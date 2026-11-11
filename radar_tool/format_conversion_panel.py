"""Format conversion workspace for radar engineering files."""

from __future__ import annotations

import os
import threading
import time

from PyQt5.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .format_conversion import (
    FormatConversionCancelled,
    FormatConversionError,
    FormatConversionTimeout,
    TrConversionResult,
    build_tr_amplitude_phase_bin,
    load_tr_amplitude_phase_bin,
    rows_to_tr_text,
    write_bytes_atomic,
    write_text_atomic,
)
from .errors import ExportError, safe_exception_message
from .background_tasks import (
    ensure_task_can_start, register_background_task, task_result_is_current,
)
from .logger import get_logger
from .ui_theme import set_button_icon, style_primary_button


logger = get_logger('format_conversion_panel')


class FormatConversionWorker(QObject):
    """Run one bounded format parse outside the Qt UI thread."""

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, filepath, txt_to_bin, timeout_seconds):
        super().__init__()
        self._filepath = filepath
        self._txt_to_bin = txt_to_bin
        self._timeout_seconds = timeout_seconds
        self._cancel_event = threading.Event()
        self._timed_out = False
        self._deadline = time.monotonic() + timeout_seconds

    def cancel(self, timed_out=False):
        self._cancel_event.set()
        self._timed_out = timed_out

    def run(self):
        try:
            self.progress.emit(5, '开始解析')
            if self._cancel_event.is_set():
                raise FormatConversionCancelled('解析已取消')
            if self._txt_to_bin:
                result = build_tr_amplitude_phase_bin(
                    self._filepath,
                    self._cancel_event,
                    self._deadline,
                    self._timeout_seconds,
                )
            else:
                result = load_tr_amplitude_phase_bin(
                    self._filepath,
                    self._cancel_event,
                    self._deadline,
                    self._timeout_seconds,
                )
        except FormatConversionCancelled as exc:
            if self._timed_out:
                self.failed.emit(
                    f'解析超时：允许 0~{self._timeout_seconds:g} 秒')
            else:
                self.cancelled.emit(safe_exception_message(exc))
        except FormatConversionTimeout as exc:
            self.failed.emit(safe_exception_message(exc))
        except (FormatConversionError, ExportError) as exc:
            self.failed.emit(safe_exception_message(exc))
        except Exception:
            logger.exception('格式解析后台任务失败')
            self.failed.emit('解析失败：发生未预期错误')
        else:
            self.progress.emit(100, '解析完成')
            self.finished.emit(result)


class FormatConversionPanel(QWidget):
    """Convert and validate parameter files using explicit protocol profiles."""

    TXT_TO_BIN = 0
    BIN_TO_TXT = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.preview_result = None  # type: TrConversionResult | None
        self._preview_source_path = ''
        self._parse_thread = None
        self._parse_worker = None
        self._timeout_timer = None
        self._preview_in_progress = False
        self._pending_convert = False
        self._parse_task_name = ''
        self._parse_task_version = 0
        self.parse_timeout_seconds = 30.0
        self._init_ui()
        self._update_direction()
        logger.info('格式转换面板已创建')

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel('格式转换')
        title.setStyleSheet('font-size: 18px; font-weight: bold; color: #172033;')
        subtitle = QLabel('TR 幅相参数协议转换与回读校验')
        subtitle.setStyleSheet('color: #64748b;')
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addLayout(title_box)
        heading.addStretch()
        self.status_badge = QLabel('等待选择文件')
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setMinimumWidth(130)
        self._set_status('等待选择文件', 'idle')
        heading.addWidget(self.status_badge)
        root.addLayout(heading)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._create_control_area())
        splitter.addWidget(self._create_result_area())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        # 左侧控制区按需求宽度起步并参与分配，避免被右侧结果区挤占
        splitter.setSizes([520, 1000])
        root.addWidget(splitter, 1)

    def _create_control_area(self):
        container = QWidget()
        container.setMinimumWidth(370)
        container.setMaximumWidth(520)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 6, 0)

        workflow = QGroupBox('转换任务')
        grid = QGridLayout(workflow)
        grid.setColumnStretch(1, 1)

        grid.addWidget(QLabel('格式:'), 0, 0)
        self.direction_combo = QComboBox()
        self.direction_combo.addItems((
            'TR 幅相 TXT → 合并 BIN',
            'TR 合并 BIN → 幅相 TXT',
        ))
        self.direction_combo.currentIndexChanged.connect(self._update_direction)
        grid.addWidget(self.direction_combo, 0, 1, 1, 2)

        grid.addWidget(QLabel('输入:'), 1, 0)
        self.source_edit = QLineEdit()
        self.source_edit.setReadOnly(True)
        self.source_edit.setPlaceholderText('选择待转换文件')
        grid.addWidget(self.source_edit, 1, 1)
        self.source_button = QPushButton()
        self.source_button.setToolTip('选择输入文件')
        set_button_icon(self.source_button, 'open')
        self.source_button.clicked.connect(self._choose_source)
        grid.addWidget(self.source_button, 1, 2)

        grid.addWidget(QLabel('输出:'), 2, 0)
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText('选择输出文件')
        self.target_edit.textChanged.connect(self._invalidate_preview)
        grid.addWidget(self.target_edit, 2, 1)
        self.target_button = QPushButton()
        self.target_button.setToolTip('选择输出文件')
        set_button_icon(self.target_button, 'save')
        self.target_button.clicked.connect(self._choose_target)
        grid.addWidget(self.target_button, 2, 2)

        button_row = QHBoxLayout()
        self.preview_button = QPushButton('预检')
        self.preview_button.setToolTip('解析输入并校验全部帧')
        set_button_icon(self.preview_button, 'reload')
        self.preview_button.clicked.connect(self._preview)
        button_row.addWidget(self.preview_button)
        self.convert_button = QPushButton('执行转换')
        self.convert_button.setToolTip('严格校验后写入目标文件')
        set_button_icon(self.convert_button, 'save')
        style_primary_button(self.convert_button)
        self.convert_button.clicked.connect(self._convert)
        button_row.addWidget(self.convert_button, 1)
        self.cancel_button = QPushButton('取消')
        self.cancel_button.setToolTip('取消正在执行的解析任务')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_parse)
        button_row.addWidget(self.cancel_button)
        grid.addLayout(button_row, 3, 0, 1, 3)
        layout.addWidget(workflow)

        protocol = QGroupBox('协议摘要')
        protocol_layout = QGridLayout(protocol)
        entries = (
            ('输入结构', '每块 64 行，通道严格 1~64'),
            ('数据列', '通道 / 幅度(dB) / 相位(°)'),
            ('量化规则', '0.1 单位，int16，大端序'),
            ('帧结构', '270 字节，最多 24 帧'),
            ('完整性', '逐帧 8 位累加和'),
        )
        for row, (name, value) in enumerate(entries):
            name_label = QLabel(name)
            name_label.setStyleSheet('color: #64748b;')
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            protocol_layout.addWidget(name_label, row, 0, Qt.AlignTop)
            protocol_layout.addWidget(value_label, row, 1)
        protocol_layout.setColumnStretch(1, 1)
        layout.addWidget(protocol)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont('Consolas', 9))
        self.log_text.setPlaceholderText('预检结果与转换状态')
        layout.addWidget(self.log_text, 1)
        return container

    def _create_result_area(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        summary_row = QHBoxLayout()
        self.summary_labels = []
        for caption in ('有效行', '帧数', 'BIN 字节', '协议状态'):
            label = QLabel(f'{caption}\n--')
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumHeight(54)
            label.setStyleSheet(
                'QLabel { background: #f8fafc; border: 1px solid #d7dee9; '
                'border-radius: 6px; padding: 5px; color: #334155; }'
            )
            summary_row.addWidget(label, 1)
            self.summary_labels.append(label)
        layout.addLayout(summary_row)

        frame_group = QGroupBox('帧预检')
        frame_layout = QVBoxLayout(frame_group)
        self.frame_table = QTableWidget(0, 5)
        self.frame_table.setHorizontalHeaderLabels(
            ('包序号', '类型', '温度字节', '累加和', '说明'))
        self.frame_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.frame_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.frame_table.setAlternatingRowColors(True)
        header = self.frame_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        frame_layout.addWidget(self.frame_table)
        layout.addWidget(frame_group, 1)

        data_group = QGroupBox('数据预览（前 128 行）')
        data_layout = QVBoxLayout(data_group)
        self.data_table = QTableWidget(0, 4)
        self.data_table.setHorizontalHeaderLabels(('块', '通道', '幅度 dB', '相位 °'))
        self.data_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.data_table.setAlternatingRowColors(True)
        self.data_table.verticalHeader().setVisible(False)
        data_header = self.data_table.horizontalHeader()
        data_header.setSectionResizeMode(QHeaderView.Stretch)
        data_layout.addWidget(self.data_table)
        layout.addWidget(data_group, 2)
        return container

    def _set_status(self, text, state):
        colors = {
            'idle': ('#f1f5f9', '#475569', '#cbd5e1'),
            'running': ('#eff6ff', '#1d4ed8', '#bfdbfe'),
            'success': ('#ecfdf5', '#166534', '#86efac'),
            'error': ('#fef2f2', '#b91c1c', '#fca5a5'),
        }
        background, foreground, border = colors[state]
        self.status_badge.setText(text)
        self.status_badge.setStyleSheet(
            f'background: {background}; color: {foreground}; border: 1px solid {border}; '
            'border-radius: 6px; padding: 6px 10px; font-weight: 600;'
        )

    def _update_direction(self):
        self.source_edit.clear()
        self.target_edit.clear()
        self._clear_preview()
        if self.direction_combo.currentIndex() == self.TXT_TO_BIN:
            self.source_edit.setPlaceholderText('选择三列幅相参数 TXT')
            self.target_edit.setPlaceholderText('输出 tr_all_inject.bin')
        else:
            self.source_edit.setPlaceholderText('选择 TR 合并 BIN')
            self.target_edit.setPlaceholderText('输出回读 TXT')

    def _choose_source(self):
        if self.direction_combo.currentIndex() == self.TXT_TO_BIN:
            file_filter = '幅相文本 (*.txt);;所有文件 (*.*)'
            title = '选择 TR 幅相参数 TXT'
        else:
            file_filter = '二进制数据 (*.bin);;所有文件 (*.*)'
            title = '选择 TR 合并 BIN'
        filepath, _ = QFileDialog.getOpenFileName(self, title, '', file_filter)
        if not filepath:
            return
        self.source_edit.setText(filepath)
        base_dir = os.path.dirname(filepath)
        if self.direction_combo.currentIndex() == self.TXT_TO_BIN:
            target = os.path.join(base_dir, 'tr_all_inject.bin')
        else:
            stem = os.path.splitext(os.path.basename(filepath))[0]
            target = os.path.join(base_dir, f'{stem}_decoded.txt')
        self.target_edit.setText(target)
        self._preview()

    def _choose_target(self):
        if self.direction_combo.currentIndex() == self.TXT_TO_BIN:
            title = '保存合并 BIN'
            file_filter = '二进制数据 (*.bin)'
            default_suffix = '.bin'
        else:
            title = '保存回读 TXT'
            file_filter = '文本文件 (*.txt)'
            default_suffix = '.txt'
        filepath, _ = QFileDialog.getSaveFileName(
            self, title, self.target_edit.text().strip(), file_filter)
        if not filepath:
            return
        if not os.path.splitext(filepath)[1]:
            filepath += default_suffix
        self.target_edit.setText(filepath)

    def _invalidate_preview(self):
        # Output path changes do not invalidate parsed bytes, but do clear a stale success banner.
        if self.preview_result is not None:
            self._set_status('预检通过', 'success')

    def _clear_preview(self):
        self.preview_result = None
        self._preview_source_path = ''
        self.frame_table.setRowCount(0)
        self.data_table.setRowCount(0)
        for label, caption in zip(
            self.summary_labels, ('有效行', '帧数', 'BIN 字节', '协议状态')):
            label.setText(f'{caption}\n--')
        self.log_text.clear()
        self._set_status('等待选择文件', 'idle')

    def closeEvent(self, event):
        self._cancel_parse()
        if self._parse_thread is not None:
            self._parse_thread.quit()
            self._parse_thread.wait(5000)
        super().closeEvent(event)

    def _set_parse_controls(self, running):
        self.preview_button.setEnabled(not running)
        self.convert_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.source_button.setEnabled(not running)
        self.direction_combo.setEnabled(not running)

    def _start_parse(self, pending_convert=False):
        filepath = self.source_edit.text().strip()
        if not filepath:
            self._show_parse_failure('请先选择输入文件')
            return False
        if not os.path.isfile(filepath):
            self._show_parse_failure('输入文件不存在')
            return False
        if self._preview_in_progress:
            self._pending_convert = self._pending_convert or pending_convert
            return True
        if self._parse_thread is not None:
            if not self._parse_thread.isFinished():
                self._parse_thread.quit()
                self._parse_thread.wait(100)
            if not self._parse_thread.isFinished():
                self._show_parse_failure('上一个解析任务尚未结束，请稍后重试')
                return False
            self._parse_worker = None
            self._parse_thread = None

        task_name = f'格式解析：{os.path.basename(filepath)}'
        try:
            ensure_task_can_start(self, task_name)
        except ValueError as exc:
            self._show_parse_failure(str(exc))
            return False
        self._pending_convert = pending_convert
        self._parse_task_name = task_name
        self._preview_in_progress = True
        self._set_parse_controls(True)
        self._set_status('解析中', 'running')
        self.log_text.setPlainText('正在后台解析输入文件，可随时取消。')

        txt_to_bin = self.direction_combo.currentIndex() == self.TXT_TO_BIN
        self._parse_thread = QThread(self)
        self._parse_worker = FormatConversionWorker(
            filepath, txt_to_bin, self.parse_timeout_seconds)
        self._parse_worker.moveToThread(self._parse_thread)
        self._parse_thread.started.connect(self._parse_worker.run)
        self._parse_worker.finished.connect(self._on_parse_finished)
        self._parse_worker.failed.connect(self._on_parse_failed)
        self._parse_worker.cancelled.connect(self._on_parse_cancelled)
        self._parse_worker.finished.connect(self._parse_thread.quit)
        self._parse_worker.failed.connect(self._parse_thread.quit)
        self._parse_worker.cancelled.connect(self._parse_thread.quit)
        self._parse_thread.finished.connect(self._parse_worker.deleteLater)
        self._parse_thread.finished.connect(self._parse_thread.deleteLater)
        self._parse_thread.finished.connect(
            lambda thread=self._parse_thread: self._on_parse_thread_finished(thread))

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_parse_timeout)
        self._timeout_timer.start(max(1, int(self.parse_timeout_seconds * 1000)))
        self._parse_task_version = register_background_task(
            self,
            task_name,
            self._parse_thread,
            self._parse_worker,
            self._parse_worker.cancel,
        )
        self._parse_thread.start()
        return True

    def _show_parse_failure(self, message):
        self.preview_result = None
        self._preview_source_path = ''
        self._preview_in_progress = False
        self._pending_convert = False
        self._set_parse_controls(False)
        self._set_status('预检失败', 'error')
        self.log_text.setPlainText(message)
        self.frame_table.setRowCount(0)
        self.data_table.setRowCount(0)
        logger.warning('格式预检失败: %s', message)

    def _finish_parse_job(self):
        if self._timeout_timer is not None:
            self._timeout_timer.stop()
            self._timeout_timer = None
        self._preview_in_progress = False
        self._set_parse_controls(False)

    def _on_parse_thread_finished(self, thread):
        if thread is self._parse_thread:
            self._parse_worker = None
            self._parse_thread = None

    def _on_parse_finished(self, result):
        if (
            not self._preview_in_progress
            or not task_result_is_current(
                self, self._parse_task_name, self._parse_task_version
            )
        ):
            return
        self.preview_result = result
        self._preview_source_path = self.source_edit.text().strip()
        self._render_result(result)
        self._set_status('预检通过', 'success')
        pending_convert = self._pending_convert
        self._pending_convert = False
        self._finish_parse_job()
        if pending_convert:
            self._perform_convert()

    def _on_parse_failed(self, message):
        if (
            not self._preview_in_progress
            or not task_result_is_current(
                self, self._parse_task_name, self._parse_task_version
            )
        ):
            return
        self._pending_convert = False
        self._finish_parse_job()
        self._show_parse_failure(message)

    def _on_parse_cancelled(self, message):
        if (
            not self._preview_in_progress
            or not task_result_is_current(
                self, self._parse_task_name, self._parse_task_version
            )
        ):
            return
        self._pending_convert = False
        self._finish_parse_job()
        self.preview_result = None
        self._preview_source_path = ''
        self._set_status('已取消', 'idle')
        self.log_text.setPlainText(message)
        self.frame_table.setRowCount(0)
        self.data_table.setRowCount(0)
        logger.info('格式解析已取消')

    def _on_parse_timeout(self):
        if self._parse_worker is not None:
            self._parse_worker.cancel(timed_out=True)

    def _cancel_parse(self):
        if self._parse_worker is not None:
            self._parse_worker.cancel()
            self._set_status('取消中', 'running')
            self.log_text.setPlainText('正在取消解析任务……')

    def _preview(self):
        if self._preview_in_progress:
            return True
        return self._start_parse(pending_convert=False)

    def _render_result(self, result):
        values = (
            ('有效行', str(len(result.rows))),
            ('帧数', str(result.block_count)),
            ('BIN 字节', str(len(result.data))),
            ('协议状态', '通过'),
        )
        for label, (caption, value) in zip(self.summary_labels, values):
            label.setText(f'{caption}\n{value}')

        self.frame_table.setRowCount(len(result.frames))
        for row, frame in enumerate(result.frames):
            values = (
                str(frame.index), frame.mode, f'0x{frame.temperature:02X}',
                f'0x{frame.checksum:02X}', frame.description,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column < 4:
                    item.setTextAlignment(Qt.AlignCenter)
                self.frame_table.setItem(row, column, item)

        preview_rows = result.rows[:128]
        self.data_table.setRowCount(len(preview_rows))
        for row, (channel, amplitude, phase) in enumerate(preview_rows):
            block = row // 64 + 1
            for column, value in enumerate(
                (str(block), str(channel), f'{amplitude:g}', f'{phase:g}')):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                self.data_table.setItem(row, column, item)

        direction = 'TXT → BIN' if self.direction_combo.currentIndex() == 0 else 'BIN → TXT'
        self.log_text.setPlainText(
            f'转换方向: {direction}\n'
            f'严格校验通过: {len(result.rows)} 行 / {result.block_count} 帧\n'
            f'数据流长度: {len(result.data)} 字节\n'
            '帧头、命令字、包序号与累加和均符合 TR 幅相协议。'
        )

    def _convert(self):
        target = self.target_edit.text().strip()
        if not target:
            QMessageBox.warning(self, '缺少输出文件', '请选择输出文件。')
            return False
        source = self.source_edit.text().strip()
        if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(target)):
            QMessageBox.warning(self, '输出路径无效', '输出文件不能与输入文件相同。')
            return False
        if os.path.exists(target):
            answer = QMessageBox.question(
                self,
                '确认覆盖',
                f'输出文件已存在，是否覆盖？\n{target}',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False

        source_current = (
            self.preview_result is not None
            and os.path.normcase(os.path.abspath(self._preview_source_path))
            == os.path.normcase(os.path.abspath(source))
        )
        if source_current and not self._preview_in_progress:
            return self._perform_convert()
        if self._preview_in_progress:
            self._pending_convert = True
            self.log_text.append('\n解析完成后将自动执行转换。')
            return True
        return self._start_parse(pending_convert=True)

    def _perform_convert(self):
        target = self.target_edit.text().strip()
        if not target or self.preview_result is None:
            QMessageBox.warning(self, '无法转换', '预检结果已失效，请重新预检。')
            return False
        try:
            if self.direction_combo.currentIndex() == self.TXT_TO_BIN:
                write_bytes_atomic(target, self.preview_result.data)
            else:
                write_text_atomic(target, rows_to_tr_text(self.preview_result.rows))
        except FormatConversionError as exc:
            self._set_status('写入失败', 'error')
            self.log_text.append(f'\n写入失败: {safe_exception_message(exc)}')
            QMessageBox.critical(self, '转换失败', safe_exception_message(exc))
            logger.exception('格式转换写入失败')
            return False

        self._set_status('转换完成', 'success')
        self.log_text.append(f'\n转换完成: {target}')
        logger.info('格式转换完成: %s', target)
        QMessageBox.information(
            self,
            '转换完成',
            f'已生成：\n{os.path.basename(target)}\n\n'
            f'{self.preview_result.block_count} 帧，'
            f'{len(self.preview_result.data)} 字节。',
        )
        return True
