from __future__ import annotations

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
