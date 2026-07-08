"""Accept dispatch callback factory for the static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace


def create_alignment_accept_dispatch_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QMessageBox = context.get('QMessageBox')
    QTimer = context.get('QTimer')
    _alignment_build_accept_route_helper = context.get('_alignment_build_accept_route_helper')
    _alignment_build_accept_running_helper = context.get('_alignment_build_accept_running_helper')
    _alignment_build_accept_set_running_helper = context.get('_alignment_build_accept_set_running_helper')
    _alignment_build_callback_result_route_helper = context.get('_alignment_build_callback_result_route_helper')
    _alignment_build_failed_status_helper = context.get('_alignment_build_failed_status_helper')
    _alignment_build_mod_warning_title_helper = context.get('_alignment_build_mod_warning_title_helper')
    _alignment_build_options_route_helper = context.get('_alignment_build_options_route_helper')
    _alignment_build_started_status_helper = context.get('_alignment_build_started_status_helper')
    _alignment_build_status_reset_helper = context.get('_alignment_build_status_reset_helper')
    _alignment_dialog_mark_accepted_helper = context.get('_alignment_dialog_mark_accepted_helper')
    _apply_alignment_build_status_view = context.get('_apply_alignment_build_status_view')
    _build_static_options_from_dialog = context.get('_build_static_options_from_dialog')
    _dispatch_alignment_accept = context.get('_dispatch_alignment_accept')
    _finish_alignment_build_state = context.get('_finish_alignment_build_state')
    _set_alignment_build_status = context.get('_set_alignment_build_status')
    build_accept_state = context.get('build_accept_state')
    continue_build_callback = context.get('continue_build_callback')
    dialog = context.get('dialog')
    dialog_accepted_state = context.get('dialog_accepted_state')
    import_button = context.get('import_button')
    on_accept = context.get('on_accept')
    replacement_export_allowed = context.get('replacement_export_allowed')
    self = context.get('self')
    continue_build_available = callable(continue_build_callback)

    def _accept_static_options() -> None:
        accept_route = _alignment_build_accept_route_helper(
            continue_build=continue_build_available,
            running=_alignment_build_accept_running_helper(build_accept_state),
        )
        if accept_route.should_ignore:
            return
        if accept_route.should_mark_running:
            _alignment_build_accept_set_running_helper(build_accept_state, True)
        if accept_route.should_disable_import:
            import_button.setEnabled(False)
            _set_alignment_build_status("Preparing mesh replacement build options...")
        if accept_route.should_schedule_status_paint:
            QTimer.singleShot(25, _accept_static_options_after_status_paint)
            return
        if accept_route.should_run_immediately:
            _accept_static_options_after_status_paint()

    def _accept_static_options_after_status_paint() -> None:
        if not callable(_build_static_options_from_dialog):
            exc = TypeError("Build Mod options builder is unavailable.")
            QMessageBox.warning(
                dialog,
                _alignment_build_mod_warning_title_helper(),
                str(exc),
            )
            _finish_alignment_build_state(_alignment_build_failed_status_helper(exc), False)
            return
        try:
            static_options = _build_static_options_from_dialog(
                show_messages=True,
                include_edited_source_mesh=True,
            )
        except Exception as exc:
            # User-visible: option construction validates all required replacement inputs.
            QMessageBox.warning(
                dialog,
                _alignment_build_mod_warning_title_helper(),
                str(exc),
            )
            _finish_alignment_build_state(_alignment_build_failed_status_helper(exc), False)
            return
        options_route = _alignment_build_options_route_helper(
            options_available=static_options is not None,
            continue_build=continue_build_available,
        )
        if options_route.should_reset_build_status:
            _apply_alignment_build_status_view(
                _alignment_build_status_reset_helper(
                    build_accept_state,
                    export_allowed=bool(replacement_export_allowed["allowed"]),
                )
            )
        if static_options is None:
            return
        dialog._static_mappings = list(static_options.submesh_mappings or [])  # type: ignore[attr-defined]
        dialog._static_options = static_options  # type: ignore[attr-defined]
        if options_route.should_collect_build_settings:
            _set_alignment_build_status("Collecting mesh replacement mod build settings...")
            if not callable(continue_build_callback):
                exc = TypeError("Build Mod callback is unavailable.")
                QMessageBox.warning(
                    dialog,
                    _alignment_build_mod_warning_title_helper(),
                    str(exc),
                )
                _finish_alignment_build_state(_alignment_build_failed_status_helper(exc), False)
                started = False
            else:
                try:
                    started = bool(
                        continue_build_callback(
                            static_options,
                            dialog,
                            _set_alignment_build_status,
                            _finish_alignment_build_state,
                            "loose",
                        )
                    )
                except Exception as exc:
                    # User-visible: callback startup failures must leave build state recoverable.
                    QMessageBox.warning(
                        dialog,
                        _alignment_build_mod_warning_title_helper(),
                        str(exc),
                    )
                    _finish_alignment_build_state(_alignment_build_failed_status_helper(exc), False)
                    started = False
            callback_route = _alignment_build_callback_result_route_helper(started)
            if callback_route.should_reset_build_status:
                _apply_alignment_build_status_view(
                    _alignment_build_status_reset_helper(
                        build_accept_state,
                        export_allowed=bool(replacement_export_allowed["allowed"]),
                    )
                )
            if callback_route.should_report_started:
                self.set_status_message(_alignment_build_started_status_helper())
            return
        if options_route.should_accept_dialog:
            _alignment_dialog_mark_accepted_helper(dialog_accepted_state)
            dialog.accept()
            if on_accept is not None:
                QTimer.singleShot(0, lambda options=static_options: _dispatch_alignment_accept(options))

    return SimpleNamespace(
        _accept_static_options=_accept_static_options,
        _accept_static_options_after_status_paint=_accept_static_options_after_status_paint,
    )
