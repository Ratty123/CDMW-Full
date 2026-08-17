"""A gizmo drag reaches the host with the transform the renderer actually sent.

The renderer emits `placement_transform_request` with the transform nested under
`placement`. The host read `translation` at the top level, found nothing, and
fell back to (0, 0, 0) -- so every drag reported no movement at all. The viewport
still moved, because it transforms its own scene locally, and then the host
applied its zero on release. To a reader the part followed the mouse and snapped
back the instant they let go.

Rotate was worse: the host has `alignment_rotation_changed` and
`alignment_rotation_finished`, and the Builder connects handlers to both, but
nothing ever emitted them.
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from cdmw.ui.preview.dotnet_host_protocol import DotNetPreviewHostProtocolMixin


class _Signal:
    def __init__(self) -> None:
        self.emissions: list[tuple] = []

    def emit(self, *args: object) -> None:
        self.emissions.append(args)


class _Host(DotNetPreviewHostProtocolMixin):
    """The protocol mixin with only the collaborators this event touches."""

    def __init__(self) -> None:
        self.alignment_drag_started = _Signal()
        self.alignment_drag_changed = _Signal()
        self.alignment_drag_finished = _Signal()
        self.alignment_rotation_changed = _Signal()
        self.alignment_rotation_finished = _Signal()
        self.renderer_event_received = _Signal()
        self.native_event_received = _Signal()
        # The mixin suppresses these compatibility signals when a Mesh
        # Editor tab has claimed the controller. A standalone host has not,
        # which is the path under test.
        self.controller = SimpleNamespace()


def _placement(translation=(1.5, -2.0, 3.25), rotation=(10.0, 20.0, 30.0), scale=(1.0, 1.0, 1.0)):
    return {
        "translation": list(translation),
        "rotation_degrees": list(rotation),
        "scale": list(scale),
    }


def _dispatch(host: _Host, *, phase: str, tool: str = "move", placement=None) -> None:
    host._handle_protocol_event(
        {
            "event": "placement_transform_request",
            "placement": _placement() if placement is None else placement,
            "placement_phase": phase,
            "gizmo_tool": tool,
            "gizmo_handle": "x",
        }
    )


def test_a_move_drag_reports_the_translation_the_renderer_sent() -> None:
    host = _Host()

    _dispatch(host, phase="update")

    assert host.alignment_drag_changed.emissions == [(1.5, -2.0, 3.25)]


def test_releasing_a_move_drag_keeps_the_dragged_position() -> None:
    # The regression: this reported (0, 0, 0) and the part snapped home.
    host = _Host()

    _dispatch(host, phase="end")

    assert host.alignment_drag_finished.emissions == [(1.5, -2.0, 3.25)]
    assert host.alignment_drag_finished.emissions != [(0.0, 0.0, 0.0)]


def test_begin_announces_the_drag_without_a_transform() -> None:
    host = _Host()

    _dispatch(host, phase="begin")

    assert host.alignment_drag_started.emissions == [()]
    assert host.alignment_drag_changed.emissions == []
    assert host.alignment_drag_finished.emissions == []


@pytest.mark.parametrize("phase,expected", [("update", "changed"), ("end", "finished")])
def test_a_rotate_drag_uses_the_rotation_signals(phase: str, expected: str) -> None:
    host = _Host()

    _dispatch(host, phase=phase, tool="rotate")

    rotation = getattr(host, f"alignment_rotation_{expected}")
    assert rotation.emissions == [(10.0, 20.0, 30.0)]
    # Rotation must not also arrive as a translation, which would move the part.
    assert host.alignment_drag_changed.emissions == []
    assert host.alignment_drag_finished.emissions == []


def test_a_scale_drag_emits_nothing_rather_than_the_wrong_axis() -> None:
    # No scale signal exists and no Builder handler consumes one. Emitting a
    # translation here would apply an unrelated transform; leaving it unwired
    # is a gap, and a wrong emission would be a bug.
    host = _Host()

    for phase in ("begin", "update", "end"):
        _dispatch(host, phase=phase, tool="scale")

    assert host.alignment_drag_started.emissions == []
    assert host.alignment_drag_changed.emissions == []
    assert host.alignment_drag_finished.emissions == []
    assert host.alignment_rotation_changed.emissions == []


def test_a_payload_with_no_placement_falls_back_without_raising() -> None:
    host = _Host()

    host._handle_protocol_event(
        {
            "event": "placement_transform_request",
            "placement_phase": "end",
            "gizmo_tool": "move",
        }
    )

    assert host.alignment_drag_finished.emissions == [(0.0, 0.0, 0.0)]


def test_a_short_translation_falls_back_rather_than_unpacking_wrongly() -> None:
    host = _Host()

    _dispatch(host, phase="end", placement={"translation": [1.0, 2.0]})

    assert host.alignment_drag_finished.emissions == [(0.0, 0.0, 0.0)]
