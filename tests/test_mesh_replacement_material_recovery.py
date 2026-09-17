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
from cdmw.services.mesh_dotnet_material_bindings import (
    apply_dotnet_native_material_batch_binding,
    copy_dotnet_preview_material_bindings,
)
from cdmw.services.mesh_replacement_import import initial_replacement_state
from cdmw.services.mesh_replacement_materials import capture_replacement_dependencies
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.services.mesh_rust_replacement_materials import prepared_replacement_material_mesh
from tests.test_mesh_editor_replacement import editor
from tests.test_mesh_editor_replacement_materials import material_fixture
from tests.test_mesh_editor_replacement_sequences import open_editor
from tests.test_mesh_rust_authoring_exact_output import _request
from tests.test_mesh_rust_replacement import command


def _texture_colors(host, state, role="base_color", *, pixel=(0, 0)):
    key = state["archive_refit_materials"]["key"]
    result = {}
    for row in host.archive_refit_material_cache[key]["textures"]:
        if row["role"] == role:
            with Image.open(host.root / row["file"]["path"]) as image:
                for index in row["material_indices_by_lod"][0]:
                    assert index not in result, "A material role was published more than once"
                    result[index] = image.convert("RGBA").getpixel(pixel)
    return result


@pytest.mark.parametrize("material_choice", ["original", "imported"])
@pytest.mark.parametrize("binding_kind", ["direct", "sidecar", "native-hair", "legacy-base", "partial-cache"])
def test_offline_draft_retains_original_material_previews(editor, tmp_path, material_choice, binding_kind):
    service, sid = editor
    original = service.capture_export_snapshot(sid)
    sources = tmp_path / "sources"
    sources.mkdir()
    target, context, model = material_fixture(sources, original)
    textures = [context.entries_by_normalized_path[f"character/texture/original{i}.dds"][0].paz_file
                for i in range(2)]
    Image.new("RGBA", (4, 4), (20, 50, 210, 255)).save(textures[1])
    if binding_kind == "native-hair":
        for path in textures:
            with Image.open(path) as image:
                cutout = image.convert("RGBA")
            cutout.putpixel((1, 0), (*cutout.getpixel((1, 0))[:3], 0))
            cutout.save(path)
    normal = tmp_path / "surviving-normal.dds"
    Image.new("RGBA", (4, 4), (128, 128, 255, 255)).save(normal)
    for mesh in (service._session(sid).base_mesh, service.working_mesh(sid, clone=False)):
        for index, (part, path) in enumerate(zip(mesh.submeshes, textures, strict=True)):
            part.preview_texture_dds_path = str(path)
            if binding_kind == "native-hair":
                preview = SimpleNamespace(source_submesh_index=index)
                apply_dotnet_native_material_batch_binding(preview, {
                    "material_category": "hair", "shader_family": "SkinnedMeshHair",
                    "alpha_mode": "alpha_cutout", "alpha_threshold": 0.18,
                    "dds_textures": {
                        "base": {"source_path": str(path)},
                        "material_inputs": [{
                            "slot": "base", "source_path": str(path), "owner_slot_index": index + 1,
                            "archive_path": f"character/texture/original{index}.dds",
                            "parameter_name": "_baseColorTexture", "semantic_type": "albedo",
                            "shader_family": "SkinnedMeshHair", "source_authority": "exact_sidecar",
                            "visible_class": "primary_visible", "layer_role": "layer",
                        }, {"slot": "material", "owner_slot_index": index + 2,
                            "binding_authority": "authoritative", "layer_role": "material_response"}],
                    },
                })
                copy_dotnet_preview_material_bindings(mesh, SimpleNamespace(submeshes=[preview]))
                assert part.preview_pac_material_owner_slot_index == index
            elif binding_kind in {"sidecar", "legacy-base"}:
                part.preview_material_texture_inputs = (PreviewMaterialTextureInput(
                    slot_kind="base_color", parameter_name="_diffuseTexture", source_dds_path=str(path),
                    preview_texture_path=str(path), source_texture_path=f"character/texture/original{index}.dds",
                    material_name=part.material, part_name=part.name, semantic_type="base_color",
                    confidence="sidecar", visualized=True,
                    binding_authority="guess" if binding_kind == "legacy-base" else "",
                    binding_disposition="diagnostic_only" if binding_kind == "legacy-base" else ""),)
            elif binding_kind == "partial-cache":
                part.preview_normal_texture_dds_path = str(normal)
    key = initial_replacement_state(original).parts[0].part_id
    draft = tmp_path / "draft" / "mesh_layers.json"
    with ExitStack() as stack:
        host = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=service, active_session_id=sid),
                                               tmp_path / "host", process_generation=1)
        stack.callback(lambda: host.cancel() if not host.closed else None)
        command(host, "replacement_choose", {"scope": "selected", "part_ids": [key], "source_path": str(model),
                                               "_archive_entry": target, "_archive_dependencies": context})
        applied = command(host, "replacement_apply", {"targets": [key], "materials": material_choice})
        expected = _texture_colors(host, applied["state"])
        expected_normals = _texture_colors(host, applied["state"], "normal")
        expected_alpha = _texture_colors(host, applied["state"], pixel=(1, 0))
        if binding_kind == "native-hair":
            assert expected_alpha[1][3] == 0
        if binding_kind == "partial-cache":
            assert set(expected_normals) == ({0, 1} if material_choice == "original" else {1})
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
        assert _texture_colors(recovered, recovered.state_payload()) == expected
        assert _texture_colors(recovered, recovered.state_payload(), "normal") == expected_normals
        assert _texture_colors(recovered, recovered.state_payload(), pixel=(1, 0)) == expected_alpha
        manifest = json.loads(recovered.manifest_path.read_text())
        active = recovered.archive_refit_material_cache[manifest["state"]["archive_refit_materials"]["key"]]
        assert manifest["textures"] == active["textures"]
        compared = command(recovered, "replacement_compare", {"mode": "original"})
        original_colors = _texture_colors(recovered, compared["state"])
        assert original_colors[0] == pytest.approx((20, 190, 90, 255), abs=4)
        assert original_colors[1] == pytest.approx((20, 50, 210, 255), abs=4)
        assert _texture_colors(recovered, command(recovered, "replacement_compare", {"mode": "output"})["state"]) == expected
        command(recovered, "replacement_compare", {"mode": "edit"})
        restore = tmp_path / "restore.obj"
        restore.write_text("o restored\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        command(recovered, "replacement_choose", {"scope": "selected", "part_ids": [key], "source_path": str(restore)})
        restored = command(recovered, "replacement_apply", {"targets": [key], "materials": "original"})
        assert _texture_colors(recovered, restored["state"]) == original_colors
        assert _texture_colors(recovered, command(recovered, "undo")["state"]) == expected
        assert _texture_colors(recovered, command(recovered, "redo")["state"]) == original_colors
        command(recovered, "undo")
        recovered.finish(_request(recovered, "finish_request", 61))
        snapshot = recovered_service.capture_export_snapshot(recovered_sid)
        output = recovered_service._replacement_output_for_snapshot(snapshot)
        assert (output.data, output.companion_files) == (bundle.data, bundle.companion_files)
        assert snapshot.original_data == original.original_data


@pytest.mark.parametrize("matching_direct", [False, True])
def test_captured_material_rebind_preserves_resolved_owner_and_layer_metadata(editor, tmp_path, matching_direct):
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
    direct = original.source_dds_path if matching_direct else "missing/other.dds"
    mesh.submeshes[0].preview_texture_dds_path = direct
    with prepared_replacement_material_mesh(mesh, (file,), required=False) as prepared:
        rebound = prepared.submeshes[0].preview_material_texture_inputs[0]
        assert rebound != original
        assert replace(rebound, source_dds_path=original.source_dds_path,
                       preview_texture_path=original.preview_texture_path) == original
        assert Path(rebound.source_dds_path).read_bytes() == file.data
        assert prepared.submeshes[0].preview_texture_dds_path == (rebound.source_dds_path if matching_direct else direct)
    assert mesh.submeshes[0].preview_material_texture_inputs == (original,)
    assert mesh.submeshes[0].preview_texture_dds_path == direct


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
