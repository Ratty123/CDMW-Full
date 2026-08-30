from __future__ import annotations

import hashlib
import math
import mmap
import re
import struct
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_deformer import recompute_mesh_normals
from cdmw.modding.mesh_parser import SubMesh
from cdmw.services.mesh_service_kernel import _record_session_edit_operations
from cdmw.services.mesh_service_native_session import _close_native_editor_session
from cdmw.services.mesh_service_state import (
    _MeshEditSession,
    _MeshHistorySnapshot,
    _MeshVertexPositionDelta,
)


RESIDENT_INTERACTION_FORMAT_VERSION = 1
RESIDENT_INTERACTION_MAPPING_PREFIX = "Local\\CDMW.MeshInteraction."
RESIDENT_INTERACTION_MAX_BYTES = 128 * 1024 * 1024

_MAGIC = b"CDMWMIT1"
_HEADER = struct.Struct("<8sIIIIQQQQQQQIIQ")
_GEOMETRY_GROUP = struct.Struct("<iI")
_VERTEX_POSITION = struct.Struct("<I3d")
_SELECTION_CHANGE = struct.Struct("<iIIIII")
_MAPPING_NAME = re.compile(r"Local\\CDMW\.MeshInteraction\.[0-9a-fA-F]{32}")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")

_FLAG_GEOMETRY = 1
_FLAG_SELECTION = 2
_VALID_FLAGS = _FLAG_GEOMETRY | _FLAG_SELECTION
_TOOL_ACTION = {
    1: ("select", "Select"),
    2: ("transform", "Move"),
    3: ("brush", "Grab"),
    4: ("brush", "Smooth"),
    5: ("brush", "Inflate"),
    6: ("brush", "Pinch"),
}


@dataclass(frozen=True, slots=True)
class ResidentGeometryGroup:
    submesh_index: int
    positions: tuple[tuple[int, tuple[float, float, float]], ...]


@dataclass(frozen=True, slots=True)
class ResidentSelectionChange:
    submesh_index: int
    target: int
    first_element: int
    second_element: int
    selected: bool


@dataclass(frozen=True, slots=True)
class ResidentInteractionTransaction:
    tool: int
    flags: int
    session_key: int
    gesture_id: int
    base_revision: int
    target_revision: int
    base_selection_revision: int
    target_selection_revision: int
    topology_generation: int
    geometry_groups: tuple[ResidentGeometryGroup, ...]
    selection_changes: tuple[ResidentSelectionChange, ...]


def resident_interaction_session_key(session_id: str) -> int:
    digest = hashlib.sha256(str(session_id).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little", signed=False)


def parse_resident_interaction_transaction(data: bytes) -> ResidentInteractionTransaction:
    if len(data) < _HEADER.size:
        raise ValueError("Resident interaction transaction is shorter than its header.")
    fields = _HEADER.unpack_from(data)
    _validate_header(fields, len(data))
    cursor = _HEADER.size
    geometry_groups, cursor = _parse_geometry_groups(data, cursor, int(fields[12]))
    selection_changes, cursor = _parse_selection_changes(data, cursor, int(fields[13]))
    if cursor != len(data):
        raise ValueError("Resident interaction transaction has trailing bytes.")
    return ResidentInteractionTransaction(
        tool=int(fields[3]),
        flags=int(fields[4]),
        session_key=int(fields[5]),
        gesture_id=int(fields[6]),
        base_revision=int(fields[7]),
        target_revision=int(fields[8]),
        base_selection_revision=int(fields[9]),
        target_selection_revision=int(fields[10]),
        topology_generation=int(fields[11]),
        geometry_groups=geometry_groups,
        selection_changes=selection_changes,
    )


def _validate_header(fields: Sequence[object], actual_length: int) -> None:
    magic, version, header_size, tool, flags = fields[:5]
    if magic != _MAGIC:
        raise ValueError("Resident interaction transaction magic is invalid.")
    if int(version) != RESIDENT_INTERACTION_FORMAT_VERSION or int(header_size) != _HEADER.size:
        raise ValueError("Resident interaction transaction version or header size is unsupported.")
    if int(tool) not in _TOOL_ACTION:
        raise ValueError("Resident interaction transaction tool is unsupported.")
    if int(flags) & ~_VALID_FLAGS:
        raise ValueError("Resident interaction transaction flags are invalid.")
    if int(fields[6]) <= 0:
        raise ValueError("Resident interaction transaction gesture id must be positive.")
    if int(fields[14]) != actual_length:
        raise ValueError("Resident interaction transaction length does not match its header.")


def _parse_geometry_groups(
    data: bytes,
    cursor: int,
    count: int,
) -> tuple[tuple[ResidentGeometryGroup, ...], int]:
    groups: list[ResidentGeometryGroup] = []
    seen_submeshes: set[int] = set()
    for _ in range(count):
        submesh_index, vertex_count = _unpack(_GEOMETRY_GROUP, data, cursor)
        cursor += _GEOMETRY_GROUP.size
        if int(submesh_index) in seen_submeshes:
            raise ValueError("Resident interaction transaction repeats a geometry submesh.")
        seen_submeshes.add(int(submesh_index))
        positions: list[tuple[int, tuple[float, float, float]]] = []
        seen_vertices: set[int] = set()
        for _vertex in range(int(vertex_count)):
            values = _unpack(_VERTEX_POSITION, data, cursor)
            cursor += _VERTEX_POSITION.size
            vertex_index = int(values[0])
            position = (float(values[1]), float(values[2]), float(values[3]))
            if vertex_index in seen_vertices or not all(math.isfinite(value) for value in position):
                raise ValueError("Resident interaction transaction has duplicate or non-finite vertex data.")
            seen_vertices.add(vertex_index)
            positions.append((vertex_index, position))
        groups.append(ResidentGeometryGroup(int(submesh_index), tuple(positions)))
    return tuple(groups), cursor


def _parse_selection_changes(
    data: bytes,
    cursor: int,
    count: int,
) -> tuple[tuple[ResidentSelectionChange, ...], int]:
    changes: list[ResidentSelectionChange] = []
    seen: set[tuple[int, int, int, int]] = set()
    for _ in range(count):
        values = _unpack(_SELECTION_CHANGE, data, cursor)
        cursor += _SELECTION_CHANGE.size
        submesh, target, first, second, element_count, selected = map(int, values)
        identity = (submesh, target, first, second)
        if target not in {1, 2, 3} or element_count != 1 or selected not in {0, 1} or identity in seen:
            raise ValueError("Resident interaction transaction has an invalid selection change.")
        seen.add(identity)
        changes.append(ResidentSelectionChange(submesh, target, first, second, bool(selected)))
    return tuple(changes), cursor


def _unpack(record: struct.Struct, data: bytes, cursor: int) -> tuple[object, ...]:
    if cursor < 0 or cursor + record.size > len(data):
        raise ValueError("Resident interaction transaction is truncated.")
    return record.unpack_from(data, cursor)


def read_resident_interaction_transaction(
    descriptor: Mapping[str, object],
) -> ResidentInteractionTransaction:
    mapping_name = str(descriptor.get("mapping_name") or "")
    length = _descriptor_int(descriptor, "length", minimum=_HEADER.size)
    expected_hash = str(descriptor.get("sha256") or "")
    if _MAPPING_NAME.fullmatch(mapping_name) is None:
        raise ValueError("Resident interaction mapping name is invalid.")
    if length > RESIDENT_INTERACTION_MAX_BYTES:
        raise ValueError("Resident interaction mapping exceeds the size limit.")
    if _SHA256.fullmatch(expected_hash) is None:
        raise ValueError("Resident interaction mapping SHA-256 is invalid.")
    with mmap.mmap(-1, length, tagname=mapping_name, access=mmap.ACCESS_READ) as mapping:
        data = mapping[:]
    if len(data) != length or hashlib.sha256(data).hexdigest() != expected_hash.lower():
        raise ValueError("Resident interaction mapping length or SHA-256 does not match.")
    transaction = parse_resident_interaction_transaction(data)
    _validate_descriptor(transaction, descriptor)
    return transaction


def _descriptor_int(descriptor: Mapping[str, object], name: str, *, minimum: int = 0) -> int:
    value = descriptor.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"Resident interaction descriptor {name} is invalid.")
    return value


def _validate_descriptor(
    transaction: ResidentInteractionTransaction,
    descriptor: Mapping[str, object],
) -> None:
    session_id = str(descriptor.get("session_id") or "")
    expected = {
        "format_version": RESIDENT_INTERACTION_FORMAT_VERSION,
        "gesture_id": transaction.gesture_id,
        "base_revision": transaction.base_revision,
        "base_selection_revision": transaction.base_selection_revision,
        "topology_generation": transaction.topology_generation,
    }
    if not session_id or transaction.session_key != resident_interaction_session_key(session_id):
        raise ValueError("Resident interaction descriptor session identity does not match.")
    for name, value in expected.items():
        if _descriptor_int(descriptor, name) != value:
            raise ValueError(f"Resident interaction descriptor {name} does not match the mapping.")


def apply_resident_interaction_transaction(
    service: object,
    session: _MeshEditSession,
    command: MeshEditCommand,
):
    descriptor = command.params or {}
    transaction = read_resident_interaction_transaction(descriptor)
    _validate_service_revisions(session, transaction, descriptor)
    geometry = _prepare_geometry(session, transaction)
    selection = _prepare_selection(session, transaction)
    stop_event = descriptor.get("stop_event")
    raise_if_cancelled(stop_event, "Resident interaction transaction cancelled.")
    if not geometry[0] and selection == session.selection:
        action, _label = _TOOL_ACTION[transaction.tool]
        return service._result(session, action, status="noop")
    _retire_legacy_native_session(session)
    _commit_transaction(service, session, command, transaction, geometry, selection)
    action, _label = _TOOL_ACTION[transaction.tool]
    changed = {delta.submesh_index: delta.vertex_indices for delta in geometry[0]}
    return service._result(
        session,
        action,
        affected=set(changed),
        changed=changed,
        native_selection_groups=_selection_groups(selection) if action == "select" else (),
        native_preview_vertex_update_groups=_preview_vertex_update_groups(session, changed),
        metrics={
            "resident_transaction_bytes": float(_descriptor_int(descriptor, "length")),
            "resident_transaction_gesture_id": float(transaction.gesture_id),
        },
    )


def _validate_service_revisions(
    session: _MeshEditSession,
    transaction: ResidentInteractionTransaction,
    descriptor: Mapping[str, object],
) -> None:
    if str(descriptor.get("session_id") or "") != session.session_id:
        raise ValueError("Resident interaction transaction targets another session.")
    geometry = bool(transaction.flags & _FLAG_GEOMETRY)
    selection = bool(transaction.flags & _FLAG_SELECTION)
    if geometry != bool(transaction.geometry_groups) or selection != bool(transaction.selection_changes):
        raise ValueError("Resident interaction transaction flags do not match its payload.")
    if (transaction.tool == 1) != selection or (transaction.tool != 1) != geometry:
        raise ValueError("Resident interaction transaction tool does not match its payload kind.")
    current_revision = 1 + session.revision + session.selection_revision
    if transaction.base_revision != current_revision or transaction.base_selection_revision != session.selection_revision:
        raise RuntimeError("Resident interaction transaction is stale.")
    if transaction.topology_generation != session.topology_operation_revision:
        raise RuntimeError("Resident interaction transaction topology generation is stale.")
    expected_target = current_revision + int(geometry or selection)
    expected_selection = session.selection_revision + int(selection)
    if transaction.target_revision != expected_target or transaction.target_selection_revision != expected_selection:
        raise ValueError("Resident interaction transaction target revisions are invalid.")


def _retire_legacy_native_session(session: _MeshEditSession) -> None:
    if session.native_editor_mesh_dirty:
        raise RuntimeError("Resident interaction transaction cannot replace unexported native edits.")
    native_markers = any(snapshot.native_editor_history for snapshot in (*session.undo_stack, *session.redo_stack))
    if session.native_editor_session_ready and (native_markers or session.native_history_undo_count):
        raise RuntimeError("Resident interaction transaction cannot discard native history.")
    if session.native_editor_session_ready:
        _close_native_editor_session(session)


def _prepare_geometry(
    session: _MeshEditSession,
    transaction: ResidentInteractionTransaction,
) -> tuple[tuple[_MeshVertexPositionDelta, ...], dict[int, list[tuple[float, float, float]]]]:
    deltas: list[_MeshVertexPositionDelta] = []
    updated: dict[int, list[tuple[float, float, float]]] = {}
    for group in transaction.geometry_groups:
        if not 0 <= group.submesh_index < len(session.working_mesh.submeshes):
            raise ValueError("Resident interaction transaction submesh is out of range.")
        vertices = list(session.working_mesh.submeshes[group.submesh_index].vertices or ())
        indices: list[int] = []
        before: list[tuple[float, float, float]] = []
        for vertex_index, position in group.positions:
            if not 0 <= vertex_index < len(vertices):
                raise ValueError("Resident interaction transaction vertex is out of range.")
            if tuple(vertices[vertex_index]) == position:
                continue
            indices.append(vertex_index)
            before.append(tuple(vertices[vertex_index]))
            vertices[vertex_index] = position
        if indices:
            deltas.append(_MeshVertexPositionDelta(group.submesh_index, tuple(indices), tuple(before)))
            updated[group.submesh_index] = vertices
    return tuple(deltas), updated


def _prepare_selection(
    session: _MeshEditSession,
    transaction: ResidentInteractionTransaction,
) -> MeshEditSelection:
    vertices = session.selection.vertex_map()
    edges = session.selection.edge_map()
    faces = session.selection.face_map()
    for change in transaction.selection_changes:
        if not 0 <= change.submesh_index < len(session.working_mesh.submeshes):
            raise ValueError("Resident interaction selection submesh is out of range.")
        submesh = session.working_mesh.submeshes[change.submesh_index]
        if change.target == 1:
            _change_set(vertices, change.submesh_index, change.first_element, len(submesh.vertices), change.selected)
        elif change.target == 2:
            if change.first_element == change.second_element:
                raise ValueError("Resident interaction selection edge is invalid.")
            edge = tuple(sorted((change.first_element, change.second_element)))
            _change_set(edges, change.submesh_index, edge, len(submesh.vertices), change.selected)
        else:
            _change_set(faces, change.submesh_index, change.first_element, len(submesh.faces or ()), change.selected)
    return MeshEditSelection.from_maps(
        vertices_by_submesh=vertices,
        edges_by_submesh=edges,
        faces_by_submesh=faces,
        source_indices=session.selection.source_indices,
    )


def _change_set(
    values: dict[int, set[object]],
    submesh_index: int,
    element: object,
    bound: int,
    selected: bool,
) -> None:
    indices = element if isinstance(element, tuple) else (element,)
    if any(not isinstance(index, int) or not 0 <= index < bound for index in indices):
        raise ValueError("Resident interaction selection element is out of range.")
    current = values.setdefault(submesh_index, set())
    if (element in current) == selected:
        raise ValueError("Resident interaction selection change is redundant.")
    current.add(element) if selected else current.discard(element)
    if not current:
        values.pop(submesh_index, None)


def _commit_transaction(
    service: object,
    session: _MeshEditSession,
    command: MeshEditCommand,
    transaction: ResidentInteractionTransaction,
    geometry: tuple[tuple[_MeshVertexPositionDelta, ...], dict[int, list[tuple[float, float, float]]]],
    selection: MeshEditSelection,
) -> None:
    deltas, updated = geometry
    action, label = _TOOL_ACTION[transaction.tool]
    snapshot = _MeshHistorySnapshot(
        mesh=None,
        mode=session.mode,
        selection=session.selection,
        edit_operations=tuple(session.edit_operations),
        vertex_position_deltas=deltas,
        history_action=action,
        history_label=str(command.label or label),
        selection_only=not bool(deltas),
        object_transform=session.object_transform,
    )
    _clear_history(service, session.redo_stack)
    service._push_history_snapshot(session, snapshot)
    for submesh_index, vertices in updated.items():
        session.working_mesh.submeshes[submesh_index].vertices = vertices
    if deltas:
        recompute_mesh_normals(session.working_mesh)
        session.revision += 1
        public_command = MeshEditCommand(action, params={"recompute_normals": True}, label=str(command.label or label))
        changed = {delta.submesh_index: delta.vertex_indices for delta in deltas}
        _record_session_edit_operations(session, action, public_command, changed, changed, topology_changed=False)
    if selection != session.selection:
        session.selection = selection
        session.selection_revision += 1
    service._trim_session_history(session)
    autosave = getattr(service, "_schedule_mesh_layer_autosave", None)
    if deltas and callable(autosave):
        autosave(session)


def _clear_history(service: object, stack: list[_MeshHistorySnapshot]) -> None:
    disposer = getattr(service, "_dispose_history_snapshot", None)
    if not callable(disposer):
        disposer = getattr(sys.modules.get("cdmw.services.mesh_service"), "_dispose_history_snapshot", None)
    while stack:
        snapshot = stack.pop()
        if callable(disposer):
            disposer(snapshot)


def _selection_groups(selection: MeshEditSelection) -> tuple[Mapping[str, object], ...]:
    vertices = selection.vertex_map()
    edges = selection.edge_map()
    faces = selection.face_map()
    sources = set(selection.source_indices)
    groups: list[Mapping[str, object]] = []
    for submesh_index in sorted(set(vertices) | set(edges) | set(faces) | sources):
        group: dict[str, object] = {"source_submesh_index": submesh_index}
        if vertices.get(submesh_index):
            group["source_vertex_indices"] = sorted(vertices[submesh_index])
        if edges.get(submesh_index):
            group["source_edges"] = [list(edge) for edge in sorted(edges[submesh_index])]
        if faces.get(submesh_index):
            group["source_face_indices"] = sorted(faces[submesh_index])
        if submesh_index in sources:
            group["source_selected"] = True
        if len(group) > 1:
            groups.append(group)
    return tuple(groups)


def _preview_vertex_update_groups(
    session: _MeshEditSession,
    changed: Mapping[int, Sequence[int]],
) -> tuple[Mapping[str, object], ...]:
    groups: list[Mapping[str, object]] = []
    for submesh_index, raw_indices in sorted(changed.items()):
        submesh = session.working_mesh.submeshes[submesh_index]
        indices = _preview_vertex_indices(submesh, raw_indices)
        positions = [component for index in indices for component in submesh.vertices[index]]
        normals = (
            [component for index in indices for component in submesh.normals[index]]
            if len(submesh.normals or ()) == len(submesh.vertices)
            else []
        )
        groups.append(
            {
                "preview_backend": "cdmw_mesh_core",
                "source_submesh_index": submesh_index,
                "source_vertex_indices": list(indices),
                "positions": positions,
                "normals": normals,
                "uvs": [],
            }
        )
    return tuple(groups)


def _preview_vertex_indices(submesh: SubMesh, changed: Sequence[int]) -> tuple[int, ...]:
    changed_indices = {int(index) for index in changed}
    indices = set(changed_indices)
    for face in tuple(submesh.faces or ()):
        if any(int(index) in changed_indices for index in face):
            indices.update(
                int(index)
                for index in face
                if 0 <= int(index) < len(submesh.vertices or ())
            )
    return tuple(sorted(indices))


__all__ = [
    "RESIDENT_INTERACTION_FORMAT_VERSION",
    "RESIDENT_INTERACTION_MAPPING_PREFIX",
    "ResidentInteractionTransaction",
    "apply_resident_interaction_transaction",
    "parse_resident_interaction_transaction",
    "read_resident_interaction_transaction",
    "resident_interaction_session_key",
]
