"""Source tree selection state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceTreeLayoutState:
    minimum_height: int
    configure_widths: tuple[int, ...]
    autofit_min_widths: tuple[int, ...]
    autofit_max_widths: tuple[int, ...]
    expand_columns: tuple[int, ...]
    max_height: int
    height_fit_kwargs: dict[str, int]
    persist_key: str


@dataclass(frozen=True, slots=True)
class SourceTreePopulationChunkPolicy:
    row_limit: int
    time_budget_seconds: float


@dataclass(frozen=True, slots=True)
class SourceTreeItemState:
    source_index: int
    geometry_text: str
    source_name: str
    source_material: str
    copied_texture_count: int
    copied_texture_disabled: bool
    enabled: bool


@dataclass(frozen=True, slots=True)
class SourceTreeContextMenuSelectionState:
    selected_source_indices: tuple[int, ...]
    select_clicked_item: bool
    clear_multi_indices: bool


def source_tree_control_text() -> dict[str, object]:
    return {
        "original_label_html": "<span style='color:#79c0ff; font-weight:700;'>Original reference parts</span>",
        "replacement_label_html": "<span style='color:#79c0ff; font-weight:700;'>Replacement reference parts</span>",
        "source_group_title": "Replacement reference parts",
        "source_tree_headers": ["Use", "#", "Source", "Role", "Target", "Status", "Geometry"],
    }


def source_tree_layout_state() -> SourceTreeLayoutState:
    return SourceTreeLayoutState(
        minimum_height=108,
        configure_widths=(42, 36, 120, 64, 120, 62, 96),
        autofit_min_widths=(34, 30, 90, 60, 90, 60, 110),
        autofit_max_widths=(48, 46, 220, 140, 220, 110, 180),
        expand_columns=(2, 4, 6),
        max_height=360,
        height_fit_kwargs={"minimum": 108, "screen_margin": 420, "maximum": 260},
        persist_key="source_parts",
    )


def source_tree_role_menu_specs(role_options: Sequence[tuple[object, object]]) -> tuple[tuple[str, str], ...]:
    return tuple((str(label), str(role_value or "")) for label, role_value in tuple(role_options or ()))


def source_tree_population_chunk_policy() -> SourceTreePopulationChunkPolicy:
    return SourceTreePopulationChunkPolicy(row_limit=40, time_budget_seconds=0.006)


def source_tree_population_queued_text(total_rows: int) -> str:
    return f"Replacement source list queued: 0 / {int(total_rows):,} row(s). Preview can open while rows load."


def source_tree_population_loading_text(current_rows: int, total_rows: int) -> str:
    return f"Replacement source list loading: {int(current_rows):,} / {int(total_rows):,} row(s)."


def source_tree_population_ready_text(total_rows: int) -> str:
    return f"Replacement source list ready: {int(total_rows):,} row(s)."


def source_tree_context_selection_initial_state() -> dict[str, object]:
    return {"multi_indices": (), "right_press": False}


def source_tree_item_update_guard_initial_state() -> dict[str, bool]:
    return {"active": False}


def source_tree_context_selection_set_right_press(
    state: MutableMapping[str, object],
    active: bool,
) -> None:
    state["right_press"] = bool(active)


def source_tree_context_selection_right_press(state: Mapping[str, object]) -> bool:
    return bool(state.get("right_press"))


def source_tree_context_selection_record_multi_indices(
    state: MutableMapping[str, object],
    source_indices: Sequence[int],
) -> None:
    state["multi_indices"] = tuple(int(index) for index in tuple(source_indices or ()))


def source_tree_context_selection_clear_multi_indices(state: MutableMapping[str, object]) -> None:
    state["multi_indices"] = ()


def source_tree_context_selection_multi_indices(state: Mapping[str, object]) -> tuple[int, ...]:
    return tuple(int(index) for index in tuple(state.get("multi_indices", ()) or ()))


def source_tree_context_selection_action(
    source_indices: Sequence[int],
    *,
    right_press_active: bool,
) -> str:
    if len(tuple(source_indices or ())) > 1:
        return "record_multi"
    if not bool(right_press_active):
        return "clear_multi"
    return "none"


def source_tree_context_menu_selection_state(
    *,
    clicked_source_index: object,
    selected_source_indices: Sequence[int],
    preserved_multi_indices: Sequence[int],
    clicked_item_selected: bool,
) -> SourceTreeContextMenuSelectionState:
    try:
        clicked_index = int(clicked_source_index)
    except (TypeError, ValueError):
        clicked_index = -1
    normalized_selected = tuple(int(index) for index in tuple(selected_source_indices or ()))
    normalized_preserved = tuple(int(index) for index in tuple(preserved_multi_indices or ()))
    if (
        len(normalized_selected) <= 1
        and len(normalized_preserved) > 1
        and clicked_index in normalized_preserved
    ):
        return SourceTreeContextMenuSelectionState(
            selected_source_indices=normalized_preserved,
            select_clicked_item=False,
            clear_multi_indices=False,
        )
    should_select_clicked = bool(clicked_index >= 0 and not clicked_item_selected and clicked_index not in normalized_selected)
    return SourceTreeContextMenuSelectionState(
        selected_source_indices=(clicked_index,) if should_select_clicked else normalized_selected,
        select_clicked_item=should_select_clicked,
        clear_multi_indices=should_select_clicked,
    )


def source_tree_current_selection_index(current_index: int, selected_indices: Sequence[int]) -> int:
    try:
        normalized_current = int(current_index)
    except (TypeError, ValueError):
        normalized_current = -1
    if normalized_current >= 0:
        return normalized_current
    for raw_index in tuple(selected_indices or ()):
        try:
            selected_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if selected_index >= 0:
            return selected_index
    return -1


def source_tree_population_initial_state() -> dict[str, object]:
    return {"next_index": 0, "complete": False}


def source_tree_population_mark_complete(state: MutableMapping[str, object]) -> None:
    state["complete"] = True


def source_tree_population_complete(state: Mapping[str, object]) -> bool:
    return bool(state.get("complete"))


def source_tree_population_next_index(state: Mapping[str, object]) -> int:
    return int(state.get("next_index", 0) or 0)


def source_tree_population_set_next_index(
    state: MutableMapping[str, object],
    next_index: int,
) -> None:
    state["next_index"] = int(next_index)


def source_tree_item_state(
    *,
    source_index: object,
    source: object,
    copied_texture_rows: Sequence[object],
    copied_texture_disabled: object,
    adjustment: object | None,
) -> SourceTreeItemState:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    geometry_text = (
        f"{len(getattr(source, 'vertices', ()) or ()):,.0f} vertices, "
        f"{len(getattr(source, 'faces', ()) or ()):,.0f} faces"
    )
    return SourceTreeItemState(
        source_index=normalized_source_index,
        geometry_text=geometry_text,
        source_name=str(getattr(source, "name", "") or ""),
        source_material=str(getattr(source, "material", "") or ""),
        copied_texture_count=len(tuple(copied_texture_rows or ())),
        copied_texture_disabled=bool(copied_texture_disabled),
        enabled=adjustment is None or bool(getattr(adjustment, "enabled", True)),
    )


__all__ = [
    "SourceTreeContextMenuSelectionState",
    "SourceTreeItemState",
    "SourceTreeLayoutState",
    "SourceTreePopulationChunkPolicy",
    "source_tree_context_selection_action",
    "source_tree_context_selection_clear_multi_indices",
    "source_tree_context_menu_selection_state",
    "source_tree_current_selection_index",
    "source_tree_context_selection_initial_state",
    "source_tree_context_selection_multi_indices",
    "source_tree_context_selection_record_multi_indices",
    "source_tree_context_selection_right_press",
    "source_tree_context_selection_set_right_press",
    "source_tree_control_text",
    "source_tree_item_state",
    "source_tree_item_update_guard_initial_state",
    "source_tree_layout_state",
    "source_tree_population_chunk_policy",
    "source_tree_population_complete",
    "source_tree_population_initial_state",
    "source_tree_population_loading_text",
    "source_tree_population_mark_complete",
    "source_tree_population_next_index",
    "source_tree_population_queued_text",
    "source_tree_population_ready_text",
    "source_tree_population_set_next_index",
    "source_tree_role_menu_specs",
]
