"""Recovered replacement previews keep the materials captured with their draft."""

from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import threading
from types import SimpleNamespace

from PIL import Image
import pytest

from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.domain.model_preview_materials import PreviewMaterialParameterInput, PreviewMaterialTextureInput
from cdmw.services.mesh_replacement_import import initial_replacement_state
from cdmw.services.mesh_replacement_materials import capture_replacement_dependencies
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.services.mesh_rust_replacement_materials import prepared_replacement_material_mesh
from tests.test_mesh_editor_replacement import editor
from tests.test_mesh_editor_replacement_materials import material_fixture
from tests.test_mesh_editor_replacement_sequences import open_editor
from tests.test_mesh_rust_authoring_exact_output import _request
from tests.test_mesh_rust_replacement import command


def _base_colors(host, state):
    key = state["archive_refit_materials"]["key"]
    result = {}
    for row in host.archive_refit_material_cache[key]["textures"]:
        if row["role"] == "base_color":
            with Image.open(host.root / row["file"]["path"]) as image:
                for index in row["material_indices_by_lod"][0]:
                    result[index] = image.convert("RGBA").getpixel((0, 0))
    return result


@pytest.mark.parametrize("material_choice", ["original", "imported"])
@pytest.mark.parametrize("captured_inputs", [False, True])
def test_offline_draft_retains_original_material_previews(editor, tmp_path, material_choice, captured_inputs):
    service, sid = editor
    original = service.capture_export_snapshot(sid)
    sources = tmp_path / "sources"
    sources.mkdir()
    target, context, model = material_fixture(sources, original)
    textures = [context.entries_by_normalized_path[f"character/texture/original{i}.dds"][0].paz_file
                for i in range(2)]
    Image.new("RGBA", (4, 4), (20, 50, 210, 255)).save(textures[1])
    for mesh in (service._session(sid).base_mesh, service.working_mesh(sid, clone=False)):
        for index, (part, path) in enumerate(zip(mesh.submeshes, textures, strict=True)):
            part.preview_texture_dds_path = str(path)
            if captured_inputs:
                part.preview_material_texture_inputs = (PreviewMaterialTextureInput(
                    slot_kind="base_color", parameter_name="_diffuseTexture", source_dds_path=str(path),
                    preview_texture_path=str(path), source_texture_path=f"character/texture/original{index}.dds",
                    material_name=part.material, part_name=part.name, semantic_type="base_color",
                    confidence="sidecar", visualized=True),)
    key = initial_replacement_state(original).parts[0].part_id
    draft = tmp_path / "draft" / "mesh_layers.json"
    with ExitStack() as stack:
        host = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=service, active_session_id=sid),
                                               tmp_path / "host", process_generation=1)
        stack.callback(lambda: host.cancel() if not host.closed else None)
        command(host, "replacement_choose", {"scope": "selected", "part_ids": [key], "source_path": str(model),
                                               "_archive_entry": target, "_archive_dependencies": context})
        applied = command(host, "replacement_apply", {"targets": [key], "materials": material_choice})
        expected = _base_colors(host, applied["state"])
        assert set(expected) == {0, 1}
        assert expected[0] == pytest.approx((210, 30, 60, 255) if material_choice == "imported" else (20, 190, 90, 255), abs=4)
        assert expected[1] == pytest.approx((20, 50, 210, 255), abs=4)
        bundle = host.shadow_service._replacement_output_for_snapshot(
            host.shadow_service.capture_export_snapshot(host.shadow_session_id))
        shadow = host.shadow_service
        shadow._session(host.shadow_session_id).mesh_layer_project_path = draft
        shadow.retry_mesh_layer_autosave(host.shadow_session_id)
        host.cancel()
        for path in sources.iterdir():
            if path.is_file():
                path.unlink()
        recovered_service, recovered_sid = open_editor(stack, original.original_data, original.mesh.path, draft)
        recovered = RustMeshAuthoringSession.create(
            SimpleNamespace(mesh_service=recovered_service, active_session_id=recovered_sid),
            tmp_path / "recovered", process_generation=2)
        stack.callback(lambda: recovered.cancel() if not recovered.closed else None)
        assert _base_colors(recovered, recovered.state_payload()) == expected
        manifest = json.loads(recovered.manifest_path.read_text())
        active = recovered.archive_refit_material_cache[manifest["state"]["archive_refit_materials"]["key"]]
        assert manifest["textures"] == active["textures"]
        compared = command(recovered, "replacement_compare", {"mode": "original"})
        original_colors = _base_colors(recovered, compared["state"])
        assert original_colors[0] == pytest.approx((20, 190, 90, 255), abs=4)
        assert original_colors[1] == pytest.approx((20, 50, 210, 255), abs=4)
        assert _base_colors(recovered, command(recovered, "replacement_compare", {"mode": "output"})["state"]) == expected
        command(recovered, "replacement_compare", {"mode": "edit"})
        restore = tmp_path / "restore.obj"
        restore.write_text("o restored\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        command(recovered, "replacement_choose", {"scope": "selected", "part_ids": [key], "source_path": str(restore)})
        restored = command(recovered, "replacement_apply", {"targets": [key], "materials": "original"})
        assert _base_colors(recovered, restored["state"]) == original_colors
        assert _base_colors(recovered, command(recovered, "undo")["state"]) == expected
        assert _base_colors(recovered, command(recovered, "redo")["state"]) == original_colors
        command(recovered, "undo")
        recovered.finish(_request(recovered, "finish_request", 61))
        snapshot = recovered_service.capture_export_snapshot(recovered_sid)
        output = recovered_service._replacement_output_for_snapshot(snapshot)
        assert (output.data, output.companion_files) == (bundle.data, bundle.companion_files)
        assert snapshot.original_data == original.original_data


def test_captured_material_rebind_preserves_resolved_owner_and_layer_metadata(editor, tmp_path):
    service, sid = editor
    mesh = service.capture_export_snapshot(sid).mesh
    path = tmp_path / "captured.dds"
    Image.new("RGBA", (4, 4), (10, 20, 30, 255)).save(path)
    file = ReplacementFile("character/texture/owned.dds", path.read_bytes())
    parameters = (PreviewMaterialParameterInput(parameter_name="_tint", color_value=(.1, .2, .3)),)
    original = PreviewMaterialTextureInput(source_texture_path=file.path, source_dds_path="missing/cache.dds",
        preview_texture_path="missing/cache.dds", material_name="different wrapper", owner_slot_index=7,
        binding_authority="native", layer_role="blend", material_parameters=parameters)
    mesh.submeshes[0].preview_material_texture_inputs = (original,)
    with prepared_replacement_material_mesh(mesh, (file,), required=False) as prepared:
        rebound = prepared.submeshes[0].preview_material_texture_inputs[0]
        assert rebound != original
        assert replace(rebound, source_dds_path=original.source_dds_path,
                       preview_texture_path=original.preview_texture_path) == original
        assert Path(rebound.source_dds_path).read_bytes() == file.data
    assert mesh.submeshes[0].preview_material_texture_inputs == (original,)


def test_captured_sidecar_does_not_replace_a_readable_authoritative_texture(editor, tmp_path):
    service, sid = editor
    mesh = service.capture_export_snapshot(sid).mesh
    path = tmp_path / "selected.dds"
    Image.new("RGBA", (4, 4), (10, 20, 30, 255)).save(path)
    mesh.submeshes[0].preview_texture_dds_path = str(path)
    xml = b'<Root><SkinnedMeshMaterialWrapper _subMeshName="target0"><Material><Vector Name="_parameters"><MaterialParameterTexture _name="_diffuseTexture" Index="0"><ResourceReferencePath_ITexture _path="character/texture/wrong.dds"/></MaterialParameterTexture></Vector></Material></SkinnedMeshMaterialWrapper></Root>'
    files = (ReplacementFile("character/model/replacement.pac_xml", xml), ReplacementFile("character/texture/wrong.dds", path.read_bytes()))
    with prepared_replacement_material_mesh(mesh, files, required=False) as prepared:
        assert prepared.submeshes[0].preview_texture_dds_path == str(path)
        assert not getattr(prepared.submeshes[0], "preview_material_texture_inputs", ())


@pytest.mark.parametrize("fault", ["unreadable-sidecar", "missing-texture"])
@pytest.mark.parametrize("required", [False, True])
def test_incomplete_original_materials_allow_geometry_but_imported_materials_stay_strict(editor, tmp_path, fault, required):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    target, context, _ = material_fixture(tmp_path, snapshot)
    files = capture_replacement_dependencies(target, context)
    if fault == "missing-texture":
        files = tuple(file for file in files if not file.path.endswith(".dds"))
    else:
        files = tuple(replace(file, data=b"") if file.path.endswith(".pac_xml") else file for file in files)
    if required:
        with pytest.raises(ValueError, match="not readable text|Missing prepared texture"):
            with prepared_replacement_material_mesh(snapshot.mesh, files, required=True):
                pytest.fail("Incomplete imported materials were accepted")
    else:
        with prepared_replacement_material_mesh(snapshot.mesh, files, required=False) as prepared:
            assert [part.vertices for part in prepared.submeshes] == [part.vertices for part in snapshot.mesh.submeshes]
            assert not any(getattr(part, "preview_material_texture_inputs", ()) for part in prepared.submeshes)


def test_cancelled_material_preparation_removes_temporary_dds_without_changing_mesh(editor, tmp_path, monkeypatch):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    target, context, _ = material_fixture(tmp_path, snapshot)
    files = capture_replacement_dependencies(target, context)
    stop = threading.Event()
    staged = []
    write = Path.write_bytes

    def cancel_after_write(path, data):
        result = write(path, data)
        if path.parent.name.startswith("cdmw-replacement-preview-"):
            staged.append(path)
            stop.set()
        return result

    monkeypatch.setattr(Path, "write_bytes", cancel_after_write)
    with pytest.raises(RuntimeError, match="cancelled"):
        with prepared_replacement_material_mesh(snapshot.mesh, files, required=True, stop_event=stop):
            pytest.fail("Cancelled material preparation completed")
    assert staged and all(not path.parent.exists() for path in staged)
    assert not any(getattr(part, "preview_material_texture_inputs", ()) for part in snapshot.mesh.submeshes)
