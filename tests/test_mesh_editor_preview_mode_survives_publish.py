"""A Mesh view chosen on the resident rail must survive the next presentation publish.

The display mode reaches the helper down two channels. `viewport_display_update`
is the one the rail's own Preview mode combo drives; the presentation snapshot is
the other, and it is republished after every accepted scene frame, every part
highlight and every armed tool. The snapshot the host keeps is a merged record,
so a partial update that carries no mode of its own still publishes whatever mode
that record last held.

Leaving the record on the old mode is what made "Solid (Textured)" revert the
moment anything else happened: Wire + Vertices back in Edit Mesh, Faces + Wire
back in placement, both from a publish the reader never asked for.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor import MeshEditorTab
from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    MESH_PREVIEW_DISPLAY_MODES,
)
from tests.test_mesh_editor_action_bar import (
    _EmbeddedMeshBuilder,
    _FakeProcess,
    _install_shared_dotnet_test_process,
)


def _mounted_tab(name: str):
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", name))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2", "viewport_display_modes_v1"),
        session_id=builder.controller.session_view().session_id,
    )
    setattr(builder, "_mesh_editor_embedded_dotnet_active", True)
    return app, tab, builder, process


def _presentation_publishes(process: _FakeProcess) -> list[dict]:
    return [
        payload
        for payload in (json.loads(raw.decode("utf-8")) for raw in process.stdin_writes)
        if payload.get("event") == "presentation_state_update"
    ]


def _published_display_modes(process: _FakeProcess) -> list[str]:
    modes: list[str] = []
    for payload in _presentation_publishes(process):
        display = payload.get("display")
        if isinstance(display, dict) and "mode" in display:
            modes.append(str(display["mode"]))
    return modes


def _acknowledge_latest_publish(tab: MeshEditorTab, process: _FakeProcess) -> None:
    """Answer the publish the helper is holding, so the next one can go out."""
    latest = _presentation_publishes(process)[-1]
    tab._handle_dotnet_presentation_state_ack(
        {
            "event": "presentation_state_applied",
            "status": "applied",
            "session_id": latest["session_id"],
            "request_id": latest["request_id"],
            "process_generation": latest["process_generation"],
        }
    )


def test_a_rail_mode_choice_is_carried_by_the_next_presentation_publish() -> None:
    app, tab, builder, process = _mounted_tab("MeshEditorPreviewModeSurvivesPublish")

    # The state the host is holding when Edit Mesh opens.
    assert tab._send_dotnet_presentation_state({"display": {"mode": "wire_vertices"}})
    assert _published_display_modes(process)[-1] == "wire_vertices"
    _acknowledge_latest_publish(tab, process)

    # The reader picks a mode on the resident rail. That travels as its own
    # message, not as a presentation snapshot.
    assert tab._handle_embedded_viewport_display_mode("untextured_faces")

    # Anything that republishes the snapshot without naming a mode -- a part
    # highlight is the everyday one -- must not put the old mode back.
    assert tab._send_dotnet_presentation_state(
        {"display": {"grid_visible": True}, "highlights": {"source_indices": [0]}}
    )
    assert _published_display_modes(process)[-1] == "untextured_faces"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("mode", MESH_PREVIEW_DISPLAY_MODES)
def test_every_display_mode_survives_selection_tool_scene_material_and_visibility_publishes(
    mode: str,
) -> None:
    app, tab, builder, process = _mounted_tab(f"MeshModeAuthority-{mode}")
    try:
        tab.standalone_dotnet_material_generation_by_role["editable_imported"] = 1
        tab.standalone_dotnet_completed_material_generation_by_role["editable_imported"] = 1
        tab.standalone_dotnet_applied_material_generation_by_role["editable_imported"] = 1
        tab.standalone_dotnet_texture_resources_ready_by_role["editable_imported"] = True

        assert tab._send_dotnet_presentation_state({"display": {"mode": "wire_vertices"}})
        _acknowledge_latest_publish(tab, process)
        assert tab._handle_embedded_viewport_display_mode(mode)

        transition_updates = (
            {"highlights": {"source_indices": [0]}},
            {"display": {"grid_visible": False}},
            {"camera": {"yaw": 0.2, "pitch": -0.1, "distance": 3.0}},
            {"visibility": {"hidden_source_indices": [1]}},
            {"comparison_mode": "replacement_only"},
        )
        for update in transition_updates:
            assert tab._send_dotnet_presentation_state(update)
            assert _published_display_modes(process)[-1] == mode
            _acknowledge_latest_publish(tab, process)
    finally:
        tab.deleteLater()
        builder.deleteLater()
        app.processEvents()
