"""Create a deterministic ZIP archive from a verified standalone release."""

from __future__ import annotations

import argparse
import stat
import time
import zipfile
from pathlib import Path
from typing import List, Tuple


def zip_datetime(epoch: int) -> Tuple[int, int, int, int, int, int]:
    value = time.gmtime(max(epoch, 315532800))
    return (
        value.tm_year,
        value.tm_mon,
        value.tm_mday,
        value.tm_hour,
        value.tm_min,
        value.tm_sec,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    release_dir = args.release_dir.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files: List[Path] = sorted(
        path for path in release_dir.rglob("*") if path.is_file()
    )
    if not files:
        raise SystemExit("release directory is empty")
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = path.relative_to(release_dir).as_posix()
            info = zipfile.ZipInfo(relative, zip_datetime(args.source_date_epoch))
            mode = 0o755 if path.suffix.lower() in {".exe", ".dll", ".pyd"} else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
