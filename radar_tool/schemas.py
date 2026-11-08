"""项目、校正与真值复核配置的显式 Schema 和版本迁移。"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict

from .errors import ValidationError


SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_KINDS = (
    "project_record",
    "calibration_config",
    "truth_review_config",
)
_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _require_mapping(value, name):
    if not isinstance(value, dict):
        raise ValidationError(f"{name} 必须是 JSON 对象")
    return value


def _require_text(value, name, allow_empty=True):
    if not isinstance(value, str):
        raise ValidationError(f"{name} 必须是字符串")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ValidationError(f"{name} 不能为空")
    return normalized


def _require_id(value, name):
    normalized = _require_text(value, name, allow_empty=False)
    if not _ID_PATTERN.fullmatch(normalized):
        raise ValidationError(
            f"{name} 只能包含字母、数字、下划线或连字符"
        )
    return normalized


def _finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} 必须是有限数值")
    if not math.isfinite(value):
        raise ValidationError(f"{name} 必须是有限数值")
    return value


def _ensure_json_value(value, name, depth=0):
    if depth > 64:
        raise ValidationError(f"{name} 嵌套深度超过上限")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        _finite_number(value, name)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValidationError(f"{name} 的键必须是字符串")
            _ensure_json_value(child, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _ensure_json_value(child, f"{name}[{index}]", depth + 1)
        return
    raise ValidationError(f"{name} 包含不能序列化的原始数据")


@dataclass
class ProjectRecord:
    """试验项目记录的显式 Schema。"""

    project_id: str
    name: str
    description: str = ""
    tasks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, project_id: str, payload: dict) -> "ProjectRecord":
        data = _require_mapping(payload, "项目记录")
        name = _require_text(data.get("name", ""), "项目名称", allow_empty=False)
        description = _require_text(data.get("description", ""), "项目描述")
        tasks = _require_mapping(data.get("tasks", {}), "项目 tasks")
        normalized_tasks = {}
        for task_id, task_payload in tasks.items():
            normalized_task_id = _require_id(task_id, "任务 ID")
            task = _require_mapping(task_payload, "任务记录")
            records = _require_mapping(task.get("records", {}), "任务 records")
            normalized_records = {}
            for record_id, record_payload in records.items():
                normalized_record_id = _require_id(record_id, "记录 ID")
                record = _require_mapping(record_payload, "试验记录")
                for field_name in (
                    "title", "date", "personnel", "location", "template",
                    "conditions", "content", "conclusion", "data",
                    "created", "updated",
                ):
                    if field_name in record and not isinstance(
                        record[field_name], str
                    ):
                        raise ValidationError(
                            f"记录字段 {field_name} 必须是字符串"
                        )
                if "steps" in record and not isinstance(record["steps"], list):
                    raise ValidationError("记录 steps 必须是数组")
                if "images" in record and not isinstance(
                    record["images"], list
                ):
                    raise ValidationError("记录 images 必须是数组")
                _ensure_json_value(record, "试验记录")
                normalized_records[normalized_record_id] = copy.deepcopy(record)
            if "name" in task and not isinstance(task["name"], str):
                raise ValidationError("任务 name 必须是字符串")
            normalized_task = copy.deepcopy(task)
            normalized_task["records"] = normalized_records
            normalized_tasks[normalized_task_id] = normalized_task
        return cls(
            project_id=_require_id(project_id, "项目 ID"),
            name=name,
            description=description,
            tasks=normalized_tasks,
            created_at=_require_text(data.get("created_at", ""), "创建时间"),
            updated_at=_require_text(data.get("updated_at", ""), "更新时间"),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "tasks": copy.deepcopy(self.tasks),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class CalibrationConfig:
    """测向校正配置的显式 Schema。"""

    config_id: str
    name: str
    data_path: str = ""
    fixed_params: Dict[str, Any] = field(default_factory=dict)
    init_params: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict) -> "CalibrationConfig":
        data = _require_mapping(payload, "校正配置")
        config_id = _require_id(data.get("id", ""), "校正配置 ID")
        name = _require_text(data.get("name", ""), "校正配置名称", False)
        data_path = _require_text(data.get("data_path", ""), "校正数据路径")
        fixed = _require_mapping(
            data.get("fixed_params", {}), "fixed_params")
        init = _require_mapping(
            data.get("init_params", {}), "init_params")
        matrix = fixed.get("matrixZT2ANT", [[0, 0, 0]] * 3)
        if not isinstance(matrix, list) or len(matrix) != 3:
            raise ValidationError("matrixZT2ANT 必须是 3x3 矩阵")
        for row in matrix:
            if not isinstance(row, list) or len(row) != 3:
                raise ValidationError("matrixZT2ANT 必须是 3x3 矩阵")
            for value in row:
                _finite_number(value, "matrixZT2ANT 元素")
        for key in ("rho_obj", "xx_r4", "BS14", "BS24", "BS34"):
            if key in fixed:
                _finite_number(fixed[key], key)
        for key in ("yy_r4_ZT", "zz_r4_ZT"):
            if key in init:
                _finite_number(init[key], key)
        _ensure_json_value(fixed, "fixed_params")
        _ensure_json_value(init, "init_params")
        return cls(
            config_id=config_id,
            name=name,
            data_path=data_path,
            fixed_params=copy.deepcopy(fixed),
            init_params=copy.deepcopy(init),
            notes=_require_text(data.get("notes", ""), "校正备注"),
            created_at=_require_text(data.get("created_at", ""), "创建时间"),
            updated_at=_require_text(data.get("updated_at", ""), "更新时间"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.config_id,
            "name": self.name,
            "data_path": self.data_path,
            "fixed_params": copy.deepcopy(self.fixed_params),
            "init_params": copy.deepcopy(self.init_params),
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TruthReviewConfig:
    """真值复核导出配置的显式 Schema。"""

    exported_at: str
    radar_file: str = ""
    gps_truth_file: str = ""
    radar_metadata_file: str = ""
    batch_directory: str = ""
    review_configuration: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict) -> "TruthReviewConfig":
        data = _require_mapping(payload, "真值复核配置")
        review = _require_mapping(
            data.get(
                "review_configuration",
                data.get("复核配置(review_configuration)", {}),
            ),
            "review_configuration",
        )
        _ensure_json_value(review, "review_configuration")
        return cls(
            exported_at=_require_text(
                data.get("exported_at", data.get("导出时间(exported_at)", "")),
                "导出时间",
            ),
            radar_file=_require_text(
                data.get("radar_file", data.get("雷达数据文件(radar_file)", "")),
                "雷达数据文件",
            ),
            gps_truth_file=_require_text(
                data.get(
                    "gps_truth_file",
                    data.get("GPS真值文件(gps_truth_file)", ""),
                ),
                "GPS真值文件",
            ),
            radar_metadata_file=_require_text(
                data.get(
                    "radar_metadata_file",
                    data.get("雷达列名文件(radar_metadata_file)", ""),
                ),
                "雷达列名文件",
            ),
            batch_directory=_require_text(
                data.get(
                    "batch_directory",
                    data.get("批次目录(batch_directory)", ""),
                ),
                "批次目录",
            ),
            review_configuration=copy.deepcopy(review),
        )

    @classmethod
    def create(
        cls,
        exported_at: str,
        radar_file: str,
        gps_truth_file: str,
        radar_metadata_file: str,
        batch_directory: str,
        review_configuration: dict,
    ) -> "TruthReviewConfig":
        return cls.from_payload({
            "exported_at": exported_at,
            "radar_file": radar_file,
            "gps_truth_file": gps_truth_file,
            "radar_metadata_file": radar_metadata_file,
            "batch_directory": batch_directory,
            "review_configuration": review_configuration,
        })

    def to_payload(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "exported_at": self.exported_at,
            "radar_file": self.radar_file,
            "gps_truth_file": self.gps_truth_file,
            "radar_metadata_file": self.radar_metadata_file,
            "batch_directory": self.batch_directory,
            "review_configuration": copy.deepcopy(
                self.review_configuration
            ),
        }


def _project_v0_to_v1(payload: dict) -> dict:
    if "projects" in payload or "schema_version" in payload:
        projects = payload.get("projects")
        if not isinstance(projects, dict):
            raise ValidationError("projects 必须是 JSON 对象")
        return {"schema_version": 1, "projects": copy.deepcopy(projects)}
    return {"schema_version": 1, "projects": copy.deepcopy(payload)}


def _calibration_v0_to_v1(payload: dict) -> dict:
    migrated = copy.deepcopy(payload)
    migrated.pop("version", None)
    migrated["schema_version"] = 1
    return migrated


def _truth_review_v0_to_v1(payload: dict) -> dict:
    migrated = copy.deepcopy(payload)
    migrated["schema_version"] = 1
    return migrated


MIGRATIONS = {
    "project_record": {0: _project_v0_to_v1},
    "calibration_config": {0: _calibration_v0_to_v1},
    "truth_review_config": {0: _truth_review_v0_to_v1},
}


def _document_version(payload: dict, kind: str) -> int:
    if "schema_version" in payload:
        version = payload["schema_version"]
    else:
        # Legacy calibration files used ``version`` without schema_version.
        version = 0
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValidationError("schema_version 必须是整数")
    return version


def migrate_schema(
    payload: dict, kind: str, target_version: int = SCHEMA_VERSION
) -> dict:
    """按版本逐步迁移 JSON 文档，不修改调用方输入。"""
    if kind not in SUPPORTED_SCHEMA_KINDS:
        raise ValidationError(f"不支持的 Schema 类型: {kind}")
    document = _require_mapping(payload, f"{kind} 文档")
    version = _document_version(document, kind)
    if version > target_version:
        raise ValidationError(
            f"不支持的 schema_version: {version}（最高支持 {target_version}）"
        )
    migrations = MIGRATIONS[kind]
    while version < target_version:
        migrate = migrations.get(version)
        if migrate is None:
            raise ValidationError(
                f"缺少 {kind} 从版本 {version} 开始的迁移函数"
            )
        document = migrate(document)
        next_version = _document_version(document, kind)
        if next_version <= version:
            raise ValidationError("Schema 迁移没有推进版本")
        version = next_version
    return document


def validate_schema(payload: dict, kind: str) -> dict:
    """校验并返回当前版本 Schema 文档的深拷贝。"""
    document = migrate_schema(payload, kind)
    if kind == "project_record":
        if set(document) != {"schema_version", "projects"}:
            raise ValidationError("项目记录 Schema 字段不完整")
        projects = document["projects"]
        if not isinstance(projects, dict):
            raise ValidationError("projects 必须是 JSON 对象")
        normalized = {}
        for project_id, project in projects.items():
            normalized[project_id] = ProjectRecord.from_dict(
                project_id, project
            ).to_dict()
        return {"schema_version": SCHEMA_VERSION, "projects": normalized}
    if kind == "calibration_config":
        if set(document) != {"schema_version", "profiles"}:
            raise ValidationError("校正配置 Schema 字段不完整")
        profiles = document["profiles"]
        if not isinstance(profiles, list):
            raise ValidationError("profiles 必须是 JSON 数组")
        normalized_profiles = [
            CalibrationConfig.from_dict(item).to_dict()
            for item in profiles
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "profiles": normalized_profiles,
        }
    truth = TruthReviewConfig.from_payload(document)
    return truth.to_payload()


def migrate_json_schema(
    payload: dict, kind: str, target_version: int = SCHEMA_VERSION
) -> dict:
    """公开别名，便于按版本调用 JSON Schema 迁移。"""
    return migrate_schema(payload, kind, target_version)
