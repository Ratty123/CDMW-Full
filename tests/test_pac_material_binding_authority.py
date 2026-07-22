from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage

from cdmw.core.archive_model_references import (
    _parse_archive_model_sidecar_texture_bindings,
)
from cdmw.core.archive_model_texture_sidecar_rules import (
    _model_sidecar_binding_can_supply_full_base,
)
from cdmw.core.upscale_profiles import (
    parse_material_sidecar_profile,
    parse_texture_sidecar_bindings,
)
from cdmw.rendering.crimson_shader_registry import decode_crimson_texture_binding
from cdmw.models import (
    PreparedModelPreviewBatch,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.rendering.material_combiner import (
    MaterialPreviewCombinerSettings,
    combine_preview_material,
)
from cdmw.rendering.material_combiner_decode import (
    _authoritative_layer_material_response_key,
    _select_material_candidates_for_payload,
)
from cdmw.rendering.material_combiner_images import _generate_material_maps
from cdmw.rendering.material_combiner_rules import (
    _authoritative_color_blending_tint_seed,
    _layer_weight_from_parameters,
    _material_surface_category,
)
from cdmw.rendering.native_preview_material_contract import (
    _apply_nonmetal_material_scalar_limits,
    _resolved_batch_material_category,
    _resolved_batch_material_category_reason,
)
from cdmw.services.mesh_dotnet_material_channels import (
    _dotnet_material_input_channels,
    _dotnet_resolved_texture_channels,
)
from cdmw.services.mesh_dotnet_material_package import _refine_synthesized_material_contract
from cdmw.services.pac_material_graph import build_pac_material_graph_v1


_TWO_OWNER_PAC_XML = """
<SkinnedMeshProperty><Vector Name="_subMeshResources" IdBase="2000">
  <SkinnedMeshMaterialWrapper ItemID="2001" _subMeshName="CD_PHM_02_Acc_0035">
    <Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">
      <MaterialParameterTexture _name="_overlayColorTexture" ItemID="1" Index="0">
        <ResourceReferencePath_ITexture _path="character/texture/acc_0035_base.dds" />
      </MaterialParameterTexture>
      <MaterialParameterColor _name="_tintColorR" ItemID="2" Index="1" _value="#403020ff" />
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
  <SkinnedMeshMaterialWrapper ItemID="2002" _subMeshName="CD_PHM_02_Acc_0037">
    <Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">
      <MaterialParameterTexture _name="_overlayColorTexture" ItemID="3" Index="0">
        <ResourceReferencePath_ITexture _path="character/texture/acc_0037_base.dds" />
      </MaterialParameterTexture>
      <MaterialParameterColor _name="_tintColorR" ItemID="4" Index="1" _value="#d0a020ff" />
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Vector></SkinnedMeshProperty>
"""


_SWORD_0014_BLADE_PAC_XML = """
<SkinnedMeshProperty><Vector Name="_subMeshResources" IdBase="1188">
  <SkinnedMeshMaterialWrapper ItemID="1189" _subMeshName="CD_PHM_02_Blade_0014">
    <Material _materialName="SkinnedMeshStandard_Ver2"><Vector Name="_parameters">
      <MaterialParameterTexture _name="_detailDiffuseMaskR" ItemID="1" Index="0">
        <ResourceReferencePath_ITexture _path="character/texture/cd_texturelayer_003_0001.dds" />
      </MaterialParameterTexture>
      <MaterialParameterTexture _name="_detailMaskTexture" ItemID="2" Index="1">
        <ResourceReferencePath_ITexture _path="character/texture/cd_phm_02_blade_0014_mg.dds" />
      </MaterialParameterTexture>
      <MaterialParameterColor _name="_tintColorR" ItemID="3" Index="2" _value="#d6a52fff" />
      <MaterialParameterColor _name="_dyeingDetailLayerColorMaskR" ItemID="4" Index="3" _value="#f1c45fff" />
    </Vector></Material>
  </SkinnedMeshMaterialWrapper>
</Vector></SkinnedMeshProperty>
"""


def test_pac_wrapper_order_and_item_id_are_conserved_on_every_texture_binding() -> None:
    profile = parse_material_sidecar_profile(
        _TWO_OWNER_PAC_XML,
        sidecar_path="character/modelproperty/sword.pac_xml",
    )
    bindings = parse_texture_sidecar_bindings(
        _TWO_OWNER_PAC_XML,
        sidecar_path="character/modelproperty/sword.pac_xml",
    )

    assert [(slot.owner_slot_index, slot.wrapper_item_id) for slot in profile.materials] == [
        (0, "2001"),
        (1, "2002"),
    ]
    assert [(binding.owner_slot_index, binding.owner_wrapper_item_id) for binding in bindings] == [
        (0, "2001"),
        (1, "2002"),
    ]
    assert all(binding.binding_authority == "authoritative" for binding in bindings)
    assert all(binding.binding_disposition == "promoted" for binding in bindings)
    assert all(binding.source_kind == "crimson_overlay_color" for binding in bindings)


def test_pac_parameters_are_joined_by_exact_wrapper_owner_not_material_similarity() -> None:
    bindings = _parse_archive_model_sidecar_texture_bindings(
        _TWO_OWNER_PAC_XML,
        sidecar_path="character/modelproperty/sword.pac_xml",
    )
    first, second = bindings

    assert first.owner_slot_index == 0
    assert first.owner_wrapper_item_id == "2001"
    assert {parameter.texture_path for parameter in first.material_parameters if parameter.texture_path} == {
        "character/texture/acc_0035_base.dds"
    }
    assert second.owner_slot_index == 1
    assert second.owner_wrapper_item_id == "2002"
    assert {parameter.texture_path for parameter in second.material_parameters if parameter.texture_path} == {
        "character/texture/acc_0037_base.dds"
    }


def test_detail_normal_and_suffix_only_support_maps_never_become_global_slots() -> None:
    detail = decode_crimson_texture_binding(
        shader_family="SkinnedMeshStandard_Ver2",
        parameter_name="_detailNormalTexture",
        source_path="character/texture/blade_n.dds",
        sidecar_kind="pac_xml",
    )
    suffix_only = decode_crimson_texture_binding(
        shader_family="SkinnedMeshStandard_Ver2",
        parameter_name="",
        source_path="character/texture/blade_mg.dds",
        sidecar_kind="pac_xml",
    )

    assert detail["disposition"] == "layer_only"
    assert detail["source_kind"] == "crimson_layer_normal"
    assert suffix_only["disposition"] == "diagnostic_only"
    assert suffix_only["promoted_channels"] == {}


def test_authoritative_pac_layer_material_responses_survive_standard_v2_candidate_caps() -> None:
    response_inputs = tuple(
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name=f"_{role}MaterialTexture{channel.upper()}",
            source_texture_path=f"character/texture/{role}_{channel}_sp.dds",
            preview_texture_path=f"C:/audit/{role}_{channel}_sp.png",
            texture_name=f"{role}_{channel}_sp.dds",
            semantic_type="material",
            semantic_subtype="material_mask",
            material_name="CD_PHM_02_Sword_0036",
            part_name="CD_PHM_02_Sword_0036",
            shader_family="SkinnedMeshStandard_Ver2",
            sidecar_kind="pac_xml",
            parameter_declared_by="pac_xml",
            layer_role=role,
            layer_channel=channel,
            owner_slot_index=3,
            owner_wrapper_item_id="4254",
            binding_authority="authoritative",
            binding_disposition="layer_material_response",
            source_kind="crimson_layer_material_response",
        )
        for role in ("grime", "detail")
        for channel in "rgb"
    )
    control_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="material_mask",
            parameter_name="_colorBlendingMaskTexture",
            source_texture_path="character/texture/sword_ma.dds",
            semantic_type="mask",
            semantic_subtype="material_mask",
            material_name="CD_PHM_02_Sword_0036",
            shader_family="SkinnedMeshStandard_Ver2",
            sidecar_kind="pac_xml",
            binding_authority="authoritative",
            binding_disposition="layer_only",
            source_kind="crimson_color_blending_mask",
        ),
        PreviewMaterialTextureInput(
            slot_kind="detail_mask",
            parameter_name="_detailMaskTexture",
            source_texture_path="character/texture/sword_mg.dds",
            semantic_type="mask",
            semantic_subtype="detail_mask",
            material_name="CD_PHM_02_Sword_0036",
            shader_family="SkinnedMeshStandard_Ver2",
            sidecar_kind="pac_xml",
            binding_authority="authoritative",
            binding_disposition="layer_only",
            source_kind="crimson_detail_mask",
        ),
    )

    selected, culled_count = _select_material_candidates_for_payload(
        control_inputs + response_inputs,
        SimpleNamespace(
            material_name="CD_PHM_02_Sword_0036",
            texture_name="CD_PHM_02_Sword_0036",
            shader_family="SkinnedMeshStandard_Ver2",
        ),
    )

    assert selected == response_inputs
    assert culled_count == len(control_inputs)


def test_structural_body_and_foot_tokens_are_not_misclassified_as_skin() -> None:
    def category(name: str) -> str:
        return _material_surface_category(
            PreviewMaterialTextureInput(
                material_name=name,
                part_name=name,
                shader_family="SkinnedMeshStandard_Ver2",
            )
        )

    assert category("WarRobot_Foot_Armor") == "metal"
    assert category("Deerila_Golem_Body") == "generic"
    assert category("CD_PHM_00_Body") == "skin"


def test_exact_pac_layer_preserves_strong_metal_islands_inside_soft_surface(
    tmp_path: Path,
) -> None:
    material = QImage(2, 1, QImage.Format.Format_RGBA8888)
    material.setPixelColor(0, 0, QColor(0, 128, 255, 255))
    material.setPixelColor(1, 0, QColor(0, 128, 0, 255))
    common = {
        "slot_kind": "material",
        "parameter_name": "_detailMaterialMaskR",
        "source_texture_path": "character/texture/cloak_chain_sp.dds",
        "texture_name": "cloak_chain_sp.dds",
        "semantic_type": "material",
        "semantic_subtype": "material_mask",
        "material_name": "CD_PHM_00_Cloak_Chain",
        "part_name": "CD_PHM_00_Cloak_Chain",
        "shader_family": "SkinnedMeshStandard_Ver2",
        "sidecar_kind": "pac_xml",
        "parameter_declared_by": "pac_xml",
        "layer_role": "detail",
        "layer_channel": "r",
        "binding_disposition": "layer_material_response",
        "source_kind": "crimson_layer_material_response",
    }

    exact_slots, exact_paths = _generate_material_maps(
        material,
        tmp_path / "exact",
        "layer",
        decode_mode="standard_v2_material",
        input_item=PreviewMaterialTextureInput(
            **common,
            binding_authority="authoritative",
        ),
        surface_category="cloth",
        force_nonmetal_surface=True,
        flip_vertical=False,
        max_dimension=16,
    )
    guessed_slots, guessed_paths = _generate_material_maps(
        material,
        tmp_path / "guess",
        "layer",
        decode_mode="standard_v2_material",
        input_item=PreviewMaterialTextureInput(
            **common,
            binding_authority="guess",
        ),
        surface_category="cloth",
        force_nonmetal_surface=True,
        flip_vertical=False,
        max_dimension=16,
    )

    assert "metalness" in exact_slots
    exact_metal = QImage(QUrl(exact_paths[2]).toLocalFile())
    assert not exact_metal.isNull()
    assert exact_metal.pixelColor(0, 0).red() >= 120
    assert exact_metal.pixelColor(1, 0).red() == 0
    assert "metalness" not in guessed_slots
    assert guessed_paths[2] == ""


def test_only_exact_owner_qualified_pac_color_binding_can_supply_full_base() -> None:
    common = {
        "sidecar_kind": "pac_xml",
        "owner_slot_index": 0,
        "owner_wrapper_item_id": "1189",
        "shader_family": "SkinnedMeshStandard_Ver2",
        "binding_authority": "authoritative",
    }
    base = SimpleNamespace(
        **common,
        parameter_name="_overlayColorTexture",
        binding_disposition="promoted",
        source_kind="crimson_overlay_color",
    )
    layer = SimpleNamespace(
        **common,
        parameter_name="_detailDiffuseMaskR",
        binding_disposition="layer_only",
        source_kind="crimson_layer_color",
    )
    suffix_only = SimpleNamespace(
        **common,
        parameter_name="",
        binding_disposition="diagnostic_only",
        source_kind="unknown_crimson_texture",
    )

    assert _model_sidecar_binding_can_supply_full_base(base) is True
    assert _model_sidecar_binding_can_supply_full_base(layer) is False
    assert _model_sidecar_binding_can_supply_full_base(suffix_only) is False
    assert _model_sidecar_binding_can_supply_full_base(SimpleNamespace()) is True


def test_dotnet_channels_reject_cross_owner_and_layer_as_base_bindings() -> None:
    source = SimpleNamespace(
        material_slot_index=0,
        preview_native_material_overrides={},
        preview_material_texture_inputs=(
            SimpleNamespace(
                semantic_type="base",
                parameter_name="_overlayColorTexture",
                source_dds_path="owner_zero.dds",
                sidecar_kind="pac_xml",
                owner_slot_index=0,
                binding_authority="authoritative",
                binding_disposition="promoted",
            ),
            SimpleNamespace(
                semantic_type="base",
                parameter_name="_overlayColorTexture",
                source_dds_path="owner_one.dds",
                sidecar_kind="pac_xml",
                owner_slot_index=1,
                binding_authority="authoritative",
                binding_disposition="promoted",
            ),
            SimpleNamespace(
                semantic_type="base",
                parameter_name="_grimeDiffuseTextureR",
                source_dds_path="grime_layer.dds",
                sidecar_kind="pac_xml",
                owner_slot_index=0,
                layer_role="grime",
                binding_authority="authoritative",
                binding_disposition="layer_only",
            ),
        ),
    )

    channels = _dotnet_material_input_channels(source)

    assert channels["base"] == "owner_zero.dds"
    assert "owner_one.dds" not in channels.values()
    assert "grime_layer.dds" not in channels.values()


def test_dotnet_resolved_channels_remove_rebased_layer_only_color_fallback() -> None:
    source_path = "character/texture/cd_texturelayer_006_0012.dds"
    transport_path = "C:/audit/package/textures/6f06c949903f61ecc002.dds"
    legacy_guess = SimpleNamespace(
        semantic_type="color",
        slot_kind="base",
        parameter_name="",
        source_texture_path=source_path,
        source_dds_path=transport_path,
        preview_texture_path=transport_path,
        owner_slot_index=-1,
        binding_disposition="",
        source_kind="",
    )
    layer = SimpleNamespace(
        semantic_type="base",
        semantic_subtype="albedo",
        parameter_name="_detailDiffuseMaskR",
        source_texture_path=source_path,
        source_dds_path=transport_path,
        preview_texture_path=transport_path,
        sidecar_kind="pac_xml",
        owner_slot_index=2,
        binding_authority="authoritative",
        binding_disposition="layer_only",
        source_kind="crimson_layer_color",
        layer_role="detail",
        layer_channel="r",
        material_parameters=(),
    )
    source = SimpleNamespace(
        material_slot_index=2,
        texture=transport_path,
        preview_texture_dds_path=transport_path,
        preview_texture_path=transport_path,
        preview_base_texture_default_path=transport_path,
        preview_native_material_overrides={},
        preview_sidecar_shader_family="SkinnedMeshStandard_Ver2",
        preview_material_parameters=(),
        preview_material_texture_inputs=(legacy_guess, layer),
    )

    channels = _dotnet_resolved_texture_channels(source)

    assert not {"base", "albedo", "diffuse"}.intersection(channels)
    graph = build_pac_material_graph_v1(source, channels)
    assert graph["binding_conservation"]["conserved"] is True
    assert graph["binding_conservation"]["layer_as_base_bindings"] == []


def test_dotnet_resolved_channels_preserve_promoted_base_reused_by_layer() -> None:
    source_path = "character/texture/blackoil.dds"
    transport_path = "C:/audit/package/textures/blackoil.dds"
    common = {
        "semantic_type": "base",
        "source_texture_path": source_path,
        "source_dds_path": transport_path,
        "preview_texture_path": transport_path,
        "sidecar_kind": "pac_xml",
        "owner_slot_index": 0,
        "binding_authority": "authoritative",
        "material_parameters": (),
    }
    base = SimpleNamespace(
        **common,
        parameter_name="_baseColorTexture",
        binding_disposition="promoted",
        source_kind="crimson_base_color",
        layer_role="base",
    )
    detail = SimpleNamespace(
        **common,
        parameter_name="_detailDiffuseMaskR",
        binding_disposition="layer_only",
        source_kind="crimson_layer_color",
        layer_role="detail",
        layer_channel="r",
    )
    source = SimpleNamespace(
        material_slot_index=0,
        texture=transport_path,
        preview_texture_dds_path=transport_path,
        preview_texture_path=transport_path,
        preview_base_texture_default_path=transport_path,
        preview_native_material_overrides={},
        preview_sidecar_shader_family="SkinnedMeshStandard",
        preview_material_parameters=(),
        preview_material_texture_inputs=(base, detail),
    )

    channels = _dotnet_resolved_texture_channels(source)

    assert channels["base"] == transport_path
    assert channels["albedo"] == transport_path
    assert channels["diffuse"] == transport_path
    graph = build_pac_material_graph_v1(source, channels)
    assert graph["binding_conservation"]["conserved"] is True
    assert graph["binding_conservation"]["layer_as_base_bindings"] == []


def test_dotnet_layer_mask_prefers_exact_pac_color_selector_over_diffuse_mask_name() -> None:
    common = {
        "sidecar_kind": "pac_xml",
        "parameter_declared_by": "pac_xml",
        "owner_slot_index": 3,
        "owner_wrapper_item_id": "1192",
        "binding_authority": "authoritative",
        "binding_disposition": "layer_only",
        "shader_family": "SkinnedMeshEmissive_Ver2",
    }
    source = SimpleNamespace(
        material_slot_index=3,
        preview_sidecar_shader_family="SkinnedMeshEmissive_Ver2",
        preview_native_material_overrides={},
        preview_material_texture_inputs=(
            SimpleNamespace(
                **common,
                semantic_type="color",
                semantic_subtype="detail_diffuse",
                layer_role="detail",
                layer_channel="r",
                parameter_name="_detailDiffuseMaskR",
                source_dds_path="detail_diffuse.dds",
            ),
            SimpleNamespace(
                **common,
                semantic_type="mask",
                semantic_subtype="material_mask",
                layer_role="mask",
                parameter_name="_colorBlendingMaskTexture",
                source_dds_path="blade_color_selector_ma.dds",
            ),
            SimpleNamespace(
                **common,
                semantic_type="detail_mask",
                semantic_subtype="detail_mask",
                layer_role="detail_mask",
                parameter_name="_detailMaskTexture",
                source_dds_path="blade_detail_mg.dds",
            ),
        ),
    )

    channels = _dotnet_material_input_channels(source)

    assert channels["layer_mask"] == "blade_color_selector_ma.dds"
    assert channels["mask"] == "blade_color_selector_ma.dds"
    assert channels["layer_mask"] != "detail_diffuse.dds"


def test_pac_material_graph_reports_conservation_and_parameter_dispositions() -> None:
    parsed = _parse_archive_model_sidecar_texture_bindings(
        _TWO_OWNER_PAC_XML,
        sidecar_path="character/modelproperty/sword.pac_xml",
    )
    first = parsed[0]
    source = SimpleNamespace(
        material_slot_index=0,
        preview_sidecar_shader_family=first.shader_family,
        preview_material_parameters=first.material_parameters,
        preview_material_texture_inputs=(
            SimpleNamespace(**{
                name: getattr(first, name)
                for name in (
                    "parameter_name",
                    "material_name",
                    "part_name",
                    "shader_family",
                    "sidecar_kind",
                    "sidecar_path",
                    "parameter_declared_by",
                    "layer_role",
                    "layer_channel",
                    "blend_flags",
                    "owner_slot_index",
                    "owner_wrapper_item_id",
                    "binding_authority",
                    "binding_disposition",
                    "source_kind",
                    "material_parameters",
                )
            }, semantic_type="base", source_texture_path=first.texture_path),
        ),
    )

    graph = build_pac_material_graph_v1(
        source,
        {"base": first.texture_path},
        source_asset_path="character/model/weapon/sword.pac",
    )

    assert graph["schema"] == "cdmw_pac_material_graph_v1"
    assert graph["wrappers"][0]["owner_slot_index"] == 0
    assert graph["wrappers"][0]["owner_wrapper_item_id"] == "2001"
    assert graph["binding_conservation"]["conserved"] is True
    assert graph["binding_conservation"]["dropped_parameters"] == []
    dispositions = {row["parameter_name"]: row["disposition"] for row in graph["parameters"]}
    assert dispositions["_overlayColorTexture"] == "bound"
    assert dispositions["_tintColorR"] == "baked"
    assert len(graph["graph_hash"]) == 64


def test_pac_material_graph_makes_layer_as_base_a_hard_conservation_failure() -> None:
    layer = SimpleNamespace(
        semantic_type="base",
        parameter_name="_grimeDiffuseTextureR",
        source_texture_path="character/texture/grime.dds",
        sidecar_kind="pac_xml",
        owner_slot_index=0,
        owner_wrapper_item_id="2001",
        binding_authority="authoritative",
        binding_disposition="layer_only",
        source_kind="crimson_layer_color",
        layer_role="grime",
        material_parameters=(),
    )
    source = SimpleNamespace(
        material_slot_index=0,
        preview_sidecar_shader_family="SkinnedMeshStandard_Ver2",
        preview_material_parameters=(),
        preview_material_texture_inputs=(layer,),
    )

    graph = build_pac_material_graph_v1(
        source,
        {"base": "character/texture/grime.dds"},
    )

    assert graph["binding_conservation"]["conserved"] is False
    assert graph["binding_conservation"]["layer_as_base_bindings"][0]["parameter_name"] == (
        "_grimeDiffuseTextureR"
    )


def test_pac_material_graph_allows_layer_reuse_of_an_authoritative_base_resource() -> None:
    base = SimpleNamespace(
        semantic_type="base",
        parameter_name="_baseColorTexture",
        source_texture_path="character/texture/blackoil.dds",
        sidecar_kind="pac_xml",
        owner_slot_index=0,
        owner_wrapper_item_id="3037",
        binding_authority="authoritative",
        binding_disposition="promoted",
        source_kind="crimson_base_color",
        layer_role="base",
        material_parameters=(),
    )
    detail = SimpleNamespace(
        semantic_type="base",
        parameter_name="_detailDiffuseMaskR",
        source_texture_path="character/texture/blackoil.dds",
        sidecar_kind="pac_xml",
        owner_slot_index=0,
        owner_wrapper_item_id="3037",
        binding_authority="authoritative",
        binding_disposition="layer_only",
        source_kind="crimson_layer_color",
        layer_role="detail",
        material_parameters=(),
    )
    source = SimpleNamespace(
        material_slot_index=0,
        preview_sidecar_shader_family="SkinnedMeshStandard",
        preview_material_parameters=(),
        preview_material_texture_inputs=(base, detail),
    )

    graph = build_pac_material_graph_v1(
        source,
        {"base": "character/texture/blackoil.dds"},
    )

    assert graph["binding_conservation"]["conserved"] is True
    assert graph["binding_conservation"]["layer_as_base_bindings"] == []


def test_pac_material_graph_keeps_canonical_reference_when_transport_is_rebased() -> None:
    parameter = PreviewMaterialParameterInput(
        parameter_kind="texture",
        parameter_name="_detailMaterialMaskG",
        texture_path="character/texture/cd_texturelayer_003_0204_sp.dds",
    )
    binding = PreviewMaterialTextureInput(
        slot_kind="material",
        parameter_name="_detailMaterialMaskG",
        source_texture_path="character/texture/cd_texturelayer_003_0204_sp.dds",
        source_dds_path="C:/audit/package/textures/1c8d538482a24f302b90.dds",
        preview_texture_path="C:/audit/package/textures/1c8d538482a24f302b90.dds",
        semantic_type="material",
        semantic_subtype="specular",
        material_name="gauntlet_17",
        shader_family="SkinnedMeshStandard_Ver2",
        sidecar_kind="pac_xml",
        layer_role="detail",
        layer_channel="g",
        owner_slot_index=13,
        owner_wrapper_item_id="3825",
        binding_authority="authoritative",
        binding_disposition="layer_only",
        source_kind="crimson_layer_material",
        material_parameters=(parameter,),
    )
    source = SimpleNamespace(
        preview_pac_material_owner_slot_index=13,
        preview_sidecar_shader_family="SkinnedMeshStandard_Ver2",
        preview_material_parameters=(parameter,),
        preview_material_texture_inputs=(binding,),
    )

    graph = build_pac_material_graph_v1(source, {})

    assert graph["binding_conservation"]["conserved"] is True
    assert graph["binding_conservation"]["dropped_parameters"] == []
    assert graph["bindings"][0]["source_reference"] == parameter.texture_path
    assert graph["bindings"][0]["transport_reference"] == binding.source_dds_path

    promoted = build_pac_material_graph_v1(
        source,
        {"base": binding.source_dds_path},
    )
    assert promoted["binding_conservation"]["conserved"] is False
    assert promoted["binding_conservation"]["layer_as_base_bindings"] == [
        {
            "owner_slot_index": 13,
            "parameter_name": "_detailMaterialMaskG",
            "source_reference": parameter.texture_path,
        }
    ]


def test_pac_material_graph_classifies_none_texture_sentinels_as_diagnostic() -> None:
    placeholders = (
        PreviewMaterialParameterInput(
            parameter_kind="texture",
            parameter_name="_damageBlendingDiffuseTexture",
            texture_path="texture/nonetexture0x00000000.dds",
        ),
        PreviewMaterialParameterInput(
            parameter_kind="texture",
            parameter_name="_damageBlendingNormalTexture",
            texture_path="texture/nonetexture0xffffffff.dds",
        ),
    )
    source = SimpleNamespace(
        material_slot_index=6,
        preview_pac_material_owner_slot_index=6,
        preview_sidecar_shader_family="SkinnedMeshEmissive_Ver2",
        preview_material_parameters=placeholders,
        preview_material_texture_inputs=(),
    )

    graph = build_pac_material_graph_v1(source, {})

    assert graph["binding_conservation"]["conserved"] is True
    assert graph["binding_conservation"]["dropped_parameters"] == []
    assert graph["unsupported_features"] == []
    assert {
        row["parameter_name"]: row["disposition"]
        for row in graph["parameters"]
    } == {
        "_damageBlendingDiffuseTexture": "diagnostic",
        "_damageBlendingNormalTexture": "diagnostic",
    }


def test_pac_material_graph_records_declared_height_without_a_local_resource() -> None:
    height = PreviewMaterialParameterInput(
        parameter_kind="texture",
        parameter_name="_heightTexture",
        texture_path="character/texture/cd_common_coffin_01_d.dds",
    )
    base = PreviewMaterialTextureInput(
        slot_kind="base",
        parameter_name="_baseColorTexture",
        source_texture_path="character/texture/cd_common_coffin_01.dds",
        semantic_type="base",
        material_name="CD_Common_Coffin_01",
        shader_family="SkinnedMeshStandard",
        sidecar_kind="pac_xml",
        layer_role="base",
        owner_slot_index=10,
        owner_wrapper_item_id="3047",
        binding_authority="authoritative",
        binding_disposition="promoted",
        source_kind="crimson_base_color",
        material_parameters=(height,),
    )
    source = SimpleNamespace(
        preview_pac_material_owner_slot_index=10,
        preview_sidecar_shader_family="SkinnedMeshStandard",
        preview_material_parameters=(height,),
        preview_material_texture_inputs=(base,),
    )

    graph = build_pac_material_graph_v1(
        source,
        {"base": "character/texture/cd_common_coffin_01.dds"},
    )

    height_binding = next(
        row for row in graph["bindings"] if row["parameter_name"] == "_heightTexture"
    )
    height_parameter = next(
        row for row in graph["parameters"] if row["parameter_name"] == "_heightTexture"
    )
    assert height_binding["owner_slot_index"] == 10
    assert height_binding["owner_wrapper_item_id"] == "3047"
    assert height_binding["semantic"] == "height"
    assert height_binding["binding_disposition"] == "recorded"
    assert height_binding["parameter_disposition"] == "bound"
    assert height_parameter["disposition"] == "bound"
    assert graph["binding_conservation"]["conserved"] is True
    assert graph["binding_conservation"]["dropped_parameters"] == []
    assert graph["unsupported_features"] == []


def test_pac_material_graph_records_missing_normal_as_explicit_flat_fallback() -> None:
    normal = PreviewMaterialParameterInput(
        parameter_kind="texture",
        parameter_name="_normalTexture",
        texture_path="character/texture/cd_phm_12_flag1_0039_n.dds",
    )
    base = PreviewMaterialTextureInput(
        slot_kind="base",
        parameter_name="_baseColorTexture",
        source_texture_path="character/texture/cd_phm_12_flag1_0039.dds",
        semantic_type="base",
        shader_family="SkinnedMeshStandard_Ver2",
        sidecar_kind="pac_xml",
        layer_role="base",
        owner_slot_index=2,
        owner_wrapper_item_id="683",
        binding_authority="authoritative",
        binding_disposition="promoted",
        source_kind="crimson_base_color",
        material_parameters=(normal,),
    )
    source = SimpleNamespace(
        preview_pac_material_owner_slot_index=2,
        preview_sidecar_shader_family="SkinnedMeshStandard_Ver2",
        preview_material_parameters=(normal,),
        preview_material_texture_inputs=(base,),
    )

    graph = build_pac_material_graph_v1(
        source,
        {"base": "character/texture/cd_phm_12_flag1_0039.dds"},
    )

    normal_binding = next(
        row for row in graph["bindings"] if row["parameter_name"] == "_normalTexture"
    )
    normal_parameter = next(
        row for row in graph["parameters"] if row["parameter_name"] == "_normalTexture"
    )
    assert normal_binding["owner_slot_index"] == 2
    assert normal_binding["owner_wrapper_item_id"] == "683"
    assert normal_binding["semantic"] == "normal"
    assert normal_binding["binding_authority"] == "policy"
    assert normal_binding["binding_disposition"] == "fallback_flat_normal"
    assert normal_binding["source_reference"] == normal.texture_path
    assert normal_binding["transport_reference"] == ""
    assert normal_binding["promoted_channels"] == {}
    assert normal_binding["parameter_disposition"] == "bound"
    assert normal_parameter["disposition"] == "bound"
    assert graph["binding_conservation"]["conserved"] is True
    assert graph["binding_conservation"]["dropped_parameters"] == []
    assert graph["unsupported_features"] == []


def test_pac_material_graph_still_rejects_a_missing_declared_base_resource() -> None:
    base = PreviewMaterialParameterInput(
        parameter_kind="texture",
        parameter_name="_baseColorTexture",
        texture_path="character/texture/missing_required_base.dds",
    )
    source = SimpleNamespace(
        preview_pac_material_owner_slot_index=4,
        preview_sidecar_shader_family="SkinnedMeshStandard",
        preview_material_parameters=(base,),
        preview_material_texture_inputs=(),
    )

    graph = build_pac_material_graph_v1(source, {})

    assert graph["binding_conservation"]["conserved"] is False
    assert graph["binding_conservation"]["dropped_parameters"] == [
        {
            "owner_slot_index": 4,
            "owner_wrapper_item_id": "",
            "parameter_name": "_baseColorTexture",
            "texture_path": base.texture_path,
        }
    ]
    assert graph["unsupported_features"][0]["parameter_name"] == "_baseColorTexture"


def test_sword_0014_blade_keeps_gold_layer_graph_without_using_texturelayer_as_albedo() -> None:
    parsed = _parse_archive_model_sidecar_texture_bindings(
        _SWORD_0014_BLADE_PAC_XML,
        sidecar_path="character/modelproperty/cd_phm_02_sword_0014.pac_xml",
    )
    inputs = tuple(
        SimpleNamespace(
            **{
                name: getattr(binding, name)
                for name in (
                    "parameter_name",
                    "material_name",
                    "part_name",
                    "shader_family",
                    "sidecar_kind",
                    "sidecar_path",
                    "parameter_declared_by",
                    "layer_role",
                    "layer_channel",
                    "blend_flags",
                    "owner_slot_index",
                    "owner_wrapper_item_id",
                    "binding_authority",
                    "binding_disposition",
                    "source_kind",
                    "material_parameters",
                )
            },
            semantic_type="material",
            source_texture_path=binding.texture_path,
        )
        for binding in parsed
    )
    source = SimpleNamespace(
        material_slot_index=0,
        preview_sidecar_shader_family="SkinnedMeshStandard_Ver2",
        preview_material_parameters=parsed[0].material_parameters,
        preview_material_texture_inputs=inputs,
    )

    graph = build_pac_material_graph_v1(
        source,
        {},
        source_asset_path=(
            "character/model/1_pc/1_phm/weapon/2_twohandweapon/"
            "cd_phm_02_sword_0014.pac"
        ),
    )

    layer = next(
        row for row in graph["bindings"] if row["source_name"] == "cd_texturelayer_003_0001.dds"
    )
    parameters = {row["parameter_name"]: row for row in graph["parameters"]}
    assert layer["binding_disposition"] == "layer_only"
    assert layer["parameter_disposition"] == "bound"
    assert layer["source_reference"].endswith("cd_texturelayer_003_0001.dds")
    assert graph["binding_conservation"]["layer_as_base_bindings"] == []
    assert parameters["_tintColorR"]["disposition"] == "baked"
    assert parameters["_tintColorR"]["color_value"][:3] == [
        0.8392156862745098,
        0.6470588235294118,
        0.1843137254901961,
    ]
    assert parameters["_dyeingDetailLayerColorMaskR"]["disposition"] == "baked"


def test_sword_0014_color_mask_bakes_silver_field_and_local_gold_without_emissive_as_base() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        color_mask = QImage(4, 1, QImage.Format.Format_RGBA8888)
        for x, color in enumerate(
            (
                QColor(255, 0, 0, 255),
                QColor(0, 255, 0, 255),
                QColor(0, 0, 255, 255),
                QColor(0, 0, 0, 255),
            )
        ):
            color_mask.setPixelColor(x, 0, color)
        color_mask_path = root / "cd_phm_02_blade_0014_ma.png"
        assert color_mask.save(str(color_mask_path), "PNG")

        layer_paths: list[Path] = []
        for channel, layer_color in zip(
            "rgb",
            (
                QColor(96, 42, 18, 255),
                QColor(32, 112, 40, 255),
                QColor(24, 48, 128, 255),
            ),
        ):
            image = QImage(4, 1, QImage.Format.Format_RGBA8888)
            image.fill(layer_color)
            path = root / f"grime_{channel}.png"
            assert image.save(str(path), "PNG")
            layer_paths.append(path)

        emissive = QImage(4, 1, QImage.Format.Format_RGBA8888)
        emissive.fill(QColor(255, 0, 255, 255))
        emissive_path = root / "blade_emi.png"
        assert emissive.save(str(emissive_path), "PNG")

        parameters = (
            PreviewMaterialParameterInput(
                parameter_kind="color",
                parameter_name="_scratchTintColorR",
                color_value=(0.80, 0.82, 0.86),
            ),
            PreviewMaterialParameterInput(
                parameter_kind="color",
                parameter_name="_scratchTintColorG",
                color_value=(1.0, 0.76, 0.20),
            ),
            PreviewMaterialParameterInput(
                parameter_kind="color",
                parameter_name="_scratchTintColorB",
                color_value=(0.96, 0.68, 0.14),
            ),
            PreviewMaterialParameterInput(
                parameter_kind="bitflag",
                parameter_name="_colorBlendingFlag",
                value="4095",
                numeric_value=4095.0,
            ),
        )
        common = {
            "material_name": "CD_PHM_02_Blade_0014",
            "shader_family": "SkinnedMeshEmissive_Ver2",
            "sidecar_kind": "pac_xml",
            "parameter_declared_by": "pac_xml",
            "owner_slot_index": 3,
            "owner_wrapper_item_id": "1192",
            "binding_authority": "authoritative",
            "material_parameters": parameters,
            "visualized": True,
        }
        inputs = (
            PreviewMaterialTextureInput(
                **common,
                slot_kind="material",
                parameter_name="_colorBlendingMaskTexture",
                source_texture_path="character/texture/cd_phm_02_blade_0014_ma.dds",
                preview_texture_path=str(color_mask_path),
                semantic_type="mask",
                semantic_subtype="material_mask",
                binding_disposition="layer_only",
                source_kind="crimson_color_blending_mask",
            ),
            *(
                PreviewMaterialTextureInput(
                    **common,
                    slot_kind="base",
                    parameter_name=f"_grimeDiffuseTexture{channel.upper()}",
                    source_texture_path=f"character/texture/grime_{channel}.dds",
                    preview_texture_path=str(path),
                    semantic_type="color",
                    semantic_subtype="detail_diffuse",
                    layer_role="grime",
                    layer_channel=channel,
                    binding_disposition="layer_only",
                    source_kind="crimson_layer_color",
                )
                for channel, path in zip("rgb", layer_paths)
            ),
            PreviewMaterialTextureInput(
                **common,
                slot_kind="emissive",
                parameter_name="_emissiveIntensityTexture",
                source_texture_path="character/texture/blade_emi.dds",
                preview_texture_path=str(emissive_path),
                semantic_type="emissive",
                semantic_subtype="emissive",
                binding_disposition="recorded",
                source_kind="crimson_emissive_control",
            ),
        )
        payload = SimpleNamespace(
            material_name="CD_PHM_02_Blade_0014",
            source_path=(
                "character/model/1_pc/1_phm/weapon/2_twohandweapon/"
                "cd_phm_02_sword_0014.pac"
            ),
            material_texture_inputs=inputs,
            tangents_usable=False,
            texture_flip_vertical=False,
        )

        combined = combine_preview_material(
            payload,
            root / "out",
            3,
            settings=MaterialPreviewCombinerSettings(support_map_max_dimension=96),
        )

        assert "standard_v2_mask" not in combined.decode_modes
        assert "neutral_metal_base_synthesized" in "; ".join(combined.notes)
        assert "albedo synthesized:grime:r,grime:g,grime:b" in "; ".join(combined.notes)
        assert "pac_color_blending_tint_seed:r,g,b" in "; ".join(combined.notes)
        assert "pac_color_layers_modulated" in "; ".join(combined.notes)
        albedo = QImage(QUrl(combined.base_source).toLocalFile())
        assert not albedo.isNull()
        silver = albedo.pixelColor(0, 0)
        gold_g = albedo.pixelColor(1, 0)
        gold_b = albedo.pixelColor(2, 0)
        untouched = albedo.pixelColor(3, 0)
        assert max(silver.red(), silver.green(), silver.blue()) - min(
            silver.red(), silver.green(), silver.blue()
        ) <= 20
        assert silver.red() >= 175
        assert gold_g.red() - gold_g.blue() >= 45
        assert gold_b.red() - gold_b.blue() >= 45
        assert max(untouched.red(), untouched.green(), untouched.blue()) - min(
            untouched.red(), untouched.green(), untouched.blue()
        ) <= 12


def test_color_blending_region_owns_detail_layer_and_dye_tint() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        color_mask = QImage(2, 1, QImage.Format.Format_RGBA8888)
        color_mask.setPixelColor(0, 0, QColor(0, 0, 255, 255))
        color_mask.setPixelColor(1, 0, QColor(255, 0, 0, 255))
        color_mask_path = root / "blade_color_mask.png"
        assert color_mask.save(str(color_mask_path), "PNG")

        detail_mask = QImage(2, 1, QImage.Format.Format_RGBA8888)
        # Deliberately oppose the authored color-region selector. The technical
        # detail mask must not move the B material layer onto the R region.
        detail_mask.setPixelColor(0, 0, QColor(0, 0, 0, 255))
        detail_mask.setPixelColor(1, 0, QColor(0, 0, 255, 255))
        detail_mask_path = root / "blade_detail_mask.png"
        assert detail_mask.save(str(detail_mask_path), "PNG")

        detail_layer = QImage(2, 1, QImage.Format.Format_RGBA8888)
        detail_layer.fill(QColor(128, 128, 128, 255))
        detail_layer_path = root / "blade_detail_layer.png"
        assert detail_layer.save(str(detail_layer_path), "PNG")

        parameters = (
            *(
                PreviewMaterialParameterInput(
                    parameter_kind="color",
                    parameter_name=f"_tintColor{channel.upper()}",
                    color_value=(0.54, 0.42, 0.31),
                )
                for channel in "rgb"
            ),
            PreviewMaterialParameterInput(
                parameter_kind="color",
                parameter_name="_dyeingDetailLayerColorMaskB",
                color_value=(0.24, 0.40, 0.90),
            ),
            PreviewMaterialParameterInput(
                parameter_kind="byte4",
                parameter_name="_dyeingGlobalOpacity",
                value=str(0x00FF0000),
            ),
            PreviewMaterialParameterInput(
                parameter_kind="bitflag",
                parameter_name="_colorBlendingFlag",
                value="4095",
                numeric_value=4095.0,
            ),
        )
        common = {
            "material_name": "CD_PHM_02_Sword_0034",
            "shader_family": "SkinnedMeshStandard_Ver2",
            "sidecar_kind": "pac_xml",
            "parameter_declared_by": "pac_xml",
            "owner_slot_index": 2,
            "owner_wrapper_item_id": "frozen-anguish-blade",
            "binding_authority": "authoritative",
            "material_parameters": parameters,
            "visualized": True,
        }
        inputs = (
            PreviewMaterialTextureInput(
                **common,
                slot_kind="material",
                parameter_name="_colorBlendingMaskTexture",
                source_texture_path="character/texture/blade_color_mask.dds",
                preview_texture_path=str(color_mask_path),
                semantic_type="mask",
                semantic_subtype="material_mask",
                binding_disposition="layer_only",
                source_kind="crimson_color_blending_mask",
            ),
            PreviewMaterialTextureInput(
                **common,
                slot_kind="material",
                parameter_name="_detailMaskTexture",
                source_texture_path="character/texture/blade_detail_mask.dds",
                preview_texture_path=str(detail_mask_path),
                semantic_type="mask",
                semantic_subtype="detail_mask",
                binding_disposition="layer_only",
                source_kind="crimson_detail_mask",
            ),
            PreviewMaterialTextureInput(
                **common,
                slot_kind="base",
                parameter_name="_detailDiffuseMaskB",
                source_texture_path="character/texture/blade_detail_layer.dds",
                preview_texture_path=str(detail_layer_path),
                semantic_type="color",
                semantic_subtype="detail_diffuse",
                layer_role="detail",
                layer_channel="b",
                binding_disposition="layer_only",
                source_kind="crimson_layer_color",
            ),
        )
        payload = SimpleNamespace(
            material_name="CD_PHM_02_Sword_0034",
            source_path=(
                "character/model/1_pc/1_phm/weapon/2_twohandweapon/"
                "cd_phm_02_sword_0034.pac"
            ),
            material_texture_inputs=inputs,
            tangents_usable=False,
            texture_flip_vertical=False,
        )

        combined = combine_preview_material(
            payload,
            root / "out",
            6,
            settings=MaterialPreviewCombinerSettings(support_map_max_dimension=96),
        )

        albedo = QImage(QUrl(combined.base_source).toLocalFile())
        assert not albedo.isNull()
        selected = albedo.pixelColor(0, 0)
        untouched = albedo.pixelColor(1, 0)
        assert selected.blue() - selected.red() >= 35
        assert untouched.red() - untouched.blue() >= 35
        assert "pac_detail_dye_tints_masked" in "; ".join(combined.notes)


def test_authoritative_pac_detail_opacity_is_not_attenuated_by_property_blend() -> None:
    parameters = (
        PreviewMaterialParameterInput(
            parameter_kind="byte4",
            parameter_name="_dyeingGlobalOpacity",
            value=str(0x00FFFFFF),
        ),
        PreviewMaterialParameterInput(
            parameter_kind="byte4",
            parameter_name="_dyeingPropertyBlend",
            value=str(0x01010101),
        ),
        PreviewMaterialParameterInput(
            parameter_kind="bitflag",
            parameter_name="_colorBlendingFlag",
            value="4095",
            numeric_value=4095.0,
        ),
    )
    authoritative = PreviewMaterialTextureInput(
        slot_kind="base",
        parameter_name="_detailDiffuseMaskB",
        source_texture_path="character/texture/blade_detail_b.dds",
        semantic_type="color",
        semantic_subtype="detail_diffuse",
        material_name="CD_PHM_02_Sword_0034",
        shader_family="SkinnedMeshStandard_Ver2",
        sidecar_kind="pac_xml",
        parameter_declared_by="pac_xml",
        layer_role="detail",
        layer_channel="b",
        binding_authority="authoritative",
        binding_disposition="layer_only",
        source_kind="crimson_layer_color",
        material_parameters=parameters,
    )
    legacy = PreviewMaterialTextureInput(
        slot_kind="base",
        parameter_name="_detailDiffuseMaskB",
        layer_role="detail",
        layer_channel="b",
        material_parameters=parameters,
    )

    assert _layer_weight_from_parameters(authoritative, has_base=True) == 1.0
    assert _layer_weight_from_parameters(legacy, has_base=True) == 0.25


def test_color_blending_seed_uses_primary_palette_for_neutral_scratch_defaults() -> None:
    parameters = (
        PreviewMaterialParameterInput(
            parameter_kind="color",
            parameter_name="_scratchTintColorR",
            color_value=(0.902, 0.875, 0.875),
        ),
        PreviewMaterialParameterInput(
            parameter_kind="color",
            parameter_name="_scratchTintColorG",
            color_value=(0.8, 0.8, 0.8),
        ),
        PreviewMaterialParameterInput(
            parameter_kind="color",
            parameter_name="_scratchTintColorB",
            color_value=(0.8, 0.8, 0.8),
        ),
        PreviewMaterialParameterInput(
            parameter_kind="color",
            parameter_name="_tintColorG",
            color_value=(0.784, 0.643, 0.314),
        ),
        PreviewMaterialParameterInput(
            parameter_kind="color",
            parameter_name="_tintColorB",
            color_value=(0.784, 0.643, 0.314),
        ),
    )
    mask = PreviewMaterialTextureInput(
        material_name="CD_PHM_01_Sword_Handle_0059",
        shader_family="SkinnedMeshStandard_Ver2",
        sidecar_kind="pac_xml",
        parameter_declared_by="pac_xml",
        binding_authority="authoritative",
        material_parameters=parameters,
        slot_kind="material",
        parameter_name="_colorBlendingMaskTexture",
        source_texture_path="character/texture/cd_phm_01_sword_0059_ma.dds",
        semantic_type="mask",
        semantic_subtype="material_mask",
        binding_disposition="layer_only",
        source_kind="crimson_color_blending_mask",
    )

    selected_mask, tints, palette_source = _authoritative_color_blending_tint_seed((mask,))

    assert selected_mask is mask
    assert palette_source == "primary_neutral_scratch_fallback"
    assert tints == (
        (0.902, 0.875, 0.875),
        (0.784, 0.643, 0.314),
        (0.784, 0.643, 0.314),
    )


def test_color_blending_seed_keeps_chromatic_scratch_palette_over_primary() -> None:
    parameters = tuple(
        PreviewMaterialParameterInput(
            parameter_kind="color",
            parameter_name=f"_{parameter_base}{channel.upper()}",
            color_value=color,
        )
        for parameter_base, colors in (
            (
                "scratchTintColor",
                (
                    (0.859, 0.859, 0.859),
                    (1.0, 0.878, 0.639),
                    (0.859, 0.753, 0.243),
                ),
            ),
            (
                "tintColor",
                (
                    (0.231, 0.231, 0.231),
                    (0.682, 0.549, 0.329),
                    (0.384, 0.318, 0.259),
                ),
            ),
        )
        for channel, color in zip("rgb", colors)
    )
    mask = PreviewMaterialTextureInput(
        material_name="CD_PHM_02_Sword_0014_01",
        shader_family="SkinnedMeshEmissive_Ver2",
        sidecar_kind="pac_xml",
        parameter_declared_by="pac_xml",
        binding_authority="authoritative",
        material_parameters=parameters,
        slot_kind="material",
        parameter_name="_colorBlendingMaskTexture",
        source_texture_path="character/texture/cd_phm_02_blade_0014_ma.dds",
        semantic_type="mask",
        semantic_subtype="material_mask",
        binding_disposition="layer_only",
        source_kind="crimson_color_blending_mask",
    )

    selected_mask, tints, palette_source = _authoritative_color_blending_tint_seed((mask,))

    assert selected_mask is mask
    assert palette_source == "scratch"
    assert tints == (
        (0.859, 0.859, 0.859),
        (1.0, 0.878, 0.639),
        (0.859, 0.753, 0.243),
    )


def test_color_blending_seed_skips_an_earlier_non_authoritative_duplicate() -> None:
    parameters = tuple(
        PreviewMaterialParameterInput(
            parameter_kind="color",
            parameter_name=f"_scratchTintColor{channel.upper()}",
            color_value=color,
        )
        for channel, color in zip(
            "rgb",
            ((0.8, 0.8, 0.8), (0.7, 0.5, 0.2), (0.6, 0.4, 0.1)),
        )
    )
    guessed = PreviewMaterialTextureInput(
        parameter_name="_colorBlendingMaskTexture",
        binding_authority="guess",
        binding_disposition="layer_only",
        source_kind="crimson_color_blending_mask",
        material_parameters=parameters,
    )
    authoritative = PreviewMaterialTextureInput(
        parameter_name="_colorBlendingMaskTexture",
        sidecar_kind="pac_xml",
        binding_authority="authoritative",
        binding_disposition="layer_only",
        source_kind="crimson_color_blending_mask",
        material_parameters=parameters,
    )

    selected_mask, tints, palette_source = _authoritative_color_blending_tint_seed(
        (guessed, authoritative)
    )

    assert selected_mask is authoritative
    assert tints == (
        (0.8, 0.8, 0.8),
        (0.7, 0.5, 0.2),
        (0.6, 0.4, 0.1),
    )
    assert palette_source == "scratch"


def test_authoritative_layer_key_preserves_owner_slot_zero() -> None:
    key = _authoritative_layer_material_response_key(
        PreviewMaterialTextureInput(
            parameter_name="_detailMaterialR",
            shader_family="SkinnedMeshStandard_Ver2",
            owner_slot_index=0,
            owner_wrapper_item_id="1189",
            binding_authority="authoritative",
            binding_disposition="layer_material_response",
            source_kind="crimson_layer_material_response",
            layer_role="detail",
            layer_channel="r",
            source_texture_path="character/texture/detail_material_r.dds",
        ),
        "standard_v2_material",
    )

    assert key is not None
    assert key[1] == 0


def test_sword_0014_handle_stays_leather_with_zero_whole_submesh_metal_floor() -> None:
    batch = PreparedModelPreviewBatch(
        material_name="CD_PHM_02_Handle_0014",
        texture_name="CD_PHM_02_Sword_Handle_0014",
    )
    hints = {"metalness": 1.0, "specular": 1.0, "roughness": 0.05}
    contract = {
        "shader_family": "standard_v2",
        "pbr_scalar_hints": dict(hints),
        "decode_profile": {"pbr_scalar_hints": dict(hints)},
    }

    category, confidence = _resolved_batch_material_category(
        batch,
        textures={},
        dds_textures={},
        material_hints=hints,
        material_contract=contract,
        source_path=(
            "character/model/1_pc/1_phm/weapon/2_twohandweapon/"
            "cd_phm_02_sword_0014.pac"
        ),
    )
    assert category == "leather"
    assert confidence >= 0.7
    assert _apply_nonmetal_material_scalar_limits(hints, contract, category) is True
    assert hints["metalness"] == 0.0
    assert hints["roughness"] >= 0.38


def test_sword_0014_tail_mixed_metal_map_never_gets_global_metal_promotion() -> None:
    refined = _refine_synthesized_material_contract(
        {
            "shader_family": "standard_v2",
            "material_category": "metal",
            "material_category_confidence": 0.9,
            "material_category_reason": "metal:weapon_family_material_response",
            "material_response_promoted": True,
        },
        {
            "generated_channels": ["metallic", "roughness", "specular"],
            "metallic_summary": {
                "q50": 0.02,
                "q90": 0.34,
                "coverage_above_0_25": 0.19,
            },
        },
    )

    assert refined["material_category"] == "generic"
    assert refined["material_response_promoted"] is False
    assert refined["material_category_reason"] == (
        "generic:equipment_material_response_without_dominant_decoded_metal_channel"
    )


def test_dense_jacket_accessory_map_stays_per_pixel_without_global_metal_floor() -> None:
    batch = PreparedModelPreviewBatch(
        material_name="CD_PHM_00_Jacket_Acc_0079_00_02",
        texture_name="CD_PHM_00_Jacket_Acc_0079_00_02",
    )
    contract = {"shader_family": "standard_v2"}
    source_path = (
        "character/model/1_pc/1_phm/equipment/15_cloak/"
        "cd_phm_00_jacket_0079.pac"
    )
    category, confidence = _resolved_batch_material_category(
        batch,
        textures={},
        dds_textures={},
        material_hints={},
        material_contract=contract,
        source_path=source_path,
    )
    reason = _resolved_batch_material_category_reason(
        category,
        batch,
        textures={},
        dds_textures={},
        material_hints={},
        material_contract=contract,
        source_path=source_path,
    )
    refined = _refine_synthesized_material_contract(
        {
            "shader_family": "standard_v2",
            "material_category": category,
            "material_category_confidence": confidence,
            "material_category_reason": reason,
            "material_response_promoted": False,
        },
        {
            "generated_channels": ["metallic", "roughness", "specular"],
            "metallic_summary": {
                "q50": 0.369,
                "q90": 0.486,
                "coverage_above_0_25": 0.651,
            },
        },
        source_asset_path=source_path,
    )

    assert category == "generic"
    assert confidence >= 0.7
    assert reason == "generic:mixed_soft_accessory_token"
    assert refined["material_category"] == "generic"
    assert refined["material_response_promoted"] is False
    assert refined["material_category_reason"] == reason


def test_sword_0014_acc_0035_cannot_receive_acc_0037_base_texture() -> None:
    bindings = _parse_archive_model_sidecar_texture_bindings(
        _TWO_OWNER_PAC_XML,
        sidecar_path="character/modelproperty/cd_phm_02_sword_0014.pac_xml",
    )
    owner_0035 = bindings[0]
    source = SimpleNamespace(
        material_slot_index=0,
        preview_native_material_overrides={},
        preview_material_texture_inputs=tuple(
            SimpleNamespace(
                semantic_type="base",
                parameter_name=binding.parameter_name,
                source_dds_path=binding.texture_path,
                sidecar_kind="pac_xml",
                owner_slot_index=binding.owner_slot_index,
                owner_wrapper_item_id=binding.owner_wrapper_item_id,
                binding_authority="authoritative",
                binding_disposition="promoted",
                source_kind="crimson_overlay_color",
            )
            for binding in bindings
        ),
    )

    channels = _dotnet_material_input_channels(source)

    assert owner_0035.owner_slot_index == 0
    assert channels["base"].endswith("acc_0035_base.dds")
    assert "acc_0037_base.dds" not in channels.values()
