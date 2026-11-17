"""Mesh Editor's texture status counts both routes its view draws textures by.

The helper draws DDS payloads (``textures``) and Preview Core material layers
(``preview_core_material_graph``). A set's pieces and Browse's native materials
come only as layers, so a status built from DDS payloads alone said "untextured
neutral surface" over a textured view (2026-11-17, an item set of
cd_m0001_00_de_phm_ub_24004.pac, lb_24004.pac and the belt). Real authoring
sessions over owned PACs; only the helper process is absent.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from cdmw.services import mesh_rust_preview_package as preview_package
from cdmw.services.mesh_dotnet_reference_composite import decode_dotnet_native_preview_package
from tests.test_mesh_preview_material_source import _native


def _layers_for(parts):
    """A Preview Core graph whose materials carry a copied diffuse for ``parts``."""

    def graph(_package_dir, _scene, _textures, _presentations, _quality, _identity, _cancelled):
        return {"materials": [
            {"lod_index": 0, "material_index": index, "material_slot_index": index, "material_name": "m",
             "layers": [{"layer_role": "base", "diffuse": {"file": {"path": f"layer-{index}.dds"}},
                         "normal": None}]}
            for index in parts]}
    return graph


def _item_set_session(tmp_path, monkeypatch, layered_parts):
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from cdmw.workers.mesh_editor_aux_workers import MeshArchiveMaterialContextWorker
    from tests.test_mesh_item_set_references import _sources

    monkeypatch.setattr(MeshArchiveMaterialContextWorker, "run", lambda worker:
        worker.context_resolved.emit(worker.request_id, SimpleNamespace(
            preview_model=None, material_package_path="", material_package_lease=None)))
    monkeypatch.setattr(preview_package, "_composite_preview_core_material_graph", _layers_for(layered_parts))
    _source, service, controller, contexts = _sources(tmp_path)
    session = RustMeshAuthoringSession.create(controller, tmp_path / "authoring", process_generation=1,
                                              item_set_contexts=contexts, edit_item_set=True)
    return service, controller, session


def test_an_item_set_drawn_by_material_layers_is_not_called_untextured(tmp_path, monkeypatch) -> None:
    service, controller, session = _item_set_session(tmp_path, monkeypatch, (0, 1))
    try:
        manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
        assert manifest["textures"] == []  # no DDS payload: the layers are the only route
        assert session.texture_unavailable_reason == ""
        assert manifest["texture_status"]["available"] is True
        assert manifest["texture_status"]["reason"] == ""
        assert session.texture_coverage == {
            "part_count": 2, "textured_part_count": 2, "dds_part_count": 0,
            "material_graph_part_count": 2, "untextured_parts": []}
    finally:
        session.cancel()
        service.close_edit_session(controller.active_session_id, force_without_saving=True)


def test_an_item_set_names_its_parts_that_really_are_untextured(tmp_path, monkeypatch) -> None:
    service, controller, session = _item_set_session(tmp_path, monkeypatch, (0,))
    try:
        parts = session.shadow_service.working_mesh(session.shadow_session_id).submeshes
        assert session.texture_unavailable_reason == ""
        assert session.texture_coverage["textured_part_count"] == 1
        assert session.texture_coverage["untextured_parts"] == [{"index": 1, "name": parts[1].name}]
        # What mesh_state reads: the materials the editor draws now.
        assert session.live_texture_coverage(parts)["untextured_parts"] == [{"index": 1, "name": parts[1].name}]
    finally:
        session.cancel()
        service.close_edit_session(controller.active_session_id, force_without_saving=True)


def test_an_item_set_with_no_textures_by_either_route_keeps_its_reason(tmp_path, monkeypatch) -> None:
    service, controller, session = _item_set_session(tmp_path, monkeypatch, ())
    try:
        assert "readable DDS" in session.texture_unavailable_reason
        assert session.texture_coverage["textured_part_count"] == 0
    finally:
        session.cancel()
        service.close_edit_session(controller.active_session_id, force_without_saving=True)


def test_browse_native_materials_count_as_textured_in_a_single_file(tmp_path) -> None:
    """The real Preview Core copier: the layer is the part's only texture."""

    from tests.test_mesh_rust_authoring import RustMeshAuthoringTests

    package = _native(tmp_path)
    path = package / "manifest.json"
    native = json.loads(path.read_text())
    native["source_path"] = "owned-rust-authoring.pac"
    native["batches"][0]["editor_identity"]["source_submesh_index"] = 0
    path.write_text(json.dumps(native))
    model = decode_dotnet_native_preview_package(package)
    service, authoring = RustMeshAuthoringTests()._create(tmp_path / "session", material_name="helmet",
        preview_material_model=model, material_package_path=package)
    try:
        manifest = json.loads(authoring.manifest_path.read_text())
        assert manifest["textures"] == []
        assert manifest["preview_core_material_graph"]["materials"][0]["layers"][0]["diffuse"]
        assert manifest["texture_status"]["available"] is True
        assert authoring.texture_unavailable_reason == ""
        assert authoring.texture_coverage["material_graph_part_count"] == 1
    finally:
        authoring.cancel()
        service.close_edit_session("authoritative-rust-test", force_without_saving=True)


@pytest.mark.parametrize("textured", [2, 0])
def test_ready_status_names_only_the_untextured_parts(tmp_path, textured) -> None:
    from tests.test_mesh_rust_editor_selection import MESH_EDITOR_BACKEND_RUST, _dispose, _tab

    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    tab.standalone_rust_hello_received = True
    untextured = [{"index": 13, "name": "belt_buckle"}, {"index": 14, "name": "belt_strap"}]
    tab.standalone_rust_authoring_session = SimpleNamespace(
        closed=True, session_id="set", material_synthesis_budget_parts=(0, 0),
        texture_coverage={"part_count": 4, "textured_part_count": textured,
                          "untextured_parts": untextured if textured else untextured * 2})
    tab.standalone_rust_texture_unavailable_reason = "" if textured else "No readable DDS preview textures."
    try:
        tab._handle_rust_ready({})
        text = tab.standalone_status_label.text()
        if textured:
            assert text.startswith("Mesh Editor is ready. 2 of 4 parts have no readable textures")
            assert text.endswith("untextured neutral surface: belt_buckle, belt_strap")
        else:
            assert text == "Mesh Editor will use an untextured neutral surface: No readable DDS preview textures."
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)
