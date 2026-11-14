"""坐标系账本 PyQt5 面板（挂载主窗口 QTabWidget，懒加载）。

布局（设计文档 9.1）：左＝坐标系树，中＝[查询][矢量][复核][3D] 子页，
右＝结果/属性面板，底＝状态栏健康度。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .coord_core import Ledger
from .coord_core import formatting as fmt
from .coord_core.compare import VERDICT_LABELS
from .coord_core.schema import Frame, TransformRecord
from .errors import AppError, ValidationError
from .error_ui import handle_ui_exception
from .logger import get_logger
from .ui_theme import style_primary_button, style_warning_button

logger = get_logger("coord_ledger_panel")

VERDICT_COLORS = {
    "ok": QColor("#e8f5e9"),
    "warn": QColor("#fff8e1"),
    "fail": QColor("#ffebee"),
}
_VERDICT_TEXT_COLORS = {
    "ok": QColor("#1b5e20"),
    "warn": QColor("#e65100"),
    "fail": QColor("#b71c1c"),
}


def _hbox_row(*widgets) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    for child in widgets:
        layout.addWidget(child)
    return widget


class _RecordDialog(QDialog):
    """新增/编辑变换记录（5.3 字段）。"""

    def __init__(self, frame_ids: List[str], parent=None, record: Optional[TransformRecord] = None):
        super().__init__(parent)
        self.setWindowTitle("变换记录")
        self.setMinimumWidth(420)
        form = QFormLayout(self)

        self.id_edit = QLineEdit(record.id if record else "")
        self.from_combo = QComboBox()
        self.to_combo = QComboBox()
        self.from_combo.addItems(frame_ids)
        self.to_combo.addItems(frame_ids)
        if record:
            index_from = self.from_combo.findText(record.from_frame)
            index_to = self.to_combo.findText(record.to_frame)
            if index_from >= 0:
                self.from_combo.setCurrentIndex(index_from)
            if index_to >= 0:
                self.to_combo.setCurrentIndex(index_to)
        elif len(frame_ids) >= 2:
            # 默认错开一系，便于直接看到生成的变换关系
            self.to_combo.setCurrentIndex(1)

        self.rotation_type = QComboBox()
        self.rotation_type.addItems(["rpy", "quaternion", "matrix"])
        self.rotation_value = QLineEdit(
            ",".join(str(v) for v in (record.rotation.get("value", []) if record else [0, 0, 0]))
        )
        self.rotation_order = QLineEdit(
            str(record.rotation.get("order", "ZYX") if record else "ZYX")
        )
        self.rotation_extra = QLineEdit(
            str(record.rotation.get("rotation_type", "intrinsic") if record else "intrinsic")
        )
        # CL-03: 独立四元数顺序下拉（仅 quaternion 显示）
        self.quaternion_order = QComboBox()
        self.quaternion_order.addItems(["wxyz", "xyzw"])
        self.quaternion_order.setCurrentText("wxyz")
        # CL-02: matrix 3×3 九格输入（默认单位阵）
        self.matrix_grid = []
        self.matrix_widget = QWidget()
        grid_layout = QGridLayout(self.matrix_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        for r in range(3):
            row_inputs = []
            for c in range(3):
                cell = QLineEdit("1.0" if r == c else "0.0")
                cell.setMaximumWidth(60)
                grid_layout.addWidget(cell, r, c)
                row_inputs.append(cell)
            self.matrix_grid.append(row_inputs)
        if record:
            kind = record.rotation.get("type", "rpy")
            index = self.rotation_type.findText(kind)
            if index >= 0:
                self.rotation_type.setCurrentIndex(index)

        self.translation = QLineEdit(
            ", ".join(str(v) for v in (record.translation if record else (0.0, 0.0, 0.0)))
        )
        self.sigma_t = QDoubleSpinBox()
        self.sigma_t.setDecimals(6)
        self.sigma_t.setMaximum(1e6)
        self.sigma_r = QDoubleSpinBox()
        self.sigma_r.setDecimals(4)
        self.sigma_r.setMaximum(1e9)
        if record:
            self.sigma_t.setValue(record.sigma.t)
            self.sigma_r.setValue(record.sigma.r_arcsec)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["design", "calibrated", "as_built", "obsolete"])
        if record:
            index = self.status_combo.findText(record.status)
            if index >= 0:
                self.status_combo.setCurrentIndex(index)

        self.source_edit = QLineEdit(record.source if record else "")
        self.effective_edit = QLineEdit(record.effective if record else "")
        self.note_edit = QLineEdit(record.note if record else "")

        form.addRow("id", self.id_edit)
        form.addRow("被变换系（to，原量所在系）", self.to_combo)
        form.addRow("结果系（from，变换后所在系）", self.from_combo)
        self._relation_hint = QLabel()
        self._relation_hint.setWordWrap(True)
        self._relation_hint.setStyleSheet("color: #64748b; font-size: 9pt;")
        self.from_combo.currentIndexChanged.connect(self._update_relation_hint)
        self.to_combo.currentIndexChanged.connect(self._update_relation_hint)
        self._update_relation_hint()
        form.addRow(self._relation_hint)
        form.addRow("旋转类型", self.rotation_type)
        form.addRow("旋转值（逗号分隔）", self.rotation_value)
        form.addRow("欧拉顺序 / 旋转方式", _hbox_row(self.rotation_order, self.rotation_extra))
        # CL-02: matrix 九格行
        self.matrix_row_label = QLabel("矩阵 3×3（行优先）")
        form.addRow(self.matrix_row_label, self.matrix_widget)
        # CL-03: 四元数顺序行
        self.quat_order_label = QLabel("四元数顺序")
        form.addRow(self.quat_order_label, self.quaternion_order)
        # 初始显隐
        self.rotation_type.currentIndexChanged.connect(self._on_rotation_type_changed)
        self._on_rotation_type_changed()
        form.addRow("平移（m，逗号分隔）", self.translation)
        form.addRow("σ 平移(m) / 旋转(″)", _hbox_row(self.sigma_t, self.sigma_r))
        form.addRow("status", self.status_combo)
        form.addRow("source", self.source_edit)
        form.addRow("effective", self.effective_edit)
        form.addRow("note", self.note_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _update_relation_hint(self) -> None:
        from_frame = self.from_combo.currentText()
        to_frame = self.to_combo.currentText()
        if from_frame and to_frame and from_frame != to_frame:
            self._relation_hint.setText(
                f"生成 T_{from_frame}_{to_frame}（{to_frame} → {from_frame}）："
                f"把 {to_frame} 系的量变换到 {from_frame} 系"
            )
        else:
            self._relation_hint.setText("被变换系与结果系不能相同")

    def _on_rotation_type_changed(self):
        """CL-02+CL-03: 根据旋转类型动态显隐字段。"""
        kind = self.rotation_type.currentText()
        is_matrix = (kind == "matrix")
        is_quat = (kind == "quaternion")
        is_rpy = (kind == "rpy")
        self.matrix_widget.setVisible(is_matrix)
        self.matrix_row_label.setVisible(is_matrix)
        self.rotation_value.setVisible(not is_matrix)
        self.quaternion_order.setVisible(is_quat)
        self.quat_order_label.setVisible(is_quat)
        self.rotation_order.setVisible(is_rpy)
        self.rotation_extra.setVisible(is_rpy)

    def result_payload(self) -> dict:
        kind = self.rotation_type.currentText()
        if kind == "matrix":
            # CL-02: 从九格读取 9 元
            values = []
            for r in range(3):
                for c in range(3):
                    values.append(float(self.matrix_grid[r][c].text().strip() or "0"))
        else:
            values = [float(part.strip()) for part in self.rotation_value.text().split(",") if part.strip()]
        rotation: dict = {"type": kind, "value": values}
        if kind == "rpy":
            rotation["order"] = self.rotation_order.text().strip() or "ZYX"
            rotation["rotation_type"] = self.rotation_extra.text().strip() or "intrinsic"
            rotation["unit"] = "deg"
        elif kind == "quaternion":
            # CL-03: 用独立下拉而非 rotation_extra
            rotation["order"] = self.quaternion_order.currentText()
        translation = [float(part.strip()) for part in self.translation.text().split(",") if part.strip()]
        payload = {
            "id": self.id_edit.text().strip(),
            "from": self.from_combo.currentText(),
            "to": self.to_combo.currentText(),
            "rotation": rotation,
            "translation": translation,
            "sigma": {"t": self.sigma_t.value(), "r_arcsec": self.sigma_r.value()},
            "status": self.status_combo.currentText(),
            "source": self.source_edit.text().strip(),
            "effective": self.effective_edit.text().strip(),
            "note": self.note_edit.text().strip(),
        }
        return payload


class _FrameDialog(QDialog):
    """新建坐标系：属性 + 父系 + 父系下的坐标原点与姿态（生成安装关系）。"""

    def __init__(self, parent_frame_ids: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建坐标系")
        self.setMinimumWidth(440)
        form = QFormLayout(self)

        self.id_edit = QLineEdit()
        self.name_edit = QLineEdit()
        self.axis_combo = QComboBox()
        self.axis_combo.addItems(["Z_UP", "Z_FORWARD", "Y_UP", "NED", "ENU"])
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["m", "mm"])
        self.definition_edit = QLineEdit()
        self.definition_edit.setPlaceholderText("各轴物理定义，如：X 沿飞行方向，Z 指向地心")

        self.parent_combo = QComboBox()
        self.parent_combo.addItem("（无 — 独立/根坐标系）", None)
        for frame_id in parent_frame_ids:
            self.parent_combo.addItem(frame_id, frame_id)

        self.origin_edits = [self._coord_spin() for _ in range(3)]
        self.rpy_edits = [self._angle_spin() for _ in range(3)]

        form.addRow("id（英文/下划线）", self.id_edit)
        form.addRow("中文名称", self.name_edit)
        form.addRow("轴向约定", self.axis_combo)
        form.addRow("单位", self.unit_combo)
        form.addRow("各轴定义", self.definition_edit)
        form.addRow("父系", self.parent_combo)
        form.addRow("坐标原点（父系下，m）", _hbox_row(*self.origin_edits))
        form.addRow("相对父系姿态 RPY（°）", _hbox_row(*self.rpy_edits))

        self._parent_hint = QLabel(
            "选择父系后将自动生成安装变换 T_<父系>_<新系>_design（RPY 为 ZYX 内旋）"
        )
        self._parent_hint.setWordWrap(True)
        self._parent_hint.setStyleSheet("color: #64748b; font-size: 9pt;")
        form.addRow(self._parent_hint)
        self.parent_combo.currentIndexChanged.connect(self._on_parent_changed)
        self._on_parent_changed()

        self.note_edit = QLineEdit()
        form.addRow("备注", self.note_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _coord_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(6)
        spin.setRange(-1e6, 1e6)
        spin.setSingleStep(0.1)
        return spin

    @staticmethod
    def _angle_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(4)
        spin.setRange(-360.0, 360.0)
        spin.setSingleStep(1.0)
        return spin

    def _on_parent_changed(self) -> None:
        has_parent = self.parent_combo.currentData() is not None
        for spin in self.origin_edits + self.rpy_edits:
            spin.setEnabled(has_parent)

    def result_payload(self) -> dict:
        frame_payload = {
            "id": self.id_edit.text().strip(),
            "axis": self.axis_combo.currentText(),
            "unit": self.unit_combo.currentText(),
        }
        if self.name_edit.text().strip():
            frame_payload["name"] = self.name_edit.text().strip()
        if self.definition_edit.text().strip():
            frame_payload["definition"] = self.definition_edit.text().strip()
        if self.note_edit.text().strip():
            frame_payload["note"] = self.note_edit.text().strip()
        parent_id = self.parent_combo.currentData()
        origin = [spin.value() for spin in self.origin_edits]
        rpy = [spin.value() for spin in self.rpy_edits]
        return {
            "frame": frame_payload,
            "parent": parent_id,
            "origin": origin,
            "rpy_deg": rpy,
        }


class CoordinateLedgerPanel(QWidget):
    """坐标系账本面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ledger: Optional[Ledger] = None
        self._3d_view = None
        self._3d_widget = None
        self._3d_matplotlib = None
        self._3d_loaded = False
        self._3d_dirty = False
        self._3d_unreachable: List[str] = []
        self._init_ui()
        self._open_sample()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def showEvent(self, event):
        """首次显示时按窗口实际宽度重设三栏尺寸，避免默认均分挤占两侧。"""
        super().showEvent(event)
        if getattr(self, "_splitter_initialized", False):
            return
        self._splitter_initialized = True
        total = self.splitter.width()
        weights = [280, 660, 320]
        if total > 800:
            scale = total / sum(weights)
            sizes = [max(200, int(weight * scale)) for weight in weights]
            self.splitter.setSizes(sizes)

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        toolbar = QHBoxLayout()
        title = QLabel("坐标系账本")
        title.setObjectName("coord_title")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        title.setFont(font)
        toolbar.addWidget(title)
        toolbar.addStretch(1)

        self.btn_open = QPushButton("打开…")
        self.btn_new = QPushButton("新建")
        self.btn_template = QPushButton("生成模板")
        self.btn_save = QPushButton("保存")
        self.btn_save_as = QPushButton("另存为…")
        self.btn_add_frame = QPushButton("新建坐标系")
        self.btn_add_transform = QPushButton("新建变换")
        self.btn_import_csv = QPushButton("批量导入CSV")
        self.btn_delete = QPushButton("删除选中记录")
        style_primary_button(self.btn_save)
        style_warning_button(self.btn_delete)
        for button in (self.btn_open, self.btn_new, self.btn_template,
                       self.btn_save_as, self.btn_add_frame, self.btn_add_transform):
            button.setStyleSheet(
                "QPushButton { padding: 4px 10px; border: 1px solid #b6c2cf; "
                "border-radius: 4px; background: #f4f7fa; }"
                "QPushButton:hover { background: #e6eef6; }"
            )
        for button in (self.btn_open, self.btn_new, self.btn_template,
                       self.btn_save, self.btn_save_as,
                       self.btn_add_frame, self.btn_add_transform,
                       self.btn_import_csv, self.btn_delete):
            toolbar.addWidget(button)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        self.splitter = splitter

        # 左：坐标系树
        left_box = QGroupBox("账本结构")
        left_layout = QVBoxLayout(left_box)
        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("视图"))
        self.tree_mode = QComboBox()
        self.tree_mode.addItems(["层级树", "平铺"])
        self.tree_mode.currentIndexChanged.connect(lambda _index: self._refresh_tree())
        view_row.addWidget(self.tree_mode)
        view_row.addStretch(1)
        left_layout.addLayout(view_row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["条目"])
        self.tree.setColumnWidth(0, 200)
        self.tree.currentItemChanged.connect(self._on_tree_selection)
        left_layout.addWidget(self.tree)
        splitter.addWidget(left_box)

        # 中：子页
        center_box = QGroupBox("功能")
        center_layout = QVBoxLayout(center_box)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_subtab_changed)
        center_layout.addWidget(self.tabs)
        splitter.addWidget(center_box)

        self.query_tab = self._build_query_tab()
        self.vector_tab = self._build_vector_tab()
        self.review_tab = self._build_review_tab()
        self.three_d_tab = QWidget()
        three_d_layout = QVBoxLayout(self.three_d_tab)
        three_d_top = QHBoxLayout()
        self.three_d_hint = QLabel("3D 视口（首次打开时加载 PyVista，失败则降级 matplotlib）")
        self.three_d_hint.setWordWrap(True)
        self.btn_refresh_3d = QPushButton("刷新 3D")
        self.btn_refresh_3d.setStyleSheet(
            "QPushButton { padding: 4px 12px; border: 1px solid #b6c2cf; "
            "border-radius: 4px; background: #f4f7fa; }"
            "QPushButton:hover { background: #e6eef6; }"
        )
        self.btn_refresh_3d.clicked.connect(self._refresh_3d)
        three_d_top.addWidget(self.three_d_hint, 1)
        three_d_top.addWidget(self.btn_refresh_3d, 0, Qt.AlignTop)
        three_d_layout.addLayout(three_d_top)
        self.tabs.addTab(self.query_tab, "查询")
        self.tabs.addTab(self.vector_tab, "矢量")
        self.tabs.addTab(self.review_tab, "复核")
        self.tabs.addTab(self.three_d_tab, "3D")

        # 右：结果/属性
        right_box = QGroupBox("属性 / 结果")
        right_layout = QVBoxLayout(right_box)
        self.attribute_text = QPlainTextEdit()
        self.attribute_text.setReadOnly(True)
        right_layout.addWidget(self.attribute_text, 2)
        right_layout.addWidget(QLabel("结果 / 结论"))
        self.conclusion_text = QPlainTextEdit()
        self.conclusion_text.setReadOnly(True)
        right_layout.addWidget(self.conclusion_text, 1)
        splitter.addWidget(right_box)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 3)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)
        left_box.setMinimumWidth(200)
        right_box.setMinimumWidth(240)
        center_box.setMinimumWidth(360)
        self._splitter_sizes = [280, 660, 320]
        splitter.setSizes(self._splitter_sizes)
        root.addWidget(splitter, 1)

        self.status_label = QLabel("未加载账本")
        root.addWidget(self.status_label)

        self.btn_open.clicked.connect(self._open_ledger)
        self.btn_new.clicked.connect(self._new_ledger)
        self.btn_template.clicked.connect(self._write_template)
        self.btn_save.clicked.connect(self._save_ledger)
        self.btn_save_as.clicked.connect(self._save_as_ledger)
        self.btn_add_frame.clicked.connect(self._add_frame)
        self.btn_add_transform.clicked.connect(self._add_transform)
        self.btn_import_csv.clicked.connect(self._import_transforms_csv)
        self.btn_delete.clicked.connect(self._delete_selected)

    def _build_query_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        controls = QHBoxLayout()
        self.query_from = QComboBox()
        self.query_to = QComboBox()
        self.query_status = QComboBox()
        self.query_status.addItem("当前有效值", None)
        for status in ("design", "calibrated", "as_built", "obsolete"):
            self.query_status.addItem(status, status)
        self.query_strategy = QComboBox()
        self.query_strategy.addItems(["min_error", "min_hops"])
        btn_query = QPushButton("查询变换")
        btn_budget = QPushButton("误差预算")
        style_primary_button(btn_query)
        controls.addWidget(QLabel("源系（被变换量）"))
        controls.addWidget(self.query_from)
        controls.addWidget(QLabel("→ 目标系（结果）"))
        controls.addWidget(self.query_to)
        controls.addWidget(QLabel("状态"))
        controls.addWidget(self.query_status)
        controls.addWidget(QLabel("策略"))
        controls.addWidget(self.query_strategy)
        controls.addWidget(btn_query)
        controls.addWidget(btn_budget)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.query_meta = QLabel("—")
        self.query_meta.setWordWrap(True)
        layout.addWidget(self.query_meta)

        self.matrix_table = QTableWidget(4, 4)
        self.matrix_table.setVerticalHeaderLabels(["r1", "r2", "r3", "r4"])
        self.matrix_table.setHorizontalHeaderLabels(["c1", "c2", "c3", "c4"])
        self.matrix_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.matrix_table.setMaximumHeight(140)
        layout.addWidget(QLabel("齐次矩阵 T_target_source"))
        layout.addWidget(self.matrix_table)

        self.budget_table = QTableWidget(0, 6)
        self.budget_table.setHorizontalHeaderLabels(
            ["路径段", "平移σ(mm)", "旋转σ(″)", "方差占比", "贡献(″)", "标注"]
        )
        self.budget_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(QLabel("误差预算分解"))
        layout.addWidget(self.budget_table, 1)

        btn_query.clicked.connect(self._run_query)
        btn_budget.clicked.connect(self._run_budget)
        return widget

    def _build_vector_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        controls = QHBoxLayout()
        self.vector_edit = QLineEdit("0, 0, 1")
        self.vector_frame = QComboBox()
        btn_vector = QPushButton("矢量跨系表达")
        style_primary_button(btn_vector)
        controls.addWidget(QLabel("矢量（x, y, z）"))
        controls.addWidget(self.vector_edit)
        controls.addWidget(QLabel("所在系"))
        controls.addWidget(self.vector_frame)
        controls.addWidget(btn_vector)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.vector_table = QTableWidget(0, 4)
        self.vector_table.setHorizontalHeaderLabels(["坐标系", "x", "y", "z"])
        self.vector_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.vector_table, 1)
        btn_vector.clicked.connect(self._run_vector)
        return widget

    def _build_review_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        compare_box = QGroupBox("D7 变换对比（design vs calibrated）")
        compare_layout = QHBoxLayout(compare_box)
        self.compare_baseline = QComboBox()
        self.compare_candidate = QComboBox()
        btn_compare = QPushButton("对比两条记录")
        btn_status_pair = QPushButton("对比当前 design/calibrated")
        style_primary_button(btn_compare)
        compare_layout.addWidget(QLabel("基准"))
        compare_layout.addWidget(self.compare_baseline)
        compare_layout.addWidget(QLabel("对比"))
        compare_layout.addWidget(self.compare_candidate)
        compare_layout.addWidget(btn_compare)
        compare_layout.addWidget(btn_status_pair)
        compare_layout.addStretch(1)
        layout.addWidget(compare_box)

        self.compare_table = QTableWidget(0, 6)
        self.compare_table.setHorizontalHeaderLabels(["分量", "偏差 δ", "σ", "z=δ/σ", "判定", "备注"])
        self.compare_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.compare_table, 2)

        action_row = QHBoxLayout()
        btn_loop = QPushButton("D8 环路闭合自检")
        btn_limits = QPushButton("D9 限值符合性")
        btn_health = QPushButton("账本健康度")
        action_row.addWidget(btn_loop)
        action_row.addWidget(btn_limits)
        action_row.addWidget(btn_health)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.review_table = QTableWidget(0, 5)
        self.review_table.setHorizontalHeaderLabels(["类型", "对象", "计算值", "限值/阈值", "判定"])
        self.review_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.review_table, 2)

        btn_compare.clicked.connect(self._run_compare)
        btn_status_pair.clicked.connect(self._run_status_pair_compare)
        btn_loop.clicked.connect(self._run_loop)
        btn_limits.clicked.connect(self._run_limits)
        btn_health.clicked.connect(self._run_health)
        return widget

    # ------------------------------------------------------------------
    # 账本装载
    # ------------------------------------------------------------------

    def _open_sample(self) -> None:
        """启动：优先恢复上次打开/保存的账本，其次载入示例账本。"""
        from .coord_core import storage as coord_storage

        last = coord_storage.load_last_ledger()
        if last:
            try:
                self.ledger = Ledger.load(last)
                self._refresh_all()
                self._set_status(f"已恢复上次账本 {os.path.basename(last)}")
                return
            except (AppError, ValueError, OSError) as exc:
                logger.warning("恢复上次账本失败: %s", exc)
        self.ledger = Ledger.sample()
        self._refresh_all()
        self._set_status("示例账本已加载")
        self._show_sample_banner()  # CL-01

    def _show_sample_banner(self):
        """CL-01: 示例账本只读横幅 + 清空并开始按钮。"""
        if self.__dict__.get('_sample_banner'):
            return
        try:
            from PyQt5.QtWidgets import QLabel, QHBoxLayout, QPushButton
            banner = QWidget()
            banner.setStyleSheet('background: #fefce8; border-bottom: 2px solid #ca8a04;')
            layout = QHBoxLayout(banner)
            layout.setContentsMargins(8, 4, 8, 4)
            msg = QLabel('⚠️ 当前为示例账本（只读），修改不会保存。')
            msg.setStyleSheet('color: #a16207; font-weight: bold; font-size: 10pt;')
            layout.addWidget(msg, 1)
            btn_clear = QPushButton('清空并开始')
            btn_clear.setStyleSheet('background: #ca8a04; color: white; padding: 4px 12px; border-radius: 4px;')
            btn_clear.clicked.connect(self._clear_and_start)
            layout.addWidget(btn_clear)
            parent_layout = self.layout()
            if parent_layout is not None:
                parent_layout.insertWidget(0, banner)
            self._sample_banner = banner
        except Exception:
            pass

    def _clear_and_start(self):
        """CL-01: 清空示例并开始新账本。"""
        self.ledger = Ledger.blank()
        self.ledger.read_only = False
        if self.__dict__.get('_sample_banner'):
            self._sample_banner.hide()
        self._refresh_all()
        self._set_status('已清空，可开始编辑新账本')

    def _open_ledger(self) -> None:
        from PyQt5.QtWidgets import QFileDialog

        filepath, _ = QFileDialog.getOpenFileName(
            self, "打开坐标系账本", "", "坐标系账本 (*.json)"
        )
        if not filepath:
            return
        try:
            self.ledger = Ledger.load(filepath)
        except (AppError, OSError, ValueError) as exc:
            handle_ui_exception(self, logger, "打开账本", exc)
            return
        from .coord_core import storage as coord_storage

        coord_storage.remember_last_ledger(filepath)
        # CL-01: 打开真实账本后隐藏示例横幅
        if self.__dict__.get('_sample_banner'):
            self._sample_banner.hide()
        self._refresh_all()
        self._set_status(f"已加载 {os.path.basename(filepath)}")

    def _new_ledger(self) -> None:
        name, ok = QInputDialog.getText(self, "新建账本", "账本名称：", text="新建坐标系账本")
        if not ok:
            return
        self.ledger = Ledger.blank(name or "新建坐标系账本")
        self._refresh_all()
        self._set_status("已新建空白账本")

    def _write_template(self) -> None:
        from PyQt5.QtWidgets import QFileDialog

        filepath, _ = QFileDialog.getSaveFileName(
            self, "生成模板账本", "ledger_template_v1.0.json", "坐标系账本 (*.json)"
        )
        if not filepath:
            return
        try:
            self.ledger.export_template(filepath, sample=True)
        except (AppError, OSError, ValueError) as exc:
            handle_ui_exception(self, logger, "生成模板", exc)
            return
        self._set_status(f"模板已写入 {os.path.basename(filepath)}")

    def _save_ledger(self) -> None:
        if self.ledger is None:
            return
        if not self.ledger.path:
            self._save_as_ledger()
            return
        self._write_ledger(self.ledger.path, announce=True)

    def _save_as_ledger(self) -> None:
        if self.ledger is None:
            return
        from PyQt5.QtWidgets import QFileDialog

        default_name = f"ledger_{self.ledger.meta.name}_v{self.ledger.meta.version}.json"
        default_dir = os.path.dirname(
            self.ledger.path or os.path.join(os.getcwd(), default_name)
        )
        filepath, _ = QFileDialog.getSaveFileName(
            self, "另存为坐标系账本", os.path.join(default_dir, default_name),
            "坐标系账本 (*.json)",
        )
        if not filepath:
            return
        self._write_ledger(filepath, announce=True)

    def _write_ledger(self, target: str, announce: bool = False) -> bool:
        from .coord_core import storage as coord_storage

        try:
            self.ledger.save(target)
            coord_storage.remember_last_ledger(target)
        except (AppError, OSError, ValueError) as exc:
            handle_ui_exception(self, logger, "保存账本", exc)
            return False
        if announce:
            # 入账后自检（设计文档 6.5 流程 A/B）
            try:
                loops = self.ledger.loop_closure()
                self._set_status(f"已保存 {os.path.basename(target)} │ {loops.summary()}")
                self.conclusion_text.setPlainText(
                    "保存后自动环路自检\n" + fmt.loop_report_text(loops)
                )
            except Exception as exc:  # 自检失败不阻塞保存
                logger.warning("保存后环路自检失败: %s", exc)
        else:
            self._set_status(f"已自动保存 {os.path.basename(target)}")
        return True

    def _autosave(self) -> None:
        """账本变更后自动落盘，防止误关丢失（无路径时落到工作账本）。"""
        if self.ledger is None:
            return
        if not self.ledger.path:
            from .coord_core import storage as coord_storage

            self.ledger.path = coord_storage.default_work_ledger_path()
        self._write_ledger(self.ledger.path, announce=False)

    # ------------------------------------------------------------------
    # 录账
    # ------------------------------------------------------------------

    def _add_frame(self) -> None:
        if self.ledger is None:
            return
        parent_ids = [frame.id for frame in self.ledger.frames()]
        dialog = _FrameDialog(parent_ids, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        payload = dialog.result_payload()
        record = None
        try:
            frame = Frame.from_dict(payload["frame"])
            if frame.id in self.ledger.document.frame_map():
                raise ValidationError(f"坐标系 id 已存在: {frame.id}")
            if payload["parent"]:
                record = TransformRecord.from_dict({
                    "id": f"T_{payload['parent']}_{frame.id}_design",
                    "from": payload["parent"],
                    "to": frame.id,
                    "rotation": {
                        "type": "rpy",
                        "value": payload["rpy_deg"],
                        "order": "ZYX",
                        "rotation_type": "intrinsic",
                        "unit": "deg",
                    },
                    "translation": payload["origin"],
                    "status": "design",
                    "note": "新建坐标系时生成的安装关系",
                })
                if record.id in self.ledger.document.transform_map():
                    raise ValidationError(f"变换 id 已存在: {record.id}")
        except (AppError, ValueError) as exc:
            handle_ui_exception(self, logger, "新建坐标系", exc)
            return
        self.ledger.document.frames.append(frame)
        if record is not None:
            self.ledger.document.transforms.append(record)
        self._refresh_all()
        if record is not None:
            self.conclusion_text.setPlainText(
                f"已新建坐标系 {frame.id}（父系 {payload['parent']}）\n"
                f"安装原点（父系坐标）: {fmt.fmt_translation(payload['origin'])}\n"
                f"相对父系姿态: {fmt.fmt_euler(payload['rpy_deg'])}\n"
                f"已生成安装变换 {record.id}"
            )
            self._set_status(
                f"已新建坐标系 {frame.id}（父系 {payload['parent']}），生成 {record.id}"
            )
        else:
            self.conclusion_text.setPlainText(
                f"已新建坐标系 {frame.id}（独立/根坐标系，未定义父系）"
            )
            self._set_status(f"已新建坐标系 {frame.id}")
        self._autosave()

    def _add_transform(self) -> None:
        if self.ledger is None:
            return
        frame_ids = [frame.id for frame in self.ledger.frames()]
        if len(frame_ids) < 2:
            QMessageBox.information(self, "提示", "至少需要两个坐标系才能新建变换")
            return
        dialog = _RecordDialog(frame_ids, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        try:
            record = TransformRecord.from_dict(dialog.result_payload())
            self.ledger.document.transforms.append(record)
            self.ledger.validate()
        except (AppError, ValueError) as exc:
            handle_ui_exception(self, logger, "新建变换", exc)
            return
        self._refresh_all()
        self._set_status(f"已新建变换 {record.id}")
        self._autosave()
        # 流程 B：录入 calibrated 后自动与 design 对比
        if record.status == "calibrated":
            try:
                comparison = self.ledger.compare_status_pair(
                    record.from_frame, record.to_frame,
                    baseline_status="design", candidate_status="calibrated",
                )
                self._show_comparison(comparison)
                self._set_status(
                    f"已新建 {record.id}，自动对比 design：{comparison.overall_label}"
                )
            except (AppError, ValueError) as exc:
                self.conclusion_text.setPlainText(
                    f"已新建 {record.id}，但自动对比未执行：{exc}"
                )

    def _import_transforms_csv(self) -> None:
        if self.ledger is None:
            return
        from PyQt5.QtWidgets import QFileDialog

        filepath, _ = QFileDialog.getOpenFileName(
            self, "批量导入变换 CSV", "", "CSV (*.csv)"
        )
        if not filepath:
            return
        try:
            added = self.ledger.import_transforms_csv(filepath)
        except (AppError, ValueError, OSError) as exc:
            handle_ui_exception(self, logger, "批量导入", exc)
            return
        self._refresh_all()
        self._set_status(f"已导入 {len(added)} 条变换记录")
        self._autosave()

    def _delete_selected(self) -> None:
        if self.ledger is None:
            return
        item = self.tree.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请先在左侧树中选中要删除的条目")
            return
        payload = item.data(0, Qt.UserRole)
        if not isinstance(payload, dict):
            QMessageBox.information(self, "提示", "请先在左侧树中选中要删除的条目")
            return
        kind = payload.get("kind")
        entry_id = payload.get("id")
        if kind == "transform":
            if QMessageBox.question(
                self, "删除变换记录",
                f"确认删除变换记录 {entry_id}？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            self.ledger.document.transforms = [
                record for record in self.ledger.document.transforms
                if record.id != entry_id
            ]
            self._set_status(f"已删除变换记录 {entry_id}")
        elif kind == "limit":
            if QMessageBox.question(
                self, "删除限值",
                f"确认删除限值 {entry_id}？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            self.ledger.document.limits = [
                limit for limit in self.ledger.document.limits
                if limit.id != entry_id
            ]
            self._set_status(f"已删除限值 {entry_id}")
        elif kind == "frame":
            related = [
                record.id for record in self.ledger.document.transforms
                if record.from_frame == entry_id or record.to_frame == entry_id
            ]
            related_limits = [
                limit.id for limit in self.ledger.document.limits
                if entry_id in limit.frames
            ]
            detail = ""
            if related:
                detail += f"\n关联变换 {len(related)} 条：{', '.join(related)}（一并删除）"
            if related_limits:
                detail += f"\n关联限值 {len(related_limits)} 条：{', '.join(related_limits)}（一并删除）"
            if QMessageBox.question(
                self, "删除坐标系",
                f"确认删除坐标系 {entry_id}？{detail}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            self.ledger.document.frames = [
                frame for frame in self.ledger.document.frames
                if frame.id != entry_id
            ]
            self.ledger.document.transforms = [
                record for record in self.ledger.document.transforms
                if record.from_frame != entry_id and record.to_frame != entry_id
            ]
            self.ledger.document.limits = [
                limit for limit in self.ledger.document.limits
                if entry_id not in limit.frames
            ]
            self._set_status(f"已删除坐标系 {entry_id}（含 {len(related)} 条关联变换）")
        else:
            return
        self._refresh_all()
        self._autosave()

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------

    def _refresh_all(self) -> None:
        if self.ledger is not None:
            self.ledger.invalidate()
        self._refresh_tree()
        self._refresh_combos()
        self._refresh_status()
        self._3d_dirty = True
        # 当前正停在 3D 页时立即同步（删除/新建后不残留旧场景）
        if self._3d_loaded and self.tabs.currentWidget() is self.three_d_tab:
            self._refresh_3d()

    def _refresh_tree(self) -> None:
        self.tree.clear()
        if self.ledger is None:
            return
        hierarchical = self.tree_mode.currentIndex() == 0
        if hierarchical:
            self._populate_tree_hierarchical()
        else:
            self._populate_tree_flat()
        self.tree.expandAll()

    # --- 层级树：按安装关系（from=父系，to=子系）展开 ---

    def _populate_tree_hierarchical(self) -> None:
        ledger = self.ledger
        meta = ledger.meta
        frames = ledger.frames()
        frame_ids = [frame.id for frame in frames]
        frame_map = ledger.document.frame_map()

        # 有效记录构成的无向邻接（obsolete 不参与层级）
        adjacency = {frame_id: set() for frame_id in frame_ids}
        for record in ledger.transforms():
            if record.status == "obsolete":
                continue
            if record.from_frame in adjacency and record.to_frame in adjacency:
                adjacency[record.from_frame].add(record.to_frame)
                adjacency[record.to_frame].add(record.from_frame)

        # BFS 生成树 → 每系唯一父系；根缺省取 body，否则取首系
        root_id = "body" if "body" in adjacency else (frame_ids[0] if frame_ids else None)
        parent_of: Dict[str, Optional[str]] = {}
        if root_id is not None:
            parent_of[root_id] = None
            queue = [root_id]
            while queue:
                current = queue.pop(0)
                for neighbor in sorted(adjacency[current]):
                    if neighbor not in parent_of:
                        parent_of[neighbor] = current
                        queue.append(neighbor)
        children_of: Dict[str, List[str]] = {frame_id: [] for frame_id in frame_ids}
        unattached: List[str] = []
        for frame_id in frame_ids:
            parent = parent_of.get(frame_id)
            if parent is None:
                if frame_id != root_id:
                    unattached.append(frame_id)
            else:
                children_of[parent].append(frame_id)

        # 记录按被变换系（to）归组，挂在对应坐标系节点下（任意两系均可建立变换）
        records_of: Dict[str, List] = {}
        for record in ledger.transforms():
            records_of.setdefault(record.to_frame, []).append(record)
        for items in records_of.values():
            items.sort(key=lambda r: (0 if r.status != "obsolete" else 1, r.status, r.id))

        def frame_node(frame_id: str) -> QTreeWidgetItem:
            frame = frame_map[frame_id]
            label = frame_id + (f" · {frame.name}" if frame.name else "")
            node = QTreeWidgetItem([label])
            node.setData(0, Qt.UserRole, {"kind": "frame", "id": frame_id})
            for record in records_of.get(frame_id, []):
                current = ledger.current_record(record.from_frame, record.to_frame)
                is_current = current is not None and current.id == record.id
                record_node = QTreeWidgetItem([("★ " if is_current else "") + record.id])
                record_node.setData(0, Qt.UserRole, {"kind": "transform", "id": record.id})
                node.addChild(record_node)
            for child_id in sorted(children_of.get(frame_id, [])):
                node.addChild(frame_node(child_id))
            return node

        ledger_root = QTreeWidgetItem([meta.name])
        ledger_root.setData(0, Qt.UserRole, {"kind": "ledger"})
        if root_id is not None:
            ledger_root.addChild(frame_node(root_id))
        for frame_id in unattached:
            node = QTreeWidgetItem([f"{frame_id}（未连通）"])
            node.setData(0, Qt.UserRole, {"kind": "frame", "id": frame_id})
            ledger_root.addChild(node)

        limits_root = QTreeWidgetItem(["限值"])
        for limit in ledger.limits():
            limits_root.addChild(self._limit_node(limit))

        self.tree.addTopLevelItems([ledger_root, limits_root])

    # --- 平铺：按类型分组 ---

    def _populate_tree_flat(self) -> None:
        frames_root = QTreeWidgetItem(["坐标系"])
        for frame in self.ledger.frames():
            node = QTreeWidgetItem([frame.id + (f" · {frame.name}" if frame.name else "")])
            node.setData(0, Qt.UserRole, {"kind": "frame", "id": frame.id})
            frames_root.addChild(node)
        transforms_root = QTreeWidgetItem(["变换记录"])
        for record in self.ledger.transforms():
            node = QTreeWidgetItem([record.id])
            node.setData(0, Qt.UserRole, {"kind": "transform", "id": record.id})
            transforms_root.addChild(node)
        limits_root = QTreeWidgetItem(["限值"])
        for limit in self.ledger.limits():
            limits_root.addChild(self._limit_node(limit))
        self.tree.addTopLevelItems([frames_root, transforms_root, limits_root])

    @staticmethod
    def _limit_node(limit) -> QTreeWidgetItem:
        node = QTreeWidgetItem([limit.id])
        node.setData(0, Qt.UserRole, {"kind": "limit", "id": limit.id})
        return node

    def _refresh_combos(self) -> None:
        frame_ids = [frame.id for frame in (self.ledger.frames() if self.ledger else [])]
        for combo in (self.query_from, self.query_to, self.vector_frame):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(frame_ids)
            index = combo.findText(current)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        # 查询默认落在一条实际存在的变换关系上（避免 body→body 恒等自查询）
        degenerate = (
            self.query_from.currentText() == self.query_to.currentText()
            or not self.query_from.currentText()
        )
        if len(frame_ids) >= 2 and degenerate:
            pair = None
            for record in (self.ledger.transforms() if self.ledger else []):
                if record.status != "obsolete":
                    pair = (record.to_frame, record.from_frame)  # source → target
                    break
            if pair is None:
                pair = (frame_ids[0], frame_ids[1])
            self.query_from.setCurrentText(pair[0])
            self.query_to.setCurrentText(pair[1])
        record_ids = [record.id for record in (self.ledger.transforms() if self.ledger else [])]
        for combo in (self.compare_baseline, self.compare_candidate):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(record_ids)
            index = combo.findText(current)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        if record_ids:
            design = next((r.id for r in self.ledger.transforms() if r.status == "design"), record_ids[0])
            calibrated = next((r.id for r in self.ledger.transforms() if r.status == "calibrated"), record_ids[-1])
            self.compare_baseline.setCurrentText(design)
            self.compare_candidate.setCurrentText(calibrated)

    def _refresh_status(self) -> None:
        if self.ledger is None:
            self.status_label.setText("未加载账本")
            return
        try:
            self.status_label.setText(self.ledger.health_summary())
        except Exception as exc:
            self.status_label.setText(f"健康度计算失败：{exc}")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        window = self.window()
        if isinstance(window, QMainWindow) and hasattr(window, "status_label"):
            window.status_label.setText(text)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _on_tree_selection(self, current, _previous) -> None:
        if current is None or self.ledger is None:
            return
        payload = current.data(0, Qt.UserRole)
        if not isinstance(payload, dict):
            return
        kind = payload.get("kind")
        if kind == "ledger":
            meta = self.ledger.meta
            self.attribute_text.setPlainText(fmt.ledger_detail(
                meta,
                frame_count=len(self.ledger.frames()),
                transform_count=len(self.ledger.transforms()),
                limit_count=len(self.ledger.limits()),
            ))
        elif kind == "frame":
            frame = self.ledger.document.frame_map().get(payload["id"])
            if frame:
                self.attribute_text.setPlainText(fmt.frame_detail(frame))
        elif kind == "transform":
            record = self.ledger.document.transform_map().get(payload["id"])
            if record:
                self.attribute_text.setPlainText(fmt.transform_detail(record))
        elif kind == "limit":
            for limit in self.ledger.limits():
                if limit.id == payload["id"]:
                    self.attribute_text.setPlainText(fmt.limit_detail(limit))

    def _on_subtab_changed(self, index: int) -> None:
        if self.tabs.tabText(index) == "3D":
            if not self._3d_loaded:
                self._init_3d()
            elif self._3d_dirty:
                self._refresh_3d()

    def _run_query(self) -> None:
        if self.ledger is None:
            return
        source = self.query_from.currentText()
        target = self.query_to.currentText()
        if not source or not target:
            return
        status = self.query_status.currentData()
        strategy = self.query_strategy.currentText()
        try:
            result = self.ledger.query(target, source, status=status, strategy=strategy)
        except (AppError, ValueError) as exc:
            handle_ui_exception(self, logger, "变换查询", exc)
            return
        self.query_meta.setText(
            f"变换   T_{result.target}_{result.source}"
            f"（{result.source} → {result.target}）\n"
            f"路径   {fmt.fmt_path(result.path)}\n"
            f"当前值来源   {result.source_line()}\n"
            f"误差   {fmt.fmt_sigma(result.sigma_t_m, result.sigma_r_arcsec)}\n"
            f"姿态   {fmt.fmt_euler(result.rpy_deg, order='ZYX', rotation_type='intrinsic', unit='deg')}\n"
            f"       {fmt.fmt_quaternion(result.quaternion, order='wxyz')}"
        )
        for row in range(4):
            for col in range(4):
                item = QTableWidgetItem(fmt.fmt_fixed(result.matrix[row, col], 6))
                item.setTextAlignment(Qt.AlignCenter)
                self.matrix_table.setItem(row, col, item)
        self.conclusion_text.setPlainText(fmt.query_result_text(result))
        self._set_status(f"查询 {result.target} ← {result.source} 完成")
        self._update_3d_path(result.path)

    def _update_3d_path(self, path) -> None:
        """E4：查询路径高亮（3D 已加载时刷新）。"""
        if not self._3d_loaded or self._3d_view is None:
            return
        self._3d_view.set_highlight_path(path)
        self._render_3d()

    def _run_budget(self) -> None:
        if self.ledger is None:
            return
        source = self.query_from.currentText()
        target = self.query_to.currentText()
        try:
            budget = self.ledger.error_budget(source, target)
        except (AppError, ValueError) as exc:
            handle_ui_exception(self, logger, "误差预算", exc)
            return
        rows = budget.to_rows()
        self.budget_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row["路径段"], fmt.fmt_fixed(row['平移σ(mm)'], 3), fmt.fmt_fixed(row['旋转σ(″)'], 2),
                f"{row['方差占比']:.0%}", fmt.fmt_fixed(row['对最终指向贡献(″)'], 2), row["主导段"],
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if row_index == len(rows) - 1:
                    item.setFont(QFont("", -1, QFont.Bold))
                self.budget_table.setItem(row_index, col_index, item)
        from .coord_core.error_budget import FOOTER_NOTE

        self.conclusion_text.setPlainText(
            fmt.error_budget_result_text(budget) + "\n\n" + FOOTER_NOTE
        )

    def _run_vector(self) -> None:
        if self.ledger is None:
            return
        try:
            values = [float(part.strip()) for part in self.vector_edit.text().split(",")]
            if len(values) != 3:
                raise ValueError("矢量必须是 3 个分量")
            expressions = self.ledger.express_vector(
                values, self.vector_frame.currentText(), to_all=True
            )
        except (AppError, ValueError) as exc:
            handle_ui_exception(self, logger, "矢量跨系", exc)
            return
        self.vector_table.setRowCount(len(expressions))
        for row_index, item in enumerate(expressions):
            cells = [item.frame,
                     fmt.fmt_fixed(item.vector[0], 6),
                     fmt.fmt_fixed(item.vector[1], 6),
                     fmt.fmt_fixed(item.vector[2], 6)]
            for col_index, value in enumerate(cells):
                table_item = QTableWidgetItem(value)
                self.vector_table.setItem(row_index, col_index, table_item)
        self._set_status("矢量跨系表达完成")
        self._update_3d_vectors(values, self.vector_frame.currentText())

    def _update_3d_vectors(self, values, source_frame: str) -> None:
        """E6：输入矢量箭头呈现（3D 已加载时刷新）。"""
        if not self._3d_loaded or self._3d_view is None:
            return
        try:
            import numpy as np

            self._3d_view.clear_vectors()
            graph = self.ledger.build_graph()
            for frame in self.ledger.frames():
                try:
                    path = graph.resolve(source_frame, frame.id)
                except Exception:
                    continue        # 不连通的系没有确定位置，跳过其矢量
                from .coord_core.transforms import split_transform

                attitude, trans = split_transform(path.matrix)
                direction = np.asarray(values, dtype=float)
                self._3d_view.add_vector(trans, attitude.apply(direction) * 0.25)
            self._render_3d()
        except Exception as exc:
            logger.warning("3D 矢量刷新失败: %s", exc)

    def _run_compare(self) -> None:
        if self.ledger is None:
            return
        baseline = self.compare_baseline.currentText()
        candidate = self.compare_candidate.currentText()
        if not baseline or not candidate:
            return
        try:
            comparison = self.ledger.compare_transforms(baseline, candidate)
        except (AppError, ValueError) as exc:
            handle_ui_exception(self, logger, "变换对比", exc)
            return
        self._show_comparison(comparison)

    def _run_status_pair_compare(self) -> None:
        if self.ledger is None:
            return
        source = self.query_from.currentText()
        target = self.query_to.currentText()
        record = self.ledger.current_record(target, source) or self.ledger.current_record(source, target)
        if record is None:
            QMessageBox.information(self, "提示", "请先在查询页选择存在变换关系的两系")
            return
        try:
            comparison = self.ledger.compare_status_pair(
                record.from_frame, record.to_frame,
                baseline_status="design", candidate_status="calibrated",
            )
        except (AppError, ValueError) as exc:
            handle_ui_exception(self, logger, "状态对对比", exc)
            return
        self._show_comparison(comparison)

    def _show_comparison(self, comparison) -> None:
        worst = comparison.worst_item
        rows = comparison.rows
        self.compare_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                f"{row.label}({row.unit})", fmt.fmt_signed(row.delta, 4), fmt.fmt_fixed(row.sigma, 4),
                fmt.fmt_signed(row.z, 3), VERDICT_LABELS[row.verdict],
                "← 最大偏差项" if row.name == worst else "",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if row.verdict in VERDICT_COLORS:
                    item.setBackground(VERDICT_COLORS[row.verdict])
                    item.setForeground(_VERDICT_TEXT_COLORS[row.verdict])
                if row.name == worst:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.compare_table.setItem(row_index, col_index, item)
        self.conclusion_text.setPlainText(fmt.comparison_result_text(comparison))
        self._set_status(f"对比完成：{comparison.overall_label}")

    def _run_loop(self) -> None:
        if self.ledger is None:
            return
        try:
            report = self.ledger.loop_closure()
        except (AppError, ValueError) as exc:
            handle_ui_exception(self, logger, "环路自检", exc)
            return
        self.review_table.setRowCount(len(report.items))
        for row_index, item in enumerate(report.items):
            values = [
                "环路", fmt.fmt_path(item.frames),
                f"e_rot {fmt.fmt_fixed(item.e_rot_arcsec, 3)}″ / e_trans {fmt.fmt_fixed(item.e_trans_mm, 3)}mm",
                f"{fmt.fmt_fixed(item.threshold_rot_arcsec, 3)}″ / {fmt.fmt_fixed(item.threshold_trans_mm, 3)}mm",
                "闭合 ✓" if item.closed else "不闭合 ✗",
            ]
            for col_index, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                verdict = "ok" if item.closed else "fail"
                table_item.setBackground(VERDICT_COLORS[verdict])
                table_item.setForeground(_VERDICT_TEXT_COLORS[verdict])
                self.review_table.setItem(row_index, col_index, table_item)
        self.conclusion_text.setPlainText(fmt.loop_report_text(report))
        self._set_status(report.summary())

    def _run_limits(self) -> None:
        if self.ledger is None:
            return
        try:
            report = self.ledger.check_limits()
        except (AppError, ValueError) as exc:
            handle_ui_exception(self, logger, "限值检查", exc)
            return
        self.review_table.setRowCount(len(report.items))
        for row_index, item in enumerate(report.items):
            values = [
                "限值", f"{item.limit_id}｜{item.description}",
                f"{fmt.fmt_fixed(item.computed, 4)} {item.unit}（偏差 {fmt.fmt_signed(item.deviation, 4)}）",
                f"{fmt.fmt_number(item.expected, 6)} ± {fmt.fmt_number(item.tolerance, 6)} {item.unit}",
                "通过 ✓" if item.passed else "不通过 ✗",
            ]
            for col_index, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                verdict = "ok" if item.passed else "fail"
                table_item.setBackground(VERDICT_COLORS[verdict])
                table_item.setForeground(_VERDICT_TEXT_COLORS[verdict])
                self.review_table.setItem(row_index, col_index, table_item)
        self.conclusion_text.setPlainText(fmt.limit_report_text(report))
        self._set_status(report.summary())

    def _run_health(self) -> None:
        if self.ledger is None:
            return
        try:
            summary = self.ledger.health_summary()
        except Exception as exc:
            handle_ui_exception(self, logger, "账本健康度", exc)
            return
        self.conclusion_text.setPlainText(summary)
        self._set_status(summary)

    # ------------------------------------------------------------------
    # 3D（懒加载 + 降级）
    # ------------------------------------------------------------------

    def _init_3d(self) -> None:
        self._3d_loaded = True
        from . import coord_3d

        self._3d_view = coord_3d.Coord3DView()
        self._refresh_3d_scene()

        if coord_3d.pyvista_available():
            try:
                interactor = coord_3d.create_pyvista_interactor(self.three_d_tab)
                self._3d_widget = interactor
                self.three_d_tab.layout().addWidget(interactor)
                self.three_d_hint.setText("PyVista 交互视口：左键旋转 / 滚轮缩放 / 中键平移")
                self._render_3d()
                return
            except Exception as exc:
                reason = getattr(exc, "user_message", None) or str(exc)
                logger.warning("PyVista 视口创建失败，降级 matplotlib: %s", reason)
                self.three_d_hint.setText(
                    f"PyVista 视口创建失败（{type(exc).__name__}: {reason}），已降级 matplotlib 静态图"
                )
        else:
            self.three_d_hint.setText(
                "PyVista 未安装（当前 Python 缺少 pyvista / pyvistaqt），已降级 matplotlib 静态图；"
                "安装：pip install pyvista pyvistaqt"
            )

        try:
            self._3d_matplotlib = coord_3d.Matplotlib3DCanvas(self.three_d_tab)
            self.three_d_tab.layout().addWidget(self._3d_matplotlib.widget())
            self._render_3d()
        except Exception as exc:
            handle_ui_exception(self, logger, "3D 视口初始化", exc)

    def _refresh_3d(self) -> None:
        """刷新 3D 场景（新建/修改坐标系后手动同步）。"""
        if not self._3d_loaded or self._3d_view is None:
            return
        try:
            self._refresh_3d_scene()
            self._render_3d()
            self._3d_dirty = False
            count = len(self._3d_view.frames)
            message = f"3D 场景已刷新（{count} 个坐标系）"
            if self._3d_unreachable:
                message += f"；{len(self._3d_unreachable)} 个孤立坐标系未显示：{', '.join(self._3d_unreachable)}"
            self._set_status(message)
        except Exception as exc:
            handle_ui_exception(self, logger, "刷新 3D", exc)

    def _refresh_3d_scene(self) -> None:
        if self._3d_view is None or self.ledger is None:
            return
        import numpy as np

        from .coord_core.transforms import invert_transform

        poses: Dict[str, object] = {}
        graph = self.ledger.build_graph()
        root_id = self.ledger.frames()[0].id if self.ledger.frames() else None
        self._3d_unreachable = []
        if root_id is None:
            self._3d_view.set_frames({}, {})
            self._3d_view.set_links([])
            return
        poses[root_id] = np.eye(4)
        for frame in self.ledger.frames():
            if frame.id == root_id:
                continue
            try:
                path = graph.resolve(root_id, frame.id)
                poses[frame.id] = path.matrix
            except Exception:
                try:
                    poses[frame.id] = invert_transform(graph.resolve(frame.id, root_id).matrix)
                except Exception:
                    # 该系与主图不连通（如变换被删），几何位置无法确定，跳过显示
                    self._3d_unreachable.append(frame.id)
        labels = {frame.id: frame.name or frame.id for frame in self.ledger.frames()}
        self._3d_view.set_frames(poses, labels)
        # 安装关系连线（去重，且两端都可达）
        links = []
        seen = set()
        for record in self.ledger.transforms():
            if record.status == "obsolete":
                continue
            key = tuple(sorted((record.from_frame, record.to_frame)))
            if key in seen:
                continue
            if record.from_frame not in poses or record.to_frame not in poses:
                continue
            seen.add(key)
            links.append((record.from_frame, record.to_frame))
        self._3d_view.set_links(links)

    def _render_3d(self, first_frame: bool = False) -> None:
        if self._3d_view is None:
            return
        if not getattr(self, "_3d_rendered_once", False):
            first_frame = True
        try:
            if self._3d_widget is not None:
                self._3d_view.render_pyvista(self._3d_widget, first_frame=first_frame)
            elif self._3d_matplotlib is not None:
                self._3d_matplotlib.draw_view(self._3d_view)
            self._3d_rendered_once = True
        except Exception as exc:
            logger.warning("3D 渲染失败: %s", exc)

    def export_3d_screenshot(self, filepath: str) -> str:
        """E8 截图导出（供报告嵌入）。"""
        if self._3d_view is None:
            self._refresh_3d_scene()
        if self._3d_view is None:
            return filepath
        return self._3d_view.screenshot(filepath)
