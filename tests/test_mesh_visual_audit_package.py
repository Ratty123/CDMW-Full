from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.mesh_harness.visual_audit_package import (
    fingerprint_visual_audit_prepared_packages,
    stabilize_visual_audit_archive_package,
)


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


def test_visual_audit_prepared_package_fingerprint_detects_tree_changes(
    tmp_path: Path,
) -> None:
    archive_package = tmp_path / "archive"
    dotnet_package = tmp_path / "dotnet"
    archive_package.mkdir()
    dotnet_package.mkdir()
    (archive_package / "manifest.json").write_text('{"ok":true}', encoding="utf-8")
    (archive_package / "texture.dds").write_bytes(b"archive-texture")
    (dotnet_package / "dotnet_scene.json").write_text('{"ok":true}', encoding="utf-8")
    (dotnet_package / "mesh.obj").write_bytes(b"v 0 0 0\n")
    runtime_assets = [
        {
            "id": "001-test",
            "archive_package_dir": str(archive_package),
            "dotnet_package_dir": str(dotnet_package),
        }
    ]

    before = fingerprint_visual_audit_prepared_packages(
        runtime_assets,
        run_id="a" * 32,
        corpus_sha256="b" * 64,
        temporary_root=tmp_path,
    )
    repeated = fingerprint_visual_audit_prepared_packages(
        runtime_assets,
        run_id="a" * 32,
        corpus_sha256="b" * 64,
        temporary_root=tmp_path,
    )
    assert repeated == before
    assert before["asset_count"] == 1
    assert before["assets"][0]["archive_package_dir"]["file_count"] == 2

    (dotnet_package / "mesh.obj").write_bytes(b"v 1 0 0\n")
    after = fingerprint_visual_audit_prepared_packages(
        runtime_assets,
        run_id="a" * 32,
        corpus_sha256="b" * 64,
        temporary_root=tmp_path,
    )
    assert after["aggregate_sha256"] != before["aggregate_sha256"]

    runtime_assets[0]["dotnet_package_dir"] = str(archive_package)
    shared = fingerprint_visual_audit_prepared_packages(
        runtime_assets,
        run_id="a" * 32,
        corpus_sha256="b" * 64,
        temporary_root=tmp_path,
    )
    assert (
        shared["assets"][0]["archive_package_dir"]
        == shared["assets"][0]["dotnet_package_dir"]
    )

    runtime_assets.append(
        {
            "id": "002-cross-asset-reuse",
            "archive_package_dir": str(archive_package),
            "dotnet_package_dir": str(dotnet_package),
        }
    )
    with pytest.raises(ValueError, match="invalid or reused"):
        fingerprint_visual_audit_prepared_packages(
            runtime_assets,
            run_id="a" * 32,
            corpus_sha256="b" * 64,
            temporary_root=tmp_path,
        )
