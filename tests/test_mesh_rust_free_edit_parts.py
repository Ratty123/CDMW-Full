"""Whole-part Free Edit keeps native history and reports source-only physics."""

import copy
import hashlib

import pytest

from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.models import ArchiveEntry, PbdProfileBinding, PbdProfileContext, PbdProfileDocument
from cdmw.services.mesh_rust_authoring import RustMeshProtocolError
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
from tests.test_mesh_rust_replacement import command
from tests.test_static_mesh_replacer_preview import _minimal_two_part_pac_original


@pytest.fixture
def free_edit_parts(tmp_path, monkeypatch):
    raw = bytearray(_minimal_two_part_pac_original()[0])
    for level in pac_cloth_lods(raw):
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                raw[offset + 28] = 255
                raw[offset + 38] = 255
                raw[offset + 39] = 63
        # Only target1 has guide bindings and jiggle contribution.
        for offset in level.submeshes[1].source_vertex_offsets:
            raw[offset + 32] = 255
            raw[offset + 38] = 0
            raw[offset + 39] = 0
    source = bytes(raw)
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    _, service, host = _open_exact_session(tmp_path / "session")
    command(host, "configure_output_policy", {
        "policy": "free_edit_rebuild", "destination": str(tmp_path / "output"),
    })
    try:
        yield source, service, host
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def delete_part(host, index=0):
    return command(host, "topology", {
        "action": "delete", "selection": {"source_indices": [index],
            "vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {}},
        "params": {"delete_parts": True}, "label": "Delete part",
    })


def test_whole_part_delete_needs_no_disposable_clone_and_keeps_native_history(free_edit_parts, monkeypatch):
    source, service, host = free_edit_parts
    shadow = host.shadow_service
    original = copy.deepcopy(shadow.working_mesh(host.shadow_session_id, clone=False))

    def reject_clone(*args, **kwargs):
        raise RuntimeError("native mesh clone failed and Python fallback was blocked")

    monkeypatch.setattr("cdmw.services.mesh_service._clone_mesh_for_service_native_snapshot", reject_clone)
    monkeypatch.setattr("cdmw.services.mesh_service.clone_mesh_for_editing", reject_clone)
    response = delete_part(host)
    assert response["state"]["undo_count"] == 1
    assert shadow._session(host.shadow_session_id).native_history_undo_count == 1
    assert [part.name for part in shadow.working_mesh(host.shadow_session_id, clone=False).submeshes] == ["target1"]
    command(host, "undo")
    restored = shadow.working_mesh(host.shadow_session_id, clone=False)
    for actual, expected in zip(restored.submeshes, original.submeshes, strict=True):
        for field in ("vertices", "faces", "uvs", "bone_indices", "bone_weights", "shader_masks", "source_vertex_offsets"):
            assert getattr(actual, field) == getattr(expected, field), field
    command(host, "redo")
    assert [part.name for part in shadow.working_mesh(host.shadow_session_id, clone=False).submeshes] == ["target1"]
    assert service.session_view(host.authoritative_session_id).revision == 0
    assert len(service.working_mesh(host.authoritative_session_id, clone=False).submeshes) == 2
    assert shadow._session(host.shadow_session_id).original_data == source


def test_whole_part_capacity_rejection_keeps_geometry_revision_and_redo(free_edit_parts, monkeypatch):
    _, _, host = free_edit_parts
    delete_part(host)
    command(host, "undo")
    before = host.shadow_service.session_view(host.shadow_session_id)

    from cdmw.services import mesh_rust_authoring
    _, current_bytes = mesh_rust_authoring._validate_owned_session_tree(host.root, host.root_identity)
    # Existing files fit; admission of the next mesh document must fail.
    monkeypatch.setattr(mesh_rust_authoring, "_SESSION_MAX_TOTAL_BYTES", current_bytes + 1)
    with pytest.raises(RustMeshProtocolError, match="aggregate limit"):
        delete_part(host)
    after = host.shadow_service.session_view(host.shadow_session_id)
    assert (after.revision, after.undo_count, after.redo_count) == (before.revision, before.undo_count, before.redo_count)
    assert [part.name for part in host.shadow_service.working_mesh(host.shadow_session_id, clone=False).submeshes] == ["target0", "target1"]


def test_free_edit_inspects_source_physics_without_enabling_physics_output(free_edit_parts):
    source, _, host = free_edit_parts
    state = host.state_payload()
    assert [part["kind"] for part in state["physics"]["parts"]] == ["none", "guide"]
    for part in state["physics"]["parts"]:
        assert part["source_only"] is True
        assert part["output_supported"] is False
        assert "OBJ" in part["output_reason"]
        assert part["geometry_eligible"] is True
        assert part["current_guide_count"] is None
        assert part["current_jiggle_count"] is None
    assert not state["cloth"]["available"]
    assert not state["jiggle"]["available"]
    delete_part(host)
    retained = host.state_payload()["physics"]["parts"]
    assert len(retained) == 1 and retained[0]["name"] == "target1"
    assert retained[0]["kind"] == "guide"
    assert retained[0]["guide_counts"] == [3, 3, 3, 3]
    assert retained[0]["jiggle_counts"] == [3, 3, 3, 3]
    command(host, "topology", {"action": "delete", "selection": {
        "source_indices": [], "vertices_by_submesh": {"0": [0]},
        "edges_by_submesh": {}, "faces_by_submesh": {}}, "params": {}})
    changed = host.state_payload()["physics"]["parts"][0]
    assert changed["kind"] == "guide" and changed["geometry_eligible"] is False
    assert host.shadow_service._session(host.shadow_session_id).original_data == source


def test_free_edit_keeps_profile_assignments_on_original_source_after_part_delete(free_edit_parts):
    _, _, host = free_edit_parts
    entry = ArchiveEntry("owned-rust-exact.pac", host.root / "source.pamt", host.root / "source.paz",
                         0, 0, 0, 0, 0)
    data = b"<Profile><SimulationMode>cloth</SimulationMode></Profile>"
    path = "character/descriptors/pbd/material/lower_fabric.xml"
    document = PbdProfileDocument(path, entry.identity, data, hashlib.sha256(data).hexdigest())
    host.physics_profile_context = PbdProfileContext(entry.identity, profiles=(document,), bindings=(
        PbdProfileBinding("Lower Fabric", "target1", "target1", "0", path),
    ))
    before = host.state_payload()["physics_profiles"]["parts"]
    assert before[0]["bindings"] == []
    assert before[1]["bindings"][0]["profile"] == "Lower Fabric"
    delete_part(host)
    after = host.state_payload()
    assert after["physics_profiles"]["parts"][0]["source_name"] == "target1"
    assert after["physics"]["parts"][0]["profiles"][0]["profile"] == "Lower Fabric"
    assert document.data == data


def test_free_edit_never_guesses_source_physics_from_current_part_row_or_name(free_edit_parts):
    _, _, host = free_edit_parts
    mesh = host.shadow_service.working_mesh(host.shadow_session_id, clone=False)
    mesh.submeshes[1].source_descriptor_offset = -1
    row = host.state_payload()["physics"]["parts"][1]
    assert row["kind"] == "unknown"
    assert row["geometry_eligible"] is False
    assert row["guide_counts"] == []
    assert "cannot be matched" in row["reason"]
