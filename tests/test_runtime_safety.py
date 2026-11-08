"""Regression tests for runtime paths and experiment persistence."""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
import tempfile
import unittest
import uuid
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
            self.assertFalse(os.path.exists(filepath))
            corrupt_files = [
                name for name in os.listdir(directory)
                if name.startswith('experiments.json.corrupt-')
            ]
            self.assertEqual(len(corrupt_files), 1)
            with open(
                os.path.join(directory, corrupt_files[0]), encoding='utf-8'
            ) as handle:
                self.assertEqual(handle.read(), '{broken json')

    def test_successful_save_keeps_previous_valid_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(exp_recorder, 'DATA_DIR', directory):
                panel = exp_recorder.ExpRecorderPanel.__new__(
                    exp_recorder.ExpRecorderPanel
                )
                panel.projects = {'project': {'name': 'first'}}
                panel._save_data()
                filepath = os.path.join(directory, 'experiments.json')
                self.assertFalse(os.path.exists(filepath + '.bak'))

                panel.projects = {'project': {'name': 'second'}}
                panel._save_data()

            with open(filepath, encoding='utf-8') as handle:
                current = json.load(handle)
            with open(filepath + '.bak', encoding='utf-8') as handle:
                backup = json.load(handle)
            self.assertEqual(
                current['projects']['project']['name'], 'second'
            )
            self.assertEqual(
                backup['projects']['project']['name'], 'first'
            )

    def test_json_size_and_depth_limits_quarantine_file(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'experiments.json')
            with open(filepath, 'w', encoding='utf-8') as handle:
                handle.write('{"schema_version": 1, "projects": {}}')
            with patch.object(exp_recorder, 'DATA_DIR', directory), patch.object(
                exp_recorder, 'MAX_JSON_FILE_SIZE', 10
            ):
                panel = exp_recorder.ExpRecorderPanel.__new__(
                    exp_recorder.ExpRecorderPanel
                )
                panel.projects = {'existing': {'name': 'keep'}}
                panel._load_data()
            self.assertEqual(panel.projects, {'existing': {'name': 'keep'}})
            self.assertFalse(os.path.exists(filepath))
            self.assertTrue(any(
                name.startswith('experiments.json.corrupt-')
                for name in os.listdir(directory)
            ))

        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'experiments.json')
            nested = {'schema_version': 1, 'projects': {}}
            cursor = nested['projects']
            for _ in range(8):
                cursor['child'] = {}
                cursor = cursor['child']
            with open(filepath, 'w', encoding='utf-8') as handle:
                json.dump(nested, handle)
            with patch.object(exp_recorder, 'DATA_DIR', directory), patch.object(
                exp_recorder, 'MAX_JSON_NESTING_DEPTH', 3
            ):
                panel = exp_recorder.ExpRecorderPanel.__new__(
                    exp_recorder.ExpRecorderPanel
                )
                panel.projects = {'existing': {'name': 'keep'}}
                panel._load_data()
            self.assertEqual(panel.projects, {'existing': {'name': 'keep'}})
            self.assertFalse(os.path.exists(filepath))
            self.assertTrue(any(
                name.startswith('experiments.json.corrupt-')
                for name in os.listdir(directory)
            ))

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


class ExperimentPathSafetyTests(unittest.TestCase):
    PNG_1X1 = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
        '+A8AAQUBAScY42YAAAAASUVORK5CYII='
    )

    @staticmethod
    def _write_png(filepath, payload=None):
        with open(filepath, 'wb') as handle:
            handle.write(ExperimentPathSafetyTests.PNG_1X1 if payload is None else payload)

    @staticmethod
    def _panel():
        return exp_recorder.ExpRecorderPanel.__new__(
            exp_recorder.ExpRecorderPanel
        )

    def test_invalid_experiment_ids_are_rejected(self):
        invalid_ids = ('../escape', '..\\escape', '/absolute', 'C:\\absolute', '.')
        with tempfile.TemporaryDirectory() as directory:
            images_dir = os.path.join(directory, 'images')
            with patch.object(exp_recorder, 'IMAGES_DIR', images_dir):
                panel = self._panel()
                for identifier in invalid_ids:
                    with self.assertRaises(ValueError):
                        panel._image_storage_dir(identifier, 'task', 'record')
                valid_id = str(uuid.uuid4())
                self.assertEqual(
                    exp_recorder.validate_experiment_id(valid_id),
                    valid_id,
                )

    def test_storage_dir_is_created_inside_images_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            images_dir = os.path.join(directory, 'images')
            with patch.object(exp_recorder, 'IMAGES_DIR', images_dir):
                panel = self._panel()
                storage_dir = panel._image_storage_dir('project', 'task', 'record')
                root = os.path.realpath(images_dir)
                self.assertTrue(
                    os.path.commonpath([root, os.path.realpath(storage_dir)]) == root
                )
                self.assertTrue(os.path.isdir(storage_dir))

    def test_copy_rejects_invalid_source_and_persists_only_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            images_dir = os.path.join(directory, 'images')
            os.makedirs(images_dir, exist_ok=True)
            source_path = os.path.join(directory, 'source.png')
            self._write_png(source_path)
            with patch.object(exp_recorder, 'IMAGES_DIR', images_dir):
                panel = self._panel()
                panel.current_project_id = 'project'
                panel.current_task_id = 'task'
                panel.current_record_id = 'record'
                normalized = panel._normalize_image_item(
                    {'path': source_path, 'caption': '截图'}
                )
                self.assertIsNotNone(normalized)
                self.assertFalse(os.path.isabs(normalized['path']))
                stored_path = os.path.join(images_dir, normalized['path'])
                self.assertTrue(os.path.isfile(stored_path))
                with self.assertRaises(ValueError):
                    exp_recorder._safe_image_path(source_path, validate_image=True)

                bad_source = os.path.join(directory, 'bad.png')
                with open(bad_source, 'wb') as handle:
                    handle.write(b'not-an-image')
                self.assertIsNone(
                    panel._normalize_image_item({'path': bad_source, 'caption': ''})
                )

    def test_image_size_pixels_magic_and_format_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            images_dir = os.path.join(directory, 'images')
            os.makedirs(images_dir, exist_ok=True)
            with patch.object(exp_recorder, 'IMAGES_DIR', images_dir):
                oversized = os.path.join(directory, 'large.png')
                self._write_png(oversized)
                with patch.object(exp_recorder, 'MAX_IMAGE_FILE_SIZE', 10):
                    with self.assertRaises(ValueError):
                        exp_recorder._validate_source_image(oversized)

                huge_pixels = os.path.join(directory, 'huge.png')
                payload = (
                    b'\x89PNG\r\n\x1a\n'
                    + struct.pack('>II', 100000, 100000)
                    + b'\x08\x06\x00\x00\x00'
                )
                self._write_png(huge_pixels, payload)
                with self.assertRaises(ValueError):
                    exp_recorder._validate_source_image(huge_pixels)

                wrong_magic = os.path.join(directory, 'wrong.png')
                with open(wrong_magic, 'wb') as handle:
                    handle.write(b'\xff\xd8\xff\xe0')
                with self.assertRaises(ValueError):
                    exp_recorder._validate_source_image(wrong_magic)

                unsupported = os.path.join(directory, 'image.gif')
                self._write_png(unsupported)
                with self.assertRaises(ValueError):
                    exp_recorder._validate_source_image(unsupported)

    def test_supported_image_headers_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            bmp_path = os.path.join(directory, 'valid.bmp')
            bmp_header = b'BM' + struct.pack('<IHHI', 66, 0, 0, 54)
            bmp_dib = struct.pack(
                '<IiiHHIIiiII', 40, 1, 1, 1, 24, 0, 12, 0, 0, 0, 0
            )
            with open(bmp_path, 'wb') as handle:
                handle.write(bmp_header + bmp_dib + b'\x00\x00\x00')

            jpeg_path = os.path.join(directory, 'valid.jpg')
            with open(jpeg_path, 'wb') as handle:
                handle.write(
                    b'\xff\xd8'
                    b'\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
                    b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
                    b'\xff\xd9'
                )

            webp_path = os.path.join(directory, 'valid.webp')
            vp8l = b'\x2f' + (0).to_bytes(4, 'little')
            webp_chunk = b'VP8L' + struct.pack('<I', len(vp8l)) + vp8l
            with open(webp_path, 'wb') as handle:
                handle.write(
                    b'RIFF'
                    + struct.pack('<I', 4 + len(webp_chunk))
                    + b'WEBP'
                    + webp_chunk
                )

            tiff_path = os.path.join(directory, 'valid.tiff')
            tiff_entries = struct.pack('<HHII', 256, 3, 1, 1)
            tiff_entries += struct.pack('<HHII', 257, 3, 1, 1)
            with open(tiff_path, 'wb') as handle:
                handle.write(
                    b'II*\x00'
                    + struct.pack('<I', 8)
                    + struct.pack('<H', 2)
                    + tiff_entries
                    + struct.pack('<I', 0)
                )

            png_path = os.path.join(directory, 'valid.png')
            self._write_png(png_path)
            for filepath in (png_path, bmp_path, jpeg_path, webp_path, tiff_path):
                self.assertEqual(
                    exp_recorder._validate_source_image(filepath),
                    os.path.realpath(filepath),
                )

    def test_symlink_and_non_regular_image_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            images_dir = os.path.join(directory, 'images')
            os.makedirs(images_dir, exist_ok=True)
            target_path = os.path.join(directory, 'target.png')
            self._write_png(target_path)
            link_path = os.path.join(images_dir, 'linked.png')
            try:
                os.symlink(target_path, link_path)
            except (OSError, NotImplementedError):
                link_path = None
            with patch.object(exp_recorder, 'IMAGES_DIR', images_dir):
                if link_path is not None:
                    with self.assertRaises(ValueError):
                        exp_recorder._safe_image_path(
                            link_path, validate_image=True
                        )
                with self.assertRaises(ValueError):
                    exp_recorder._safe_image_path(
                        images_dir, validate_image=False
                    )

    def test_schema_version_and_legacy_absolute_image_are_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = os.path.join(directory, 'data')
            images_dir = os.path.join(data_dir, 'images')
            os.makedirs(images_dir, exist_ok=True)
            image_path = os.path.join(images_dir, 'legacy.png')
            self._write_png(image_path)
            filepath = os.path.join(data_dir, 'experiments.json')
            legacy_payload = {
                'project': {
                    'name': '旧项目',
                    'tasks': {
                        'task': {
                            'name': '旧任务',
                            'records': {
                                'record': {
                                    'title': '旧记录',
                                    'images': [image_path],
                                }
                            },
                        }
                    },
                }
            }
            with open(filepath, 'w', encoding='utf-8') as handle:
                json.dump(legacy_payload, handle, ensure_ascii=False)

            with patch.object(exp_recorder, 'DATA_DIR', data_dir), patch.object(
                exp_recorder, 'IMAGES_DIR', images_dir
            ):
                panel = self._panel()
                panel.projects = {}
                panel._load_data()
                loaded_image = panel.projects['project']['tasks']['task'][
                    'records'
                ]['record']['images'][0]['path']
                self.assertFalse(os.path.isabs(loaded_image))
                panel._save_data()

            with open(filepath, encoding='utf-8') as handle:
                saved = json.load(handle)
            self.assertEqual(
                saved['schema_version'],
                exp_recorder.EXPERIMENTS_SCHEMA_VERSION,
            )
            saved_image = saved['projects']['project']['tasks']['task'][
                'records'
            ]['record']['images'][0]['path']
            self.assertFalse(os.path.isabs(saved_image))

    def test_external_or_traversing_json_image_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = os.path.join(directory, 'data')
            images_dir = os.path.join(data_dir, 'images')
            os.makedirs(images_dir, exist_ok=True)
            outside_image = os.path.join(directory, 'outside.png')
            self._write_png(outside_image)
            filepath = os.path.join(data_dir, 'experiments.json')

            for bad_path in (outside_image, '../outside.png', '..\\outside.png'):
                payload = {
                    'schema_version': exp_recorder.EXPERIMENTS_SCHEMA_VERSION,
                    'projects': {
                        'project': {
                            'name': '项目',
                            'tasks': {
                                'task': {
                                    'name': '任务',
                                    'records': {
                                        'record': {
                                            'title': '记录',
                                            'images': [bad_path],
                                        }
                                    },
                                }
                            },
                        }
                    },
                }
                with open(filepath, 'w', encoding='utf-8') as handle:
                    json.dump(payload, handle, ensure_ascii=False)
                with patch.object(exp_recorder, 'DATA_DIR', data_dir), patch.object(
                    exp_recorder, 'IMAGES_DIR', images_dir
                ):
                    panel = self._panel()
                    panel.projects = {'existing': {'name': '保留'}}
                    panel._load_data()
                    self.assertEqual(panel.projects, {'existing': {'name': '保留'}})

    def test_schema_rejects_invalid_ids_and_accepts_uuid(self):
        payload = {
            'schema_version': exp_recorder.EXPERIMENTS_SCHEMA_VERSION,
            'projects': {'../escape': {'name': '恶意项目'}},
        }
        with self.assertRaises(ValueError):
            exp_recorder._normalize_projects_payload(payload)
        valid_uuid = str(uuid.uuid4())
        self.assertEqual(exp_recorder.validate_experiment_id(valid_uuid), valid_uuid)

    def test_relative_image_path_is_accepted_by_safe_resolver(self):
        with tempfile.TemporaryDirectory() as directory:
            images_dir = os.path.join(directory, 'images')
            os.makedirs(os.path.join(images_dir, 'project', 'task', 'record'), exist_ok=True)
            image_path = os.path.join(
                images_dir, 'project', 'task', 'record', 'relative.png'
            )
            self._write_png(image_path)
            relative_path = os.path.join(
                'project', 'task', 'record', 'relative.png'
            )
            with patch.object(exp_recorder, 'IMAGES_DIR', images_dir):
                resolved = exp_recorder._safe_image_path(
                    relative_path, validate_image=True
                )
                self.assertTrue(
                    os.path.commonpath(
                        [os.path.realpath(images_dir), resolved]
                    ) == os.path.realpath(images_dir)
                )
                with self.assertRaises(ValueError):
                    exp_recorder._safe_image_path(
                        os.path.join(directory, 'outside.png'),
                        validate_image=True,
                    )


if __name__ == '__main__':
    unittest.main()
