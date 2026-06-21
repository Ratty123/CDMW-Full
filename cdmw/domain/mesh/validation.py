"""Pure mesh import validation helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Tuple
from urllib.parse import unquote, urlparse
from pathlib import PurePosixPath

SUPPORTED_MESH_IMPORT_EXTENSIONS = frozenset({".obj", ".dae", ".gltf", ".glb"})


def is_supported_mesh_import(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_MESH_IMPORT_EXTENSIONS


@dataclass(slots=True, frozen=True)
class MeshImportModeAvailability:
    roundtrip_enabled: bool
    static_enabled: bool
    default_mode: str
    guidance: str


def _format_scene_import_byte_size(byte_count: int) -> str:
    size = max(0, int(byte_count))
    if size < 1024:
        return f"{size:,} byte{'s' if size != 1 else ''}"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _scene_import_file_size(path: Path) -> Optional[int]:
    try:
        resolved = Path(path).expanduser()
        if not resolved.is_file():
            return None
        return int(resolved.stat().st_size)
    except OSError:
        return None


def _iter_gltf_external_buffer_paths(source_path: Path) -> Tuple[Path, ...]:
    if Path(source_path).suffix.lower() != ".gltf":
        return ()
    try:
        document = json.loads(Path(source_path).read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        try:
            document = json.loads(Path(source_path).read_text(encoding="utf-8-sig"))
        except Exception:
            return ()
    except Exception:
        return ()
    if not isinstance(document, dict):
        return ()
    paths: List[Path] = []
    for buffer_entry in document.get("buffers", []) or []:
        if not isinstance(buffer_entry, Mapping):
            continue
        uri = str(buffer_entry.get("uri", "") or "").strip()
        if not uri or uri.startswith("data:"):
            continue
        parsed = urlparse(uri)
        if parsed.scheme and parsed.scheme.lower() != "file":
            continue
        if parsed.scheme.lower() == "file":
            candidate = Path(unquote(parsed.path))
        else:
            candidate = Path(source_path).parent.joinpath(*PurePosixPath(unquote(parsed.path or uri)).parts)
        paths.append(candidate)
    return tuple(paths)


def format_scene_import_file_size_summary(source_path: Path, scene_result: Optional[SceneImportResult] = None) -> str:
    source_size = _scene_import_file_size(source_path)
    linked_buffer_sizes: List[int] = []
    seen_paths: set[str] = {str(Path(source_path).expanduser()).casefold()}
    for linked_path in _iter_gltf_external_buffer_paths(source_path):
        key = str(Path(linked_path).expanduser()).casefold()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        linked_size = _scene_import_file_size(linked_path)
        if linked_size is not None:
            linked_buffer_sizes.append(linked_size)

    if source_size is None and not linked_buffer_sizes:
        return ""

    if source_size is None:
        return f"\n\nFile size: {_format_scene_import_byte_size(sum(linked_buffer_sizes))} linked mesh buffer(s)"

    if linked_buffer_sizes:
        total_size = source_size + sum(linked_buffer_sizes)
        return (
            f"\n\nFile size: {_format_scene_import_byte_size(source_size)} source, "
            f"{_format_scene_import_byte_size(total_size)} with linked mesh buffer(s)"
        )

    return f"\n\nFile size: {_format_scene_import_byte_size(source_size)}"


def mesh_import_mode_availability(
    scene_path: Path,
    *,
    has_roundtrip_sidecar: bool,
    static_supported: bool = True,
) -> MeshImportModeAvailability:
    suffix = scene_path.suffix.lower()
    is_obj = suffix == ".obj"
    static_enabled = bool(static_supported)
    roundtrip_enabled = is_obj
    if suffix in {".gltf", ".glb"}:
        guidance = (
            "GLB/glTF imports are static Mesh Replacement sources. Skins, bones, animations, and PBR material graphs are not converted into game material data."
        )
    elif suffix == ".dae":
        guidance = "DAE imports use Mesh Replacement. Round-trip edit remains OBJ-only."
    elif suffix in {".pac", ".pam", ".pamlod"}:
        guidance = (
            "Local PAC/PAM/PAMLOD imports use Mesh Replacement. Geometry is parsed directly, and matching loose sidecars/DDS files are included when discovered."
        )
        roundtrip_enabled = False
    elif has_roundtrip_sidecar:
        guidance = "An OBJ round-trip sidecar was found, so Round-trip edit is selected by default."
    else:
        guidance = "No OBJ round-trip sidecar was found. Mesh Replacement is selected by default."
    if is_obj and (has_roundtrip_sidecar or not static_enabled):
        default_mode = "roundtrip"
    elif static_enabled:
        default_mode = "static_replacement"
    elif roundtrip_enabled:
        default_mode = "roundtrip"
    else:
        default_mode = ""
    return MeshImportModeAvailability(
        roundtrip_enabled=roundtrip_enabled,
        static_enabled=static_enabled,
        default_mode=default_mode,
        guidance=guidance,
    )


__all__ = [
    "MeshImportModeAvailability",
    "SUPPORTED_MESH_IMPORT_EXTENSIONS",
    "format_scene_import_file_size_summary",
    "is_supported_mesh_import",
    "mesh_import_mode_availability",
]
