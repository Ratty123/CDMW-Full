"""State and callback binding owner for static replacement prompt."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps import (
    install_static_replacement_prompt_dependencies,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_state_context import (
    StaticReplacementPromptStateControls,
)

install_static_replacement_prompt_dependencies(globals())


def create_static_replacement_prompt_state_callbacks(context: dict[str, object]) -> SimpleNamespace:
    _alignment_dialog_widgets_live = context['_alignment_dialog_widgets_live']
    _record_runtime_event = context['_record_runtime_event']
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    alignment_d3d11_state = context['alignment_d3d11_state']
    controls = StaticReplacementPromptStateControls.from_mapping(context)
    dialog = context['dialog']
    entry = context['entry']
    prompt_shell_context = context['prompt_shell_context']
    SceneImportResult = context.get('SceneImportResult')
    obj_path = context.get('obj_path')
    scene_import_result = context.get('scene_import_result')
    self = context['self']

    def _mesh_edit_raw_preview_active() -> bool:
        active_callback = context.get("_mesh_edit_raw_preview_active")
        if callable(active_callback) and active_callback is not _mesh_edit_raw_preview_active:
            return bool(active_callback())
        return bool(
            _mesh_edit_raw_preview_active_helper(
                context.get("mesh_edit_enabled_checkbox"),
                context.get("_alignment_mesh_edit_tab_active"),
            )
        )

    suggested_mappings: List[StaticSubmeshMapping] = []
    prompt_shell_context["suggested_mappings"] = suggested_mappings
    mapping_edits: List[Tuple[int, QLineEdit]] = []
    texture_override_rows: List[Dict[str, Any]] = []
    texture_override_assignments: Dict[Tuple[str, str, str], str] = {}
    texture_sets: Dict[str, Any] = {}
    source_part_adjustments: Dict[int, StaticSourcePartAdjustment] = {}
    original_part_copies: List[StaticOriginalPartCopy] = []
    source_items_by_index: Dict[int, QTreeWidgetItem] = {}
    original_items_by_index: Dict[int, QTreeWidgetItem] = {}
    mapping_items_by_target: Dict[int, QTreeWidgetItem] = {}
    mapping_edits_by_target: Dict[int, QLineEdit] = {}
    selected_source_part = _single_selection_index_initial_state_helper()
    selected_original_part = _single_selection_index_initial_state_helper()
    selected_target_slot = _single_selection_index_initial_state_helper()
    source_role_overrides: Dict[int, str] = {}
    source_display_overrides: Dict[int, str] = {}
    source_display_label_cache: Dict[int, str] = {}
    source_display_duplicate_counts_cache: Dict[str, int] = {}
    source_display_cache_revision = _source_display_cache_revision_initial_state_helper()
    texture_items_by_source: List[Tuple[QTreeWidgetItem, Tuple[int, ...]]] = []
    texture_filter_selected_checkbox: Optional[QCheckBox] = None
    texture_filter_refresh: Dict[str, Optional[Callable[[], None]]] = _texture_filter_refresh_initial_state_helper()
    mesh_edit_raw_preview_state = _mesh_edit_raw_preview_initial_state_helper()
    replacement_mesh_for_mapping = None
    replacement_mesh_base_for_mapping = None
    original_mesh_for_mapping = None
    replacement_preview_model = None

    def _get_replacement_mesh_for_mapping():
        return replacement_mesh_for_mapping

    def _set_replacement_mesh_for_mapping(value) -> None:
        nonlocal replacement_mesh_for_mapping
        replacement_mesh_for_mapping = value

    def _get_replacement_mesh_base_for_mapping():
        return replacement_mesh_base_for_mapping

    def _set_replacement_mesh_base_for_mapping(value) -> None:
        nonlocal replacement_mesh_base_for_mapping
        replacement_mesh_base_for_mapping = value

    def _get_original_mesh_for_mapping():
        return original_mesh_for_mapping

    def _get_texture_sets() -> Dict[str, Any]:
        return texture_sets

    def _set_texture_sets(value: Dict[str, Any]) -> None:
        nonlocal texture_sets
        texture_sets = value

    def _get_replacement_preview_model():
        return replacement_preview_model

    def _set_replacement_preview_model(value) -> None:
        nonlocal replacement_preview_model
        if SceneImportResult is not None and isinstance(scene_import_result, SceneImportResult):
            scene_mesh = getattr(scene_import_result, "mesh", None)
            flip_v = scene_import_normalizes_texture_v(
                getattr(scene_mesh, "format", ""),
                getattr(scene_mesh, "path", "") or obj_path,
            )
            for mesh in tuple(getattr(value, "meshes", ()) or ()):
                if hasattr(mesh, "preview_texture_flip_vertical"):
                    mesh.preview_texture_flip_vertical = flip_v
        replacement_preview_model = value

    asset_profile: Optional[ReplacementAssetProfile] = None
    preview_controls_ready = _preview_controls_ready_initial_state_helper()
    replacement_export_allowed = _replacement_export_allowed_initial_state_helper()
    highlighted_source_indices: set[int] = set()
    highlighted_original_indices: set[int] = set()
    selected_source_highlight_indices: set[int] = set()
    selected_target_source_highlight_indices: set[int] = set()
    transform_source_indices: set[int] = set()
    direct_source_preview_index_map: Dict[int, int] = {}
    source_overlay_preview_index_map: Dict[int, int] = {}
    source_selection_overlay_preview_index_map: Dict[int, int] = {}
    source_selection_overlay_editor_id_map: Dict[int, int] = {}
    preview_submesh_index_map: Dict[int, int] = {}
    appended_source_indices: set[int] = set()
    independent_output_source_indices: set[int] = set()
    preview_only_source_indices: set[int] = set()
    selected_original_highlight_indices: set[int] = set()
    selected_target_original_highlight_indices: set[int] = set()
    texture_uv_transform_state: Dict[str, Dict[str, object]] = {}
    texture_uv_global_transform_state: Dict[str, object] = _texture_uv_global_transform_initial_state_helper()
    alignment_d3d11_texture_uv_fast_state = _texture_uv_fast_preview_initial_state_helper()
    source_material_texture_override_assignments: Dict[Tuple[str, str], str] = {}
    copied_original_texture_intents_by_source: Dict[int, List[Dict[str, str]]] = {}
    copied_original_texture_disabled_sources: set[int] = set()
    copied_original_source_indices: set[int] = set()
    copied_original_source_to_original_index: Dict[int, int] = {}
    copied_original_physics_sensitive_sources: set[int] = set()
    alignment_part_clipboard: Dict[str, object] = {}
    alignment_tree_event_filters: List[QObject] = []
    donor_material_plans_by_target: Dict[int, StaticDonorMaterialPlan] = {}
    texture_override_preview_specs: List[tuple[str, str, str, str, Tuple[int, ...], str]] = []

    def _get_texture_override_preview_specs():
        return texture_override_preview_specs

    def _set_texture_override_preview_specs(value) -> None:
        nonlocal texture_override_preview_specs
        texture_override_preview_specs = value

    def _get_rebuild_sidecar_checkbox():
        return context["rebuild_sidecar_checkbox"]

    alignment_virtual_texture_contract: Dict[str, object] = {
        "rows": (),
        "preview_specs": (),
        "patched_sidecar_texts": {},
        "sidecar_reports": (),
    }
    texture_overrides_dirty = _texture_overrides_dirty_initial_state_helper()
    source_parts_apply_state: Dict[str, object] = _source_parts_apply_initial_state_helper()
    material_authority_preview_signature_state = _material_authority_preview_signature_initial_state_helper()
    static_preview_refresh_timer = QTimer(dialog)
    static_preview_refresh_timer.setSingleShot(True)
    static_preview_refresh_timer.setInterval(_static_preview_refresh_interval_ms_helper())
    static_preview_settle_timer = QTimer(dialog)
    static_preview_settle_timer.setSingleShot(True)
    static_preview_settle_timer.setInterval(_static_preview_settle_interval_ms_helper())
    material_edit_refresh_timer = QTimer(dialog)
    material_edit_refresh_timer.setSingleShot(True)
    material_edit_refresh_timer.setInterval(_material_edit_refresh_interval_ms_helper())
    source_material_plan_refresh_timer = QTimer(dialog)
    source_material_plan_refresh_timer.setSingleShot(True)
    source_material_plan_refresh_timer.setInterval(_source_material_plan_refresh_interval_ms_helper())
    mapping_edit_refresh_timer = QTimer(dialog)
    mapping_edit_refresh_timer.setSingleShot(True)
    mapping_edit_refresh_timer.setInterval(_mapping_edit_refresh_interval_ms_helper())
    static_preview_batch_state = _static_preview_batch_initial_state_helper()
    material_edit_refresh_state = _material_edit_refresh_initial_state_helper()
    source_material_plan_refresh_state = _source_material_plan_refresh_initial_state_helper()
    alignment_post_open_tasks: List[Callable[[], None]] = []
    alignment_post_open_state = _alignment_post_open_initial_state_helper()
    static_preview_baked_transform_state: Dict[str, object] = _static_preview_baked_transform_initial_state_helper()
    alignment_d3d11_drag_transaction = _alignment_d3d11_drag_transaction_initial_state_helper()
    alignment_d3d11_drag_generation = _alignment_d3d11_drag_generation_initial_state_helper()
    alignment_transform_generation = _alignment_transform_generation_initial_state_helper()
    alignment_d3d11_drag_ui_state = _alignment_d3d11_drag_ui_initial_state_helper()
    alignment_d3d11_drag_ui_timer = QTimer(dialog)
    alignment_d3d11_drag_ui_timer.setSingleShot(True)
    alignment_d3d11_drag_ui_timer.setInterval(66)
    static_preview_geometry_cache: Dict[str, tuple[object, bool, Dict[int, int], Dict[int, int], Dict[int, int]]] = {}
    static_preview_prepared_cache: Dict[str, tuple[object, Optional[PreparedModelPreviewData]]] = {}
    static_replacement_vertex_limit = 65_535
    static_preview_interactive_until = _static_preview_interactive_until_initial_state_helper()
    mesh_edit_revision = _mesh_edit_revision_initial_state_helper()
    source_geometry_revision = _source_geometry_revision_initial_state_helper()
    dialog_added_supplemental_files: List[Path] = []
    mesh_edit_undo_stack: List[ParsedMesh] = []
    mesh_edit_redo_stack: List[ParsedMesh] = []
    mesh_edit_undo_adjustment_stack: List[Dict[int, bool]] = []
    mesh_edit_redo_adjustment_stack: List[Dict[int, bool]] = []
    mesh_edit_active_stroke: Dict[str, object] = {}
    mesh_edit_selected_vertices_by_submesh: Dict[int, set[int]] = {}
    mesh_edit_selected_faces_by_submesh: Dict[int, set[int]] = {}
    mesh_edit_selected_source_indices: set[int] = set()
    morph_slider_profile_root = self.settings_file_path.parent / "mesh_slider_profiles"
    morph_slider_profiles: List[MeshMorphSliderProfile] = []
    morph_slider_deltas: Dict[str, MeshMorphSliderDelta] = {}
    morph_slider_values: Dict[str, float] = {}
    morph_slider_rows: List[Dict[str, object]] = []
    morph_slider_post_edit_deltas: List[List[Tuple[float, float, float]]] = []
    morph_slider_topology_blocked: Dict[str, object] = _morph_slider_topology_blocked_initial_state_helper()
    morph_slider_update_guard: Dict[str, bool] = _morph_slider_activity_guard_initial_state_helper()
    morph_slider_change_active: Dict[str, bool] = _morph_slider_activity_guard_initial_state_helper()
    texture_material_plan_loaded = _texture_material_plan_loaded_initial_state_helper()
    geometry_undo_stack: List[Dict[str, Any]] = []
    geometry_initial_snapshot: Dict[str, Any] = {}
    geometry_history_guard = _geometry_history_guard_initial_state_helper()

    alignment_refresh_queue_callbacks = create_alignment_refresh_queue_callbacks({**context, **globals(), **locals()})
    (
        _queue_alignment_post_open_task, _run_alignment_post_open_tasks, _load_original_reference_texture_preview, _mark_alignment_transform_changed,
        _clear_alignment_d3d11_fast_transform_state, _alignment_d3d11_package_refresh_in_flight, _capture_static_preview_baked_transform_state, _alignment_preview_widget_render_settings,
        _alignment_preview_source_face_limit, _alignment_preview_selected_source_face_limit, _alignment_preview_background_source_face_limit, _configure_alignment_tree,
        _configure_texture_mapping_tree, _fit_alignment_tree_height_to_rows, _auto_fit_alignment_tree_columns, _install_alignment_tree_column_autofit,
        _mark_alignment_d3d11_rebuild_reason, _queue_static_preview_refresh, _queue_selection_preview_refresh, _queue_static_preview_rebuild,
        _queue_texture_preview_refresh, _queue_texture_uv_preview_refresh, _queue_material_edit_refresh, _queue_source_material_plan_refresh,
        _run_source_material_plan_refresh, _run_material_edit_refresh,
    ) = static_replacement_section_values(
        alignment_refresh_queue_callbacks,
        (
            "_queue_alignment_post_open_task", "_run_alignment_post_open_tasks", "_load_original_reference_texture_preview", "_mark_alignment_transform_changed",
            "_clear_alignment_d3d11_fast_transform_state", "_alignment_d3d11_package_refresh_in_flight", "_capture_static_preview_baked_transform_state", "_alignment_preview_widget_render_settings",
            "_alignment_preview_source_face_limit", "_alignment_preview_selected_source_face_limit", "_alignment_preview_background_source_face_limit", "_configure_alignment_tree",
            "_configure_texture_mapping_tree", "_fit_alignment_tree_height_to_rows", "_auto_fit_alignment_tree_columns", "_install_alignment_tree_column_autofit",
            "_mark_alignment_d3d11_rebuild_reason", "_queue_static_preview_refresh", "_queue_selection_preview_refresh", "_queue_static_preview_rebuild",
            "_queue_texture_preview_refresh", "_queue_texture_uv_preview_refresh", "_queue_material_edit_refresh", "_queue_source_material_plan_refresh",
            "_run_source_material_plan_refresh", "_run_material_edit_refresh",
        ),
    )

    alignment_dialog_layout_callbacks = create_alignment_dialog_layout_callbacks({**context, **globals(), **locals()})
    _run_static_preview_batch = alignment_dialog_layout_callbacks._run_static_preview_batch

    material_edit_refresh_timer.timeout.connect(_run_material_edit_refresh)
    source_material_plan_refresh_timer.timeout.connect(_run_source_material_plan_refresh)

    def _mesh_edit_apply_preview_mode_transition(reason: str) -> None:
        if not _alignment_dialog_widgets_live():
            return
        previous_raw, current_raw = _mesh_edit_raw_preview_record_state_helper(
            mesh_edit_raw_preview_state,
            _mesh_edit_raw_preview_active(),
        )
        try:
            sync_mesh_edit_preview_settings = prompt_shell_context.get(
                "_sync_mesh_edit_preview_settings",
                context.get("_sync_mesh_edit_preview_settings"),
            )
            if callable(sync_mesh_edit_preview_settings):
                sync_mesh_edit_preview_settings()
        except NameError:
            pass
        transition_route = _mesh_edit_raw_preview_transition_route_helper(
            previous_raw,
            current_raw,
            raw_package_active_or_pending=_alignment_d3d11_raw_package_active_or_pending_helper(alignment_d3d11_state),
        )
        if not transition_route.changed:
            return
        _record_runtime_event(
            "mesh_edit_preview_mode_transition",
            reason=str(reason or "unknown"),
            raw_preview_before=previous_raw,
            raw_preview_after=current_raw,
            d3d11_active=bool(_alignment_d3d11_preview_active()),
            path=str(getattr(entry, "path", "") or ""),
        )
    def _commit_spinbox_text(spin: QDoubleSpinBox, *, block_signals: bool = False) -> None:
        _commit_spinbox_text_helper(spin, block_signals=block_signals)

    _current_texture_uv_transforms = lambda: _current_texture_uv_transforms_helper(
            texture_sets,
            texture_uv_transform_state,
            texture_uv_global_transform_state,
            state_has_edits=_texture_uv_state_has_edits,
            transform_key=_texture_uv_transform_key,
        )

    _current_source_material_texture_overrides = (
        lambda: _current_source_material_texture_overrides_helper(source_material_texture_override_assignments)
    )

    _current_donor_material_plans = lambda: _current_donor_material_plans_helper(donor_material_plans_by_target)

    alignment_d3d11_package_lifecycle_callbacks = create_alignment_d3d11_package_lifecycle_callbacks({**context, **globals(), **locals()})
    (
        _apply_source_material_texture_overrides_to_ui_texture_sets, _alignment_d3d11_preview_active, _alignment_d3d11_editor_ids_for_source_indices, _alignment_d3d11_source_indices_for_editor_id, _alignment_mesh_edit_tab_active, _reapply_global_flip_v_fast_preview, _try_apply_global_flip_v_fast_preview,
        _alignment_default_d3d11_editor_ids, _cleanup_alignment_d3d11_package, _alignment_d3d11_invalidate_package_cache, _alignment_d3d11_geometry_cache_key,
        _alignment_d3d11_preview_cache_signature, _alignment_d3d11_preview_cache_key, _alignment_d3d11_package_cache_get, _alignment_d3d11_package_cache_put,
        _drop_alignment_d3d11_package_reload, _alignment_d3d11_stop_process, _alignment_d3d11_stop_worker, _shutdown_alignment_d3d11_preview,
        _safe_shutdown_alignment_d3d11_preview, _side_by_side_alignment_preview_model, _queue_alignment_d3d11_preview, _alignment_d3d11_package_quality,
        _queue_alignment_archive_parity_upgrade, _queue_latest_alignment_d3d11_rebuild_for_stale_reload, _handle_alignment_d3d11_stale_reload, _handle_alignment_d3d11_package_progress,
        _start_alignment_d3d11_package_worker, _flush_alignment_d3d11_preview_request, _handle_alignment_d3d11_package_ready, _handle_alignment_d3d11_package_error,
        _cleanup_alignment_d3d11_package_worker_refs, _start_alignment_d3d11_process, _check_alignment_d3d11_start_timeout, _handle_alignment_d3d11_stderr,
        _handle_alignment_d3d11_error, _handle_alignment_d3d11_finished, _poll_alignment_d3d11_status,
    ) = static_replacement_section_values(
        alignment_d3d11_package_lifecycle_callbacks,
        (
            "_apply_source_material_texture_overrides_to_ui_texture_sets", "_alignment_d3d11_preview_active", "_alignment_d3d11_editor_ids_for_source_indices", "_alignment_d3d11_source_indices_for_editor_id", "_alignment_mesh_edit_tab_active", "_reapply_global_flip_v_fast_preview", "_try_apply_global_flip_v_fast_preview",
            "_alignment_default_d3d11_editor_ids", "_cleanup_alignment_d3d11_package", "_alignment_d3d11_invalidate_package_cache", "_alignment_d3d11_geometry_cache_key",
            "_alignment_d3d11_preview_cache_signature", "_alignment_d3d11_preview_cache_key", "_alignment_d3d11_package_cache_get", "_alignment_d3d11_package_cache_put",
            "_drop_alignment_d3d11_package_reload", "_alignment_d3d11_stop_process", "_alignment_d3d11_stop_worker", "_shutdown_alignment_d3d11_preview",
            "_safe_shutdown_alignment_d3d11_preview", "_side_by_side_alignment_preview_model", "_queue_alignment_d3d11_preview", "_alignment_d3d11_package_quality",
            "_queue_alignment_archive_parity_upgrade", "_queue_latest_alignment_d3d11_rebuild_for_stale_reload", "_handle_alignment_d3d11_stale_reload", "_handle_alignment_d3d11_package_progress",
            "_start_alignment_d3d11_package_worker", "_flush_alignment_d3d11_preview_request", "_handle_alignment_d3d11_package_ready", "_handle_alignment_d3d11_package_error",
            "_cleanup_alignment_d3d11_package_worker_refs", "_start_alignment_d3d11_process", "_check_alignment_d3d11_start_timeout", "_handle_alignment_d3d11_stderr",
            "_handle_alignment_d3d11_error", "_handle_alignment_d3d11_finished", "_poll_alignment_d3d11_status",
        ),
    )
    prompt_shell_context["_alignment_d3d11_source_indices_for_editor_id"] = _alignment_d3d11_source_indices_for_editor_id
    context["_alignment_d3d11_source_indices_for_editor_id"] = _alignment_d3d11_source_indices_for_editor_id
    prompt_shell_context["_alignment_mesh_edit_tab_active"] = _alignment_mesh_edit_tab_active
    context["_alignment_mesh_edit_tab_active"] = _alignment_mesh_edit_tab_active

    alignment_preview_mode_callbacks = create_alignment_preview_mode_callbacks({**context, **globals(), **locals()})
    _set_preview_renderer = alignment_preview_mode_callbacks._set_preview_renderer
    _sync_highlight_sets = alignment_preview_mode_callbacks._sync_highlight_sets
    _preview_mode_qt_widgets = alignment_preview_mode_callbacks._preview_mode_qt_widgets
    _preview_mode_needs_static_refresh = alignment_preview_mode_callbacks._preview_mode_needs_static_refresh
    _set_preview_display_mode = alignment_preview_mode_callbacks._set_preview_display_mode
    _set_preview_mode = alignment_preview_mode_callbacks._set_preview_mode

    alignment_preview_render_settings_callbacks = create_alignment_preview_render_settings_callbacks({**context, **globals(), **locals()})
    (
        _alignment_preview_render_settings_from_controls, _current_alignment_preview_render_settings, _alignment_preview_package_settings_changed, _apply_alignment_preview_render_settings,
        _sync_alignment_preview_controls_from_settings, _use_global_alignment_preview_settings, _open_alignment_preview_settings_dialog,
    ) = static_replacement_section_values(
        alignment_preview_render_settings_callbacks,
        (
            "_alignment_preview_render_settings_from_controls", "_current_alignment_preview_render_settings", "_alignment_preview_package_settings_changed", "_apply_alignment_preview_render_settings",
            "_sync_alignment_preview_controls_from_settings", "_use_global_alignment_preview_settings", "_open_alignment_preview_settings_dialog",
        ),
    )

    controls.preview_visible_mode_combo.currentIndexChanged.connect(_apply_alignment_preview_render_settings)
    controls.preview_render_mode_combo.currentIndexChanged.connect(_apply_alignment_preview_render_settings)
    controls.preview_disable_tint_checkbox.toggled.connect(_apply_alignment_preview_render_settings)
    controls.preview_disable_brightness_checkbox.toggled.connect(_apply_alignment_preview_render_settings)
    controls.preview_disable_uv_scale_checkbox.toggled.connect(_apply_alignment_preview_render_settings)
    controls.preview_support_maps_checkbox.toggled.connect(_apply_alignment_preview_render_settings)
    controls.preview_depth_spin.valueChanged.connect(_apply_alignment_preview_render_settings)
    controls.preview_shine_spin.valueChanged.connect(_apply_alignment_preview_render_settings)
    controls.preview_rough_spin.valueChanged.connect(_apply_alignment_preview_render_settings)
    controls.alignment_d3d11_view_mode_combo.currentIndexChanged.connect(
        _apply_alignment_preview_render_settings
    )
    controls.alignment_preview_settings_button.clicked.connect(
        lambda _checked=False: _open_alignment_preview_settings_dialog()
    )
    controls.alignment_use_global_preview_button.clicked.connect(_use_global_alignment_preview_settings)

    controls.preview_renderer_combo.currentIndexChanged.connect(lambda _index: _set_preview_renderer())
    controls.preview_mode_combo.currentIndexChanged.connect(_set_preview_mode)
    controls.preview_mesh_view_combo.currentIndexChanged.connect(_set_preview_display_mode)
    controls.overlay_original_locked_checkbox.toggled.connect(_queue_static_preview_refresh)
    controls.alignment_d3d11_reload_timer.timeout.connect(_flush_alignment_d3d11_preview_request)

    alignment_selection_mapping_helpers = create_alignment_selection_mapping_helpers({
        **context,
        **globals(),
        **locals(),
        "_copied_original_dds_badge": (lambda *args, **kwargs: context["_copied_original_dds_badge"](*args, **kwargs)),
        "_copied_original_texture_tooltip": (
            lambda *args, **kwargs: context["_copied_original_texture_tooltip"](*args, **kwargs)
        ),
        "_get_added_texture_role_combo": (lambda: context['added_texture_role_combo']),
        "_get_mapping_tree": (lambda: context['mapping_tree']),
        "_get_mappings_by_target": (lambda: context['mappings_by_target']),
        "_get_part_glow_color_checkbox": (lambda: context['part_glow_color_checkbox']),
        "_get_properties_labels": (lambda: (
            context["properties_identity_label"],
            context["properties_assignment_label"],
            context["properties_dds_label"],
            context["properties_output_label"],
            context["properties_warnings_label"],
        )),
        "_get_prune_unmapped_original_dds_checkbox": (lambda: context['prune_unmapped_original_dds_checkbox']),
        "_get_selected_added_part_texture_row": (lambda: context['selected_added_part_texture_row']),
        "_get_selected_texture_row": (lambda: context['selected_texture_row']),
        "_get_source_tree": (lambda: context['source_tree']),
        "_get_source_tree_layout_state": (lambda: context['source_tree_layout_state']),
        "_get_texture_filter_selected_checkbox": (lambda: context['texture_filter_selected_checkbox']),
        "_get_texture_transform_material_combo": (lambda: context['texture_transform_material_combo']),
        "_parse_mapping_edit": (lambda *args, **kwargs: context["_parse_mapping_edit"](*args, **kwargs)),
        "_refresh_added_part_texture_tree": (
            lambda *args, **kwargs: context["_refresh_added_part_texture_tree"](*args, **kwargs)
        ),
        "_refresh_geometry_summary": (lambda *args, **kwargs: context["_refresh_geometry_summary"](*args, **kwargs)),
        "_refresh_output_impact_review": (lambda *args, **kwargs: context["_refresh_output_impact_review"](*args, **kwargs)),
        "_refresh_parts_outliner": (lambda *args, **kwargs: context["_refresh_parts_outliner"](*args, **kwargs)),
        "_refresh_source_material_plan": (lambda *args, **kwargs: context["_refresh_source_material_plan"](*args, **kwargs)),
        "_refresh_ui_texture_sets_after_source_part_material_override": (
            lambda *args, **kwargs: context["_refresh_ui_texture_sets_after_source_part_material_override"](*args, **kwargs)
        ),
        "_selected_part_glow_rgb_from_controls": (
            lambda *args, **kwargs: context["_selected_part_glow_rgb_from_controls"](*args, **kwargs)
        ),
        "_source_texture_slot_count": (
            lambda *args, **kwargs: (
                context.get("_source_texture_slot_count") or (lambda *_args, **_kwargs: 0)
            )(*args, **kwargs)
        ),
        "_target_physics_status_text": (lambda *args, **kwargs: context["_target_physics_status_text"](*args, **kwargs)),
        "_target_texture_status_text": (lambda *args, **kwargs: context["_target_texture_status_text"](*args, **kwargs)),
    })
    (
        _disabled_source_part_indices, _enabled_renderable_source_indices,
        _geometry_original_copy_text_by_index, _invalidate_source_display_cache,
        _mapping_role_hint, _material_sidecar_patch_enabled,
        _removed_target_dds_cell_text, _selected_source_summary,
        _source_display_name, _source_index_help_text,
        _source_index_is_enabled_renderable, _source_outliner_dds_text,
        _source_outliner_state, _source_role_label,
        _source_role_override_value, _source_target_summary,
        _source_tree_status_text, _target_display_name,
        _target_index_for_name, _target_outliner_state,
        mesh_replacement_selection_view_model,
    ) = static_replacement_section_values(
        alignment_selection_mapping_helpers,
        (
            "_disabled_source_part_indices", "_enabled_renderable_source_indices",
            "_geometry_original_copy_text_by_index", "_invalidate_source_display_cache",
            "_mapping_role_hint", "_material_sidecar_patch_enabled",
            "_removed_target_dds_cell_text", "_selected_source_summary",
            "_source_display_name", "_source_index_help_text",
            "_source_index_is_enabled_renderable", "_source_outliner_dds_text",
            "_source_outliner_state", "_source_role_label",
            "_source_role_override_value", "_source_target_summary",
            "_source_tree_status_text", "_target_display_name",
            "_target_index_for_name", "_target_outliner_state",
            "mesh_replacement_selection_view_model",
        ),
    )

    (
        _current_source_part_adjustments, _ensure_source_part_adjustment,
        _geometry_mapping_text_by_target, _output_impact_counts,
        _refresh_mesh_replacement_properties_inspector, _refresh_source_assignment_columns,
        _selection_context_texture_text, _set_mesh_replacement_selection_view,
        _set_source_role_override_value, _source_indices_for_target_name,
        _update_selection_context,
    ) = static_replacement_section_values(
        alignment_selection_mapping_helpers,
        (
            "_current_source_part_adjustments", "_ensure_source_part_adjustment",
            "_geometry_mapping_text_by_target", "_output_impact_counts",
            "_refresh_mesh_replacement_properties_inspector", "_refresh_source_assignment_columns",
            "_selection_context_texture_text", "_set_mesh_replacement_selection_view",
            "_set_source_role_override_value", "_source_indices_for_target_name",
            "_update_selection_context",
        ),
    )

    alignment_geometry_history_callbacks = create_alignment_geometry_history_callbacks({**context, **globals(), **locals(), '_load_selected_part_controls': (lambda *args, **kwargs: context['_load_selected_part_controls'](*args, **kwargs)), '_morph_slider_refresh_controls': (lambda *args, **kwargs: context['_morph_slider_refresh_controls'](*args, **kwargs)), '_morph_slider_reload_profiles': (lambda *args, **kwargs: context['_morph_slider_reload_profiles'](*args, **kwargs)), '_rebuild_source_part_widgets': (lambda *args, **kwargs: context['_rebuild_source_part_widgets'](*args, **kwargs)), '_refresh_original_reference_preview': (lambda *args, **kwargs: context['_refresh_original_reference_preview'](*args, **kwargs)), '_refresh_texture_row_guidance': (lambda *args, **kwargs: context['_refresh_texture_row_guidance'](*args, **kwargs)), '_refresh_texture_table': (lambda *args, **kwargs: context['_refresh_texture_table'](*args, **kwargs)), '_selected_source_indices_from_tree': (lambda *args, **kwargs: context['_selected_source_indices_from_tree'](*args, **kwargs)), '_update_mapping_status': (lambda *args, **kwargs: context['_update_mapping_status'](*args, **kwargs))})
    (
        _capture_geometry_history_state, _refresh_geometry_history_buttons, _push_geometry_undo_snapshot, _push_geometry_sparse_mesh_edit_snapshot, _pop_geometry_undo_snapshot,
        _restore_geometry_history_state, _undo_geometry_change, _reset_geometry_changes, _capture_initial_geometry_snapshot,
        _flush_mapping_edit_refresh,
    ) = static_replacement_section_values(
        alignment_geometry_history_callbacks,
        (
            "_capture_geometry_history_state", "_refresh_geometry_history_buttons", "_push_geometry_undo_snapshot", "_push_geometry_sparse_mesh_edit_snapshot", "_pop_geometry_undo_snapshot",
            "_restore_geometry_history_state", "_undo_geometry_change", "_reset_geometry_changes", "_capture_initial_geometry_snapshot",
            "_flush_mapping_edit_refresh",
        ),
    )

    mapping_edit_refresh_timer.timeout.connect(_flush_mapping_edit_refresh)

    alignment_mapping_edit_callbacks = create_alignment_mapping_edit_callbacks({**context, **globals(), **locals(), '_sync_target_mapping_tree_item': (lambda *args, **kwargs: context['_sync_target_mapping_tree_item'](*args, **kwargs))})
    _commit_mapping_edit = alignment_mapping_edit_callbacks._commit_mapping_edit


    return SimpleNamespace(**{name: value for name, value in locals().items() if name != "context"})


__all__ = ["create_static_replacement_prompt_state_callbacks"]
