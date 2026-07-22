"""Morph callbacks for static-replacement mesh editing."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace


def create_morph_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace()
    for function in _CALLBACKS:
        function.__annotations__ = {key: value.replace("_state.", "") if isinstance(value, str) else value for key, value in function.__annotations__.items()}
        bound = partial(function, state, callbacks)
        bound.__name__ = function.__name__
        bound.__annotations__ = dict(function.__annotations__)
        setattr(result, function.__name__, bound)
    return result


def _morph_slider_ensure_post_edit_deltas(_state, _callbacks, ) -> None:
    if _state._mesh_edit_state.replacement_mesh_base_for_mapping is None:
        _state.morph_slider_post_edit_deltas.clear()
        return
    expected_counts = _state._morph_slider_expected_vertex_counts_helper(_state._mesh_edit_state.replacement_mesh_base_for_mapping)
    if _state._morph_slider_post_edit_deltas_need_reset_helper(_state.morph_slider_post_edit_deltas, expected_counts):
        _state.morph_slider_post_edit_deltas[:] = _state._morph_slider_zero_post_edit_deltas()

def _morph_slider_zero_post_edit_deltas_for_sources(_state, _callbacks, source_indices: _state.Sequence[int]) -> None:
    _callbacks._morph_slider_ensure_post_edit_deltas()
    _state._morph_slider_zero_post_edit_deltas_for_sources_helper(_state.morph_slider_post_edit_deltas, source_indices)

def _morph_slider_mark_topology_changed(_state, _callbacks, reason: str) -> None:
    _state.morph_slider_topology_blocked["blocked"] = True
    _state.morph_slider_topology_blocked["reason"] = str(
        reason or _state._morph_slider_topology_changed_reason_text_helper()
    )
    _callbacks._morph_slider_refresh_controls()

def _morph_slider_refresh_topology_block_state(_state, _callbacks, ) -> bool:
    if _state._mesh_edit_state.replacement_mesh_base_for_mapping is None or _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return False
    try:
        _state.validate_morph_target(_state._mesh_edit_state.replacement_mesh_base_for_mapping, _state._mesh_edit_state.replacement_mesh_for_mapping)
    except Exception as exc:
        _state.morph_slider_topology_blocked["blocked"] = True
        _state.morph_slider_topology_blocked["reason"] = str(exc)
        return False
    _state.morph_slider_topology_blocked["blocked"] = False
    _state.morph_slider_topology_blocked["reason"] = ""
    return True

def _morph_slider_active_deltas(_state, _callbacks, ) -> tuple[_state.MeshMorphSliderDelta, ...]:
    return _state._morph_slider_active_deltas_helper(_state.morph_slider_deltas)

def _morph_slider_slider_only_mesh(_state, _callbacks, ) -> _state.Optional[_state.ParsedMesh]:
    if _state._mesh_edit_state.replacement_mesh_base_for_mapping is None:
        return None
    return _state.apply_morph_slider_values(
        _state._mesh_edit_state.replacement_mesh_base_for_mapping,
        _callbacks._morph_slider_active_deltas(),
        _state.morph_slider_values,
    )

def _morph_slider_capture_post_edit_deltas(_state, _callbacks, ) -> None:
    if not _state._morph_slider_has_loaded_deltas() or _state._mesh_edit_state.replacement_mesh_base_for_mapping is None or _state._mesh_edit_state.replacement_mesh_for_mapping is None:
        return
    if not _callbacks._morph_slider_refresh_topology_block_state():
        return
    slider_only_mesh = _callbacks._morph_slider_slider_only_mesh()
    if slider_only_mesh is None:
        return
    try:
        _state.morph_slider_post_edit_deltas[:] = _state._morph_slider_capture_post_edit_deltas_helper(
            _state._mesh_edit_state.replacement_mesh_for_mapping,
            slider_only_mesh,
        )
    except Exception as exc:
        _state.morph_slider_topology_blocked["blocked"] = True
        _state.morph_slider_topology_blocked["reason"] = str(exc)
        _state.self.set_status_message(str(exc))
        _callbacks._morph_slider_refresh_controls()

def _morph_slider_apply_to_working_mesh(_state, _callbacks,
        *,
        increment_revision: bool = True,
        refresh_controls: bool = True,
        status_message: str = "",
    ) -> bool:
    if _state._mesh_edit_state.replacement_mesh_base_for_mapping is None:
        return False
    if _state._mesh_edit_tab_active():
        _callbacks._mesh_edit_mark_native_preview_stale(
            "Active Mesh Editor morph-slider apply requires native geometry execution; Python mesh mutation fallback is disabled."
        )
        return False
    _callbacks._morph_slider_ensure_post_edit_deltas()
    try:
        _state._mesh_edit_state.replacement_mesh_for_mapping = _state.apply_morph_slider_values(
            _state._mesh_edit_state.replacement_mesh_base_for_mapping,
            _callbacks._morph_slider_active_deltas(),
            _state.morph_slider_values,
            post_edit_deltas=_state.morph_slider_post_edit_deltas,
        )
    except Exception as exc:
        _state.morph_slider_topology_blocked["blocked"] = True
        _state.morph_slider_topology_blocked["reason"] = str(exc)
        if refresh_controls:
            _callbacks._morph_slider_refresh_controls()
        return False
    _callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
    if increment_revision:
        _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _state._refresh_source_tree_selection_state()
    _state._refresh_source_assignment_columns()
    if refresh_controls:
        _callbacks._refresh_mesh_edit_controls()
    if _state._alignment_d3d11_preview_active():
        _callbacks._mesh_edit_update_live_preview(
            _state._mesh_edit_all_live_vertices_for_sources(_state._mesh_edit_preview_source_indices()),
            include_normals=True,
            immediate=True,
        )
    elif _state._mesh_edit_tab_active():
        _callbacks._mesh_edit_mark_native_preview_stale(
            "Active Mesh Editor morph-slider apply requires native D3D11 refresh; Python preview rebuild fallback is disabled."
        )
    else:
        _state._queue_static_preview_rebuild()
    if status_message:
        _state.self.set_status_message(status_message)
    return True

def _morph_slider_sync_row_widgets(_state, _callbacks, ) -> None:
    _state.morph_slider_update_guard["active"] = True
    try:
        for sync_state in _state._morph_slider_row_sync_states_helper(_state.morph_slider_rows, _state.morph_slider_values):
            slider = sync_state.row.get("slider")
            spin = sync_state.row.get("spin")
            if isinstance(slider, _state.QSlider):
                slider.setValue(sync_state.slider_value)
            if isinstance(spin, _state.QDoubleSpinBox):
                spin.setValue(sync_state.percent)
    finally:
        _state.morph_slider_update_guard["active"] = False

def _morph_slider_begin_change(_state, _callbacks, reason: str = "Morph slider") -> None:
    if _state.morph_slider_change_active.get("active"):
        return
    if _state._mesh_edit_state.replacement_mesh_for_mapping is not None:
        _callbacks._mesh_edit_record_snapshot()
    _state.morph_slider_change_active["active"] = True

def _morph_slider_end_change(_state, _callbacks, ) -> None:
    _state.morph_slider_change_active["active"] = False

def _morph_slider_set_value(_state, _callbacks,
        slider_id: str,
        percent: float,
        *,
        record_snapshot: bool = True,
        finish_change: bool = True,
    ) -> None:
    delta = _state.morph_slider_deltas.get(str(slider_id))
    commit_state = _state._morph_slider_value_commit_state_helper(
        update_active=bool(_state.morph_slider_update_guard.get("active")),
        delta=delta,
        supported=_state._morph_slider_supported(),
        blocked=bool(_state.morph_slider_topology_blocked.get("blocked")),
        values=_state.morph_slider_values,
        percent=percent,
    )
    if not commit_state.should_commit:
        return
    if record_snapshot:
        _callbacks._morph_slider_begin_change("Morph slider")
    _state.morph_slider_values[commit_state.slider_id] = commit_state.clamped_percent
    _callbacks._morph_slider_sync_row_widgets()
    _callbacks._morph_slider_apply_to_working_mesh(status_message=commit_state.status_text)
    if record_snapshot and finish_change:
        _callbacks._morph_slider_end_change()

def _morph_slider_clear_rows(_state, _callbacks, ) -> None:
    while _state.morph_slider_rows_layout.count():
        item = _state.morph_slider_rows_layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
    _state.morph_slider_rows.clear()

def _morph_slider_add_row(_state, _callbacks, delta: _state.MeshMorphSliderDelta) -> None:
    row_state = _state._morph_slider_row_state_helper(delta, _state.morph_slider_values)
    row = _state.QFrame(_state.morph_slider_rows_widget)
    row_layout = _state.QGridLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setHorizontalSpacing(3)
    row_layout.setVerticalSpacing(2)
    label = _state.QLabel(row_state.label)
    label.setMinimumWidth(0)
    label.setSizePolicy(_state.QSizePolicy.Ignored, _state.QSizePolicy.Preferred)
    reset_button = _state.QPushButton(row_state.reset_text)
    reset_button.setMinimumWidth(0)
    slider = _state.QSlider(_state.Qt.Horizontal)
    slider.setRange(row_state.slider_minimum, row_state.slider_maximum)
    slider.setSingleStep(100)
    slider.setPageStep(1000)
    spin = _state._make_double_spin_helper(
        0.0,
        row_state.spin_minimum,
        row_state.spin_maximum,
        2,
        1.0,
        " %",
    )
    spin.setMinimumWidth(76)
    row_layout.addWidget(label, 0, 0, 1, 3)
    row_layout.addWidget(reset_button, 1, 0)
    row_layout.addWidget(slider, 1, 1)
    row_layout.addWidget(spin, 1, 2)
    reset_button.clicked.connect(
        lambda _checked=False, sid=row_state.slider_id, default=row_state.reset_percent: _callbacks._morph_slider_set_value(
            sid,
            default,
        )
    )
    slider.sliderPressed.connect(lambda sid=row_state.slider_id: _callbacks._morph_slider_begin_change("Morph slider"))
    slider.valueChanged.connect(
        lambda raw_value, sid=row_state.slider_id: _callbacks._morph_slider_set_value(
            sid,
            float(raw_value) / 100.0,
            record_snapshot=False,
            finish_change=False,
        )
    )
    slider.sliderReleased.connect(_callbacks._morph_slider_end_change)
    spin.valueChanged.connect(
        lambda value, sid=row_state.slider_id: _callbacks._morph_slider_set_value(
            sid,
            float(value),
        )
    )
    _state.morph_slider_rows_layout.addWidget(row)
    _state.morph_slider_rows.append({"slider_id": row_state.slider_id, "slider": slider, "spin": spin, "row": row})

def _morph_slider_rebuild_rows(_state, _callbacks, ) -> None:
    _callbacks._morph_slider_clear_rows()
    for delta in _callbacks._morph_slider_active_deltas():
        _callbacks._morph_slider_add_row(delta)
    _callbacks._morph_slider_sync_row_widgets()

def _morph_slider_refresh_controls(_state, _callbacks, ) -> None:
    supported = _state._morph_slider_supported()
    loaded = _state._morph_slider_has_loaded_deltas()
    blocked = bool(_state.morph_slider_topology_blocked.get("blocked"))
    selected_count = _state._mesh_edit_index_group_count_helper(_state.mesh_edit_selected_vertices_by_submesh)
    has_nonzero_values = _state._morph_slider_has_nonzero_values()
    control_state = _state._morph_slider_control_state_helper(
        supported=supported,
        loaded=loaded,
        blocked=blocked,
        selected_count=selected_count,
        has_nonzero_values=has_nonzero_values,
    )
    _state.morph_slider_group.setEnabled(control_state["group_enabled"])
    _state.morph_slider_create_button.setEnabled(control_state["create_enabled"])
    _state.morph_slider_manage_button.setEnabled(control_state["manage_enabled"])
    for row in _state.morph_slider_rows:
        row_widget = row.get("row")
        if isinstance(row_widget, _state.QWidget):
            row_widget.setEnabled(control_state["rows_enabled"])
    _state.morph_slider_reset_button.setEnabled(control_state["reset_enabled"])
    _state.morph_slider_bake_button.setEnabled(control_state["bake_enabled"])
    _state.morph_slider_status_label.setText(
        _state._morph_slider_status_text_helper(
            supported=supported,
            blocked=blocked,
            block_reason=_state.morph_slider_topology_blocked.get("reason"),
            loaded=loaded,
            profile_count=len(_state.morph_slider_profiles),
            slider_count=len(_state.morph_slider_deltas),
        )
    )

def _morph_slider_reload_profiles(_state, _callbacks, *, preserve_values: bool = False) -> None:
    reload_state = _state._morph_slider_reload_state_helper(
        preserve_values=preserve_values,
        values=_state.morph_slider_values,
        supported=_state._morph_slider_supported(),
        has_base_mesh=_state._mesh_edit_state.replacement_mesh_base_for_mapping is not None,
    )
    old_values = reload_state.old_values
    _state.morph_slider_profiles.clear()
    _state.morph_slider_deltas.clear()
    _state.morph_slider_values.clear()
    if reload_state.clear_block_reason:
        _state.morph_slider_topology_blocked["blocked"] = False
        _state.morph_slider_topology_blocked["reason"] = ""
    if not reload_state.should_load_profiles:
        _state.morph_slider_post_edit_deltas.clear()
        _callbacks._morph_slider_rebuild_rows()
        _callbacks._morph_slider_refresh_controls()
        return
    profiles = _state.load_morph_slider_profiles(
        _state.morph_slider_profile_root,
        _state._mesh_edit_state.replacement_mesh_base_for_mapping,
        _state.entry.path,
    )
    _state.morph_slider_profiles.extend(profiles)
    used_slider_ids: set[str] = set()
    for profile_index, profile in enumerate(profiles):
        for spec in tuple(profile.sliders or ()):
            slider_id = _state._morph_slider_unique_slider_id_helper(
                spec.slider_id,
                used_slider_ids,
                profile_index=profile_index,
            )
            try:
                delta = _state.load_morph_slider_delta(
                    _state._mesh_edit_state.replacement_mesh_base_for_mapping,
                    profile,
                    spec,
                    slider_id=slider_id,
                )
            except Exception as exc:
                _state.self.append_archive_log(f"Skipped incompatible Morph Slider {spec.label or spec.slider_id}: {exc}")
                continue
            used_slider_ids.add(slider_id.lower())
            _state.morph_slider_deltas[delta.slider_id] = delta
            _state.morph_slider_values[delta.slider_id] = _state._morph_slider_value_or_default_helper(
                old_values,
                delta.slider_id,
                delta.default_percent,
            )
    _state.morph_slider_post_edit_deltas[:] = _state._morph_slider_zero_post_edit_deltas()
    _callbacks._morph_slider_capture_post_edit_deltas()
    _callbacks._morph_slider_rebuild_rows()
    _callbacks._morph_slider_refresh_controls()

def _morph_slider_reset_all(_state, _callbacks, ) -> None:
    reset_state = _state._morph_slider_reset_state_helper(loaded=_state._morph_slider_has_loaded_deltas())
    if not reset_state.should_reset:
        return
    _callbacks._morph_slider_begin_change(reset_state.change_label)
    for delta in _callbacks._morph_slider_active_deltas():
        _state.morph_slider_values[delta.slider_id] = float(delta.default_percent)
    _callbacks._morph_slider_sync_row_widgets()
    _callbacks._morph_slider_apply_to_working_mesh(status_message=reset_state.status_text)
    _callbacks._morph_slider_end_change()

def _morph_slider_clone_working_mesh_for_bake(_state, _callbacks, ) -> _state.ParsedMesh | None:
    mesh = _state._mesh_edit_state.replacement_mesh_for_mapping
    if mesh is None:
        return None
    native_snapshot = None
    try:
        from cdmw.services.mesh_workflow_service import (
            dispose_native_mesh_submesh_snapshot,
            invalidate_native_mesh_session_submeshes,
            restore_native_mesh_submesh_snapshot,
            snapshot_native_mesh_submeshes,
        )

        native_snapshot = snapshot_native_mesh_submeshes(mesh)
        if native_snapshot is not None:
            baked_mesh = _state.ParsedMesh()
            if restore_native_mesh_submesh_snapshot(baked_mesh, native_snapshot):
                invalidate_native_mesh_session_submeshes(
                    baked_mesh,
                    range(len(getattr(baked_mesh, "submeshes", ()) or ())),
                )
                return baked_mesh
    except Exception as exc:
        _callbacks._record_mesh_edit_event("morph_slider_native_bake_snapshot_error", message=str(exc))
    finally:
        if native_snapshot is not None:
            try:
                dispose_native_mesh_submesh_snapshot(native_snapshot)
            except Exception as exc:
                _callbacks._record_mesh_edit_event("morph_slider_native_bake_snapshot_dispose_failed", message=str(exc))
    message = "Native morph-slider bake snapshot failed; Python full-mesh bake clone fallback is disabled."
    _callbacks._record_mesh_edit_event(
        "morph_slider_native_bake_snapshot_failed",
        message=message,
    )
    _state.self.set_status_message(message, error=True)
    return None

def _morph_slider_bake(_state, _callbacks, ) -> None:
    bake_state = _state._morph_slider_bake_state_helper(
        has_working_mesh=_state._mesh_edit_state.replacement_mesh_for_mapping is not None,
        loaded=_state._morph_slider_has_loaded_deltas(),
        has_nonzero_values=_state._morph_slider_has_nonzero_values(),
    )
    if not bake_state.should_bake:
        return
    baked_base_mesh = _callbacks._morph_slider_clone_working_mesh_for_bake()
    if baked_base_mesh is None:
        return
    _callbacks._morph_slider_begin_change(bake_state.change_label)
    _state._mesh_edit_state.replacement_mesh_base_for_mapping = baked_base_mesh
    _state.morph_slider_values.clear()
    _state.morph_slider_post_edit_deltas[:] = _state._morph_slider_zero_post_edit_deltas()
    _state.morph_slider_topology_blocked["blocked"] = False
    _state.morph_slider_topology_blocked["reason"] = ""
    _callbacks._morph_slider_reload_profiles(preserve_values=False)
    _state.mesh_edit_revision["value"] = int(_state.mesh_edit_revision.get("value", 0) or 0) + 1
    _callbacks._mesh_edit_commit_geometry_preview_state()
    _state._refresh_source_assignment_columns()
    _callbacks._refresh_mesh_edit_controls()
    _callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(_state._mesh_edit_preview_source_indices(), replace_all=True)
    _callbacks._morph_slider_end_change()
    _state.self.set_status_message(bake_state.status_text)

def _morph_slider_default_region_amount(_state, _callbacks, ) -> float:
    if _state._mesh_edit_state.replacement_mesh_base_for_mapping is None:
        return 0.01
    return _state._mesh_edit_selection_region_default_amount_helper(
        _state._mesh_edit_state.replacement_mesh_base_for_mapping,
        _state.mesh_edit_selected_vertices_by_submesh,
    )

def _morph_slider_create_from_selection(_state, _callbacks, ) -> None:
    route_state = _state._morph_slider_create_route_state_helper(
        has_base_mesh=_state._mesh_edit_state.replacement_mesh_base_for_mapping is not None,
        has_selection=_state._mesh_edit_has_index_groups_helper(_state.mesh_edit_selected_vertices_by_submesh),
    )
    if not route_state.allowed:
        _state.QMessageBox.information(
            _state.dialog,
            route_state.title,
            route_state.message,
        )
        return
    name, accepted = _state.QInputDialog.getText(
        _state.dialog,
        _state._morph_slider_create_action_text_helper(),
        _state._morph_slider_name_prompt_text_helper(),
        text=_state._morph_slider_default_name_text_helper(),
    )
    if not accepted or not str(name or "").strip():
        return
    default_amount = _callbacks._morph_slider_default_region_amount()
    amount, accepted = _state.QInputDialog.getDouble(
        _state.dialog,
        _state._morph_slider_create_action_text_helper(),
        _state._morph_slider_amount_prompt_text_helper(),
        float(default_amount),
        0.000001,
        1000000.0,
        6,
    )
    if not accepted:
        return
    feather, accepted = _state.QInputDialog.getInt(
        _state.dialog,
        _state._morph_slider_create_action_text_helper(),
        _state._morph_slider_feather_prompt_text_helper(),
        2,
        0,
        32,
        1,
    )
    if not accepted:
        return
    try:
        profile = _state.create_region_volume_slider_profile(
            _state._mesh_edit_state.replacement_mesh_base_for_mapping,
            _state.entry.path,
            _state.morph_slider_profile_root,
            _state.mesh_edit_selected_vertices_by_submesh,
            name=str(name),
            amount=float(amount),
            feather=int(feather),
        )
    except Exception as exc:
        _state.QMessageBox.warning(_state.dialog, _state._morph_slider_create_action_text_helper(), str(exc))
        return
    _callbacks._morph_slider_reload_profiles(preserve_values=True)
    _state.self.set_status_message(_state._morph_slider_created_status_text_helper(profile.name))


_CALLBACKS = (
    _morph_slider_ensure_post_edit_deltas,
    _morph_slider_zero_post_edit_deltas_for_sources,
    _morph_slider_mark_topology_changed,
    _morph_slider_refresh_topology_block_state,
    _morph_slider_active_deltas,
    _morph_slider_slider_only_mesh,
    _morph_slider_capture_post_edit_deltas,
    _morph_slider_apply_to_working_mesh,
    _morph_slider_sync_row_widgets,
    _morph_slider_begin_change,
    _morph_slider_end_change,
    _morph_slider_set_value,
    _morph_slider_clear_rows,
    _morph_slider_add_row,
    _morph_slider_rebuild_rows,
    _morph_slider_refresh_controls,
    _morph_slider_reload_profiles,
    _morph_slider_reset_all,
    _morph_slider_clone_working_mesh_for_bake,
    _morph_slider_bake,
    _morph_slider_default_region_amount,
    _morph_slider_create_from_selection,
)
