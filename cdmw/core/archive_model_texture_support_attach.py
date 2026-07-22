from __future__ import annotations

import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.models import (
    ArchiveEntry,
    ModelPreviewData,
    ModelPreviewMesh,
    PreviewMaterialTextureInput,
)
from cdmw.rendering.crimson_shader_registry import decode_crimson_texture_binding
from cdmw.core.common import RunCancelled, raise_if_cancelled
from cdmw.core.archive_model_references import (
    _ArchiveModelSidecarTextureBinding,
    _is_anonymous_model_submesh_reference_key,
    _model_texture_slot_hint_priority,
    _normalize_model_texture_reference,
)
from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup

from cdmw.core import archive_model_texture_config as _config
from cdmw.core.archive_model_texture_resolution import (
    _prefetch_archive_model_texture_preview_paths,
    _resolve_model_texture_archive_entry,
)
from cdmw.core.archive_model_texture_semantics import (
    _append_model_preview_material_input,
    _infer_model_preview_normal_strength,
    _infer_model_preview_texture_slot,
    _iter_model_sidecar_binding_exact_submesh_keys,
    _iter_model_sidecar_binding_submesh_keys,
    _iter_model_submesh_exact_reference_candidates,
    _iter_model_submesh_reference_candidates,
    _iter_parsed_model_submeshes,
    _model_sidecar_binding_matches_source_component,
    _model_texture_candidate_slot_priority,
    _refine_model_texture_semantic_from_hint,
    _resolve_model_texture_semantic_details,
    _resolve_model_texture_semantics,
    _select_model_sidecar_bindings_for_submesh,
    _set_model_preview_texture_slot,
)

def _public_preview_path(*args, **kwargs):
    from cdmw.core import archive_model_textures as public
    return public._ensure_archive_model_texture_preview_path(*args, **kwargs)

_SupportBinding = Tuple[Tuple[int, int, int, int], ArchiveEntry, str, str]
_MaterialInputBinding = Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding]


@dataclass
class _SupportAttachmentState:
    source_entry: ArchiveEntry
    model_preview: ModelPreviewData
    parsed_submeshes: Tuple[object, ...]
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]]
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]]
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]]
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]]
    support_slots: Tuple[str, ...]
    stop_event: Optional[threading.Event]
    preview_cache: Dict[str, str] = field(default_factory=dict)
    exact_assigned: Dict[str, int] = field(default_factory=dict)
    fallback_assigned: Dict[str, int] = field(default_factory=dict)
    exact_examples: Dict[str, List[str]] = field(default_factory=dict)
    fallback_examples: Dict[str, List[str]] = field(default_factory=dict)
    exact_sidecar_paths: List[str] = field(default_factory=list)
    ordered_keys: Dict[str, Dict[str, int]] = field(default_factory=dict)
    ordered_assigned: Dict[str, int] = field(default_factory=dict)
    exact_resolved: Dict[Tuple[str, str], _SupportBinding] = field(default_factory=dict)
    material_inputs: Dict[str, List[_MaterialInputBinding]] = field(default_factory=lambda: defaultdict(list))
    support_candidates: Dict[str, List[_MaterialInputBinding]] = field(default_factory=lambda: defaultdict(list))
    material_input_candidates: List[_MaterialInputBinding] = field(default_factory=list)
    global_bindings: Dict[str, List[_SupportBinding]] = field(default_factory=lambda: defaultdict(list))
    ambiguous_slots_by_mesh_id: Dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))
    preserved_inputs: int = 0
    culled_inputs: int = 0


def _support_sidecar_texts(state: _SupportAttachmentState, texture_path: str) -> Tuple[str, ...]:
    normalized = normalize_texture_reference_for_sidecar_lookup(texture_path)
    texts = tuple(state.sidecar_texts_by_normalized_path.get(normalized, ())) if state.sidecar_texts_by_normalized_path is not None and normalized else ()
    if not texts and state.sidecar_texts_by_basename is not None:
        basename = PurePosixPath(texture_path.replace("\\", "/")).name.lower()
        texts = tuple(state.sidecar_texts_by_basename.get(basename, ())) if basename else ()
    return texts


def _support_preview_path(state: _SupportAttachmentState, entry: ArchiveEntry, slot: str) -> str:
    key = f"{_normalize_model_texture_reference(entry.path)}|{slot}"
    if key not in state.preview_cache:
        state.preview_cache[key] = _public_preview_path(
            entry,
            max_dimension=_config.MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION,
            slot_kind=slot,
            stop_event=state.stop_event,
        )
    return state.preview_cache[key]


def _record_support_example(target: Dict[str, List[str]], slot: str, path: str) -> None:
    basename = PurePosixPath(path.replace("\\", "/")).name
    if basename and basename not in target[slot] and len(target[slot]) < 3:
        target[slot].append(basename)


def _assign_support_slot(state: _SupportAttachmentState, mesh: ModelPreviewMesh, slot: str, entry: ArchiveEntry, hint: str) -> bool:
    semantic_type = semantic_subtype = ""
    packed_channels: Tuple[str, ...] = ()
    if slot == "material":
        semantic_type, semantic_subtype, _confidence, packed_channels = _resolve_model_texture_semantic_details(entry.path, sidecar_texts=_support_sidecar_texts(state, entry.path))
        semantic_type, semantic_subtype = _refine_model_texture_semantic_from_hint(semantic_type, semantic_subtype, hint)
    changed = _set_model_preview_texture_slot(
        mesh,
        slot=slot,
        preview_path=_support_preview_path(state, entry, slot),
        texture_path=entry.path,
        normal_strength=(
            _infer_model_preview_normal_strength(
                base_texture_path=str(getattr(mesh, "texture_name", "") or "").strip(),
                normal_texture_path=entry.path,
                material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                semantic_hint=hint,
                prefer_stronger=False,
            ) if slot == "normal" else None
        ),
        semantic_type=semantic_type,
        semantic_subtype=semantic_subtype,
        packed_channels=packed_channels,
    )
    if changed and str(getattr(state.source_entry, "extension", "") or "").lower() == ".pac":
        mesh.preview_texture_flip_vertical = False
    return changed


def _remember_material_input(state: _SupportAttachmentState, key: str, candidate: _MaterialInputBinding) -> None:
    normalized_key = str(key or "").strip()
    if not normalized_key:
        return
    identity = (_normalize_model_texture_reference(candidate[1].path), str(candidate[2] or "").strip().lower())
    if any((_normalize_model_texture_reference(item[1].path), str(item[2] or "").strip().lower()) == identity for item in state.material_inputs[normalized_key]):
        return
    state.material_inputs[normalized_key].append(candidate)


def _binding_registry_slot(
    binding: _ArchiveModelSidecarTextureBinding,
    parameter: str,
    source_path: str,
    *,
    slot_name: str = "material",
    semantic_subtype: str = "",
) -> str:
    decode = decode_crimson_texture_binding(
        shader_family=getattr(binding, "shader_family", ""),
        parameter_name=parameter,
        source_path=source_path,
        slot_name=slot_name,
        semantic_subtype=semantic_subtype,
        layer_channel=getattr(binding, "layer_channel", ""),
        blend_flags=tuple(getattr(binding, "blend_flags", ()) or ()),
        sidecar_kind=getattr(binding, "sidecar_kind", ""),
        parameter_declared_by=getattr(binding, "parameter_declared_by", ""),
    )
    return str(decode.get("slot", "") or "material").strip().casefold()


def _binding_registry_preview_slot(
    binding: _ArchiveModelSidecarTextureBinding,
    parameter: str,
    source_path: str,
) -> str:
    slot = _binding_registry_slot(binding, parameter, source_path)
    return slot if slot in {"base", "normal", "height", "emissive"} else "material"


def _append_material_input(state: _SupportAttachmentState, mesh: ModelPreviewMesh, candidate: _MaterialInputBinding) -> bool:
    _key, entry, parameter, binding = candidate
    declared_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
    transport_path = str(entry.path or "").replace("\\", "/").strip()
    transport_is_alias = bool(
        declared_path
        and _normalize_model_texture_reference(declared_path)
        != _normalize_model_texture_reference(transport_path)
    )
    semantic_type, subtype, _confidence, channels = _resolve_model_texture_semantic_details(entry.path, sidecar_texts=_support_sidecar_texts(state, entry.path))
    semantic_type, subtype = _refine_model_texture_semantic_from_hint(semantic_type, subtype, parameter)
    registry_slot = _binding_registry_slot(
        binding,
        parameter,
        entry.path,
        slot_name=semantic_type or "material",
        semantic_subtype=subtype,
    )
    preview_slot = registry_slot if registry_slot in {"base", "normal", "height", "emissive"} else "material"
    try:
        preview_path = _support_preview_path(state, entry, preview_slot)
    except RunCancelled:
        raise
    except Exception:
        # The source-side material graph remains authoritative even when the
        # optional display conversion fails. Downstream package writers can
        # still resolve and decode the DDS directly.
        preview_path = ""
    return _append_model_preview_material_input(
        mesh,
        PreviewMaterialTextureInput(
            slot_kind=registry_slot,
            parameter_name=str(parameter or "").strip(),
            # Keep the PAC-declared reference as semantic authority while the
            # resolved archive entry records the local transport. Relocated
            # texture families can legitimately use different virtual roots.
            source_texture_path=declared_path or transport_path,
            source_dds_path=transport_path,
            texture_name=PurePosixPath(entry.path.replace("\\", "/")).name,
            preview_texture_path=preview_path,
            semantic_type=registry_slot or str(semantic_type or "material").strip().lower(),
            semantic_subtype=str(subtype or "").strip().lower(),
            packed_channels=tuple(str(channel or "").strip().lower() for channel in channels if str(channel or "").strip()),
            material_name=str(getattr(binding, "material_name", "") or getattr(binding, "submesh_name", "") or getattr(mesh, "material_name", "") or "").strip(),
            part_name=str(getattr(binding, "part_name", "") or "").strip(),
            shader_family=str(getattr(binding, "shader_family", "") or "").strip(),
            confidence=("sidecar-family-transport" if transport_is_alias else "sidecar-exact"),
            visualized=bool(preview_path),
            sidecar_kind=str(getattr(binding, "sidecar_kind", "") or "").strip(),
            sidecar_path=str(getattr(binding, "sidecar_path", "") or "").strip(),
            linked_mesh_path=str(getattr(binding, "linked_mesh_path", "") or "").strip(),
            srgb_mode=str(getattr(binding, "srgb_mode", "") or "").strip(),
            parameter_declared_by=str(getattr(binding, "parameter_declared_by", "") or "").strip(),
            material_output_quality=str(getattr(binding, "material_output_quality", "") or "").strip(),
            layer_role=str(getattr(binding, "layer_role", "") or "").strip(),
            layer_channel=str(getattr(binding, "layer_channel", "") or "").strip(),
            blend_flags=tuple(str(value) for value in tuple(getattr(binding, "blend_flags", ()) or ()) if str(value)),
            owner_slot_index=int(getattr(binding, "owner_slot_index", -1)),
            owner_wrapper_item_id=str(getattr(binding, "owner_wrapper_item_id", "") or ""),
            binding_authority=str(getattr(binding, "binding_authority", "") or ""),
            binding_disposition=str(getattr(binding, "binding_disposition", "") or ""),
            source_kind=str(getattr(binding, "source_kind", "") or ""),
            material_parameters=tuple(getattr(binding, "material_parameters", ()) or ()),
        ),
    )


def _material_input_group(parameter: str, texture_path: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "", str(parameter or "").lower())
    stem = PurePosixPath(str(texture_path or "").replace("\\", "/")).stem.lower()
    rules = (
        (("layerbasecolor", "detaildiffuse", "grimediffuse", "damageblendingdiffuse"), "visible_layer"),
        (("basecolor", "overlaycolor"), "visible_base"), (("colorblendingmask",), "mask"),
        (("detailmask",), "detail_mask"), (("specular",), "specular"), (("grime",), "grime"),
        (("damage",), "damage"), (("skin",), "skin"), (("material",), "material"),
    )
    for tokens, group in rules:
        if any(token in key for token in tokens):
            return group
    if stem.endswith(("_ma", "_mask")):
        return "mask"
    if stem.endswith("_mg"):
        return "detail_mask"
    if stem.endswith("_sp"):
        return "specular"
    if stem.endswith("_m"):
        return "material"
    return "other"


def _preserve_visible_material_input(parameter: str) -> bool:
    key = re.sub(r"[^a-z0-9]+", "", str(parameter or "").lower())
    return any(token in key for token in ("layerbasecolor", "detaildiffuse", "grimediffuse", "damageblendingdiffuse", "overlaycolor", "basecolor"))


def _select_material_inputs(candidates: Sequence[_MaterialInputBinding]) -> Tuple[_MaterialInputBinding, ...]:
    ordered = sorted(candidates, key=lambda item: item[0], reverse=True)
    authoritative_pac_graph = any(
        str(getattr(candidate[3], "sidecar_kind", "") or "").strip().casefold()
        in {"pac_xml", "pami"}
        and int(getattr(candidate[3], "owner_slot_index", -1)) >= 0
        for candidate in ordered
    )
    if authoritative_pac_graph:
        selected: List[_MaterialInputBinding] = []
        identities: set[Tuple[str, str]] = set()
        for candidate in ordered:
            identity = (
                _normalize_model_texture_reference(candidate[1].path),
                str(candidate[2] or "").strip().lower(),
            )
            if identity in identities:
                continue
            identities.add(identity)
            selected.append(candidate)
        return tuple(selected)
    selected: List[_MaterialInputBinding] = []
    identities: set[Tuple[str, str]] = set()
    groups: set[str] = set()
    for candidate in ordered:
        identity = (_normalize_model_texture_reference(candidate[1].path), str(candidate[2] or "").strip().lower())
        group = _material_input_group(candidate[2], candidate[1].path)
        if identity not in identities and group not in groups:
            selected.append(candidate); identities.add(identity); groups.add(group)
            if len(selected) >= 5:
                return tuple(selected)
    for candidate in ordered:
        identity = (_normalize_model_texture_reference(candidate[1].path), str(candidate[2] or "").strip().lower())
        if identity not in identities:
            selected.append(candidate); identities.add(identity)
            if len(selected) >= 5:
                break
    return tuple(selected)


def _collect_support_binding(state: _SupportAttachmentState, binding: _ArchiveModelSidecarTextureBinding, seen_global: set[Tuple[str, str, str]]) -> None:
    if not _model_sidecar_binding_matches_source_component(state.source_entry, binding):
        return
    parameter = str(binding.parameter_name or "").strip()
    owner_qualified_pac = (
        str(getattr(binding, "sidecar_kind", "") or "").strip().casefold()
        in {"pac_xml", "pami"}
        and int(getattr(binding, "owner_slot_index", -1)) >= 0
    )
    slot = (
        _binding_registry_preview_slot(binding, parameter, binding.texture_path)
        if owner_qualified_pac
        else _infer_model_preview_texture_slot("", semantic_hint=parameter)
    )
    preserve_visible = slot == "base" and _preserve_visible_material_input(parameter)
    preserve_pac_graph = owner_qualified_pac
    if slot not in state.support_slots and not preserve_visible and not preserve_pac_graph:
        return
    exact_submesh_keys = _iter_model_sidecar_binding_exact_submesh_keys(binding)
    entry, status = _resolve_model_texture_archive_entry(
        state.source_entry,
        binding.texture_path,
        # A PAC wrapper already names its exact DDS.  Supplying the material
        # name as a second texture candidate can make semantic scoring replace
        # a declared ``*_sp``/``*_m``/``*_f`` map with the base-color sibling.
        # Keep that fallback only for legacy or inferred bindings.
        "" if owner_qualified_pac else binding.submesh_name,
        state.texture_entries_by_normalized_path, state.texture_entries_by_basename,
        semantic_hint=parameter, expand_family_candidates=False, allow_technical_match=True,
        # An owner-qualified PAC parameter is the semantic authority for its
        # exact DDS reference.  Filename families remain useful for legacy and
        # inferred bindings, but must not reject cases where (for example) an
        # ``*_emi.dds`` is explicitly bound as a color mask or height input.
        preferred_slot="" if owner_qualified_pac else slot,
        sidecar_texts_by_normalized_path=state.sidecar_texts_by_normalized_path,
        sidecar_texts_by_basename=state.sidecar_texts_by_basename,
    )
    if owner_qualified_pac and (entry is None or status != "resolved"):
        # Some PACs retain an authoritative texture-family reference under an
        # older virtual root (for example tree/.../*_color.dds) while the same
        # family is shipped under character/.../*.dds. Only owner-qualified
        # PAC parameters may use this semantic family fallback, and the slot
        # constraint keeps base/material/normal siblings from crossing roles.
        entry, status = _resolve_model_texture_archive_entry(
            state.source_entry,
            binding.texture_path,
            "",
            state.texture_entries_by_normalized_path,
            state.texture_entries_by_basename,
            semantic_hint=parameter,
            expand_family_candidates=True,
            allow_technical_match=True,
            preferred_slot=slot,
            sidecar_texts_by_normalized_path=state.sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=state.sidecar_texts_by_basename,
        )
    if entry is None or status != "resolved":
        return
    texts = _support_sidecar_texts(state, entry.path)
    _texture_type, _subtype, confidence = _resolve_model_texture_semantics(entry.path, sidecar_texts=texts)
    priority = (8, 0) if preserve_visible else (_model_texture_slot_hint_priority(slot, parameter) or _model_texture_candidate_slot_priority(slot, entry.path, sidecar_texts=texts))
    if priority is None and preserve_pac_graph:
        # Exact owner-qualified PAC inputs are part of the source graph even
        # when a shader-specific suffix (for example ``*_tp`` torn-cloth
        # patterns) has no legacy preview-slot heuristic. Keep the binding at
        # the lowest priority so it reaches the graph compiler without being
        # preferred as a direct support map.
        priority = (1, 0)
    if priority is None:
        return
    candidate_key = (priority[0], priority[1], confidence, -len(entry.path))
    candidate = (candidate_key, entry, parameter, binding)
    if exact_submesh_keys:
        primary = exact_submesh_keys[0]
        if primary:
            state.ordered_keys.setdefault(slot, {}).setdefault(primary, len(state.ordered_keys.setdefault(slot, {})))
        if slot == "material" or preserve_visible or preserve_pac_graph:
            state.material_input_candidates.append(candidate)
        if not preserve_visible:
            state.support_candidates[slot].append(candidate)
        for key in exact_submesh_keys:
            if slot == "material" or preserve_visible or preserve_pac_graph:
                _remember_material_input(state, key, candidate)
            if not preserve_visible:
                current = state.exact_resolved.get((slot, key))
                if current is None or candidate_key > current[0]:
                    state.exact_resolved[(slot, key)] = (candidate_key, entry, parameter, binding.submesh_name)
    elif not preserve_visible:
        key = (slot, _normalize_model_texture_reference(entry.path), parameter.lower())
        if key not in seen_global:
            seen_global.add(key)
            state.global_bindings[slot].append((candidate_key, entry, parameter, binding.submesh_name))
    if binding.sidecar_path and binding.sidecar_path not in state.exact_sidecar_paths:
        state.exact_sidecar_paths.append(binding.sidecar_path)


def _collect_and_prefetch_support_bindings(state: _SupportAttachmentState, bindings: Sequence[_ArchiveModelSidecarTextureBinding]) -> None:
    seen_global: set[Tuple[str, str, str]] = set()
    for binding in bindings:
        raise_if_cancelled(state.stop_event)
        _collect_support_binding(state, binding, seen_global)
    dimension = int(_config.MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)
    requests = [(item[1], slot, dimension) for (slot, _key), item in state.exact_resolved.items()]
    requests.extend((item[1], slot, dimension) for slot, values in state.global_bindings.items() for item in values)
    requests.extend(
        (
            item[1],
            _material_input_preview_slot(item),
            dimension,
        )
        for values in state.material_inputs.values()
        for item in _select_material_inputs(values)
    )
    _prefetch_archive_model_texture_preview_paths(requests, state.preview_cache, stop_event=state.stop_event)


def _material_input_preview_slot(candidate: _MaterialInputBinding) -> str:
    _key, entry, parameter, binding = candidate
    return _binding_registry_preview_slot(binding, parameter, entry.path)


def _support_mesh_candidates(state: _SupportAttachmentState, index: int, mesh: ModelPreviewMesh) -> Tuple[str, ...]:
    parsed = state.parsed_submeshes[index] if index < len(state.parsed_submeshes) else None
    return _iter_model_submesh_reference_candidates(
        str(getattr(parsed, "name", "") or ""), str(getattr(parsed, "material", "") or ""),
        str(getattr(parsed, "texture", "") or ""), str(getattr(mesh, "material_name", "") or ""),
        str(getattr(mesh, "preview_sidecar_material_primitive", "") or ""),
        str(getattr(mesh, "texture_name", "") or ""),
    )


def _support_mesh_exact_candidates(
    state: _SupportAttachmentState,
    index: int,
    mesh: ModelPreviewMesh,
) -> Tuple[str, ...]:
    parsed = state.parsed_submeshes[index] if index < len(state.parsed_submeshes) else None
    return _iter_model_submesh_exact_reference_candidates(
        str(getattr(parsed, "name", "") or ""), str(getattr(parsed, "material", "") or ""),
        str(getattr(parsed, "texture", "") or ""), str(getattr(mesh, "material_name", "") or ""),
        str(getattr(mesh, "preview_sidecar_material_primitive", "") or ""),
        str(getattr(mesh, "texture_name", "") or ""),
    )


def _matched_support_candidates(
    candidates: Sequence[_MaterialInputBinding],
    *,
    exact_keys: Sequence[str],
    fuzzy_keys: Sequence[str],
) -> Tuple[_MaterialInputBinding, ...]:
    selected_bindings = _select_model_sidecar_bindings_for_submesh(
        tuple(candidate[3] for candidate in candidates),
        exact_candidates=exact_keys,
        fuzzy_candidates=fuzzy_keys,
    )
    selected_ids = {id(binding) for binding in selected_bindings}
    return tuple(candidate for candidate in candidates if id(candidate[3]) in selected_ids)


def _has_fuzzy_support_candidates(
    candidates: Sequence[_MaterialInputBinding],
    fuzzy_keys: Sequence[str],
) -> bool:
    candidate_keys = {str(key or "").strip().lower() for key in fuzzy_keys if str(key or "").strip()}
    return bool(
        candidate_keys
        and any(
            candidate_keys.intersection(_iter_model_sidecar_binding_submesh_keys(candidate[3]))
            for candidate in candidates
        )
    )


def _assign_exact_support_maps(state: _SupportAttachmentState) -> None:
    for index, mesh in enumerate(state.model_preview.meshes):
        raise_if_cancelled(state.stop_event)
        exact_keys = _support_mesh_exact_candidates(state, index, mesh)
        fuzzy_keys = _support_mesh_candidates(state, index, mesh)
        rich: List[_MaterialInputBinding] = []
        seen: set[Tuple[str, str]] = set()
        material_candidates = _matched_support_candidates(
            state.material_input_candidates,
            exact_keys=exact_keys,
            fuzzy_keys=fuzzy_keys,
        )
        for candidate in sorted(material_candidates, key=lambda item: item[0], reverse=True):
            identity = (_normalize_model_texture_reference(candidate[1].path), str(candidate[2] or "").strip().lower())
            if identity not in seen:
                seen.add(identity); rich.append(candidate)
        selected = _select_material_inputs(rich)
        state.culled_inputs += max(0, len(rich) - len(selected))
        for candidate in selected:
            try:
                if _append_material_input(state, mesh, candidate):
                    state.preserved_inputs += 1
            except RunCancelled:
                raise
            except Exception:
                continue
        for slot in state.support_slots:
            if str(getattr(mesh, f"preview_{slot}_texture_path", "") or "").strip():
                continue
            matched = _matched_support_candidates(
                state.support_candidates.get(slot, ()),
                exact_keys=exact_keys,
                fuzzy_keys=fuzzy_keys,
            )
            if not matched and _has_fuzzy_support_candidates(
                state.support_candidates.get(slot, ()),
                fuzzy_keys,
            ):
                state.ambiguous_slots_by_mesh_id[id(mesh)].add(slot)
            best = max(matched, key=lambda item: item[0], default=None)
            if best is None:
                continue
            try:
                if _assign_support_slot(state, mesh, slot, best[1], best[2]):
                    state.exact_assigned[slot] += 1
                    _record_support_example(state.exact_examples, slot, best[1].path)
            except RunCancelled:
                raise
            except Exception:
                continue


def _assign_ordered_support_maps(state: _SupportAttachmentState) -> None:
    for slot in state.support_slots:
        if slot == "emissive":
            # Emissive maps are sparse, submesh-specific effects. PAC wrapper
            # order is not a reliable material identity and must not spread a
            # blade/accessory glow onto unrelated handle or guard geometry.
            continue
        keys = state.ordered_keys.get(slot, {})
        if len(keys) <= 1:
            continue
        ordered = [state.exact_resolved.get((slot, key)) for key, _index in sorted(keys.items(), key=lambda value: value[1])]
        if not any(ordered):
            continue
        for index, mesh in enumerate(state.model_preview.meshes):
            if slot in state.ambiguous_slots_by_mesh_id.get(id(mesh), set()):
                continue
            mesh_keys = _support_mesh_candidates(state, index, mesh)
            if mesh_keys and not all(_is_anonymous_model_submesh_reference_key(key) for key in mesh_keys):
                continue
            if str(getattr(mesh, f"preview_{slot}_texture_path", "") or "").strip() or index >= len(ordered) or ordered[index] is None:
                continue
            item = ordered[index]
            try:
                if _assign_support_slot(state, mesh, slot, item[1], item[2]):
                    state.exact_assigned[slot] += 1; state.ordered_assigned[slot] += 1
                    _record_support_example(state.exact_examples, slot, item[1].path)
            except RunCancelled:
                raise
            except Exception:
                continue


def _assign_global_support_maps(state: _SupportAttachmentState) -> None:
    for slot in state.support_slots:
        if slot == "emissive" and len(state.model_preview.meshes) > 1:
            continue
        bindings = sorted(state.global_bindings.get(slot, ()), key=lambda item: item[0], reverse=True)
        unresolved = [
            mesh
            for mesh in state.model_preview.meshes
            if not str(getattr(mesh, f"preview_{slot}_texture_path", "") or "").strip()
            and slot not in state.ambiguous_slots_by_mesh_id.get(id(mesh), set())
        ]
        for index, mesh in enumerate(unresolved):
            if not bindings or (len(bindings) != 1 and index >= len(bindings)):
                break
            item = bindings[0] if len(bindings) == 1 else bindings[index]
            try:
                if _assign_support_slot(state, mesh, slot, item[1], item[2]):
                    state.exact_assigned[slot] += 1
                    _record_support_example(state.exact_examples, slot, item[1].path)
            except RunCancelled:
                raise
            except Exception:
                continue


def _mesh_declares_emissive_authority(mesh: ModelPreviewMesh) -> bool:
    def positive_number(value: object) -> bool:
        try:
            return float(value) > 0.0
        except (TypeError, ValueError, OverflowError):
            return False

    def nonblack_color(value: object) -> bool:
        if isinstance(value, str):
            text = value.strip().lstrip("#")
            if len(text) in {6, 8} and re.fullmatch(r"[0-9a-fA-F]+", text):
                return any(int(text[offset : offset + 2], 16) > 0 for offset in (0, 2, 4))
            return any(positive_number(component) for component in re.findall(r"[-+]?\d*\.?\d+", value))
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return any(positive_number(component) for component in tuple(value)[:3])
        return False

    family = str(getattr(mesh, "preview_sidecar_shader_family", "") or "").strip().casefold()
    if "emissive" in family:
        return True
    overrides = getattr(mesh, "preview_native_material_overrides", {}) or {}
    if isinstance(overrides, Mapping):
        if positive_number(overrides.get("emissive_intensity")):
            return True
        if nonblack_color(overrides.get("emissive_color")):
            return True
    for texture_input in tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ()):
        if any(
            "emissive" in str(getattr(texture_input, field_name, "") or "").strip().casefold()
            for field_name in ("slot_kind", "semantic_type", "semantic_subtype", "parameter_name")
        ):
            return True
    for parameter in tuple(getattr(mesh, "preview_material_parameters", ()) or ()):
        name = str(getattr(parameter, "parameter_name", "") or "").strip().casefold()
        if "emissiveintensity" in name and positive_number(
            getattr(parameter, "numeric_value", None)
            if getattr(parameter, "numeric_value", None) is not None
            else getattr(parameter, "value", None)
        ):
            return True
        if "emissivecolor" in name and nonblack_color(
            getattr(parameter, "color_value", ()) or getattr(parameter, "value", None)
        ):
            return True
    return False


def _assign_fallback_support_maps(state: _SupportAttachmentState) -> None:
    for mesh in state.model_preview.meshes:
        raise_if_cancelled(state.stop_event)
        texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        material_name = str(getattr(mesh, "material_name", "") or "").strip()
        if not texture_name and not material_name:
            continue
        for slot in state.support_slots:
            if str(getattr(mesh, f"preview_{slot}_texture_path", "") or "").strip():
                continue
            if slot in state.ambiguous_slots_by_mesh_id.get(id(mesh), set()):
                continue
            if slot == "emissive" and not _mesh_declares_emissive_authority(mesh):
                continue
            entry, status = _resolve_model_texture_archive_entry(
                state.source_entry, texture_name, material_name,
                state.texture_entries_by_normalized_path, state.texture_entries_by_basename,
                semantic_hint=slot, allow_technical_match=True, preferred_slot=slot,
                sidecar_texts_by_normalized_path=state.sidecar_texts_by_normalized_path,
                sidecar_texts_by_basename=state.sidecar_texts_by_basename,
            )
            if entry is None or status != "resolved":
                continue
            sidecar_texts = _support_sidecar_texts(state, entry.path)
            if _model_texture_candidate_slot_priority(
                slot,
                entry.path,
                sidecar_texts=sidecar_texts,
            ) is None:
                continue
            try:
                if _assign_support_slot(state, mesh, slot, entry, slot):
                    state.fallback_assigned[slot] += 1
                    _record_support_example(state.fallback_examples, slot, entry.path)
            except RunCancelled:
                raise
            except Exception:
                continue


def _support_attachment_report(state: _SupportAttachmentState) -> List[str]:
    labels = {
        "normal": "normal-map",
        "material": "material-mask",
        "height": "height/displacement",
        "emissive": "emissive",
    }
    info: List[str] = []
    exact_total = sum(state.exact_assigned.values())
    fallback_total = sum(state.fallback_assigned.values())
    if exact_total:
        suffix = f" from {', '.join(state.exact_sidecar_paths[:2])}" if state.exact_sidecar_paths else ""
        if len(state.exact_sidecar_paths) > 2:
            suffix += " ..."
        info.append(f"Applied {exact_total:,} exact high-quality support-map binding(s) from companion material sidecar data{suffix}.")
        for slot in state.support_slots:
            if state.exact_assigned[slot]:
                examples = f" Examples: {', '.join(state.exact_examples[slot])}." if state.exact_examples[slot] else ""
                info.append(f"Exact sidecar {labels[slot]} bindings: {state.exact_assigned[slot]:,}.{examples}")
    if state.preserved_inputs:
        info.append(f"Preserved {state.preserved_inputs:,} exact sidecar material texture input(s) for material diagnostics and preview.")
    if state.culled_inputs:
        info.append(f"Skipped {state.culled_inputs:,} lower-priority sidecar material texture input(s) before preview conversion to keep model loading responsive.")
    ordered_total = sum(state.ordered_assigned.values())
    if ordered_total:
        parts = [f"{slot[0]}:{state.ordered_assigned[slot]:,}" for slot in state.support_slots if state.ordered_assigned[slot]]
        info.append(f"Matched {ordered_total:,} anonymous support-map binding(s) to ordered sidecar material wrapper(s)" + (f" ({', '.join(parts)})." if parts else "."))
    if fallback_total:
        info.append(f"Applied {fallback_total:,} semantic sibling high-quality support-map binding(s) using slot-correct family fallback.")
        for slot in state.support_slots:
            if state.fallback_assigned[slot]:
                examples = f" Examples: {', '.join(state.fallback_examples[slot])}." if state.fallback_examples[slot] else ""
                info.append(f"Semantic sibling {labels[slot]} bindings: {state.fallback_assigned[slot]:,}.{examples}")
    if not exact_total and not fallback_total and any(str(getattr(mesh, "texture_name", "") or "").strip() or str(getattr(mesh, "preview_texture_path", "") or "").strip() for mesh in state.model_preview.meshes):
        info.append("No usable high-quality support maps were resolved from exact sidecar bindings or semantic sibling fallback. The preview remains base-texture only.")
    return info


def _attach_model_support_texture_preview_paths(
    source_entry: ArchiveEntry,
    model_preview: Optional[ModelPreviewData],
    *,
    parsed_mesh: Optional[object] = None,
    sidecar_texture_bindings: Sequence[_ArchiveModelSidecarTextureBinding] = (),
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
    support_slots: Sequence[str] = ("normal", "material", "height", "emissive"),
    stop_event: Optional[threading.Event] = None,
) -> List[str]:
    if model_preview is None or not model_preview.meshes:
        return []
    requested = {str(slot or "").strip().lower() for slot in support_slots}
    slots = tuple(slot for slot in ("normal", "material", "height", "emissive") if slot in requested)
    if not slots:
        return []
    state = _SupportAttachmentState(
        source_entry=source_entry,
        model_preview=model_preview,
        parsed_submeshes=_iter_parsed_model_submeshes(parsed_mesh),
        texture_entries_by_normalized_path=texture_entries_by_normalized_path,
        texture_entries_by_basename=texture_entries_by_basename,
        sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
        sidecar_texts_by_basename=sidecar_texts_by_basename,
        support_slots=slots,
        stop_event=stop_event,
        exact_assigned={slot: 0 for slot in slots}, fallback_assigned={slot: 0 for slot in slots},
        exact_examples={slot: [] for slot in slots}, fallback_examples={slot: [] for slot in slots},
        ordered_keys={slot: {} for slot in slots}, ordered_assigned={slot: 0 for slot in slots},
    )
    _collect_and_prefetch_support_bindings(state, sidecar_texture_bindings)
    _assign_exact_support_maps(state)
    _assign_ordered_support_maps(state)
    _assign_global_support_maps(state)
    _assign_fallback_support_maps(state)
    return _support_attachment_report(state)
