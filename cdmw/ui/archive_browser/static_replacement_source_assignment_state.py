"""Source assignment presentation helpers for static replacement."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceAssignmentRowState:
    source_index: int
    role_text: str
    assigned_targets_text: str
    assigned_targets_color: str
    status_text: str
    status_color: str
    target_tooltip: str
    status_tooltip: str
    source_state: str
    assigned_target_indices: tuple[int, ...]


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


def source_assigned_target_indices(
    source_index: object,
    mapping_edits: Sequence[tuple[int, object]],
    *,
    parse_mapping_edit: Callable[[object], Sequence[int]],
) -> tuple[int, ...]:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        return ()
    assigned: list[int] = []
    for target_index, edit in mapping_edits:
        if normalized_source_index in _nonnegative_indices(parse_mapping_edit(edit)):
            assigned.append(int(target_index))
    return tuple(assigned)


def source_assignment_index(
    mapping_edits: Sequence[tuple[int, object]],
    *,
    parse_mapping_edit: Callable[[object], Sequence[int]],
) -> dict[int, list[int]]:
    assignments: dict[int, list[int]] = defaultdict(list)
    for target_index, edit in mapping_edits:
        for mapped_source_index in parse_mapping_edit(edit):
            if mapped_source_index >= 0:
                assignments[int(mapped_source_index)].append(int(target_index))
    return assignments


def source_assignment_targets_tooltip(assigned_targets: str) -> str:
    return str(assigned_targets or "").strip() or "Not assigned to an original target."


def source_assignment_state_tooltip(source_state: str) -> str:
    normalized_state = str(source_state or "").strip()
    tooltips = {
        "Assigned": "This replacement source feeds at least one original target.",
        "Preview-only": "This replacement source is visible for review but will not replace an original target until assigned.",
        "Unassigned": "This replacement source is not connected to any original target.",
        "Disabled": "This replacement source is excluded from output.",
        "Independent": "This replacement source exports independently instead of replacing an original target.",
    }
    return tooltips.get(normalized_state, normalized_state)


def source_assignment_row_state(
    source_index: object,
    assigned_target_indices: Sequence[int],
    *,
    role_text: object,
    assigned_targets_text: object,
    source_state: object,
    status_text: object,
    status_color: object,
    copied_texture_tooltip: object = "",
) -> SourceAssignmentRowState:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    normalized_target_indices = tuple(int(index) for index in assigned_target_indices)
    targets_text = str(assigned_targets_text or "").strip()
    normalized_source_state = str(source_state or "").strip()
    copied_tooltip = str(copied_texture_tooltip or "").strip()
    return SourceAssignmentRowState(
        source_index=normalized_source_index,
        role_text=str(role_text or ""),
        assigned_targets_text=targets_text or "-",
        assigned_targets_color="#cbd5e1" if targets_text else "#8b949e",
        status_text=str(status_text or ""),
        status_color=str(status_color or "#8b949e"),
        target_tooltip=source_assignment_targets_tooltip(targets_text),
        status_tooltip=copied_tooltip or source_assignment_state_tooltip(normalized_source_state),
        source_state=normalized_source_state,
        assigned_target_indices=normalized_target_indices,
    )


__all__ = [
    "SourceAssignmentRowState",
    "source_assigned_target_indices",
    "source_assignment_index",
    "source_assignment_row_state",
    "source_assignment_state_tooltip",
    "source_assignment_targets_tooltip",
]
