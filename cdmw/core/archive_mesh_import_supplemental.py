from __future__ import annotations

import re
import threading
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_modding_constants import (
    MESH_IMPORT_COMPANION_EXTENSIONS,
    MESH_IMPORT_SIDECAR_EXTENSIONS,
    _MESH_IMPORT_RUNTIME_MESH_EXTENSIONS,
    _MESH_IMPORT_SHORT_TEXTURE_SUFFIXES,
    _MESH_IMPORT_TEXTURE_SUFFIXES,
)
from cdmw.core.archive_mesh_types import MeshImportSupplementalFileSpec
from cdmw.core.archive_patching import _normalize_virtual_path
from cdmw.core.common import raise_if_cancelled
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
)
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.modding.scene_importer import SCENE_TEXTURE_SOURCE_EXTENSIONS

from cdmw.core.archive_mesh_import_local_textures import (
    _mesh_import_candidate_virtual_paths,
    _mesh_import_loose_texture_preferred_paths,
    _mesh_import_sidecar_preferred_paths,
    _resolve_supplemental_target_entry,
)

def _build_selected_sidecar_texture_bindings(
    supplemental_files: Sequence[Path],
) -> Tuple[
    Tuple[object, ...],
    Tuple[str, ...],
    Dict[str, Tuple[str, ...]],
    Dict[str, Tuple[str, ...]],
]:
    from collections import defaultdict

    from cdmw.core.archive_model_references import _ArchiveModelSidecarTextureBinding
    from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup, parse_texture_sidecar_bindings

    bindings: List[object] = []
    sidecar_paths: List[str] = []
    seen_binding_keys: set[Tuple[str, str, str]] = set()
    sidecar_texts_by_normalized_path: Dict[str, List[str]] = defaultdict(list)
    sidecar_texts_by_basename: Dict[str, List[str]] = defaultdict(list)

    def append_unique_text(target: Dict[str, List[str]], key: str, text: str) -> None:
        normalized_key = str(key or "").strip()
        normalized_text = str(text or "")
        if not normalized_key or not normalized_text.strip():
            return
        bucket = target[normalized_key]
        if normalized_text not in bucket:
            bucket.append(normalized_text)

    def read_sidecar_text(path: Path) -> str:
        data = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-16", "utf-8", "cp1252"):
            try:
                return data.decode(encoding).replace("\ufeff", "")
            except UnicodeError:
                continue
        return data.decode("utf-8", errors="replace").replace("\ufeff", "")

    for supplemental_path in supplemental_files:
        if supplemental_path.suffix.lower() not in MESH_IMPORT_SIDECAR_EXTENSIONS:
            continue
        resolved_path = supplemental_path.expanduser().resolve()
        if not resolved_path.is_file():
            continue
        try:
            text = read_sidecar_text(resolved_path)
        except OSError:
            continue
        parsed_bindings = parse_texture_sidecar_bindings(text, sidecar_path=resolved_path.name)
        if not parsed_bindings:
            continue
        sidecar_paths.append(resolved_path.name)
        for binding in parsed_bindings:
            texture_role = binding.texture_role
            visualization_state = binding.visualization_state
            try:
                from cdmw.modding.asset_replacement import classify_texture_binding

                classification = classify_texture_binding(binding.parameter_name, binding.texture_path)
                texture_role = classification.slot_label or classification.slot_kind
                visualization_state = classification.visual_state
            except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
                # Best effort: sidecar binding text remains useful without role classification.
                pass
            normalized_texture_path = normalize_texture_reference_for_sidecar_lookup(binding.texture_path)
            key = (
                normalized_texture_path,
                str(binding.submesh_name or "").strip().lower(),
                str(binding.parameter_name or "").strip().lower(),
            )
            if normalized_texture_path:
                append_unique_text(sidecar_texts_by_normalized_path, normalized_texture_path, text)
                basename = PurePosixPath(normalized_texture_path).name
                if basename:
                    append_unique_text(sidecar_texts_by_basename, basename, text)
            if key in seen_binding_keys:
                continue
            seen_binding_keys.add(key)
            bindings.append(
                _ArchiveModelSidecarTextureBinding(
                    texture_path=binding.texture_path,
                    parameter_name=binding.parameter_name,
                    submesh_name=binding.submesh_name,
                    sidecar_path=resolved_path.name,
                    sidecar_kind=binding.sidecar_kind,
                    linked_mesh_path=binding.linked_mesh_path,
                    part_name=binding.part_name,
                    material_name=binding.material_name,
                    shader_family=binding.shader_family,
                    texture_role=texture_role,
                    visualization_state=visualization_state,
                    resolved_texture_exists=binding.resolved_texture_exists,
                    srgb_mode=str(getattr(binding, "srgb_mode", "") or ""),
                    parameter_declared_by=str(getattr(binding, "parameter_declared_by", "") or ""),
                    material_output_quality=str(getattr(binding, "material_output_quality", "") or ""),
                    layer_role=str(getattr(binding, "layer_role", "") or ""),
                    layer_channel=str(getattr(binding, "layer_channel", "") or ""),
                    blend_flags=tuple(
                        str(value)
                        for value in tuple(getattr(binding, "blend_flags", ()) or ())
                        if str(value)
                    ),
                    owner_slot_index=int(getattr(binding, "owner_slot_index", -1)),
                    owner_wrapper_item_id=str(getattr(binding, "owner_wrapper_item_id", "") or ""),
                    binding_authority=str(getattr(binding, "binding_authority", "") or ""),
                    binding_disposition=str(getattr(binding, "binding_disposition", "") or ""),
                    source_kind=str(getattr(binding, "source_kind", "") or ""),
                )
            )
    return (
        tuple(bindings),
        tuple(sidecar_paths),
        {key: tuple(values) for key, values in sidecar_texts_by_normalized_path.items()},
        {key: tuple(values) for key, values in sidecar_texts_by_basename.items()},
    )

def _build_mesh_import_supplemental_file_specs(
    entry: ArchiveEntry,
    supplemental_files: Sequence[Path],
    texture_references: Sequence[ArchiveModelTextureReference],
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[MeshImportSupplementalFileSpec, ...]:
    if not supplemental_files:
        return ()

    reference_candidates_by_basename: Dict[str, List[str]] = {}
    for reference in texture_references:
        raise_if_cancelled(stop_event, "Mesh import preview cancelled.")
        resolved_archive_path = str(getattr(reference, "resolved_archive_path", "") or "").strip()
        reference_name = str(getattr(reference, "reference_name", "") or "").strip()
        target_path = resolved_archive_path or reference_name
        if not target_path:
            continue
        basename = PurePosixPath(target_path.replace("\\", "/")).name.lower()
        if not basename:
            continue
        bucket = reference_candidates_by_basename.setdefault(basename, [])
        if target_path not in bucket:
            bucket.append(target_path)

    related_entries: Sequence[ArchiveEntry] = ()
    if archive_entries_by_basename is not None:
        from cdmw.core.archive_model_references import _find_archive_model_related_entries

        related_entries = _find_archive_model_related_entries(entry, dict(archive_entries_by_basename))
    related_entries_by_extension: Dict[str, List[ArchiveEntry]] = {}
    for related_entry in related_entries:
        related_entries_by_extension.setdefault(related_entry.extension.lower(), []).append(related_entry)

    specs: List[MeshImportSupplementalFileSpec] = []
    for supplemental_path in supplemental_files:
        raise_if_cancelled(stop_event, "Mesh import preview cancelled.")
        resolved_source = supplemental_path.expanduser().resolve()
        if not resolved_source.is_file():
            continue
        extension = resolved_source.suffix.lower()
        if extension in SCENE_TEXTURE_SOURCE_EXTENSIONS - {".dds"}:
            continue
        preferred_paths: List[str] = []
        if extension == ".dds":
            preferred_paths.extend(reference_candidates_by_basename.get(resolved_source.name.lower(), ()))
            preferred_paths.extend(_mesh_import_loose_texture_preferred_paths(resolved_source))
        elif extension in MESH_IMPORT_SIDECAR_EXTENSIONS:
            preferred_paths.extend(
                _mesh_import_sidecar_preferred_paths(entry, resolved_source, related_entries_by_extension)
            )
        elif extension in MESH_IMPORT_COMPANION_EXTENSIONS:
            preferred_paths.extend(_mesh_import_candidate_virtual_paths(resolved_source))
        target_entry, target_path = _resolve_supplemental_target_entry(
            resolved_source,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            archive_entries_by_basename=archive_entries_by_basename,
            preferred_paths=preferred_paths,
        )
        if extension == ".dds" and target_entry is None and not preferred_paths:
            continue
        kind = (
            "texture"
            if extension == ".dds"
            else "sidecar"
            if extension in MESH_IMPORT_SIDECAR_EXTENSIONS
            else "companion"
            if extension in MESH_IMPORT_COMPANION_EXTENSIONS
            else "file"
        )
        specs.append(
            MeshImportSupplementalFileSpec(
                source_path=resolved_source,
                target_path=target_path or (target_entry.path if isinstance(target_entry, ArchiveEntry) else ""),
                kind=kind,
                target_entry=target_entry if isinstance(target_entry, ArchiveEntry) else None,
                used_for_preview=kind in {"texture", "sidecar", "companion"},
            )
        )
    return tuple(specs)

def _find_first_archive_entry_by_virtual_path(
    virtual_path: str,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Optional[ArchiveEntry]:
    if archive_entries_by_normalized_path is None:
        return None
    candidates = archive_entries_by_normalized_path.get(_normalize_virtual_path(virtual_path), ())
    return candidates[0] if candidates else None

def _collect_original_mesh_sidecar_texts(
    entry: ArchiveEntry,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Tuple[ArchiveEntry, str], ...]:
    if archive_entries_by_basename is None:
        return ()
    from cdmw.core.archive_binary_preview import try_decode_text_like_archive_data
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_model_references import _find_archive_model_sidecar_entries

    sidecars: List[Tuple[ArchiveEntry, str]] = []
    for sidecar_entry in _find_archive_model_sidecar_entries(entry, dict(archive_entries_by_basename)):
        raise_if_cancelled(stop_event, "Mesh import preview cancelled.")
        try:
            sidecar_data, _decompressed, _note = read_archive_entry_data(
                sidecar_entry,
                stop_event=stop_event,
            )
        except (OSError, RuntimeError, ValueError):
            continue
        sidecar_text = try_decode_text_like_archive_data(sidecar_data)
        if sidecar_text:
            sidecars.append((sidecar_entry, sidecar_text))
    return tuple(sidecars)

def _source_owned_sidecar_name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

def _source_owned_sidecar_name_is_helper_row(value: str) -> bool:
    key = _source_owned_sidecar_name_key(value)
    if not key:
        return False
    parts = tuple(part for part in key.split("_") if part)
    if not parts:
        return False
    if parts[-1] in {"black", "inside"}:
        return True
    return "mask" in parts and key.startswith(("cd_", "pew_", "pe_", "npc_", "monster_", "vehicle_"))

def _align_source_owned_target_names_to_mesh(
    wrapper_names: Sequence[str],
    original_mesh: ParsedMesh,
) -> Tuple[str, ...]:
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    if not wrapper_names or not submeshes:
        return tuple(str(name or "").strip() for name in tuple(wrapper_names or ()) if str(name or "").strip())
    wrappers = tuple(str(name or "").strip() for name in tuple(wrapper_names or ()) if str(name or "").strip())
    if not wrappers:
        return ()
    indices_by_key: Dict[str, List[int]] = defaultdict(list)
    for index, name in enumerate(wrappers):
        key = _source_owned_sidecar_name_key(name)
        if key:
            indices_by_key[key].append(index)

    aligned: List[str] = []
    used_indices: set[int] = set()
    for target_index, submesh in enumerate(submeshes):
        fallback_names = [
            str(getattr(submesh, "name", "") or "").strip(),
            str(getattr(submesh, "material", "") or "").strip(),
        ]
        fallbacks = [name for index, name in enumerate(fallback_names) if name and name not in fallback_names[:index]]
        chosen = ""
        for fallback in fallbacks:
            key = _source_owned_sidecar_name_key(fallback)
            for wrapper_index in indices_by_key.get(key, ()):
                if wrapper_index in used_indices:
                    continue
                chosen = wrappers[wrapper_index]
                used_indices.add(wrapper_index)
                break
            if chosen:
                break
        if not chosen and target_index < len(wrappers):
            candidate = wrappers[target_index]
            fallback = fallbacks[0] if fallbacks else candidate
            candidate_key = _source_owned_sidecar_name_key(candidate)
            fallback_key = _source_owned_sidecar_name_key(fallback)
            if not (
                candidate_key != fallback_key
                and fallback
                and _source_owned_sidecar_name_is_helper_row(candidate)
            ):
                chosen = candidate
                used_indices.add(target_index)
        if not chosen:
            chosen = fallbacks[0] if fallbacks else (wrappers[target_index] if target_index < len(wrappers) else "")
        if chosen:
            aligned.append(chosen)
    return tuple(aligned)

def _source_owned_target_names_from_sidecars(
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]],
    original_mesh: Optional[ParsedMesh] = None,
) -> Tuple[str, ...]:
    """Return game-runtime submesh wrapper names aligned to original PAC draw sections."""
    for _sidecar_entry, sidecar_text in tuple(original_sidecars or ()):
        text = str(sidecar_text or "")
        if "_subMeshResources" not in text or "SkinnedMeshMaterialWrapper" not in text:
            continue
        vector_match = re.search(
            r'<Vector\b[^>]*\bName="_subMeshResources"[^>]*>(?P<body>.*?)</Vector>\s*</SkinnedMeshProperty>',
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        body = vector_match.group("body") if vector_match is not None else text
        names: List[str] = []
        for match in re.finditer(
            r'<SkinnedMeshMaterialWrapper\b(?P<attrs>[^>]*)>',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            attrs = match.group("attrs") or ""
            name_match = re.search(
                r'\b(?:_subMeshName|subMeshName|SubMeshName)="([^"]+)"',
                attrs,
                flags=re.IGNORECASE,
            )
            name = str(name_match.group(1) if name_match else "").strip()
            if name:
                names.append(name)
        if names:
            if original_mesh is not None:
                return _align_source_owned_target_names_to_mesh(names, original_mesh)
            return tuple(names)
    return ()

def _mesh_import_normalize_runtime_stem_candidate(value: str) -> str:
    candidate = str(value or "").replace("\\", "/").strip().strip('"').strip("'").lower()
    if not candidate:
        return ""
    candidate = PurePosixPath(candidate).name
    for suffix in _MESH_IMPORT_TEXTURE_SUFFIXES:
        if candidate.endswith(suffix):
            candidate = candidate[: -len(suffix)]
            break
    for suffix in _MESH_IMPORT_SHORT_TEXTURE_SUFFIXES:
        if candidate.endswith(suffix) and len(candidate) > len(suffix):
            candidate = candidate[: -len(suffix)]
            break
    candidate = re.sub(r"[^a-z0-9_]+", "_", candidate).strip("_")
    if not candidate.startswith("cd_") or len(candidate) < 8:
        return ""
    return candidate

def _mesh_import_runtime_stem_candidates_from_sidecars(
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]],
) -> Tuple[str, ...]:
    stems: List[str] = []
    seen: set[str] = set()
    for _sidecar_entry, sidecar_text in tuple(original_sidecars or ()):
        text = str(sidecar_text or "").replace("\\", "/")
        if not text:
            continue
        for pattern in (
            r'\b(?:_subMeshName|subMeshName|SubMeshName)="([^"]+)"',
            r'\b_path="([^"]+)"',
            r'\bvalue="([^"]+)"',
        ):
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                stem = _mesh_import_normalize_runtime_stem_candidate(match.group(1))
                if stem and stem not in seen:
                    stems.append(stem)
                    seen.add(stem)
    return tuple(stems)

def _mesh_import_runtime_mesh_paths_from_sidecars(
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]],
) -> Tuple[str, ...]:
    paths: List[str] = []
    seen: set[str] = set()
    extension_pattern = "|".join(re.escape(ext.lstrip(".")) for ext in sorted(_MESH_IMPORT_RUNTIME_MESH_EXTENSIONS))
    path_pattern = re.compile(
        rf"character/model/[^\s\"'<>]+?\.(?:{extension_pattern})\b",
        flags=re.IGNORECASE,
    )
    for _sidecar_entry, sidecar_text in tuple(original_sidecars or ()):
        text = str(sidecar_text or "")
        if not text:
            continue
        for match in path_pattern.finditer(text):
            path = match.group(0).replace("\\", "/").strip().strip('"').strip("'")
            key = path.lower()
            if key and key not in seen:
                paths.append(path)
                seen.add(key)
    return tuple(paths)

def _mesh_import_runtime_stem_candidates_from_mesh(mesh: ParsedMesh) -> Tuple[str, ...]:
    stems: List[str] = []
    seen: set[str] = set()
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        for raw_value in (
            getattr(submesh, "name", ""),
            getattr(submesh, "material", ""),
            getattr(submesh, "texture", ""),
        ):
            stem = _mesh_import_normalize_runtime_stem_candidate(str(raw_value or ""))
            if stem and stem not in seen:
                stems.append(stem)
                seen.add(stem)
    return tuple(stems)

def _mesh_import_runtime_sibling_mesh_candidates(
    entry: ArchiveEntry,
    mesh: ParsedMesh,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]] = (),
) -> Tuple[ArchiveEntry, ...]:
    if archive_entries_by_basename is None:
        return ()
    source_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower()
    source_extension = str(getattr(entry, "extension", "") or "").strip().lower()
    if source_extension not in _MESH_IMPORT_RUNTIME_MESH_EXTENSIONS:
        return ()
    # Submesh names and DDS stems often describe shared material families, not
    # runtime mesh identity. Only explicit model mesh paths from sidecars are
    # strong enough to warn that the selected PAC may not be the runtime target.
    runtime_paths = _mesh_import_runtime_mesh_paths_from_sidecars(original_sidecars)
    if not runtime_paths:
        return ()
    candidates: List[ArchiveEntry] = []
    seen_paths: set[str] = set()
    for runtime_path in runtime_paths:
        runtime_key = str(runtime_path or "").replace("\\", "/").strip().lower()
        basename = PurePosixPath(runtime_key).name
        if not basename:
            continue
        basename_candidates = list(archive_entries_by_basename.get(basename, ()) or ())
        if basename != basename.lower():
            basename_candidates.extend(archive_entries_by_basename.get(basename.lower(), ()) or ())
        for candidate in tuple(basename_candidates):
            candidate_path = str(getattr(candidate, "path", "") or "").replace("\\", "/").strip()
            candidate_key = candidate_path.lower()
            if not candidate_key or candidate_key == source_path or candidate_key in seen_paths:
                continue
            if candidate_key != runtime_key:
                continue
            if str(getattr(candidate, "extension", "") or "").strip().lower() not in _MESH_IMPORT_RUNTIME_MESH_EXTENSIONS:
                continue
            if "character/model/" not in candidate_key:
                continue
            candidates.append(candidate)
            seen_paths.add(candidate_key)

    def _score(candidate: ArchiveEntry) -> Tuple[int, int, str]:
        path = str(getattr(candidate, "path", "") or "").replace("\\", "/").lower()
        score = 0
        if "/1_pc/" in path:
            score += 80
        if "/armor/" in path:
            score += 30
        if "/2_mon/" in source_path and "/2_mon/" not in path:
            score += 20
        if "/modelproperty/" not in path and "character/model/" in path:
            score += 5
        return (score, -len(path), path)

    candidates.sort(key=_score, reverse=True)
    return tuple(candidates[:12])

def mesh_import_runtime_sibling_mesh_candidates(
    entry: ArchiveEntry,
    mesh: ParsedMesh,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]] = (),
) -> Tuple[ArchiveEntry, ...]:
    """Return likely runtime mesh targets for display/preview clone sources."""

    return _mesh_import_runtime_sibling_mesh_candidates(
        entry,
        mesh,
        archive_entries_by_basename,
        original_sidecars,
    )

def _mesh_import_runtime_sibling_warning_lines(
    entry: ArchiveEntry,
    mesh: ParsedMesh,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
    original_sidecars: Sequence[Tuple[ArchiveEntry, str]] = (),
) -> Tuple[str, ...]:
    candidates = _mesh_import_runtime_sibling_mesh_candidates(
        entry,
        mesh,
        archive_entries_by_basename,
        original_sidecars,
    )
    if not candidates:
        return ()
    source_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower()
    has_player_candidate = any("/1_pc/" in str(getattr(candidate, "path", "") or "").replace("\\", "/").lower() for candidate in candidates)
    if "/2_mon/" not in source_path and not has_player_candidate:
        return ()
    lines = [
        "Runtime target warning: this selected mesh appears to be a display/monster clone that references player equipment mesh names. "
        "Editing/exporting only this PAC can look correct in preview but leave the equipped in-game model unchanged."
        if "/2_mon/" in source_path and has_player_candidate
        else "Runtime target warning: related runtime mesh candidates with the same material/submesh family were found. "
        "If in-game output does not change, edit/export the runtime mesh path instead of only this preview source.",
        "Likely runtime mesh candidate(s):",
    ]
    for candidate in candidates[:6]:
        lines.append(f"  {candidate.path}")
    if len(candidates) > 6:
        lines.append(f"  ... {len(candidates) - 6:,} more candidate(s)")
    return tuple(lines)

def _decode_text_payload(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "utf-8", "cp1252"):
        try:
            return bytes(data or b"").decode(encoding).replace("\ufeff", "")
        except UnicodeError:
            continue
    return bytes(data or b"").decode("utf-8", errors="replace").replace("\ufeff", "")

def _summarize_crimson_companion_supplemental_files(supplemental_files: Sequence[Path]) -> Tuple[str, ...]:
    companion_files = [
        path
        for path in tuple(supplemental_files or ())
        if isinstance(path, Path) and path.suffix.lower() in (MESH_IMPORT_COMPANION_EXTENSIONS | {".pami"})
    ]
    if not companion_files:
        return ()
    try:
        from cdmw.core.crimson_formats import (
            complete_swap_file_policy,
            decode_meshinfo,
            decode_paa_metabin,
            decode_prefab,
            parse_pami_material_instances,
        )
    except ImportError:
        return ()
    try:
        from cdmw.rendering.material_channels import parse_crimson_material_definition_text
    except ImportError:
        parse_crimson_material_definition_text = None  # type: ignore[assignment]

    lines: List[str] = ["Crimson companion metadata:"]
    for path in companion_files[:12]:
        extension = path.suffix.lower()
        policy = complete_swap_file_policy(extension)
        try:
            data = path.read_bytes()
        except OSError as exc:
            lines.append(f"  {path.name}: unreadable ({exc})")
            continue
        if extension == ".prefab":
            decoded = decode_prefab(data)
            roles = Counter(reference.role for reference in decoded.references)
            role_text = _summarize_compact([f"{role}={count}" for role, count in sorted(roles.items())]) or "no resource refs"
            lines.append(
                f"  {path.name}: prefab refs {role_text}; patchable={decoded.patchable_reference_count}; policy={policy}"
            )
        elif extension == ".meshinfo":
            decoded = decode_meshinfo(data)
            roles = Counter(reference.role for reference in decoded.references)
            role_text = _summarize_compact([f"{role}={count}" for role, count in sorted(roles.items())]) or "no visible refs"
            lines.append(f"  {path.name}: meshinfo refs {role_text}; policy={decoded.material_policy}")
        elif extension == ".paa_metabin":
            decoded = decode_paa_metabin(data)
            declared = decoded.declared_type or "AnimationMetaData"
            lines.append(f"  {path.name}: {declared}; policy={decoded.material_policy}")
        elif extension == ".pami":
            instances = parse_pami_material_instances(_decode_text_payload(data))
            texture_count = sum(len(instance.texture_parameters) for instance in instances)
            lines.append(
                f"  {path.name}: pami material instances={len(instances)}, texture params={texture_count}; policy={policy}"
            )
        elif extension == ".material" and parse_crimson_material_definition_text is not None:
            try:
                definition = parse_crimson_material_definition_text(_decode_text_payload(data), source_path=str(path))
                lines.append(
                    f"  {path.name}: material technique={definition.technique or '-'}, params={len(definition.parameters)}, groups={len(definition.parameter_groups)}; policy={policy}"
                )
            except Exception as exc:
                # User-visible metadata path: report parser failures in the preview summary.
                lines.append(f"  {path.name}: material definition parse failed ({exc}); policy={policy}")
        else:
            lines.append(f"  {path.name}: policy={policy}")
    if len(companion_files) > 12:
        lines.append(f"  ... {len(companion_files) - 12:,} more companion file(s)")
    return tuple(lines)

def _mesh_texture_original_source_path(texture_entry: object) -> Path:
    from cdmw.core.archive_media_preview import ensure_archive_preview_source

    if not isinstance(texture_entry, ArchiveEntry):
        raise ValueError("Original texture archive entry is unavailable.")
    source_path, _note = ensure_archive_preview_source(texture_entry)
    return source_path

def _mesh_texture_original_bytes(texture_entry: object) -> bytes:
    from cdmw.core.archive_extraction import read_archive_entry_data

    if not isinstance(texture_entry, ArchiveEntry):
        raise ValueError("Original texture archive entry is unavailable.")
    data, _decompressed, _note = read_archive_entry_data(texture_entry)
    return data
