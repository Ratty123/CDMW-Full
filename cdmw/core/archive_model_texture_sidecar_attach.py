from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.models import (
    ArchiveEntry,
    ModelPreviewData,
    ModelPreviewMesh,
)


_PAC_CUTOUT_ALPHA_CUTOFF = 0.12
from cdmw.core.common import RunCancelled, raise_if_cancelled
from cdmw.core.archive_model_references import (
    _ArchiveModelSidecarTextureBinding,
    _allowed_model_sidecar_visible_classes,
    _classify_model_sidecar_visible_binding,
    _is_anonymous_model_submesh_reference_key,
    _model_sidecar_visible_class_priority,
    _model_texture_hint_priority,
    _normalize_model_submesh_reference,
    _normalize_model_texture_reference,
    _normalize_model_visible_texture_mode,
)
from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup

from cdmw.core import archive_model_texture_config as _config
from cdmw.core.archive_model_texture_resolution import (
    _prefetch_archive_model_texture_preview_paths,
    _resolve_model_texture_archive_entry,
)
from cdmw.core.archive_model_texture_semantics import (
    _is_visible_model_texture_type,
    _iter_model_sidecar_binding_submesh_keys,
    _iter_model_submesh_reference_candidates,
    _iter_parsed_model_submeshes,
    _model_sidecar_binding_matches_source_component,
    _refine_model_texture_semantic_from_hint,
    _resolve_model_texture_semantics,
)
from cdmw.core.archive_model_texture_sidecar_rules import (
    _apply_model_sidecar_base_preview,
    _is_low_authority_model_base_texture,
    _mesh_existing_base_is_sidecar_identity,
    _mesh_preview_base_is_low_authority,
    _model_sidecar_binding_alpha_cutoff,
    _model_sidecar_binding_alpha_mode,
    _model_sidecar_binding_double_sided,
    _model_preview_sidecar_material_color,
)

def _public_preview_path(*args, **kwargs):
    from cdmw.core import archive_model_textures as public
    return public._ensure_archive_model_texture_preview_path(*args, **kwargs)

_VisibleBinding = Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]
_MaterialColor = Tuple[Tuple[int, int, int, int], Tuple[float, float, float], _ArchiveModelSidecarTextureBinding]


@dataclass
class _SidecarAttachmentState:
    source_entry: ArchiveEntry
    model_preview: ModelPreviewData
    parsed_submeshes: Tuple[object, ...]
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]]
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]]
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]]
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]]
    allowed_visible_classes: set[str]
    fallback_only: bool
    stop_event: Optional[threading.Event]
    bindings: Sequence[_ArchiveModelSidecarTextureBinding]
    resolved_by_submesh: Dict[str, _VisibleBinding] = field(default_factory=dict)
    global_visible_bindings: List[Tuple[ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]] = field(default_factory=list)
    fallback_visible_bindings: List[_VisibleBinding] = field(default_factory=list)
    material_color_by_submesh: Dict[str, _MaterialColor] = field(default_factory=dict)
    global_material_colors: List[_MaterialColor] = field(default_factory=list)
    sidecar_paths: List[str] = field(default_factory=list)
    preview_cache: Dict[str, str] = field(default_factory=dict)
    unresolved_meshes: List[ModelPreviewMesh] = field(default_factory=list)
    unresolved_mesh_indices_by_id: Dict[int, int] = field(default_factory=dict)
    assigned_count: int = 0
    identity_override_count: int = 0
    low_authority_layer_override_count: int = 0
    ordered_anonymous_fallback_count: int = 0
    material_color_fallback_count: int = 0
    material_contract_count: int = 0
    alpha_contract_count: int = 0
    double_sided_contract_count: int = 0
    promoted_anonymous_fallback: bool = False


def _sidecar_preview_path(state: _SidecarAttachmentState, entry: ArchiveEntry) -> str:
    key = f"{_normalize_model_texture_reference(entry.path)}|base"
    if key not in state.preview_cache:
        state.preview_cache[key] = _public_preview_path(
            entry,
            slot_kind="base",
            stop_event=state.stop_event,
        )
    return state.preview_cache[key]


def _collect_sidecar_binding(
    state: _SidecarAttachmentState,
    binding: _ArchiveModelSidecarTextureBinding,
    seen_fallback: set[Tuple[str, str, str]],
    seen_global: set[Tuple[str, str]],
    seen_colors: set[Tuple[float, float, float, str, str]],
) -> None:
    if not _model_sidecar_binding_matches_source_component(state.source_entry, binding):
        return
    submesh_keys = _iter_model_sidecar_binding_submesh_keys(binding)
    binding_class = _classify_model_sidecar_visible_binding(binding.parameter_name, binding.texture_path)
    color = _model_preview_sidecar_material_color(binding)
    if color:
        color_priority = (_model_sidecar_visible_class_priority(binding_class), 1 if binding_class != "technical" else 0, 1 if str(getattr(binding, "tint_color", "") or "") else 0, -len(str(getattr(binding, "texture_path", "") or "")))
        if submesh_keys:
            for key in submesh_keys:
                existing = state.material_color_by_submesh.get(key)
                if existing is None or color_priority > existing[0]:
                    state.material_color_by_submesh[key] = (color_priority, color, binding)
        else:
            color_key = (color[0], color[1], color[2], str(getattr(binding, "material_name", "") or "").strip().lower(), str(getattr(binding, "part_name", "") or "").strip().lower())
            if color_key not in seen_colors:
                seen_colors.add(color_key)
                state.global_material_colors.append((color_priority, color, binding))
    entry, status = _resolve_model_texture_archive_entry(
        state.source_entry,
        binding.texture_path,
        binding.submesh_name,
        state.texture_entries_by_normalized_path,
        state.texture_entries_by_basename,
        semantic_hint=binding.parameter_name,
        expand_family_candidates=False,
        allow_technical_match=True,
        sidecar_texts_by_normalized_path=state.sidecar_texts_by_normalized_path,
        sidecar_texts_by_basename=state.sidecar_texts_by_basename,
    )
    if entry is None or status != "resolved":
        return
    normalized = normalize_texture_reference_for_sidecar_lookup(entry.path)
    texts = tuple(state.sidecar_texts_by_normalized_path.get(normalized, ())) if state.sidecar_texts_by_normalized_path is not None and normalized else ()
    if not texts and state.sidecar_texts_by_basename is not None:
        texts = tuple(state.sidecar_texts_by_basename.get(PurePosixPath(entry.path.replace("\\", "/")).name.lower(), ()))
    texture_type, subtype, confidence = _resolve_model_texture_semantics(entry.path, sidecar_texts=texts)
    texture_type, subtype = _refine_model_texture_semantic_from_hint(texture_type, subtype, binding.parameter_name)
    visible_class = _classify_model_sidecar_visible_binding(binding.parameter_name, entry.path)
    if not _is_visible_model_texture_type(texture_type) or visible_class not in state.allowed_visible_classes:
        return
    priority = _model_texture_hint_priority(binding.parameter_name) or _model_texture_semantic_priority(texture_type, subtype)
    candidate_key = (_model_sidecar_visible_class_priority(visible_class), priority[0], priority[1], confidence, -len(entry.path))
    fallback_key = (_normalize_model_texture_reference(entry.path), str(binding.parameter_name or "").strip().lower(), _normalize_model_submesh_reference(binding.submesh_name))
    item = (candidate_key, entry, binding.parameter_name, binding.submesh_name, binding)
    if fallback_key not in seen_fallback:
        seen_fallback.add(fallback_key)
        state.fallback_visible_bindings.append(item)
    if submesh_keys:
        for key in submesh_keys:
            existing = state.resolved_by_submesh.get(key)
            if existing is None or candidate_key > existing[0]:
                state.resolved_by_submesh[key] = item
    else:
        global_key = (_normalize_model_texture_reference(entry.path), str(binding.parameter_name or "").strip().lower())
        if global_key not in seen_global:
            seen_global.add(global_key)
            state.global_visible_bindings.append((entry, binding.parameter_name, binding.submesh_name, binding))
    if binding.sidecar_path and binding.sidecar_path not in state.sidecar_paths:
        state.sidecar_paths.append(binding.sidecar_path)


def _collect_and_prefetch_sidecar_bindings(state: _SidecarAttachmentState) -> None:
    seen_fallback: set[Tuple[str, str, str]] = set()
    seen_global: set[Tuple[str, str]] = set()
    seen_colors: set[Tuple[float, float, float, str, str]] = set()
    for binding in state.bindings:
        raise_if_cancelled(state.stop_event)
        _collect_sidecar_binding(state, binding, seen_fallback, seen_global, seen_colors)
    requests = [(item[1], "base", int(_config.MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)) for item in state.resolved_by_submesh.values()]
    mesh_count = max(1, len(state.model_preview.meshes))
    requests.extend((item[0], "base", int(_config.MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)) for item in state.global_visible_bindings[:mesh_count])
    requests.extend((item[1], "base", int(_config.MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)) for item in sorted(state.fallback_visible_bindings, key=lambda value: value[0], reverse=True)[:max(mesh_count * 2, 8)])
    _prefetch_archive_model_texture_preview_paths(requests, state.preview_cache, stop_event=state.stop_event)


def _mesh_sidecar_candidates(state: _SidecarAttachmentState, index: int, mesh: ModelPreviewMesh) -> Tuple[str, ...]:
    parsed = state.parsed_submeshes[index] if 0 <= index < len(state.parsed_submeshes) else None
    return _iter_model_submesh_reference_candidates(
        str(getattr(parsed, "name", "") or ""), str(getattr(parsed, "material", "") or ""),
        str(getattr(parsed, "texture", "") or ""), str(getattr(mesh, "material_name", "") or ""),
        str(getattr(mesh, "texture_name", "") or ""),
    )


def _best_visible_sidecar_fallback(state: _SidecarAttachmentState, candidate_keys: Sequence[str]) -> Optional[_VisibleBinding]:
    key_set = set(candidate_keys)
    best: Optional[_VisibleBinding] = None
    for item in state.fallback_visible_bindings:
        if _is_low_authority_model_base_texture(item[1].path):
            continue
        binding_keys = _iter_model_sidecar_binding_submesh_keys(item[4])
        if binding_keys and any(key in key_set for key in binding_keys) and (best is None or item[0] > best[0]):
            best = item
    return best


def _apply_sidecar_base(state: _SidecarAttachmentState, mesh: ModelPreviewMesh, item: _VisibleBinding, *, set_name: bool) -> None:
    _key, entry, _parameter, _submesh, binding = item
    _apply_model_sidecar_base_preview(
        mesh,
        texture_entry=entry,
        preview_path_text=_sidecar_preview_path(state, entry),
        binding=binding,
        force_unflipped_preview=str(getattr(state.source_entry, "extension", "") or "").lower() == ".pac",
        set_texture_name=set_name,
    )
    state.assigned_count += 1


def _assign_matched_sidecar_bases(state: _SidecarAttachmentState) -> None:
    for index, mesh in enumerate(state.model_preview.meshes):
        raise_if_cancelled(state.stop_event)
        existing_path = str(getattr(mesh, "preview_texture_path", "") or "").strip()
        parsed = state.parsed_submeshes[index] if index < len(state.parsed_submeshes) else None
        candidate_keys = _mesh_sidecar_candidates(state, index, mesh)
        best = max((state.resolved_by_submesh[key] for key in candidate_keys if key in state.resolved_by_submesh), key=lambda value: value[0], default=None)
        promoted = False
        if state.fallback_only and existing_path and _mesh_preview_base_is_low_authority(mesh):
            better = _best_visible_sidecar_fallback(state, candidate_keys)
            if better is not None:
                best, promoted = better, True
        if best is None:
            if not existing_path:
                state.unresolved_meshes.append(mesh)
                state.unresolved_mesh_indices_by_id[id(mesh)] = index
            continue
        if existing_path and state.fallback_only and not promoted:
            continue
        if existing_path and not promoted and not _mesh_existing_base_is_sidecar_identity(mesh, parsed, best[4]):
            continue
        try:
            old_path = existing_path
            _apply_sidecar_base(state, mesh, best, set_name=bool(existing_path))
            new_path = str(getattr(mesh, "preview_texture_path", "") or "")
            if old_path and _normalize_model_texture_reference(old_path) != _normalize_model_texture_reference(new_path):
                if promoted:
                    state.low_authority_layer_override_count += 1
                    mesh.preview_texture_approximation_note = "Sidecar visible layer texture is used over a low-detail overlay/default base for preview."
                else:
                    state.identity_override_count += 1
        except RunCancelled:
            raise
        except Exception:
            continue


def _assign_ordered_sidecar_bases(state: _SidecarAttachmentState) -> None:
    if not state.unresolved_meshes or not state.fallback_visible_bindings:
        return
    order: Dict[str, int] = {}
    best_by_key: Dict[str, _VisibleBinding] = {}
    for item in state.fallback_visible_bindings:
        binding = item[4]
        key = next((_normalize_model_submesh_reference(value) for value in (str(getattr(binding, "submesh_name", "") or ""), str(getattr(binding, "part_name", "") or ""), str(getattr(binding, "material_name", "") or "")) if _normalize_model_submesh_reference(value)), "")
        if not key:
            continue
        order.setdefault(key, len(order))
        if key not in best_by_key or item[0] > best_by_key[key][0]:
            best_by_key[key] = item
    ordered = [best_by_key[key] for key, _index in sorted(order.items(), key=lambda value: value[1]) if key in best_by_key]
    if len(ordered) <= 1:
        return
    for mesh in state.unresolved_meshes:
        index = state.unresolved_mesh_indices_by_id.get(id(mesh), -1)
        if str(getattr(mesh, "preview_texture_path", "") or "").strip() or not 0 <= index < len(ordered):
            continue
        try:
            _apply_sidecar_base(state, mesh, ordered[index], set_name=False)
            state.ordered_anonymous_fallback_count += 1
        except RunCancelled:
            raise
        except Exception:
            continue


def _promote_and_assign_global_sidecar_bases(state: _SidecarAttachmentState) -> None:
    if not state.global_visible_bindings and state.unresolved_meshes and state.fallback_visible_bindings:
        anonymous = all(not (keys := _mesh_sidecar_candidates(state, state.unresolved_mesh_indices_by_id.get(id(mesh), -1), mesh)) or all(_is_anonymous_model_submesh_reference_key(key) for key in keys) for mesh in state.unresolved_meshes)
        named = {_normalize_model_submesh_reference(item[3]) for item in state.fallback_visible_bindings if _normalize_model_submesh_reference(item[3])}
        all_named = {key for binding in state.bindings for key in _iter_model_sidecar_binding_submesh_keys(binding)[:1] if key}
        promote = len(state.model_preview.meshes) == 1 or (anonymous and (len(state.unresolved_meshes) == 1 or len(state.parsed_submeshes) <= 1 or (len(named) == 1 and len(all_named) <= 1)))
        if promote:
            best = max(state.fallback_visible_bindings, key=lambda item: item[0])
            state.global_visible_bindings.append((best[1], best[2], best[3], best[4]))
            state.promoted_anonymous_fallback = True
    if not state.global_visible_bindings:
        return
    unresolved = [mesh for mesh in state.unresolved_meshes if not str(getattr(mesh, "preview_texture_path", "") or "").strip()]
    selected = state.global_visible_bindings
    for index, mesh in enumerate(unresolved):
        if len(selected) != 1 and index >= len(selected):
            break
        raw = selected[0] if len(selected) == 1 else selected[index]
        item: _VisibleBinding = ((0, 0, 0, 0, 0), raw[0], raw[1], raw[2], raw[3])
        try:
            _apply_sidecar_base(state, mesh, item, set_name=False)
        except RunCancelled:
            raise
        except Exception:
            continue


def _assign_sidecar_material_colors(state: _SidecarAttachmentState) -> None:
    if not state.material_color_by_submesh and not state.global_material_colors:
        return
    global_colors = sorted(state.global_material_colors, key=lambda item: item[0], reverse=True)
    global_index = 0
    for index, mesh in enumerate(state.model_preview.meshes):
        raise_if_cancelled(state.stop_event)
        existing_color = tuple(getattr(mesh, "preview_color", ()) or ())
        existing_path = str(getattr(mesh, "preview_texture_path", "") or "").strip()
        candidates = _mesh_sidecar_candidates(state, index, mesh)
        best = max((state.material_color_by_submesh[key] for key in candidates if key in state.material_color_by_submesh), key=lambda item: item[0], default=None)
        if best is None and global_colors:
            if len(global_colors) == 1:
                best = global_colors[0]
            elif not existing_path and global_index < len(global_colors):
                best = global_colors[global_index]
                global_index += 1
        if best is None:
            continue
        color = best[1]
        if len(existing_color) >= 3 and existing_path and not _is_low_authority_model_base_texture(str(getattr(mesh, "texture_name", "") or "")):
            continue
        if tuple(existing_color[:3]) != tuple(color):
            mesh.preview_color = color
            if not existing_path:
                mesh.preview_base_texture_quality = "material_color_fallback"
                mesh.preview_texture_approximation_note = "Sidecar material color is used because no exact visible base DDS preview was resolved."
            state.material_color_fallback_count += 1


def _matching_sidecar_contract_bindings(
    state: _SidecarAttachmentState,
    index: int,
    mesh: ModelPreviewMesh,
) -> Tuple[_ArchiveModelSidecarTextureBinding, ...]:
    candidates = set(_mesh_sidecar_candidates(state, index, mesh))
    matched = tuple(
        binding
        for binding in state.bindings
        if _model_sidecar_binding_matches_source_component(state.source_entry, binding)
        and candidates.intersection(_iter_model_sidecar_binding_submesh_keys(binding))
    )
    if matched:
        return matched
    if len(state.model_preview.meshes) == 1:
        return tuple(
            binding
            for binding in state.bindings
            if _model_sidecar_binding_matches_source_component(state.source_entry, binding)
        )
    return ()


def _assign_sidecar_material_contracts(state: _SidecarAttachmentState) -> None:
    """Promote non-texture PAC XML authority onto the preview mesh.

    This runs independently of DDS resolution. A missing preview conversion must
    not erase an explicit shader family, AlphaTest flag, or two-sided contract.
    """

    for index, mesh in enumerate(state.model_preview.meshes):
        raise_if_cancelled(state.stop_event)
        bindings = _matching_sidecar_contract_bindings(state, index, mesh)
        if not bindings:
            continue
        changed = False
        shader_family = next(
            (
                str(getattr(binding, "shader_family", "") or "").strip()
                for binding in bindings
                if str(getattr(binding, "shader_family", "") or "").strip()
            ),
            "",
        )
        if shader_family and mesh.preview_sidecar_shader_family != shader_family:
            mesh.preview_sidecar_shader_family = shader_family
            changed = True
        material_primitive = next(
            (
                str(
                    getattr(binding, "material_name", "")
                    or getattr(binding, "part_name", "")
                    or getattr(binding, "submesh_name", "")
                    or ""
                ).strip()
                for binding in bindings
                if str(
                    getattr(binding, "material_name", "")
                    or getattr(binding, "part_name", "")
                    or getattr(binding, "submesh_name", "")
                    or ""
                ).strip()
            ),
            "",
        )
        if material_primitive and mesh.preview_sidecar_material_primitive != material_primitive:
            mesh.preview_sidecar_material_primitive = material_primitive
            changed = True
        parameters = list(tuple(getattr(mesh, "preview_material_parameters", ()) or ()))
        for binding in bindings:
            for parameter in tuple(getattr(binding, "material_parameters", ()) or ()):
                if parameter not in parameters:
                    parameters.append(parameter)
        if tuple(parameters) != tuple(getattr(mesh, "preview_material_parameters", ()) or ()):
            mesh.preview_material_parameters = tuple(parameters)
            changed = True

        alpha_mode = "blend" if any(
            _model_sidecar_binding_alpha_mode(binding) == "blend" for binding in bindings
        ) else "cutout" if any(
            _model_sidecar_binding_alpha_mode(binding) == "cutout" for binding in bindings
        ) else ""
        if alpha_mode and str(getattr(mesh, "preview_alpha_mode", "") or "").strip().casefold() != alpha_mode:
            mesh.preview_alpha_mode = alpha_mode
            state.alpha_contract_count += 1
            changed = True
        alpha_cutoff = next(
            (
                cutoff
                for binding in bindings
                if (cutoff := _model_sidecar_binding_alpha_cutoff(binding)) is not None
            ),
            None,
        )
        if alpha_mode == "cutout" and alpha_cutoff is None:
            alpha_cutoff = _PAC_CUTOUT_ALPHA_CUTOFF
        if alpha_cutoff is not None:
            overrides = dict(getattr(mesh, "preview_native_material_overrides", {}) or {})
            if overrides.get("alpha_cutoff") != alpha_cutoff:
                overrides["alpha_cutoff"] = alpha_cutoff
                mesh.preview_native_material_overrides = overrides
                changed = True
        if any(_model_sidecar_binding_double_sided(binding) for binding in bindings) and not mesh.preview_double_sided:
            mesh.preview_double_sided = True
            state.double_sided_contract_count += 1
            changed = True
        if changed:
            state.material_contract_count += 1


def _sidecar_attachment_report(state: _SidecarAttachmentState) -> List[str]:
    if state.assigned_count <= 0:
        info: List[str] = []
        if state.material_contract_count:
            info.append(
                f"Applied {state.material_contract_count:,} sidecar shader/alpha material contract(s) independently of texture resolution."
            )
        if state.material_color_fallback_count:
            info.append(f"Applied {state.material_color_fallback_count:,} sidecar material color fallback(s) for meshes without a reliable visible base DDS.")
        return info
    suffix = f" from {', '.join(state.sidecar_paths[:2])}" if state.sidecar_paths else ""
    if len(state.sidecar_paths) > 2:
        suffix += " ..."
    noun = "textured preview fallback binding(s)" if state.fallback_only else "textured preview binding(s)"
    info = [f"Applied {state.assigned_count:,} {noun} from companion material sidecar data{suffix}."]
    if state.promoted_anonymous_fallback:
        info.append("Used a sidecar texture fallback because the recovered mesh preview did not preserve a reliable submesh/material name match.")
    if state.ordered_anonymous_fallback_count:
        info.append(f"Matched {state.ordered_anonymous_fallback_count:,} anonymous mesh texture preview(s) to ordered sidecar material wrapper(s).")
    if state.identity_override_count:
        info.append(f"Selected {state.identity_override_count:,} sidecar base texture preview(s) over embedded material primitive/identity name(s).")
    if state.low_authority_layer_override_count:
        info.append(f"Promoted {state.low_authority_layer_override_count:,} sidecar visible layer texture preview(s) over low-detail overlay/default base(s).")
    if state.material_color_fallback_count:
        info.append(f"Applied {state.material_color_fallback_count:,} sidecar material color fallback(s) where the visible base DDS was missing or low confidence.")
    if state.alpha_contract_count:
        info.append(f"Applied {state.alpha_contract_count:,} explicit sidecar alpha-test/blend contract(s).")
    if state.double_sided_contract_count:
        info.append(f"Applied {state.double_sided_contract_count:,} explicit sidecar two-sided contract(s).")
    return info


def _attach_model_sidecar_texture_preview_paths(
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
    state = _SidecarAttachmentState(
        source_entry=source_entry,
        model_preview=model_preview,
        parsed_submeshes=_iter_parsed_model_submeshes(parsed_mesh),
        texture_entries_by_normalized_path=texture_entries_by_normalized_path,
        texture_entries_by_basename=texture_entries_by_basename,
        sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
        sidecar_texts_by_basename=sidecar_texts_by_basename,
        allowed_visible_classes=set(_allowed_model_sidecar_visible_classes(_normalize_model_visible_texture_mode(visible_texture_mode))),
        fallback_only=fallback_only,
        stop_event=stop_event,
        bindings=sidecar_texture_bindings,
    )
    _collect_and_prefetch_sidecar_bindings(state)
    _assign_sidecar_material_contracts(state)
    _assign_matched_sidecar_bases(state)
    _assign_ordered_sidecar_bases(state)
    _promote_and_assign_global_sidecar_bases(state)
    _assign_sidecar_material_colors(state)
    return _sidecar_attachment_report(state)
