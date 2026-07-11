from __future__ import annotations

from pathlib import PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    ModelPreviewData,
    ModelPreviewMesh,
    RelationConfidence,
)
from cdmw.core.archive_format import _is_material_sidecar_extension
from cdmw.core.archive_model_references import (
    _ArchiveModelSidecarTextureBinding,
    _archive_texture_family_mismatch_reason,
    _build_archive_relation_metadata,
    _find_archive_model_related_entries,
    _humanize_model_texture_hint,
    _model_texture_hint_priority,
    _normalize_model_texture_reference,
)
from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup

from cdmw.core.archive_model_texture_resolution import _resolve_model_texture_archive_entry
from cdmw.core.archive_model_texture_semantics import (
    _has_explicit_model_texture_reference,
    _iter_parsed_model_submeshes,
    _resolve_model_texture_semantics,
)

def _model_preview_texture_slot_label(*values: object) -> str:
    for value in values:
        text = str(value or "").replace("\\", "/").strip()
        if not text:
            continue
        name = PurePosixPath(text).name
        return name or text
    return "missing"

def _model_preview_material_decode_label(mesh: ModelPreviewMesh) -> str:
    texture_type = str(getattr(mesh, "preview_material_texture_type", "") or "material").strip().lower() or "material"
    subtype = str(getattr(mesh, "preview_material_texture_subtype", "") or "unknown").strip().lower() or "unknown"
    channels = tuple(
        str(channel or "").strip().lower()
        for channel in tuple(getattr(mesh, "preview_material_texture_packed_channels", ()) or ())
        if str(channel or "").strip()
    )
    channel_text = ",".join(channels) if channels else "no-packed-channels"
    return f"{texture_type}/{subtype}/{channel_text}"

def _build_model_preview_texture_slot_detail_text(
    model_preview: Optional[ModelPreviewData],
    *,
    max_meshes: int = 24,
) -> str:
    if model_preview is None:
        return ""
    meshes = tuple(getattr(model_preview, "meshes", ()) or ())
    if not meshes:
        return ""
    lines = ["Texture Slot Mapping"]
    for mesh_index, mesh in enumerate(meshes[: max(0, int(max_meshes))]):
        if not isinstance(mesh, ModelPreviewMesh):
            continue
        material_label = str(getattr(mesh, "material_name", "") or "").strip() or f"mesh[{mesh_index}]"
        base_dds = _model_preview_texture_slot_label(
            getattr(mesh, "preview_texture_dds_path", ""),
            getattr(mesh, "texture_name", ""),
        )
        normal_dds = _model_preview_texture_slot_label(
            getattr(mesh, "preview_normal_texture_dds_path", ""),
            getattr(mesh, "preview_normal_texture_name", ""),
        )
        material_dds = _model_preview_texture_slot_label(
            getattr(mesh, "preview_material_texture_dds_path", ""),
            getattr(mesh, "preview_material_texture_name", ""),
        )
        height_dds = _model_preview_texture_slot_label(
            getattr(mesh, "preview_height_texture_dds_path", ""),
            getattr(mesh, "preview_height_texture_name", ""),
        )
        lines.append(
            f"- {material_label} -> base DDS={base_dds} -> normal DDS={normal_dds} "
            f"-> material DDS={material_dds} -> height DDS={height_dds} "
            f"-> decoded channels={_model_preview_material_decode_label(mesh)}"
        )
    if len(meshes) > max_meshes:
        lines.append(f"- ... {len(meshes) - max_meshes:,} additional mesh material slot(s) omitted.")
    return "\n".join(lines)

def _describe_model_texture_semantic_label(
    texture_path: str,
    *,
    semantic_hint: str = "",
    sidecar_texts: Sequence[str] = (),
) -> str:
    hint_label = _humanize_model_texture_hint(semantic_hint)
    if hint_label:
        return hint_label
    texture_type_raw, subtype_raw, _confidence = _resolve_model_texture_semantics(
        texture_path,
        sidecar_texts=sidecar_texts,
    )
    texture_type = str(texture_type_raw or "").strip().replace("_", " ")
    subtype = str(subtype_raw or "").strip().replace("_", " ")
    if not texture_type or texture_type.lower() == "unknown":
        return hint_label
    hint_priority = _model_texture_hint_priority(semantic_hint)
    if hint_label and hint_priority is not None and hint_priority[0] >= 5 and texture_type.lower() not in {"color", "ui", "emissive"}:
        return hint_label
    if subtype and subtype.lower() not in {"unknown", texture_type.lower()}:
        return f"{texture_type.title()} / {subtype.title()}"
    return texture_type.title()

def _describe_model_related_file_label(entry: ArchiveEntry) -> str:
    extension = str(entry.extension or "").strip().lower()
    path = str(entry.path or "").replace("\\", "/").lower()
    basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
    if extension == ".pam":
        return "Companion PAM"
    if extension == ".pamlod":
        return "Companion PAMLOD"
    if extension == ".pac":
        return "Companion PAC"
    if extension == ".pab":
        return "Companion PAB"
    if extension == ".pabc":
        return "Skeleton Variation"
    if extension == ".papr":
        return "Animation Constraint"
    if "prefabdata" in basename or extension == ".prefabdata_xml":
        return "Prefab Metadata"
    if extension == ".pami":
        return "Material Variant Sidecar"
    if _is_material_sidecar_extension(extension, basename):
        return "Material Sidecar"
    if extension == ".xml":
        return "Companion XML"
    if extension in {".hkx", ".hkt"}:
        label = extension.lstrip(".").upper()
        if any(token in path for token in ("meshphysics", "havokphysics", "ragdoll", "physics")):
            return f"Physics {label}"
        return f"Companion {label}"
    if extension == ".meshinfo":
        return "Companion MeshInfo"
    if extension == ".pappt":
        return "Part Prefab Metadata"
    if extension == ".pamhc":
        return "Model Property Header"
    if extension == ".paa":
        return "Companion PAA"
    if extension == ".paa_metabin":
        return "Animation Metadata"
    if extension == ".motionblending":
        return "Motion Blending"
    if extension in {".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage"}:
        return "Animation Metadata"
    if extension == ".seqmt":
        return "Sequence Texture Metadata"
    if extension in {".pae", ".paem"}:
        return "Companion Effect"
    if extension:
        return f"Companion {extension.lstrip('.').upper()}"
    return "Related File"

def _merge_model_reference_semantic_label(
    existing_label: str,
    new_label: str,
    *,
    existing_hint: str = "",
    new_hint: str = "",
) -> str:
    current = str(existing_label or "").strip()
    incoming = str(new_label or "").strip()
    if not current:
        return incoming
    if not incoming or incoming == current:
        return current
    if not str(existing_hint or "").strip() and str(new_hint or "").strip():
        return incoming
    if str(existing_hint or "").strip() and not str(new_hint or "").strip():
        return current
    parts = [part.strip() for part in current.split(" | ") if part.strip()]
    if incoming not in parts:
        parts.append(incoming)
    return " | ".join(parts)

def _model_reference_status_rank(status: str) -> int:
    normalized = str(status or "").strip().lower()
    if normalized == "resolved":
        return 3
    if normalized == "technical_only":
        return 2
    return 1

def _texture_reference_relation_metadata(
    source_entry: ArchiveEntry,
    reference_name: str,
    resolved_entry: Optional[ArchiveEntry],
    *,
    semantic_hint: str = "",
) -> Tuple[str, str]:
    if not isinstance(resolved_entry, ArchiveEntry):
        return (
            RelationConfidence.AUTHORITATIVE.value if semantic_hint else RelationConfidence.DERIVED_SAME_STEM.value,
            "Sidecar texture binding" if semantic_hint else "Resolved texture family",
        )
    normalized_reference = normalize_texture_reference_for_sidecar_lookup(reference_name)
    normalized_resolved = normalize_texture_reference_for_sidecar_lookup(resolved_entry.path)
    mismatch_reason = _archive_texture_family_mismatch_reason(source_entry, resolved_entry) if semantic_hint else ""
    if normalized_reference and normalized_reference == normalized_resolved:
        if mismatch_reason:
            return RelationConfidence.EXACT_PATH.value, f"Exact sidecar path; {mismatch_reason}"
        return RelationConfidence.EXACT_PATH.value, "Exact archive path"
    if (
        normalized_reference
        and normalized_resolved
        and PurePosixPath(normalized_reference).name == PurePosixPath(normalized_resolved).name
        and source_entry.pamt_path.parent != resolved_entry.pamt_path.parent
    ):
        return RelationConfidence.CROSS_PACKAGE.value, "Cross-package texture reference"
    if normalized_reference and normalized_resolved and normalized_reference.lstrip("/") == normalized_resolved.lstrip("/"):
        if mismatch_reason:
            return RelationConfidence.PATH_NORMALIZED.value, f"Path-normalized sidecar path; {mismatch_reason}"
        return RelationConfidence.PATH_NORMALIZED.value, "Path-normalized texture reference"
    if semantic_hint:
        if mismatch_reason:
            return RelationConfidence.AUTHORITATIVE.value, f"Sidecar texture binding; {mismatch_reason}"
        return RelationConfidence.AUTHORITATIVE.value, "Sidecar texture binding"
    return RelationConfidence.DERIVED_SAME_STEM.value, "Resolved texture family"

def _add_related_model_references(
    source_entry: ArchiveEntry,
    related_entries: Sequence[ArchiveEntry],
    references: Dict[Tuple[str, ...], ArchiveModelTextureReference],
    ordered_keys: List[Tuple[str, ...]],
) -> None:
    for related_entry in related_entries:
        key = ("sidecar", _normalize_model_texture_reference(related_entry.path))
        if key in references:
            continue
        kind, group, confidence, reason = _build_archive_relation_metadata(source_entry, resolved_entry=related_entry)
        references[key] = ArchiveModelTextureReference(
            reference_name=PurePosixPath(related_entry.path.replace("\\", "/")).name,
            semantic_label=_describe_model_related_file_label(related_entry),
            resolution_status="resolved",
            resolved_archive_path=related_entry.path,
            resolved_package_label=related_entry.package_label,
            resolved_entry=related_entry,
            usage_count=1,
            reference_kind=kind,
            relation_group=group,
            relation_reason=reason,
            relation_confidence=confidence,
        )
        ordered_keys.append(key)


def _collect_model_reference_candidates(
    preview_meshes: Sequence[object],
    parsed_submeshes: Sequence[object],
    binary_references: Sequence[str],
    sidecar_references: Sequence[_ArchiveModelSidecarTextureBinding],
) -> List[Tuple[str, str, str, str, Optional[object]]]:
    candidates: List[Tuple[str, str, str, str, Optional[object]]] = []
    seen: set[Tuple[str, str, str]] = set()
    for binding in sidecar_references:
        texture = str(binding.texture_path or "").strip()
        material = str(getattr(binding, "part_name", "") or getattr(binding, "material_name", "") or binding.submesh_name or binding.parameter_name or "").strip()
        hint = str(binding.parameter_name or "").strip()
        key = (_normalize_model_texture_reference(texture), _normalize_model_texture_reference(material), hint.lower())
        if texture and key not in seen:
            seen.add(key)
            candidates.append((texture, material, "", hint, binding))
    for mesh in preview_meshes:
        texture = str(getattr(mesh, "texture_name", "") or "").strip()
        material = str(getattr(mesh, "material_name", "") or "").strip()
        seen.add((_normalize_model_texture_reference(texture), _normalize_model_texture_reference(material), ""))
        candidates.append((texture, material, str(getattr(mesh, "preview_texture_path", "") or "").strip(), "", None))
    for submesh in parsed_submeshes:
        texture = str(getattr(submesh, "texture", "") or "").strip()
        material = str(getattr(submesh, "material", "") or "").strip()
        key = (_normalize_model_texture_reference(texture), _normalize_model_texture_reference(material), "")
        if key not in seen:
            seen.add(key)
            candidates.append((texture, material, "", "", None))
    for raw_reference in binary_references:
        texture = str(raw_reference or "").strip()
        key = (_normalize_model_texture_reference(texture), "", "")
        if texture and key not in seen:
            seen.add(key)
            candidates.append((texture, "", "", "", None))
    return candidates


def _reference_sidecar_texts(
    path: str,
    by_path: Optional[Dict[str, Tuple[str, ...]]],
    by_basename: Optional[Dict[str, Tuple[str, ...]]],
) -> Tuple[str, ...]:
    normalized = normalize_texture_reference_for_sidecar_lookup(path)
    texts = tuple(by_path.get(normalized, ())) if by_path is not None and normalized else ()
    if not texts and by_basename is not None:
        basename = PurePosixPath(path.replace("\\", "/")).name.lower()
        texts = tuple(by_basename.get(basename, ())) if basename else ()
    return texts


def _merge_model_texture_reference(
    existing: ArchiveModelTextureReference,
    candidate: ArchiveModelTextureReference,
) -> None:
    existing.usage_count += 1
    for field_name in (
        "material_name", "preview_texture_path", "sidecar_kind", "linked_mesh_path",
        "part_name", "shader_family", "texture_role", "visualization_state",
    ):
        value = getattr(candidate, field_name)
        if value and not getattr(existing, field_name):
            setattr(existing, field_name, value)
    candidate_rank = _model_reference_status_rank(candidate.resolution_status)
    existing_rank = _model_reference_status_rank(existing.resolution_status)
    if candidate.resolved_entry is not None and (existing.resolved_entry is None or candidate_rank > existing_rank):
        existing.resolved_entry = candidate.resolved_entry
        existing.resolved_archive_path = candidate.resolved_archive_path
        existing.resolved_package_label = candidate.resolved_package_label
        existing.resolution_status = candidate.resolution_status
    elif candidate_rank > existing_rank:
        existing.resolution_status = candidate.resolution_status
    if candidate.semantic_label:
        existing.semantic_label = _merge_model_reference_semantic_label(
            existing.semantic_label,
            candidate.semantic_label,
            existing_hint=existing.semantic_hint,
            new_hint=candidate.semantic_hint,
        )
    if candidate.semantic_hint and candidate.semantic_hint != existing.semantic_hint:
        existing.semantic_hint = " | ".join(part for part in (existing.semantic_hint.strip(), candidate.semantic_hint.strip()) if part)
        if not existing.sidecar_parameter_name:
            existing.sidecar_parameter_name = candidate.semantic_hint
    if candidate.sidecar_texts:
        merged = list(existing.sidecar_texts)
        merged.extend(text for text in candidate.sidecar_texts if text not in merged)
        existing.sidecar_texts = tuple(merged)


def _upsert_model_texture_reference(
    source_entry: ArchiveEntry,
    candidate: Tuple[str, str, str, str, Optional[object]],
    references: Dict[Tuple[str, ...], ArchiveModelTextureReference],
    ordered_keys: List[Tuple[str, ...]],
    *,
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]],
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]],
) -> None:
    texture_name, material_name, preview_path, semantic_hint, binding = candidate
    reference_name = texture_name or material_name
    if not reference_name:
        return
    texture_entry, status = _resolve_model_texture_archive_entry(
        source_entry,
        texture_name,
        material_name,
        texture_entries_by_normalized_path,
        texture_entries_by_basename,
        semantic_hint=semantic_hint,
        expand_family_candidates=not _has_explicit_model_texture_reference(texture_name, material_name),
        allow_technical_match=True,
        sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
        sidecar_texts_by_basename=sidecar_texts_by_basename,
    )
    resolved_path = texture_entry.path if texture_entry is not None else ""
    key_value = _normalize_model_texture_reference(resolved_path or reference_name)
    key = (
        ("texture", key_value, _normalize_model_texture_reference(material_name), semantic_hint.strip().lower(), str(getattr(binding, "sidecar_kind", "") or "").strip().lower())
        if binding is not None else ("texture", key_value)
    )
    texts = _reference_sidecar_texts(
        resolved_path or reference_name,
        sidecar_texts_by_normalized_path,
        sidecar_texts_by_basename,
    )
    confidence, reason = _texture_reference_relation_metadata(source_entry, reference_name, texture_entry, semantic_hint=semantic_hint)
    item = ArchiveModelTextureReference(
        reference_name=reference_name,
        material_name=material_name,
        semantic_label=_describe_model_texture_semantic_label(resolved_path or reference_name, semantic_hint=semantic_hint, sidecar_texts=texts),
        semantic_hint=semantic_hint,
        sidecar_parameter_name=semantic_hint,
        sidecar_kind=str(getattr(binding, "sidecar_kind", "") or "").strip(),
        linked_mesh_path=str(getattr(binding, "linked_mesh_path", "") or "").strip(),
        part_name=str(getattr(binding, "part_name", "") or "").strip(),
        shader_family=str(getattr(binding, "shader_family", "") or "").strip(),
        texture_role=str(getattr(binding, "texture_role", "") or "").strip(),
        visualization_state=str(getattr(binding, "visualization_state", "") or "").strip(),
        sidecar_texts=texts,
        resolution_status=status,
        resolved_archive_path=resolved_path,
        resolved_package_label=texture_entry.package_label if texture_entry is not None else "",
        resolved_entry=texture_entry,
        preview_texture_path=preview_path,
        usage_count=1,
        reference_kind="texture",
        relation_group="Textures",
        relation_reason=reason,
        relation_confidence=confidence,
    )
    if key in references:
        _merge_model_texture_reference(references[key], item)
    else:
        references[key] = item
        ordered_keys.append(key)


def build_archive_model_texture_references(
    source_entry: ArchiveEntry,
    model_preview: Optional[ModelPreviewData],
    *,
    parsed_mesh: Optional[object] = None,
    binary_texture_references: Sequence[str] = (),
    sidecar_texture_references: Sequence[_ArchiveModelSidecarTextureBinding] = (),
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
) -> List[ArchiveModelTextureReference]:
    preview_meshes = list(getattr(model_preview, "meshes", ()) or [])
    parsed_submeshes = _iter_parsed_model_submeshes(parsed_mesh)
    related = _find_archive_model_related_entries(source_entry, texture_entries_by_basename) if texture_entries_by_basename is not None else ()
    if not any((preview_meshes, parsed_submeshes, binary_texture_references, sidecar_texture_references, related)):
        return []
    references: Dict[Tuple[str, ...], ArchiveModelTextureReference] = {}
    ordered_keys: List[Tuple[str, ...]] = []
    _add_related_model_references(source_entry, related, references, ordered_keys)
    candidates = _collect_model_reference_candidates(preview_meshes, parsed_submeshes, binary_texture_references, sidecar_texture_references)
    for candidate in candidates:
        _upsert_model_texture_reference(
            source_entry,
            candidate,
            references,
            ordered_keys,
            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
            texture_entries_by_basename=texture_entries_by_basename,
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
        )
    return [references[key] for key in ordered_keys]
