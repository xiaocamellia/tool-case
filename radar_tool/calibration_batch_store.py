"""Persistent reusable batch profiles for direction-finding calibration."""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import uuid

from .runtime_paths import get_user_data_dir


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

    VERSION = 1

    def __init__(self, filepath: str | None = None):
        self.filepath = filepath or os.path.join(
            get_user_data_dir('测向校正'), 'batch_configs.json')
        self._profiles = []
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
                normalized['created_at'] = existing.get('created_at', normalized['created_at'])
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

    def _normalize_profile(self, profile: dict, profile_id: str | None = None) -> dict:
        name = str(profile.get('name', '')).strip()
        if not name:
            raise ValueError('请输入批次参数名称')
        now = dt.datetime.now().isoformat(timespec='seconds')
        fixed = copy.deepcopy(DEFAULT_FIXED_PARAMS)
        fixed.update(copy.deepcopy(profile.get('fixed_params') or {}))
        matrix = fixed.get('matrixZT2ANT')
        if not isinstance(matrix, list) or len(matrix) != 3 or any(
            not isinstance(row, list) or len(row) != 3 for row in matrix
        ):
            raise ValueError('matrixZT2ANT 必须是 3x3 矩阵')
        init = copy.deepcopy(DEFAULT_INIT_PARAMS)
        init.update(copy.deepcopy(profile.get('init_params') or {}))
        return {
            'id': profile_id or profile.get('id') or uuid.uuid4().hex,
            'name': name,
            'data_path': str(profile.get('data_path', '')).strip(),
            'fixed_params': fixed,
            'init_params': init,
            'notes': str(profile.get('notes', '')),
            'created_at': str(profile.get('created_at') or now),
            'updated_at': str(profile.get('updated_at') or now),
        }

    def _load(self):
        if not os.path.isfile(self.filepath):
            self._profiles = [create_default_profile()]
            self._save()
            return
        try:
            with open(self.filepath, 'r', encoding='utf-8') as file:
                payload = json.load(file)
            raw_profiles = payload.get('profiles', []) if isinstance(payload, dict) else []
            self._profiles = [self._normalize_profile(item, item.get('id')) for item in raw_profiles]
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f'批次参数库读取失败: {exc}') from exc

    def _save(self):
        directory = os.path.dirname(os.path.abspath(self.filepath))
        os.makedirs(directory, exist_ok=True)
        temporary_path = self.filepath + '.tmp'
        payload = {'version': self.VERSION, 'profiles': self._profiles}
        try:
            with open(temporary_path, 'w', encoding='utf-8') as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.filepath)
        except OSError:
            if os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass
            raise
