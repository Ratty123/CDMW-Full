from __future__ import annotations

from pathlib import PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.constants import ARCHIVE_MODEL_EXTENSIONS
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference, RelationConfidence
from cdmw.core.archive_format import _is_material_sidecar_extension
from cdmw.core.archive_model_references import (
    _ARCHIVE_ITEM_ICON_STEM_PREFIXES,
    _archive_entry_identity_signature,
    _build_archive_relation_metadata,
    _find_archive_model_related_entries,
    _humanize_model_texture_hint,
    _normalize_model_texture_reference,
    _relation_group_for_kind,
    _relation_kind_for_entry,
    _strip_archive_model_family_variant_suffix,
    iter_archive_character_equipment_root_alias_stems,
    iter_archive_equipment_model_alias_stems,
)
from cdmw.core.archive_model_textures import (
    _describe_model_related_file_label,
    _describe_model_texture_semantic_label,
)
def _score_related_reference_candidate(
    source_entry: ArchiveEntry,
    candidate: ArchiveEntry,
    *,
    reference_name: str = "",
) -> Tuple[int, int, int]:
    normalized_reference = _normalize_model_texture_reference(reference_name)
    normalized_candidate = _normalize_model_texture_reference(candidate.path)
    reference_basename = PurePosixPath(normalized_reference).name if normalized_reference else ""
    candidate_basename = PurePosixPath(normalized_candidate).name
    source_root = PurePosixPath(_normalize_model_texture_reference(source_entry.path)).parts[:1]
    candidate_root = PurePosixPath(normalized_candidate).parts[:1]
    score_value = 0
    if normalized_reference and normalized_candidate == normalized_reference:
        score_value += 20
    if reference_basename and candidate_basename == reference_basename:
        score_value += 10
    if candidate.pamt_path == source_entry.pamt_path:
        score_value += 8
    if candidate.pamt_path.parent == source_entry.pamt_path.parent:
        score_value += 5
    if source_root and candidate_root and source_root == candidate_root:
        score_value += 3
    return score_value, -len(candidate.path), 0


def _resolve_related_archive_entry(
    source_entry: ArchiveEntry,
    reference_name: str,
    *,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Optional[ArchiveEntry]:
    normalized_reference = _normalize_model_texture_reference(reference_name)
    candidates: List[ArchiveEntry] = []
    seen_paths: set[str] = set()

    if archive_entries_by_normalized_path is not None and normalized_reference:
        for candidate in archive_entries_by_normalized_path.get(normalized_reference, ()):
            normalized_candidate = _normalize_model_texture_reference(candidate.path)
            if normalized_candidate in seen_paths or normalized_candidate == _normalize_model_texture_reference(source_entry.path):
                continue
            seen_paths.add(normalized_candidate)
            candidates.append(candidate)

    reference_basename = PurePosixPath(normalized_reference or reference_name.replace("\\", "/")).name.lower()
    if archive_entries_by_basename is not None and reference_basename:
        for candidate in archive_entries_by_basename.get(reference_basename, ()):
            normalized_candidate = _normalize_model_texture_reference(candidate.path)
            if normalized_candidate in seen_paths or normalized_candidate == _normalize_model_texture_reference(source_entry.path):
                continue
            seen_paths.add(normalized_candidate)
            candidates.append(candidate)

    if not candidates:
        return None

    candidates.sort(
        key=lambda candidate: _score_related_reference_candidate(
            source_entry,
            candidate,
            reference_name=reference_name,
        ),
        reverse=True,
    )
    return candidates[0]


def _describe_generic_related_reference_label(reference_name: str, resolved_entry: Optional[ArchiveEntry] = None) -> str:
    reference_basename = PurePosixPath(
        str(getattr(resolved_entry, "path", "") or reference_name).replace("\\", "/")
    ).name.lower()
    extension = str(getattr(resolved_entry, "extension", "") or PurePosixPath(reference_name.replace("\\", "/")).suffix).strip().lower()
    if extension == ".dds":
        semantic_label = _describe_model_texture_semantic_label(reference_name)
        return semantic_label or "Texture / DDS"
    if "prefabdata" in reference_basename or extension == ".prefabdata_xml":
        return "Prefab Metadata"
    if extension == ".pami":
        return "Material Variant Sidecar"
    if _is_material_sidecar_extension(extension, reference_basename):
        return "Material Sidecar"
    if extension == ".xml":
        return "Related XML"
    if extension == ".meshinfo":
        return "Related MeshInfo"
    if extension in {".hkx", ".hkt"}:
        return f"Related {extension.lstrip('.').upper()}"
    if extension == ".pab":
        return "Related PAB"
    if extension == ".pabc":
        return "Skeleton Variation"
    if extension in {".pabv", ".pabgb", ".pabgh"}:
        return "Rig / Gameplay Variant"
    if extension == ".papr":
        return "Animation Constraint"
    if extension == ".pac":
        return "Related PAC"
    if extension == ".pam":
        return "Related PAM"
    if extension == ".pamlod":
        return "Related PAMLOD"
    if extension == ".paa":
        return "Related PAA"
    if extension == ".paa_metabin":
        return "Animation Metadata"
    if extension in {".pae", ".paem"}:
        return "Related Effect"
    if extension == ".seqmt":
        return "Sequence Texture Metadata"
    if extension == ".prefab":
        return "Prefab"
    if extension in {".levelinfo", ".palevel"}:
        return "Level Metadata"
    if extension in {".roadsector", ".road", ".nav"}:
        return "World / Navigation"
    if extension:
        return f"Related {extension.lstrip('.').upper()}"
    return "Related File"


def build_archive_related_file_references(
    source_entry: ArchiveEntry,
    *,
    explicit_reference_names: Sequence[str] = (),
    companion_entries: Sequence[ArchiveEntry] = (),
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveModelTextureReference, ...]:
    references: Dict[Tuple[str, str], ArchiveModelTextureReference] = {}
    ordered_keys: List[Tuple[str, str]] = []

    for companion_entry in companion_entries:
        normalized_path = _normalize_model_texture_reference(companion_entry.path)
        if not normalized_path:
            continue
        key = ("file", normalized_path)
        if key in references:
            continue
        relation_kind, relation_group, relation_confidence, relation_reason = _build_archive_relation_metadata(
            source_entry,
            resolved_entry=companion_entry,
            authoritative=(
                str(source_entry.extension or "").strip().lower() == ".dds"
                and _is_material_sidecar_extension(
                    str(companion_entry.extension or "").strip().lower(),
                    PurePosixPath(companion_entry.path.replace("\\", "/")).name.lower(),
                )
            ),
            authoritative_reason="Sidecar binding reference",
        )
        references[key] = ArchiveModelTextureReference(
            reference_name=PurePosixPath(companion_entry.path.replace("\\", "/")).name,
            semantic_label=_describe_model_related_file_label(companion_entry),
            resolution_status="resolved",
            resolved_archive_path=companion_entry.path,
            resolved_package_label=companion_entry.package_label,
            resolved_entry=companion_entry,
            usage_count=1,
            reference_kind=relation_kind,
            relation_group=relation_group,
            relation_reason=relation_reason,
            relation_confidence=relation_confidence,
        )
        ordered_keys.append(key)

    for raw_reference_name in explicit_reference_names:
        reference_name = str(raw_reference_name or "").strip().replace("\\", "/")
        if not reference_name:
            continue
        resolved_entry = _resolve_related_archive_entry(
            source_entry,
            reference_name,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            archive_entries_by_basename=archive_entries_by_basename,
        )
        normalized_key_value = _normalize_model_texture_reference(
            resolved_entry.path if isinstance(resolved_entry, ArchiveEntry) else reference_name
        )
        if not normalized_key_value or normalized_key_value == _normalize_model_texture_reference(source_entry.path):
            continue
        key = ("file", normalized_key_value)
        if key not in references:
            authoritative = bool(isinstance(resolved_entry, ArchiveEntry) or "/" in reference_name or "." in PurePosixPath(reference_name).name)
            relation_kind, relation_group, relation_confidence, relation_reason = _build_archive_relation_metadata(
                source_entry,
                reference_name=reference_name,
                resolved_entry=resolved_entry if isinstance(resolved_entry, ArchiveEntry) else None,
                authoritative=authoritative,
                authoritative_reason="Explicit path reference",
            )
            references[key] = ArchiveModelTextureReference(
                reference_name=reference_name,
                semantic_label=_describe_generic_related_reference_label(reference_name, resolved_entry),
                resolution_status="resolved" if isinstance(resolved_entry, ArchiveEntry) else "missing",
                resolved_archive_path=resolved_entry.path if isinstance(resolved_entry, ArchiveEntry) else "",
                resolved_package_label=resolved_entry.package_label if isinstance(resolved_entry, ArchiveEntry) else "",
                resolved_entry=resolved_entry if isinstance(resolved_entry, ArchiveEntry) else None,
                usage_count=1,
                reference_kind=relation_kind,
                relation_group=relation_group,
                relation_reason=relation_reason,
                relation_confidence=relation_confidence,
            )
            ordered_keys.append(key)
            continue
        references[key].usage_count += 1
        if reference_name and not references[key].reference_name:
            references[key].reference_name = reference_name
        if isinstance(resolved_entry, ArchiveEntry) and references[key].resolved_entry is None:
            references[key].resolved_entry = resolved_entry
            references[key].resolved_archive_path = resolved_entry.path
            references[key].resolved_package_label = resolved_entry.package_label
            references[key].resolution_status = "resolved"

    return tuple(references[key] for key in ordered_keys)


def _archive_relationship_edge_group_label(edge: object, resolved_entry: ArchiveEntry) -> str:
    relation_kind = str(getattr(edge, "relation_kind", "") or "").strip().lower()
    resolved_extension = str(resolved_entry.extension or "").lower()
    resolved_path = str(resolved_entry.path or "").replace("\\", "/").lower()
    resolved_basename = PurePosixPath(resolved_entry.path.replace("\\", "/")).name.lower()
    if relation_kind == "texture" or str(resolved_entry.extension or "").lower() == ".dds":
        return "Textures"
    if relation_kind == "material_sidecar" or _is_material_sidecar_extension(resolved_extension, resolved_basename):
        return "Material Sidecars"
    if resolved_extension == ".pamhc":
        return "Material Sidecars"
    if relation_kind in {"model", "mesh", "lod"} or str(resolved_entry.extension or "").lower() in {".pac", ".pam", ".pamlod"}:
        return "Mesh / Model"
    if relation_kind == "skeleton" or str(resolved_entry.extension or "").lower() in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh"}:
        return "Skeleton / Rig"
    if relation_kind == "physics" or (
        resolved_extension in {".hkx", ".hkt"}
        and any(token in resolved_path for token in ("meshphysics", "havokphysics", "ragdoll", "physics"))
    ):
        return "Physics / Collision"
    if relation_kind == "animation" or resolved_extension in {
        ".hkx",
        ".hkt",
        ".paa",
        ".paa_metabin",
        ".motionblending",
        ".papr",
        ".pae",
        ".paem",
        ".paseq",
        ".paseqc",
        ".paschedule",
        ".paschedulepath",
        ".pastage",
        ".seqmt",
    }:
        return "Animation / Motion"
    return "Metadata / Other"


def _archive_relationship_edge_semantic_label(edge: object, resolved_entry: ArchiveEntry) -> str:
    role = str(getattr(edge, "role", "") or "").strip()
    if role:
        return _humanize_model_texture_hint(role)
    if str(resolved_entry.extension or "").lower() == ".dds":
        return _describe_model_texture_semantic_label(resolved_entry.path)
    return _describe_model_related_file_label(resolved_entry)


def build_archive_relationship_references(
    source_entry: ArchiveEntry,
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveModelTextureReference, ...]:
    extension = str(source_entry.extension or "").strip().lower()
    basename = PurePosixPath(source_entry.path.replace("\\", "/")).name.lower()
    if not (
        extension in ARCHIVE_MODEL_EXTENSIONS
        or extension in {
            ".app_xml",
            ".prefabdata_xml",
            ".pac_xml",
            ".pam_xml",
            ".pamlod_xml",
            ".pami",
            ".prefab",
            ".pappt",
            ".pamhc",
            ".hkx",
            ".hkt",
            ".meshinfo",
            ".levelinfo",
            ".palevel",
            ".roadsector",
            ".road",
            ".nav",
            ".paa",
            ".paa_metabin",
            ".pae",
            ".paem",
            ".motionblending",
            ".paseq",
            ".paseqc",
            ".paschedule",
            ".paschedulepath",
            ".pastage",
            ".seqmt",
            ".pab",
            ".pabc",
            ".pabv",
            ".pabgb",
            ".pabgh",
        }
        or _is_material_sidecar_extension(extension, basename)
    ):
        return ()
    if archive_entries_by_normalized_path is None and archive_entries_by_basename is None:
        return ()

    try:
        from cdmw.core.archive_relationships import build_archive_relationship_plan
    except Exception:
        return ()

    try:
        relationship_plan = build_archive_relationship_plan(
            source_entry,
            (),
            path_index=archive_entries_by_normalized_path,
            basename_index=archive_entries_by_basename,
        )
    except Exception:
        return ()

    references: List[ArchiveModelTextureReference] = []
    seen: set[Tuple[object, ...]] = set()
    source_identity = _archive_entry_identity_signature(source_entry)

    def add_resolved_reference(
        resolved_entry: ArchiveEntry,
        *,
        reference_name: str = "",
        semantic_label: str = "",
        relation_kind: str = "",
        relation_group: str = "",
        relation_reason: str = "",
        relation_confidence: str = "",
        semantic_hint: str = "",
        source_table: str = "",
        source_field: str = "",
    ) -> None:
        resolved_identity = _archive_entry_identity_signature(resolved_entry)
        if not resolved_identity or resolved_identity == source_identity or resolved_identity in seen:
            return
        seen.add(resolved_identity)
        references.append(
            ArchiveModelTextureReference(
                reference_name=reference_name or PurePosixPath(resolved_entry.path.replace("\\", "/")).name,
                semantic_label=semantic_label or _describe_model_related_file_label(resolved_entry),
                resolution_status="resolved",
                resolved_archive_path=resolved_entry.path,
                resolved_package_label=resolved_entry.package_label,
                resolved_entry=resolved_entry,
                usage_count=1,
                reference_kind=relation_kind or _relation_kind_for_entry(resolved_entry),
                relation_group=relation_group or _relation_group_for_kind(relation_kind or _relation_kind_for_entry(resolved_entry)),
                relation_reason=relation_reason,
                relation_confidence=relation_confidence or RelationConfidence.DERIVED_SAME_STEM.value,
                semantic_hint=semantic_hint,
                sidecar_parameter_name=semantic_hint,
                source_table=source_table,
                source_field=source_field,
            )
        )

    direct_same_stem_extensions = {
        ".hkx",
        ".hkt",
        ".meshinfo",
        ".prefab",
        ".pappt",
        ".pamhc",
        ".paa",
        ".paa_metabin",
        ".motionblending",
        ".pae",
        ".paem",
        ".paseq",
        ".paseqc",
        ".paschedule",
        ".paschedulepath",
        ".pastage",
        ".seqmt",
        ".pab",
        ".pabc",
        ".pabv",
        ".pabgb",
        ".pabgh",
        ".levelinfo",
        ".palevel",
        ".roadsector",
        ".road",
        ".nav",
    }
    if archive_entries_by_basename is not None and (
        extension in ARCHIVE_MODEL_EXTENSIONS or extension in direct_same_stem_extensions
    ):
        for related_entry in _find_archive_model_related_entries(source_entry, archive_entries_by_basename):
            relation_kind, relation_group, relation_confidence, relation_reason = _build_archive_relation_metadata(
                source_entry,
                reference_name=related_entry.path,
                resolved_entry=related_entry,
            )
            add_resolved_reference(
                related_entry,
                semantic_label=_describe_model_related_file_label(related_entry),
                relation_kind=relation_kind,
                relation_group=relation_group,
                relation_reason=relation_reason,
                relation_confidence=relation_confidence,
                semantic_hint="same_stem_companion",
            )

    for edge in tuple(getattr(relationship_plan, "edges", ()) or ()):
        if bool(getattr(edge, "unresolved", False)):
            continue
        resolved_entry = getattr(edge, "related_entry", None)
        if not isinstance(resolved_entry, ArchiveEntry):
            continue
        add_resolved_reference(
            resolved_entry,
            semantic_label=_archive_relationship_edge_semantic_label(edge, resolved_entry),
            relation_kind=str(getattr(edge, "relation_kind", "") or _relation_kind_for_entry(resolved_entry)),
            relation_group=_archive_relationship_edge_group_label(edge, resolved_entry),
            relation_reason=str(getattr(edge, "reason", "") or "").strip(),
            relation_confidence=str(getattr(edge, "confidence", "") or RelationConfidence.DERIVED_SAME_STEM.value),
            semantic_hint=str(getattr(edge, "role", "") or "").strip(),
            source_table=str(getattr(edge, "source_table", "") or "").strip(),
            source_field=str(getattr(edge, "source_field", "") or "").strip(),
        )
    return tuple(references)


def merge_archive_reference_rows(
    *reference_groups: Sequence[ArchiveModelTextureReference],
) -> Tuple[ArchiveModelTextureReference, ...]:
    merged: List[ArchiveModelTextureReference] = []
    rows_by_key: Dict[Tuple[object, ...], ArchiveModelTextureReference] = {}

    def key_for(reference: ArchiveModelTextureReference) -> Tuple[object, ...]:
        resolved_entry = getattr(reference, "resolved_entry", None)
        if isinstance(resolved_entry, ArchiveEntry):
            return ("entry", *_archive_entry_identity_signature(resolved_entry))
        resolved_path = str(getattr(reference, "resolved_archive_path", "") or "").replace("\\", "/").strip().lower()
        if resolved_path:
            return ("path", resolved_path)
        return (
            "ref",
            str(getattr(reference, "relation_group", "") or "").strip().lower(),
            str(getattr(reference, "reference_kind", "") or "").strip().lower(),
            str(getattr(reference, "reference_name", "") or "").replace("\\", "/").strip().lower(),
        )

    for group in reference_groups:
        for reference in tuple(group or ()):
            if not isinstance(reference, ArchiveModelTextureReference):
                continue
            key = key_for(reference)
            existing = rows_by_key.get(key)
            if existing is None:
                rows_by_key[key] = reference
                merged.append(reference)
                continue
            existing.usage_count = max(1, int(existing.usage_count or 0)) + max(1, int(reference.usage_count or 0))
            if not existing.semantic_label and reference.semantic_label:
                existing.semantic_label = reference.semantic_label
            if reference.semantic_hint and not existing.semantic_hint:
                existing.semantic_hint = reference.semantic_hint
                existing.sidecar_parameter_name = existing.sidecar_parameter_name or reference.sidecar_parameter_name
                if reference.semantic_label:
                    existing.semantic_label = reference.semantic_label
            if not existing.relation_reason and reference.relation_reason:
                existing.relation_reason = reference.relation_reason
            if not existing.relation_confidence and reference.relation_confidence:
                existing.relation_confidence = reference.relation_confidence
            if not existing.reference_kind and reference.reference_kind:
                existing.reference_kind = reference.reference_kind
            if not existing.relation_group and reference.relation_group:
                existing.relation_group = reference.relation_group
            if not existing.source_table and getattr(reference, "source_table", ""):
                existing.source_table = str(reference.source_table or "")
            if not existing.source_field and getattr(reference, "source_field", ""):
                existing.source_field = str(reference.source_field or "")
    return tuple(merged)


def _archive_item_icon_catalog_row_value(row: object, key: str) -> object:
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _archive_item_icon_catalog_row_values(row: object, key: str) -> Tuple[str, ...]:
    raw_value = _archive_item_icon_catalog_row_value(row, key)
    if isinstance(raw_value, str):
        value = raw_value.replace("\\", "/").strip()
        return (value,) if value else ()
    if isinstance(raw_value, (list, tuple)):
        values: List[str] = []
        seen: set[str] = set()
        for item in raw_value:
            value = str(item or "").replace("\\", "/").strip()
            lowered = value.casefold()
            if value and lowered not in seen:
                values.append(value)
                seen.add(lowered)
        return tuple(values)
    return ()


def _strip_archive_item_icon_stem_prefix(value: str) -> str:
    stem = PurePosixPath(str(value or "").replace("\\", "/")).stem.casefold().strip()
    for prefix in _ARCHIVE_ITEM_ICON_STEM_PREFIXES:
        if stem.startswith(prefix):
            return stem[len(prefix) :].strip("_")
    return stem


def _archive_path_is_probable_item_icon(path: object) -> bool:
    path_text = str(path or "").replace("\\", "/").strip().casefold()
    if not path_text:
        return False
    posix = PurePosixPath(path_text)
    if posix.suffix.lower() != ".dds":
        return False
    stem = posix.stem.casefold()
    return "itemicon" in path_text or any(stem.startswith(prefix) for prefix in _ARCHIVE_ITEM_ICON_STEM_PREFIXES)


def _add_archive_item_icon_match_keys(keys: set[str], raw_value: object) -> None:
    normalized = str(raw_value or "").replace("\\", "/").strip().strip("/").casefold()
    if not normalized:
        return
    posix = PurePosixPath(normalized)
    basename = posix.name.casefold()
    stem = posix.stem.casefold()
    candidates = {
        normalized,
        basename,
        stem,
        _strip_archive_model_family_variant_suffix(stem),
    }
    icon_model_stem = _strip_archive_item_icon_stem_prefix(stem)
    if icon_model_stem:
        candidates.add(icon_model_stem)
        candidates.add(_strip_archive_model_family_variant_suffix(icon_model_stem))
    for candidate in tuple(candidates):
        if not candidate:
            continue
        keys.add(candidate)
        if "/" not in candidate and "." not in candidate:
            for alias in iter_archive_character_equipment_root_alias_stems(candidate):
                if alias:
                    keys.add(alias.casefold())
            for alias in iter_archive_equipment_model_alias_stems(candidate):
                if alias:
                    keys.add(alias.casefold())


def _archive_item_icon_catalog_row_match_keys(row: object) -> set[str]:
    keys: set[str] = set()
    for key in ("pac_files", "model_stems", "icon_paths"):
        for value in _archive_item_icon_catalog_row_values(row, key):
            _add_archive_item_icon_match_keys(keys, value)
    return keys


def _resolve_archive_item_icon_catalog_entries(
    value: str,
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    fallback_extensions: Sequence[str] = (".dds",),
) -> Tuple[ArchiveEntry, ...]:
    normalized = str(value or "").replace("\\", "/").strip()
    if not normalized:
        return ()
    candidates: List[ArchiveEntry] = []
    seen: set[Tuple[object, ...]] = set()

    def add_entry(entry: ArchiveEntry) -> None:
        key = _archive_entry_identity_signature(entry)
        if key in seen:
            return
        candidates.append(entry)
        seen.add(key)

    def add_by_path_or_basename(candidate_text: str) -> None:
        candidate = str(candidate_text or "").replace("\\", "/").strip()
        if not candidate:
            return
        candidate_lower = candidate.casefold()
        if archive_entries_by_normalized_path is not None:
            for entry in archive_entries_by_normalized_path.get(candidate_lower, ()) or ():
                add_entry(entry)
        basename = PurePosixPath(candidate).name.casefold()
        if basename and archive_entries_by_basename is not None:
            for entry in archive_entries_by_basename.get(basename, ()) or ():
                add_entry(entry)

    add_by_path_or_basename(normalized)
    if not PurePosixPath(normalized).suffix:
        for extension in fallback_extensions:
            ext = str(extension or "").strip()
            if ext and not ext.startswith("."):
                ext = f".{ext}"
            add_by_path_or_basename(f"{normalized}{ext}")
    return tuple(candidates)


def build_archive_item_icon_references_from_catalog(
    source_entry: ArchiveEntry,
    item_asset_catalog: Sequence[object] = (),
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    related_references: Sequence[ArchiveModelTextureReference] = (),
) -> Tuple[ArchiveModelTextureReference, ...]:
    if not isinstance(source_entry, ArchiveEntry) or not item_asset_catalog:
        return ()
    source_keys: set[str] = set()
    _add_archive_item_icon_match_keys(source_keys, source_entry.path)
    for reference in tuple(related_references or ()):
        if not isinstance(reference, ArchiveModelTextureReference):
            continue
        _add_archive_item_icon_match_keys(source_keys, getattr(reference, "reference_name", ""))
        _add_archive_item_icon_match_keys(source_keys, getattr(reference, "resolved_archive_path", ""))
        resolved_entry = getattr(reference, "resolved_entry", None)
        if isinstance(resolved_entry, ArchiveEntry):
            _add_archive_item_icon_match_keys(source_keys, resolved_entry.path)
    if not source_keys:
        return ()

    references: List[ArchiveModelTextureReference] = []
    seen_entries: set[Tuple[object, ...]] = {_archive_entry_identity_signature(source_entry)}
    for row in tuple(item_asset_catalog or ()):
        icon_paths = _archive_item_icon_catalog_row_values(row, "icon_paths")
        if not icon_paths:
            continue
        row_keys = _archive_item_icon_catalog_row_match_keys(row)
        if not (source_keys & row_keys):
            continue
        item_label = str(
            _archive_item_icon_catalog_row_value(row, "display_name")
            or _archive_item_icon_catalog_row_value(row, "internal_name")
            or "Item Finder row"
        ).strip()
        if _archive_path_is_probable_item_icon(source_entry.path):
            owner_candidates: List[str] = []
            owner_candidates.extend(_archive_item_icon_catalog_row_values(row, "pac_files"))
            owner_candidates.extend(_archive_item_icon_catalog_row_values(row, "model_stems"))
            for owner_path in owner_candidates:
                for owner_entry in _resolve_archive_item_icon_catalog_entries(
                    owner_path,
                    archive_entries_by_normalized_path=archive_entries_by_normalized_path,
                    archive_entries_by_basename=archive_entries_by_basename,
                    fallback_extensions=(".pac", ".pam", ".pamlod"),
                ):
                    if str(owner_entry.extension or "").lower() not in {".pac", ".pam", ".pamlod"}:
                        continue
                    entry_key = _archive_entry_identity_signature(owner_entry)
                    if entry_key in seen_entries:
                        continue
                    seen_entries.add(entry_key)
                    references.append(
                        ArchiveModelTextureReference(
                            reference_name=owner_path or owner_entry.basename,
                            semantic_label="Owner Model",
                            semantic_hint=item_label,
                            resolution_status="resolved",
                            resolved_archive_path=owner_entry.path,
                            resolved_package_label=owner_entry.package_label,
                            resolved_entry=owner_entry,
                            usage_count=1,
                            reference_kind="used_by",
                            relation_group="Used By / Model",
                            relation_reason=f"Item Finder catalog links {item_label} to the selected inventory icon.",
                            relation_confidence="item_finder",
                        )
                    )
        for icon_path in icon_paths:
            for icon_entry in _resolve_archive_item_icon_catalog_entries(
                icon_path,
                archive_entries_by_normalized_path=archive_entries_by_normalized_path,
                archive_entries_by_basename=archive_entries_by_basename,
            ):
                if not _archive_path_is_probable_item_icon(icon_entry.path):
                    continue
                entry_key = _archive_entry_identity_signature(icon_entry)
                if entry_key in seen_entries:
                    continue
                seen_entries.add(entry_key)
                references.append(
                    ArchiveModelTextureReference(
                        reference_name=icon_path or icon_entry.basename,
                        semantic_label="Inventory Icon",
                        semantic_hint=item_label,
                        resolution_status="resolved",
                        resolved_archive_path=icon_entry.path,
                        resolved_package_label=icon_entry.package_label,
                        resolved_entry=icon_entry,
                        usage_count=1,
                        reference_kind="item_icon",
                        relation_group="Item Icons",
                        relation_reason=f"Item Finder catalog links {item_label} to this inventory icon.",
                        relation_confidence="item_finder",
                    )
                )
    return tuple(references)
