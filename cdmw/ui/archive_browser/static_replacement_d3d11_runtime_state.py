"""D3D11 runtime, refresh, and fast-transform state rules for static replacement previews."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass

from cdmw.ui.archive_browser.static_replacement_d3d11_watchdog_state import (
    AlignmentD3D11ClearStuckLoadingRouteState,
    AlignmentD3D11LoadingRecoveryAction,
    AlignmentD3D11LoadingWatchdogSnapshot,
    alignment_d3d11_clear_stuck_loading_route,
    alignment_d3d11_loading_recovery_action,
    alignment_d3d11_loading_stuck,
    alignment_d3d11_loading_watchdog_snapshot,
    alignment_d3d11_stale_loading_restart_allowed,
)


@dataclass(frozen=True, slots=True)
class AlignmentD3D11HostReadyState:
    ready: bool
    detail: str


@dataclass(frozen=True, slots=True)
class AlignmentD3D11StaleReloadRouteState:
    should_continue: bool
    should_pause_loading: bool
    pause_message: str
    active_preview_alive: bool


@dataclass(frozen=True, slots=True)
class AlignmentD3D11StartTimeoutRouteState:
    should_report_timeout: bool


@dataclass(frozen=True, slots=True)
class AlignmentD3D11ProcessFinishedRouteState:
    should_ignore: bool
    should_poll_status: bool
    should_cleanup: bool
    should_report_error: bool


@dataclass(frozen=True, slots=True)
class AlignmentD3D11RenderSettingsRoute:
    action: str
    should_invalidate_package_cache: bool
    should_mark_rebuild_reason: bool
    should_queue_static_preview_refresh: bool
    should_apply_live_render_tuning: bool
    should_apply_static_widget_settings: bool
    performance_kind: str


@dataclass(frozen=True, slots=True)
class AlignmentD3D11ViewStateRoute:
    action: str
    should_ignore: bool
    should_clear_saved_state: bool
    should_store_snapshot: bool
    should_return_saved_state: bool


def _request_id(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def alignment_d3d11_loaded_package_transform_current(
    state: Mapping[str, object],
    transform_generation: Mapping[str, object],
    *,
    request_id: int = 0,
) -> bool:
    request_generation = int(state.get("request_transform_generation", 0) or 0)
    request_generations = state.get("request_transform_generations")
    request_id = _request_id(request_id)
    if isinstance(request_generations, Mapping) and request_id > 0:
        try:
            request_generation = int(request_generations.get(request_id, request_generation) or 0)
        except (TypeError, ValueError):
            request_generation = int(state.get("request_transform_generation", 0) or 0)
    committed_generation = int(transform_generation.get("committed", 0) or 0)
    return request_generation >= committed_generation


def alignment_d3d11_raw_package_active_or_pending(state: Mapping[str, object]) -> bool:
    if str(state.get("active_package_quality", "") or "").strip().lower() == "mesh_edit_raw":
        return True
    if str(state.get("queued_package_quality", "") or "").strip().lower() == "mesh_edit_raw":
        return True
    if str(state.get("pending_package_quality", "") or "").strip().lower() == "mesh_edit_raw":
        return True
    request_package_qualities = state.get("request_package_qualities")
    if isinstance(request_package_qualities, Mapping):
        return any(str(value or "").strip().lower() == "mesh_edit_raw" for value in request_package_qualities.values())
    return False


def alignment_d3d11_global_fast_transform_pending(state: Mapping[str, object]) -> bool:
    payload = state.get("pending_fast_transform")
    if not isinstance(payload, Mapping):
        return False
    try:
        source_indices = tuple(payload.get("source_submesh_indices", ()) or ())
    except TypeError:
        return False
    return not source_indices


def alignment_d3d11_record_fast_transform_payload(
    state: MutableMapping[str, object],
    payload: Mapping[str, object],
) -> tuple[int, ...]:
    try:
        source_indices = tuple(
            sorted({int(index) for index in tuple(payload.get("source_submesh_indices", ()) or ()) if int(index) >= 0})
        )
    except (TypeError, ValueError):
        source_indices = ()
    if source_indices:
        part_state = state.get("pending_part_fast_transforms")
        if not isinstance(part_state, dict):
            part_state = {}
            state["pending_part_fast_transforms"] = part_state
        for source_index in source_indices:
            part_state[int(source_index)] = payload
    else:
        state["pending_fast_transform"] = payload
    return source_indices


def alignment_d3d11_fast_transform_queue_state(
    state: MutableMapping[str, object],
    payload: Mapping[str, object],
    *,
    preview_active: bool,
    drag_active: bool,
) -> dict[str, object]:
    source_indices = alignment_d3d11_record_fast_transform_payload(state, payload)
    return {
        "source_indices": source_indices,
        "send_preview": bool(preview_active) and not bool(drag_active),
    }


def _fast_transform_vector(
    payload: Mapping[str, object],
    key: str,
    default: tuple[float, float, float],
) -> tuple[object, ...]:
    value = payload.get(key, default) or default
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError:
        return default


def _fast_transform_editor_ids(
    editor_ids_for_source_indices: Callable[[Sequence[int]], Sequence[int]],
    source_indices: Sequence[int],
) -> tuple[int, ...]:
    if not callable(editor_ids_for_source_indices):
        return ()
    try:
        resolved = editor_ids_for_source_indices(source_indices)
    except (AttributeError, TypeError, ValueError):
        return ()
    try:
        return tuple(int(index) for index in tuple(resolved or ()) if int(index) >= 0)
    except (TypeError, ValueError, OverflowError):
        return ()


def alignment_d3d11_fast_transform_preview_state(
    state: Mapping[str, object],
    editor_ids_for_source_indices: Callable[[Sequence[int]], Sequence[int]],
) -> tuple[tuple[object, ...], tuple[object, ...], tuple[object, ...], list[dict[str, object]]]:
    global_payload = state.get("pending_fast_transform")
    global_translation: tuple[object, ...] = (0.0, 0.0, 0.0)
    global_rotation: tuple[object, ...] = (0.0, 0.0, 0.0)
    global_scale: tuple[object, ...] = (1.0, 1.0, 1.0)
    if isinstance(global_payload, Mapping):
        global_translation = _fast_transform_vector(global_payload, "translation", (0.0, 0.0, 0.0))
        global_rotation = _fast_transform_vector(global_payload, "rotation_degrees", (0.0, 0.0, 0.0))
        global_scale = _fast_transform_vector(global_payload, "scale_xyz", (1.0, 1.0, 1.0))

    part_transforms: list[dict[str, object]] = []
    part_state = state.get("pending_part_fast_transforms")
    if not isinstance(part_state, Mapping):
        return global_translation, global_rotation, global_scale, part_transforms

    for raw_source_index, raw_payload in sorted(part_state.items(), key=lambda item: int(item[0])):
        if not isinstance(raw_payload, Mapping):
            continue
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        editor_ids = _fast_transform_editor_ids(editor_ids_for_source_indices, (source_index,))
        if not editor_ids:
            continue
        part_transforms.append(
            {
                "source_submesh_indices": editor_ids,
                "translation": _fast_transform_vector(raw_payload, "translation", (0.0, 0.0, 0.0)),
                "rotation_degrees": _fast_transform_vector(raw_payload, "rotation_degrees", (0.0, 0.0, 0.0)),
                "scale_xyz": _fast_transform_vector(raw_payload, "scale_xyz", (1.0, 1.0, 1.0)),
            }
        )
    return global_translation, global_rotation, global_scale, part_transforms


def alignment_d3d11_fast_transform_send_state(
    state: Mapping[str, object],
    editor_ids_for_source_indices: Callable[[Sequence[int]], Sequence[int]],
    *,
    scope_source_indices: Sequence[int] | None = None,
) -> dict[str, object]:
    if not callable(editor_ids_for_source_indices):
        editor_ids_for_source_indices = lambda _indices: ()
    global_translation, global_rotation, global_scale, part_transforms = alignment_d3d11_fast_transform_preview_state(
        state,
        editor_ids_for_source_indices,
    )
    update_scope = scope_source_indices is not None
    scope_editor_ids: tuple[int, ...] = ()
    if update_scope:
        try:
            source_indices = tuple(int(index) for index in tuple(scope_source_indices or ()))
        except (TypeError, ValueError, OverflowError):
            source_indices = ()
        scope_editor_ids = _fast_transform_editor_ids(editor_ids_for_source_indices, source_indices)
    return {
        "update_scope": update_scope,
        "scope_source_indices": scope_editor_ids,
        "translation": global_translation,
        "rotation_degrees": global_rotation,
        "scale_xyz": global_scale,
        "part_transforms": part_transforms,
    }


def alignment_d3d11_fast_transform_replay_state(
    state: Mapping[str, object],
    *,
    mesh_edit_raw_active: bool,
    preview_active: bool,
    reload_reason: str = "",
    package_quality: str = "",
) -> dict[str, bool]:
    normalized_reason = str(reload_reason or "").strip().lower()
    normalized_quality = str(package_quality or "").strip().lower()
    if not normalized_quality:
        normalized_quality = str(
            state.get("active_package_quality", "")
            or state.get("queued_package_quality", "")
            or state.get("pending_package_quality", "")
            or ""
        ).strip().lower()
    material_reload = normalized_quality == "material_refresh" or normalized_reason in {
        "material",
        "material_refresh",
        "material-only",
        "material_only",
    }
    if bool(mesh_edit_raw_active) and not material_reload:
        return {
            "clear_state": True,
            "reset_host": bool(preview_active),
            "send_preview": False,
        }
    payload = state.get("pending_fast_transform")
    part_state = state.get("pending_part_fast_transforms")
    has_part_payload = isinstance(part_state, Mapping) and bool(part_state)
    return {
        "clear_state": False,
        "reset_host": False,
        "send_preview": isinstance(payload, Mapping) or has_part_payload,
    }


def alignment_d3d11_view_state_reset_needed(
    state: MutableMapping[str, object],
    current_generation: int,
) -> bool:
    current_generation = int(current_generation or 0)
    if current_generation == int(state.get("mesh_editor_view_state_reset_generation", 0) or 0):
        return False
    state["mesh_editor_view_state_reset_generation"] = current_generation
    return True


def alignment_d3d11_view_state_payload_route(
    state: MutableMapping[str, object],
    current_generation: int,
    *,
    payload_is_mapping: bool,
) -> AlignmentD3D11ViewStateRoute:
    if not bool(payload_is_mapping):
        return AlignmentD3D11ViewStateRoute(
            action="ignore",
            should_ignore=True,
            should_clear_saved_state=False,
            should_store_snapshot=False,
            should_return_saved_state=False,
        )
    if alignment_d3d11_view_state_reset_needed(state, current_generation):
        return AlignmentD3D11ViewStateRoute(
            action="reset_generation",
            should_ignore=False,
            should_clear_saved_state=True,
            should_store_snapshot=False,
            should_return_saved_state=False,
        )
    return AlignmentD3D11ViewStateRoute(
        action="store_snapshot",
        should_ignore=False,
        should_clear_saved_state=True,
        should_store_snapshot=True,
        should_return_saved_state=False,
    )


def alignment_d3d11_saved_view_state_route(
    state: MutableMapping[str, object],
    current_generation: int,
    *,
    has_saved_state: bool,
) -> AlignmentD3D11ViewStateRoute:
    if alignment_d3d11_view_state_reset_needed(state, current_generation):
        return AlignmentD3D11ViewStateRoute(
            action="reset_generation",
            should_ignore=False,
            should_clear_saved_state=True,
            should_store_snapshot=False,
            should_return_saved_state=False,
        )
    return AlignmentD3D11ViewStateRoute(
        action="return_saved" if bool(has_saved_state) else "empty",
        should_ignore=False,
        should_clear_saved_state=False,
        should_store_snapshot=False,
        should_return_saved_state=bool(has_saved_state),
    )


def alignment_d3d11_package_settings_changed(
    previous_settings: object,
    current_settings: object,
) -> bool:
    package_fields = (
        "use_textures_by_default",
        "high_quality_by_default",
        "preview_texture_max_dimension",
        "low_quality_texture_max_dimension",
        "visible_texture_mode",
        "alpha_handling_mode",
        "disable_all_support_maps",
        "disable_normal_map",
        "disable_material_map",
        "disable_height_map",
        "flip_texture_v",
    )
    return any(
        getattr(previous_settings, field_name, None) != getattr(current_settings, field_name, None)
        for field_name in package_fields
    )


def alignment_d3d11_render_settings_route(
    *,
    d3d11_active: bool,
    package_settings_changed: bool,
) -> AlignmentD3D11RenderSettingsRoute:
    if bool(d3d11_active) and bool(package_settings_changed):
        return AlignmentD3D11RenderSettingsRoute(
            action="d3d11_rebuild",
            should_invalidate_package_cache=True,
            should_mark_rebuild_reason=True,
            should_queue_static_preview_refresh=True,
            should_apply_live_render_tuning=False,
            should_apply_static_widget_settings=False,
            performance_kind="rebuild",
        )
    if bool(d3d11_active):
        return AlignmentD3D11RenderSettingsRoute(
            action="d3d11_live",
            should_invalidate_package_cache=False,
            should_mark_rebuild_reason=False,
            should_queue_static_preview_refresh=False,
            should_apply_live_render_tuning=True,
            should_apply_static_widget_settings=False,
            performance_kind="live",
        )
    return AlignmentD3D11RenderSettingsRoute(
        action="static",
        should_invalidate_package_cache=False,
        should_mark_rebuild_reason=False,
        should_queue_static_preview_refresh=True,
        should_apply_live_render_tuning=False,
        should_apply_static_widget_settings=True,
        performance_kind="",
    )


def alignment_d3d11_clear_fast_transform_state(state: MutableMapping[str, object]) -> None:
    state["pending_fast_transform"] = None
    state["pending_part_fast_transforms"] = {}


def alignment_d3d11_mark_transform_changed(
    state: MutableMapping[str, object],
    transform_generation: MutableMapping[str, object],
) -> int:
    generation = int(transform_generation.get("value", 0) or 0) + 1
    transform_generation["value"] = generation
    transform_generation["committed"] = max(
        int(transform_generation.get("committed", 0) or 0),
        generation,
    )
    state["request_id"] = _request_id(state.get("request_id")) + 1
    for key, value in (
        ("queued_model", None),
        ("queued_label", ""),
        ("queued_reason", ""),
        ("queued_transform_generation", 0),
        ("queued_package_quality", ""),
        ("pending_model", None),
        ("pending_label", ""),
        ("pending_reason", ""),
        ("pending_transform_generation", 0),
        ("pending_package_quality", ""),
        ("request_package_qualities", {}),
    ):
        state[key] = value
    return generation


def alignment_d3d11_drag_reload_stale(
    state: Mapping[str, object],
    drag_transaction: Mapping[str, object],
    drag_generation: Mapping[str, object],
    transform_generation: Mapping[str, object],
    *,
    request_id: int = 0,
) -> bool:
    if bool(drag_transaction.get("active")):
        return True
    request_generation = int(state.get("request_drag_generation", 0) or 0)
    request_generations = state.get("request_drag_generations")
    request_id = _request_id(request_id)
    if isinstance(request_generations, Mapping):
        try:
            request_generation = int(request_generations.get(request_id, request_generation) or 0)
        except (TypeError, ValueError):
            request_generation = int(state.get("request_drag_generation", 0) or 0)
    committed_generation = int(drag_generation.get("committed", 0) or 0)
    request_transform_generation = int(state.get("request_transform_generation", 0) or 0)
    request_transform_generations = state.get("request_transform_generations")
    if isinstance(request_transform_generations, Mapping):
        try:
            request_transform_generation = int(
                request_transform_generations.get(request_id, request_transform_generation) or 0
            )
        except (TypeError, ValueError):
            request_transform_generation = int(state.get("request_transform_generation", 0) or 0)
    committed_transform_generation = int(transform_generation.get("committed", 0) or 0)
    return request_generation < committed_generation or request_transform_generation < committed_transform_generation


def alignment_d3d11_mode_requires_original(mode: str) -> bool:
    return str(mode or "side_by_side") in {"side_by_side", "overlay"}


def alignment_d3d11_package_mode_has_original(mode: str) -> bool:
    normalized_mode = str(mode or "").strip().lower()
    return normalized_mode in {"side_by_side", "overlay"}


def alignment_d3d11_mode_refresh_needed(
    state: Mapping[str, object],
    mode: str,
    *,
    queued_model_active: bool,
    pending_model_active: bool,
    mesh_edit_raw_preview_active: bool,
) -> bool:
    if not alignment_d3d11_mode_requires_original(mode):
        return False
    active_display_mode = str(state.get("active_package_display_mode", "") or "")
    active_package_present = state.get("active_package") is not None
    if active_package_present and not alignment_d3d11_package_mode_has_original(active_display_mode):
        return True
    active_package_quality = str(state.get("active_package_quality", "") or "").strip().lower()
    if active_package_present and active_package_quality == "mesh_edit_raw" and not mesh_edit_raw_preview_active:
        return True
    queued_display_mode = str(state.get("queued_display_mode", "") or "")
    if queued_model_active and not alignment_d3d11_package_mode_has_original(queued_display_mode):
        return True
    pending_display_mode = str(state.get("pending_display_mode", "") or "")
    if pending_model_active and not alignment_d3d11_package_mode_has_original(pending_display_mode):
        return True
    return False


def alignment_d3d11_preview_mode_static_refresh_needed(
    state: Mapping[str, object],
    *,
    mode_refresh_needed: bool,
    renderer_active: bool,
    queued_model_active: bool,
    pending_model_active: bool,
) -> bool:
    if mode_refresh_needed:
        return True
    package_active = state.get("active_package") is not None
    return not bool(package_active or renderer_active or queued_model_active or pending_model_active)


def alignment_d3d11_request_active(
    *,
    process_active: bool,
    thread_active: bool,
    queued_model_active: bool,
    pending_model_active: bool,
    active_package_exists: bool,
) -> bool:
    return bool(process_active or thread_active or queued_model_active or pending_model_active or active_package_exists)


def alignment_d3d11_package_refresh_in_flight(
    state: Mapping[str, object],
    *,
    preview_active: bool,
    queued_model_active: bool,
    pending_model_active: bool,
    thread_active: bool,
    process_active: bool,
    active_package_exists: bool,
    committed_transform_generation: int,
) -> bool:
    if not preview_active:
        return False
    if queued_model_active or pending_model_active or thread_active:
        return True
    if bool(process_active) and not bool(state.get("preview_loaded")):
        return True
    if bool(active_package_exists) and not bool(state.get("preview_loaded")):
        return True
    active_request_id = _request_id(state.get("active_package_request_id"))
    request_generation = int(state.get("request_transform_generation", 0) or 0)
    request_generations = state.get("request_transform_generations")
    if isinstance(request_generations, Mapping) and active_request_id > 0:
        try:
            request_generation = int(request_generations.get(active_request_id, request_generation) or 0)
        except (TypeError, ValueError):
            request_generation = int(state.get("request_transform_generation", 0) or 0)
    return request_generation < int(committed_transform_generation or 0)


def alignment_d3d11_live_frame_available(
    state: Mapping[str, object],
    *,
    process_active: bool,
    active_package_exists: bool,
) -> bool:
    return bool(state.get("preview_loaded")) and bool(process_active and active_package_exists)


def alignment_d3d11_host_ready_state(
    *,
    dialog_live: bool,
    host_visible: bool,
    width: object,
    height: object,
    parent_hwnd: object,
    child_hwnd: object = 0,
    require_child: bool = False,
    check_error: object = "",
) -> AlignmentD3D11HostReadyState:
    error = str(check_error or "").strip()
    if error:
        return AlignmentD3D11HostReadyState(False, f"preview host check failed: {error}")
    if not bool(dialog_live):
        return AlignmentD3D11HostReadyState(False, "alignment dialog is closing")
    if not bool(host_visible):
        return AlignmentD3D11HostReadyState(False, "preview host widget is hidden")
    try:
        normalized_width = int(width)
        normalized_height = int(height)
    except (TypeError, ValueError, OverflowError):
        normalized_width = 0
        normalized_height = 0
    if normalized_width < 16 or normalized_height < 16:
        return AlignmentD3D11HostReadyState(
            False,
            f"preview host widget is too small ({normalized_width}x{normalized_height})",
        )
    try:
        normalized_parent_hwnd = int(parent_hwnd)
    except (TypeError, ValueError, OverflowError):
        normalized_parent_hwnd = 0
    if normalized_parent_hwnd <= 0:
        return AlignmentD3D11HostReadyState(False, "preview host parent HWND is unavailable")
    if bool(require_child):
        try:
            normalized_child_hwnd = int(child_hwnd)
        except (TypeError, ValueError, OverflowError):
            normalized_child_hwnd = 0
        if normalized_child_hwnd <= 0:
            return AlignmentD3D11HostReadyState(False, ".NET/Vortice preview child HWND is unavailable")
    return AlignmentD3D11HostReadyState(True, "preview host is ready")


def alignment_d3d11_stale_reload_route(
    *,
    dialog_live: bool,
    drag_active: bool,
    process_active: bool,
    active_package_exists: bool,
) -> AlignmentD3D11StaleReloadRouteState:
    if not bool(dialog_live):
        return AlignmentD3D11StaleReloadRouteState(False, False, "", False)
    if bool(drag_active):
        return AlignmentD3D11StaleReloadRouteState(
            should_continue=False,
            should_pause_loading=True,
            pause_message="Preview reload paused during movement.",
            active_preview_alive=False,
        )
    active_preview_alive = bool(process_active and active_package_exists)
    return AlignmentD3D11StaleReloadRouteState(True, False, "", active_preview_alive)


def alignment_d3d11_start_timeout_route(
    *,
    dialog_live: bool,
    status_matches: bool,
    process_active: bool,
    status_file_exists: bool,
) -> AlignmentD3D11StartTimeoutRouteState:
    return AlignmentD3D11StartTimeoutRouteState(
        should_report_timeout=bool(dialog_live and status_matches and process_active and not status_file_exists)
    )


def alignment_d3d11_process_finished_route(
    *,
    current_process: bool,
    widgets_live: bool,
    exit_code: object,
) -> AlignmentD3D11ProcessFinishedRouteState:
    if not bool(current_process):
        return AlignmentD3D11ProcessFinishedRouteState(True, False, False, False)
    try:
        normalized_exit_code = int(exit_code)
    except (TypeError, ValueError, OverflowError):
        normalized_exit_code = 0
    return AlignmentD3D11ProcessFinishedRouteState(
        should_ignore=False,
        should_poll_status=bool(widgets_live),
        should_cleanup=True,
        should_report_error=bool(widgets_live and normalized_exit_code != 0),
    )


__all__ = [
    "AlignmentD3D11ClearStuckLoadingRouteState",
    "AlignmentD3D11HostReadyState",
    "AlignmentD3D11LoadingRecoveryAction",
    "AlignmentD3D11LoadingWatchdogSnapshot",
    "AlignmentD3D11ProcessFinishedRouteState",
    "AlignmentD3D11RenderSettingsRoute",
    "AlignmentD3D11StaleReloadRouteState",
    "AlignmentD3D11StartTimeoutRouteState",
    "AlignmentD3D11ViewStateRoute",
    "alignment_d3d11_clear_stuck_loading_route",
    "alignment_d3d11_clear_fast_transform_state",
    "alignment_d3d11_drag_reload_stale",
    "alignment_d3d11_fast_transform_preview_state",
    "alignment_d3d11_fast_transform_queue_state",
    "alignment_d3d11_fast_transform_replay_state",
    "alignment_d3d11_fast_transform_send_state",
    "alignment_d3d11_global_fast_transform_pending",
    "alignment_d3d11_host_ready_state",
    "alignment_d3d11_live_frame_available",
    "alignment_d3d11_loaded_package_transform_current",
    "alignment_d3d11_loading_stuck",
    "alignment_d3d11_loading_recovery_action",
    "alignment_d3d11_loading_watchdog_snapshot",
    "alignment_d3d11_mark_transform_changed",
    "alignment_d3d11_mode_refresh_needed",
    "alignment_d3d11_mode_requires_original",
    "alignment_d3d11_package_mode_has_original",
    "alignment_d3d11_package_settings_changed",
    "alignment_d3d11_package_refresh_in_flight",
    "alignment_d3d11_preview_mode_static_refresh_needed",
    "alignment_d3d11_process_finished_route",
    "alignment_d3d11_record_fast_transform_payload",
    "alignment_d3d11_raw_package_active_or_pending",
    "alignment_d3d11_request_active",
    "alignment_d3d11_render_settings_route",
    "alignment_d3d11_stale_loading_restart_allowed",
    "alignment_d3d11_stale_reload_route",
    "alignment_d3d11_start_timeout_route",
    "alignment_d3d11_saved_view_state_route",
    "alignment_d3d11_view_state_payload_route",
    "alignment_d3d11_view_state_reset_needed",
]
