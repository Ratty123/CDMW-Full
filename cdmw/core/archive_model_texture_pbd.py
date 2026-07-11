from __future__ import annotations

import threading
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.models import (
    ArchiveEntry,
    ModelPreviewData,
)
from cdmw.core.common import RunCancelled, raise_if_cancelled
from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_model_references import _find_archive_model_sidecar_entries
from cdmw.core.pbd_cloth import PbdConfigMaterial, build_cloth_preview_from_sidecars, collect_pbd_sidecar_hints

def ensure_archive_preview_source(*args, **kwargs):
    from cdmw.core.archive_media_preview import ensure_archive_preview_source as owner

    return owner(*args, **kwargs)

def try_decode_text_like_archive_data(*args, **kwargs):
    from cdmw.core.archive_binary_preview import try_decode_text_like_archive_data as owner

    return owner(*args, **kwargs)

def _read_archive_text_entry(
    entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> str:
    data, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
    return try_decode_text_like_archive_data(data) or ""

def _collect_archive_model_pbd_sidecar_texts(
    source_entry: ArchiveEntry,
    *,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Tuple[str, str], ...]:
    if archive_entries_by_basename is None:
        return ()
    texts: List[Tuple[str, str]] = []
    for sidecar_entry in _find_archive_model_sidecar_entries(source_entry, archive_entries_by_basename):
        raise_if_cancelled(stop_event)
        try:
            text = _read_archive_text_entry(sidecar_entry, stop_event=stop_event)
        except RunCancelled:
            raise
        except Exception:
            continue
        if "_pbdSimulationMaterialName" not in text and "pbdSimulationMaterialName" not in text:
            continue
        texts.append((sidecar_entry.path, text))
    return tuple(texts)

def _archive_entry_by_preferred_suffix(
    entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    basename: str,
    suffixes: Sequence[str],
) -> Optional[ArchiveEntry]:
    if entries_by_basename is None:
        return None
    candidates = tuple(entries_by_basename.get(str(basename or "").strip().lower(), ()) or ())
    if not candidates:
        return None
    normalized_suffixes = tuple(str(suffix or "").replace("\\", "/").strip().lower() for suffix in suffixes if str(suffix or "").strip())
    scored: List[Tuple[int, ArchiveEntry]] = []
    for candidate in candidates:
        path = str(getattr(candidate, "path", "") or "").replace("\\", "/").lower()
        score = 0
        for index, suffix in enumerate(normalized_suffixes):
            if suffix and path.endswith(suffix):
                score = max(score, 100 - index)
        if "/character/descriptors/pbd/" in path:
            score += 20
        scored.append((score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored else None

def _read_archive_pbd_config_text(
    entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    *,
    stop_event: Optional[threading.Event] = None,
) -> str:
    entry = _archive_entry_by_preferred_suffix(
        entries_by_basename,
        "pbdconfig.xml",
        ("character/descriptors/pbd/pbdconfig.xml", "descriptors/pbd/pbdconfig.xml", "pbdconfig.xml"),
    )
    if entry is None:
        return ""
    try:
        return _read_archive_text_entry(entry, stop_event=stop_event)
    except RunCancelled:
        raise
    except Exception:
        return ""

def _read_archive_pbd_material_text(
    config_material: PbdConfigMaterial,
    entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[str, str]:
    filename = str(getattr(config_material, "filename", "") or "").replace("\\", "/").strip()
    basename = PurePosixPath(filename).name.lower()
    if not basename:
        return "", ""
    normalized_filename = filename.lower()
    entry = _archive_entry_by_preferred_suffix(
        entries_by_basename,
        basename,
        (
            f"character/descriptors/pbd/{normalized_filename}",
            f"descriptors/pbd/{normalized_filename}",
            normalized_filename,
            basename,
        ),
    )
    if entry is None:
        return filename, ""
    try:
        return entry.path, _read_archive_text_entry(entry, stop_event=stop_event)
    except RunCancelled:
        raise
    except Exception:
        return getattr(entry, "path", filename), ""

def _attach_pbd_cloth_preview_to_model_preview(
    entry: ArchiveEntry,
    model_preview: Optional[ModelPreviewData],
    parsed_mesh: Optional[object],
    *,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    stop_event: Optional[threading.Event] = None,
) -> List[str]:
    if model_preview is None or parsed_mesh is None or entry.extension != ".pac":
        return []
    sidecar_texts = _collect_archive_model_pbd_sidecar_texts(
        entry,
        archive_entries_by_basename=archive_entries_by_basename,
        stop_event=stop_event,
    )
    if not sidecar_texts:
        return []
    hints = collect_pbd_sidecar_hints(sidecar_texts)
    pbd_config_text = _read_archive_pbd_config_text(archive_entries_by_basename, stop_event=stop_event)

    def resolve_material(config_material: PbdConfigMaterial) -> Tuple[str, str]:
        return _read_archive_pbd_material_text(
            config_material,
            archive_entries_by_basename,
            stop_event=stop_event,
        )

    cloth_preview = build_cloth_preview_from_sidecars(
        model_preview,
        parsed_mesh,
        sidecar_texts,
        pbd_config_text,
        resolve_material,
    )
    if cloth_preview is None or not cloth_preview.batches:
        return [
            "Detected PBD soft-physics sidecar metadata, but no recovered PAC submesh could be matched for tool-side PBD physics preview."
        ]
    model_preview.cloth_preview = cloth_preview
    return [
        (
            f"{cloth_preview.summary} Enable Tool-side PBD physics preview in Preview Settings to simulate it; "
            "this is not game-exact Havok/Pearl Abyss physics."
        )
    ]
