import copy
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from cdmw.services.mesh_preview_material_source import (
    bind_authoring_preview_core_materials, bind_preview_core_material_source,
    unedited_preview_core_material_source,
)
from cdmw.services.mesh_rust_authoring import _submesh_has_material_synthesis_inputs
from cdmw.services.mesh_rust_preview_package import build_rust_preview_package
from cdmw.services.mesh_dotnet_reference_composite import decode_dotnet_native_preview_package
from tests.test_rust_preview_production_cutover import _write_schema8_preview_core_fixture


def _native(tmp_path):
    package, *_ = _write_schema8_preview_core_fixture(tmp_path)
    Image.new("RGBA", (4, 4), (120, 80, 40, 255)).save(tmp_path / "helmet_base.dds")
    return package


@pytest.mark.parametrize("edit", ["tint", "input", "override", "material", "path", "file"])
def test_only_unchanged_material_bindings_keep_native_graph(tmp_path, edit):
    package = _native(tmp_path)
    mesh = decode_dotnet_native_preview_package(package)
    part = mesh.submeshes[0]
    source = unedited_preview_core_material_source(part)
    assert source is not None
    assert not _submesh_has_material_synthesis_inputs(part)
    # Geometry and placement remain editable without baking their materials.
    part.vertices = [(0., 0., 0.)] * len(part.vertices)
    part.preview_role = "placed_item"
    assert unedited_preview_core_material_source(part) is not None
    if edit == "tint":
        part.preview_texture_tint = (0.1, 0.2, 0.3)
    elif edit == "input":
        part.preview_material_texture_inputs = (SimpleNamespace(confidence="sidecar", parameter_name="_baseColorTexture"),)
    elif edit == "override":
        part.preview_native_material_overrides["roughness"] = .91
    elif edit == "material":
        part.material = "replacement"
    elif edit == "path":
        part.preview_texture_dds_path = str(tmp_path / "replacement.dds")
    else:
        (tmp_path / "helmet_base.dds").write_bytes(b"replaced")
    assert unedited_preview_core_material_source(part) is None


def test_authoring_attaches_only_exact_file_section_and_material(tmp_path):
    package = _native(tmp_path)
    native = json.loads((package / "manifest.json").read_text())
    part = SimpleNamespace(material="helmet", preview_native_material_overrides={})
    mesh = SimpleNamespace(path="character/helmet.pac", lod_levels=[], submeshes=[copy.copy(part) for _ in range(5)])
    bind_authoring_preview_core_materials(mesh, package)
    assert [i for i, p in enumerate(mesh.submeshes) if unedited_preview_core_material_source(p)] == [4]
    for path in ("imported/helmet.pac", "character/other.pac"):
        mesh = SimpleNamespace(path=path, lod_levels=[], submeshes=[copy.copy(part) for _ in range(5)])
        bind_authoring_preview_core_materials(mesh, package)
        assert all(unedited_preview_core_material_source(p) is None for p in mesh.submeshes)
    native["batches"].append(native["batches"][0])
    (package / "manifest.json").write_text(json.dumps(native))
    mesh = SimpleNamespace(path="character/helmet.pac", lod_levels=[], submeshes=[copy.copy(part) for _ in range(5)])
    bind_authoring_preview_core_materials(mesh, package)
    assert all(unedited_preview_core_material_source(p) is None for p in mesh.submeshes)


def test_new_item_graph_and_painted_alpha_use_same_owned_source(tmp_path):
    from cdmw.domain.textures.transparency_mask import TransparencyMask
    from cdmw.services.transparency_masks import preview_masked_part

    package = _native(tmp_path)
    mesh = decode_dotnet_native_preview_package(package)
    for glass, expected in ((True, 1), (False, 2)):
        painted = copy.copy(mesh)
        painted.submeshes = [preview_masked_part(mesh.submeshes[0], TransparencyMask(64, 16, bytes(1024)), glass=glass)]
        painted.lod_levels = [painted.submeshes]
        assert unedited_preview_core_material_source(painted.submeshes[0]) is not None
        output = build_rust_preview_package(painted, output_package_dir=tmp_path / str(expected))
        manifest = json.loads(output.manifest_path.read_text())
        assert manifest["preview_core_material_graph"]["materials"][0]["authoring_channels"] == expected
        assert manifest["material_contract"]["conservation"]["conserved"]


def test_real_authoring_manifest_retains_original_material_graph(tmp_path):
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
        assert manifest["preview_core_material_graph"]["materials"][0]["material_name"] == "helmet"
        assert "preview_core_geometry" not in manifest
        assert manifest["output_policy"]["policy"] == "exact_game_asset"
        assert authoring.material_synthesis_budget_parts == (0, 0)
    finally:
        authoring.cancel()
        service.close_edit_session("authoritative-rust-test", force_without_saving=True)


def test_edited_native_material_bakes_only_its_owned_part(tmp_path, monkeypatch):
    from cdmw.services import mesh_rust_authoring as authoring
    from cdmw.services.mesh_rust_replacement_materials import _bake_edited_native_layers

    mesh = decode_dotnet_native_preview_package(_native(tmp_path))
    mesh.submeshes.append(copy.deepcopy(mesh.submeshes[0]))
    mesh.lod_levels = [mesh.submeshes]
    original = {"preview_core_material_graph": {"materials": [
        {"lod_index": 0, "material_index": 0}, {"lod_index": 0, "material_index": 1}]},
        "textures": [{"file": {"path": "original.dds"}, "material_indices_by_lod": [[0, 1]]}],
        "material_presentations": authoring._mesh_material_presentations(mesh)}
    payload = copy.deepcopy(original)
    def bake(root, selected, **kwargs):
        assert len(selected.submeshes) == 1
        assert unedited_preview_core_material_source(selected.submeshes[0]) is None
        kwargs["synthesis_state"].presentation_overrides[(0, 0)] = {"normal_y_policy": "preserve"}
        return [{"file": {"path": "baked.dds"}, "material_indices_by_lod": [[0]]}]
    monkeypatch.setattr(authoring, "_mesh_texture_payloads", bake)
    _bake_edited_native_layers(SimpleNamespace(root=tmp_path, root_identity=()), mesh, payload, {(0, 0)}, None)
    assert payload["preview_core_material_graph"]["materials"] == [{"lod_index": 0, "material_index": 1}]
    assert [(row["file"]["path"], row["material_indices_by_lod"]) for row in payload["textures"]] == [
        ("original.dds", [[1]]), ("baked.dds", [[0]])]
    assert payload["material_presentations"][0]["normal_y_policy"] == "preserve"
    assert len(original["preview_core_material_graph"]["materials"]) == 2
    assert unedited_preview_core_material_source(mesh.submeshes[0]) is not None


def test_edited_new_item_material_enters_existing_compositor(tmp_path, monkeypatch):
    from cdmw.services import mesh_rust_authoring as authoring
    mesh = decode_dotnet_native_preview_package(_native(tmp_path))
    mesh.submeshes[0].preview_texture_tint = (0.3, 0.2, 0.1)
    # The real material context carries these owned inputs; the compact native
    # fixture needs one to exercise the compositor rather than a flat fallback.
    mesh.submeshes[0].preview_material_texture_inputs = (
        SimpleNamespace(parameter_name="_baseColorTexture", confidence="sidecar"),)
    calls = []
    def bake(selected, *_args, **_kwargs):
        calls.append(selected)
        assert authoring._submesh_has_material_synthesis_inputs(selected.submeshes[0])
        return {}
    monkeypatch.setattr(authoring, "_mesh_synthesized_texture_overrides", bake)
    output = build_rust_preview_package(mesh, output_root=tmp_path / "output")
    assert len(calls) == 1
    assert "preview_core_material_graph" not in json.loads(output.manifest_path.read_text())


@pytest.mark.parametrize("outcome", ["bound", "foreign", "cancelled", "unsupported"])
def test_set_source_uses_its_native_graph_and_releases_failed_leases(tmp_path, monkeypatch, outcome):
    import threading
    from cdmw.domain.cancellation import RunCancelled
    from cdmw.rendering import native_preview_core, native_preview_package_cache
    from cdmw.services import mesh_preview_material_source as owner

    package = _native(tmp_path)
    entry = SimpleNamespace(path="character/helmet.pac")
    context = SimpleNamespace(selected_entry=entry, entries=(entry,), remote=True,
                              entry_matching=lambda selected: entry if selected is entry else None)
    parts = [SimpleNamespace(material="helmet", source_descriptor_offset=64,
        preview_material_texture_inputs=(SimpleNamespace(confidence="sidecar"),),
        preview_native_material_overrides={}) for _ in range(5)]
    mesh = SimpleNamespace(path=entry.path, lod_levels=[], submeshes=parts)
    stop = threading.Event()
    calls, leases = [], []
    if outcome == "foreign":
        path = package / "manifest.json"
        payload = json.loads(path.read_text())
        payload["source_path"] = "character/other.pac"
        path.write_text(json.dumps(payload))
    def native(selected, **kwargs):
        assert selected is entry
        assert kwargs["dependency_entries"] == (entry,)
        assert kwargs["dependency_entries_complete"] is True
        assert kwargs["stop_event"] is stop
        calls.append(selected)
        return SimpleNamespace(succeeded=outcome != "unsupported", package_path=str(package))
    acquire = native_preview_package_cache.acquire_native_preview_package_cache_lease_for_path
    def lease(path):
        result = acquire(path)
        leases.append(result)
        return result
    bind = owner.bind_authoring_preview_core_materials
    def bind_and_cancel(*args):
        bind(*args)
        stop.set()
    monkeypatch.setattr(native_preview_core, "run_native_preview_core_preview_job", native)
    monkeypatch.setattr(native_preview_package_cache, "acquire_native_preview_package_cache_lease_for_path", lease)
    if outcome == "cancelled":
        monkeypatch.setattr(owner, "bind_authoring_preview_core_materials", bind_and_cancel)
    if outcome in ("foreign", "cancelled"):
        with pytest.raises(ValueError if outcome == "foreign" else RunCancelled):
            owner.prepare_item_set_material_source(mesh, context, tmp_path / "cache", stop)
        assert len(leases) == 1 and not leases[0].active
    else:
        retained = owner.prepare_item_set_material_source(mesh, context, tmp_path / "cache", stop)
        if outcome == "unsupported":
            assert retained is None and not leases
            assert all(unedited_preview_core_material_source(part) is None for part in parts)
        else:
            try:
                assert copy.deepcopy(retained) is retained
                assert retained.lease.active
                assert [i for i, part in enumerate(parts) if unedited_preview_core_material_source(part)] == [4]
                assert parts[4].source_descriptor_offset == 64
            finally:
                retained.lease.release()
    assert calls == [entry]
