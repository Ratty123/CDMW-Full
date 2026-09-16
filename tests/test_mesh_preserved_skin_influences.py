from dataclasses import replace
import struct

import pytest

from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_pac_topology_serializer import _pac_fixture


def _eight_influence_pac():
    data = bytearray(_pac_fixture(skinned=True))
    offset = parse_pac(data).submeshes[0].source_vertex_offsets[0]
    struct.pack_into("<ee", data, offset + 12, 6., 7.)
    struct.pack_into("<II", data, offset + 20, 0 | (1 << 10) | (2 << 20), 3 | (4 << 10) | (5 << 20))
    data[offset + 28:offset + 36] = bytes([32] * 8)
    data[offset + 39] = 0  # Four skeletal and four cloth guide influences.
    return bytes(data)


def test_exact_geometry_export_preserves_original_skeletal_and_cloth_lanes():
    source = _eight_influence_pac()
    service = MeshService()
    mesh = service.load_mesh_bytes(source, "eight-influence-armor.pac", run_roundtrip=True)
    assert mesh.submeshes[0].bone_indices[0] == tuple(range(4))
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
        snapshot.mesh.submeshes[0].bone_indices[0] = tuple(range(8))
        snapshot.mesh.submeshes[0].bone_weights[0] = (.2, .1, .1, .1, .1, .1, .1, .2)
        report = service.validate_export_snapshot(snapshot)
        assert not report.ok
        assert {issue.code for issue in report.blockers} >= {"too_many_bone_influences", "skinning_data_changed"}
    finally:
        service.close_edit_session(sid, force_without_saving=True)


@pytest.mark.parametrize("with_extra_lanes", [False, True])
def test_exact_geometry_preserves_source_slots_outside_attached_pab(with_extra_lanes):
    data = bytearray(_eight_influence_pac())
    offset = parse_pac(data).submeshes[0].source_vertex_offsets[0]
    struct.pack_into("<II", data, offset + 20, 0 | (1 << 10) | (2 << 20), 3 | (753 << 10) | (745 << 20))
    if not with_extra_lanes:
        data[offset + 39] = 63
    source = bytes(data)
    service = MeshService()
    mesh = service.load_mesh_bytes(source, "original-slots.pac", run_roundtrip=True)
    sid = service.open_edit_session(mesh, load_layer_project=False).session_id
    try:
        snapshot = replace(service.capture_export_snapshot(sid), skeleton_bone_count=448)
        snapshot.mesh.submeshes[0].vertices[0] = (.1, 0., 0.)
        rebuilt, report = service.rebuild_result_from_snapshot(snapshot)
        assert report.validation_status == "passed"
        returned = parse_pac(rebuilt.data)
        assert returned.submeshes[0].vertices[0][0] == pytest.approx(.1, abs=2e-5)
        assert returned.submeshes[0].bone_indices == mesh.submeshes[0].bone_indices
        assert returned.submeshes[0].bone_weights == mesh.submeshes[0].bone_weights
        for part in mesh.submeshes:
            for vertex_offset in part.source_vertex_offsets:
                assert rebuilt.data[vertex_offset + 12:vertex_offset + 16] == source[vertex_offset + 12:vertex_offset + 16]
                assert rebuilt.data[vertex_offset + 20:vertex_offset + 36] == source[vertex_offset + 20:vertex_offset + 36]
                assert rebuilt.data[vertex_offset + 39] == source[vertex_offset + 39]

        indices = list(snapshot.mesh.submeshes[0].bone_indices[0])
        indices[-1] = 999
        snapshot.mesh.submeshes[0].bone_indices[0] = tuple(indices)
        rejected = service.validate_export_snapshot(snapshot)
        assert {issue.code for issue in rejected.blockers} >= {"invalid_bone_index", "skinning_data_changed"}
    finally:
        service.close_edit_session(sid, force_without_saving=True)
