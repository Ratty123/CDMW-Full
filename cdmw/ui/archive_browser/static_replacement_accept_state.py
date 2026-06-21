"""Static replacement dialog accept/cancel state helpers."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass


@dataclass(frozen=True)
class AlignmentDialogFinishedRoute:
    should_call_cancel_handler: bool
    should_show_embedded_empty_state: bool


@dataclass(frozen=True)
class AlignmentBuildAcceptRoute:
    should_ignore: bool
    should_mark_running: bool
    should_disable_import: bool
    should_schedule_status_paint: bool
    should_run_immediately: bool


@dataclass(frozen=True)
class AlignmentBuildOptionsRoute:
    should_reset_build_status: bool
    should_collect_build_settings: bool
    should_accept_dialog: bool


@dataclass(frozen=True)
class AlignmentBuildCallbackResultRoute:
    should_reset_build_status: bool
    should_report_started: bool


def alignment_dialog_accept_initial_state() -> dict[str, bool]:
    return {"accepted": False}


def alignment_dialog_closing_initial_state() -> dict[str, bool]:
    return {"closing": False}


def alignment_dialog_accepted(state: MutableMapping[str, object]) -> bool:
    return bool(state.get("accepted"))


def alignment_dialog_mark_accepted(state: MutableMapping[str, object]) -> None:
    state["accepted"] = True


def alignment_dialog_mark_closing(state: MutableMapping[str, object]) -> None:
    state["closing"] = True


def alignment_dialog_finished_route(
    *,
    result: int,
    accepted_code: int,
    accepted: bool,
    has_cancel_handler: bool,
    embedded_builder: bool,
    has_mesh_editor: bool,
) -> AlignmentDialogFinishedRoute:
    cancelled = int(result) != int(accepted_code) and not bool(accepted)
    return AlignmentDialogFinishedRoute(
        should_call_cancel_handler=bool(cancelled and has_cancel_handler),
        should_show_embedded_empty_state=bool(embedded_builder and has_mesh_editor),
    )


def alignment_build_accept_initial_state() -> dict[str, bool]:
    return {"running": False}


def replacement_export_allowed_initial_state() -> dict[str, object]:
    return {"allowed": True, "reason": ""}


def alignment_build_accept_running(state: MutableMapping[str, object]) -> bool:
    return bool(state.get("running"))


def alignment_build_accept_set_running(
    state: MutableMapping[str, object],
    running: bool,
) -> bool:
    active = bool(running)
    state["running"] = active
    return active


def alignment_build_accept_route(
    *,
    continue_build: bool,
    running: bool,
) -> AlignmentBuildAcceptRoute:
    if bool(continue_build) and bool(running):
        return AlignmentBuildAcceptRoute(True, False, False, False, False)
    if bool(continue_build):
        return AlignmentBuildAcceptRoute(False, True, True, True, False)
    return AlignmentBuildAcceptRoute(False, False, False, False, True)


def alignment_build_options_route(
    *,
    options_available: bool,
    continue_build: bool,
) -> AlignmentBuildOptionsRoute:
    if not bool(options_available):
        return AlignmentBuildOptionsRoute(
            should_reset_build_status=bool(continue_build),
            should_collect_build_settings=False,
            should_accept_dialog=False,
        )
    if bool(continue_build):
        return AlignmentBuildOptionsRoute(
            should_reset_build_status=False,
            should_collect_build_settings=True,
            should_accept_dialog=False,
        )
    return AlignmentBuildOptionsRoute(
        should_reset_build_status=False,
        should_collect_build_settings=False,
        should_accept_dialog=True,
    )


def alignment_build_callback_result_route(started: bool) -> AlignmentBuildCallbackResultRoute:
    return AlignmentBuildCallbackResultRoute(
        should_reset_build_status=not bool(started),
        should_report_started=bool(started),
    )


def alignment_build_status_view(
    message: object,
    *,
    running: bool,
    import_enabled: bool | None = None,
) -> dict[str, object]:
    text = str(message or "").strip()
    view_state: dict[str, object] = {
        "text": text,
        "label_visible": bool(text),
        "bar_visible": bool(running),
    }
    if import_enabled is not None:
        view_state["import_enabled"] = bool(import_enabled)
    return view_state


def alignment_build_status_started(message: object) -> dict[str, object]:
    return alignment_build_status_view(message, running=True)


def alignment_build_status_finished(
    state: MutableMapping[str, object],
    message: object,
    *,
    success: bool,
    export_allowed: bool,
) -> dict[str, object]:
    alignment_build_accept_set_running(state, False)
    view_state = alignment_build_status_view(
        message,
        running=False,
        import_enabled=bool(export_allowed),
    )
    view_state["status_error"] = not bool(success)
    return view_state


def alignment_build_status_reset(
    state: MutableMapping[str, object],
    *,
    export_allowed: bool,
) -> dict[str, object]:
    alignment_build_accept_set_running(state, False)
    return alignment_build_status_view(
        "",
        running=False,
        import_enabled=bool(export_allowed),
    )


def alignment_accept_handler_failed_status(error: object) -> str:
    return f"Mesh Replacement Alignment accept handler failed: {error}"


def alignment_cancel_handler_failed_status(error: object) -> str:
    return f"Mesh Replacement Alignment cancel handler failed: {error}"


def alignment_build_failed_status(error: object) -> str:
    return f"Mesh replacement build failed: {error}"


def alignment_build_started_status() -> str:
    return "Started mesh replacement build. Builder window remains open for more edits."


def alignment_builder_warning_title() -> str:
    return "Mesh Replacement Builder"


def alignment_build_mod_warning_title() -> str:
    return "Build Mod"


__all__ = [
    "AlignmentBuildAcceptRoute",
    "AlignmentBuildCallbackResultRoute",
    "AlignmentBuildOptionsRoute",
    "AlignmentDialogFinishedRoute",
    "alignment_accept_handler_failed_status",
    "alignment_build_accept_initial_state",
    "alignment_build_accept_running",
    "alignment_build_accept_route",
    "alignment_build_accept_set_running",
    "alignment_build_callback_result_route",
    "alignment_build_failed_status",
    "alignment_build_mod_warning_title",
    "alignment_build_started_status",
    "alignment_build_status_finished",
    "alignment_build_status_reset",
    "alignment_build_status_started",
    "alignment_build_status_view",
    "alignment_builder_warning_title",
    "alignment_cancel_handler_failed_status",
    "alignment_dialog_accept_initial_state",
    "alignment_dialog_accepted",
    "alignment_dialog_closing_initial_state",
    "alignment_dialog_finished_route",
    "alignment_dialog_mark_accepted",
    "alignment_dialog_mark_closing",
    "alignment_build_options_route",
    "replacement_export_allowed_initial_state",
]
