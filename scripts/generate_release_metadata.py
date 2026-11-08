"""Generate deterministic release metadata, inventories, and CycloneDX SBOM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pip-cache",
    ".pytest_cache",
    ".pytest-temp-functional",
    ".ruff_cache",
    ".venv",
    ".venv-build",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
    "var",
}
PIN_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_source_files(root: Path) -> Iterable[Path]:
    for current_root, directories, files in os.walk(root):
        directories[:] = sorted(
            name for name in directories if name not in EXCLUDED_DIRS
        )
        current = Path(current_root)
        for name in sorted(files):
            path = current / name
            if not path.is_symlink():
                yield path


def source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in iter_source_files(root):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def parse_lock(path: Path) -> List[Tuple[str, str]]:
    components: List[Tuple[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_PATTERN.fullmatch(line)
        if not match:
            raise ValueError(f"invalid exact pin in {path.name}: {line}")
        components.append((match.group(1), match.group(2)))
    return components


def normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def purl(name: str, version: str) -> str:
    return f"pkg:pypi/{normalized_name(name)}@{version}"


def write_json(path: Path, value: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )


def build_components(
    version: str, lock_components: List[Tuple[str, str]]
) -> List[Dict[str, str]]:
    components = [
        {
            "name": "Portable Radar Toolbox",
            "type": "application",
            "version": version,
            "purl": f"pkg:generic/portable-radar-toolbox@{version}",
        }
    ]
    components.extend(
        {
            "name": name,
            "type": "library",
            "version": package_version,
            "purl": purl(name, package_version),
        }
        for name, package_version in lock_components
    )
    return components


def build_sbom(
    components: List[Dict[str, str]], source_hash: str, generated_at: str
) -> Dict[str, Any]:
    serial_number = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"urn:portable-radar-toolbox:sbom:{source_hash}",
        )
    )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial_number}",
        "version": 1,
        "metadata": {
            "timestamp": generated_at,
            "tools": [{"vendor": "Portable Radar Toolbox", "name": "release-metadata", "version": "1"}],
            "component": {
                "type": "application",
                "name": "Portable Radar Toolbox",
                "version": components[0]["version"],
                "purl": components[0]["purl"],
            },
            "properties": [{"name": "radar_tool:source_sha256", "value": source_hash}],
        },
        "components": [
            {
                "type": component["type"],
                "name": component["name"],
                "version": component["version"],
                "purl": component["purl"],
            }
            for component in components[1:]
        ],
    }


def release_files(release_dir: Path, manifest_name: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for path in sorted(release_dir.rglob("*")):
        if not path.is_file() or path.name == manifest_name:
            continue
        results.append(
            {
                "path": path.relative_to(release_dir).as_posix(),
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-date-epoch", type=int, default=0)
    parser.add_argument("--build-log", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    release_dir = args.release_dir.resolve()
    release_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.fromtimestamp(
        args.source_date_epoch, timezone.utc
    ).isoformat().replace("+00:00", "Z")
    lock_path = root / "requirements.lock"
    source_hash = source_digest(root)
    components = build_components(args.version, parse_lock(lock_path))
    inventory = {
        "format": "portable-radar-toolbox-third-party-inventory/v1",
        "generated_at": generated_at,
        "lock": {
            "path": "requirements.lock",
            "sha256": sha256_file(lock_path),
        },
        "components": components[1:],
    }
    write_json(release_dir / "third-party-components.json", inventory)
    write_json(
        release_dir / "sbom.cdx.json",
        build_sbom(components, source_hash, generated_at),
    )
    build_manifest = {
        "format": "portable-radar-toolbox-build-manifest/v1",
        "application": {"name": "Portable Radar Toolbox", "version": args.version},
        "build": {
            "source_sha256": source_hash,
            "source_date_epoch": args.source_date_epoch,
            "generated_at": generated_at,
            "python": {
                "implementation": platform.python_implementation(),
                "version": platform.python_version(),
                "architecture": platform.architecture()[0],
            },
            "platform": platform.platform(),
        },
        "artifacts": release_files(release_dir, "build-manifest.json"),
    }
    if args.build_log and args.build_log.is_file():
        build_manifest["build_log_sha256"] = sha256_file(args.build_log)
    write_json(release_dir / "build-manifest.json", build_manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
