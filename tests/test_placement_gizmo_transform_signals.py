"""A gizmo drag reaches the host as the delta its consumers expect.

The renderer emits `placement_transform_request` with the *absolute* placement
nested under `placement`. Every consumer of the host's drag signals -- the
Builder's drag transaction, the attachment safe-placement dialog -- adds what it
receives to a base it captured when the drag started, so the contract is a
delta. Two faults met here.

The host read `translation` at the top level, found nothing, and fell back to
(0, 0, 0): every drag reported no movement, the viewport followed the mouse from
its own local transform, and the host applied zero on release, so the part
snapped home. Rotate was never routed at all. And the first correction passed the
absolute where a delta was expected, which is right only for the first drag from
the origin and puts a part at base+absolute on every drag after.

The renderer now emits a `begin` sample carrying the exact start placement, and
the host subtracts it. Scale rides the same path, with its own signals.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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
        self.alignment_scale_changed = _Signal()
        self.alignment_scale_finished = _Signal()
        self.renderer_event_received = _Signal()
        self.native_event_received = _Signal()
        # The mixin suppresses these compatibility signals when a Mesh Editor
        # tab has claimed the controller. A standalone host has not.
        self.controller = SimpleNamespace()


def _placement(translation=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)):
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


def _drag(host: _Host, tool: str, key: str, start, *samples):
    """A begin sample, then updates, then an end at the last sample."""
    _dispatch(host, phase="begin", tool=tool, placement={key: list(start)})
    for sample in samples[:-1]:
        _dispatch(host, phase="update", tool=tool, placement={key: list(sample)})
    _dispatch(host, phase="end", tool=tool, placement={key: list(samples[-1])})


def test_a_move_drag_reports_the_delta_from_where_it_began() -> None:
    host = _Host()

    _drag(host, "move", "translation", (0.0, 5.0, 0.0), (0.0, 5.5, 0.0), (1.5, 3.0, 3.25))

    assert host.alignment_drag_started.emissions == [()]
    assert host.alignment_drag_changed.emissions == [(0.0, 0.5, 0.0)]
    assert host.alignment_drag_finished.emissions == [(1.5, -2.0, 3.25)]


def test_a_second_drag_is_relative_to_its_own_start_not_the_origin() -> None:
    # The regression the first correction introduced: passing the absolute
    # placement as a delta put a part at base+absolute on every drag after the
    # first. Each drag must report only what happened during it.
    host = _Host()

    _drag(host, "move", "translation", (0.0, 0.0, 0.0), (0.0, 0.077, 0.0))
    _drag(host, "move", "translation", (0.0, 0.077, 0.0), (0.0, 0.24, 0.0))

    finished = host.alignment_drag_finished.emissions
    assert [round(value, 3) for value in finished[0]] == [0.0, 0.077, 0.0]
    assert [round(value, 3) for value in finished[1]] == [0.0, 0.163, 0.0]


def test_releasing_where_the_drag_began_reports_no_movement() -> None:
    host = _Host()

    _drag(host, "move", "translation", (2.0, 2.0, 2.0), (2.0, 2.0, 2.0))

    assert host.alignment_drag_finished.emissions == [(0.0, 0.0, 0.0)]


@pytest.mark.parametrize("phase,expected", [("update", "changed"), ("end", "finished")])
def test_a_rotate_drag_uses_the_rotation_signals(phase: str, expected: str) -> None:
    host = _Host()

    _dispatch(host, phase="begin", tool="rotate", placement={"rotation_degrees": [0.0, 90.0, 0.0]})
    _dispatch(host, phase=phase, tool="rotate", placement={"rotation_degrees": [10.0, 110.0, 30.0]})

    rotation = getattr(host, f"alignment_rotation_{expected}")
    assert rotation.emissions == [(10.0, 20.0, 30.0)]
    # Rotation must not also arrive as a translation, which would move the part.
    assert host.alignment_drag_changed.emissions == []
    assert host.alignment_drag_finished.emissions == []


@pytest.mark.parametrize("phase,expected", [("update", "changed"), ("end", "finished")])
def test_a_scale_drag_uses_the_scale_signals(phase: str, expected: str) -> None:
    host = _Host()

    _dispatch(host, phase="begin", tool="scale", placement={"scale": [1.0, 1.0, 1.0]})
    _dispatch(host, phase=phase, tool="scale", placement={"scale": [1.5, 1.0, 0.75]})

    scale = getattr(host, f"alignment_scale_{expected}")
    assert scale.emissions == [(0.5, 0.0, -0.25)]
    assert host.alignment_drag_changed.emissions == []
    assert host.alignment_rotation_changed.emissions == []


def test_a_scale_drag_missing_its_start_falls_back_to_a_neutral_scale() -> None:
    # No begin and no scale in the payload: the fallback start for scale is
    # (1, 1, 1), not (0, 0, 0), or a missing sample would read as a collapse.
    host = _Host()

    _dispatch(host, phase="end", tool="scale", placement={})

    assert host.alignment_scale_finished.emissions == [(0.0, 0.0, 0.0)]


def test_an_older_helper_that_sends_no_begin_still_gets_a_start() -> None:
    # The first sample becomes the start. It may already carry one pointer
    # step, which is why the renderer now sends begin; this is the fallback.
    host = _Host()

    _dispatch(host, phase="update", tool="move", placement={"translation": [0.0, 0.079, 0.0]})
    _dispatch(host, phase="end", tool="move", placement={"translation": [0.0, 0.24, 0.0]})

    assert host.alignment_drag_started.emissions == [()]
    assert [round(value, 3) for value in host.alignment_drag_finished.emissions[0]] == [0.0, 0.161, 0.0]


def test_a_short_translation_falls_back_rather_than_unpacking_wrongly() -> None:
    host = _Host()

    _dispatch(host, phase="begin", tool="move", placement={"translation": [0.0, 0.0, 0.0]})
    _dispatch(host, phase="end", tool="move", placement={"translation": [1.0, 2.0]})

    assert host.alignment_drag_finished.emissions == [(0.0, 0.0, 0.0)]


def test_tools_keep_independent_starts() -> None:
    host = _Host()

    _dispatch(host, phase="begin", tool="move", placement={"translation": [1.0, 0.0, 0.0]})
    _dispatch(host, phase="begin", tool="scale", placement={"scale": [2.0, 2.0, 2.0]})
    _dispatch(host, phase="end", tool="scale", placement={"scale": [3.0, 2.0, 2.0]})
    _dispatch(host, phase="end", tool="move", placement={"translation": [1.0, 4.0, 0.0]})

    assert host.alignment_scale_finished.emissions == [(1.0, 0.0, 0.0)]
    assert host.alignment_drag_finished.emissions == [(0.0, 4.0, 0.0)]


def test_the_embedded_builder_applies_a_scale_gizmo_drag_to_its_scale_spins() -> None:
    """The path the embedded Mesh Editor actually takes.

    When a Mesh Editor tab owns the controller, the compatibility signals above
    are suppressed and the tab hands the absolute placement to the Builder's
    `_mesh_editor_apply_dotnet_placement_state`. That is where a scale drag
    lands in practice, so it is driven on a real Builder: an update moves the
    scale spins and publishes nothing, and the end publishes the frame.
    """
    from tests.mesh_builder_driver import open_mesh_builder

    with open_mesh_builder(dialog_title="Scale gizmo") as builder:
        apply_placement = getattr(builder.dialog, "_mesh_editor_apply_dotnet_placement_state")
        spins = builder.control("scale_spins")
        timer = builder.control("static_preview_refresh_timer")

        assert apply_placement({"scale": [1.0, 1.0, 1.0]}, phase="begin") is True
        assert apply_placement({"scale": [1.5, 1.0, 0.75]}, phase="update") is True
        assert [round(spin.value(), 3) for spin in spins] == [1.5, 1.0, 0.75]

        assert apply_placement({"scale": [2.0, 1.0, 0.75]}, phase="end") is True
        assert [round(spin.value(), 3) for spin in spins] == [2.0, 1.0, 0.75]
        # The terminal sample queues the rebuild that makes the placement
        # authoritative again; the driver refuses to close over a live timer.
        builder.pump()
        timer.stop()
