"""Bounded native packet construction for Mesh Editor live strokes."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cdmw.domain.mesh import (
    MeshEditCommand,
    MeshEditSelection,
    StrokeSample,
    StrokeSampleBuffer,
    StrokeSampleConfig,
)


STROKE_MAX_SAMPLES_PER_PACKET = 256
STROKE_MAX_PACKET_BYTES = 64 * 1024
STROKE_MAX_SEGMENTS = 16
STROKE_SAMPLE_CONFIG = StrokeSampleConfig(
    max_samples=STROKE_MAX_SAMPLES_PER_PACKET,
    min_spacing_pixels=2.5,
    max_interval_seconds=0.050,
    curvature_degrees=12.0,
)

_INTERNAL_PREFIX = "_dispatcher_"
_DRAG_TIMES = "_dispatcher_drag_sample_times"
_DRAG_RAW_COUNT = "_dispatcher_drag_raw_sample_count"
_SELECTION_TIMES = "_dispatcher_selection_sample_times"
_SELECTION_RAW_COUNT = "_dispatcher_selection_raw_sample_count"


@dataclass(frozen=True, slots=True)
class StrokePacketBuild:
    command: MeshEditCommand
    encoded_bytes: int
    retained_samples: int
    raw_samples: int
    overflowed: bool
    too_large: bool = False


def bound_live_stroke_command(
    command: MeshEditCommand,
    *,
    source: str,
    timestamp_seconds: float,
) -> StrokePacketBuild:
    """Simplify one native command until count and encoded-size limits hold."""

    limit = STROKE_MAX_SAMPLES_PER_PACKET
    last: StrokePacketBuild | None = None
    while True:
        bounded = _bound_command(
            command,
            source=source,
            timestamp_seconds=timestamp_seconds,
            max_samples=limit,
        )
        encoded_bytes = encoded_stroke_command_bytes(bounded.command)
        last = StrokePacketBuild(
            bounded.command,
            encoded_bytes,
            bounded.retained_samples,
            bounded.raw_samples,
            bounded.overflowed,
            too_large=False,
        )
        if encoded_bytes <= STROKE_MAX_PACKET_BYTES and bounded.retained_samples <= STROKE_MAX_SAMPLES_PER_PACKET:
            return last
        if limit <= 2 or bounded.retained_samples <= 2:
            return StrokePacketBuild(
                last.command,
                last.encoded_bytes,
                last.retained_samples,
                last.raw_samples,
                True,
                too_large=True,
            )
        limit = max(2, limit // 2)


def merge_live_stroke_commands(
    previous: MeshEditCommand,
    newest: MeshEditCommand,
    *,
    source: str,
    timestamp_seconds: float,
) -> StrokePacketBuild:
    command = newest
    if source == "dotnet_selection":
        command = _merge_screen_selection(previous, command, timestamp_seconds)
    command = _merge_screen_drag(previous, command, timestamp_seconds)
    return bound_live_stroke_command(
        command,
        source=source,
        timestamp_seconds=timestamp_seconds,
    )


def carry_live_stroke_segment_boundary(
    previous: MeshEditCommand,
    newest: MeshEditCommand,
    *,
    source: str,
    timestamp_seconds: float,
) -> StrokePacketBuild:
    """Start a new segment at the prior endpoint without copying its history."""

    command = newest
    if source == "dotnet_selection":
        command = _carry_selection_boundary(previous, command, timestamp_seconds)
    command = _carry_drag_boundary(previous, command, timestamp_seconds)
    return bound_live_stroke_command(
        command,
        source=source,
        timestamp_seconds=timestamp_seconds,
    )


def continue_selection_terminal(command: MeshEditCommand) -> MeshEditCommand:
    operation = str(command.params.get("operation", "replace") or "replace").strip().lower()
    if operation != "replace":
        return command
    return _replace_command_params(command, {**command.params, "operation": "add"})


def cancel_live_stroke_command(command: MeshEditCommand, *, source: str) -> MeshEditCommand:
    params: dict[str, object] = {"record_history": False}
    if source == "dotnet_selection":
        params.update(
            {
                "selection_stroke_id": command.params.get("selection_stroke_id", ""),
                "selection_stroke_phase": "cancel",
                "selection_stroke_sequence": command.params.get("selection_stroke_sequence", 0),
                "operation": "replace",
            }
        )
    elif source == "dotnet_morph":
        params.update(
            {
                "definition_id": command.params.get("definition_id", ""),
                "value": command.params.get("value", 0.0),
                "phase": "cancel",
                "change_id": command.params.get("change_id", ""),
            }
        )
    else:
        params.update(
            {
                "stroke_id": command.params.get("stroke_id", ""),
                "stroke_phase": "cancel",
            }
        )
    return _replace_command_params(command, params)


def command_for_live_stroke_apply(command: MeshEditCommand) -> MeshEditCommand:
    params = {
        key: value
        for key, value in command.params.items()
        if not str(key).startswith(_INTERNAL_PREFIX)
    }
    return _replace_command_params(command, params)


def encoded_stroke_command_bytes(command: MeshEditCommand) -> int:
    payload = {
        "action": command.action,
        "mode": command.mode,
        "label": command.label,
        "selection": _selection_packet_payload(command.selection),
        "params": {
            key: value
            for key, value in command.params.items()
            if not str(key).startswith(_INTERNAL_PREFIX)
        },
    }
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    )


def _selection_packet_payload(selection: MeshEditSelection | None) -> dict[str, object]:
    if selection is None:
        return {}
    return {
        "source_indices": tuple(selection.source_indices),
        "vertices_by_submesh": {
            int(key): tuple(sorted(values))
            for key, values in selection.vertex_map().items()
        },
        "edges_by_submesh": {
            int(key): tuple(sorted(tuple(edge) for edge in values))
            for key, values in selection.edge_map().items()
        },
        "faces_by_submesh": {
            int(key): tuple(sorted(values))
            for key, values in selection.face_map().items()
        },
    }


def _bound_command(
    command: MeshEditCommand,
    *,
    source: str,
    timestamp_seconds: float,
    max_samples: int,
) -> StrokePacketBuild:
    params = dict(command.params)
    raw_samples = 0
    retained_samples = 0
    overflowed = False

    drag = params.get("screen_drag")
    if isinstance(drag, Mapping):
        points, times, raw_count = _drag_samples(params, drag, timestamp_seconds)
        buffer, did_overflow = _bounded_buffer(points, times, max_samples=max_samples)
        if buffer.retained_count >= 2:
            samples = buffer.samples
            params["screen_drag"] = {
                **dict(drag),
                "start_x": samples[0].x,
                "start_y": samples[0].y,
                "end_x": samples[-1].x,
                "end_y": samples[-1].y,
            }
            params["screen_path"] = tuple(
                {"x": sample.x, "y": sample.y}
                for sample in samples
            )
            params[_DRAG_TIMES] = tuple(sample.timestamp_seconds for sample in samples)
            params[_DRAG_RAW_COUNT] = raw_count
            retained_samples += buffer.retained_count
            raw_samples += raw_count
            overflowed = overflowed or did_overflow

    raw_screen = params.get("_native_screen_selection_payload")
    if isinstance(raw_screen, Mapping):
        screen, screen_retained, screen_raw, screen_overflowed, selection_times = _bound_screen_selection(
            raw_screen,
            params,
            timestamp_seconds=timestamp_seconds,
            max_samples=max_samples,
        )
        params["_native_screen_selection_payload"] = screen
        if selection_times:
            params[_SELECTION_TIMES] = selection_times
            params[_SELECTION_RAW_COUNT] = screen_raw
        retained_samples += screen_retained
        raw_samples += screen_raw
        overflowed = overflowed or screen_overflowed

    return StrokePacketBuild(
        _replace_command_params(command, params),
        0,
        retained_samples,
        raw_samples,
        overflowed,
    )


def _merge_screen_drag(
    previous: MeshEditCommand,
    newest: MeshEditCommand,
    timestamp_seconds: float,
) -> MeshEditCommand:
    previous_stroke_id = str(previous.params.get("stroke_id", "") or "")
    newest_stroke_id = str(newest.params.get("stroke_id", "") or "")
    previous_drag = previous.params.get("screen_drag")
    newest_drag = newest.params.get("screen_drag")
    if (
        not previous_stroke_id
        or previous_stroke_id != newest_stroke_id
        or not isinstance(previous_drag, Mapping)
        or not isinstance(newest_drag, Mapping)
    ):
        return newest
    previous_points, previous_times, previous_raw = _drag_samples(
        previous.params,
        previous_drag,
        timestamp_seconds,
    )
    newest_points, newest_times, newest_raw = _drag_samples(
        newest.params,
        newest_drag,
        timestamp_seconds,
    )
    points, times, duplicate = _join_samples(
        previous_points,
        previous_times,
        newest_points,
        newest_times,
    )
    params = {
        **newest.params,
        "screen_drag": {
            **dict(newest_drag),
            "start_x": points[0][0],
            "start_y": points[0][1],
            "end_x": points[-1][0],
            "end_y": points[-1][1],
        },
        "screen_path": tuple({"x": x, "y": y} for x, y in points),
        _DRAG_TIMES: tuple(times),
        _DRAG_RAW_COUNT: previous_raw + newest_raw - int(duplicate),
    }
    return _replace_command_params(newest, params)


def _merge_screen_selection(
    previous: MeshEditCommand,
    newest: MeshEditCommand,
    timestamp_seconds: float,
) -> MeshEditCommand:
    previous_stroke_id = str(previous.params.get("selection_stroke_id", "") or "")
    newest_stroke_id = str(newest.params.get("selection_stroke_id", "") or "")
    previous_screen = previous.params.get("_native_screen_selection_payload")
    newest_screen = newest.params.get("_native_screen_selection_payload")
    if (
        not previous_stroke_id
        or previous_stroke_id != newest_stroke_id
        or not isinstance(previous_screen, Mapping)
        or not isinstance(newest_screen, Mapping)
    ):
        return newest
    previous_path = _brush_path(previous_screen, previous.params, timestamp_seconds)
    newest_path = _brush_path(newest_screen, newest.params, timestamp_seconds)
    merged_screen = dict(newest_screen)
    if previous_path is not None and newest_path is not None and previous_path[3] == newest_path[3]:
        points, times, duplicate = _join_samples(
            previous_path[0],
            previous_path[1],
            newest_path[0],
            newest_path[1],
        )
        raw_count = previous_path[2] + newest_path[2] - int(duplicate)
        merged_screen = _screen_with_brush_path(merged_screen, newest_path[3], points)
        params = {
            **newest.params,
            "operation": previous.params.get("operation", newest.params.get("operation", "add")),
            "_native_screen_selection_payload": merged_screen,
            _SELECTION_TIMES: tuple(times),
            _SELECTION_RAW_COUNT: raw_count,
        }
        return _replace_command_params(newest, params)

    brushes = _screen_selection_items(previous_screen, "screen_brush", "screen_brushes")
    brushes.extend(_screen_selection_items(newest_screen, "screen_brush", "screen_brushes"))
    regions = _screen_selection_items(previous_screen, "screen_region", "screen_regions")
    regions.extend(_screen_selection_items(newest_screen, "screen_region", "screen_regions"))
    merged_screen.pop("screen_brush", None)
    merged_screen.pop("screen_region", None)
    if brushes:
        merged_screen["screen_brushes"] = brushes
    if regions:
        merged_screen["screen_regions"] = regions
    return _replace_command_params(
        newest,
        {
            **newest.params,
            "operation": previous.params.get("operation", newest.params.get("operation", "add")),
            "_native_screen_selection_payload": merged_screen,
        },
    )


def _carry_drag_boundary(
    previous: MeshEditCommand,
    newest: MeshEditCommand,
    timestamp_seconds: float,
) -> MeshEditCommand:
    previous_drag = previous.params.get("screen_drag")
    newest_drag = newest.params.get("screen_drag")
    if not isinstance(previous_drag, Mapping) or not isinstance(newest_drag, Mapping):
        return newest
    previous_points, previous_times, _raw = _drag_samples(
        previous.params,
        previous_drag,
        timestamp_seconds,
    )
    newest_points, newest_times, newest_raw = _drag_samples(
        newest.params,
        newest_drag,
        timestamp_seconds,
    )
    points, times, duplicate = _join_samples(
        (previous_points[-1],),
        (previous_times[-1],),
        newest_points,
        newest_times,
    )
    params = {
        **newest.params,
        "screen_drag": {
            **dict(newest_drag),
            "start_x": points[0][0],
            "start_y": points[0][1],
        },
        "screen_path": tuple({"x": x, "y": y} for x, y in points),
        _DRAG_TIMES: tuple(times),
        _DRAG_RAW_COUNT: newest_raw + 1 - int(duplicate),
    }
    return _replace_command_params(newest, params)


def _carry_selection_boundary(
    previous: MeshEditCommand,
    newest: MeshEditCommand,
    timestamp_seconds: float,
) -> MeshEditCommand:
    previous_screen = previous.params.get("_native_screen_selection_payload")
    newest_screen = newest.params.get("_native_screen_selection_payload")
    if not isinstance(previous_screen, Mapping) or not isinstance(newest_screen, Mapping):
        return continue_selection_terminal(newest)
    previous_path = _brush_path(previous_screen, previous.params, timestamp_seconds)
    newest_path = _brush_path(newest_screen, newest.params, timestamp_seconds)
    operation = str(previous.params.get("operation", "replace") or "replace").strip().lower()
    next_operation = "add" if operation == "replace" else operation
    if previous_path is None or newest_path is None or previous_path[3] != newest_path[3]:
        return _replace_command_params(newest, {**newest.params, "operation": next_operation})
    boundary_points: tuple[tuple[float, float], ...] = ()
    boundary_times: tuple[float, ...] = ()
    if operation != "toggle":
        boundary_points = (previous_path[0][-1],)
        boundary_times = (previous_path[1][-1],)
    points, times, duplicate = _join_samples(
        boundary_points,
        boundary_times,
        newest_path[0],
        newest_path[1],
    )
    screen = _screen_with_brush_path(dict(newest_screen), newest_path[3], points)
    return _replace_command_params(
        newest,
        {
            **newest.params,
            "operation": next_operation,
            "_native_screen_selection_payload": screen,
            _SELECTION_TIMES: tuple(times),
            _SELECTION_RAW_COUNT: newest_path[2] + len(boundary_points) - int(duplicate),
        },
    )


def _bound_screen_selection(
    raw_screen: Mapping[str, object],
    params: Mapping[str, object],
    *,
    timestamp_seconds: float,
    max_samples: int,
) -> tuple[dict[str, object], int, int, bool, tuple[float, ...]]:
    screen = dict(raw_screen)
    path = _brush_path(screen, params, timestamp_seconds)
    retained = 0
    raw_count = 0
    overflowed = False
    selection_times: tuple[float, ...] = ()
    if path is not None:
        buffer, did_overflow = _bounded_buffer(path[0], path[1], max_samples=max_samples)
        if buffer.retained_count >= 2:
            screen = _screen_with_brush_path(screen, path[3], buffer.points)
        retained += buffer.retained_count
        raw_count += path[2]
        overflowed = did_overflow
        selection_times = tuple(sample.timestamp_seconds for sample in buffer.samples)
        bounded_regions: list[dict[str, object]] = []
        for region in _screen_selection_items(screen, "screen_region", "screen_regions"):
            mode = str(region.get("mode", region.get("selection_mode", "")) or "").strip().lower()
            if mode == "brush":
                bounded_regions.append(region)
                continue
            bounded, region_retained, region_raw, region_overflowed = _bound_region_points(
                region,
                timestamp_seconds=timestamp_seconds,
                max_samples=max_samples,
            )
            bounded_regions.append(bounded)
            retained += region_retained
            raw_count += region_raw
            overflowed = overflowed or region_overflowed
        screen.pop("screen_region", None)
        screen.pop("screen_regions", None)
        if len(bounded_regions) == 1:
            screen["screen_region"] = bounded_regions[0]
        elif bounded_regions:
            screen["screen_regions"] = _evenly_bounded(bounded_regions, max_samples)
        return screen, retained, raw_count, overflowed, selection_times

    for singular, plural in (("screen_brush", "screen_brushes"), ("screen_region", "screen_regions")):
        items = _screen_selection_items(screen, singular, plural)
        if not items:
            continue
        bounded_items = _evenly_bounded(items, max_samples)
        screen.pop(singular, None)
        screen[plural] = bounded_items
        retained += len(bounded_items)
        raw_count += len(items)
        overflowed = overflowed or len(items) > len(bounded_items)
    return screen, retained, raw_count, overflowed, selection_times


def _bound_region_points(
    region: Mapping[str, object],
    *,
    timestamp_seconds: float,
    max_samples: int,
) -> tuple[dict[str, object], int, int, bool]:
    raw_points = region.get("points")
    if not isinstance(raw_points, (tuple, list)):
        return dict(region), 1, 1, False
    points = tuple(
        point
        for raw in raw_points
        if (point := _sequence_point(raw)) is not None
    )
    if not points:
        return dict(region), 1, 1, False
    times = _sample_times(None, len(points), timestamp_seconds)
    buffer, overflowed = _bounded_buffer(points, times, max_samples=max_samples)
    bounded = {
        **dict(region),
        "points": [[x, y] for x, y in buffer.points],
        "start_x": buffer.points[0][0],
        "start_y": buffer.points[0][1],
        "end_x": buffer.points[-1][0],
        "end_y": buffer.points[-1][1],
    }
    return bounded, buffer.retained_count, len(points), overflowed


def _brush_path(
    screen: Mapping[str, object],
    params: Mapping[str, object],
    timestamp_seconds: float,
) -> tuple[tuple[tuple[float, float], ...], tuple[float, ...], int, dict[str, object]] | None:
    points: list[tuple[float, float]] = []
    template: dict[str, object] | None = None
    for region in _screen_selection_items(screen, "screen_region", "screen_regions"):
        mode = str(region.get("mode", region.get("selection_mode", "")) or "").strip().lower()
        raw_points = region.get("points")
        if mode != "brush" or not isinstance(raw_points, (tuple, list)):
            continue
        metadata = {
            key: value
            for key, value in region.items()
            if key not in {"points", "start_x", "start_y", "end_x", "end_y", "mode", "selection_mode"}
        }
        if template is not None and not _same_metadata(template, metadata):
            return None
        template = metadata
        points.extend(
            point
            for raw in raw_points
            if (point := _sequence_point(raw)) is not None
        )
    for brush in _screen_selection_items(screen, "screen_brush", "screen_brushes"):
        point = _xy_point(brush.get("x"), brush.get("y"))
        metadata = {key: value for key, value in brush.items() if key not in {"x", "y"}}
        if point is None or (template is not None and not _same_metadata(template, metadata)):
            return None
        template = metadata
        points.append(point)
    if not points or template is None:
        return None
    raw_count = int(params.get(_SELECTION_RAW_COUNT, len(points)) or len(points))
    raw_times = params.get(_SELECTION_TIMES)
    times = _sample_times(raw_times, len(points), timestamp_seconds)
    return tuple(points), times, max(raw_count, len(points)), template


def _screen_with_brush_path(
    screen: dict[str, object],
    template: Mapping[str, object],
    points: Sequence[tuple[float, float]],
) -> dict[str, object]:
    screen.pop("screen_brush", None)
    screen.pop("screen_brushes", None)
    existing_regions = [
        region
        for region in _screen_selection_items(screen, "screen_region", "screen_regions")
        if str(region.get("mode", region.get("selection_mode", "")) or "").strip().lower() != "brush"
    ]
    screen.pop("screen_region", None)
    screen.pop("screen_regions", None)
    region = {
        **dict(template),
        "mode": "brush",
        "selection_mode": "brush",
        "points": [[x, y] for x, y in points],
        "start_x": points[0][0],
        "start_y": points[0][1],
        "end_x": points[-1][0],
        "end_y": points[-1][1],
    }
    if existing_regions:
        screen["screen_regions"] = [*existing_regions, region]
    else:
        screen["screen_region"] = region
    return screen


def _drag_samples(
    params: Mapping[str, object],
    drag: Mapping[str, object],
    timestamp_seconds: float,
) -> tuple[tuple[tuple[float, float], ...], tuple[float, ...], int]:
    raw_path = params.get("screen_path")
    points: list[tuple[float, float]] = []
    if isinstance(raw_path, (tuple, list)):
        points.extend(
            point
            for raw in raw_path
            if isinstance(raw, Mapping)
            and (point := _xy_point(raw.get("x"), raw.get("y"))) is not None
        )
    if len(points) < 2:
        start = _xy_point(drag.get("start_x"), drag.get("start_y"))
        end = _xy_point(drag.get("end_x"), drag.get("end_y"))
        points = [point for point in (start, end) if point is not None]
    times = _sample_times(params.get(_DRAG_TIMES), len(points), timestamp_seconds)
    raw_count = int(params.get(_DRAG_RAW_COUNT, len(points)) or len(points))
    return tuple(points), times, max(raw_count, len(points))


def _bounded_buffer(
    points: Sequence[tuple[float, float]],
    times: Sequence[float],
    *,
    max_samples: int,
) -> tuple[StrokeSampleBuffer, bool]:
    config = StrokeSampleConfig(
        max_samples=max_samples,
        min_spacing_pixels=STROKE_SAMPLE_CONFIG.min_spacing_pixels,
        max_interval_seconds=STROKE_SAMPLE_CONFIG.max_interval_seconds,
        curvature_degrees=STROKE_SAMPLE_CONFIG.curvature_degrees,
    )
    buffer = StrokeSampleBuffer(config)
    overflowed = buffer.extend(
        StrokeSample(x, y, timestamp)
        for (x, y), timestamp in zip(points, times)
    )
    return buffer, overflowed


def _sample_times(raw: object, count: int, timestamp_seconds: float) -> tuple[float, ...]:
    if isinstance(raw, (tuple, list)) and len(raw) == count:
        try:
            values = tuple(float(value) for value in raw)
        except (TypeError, ValueError, OverflowError):
            values = ()
        if values and all(math.isfinite(value) for value in values):
            return values
    start = timestamp_seconds - max(0, count - 1) * 1e-6
    return tuple(start + index * 1e-6 for index in range(count))


def _join_samples(
    first_points: Sequence[tuple[float, float]],
    first_times: Sequence[float],
    second_points: Sequence[tuple[float, float]],
    second_times: Sequence[float],
) -> tuple[tuple[tuple[float, float], ...], tuple[float, ...], bool]:
    points = list(first_points)
    times = list(first_times)
    duplicate = bool(points and second_points and points[-1] == second_points[0])
    offset = 1 if duplicate else 0
    points.extend(second_points[offset:])
    times.extend(second_times[offset:])
    return tuple(points), tuple(times), duplicate


def _screen_selection_items(payload: Mapping[str, object], singular: str, plural: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    raw_many = payload.get(plural)
    if isinstance(raw_many, (tuple, list)):
        items.extend(dict(item) for item in raw_many if isinstance(item, Mapping))
    raw_one = payload.get(singular)
    if isinstance(raw_one, Mapping):
        items.append(dict(raw_one))
    return items


def _evenly_bounded(items: Sequence[dict[str, object]], limit: int) -> list[dict[str, object]]:
    if len(items) <= limit:
        return list(items)
    if limit <= 2:
        return [dict(items[0]), dict(items[-1])]
    scale = (len(items) - 1) / (limit - 1)
    indices = tuple(round(index * scale) for index in range(limit))
    return [dict(items[index]) for index in indices]


def _same_metadata(first: Mapping[str, object], second: Mapping[str, object]) -> bool:
    return json.dumps(first, sort_keys=True, default=str) == json.dumps(second, sort_keys=True, default=str)


def _xy_point(x: object, y: object) -> tuple[float, float] | None:
    try:
        point = float(x), float(y)
    except (TypeError, ValueError, OverflowError):
        return None
    return point if all(math.isfinite(value) for value in point) else None


def _sequence_point(raw: object) -> tuple[float, float] | None:
    if isinstance(raw, Mapping):
        return _xy_point(raw.get("x"), raw.get("y"))
    if isinstance(raw, (tuple, list)) and len(raw) >= 2:
        return _xy_point(raw[0], raw[1])
    return None


def _replace_command_params(command: MeshEditCommand, params: Mapping[str, object]) -> MeshEditCommand:
    return MeshEditCommand(
        command.action,
        selection=command.selection,
        params=dict(params),
        mode=command.mode,
        label=command.label,
    )


__all__ = [
    "STROKE_MAX_PACKET_BYTES",
    "STROKE_MAX_SAMPLES_PER_PACKET",
    "STROKE_MAX_SEGMENTS",
    "StrokePacketBuild",
    "bound_live_stroke_command",
    "cancel_live_stroke_command",
    "carry_live_stroke_segment_boundary",
    "command_for_live_stroke_apply",
    "continue_selection_terminal",
    "encoded_stroke_command_bytes",
    "merge_live_stroke_commands",
]
