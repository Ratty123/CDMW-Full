"""Reference-only native composite geometry for the .NET Mesh Editor scene."""

from __future__ import annotations

import copy
import json
import math
import os
import struct
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from cdmw.domain.cancellation import RunCancelled
from cdmw.modding.mesh_totals import refresh_mesh_totals
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_dotnet_material_state import apply_dotnet_native_material_batch_binding


_NATIVE_VERTEX = struct.Struct("<23f")
_NATIVE_IDENTITY = struct.Struct("<2i")
_DECODE_CHUNK_VERTICES = 4096
_MAX_REFERENCE_COMPOSITE_VERTICES = 2_000_000


def _finite_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _index(value: object, fallback: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _vec3(value: object) -> tuple[float, float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or len(value) < 3:
        return None
    parsed = tuple(_finite_float(component, float("nan")) for component in value[:3])
    return parsed if all(math.isfinite(component) for component in parsed) else None  # type: ignore[return-value]


def _package_child(package_dir: Path, value: object) -> Path | None:
    text = str(value or "").strip().replace("/", os.sep)
    if not text:
        return None
    try:
        root = package_dir.resolve()
        candidate = (root / text).resolve()
        if os.path.commonpath((str(root), str(candidate))) != str(root):
            return None
    except (OSError, ValueError):
        return None
    return candidate


def _native_reference_batch(batch: Mapping[str, object]) -> bool:
    identity = batch.get("editor_identity")
    identity = identity if isinstance(identity, Mapping) else {}
    component_index = _index(identity.get("source_component_index", 0), 0)
    return bool(identity.get("prefab_component", False)) or component_index != 0


def _load_native_manifest(package_path: Path | str | None) -> tuple[Path, Mapping[str, object]] | None:
    if package_path is None:
        return None
    try:
        package_dir = Path(package_path).expanduser().resolve()
        manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    return (package_dir, manifest) if isinstance(manifest, Mapping) else None


def apply_dotnet_native_reference_materials(
    reference_mesh: ParsedMesh,
    package_path: Path | str | None,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> int:
    """Hydrate direct original-reference submeshes from native material evidence.

    The package belongs to the archive original, so these bindings must never be
    copied onto the editable replacement mesh. Native local-submesh identity is
    authoritative and avoids material-name guessing when several parts share a
    texture family.
    """

    stop_requested = cancelled or (lambda: False)
    if stop_requested() or reference_mesh is None:
        return 0
    loaded = _load_native_manifest(package_path)
    if loaded is None:
        return 0
    _package_dir, manifest = loaded
    raw_batches = manifest.get("batches")
    submeshes = tuple(getattr(reference_mesh, "submeshes", ()) or ())
    if not submeshes or not isinstance(raw_batches, Sequence) or isinstance(raw_batches, (str, bytes, bytearray)):
        return 0

    applied: set[int] = set()
    for fallback_index, raw_batch in enumerate(raw_batches):
        if stop_requested():
            return 0
        if not isinstance(raw_batch, Mapping) or _native_reference_batch(raw_batch):
            continue
        identity = raw_batch.get("editor_identity")
        identity = identity if isinstance(identity, Mapping) else {}
        local_index = _index(
            identity.get("source_local_submesh_index", identity.get("source_submesh_index", fallback_index)),
            fallback_index,
        )
        if local_index < 0 or local_index >= len(submeshes) or local_index in applied:
            continue
        target = submeshes[local_index]
        if not apply_dotnet_native_material_batch_binding(target, raw_batch):
            continue
        setattr(target, "cdmw_material_authority_profile", "native_reference_direct")
        applied.add(local_index)
    return len(applied)


def _decode_native_reference_submesh(
    package_dir: Path,
    batch: Mapping[str, object],
    *,
    center: tuple[float, float, float],
    scale: float,
    cancelled: Callable[[], bool],
    preview_role: str = "original_reference_prefab",
    material_authority_profile: str = "native_reference_composite",
) -> SubMesh | None:
    vertex_count = _index(batch.get("vertex_count"), 0)
    if vertex_count <= 0 or vertex_count % 3 or vertex_count > _MAX_REFERENCE_COMPOSITE_VERTICES:
        return None
    geometry_path = _package_child(package_dir, batch.get("vertex_file"))
    if geometry_path is None or not geometry_path.is_file():
        return None
    expected_geometry_size = vertex_count * _NATIVE_VERTEX.size
    try:
        if geometry_path.stat().st_size != expected_geometry_size:
            return None
    except OSError:
        return None

    identity = batch.get("editor_identity")
    identity = identity if isinstance(identity, Mapping) else {}
    identity_path = _package_child(package_dir, identity.get("identity_file"))
    identity_available = False
    if identity_path is not None and identity_path.is_file():
        try:
            identity_available = identity_path.stat().st_size == vertex_count * _NATIVE_IDENTITY.size
        except OSError:
            identity_available = False

    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    tangents: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    source_vertex_map: list[int] = []
    try:
        with geometry_path.open("rb") as geometry_stream:
            identity_stream = identity_path.open("rb") if identity_available and identity_path is not None else None
            try:
                remaining = vertex_count
                while remaining > 0:
                    if cancelled():
                        return None
                    chunk_count = min(remaining, _DECODE_CHUNK_VERTICES)
                    geometry = geometry_stream.read(chunk_count * _NATIVE_VERTEX.size)
                    if len(geometry) != chunk_count * _NATIVE_VERTEX.size:
                        return None
                    raw_identity = (
                        identity_stream.read(chunk_count * _NATIVE_IDENTITY.size)
                        if identity_stream is not None
                        else b""
                    )
                    if identity_stream is not None and len(raw_identity) != chunk_count * _NATIVE_IDENTITY.size:
                        return None
                    identities = iter(struct.iter_unpack(_NATIVE_IDENTITY.format, raw_identity)) if raw_identity else None
                    for values in struct.iter_unpack(_NATIVE_VERTEX.format, geometry):
                        positions.append(
                            (
                                values[0] / scale + center[0],
                                values[1] / scale + center[1],
                                values[2] / scale + center[2],
                            )
                        )
                        normals.append((values[3], values[4], values[5]))
                        uvs.append((values[9], values[10]))
                        tangents.append((values[11], values[12], values[13]))
                        source_vertex_map.append(next(identities)[1] if identities is not None else len(source_vertex_map))
                    remaining -= chunk_count
            finally:
                if identity_stream is not None:
                    identity_stream.close()
    except (OSError, StopIteration, struct.error):
        return None
    if cancelled() or len(positions) != vertex_count:
        return None

    raw_index = _index(batch.get("index"), 0)
    component_index = _index(identity.get("source_component_index"), 0)
    local_index = _index(identity.get("source_local_submesh_index"), 0)
    component_label = str(identity.get("source_component_label", "") or "prefab")
    material_name = str(batch.get("material_name", "") or component_label)
    minimum = tuple(min(vertex[axis] for vertex in positions) for axis in range(3))
    maximum = tuple(max(vertex[axis] for vertex in positions) for axis in range(3))
    submesh = SubMesh(
        name=f"reference_prefab_{component_index}_{local_index}_{component_label}",
        material=material_name,
        vertices=positions,
        uvs=uvs,
        normals=normals,
        tangents=tangents,
        faces=[(offset, offset + 1, offset + 2) for offset in range(0, vertex_count, 3)],
        source_vertex_map=source_vertex_map,
        source_vertex_map_authority="native_preview_identity",
        vertex_count=vertex_count,
        face_count=vertex_count // 3,
        source_index_count=vertex_count,
        source_bbox_min=minimum,
        source_bbox_extent=tuple(maximum[axis] - minimum[axis] for axis in range(3)),
    )
    setattr(submesh, "preview_role", str(preview_role or "archive_model"))
    setattr(submesh, "preview_source_asset_path", str(identity.get("source_asset_path", "") or ""))
    setattr(submesh, "cdmw_material_authority_profile", str(material_authority_profile or "native_preview_core"))
    setattr(submesh, "cdmw_mesh_edit_topology_source_submesh_index", raw_index)
    setattr(submesh, "cdmw_native_source_submesh_index", _index(identity.get("source_submesh_index"), raw_index))
    setattr(submesh, "cdmw_native_source_local_submesh_index", local_index)
    setattr(submesh, "cdmw_native_source_component_index", component_index)
    setattr(submesh, "cdmw_native_source_component_label", component_label)
    setattr(submesh, "cdmw_native_prefab_component", bool(identity.get("prefab_component", False)))
    setattr(submesh, "cdmw_native_editor_identity", copy.deepcopy(dict(identity)))
    apply_dotnet_native_material_batch_binding(submesh, batch)
    return submesh


def decode_dotnet_native_preview_package(
    package_path: Path | str,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ParsedMesh:
    """Decode every preview-core batch into canonical ``ParsedMesh`` input.

    Preview Core remains the authoritative archive decoder.  Its normalized
    triangle stream is restored to source coordinates here so the ordinary
    .NET package/material compiler owns every visible artifact after decoding.
    """

    stop_requested = cancelled or (lambda: False)
    if stop_requested():
        raise RunCancelled("Preview-core package decode cancelled.")
    loaded = _load_native_manifest(package_path)
    if loaded is None:
        raise ValueError("Preview-core package manifest is missing or invalid.")
    package_dir, manifest = loaded
    center = _vec3(manifest.get("normalization_center"))
    scale = _finite_float(manifest.get("normalization_scale"), 0.0)
    raw_batches = manifest.get("batches")
    if center is None or abs(scale) <= 1.0e-12:
        raise ValueError("Preview-core package normalization is invalid.")
    if not isinstance(raw_batches, Sequence) or isinstance(raw_batches, (str, bytes, bytearray)):
        raise ValueError("Preview-core package batch list is invalid.")

    decoded: list[SubMesh] = []
    total_vertices = 0
    for raw_batch in raw_batches:
        if stop_requested():
            raise RunCancelled("Preview-core package decode cancelled.")
        if not isinstance(raw_batch, Mapping):
            raise ValueError("Preview-core package contains an invalid batch.")
        batch_vertices = _index(raw_batch.get("vertex_count"), 0)
        if batch_vertices <= 0 or total_vertices + batch_vertices > _MAX_REFERENCE_COMPOSITE_VERTICES:
            raise ValueError("Preview-core package exceeds the canonical preview vertex limit.")
        submesh = _decode_native_reference_submesh(
            package_dir,
            raw_batch,
            center=center,
            scale=scale,
            cancelled=stop_requested,
            preview_role="archive_model",
            material_authority_profile="native_preview_core_canonical",
        )
        if submesh is None:
            if stop_requested():
                raise RunCancelled("Preview-core package decode cancelled.")
            raise ValueError("Preview-core package geometry is incomplete or corrupt.")
        decoded.append(submesh)
        total_vertices += len(submesh.vertices)
    if not decoded:
        raise ValueError("Preview-core package contains no renderable batches.")

    minimum = tuple(min(submesh.source_bbox_min[axis] for submesh in decoded) for axis in range(3))
    maximum = tuple(
        max(submesh.source_bbox_min[axis] + submesh.source_bbox_extent[axis] for submesh in decoded)
        for axis in range(3)
    )
    mesh = ParsedMesh(
        path=str(manifest.get("source_path", "") or package_dir),
        format=str(manifest.get("format", "") or "pac").strip().lower(),
        bbox_min=minimum,
        bbox_max=maximum,
        submeshes=decoded,
        has_uvs=all(len(submesh.uvs) == len(submesh.vertices) for submesh in decoded),
    )
    refresh_mesh_totals(mesh)
    setattr(mesh, "cdmw_preview_core_package_path", str(package_dir))
    setattr(mesh, "cdmw_preview_core_manifest", copy.deepcopy(dict(manifest)))
    return mesh


def append_dotnet_native_reference_composite(
    reference_mesh: ParsedMesh,
    package_path: Path | str | None,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> int:
    """Append secondary native-package components to a cloned reference mesh.

    Only component/prefab batches are decoded. The direct source PAC remains the
    editable/export authority, and callers pass this mesh only as the .NET
    scene's original-reference role.
    """

    stop_requested = cancelled or (lambda: False)
    if stop_requested() or reference_mesh is None or package_path is None:
        return 0
    loaded = _load_native_manifest(package_path)
    if loaded is None:
        return 0
    package_dir, manifest = loaded
    center = _vec3(manifest.get("normalization_center"))
    scale = _finite_float(manifest.get("normalization_scale"), 0.0)
    raw_batches = manifest.get("batches")
    if center is None or abs(scale) <= 1.0e-12 or not isinstance(raw_batches, Sequence) or isinstance(raw_batches, (str, bytes, bytearray)):
        return 0

    additions: list[SubMesh] = []
    total_vertices = 0
    for raw_batch in raw_batches:
        if stop_requested():
            return 0
        if not isinstance(raw_batch, Mapping) or not _native_reference_batch(raw_batch):
            continue
        batch_vertices = _index(raw_batch.get("vertex_count"), 0)
        if batch_vertices <= 0 or total_vertices + batch_vertices > _MAX_REFERENCE_COMPOSITE_VERTICES:
            continue
        decoded = _decode_native_reference_submesh(
            package_dir,
            raw_batch,
            center=center,
            scale=scale,
            cancelled=stop_requested,
        )
        if decoded is None:
            if stop_requested():
                return 0
            continue
        additions.append(decoded)
        total_vertices += len(decoded.vertices)
    if stop_requested() or not additions:
        return 0
    reference_mesh.submeshes.extend(additions)
    refresh_mesh_totals(reference_mesh)
    return len(additions)


__all__ = [
    "apply_dotnet_native_reference_materials",
    "append_dotnet_native_reference_composite",
    "decode_dotnet_native_preview_package",
]
