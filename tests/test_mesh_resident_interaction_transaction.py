from __future__ import annotations

import hashlib
import mmap
import struct
import threading
from uuid import uuid4

import pytest

from cdmw.domain.mesh import MeshEditCommand
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.models import RunCancelled
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service_resident_transaction import resident_interaction_session_key
from cdmw.ui.mesh_editor.controller import MeshEditorController


_HEADER = struct.Struct("<8sIIIIQQQQQQQIIQ")
_GEOMETRY_GROUP = struct.Struct("<iI")
_VERTEX = struct.Struct("<I3d")
_SELECTION = struct.Struct("<iIIIII")


def _mesh() -> ParsedMesh:
    return ParsedMesh(
        format="pac",
        path="character/model/resident.pac",
        submeshes=[
            SubMesh(
                name="body",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                faces=[(0, 1, 2)],
                vertex_count=3,
                face_count=1,
            )
        ],
    )


def _transaction_bytes(
    service: MeshService,
    session_id: str,
    *,
    gesture_id: int,
    tool: int,
    geometry: tuple[tuple[int, tuple[tuple[int, tuple[float, float, float]], ...]], ...] = (),
    selection: tuple[tuple[int, int, int, int, bool], ...] = (),
) -> tuple[bytes, dict[str, object]]:
    session = service._sessions[session_id]
    base_revision = service.session_view(session_id).resident_revision
    flags = (1 if geometry else 0) | (2 if selection else 0)
    target_revision = base_revision + int(bool(flags))
    target_selection = session.selection_revision + int(bool(selection))
    body = bytearray()
    for submesh_index, records in geometry:
        body.extend(_GEOMETRY_GROUP.pack(submesh_index, len(records)))
        for vertex_index, position in records:
            body.extend(_VERTEX.pack(vertex_index, *position))
    for submesh, target, first, second, selected in selection:
        body.extend(_SELECTION.pack(submesh, target, first, second, 1, int(selected)))
    length = _HEADER.size + len(body)
    header = _HEADER.pack(
        b"CDMWMIT1",
        1,
        _HEADER.size,
        tool,
        flags,
        resident_interaction_session_key(session_id),
        gesture_id,
        base_revision,
        target_revision,
        session.selection_revision,
        target_selection,
        session.topology_operation_revision,
        len(geometry),
        len(selection),
        length,
    )
    payload = header + body
    descriptor: dict[str, object] = {
        "session_id": session_id,
        "gesture_id": gesture_id,
        "base_revision": base_revision,
        "base_selection_revision": session.selection_revision,
        "topology_generation": session.topology_operation_revision,
        "format_version": 1,
        "length": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    return payload, descriptor


def _mapped_command(payload: bytes, descriptor: dict[str, object], *, label: str):
    mapping_name = f"Local\\CDMW.MeshInteraction.{uuid4().hex}"
    mapping = mmap.mmap(-1, len(payload), tagname=mapping_name)
    mapping.write(payload)
    mapping.seek(0)
    command = MeshEditCommand(
        "_resident_interaction_transaction",
        params={**descriptor, "mapping_name": mapping_name},
        label=label,
    )
    return mapping, command


def _apply(
    service: MeshService,
    session_id: str,
    payload: bytes,
    descriptor: dict[str, object],
    *,
    label: str,
):
    mapping, command = _mapped_command(payload, descriptor, label=label)
    try:
        return service.apply_command(session_id, command)
    finally:
        mapping.close()


def test_geometry_transaction_commits_one_history_entry_and_undo_redo_are_exact() -> None:
    service = MeshService()
    view = service.open_edit_session(_mesh(), session_id="resident-grab", mode="edit")
    baseline = tuple(service.working_mesh(view.session_id).submeshes[0].vertices)
    committed = (1.25, 0.25, 0.5)
    payload, descriptor = _transaction_bytes(
        service,
        view.session_id,
        gesture_id=101,
        tool=3,
        geometry=((0, ((1, committed),)),),
    )

    result = _apply(service, view.session_id, payload, descriptor, label="Grab")

    assert result.ok and result.action == "brush"
    assert result.native_preview_vertex_update_groups == (
        {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [0, 1, 2],
            "positions": [
                component
                for vertex in service.working_mesh(view.session_id).submeshes[0].vertices
                for component in vertex
            ],
            "normals": [
                component
                for normal in service.working_mesh(view.session_id).submeshes[0].normals
                for component in normal
            ],
            "uvs": [],
        },
    )
    assert service.working_mesh(view.session_id).submeshes[0].vertices[1] == committed
    assert len(service._sessions[view.session_id].undo_stack) == 1
    assert service.undo(view.session_id).ok
    assert tuple(service.working_mesh(view.session_id).submeshes[0].vertices) == baseline
    assert service.redo(view.session_id).ok
    assert service.working_mesh(view.session_id).submeshes[0].vertices[1] == committed


def test_geometry_transaction_result_is_a_native_resident_vertex_update() -> None:
    service = MeshService()
    controller = MeshEditorController(mesh_service=service)
    view = controller.open_mesh(_mesh(), session_id="resident-preview", mode="edit")
    payload, descriptor = _transaction_bytes(
        service,
        view.session_id,
        gesture_id=102,
        tool=3,
        geometry=((0, ((1, (1.5, 0.25, 0.75)),)),),
    )

    result = _apply(service, view.session_id, payload, descriptor, label="Grab")
    update = controller.native_update_for_result(result)

    assert len(update.vertex_groups) == 1
    assert update.vertex_groups[0]["preview_backend"] == "cdmw_mesh_core"
    assert update.vertex_groups[0]["source_vertex_indices"] == [0, 1, 2]
    assert update.vertex_groups[0]["positions"][3:6] == [1.5, 0.25, 0.75]


def test_grab_undo_then_grab_rearms_and_replaces_redo_branch() -> None:
    service = MeshService()
    view = service.open_edit_session(_mesh(), session_id="resident-rearm", mode="edit")
    baseline = tuple(service.working_mesh(view.session_id).submeshes[0].vertices)
    first, first_descriptor = _transaction_bytes(
        service,
        view.session_id,
        gesture_id=201,
        tool=3,
        geometry=((0, ((0, (0.0, 0.0, 0.4)),)),),
    )
    _apply(service, view.session_id, first, first_descriptor, label="Grab")
    service.undo(view.session_id)
    second, second_descriptor = _transaction_bytes(
        service,
        view.session_id,
        gesture_id=202,
        tool=3,
        geometry=((0, ((0, (0.0, 0.0, 0.8)),)),),
    )

    _apply(service, view.session_id, second, second_descriptor, label="Grab")

    session = service._sessions[view.session_id]
    assert len(session.undo_stack) == 1
    assert session.redo_stack == []
    assert service.undo(view.session_id).ok
    assert tuple(service.working_mesh(view.session_id).submeshes[0].vertices) == baseline


def test_selection_transaction_has_one_exact_history_entry() -> None:
    service = MeshService()
    view = service.open_edit_session(_mesh(), session_id="resident-select", mode="edit")
    payload, descriptor = _transaction_bytes(
        service,
        view.session_id,
        gesture_id=301,
        tool=1,
        selection=((0, 1, 2, 0, True),),
    )

    result = _apply(service, view.session_id, payload, descriptor, label="Select")

    assert result.ok and result.action == "select"
    assert service.session_view(view.session_id).selection.vertex_map() == {0: {2}}
    assert len(service._sessions[view.session_id].undo_stack) == 1
    assert service.undo(view.session_id).ok
    assert service.session_view(view.session_id).selection.is_empty()
    assert service.redo(view.session_id).ok
    assert service.session_view(view.session_id).selection.vertex_map() == {0: {2}}


def test_duplicate_stale_transaction_is_rejected_without_second_history_entry() -> None:
    service = MeshService()
    view = service.open_edit_session(_mesh(), session_id="resident-stale", mode="edit")
    payload, descriptor = _transaction_bytes(
        service,
        view.session_id,
        gesture_id=401,
        tool=5,
        geometry=((0, ((2, (0.0, 1.0, 0.2)),)),),
    )
    mapping, command = _mapped_command(payload, descriptor, label="Inflate")
    try:
        assert service.apply_command(view.session_id, command).ok
        with pytest.raises(RuntimeError, match="stale"):
            service.apply_command(view.session_id, command)
    finally:
        mapping.close()
    assert len(service._sessions[view.session_id].undo_stack) == 1


def test_hash_mismatch_and_cancellation_publish_no_geometry_or_history() -> None:
    service = MeshService()
    view = service.open_edit_session(_mesh(), session_id="resident-reject", mode="edit")
    baseline = tuple(service.working_mesh(view.session_id).submeshes[0].vertices)
    payload, descriptor = _transaction_bytes(
        service,
        view.session_id,
        gesture_id=501,
        tool=6,
        geometry=((0, ((0, (0.2, 0.0, 0.0)),)),),
    )
    bad = dict(descriptor)
    bad["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        _apply(service, view.session_id, payload, bad, label="Pinch")

    stop = threading.Event()
    stop.set()
    cancelled = dict(descriptor)
    cancelled["stop_event"] = stop
    with pytest.raises(RunCancelled, match="cancelled"):
        _apply(service, view.session_id, payload, cancelled, label="Pinch")

    assert tuple(service.working_mesh(view.session_id).submeshes[0].vertices) == baseline
    assert service._sessions[view.session_id].undo_stack == []


def test_out_of_range_payload_is_rejected_before_retiring_clean_legacy_session() -> None:
    service = MeshService()
    view = service.open_edit_session(_mesh(), session_id="resident-invalid", mode="edit")
    session = service._sessions[view.session_id]
    session.native_editor_session_ready = True
    payload, descriptor = _transaction_bytes(
        service,
        view.session_id,
        gesture_id=601,
        tool=4,
        geometry=((0, ((99, (0.0, 0.0, 1.0)),)),),
    )

    with pytest.raises(ValueError, match="out of range"):
        _apply(service, view.session_id, payload, descriptor, label="Smooth")

    assert session.native_editor_session_ready is True
    assert session.undo_stack == []
