"""
干涉仪测向仿真工具 - Interferometer Direction Finding Simulation Tool
基于 PyQt5 + matplotlib，用于阵列配置、DOA估计算法仿真与性能评估
"""

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QFileDialog, QComboBox, QDoubleSpinBox,
    QSpinBox, QMessageBox, QTextEdit, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox, QSplitter, QFrame,
    QLineEdit, QAbstractItemView
)
from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor
from matplotlib.backends.backend_qt5agg import (
    NavigationToolbar2QT as NavigationToolbar,
    FigureCanvasQTAgg as FigureCanvas,
)
from matplotlib.figure import Figure

from .ui_theme import set_button_icon, style_primary_button, style_warning_button
from .logger import get_logger

logger = get_logger('interferometer_sim')
from .algorithms import (
    C,
    compute_array_manifold_2d,
    generate_received_signal,
    bartlett_doa_1d,
    music_doa_1d,
    bartlett_doa_2d,
    music_doa_2d,
    esprit_doa,
    monte_carlo_evaluation,
    create_ula,
    create_uca,
    create_l_array,
    create_rect_array,
)


def _pick_top_peaks_1d(P, thetas, count, min_sep_deg=2.0):
    """Pick separated local maxima from a 1D spectrum."""
    if count <= 0 or len(P) == 0:
        return []
    order = np.argsort(P)[::-1]
    peaks = []
    for idx in order:
        theta = float(thetas[idx])
        if all(abs(theta - picked) >= min_sep_deg for picked in peaks):
            peaks.append(theta)
            if len(peaks) >= count:
                break
    return sorted(peaks)


def _pick_top_peaks_2d(P, thetas, phis, count, min_sep_deg=3.0):
    """Pick separated peaks from a 2D spectrum."""
    if count <= 0 or P.size == 0:
        return []
    flat_order = np.argsort(P.ravel())[::-1]
    peaks = []
    for flat_idx in flat_order:
        phi_idx, theta_idx = np.unravel_index(flat_idx, P.shape)
        theta = float(thetas[theta_idx])
        phi = float(phis[phi_idx])
        if all(np.hypot(theta - pt, phi - pp) >= min_sep_deg for pt, pp in peaks):
            peaks.append((theta, phi))
            if len(peaks) >= count:
                break
    return peaks


class SimulationWorker(QObject):
    """Run a single DOA simulation outside the Qt UI thread."""

    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, params):
        super().__init__()
        self.params = params

    def run(self):
        try:
            p = self.params
            array_pos = p['array_pos']
            signals = p['signals']
            fc = p['fc']
            fs = p['fs']
            T = p['T']
            SNR = p['SNR']
            N_signals = p['N_signals']
            do_2d = p['do_2d']
            algo_idx = p['algo_idx']
            theta_range = p['theta_range']
            theta_step = p['theta_step']
            theta_true = p['theta_true']
            phi_true = p['phi_true']
            imperfections = p.get('imperfections')

            X = generate_received_signal(array_pos, signals, fc, fs, T, SNR, imperfections=imperfections)

            if do_2d:
                if algo_idx == 0:
                    theta_est, phi_est, P, thetas, phis = bartlett_doa_2d(
                        X, array_pos, theta_range, theta_step, (-90, 90), theta_step, fc)
                    algo_name = 'Bartlett (2D)'
                elif algo_idx == 1:
                    theta_est, phi_est, P, thetas, phis = music_doa_2d(
                        X, array_pos, theta_range, theta_step, (-90, 90), theta_step, fc, N_signals)
                    algo_name = 'MUSIC (2D)'
                else:
                    raise ValueError('ESPRIT不支持二维估计')
                peak_pairs = _pick_top_peaks_2d(P, thetas, phis, N_signals)
                theta_ests = [theta for theta, _ in peak_pairs]
                phi_ests = [phi for _, phi in peak_pairs]

                self.finished.emit({
                    'do_2d': True,
                    'algo_name': algo_name,
                    'theta_est': theta_est,
                    'phi_est': phi_est,
                    'theta_ests': theta_ests,
                    'phi_ests': phi_ests,
                    'theta_true': theta_true,
                    'phi_true': phi_true,
                    'targets': signals,
                    'P': P,
                    'thetas': thetas,
                    'phis': phis,
                })
            else:
                if algo_idx == 0:
                    theta_est, P, thetas, _ = bartlett_doa_1d(X, array_pos, theta_range, theta_step, fc, phi_true)
                    algo_name = 'Bartlett'
                elif algo_idx == 1:
                    theta_est, P, thetas, _ = music_doa_1d(X, array_pos, theta_range, theta_step, fc, N_signals, phi_true)
                    algo_name = 'MUSIC'
                else:
                    d = p['array_spacing']
                    if d <= 0:
                        raise ValueError('ESPRIT需要设置阵元间距')
                    angles = esprit_doa(X, d, fc, N_signals)
                    theta_est = float(angles[0]) if len(angles) > 0 else 0
                    _, P, thetas, _ = music_doa_1d(X, array_pos, theta_range, theta_step, fc, N_signals, phi_true)
                    algo_name = 'ESPRIT'
                theta_ests = _pick_top_peaks_1d(P, thetas, N_signals)

                self.finished.emit({
                    'do_2d': False,
                    'algo_name': algo_name,
                    'theta_est': theta_est,
                    'theta_ests': theta_ests,
                    'theta_true': theta_true,
                    'targets': signals,
                    'P': P,
                    'thetas': thetas,
                })
        except Exception as e:
            self.failed.emit(str(e))


class MonteCarloWorker(QObject):
    """Run Monte Carlo calculations outside the Qt UI thread."""

    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, params):
        super().__init__()
        self.params = params

    def run(self):
        try:
            p = self.params
            array_pos = p['array_pos']
            signals = p['signals']
            fc = p['fc']
            fs = p['fs']
            T = p['T']
            SNR = p['SNR']
            N_trials = p['N_trials']
            do_2d = p['do_2d']
            algo_idx = p['algo_idx']
            theta_step = p['theta_step']
            phi_true = p['phi_true']
            imperfections = p.get('imperfections')

            if do_2d:
                if algo_idx == 0:
                    algo_func = lambda X, ap, tr, ts, pr, ps, fc, ns: bartlett_doa_2d(X, ap, tr, ts, pr, ps, fc)
                    algo_name = 'Bartlett (2D)'
                else:
                    algo_func = lambda X, ap, tr, ts, pr, ps, fc, ns: music_doa_2d(X, ap, tr, ts, pr, ps, fc, ns)
                    algo_name = 'MUSIC (2D)'

                rmse_t, bias_t, std_t, errors_t, rmse_p, errors_p = monte_carlo_evaluation(
                    array_pos, signals, fc, fs, T, SNR, algo_func, N_trials,
                    do_2d=True, theta_step=theta_step, phi_step=theta_step, imperfections=imperfections
                )
                self.finished.emit({
                    'do_2d': True,
                    'algo_name': algo_name,
                    'rmse_t': rmse_t,
                    'bias_t': bias_t,
                    'std_t': std_t,
                    'errors_t': errors_t,
                    'rmse_p': rmse_p,
                    'errors_p': errors_p,
                })
            else:
                if algo_idx == 0:
                    algo_func = lambda X, ap, tr, ts, fc, ns: bartlett_doa_1d(X, ap, tr, ts, fc, phi_true)
                    algo_name = 'Bartlett'
                else:
                    algo_func = lambda X, ap, tr, ts, fc, ns: music_doa_1d(X, ap, tr, ts, fc, ns, phi_true)
                    algo_name = 'MUSIC' if algo_idx == 1 else 'ESPRIT-like'

                rmse, bias, std_dev, errors = monte_carlo_evaluation(
                    array_pos, signals, fc, fs, T, SNR, algo_func, N_trials,
                    theta_step=theta_step, imperfections=imperfections
                )
                self.finished.emit({
                    'do_2d': False,
                    'algo_name': algo_name,
                    'rmse': rmse,
                    'bias': bias,
                    'std_dev': std_dev,
                    'errors': errors,
                })
        except Exception as e:
            self.failed.emit(str(e))


class InterferometerSimPanel(QWidget):
    """干涉仪测向仿真工具主面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.array_pos = None  # 当前阵列坐标
        self._custom_coords = None  # 自定义坐标缓存
        self.sim_result = None
        self.mc_errors = None
        self._sim_thread = None
        self._sim_worker = None
        self._sim_context = None
        self._mc_thread = None
        self._mc_worker = None
        self._mc_context = None
        
        self._init_ui()
        self._load_default_array()
        logger.info('干涉仪测向仿真工具面板已创建')
    
    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        
        # ===== 顶部控制栏 =====
        ctrl_group = QGroupBox('仿真控制')
        ctrl_layout = QHBoxLayout(ctrl_group)
        
        self.btn_run = QPushButton('▶ 开始仿真')
        self.btn_run.clicked.connect(self.run_simulation)
        self.btn_run.setStyleSheet('background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;')
        set_button_icon(self.btn_run, 'play')
        style_primary_button(self.btn_run)
        ctrl_layout.addWidget(self.btn_run)
        
        self.btn_mc = QPushButton('🎲 蒙特卡洛评估')
        self.btn_mc.clicked.connect(self.run_monte_carlo)
        style_primary_button(self.btn_mc)
        ctrl_layout.addWidget(self.btn_mc)
        
        self.btn_clear = QPushButton('🗑️ 清除结果')
        self.btn_clear.clicked.connect(self.clear_results)
        style_warning_button(self.btn_clear)
        ctrl_layout.addWidget(self.btn_clear)
        
        ctrl_layout.addStretch()
        main_layout.addWidget(ctrl_group)
        
        # ===== 主分割器：左配置 / 右结果 =====
        splitter = QSplitter(Qt.Horizontal)
        
        # ---- 左侧配置面板 ----
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self._create_array_config(left_layout)
        self._create_signal_config(left_layout)
        self._create_algorithm_config(left_layout)
        
        splitter.addWidget(left_widget)
        
        # ---- 右侧结果面板 ----
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        self._create_results_panel(right_layout)
        
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        main_layout.addWidget(splitter, 1)
    
    # ---------- 阵列配置 ----------
    
    def _create_array_config(self, parent_layout):
        group = QGroupBox('阵列配置')
        layout = QGridLayout(group)
        
        # ---- 第0行: 阵列类型 ----
        layout.addWidget(QLabel('阵列类型:'), 0, 0)
        self.combo_array_type = QComboBox()
        self.combo_array_type.addItems(['均匀线阵 (ULA)', '均匀圆阵 (UCA)', 'L型阵列', '矩形面阵', '自定义坐标'])
        self.combo_array_type.setCurrentIndex(1)  # 默认UCA，支持二维DOA估计
        self.combo_array_type.currentIndexChanged.connect(self.on_array_type_changed)
        layout.addWidget(self.combo_array_type, 0, 1)
        
        # ---- 第1行左侧: 阵元数(动态标签) ----
        self.lbl_element = QLabel('阵元数:')
        layout.addWidget(self.lbl_element, 1, 0)
        
        # 主阵元数 SpinBox (ULA单值 / L型X轴 / 矩形行数)
        self.spin_array_N = QSpinBox()
        self.spin_array_N.setRange(2, 64)
        self.spin_array_N.setValue(8)
        self.spin_array_N.valueChanged.connect(self.on_array_param_changed)
        layout.addWidget(self.spin_array_N, 1, 1)
        
        # L型/矩形第2个阵元数
        self.lbl_element2 = QLabel('')
        self.spin_element2 = QSpinBox()
        self.spin_element2.setRange(2, 32)
        self.spin_element2.setValue(4)
        self.spin_element2.valueChanged.connect(self.on_array_param_changed)
        layout.addWidget(self.lbl_element2, 1, 2)
        layout.addWidget(self.spin_element2, 1, 3)
        self.lbl_element2.hide()
        self.spin_element2.hide()
        
        # ---- 第2行左侧: 间距(动态标签) ----
        self.lbl_spacing = QLabel('间距(m):')
        layout.addWidget(self.lbl_spacing, 2, 0)
        self.spin_array_d = QDoubleSpinBox()
        self.spin_array_d.setRange(0.001, 10.0)
        self.spin_array_d.setDecimals(4)
        self.spin_array_d.setValue(0.0625)
        self.spin_array_d.setSingleStep(0.01)
        self.spin_array_d.valueChanged.connect(self.on_array_param_changed)
        layout.addWidget(self.spin_array_d, 2, 1)
        
        # 第2行右侧: 间距2(用于矩形的列间距)
        self.lbl_d2 = QLabel('')
        self.spin_d2 = QDoubleSpinBox()
        self.spin_d2.setRange(0.001, 10.0)
        self.spin_d2.setDecimals(4)
        self.spin_d2.setValue(0.0625)
        self.spin_d2.setSingleStep(0.01)
        self.spin_d2.valueChanged.connect(self.on_array_param_changed)
        layout.addWidget(self.lbl_d2, 2, 2)
        layout.addWidget(self.spin_d2, 2, 3)
        self.lbl_d2.hide()
        self.spin_d2.hide()
        
        # ---- 第3行左侧: 圆阵半径 ----
        self.lbl_radius = QLabel('半径(m):')
        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setRange(0.001, 10.0)
        self.spin_radius.setDecimals(4)
        self.spin_radius.setValue(0.15)
        self.spin_radius.setSingleStep(0.01)
        self.spin_radius.valueChanged.connect(self.on_array_param_changed)
        layout.addWidget(self.lbl_radius, 3, 0)
        layout.addWidget(self.spin_radius, 3, 1)
        self.lbl_radius.hide()
        self.spin_radius.hide()
        
        # ---- 第3行右侧: 波长 ----
        layout.addWidget(QLabel('波长λ:'), 3, 2)
        self.lbl_wavelength = QLabel('0.1250 m')
        self.lbl_wavelength.setStyleSheet('font-weight: bold; color: #1d4ed8;')
        layout.addWidget(self.lbl_wavelength, 3, 3)
        
        # ---- 第4行: 自定义坐标按钮 ----
        self.btn_edit_coords = QPushButton('✏️ 编辑坐标')
        self.btn_edit_coords.clicked.connect(self.edit_custom_coords)
        layout.addWidget(self.btn_edit_coords, 4, 0, 1, 2)
        self.btn_edit_coords.hide()
        
        parent_layout.addWidget(group)
    
    def _create_signal_config(self, parent_layout):
        group = QGroupBox('信号参数')
        layout = QGridLayout(group)
        
        layout.addWidget(QLabel('载波频率:'), 0, 0)
        self.combo_fc = QComboBox()
        self.combo_fc.addItems(['2.4 GHz', '1.0 GHz', '5.8 GHz', '10 GHz', '自定义'])
        self.combo_fc.setCurrentIndex(0)
        self.combo_fc.currentIndexChanged.connect(self.on_fc_changed)
        layout.addWidget(self.combo_fc, 0, 1)
        
        self.edit_fc_custom = QLineEdit('2400000000')
        self.edit_fc_custom.setPlaceholderText('单位: Hz')
        self.edit_fc_custom.hide()
        layout.addWidget(self.edit_fc_custom, 0, 2)
        
        layout.addWidget(QLabel('默认SNR (dB):'), 1, 0)
        self.spin_snr = QDoubleSpinBox()
        self.spin_snr.setRange(-30, 60)
        self.spin_snr.setValue(20)
        self.spin_snr.setDecimals(1)
        layout.addWidget(self.spin_snr, 1, 1)
        
        layout.addWidget(QLabel('快拍数:'), 2, 0)
        self.spin_snapshots = QSpinBox()
        self.spin_snapshots.setRange(10, 100000)
        self.spin_snapshots.setValue(1000)
        self.spin_snapshots.setSingleStep(100)
        layout.addWidget(self.spin_snapshots, 2, 1)
        
        self.target_table = QTableWidget()
        self.target_table.setColumnCount(5)
        self.target_table.setHorizontalHeaderLabels(['方位°', '俯仰°', '频率kHz', '幅度', 'SNR dB'])
        self.target_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.target_table.setMaximumHeight(115)
        self.target_table.itemChanged.connect(self._on_target_cell_changed)
        layout.addWidget(QLabel('目标信号:'), 3, 0)
        layout.addWidget(self.target_table, 3, 1, 1, 3)
        self._sync_target_rows(1)

        target_btn_layout = QHBoxLayout()
        self.btn_add_target = QPushButton('新增目标')
        self.btn_add_target.clicked.connect(self._add_target_row)
        target_btn_layout.addWidget(self.btn_add_target)
        self.btn_remove_target = QPushButton('删除目标')
        self.btn_remove_target.clicked.connect(self._remove_target_row)
        target_btn_layout.addWidget(self.btn_remove_target)
        target_btn_layout.addStretch()
        layout.addLayout(target_btn_layout, 4, 1, 1, 3)

        nonideal_group = QGroupBox('非理想因素')
        nonideal_layout = QGridLayout(nonideal_group)

        self.chk_phase_error = QCheckBox('阵元相位误差')
        self.spin_phase_error = QDoubleSpinBox()
        self.spin_phase_error.setRange(0, 180)
        self.spin_phase_error.setValue(3)
        self.spin_phase_error.setDecimals(1)
        nonideal_layout.addWidget(self.chk_phase_error, 0, 0)
        nonideal_layout.addWidget(self.spin_phase_error, 0, 1)
        nonideal_layout.addWidget(QLabel('deg RMS'), 0, 2)

        self.chk_amp_error = QCheckBox('阵元幅度误差')
        self.spin_amp_error = QDoubleSpinBox()
        self.spin_amp_error.setRange(0, 20)
        self.spin_amp_error.setValue(0.5)
        self.spin_amp_error.setDecimals(2)
        nonideal_layout.addWidget(self.chk_amp_error, 1, 0)
        nonideal_layout.addWidget(self.spin_amp_error, 1, 1)
        nonideal_layout.addWidget(QLabel('dB RMS'), 1, 2)

        self.chk_pos_error = QCheckBox('阵元位置误差')
        self.spin_pos_error = QDoubleSpinBox()
        self.spin_pos_error.setRange(0, 100)
        self.spin_pos_error.setValue(1)
        self.spin_pos_error.setDecimals(2)
        nonideal_layout.addWidget(self.chk_pos_error, 2, 0)
        nonideal_layout.addWidget(self.spin_pos_error, 2, 1)
        nonideal_layout.addWidget(QLabel('mm RMS'), 2, 2)

        self.chk_freq_offset = QCheckBox('频率偏差')
        self.spin_freq_offset = QDoubleSpinBox()
        self.spin_freq_offset.setRange(0, 1000000)
        self.spin_freq_offset.setValue(100)
        self.spin_freq_offset.setDecimals(1)
        nonideal_layout.addWidget(self.chk_freq_offset, 3, 0)
        nonideal_layout.addWidget(self.spin_freq_offset, 3, 1)
        nonideal_layout.addWidget(QLabel('Hz RMS'), 3, 2)

        layout.addWidget(nonideal_group, 5, 0, 1, 4)
        
        parent_layout.addWidget(group)
    
    def _sync_target_rows(self, count):
        """Resize target table while preserving existing values."""
        if not hasattr(self, 'target_table'):
            return
        count = max(1, min(10, int(count)))
        self.target_table.blockSignals(True)
        old_count = self.target_table.rowCount()
        self.target_table.setRowCount(count)
        for row in range(old_count, count):
            self._set_target_row_defaults(row)
        self.target_table.blockSignals(False)
        if hasattr(self, 'spin_n_sources') and self.spin_n_sources.value() != count:
            self.spin_n_sources.blockSignals(True)
            self.spin_n_sources.setValue(count)
            self.spin_n_sources.blockSignals(False)
        if hasattr(self, 'array_figure'):
            self._plot_array_layout()

    def _add_target_row(self):
        self._sync_target_rows(self.target_table.rowCount() + 1)

    def _remove_target_row(self):
        row_count = self.target_table.rowCount()
        if row_count <= 1:
            QMessageBox.information(self, '提示', '至少保留一个目标信号。')
            return
        selected_rows = sorted({item.row() for item in self.target_table.selectedItems()}, reverse=True)
        if not selected_rows:
            selected_rows = [row_count - 1]
        self.target_table.blockSignals(True)
        for row in selected_rows:
            if self.target_table.rowCount() > 1:
                self.target_table.removeRow(row)
        count = self.target_table.rowCount()
        self.target_table.blockSignals(False)
        if self.spin_n_sources.value() != count:
            self.spin_n_sources.blockSignals(True)
            self.spin_n_sources.setValue(count)
            self.spin_n_sources.blockSignals(False)
        if hasattr(self, 'array_figure'):
            self._plot_array_layout()

    def _set_target_row_defaults(self, row):
        defaults = [
            30 + row * 15,
            0,
            100 * (row + 1),
            1.0,
            self.spin_snr.value() if hasattr(self, 'spin_snr') else 20,
        ]
        for col, value in enumerate(defaults):
            item = QTableWidgetItem(f'{value:g}')
            item.setTextAlignment(Qt.AlignCenter)
            self.target_table.setItem(row, col, item)

    def _on_target_cell_changed(self, item):
        if item is not None and item.row() == 0 and item.column() in (0, 1) and hasattr(self, 'array_figure'):
            self._plot_array_layout()

    def get_targets(self):
        """Read target table rows as signal dictionaries."""
        targets = []
        for row in range(self.target_table.rowCount()):
            values = []
            for col in range(self.target_table.columnCount()):
                item = self.target_table.item(row, col)
                text = item.text().strip() if item is not None else ''
                try:
                    values.append(float(text))
                except ValueError:
                    raise ValueError(f'目标 {row + 1} 的参数格式无效')
            targets.append({
                'theta': values[0],
                'phi': values[1],
                'freq': values[2] * 1000.0,
                'amp': values[3],
                'snr': values[4],
            })
        if not targets:
            raise ValueError('至少需要配置一个目标信号')
        return targets

    def get_imperfections(self):
        """Read enabled non-ideal array and oscillator settings."""
        return {
            'phase_enabled': self.chk_phase_error.isChecked(),
            'phase_std_deg': self.spin_phase_error.value(),
            'amp_enabled': self.chk_amp_error.isChecked(),
            'amp_std_db': self.spin_amp_error.value(),
            'pos_enabled': self.chk_pos_error.isChecked(),
            'pos_std': self.spin_pos_error.value() / 1000.0,
            'freq_enabled': self.chk_freq_offset.isChecked(),
            'freq_offset_std': self.spin_freq_offset.value(),
        }

    def get_primary_target(self):
        targets = self.get_targets()
        return targets[0]
    
    def _create_algorithm_config(self, parent_layout):
        group = QGroupBox('算法选择')
        layout = QHBoxLayout(group)
        
        self.combo_algorithm = QComboBox()
        self.combo_algorithm.addItems([
            'Bartlett (传统相关法)',
            'MUSIC (多信号分类)',
            'ESPRIT (旋转不变子空间)',
        ])
        self.combo_algorithm.setCurrentIndex(1)
        layout.addWidget(self.combo_algorithm, 1)
        
        self.chk_2d = QCheckBox('二维估计(同时估计方位+俯仰)')
        self.chk_2d.setChecked(True)
        layout.addWidget(self.chk_2d)
        
        layout.addWidget(QLabel('信号源数:'))
        self.spin_n_sources = QSpinBox()
        self.spin_n_sources.setRange(1, 10)
        self.spin_n_sources.setValue(1)
        self.spin_n_sources.valueChanged.connect(self._sync_target_rows)
        layout.addWidget(self.spin_n_sources)
        
        layout.addWidget(QLabel('扫描步长°:'))
        self.spin_scan_step = QDoubleSpinBox()
        self.spin_scan_step.setRange(0.01, 5.0)
        self.spin_scan_step.setValue(0.5)
        self.spin_scan_step.setDecimals(2)
        layout.addWidget(self.spin_scan_step)
        
        parent_layout.addWidget(group)
    
    # ---------- 结果面板 ----------
    
    def _create_results_panel(self, parent_layout):
        # 结果Tabs
        self.result_tabs = QTabWidget()
        
        # Tab1: 阵列布局（默认显示）
        array_tab = QWidget()
        array_layout = QVBoxLayout(array_tab)
        
        self.array_figure = Figure(figsize=(6, 4), dpi=120, facecolor='white')
        self.array_canvas = FigureCanvas(self.array_figure)
        self.array_toolbar = NavigationToolbar(self.array_canvas, self)
        array_layout.addWidget(self.array_toolbar)
        array_layout.addWidget(self.array_canvas, 1)
        
        self.result_tabs.addTab(array_tab, '阵列布局 (3D)')
        
        # Tab2: 空间谱
        spectrum_tab = QWidget()
        spectrum_layout = QVBoxLayout(spectrum_tab)
        
        self.spectrum_figure = Figure(figsize=(6, 4), dpi=120, facecolor='white')
        self.spectrum_canvas = FigureCanvas(self.spectrum_figure)
        self.spectrum_toolbar = NavigationToolbar(self.spectrum_canvas, self)
        spectrum_layout.addWidget(self.spectrum_toolbar)
        spectrum_layout.addWidget(self.spectrum_canvas, 1)
        
        self.result_tabs.addTab(spectrum_tab, '空间谱')
        
        # Tab3: 蒙特卡洛结果
        mc_tab = QWidget()
        mc_layout = QVBoxLayout(mc_tab)
        
        self.mc_figure = Figure(figsize=(6, 4), dpi=120, facecolor='white')
        self.mc_canvas = FigureCanvas(self.mc_figure)
        self.mc_toolbar = NavigationToolbar(self.mc_canvas, self)
        mc_layout.addWidget(self.mc_toolbar)
        mc_layout.addWidget(self.mc_canvas, 1)
        
        self.result_tabs.addTab(mc_tab, '蒙特卡洛分析')
        
        parent_layout.addWidget(self.result_tabs, 1)
        
        # 统计信息
        self.txt_stats = QTextEdit()
        self.txt_stats.setMaximumHeight(150)
        self.txt_stats.setReadOnly(True)
        self.txt_stats.setFont(QFont('Consolas', 9))
        self.txt_stats.setText('配置阵列和信号参数后，点击"开始仿真"运行。')
        parent_layout.addWidget(self.txt_stats)
    
    # ---------- 事件处理 ----------
    
    def on_fc_changed(self, idx):
        self.edit_fc_custom.setVisible(idx == self.combo_fc.count() - 1)
        self.update_wavelength()
    
    def get_fc(self):
        idx = self.combo_fc.currentIndex()
        if idx == 0:
            return 2.4e9
        elif idx == 1:
            return 1.0e9
        elif idx == 2:
            return 5.8e9
        elif idx == 3:
            return 10e9
        else:
            try:
                return float(self.edit_fc_custom.text())
            except ValueError:
                return 2.4e9
    
    def update_wavelength(self):
        fc = self.get_fc()
        lambda_ = C / fc
        self.lbl_wavelength.setText(f'{lambda_:.4f} m')
    
    def on_array_type_changed(self, idx):
        """阵列类型切换时显示/隐藏对应参数"""
        # 先全部隐藏
        for w in [self.lbl_element, self.spin_array_N,
                  self.lbl_element2, self.spin_element2,
                  self.lbl_spacing, self.spin_array_d,
                  self.spin_d2, self.lbl_d2,
                  self.lbl_radius, self.spin_radius,
                  self.btn_edit_coords]:
            w.hide()
        
        if idx == 0:  # ULA — 阵元数, 间距
            self.lbl_element.setText('阵元数:')
            self.lbl_element.show()
            self.spin_array_N.show()
            self.spin_array_d.show()
            
        elif idx == 1:  # UCA — 阵元数, 半径
            self.lbl_element.setText('阵元数:')
            self.lbl_element.show()
            self.spin_array_N.show()
            self.lbl_radius.show()
            self.spin_radius.show()
            
        elif idx == 2:  # L型阵列 — X轴阵元, Y轴阵元, 间距
            self.lbl_element.setText('X轴阵元:')
            self.lbl_element.show()
            self.spin_array_N.show()
            self.lbl_element2.setText('Y轴阵元:')
            self.lbl_element2.show()
            self.spin_element2.show()
            self.spin_array_d.show()
            
        elif idx == 3:  # 矩形面阵 — 行数, 列数, 行间距, 列间距
            self.lbl_element.setText('行数:')
            self.lbl_element.show()
            self.spin_array_N.show()
            self.lbl_element2.setText('列数:')
            self.lbl_element2.show()
            self.spin_element2.show()
            self.lbl_spacing.setText('行间距:')
            self.lbl_spacing.show()
            self.spin_array_d.show()
            self.lbl_d2.setText('列间距:')
            self.lbl_d2.show()
            self.spin_d2.show()
            
        elif idx == 4:  # 自定义坐标
            self.btn_edit_coords.show()
        
        self.update_wavelength()
        self._load_default_array()
    
    def on_array_param_changed(self):
        self._load_default_array()
    
    def _on_source_angle_changed(self):
        """角度变化时实时更新3D布局图中的来波方向箭头"""
        self._plot_array_layout()
    
    def get_array_positions(self):
        """根据当前配置获取阵列坐标"""
        idx = self.combo_array_type.currentIndex()
        N = self.spin_array_N.value()
        d = self.spin_array_d.value()
        
        if idx == 0:  # ULA
            return create_ula(N, d)
        elif idx == 1:  # UCA
            radius = self.spin_radius.value()
            return create_uca(N, radius)
        elif idx == 2:  # L阵: X轴阵元=N, Y轴阵元=spin_element2
            Ny = self.spin_element2.value()
            return create_l_array(N, Ny, d)
        elif idx == 3:  # 矩形面阵: 行数=N, 列数=spin_element2, 行间距=d, 列间距=spin_d2
            cols = self.spin_element2.value()
            dx = d
            dy = self.spin_d2.value()
            return create_rect_array(N, cols, dx, dy)
        else:
            # 自定义坐标，使用默认ULA
            return create_ula(4, C / self.get_fc() / 2)
    
    def _load_default_array(self):
        """加载默认阵列并更新阵列布局图"""
        self.array_pos = self.get_array_positions()
        self._plot_array_layout()
    
    def edit_custom_coords(self):
        """打开自定义坐标编辑对话框"""
        from PyQt5.QtWidgets import QDialog, QTableWidget, QHeaderView

        dialog = QDialog(self)
        dialog.setWindowTitle('自定义阵元坐标编辑')
        dialog.setMinimumSize(500, 400)
        dlg_layout = QVBoxLayout(dialog)
        
        # 提示信息
        info_label = QLabel(
            '坐标系说明：右手系 XYZ，X轴为阵面法线方向，Y轴向右，Z轴向上。\n'
            '阵元安装在 Y-Z 平面（X=0），输入 Y 和 Z 坐标即可。'
        )
        info_label.setStyleSheet('color: #334155; font-size: 10px;')
        dlg_layout.addWidget(info_label)
        
        # 表格
        self.coords_table = QTableWidget()
        self.coords_table.setColumnCount(2)
        self.coords_table.setHorizontalHeaderLabels(['Y (m)', 'Z (m)'])
        self.coords_table.horizontalHeader().setStretchLastSection(True)
        self.coords_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        dlg_layout.addWidget(self.coords_table, 1)
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_add = QPushButton('➕ 添加行')
        btn_add.clicked.connect(lambda: self._coords_table_add_row())
        btn_layout.addWidget(btn_add)
        
        btn_remove = QPushButton('➖ 删除选中')
        btn_remove.clicked.connect(lambda: self._coords_table_remove_row())
        btn_layout.addWidget(btn_remove)
        
        btn_layout.addStretch()
        
        btn_import = QPushButton('📂 从CSV导入')
        btn_import.clicked.connect(self._coords_import_csv)
        btn_layout.addWidget(btn_import)
        
        dlg_layout.addLayout(btn_layout)
        
        # 确定/取消
        okcancel = QHBoxLayout()
        okcancel.addStretch()
        btn_ok = QPushButton('确定')
        btn_ok.clicked.connect(lambda: self._coords_table_apply(dialog))
        style_primary_button(btn_ok)
        okcancel.addWidget(btn_ok)
        
        btn_cancel = QPushButton('取消')
        btn_cancel.clicked.connect(dialog.reject)
        okcancel.addWidget(btn_cancel)
        dlg_layout.addLayout(okcancel)
        
        # 加载当前坐标
        if self._custom_coords is not None and len(self._custom_coords) > 0:
            self.coords_table.setRowCount(len(self._custom_coords))
            for i, (y, z) in enumerate(self._custom_coords):
                self.coords_table.setItem(i, 0, QTableWidgetItem(f'{y:.6f}'))
                self.coords_table.setItem(i, 1, QTableWidgetItem(f'{z:.6f}'))
        else:
            # 默认4个阵元L形
            self.coords_table.setRowCount(4)
            default_coords = [[0, 0], [0.0625, 0], [0, 0.0625], [0.125, 0]]
            for i, (y, z) in enumerate(default_coords):
                self.coords_table.setItem(i, 0, QTableWidgetItem(f'{y:.6f}'))
                self.coords_table.setItem(i, 1, QTableWidgetItem(f'{z:.6f}'))
        
        dialog.exec_()
    
    def _coords_table_add_row(self):
        """在自定义坐标表格中添加一行"""
        row = self.coords_table.rowCount()
        self.coords_table.insertRow(row)
        self.coords_table.setItem(row, 0, QTableWidgetItem('0.000000'))
        self.coords_table.setItem(row, 1, QTableWidgetItem('0.000000'))
    
    def _coords_table_remove_row(self):
        """删除选中的行"""
        rows = set()
        for item in self.coords_table.selectedItems():
            rows.add(item.row())
        for row in sorted(rows, reverse=True):
            self.coords_table.removeRow(row)
    
    def _coords_import_csv(self):
        """从CSV文件导入坐标"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, '导入阵元坐标 (CSV)', '', 'CSV文件 (*.csv);;文本文件 (*.txt);;所有文件 (*.*)'
        )
        if not filepath:
            return
        try:
            data = np.loadtxt(filepath, delimiter=',')
            if data.ndim == 1:
                data = data.reshape(-1, 1)
            if data.shape[1] >= 2:
                self.coords_table.setRowCount(len(data))
                for i, row in enumerate(data):
                    self.coords_table.setItem(i, 0, QTableWidgetItem(f'{row[0]:.6f}'))
                    self.coords_table.setItem(i, 1, QTableWidgetItem(f'{row[1]:.6f}'))
                QMessageBox.information(self, '导入成功', f'已导入 {len(data)} 个阵元坐标')
            else:
                QMessageBox.warning(self, '格式错误', 'CSV文件至少需要2列数据 (Y, Z)')
        except Exception as e:
            QMessageBox.warning(self, '导入失败', str(e))
    
    def _coords_table_apply(self, dialog):
        """应用自定义坐标"""
        rows = self.coords_table.rowCount()
        if rows < 2:
            QMessageBox.warning(self, '错误', '至少需要2个阵元')
            return
        coords = []
        for i in range(rows):
            try:
                y = float(self.coords_table.item(i, 0).text())
                z = float(self.coords_table.item(i, 1).text())
                coords.append([y, z])
            except (ValueError, AttributeError) as e:
                QMessageBox.warning(self, '格式错误', f'第 {i+1} 行坐标格式无效')
                return
        
        self._custom_coords = np.array(coords)
        self.array_pos = np.array(coords)
        self.combo_array_type.setCurrentIndex(4)  # 切换到自定义模式
        self._plot_array_layout()
        dialog.accept()
        
        N = len(coords)
        logger.info(f'自定义坐标已应用: {N} 个阵元')
        self._show_status(f'已加载自定义坐标: {N} 个阵元')
    
    # ---------- 绘图函数 ----------
    
    def _plot_array_layout(self):
        """绘制3D阵列布局图（右手系：X=法线, Y=右, Z=上）"""
        if self.array_pos is None or not hasattr(self, 'array_figure'):
            return
        
        from mpl_toolkits.mplot3d import Axes3D, art3d
        
        fig = self.array_figure
        fig.clear()
        ax = fig.add_subplot(111, projection='3d')
        
        pos = self.array_pos  # pos[:,0]=Y, pos[:,1]=Z
        
        # 阵元位于 Y-Z 平面 (X=0)
        xs = np.zeros(len(pos))   # X=0 （法线方向）
        ys = pos[:, 0]            # Y坐标
        zs = pos[:, 1]            # Z坐标
        
        # 绘制阵元
        ax.scatter(xs, ys, zs, s=80, c='#1d4ed8', marker='o', zorder=5, label='阵元')
        
        # 标注编号
        for i, (x, y, z) in enumerate(zip(xs, ys, zs)):
            ax.text(x, y, z, f'  {i+1}', fontsize=8, fontweight='bold', color='#1d4ed8')
        
        # 绘制阵面（矩形的Y-Z平面示意）
        y_margin = max(np.ptp(ys), 0.05) * 0.15
        z_margin = max(np.ptp(zs), 0.05) * 0.15
        y_center = ys.mean()
        z_center = zs.mean()
        
        # 绘制阵面半透明矩形（必须用 numpy 数组）
        y_span = max(np.ptp(ys), 0.05) + y_margin
        z_span = max(np.ptp(zs), 0.05) + z_margin
        xx = np.array([[0, 0], [0, 0]])
        yy = np.array([[y_center - y_span/2, y_center + y_span/2],
                       [y_center - y_span/2, y_center + y_span/2]])
        zz = np.array([[z_center - z_span/2, z_center - z_span/2],
                       [z_center + z_span/2, z_center + z_span/2]])
        ax.plot_surface(xx, yy, zz, alpha=0.06, color='#6366f1')
        
        # 绘制每个目标的来波方向箭头（从阵面中心沿X方向出射）
        try:
            targets = self.get_targets()
        except Exception:
            targets = [{'theta': 30, 'phi': 0}]
        arrow_len = max(y_span, z_span, 0.1) * 0.6
        target_colors = ['#ef4444', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899', '#14b8a6']
        for idx, target in enumerate(targets):
            theta = target['theta']
            phi = target['phi']
            color = target_colors[idx % len(target_colors)]
            dir_x = np.cos(np.deg2rad(phi)) * np.cos(np.deg2rad(theta))
            dir_y = np.cos(np.deg2rad(phi)) * np.sin(np.deg2rad(theta))
            dir_z = np.sin(np.deg2rad(phi))
            ax.quiver(0, y_center, z_center,
                      dir_x * arrow_len, dir_y * arrow_len, dir_z * arrow_len,
                      color=color, linewidth=2.2, arrow_length_ratio=0.15,
                      label=f'目标{idx + 1} θ={theta}°, φ={phi}°')
        
        # 坐标轴标注
        ax.set_xlabel('X (法线)', fontsize=10, labelpad=8)
        ax.set_ylabel('Y (右)', fontsize=10, labelpad=8)
        ax.set_zlabel('Z (上)', fontsize=10, labelpad=8)
        ax.set_title('阵列布局 (3D) - 右手坐标系', fontsize=11, fontweight='bold')
        
        # 设置坐标范围
        max_span = max(y_span, z_span, 0.15)
        ax.set_xlim(-max_span * 0.2, max_span * 1.0)
        ax.set_ylim(y_center - max_span/1.5, y_center + max_span/1.5)
        ax.set_zlim(z_center - max_span/1.5, z_center + max_span/1.5)
        
        # 设置视角（从右前上方看）
        ax.view_init(elev=25, azim=-60)
        
        ax.legend(fontsize=8, loc='upper right')
        
        fig.tight_layout()
        self.array_canvas.draw()
    
    def _plot_spectrum(self, P, thetas, theta_ests, targets):
        """绘制空间谱图"""
        fig = self.spectrum_figure
        fig.clear()
        ax = fig.add_subplot(111)
        
        # 转为dB
        P_db = 10 * np.log10(np.maximum(P, 1e-30))
        ax.plot(thetas, P_db, color='#1d4ed8', linewidth=2.0, label='空间谱')
        
        for idx, target in enumerate(targets):
            theta_true = target['theta']
            label = f'真实{idx + 1}: {theta_true}°' if idx == 0 else f'真实{idx + 1}: {theta_true}°'
            ax.axvline(theta_true, color='#10b981', linestyle='--', linewidth=1.5, alpha=0.8, label=label)

        for idx, theta_est in enumerate(theta_ests):
            ax.axvline(theta_est, color='#ef4444', linestyle=':', linewidth=1.6, alpha=0.9,
                       label=f'估计{idx + 1}: {theta_est:.2f}°')
        
        ax.set_xlabel('角度 (°)')
        ax.set_ylabel('功率 (dB)')
        ax.set_title('DOA估计空间谱', fontsize=12, fontweight='bold')
        ax.grid(True, linestyle='--', alpha=0.3)
        ax.legend(fontsize=9)
        
        fig.tight_layout()
        self.spectrum_canvas.draw()
    
    def _plot_mc_results(self, errors, theta_true, errors_phi=None, phi_true=None):
        """绘制蒙特卡洛结果
        支持1D(仅theta)和2D(theta+phi)两种模式
        """
        fig = self.mc_figure
        fig.clear()
        
        if len(errors) == 0:
            self.mc_canvas.draw()
            return
        
        if errors_phi is not None:
            # 2D模式: 4个子图 (theta直方图, theta散点, phi直方图, phi散点)
            ax1 = fig.add_subplot(221)
            n, bins, patches = ax1.hist(errors, bins='auto', density=True,
                                         alpha=0.7, color='#6366f1', edgecolor='white')
            ax1.axvline(0, color='#10b981', linestyle='--', linewidth=1.5, label='无偏')
            ax1.set_xlabel('θ误差 (°)')
            ax1.set_ylabel('概率密度')
            ax1.set_title('方位角误差分布', fontsize=11, fontweight='bold')
            ax1.grid(True, linestyle='--', alpha=0.3)
            ax1.legend(fontsize=8)
            
            ax2 = fig.add_subplot(222)
            ax2.scatter(range(len(errors)), errors, s=8, alpha=0.5, color='#6366f1')
            ax2.axhline(0, color='#10b981', linestyle='--', linewidth=1.0)
            ax2.set_xlabel('试验次数')
            ax2.set_ylabel('θ误差 (°)')
            ax2.set_title('方位角各次试验误差', fontsize=11, fontweight='bold')
            ax2.grid(True, linestyle='--', alpha=0.3)
            
            ax3 = fig.add_subplot(223)
            n_p, bins_p, patches_p = ax3.hist(errors_phi, bins='auto', density=True,
                                                alpha=0.7, color='#f59e0b', edgecolor='white')
            ax3.axvline(0, color='#10b981', linestyle='--', linewidth=1.5, label='无偏')
            ax3.set_xlabel('φ误差 (°)')
            ax3.set_ylabel('概率密度')
            ax3.set_title('俯仰角误差分布', fontsize=11, fontweight='bold')
            ax3.grid(True, linestyle='--', alpha=0.3)
            ax3.legend(fontsize=8)
            
            ax4 = fig.add_subplot(224)
            ax4.scatter(range(len(errors_phi)), errors_phi, s=8, alpha=0.5, color='#f59e0b')
            ax4.axhline(0, color='#10b981', linestyle='--', linewidth=1.0)
            ax4.set_xlabel('试验次数')
            ax4.set_ylabel('φ误差 (°)')
            ax4.set_title('俯仰角各次试验误差', fontsize=11, fontweight='bold')
            ax4.grid(True, linestyle='--', alpha=0.3)
        else:
            # 1D模式: 2个子图 (保持不变)
            ax1 = fig.add_subplot(121)
            n, bins, patches = ax1.hist(errors, bins='auto', density=True,
                                         alpha=0.7, color='#6366f1', edgecolor='white')
            ax1.axvline(0, color='#10b981', linestyle='--', linewidth=1.5, label='无偏')
            ax1.set_xlabel('误差 (°)')
            ax1.set_ylabel('概率密度')
            ax1.set_title('误差分布直方图', fontsize=11, fontweight='bold')
            ax1.grid(True, linestyle='--', alpha=0.3)
            ax1.legend(fontsize=8)
            
            ax2 = fig.add_subplot(122)
            ax2.scatter(range(len(errors)), errors, s=8, alpha=0.5, color='#6366f1')
            ax2.axhline(0, color='#10b981', linestyle='--', linewidth=1.0)
            ax2.set_xlabel('试验次数')
            ax2.set_ylabel('误差 (°)')
            ax2.set_title('各次试验误差', fontsize=11, fontweight='bold')
            ax2.grid(True, linestyle='--', alpha=0.3)
        
        fig.tight_layout()
        self.mc_canvas.draw()
    
    # ---------- 核心功能 ----------
    
    def _plot_spectrum_2d(self, P, thetas, phis, theta_ests, phi_ests, targets):
        """绘制二维空间谱热力图"""
        fig = self.spectrum_figure
        fig.clear()
        ax = fig.add_subplot(111)
        
        P_db = 10 * np.log10(np.maximum(P, 1e-30))
        im = ax.imshow(P_db, aspect='auto', origin='lower',
                       extent=[thetas[0], thetas[-1], phis[0], phis[-1]],
                       cmap='jet')
        fig.colorbar(im, ax=ax, label='功率 (dB)')
        for idx, target in enumerate(targets):
            ax.plot(target['theta'], target['phi'], 'g*', markersize=13,
                    label=f"真实{idx + 1} θ={target['theta']}°, φ={target['phi']}°")
        for idx, (theta_est, phi_est) in enumerate(zip(theta_ests, phi_ests)):
            ax.plot(theta_est, phi_est, 'rx', markersize=11, markeredgewidth=2.5,
                    label=f'估计{idx + 1} θ={theta_est:.2f}°, φ={phi_est:.2f}°')
        ax.set_xlabel('方位角 (°)')
        ax.set_ylabel('俯仰角 (°)')
        ax.set_title('二维DOA估计空间谱', fontsize=12, fontweight='bold')
        ax.legend(fontsize=9)
        
        fig.tight_layout()
        self.spectrum_canvas.draw()

    def _signal_quality_text(self, P, SNR):
        """Build compact quality metrics that make SNR changes visible."""
        P_db = 10 * np.log10(np.maximum(P, 1e-30))
        peak_db = float(np.nanmax(P_db))
        median_db = float(np.nanmedian(P_db))
        noise_rms = np.sqrt(1.0 / (10 ** (SNR / 10)))
        return (
            f"谱峰-中位噪底: {peak_db - median_db:.2f} dB\n"
            f"相对噪声RMS: {noise_rms:.4f}\n"
            f"说明: 高SNR或快拍数较大时，角度估计会稳定在同一网格点"
        )

    def _format_targets_text(self, targets):
        lines = []
        for idx, target in enumerate(targets):
            lines.append(
                f"真实目标{idx + 1}: θ={target['theta']}°, φ={target['phi']}°, "
                f"f={target['freq'] / 1000:.1f}kHz, SNR={target['snr']}dB"
            )
        return '\n'.join(lines)

    def _format_estimates_1d_text(self, theta_ests):
        return '\n'.join(f"估计峰{idx + 1}: θ={theta:.4f}°" for idx, theta in enumerate(theta_ests))

    def _format_estimates_2d_text(self, theta_ests, phi_ests):
        return '\n'.join(
            f"估计峰{idx + 1}: θ={theta:.4f}°, φ={phi:.4f}°"
            for idx, (theta, phi) in enumerate(zip(theta_ests, phi_ests))
        )

    def _format_matched_errors_1d_text(self, targets, theta_ests):
        unused = set(range(len(theta_ests)))
        lines = []
        for target_idx, target in enumerate(targets):
            if not unused:
                lines.append(f"目标{target_idx + 1}: 未匹配到估计峰")
                continue
            best_idx = min(unused, key=lambda idx: abs(theta_ests[idx] - target['theta']))
            unused.remove(best_idx)
            error_t = theta_ests[best_idx] - target['theta']
            lines.append(
                f"目标{target_idx + 1}匹配估计峰{best_idx + 1}: Δθ={error_t:.4f}°"
            )
        return '\n'.join(lines)

    def _format_matched_errors_2d_text(self, targets, theta_ests, phi_ests):
        estimate_count = min(len(theta_ests), len(phi_ests))
        unused = set(range(estimate_count))
        lines = []
        for target_idx, target in enumerate(targets):
            if not unused:
                lines.append(f"目标{target_idx + 1}: 未匹配到估计峰")
                continue
            best_idx = min(
                unused,
                key=lambda idx: np.hypot(theta_ests[idx] - target['theta'], phi_ests[idx] - target['phi'])
            )
            unused.remove(best_idx)
            error_t = theta_ests[best_idx] - target['theta']
            error_p = phi_ests[best_idx] - target['phi']
            lines.append(
                f"目标{target_idx + 1}匹配估计峰{best_idx + 1}: Δθ={error_t:.4f}°, Δφ={error_p:.4f}°"
            )
        return '\n'.join(lines)
    
    def run_simulation(self):
        """运行单次仿真"""
        if self.array_pos is None:
            QMessageBox.warning(self, '错误', '请先配置阵列')
            return
        if self._sim_thread is not None:
            QMessageBox.information(self, '提示', '仿真正在运行，请稍候。')
            return
        
        try:
            fc = self.get_fc()
            fs = 100e6
            T = self.spin_snapshots.value() / fs
            signals = self.get_targets()
            primary_target = signals[0]
            SNR = primary_target.get('snr', self.spin_snr.value())
            N_signals = len(signals)
            do_2d = self.chk_2d.isChecked()
            
            theta_true = primary_target['theta']
            phi_true = primary_target['phi']
            algo_idx = self.combo_algorithm.currentIndex()
            theta_range = (-90, 90)
            theta_step = self.spin_scan_step.value()
            imperfections = self.get_imperfections()

            if do_2d and algo_idx == 2:
                QMessageBox.warning(self, '错误', 'ESPRIT不支持二维估计，请切换到 Bartlett 或 MUSIC。')
                return
            if algo_idx in (1, 2) and N_signals >= len(self.array_pos):
                QMessageBox.warning(self, '错误', 'MUSIC/ESPRIT要求目标数小于阵元数，请减少目标或增加阵元。')
                return
            if not self._validate_scan_load(do_2d, theta_step):
                return

            self._sim_context = {
                'fc': fc,
                'SNR': SNR,
                'snapshots': self.spin_snapshots.value(),
                'array_name': self.combo_array_type.currentText(),
                'array_count': len(self.array_pos),
            }
            params = {
                'array_pos': self.array_pos.copy(),
                'signals': signals,
                'fc': fc,
                'fs': fs,
                'T': T,
                'SNR': SNR,
                'N_signals': N_signals,
                'do_2d': do_2d,
                'algo_idx': algo_idx,
                'theta_range': theta_range,
                'theta_step': theta_step,
                'theta_true': theta_true,
                'phi_true': phi_true,
                'array_spacing': self.spin_array_d.value(),
                'imperfections': imperfections,
            }

            self.btn_run.setEnabled(False)
            self.btn_run.setText('仿真计算中...')
            self.txt_stats.setText(
                f'仿真正在后台运行...\n快拍数: {self.spin_snapshots.value()}\n扫描步长: {theta_step}°'
            )
            self._show_status('仿真正在后台运行...')

            self._sim_thread = QThread(self)
            self._sim_worker = SimulationWorker(params)
            self._sim_worker.moveToThread(self._sim_thread)
            self._sim_thread.started.connect(self._sim_worker.run)
            self._sim_worker.finished.connect(self._on_simulation_finished)
            self._sim_worker.failed.connect(self._on_simulation_failed)
            self._sim_worker.finished.connect(self._sim_thread.quit)
            self._sim_worker.failed.connect(self._sim_thread.quit)
            self._sim_worker.finished.connect(self._sim_worker.deleteLater)
            self._sim_worker.failed.connect(self._sim_worker.deleteLater)
            self._sim_thread.finished.connect(self._sim_thread.deleteLater)
            self._sim_thread.finished.connect(self._cleanup_simulation_worker)
            self._sim_thread.start()
            
        except Exception as e:
            logger.error(f'仿真失败: {e}')
            QMessageBox.warning(self, '仿真错误', str(e))

    def _validate_scan_load(self, do_2d, theta_step):
        """Prevent accidental huge 2D grids that would exhaust time or memory."""
        if not do_2d:
            return True
        n_theta = int(np.floor(180 / theta_step)) + 1
        grid_points = n_theta * n_theta
        if grid_points <= 1_000_000:
            return True

        recommended_step = np.sqrt((180 * 180) / 1_000_000)
        QMessageBox.warning(
            self,
            '扫描步长过小',
            f'当前二维扫描约 {grid_points:,} 个网格点，计算量过大。\n'
            f'请把扫描步长调到 {recommended_step:.2f}° 或更大，或先关闭二维估计。'
        )
        return False

    def _on_simulation_finished(self, result):
        """Render a simulation result after worker completion."""
        ctx = self._sim_context or {}
        SNR = ctx.get('SNR', 0)
        fc = ctx.get('fc', 0)
        P = result['P']

        if result.get('do_2d'):
            theta_est = result['theta_est']
            phi_est = result['phi_est']
            theta_ests = result.get('theta_ests') or [theta_est]
            phi_ests = result.get('phi_ests') or [phi_est]
            theta_true = result['theta_true']
            phi_true = result['phi_true']
            targets = result.get('targets') or [{'theta': theta_true, 'phi': phi_true, 'freq': 0, 'snr': SNR}]
            self._plot_spectrum_2d(P, result['thetas'], result['phis'], theta_ests, phi_ests, targets)
            stats_text = (
                f"算法: {result['algo_name']}\n"
                f"{self._format_targets_text(targets)}\n"
                f"{self._format_estimates_2d_text(theta_ests, phi_ests)}\n"
                f"{self._format_matched_errors_2d_text(targets, theta_ests, phi_ests)}\n"
                f"阵列: {ctx.get('array_name', '')}\n"
                f"阵元数: {ctx.get('array_count', 0)}\n"
                f"载波频率: {fc/1e9:.2f} GHz\n"
                f"SNR: {SNR:.1f} dB\n"
                f"快拍数: {ctx.get('snapshots', 0)}\n"
                f"{self._signal_quality_text(P, SNR)}"
            )
            self.txt_stats.setText(stats_text)
            self.sim_result = {
                'theta_est': theta_est,
                'phi_est': phi_est,
                'theta_ests': theta_ests,
                'phi_ests': phi_ests,
                'theta_true': theta_true,
                'phi_true': phi_true,
                'algorithm': result['algo_name'],
            }
            self._show_status(f'✅ 2D DOA完成: θ={theta_est:.2f}°, φ={phi_est:.2f}°')
        else:
            theta_est = result['theta_est']
            theta_ests = result.get('theta_ests') or [theta_est]
            theta_true = result['theta_true']
            targets = result.get('targets') or [{'theta': theta_true, 'phi': 0, 'freq': 0, 'snr': SNR}]
            self._plot_spectrum(P, result['thetas'], theta_ests, targets)
            stats_text = (
                f"算法: {result['algo_name']}\n"
                f"{self._format_targets_text(targets)}\n"
                f"{self._format_estimates_1d_text(theta_ests)}\n"
                f"{self._format_matched_errors_1d_text(targets, theta_ests)}\n"
                f"阵列: {ctx.get('array_name', '')}\n"
                f"阵元数: {ctx.get('array_count', 0)}\n"
                f"载波频率: {fc/1e9:.2f} GHz\n"
                f"SNR: {SNR:.1f} dB\n"
                f"快拍数: {ctx.get('snapshots', 0)}\n"
                f"{self._signal_quality_text(P, SNR)}"
            )
            self.txt_stats.setText(stats_text)
            self.sim_result = {
                'theta_est': theta_est,
                'theta_ests': theta_ests,
                'theta_true': theta_true,
                'algorithm': result['algo_name'],
            }
            self._show_status(f'✅ DOA估计完成: {theta_est:.2f}°')

        logger.info(f"仿真完成: 算法={result['algo_name']}")

    def _on_simulation_failed(self, message):
        """Show simulation worker errors on the UI thread."""
        logger.error(f'仿真失败: {message}')
        QMessageBox.warning(self, '仿真错误', message)

    def _cleanup_simulation_worker(self):
        self.btn_run.setEnabled(True)
        self.btn_run.setText('▶ 开始仿真')
        self._sim_thread = None
        self._sim_worker = None
        self._sim_context = None
    
    def run_monte_carlo(self):
        """运行蒙特卡洛仿真"""
        if self.array_pos is None:
            QMessageBox.warning(self, '错误', '请先配置阵列')
            return
        if self._mc_thread is not None:
            QMessageBox.information(self, '提示', '蒙特卡洛分析正在运行，请稍候。')
            return
        
        try:
            fc = self.get_fc()
            fs = 100e6
            T = self.spin_snapshots.value() / fs
            signals = self.get_targets()
            primary_target = signals[0]
            SNR = primary_target.get('snr', self.spin_snr.value())
            N_signals = len(signals)
            do_2d = self.chk_2d.isChecked()
            
            theta_true = primary_target['theta']
            phi_true = primary_target['phi']
            
            algo_idx = self.combo_algorithm.currentIndex()
            if do_2d and algo_idx == 2:
                QMessageBox.warning(self, '错误', 'ESPRIT不支持二维蒙特卡洛估计，请切换到 Bartlett 或 MUSIC。')
                return
            if algo_idx in (1, 2) and N_signals >= len(self.array_pos):
                QMessageBox.warning(self, '错误', 'MUSIC/ESPRIT要求目标数小于阵元数，请减少目标或增加阵元。')
                return

            N_trials = 30 if do_2d else 200
            theta_step = self.spin_scan_step.value()
            mc_step = max(theta_step, 2.0) if do_2d else theta_step
            imperfections = self.get_imperfections()
            self._mc_context = {
                'theta_true': theta_true,
                'phi_true': phi_true,
                'N_trials': N_trials,
                'mc_step': mc_step,
                'array_name': self.combo_array_type.currentText(),
                'array_count': len(self.array_pos),
                'SNR': SNR,
                'snapshots': self.spin_snapshots.value(),
            }
            params = {
                'array_pos': self.array_pos.copy(),
                'signals': signals,
                'fc': fc,
                'fs': fs,
                'T': T,
                'SNR': SNR,
                'N_trials': N_trials,
                'do_2d': do_2d,
                'algo_idx': algo_idx,
                'theta_step': mc_step,
                'phi_true': phi_true,
                'imperfections': imperfections,
            }

            self.btn_mc.setEnabled(False)
            self.btn_mc.setText('蒙特卡洛计算中...')
            self.txt_stats.setText(f'蒙特卡洛分析正在后台运行...\n试验次数: {N_trials}\n扫描步长: {mc_step}°')
            self._show_status('蒙特卡洛分析正在后台运行...')

            self._mc_thread = QThread(self)
            self._mc_worker = MonteCarloWorker(params)
            self._mc_worker.moveToThread(self._mc_thread)
            self._mc_thread.started.connect(self._mc_worker.run)
            self._mc_worker.finished.connect(self._on_monte_carlo_finished)
            self._mc_worker.failed.connect(self._on_monte_carlo_failed)
            self._mc_worker.finished.connect(self._mc_thread.quit)
            self._mc_worker.failed.connect(self._mc_thread.quit)
            self._mc_worker.finished.connect(self._mc_worker.deleteLater)
            self._mc_worker.failed.connect(self._mc_worker.deleteLater)
            self._mc_thread.finished.connect(self._mc_thread.deleteLater)
            self._mc_thread.finished.connect(self._cleanup_monte_carlo_worker)
            self._mc_thread.start()
                
        except Exception as e:
            logger.error(f'蒙特卡洛仿真失败: {e}')
            QMessageBox.warning(self, '仿真错误', str(e))

    def _on_monte_carlo_finished(self, result):
        """Render Monte Carlo results after worker completion."""
        ctx = self._mc_context or {}
        theta_true = ctx.get('theta_true', 0)
        phi_true = ctx.get('phi_true', 0)
        N_trials = ctx.get('N_trials', 0)
        mc_step = ctx.get('mc_step', 0)

        if result.get('do_2d'):
            errors_t = result['errors_t']
            errors_p = result['errors_p']
            self.mc_errors = errors_t
            self._plot_mc_results(errors_t, theta_true, errors_phi=errors_p, phi_true=phi_true)
            stats_text = (
                f"算法: {result['algo_name']}\n"
                f"蒙特卡洛试验次数: {N_trials}\n"
                f"扫描步长: {mc_step}°\n"
                f"真实方位角: {theta_true}°\n"
                f"--- 方位角性能 ---\n"
                f"RMSE: {result['rmse_t']:.4f}°  偏差: {result['bias_t']:.4f}°  标准差: {result['std_t']:.4f}°\n"
                f"--- 俯仰角性能 ---\n"
                f"RMSE: {result['rmse_p']:.4f}°\n"
                f"--- 配置 ---\n"
                f"阵列: {ctx.get('array_name', '')}\n"
                f"阵元数: {ctx.get('array_count', 0)}\n"
                f"SNR: {ctx.get('SNR', 0):.1f} dB\n"
                f"快拍数: {ctx.get('snapshots', 0)}\n"
                f"说明: 高SNR或快拍数较大时，RMSE可能稳定为0"
            )
            self.txt_stats.setText(stats_text)
            self._show_status(f"✅ 2D蒙特卡洛完成: RMSE_θ={result['rmse_t']:.4f}°, RMSE_φ={result['rmse_p']:.4f}°")
        else:
            errors = result['errors']
            self.mc_errors = errors
            self._plot_mc_results(errors, theta_true)
            stats_text = (
                f"算法: {result['algo_name']}\n"
                f"蒙特卡洛试验次数: {N_trials}\n"
                f"扫描步长: {mc_step}°\n"
                f"真实角度: {theta_true}°\n"
                f"--- 性能指标 ---\n"
                f"RMSE: {result['rmse']:.4f}°\n"
                f"偏差 (Bias): {result['bias']:.4f}°\n"
                f"标准差 (Std): {result['std_dev']:.4f}°\n"
                f"--- 配置 ---\n"
                f"阵列: {ctx.get('array_name', '')}\n"
                f"阵元数: {ctx.get('array_count', 0)}\n"
                f"SNR: {ctx.get('SNR', 0):.1f} dB\n"
                f"快拍数: {ctx.get('snapshots', 0)}\n"
                f"说明: 高SNR或快拍数较大时，RMSE可能稳定为0"
            )
            self.txt_stats.setText(stats_text)
            self._show_status(f"✅ 蒙特卡洛评估完成: RMSE={result['rmse']:.4f}°")

        logger.info(f"蒙特卡洛完成: 算法={result['algo_name']}, 次数={N_trials}, 步长={mc_step}°")

    def _on_monte_carlo_failed(self, message):
        """Show Monte Carlo worker errors on the UI thread."""
        logger.error(f'蒙特卡洛仿真失败: {message}')
        QMessageBox.warning(self, '仿真错误', message)

    def _cleanup_monte_carlo_worker(self):
        self.btn_mc.setEnabled(True)
        self.btn_mc.setText('🎲 蒙特卡洛评估')
        self._mc_thread = None
        self._mc_worker = None
        self._mc_context = None
    
    def clear_results(self):
        """清除所有结果"""
        for fig in [self.spectrum_figure, self.array_figure, self.mc_figure]:
            fig.clear()
            fig.canvas.draw()
        
        self.txt_stats.setText('结果已清除。')
        self.sim_result = None
        self.mc_errors = None
        logger.info('用户操作: 清除仿真结果')
        self._show_status('结果已清除')

    def _show_status(self, message):
        """Show a message when the panel is attached to a main window."""
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage(message)
    
    def statusBar(self):
        """获取父窗口的状态栏"""
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'statusBar'):
                return parent.statusBar()
            parent = parent.parent()
        return None
