"""Pure Morph Slider state and status helpers for static replacement UI."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, MutableSequence, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MorphSliderRowState:
    slider_id: str
    label: str
    slider_minimum: int
    slider_maximum: int
    spin_minimum: float
    spin_maximum: float
    current_percent: float
    reset_percent: float
    reset_text: str


@dataclass(frozen=True, slots=True)
class MorphSliderRowSyncState:
    row: Mapping[str, object]
    slider_id: str
    percent: float
    slider_value: int


@dataclass(frozen=True, slots=True)
class MorphSliderValueCommitState:
    should_commit: bool
    slider_id: str
    clamped_percent: float
    status_text: str


@dataclass(frozen=True, slots=True)
class MorphSliderActionRouteState:
    allowed: bool
    title: str
    message: str


@dataclass(frozen=True, slots=True)
class MorphSliderResetState:
    should_reset: bool
    change_label: str
    status_text: str


@dataclass(frozen=True, slots=True)
class MorphSliderBakeState:
    should_bake: bool
    change_label: str
    status_text: str


@dataclass(frozen=True, slots=True)
class MorphSliderReloadState:
    old_values: dict[object, object]
    should_load_profiles: bool
    should_clear_post_edit_deltas: bool
    clear_block_reason: bool


def morph_slider_supported(
    *,
    modify_original_clone_mode: bool,
    has_base_mesh: bool,
    has_working_mesh: bool,
) -> bool:
    return bool(modify_original_clone_mode and has_base_mesh and has_working_mesh)


def morph_slider_has_loaded_deltas(deltas: Mapping[object, object]) -> bool:
    return bool(deltas)


def morph_slider_has_nonzero_values(values: Mapping[object, object], *, tolerance: float = 1e-6) -> bool:
    for value in values.values():
        try:
            if abs(float(value or 0.0)) > float(tolerance):
                return True
        except (TypeError, ValueError, OverflowError):
            continue
    return False


def morph_slider_active_deltas(deltas: Mapping[object, object]) -> tuple[object, ...]:
    return tuple(deltas[slider_id] for slider_id in deltas)


def morph_slider_topology_blocked_initial_state() -> dict[str, object]:
    return {"blocked": False, "reason": ""}


def morph_slider_activity_guard_initial_state() -> dict[str, bool]:
    return {"active": False}


def morph_slider_clamped_percent(percent: object, min_percent: object, max_percent: object) -> float:
    return max(float(min_percent), min(float(max_percent), float(percent)))


def morph_slider_value_changed(previous: object, current: object, *, tolerance: float = 1e-6) -> bool:
    try:
        previous_value = float(previous or 0.0)
        current_value = float(current or 0.0)
    except (TypeError, ValueError, OverflowError):
        return True
    return abs(previous_value - current_value) > float(tolerance)


def morph_slider_applied_status_text(label: object, percent: object) -> str:
    return f"Applied Morph Slider {label}: {float(percent):.2f}%."


def morph_slider_title_text() -> str:
    return "Morph Sliders"


def morph_slider_create_action_text() -> str:
    return "Create Slider From Selection"


def morph_slider_create_action_tooltip() -> str:
    return "Save the selected vertices as a Volume Size slider for this Modify Original mesh topology."


def morph_slider_manage_action_text() -> str:
    return "Manage Profiles"


def morph_slider_manage_action_tooltip() -> str:
    return "Import Body Slider Pro packs or add exact same-topology target-mesh sliders."


def morph_slider_import_action_text() -> str:
    return "Import Slider Pack"


def morph_slider_add_target_action_text() -> str:
    return "Add Slider From Target Mesh"


def morph_slider_target_mesh_file_filter() -> str:
    return "Morph Target Mesh (*.obj *.pac *.pam *.pamlod)"


def morph_slider_reload_action_text() -> str:
    return "Reload Profiles"


def morph_slider_reset_action_text() -> str:
    return "Reset Sliders"


def morph_slider_row_reset_action_text() -> str:
    return "Reset"


def morph_slider_reset_change_label() -> str:
    return "Reset Morph Sliders"


def morph_slider_reset_status_text() -> str:
    return "Reset Morph Sliders."


def morph_slider_bake_action_text() -> str:
    return "Bake Sliders"


def morph_slider_bake_action_tooltip() -> str:
    return "Apply current slider values into the editable base mesh, then reset slider values to zero."


def morph_slider_bake_change_label() -> str:
    return "Bake Morph Sliders"


def morph_slider_baked_status_text() -> str:
    return "Baked Morph Sliders into the editable mesh base."


def morph_slider_import_requires_modify_original_text() -> str:
    return "Open Modify Original for a parsed mesh before importing sliders."


def morph_slider_add_requires_modify_original_text() -> str:
    return "Open Modify Original for a parsed mesh before adding sliders."


def morph_slider_create_requires_modify_original_text() -> str:
    return "Open Modify Original for a parsed mesh before creating sliders."


def morph_slider_create_requires_selection_text() -> str:
    return "Select vertices first, then create a region slider."


def morph_slider_topology_changed_reason_text() -> str:
    return "Topology changed; reset the edited scope before using Morph Sliders."


def morph_slider_name_prompt_text() -> str:
    return "Slider name:"


def morph_slider_default_name_text() -> str:
    return "Volume Size"


def morph_slider_amount_prompt_text() -> str:
    return "100% size amount:"


def morph_slider_feather_prompt_text() -> str:
    return "Feather rings:"


def morph_slider_imported_status_text(profile_name: object) -> str:
    return f"Imported Morph Slider profile: {profile_name}."


def morph_slider_added_status_text(profile_name: object) -> str:
    return f"Added Morph Slider profile: {profile_name}."


def morph_slider_created_status_text(profile_name: object) -> str:
    return f"Created Morph Slider profile: {profile_name}."


def morph_slider_value_or_default(values: Mapping[object, object], slider_id: object, default_percent: object) -> float:
    return float(values.get(str(slider_id), default_percent) or 0.0)


def morph_slider_row_state(delta: object, values: Mapping[object, object]) -> MorphSliderRowState:
    slider_id = str(getattr(delta, "slider_id", "") or "")
    min_percent = float(getattr(delta, "min_percent", 0.0) or 0.0)
    max_percent = float(getattr(delta, "max_percent", 0.0) or 0.0)
    default_percent = float(getattr(delta, "default_percent", 0.0) or 0.0)
    return MorphSliderRowState(
        slider_id=slider_id,
        label=str(getattr(delta, "label", "") or slider_id),
        slider_minimum=int(round(min_percent * 100.0)),
        slider_maximum=int(round(max_percent * 100.0)),
        spin_minimum=min_percent,
        spin_maximum=max_percent,
        current_percent=morph_slider_value_or_default(values, slider_id, default_percent),
        reset_percent=default_percent,
        reset_text=morph_slider_row_reset_action_text(),
    )


def morph_slider_row_sync_states(
    rows: Sequence[Mapping[str, object]],
    values: Mapping[object, object],
) -> tuple[MorphSliderRowSyncState, ...]:
    states: list[MorphSliderRowSyncState] = []
    for row in tuple(rows or ()):
        slider_id = str(row.get("slider_id") or "")
        percent = float(values.get(slider_id, 0.0) or 0.0)
        states.append(
            MorphSliderRowSyncState(
                row=row,
                slider_id=slider_id,
                percent=percent,
                slider_value=int(round(percent * 100.0)),
            )
        )
    return tuple(states)


def morph_slider_value_commit_state(
    *,
    update_active: bool,
    delta: object | None,
    supported: bool,
    blocked: bool,
    values: Mapping[object, object],
    percent: object,
) -> MorphSliderValueCommitState:
    if bool(update_active) or delta is None or not bool(supported) or bool(blocked):
        return MorphSliderValueCommitState(False, "", 0.0, "")
    slider_id = str(getattr(delta, "slider_id", "") or "")
    clamped = morph_slider_clamped_percent(
        percent,
        getattr(delta, "min_percent", 0.0),
        getattr(delta, "max_percent", 0.0),
    )
    previous = morph_slider_value_or_default(values, slider_id, 0.0)
    if not morph_slider_value_changed(previous, clamped):
        return MorphSliderValueCommitState(False, slider_id, clamped, "")
    return MorphSliderValueCommitState(
        True,
        slider_id,
        clamped,
        morph_slider_applied_status_text(getattr(delta, "label", slider_id), clamped),
    )


def morph_slider_import_route_state(*, has_base_mesh: bool) -> MorphSliderActionRouteState:
    return MorphSliderActionRouteState(
        allowed=bool(has_base_mesh),
        title=morph_slider_title_text(),
        message="" if has_base_mesh else morph_slider_import_requires_modify_original_text(),
    )


def morph_slider_add_target_route_state(*, has_base_mesh: bool) -> MorphSliderActionRouteState:
    return MorphSliderActionRouteState(
        allowed=bool(has_base_mesh),
        title=morph_slider_title_text(),
        message="" if has_base_mesh else morph_slider_add_requires_modify_original_text(),
    )


def morph_slider_create_route_state(*, has_base_mesh: bool, has_selection: bool) -> MorphSliderActionRouteState:
    if not bool(has_base_mesh):
        return MorphSliderActionRouteState(
            allowed=False,
            title=morph_slider_title_text(),
            message=morph_slider_create_requires_modify_original_text(),
        )
    if not bool(has_selection):
        return MorphSliderActionRouteState(
            allowed=False,
            title=morph_slider_title_text(),
            message=morph_slider_create_requires_selection_text(),
        )
    return MorphSliderActionRouteState(True, morph_slider_title_text(), "")


def morph_slider_reset_state(*, loaded: bool) -> MorphSliderResetState:
    return MorphSliderResetState(
        should_reset=bool(loaded),
        change_label=morph_slider_reset_change_label(),
        status_text=morph_slider_reset_status_text(),
    )


def morph_slider_bake_state(*, has_working_mesh: bool, loaded: bool, has_nonzero_values: bool) -> MorphSliderBakeState:
    return MorphSliderBakeState(
        should_bake=bool(has_working_mesh and loaded and has_nonzero_values),
        change_label=morph_slider_bake_change_label(),
        status_text=morph_slider_baked_status_text(),
    )


def morph_slider_unique_slider_id(
    raw_slider_id: object,
    used_slider_ids: set[str],
    *,
    profile_index: int,
) -> str:
    slider_id = str(raw_slider_id or "").strip() or "slider"
    base_slider_id = slider_id
    duplicate_counter = 2
    while slider_id.lower() in used_slider_ids:
        slider_id = f"{base_slider_id}_{int(profile_index) + 1}_{duplicate_counter}"
        duplicate_counter += 1
    return slider_id


def _morph_slider_vertex_count(mesh: object | None) -> int:
    try:
        count = int(getattr(mesh, "total_vertices", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        count = 0
    if count > 0:
        return count
    return sum(
        len(getattr(submesh, "vertices", ()) or ())
        for submesh in getattr(mesh, "submeshes", ()) or ()
    )


def _morph_slider_native_post_edit_deltas(
    working_mesh: object,
    slider_only_mesh: object,
) -> list[list[tuple[float, float, float]]] | None:
    try:
        from cdmw.modding.mesh_native_core import (
            build_native_morph_post_edit_deltas,
            native_mesh_core_available,
            record_native_mesh_core_fallback,
        )
    except Exception:
        return None
    native_result = build_native_morph_post_edit_deltas(working_mesh, slider_only_mesh)
    if (
        native_result is None
        and native_mesh_core_available()
        and not os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip()
    ):
        record_native_mesh_core_fallback(
            "morph_post_edit_delta",
            "native_result_unavailable",
            vertices=max(_morph_slider_vertex_count(working_mesh), _morph_slider_vertex_count(slider_only_mesh)),
        )
    return native_result


def _allow_python_morph_post_edit_delta_fallback(working_mesh: object, slider_only_mesh: object) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    try:
        from cdmw.modding.mesh_native_core import native_mesh_core_available, record_native_mesh_core_fallback
    except Exception:
        return True
    if not native_mesh_core_available():
        return True
    vertex_count = max(_morph_slider_vertex_count(working_mesh), _morph_slider_vertex_count(slider_only_mesh))
    record_native_mesh_core_fallback(
        "morph_post_edit_delta.blocked",
        "Python morph post-edit delta fallback blocked while native mesh core is available",
        vertex_count=vertex_count,
    )
    return False


def morph_slider_zero_post_edit_deltas(mesh: object | None) -> list[list[tuple[float, float, float]]]:
    return []


def _morph_slider_capture_post_edit_deltas_fallback(
    working_mesh: object | None,
    slider_only_mesh: object | None,
) -> list[list[tuple[float, float, float]]]:
    if working_mesh is None or slider_only_mesh is None:
        return []
    captured: list[list[tuple[float, float, float]]] = []
    for working_submesh, slider_submesh in zip(
        getattr(working_mesh, "submeshes", ()) or (),
        getattr(slider_only_mesh, "submeshes", ()) or (),
    ):
        submesh_deltas: list[tuple[float, float, float]] = []
        for working_vertex, slider_vertex in zip(
            getattr(working_submesh, "vertices", ()) or (),
            getattr(slider_submesh, "vertices", ()) or (),
        ):
            submesh_deltas.append(
                (
                    float(working_vertex[0]) - float(slider_vertex[0]),
                    float(working_vertex[1]) - float(slider_vertex[1]),
                    float(working_vertex[2]) - float(slider_vertex[2]),
                )
            )
        captured.append(submesh_deltas)
    return captured


def morph_slider_capture_post_edit_deltas(
    working_mesh: object | None,
    slider_only_mesh: object | None,
) -> list[list[tuple[float, float, float]]]:
    if working_mesh is None or slider_only_mesh is None:
        return []
    native_result = _morph_slider_native_post_edit_deltas(working_mesh, slider_only_mesh)
    if native_result is not None:
        return native_result
    if not _allow_python_morph_post_edit_delta_fallback(working_mesh, slider_only_mesh):
        raise RuntimeError("native morph post-edit delta failed and Python morph fallback was blocked")
    return _morph_slider_capture_post_edit_deltas_fallback(working_mesh, slider_only_mesh)


def morph_slider_expected_vertex_counts(mesh: object | None) -> list[int]:
    if mesh is None:
        return []
    return [
        len(getattr(submesh, "vertices", ()) or ())
        for submesh in getattr(mesh, "submeshes", ()) or ()
    ]


def morph_slider_post_edit_deltas_need_reset(
    post_edit_deltas: Sequence[Sequence[object]],
    expected_vertex_counts: Sequence[int],
) -> bool:
    if not post_edit_deltas:
        return False
    if len(post_edit_deltas) != len(expected_vertex_counts):
        return True
    return any(
        len(post_edit_deltas[index]) not in {0, int(expected_count)}
        for index, expected_count in enumerate(expected_vertex_counts)
    )


def morph_slider_zero_post_edit_deltas_for_sources(
    post_edit_deltas: MutableSequence[MutableSequence[tuple[float, float, float]]],
    source_indices: Iterable[object],
) -> None:
    for raw_source_index in source_indices or ():
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        if 0 <= source_index < len(post_edit_deltas):
            post_edit_deltas[source_index] = []


def morph_slider_reload_state(
    *,
    preserve_values: bool,
    values: Mapping[object, object],
    supported: bool,
    has_base_mesh: bool,
) -> MorphSliderReloadState:
    should_load = bool(supported and has_base_mesh)
    return MorphSliderReloadState(
        old_values=dict(values) if preserve_values else {},
        should_load_profiles=should_load,
        should_clear_post_edit_deltas=not should_load,
        clear_block_reason=True,
    )


def morph_slider_status_text(
    *,
    supported: bool,
    blocked: bool,
    block_reason: object,
    loaded: bool,
    profile_count: int,
    slider_count: int,
) -> str:
    if not supported:
        return "Morph Sliders are available in Modify Original mode for compatible PAC/PAM/PAMLOD meshes."
    if blocked:
        reason = str(block_reason or "topology changed; use Reset Scope to restore compatibility.")
        return f"Morph Sliders disabled: {reason}"
    if loaded:
        return f"Loaded {int(slider_count):,} slider(s) from {int(profile_count):,} compatible local profile(s)."
    return "No compatible slider profile loaded for this Modify Original mesh."


def morph_slider_control_state(
    *,
    supported: bool,
    loaded: bool,
    blocked: bool,
    selected_count: int,
    has_nonzero_values: bool,
) -> dict[str, bool]:
    rows_enabled = bool(supported and loaded and not blocked)
    return {
        "group_enabled": bool(supported),
        "create_enabled": bool(supported and not blocked and int(selected_count) > 0),
        "manage_enabled": bool(supported),
        "rows_enabled": rows_enabled,
        "reset_enabled": bool(rows_enabled and has_nonzero_values),
        "bake_enabled": bool(rows_enabled and has_nonzero_values),
    }


__all__ = [
    "MorphSliderActionRouteState",
    "MorphSliderBakeState",
    "MorphSliderResetState",
    "MorphSliderReloadState",
    "MorphSliderRowState",
    "MorphSliderRowSyncState",
    "MorphSliderValueCommitState",
    "morph_slider_add_requires_modify_original_text",
    "morph_slider_add_target_route_state",
    "morph_slider_add_target_action_text",
    "morph_slider_activity_guard_initial_state",
    "morph_slider_added_status_text",
    "morph_slider_amount_prompt_text",
    "morph_slider_applied_status_text",
    "morph_slider_active_deltas",
    "morph_slider_bake_action_text",
    "morph_slider_bake_action_tooltip",
    "morph_slider_bake_change_label",
    "morph_slider_bake_state",
    "morph_slider_baked_status_text",
    "morph_slider_capture_post_edit_deltas",
    "morph_slider_clamped_percent",
    "morph_slider_control_state",
    "morph_slider_create_action_text",
    "morph_slider_create_action_tooltip",
    "morph_slider_create_route_state",
    "morph_slider_create_requires_modify_original_text",
    "morph_slider_create_requires_selection_text",
    "morph_slider_created_status_text",
    "morph_slider_default_name_text",
    "morph_slider_expected_vertex_counts",
    "morph_slider_feather_prompt_text",
    "morph_slider_has_loaded_deltas",
    "morph_slider_has_nonzero_values",
    "morph_slider_import_action_text",
    "morph_slider_import_requires_modify_original_text",
    "morph_slider_import_route_state",
    "morph_slider_imported_status_text",
    "morph_slider_manage_action_text",
    "morph_slider_manage_action_tooltip",
    "morph_slider_name_prompt_text",
    "morph_slider_post_edit_deltas_need_reset",
    "morph_slider_reload_action_text",
    "morph_slider_reload_state",
    "morph_slider_reset_action_text",
    "morph_slider_reset_change_label",
    "morph_slider_reset_state",
    "morph_slider_reset_status_text",
    "morph_slider_row_state",
    "morph_slider_row_reset_action_text",
    "morph_slider_row_sync_states",
    "morph_slider_status_text",
    "morph_slider_supported",
    "morph_slider_target_mesh_file_filter",
    "morph_slider_title_text",
    "morph_slider_topology_changed_reason_text",
    "morph_slider_topology_blocked_initial_state",
    "morph_slider_unique_slider_id",
    "morph_slider_value_changed",
    "morph_slider_value_commit_state",
    "morph_slider_value_or_default",
    "morph_slider_zero_post_edit_deltas",
    "morph_slider_zero_post_edit_deltas_for_sources",
]
