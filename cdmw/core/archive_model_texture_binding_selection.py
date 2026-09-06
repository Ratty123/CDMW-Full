"""Exact submesh identity and sidecar texture-binding selection."""

from __future__ import annotations

from functools import lru_cache
from pathlib import PurePosixPath
from typing import List, Optional, Sequence, Tuple
from cdmw.core.archive_model_references import (
    _ArchiveModelSidecarTextureBinding,
    _normalize_model_submesh_reference,
    _normalize_model_texture_reference,
)
from cdmw.rendering.crimson_shader_registry import normalize_shader_family


def _iter_parsed_model_submeshes(parsed_mesh: Optional[object]) -> List[object]:
    if parsed_mesh is None:
        return []
    if str(getattr(parsed_mesh, "format", "") or "").strip().lower() == "pamlod":
        lod_levels = getattr(parsed_mesh, "lod_levels", None) or [[]]
        return list(lod_levels[0] or [])
    return list(getattr(parsed_mesh, "submeshes", ()) or [])


@lru_cache(maxsize=16384)
def _normalize_model_submesh_exact_reference(value: str) -> str:
    raw_text = str(value or "").replace("\\", "/").strip().lower()
    if not raw_text:
        return ""
    return (PurePosixPath(raw_text).name or raw_text).strip().lower()


@lru_cache(maxsize=8192)
def _iter_model_submesh_exact_reference_candidates(*values: str) -> Tuple[str, ...]:
    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_submesh_exact_reference(raw_value)
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


@lru_cache(maxsize=8192)
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


def _iter_model_sidecar_binding_exact_submesh_keys(
    binding: _ArchiveModelSidecarTextureBinding,
) -> Tuple[str, ...]:
    values: List[str] = [
        str(getattr(binding, "submesh_name", "") or ""),
        str(getattr(binding, "part_name", "") or ""),
        str(getattr(binding, "material_name", "") or ""),
    ]
    explicit_keys = _iter_model_submesh_exact_reference_candidates(*values)
    if explicit_keys:
        return explicit_keys
    linked_mesh_path = str(getattr(binding, "linked_mesh_path", "") or "").replace("\\", "/").strip()
    if linked_mesh_path:
        linked_mesh = PurePosixPath(linked_mesh_path)
        values.extend([linked_mesh_path, linked_mesh.name, linked_mesh.stem])
    return _iter_model_submesh_exact_reference_candidates(*values)


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


def _prefer_authoritative_skin_wrapper_variant(
    bindings: Sequence[_ArchiveModelSidecarTextureBinding],
) -> Tuple[_ArchiveModelSidecarTextureBinding, ...]:
    """Drop a Standard duplicate only when it aliases an authoritative Skin ``_sp``.

    Some nude PAC XML files declare the same head/hand/body material once with
    ``SkinnedMeshSkin`` and again with ``SkinnedMeshStandard``.  The visible
    base, normal, and ``_materialTexture`` references are identical, but only
    the Skin wrapper gives ``_materialTexture`` its skin-response channel
    contract.  Keep the complete Skin wrapper in that exact duplicate case so
    downstream support-map compilation cannot retain the Standard source kind
    merely because of wrapper order.
    """

    def wrapper_key(
        binding: _ArchiveModelSidecarTextureBinding,
    ) -> Tuple[str, object] | None:
        item_id = str(getattr(binding, "owner_wrapper_item_id", "") or "").strip()
        if item_id:
            return ("item", item_id)
        try:
            owner_slot_index = int(getattr(binding, "owner_slot_index", -1))
        except (TypeError, ValueError, OverflowError):
            owner_slot_index = -1
        return ("slot", owner_slot_index) if owner_slot_index >= 0 else None

    def owner_identity(binding: _ArchiveModelSidecarTextureBinding) -> str:
        for value in (
            str(getattr(binding, "material_name", "") or ""),
            str(getattr(binding, "part_name", "") or ""),
            str(getattr(binding, "submesh_name", "") or ""),
        ):
            candidates = _iter_model_submesh_exact_reference_candidates(value)
            if candidates:
                return candidates[0]
        return ""

    skin_edges: dict[Tuple[str, str, str], set[Tuple[str, object]]] = {}
    standard_edges: dict[Tuple[str, str, str], set[Tuple[str, object]]] = {}
    for binding in bindings:
        key = wrapper_key(binding)
        owner = owner_identity(binding)
        parameter = str(getattr(binding, "parameter_name", "") or "").strip().casefold()
        texture_path = _normalize_model_texture_reference(
            str(getattr(binding, "texture_path", "") or "")
        )
        if key is None or not owner or parameter != "_materialtexture" or not texture_path:
            continue
        family = normalize_shader_family(
            str(getattr(binding, "shader_family", "") or "")
        )
        source_kind = str(getattr(binding, "source_kind", "") or "").strip().casefold()
        edge = (owner, parameter, texture_path)
        if family == "skin" and source_kind == "crimson_skin_material_response":
            skin_edges.setdefault(edge, set()).add(key)
        elif family in {"standard", "standard_v2"}:
            standard_edges.setdefault(edge, set()).add(key)

    duplicate_edges = skin_edges.keys() & standard_edges.keys()
    if not duplicate_edges:
        return tuple(bindings)
    duplicate_standard_wrappers = {
        wrapper
        for edge in duplicate_edges
        for wrapper in standard_edges[edge]
    }
    return tuple(
        binding
        for binding in bindings
        if wrapper_key(binding) not in duplicate_standard_wrappers
    )


def _sidecar_binding_identity_components(bindings):
    identity_components: List[
        Tuple[
            Tuple[_ArchiveModelSidecarTextureBinding, ...],
            frozenset[str],
            frozenset[str],
        ]
    ] = []

    def owner_keys(
        binding: _ArchiveModelSidecarTextureBinding,
    ) -> frozenset[str]:
        for value in (
            str(getattr(binding, "submesh_name", "") or ""),
            str(getattr(binding, "part_name", "") or ""),
            str(getattr(binding, "material_name", "") or ""),
            str(getattr(binding, "linked_mesh_path", "") or ""),
        ):
            keys = _iter_model_submesh_exact_reference_candidates(value)
            if keys:
                return frozenset(keys)
        return frozenset()

    remaining = list(bindings)
    while remaining:
        component = [remaining.pop(0)]
        component_owner_keys = set(owner_keys(component[0]))
        component_alias_keys = set(
            _iter_model_sidecar_binding_exact_submesh_keys(component[0])
        )
        expanded = True
        while expanded:
            expanded = False
            for binding in tuple(remaining):
                binding_owner_keys = set(owner_keys(binding))
                if (
                    not component_owner_keys
                    or not binding_owner_keys
                    or component_owner_keys.isdisjoint(binding_owner_keys)
                ):
                    continue
                remaining.remove(binding)
                component.append(binding)
                component_owner_keys.update(binding_owner_keys)
                component_alias_keys.update(
                    _iter_model_sidecar_binding_exact_submesh_keys(binding)
                )
                expanded = True
        identity_components.append(
            (
                tuple(component),
                frozenset(component_owner_keys),
                frozenset(component_alias_keys),
            )
        )
    return identity_components


def _select_model_sidecar_bindings_for_submesh(
    bindings: Sequence[_ArchiveModelSidecarTextureBinding],
    *,
    exact_candidates: Sequence[str],
    fuzzy_candidates: Sequence[str],
) -> Tuple[_ArchiveModelSidecarTextureBinding, ...]:
    identity_components = _sidecar_binding_identity_components(bindings)

    ordered_exact_keys = tuple(
        dict.fromkeys(
            str(value or "").strip().lower()
            for value in exact_candidates
            if str(value or "").strip()
        )
    )
    for exact_key in ordered_exact_keys:
        owner_matches = [
            index
            for index, (_component, component_owner_keys, _component_alias_keys) in enumerate(
                identity_components
            )
            if exact_key in component_owner_keys
        ]
        if len(owner_matches) > 1:
            return ()
        if len(owner_matches) == 1:
            selected_ids = {
                id(binding)
                for binding in identity_components[owner_matches[0]][0]
            }
            return _prefer_authoritative_skin_wrapper_variant(
                tuple(binding for binding in bindings if id(binding) in selected_ids)
            )

    for exact_key in ordered_exact_keys:
        alias_matches = [
            index
            for index, (_component, _component_owner_keys, component_alias_keys) in enumerate(
                identity_components
            )
            if exact_key in component_alias_keys
        ]
        if len(alias_matches) > 1:
            return ()
        if len(alias_matches) == 1:
            selected_ids = {
                id(binding)
                for binding in identity_components[alias_matches[0]][0]
            }
            return _prefer_authoritative_skin_wrapper_variant(
                tuple(binding for binding in bindings if id(binding) in selected_ids)
            )

    fuzzy_component_indexes: set[int] = set()
    for fuzzy_key in fuzzy_candidates:
        normalized_fuzzy = str(fuzzy_key or "").strip().lower()
        if not normalized_fuzzy:
            continue
        owner_matches = [
            index
            for index, (_component, component_owner_keys, _component_alias_keys) in enumerate(
                identity_components
            )
            if any(
                _normalize_model_submesh_reference(exact_key) == normalized_fuzzy
                for exact_key in component_owner_keys
            )
        ]
        if len(owner_matches) == 1:
            fuzzy_component_indexes.add(owner_matches[0])
            continue
        if owner_matches:
            return ()
        alias_matches = [
            index
            for index, (_component, _component_owner_keys, component_alias_keys) in enumerate(
                identity_components
            )
            if any(
                _normalize_model_submesh_reference(exact_key) == normalized_fuzzy
                for exact_key in component_alias_keys
            )
        ]
        if len(alias_matches) == 1:
            fuzzy_component_indexes.add(alias_matches[0])
        elif alias_matches:
            return ()

    if len(fuzzy_component_indexes) != 1:
        return ()
    selected_component_index = next(iter(fuzzy_component_indexes))
    selected_ids = {
        id(binding)
        for binding in identity_components[selected_component_index][0]
    }
    return _prefer_authoritative_skin_wrapper_variant(
        tuple(binding for binding in bindings if id(binding) in selected_ids)
    )
