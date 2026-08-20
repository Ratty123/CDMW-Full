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

    from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
    from cdmw.core.papgt_format import papgt_with_directory
    from cdmw.services.archive_overlay_install import (
        OVERLAY_DIRECTORY_FIRST,
        _processed_payload,
        overlay_directory_name,
    )

    root = Path(package_root)
    root.mkdir(parents=True, exist_ok=True)
    files = {}
    for request in plan.patches:
        entry = request.entry
        path = str(entry.path).replace("\\", "/").strip("/")
        files[path] = OverlayFile(
            path=path,
            payload=_processed_payload(
                request.payload_data,
                compression_type=int(entry.compression_type),
                encrypted=bool(entry.encrypted),
                basename=str(entry.basename),
            ),
            orig_size=len(request.payload_data),
            flags=int(entry.flags),
        )
    for addition in plan.additions:
        path = str(addition.path).replace("\\", "/").strip("/")
        files[path] = OverlayFile(
            path=path,
            payload=_processed_payload(
                addition.payload_data,
                compression_type=int(addition.compression_type),
                encrypted=bool(addition.encryption_type),
                basename=str(addition.basename),
            ),
            orig_size=len(addition.payload_data),
            flags=int(addition.flags),
        )
    if not files:
        raise ValueError("The plan changes nothing, so there is no archive to write.")

    name = str(group or "") or (
        overlay_directory_name(Path(game_root)) if game_root and Path(game_root).is_dir()
        else f"{OVERLAY_DIRECTORY_FIRST:04d}"
    )
    built = build_overlay_archive(sorted(files.values(), key=lambda item: item.path), on_log=on_log)
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "0.paz").write_bytes(built.paz_bytes)
    (directory / "0.pamt").write_bytes(built.pamt_bytes)

    mount_written = False
    if game_root is not None:
        source = Path(game_root) / "meta" / "0.papgt"
        if source.is_file():
            mounted = papgt_with_directory(source.read_bytes(), name, built.pamt_checksum, first=True)
            (root / "meta").mkdir(parents=True, exist_ok=True)
            (root / "meta" / "0.papgt").write_bytes(mounted)
            mount_written = True

    written: list = []
    for relative, payload in [(write.path, write.payload_data) for write in getattr(plan, "meta_files", ())]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        written.append(str(relative))

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
        "generator": "Crimson Desert Mod Workbench - New Item Studio",
        "files_dir": ".",
        "manager_targets": ["dmm"],
        "manager_target_labels": ["Definitive Mod Manager"],
        "structure": "archive_group",
        "archive_group": name,
        "file_count": len(files),
        "created_utc": created_utc,
        "overrides": sorted(files),
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
                f"An archive group ({name}/0.pamt and 0.paz) holding {len(files)} file(s), the shape a mod manager mounts",
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
    if on_log is not None:
        on_log(f"Wrote {name}/0.pamt and 0.paz: {len(files)} file(s), {len(built.paz_bytes):,} bytes.")
    return OverlayModExport(
        package_root=root,
        group=name,
        file_count=len(files),
        payload_bytes=len(built.paz_bytes),
        paths=tuple(sorted(files)),
        metadata_files=("manifest.json", "modinfo.json", "README.txt", *written),
        mount_list_written=mount_written,
    )
