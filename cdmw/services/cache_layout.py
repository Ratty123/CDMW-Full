"""Stable paths and conservative migration for the runtime cache tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimeCacheLayout:
    root: Path
    index_root: Path
    catalogue_root: Path
    preview_root: Path
    item_icon_preview_root: Path
    model_preview_root: Path
    native_preview_root: Path
    texture_preview_root: Path
    directxtex_preview_root: Path


@dataclass(slots=True)
class CacheLayoutMigrationReport:
    moved: list[tuple[Path, Path]] = field(default_factory=list)
    skipped: list[tuple[Path, Path, str]] = field(default_factory=list)


def runtime_cache_layout(cache_root: Path | str) -> RuntimeCacheLayout:
    root = Path(cache_root).expanduser()
    index_root = root / "index"
    preview_root = root / "preview"
    texture_preview_root = preview_root / "textures"
    return RuntimeCacheLayout(
        root=root,
        index_root=index_root,
        catalogue_root=index_root / "catalogue_v2",
        preview_root=preview_root,
        item_icon_preview_root=preview_root / "item-icons",
        model_preview_root=preview_root / "models",
        native_preview_root=preview_root / "native",
        texture_preview_root=texture_preview_root,
        directxtex_preview_root=texture_preview_root / "directxtex",
    )


def _move_directory(
    source: Path,
    destination: Path,
    report: CacheLayoutMigrationReport,
) -> None:
    if not source.exists():
        return
    if not source.is_dir():
        report.skipped.append((source, destination, "source is not a directory"))
        return
    if destination.exists():
        report.skipped.append((source, destination, "destination exists"))
        return
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        report.moved.append((source, destination))
    except OSError as exc:
        report.skipped.append((source, destination, str(exc)))


def _remove_empty_legacy_directory(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def migrate_runtime_cache_layout(cache_root: Path | str) -> CacheLayoutMigrationReport:
    """Move known legacy cache lanes without merging or replacing data."""

    layout = runtime_cache_layout(cache_root)
    report = CacheLayoutMigrationReport()
    for directory in (
        layout.index_root,
        layout.preview_root,
        layout.item_icon_preview_root,
        layout.model_preview_root,
        layout.native_preview_root,
        layout.texture_preview_root,
    ):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            report.skipped.append((directory, directory, str(exc)))

    _move_directory(layout.root / "catalogue_v2", layout.catalogue_root, report)
    _move_directory(
        layout.root / "directxtex_texture_preview",
        layout.directxtex_preview_root,
        report,
    )

    legacy_native_root = layout.root / "native_preview_core"
    for dirname in ("packages", "dotnet_vortice"):
        _move_directory(
            legacy_native_root / dirname,
            layout.model_preview_root / dirname,
            report,
        )
    for dirname in ("dds", "native_material_graph", "pamt_index"):
        _move_directory(
            legacy_native_root / dirname,
            layout.native_preview_root / dirname,
            report,
        )
    _remove_empty_legacy_directory(legacy_native_root)

    # Accept the short-lived transitional shape where the complete legacy
    # directory was moved below preview/native before model packages split out.
    for dirname in ("packages", "dotnet_vortice"):
        _move_directory(
            layout.native_preview_root / dirname,
            layout.model_preview_root / dirname,
            report,
        )
    return report


__all__ = [
    "CacheLayoutMigrationReport",
    "RuntimeCacheLayout",
    "migrate_runtime_cache_layout",
    "runtime_cache_layout",
]
