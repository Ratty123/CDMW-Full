"""Selection route state helpers for static replacement UI."""

from __future__ import annotations

from collections.abc import Sequence

from cdmw.ui.archive_browser.static_replacement_selection_view_state import (
    d3d11_source_selection_index,
    original_selection_state,
    selection_filter_refresh_needed,
    selection_view_update_kwargs,
    source_selection_state,
    target_selection_state,
)


def source_selection_route_state(
    source_index: int,
    target_indices: Sequence[int],
    *,
    has_filter_refresh: bool,
    selected_filter_enabled: bool,
) -> dict[str, object]:
    state = source_selection_state(source_index, target_indices)
    transform_source_indices = tuple(state["transform_source_indices"])  # type: ignore[arg-type]
    return {
        **state,
        "selection_view_kwargs": selection_view_update_kwargs(state["selection_view"]),  # type: ignore[arg-type]
        "clear_transform_source_indices": not bool(transform_source_indices),
        "refresh_filter": selection_filter_refresh_needed(
            has_filter_refresh=has_filter_refresh,
            selected_filter_enabled=selected_filter_enabled,
        ),
    }


def d3d11_source_part_selection_route(
    *,
    preview_active: bool,
    geometry_tab_active: bool,
    source_index: object,
    current_source_index: object,
    editor_source_indices: Sequence[int],
) -> dict[str, object]:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    selected_source_index = d3d11_source_selection_index(current_source_index, editor_source_indices)
    return {
        "source_index": normalized_source_index,
        "selected_source_index": selected_source_index,
        "should_select": bool(
            preview_active
            and geometry_tab_active
            and normalized_source_index >= 0
            and selected_source_index >= 0
        ),
    }


def original_selection_route_state(raw_indices: object) -> dict[str, object]:
    state = original_selection_state(raw_indices)
    return {
        **state,
        "selection_view_kwargs": selection_view_update_kwargs(state["selection_view"]),  # type: ignore[arg-type]
    }


def target_selection_route_state(raw_value: object, source_indices: Sequence[int] = ()) -> dict[str, object]:
    state = target_selection_state(raw_value, source_indices)
    return {
        **state,
        "outliner_source_selection": tuple(sorted(state["target_source_highlight_indices"])),  # type: ignore[arg-type]
        "selection_view_kwargs": selection_view_update_kwargs(state["selection_view"]),  # type: ignore[arg-type]
    }


__all__ = [
    "d3d11_source_part_selection_route",
    "original_selection_route_state",
    "source_selection_route_state",
    "target_selection_route_state",
]
