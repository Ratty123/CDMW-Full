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


def material(shader="SkinnedMeshStandard", extra="", name="Blade"):
    block = plain_material_xml(PlainMaterial(base="texture/base.dds", normal="texture/normal.dds"))
    block = block.replace('SkinnedMeshStandard"', shader + '"')
    block = block.replace('</Vector>', extra + '</Vector>', 1)
    return f'<SkinnedMeshMaterialWrapper _subMeshName="{name}">{block}</SkinnedMeshMaterialWrapper>'


def field(name, value, kind="Float"):
    return f'<MaterialParameter{kind} StringItemID="{name}" ItemID="123" _name="{name}" _value="{value}" Index="50"/>'


def choice(shader="SkinnedMeshWing", **values):
    return ShaderControls(shader, tuple((name, (value,) if isinstance(value, (int, float)) else value) for name, value in values.items()))
