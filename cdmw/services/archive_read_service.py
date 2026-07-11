"""Read-only archive data and presentation summaries."""

from __future__ import annotations

from typing import Any


def read_archive_entry_data(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_extraction import read_archive_entry_data as owner

    return owner(*args, **kwargs)


def build_archive_entry_detail_text(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_extraction import build_archive_entry_detail_text as owner

    return owner(*args, **kwargs)


def build_archive_entry_metadata_summary(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_extraction import build_archive_entry_metadata_summary as owner

    return owner(*args, **kwargs)


def format_byte_size(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_extraction import format_byte_size as owner

    return owner(*args, **kwargs)


__all__ = [
    "build_archive_entry_detail_text",
    "build_archive_entry_metadata_summary",
    "format_byte_size",
    "read_archive_entry_data",
]
