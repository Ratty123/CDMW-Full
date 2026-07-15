from __future__ import annotations

import json
from pathlib import Path

from tools.mesh_harness.visual_audit_package import stabilize_visual_audit_archive_package


def test_visual_audit_package_owns_transient_native_texture_sources(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    cache_dir = tmp_path / "transient-cache"
    package_dir.mkdir()
    cache_dir.mkdir()
    base_source = cache_dir / "base.dds"
    normal_source = cache_dir / "normal.dds"
    specular_source = cache_dir / "specular.dds"
    detail_source = cache_dir / "detail.dds"
    base_source.write_bytes(b"base-dds")
    normal_source.write_bytes(b"normal-dds")
    specular_source.write_bytes(b"specular-dds")
    detail_source.write_bytes(b"detail-dds")
    manifest_path = package_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "batches": [
                    {
                        "dds_textures": {
                            "base": {
                                "source_path": str(base_source),
                                "available": True,
                                "direct_upload_candidate": True,
                            },
                            "missing_optional": {
                                "source_path": str(cache_dir / "missing.dds"),
                                "available": False,
                                "direct_upload_candidate": True,
                            },
                            "material_inputs": [
                                {
                                    "source_path": str(specular_source),
                                    "available": True,
                                    "direct_upload_candidate": True,
                                    "semantic_subtype": "specular",
                                },
                                {
                                    "source_path": str(detail_source),
                                    "available": True,
                                    "direct_upload_candidate": False,
                                    "semantic_subtype": "detail_mask",
                                },
                            ],
                        },
                        "material_layers": [
                            {
                                "diffuse_source": str(base_source),
                                "normal_source": str(normal_source),
                            }
                        ],
                        "primary_material_layer": {
                            "diffuse_source": str(base_source),
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = stabilize_visual_audit_archive_package(package_dir)
    stabilized = json.loads(manifest_path.read_text(encoding="utf-8"))
    batch = stabilized["batches"][0]
    stable_base = Path(batch["dds_textures"]["base"]["source_path"])
    stable_normal = Path(batch["material_layers"][0]["normal_source"])
    stable_specular = Path(
        batch["dds_textures"]["material_inputs"][0]["source_path"]
    )
    stable_detail = Path(
        batch["dds_textures"]["material_inputs"][1]["source_path"]
    )

    assert result["external_reference_count"] == 6
    assert result["materialized_file_count"] == 4
    assert stable_base.is_relative_to(package_dir.resolve())
    assert stable_normal.is_relative_to(package_dir.resolve())
    assert stable_specular.is_relative_to(package_dir.resolve())
    assert stable_detail.is_relative_to(package_dir.resolve())
    assert batch["material_layers"][0]["diffuse_source"] == str(stable_base)
    assert batch["primary_material_layer"]["diffuse_source"] == str(stable_base)
    assert batch["dds_textures"]["missing_optional"]["source_path"].endswith(
        "missing.dds"
    )

    base_source.unlink()
    normal_source.unlink()
    specular_source.unlink()
    detail_source.unlink()
    assert stable_base.read_bytes() == b"base-dds"
    assert stable_normal.read_bytes() == b"normal-dds"
    assert stable_specular.read_bytes() == b"specular-dds"
    assert stable_detail.read_bytes() == b"detail-dds"
