"""Owned fixtures for the PAC XML fragment and vertex-gate contracts."""
from types import SimpleNamespace

import pytest

from cdmw.core.pbd_cloth import (
    build_cloth_preview_data,
    parse_pbd_material_settings,
    parse_pbd_sidecar_hints,
)
from cdmw.models import ModelPreviewData, ModelPreviewMesh


def _variant(index: int, profile: str, part: str = "cloth_panel") -> str:
    return f'''<ModelProperty Index="{index}">
      <SkinnedMeshProperty _pbdSimulationMaterialName="{profile}">
        <Vector Name="_subMeshResources">
          <SkinnedMeshMaterialWrapper _subMeshName="{part}">
            <Material _materialName="SkinnedMeshStandard_Ver2" />
          </SkinnedMeshMaterialWrapper>
        </Vector>
      </SkinnedMeshProperty>
    </ModelProperty>'''


def _fragments(*variants: str) -> str:
    return '\ufeff<?xml version="1.0"?>\n<SkinnedMeshPropertyCommon/>' + (
        "<ModelPropertyList>" + "".join(variants) + "</ModelPropertyList>"
    )


def _model_and_source(*, part: str = "cloth_panel", stride: int = 40):
    positions = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)]
    model = ModelPreviewData(path="owned.pac", meshes=[ModelPreviewMesh(
        material_name="SkinnedMeshStandard_Ver2", positions=positions,
        indices=[0, 1, 2], source_submesh_index=0,
    )])
    parsed = SimpleNamespace(submeshes=[SimpleNamespace(
        name=part, material="SkinnedMeshStandard_Ver2", source_vertex_stride=stride,
        source_vertex_offsets=(0, 40, 80),
    )])
    return model, parsed


def test_fragment_profiles_stay_on_named_parts_and_variants():
    hints = parse_pbd_sidecar_hints(_fragments(
        _variant(0, "Lower_Fabric"), _variant(1, "Lower_Leather", "cloth_panel_2"),
    ))
    assert [(h.variant_index, h.submesh_name, h.simulation_material_name) for h in hints] == [
        ("0", "cloth_panel", "Lower_Fabric"), ("1", "cloth_panel_2", "Lower_Leather"),
    ]
    assert not parse_pbd_sidecar_hints('<Common/><ModelProperty><Broken>')


def test_explicit_empty_profile_does_not_inherit_parent_profile():
    xml = '''<Root _pbdSimulationMaterialName="Lower_Fabric">
      <Part _subMeshName="cloth_panel" _pbdSimulationMaterialName=""/>
    </Root>'''
    assert not parse_pbd_sidecar_hints(xml)


def test_named_profile_cannot_attach_to_other_part_with_same_shader_material():
    hints = parse_pbd_sidecar_hints(_fragments(_variant(0, "Lower_Fabric")))
    model, parsed = _model_and_source(part="unrelated_cloth")
    assert build_cloth_preview_data(model, parsed, hints, {}) is None


@pytest.mark.parametrize("other", ["Upper_Fabric", "", "UnresolvedPhysics"])
def test_conflicting_variant_profiles_do_not_choose_first_xml_entry(other):
    hints = parse_pbd_sidecar_hints(_fragments(
        _variant(0, "Lower_Fabric"), _variant(1, other),
    ))
    model, parsed = _model_and_source()
    assert build_cloth_preview_data(model, parsed, hints, {}) is None


@pytest.mark.parametrize("gate, stride, expected", [(0, 40, True), (63, 40, False), (255, 40, False), (0, 32, False)])
def test_render_cloth_batch_requires_a_verified_vertex_gate(gate, stride, expected):
    hints = parse_pbd_sidecar_hints(_fragments(_variant(0, "Lower_Fabric")))
    model, parsed = _model_and_source(stride=stride)
    source = bytearray(120)
    for offset in (39, 79, 119):
        source[offset] = gate
    result = build_cloth_preview_data(model, parsed, hints, {}, source_data=bytes(source))
    assert (result is not None) is expected
    assert build_cloth_preview_data(model, parsed, hints, {}, source_data=b"") is None


@pytest.mark.parametrize("mode, enabled", [("NoCollision", False), ("Normal", True), ("Advanced", True), ("Ultra", True)])
def test_authored_collision_mode_overrides_legacy_boolean_and_defaults(mode, enabled):
    settings = parse_pbd_material_settings(
        f'<PbdMaterial CollisionMode="{mode}" CollisionCheck="{str(not enabled).lower()}"/>',
        material_name="Lower_Fabric",
    )
    assert settings.collision_mode == mode
    assert settings.collision_enabled is enabled


@pytest.mark.parametrize("attached_first", [False, True])
def test_attached_cloth_values_do_not_replace_parent_spline_settings(attached_first):
    parent = ("<SimulationMode>spline</SimulationMode><Damping>0.8</Damping>"
              "<StretchingStiffness>0.4</StretchingStiffness><Gravity>-1</Gravity>")
    attached = ("<AttachedCloth><SimulationMode>cloth</SimulationMode><Damping>0.02</Damping>"
                "<StretchingStiffness>0.1025</StretchingStiffness><Gravity>-10</Gravity></AttachedCloth>")
    settings = parse_pbd_material_settings(
        "<SimulationParameters>" + (attached + parent if attached_first else parent + attached)
        + "</SimulationParameters>", material_name="BG_AttachedSpline",
    )
    assert settings.simulation_kind == "spline"
    assert settings.damping == pytest.approx(0.8)
    assert settings.stretching_stiffness == pytest.approx(0.4)
    assert settings.gravity == -1


def test_archive_attachment_passes_raw_gate_to_cloth_builder(monkeypatch):
    from cdmw.core import archive_model_texture_pbd as module

    monkeypatch.setattr(module, "_collect_archive_model_pbd_sidecar_texts", lambda *a, **k: [
        ("owned.pac_xml", _fragments(_variant(0, "Lower_Fabric"))),
    ])
    monkeypatch.setattr(module, "_read_archive_pbd_config_text", lambda *a, **k: "")
    model, parsed = _model_and_source()
    notes = module._attach_pbd_cloth_preview_to_model_preview(
        SimpleNamespace(extension=".pac"), model, parsed,
        archive_entries_by_basename={}, source_data=bytes([255]) * 120,
    )
    assert model.cloth_preview is None
    assert "no recovered PAC submesh" in notes[0]
    module._attach_pbd_cloth_preview_to_model_preview(
        SimpleNamespace(extension=".pac"), model, parsed,
        archive_entries_by_basename={}, source_data=bytes(120),
    )
    assert model.cloth_preview is not None
