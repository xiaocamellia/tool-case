"""Runtime path helpers for source and bundled executions."""

from __future__ import annotations

import os
import shutil
import sys


APP_NAME = "PortableRadarToolbox"
LEGACY_DATA_NAMES = ('日志', '测向校正', '试验数据', '.matplotlib_cache')


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) or hasattr(sys, "__compiled__"))


def get_bundle_root() -> str:
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_launcher_dir() -> str:
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_user_data_root() -> str:
    if is_frozen():
        base_dir = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base_dir, APP_NAME)
    return os.path.join(get_launcher_dir(), "var")


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _migrate_legacy_user_data(parts: tuple[str, ...], target: str) -> None:
    """Move first-run data from the source tree into the ignored runtime folder."""
    legacy = os.path.join(get_launcher_dir(), *parts)
    if os.path.abspath(legacy) == os.path.abspath(target):
        return
    if not os.path.exists(legacy) or os.path.exists(target):
        return
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.move(legacy, target)
    except OSError:
        # Keep the legacy copy if migration is blocked; never delete user data.
        pass


def migrate_legacy_user_data() -> None:
    """Move known legacy runtime folders into ``var`` during application startup."""
    for name in LEGACY_DATA_NAMES:
        target = os.path.join(get_user_data_root(), name)
        _migrate_legacy_user_data((name,), target)


def get_user_data_dir(*parts: str) -> str:
    normalized_parts = tuple(str(part) for part in parts)
    target = os.path.join(get_user_data_root(), *normalized_parts)
    _migrate_legacy_user_data(normalized_parts, target)
    return ensure_dir(target)


def get_resource_path(*parts: str) -> str:
    return os.path.join(get_bundle_root(), *parts)
