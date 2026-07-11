from __future__ import annotations

from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_modding_constants import _MESH_IMPORT_ASSET_ROOT_MARKERS
from cdmw.core.archive_patching import _normalize_virtual_path
from cdmw.models import (
    ArchiveEntry,
    ModelPreviewData,
    ModelPreviewMesh,
)
from cdmw.modding.mesh_parser import ParsedMesh

def _mesh_import_candidate_virtual_paths(source_path: Path) -> Tuple[str, ...]:
    normalized_parts = [part for part in source_path.expanduser().parts if part]
    if not normalized_parts:
        return ()
    lowered_parts = [str(part).strip() for part in normalized_parts]
    ordered: List[str] = []
    seen: set[str] = set()

    def _append(parts: Sequence[str]) -> None:
        candidate = PurePosixPath(*parts).as_posix().strip()
        normalized_candidate = _normalize_virtual_path(candidate)
        if not normalized_candidate or normalized_candidate in seen:
            return
        seen.add(normalized_candidate)
        ordered.append(candidate)

    for index, part in enumerate(lowered_parts):
        if str(part).strip().lower() == "files" and index + 1 < len(lowered_parts):
            _append(lowered_parts[index + 1 :])
            break

    for index, part in enumerate(lowered_parts):
        if str(part).strip().lower() in _MESH_IMPORT_ASSET_ROOT_MARKERS:
            _append(lowered_parts[index:])
            break

    _append([source_path.name])
    return tuple(ordered)

def _mesh_import_loose_texture_preferred_paths(source_path: Path) -> Tuple[str, ...]:
    if source_path.suffix.lower() != ".dds":
        return ()
    if not any(str(part).strip().lower() == "files" for part in source_path.expanduser().parts):
        return ()

    ordered: List[str] = []
    seen: set[str] = set()

    def _append(value: str) -> None:
        normalized = _normalize_virtual_path(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered.append(value.replace("\\", "/"))

    for candidate in _mesh_import_candidate_virtual_paths(source_path):
        parts = tuple(part for part in PurePosixPath(candidate.replace("\\", "/")).parts if part)
        if len(parts) < 2 or parts[0].lower() not in _MESH_IMPORT_ASSET_ROOT_MARKERS:
            continue
        basename = parts[-1]
        if not basename.lower().endswith(".dds"):
            continue
        if len(parts) == 2:
            _append(PurePosixPath(parts[0], "texture", basename).as_posix())
        elif parts[1].lower() in {"texture", "textures"}:
            _append(PurePosixPath(parts[0], "texture", basename).as_posix())
    return tuple(ordered)

def _mesh_import_modelproperty_variant(mesh_path: str) -> str:
    parts = list(PurePosixPath(str(mesh_path or "").replace("\\", "/")).parts)
    for index, part in enumerate(parts):
        if part.lower() == "model":
            parts[index] = "modelproperty"
            return PurePosixPath(*parts).as_posix()
    return ""

def _mesh_import_target_sidecar_candidates_for_base(
    mesh_path: str,
    source_sidecar_path: Path,
) -> Tuple[str, ...]:
    mesh_pure = PurePosixPath(str(mesh_path or "").replace("\\", "/").strip())
    if not mesh_pure.name:
        return ()

    mesh_extension = mesh_pure.suffix.lower()
    source_extension = source_sidecar_path.suffix.lower()
    source_name = source_sidecar_path.name.lower()
    candidates: List[str] = []

    def _append(candidate: PurePosixPath) -> None:
        value = candidate.as_posix().strip()
        if value and value not in candidates:
            candidates.append(value)

    if source_extension in {".pac_xml", ".pam_xml", ".pamlod_xml", ".app_xml", ".prefabdata_xml"}:
        _append(mesh_pure.with_suffix(source_extension))
    elif source_extension == ".pami":
        _append(mesh_pure.with_suffix(".pami"))
    elif source_extension == ".xml":
        if source_name.endswith(".pac.xml") or mesh_extension == ".pac":
            _append(mesh_pure.with_name(f"{mesh_pure.name}.xml"))
            _append(mesh_pure.with_suffix(".pac_xml"))
        elif source_name.endswith(".pam.xml") or mesh_extension == ".pam":
            _append(mesh_pure.with_name(f"{mesh_pure.name}.xml"))
            _append(mesh_pure.with_suffix(".pam_xml"))
        elif source_name.endswith(".pamlod.xml") or mesh_extension == ".pamlod":
            _append(mesh_pure.with_name(f"{mesh_pure.name}.xml"))
            _append(mesh_pure.with_suffix(".pamlod_xml"))
        elif source_name.endswith(".app.xml"):
            _append(mesh_pure.with_suffix(".app_xml"))
        elif source_name.endswith(".prefabdata.xml"):
            _append(mesh_pure.with_suffix(".prefabdata_xml"))
        else:
            _append(mesh_pure.with_suffix(".xml"))
    return tuple(candidates)

def _mesh_import_sidecar_preferred_paths(
    entry: ArchiveEntry,
    source_sidecar_path: Path,
    related_entries_by_extension: Mapping[str, Sequence[ArchiveEntry]],
) -> Tuple[str, ...]:
    source_extension = source_sidecar_path.suffix.lower()
    ordered: List[str] = []
    seen: set[str] = set()

    def _append(value: str) -> None:
        normalized = _normalize_virtual_path(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered.append(str(value).replace("\\", "/"))

    target_names = {
        PurePosixPath(path).name.lower()
        for base_path in (entry.path, _mesh_import_modelproperty_variant(entry.path))
        for path in _mesh_import_target_sidecar_candidates_for_base(base_path, source_sidecar_path)
        if path
    }
    related_by_extension = list(related_entries_by_extension.get(source_extension, ()))
    for related_entry in related_by_extension:
        if PurePosixPath(related_entry.path.replace("\\", "/")).name.lower() in target_names:
            _append(related_entry.path)
    if len(related_by_extension) == 1:
        _append(related_by_extension[0].path)

    modelproperty_path = _mesh_import_modelproperty_variant(entry.path)
    for base_path in (modelproperty_path, entry.path):
        if not base_path:
            continue
        for candidate in _mesh_import_target_sidecar_candidates_for_base(base_path, source_sidecar_path):
            _append(candidate)
    return tuple(ordered)

def _resolve_supplemental_target_entry(
    source_path: Path,
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    preferred_paths: Sequence[str] = (),
) -> Tuple[Optional[ArchiveEntry], str]:
    candidate_virtual_paths: List[str] = []
    seen_virtual_paths: set[str] = set()
    for raw_path in list(preferred_paths) + list(_mesh_import_candidate_virtual_paths(source_path)):
        normalized = _normalize_virtual_path(raw_path)
        if not normalized or normalized in seen_virtual_paths:
            continue
        seen_virtual_paths.add(normalized)
        candidate_virtual_paths.append(raw_path)

    if archive_entries_by_normalized_path is not None:
        for candidate_virtual_path in candidate_virtual_paths:
            normalized = _normalize_virtual_path(candidate_virtual_path)
            entries = archive_entries_by_normalized_path.get(normalized, ())
            if entries:
                return entries[0], candidate_virtual_path.replace("\\", "/")

    basename = source_path.name.lower()
    if archive_entries_by_basename is not None and basename:
        entries = archive_entries_by_basename.get(basename, ())
        if len(entries) == 1:
            return entries[0], entries[0].path

    if candidate_virtual_paths:
        return None, candidate_virtual_paths[0].replace("\\", "/")
    return None, ""

def _build_mesh_import_local_dds_lookup(
    supplemental_files: Sequence[Path],
) -> Tuple[Dict[str, Path], Dict[str, Path]]:
    by_normalized_path: Dict[str, Path] = {}
    by_basename: Dict[str, Path] = {}
    for supplemental_path in supplemental_files:
        if supplemental_path.suffix.lower() != ".dds":
            continue
        resolved_path = supplemental_path.expanduser().resolve()
        for candidate_virtual_path in _mesh_import_candidate_virtual_paths(resolved_path):
            normalized = _normalize_virtual_path(candidate_virtual_path)
            if normalized and normalized not in by_normalized_path:
                by_normalized_path[normalized] = resolved_path
        basename = resolved_path.name.lower()
        if basename and basename not in by_basename:
            by_basename[basename] = resolved_path
    return by_normalized_path, by_basename

def _local_dds_preview_path(resolved_texconv_path: Optional[Path], cache: Dict[str, str], dds_path: Path) -> str:
    key = str(dds_path).lower()
    if key not in cache:
        from cdmw.core.texture_pipeline.inspection import parse_dds
        from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
        try:
            info = parse_dds(dds_path)
        except (OSError, ValueError):
            info = None
        cache[key] = ensure_dds_display_preview_png(resolved_texconv_path, dds_path, dds_info=info)
    return cache[key]


def _collect_local_visible_bindings(
    bindings: Sequence[object],
    by_path: Mapping[str, Path],
    by_basename: Mapping[str, Path],
) -> Tuple[Dict[str, Tuple[Tuple[int, int, int, int], Path, str, str, str]], List[Tuple[Path, str, str, str]], List[Tuple[Tuple[int, int, int, int], Path, str, str, str]]]:
    from cdmw.core.archive_model_references import _model_texture_hint_priority, _normalize_model_submesh_reference
    from cdmw.core.archive_model_textures import _is_visible_model_texture_type, _iter_model_submesh_reference_candidates, _model_texture_semantic_priority, _resolve_model_texture_semantics
    from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup
    resolved: Dict[str, Tuple[Tuple[int, int, int, int], Path, str, str, str]] = {}
    global_bindings: List[Tuple[Path, str, str, str]] = []
    fallback: List[Tuple[Tuple[int, int, int, int], Path, str, str, str]] = []
    seen_fallback: set[Tuple[str, str, str]] = set(); seen_global: set[Tuple[str, str]] = set()
    for binding in bindings:
        texture_path = str(getattr(binding, "texture_path", "") or "").strip()
        normalized = normalize_texture_reference_for_sidecar_lookup(texture_path)
        basename = PurePosixPath(normalized or texture_path.replace("\\", "/")).name.lower()
        override = by_path.get(normalized) or (by_basename.get(basename) if basename else None)
        if not texture_path or override is None:
            continue
        parameter = str(getattr(binding, "parameter_name", "") or "").strip()
        texture_type, subtype, confidence = _resolve_model_texture_semantics(texture_path)
        priority = _model_texture_hint_priority(parameter) or _model_texture_semantic_priority(texture_type, subtype)
        if priority[0] <= 0 and not _is_visible_model_texture_type(texture_type):
            continue
        candidate_key = (priority[0], priority[1], confidence, -len(texture_path or override.name))
        submesh = str(getattr(binding, "submesh_name", "") or "").strip()
        item = (candidate_key, override, parameter, submesh, texture_path)
        fallback_key = (_normalize_model_submesh_reference(submesh), basename, parameter.lower())
        if fallback_key not in seen_fallback:
            seen_fallback.add(fallback_key); fallback.append(item)
        keys = _iter_model_submesh_reference_candidates(submesh)
        if keys:
            for key in keys:
                if key not in resolved or candidate_key > resolved[key][0]:
                    resolved[key] = item
        elif (basename, parameter.lower()) not in seen_global:
            seen_global.add((basename, parameter.lower())); global_bindings.append((override, parameter, submesh, texture_path))
    return resolved, global_bindings, fallback


def _local_mesh_reference_candidates(parsed_submeshes: Sequence[object], index: int, mesh: ModelPreviewMesh) -> Tuple[str, ...]:
    from cdmw.core.archive_model_textures import _iter_model_submesh_reference_candidates
    parsed = parsed_submeshes[index] if 0 <= index < len(parsed_submeshes) else None
    return _iter_model_submesh_reference_candidates(str(getattr(parsed, "name", "") or ""), str(getattr(parsed, "material", "") or ""), str(getattr(parsed, "texture", "") or ""), str(getattr(mesh, "material_name", "") or ""), str(getattr(mesh, "texture_name", "") or ""))


def _assign_local_visible(mesh: ModelPreviewMesh, item: Tuple[Path, str, str, str], resolved_texconv: Optional[Path], cache: Dict[str, str]) -> bool:
    override, _parameter, submesh, texture_path = item
    try:
        mesh.preview_texture_path = _local_dds_preview_path(resolved_texconv, cache, override)
    except (OSError, RuntimeError, ValueError):
        return False
    mesh.texture_name = texture_path or override.name
    mesh.preview_texture_flip_vertical = False
    if submesh and not str(getattr(mesh, "material_name", "") or "").strip():
        mesh.material_name = submesh
    return True


def _assign_local_matched_visible(
    meshes: Sequence[ModelPreviewMesh], parsed_submeshes: Sequence[object], resolved: Mapping[str, Tuple[Tuple[int, int, int, int], Path, str, str, str]],
    resolved_texconv: Optional[Path], cache: Dict[str, str],
) -> Tuple[int, List[ModelPreviewMesh], Dict[int, int]]:
    assigned = 0; unresolved: List[ModelPreviewMesh] = []; indices: Dict[int, int] = {}
    for index, mesh in enumerate(meshes):
        if str(getattr(mesh, "preview_texture_path", "") or "").strip():
            continue
        keys = _local_mesh_reference_candidates(parsed_submeshes, index, mesh)
        best = max((resolved[key] for key in keys if key in resolved), key=lambda item: item[0], default=None)
        if best is None:
            unresolved.append(mesh); indices[id(mesh)] = index
        elif _assign_local_visible(mesh, (best[1], best[2], best[3], best[4]), resolved_texconv, cache):
            assigned += 1
    return assigned, unresolved, indices


def _promote_local_visible_fallback(
    meshes: Sequence[ModelPreviewMesh], parsed_submeshes: Sequence[object], unresolved: Sequence[ModelPreviewMesh], indices: Mapping[int, int],
    global_bindings: List[Tuple[Path, str, str, str]], fallback: Sequence[Tuple[Tuple[int, int, int, int], Path, str, str, str]],
) -> bool:
    from cdmw.core.archive_model_references import _is_anonymous_model_submesh_reference_key, _normalize_model_submesh_reference
    if global_bindings or not unresolved or not fallback:
        return False
    anonymous = all(not (keys := _local_mesh_reference_candidates(parsed_submeshes, indices.get(id(mesh), -1), mesh)) or all(_is_anonymous_model_submesh_reference_key(key) for key in keys) for mesh in unresolved)
    named = {_normalize_model_submesh_reference(item[3]) for item in fallback if _normalize_model_submesh_reference(item[3])}
    if len(meshes) != 1 and not (anonymous and (len(unresolved) == 1 or len(parsed_submeshes) <= 1 or len(named) == 1)):
        return False
    best = max(fallback, key=lambda item: item[0])
    global_bindings.append((best[1], best[2], best[3], best[4]))
    return True


def _assign_local_global_visible(meshes: Sequence[ModelPreviewMesh], bindings: Sequence[Tuple[Path, str, str, str]], resolved_texconv: Optional[Path], cache: Dict[str, str]) -> int:
    unresolved = [mesh for mesh in meshes if not str(getattr(mesh, "preview_texture_path", "") or "").strip()]
    assigned = 0
    for index, mesh in enumerate(unresolved):
        if not bindings or (len(bindings) != 1 and index >= len(bindings)):
            break
        item = bindings[0] if len(bindings) == 1 else bindings[index]
        assigned += int(_assign_local_visible(mesh, item, resolved_texconv, cache))
    return assigned


def _apply_mesh_import_local_sidecar_texture_overrides(
    preview_model: ModelPreviewData,
    parsed_mesh: Optional[ParsedMesh],
    sidecar_texture_bindings: Sequence[object],
    supplemental_dds_by_normalized_path: Mapping[str, Path],
    supplemental_dds_by_basename: Mapping[str, Path],
    *,
    texconv_path: Optional[Path],
) -> List[str]:
    if not preview_model.meshes or not sidecar_texture_bindings:
        return []
    from cdmw.core.archive_model_textures import _iter_parsed_model_submeshes
    parsed = _iter_parsed_model_submeshes(parsed_mesh)
    resolved, global_bindings, fallback = _collect_local_visible_bindings(sidecar_texture_bindings, supplemental_dds_by_normalized_path, supplemental_dds_by_basename)
    texconv = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    cache: Dict[str, str] = {}
    assigned, unresolved, indices = _assign_local_matched_visible(preview_model.meshes, parsed, resolved, texconv, cache)
    promoted = _promote_local_visible_fallback(preview_model.meshes, parsed, unresolved, indices, global_bindings, fallback)
    assigned += _assign_local_global_visible(unresolved, global_bindings, texconv, cache)
    if not assigned:
        return []
    info = [f"Applied {assigned:,} local sidecar-driven texture preview binding(s) from the selected supplemental files."]
    if promoted:
        info.append("Used a local sidecar texture fallback because the rebuilt preview did not preserve a reliable submesh/material name match.")
    return info

def _collect_local_support_bindings(
    bindings: Sequence[object], by_path: Mapping[str, Path], by_basename: Mapping[str, Path],
) -> Tuple[Dict[Tuple[str, str], Tuple[Tuple[int, int, int, int], Path, str, str, str]], Dict[str, List[Tuple[Tuple[int, int, int, int], Path, str, str, str]]]]:
    from cdmw.core.archive_model_references import _model_texture_slot_hint_priority
    from cdmw.core.archive_model_textures import _infer_model_preview_texture_slot, _iter_model_submesh_reference_candidates, _model_texture_candidate_slot_priority
    from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup
    resolved: Dict[Tuple[str, str], Tuple[Tuple[int, int, int, int], Path, str, str, str]] = {}
    global_bindings: Dict[str, List[Tuple[Tuple[int, int, int, int], Path, str, str, str]]] = defaultdict(list)
    seen: set[Tuple[str, str, str]] = set()
    for binding in bindings:
        texture = str(getattr(binding, "texture_path", "") or "").strip()
        parameter = str(getattr(binding, "parameter_name", "") or "").strip()
        slot = _infer_model_preview_texture_slot(texture, semantic_hint=parameter)
        normalized = normalize_texture_reference_for_sidecar_lookup(texture)
        basename = PurePosixPath(normalized or texture.replace("\\", "/")).name.lower()
        override = by_path.get(normalized) or (by_basename.get(basename) if basename else None)
        if not texture or slot not in {"normal", "material", "height"} or override is None:
            continue
        priority = _model_texture_slot_hint_priority(slot, parameter) or _model_texture_candidate_slot_priority(slot, texture) or (0, 0)
        candidate_key = (priority[0], priority[1], len(parameter), -len(texture or override.name))
        submesh = str(getattr(binding, "submesh_name", "") or "").strip()
        item = (candidate_key, override, parameter, submesh, texture)
        keys = _iter_model_submesh_reference_candidates(submesh)
        if keys:
            for key in keys:
                current = resolved.get((slot, key))
                if current is None or candidate_key > current[0]:
                    resolved[(slot, key)] = item
        elif (slot, basename, parameter.lower()) not in seen:
            seen.add((slot, basename, parameter.lower())); global_bindings[slot].append(item)
    return resolved, global_bindings


def _assign_local_support(mesh: ModelPreviewMesh, slot: str, item: Tuple[Tuple[int, int, int, int], Path, str, str, str], texconv: Optional[Path], cache: Dict[str, str]) -> bool:
    from cdmw.core.archive_model_textures import _infer_model_preview_normal_strength, _refine_model_texture_semantic_from_hint, _resolve_model_texture_semantic_details
    _key, override, parameter, _submesh, texture = item
    try:
        preview_path = _local_dds_preview_path(texconv, cache, override)
    except (OSError, RuntimeError, ValueError):
        return False
    name = texture or override.name
    if slot == "normal":
        mesh.preview_normal_texture_path = preview_path; mesh.preview_normal_texture_name = name
        mesh.preview_normal_texture_strength = _infer_model_preview_normal_strength(base_texture_path=str(getattr(mesh, "texture_name", "") or "").strip(), normal_texture_path=name, material_name=str(getattr(mesh, "material_name", "") or "").strip(), semantic_hint=parameter, prefer_stronger=False)
    elif slot == "material":
        semantic_type, subtype, _confidence, channels = _resolve_model_texture_semantic_details(name)
        semantic_type, subtype = _refine_model_texture_semantic_from_hint(semantic_type, subtype, parameter)
        mesh.preview_material_texture_path = preview_path; mesh.preview_material_texture_name = name
        mesh.preview_material_texture_type = semantic_type; mesh.preview_material_texture_subtype = subtype
        mesh.preview_material_texture_packed_channels = tuple(channels)
    elif slot == "height":
        mesh.preview_height_texture_path = preview_path; mesh.preview_height_texture_name = name
    else:
        return False
    return True


def _assign_local_matched_support(meshes: Sequence[ModelPreviewMesh], parsed: Sequence[object], resolved: Mapping[Tuple[str, str], Tuple[Tuple[int, int, int, int], Path, str, str, str]], texconv: Optional[Path], cache: Dict[str, str], counts: Dict[str, int]) -> None:
    for index, mesh in enumerate(meshes):
        keys = _local_mesh_reference_candidates(parsed, index, mesh)
        for slot in ("normal", "material", "height"):
            best = max((resolved[(slot, key)] for key in keys if (slot, key) in resolved), key=lambda item: item[0], default=None)
            if best is not None and _assign_local_support(mesh, slot, best, texconv, cache):
                counts[slot] += 1


def _assign_local_global_support(meshes: Sequence[ModelPreviewMesh], bindings_by_slot: Mapping[str, Sequence[Tuple[Tuple[int, int, int, int], Path, str, str, str]]], texconv: Optional[Path], cache: Dict[str, str], counts: Dict[str, int]) -> None:
    for slot in ("normal", "material", "height"):
        bindings = sorted(bindings_by_slot.get(slot, ()), key=lambda item: item[0], reverse=True)
        unresolved = [mesh for mesh in meshes if not str(getattr(mesh, f"preview_{slot}_texture_path", "") or "").strip()]
        for index, mesh in enumerate(unresolved):
            if not bindings or (len(bindings) != 1 and index >= len(bindings)):
                break
            item = bindings[0] if len(bindings) == 1 else bindings[index]
            counts[slot] += int(_assign_local_support(mesh, slot, item, texconv, cache))


def _apply_mesh_import_local_support_texture_overrides(
    preview_model: ModelPreviewData,
    parsed_mesh: Optional[ParsedMesh],
    sidecar_texture_bindings: Sequence[object],
    supplemental_dds_by_normalized_path: Mapping[str, Path],
    supplemental_dds_by_basename: Mapping[str, Path],
    *,
    texconv_path: Optional[Path],
) -> List[str]:
    if not preview_model.meshes or not sidecar_texture_bindings:
        return []
    from cdmw.core.archive_model_textures import _iter_parsed_model_submeshes
    resolved, global_bindings = _collect_local_support_bindings(sidecar_texture_bindings, supplemental_dds_by_normalized_path, supplemental_dds_by_basename)
    parsed = _iter_parsed_model_submeshes(parsed_mesh)
    texconv = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    cache: Dict[str, str] = {}; counts = {slot: 0 for slot in ("normal", "material", "height")}
    _assign_local_matched_support(preview_model.meshes, parsed, resolved, texconv, cache, counts)
    _assign_local_global_support(preview_model.meshes, global_bindings, texconv, cache, counts)
    total = sum(counts.values())
    if not total:
        return []
    labels = {"normal": "Local normal-map override(s)", "material": "Local material-mask override(s)", "height": "Local height/displacement override(s)"}
    return [f"Applied {total:,} local DDS support-map override(s) from the selected supplemental files."] + [f"{labels[slot]}: {counts[slot]:,}." for slot in ("normal", "material", "height") if counts[slot]]

def _apply_mesh_import_local_texture_overrides(
    preview_model: ModelPreviewData,
    supplemental_dds_by_normalized_path: Mapping[str, Path],
    supplemental_dds_by_basename: Mapping[str, Path],
    *,
    texconv_path: Optional[Path],
) -> List[str]:
    if not getattr(preview_model, "meshes", None):
        return []

    from cdmw.core.texture_pipeline.inspection import parse_dds
    from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png

    resolved_texconv_path = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    preview_cache: Dict[str, str] = {}
    override_count = 0
    unresolved_names: List[str] = []
    for mesh in preview_model.meshes:
        texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        if not texture_name:
            continue
        normalized_texture_name = _normalize_virtual_path(texture_name)
        basename = PurePosixPath(texture_name.replace("\\", "/")).name.lower()
        override_path = supplemental_dds_by_normalized_path.get(normalized_texture_name)
        if override_path is None and basename:
            override_path = supplemental_dds_by_basename.get(basename)
        if override_path is None:
            if texture_name not in unresolved_names and len(unresolved_names) < 5:
                unresolved_names.append(texture_name)
            continue
        cache_key = str(override_path).lower()
        preview_path = preview_cache.get(cache_key, "")
        if not preview_path:
            dds_info = None
            try:
                dds_info = parse_dds(override_path)
            except (OSError, ValueError):
                dds_info = None
            preview_path = ensure_dds_display_preview_png(
                resolved_texconv_path,
                override_path,
                dds_info=dds_info,
            )
            preview_cache[cache_key] = preview_path
        mesh.preview_texture_path = preview_path
        mesh.preview_texture_flip_vertical = False
        override_count += 1

    info_lines: List[str] = []
    if override_count > 0:
        info_lines.append(f"Applied {override_count:,} local DDS override texture(s) from the selected supplemental files.")
    return info_lines

def _merge_sidecar_text_maps(
    base_map: Mapping[str, Tuple[str, ...]],
    extra_map: Mapping[str, Tuple[str, ...]],
) -> Dict[str, Tuple[str, ...]]:
    merged: Dict[str, List[str]] = {key: list(values) for key, values in base_map.items()}
    for key, values in extra_map.items():
        bucket = merged.setdefault(key, [])
        for value in values:
            if value not in bucket:
                bucket.append(value)
    return {key: tuple(values) for key, values in merged.items()}
