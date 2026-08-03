"""An accepted scene frame must not re-apply presentation the helper is holding.

Presentation state is replayable desired state, not a command. The host
republishes the whole snapshot after every accepted scene frame, and a frame is
published per brush pointer sample and after every selection change, so an
unguarded publish put a full presentation re-application behind every stroke
sample and every part click. In the helper that runs ``TryApplyPresentationState``
and then rewrites the preview-mode selection, the role-view buttons and the
controls hint -- the preview flashing a different mode before it settled, the
grid going out and coming back, and the right column repainting on a part click.

These drive the real handlers and count the real sends. A source guard would
still pass if the comparison were wired to the wrong dictionary.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.tab import MeshEditorTab
from tests.test_mesh_editor_action_bar import _EmbeddedMeshBuilder

ROOT = Path(__file__).resolve().parents[1]
_APP = QApplication.instance() or QApplication([])

_PRESENTATION = {
    "display": {"mode": "solid", "grid_visible": True, "gizmo_visible": True},
    "comparison_mode": "replacement_only",
    "mesh_edit_active": True,
    "camera": {"yaw": 1.0, "pitch": 0.5, "distance": 3.0},
}


class _PresentationBuilder(_EmbeddedMeshBuilder):
    """A builder whose presentation snapshot the test controls outright."""

    def __init__(self) -> None:
        super().__init__()
        self.presentation = copy.deepcopy(_PRESENTATION)

    def _mesh_editor_embedded_presentation_state(self) -> dict:
        # Deep-copied on every read, exactly as the real builder rebuilds it
        # from live widget state: equal content must still compare equal.
        return copy.deepcopy(self.presentation)


class _FakeSharedController:
    def __init__(self) -> None:
        self.is_running = True
        self.sent: list[dict] = []
        self.request_id = 40

    def send_authoring_message(self, payload) -> bool:
        self.sent.append(dict(payload))
        return True

    def send_correlated(self, event: str, payload) -> int:
        self.request_id += 1
        self.sent.append(
            {
                **dict(payload),
                "event": str(event),
                "request_id": self.request_id,
                "process_generation": 3,
            }
        )
        return self.request_id


def _embedded_tab(name: str) -> tuple[MeshEditorTab, _PresentationBuilder, _FakeSharedController]:
    settings = QSettings("CDMWTests", name)
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    builder = _PresentationBuilder()
    tab.mount_embedded_builder(builder)
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    fake = _FakeSharedController()
    tab._active_shared_dotnet_controller = lambda: fake  # type: ignore[method-assign]
    tab.standalone_dotnet_process_generation = 3
    return tab, builder, fake


def _publishes(fake: _FakeSharedController) -> list[dict]:
    return [msg for msg in fake.sent if msg.get("event") == "presentation_state_update"]


def _drive_scene_frame(tab: MeshEditorTab, builder: _PresentationBuilder, index: int) -> None:
    """One accepted scene frame, answered the way the real helper answers."""

    pending = {
        "session_id": str(builder.controller.session_view().session_id),
        "request_id": index,
        "process_generation": 3,
        "source_identity": "presentation-republish-test",
        "scene_generation": index,
    }
    tab.standalone_dotnet_scene_pending = dict(pending)
    ack = dict(pending)
    ack["status"] = "applied"
    tab._handle_dotnet_scene_state_ack(ack)
    _drain_presentation_acks(tab)


def _drain_presentation_acks(tab: MeshEditorTab) -> None:
    for _ in range(4):
        pending = tab.standalone_dotnet_presentation_pending
        if pending is None:
            return
        tab._handle_dotnet_protocol_event(
            {
                "event": "presentation_state_update_ack",
                "status": "applied",
                "session_id": pending["session_id"],
                "request_id": pending["request_id"],
                "process_generation": pending["process_generation"],
            }
        )


def test_a_stroke_of_scene_frames_publishes_presentation_once() -> None:
    tab, builder, fake = _embedded_tab("MeshPresentationStroke")
    try:
        for index in range(1, 13):
            _drive_scene_frame(tab, builder, index)

        published = _publishes(fake)
        assert len(published) == 1, (
            "every accepted scene frame republished the presentation snapshot; "
            "the helper re-applies its display mode, overlays and role view per "
            f"brush sample and per part click ({len(published)} publishes for 12 frames)"
        )
    finally:
        tab.deleteLater()


def test_a_changed_snapshot_still_publishes() -> None:
    """Skipping unchanged content must not make the helper unreachable."""

    tab, builder, fake = _embedded_tab("MeshPresentationChanged")
    try:
        _drive_scene_frame(tab, builder, 1)
        assert len(_publishes(fake)) == 1

        # The reader switched the preview's mesh view.
        builder.presentation["display"]["mode"] = "wireframe"
        _drive_scene_frame(tab, builder, 2)

        published = _publishes(fake)
        assert len(published) == 2, (
            f"a changed display mode never reached the helper ({len(published)})"
        )
        assert published[-1]["display"]["mode"] == "wireframe"

        # And it settles again rather than republishing the new value forever.
        for index in range(3, 8):
            _drive_scene_frame(tab, builder, index)
        assert len(_publishes(fake)) == 2
    finally:
        tab.deleteLater()


def test_presentation_uses_the_shared_controller_request_sequence() -> None:
    """Host and tab presentation acks must never share a request id."""

    tab, _builder, fake = _embedded_tab("MeshPresentationSharedRequestIds")
    try:
        assert tab._send_dotnet_presentation_state(copy.deepcopy(_PRESENTATION))

        pending = tab.standalone_dotnet_presentation_pending
        assert pending is not None
        assert pending["request_id"] == 41
        assert _publishes(fake)[-1]["request_id"] == 41
        assert tab.standalone_dotnet_presentation_request_id == 41
    finally:
        tab.deleteLater()


def test_a_rejected_apply_is_resent() -> None:
    """A helper that refused the payload is not holding it."""

    tab, builder, fake = _embedded_tab("MeshPresentationRejected")
    try:
        pending = {
            "session_id": str(builder.controller.session_view().session_id),
            "request_id": 1,
            "process_generation": 3,
            "source_identity": "presentation-republish-test",
            "scene_generation": 1,
        }
        tab.standalone_dotnet_scene_pending = dict(pending)
        tab._handle_dotnet_scene_state_ack({**pending, "status": "applied"})
        assert len(_publishes(fake)) == 1

        rejected = tab.standalone_dotnet_presentation_pending
        assert rejected is not None
        tab._handle_dotnet_protocol_event(
            {
                "event": "presentation_state_update_ack",
                "status": "rejected",
                "reason": "stale_process_generation",
                "session_id": rejected["session_id"],
                "request_id": rejected["request_id"],
                "process_generation": rejected["process_generation"],
            }
        )

        _drive_scene_frame(tab, builder, 2)
        assert len(_publishes(fake)) == 2, (
            "a refused presentation payload was recorded as applied, so the "
            "helper was left on the previous presentation with no way back"
        )
    finally:
        tab.deleteLater()


def test_a_package_apply_clears_what_the_helper_is_holding() -> None:
    """Applying a package empties the viewport's presentation contexts."""

    tab, builder, fake = _embedded_tab("MeshPresentationRehydrate")
    try:
        _drive_scene_frame(tab, builder, 1)
        assert len(_publishes(fake)) == 1
        assert tab.standalone_dotnet_presentation_published_content is not None

        tab._rehydrate_shared_dotnet_controller(fake)
        _drain_presentation_acks(tab)

        assert len(_publishes(fake)) == 2, (
            "a package apply left the host believing the helper still held a "
            "presentation the apply had just cleared"
        )
    finally:
        tab.deleteLater()


def test_the_other_display_mode_channel_invalidates_the_record() -> None:
    """`viewport_display_update` changes the same state by another route.

    The display mode lives in the presentation snapshot, but it is also settable
    through its own message, which never touches the desired snapshot. Left
    recorded as applied, a later presentation publish of the mode the record
    still names would be skipped and the helper would stay where the other
    channel put it, with nothing able to move it back.
    """

    tab, _builder, fake = _embedded_tab("MeshPresentationDisplayChannel")
    try:
        tab.standalone_dotnet_presentation_published_content = {
            "display": {"mode": "solid"}
        }
        assert tab._send_embedded_viewport_display_mode("wireframe") is True
        assert tab.standalone_dotnet_presentation_published_content is None, (
            "the display mode was changed through the viewport channel while the "
            "host went on believing the helper held the presentation snapshot's mode"
        )
        assert any(
            msg.get("event") == "viewport_display_update" for msg in fake.sent
        )
    finally:
        tab.deleteLater()


def test_a_fresh_process_holds_no_presentation() -> None:
    tab, _builder, _fake = _embedded_tab("MeshPresentationFreshProcess")
    try:
        tab.standalone_dotnet_presentation_published_content = {"display": {"mode": "solid"}}
        tab._connect_dotnet_protocol(object())
        assert tab.standalone_dotnet_presentation_published_content is None
    finally:
        tab.deleteLater()
