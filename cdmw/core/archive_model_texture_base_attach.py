from __future__ import annotations

import threading
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.models import (
    ArchiveEntry,
    ModelPreviewData,
    ModelPreviewMesh,
    PreviewMaterialTextureInput,
)
from cdmw.core.common import RunCancelled, raise_if_cancelled
from cdmw.core.archive_model_references import _normalize_model_texture_reference

from cdmw.core.archive_model_texture_resolution import _resolve_model_texture_archive_entry
from cdmw.core.archive_model_texture_semantics import _append_model_preview_material_input
from cdmw.core.archive_model_texture_sidecar_rules import _model_preview_base_texture_quality

def _public_preview_path(*args, **kwargs):
    from cdmw.core import archive_model_textures as public
    return public._ensure_archive_model_texture_preview_path(*args, **kwargs)

def _remember_name(names: List[str], value: str) -> None:
    if value not in names and len(names) < 5:
        names.append(value)


def _attach_base_texture_to_mesh(
    mesh: ModelPreviewMesh,
    *,
    source_entry: ArchiveEntry,
    preview_cache: Dict[str, str],
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]],
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]],
    override_existing_base: bool,
    prefer_material_name_for_base: bool,
    stop_event: Optional[threading.Event],
) -> Tuple[str, str]:
    existing_preview_path = str(getattr(mesh, "preview_texture_path", "") or "").strip()
    texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
    material_name = str(getattr(mesh, "material_name", "") or "").strip()
    if override_existing_base:
        existing_source = str(getattr(mesh, "preview_base_texture_source", "") or "").strip().lower()
        material_lookup = prefer_material_name_for_base and bool(material_name) and not material_name.lower().endswith(".dds")
        embedded_lookup = material_lookup or (prefer_material_name_for_base and texture_name.lower().endswith(".dds"))
        if existing_source in {"pami", "pac_xml", "sidecar", "pamlod_xml", "pam_xml"} and not embedded_lookup:
            return "skip", ""
    if existing_preview_path and not override_existing_base:
        return "sidecar", ""
    lookup_texture = "" if override_existing_base and prefer_material_name_for_base and material_name and not material_name.lower().endswith(".dds") else texture_name
    lookup_material = material_name
    attempts = [(lookup_texture, lookup_material)]
    if override_existing_base and prefer_material_name_for_base and not lookup_texture and texture_name:
        attempts.append((texture_name, material_name))
    label = lookup_texture or lookup_material or texture_name
    if not label:
        return "skip", ""
    texture_entry: Optional[ArchiveEntry] = None
    resolution_status = "missing"
    for attempt_texture, attempt_material in attempts:
        texture_entry, resolution_status = _resolve_model_texture_archive_entry(
            source_entry,
            attempt_texture,
            attempt_material,
            texture_entries_by_normalized_path,
            texture_entries_by_basename,
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
        )
        if texture_entry is not None:
            break
    if texture_entry is None:
        return ("technical" if resolution_status == "technical_only" else "missing"), label
    cache_key = _normalize_model_texture_reference(texture_entry.path)
    preview_path = preview_cache.get(cache_key, "")
    if not preview_path:
        try:
            preview_path = _public_preview_path(texture_entry, stop_event=stop_event)
            preview_cache[cache_key] = preview_path
        except RunCancelled:
            raise
        except Exception:
            return "failure", label
    if str(getattr(mesh, "preview_texture_path", "") or "").strip() != preview_path:
        mesh.preview_texture_path = preview_path
        mesh.preview_texture_image = None
    mesh.preview_base_texture_quality = _model_preview_base_texture_quality(texture_entry.path)
    if str(getattr(source_entry, "extension", "") or "").lower() == ".pac":
        mesh.preview_texture_flip_vertical = False
    current_texture = str(getattr(mesh, "texture_name", "") or "").strip()
    if override_existing_base or not current_texture or not current_texture.lower().endswith(".dds"):
        mesh.texture_name = texture_entry.path
    if not str(getattr(mesh, "preview_base_texture_source", "") or "").strip():
        mesh.preview_base_texture_source = "embedded mesh"
    _append_model_preview_material_input(
        mesh,
        PreviewMaterialTextureInput(
            slot_kind="base",
            source_texture_path=texture_entry.path,
            source_dds_path=texture_entry.path,
            texture_name=PurePosixPath(texture_entry.path.replace("\\", "/")).name,
            preview_texture_path=preview_path,
            semantic_type="color",
            semantic_subtype="albedo",
            material_name=str(getattr(mesh, "material_name", "") or "").strip(),
            confidence=str(getattr(mesh, "preview_base_texture_source", "") or "embedded mesh").strip(),
            visualized=True,
        ),
    )
    changed = existing_preview_path and override_existing_base and _normalize_model_texture_reference(existing_preview_path) != _normalize_model_texture_reference(preview_path)
    return ("override" if changed else "resolved"), ""


def _base_texture_attachment_report(counts: Dict[str, int], names: Dict[str, List[str]], *, override: bool) -> List[str]:
    info: List[str] = []
    resolved = counts["resolved"] + counts["override"] + counts["sidecar"]
    if counts["override"]:
        info.append(f"Corrected {counts['override']:,} mesh base texture preview(s) so embedded material names override sidecar overlay/detail fallback.")
    elif resolved and not override:
        sidecar = counts["sidecar"]
        if sidecar >= resolved:
            info.append(f"Resolved {resolved:,} mesh texture preview(s) for textured shading and export using sidecar-aware material bindings.")
        elif sidecar:
            info.append(f"Resolved {resolved:,} mesh texture preview(s) for textured shading and export ({sidecar:,} via sidecar-aware bindings, remaining matches via semantic base-color fallback).")
        else:
            info.append(f"Resolved {resolved:,} mesh texture preview(s) for textured shading and export using semantic base-color selection only.")
    if counts["missing"] and not override:
        suffix = f" Examples: {', '.join(names['missing'])}." if names["missing"] else ""
        info.append(f"{counts['missing']:,} embedded material base name(s) had no direct visible DDS match; sidecar layer bindings may still provide a preview fallback.{suffix}")
    if counts["technical"] and not override:
        suffix = f" Examples: {', '.join(names['technical'])}." if names["technical"] else ""
        info.append(f"{counts['technical']:,} mesh texture reference(s) were skipped because only technical DDS matches were found.{suffix}")
    if counts["failure"]:
        suffix = f" Examples: {', '.join(names['failure'])}." if names["failure"] else ""
        info.append(f"{counts['failure']:,} resolved texture(s) failed during DDS-to-PNG preview generation.{suffix}")
    return info


def _attach_model_texture_preview_paths(
    source_entry: ArchiveEntry,
    model_preview: Optional[ModelPreviewData],
    *,
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
    override_existing_base: bool = False,
    prefer_material_name_for_base: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> List[str]:
    if model_preview is None or not model_preview.meshes:
        return []
    counts = {key: 0 for key in ("resolved", "sidecar", "override", "missing", "technical", "failure", "skip")}
    names = {key: [] for key in ("missing", "technical", "failure")}
    preview_cache: Dict[str, str] = {}
    for mesh in model_preview.meshes:
        raise_if_cancelled(stop_event)
        status, label = _attach_base_texture_to_mesh(
            mesh,
            source_entry=source_entry,
            preview_cache=preview_cache,
            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
            texture_entries_by_basename=texture_entries_by_basename,
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
            override_existing_base=override_existing_base,
            prefer_material_name_for_base=prefer_material_name_for_base,
            stop_event=stop_event,
        )
        counts[status] += 1
        if label and status in names:
            _remember_name(names[status], label)
    return _base_texture_attachment_report(counts, names, override=override_existing_base)
