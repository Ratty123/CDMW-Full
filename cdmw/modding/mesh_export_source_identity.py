"""Source provenance used by mesh export reports and sidecars."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .mesh_parser import ParsedMesh


def mesh_export_original_data(mesh: ParsedMesh) -> bytes:
    original_data = bytes(getattr(mesh, "_cdmw_original_data", b"") or b"")
    source = Path(str(getattr(mesh, "path", "") or ""))
    if not original_data and source.is_file():
        try:
            original_data = source.read_bytes()
        except OSError:
            pass
    return original_data


def mesh_export_source_identity(mesh: ParsedMesh) -> dict[str, object]:
    original_data = mesh_export_original_data(mesh)
    if original_data:
        return {"source_asset_hash": hashlib.sha256(original_data).hexdigest(), "source_asset_size": len(original_data)}
    source_hash = str(
        getattr(mesh, "_cdmw_mesh_asset_source_hash", "")
        or getattr(mesh, "_cdmw_sidecar_source_asset_hash", "")
        or ""
    ).strip().lower()
    if not source_hash:
        return {}
    payload: dict[str, object] = {"source_asset_hash": source_hash}
    try:
        source_size = int(getattr(mesh, "_cdmw_sidecar_source_asset_size", -1))
    except (TypeError, ValueError, OverflowError):
        source_size = -1
    if source_size >= 0:
        payload["source_asset_size"] = source_size
    return payload
