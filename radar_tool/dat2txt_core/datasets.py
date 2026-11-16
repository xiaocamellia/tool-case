"""Dataset registry: which data type uses which CSV table and frame length.

Mirrors the ``switch`` inside ``SQLiteControl.ExportDatFrameToTxt`` where the
selected table value decides ``frameByteLength`` and ``codeId``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .spec_csv import FieldSpec, load_specs

#: Environment variable that overrides the ``Config`` directory lookup.
CONFIG_ENV = "DAT2TXT_CONFIG"


@dataclass(frozen=True)
class Dataset:
    """One entry of the "数据类型" drop down."""

    key: str
    label: str
    code_id: int
    frame_length: int
    csv_relative_path: str

    @property
    def frame_data_length(self) -> int:
        """Payload length, i.e. frame length without the 6 BCD timestamp bytes."""
        return self.frame_length - 6


DATASETS: tuple[Dataset, ...] = (
    Dataset(
        key="雷达内部工况",
        label="雷达内部工况（0x3014）",
        code_id=0x3014,
        frame_length=326,
        csv_relative_path="内部工况遥测/载人雷达内部工况接口遥测.csv",
    ),
    Dataset(
        key="应答机内部工况",
        label="应答机内部工况（0x3024）",
        code_id=0x3024,
        frame_length=326,
        csv_relative_path="内部工况遥测/载人应答机内部工况接口遥测.csv",
    ),
    Dataset(
        key="雷达端KA波段非锁定",
        label="KA 波段雷达 非锁定（0x3034 / 0x512）",
        code_id=0x512,
        frame_length=233,
        csv_relative_path="内部调试遥测/KA波段微波雷达非锁定状态遥测包.csv",
    ),
    Dataset(
        key="雷达端KA波段锁定",
        label="KA 波段雷达 锁定（0x3044 / 0x513）",
        code_id=0x513,
        frame_length=233,
        csv_relative_path="内部调试遥测/KA波段微波雷达锁定状态遥测包.csv",
    ),
    Dataset(
        key="KA_KU非锁定",
        label="KA_KU 非锁定（0x510）",
        code_id=0x510,
        frame_length=191,
        csv_relative_path="内部调试遥测/KA_KU非锁定遥测数据包.csv",
    ),
    Dataset(
        key="KA_KU锁定",
        label="KA_KU 锁定（0x511）",
        code_id=0x511,
        frame_length=191,
        csv_relative_path="内部调试遥测/KA_KU锁定遥测数据包.csv",
    ),
)

_SPEC_CACHE: dict[str, list[FieldSpec]] = {}


def config_root() -> Path:
    """Locate the bundled ``Config`` directory of the field definitions.

    Falls back to the simulator installation layout via ``DAT2TXT_CONFIG``
    when the caller wants to point at an external Config tree.
    """
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser().resolve()
    from ..runtime_paths import get_resource_path

    return Path(get_resource_path("Config"))


def receive_root() -> Path:
    """``Config/receive`` (all telemetry tables live below it)."""
    return config_root() / "receive"


def csv_path(dataset: Dataset) -> Path:
    """Absolute path of the field definition CSV of *dataset*."""
    return receive_root() / dataset.csv_relative_path


def find_dataset(code_id: int) -> Optional[Dataset]:
    """Look up a dataset by its telemetry code id."""
    for dataset in DATASETS:
        if dataset.code_id == code_id:
            return dataset
    return None


def load_dataset_specs(dataset: Dataset) -> list[FieldSpec]:
    """Load (and cache) the field definitions of *dataset*."""
    path = csv_path(dataset)
    cache_key = str(path)
    cached = _SPEC_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if not path.is_file():
        raise FileNotFoundError(
            "找不到字段定义文件：%s\n请确认 Config 目录完整，或用环境变量 %s 指定 Config 路径。"
            % (path, CONFIG_ENV)
        )
    specs = load_specs(str(path))
    _SPEC_CACHE[cache_key] = specs
    return specs
