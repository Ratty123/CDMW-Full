"""Cancellable atomic export for edited HKX XML documents."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from cdmw.core.atomic_file import atomic_text_writer
from cdmw.domain.cancellation import raise_if_cancelled


_WRITE_CHUNK_CHARS = 256 * 1024


@dataclass(frozen=True, slots=True)
class HkxXmlExportRequest:
    request_id: int
    output_path: Path
    document_text: str


@dataclass(frozen=True, slots=True)
class HkxXmlExportResult:
    request_id: int
    output_path: Path


def export_hkx_xml(
    request: HkxXmlExportRequest,
    *,
    stop_event: threading.Event | None = None,
) -> HkxXmlExportResult:
    """Write a complete document without publishing partial or cancelled output."""

    raise_if_cancelled(stop_event, "HKX XML export stopped by user.")
    with atomic_text_writer(request.output_path, encoding="utf-8") as handle:
        for offset in range(0, len(request.document_text), _WRITE_CHUNK_CHARS):
            raise_if_cancelled(stop_event, "HKX XML export stopped by user.")
            handle.write(request.document_text[offset : offset + _WRITE_CHUNK_CHARS])
        raise_if_cancelled(stop_event, "HKX XML export stopped by user.")
    return HkxXmlExportResult(request.request_id, request.output_path)


__all__ = [
    "HkxXmlExportRequest",
    "HkxXmlExportResult",
    "export_hkx_xml",
]
