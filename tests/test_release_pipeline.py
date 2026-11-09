"""Static and deterministic-output checks for the release pipeline."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import radar_tool


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_release_version_and_build_environment_are_consistent():
    config = json.loads((ROOT / "build-environment.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    build_script = (ROOT / "packaging/nuitka/build.ps1").read_text(encoding="utf-8")

    assert radar_tool.__version__ == config["application_version"] == "1.1.0"
    assert 'version = "1.1.0"' in pyproject
    assert "--standalone" in build_script
    assert "--onefile" not in build_script
    assert "--nofollow-import-to=*.tests" in build_script
    assert "--include-package-data=matplotlib" in build_script
    assert "--include-package-data=openpyxl" in build_script
    assert "--include-package-data=docx" in build_script
    assert "Get-AuthenticodeSignature" in build_script
    assert "scripts\\generate_release_metadata.py" in build_script
    assert "scripts\\package_release.py" in build_script


def test_dependency_lock_hashes_are_current():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_lock_hash.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_release_metadata_generation_is_deterministic(tmp_path):
    release_dir = tmp_path / "release"
    command = [
        sys.executable,
        str(ROOT / "scripts/generate_release_metadata.py"),
        "--root",
        str(ROOT),
        "--release-dir",
        str(release_dir),
        "--version",
        "1.1.0",
        "--source-date-epoch",
        "1700000000",
    ]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    first_hashes = {
        path.name: _sha256(path) for path in sorted(release_dir.iterdir()) if path.is_file()
    }

    second = subprocess.run(command, capture_output=True, text=True, check=True)
    second_hashes = {
        path.name: _sha256(path) for path in sorted(release_dir.iterdir()) if path.is_file()
    }

    assert first.returncode == second.returncode == 0
    assert first_hashes == second_hashes
    assert {
        "build-manifest.json",
        "sbom.cdx.json",
        "third-party-components.json",
    } == set(second_hashes)


def test_release_zip_is_deterministic(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "app.exe").write_bytes(b"portable executable")
    (release_dir / "image").mkdir()
    (release_dir / "image" / "rose.ico").write_bytes(b"icon")

    first_zip = tmp_path / "first.zip"
    second_zip = tmp_path / "second.zip"
    for output in (first_zip, second_zip):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/package_release.py"),
                "--release-dir",
                str(release_dir),
                "--output",
                str(output),
                "--source-date-epoch",
                "1700000000",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    assert _sha256(first_zip) == _sha256(second_zip)
    with zipfile.ZipFile(first_zip) as archive:
        assert archive.namelist() == ["app.exe", "image/rose.ico"]
