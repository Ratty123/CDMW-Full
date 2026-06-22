"""Selection/mapping display helpers for static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace


def _safe_call(func, *args, default=None, **kwargs):
    if not callable(func):
        return default
    try:
        return func(*args, **kwargs)
    except (KeyError, NameError):
        return default


def create_alignment_selection_mapping_helpers(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get("Dict")
    Mapping = context.get("Mapping")
    QBrush = context.get("QBrush")
    QColor = context.get("QColor")
    Sequence = context.get("Sequence")
    StaticSourcePartAdjustment = context.get("StaticSourcePartAdjustment")
    _added_part_texture_role_label_helper = context.get("_added_part_texture_role_label_helper")
    _alignment_dialog_widgets_live = context.get("_alignment_dialog_widgets_live")
    _current_source_part_adjustments_helper = context.get("_current_source_part_adjustments_helper")
    _disabled_source_part_indices_helper = context.get("_disabled_source_part_indices_helper")
    _enabled_renderable_source_indices_helper = context.get("_enabled_renderable_source_indices_helper")
    _format_index_list_helper = context.get("_format_index_list_helper")
    _auto_fit_alignment_tree_columns = context.get("_auto_fit_alignment_tree_columns")
    _geometry_mapping_text_by_target_helper = context.get("_geometry_mapping_text_by_target_helper")
    _geometry_original_copy_text_by_index_helper = context.get("_geometry_original_copy_text_by_index_helper")
    _invalidate_source_display_cache_helper = context.get("_invalidate_source_display_cache_helper")
    _is_default_source_part_adjustment = context.get("_is_default_source_part_adjustment")
    _is_marker_source = context.get("_is_marker_source")
    _mesh_replacement_selection_view_initial_model_helper = context.get("_mesh_replacement_selection_view_initial_model_helper")
    _output_impact_counts_helper = context.get("_output_impact_counts_helper")
    _qt_object_is_valid = context.get("_qt_object_is_valid")
    _removed_target_dds_cell_text_helper = context.get("_removed_target_dds_cell_text_helper")
    _selected_source_summary_helper = context.get("_selected_source_summary_helper")
    _source_display_name_helper = context.get("_source_display_name_helper")
    _source_index_help_text_helper = context.get("_source_index_help_text_helper")
    _source_index_is_enabled_renderable_helper = context.get("_source_index_is_enabled_renderable_helper")
    _source_material_name_for_index_helper = context.get("_source_material_name_for_index_helper")
    _source_outliner_dds_text_helper = context.get("_source_outliner_dds_text_helper")
    _source_outliner_state_helper = context.get("_source_outliner_state_helper")
    _source_part_properties_inspector_state_helper = context.get("_source_part_properties_inspector_state_helper")
    _source_part_role_override_state_helper = context.get("_source_part_role_override_state_helper")
    _source_part_selection_added_texture_context_text_helper = context.get("_source_part_selection_added_texture_context_text_helper")
    _source_part_selection_context_state_helper = context.get("_source_part_selection_context_state_helper")
    _source_part_selection_texture_fallback_helper = context.get("_source_part_selection_texture_fallback_helper")
    _source_part_selection_texture_row_context_text_helper = context.get("_source_part_selection_texture_row_context_text_helper")
    _source_slot_for_added_part_helper = context.get("_source_slot_for_added_part_helper")
    _source_role_label_helper = context.get("_source_role_label_helper")
    _source_role_override_value_helper = context.get("_source_role_override_value_helper")
    _source_assignment_index_helper = context.get("_source_assignment_index_helper")
    _source_assignment_row_state_helper = context.get("_source_assignment_row_state_helper")
    _source_indices_for_target_name_helper = context.get("_source_indices_for_target_name_helper")
    _source_target_summary_helper = context.get("_source_target_summary_helper")
    _source_tree_status_text_helper = context.get("_source_tree_status_text_helper")
    _target_display_name_helper = context.get("_target_display_name_helper")
    _target_index_for_name_helper = context.get("_target_index_for_name_helper")
    _target_outliner_state_helper = context.get("_target_outliner_state_helper")
    _target_submesh_display_name_helper = context.get("_target_submesh_display_name_helper")
    _target_source_indices_helper = context.get("_target_source_indices_helper")
    _texture_role_label_for_slot = context.get("_texture_role_label_for_slot")
    _update_mesh_replacement_selection_view_model_helper = context.get("_update_mesh_replacement_selection_view_model_helper")
    _selection_filter_refresh_needed_helper = context.get("_selection_filter_refresh_needed_helper")
    infer_static_replacement_part_role = context.get("infer_static_replacement_part_role")
    simplified_part_label = context.get("simplified_part_label")

    _copied_original_dds_badge = context.get("_copied_original_dds_badge")
    _copied_original_texture_tooltip = context.get("_copied_original_texture_tooltip")
    _parse_mapping_edit = context.get("_parse_mapping_edit")
    _source_texture_slot_count = context.get("_source_texture_slot_count")
    _target_physics_status_text = context.get("_target_physics_status_text")
    _target_texture_status_text = context.get("_target_texture_status_text")

    _get_original_mesh_for_mapping = context.get("_get_original_mesh_for_mapping")
    _get_added_texture_role_combo = context.get("_get_added_texture_role_combo")
    _get_mapping_tree = context.get("_get_mapping_tree")
    _get_mappings_by_target = context.get("_get_mappings_by_target")
    _get_part_glow_color_checkbox = context.get("_get_part_glow_color_checkbox")
    _get_properties_labels = context.get("_get_properties_labels")
    _get_prune_unmapped_original_dds_checkbox = context.get("_get_prune_unmapped_original_dds_checkbox")
    _get_rebuild_sidecar_checkbox = context.get("_get_rebuild_sidecar_checkbox")
    _get_replacement_mesh_for_mapping = context.get("_get_replacement_mesh_for_mapping")
    _get_selected_added_part_texture_row = context.get("_get_selected_added_part_texture_row")
    _get_selected_texture_row = context.get("_get_selected_texture_row")
    _get_source_tree = context.get("_get_source_tree")
    _get_source_tree_layout_state = context.get("_get_source_tree_layout_state")
    _get_texture_filter_selected_checkbox = context.get("_get_texture_filter_selected_checkbox")
    _get_texture_sets = context.get("_get_texture_sets")
    _get_texture_transform_material_combo = context.get("_get_texture_transform_material_combo")
    _refresh_added_part_texture_tree = context.get("_refresh_added_part_texture_tree")
    _refresh_geometry_summary = context.get("_refresh_geometry_summary")
    _refresh_mesh_replacement_properties_inspector_hook = context.get("_refresh_mesh_replacement_properties_inspector")
    _refresh_output_impact_review = context.get("_refresh_output_impact_review")
    _refresh_parts_outliner = context.get("_refresh_parts_outliner")
    _refresh_source_material_plan = context.get("_refresh_source_material_plan")
    _refresh_ui_texture_sets_after_source_part_material_override = context.get("_refresh_ui_texture_sets_after_source_part_material_override")
    _selected_part_glow_rgb_from_controls = context.get("_selected_part_glow_rgb_from_controls")

    copied_original_texture_intents_by_source = context.get("copied_original_texture_intents_by_source")
    control_tabs = context.get("control_tabs")
    independent_output_source_indices = context.get("independent_output_source_indices")
    mapping_edits = context.get("mapping_edits")
    mapping_edits_by_target = context.get("mapping_edits_by_target")
    original_items_by_index = context.get("original_items_by_index")
    preview_only_source_indices = context.get("preview_only_source_indices")
    selected_source_highlight_indices = context.get("selected_source_highlight_indices")
    selected_source_part = context.get("selected_source_part")
    selected_target_highlight_indices = context.get("selected_target_original_highlight_indices")
    selected_target_slot = context.get("selected_target_slot")
    selection_context_label = context.get("selection_context_label")
    source_display_cache_revision = context.get("source_display_cache_revision")
    source_display_duplicate_counts_cache = context.get("source_display_duplicate_counts_cache")
    source_display_label_cache = context.get("source_display_label_cache")
    source_display_overrides = context.get("source_display_overrides")
    source_items_by_index = context.get("source_items_by_index")
    source_material_texture_override_assignments = context.get("source_material_texture_override_assignments")
    source_part_adjustments = context.get("source_part_adjustments")
    source_role_overrides = context.get("source_role_overrides")
    texture_filter_refresh = context.get("texture_filter_refresh")
    texture_overrides_dirty = context.get("texture_overrides_dirty")
    texture_override_rows = context.get("texture_override_rows")

    def _replacement_mesh():
        return _safe_call(_get_replacement_mesh_for_mapping)

    def _original_mesh():
        return _safe_call(_get_original_mesh_for_mapping)

    def _texture_sets():
        return _safe_call(_get_texture_sets, default={})

    def _source_index_is_enabled_renderable(source_index: int) -> bool:
        return bool(
            _source_index_is_enabled_renderable_helper(
                source_index,
                _replacement_mesh(),
                source_part_adjustments or {},
                is_marker_source=_is_marker_source,
            )
        )

    _enabled_renderable_source_indices = lambda source_indices: _enabled_renderable_source_indices_helper(
        source_indices,
        source_index_is_enabled_renderable=_source_index_is_enabled_renderable,
    )

    def _mapping_role_hint(label: str) -> str:
        return infer_static_replacement_part_role(label)

    _source_role_override_value = lambda source_index: _source_role_override_value_helper(
        source_index,
        source_role_overrides,
        source_part_adjustments,
    )
    _source_role_label = lambda source_index: _source_role_label_helper(
        source_index,
        _replacement_mesh(),
        source_role_overrides,
        source_part_adjustments,
        role_hint=_mapping_role_hint,
    )
    _invalidate_source_display_cache = lambda: _invalidate_source_display_cache_helper(
        source_display_label_cache,
        source_display_duplicate_counts_cache,
        source_display_cache_revision,
    )
    _source_display_name = lambda source_index: _source_display_name_helper(
        source_index,
        _replacement_mesh(),
        source_display_overrides,
        source_display_label_cache,
        source_display_duplicate_counts_cache,
    )
    _selected_source_summary = lambda raw_text: _selected_source_summary_helper(
        raw_text,
        _replacement_mesh(),
        display_name=_source_display_name,
        is_marker_source=_is_marker_source,
    )
    _source_index_help_text = lambda: _source_index_help_text_helper(
        _replacement_mesh(),
        display_name=_source_display_name,
        is_marker_source=_is_marker_source,
    )
    _target_display_name = lambda target_index: _target_display_name_helper(
        target_index,
        _original_mesh(),
    )
    _target_index_for_name = lambda target_name: _target_index_for_name_helper(
        target_name,
        _original_mesh(),
    )

    mesh_replacement_selection_view_model: Dict[str, object] = _mesh_replacement_selection_view_initial_model_helper()

    _target_outliner_state = lambda target_index, source_indices: _target_outliner_state_helper(
        target_index,
        source_indices,
        original_mesh=_original_mesh(),
        replacement_mesh=_replacement_mesh(),
        enabled_renderable_source_indices=_enabled_renderable_source_indices,
        target_physics_status_text=_target_physics_status_text,
    )
    _source_outliner_state = lambda source_index, assigned_targets=(): _source_outliner_state_helper(
        source_index,
        assigned_targets,
        source_part_adjustments=source_part_adjustments,
        preview_only_source_indices=preview_only_source_indices,
        independent_output_source_indices=independent_output_source_indices,
        assigned_target_indices=lambda index: _safe_call(
            context.get("_source_assigned_target_indices_helper"),
            index,
            mapping_edits,
            parse_mapping_edit=_parse_mapping_edit,
            default=(),
        ),
    )

    def _source_tree_status_text(source_index: int, assigned_targets: Sequence[int] = ()) -> tuple[str, str]:
        state_text, state_color = _source_outliner_state(source_index, assigned_targets)
        dds_badge = _safe_call(_copied_original_dds_badge, source_index, default="")
        return _source_tree_status_text_helper(state_text, state_color, dds_badge)

    def _source_outliner_dds_text(source_index: int) -> str:
        dds_badge = _safe_call(_copied_original_dds_badge, source_index, default="")
        return _source_outliner_dds_text_helper(
            source_index,
            dds_badge,
            source_texture_slot_count=_source_texture_slot_count,
        )

    def _material_sidecar_patch_enabled() -> bool | None:
        checkbox = _safe_call(_get_rebuild_sidecar_checkbox)
        if checkbox is None:
            return None
        return bool(checkbox.isChecked())

    def _removed_target_dds_cell_text(target_label_text: str) -> str:
        current_dds = _safe_call(_target_texture_status_text, target_label_text, default="")
        return _removed_target_dds_cell_text_helper(current_dds, _material_sidecar_patch_enabled())

    def _set_mesh_replacement_selection_view(
        *,
        kind: str,
        source_indices: Sequence[int] = (),
        target_indices: Sequence[int] = (),
        material_name: str = "",
        texture_role: str = "",
        texture_path: str = "",
        warning: str = "",
    ) -> None:
        if not _alignment_dialog_widgets_live():
            return
        _update_mesh_replacement_selection_view_model_helper(
            mesh_replacement_selection_view_model,
            kind=kind,
            source_indices=source_indices,
            target_indices=target_indices,
            material_name=material_name,
            texture_role=texture_role,
            texture_path=texture_path,
            warning=warning,
        )
        _refresh_mesh_replacement_properties_inspector()

    def _output_impact_counts() -> tuple[int, int, int, int, str]:
        sidecar_checkbox = _safe_call(_get_rebuild_sidecar_checkbox)
        prune_checkbox = _safe_call(_get_prune_unmapped_original_dds_checkbox)
        return _output_impact_counts_helper(
            mapping_edits,
            texture_override_rows,
            parse_mapping_edit=_parse_mapping_edit,
            enabled_renderable_source_indices=_enabled_renderable_source_indices,
            sidecar_enabled=bool(sidecar_checkbox.isChecked()) if sidecar_checkbox is not None else False,
            prune_unmapped_enabled=bool(prune_checkbox.isChecked()) if prune_checkbox is not None else False,
        )

    def _refresh_mesh_replacement_properties_inspector() -> None:
        if not _alignment_dialog_widgets_live():
            return
        labels = _safe_call(_get_properties_labels, default=None)
        if labels is None:
            return
        identity_label, assignment_label, dds_label, output_label, warnings_label = labels
        if not all(_qt_object_is_valid(label) for label in labels):
            return

        def _properties_target_dds_label(target_index: int) -> str:
            original_mesh = _original_mesh()
            if original_mesh is None or target_index < 0:
                return ""
            submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
            if target_index >= len(submeshes):
                return ""
            return _target_submesh_display_name_helper(target_index, submeshes[target_index])

        inspector_state = _source_part_properties_inspector_state_helper(
            mesh_replacement_selection_view_model,
            output_counts=_output_impact_counts(),
            target_source_indices=lambda target_index: _target_source_indices_helper(
                target_index,
                mapping_edits_by_target,
                parse_mapping_edit=_parse_mapping_edit,
            ),
            target_outliner_state=_target_outliner_state,
            format_source_indices=lambda indices: _format_index_list_helper(indices, display_name=_source_display_name),
            format_target_indices=lambda indices: _format_index_list_helper(indices, display_name=_target_display_name),
            target_dds_label=_properties_target_dds_label,
            target_texture_status_text=_target_texture_status_text,
            source_assigned_target_indices=lambda source_index: _safe_call(
                context.get("_source_assigned_target_indices_helper"),
                source_index,
                mapping_edits,
                parse_mapping_edit=_parse_mapping_edit,
                default=(),
            ),
            source_outliner_state=_source_outliner_state,
            source_material_name=lambda source_index: _source_material_name_for_index_helper(
                source_index,
                _replacement_mesh(),
                _texture_sets(),
            ),
        )
        identity_label.setText(inspector_state.identity_html)
        assignment_label.setText(inspector_state.assignment_html)
        dds_label.setText(inspector_state.dds_html)
        output_label.setText(inspector_state.output_html)
        warnings_label.setText(inspector_state.warning_html)
        warnings_label.setVisible(inspector_state.warning_visible)

    def _selection_context_texture_text() -> str:
        selected_texture_row = _safe_call(_get_selected_texture_row, default={})
        row_state = selected_texture_row.get("row") if isinstance(selected_texture_row, dict) else None
        if isinstance(row_state, Mapping):
            return _source_part_selection_texture_row_context_text_helper(
                row_state,
                role_label_for_slot=_texture_role_label_for_slot,
                simplify_part_label=simplified_part_label,
            )
        selected_added_part_texture_row = _safe_call(_get_selected_added_part_texture_row, default={})
        added_role_combo = _safe_call(_get_added_texture_role_combo)
        try:
            added_source_index = int(selected_added_part_texture_row.get("source_index", -1))
            added_role = str(added_role_combo.currentData() or "base") if added_role_combo is not None else ""
        except (AttributeError, TypeError, ValueError):
            added_source_index = -1
            added_role = ""
        if added_source_index >= 0:
            source_path = _source_slot_for_added_part_helper(
                added_source_index,
                added_role,
                _replacement_mesh(),
                _texture_sets(),
                source_material_texture_override_assignments,
            )
            return _source_part_selection_added_texture_context_text_helper(
                added_source_index,
                added_role,
                source_path,
                source_display_name=_source_display_name,
                added_part_texture_role_label=_added_part_texture_role_label_helper,
            )
        texture_transform_material_combo = _safe_call(_get_texture_transform_material_combo)
        material_name = (
            texture_transform_material_combo.currentText().strip()
            if texture_transform_material_combo is not None
            else ""
        )
        return _source_part_selection_texture_fallback_helper(material_name)

    def _update_selection_context() -> None:
        context_state = _source_part_selection_context_state_helper(
            selected_tab=control_tabs.tabText(control_tabs.currentIndex()) if control_tabs.count() else "Setup",
            source_index=selected_source_part.get("index", -1),
            target_index=selected_target_slot.get("index", -1),
            selected_source_highlight_indices=tuple(selected_source_highlight_indices),
            selected_target_highlight_indices=tuple(selected_target_highlight_indices),
            texture_text=_selection_context_texture_text(),
            source_display_name=_source_display_name,
            target_display_name=_target_display_name,
        )
        selection_context_label.setText(context_state.label_text)
        selection_context_label.setToolTip(context_state.tooltip_text)

    def _ensure_source_part_adjustment(source_index: int) -> StaticSourcePartAdjustment:
        adjustment = source_part_adjustments.get(source_index)
        if adjustment is None:
            adjustment = StaticSourcePartAdjustment(source_submesh_index=source_index)
            source_part_adjustments[source_index] = adjustment
        return adjustment

    _current_source_part_adjustments = lambda: _current_source_part_adjustments_helper(
        source_part_adjustments,
        is_default_adjustment=_is_default_source_part_adjustment,
    )

    def _set_source_role_override_value(source_index: int, role_value: str) -> str:
        part_glow_color_checkbox = _safe_call(_get_part_glow_color_checkbox)
        glow_color_checked = bool(part_glow_color_checkbox.isChecked()) if part_glow_color_checkbox is not None else False
        glow_rgb = _safe_call(_selected_part_glow_rgb_from_controls, default=()) or ()
        role_state = _source_part_role_override_state_helper(
            source_index=source_index,
            role_value=role_value,
            glow_color_checked=glow_color_checked,
            glow_rgb=glow_rgb,
        )
        if role_state.source_index < 0:
            return ""
        if role_state.store_override:
            source_role_overrides[role_state.source_index] = role_state.normalized_role
        else:
            source_role_overrides.pop(role_state.source_index, None)
        adjustment = _ensure_source_part_adjustment(role_state.source_index)
        adjustment.material_role = role_state.normalized_role
        adjustment.emissive_color_rgb = role_state.emissive_color_rgb
        if _is_default_source_part_adjustment(adjustment):
            source_part_adjustments.pop(role_state.source_index, None)
        _safe_call(_refresh_ui_texture_sets_after_source_part_material_override)
        texture_overrides_dirty["dirty"] = True
        return role_state.normalized_role

    _disabled_source_part_indices = lambda: _disabled_source_part_indices_helper(source_part_adjustments)
    _source_target_summary = lambda source_index: _source_target_summary_helper(
        source_index,
        mapping_edits,
        _original_mesh(),
    )
    _geometry_original_copy_text_by_index = lambda: _geometry_original_copy_text_by_index_helper(
        original_items_by_index
    )

    def _refresh_source_assignment_columns(*, lightweight: bool = False) -> None:
        if not _alignment_dialog_widgets_live():
            return
        assignment_index = _source_assignment_index_helper(mapping_edits, parse_mapping_edit=_parse_mapping_edit)
        for source_index, item in source_items_by_index.items():
            assigned_target_indices = tuple(assignment_index.get(int(source_index), ()))
            assigned_targets_text = (
                _format_index_list_helper(assigned_target_indices, display_name=_target_display_name)
                if assigned_target_indices
                else ""
            )
            source_state, _source_color = _source_outliner_state(source_index, assigned_target_indices)
            status_text, status_color = _source_tree_status_text(source_index, assigned_target_indices)
            row_state = _source_assignment_row_state_helper(
                source_index,
                assigned_target_indices,
                role_text=_source_role_label(source_index),
                assigned_targets_text=assigned_targets_text,
                source_state=source_state,
                status_text=status_text,
                status_color=status_color,
                copied_texture_tooltip=(
                    _safe_call(_copied_original_texture_tooltip, int(source_index), default="")
                    if int(source_index) in copied_original_texture_intents_by_source
                    else ""
                ),
            )
            item.setText(3, row_state.role_text)
            item.setText(4, row_state.assigned_targets_text)
            item.setText(5, row_state.status_text)
            item.setForeground(4, QBrush(QColor(row_state.assigned_targets_color)))
            item.setForeground(5, QBrush(QColor(row_state.status_color)))
            item.setToolTip(4, row_state.target_tooltip)
            item.setToolTip(5, row_state.status_tooltip)
        source_help_text = _source_index_help_text()
        for _target_index, edit in mapping_edits:
            edit.setToolTip(source_help_text)
        filter_refresh = texture_filter_refresh.get("func")
        selected_filter_checkbox = _safe_call(_get_texture_filter_selected_checkbox)
        if _selection_filter_refresh_needed_helper(
            has_filter_refresh=filter_refresh is not None,
            selected_filter_enabled=(
                selected_filter_checkbox is not None
                and selected_filter_checkbox.isChecked()
            ),
        ):
            filter_refresh()
        _safe_call(_refresh_parts_outliner)
        if lightweight:
            _safe_call(_refresh_geometry_summary)
            _safe_call(_refresh_output_impact_review)
            return
        _safe_call(_refresh_source_material_plan)
        _safe_call(_refresh_added_part_texture_tree)
        source_tree = _safe_call(_get_source_tree)
        source_tree_layout_state = _safe_call(_get_source_tree_layout_state)
        mapping_tree = _safe_call(_get_mapping_tree)
        if (
            callable(_auto_fit_alignment_tree_columns)
            and source_tree is not None
            and source_tree_layout_state is not None
            and mapping_tree is not None
        ):
            _auto_fit_alignment_tree_columns(
                source_tree,
                source_tree_layout_state.autofit_min_widths,
                source_tree_layout_state.autofit_max_widths,
                expand_columns=source_tree_layout_state.expand_columns,
            )
            _auto_fit_alignment_tree_columns(
                mapping_tree,
                (120, 70, 120, 150, 90, 90, 70),
                (240, 160, 220, 260, 160, 180, 130),
                expand_column=3,
            )
        _safe_call(_refresh_output_impact_review)
        _safe_call(_refresh_geometry_summary)

    def _geometry_mapping_text_by_target() -> Dict[int, str]:
        return _geometry_mapping_text_by_target_helper(
            mapping_edits,
            mappings_by_target=_safe_call(_get_mappings_by_target),
            original_mesh=_original_mesh(),
        )

    def _source_indices_for_target_name(target_name):
        return _source_indices_for_target_name_helper(
            target_name,
            mapping_edits,
            _original_mesh(),
        )

    return SimpleNamespace(
        _disabled_source_part_indices=_disabled_source_part_indices,
        _enabled_renderable_source_indices=_enabled_renderable_source_indices,
        _geometry_mapping_text_by_target=_geometry_mapping_text_by_target,
        _geometry_original_copy_text_by_index=_geometry_original_copy_text_by_index,
        _invalidate_source_display_cache=_invalidate_source_display_cache,
        _mapping_role_hint=_mapping_role_hint,
        _material_sidecar_patch_enabled=_material_sidecar_patch_enabled,
        _removed_target_dds_cell_text=_removed_target_dds_cell_text,
        _selected_source_summary=_selected_source_summary,
        _source_display_name=_source_display_name,
        _selection_context_texture_text=_selection_context_texture_text,
        _set_mesh_replacement_selection_view=_set_mesh_replacement_selection_view,
        _ensure_source_part_adjustment=_ensure_source_part_adjustment,
        _source_index_help_text=_source_index_help_text,
        _source_index_is_enabled_renderable=_source_index_is_enabled_renderable,
        _source_outliner_dds_text=_source_outliner_dds_text,
        _source_outliner_state=_source_outliner_state,
        _source_role_label=_source_role_label,
        _source_role_override_value=_source_role_override_value,
        _source_target_summary=_source_target_summary,
        _source_tree_status_text=_source_tree_status_text,
        _current_source_part_adjustments=_current_source_part_adjustments,
        _output_impact_counts=_output_impact_counts,
        _refresh_mesh_replacement_properties_inspector=_refresh_mesh_replacement_properties_inspector,
        _refresh_source_assignment_columns=_refresh_source_assignment_columns,
        _source_indices_for_target_name=_source_indices_for_target_name,
        _set_source_role_override_value=_set_source_role_override_value,
        _update_selection_context=_update_selection_context,
        _target_display_name=_target_display_name,
        _target_index_for_name=_target_index_for_name,
        _target_outliner_state=_target_outliner_state,
        mesh_replacement_selection_view_model=mesh_replacement_selection_view_model,
    )
