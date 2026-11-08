"""Packaging-facing path and application smoke checks."""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

from radar_tool.runtime_paths import (
    _safe_join,
    get_bundle_root,
    get_resource_path,
    get_user_data_dir,
    get_user_data_root,
    get_bundle_root,
)
from radar_tool.smoke_test import run_smoke_test


def test_source_package_resource_and_user_data_paths_are_isolated(tmp_path):
    assert os.path.isfile(get_resource_path('image', 'rose.ico'))

    data_dir = get_user_data_dir('smoke-test')
    assert os.path.isdir(data_dir)
    assert os.path.commonpath(
        [os.path.abspath(data_dir), os.path.abspath(get_user_data_root())]
    ) == os.path.abspath(get_user_data_root())


def test_frozen_bundle_uses_executable_directory_and_appdata(tmp_path):
    executable = tmp_path / 'PortableRadarToolbox.exe'
    executable.write_bytes(b'executable placeholder')
    appdata = tmp_path / 'AppData'

    with patch.object(sys, 'executable', str(executable)), patch.object(
        sys, 'frozen', True, create=True
    ), patch.dict(os.environ, {'APPDATA': str(appdata)}):
        bundle_root = get_bundle_root()
        user_data_root = get_user_data_root()
        user_data_dir = get_user_data_dir('smoke-test')

    assert bundle_root == str(executable.parent)
    assert user_data_root == str(appdata / 'PortableRadarToolbox')
    assert user_data_dir.startswith(user_data_root)


def test_application_smoke_initializes_all_packaging_tabs():
    run_smoke_test()


@pytest.mark.parametrize(
    "component",
    ["", ".", "..", "../escape", "..\\escape", "/absolute", "C:\\absolute", "nested/name"],
)
def test_managed_path_components_reject_traversal_and_separators(component):
    with pytest.raises(ValueError):
        get_user_data_dir(component)
    with pytest.raises(ValueError):
        get_resource_path(component)


def test_realpath_escape_through_symlink_is_rejected(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks are unavailable")
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(ValueError):
        _safe_join(str(root), "link")
