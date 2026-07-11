"""Archive extraction and destination coordination boundary."""

from __future__ import annotations

from typing import Any


def clear_directory_contents(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_extraction import clear_directory_contents as owner

    return owner(*args, **kwargs)


def count_existing_archive_targets(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_extraction import count_existing_archive_targets as owner

    return owner(*args, **kwargs)


def directory_has_contents(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_extraction import directory_has_contents as owner

    return owner(*args, **kwargs)


def extract_archive_entries(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_extraction import extract_archive_entries as owner

    return owner(*args, **kwargs)


def extract_archive_entry(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_extraction import extract_archive_entry as owner

    return owner(*args, **kwargs)


def find_available_output_path(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_extraction import find_available_output_path as owner

    return owner(*args, **kwargs)


__all__ = [
    "clear_directory_contents",
    "count_existing_archive_targets",
    "directory_has_contents",
    "extract_archive_entries",
    "extract_archive_entry",
    "find_available_output_path",
]
