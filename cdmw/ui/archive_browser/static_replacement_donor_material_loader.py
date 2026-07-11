"""Cancellable donor-material archive loading for the static-replacement dialog."""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cdmw.domain.archives.format import try_decode_text_like_archive_data
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.archive_workflow_service import _extract_archive_model_sidecar_texture_references
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.ui.archive_browser.static_replacement_donor_material_state import (
    donor_bindings_from_sidecar_profiles,
)


@dataclass(frozen=True, slots=True)
class DonorMaterialSourceLoadResult:
    bindings: tuple[object, ...]
    sidecar_texts: tuple[tuple[str, str], ...]
    bindings_from_profile: bool


def load_donor_material_source(
    donor_entry: ArchiveEntry,
    sidecar_entries: Sequence[ArchiveEntry],
    archive_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
    *,
    stop_event: threading.Event | None = None,
) -> DonorMaterialSourceLoadResult:
    """Read and parse donor sidecars off the UI thread."""

    bindings, _paths, _texts_by_path, _texts_by_basename = (
        _extract_archive_model_sidecar_texture_references(
            donor_entry,
            archive_entries_by_basename=archive_entries_by_basename,
            stop_event=stop_event,
        )
    )
    sidecar_texts: dict[str, str] = {}
    for sidecar_entry in sidecar_entries:
        raise_if_cancelled(stop_event, "Donor material loading cancelled.")
        try:
            sidecar_data, _decompressed, _note = read_archive_entry_data(
                sidecar_entry,
                stop_event=stop_event,
            )
            sidecar_text = try_decode_text_like_archive_data(sidecar_data) or ""
        except RunCancelled:
            raise
        except Exception:
            continue
        if sidecar_text.strip():
            sidecar_texts[sidecar_entry.path.replace("\\", "/")] = sidecar_text

    bindings_from_profile = False
    if not bindings:
        bindings = donor_bindings_from_sidecar_profiles(sidecar_texts)
        bindings_from_profile = bool(bindings)
    raise_if_cancelled(stop_event, "Donor material loading cancelled.")
    return DonorMaterialSourceLoadResult(
        bindings=tuple(bindings or ()),
        sidecar_texts=tuple(sidecar_texts.items()),
        bindings_from_profile=bindings_from_profile,
    )


__all__ = ["DonorMaterialSourceLoadResult", "load_donor_material_source"]
