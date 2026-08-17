"""Nothing that is not a camera command may move the camera.

Enabling the Gizmo put the viewport back to its opening framing. The gizmo was
never the point: presentation state is republished for a whole class of reasons
that have nothing to do with the camera -- a gizmo or grid toggle, a part
highlight, a display mode, a preview refresh, an accepted scene frame -- and two
separate things put a camera into those republishes.

The first is that the embedded Mesh Editor snapshot synthesised one. Its getter
answers, for the embedded viewport, with a per-mode snapshot saved at the last
mode switch or, failing that, a hardcoded yaw -35 / pitch 20 carrying
`fit_to_view`. The resident helper honours `fit_to_view` by refitting the zoom
and zeroing the pan, so publishing it is a reset.

The second is that the camera was retained in the replayable desired snapshot,
so once any camera had been merged it rode every later publish.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    builder_part_highlight_state,
    builder_presentation_state,
)
from cdmw.ui.mesh_editor import MeshEditorTab
from tests.test_mesh_editor_action_bar import (
    _EmbeddedMeshBuilder,
    _FakeProcess,
    _install_shared_dotnet_test_process,
)


def _presentation_state(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "comparison_mode": "replacement_only",
        "camera": None,
        "render_settings": SimpleNamespace(),
        "grid_visible": True,
        "gizmo_visible": True,
        "part_pick_enabled": False,
    }
    base.update(overrides)
    return builder_presentation_state(**base)  # type: ignore[arg-type]


def test_a_snapshot_without_a_camera_carries_no_camera_key() -> None:
    """An absent key is what leaves the helper's camera alone.

    An empty mapping is not good enough: the helper applies any camera block it
    is given, and only a missing key skips that path entirely.
    """
    assert "camera" not in _presentation_state(camera=None)
    assert "camera" not in _presentation_state(camera={})


def test_a_real_camera_still_travels() -> None:
    state = _presentation_state(camera={"yaw": 12.0, "pitch": 3.0})
    assert state["camera"]["yaw"] == 12.0
    assert state["camera"]["pitch"] == 3.0


def test_the_narrow_highlight_update_never_carried_a_camera() -> None:
    state = builder_part_highlight_state(
        selection_active=True,
        grid_visible=True,
        gizmo_visible=True,
        part_pick_enabled=False,
    )
    assert "camera" not in state


def _mounted_tab(name: str):
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", name)
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(tab, process)
    return app, tab, builder, process


def _published_cameras(tab: MeshEditorTab) -> list[object]:
    return [
        payload["camera"]
        for payload in tab.standalone_dotnet_published_presentation_payloads
        if "camera" in payload
    ]


def _capture_publishes(tab: MeshEditorTab) -> None:
    """Record the payloads that actually go on the wire.

    Not the retained snapshot: the whole point of the fix is that the two now
    differ, so a test reading the snapshot would be blind to what was sent.
    """
    tab.standalone_dotnet_published_presentation_payloads = []
    controller = tab._active_shared_dotnet_controller()
    original = controller.send_correlated

    def record(event: str, payload: dict[str, object]) -> int:
        if event == "presentation_state_update":
            tab.standalone_dotnet_published_presentation_payloads.append(dict(payload))
        return original(event, payload)

    controller.send_correlated = record


def _send_and_acknowledge(tab: MeshEditorTab, state: dict[str, object]) -> None:
    """Send one presentation update and let it settle.

    A publish waits for its acknowledgement before the next one goes out, and
    the fake process never sends one. Without clearing the pending slot every
    send after the first is merely queued, and a test that skipped this would
    pass because nothing was republished at all rather than because the camera
    was withheld.
    """
    tab._send_dotnet_presentation_state(state)
    tab.standalone_dotnet_presentation_pending = None


def test_a_gizmo_toggle_after_a_camera_command_does_not_replay_the_camera() -> None:
    """The reported failure, as a sequence.

    A camera command lands, the reader then changes something unrelated, and the
    republish that follows must not carry the camera again.
    """
    app, tab, builder, _process = _mounted_tab("MeshEditorCameraNotReset")
    _capture_publishes(tab)

    # A deliberate camera command. This one is allowed to move the viewport.
    _send_and_acknowledge(tab, {"camera": {"yaw": -35.0, "fit_to_view": True}})
    cameras = _published_cameras(tab)
    assert len(cameras) == 1
    assert cameras[0]["yaw"] == -35.0
    # It is stamped, so a helper that already applied it can recognise a replay.
    assert int(cameras[0]["command_generation"]) > 0

    # The retained snapshot keeps it, deliberately: it is the value the next
    # camera is compared against, and dropping it would make an identical
    # camera look like a new command and republish it on every accepted frame.
    # What must not happen is it riding a publish again.
    assert "camera" in tab.standalone_dotnet_presentation_desired

    # Now the reader enables the gizmo. Unrelated to the camera.
    _send_and_acknowledge(tab, {"display": {"gizmo_visible": True}})
    published_before = len(tab.standalone_dotnet_published_presentation_payloads)
    assert _published_cameras(tab) == cameras, "the gizmo toggle replayed the camera"

    # And a few more unrelated republishes, of the kinds that actually fire.
    _send_and_acknowledge(tab, {"display": {"grid_visible": False}})
    _send_and_acknowledge(tab, {"display": {"part_pick_enabled": True}})
    _send_and_acknowledge(tab, {"highlights": {"source_indices": [1]}})
    assert _published_cameras(tab) == cameras
    # The republishes really did happen, so the assertion above means the camera
    # was withheld rather than that nothing was sent.
    assert len(tab.standalone_dotnet_published_presentation_payloads) > published_before

    app.processEvents()
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_a_second_camera_command_is_still_honoured() -> None:
    """Dropping the retained camera must not make the camera unmovable."""
    app, tab, builder, _process = _mounted_tab("MeshEditorCameraStillMoves")
    _capture_publishes(tab)

    _send_and_acknowledge(tab, {"camera": {"yaw": -35.0}})
    _send_and_acknowledge(tab, {"display": {"gizmo_visible": True}})
    _send_and_acknowledge(tab, {"camera": {"yaw": 90.0}})

    cameras = _published_cameras(tab)
    assert [camera["yaw"] for camera in cameras] == [-35.0, 90.0]
    # Each command gets its own generation, so the helper applies both.
    assert cameras[0]["command_generation"] != cameras[1]["command_generation"]

    app.processEvents()
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()
