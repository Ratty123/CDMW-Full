"""Regression coverage for the Edit Mesh stroke protocol path.

A live brush or move stroke reports one protocol message per sampled mouse move,
and each message carries a projection matrix per editable submesh. On a
multi-part model that burst is large enough to arrive in a single read, which
used to trip the host's input-buffer guard and stop the resident .NET editor
mid-stroke. It also used to be possible for a stroke to outlive the tool that
opened it and report a tool the host cannot execute.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.process_io import DOTNET_PROTOCOL_BUFFER_LIMIT
from cdmw.ui.mesh_editor.tab import MeshEditorTab

DOTNET_EDITOR = Path(__file__).resolve().parents[1] / "tools" / "dotnet_mesh_editor_experiment"


def dotnet_experiment_source(name: str) -> str:
    return (DOTNET_EDITOR / name).read_text(encoding="utf-8")


class _StdoutProcess:
    """Minimal QProcess stand-in that yields one scripted stdout chunk."""

    def __init__(self, chunk: bytes) -> None:
        self._chunk = chunk

    def readAllStandardOutput(self) -> bytes:
        chunk, self._chunk = self._chunk, b""
        return chunk


def _tab_for_stdout(name: str) -> MeshEditorTab:
    tab = MeshEditorTab(settings=QSettings("CDMWTests", name))
    tab.standalone_dotnet_protocol_stdout = ""
    return tab


def _stroke_line(index: int, submesh_count: int) -> bytes:
    matrix = [float(index)] * 16
    projections = [
        {"source_submesh_index": submesh, "world_view_projection": matrix}
        for submesh in range(submesh_count)
    ]
    screen = {
        "x": index,
        "y": index,
        "radius": 24.0,
        "viewport_width": 800,
        "viewport_height": 600,
        "world_view_projection": matrix,
        "source_submesh_indices": list(range(submesh_count)),
        "source_submesh_world_view_projections": projections,
    }
    payload = {
        "event": "stroke_update",
        "tool": "grab",
        "stroke_id": "1",
        "screen_brush": screen,
        "screen_drag": dict(screen, start_x=0, start_y=0, end_x=index, end_y=index),
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


def test_a_large_burst_of_complete_stroke_messages_does_not_stop_the_editor() -> None:
    QApplication.instance() or QApplication([])
    tab = _tab_for_stdout("MeshDotNetStrokeBurst")

    chunk = b""
    index = 0
    while len(chunk) <= DOTNET_PROTOCOL_BUFFER_LIMIT:
        index += 1
        chunk += _stroke_line(index, submesh_count=40)
    assert len(chunk) > DOTNET_PROTOCOL_BUFFER_LIMIT

    process = _StdoutProcess(chunk)
    tab.standalone_dotnet_editor_process = process  # type: ignore[assignment]
    stopped: list[object] = []
    handled: list[str] = []
    tab._stop_standalone_dotnet_editor_process = (  # type: ignore[method-assign]
        lambda *args, **kwargs: stopped.append((args, kwargs))
    )
    tab._handle_dotnet_protocol_line = (  # type: ignore[method-assign]
        lambda line: handled.append(line) or True
    )

    tab._handle_dotnet_protocol_stdout_ready(process)

    assert not stopped, "a burst of well-formed stroke messages must not stop the editor"
    assert len(handled) == index
    assert tab.standalone_dotnet_protocol_stdout == ""
    tab.deleteLater()


def test_an_unterminated_message_past_the_buffer_limit_still_stops_the_editor() -> None:
    QApplication.instance() or QApplication([])
    tab = _tab_for_stdout("MeshDotNetRunawayBuffer")

    process = _StdoutProcess(b"{" + b"x" * (DOTNET_PROTOCOL_BUFFER_LIMIT + 16))
    tab.standalone_dotnet_editor_process = process  # type: ignore[assignment]
    stopped: list[object] = []
    tab._stop_standalone_dotnet_editor_process = (  # type: ignore[method-assign]
        lambda *args, **kwargs: stopped.append((args, kwargs))
    )

    tab._handle_dotnet_protocol_stdout_ready(process)

    assert stopped, "an unterminated message must still trip the input-buffer guard"
    assert tab.standalone_dotnet_protocol_stdout == ""
    tab.deleteLater()


def test_helper_pins_the_stroke_tool_and_paces_stroke_updates() -> None:
    input_source = dotnet_experiment_source("MeshViewport.Input.cs")
    runtime_source = dotnet_experiment_source("ExperimentForm.Runtime.cs")

    # Only stroke tools may open a stroke, and update/end report the tool the
    # stroke opened with rather than whatever is active by then.
    assert "private static readonly HashSet<string> StrokeTools" in input_source
    assert "IsStrokeTool(ActiveTool)" in input_source
    assert "private string _strokeTool" in input_source
    assert 'StrokePointerPayload(e.Location, _strokePrevious)' in input_source
    assert "toolOverride: _strokeTool" in input_source

    # A gesture that loses its mouse-up must not leave the stroke open.
    assert "EndEditorStroke(e.Location, cancelled: false)" in input_source
    assert "internal void CancelActiveStroke()" in input_source
    assert "protected override void OnLostFocus" in input_source

    # Intermediate samples coalesce; the phases that carry meaning do not.
    assert "StrokeUpdateProtocolIntervalMs" in runtime_source
    assert "_pendingStrokeUpdatePayload" in runtime_source
    assert 'eventName is "stroke_begin" or "stroke_end" or "stroke_cancel"' in runtime_source

    # Each sample's screen_drag is motion since the previous sample, so
    # coalescing has to carry the older start point forward or the dropped
    # samples' pointer motion is lost. The terminal phase absorbs the residue.
    coalesce = runtime_source.split(
        "private static Dictionary<string, object?> CoalesceStrokeSample", maxsplit=1
    )[1].split("private void FlushPendingStrokeUpdate", maxsplit=1)[0]
    assert '"start_x", "start_y"' in coalesce
    assert 'merged["screen_drag"] = drag;' in coalesce
    assert "var terminal = CoalesceStrokeSample(_pendingStrokeUpdatePayload, payload);" in runtime_source


def test_every_reported_viewport_control_notifies_view_state() -> None:
    """Controls that change reported view state must tell the host.

    PresentationStatusPayload carries display_mode, xray, textures_enabled,
    part_pick_enabled, zoom and pan. Camera drags reported their changes but
    Reset/Fit, the preview mode combo, X-Ray and Part Pick did not, so the host
    kept a stale mirror to restore from.
    """
    display_source = dotnet_experiment_source("MeshViewport.DisplayModes.cs")
    topology_source = dotnet_experiment_source("MeshViewport.Topology.cs")
    program_source = dotnet_experiment_source("Program.cs")
    presentation_source = dotnet_experiment_source("MeshViewport.Presentation.cs")

    for field in ("display_mode", "xray", "textures_enabled", "part_pick_enabled"):
        assert f'["{field}"]' in presentation_source

    set_xray = display_source.split("public void SetXRayEnabled", maxsplit=1)[1]
    set_xray = set_xray.split("public bool TrySetDisplayMode", maxsplit=1)[0]
    assert "NotifyViewStateChanged();" in set_xray

    set_mode = display_source.split("public bool TrySetDisplayMode", maxsplit=1)[1]
    assert "NotifyViewStateChanged();" in set_mode

    frame_mesh = topology_source.split("public void FrameMesh()", maxsplit=1)[1]
    frame_mesh = frame_mesh.split("private static void ReplaceSelectionMap", maxsplit=1)[0]
    assert "NotifyViewStateChanged();" in frame_mesh

    part_pick = program_source.split("public bool PartPickEnabled", maxsplit=1)[1]
    part_pick = part_pick.split("public bool TexturesEnabled", maxsplit=1)[0]
    assert "NotifyViewStateChanged();" in part_pick


def test_layout_transitions_paint_once_instead_of_step_by_step() -> None:
    redraw_source = dotnet_experiment_source("ExperimentForm.Redraw.cs")
    layouts_source = dotnet_experiment_source("ExperimentForm.EditMeshLayouts.cs")
    program_source = dotnet_experiment_source("Program.cs")

    # SuspendLayout defers measurement but not painting, so the batch has to
    # hold WM_SETREDRAW and force one settled repaint on release.
    assert "WmSetRedraw" in redraw_source
    assert "_control.PerformLayout()" not in redraw_source
    assert "_form.PerformLayout();" in redraw_source
    assert "_form.Invalidate(invalidateChildren: true);" in redraw_source
    assert "_form.Update();" in redraw_source

    # Nested batches must not thaw the window early.
    assert "_redrawBatchDepth" in redraw_source
    assert "if (_form._redrawBatchDepth++ == 0)" in redraw_source
    assert "if (--_form._redrawBatchDepth > 0)" in redraw_source

    # Every path that re-parents live sections holds a batch: both layout
    # activations, and the deferred authoring panel build that runs after the
    # editor's first frame is already on screen.
    tool_rail = layouts_source.split("private void ActivateToolRailLayout()", maxsplit=1)[1]
    tool_rail = tool_rail.split("private void ActivateClassicEditMeshLayout()", maxsplit=1)[0]
    classic = layouts_source.split("private void ActivateClassicEditMeshLayout()", maxsplit=1)[1]
    classic = classic.split("private void MoveSessionControlsToCompactBar()", maxsplit=1)[0]
    deferred = program_source.split("private void EnsureAuthoringToolPanelsReady()", maxsplit=1)[1]
    deferred = deferred.split("private (Panel Left, Panel Right) BuildToolPanels()", maxsplit=1)[0]
    for name, body in (("tool rail", tool_rail), ("classic", classic), ("deferred", deferred)):
        assert "BeginRedrawBatch()" in body, f"{name} activation must batch its repaint"
