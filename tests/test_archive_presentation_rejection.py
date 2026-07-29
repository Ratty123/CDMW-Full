"""A refused .NET presentation update must be reported, not dropped.

Only the mesh editor read ``presentation_state_update_ack``. In the Archive
Browser a rejected display change left the toolbar showing the new state over a
viewport that never changed -- the shape of "unticking Load textures does
nothing" -- with no message anywhere saying the renderer had refused it.
"""

from __future__ import annotations

from cdmw.ui.archive_browser.preview_dotnet_lifecycle import (
    ArchivePreviewDotNetLifecycleMixin,
)


class _Harness(ArchivePreviewDotNetLifecycleMixin):
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []
        self.debug: list[str] = []

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.messages.append((message, bool(error)))

    def _set_archive_isolated_renderer_debug(self, message: str) -> None:
        self.debug.append(message)


def test_rejected_presentation_update_is_reported_with_its_reason() -> None:
    harness = _Harness()

    harness._handle_archive_renderer_protocol_event(
        {
            "event": "presentation_state_update_ack",
            "status": "rejected",
            "reason": "stale_process_generation",
        }
    )

    assert harness.messages == [
        (
            "The preview renderer refused the display change (stale_process_generation); "
            "the viewport still shows the previous view.",
            True,
        )
    ]
    assert harness.debug == [
        ".NET/Vortice Preview: presentation update rejected: stale_process_generation"
    ]
    assert harness._archive_presentation_rejection_reason == "stale_process_generation"


def test_rejection_without_a_reason_still_reports() -> None:
    harness = _Harness()

    harness._handle_archive_renderer_protocol_event(
        {"event": "presentation_state_update_ack", "status": "rejected"}
    )

    assert harness.messages[-1][1] is True
    assert "no reason reported" in harness.messages[-1][0]


def test_applied_updates_and_unrelated_events_stay_quiet() -> None:
    harness = _Harness()

    harness._handle_archive_renderer_protocol_event(
        {"event": "presentation_state_update_ack", "status": "applied", "reason": ""}
    )
    harness._handle_archive_renderer_protocol_event(
        {"event": "viewport_display_update_ack", "status": "rejected", "reason": "nope"}
    )
    harness._handle_archive_renderer_protocol_event("not a mapping")
    harness._handle_archive_renderer_protocol_event({})

    assert harness.messages == []
    assert harness.debug == []
