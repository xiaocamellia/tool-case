"""DAT 导出 TXT 辅助面板 — 数据可视化页签内的并行工作区。

把雷达模拟器记录的定长 ``.dat`` 导出成与成熟软件逐字节一致的 GBK 文本
（``dat2txt_core`` 复刻 ``SQLiteControl.ExportDatFrameToTxt``），供本页签
「数据绘图」子页直接加载。界面交互对齐原 dat2txt 工具（数据类型 / dat 文件 /
输出文件 / 起止时间 / 采样间隔 / 导出列 / 进度与日志）。
"""

from __future__ import annotations

import os
import threading
from datetime import datetime

from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .dat2txt_core import (
    DATASETS,
    ExportCancelled,
    ExportRequest,
    default_output_path,
    ensure_parent,
    export_dat,
    frame_count,
    load_dataset_specs,
    read_frame_time,
    summarize,
)
from .background_tasks import (
    ensure_task_can_start,
    register_background_task,
    task_result_is_current,
)
from .errors import safe_exception_message
from .logger import get_logger
from .ui_theme import set_button_icon, set_text_tone, set_variant, style_primary_button

logger = get_logger('dat2txt_panel')

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
_TIME_FORMATS = (
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d %H:%M',
    '%Y/%m/%d %H:%M:%S',
    '%Y%m%d%H%M%S',
)


def parse_time_text(text):
    """解析 GUI/CLI 接受的时间格式（yyyy-MM-dd HH:mm:ss 等）。"""
    value = (text or '').strip()
    for pattern in _TIME_FORMATS:
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    raise ValueError('无法解析时间：%r（请使用 yyyy-MM-dd HH:mm:ss）' % (text,))


class Dat2TxtExportWorker(QObject):
    """在 Qt UI 线程之外执行一次 dat -> txt 导出。"""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, request):
        super().__init__()
        self._request = request
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        def on_progress(message):
            text = str(message)
            self.progress.emit(_parse_progress_percent(text), text)

        try:
            result = export_dat(
                self._request,
                progress=on_progress,
                cancel=self._cancel_event.is_set,
            )
        except ExportCancelled:
            self.cancelled.emit('导出已取消')
        except Exception as exc:  # noqa: BLE001 - reported in the panel
            if self._cancel_event.is_set():
                self.cancelled.emit('导出已取消')
            else:
                logger.exception('dat 导出 txt 后台任务失败')
                self.failed.emit(safe_exception_message(exc))
        else:
            self.progress.emit(100, '导出完成')
            self.succeeded.emit(result)


def _parse_progress_percent(message):
    """从「当前进度：N/M xx%」解析百分比；其余文案返回 -1。"""
    if not message.startswith('当前进度：'):
        return -1
    try:
        rest = message.split('：', 1)[1]
        _done, tail = rest.split('/', 1)
        return int(float(tail.split()[1].rstrip('%')))
    except (IndexError, ValueError):
        return -1


class Dat2TxtPanel(QWidget):
    """dat -> txt 导出工作区（数据可视化页签内的并行子页）。"""

    def __init__(self, viz_panel=None, parent=None):
        super().__init__(parent)
        self._viz = viz_panel
        self._specs = []
        self._export_thread = None
        self._export_worker = None
        self._export_task_name = ''
        self._export_task_version = 0
        self._last_result = None  # type: ExportResult | None
        self._init_ui()
        self._refresh_columns()
        logger.info('DAT 导出 TXT 面板已创建')

    # ------------------------------------------------------------------ UI
    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel('DAT 导出 TXT')
        title.setObjectName('pageTitle')
        subtitle = QLabel('雷达模拟器 .dat 定长帧 → GBK 文本（与成熟软件导出逐字节一致）')
        set_text_tone(subtitle, 'muted')
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addLayout(title_box)
        heading.addStretch()
        root.addLayout(heading)

        # ===== 导出参数 =====
        param_group = QGroupBox('导出参数')
        grid = QGridLayout(param_group)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        grid.addWidget(QLabel('数据类型'), 0, 0)
        self.combo_dataset = QComboBox()
        for dataset in DATASETS:
            self.combo_dataset.addItem(dataset.label, dataset.key)
        self.combo_dataset.setToolTip('决定单帧长度与字段定义')
        self.combo_dataset.currentIndexChanged.connect(self._on_dataset_changed)
        grid.addWidget(self.combo_dataset, 0, 1, 1, 3)

        grid.addWidget(QLabel('dat 文件'), 1, 0)
        self.edit_dat_path = QLineEdit()
        self.edit_dat_path.setPlaceholderText('选择雷达模拟器记录的 .dat 文件')
        self.edit_dat_path.editingFinished.connect(self._on_dat_path_edited)
        grid.addWidget(self.edit_dat_path, 1, 1, 1, 2)
        self.btn_browse_dat = QPushButton('浏览...')
        self.btn_browse_dat.clicked.connect(self._browse_dat)
        set_button_icon(self.btn_browse_dat, 'open')
        grid.addWidget(self.btn_browse_dat, 1, 3)

        grid.addWidget(QLabel('输出文件'), 2, 0)
        self.edit_txt_path = QLineEdit()
        self.edit_txt_path.setPlaceholderText('默认与 dat 同目录，{表名}_{时间戳}_export.txt')
        grid.addWidget(self.edit_txt_path, 2, 1, 1, 2)
        self.btn_browse_out = QPushButton('另存为...')
        self.btn_browse_out.clicked.connect(self._browse_out)
        set_button_icon(self.btn_browse_out, 'save')
        grid.addWidget(self.btn_browse_out, 2, 3)

        grid.addWidget(QLabel('起始时间'), 3, 0)
        self.edit_start = QLineEdit()
        self.edit_start.setPlaceholderText('yyyy-MM-dd HH:mm:ss')
        self.edit_start.setMaximumWidth(170)
        grid.addWidget(self.edit_start, 3, 1)

        time_box = QHBoxLayout()
        time_box.addWidget(QLabel('结束时间'))
        self.edit_end = QLineEdit()
        self.edit_end.setPlaceholderText('yyyy-MM-dd HH:mm:ss')
        self.edit_end.setMaximumWidth(170)
        time_box.addWidget(self.edit_end)
        time_box.addWidget(QLabel('采样间隔'))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(0, 100000)
        self.spin_interval.setToolTip('0 = 导出全部帧；N = 每 N+1 帧取 1 帧')
        time_box.addWidget(self.spin_interval)
        self.btn_time_range = QPushButton('读取时间范围')
        self.btn_time_range.setToolTip('读取 dat 首/末帧时间并填入起止时间')
        self.btn_time_range.clicked.connect(self._load_time_range)
        set_button_icon(self.btn_time_range, 'reload')
        time_box.addWidget(self.btn_time_range)
        time_box.addStretch()
        grid.addLayout(time_box, 3, 2, 1, 2)

        hint = QLabel('间隔 0 = 导出全部帧，1 = 每 2 帧取 1 帧；起止时间为闭区间')
        set_text_tone(hint, 'hint')
        grid.addWidget(hint, 4, 0, 1, 4)

        root.addWidget(param_group)

        # ===== 导出列 =====
        column_group = QGroupBox('导出列（按 CSV 顺序输出）')
        column_layout = QHBoxLayout(column_group)

        self.list_columns = QListWidget()
        self.list_columns.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_columns.itemChanged.connect(self._update_column_count)
        column_layout.addWidget(self.list_columns, 1)

        button_box = QVBoxLayout()
        self.btn_select_all = QPushButton('全选')
        self.btn_select_all.clicked.connect(self._select_all_columns)
        set_button_icon(self.btn_select_all, 'apply')
        set_variant(self.btn_select_all, 'ghost')
        button_box.addWidget(self.btn_select_all)

        self.btn_select_none = QPushButton('全不选')
        self.btn_select_none.clicked.connect(self._select_no_columns)
        set_button_icon(self.btn_select_none, 'clear')
        set_variant(self.btn_select_none, 'ghost')
        button_box.addWidget(self.btn_select_none)

        self.btn_invert = QPushButton('反选')
        self.btn_invert.clicked.connect(self._invert_columns)
        set_button_icon(self.btn_invert, 'refresh')
        set_variant(self.btn_invert, 'ghost')
        button_box.addWidget(self.btn_invert)

        self.lbl_col_count = QLabel('已选 0 / 0 列')
        set_text_tone(self.lbl_col_count, 'muted')
        button_box.addWidget(self.lbl_col_count)
        button_box.addStretch()
        column_layout.addLayout(button_box)
        root.addWidget(column_group, 1)

        # ===== 动作与进度 =====
        action_row = QHBoxLayout()
        self.btn_export = QPushButton('开始导出')
        self.btn_export.clicked.connect(self._start_export)
        set_button_icon(self.btn_export, 'play')
        style_primary_button(self.btn_export)
        action_row.addWidget(self.btn_export)

        self.btn_cancel = QPushButton('取消')
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._request_cancel)
        set_button_icon(self.btn_cancel, 'clear')
        set_variant(self.btn_cancel, 'warning')
        action_row.addWidget(self.btn_cancel)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        action_row.addWidget(self.progress_bar, 1)

        self.btn_load_result = QPushButton('加载导出结果到数据集')
        self.btn_load_result.setToolTip('把刚导出的 txt 载入「数据绘图」子页的数据集列表')
        self.btn_load_result.setEnabled(False)
        self.btn_load_result.clicked.connect(self._load_exported_result)
        set_button_icon(self.btn_load_result, 'apply')
        set_variant(self.btn_load_result, 'secondary')
        action_row.addWidget(self.btn_load_result)
        root.addLayout(action_row)

        self.lbl_status = QLabel('就绪')
        set_text_tone(self.lbl_status, 'success')
        root.addWidget(self.lbl_status)

        # ===== 日志 =====
        log_group = QGroupBox('日志')
        log_layout = QVBoxLayout(log_group)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(120)
        log_layout.addWidget(self.txt_log)
        root.addWidget(log_group)

    # ----------------------------------------------------------- 列定义
    @property
    def dataset(self):
        key = self.combo_dataset.currentData()
        for item in DATASETS:
            if item.key == key:
                return item
        return DATASETS[0]

    def _refresh_columns(self):
        self.list_columns.blockSignals(True)
        self.list_columns.clear()
        try:
            self._specs = load_dataset_specs(self.dataset)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self._specs = []
            self._append_log('读取字段定义失败：%s' % (safe_exception_message(exc),))
            self.list_columns.blockSignals(False)
            self._update_column_count()
            return
        for spec in self._specs:
            item = QListWidgetItem('%3d  %s' % (spec.index + 1, spec.name))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_columns.addItem(item)
        self.list_columns.blockSignals(False)
        self._update_column_count()

    def _selected_column_indices(self):
        indices = []
        for row in range(self.list_columns.count()):
            item = self.list_columns.item(row)
            if item.checkState() == Qt.Checked and row < len(self._specs):
                indices.append(self._specs[row].index)
        return indices

    def _update_column_count(self, _item=None):
        total = self.list_columns.count()
        selected = sum(
            1
            for row in range(total)
            if self.list_columns.item(row).checkState() == Qt.Checked
        )
        self.lbl_col_count.setText('已选 %d / %d 列' % (selected, total))

    def _select_all_columns(self):
        self._set_all_check_states(Qt.Checked)

    def _select_no_columns(self):
        self._set_all_check_states(Qt.Unchecked)

    def _invert_columns(self):
        self.list_columns.blockSignals(True)
        for row in range(self.list_columns.count()):
            item = self.list_columns.item(row)
            if item.checkState() == Qt.Checked:
                item.setCheckState(Qt.Unchecked)
            else:
                item.setCheckState(Qt.Checked)
        self.list_columns.blockSignals(False)
        self._update_column_count()

    def _set_all_check_states(self, state):
        self.list_columns.blockSignals(True)
        for row in range(self.list_columns.count()):
            self.list_columns.item(row).setCheckState(state)
        self.list_columns.blockSignals(False)
        self._update_column_count()

    # ----------------------------------------------------------- 文件选择
    def _on_dataset_changed(self, _index=None):
        self._refresh_columns()
        if self.edit_dat_path.text().strip():
            self._load_time_range()

    def _on_dat_path_edited(self):
        path = self.edit_dat_path.text().strip()
        if path and os.path.isfile(path):
            if not self.edit_txt_path.text().strip():
                self.edit_txt_path.setText(default_output_path(self.dataset, path))
            self._load_time_range()

    def _browse_dat(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择 dat 文件', '', 'dat 文件 (*.dat);;所有文件 (*.*)'
        )
        if not path:
            return
        self.edit_dat_path.setText(path)
        self.edit_txt_path.setText(default_output_path(self.dataset, path))
        self._load_time_range()

    def _browse_out(self):
        initial = self.edit_txt_path.text().strip() or default_output_path(
            self.dataset, self.edit_dat_path.text().strip() or 'export.dat'
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            '输出 txt 文件',
            initial,
            'txt 文件 (*.txt);;所有文件 (*.*)',
        )
        if path:
            self.edit_txt_path.setText(path)

    def _load_time_range(self):
        path = self.edit_dat_path.text().strip()
        if not path or not os.path.isfile(path):
            return
        dataset = self.dataset
        total, remainder = frame_count(path, dataset.frame_length)
        if total <= 0:
            self._append_log('文件不足一帧（%d 字节）' % (dataset.frame_length,))
            return
        first = read_frame_time(path, dataset.frame_length, 0)
        last = read_frame_time(path, dataset.frame_length, total - 1)
        if first:
            self.edit_start.setText(first.strftime(TIME_FORMAT))
        if last:
            self.edit_end.setText(last.strftime(TIME_FORMAT))
        self._append_log(
            '共 %d 帧（单帧 %d 字节，余 %d 字节） 时间范围 %s ~ %s'
            % (total, dataset.frame_length, remainder, first, last)
        )

    # ------------------------------------------------------------- 导出
    def _start_export(self):
        if self._export_thread is not None:
            return
        dat_path = self.edit_dat_path.text().strip()
        txt_path = self.edit_txt_path.text().strip()
        if not dat_path or not os.path.isfile(dat_path):
            QMessageBox.warning(self, '提示', '请选择存在的 dat 文件')
            return
        if not txt_path:
            QMessageBox.warning(self, '提示', '请指定输出文件')
            return
        try:
            start_time = parse_time_text(self.edit_start.text())
            end_time = parse_time_text(self.edit_end.text())
        except ValueError as exc:
            QMessageBox.warning(self, '提示', safe_exception_message(exc))
            return
        if end_time < start_time:
            QMessageBox.warning(self, '提示', '结束时间不能早于起始时间')
            return
        interval = self.spin_interval.value()
        column_indices = self._selected_column_indices()
        if not column_indices:
            QMessageBox.warning(self, '提示', '请至少选择一列')
            return

        dataset = self.dataset
        try:
            ensure_parent(txt_path)
        except OSError as exc:
            QMessageBox.critical(self, '提示', '无法创建输出目录：%s' % (exc,))
            return

        request = ExportRequest(
            dat_path=dat_path,
            txt_path=txt_path,
            code_id=dataset.code_id,
            start_time=start_time,
            end_time=end_time,
            interval=interval,
            column_indices=column_indices,
        )

        task_name = 'dat 导出 txt'
        ensure_task_can_start(self, task_name)
        self._export_task_name = task_name
        self.btn_export.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_load_result.setEnabled(False)
        self._last_result = None
        self.progress_bar.setValue(0)
        self.lbl_status.setText('开始加载文件...')
        set_text_tone(self.lbl_status, 'primary')
        self._append_log('开始导出：%s -> %s' % (dat_path, txt_path))

        thread = QThread(self)
        worker = Dat2TxtExportWorker(request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(self._on_export_succeeded)
        worker.failed.connect(self._on_export_failed)
        worker.cancelled.connect(self._on_export_cancelled)
        for signal in (worker.succeeded, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
            signal.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_export_thread_finished)
        self._export_thread = thread
        self._export_worker = worker
        self._export_task_version = register_background_task(
            self,
            task_name,
            thread,
            worker,
            worker.cancel,
        )
        thread.start()
        logger.info('用户操作: 开始 dat 导出 txt — %s', dat_path)

    def _request_cancel(self):
        if self._export_worker is not None:
            self._export_worker.cancel()
        self.lbl_status.setText('正在取消...')
        set_text_tone(self.lbl_status, 'warning')

    def _on_progress(self, percent, message):
        if percent >= 0:
            self.progress_bar.setValue(percent)
            self.lbl_status.setText(message)
        elif message.startswith('警告'):
            self._append_log(message)
        else:
            self.lbl_status.setText(message)

    def _on_export_succeeded(self, result):
        if not task_result_is_current(
            self, self._export_task_name, self._export_task_version
        ):
            return
        self._last_result = result
        self.progress_bar.setValue(100)
        self.lbl_status.setText('导出完成！共处理 %d 帧数据' % (result.total_frames,))
        set_text_tone(self.lbl_status, 'success')
        for warning in result.warnings:
            self._append_log(warning)
        self._append_log(summarize(result))
        self._append_log('txt  ：%s' % (result.txt_path,))
        self._append_log('列名 ：%s' % (result.column_path,))
        self.btn_load_result.setEnabled(True)
        logger.info('dat 导出 txt 完成: %s', result.txt_path)
        QMessageBox.information(
            self,
            '完成',
            '导出完成！共处理 %d 帧数据\n数据已导入至文件%s,共计用时%dms'
            % (result.total_frames, result.txt_path, result.elapsed_ms),
        )

    def _on_export_failed(self, message):
        if not task_result_is_current(
            self, self._export_task_name, self._export_task_version
        ):
            return
        self.lbl_status.setText('导出失败')
        set_text_tone(self.lbl_status, 'danger')
        self._append_log('导出失败：%s' % (message,))
        logger.warning('dat 导出 txt 失败: %s', message)
        QMessageBox.critical(self, '导出失败', message)

    def _on_export_cancelled(self, message):
        if not task_result_is_current(
            self, self._export_task_name, self._export_task_version
        ):
            return
        self.progress_bar.setValue(0)
        self.lbl_status.setText('已取消')
        set_text_tone(self.lbl_status, 'warning')
        self._append_log(message)
        logger.info('dat 导出 txt 已取消')

    def _on_export_thread_finished(self):
        self._export_worker = None
        self._export_thread = None
        self.btn_export.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    # ------------------------------------------------------- 联动数据绘图
    def _load_exported_result(self):
        result = self._last_result
        if result is None:
            return
        if self._viz is None or not hasattr(self._viz, 'load_dataset_paths'):
            QMessageBox.information(self, '提示', '当前没有可用的数据绘图工作区')
            return
        self._viz.load_dataset_paths([result.txt_path])
        workspace = getattr(self._viz, 'workspace_tabs', None)
        if workspace is not None:
            workspace.setCurrentIndex(0)
        self._append_log('已把导出结果加入数据集列表：%s' % (result.txt_path,))

    # --------------------------------------------------------------- 日志
    def _append_log(self, message):
        self.txt_log.append(message)
