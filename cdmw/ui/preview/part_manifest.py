"""Where a preview package's parts are listed (Scene panel, Parts menu)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional


def _read_json(path: Path) -> Optional[dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def read_part_manifest(package_dir: Path) -> Optional[dict]:
    """The manifest whose ``batches`` name each part's file, for the Scene panel and Parts menu.

    The resident preview's cached package keeps its geometry under
    ``preview_core_geometry`` with no per-part file names; its ``cache_entry.json``
    names the canonical package it was made from, which has them, in the same order.
    Without this a set's Scene panel listed no parts, and "Open ticked parts in Mesh
    Editor" refused every set ("Tick at least one part").
    """

    manifest = _read_json(package_dir / "manifest.json")
    if manifest is None or isinstance(manifest.get("batches"), list):
        return manifest
    geometry = manifest.get("preview_core_geometry")
    resident = geometry.get("batches") if isinstance(geometry, Mapping) else None
    entry = _read_json(package_dir.parent / "cache_entry.json") or {}
    source = str(entry.get("source_package") or "").strip()
    if not source or not isinstance(resident, list):
        return manifest
    canonical = _read_json(Path(source) / "manifest.json")
    batches = canonical.get("batches") if canonical is not None else None
    if not isinstance(batches, list) or len(batches) != len(resident):
        return manifest
    return {**manifest, "batches": batches,
            **({"asset_family": canonical["asset_family"]} if "asset_family" in canonical else {})}
