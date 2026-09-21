"""Selected-part export, reversible preview and draft coverage for translucency."""

import os
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.new_item.rules import validate_spec
from cdmw.domain.new_item.spec import MaterialRoute, ModelSource
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.services.new_item_materials import SourceMaterialTextures, route_model_files, route_plain_pbr
from cdmw.services.new_item_planning import NewItemPlanError
from cdmw.services.new_item_translucency import selected_translucency, source_translucency, translucency_preview_mesh
from cdmw.ui.new_item.state import NewItemDraft, spec_from_draft
from tests.test_new_item_materials import XML, builder_files


def prebuilt_glass_files():
    from cdmw.core.pac_xml_standard_material import PlainMaterial, rewrite_materials
    from tests.test_new_item_materials import GEM_BASE, GEM_EMI, GEM_MASK

    files = builder_files()
    original = files.side_files[XML].decode()
    gem = find_material_wrappers(original)[1].submesh_name
    text = rewrite_materials(original, {gem: PlainMaterial(
        base=GEM_BASE, material=GEM_MASK, emissive_texture=GEM_EMI,
        emissive_color="#FF0000FF", emissive_intensity=10, translucency=(0.1, 0.3),
    )}).text
    return replace(files, side_files={**files.side_files, XML: text.encode()})


@pytest.mark.parametrize("current", [False, True])
@pytest.mark.parametrize("selected_index", [0, 1])
def test_prebuilt_plans_change_only_selected_absorption_and_keep_glass_glow_and_textures(tmp_path, current, selected_index):
    from tests.test_new_item_provenance import setup_game, spec

    service, snapshot, _ = setup_game(tmp_path, current=current)
    files = prebuilt_glass_files()
    original = files.side_files[XML].decode()
    before = find_material_wrappers(original)
    choice = TranslucencyChoice((before[selected_index].submesh_name,), 0.25, 0.6)
    request = replace(spec(), model_source=ModelSource.IMPORTED, material_route=MaterialRoute.PLAIN_PBR,
                      translucency=choice)
    # Stop after real service/variant material preparation, before unrelated
    # table composition and geometry rig validation on these owned fixture bytes.
    with patch("cdmw.services.new_item_service.build_plan", side_effect=lambda *_args, **kwargs: kwargs), \
         patch("cdmw.services.new_item_variants.validate_variant_rig"):
        prepared = service.plan(request, snapshot, model=files)
    output = next(iter(prepared["variant_models"].values())) if current else prepared["model"]
    text = output.side_files[XML].decode()
    after = find_material_wrappers(text)
    assert output.pac_data == files.pac_data
    assert {path: data for path, data in output.side_files.items() if path != XML} == {
        path: data for path, data in files.side_files.items() if path != XML
    }
    for index, (old, new) in enumerate(zip(before, after)):
        if index == selected_index:
            assert new.shader == "SkinnedMeshTranslucent"
            assert float(new.value("_thickness")) == 0.25
            assert float(new.value("_extinctionCoefficient")) == 0.6
            retained = lambda row: tuple(parameter for parameter in row.parameters
                                         if parameter.name not in {"_thickness", "_extinctionCoefficient"})
            assert retained(new) == retained(old)
        else:
            assert text[new.start:new.end] == original[old.start:old.end]
    assert after[1].shader == "SkinnedMeshTranslucent"
    assert after[1].value("_emissiveColor") == "#FF0000FF"
    assert float(after[1].value("_emissiveIntensity")) == 10
    assert files.side_files[XML].decode() == original


def test_prebuilt_override_is_reversible_and_missing_selections_fail_without_mutation():
    from cdmw.services.new_item_translucency import apply_prebuilt_translucency

    files = prebuilt_glass_files()
    assert apply_prebuilt_translucency(files, MaterialRoute.PLAIN_PBR, None) is files
    with pytest.raises(NewItemPlanError, match="not found"):
        apply_prebuilt_translucency(files, MaterialRoute.PLAIN_PBR, TranslucencyChoice(("missing",)))
    with pytest.raises(NewItemPlanError, match="Plain PBR"):
        apply_prebuilt_translucency(files, MaterialRoute.BUILDER, TranslucencyChoice(("missing",)))
    assert files == prebuilt_glass_files()


def test_export_changes_only_selected_material_and_preserves_texture_bytes():
    files = builder_files()
    before = find_material_wrappers(files.side_files[XML].decode())
    chosen = before[0].submesh_name
    choice = TranslucencyChoice((chosen,), 0.125, 0.42)
    result = route_plain_pbr(files, translucency=choice).files
    text = result.side_files[XML].decode()
    # PAC XML is a sequence of XML roots, as in the stock sidecars.
    ET.fromstring("<Document>" + text.lstrip("\ufeff") + "</Document>")
    wrappers = find_material_wrappers(text)
    selected = next(row for row in wrappers if row.submesh_name == chosen)
    assert selected.shader == "SkinnedMeshTranslucent"
    assert selected.value("_thickness") == "0.125000"
    assert selected.value("_extinctionCoefficient") == "0.420000"
    assert all(row.shader != selected.shader for row in wrappers if row.submesh_name != chosen)
    for path in selected.textures.values():
        assert result.side_files[path] == files.side_files[path]
    assert files.side_files[XML].decode() == builder_files().side_files[XML].decode()
    assert result.pac_data == files.pac_data
    assert any("approximate" in warning for warning in result.warnings)


def test_source_names_resolve_but_missing_names_and_mixed_atlases_do_not_silently_export():
    files = builder_files()
    name = find_material_wrappers(files.side_files[XML].decode())[0].submesh_name
    choice = TranslucencyChoice(("Blade",))
    result = route_plain_pbr(files, sources={name.casefold(): SourceMaterialTextures("Blade")},
                             translucency=choice, encode_factors=lambda *_: b"material map").files
    assert find_material_wrappers(result.side_files[XML].decode())[0].shader == "SkinnedMeshTranslucent"
    with pytest.raises(NewItemPlanError, match="not found"):
        route_plain_pbr(files, translucency=choice)
    with pytest.raises(NewItemPlanError, match="Plain PBR"):
        route_model_files(files, MaterialRoute.BUILDER, translucency=choice)
    atlas = SourceMaterialTextures("Combined", atlas_sources=(SourceMaterialTextures("Blade"), SourceMaterialTextures("Grip")))
    with pytest.raises(NewItemPlanError, match="share one atlas"):
        selected_translucency(choice, "part_0", atlas)
    assert selected_translucency(TranslucencyChoice(("Blade", "Grip")), "part_0", atlas) == {"blade", "grip"}


def test_authored_glass_atlases_cannot_silently_change_opaque_regions():
    files = builder_files()
    name = find_material_wrappers(files.side_files[XML].decode())[0].submesh_name
    glass = SourceMaterialTextures("Glass", transmission_factor=0.5)
    atlas = SourceMaterialTextures("Combined", atlas_sources=(glass, SourceMaterialTextures("Grip")))
    assert source_translucency(SourceMaterialTextures("AllGlass", atlas_sources=(glass, glass))) == (0.1, 0.3)
    with pytest.raises(NewItemPlanError, match="glass and opaque materials share one atlas"):
        route_plain_pbr(files, sources={name.casefold(): atlas})
    result = route_plain_pbr(
        files, sources={name.casefold(): atlas}, translucency=TranslucencyChoice(("Glass", "Grip")),
        encode_factors=lambda *_: b"material map",
    ).files
    assert find_material_wrappers(result.side_files[XML].decode())[0].shader == "SkinnedMeshTranslucent"


@pytest.mark.parametrize("factor", [0, -0.1, float("nan"), float("inf"), "invalid"])
def test_inactive_or_invalid_transmission_does_not_enable_glass(factor):
    assert source_translucency(SimpleNamespace(transmission_factor=factor)) is None


def test_emissive_selection_retains_map_colour_and_strength():
    files = builder_files()
    from cdmw.domain.new_item.spec import GlowChoice
    name = find_material_wrappers(files.side_files[XML].decode())[0].submesh_name
    result = route_plain_pbr(files, translucency=TranslucencyChoice((name,)),
                            glow=GlowChoice((name,)), encode_glow=lambda: b"emissive map").files
    wrapper = next(row for row in find_material_wrappers(result.side_files[XML].decode()) if row.submesh_name == name)
    assert wrapper.shader == "SkinnedMeshTranslucent"
    assert result.side_files[wrapper.textures["_emissiveIntensityTexture"]] == b"emissive map"
    assert wrapper.value("_emissiveColor") == "#FFFFFFFF"
    assert float(wrapper.value("_emissiveIntensity")) == GlowChoice((name,)).intensity
    assert any("may ignore" in warning for warning in result.warnings)


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_draft_validation_rejects_invalid_absorption(value):
    draft = NewItemDraft(template_key=1, internal_name="Test", model_source=ModelSource.IMPORTED,
                         translucency=TranslucencyChoice(("Blade",), value, 0.3))
    spec = spec_from_draft(draft, None)
    assert spec.translucency == draft.translucency
    assert any(issue.code == "translucency.invalid" for issue in validate_spec(spec))


def test_effect_preview_copies_inputs_and_keeps_translucency_in_rust_package():
    from cdmw.services import mesh_rust_authoring as authoring
    part = SimpleNamespace(name="part_0", material="Blade", preview_native_material_overrides={"roughness": 0.4})
    mesh = SimpleNamespace(path="test.pac", lod_levels=[], submeshes=[part])
    preview = translucency_preview_mesh(mesh, TranslucencyChoice(("Blade",), 0.2, 0.4))
    assert "translucency" not in part.preview_native_material_overrides
    with patch.object(authoring, "mesh_dotnet_material_state_payload", return_value={
        "submeshes": [{"submesh_index": 0, "material_slot_index": 0, "parameters": {}}]
    }):
        row = authoring._mesh_material_presentations(preview)[0]
    assert row["translucency"] == [0.2, 0.4]
    assert row["roughness"] == 0.4


def test_live_panel_groups_keep_glow_and_clear_translucency_when_disabled():
    from cdmw.ui.new_item.panels_model import ModelPanel
    from tests.test_new_item_glow_preview import PanelGlowSyncTests
    panel, sent = PanelGlowSyncTests()._panel(glow_parts=("Gem",))
    panel._controller.draft.translucency = TranslucencyChoice(("Blade",))
    ModelPanel._sync_glow_preview(panel)
    assert any(group.get("translucency") == [0.1, 0.3] and group["source_submesh_indices"] == [0] for group in sent[-1])
    assert any(group.get("emissive_intensity") == 5.0 for group in sent[-1])
    panel._controller.draft.translucency = None
    ModelPanel._sync_glow_preview(panel)
    assert all(group.get("translucency") is None for group in sent[-1])


def test_plain_pbr_checkbox_replays_source_glass_and_restores_builder_preview():
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.model_import import ModelPlacement
    from cdmw.ui.new_item.panels_model import ModelPanel
    from tests.test_new_item_glow_preview import _mesh, _parameter

    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    panel = ModelPanel(controller)
    mesh = _mesh()
    mesh.submeshes[1].preview_material_parameters.append(_parameter("_transmissionFactor", value="0.5"))
    controller.model_import = SimpleNamespace(scene=SimpleNamespace(mesh=mesh), baked_preview_mesh=lambda: mesh)
    sent = []
    panel.preview.host = SimpleNamespace(apply_material_parameter_groups=lambda groups: sent.append(groups) or True)
    panel.preview.is_ready = True
    panel.preview._loaded_is_placement = True
    panel.preview._placement = ModelPlacement()
    panel.plain_pbr.setEnabled(True)
    try:
        panel._sync_glow_preview()
        assert any(group.get("translucency") == [0.1, 0.3] and group["source_submesh_indices"] == [1] for group in sent[-1])
        panel.plain_pbr.setChecked(False)
        assert controller.draft.material_route is MaterialRoute.BUILDER
        assert all(group.get("translucency") is None for group in sent[-1])
        panel.plain_pbr.setChecked(True)
        assert any(group.get("translucency") == [0.1, 0.3] for group in sent[-1])
        controller.draft.translucency = TranslucencyChoice(("Blade",), 0.05, 0.5)
        panel._sync_glow_preview()
        assert any(group.get("translucency") == [0.05, 0.5] and group["source_submesh_indices"] == [0] for group in sent[-1])
        assert any(group.get("translucency") == [0.1, 0.3] and group["source_submesh_indices"] == [1] for group in sent[-1])
        controller.draft.translucency = None
        panel._sync_glow_preview()
        absorption = [group["translucency"] for group in sent[-1] if "translucency" in group]
        assert absorption == [None, [0.1, 0.3], None]
    finally:
        panel.preview.host = None
        controller.model_import = None
        panel.preview.shutdown()
        controller.request_shutdown()
        panel.deleteLater()
        controller.deleteLater()
        app.processEvents()


def test_editor_signals_values_and_restores_a_variant_without_emitting_edits():
    from cdmw.ui.new_item.translucency_editor import TranslucencyEditor
    app = QApplication.instance() or QApplication([])
    editor = TranslucencyEditor()
    sent = []
    editor.changed.connect(sent.append)
    try:
        editor.refresh((("Blade", "Blade"), ("Grip", "Grip")), None)
        assert not sent and editor.isEnabled()
        editor.setChecked(True)
        editor.parts.item(0).setCheckState(Qt.CheckState.Checked)
        editor.thickness.setValue(0.275)
        assert sent[-1] == TranslucencyChoice(("Blade",), 0.275, 0.3)
        editor.setChecked(False)
        assert sent[-1] is None
        sent.clear()
        editor.refresh((("Blade", "Blade"), ("Grip", "Grip")), TranslucencyChoice(("Grip",), 0.5, 0.2))
        assert not sent and editor.isChecked()
        assert editor.thickness.value() == 0.5 and editor.extinction.value() == 0.2
        editor.refresh((), None)
        assert not editor.isChecked() and not editor.isEnabled()
    finally:
        editor.close()
        editor.deleteLater()
        app.processEvents()


def test_per_part_controls_preserve_other_parts_and_restore_without_signals():
    from cdmw.ui.new_item.translucency_editor import TranslucencyEditor
    app = QApplication.instance() or QApplication([])
    editor = TranslucencyEditor()
    sent = []
    editor.changed.connect(sent.append)
    try:
        rows = (("Blade", "Blade"), ("Gem", "Gem"))
        editor.refresh(rows, None)
        editor.setChecked(True)
        editor.parts.item(0).setCheckState(Qt.CheckState.Checked)
        editor.extinction.setValue(0.7)
        editor.parts.item(1).setCheckState(Qt.CheckState.Checked)
        editor.preset.setCurrentIndex(4)  # Dense absorption on the highlighted Gem.
        choice = sent[-1]
        assert choice.values_for("Blade") == (0.1, 0.7)
        assert choice.values_for("gem") == (1.0, 1.0)
        before = len(sent)
        editor.parts.setCurrentRow(0)
        assert len(sent) == before and editor.extinction.value() == 0.7
        editor.absorption.setValue(500)
        assert sent[-1].values_for("Blade") == (0.5, 0.5)
        assert sent[-1].values_for("Gem") == (1.0, 1.0)
        saved = sent[-1]
        editor.refresh(rows, None)
        editor.refresh(rows, saved)
        assert sent[-1] == saved and len(sent) == before + 1
        editor.parts.setCurrentRow(1)
        assert editor.preset.currentIndex() == 4
        editor.parts.item(1).setCheckState(Qt.CheckState.Unchecked)
        assert sent[-1].parts == ("Blade",)
        assert sent[-1].values_for("Blade") == (0.5, 0.5)
    finally:
        editor.deleteLater()
        app.processEvents()


def test_per_part_values_reach_import_prebuilt_template_and_preview():
    from cdmw.services.new_item_translucency import apply_prebuilt_translucency, translucency_preview_parameter_groups
    from cdmw.services.new_item_template_model import prepare_template_model

    files = prebuilt_glass_files()
    names = tuple(row.submesh_name for row in find_material_wrappers(files.side_files[XML].decode())[:2])
    settings = {names[0]: (0.2, 0.4), names[1]: (0.7, 0.9)}
    choice = TranslucencyChoice.from_settings(settings)
    choice.validate()
    model_path = XML.replace("/modelproperty/", "/model/").removesuffix("_xml")
    snapshot = SimpleNamespace(payload=lambda path: files.pac_data if path == model_path else files.side_files[path],
                               has_entry=lambda path: path in files.side_files)
    outputs = [
        route_model_files(files, MaterialRoute.PLAIN_PBR, translucency=choice),
        apply_prebuilt_translucency(files, MaterialRoute.PLAIN_PBR, choice),
        prepare_template_model(snapshot, (model_path,), translucency=choice),
    ]
    for output in outputs:
        for row in find_material_wrappers(output.side_files[XML].decode()):
            if row.submesh_name not in settings:
                continue
            assert row.shader == "SkinnedMeshTranslucent"
            assert (float(row.value("_thickness")), float(row.value("_extinctionCoefficient"))) == settings[row.submesh_name]
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name=name, material=name) for name in names])
    assert [row["translucency"] for row in translucency_preview_parameter_groups(mesh, choice)] == [[0.2, 0.4], [0.7, 0.9]]
    legacy = TranslucencyChoice(names, 0.2, 0.4)
    assert all(legacy.values_for(name) == (0.2, 0.4) for name in names)


def test_conflicting_atlas_settings_and_invalid_part_overrides_fail():
    choice = TranslucencyChoice.from_settings({"Blade": (0.2, 0.4), "Gem": (0.7, 0.9)})
    atlas = SourceMaterialTextures("Combined", atlas_sources=(SourceMaterialTextures("Blade"), SourceMaterialTextures("Gem")))
    with pytest.raises(NewItemPlanError, match="different translucency settings"):
        selected_translucency(choice, "combined", atlas)
    for settings in ((("Missing", 0.1, 0.3),), (("Blade", 0.1, 0.3), ("blade", 0.5, 0.7)), (("Blade", float("nan"), 0.3),)):
        with pytest.raises(ValueError):
            TranslucencyChoice(("Blade",), part_settings=settings).validate()
