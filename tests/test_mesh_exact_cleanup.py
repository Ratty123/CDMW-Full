"""Exact PAC cleanup preserves original records through the real native writer."""

import struct
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.authoring_capability import action_authoring_capability
from cdmw.domain.mesh.topology import validate_topology_operation_history
from cdmw.modding.mesh_pac_topology_builder import protected_byte_mask, _section_payloads, topology_rebuild_blockers
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_rust_authoring_exact_output import _request


def _duplicate_pac(*, matching_lods=False):
    data = bytearray(_pac_fixture(skinned=True, lower_matches_lod0=matching_lods))
    part = parse_pac(data).submeshes[0]
    # First triangle collapses; the surviving triangle must keep face origin 1.
    first, duplicate = part.source_vertex_offsets[:2]
    data[duplicate:duplicate + 6] = data[first:first + 6]
    if matching_lods:
        payloads, sections, lod_count, _metadata, _section = _section_payloads(bytes(data))
        for section in sections:
            if 0 < section["index"] < lod_count:
                data[section["offset"]:section["offset"] + section["size"]] = payloads[lod_count]
    return bytes(data)


@pytest.fixture
def exact_cleanup_session(tmp_path, request):
    source = _duplicate_pac(matching_lods=bool(getattr(request, "param", False)))
    service = MeshService()
    mesh = service.load_mesh_bytes(source, "owned-exact-cleanup.pac", run_roundtrip=True)
    mesh._cdmw_mesh_asset_inferred_bone_count = 8
    view = service.open_edit_session(mesh, session_id="exact-cleanup", mode="edit", load_layer_project=False)
    session = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=service, active_session_id=view.session_id),
        tmp_path / "session", process_generation=23)
    try:
        yield source, service, session
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(view.session_id, force_without_saving=True)


def _command(session, request_id, command, **arguments):
    request = _request(session, "command_request", request_id)
    request.update(command=command, arguments=arguments)
    return session.run_command(request)


def _cleanup(session, request_id=1):
    return _command(session, request_id, "mesh_action", action="remove_doubles",
                    selection={"vertices_by_submesh": {"0": [0, 1]},
                               "edges_by_submesh": {}, "faces_by_submesh": {}, "source_indices": []},
                    params={"threshold": 0.00001})


@pytest.mark.parametrize("mesh_format,lod,authorable", [
    ("pac", 0, True), ("pam", 0, False), ("pamlod", 0, False), ("pac", 1, False),
])
def test_exact_cleanup_is_only_advertised_for_pac_lod0(mesh_format, lod, authorable):
    capability = action_authoring_capability("remove_doubles", mesh_format=mesh_format, lod_index=lod)
    assert capability.authorable is authorable


@pytest.mark.parametrize("exact_cleanup_session", [False, True], indirect=True)
def test_exact_cleanup_keeps_native_history_original_faces_and_protected_records(exact_cleanup_session, tmp_path):
    source, service, session = exact_cleanup_session
    _cleanup(session)
    mesh = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
    part = mesh.submeshes[0]
    provenance = part.topology_provenance
    assert provenance is not None
    assert provenance.face_origins == (1,)
    assert tuple(origin.direct_parent for origin in provenance.vertex_origins) == (0, 2, 3)
    operations = session.shadow_service._session(session.shadow_session_id).edit_operations
    assert operations[-1].operation == "remove_doubles_topology"
    assert validate_topology_operation_history(operations) == ()
    _command(session, 2, "undo")
    assert len(session.shadow_service.working_mesh(session.shadow_session_id, clone=False).submeshes[0].vertices) == 4
    _command(session, 3, "redo")
    assert session.shadow_service.working_mesh(session.shadow_session_id, clone=True).submeshes[0].topology_provenance == provenance

    result = session.finish(_request(session, "finish_request", 4))
    assert result["exact_output_validation"]["status"] == "passed"
    snapshot = service.capture_export_snapshot(session.authoritative_session_id)
    rebuilt, report = service.rebuild_result_from_snapshot(snapshot)
    assert report.validation_status == "passed"
    assert rebuilt.report.topology_rebuild["serializer"] == "pac_lod0_topology_exact_v1"
    assert rebuilt.report.topology_rebuild["fallback_used"] is False
    payloads_before, _sections, count, _metadata, _section = _section_payloads(source)
    payloads_after, _sections, _count, _metadata, _section = _section_payloads(rebuilt.data)
    matching_lods = payloads_before[1] == payloads_before[count]
    assert rebuilt.report.topology_rebuild["synchronized_cleanup_lod_indices"] == ((1, 2, 3) if matching_lods else ())
    assert rebuilt.report.topology_rebuild["lower_lods_preserved"] is (not matching_lods)
    for index in range(1, count):
        assert payloads_after[index] == (payloads_after[count] if matching_lods else payloads_before[index])
    returned = parse_pac(rebuilt.data)
    original = parse_pac(source)
    assert len(returned.submeshes[0].vertices) == 3
    assert returned.submeshes[0].faces == part.faces
    assert returned.lod_levels[1:] == original.lod_levels[1:]
    mask = bytearray(protected_byte_mask(skinned=True))
    # Parent-blend admission also conservatively compares the normal Z sign.
    # Direct donor vertices may author normals; audit their foreign tangent Y
    # and handedness bits separately using the existing normal codec contract.
    mask[16:20] = bytes(4)
    for row, origin in enumerate(provenance.vertex_origins):
        before = original.submeshes[0].source_vertex_offsets[origin.direct_parent]
        after = returned.submeshes[0].source_vertex_offsets[row]
        assert bytes(value & bit for value, bit in zip(source[before:before + 40], mask)) == bytes(
            value & bit for value, bit in zip(rebuilt.data[after:after + 40], mask))
        assert source[before + 12:before + 16] == rebuilt.data[after + 12:after + 16]
        assert source[before + 20:before + 40] == rebuilt.data[after + 20:after + 40]
        normal_changed = struct.unpack_from("<I", source, before + 16)[0] ^ struct.unpack_from("<I", rebuilt.data, after + 16)[0]
        assert normal_changed & 0x800003FF == 0
        assert returned.submeshes[0].normals[row] == pytest.approx(part.normals[row], abs=0.003)
    assert service._session(session.authoritative_session_id).original_data == source

    reopened = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=service, active_session_id=session.authoritative_session_id),
        tmp_path / "reopened", process_generation=24)
    try:
        assert reopened.finish(_request(reopened, "finish_request", 5))["exact_output_validation"]["status"] == "passed"
    finally:
        if not reopened.closed:
            reopened.cancel()


@pytest.mark.parametrize("damage,blocker", [
    ("weights", "skinning_data_changed"), ("missing_provenance", "submesh_vertex_count_changed"),
    ("offset", "source_vertex_offsets_changed"),
])
def test_exact_cleanup_does_not_authorize_skin_or_source_tampering(exact_cleanup_session, damage, blocker):
    _source, service, session = exact_cleanup_session
    _cleanup(session)
    mesh = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
    part = mesh.submeshes[0]
    if damage == "weights":
        part.bone_weights[0] = (0.25, 0.75)
    elif damage == "missing_provenance":
        part.topology_provenance = None
    else:
        part.source_vertex_offsets[0] += 40
    prepared = service.prepare_working_mesh_replacement(session.authoritative_session_id, mesh)
    assert blocker in {issue.code for issue in prepared.validation_report.blockers}
    assert service.session_view(session.authoritative_session_id).revision == 0
    assert len(service.working_mesh(session.authoritative_session_id, clone=False).submeshes[0].vertices) == 4


@pytest.mark.parametrize("damage", ["payload", "split", "missing_operation"])
@pytest.mark.parametrize("exact_cleanup_session", [True], indirect=True)
def test_cleanup_refuses_unproven_lower_lod_synchronization(exact_cleanup_session, damage):
    source, _service, session = exact_cleanup_session
    _cleanup(session)
    mesh = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
    mesh._cdmw_edit_operations = session.shadow_service.capture_export_snapshot(session.shadow_session_id).edit_operations
    assert topology_rebuild_blockers(parse_pac(source), mesh, source) == ()
    if damage == "missing_operation":
        mesh._cdmw_edit_operations = ()
    else:
        data = bytearray(source)
        _payloads, sections, count, _metadata, section_0 = _section_payloads(source)
        lower = next(section for section in sections if section["index"] == 1)
        if damage == "payload":
            data[lower["offset"] + 6] ^= 1  # Same counts/positions do not prove the records match.
        else:
            split_pointer = section_0["offset"] + 5 + count * 4 + (count - 1) * 4
            struct.pack_into("<I", data, split_pointer, struct.unpack_from("<I", data, split_pointer)[0] + 40)
        source = bytes(data)
    original = parse_pac(source)
    assert "TOPOLOGY_CONTRACT_UNSUPPORTED" in topology_rebuild_blockers(original, mesh, source)
