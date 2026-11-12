"""The inspector must show what the material declares, not the definition defaults.

Values mirror the shipped wedding veil cd_phw_00_hel_00_0219 (two wrappers with
different numbers) decoded on 2026-11-12.
"""
from types import SimpleNamespace

from cdmw.domain.mesh.shader_controls import (BLENDED_FAMILIES, ShaderControls, authored_field_numbers,
                                             authored_values_payload, catalogue_payload, family_for,
                                             preview_factors)
from cdmw.services.mesh_shader_controls import _shader_source_options
from cdmw.services.shader_controls_preview import authored_blended_factors

VEIL_B = {"_netPitch": "0.300000", "_netThread": "0.727000", "_glow": "0.516000", "_sheen": "0.901000",
          "_uvScale": "0.270000", "_dyeingColor": "#d9d9d9ff"}
VEIL_A = {"_netPitch": "0.334000", "_netThread": "0.538000", "_glow": "0.443000", "_sheen": "0.625000"}


def veil_part(values, name="cd_phw_00_hel_00_0219"):
    part = SimpleNamespace(name=name, material=name)
    part.preview_sidecar_shader_family = "SkinnedMeshTransparency"
    part.preview_material_parameters = tuple(SimpleNamespace(parameter_name=key, value=value)
                                             for key, value in values.items())
    part.preview_material_texture_inputs = (
        SimpleNamespace(parameter_name="_baseColorTexture", source_texture_path="character/texture/cd_phw_00_hel_00_0219.dds",
                        material_parameters=(), shader_family="SkinnedMeshTransparency"),
        SimpleNamespace(parameter_name="_heightTexture", source_texture_path="character/texture/cd_phw_00_hel_00_0219_disp.dds",
                        material_parameters=(), shader_family="SkinnedMeshTransparency"))
    return part


def session(*parts):
    mesh = SimpleNamespace(submeshes=list(parts))
    return SimpleNamespace(replacement_state=None, mesh_format="pac", working_mesh=mesh, base_mesh=mesh)


def test_panel_state_reports_each_wrappers_own_authored_numbers():
    rows = _shader_source_options(session(veil_part(VEIL_A, "veil_a"), veil_part(VEIL_B)))
    first = rows[0]["authored"][0]["fields"]["SkinnedMeshTransparency"]
    second = rows[1]["authored"][0]["fields"]["SkinnedMeshTransparency"]
    assert first == {"_netPitch": [0.334], "_netThread": [0.538], "_glow": [0.443], "_sheen": [0.625]}
    assert second["_netPitch"] == [0.3] and second["_netThread"] == [0.727]
    assert second["_uvScale"] == [0.27]
    assert second["_dyeingColor"] == [217 / 255] * 3
    # A parameter the wrapper does not declare is absent, so the panel can label it a default.
    assert "_uvScale" not in first and "_dyeingColor" not in first
    assert rows[1]["authored"][0]["shader"] == "SkinnedMeshTransparency"
    assert rows[1]["authored"][0]["textures"]["_heightTexture"].endswith("_disp.dds")


def test_preview_base_is_the_vector_the_viewport_already_draws():
    part = veil_part(VEIL_B)
    row = _shader_source_options(session(part))[0]
    assert row["shader_options"]["SkinnedMeshTransparency"] == ""
    assert tuple(row["preview_base"]["SkinnedMeshTransparency"]) == tuple(authored_blended_factors(part))
    assert row["preview_base"]["SkinnedMeshTransparency"][:13] == [
        11.0, 1.0, 0.0, 0.0, 0.3, 0.727, 0.516, 0.901, 0.27, 217 / 255, 217 / 255, 217 / 255, 1.0]
    # Families the source cannot become have no live-preview base.
    assert "Dissolve" not in row["preview_base"]


def test_one_parser_feeds_the_panel_and_the_renderer():
    veil = family_for("SkinnedMeshTransparency")
    for field in veil.fields:
        shown = authored_field_numbers(field, VEIL_B.get(field.name))
        assert shown is not None
        offset = 4 + sum(len(other.default) for other in veil.fields[:veil.fields.index(field)])
        drawn = preview_factors(ShaderControls(veil.shader), VEIL_B)[offset:offset + len(field.default)]
        assert tuple(shown) == tuple(drawn)
    assert authored_field_numbers(veil.fields[0], None) is None
    assert authored_field_numbers(veil.fields[0], "not a number") is None
    assert authored_field_numbers(veil.fields[0], "") is None
    assert authored_values_payload({}) == {} and authored_values_payload(None) == {}


def test_catalogue_field_order_defines_the_lane_layout_the_inspector_edits():
    """The Rust inspector replaces lanes at 4 + the summed widths of earlier fields."""
    catalogue = {family["shader"]: family for family in catalogue_payload()}
    for family in BLENDED_FAMILIES:
        lane = 4
        base = preview_factors(ShaderControls(family.shader), {})
        for field, row in zip(family.fields, catalogue[family.shader]["fields"]):
            assert row["name"] == field.name and len(row["default"]) == len(field.default)
            edited = tuple(min(field.maximum, value + 0.125) for value in field.default)
            expected = list(base)
            expected[lane:lane + len(edited)] = edited
            assert preview_factors(ShaderControls(family.shader, ((field.name, edited),)), {}) == tuple(expected)
            lane += len(field.default)


def test_presets_are_valid_controls_for_their_family():
    from cdmw.domain.mesh.shader_controls import SHADER_PRESETS
    catalogue = {family["shader"]: family for family in catalogue_payload()}
    assert set(SHADER_PRESETS) == {"SkinnedMeshTransparency", "SkinnedMeshGlass"}
    for shader, presets in SHADER_PRESETS.items():
        assert [row["label"] for row in catalogue[shader]["presets"]] == [label for label, _ in presets]
        for label, values in presets:
            ShaderControls(shader, values).validate()
            preview_factors(ShaderControls(shader, values), {})
    veil_b = dict(SHADER_PRESETS["SkinnedMeshTransparency"])["Wedding veil B"]
    assert preview_factors(ShaderControls("SkinnedMeshTransparency", veil_b), {})[:12] == \
        preview_factors(ShaderControls("SkinnedMeshTransparency"), VEIL_B)[:12]
    assert all(family["presets"] == [] for shader, family in catalogue.items() if shader not in SHADER_PRESETS)


def test_new_item_editor_shows_the_source_numbers_for_untouched_fields():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from cdmw.core.material_shader_controls import equipment_authored_values, equipment_shader_options
    from cdmw.ui.new_item.shader_controls_editor import ShaderControlsEditor
    from tests.test_shader_controls import material, field

    extra = "".join(field(name, value, "Color" if name == "_dyeingColor" else "Float") for name, value in VEIL_B.items())
    text = material("SkinnedMeshTransparency", extra, name="Veil")
    authored = equipment_authored_values(text)
    assert authored["veil"]["SkinnedMeshTransparency"]["_netThread"] == [0.727]

    app = QApplication.instance() or QApplication([])
    editor = ShaderControlsEditor()
    events = []
    editor.changed.connect(events.append)
    try:
        editor.refresh((("Veil", "Veil"),), (), equipment_shader_options(text), authored)
        editor.family.setCurrentIndex(editor.family.findData("SkinnedMeshTransparency"))
        rows = {field_def.name: (enabled, spins) for field_def, enabled, spins in editor._rows}
        # Untouched fields show 0.300 / 0.727 / 0.516 / 0.901 / 0.270, not 0.5 / 0.5 / 0.65 / 0.22 / 1.
        shown = {name: [round(spin.value(), 4) for spin in spins] for name, (_enabled, spins) in rows.items()}
        assert shown["_netPitch"] == [0.3] and shown["_netThread"] == [0.727]
        assert shown["_glow"] == [0.516] and shown["_sheen"] == [0.901] and shown["_uvScale"] == [0.27]
        assert shown["_dyeingColor"] == [round(217 / 255, 4)] * 3
        assert not any(enabled.isChecked() for enabled, _spins in rows.values())
        # Showing the source number does not turn it into an override.
        assert events[-1] == (("Veil", ShaderControls("SkinnedMeshTransparency")),)
        # Without authored data the editor falls back to the definition defaults as before.
        editor.refresh((("Veil", "Veil"),), dict(events[-1]).items(), equipment_shader_options(text))
        rows = {field_def.name: spins for field_def, _enabled, spins in editor._rows}
        assert round(rows["_netThread"][0].value(), 4) == 0.5
    finally:
        editor.close()
        editor.deleteLater()
        app.processEvents()
