"""Actual material output, protocol, drafts and viewport factors for animated glow."""
from dataclasses import replace
import copy
from types import SimpleNamespace

import pytest

from cdmw.core.pac_xml_emission import rewrite_emission_animation, ANIMATION_PARAMETERS
from cdmw.core.pac_xml_standard_material import find_material_wrappers, rewrite_emission
from cdmw.domain.mesh.emission import EmissionChoice, GlowAnimation, RgbGlow, authored_glow_animation, authored_rgb_glow_factors
from cdmw.services.mesh_emission import build_emission_files
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from cdmw.services.mesh_replacement_import import initial_replacement_state
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from tests.test_mesh_editor_replacement import editor
from tests.test_mesh_translucency import sidecar
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command


@pytest.mark.parametrize("animation", [GlowAnimation(flow_u=-1), GlowAnimation(flow_v=11),
    GlowAnimation(pulse_frequency=float("nan")), GlowAnimation(pulse_minimum=2), GlowAnimation(flow_u=True)])
def test_animation_rejects_invalid_and_nonfinite_values(animation):
    with pytest.raises(ValueError):
        animation.validate()


def test_only_selected_material_changes_and_zero_stops_authored_animation(editor):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    original = sidecar(snapshot).data.decode()
    wrappers = find_material_wrappers(original)
    name = wrappers[0].submesh_name
    animation = GlowAnimation(.88, .64, 2, .1)
    text = rewrite_emission_animation(original, {name: animation})
    row, untouched = find_material_wrappers(text)
    assert row.textures == wrappers[0].textures
    assert text[untouched.start:untouched.end] == original[wrappers[1].start:wrappers[1].end]
    assert [float(row.value(name)) for name, _ in ANIMATION_PARAMETERS] == list(animation.factors())
    stopped = find_material_wrappers(rewrite_emission_animation(text, {name: GlowAnimation()}))[0]
    assert all(float(stopped.value(name)) == 0 for name, _ in ANIMATION_PARAMETERS)
    exported = SimpleNamespace(preview_sidecar_shader_family=row.shader, preview_material_parameters=[
        SimpleNamespace(parameter_name=name, value=row.value(name), numeric_value=None) for name, _ in ANIMATION_PARAMETERS])
    assert authored_glow_animation(exported) == animation.factors()
    exported.preview_sidecar_shader_family = "SkinnedMeshStandard_Ver2"
    assert authored_glow_animation(exported) is None


def test_incompatible_shader_and_wrinkle_inputs_fail_before_export(editor):
    service, sid = editor
    source = sidecar(service.capture_export_snapshot(sid)).data.decode()
    name = find_material_wrappers(source)[0].submesh_name
    with pytest.raises(ValueError, match="translucency"):
        rewrite_emission_animation(source.replace("SkinnedMeshEmissive", "SkinnedMeshTranslucent"), {name: GlowAnimation(pulse_frequency=1)})
    source = source.replace("SkinnedMeshEmissive", "SkinnedMeshStandard_Ver2").replace("_emissiveIntensity", "_wrinkleBitFlag")
    with pytest.raises(ValueError, match="wrinkle"):
        rewrite_emission_animation(source, {name: GlowAnimation(pulse_frequency=1)})


def test_unticked_part_restores_authored_animation_in_combined_preview(editor):
    from cdmw.services.mesh_rust_authoring import _append_rust_material_presentation
    service, sid = editor
    part = service.capture_export_snapshot(sid).mesh.submeshes[0]
    part.preview_sidecar_shader_family = "SkinnedMeshEmissive"
    part.preview_material_parameters = [SimpleNamespace(
        parameter_name="_emissiveFlowSpeedU", value="0.5", numeric_value=None)]
    part.preview_native_material_overrides = {"emission_animation": None}
    rows = []
    _append_rust_material_presentation(rows, {}, 0, [part], None, 0)
    assert tuple(rows[0]["emission_animation"]) == (.5, 0, 0, 0)
    part.preview_native_material_overrides = {"emission_animation": [0, 0, 0, 0]}
    rows = []
    _append_rust_material_presentation(rows, {}, 0, [part], None, 0)
    assert rows[0]["emission_animation"] == [0, 0, 0, 0]


def test_textureless_shader_with_empty_parameter_vector_accepts_glow():
    import xml.etree.ElementTree as ET
    source = ('<SkinnedMeshMaterialWrapper _subMeshName="Part">'
              '<Material Name="_resourceMaterial" _materialName="SkinnedMeshStandard">'
              '<Vector Name="_permutations"/><Vector Name="_parameters"/></Material></SkinnedMeshMaterialWrapper>')
    text = rewrite_emission_animation(source, {"Part": GlowAnimation(pulse_frequency=1)})
    text = rewrite_emission(text, {"Part": ("texture/glow.dds", "#FFFFFFFF", 4)})
    tree = ET.fromstring(text)
    assert len(tree.find("Material/Vector[@Name='_permutations']")) == 0
    assert len(tree.find("Material/Vector[@Name='_parameters']")) == 7
    assert "emission-parameter-template" not in text


@pytest.mark.parametrize("rgb", [None, RgbGlow(.6, .4, .05, True)])
def test_glow_draft_round_trip_and_shared_part_rejection(editor, tmp_path, rgb):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    source = sidecar(snapshot)
    state = initial_replacement_state(snapshot, dependencies=(source,))
    glow = EmissionChoice((1, .2, .3), 3, GlowAnimation(.5, 0, 2, .2), rgb)
    state = replace(state, parts=(replace(state.parts[0], emission=glow), state.parts[1]))
    directory = tmp_path / "generation"
    directory.mkdir()
    payload = save_replacement_state(state, tmp_path, directory)
    assert payload["version"] == 11 and load_replacement_state(payload, tmp_path) == state
    with pytest.raises(ValueError, match="version 11"):
        load_replacement_state({**payload, "version": 10}, tmp_path)
    output = build_emission_files(state, snapshot.mesh, ())
    assert find_material_wrappers(output[0].data.decode())[0].value("_emissiveFlowSpeedU") == "0.500000"
    restored = replace(state, parts=tuple(replace(p, emission=None) for p in state.parts))
    assert build_emission_files(restored, snapshot.mesh, ()) == ()
    shared = copy.deepcopy(snapshot.mesh)
    shared.submeshes[1].name = shared.submeshes[0].name
    shared.submeshes[1].material = shared.submeshes[0].material
    with pytest.raises(ValueError, match="sharing"):
        build_emission_files(state, shared, ())


def test_mesh_command_reuses_textures_and_round_trips_history_finish(tmp_path, monkeypatch):
    original, service, session = _open_exact_session(tmp_path / "session")
    try:
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        source = sidecar(snapshot)
        monkeypatch.setattr("cdmw.services.mesh_replacement_materials.capture_replacement_dependencies", lambda *args: (source,))
        monkeypatch.setattr("cdmw.services.mesh_rust_authoring._mesh_texture_payloads",
                            lambda *a, **kw: pytest.fail("glow must reuse texture resources"))
        base = copy.deepcopy(session.archive_refit_material_cache["base"])
        key = session.state_payload()["emission"]["parts"][0]["id"]
        glow = EmissionChoice((.25, .5, 1), 6, GlowAnimation(.5, .25, 2, .2))
        changed = command(session, "replacement_emission", {"part_ids": [key], "emission": glow.to_dict()})
        cache_key = changed["state"]["archive_refit_materials"]["key"]
        prepared = session.archive_refit_material_cache[cache_key]
        assert prepared["textures"] == base["textures"]
        assert prepared["material_presentations"][0]["emission_animation"] == list(glow.animation.factors())
        assert prepared["material_presentations"][0]["emissive_intensity"] == 6
        command(session, "undo")
        assert session.state_payload()["emission"]["parts"][0]["emission"] is None
        command(session, "redo")
        assert session.state_payload()["emission"]["parts"][0]["emission"] == glow.to_dict()
        with pytest.raises(ValueError, match="translucency"):
            command(session, "replacement_translucency", {"part_ids": [key], "translucency": [.1, .3]})
        session.finish(_request(session, "finish_request", 22))
        result = prepare_replacement_output(service.capture_export_snapshot(session.authoritative_session_id))
        assert result.data == original
        row = find_material_wrappers(next(f.data.decode() for f in result.companion_files if f.path.endswith("_xml")))[0]
        assert row.value("_emissiveFlickeringFreq") == "2.000000"
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def test_rgb_recipe_round_trips_reveal_and_resets_progress(editor):
    from cdmw.core.pac_xml_emission import rewrite_rgb_emission
    from cdmw.domain.model_preview_materials import PreviewMaterialTextureInput, PreviewMaterialParameterInput
    service, sid = editor
    source = sidecar(service.capture_export_snapshot(sid)).data.decode()
    name = find_material_wrappers(source)[0].submesh_name
    rgb = RgbGlow(.75, .5, .1, True)
    edited = rewrite_rgb_emission(source, {name: (rgb, "#FF8040FF")})
    row = find_material_wrappers(edited)[0]
    assert row.textures["_emissiveProgressTexture"] == row.textures["_emissiveProgressMaskTexture"] == "texture/glow.dds"
    assert row.value("_emissiveIntensity") == "0.000000"
    params = tuple(PreviewMaterialParameterInput(parameter_name=p.name, value=p.value) for p in row.parameters if p.kind != "Texture")
    part = SimpleNamespace(preview_sidecar_shader_family=row.shader, preview_material_texture_inputs=tuple(
        PreviewMaterialTextureInput(parameter_name=key, source_texture_path=value, material_parameters=params)
        for key, value in row.textures.items()))
    factors = authored_rgb_glow_factors(part)
    assert factors["emission_reveal"] == rgb.factors()
    assert factors["emissive_color"] == (1, 128 / 255, 64 / 255)
    mono = rewrite_emission(edited, {name: ("texture/glow.dds", "#FFFFFFFF", 5)})
    mono = rewrite_rgb_emission(mono, {name: (None, "#FFFFFFFF")})
    assert find_material_wrappers(mono)[0].value("_emissiveProgressGauge") == "0.000000"


def test_new_item_rgb_output_keeps_dds_bytes_and_surface(tmp_path):
    from PIL import Image
    from cdmw.domain.new_item.spec import GlowChoice
    from cdmw.services.new_item_materials import SourceMaterialTextures, route_plain_pbr
    from tests.test_new_item_materials import builder_files, XML, dds
    image = Image.new("RGBA", (4, 4), (220, 40, 80, 127))
    image.putpixel((1, 0), (40, 180, 70, 255))
    path = tmp_path / "coloured_glow.dds"
    image.save(path)
    files = builder_files()
    name = "cd_phm_02_sword_handle_0003"
    route = route_plain_pbr(files, sources={name: SourceMaterialTextures(name="Inside", emissive=path)},
        glow=GlowChoice(("Inside",), (1, 1, 1), 4, GlowAnimation(.5, 0, 2, .1), RgbGlow(.75, .5, .1)),
        encode_factors=lambda *_: dds(), encode_emissive=lambda *_: pytest.fail("RGB must not be greyscaled"))
    row = next(row for row in find_material_wrappers(route.files.side_files[XML].decode()) if row.submesh_name == name)
    assert route.files.side_files[row.textures["_emissiveProgressTexture"]] == path.read_bytes()
    assert row.value("_emissiveProgressGauge") == "0.500000"
    assert row.value("_emissiveFlowSpeedU") == "0.500000"
    assert "_glow_" not in row.textures["_baseColorTexture"]


def test_template_rgb_plan_and_preview_keep_the_same_selected_settings(editor):
    from cdmw.domain.new_item.spec import GlowChoice
    from cdmw.services.new_item_template_model import prepare_template_model
    from cdmw.services.new_item_materials import glow_preview_mesh
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    source = sidecar(snapshot)
    path = snapshot.mesh.path
    rows = find_material_wrappers(source.data.decode())
    glow = GlowChoice((rows[0].submesh_name,), (.5, 1, .25), 4, GlowAnimation(.5, .25, 2, .1), RgbGlow(.5, .8, .2))
    payloads = {path: snapshot.original_data, source.path: source.data}
    store = SimpleNamespace(payload=payloads.__getitem__, has_entry=payloads.__contains__)
    output = prepare_template_model(store, (path,), glow=glow)
    assert output.pac_data == snapshot.original_data
    after = find_material_wrappers(output.side_files[source.path].decode())
    assert after[0].value("_emissiveProgressGauge") == "0.800000"
    assert after[1].parameters == rows[1].parameters
    preview = glow_preview_mesh(snapshot.mesh, glow)
    assert preview.submeshes[0].preview_native_material_overrides["emission_reveal"] == list(glow.rgb.factors())
    assert preview.submeshes[0].preview_native_material_overrides["emission_animation"] == list(glow.animation.factors())
    assert "emission_reveal" not in getattr(snapshot.mesh.submeshes[0], "preview_native_material_overrides", {})


def test_qt_animation_editor_and_variant_capture_preserve_choices(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.new_item.glow_animation_editor import GlowAnimationEditor
    from cdmw.ui.new_item.state import NewItemDraft, glow_choice
    from cdmw.ui.new_item.controller_variant_mixin import NewItemVariantControllerMixin
    from cdmw.ui.new_item.model_import import ModelPlacement
    app = QApplication.instance() or QApplication([])
    widget = GlowAnimationEditor()
    rgb, animation = RgbGlow(.7, .8, .2, True), GlowAnimation(.5, .25, 2, .1)
    signals = []
    widget.changed.connect(lambda: signals.append(1))
    widget.refresh(animation, rgb)
    assert not signals and widget.value() == animation and widget.rgb_value() == rgb
    widget.spins["pulse_frequency"].setValue(3)
    assert signals and widget.value().pulse_frequency == 3
    draft = NewItemDraft(glow_parts=("Blade",), glow_animation=animation, glow_rgb=rgb)
    controller = SimpleNamespace(draft=draft, _variant_states={}, model_import=None, model_result=None,
        model_entry=None, model_scene=None, model_placement=ModelPlacement())
    key = ("prefab", "model")
    NewItemVariantControllerMixin._capture_variant(controller, key)
    saved = controller._variant_states[key].appearance.glow_choice()
    assert saved == glow_choice(draft)
    widget.close()


@pytest.mark.parametrize("rgb", [RgbGlow(softness=0), RgbGlow(reveal=2), RgbGlow(intensity=float("inf")), RgbGlow(inverse=1)])
def test_rgb_controls_reject_undefined_math_and_invalid_values(rgb):
    with pytest.raises(ValueError):
        rgb.validate()


def test_child_material_animation_cannot_be_silently_lost_in_atlas():
    from cdmw.domain.new_item.spec import GlowChoice
    from cdmw.services.new_item_materials import SourceMaterialTextures, route_plain_pbr
    from tests.test_new_item_materials import builder_files
    name = "cd_phm_02_sword_handle_0003"
    source = SourceMaterialTextures(name="atlas", atlas_section=SimpleNamespace(target_submesh_name=name),
                                   atlas_sources=(SourceMaterialTextures(name="Inside"),))
    with pytest.raises(ValueError, match="split this atlas"):
        route_plain_pbr(builder_files(), sources={name: source},
            glow=GlowChoice(("Inside",), animation=GlowAnimation(pulse_frequency=1)))


@pytest.mark.parametrize("glow", [EmissionChoice(animation=GlowAnimation(flow_u=1)), EmissionChoice(rgb=RgbGlow())])
def test_builder_route_cannot_silently_drop_glow_controls(glow):
    from cdmw.domain.new_item.spec import MaterialRoute
    from cdmw.services.new_item_materials import route_model_files
    from tests.test_new_item_materials import builder_files
    with pytest.raises(ValueError, match="Plain PBR"):
        route_model_files(builder_files(), MaterialRoute.BUILDER, glow=glow)
