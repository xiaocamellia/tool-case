"""步骤 9：统一 Schema、领域异常与敏感信息处理测试。"""

from __future__ import annotations

import io
import json
import logging
import os

import numpy as np
import pytest

import radar_tool.error_ui as error_ui
from radar_tool.error_ui import handle_ui_exception
from radar_tool.errors import (
    AppError,
    DataLimitError,
    ExportError,
    ValidationError,
    safe_exception_message,
    sanitize_sensitive_text,
)
from radar_tool.input_limits import InputResourceError
from radar_tool.logger import SafeFormatter
from radar_tool.schemas import (
    SCHEMA_VERSION,
    CalibrationConfig,
    ProjectRecord,
    TruthReviewConfig,
    migrate_json_schema,
    migrate_schema,
    validate_schema,
)


def _calibration_profile(profile_id="profile-1"):
    return {
        "id": profile_id,
        "name": "暗室配置",
        "data_path": "",
        "fixed_params": {
            "rho_obj": 15000.0,
            "xx_r4": 15576.864,
            "BS14": 194.5,
            "BS24": 119.5,
            "BS34": 58.0,
            "matrixZT2ANT": [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
        },
        "init_params": {"yy_r4_ZT": 1.999, "zz_r4_ZT": 1.096},
        "notes": "",
        "created_at": "2026-11-05T00:00:00",
        "updated_at": "2026-11-05T00:00:00",
    }


def test_domain_exception_hierarchy_is_unified():
    assert issubclass(ValidationError, ValueError)
    assert issubclass(ValidationError, AppError)
    assert issubclass(DataLimitError, ValidationError)
    assert issubclass(InputResourceError, DataLimitError)
    assert issubclass(ExportError, AppError)
    assert not issubclass(ExportError, ValueError)


def test_sensitive_paths_and_raw_data_are_sanitized():
    raw = (
        r"C:\Users\alice\private\measurements.csv "
        "1.0,2.0,3.0,4.0,5.0,6.0"
    )
    safe = sanitize_sensitive_text(raw)

    assert "alice" not in safe
    assert "measurements.csv" not in safe
    assert "1.0,2.0,3.0" not in safe
    assert "<文件路径>" in safe
    assert "<原始数据已隐藏>" in safe

    domain = safe_exception_message(ValidationError(raw))
    unexpected = safe_exception_message(RuntimeError(raw))
    assert "alice" not in domain
    assert raw not in unexpected
    assert "未预期错误" in unexpected


def test_safe_formatter_keeps_stack_but_redacts_sensitive_content():
    stream = io.StringIO()
    test_logger = logging.getLogger("test.safe_formatter")
    test_logger.handlers.clear()
    test_logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeFormatter("%(message)s"))
    test_logger.addHandler(handler)

    try:
        raise RuntimeError(
            r"C:\secret\private.csv 1,2,3,4,5,6"
        )
    except RuntimeError:
        test_logger.exception("后台任务失败")

    output = stream.getvalue()
    assert "Traceback" in output
    assert "RuntimeError" in output
    assert "secret" not in output
    assert "1,2,3,4,5,6" not in output
    test_logger.handlers.clear()


def test_project_record_schema_validates_and_migrates_legacy_payload():
    legacy = {
        "project-1": {
            "name": "外场试验",
            "description": "",
            "tasks": {
                "task-1": {
                    "name": "任务一",
                    "records": {
                        "record-1": {
                            "title": "记录一",
                            "steps": [],
                            "images": [],
                        }
                    },
                }
            },
        }
    }
    original = json.loads(json.dumps(legacy))

    migrated = migrate_schema(legacy, "project_record")
    validated = validate_schema(migrated, "project_record")

    assert migrated["schema_version"] == SCHEMA_VERSION
    assert validated["schema_version"] == SCHEMA_VERSION
    assert legacy == original
    assert "schema_version" not in legacy
    assert validated["projects"]["project-1"]["tasks"]["task-1"][
        "records"
    ]["record-1"]["title"] == "记录一"

    with pytest.raises(ValidationError, match="项目 ID"):
        ProjectRecord.from_dict("../escape", {"name": "非法项目"})


def test_calibration_schema_migrates_legacy_version_key():
    legacy = {
        "version": SCHEMA_VERSION,
        "profiles": [_calibration_profile()],
    }
    original = json.loads(json.dumps(legacy))

    migrated = migrate_json_schema(legacy, "calibration_config")
    validated = validate_schema(migrated, "calibration_config")

    assert migrated["schema_version"] == SCHEMA_VERSION
    assert "version" not in migrated
    assert legacy == original
    assert validated["profiles"][0]["name"] == "暗室配置"

    invalid = _calibration_profile()
    invalid["fixed_params"]["matrixZT2ANT"][0][0] = float("nan")
    with pytest.raises(ValidationError, match="有限"):
        CalibrationConfig.from_dict(invalid)


def test_truth_review_schema_is_versioned_and_json_safe():
    legacy = {
        "导出时间(exported_at)": "2026-11-05T00:00:00",
        "雷达数据文件(radar_file)": "RADAR_A.txt",
        "GPS真值文件(gps_truth_file)": "GPS_A.txt",
        "雷达列名文件(radar_metadata_file)": "",
        "批次目录(batch_directory)": "20261105_000000_RADAR_A_真值复核",
        "复核配置(review_configuration)": {
            "reference_metric": "distance",
            "metrics": {"distance": {"count": 10}},
        },
    }

    migrated = migrate_schema(legacy, "truth_review_config")
    validated = validate_schema(migrated, "truth_review_config")
    payload = TruthReviewConfig.create(
        exported_at="2026-11-05T00:00:00",
        radar_file=os.path.basename("C:/private/RADAR_A.txt"),
        gps_truth_file=os.path.basename("C:/private/GPS_A.txt"),
        radar_metadata_file="",
        batch_directory="batch",
        review_configuration={"count": 1},
    ).to_payload()

    assert migrated["schema_version"] == SCHEMA_VERSION
    assert validated["schema_version"] == SCHEMA_VERSION
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["radar_file"] == "RADAR_A.txt"
    assert "C:" not in payload["radar_file"]
    json.dumps(payload, ensure_ascii=False)

    with pytest.raises(ValidationError, match="不能序列化"):
        TruthReviewConfig.create(
            exported_at="now",
            radar_file="RADAR.txt",
            gps_truth_file="GPS.txt",
            radar_metadata_file="",
            batch_directory="batch",
            review_configuration={"raw": np.arange(10)},
        )


@pytest.mark.parametrize(
    "kind,payload",
    [
        (
            "project_record",
            {"schema_version": 2, "projects": {}},
        ),
        (
            "calibration_config",
            {"schema_version": 2, "profiles": []},
        ),
        (
            "truth_review_config",
            {"schema_version": 2},
        ),
    ],
)
def test_future_schema_versions_are_rejected(kind, payload):
    with pytest.raises(ValidationError, match="不支持的 schema_version"):
        migrate_schema(payload, kind)


def test_unexpected_ui_exception_uses_unified_page_and_safe_log():
    warnings = []
    criticals = []

    class MessageboxStub:
        @staticmethod
        def warning(*args):
            warnings.append(args)

        @staticmethod
        def critical(*args):
            criticals.append(args)

    original_messagebox = error_ui.QMessageBox
    error_ui.QMessageBox = MessageboxStub
    try:
        test_logger = logging.getLogger("test.unified_error")
        test_logger.handlers.clear()
        test_logger.propagate = False
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        test_logger.addHandler(handler)

        raw = r"C:\private\payload.csv 1,2,3,4,5,6"
        try:
            raise RuntimeError(raw)
        except RuntimeError as exc:
            result = handle_ui_exception(
                None, test_logger, "执行任务", exc
            )
        log_output = stream.getvalue()
        test_logger.handlers.clear()
    finally:
        error_ui.QMessageBox = original_messagebox

    assert len(criticals) == 1
    assert len(warnings) == 0
    assert criticals[0][1] == "统一错误页面"
    dialog_text = criticals[0][2]
    assert result in dialog_text
    assert "private" not in dialog_text
    assert "1,2,3,4,5,6" not in dialog_text
    assert "Traceback" in log_output
    assert "private" not in log_output
    assert "1,2,3,4,5,6" not in log_output


def test_domain_ui_exception_shows_sanitized_message():
    warnings = []
    criticals = []

    class MessageboxStub:
        @staticmethod
        def warning(*args):
            warnings.append(args)

        @staticmethod
        def critical(*args):
            criticals.append(args)

    original_messagebox = error_ui.QMessageBox
    error_ui.QMessageBox = MessageboxStub
    try:
        test_logger = logging.getLogger("test.domain_error")
        test_logger.handlers.clear()
        test_logger.propagate = False
        test_logger.addHandler(logging.NullHandler())

        raw = r"C:\private\input.csv 字段数量错误"
        result = handle_ui_exception(
            None, test_logger, "加载数据", ValidationError(raw)
        )
    finally:
        error_ui.QMessageBox = original_messagebox

    assert len(warnings) == 1
    assert len(criticals) == 0
    assert warnings[0][1] == "操作失败"
    assert "private" not in warnings[0][2]
    assert "字段数量错误" in warnings[0][2]
    assert "private" not in result
