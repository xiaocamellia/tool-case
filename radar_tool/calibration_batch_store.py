"""Persistent reusable batch profiles for direction-finding calibration."""

from __future__ import annotations

import copy
import datetime as dt
import json
import logging
import math
import os
import shutil
import uuid

from .runtime_paths import get_user_data_dir
from .schemas import SCHEMA_VERSION, migrate_schema


DEFAULT_FIXED_PARAMS = {
    'rho_obj': 15000.0,
    'xx_r4': 15576.864,
    'BS14': 194.5,
    'BS24': 119.5,
    'BS34': 58.0,
    'matrixZT2ANT': [
        [0.9999946, 0.0015699, 0.0028962],
        [-0.0015826, 0.9999892, 0.0043656],
        [-0.0028893, -0.0043701, 0.9999863],
    ],
}
DEFAULT_INIT_PARAMS = {'yy_r4_ZT': 1.999, 'zz_r4_ZT': 1.096}

MAX_JSON_FILE_SIZE = 10 * 1024 * 1024
MAX_JSON_NESTING_DEPTH = 64
FIXED_SCALAR_PARAMS = frozenset(
    ('rho_obj', 'xx_r4', 'BS14', 'BS24', 'BS34')
)
INIT_PARAM_NAMES = frozenset(('yy_r4_ZT', 'zz_r4_ZT'))
logger = logging.getLogger(__name__)


def _validate_json_depth(value, depth=1):
    if depth > MAX_JSON_NESTING_DEPTH:
        raise ValueError(f'JSON 嵌套深度超过上限 {MAX_JSON_NESTING_DEPTH}')
    if isinstance(value, dict):
        for child in value.values():
            _validate_json_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_json_depth(child, depth + 1)


def _read_json_with_limits(filepath, validator=None):
    size = os.path.getsize(filepath)
    if size > MAX_JSON_FILE_SIZE:
        raise ValueError(f'JSON 文件大小超过上限 {MAX_JSON_FILE_SIZE} 字节')
    with open(filepath, 'r', encoding='utf-8') as handle:
        payload = json.load(handle)
    _validate_json_depth(payload)
    if validator is not None:
        payload = validator(payload)
    return payload


def _quarantine_corrupt_file(filepath):
    if not os.path.isfile(filepath):
        return None
    timestamp = dt.datetime.now().strftime('%Y%m%d%H%M%S%f')
    candidate = f'{filepath}.corrupt-{timestamp}'
    suffix = 1
    while os.path.lexists(candidate):
        candidate = f'{filepath}.corrupt-{timestamp}-{suffix}'
        suffix += 1
    try:
        os.replace(filepath, candidate)
    except OSError as exc:
        logger.warning('无法隔离损坏 JSON: %s', type(exc).__name__)
        return None
    logger.warning('已隔离损坏 JSON: %s', os.path.basename(candidate))
    return candidate


def _backup_valid_json(filepath, validator):
    if not os.path.isfile(filepath):
        return None
    try:
        _read_json_with_limits(filepath, validator)
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        return False
    backup_path = filepath + '.bak'
    temporary_path = backup_path + '.tmp'
    try:
        shutil.copy2(filepath, temporary_path)
        os.replace(temporary_path, backup_path)
    except OSError:
        if os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass
        raise
    return True


def _ensure_finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label} 必须是数值')
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError) as exc:
        raise ValueError(f'{label} 必须是有限数值') from exc
    if not finite:
        raise ValueError(f'{label} 必须是有限数值')
    return value


def create_default_profile(name: str = '默认标定参数') -> dict:
    now = dt.datetime.now().isoformat(timespec='seconds')
    return {
        'id': uuid.uuid4().hex,
        'name': name,
        'data_path': '',
        'fixed_params': copy.deepcopy(DEFAULT_FIXED_PARAMS),
        'init_params': copy.deepcopy(DEFAULT_INIT_PARAMS),
        'notes': '',
        'created_at': now,
        'updated_at': now,
    }


class CalibrationBatchStore:
    """CRUD storage for reusable calibration parameter profiles."""

    VERSION = SCHEMA_VERSION

    def __init__(self, filepath: str | None = None):
        self.filepath = filepath or os.path.join(
            get_user_data_dir('测向校正'), 'batch_configs.json')
        self._profiles: list[dict] = []
        self._load()

    def list_profiles(self) -> list[dict]:
        return copy.deepcopy(self._profiles)

    def get_profile(self, profile_id: str) -> dict | None:
        for profile in self._profiles:
            if profile['id'] == profile_id:
                return copy.deepcopy(profile)
        return None

    def save_profile(self, profile: dict, profile_id: str | None = None) -> dict:
        normalized = self._normalize_profile(profile, profile_id)
        duplicate = next((
            item for item in self._profiles
            if item['name'].casefold() == normalized['name'].casefold()
            and item['id'] != normalized['id']
        ), None)
        if duplicate is not None:
            raise ValueError(f'批次参数名称“{normalized["name"]}”已存在')

        for index, existing in enumerate(self._profiles):
            if existing['id'] == normalized['id']:
                normalized['created_at'] = existing.get(
                    'created_at', normalized['created_at']
                )
                normalized['updated_at'] = dt.datetime.now().isoformat(
                    timespec='seconds'
                )
                self._profiles[index] = normalized
                break
        else:
            self._profiles.append(normalized)
        self._save()
        return copy.deepcopy(normalized)

    def delete_profile(self, profile_id: str) -> bool:
        remaining = [item for item in self._profiles if item['id'] != profile_id]
        if len(remaining) == len(self._profiles):
            return False
        self._profiles = remaining
        self._save()
        return True

    @staticmethod
    def _optional_text(profile, field, default=''):
        if field not in profile:
            return default
        value = profile[field]
        if not isinstance(value, str):
            raise ValueError(f'{field} 必须是字符串')
        return value

    def _normalize_profile(self, profile: dict, profile_id: str | None = None) -> dict:
        if not isinstance(profile, dict):
            raise ValueError('校正配置必须是 JSON 对象')
        name_value = profile.get('name')
        if not isinstance(name_value, str):
            raise ValueError('批次参数名称必须是字符串')
        name = name_value.strip()
        if not name:
            raise ValueError('请输入批次参数名称')

        if profile_id is not None:
            raw_id = profile_id
        elif 'id' in profile:
            raw_id = profile['id']
        else:
            raw_id = uuid.uuid4().hex
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise ValueError('配置 ID 必须是非空字符串')
        normalized_id = raw_id.strip()

        now = dt.datetime.now().isoformat(timespec='seconds')
        fixed_input = profile.get('fixed_params', {})
        if not isinstance(fixed_input, dict):
            raise ValueError('fixed_params 必须是 JSON 对象')
        unknown_fixed = set(fixed_input) - set(DEFAULT_FIXED_PARAMS)
        if unknown_fixed:
            raise ValueError(
                '未知固定参数: ' + ', '.join(sorted(str(key) for key in unknown_fixed))
            )
        fixed = copy.deepcopy(DEFAULT_FIXED_PARAMS)
        fixed.update(copy.deepcopy(fixed_input))

        matrix = fixed.get('matrixZT2ANT')
        if not isinstance(matrix, list) or len(matrix) != 3:
            raise ValueError('matrixZT2ANT 必须是 3x3 矩阵')
        for row in matrix:
            if not isinstance(row, list) or len(row) != 3:
                raise ValueError('matrixZT2ANT 必须是 3x3 矩阵')
            for value in row:
                _ensure_finite_number(value, 'matrixZT2ANT 元素')
        for key in FIXED_SCALAR_PARAMS:
            _ensure_finite_number(fixed[key], key)

        init_input = profile.get('init_params', {})
        if not isinstance(init_input, dict):
            raise ValueError('init_params 必须是 JSON 对象')
        unknown_init = set(init_input) - set(DEFAULT_INIT_PARAMS)
        if unknown_init:
            raise ValueError(
                '未知初值参数: ' + ', '.join(sorted(str(key) for key in unknown_init))
            )
        init = copy.deepcopy(DEFAULT_INIT_PARAMS)
        init.update(copy.deepcopy(init_input))
        for key in INIT_PARAM_NAMES:
            _ensure_finite_number(init[key], key)

        return {
            'id': normalized_id,
            'name': name,
            'data_path': self._optional_text(profile, 'data_path').strip(),
            'fixed_params': fixed,
            'init_params': init,
            'notes': self._optional_text(profile, 'notes'),
            'created_at': self._optional_text(profile, 'created_at', now),
            'updated_at': self._optional_text(profile, 'updated_at', now),
        }

    @staticmethod
    def _validate_document(payload):
        document = migrate_schema(payload, 'calibration_config')
        if set(document) != {'schema_version', 'profiles'}:
            raise ValueError('批次参数库 Schema 字段不完整')
        if not isinstance(document.get('profiles'), list):
            raise ValueError('profiles 必须是 JSON 数组')
        return document

    def _validate_payload(self, payload):
        document = self._validate_document(payload)
        raw_profiles = document['profiles']
        seen_ids = set()
        for item in raw_profiles:
            profile_id = item.get('id') if isinstance(item, dict) else None
            normalized = self._normalize_profile(item, profile_id)
            if normalized['id'] in seen_ids:
                raise ValueError('配置 ID 重复')
            seen_ids.add(normalized['id'])
        return document

    def _load(self):
        if not os.path.isfile(self.filepath):
            self._profiles = [create_default_profile()]
            self._save()
            return
        try:
            payload = _read_json_with_limits(
                self.filepath, self._validate_document
            )
            raw_profiles = payload['profiles']
        except Exception as exc:
            quarantined = _quarantine_corrupt_file(self.filepath)
            if quarantined is None and os.path.lexists(self.filepath):
                raise ValueError('批次参数库读取失败，且无法隔离损坏文件') from exc
            logger.error(
                '批次参数库读取失败（%s），已隔离原文件',
                type(exc).__name__,
            )
            self._profiles = [create_default_profile()]
            self._save()
            return

        self._profiles = []
        seen_ids = set()
        for index, item in enumerate(raw_profiles):
            try:
                profile_id = item.get('id') if isinstance(item, dict) else None
                normalized = self._normalize_profile(item, profile_id)
            except Exception as exc:
                logger.warning(
                    '跳过非法校正配置 index=%s: %s', index, exc
                )
                continue
            if normalized['id'] in seen_ids:
                logger.warning('跳过重复校正配置 ID index=%s', index)
                continue
            seen_ids.add(normalized['id'])
            self._profiles.append(normalized)

    def _save(self):
        directory = os.path.dirname(os.path.abspath(self.filepath))
        os.makedirs(directory, exist_ok=True)
        temporary_path = self.filepath + '.tmp'
        payload = {
            'schema_version': self.VERSION,
            'profiles': self._profiles,
        }
        try:
            self._validate_payload(payload)
            backup_status = _backup_valid_json(
                self.filepath, self._validate_payload
            )
            if backup_status is False:
                if (
                    _quarantine_corrupt_file(self.filepath) is None
                    and os.path.lexists(self.filepath)
                ):
                    raise RuntimeError('无法隔离损坏的批次参数库文件')
            with open(temporary_path, 'w', encoding='utf-8') as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.filepath)
        except Exception:
            if os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass
            raise
