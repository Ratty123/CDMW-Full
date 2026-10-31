"""Exact PAM output after a native edit session that leaves topology unchanged."""

import copy

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.domain.mesh.topology import identity_topology_provenance, topology_contract_submesh_indices
from cdmw.modding.mesh_importer import rebuild_mesh_with_report
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_editor_replacement_formats import static_fixture


def test_native_transform_exports_exact_pam_and_keeps_other_parts():
    original = static_fixture("pam")
    mesh = parse_mesh(original, "object/two.pam")
    mesh._cdmw_original_data = original
    service = MeshService()
    view = service.open_edit_session(mesh, mode="edit", load_layer_project=False)
    try:
        service.apply_command(view.session_id, MeshEditCommand(
            "transform", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"scale": (0.5, 0.5, 0.5)}))
        snapshot = service.capture_export_snapshot(view.session_id)
        # Native sessions give every part a contract, here the identity one.
        assert topology_contract_submesh_indices(snapshot.mesh) == (0, 1)
        built, _report = service.rebuild_result_from_snapshot(snapshot, available_textures=("target0.dds", "target1.dds"))
    finally:
        service.close_edit_session(view.session_id, force_without_saving=True)
    assert len(built.data) == len(original) and built.data != original
    parsed = parse_mesh(built.data, mesh.path)
    expected = snapshot.mesh.submeshes[0].vertices
    assert expected != mesh.submeshes[0].vertices
    for actual, wanted in zip(parsed.submeshes[0].vertices, expected, strict=True):
        assert actual == pytest.approx(wanted, abs=1e-4)
    assert parsed.submeshes[1].vertices == mesh.submeshes[1].vertices
    assert parsed.submeshes[1].faces == mesh.submeshes[1].faces


def test_pam_still_refuses_a_contract_that_changes_its_faces():
    original = static_fixture("pam")
    source = parse_mesh(original, "object/two.pam")
    edited = copy.deepcopy(source)
    for part in edited.submeshes:
        part.topology_provenance = identity_topology_provenance(len(part.vertices), len(part.faces))
    edited.submeshes[0].vertices[0] = (0.25, 0.25, 0.25)
    assert rebuild_mesh_with_report(edited, original, original_mesh=source).data != original
    edited.submeshes[0].faces = [tuple(reversed(face)) for face in edited.submeshes[0].faces]
    with pytest.raises(ValueError, match="only rebuildable into PAC"):
        rebuild_mesh_with_report(edited, original, original_mesh=source)
