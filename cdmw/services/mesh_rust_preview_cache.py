"""Rust Archive Preview packages derived from shared Preview Core output."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import struct
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from cdmw.domain.cancellation import RunCancelled
from cdmw.modding.mesh_deformer import copy_extra_submesh_attrs
from cdmw.modding.mesh_totals import refresh_mesh_totals
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.rendering.dotnet_preview_package_cache import (
    create_dotnet_preview_package_staging_dir,
    dotnet_preview_package_cache_build_lock,
    lookup_dotnet_preview_package_cache,
    release_dotnet_preview_package_staging_dir,
    store_dotnet_preview_package_cache,
)
from cdmw.services.mesh_dotnet_reference_composite import decode_dotnet_native_preview_package
from cdmw.services.mesh_rust_contract import (
    RUST_MESH_AUTHORING_PACKAGE,
    RUST_PREVIEW_BACKEND,
    RUST_PREVIEW_PACKAGE,
)
from cdmw.services.mesh_rust_preview_package import (
    RustPreviewPackage,
    build_rust_preview_package,
    build_rust_preview_package_from_preview_core,
    build_rust_preview_prewarm_package,
    rust_preview_package_from_path,
    validate_rust_preview_package,
)
_PYTHON_MODEL_PREVIEW_SOURCE_MANIFEST = {
    "schema_version": 1,
    "material_semantics_version": 1,
    "material_graph_version": 1,
}
_CLOTH_PARTICLE = struct.Struct("<3f")
_CLOTH_PIN = struct.Struct("<f")
_CLOTH_CONSTRAINT = struct.Struct("<2i2f")
_MAX_CLOTH_PARTICLES = 2_000_000
_MAX_CLOTH_CONSTRAINTS = 4_000_000
_LOGGER = logging.getLogger(__name__)
RUST_PREVIEW_CACHE_SCHEMA = 3


def _cancelled(callback: Callable[[], bool] | None) -> bool:
    return bool(callback is not None and callback())


def _check_cancelled(callback: Callable[[], bool] | None) -> None:
    if _cancelled(callback):
        raise RunCancelled("Rust preview package preparation cancelled.")


def _safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _vec3(value: object) -> tuple[float, float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or len(value) < 3:
        return None
    parsed = tuple(_safe_float(component, float("nan")) for component in value[:3])
    return parsed if all(math.isfinite(component) for component in parsed) else None  # type: ignore[return-value]


def _package_child(package_dir: Path, value: object) -> Path | None:
    text = str(value or "").strip().replace("/", os.sep)
    if not text:
        return None
    try:
        root = package_dir.resolve()
        child = (root / text).resolve()
        child.relative_to(root)
    except (OSError, ValueError):
        return None
    return child


def _read_exact_records(
    path: Path | None,
    record: struct.Struct,
    count: int,
    *,
    cancelled: Callable[[], bool] | None,
) -> tuple[tuple[object, ...], ...]:
    if path is None or count <= 0 or not path.is_file():
        return ()
    try:
        if path.stat().st_size != count * record.size:
            return ()
        payload = path.read_bytes()
    except OSError:
        return ()
    _check_cancelled(cancelled)
    try:
        return tuple(struct.iter_unpack(record.format, payload))
    except struct.error:
        return ()


def rust_preview_overlays_from_preview_core_package(
    package_path: Path | str,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Translate Preview Core skeleton/PBD resources into scene overlay data."""

    package_dir = Path(package_path).expanduser().resolve()
    try:
        manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Preview-core overlay manifest is missing or invalid.") from exc
    if not isinstance(manifest, Mapping):
        raise ValueError("Preview-core overlay manifest is not a JSON object.")
    center = _vec3(manifest.get("normalization_center"))
    scale = _safe_float(manifest.get("normalization_scale"), 0.0)
    if center is None or abs(scale) <= 1.0e-12:
        raise ValueError("Preview-core overlay normalization is invalid.")

    result: dict[str, object] = {}
    skeleton = manifest.get("skeleton_overlay")
    if isinstance(skeleton, Mapping):
        result["skeleton"] = copy.deepcopy(dict(skeleton))

    raw_batches = manifest.get("batches", ())
    if not isinstance(raw_batches, Sequence) or isinstance(raw_batches, (str, bytes, bytearray)):
        return result
    particles: list[list[float]] = []
    pins: list[float] = []
    constraints: list[list[int]] = []
    cloth_settings: Mapping[str, object] | None = None
    for batch in raw_batches:
        _check_cancelled(cancelled)
        if not isinstance(batch, Mapping) or not bool(batch.get("cloth_enabled", False)):
            continue
        particle_count = _safe_int(batch.get("cloth_particle_count"), 0)
        constraint_count = _safe_int(batch.get("cloth_constraint_count"), 0)
        if particle_count <= 0 or particle_count > _MAX_CLOTH_PARTICLES:
            raise ValueError("Preview-core cloth particle count is invalid.")
        if constraint_count < 0 or constraint_count > _MAX_CLOTH_CONSTRAINTS:
            raise ValueError("Preview-core cloth constraint count is invalid.")
        particle_rows = _read_exact_records(
            _package_child(package_dir, batch.get("cloth_particle_file")),
            _CLOTH_PARTICLE,
            particle_count,
            cancelled=cancelled,
        )
        pin_rows = _read_exact_records(
            _package_child(package_dir, batch.get("cloth_pin_file")),
            _CLOTH_PIN,
            particle_count,
            cancelled=cancelled,
        )
        constraint_rows = _read_exact_records(
            _package_child(package_dir, batch.get("cloth_constraint_file")),
            _CLOTH_CONSTRAINT,
            constraint_count,
            cancelled=cancelled,
        )
        if len(particle_rows) != particle_count or len(pin_rows) != particle_count:
            raise ValueError("Preview-core cloth particle resources are incomplete or corrupt.")
        if len(constraint_rows) != constraint_count:
            raise ValueError("Preview-core cloth constraint resources are incomplete or corrupt.")
        offset = len(particles)
        for row in particle_rows:
            particles.append(
                [
                    _safe_float(row[0]) / scale + center[0],
                    _safe_float(row[1]) / scale + center[1],
                    _safe_float(row[2]) / scale + center[2],
                ]
            )
        pins.extend(max(0.0, min(1.0, _safe_float(row[0]))) for row in pin_rows)
        for row in constraint_rows:
            a = _safe_int(row[0], -1)
            b = _safe_int(row[1], -1)
            if 0 <= a < particle_count and 0 <= b < particle_count and a != b:
                constraints.append([offset + a, offset + b])
        if cloth_settings is None:
            cloth_settings = batch

    if particles:
        settings = cloth_settings or {}
        raw_colliders = manifest.get("cloth_colliders", ())
        colliders = (
            copy.deepcopy(list(raw_colliders))
            if isinstance(raw_colliders, Sequence) and not isinstance(raw_colliders, (str, bytes, bytearray))
            else []
        )
        result["cloth"] = {
            "schema_version": 1,
            "enabled": True,
            "paused": False,
            "show_pins": False,
            "show_colliders": False,
            "wind_strength": 0.0,
            "wind_direction_degrees": 35.0,
            "reset_generation": 0,
            "gravity": _safe_float(settings.get("cloth_gravity"), -10.0),
            "damping": _safe_float(settings.get("cloth_damping"), 0.65),
            "air_resistance": _safe_float(settings.get("cloth_air_resistance"), 1.0),
            "wind_response": _safe_float(settings.get("cloth_wind_response"), 0.4),
            "solver_iterations": max(1, _safe_int(settings.get("cloth_solver_iterations"), 30)),
            "particles": particles,
            "pin_weights": pins,
            "constraints": constraints,
            "colliders": colliders,
        }
    return result


def parsed_mesh_from_model_preview(model: object) -> ParsedMesh:
    """Adapt the Python preview decoder result to the canonical package input."""

    center = _vec3(getattr(model, "normalization_center", (0.0, 0.0, 0.0))) or (0.0, 0.0, 0.0)
    scale = _safe_float(getattr(model, "normalization_scale", 1.0), 1.0)
    if abs(scale) <= 1.0e-12:
        scale = 1.0
    submeshes: list[SubMesh] = []
    for fallback_index, source in enumerate(tuple(getattr(model, "meshes", ()) or ())):
        positions = [
            (
                _safe_float(position[0]) / scale + center[0],
                _safe_float(position[1]) / scale + center[1],
                _safe_float(position[2]) / scale + center[2],
            )
            for position in tuple(getattr(source, "positions", ()) or ())
            if isinstance(position, Sequence) and len(position) >= 3
        ]
        raw_indices = tuple(getattr(source, "indices", ()) or ())
        indices = [_safe_int(value, -1) for value in raw_indices]
        faces = [
            (indices[offset], indices[offset + 1], indices[offset + 2])
            for offset in range(0, len(indices) - 2, 3)
            if all(0 <= indices[offset + corner] < len(positions) for corner in range(3))
        ]
        if not positions or not faces:
            continue
        source_index = _safe_int(getattr(source, "source_submesh_index", fallback_index), fallback_index)
        submesh = SubMesh(
            name=str(getattr(source, "editor_part_name", "") or f"part_{source_index}"),
            material=str(getattr(source, "material_name", "") or ""),
            texture=str(getattr(source, "texture_name", "") or ""),
            vertices=positions,
            uvs=list(tuple(getattr(source, "texture_coordinates", ()) or ())),
            normals=list(tuple(getattr(source, "normals", ()) or ())),
            faces=faces,
            source_vertex_map=list(tuple(getattr(source, "source_vertex_indices", ()) or ())),
            source_vertex_map_authority="python_preview_decoder",
            vertex_count=len(positions),
            face_count=len(faces),
            source_index_count=len(faces) * 3,
        )
        copy_extra_submesh_attrs(source, submesh)
        setattr(submesh, "preview_role", str(getattr(source, "preview_role", "") or "archive_model"))
        setattr(
            submesh,
            "preview_source_asset_path",
            str(getattr(source, "preview_source_asset_path", "") or getattr(model, "path", "") or ""),
        )
        setattr(submesh, "cdmw_mesh_edit_topology_source_submesh_index", source_index)
        setattr(submesh, "cdmw_native_source_submesh_index", source_index)
        setattr(submesh, "cdmw_native_source_local_submesh_index", source_index)
        submeshes.append(submesh)
    if not submeshes:
        raise ValueError("Python preview decoder produced no canonical mesh geometry.")
    minimum = tuple(min(vertex[axis] for submesh in submeshes for vertex in submesh.vertices) for axis in range(3))
    maximum = tuple(max(vertex[axis] for submesh in submeshes for vertex in submesh.vertices) for axis in range(3))
    mesh = ParsedMesh(
        path=str(getattr(model, "path", "") or getattr(model, "source_path", "") or ""),
        format=str(getattr(model, "format", "") or "pac"),
        bbox_min=minimum,
        bbox_max=maximum,
        submeshes=submeshes,
        has_uvs=all(len(submesh.uvs) == len(submesh.vertices) for submesh in submeshes),
    )
    refresh_mesh_totals(mesh)
    setattr(mesh, "cdmw_preview_overlays", rust_preview_overlays_from_model(model))
    return mesh


def rust_preview_overlays_from_model(model: object) -> dict[str, object]:
    center = _vec3(getattr(model, "normalization_center", (0.0, 0.0, 0.0))) or (0.0, 0.0, 0.0)
    scale = _safe_float(getattr(model, "normalization_scale", 1.0), 1.0)
    if abs(scale) <= 1.0e-12:
        scale = 1.0

    def source_point(value: object) -> list[float]:
        point = _vec3(value) or (0.0, 0.0, 0.0)
        return [point[axis] / scale + center[axis] for axis in range(3)]

    result: dict[str, object] = {}
    physics = getattr(model, "physics_overlay", None)
    bones = []
    for bone in tuple(getattr(physics, "bones", ()) or ())[:4096]:
        bones.append(
            {
                "name": str(getattr(bone, "name", "") or ""),
                "index": _safe_int(getattr(bone, "index", -1), -1),
                "parent_index": _safe_int(getattr(bone, "parent_index", -1), -1),
                "parent_name": str(getattr(bone, "parent_name", "") or ""),
                "position": source_point(getattr(bone, "position", ())),
                "parent_position": source_point(getattr(bone, "parent_position", ())),
                "source_path": str(getattr(bone, "source_path", "") or ""),
            }
        )
    if bones:
        result["skeleton"] = {
            "schema_version": 1,
            "enabled": True,
            "read_only": True,
            "bone_count": len(bones),
            "pose_enabled": bool(getattr(physics, "skeleton_pose_enabled", False)),
            "selected_bone_index": _safe_int(
                getattr(physics, "skeleton_selected_bone_index", -1),
                -1,
            ),
            "bones": bones,
        }

    particles: list[list[float]] = []
    pins: list[float] = []
    constraints: list[list[int]] = []
    settings: object | None = None
    cloth = getattr(model, "cloth_preview", None)
    for batch in tuple(getattr(cloth, "batches", ()) or ()):
        offset = len(particles)
        batch_positions = tuple(getattr(batch, "positions", ()) or ())
        particles.extend(source_point(position) for position in batch_positions)
        batch_pins = tuple(getattr(batch, "pin_weights", ()) or ())
        pins.extend(
            max(0.0, min(1.0, _safe_float(batch_pins[index], 0.0)))
            if index < len(batch_pins)
            else 0.0
            for index in range(len(batch_positions))
        )
        for constraint in tuple(getattr(batch, "constraints", ()) or ()):
            a = _safe_int(getattr(constraint, "a", -1), -1)
            b = _safe_int(getattr(constraint, "b", -1), -1)
            if 0 <= a < len(batch_positions) and 0 <= b < len(batch_positions) and a != b:
                constraints.append([offset + a, offset + b])
        settings = settings or getattr(batch, "material_settings", None)
    if particles:
        colliders = []
        for shape in tuple(getattr(physics, "shapes", ()) or ())[:4096]:
            kind = str(getattr(shape, "shape_type", "") or "").strip().lower()
            if "capsule" in kind:
                colliders.append(
                    {
                        "kind": "capsule",
                        "a": source_point(getattr(shape, "capsule_start", ())),
                        "b": source_point(getattr(shape, "capsule_end", ())),
                        "radius": max(0.0, _safe_float(getattr(shape, "radius", 0.0)) / scale),
                    }
                )
            elif "sphere" in kind:
                colliders.append(
                    {
                        "kind": "sphere",
                        "center": source_point(getattr(shape, "center", ())),
                        "radius": max(0.0, _safe_float(getattr(shape, "radius", 0.0)) / scale),
                    }
                )
            elif "box" in kind or "aabb" in kind:
                colliders.append(
                    {
                        "kind": "aabb",
                        "a": source_point(getattr(shape, "bounds_min", ())),
                        "maximum": source_point(getattr(shape, "bounds_max", ())),
                    }
                )
        result["cloth"] = {
            "schema_version": 1,
            "enabled": True,
            "paused": False,
            "show_pins": False,
            "show_colliders": False,
            "wind_strength": 0.0,
            "wind_direction_degrees": 35.0,
            "reset_generation": 0,
            "gravity": _safe_float(getattr(settings, "gravity", -10.0), -10.0),
            "damping": _safe_float(getattr(settings, "damping", 0.65), 0.65),
            "air_resistance": _safe_float(getattr(settings, "air_resistance", 1.0), 1.0),
            "wind_response": _safe_float(getattr(settings, "wind_response", 0.4), 0.4),
            "solver_iterations": max(1, _safe_int(getattr(settings, "solver_iterations", 30), 30)),
            "particles": particles,
            "pin_weights": pins,
            "constraints": constraints,
            "colliders": colliders,
        }
    return result


def rust_preview_package_cache_key(
    archive_identity: str,
    *,
    sidecar_generation: int = 0,
    source_manifest: Mapping[str, object] | None = None,
) -> str:
    manifest = source_manifest if isinstance(source_manifest, Mapping) else {}
    payload = {
        "schema": RUST_PREVIEW_PACKAGE,
        "cache_schema": RUST_PREVIEW_CACHE_SCHEMA,
        "compiler_schema": RUST_MESH_AUTHORING_PACKAGE,
        "preview_backend": RUST_PREVIEW_BACKEND,
        "archive_identity": str(archive_identity or ""),
        "sidecar_generation": max(0, int(sidecar_generation)),
        "source_schema": _safe_int(manifest.get("schema_version"), 0),
        "source_material_semantics": _safe_int(manifest.get("material_semantics_version"), 0),
        "source_material_graph": _safe_int(manifest.get("material_graph_version"), 0),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def rust_preview_package_cache_root(cache_root: Path | str) -> Path:
    """Return the renderer-specific cache tier without touching legacy data."""

    return Path(cache_root) / "rust_wgpu_v1"


def _validate_rust_cache_package(package_dir: Path) -> tuple[bool, tuple[str, ...]]:
    missing = validate_rust_preview_package(package_dir)
    return not missing, missing


def validate_rust_preview_cache_package(package_dir: Path | str) -> tuple[bool, tuple[str, ...]]:
    """Validate one derived Rust package without touching its source package."""

    return _validate_rust_cache_package(Path(package_dir))


def _source_manifest(package_dir: Path) -> Mapping[str, object]:
    try:
        payload = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def build_or_lookup_rust_preview_package(
    preview_core_package_dir: Path | str,
    *,
    cache_root: Path,
    archive_identity: str,
    sidecar_generation: int = 0,
    cache_mode: str = "balanced",
    max_bytes: int = 0,
    target_bytes: int = 0,
    cancelled: Callable[[], bool] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> RustPreviewPackage:
    """Build the Rust viewport package from authoritative Preview Core output.

    The source Preview Core package remains immutable; only the Rust cache
    namespace receives derived renderer input.
    """

    source_package = Path(preview_core_package_dir).expanduser().resolve()
    source_manifest = _source_manifest(source_package)
    if not source_manifest:
        raise ValueError("Preview-core package manifest is missing or invalid.")
    started = time.perf_counter()
    cache_key = rust_preview_package_cache_key(
        archive_identity,
        sidecar_generation=sidecar_generation,
        source_manifest=source_manifest,
    )
    derived_cache_root = rust_preview_package_cache_root(cache_root)
    durable = str(cache_mode or "off").strip().lower() in {"balanced", "aggressive"} and max_bytes > 0

    def build(output_package_dir: Path) -> RustPreviewPackage:
        overlays = rust_preview_overlays_from_preview_core_package(
            source_package,
            cancelled=cancelled,
        )
        _check_cancelled(cancelled)
        if _safe_int(source_manifest.get("schema_version"), 0) >= 8:
            return build_rust_preview_package_from_preview_core(
                source_package,
                source_manifest=source_manifest,
                output_package_dir=output_package_dir,
                preview_overlays=overlays,
                cancelled=cancelled,
            )
        mesh = decode_dotnet_native_preview_package(source_package, cancelled=cancelled)
        return build_rust_preview_package(
            mesh,
            output_package_dir=output_package_dir,
            preview_overlays=overlays,
            material_package_path=source_package,
            cancelled=cancelled,
        )

    if durable:
        with dotnet_preview_package_cache_build_lock(derived_cache_root, cache_key):
            _check_cancelled(cancelled)
            hit = lookup_dotnet_preview_package_cache(
                derived_cache_root,
                cache_key,
                validate_package=_validate_rust_cache_package,
            )
            if hit is not None:
                return rust_preview_package_from_path(hit.package_dir)
            staging_entry = create_dotnet_preview_package_staging_dir(
                derived_cache_root,
                leased=True,
            )
            try:
                build(staging_entry / "package")
                cache_metadata = dict(metadata or {})
                cache_metadata.update(
                    {
                        "renderer": "rust_wgpu",
                        "preview_schema": RUST_PREVIEW_PACKAGE,
                        "preview_backend": RUST_PREVIEW_BACKEND,
                        "archive_identity": str(archive_identity or ""),
                        "sidecar_generation": max(0, int(sidecar_generation)),
                        "source_package": str(source_package),
                    }
                )
                hit = store_dotnet_preview_package_cache(
                    derived_cache_root,
                    cache_key,
                    staging_entry,
                    cache_metadata,
                    validate_package=_validate_rust_cache_package,
                    max_bytes=max_bytes,
                    target_bytes=target_bytes,
                )
                if hit is None:
                    raise RuntimeError("Rust preview cache publication failed.")
                return rust_preview_package_from_path(hit.package_dir)
            finally:
                release_dotnet_preview_package_staging_dir(staging_entry, cleanup=True)

    Path(cache_root).mkdir(parents=True, exist_ok=True)
    transient_root = Path(tempfile.mkdtemp(prefix="cdmw_rust_preview_", dir=str(cache_root)))
    package = build(transient_root / "package")
    _LOGGER.info(
        "rust_preview_package source=%s schema=%d elapsed_ms=%.3f",
        source_package,
        _safe_int(source_manifest.get("schema_version"), 0),
        max(0.0, (time.perf_counter() - started) * 1000.0),
    )
    return package


def build_or_lookup_rust_preview_package_from_model(
    model: object,
    *,
    cache_root: Path,
    archive_identity: str,
    sidecar_generation: int = 0,
    cache_mode: str = "balanced",
    max_bytes: int = 0,
    target_bytes: int = 0,
    cancelled: Callable[[], bool] | None = None,
    metadata: Mapping[str, object] | None = None,
    interaction_profile: str = "read_only",
) -> RustPreviewPackage:
    """Build a Rust package from the Python archive preview decoder."""

    profile = str(interaction_profile or "read_only").strip().lower()
    if profile not in {"read_only", "static_replacement"}:
        raise ValueError(f"Unsupported Rust preview interaction profile: {profile}")
    cache_key = rust_preview_package_cache_key(
        f"python:{profile}:" + str(archive_identity or ""),
        sidecar_generation=sidecar_generation,
        source_manifest=_PYTHON_MODEL_PREVIEW_SOURCE_MANIFEST,
    )
    derived_cache_root = rust_preview_package_cache_root(cache_root)
    durable = str(cache_mode or "off").strip().lower() in {"balanced", "aggressive"} and max_bytes > 0
    if durable:
        with dotnet_preview_package_cache_build_lock(derived_cache_root, cache_key):
            _check_cancelled(cancelled)
            hit = lookup_dotnet_preview_package_cache(
                derived_cache_root,
                cache_key,
                validate_package=_validate_rust_cache_package,
            )
            if hit is not None:
                return rust_preview_package_from_path(hit.package_dir)
            staging_entry = create_dotnet_preview_package_staging_dir(derived_cache_root, leased=True)
            try:
                mesh = parsed_mesh_from_model_preview(model)
                _check_cancelled(cancelled)
                build_rust_preview_package(
                    mesh,
                    output_package_dir=staging_entry / "package",
                    cancelled=cancelled,
                    preview_overlays=getattr(mesh, "cdmw_preview_overlays", None),
                    interaction_profile=profile,
                )
                cache_metadata = dict(metadata or {})
                cache_metadata.update(
                    {
                        "renderer": "rust_wgpu",
                        "preview_schema": RUST_PREVIEW_PACKAGE,
                        "preview_backend": RUST_PREVIEW_BACKEND,
                        "archive_identity": str(archive_identity or ""),
                        "sidecar_generation": max(0, int(sidecar_generation)),
                        "source_decoder": "python_model_preview",
                    }
                )
                hit = store_dotnet_preview_package_cache(
                    derived_cache_root,
                    cache_key,
                    staging_entry,
                    cache_metadata,
                    validate_package=_validate_rust_cache_package,
                    max_bytes=max_bytes,
                    target_bytes=target_bytes,
                )
                if hit is None:
                    raise RuntimeError("Rust preview package cache publication failed.")
                return rust_preview_package_from_path(hit.package_dir)
            finally:
                release_dotnet_preview_package_staging_dir(staging_entry, cleanup=True)

    _check_cancelled(cancelled)
    Path(cache_root).mkdir(parents=True, exist_ok=True)
    transient_root = Path(tempfile.mkdtemp(prefix="cdmw_rust_preview_", dir=str(cache_root)))
    mesh = parsed_mesh_from_model_preview(model)
    return build_rust_preview_package(
        mesh,
        output_package_dir=transient_root / "package",
        cancelled=cancelled,
        preview_overlays=getattr(mesh, "cdmw_preview_overlays", None),
        interaction_profile=profile,
    )


def lookup_rust_preview_package_from_model_identity(
    *,
    cache_root: Path,
    archive_identity: str,
    sidecar_generation: int = 0,
    interaction_profile: str = "read_only",
    cancelled: Callable[[], bool] | None = None,
) -> RustPreviewPackage | None:
    """Return a valid canonical Python-model package without decoding its source."""

    hit = lookup_rust_preview_package_hit_from_model_identity(
        cache_root=cache_root,
        archive_identity=archive_identity,
        sidecar_generation=sidecar_generation,
        interaction_profile=interaction_profile,
        cancelled=cancelled,
    )
    return hit[0] if hit is not None else None


def lookup_rust_preview_package_hit_from_model_identity(
    *,
    cache_root: Path,
    archive_identity: str,
    sidecar_generation: int = 0,
    interaction_profile: str = "read_only",
    cancelled: Callable[[], bool] | None = None,
) -> tuple[RustPreviewPackage, dict[str, object]] | None:
    """Return a canonical Python-model package and its publication metadata."""

    _check_cancelled(cancelled)
    profile = str(interaction_profile or "read_only").strip().lower()
    if profile not in {"read_only", "static_replacement"}:
        raise ValueError(f"Unsupported Rust preview interaction profile: {profile}")
    cache_key = rust_preview_package_cache_key(
        f"python:{profile}:" + str(archive_identity or ""),
        sidecar_generation=sidecar_generation,
        source_manifest=_PYTHON_MODEL_PREVIEW_SOURCE_MANIFEST,
    )
    hit = lookup_dotnet_preview_package_cache(
        rust_preview_package_cache_root(cache_root),
        cache_key,
        validate_package=_validate_rust_cache_package,
    )
    _check_cancelled(cancelled)
    if hit is None:
        return None
    return rust_preview_package_from_path(hit.package_dir), dict(hit.metadata)


def build_rust_preview_cache_prewarm_package(cache_root: Path) -> RustPreviewPackage:
    """Compatibility alias for the viewport-only Rust prewarm package."""

    return build_rust_preview_prewarm_package(cache_root)


__all__ = [
    "build_or_lookup_rust_preview_package",
    "build_or_lookup_rust_preview_package_from_model",
    "build_rust_preview_cache_prewarm_package",
    "rust_preview_overlays_from_model",
    "rust_preview_overlays_from_preview_core_package",
    "rust_preview_package_cache_key",
    "lookup_rust_preview_package_from_model_identity",
    "lookup_rust_preview_package_hit_from_model_identity",
    "parsed_mesh_from_model_preview",
    "rust_preview_package_cache_root",
    "RUST_PREVIEW_CACHE_SCHEMA",
    "validate_rust_preview_package",
    "validate_rust_preview_cache_package",
]
