"""Static mesh replacement builder prompt owner for archive browser entries."""

from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps import (
    install_static_replacement_prompt_dependencies,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_shell import (
    create_static_replacement_prompt_shell,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_setup import (
    create_static_replacement_prompt_setup,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_state_callbacks import (
    create_static_replacement_prompt_state_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_transform import (
    finish_static_replacement_prompt_transform,
)

install_static_replacement_prompt_dependencies(globals())


def prompt_archive_static_replacement_options(
    self,
    entry: ArchiveEntry,
    obj_path: Path,
    supplemental_files: Sequence[Path] = (),
    import_diagnostics: Sequence[str] = (),
    scene_import_result: Optional[SceneImportResult] = None,
    original_mesh: Optional[ParsedMesh] = None,
    preferred_rebuild_material_sidecar: Optional[bool] = None,
    preferred_complete_source_swap: bool = False,
    dialog_title: str = "",
    placement_context_note: str = "",
    source_texture_evidence: Sequence[Mapping[str, object]] = (),
    extra_supplemental_specs: Sequence[MeshImportSupplementalFileSpec] = (),
    defer_original_texture_preview: bool = False,
    runtime_export_target_entry: Optional[ArchiveEntry] = None,
    embedded_host: Optional[QWidget] = None,
    continue_build_callback: Optional[
        Callable[
            [
                StaticMeshReplacementOptions,
                Optional[QWidget],
                Callable[[str], None],
                Callable[[str, bool], None],
                str,
            ],
            bool,
        ]
    ] = None,
    on_accept: Optional[Callable[[StaticMeshReplacementOptions], None]] = None,
    on_cancel: Optional[Callable[[], None]] = None,
) -> None:
    dialog_title = dialog_title or _alignment_builder_window_title_helper()
    alignment_dialog_key = self._modeless_alignment_dialog_key(entry, obj_path, dialog_title)
    if self._activate_modeless_alignment_dialog(alignment_dialog_key):
        self.set_status_message(_alignment_builder_already_open_status_helper())
        return
    _record_runtime_event = getattr(self, "_record_runtime_event", lambda *_args, **_kwargs: {})
    builtin_context = {
        "any": any,
        "bool": bool,
        "enumerate": enumerate,
        "float": float,
        "globals": globals,
        "int": int,
        "len": len,
        "list": list,
        "locals": locals,
        "max": max,
        "object": object,
        "set": set,
        "str": str,
        "sum": sum,
        "tuple": tuple,
    }
    prompt_shell_context = {**globals(), **builtin_context, **locals()}
    alignment_prompt_shell = create_static_replacement_prompt_shell(prompt_shell_context)
    (
        alignment_dialog_key_hash, alignment_d3d11_view_state_reset_generation, embedded_alignment_builder,
        preview_build_entry, modify_original_clone_mode, original_texture_preview_default,
        original_texture_preview_state, original_reference_texture_preview_state, alignment_startup_text,
        startup_progress, startup_progress_closed, alignment_startup_step_state, _alignment_startup_step,
        _finish_alignment_startup_progress, dialog, alignment_dialog_closing, _alignment_dialog_widgets_live,
        _complete_external_swap_enabled, _complete_external_swap_mappings, _sync_complete_external_swap_mode,
        _refresh_output_impact_review, _clear_all_part_selections, _d3d11_source_part_selected,
        _mesh_edit_begin_stroke, _mesh_edit_apply_preview_payload, _mesh_edit_finish_stroke,
        _mesh_edit_cancel_stroke, _mesh_edit_selection_changed, alignment_texture_lookup_cache,
        _alignment_texture_lookup_indexes,
    ) = static_replacement_section_values(
        alignment_prompt_shell,
        (
            "alignment_dialog_key_hash", "alignment_d3d11_view_state_reset_generation", "embedded_alignment_builder",
            "preview_build_entry", "modify_original_clone_mode", "original_texture_preview_default",
            "original_texture_preview_state", "original_reference_texture_preview_state", "alignment_startup_text",
            "startup_progress", "startup_progress_closed", "alignment_startup_step_state", "_alignment_startup_step",
            "_finish_alignment_startup_progress", "dialog", "alignment_dialog_closing", "_alignment_dialog_widgets_live",
            "_complete_external_swap_enabled", "_complete_external_swap_mappings", "_sync_complete_external_swap_mode",
            "_refresh_output_impact_review", "_clear_all_part_selections", "_d3d11_source_part_selected",
            "_mesh_edit_begin_stroke", "_mesh_edit_apply_preview_payload", "_mesh_edit_finish_stroke",
            "_mesh_edit_cancel_stroke", "_mesh_edit_selection_changed", "alignment_texture_lookup_cache",
            "_alignment_texture_lookup_indexes",
        ),
    )
    alignment_preview_shell_section = create_alignment_preview_shell_section({
        **prompt_shell_context,
        **locals(),
        '_sync_highlight_sets': (lambda *args, **kwargs: _sync_highlight_sets(*args, **kwargs)),
    })
    (
        _alignment_current_camera_state, _alignment_d3d11_host_ready, _alignment_d3d11_live_frame_available, _alignment_d3d11_loading_stuck,
        _alignment_d3d11_saved_view_state, _apply_alignment_dialog_responsive_layout, _clear_stuck_alignment_d3d11_loading, _copy_mesh_editor_diagnostics,
        _get_preview_render_settings, _refresh_mesh_editor_diagnostics, _restore_alignment_preview_mode_view_state, _run_static_preview_batch,
        _save_alignment_preview_mode_view_state, _set_alignment_d3d11_loading, _set_alignment_d3d11_pipeline_stage, _set_alignment_d3d11_progress,
        _set_preview_performance_status, _set_preview_render_settings, alignment_control_content_min_width, alignment_control_min_width,
        alignment_d3d11_available, alignment_d3d11_fast_reload_interval_ms, alignment_d3d11_loading_spinner_label, alignment_d3d11_loading_state,
        alignment_d3d11_loading_timer, alignment_d3d11_package_reload_interval_ms, alignment_d3d11_preview_host, alignment_d3d11_preview_page,
        alignment_d3d11_preview_status_label, alignment_d3d11_reload_stuck_timeout_s, alignment_d3d11_reload_timer, alignment_d3d11_state,
        alignment_d3d11_status_timer, alignment_d3d11_view_mode_combo, alignment_d3d11_view_state, alignment_dialog_layout_callbacks,
        alignment_dialog_layout_state, alignment_preview_control_text, alignment_preview_min_width, alignment_preview_mode_state,
        alignment_preview_mode_view_states, alignment_preview_render_control_text, alignment_preview_settings_button, alignment_preview_view_sync,
        alignment_use_global_preview_button, clear_alignment_selection_button, content_container, controls_panel,
        custom_icon_control_text, generate_alignment_icon_button, label, layout,
        main_splitter, mesh_edit_control_content_min_width, mesh_edit_control_max_width, mesh_edit_control_min_width,
        mesh_editor_diagnostics_state, object_name, original_dialog_preview, overlay_dialog_preview,
        overlay_original_locked_checkbox, preview_depth_spin, preview_disable_brightness_checkbox, preview_disable_tint_checkbox,
        preview_disable_uv_scale_checkbox, preview_gizmo_checkbox, preview_help, preview_mode_combo,
        preview_panel, preview_performance_label, preview_render_mode_combo, preview_render_settings,
        preview_renderer_combo, preview_rough_spin, preview_shine_spin, preview_splitter,
        preview_stack, preview_support_maps_checkbox, preview_visible_mode_combo, previous_dialog_resize_event,
        replacement_only_preview, root_layout, static_dialog_preview, tooltip,
    ) = static_replacement_section_values(
        alignment_preview_shell_section,
        (
            "_alignment_current_camera_state", "_alignment_d3d11_host_ready", "_alignment_d3d11_live_frame_available", "_alignment_d3d11_loading_stuck",
            "_alignment_d3d11_saved_view_state", "_apply_alignment_dialog_responsive_layout", "_clear_stuck_alignment_d3d11_loading", "_copy_mesh_editor_diagnostics",
            "_get_preview_render_settings", "_refresh_mesh_editor_diagnostics", "_restore_alignment_preview_mode_view_state", "_run_static_preview_batch",
            "_save_alignment_preview_mode_view_state", "_set_alignment_d3d11_loading", "_set_alignment_d3d11_pipeline_stage", "_set_alignment_d3d11_progress",
            "_set_preview_performance_status", "_set_preview_render_settings", "alignment_control_content_min_width", "alignment_control_min_width",
            "alignment_d3d11_available", "alignment_d3d11_fast_reload_interval_ms", "alignment_d3d11_loading_spinner_label", "alignment_d3d11_loading_state",
            "alignment_d3d11_loading_timer", "alignment_d3d11_package_reload_interval_ms", "alignment_d3d11_preview_host", "alignment_d3d11_preview_page",
            "alignment_d3d11_preview_status_label", "alignment_d3d11_reload_stuck_timeout_s", "alignment_d3d11_reload_timer", "alignment_d3d11_state",
            "alignment_d3d11_status_timer", "alignment_d3d11_view_mode_combo", "alignment_d3d11_view_state", "alignment_dialog_layout_callbacks",
            "alignment_dialog_layout_state", "alignment_preview_control_text", "alignment_preview_min_width", "alignment_preview_mode_state",
            "alignment_preview_mode_view_states", "alignment_preview_render_control_text", "alignment_preview_settings_button", "alignment_preview_view_sync",
            "alignment_use_global_preview_button", "clear_alignment_selection_button", "content_container", "controls_panel",
            "custom_icon_control_text", "generate_alignment_icon_button", "label", "layout",
            "main_splitter", "mesh_edit_control_content_min_width", "mesh_edit_control_max_width", "mesh_edit_control_min_width",
            "mesh_editor_diagnostics_state", "object_name", "original_dialog_preview", "overlay_dialog_preview",
            "overlay_original_locked_checkbox", "preview_depth_spin", "preview_disable_brightness_checkbox", "preview_disable_tint_checkbox",
            "preview_disable_uv_scale_checkbox", "preview_gizmo_checkbox", "preview_help", "preview_mode_combo",
            "preview_panel", "preview_performance_label", "preview_render_mode_combo", "preview_render_settings",
            "preview_renderer_combo", "preview_rough_spin", "preview_shine_spin", "preview_splitter",
            "preview_stack", "preview_support_maps_checkbox", "preview_visible_mode_combo", "previous_dialog_resize_event",
            "replacement_only_preview", "root_layout", "static_dialog_preview", "tooltip",
        ),
    )
    alignment_workflow_shell_section = create_alignment_workflow_shell_section({**prompt_shell_context, **locals()})
    (
        _add_loose_source_folder_for_alignment, _choose_loaded_archive_mesh_source_for_alignment,
        _choose_mod_archive_mesh_source_for_alignment, add_archive_source_button,
        add_loose_source_button, add_mod_archive_source_button,
        alignment_source_mix_callbacks, alignment_workflow_control_text,
        context_group, context_html, context_values, control_tabs,
        diagnostics_copy_button, diagnostics_layout, diagnostics_page,
        diagnostics_refresh_button, diagnostics_tab, diagnostics_text,
        intro, mesh_edit_layout_page, mesh_edit_page, mesh_edit_tab,
        modify_original_parity_label, parts_layout, parts_page, parts_tab,
        selection_context_label, setup_layout, setup_page, setup_tab,
        source_mix_control_text, source_mix_hint, source_mix_layout,
        source_mix_status_label, source_mix_tray, textures_layout,
        textures_page, textures_tab,
    ) = static_replacement_section_values(
        alignment_workflow_shell_section,
        (
            "_add_loose_source_folder_for_alignment", "_choose_loaded_archive_mesh_source_for_alignment",
            "_choose_mod_archive_mesh_source_for_alignment", "add_archive_source_button",
            "add_loose_source_button", "add_mod_archive_source_button",
            "alignment_source_mix_callbacks", "alignment_workflow_control_text",
            "context_group", "context_html", "context_values", "control_tabs",
            "diagnostics_copy_button", "diagnostics_layout", "diagnostics_page",
            "diagnostics_refresh_button", "diagnostics_tab", "diagnostics_text",
            "intro", "mesh_edit_layout_page", "mesh_edit_page", "mesh_edit_tab",
            "modify_original_parity_label", "parts_layout", "parts_page", "parts_tab",
            "selection_context_label", "setup_layout", "setup_page", "setup_tab",
            "source_mix_control_text", "source_mix_hint", "source_mix_layout",
            "source_mix_status_label", "source_mix_tray", "textures_layout",
            "textures_page", "textures_tab",
        ),
    )

    prompt_shell_context.update(locals())
    alignment_prompt_state_callbacks = create_static_replacement_prompt_state_callbacks(prompt_shell_context)
    prompt_shell_context.update(vars(alignment_prompt_state_callbacks))

    prompt_shell_context.update(locals())
    alignment_prompt_setup = create_static_replacement_prompt_setup(prompt_shell_context)
    prompt_shell_context.update(vars(alignment_prompt_setup))
    if getattr(alignment_prompt_setup, "alignment_setup_failed", False):
        _finish_alignment_startup_progress()
        try:
            self._unregister_modeless_alignment_dialog(alignment_dialog_key, dialog)
        except Exception:
            pass
        try:
            dialog.close()
            dialog.deleteLater()
        except Exception:
            pass
        error_text = str(getattr(alignment_prompt_setup, "alignment_setup_error", "") or "unknown error")
        self.set_status_message(f"Mesh Replacement Builder setup failed: {error_text}", error=True)
        if embedded_alignment_builder and hasattr(self, "mesh_editor_tab"):
            QTimer.singleShot(
                0,
                lambda: self.mesh_editor_tab.show_empty_state(
                    "Mesh Replacement Builder setup failed. See workspace logs."
                ),
            )
        return
    finish_static_replacement_prompt_transform(prompt_shell_context)
    return


__all__ = ["prompt_archive_static_replacement_options"]
