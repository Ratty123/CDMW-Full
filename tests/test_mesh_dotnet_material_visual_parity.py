from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    parameters = payload["submeshes"][0]["parameters"]
    assert target.preview_color == (0.57, 0.39, 0.29)
    assert parameters["base_tint_color"] == [0.57, 0.39, 0.29]
    assert parameters["base_tint_strength"] == 0.35
    assert parameters["base_tint_metallic"] is True
    assert parameters["texture_tint"] == [0.73, 0.44, 0.24]


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
