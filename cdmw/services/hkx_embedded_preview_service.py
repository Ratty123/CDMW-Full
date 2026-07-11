"""Cancellable archive/model preparation for the embedded HKX preview."""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from cdmw.core.archive import build_archive_preview_result
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry, ArchiveEntryIdentity, ArchivePreviewResult, ModelPreviewData
from cdmw.rendering.model_preview_prepare import prepare_model_preview


@dataclass(frozen=True, slots=True)
class HkxEmbeddedPreviewRequest:
    entry_key: ArchiveEntryIdentity
    model_entry: ArchiveEntry
    companion_entry: ArchiveEntry | None
    texconv_path: Path | None
    texture_entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]]
    texture_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]]
    sidecar_entries_by_texture_path: Mapping[str, Sequence[ArchiveEntry]]
    sidecar_entries_by_texture_basename: Mapping[str, Sequence[ArchiveEntry]]
    visible_texture_mode: str
    support_texture_slots: tuple[str, ...]


def build_hkx_embedded_preview(
    request: HkxEmbeddedPreviewRequest,
    *,
    stop_event: threading.Event | None = None,
) -> tuple[ArchiveEntryIdentity, str, ArchivePreviewResult]:
    raise_if_cancelled(stop_event, "Embedded HKX preview stopped by user.")
    texconv_path = request.texconv_path
    if texconv_path is not None and not texconv_path.is_file():
        texconv_path = None
    preview_result = build_archive_preview_result(
        texconv_path,
        request.model_entry,
        companion_entry=request.companion_entry,
        texture_entries_by_normalized_path=request.texture_entries_by_normalized_path,
        texture_entries_by_basename=request.texture_entries_by_basename,
        sidecar_entries_by_texture_path=request.sidecar_entries_by_texture_path,
        sidecar_entries_by_texture_basename=request.sidecar_entries_by_texture_basename,
        include_loose_preview_assets=False,
        visible_texture_mode=request.visible_texture_mode,
        support_texture_slots=request.support_texture_slots,
        stop_event=stop_event,
    )
    preview_model = preview_result.preview_model
    if isinstance(preview_model, ModelPreviewData):
        prepared_model, prepared_preview_model = prepare_model_preview(preview_model, stop_event=stop_event)
        preview_result = dataclasses.replace(
            preview_result,
            preview_model=prepared_model,
            prepared_preview_model=prepared_preview_model,
        )
    raise_if_cancelled(stop_event, "Embedded HKX preview stopped by user.")
    return request.entry_key, request.model_entry.path, preview_result


__all__ = ["HkxEmbeddedPreviewRequest", "build_hkx_embedded_preview"]
