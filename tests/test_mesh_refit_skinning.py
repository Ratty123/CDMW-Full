from __future__ import annotations

import hashlib
import struct

import pytest

from cdmw.domain.mesh.export_validation import validate_mesh_export
from cdmw.modding.mesh_obj_importer import import_obj
from cdmw.modding.mesh_parser import parse_pac
from tests.test_mesh_preserved_skin_influences import _eight_influence_pac
from tests.test_mesh_rust_authoring import _request
from tests.test_mesh_rust_morph_safety import _open_exact_rust_session


@pytest.mark.parametrize("role", ["body", "armor"])
def test_free_refit_keeps_incoming_skinning_through_history_finish_and_obj(tmp_path, role):
    source = bytearray(_eight_influence_pac())
    vertex_offset = parse_pac(source).submeshes[0].source_vertex_offsets[0]
    struct.pack_into("<ee", source, vertex_offset + 12, 64.0, 65.0)
    source = bytes(source)
    incoming = tmp_path / "incoming.pac"
    incoming.write_bytes(source)
    expected = parse_pac(source).submeshes[0]
    authority, editor = _open_exact_rust_session(tmp_path / "session")
    request_id = 0

    def command(name, **arguments):
        nonlocal request_id
        request_id += 1
        event = _request(editor, "command_request", request_id)
        event.update(command=name, arguments=arguments)
        return editor.run_command(event)

    def working():
        return editor.shadow_service.working_mesh(editor.shadow_session_id, clone=True)

    try:
        snapshot = editor.shadow_service.capture_export_snapshot(editor.shadow_session_id)
        assert snapshot.skeleton_bone_count < max(expected.bone_indices[0]) + 1
        original_count = len(snapshot.mesh.submeshes)
        command("configure_output_policy", policy="free_edit_rebuild", destination=str(tmp_path / "output"))
        command("refit_load_mesh", path=str(incoming), role=role)
        assert working().submeshes[-1].bone_indices == expected.bone_indices
        assert working().submeshes[-1].bone_weights == expected.bone_weights
        command("undo")
        assert len(working().submeshes) == original_count
        command("redo")
        assert working().submeshes[-1].bone_indices == expected.bone_indices
        assert working().submeshes[-1].bone_weights == expected.bone_weights

        result = editor.finish(_request(editor, "finish_request", request_id + 1))
        assert result["status"] == "accepted"
        retained = authority.working_mesh(editor.authoritative_session_id, clone=True)
        assert retained.submeshes[-1].bone_indices == expected.bone_indices
        assert retained.submeshes[-1].bone_weights == expected.bone_weights
        exported = authority.export_free_edit_output(editor.authoritative_session_id)
        reparsed = import_obj(str(exported.obj_path))
        assert reparsed.total_vertices == retained.total_vertices
        assert reparsed.total_faces == retained.total_faces
        assert not exported.exact_archive_writeback
        assert hashlib.sha256(incoming.read_bytes()).digest() == hashlib.sha256(source).digest()
    finally:
        editor.cancel()
        authority.close_edit_session("authoritative-rust-test", force_without_saving=True)


@pytest.mark.parametrize("bone_count", [None, 1])
def test_free_geometry_validation_does_not_require_a_shared_skeleton(bone_count):
    mesh = parse_pac(_eight_influence_pac())
    free = validate_mesh_export(mesh, skeleton_bone_count=bone_count, exact_output=False)
    assert free.ok, free.blockers
    exact = validate_mesh_export(mesh, skeleton_bone_count=bone_count)
    assert not exact.ok
    assert "too_many_bone_influences" in {issue.code for issue in exact.blockers}


@pytest.mark.parametrize("indices,weights,code", [
    ((-1,), (1.0,), "invalid_bone_index"),
    ((0,), (float("nan"),), "invalid_bone_weight"),
    ((0, 1), (1.0,), "bone_weight_row_mismatch"),
    (tuple(range(9)), (1.0 / 9,) * 9, "too_many_bone_influences"),
])
def test_free_refit_still_rejects_malformed_or_unsupported_skin_rows(indices, weights, code):
    mesh = parse_pac(_eight_influence_pac())
    mesh.submeshes[0].bone_indices[0] = indices
    mesh.submeshes[0].bone_weights[0] = weights
    report = validate_mesh_export(mesh, skeleton_bone_count=1, exact_output=False)
    assert code in {issue.code for issue in report.blockers}
