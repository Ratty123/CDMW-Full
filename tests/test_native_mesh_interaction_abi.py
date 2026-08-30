from __future__ import annotations

import ctypes
import hashlib
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
REJECTED = 10

SYNC_SELECTION = 1 << 1
SYNC_CAMERA = 1 << 3
SYNC_VIEWPORT = 1 << 4
TOOL_MOVE = 2
TOOL_SELECT = 1
SELECTION_VERTEX = 1
SELECTION_BRUSH = 1
SELECTION_REPLACE = 1
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
    assert _read_vertex(abi, handle, 1) == pytest.approx((1.0, 0.0, 0.6))

    status, result = _call(abi, "apply_authoritative", _authority(handle, AUTHORITY_ACCEPTED, 1, 2, 101))
    assert status == OK
    assert result.operator_state == OPERATOR_IDLE
    status, _ = _call(abi, "apply_authoritative", _authority(handle, AUTHORITY_UNDO, 2, 3))
    assert status == OK
    assert _read_vertex(abi, handle, 1) == pytest.approx((1.0, 0.0, 0.0))
    status, _ = _call(abi, "apply_authoritative", _authority(handle, AUTHORITY_REDO, 3, 4))
    assert status == OK
    assert _read_vertex(abi, handle, 1) == pytest.approx((1.0, 0.0, 0.6))

    status, _ = _call(abi, "begin", _gesture(handle, 102, 4, 0.25))
    assert status == OK
    status, result = _call(abi, "cancel", _gesture(handle, 102, 4, 0.0))
    assert status == OK
    assert result.operator_state == OPERATOR_IDLE
    assert _read_vertex(abi, handle, 1) == pytest.approx((1.0, 0.0, 0.6))

    status, _ = _call(abi, "begin", _gesture(handle, 103, 4, 0.4))
    assert status == OK
    status, _ = _call(abi, "end", _gesture(handle, 103, 4, 0.0))
    assert status == OK
    status, result = _call(abi, "apply_authoritative", _authority(handle, AUTHORITY_REJECTED, 4, 5, 103))
    assert status == REJECTED
    assert result.operator_state == OPERATOR_IDLE
    assert _read_vertex(abi, handle, 1) == pytest.approx((1.0, 0.0, 0.6))

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
