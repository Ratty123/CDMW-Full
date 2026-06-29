from __future__ import annotations

import fnmatch
import re
import threading
from collections import OrderedDict, defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    DdsInfo,
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
    PreviewMaterialTextureInput,
    RelationConfidence,
    clamp_model_preview_render_settings,
)
from cdmw.core.common import RunCancelled, raise_if_cancelled
from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_filtering import _COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS
from cdmw.core.archive_format import _is_material_sidecar_extension
from cdmw.core.archive_model_references import (
    _ArchiveModelSidecarTextureBinding,
    _allowed_model_sidecar_visible_classes,
    _archive_entry_identity_signature,
    _archive_entry_pathc_identity_signature,
    _archive_texture_family_mismatch_reason,
    _build_archive_relation_metadata,
    _classify_model_sidecar_visible_binding,
    _find_archive_model_related_entries,
    _find_archive_model_sidecar_entries,
    _humanize_model_texture_hint,
    _is_anonymous_model_submesh_reference_key,
    _iter_archive_attachment_side_family_stems,
    _iter_archive_prefab_equipment_family_stems,
    _model_sidecar_visible_class_priority,
    _model_texture_hint_priority,
    _model_texture_slot_hint_priority,
    _normalize_model_submesh_reference,
    _normalize_model_texture_reference,
    _normalize_model_visible_texture_mode,
    _strip_archive_model_family_variant_suffix,
    _texconv_identity_signature,
    iter_archive_character_equipment_root_alias_stems,
    iter_archive_equipment_model_alias_stems,
)
from cdmw.core.pbd_cloth import (
    PbdConfigMaterial,
    build_cloth_preview_from_sidecars,
    collect_pbd_sidecar_hints,
)
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.core.upscale_profiles import (
    derive_texture_group_key,
    infer_texture_semantics,
    normalize_texture_reference_for_sidecar_lookup,
)


def _archive_core():
    from cdmw.core import archive as archive_core

    return archive_core


def ensure_archive_preview_source(*args, **kwargs):
    return _archive_core().ensure_archive_preview_source(*args, **kwargs)


def try_decode_text_like_archive_data(*args, **kwargs):
    return _archive_core().try_decode_text_like_archive_data(*args, **kwargs)

_INITIAL_MODEL_PREVIEW_RENDER_SETTINGS = clamp_model_preview_render_settings()
# Keep visible base textures closer to their source resolution in the 3D preview.
# Support maps are only sampled for lighting/material approximation. Keep them
# small before the CPU material combiner reads them; large support-map previews
# dominate cold .pac/.pam preview load time without improving the on-screen result.
_MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = _INITIAL_MODEL_PREVIEW_RENDER_SETTINGS.preview_texture_max_dimension
_MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = min(
    256,
    max(128, int(_INITIAL_MODEL_PREVIEW_RENDER_SETTINGS.low_quality_texture_max_dimension)),
)
_FAST_ARCHIVE_PREVIEW_MAX_FACES = 35_000
_FAST_ARCHIVE_PREVIEW_TEXTURE_NOTE = (
    "Fast preview skips high-resolution texture preparation while the full-quality preview builds in the background."
)
_MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES: Tuple[str, ...] = (
    "",
    "_d",
    "_diff",
    "_ct",
    "_color",
    "_col",
    "_bc",
    "_albedo",
    "_basecolor",
    "_base_color",
    "_diffuse",
)

# Archive query and name-search index ownership lives in archive_name_search.
from cdmw.core.archive_name_search import (
    _ARCHIVE_SEARCH_DEFAULT_FIELD,
    _ARCHIVE_SEARCH_FIELDS,
    _ARCHIVE_SEARCH_SIZE_RE,
    ArchiveSearchTerm,
    ArchiveSearchQuery,
    _tokenize_archive_search_text,
    _archive_search_size_to_bytes,
    _strip_archive_search_quotes,
    _archive_search_term_from_token,
    parse_archive_search_query,
    _archive_search_tokens,
    _archive_search_token_prefix_match,
    _archive_search_text_match,
    _ARCHIVE_NAME_SEARCH_COMMON_TERMS,
    _ARCHIVE_NAME_SEARCH_TOKEN_ALIASES,
    _ARCHIVE_NAME_SEARCH_QUERY_ALIASES,
    _ARCHIVE_NAME_SEARCH_INDEXABLE_FIELDS,
    _archive_name_search_embedded_source_tokens,
    _archive_name_search_aliases_for_token,
    _archive_name_search_token_matches,
    _archive_name_search_text_match,
    ArchiveNameSearchIndex,
    _native_name_search_cache_row_limit,
    _LazyNativeNameSearchTokenRows,
    _MergedArchiveNameSearchTokenRows,
    _build_archive_name_search_index_python,
    _archive_name_search_native_min_entries,
    _sanitize_native_name_search_field,
    _load_native_name_search_index_binary,
    _write_native_name_search_index_binary,
    _try_build_archive_name_search_index_native,
    build_archive_name_search_index,
    _archive_name_search_alias_signature,
    _archive_entry_package_group,
    archive_item_index_dependency_signature,
    _archive_name_search_shard_binary_path,
    _archive_name_search_shard_meta_path,
    _read_archive_name_search_shard_meta,
    _write_archive_name_search_shard_meta,
    _archive_name_search_shard_meta_matches,
    _archive_name_search_shards_ready,
    _load_archive_name_search_shards_trusted,
    _write_archive_name_search_index_shard,
    _load_or_update_archive_name_search_shards,
    load_or_update_archive_name_search_shards,
    _write_archive_name_search_shard_caches,
    LazyArchiveEntryRowIndex,
)

_MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "normal": (
        "_n",
        "_normal",
        "_normalmap",
    ),
    "material": (
        "_sp",
        "_material",
        "_mask",
        "_ma",
        "_mg",
        "_m",
        "_orm",
        "_mra",
        "_rma",
        "_arm",
        "_ao",
        "_spec",
        "_specular",
    ),
    "height": (
        "_disp",
        "_displacement",
        "_height",
        "_hgt",
        "_dmap",
        "_bump",
        "_parallax",
        "_pom",
        "_ssdm",
    ),
}


def set_model_texture_display_preview_max_dimension(
    value: int,
    *,
    low_quality_value: Optional[int] = None,
) -> None:
    global _MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION, _MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION
    settings = clamp_model_preview_render_settings(
        ModelPreviewRenderSettings(
            preview_texture_max_dimension=int(value),
            low_quality_texture_max_dimension=(
                int(low_quality_value)
                if low_quality_value is not None
                else ModelPreviewRenderSettings().low_quality_texture_max_dimension
            ),
        )
    )
    _MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = int(settings.preview_texture_max_dimension)
    _MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = min(
        256,
        max(128, int(settings.low_quality_texture_max_dimension)),
    )

_MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT = 2048
_MODEL_TEXTURE_PREVIEW_PATH_CACHE: OrderedDict[Tuple[object, ...], str] = OrderedDict()
_MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK = threading.Lock()

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


def _iter_parsed_model_submeshes(parsed_mesh: Optional[object]) -> List[object]:
    if parsed_mesh is None:
        return []
    if str(getattr(parsed_mesh, "format", "") or "").strip().lower() == "pamlod":
        lod_levels = getattr(parsed_mesh, "lod_levels", None) or [[]]
        return list(lod_levels[0] or [])
    return list(getattr(parsed_mesh, "submeshes", ()) or [])


def _iter_model_submesh_reference_candidates(*values: str) -> Tuple[str, ...]:
    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_submesh_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)

    for raw_value in values:
        raw_text = str(raw_value or "").strip()
        if not raw_text:
            continue
        add_candidate(raw_text)
        pure_path = PurePosixPath(raw_text.replace("\\", "/"))
        basename = pure_path.name
        stem = pure_path.stem
        if basename and basename != raw_text:
            add_candidate(basename)
        if stem and stem not in {raw_text, basename}:
            add_candidate(stem)
    return tuple(ordered_candidates)


def _iter_model_sidecar_binding_submesh_keys(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[str, ...]:
    values: List[str] = [
        str(getattr(binding, "submesh_name", "") or ""),
        str(getattr(binding, "part_name", "") or ""),
        str(getattr(binding, "material_name", "") or ""),
    ]
    explicit_keys = _iter_model_submesh_reference_candidates(*values)
    if explicit_keys:
        return explicit_keys
    linked_mesh_path = str(getattr(binding, "linked_mesh_path", "") or "").replace("\\", "/").strip()
    if linked_mesh_path:
        linked_mesh = PurePosixPath(linked_mesh_path)
        values.extend([linked_mesh_path, linked_mesh.name, linked_mesh.stem])
    return _iter_model_submesh_reference_candidates(*values)


def _archive_model_component_alias_stems(path: str) -> set[str]:
    normalized = _normalize_model_texture_reference(path)
    if not normalized:
        return set()
    stem = PurePosixPath(normalized).stem.strip().lower()
    if not stem:
        return set()
    stems: set[str] = {stem}
    stripped = _strip_archive_model_family_variant_suffix(stem)
    if stripped:
        stems.add(stripped)
    for alias in _iter_archive_attachment_side_family_stems(stem):
        stems.add(alias)
    for alias in _iter_archive_prefab_equipment_family_stems(stem):
        stems.add(alias)
    for alias in iter_archive_equipment_model_alias_stems(stem):
        stems.add(alias)
    for alias in iter_archive_character_equipment_root_alias_stems(stem):
        stems.add(alias)
    return {value for value in stems if value}


def _sidecar_binding_linked_model_path(binding: _ArchiveModelSidecarTextureBinding) -> str:
    linked_mesh_path = _normalize_model_texture_reference(str(getattr(binding, "linked_mesh_path", "") or ""))
    if linked_mesh_path:
        return linked_mesh_path
    sidecar_path = str(getattr(binding, "sidecar_path", "") or "").replace("\\", "/").strip()
    if not sidecar_path:
        return ""
    lowered = sidecar_path.lower()
    sidecar_kind = str(getattr(binding, "sidecar_kind", "") or "").strip().lower()
    if (sidecar_kind == "pac_xml" or lowered.endswith(".pac_xml")) and lowered.endswith(".pac_xml"):
        return _normalize_model_texture_reference(sidecar_path[: -len(".pac_xml")] + ".pac").replace(
            "/modelproperty/",
            "/model/",
        )
    if (sidecar_kind == "pam_xml" or lowered.endswith(".pam_xml")) and lowered.endswith(".pam_xml"):
        return _normalize_model_texture_reference(sidecar_path[: -len(".pam_xml")] + ".pam")
    if (sidecar_kind == "pamlod_xml" or lowered.endswith(".pamlod_xml")) and lowered.endswith(".pamlod_xml"):
        return _normalize_model_texture_reference(sidecar_path[: -len(".pamlod_xml")] + ".pamlod")
    return ""


def _model_sidecar_binding_matches_source_component(
    source_entry: ArchiveEntry,
    binding: _ArchiveModelSidecarTextureBinding,
) -> bool:
    source_path = _normalize_model_texture_reference(str(getattr(source_entry, "path", "") or ""))
    source_extension = str(getattr(source_entry, "extension", "") or PurePosixPath(source_path).suffix).strip().lower()
    if source_extension not in {".pac", ".pam", ".pamlod"}:
        return True
    linked_model_path = _sidecar_binding_linked_model_path(binding)
    if not linked_model_path or linked_model_path == source_path:
        return True
    source_stems = _archive_model_component_alias_stems(source_path)
    linked_stems = _archive_model_component_alias_stems(linked_model_path)
    if source_stems and linked_stems and source_stems.intersection(linked_stems):
        return True
    return False


def _iter_model_texture_family_reference_candidates(group_key: str) -> Tuple[str, ...]:
    normalized_group_key = _normalize_model_texture_reference(group_key)
    if not normalized_group_key:
        return ()

    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)

    if "/" in normalized_group_key:
        folder, _, family_name = normalized_group_key.rpartition("/")
    else:
        folder, family_name = "", normalized_group_key
    family_name = family_name.strip()
    if not family_name:
        return ()

    for suffix in _MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES:
        basename = f"{family_name}{suffix}.dds"
        add_candidate(basename)
        if folder:
            add_candidate(f"{folder}/{basename}")

    return tuple(ordered_candidates)


def _iter_model_texture_slot_family_reference_candidates(
    group_key: str,
    preview_slot: str,
) -> Tuple[str, ...]:
    normalized_slot = str(preview_slot or "").strip().lower()
    if not normalized_slot or normalized_slot == "base":
        return _iter_model_texture_family_reference_candidates(group_key)

    suffixes = _MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES.get(normalized_slot, ())
    if not suffixes:
        return ()

    normalized_group_key = _normalize_model_texture_reference(group_key)
    if not normalized_group_key:
        return ()

    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)
        parts = [part for part in PurePosixPath(normalized).parts if part]
        if len(parts) >= 3 and parts[1].lower() == "texture":
            texture_folder_variant = "/".join((parts[0], *parts[2:]))
            if texture_folder_variant and texture_folder_variant not in seen:
                seen.add(texture_folder_variant)
                ordered_candidates.append(texture_folder_variant)

    if "/" in normalized_group_key:
        folder, _, family_name = normalized_group_key.rpartition("/")
    else:
        folder, family_name = "", normalized_group_key
    family_name = family_name.strip()
    if not family_name:
        return ()

    for suffix in suffixes:
        basename = f"{family_name}{suffix}.dds"
        add_candidate(basename)
        if folder:
            add_candidate(f"{folder}/{basename}")

    return tuple(ordered_candidates)


def _iter_model_texture_reference_candidates(
    texture_name: str,
    material_name: str = "",
) -> Tuple[str, ...]:
    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)

    for raw_value in (texture_name, material_name):
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized:
            continue
        add_candidate(normalized)
        basename = PurePosixPath(normalized).name
        stem = PurePosixPath(normalized).stem
        suffix = PurePosixPath(normalized).suffix.lower()
        if basename:
            add_candidate(basename)
        if stem:
            add_candidate(stem)
        if suffix != ".dds":
            add_candidate(f"{normalized}.dds")
            if basename:
                add_candidate(f"{basename}.dds")
            if stem:
                add_candidate(f"{stem}.dds")

    return tuple(ordered_candidates)


def _match_model_texture_slot_family_suffix(
    texture_path: str,
    preview_slot: str,
) -> int:
    normalized_slot = str(preview_slot or "").strip().lower()
    suffixes = _MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES.get(normalized_slot, ())
    if not suffixes:
        return -1
    basename = PurePosixPath(_normalize_model_texture_reference(texture_path)).name
    if not basename.endswith(".dds"):
        return -1
    stem = basename[:-4]
    for index, suffix in enumerate(suffixes):
        if stem.endswith(suffix):
            return index
    return -1


def _looks_like_technical_model_texture(texture_path: str) -> bool:
    normalized = _normalize_model_texture_reference(texture_path)
    if not normalized:
        return False
    basename = PurePosixPath(normalized).name
    for pattern in _COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS:
        if (basename and fnmatch.fnmatch(basename, pattern)) or fnmatch.fnmatch(normalized, pattern):
            return True
    return False


def _is_placeholder_model_texture(texture_path: str) -> bool:
    normalized = _normalize_model_texture_reference(texture_path)
    if not normalized:
        return False
    stem = PurePosixPath(normalized).stem.lower()
    compact_stem = re.sub(r"[^a-z0-9]+", "", stem)
    if "nonetexture" in compact_stem or "nulltexture" in compact_stem or "dummytexture" in compact_stem:
        return True
    if compact_stem in {"none", "notexture", "placeholdertexture"}:
        return True
    return False


def _has_explicit_model_texture_reference(*values: str) -> bool:
    for raw_value in values:
        normalized = _normalize_model_texture_reference(raw_value)
        if normalized.endswith(".dds"):
            return True
    return False


def _is_visible_model_texture_type(texture_type: str) -> bool:
    return str(texture_type or "").strip().lower() in {"color", "ui", "emissive", "impostor"}


def _resolve_model_texture_semantics(
    texture_path: str,
    *,
    family_members: Sequence[str] = (),
    sidecar_texts: Sequence[str] = (),
) -> Tuple[str, str, int]:
    semantic = infer_texture_semantics(
        texture_path,
        family_members=family_members,
        sidecar_texts=sidecar_texts,
    )
    texture_type = str(getattr(semantic, "texture_type", "") or "").strip().lower() or "unknown"
    semantic_subtype = str(getattr(semantic, "semantic_subtype", "") or "").strip().lower() or texture_type
    confidence = int(getattr(semantic, "confidence", 0) or 0)
    if texture_type == "unknown":
        normalized = _normalize_model_texture_reference(texture_path)
        if (
            normalized.endswith(".dds")
            and not _is_placeholder_model_texture(normalized)
            and not _looks_like_technical_model_texture(normalized)
        ):
            return "color", "albedo", max(confidence, 64)
    return texture_type, semantic_subtype, confidence


def _resolve_model_texture_semantic_details(
    texture_path: str,
    *,
    family_members: Sequence[str] = (),
    sidecar_texts: Sequence[str] = (),
) -> Tuple[str, str, int, Tuple[str, ...]]:
    semantic = infer_texture_semantics(
        texture_path,
        family_members=family_members,
        sidecar_texts=sidecar_texts,
    )
    texture_type = str(getattr(semantic, "texture_type", "") or "").strip().lower() or "unknown"
    semantic_subtype = str(getattr(semantic, "semantic_subtype", "") or "").strip().lower() or texture_type
    confidence = int(getattr(semantic, "confidence", 0) or 0)
    packed_channels = tuple(
        str(item or "").strip().lower()
        for item in getattr(semantic, "packed_channels", ())
        if str(item or "").strip()
    )
    if texture_type == "unknown":
        normalized = _normalize_model_texture_reference(texture_path)
        if (
            normalized.endswith(".dds")
            and not _is_placeholder_model_texture(normalized)
            and not _looks_like_technical_model_texture(normalized)
        ):
            return "color", "albedo", max(confidence, 64), ()
    return texture_type, semantic_subtype, confidence, packed_channels


def _refine_model_texture_semantic_from_hint(
    texture_type: str,
    semantic_subtype: str,
    semantic_hint: str,
) -> Tuple[str, str]:
    normalized_hint = re.sub(r"[^a-z0-9]+", "", str(semantic_hint or "").strip().lower())
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    if not normalized_hint:
        return normalized_type, normalized_subtype

    if any(token in normalized_hint for token in ("orm", "occlusionroughnessmetallic")):
        return "mask", "orm"
    if any(token in normalized_hint for token in ("rma", "roughnessmetallicao")):
        return "mask", "rma"
    if any(token in normalized_hint for token in ("mra", "metallicroughnessao")):
        return "mask", "mra"
    if any(token in normalized_hint for token in ("arm", "aoroughnessmetallic")):
        return "mask", "arm"
    if "roughness" in normalized_hint:
        return "roughness", "roughness"
    if any(token in normalized_hint for token in ("specular", "gloss", "smoothness")):
        return "mask", "specular"
    if any(token in normalized_hint for token in ("metallic", "metalness")):
        return "mask", "metallic"
    if any(token in normalized_hint for token in ("ao", "occlusion")):
        return "mask", "ao"
    if "opacity" in normalized_hint or "alpha" in normalized_hint:
        return "mask", "opacity_mask"
    if "material" in normalized_hint and normalized_subtype in {"unknown", "mask"}:
        return "mask", "material_mask"
    if any(token in normalized_hint for token in ("basecolor", "basecolour", "overlaycolor", "diffuse", "albedo", "colortexture")):
        return "color", "albedo"
    if "emissive" in normalized_hint:
        return "emissive", "emissive"
    return normalized_type, normalized_subtype


def _infer_model_preview_texture_slot(
    texture_path: str,
    *,
    semantic_hint: str = "",
    sidecar_texts: Sequence[str] = (),
) -> str:
    normalized_hint = re.sub(r"[^a-z0-9]+", "", str(semantic_hint or "").strip().lower())
    if normalized_hint:
        if "normal" in normalized_hint:
            return "normal"
        if any(token in normalized_hint for token in ("height", "displacement", "parallax", "pom", "ssdm", "bump")):
            return "height"
        if any(token in normalized_hint for token in ("material", "roughness", "metallic", "metalness", "specular", "ao", "occlusion", "mask")):
            return "material"
        if any(token in normalized_hint for token in ("basecolor", "overlaycolor", "diffuse", "albedo", "colortexture", "emissive")):
            return "base"
    texture_type, semantic_subtype, _confidence = _resolve_model_texture_semantics(
        texture_path,
        sidecar_texts=sidecar_texts,
    )
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    if normalized_type == "normal":
        return "normal"
    if normalized_type == "height" or normalized_subtype in {"displacement", "parallax_height", "height", "bump"}:
        return "height"
    if normalized_type in {"mask", "roughness", "vector"}:
        return "material"
    return "base"


def _model_texture_candidate_slot_priority(
    preview_slot: str,
    texture_path: str,
    *,
    sidecar_texts: Sequence[str] = (),
) -> Optional[Tuple[int, int]]:
    normalized_slot = str(preview_slot or "").strip().lower()
    if normalized_slot not in {"normal", "material", "height"}:
        return None

    texture_type, semantic_subtype, _confidence = _resolve_model_texture_semantics(
        texture_path,
        sidecar_texts=sidecar_texts,
    )
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    suffix_index = _match_model_texture_slot_family_suffix(texture_path, normalized_slot)
    suffix_priority = (
        len(_MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES.get(normalized_slot, ())) - suffix_index
        if suffix_index >= 0
        else 0
    )

    if normalized_slot == "normal":
        if normalized_type == "normal":
            return (12, 3)
        if suffix_index >= 0:
            return (10, suffix_priority)
        return None

    if normalized_slot == "height":
        if normalized_type == "height" or normalized_subtype in {"displacement", "parallax_height", "height", "bump"}:
            return (12, 3)
        if suffix_index >= 0:
            return (10, suffix_priority)
        return None

    if normalized_slot == "material":
        if normalized_type in {"mask", "roughness", "vector"}:
            return (12, 3)
        if normalized_subtype in {"packed_mask", "specular", "metallic", "ao", "mask", "opacity_mask"}:
            return (11, 2)
        if suffix_index >= 0:
            return (10, suffix_priority)
        return None

    return None


def _infer_model_preview_normal_strength(
    *,
    base_texture_path: str = "",
    normal_texture_path: str = "",
    material_name: str = "",
    semantic_hint: str = "",
    prefer_stronger: bool = False,
) -> float:
    normalized_hint = str(semantic_hint or "").strip().lower().replace("_", "")
    combined = " ".join(
        part
        for part in (
            _normalize_model_texture_reference(base_texture_path),
            _normalize_model_texture_reference(normal_texture_path),
            str(material_name or "").strip().lower(),
            normalized_hint,
        )
        if part
    )

    strength = 0.36
    if prefer_stronger:
        strength += 0.08
    if normalized_hint in {"normaltexture", "basenormaltexture"}:
        strength += 0.06
    elif "detailnormal" in normalized_hint or "grimenormal" in normalized_hint:
        strength -= 0.05

    soft_tokens = (
        "wood",
        "plank",
        "timber",
        "fabric",
        "cloth",
        "rope",
        "leather",
        "skin",
        "paper",
        "parchment",
        "banner",
        "canvas",
        "fur",
        "hair",
    )
    hard_tokens = (
        "stone",
        "rock",
        "brick",
        "concrete",
        "cliff",
        "marble",
        "granite",
        "dungeon",
        "ancient",
        "wall",
        "masonry",
        "ruin",
    )
    medium_tokens = (
        "metal",
        "rust",
        "iron",
        "steel",
        "armor",
        "shield",
        "weapon",
    )

    if any(token in combined for token in soft_tokens):
        strength -= 0.04
    if any(token in combined for token in hard_tokens):
        strength += 0.14
    if any(token in combined for token in medium_tokens):
        strength += 0.08

    return max(0.22, min(0.72, strength))


def _set_model_preview_texture_slot(
    mesh: ModelPreviewMesh,
    *,
    slot: str,
    preview_path: str,
    texture_path: str,
    normal_strength: Optional[float] = None,
    semantic_type: str = "",
    semantic_subtype: str = "",
    packed_channels: Sequence[str] = (),
    flip_vertical: Optional[bool] = None,
) -> bool:
    normalized_slot = str(slot or "").strip().lower()
    preview_path_text = str(preview_path or "").strip()
    texture_path_text = str(texture_path or "").strip()
    if not preview_path_text:
        return False

    if normalized_slot == "normal":
        if not str(getattr(mesh, "preview_normal_texture_path", "") or "").strip():
            mesh.preview_normal_texture_path = preview_path_text
            mesh.preview_normal_texture_image = None
            mesh.preview_normal_texture_name = texture_path_text
            if normal_strength is not None:
                mesh.preview_normal_texture_strength = float(normal_strength)
            if texture_path_text and not str(getattr(mesh, "texture_name", "") or "").strip():
                mesh.texture_name = texture_path_text
            _append_model_preview_material_input(
                mesh,
                PreviewMaterialTextureInput(
                    slot_kind="normal",
                    source_texture_path=texture_path_text,
                    source_dds_path=texture_path_text,
                    texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                    preview_texture_path=preview_path_text,
                    semantic_type="normal",
                    semantic_subtype="normal",
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    confidence="resolved",
                    visualized=True,
                ),
            )
            return True
        return False
    if normalized_slot == "material":
        if not str(getattr(mesh, "preview_material_texture_path", "") or "").strip():
            mesh.preview_material_texture_path = preview_path_text
            mesh.preview_material_texture_image = None
            mesh.preview_material_texture_name = texture_path_text
            mesh.preview_material_texture_type = str(semantic_type or "").strip().lower()
            mesh.preview_material_texture_subtype = str(semantic_subtype or "").strip().lower()
            mesh.preview_material_texture_packed_channels = tuple(
                str(channel or "").strip().lower()
                for channel in packed_channels
                if str(channel or "").strip()
            )
            _append_model_preview_material_input(
                mesh,
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    source_texture_path=texture_path_text,
                    source_dds_path=texture_path_text,
                    texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                    preview_texture_path=preview_path_text,
                    semantic_type=str(semantic_type or "material").strip().lower(),
                    semantic_subtype=str(semantic_subtype or "").strip().lower(),
                    packed_channels=tuple(
                        str(channel or "").strip().lower()
                        for channel in packed_channels
                        if str(channel or "").strip()
                    ),
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    confidence="resolved",
                    visualized=True,
                ),
            )
            return True
        return False
    if normalized_slot == "height":
        if not str(getattr(mesh, "preview_height_texture_path", "") or "").strip():
            mesh.preview_height_texture_path = preview_path_text
            mesh.preview_height_texture_image = None
            mesh.preview_height_texture_name = texture_path_text
            _append_model_preview_material_input(
                mesh,
                PreviewMaterialTextureInput(
                    slot_kind="height",
                    source_texture_path=texture_path_text,
                    source_dds_path=texture_path_text,
                    texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                    preview_texture_path=preview_path_text,
                    semantic_type="height",
                    semantic_subtype="displacement",
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    confidence="resolved",
                    visualized=True,
                ),
            )
            return True
        return False

    changed = False
    if not str(getattr(mesh, "preview_texture_path", "") or "").strip():
        mesh.preview_texture_path = preview_path_text
        mesh.preview_texture_image = None
        changed = True
    if texture_path_text:
        current_texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        if not current_texture_name or not current_texture_name.lower().endswith(".dds"):
            mesh.texture_name = texture_path_text
            changed = True
    if flip_vertical is not None:
        mesh.preview_texture_flip_vertical = bool(flip_vertical)
        changed = True
    if changed:
        _append_model_preview_material_input(
            mesh,
            PreviewMaterialTextureInput(
                slot_kind="base",
                source_texture_path=texture_path_text,
                source_dds_path=texture_path_text,
                texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                preview_texture_path=preview_path_text,
                semantic_type="color",
                semantic_subtype="albedo",
                material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                confidence="resolved",
                visualized=True,
            ),
        )
    return changed


def _append_model_preview_material_input(
    mesh: ModelPreviewMesh,
    input_item: PreviewMaterialTextureInput,
) -> bool:
    existing = list(getattr(mesh, "preview_material_texture_inputs", ()) or ())
    key = (
        str(input_item.slot_kind or "").strip().lower(),
        str(input_item.preview_texture_path or "").strip().lower(),
        str(input_item.source_texture_path or "").strip().lower(),
        str(input_item.parameter_name or "").strip().lower(),
    )
    for item in existing:
        existing_key = (
            str(getattr(item, "slot_kind", "") or "").strip().lower(),
            str(getattr(item, "preview_texture_path", "") or "").strip().lower(),
            str(getattr(item, "source_texture_path", "") or "").strip().lower(),
            str(getattr(item, "parameter_name", "") or "").strip().lower(),
        )
        if existing_key == key:
            return False
    existing.append(input_item)
    mesh.preview_material_texture_inputs = tuple(existing)
    return True


def _score_model_texture_archive_candidate(
    source_entry: ArchiveEntry,
    candidate: ArchiveEntry,
    reference_candidates: Sequence[str],
) -> Tuple[int, int]:
    score_value = 0
    normalized_candidate_path = _normalize_model_texture_reference(candidate.path)
    candidate_basename = PurePosixPath(normalized_candidate_path).name
    for reference_index, normalized_reference in enumerate(reference_candidates):
        reference_basename = PurePosixPath(normalized_reference).name
        if normalized_candidate_path == normalized_reference:
            score_value += max(8, 24 - reference_index)
            break
        if candidate_basename and candidate_basename == reference_basename:
            score_value += max(4, 16 - reference_index)
            break
    if candidate.pamt_path == source_entry.pamt_path:
        score_value += 8
    if candidate.pamt_path.parent == source_entry.pamt_path.parent:
        score_value += 4
    if candidate.paz_file == source_entry.paz_file:
        score_value += 2
    if "/texture/" in normalized_candidate_path:
        score_value += 1
    return score_value, -len(candidate.path)


def _collect_model_texture_archive_entry_candidates(
    source_entry: ArchiveEntry,
    texture_name: str,
    material_name: str,
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    *,
    expand_family_candidates: bool = True,
    preferred_slot: str = "",
) -> List[Tuple[ArchiveEntry, Tuple[int, int]]]:
    reference_candidates = _iter_model_texture_reference_candidates(texture_name, material_name)
    if not reference_candidates:
        return []

    expanded_reference_candidates: List[str] = list(reference_candidates)
    if expand_family_candidates:
        seen_expanded = set(expanded_reference_candidates)
        for normalized_reference in reference_candidates:
            group_key = derive_texture_group_key(normalized_reference)
            for family_reference in _iter_model_texture_slot_family_reference_candidates(group_key, preferred_slot):
                if family_reference in seen_expanded:
                    continue
                seen_expanded.add(family_reference)
                expanded_reference_candidates.append(family_reference)

    candidates: List[ArchiveEntry] = []
    for normalized_reference in expanded_reference_candidates:
        if texture_entries_by_normalized_path is not None:
            for candidate in texture_entries_by_normalized_path.get(normalized_reference, []):
                if candidate.extension == ".dds" and candidate not in candidates:
                    candidates.append(candidate)

        basename = PurePosixPath(normalized_reference).name
        if texture_entries_by_basename is not None and basename:
            for candidate in texture_entries_by_basename.get(basename, []):
                if candidate.extension == ".dds" and candidate not in candidates:
                    candidates.append(candidate)

    if not candidates:
        return []

    scored_candidates = [
        (candidate, _score_model_texture_archive_candidate(source_entry, candidate, reference_candidates))
        for candidate in candidates
    ]
    scored_candidates.sort(key=lambda item: item[1], reverse=True)
    return scored_candidates


def _model_texture_semantic_priority(texture_type: str, semantic_subtype: str) -> Tuple[int, int]:
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    if normalized_type == "color":
        subtype_priority = {
            "albedo": 4,
            "albedo_variant": 3,
            "diffuse": 2,
        }.get(normalized_subtype, 1)
        return 6, subtype_priority
    if normalized_type == "ui":
        return 5, 0
    if normalized_type == "emissive":
        return 4, 0
    if normalized_type == "impostor":
        return 3, 0
    if normalized_type == "unknown":
        return 2, 0
    if normalized_type == "mask" and normalized_subtype in {"detail_support", "grayscale_data"}:
        return 1, 0
    return 0, 0


def _resolve_model_texture_archive_entry(
    source_entry: ArchiveEntry,
    texture_name: str,
    material_name: str,
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    *,
    semantic_hint: str = "",
    expand_family_candidates: Optional[bool] = None,
    allow_technical_match: bool = False,
    preferred_slot: str = "",
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
) -> Tuple[Optional[ArchiveEntry], str]:
    normalized_preferred_slot = str(preferred_slot or "").strip().lower()
    if _has_explicit_model_texture_reference(texture_name) and _is_placeholder_model_texture(texture_name):
        return None, "missing"
    if _has_explicit_model_texture_reference(material_name) and _is_placeholder_model_texture(material_name):
        return None, "missing"
    if expand_family_candidates is None:
        if normalized_preferred_slot in {"normal", "material", "height"}:
            expand_family_candidates = True
        else:
            expand_family_candidates = not _has_explicit_model_texture_reference(texture_name, material_name)
    scored_candidates = _collect_model_texture_archive_entry_candidates(
        source_entry,
        texture_name,
        material_name,
        texture_entries_by_normalized_path,
        texture_entries_by_basename,
        expand_family_candidates=expand_family_candidates,
        preferred_slot=normalized_preferred_slot,
    )
    if not scored_candidates:
        return None, "missing"

    family_members_by_group: Dict[str, Tuple[str, ...]] = defaultdict(tuple)
    grouped_family_members: Dict[str, List[str]] = defaultdict(list)
    for candidate, _direct_score in scored_candidates:
        grouped_family_members[derive_texture_group_key(candidate.path)].append(candidate.path)
    for group_key, members in grouped_family_members.items():
        family_members_by_group[group_key] = tuple(members)

    best_candidate: Optional[ArchiveEntry] = None
    best_candidate_key: Optional[Tuple[int, int, int, Tuple[int, int]]] = None
    best_candidate_priority = (0, 0)
    hint_priority = _model_texture_hint_priority(semantic_hint)
    slot_filtered_out = False
    for candidate, direct_score in scored_candidates:
        group_key = derive_texture_group_key(candidate.path)
        candidate_normalized_path = normalize_texture_reference_for_sidecar_lookup(candidate.path)
        sidecar_texts = tuple(sidecar_texts_by_normalized_path.get(candidate_normalized_path, ())) if (
            sidecar_texts_by_normalized_path is not None and candidate_normalized_path
        ) else ()
        if not sidecar_texts and sidecar_texts_by_basename is not None:
            sidecar_texts = tuple(
                sidecar_texts_by_basename.get(PurePosixPath(candidate.path.replace("\\", "/")).name.lower(), ())
            )
        texture_type, semantic_subtype, confidence = _resolve_model_texture_semantics(
            candidate.path,
            family_members=family_members_by_group.get(group_key, (candidate.path,)),
            sidecar_texts=sidecar_texts,
        )
        if normalized_preferred_slot in {"normal", "material", "height"}:
            semantic_priority = _model_texture_candidate_slot_priority(
                normalized_preferred_slot,
                candidate.path,
                sidecar_texts=sidecar_texts,
            )
            if semantic_priority is None:
                slot_filtered_out = True
                continue
        else:
            semantic_priority = _model_texture_semantic_priority(
                texture_type,
                semantic_subtype,
            )
            if hint_priority is not None and hint_priority > semantic_priority:
                semantic_priority = hint_priority
        sort_key = (
            semantic_priority[0],
            semantic_priority[1],
            confidence,
            direct_score,
        )
        if best_candidate_key is None or sort_key > best_candidate_key:
            best_candidate = candidate
            best_candidate_key = sort_key
            best_candidate_priority = semantic_priority

    if best_candidate is None:
        if normalized_preferred_slot in {"normal", "material", "height"} and slot_filtered_out:
            return None, "technical_only"
        return None, "missing"
    if allow_technical_match and best_candidate_priority[0] <= 0:
        return best_candidate, "resolved"
    if best_candidate_priority[0] <= 0:
        return None, "technical_only"
    return best_candidate, "resolved"


def _ensure_archive_model_texture_preview_path(
    resolved_texconv_path: Optional[Path],
    texture_entry: ArchiveEntry,
    *,
    max_dimension: Optional[int] = None,
    slot_kind: str = "base",
    stop_event: Optional[threading.Event] = None,
) -> str:
    resolved_max_dimension = (
        int(max_dimension)
        if max_dimension is not None
        else int(_MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)
    )
    cache_key: Tuple[object, ...] = (
        _archive_entry_identity_signature(texture_entry),
        _archive_entry_pathc_identity_signature(texture_entry),
        _texconv_identity_signature(resolved_texconv_path),
        resolved_max_dimension,
        str(slot_kind or "base").strip().lower(),
    )
    with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
        cached_preview_path = _MODEL_TEXTURE_PREVIEW_PATH_CACHE.get(cache_key)
        if cached_preview_path:
            cached_path = Path(cached_preview_path)
            try:
                if cached_path.is_file() and cached_path.stat().st_size > 0:
                    _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
                    return cached_preview_path
            except OSError:
                pass
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE.pop(cache_key, None)

    texture_source_path, _texture_note = ensure_archive_preview_source(
        texture_entry,
        stop_event=stop_event,
    )
    dds_info: Optional[DdsInfo] = None
    try:
        dds_info = parse_dds(texture_source_path)
    except Exception:
        dds_info = None
    preview_path = ensure_dds_display_preview_png(
        resolved_texconv_path,
        texture_source_path.resolve(),
        dds_info=dds_info,
        max_dimension=resolved_max_dimension,
        slot_kind=slot_kind,
        stop_event=stop_event,
    )
    preview_path_text = str(preview_path)
    with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
        _MODEL_TEXTURE_PREVIEW_PATH_CACHE[cache_key] = preview_path_text
        _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
        while len(_MODEL_TEXTURE_PREVIEW_PATH_CACHE) > _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT:
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE.popitem(last=False)
    return preview_path_text


def _prefetch_archive_model_texture_preview_paths(
    resolved_texconv_path: Optional[Path],
    requests: Sequence[Tuple[ArchiveEntry, str, int]],
    preview_cache: Dict[str, str],
    *,
    stop_event: Optional[threading.Event] = None,
) -> None:
    if not requests:
        return
    try:
        from cdmw.core.texture_native import directxtex_preview_result_key, ensure_directxtex_dds_preview_pngs
    except Exception:
        return

    normalized_requests: List[Tuple[ArchiveEntry, str, int, str, Tuple[object, ...]]] = []
    seen: set[Tuple[str, str, int]] = set()
    for texture_entry, slot_kind, max_dimension in requests:
        slot_key = str(slot_kind or "base").strip().lower() or "base"
        resolved_max_dimension = max(1, int(max_dimension or _MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION))
        normalized_path = _normalize_model_texture_reference(texture_entry.path)
        if not normalized_path:
            continue
        local_key = f"{normalized_path}|{slot_key}"
        dedupe_key = (normalized_path, slot_key, resolved_max_dimension)
        if dedupe_key in seen or preview_cache.get(local_key):
            continue
        seen.add(dedupe_key)
        cache_key: Tuple[object, ...] = (
            _archive_entry_identity_signature(texture_entry),
            _archive_entry_pathc_identity_signature(texture_entry),
            _texconv_identity_signature(resolved_texconv_path),
            resolved_max_dimension,
            slot_key,
        )
        with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
            cached_preview_path = _MODEL_TEXTURE_PREVIEW_PATH_CACHE.get(cache_key)
            if cached_preview_path:
                cached_path = Path(cached_preview_path)
                try:
                    if cached_path.is_file() and cached_path.stat().st_size > 0:
                        _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
                        preview_cache[local_key] = cached_preview_path
                        continue
                except OSError:
                    pass
                _MODEL_TEXTURE_PREVIEW_PATH_CACHE.pop(cache_key, None)
        normalized_requests.append((texture_entry, slot_key, resolved_max_dimension, local_key, cache_key))

    if not normalized_requests:
        return

    jobs: List[Dict[str, object]] = []
    by_job_key: Dict[str, Tuple[str, Tuple[object, ...]]] = {}
    by_source: Dict[str, Tuple[str, Tuple[object, ...]]] = {}
    for texture_entry, slot_key, resolved_max_dimension, local_key, cache_key in normalized_requests:
        raise_if_cancelled(stop_event)
        try:
            texture_source_path, _texture_note = ensure_archive_preview_source(texture_entry, stop_event=stop_event)
            source_key = str(texture_source_path.expanduser().resolve())
        except RunCancelled:
            raise
        except OSError:
            continue
        except Exception:
            continue
        jobs.append(
            {
                "dds_path": source_key,
                "slot_kind": slot_key,
                "max_dimension": resolved_max_dimension,
                "normal_space": "green_up" if slot_key == "normal" else "auto",
                "srgb": "auto",
            }
        )
        job_key = directxtex_preview_result_key(
            Path(source_key),
            max_dimension=resolved_max_dimension,
            slot_kind=slot_key,
            srgb="auto",
            normal_space="green_up" if slot_key == "normal" else "auto",
        )
        by_job_key[job_key] = (local_key, cache_key)
        by_source.setdefault(source_key, (local_key, cache_key))

    if not jobs:
        return

    try:
        timeout_seconds = max(10.0, min(180.0, 4.0 + (len(jobs) * 4.0)))
        results = ensure_directxtex_dds_preview_pngs(
            jobs,
            timeout_seconds=timeout_seconds,
            include_job_keys=True,
            stop_event=stop_event,
        )
    except RunCancelled:
        raise
    except Exception:
        return
    for result_key, mapped in by_job_key.items():
        preview_path = results.get(result_key)
        if preview_path is None:
            source_key = result_key.split("|slot=", 1)[0]
            preview_path = results.get(source_key)
        if preview_path is None:
            continue
        local_key, cache_key = mapped
        preview_path_text = str(preview_path)
        preview_cache[local_key] = preview_path_text
        with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE[cache_key] = preview_path_text
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
            while len(_MODEL_TEXTURE_PREVIEW_PATH_CACHE) > _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT:
                _MODEL_TEXTURE_PREVIEW_PATH_CACHE.popitem(last=False)
    for source_key, preview_path in results.items():
        if "|slot=" in str(source_key):
            continue
        mapped = by_source.get(str(source_key))
        if mapped is None:
            try:
                mapped = by_source.get(str(Path(source_key).expanduser().resolve()))
            except OSError:
                mapped = None
        if mapped is None:
            continue
        local_key, cache_key = mapped
        if local_key in preview_cache:
            continue
        preview_path_text = str(preview_path)
        preview_cache[local_key] = preview_path_text
        with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE[cache_key] = preview_path_text
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
            while len(_MODEL_TEXTURE_PREVIEW_PATH_CACHE) > _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT:
                _MODEL_TEXTURE_PREVIEW_PATH_CACHE.popitem(last=False)


def _model_preview_sidecar_tint(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[float, float, float]:
    tint = tuple(getattr(binding, "tint_color", ()) or ())
    if len(tint) < 3:
        tint = tuple(getattr(binding, "represent_color", ()) or ())
    if len(tint) >= 3:
        return (
            max(0.0, min(2.0, float(tint[0]))),
            max(0.0, min(2.0, float(tint[1]))),
            max(0.0, min(2.0, float(tint[2]))),
        )
    return ()


def _model_preview_sidecar_uv_scale(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[float, float]:
    try:
        uv_scale = float(getattr(binding, "uv_scale", 1.0) or 1.0)
    except (TypeError, ValueError):
        uv_scale = 1.0
    uv_scale = max(0.05, min(64.0, uv_scale))
    if abs(uv_scale - 1.0) <= 1e-6:
        return ()
    return (uv_scale, uv_scale)


def _model_preview_sidecar_material_color(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[float, float, float]:
    color = _model_preview_sidecar_tint(binding)
    if len(color) < 3:
        return ()
    try:
        red = max(0.0, min(1.0, float(color[0])))
        green = max(0.0, min(1.0, float(color[1])))
        blue = max(0.0, min(1.0, float(color[2])))
    except (TypeError, ValueError):
        return ()
    luma = (red * 0.2126) + (green * 0.7152) + (blue * 0.0722)
    saturation = max(red, green, blue) - min(red, green, blue)
    if luma <= 0.018 and saturation <= 0.035:
        return ()
    return (red, green, blue)


def _is_low_authority_model_base_texture(texture_path: str) -> bool:
    normalized = _normalize_model_texture_reference(texture_path)
    if not normalized:
        return False
    if _is_placeholder_model_texture(normalized):
        return True
    basename = PurePosixPath(normalized).name.lower()
    stem = PurePosixPath(normalized).stem.lower()
    if "common_default" in stem and "overlay" in stem:
        return True
    if stem in {"cd_common_default_overlay", "cd_common_default_overlay_old"}:
        return True
    if stem.endswith("_o") or "_overlay" in stem:
        return True
    return False


def _model_preview_base_texture_quality(texture_path: str, *, fallback_only: bool = False) -> str:
    if fallback_only:
        return "material_color_fallback"
    if _is_low_authority_model_base_texture(texture_path):
        return "low_authority_overlay"
    normalized = _normalize_model_texture_reference(texture_path)
    return "resolved_base" if normalized else ""


def _mesh_preview_base_is_low_authority(mesh: ModelPreviewMesh) -> bool:
    quality = str(getattr(mesh, "preview_base_texture_quality", "") or "").strip().lower()
    if quality == "low_authority_overlay":
        return True
    texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
    return _is_low_authority_model_base_texture(texture_name)


def _mesh_existing_base_is_sidecar_identity(
    mesh: ModelPreviewMesh,
    parsed_submesh: Optional[object],
    binding: _ArchiveModelSidecarTextureBinding,
) -> bool:
    sidecar_candidates = _iter_model_submesh_reference_candidates(
        str(getattr(binding, "submesh_name", "") or ""),
        str(getattr(binding, "part_name", "") or ""),
        str(getattr(binding, "material_name", "") or ""),
    )
    if not sidecar_candidates:
        return False
    sidecar_candidate_set = set(sidecar_candidates)
    mesh_candidates = _iter_model_submesh_reference_candidates(
        str(getattr(parsed_submesh, "name", "") or ""),
        str(getattr(parsed_submesh, "material", "") or ""),
        str(getattr(parsed_submesh, "texture", "") or ""),
        str(getattr(mesh, "material_name", "") or ""),
        str(getattr(mesh, "texture_name", "") or ""),
    )
    return any(candidate in sidecar_candidate_set for candidate in mesh_candidates)


def _apply_model_sidecar_base_preview(
    mesh: ModelPreviewMesh,
    *,
    texture_entry: ArchiveEntry,
    preview_path_text: str,
    binding: _ArchiveModelSidecarTextureBinding,
    force_unflipped_preview: bool,
    set_texture_name: bool,
) -> None:
    if str(getattr(mesh, "preview_texture_path", "") or "").strip() != preview_path_text:
        mesh.preview_texture_path = preview_path_text
        mesh.preview_texture_image = None
    if force_unflipped_preview:
        mesh.preview_texture_flip_vertical = False
    current_texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
    if set_texture_name or not current_texture_name or not current_texture_name.lower().endswith(".dds"):
        mesh.texture_name = texture_entry.path
    _append_model_preview_material_input(
        mesh,
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name=str(getattr(binding, "parameter_name", "") or "").strip(),
            source_texture_path=texture_entry.path,
            source_dds_path=texture_entry.path,
            texture_name=PurePosixPath(texture_entry.path.replace("\\", "/")).name,
            preview_texture_path=preview_path_text,
            semantic_type="color",
            semantic_subtype="albedo",
            material_name=(
                str(getattr(binding, "material_name", "") or "").strip()
                or str(getattr(binding, "submesh_name", "") or "").strip()
                or str(getattr(mesh, "material_name", "") or "").strip()
            ),
            part_name=str(getattr(binding, "part_name", "") or "").strip(),
            shader_family=str(getattr(binding, "shader_family", "") or "").strip(),
            confidence="sidecar",
            visualized=True,
            sidecar_kind=str(getattr(binding, "sidecar_kind", "") or "").strip(),
            sidecar_path=str(getattr(binding, "sidecar_path", "") or "").strip(),
            linked_mesh_path=str(getattr(binding, "linked_mesh_path", "") or "").strip(),
            srgb_mode=str(getattr(binding, "srgb_mode", "") or "").strip(),
            parameter_declared_by=str(getattr(binding, "parameter_declared_by", "") or "").strip(),
            material_output_quality=str(getattr(binding, "material_output_quality", "") or "").strip(),
            layer_role=str(getattr(binding, "layer_role", "") or "").strip(),
            layer_channel=str(getattr(binding, "layer_channel", "") or "").strip(),
            blend_flags=tuple(str(value) for value in tuple(getattr(binding, "blend_flags", ()) or ()) if str(value)),
            material_parameters=tuple(getattr(binding, "material_parameters", ()) or ()),
        ),
    )
    current_material_name = str(getattr(mesh, "material_name", "") or "").strip()
    sidecar_material_name = str(getattr(binding, "submesh_name", "") or "").strip()
    if sidecar_material_name and not current_material_name:
        mesh.material_name = sidecar_material_name
    mesh.preview_base_texture_source = str(getattr(binding, "sidecar_kind", "") or "sidecar").strip() or "sidecar"
    mesh.preview_sidecar_material_primitive = (
        str(getattr(binding, "material_name", "") or "").strip()
        or str(getattr(binding, "part_name", "") or "").strip()
        or sidecar_material_name
    )
    mesh.preview_sidecar_shader_family = str(getattr(binding, "shader_family", "") or "").strip()
    try:
        mesh.preview_texture_brightness = max(0.1, min(3.0, float(getattr(binding, "brightness", 1.0) or 1.0)))
    except (TypeError, ValueError):
        mesh.preview_texture_brightness = 1.0
    mesh.preview_texture_tint = _model_preview_sidecar_tint(binding)
    mesh.preview_texture_uv_scale = _model_preview_sidecar_uv_scale(binding)
    material_color = _model_preview_sidecar_material_color(binding)
    low_authority_base = _is_low_authority_model_base_texture(texture_entry.path)
    mesh.preview_base_texture_quality = _model_preview_base_texture_quality(texture_entry.path)
    if material_color:
        mesh.preview_color = material_color
    if (
        mesh.preview_texture_tint
        or mesh.preview_texture_uv_scale
        or abs(float(mesh.preview_texture_brightness or 1.0) - 1.0) > 1e-6
    ):
        mesh.preview_texture_approximation_note = "Sidecar tint, brightness, and UV scale are preview approximations."
    if low_authority_base and material_color:
        mesh.preview_texture_approximation_note = (
            "Sidecar material color drives visible preview color; the resolved DDS is a low-detail overlay/default layer."
        )


def _attach_model_sidecar_texture_preview_paths(
    texconv_path: Optional[Path],
    source_entry: ArchiveEntry,
    model_preview: Optional[ModelPreviewData],
    *,
    parsed_mesh: Optional[object],
    sidecar_texture_bindings: Sequence[_ArchiveModelSidecarTextureBinding],
    visible_texture_mode: str = "mesh_base_first",
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
    fallback_only: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> List[str]:
    if model_preview is None or not model_preview.meshes or not sidecar_texture_bindings:
        return []

    parsed_submeshes = _iter_parsed_model_submeshes(parsed_mesh)
    resolved_texconv_path = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    normalized_visible_texture_mode = _normalize_model_visible_texture_mode(visible_texture_mode)
    allowed_visible_classes = set(_allowed_model_sidecar_visible_classes(normalized_visible_texture_mode))
    resolved_by_submesh: Dict[str, Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]] = {}
    global_visible_bindings: List[Tuple[ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]] = []
    fallback_visible_bindings: List[
        Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]
    ] = []
    material_color_by_submesh: Dict[
        str,
        Tuple[Tuple[int, int, int, int], Tuple[float, float, float], _ArchiveModelSidecarTextureBinding],
    ] = {}
    global_material_colors: List[Tuple[Tuple[int, int, int, int], Tuple[float, float, float], _ArchiveModelSidecarTextureBinding]] = []
    seen_fallback_binding_keys: set[Tuple[str, str, str]] = set()
    seen_global_binding_keys: set[Tuple[str, str]] = set()
    seen_global_color_keys: set[Tuple[float, float, float, str, str]] = set()
    sidecar_paths: List[str] = []
    promoted_anonymous_fallback = False
    force_unflipped_preview = str(getattr(source_entry, "extension", "") or "").lower() == ".pac"
    preview_cache: Dict[str, str] = {}

    def _preview_path_for_entry(texture_entry: ArchiveEntry, *, slot_kind: str = "base") -> str:
        slot_key = str(slot_kind or "base").strip().lower()
        cache_key = f"{_normalize_model_texture_reference(texture_entry.path)}|{slot_key}"
        preview_path_text = preview_cache.get(cache_key, "")
        if preview_path_text:
            return preview_path_text
        preview_path_text = _archive_core()._ensure_archive_model_texture_preview_path(
            resolved_texconv_path,
            texture_entry,
            slot_kind=slot_key,
            stop_event=stop_event,
        )
        preview_cache[cache_key] = preview_path_text
        return preview_path_text

    for binding in sidecar_texture_bindings:
        raise_if_cancelled(stop_event)
        if not _model_sidecar_binding_matches_source_component(source_entry, binding):
            continue
        submesh_keys = _iter_model_sidecar_binding_submesh_keys(binding)
        color_binding_class = _classify_model_sidecar_visible_binding(binding.parameter_name, binding.texture_path)
        material_color = _model_preview_sidecar_material_color(binding)
        if material_color:
            color_priority = (
                _model_sidecar_visible_class_priority(color_binding_class),
                1 if color_binding_class != "technical" else 0,
                1 if str(getattr(binding, "tint_color", "") or "") else 0,
                -len(str(getattr(binding, "texture_path", "") or "")),
            )
            if submesh_keys:
                for submesh_key in submesh_keys:
                    existing_color = material_color_by_submesh.get(submesh_key)
                    if existing_color is None or color_priority > existing_color[0]:
                        material_color_by_submesh[submesh_key] = (color_priority, material_color, binding)
            else:
                global_color_key = (
                    material_color[0],
                    material_color[1],
                    material_color[2],
                    str(getattr(binding, "material_name", "") or "").strip().lower(),
                    str(getattr(binding, "part_name", "") or "").strip().lower(),
                )
                if global_color_key not in seen_global_color_keys:
                    seen_global_color_keys.add(global_color_key)
                    global_material_colors.append((color_priority, material_color, binding))
        texture_entry, resolution_status = _resolve_model_texture_archive_entry(
            source_entry,
            binding.texture_path,
            binding.submesh_name,
            texture_entries_by_normalized_path,
            texture_entries_by_basename,
            semantic_hint=binding.parameter_name,
            expand_family_candidates=False,
            allow_technical_match=True,
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
        )
        if texture_entry is None or resolution_status != "resolved":
            continue
        candidate_normalized_path = normalize_texture_reference_for_sidecar_lookup(texture_entry.path)
        sidecar_texts = tuple(sidecar_texts_by_normalized_path.get(candidate_normalized_path, ())) if (
            sidecar_texts_by_normalized_path is not None and candidate_normalized_path
        ) else ()
        if not sidecar_texts and sidecar_texts_by_basename is not None:
            sidecar_texts = tuple(
                sidecar_texts_by_basename.get(PurePosixPath(texture_entry.path.replace("\\", "/")).name.lower(), ())
            )
        texture_type, semantic_subtype, confidence = _resolve_model_texture_semantics(texture_entry.path)
        if sidecar_texts:
            texture_type, semantic_subtype, confidence = _resolve_model_texture_semantics(
                texture_entry.path,
                sidecar_texts=sidecar_texts,
            )
        texture_type, semantic_subtype = _refine_model_texture_semantic_from_hint(
            texture_type,
            semantic_subtype,
            binding.parameter_name,
        )
        if not _is_visible_model_texture_type(texture_type):
            continue
        binding_class = _classify_model_sidecar_visible_binding(binding.parameter_name, texture_entry.path)
        if binding_class not in allowed_visible_classes:
            continue
        priority = _model_texture_hint_priority(binding.parameter_name) or _model_texture_semantic_priority(
            texture_type,
            semantic_subtype,
        )
        candidate_key = (
            _model_sidecar_visible_class_priority(binding_class),
            priority[0],
            priority[1],
            confidence,
            -len(texture_entry.path),
        )
        fallback_binding_key = (
            _normalize_model_texture_reference(texture_entry.path),
            str(binding.parameter_name or "").strip().lower(),
            _normalize_model_submesh_reference(binding.submesh_name),
        )
        if fallback_binding_key not in seen_fallback_binding_keys:
            seen_fallback_binding_keys.add(fallback_binding_key)
            fallback_visible_bindings.append(
                (
                    candidate_key,
                    texture_entry,
                    binding.parameter_name,
                    binding.submesh_name,
                    binding,
                )
            )
        if submesh_keys:
            for submesh_key in submesh_keys:
                existing = resolved_by_submesh.get(submesh_key)
                if existing is None or candidate_key > existing[0]:
                    resolved_by_submesh[submesh_key] = (
                        candidate_key,
                        texture_entry,
                        binding.parameter_name,
                        binding.submesh_name,
                        binding,
                    )
        else:
            global_key = (
                _normalize_model_texture_reference(texture_entry.path),
                str(binding.parameter_name or "").strip().lower(),
            )
            if global_key not in seen_global_binding_keys:
                seen_global_binding_keys.add(global_key)
                global_visible_bindings.append((texture_entry, binding.parameter_name, binding.submesh_name, binding))
        if binding.sidecar_path and binding.sidecar_path not in sidecar_paths:
            sidecar_paths.append(binding.sidecar_path)

    prefetch_requests: List[Tuple[ArchiveEntry, str, int]] = []
    for _candidate_key, texture_entry, _parameter_name, _submesh_name, _binding in resolved_by_submesh.values():
        prefetch_requests.append((texture_entry, "base", int(_MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)))
    mesh_count = max(1, len(tuple(getattr(model_preview, "meshes", ()) or ())))
    for texture_entry, _parameter_name, _submesh_name, _binding in global_visible_bindings[:mesh_count]:
        prefetch_requests.append((texture_entry, "base", int(_MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)))
    fallback_prefetch_limit = max(mesh_count * 2, 8)
    for _candidate_key, texture_entry, _parameter_name, _submesh_name, _binding in sorted(
        fallback_visible_bindings,
        key=lambda item: item[0],
        reverse=True,
    )[:fallback_prefetch_limit]:
        prefetch_requests.append((texture_entry, "base", int(_MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)))
    _prefetch_archive_model_texture_preview_paths(
        resolved_texconv_path,
        prefetch_requests,
        preview_cache,
        stop_event=stop_event,
    )

    assigned_count = 0
    identity_override_count = 0
    low_authority_layer_override_count = 0
    unresolved_meshes: List[ModelPreviewMesh] = []
    unresolved_mesh_indices_by_id: Dict[int, int] = {}
    ordered_anonymous_fallback_count = 0

    def _best_non_low_authority_fallback_for_mesh(
        candidate_keys: Sequence[str],
    ) -> Optional[Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]]:
        if not candidate_keys:
            return None
        candidate_key_set = set(candidate_keys)
        best_item: Optional[
            Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]
        ] = None
        for fallback_item in fallback_visible_bindings:
            texture_entry = fallback_item[1]
            if _is_low_authority_model_base_texture(texture_entry.path):
                continue
            binding = fallback_item[4]
            binding_keys = _iter_model_sidecar_binding_submesh_keys(binding)
            if not binding_keys or not any(binding_key in candidate_key_set for binding_key in binding_keys):
                continue
            if best_item is None or fallback_item[0] > best_item[0]:
                best_item = fallback_item
        return best_item

    def _mesh_reference_candidates_for_index(mesh_index: int, mesh: ModelPreviewMesh) -> Tuple[str, ...]:
        parsed_submesh = parsed_submeshes[mesh_index] if 0 <= mesh_index < len(parsed_submeshes) else None
        return _iter_model_submesh_reference_candidates(
            str(getattr(parsed_submesh, "name", "") or ""),
            str(getattr(parsed_submesh, "material", "") or ""),
            str(getattr(parsed_submesh, "texture", "") or ""),
            str(getattr(mesh, "material_name", "") or ""),
            str(getattr(mesh, "texture_name", "") or ""),
        )

    def _mesh_preview_identity_is_anonymous(mesh_index: int, mesh: ModelPreviewMesh) -> bool:
        candidate_keys = _mesh_reference_candidates_for_index(mesh_index, mesh)
        return not candidate_keys or all(_is_anonymous_model_submesh_reference_key(candidate_key) for candidate_key in candidate_keys)

    for mesh_index, mesh in enumerate(model_preview.meshes):
        raise_if_cancelled(stop_event)
        existing_preview_path = str(getattr(mesh, "preview_texture_path", "") or "").strip()
        parsed_submesh = parsed_submeshes[mesh_index] if mesh_index < len(parsed_submeshes) else None
        candidate_keys = _mesh_reference_candidates_for_index(mesh_index, mesh)
        best_match: Optional[Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]] = None
        for candidate_key_text in candidate_keys:
            resolved = resolved_by_submesh.get(candidate_key_text)
            if resolved is None:
                continue
            if best_match is None or resolved[0] > best_match[0]:
                best_match = resolved
        promoted_low_authority_layer = False
        if fallback_only and existing_preview_path and _mesh_preview_base_is_low_authority(mesh):
            better_layer_match = _best_non_low_authority_fallback_for_mesh(candidate_keys)
            if better_layer_match is not None:
                best_match = better_layer_match
                promoted_low_authority_layer = True
        if best_match is None:
            if not existing_preview_path:
                unresolved_meshes.append(mesh)
                unresolved_mesh_indices_by_id[id(mesh)] = mesh_index
            continue
        _candidate_key, texture_entry, _parameter_name, submesh_name, binding = best_match
        if existing_preview_path:
            if fallback_only and not promoted_low_authority_layer:
                continue
            if not promoted_low_authority_layer and not _mesh_existing_base_is_sidecar_identity(mesh, parsed_submesh, binding):
                continue
        try:
            preview_path_text = _preview_path_for_entry(texture_entry)
            _apply_model_sidecar_base_preview(
                mesh,
                texture_entry=texture_entry,
                preview_path_text=preview_path_text,
                binding=binding,
                force_unflipped_preview=force_unflipped_preview,
                set_texture_name=bool(existing_preview_path),
            )
            if existing_preview_path and _normalize_model_texture_reference(existing_preview_path) != _normalize_model_texture_reference(preview_path_text):
                if promoted_low_authority_layer:
                    low_authority_layer_override_count += 1
                    mesh.preview_texture_approximation_note = (
                        "Sidecar visible layer texture is used over a low-detail overlay/default base for preview."
                    )
                else:
                    identity_override_count += 1
            assigned_count += 1
        except RunCancelled:
            raise
        except Exception:
            continue

    if unresolved_meshes and fallback_visible_bindings:
        ordered_keys: Dict[str, int] = {}
        best_fallback_by_key: Dict[
            str,
            Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding],
        ] = {}
        for fallback_item in fallback_visible_bindings:
            binding = fallback_item[4]
            sidecar_key = ""
            for raw_value in (
                str(getattr(binding, "submesh_name", "") or ""),
                str(getattr(binding, "part_name", "") or ""),
                str(getattr(binding, "material_name", "") or ""),
            ):
                sidecar_key = _normalize_model_submesh_reference(raw_value)
                if sidecar_key:
                    break
            if not sidecar_key:
                continue
            ordered_keys.setdefault(sidecar_key, len(ordered_keys))
            existing = best_fallback_by_key.get(sidecar_key)
            if existing is None or fallback_item[0] > existing[0]:
                best_fallback_by_key[sidecar_key] = fallback_item
        ordered_fallbacks = [
            best_fallback_by_key[key]
            for key, _order in sorted(ordered_keys.items(), key=lambda item: item[1])
            if key in best_fallback_by_key
        ]
        if len(ordered_fallbacks) > 1:
            for mesh in unresolved_meshes:
                raise_if_cancelled(stop_event)
                if str(getattr(mesh, "preview_texture_path", "") or "").strip():
                    continue
                mesh_index = unresolved_mesh_indices_by_id.get(id(mesh), -1)
                if mesh_index < 0 or mesh_index >= len(ordered_fallbacks):
                    continue
                _candidate_key, texture_entry, _parameter_name, _submesh_name, binding = ordered_fallbacks[mesh_index]
                try:
                    preview_path_text = _preview_path_for_entry(texture_entry)
                    _apply_model_sidecar_base_preview(
                        mesh,
                        texture_entry=texture_entry,
                        preview_path_text=preview_path_text,
                        binding=binding,
                        force_unflipped_preview=force_unflipped_preview,
                        set_texture_name=False,
                    )
                    assigned_count += 1
                    ordered_anonymous_fallback_count += 1
                except RunCancelled:
                    raise
                except Exception:
                    continue

    if not global_visible_bindings and unresolved_meshes and fallback_visible_bindings:
        unresolved_meshes_are_anonymous = all(
            _mesh_preview_identity_is_anonymous(unresolved_mesh_indices_by_id.get(id(mesh), -1), mesh)
            for mesh in unresolved_meshes
        )
        unique_named_sidecar_submeshes = {
            _normalize_model_submesh_reference(submesh_name)
            for _candidate_key, _texture_entry, _parameter_name, submesh_name, _binding in fallback_visible_bindings
            if _normalize_model_submesh_reference(submesh_name)
        }
        unique_named_sidecar_submeshes_all = {
            sidecar_key
            for binding in sidecar_texture_bindings
            for sidecar_key in _iter_model_sidecar_binding_submesh_keys(binding)[:1]
            if sidecar_key
        }
        should_promote_fallback = (
            len(model_preview.meshes) == 1
            or (
                unresolved_meshes_are_anonymous
                and (
                    len(unresolved_meshes) == 1
                    or len(parsed_submeshes) <= 1
                    or (len(unique_named_sidecar_submeshes) == 1 and len(unique_named_sidecar_submeshes_all) <= 1)
                )
            )
        )
        if should_promote_fallback:
            fallback_visible_bindings.sort(key=lambda item: item[0], reverse=True)
            _candidate_key, texture_entry, parameter_name, submesh_name, binding = fallback_visible_bindings[0]
            global_visible_bindings.append((texture_entry, parameter_name, submesh_name, binding))
            promoted_anonymous_fallback = True

    if global_visible_bindings and unresolved_meshes:
        if len(global_visible_bindings) == 1:
            texture_entry, _parameter_name, submesh_name, binding = global_visible_bindings[0]
            for mesh in unresolved_meshes:
                raise_if_cancelled(stop_event)
                if str(getattr(mesh, "preview_texture_path", "") or "").strip():
                    continue
                try:
                    preview_path_text = _preview_path_for_entry(texture_entry)
                    _apply_model_sidecar_base_preview(
                        mesh,
                        texture_entry=texture_entry,
                        preview_path_text=preview_path_text,
                        binding=binding,
                        force_unflipped_preview=force_unflipped_preview,
                        set_texture_name=False,
                    )
                    assigned_count += 1
                except RunCancelled:
                    raise
                except Exception:
                    continue
        else:
            binding_index = 0
            for mesh in unresolved_meshes:
                raise_if_cancelled(stop_event)
                if str(getattr(mesh, "preview_texture_path", "") or "").strip():
                    continue
                if binding_index >= len(global_visible_bindings):
                    break
                texture_entry, _parameter_name, submesh_name, binding = global_visible_bindings[binding_index]
                binding_index += 1
                try:
                    preview_path_text = _preview_path_for_entry(texture_entry)
                    _apply_model_sidecar_base_preview(
                        mesh,
                        texture_entry=texture_entry,
                        preview_path_text=preview_path_text,
                        binding=binding,
                        force_unflipped_preview=force_unflipped_preview,
                        set_texture_name=False,
                    )
                    assigned_count += 1
                except RunCancelled:
                    raise
                except Exception:
                    continue

    material_color_fallback_count = 0
    if material_color_by_submesh or global_material_colors:
        sorted_global_material_colors = [
            item for item in sorted(global_material_colors, key=lambda item: item[0], reverse=True)
        ]
        global_color_index = 0
        for mesh_index, mesh in enumerate(model_preview.meshes):
            raise_if_cancelled(stop_event)
            existing_preview_color = tuple(getattr(mesh, "preview_color", ()) or ())
            existing_preview_path = str(getattr(mesh, "preview_texture_path", "") or "").strip()
            parsed_submesh = parsed_submeshes[mesh_index] if mesh_index < len(parsed_submeshes) else None
            candidate_keys = _iter_model_submesh_reference_candidates(
                str(getattr(parsed_submesh, "name", "") or ""),
                str(getattr(parsed_submesh, "material", "") or ""),
                str(getattr(parsed_submesh, "texture", "") or ""),
                str(getattr(mesh, "material_name", "") or ""),
                str(getattr(mesh, "texture_name", "") or ""),
            )
            best_color: Optional[
                Tuple[Tuple[int, int, int, int], Tuple[float, float, float], _ArchiveModelSidecarTextureBinding]
            ] = None
            for candidate_key_text in candidate_keys:
                color_item = material_color_by_submesh.get(candidate_key_text)
                if color_item is not None and (best_color is None or color_item[0] > best_color[0]):
                    best_color = color_item
            if best_color is None and sorted_global_material_colors:
                if len(sorted_global_material_colors) == 1:
                    best_color = sorted_global_material_colors[0]
                elif not existing_preview_path and global_color_index < len(sorted_global_material_colors):
                    best_color = sorted_global_material_colors[global_color_index]
                    global_color_index += 1
            if best_color is None:
                continue
            _color_priority, material_color, _binding = best_color
            should_assign_color = (
                len(existing_preview_color) < 3
                or not existing_preview_path
                or _is_low_authority_model_base_texture(str(getattr(mesh, "texture_name", "") or ""))
            )
            if not should_assign_color:
                continue
            if tuple(existing_preview_color[:3]) != tuple(material_color):
                mesh.preview_color = material_color
                if not existing_preview_path:
                    mesh.preview_base_texture_quality = "material_color_fallback"
                material_color_fallback_count += 1
                if not existing_preview_path:
                    mesh.preview_texture_approximation_note = (
                        "Sidecar material color is used because no exact visible base DDS preview was resolved."
                    )

    if assigned_count <= 0:
        if material_color_fallback_count <= 0:
            return []
        return [
            f"Applied {material_color_fallback_count:,} sidecar material color fallback(s) for meshes without a reliable visible base DDS."
        ]
    sidecar_suffix = f" from {', '.join(sidecar_paths[:2])}" if sidecar_paths else ""
    if len(sidecar_paths) > 2:
        sidecar_suffix += " ..."
    info_lines = [
        (
            f"Applied {assigned_count:,} textured preview fallback binding(s) from companion material sidecar data{sidecar_suffix}."
            if fallback_only
            else f"Applied {assigned_count:,} textured preview binding(s) from companion material sidecar data{sidecar_suffix}."
        )
    ]
    if promoted_anonymous_fallback:
        info_lines.append(
            "Used a sidecar texture fallback because the recovered mesh preview did not preserve a reliable submesh/material name match."
        )
    if ordered_anonymous_fallback_count > 0:
        info_lines.append(
            f"Matched {ordered_anonymous_fallback_count:,} anonymous mesh texture preview(s) to ordered sidecar material wrapper(s)."
        )
    if identity_override_count > 0:
        info_lines.append(
            f"Selected {identity_override_count:,} sidecar base texture preview(s) over embedded material primitive/identity name(s)."
        )
    if low_authority_layer_override_count > 0:
        info_lines.append(
            f"Promoted {low_authority_layer_override_count:,} sidecar visible layer texture preview(s) over low-detail overlay/default base(s)."
        )
    if material_color_fallback_count > 0:
        info_lines.append(
            f"Applied {material_color_fallback_count:,} sidecar material color fallback(s) where the visible base DDS was missing or low confidence."
        )
    return info_lines


def _attach_model_texture_preview_paths(
    texconv_path: Optional[Path],
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

    resolved_texconv_path = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    preview_cache: Dict[str, str] = {}
    resolved_count = 0
    unresolved_lookup_count = 0
    technical_skip_count = 0
    preview_failure_count = 0
    sidecar_bound_count = 0
    override_count = 0
    unresolved_lookup_names: List[str] = []
    technical_skip_names: List[str] = []
    preview_failure_names: List[str] = []
    force_unflipped_preview = str(getattr(source_entry, "extension", "") or "").lower() == ".pac"

    for mesh in model_preview.meshes:
        raise_if_cancelled(stop_event)
        existing_preview_path = str(getattr(mesh, "preview_texture_path", "") or "").strip()
        texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        material_name = str(getattr(mesh, "material_name", "") or "").strip()
        if override_existing_base:
            existing_source = str(getattr(mesh, "preview_base_texture_source", "") or "").strip().lower()
            has_material_name_base_lookup = (
                prefer_material_name_for_base
                and bool(material_name)
                and not material_name.lower().endswith(".dds")
            )
            has_embedded_base_lookup = has_material_name_base_lookup or (
                prefer_material_name_for_base
                and bool(texture_name)
                and texture_name.lower().endswith(".dds")
            )
            if existing_source in {"pami", "pac_xml", "sidecar", "pamlod_xml", "pam_xml"} and not has_embedded_base_lookup:
                continue
        if existing_preview_path and not override_existing_base:
            resolved_count += 1
            sidecar_bound_count += 1
            continue
        lookup_texture_name = texture_name
        lookup_material_name = material_name
        if override_existing_base and prefer_material_name_for_base and material_name and not material_name.lower().endswith(".dds"):
            lookup_texture_name = ""
            lookup_material_name = material_name
        lookup_attempts = [(lookup_texture_name, lookup_material_name)]
        if (
            override_existing_base
            and prefer_material_name_for_base
            and lookup_texture_name == ""
            and texture_name
        ):
            lookup_attempts.append((texture_name, material_name))
        texture_label = lookup_texture_name or lookup_material_name or texture_name
        if not texture_label:
            continue

        texture_entry: Optional[ArchiveEntry] = None
        resolution_status = "missing"
        for attempt_texture_name, attempt_material_name in lookup_attempts:
            texture_entry, resolution_status = _resolve_model_texture_archive_entry(
                source_entry,
                attempt_texture_name,
                attempt_material_name,
                texture_entries_by_normalized_path,
                texture_entries_by_basename,
                sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                sidecar_texts_by_basename=sidecar_texts_by_basename,
            )
            if texture_entry is not None:
                break
        if texture_entry is None:
            if resolution_status == "technical_only":
                technical_skip_count += 1
                if texture_label not in technical_skip_names and len(technical_skip_names) < 5:
                    technical_skip_names.append(texture_label)
            else:
                unresolved_lookup_count += 1
                if texture_label not in unresolved_lookup_names and len(unresolved_lookup_names) < 5:
                    unresolved_lookup_names.append(texture_label)
            continue

        cache_key = _normalize_model_texture_reference(texture_entry.path)
        preview_path_text = preview_cache.get(cache_key, "")
        if not preview_path_text:
            try:
                preview_path_text = _archive_core()._ensure_archive_model_texture_preview_path(
                    resolved_texconv_path,
                    texture_entry,
                    stop_event=stop_event,
                )
                preview_cache[cache_key] = preview_path_text
            except RunCancelled:
                raise
            except Exception:
                preview_failure_count += 1
                if texture_label not in preview_failure_names and len(preview_failure_names) < 5:
                    preview_failure_names.append(texture_label)
                continue

        if str(getattr(mesh, "preview_texture_path", "") or "").strip() != preview_path_text:
            mesh.preview_texture_path = preview_path_text
            mesh.preview_texture_image = None
        mesh.preview_base_texture_quality = _model_preview_base_texture_quality(texture_entry.path)
        if force_unflipped_preview:
            mesh.preview_texture_flip_vertical = False
        current_texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        if override_existing_base or not current_texture_name or not current_texture_name.lower().endswith(".dds"):
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
                preview_texture_path=preview_path_text,
                semantic_type="color",
                semantic_subtype="albedo",
                material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                confidence=str(getattr(mesh, "preview_base_texture_source", "") or "embedded mesh").strip(),
                visualized=True,
            ),
        )
        if (
            existing_preview_path
            and override_existing_base
            and _normalize_model_texture_reference(existing_preview_path)
            != _normalize_model_texture_reference(preview_path_text)
        ):
            override_count += 1
        resolved_count += 1

    info_lines: List[str] = []
    if resolved_count > 0:
        if override_count > 0:
            info_lines.append(
                f"Corrected {override_count:,} mesh base texture preview(s) so embedded material names override sidecar overlay/detail fallback."
            )
        elif override_existing_base:
            pass
        elif sidecar_bound_count > 0 and sidecar_bound_count >= resolved_count:
            info_lines.append(
                f"Resolved {resolved_count:,} mesh texture preview(s) for textured shading and export using sidecar-aware material bindings."
            )
        elif sidecar_bound_count > 0:
            info_lines.append(
                f"Resolved {resolved_count:,} mesh texture preview(s) for textured shading and export "
                f"({sidecar_bound_count:,} via sidecar-aware bindings, remaining matches via semantic base-color fallback)."
            )
        else:
            info_lines.append(
                f"Resolved {resolved_count:,} mesh texture preview(s) for textured shading and export using semantic base-color selection only."
            )
    if unresolved_lookup_count > 0 and not override_existing_base:
        lookup_suffix = f" Examples: {', '.join(unresolved_lookup_names)}." if unresolved_lookup_names else ""
        info_lines.append(
            f"{unresolved_lookup_count:,} embedded material base name(s) had no direct visible DDS match; "
            f"sidecar layer bindings may still provide a preview fallback.{lookup_suffix}"
        )
    if technical_skip_count > 0 and not override_existing_base:
        technical_suffix = f" Examples: {', '.join(technical_skip_names)}." if technical_skip_names else ""
        info_lines.append(
            f"{technical_skip_count:,} mesh texture reference(s) were skipped because only technical DDS matches were found.{technical_suffix}"
        )
    if preview_failure_count > 0:
        failure_suffix = f" Examples: {', '.join(preview_failure_names)}." if preview_failure_names else ""
        info_lines.append(
            f"{preview_failure_count:,} resolved texture(s) failed during DDS-to-PNG preview generation.{failure_suffix}"
        )
    return info_lines


def _attach_model_support_texture_preview_paths(
    texconv_path: Optional[Path],
    source_entry: ArchiveEntry,
    model_preview: Optional[ModelPreviewData],
    *,
    parsed_mesh: Optional[object] = None,
    sidecar_texture_bindings: Sequence[_ArchiveModelSidecarTextureBinding] = (),
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
    support_slots: Sequence[str] = ("normal", "material", "height"),
    stop_event: Optional[threading.Event] = None,
) -> List[str]:
    if model_preview is None or not model_preview.meshes:
        return []

    parsed_submeshes = _iter_parsed_model_submeshes(parsed_mesh)
    resolved_texconv_path = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    preview_cache: Dict[str, str] = {}
    requested_support_slots = {
        str(slot or "").strip().lower()
        for slot in (support_slots or ())
    }
    support_slots = tuple(
        slot
        for slot in ("normal", "material", "height")
        if slot in requested_support_slots
    )
    if not support_slots:
        return []
    slot_labels = {
        "normal": "normal-map",
        "material": "material-mask",
        "height": "height/displacement",
    }
    exact_assigned_by_slot: Dict[str, int] = {slot: 0 for slot in support_slots}
    fallback_assigned_by_slot: Dict[str, int] = {slot: 0 for slot in support_slots}
    exact_examples: Dict[str, List[str]] = {slot: [] for slot in support_slots}
    fallback_examples: Dict[str, List[str]] = {slot: [] for slot in support_slots}
    exact_sidecar_paths: List[str] = []
    force_unflipped_preview = str(getattr(source_entry, "extension", "") or "").lower() == ".pac"
    slot_hints = (
        ("normal", "normal"),
        ("material", "material"),
        ("height", "height"),
    )
    ordered_support_keys_by_slot: Dict[str, Dict[str, int]] = {slot: {} for slot in support_slots}
    ordered_anonymous_assigned_by_slot: Dict[str, int] = {slot: 0 for slot in support_slots}

    def _lookup_sidecar_texts(texture_path: str) -> Tuple[str, ...]:
        normalized_path = normalize_texture_reference_for_sidecar_lookup(texture_path)
        if sidecar_texts_by_normalized_path is not None and normalized_path:
            sidecar_texts = tuple(sidecar_texts_by_normalized_path.get(normalized_path, ()))
            if sidecar_texts:
                return sidecar_texts
        if sidecar_texts_by_basename is not None:
            basename = PurePosixPath(texture_path.replace("\\", "/")).name.lower()
            if basename:
                return tuple(sidecar_texts_by_basename.get(basename, ()))
        return ()

    def _preview_path_for_entry(texture_entry: ArchiveEntry, *, slot_kind: str = "base") -> str:
        slot_key = str(slot_kind or "base").strip().lower()
        cache_key = f"{_normalize_model_texture_reference(texture_entry.path)}|{slot_key}"
        preview_path_text = preview_cache.get(cache_key, "")
        if preview_path_text:
            return preview_path_text
        preview_path_text = _archive_core()._ensure_archive_model_texture_preview_path(
            resolved_texconv_path,
            texture_entry,
            max_dimension=_MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION,
            slot_kind=slot_key,
            stop_event=stop_event,
        )
        preview_cache[cache_key] = preview_path_text
        return preview_path_text

    def _record_slot_example(target: Dict[str, List[str]], slot_name: str, texture_path: str) -> None:
        examples = target[slot_name]
        basename = PurePosixPath(texture_path.replace("\\", "/")).name
        if basename and basename not in examples and len(examples) < 3:
            examples.append(basename)

    def _assign_support_slot(
        mesh: ModelPreviewMesh,
        slot_name: str,
        texture_entry: ArchiveEntry,
        *,
        semantic_hint: str,
    ) -> bool:
        preview_path_text = _preview_path_for_entry(texture_entry, slot_kind=slot_name)
        semantic_type = ""
        semantic_subtype = ""
        packed_channels: Tuple[str, ...] = ()
        if slot_name == "material":
            sidecar_texts = _lookup_sidecar_texts(texture_entry.path)
            semantic_type, semantic_subtype, _confidence, packed_channels = _resolve_model_texture_semantic_details(
                texture_entry.path,
                sidecar_texts=sidecar_texts,
            )
            semantic_type, semantic_subtype = _refine_model_texture_semantic_from_hint(
                semantic_type,
                semantic_subtype,
                semantic_hint,
            )
        changed = _set_model_preview_texture_slot(
            mesh,
            slot=slot_name,
            preview_path=preview_path_text,
            texture_path=texture_entry.path,
            normal_strength=(
                _infer_model_preview_normal_strength(
                    base_texture_path=str(getattr(mesh, "texture_name", "") or "").strip(),
                    normal_texture_path=texture_entry.path,
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    semantic_hint=semantic_hint,
                    prefer_stronger=False,
                )
                if slot_name == "normal"
                else None
            ),
            semantic_type=semantic_type,
            semantic_subtype=semantic_subtype,
            packed_channels=packed_channels,
        )
        if changed and force_unflipped_preview:
            mesh.preview_texture_flip_vertical = False
        return changed

    exact_resolved_by_submesh: Dict[Tuple[str, str], Tuple[Tuple[int, int, int, int], ArchiveEntry, str, str]] = {}
    exact_material_inputs_by_submesh: Dict[str, List[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding]]] = defaultdict(list)
    exact_global_bindings: Dict[str, List[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, str]]] = defaultdict(list)
    seen_exact_global_keys: set[Tuple[str, str, str]] = set()
    preserved_extra_material_input_count = 0
    culled_extra_material_input_count = 0

    def _remember_exact_material_input(
        submesh_key: str,
        candidate_key: Tuple[int, int, int, int],
        texture_entry: ArchiveEntry,
        parameter_name: str,
        binding: _ArchiveModelSidecarTextureBinding,
    ) -> None:
        normalized_submesh_key = str(submesh_key or "").strip()
        if not normalized_submesh_key:
            return
        normalized_texture = _normalize_model_texture_reference(texture_entry.path)
        normalized_parameter = str(parameter_name or "").strip().lower()
        bucket = exact_material_inputs_by_submesh[normalized_submesh_key]
        for _existing_key, existing_entry, existing_parameter, _existing_binding in bucket:
            if (
                _normalize_model_texture_reference(existing_entry.path) == normalized_texture
                and str(existing_parameter or "").strip().lower() == normalized_parameter
            ):
                return
        bucket.append((candidate_key, texture_entry, parameter_name, binding))

    def _append_exact_material_input(
        mesh: ModelPreviewMesh,
        texture_entry: ArchiveEntry,
        parameter_name: str,
        binding: _ArchiveModelSidecarTextureBinding,
    ) -> bool:
        preview_path_text = _preview_path_for_entry(texture_entry, slot_kind="material")
        sidecar_texts = _lookup_sidecar_texts(texture_entry.path)
        semantic_type, semantic_subtype, _confidence, packed_channels = _resolve_model_texture_semantic_details(
            texture_entry.path,
            sidecar_texts=sidecar_texts,
        )
        semantic_type, semantic_subtype = _refine_model_texture_semantic_from_hint(
            semantic_type,
            semantic_subtype,
            parameter_name,
        )
        return _append_model_preview_material_input(
            mesh,
            PreviewMaterialTextureInput(
                slot_kind="material",
                parameter_name=str(parameter_name or "").strip(),
                source_texture_path=texture_entry.path,
                source_dds_path=texture_entry.path,
                texture_name=PurePosixPath(texture_entry.path.replace("\\", "/")).name,
                preview_texture_path=preview_path_text,
                semantic_type=str(semantic_type or "material").strip().lower(),
                semantic_subtype=str(semantic_subtype or "").strip().lower(),
                packed_channels=tuple(
                    str(channel or "").strip().lower()
                    for channel in packed_channels
                    if str(channel or "").strip()
                ),
                material_name=(
                    str(getattr(binding, "material_name", "") or "").strip()
                    or str(getattr(binding, "submesh_name", "") or "").strip()
                    or str(getattr(mesh, "material_name", "") or "").strip()
                ),
                part_name=str(getattr(binding, "part_name", "") or "").strip(),
                shader_family=str(getattr(binding, "shader_family", "") or "").strip(),
                confidence="sidecar-exact",
                visualized=True,
                sidecar_kind=str(getattr(binding, "sidecar_kind", "") or "").strip(),
                sidecar_path=str(getattr(binding, "sidecar_path", "") or "").strip(),
                linked_mesh_path=str(getattr(binding, "linked_mesh_path", "") or "").strip(),
                srgb_mode=str(getattr(binding, "srgb_mode", "") or "").strip(),
                parameter_declared_by=str(getattr(binding, "parameter_declared_by", "") or "").strip(),
                material_output_quality=str(getattr(binding, "material_output_quality", "") or "").strip(),
                layer_role=str(getattr(binding, "layer_role", "") or "").strip(),
                layer_channel=str(getattr(binding, "layer_channel", "") or "").strip(),
                blend_flags=tuple(str(value) for value in tuple(getattr(binding, "blend_flags", ()) or ()) if str(value)),
                material_parameters=tuple(getattr(binding, "material_parameters", ()) or ()),
            ),
        )

    def _material_input_preserve_group(parameter_name: str, texture_path: str) -> str:
        parameter_key = re.sub(r"[^a-z0-9]+", "", str(parameter_name or "").lower())
        stem = PurePosixPath(str(texture_path or "").replace("\\", "/")).stem.lower()
        if any(token in parameter_key for token in ("layerbasecolor", "detaildiffuse", "grimediffuse", "damageblendingdiffuse")):
            return "visible_layer"
        if any(token in parameter_key for token in ("basecolor", "overlaycolor")):
            return "visible_base"
        if "colorblendingmask" in parameter_key or stem.endswith("_ma") or stem.endswith("_mask"):
            return "mask"
        if "detailmask" in parameter_key or stem.endswith("_mg"):
            return "detail_mask"
        if "specular" in parameter_key or stem.endswith("_sp"):
            return "specular"
        if "grime" in parameter_key:
            return "grime"
        if "damage" in parameter_key:
            return "damage"
        if "skin" in parameter_key:
            return "skin"
        if "material" in parameter_key or stem.endswith("_m"):
            return "material"
        return "other"

    def _preserve_visible_material_input(parameter_name: str) -> bool:
        parameter_key = re.sub(r"[^a-z0-9]+", "", str(parameter_name or "").lower())
        return any(
            token in parameter_key
            for token in (
                "layerbasecolor",
                "detaildiffuse",
                "grimediffuse",
                "damageblendingdiffuse",
                "overlaycolor",
                "basecolor",
            )
        )

    def _candidate_material_input_identity(
        candidate: Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding]
    ) -> Tuple[str, str]:
        _candidate_key, texture_entry, parameter_name, _binding = candidate
        return (
            _normalize_model_texture_reference(texture_entry.path),
            str(parameter_name or "").strip().lower(),
        )

    def _select_rich_material_input_candidates(
        candidates: Sequence[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding]]
    ) -> Tuple[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding], ...]:
        if not candidates:
            return ()
        limit = 5
        ordered = sorted(candidates, key=lambda item: item[0], reverse=True)
        selected: List[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding]] = []
        selected_identities: set[Tuple[str, str]] = set()
        selected_groups: set[str] = set()
        for candidate in ordered:
            _candidate_key, texture_entry, parameter_name, _binding = candidate
            group = _material_input_preserve_group(parameter_name, texture_entry.path)
            identity = _candidate_material_input_identity(candidate)
            if identity in selected_identities or group in selected_groups:
                continue
            selected.append(candidate)
            selected_identities.add(identity)
            selected_groups.add(group)
            if len(selected) >= limit:
                return tuple(selected)
        for candidate in ordered:
            identity = _candidate_material_input_identity(candidate)
            if identity in selected_identities:
                continue
            selected.append(candidate)
            selected_identities.add(identity)
            if len(selected) >= limit:
                break
        return tuple(selected)

    for binding in sidecar_texture_bindings:
        raise_if_cancelled(stop_event)
        if not _model_sidecar_binding_matches_source_component(source_entry, binding):
            continue
        parameter_name = str(binding.parameter_name or "").strip()
        slot_name = _infer_model_preview_texture_slot("", semantic_hint=parameter_name)
        preserve_visible_input = slot_name == "base" and _preserve_visible_material_input(parameter_name)
        if slot_name not in support_slots and not preserve_visible_input:
            continue
        submesh_keys = _iter_model_sidecar_binding_submesh_keys(binding)
        texture_entry, resolution_status = _resolve_model_texture_archive_entry(
            source_entry,
            binding.texture_path,
            binding.submesh_name,
            texture_entries_by_normalized_path,
            texture_entries_by_basename,
            semantic_hint=parameter_name,
            expand_family_candidates=False,
            allow_technical_match=True,
            preferred_slot=slot_name,
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
        )
        if texture_entry is None or resolution_status != "resolved":
            continue
        sidecar_texts = _lookup_sidecar_texts(texture_entry.path)
        texture_type, semantic_subtype, confidence = _resolve_model_texture_semantics(
            texture_entry.path,
            sidecar_texts=sidecar_texts,
        )
        if preserve_visible_input:
            slot_priority = (8, 0)
        else:
            slot_priority = (
                _model_texture_slot_hint_priority(slot_name, parameter_name)
                or _model_texture_candidate_slot_priority(slot_name, texture_entry.path, sidecar_texts=sidecar_texts)
            )
        if slot_priority is None:
            continue
        candidate_key = (
            slot_priority[0],
            slot_priority[1],
            confidence,
            -len(texture_entry.path),
        )
        if submesh_keys:
            primary_sidecar_key = submesh_keys[0]
            if primary_sidecar_key:
                ordered_support_keys_by_slot.setdefault(slot_name, {}).setdefault(
                    primary_sidecar_key,
                    len(ordered_support_keys_by_slot.setdefault(slot_name, {})),
                )
            for submesh_key in submesh_keys:
                resolved_key = (slot_name, submesh_key)
                if slot_name == "material" or preserve_visible_input:
                    _remember_exact_material_input(
                        submesh_key,
                        candidate_key,
                        texture_entry,
                        parameter_name,
                        binding,
                    )
                if preserve_visible_input:
                    continue
                existing = exact_resolved_by_submesh.get(resolved_key)
                if existing is None or candidate_key > existing[0]:
                    exact_resolved_by_submesh[resolved_key] = (
                        candidate_key,
                        texture_entry,
                        parameter_name,
                        binding.submesh_name,
                )
        else:
            if preserve_visible_input:
                continue
            global_key = (
                slot_name,
                _normalize_model_texture_reference(texture_entry.path),
                parameter_name.lower(),
            )
            if global_key not in seen_exact_global_keys:
                seen_exact_global_keys.add(global_key)
                exact_global_bindings[slot_name].append(
                    (
                        candidate_key,
                        texture_entry,
                        parameter_name,
                        binding.submesh_name,
                    )
                )
        if binding.sidecar_path and binding.sidecar_path not in exact_sidecar_paths:
            exact_sidecar_paths.append(binding.sidecar_path)

    support_prefetch_requests: List[Tuple[ArchiveEntry, str, int]] = []
    support_max_dimension = int(_MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)
    for (slot_name, _submesh_key), (_candidate_key, texture_entry, _parameter_name, _submesh_name) in exact_resolved_by_submesh.items():
        support_prefetch_requests.append((texture_entry, slot_name, support_max_dimension))
    for slot_name, bindings in exact_global_bindings.items():
        for _candidate_key, texture_entry, _parameter_name, _submesh_name in bindings:
            support_prefetch_requests.append((texture_entry, slot_name, support_max_dimension))
    for candidates in exact_material_inputs_by_submesh.values():
        for _candidate_key, texture_entry, _parameter_name, _binding in _select_rich_material_input_candidates(candidates):
            support_prefetch_requests.append((texture_entry, "material", support_max_dimension))
    _prefetch_archive_model_texture_preview_paths(
        resolved_texconv_path,
        support_prefetch_requests,
        preview_cache,
        stop_event=stop_event,
    )

    for mesh_index, mesh in enumerate(model_preview.meshes):
        raise_if_cancelled(stop_event)
        parsed_submesh = parsed_submeshes[mesh_index] if mesh_index < len(parsed_submeshes) else None
        candidate_keys = _iter_model_submesh_reference_candidates(
            str(getattr(parsed_submesh, "name", "") or ""),
            str(getattr(parsed_submesh, "material", "") or ""),
            str(getattr(parsed_submesh, "texture", "") or ""),
            str(getattr(mesh, "material_name", "") or ""),
            str(getattr(mesh, "texture_name", "") or ""),
        )
        seen_rich_material_keys: set[Tuple[str, str]] = set()
        rich_material_candidates: List[
            Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding]
        ] = []
        for candidate_key_text in candidate_keys:
            for _candidate_key, texture_entry, parameter_name, binding in sorted(
                exact_material_inputs_by_submesh.get(candidate_key_text, ()),
                key=lambda item: item[0],
                reverse=True,
            ):
                rich_key = (
                    _normalize_model_texture_reference(texture_entry.path),
                    str(parameter_name or "").strip().lower(),
                )
                if rich_key in seen_rich_material_keys:
                    continue
                seen_rich_material_keys.add(rich_key)
                rich_material_candidates.append((_candidate_key, texture_entry, parameter_name, binding))
        selected_rich_material_candidates = _select_rich_material_input_candidates(rich_material_candidates)
        culled_extra_material_input_count += max(
            0,
            len(rich_material_candidates) - len(selected_rich_material_candidates),
        )
        for _candidate_key, texture_entry, parameter_name, binding in selected_rich_material_candidates:
            try:
                if _append_exact_material_input(mesh, texture_entry, parameter_name, binding):
                    preserved_extra_material_input_count += 1
            except RunCancelled:
                raise
            except Exception:
                continue
        for slot_name in support_slots:
            existing_preview_path = str(getattr(mesh, f"preview_{slot_name}_texture_path", "") or "").strip()
            if existing_preview_path:
                continue
            best_match: Optional[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, str]] = None
            for candidate_key_text in candidate_keys:
                resolved = exact_resolved_by_submesh.get((slot_name, candidate_key_text))
                if resolved is None:
                    continue
                if best_match is None or resolved[0] > best_match[0]:
                    best_match = resolved
            if best_match is None:
                continue
            _candidate_key, texture_entry, parameter_name, _submesh_name = best_match
            try:
                if _assign_support_slot(mesh, slot_name, texture_entry, semantic_hint=parameter_name):
                    exact_assigned_by_slot[slot_name] += 1
                    _record_slot_example(exact_examples, slot_name, texture_entry.path)
            except RunCancelled:
                raise
            except Exception:
                continue

    for slot_name in support_slots:
        ordered_keys = ordered_support_keys_by_slot.get(slot_name, {})
        if len(ordered_keys) <= 1:
            continue
        ordered_bindings = [
            exact_resolved_by_submesh.get((slot_name, key))
            for key, _order in sorted(ordered_keys.items(), key=lambda item: item[1])
        ]
        if not any(ordered_bindings):
            continue
        for mesh_index, mesh in enumerate(model_preview.meshes):
            raise_if_cancelled(stop_event)
            existing_preview_path = str(getattr(mesh, f"preview_{slot_name}_texture_path", "") or "").strip()
            if existing_preview_path or mesh_index >= len(ordered_bindings):
                continue
            ordered_binding = ordered_bindings[mesh_index]
            if ordered_binding is None:
                continue
            _candidate_key, texture_entry, parameter_name, _submesh_name = ordered_binding
            try:
                if _assign_support_slot(mesh, slot_name, texture_entry, semantic_hint=parameter_name):
                    exact_assigned_by_slot[slot_name] += 1
                    ordered_anonymous_assigned_by_slot[slot_name] += 1
                    _record_slot_example(exact_examples, slot_name, texture_entry.path)
            except RunCancelled:
                raise
            except Exception:
                continue

    for slot_name in support_slots:
        global_bindings = exact_global_bindings.get(slot_name, [])
        if not global_bindings:
            continue
        global_bindings.sort(key=lambda item: item[0], reverse=True)
        unresolved_meshes = [
            mesh
            for mesh in model_preview.meshes
            if not str(getattr(mesh, f"preview_{slot_name}_texture_path", "") or "").strip()
        ]
        if not unresolved_meshes:
            continue
        if len(global_bindings) == 1:
            _candidate_key, texture_entry, parameter_name, _submesh_name = global_bindings[0]
            for mesh in unresolved_meshes:
                raise_if_cancelled(stop_event)
                try:
                    if _assign_support_slot(mesh, slot_name, texture_entry, semantic_hint=parameter_name):
                        exact_assigned_by_slot[slot_name] += 1
                        _record_slot_example(exact_examples, slot_name, texture_entry.path)
                except RunCancelled:
                    raise
                except Exception:
                    continue
        else:
            binding_index = 0
            for mesh in unresolved_meshes:
                raise_if_cancelled(stop_event)
                if binding_index >= len(global_bindings):
                    break
                _candidate_key, texture_entry, parameter_name, _submesh_name = global_bindings[binding_index]
                binding_index += 1
                try:
                    if _assign_support_slot(mesh, slot_name, texture_entry, semantic_hint=parameter_name):
                        exact_assigned_by_slot[slot_name] += 1
                        _record_slot_example(exact_examples, slot_name, texture_entry.path)
                except RunCancelled:
                    raise
                except Exception:
                    continue

    for mesh in model_preview.meshes:
        raise_if_cancelled(stop_event)
        reference_texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        reference_material_name = str(getattr(mesh, "material_name", "") or "").strip()
        if not reference_texture_name and not reference_material_name:
            continue
        for slot_name, semantic_hint in slot_hints:
            existing_preview_path = str(getattr(mesh, f"preview_{slot_name}_texture_path", "") or "").strip()
            if existing_preview_path:
                continue
            texture_entry, resolution_status = _resolve_model_texture_archive_entry(
                source_entry,
                reference_texture_name,
                reference_material_name,
                texture_entries_by_normalized_path,
                texture_entries_by_basename,
                semantic_hint=semantic_hint,
                allow_technical_match=True,
                preferred_slot=slot_name,
                sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                sidecar_texts_by_basename=sidecar_texts_by_basename,
            )
            if texture_entry is None or resolution_status != "resolved":
                continue
            try:
                if _assign_support_slot(mesh, slot_name, texture_entry, semantic_hint=semantic_hint):
                    fallback_assigned_by_slot[slot_name] += 1
                    _record_slot_example(fallback_examples, slot_name, texture_entry.path)
            except RunCancelled:
                raise
            except Exception:
                continue

    info_lines: List[str] = []
    exact_total = sum(exact_assigned_by_slot.values())
    fallback_total = sum(fallback_assigned_by_slot.values())
    if exact_total > 0:
        sidecar_suffix = f" from {', '.join(exact_sidecar_paths[:2])}" if exact_sidecar_paths else ""
        if len(exact_sidecar_paths) > 2:
            sidecar_suffix += " ..."
        info_lines.append(
            f"Applied {exact_total:,} exact high-quality support-map binding(s) from companion material sidecar data{sidecar_suffix}."
        )
        for slot_name in support_slots:
            count = exact_assigned_by_slot[slot_name]
            if count <= 0:
                continue
            suffix = f" Examples: {', '.join(exact_examples[slot_name])}." if exact_examples[slot_name] else ""
            info_lines.append(
                f"Exact sidecar {slot_labels[slot_name]} bindings: {count:,}.{suffix}"
            )
    if preserved_extra_material_input_count > 0:
        info_lines.append(
            f"Preserved {preserved_extra_material_input_count:,} exact sidecar material texture input(s) for material diagnostics and preview."
        )
    if culled_extra_material_input_count > 0:
        info_lines.append(
            f"Skipped {culled_extra_material_input_count:,} lower-priority sidecar material texture input(s) before preview conversion to keep model loading responsive."
        )
    ordered_total = sum(ordered_anonymous_assigned_by_slot.values())
    if ordered_total > 0:
        ordered_parts = [
            f"{slot_name[0]}:{ordered_anonymous_assigned_by_slot[slot_name]:,}"
            for slot_name in support_slots
            if ordered_anonymous_assigned_by_slot[slot_name] > 0
        ]
        info_lines.append(
            "Matched "
            f"{ordered_total:,} anonymous support-map binding(s) to ordered sidecar material wrapper(s)"
            + (f" ({', '.join(ordered_parts)})." if ordered_parts else ".")
        )
    if fallback_total > 0:
        info_lines.append(
            f"Applied {fallback_total:,} semantic sibling high-quality support-map binding(s) using slot-correct family fallback."
        )
        for slot_name in support_slots:
            count = fallback_assigned_by_slot[slot_name]
            if count <= 0:
                continue
            suffix = f" Examples: {', '.join(fallback_examples[slot_name])}." if fallback_examples[slot_name] else ""
            info_lines.append(
                f"Semantic sibling {slot_labels[slot_name]} bindings: {count:,}.{suffix}"
            )
    if exact_total <= 0 and fallback_total <= 0:
        has_textured_mesh = any(
            str(getattr(mesh, "texture_name", "") or "").strip()
            or str(getattr(mesh, "preview_texture_path", "") or "").strip()
            for mesh in model_preview.meshes
        )
        if has_textured_mesh:
            info_lines.append(
                "No usable high-quality support maps were resolved from exact sidecar bindings or semantic sibling fallback. The preview remains base-texture only."
            )
    return info_lines


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
    related_companion_entries = (
        _find_archive_model_related_entries(source_entry, texture_entries_by_basename)
        if texture_entries_by_basename is not None
        else ()
    )

    if (
        not preview_meshes
        and not parsed_submeshes
        and not binary_texture_references
        and not sidecar_texture_references
        and not related_companion_entries
    ):
        return []

    references: Dict[Tuple[str, ...], ArchiveModelTextureReference] = {}
    ordered_keys: List[Tuple[str, ...]] = []

    for related_entry in related_companion_entries:
        related_key = ("sidecar", _normalize_model_texture_reference(related_entry.path))
        if related_key in references:
            continue
        relation_kind, relation_group, relation_confidence, relation_reason = _build_archive_relation_metadata(
            source_entry,
            resolved_entry=related_entry,
        )
        references[related_key] = ArchiveModelTextureReference(
            reference_name=PurePosixPath(related_entry.path.replace("\\", "/")).name,
            semantic_label=_describe_model_related_file_label(related_entry),
            resolution_status="resolved",
            resolved_archive_path=related_entry.path,
            resolved_package_label=related_entry.package_label,
            resolved_entry=related_entry,
            usage_count=1,
            reference_kind=relation_kind,
            relation_group=relation_group,
            relation_reason=relation_reason,
            relation_confidence=relation_confidence,
        )
        ordered_keys.append(related_key)

    candidates: List[Tuple[str, str, str, str, Optional[object]]] = []
    seen_candidate_keys: set[Tuple[str, str, str]] = set()
    for binding in sidecar_texture_references:
        texture_name = str(binding.texture_path or "").strip()
        material_name = str(
            getattr(binding, "part_name", "")
            or getattr(binding, "material_name", "")
            or binding.submesh_name
            or binding.parameter_name
            or ""
        ).strip()
        semantic_hint = str(binding.parameter_name or "").strip()
        key = (
            _normalize_model_texture_reference(texture_name),
            _normalize_model_texture_reference(material_name),
            str(semantic_hint or "").strip().lower(),
        )
        if not texture_name or key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        candidates.append((texture_name, material_name, "", semantic_hint, binding))
    for mesh in preview_meshes:
        texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        material_name = str(getattr(mesh, "material_name", "") or "").strip()
        key = (
            _normalize_model_texture_reference(texture_name),
            _normalize_model_texture_reference(material_name),
            "",
        )
        seen_candidate_keys.add(key)
        candidates.append(
            (
                texture_name,
                material_name,
                str(getattr(mesh, "preview_texture_path", "") or "").strip(),
                "",
                None,
            )
        )
    for submesh in parsed_submeshes:
        texture_name = str(getattr(submesh, "texture", "") or "").strip()
        material_name = str(getattr(submesh, "material", "") or "").strip()
        key = (
            _normalize_model_texture_reference(texture_name),
            _normalize_model_texture_reference(material_name),
            "",
        )
        if key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        candidates.append((texture_name, material_name, "", "", None))
    for raw_reference in binary_texture_references:
        texture_name = str(raw_reference or "").strip()
        if not texture_name:
            continue
        key = (_normalize_model_texture_reference(texture_name), "", "")
        if key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        candidates.append((texture_name, "", "", "", None))

    for texture_name, material_name, preview_texture_path, semantic_hint, sidecar_binding in candidates:
        reference_name = texture_name or material_name
        if not reference_name:
            continue

        texture_entry, resolution_status = _resolve_model_texture_archive_entry(
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
        resolved_archive_path = texture_entry.path if texture_entry is not None else ""
        reference_key_value = _normalize_model_texture_reference(resolved_archive_path or reference_name)
        if sidecar_binding is not None:
            key = (
                "texture",
                reference_key_value,
                _normalize_model_texture_reference(material_name),
                str(semantic_hint or "").strip().lower(),
                str(getattr(sidecar_binding, "sidecar_kind", "") or "").strip().lower(),
            )
        else:
            key = ("texture", reference_key_value)
        sidecar_texts: Tuple[str, ...] = ()
        normalized_reference_path = normalize_texture_reference_for_sidecar_lookup(resolved_archive_path or reference_name)
        if sidecar_texts_by_normalized_path is not None and normalized_reference_path:
            sidecar_texts = tuple(sidecar_texts_by_normalized_path.get(normalized_reference_path, ()))
        if not sidecar_texts and sidecar_texts_by_basename is not None:
            reference_basename = PurePosixPath(
                (resolved_archive_path or reference_name).replace("\\", "/")
            ).name.lower()
            if reference_basename:
                sidecar_texts = tuple(sidecar_texts_by_basename.get(reference_basename, ()))
        semantic_label = _describe_model_texture_semantic_label(
            resolved_archive_path or reference_name,
            semantic_hint=semantic_hint,
            sidecar_texts=sidecar_texts,
        )
        sidecar_kind = str(getattr(sidecar_binding, "sidecar_kind", "") or "").strip()
        linked_mesh_path = str(getattr(sidecar_binding, "linked_mesh_path", "") or "").strip()
        part_name = str(getattr(sidecar_binding, "part_name", "") or "").strip()
        shader_family = str(getattr(sidecar_binding, "shader_family", "") or "").strip()
        texture_role = str(getattr(sidecar_binding, "texture_role", "") or "").strip()
        visualization_state = str(getattr(sidecar_binding, "visualization_state", "") or "").strip()
        resolved_package_label = texture_entry.package_label if texture_entry is not None else ""
        relation_confidence, relation_reason = _texture_reference_relation_metadata(
            source_entry,
            reference_name,
            texture_entry,
            semantic_hint=semantic_hint,
        )
        existing = references.get(key)
        if existing is None:
            references[key] = ArchiveModelTextureReference(
                reference_name=reference_name,
                material_name=material_name,
                semantic_label=semantic_label,
                semantic_hint=semantic_hint,
                sidecar_parameter_name=semantic_hint,
                sidecar_kind=sidecar_kind,
                linked_mesh_path=linked_mesh_path,
                part_name=part_name,
                shader_family=shader_family,
                texture_role=texture_role,
                visualization_state=visualization_state,
                sidecar_texts=sidecar_texts,
                resolution_status=resolution_status,
                resolved_archive_path=resolved_archive_path,
                resolved_package_label=resolved_package_label,
                resolved_entry=texture_entry,
                preview_texture_path=preview_texture_path,
                usage_count=1,
                reference_kind="texture",
                relation_group="Textures",
                relation_reason=relation_reason,
                relation_confidence=relation_confidence,
            )
            ordered_keys.append(key)
            continue

        existing.usage_count += 1
        if material_name and not existing.material_name:
            existing.material_name = material_name
        if preview_texture_path and not existing.preview_texture_path:
            existing.preview_texture_path = preview_texture_path
        if sidecar_kind and not existing.sidecar_kind:
            existing.sidecar_kind = sidecar_kind
        if linked_mesh_path and not existing.linked_mesh_path:
            existing.linked_mesh_path = linked_mesh_path
        if part_name and not existing.part_name:
            existing.part_name = part_name
        if shader_family and not existing.shader_family:
            existing.shader_family = shader_family
        if texture_role and not existing.texture_role:
            existing.texture_role = texture_role
        if visualization_state and not existing.visualization_state:
            existing.visualization_state = visualization_state
        if texture_entry is not None and (
            existing.resolved_entry is None
            or _model_reference_status_rank(resolution_status) > _model_reference_status_rank(existing.resolution_status)
        ):
            existing.resolved_entry = texture_entry
            existing.resolved_archive_path = texture_entry.path
            existing.resolved_package_label = texture_entry.package_label
            existing.resolution_status = resolution_status
        elif _model_reference_status_rank(resolution_status) > _model_reference_status_rank(existing.resolution_status):
            existing.resolution_status = resolution_status
        if semantic_label:
            existing.semantic_label = _merge_model_reference_semantic_label(
                existing.semantic_label,
                semantic_label,
                existing_hint=existing.semantic_hint,
                new_hint=semantic_hint,
            )
        if semantic_hint and semantic_hint != existing.semantic_hint:
            existing.semantic_hint = " | ".join(
                part
                for part in [existing.semantic_hint.strip(), semantic_hint.strip()]
                if part
            )
            if not existing.sidecar_parameter_name:
                existing.sidecar_parameter_name = semantic_hint
        if sidecar_texts:
            merged_sidecar_texts = list(existing.sidecar_texts)
            for text in sidecar_texts:
                if text not in merged_sidecar_texts:
                    merged_sidecar_texts.append(text)
            existing.sidecar_texts = tuple(merged_sidecar_texts)

    return [references[key] for key in ordered_keys]
