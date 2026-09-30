"""Output and preview contracts for the decoded material-family experiments."""
from dataclasses import replace
from types import SimpleNamespace
import threading
import xml.etree.ElementTree as ET

import pytest

from cdmw.core.material_shader_controls import rewrite_shader_controls, control_material_sources
from cdmw.core.pac_xml_standard_material import find_material_wrappers, plain_material_xml, PlainMaterial
from cdmw.domain.mesh.shader_controls import FAMILIES, ShaderControls, family_for, preview_factors, validate_choices
from cdmw.services.mesh_shader_controls import build_shader_control_files
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids, commit_replacement
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from tests.test_mesh_editor_replacement import editor
from tests.test_mesh_translucency import sidecar


@pytest.mark.parametrize("packed", [0, 64, 127, 128, 191, 255])
@pytest.mark.parametrize("pixel", [0, 64, 128, 255])
def test_raw_eye_cover_mask_keeps_unclamped_legacy_channel_math(packed, pixel):
    from cdmw.domain.mesh.shader_controls import EYE_COVER, eye_cover_colour_range
    from cdmw.domain.textures.transparency_mask import TransparencyMask
    mask = TransparencyMask(1, 1, bytes([pixel]))
    controls = ShaderControls(EYE_COVER.shader, (("_eyeCoverDiffuseParameter", (packed / 255,)),), mask)
    assert ShaderControls.from_dict(controls.to_dict()) == controls
    assert "coverage_mapping" not in controls.to_dict()
    assert controls.colour_mask_for_output() == mask
    low, high = eye_cover_colour_range(controls)
    assert low == high == pytest.approx((2 * packed - pixel) / 255)


@pytest.mark.parametrize("coverage", [0., 64 / 255, 128 / 255, 254 / 255])
def test_calibrated_eye_cover_mask_is_explicit_bounded_and_reversible(coverage):
    from dataclasses import replace
    from cdmw.domain.mesh.shader_controls import EYE_COVER
    from cdmw.domain.textures.transparency_mask import TransparencyMask
    mask = TransparencyMask(4, 1, bytes([0, 64, 128, 255]))
    raw = ShaderControls(EYE_COVER.shader, (("_eyeCoverDiffuseParameter", (0.,)), ("material_red", (0.,))), mask)
    calibrated = replace(raw, coverage_mapping="calibrated_v1", colour_coverage=coverage, surface_response_mask=mask)
    assert ShaderControls.from_dict(calibrated.to_dict()) == calibrated
    assert calibrated.values == raw.values  # Explicit zero is not an absent setting.
    assert preview_factors(calibrated)[4:7] == (127 / 255, -1., -1.)
    result = calibrated.colour_mask_for_output().pixels
    for fade, red in zip(mask.pixels, result):
        assert 0 <= (254 - red) / 255 <= 254 / 255
        assert abs((254 - red) / 255 - coverage * (1 - fade / 255)) <= .5 / 255
    assert replace(calibrated, coverage_mapping="raw", colour_coverage=None).colour_mask_for_output() == mask
    assert raw.transparency_mask == mask


@pytest.mark.parametrize("extra", [
    {"coverage_mapping": "future_v2"}, {"coverage_mapping": "calibrated_v1"},
    {"colour_coverage": 0.}, {"coverage_mapping": "calibrated_v1", "colour_coverage": 1.},
    {"coverage_mapping": "calibrated_v1", "colour_coverage": True},
    {"surface_response_mask": None}, {"cutout_mask": {}}, {"surface_mask": {}},
])
def test_unknown_or_malformed_mask_state_is_never_silently_dropped(extra):
    with pytest.raises(ValueError):
        ShaderControls.from_dict({"shader": "SkinnedMeshEyeCover", "values": {}, **extra})


def material(shader="SkinnedMeshStandard", extra="", name="Blade"):
    block = plain_material_xml(PlainMaterial(base="texture/base.dds", normal="texture/normal.dds"))
    block = block.replace('SkinnedMeshStandard"', shader + '"')
    block = block.replace('</Vector>', extra + '</Vector>', 1)
    return f'<SkinnedMeshMaterialWrapper _subMeshName="{name}">{block}</SkinnedMeshMaterialWrapper>'


def field(name, value, kind="Float"):
    return f'<MaterialParameter{kind} StringItemID="{name}" ItemID="123" _name="{name}" _value="{value}" Index="50"/>'


def choice(shader="SkinnedMeshWing", **values):
    return ShaderControls(shader, tuple((name, (value,) if isinstance(value, (int, float)) else value) for name, value in values.items()))


@pytest.mark.parametrize("shader,extra,supported", [
    ("SkinnedMeshStandard", "", ("SkinnedMeshWing", "SkinnedMeshEyeCover")),
    ("SkinnedMeshEmissive", "", ("SkinnedMeshWing", "SkinnedMeshEyeCover")),
    ("SkinnedMeshStandard", field("_overlayWeight", "1"), ()),
    ("SkinnedMeshStandard_Ver2", "", ()),
    ("SkinnedMeshHair", "", ()),
    ("SkinnedMeshTranslucent", "", ("SkinnedMeshEyeCover",)),
    *[(family.shader, "", (family.shader,)) for family in FAMILIES if family.shader != "Dissolve"],
])
def test_equipment_shader_options_follow_output_compatibility(shader, extra, supported):
    from cdmw.core.material_shader_controls import equipment_shader_options
    text = material(shader, extra)
    assert equipment_shader_options(text) == {"blade": (shader, supported)}
    for family in FAMILIES:
        if family.shader in supported:
            rewrite_shader_controls(text, (("Blade", choice(family.shader)),))
        else:
            with pytest.raises(ValueError):
                rewrite_shader_controls(text, (("Blade", choice(family.shader)),))


def test_equipment_shader_options_disable_ambiguous_materials():
    from cdmw.core.material_shader_controls import equipment_shader_options
    for text in (material() * 2, material(extra=field("_normalScale", "1") * 2)):
        assert equipment_shader_options(text)["blade"][1] == ()


def test_wing_conversion_preserves_unselected_and_authored_maps():
    before = material() + material(name="Handle")
    controls = choice(_wingFlowProgress=.4, _wingFlowInverse=1)
    after, found = rewrite_shader_controls(before, (("Blade", controls),))
    old, new = find_material_wrappers(before), find_material_wrappers(after)
    assert found == {"blade"}
    assert new[0].shader == "SkinnedMeshWing"
    assert new[0].value("_wingFlowProgress") == "0.4"
    assert new[0].textures["_baseColorTexture"] == old[0].textures["_baseColorTexture"]
    assert new[0].textures["_normalTexture"] == old[0].textures["_normalTexture"]
    assert new[0].textures["_wingFlowTex1"] == FAMILIES[0].default_mask
    assert after[new[1].start:new[1].end] == before[old[1].start:old[1].end]
    assert rewrite_shader_controls(after, (("Blade", controls),))[0] == after


@pytest.mark.parametrize("family", FAMILIES[:-1])
def test_each_character_family_writes_only_explicit_typed_controls(family):
    setting = family.fields[0]
    values = ((setting.name, (setting.maximum,)),)
    source = material(family.shader, field("_unrelated", "123"))
    after, _ = rewrite_shader_controls(source, (("Blade", ShaderControls(family.shader, values)),))
    _, fields, _ = control_material_sources(after)["blade"]
    assert float(fields[setting.name]) == setting.maximum
    assert fields["_unrelated"] == "123"
    assert not ({p.name for p in family.fields[1:]} & fields.keys())


@pytest.mark.parametrize("controls", [
    choice(_wingFlowProgress=float("nan")), choice(_wingFlowProgress=True), choice(_wingFlowInverse=.5),
    choice("Dissolve", _dissolveHardness=0), choice("Dissolve", _dissolvePositionType=1.5),
    choice("SkinnedMeshHairAnimatedUV", _frequencyU=float("inf")),
    choice("SkinnedMeshPoster", _wingFlowProgress=1),
    ShaderControls("Water"), ShaderControls("SkinnedMeshWing", (("_wingFlowProgress", (1.,)), ("_wingFlowProgress", (2.,)))),
])
def test_invalid_controls_are_rejected(controls):
    with pytest.raises(ValueError):
        controls.validate()


def test_shader_family_boundaries_and_glass_glow_conflicts():
    for shader in ("SkinnedMeshStandard_Ver2", "SkinnedMeshTranslucent", "SkinnedMeshHair"):
        with pytest.raises(ValueError, match="requires"):
            rewrite_shader_controls(material(shader), (("Blade", choice()),))
    with pytest.raises(ValueError, match="different vertex pipelines"):
        rewrite_shader_controls(material("Dissolve"), (("Blade", choice("Dissolve")),))
    for kwargs in ({"glow_parts": ("blade",)}, {"translucent_parts": ("BLADE",)}):
        with pytest.raises(ValueError, match="restore Glow"):
            validate_choices((("Blade", choice()),), **kwargs)
    with pytest.raises(ValueError, match="static object"):
        validate_choices((("Blade", choice("Dissolve")),), equipment=True)


def test_roughness_byte_preserves_other_channels_and_requires_authored_dye():
    original = material("SkinnedMeshAnisotropy", field("_hairDyeingProperty", str(0x12345680), "Byte4")
                        + field("_hairDyeingColor", "#123456FF", "Color"))
    controls = choice("SkinnedMeshAnisotropy", _hairDyeingProperty=200)
    edited, _ = rewrite_shader_controls(original, (("Blade", controls),))
    values = control_material_sources(edited)["blade"][1]
    assert int(values["_hairDyeingProperty"]) == 0x123456C8
    assert values["_hairDyeingColor"] == "#123456FF"
    with pytest.raises(ValueError, match="alpha is zero"):
        rewrite_shader_controls(original.replace("#123456FF", "#12345600"), (("Blade", controls),))


def test_static_dissolve_preserves_other_flags_and_serializes_vector_types():
    source = ('<Material PrimitiveName="Rock"><Common MaterialName="Dissolve"/><Parameters>'
              '<MaterialParameterBitFlag32 Name="_materialFlags" Value="8"/>'
              '<MaterialParameterTexture Name="_baseColorTexture" Value="rock.dds"/>'
              '</Parameters></Material>')
    controls = choice("Dissolve", _dissolveHardness=.2, _dissolvePositionType=2,
                      _dissolvePosition=(1., -2., 3.), _dissolveNoiseSpeed=(.1, -.2), _materialFlags=1)
    edited, _ = rewrite_shader_controls(source, (("Rock", controls),), static=True)
    root = ET.fromstring(edited)
    assert root.find('.//MaterialParameterBitFlag32').get("Value") == "9"
    assert root.find('.//MaterialParameterFloat3').get("Value") == "1 -2 3"
    assert root.find('.//MaterialParameterFloat2').get("Value") == "0.1 -0.2"
    assert root.find('.//MaterialParameterFloat[@Name="_dissolvePositionType"]').get("Value") == "2"
    assert root.find('.//MaterialParameterTexture[@Name="_baseColorTexture"]').get("Value") == "rock.dds"


def test_mesh_output_history_and_versioned_draft(editor, tmp_path):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    state = initial_replacement_state(snapshot, dependencies=(sidecar(snapshot),))
    controls = choice(_wingFlowProgress=.5)
    state = replace(state, parts=(replace(state.parts[0], shader_controls=controls), *state.parts[1:]))
    commit_replacement(service, snapshot, mesh_with_part_ids(snapshot, state), state, label="Shader controls")
    edited = service.capture_export_snapshot(sid)
    result = prepare_replacement_output(edited)
    assert result.data == snapshot.original_data
    assert find_material_wrappers(result.companion_files[0].data.decode())[0].shader == "SkinnedMeshWing"
    generation = tmp_path / "generation"
    generation.mkdir()
    payload = save_replacement_state(state, tmp_path, generation)
    assert payload["version"] == 12
    restored = load_replacement_state(payload, tmp_path)
    assert restored == state
    assert prepare_replacement_output(replace(edited, replacement_state=restored)).companion_files == result.companion_files
    assert ShaderControls.from_dict(controls.to_dict()) == controls
    payload["version"] = 11
    with pytest.raises(ValueError, match="version 12"):
        load_replacement_state(payload, tmp_path)
    service.undo(sid)
    assert service.capture_export_snapshot(sid).replacement_state is None


def test_new_item_template_and_variant_controls_keep_source(editor):
    from cdmw.services.new_item_template_model import prepare_template_model
    from cdmw.domain.new_item.authoring import VariantAppearance
    from cdmw.domain.new_item.spec import NewItemSpec
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    xml = sidecar(snapshot)
    path = snapshot.mesh.path
    data = {path: snapshot.original_data, xml.path: xml.data}
    source = SimpleNamespace(payload=lambda p: data[p], has_entry=lambda p: p in data)
    name = snapshot.mesh.submeshes[0].material or snapshot.mesh.submeshes[0].name
    controls = ((name, choice(_wingFlowProgress=.75)),)
    result = prepare_template_model(source, [path], shader_controls=controls)
    assert result.pac_data == snapshot.original_data
    assert find_material_wrappers(result.side_files[xml.path].decode())[0].value("_wingFlowProgress") == "0.75"
    assert data[xml.path] == xml.data
    spec = NewItemSpec(1, "test_shader", shader_controls=controls)
    assert spec.needs_own_family
    assert VariantAppearance("prefab", path, shader_controls=controls).shader_controls == controls


def test_preview_packet_uses_source_defaults_without_enabling_dye():
    family = FAMILIES[3]
    values = preview_factors(ShaderControls(family.shader), {"_hairDyeingProperty": str(0x123456AB), "_hairDyeingColor": "#AABBCC00"})
    assert len(values) == 32
    assert values[0] == 4 and values[1] == 0
    assert values[4:7] == (0, .5, 171)
    assert preview_factors(choice("Dissolve"))[7] == 0  # source default is player-relative
    flags = preview_factors(choice("Dissolve"), {"_materialFlags": str(0x80000001)})
    assert flags[2] == 1 and max(flags) <= 255  # packed flags must not become GPU scalar magnitudes


def test_vertex_mask_mapping_refuses_ambiguous_seams_and_cancellation():
    from cdmw.services.shader_controls_preview import attach_source_masks, shader_preview_mesh
    from cdmw.domain.cancellation import RunCancelled
    source = SimpleNamespace(vertices=[(0., 0., 0.)]*2, uvs=[(0., 0.)]*2,
                             shader_masks=[(.2, .3, 1.), (.2, .4, 1.)])
    target = SimpleNamespace(vertices=[(0., 0., 0.)], uvs=[(0., 0.)])
    attach_source_masks(target, source)
    assert target.shader_masks == [(1., 1., 0.)]
    source.shader_masks[1] = source.shader_masks[0]
    attach_source_masks(target, source)
    assert target.shader_masks == [(.2, .3, 1.)]
    event = threading.Event()
    event.set()
    with pytest.raises(RunCancelled):
        shader_preview_mesh(SimpleNamespace(submeshes=[target]), (("Blade", choice()),), stop_event=event)


def test_real_qt_editor_emits_only_enabled_fields_and_restores():
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.new_item.shader_controls_editor import ShaderControlsEditor
    app = QApplication.instance() or QApplication([])
    widget = ShaderControlsEditor()
    changes = []
    widget.changed.connect(changes.append)
    widget.refresh((("Blade", "Blade"), ("Guard", "Guard")), ())
    widget.family.setCurrentIndex(1)
    assert changes[-1][0][1].shader == "SkinnedMeshWing"
    assert dict(changes[-1][0][1].values) == {"_wingFlowProgress": (2.,)}
    field_, enabled, spins = widget._rows[1]
    enabled.setChecked(True)
    spins[0].setValue(1)
    assert dict(changes[-1][0][1].values)[field_.name] == (1.,)
    widget.part.setCurrentIndex(1)
    assert widget.family.currentIndex() == 0
    widget.part.setCurrentIndex(0)
    widget.reset.click()
    assert changes[-1] == ()
    widget.close()
    app.processEvents()


def test_template_and_import_shader_options_follow_the_output_route(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.shader_controls_editor import ShaderControlsEditor
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    widget = ShaderControlsEditor()
    changes = []
    widget.changed.connect(changes.append)
    controller._template_shader_options = {
        "plain.pac": {"blade": ("SkinnedMeshStandard", ("SkinnedMeshWing",))},
        "cloth.pac": {"blade": ("SkinnedMeshTornCloth_Ver2", ("SkinnedMeshTornCloth_Ver2",))},
    }
    selected = ["PLAIN.PAC"]
    monkeypatch.setattr(controller, "current_variant_identity", lambda: ("prefab", selected[0]))
    try:
        for path, shader in (("PLAIN.PAC", "SkinnedMeshWing"), ("cloth.pac", "SkinnedMeshTornCloth_Ver2")):
            selected[0] = path
            widget.refresh((("Blade", "Blade"),), (), controller.material_shader_options())
            available = [widget.family.itemData(i) for i in range(1, widget.family.count())
                         if widget.family.model().item(i).isEnabled()]
            assert available == [shader]
            assert family_for(shader).label in widget.family.toolTip()
            for index in range(1, widget.family.count()):
                item = widget.family.model().item(index)
                if not item.isEnabled():
                    assert "Unavailable" in item.text()
                    assert "Requires" in item.toolTip()
                    assert "This part uses" in item.toolTip()
            assert not changes
            widget.family.setCurrentIndex(widget.family.findData(shader))
            assert changes.pop()[0][1].shader == shader
        controller.model_import = object()
        monkeypatch.setattr(controller, "material_parts", lambda: (("Imported", "Imported"),))
        widget.refresh((("Imported", "Imported"),), (), controller.material_shader_options())
        assert [widget.family.itemData(i) for i in range(1, widget.family.count())
                if widget.family.model().item(i).isEnabled()] == ["SkinnedMeshWing", "SkinnedMeshEyeCover"]
        widget.family.setCurrentIndex(widget.family.findData("SkinnedMeshTornCloth_Ver2"))
        assert not changes
        part = SimpleNamespace(name="Imported", material="Imported", preview_material_parameters=(
            SimpleNamespace(parameter_name="_transmissionFactor", value="0.7"),))
        controller.model_import = SimpleNamespace(scene=SimpleNamespace(mesh=SimpleNamespace(submeshes=[part])))
        assert controller.material_shader_options()["imported"] == ("SkinnedMeshStandard", ("SkinnedMeshWing", "SkinnedMeshEyeCover"))
        from cdmw.domain.new_item.translucency import TranslucencyChoice
        controller.draft.translucency = TranslucencyChoice(("Imported",))
        assert controller.material_shader_options()["imported"] == ("SkinnedMeshTranslucent", ("SkinnedMeshEyeCover",))
        from cdmw.domain.new_item.spec import MaterialRoute
        controller.draft.material_route = MaterialRoute.BUILDER
        widget.refresh((("Imported", "Imported"),), (), controller.material_shader_options())
        assert all(not widget.family.model().item(i).isEnabled() for i in range(1, widget.family.count()))
    finally:
        controller.model_import = None
        controller.shutdown()
        widget.close()
        app.processEvents()


@pytest.mark.parametrize("progress", [None, .25])
def test_import_wing_inherited_progress_matches_live_prepared_and_export(progress):
    from PySide6.QtWidgets import QApplication
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services.shader_controls_preview import shader_preview_groups, shader_preview_mesh
    from cdmw.ui.new_item.shader_controls_editor import ShaderControlsEditor
    app = QApplication.instance() or QApplication([])
    widget = ShaderControlsEditor()
    try:
        widget.refresh((("Blade", "Blade"),), (), {"blade": ("SkinnedMeshStandard", ("SkinnedMeshWing",))})
        widget.family.setCurrentIndex(widget.family.findData("SkinnedMeshWing"))
        field, enabled, spins = widget._rows[0]
        assert field.name == "_wingFlowProgress"
        if progress is None:
            enabled.setChecked(False)
        else:
            spins[0].setValue(progress)
        controls = widget._choices["Blade"]
        part = SubMesh(name="Blade", material="Blade")
        part.preview_material_texture_inputs = (SimpleNamespace(parameter_name="_wingFlowTex1",
            source_texture_path="mask.dds", preview_texture_path="owned-mask.dds"),)
        mesh = ParsedMesh(path="imported.obj", submeshes=[part])
        settings = (("Blade", controls),)
        output, _ = rewrite_shader_controls(material(), settings)
        expected = float(find_material_wrappers(output)[0].value("_wingFlowProgress"))
        assert shader_preview_groups(mesh, settings, plain_pbr=True)[0]["shader_controls"][4] == expected
        prepared = shader_preview_mesh(mesh, settings, plain_pbr=True)
        assert prepared.submeshes[0].preview_native_material_overrides["shader_controls"][4] == expected
        from cdmw.ui.new_item.effect_item_source import PlannedEffectItemSource
        from cdmw.ui.new_item.model_import import ModelPlacement
        effects = PlannedEffectItemSource(object(), ModelPlacement(), False, None, b"", None, None, None,
                                          shader_controls=settings)
        effect_mesh, _ = effects._finish(mesh, "placed", threading.Event())
        assert effect_mesh.submeshes[0].preview_native_material_overrides["shader_controls"][4] == expected
        # Authored Wing materials still inherit their own value in other callers.
        part.preview_material_parameters = (SimpleNamespace(parameter_name="_wingFlowProgress", value="0.8"),)
        assert shader_preview_groups(mesh, (("Blade", choice()),))[0]["shader_controls"][4] == .8
    finally:
        widget.close()
        app.processEvents()


def test_import_bindings_map_renamed_parts_and_clones_without_touching_other_materials():
    from cdmw.services.new_item_shader_controls import apply_shader_controls
    from cdmw.services.new_item_planning import ModelFiles
    result = SimpleNamespace(source_owned_output_draw_sections=(
        SimpleNamespace(target_submesh_name="game_blade", source_material_name="Imported Blade"),))
    scene = SimpleNamespace(material_bindings=(SimpleNamespace(material_name="Imported Blade", texture_slots=()),))
    source = material(name="game_blade") + material(name="clone") + material(name="guard").replace("texture/base.dds", "guard.dds")
    source += material(name="GAME_BLADE")
    files = ModelFiles(b"geometry", {"blade.pac_xml": b"\xef\xbb\xbf" + source.encode(), "texture/base.dds": b"owned texture"})
    output = apply_shader_controls(files, (("Imported Blade", choice(_wingFlowProgress=.7)),), result=result, scene=scene)
    rows = find_material_wrappers(output.side_files["blade.pac_xml"].decode("utf-8-sig"))
    assert [row.shader for row in rows] == ["SkinnedMeshWing", "SkinnedMeshWing", "SkinnedMeshStandard", "SkinnedMeshWing"]
    assert output.side_files["blade.pac_xml"].startswith(b"\xef\xbb\xbf")
    assert output.pac_data == files.pac_data
    assert files.side_files["blade.pac_xml"] == b"\xef\xbb\xbf" + source.encode()


def test_import_atlas_requires_all_members_and_identical_settings():
    from cdmw.services.new_item_shader_controls import apply_shader_controls
    from cdmw.services.new_item_planning import ModelFiles
    result = SimpleNamespace(source_owned_output_draw_sections=(SimpleNamespace(target_submesh_name="Atlas",
        source_material_name="", atlas_material_name="Merged", atlas_rects=(
            SimpleNamespace(source_material_name="Blade"), SimpleNamespace(source_material_name="Guard"))),))
    scene = SimpleNamespace(material_bindings=tuple(SimpleNamespace(material_name=name, texture_slots=()) for name in ("Blade", "Guard")))
    files = ModelFiles(b"geometry", {"blade.pac_xml": material(name="Atlas").encode()})
    with pytest.raises(ValueError, match="whole atlas"):
        apply_shader_controls(files, (("Blade", choice()),), result=result, scene=scene)
    with pytest.raises(ValueError, match="same shader controls"):
        apply_shader_controls(files, (("Blade", choice()), ("Guard", choice(_wingFlowProgress=.1))), result=result, scene=scene)
    output = apply_shader_controls(files, (("Blade", choice()), ("Guard", choice())), result=result, scene=scene)
    assert find_material_wrappers(output.side_files["blade.pac_xml"].decode())[0].shader == "SkinnedMeshWing"


def test_repeated_clone_names_cannot_edit_an_unselected_source_owner():
    from cdmw.services.new_item_shader_controls import apply_shader_controls
    from cdmw.services.new_item_planning import ModelFiles

    result = SimpleNamespace(source_owned_output_draw_sections=tuple(
        SimpleNamespace(target_submesh_name="game_" + name, source_material_name=name) for name in ("Skull", "Handle")))
    scene = SimpleNamespace(material_bindings=tuple(
        SimpleNamespace(material_name=name, texture_slots=()) for name in ("Skull", "Handle")))
    text = "".join(material(name=target).replace("texture/base.dds", f"texture/{name}.dds")
                   for name in ("Skull", "Handle") for target in ("game_" + name, "clone"))
    files = ModelFiles(b"geometry", {"weapon.pac_xml": text.encode(),
                                   "texture/Skull.dds": b"skull", "texture/Handle.dds": b"handle"})
    with pytest.raises(ValueError, match="must all use the same shader controls"):
        apply_shader_controls(files, (("Skull", choice()),), result=result, scene=scene)
    with pytest.raises(ValueError, match="same shader controls"):
        apply_shader_controls(files, (("Skull", choice()), ("Handle", choice(_wingFlowProgress=.1))),
                              result=result, scene=scene)
    output = apply_shader_controls(files, (("Skull", choice()), ("Handle", choice())), result=result, scene=scene)
    assert all(row.shader == "SkinnedMeshWing" for row in find_material_wrappers(output.side_files["weapon.pac_xml"].decode()))


def test_mesh_command_caches_masks_reuses_base_maps_and_restores_on_undo(tmp_path, monkeypatch):
    import copy
    from cdmw.domain.mesh.replacement import ReplacementFile
    from tests.test_new_item_materials import dds
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
    from tests.test_mesh_rust_replacement import command
    _, service, session = _open_exact_session(tmp_path / "session")
    monkeypatch.setenv("CDMW_TEMP_CACHE_ROOT", str(tmp_path / "cache"))
    try:
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        mask = ReplacementFile(FAMILIES[0].default_mask, dds())
        monkeypatch.setattr("cdmw.services.mesh_replacement_materials.capture_replacement_dependencies", lambda *args: (sidecar(snapshot), mask))
        monkeypatch.setattr("cdmw.services.mesh_rust_authoring._mesh_texture_payloads", lambda *args, **kw: pytest.fail("base maps decoded again"))
        base = copy.deepcopy(session.archive_refit_material_cache["base"])
        key = session.state_payload()["shader_controls"]["parts"][0]["id"]
        def apply(progress):
            return command(session, "replacement_shader_controls", {"part_ids": [key], "shader_controls": choice(_wingFlowProgress=progress).to_dict()})
        edited = apply(.2)
        first = session.archive_refit_material_cache[edited["state"]["archive_refit_materials"]["key"]]
        assert any(row["role"] == "shader_mask" for row in first["textures"])
        resources = list((tmp_path / "cache").rglob("cdmw-shader-preview-v1/*.dds"))
        assert len(resources) == 1
        stamp = resources[0].stat().st_mtime_ns
        edited = apply(.7)
        second = session.archive_refit_material_cache[edited["state"]["archive_refit_materials"]["key"]]
        assert second["textures"] == first["textures"]
        assert second["material_presentations"][0]["shader_controls"][4] == .7
        assert resources[0].stat().st_mtime_ns == stamp
        assert session.archive_refit_material_cache["base"] == base
        assert service.capture_export_snapshot(session.authoritative_session_id).replacement_state is None
        command(session, "undo")
        assert session.shadow_service.capture_export_snapshot(session.shadow_session_id).replacement_state.parts[0].shader_controls == choice(_wingFlowProgress=.2)
        command(session, "redo")
        with monkeypatch.context() as failure:
            failure.setattr("cdmw.services.mesh_rust_replacement_materials.stage_replacement_materials", lambda *args: (_ for _ in ()).throw(RuntimeError("staging failed")))
            with pytest.raises(Exception, match="staging failed"):
                apply(.3)
        assert session.shadow_service.capture_export_snapshot(session.shadow_session_id).replacement_state.parts[0].shader_controls == choice(_wingFlowProgress=.7)
        restored = command(session, "replacement_shader_controls", {"part_ids": [key], "reset": True})
        assert restored["state"]["archive_refit_materials"]["key"] == "base"
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id)


def test_texture_cache_validates_before_publication_and_honours_cancel(tmp_path, monkeypatch):
    from cdmw.core.temp_cache import session_generated_cache_path
    from cdmw.services.shader_controls_preview import publish_preview_texture, shader_preview_mesh
    from cdmw.domain.cancellation import RunCancelled
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from tests.test_new_item_materials import dds
    from cdmw.services.mesh_rust_authoring import RustMeshProtocolError
    monkeypatch.setenv("CDMW_TEMP_CACHE_ROOT", str(tmp_path / "cache"))
    directory = session_generated_cache_path("cdmw-shader-preview-v1")
    with pytest.raises(RustMeshProtocolError, match="not a DDS"):
        publish_preview_texture(b"invalid DDS")
    assert not list(directory.iterdir())
    event = threading.Event()
    def read(_path):
        event.set()
        return dds()
    snapshot = SimpleNamespace(has_entry=lambda _: True, payload=read)
    mesh = ParsedMesh(path="imported.obj", submeshes=[SubMesh(name="Blade", material="Blade")])
    with pytest.raises(RunCancelled):
        shader_preview_mesh(mesh, (("Blade", choice()),), snapshot=snapshot, stop_event=event)
    assert not list(directory.iterdir())


def test_pac_vertex_colours_reach_render_document_and_effect_placement():
    import copy
    from cdmw.modding.mesh_parser import parse_pac
    from cdmw.services.mesh_rust_authoring import _mesh_document_payload
    from cdmw.ui.new_item.effect_item_source import PlannedEffectItemSource
    from cdmw.ui.new_item.model_import import ModelPlacement
    from tests.test_mesh_pac_topology_serializer import _pac_fixture

    payload = _pac_fixture()
    original = parse_pac(payload, "character/model/helmet.pac")
    part = original.submeshes[0]
    assert part.shader_masks == [(0x33 / 255, 0x44 / 255, 1.)] * len(part.vertices)
    document = _mesh_document_payload(original)
    assert document["lods"][0]["submeshes"][0]["shader_masks"] == part.shader_masks
    native = copy.deepcopy(original)
    native.submeshes[0].shader_masks = []  # canonical native geometry needs exact source colours
    xml_path = "character/modelproperty/helmet.pac_xml"
    data = {original.path: payload, xml_path: material("SkinnedMeshHairAnimatedUV", name=part.name).encode()}
    snapshot = SimpleNamespace(has_entry=lambda path: path in data, payload=lambda path: data[path])
    settings = ((part.name, choice("SkinnedMeshHairAnimatedUV", _speedU=3)),)
    source = PlannedEffectItemSource(None, ModelPlacement(offset=(5., 2., 1.)), False, None,
                                    b"", snapshot, None, None, shader_controls=settings)
    preview, kind = source._finish(native, "template", threading.Event(), template_transform=source.placement.matrix())
    assert kind == "template"
    assert preview.submeshes[0].shader_masks == part.shader_masks
    assert preview.submeshes[0].vertices[0][0] == pytest.approx(part.vertices[0][0] + 5)
    assert preview.submeshes[0].preview_native_material_overrides["shader_controls"][6] == 3
    assert native.submeshes[0].shader_masks == []
    assert not hasattr(native.submeshes[0], "preview_native_material_overrides")


@pytest.mark.parametrize("settings", [choice(_wingFlowProgress=.4),
    choice("SkinnedMeshEyeCover", _eyeCoverDiffuseParameter=.3, surface_alpha=.2, material_red=.1)])
def test_variant_switch_retains_shader_choices_and_plans_only_selected_variant(tmp_path, settings):
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.new_item.controller import NewItemStudioController
    from tests.test_new_item_provenance import setup_game
    from tests.test_new_item_service import TEMPLATE
    from tests.test_new_item_variant_authoring import selections
    app = QApplication.instance() or QApplication([])
    _, snapshot, _ = setup_game(tmp_path)
    controller = NewItemStudioController(synchronous=True)
    try:
        controller.snapshot = snapshot
        controller.set_template(TEMPLATE)
        first, second = [row.identity for row in selections(snapshot)[:2]]
        controller.select_variant(first)
        controls = (("Blade", settings),)
        controller.draft.shader_controls = controls
        controller.select_variant(second)
        assert controller.draft.shader_controls == ()
        controller.select_variant(first)
        assert controller.draft.shader_controls == controls
        spec = controller.current_spec()
        selected = next(row for row in spec.variants if row.identity == first)
        assert selected.shader_controls == controls
        assert all(not row.shader_controls for row in spec.variants if row.identity != first)
    finally:
        controller.shutdown()
        app.processEvents()


def test_new_item_preview_keeps_base_dds_and_adds_only_an_owned_shader_mask(tmp_path, monkeypatch):
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services.shader_controls_preview import shader_preview_mesh
    from cdmw.services.mesh_rust_authoring import _mesh_texture_payloads, _mesh_material_presentations, _material_input_is_renderer_role_eligible, _session_root_identity
    from tests.test_new_item_materials import dds
    monkeypatch.setenv("CDMW_TEMP_CACHE_ROOT", str(tmp_path / "cache"))
    base = tmp_path / "base.dds"
    base.write_bytes(dds())
    part = SubMesh(name="Blade", material="Blade", vertices=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)],
                   uvs=[(0., 0.), (1., 0.), (0., 1.)], faces=[(0, 1, 2)])
    part.preview_texture_dds_path = str(base)
    part.preview_texture_path = str(base)
    part.preview_native_material_overrides = {"roughness": .4}
    mesh = ParsedMesh(path="character/model/sword.pac", format="pac", submeshes=[part])
    payloads = {"character/modelproperty/sword.pac_xml": material().encode(), FAMILIES[0].default_mask: dds()}
    snapshot = SimpleNamespace(payload=lambda path: payloads[path], has_entry=lambda path: path in payloads)
    preview = shader_preview_mesh(mesh, (("Blade", choice()),), snapshot=snapshot)
    assert preview.submeshes[0].preview_native_material_overrides["shader_controls"][4] == 2
    assert preview.submeshes[0].preview_native_material_overrides["roughness"] == .4
    assert part.preview_native_material_overrides == {"roughness": .4}
    output = tmp_path / "package"
    output.mkdir()
    resources = _mesh_texture_payloads(output, preview, expected_root_identity=_session_root_identity(output))
    assert {row["role"] for row in resources} >= {"base_color", "shader_mask"}
    assert _mesh_material_presentations(preview)[0]["shader_controls"][4] == 2
    for resource in resources:
        assert resource["material_indices_by_lod"] == [[0]]
        assert (output / resource["file"]["path"]).read_bytes() == dds()
    foreign = SimpleNamespace(binding_authority="authoritative", owner_slot_index=2)
    owner = SimpleNamespace(preview_pac_material_owner_slot_index=1)
    assert not _material_input_is_renderer_role_eligible(owner, foreign, "shader_mask")


def test_build_plan_owns_only_the_selected_template_shader_variant(tmp_path):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.services.new_item_service import NewItemService
    from tests.test_new_item_provenance import current_files, spec
    from tests.test_new_item_service import PAC, PAC_XML, build_package, _read
    from tests.test_new_item_variant_authoring import selections
    files = current_files()
    files[PAC_XML] = material(name="Blade").encode()
    pamt = build_package(tmp_path / "game", files)
    before = pamt.read_bytes()
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(pamt), read_entry=_read)
    selected = next(value for value in selections(snapshot) if value.model_path == PAC)
    selected = replace(selected, shader_controls=(("Blade", choice(_wingFlowProgress=.6)),))
    plan = service.plan(replace(spec(), variants=(selected,)), snapshot)
    changed = [value for value in plan.manifest["variants"] if "output_model" in value]
    assert len(changed) == 1
    xmls = [data for path, data in plan.loose_files.items() if path.endswith(".pac_xml")]
    assert len(xmls) == 1
    wrapper = find_material_wrappers(xmls[0].decode("utf-8-sig"))[0]
    assert wrapper.shader == "SkinnedMeshWing" and wrapper.value("_wingFlowProgress") == "0.6"
    assert snapshot.payload(PAC_XML) == files[PAC_XML]
    assert pamt.read_bytes() == before


def test_mask_diagnostics_report_actual_gates_and_preserve_packed_bits():
    from cdmw.modding.mesh_parser import SubMesh
    from cdmw.services.shader_controls_preview import shader_control_diagnostic
    part = SubMesh(vertices=[(0., 0., 0.)] * 3, shader_masks=[(1., 1., 1.), (.2, .4, 1.), (1., 1., 0.)])
    torn = shader_control_diagnostic(part, choice("SkinnedMeshTornCloth_Ver2"), {})
    assert "Known masks: 2/3" in torn and "1 length-grain, 1 cross-grain" in torn
    assert "1 vertices below white green" in shader_control_diagnostic(part, choice("SkinnedMeshHairAnimatedUV"), {})
    packed = {"_hairDyeingProperty": str(0x01020380), "_hairDyeingColor": "#12345600"}
    assert "128/255; dye gate inactive" in shader_control_diagnostic(part, choice("SkinnedMeshAnisotropy"), packed)
    assert packed["_hairDyeingProperty"] == str(0x01020380)
    part.shader_masks = []
    assert "unavailable" in shader_control_diagnostic(part, choice("SkinnedMeshTornCloth_Ver2"), {})


def test_native_duplicate_remaps_masks_and_keeps_generated_vertices_unknown():
    from cdmw.modding.mesh_parser import SubMesh
    from cdmw.modding.mesh_native_duplicate_reports import _build_duplicate_submesh
    source = SubMesh(vertices=[(0., 0., 0.), (1., 0., 0.)], source_vertex_offsets=[100, 140],
                     shader_masks=[(.2, .4, 1.), (.7, .8, 1.)])
    result = _build_duplicate_submesh(source, {"vertices": [(2., 0., 0.)] * 3, "faces": [],
        "source_vertex_offsets": [140, -1, 100]}, source_index=0, copy_extra_attrs=True,
        reset_source_descriptors=True, recompute_normals=False)
    assert result.shader_masks == [(.7, .8, 1.), (1., 1., 0.), (.2, .4, 1.)]


def test_vertex_mask_controls_and_diagnostics_survive_mesh_undo(tmp_path, monkeypatch):
    from cdmw.modding.mesh_parser import parse_pac
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
    from tests.test_mesh_rust_replacement import command
    _, service, session = _open_exact_session(tmp_path / "session")
    try:
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        file = sidecar(snapshot)
        file = replace(file, data=file.data.replace(b'SkinnedMeshEmissive', b'SkinnedMeshHairAnimatedUV').replace(b'SkinnedMeshStandard', b'SkinnedMeshHairAnimatedUV'))
        monkeypatch.setattr("cdmw.services.mesh_replacement_materials.capture_replacement_dependencies", lambda *args: (file,))
        key = session.state_payload()["shader_controls"]["parts"][0]["id"]
        controls = choice("SkinnedMeshHairAnimatedUV", _speedU=3)
        edited = command(session, "replacement_shader_controls", {"part_ids": [key], "shader_controls": controls.to_dict()})
        note = edited["state"]["shader_controls"]["parts"][0]["diagnostic"]
        assert "Known masks:" in note and "below white green" in note
        original_masks = parse_pac(snapshot.original_data, snapshot.mesh.path).submeshes[0].shader_masks
        assert original_masks
        assert session.shadow_service.working_mesh(session.shadow_session_id).submeshes[0].shader_masks == original_masks
        command(session, "undo")
        command(session, "redo")
        assert session.shadow_service.working_mesh(session.shadow_session_id).submeshes[0].shader_masks == original_masks
        assert session.state_payload()["shader_controls"]["parts"][0]["diagnostic"] == note
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id)


@pytest.mark.parametrize("with_character", [False, True])
def test_applied_import_fallback_keeps_shader_controls_and_character(with_character):
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.ui.new_item.controller_preview_mixin import _imported_model_progressive_source
    from cdmw.ui.new_item.item_preview import PlacementScene
    part = SubMesh(name="Blade", material="Blade", vertices=[(0., 0., 0.)], shader_masks=[(.3, .2, 1.)])
    model = ParsedMesh(path="imported", submeshes=[part])
    body = ParsedMesh(submeshes=[SubMesh(name="Character")])
    source = _imported_model_progressive_source(model, (("Blade", choice("SkinnedMeshHairAnimatedUV", _speedV=4)),),
                                                character_mesh=(lambda _: body) if with_character else None)
    geometry = source.geometry(threading.Event())
    preview = source.materials(threading.Event())
    if with_character:
        assert isinstance(preview, PlacementScene) and preview.character is body and geometry.character is body
        preview, geometry = preview.model, geometry.model
    assert preview.submeshes[0].preview_native_material_overrides["shader_controls"][7] == 4
    assert not hasattr(geometry.submeshes[0], "preview_native_material_overrides")


def test_dye_preview_consumes_prepared_shader_material_before_cleanup(tmp_path, monkeypatch):
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.ui.new_item.dye_preview import variant_dye_preview_source
    from tests.test_new_item_provenance import setup_game
    from tests.test_new_item_service import PAC, PAC_XML, TEMPLATE
    from tests.test_new_item_variant_authoring import selections
    from tests.test_mesh_pac_topology_serializer import _pac_fixture
    _, snapshot, _ = setup_game(tmp_path)
    original_payload = snapshot.payload
    monkeypatch.setattr(type(snapshot), "payload", lambda self, path: material("SkinnedMeshHairAnimatedUV").encode() if path == PAC_XML else _pac_fixture() if path == PAC else original_payload(path))
    selected = next(value for value in selections(snapshot) if value.model_path == PAC)
    selected = replace(selected, shader_controls=(("Blade", choice("SkinnedMeshHairAnimatedUV", _speedU=9)),))
    state = SimpleNamespace(appearance=selected, result=None, source=None, scene=None)
    controller = SimpleNamespace(current_variant_identity=lambda: selected.identity, snapshot=snapshot,
        _sync_variant_state=lambda: None, _variant_states={selected.identity: state}, draft=SimpleNamespace(template_key=TEMPLATE))
    index = SimpleNamespace(rows={PAC.casefold(): object()}, pair=SimpleNamespace(payload_entry=SimpleNamespace(path="test.body"), header_entry=SimpleNamespace(path="test.header")))
    monkeypatch.setattr("cdmw.ui.new_item.dye_preview.load_dye_index", lambda *args, **kw: index)
    monkeypatch.setattr("cdmw.ui.new_item.dye_preview.prepare_dye_assignments", lambda row, data, *args, **kw: ((), data))
    monkeypatch.setattr("cdmw.ui.new_item.dye_preview.prepare_dye_preview_table", lambda *args: (b"body", b"header"))
    mesh = ParsedMesh(path=PAC, submeshes=[SubMesh(name="Blade", material="Blade")])
    monkeypatch.setattr("cdmw.services.mesh_dotnet_reference_composite.decode_dotnet_native_preview_package", lambda *args, **kw: mesh)
    monkeypatch.setattr("cdmw.ui.new_item.item_preview.build_item_preview_package", lambda model, **kw: model)
    prepared_paths = []
    def native(primary, prepared, *args, **kw):
        prepared_paths.extend(value.prepared_path for value in prepared if value.prepared_path)
        assert all(path.exists() for path in prepared_paths)
        return kw["consume_native_package"](tmp_path)
    monkeypatch.setattr("cdmw.ui.new_item.template_preview_cache.build_native_template_preview", native)
    _, source = variant_dye_preview_source(controller)
    preview = source.materials(threading.Event(), output_root=tmp_path, native_preview_core_cache_root=tmp_path)
    assert preview.submeshes[0].preview_native_material_overrides["shader_controls"][6] == 9
    assert not any(path.exists() for path in prepared_paths)
