"""Private material texture copies keep exact source pins and borrowed limits."""
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
import xml.etree.ElementTree as ET

import pytest

from cdmw.domain.new_item.spec import ModelSource
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_remove, resolve_items
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.independent_item_references import audit_references
from cdmw.services.new_item_planning import ModelFiles, _Planner
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_item_physics import collision, physics_game
from tests.test_independent_item_regressions import files_in
from tests.test_new_item_service import PAC, PAC_XML, STEM, build_package, imported_pac
from tests.test_new_item_variant_authoring import selections


TEXTURE = f"character/texture/1_pc/{STEM}_d.dds"


def texture_paths(data):
    tree = ET.fromstring("<Model>" + data.decode("utf-8-sig") + "</Model>")
    return {node.attrib["_path"].replace("\\", "/").lower() for node in tree.iter()
            if node.tag == "ResourceReferencePath_ITexture" and node.attrib.get("_path")}


@pytest.mark.parametrize("variant", [False, True])
def test_owned_template_materials_copy_supported_dds_without_supplied_texture_blobs(tmp_path, collision, variant):
    service, snapshot = physics_game(tmp_path, collision)
    choice = shop_spec("PrivateTemplateTexture")
    kwargs = {}
    if variant:
        selected = next(row for row in selections(snapshot) if row.model_path == PAC)
        choice = replace(choice, variants=(selected,))
    else:
        choice = replace(choice, model_source=ModelSource.IMPORTED)
        kwargs["model"] = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)})
    plan = service.plan(choice, snapshot, capture_independent=True, **kwargs)
    outputs = {row.path: bytes(row.payload_data) for row in plan.additions}
    materials = {path: data for path, data in outputs.items() if path.endswith(".pac_xml")}
    assert materials
    targets = set().union(*(texture_paths(data) for data in materials.values()))
    assert TEXTURE not in targets
    assert targets and targets <= outputs.keys()
    assert all(outputs[path] == snapshot.payload(TEXTURE) for path in targets)
    assert len(targets) == 1  # Multiple owned materials reuse one private source copy.
    assert targets <= set(plan.manifest["texture_registry"])
    assert targets <= set(plan.manifest["model_files"])
    package = from_plan(plan, uuid4().hex)
    assert TEXTURE in package.dependencies
    assert snapshot.payload(TEXTURE) not in package.blobs.values()
    graph = plan.reference_assessment
    resources = {row.path: row for row in graph.resources}
    assert resources[TEXTURE].ownership == "borrowed"
    assert all(resources[path].ownership == "owned" for path in targets)
    assert all(resources[path].source_paths == (TEXTURE,) for path in targets)
    assert any(row.path.endswith(".sockets.xml") and row.ownership == "borrowed"
               for row in graph.resources)
    assert not graph.reference_closure_complete


def test_ordinary_material_authoring_keeps_existing_borrowed_texture_behavior(tmp_path, collision):
    service, snapshot = physics_game(tmp_path, collision)
    selected = next(row for row in selections(snapshot) if row.model_path == PAC)
    plan = service.plan(replace(shop_spec("OrdinaryTemplateTexture"), variants=(selected,)), snapshot)
    materials = [bytes(row.payload_data) for row in plan.additions if row.path.endswith(".pac_xml")]
    assert materials and any(TEXTURE in texture_paths(data) for data in materials)
    assert not any(row.path.endswith(".dds") for row in plan.additions)


def test_selected_prefab_companion_materials_share_one_owned_copy_and_leave_other_variants_borrowed(tmp_path, collision):
    from cdmw.core.prefab_component_graft import graft_prefab_component
    from cdmw.services.new_item_variants import xml_path

    service, initial = physics_game(tmp_path, collision)
    selected = next(row for row in selections(initial) if row.model_path == PAC)
    companion = PAC.removesuffix(".pac") + "_companion.pac"
    files = {path: initial.payload(path) for path in initial.entries}
    files[companion], files[xml_path(companion)] = files[PAC], files[PAC_XML]
    files[selected.prefab_path] = graft_prefab_component(files[selected.prefab_path], files[selected.prefab_path],
        component_type="SkinnedMeshComponent", path_replacements={PAC: companion}).data
    build_package(tmp_path / "game", files)
    snapshot = snapshot_of(tmp_path / "game")
    plan = service.plan(replace(shop_spec("PrivateCompanion"), variants=(selected,)), snapshot,
                        capture_independent=True)
    variants = plan.manifest["variants"]
    owned = [row for row in variants if "output_model" in row]
    assert len(owned) == 2 and any(row["model_path"] == companion and row["companion"] for row in owned)
    assert any(row["model_path"] == PAC and row["appearance"] == "template" for row in variants)
    outputs = {row.path: bytes(row.payload_data) for row in plan.additions}
    paths = [texture_paths(outputs[xml_path(row["output_model"])]) for row in owned]
    assert paths[0] == paths[1] and len(paths[0]) == 1 and TEXTURE not in paths[0]
    assert next(iter(paths[0])) in outputs
    assert snapshot.payload(PAC_XML) == files[PAC_XML] and TEXTURE in texture_paths(snapshot.payload(PAC_XML))
    assert any(row.path == TEXTURE and row.ownership == "borrowed" for row in plan.reference_assessment.resources)


def test_unhandled_material_resource_edge_remains_borrowed_and_explicit(tmp_path, collision):
    service, snapshot = physics_game(tmp_path, collision)
    resource = f'<ResourceReferencePath_IModel Name="_value" _path="{TEXTURE}"/>'.encode()
    material = snapshot.payload(PAC_XML).replace(b"</ModelPropertyList>", resource + b"</ModelPropertyList>")
    assert resource in material
    choice = replace(shop_spec("PartlyPrivateMaterial"), model_source=ModelSource.IMPORTED)
    plan = service.plan(choice, snapshot,
        model=ModelFiles(imported_pac(100), {PAC_XML: material}), capture_independent=True)
    graph = plan.reference_assessment
    rows = {row.path: row for row in graph.resources}
    assert rows[TEXTURE].ownership == "borrowed" and "contribution" in rows[TEXTURE].reachability
    assert any(row.path.endswith(".dds") and row.ownership == "owned" for row in graph.resources)
    assert any("outside the private DDS lookup scope" in problem for problem in graph.unresolved)


def test_unsupported_source_dds_keeps_its_original_binding_and_dependency(tmp_path, collision):
    service, initial = physics_game(tmp_path, collision)
    files = {path: initial.payload(path) for path in initial.entries}
    files[TEXTURE] = files[TEXTURE][:-1]
    build_package(tmp_path / "game", files)
    snapshot = snapshot_of(tmp_path / "game")
    choice = replace(shop_spec("BorrowedUnsupportedDDS"), model_source=ModelSource.IMPORTED)
    plan = service.plan(choice, snapshot,
        model=ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)}), capture_independent=True)
    assert not any(row.path.endswith(".dds") for row in plan.additions)
    assert any(TEXTURE in texture_paths(row.payload_data) for row in plan.additions if row.path.endswith(".pac_xml"))
    assert any(TEXTURE in warning and "retains its source binding" in warning for warning in plan.warnings)
    assert TEXTURE in from_plan(plan, uuid4().hex).dependencies


@pytest.mark.parametrize("limit", ["bytes", "paths"])
def test_shared_immutable_payloads_still_consume_each_owned_output_budget(tmp_path, collision, monkeypatch, limit):
    from cdmw.services import independent_item_package as package_owner

    service, snapshot = physics_game(tmp_path, collision)
    choice = service.allocate(shop_spec("BoundedCopies"), snapshot)
    planner = _Planner(choice, snapshot, None, None, None, None, independent=True)
    data, entry = snapshot.payload(TEXTURE), snapshot.entry(TEXTURE)
    if limit == "bytes":
        monkeypatch.setattr(package_owner, "MAX_TOTAL", len(data) * 2 - 1)
    else:
        monkeypatch.setattr(package_owner, "MAX_FILES", 1)
    planner.add(entry, "character/texture/first.dds", data, "first")
    with pytest.raises(ValueError, match="size limit|file-count limit"):
        planner.add(entry, "character/texture/second.dds", data, "second")
    assert len(planner.additions) == 1 and planner.additions[0].payload_data is data
    assert planner.owned_resource_bytes == len(data)


def test_automatic_texture_size_limit_refuses_before_source_payload_read(monkeypatch):
    from cdmw.services import independent_item_package as package_owner
    from cdmw.services.new_item_resource_copies import copy_material_textures

    monkeypatch.setattr(package_owner, "MAX_BLOB", 1024)
    reads = []
    snapshot = SimpleNamespace(entry=lambda _path: SimpleNamespace(orig_size=1025),
                               payload=lambda path: reads.append(path))
    planner = SimpleNamespace(snapshot=snapshot, new_stem="cdmw_private", check=lambda: None,
                              additions=[], owned_resource_bytes=0, private_texture_copies={})
    material = f'<ModelPropertyList><ResourceReferencePath_ITexture _path="{TEXTURE}"/></ModelPropertyList>'.encode()
    with pytest.raises(ValueError, match="per-file size limit"):
        copy_material_textures(planner, material, {})
    assert reads == [] and planner.additions == []


def test_private_copy_does_not_hide_an_incomplete_package_source_graph(tmp_path, collision):
    service, snapshot = physics_game(tmp_path, collision)
    choice = replace(shop_spec("MissingTexturePin"), model_source=ModelSource.IMPORTED)
    plan = service.plan(choice, snapshot,
        model=ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)}), capture_independent=True)
    package = from_plan(plan, uuid4().hex)
    incomplete = replace(package, dependencies={path: value for path, value in package.dependencies.items() if path != TEXTURE})
    before = files_in(tmp_path / "game")
    with pytest.raises(IndependentItemError, match="incomplete game dependency graph"):
        resolve_items([package_bytes(incomplete)], tmp_path / "game", target="virtual")
    assert files_in(tmp_path / "game") == before


def test_automatic_copy_source_evidence_is_derived_from_the_actual_payload(tmp_path, collision):
    service, snapshot = physics_game(tmp_path, collision)
    choice = replace(shop_spec("CheckedCopyEvidence"), model_source=ModelSource.IMPORTED)
    plan = service.plan(choice, snapshot,
        model=ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)}), capture_independent=True)
    texture = next(row for row in plan.additions if row.path.endswith(".dds"))
    changed = bytes(texture.payload_data[:-1]) + bytes([texture.payload_data[-1] ^ 1])
    graph = audit_references(replace(plan, additions=tuple(
        replace(row, payload_data=changed) if row is texture else row for row in plan.additions)), snapshot)
    resource = next(row for row in graph.resources if row.path == texture.path)
    assert resource.ownership == "owned" and resource.source_paths == ()
    assert not any("match the retained DDS source" in evidence for evidence in resource.source_evidence)


@pytest.mark.parametrize("target", ["archive", "virtual"])
@pytest.mark.parametrize("reverse", [False, True])
def test_two_packages_keep_private_texture_bytes_through_update_and_removal(tmp_path, collision, target, reverse, monkeypatch):
    from cdmw.services.independent_mod_package import migrate_v1

    service, snapshot = physics_game(tmp_path, collision)
    choice = replace(shop_spec("TwoPrivateMaterials"), model_source=ModelSource.IMPORTED)
    material = snapshot.payload(PAC_XML)
    base = service.plan(choice, snapshot,
        model=ModelFiles(imported_pac(100), {PAC_XML: material}), capture_independent=True)
    first, second = [from_plan(base, uuid4().hex) for _ in range(2)]
    second = migrate_v1(second)
    original = snapshot.payload(TEXTURE)
    changed = original[:-1] + bytes([original[-1] ^ 1])
    updated = from_plan(service.plan(choice, snapshot,
        model=ModelFiles(imported_pac(100), {PAC_XML: material, TEXTURE: changed}),
        capture_independent=True), first.identity)
    root, backups = tmp_path / "game", Backups(tmp_path)
    if target == "virtual":
        monkeypatch.setattr("cdmw.services.new_item_service.game_is_running", lambda *_args, **_kwargs: False)
    from tests.test_virtual_loader import game_bytes
    before = game_bytes(root)

    def apply(packages):
        if target == "archive":
            backups.apply(prepare_install([package_bytes(package) for package in packages], root).preparation)
            return
        from cdmw.domain.virtual_loader import VirtualProfile
        from cdmw.services.virtual_loader_composition import prepare_profile
        from cdmw.services.virtual_loader_state import publish_profile
        paths = []
        for package in packages:
            source = tmp_path / f"{package.identity}.cditem"
            source.write_bytes(package_bytes(package))
            paths.append(source)
        publish_profile(prepare_profile(VirtualProfile(tuple(paths)), root))

    def active_entries():
        if target == "archive":
            return snapshot_of(root).entries
        from cdmw.core.archive_format import parse_archive_pamt
        from cdmw.services.virtual_loader_state import load_profile
        generation = root / ".cdmw/virtual-loader/generations" / load_profile(root)["generation"] / "files"
        return {entry.path: entry for pamt in generation.glob("*/0.pamt") for entry in parse_archive_pamt(pamt)}

    def payload(path):
        from cdmw.core.archive_extraction import read_archive_entry_data
        return read_archive_entry_data(active_entries()[path])[0]

    packages = [second, first] if reverse else [first, second]
    apply(packages)
    records = load_registry(root)["items"]
    paths = [next(path for path in records[package.identity]["paths"] if path.endswith(".dds"))
             for package in (first, second)]
    assert paths[0] != paths[1]
    assert all(payload(path) == original for path in paths)
    first_material = next(path for path in records[first.identity]["paths"] if path.endswith(".pac_xml"))
    apply([updated if package.identity == first.identity else package for package in packages])
    assert payload(paths[1]) == original and snapshot_of(root).payload(TEXTURE) == original
    assert paths[0] not in active_entries()
    updated_texture, = texture_paths(payload(first_material))
    assert updated_texture != paths[0] and payload(updated_texture) == changed
    assert paths[0] in load_registry(root)["items"][first.identity]["paths"]
    if target == "archive":
        backups.apply(prepare_remove(first.identity, root))
    else:
        apply([second])
    assert payload(paths[1]) == original
    assert load_registry(root)["items"][second.identity]["values"] == records[second.identity]["values"]
    if target == "virtual":
        assert game_bytes(root) == before


def test_private_copy_cost_keeps_portable_inputs_and_source_pins_unchanged(tmp_path, monkeypatch):
    import json
    from time import perf_counter
    from cdmw.services import new_item_resource_copies as copies
    from tests.test_independent_items import imported_game

    identity, measurements, packages = uuid4().hex, {}, {}
    choice = replace(shop_spec("TextureCopyCost"), model_source=ModelSource.IMPORTED)
    for enabled in (False, True):
        service, snapshot = imported_game(tmp_path / str(enabled))
        model = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)})
        baseline_pathc = (tmp_path / str(enabled) / "game/meta/0.pathc").read_bytes()
        with monkeypatch.context() as context:
            if not enabled:
                # The recipe has no supplied DDS. Disabling only automatic
                # copies reconstructs its previous unchanged-material output.
                context.setattr(copies, "copy_material_textures", lambda _planner, data, _mapping: (data, ()))
            start = perf_counter()
            plan = service.plan(choice, snapshot, model=model, capture_independent=True)
            elapsed = perf_counter() - start
        package = from_plan(plan, identity)
        packages[enabled] = package
        owned = {row.path: row.payload_data for row in plan.additions}
        pathc = next((row.payload_data for row in plan.meta_files if row.path == "meta/0.pathc"), baseline_pathc)
        measurements[enabled] = {
            "dds_outputs": sum(path.endswith(".dds") for path in owned),
            "dds_bytes": sum(len(data) for path, data in owned.items() if path.endswith(".dds")),
            "material_bytes": sum(len(data) for path, data in owned.items() if path.endswith(".pac_xml")),
            "owned_resource_bytes": sum(map(len, owned.values())),
            "pathc_bytes": len(pathc),
            "package_blob_bytes": sum(map(len, package.blobs.values())),
            "package_zip_bytes": len(package_bytes(package)),
            "compiler_seconds": round(elapsed, 6),
        }
    assert packages[False].dependencies == packages[True].dependencies
    assert packages[False].blobs == packages[True].blobs
    assert measurements[True]["dds_outputs"] == measurements[False]["dds_outputs"] + 1
    assert measurements[True]["dds_bytes"] == len(snapshot.payload(TEXTURE))
    assert measurements[True]["package_zip_bytes"] == measurements[False]["package_zip_bytes"]
    delta = {key: measurements[True][key] - measurements[False][key]
             for key in measurements[True] if key != "compiler_seconds"}
    print(json.dumps({"scope": "synthetic imported mesh with retained template material", "delta": delta,
                      "compiler_seconds": {str(key): value["compiler_seconds"] for key, value in measurements.items()},
                      "native_runtime_cost": "unmeasured"}, sort_keys=True))
