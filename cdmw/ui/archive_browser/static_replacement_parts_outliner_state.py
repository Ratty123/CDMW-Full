"""Parts outliner state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PartsOutlinerSourceTargetApplyState:
    source_index: int
    target_index: int
    available: bool


def parts_outliner_control_text() -> dict[str, object]:
    return {
        "title": "Parts Outliner",
        "tooltip": (
            "Targets are original game draw/material slots. Child rows are replacement source parts feeding each target."
        ),
        "headers": ["Item", "Target", "Role", "DDS", "State", "Physics", "Geometry"],
    }


def parts_outliner_unassigned_target_label() -> str:
    return "Preview-only / Unassigned"


def parts_outliner_source_role_change_undo_label() -> str:
    return "Change source role"


def parts_outliner_source_role_change_refresh_reason() -> str:
    return "source role change"


def parts_outliner_cache_initial_state() -> dict[str, object]:
    return {"revision": None}


def parts_outliner_item_update_guard_initial_state() -> dict[str, bool]:
    return {"active": False, "refreshing": False}


def parts_outliner_revision(
    *,
    original_mesh: object | None,
    replacement_mesh: object | None,
    mapping_edits: Sequence[tuple[int, object]],
    preview_only_source_indices: Sequence[int],
    independent_output_source_indices: Sequence[int],
    copied_original_texture_intents_by_source: Mapping[int, object],
) -> tuple[object, ...]:
    mapping_revision = tuple(
        (int(target_index), str(edit.text()))
        for target_index, edit in tuple(mapping_edits or ())
    )
    return (
        len(tuple(getattr(original_mesh, "submeshes", ()) or ())),
        len(tuple(getattr(replacement_mesh, "submeshes", ()) or ())),
        mapping_revision,
        tuple(sorted(int(index) for index in preview_only_source_indices)),
        tuple(sorted(int(index) for index in independent_output_source_indices)),
        tuple(sorted(int(index) for index in copied_original_texture_intents_by_source.keys())),
    )


def parts_outliner_cache_matches(
    cache_state: Mapping[str, object],
    revision: object,
    *,
    has_items: bool,
) -> bool:
    return bool(has_items and cache_state.get("revision") == revision)


def parts_outliner_cache_record_revision(
    cache_state: MutableMapping[str, object],
    revision: object,
) -> None:
    cache_state["revision"] = revision


def parts_outliner_drop_target_index(item: object | None, *, user_role: int) -> int | None:
    if item is None:
        return None
    data_getter = getattr(item, "data", None)
    if not callable(data_getter):
        return None
    row_kind = str(data_getter(0, int(user_role)) or "")
    if row_kind == "unassigned_group":
        return -1
    if row_kind in {"target", "source"}:
        try:
            return int(data_getter(0, int(user_role) + 1))
        except (TypeError, ValueError):
            return None
    parent_getter = getattr(item, "parent", None)
    parent = parent_getter() if callable(parent_getter) else None
    if parent is not None:
        return parts_outliner_drop_target_index(parent, user_role=user_role)
    return None


def parts_outliner_target_label(
    target_index: object,
    target_label_text: object,
    *,
    simplify_label: Callable[[str], str],
) -> str:
    try:
        normalized_target_index = int(target_index)
    except (TypeError, ValueError):
        normalized_target_index = -1
    return f"Target {normalized_target_index}: {simplify_label(str(target_label_text))}"


def parts_outliner_source_label(source_label: object) -> str:
    return f"  -> {source_label}"


def parts_outliner_geometry_text(part: object) -> str:
    vertices = getattr(part, "vertices", ()) or ()
    faces = getattr(part, "faces", ()) or ()
    return f"{len(vertices):,.0f} vertices, {len(faces):,.0f} faces"


def parts_outliner_copied_texture_tooltip_source_index(
    source_index: object,
    copied_original_texture_intents_by_source: Mapping[int, object],
) -> int | None:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        return None
    if normalized_source_index in copied_original_texture_intents_by_source:
        return normalized_source_index
    return None


def parts_outliner_target_menu_specs(target_labels: Sequence[object]) -> tuple[tuple[str, int], ...]:
    specs: list[tuple[str, int]] = [(parts_outliner_unassigned_target_label(), -1)]
    for target_index, label in enumerate(tuple(target_labels or ())):
        specs.append((str(label), int(target_index)))
    return tuple(specs)


def parts_outliner_role_menu_specs(role_options: Sequence[tuple[object, object]]) -> tuple[tuple[str, str], ...]:
    return tuple((str(label), str(role_value or "")) for label, role_value in tuple(role_options or ()))


def _nonnegative_unique_indices(raw_indices: object) -> tuple[int, ...]:
    if not isinstance(raw_indices, (tuple, list, set)):
        return ()
    normalized: list[int] = []
    for raw_index in raw_indices:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index >= 0 and index not in normalized:
            normalized.append(index)
    return tuple(normalized)


def parts_outliner_source_indices(source_indices: object) -> tuple[int, ...]:
    return _nonnegative_unique_indices(source_indices)


def parts_outliner_unassigned_source_indices(
    replacement_mesh: object | None,
    assigned_sources: Sequence[int],
    *,
    is_marker_source: Callable[[object], bool],
) -> tuple[int, ...]:
    if replacement_mesh is None:
        return ()
    assigned = set(_nonnegative_unique_indices(tuple(assigned_sources or ())))
    indices: list[int] = []
    for source_index, source in enumerate(tuple(getattr(replacement_mesh, "submeshes", ()) or ())):
        if is_marker_source(source) or source_index in assigned:
            continue
        indices.append(int(source_index))
    return tuple(indices)


def parts_outliner_selection_row_state(item: object | None, *, user_role: int) -> dict[str, object] | None:
    if item is None:
        return None
    data_getter = getattr(item, "data", None)
    if not callable(data_getter):
        return None
    try:
        target_index = int(data_getter(0, int(user_role) + 1))
    except (TypeError, ValueError):
        target_index = -1
    return {
        "row_kind": str(data_getter(0, int(user_role)) or ""),
        "target_index": target_index,
        "source_indices": _nonnegative_unique_indices(data_getter(0, int(user_role) + 2)),
    }


def parts_outliner_target_selection_view_payload(
    *,
    row_kind: object,
    target_index: int,
    source_indices: Sequence[int],
) -> dict[str, object] | None:
    if str(row_kind or "") != "target":
        return None
    return {
        "kind": "target" if int(target_index) >= 0 else "none",
        "target_indices": (int(target_index),) if int(target_index) >= 0 else (),
        "source_indices": tuple(int(index) for index in tuple(source_indices or ())),
    }


def parts_outliner_source_click_action(row_kind: object, column: int) -> str:
    if str(row_kind or "") != "source":
        return ""
    if int(column) == 1:
        return "target"
    if int(column) == 2:
        return "role"
    return ""


def parts_outliner_action_target_index(raw_value: object, *, default: int = -1) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return int(default)


def parts_outliner_source_target_apply_state(
    *,
    source_index: object,
    target_index: object,
    source_count: object,
) -> PartsOutlinerSourceTargetApplyState:
    try:
        normalized_source = int(source_index)
        normalized_source_count = max(0, int(source_count))
        normalized_target = int(target_index)
    except (TypeError, ValueError):
        return PartsOutlinerSourceTargetApplyState(source_index=-1, target_index=-1, available=False)
    available = 0 <= normalized_source < normalized_source_count
    return PartsOutlinerSourceTargetApplyState(
        source_index=normalized_source if available else -1,
        target_index=normalized_target if available else -1,
        available=bool(available),
    )


def parts_outliner_action_role_value(raw_value: object) -> str:
    return str(raw_value or "")


def parts_outliner_source_drop_allowed(
    *,
    refreshing: bool,
    source_index: int,
    target_index: int | None,
) -> bool:
    return not bool(refreshing) and int(source_index) >= 0 and target_index is not None


__all__ = [
    "PartsOutlinerSourceTargetApplyState",
    "parts_outliner_action_role_value",
    "parts_outliner_action_target_index",
    "parts_outliner_cache_initial_state",
    "parts_outliner_cache_matches",
    "parts_outliner_cache_record_revision",
    "parts_outliner_control_text",
    "parts_outliner_copied_texture_tooltip_source_index",
    "parts_outliner_drop_target_index",
    "parts_outliner_geometry_text",
    "parts_outliner_item_update_guard_initial_state",
    "parts_outliner_revision",
    "parts_outliner_role_menu_specs",
    "parts_outliner_selection_row_state",
    "parts_outliner_source_drop_allowed",
    "parts_outliner_source_click_action",
    "parts_outliner_source_indices",
    "parts_outliner_source_label",
    "parts_outliner_source_target_apply_state",
    "parts_outliner_target_label",
    "parts_outliner_target_menu_specs",
    "parts_outliner_target_selection_view_payload",
    "parts_outliner_source_role_change_refresh_reason",
    "parts_outliner_source_role_change_undo_label",
    "parts_outliner_unassigned_source_indices",
    "parts_outliner_unassigned_target_label",
]
