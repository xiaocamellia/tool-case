"""JSON persistence limits and corrupt-file isolation."""
import datetime
import json
import os
import shutil

from . import exp_recorder as _context

def _reject_json_constant(value):
    raise ValueError(f'不支持的 JSON 常量: {value}')
def _validate_json_depth(value, depth=1):
    if depth > _context.MAX_JSON_NESTING_DEPTH:
        raise ValueError(f'JSON 嵌套深度超过上限 {_context.MAX_JSON_NESTING_DEPTH}')
    if isinstance(value, dict):
        for child in value.values():
            _validate_json_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_json_depth(child, depth + 1)
def _read_json_with_limits(filepath, validator=None):
    size = os.path.getsize(filepath)
    if size > _context.MAX_JSON_FILE_SIZE:
        raise ValueError(f'JSON 文件大小超过上限 {_context.MAX_JSON_FILE_SIZE} 字节')
    with open(filepath, 'r', encoding='utf-8') as handle:
        payload = json.load(handle, parse_constant=_reject_json_constant)
    _validate_json_depth(payload)
    if validator is not None:
        payload = validator(payload)
    return payload
def _quarantine_corrupt_file(filepath):
    if not os.path.isfile(filepath):
        return None
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
    candidate = f'{filepath}.corrupt-{timestamp}'
    suffix = 1
    while os.path.lexists(candidate):
        candidate = f'{filepath}.corrupt-{timestamp}-{suffix}'
        suffix += 1
    try:
        os.replace(filepath, candidate)
    except OSError as exc:
        _context.logger.warning('无法隔离损坏 JSON: %s', type(exc).__name__)
        return None
    _context.logger.warning('已隔离损坏 JSON: %s', os.path.basename(candidate))
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
    except OSError as exc:
        if os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass
        _context.logger.warning('无法更新 JSON 备份: %s', type(exc).__name__)
        raise
    return True
