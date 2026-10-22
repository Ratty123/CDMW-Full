"""Deliberate skin edits survive proven donor-record cleanup, never a bypass."""

import copy
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.modding.mesh_parser import parse_pac
from cdmw.domain.mesh.skin_weight_edits import SKIN_ROW_FINGERPRINTS, skin_row_fingerprints
from cdmw.services.mesh_vertex_parameters import inspection_token
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from cdmw.modding.mesh_pac_topology_builder import _section_payloads
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_exact_cleanup import _command


def _edit_and_merge(session, method="rig", *, cycle_weight_history=False):
    selection = {"vertices_by_submesh": {"0": [0]}, "edges_by_submesh": {},
                 "faces_by_submesh": {}, "source_indices": []}
    if method == "rig":
        _command(session, 1, "rig_select_bone", bone_index=7)
        _command(session, 2, "rig_adjust_weight", selection=selection, delta=0.1)
    else:
        _command(session, 1, "select", selection=selection)
        _command(session, 2, "vertex_edit", token=inspection_token(session),
                 edits={"weights": {"mode": "offset", "bone": 7, "value": 0.1}})
    authored = session.shadow_service.working_mesh(session.shadow_session_id, clone=True).submeshes[0]
    if cycle_weight_history:
        _command(session, 3, "undo")
        assert session.shadow_service.working_mesh(session.shadow_session_id, clone=True).submeshes[0].bone_weights != authored.bone_weights
        _command(session, 4, "redo")
        assert session.shadow_service.working_mesh(session.shadow_session_id, clone=True).submeshes[0].bone_weights == authored.bone_weights
    selection["vertices_by_submesh"]["0"] = [0, 1]
    _command(session, 5 if cycle_weight_history else 3, "mesh_action", action="remove_doubles", selection=selection,
             params={"threshold": 1.01})
    return authored


@pytest.mark.parametrize("output_policy", ["exact_game_asset", "free_edit_rebuild"])
@pytest.mark.parametrize("method", ["rig", "vertex_parameters"])
def test_deliberate_weight_edit_then_merge_can_undo_redo_and_finish(tmp_path: Path, output_policy, method):
    source, service, session = _open_exact_session(tmp_path / "session", resolved_rig=True)
    sid = session.authoritative_session_id
    try:
        authored = _edit_and_merge(session, method, cycle_weight_history=True)
        assert authored.bone_weights[0] != parse_pac(source).submeshes[0].bone_weights[0]
        _command(session, 10, "undo")
        undone = session.shadow_service.working_mesh(session.shadow_session_id, clone=True).submeshes[0]
        assert len(undone.vertices) == 4
        assert undone.bone_weights == authored.bone_weights
        _command(session, 11, "redo")
        if output_policy == "free_edit_rebuild":
            _command(session, 12, "configure_output_policy", policy=output_policy,
                     destination=str(tmp_path / "output"))

        result = session.finish(_request(session, "finish_request", 13))

        evidence = "exact_output_validation" if output_policy == "exact_game_asset" else "free_edit_output_validation"
        assert result[evidence]["status"] == "passed"
        assert result[evidence]["fallback_used"] is False
        accepted = service.working_mesh(sid, clone=True).submeshes[0]
        assert len(accepted.vertices) == 3
        assert accepted.bone_indices[0] == authored.bone_indices[0]
        assert accepted.bone_weights[0] == authored.bone_weights[0]
        assert service._session(sid).original_data == source
        if output_policy == "exact_game_asset":
            rebuilt, report = service.rebuild_result_from_snapshot(service.capture_export_snapshot(sid))
            assert report.validation_status == "passed"
            returned = parse_pac(rebuilt.data).submeshes[0]
            assert returned.bone_indices[0] == (3, 7)
            assert returned.bone_weights[0] == pytest.approx((174 / 255, 81 / 255))
            original = parse_pac(source).submeshes[0]
            for row, parent in enumerate((0, 2, 3)):
                before, after = original.source_vertex_offsets[parent], returned.source_vertex_offsets[row]
                assert source[before + 12:before + 16] == rebuilt.data[after + 12:after + 16]
                assert source[before + 34:before + 40] == rebuilt.data[after + 34:after + 40]
            assert returned.bone_weights[1:] == original.bone_weights[2:]
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(sid, force_without_saving=True)


@pytest.mark.parametrize("output_policy", ["exact_game_asset", "free_edit_rebuild"])
@pytest.mark.parametrize("damage", [
    "unrecorded_weights", "unrecorded_bones", "missing_proof", "wrong_record",
    "out_of_palette", "unnormalized", "missing_operation", "unsupported_topology", "missing_rows",
    "unsupported_topology_without_retained_weight_change",
])
def test_skin_cleanup_does_not_authorize_unrecorded_or_invalid_skin_rows(tmp_path, output_policy, damage):
    source, service, session = _open_exact_session(tmp_path / "session", resolved_rig=True)
    sid = session.authoritative_session_id
    try:
        _edit_and_merge(session)
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        candidate = snapshot.mesh
        operations = copy.deepcopy(list(snapshot.edit_operations))
        skin = next(operation for operation in operations if operation["operation"] == "replace_skin_weights_same_count")
        part = candidate.submeshes[0]
        if damage == "unrecorded_weights":
            part.bone_weights = [(0.6, 0.4), *part.bone_weights[1:]]
        elif damage == "unrecorded_bones":
            part.bone_indices = [(2, 7), *part.bone_indices[1:]]
        elif damage == "missing_proof":
            del skin["metadata"][SKIN_ROW_FINGERPRINTS]
        elif damage == "wrong_record":
            part.source_vertex_offsets = [part.source_vertex_offsets[0] + 40, *part.source_vertex_offsets[1:]]
        elif damage in {"out_of_palette", "unnormalized"}:
            if damage == "out_of_palette":
                part.bone_indices = [(99, 7), *part.bone_indices[1:]]
            else:
                part.bone_weights = [(0.3, 0.3), *part.bone_weights[1:]]
            # A matching fingerprint is proof of intent, never proof that a
            # palette slot or weight value is valid.
            skin["metadata"][SKIN_ROW_FINGERPRINTS].update(skin_row_fingerprints(part, [0]))
        elif damage == "missing_operation":
            operations.remove(skin)
        elif damage == "missing_rows":
            part.bone_indices = []
            part.bone_weights = []
        else:
            next(operation for operation in operations if operation["operation"] == "remove_doubles_topology")["operation"] = "subdivide_midpoint_topology"
            if damage == "unsupported_topology_without_retained_weight_change":
                part.bone_weights = [parse_pac(source).submeshes[0].bone_weights[0], *part.bone_weights[1:]]
        candidate._cdmw_edit_operations = tuple(operations)

        prepared = service.prepare_working_mesh_replacement(
            sid, candidate, validation_output_policy=output_policy,
            validation_output_destination=str(tmp_path / "output"), validation_output_destination_ready=True,
        )

        assert not prepared.validation_report.ok
        if damage in {"out_of_palette", "unnormalized"}:
            assert "invalid_safe_skin_weight_row" in {issue.code for issue in prepared.validation_report.blockers}
        assert service.session_view(sid).revision == 0
        assert service._session(sid).original_data == source
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(sid, force_without_saving=True)


@pytest.fixture
def cloth_skin_session(tmp_path):
    data = bytearray(_pac_fixture(skinned=True, lower_matches_lod0=True))
    for offset in parse_pac(data).submeshes[0].source_vertex_offsets:
        data[offset + 39] = 17
        struct.pack_into("<I", data, offset + 24,
                         (struct.unpack_from("<I", data, offset + 24)[0] & 0xC00003FF) | (1234 << 10))
    payloads, sections, count, _metadata, _section = _section_payloads(bytes(data))
    for section in sections:
        if 0 < section["index"] < count:
            data[section["offset"]:section["offset"] + section["size"]] = payloads[count]
    with patch("tests.test_mesh_rust_authoring_exact_output._pac_fixture", return_value=bytes(data)):
        source, service, session = _open_exact_session(tmp_path / "session", resolved_rig=True)
    try:
        yield source, service, session
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def test_weighted_cleanup_preserves_cloth_guides_and_synchronizes_identical_lods(cloth_skin_session):
    source, service, session = cloth_skin_session
    _edit_and_merge(session)
    result = session.finish(_request(session, "finish_request", 4))
    assert result["exact_output_validation"]["status"] == "passed"
    rebuilt, report = service.rebuild_result_from_snapshot(service.capture_export_snapshot(session.authoritative_session_id))
    original, returned = parse_pac(source).submeshes[0], parse_pac(rebuilt.data).submeshes[0]
    assert returned.bone_weights[0] == pytest.approx((174 / 255, 81 / 255))
    for row, parent in enumerate((0, 2, 3)):
        before, after = original.source_vertex_offsets[parent], returned.source_vertex_offsets[row]
        assert (struct.unpack_from("<I", source, before + 24)[0] & 0xFFFFFC00
                == struct.unpack_from("<I", rebuilt.data, after + 24)[0] & 0xFFFFFC00)
        assert source[before + 32:before + 40] == rebuilt.data[after + 32:after + 40]
    assert report.topology_rebuild["synchronized_cleanup_lod_indices"] == (1, 2, 3)
    assert report.topology_rebuild["lost_influence_mass"] == 0.0
    assert report.topology_rebuild["fallback_used"] is False
    assert service._session(session.authoritative_session_id).original_data == source


@pytest.mark.parametrize("output_policy", ["exact_game_asset", "free_edit_rebuild"])
def test_weighted_cleanup_refuses_a_fifth_cloth_influence_even_with_matching_proof(cloth_skin_session, output_policy):
    _source, service, session = cloth_skin_session
    _edit_and_merge(session)
    snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
    candidate = snapshot.mesh
    part = candidate.submeshes[0]
    part.bone_indices = [(0, 1, 2, 3, 7), *part.bone_indices[1:]]
    part.bone_weights = [(0.2,) * 5, *part.bone_weights[1:]]
    operations = copy.deepcopy(list(snapshot.edit_operations))
    skin = next(operation for operation in operations if operation["operation"] == "replace_skin_weights_same_count")
    skin["metadata"][SKIN_ROW_FINGERPRINTS].update(skin_row_fingerprints(part, [0]))
    candidate._cdmw_edit_operations = tuple(operations)

    prepared = service.prepare_working_mesh_replacement(
        session.authoritative_session_id, candidate, validation_output_policy=output_policy,
    )

    assert not prepared.validation_report.ok
    assert service.session_view(session.authoritative_session_id).revision == 0


@pytest.mark.parametrize("output_policy", ["exact_game_asset", "free_edit_rebuild"])
def test_merge_retains_a_deliberately_added_palette_influence(tmp_path, output_policy):
    source, service, session = _open_exact_session(tmp_path / "session", resolved_rig=True)
    sid = session.authoritative_session_id
    selection = {"vertices_by_submesh": {"0": [0]}, "edges_by_submesh": {},
                 "faces_by_submesh": {}, "source_indices": []}
    try:
        _command(session, 1, "rig_select_bone", bone_index=2)
        _command(session, 2, "rig_adjust_weight", selection=selection, delta=0.1)
        selection["vertices_by_submesh"]["0"] = [0, 1]
        _command(session, 3, "mesh_action", action="remove_doubles", selection=selection,
                 params={"threshold": 1.01})
        if output_policy == "free_edit_rebuild":
            _command(session, 4, "configure_output_policy", policy=output_policy,
                     destination=str(tmp_path / "output"))
        result = session.finish(_request(session, "finish_request", 5))
        evidence = "exact_output_validation" if output_policy == "exact_game_asset" else "free_edit_output_validation"
        assert result[evidence]["status"] == "passed"
        assert set(service.working_mesh(sid, clone=True).submeshes[0].bone_indices[0]) == {2, 3, 7}
        if output_policy == "exact_game_asset":
            rebuilt, report = service.rebuild_result_from_snapshot(service.capture_export_snapshot(sid))
            original, returned = parse_pac(source).submeshes[0], parse_pac(rebuilt.data).submeshes[0]
            assert set(returned.bone_indices[0]) == {2, 3, 7}
            assert all(weight > 0 for weight in returned.bone_weights[0])
            assert sum(returned.bone_weights[0]) == pytest.approx(1.0)
            before, after = original.source_vertex_offsets[0], returned.source_vertex_offsets[0]
            for field in (20, 24):
                assert (struct.unpack_from("<I", source, before + field)[0] & 0xC0000000
                        == struct.unpack_from("<I", rebuilt.data, after + field)[0] & 0xC0000000)
            for start, stop in ((6, 8), (12, 16), (34, 40)):
                assert source[before + start:before + stop] == rebuilt.data[after + start:after + stop]
            assert report.topology_rebuild["lost_influence_mass"] == 0.0
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(sid, force_without_saving=True)
