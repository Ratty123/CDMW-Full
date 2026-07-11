"""Cancellable language import/export requests."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from cdmw.services.localization_file_service import (
    load_language_file,
    safe_language_code,
    write_language_file,
)


@dataclass(frozen=True, slots=True)
class LanguageExportRequest:
    output_path: Path
    language_code: str
    language_name: str
    translations: tuple[tuple[str, str], ...]
    request_id: int = 0


@dataclass(frozen=True, slots=True)
class LanguageExportResult:
    request_id: int
    output_path: Path
    language_code: str
    translation_count: int


@dataclass(frozen=True, slots=True)
class LanguageImportRequest:
    source_path: Path
    language_dir: Path
    request_id: int = 0


@dataclass(frozen=True, slots=True)
class LanguageImportResult:
    request_id: int
    language_code: str
    language_name: str
    target_path: Path
    translations: tuple[tuple[str, str], ...]


def run_language_export(
    request: LanguageExportRequest,
    *,
    stop_event: threading.Event | None = None,
) -> LanguageExportResult:
    translations = dict(request.translations)
    write_language_file(
        request.output_path,
        language_code=request.language_code,
        language_name=request.language_name,
        translations=translations,
        stop_event=stop_event,
    )
    return LanguageExportResult(
        request.request_id,
        request.output_path,
        request.language_code,
        len(translations),
    )


def run_language_import(
    request: LanguageImportRequest,
    *,
    stop_event: threading.Event | None = None,
) -> LanguageImportResult:
    _raw_code, language_name, translations = load_language_file(
        request.source_path,
        stop_event=stop_event,
    )
    language_code = safe_language_code(_raw_code)
    target_path = request.language_dir / f"{language_code}.json"
    write_language_file(
        target_path,
        language_code=language_code,
        language_name=language_name,
        translations=translations,
        stop_event=stop_event,
    )
    return LanguageImportResult(
        request.request_id,
        language_code,
        language_name,
        target_path,
        tuple(sorted(translations.items())),
    )


__all__ = [
    "LanguageExportRequest",
    "LanguageExportResult",
    "LanguageImportRequest",
    "LanguageImportResult",
    "run_language_export",
    "run_language_import",
]
