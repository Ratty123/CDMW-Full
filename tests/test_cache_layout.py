from __future__ import annotations

from pathlib import Path

from cdmw.services.cache_layout import migrate_runtime_cache_layout, runtime_cache_layout


def test_runtime_cache_layout_groups_index_and_preview_lanes(tmp_path: Path) -> None:
    layout = runtime_cache_layout(tmp_path / "cache")

    assert layout.catalogue_root == tmp_path / "cache" / "index" / "catalogue_v2"
    assert layout.item_icon_preview_root == tmp_path / "cache" / "preview" / "item-icons"
    assert layout.model_preview_root == tmp_path / "cache" / "preview" / "models"
    assert layout.native_preview_root == tmp_path / "cache" / "preview" / "native"
    assert layout.directxtex_preview_root == tmp_path / "cache" / "preview" / "textures" / "directxtex"


def test_migration_preserves_known_legacy_cache_lanes(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    (cache_root / "catalogue_v2" / "root-id").mkdir(parents=True)
    (cache_root / "catalogue_v2" / "root-id" / "current.json").write_text("{}", encoding="utf-8")
    (cache_root / "directxtex_texture_preview" / "texture-key").mkdir(parents=True)
    (cache_root / "directxtex_texture_preview" / "texture-key" / "icon.png").write_bytes(b"png")
    for dirname in ("dds", "native_material_graph", "pamt_index", "packages", "dotnet_vortice"):
        directory = cache_root / "native_preview_core" / dirname
        directory.mkdir(parents=True)
        (directory / "marker.bin").write_bytes(dirname.encode("ascii"))
    unknown = cache_root / "native_preview_core" / "future_cache"
    unknown.mkdir(parents=True)

    report = migrate_runtime_cache_layout(cache_root)
    layout = runtime_cache_layout(cache_root)

    assert (layout.catalogue_root / "root-id" / "current.json").is_file()
    assert (layout.directxtex_preview_root / "texture-key" / "icon.png").is_file()
    for dirname in ("dds", "native_material_graph", "pamt_index"):
        assert (layout.native_preview_root / dirname / "marker.bin").is_file()
    for dirname in ("packages", "dotnet_vortice"):
        assert (layout.model_preview_root / dirname / "marker.bin").is_file()
    assert unknown.is_dir()
    assert len(report.moved) == 7

    second = migrate_runtime_cache_layout(cache_root)
    assert second.moved == []


def test_migration_never_overwrites_an_existing_destination(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    source = cache_root / "catalogue_v2"
    destination = cache_root / "index" / "catalogue_v2"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "source.txt").write_text("legacy", encoding="utf-8")
    (destination / "destination.txt").write_text("current", encoding="utf-8")

    report = migrate_runtime_cache_layout(cache_root)

    assert (source / "source.txt").read_text(encoding="utf-8") == "legacy"
    assert (destination / "destination.txt").read_text(encoding="utf-8") == "current"
    assert any(item[0] == source and item[2] == "destination exists" for item in report.skipped)
