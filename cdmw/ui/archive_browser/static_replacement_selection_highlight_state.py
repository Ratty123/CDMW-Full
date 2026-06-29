"""Selection highlight routing helpers for static replacement UI."""

from __future__ import annotations

from collections.abc import Sequence


def _nonnegative_indices(raw_indices: Sequence[int]) -> tuple[int, ...]:
    normalized: list[int] = []
    for raw_index in tuple(raw_indices or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index >= 0:
            normalized.append(index)
    return tuple(normalized)


def _target_selection_view_payload(target_index: int, source_indices: Sequence[int] = ()) -> dict[str, object]:
    if int(target_index) < 0:
        return {"kind": "none", "target_indices": (), "source_indices": _nonnegative_indices(source_indices)}
    return {
        "kind": "target",
        "target_indices": (int(target_index),),
        "source_indices": _nonnegative_indices(source_indices),
    }


def _target_selection_state(raw_value: object, source_indices: Sequence[int] = ()) -> dict[str, object]:
    try:
        selected_index = int(raw_value)
    except (TypeError, ValueError):
        selected_index = -1
    target_source_indices = _nonnegative_indices(source_indices) if selected_index >= 0 else ()
    target_original_indices = (selected_index,) if selected_index >= 0 else ()
    return {
        "target_index": selected_index,
        "target_original_highlight_indices": target_original_indices,
        "target_source_highlight_indices": target_source_indices,
        "selection_view": _target_selection_view_payload(selected_index, target_source_indices),
    }


def selection_highlight_sets_state(
    *,
    selected_source_highlights: Sequence[int],
    selected_target_source_highlights: Sequence[int],
    selected_original_highlights: Sequence[int],
    selected_target_original_highlights: Sequence[int],
    d3d11_active: bool,
    geometry_active: bool,
    texture_tab_active: bool,
    mesh_edit_raw_active: bool,
    preview_gizmo_checked: bool,
    selected_source_overlay_ids: Sequence[int],
    selected_source_editor_ids: Sequence[int],
    selected_target_source_editor_ids: Sequence[int],
    disabled_source_editor_ids: Sequence[int],
    default_d3d11_editor_ids: Sequence[int],
    hovered_source_highlights: Sequence[int] = (),
    hovered_source_editor_ids: Sequence[int] = (),
    part_pick_checked: bool = False,
) -> dict[str, object]:
    selected_source_indices = _nonnegative_indices(selected_source_highlights)
    selected_target_source_indices = _nonnegative_indices(selected_target_source_highlights)
    hovered_source_indices = _nonnegative_indices(hovered_source_highlights) if bool(part_pick_checked) else ()
    selected_original_indices = _nonnegative_indices(selected_original_highlights)
    selected_target_original_indices = _nonnegative_indices(selected_target_original_highlights)
    highlighted_source_indices = tuple(
        sorted(set(selected_source_indices).union(selected_target_source_indices).union(hovered_source_indices))
    )
    highlighted_original_indices = tuple(sorted(set(selected_original_indices).union(selected_target_original_indices)))

    highlight_active = bool(geometry_active) or bool(texture_tab_active) or bool(hovered_source_indices)
    gizmo_enabled = bool(preview_gizmo_checked) and not bool(mesh_edit_raw_active)
    if not bool(d3d11_active):
        return {
            "highlighted_source_indices": highlighted_source_indices,
            "highlighted_original_indices": highlighted_original_indices,
            "d3d11_highlighted_indices": (),
            "d3d11_original_highlighted_indices": (),
            "d3d11_selected_indices": (),
            "d3d11_hidden_source_indices": (),
            "d3d11_gizmo_enabled": gizmo_enabled,
        }

    d3d11_highlight_ids: set[int] = set()
    if highlight_active:
        overlay_ids = _nonnegative_indices(selected_source_overlay_ids)
        editor_ids = _nonnegative_indices(selected_source_editor_ids)
        d3d11_highlight_ids.update(editor_ids or overlay_ids)
        d3d11_highlight_ids.update(_nonnegative_indices(selected_target_source_editor_ids))
        if bool(part_pick_checked):
            d3d11_highlight_ids.update(_nonnegative_indices(hovered_source_editor_ids))
    return {
        "highlighted_source_indices": highlighted_source_indices,
        "highlighted_original_indices": highlighted_original_indices,
        "d3d11_highlighted_indices": tuple(sorted(d3d11_highlight_ids)),
        "d3d11_original_highlighted_indices": highlighted_original_indices if highlight_active else (),
        "d3d11_selected_indices": _nonnegative_indices(default_d3d11_editor_ids) if gizmo_enabled else (),
        "d3d11_hidden_source_indices": _nonnegative_indices(disabled_source_editor_ids),
        "d3d11_gizmo_enabled": gizmo_enabled,
    }


def parts_outliner_target_selection_state(
    *,
    row_kind: str,
    target_index: int,
    source_indices: Sequence[int],
) -> dict[str, object] | None:
    if str(row_kind or "") != "target":
        return None
    selection_state = _target_selection_state(target_index, source_indices)
    return {
        "selected_target_index": selection_state["target_index"],
        "target_original_highlight_indices": selection_state["target_original_highlight_indices"],
        "target_source_highlight_indices": selection_state["target_source_highlight_indices"],
        "selection_view": selection_state["selection_view"],
    }


def texture_row_selection_highlight_state(
    *,
    source_indices: Sequence[int],
    target_index: int,
    selected_source_highlights: Sequence[int],
    selected_target_original_highlights: Sequence[int],
    transform_source_indices: Sequence[int],
) -> dict[str, object]:
    next_source_indices = _nonnegative_indices(source_indices)
    try:
        normalized_target_index = int(target_index)
    except (TypeError, ValueError):
        normalized_target_index = -1
    next_target_original_indices = (normalized_target_index,) if normalized_target_index >= 0 else ()
    unchanged = (
        set(_nonnegative_indices(selected_source_highlights)) == set(next_source_indices)
        and set(_nonnegative_indices(selected_target_original_highlights)) == set(next_target_original_indices)
        and not bool(tuple(transform_source_indices or ()))
    )
    return {
        "changed": not unchanged,
        "selected_source_index": -1,
        "selected_target_index": normalized_target_index,
        "selected_source_highlight_indices": (),
        "target_source_highlight_indices": next_source_indices,
        "target_original_highlight_indices": next_target_original_indices,
        "clear_transform_source_indices": True,
    }


__all__ = [
    "parts_outliner_target_selection_state",
    "selection_highlight_sets_state",
    "texture_row_selection_highlight_state",
]
