"""Selected source-part action/status state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Sequence
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


def source_part_context_menu_text() -> dict[str, str]:
    return {
        "delete_selected_parts": "Delete Selected Part(s)",
        "apply": "Apply",
        "set_role_glow": "Set Role: Glow / emissive",
        "set_role_auto": "Set Role: Auto / inferred",
    }


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
    return f"Deleted {int(delete_count):,} replacement source part(s). Preview still shows old geometry until Apply."


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
    "SourcePartDeleteIndexMapState",
    "SourcePartDeleteSelectionState",
    "source_part_context_menu_text",
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
