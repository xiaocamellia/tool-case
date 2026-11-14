"""账本 JSON 持久化：限深读取、写前备份、写坏隔离（对齐既有 JSON 安全模式）。"""

from __future__ import annotations

import datetime
import json
import os
import shutil
from typing import Optional

from ..errors import ValidationError
from ..logger import get_logger
from .schema import LedgerDocument, make_blank_document, make_sample_document

logger = get_logger("coord_storage")

MAX_JSON_FILE_SIZE = 10 * 1024 * 1024
MAX_JSON_NESTING_DEPTH = 64

_LAST_LEDGER_NAME = "last_ledger.txt"


def _last_ledger_path() -> str:
    from ..runtime_paths import get_user_data_dir

    return os.path.join(get_user_data_dir("坐标系账本"), _LAST_LEDGER_NAME)


def remember_last_ledger(filepath: str) -> None:
    """记录最近打开/保存的账本路径，供下次启动恢复。"""
    try:
        state_path = _last_ledger_path()
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as handle:
            handle.write(os.path.abspath(filepath))
    except OSError as exc:
        logger.warning("无法记录最近账本路径: %s", type(exc).__name__)


def load_last_ledger() -> Optional[str]:
    """返回最近账本路径；不存在或已删除时返回 None。"""
    try:
        state_path = _last_ledger_path()
        if not os.path.isfile(state_path):
            return None
        with open(state_path, "r", encoding="utf-8") as handle:
            candidate = handle.read().strip()
        return candidate if candidate and os.path.isfile(candidate) else None
    except OSError:
        return None


def default_work_ledger_path(name: str = "ledger_work_v1.0.json") -> str:
    """未指定保存位置时的工作账本路径（用户数据目录）。"""
    from ..runtime_paths import get_user_data_dir

    return os.path.join(get_user_data_dir("坐标系账本"), name)


def _reject_json_constant(value):
    raise ValueError(f"不支持的 JSON 常量: {value}")


def _validate_json_depth(value, depth=1):
    if depth > MAX_JSON_NESTING_DEPTH:
        raise ValueError(f"JSON 嵌套深度超过上限 {MAX_JSON_NESTING_DEPTH}")
    if isinstance(value, dict):
        for child in value.values():
            _validate_json_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_json_depth(child, depth + 1)


def _read_json_with_limits(filepath: str):
    size = os.path.getsize(filepath)
    if size > MAX_JSON_FILE_SIZE:
        raise ValueError(f"JSON 文件大小超过上限 {MAX_JSON_FILE_SIZE} 字节")
    with open(filepath, "r", encoding="utf-8") as handle:
        payload = json.load(handle, parse_constant=_reject_json_constant)
    _validate_json_depth(payload)
    return payload


def quarantine_corrupt_file(filepath: str) -> Optional[str]:
    """把损坏文件改名隔离，返回隔离后的路径。"""
    if not os.path.isfile(filepath):
        return None
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    candidate = f"{filepath}.corrupt-{timestamp}"
    suffix = 1
    while os.path.lexists(candidate):
        candidate = f"{filepath}.corrupt-{timestamp}-{suffix}"
        suffix += 1
    try:
        os.replace(filepath, candidate)
    except OSError as exc:
        logger.warning("无法隔离损坏 JSON: %s", type(exc).__name__)
        return None
    logger.warning("已隔离损坏 JSON: %s", os.path.basename(candidate))
    return candidate


def backup_valid_json(filepath: str) -> Optional[bool]:
    """写前备份：文件有效则复制为 ``.bak``；无效返回 False；不存在返回 None。"""
    if not os.path.isfile(filepath):
        return None
    try:
        _read_json_with_limits(filepath)
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, ValidationError):
        return False
    backup_path = filepath + ".bak"
    temporary_path = backup_path + ".tmp"
    try:
        shutil.copy2(filepath, temporary_path)
        os.replace(temporary_path, backup_path)
    except OSError as exc:
        if os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass
        logger.warning("无法更新 JSON 备份: %s", type(exc).__name__)
        raise
    return True


def load_document(filepath: str) -> LedgerDocument:
    """读取账本；损坏文件自动隔离后报错。"""
    if not os.path.isfile(filepath):
        raise ValidationError(f"账本文件不存在: {os.path.basename(filepath)}")
    try:
        payload = _read_json_with_limits(filepath)
        return LedgerDocument.from_dict(payload)
    except (ValueError, TypeError, OverflowError, RecursionError, ValidationError) as exc:
        quarantine_corrupt_file(filepath)
        message = getattr(exc, "user_message", None) or str(exc)
        raise ValidationError(f"账本读取失败：{message}") from exc


def save_document(document: LedgerDocument, filepath: str) -> str:
    """安全写盘：写前备份有效旧文件，原子替换（A7）。"""
    payload = document.to_dict()
    # 写出前自校验，防止把非法账本落盘
    document.validate().raise_if_failed()
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    text += "\n"

    directory = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(directory, exist_ok=True)

    if os.path.isfile(filepath):
        status = backup_valid_json(filepath)
        if status is False:
            quarantine_corrupt_file(filepath)

    temporary_path = filepath + ".tmp"
    with open(temporary_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary_path, filepath)
    logger.info("账本已保存: %s", os.path.basename(filepath))
    return filepath


def write_template(filepath: str, sample: bool = True, name: str = "新建坐标系账本") -> str:
    """生成模板账本（A3）。"""
    document = make_sample_document() if sample else make_blank_document(name)
    return save_document(document, filepath)


def merge_documents(documents, name: str = "合并账本") -> LedgerDocument:
    """多文件合并（A4）：id 冲突报错。"""
    from .schema import LedgerDocument as _Doc
    from .schema import LedgerMeta

    if not documents:
        raise ValidationError("没有可合并的账本")
    meta = documents[0].meta
    merged = _Doc(meta=LedgerMeta.from_dict({**meta.to_dict(), "name": name}))
    seen = {"frames": set(), "transforms": set(), "limits": set()}
    for document in documents:
        for frame in document.frames:
            if frame.id in seen["frames"]:
                raise ValidationError(f"合并冲突：坐标系 id 重复 {frame.id}")
            seen["frames"].add(frame.id)
            merged.frames.append(frame)
        for record in document.transforms:
            if record.id in seen["transforms"]:
                raise ValidationError(f"合并冲突：变换 id 重复 {record.id}")
            seen["transforms"].add(record.id)
            merged.transforms.append(record)
        for limit in document.limits:
            if limit.id in seen["limits"]:
                raise ValidationError(f"合并冲突：限值 id 重复 {limit.id}")
            seen["limits"].add(limit.id)
            merged.limits.append(limit)
    return merged
