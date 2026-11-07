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


#: Names an editable package export writes, in the order a tie is resolved.
EDITABLE_PACKAGE_MESH_NAMES = (
    "mesh.glb",
    "edited_mesh.glb",
    "edited.glb",
    "mesh.obj",
    "edited_mesh.obj",
    "edited.obj",
    "mesh.fbx",
    "edited_mesh.fbx",
    "edited.fbx",
)
_EDITABLE_PACKAGE_MESH_SUFFIXES = frozenset({".glb", ".fbx", ".obj"})


def editable_package_mesh_in_folder(folder: Path) -> Path | None:
    """The mesh a returned editable package folder holds, or None when it has none.

    A folder can hold the exported file and the file Blender saved beside it, or
    the three formats of one export. The most recently written mesh is the
    return; files written together fall back to the export's own name order.
    """
    candidates = [item for item in folder.iterdir()
                  if item.is_file() and item.suffix.lower() in _EDITABLE_PACKAGE_MESH_SUFFIXES]
    if not candidates:
        return None
    order = {name: index for index, name in enumerate(EDITABLE_PACKAGE_MESH_NAMES)}

    def modified(item: Path) -> int:
        try:
            return int(item.stat().st_mtime_ns)
        except OSError:
            return 0

    newest = max(modified(item) for item in candidates)
    # One export writes its formats within moments of each other.
    recent = [item for item in candidates if newest - modified(item) <= 2_000_000_000]
    return min(recent, key=lambda item: (order.get(item.name.casefold(), len(order)), item.name.casefold()))


__all__ = ["EDITABLE_PACKAGE_MESH_NAMES", "artifact_row", "editable_package_mesh_in_folder", "texture_artifact_name"]
