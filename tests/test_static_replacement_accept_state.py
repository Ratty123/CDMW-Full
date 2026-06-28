from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_accept_state import (
    alignment_build_accept_route,
    alignment_accept_handler_failed_status,
    alignment_build_accept_initial_state,
    alignment_build_accept_running,
    alignment_build_accept_set_running,
    alignment_build_callback_result_route,
    alignment_build_failed_status,
    alignment_build_mod_warning_title,
    alignment_build_options_route,
    alignment_build_started_status,
    alignment_build_status_finished,
    alignment_build_status_reset,
    alignment_build_status_started,
    alignment_build_status_view,
    alignment_builder_warning_title,
    alignment_cancel_handler_failed_status,
    alignment_dialog_accept_initial_state,
    alignment_dialog_accepted,
    alignment_dialog_closing_initial_state,
    alignment_dialog_finished_route,
    alignment_dialog_mark_accepted,
    alignment_dialog_mark_closing,
    replacement_export_allowed_initial_state,
)
from cdmw.ui.archive_browser.static_replacement_dialog_callback_factories import (
    create_alignment_accept_dispatch_callbacks,
)


class _BuildButton:
    def __init__(self) -> None:
        self.enabled = True

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _MessageBox:
    warnings: list[tuple[object, str, str]] = []

    @classmethod
    def warning(cls, dialog: object, title: str, message: str) -> None:
        cls.warnings.append((dialog, title, message))


class _ImmediateTimer:
    @staticmethod
    def singleShot(_delay_ms: int, callback: object) -> None:
        callback()


class _StatusSink:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []

    def set_status_message(self, message: str, error: bool = False) -> None:
        self.messages.append((message, error))


def _accept_dispatch_context(
    *,
    options: object | None = None,
    build_options_callback: object | None = None,
    continue_build_callback: object | None = None,
) -> tuple[dict[str, object], list[object], list[str], list[tuple[str, bool]], _BuildButton, _StatusSink]:
    _MessageBox.warnings = []
    import_button = _BuildButton()
    status_sink = _StatusSink()
    view_states: list[object] = []
    status_updates: list[str] = []
    finishes: list[tuple[str, bool]] = []
    dialog = SimpleNamespace()

    def build_options(**kwargs: object) -> object | None:
        if build_options_callback is not None:
            return build_options_callback(**kwargs)
        return options

    context = {
        "QMessageBox": _MessageBox,
        "QTimer": _ImmediateTimer,
        "_alignment_build_accept_route_helper": alignment_build_accept_route,
        "_alignment_build_accept_running_helper": alignment_build_accept_running,
        "_alignment_build_accept_set_running_helper": alignment_build_accept_set_running,
        "_alignment_build_callback_result_route_helper": alignment_build_callback_result_route,
        "_alignment_build_failed_status_helper": alignment_build_failed_status,
        "_alignment_build_mod_warning_title_helper": alignment_build_mod_warning_title,
        "_alignment_build_options_route_helper": alignment_build_options_route,
        "_alignment_build_started_status_helper": alignment_build_started_status,
        "_alignment_build_status_reset_helper": alignment_build_status_reset,
        "_alignment_dialog_mark_accepted_helper": alignment_dialog_mark_accepted,
        "_apply_alignment_build_status_view": view_states.append,
        "_build_static_options_from_dialog": build_options if build_options_callback is not None or options is not None else None,
        "_dispatch_alignment_accept": lambda accepted_options: None,
        "_finish_alignment_build_state": lambda message, success: finishes.append((message, success)),
        "_set_alignment_build_status": status_updates.append,
        "build_accept_state": alignment_build_accept_initial_state(),
        "continue_build_callback": continue_build_callback,
        "dialog": dialog,
        "dialog_accepted_state": alignment_dialog_accept_initial_state(),
        "import_button": import_button,
        "on_accept": None,
        "replacement_export_allowed": replacement_export_allowed_initial_state(),
        "self": status_sink,
    }
    return context, view_states, status_updates, finishes, import_button, status_sink


def test_alignment_dialog_closing_initial_state_preserves_default() -> None:
    assert alignment_dialog_closing_initial_state() == {"closing": False}


def test_alignment_dialog_finished_route_separates_cancel_and_embedded_cleanup() -> None:
    state = alignment_dialog_closing_initial_state()
    alignment_dialog_mark_closing(state)
    route = alignment_dialog_finished_route(
        result=0,
        accepted_code=1,
        accepted=False,
        has_cancel_handler=True,
        embedded_builder=True,
        has_mesh_editor=True,
    )

    assert state == {"closing": True}
    assert route.should_call_cancel_handler is True
    assert route.should_show_embedded_empty_state is True
    accepted_route = alignment_dialog_finished_route(
        result=1,
        accepted_code=1,
        accepted=True,
        has_cancel_handler=True,
        embedded_builder=True,
        has_mesh_editor=False,
    )
    assert accepted_route.should_call_cancel_handler is False
    assert accepted_route.should_show_embedded_empty_state is False


def test_alignment_dialog_accept_state_starts_unaccepted() -> None:
    state = alignment_dialog_accept_initial_state()

    assert state == {"accepted": False}
    assert alignment_dialog_accepted(state) is False


def test_alignment_dialog_mark_accepted_sets_flag() -> None:
    state = alignment_dialog_accept_initial_state()

    alignment_dialog_mark_accepted(state)

    assert state == {"accepted": True}
    assert alignment_dialog_accepted(state) is True


def test_alignment_build_accept_state_tracks_running_flag() -> None:
    state = alignment_build_accept_initial_state()

    assert state == {"running": False}
    assert alignment_build_accept_running(state) is False
    assert alignment_build_accept_set_running(state, True) is True
    assert alignment_build_accept_running(state) is True
    assert alignment_build_accept_set_running(state, False) is False
    assert state == {"running": False}


def test_alignment_build_accept_route_schedules_or_runs_based_on_build_mode() -> None:
    running = alignment_build_accept_route(continue_build=True, running=True)
    assert running.should_ignore is True

    build_mod = alignment_build_accept_route(continue_build=True, running=False)
    assert build_mod.should_mark_running is True
    assert build_mod.should_disable_import is True
    assert build_mod.should_schedule_status_paint is True
    assert build_mod.should_run_immediately is False

    modal_continue = alignment_build_accept_route(continue_build=False, running=False)
    assert modal_continue.should_ignore is False
    assert modal_continue.should_run_immediately is True


def test_alignment_build_options_and_callback_routes_cover_reset_accept_and_started() -> None:
    missing = alignment_build_options_route(options_available=False, continue_build=True)
    assert missing.should_reset_build_status is True
    assert missing.should_collect_build_settings is False
    assert missing.should_accept_dialog is False

    collect = alignment_build_options_route(options_available=True, continue_build=True)
    assert collect.should_reset_build_status is False
    assert collect.should_collect_build_settings is True
    assert collect.should_accept_dialog is False

    accept = alignment_build_options_route(options_available=True, continue_build=False)
    assert accept.should_accept_dialog is True

    assert alignment_build_callback_result_route(False).should_reset_build_status is True
    assert alignment_build_callback_result_route(False).should_report_started is False
    assert alignment_build_callback_result_route(True).should_reset_build_status is False
    assert alignment_build_callback_result_route(True).should_report_started is True


def test_build_mod_after_material_authority_calls_continue_build_callback() -> None:
    options = SimpleNamespace(
        submesh_mappings=[SimpleNamespace(target_submesh_index=0)],
        complete_swap_material_profile="material_authority_detail_mask",
    )
    build_calls: list[tuple[object, object, str]] = []

    def continue_build(static_options: object, dialog: object, _set_status: object, _finish: object, mode: str) -> bool:
        build_calls.append((static_options, dialog, mode))
        return True

    context, _views, status_updates, _finishes, import_button, status_sink = _accept_dispatch_context(
        options=options,
        continue_build_callback=continue_build,
    )

    create_alignment_accept_dispatch_callbacks(context)._accept_static_options()

    assert build_calls == [(options, context["dialog"], "loose")]
    assert context["dialog"]._static_options is options
    assert import_button.enabled is False
    assert "Collecting mesh replacement mod build settings..." in status_updates
    assert status_sink.messages == [(alignment_build_started_status(), False)]
    assert _MessageBox.warnings == []


def test_build_mod_after_mesh_edit_requests_edited_source_mesh() -> None:
    edited_mesh = object()
    options = SimpleNamespace(submesh_mappings=[], edited_source_mesh=edited_mesh)
    build_kwargs: dict[str, object] = {}
    build_calls: list[object] = []

    def build_options(**kwargs: object) -> object:
        build_kwargs.update(kwargs)
        return options

    def continue_build(static_options: object, *_args: object) -> bool:
        build_calls.append(static_options)
        return True

    context, _views, _status_updates, _finishes, _import_button, _status_sink = _accept_dispatch_context(
        build_options_callback=build_options,
        continue_build_callback=continue_build,
    )

    create_alignment_accept_dispatch_callbacks(context)._accept_static_options()

    assert build_kwargs["include_edited_source_mesh"] is True
    assert build_calls == [options]
    assert context["dialog"]._static_options.edited_source_mesh is edited_mesh
    assert _MessageBox.warnings == []


def test_build_mod_missing_options_builder_reports_warning_without_calling_build() -> None:
    build_calls: list[object] = []

    context, _views, _status_updates, finishes, _import_button, _status_sink = _accept_dispatch_context(
        continue_build_callback=lambda *args: build_calls.append(args) or True,
    )

    create_alignment_accept_dispatch_callbacks(context)._accept_static_options()

    assert build_calls == []
    assert _MessageBox.warnings == [
        (
            context["dialog"],
            "Build Mod",
            "Build Mod options builder is unavailable.",
        )
    ]
    assert finishes == [("Mesh replacement build failed: Build Mod options builder is unavailable.", False)]


def test_replacement_export_allowed_initial_state_preserves_default() -> None:
    assert replacement_export_allowed_initial_state() == {"allowed": True, "reason": ""}


def test_alignment_build_status_view_normalizes_text_and_visibility() -> None:
    assert alignment_build_status_view("  Working  ", running=True) == {
        "text": "Working",
        "label_visible": True,
        "bar_visible": True,
    }
    assert alignment_build_status_view("", running=False, import_enabled=True) == {
        "text": "",
        "label_visible": False,
        "bar_visible": False,
        "import_enabled": True,
    }


def test_alignment_build_status_started_shows_progress() -> None:
    assert alignment_build_status_started("Preparing") == {
        "text": "Preparing",
        "label_visible": True,
        "bar_visible": True,
    }


def test_alignment_build_status_finished_clears_running_and_reports_error_state() -> None:
    state = {"running": True}

    view_state = alignment_build_status_finished(
        state,
        "Done",
        success=False,
        export_allowed=True,
    )

    assert state == {"running": False}
    assert view_state == {
        "text": "Done",
        "label_visible": True,
        "bar_visible": False,
        "import_enabled": True,
        "status_error": True,
    }


def test_alignment_build_status_reset_clears_running_and_hides_progress() -> None:
    state = {"running": True}

    assert alignment_build_status_reset(state, export_allowed=False) == {
        "text": "",
        "label_visible": False,
        "bar_visible": False,
        "import_enabled": False,
    }
    assert state == {"running": False}


def test_alignment_build_and_handler_status_text_preserves_dialog_copy() -> None:
    assert alignment_accept_handler_failed_status("boom") == (
        "Mesh Replacement Alignment accept handler failed: boom"
    )
    assert alignment_cancel_handler_failed_status("boom") == (
        "Mesh Replacement Alignment cancel handler failed: boom"
    )
    assert alignment_build_failed_status("boom") == "Mesh replacement build failed: boom"
    assert alignment_build_started_status() == (
        "Started mesh replacement build. Builder window remains open for more edits."
    )
    assert alignment_builder_warning_title() == "Mesh Replacement Builder"
    assert alignment_build_mod_warning_title() == "Build Mod"
