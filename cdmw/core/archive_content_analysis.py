"""Read the bounded semantic artifacts emitted by the resident archive worker."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Protocol


_MAXIMUM_JSON_BYTES = 4 * 1024 * 1024
_MAXIMUM_TEXT_BYTES = 2 * 1024 * 1024


class _AnalyzedArchiveEntry(Protocol):
    extension: str
    content_analysis_json_path: Path | None
    content_analysis_text_path: Path | None
    content_analysis_version: str


@dataclass(frozen=True, slots=True)
class ArchiveContentAnalysisPreview:
    text: str
    json_path: Path
    analyzer_version: str
    maturity: str
    content_kind: str


def load_archive_content_analysis(
    entry: _AnalyzedArchiveEntry,
) -> ArchiveContentAnalysisPreview | None:
    json_path = getattr(entry, "content_analysis_json_path", None)
    text_path = getattr(entry, "content_analysis_text_path", None)
    if not isinstance(json_path, Path) or not isinstance(text_path, Path):
        return None
    try:
        if not json_path.is_file() or not text_path.is_file():
            return None
        if json_path.stat().st_size > _MAXIMUM_JSON_BYTES or text_path.stat().st_size > _MAXIMUM_TEXT_BYTES:
            return None
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return None
        extension = str(payload.get("extension") or "").strip().casefold()
        if extension != str(entry.extension or "").strip().casefold():
            return None
        analyzer_version = str(payload.get("analyzer_version") or "").strip()
        expected_version = str(getattr(entry, "content_analysis_version", "") or "").strip()
        if not analyzer_version or (expected_version and analyzer_version != expected_version):
            return None
        return ArchiveContentAnalysisPreview(
            text=text_path.read_text(encoding="utf-8"),
            json_path=json_path,
            analyzer_version=analyzer_version,
            maturity=str(payload.get("maturity") or "unknown"),
            content_kind=str(payload.get("content_kind") or "generic_binary"),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return None


__all__ = ["ArchiveContentAnalysisPreview", "load_archive_content_analysis"]
