"""Regression tests for runtime paths and experiment persistence."""

from __future__ import annotations

import logging
import os
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

from radar_tool import exp_recorder
from radar_tool.logger import get_logger
from radar_tool.runtime_paths import get_user_data_root


class RuntimePathTests(unittest.TestCase):
    def test_source_runtime_data_is_isolated_from_project_status(self):
        self.assertTrue(get_user_data_root().endswith('var'))

    def test_logger_uses_rotating_file_handler(self):
        get_logger('runtime_safety_test')
        handlers = logging.getLogger('radar_tool').handlers
        self.assertTrue(
            any(isinstance(handler, RotatingFileHandler) for handler in handlers)
        )


class ExperimentPersistenceTests(unittest.TestCase):
    def test_save_is_atomic_when_replacement_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(exp_recorder, 'DATA_DIR', directory):
                panel = exp_recorder.ExpRecorderPanel.__new__(
                    exp_recorder.ExpRecorderPanel
                )
                panel.projects = {'project': {'name': 'original'}}
                panel._save_data()
                filepath = os.path.join(directory, 'experiments.json')
                with open(filepath, encoding='utf-8') as handle:
                    original = handle.read()

                panel.projects = {'project': {'name': 'replacement'}}
                with patch.object(
                    exp_recorder.os,
                    'replace',
                    side_effect=OSError('simulated failure'),
                ):
                    panel._save_data()

                with open(filepath, encoding='utf-8') as handle:
                    self.assertEqual(handle.read(), original)
                self.assertFalse(os.path.exists(filepath + '.tmp'))

    def test_load_failure_preserves_existing_memory_state(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'experiments.json')
            with open(filepath, 'w', encoding='utf-8') as handle:
                handle.write('{broken json')

            with patch.object(exp_recorder, 'DATA_DIR', directory):
                panel = exp_recorder.ExpRecorderPanel.__new__(
                    exp_recorder.ExpRecorderPanel
                )
                panel.projects = {'existing': {'name': 'keep'}}
                panel._load_data()

            self.assertEqual(panel.projects, {'existing': {'name': 'keep'}})
            self.assertTrue(os.path.exists(filepath))

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(exp_recorder, 'DATA_DIR', directory):
                panel = exp_recorder.ExpRecorderPanel.__new__(
                    exp_recorder.ExpRecorderPanel
                )
                panel.projects = {'project': {'name': '试验项目'}}
                panel._save_data()
                panel.projects = {}
                panel._load_data()

            self.assertEqual(panel.projects, {'project': {'name': '试验项目'}})


if __name__ == '__main__':
    unittest.main()
