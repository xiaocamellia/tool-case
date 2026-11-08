"""Verify recorded SHA256 values and exact pins in all dependency lock files."""

from __future__ import annotations

import hashlib
from pathlib import Path


LOCK_NAMES = ("requirements.lock", "requirements-build.lock")


def verify_lock(root: Path, lock_name: str) -> None:
    lock_path = root / lock_name
    hash_path = root / f"{lock_name}.sha256"
    lock_bytes = lock_path.read_bytes()
    expected_line = hash_path.read_text(encoding="utf-8").strip().split()
    if len(expected_line) != 2 or expected_line[1] != lock_name:
        raise SystemExit(f"{hash_path.name} format is invalid")
    expected = expected_line[0].lower()
    actual = hashlib.sha256(lock_bytes).hexdigest()
    if actual != expected:
        raise SystemExit(
            f"{lock_name} hash mismatch: "
            f"expected={expected}, actual={actual}"
        )

    for raw_line in lock_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line or any(
            marker in line for marker in (">=", "<=", "~=", "!=")
        ):
            raise SystemExit(f"lock files must use exact pins only: {line}")
    print(f"{lock_name} SHA256 and exact pins verified")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    for lock_name in LOCK_NAMES:
        verify_lock(root, lock_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
