from __future__ import annotations

import json
from pathlib import Path

from cdmw.services.mesh_dotnet_preview_package import build_or_lookup_dotnet_preview_package


def _write_layered_native_package(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    package = tmp_path / "native_layered"
    geometry = package / "geometry"
    geometry.mkdir(parents=True)
    (geometry / "batch_000.bin").write_bytes(bytes(3 * 23 * 4))
    textures = {
        "base": tmp_path / "shield_base.dds",
        "surface": tmp_path / "shield_surface.dds",
        "detail": tmp_path / "shield_detail.dds",
        "mask": tmp_path / "shield_detail_mask.dds",
        "detail_surface": tmp_path / "shield_detail_surface.dds",
    }
    for name, path in textures.items():
        path.write_bytes(name.encode("ascii"))
    material_inputs = [
        {"slot": "base", "source_path": str(textures["base"]), "semantic_type": "albedo"},
        {
            "slot": "material",
            "source_path": str(textures["surface"]),
            "semantic_type": "packed_material",
            "packed_channels": "g=roughness,b=metallic",
        },
        {"slot": "base", "source_path": str(textures["detail"]), "layer_role": "detail"},
        {"slot": "material", "source_path": str(textures["mask"]), "layer_role": "detail"},
        {
            "slot": "material",
            "source_path": str(textures["detail_surface"]),
            "layer_role": "detail",
        },
    ]
    manifest = {
        "schema_version": 8,
        "source_path": "character/layered_shield.pac",
        "use_textures": True,
        "normalization_center": [0.0, 0.0, 0.0],
        "normalization_scale": 1.0,
        "batches": [
            {
                "index": 0,
                "material_name": "CD_PHM_03_Shield_0101",
                "vertex_file": "geometry/batch_000.bin",
                "vertex_count": 3,
                "base_color": [0.8, 0.7, 0.6],
                "roughness": 0.72,
                "metalness": 0.2,
                "material_category": "generic",
                "shader_family": "SkinnedMeshStandard_Ver2",
                "dds_textures": {
                    "base": material_inputs[0],
                    "material": material_inputs[1],
                    "material_inputs": material_inputs,
                },
                "material_layers": [
                    {
                        "layer_role": "base",
                        "mask_channel": "r",
                        "weight": 1.0,
                        "tint": [0.8, 0.7, 0.6, 1.0],
                        "diffuse_source": str(textures["base"]),
                        "material_source": str(textures["surface"]),
                    },
                    {
                        "layer_role": "detail",
                        "mask_channel": "g",
                        "weight": 0.68,
                        "tint": [0.4, 0.5, 0.6, 1.0],
                        "diffuse_source": str(textures["detail"]),
                        "mask_source": str(textures["mask"]),
                        "material_source": str(textures["detail_surface"]),
                    },
                ],
            }
        ],
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return package, textures


def test_schema8_adapter_preserves_authoritative_material_layers(tmp_path: Path) -> None:
    source_package, textures = _write_layered_native_package(tmp_path)

    package = build_or_lookup_dotnet_preview_package(
        source_package,
        cache_root=tmp_path / "preview-cache",
        archive_identity="layered-shield",
    )

    materials = json.loads((package.package_dir / "net_materials.json").read_text(encoding="utf-8"))
    binding = materials["submeshes"][0]
    assert binding["material_layer_compiler"] == "archive_lite_managed_layer_compiler_v1"
    assert len(binding["material_layers"]) == 2
    detail = binding["material_layers"][1]
    resources = {resource["resource_id"]: resource for resource in materials["resources"]}
    assert Path(resources[detail["diffuse_resource_id"]]["path"]) == textures["detail"].resolve()
    assert Path(resources[detail["mask_resource_id"]]["path"]) == textures["mask"].resolve()
    assert Path(resources[detail["material_resource_id"]]["path"]) == textures["detail_surface"].resolve()
    assert "material" in binding["resource_channels"]
    assert "roughness" not in binding["resource_channels"]
    assert "metallic" not in binding["resource_channels"]
    marker = json.loads((package.package_dir / "cdmw_native_dotnet_adapter_v1.json").read_text(encoding="utf-8"))
    assert marker["schema"] == 2
