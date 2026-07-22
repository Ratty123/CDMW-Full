"""Compatibility helpers for authoring screen-space payload tests.

This module does not start or communicate with the retired native renderer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import time

from tools.mesh_harness.constants import _LEGACY_SCREEN_CAMERA_FIELDS
from tools.mesh_harness.stroke_harness_host import _HarnessSignal


def _emit_timed_stroke(signal: _HarnessSignal, payload: Mapping[str, object]) -> float:
    started = time.perf_counter()
    signal.emit(dict(payload))
    return max(0.0, (time.perf_counter() - started) * 1000.0)


def _finite_float(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _payload_frame_count(payload: object) -> int:
    if not isinstance(payload, Mapping):
        return -1
    try:
        return int(payload.get("frame_count", -1) or -1)
    except (TypeError, ValueError, OverflowError):
        return -1


def _timing_summary(
    samples: Sequence[Mapping[str, object]], key: str
) -> dict[str, float]:
    values = sorted(_finite_float(sample.get(key), 0.0) for sample in samples)
    values = [value for value in values if value >= 0.0]
    if not values:
        return {"count": 0.0, "max_ms": 0.0, "average_ms": 0.0, "p95_ms": 0.0}
    p95_index = min(len(values) - 1, int(math.ceil(len(values) * 0.95)) - 1)
    return {
        "count": float(len(values)),
        "max_ms": values[-1],
        "average_ms": sum(values) / len(values),
        "p95_ms": values[p95_index],
    }


def _matrix_only_screen_payload(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key not in _LEGACY_SCREEN_CAMERA_FIELDS
    }


def _project_world_to_screen(
    matrix: Sequence[object],
    vertex: Sequence[float],
    *,
    viewport_x: float,
    viewport_y: float,
    viewport_width: float,
    viewport_height: float,
) -> tuple[float, float] | None:
    if (
        len(matrix) != 16
        or len(vertex) < 3
        or viewport_width <= 0.0
        or viewport_height <= 0.0
    ):
        return None
    values = [float(value) for value in matrix]
    x, y, z = (float(vertex[0]), float(vertex[1]), float(vertex[2]))
    clip_x = x * values[0] + y * values[4] + z * values[8] + values[12]
    clip_y = x * values[1] + y * values[5] + z * values[9] + values[13]
    clip_z = x * values[2] + y * values[6] + z * values[10] + values[14]
    clip_w = x * values[3] + y * values[7] + z * values[11] + values[15]
    if not all(math.isfinite(value) for value in (clip_x, clip_y, clip_z, clip_w)) or abs(clip_w) <= 1e-12:
        return None
    ndc_x, ndc_y, ndc_z = clip_x / clip_w, clip_y / clip_w, clip_z / clip_w
    if not all(math.isfinite(value) for value in (ndc_x, ndc_y, ndc_z)) or not 0.0 <= ndc_z <= 1.0:
        return None
    screen_x = viewport_x + (ndc_x * 0.5 + 0.5) * viewport_width
    screen_y = viewport_y + (0.5 - ndc_y * 0.5) * viewport_height
    return (screen_x, screen_y) if math.isfinite(screen_x) and math.isfinite(screen_y) else None


def _projected_face_cluster_for_drag(
    submesh: object,
    matrix: Sequence[object],
    *,
    viewport_x: float,
    viewport_y: float,
    viewport_width: float,
    viewport_height: float,
    max_faces: int = 12,
) -> tuple[int, ...]:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    projected: dict[int, tuple[float, float, float, float]] = {}
    for face_index, face in enumerate(faces):
        indices = tuple(int(value) for value in tuple(face or ())[:3])
        if len(indices) < 3 or any(index < 0 or index >= len(vertices) for index in indices):
            continue
        center = tuple(
            sum(float(vertices[index][axis]) for index in indices) / 3.0
            for axis in range(3)
        )
        screen = _project_world_to_screen(
            matrix,
            center,
            viewport_x=viewport_x,
            viewport_y=viewport_y,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
        if screen is None:
            continue
        screen_x, screen_y = screen
        if viewport_x <= screen_x <= viewport_x + viewport_width and viewport_y <= screen_y <= viewport_y + viewport_height:
            projected[face_index] = (screen_x, screen_y, center[0], center[1])
    if not projected:
        return tuple(range(min(max_faces, len(faces))))
    min_x = min(item[0] for item in projected.values())
    max_x = max(item[0] for item in projected.values())
    min_y = min(item[1] for item in projected.values())
    max_y = max(item[1] for item in projected.values())
    target = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)
    start_face = min(
        projected,
        key=lambda face_index: math.hypot(
            projected[face_index][0] - target[0],
            projected[face_index][1] - target[1],
        ),
    )
    vertex_to_faces: dict[int, list[int]] = {}
    for face_index, face in enumerate(faces):
        for vertex_index in tuple(face or ())[:3]:
            vertex_to_faces.setdefault(int(vertex_index), []).append(face_index)
    selected: set[int] = {start_face}
    frontier = [start_face]
    while frontier and len(selected) < max_faces:
        face_index = frontier.pop(0)
        neighbours: set[int] = set()
        for vertex_index in tuple(faces[face_index] or ())[:3]:
            neighbours.update(vertex_to_faces.get(int(vertex_index), ()))
        for neighbour in sorted(
            neighbours - selected,
            key=lambda item: (
                math.hypot(
                    projected.get(item, (target[0], target[1]))[0] - target[0],
                    projected.get(item, (target[0], target[1]))[1] - target[1],
                ),
                item,
            ),
        ):
            selected.add(neighbour)
            frontier.append(neighbour)
            if len(selected) >= max_faces:
                break
    return tuple(sorted(selected))


def _screen_source_transform_override_ok(payload: Mapping[str, object]) -> bool:
    raw_overrides = payload.get("source_submesh_world_transforms")
    if not isinstance(raw_overrides, Sequence) or isinstance(raw_overrides, (str, bytes, bytearray)):
        return False
    for item in raw_overrides:
        if not isinstance(item, Mapping) or not isinstance(item.get("source_submesh_index"), int):
            continue
        raw_matrix = item.get("world_transform")
        if isinstance(raw_matrix, Sequence) and not isinstance(raw_matrix, (str, bytes, bytearray)):
            matrix = tuple(raw_matrix)
            if len(matrix) == 16 and all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in matrix):
                return True
    return False


def _screen_drag_for_z_delta(delta_z: float, *, start_z: float = 0.0) -> dict[str, object]:
    start_x = float(start_z) * 100.0
    end_x = float(start_z + delta_z) * 100.0
    return {
        "start_x": start_x,
        "start_y": 0.0,
        "end_x": end_x,
        "end_y": 0.0,
        "viewport_width": 200.0,
        "viewport_height": 200.0,
        "world_view_projection": [
            0.0, 0.0, 0.5, 0.0,
            0.0, 1.0, 0.0, 0.0,
            1.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.5, 1.0,
        ],
    }


def _wait_for_live_stroke_idle(
    tab: object, app: object, timeout_seconds: float = 5.0
) -> bool:
    dispatcher = getattr(tab, "standalone_live_stroke_dispatcher", None)
    if dispatcher is None:
        return False
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while not dispatcher.wait_idle(0.0) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    app.processEvents()
    return bool(dispatcher.wait_idle(0.0))
