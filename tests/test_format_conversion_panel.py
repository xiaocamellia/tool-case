"""Offscreen workflow tests for the format conversion panel."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from radar_tool.format_conversion_panel import FormatConversionPanel
from radar_tool.main_window import MainWindow


class FormatConversionPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
            self.assertEqual(panel.frame_table.rowCount(), 1)
            self.assertEqual(panel.data_table.rowCount(), 64)

            with patch('radar_tool.format_conversion_panel.QMessageBox.information'):
                self.assertTrue(panel._convert())
            self.assertEqual(os.path.getsize(binary), 270)

            panel.direction_combo.setCurrentIndex(panel.BIN_TO_TXT)
            panel.source_edit.setText(binary)
            panel.target_edit.setText(decoded)
            with patch('radar_tool.format_conversion_panel.QMessageBox.information'):
                self.assertTrue(panel._convert())
            with open(decoded, 'r', encoding='utf-8-sig') as source_file:
                lines = source_file.read().splitlines()
            self.assertEqual(lines[0], '1\t0.1\t-0.1')
            self.assertEqual(lines[-1], '64\t6.4\t-6.4')
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
