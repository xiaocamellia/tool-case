"""Offscreen workflow tests for the format conversion panel."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from radar_tool.format_conversion import FormatConversionCancelled
from radar_tool.format_conversion_panel import FormatConversionPanel
from radar_tool.main_window import MainWindow


class FormatConversionPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wait_for_preview(self, panel, timeout=5.0):
        deadline = time.monotonic() + timeout
        while panel._preview_in_progress and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        return panel.preview_result is not None

    def test_panel_previews_converts_and_decodes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, 'amp_phase.txt')
            binary = os.path.join(directory, 'tr_all_inject.bin')
            decoded = os.path.join(directory, 'decoded.txt')
            with open(source, 'w', encoding='utf-8') as output:
                output.write('\n'.join(
                    f'{channel} {channel / 10:.1f} {-channel / 10:.1f}'
                    for channel in range(1, 65)
                ))

            panel = FormatConversionPanel()
            panel.source_edit.setText(source)
            panel.target_edit.setText(binary)
            self.assertTrue(panel._preview())
            self.assertTrue(self._wait_for_preview(panel))
            self.assertEqual(panel.frame_table.rowCount(), 1)
            self.assertEqual(panel.data_table.rowCount(), 64)

            with patch('radar_tool.format_conversion_panel.QMessageBox.information'):
                self.assertTrue(panel._convert())
            self.assertEqual(os.path.getsize(binary), 270)

            panel.direction_combo.setCurrentIndex(panel.BIN_TO_TXT)
            panel.source_edit.setText(binary)
            panel.target_edit.setText(decoded)
            self.assertTrue(panel._preview())
            self.assertTrue(self._wait_for_preview(panel))
            with patch('radar_tool.format_conversion_panel.QMessageBox.information'):
                self.assertTrue(panel._convert())
            with open(decoded, 'r', encoding='utf-8-sig') as source_file:
                lines = source_file.read().splitlines()
            self.assertEqual(lines[0], '1\t0.1\t-0.1')
            self.assertEqual(lines[-1], '64\t6.4\t-6.4')
            self.assertTrue(self._wait_until(
                panel, lambda: panel._parse_thread is None))
            panel.close()

    def _wait_until(self, panel, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        self.app.processEvents()
        return predicate()

    def test_panel_cancels_background_parse_without_blocking_ui(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, 'slow.txt')
            with open(source, 'w', encoding='utf-8') as output:
                output.write('1 0 0\n')

            panel = FormatConversionPanel()
            panel.source_edit.setText(source)

            def slow_load(_filepath, cancel_event, *_args):
                while not cancel_event.is_set():
                    time.sleep(0.01)
                raise FormatConversionCancelled('解析已取消')

            with patch(
                'radar_tool.format_conversion_panel.build_tr_amplitude_phase_bin',
                side_effect=slow_load,
            ):
                self.assertTrue(panel._preview())
                self.assertTrue(panel._preview_in_progress)
                panel._cancel_parse()
                self.assertTrue(self._wait_until(
                    panel, lambda: not panel._preview_in_progress))
            self.assertEqual(panel.status_badge.text(), '已取消')
            self.assertTrue(self._wait_until(
                panel, lambda: panel._parse_thread is None))
            panel.close()

    def test_panel_reports_timeout_from_background_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, 'slow.txt')
            with open(source, 'w', encoding='utf-8') as output:
                output.write('1 0 0\n')

            panel = FormatConversionPanel()
            panel.parse_timeout_seconds = 0.05
            panel.source_edit.setText(source)

            def slow_load(_filepath, cancel_event, *_args):
                while not cancel_event.is_set():
                    time.sleep(0.005)
                raise FormatConversionCancelled('解析已取消')

            with patch(
                'radar_tool.format_conversion_panel.build_tr_amplitude_phase_bin',
                side_effect=slow_load,
            ):
                self.assertTrue(panel._preview())
                self.assertTrue(self._wait_until(
                    panel, lambda: not panel._preview_in_progress))
            self.assertEqual(panel.status_badge.text(), '预检失败')
            self.assertIn('解析超时', panel.log_text.toPlainText())
            self.assertTrue(self._wait_until(
                panel, lambda: panel._parse_thread is None))
            panel.close()

    def test_main_window_exposes_lazy_format_conversion_tab(self):
        window = MainWindow()
        index = window._tab_names.index('格式转换')
        self.assertFalse(window._tab_loaded[index])
        panel = window._lazy_create_or_get_panel(index)
        self.assertIsInstance(panel, FormatConversionPanel)
        self.assertTrue(window._tab_loaded[index])
        window.close()


if __name__ == '__main__':
    unittest.main()
