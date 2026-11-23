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


def test_a_package_whose_textures_are_gone_is_not_reused(tmp_path):
    """A cached Browse package outlives the archive index that prepared its textures.

    Opening the model in the Mesh Editor then stopped with "Preview Core material graph
    DDS is missing". The editor now prepares its own materials instead.
    """
    from cdmw.services.mesh_preview_material_source import native_companion_reference_mesh
    from cdmw.services.mesh_rust_preview_package import preview_core_missing_material_source

    package = _native(tmp_path)
    manifest = json.loads((package / "manifest.json").read_text())
    part = SimpleNamespace(material="helmet", preview_native_material_overrides={})
    fresh = lambda: SimpleNamespace(path="character/helmet.pac", lod_levels=[],
                                    submeshes=[copy.copy(part) for _ in range(5)])
    assert preview_core_missing_material_source(package, manifest) == ""
    mesh = fresh()
    bind_authoring_preview_core_materials(mesh, package)
    assert any(unedited_preview_core_material_source(p) for p in mesh.submeshes)
    # The index generation is replaced: the file the manifest points at is gone.
    (tmp_path / "helmet_base.dds").unlink()
    missing = preview_core_missing_material_source(package, manifest)
    assert missing and missing.endswith(".dds")
    mesh = fresh()
    bind_authoring_preview_core_materials(mesh, package)
    assert all(unedited_preview_core_material_source(p) is None for p in mesh.submeshes)
    assert native_companion_reference_mesh(SimpleNamespace(path="character/helmet.pac"), package) is None


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


@pytest.mark.parametrize("outcome", ["bound", "foreign", "cancelled", "unsupported", "incomplete",
                                     "unconserved"])
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
    if outcome in ("foreign", "unconserved"):
        path = package / "manifest.json"
        payload = json.loads(path.read_text())
        if outcome == "foreign":
            payload["source_path"] = "character/other.pac"
        else:
            # One declared texture the job could not resolve (2026-11-23).
            payload["material_conservation"]["conserved"] = False
        path.write_text(json.dumps(payload))
    if outcome == "incomplete":
        # Demenissian Council Robes' upper body: a declared normal map the game lacks
        # left this piece's own graph unconserved, and the whole set open failed.
        path = package / "manifest.json"
        payload = json.loads(path.read_text())
        payload["material_conservation"]["conserved"] = False
        payload["material_conservation"]["findings"] = ["source_dds_unavailable:helmet.pac_xml:1:_normalTexture:x_n.dds"]
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
        elif outcome in ("incomplete", "unconserved"):
            # The piece falls back to the CPU compositor; the set still opens.
            assert retained is None
            assert len(leases) == 1 and not leases[0].active
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


def test_set_source_job_gets_the_game_folder_and_archive_index_as_browse_does(tmp_path, monkeypatch):
    """Without them a technique's default texture cannot be found, so a file that declares a
    texture the game lacks got no conserved graph and its set did not open (2026-11-23)."""
    import threading

    from cdmw.rendering import native_preview_core
    from cdmw.services import mesh_preview_material_source as owner

    game = tmp_path / "Crimson Desert"
    (game / "0009").mkdir(parents=True)
    (game / "0009" / "0.pamt").write_bytes(b"")
    entry = SimpleNamespace(path="character/robe.pac", pamt_path=game / "0009" / "0.pamt")
    index = tmp_path / "index" / "archive.adx"
    index.parent.mkdir()
    index.write_bytes(b"index")
    configured = tmp_path / "Configured Game"
    configured.mkdir()
    context = SimpleNamespace(selected_entry=entry, entries=(entry,), remote=True, archive_index_path=str(index),
                              archive_package_root=str(configured),
                              entry_matching=lambda selected: entry if selected is entry else None)
    parts = [SimpleNamespace(material="robe", preview_material_texture_inputs=(SimpleNamespace(confidence="sidecar"),),
                             preview_native_material_overrides={})]
    mesh = SimpleNamespace(path=entry.path, lod_levels=[], submeshes=parts)
    jobs = []

    def native(_selected, **kwargs):
        jobs.append(kwargs)
        return SimpleNamespace(succeeded=False, package_path="")

    monkeypatch.setattr(native_preview_core, "run_native_preview_core_preview_job", native)
    assert owner.prepare_item_set_material_source(mesh, context, tmp_path / "cache", threading.Event()) is None
    # The catalogue's game folder, as Browse's job uses the configured one.
    assert jobs[0]["package_root"] == configured
    assert jobs[0]["archive_index_path"] == index

    # Without it, the game folder found from the entry's own archive files.
    jobs.clear()
    context.archive_package_root = ""
    assert owner.prepare_item_set_material_source(mesh, context, tmp_path / "cache", threading.Event()) is None
    assert jobs[0]["package_root"] == game.resolve()

    # A context from elsewhere (no index, an entry without a package path) passes neither.
    jobs.clear()
    bare = SimpleNamespace(path="character/robe.pac")
    context = SimpleNamespace(selected_entry=bare, entries=(bare,), remote=True,
                              entry_matching=lambda selected: bare if selected is bare else None)
    assert owner.prepare_item_set_material_source(
        SimpleNamespace(path=bare.path, lod_levels=[], submeshes=parts), context, tmp_path / "cache",
        threading.Event()) is None
    assert jobs[0]["package_root"] is None and jobs[0]["archive_index_path"] is None


def test_set_source_draws_the_variant_its_items_prefab_selects(tmp_path, monkeypatch):
    """The honor guard's prefab draws cd_phm_00_lb_0002 at variant 32, not variant 0."""
    import threading
    from cdmw.rendering import native_preview_core
    from cdmw.services import mesh_preview_material_source as owner
    from tests import prefab_variant_fixtures as census

    census.install(monkeypatch)
    lower = census.entry(census.HONOR_GUARD_LB)
    entries = (lower, census.entry(census.HONOR_GUARD_PREFAB), census.entry(census.FOOT_SET_PREFAB))
    context = SimpleNamespace(selected_entry=lower, entries=entries, remote=True,
                              entry_matching=lambda selected: lower if selected is lower else None)
    parts = [SimpleNamespace(material="lower", preview_material_texture_inputs=(SimpleNamespace(confidence="sidecar"),),
                             preview_native_material_overrides={})]
    mesh = SimpleNamespace(path=lower.path, lod_levels=[], submeshes=parts)
    jobs = []

    def native(selected, **kwargs):
        jobs.append(kwargs)
        return SimpleNamespace(succeeded=False, package_path="")

    monkeypatch.setattr(native_preview_core, "run_native_preview_core_preview_job", native)
    assert owner.prepare_item_set_material_source(mesh, context, tmp_path / "cache", threading.Event()) is None
    # Only the drawn file is named: the job takes at most 32 selections.
    assert jobs[0]["model_property_indices"] == {census.HONOR_GUARD_LB: 32}


def test_set_source_job_reads_shader_defaults_from_the_game_folder(tmp_path, monkeypatch):
    """A set piece's own Preview Core job gets the game folder, as Browse's job does.

    Without it the core loads no shader definitions, so a texture a material declares
    but the game lacks gets no default and the piece's graph is not conserved
    (Demenissian Council Robes, served from the DLC's 0009 group)."""
    import threading
    from cdmw.rendering import native_preview_core
    from cdmw.services import mesh_preview_material_source as owner

    game = tmp_path / "Crimson Desert"
    groups = (game / "0009", game / "dlc" / "dlc_01" / "0009")
    for group in groups:
        group.mkdir(parents=True)
        (group / "0.pamt").write_bytes(b"")
    roots = []

    def native(selected, **kwargs):
        roots.append(kwargs.get("package_root"))
        return SimpleNamespace(succeeded=False, package_path="")

    monkeypatch.setattr(native_preview_core, "run_native_preview_core_preview_job", native)
    for group in groups:
        entry = SimpleNamespace(path="character/robe.pac", pamt_path=group / "0.pamt")
        context = SimpleNamespace(selected_entry=entry, entries=(entry,), remote=True,
                                  entry_matching=lambda selected, entry=entry: entry if selected is entry else None)
        part = SimpleNamespace(material="robe", preview_material_texture_inputs=(SimpleNamespace(confidence="sidecar"),),
                               preview_native_material_overrides={})
        mesh = SimpleNamespace(path=entry.path, lod_levels=[], submeshes=[part])
        assert owner.prepare_item_set_material_source(mesh, context, tmp_path / "cache", threading.Event()) is None
    assert roots == [game.resolve(), game.resolve()]


def test_replacement_material_payloads_keep_the_graph_totals_the_editor_checks(tmp_path):
    """Import Replacement on a game model with native layers (alpha.6): the editor refused
    the result because the graph kept its old totals or no rows, and closed itself."""
    from tests.test_mesh_rust_authoring import RustMeshAuthoringTests
    from cdmw.services.mesh_rust_preview_package import conserve_preview_core_material_graph

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
        base = authoring.archive_refit_material_cache["base"]
        graph = base["preview_core_material_graph"]
        totals = {key: graph[key] for key in ("source_edge_count", "unique_resource_count",
                                              "copied_resource_count", "unique_resource_bytes")}
        unchanged = copy.deepcopy(base)
        conserve_preview_core_material_graph(unchanged)
        assert {key: unchanged["preview_core_material_graph"][key] for key in totals} == totals

        # An imported texture joins the payload: the totals count it once.
        added = copy.deepcopy(base)
        layer = next(layer[role] for row in graph["materials"] for layer in row["layers"]
                     for role in ("diffuse", "normal", "material") if layer.get(role))
        imported = {**layer, "path": "texture-0099-0123456789ab.dds", "sha256": "AB" * 32, "byte_length": 321}
        added["textures"].append({"label": "imported", "role": "base_color", "file": imported,
                                  "material_indices_by_lod": [[0]]})
        added["textures"].append({"label": "imported again", "role": "normal", "file": dict(imported),
                                  "material_indices_by_lod": [[0]]})
        conserve_preview_core_material_graph(added)
        result = added["preview_core_material_graph"]
        assert result["unique_resource_count"] == totals["unique_resource_count"] + 1
        assert result["unique_resource_bytes"] == totals["unique_resource_bytes"] + 321
        assert result["source_edge_count"] == totals["source_edge_count"]
        assert result["copied_resource_count"] <= result["unique_resource_count"]

        # Every part replaced: no row is left, and the editor refuses an empty graph.
        replaced = copy.deepcopy(base)
        replaced["preview_core_material_graph"]["materials"] = []
        conserve_preview_core_material_graph(replaced)
        assert replaced["preview_core_material_graph"] is None
    finally:
        authoring.cancel()
        service.close_edit_session("authoritative-rust-test", force_without_saving=True)


def test_binding_signature_survives_json_int_float_round_trip_for_v1_and_v2(tmp_path):
    from cdmw.modding.mesh_native_snapshot_codec import _restored_snapshot_metadata_value
    from cdmw.services.mesh_preview_material_source import _legacy_binding_signature

    package = _native(tmp_path)
    native = json.loads((package / "manifest.json").read_text())
    batch = native["batches"][0]
    conservation = native["material_conservation"]

    def make_part():
        return SimpleNamespace(
            material=batch["material_name"],
            texture="",
            preview_color=[1.0, 1.0, 1.0],
            preview_normal_texture_strength=1.0,
            preview_native_material_overrides={"roughness": 1.0, "metalness": 0.0},
        )

    part_v2 = make_part()
    bind_preview_core_material_source(part_v2, package, batch, conservation)
    # Simulate C++ JSON serializer writing whole floats as ints and snapshot restore reading JSON.
    for target, versioned in ((part_v2, True), (make_part(), False)):
        if not versioned:
            target.preview_native_material_overrides["preview_core_material_source"] = {
                "package": str(package),
                "batch": dict(batch),
                "conservation": dict(conservation),
                "binding_signature": _legacy_binding_signature(target),
            }
        target.preview_color = _restored_snapshot_metadata_value("preview_color", [1, 1, 1])
        target.preview_normal_texture_strength = _restored_snapshot_metadata_value(
            "preview_normal_texture_strength", 1
        )
        # Also simulate an uncoerced nested override int (metalness=0, roughness=1) on v2.
        if versioned:
            target.preview_native_material_overrides["roughness"] = 1
            target.preview_native_material_overrides["metalness"] = 0
        assert unedited_preview_core_material_source(target) is not None
        # Real material edits must still invalidate both v1 and v2 signatures.
        target.preview_color = [0.5, 1.0, 1.0]
        assert unedited_preview_core_material_source(target) is None


def _decoded(root):
    """A mesh whose parts are bound to a native package under ``root``, as one cache generation holds it."""
    root.mkdir(parents=True)
    return decode_dotnet_native_preview_package(_native(root))


def test_a_restored_part_takes_this_sessions_bindings_when_only_the_cache_moved(tmp_path):
    """A saved editor state stores its material bindings as paths into the archive index and
    preview caches. After those were rebuilt the stored native source no longer counted as
    unedited, and Continue Editing drew the draft's raw textures without their layers."""
    import shutil

    from cdmw.services.mesh_preview_material_source import adopt_current_material_bindings

    saved = _decoded(tmp_path / "generation-1")
    current = _decoded(tmp_path / "generation-2")
    restored, bound = saved.submeshes[0], current.submeshes[0]
    source = unedited_preview_core_material_source(bound)
    stored = unedited_preview_core_material_source(restored)
    assert source is not None and stored is not None and stored is not source
    # While the saved state's own files exist it keeps what it stored.
    assert adopt_current_material_bindings(saved, current) == 0
    assert unedited_preview_core_material_source(restored) is stored

    shutil.rmtree(tmp_path / "generation-1")  # the cache generation it points into is gone
    assert unedited_preview_core_material_source(restored) is None
    assert adopt_current_material_bindings(saved, current) >= 1
    assert unedited_preview_core_material_source(restored) is source
    assert str(restored.preview_texture_dds_path).startswith(str(tmp_path / "generation-2"))
    # Nothing of the session's own part is shared but the read-only source.
    restored.preview_native_material_overrides["roughness"] = 0.91
    assert unedited_preview_core_material_source(bound) is source


@pytest.mark.parametrize("difference", ["tint", "override", "renamed", "unbound_session", "ambiguous"])
def test_a_restored_part_keeps_its_stored_material_when_more_than_the_cache_moved(tmp_path, difference):
    import shutil

    from cdmw.services.mesh_preview_material_source import adopt_current_material_bindings

    saved = _decoded(tmp_path / "generation-1")
    current = _decoded(tmp_path / "generation-2")
    restored, bound = saved.submeshes[0], current.submeshes[0]
    if difference == "tint":
        restored.preview_texture_tint = (0.1, 0.2, 0.3)  # an edit made before the state was saved
    elif difference == "override":
        restored.preview_native_material_overrides["roughness"] = 0.91
    elif difference == "renamed":
        restored.name = "Renamed part"
    elif difference == "unbound_session":
        bound.preview_native_material_overrides.pop("preview_core_material_source")
    else:
        current.submeshes.append(copy.copy(bound))
    kept = copy.deepcopy({name: getattr(restored, name, None) for name in (
        "preview_texture_tint", "preview_texture_dds_path", "preview_native_material_overrides")})
    shutil.rmtree(tmp_path / "generation-1")
    adopt_current_material_bindings(saved, current)
    assert unedited_preview_core_material_source(restored) is None
    assert {name: getattr(restored, name, None) for name in kept} == kept
