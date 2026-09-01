from __future__ import annotations

import ctypes
import hashlib
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DLL_PATH = ROOT / "native" / "cdmw_mesh_core" / "build" / "Release" / "cdmw-mesh-core.dll"
HEADER_PATH = ROOT / "native" / "cdmw_mesh_core" / "src" / "mesh_interaction_abi.h"

ABI_VERSION = 1
OK = 0
INVALID_SIZE = 2
UNSUPPORTED_VERSION = 3
SESSION_NOT_FOUND = 4
SESSION_EXISTS = 5
REVISION_MISMATCH = 6
INVALID_STATE = 8
REJECTED = 10
INVALID_ARGUMENT = 1

SYNC_MESH = 1 << 0
SYNC_SELECTION = 1 << 1
SYNC_TOPOLOGY = 1 << 2
SYNC_CAMERA = 1 << 3
SYNC_VIEWPORT = 1 << 4
TOOL_MOVE = 2
TOOL_SELECT = 1
TOOL_GRAB = 3
TOOL_SMOOTH = 4
TOOL_INFLATE = 5
TOOL_PINCH = 6
SELECTION_VERTEX = 1
SELECTION_EDGE = 2
SELECTION_FACE = 3
SELECTION_BRUSH = 1
SELECTION_RECTANGLE = 2
SELECTION_LASSO = 3
SELECTION_REPLACE = 1
SELECTION_ADD = 2
SELECTION_SUBTRACT = 3
SELECTION_TOGGLE = 4
OPERATOR_IDLE = 0
OPERATOR_ACTIVE = 1
OPERATOR_AWAITING_AUTHORITY = 2
AUTHORITY_ACCEPTED = 1
AUTHORITY_REJECTED = 2
AUTHORITY_UNDO = 3
AUTHORITY_REDO = 4


class Submesh(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("submesh_index", ctypes.c_int32),
        ("vertex_count", ctypes.c_uint32),
        ("positions_xyz", ctypes.POINTER(ctypes.c_double)),
        ("normals_xyz", ctypes.POINTER(ctypes.c_double)),
        ("triangle_count", ctypes.c_uint32),
        ("triangle_indices", ctypes.POINTER(ctypes.c_uint32)),
    ]


class Selection(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("submesh_index", ctypes.c_int32),
        ("vertex_count", ctypes.c_uint32),
        ("vertex_indices", ctypes.POINTER(ctypes.c_uint32)),
        ("face_count", ctypes.c_uint32),
        ("face_indices", ctypes.POINTER(ctypes.c_uint32)),
        ("edge_count", ctypes.c_uint32),
        ("edge_vertex_pairs", ctypes.POINTER(ctypes.c_uint32)),
    ]


class Projection(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("submesh_index", ctypes.c_int32),
        ("reserved", ctypes.c_uint32),
        ("world_view_projection", ctypes.c_double * 16),
    ]


class OpenRequest(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("session_key", ctypes.c_uint64),
        ("mesh_revision", ctypes.c_uint64),
        ("selection_revision", ctypes.c_uint64),
        ("topology_generation", ctypes.c_uint64),
        ("camera_revision", ctypes.c_uint64),
        ("viewport_revision", ctypes.c_uint64),
        ("submesh_count", ctypes.c_uint32),
        ("submeshes", ctypes.POINTER(Submesh)),
    ]


class SessionRequest(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("session_handle", ctypes.c_uint64),
    ]


class SyncRequest(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("session_handle", ctypes.c_uint64),
        ("flags", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("base_mesh_revision", ctypes.c_uint64),
        ("mesh_revision", ctypes.c_uint64),
        ("base_selection_revision", ctypes.c_uint64),
        ("selection_revision", ctypes.c_uint64),
        ("base_topology_generation", ctypes.c_uint64),
        ("topology_generation", ctypes.c_uint64),
        ("base_camera_revision", ctypes.c_uint64),
        ("camera_revision", ctypes.c_uint64),
        ("base_viewport_revision", ctypes.c_uint64),
        ("viewport_revision", ctypes.c_uint64),
        ("submesh_count", ctypes.c_uint32),
        ("submeshes", ctypes.POINTER(Submesh)),
        ("selection_count", ctypes.c_uint32),
        ("selections", ctypes.POINTER(Selection)),
        ("projection_count", ctypes.c_uint32),
        ("projections", ctypes.POINTER(Projection)),
        ("world_view_projection", ctypes.c_double * 16),
        ("viewport_width", ctypes.c_double),
        ("viewport_height", ctypes.c_double),
    ]


class GestureRequest(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("session_handle", ctypes.c_uint64),
        ("gesture_id", ctypes.c_uint64),
        ("mesh_revision", ctypes.c_uint64),
        ("selection_revision", ctypes.c_uint64),
        ("topology_generation", ctypes.c_uint64),
        ("camera_revision", ctypes.c_uint64),
        ("viewport_revision", ctypes.c_uint64),
        ("tool", ctypes.c_uint32),
        ("selection_target", ctypes.c_uint32),
        ("selection_shape", ctypes.c_uint32),
        ("selection_operation", ctypes.c_uint32),
        ("xray", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("start_x", ctypes.c_double),
        ("start_y", ctypes.c_double),
        ("current_x", ctypes.c_double),
        ("current_y", ctypes.c_double),
        ("radius_pixels", ctypes.c_double),
        ("strength", ctypes.c_double),
        ("pressure", ctypes.c_double),
        ("delta_x", ctypes.c_double),
        ("delta_y", ctypes.c_double),
        ("delta_z", ctypes.c_double),
        ("point_count", ctypes.c_uint32),
        ("points_xy", ctypes.POINTER(ctypes.c_double)),
    ]


class PrepareSnapshotRequest(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("session_handle", ctypes.c_uint64),
        ("mesh_revision", ctypes.c_uint64),
        ("selection_revision", ctypes.c_uint64),
        ("topology_generation", ctypes.c_uint64),
        ("camera_revision", ctypes.c_uint64),
        ("viewport_revision", ctypes.c_uint64),
        ("visible_parts_revision", ctypes.c_uint64),
        ("model_transform_revision", ctypes.c_uint64),
        ("xray", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
    ]


class AuthorityRequest(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("session_handle", ctypes.c_uint64),
        ("gesture_id", ctypes.c_uint64),
        ("action", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("base_mesh_revision", ctypes.c_uint64),
        ("mesh_revision", ctypes.c_uint64),
        ("base_selection_revision", ctypes.c_uint64),
        ("selection_revision", ctypes.c_uint64),
        ("base_topology_generation", ctypes.c_uint64),
        ("topology_generation", ctypes.c_uint64),
    ]


class VertexRead(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("session_handle", ctypes.c_uint64),
        ("submesh_index", ctypes.c_int32),
        ("first_vertex", ctypes.c_uint32),
        ("vertex_count", ctypes.c_uint32),
        ("position_capacity", ctypes.c_uint32),
        ("positions_xyz", ctypes.POINTER(ctypes.c_double)),
        ("written_vertex_count", ctypes.c_uint32),
    ]


class DirtyRange(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("submesh_index", ctypes.c_int32),
        ("first_vertex", ctypes.c_uint32),
        ("vertex_count", ctypes.c_uint32),
        ("mesh_revision", ctypes.c_uint64),
        ("topology_generation", ctypes.c_uint64),
        ("interaction_generation", ctypes.c_uint64),
    ]


class SelectionChange(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("submesh_index", ctypes.c_int32),
        ("target", ctypes.c_uint32),
        ("first_element", ctypes.c_uint32),
        ("second_element", ctypes.c_uint32),
        ("element_count", ctypes.c_uint32),
        ("selected", ctypes.c_uint32),
        ("selection_revision", ctypes.c_uint64),
        ("interaction_generation", ctypes.c_uint64),
    ]


class Result(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("struct_version", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("operator_state", ctypes.c_uint32),
        ("session_handle", ctypes.c_uint64),
        ("gesture_id", ctypes.c_uint64),
        ("mesh_revision", ctypes.c_uint64),
        ("selection_revision", ctypes.c_uint64),
        ("topology_generation", ctypes.c_uint64),
        ("camera_revision", ctypes.c_uint64),
        ("viewport_revision", ctypes.c_uint64),
        ("interaction_generation", ctypes.c_uint64),
        ("dirty_range_capacity", ctypes.c_uint32),
        ("dirty_ranges", ctypes.POINTER(DirtyRange)),
        ("dirty_range_count", ctypes.c_uint32),
        ("selection_change_capacity", ctypes.c_uint32),
        ("selection_changes", ctypes.POINTER(SelectionChange)),
        ("selection_change_count", ctypes.c_uint32),
        ("message", ctypes.c_char * 256),
    ]


@pytest.fixture(scope="module")
def abi() -> ctypes.CDLL:
    if not DLL_PATH.is_file():
        pytest.skip(f"build the native ABI target first: {DLL_PATH}")
    library = ctypes.CDLL(str(DLL_PATH))
    library.cdmw_mesh_interaction_abi_version.restype = ctypes.c_uint32
    library.cdmw_mesh_interaction_abi_contract.restype = ctypes.c_char_p
    library.cdmw_mesh_interaction_abi_header_sha256.restype = ctypes.c_char_p
    library.cdmw_mesh_interaction_backend.restype = ctypes.c_char_p
    library.cdmw_mesh_interaction_struct_size.argtypes = [ctypes.c_uint32]
    library.cdmw_mesh_interaction_struct_size.restype = ctypes.c_uint32
    signatures = {
        "open": OpenRequest,
        "close": SessionRequest,
        "sync": SyncRequest,
        "prepare_snapshot_v1": PrepareSnapshotRequest,
        "begin": GestureRequest,
        "update": GestureRequest,
        "end": GestureRequest,
        "cancel": GestureRequest,
        "apply_authoritative": AuthorityRequest,
        "read_vertices": VertexRead,
    }
    for suffix, request_type in signatures.items():
        function = getattr(library, f"cdmw_mesh_interaction_{suffix}")
        function.argtypes = [ctypes.POINTER(request_type), ctypes.POINTER(Result)]
        function.restype = ctypes.c_uint32
    return library


def _result() -> tuple[Result, ctypes.Array[DirtyRange], ctypes.Array[SelectionChange]]:
    dirty = (DirtyRange * 64)()
    changes = (SelectionChange * 64)()
    result = Result()
    result.struct_size = ctypes.sizeof(Result)
    result.struct_version = ABI_VERSION
    result.dirty_range_capacity = len(dirty)
    result.dirty_ranges = dirty
    result.selection_change_capacity = len(changes)
    result.selection_changes = changes
    return result, dirty, changes


def _call(library: ctypes.CDLL, name: str, request: ctypes.Structure) -> tuple[int, Result]:
    result, dirty, changes = _result()
    status = getattr(library, f"cdmw_mesh_interaction_{name}")(
        ctypes.byref(request), ctypes.byref(result)
    )
    result._dirty_owner = dirty
    result._selection_owner = changes
    return status, result


def _prepare_snapshot(
    library: ctypes.CDLL,
    handle: int,
    mesh_revision: int,
    selection_revision: int,
    *,
    xray: bool,
    camera_revision: int = 1,
    viewport_revision: int = 1,
) -> Result:
    request = PrepareSnapshotRequest(
        ctypes.sizeof(PrepareSnapshotRequest),
        ABI_VERSION,
        handle,
        mesh_revision,
        selection_revision,
        1,
        camera_revision,
        viewport_revision,
        1,
        1,
        int(xray),
        0,
    )
    status, result = _call(library, "prepare_snapshot_v1", request)
    assert status == OK, bytes(result.message).split(b"\0", 1)[0].decode()
    return result


def _gesture(handle: int, gesture_id: int, mesh_revision: int, delta_z: float) -> GestureRequest:
    request = GestureRequest()
    request.struct_size = ctypes.sizeof(GestureRequest)
    request.struct_version = ABI_VERSION
    request.session_handle = handle
    request.gesture_id = gesture_id
    request.mesh_revision = mesh_revision
    request.selection_revision = 2
    request.topology_generation = 1
    request.camera_revision = 1
    request.viewport_revision = 1
    request.tool = TOOL_MOVE
    request.strength = 1.0
    request.pressure = 1.0
    request.delta_z = delta_z
    return request


def _authority(
    handle: int,
    action: int,
    base_revision: int,
    revision: int,
    gesture_id: int = 0,
    *,
    base_selection_revision: int = 2,
    selection_revision: int = 2,
) -> AuthorityRequest:
    request = AuthorityRequest()
    request.struct_size = ctypes.sizeof(AuthorityRequest)
    request.struct_version = ABI_VERSION
    request.session_handle = handle
    request.gesture_id = gesture_id
    request.action = action
    request.base_mesh_revision = base_revision
    request.mesh_revision = revision
    request.base_selection_revision = base_selection_revision
    request.selection_revision = selection_revision
    request.base_topology_generation = 1
    request.topology_generation = 1
    return request


def _selection_gesture(
    handle: int,
    gesture_id: int,
    mesh_revision: int,
    *,
    selection_revision: int = 2,
    operation: int = SELECTION_REPLACE,
    x: float = 320.0,
    y: float = 240.0,
) -> GestureRequest:
    request = _gesture(handle, gesture_id, mesh_revision, 0.0)
    request.selection_revision = selection_revision
    request.tool = TOOL_SELECT
    request.selection_target = SELECTION_VERTEX
    request.selection_shape = SELECTION_BRUSH
    request.selection_operation = operation
    request.xray = 1
    request.current_x = x
    request.current_y = y
    request.radius_pixels = 16.0
    return request


def _read_vertex(library: ctypes.CDLL, handle: int, index: int) -> tuple[float, float, float]:
    output = (ctypes.c_double * 3)()
    request = VertexRead()
    request.struct_size = ctypes.sizeof(VertexRead)
    request.struct_version = ABI_VERSION
    request.session_handle = handle
    request.submesh_index = 0
    request.first_vertex = index
    request.vertex_count = 1
    request.position_capacity = len(output)
    request.positions_xyz = output
    status, _ = _call(library, "read_vertices", request)
    assert status == OK
    assert request.written_vertex_count == 1
    return tuple(output)  # type: ignore[return-value]


def _open_indexed_scene(
    library: ctypes.CDLL,
    session_key: int,
    positions: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    *,
    selected_vertices: tuple[int, ...] = (),
    viewport: tuple[int, int] = (640, 480),
) -> tuple[int, tuple[object, ...]]:
    position_values = (ctypes.c_double * (len(positions) * 3))(
        *(value for position in positions for value in position)
    )
    face_values = (ctypes.c_uint32 * (len(faces) * 3))(
        *(value for face in faces for value in face)
    )
    submesh = Submesh(
        ctypes.sizeof(Submesh),
        ABI_VERSION,
        0,
        len(positions),
        position_values,
        None,
        len(faces),
        face_values,
    )
    submeshes = (Submesh * 1)(submesh)
    opened = OpenRequest(
        ctypes.sizeof(OpenRequest), ABI_VERSION, session_key,
        1, 1, 1, 0, 0, 1, submeshes,
    )
    status, result = _call(library, "open", opened)
    assert status == OK

    selected = (ctypes.c_uint32 * len(selected_vertices))(*selected_vertices)
    selection = Selection(
        ctypes.sizeof(Selection), ABI_VERSION, 0,
        len(selected_vertices), selected if selected_vertices else None,
        0, None, 0, None,
    )
    selections = (Selection * 1)(selection)
    identity = (ctypes.c_double * 16)(
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    )
    projection = Projection(
        ctypes.sizeof(Projection), ABI_VERSION, 0, 0, identity
    )
    projections = (Projection * 1)(projection)
    sync = SyncRequest()
    sync.struct_size = ctypes.sizeof(SyncRequest)
    sync.struct_version = ABI_VERSION
    sync.session_handle = result.session_handle
    sync.flags = SYNC_SELECTION | SYNC_CAMERA | SYNC_VIEWPORT
    sync.base_selection_revision = 1
    sync.selection_revision = 2
    sync.base_camera_revision = 0
    sync.camera_revision = 1
    sync.base_viewport_revision = 0
    sync.viewport_revision = 1
    sync.selection_count = 1
    sync.selections = selections
    sync.projection_count = 1
    sync.projections = projections
    sync.world_view_projection = identity
    sync.viewport_width = viewport[0]
    sync.viewport_height = viewport[1]
    status, _ = _call(library, "sync", sync)
    assert status == OK
    owners: tuple[object, ...] = (
        position_values, face_values, submeshes, selected, selections,
        identity, projections,
    )
    return result.session_handle, owners


def _close_indexed_scene(library: ctypes.CDLL, handle: int) -> None:
    status, _ = _call(
        library,
        "close",
        SessionRequest(ctypes.sizeof(SessionRequest), ABI_VERSION, handle),
    )
    assert status == OK


def _indexed_selection_gesture(
    handle: int,
    gesture_id: int,
    mesh_revision: int,
    selection_revision: int,
    *,
    target: int,
    shape: int,
    operation: int = SELECTION_REPLACE,
    xray: bool = True,
    start: tuple[float, float] = (0.0, 0.0),
    current: tuple[float, float] = (0.0, 0.0),
    radius: float = 20.0,
    points: tuple[tuple[float, float], ...] = (),
) -> GestureRequest:
    values = (ctypes.c_double * (len(points) * 2))(
        *(value for point in points for value in point)
    )
    request = GestureRequest()
    request.struct_size = ctypes.sizeof(GestureRequest)
    request.struct_version = ABI_VERSION
    request.session_handle = handle
    request.gesture_id = gesture_id
    request.mesh_revision = mesh_revision
    request.selection_revision = selection_revision
    request.topology_generation = 1
    request.camera_revision = 1
    request.viewport_revision = 1
    request.tool = TOOL_SELECT
    request.selection_target = target
    request.selection_shape = shape
    request.selection_operation = operation
    request.xray = int(xray)
    request.start_x, request.start_y = start
    request.current_x, request.current_y = current
    request.radius_pixels = radius
    request.strength = 1.0
    request.pressure = 1.0
    request.point_count = len(points)
    request.points_xy = values if points else None
    request._points_owner = values
    return request


def _selection_identity(change: SelectionChange) -> object:
    if change.target == SELECTION_EDGE:
        return tuple(sorted((change.first_element, change.second_element)))
    return change.first_element


def _finish_indexed_selection(
    library: ctypes.CDLL,
    request: GestureRequest,
) -> set[object]:
    status, _ = _call(library, "begin", request)
    assert status == OK
    status, result = _call(library, "end", request)
    assert status == OK
    selected = {
        _selection_identity(result.selection_changes[index])
        for index in range(result.selection_change_count)
        if result.selection_changes[index].selected
    }
    status, _ = _call(
        library,
        "apply_authoritative",
        _authority(
            request.session_handle,
            AUTHORITY_ACCEPTED,
            request.mesh_revision,
            request.mesh_revision + 1,
            request.gesture_id,
            base_selection_revision=request.selection_revision,
            selection_revision=request.selection_revision + 1,
        ),
    )
    assert status == OK
    return selected


def _projected(
    position: tuple[float, float, float],
    viewport: tuple[int, int] = (640, 480),
) -> tuple[float, float, float]:
    return (
        (position[0] + 1.0) * viewport[0] * 0.5,
        (1.0 - position[1]) * viewport[1] * 0.5,
        position[2],
    )


def _point_in_polygon(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    x, y = point
    inside = False
    right = len(polygon) - 1
    for left, (ax, ay) in enumerate(polygon):
        bx, by = polygon[right]
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
        right = left
    return inside


def _point_in_shape(
    point: tuple[float, float],
    *,
    shape: int,
    start: tuple[float, float],
    current: tuple[float, float],
    radius: float,
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    if shape == SELECTION_BRUSH:
        return math.dist(point, current) <= radius
    if shape == SELECTION_RECTANGLE:
        return (
            min(start[0], current[0]) <= point[0] <= max(start[0], current[0])
            and min(start[1], current[1]) <= point[1] <= max(start[1], current[1])
        )
    return _point_in_polygon(point, polygon)


def _orientation(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    return (c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])


def _on_segment(
    a: tuple[float, float], b: tuple[float, float], point: tuple[float, float]
) -> bool:
    return (
        abs(_orientation(a, b, point)) <= 1e-9
        and min(a[0], b[0]) - 1e-9 <= point[0] <= max(a[0], b[0]) + 1e-9
        and min(a[1], b[1]) - 1e-9 <= point[1] <= max(a[1], b[1]) + 1e-9
    )


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    values = (_orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b))
    signs = tuple(0 if abs(value) <= 1e-9 else (1 if value > 0 else -1) for value in values)
    if signs[0] != signs[1] and signs[2] != signs[3]:
        return True
    return (
        (signs[0] == 0 and _on_segment(a, b, c))
        or (signs[1] == 0 and _on_segment(a, b, d))
        or (signs[2] == 0 and _on_segment(c, d, a))
        or (signs[3] == 0 and _on_segment(c, d, b))
    )


def _point_segment_distance(
    point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0.0 and dy == 0.0:
        return math.dist(point, a)
    amount = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.dist(point, (a[0] + amount * dx, a[1] + amount * dy))


def _shape_boundary(
    shape: int,
    start: tuple[float, float],
    current: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    if shape == SELECTION_LASSO:
        return polygon
    if shape == SELECTION_RECTANGLE:
        left, right = sorted((start[0], current[0]))
        top, bottom = sorted((start[1], current[1]))
        return ((left, top), (right, top), (right, bottom), (left, bottom))
    return ()


def _segment_hits_shape(
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    shape: int,
    start: tuple[float, float],
    current: tuple[float, float],
    radius: float,
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    arguments = dict(shape=shape, start=start, current=current, radius=radius, polygon=polygon)
    if _point_in_shape(a, **arguments) or _point_in_shape(b, **arguments):
        return True
    if shape == SELECTION_BRUSH:
        return _point_segment_distance(current, a, b) <= radius
    boundary = _shape_boundary(shape, start, current, polygon)
    return any(
        _segments_intersect(a, b, boundary[index - 1], boundary[index])
        for index in range(len(boundary))
    )


def _point_in_triangle(
    point: tuple[float, float], triangle: tuple[tuple[float, float], ...]
) -> bool:
    values = [_orientation(triangle[index - 1], triangle[index], point) for index in range(3)]
    return not (any(value < -1e-9 for value in values) and any(value > 1e-9 for value in values))


def _triangle_hits_shape(
    triangle: tuple[tuple[float, float], ...],
    *,
    shape: int,
    start: tuple[float, float],
    current: tuple[float, float],
    radius: float,
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    arguments = dict(shape=shape, start=start, current=current, radius=radius, polygon=polygon)
    if any(_point_in_shape(point, **arguments) for point in triangle):
        return True
    if shape == SELECTION_BRUSH and (
        _point_in_triangle(current, triangle)
        or any(_point_segment_distance(current, triangle[index - 1], triangle[index]) <= radius for index in range(3))
    ):
        return True
    if any(_segment_hits_shape(triangle[index - 1], triangle[index], **arguments) for index in range(3)):
        return True
    return any(_point_in_triangle(point, triangle) for point in _shape_boundary(shape, start, current, polygon))


def _deformation_gesture(
    handle: int,
    gesture_id: int,
    tool: int,
    *,
    current: tuple[float, float],
    radius: float,
    delta: tuple[float, float, float],
    strength: float = 1.0,
    camera_revision: int = 1,
    viewport_revision: int = 1,
) -> GestureRequest:
    request = GestureRequest()
    request.struct_size = ctypes.sizeof(GestureRequest)
    request.struct_version = ABI_VERSION
    request.session_handle = handle
    request.gesture_id = gesture_id
    request.mesh_revision = 1
    request.selection_revision = 2
    request.topology_generation = 1
    request.camera_revision = camera_revision
    request.viewport_revision = viewport_revision
    request.tool = tool
    request.xray = 1
    request.start_x, request.start_y = current
    request.current_x, request.current_y = current
    request.radius_pixels = radius
    request.strength = strength
    request.pressure = 1.0
    request.delta_x, request.delta_y, request.delta_z = delta
    return request


def _read_all_vertices(
    library: ctypes.CDLL,
    handle: int,
    count: int,
) -> list[tuple[float, float, float]]:
    return [_read_vertex(library, handle, index) for index in range(count)]


def test_native_interaction_abi_introspection_and_invalid_headers(abi: ctypes.CDLL) -> None:
    assert abi.cdmw_mesh_interaction_abi_version() == ABI_VERSION
    assert abi.cdmw_mesh_interaction_abi_contract() == b"cdmw_mesh_interaction_abi_v1"
    assert abi.cdmw_mesh_interaction_backend() == b"cdmw_mesh_core_0.1"
    assert abi.cdmw_mesh_interaction_abi_header_sha256().decode() == hashlib.sha256(
        HEADER_PATH.read_bytes()
    ).hexdigest()
    structures = [
        Submesh, Selection, OpenRequest, SessionRequest, SyncRequest, GestureRequest,
        AuthorityRequest, VertexRead, DirtyRange, SelectionChange, Result, Projection,
        PrepareSnapshotRequest,
    ]
    for struct_id, structure in enumerate(structures, start=1):
        assert abi.cdmw_mesh_interaction_struct_size(struct_id) == ctypes.sizeof(structure)

    invalid = OpenRequest()
    invalid.struct_size = ctypes.sizeof(OpenRequest) - 1
    invalid.struct_version = ABI_VERSION
    status, result = _call(abi, "open", invalid)
    assert status == INVALID_SIZE
    assert result.status == INVALID_SIZE
    invalid.struct_size = ctypes.sizeof(OpenRequest)
    invalid.struct_version = ABI_VERSION + 1
    status, result = _call(abi, "open", invalid)
    assert status == UNSUPPORTED_VERSION
    assert result.status == UNSUPPORTED_VERSION


def _exercise_resident_selection_gestures(abi: ctypes.CDLL, handle: int) -> None:
    _prepare_snapshot(abi, handle, 5, 2, xray=True)
    status, result = _call(abi, "begin", _selection_gesture(handle, 201, 5))
    assert status == OK
    assert result.selection_change_count == 2
    status, result = _call(
        abi,
        "update",
        _selection_gesture(handle, 201, 5, x=320.0, y=0.0),
    )
    assert status == OK
    assert result.selection_change_count == 1
    assert (result.selection_changes[0].first_element, result.selection_changes[0].selected) == (2, 1)
    status, result = _call(abi, "end", _selection_gesture(handle, 201, 5))
    assert status == OK
    assert result.operator_state == OPERATOR_AWAITING_AUTHORITY
    assert result.selection_change_count == 3
    assert {
        (result.selection_changes[index].first_element, result.selection_changes[index].selected)
        for index in range(result.selection_change_count)
    } == {(0, 1), (1, 0), (2, 1)}
    status, result = _call(
        abi,
        "apply_authoritative",
        _authority(
            handle,
            AUTHORITY_ACCEPTED,
            5,
            5,
            201,
            base_selection_revision=2,
            selection_revision=3,
        ),
    )
    assert status == OK
    assert result.selection_revision == 3

    _prepare_snapshot(abi, handle, 5, 3, xray=True)
    toggle = _selection_gesture(
        handle,
        202,
        5,
        selection_revision=3,
        operation=SELECTION_TOGGLE,
    )
    status, result = _call(abi, "begin", toggle)
    assert status == OK
    assert result.selection_change_count == 1
    assert (result.selection_changes[0].first_element, result.selection_changes[0].selected) == (0, 0)
    status, result = _call(abi, "update", toggle)
    assert status == OK
    assert result.selection_change_count == 0
    status, result = _call(abi, "end", toggle)
    assert status == OK
    assert result.selection_change_count == 1
    assert (result.selection_changes[0].first_element, result.selection_changes[0].selected) == (0, 0)
    status, result = _call(
        abi,
        "apply_authoritative",
        _authority(
            handle,
            AUTHORITY_REJECTED,
            5,
            5,
            202,
            base_selection_revision=3,
            selection_revision=4,
        ),
    )
    assert status == REJECTED
    assert result.operator_state == OPERATOR_IDLE


def test_native_interaction_abi_session_gesture_history_and_reopen(abi: ctypes.CDLL) -> None:
    positions = (ctypes.c_double * 12)(
        0.0, 0.0, 0.0,
        1.0, 0.0, 0.0,
        0.0, 1.0, 0.0,
        1.0, 1.0, 0.0,
    )
    triangles = (ctypes.c_uint32 * 6)(0, 1, 2, 2, 1, 3)
    submesh = Submesh(
        ctypes.sizeof(Submesh), ABI_VERSION, 0, 4, positions, None, 2, triangles
    )
    submeshes = (Submesh * 1)(submesh)
    opened = OpenRequest(
        ctypes.sizeof(OpenRequest), ABI_VERSION, 0xCD4D5701,
        1, 1, 1, 0, 0, 1, submeshes,
    )
    status, result = _call(abi, "open", opened)
    assert status == OK
    assert result.dirty_range_count == 1
    assert (result.dirty_ranges[0].first_vertex, result.dirty_ranges[0].vertex_count) == (0, 4)
    handle = result.session_handle
    assert handle > 0

    duplicate_status, _ = _call(abi, "open", opened)
    assert duplicate_status == SESSION_EXISTS

    selected_vertices = (ctypes.c_uint32 * 1)(1)
    selection = Selection(
        ctypes.sizeof(Selection), ABI_VERSION, 0, 1, selected_vertices,
        0, None, 0, None,
    )
    selections = (Selection * 1)(selection)
    sync = SyncRequest()
    sync.struct_size = ctypes.sizeof(SyncRequest)
    sync.struct_version = ABI_VERSION
    sync.session_handle = handle
    sync.flags = SYNC_SELECTION | SYNC_CAMERA | SYNC_VIEWPORT
    sync.base_selection_revision = 1
    sync.selection_revision = 2
    sync.base_camera_revision = 0
    sync.camera_revision = 1
    sync.base_viewport_revision = 0
    sync.viewport_revision = 1
    sync.selection_count = 1
    sync.selections = selections
    projection = Projection(
        ctypes.sizeof(Projection),
        ABI_VERSION,
        0,
        0,
        (ctypes.c_double * 16)(
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1,
        ),
    )
    projections = (Projection * 1)(projection)
    sync.projection_count = 1
    sync.projections = projections
    sync.world_view_projection = (ctypes.c_double * 16)(
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    )
    sync.viewport_width = 640
    sync.viewport_height = 480
    status, result = _call(abi, "sync", sync)
    assert status == OK
    assert result.selection_change_count == 1

    _prepare_snapshot(abi, handle, 1, 2, xray=False)

    status, result = _call(abi, "begin", _gesture(handle, 101, 1, 0.1))
    assert status == OK
    assert result.operator_state == OPERATOR_ACTIVE
    status, result = _call(abi, "update", _gesture(handle, 101, 1, 0.2))
    assert status == OK
    assert result.dirty_range_count == 1
    assert (result.dirty_ranges[0].first_vertex, result.dirty_ranges[0].vertex_count) == (1, 1)
    status, result = _call(abi, "end", _gesture(handle, 101, 1, 0.3))
    assert status == OK
    assert result.operator_state == OPERATOR_AWAITING_AUTHORITY
    assert result.dirty_range_count == 1
    assert (result.dirty_ranges[0].first_vertex, result.dirty_ranges[0].vertex_count) == (1, 1)
    assert _read_vertex(abi, handle, 1) == pytest.approx((1.0, 0.0, 0.2))

    status, result = _call(abi, "apply_authoritative", _authority(handle, AUTHORITY_ACCEPTED, 1, 2, 101))
    assert status == OK
    assert result.operator_state == OPERATOR_IDLE
    status, _ = _call(abi, "apply_authoritative", _authority(handle, AUTHORITY_UNDO, 2, 3))
    assert status == OK
    assert _read_vertex(abi, handle, 1) == pytest.approx((1.0, 0.0, 0.0))
    status, _ = _call(abi, "apply_authoritative", _authority(handle, AUTHORITY_REDO, 3, 4))
    assert status == OK
    assert _read_vertex(abi, handle, 1) == pytest.approx((1.0, 0.0, 0.2))

    _prepare_snapshot(abi, handle, 4, 2, xray=False)
    status, _ = _call(abi, "begin", _gesture(handle, 102, 4, 0.25))
    assert status == OK
    status, result = _call(abi, "cancel", _gesture(handle, 102, 4, 0.0))
    assert status == OK
    assert result.operator_state == OPERATOR_IDLE
    assert _read_vertex(abi, handle, 1) == pytest.approx((1.0, 0.0, 0.2))

    _prepare_snapshot(abi, handle, 4, 2, xray=False)
    status, _ = _call(abi, "begin", _gesture(handle, 103, 4, 0.4))
    assert status == OK
    status, _ = _call(abi, "end", _gesture(handle, 103, 4, 0.0))
    assert status == OK
    status, result = _call(abi, "apply_authoritative", _authority(handle, AUTHORITY_REJECTED, 4, 5, 103))
    assert status == REJECTED
    assert result.operator_state == OPERATOR_IDLE
    assert _read_vertex(abi, handle, 1) == pytest.approx((1.0, 0.0, 0.2))

    _exercise_resident_selection_gestures(abi, handle)

    close = SessionRequest(ctypes.sizeof(SessionRequest), ABI_VERSION, handle)
    status, _ = _call(abi, "close", close)
    assert status == OK
    read_after_close = VertexRead(
        ctypes.sizeof(VertexRead), ABI_VERSION, handle, 0, 0, 1, 3,
        (ctypes.c_double * 3)(), 0,
    )
    status, _ = _call(abi, "read_vertices", read_after_close)
    assert status == SESSION_NOT_FOUND

    reopened = OpenRequest(
        ctypes.sizeof(OpenRequest), ABI_VERSION, opened.session_key,
        5, 3, 1, 1, 1, 1, submeshes,
    )
    status, result = _call(abi, "open", reopened)
    assert status == OK
    assert result.session_handle != handle
    close = SessionRequest(ctypes.sizeof(SessionRequest), ABI_VERSION, result.session_handle)
    status, _ = _call(abi, "close", close)
    assert status == OK


@pytest.mark.parametrize("target", [SELECTION_VERTEX, SELECTION_EDGE, SELECTION_FACE])
@pytest.mark.parametrize("shape", [SELECTION_BRUSH, SELECTION_RECTANGLE, SELECTION_LASSO])
def test_indexed_selection_matches_exact_bruteforce(
    abi: ctypes.CDLL,
    target: int,
    shape: int,
) -> None:
    positions = [
        (-0.5, -0.5, 0.0),
        (0.5, -0.5, 0.0),
        (-0.5, 0.5, 0.0),
        (0.5, 0.5, 0.0),
    ]
    faces = [(0, 1, 2), (2, 1, 3)]
    start = (140.0, 340.0)
    current = (180.0, 380.0)
    radius = 24.0
    polygon = ((135.0, 335.0), (185.0, 335.0), (185.0, 385.0), (135.0, 385.0))
    if shape == SELECTION_BRUSH:
        start = current = (160.0, 360.0)
    projected = [_projected(position)[:2] for position in positions]
    arguments = dict(
        shape=shape,
        start=start,
        current=current,
        radius=radius,
        polygon=polygon,
    )
    if target == SELECTION_VERTEX:
        golden: set[object] = {
            index for index, point in enumerate(projected) if _point_in_shape(point, **arguments)
        }
    elif target == SELECTION_EDGE:
        edges = {
            tuple(sorted((face[index - 1], face[index])))
            for face in faces
            for index in range(3)
        }
        golden = {
            edge for edge in edges
            if _segment_hits_shape(projected[edge[0]], projected[edge[1]], **arguments)
        }
    else:
        golden = {
            index for index, face in enumerate(faces)
            if _triangle_hits_shape(tuple(projected[vertex] for vertex in face), **arguments)
        }

    handle, owners = _open_indexed_scene(
        abi,
        0xCD4D6000 + shape * 10 + target,
        positions,
        faces,
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)
        request = _indexed_selection_gesture(
            handle,
            shape * 10 + target,
            1,
            2,
            target=target,
            shape=shape,
            xray=True,
            start=start,
            current=current,
            radius=radius,
            points=polygon if shape == SELECTION_LASSO else (),
        )
        assert _finish_indexed_selection(abi, request) == golden
    finally:
        _close_indexed_scene(abi, handle)


def test_indexed_selection_operations_are_exact_and_ordered(abi: ctypes.CDLL) -> None:
    positions = [
        (-0.5, -0.5, 0.0),
        (0.5, -0.5, 0.0),
        (-0.5, 0.5, 0.0),
        (0.5, 0.5, 0.0),
    ]
    faces = [(0, 1, 2), (2, 1, 3)]
    handle, owners = _open_indexed_scene(abi, 0xCD4D6101, positions, faces)
    assert owners
    mesh_revision = 1
    selection_revision = 2
    selected: set[int] = set()
    operations = (
        (SELECTION_REPLACE, (160.0, 360.0), 0, True),
        (SELECTION_ADD, (480.0, 120.0), 3, True),
        (SELECTION_SUBTRACT, (160.0, 360.0), 0, False),
        (SELECTION_TOGGLE, (480.0, 120.0), 3, False),
    )
    try:
        for offset, (operation, point, index, added) in enumerate(operations, start=1):
            _prepare_snapshot(
                abi,
                handle,
                mesh_revision,
                selection_revision,
                xray=True,
            )
            request = _indexed_selection_gesture(
                handle,
                300 + offset,
                mesh_revision,
                selection_revision,
                target=SELECTION_VERTEX,
                shape=SELECTION_BRUSH,
                operation=operation,
                current=point,
                radius=20.0,
            )
            status, _ = _call(abi, "begin", request)
            assert status == OK
            status, result = _call(abi, "end", request)
            assert status == OK
            changes = {
                result.selection_changes[position].first_element:
                    bool(result.selection_changes[position].selected)
                for position in range(result.selection_change_count)
            }
            assert changes == {index: added}
            selected.add(index) if added else selected.discard(index)
            status, _ = _call(
                abi,
                "apply_authoritative",
                _authority(
                    handle,
                    AUTHORITY_ACCEPTED,
                    mesh_revision,
                    mesh_revision + 1,
                    request.gesture_id,
                    base_selection_revision=selection_revision,
                    selection_revision=selection_revision + 1,
                ),
            )
            assert status == OK
            mesh_revision += 1
            selection_revision += 1
        assert selected == set()
    finally:
        _close_indexed_scene(abi, handle)


def test_indexed_selection_handles_large_faces_and_visibility(abi: ctypes.CDLL) -> None:
    large_positions = [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (0.0, 1.0, 0.0)]
    handle, owners = _open_indexed_scene(
        abi,
        0xCD4D6201,
        large_positions,
        [(0, 1, 2)],
        viewport=(4096, 4096),
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)
        request = _indexed_selection_gesture(
            handle,
            401,
            1,
            2,
            target=SELECTION_FACE,
            shape=SELECTION_RECTANGLE,
            xray=True,
            start=(2032.0, 2032.0),
            current=(2064.0, 2064.0),
        )
        assert _finish_indexed_selection(abi, request) == {0}
    finally:
        _close_indexed_scene(abi, handle)

    overlapping = [
        (-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.0, 0.5, 0.0),
        (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.0, 0.5, 0.5),
    ]
    for xray, expected, key in ((False, {0}, 0xCD4D6202), (True, {0, 1}, 0xCD4D6203)):
        handle, owners = _open_indexed_scene(
            abi,
            key,
            overlapping,
            [(0, 1, 2), (3, 4, 5)],
        )
        assert owners
        try:
            _prepare_snapshot(abi, handle, 1, 2, xray=xray)
            request = _indexed_selection_gesture(
                handle,
                402 + int(xray),
                1,
                2,
                target=SELECTION_FACE,
                shape=SELECTION_BRUSH,
                xray=xray,
                current=(320.0, 240.0),
                radius=40.0,
            )
            assert _finish_indexed_selection(abi, request) == expected
        finally:
            _close_indexed_scene(abi, handle)


@pytest.mark.parametrize(
    ("tool", "point", "radius", "delta", "expected"),
    [
        (TOOL_MOVE, (320.0, 240.0), 60.0, (0.1, 0.2, 0.3), (0.1, 0.2, 0.3)),
        (TOOL_GRAB, (320.0, 240.0), 60.0, (0.1, 0.2, 0.3), (0.1, 0.2, 0.3)),
        (TOOL_SMOOTH, (320.0, 240.0), 60.0, (0.0, 0.0, 0.1), None),
        (TOOL_INFLATE, (320.0, 240.0), 60.0, (0.0, 0.0, 0.2), None),
        (TOOL_PINCH, (400.0, 240.0), 100.0, (0.0, 0.0, 0.2), None),
    ],
)
def test_indexed_deformation_matches_typed_golden_and_one_undo(
    abi: ctypes.CDLL,
    tool: int,
    point: tuple[float, float],
    radius: float,
    delta: tuple[float, float, float],
    expected: tuple[float, float, float] | None,
) -> None:
    positions = [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0)]
    handle, owners = _open_indexed_scene(
        abi,
        0xCD4D6300 + tool,
        positions,
        [(0, 1, 2)],
        selected_vertices=(0,),
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)
        begin = _deformation_gesture(
            handle, 500 + tool, tool, current=point, radius=radius, delta=(0.0, 0.0, 0.0)
        )
        update = _deformation_gesture(
            handle, 500 + tool, tool, current=point, radius=radius, delta=delta
        )
        status, begin_result = _call(abi, "begin", begin)
        assert status == OK
        if tool in (TOOL_SMOOTH, TOOL_INFLATE, TOOL_PINCH):
            assert begin_result.dirty_range_count > 0
        status, result = _call(abi, "update", update)
        assert status == OK
        assert result.dirty_range_count > 0
        status, result = _call(abi, "end", begin)
        assert status == OK
        assert result.operator_state == OPERATOR_AWAITING_AUTHORITY
        changed = _read_all_vertices(abi, handle, len(positions))
        if expected is not None:
            assert changed[0] == pytest.approx(expected, abs=1e-6)
        elif tool == TOOL_SMOOTH:
            assert 0.0 < changed[0][0] < 0.25
            assert 0.0 < changed[0][1] < 0.25
        elif tool == TOOL_INFLATE:
            assert changed[0][2] > 0.0
        else:
            assert 0.0 < changed[0][0] < 0.25
        assert changed[1] == pytest.approx(positions[1], abs=1e-6)
        assert changed[2] == pytest.approx(positions[2], abs=1e-6)

        status, _ = _call(
            abi,
            "apply_authoritative",
            _authority(handle, AUTHORITY_ACCEPTED, 1, 2, 500 + tool),
        )
        assert status == OK
        status, _ = _call(
            abi,
            "apply_authoritative",
            _authority(handle, AUTHORITY_UNDO, 2, 3),
        )
        assert status == OK
        assert _read_all_vertices(abi, handle, len(positions)) == pytest.approx(positions)
    finally:
        _close_indexed_scene(abi, handle)


@pytest.mark.parametrize(
    ("tool", "point", "radius"),
    [
        (TOOL_SMOOTH, (320.0, 240.0), 60.0),
        (TOOL_INFLATE, (320.0, 240.0), 60.0),
        (TOOL_PINCH, (360.0, 240.0), 80.0),
    ],
)
def test_sculpt_applies_an_initial_dab_without_a_selection(
    abi: ctypes.CDLL,
    tool: int,
    point: tuple[float, float],
    radius: float,
) -> None:
    positions = [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0)]
    handle, owners = _open_indexed_scene(
        abi, 0xCD4D6330 + tool, positions, [(0, 1, 2)]
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)
        begin = _deformation_gesture(
            handle,
            530 + tool,
            tool,
            current=point,
            radius=radius,
            delta=(0.0, 0.0, 0.0),
        )
        status, result = _call(abi, "begin", begin)
        assert status == OK
        assert result.dirty_range_count > 0
        changed = _read_all_vertices(abi, handle, len(positions))
        assert changed != pytest.approx(positions)

        status, result = _call(abi, "end", begin)
        assert status == OK
        assert result.operator_state == OPERATOR_AWAITING_AUTHORITY
        status, _ = _call(
            abi,
            "apply_authoritative",
            _authority(handle, AUTHORITY_REJECTED, 1, 2, 530 + tool),
        )
        assert status == REJECTED
        assert _read_all_vertices(abi, handle, len(positions)) == pytest.approx(positions)
    finally:
        _close_indexed_scene(abi, handle)


@pytest.mark.parametrize(
    ("tool", "point"),
    [
        (TOOL_GRAB, (336.0, 240.0)),
        (TOOL_SMOOTH, (336.0, 240.0)),
        (TOOL_INFLATE, (336.0, 240.0)),
        (TOOL_PINCH, (360.0, 240.0)),
    ],
)
def test_brush_tools_clip_the_cursor_scope_to_a_committed_selection(
    abi: ctypes.CDLL,
    tool: int,
    point: tuple[float, float],
) -> None:
    positions = [(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.5, 0.0)]
    handle, owners = _open_indexed_scene(
        abi,
        0xCD4D6360 + tool,
        positions,
        [(0, 1, 2)],
        selected_vertices=(0,),
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)
        begin = _deformation_gesture(
            handle,
            570 + tool,
            tool,
            current=point,
            radius=80.0,
            delta=(0.0, 0.0, 0.0),
        )
        status, _ = _call(abi, "begin", begin)
        assert status == OK
        if tool == TOOL_GRAB:
            update = _deformation_gesture(
                handle,
                570 + tool,
                tool,
                current=(point[0] + 20.0, point[1]),
                radius=80.0,
                delta=(0.1, 0.0, 0.0),
            )
            status, _ = _call(abi, "update", update)
            assert status == OK
        status, _ = _call(abi, "end", begin)
        assert status == OK
        changed = _read_all_vertices(abi, handle, len(positions))
        assert changed[0] != pytest.approx(positions[0])
        assert changed[1:] == pytest.approx(positions[1:])
    finally:
        _close_indexed_scene(abi, handle)


def test_move_rejects_an_empty_committed_selection(abi: ctypes.CDLL) -> None:
    positions = [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0)]
    handle, owners = _open_indexed_scene(
        abi, 0xCD4D6370, positions, [(0, 1, 2)]
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)
        begin = _deformation_gesture(
            handle,
            590,
            TOOL_MOVE,
            current=(320.0, 240.0),
            radius=60.0,
            delta=(0.0, 0.0, 0.0),
        )
        status, result = _call(abi, "begin", begin)
        assert status == INVALID_ARGUMENT
        assert b"Move requires a committed mesh selection" in bytes(result.message)
        assert result.operator_state == OPERATOR_IDLE
        assert _read_all_vertices(abi, handle, len(positions)) == pytest.approx(positions)
    finally:
        _close_indexed_scene(abi, handle)


@pytest.mark.parametrize("tool", [TOOL_MOVE, TOOL_GRAB])
def test_direct_deformation_tracks_the_full_pointer_delta_independent_of_brush_strength(
    abi: ctypes.CDLL,
    tool: int,
) -> None:
    positions = [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0)]
    handle, owners = _open_indexed_scene(
        abi,
        0xCD4D6340 + tool,
        positions,
        [(0, 1, 2)],
        selected_vertices=(0,),
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)
        begin = _deformation_gesture(
            handle,
            540 + tool,
            tool,
            current=(320.0, 240.0),
            radius=60.0,
            delta=(0.0, 0.0, 0.0),
            strength=0.25,
        )
        update = _deformation_gesture(
            handle,
            540 + tool,
            tool,
            current=(360.0, 240.0),
            radius=60.0,
            delta=(0.4, 0.0, 0.0),
            strength=0.25,
        )
        status, _ = _call(abi, "begin", begin)
        assert status == OK
        status, _ = _call(abi, "update", update)
        assert status == OK
        status, _ = _call(abi, "end", update)
        assert status == OK
        changed = _read_all_vertices(abi, handle, len(positions))
        assert changed[0] == pytest.approx((0.4, 0.0, 0.0))
        assert changed[1:] == pytest.approx(positions[1:])
    finally:
        _close_indexed_scene(abi, handle)


def test_indexed_pinch_uses_the_pointer_center_for_a_single_vertex_brush(
    abi: ctypes.CDLL,
) -> None:
    positions = [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0)]
    handle, owners = _open_indexed_scene(
        abi,
        0xCD4D6350,
        positions,
        [(0, 1, 2)],
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)
        begin = _deformation_gesture(
            handle, 560, TOOL_PINCH,
            current=(350.0, 240.0), radius=50.0, delta=(0.0, 0.0, 0.0),
        )
        update = _deformation_gesture(
            handle, 560, TOOL_PINCH,
            current=(350.0, 240.0), radius=50.0, delta=(0.0, 0.0, 0.2),
        )
        status, _ = _call(abi, "begin", begin)
        assert status == OK
        status, result = _call(abi, "update", update)
        assert status == OK
        assert result.dirty_range_count == 1
        status, _ = _call(abi, "end", begin)
        assert status == OK
        changed = _read_all_vertices(abi, handle, len(positions))
        assert 0.0 < changed[0][0] < 0.1
        assert changed[1:] == pytest.approx(positions[1:])
        status, _ = _call(
            abi,
            "apply_authoritative",
            _authority(handle, AUTHORITY_REJECTED, 1, 2, 560),
        )
        assert status == REJECTED
    finally:
        _close_indexed_scene(abi, handle)


@pytest.mark.parametrize("tool", [TOOL_MOVE, TOOL_GRAB, TOOL_SMOOTH, TOOL_INFLATE, TOOL_PINCH])
def test_indexed_deformation_cancel_restores_exact_baseline(
    abi: ctypes.CDLL,
    tool: int,
) -> None:
    positions = [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0)]
    point = (400.0, 240.0) if tool == TOOL_PINCH else (320.0, 240.0)
    radius = 100.0 if tool == TOOL_PINCH else 60.0
    handle, owners = _open_indexed_scene(
        abi,
        0xCD4D6400 + tool,
        positions,
        [(0, 1, 2)],
        selected_vertices=(0,),
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)
        begin = _deformation_gesture(
            handle, 600 + tool, tool, current=point, radius=radius, delta=(0.0, 0.0, 0.0)
        )
        update = _deformation_gesture(
            handle, 600 + tool, tool, current=point, radius=radius, delta=(0.1, 0.0, 0.2)
        )
        status, _ = _call(abi, "begin", begin)
        assert status == OK
        status, _ = _call(abi, "update", update)
        assert status == OK
        status, result = _call(abi, "cancel", begin)
        assert status == OK
        assert result.operator_state == OPERATOR_IDLE
        assert _read_all_vertices(abi, handle, len(positions)) == pytest.approx(positions)
    finally:
        _close_indexed_scene(abi, handle)


def test_indexed_grab_freezes_scope_and_sculpt_resamples_path(abi: ctypes.CDLL) -> None:
    positions = [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0)]
    handle, owners = _open_indexed_scene(
        abi, 0xCD4D6501, positions, [(0, 1, 2)], selected_vertices=(0,)
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)
        begin = _deformation_gesture(
            handle, 701, TOOL_GRAB, current=(320.0, 240.0), radius=45.0, delta=(0.0, 0.0, 0.0)
        )
        update = _deformation_gesture(
            handle, 701, TOOL_GRAB, current=(480.0, 240.0), radius=45.0, delta=(0.1, 0.0, 0.0)
        )
        status, _ = _call(abi, "begin", begin)
        assert status == OK
        status, _ = _call(abi, "update", update)
        assert status == OK
        status, _ = _call(abi, "end", update)
        assert status == OK
        changed = _read_all_vertices(abi, handle, len(positions))
        assert changed[0] == pytest.approx((0.1, 0.0, 0.0))
        assert changed[1] == pytest.approx(positions[1])
        status, _ = _call(abi, "apply_authoritative", _authority(handle, AUTHORITY_REJECTED, 1, 2, 701))
        assert status == REJECTED
    finally:
        _close_indexed_scene(abi, handle)

    handle, owners = _open_indexed_scene(
        abi, 0xCD4D6502, positions, [(0, 1, 2)]
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)
        begin = _deformation_gesture(
            handle, 702, TOOL_INFLATE, current=(320.0, 240.0), radius=55.0, delta=(0.0, 0.0, 0.0)
        )
        update = _deformation_gesture(
            handle, 702, TOOL_INFLATE, current=(480.0, 240.0), radius=55.0, delta=(0.0, 0.0, 0.3)
        )
        status, _ = _call(abi, "begin", begin)
        assert status == OK
        status, _ = _call(abi, "update", update)
        assert status == OK
        status, _ = _call(abi, "end", update)
        assert status == OK
        changed = _read_all_vertices(abi, handle, len(positions))
        assert changed[0][2] > 0.0
        assert changed[1][2] > 0.0
        assert changed[2] == pytest.approx(positions[2])
        status, _ = _call(abi, "apply_authoritative", _authority(handle, AUTHORITY_REJECTED, 1, 2, 702))
        assert status == REJECTED
    finally:
        _close_indexed_scene(abi, handle)


def test_snapshot_staleness_and_two_resident_sessions_are_isolated(abi: ctypes.CDLL) -> None:
    positions = [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0)]
    handles: list[int] = []
    owners: list[tuple[object, ...]] = []
    for offset in range(2):
        handle, retained = _open_indexed_scene(
            abi,
            0xCD4D6600 + offset,
            positions,
            [(0, 1, 2)],
            selected_vertices=(0,),
        )
        handles.append(handle)
        owners.append(retained)
    assert owners
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            prepared = list(pool.map(
                lambda handle: _prepare_snapshot(abi, handle, 1, 2, xray=True),
                handles,
            ))
        assert all(result.status == OK for result in prepared)

        def edit(index: int) -> tuple[int, int, int]:
            begin = _deformation_gesture(
                handles[index], 800 + index, TOOL_MOVE,
                current=(320.0, 240.0), radius=50.0,
                delta=(0.0, 0.0, 0.0),
            )
            update = _deformation_gesture(
                handles[index], 800 + index, TOOL_MOVE,
                current=(320.0, 240.0), radius=50.0,
                delta=(0.1 * (index + 1), 0.0, 0.0),
            )
            begin_status, _ = _call(abi, "begin", begin)
            update_status, _ = _call(abi, "update", update)
            end_status, _ = _call(abi, "end", begin)
            return begin_status, update_status, end_status

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(edit, range(2)))
        assert outcomes == [(OK, OK, OK), (OK, OK, OK)]
        assert _read_vertex(abi, handles[0], 0) == pytest.approx((0.1, 0.0, 0.0))
        assert _read_vertex(abi, handles[1], 0) == pytest.approx((0.2, 0.0, 0.0))
        for index, handle in enumerate(handles):
            status, _ = _call(
                abi,
                "apply_authoritative",
                _authority(handle, AUTHORITY_ACCEPTED, 1, 2, 800 + index),
            )
            assert status == OK

        sync = SyncRequest()
        sync.struct_size = ctypes.sizeof(SyncRequest)
        sync.struct_version = ABI_VERSION
        sync.session_handle = handles[0]
        sync.flags = SYNC_CAMERA
        sync.base_camera_revision = 1
        sync.camera_revision = 2
        sync.world_view_projection = (ctypes.c_double * 16)(
            1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1
        )
        status, _ = _call(abi, "sync", sync)
        assert status == OK
        stale = PrepareSnapshotRequest(
            ctypes.sizeof(PrepareSnapshotRequest), ABI_VERSION, handles[0],
            2, 2, 1, 1, 1, 1, 1, 1, 0,
        )
        status, _ = _call(abi, "prepare_snapshot_v1", stale)
        assert status == REVISION_MISMATCH
        gesture = _deformation_gesture(
            handles[0], 900, TOOL_MOVE,
            current=(320.0, 240.0), radius=50.0, delta=(0.0, 0.0, 0.0),
            camera_revision=2,
        )
        gesture.mesh_revision = 2
        status, _ = _call(abi, "begin", gesture)
        assert status == INVALID_STATE
        _prepare_snapshot(
            abi, handles[0], 2, 2, xray=True, camera_revision=2
        )
        status, _ = _call(abi, "begin", gesture)
        assert status == OK
        status, _ = _call(abi, "cancel", gesture)
        assert status == OK
    finally:
        for handle in handles:
            _close_indexed_scene(abi, handle)


def test_indexed_snapshot_remains_valid_across_selection_sync(abi: ctypes.CDLL) -> None:
    handle, owners = _open_indexed_scene(
        abi,
        0xCD4D6610,
        [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0)],
        [(0, 1, 2)],
        selected_vertices=(0,),
    )
    assert owners
    try:
        _prepare_snapshot(abi, handle, 1, 2, xray=True)

        selected_vertices = (ctypes.c_uint32 * 1)(1)
        selection = Selection(
            ctypes.sizeof(Selection), ABI_VERSION, 0,
            1, selected_vertices, 0, None, 0, None,
        )
        selections = (Selection * 1)(selection)
        sync = SyncRequest()
        sync.struct_size = ctypes.sizeof(SyncRequest)
        sync.struct_version = ABI_VERSION
        sync.session_handle = handle
        sync.flags = SYNC_SELECTION
        sync.base_selection_revision = 2
        sync.selection_revision = 3
        sync.selection_count = 1
        sync.selections = selections
        status, _ = _call(abi, "sync", sync)
        assert status == OK

        gesture = _selection_gesture(
            handle,
            910,
            1,
            selection_revision=3,
            x=320.0,
            y=240.0,
        )
        status, result = _call(abi, "begin", gesture)
        assert status == OK, bytes(result.message).split(b"\0", 1)[0].decode()
        status, _ = _call(abi, "cancel", gesture)
        assert status == OK
    finally:
        _close_indexed_scene(abi, handle)
