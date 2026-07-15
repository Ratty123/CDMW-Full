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
    base_source.write_bytes(b"base-dds")
    normal_source.write_bytes(b"normal-dds")
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

    assert result["external_reference_count"] == 4
    assert result["materialized_file_count"] == 2
    assert stable_base.is_relative_to(package_dir.resolve())
    assert stable_normal.is_relative_to(package_dir.resolve())
    assert batch["material_layers"][0]["diffuse_source"] == str(stable_base)
    assert batch["primary_material_layer"]["diffuse_source"] == str(stable_base)
    assert batch["dds_textures"]["missing_optional"]["source_path"].endswith(
        "missing.dds"
    )

    base_source.unlink()
    normal_source.unlink()
    assert stable_base.read_bytes() == b"base-dds"
    assert stable_normal.read_bytes() == b"normal-dds"
