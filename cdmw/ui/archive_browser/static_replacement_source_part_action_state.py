"""Selected source-part action/status state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourcePartDeleteSelectionState:
    delete_indices: frozenset[int]
    status_key: str
    available: bool


@dataclass(frozen=True, slots=True)
class SourcePartDeleteIndexMapState:
    index_map: dict[int, int]
    kept_indices: tuple[int, ...]
    deleted_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SourcePartContextActionSpec:
    key: str
    label: str
    enabled: bool
    unavailable_reason: str = ""


def source_part_context_menu_text() -> dict[str, str]:
    return {
        "select_only": "Select Only",
        "toggle_selection": "Toggle Selection",
        "duplicate": "Duplicate Selected Part(s)",
        "delete_selected_parts": "Delete Selected Part(s)",
        "hide_selected_parts": "Hide Selected Part(s)",
        "show_selected_parts": "Show Selected Part(s)",
        "route_selected_target": "Route to Selected Target",
        "undo": "Undo Part Action",
        "redo": "Redo Part Action",
        "reset": "Reset Part",
        "apply": "Apply",
        "set_role_glow": "Set Role: Glow / emissive",
        "set_role_auto": "Set Role: Auto / inferred",
    }


def source_part_context_action_specs(
    *,
    has_selection: bool,
    all_visible: bool,
    can_route: bool,
    can_undo: bool,
    can_redo: bool,
) -> tuple[SourcePartContextActionSpec, ...]:
    text = source_part_context_menu_text()
    selected = bool(has_selection)
    return (
        SourcePartContextActionSpec("select_only", text["select_only"], selected),
        SourcePartContextActionSpec("toggle_selection", text["toggle_selection"], selected),
        SourcePartContextActionSpec("duplicate", text["duplicate"], selected),
        SourcePartContextActionSpec("delete", text["delete_selected_parts"], selected),
        SourcePartContextActionSpec("set_role_glow", text["set_role_glow"], selected),
        SourcePartContextActionSpec("set_role_auto", text["set_role_auto"], selected),
        SourcePartContextActionSpec(
            "toggle_visibility",
            text["hide_selected_parts" if all_visible else "show_selected_parts"],
            selected,
        ),
        SourcePartContextActionSpec("route_selected_target", text["route_selected_target"], selected and can_route),
        SourcePartContextActionSpec("undo", text["undo"], bool(can_undo)),
        SourcePartContextActionSpec("redo", text["redo"], bool(can_redo)),
        SourcePartContextActionSpec(
            "reset",
            text["reset"],
            False,
            "Resident part reset is disabled until a native reset command is supported.",
        ),
    )


def dispatch_source_part_context_action(
    action_key: object,
    handlers: Mapping[str, Callable[[], object]],
) -> bool:
    handler = handlers.get(str(action_key or "").strip().lower())
    return bool(callable(handler) and handler() is not False)


def source_part_delete_status_text() -> dict[str, str]:
    return {
        "select_first": "Select replacement source part(s) to delete first.",
        "none_deletable": "No deletable replacement source part selected.",
        "undo_label": "Delete source part",
    }


def source_part_delete_selection_state(
    selected_indices: Sequence[int],
    *,
    source_count: int,
    marker_source_indices: Sequence[int] = (),
) -> SourcePartDeleteSelectionState:
    selected = tuple(selected_indices or ())
    if not selected:
        return SourcePartDeleteSelectionState(frozenset(), "select_first", False)
    markers = {
        int(index)
        for index in tuple(marker_source_indices or ())
        if str(index).lstrip("-").isdigit()
    }
    try:
        normalized_source_count = max(0, int(source_count))
    except (TypeError, ValueError):
        normalized_source_count = 0
    delete_indices: set[int] = set()
    for raw_index in selected:
        try:
            source_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= source_index < normalized_source_count and source_index not in markers:
            delete_indices.add(source_index)
    if not delete_indices:
        return SourcePartDeleteSelectionState(frozenset(), "none_deletable", False)
    return SourcePartDeleteSelectionState(frozenset(delete_indices), "", True)


def source_part_delete_index_map_state(
    *,
    source_count: int,
    delete_indices: Sequence[int],
) -> SourcePartDeleteIndexMapState:
    try:
        normalized_source_count = max(0, int(source_count))
    except (TypeError, ValueError):
        normalized_source_count = 0
    deleted = {
        int(index)
        for index in tuple(delete_indices or ())
        if str(index).lstrip("-").isdigit()
    }
    index_map: dict[int, int] = {}
    kept_indices: list[int] = []
    for old_index in range(normalized_source_count):
        if old_index in deleted:
            continue
        index_map[old_index] = len(kept_indices)
        kept_indices.append(old_index)
    return SourcePartDeleteIndexMapState(
        index_map=index_map,
        kept_indices=tuple(kept_indices),
        deleted_indices=tuple(sorted(index for index in deleted if 0 <= index < normalized_source_count)),
    )


def source_part_deleted_pending_reason(delete_count: int) -> str:
    return f"deleted {int(delete_count):,} source part(s); target routes were unassigned/remapped"


def source_part_deleted_status(delete_count: int) -> str:
    return f"Deleted {int(delete_count):,} replacement source part(s). Preview is rebuilding."


def source_part_group_routing_text() -> dict[str, str]:
    return {
        "no_source_title": "No Source Parts",
        "no_source_message": "There are no active replacement source parts to route.",
        "no_target_title": "No Target Slots",
        "no_target_message": "The original model has no draw/material slots to route into.",
        "undo_label": "Group routing by source material",
        "clear_manual_title": "Clear Manual DDS Overrides?",
        "clear_manual_message": (
            "Manual original-DDS override assignments can force the old slot layout and hide the source-material routing. "
            "Clear those override assignments before grouping by source material?"
        ),
        "overflow_title": "Material Groups Exceed Target Slots",
    }


def source_part_group_routing_overflow_message(overflow_groups: Sequence[str]) -> str:
    groups = tuple(str(group) for group in tuple(overflow_groups or ()))
    displayed_groups = f"{', '.join(groups[:8])}{'...' if len(groups) > 8 else ''}"
    return (
        "The replacement has more source material group(s) than original target draw slot(s). "
        "Some groups still had to be merged, so those parts cannot keep separate textures unless you split the mesh "
        "differently or bake/atlas textures first.\n\n"
        f"Merged groups: {displayed_groups}"
    )


def source_part_include_exclude_pending_reason() -> str:
    return "source include/exclude changed"


def source_part_routing_preview_action(
    *,
    defer_preview: bool,
    pending_reason: str,
) -> dict[str, object]:
    if bool(defer_preview):
        return {"apply_pending": True, "pending_reason": str(pending_reason or "source routing changed"), "queue_preview": False}
    return {"apply_pending": False, "pending_reason": "", "queue_preview": True}


def source_part_edit_undo_label(action: str) -> str:
    labels = {
        "adjust": "Adjust source part",
        "toggle": "Toggle source output",
        "role": "Change source part role",
        "glow": "Change accent glow color",
        "unmap": "Unmap source part",
        "reset": "Reset source part",
        "remove": "Remove source part from output",
        "fit": "Fit source part size",
        "nudge": "Nudge source part",
        "center": "Center source part on target",
    }
    return labels.get(str(action or "").strip(), "")


__all__ = [
    "SourcePartContextActionSpec",
    "SourcePartDeleteIndexMapState",
    "SourcePartDeleteSelectionState",
    "source_part_context_menu_text",
    "source_part_context_action_specs",
    "dispatch_source_part_context_action",
    "source_part_delete_index_map_state",
    "source_part_delete_selection_state",
    "source_part_delete_status_text",
    "source_part_deleted_pending_reason",
    "source_part_deleted_status",
    "source_part_edit_undo_label",
    "source_part_group_routing_overflow_message",
    "source_part_group_routing_text",
    "source_part_include_exclude_pending_reason",
    "source_part_routing_preview_action",
]
