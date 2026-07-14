from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.models import ModelPreviewData, ModelPreviewMesh, PreviewMaterialTextureInput
from cdmw.modding.asset_replacement import infer_cd_texture_role_from_path
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services import mesh_dotnet_experiment, mesh_dotnet_material_state
from cdmw.services.mesh_dotnet_material_state import copy_dotnet_preview_material_bindings
from cdmw.services.mesh_dotnet_experiment import (
    build_mesh_dotnet_experiment_package,
    mesh_dotnet_material_input_signature,
    mesh_dotnet_material_state_payload,
)
from tests.test_mesh_dotnet_experiment import _mesh


def test_dotnet_material_signature_changes_only_with_material_inputs(tmp_path: Path) -> None:
    mesh = _mesh()
    texture = tmp_path / "skin.png"
    texture.write_bytes(b"first")
    mesh.submeshes[0].preview_texture_path = str(texture)

    first = mesh_dotnet_material_input_signature(mesh)
    mesh.submeshes[0].vertices[0] = (9.0, 8.0, 7.0)
    assert mesh_dotnet_material_input_signature(mesh) == first

    texture.write_bytes(b"changed-content")
    assert mesh_dotnet_material_input_signature(mesh) != first


def test_dotnet_material_state_payload_is_deterministic_and_does_not_build_package(
    tmp_path: Path,
    monkeypatch,
) -> None:
    base = tmp_path / "skin.dds"
    normal = tmp_path / "skin_n.dds"
    base.write_bytes(b"base")
    normal.write_bytes(b"normal")
    mesh = _mesh()
    body = mesh.submeshes[0]
    body.submesh_index = 3
    body.material_slot_index = 7
    body.preview_texture_path = str(base)
    body.preview_normal_texture_path = str(normal)
    eyes = SubMesh(name="eyes", material="eye", texture=r"missing\eyes.dds")
    eyes.submesh_index = 8
    eyes.material_slot_index = 4
    mesh.submeshes.append(eyes)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("material snapshot must not build or copy a package")

    monkeypatch.setattr(mesh_dotnet_experiment, "export_obj", forbidden)
    monkeypatch.setattr(mesh_dotnet_experiment, "_copy_dotnet_texture_channel_resources", forbidden)
    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="session-1",
        edit_revision=9,
        generation=12,
        affected_submeshes=[8, 8, 99],
    )

    assert payload["schema"] == "cdmw_mesh_material_state_v2"
    assert payload["version"] == 2
    assert payload["event"] == "material_state_update"
    assert payload["session_id"] == "session-1"
    assert payload["edit_revision"] == 9
    assert payload["generation"] == 12
    assert payload["material_signature"] == mesh_dotnet_material_input_signature(mesh)
    assert payload["affected_submeshes"] == [8]
    assert [item["submesh_index"] for item in payload["submeshes"]] == [3, 8]
    assert payload["submeshes"][0]["material_slot_index"] == 7
    assert payload["submeshes"][0]["material"] == "skin"

    resources = {item["path"]: item for item in payload["resources"]}
    base_stat = base.stat()
    base_identity = f"{base.resolve().as_posix().casefold()}|size:{base_stat.st_size}|mtime_ns:{base_stat.st_mtime_ns}"
    expected_base_fingerprint = hashlib.sha256(base_identity.encode("utf-8")).hexdigest()
    assert resources[base.resolve().as_posix()]["fingerprint"] == expected_base_fingerprint
    assert resources["missing/eyes.dds"]["fingerprint"] == hashlib.sha256(
        b"raw:missing/eyes.dds"
    ).hexdigest()
    body_channels = payload["submeshes"][0]["channels"]
    assert body_channels["base"] == body_channels["albedo"] == body_channels["diffuse"]
    assert body_channels["base"] == f"texture:{expected_base_fingerprint}"
    assert len(payload["resources"]) == 3
    assert payload["resources"] == sorted(payload["resources"], key=lambda item: item["resource_id"])
    assert resources[base.resolve().as_posix()] | {
        "path": "ignored",
        "source_reference": "ignored",
        "fingerprint": "ignored",
        "resource_id": "ignored",
    } == {
        "path": "ignored",
        "source_reference": "ignored",
        "fingerprint": "ignored",
        "resource_id": "ignored",
        "role": "replacement",
        "submesh_index": 3,
        "material_channel": "base",
        "profile": "legacy_unknown",
        "required": False,
        "criticality": "optional",
        "fallback_policy": "neutral_checker",
        "semantic": "base",
        "color_space": "srgb",
        "semantic_authority": "inferred",
    }

    repeat = mesh_dotnet_material_state_payload(
        mesh,
        session_id="session-1",
        edit_revision=9,
        generation=12,
    )
    assert repeat["affected_submeshes"] == [3, 8]
    assert repeat | {"affected_submeshes": [8]} == payload


def test_initial_manifest_and_resident_update_share_resource_fingerprint(tmp_path: Path) -> None:
    texture = tmp_path / "skin.dds"
    texture.write_bytes(b"same-resource")
    mesh = _mesh()
    mesh.submeshes[0].preview_texture_path = str(texture)

    package = build_mesh_dotnet_experiment_package(mesh, output_root=tmp_path / "packages")
    manifest = json.loads((package.package_dir / "net_materials.json").read_text(encoding="utf-8"))
    resident = mesh_dotnet_material_state_payload(mesh, session_id="s", edit_revision=1, generation=1)

    initial_resource = manifest["resources"][0]
    resident_resource = resident["resources"][0]
    assert initial_resource["resource_id"] == resident_resource["resource_id"]
    assert initial_resource["fingerprint"] == resident_resource["fingerprint"]
    assert (package.package_dir / initial_resource["path"]).is_file()
    assert manifest["submeshes"][0]["resource_channels"]["base"] == initial_resource["resource_id"]


def test_late_reference_material_snapshot_targets_scene_role_without_export_identity_collision(
    tmp_path: Path,
) -> None:
    texture = tmp_path / "original.dds"
    texture.write_bytes(b"original")
    source = SubMesh(name="original", material="stock", texture=str(texture))

    payload = mesh_dotnet_material_state_payload(
        SimpleNamespace(submeshes=(source,)),
        session_id="resident",
        edit_revision=4,
        generation=3,
        affected_submeshes=(2,),
        role="original_reference",
        submesh_index_offset=2,
        material_signature="whole-scene-signature",
    )

    assert payload["affected_submeshes"] == [2]
    assert payload["submeshes"][0]["submesh_index"] == 2
    assert payload["material_signature"] == "whole-scene-signature"
    resource = payload["resources"][0]
    assert resource["role"] == "original_reference"
    assert resource["submesh_index"] == 2
    assert resource["resource_id"].endswith(":original_reference:2")
    assert resource["required"] is False


def test_late_reference_material_snapshot_accepts_resolved_preview_model(tmp_path: Path) -> None:
    texture = tmp_path / "resolved-original.dds"
    texture.write_bytes(b"resolved-original")
    preview = ModelPreviewData(
        path="archive/original.pac",
        meshes=[
            ModelPreviewMesh(
                material_name="stock_blade",
                preview_texture_path=str(texture),
                preview_texture_flip_vertical=False,
                source_submesh_index=0,
            )
        ],
    )

    payload = mesh_dotnet_material_state_payload(
        preview,
        session_id="resident-preview-model",
        edit_revision=7,
        generation=4,
        role="original_reference",
        submesh_index_offset=3,
        material_signature="whole-scene-signature",
    )

    assert payload["affected_submeshes"] == [3]
    assert payload["submeshes"] == [
        payload["submeshes"][0]
        | {
            "submesh_index": 3,
            "material_slot_index": 0,
            "material": "stock_blade",
            "texture_flip_vertical": False,
        }
    ]
    assert payload["submeshes"][0]["channels"]["base"].startswith("texture:")
    assert payload["resources"][0]["path"] == texture.resolve().as_posix()
    assert payload["resources"][0]["role"] == "original_reference"


def test_preview_material_bridge_preserves_per_role_texture_orientation(tmp_path: Path) -> None:
    imported_texture = tmp_path / "imported.png"
    original_texture = tmp_path / "original.dds"
    imported_texture.write_bytes(b"imported")
    original_texture.write_bytes(b"original")
    editable = ParsedMesh(
        path="imported.obj",
        format="obj",
        submeshes=[SubMesh(name="imported", material="imported")],
    )
    reference = ParsedMesh(
        path="archive/original.pac",
        format="pac",
        submeshes=[SubMesh(name="original", material="original")],
    )
    editable_preview = ModelPreviewData(
        path="external/imported.gltf",
        meshes=[
            ModelPreviewMesh(
                preview_texture_path=str(imported_texture),
                preview_texture_flip_vertical=True,
                source_submesh_index=0,
            )
        ]
    )
    reference_preview = ModelPreviewData(
        path="character/model/weapon/original.pac",
        meshes=[
            ModelPreviewMesh(
                preview_texture_path=str(original_texture),
                preview_texture_flip_vertical=False,
                source_submesh_index=0,
            )
        ]
    )

    assert copy_dotnet_preview_material_bindings(editable, editable_preview) == 1
    assert copy_dotnet_preview_material_bindings(reference, reference_preview) == 1
    assert editable.submeshes[0].preview_source_asset_path == "external/imported.gltf"
    assert reference.submeshes[0].preview_source_asset_path == "character/model/weapon/original.pac"
    editable_payload = mesh_dotnet_material_state_payload(
        editable,
        session_id="orientation",
        edit_revision=0,
        generation=1,
    )
    reference_payload = mesh_dotnet_material_state_payload(
        reference,
        session_id="orientation",
        edit_revision=0,
        generation=2,
        role="original_reference",
        submesh_index_offset=1,
        material_signature="whole-scene-signature",
    )

    assert editable_payload["submeshes"][0]["texture_flip_vertical"] is True
    assert reference_payload["submeshes"][0]["texture_flip_vertical"] is False
    assert mesh_dotnet_material_input_signature(editable) != mesh_dotnet_material_input_signature(reference)


def test_real_material_identity_inference_activates_only_supported_family_policies(
    tmp_path: Path,
) -> None:
    texture = tmp_path / "source.dds"
    texture.write_bytes(b"source")
    mesh = ParsedMesh(
        path="character/model/1_pc/1_phm/armor/38_underwear/cd_phm_00_nude_0001.pac",
        format="pac",
        submeshes=[
            SubMesh(name="head", material="CD_PTM_00_Head_0001_01"),
            SubMesh(name="body", material="CD_PTM_00_Nude_0001"),
            SubMesh(name="hair", material="CD_PHM_00_Hair_0003"),
            SubMesh(name="blade", material="CD_PHM_01_Blade_0001_mg"),
        ],
    )
    for submesh in mesh.submeshes:
        submesh.preview_texture_path = str(texture)

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="family-inference",
        edit_revision=0,
        generation=1,
    )
    bindings = {binding["material"]: binding for binding in payload["submeshes"]}

    for material in ("CD_PTM_00_Head_0001_01", "CD_PTM_00_Nude_0001"):
        binding = bindings[material]
        assert binding["shader_family"] == "skin"
        assert binding["shader_authority"] == "inferred"
        assert binding["shader_family_source"] == "material_identity_inference"
        assert "skin_subsurface_and_wrinkle_response" in binding["unsupported_features"]

    hair = bindings["CD_PHM_00_Hair_0003"]
    assert hair["shader_family"] == "hair"
    assert hair["shader_authority"] == "inferred"
    assert hair["alpha_mode"] == "cutout"
    assert hair["alpha_authority"] == "inferred"
    assert hair["double_sided"] is True
    assert hair["double_sided_authority"] == "inferred"
    assert "hair/fur cards" in hair["double_sided_reason"]
    assert "hair_fur_anisotropy_and_flow" in hair["unsupported_features"]

    blade = bindings["CD_PHM_01_Blade_0001_mg"]
    assert blade["shader_family"] == "generic"
    assert blade["shader_authority"] == "guess"
    assert blade["alpha_mode"] == "opaque"
    assert blade["alpha_authority"] == "guess"


def test_explicit_hair_alpha_contract_wins_over_cutout_inference(tmp_path: Path) -> None:
    texture = tmp_path / "hair.dds"
    texture.write_bytes(b"hair")
    hair = SubMesh(name="hair", material="CD_PHM_00_Hair_0003")
    hair.preview_texture_path = str(texture)
    hair.preview_alpha_mode = "opaque"
    mesh = ParsedMesh(path="character/model/hair/hair.pac", format="pac", submeshes=[hair])

    binding = mesh_dotnet_material_state_payload(
        mesh,
        session_id="explicit-alpha",
        edit_revision=0,
        generation=1,
    )["submeshes"][0]

    assert binding["shader_family"] == "hair"
    assert binding["alpha_mode"] == "opaque"
    assert binding["alpha_authority"] == "sidecar"
    assert "source declared alpha mode opaque" == binding["alpha_reason"]


def test_explicit_hair_family_does_not_override_source_culling_contract(tmp_path: Path) -> None:
    texture = tmp_path / "hair.dds"
    texture.write_bytes(b"hair")
    hair = SubMesh(name="hair", material="CD_PHM_00_Hair_0003")
    hair.preview_texture_path = str(texture)
    hair.preview_sidecar_shader_family = "hair"
    hair.preview_double_sided = False
    mesh = ParsedMesh(path="character/model/hair/hair.pac", format="pac", submeshes=[hair])

    binding = mesh_dotnet_material_state_payload(
        mesh,
        session_id="explicit-hair-family",
        edit_revision=0,
        generation=1,
    )["submeshes"][0]

    assert binding["shader_family"] == "hair"
    assert binding["shader_authority"] != "inferred"
    assert binding["double_sided"] is False
    assert binding["double_sided_authority"] == "guess"


def test_alpha_blend_contract_reports_only_remaining_per_triangle_sort_limit(tmp_path: Path) -> None:
    texture = tmp_path / "glass.png"
    texture.write_bytes(b"glass")
    glass = SubMesh(name="glass", material="glass")
    glass.preview_texture_path = str(texture)
    glass.preview_alpha_mode = "blend"
    mesh = ParsedMesh(path="external/glass.gltf", format="gltf", submeshes=[glass])

    binding = mesh_dotnet_material_state_payload(
        mesh,
        session_id="alpha-blend",
        edit_revision=0,
        generation=1,
    )["submeshes"][0]

    assert binding["alpha_mode"] == "blend"
    assert "per_triangle_alpha_blend_sorting" in binding["unsupported_features"]
    assert "order_dependent_alpha_blending" not in binding["unsupported_features"]


def test_crimson_support_map_suffixes_are_not_misbound_as_srgb_base_color(
    tmp_path: Path,
) -> None:
    cases = (
        ("weapon_mg.dds", "detail_mask", "layer_mask", "linear"),
        ("weapon_ma.dds", "material_mask", "material", "linear"),
        ("weapon_m.dds", "material", "material", "linear"),
        ("weapon_sp.dds", "material", "specular", "linear"),
        ("weapon_n.dds", "normal", "normal", "linear"),
        ("weapon_disp.dds", "height", "height", "linear"),
        ("weapon_emi.dds", "emissive", "emissive", "srgb"),
    )
    for filename, expected_role, expected_channel, expected_color_space in cases:
        texture = tmp_path / filename
        texture.write_bytes(filename.encode("ascii"))
        submesh = SubMesh(name=filename, material=filename, texture=str(texture))
        mesh = ParsedMesh(path="character/model/weapon/test.pac", format="pac", submeshes=[submesh])

        payload = mesh_dotnet_material_state_payload(
            mesh,
            session_id=f"technical-{expected_channel}",
            edit_revision=0,
            generation=1,
        )
        binding = payload["submeshes"][0]

        assert infer_cd_texture_role_from_path(str(texture)) == expected_role
        assert not {"base", "albedo", "diffuse"}.intersection(binding["channels"])
        assert expected_channel in binding["channels"]
        resource = next(
            item for item in payload["resources"] if item["material_channel"] == expected_channel
        )
        assert resource["color_space"] == expected_color_space


def test_authoritative_source_color_binding_wins_over_filename_suffix(tmp_path: Path) -> None:
    texture = tmp_path / "intentional_base_mg.dds"
    texture.write_bytes(b"base")
    submesh = SubMesh(name="external", material="external", texture=str(texture))
    submesh.preview_material_texture_inputs = (
        SimpleNamespace(
            semantic_type="base",
            source_dds_path=str(texture),
            confidence="gltf",
        ),
    )
    mesh = ParsedMesh(path="external/model.gltf", format="gltf", submeshes=[submesh])

    binding = mesh_dotnet_material_state_payload(
        mesh,
        session_id="authoritative-color",
        edit_revision=0,
        generation=1,
    )["submeshes"][0]

    assert {"base", "albedo", "diffuse"}.issubset(binding["channels"])
    assert "layer_mask" not in binding["channels"]


def test_initial_two_role_manifest_keeps_texture_paths_and_uv_orientation_separate(
    tmp_path: Path,
) -> None:
    imported_texture = tmp_path / "imported.png"
    original_texture = tmp_path / "original.dds"
    imported_texture.write_bytes(b"imported")
    original_texture.write_bytes(b"original")
    editable = _mesh()
    editable.path = "imported.obj"
    editable.format = "obj"
    editable.submeshes[0].preview_texture_path = str(imported_texture)
    editable.submeshes[0].preview_texture_flip_vertical = True
    reference = _mesh()
    reference.path = "archive/original.pac"
    reference.format = "pac"
    reference.submeshes[0].preview_texture_path = str(original_texture)
    reference.submeshes[0].preview_texture_flip_vertical = False

    package = build_mesh_dotnet_experiment_package(
        editable,
        output_root=tmp_path / "packages",
        reference_mesh=reference,
    )
    manifest = json.loads(
        (package.package_dir / "net_materials.json").read_text(encoding="utf-8")
    )

    assert [binding["texture_flip_vertical"] for binding in manifest["submeshes"]] == [
        True,
        False,
    ]
    assert manifest["submeshes"][0]["resolved_channels"]["base"] == str(imported_texture)
    assert manifest["submeshes"][1]["resolved_channels"]["base"] == str(original_texture)
    assert manifest["submeshes"][0]["resource_channels"]["base"].startswith("texture:")
    assert manifest["submeshes"][1]["resource_channels"]["base"].endswith(
        ":original_reference:1"
    )


def test_gltf_packed_channels_and_source_factors_survive_resident_snapshot(tmp_path: Path) -> None:
    base = tmp_path / "blade_base.png"
    material = tmp_path / "blade_metallicRoughness.png"
    base.write_bytes(b"base")
    material.write_bytes(b"packed")
    mesh = _mesh()
    blade = mesh.submeshes[0]
    blade.preview_texture_path = str(base)
    blade.preview_material_texture_path = str(material)
    blade.preview_material_texture_subtype = "metallic_roughness"
    blade.preview_material_texture_packed_channels = ("roughness", "metallic")
    blade.preview_color = (0.75, 0.5, 0.25)
    blade.preview_native_material_overrides = {
        "roughness": 0.8,
        "metalness": 0.6,
        "emissive_color": "#ff4000",
        "emissive_intensity": 2.0,
    }

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="gltf",
        edit_revision=1,
        generation=1,
    )
    binding = payload["submeshes"][0]

    assert binding["channels"]["roughness"] == binding["channels"]["metallic"]
    assert "specular" not in binding["channels"]
    assert binding["channel_components"] == {"roughness": "g", "metallic": "b"}
    assert binding["parameters"] == {
        "tint_color": [0.75, 0.5, 0.25],
        "roughness_scale": 0.8,
        "metalness_scale": 0.6,
        "emissive_color": [1.0, 64 / 255.0, 0.0],
        "emissive_intensity": 2.0,
    }

    signature = mesh_dotnet_material_input_signature(mesh)
    blade.preview_color = (0.5, 0.5, 0.5)
    assert mesh_dotnet_material_input_signature(mesh) != signature


def test_layer_mask_input_gets_a_distinct_resident_shader_binding(tmp_path: Path) -> None:
    mask = tmp_path / "blade_layer_mask.dds"
    mask.write_bytes(b"mask")
    mesh = _mesh()
    mesh.submeshes[0].preview_material_texture_inputs = (
        SimpleNamespace(
            semantic_type="material",
            semantic_subtype="color_blending_mask",
            parameter_name="_colorBlendingMaskTexture",
            source_dds_path=str(mask),
            layer_channel="g",
        ),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="layer-mask",
        edit_revision=2,
        generation=3,
    )
    binding = payload["submeshes"][0]

    assert binding["channels"]["layer_mask"] == binding["channels"]["material"]
    assert binding["channel_components"]["layer_mask"] == "g"
    assert any(resource["path"] == mask.resolve().as_posix() for resource in payload["resources"])


def test_authoritative_crimson_color_mask_promotes_pbr_components(tmp_path: Path) -> None:
    mask = tmp_path / "blade_ma.dds"
    mask.write_bytes(b"packed-mask")
    mesh = _mesh()
    blade = mesh.submeshes[0]
    blade.preview_sidecar_shader_family = "SkinnedMeshStandard_Ver2"
    blade.preview_material_texture_inputs = (
        SimpleNamespace(
            semantic_type="mask",
            semantic_subtype="color_blending_mask",
            parameter_name="_colorBlendingMaskTexture",
            source_dds_path=str(mask),
            sidecar_kind="pac_xml",
            parameter_declared_by="pac_xml",
        ),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="crimson-packed-mask",
        edit_revision=0,
        generation=1,
    )
    binding = payload["submeshes"][0]

    for channel in ("ao", "roughness", "metallic"):
        assert binding["channels"][channel] == binding["channels"]["layer_mask"]
    assert binding["channel_components"] | {"layer_mask": "r"} == {
        "ao": "r",
        "roughness": "g",
        "metallic": "b",
        "layer_mask": "r",
    }


def test_layer_only_albedo_is_not_promoted_over_native_tint_fallback(tmp_path: Path) -> None:
    layer_albedo = tmp_path / "detail_albedo.dds"
    primary_normal = tmp_path / "cloth_n.dds"
    layer_albedo.write_bytes(b"layer")
    primary_normal.write_bytes(b"normal")
    mesh = _mesh()
    cloth = mesh.submeshes[0]
    cloth.texture = ""
    cloth.preview_color = (0.90, 0.83, 0.71)
    cloth.preview_sidecar_shader_family = "SkinnedMeshCloth_Ver2"
    cloth.preview_native_material_overrides = {
        "base_tint_only_fallback": True,
        "roughness": 0.48,
        "metalness": 0.0,
    }
    cloth.preview_material_texture_inputs = (
        SimpleNamespace(
            semantic_type="albedo",
            source_dds_path=str(layer_albedo),
            layer_role="detail",
            layer_channel="b",
        ),
        SimpleNamespace(
            semantic_type="normal",
            source_dds_path=str(primary_normal),
            layer_role="normal",
        ),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="tint-only-cloth",
        edit_revision=0,
        generation=1,
    )
    binding = payload["submeshes"][0]

    assert not {"albedo", "base", "diffuse"}.intersection(binding["channels"])
    assert binding["parameters"]["tint_color"] == [0.90, 0.83, 0.71]
    assert binding["parameters"]["roughness"] == 0.48
    assert binding["parameters"]["metalness"] == 0.0
    assert binding["shader_family"] == "cloth_v2"
    assert "normal" in binding["channels"]


def test_textured_material_does_not_apply_representative_preview_color_as_tint(tmp_path: Path) -> None:
    base = tmp_path / "lantern_base.dds"
    base.write_bytes(b"base")
    mesh = _mesh()
    lantern = mesh.submeshes[0]
    lantern.preview_color = (0.68, 0.60, 0.49)
    lantern.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            semantic_type="base",
            source_dds_path=str(base),
        ),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="textured-preview-color",
        edit_revision=0,
        generation=1,
    )

    assert "tint_color" not in payload["submeshes"][0]["parameters"]


def test_textured_material_transports_explicit_texture_tint(tmp_path: Path) -> None:
    base = tmp_path / "shield_base.dds"
    base.write_bytes(b"base")
    mesh = _mesh()
    shield = mesh.submeshes[0]
    shield.preview_color = (0.57, 0.39, 0.29)
    shield.preview_texture_tint = (0.73, 0.44, 0.24)
    shield.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            semantic_type="base",
            source_dds_path=str(base),
        ),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="textured-explicit-tint",
        edit_revision=0,
        generation=1,
    )

    assert payload["submeshes"][0]["parameters"]["tint_color"] == [0.73, 0.44, 0.24]


def test_native_material_batch_binding_preserves_explicit_texture_tint(tmp_path: Path) -> None:
    base = tmp_path / "reference_base.dds"
    base.write_bytes(b"base")
    model = _mesh()
    target = model.submeshes[0]

    assert mesh_dotnet_material_state.apply_dotnet_native_material_batch_binding(
        target,
        {
            "dds_textures": {"base": {"source_path": str(base)}},
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
    assert payload["submeshes"][0]["parameters"]["tint_color"] == [0.73, 0.44, 0.24]


def test_bc4_emissive_dds_is_tagged_as_scalar_mask(tmp_path: Path) -> None:
    emissive = tmp_path / "rune_emi.dds"
    emissive.write_bytes(b"bc4")
    mesh = _mesh()
    rune = mesh.submeshes[0]
    rune.preview_emissive_texture_dds_path = str(emissive)

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


def test_gltf_normal_maps_carry_the_directx_green_inversion_policy(tmp_path: Path) -> None:
    normal = tmp_path / "blade_normal.png"
    normal.write_bytes(b"normal")
    mesh = _mesh()
    blade = mesh.submeshes[0]
    blade.preview_material_texture_inputs = (
        SimpleNamespace(
            semantic_type="normal",
            source_texture_path=str(normal),
            confidence="gltf",
        ),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="normal-y",
        edit_revision=0,
        generation=1,
    )

    assert payload["submeshes"][0]["normal_y_policy"] == "invert_green_for_directx"


def test_archive_green_up_normal_maps_carry_the_directx_green_inversion_policy(tmp_path: Path) -> None:
    normal = tmp_path / "archive_normal.dds"
    normal.write_bytes(b"normal")
    mesh = _mesh()
    blade = mesh.submeshes[0]
    blade.preview_material_texture_inputs = (
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
    blade = mesh.submeshes[0]
    blade.preview_material_texture_inputs = (
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


def test_source_dds_and_material_semantics_survive_resident_transport(tmp_path: Path) -> None:
    source_dds = tmp_path / "skin_base.dds"
    preview_png = tmp_path / "skin_base.png"
    source_dds.write_bytes(b"source-dds")
    preview_png.write_bytes(b"preview-png")
    mesh = _mesh()
    skin = mesh.submeshes[0]
    skin.preview_sidecar_shader_family = "Skin"
    skin.preview_alpha_mode = "mask"
    skin.preview_double_sided = True
    skin.preview_native_material_overrides = {"alpha_cutoff": 0.37}
    skin.preview_material_texture_inputs = (
        SimpleNamespace(
            semantic_type="base",
            parameter_name="BaseColorTexture",
            source_dds_path=str(source_dds),
            preview_texture_path=str(preview_png),
            sidecar_kind="material_sidecar",
        ),
    )

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="semantic-source",
        edit_revision=0,
        generation=1,
    )
    binding = payload["submeshes"][0]
    resource = next(item for item in payload["resources"] if item["material_channel"] == "base")

    assert resource["path"] == source_dds.resolve().as_posix()
    assert binding["channels"]["base"] == resource["resource_id"]
    assert resource["color_space"] == "srgb"
    assert resource["semantic_authority"] == "authoritative"
    assert binding["shader_family"] == "skin"
    assert binding["alpha_mode"] == "cutout"
    assert binding["alpha_cutoff"] == 0.37
    assert binding["double_sided"] is True
    assert "skin_subsurface_and_wrinkle_response" in binding["unsupported_features"]


def test_gltf_opacity_factor_survives_resident_transport() -> None:
    mesh = _mesh()
    gem = mesh.submeshes[0]
    gem.preview_alpha_mode = "blend"
    gem.preview_vertex_alpha_mean = 0.25
    gem.preview_native_material_overrides = {"opacity": 0.5}

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="gltf-opacity",
        edit_revision=0,
        generation=1,
    )

    binding = payload["submeshes"][0]
    assert binding["alpha_mode"] == "blend"
    assert binding["opacity_factor"] == 0.5


def test_material_opacity_factor_defaults_to_opaque() -> None:
    payload = mesh_dotnet_material_state_payload(
        _mesh(),
        session_id="opaque-default",
        edit_revision=0,
        generation=1,
    )

    assert payload["submeshes"][0]["opacity_factor"] == 1.0


def test_color_only_gltf_material_preserves_surface_and_emissive_factors(tmp_path: Path) -> None:
    mesh = _mesh()
    gem = mesh.submeshes[0]
    gem.name = "Gem_inside"
    gem.material = "Gem_inside"
    gem.texture = ""
    gem.preview_color = (0.0, 1.0, 0.7911)
    gem.preview_native_material_overrides = {
        "roughness": 0.920748,
        "emissive_color": "#ff0000",
        "emissive_intensity": 10.0,
    }

    payload = mesh_dotnet_material_state_payload(
        mesh,
        session_id="gem",
        edit_revision=1,
        generation=1,
    )

    assert payload["submeshes"][0]["parameters"] == {
        "tint_color": [0.0, 1.0, 0.7911],
        "roughness": 0.920748,
        "emissive_color": [1.0, 0.0, 0.0],
        "emissive_intensity": 10.0,
    }
    assert payload["submeshes"][0]["shader_family"] == "emissive"
    assert payload["submeshes"][0]["shader_authority"] == "inferred"
