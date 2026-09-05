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
from cdmw.ui.mesh_editor.tab_dotnet_payloads import MeshEditorDotNetPayloadMixin

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


class _ScreenSelectionPayloadHarness(MeshEditorDotNetPayloadMixin):
    @staticmethod
    def _native_screen_payload(payload: object) -> dict[object, object]:
        assert isinstance(payload, dict)
        return dict(payload)


def test_edit_mesh_screen_selection_never_promotes_a_viewport_hit_to_a_part() -> None:
    owner = object.__new__(_ScreenSelectionPayloadHarness)
    payload = {
        "screen_brush": {"x": 10, "y": 20, "radius": 24.0},
        "selection_depth_mode": "visible",
    }

    for target_mode in ("vertex", "edge", "face"):
        result = owner._dotnet_screen_selection_payload(
            dict(payload, target_mode=target_mode)
        )
        assert result["target_mode"] == target_mode

    for stale_part_target in ("source", "part", ""):
        result = owner._dotnet_screen_selection_payload(
            dict(payload, target_mode=stale_part_target)
        )
        assert result["target_mode"] == "vertex"


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
