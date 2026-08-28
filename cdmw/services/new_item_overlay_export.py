"""Write a plan as an archive-group mod folder: the shape DMM mounts.

A loose mod drops game-relative files into a folder and hopes the manager routes them.
For the tables a new item rewrites -- a six-megabyte `iteminfo.pabgb` among them -- DMM
does not route them that way: its own summary counts mods as JSON, browser/file,
standalone-overlay or group-replace, and a table belongs to the last two. What it mounts
is a prebuilt archive group, `<group>/0.pamt` and `0.paz` beside a `meta/0.papgt` naming
it, which is the same directory the workbench installs into the game itself.

So this writes exactly that, into the mod folder instead of into the game. The archive is
built by :func:`cdmw.core.archive_overlay.build_overlay_archive`, the one whose output
reproduces a shipped archive byte for byte, and the mount list is the game's own with the
group added -- the count in its header included, which is what the game reads to decide
whether its installation is sound.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple

__all__ = ["OverlayModExport", "export_overlay_mod"]


@dataclass(frozen=True, slots=True)
class OverlayModExport:
    """What was written into the mod folder."""

    package_root: Path
    group: str
    file_count: int
    payload_bytes: int
    paths: Tuple[str, ...]
    metadata_files: Tuple[str, ...]
    mount_list_written: bool


def export_overlay_mod(
    plan,
    package_root: Path,
    *,
    group: str = "",
    title: str = "",
    description: str = "",
    author: str = "",
    version: str = "1.0.0",
    created_utc: str = "",
    game_root: Optional[Path] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> OverlayModExport:
    """Write `plan` into `package_root` as an archive group with its mount list.

    `game_root` is the install the plan was built against; its `meta/0.papgt` is copied
    with the group added, because a manager that mounts a prebuilt group needs to know
    the group exists. Without it the folder still holds the archive, and the manager has
    to name the group itself.
    """

    from cdmw.services.archive_overlay_package_service import export_archive_overlay_package

    shared = export_archive_overlay_package(
        plan.patches,
        plan.additions,
        package_root=Path(package_root),
        group=group,
        game_root=game_root,
        metadata_files=tuple(
            (write.path, write.payload_data) for write in getattr(plan, "meta_files", ())
        ),
        on_log=on_log,
    )
    root = shared.package_root
    name = shared.group
    written = list(shared.metadata_files)

    spec = plan.spec
    manifest = {
        "format": "v1",
        "schema_version": 1,
        "kind": "archive_override_mod",
        "name": title or f"New item {spec.internal_name}",
        "title": title or f"New item {spec.internal_name}",
        "game": "Crimson Desert",
        "version": version,
        "author": author,
        "description": description or f"Adds {spec.internal_name} (item {spec.item_key}) cloned from item {spec.template_key}.",
        "generator": "Crimson Desert Mod Workbench - Create New Item",
        "files_dir": ".",
        "manager_targets": ["dmm"],
        "manager_target_labels": ["Definitive Mod Manager"],
        "structure": "archive_group",
        "archive_group": name,
        "file_count": shared.file_count,
        "created_utc": created_utc,
        "overrides": list(shared.paths),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (root / "modinfo.json").write_text(
        json.dumps(
            {
                "name": manifest["name"],
                "version": version,
                "author": author,
                "description": manifest["description"],
                "title": manifest["title"],
                "created_utc": created_utc,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "README.txt").write_text(
        "\n".join(
            [
                manifest["title"],
                "=" * len(manifest["title"]),
                "",
                manifest["description"],
                "",
                "What this is",
                "------------",
                f"An archive group ({name}/0.pamt and 0.paz) holding {shared.file_count} file(s), the shape a mod manager mounts",
                "ahead of the archives the game shipped. The shipped archives are not modified by installing it.",
                "",
                "How to use it",
                "-------------",
                "1. Place this folder inside your mod manager's mods folder.",
                "2. Enable it and mount.",
                "",
                "Two of these cannot both be enabled: each carries the whole item table, so the one mounted last owns it.",
                "Build the second item into the same folder instead, and one group holds both.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return OverlayModExport(
        package_root=root,
        group=name,
        file_count=shared.file_count,
        payload_bytes=shared.payload_bytes,
        paths=shared.paths,
        metadata_files=("manifest.json", "modinfo.json", "README.txt", *written),
        mount_list_written=shared.mount_list_written,
    )
