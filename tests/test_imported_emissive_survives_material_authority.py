"""An imported material's emissive survives the Material Authority parameter update.

The wolf-sword gem: a glTF material with `baseColorFactor` green, `emissiveFactor`
red, and no textures at all. It rendered flat green. Every stage that was checked
first was correct -- import, channel resolution, manifest, publication, the C#
reader, the shader's factor-only path -- and the reason it was correct at every
one of them is that the emissive really did reach the renderer.

What killed it was the message after. The Material Authority bridge sends a
`material_parameter_update` covering every submesh, and for a submesh it believes
has no emissive it sends `emissive_intensity: null, emissive_color: null`, which
the C# reader takes as "explicitly clear". It believed the gem had none because
`parsed_mesh_to_preview_model` copied every preview field onto the preview mesh
except `preview_material_parameters` -- the only place a texture-less material's
factors live -- so `source_emissive_strength` found nothing.

The colour had a second gap: `evaluate_material_parameters` resolved intensity
from the source but never the colour, so once intensity was kept the glow would
have been white.
"""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.core.archive_mesh_import_scene_preview import parsed_mesh_to_preview_model
from cdmw.domain.textures.material_parameters import (
    evaluate_material_parameters,
    material_parameter_renderer_overrides,
    source_emissive_color,
    source_emissive_strength,
)
from cdmw.models import PreviewMaterialParameterInput
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    resident_material_parameter_groups_for_model,
)


def _gem_submesh(name: str = "Broken_sword_Gem_inside_0") -> SubMesh:
    submesh = SubMesh(
        name=name,
        material="Gem_inside",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
    )
    submesh.preview_color = (0.0, 1.0, 0.791)
    submesh.preview_material_parameters = (
        PreviewMaterialParameterInput(
            parameter_kind="color", parameter_name="_baseColorFactor", value="#00ffca", color_value=(0.0, 1.0, 0.791)
        ),
        PreviewMaterialParameterInput(
            parameter_kind="color", parameter_name="_emissiveColor", value="#ff0000", color_value=(1.0, 0.0, 0.0)
        ),
        PreviewMaterialParameterInput(
            parameter_kind="float", parameter_name="_emissiveIntensity", value="10.000000", numeric_value=10.0
        ),
    )
    return submesh


def _plain_submesh() -> SubMesh:
    return SubMesh(
        name="Broken_sword_lambert1_0",
        material="lambert1",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
    )


def _mesh() -> ParsedMesh:
    return ParsedMesh(path="scene.gltf", format="gltf", submeshes=[_plain_submesh(), _gem_submesh()])


def test_the_preview_mesh_carries_the_texture_less_material_parameters() -> None:
    preview = parsed_mesh_to_preview_model(_mesh())

    gem = preview.meshes[1]
    names = [parameter.parameter_name for parameter in gem.preview_material_parameters]
    assert "_emissiveColor" in names
    assert "_emissiveIntensity" in names
    # A submesh with nothing declared stays empty rather than gaining a tuple.
    assert preview.meshes[0].preview_material_parameters == ()


def test_the_imported_emissive_is_readable_from_the_preview_mesh() -> None:
    preview = parsed_mesh_to_preview_model(_mesh())

    assert source_emissive_strength(preview.meshes[1]) == 10.0
    assert source_emissive_color(preview.meshes[1]) == (1.0, 0.0, 0.0)
    assert source_emissive_strength(preview.meshes[0]) is None
    assert source_emissive_color(preview.meshes[0]) == ()


def test_the_material_authority_update_keeps_the_gems_glow() -> None:
    """The message that used to clear it now carries it."""
    preview = parsed_mesh_to_preview_model(_mesh())

    groups = {
        tuple(group["source_submesh_indices"]): group
        for group in resident_material_parameter_groups_for_model({}, preview, profile=None)
    }

    gem = groups[(1,)]
    assert gem["emissive_intensity"] == 10.0
    assert gem["emissive_color"] == [1.0, 0.0, 0.0]
    assert gem["material_role"] == "emissive"
    # The blade genuinely has no emissive; clearing it there is correct.
    plain = groups[(0,)]
    assert plain["emissive_intensity"] is None
    assert plain["emissive_color"] is None


def test_the_imported_colour_is_a_fallback_below_a_part_pick() -> None:
    preview = parsed_mesh_to_preview_model(_mesh())
    gem = preview.meshes[1]

    imported = material_parameter_renderer_overrides(
        evaluate_material_parameters(None, source_slot=gem, emissive_role=True)
    )
    picked = material_parameter_renderer_overrides(
        evaluate_material_parameters(
            None,
            source_slot=gem,
            part_adjustment=SimpleNamespace(emissive_color_rgb=(0, 0, 255)),
            emissive_role=True,
        )
    )

    assert imported["emissive_color"] == [1.0, 0.0, 0.0]
    assert picked["emissive_color"] == [0.0, 0.0, 1.0]


def test_the_imported_colour_outranks_the_profiles_global_accent_glow() -> None:
    preview = parsed_mesh_to_preview_model(_mesh())
    profile = SimpleNamespace(accent_glow_color_rgb=(0.0, 1.0, 1.0))

    overrides = material_parameter_renderer_overrides(
        evaluate_material_parameters(profile, source_slot=preview.meshes[1], emissive_role=True)
    )

    # The profile setting is a global default; a model declaring its own
    # emissive colour is more specific than that.
    assert overrides["emissive_color"] == [1.0, 0.0, 0.0]


def test_a_hex_only_colour_parameter_is_still_read() -> None:
    source = SimpleNamespace(
        preview_material_parameters=(
            PreviewMaterialParameterInput(parameter_kind="color", parameter_name="_emissiveColor", value="#00ff00"),
        )
    )

    assert source_emissive_color(source) == (0.0, 1.0, 0.0)
