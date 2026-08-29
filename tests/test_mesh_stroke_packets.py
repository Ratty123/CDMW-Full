from __future__ import annotations

from collections.abc import Mapping

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.ui.mesh_editor.stroke_packets import (
    STROKE_MAX_PACKET_BYTES,
    STROKE_MAX_SAMPLES_PER_PACKET,
    bound_live_stroke_command,
    cancel_live_stroke_command,
    carry_live_stroke_segment_boundary,
    command_for_live_stroke_apply,
    encoded_stroke_command_bytes,
    merge_live_stroke_commands,
)


def _drag_command(points: list[tuple[float, float]], *, blob: str = "") -> MeshEditCommand:
    params: dict[str, object] = {
        "stroke_id": "drag-a",
        "screen_drag": {
            "start_x": points[0][0],
            "start_y": points[0][1],
            "end_x": points[-1][0],
            "end_y": points[-1][1],
            "viewport_width": 1920,
            "viewport_height": 1080,
        },
        "screen_path": tuple({"x": x, "y": y} for x, y in points),
    }
    if blob:
        params["blob"] = blob
    return MeshEditCommand("brush", params=params)


def _selection_command(points: list[tuple[float, float]], *, operation: str = "replace") -> MeshEditCommand:
    brushes = [
        {
            "x": x,
            "y": y,
            "radius_pixels": 8.0,
            "viewport_width": 1920,
            "viewport_height": 1080,
            "world_view_projection": [1.0] * 16,
        }
        for x, y in points
    ]
    return MeshEditCommand(
        "select",
        params={
            "selection_stroke_id": "selection-a",
            "selection_stroke_phase": "update",
            "selection_stroke_sequence": len(points),
            "operation": operation,
            "record_history": False,
            "_native_screen_selection_payload": {
                "target_mode": "vertex",
                "selection_depth_mode": "visible",
                "screen_brushes": brushes,
            },
        },
    )


def _selection_region(command: MeshEditCommand) -> Mapping[str, object]:
    screen = command.params["_native_screen_selection_payload"]
    assert isinstance(screen, Mapping)
    region = screen.get("screen_region")
    if not isinstance(region, Mapping):
        regions = screen.get("screen_regions")
        if isinstance(regions, (tuple, list)) and regions:
            region = regions[-1]
    assert isinstance(region, Mapping)
    return region


def test_large_drag_path_is_bounded_and_keeps_endpoints() -> None:
    points = [(float(index), float(index % 2) * 10.0) for index in range(2400)]

    built = bound_live_stroke_command(
        _drag_command(points),
        source="dotnet",
        timestamp_seconds=3.0,
    )

    path = built.command.params["screen_path"]
    assert isinstance(path, tuple)
    assert len(path) <= STROKE_MAX_SAMPLES_PER_PACKET
    assert path[0] == {"x": 0.0, "y": 0.0}
    assert path[-1] == {"x": 2399.0, "y": 10.0}
    assert built.encoded_bytes <= STROKE_MAX_PACKET_BYTES
    assert built.raw_samples == 2400
    assert built.overflowed


def test_2400_brush_dabs_become_one_bounded_swept_region() -> None:
    points = [(float(index), 20.0) for index in range(2400)]

    built = bound_live_stroke_command(
        _selection_command(points),
        source="dotnet_selection",
        timestamp_seconds=3.0,
    )

    region = _selection_region(built.command)
    retained = region["points"]
    assert isinstance(retained, list)
    assert len(retained) < 60
    assert retained[0] == [0.0, 20.0]
    assert retained[-1] == [2399.0, 20.0]
    assert "screen_brushes" not in built.command.params["_native_screen_selection_payload"]  # type: ignore[operator]
    assert built.encoded_bytes <= STROKE_MAX_PACKET_BYTES


def test_merge_reports_overflow_for_a_segment_boundary() -> None:
    first = _selection_command(
        [(float(index), float(index % 2) * 10.0) for index in range(256)]
    )
    newest = _selection_command([(256.0, 0.0)])

    merged = merge_live_stroke_commands(
        first,
        newest,
        source="dotnet_selection",
        timestamp_seconds=1.0,
    )

    assert merged.retained_samples <= STROKE_MAX_SAMPLES_PER_PACKET
    assert merged.overflowed


def test_segment_boundary_preserves_continuity_and_changes_replace_to_add() -> None:
    previous = _selection_command([(0.0, 0.0), (10.0, 0.0)], operation="replace")
    newest = _selection_command([(20.0, 0.0)], operation="replace")

    carried = carry_live_stroke_segment_boundary(
        previous,
        newest,
        source="dotnet_selection",
        timestamp_seconds=1.0,
    )

    region = _selection_region(carried.command)
    assert region["points"] == [[10.0, 0.0], [20.0, 0.0]]
    assert carried.command.params["operation"] == "add"


def test_toggle_segment_does_not_repeat_the_boundary_sample() -> None:
    previous = _selection_command([(0.0, 0.0), (10.0, 0.0)], operation="toggle")
    newest = _selection_command([(20.0, 0.0)], operation="toggle")

    carried = carry_live_stroke_segment_boundary(
        previous,
        newest,
        source="dotnet_selection",
        timestamp_seconds=1.0,
    )

    screen = carried.command.params["_native_screen_selection_payload"]
    assert isinstance(screen, Mapping)
    region = _selection_region(carried.command)
    assert region["points"] == [[20.0, 0.0]]


def test_impossible_metadata_only_packet_is_rejected() -> None:
    built = bound_live_stroke_command(
        _drag_command([(0.0, 0.0), (1.0, 1.0)], blob="x" * (STROKE_MAX_PACKET_BYTES + 1)),
        source="dotnet",
        timestamp_seconds=1.0,
    )

    assert built.too_large
    assert built.encoded_bytes > STROKE_MAX_PACKET_BYTES


def test_impossible_explicit_selection_packet_is_rejected() -> None:
    command = _drag_command([(0.0, 0.0), (1.0, 1.0)])
    command = MeshEditCommand(
        command.action,
        selection=MeshEditSelection.from_maps(vertices_by_submesh={0: range(20_000)}),
        params=command.params,
    )

    built = bound_live_stroke_command(
        command,
        source="dotnet",
        timestamp_seconds=1.0,
    )

    assert built.too_large
    assert built.encoded_bytes > STROKE_MAX_PACKET_BYTES


def test_dispatcher_metadata_is_removed_before_service_apply() -> None:
    built = bound_live_stroke_command(
        _drag_command([(0.0, 0.0), (1.0, 1.0)]),
        source="dotnet",
        timestamp_seconds=1.0,
    )

    clean = command_for_live_stroke_apply(built.command)

    assert all(not str(key).startswith("_dispatcher_") for key in clean.params)
    assert encoded_stroke_command_bytes(clean) == built.encoded_bytes


def test_oversize_terminal_can_fall_back_to_a_minimal_correlated_cancel() -> None:
    command = _selection_command([(0.0, 0.0)])
    params = {**command.params, "blob": "x" * (STROKE_MAX_PACKET_BYTES + 1)}
    params["selection_stroke_phase"] = "end"
    terminal = MeshEditCommand("select", params=params)

    cancelled = cancel_live_stroke_command(terminal, source="dotnet_selection")
    built = bound_live_stroke_command(
        cancelled,
        source="dotnet_selection",
        timestamp_seconds=1.0,
    )

    assert not built.too_large
    assert built.command.params["selection_stroke_id"] == "selection-a"
    assert built.command.params["selection_stroke_phase"] == "cancel"
    assert built.command.params["record_history"] is False


def test_cancel_live_stroke_command_uses_morph_phase_contract() -> None:
    terminal = MeshEditCommand(
        "morph_change",
        params={
            "definition_id": "waist",
            "value": 0.75,
            "phase": "end",
            "change_id": "change-4",
        },
    )

    cancelled = cancel_live_stroke_command(terminal, source="dotnet_morph")

    assert cancelled.params == {
        "definition_id": "waist",
        "value": 0.75,
        "phase": "cancel",
        "change_id": "change-4",
        "record_history": False,
    }
