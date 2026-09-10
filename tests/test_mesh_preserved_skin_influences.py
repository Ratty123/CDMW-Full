from dataclasses import replace
import struct

from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_pac_topology_serializer import _pac_fixture


def _eight_influence_pac():
    data = bytearray(_pac_fixture(skinned=True))
    offset = parse_pac(data).submeshes[0].source_vertex_offsets[0]
    struct.pack_into("<ee", data, offset + 12, 6., 7.)
    struct.pack_into("<II", data, offset + 20, 0 | (1 << 10) | (2 << 20), 3 | (4 << 10) | (5 << 20))
    data[offset + 28:offset + 36] = bytes([32] * 8)
    data[offset + 39] = 0  # Extra influence pair is present.
    return bytes(data)


def test_exact_geometry_export_preserves_all_eight_original_influences():
    source = _eight_influence_pac()
    service = MeshService()
    mesh = service.load_mesh_bytes(source, "eight-influence-armor.pac", run_roundtrip=True)
    assert mesh.submeshes[0].bone_indices[0] == tuple(range(8))
    sid = service.open_edit_session(mesh, load_layer_project=False).session_id
    try:
        snapshot = replace(service.capture_export_snapshot(sid), skeleton_bone_count=8)
        rebuilt, report = service.rebuild_result_from_snapshot(snapshot)
        assert report.validation_status == "passed" and rebuilt.data == source
        snapshot.mesh.submeshes[0].vertices[0] = (.1, .0, .0)
        rebuilt, report = service.rebuild_result_from_snapshot(snapshot)
        result = parse_pac(rebuilt.data)
        assert report.validation_status == "passed"
        assert abs(result.submeshes[0].vertices[0][0] - .1) < 2e-5
        assert result.submeshes[0].bone_indices == mesh.submeshes[0].bone_indices
        assert result.submeshes[0].bone_weights == mesh.submeshes[0].bone_weights
    finally:
        service.close_edit_session(sid, force_without_saving=True)


def test_changed_extra_influence_rows_are_still_rejected():
    service = MeshService()
    mesh = service.load_mesh_bytes(_eight_influence_pac(), "eight-influence-armor.pac", run_roundtrip=True)
    sid = service.open_edit_session(mesh, load_layer_project=False).session_id
    try:
        snapshot = replace(service.capture_export_snapshot(sid), skeleton_bone_count=8)
        snapshot.mesh.submeshes[0].bone_weights[0] = (.2, .1, .1, .1, .1, .1, .1, .2)
        report = service.validate_export_snapshot(snapshot)
        assert not report.ok
        assert {issue.code for issue in report.blockers} >= {"too_many_bone_influences", "skinning_data_changed"}
    finally:
        service.close_edit_session(sid, force_without_saving=True)
