"""Pure artifact naming and reporting helpers for Mesh Editor export workers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from cdmw.services.mesh_service_state import MeshExportTextureSnapshot


def artifact_row(path: Path, root: Path, role: str, **extra: object) -> dict[str, object]:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {
        "role": str(role),
        "path": path.relative_to(root).as_posix(),
        "size": int(path.stat().st_size),
        "sha256": digest,
        **extra,
    }


def texture_artifact_name(resource: MeshExportTextureSnapshot) -> str:
    digest = hashlib.sha256(
        f"{resource.resource_id}\0{resource.channel}".encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    semantic = "".join(ch if ch.isalnum() else "_" for ch in resource.channel).strip("_") or "base"
    return f"{semantic}_{digest}.dds"


__all__ = ["artifact_row", "texture_artifact_name"]
