"""Tests for atomic, traceable, and injection-safe exports."""

from __future__ import annotations

import datetime
import os
import shutil
from unittest.mock import patch

import pandas as pd
import pytest

from radar_tool import exp_recorder, experiment_word_export
from radar_tool.export_safety import (
    APP_VERSION,
    BatchExportError,
    atomic_export_batch,
    build_export_metadata,
    escape_csv_cell,
    sanitize_dataframe_for_csv,
)


def test_formula_prefixes_are_escaped_in_headers_and_string_cells():
    dataframe = pd.DataFrame(
        {
            '=header': ['=formula', '+formula', '-formula', '@formula'],
            'numeric': [-1, 2, 3, 4],
        }
    )

    sanitized = sanitize_dataframe_for_csv(dataframe)

    assert escape_csv_cell('plain text') == 'plain text'
    assert list(sanitized.columns) == ["'=header", 'numeric']
    assert sanitized.iloc[:, 0].tolist() == [
        "'=formula",
        "'+formula",
        "'-formula",
        "'@formula",
    ]
    assert sanitized['numeric'].tolist() == [-1, 2, 3, 4]


def test_atomic_export_batch_publishes_only_after_writer_succeeds(tmp_path):
    target = tmp_path / 'batch'

    def writer(temporary_directory):
        output = os.path.join(temporary_directory, 'result.csv')
        with open(output, 'w', encoding='utf-8') as handle:
            handle.write('value\n1\n')

    result = atomic_export_batch(str(target), writer)

    assert result == str(target)
    assert (target / 'result.csv').is_file()
    assert not list(tmp_path.glob('.batch.tmp-*'))


def test_failed_writer_is_cleaned_and_target_is_not_published(tmp_path):
    target = tmp_path / 'batch'

    def writer(temporary_directory):
        with open(
            os.path.join(temporary_directory, 'partial.csv'),
            'w',
            encoding='utf-8',
        ) as handle:
            handle.write('partial')
        raise RuntimeError('write failed')

    with pytest.raises(BatchExportError) as error:
        atomic_export_batch(str(target), writer)

    assert '无残留文件' in str(error.value)
    assert error.value.residual_files == ()
    assert not target.exists()
    assert not list(tmp_path.glob('.batch.tmp-*'))


def test_cleanup_failure_lists_every_residual_file(tmp_path):
    target = tmp_path / 'batch'

    def writer(temporary_directory):
        nested = os.path.join(temporary_directory, 'nested')
        os.makedirs(nested)
        for filename in ('first.csv', os.path.join('nested', 'second.json')):
            with open(
                os.path.join(temporary_directory, filename),
                'w',
                encoding='utf-8',
            ) as handle:
                handle.write('residual')

    with patch(
        'radar_tool.export_safety.os.replace',
        side_effect=PermissionError('publish blocked'),
    ):
        with patch(
            'radar_tool.export_safety.shutil.rmtree',
            side_effect=PermissionError('locked'),
        ):
            with pytest.raises(BatchExportError) as error:
                atomic_export_batch(str(target), writer)

    assert '无法清理的残留文件' in str(error.value)
    assert 'first.csv' in str(error.value)
    assert 'second.json' in str(error.value)
    assert len(error.value.residual_files) == 2
    assert not target.exists()
    shutil.rmtree(next(tmp_path.glob('.batch.tmp-*')))


def test_export_metadata_contains_traceability_fields():
    metadata = build_export_metadata(
        input_summary={'source': 'input.csv', 'rows': 12},
        parameters={'threshold': 3},
    )

    assert metadata['version'] == APP_VERSION == '1.0.0'
    assert metadata['schema_version'] == 1
    assert metadata['input_summary'] == {'source': 'input.csv', 'rows': 12}
    assert metadata['parameters'] == {'threshold': 3}
    generated_at = datetime.datetime.fromisoformat(metadata['generated_at'])
    assert generated_at.tzinfo is not None


def test_word_metadata_lines_include_version_summary_and_parameters():
    metadata = build_export_metadata(
        input_summary={'scope': 'record', 'record_count': 1},
        parameters={'report_style': '标准正式'},
    )

    lines = experiment_word_export.WordExportMixin()._export_metadata_lines(
        metadata
    )

    assert f'"version": "{APP_VERSION}"' in lines[0]
    assert '"schema_version": 1' in lines[0]
    assert '"generated_at"' in lines[0]
    assert '"scope": "record"' in lines[1]
    assert '"record_count": 1' in lines[1]
    assert '"report_style": "标准正式"' in lines[2]


def test_word_export_rejects_absolute_path_outside_managed_images_dir(tmp_path):
    managed_images = tmp_path / 'images'
    managed_images.mkdir()
    outside_image = tmp_path / 'outside.png'
    outside_image.write_bytes(b'not an image')

    with patch.object(exp_recorder, 'IMAGES_DIR', str(managed_images)):
        with pytest.raises(ValueError, match='超出允许的图片目录'):
            experiment_word_export._safe_image_path(
                str(outside_image), validate_image=False
            )
