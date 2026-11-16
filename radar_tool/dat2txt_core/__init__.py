"""dat -> txt export core.

Portable re-implementation of the mature simulator's
``SQLiteControl.ExportDatFrameToTxt`` pipeline, kept standard-library only so
the exporter can run wherever the toolbox runs.  Field definitions live in the
bundled ``Config/receive`` CSV tables (override with ``DAT2TXT_CONFIG``).
"""

from __future__ import annotations

from .datasets import (
    CONFIG_ENV,
    DATASETS,
    Dataset,
    config_root,
    csv_path,
    find_dataset,
    load_dataset_specs,
    receive_root,
)
from .exporter import (
    COLUMN_HEADER,
    ExportCancelled,
    ExportError,
    ExportRequest,
    ExportResult,
    bcd_bytes_to_datetime,
    column_file_path,
    default_output_path,
    ensure_parent,
    export_dat,
    frame_count,
    header_names,
    read_frame_time,
    summarize,
    write_column_file,
)
from .spec_csv import FieldSpec, load_specs

__all__ = [
    "CONFIG_ENV",
    "COLUMN_HEADER",
    "DATASETS",
    "Dataset",
    "ExportCancelled",
    "ExportError",
    "ExportRequest",
    "ExportResult",
    "FieldSpec",
    "bcd_bytes_to_datetime",
    "column_file_path",
    "config_root",
    "csv_path",
    "default_output_path",
    "ensure_parent",
    "export_dat",
    "find_dataset",
    "frame_count",
    "header_names",
    "load_dataset_specs",
    "load_specs",
    "read_frame_time",
    "receive_root",
    "summarize",
    "write_column_file",
]
