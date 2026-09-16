from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_replacement_import import initial_replacement_state, prepare_import, compose_import
from cdmw.services.mesh_replacement_import import commit_replacement
from cdmw.services.mesh_replacement_materials import capture_replacement_dependencies, prepare_imported_materials
from tests.test_mesh_editor_replacement import editor


def entry(root, path, data):
    source = root / Path(path).name
    source.write_bytes(data)
    return ArchiveEntry(path, root / "0009/0.pamt", source, 0, len(data), len(data), 0, 0)


def material_fixture(root, snapshot):
    source = root / "color.dds"
    Image.new("RGBA", (4, 4), (210, 30, 60, 255)).save(source)
    original = root / "original.dds"
    Image.new("RGBA", (4, 4), (20, 190, 90, 255)).save(original)
    xml = ('<Root>' + ''.join(
        f'<SkinnedMeshMaterialWrapper _subMeshName="target{i}"><Material><Vector Name="_parameters">'
        f'<MaterialParameterTexture _name="_diffuseTexture" Index="0"><ResourceReferencePath_ITexture _path="character/texture/original{i}.dds"/>'
        '</MaterialParameterTexture></Vector></Material></SkinnedMeshMaterialWrapper>' for i in range(2)) + '</Root>')
    target = entry(root, snapshot.mesh.path, snapshot.original_data)
    entries = [target, entry(root, str(Path(target.path).with_suffix(".pac_xml")), xml.encode()),
               *(entry(root, f"character/texture/original{i}.dds", original.read_bytes()) for i in range(2))]
    context = SimpleNamespace(entries_by_basename={Path(item.path).name.casefold(): [item] for item in entries},
                              entries_by_normalized_path={item.path.casefold(): [item] for item in entries})
    model = root / "import.obj"
    model.write_text("mtllib import.mtl\no replacement\nusemtl imported\nv 12 3 7\nv 16 3 7\nv 12 5 8\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3\n")
    model.with_suffix(".mtl").write_text("newmtl imported\nKd 1 1 1\nmap_Kd color.dds\n")
    return target, context, model


def test_imported_materials_use_retained_converter_and_preserve_unselected_binding(editor, tmp_path):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    assert len(dependencies) == 3
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    files = prepare_imported_materials(pending, (key,), tmp_path)
    assert any(file.path.endswith(".dds") for file in files)
    sidecar = next(file for file in files if file.path.endswith(".pac_xml"))
    text = sidecar.data.decode()
    assert "original1.dds" in text
    mesh, state = compose_import(pending, (key,), material_choice="imported", companion_files=files)
    assert mesh.submeshes[1].material == snapshot.mesh.submeshes[1].material
    assert state.parts[0].material_choice == "imported"


@pytest.mark.parametrize("missing", ["library", "texture"])
def test_missing_material_dependencies_only_block_imported_materials(editor, tmp_path, missing):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    (model.with_suffix(".mtl") if missing == "library" else tmp_path / "color.dds").unlink()
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    with pytest.raises(ValueError, match=f"Missing imported {'material library' if missing == 'library' else 'texture'}"):
        prepare_imported_materials(pending, (key,), tmp_path)
    assert service.session_view(session_id).revision == snapshot.mesh_revision
    mesh, state = compose_import(pending, (key,), material_choice="original")
    assert [part.material for part in mesh.submeshes] == [part.material for part in snapshot.mesh.submeshes]
    assert list(mesh.submeshes[0].vertices) == [(12, 3, 7), (16, 3, 7), (12, 5, 8)]
    assert list(mesh.submeshes[1].vertices) == list(snapshot.mesh.submeshes[1].vertices)
    assert not state.companion_files
    commit_replacement(service, snapshot, mesh, state, label="Keep original materials")
    rebuilt, report = service.rebuild_result_from_snapshot(service.capture_export_snapshot(session_id))
    from cdmw.modding.mesh_parser import parse_mesh
    assert report.validation_status == "passed"
    assert len(parse_mesh(rebuilt.data, state.target_path).submeshes) == 2


@pytest.mark.parametrize("changed", ["library", "texture", "geometry"])
def test_dependency_fingerprints_follow_material_choice(editor, tmp_path, changed):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
    path = {"library": model.with_suffix(".mtl"), "texture": tmp_path / "color.dds", "geometry": model}[changed]
    path.write_bytes(path.read_bytes() + b"\nchanged")
    with pytest.raises(ValueError, match="dependency changed"):
        prepare_imported_materials(pending, (key,), tmp_path)
    if changed == "geometry":
        with pytest.raises(ValueError, match="dependency changed"):
            compose_import(pending, (key,))
    else:
        mesh, state = compose_import(pending, (key,))
        assert mesh.submeshes[0].material == snapshot.mesh.submeshes[0].material
        assert not state.companion_files
    assert service.session_view(session_id).revision == snapshot.mesh_revision


@pytest.mark.parametrize("extension", ["gltf", "glb"])
def test_missing_gltf_texture_is_optional_but_geometry_buffer_is_required(editor, tmp_path, extension):
    from tests.test_scene_import_normalization import _write_gltf
    from tests.test_scene_importer_gltf import _write_glb
    import json

    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    model = _write_gltf(tmp_path, positions=[(12, 3, 7), (16, 3, 7), (12, 5, 8)], indices=[0, 1, 2],
                        uvs=[(0, 0), (1, 0), (0, 1)],
                        material={"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}})
    if extension == "glb":
        document = json.loads(model.read_text())
        model = tmp_path / "external.glb"
        _write_glb(model, document, b"")
    (tmp_path / "texture.png").unlink()
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,))
    mesh, _ = compose_import(pending, (key,))
    assert mesh.submeshes[0].material == snapshot.mesh.submeshes[0].material
    with pytest.raises(ValueError, match="Missing imported dependency: texture.png"):
        prepare_imported_materials(pending, (key,), tmp_path)
    (tmp_path / "mesh.bin").unlink()
    with pytest.raises(ValueError, match="dependency changed"):
        compose_import(pending, (key,))
    with pytest.raises(ValueError, match="Missing imported dependency: mesh.bin"):
        prepare_import(snapshot, model, target_part_ids=(key,))


@pytest.mark.parametrize("extension", ["gltf", "glb"])
@pytest.mark.parametrize("change", ["modify", "delete"])
def test_external_geometry_buffer_changes_reject_pending_replacement(editor, tmp_path, extension, change):
    from tests.test_scene_import_normalization import _write_gltf
    from tests.test_scene_importer_gltf import _write_glb
    import json

    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    model = _write_gltf(tmp_path, positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], indices=[0, 1, 2],
                        uvs=[(0, 0), (1, 0), (0, 1)])
    if extension == "glb":
        document = json.loads(model.read_text())
        model = tmp_path / "external.glb"
        _write_glb(model, document, b"")
    key = initial_replacement_state(snapshot).parts[0].part_id
    pending = prepare_import(snapshot, model, target_part_ids=(key,))
    buffer = tmp_path / "mesh.bin"
    if change == "modify":
        buffer.write_bytes(buffer.read_bytes() + b"changed")
    else:
        buffer.unlink()
    with pytest.raises(ValueError, match="dependency changed"):
        compose_import(pending, (key,))
    assert service.session_view(session_id).revision == snapshot.mesh_revision
    assert service.session_view(session_id).undo_count == 0


def test_repeated_imports_keep_other_materials_and_restore_original(editor, tmp_path):
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    dependencies = capture_replacement_dependencies(target, context)
    keys = [part.part_id for part in initial_replacement_state(snapshot).parts]
    for key in keys:
        snapshot = service.capture_export_snapshot(session_id)
        pending = prepare_import(snapshot, model, target_part_ids=(key,), entry=target, dependencies=dependencies)
        files = prepare_imported_materials(pending, (key,), tmp_path)
        mesh, state = compose_import(pending, (key,), material_choice="imported", companion_files=files)
        commit_replacement(service, snapshot, mesh, state, label="Import")
    assert len({file.path for file in files if file.path.endswith(".dds")}) == 2
    for key in keys:
        snapshot = service.capture_export_snapshot(session_id)
        pending = prepare_import(snapshot, model, target_part_ids=(key,))
        mesh, state = compose_import(pending, (key,))
        commit_replacement(service, snapshot, mesh, state, label="Original materials")
    assert state.companion_files == ()


@pytest.mark.parametrize("part_index", [0, 1])
def test_material_preview_and_package_share_frozen_bundle(editor, tmp_path, part_index):
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from cdmw.services.mesh_rust_replacement_materials import stage_replacement_materials
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
    from tests.test_mesh_rust_replacement import command
    import json
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    target, context, model = material_fixture(tmp_path, snapshot)
    host = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=service, active_session_id=session_id), tmp_path / "host", process_generation=1)
    try:
        chosen = command(host, "replacement_choose", {"scope": "selected", "part_ids": [initial_replacement_state(snapshot).parts[part_index].part_id],
                         "source_path": str(model), "_archive_entry": target, "_archive_dependencies": context})
        key = chosen["state"]["replacement"]["pending"]["targets"][0]["id"]
        applied = command(host, "replacement_apply", {"targets": [key], "materials": "imported"})
        material_key = applied["state"]["archive_refit_materials"]["key"]
        assert material_key != "base"
        textures = host.archive_refit_material_cache[material_key]["textures"]
        assert textures and any(part_index in row["material_indices_by_lod"][0] for row in textures)
        assert command(host, "replacement_compare", {"mode": "original"})["state"]["archive_refit_materials"]["key"] == "base"
        assert command(host, "replacement_compare", {"mode": "output"})["state"]["archive_refit_materials"]["key"] == material_key
        command(host, "replacement_compare", {"mode": "edit"})
        command(host, "undo")
        assert command(host, "redo")["state"]["archive_refit_materials"]["key"] == material_key
        from tests.test_mesh_rust_authoring_exact_output import _request
        host.finish(_request(host, "finish_request", 51))
        snapshot = service.capture_export_snapshot(session_id)
        bundle = service._replacement_output_for_snapshot(snapshot)
        # Output is self-contained after imported source files disappear.
        model.unlink()
        (tmp_path / "color.dds").unlink()
        draft = tmp_path / "draft" / "mesh_layers.json"
        service._session(session_id).mesh_layer_project_path = draft
        service.retry_mesh_layer_autosave(session_id)
        from cdmw.modding.mesh_parser import parse_mesh
        from cdmw.services.mesh_service import MeshService
        seed = parse_mesh(snapshot.original_data, snapshot.mesh.path)
        seed._cdmw_original_data = snapshot.original_data
        seed._cdmw_mesh_layer_project_path = str(draft)
        restored_service = MeshService()
        restored = restored_service.open_edit_session(seed)
        try:
            reopened = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=restored_service, active_session_id=restored.session_id),
                                                       tmp_path / "reopened-host", process_generation=2)
            try:
                saved_key = reopened.state_payload()["archive_refit_materials"]["key"]
                assert saved_key == material_key
                assert reopened.archive_refit_material_cache[saved_key]["textures"]
                manifest = json.loads(reopened.manifest_path.read_text())
                assert manifest["textures"] == reopened.archive_refit_material_cache[saved_key]["textures"]
                assert manifest["material_presentations"] == reopened.archive_refit_material_cache[saved_key]["material_presentations"]
                references = manifest["replacement_material_states"]
                assert {row["path"] for row in references} == {
                    "material-state-base.json", f"material-state-{saved_key}.json"}
                import hashlib
                for row in references:
                    assert hashlib.sha256((reopened.root / row["path"]).read_bytes()).hexdigest().upper() == row["sha256"].upper()
                assert restored_service._replacement_output_for_snapshot(restored_service.capture_export_snapshot(restored.session_id)).data == bundle.data
            finally:
                reopened.cancel()
        finally:
            restored_service.close_edit_session(restored.session_id)
        worker = MeshDirectOutputWorker(1, service, session_id, target, kind="loose_mod", output_path=tmp_path / "mod")
        errors, completed = [], []
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors
        assert completed
        assert (tmp_path / "mod" / target.path).read_bytes() == bundle.data
        for file in bundle.companion_files:
            assert (tmp_path / "mod" / file.path).read_bytes() == file.data
    finally:
        if not host.closed:
            host.cancel()


def test_replacement_build_button_and_companion_export_guard(editor, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSettings
    from cdmw.domain.mesh.ui_state import MeshEditorUiState
    from cdmw.domain.mesh.replacement import ReplacementFile
    from cdmw.ui.mesh_editor.tab import MeshEditorTab
    app = QApplication.instance() or QApplication([])
    service, session_id = editor
    snapshot = service.capture_export_snapshot(session_id)
    state = replace(initial_replacement_state(snapshot), companion_files=(ReplacementFile("object/test.pac_xml", b"<Root/>"),))
    service._session(session_id).replacement_state = state
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "ReplacementOutputControls"))
    tab.standalone_controller = SimpleNamespace(mesh_service=service, active_session_id=session_id)
    tab.standalone_workspace.setEnabled(True)
    monkeypatch.setattr(tab, "_standalone_rebuild_allowed", lambda: True)
    try:
        tab._apply_mesh_editor_output_control_state(MeshEditorUiState(output_policy="replacement_game_asset"),
            has_standalone=True, has_archive_target=True, output_task_active=False)
        assert tab.standalone_build_mod_button.isEnabled()
        assert tab.standalone_run_validation_report_button.isEnabled()
        assert not tab.standalone_export_mesh_file_button.isEnabled()
        assert "companion" in tab.standalone_export_mesh_file_button.toolTip()
        service._session(session_id).replacement_state = replace(state, companion_files=())
        tab._apply_mesh_editor_output_control_state(MeshEditorUiState(output_policy="replacement_game_asset"),
            has_standalone=True, has_archive_target=True, output_task_active=False)
        assert tab.standalone_export_mesh_file_button.isEnabled()
    finally:
        tab.standalone_controller = None
        tab.deleteLater()
        app.processEvents()
