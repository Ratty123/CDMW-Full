from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cdmw.rendering.native_preview_core import (
    _native_preview_core_manifest_dds_paths,
    prune_native_preview_core_cache,
)
from cdmw.services.mesh_rust_preview_package import (
    build_rust_preview_package_from_preview_core,
    validate_rust_preview_package,
)
from cdmw.workers.archive_preview_native import ArchivePreviewNativeMixin
from tests.test_rust_preview_production_cutover import _write_schema8_preview_core_fixture


RESOURCE_ROLES = ("diffuse", "normal", "material", "height", "mask")


@pytest.mark.parametrize("source_format", ("pac", "pam", "pamlod"))
@pytest.mark.parametrize("quality", ("direct", "full"))
@pytest.mark.parametrize("role", RESOURCE_ROLES)
def test_layer_only_dds_survives_prune_and_reaches_preview_package(
    tmp_path: Path, source_format: str, quality: str, role: str,
) -> None:
    source, *_ = _write_schema8_preview_core_fixture(tmp_path)
    cache = tmp_path / "native-cache"
    dds_root = cache / "dds"
    dds_root.mkdir(parents=True)
    texture = dds_root / "nonetexture0x00000000.dds"
    disposable = dds_root / "unused.dds"
    texture.write_bytes(b"DDS " + b"a" * 80)
    disposable.write_bytes(b"DDS " + b"b" * 80)
    os.utime(texture, (1000, 1000))
    os.utime(disposable, (2000, 2000))

    manifest_path = source / "manifest.json"
    native = json.loads(manifest_path.read_text(encoding="utf-8"))
    native["format"] = source_format
    native["source_path"] = f"fixture/model.{source_format}"
    batch = native["batches"][0]
    # This resource is required by the graph, but has no direct-upload slot.
    batch.pop("dds_textures")
    layer = batch["material_layers"][0]
    layer["diffuse_source"] = ""
    layer["diffuse_archive_path"] = ""
    layer[f"{role}_source"] = str(texture)
    layer[f"{role}_archive_path"] = "texture/nonetexture0x00000000.dds"
    manifest_path.write_text(json.dumps(native), encoding="utf-8")

    report = prune_native_preview_core_cache(
        cache, max_bytes=120, target_bytes=90,
        protected_paths=_native_preview_core_manifest_dds_paths(source),
    )
    package = build_rust_preview_package_from_preview_core(
        source, output_package_dir=tmp_path / "rust-package", material_quality=quality,
    )

    assert report["removed_files"] == 1
    assert texture.is_file()
    assert not disposable.exists()
    assert validate_rust_preview_package(package.package_dir) == ()
    published = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    graph_layer = published["preview_core_material_graph"]["materials"][0]["layers"][0]
    assert graph_layer[f"{role}_declared"] is True
    if quality == "full":
        assert (package.package_dir / graph_layer[role]["path"]).read_bytes() == texture.read_bytes()
    else:
        assert graph_layer[role] is None


@pytest.mark.parametrize("role", RESOURCE_ROLES)
@pytest.mark.parametrize("relative", (False, True))
def test_native_cache_rejects_missing_layer_resource_and_accepts_restored_source(
    tmp_path: Path, role: str, relative: bool,
) -> None:
    source, *_ = _write_schema8_preview_core_fixture(tmp_path)
    texture = source / "layer.dds"
    manifest_path = source / "manifest.json"
    native = json.loads(manifest_path.read_text(encoding="utf-8"))
    native["batches"][0]["material_layers"][0][f"{role}_source"] = (
        texture.name if relative else str(texture)
    )
    manifest_path.write_text(json.dumps(native), encoding="utf-8")
    validate = ArchivePreviewNativeMixin._validate_native_preview_core_package_basic

    valid, reasons = validate(source)
    assert not valid
    assert str(texture) in reasons
    assert texture in _native_preview_core_manifest_dds_paths(source)

    texture.write_bytes(b"DDS " + b"a" * 80)
    assert validate(source) == (True, ())
