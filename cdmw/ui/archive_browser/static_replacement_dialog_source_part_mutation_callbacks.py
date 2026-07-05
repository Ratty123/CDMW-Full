"""Source-part mutation callback factory for static replacement dialog."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.ui.archive_browser.static_replacement_sparse_history import (
    allow_python_full_mesh_clone_fallback,
    clear_mesh_history_snapshot_stack,
    clone_mesh_for_static_replacement_native_first,
    release_native_submesh_snapshot,
    replace_mesh_history_snapshot_stack,
)


def create_alignment_source_part_mutation_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    List = context.get('List')
    Optional = context.get('Optional')
    Path = context.get('Path')
    QFileDialog = context.get('QFileDialog')
    QMessageBox = context.get('QMessageBox')
    SCENE_IMPORT_EXTENSIONS = context.get('SCENE_IMPORT_EXTENSIONS')
    Sequence = context.get('Sequence')
    StaticSourcePartAdjustment = context.get('StaticSourcePartAdjustment')
    _add_dialog_supplemental_file = context.get('_add_dialog_supplemental_file')
    _add_source_tree_item = context.get('_add_source_tree_item')
    _apply_source_material_texture_overrides_to_ui_texture_sets = context.get('_apply_source_material_texture_overrides_to_ui_texture_sets')
    _copy_source_part_with_adjustment = context.get('_copy_source_part_with_adjustment')
    _fit_alignment_tree_height_to_rows = context.get('_fit_alignment_tree_height_to_rows')
    _get_replacement_mesh_base_for_mapping = context.get('_get_replacement_mesh_base_for_mapping')
    _get_replacement_mesh_for_mapping = context.get('_get_replacement_mesh_for_mapping')
    _get_texture_sets = context.get('_get_texture_sets')
    _invalidate_source_display_cache = context.get('_invalidate_source_display_cache')
    _is_marker_source = context.get('_is_marker_source')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _mapping_role_hint = context.get('_mapping_role_hint')
    _maybe_flatten_scene_import_parts = context.get('_maybe_flatten_scene_import_parts')
    _maybe_reduce_high_density_scene_import = context.get('_maybe_reduce_high_density_scene_import')
    _normalize_appended_part_to_work_area = context.get('_normalize_appended_part_to_work_area')
    _parse_mapping_edit = context.get('_parse_mapping_edit')
    _pop_geometry_undo_snapshot = context.get('_pop_geometry_undo_snapshot')
    _prompt_assign_appended_mesh_parts = context.get('_prompt_assign_appended_mesh_parts')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _queue_static_preview_rebuild = context.get('_queue_static_preview_rebuild')
    _rebuild_source_part_widgets = context.get('_rebuild_source_part_widgets')
    _refresh_added_part_texture_tree = context.get('_refresh_added_part_texture_tree')
    _refresh_original_reference_preview = context.get('_refresh_original_reference_preview')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _refresh_source_material_plan = context.get('_refresh_source_material_plan')
    _refresh_source_tree_selection_state = context.get('_refresh_source_tree_selection_state')
    _refresh_texture_override_tree = context.get('_refresh_texture_override_tree')
    _refresh_texture_row_guidance = context.get('_refresh_texture_row_guidance')
    _refresh_texture_table = context.get('_refresh_texture_table')
    _remap_selected_source_index = context.get('_remap_selected_source_index')
    _remap_source_index_collection = context.get('_remap_source_index_collection')
    _remap_source_index_dict = context.get('_remap_source_index_dict')
    _remapped_original_copy_source_text_helper = context.get('_remapped_original_copy_source_text_helper')
    _rollback_cancelled_appended_mesh_part_import = context.get('_rollback_cancelled_appended_mesh_part_import')
    _selected_source_indices_from_tree = context.get('_selected_source_indices_from_tree')
    _semantic_tokens = context.get('_semantic_tokens')
    _set_mapping_indices = context.get('_set_mapping_indices')
    _set_replacement_mesh_base_for_mapping = context.get('_set_replacement_mesh_base_for_mapping')
    _set_replacement_mesh_for_mapping = context.get('_set_replacement_mesh_for_mapping')
    _set_replacement_preview_model = context.get('_set_replacement_preview_model')
    _set_source_parts_apply_pending = context.get('_set_source_parts_apply_pending')
    _set_source_parts_preview_rebuild_pending = context.get('_set_source_parts_preview_rebuild_pending')
    _set_texture_sets = context.get('_set_texture_sets')
    _set_transform_source_indices = context.get('_set_transform_source_indices')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')
    _mesh_edit_preview_source_indices = context.get('_mesh_edit_preview_source_indices')
    _mesh_edit_replace_live_triangles_or_queue_rebuild = context.get('_mesh_edit_replace_live_triangles_or_queue_rebuild')
    _source_display_name = context.get('_source_display_name')
    _source_group_label_or_fallback_helper = context.get('_source_group_label_or_fallback_helper')
    _source_mapping_target_indices = context.get('_source_mapping_target_indices')
    _source_material_group_label = context.get('_source_material_group_label')
    _source_part_add_mesh_part_failed_title_helper = context.get('_source_part_add_mesh_part_failed_title_helper')
    _source_part_added_mesh_part_status_helper = context.get('_source_part_added_mesh_part_status_helper')
    _source_part_append_file_route_state_helper = context.get('_source_part_append_file_route_state_helper')
    _source_part_append_imported_state_helper = context.get('_source_part_append_imported_state_helper')
    _source_part_append_mesh_file_dialog_text_helper = context.get('_source_part_append_mesh_file_dialog_text_helper')
    _source_part_append_rollback_snapshot_helper = context.get('_source_part_append_rollback_snapshot_helper')
    _source_part_append_texture_control_state_helper = context.get('_source_part_append_texture_control_state_helper')
    _source_part_assign_material_groups_to_targets_helper = context.get('_source_part_assign_material_groups_to_targets_helper')
    _source_part_cancel_import_status_helper = context.get('_source_part_cancel_import_status_helper')
    _source_part_delete_index_map_state_helper = context.get('_source_part_delete_index_map_state_helper')
    _source_part_delete_selection_state_helper = context.get('_source_part_delete_selection_state_helper')
    _source_part_delete_status_text_helper = context.get('_source_part_delete_status_text_helper')
    _source_part_deleted_pending_reason_helper = context.get('_source_part_deleted_pending_reason_helper')
    _source_part_deleted_status_helper = context.get('_source_part_deleted_status_helper')
    _source_part_display_label_helper = context.get('_source_part_display_label_helper')
    _source_part_duplicate_presentation_state_helper = context.get('_source_part_duplicate_presentation_state_helper')
    _source_part_duplicate_route_state_helper = context.get('_source_part_duplicate_route_state_helper')
    _source_part_group_initial_target_counts_helper = context.get('_source_part_group_initial_target_counts_helper')
    _source_part_group_items_helper = context.get('_source_part_group_items_helper')
    _source_part_group_routing_overflow_message_helper = context.get('_source_part_group_routing_overflow_message_helper')
    _source_part_group_routing_text_helper = context.get('_source_part_group_routing_text_helper')
    _source_part_mapping_indices_for_target_helper = context.get('_source_part_mapping_indices_for_target_helper')
    _source_part_material_groups_helper = context.get('_source_part_material_groups_helper')
    _source_part_unsupported_mesh_part_message_helper = context.get('_source_part_unsupported_mesh_part_message_helper')
    _source_role_label = context.get('_source_role_label')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _target_submesh_display_name_helper = context.get('_target_submesh_display_name_helper')
    _texture_set_for_source_index = context.get('_texture_set_for_source_index')
    _update_mapping_status = context.get('_update_mapping_status')
    _update_selection_context = context.get('_update_selection_context')
    adjustment = context.get('adjustment')
    append_file_route = context.get('append_file_route')
    append_imported_state = context.get('append_imported_state')
    append_result = context.get('append_result')
    append_rollback_snapshot = context.get('append_rollback_snapshot')
    append_scene_import_to_mesh = context.get('append_scene_import_to_mesh')
    append_scene_result = context.get('append_scene_result')
    append_texture_control_state = context.get('append_texture_control_state')
    append_undo_pushed = context.get('append_undo_pushed')
    appended_source_indices = context.get('appended_source_indices')
    appended_texture_sets = context.get('appended_texture_sets')
    assignment_action = context.get('assignment_action')
    baked_source = context.get('baked_source')
    base_copy = context.get('base_copy')
    base_submeshes = context.get('base_submeshes')
    clear_response = context.get('clear_response')
    copied_original_physics_sensitive_sources = context.get('copied_original_physics_sensitive_sources')
    copied_original_source_indices = context.get('copied_original_source_indices')
    copied_original_source_to_original_index = context.get('copied_original_source_to_original_index')
    copied_original_texture_disabled_sources = context.get('copied_original_texture_disabled_sources')
    copied_original_texture_intents_by_source = context.get('copied_original_texture_intents_by_source')
    copy = context.get('copy')
    delete_index_map_state = context.get('delete_index_map_state')
    delete_indices = context.get('delete_indices')
    delete_selection_state = context.get('delete_selection_state')
    deltas = context.get('deltas')
    dialog = context.get('dialog')
    dialog_added_supplemental_files = context.get('dialog_added_supplemental_files')
    duplicate_presentation = context.get('duplicate_presentation')
    duplicate_route = context.get('duplicate_route')
    edit = context.get('edit')
    exc = context.get('exc')
    group_replacement_texture_sets = context.get('group_replacement_texture_sets')
    import_scene_mesh_with_report = context.get('import_scene_mesh_with_report')
    independent_output_source_indices = context.get('independent_output_source_indices')
    index = context.get('index')
    index_map = context.get('index_map')
    inject_base_color_checkbox = context.get('inject_base_color_checkbox')
    item = context.get('item')
    kept_submeshes = context.get('kept_submeshes')
    mapped_targets = context.get('mapped_targets')
    mapping_edits = context.get('mapping_edits')
    mapping_edits_by_target = context.get('mapping_edits_by_target')
    marker_source_indices = context.get('marker_source_indices')
    mesh_edit_redo_adjustment_stack = context.get('mesh_edit_redo_adjustment_stack')
    mesh_edit_redo_stack = context.get('mesh_edit_redo_stack')
    mesh_edit_selected_faces_by_submesh = context.get('mesh_edit_selected_faces_by_submesh')
    mesh_edit_selected_source_indices = context.get('mesh_edit_selected_source_indices')
    mesh_edit_selected_vertices_by_submesh = context.get('mesh_edit_selected_vertices_by_submesh')
    mesh_edit_undo_adjustment_stack = context.get('mesh_edit_undo_adjustment_stack')
    mesh_edit_undo_stack = context.get('mesh_edit_undo_stack')
    mirrored = context.get('mirrored')
    morph_slider_post_edit_deltas = context.get('morph_slider_post_edit_deltas')
    new_adjustment = context.get('new_adjustment')
    new_current_index = context.get('new_current_index')
    new_index = context.get('new_index')
    new_item = context.get('new_item')
    old_index = context.get('old_index')
    original_item = context.get('original_item')
    original_items_by_index = context.get('original_items_by_index')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    overflow_groups = context.get('overflow_groups')
    parsed_mesh_to_preview_model = context.get('parsed_mesh_to_preview_model')
    part_source_combo = context.get('part_source_combo')
    placement_note = context.get('placement_note')
    plane_x = context.get('plane_x')
    presentation = context.get('presentation')
    preview_only_source_indices = context.get('preview_only_source_indices')
    rebuild_reason = context.get('rebuild_reason')
    rebuild_sidecar_checkbox = context.get('rebuild_sidecar_checkbox')
    refresh_parsed_mesh_totals = context.get('refresh_parsed_mesh_totals')
    remapped = context.get('remapped')
    remapped_adjustment = context.get('remapped_adjustment')
    remapped_adjustments = context.get('remapped_adjustments')
    remapped_copied_original_source_to_original_index = context.get('remapped_copied_original_source_to_original_index')
    remapped_copied_original_texture_intents = context.get('remapped_copied_original_texture_intents')
    remapped_indices = context.get('remapped_indices')
    remapped_source_display_overrides = context.get('remapped_source_display_overrides')
    remapped_source_role_overrides = context.get('remapped_source_role_overrides')
    replacement_mesh_base_for_mapping = context.get('replacement_mesh_base_for_mapping')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    selected_added_part_texture_row = context.get('selected_added_part_texture_row')
    selected_indices = context.get('selected_indices')
    selected_original_highlight_indices = context.get('selected_original_highlight_indices')
    selected_original_part = context.get('selected_original_part')
    selected_path = context.get('selected_path')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    selected_target_original_highlight_indices = context.get('selected_target_original_highlight_indices')
    selected_target_slot = context.get('selected_target_slot')
    selected_target_source_highlight_indices = context.get('selected_target_source_highlight_indices')
    selected_texture_plan_source = context.get('selected_texture_plan_source')
    selected_texture_row = context.get('selected_texture_row')
    self = context.get('self')
    source = context.get('source')
    source_adjustment = context.get('source_adjustment')
    source_count = context.get('source_count')
    source_display_overrides = context.get('source_display_overrides')
    source_face_counts = context.get('source_face_counts')
    source_geometry_revision = context.get('source_geometry_revision')
    source_groups = context.get('source_groups')
    source_index = context.get('source_index')
    source_indices = context.get('source_indices')
    source_initial_targets = context.get('source_initial_targets')
    source_items_by_index = context.get('source_items_by_index')
    source_label = context.get('source_label')
    source_material_texture_override_assignments = context.get('source_material_texture_override_assignments')
    source_part_adjustments = context.get('source_part_adjustments')
    source_part_append_mesh_file_dialog_text = context.get('source_part_append_mesh_file_dialog_text')
    source_part_delete_status_text = context.get('source_part_delete_status_text')
    source_part_group_routing_text = context.get('source_part_group_routing_text')
    source_parts_apply_state = context.get('source_parts_apply_state')
    source_path = context.get('source_path')
    source_role_overrides = context.get('source_role_overrides')
    source_tree = context.get('source_tree')
    source_tree_layout_state = context.get('source_tree_layout_state')
    static_preview_baked_transform_state = context.get('static_preview_baked_transform_state')
    static_preview_geometry_cache = context.get('static_preview_geometry_cache')
    static_preview_prepared_cache = context.get('static_preview_prepared_cache')
    submesh = context.get('submesh')
    suggested_mappings = context.get('suggested_mappings')
    supplemental_path = context.get('supplemental_path')
    target_count = context.get('target_count')
    target_index = context.get('target_index')
    target_set = context.get('target_set')
    target_sources = context.get('target_sources')
    texture_files_for_mapping = context.get('texture_files_for_mapping')
    texture_override_assignments = context.get('texture_override_assignments')
    texture_overrides_dirty = context.get('texture_overrides_dirty')
    texture_sets = context.get('texture_sets')
    transform_source_indices = context.get('transform_source_indices')
    value = context.get('value')
    working_copy = context.get('working_copy')

    def _source_part_current_preview_indices() -> object:
        if callable(_mesh_edit_preview_source_indices):
            return _mesh_edit_preview_source_indices()
        mesh = _get_replacement_mesh_for_mapping()
        return range(len(getattr(mesh, "submeshes", ()) or ())) if mesh is not None else ()

    def _source_part_mesh_edit_active() -> bool:
        if not callable(_alignment_mesh_edit_tab_active):
            return False
        return bool(_alignment_mesh_edit_tab_active())

    def _source_part_refresh_geometry_preview(
        reason: str,
        source_indices: object | None = None,
        *,
        replace_all: bool = False,
    ) -> None:
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        texture_overrides_dirty["dirty"] = True
        if callable(_alignment_d3d11_preview_active) and _alignment_d3d11_preview_active():
            if callable(_mesh_edit_replace_live_triangles_or_queue_rebuild):
                _mesh_edit_replace_live_triangles_or_queue_rebuild(
                    source_indices if source_indices is not None else _source_part_current_preview_indices(),
                    replace_all=replace_all,
                )
                return
            self.set_status_message(
                "Native D3D11 source-part preview commands are unavailable; preview is stale. Reload D3D11 preview to resync.",
                error=True,
            )
            return
        if _source_part_mesh_edit_active():
            self.set_status_message(
                "Active Mesh Editor source-part preview requires native D3D11 refresh; Python preview rebuild fallback is disabled.",
                error=True,
            )
            return
        replacement_mesh_for_mapping = _get_replacement_mesh_for_mapping()
        _set_replacement_preview_model(
            parsed_mesh_to_preview_model(replacement_mesh_for_mapping)
            if replacement_mesh_for_mapping is not None
            else None
        )
        _set_source_parts_preview_rebuild_pending(reason)
        _queue_static_preview_rebuild()

    def _source_part_active_geometry_mutation_blocked() -> bool:
        if not _source_part_mesh_edit_active():
            return False
        self.set_status_message(
            "Active Mesh Editor source-part topology changes require native geometry execution; Python mesh mutation fallback is disabled.",
            error=True,
        )
        return True

    def _source_part_material_routing_mutation_blocked() -> bool:
        if not _source_part_mesh_edit_active():
            return False
        self.set_status_message(
            "Active Mesh Editor source-part material routing requires native material execution; Python routing mutation fallback is disabled.",
            error=True,
        )
        return True

    def _source_part_append_capture_mesh_snapshot(mesh: object, operation: str) -> object | None:
        if mesh is None:
            return None
        try:
            from cdmw.modding.mesh_native_core import snapshot_native_mesh_submeshes

            native_snapshot = snapshot_native_mesh_submeshes(mesh)
        except Exception:
            native_snapshot = None
        if native_snapshot is not None:
            return native_snapshot
        def _fallback_allowed(candidate: object) -> bool:
            if allow_python_full_mesh_clone_fallback(
                candidate,
                operation,
                "Python source-part append rollback clone fallback blocked while native mesh core is available",
            ):
                return True
            self.set_status_message(
                "Native source-part append rollback snapshot failed; Python full-mesh clone fallback blocked while native mesh core is available.",
                error=True,
            )
            return False

        return clone_mesh_for_static_replacement_native_first(
            mesh,
            operation,
            "Python source-part append rollback clone fallback blocked while native mesh core is available",
            fallback_allowed=_fallback_allowed,
        )

    def _source_part_append_restore_mesh_snapshot(snapshot: object) -> object | None:
        if isinstance(snapshot, Mapping) and snapshot.get("kind") == "native_submesh_snapshot":
            try:
                from cdmw.modding.mesh_native_core import restore_native_mesh_submesh_snapshot

                restored = ParsedMesh()
                if restore_native_mesh_submesh_snapshot(restored, snapshot):
                    return restored
            except Exception:
                return None
            return None
        if isinstance(snapshot, ParsedMesh):
            return _source_part_append_clone_parsed_mesh_snapshot(snapshot)
        return None

    def _source_part_append_clone_parsed_mesh_snapshot(snapshot: ParsedMesh) -> ParsedMesh | None:
        def _fallback_allowed(candidate: object) -> bool:
            if allow_python_full_mesh_clone_fallback(
                candidate,
                "source_part.append_rollback_restore",
                "Python source-part append rollback restore clone fallback blocked while native mesh core is available",
            ):
                return True
            self.set_status_message(
                "Native source-part append rollback restore failed; Python full-mesh clone fallback blocked while native mesh core is available.",
                error=True,
            )
            return False

        restored = clone_mesh_for_static_replacement_native_first(
            snapshot,
            "source_part.append_rollback_restore",
            "Python source-part append rollback restore clone fallback blocked while native mesh core is available",
            fallback_allowed=_fallback_allowed,
        )
        return restored if isinstance(restored, ParsedMesh) else None

    def _source_part_append_release_rollback_snapshots(snapshot: object) -> None:
        release_native_submesh_snapshot(getattr(snapshot, "replacement_mesh", None))
        release_native_submesh_snapshot(getattr(snapshot, "replacement_base_mesh", None))

    def _delete_selected_source_parts(source_indices: Optional[Sequence[int]] = None) -> None:
        replacement_mesh_for_mapping = _get_replacement_mesh_for_mapping()
        replacement_mesh_base_for_mapping = _get_replacement_mesh_base_for_mapping()
        if replacement_mesh_for_mapping is None:
            return
        if source_indices is None or isinstance(source_indices, bool):
            selected_indices = _selected_source_indices_from_tree()
        else:
            selected_indices = list(source_indices)
        source_count = len(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ())
        marker_source_indices = tuple(
            index
            for index, source in enumerate(tuple(replacement_mesh_for_mapping.submeshes or ()))
            if _is_marker_source(source)
        )
        delete_selection_state = _source_part_delete_selection_state_helper(
            selected_indices,
            source_count=source_count,
            marker_source_indices=marker_source_indices,
        )
        source_part_delete_status_text = _source_part_delete_status_text_helper()
        if not delete_selection_state.available:
            self.set_status_message(source_part_delete_status_text[delete_selection_state.status_key])
            return
        if _source_part_active_geometry_mutation_blocked():
            return
        delete_indices = set(delete_selection_state.delete_indices)
        _push_geometry_undo_snapshot(source_part_delete_status_text["undo_label"])
        delete_index_map_state = _source_part_delete_index_map_state_helper(
            source_count=source_count,
            delete_indices=tuple(delete_indices),
        )
        index_map = delete_index_map_state.index_map
        kept_submeshes = [
            submesh
            for old_index, submesh in enumerate(tuple(replacement_mesh_for_mapping.submeshes or ()))
            if old_index in delete_index_map_state.kept_indices
        ]
        replacement_mesh_for_mapping.submeshes[:] = kept_submeshes
        if replacement_mesh_base_for_mapping is not None:
            base_submeshes = tuple(getattr(replacement_mesh_base_for_mapping, "submeshes", ()) or ())
            if len(base_submeshes) == source_count:
                replacement_mesh_base_for_mapping.submeshes[:] = [
                    submesh for old_index, submesh in enumerate(base_submeshes)
                    if old_index in delete_index_map_state.kept_indices
                ]
                refresh_parsed_mesh_totals(replacement_mesh_base_for_mapping)
        refresh_parsed_mesh_totals(replacement_mesh_for_mapping)
        source_geometry_revision["value"] = int(source_geometry_revision.get("value", 0) or 0) + 1

        remapped_adjustments: Dict[int, StaticSourcePartAdjustment] = {}
        for old_index, adjustment in source_part_adjustments.items():
            new_index = index_map.get(int(old_index))
            if new_index is None:
                continue
            remapped_adjustment = copy.deepcopy(adjustment)
            remapped_adjustment.source_submesh_index = int(new_index)
            remapped_adjustments[int(new_index)] = remapped_adjustment
        source_part_adjustments.clear()
        source_part_adjustments.update(remapped_adjustments)

        remapped_source_role_overrides = {
            int(new_index): str(value)
            for new_index, value in _remap_source_index_dict(source_role_overrides, index_map).items()
        }
        remapped_source_display_overrides = {
            int(new_index): str(value)
            for new_index, value in _remap_source_index_dict(source_display_overrides, index_map).items()
        }
        source_role_overrides.clear()
        source_role_overrides.update(remapped_source_role_overrides)
        source_display_overrides.clear()
        source_display_overrides.update(remapped_source_display_overrides)
        _invalidate_source_display_cache()

        for target_set in (
            appended_source_indices,
            independent_output_source_indices,
            preview_only_source_indices,
            copied_original_source_indices,
            copied_original_texture_disabled_sources,
            copied_original_physics_sensitive_sources,
            selected_source_highlight_indices,
            selected_target_source_highlight_indices,
            transform_source_indices,
        ):
            remapped = _remap_source_index_collection(target_set, index_map)
            target_set.clear()
            target_set.update(remapped)

        remapped_copied_original_source_to_original_index = {
            int(new_index): int(value)
            for new_index, value in _remap_source_index_dict(
                copied_original_source_to_original_index,
                index_map,
            ).items()
        }
        remapped_copied_original_texture_intents = {
            int(new_index): list(value)
            for new_index, value in _remap_source_index_dict(
                copied_original_texture_intents_by_source,
                index_map,
                copy_values=True,
            ).items()
            if isinstance(value, list)
        }
        copied_original_source_to_original_index.clear()
        copied_original_source_to_original_index.update(remapped_copied_original_source_to_original_index)
        copied_original_texture_intents_by_source.clear()
        copied_original_texture_intents_by_source.update(remapped_copied_original_texture_intents)
        selected_source_part["index"] = _remap_selected_source_index(
            int(selected_source_part.get("index", -1)),
            index_map,
        )
        for original_item in original_items_by_index.values():
            original_item.setText(4, _remapped_original_copy_source_text_helper(original_item.text(4), index_map))
        if isinstance(static_preview_baked_transform_state.get("parts"), dict):
            static_preview_baked_transform_state["parts"] = _remap_source_index_dict(
                static_preview_baked_transform_state.get("parts", {}),
                index_map,
                copy_values=True,
        )
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        if hasattr(mesh_edit_selected_source_indices, "clear"):
            mesh_edit_selected_source_indices.clear()
        if morph_slider_post_edit_deltas and len(morph_slider_post_edit_deltas) == source_count:
            morph_slider_post_edit_deltas[:] = [
                deltas
                for old_index, deltas in enumerate(morph_slider_post_edit_deltas)
                if old_index not in delete_indices
            ]
        new_current_index = int(selected_source_part.get("index", -1))
        _rebuild_source_part_widgets(
            (new_current_index,) if new_current_index >= 0 else (),
            current_index=new_current_index,
        )
        for target_index, edit in tuple(mapping_edits):
            remapped_indices: List[int] = []
            for old_index in _parse_mapping_edit(edit):
                new_index = index_map.get(int(old_index))
                if new_index is not None and int(new_index) not in remapped_indices:
                    remapped_indices.append(int(new_index))
            _set_mapping_indices(
                int(target_index),
                remapped_indices,
                push_undo=False,
                undo_label=source_part_delete_status_text["undo_label"],
                defer_preview=True,
            )
        clear_mesh_history_snapshot_stack(mesh_edit_undo_stack)
        clear_mesh_history_snapshot_stack(mesh_edit_redo_stack)
        mesh_edit_undo_adjustment_stack.clear()
        mesh_edit_redo_adjustment_stack.clear()
        texture_sets = group_replacement_texture_sets(texture_files_for_mapping, obj_mesh=replacement_mesh_for_mapping)
        _set_texture_sets(texture_sets)
        _apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
        try:
            selected_added_part_texture_row["source_index"] = _remap_selected_source_index(
                int(selected_added_part_texture_row.get("source_index", -1)),
                index_map,
            )
        except NameError:
            pass
        try:
            selected_texture_plan_source["source_indices"] = tuple(
                sorted(_remap_source_index_collection(selected_texture_plan_source.get("source_indices", ()), index_map))
            )
        except NameError:
            pass
        _refresh_source_assignment_columns()
        try:
            _refresh_texture_row_guidance()
            _refresh_texture_table(selected_texture_row.get("row"))
        except NameError:
            pass
        try:
            _refresh_added_part_texture_tree(new_current_index if new_current_index >= 0 else None)
        except NameError:
            pass
        try:
            _refresh_source_material_plan(force=True)
        except NameError:
            pass
        _load_selected_part_controls()
        _sync_highlight_sets()
        _source_part_refresh_geometry_preview(
            _source_part_deleted_pending_reason_helper(len(delete_indices)),
            replace_all=True,
        )
        self.set_status_message(_source_part_deleted_status_helper(len(delete_indices)))

    def _apply_source_part_preview_changes() -> None:
        rebuild_reason = str(
            source_parts_apply_state.get("reason", "") or "source-part changes"
        )
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        texture_overrides_dirty["dirty"] = True
        _refresh_source_assignment_columns()
        _update_mapping_status()
        _update_selection_context()
        _source_part_refresh_geometry_preview(rebuild_reason, replace_all=True)

    def _apply_source_material_grouped_routing() -> None:
        if _source_part_material_routing_mutation_blocked():
            return
        replacement_mesh_for_mapping = _get_replacement_mesh_for_mapping()
        texture_sets = _get_texture_sets()
        if original_mesh_for_mapping is None or replacement_mesh_for_mapping is None:
            return
        try:
            texture_sets = group_replacement_texture_sets(
                texture_files_for_mapping,
                obj_mesh=replacement_mesh_for_mapping,
            )
            _set_texture_sets(texture_sets)
            _apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
        except NameError:
            texture_sets = {}
            _set_texture_sets(texture_sets)
        source_initial_targets = _source_part_group_initial_target_counts_helper(
            suggested_mappings,
            lambda source_index: _source_material_group_label(int(source_index), texture_sets),
        )
        source_groups, source_face_counts = _source_part_material_groups_helper(
            replacement_mesh_for_mapping,
            source_part_adjustments,
            source_material_group_label=lambda source_index: _source_material_group_label(
                int(source_index),
                texture_sets,
            ),
            source_group_label_or_fallback=_source_group_label_or_fallback_helper,
            is_marker_source=_is_marker_source,
        )
        if not source_groups:
            source_part_group_routing_text = _source_part_group_routing_text_helper()
            QMessageBox.information(
                dialog,
                source_part_group_routing_text["no_source_title"],
                source_part_group_routing_text["no_source_message"],
            )
            return
        target_count = len(original_mesh_for_mapping.submeshes)
        if target_count <= 0:
            source_part_group_routing_text = _source_part_group_routing_text_helper()
            QMessageBox.information(
                dialog,
                source_part_group_routing_text["no_target_title"],
                source_part_group_routing_text["no_target_message"],
            )
            return
        source_part_group_routing_text = _source_part_group_routing_text_helper()
        _push_geometry_undo_snapshot(source_part_group_routing_text["undo_label"])
        if any(str(value or "").strip() for value in texture_override_assignments.values()):
            clear_response = QMessageBox.question(
                dialog,
                source_part_group_routing_text["clear_manual_title"],
                source_part_group_routing_text["clear_manual_message"],
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if clear_response == QMessageBox.Yes:
                texture_override_assignments.clear()
                try:
                    _refresh_texture_override_tree()
                except NameError:
                    pass
        target_sources, overflow_groups = _source_part_assign_material_groups_to_targets_helper(
            _source_part_group_items_helper(source_groups, source_face_counts),
            target_count=target_count,
            original_mesh=original_mesh_for_mapping,
            replacement_mesh=replacement_mesh_for_mapping,
            target_display_name=_target_submesh_display_name_helper,
            source_initial_targets=source_initial_targets,
            semantic_tokens=_semantic_tokens,
        )

        for target_index, source_indices in target_sources.items():
            _set_mapping_indices(target_index, source_indices, push_undo=False)
        try:
            if texture_sets and not rebuild_sidecar_checkbox.isChecked():
                rebuild_sidecar_checkbox.setChecked(True)
        except NameError:
            pass
        try:
            _refresh_source_material_plan()
        except NameError:
            pass
        if overflow_groups:
            source_part_group_routing_text = _source_part_group_routing_text_helper()
            QMessageBox.warning(
                dialog,
                source_part_group_routing_text["overflow_title"],
                _source_part_group_routing_overflow_message_helper(overflow_groups),
            )

    def _duplicate_selected_part(*, mirrored: bool = False) -> None:
        replacement_mesh_for_mapping = _get_replacement_mesh_for_mapping()
        replacement_mesh_base_for_mapping = _get_replacement_mesh_base_for_mapping()
        source_index = int(selected_source_part.get("index", -1))
        if replacement_mesh_for_mapping is None or replacement_mesh_base_for_mapping is None:
            return
        mapped_targets = _source_mapping_target_indices(source_index)
        duplicate_route = _source_part_duplicate_route_state_helper(
            mirrored=mirrored,
            source_index=source_index,
            source_count=len(replacement_mesh_for_mapping.submeshes),
            has_base_mesh=replacement_mesh_base_for_mapping is not None,
            new_index=len(replacement_mesh_for_mapping.submeshes),
            mapped_target_indices=mapped_targets,
            independent_output_source_indices=independent_output_source_indices,
            preview_only_source_indices=preview_only_source_indices,
        )
        if not duplicate_route.available:
            return
        if _source_part_active_geometry_mutation_blocked():
            return
        _push_geometry_undo_snapshot(duplicate_route.undo_label)
        source = replacement_mesh_for_mapping.submeshes[source_index]
        source_adjustment = source_part_adjustments.get(
            source_index,
            StaticSourcePartAdjustment(source_index),
        )
        if mirrored:
            working_copy = _copy_source_part_with_adjustment(
                source,
                source_adjustment,
                mirror_x_around_bounds_center=True,
            )
            base_copy = _copy_source_part_with_adjustment(
                working_copy,
                StaticSourcePartAdjustment(source_submesh_index=0),
            )
            new_adjustment = StaticSourcePartAdjustment(source_submesh_index=0)
        else:
            working_copy = _copy_source_part_with_adjustment(
                source,
                StaticSourcePartAdjustment(source_submesh_index=source_index),
            )
            base_source = (
                replacement_mesh_base_for_mapping.submeshes[source_index]
                if source_index < len(replacement_mesh_base_for_mapping.submeshes)
                else source
            )
            base_copy = _copy_source_part_with_adjustment(
                base_source,
                StaticSourcePartAdjustment(source_submesh_index=source_index),
            )
            new_adjustment = copy.deepcopy(source_adjustment)

        new_index = duplicate_route.new_index
        new_adjustment.source_submesh_index = new_index
        new_adjustment.enabled = True
        replacement_mesh_for_mapping.submeshes.append(working_copy)
        replacement_mesh_base_for_mapping.submeshes.append(base_copy)
        refresh_parsed_mesh_totals(replacement_mesh_for_mapping)
        refresh_parsed_mesh_totals(replacement_mesh_base_for_mapping)

        source_part_adjustments[new_index] = new_adjustment
        appended_source_indices.add(new_index)
        source_label = _source_part_display_label_helper(source_index, source, source_display_overrides)
        duplicate_presentation = _source_part_duplicate_presentation_state_helper(
            existing_role=source_role_overrides.get(source_index, ""),
            fallback_role=_source_role_label(source_index),
            source_label=source_label,
            copy_suffix=duplicate_route.copy_suffix,
        )
        source_role_overrides[new_index] = duplicate_presentation.role_override
        source_display_overrides[new_index] = duplicate_presentation.display_override
        _invalidate_source_display_cache()

        if duplicate_route.output_route == "independent":
            independent_output_source_indices.add(new_index)
        elif duplicate_route.output_route == "preview":
            preview_only_source_indices.add(new_index)

        _add_source_tree_item(new_index, working_copy)
        part_source_combo.addItem(_source_display_name(new_index), new_index)
        source_tree.clearSelection()
        new_item = source_items_by_index.get(new_index)
        if new_item is not None:
            new_item.setSelected(True)
            source_tree.setCurrentItem(new_item)
        selected_source_part["index"] = new_index
        selected_source_highlight_indices.clear()
        selected_source_highlight_indices.add(new_index)
        _set_transform_source_indices((new_index,))
        for target_index in mapped_targets:
            edit = mapping_edits_by_target.get(target_index)
            if edit is None:
                continue
            _set_mapping_indices(
                target_index,
                list(
                    _source_part_mapping_indices_for_target_helper(
                        _parse_mapping_edit(edit),
                        source_index=new_index,
                        replace=False,
                    )
                ),
                push_undo=False,
            )

        source_geometry_revision["value"] = int(source_geometry_revision.get("value", 0) or 0) + 1
        clear_mesh_history_snapshot_stack(mesh_edit_redo_stack)
        mesh_edit_redo_adjustment_stack.clear()
        texture_sets = group_replacement_texture_sets(texture_files_for_mapping, obj_mesh=replacement_mesh_for_mapping)
        _set_texture_sets(texture_sets)
        _apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
        _fit_alignment_tree_height_to_rows(source_tree, **source_tree_layout_state.height_fit_kwargs)
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        try:
            _refresh_added_part_texture_tree(new_index)
        except NameError:
            pass
        try:
            _refresh_source_material_plan()
        except NameError:
            pass
        try:
            _refresh_texture_row_guidance()
            _refresh_texture_table(selected_texture_row.get("row"))
        except NameError:
            pass
        _load_selected_part_controls()
        _source_part_refresh_geometry_preview(duplicate_route.status_text, (new_index,))
        self.set_status_message(duplicate_route.status_text)

    def _append_mesh_part_to_geometry() -> None:
        replacement_mesh_for_mapping = _get_replacement_mesh_for_mapping()
        replacement_mesh_base_for_mapping = _get_replacement_mesh_base_for_mapping()
        if replacement_mesh_for_mapping is None or replacement_mesh_base_for_mapping is None:
            return
        if _source_part_active_geometry_mutation_blocked():
            return
        source_part_append_mesh_file_dialog_text = _source_part_append_mesh_file_dialog_text_helper()
        selected_path, _selected_filter = QFileDialog.getOpenFileName(
            dialog,
            source_part_append_mesh_file_dialog_text["title"],
            str(self._suggest_workspace_base_dir()),
            source_part_append_mesh_file_dialog_text["mesh_filter"],
        )
        if not selected_path:
            return
        source_path = Path(selected_path).expanduser()
        append_file_route = _source_part_append_file_route_state_helper(
            source_path,
            allowed_extensions=SCENE_IMPORT_EXTENSIONS,
        )
        if append_file_route.route == "fbx_deferred":
            QMessageBox.information(
                dialog,
                source_part_append_mesh_file_dialog_text["fbx_title"],
                source_part_append_mesh_file_dialog_text["fbx_message"],
            )
            return
        if append_file_route.route == "unsupported":
            QMessageBox.warning(
                dialog,
                source_part_append_mesh_file_dialog_text["unsupported_title"],
                _source_part_unsupported_mesh_part_message_helper(source_path.name),
            )
            return
        rollback_replacement_mesh = _source_part_append_capture_mesh_snapshot(
            replacement_mesh_for_mapping,
            "source_part.append_rollback_working_mesh",
        )
        rollback_replacement_base_mesh = _source_part_append_capture_mesh_snapshot(
            replacement_mesh_base_for_mapping,
            "source_part.append_rollback_base_mesh",
        )
        if rollback_replacement_mesh is None or rollback_replacement_base_mesh is None:
            release_native_submesh_snapshot(rollback_replacement_mesh)
            release_native_submesh_snapshot(rollback_replacement_base_mesh)
            return
        append_rollback_snapshot = _source_part_append_rollback_snapshot_helper(
            replacement_mesh=rollback_replacement_mesh,
            replacement_base_mesh=rollback_replacement_base_mesh,
            appended_source_indices=appended_source_indices,
            independent_output_source_indices=independent_output_source_indices,
            preview_only_source_indices=preview_only_source_indices,
            source_role_overrides=source_role_overrides,
            source_display_overrides=source_display_overrides,
            source_part_adjustments=source_part_adjustments,
            dialog_added_supplemental_files=dialog_added_supplemental_files,
            texture_files_for_mapping=texture_files_for_mapping,
            source_material_texture_override_assignments=source_material_texture_override_assignments,
            mesh_edit_redo_stack=mesh_edit_redo_stack,
            mesh_edit_redo_adjustment_stack=mesh_edit_redo_adjustment_stack,
            source_geometry_revision=source_geometry_revision.get("value", 0),
            selected_source_index=selected_source_part.get("index", -1),
            selected_source_indices=_selected_source_indices_from_tree(),
            selected_target_index=selected_target_slot.get("index", -1),
            selected_original_index=selected_original_part.get("index", -1),
            selected_source_highlights=selected_source_highlight_indices,
            selected_target_source_highlights=selected_target_source_highlight_indices,
            transform_source_indices=transform_source_indices,
            selected_original_highlights=selected_original_highlight_indices,
            selected_target_original_highlights=selected_target_original_highlight_indices,
        )

        def _rollback_cancelled_appended_mesh_part_import() -> bool:
            replacement_mesh_for_mapping = _source_part_append_restore_mesh_snapshot(
                append_rollback_snapshot.replacement_mesh
            )
            replacement_mesh_base_for_mapping = _source_part_append_restore_mesh_snapshot(
                append_rollback_snapshot.replacement_base_mesh
            )
            if replacement_mesh_for_mapping is None or replacement_mesh_base_for_mapping is None:
                self.set_status_message(
                    "Could not restore source-part append rollback snapshot; reload the preview before continuing.",
                    error=True,
                )
                return False
            _set_replacement_mesh_for_mapping(replacement_mesh_for_mapping)
            _set_replacement_mesh_base_for_mapping(replacement_mesh_base_for_mapping)
            appended_source_indices.clear()
            appended_source_indices.update(append_rollback_snapshot.appended_source_indices)
            independent_output_source_indices.clear()
            independent_output_source_indices.update(append_rollback_snapshot.independent_output_source_indices)
            preview_only_source_indices.clear()
            preview_only_source_indices.update(append_rollback_snapshot.preview_only_source_indices)
            source_role_overrides.clear()
            source_role_overrides.update(append_rollback_snapshot.source_role_overrides)
            source_display_overrides.clear()
            source_display_overrides.update(append_rollback_snapshot.source_display_overrides)
            _invalidate_source_display_cache()
            source_part_adjustments.clear()
            source_part_adjustments.update(copy.deepcopy(append_rollback_snapshot.source_part_adjustments))
            dialog_added_supplemental_files[:] = list(append_rollback_snapshot.dialog_added_supplemental_files)
            texture_files_for_mapping[:] = list(append_rollback_snapshot.texture_files_for_mapping)
            source_material_texture_override_assignments.clear()
            source_material_texture_override_assignments.update(
                append_rollback_snapshot.source_material_texture_override_assignments
            )
            replace_mesh_history_snapshot_stack(
                mesh_edit_redo_stack,
                append_rollback_snapshot.mesh_edit_redo_stack,
            )
            mesh_edit_redo_adjustment_stack[:] = copy.deepcopy(
                append_rollback_snapshot.mesh_edit_redo_adjustment_stack
            )
            source_geometry_revision["value"] = append_rollback_snapshot.source_geometry_revision
            selected_source_part["index"] = append_rollback_snapshot.selected_source_index
            selected_target_slot["index"] = append_rollback_snapshot.selected_target_index
            selected_original_part["index"] = append_rollback_snapshot.selected_original_index
            selected_source_highlight_indices.clear()
            selected_source_highlight_indices.update(append_rollback_snapshot.selected_source_highlights)
            transform_source_indices.clear()
            transform_source_indices.update(append_rollback_snapshot.transform_source_indices)
            selected_target_source_highlight_indices.clear()
            selected_target_source_highlight_indices.update(
                append_rollback_snapshot.selected_target_source_highlights
            )
            selected_original_highlight_indices.clear()
            selected_original_highlight_indices.update(append_rollback_snapshot.selected_original_highlights)
            selected_target_original_highlight_indices.clear()
            selected_target_original_highlight_indices.update(
                append_rollback_snapshot.selected_target_original_highlights
            )
            _rebuild_source_part_widgets(
                append_rollback_snapshot.selected_source_indices,
                current_index=append_rollback_snapshot.selected_source_index,
            )
            _sync_highlight_sets()
            _refresh_original_reference_preview()
            texture_sets = group_replacement_texture_sets(
                texture_files_for_mapping,
                obj_mesh=replacement_mesh_for_mapping,
            )
            _set_texture_sets(texture_sets)
            _apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
            _refresh_source_assignment_columns()
            try:
                _refresh_source_material_plan()
            except NameError:
                pass
            try:
                _refresh_texture_row_guidance()
                _refresh_texture_table(selected_texture_row.get("row"))
            except NameError:
                pass
            _load_selected_part_controls()
            _source_part_refresh_geometry_preview("cancelled mesh part import", replace_all=True)
            return True
        append_undo_pushed = False
        try:
            append_scene_result = import_scene_mesh_with_report(source_path)
            append_scene_result = _maybe_flatten_scene_import_parts(source_path, append_scene_result)
            if append_scene_result is None:
                _source_part_append_release_rollback_snapshots(append_rollback_snapshot)
                return
            append_scene_result = _maybe_reduce_high_density_scene_import(source_path, append_scene_result)
            if append_scene_result is None:
                _source_part_append_release_rollback_snapshots(append_rollback_snapshot)
                return
            _push_geometry_undo_snapshot("Add mesh part")
            append_undo_pushed = True
            append_result = append_scene_import_to_mesh(
                replacement_mesh_for_mapping,
                replacement_mesh_base_for_mapping,
                append_scene_result,
                source_path=source_path,
                label_prefix=source_path.stem,
            )
        except Exception as exc:
            if append_undo_pushed:
                _pop_geometry_undo_snapshot()
            _source_part_append_release_rollback_snapshots(append_rollback_snapshot)
            QMessageBox.warning(dialog, _source_part_add_mesh_part_failed_title_helper(), str(exc))
            return
        placement_note = _normalize_appended_part_to_work_area(append_result.source_indices)
        append_imported_state = _source_part_append_imported_state_helper(
            source_indices=append_result.source_indices,
            sources=replacement_mesh_for_mapping.submeshes,
            source_stem=source_path.stem,
            appended_source_indices=appended_source_indices,
            independent_output_source_indices=independent_output_source_indices,
            preview_only_source_indices=preview_only_source_indices,
        )
        appended_source_indices.clear()
        appended_source_indices.update(append_imported_state.index_state.appended_source_indices)
        independent_output_source_indices.clear()
        independent_output_source_indices.update(append_imported_state.index_state.independent_output_source_indices)
        preview_only_source_indices.clear()
        preview_only_source_indices.update(append_imported_state.index_state.preview_only_source_indices)
        for supplemental_path in tuple(append_result.supplemental_files or ()):
            if isinstance(supplemental_path, Path):
                _add_dialog_supplemental_file(supplemental_path)
        for presentation in append_imported_state.presentations:
            source = replacement_mesh_for_mapping.submeshes[presentation.source_index]
            source_display_overrides[presentation.source_index] = presentation.display_override
            source_role_overrides[presentation.source_index] = _mapping_role_hint(presentation.role_hint_text)
            _add_source_tree_item(presentation.source_index, source)
            part_source_combo.addItem(
                _source_display_name(presentation.source_index),
                presentation.source_index,
            )
        _invalidate_source_display_cache()
        source_geometry_revision["value"] = int(source_geometry_revision.get("value", 0) or 0) + 1
        clear_mesh_history_snapshot_stack(mesh_edit_redo_stack)
        mesh_edit_redo_adjustment_stack.clear()
        texture_sets = group_replacement_texture_sets(texture_files_for_mapping, obj_mesh=replacement_mesh_for_mapping)
        _set_texture_sets(texture_sets)
        _apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
        try:
            appended_texture_sets = [
                _texture_set_for_source_index(int(source_index), texture_sets)
                for source_index in tuple(append_result.source_indices or ())
            ]
            append_texture_control_state = _source_part_append_texture_control_state_helper(
                has_texture_files=bool(append_result.texture_files),
                texture_sets=tuple(appended_texture_sets),
            )
            if append_texture_control_state.enable_rebuild_sidecar:
                rebuild_sidecar_checkbox.setChecked(True)
            if append_texture_control_state.enable_inject_base_color:
                inject_base_color_checkbox.setChecked(True)
        except NameError:
            pass
        source_tree.clearSelection()
        for source_index in append_result.source_indices:
            item = source_items_by_index.get(int(source_index))
            if item is not None:
                item.setSelected(True)
                source_tree.setCurrentItem(item)
        if append_imported_state.first_source_index >= 0:
            selected_source_part["index"] = append_imported_state.first_source_index
        _fit_alignment_tree_height_to_rows(source_tree, **source_tree_layout_state.height_fit_kwargs)
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        try:
            _refresh_source_material_plan()
        except NameError:
            pass
        try:
            _refresh_texture_row_guidance()
            _refresh_texture_table(selected_texture_row.get("row"))
        except NameError:
            pass
        _load_selected_part_controls()
        _source_part_refresh_geometry_preview(
            _source_part_added_mesh_part_status_helper(source_path.name, placement_note),
            append_result.source_indices,
        )
        assignment_action = _prompt_assign_appended_mesh_parts(
            source_path,
            append_result.source_indices,
            placement_note=placement_note,
            discovered_texture_files=tuple(append_scene_result.discovered_texture_files or ()),
        )
        if assignment_action == "cancel":
            try:
                if _rollback_cancelled_appended_mesh_part_import():
                    _pop_geometry_undo_snapshot()
                    self.set_status_message(_source_part_cancel_import_status_helper(source_path.name))
                return
            finally:
                _source_part_append_release_rollback_snapshots(append_rollback_snapshot)
        _refresh_source_assignment_columns()
        try:
            _refresh_added_part_texture_tree(int(append_result.source_indices[0]) if append_result.source_indices else None)
        except NameError:
            pass
        try:
            _refresh_source_material_plan()
        except NameError:
            pass
        _source_part_refresh_geometry_preview(
            _source_part_added_mesh_part_status_helper(source_path.name, placement_note),
            append_result.source_indices,
        )
        _source_part_append_release_rollback_snapshots(append_rollback_snapshot)
        self.set_status_message(
            _source_part_added_mesh_part_status_helper(source_path.name, placement_note)
        )

    return SimpleNamespace(
        _delete_selected_source_parts=_delete_selected_source_parts,
        _apply_source_part_preview_changes=_apply_source_part_preview_changes,
        _apply_source_material_grouped_routing=_apply_source_material_grouped_routing,
        _duplicate_selected_part=_duplicate_selected_part,
        _append_mesh_part_to_geometry=_append_mesh_part_to_geometry,
    )
