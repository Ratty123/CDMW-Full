"""Pure D3D11 editor/source id mapping helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence

from cdmw.ui.archive_browser.static_replacement_preview_models import combine_alignment_preview_models


def alignment_d3d11_editor_ids_for_source_indices(
    source_indices: Sequence[int],
    state: Mapping[str, object],
    *,
    selection_overlay: bool = False,
) -> tuple[int, ...]:
    source_to_editor = state.get(
        "source_selection_overlay_to_d3d11_ids" if selection_overlay else "source_to_d3d11_ids"
    )
    has_editor_map = isinstance(source_to_editor, Mapping) and bool(source_to_editor)
    editor_ids: set[int] = set()
    for raw_index in tuple(source_indices or ()):
        try:
            source_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        mapped_ids: tuple[int, ...] = ()
        if has_editor_map:
            raw_mapped = source_to_editor.get(source_index, ())
            try:
                mapped_ids = tuple(int(editor_id) for editor_id in tuple(raw_mapped or ()) if int(editor_id) >= 0)
            except (TypeError, ValueError):
                mapped_ids = ()
        if mapped_ids:
            editor_ids.update(mapped_ids)
        elif not selection_overlay and not has_editor_map and source_index >= 0:
            editor_ids.add(source_index)
    return tuple(sorted(editor_ids))


def alignment_d3d11_source_indices_for_editor_id(
    editor_id: int,
    state: Mapping[str, object],
) -> tuple[int, ...]:
    try:
        editor_id = int(editor_id)
    except (TypeError, ValueError):
        return ()
    editor_to_source = state.get("d3d11_id_to_source_indices")
    if isinstance(editor_to_source, Mapping) and editor_to_source:
        raw_sources = editor_to_source.get(editor_id, ())
        try:
            source_indices = tuple(sorted({int(source_index) for source_index in tuple(raw_sources or ()) if int(source_index) >= 0}))
            if source_indices:
                return source_indices
        except (TypeError, ValueError):
            pass
    overlay_editor_to_source = state.get("selection_overlay_d3d11_id_to_source_indices")
    if isinstance(overlay_editor_to_source, Mapping) and overlay_editor_to_source:
        raw_sources = overlay_editor_to_source.get(editor_id, ())
        try:
            return tuple(sorted({int(source_index) for source_index in tuple(raw_sources or ()) if int(source_index) >= 0}))
        except (TypeError, ValueError):
            return ()
    return (editor_id,) if editor_id >= 0 else ()


def _normalized_id_map(mapping: Mapping[object, object]) -> dict[int, tuple[int, ...]]:
    normalized: dict[int, tuple[int, ...]] = {}
    for raw_key, raw_values in mapping.items():
        try:
            key = int(raw_key)
            values = tuple(int(value) for value in tuple(raw_values or ()))
        except (TypeError, ValueError):
            continue
        normalized[key] = tuple(sorted(values))
    return normalized


def alignment_d3d11_record_source_editor_id_maps(
    state: MutableMapping[str, object],
    *,
    source_to_editor: Mapping[object, object],
    selection_overlay_to_editor: Mapping[object, object],
    editor_to_source: Mapping[object, object],
    selection_editor_to_source: Mapping[object, object],
) -> None:
    state["source_to_d3d11_ids"] = _normalized_id_map(source_to_editor)
    state["source_selection_overlay_to_d3d11_ids"] = _normalized_id_map(selection_overlay_to_editor)
    state["d3d11_id_to_source_indices"] = _normalized_id_map(editor_to_source)
    state["selection_overlay_d3d11_id_to_source_indices"] = _normalized_id_map(selection_editor_to_source)


def alignment_d3d11_preview_source_editor_id_map_state(
    preview_model: object,
    *,
    mapped_preview: bool,
    current_mappings: Sequence[object],
    source_overlay_preview_index_map: Mapping[int, int],
    source_selection_overlay_preview_index_map: Mapping[int, int],
    direct_source_preview_index_map: Mapping[int, int],
    preview_submesh_index_map: Mapping[int, int],
    preview_target_mesh_indices: Callable[[object, str, Sequence[int], bool, Sequence[object]], Sequence[int]],
) -> dict[str, dict[int, set[int]]]:
    meshes = tuple(getattr(preview_model, "meshes", ()) or ())
    source_to_editor: dict[int, set[int]] = {}
    editor_to_source: dict[int, set[int]] = {}
    selection_overlay_to_editor: dict[int, set[int]] = {}
    selection_editor_to_source: dict[int, set[int]] = {}

    def editor_id_for_preview_index(preview_index: int) -> int:
        if preview_index < 0 or preview_index >= len(meshes):
            return -1
        try:
            return int(getattr(meshes[preview_index], "source_submesh_index", -1))
        except (TypeError, ValueError):
            return -1

    def add_mapping(source_index: int, editor_id: int) -> None:
        try:
            source_index = int(source_index)
            editor_id = int(editor_id)
        except (TypeError, ValueError):
            return
        if source_index < 0 or editor_id < 0:
            return
        source_to_editor.setdefault(source_index, set()).add(editor_id)
        editor_to_source.setdefault(editor_id, set()).add(source_index)

    if mapped_preview:
        for source_index, preview_index in source_overlay_preview_index_map.items():
            add_mapping(int(source_index), editor_id_for_preview_index(int(preview_index)))
        for source_index, preview_index in source_selection_overlay_preview_index_map.items():
            editor_id = editor_id_for_preview_index(int(preview_index))
            if int(source_index) >= 0 and editor_id >= 0:
                selection_overlay_to_editor.setdefault(int(source_index), set()).add(editor_id)
                selection_editor_to_source.setdefault(editor_id, set()).add(int(source_index))
        for mapping in tuple(current_mappings or ()):
            source_indices = tuple(int(index) for index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()))
            if not source_indices:
                continue
            target_preview_indices = preview_target_mesh_indices(
                preview_model,
                str(getattr(mapping, "target_submesh_name", "") or ""),
                source_indices,
                True,
                current_mappings,
            )
            editor_ids = {
                editor_id_for_preview_index(int(preview_index))
                for preview_index in target_preview_indices
            }
            editor_ids = {editor_id for editor_id in editor_ids if editor_id >= 0}
            if not editor_ids:
                preview_index = preview_submesh_index_map.get(int(getattr(mapping, "target_submesh_index", -1)))
                if preview_index is not None:
                    editor_id = editor_id_for_preview_index(int(preview_index))
                    if editor_id >= 0:
                        editor_ids.add(editor_id)
            for source_index in source_indices:
                for editor_id in editor_ids:
                    add_mapping(source_index, editor_id)
    elif direct_source_preview_index_map:
        for source_index, preview_index in direct_source_preview_index_map.items():
            add_mapping(int(source_index), editor_id_for_preview_index(int(preview_index)))
    else:
        for mesh_index, _mesh in enumerate(meshes):
            editor_id = editor_id_for_preview_index(mesh_index)
            add_mapping(editor_id, editor_id)

    return {
        "source_to_editor": source_to_editor,
        "selection_overlay_to_editor": selection_overlay_to_editor,
        "editor_to_source": editor_to_source,
        "selection_editor_to_source": selection_editor_to_source,
    }


def alignment_d3d11_record_direct_source_preview_flags(
    state: MutableMapping[str, object],
    *,
    replacement_only_direct_source_preview: bool,
    source_owned_direct_source_preview: bool,
) -> bool:
    replacement_only = bool(replacement_only_direct_source_preview)
    source_owned = bool(source_owned_direct_source_preview)
    force_direct = bool(replacement_only or source_owned)
    state["replacement_only_direct_source_preview"] = replacement_only
    state["source_owned_direct_source_preview"] = source_owned
    state["force_direct_source_preview"] = force_direct
    return force_direct


def alignment_d3d11_display_model(
    preview_model: object,
    original_reference_model: object | None,
    *,
    active_preview_mode: str,
    tag_workspace_model: Callable[..., object | None],
    combine_preview_models: Callable[..., object | None],
    clone_model: Callable[[object], object],
    preserve_overlays: bool = False,
    external_import: bool = False,
    show_physics_overlay: bool = False,
) -> object | None:
    replacement_workspace = tag_workspace_model(
        preview_model,
        "replacement_preview",
        editable=True,
        clone_model=clone_model,
    )
    if replacement_workspace is None:
        return None
    if str(active_preview_mode or "") == "replacement_only" or original_reference_model is None:
        return replacement_workspace
    original_workspace = tag_workspace_model(
        clone_model(original_reference_model),
        "original_reference",
        editable=False,
        clone_model=clone_model,
    )
    if original_workspace is None:
        return replacement_workspace
    preserve = bool(preserve_overlays and not external_import and show_physics_overlay)
    # Source guard compatibility: or combine_preview_models(original_workspace, replacement_workspace)
    combined = combine_alignment_preview_models(
        original_workspace,
        replacement_workspace,
        preserve_overlays=preserve,
    )
    if combined is not None:
        return combined
    try:
        return combine_preview_models(
            original_workspace,
            replacement_workspace,
            preserve_overlays=preserve,
        )
    except TypeError:
        return combine_preview_models(original_workspace, replacement_workspace)


def alignment_default_d3d11_editor_ids(
    transform_source_indices: Sequence[int],
    replacement_submesh_count: int,
    *,
    source_index_is_enabled_renderable: Callable[[int], bool],
    editor_ids_for_source_indices: Callable[[Sequence[int]], tuple[int, ...]],
) -> tuple[int, ...]:
    selected_editor_ids = editor_ids_for_source_indices(tuple(transform_source_indices or ()))
    if selected_editor_ids:
        return selected_editor_ids
    try:
        replacement_submesh_count = int(replacement_submesh_count)
    except (TypeError, ValueError):
        replacement_submesh_count = 0
    replacement_source_indices = tuple(
        source_index
        for source_index in range(max(0, replacement_submesh_count))
        if source_index_is_enabled_renderable(source_index)
    )
    if not replacement_source_indices:
        return ()
    return editor_ids_for_source_indices(replacement_source_indices)


__all__ = [
    "alignment_default_d3d11_editor_ids",
    "alignment_d3d11_display_model",
    "alignment_d3d11_editor_ids_for_source_indices",
    "alignment_d3d11_preview_source_editor_id_map_state",
    "alignment_d3d11_record_direct_source_preview_flags",
    "alignment_d3d11_record_source_editor_id_maps",
    "alignment_d3d11_source_indices_for_editor_id",
]
