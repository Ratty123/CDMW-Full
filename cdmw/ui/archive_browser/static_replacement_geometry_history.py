"""Pure geometry history snapshot helpers for static replacement."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GeometryHistoryRestoreState:
    replacement_mesh: object | None
    replacement_base_mesh: object | None
    source_part_adjustments: dict[int, object]
    source_role_overrides: dict[int, str]
    source_display_overrides: dict[int, str]
    original_part_copies: list[object]
    appended_source_indices: set[int]
    independent_output_source_indices: set[int]
    preview_only_source_indices: set[int]
    dialog_added_supplemental_files: list[object]
    texture_files_for_mapping: list[object]
    texture_override_assignments: dict[object, object]
    source_material_texture_override_assignments: dict[object, object]
    copied_original_texture_intents_by_source: dict[int, object]
    copied_original_texture_disabled_sources: set[int]
    copied_original_source_indices: set[int]
    copied_original_source_to_original_index: dict[int, int]
    copied_original_physics_sensitive_sources: set[int]
    texture_uv_transform_state: dict[object, object]
    texture_uv_global_transform_state: dict[object, object]
    mesh_edit_revision: int
    source_geometry_revision: int
    morph_slider_values: dict[str, float]
    morph_slider_post_edit_deltas: list[object]
    morph_slider_topology_blocked: dict[str, object]
    selected_source_index: int
    selected_source_indices: tuple[int, ...]
    selected_target_index: int
    selected_original_index: int
    selected_source_highlights: set[int]
    selected_target_source_highlights: set[int]
    transform_source_indices: set[int]
    selected_original_highlights: set[int]
    selected_target_original_highlights: set[int]
    original_copy_text_by_index: dict[int, str]
    mapping_text_by_target: dict[int, str]
    metadata_only: bool = False
    material_authority_state: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GeometryHistoryStackState:
    pushed: bool
    snapshots: tuple[Mapping[str, object], ...]
    dropped_oldest: bool


def _int_value(value: object, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _int_set(values: object) -> set[int]:
    result: set[int] = set()
    for raw_index in tuple(values or ()):
        try:
            result.add(int(raw_index))
        except (TypeError, ValueError):
            continue
    return result


def _int_tuple(values: object) -> tuple[int, ...]:
    return tuple(sorted(_int_set(values)))


def _int_str_dict(values: object) -> dict[int, str]:
    result: dict[int, str] = {}
    for raw_index, value in dict(values or {}).items():
        try:
            result[int(raw_index)] = str(value)
        except (TypeError, ValueError):
            continue
    return result


def _int_object_dict(values: object, *, copy_values: bool = False) -> dict[int, object]:
    result: dict[int, object] = {}
    for raw_index, value in dict(values or {}).items():
        try:
            result[int(raw_index)] = copy.deepcopy(value) if copy_values else value
        except (TypeError, ValueError):
            continue
    return result


def geometry_mapping_text_by_target(
    mapping_edits: Sequence[tuple[int, object]],
    *,
    mappings_by_target: Mapping[int, object] | None = None,
    original_mesh: object | None = None,
) -> dict[int, str]:
    mapping_text = {int(target_index): str(edit.text() if hasattr(edit, "text") else edit) for target_index, edit in mapping_edits}
    if mappings_by_target is not None:
        for target_index, mapping in mappings_by_target.items():
            mapping_text.setdefault(
                int(target_index),
                ", ".join(str(index) for index in tuple(getattr(mapping, "source_submesh_indices", ()) or ())),
            )
    target_count = len(tuple(getattr(original_mesh, "submeshes", ()) or ())) if original_mesh is not None else 0
    for target_index in range(target_count):
        mapping_text.setdefault(int(target_index), "")
    return mapping_text


def geometry_original_copy_text_by_index(original_items_by_index: Mapping[int, object]) -> dict[int, str]:
    return {int(index): str(item.text(4) if hasattr(item, "text") else "") for index, item in original_items_by_index.items()}


def geometry_history_guard_initial_state() -> dict[str, bool]:
    return {"active": False}


def geometry_history_capture_state(
    *,
    reason: str,
    replacement_mesh: object | None,
    replacement_base_mesh: object | None,
    mapping_text_by_target: Mapping[int, str],
    source_part_adjustments: Mapping[int, object],
    source_role_overrides: Mapping[int, object],
    source_display_overrides: Mapping[int, object],
    original_part_copies: Sequence[object],
    original_copy_text_by_index: Mapping[int, str],
    appended_source_indices: Sequence[int],
    independent_output_source_indices: Sequence[int],
    preview_only_source_indices: Sequence[int],
    dialog_added_supplemental_files: Sequence[object],
    texture_files_for_mapping: Sequence[object],
    texture_override_assignments: Mapping[object, object],
    source_material_texture_override_assignments: Mapping[object, object],
    copied_original_texture_intents_by_source: Mapping[int, object],
    copied_original_texture_disabled_sources: Sequence[int],
    copied_original_source_indices: Sequence[int],
    copied_original_source_to_original_index: Mapping[int, int],
    copied_original_physics_sensitive_sources: Sequence[int],
    texture_uv_transform_state: Mapping[object, object],
    texture_uv_global_transform_state: Mapping[object, object],
    mesh_edit_revision: object,
    source_geometry_revision: object,
    morph_slider_values: Mapping[object, object],
    morph_slider_post_edit_deltas: Sequence[object],
    morph_slider_topology_blocked: Mapping[str, object],
    selected_source_index: object,
    selected_source_indices: Sequence[int],
    selected_target_index: object,
    selected_original_index: object,
    selected_source_highlights: Sequence[int],
    selected_target_source_highlights: Sequence[int],
    transform_source_indices: Sequence[int],
    selected_original_highlights: Sequence[int],
    selected_target_original_highlights: Sequence[int],
    metadata_only: bool = False,
    material_authority_state: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "reason": str(reason or "Geometry change"),
        "replacement_mesh": replacement_mesh,
        "replacement_base_mesh": replacement_base_mesh,
        "mapping_text_by_target": dict(mapping_text_by_target),
        "source_part_adjustments": copy.deepcopy(dict(source_part_adjustments or {})),
        "source_role_overrides": _int_str_dict(source_role_overrides),
        "source_display_overrides": _int_str_dict(source_display_overrides),
        "original_part_copies": copy.deepcopy(list(original_part_copies or ())),
        "original_copy_text_by_index": dict(original_copy_text_by_index),
        "appended_source_indices": _int_set(appended_source_indices),
        "independent_output_source_indices": _int_set(independent_output_source_indices),
        "preview_only_source_indices": _int_set(preview_only_source_indices),
        "dialog_added_supplemental_files": list(dialog_added_supplemental_files or ()),
        "texture_files_for_mapping": list(texture_files_for_mapping or ()),
        "texture_override_assignments": dict(texture_override_assignments or {}),
        "source_material_texture_override_assignments": dict(source_material_texture_override_assignments or {}),
        "copied_original_texture_intents_by_source": copy.deepcopy(
            _int_object_dict(copied_original_texture_intents_by_source, copy_values=True)
        ),
        "copied_original_texture_disabled_sources": _int_set(copied_original_texture_disabled_sources),
        "copied_original_source_indices": _int_set(copied_original_source_indices),
        "copied_original_source_to_original_index": {
            int(source_index): int(original_index)
            for source_index, original_index in dict(copied_original_source_to_original_index or {}).items()
        },
        "copied_original_physics_sensitive_sources": _int_set(copied_original_physics_sensitive_sources),
        "texture_uv_transform_state": copy.deepcopy(dict(texture_uv_transform_state or {})),
        "texture_uv_global_transform_state": copy.deepcopy(dict(texture_uv_global_transform_state or {})),
        "mesh_edit_revision": _int_value(mesh_edit_revision, 0),
        "source_geometry_revision": _int_value(source_geometry_revision, 0),
        "morph_slider_values": {
            str(slider_id): float(value)
            for slider_id, value in dict(morph_slider_values or {}).items()
        },
        "morph_slider_post_edit_deltas": copy.deepcopy(list(morph_slider_post_edit_deltas or ())),
        "morph_slider_topology_blocked": dict(
            morph_slider_topology_blocked or {"blocked": False, "reason": ""}
        ),
        "selected_source_index": _int_value(selected_source_index),
        "selected_source_indices": _int_tuple(selected_source_indices),
        "selected_target_index": _int_value(selected_target_index),
        "selected_original_index": _int_value(selected_original_index),
        "selected_source_highlights": _int_set(selected_source_highlights),
        "selected_target_source_highlights": _int_set(selected_target_source_highlights),
        "transform_source_indices": _int_set(transform_source_indices),
        "selected_original_highlights": _int_set(selected_original_highlights),
        "selected_target_original_highlights": _int_set(selected_target_original_highlights),
        "metadata_only": bool(metadata_only),
        "material_authority_state": copy.deepcopy(dict(material_authority_state or {})),
    }


def geometry_history_push_state(
    snapshots: Sequence[Mapping[str, object]],
    snapshot: Mapping[str, object],
    *,
    guard_active: bool,
    limit: int = 40,
) -> GeometryHistoryStackState:
    if bool(guard_active):
        return GeometryHistoryStackState(False, tuple(snapshots or ()), False)
    normalized_limit = max(1, int(limit))
    updated = list(snapshots or ())
    updated.append(snapshot)
    dropped_oldest = False
    if len(updated) > normalized_limit:
        del updated[0 : len(updated) - normalized_limit]
        dropped_oldest = True
    return GeometryHistoryStackState(True, tuple(updated), dropped_oldest)


def geometry_history_restore_state(
    snapshot: Mapping[str, Any],
    *,
    default_texture_uv_global_transform_state: Mapping[object, object],
) -> GeometryHistoryRestoreState:
    default_topology_blocked = {"blocked": False, "reason": ""}
    return GeometryHistoryRestoreState(
        replacement_mesh=snapshot.get("replacement_mesh"),
        replacement_base_mesh=snapshot.get("replacement_base_mesh"),
        source_part_adjustments=copy.deepcopy(_int_object_dict(snapshot.get("source_part_adjustments", {}))),
        source_role_overrides=_int_str_dict(snapshot.get("source_role_overrides", {})),
        source_display_overrides=_int_str_dict(snapshot.get("source_display_overrides", {})),
        original_part_copies=list(copy.deepcopy(snapshot.get("original_part_copies", []))),
        appended_source_indices=_int_set(snapshot.get("appended_source_indices", set())),
        independent_output_source_indices=_int_set(snapshot.get("independent_output_source_indices", set())),
        preview_only_source_indices=_int_set(snapshot.get("preview_only_source_indices", set())),
        dialog_added_supplemental_files=list(snapshot.get("dialog_added_supplemental_files", [])),
        texture_files_for_mapping=list(snapshot.get("texture_files_for_mapping", [])),
        texture_override_assignments=dict(snapshot.get("texture_override_assignments", {})),
        source_material_texture_override_assignments=dict(
            snapshot.get("source_material_texture_override_assignments", {})
        ),
        copied_original_texture_intents_by_source=copy.deepcopy(
            _int_object_dict(snapshot.get("copied_original_texture_intents_by_source", {}), copy_values=True)
        ),
        copied_original_texture_disabled_sources=_int_set(
            snapshot.get("copied_original_texture_disabled_sources", set())
        ),
        copied_original_source_indices=_int_set(snapshot.get("copied_original_source_indices", set())),
        copied_original_source_to_original_index={
            int(source_index): int(original_index)
            for source_index, original_index in dict(
                snapshot.get("copied_original_source_to_original_index", {})
            ).items()
        },
        copied_original_physics_sensitive_sources=_int_set(
            snapshot.get("copied_original_physics_sensitive_sources", set())
        ),
        texture_uv_transform_state=copy.deepcopy(dict(snapshot.get("texture_uv_transform_state", {}))),
        texture_uv_global_transform_state=copy.deepcopy(
            dict(snapshot.get("texture_uv_global_transform_state", default_texture_uv_global_transform_state))
        ),
        mesh_edit_revision=_int_value(snapshot.get("mesh_edit_revision", 0), 0),
        source_geometry_revision=_int_value(snapshot.get("source_geometry_revision", 0), 0),
        morph_slider_values={
            str(slider_id): float(value)
            for slider_id, value in dict(snapshot.get("morph_slider_values", {}) or {}).items()
        },
        morph_slider_post_edit_deltas=copy.deepcopy(list(snapshot.get("morph_slider_post_edit_deltas", []))),
        morph_slider_topology_blocked=dict(
            snapshot.get("morph_slider_topology_blocked", default_topology_blocked) or default_topology_blocked
        ),
        selected_source_index=_int_value(snapshot.get("selected_source_index", -1)),
        selected_source_indices=tuple(_int_tuple(snapshot.get("selected_source_indices", ()))),
        selected_target_index=_int_value(snapshot.get("selected_target_index", -1)),
        selected_original_index=_int_value(snapshot.get("selected_original_index", -1)),
        selected_source_highlights=_int_set(snapshot.get("selected_source_highlights", set())),
        selected_target_source_highlights=_int_set(snapshot.get("selected_target_source_highlights", set())),
        transform_source_indices=_int_set(snapshot.get("transform_source_indices", set())),
        selected_original_highlights=_int_set(snapshot.get("selected_original_highlights", set())),
        selected_target_original_highlights=_int_set(
            snapshot.get("selected_target_original_highlights", set())
        ),
        original_copy_text_by_index={
            int(index): str(text)
            for index, text in dict(snapshot.get("original_copy_text_by_index", {})).items()
        },
        mapping_text_by_target={
            int(index): str(text)
            for index, text in dict(snapshot.get("mapping_text_by_target", {})).items()
        },
        metadata_only=bool(snapshot.get("metadata_only", False)),
        material_authority_state=copy.deepcopy(dict(snapshot.get("material_authority_state", {}) or {})),
    )


def geometry_undo_status_text(reason: object) -> str:
    return f"Undid Geometry change: {str(reason)}."


def geometry_reset_status_text() -> str:
    return "Reset Geometry changes back to the initial alignment state."


__all__ = [
    "GeometryHistoryRestoreState",
    "GeometryHistoryStackState",
    "geometry_history_capture_state",
    "geometry_history_guard_initial_state",
    "geometry_history_push_state",
    "geometry_history_restore_state",
    "geometry_mapping_text_by_target",
    "geometry_original_copy_text_by_index",
    "geometry_reset_status_text",
    "geometry_undo_status_text",
]
