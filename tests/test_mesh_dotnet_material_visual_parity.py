from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput
from cdmw.services import mesh_dotnet_material_state
from cdmw.services.mesh_dotnet_experiment import mesh_dotnet_material_state_payload
from cdmw.services.mesh_dotnet_material_bindings import apply_dotnet_native_material_batch_bindings
from tests.test_mesh_dotnet_experiment import _mesh


def test_textured_material_carries_representative_preview_color_as_inactive_base_tint(tmp_path: Path) -> None:
    base = tmp_path / "lantern_base.dds"
    base.write_bytes(b"base")
    mesh = _mesh()
    lantern = mesh.submeshes[0]
    lantern.preview_color = (0.68, 0.60, 0.49)
    lantern.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(semantic_type="base", source_dds_path=str(base)),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="textured-preview-color",
        edit_revision=0,
        generation=1,
    )

    parameters = payload["submeshes"][0]["parameters"]
    assert parameters["base_tint_color"] == [0.68, 0.60, 0.49]
    assert parameters["base_tint_strength"] == 0.0
    assert "texture_tint" not in parameters


def test_textured_material_transports_explicit_texture_tint(tmp_path: Path) -> None:
    base = tmp_path / "shield_base.dds"
    base.write_bytes(b"base")
    mesh = _mesh()
    shield = mesh.submeshes[0]
    shield.preview_color = (0.57, 0.39, 0.29)
    shield.preview_texture_tint = (0.73, 0.44, 0.24)
    shield.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(semantic_type="base", source_dds_path=str(base)),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="textured-explicit-tint",
        edit_revision=0,
        generation=1,
    )

    parameters = payload["submeshes"][0]["parameters"]
    assert parameters["base_tint_color"] == [0.57, 0.39, 0.29]
    assert parameters["base_tint_strength"] == 0.85
    assert parameters["texture_tint"] == [0.73, 0.44, 0.24]


def test_imported_gltf_base_color_factor_is_only_multiplicative_texture_tint(
    tmp_path: Path,
) -> None:
    base = tmp_path / "gltf_base.png"
    base.write_bytes(b"base")
    mesh = _mesh()
    material = mesh.submeshes[0]
    material.preview_color = (0.50, 0.25, 1.0)
    material.preview_texture_tint = (0.50, 0.25, 1.0)
    material.preview_texture_path = str(base)
    material.preview_material_parameters = (
        PreviewMaterialParameterInput(
            parameter_kind="color",
            parameter_name="_baseColorFactor",
            color_value=(0.50, 0.25, 1.0),
        ),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="gltf-base-color-factor",
        edit_revision=0,
        generation=1,
    )

    parameters = payload["submeshes"][0]["parameters"]
    assert parameters["base_tint_color"] == [0.50, 0.25, 1.0]
    assert parameters["base_tint_strength"] == 0.0
    assert parameters["texture_tint"] == [0.50, 0.25, 1.0]


def test_native_material_batch_binding_preserves_explicit_texture_tint(tmp_path: Path) -> None:
    base = tmp_path / "reference_base.dds"
    base.write_bytes(b"base")
    model = _mesh()
    target = model.submeshes[0]

    assert mesh_dotnet_material_state.apply_dotnet_native_material_batch_binding(
        target,
        {
            "dds_textures": {"base": {"source_path": str(base)}},
            "base_color": [0.57, 0.39, 0.29],
            "base_tint_strength": 0.35,
            "material_category": "metal",
            "material_category_confidence": 0.91,
            "material_category_reason": "metal:authoritative-test-evidence",
            "material_response_promoted": True,
            "texture_tint": [0.73, 0.44, 0.24],
        },
    )
    payload = mesh_dotnet_material_state_payload(
        model,
        session_id="native-reference-tint",
        edit_revision=0,
        generation=1,
    )

    assert target.preview_texture_tint == (0.73, 0.44, 0.24)
    binding = payload["submeshes"][0]
    parameters = binding["parameters"]
    assert target.preview_color == (0.57, 0.39, 0.29)
    assert binding["material_category"] == "metal"
    assert binding["material_category_confidence"] == 0.91
    assert binding["material_category_reason"] == "metal:authoritative-test-evidence"
    assert binding["material_response_promoted"] is True
    assert parameters["base_tint_color"] == [0.57, 0.39, 0.29]
    assert parameters["base_tint_strength"] == 0.35
    assert parameters["base_tint_metallic"] is True
    assert parameters["texture_tint"] == [0.73, 0.44, 0.24]


def test_native_material_hints_remain_distinct_from_texture_transforms(tmp_path: Path) -> None:
    roughness = tmp_path / "reference_roughness.dds"
    roughness.write_bytes(b"roughness")
    model = _mesh()
    target = model.submeshes[0]
    target.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(semantic_type="roughness", source_dds_path=str(roughness)),
    )

    assert mesh_dotnet_material_state.apply_dotnet_native_material_batch_binding(
        target,
        {
            "roughness": 0.38,
            "metalness": 0.72,
            "specular": 0.24,
            "native_material_hints": {
                "roughness": 0.38,
                "metalness": 0.72,
                "specular": 0.24,
            },
        },
    )
    payload = mesh_dotnet_material_state_payload(
        model,
        session_id="native-reference-hints",
        edit_revision=0,
        generation=1,
    )

    parameters = payload["submeshes"][0]["parameters"]
    assert parameters["roughness_hint"] == 0.38
    assert parameters["metalness_hint"] == 0.72
    assert parameters["specular_hint"] == 0.24
    assert "roughness" not in parameters
    assert "roughness_scale" not in parameters
    assert "metalness" not in parameters
    assert "metalness_scale" not in parameters
    assert "specular" not in parameters


def test_native_material_hint_presence_distinguishes_omitted_and_explicit_zero() -> None:
    model = _mesh()
    target = model.submeshes[0]

    assert mesh_dotnet_material_state.apply_dotnet_native_material_batch_binding(
        target,
        {
            "roughness": 0.0,
            "roughness_hint_present": False,
            "metalness": 0.0,
            "metalness_hint_present": False,
            "specular": 0.24,
            "specular_hint_present": True,
            "native_material_hints": {
                "roughness": 0.0,
                "roughness_hint_present": False,
                "metalness": 0.0,
                "metalness_hint_present": False,
                "specular": 0.24,
                "specular_hint_present": True,
            },
        },
    )
    specular_only = mesh_dotnet_material_state_payload(
        model,
        session_id="specular-only-hint",
        edit_revision=0,
        generation=1,
    )["submeshes"][0]["parameters"]

    assert "roughness_hint" not in specular_only
    assert "metalness_hint" not in specular_only
    assert specular_only["specular_hint"] == 0.24

    target.preview_native_material_overrides["roughness_hint_present"] = True
    target.preview_native_material_overrides["native_material_hints"]["roughness_hint_present"] = True
    explicit_zero = mesh_dotnet_material_state_payload(
        model,
        session_id="explicit-zero-roughness-hint",
        edit_revision=1,
        generation=2,
    )["submeshes"][0]["parameters"]

    assert explicit_zero["roughness_hint"] == 0.0
    assert explicit_zero["specular_hint"] == 0.24


def test_native_emissive_color_authority_survives_numeric_and_pac_hex_transport() -> None:
    model = _mesh()
    target = model.submeshes[0]

    assert mesh_dotnet_material_state.apply_dotnet_native_material_batch_binding(
        target,
        {
            "emissive_color": [0.35, 0.68, 1.0],
            "emissive_color_authoritative": False,
            "emissive_intensity": 4.0,
        },
    )
    fallback = mesh_dotnet_material_state_payload(
        model,
        session_id="fallback-emissive-color",
        edit_revision=0,
        generation=1,
    )["submeshes"][0]["parameters"]
    assert fallback["emissive_color"] == [0.35, 0.68, 1.0]
    assert fallback["emissive_color_authoritative"] is False

    target.preview_native_material_overrides = {
        "emissive_color": "4e9838ff",
        "emissive_color_authoritative": True,
        "emissive_intensity": 1.0,
    }
    authoritative = mesh_dotnet_material_state_payload(
        model,
        session_id="authoritative-emissive-color",
        edit_revision=1,
        generation=2,
    )["submeshes"][0]["parameters"]
    assert authoritative["emissive_color"] == pytest.approx([0x4E / 255, 0x98 / 255, 0x38 / 255])
    assert authoritative["emissive_color_authoritative"] is True


def test_zero_non_authoritative_emissive_fallback_does_not_promote_generic_native_batch() -> None:
    model = _mesh()
    model.path = "character/model/object/machine_part.pac"
    target = model.submeshes[0]
    target.name = "machine_part"
    target.material = "machine_part"
    target.texture = ""
    assert apply_dotnet_native_material_batch_bindings(
        model,
        (
            {
                "editor_identity": {"source_local_submesh_index": 0},
                "material_shader_family": "generic",
                "emissive_color": [0.35, 0.68, 1.0],
                "emissive_color_authoritative": False,
                "emissive_intensity": 0.0,
            },
        ),
    ) == 1

    binding = mesh_dotnet_material_state_payload(
        model,
        session_id="inactive-emissive-fallback",
        edit_revision=0,
        generation=1,
    )["submeshes"][0]

    assert binding["shader_family"] == "generic"
    assert binding["shader_family_source"] == "unresolved"
    assert binding["parameters"]["emissive_intensity"] == 0.0
    assert binding["parameters"]["emissive_color_authoritative"] is False

    target.preview_native_material_overrides = {
        "material_shader_family": "generic",
        "emissive_color": [0.0, 0.0, 0.0],
        "emissive_color_authoritative": True,
        "emissive_intensity": 0.0,
    }
    black_binding = mesh_dotnet_material_state_payload(
        model,
        session_id="black-emissive-factor",
        edit_revision=1,
        generation=2,
    )["submeshes"][0]

    assert black_binding["shader_family"] == "generic"
    assert black_binding["shader_family_source"] == "unresolved"

    target.preview_native_material_overrides = {
        "material_shader_family": "generic",
        "emissive_color": [0.1, 0.0, 0.0],
        "emissive_intensity": 0.0,
    }
    color_binding = mesh_dotnet_material_state_payload(
        model,
        session_id="visible-emissive-color",
        edit_revision=2,
        generation=3,
    )["submeshes"][0]

    assert color_binding["shader_family"] == "emissive"
    assert color_binding["shader_family_source"] == "material_identity_inference"

    target.preview_native_material_overrides = {
        "material_shader_family": "generic",
        "emissive_color": [0.35, 0.68, 1.0],
        "emissive_color_authoritative": False,
        "emissive_intensity": 4.0,
    }
    active_binding = mesh_dotnet_material_state_payload(
        model,
        session_id="active-emissive-intensity",
        edit_revision=3,
        generation=4,
    )["submeshes"][0]

    assert active_binding["shader_family"] == "emissive"
    assert active_binding["shader_family_source"] == "material_identity_inference"


def test_native_material_batches_preserve_per_submesh_category_without_name_inference() -> None:
    model = _mesh()
    model.submeshes.append(_mesh().submeshes[0])

    applied = apply_dotnet_native_material_batch_bindings(
        model,
        (
            {
                "editor_identity": {"source_local_submesh_index": 1},
                "base_color": [0.31, 0.42, 0.53],
                "base_tint_strength": 0.6,
                "material_category": "leather",
            },
            {
                "editor_identity": {"source_local_submesh_index": 0},
                "base_color": [0.71, 0.62, 0.48],
                "base_tint_strength": 0.4,
                "material_category": "metal",
            },
        ),
    )
    payload = mesh_dotnet_material_state_payload(
        model,
        session_id="per-submesh-category",
        edit_revision=0,
        generation=1,
    )

    assert applied == 2
    by_index = {row["submesh_index"]: row["parameters"] for row in payload["submeshes"]}
    assert by_index[0]["base_tint_metallic"] is True
    assert by_index[1]["base_tint_metallic"] is False


def test_bc4_emissive_dds_is_tagged_as_scalar_mask(tmp_path: Path) -> None:
    emissive = tmp_path / "rune_emi.dds"
    emissive.write_bytes(b"bc4")
    mesh = _mesh()
    mesh.submeshes[0].preview_emissive_texture_dds_path = str(emissive)

    with patch.object(
        mesh_dotnet_material_state,
        "inspect_dds_native_path",
        return_value=SimpleNamespace(compressed_family="bc4", format_name="BC4_UNORM"),
    ):
        mesh_dotnet_material_state._dotnet_emissive_texture_is_scalar_mask_cached.cache_clear()
        payload = mesh_dotnet_material_state_payload(
            mesh,
            session_id="bc4-emissive",
            edit_revision=0,
            generation=1,
        )
        mesh_dotnet_material_state._dotnet_emissive_texture_is_scalar_mask_cached.cache_clear()

    assert payload["submeshes"][0]["parameters"]["emissive_scalar_mask"] is True


def test_emissive_texture_distinguishes_undeclared_intensity_from_explicit_zero(tmp_path: Path) -> None:
    emissive = tmp_path / "rune_emissive.png"
    emissive.write_bytes(b"emissive")
    mesh = _mesh()
    material = mesh.submeshes[0]
    material.preview_emissive_texture_path = str(emissive)

    texture_default_payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="emissive-texture-default",
        edit_revision=0,
        generation=1,
    )
    material.preview_native_material_overrides = {"emissive_intensity": 0.0}
    explicit_zero_payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="emissive-explicit-zero",
        edit_revision=1,
        generation=2,
    )

    texture_default = texture_default_payload["submeshes"][0]["parameters"]
    explicit_zero = explicit_zero_payload["submeshes"][0]["parameters"]
    assert "emissive_intensity" not in texture_default
    assert explicit_zero["emissive_intensity"] == 0.0


def test_emissive_scalar_mask_refreshes_and_emits_false_after_same_path_format_change(tmp_path: Path) -> None:
    emissive = tmp_path / "rune_emi.dds"
    emissive.write_bytes(b"bc4")
    mesh = _mesh()
    mesh.submeshes[0].preview_emissive_texture_dds_path = str(emissive)

    with patch.object(
        mesh_dotnet_material_state,
        "inspect_dds_native_path",
        side_effect=(
            SimpleNamespace(compressed_family="bc4", format_name="BC4_UNORM"),
            SimpleNamespace(compressed_family="bc7", format_name="BC7_UNORM"),
        ),
    ) as inspect:
        mesh_dotnet_material_state._dotnet_emissive_texture_is_scalar_mask_cached.cache_clear()
        scalar_payload = mesh_dotnet_material_state_payload(
            mesh,
            session_id="resident-emissive-format",
            edit_revision=1,
            generation=1,
        )
        emissive.write_bytes(b"bc7-rgb-replacement")
        rgb_payload = mesh_dotnet_material_state_payload(
            mesh,
            session_id="resident-emissive-format",
            edit_revision=2,
            generation=2,
        )
        mesh_dotnet_material_state._dotnet_emissive_texture_is_scalar_mask_cached.cache_clear()

    assert scalar_payload["submeshes"][0]["parameters"]["emissive_scalar_mask"] is True
    assert rgb_payload["submeshes"][0]["parameters"]["emissive_scalar_mask"] is False
    assert inspect.call_count == 2


def test_archive_green_up_normal_maps_carry_the_directx_green_inversion_policy(tmp_path: Path) -> None:
    normal = tmp_path / "archive_normal.dds"
    normal.write_bytes(b"normal")
    mesh = _mesh()
    mesh.submeshes[0].preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            semantic_type="normal",
            source_dds_path=str(normal),
            normal_space="green_up",
            confidence="resolved",
        ),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="archive-normal-y",
        edit_revision=0,
        generation=1,
    )

    assert payload["submeshes"][0]["normal_y_policy"] == "invert_green_for_directx"


def test_directx_normal_maps_preserve_green_channel(tmp_path: Path) -> None:
    normal = tmp_path / "directx_normal.dds"
    normal.write_bytes(b"normal")
    mesh = _mesh()
    mesh.submeshes[0].preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            semantic_type="normal",
            source_dds_path=str(normal),
            normal_space="directx",
        ),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="directx-normal-y",
        edit_revision=0,
        generation=1,
    )

    assert payload["submeshes"][0]["normal_y_policy"] == "preserve"
