"""Archive preview preparation boundary."""

from __future__ import annotations

from typing import Any


def ensure_archive_preview_source(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_media_preview import ensure_archive_preview_source as owner

    return owner(*args, **kwargs)


def build_archive_preview_result(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_preview_result_builder import build_archive_preview_result as owner

    return owner(*args, **kwargs)


__all__ = ["build_archive_preview_result", "ensure_archive_preview_source"]
