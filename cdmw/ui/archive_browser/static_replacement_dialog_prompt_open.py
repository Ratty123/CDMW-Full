"""Final open/build wiring for static replacement prompt."""

from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps import (
    install_static_replacement_prompt_dependencies,
)

install_static_replacement_prompt_dependencies(globals())


def finish_static_replacement_prompt_open(context: dict[str, object]) -> None:
    self = context["self"]
    dialog = context["dialog"]
    root_layout = context["root_layout"]
    embedded_alignment_builder = context["embedded_alignment_builder"]
    continue_build_callback = context.get("continue_build_callback")
    replacement_export_allowed = context["replacement_export_allowed"]
    alignment_startup_text = context["alignment_startup_text"]
    _alignment_startup_step = context["_alignment_startup_step"]
    _finish_alignment_startup_progress = context["_finish_alignment_startup_progress"]
    _apply_alignment_dialog_responsive_layout = context["_apply_alignment_dialog_responsive_layout"]
    _queue_alignment_post_open_task = context["_queue_alignment_post_open_task"]
    _set_preview_renderer = context["_set_preview_renderer"]
    _capture_initial_geometry_snapshot = context["_capture_initial_geometry_snapshot"]
    _queue_static_preview_refresh = context["_queue_static_preview_refresh"]
    _load_original_reference_texture_preview = context["_load_original_reference_texture_preview"]
    _clear_all_part_selections = context["_clear_all_part_selections"]
    _refresh_mesh_editor_diagnostics = context["_refresh_mesh_editor_diagnostics"]
    _run_alignment_post_open_tasks = context["_run_alignment_post_open_tasks"]
    _record_runtime_event = getattr(self, "_record_runtime_event", lambda *_args, **_kwargs: {})

    def _record_open_step(step: str) -> None:
        _record_runtime_event(
            "mesh_alignment_open_step",
            path=str(getattr(context.get("entry"), "path", "") or ""),
            dialog_title=str(context.get("dialog_title") or ""),
            step=str(step or ""),
            embedded=bool(embedded_alignment_builder),
        )

    dialog_accepted_state = _alignment_dialog_accept_initial_state_helper()

    alignment_modeless_dialog_callbacks = create_alignment_modeless_dialog_callbacks(
        {**globals(), **context, **locals()}
    )
    _modeless_alignment_dialog_finished = (
        alignment_modeless_dialog_callbacks._modeless_alignment_dialog_finished
    )

    dialog.finished.connect(_modeless_alignment_dialog_finished)
    setattr(
        dialog,
        "_mesh_editor_embedded_request_material_resources",
        _load_original_reference_texture_preview,
    )
    _queue_alignment_post_open_task(_set_preview_renderer)
    _queue_alignment_post_open_task(_capture_initial_geometry_snapshot)
    _queue_alignment_post_open_task(_queue_static_preview_refresh)
    if not embedded_alignment_builder:
        _queue_alignment_post_open_task(_load_original_reference_texture_preview)
    _queue_alignment_post_open_task(_clear_all_part_selections)
    _queue_alignment_post_open_task(_refresh_mesh_editor_diagnostics)

    build_footer = _make_alignment_build_footer_helper(
        root_layout,
        continue_build=callable(continue_build_callback),
        export_allowed=bool(replacement_export_allowed["allowed"]),
        export_block_reason=str(replacement_export_allowed["reason"] or ""),
    )
    cancel_button = build_footer.cancel_button
    import_button = build_footer.import_button
    setattr(dialog, "_material_authority_build_button", import_button)
    setattr(
        dialog,
        "_material_authority_base_build_allowed",
        bool(replacement_export_allowed["allowed"]),
    )
    material_sync_status = str(getattr(dialog, "_material_authority_sync_status", "inactive") or "inactive")
    material_sync_state = getattr(dialog, "_material_authority_resolved_state", None)
    if material_sync_status != "inactive" and not bool(getattr(material_sync_state, "build_allowed", False)):
        import_button.setEnabled(False)
        import_button.setToolTip(
            str(getattr(dialog, "_material_authority_sync_reason", "") or "Material Authority exact preview is pending.")
        )
    build_status_bar = build_footer.build_status_bar
    build_status_label = build_footer.build_status_label
    cancel_button.clicked.connect(dialog.reject)
    build_accept_state = _alignment_build_accept_initial_state_helper()

    alignment_accept_build_callbacks = create_alignment_accept_build_callbacks(
        {**globals(), **context, **locals()}
    )
    (
        _apply_alignment_build_status_view,
        _set_alignment_build_status,
        _finish_alignment_build_state,
        _dispatch_alignment_accept,
        _commit_alignment_numeric_edits,
        _build_static_options_from_dialog,
    ) = static_replacement_section_values(
        alignment_accept_build_callbacks,
        (
            "_apply_alignment_build_status_view",
            "_set_alignment_build_status",
            "_finish_alignment_build_state",
            "_dispatch_alignment_accept",
            "_commit_alignment_numeric_edits",
            "_build_static_options_from_dialog",
        ),
    )

    _archive_dds_preview_source_for_path, _archive_dds_preview_sources_for_basename = (
        _archive_dds_preview_resolver_pair_helper(
            self.archive_entries_by_normalized_path,
            self.archive_entries_by_basename,
            ensure_preview_source=ensure_archive_preview_source,
        )
    )

    alignment_original_texture_intent_callbacks = create_alignment_original_texture_intent_callbacks(
        {**globals(), **context, **locals()}
    )
    _original_part_texture_intent_rows = (
        alignment_original_texture_intent_callbacks._original_part_texture_intent_rows
    )

    alignment_accept_dispatch_callbacks = create_alignment_accept_dispatch_callbacks(
        {**globals(), **context, **locals()}
    )
    _accept_static_options = alignment_accept_dispatch_callbacks._accept_static_options
    _accept_static_options_after_status_paint = (
        alignment_accept_dispatch_callbacks._accept_static_options_after_status_paint
    )

    import_button.clicked.connect(lambda _checked=False: _accept_static_options())

    alignment_fit_dialog_callbacks = create_alignment_fit_dialog_callbacks(
        {**globals(), **context, **locals()}
    )
    _fit_alignment_dialog_to_screen = alignment_fit_dialog_callbacks._fit_alignment_dialog_to_screen

    _alignment_startup_step(alignment_startup_text["opening_builder"])
    _record_open_step("begin")
    if embedded_alignment_builder and hasattr(self, "mesh_editor_tab"):
        _record_open_step("mount_embedded_before")
        dialog.setWindowTitle("Mesh Replacement Builder")
        root_layout.setContentsMargins(0, 0, 0, 0)
        self.mesh_editor_tab.mount_embedded_builder(dialog)
        _record_open_step("mount_embedded_after")
        _apply_alignment_dialog_responsive_layout(force_sizes=True)
    else:
        _record_open_step("fit_before")
        _fit_alignment_dialog_to_screen()
        _record_open_step("fit_after")
    _record_open_step("finish_progress_before")
    _finish_alignment_startup_progress()
    _record_open_step("finish_progress_after")
    _record_open_step("post_open_timer_before")
    QTimer.singleShot(0, _run_alignment_post_open_tasks)
    _record_open_step("post_open_timer_after")
    _record_open_step("show_before")
    dialog.show()
    _record_open_step("show_after")
    if embedded_alignment_builder:
        QTimer.singleShot(0, lambda: _apply_alignment_dialog_responsive_layout(force_sizes=True))
    if not embedded_alignment_builder:
        _record_open_step("raise_before")
        dialog.raise_()
        _record_open_step("raise_after")
        _record_open_step("activate_before")
        dialog.activateWindow()
        _record_open_step("activate_after")


__all__ = ["finish_static_replacement_prompt_open"]
