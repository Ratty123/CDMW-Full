"""Session callbacks for static-replacement mesh editing."""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from types import SimpleNamespace
from uuid import uuid4

from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    send_resident_presentation_state,
)
from cdmw.ui.archive_browser.static_replacement_preview_materials import (
    copy_preview_material_bindings_to_mesh,
)


def create_session_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _mesh_edit_target_mode_for_tool(_state, _callbacks, ) -> str:
    if str(_state.mesh_editor_action_bar_active_tool_key.get("value") or "") == "transform_move":
        return "selection"
    if _state._mesh_edit_current_tool() == "vertex":
        return str(_state.mesh_editor_action_bar_selection_mode.get("value") or "vertex")
    return _state._mesh_edit_target_mode_for_tool_helper(_state._mesh_edit_current_tool())

def _refresh_mesh_edit_part_combo(_state, _callbacks, ) -> None:
    previous = _state._mesh_edit_selected_scope_source_index()
    fallback = _state._mesh_edit_selected_source_index()
    _state.mesh_edit_part_combo.blockSignals(True)
    try:
        _state.mesh_edit_part_combo.clear()
        if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
            _state.mesh_edit_part_combo.addItem(_state.mesh_edit_action_control_text["no_editable_parts"], -1)
            return
        editable_indices = list(
            _state._mesh_edit_source_indices_helper(
                _state._mesh_edit_state.replacement_mesh_for_mapping,
                _state._mesh_edit_base_source_index_is_editable,
            )
        )
        if not editable_indices:
            _state.mesh_edit_part_combo.addItem(_state.mesh_edit_action_control_text["no_editable_parts"], -1)
            return
        for source_index in editable_indices:
            _state.mesh_edit_part_combo.addItem(_state._source_display_name(int(source_index)), int(source_index))
        target_index = previous if previous in editable_indices else fallback
        if target_index not in editable_indices:
            target_index = editable_indices[0]
        combo_index = _state.mesh_edit_part_combo.findData(int(target_index))
        if combo_index >= 0:
            _state.mesh_edit_part_combo.setCurrentIndex(combo_index)
    finally:
        _state.mesh_edit_part_combo.blockSignals(False)

def _mesh_edit_selected_source_indices(_state, _callbacks, *, allowed_indices: set[int] | None = None) -> tuple[int, ...]:
    allowed = allowed_indices if allowed_indices is not None else set(_state._mesh_edit_allowed_source_indices())
    return tuple(sorted(index for index in _state.mesh_edit_selected_source_indices if index in allowed))

def _mesh_edit_selected_source_vertex_count(_state, _callbacks, *, allowed_indices: set[int] | None = None) -> int:
    mesh = _state._mesh_edit_state.replacement_mesh_for_mapping
    if mesh is None:
        return 0
    submeshes = getattr(mesh, "submeshes", ()) or ()
    total = 0
    for source_index in _callbacks._mesh_edit_selected_source_indices(allowed_indices=allowed_indices):
        if 0 <= source_index < len(submeshes):
            total += len(getattr(submeshes[source_index], "vertices", ()) or ())
    return total

def _mesh_editor_current_edit_revision(_state, _callbacks, ) -> int:
    if not isinstance(_state.mesh_edit_revision, dict):
        return -1
    try:
        return int(_state.mesh_edit_revision.get("value", 0) or 0)
    except (TypeError, ValueError):
        return -1

def _mesh_editor_clear_static_replacement_session(_state, _callbacks, ) -> None:
    old_session = _state.mesh_editor_static_replacement_session_state.get("session")
    if isinstance(old_session, _state.StaticReplacementMeshEditSession):
        old_session.close()
    _state.mesh_editor_static_replacement_session_state.clear()

def _mesh_editor_ensure_static_replacement_session(_state, _callbacks, mesh=None):
    source_mesh = mesh if mesh is not None else _state._mesh_edit_state.replacement_mesh_for_mapping
    current_revision = _callbacks._mesh_editor_current_edit_revision()
    if source_mesh is None or current_revision < 0:
        return None
    session = _state.mesh_editor_static_replacement_session_state.get("session")
    material_source_getter = _state.context.get(
        "_get_original_reference_preview_model"
        if bool(_state.modify_original_clone_mode)
        else "_get_replacement_preview_model"
    )
    material_source = (
        material_source_getter()
        if callable(material_source_getter)
        else (
            _state.original_reference_preview_model
            if bool(_state.modify_original_clone_mode)
            else _state.replacement_preview_model
        )
    )
    material_source_changed = (
        material_source is not None
        and _state.mesh_editor_static_replacement_session_state.get("material_source") is not material_source
    )
    if material_source_changed:
        copy_preview_material_bindings_to_mesh(source_mesh, material_source)
    if (
        not isinstance(session, _state.StaticReplacementMeshEditSession)
        or _state.mesh_editor_static_replacement_session_state.get("mesh") is not source_mesh
        or _state.mesh_editor_static_replacement_session_state.get("revision") != current_revision
    ):
        _callbacks._mesh_editor_clear_static_replacement_session()
        session_id = str(
            getattr(_state.dialog, "_mesh_editor_embedded_session_id", "") or ""
        )
        if not session_id:
            session_id = f"static-replacement-{uuid4().hex}"
            setattr(_state.dialog, "_mesh_editor_embedded_session_id", session_id)
        session = _state.StaticReplacementMeshEditSession(session_id=session_id)
        session.open(source_mesh)
        if _state.source_skeleton is not None:
            try:
                session.controller.attach_skeleton(
                    _state.source_skeleton,
                    source_path=str(getattr(_state.source_skeleton, "path", "") or ""),
                )
            except Exception as exc:
                _callbacks._record_mesh_edit_event(
                    "mesh_edit_static_session_skeleton_attach_failed",
                    message=str(exc),
                )
        _state.mesh_editor_static_replacement_session_state["session"] = session
        _state.mesh_editor_static_replacement_session_state["mesh"] = source_mesh
        _state.mesh_editor_static_replacement_session_state["revision"] = current_revision
        _state.mesh_edit_native_result_submesh_counts["value"] = ()
    elif material_source_changed:
        copy_preview_material_bindings_to_mesh(
            session.controller.working_mesh(clone=False),
            material_source,
        )
    if material_source is not None:
        _state.mesh_editor_static_replacement_session_state["material_source"] = material_source
    return session

def _mesh_editor_result_has_deferred_native_python_apply(_state, _callbacks, result: object) -> bool:
    edit_result = getattr(result, "edit_result", None)
    metrics = getattr(edit_result, "metrics", {}) if edit_result is not None else {}
    try:
        return float(metrics.get("python_apply_deferred", 0.0) or 0.0) == 1.0
    except (TypeError, ValueError):
        return False

def _mesh_editor_result_mesh_for_state(_state, _callbacks, result: object, fallback: object | None = None) -> object | None:
    if _callbacks._mesh_editor_result_has_deferred_native_python_apply(result):
        return fallback if fallback is not None else _state._mesh_edit_state.replacement_mesh_for_mapping
    return getattr(result, "mesh", fallback)

def _mesh_editor_result_submesh_counts(_state, _callbacks, result: object) -> tuple[tuple[int, int], ...]:
    edit_result = getattr(result, "edit_result", None)
    raw_counts = getattr(edit_result, "submesh_counts", ()) if edit_result is not None else ()
    counts: list[tuple[int, int]] = []
    for raw_count in tuple(raw_counts or ()):
        try:
            vertex_count, face_count = raw_count
            counts.append((max(0, int(vertex_count)), max(0, int(face_count))))
        except (TypeError, ValueError):
            return ()
    return tuple(counts)

def _mesh_editor_result_changes_mesh(_state, _callbacks, result: object) -> bool:
    return bool(
        getattr(result, "affected_submesh_indices", None)
        or getattr(result, "changed_vertices_by_submesh", None)
        or getattr(result, "added_face_count", 0)
        or getattr(result, "removed_face_count", 0)
        or getattr(result, "moved_face_count", 0)
        or getattr(result, "material_override_groups", None)
    )

def _mesh_editor_store_result_mesh(_state, _callbacks, result: object, fallback: object | None = None) -> bool:
    mesh = _callbacks._mesh_editor_result_mesh_for_state(result, fallback)
    if mesh is None:
        return False
    _state._mesh_edit_state.replacement_mesh_for_mapping = mesh
    counts = _callbacks._mesh_editor_result_submesh_counts(result)
    _state.mesh_edit_native_result_submesh_counts["value"] = counts if _callbacks._mesh_editor_result_has_deferred_native_python_apply(result) else ()
    return True

def _mesh_editor_apply_static_replacement_edit(_state, _callbacks, mesh, action: str, **params: object):
    current_revision = _callbacks._mesh_editor_current_edit_revision()
    if current_revision < 0:
        raise RuntimeError("active static Mesh Editor edit requires a native session revision")
    session = _callbacks._mesh_editor_ensure_static_replacement_session(mesh)
    if session is None:
        raise RuntimeError("active static Mesh Editor edit requires a native session")
    result = session.apply(action, **params)
    changed = _callbacks._mesh_editor_result_changes_mesh(result)
    _state.mesh_editor_static_replacement_session_state["mesh"] = _callbacks._mesh_editor_result_mesh_for_state(result, mesh)
    _state.mesh_editor_static_replacement_session_state["revision"] = current_revision + (1 if changed else 0)
    return result

def _mesh_editor_fresh_static_replacement_session(_state, _callbacks, ):
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return None
    current_revision = _callbacks._mesh_editor_current_edit_revision()
    if current_revision < 0:
        return None
    session = _state.mesh_editor_static_replacement_session_state.get("session")
    if not isinstance(session, _state.StaticReplacementMeshEditSession):
        return None
    if (
        _state.mesh_editor_static_replacement_session_state.get("mesh") is not _state._mesh_edit_state.replacement_mesh_for_mapping
        or _state.mesh_editor_static_replacement_session_state.get("revision") != current_revision
    ):
        return None
    try:
        session.view()
    except (KeyError, RuntimeError):
        return None
    return session

def _mesh_editor_sync_static_replacement_session_to_working_mesh(_state, _callbacks, reason: str) -> bool:
    session = _callbacks._mesh_editor_fresh_static_replacement_session()
    if not isinstance(session, _state.StaticReplacementMeshEditSession):
        return True
    try:
        mesh = session.sync_working_mesh()
    except Exception as exc:
        _callbacks._record_mesh_edit_event(
            "mesh_edit_static_session_sync_failed",
            reason=str(reason or "mesh_edit.sync"),
            message=str(exc),
        )
        _state.self.set_status_message(
            ".NET/Vortice Mesh Editor sync failed; reload the preview before continuing.",
            error=True,
        )
        return False
    _state._mesh_edit_state.replacement_mesh_for_mapping = mesh
    _state.mesh_edit_native_result_submesh_counts["value"] = ()
    _state.mesh_edit_preview_model_dirty["value"] = True
    _callbacks._mesh_editor_remember_static_replacement_session_mesh()
    return True

def _mesh_editor_remember_static_replacement_session_mesh(_state, _callbacks, ) -> None:
    _state.mesh_editor_static_replacement_session_state["mesh"] = _state._mesh_edit_state.replacement_mesh_for_mapping
    _state.mesh_editor_static_replacement_session_state["revision"] = _callbacks._mesh_editor_current_edit_revision()

def _mesh_edit_commit_geometry_preview_state(_state, _callbacks, ) -> None:
    _callbacks._mesh_editor_remember_static_replacement_session_mesh()
    _state.static_preview_geometry_cache.clear()
    _state.static_preview_prepared_cache.clear()
    if callable(_state._mark_alignment_d3d11_rebuild_reason):
        _state._mark_alignment_d3d11_rebuild_reason("geometry")
    if callable(_state._alignment_d3d11_invalidate_package_cache):
        _state._alignment_d3d11_invalidate_package_cache("geometry")

def _mesh_edit_refresh_replacement_preview_model(_state, _callbacks,
        *,
        allow_defer_for_incremental_d3d11: bool = False,
    ) -> bool:
    if _state._mesh_edit_state.replacement_mesh_for_mapping is None or not callable(_state.parsed_mesh_to_preview_model):
        return False
    if (
        allow_defer_for_incremental_d3d11
        and _state._mesh_edit_tab_active()
        and not _state._alignment_d3d11_preview_active()
    ):
        _state.self.set_status_message(
            "Active Mesh Editor preview refresh requires .NET/Vortice; Python preview rebuild fallback is disabled.",
            error=True,
        )
        return False
    if tuple(_state.mesh_edit_native_result_submesh_counts.get("value") or ()):
        if allow_defer_for_incremental_d3d11 and _state._alignment_d3d11_preview_active():
            _state.mesh_edit_preview_model_dirty["value"] = True
            return False
        raise RuntimeError("native deferred edit cannot rebuild Python preview model; Python preview rebuild fallback is disabled")
    if (
        allow_defer_for_incremental_d3d11
        and _state._mesh_edit_tab_active()
        and _state._alignment_d3d11_preview_active()
    ):
        _state.mesh_edit_preview_model_dirty["value"] = True
        return False
    _state._mesh_edit_state.replacement_preview_model = _state.parsed_mesh_to_preview_model(
        _state._mesh_edit_state.replacement_mesh_for_mapping
    )
    _state.mesh_edit_preview_model_dirty["value"] = False
    return True

def _mesh_editor_queue_post_edit_textured_preview_rebuild(_state, _callbacks, reason: str) -> None:
    _state.mesh_edit_preview_model_dirty["value"] = True
    _state.mesh_edit_native_result_submesh_counts["value"] = ()
    if _state._mesh_edit_state.replacement_mesh_for_mapping is not None:
        try:
            _callbacks._mesh_edit_refresh_replacement_preview_model(
                allow_defer_for_incremental_d3d11=False,
            )
        except RuntimeError as exc:
            _callbacks._record_mesh_edit_event(
                "mesh_edit_post_exit_preview_model_refresh_failed",
                reason=str(reason or "mesh_edit.finalize"),
                message=str(exc),
            )
            _state.mesh_edit_preview_model_dirty["value"] = True
    _state._mesh_edit_apply_preview_mode_transition(str(reason or "mesh_edit.finalize"))
    _state._queue_texture_preview_refresh()

def _mesh_editor_finalize_edit_mode_exit(_state, _callbacks, reason: str, mesh_changed: bool = True) -> bool:
    was_checked = bool(_state.mesh_edit_enabled_checkbox.isChecked())
    if not _callbacks._mesh_editor_sync_static_replacement_session_to_working_mesh(str(reason or "mesh_edit.finalize")):
        if not was_checked:
            was_blocked = bool(_state.mesh_edit_enabled_checkbox.blockSignals(True))
            try:
                _state.mesh_edit_enabled_checkbox.setChecked(True)
            finally:
                _state.mesh_edit_enabled_checkbox.blockSignals(was_blocked)
        return False
    if was_checked:
        was_blocked = bool(_state.mesh_edit_enabled_checkbox.blockSignals(True))
        try:
            _state.mesh_edit_enabled_checkbox.setChecked(False)
        finally:
            _state.mesh_edit_enabled_checkbox.blockSignals(was_blocked)
    if getattr(_state, "controls_panel", None) is not None:
        _state.controls_panel.setVisible(True)
    presentation_getter = getattr(
        _state.dialog,
        "_mesh_editor_embedded_presentation_state",
        None,
    )
    if callable(presentation_getter):
        try:
            presentation_state = presentation_getter()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            presentation_state = None
        if isinstance(presentation_state, Mapping):
            send_resident_presentation_state(_state.dialog, presentation_state)
    if bool(mesh_changed):
        _state.mesh_edit_preview_model_dirty["value"] = True
    _callbacks._mesh_editor_queue_post_edit_textured_preview_rebuild(str(reason or "mesh_edit.finalize"))
    _callbacks._refresh_mesh_edit_controls()
    return True

def _mesh_editor_embedded_finalize_dotnet_import(_state, _callbacks, reason: str) -> bool:
    return _callbacks._mesh_editor_finalize_edit_mode_exit(str(reason or "dotnet_import"), mesh_changed=True)


_CALLBACKS = (
    _mesh_edit_target_mode_for_tool,
    _refresh_mesh_edit_part_combo,
    _mesh_edit_selected_source_indices,
    _mesh_edit_selected_source_vertex_count,
    _mesh_editor_current_edit_revision,
    _mesh_editor_clear_static_replacement_session,
    _mesh_editor_ensure_static_replacement_session,
    _mesh_editor_result_has_deferred_native_python_apply,
    _mesh_editor_result_mesh_for_state,
    _mesh_editor_result_submesh_counts,
    _mesh_editor_result_changes_mesh,
    _mesh_editor_store_result_mesh,
    _mesh_editor_apply_static_replacement_edit,
    _mesh_editor_fresh_static_replacement_session,
    _mesh_editor_sync_static_replacement_session_to_working_mesh,
    _mesh_editor_remember_static_replacement_session_mesh,
    _mesh_edit_commit_geometry_preview_state,
    _mesh_edit_refresh_replacement_preview_model,
    _mesh_editor_queue_post_edit_textured_preview_rebuild,
    _mesh_editor_finalize_edit_mode_exit,
    _mesh_editor_embedded_finalize_dotnet_import,
)
