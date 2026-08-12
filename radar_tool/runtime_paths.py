"""Runtime path helpers for source and bundled executions."""

from __future__ import annotations

import os
import sys


APP_NAME = "PortableRadarToolbox"


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
    return get_launcher_dir()


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def get_user_data_dir(*parts: str) -> str:
    return ensure_dir(os.path.join(get_user_data_root(), *parts))


def get_resource_path(*parts: str) -> str:
    return os.path.join(get_bundle_root(), *parts)
