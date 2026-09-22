"""Appearance and dye edits must survive both native preview handoff and planning."""
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.core.partprefab_dye_table import encode_prefab_dye_row, parse_prefab_dye_table
from cdmw.domain.mesh.shader_controls import ShaderControls
from cdmw.domain.new_item.authoring import DyeAssignment
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.services.new_item_service import NewItemService
from cdmw.services.new_item_template_model import prepare_template_model
from cdmw.services.new_item_variants import xml_path
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.dye_preview import variant_dye_preview_source
from tests.test_multichangeinfo_table import _table
from tests.test_new_item_dye_authoring import material, dye_row
from tests.test_new_item_provenance import current_files, spec
from tests.test_new_item_service import PAC, PAC_XML, TEMPLATE, build_package, _read
from tests.test_new_item_variant_authoring import selections
from tests.test_pac_xml_standard_material import texture

BASE = "gamedata/binarystaticinfo__/bin/partprefabdyeslotinfo"
MAPPING = (DyeAssignment("blade", "blade", (2, 1, 0)),)


def fixture(tmp_path, shader="SkinnedMeshStandard_Ver2"):
    files = current_files()
    base = "character/texture/appearance_base.dds"
    text = material(properties=(0,)).decode().replace("SkinnedMeshStandard_Ver2", shader)
    files[PAC_XML] = text.replace("</Vector>", texture("_baseColorTexture", "3", base, 2) + "</Vector>", 1).encode()
    from tests.test_new_item_materials import dds
    files[base] = dds()
    row = dye_row()
    files[BASE + ".staticinfobody"], files[BASE + ".staticinfoheader"] = _table([(row.key, encode_prefab_dye_row(row))])
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path / "game", files)), read_entry=_read)
    return service, snapshot, selections(snapshot)[0]


def output_material(plan, choice):
    model = next(value["output_model"] for value in plan.manifest["variants"]
                 if value["model_path"] == choice.model_path and "output_model" in value)
    return model, find_material_wrappers(plan.loose_files[xml_path(model)].decode())[0]


@pytest.mark.parametrize("kind", ["glow", "shader"])
def test_dye_mapping_keeps_compatible_appearance_edits_in_the_final_plan(tmp_path, kind):
    service, snapshot, choice = fixture(tmp_path, "SkinnedMeshTornCloth_Ver2" if kind == "shader" else "SkinnedMeshStandard_Ver2")
    if kind == "glow":
        choice = replace(choice, glow_parts=("blade",), glow_color=(1., 0., 0.), glow_intensity=9.)
    else:
        choice = replace(choice, shader_controls=(("blade", ShaderControls("SkinnedMeshTornCloth_Ver2",
            (("_tornCrossGrainPower", (.6,)),))),))
    original = snapshot.payload(PAC_XML)
    before = service.plan(replace(spec(), variants=(choice,)), snapshot)
    after = service.plan(replace(spec(), variants=(replace(choice, dyes=MAPPING),)), snapshot)
    _, expected = output_material(before, choice)
    model, actual = output_material(after, choice)
    assert actual.shader == expected.shader
    parameter = "_emissiveIntensity" if kind == "glow" else "_tornCrossGrainPower"
    assert actual.value(parameter) == expected.value(parameter)
    assert actual.value("_emissiveColor") == expected.value("_emissiveColor")
    rows = parse_prefab_dye_table(after.loose_files[BASE + ".staticinfobody"], after.loose_files[BASE + ".staticinfoheader"])
    assert next(value for value in rows if value.model_path == model).submeshes[0].slots == (2, 1, 0)
    assert snapshot.payload(PAC_XML) == original


def test_incompatible_dye_graft_cannot_silently_replace_translucency(tmp_path):
    service, snapshot, choice = fixture(tmp_path)
    choice = replace(choice, translucency=TranslucencyChoice(("blade",), .1, .3))
    valid = service.plan(replace(spec(), variants=(choice,)), snapshot)
    assert output_material(valid, choice)[1].shader == "SkinnedMeshTranslucent"
    with pytest.raises(ValueError, match="dye mapping would replace the edited material"):
        service.plan(replace(spec(), variants=(replace(choice, dyes=MAPPING),)), snapshot)


def test_another_parts_appearance_edit_does_not_block_an_unedited_dye_donor_swap():
    from cdmw.services.new_item_dyes import prepare_dye_assignments
    from tests.test_pac_xml_standard_material import wrapper
    guard = wrapper("Guard", "SkinnedMeshStandard_Ver2", texture("_maskTexture", "2", "guard.dds", 0)
        + '<MaterialParameterFloat StringItemID="_dyeingGlobalOpacity" ItemID="3" _name="_dyeingGlobalOpacity" _value="1" Index="1"/>')
    original = material(properties=(0,)).replace(b"</ModelProperty>", guard.encode() + b"</ModelProperty>")
    edited = original.replace(b"SkinnedMeshStandard_Ver2", b"SkinnedMeshEmissive_Ver2", 1)
    parts, result = prepare_dye_assignments(dye_row(), edited, original,
        (DyeAssignment("Guard", "blade", (2, 1, 0)),), imported=False, preserve_materials=True)
    wrappers = find_material_wrappers(result.decode())
    assert wrappers[0].shader == "SkinnedMeshEmissive_Ver2"
    assert wrappers[1].textures["_colorBlendingMaskTexture"] == "character/texture/template_mask.dds"
    assert parts[0].name == "Guard"


@pytest.mark.parametrize("dyes", [None, MAPPING])
def test_dye_preview_handoff_keeps_template_glow(tmp_path, monkeypatch, dyes):
    _, snapshot, choice = fixture(tmp_path)
    choice = replace(choice, dyes=dyes, glow_parts=("blade",), glow_color=(1., 0., 0.), glow_intensity=9.)
    state = SimpleNamespace(appearance=choice, result=None, source=None, scene=None)
    controller = SimpleNamespace(current_variant_identity=lambda: choice.identity, snapshot=snapshot,
        _sync_variant_state=lambda: None, _variant_states={choice.identity: state}, draft=SimpleNamespace(template_key=TEMPLATE))
    captured = []
    def native(_primary, entries, *_args, **_kwargs):
        captured.append(next(entry.prepared_path.read_bytes() for entry in entries if entry.path == PAC_XML))
        return object()
    monkeypatch.setattr("cdmw.ui.new_item.template_preview_cache.build_native_template_preview", native)
    _, preview = variant_dye_preview_source(controller)
    preview.materials(Event(), output_root=tmp_path, native_preview_core_cache_root=tmp_path)
    expected = prepare_template_model(snapshot, (PAC,), glow=choice.glow_choice()).side_files[PAC_XML]
    assert captured == [expected]


def test_template_dye_preview_prepares_translucency_before_checking_dye_compatibility(tmp_path, monkeypatch):
    _, snapshot, choice = fixture(tmp_path)
    choice = replace(choice, dyes=None, translucency=TranslucencyChoice(("blade",), .2, .4))
    state = SimpleNamespace(appearance=choice, result=None, source=None, scene=None)
    controller = SimpleNamespace(current_variant_identity=lambda: choice.identity, snapshot=snapshot,
        _sync_variant_state=lambda: None, _variant_states={choice.identity: state}, draft=SimpleNamespace(template_key=TEMPLATE))
    class Captured(Exception):
        pass
    def check(_row, data, *_args, **_kwargs):
        actual = find_material_wrappers(data.decode())[0]
        assert actual.shader == "SkinnedMeshTranslucent"
        assert float(actual.value("_thickness")) == .2
        assert float(actual.value("_extinctionCoefficient")) == .4
        raise Captured()
    monkeypatch.setattr("cdmw.ui.new_item.dye_preview.prepare_dye_assignments", check)
    _, preview = variant_dye_preview_source(controller)
    with pytest.raises(Captured):
        preview.materials(Event(), output_root=tmp_path, native_preview_core_cache_root=tmp_path)


def test_clear_dyes_survives_variant_switch_and_writes_an_empty_dye_row(tmp_path):
    app = QApplication.instance() or QApplication([])
    service, snapshot, choice = fixture(tmp_path)
    controller = NewItemStudioController(service=service, synchronous=True)
    try:
        controller.snapshot = snapshot
        controller.set_template(TEMPLATE)
        controller.select_variant(choice.identity)
        # Merely selecting a variant must not create an appearance override.
        assert not controller.current_spec().variants
        controller.set_variant_dyes(MAPPING)
        controller.set_variant_dyes(())
        other = selections(snapshot)[1].identity
        controller.select_variant(other)
        controller.select_variant(choice.identity)
        choices = controller.current_spec().variants
        assert len(choices) == 1 and choices[0].dyes == ()
        plan = service.plan(replace(spec(), variants=choices), snapshot)
        model, _ = output_material(plan, choice)
        rows = parse_prefab_dye_table(plan.loose_files[BASE + ".staticinfobody"], plan.loose_files[BASE + ".staticinfoheader"])
        assert next(value for value in rows if value.model_path == model).submeshes == ()
    finally:
        controller.shutdown()
        app.processEvents()
