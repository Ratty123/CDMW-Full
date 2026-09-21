"""Selected-part export, reversible preview and draft coverage for translucency."""

import os
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
