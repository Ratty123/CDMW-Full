"""Exercise all appearance routes with PAC part names distinct from material labels."""
import copy
import json
import threading
from types import SimpleNamespace

import pytest

from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.mesh.emission import EmissionChoice
from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.domain.mesh.shader_controls import FAMILIES, ShaderControls
from cdmw.domain.new_item.spec import GlowChoice
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_pac
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from tests.test_new_item_materials import dds
from tests.test_shader_controls import material
from tests.test_static_mesh_replacer_preview import _minimal_two_part_pac_original


def named_parts(alias):
    raw, _ = _minimal_two_part_pac_original()
    for index in range(2):
        name = f"target{index}".encode()
        raw = raw.replace(b"\x07" + name + b"\x07" + name, b"\x07" + name + b"\x07" + alias.encode())
    data = bytearray(raw)
    for part in parse_pac(raw).submeshes:
        for offset in part.source_vertex_offsets:
            data[offset + 28] = 255
    return bytes(data)


def dependencies(mesh):
    xml = mesh.path.replace("/model/", "/modelproperty/") + "_xml"
    text = "\n".join(material(name=part.name) for part in mesh.submeshes)
    return (ReplacementFile(xml, text.encode()), ReplacementFile(FAMILIES[0].default_mask, dds()))


@pytest.mark.parametrize("alias", ["blade_n", "sharedX", "target0"])
@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("feature", ["translucency", "emission", "shader_controls"])
def test_mesh_commands_bind_each_part_preserve_other_parts_and_round_trip(tmp_path, monkeypatch, alias, index, feature):
    from tests import test_mesh_rust_authoring_exact_output as exact
    from tests.test_mesh_rust_replacement import command
    raw = named_parts(alias)
    monkeypatch.setattr(exact, "_pac_fixture", lambda **_: raw)
    monkeypatch.setattr("cdmw.services.shader_controls_preview.gettempdir", lambda: str(tmp_path))
    original, service, session = exact._open_exact_session(tmp_path / "session")
    try:
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        assert any(part.name != part.material for part in snapshot.mesh.submeshes)
        captured = dependencies(snapshot.mesh)
        monkeypatch.setattr("cdmw.services.mesh_replacement_materials.capture_replacement_dependencies", lambda *_: captured)
        baseline = copy.deepcopy(session.archive_refit_material_cache["base"])
        monkeypatch.setattr("cdmw.services.mesh_rust_authoring._mesh_texture_payloads",
                            lambda *_a, **_k: pytest.fail("appearance edit decoded base maps again"))
        key = session.state_payload()[feature]["parts"][index]["id"]
        value = {"translucency": [.25, .75], "emission": EmissionChoice((1., .2, .1), 6).to_dict(),
                 "shader_controls": ShaderControls("SkinnedMeshWing", (("_wingFlowProgress", (.6,)),)).to_dict()}[feature]
        edited = command(session, "replacement_" + feature, {"part_ids": [key], feature: value})
        packet = session.archive_refit_material_cache[edited["state"]["archive_refit_materials"]["key"]]
        for row in packet["material_presentations"]:
            if row["material_index"] == index:
                if feature == "translucency": assert row[feature] == value
                elif feature == "emission": assert row["emissive_intensity"] == 6
                else: assert row[feature][4] == .6
            else:
                old = next(r for r in baseline["material_presentations"] if r["material_index"] == row["material_index"] and r["lod_index"] == row["lod_index"])
                assert row == old
        command(session, "undo")
        assert session.shadow_service.capture_export_snapshot(session.shadow_session_id).replacement_state is None
        command(session, "redo")
        output = prepare_replacement_output(session.shadow_service.capture_export_snapshot(session.shadow_session_id))
        assert output.data == original
        text = next(f.data.decode("utf-8-sig") for f in output.companion_files if f.path.endswith("_xml"))
        before, after = find_material_wrappers(captured[0].data.decode()), find_material_wrappers(text)
        assert after[index].shader == {"translucency": "SkinnedMeshTranslucent", "emission": "SkinnedMeshEmissive", "shader_controls": "SkinnedMeshWing"}[feature]
        assert after[1 - index].parameters == before[1 - index].parameters
        assert session.archive_refit_material_cache["base"] == baseline
        command(session, "replacement_" + feature, {"part_ids": [key], "reset": True})
        assert not prepare_replacement_output(session.shadow_service.capture_export_snapshot(session.shadow_session_id)).companion_files
    finally:
        if not session.closed: session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)


@pytest.mark.parametrize("surface", ["placement", "effects"])
@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("feature", ["translucency", "glow", "shader_controls", "eye_cover"])
def test_new_item_both_preview_stages_apply_each_named_part(tmp_path, monkeypatch, surface, index, feature):
    from cdmw.ui.new_item.controller_preview_mixin import _template_progressive_source
    from cdmw.ui.new_item.effect_item_source import PlannedEffectItemSource
    from cdmw.ui.new_item.item_preview import build_item_preview_package
    from cdmw.ui.new_item.model_import import ModelPlacement
    from cdmw.services.effect_placement_preview import build_effect_placement_package
    monkeypatch.setattr("cdmw.services.shader_controls_preview.gettempdir", lambda: str(tmp_path))
    raw = named_parts("sharedX")
    mesh = parse_pac(raw, "character/model/item.pac")
    files = {f.path: f.data for f in dependencies(mesh)}
    files[mesh.path] = raw
    snapshot = SimpleNamespace(has_entry=lambda p: p in files, payload=lambda p: files[p])
    name = mesh.submeshes[index].name
    glow = GlowChoice((name,), (1., .2, .1), 6) if feature == "glow" else None
    glass = TranslucencyChoice((name,), .25, .75) if feature == "translucency" else None
    controls = ((name, ShaderControls("SkinnedMeshWing", (("_wingFlowProgress", (.6,)),))),) if feature == "shader_controls" else ()
    if feature == "eye_cover":
        controls = ((name, ShaderControls("SkinnedMeshEyeCover", (("_eyeCoverDiffuseParameter", (.25,)),
                                                                  ("surface_alpha", (.2,))))),)
    stop = threading.Event()
    if surface == "placement":
        token, source = _template_progressive_source(("template", 1), 1, lambda _: mesh, lambda _: mesh,
            False, lambda _: None, glow, glass, controls, snapshot)
        package = build_item_preview_package(source.materials(stop), token=token, output_root=tmp_path / "preview",
                                             stop_event=stop, include_material_resources=True)
    else:
        source = PlannedEffectItemSource(None, ModelPlacement(), False, None, b"", snapshot, None, glow,
                                         translucency=glass, shader_controls=controls)
        preview, _ = source._finish(mesh, "template", stop)
        package = build_effect_placement_package(preview, (-1, -1, -1), (1, 1, 1), output_root=tmp_path / "preview",
                                                 include_body=False, include_item_textures=True).package_dir
    manifest = json.loads((package / "manifest.json").read_text())
    rows = {row["material_index"]: row for row in manifest["material_presentations"] if row["lod_index"] == 0}
    # Effects puts the editable anchor and axis markers before the reference item.
    offset = len(rows) - len(mesh.submeshes) if surface == "effects" else 0
    rows = {i: rows[i + offset] for i in range(len(mesh.submeshes))}
    if feature == "glow":
        assert rows[index]["emissive_intensity"] == 6 and rows[1 - index].get("emissive_intensity") != 6
    elif feature == "translucency":
        assert rows[index][feature] == [.25, .75] and rows[1 - index].get(feature) is None
    elif feature == "eye_cover":
        assert rows[index]["shader_controls"][:6] == [7., 0., 0., 0., 64 / 255, .2]
        assert rows[1 - index].get("shader_controls") is None
    else:
        assert rows[index][feature][4] == .6 and rows[1 - index].get(feature) is None
    assert all(not getattr(p, "preview_native_material_overrides", {}) for p in mesh.submeshes)


@pytest.mark.parametrize("shader", ["SkinnedMeshStandard_Ver2", "SkinnedMeshEmissive_Ver2", "SkinnedMeshCloth_Ver2", "SkinnedMeshFur_Ver2"])
def test_mesh_translucency_prepares_layered_materials_like_new_item(shader):
    from cdmw.services.mesh_translucency import build_translucency_files
    from tests.test_new_item_template_translucency_bake import layered_inputs, PAC, PAC_XML, BLADE
    files = layered_inputs(shader)
    baseline = dict(files)
    mesh = ParsedMesh(path=PAC, format="pac", submeshes=[SubMesh(name=BLADE, material="some_texture")])
    state = SimpleNamespace(target_path=PAC, parts=(SimpleNamespace(target_index=0, translucency=(.2, .3),
        translucency_surface=None, emission=None, shader_controls=None),),
        dependencies=tuple(ReplacementFile(p, data) for p, data in files.items()), companion_files=())
    output = {f.path: f.data for f in build_translucency_files(state, mesh, ())}
    row = find_material_wrappers(output[PAC_XML].decode())[0]
    assert row.shader == "SkinnedMeshTranslucent"
    assert row.textures["_baseColorTexture"] in output
    # Authored emission is still read from its original archive dependency.
    assert row.textures["_emissiveIntensityTexture"] in (files | output)
    assert files == baseline


def test_effects_incompatible_experiment_points_to_recovery():
    from cdmw.ui.new_item.effect_item_source import PlannedEffectItemSource
    from cdmw.ui.new_item.model_import import ModelPlacement
    mesh = parse_pac(named_parts("sharedX"), "character/model/item.pac")
    files = {f.path: f.data for f in dependencies(mesh)}
    snapshot = SimpleNamespace(has_entry=lambda p: p in files, payload=lambda p: files[p])
    source = PlannedEffectItemSource(None, ModelPlacement(), False, None, b"", snapshot, None, None,
        shader_controls=((mesh.submeshes[0].name, ShaderControls("SkinnedMeshTornCloth_Ver2")),))
    with pytest.raises(ValueError, match="Model & Placement > Appearance"):
        source._finish(mesh, "template", threading.Event())


@pytest.mark.parametrize("feature", ["translucency", "emission", "shader_controls"])
def test_legacy_material_binding_requires_all_actual_owners(feature):
    from cdmw.services.mesh_translucency import build_translucency_files
    from cdmw.services.mesh_emission import build_emission_files
    from cdmw.services.mesh_shader_controls import build_shader_control_files
    mesh = parse_pac(named_parts("sharedX"), "character/model/item.pac")
    xml = "character/modelproperty/item.pac_xml"
    files = (ReplacementFile(xml, material(name="sharedX").encode()),)
    values = {"translucency": (.2, .3), "emission": EmissionChoice((1., .2, .1), 6),
              "shader_controls": ShaderControls("SkinnedMeshWing")}
    parts = [SimpleNamespace(target_index=i, translucency=None, translucency_surface=None,
                             emission=None, shader_controls=None) for i in range(2)]
    state = SimpleNamespace(target_path=mesh.path, parts=parts, dependencies=files, companion_files=())
    build = {"translucency": build_translucency_files, "emission": build_emission_files,
             "shader_controls": build_shader_control_files}[feature]
    setattr(parts[0], feature, values[feature])
    with pytest.raises(ValueError, match="sharing this material"):
        build(state, mesh, ())
    setattr(parts[1], feature, values[feature])
    output = {f.path: f.data for f in build(state, mesh, ())}
    row = find_material_wrappers(output[xml].decode())[0]
    assert row.shader == {"translucency": "SkinnedMeshTranslucent", "emission": "SkinnedMeshEmissive",
                          "shader_controls": "SkinnedMeshWing"}[feature]


def test_cancelled_layered_mesh_edit_does_not_read_or_publish_textures(monkeypatch):
    from cdmw.domain.cancellation import RunCancelled
    from cdmw.services.mesh_translucency import build_translucency_files
    from tests.test_new_item_template_translucency_bake import layered_inputs, PAC, BLADE
    files = layered_inputs("SkinnedMeshStandard_Ver2")
    mesh = ParsedMesh(path=PAC, format="pac", submeshes=[SubMesh(name=BLADE, material="some_texture")])
    state = SimpleNamespace(target_path=PAC, parts=(SimpleNamespace(target_index=0, translucency=(.2, .3),
        translucency_surface=None, emission=None, shader_controls=None),),
        dependencies=tuple(ReplacementFile(p, data) for p, data in files.items()), companion_files=())
    monkeypatch.setattr("cdmw.services.new_item_template_materials._bake_material_maps",
                        lambda *_: pytest.fail("cancelled edit began a texture bake"))
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        build_translucency_files(state, mesh, (), stop_event=stop)
    assert state.companion_files == ()


@pytest.mark.parametrize("index", [0, 1])
def test_shader_lod_preview_does_not_fall_back_to_another_parts_wrapper(tmp_path, monkeypatch, index):
    from dataclasses import replace
    from tests import test_mesh_rust_authoring_exact_output as exact
    from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids
    from cdmw.services.mesh_shader_controls_preview import stage_shader_preview
    monkeypatch.setattr(exact, "_pac_fixture", lambda **_: named_parts("target0"))
    monkeypatch.setattr("cdmw.services.shader_controls_preview.gettempdir", lambda: str(tmp_path))
    _, service, session = exact._open_exact_session(tmp_path / "session")
    try:
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        state = initial_replacement_state(snapshot, dependencies=dependencies(snapshot.mesh))
        state = replace(state, parts=tuple(replace(part, shader_controls=ShaderControls("SkinnedMeshWing"))
                        if i == index else part for i, part in enumerate(state.parts)))
        mesh = mesh_with_part_ids(snapshot, state)
        # Exercise the preview mapper's multiple-LOD contract directly; PAC's
        # native editing session displays only the current LOD.
        mesh.lod_levels = [mesh.submeshes, copy.deepcopy(mesh.submeshes)]
        presentations = {}
        stage_shader_preview(session, mesh, state, {"textures": []}, presentations, threading.Event())
        assert set(presentations) == {(0, index), (1, index)}
    finally:
        if not session.closed: session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)
