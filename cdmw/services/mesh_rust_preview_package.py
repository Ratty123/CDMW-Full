"""Bounded viewport-only packages for the resident Rust Archive Preview.

The package deliberately reuses the same PAC/PAC_XML material preparation as
the Rust Mesh Editor.  It contains renderer-ready geometry, original DDS
payloads and material ownership, but no editable output directory or Vortice
handoff files.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import mmap
import os
import struct
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from cdmw.services.mesh_rust_authoring import _RustMaterialSynthesisState

from cdmw.core.atomic_file import atomic_write_bytes, atomic_write_text
from cdmw.domain.cancellation import RunCancelled
from cdmw.services.mesh_rust_preview_files import atomic_preview_publication, validate_preview_files
from cdmw.modding.mesh_deformer import clone_mesh_for_editing
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.static_mesh_scene_frame import (
    StaticMeshSceneFrame,
    StaticSceneRoleFrame,
    StaticWorldBounds,
    build_authoritative_static_scene_frame,
    static_scene_source_identity,
)
from cdmw.modding.static_mesh_types import StaticReplacementTransform
from cdmw.services.mesh_dotnet_material_bindings import (
    apply_dotnet_native_material_batch_binding,
)
from cdmw.services.mesh_rust_contract import (
    RUST_MESH_RENDERER,
    RUST_PREVIEW_BACKEND,
    RUST_PREVIEW_PACKAGE,
    RUST_PREVIEW_PROTOCOL,
)

_PREVIEW_CORE_VERTEX = struct.Struct("<23f")
_PREVIEW_CORE_IDENTITY = struct.Struct("<2i")
_PREVIEW_CORE_SCHEMA_MINIMUM = 8
_PREVIEW_CORE_MATERIAL_GRAPH_VERSION = 4
_PREVIEW_CORE_MATERIAL_SEMANTICS_VERSION = 10
_PREVIEW_CORE_BATCH_LIMIT = 4_096
_PREVIEW_CORE_VERTEX_LIMIT = 2_000_000
_PREVIEW_CORE_COPY_CHUNK_BYTES = 4 * 1024 * 1024
_RUST_PREVIEW_MATERIAL_QUALITIES = frozenset({"direct", "full"})
_PREVIEW_CORE_MATERIAL_GRAPH_SCHEMA = 1
_PREVIEW_CORE_MATERIAL_LAYER_LIMIT = 64
_PREVIEW_CORE_MATERIAL_RESOURCE_LIMIT = 4_096
_PREVIEW_CORE_MATERIAL_RESOURCE_BYTES = 512 * 1024 * 1024
_EFFECT_TEXTURE_RESOURCE_LIMIT = 128
_EFFECT_TEXTURE_FILE_BYTES = 64 * 1024 * 1024
_EFFECT_TEXTURE_TOTAL_BYTES = 512 * 1024 * 1024


def _write_effect_texture_resources(
    package_dir: Path,
    resources: Mapping[str, bytes],
    *,
    expected_root_identity: tuple[int, int],
    cancelled: Callable[[], bool] | None,
) -> tuple[dict[str, str], list[dict[str, object]]]:
    """Publish bounded, hash-addressed DDS sprites inside an immutable package."""

    from cdmw.services.mesh_rust_authoring import (
        _session_root_identity,
    )

    if len(resources) > _EFFECT_TEXTURE_RESOURCE_LIMIT:
        raise ValueError("Effect preview contains too many sprite textures.")
    texture_dir = package_dir / "effect_textures"
    files: dict[str, str] = {}
    references: list[dict[str, object]] = []
    written: dict[str, dict[str, object]] = {}
    aggregate = 0
    for raw_archive_path, raw_data in resources.items():
        _cancelled(cancelled)
        archive_path = str(raw_archive_path or "").strip().replace("\\", "/")
        components = tuple(archive_path.split("/"))
        if (
            not archive_path
            or len(archive_path) > 1_024
            or "\x00" in archive_path
            or PurePosixPath(archive_path).is_absolute()
            or any(component in {"", ".", ".."} for component in components)
            or ":" in components[0]
            or archive_path in files
        ):
            raise ValueError("Effect preview texture archive path is invalid.")
        data = bytes(raw_data)
        if (
            len(data) < 128
            or len(data) > _EFFECT_TEXTURE_FILE_BYTES
            or not data.startswith(b"DDS ")
        ):
            raise ValueError(f"Effect preview texture is not a bounded DDS resource: {archive_path}")
        digest = hashlib.sha256(data).hexdigest().upper()
        aggregate += len(data) if digest not in written else 0
        if aggregate > _EFFECT_TEXTURE_TOTAL_BYTES:
            raise ValueError("Effect preview sprite textures exceed the aggregate size limit.")
        relative = f"effect_textures/{digest.casefold()}.dds"
        if digest not in written:
            texture_dir.mkdir(parents=True, exist_ok=True)
            _session_root_identity(package_dir, expected_root_identity)
            atomic_write_bytes(package_dir / Path(relative), data)
            _session_root_identity(package_dir, expected_root_identity)
            written[digest] = {
                "path": relative,
                "data_type": "effect_sprite_dds",
                "count": 1,
                "byte_length": len(data),
                "sha256": digest,
                "content_type": "image/vnd-ms.dds",
            }
        files[archive_path] = relative
        references.append(
            {
                "archive_path": archive_path,
                "file": dict(written[digest]),
            }
        )
    return files, references


def semantic_initial_view(
    bounds: tuple[Sequence[float], Sequence[float]],
    normal_axis: str,
) -> dict[str, list[float]]:
    """Describe a stable broadside view without baking camera angles into Qt.

    The thinnest/template-normal axis faces the camera and the longest remaining
    axis is kept upright. Keeping this semantic lets the renderer frame the same
    authored side at every DPI and aspect ratio.
    """

    low, high = bounds
    minimum = [float(low[index]) for index in range(3)]
    maximum = [float(high[index]) for index in range(3)]
    extents = [abs(maximum[index] - minimum[index]) for index in range(3)]
    axis = {"x": 0, "y": 1, "z": 2}.get(str(normal_axis or "y").casefold(), 1)
    upright = max((index for index in range(3) if index != axis), key=extents.__getitem__)
    view_direction = [0.0, 0.0, 0.0]
    screen_up_direction = [0.0, 0.0, 0.0]
    view_direction[axis] = 1.0
    screen_up_direction[upright] = 1.0
    return {
        "view_direction": view_direction,
        "screen_up_direction": screen_up_direction,
        "fit_bounds": [minimum, maximum],
    }


@dataclass(frozen=True, slots=True)
class RustPreviewPackage:
    package_dir: Path
    manifest_path: Path
    status_path: Path
    output_dir: Path
    edit_operations_path: Path
    material_signature: str = ""
    scene_frame: StaticMeshSceneFrame | None = None
    scene_session_id: str = ""
    editable_submesh_count: int = 0
    reference_submesh_count: int = 0
    runtime_output_external: bool = False


class _CancellationView:
    """The Rust material builder only needs Event.is_set().

    Adapting the caller's cancellation callback keeps long PAC/PAC_XML material
    synthesis cancellable without owning a second polling thread.
    """

    def __init__(self, callback: Callable[[], bool] | None) -> None:
        self._callback = callback

    def is_set(self) -> bool:
        return bool(self._callback is not None and self._callback())


def normalize_rust_preview_material_quality(value: object) -> str:
    """Return the bounded Rust preview material tier used by package builders."""

    quality = str(value or "full").strip().casefold()
    if quality not in _RUST_PREVIEW_MATERIAL_QUALITIES:
        raise ValueError(f"Unsupported preview material quality: {quality}")
    return quality


_PREVIEW_IMAGE_TEXTURES = (
    ("base", "preview_texture_dds_path", ("preview_texture_path", "texture")),
    (
        "normal",
        "preview_normal_texture_dds_path",
        ("preview_normal_texture_path",),
    ),
    (
        "material",
        "preview_material_texture_dds_path",
        ("preview_material_texture_path",),
    ),
    (
        "height",
        "preview_height_texture_dds_path",
        ("preview_height_texture_path",),
    ),
    (
        "emissive",
        "preview_emissive_texture_dds_path",
        ("preview_emissive_texture_path",),
    ),
)


def _existing_preview_image(source: object, attributes: Sequence[str]) -> Path | None:
    for attribute in attributes:
        value = str(getattr(source, attribute, "") or "").strip()
        if not value:
            continue
        try:
            path = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if path.is_file() and path.suffix.casefold() in {
            ".bmp",
            ".gif",
            ".jpeg",
            ".jpg",
            ".png",
            ".tga",
            ".tif",
            ".tiff",
            ".webp",
        }:
            return path
    return None


def _encode_non_dds_preview_textures(
    mesh: ParsedMesh,
    staging_root: Path,
    stop_event: _CancellationView,
    synthesis: _RustMaterialSynthesisState,
) -> dict[tuple[int, int, str], Path]:
    """Convert external-model images to owned DDS while preserving PAC DDS unchanged."""

    from cdmw.services.mesh_rust_authoring import (
        _RustMaterialSynthesisState,
        _encode_rust_preview_dds_batch,
        _mesh_lods,
    )

    overrides: dict[tuple[int, int, str], Path] = {}
    encoded_sources: dict[tuple[Path, str], Path] = {}
    bindings: list[tuple[object, str, int, int, str, Path]] = []
    for lod_index, submeshes in enumerate(_mesh_lods(mesh)):
        for submesh_index, submesh in enumerate(submeshes):
            for role, dds_attribute, image_attributes in _PREVIEW_IMAGE_TEXTURES:
                declared_dds = str(getattr(submesh, dds_attribute, "") or "").strip()
                if declared_dds:
                    try:
                        dds_path = Path(declared_dds).expanduser().resolve(strict=True)
                    except (OSError, RuntimeError):
                        dds_path = None
                    if dds_path is not None and dds_path.is_file():
                        continue
                image_path = _existing_preview_image(submesh, image_attributes)
                if image_path is None:
                    continue
                source_key = (image_path, role)
                target = encoded_sources.get(source_key)
                if target is None:
                    target = staging_root / (
                        f"texture-{len(encoded_sources):04d}-{role}.dds"
                    )
                    encoded_sources[source_key] = target
                bindings.append(
                    (submesh, dds_attribute, lod_index, submesh_index, role, target)
                )

    _encode_rust_preview_dds_batch(
        tuple(
            (image_path, target, role)
            for (image_path, role), target in encoded_sources.items()
        ),
        stop_event,  # type: ignore[arg-type]
        synthesis,
    )
    for submesh, dds_attribute, lod_index, submesh_index, role, target in bindings:
        setattr(submesh, dds_attribute, str(target))
        overrides[
            (lod_index, submesh_index, "base_color" if role == "base" else role)
        ] = target
    return overrides


def _scene_mesh(mesh: ParsedMesh, reference_mesh: ParsedMesh | None) -> ParsedMesh:
    from cdmw.modding.mesh_edit_ops import refresh_mesh_totals

    scene = clone_mesh_for_editing(mesh)
    if reference_mesh is not None:
        reference = clone_mesh_for_editing(reference_mesh)
        for index, submesh in enumerate(reference.submeshes):
            submesh.name = f"original_reference_{index}_{submesh.name or 'part'}"
        scene.submeshes.extend(reference.submeshes)
    refresh_mesh_totals(scene)
    return scene


def _part_identities(mesh: ParsedMesh) -> list[dict[str, object]]:
    return [
        {
            "scene_submesh_index": index,
            "source_submesh_index": int(
                getattr(submesh, "source_submesh_index", index) or index
            ),
            "name": str(getattr(submesh, "name", "") or f"Part {index + 1}"),
            "material": str(getattr(submesh, "material", "") or ""),
        }
        for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ()))
    ]


def _cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise RunCancelled("preview package preparation cancelled.")


def _preview_core_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _preview_core_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _preview_core_vec3(value: object) -> tuple[float, float, float] | None:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) < 3
    ):
        return None
    result = tuple(_preview_core_float(component, float("nan")) for component in value[:3])
    return result if all(math.isfinite(component) for component in result) else None  # type: ignore[return-value]


def _preview_core_child(package_dir: Path, value: object) -> Path | None:
    text = str(value or "").strip().replace("/", os.sep)
    if not text:
        return None
    try:
        root = package_dir.resolve(strict=True)
        child = (root / text).resolve(strict=True)
        child.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return child if child.is_file() else None


def _copy_preview_core_binary(
    package_dir: Path,
    source: Path,
    *,
    file_index: int,
    kind: str,
    data_type: str,
    element_count: int,
    expected_byte_length: int,
    expected_root_identity: tuple[int, int],
    cancelled: Callable[[], bool] | None,
) -> dict[str, object]:
    from cdmw.services.mesh_rust_authoring import (
        _session_root_identity,
    )

    if kind not in {"geometry", "identity"}:
        raise ValueError("Unsupported Preview Core binary role.")
    if expected_byte_length <= 0:
        raise ValueError("Preview Core binary payload is empty.")
    try:
        source_before = source.stat()
    except OSError as exc:
        raise ValueError("Preview Core binary payload is missing.") from exc
    if source_before.st_size != expected_byte_length or source.is_symlink():
        raise ValueError("Preview Core binary payload size does not match its manifest.")

    temporary = package_dir / f".preview-{kind}-{file_index:04d}-{uuid4().hex}.tmp"
    digest = hashlib.sha256()
    byte_length = 0
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            while True:
                _cancelled(cancelled)
                block = reader.read(_PREVIEW_CORE_COPY_CHUNK_BYTES)
                if not block:
                    break
                writer.write(block)
                digest.update(block)
                byte_length += len(block)
            writer.flush()
            os.fsync(writer.fileno())
        source_after = source.stat()
        source_identity_before = (
            int(source_before.st_dev),
            int(source_before.st_ino),
            int(source_before.st_size),
            int(source_before.st_mtime_ns),
        )
        source_identity_after = (
            int(source_after.st_dev),
            int(source_after.st_ino),
            int(source_after.st_size),
            int(source_after.st_mtime_ns),
        )
        if source_identity_before != source_identity_after or byte_length != expected_byte_length:
            raise ValueError("Preview Core binary payload changed while it was copied.")
        sha256 = digest.hexdigest().upper()
        name = f"preview-{kind}-{file_index:04d}-{sha256[:12].lower()}.bin"
        destination = package_dir / name
        _cancelled(cancelled)
        _session_root_identity(package_dir, expected_root_identity)
        os.replace(temporary, destination)
        return {
            "path": name,
            "data_type": data_type,
            "count": element_count,
            "byte_length": byte_length,
            "sha256": sha256,
            "content_type": "application/octet-stream",
        }
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def _preview_core_material_source(package_dir: Path, value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    try:
        if candidate.is_absolute():
            candidate = candidate.resolve(strict=True)
        else:
            candidate = _preview_core_child(package_dir, text)
    except (OSError, RuntimeError):
        return None
    if (
        candidate is None
        or not candidate.is_file()
        or candidate.is_symlink()
        or candidate.suffix.casefold() != ".dds"
    ):
        return None
    return candidate


def _preview_core_material_resource_index(
    package_dir: Path,
    textures: Sequence[object],
) -> tuple[dict[str, dict[str, object]], int, int]:
    resources: dict[str, dict[str, object]] = {}
    next_index = 0
    total_bytes = 0
    for raw_texture in textures:
        if not isinstance(raw_texture, Mapping):
            continue
        raw_file = raw_texture.get("file")
        if not isinstance(raw_file, Mapping):
            continue
        reference = copy.deepcopy(dict(raw_file))
        sha256 = str(reference.get("sha256", "") or "").strip().upper()
        path = str(reference.get("path", "") or "").strip()
        try:
            byte_length = int(reference.get("byte_length", 0))
        except (TypeError, ValueError, OverflowError):
            byte_length = 0
        if len(sha256) == 64 and byte_length > 0 and (package_dir / path).is_file():
            if sha256 not in resources:
                resources[sha256] = reference
                total_bytes += byte_length
        stem = Path(path).stem.split("-")
        if len(stem) >= 3 and stem[0] == "texture" and stem[1].isdigit():
            next_index = max(next_index, int(stem[1]) + 1)
    return resources, next_index, total_bytes


def _copy_preview_core_material_resource(
    package_dir: Path,
    source: Path,
    *,
    expected_root_identity: tuple[int, int],
    resources: dict[str, dict[str, object]],
    next_index: int,
    aggregate_bytes: int,
    cancelled: Callable[[], bool] | None,
) -> tuple[dict[str, object], int, int]:
    from cdmw.services.mesh_rust_authoring import (
        _session_root_identity,
    )

    try:
        source_size = source.stat().st_size
    except OSError as exc:
        raise ValueError("Preview Core material DDS is missing.") from exc
    if source_size <= 0 or source_size > _PREVIEW_CORE_MATERIAL_RESOURCE_BYTES:
        raise ValueError("Preview Core material DDS is outside the package size limit.")
    temporary = package_dir / f".material-texture-{uuid4().hex}.tmp"
    digest = hashlib.sha256()
    byte_length = 0
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            source_before = os.fstat(reader.fileno())
            while True:
                _cancelled(cancelled)
                block = reader.read(_PREVIEW_CORE_COPY_CHUNK_BYTES)
                if not block:
                    break
                digest.update(block)
                writer.write(block)
                byte_length += len(block)
                if aggregate_bytes + byte_length > _PREVIEW_CORE_MATERIAL_RESOURCE_BYTES:
                    raise ValueError(
                        "Preview Core material DDS resources exceed the 512 MiB package limit."
                    )
            writer.flush()
            os.fsync(writer.fileno())
            source_after = os.fstat(reader.fileno())
        before = (
            int(source_before.st_dev),
            int(source_before.st_ino),
            int(source_before.st_size),
            int(source_before.st_mtime_ns),
        )
        after = (
            int(source_after.st_dev),
            int(source_after.st_ino),
            int(source_after.st_size),
            int(source_after.st_mtime_ns),
        )
        if before != after or byte_length != source_size:
            raise ValueError("Preview Core material DDS changed while it was copied.")
        sha256 = digest.hexdigest().upper()
        existing = resources.get(sha256)
        if existing is not None:
            return copy.deepcopy(existing), next_index, aggregate_bytes
        if len(resources) >= _PREVIEW_CORE_MATERIAL_RESOURCE_LIMIT:
            raise ValueError("Preview Core material graph contains too many unique DDS resources.")
        while True:
            name = f"texture-{next_index:04d}-{sha256[:12].lower()}.dds"
            next_index += 1
            if not (package_dir / name).exists():
                break
        reference: dict[str, object] = {
            "path": name,
            "data_type": "dds_texture",
            "count": 1,
            "byte_length": byte_length,
            "sha256": sha256,
            "content_type": "image/vnd-ms.dds",
        }
        _cancelled(cancelled)
        _session_root_identity(package_dir, expected_root_identity)
        os.replace(temporary, package_dir / name)
        resources[sha256] = reference
        return copy.deepcopy(reference), next_index, aggregate_bytes + byte_length
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def _preview_core_layer_float(value: object, *, fallback: float = 0.0) -> float:
    result = _preview_core_float(value, fallback)
    return max(0.0, min(1.0, result))


def _preview_core_layer_tint(value: object) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return [1.0, 1.0, 1.0, 1.0]
    components = [
        _preview_core_layer_float(component, fallback=1.0)
        for component in tuple(value)[:4]
    ]
    return (components + [1.0] * 4)[:4]


def _copy_preview_core_material_layers(
    raw_batches, source_package, package_dir, quality, resources, next_index, aggregate_bytes, copied_sources,
    materials, source_edge_count, cancelled, expected_root_identity,
):
    for material_index, raw_batch in enumerate(raw_batches):
        if not isinstance(raw_batch, Mapping):
            raise ValueError("Preview Core material graph contains an invalid batch.")
        raw_layers = raw_batch.get("material_layers")
        if not isinstance(raw_layers, Sequence) or isinstance(
            raw_layers, (str, bytes, bytearray)
        ):
            raise ValueError("Preview Core batch is missing its material-layer graph.")
        if not raw_layers or len(raw_layers) > _PREVIEW_CORE_MATERIAL_LAYER_LIMIT:
            raise ValueError("Preview Core material-layer graph exceeds the bounded layer limit.")
        layers: list[dict[str, object]] = []
        for raw_layer in raw_layers:
            if not isinstance(raw_layer, Mapping):
                raise ValueError("Preview Core material graph contains an invalid layer.")
            role = str(raw_layer.get("layer_role", "") or "").strip().casefold()
            channel = str(raw_layer.get("mask_channel", "") or "").strip().casefold()
            owner = str(raw_layer.get("owner_wrapper_item_id", "") or "").strip()
            wrapper_index = _preview_core_int(raw_layer.get("material_wrapper_index"), -1)
            source_parameter = str(raw_layer.get("source_parameter", "") or "").strip()
            mask_parameter = str(raw_layer.get("mask_parameter", "") or "").strip()
            if (
                raw_layer.get("material_wrapper_index") == -1
                and not owner
                and role == "base"
                and not source_parameter
                and not mask_parameter
                and all(
                    not str(raw_layer.get(f"{resource_role}_{field}", "") or "").strip()
                    for resource_role in ("diffuse", "normal", "material", "height", "mask")
                    for field in ("source", "archive_path")
                )
            ):
                # Preview Core emits an ownerless base when no global map is
                # bound. Give this source-free layer its batch-local Rust index;
                # keep its absent wrapper identity and all textured layers intact.
                wrapper_index = material_index
            if (
                not role
                or len(role) > 32
                or channel not in {"", "r", "g", "b", "a"}
                or len(owner) > 64
                or wrapper_index < 0
                or len(source_parameter) > 128
                or len(mask_parameter) > 128
            ):
                raise ValueError("Preview Core material layer identity is invalid.")
            layer: dict[str, object] = {
                "owner_wrapper_item_id": owner,
                "material_wrapper_index": wrapper_index,
                "layer_role": role,
                "mask_channel": channel,
                "shader_family": str(raw_layer.get("shader_family", "") or "")[:128],
                "shader_rule": str(raw_layer.get("shader_rule", "") or "")[:128],
                "evidence_grade": str(raw_layer.get("evidence_grade", "") or "")[:64],
                "source_parameter": source_parameter,
                "mask_parameter": mask_parameter,
                "weight": _preview_core_layer_float(raw_layer.get("weight"), fallback=1.0),
                "detail_scale": _preview_core_layer_float(raw_layer.get("detail_scale")),
                "roughness_hint": _preview_core_layer_float(raw_layer.get("roughness_hint")),
                "metalness_hint": _preview_core_layer_float(raw_layer.get("metalness_hint")),
                "specular_hint": _preview_core_layer_float(raw_layer.get("specular_hint")),
                "height_scale_hint": _preview_core_layer_float(
                    raw_layer.get("height_scale_hint")
                ),
                "tint": _preview_core_layer_tint(raw_layer.get("tint")),
            }
            layer_has_source = False
            for resource_role in ("diffuse", "normal", "material", "height", "mask"):
                _cancelled(cancelled)
                source_key = f"{resource_role}_source"
                archive_key = f"{resource_role}_archive_path"
                source_text = str(raw_layer.get(source_key, "") or "").strip()
                archive_path = str(raw_layer.get(archive_key, "") or "").strip().replace("\\", "/")
                layer[f"{resource_role}_archive_path"] = archive_path
                reference: dict[str, object] | None = None
                layer[f"{resource_role}_declared"] = bool(source_text)
                if source_text:
                    layer_has_source = True
                    source_edge_count += 1
                    source = _preview_core_material_source(source_package, source_text)
                    if source is None:
                        raise ValueError(
                            f"Preview Core material graph DDS is missing: {archive_path or source_text}"
                        )
                    if quality == "full":
                        source_stat = source.stat()
                        source_identity = (
                            source_stat.st_dev, source_stat.st_ino,
                            source_stat.st_size, source_stat.st_mtime_ns,
                        )
                        cached = copied_sources.get(source)
                        if cached is not None:
                            if cached[0] != source_identity:
                                raise ValueError("Preview Core material DDS changed while its graph was built.")
                            reference = copy.deepcopy(cached[1])
                        else:
                            reference, next_index, aggregate_bytes = (
                                _copy_preview_core_material_resource(
                                    package_dir,
                                    source,
                                    expected_root_identity=expected_root_identity,
                                    resources=resources,
                                    next_index=next_index,
                                    aggregate_bytes=aggregate_bytes,
                                    cancelled=cancelled,
                                )
                            )
                            source_after = source.stat()
                            if source_identity != (
                                source_after.st_dev, source_after.st_ino,
                                source_after.st_size, source_after.st_mtime_ns,
                            ):
                                raise ValueError("Preview Core material DDS changed while its graph was built.")
                            if len(copied_sources) < _PREVIEW_CORE_MATERIAL_RESOURCE_LIMIT:
                                copied_sources[source] = (source_identity, reference)
                layer[resource_role] = reference
            if layer_has_source and not owner:
                raise ValueError("Preview Core material layer lost its wrapper owner identity.")
            if role != "base" and layer.get("diffuse") is not None and not source_parameter:
                raise ValueError("Preview Core visible layer lost its source parameter identity.")
            layers.append(layer)
        material_slot_index = _preview_core_int(raw_batch.get("index"), material_index)
        materials.append(
            {
                "lod_index": 0,
                "material_index": material_index,
                "material_slot_index": material_slot_index,
                "material_name": str(raw_batch.get("material_name", "") or "")[:256],
                "base_color": [
                    _preview_core_layer_float(component, fallback=0.62)
                    for component in tuple(raw_batch.get("base_color", (0.62, 0.62, 0.62)))[:3]
                ],
                "layers": layers,
            }
        )
    return aggregate_bytes, source_edge_count


def _build_preview_core_material_graph(
    source_package: Path,
    package_dir: Path,
    raw_batches: Sequence[object],
    *,
    quality: str,
    textures: Sequence[object],
    expected_root_identity: tuple[int, int],
    cancelled: Callable[[], bool] | None,
) -> dict[str, object]:
    resources, next_index, aggregate_bytes = _preview_core_material_resource_index(
        package_dir,
        textures,
    )
    initial_resource_shas = frozenset(resources)
    copied_sources: dict[Path, tuple[tuple[int, int, int, int], dict[str, object]]] = {}
    materials: list[dict[str, object]] = []
    source_edge_count = 0
    (
        aggregate_bytes, source_edge_count,
    ) = _copy_preview_core_material_layers(
        raw_batches, source_package, package_dir, quality, resources, next_index, aggregate_bytes,
        copied_sources, materials, source_edge_count, cancelled, expected_root_identity,
    )
    copied_resource_shas = set(resources).difference(initial_resource_shas)
    return {
        "schema_version": _PREVIEW_CORE_MATERIAL_GRAPH_SCHEMA,
        "graph_version": _PREVIEW_CORE_MATERIAL_GRAPH_VERSION,
        "semantics_version": _PREVIEW_CORE_MATERIAL_SEMANTICS_VERSION,
        "quality": quality,
        "resources_included": quality == "full",
        "source_edge_count": source_edge_count,
        "unique_resource_count": len(resources),
        "copied_resource_count": len(copied_resource_shas),
        "unique_resource_bytes": aggregate_bytes,
        "materials": materials,
    }


def _rebased_preview_core_batch(
    package_dir: Path,
    batch: Mapping[str, object],
) -> dict[str, object]:
    # Only descriptor source paths change. The binding adapter hydrates its own
    # material inputs; copying every nested parameter at each level multiplies
    # preparation time for PACs with many texture edges.
    result = dict(batch)
    raw_dds = result.get("dds_textures")
    if not isinstance(raw_dds, Mapping):
        return result
    dds: dict[str, object] = dict(raw_dds)

    def rebase_descriptor(value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        descriptor = dict(value)
        text = str(descriptor.get("source_path", "") or "").strip()
        if text and not Path(text).expanduser().is_absolute():
            resolved = _preview_core_child(package_dir, text)
            if resolved is not None:
                descriptor["source_path"] = str(resolved)
        return descriptor

    for slot, value in tuple(dds.items()):
        if slot == "material_inputs" and isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            dds[slot] = [rebase_descriptor(item) for item in value]
        else:
            dds[slot] = rebase_descriptor(value)
    result["dds_textures"] = dds
    return result


def _preview_core_material_sample(
    geometry_path: Path,
    *,
    vertex_count: int,
    center: tuple[float, float, float],
    scale: float,
    cancelled: Callable[[], bool] | None,
) -> tuple[
    list[tuple[float, float, float]],
    list[tuple[float, float]],
    list[tuple[int, int, int]],
]:
    from cdmw.services.mesh_rust_authoring import (
        _deterministic_luminance_face_indices,
    )

    positions: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    faces: list[tuple[int, int, int]] = []
    face_indices = _deterministic_luminance_face_indices(vertex_count // 3)
    with geometry_path.open("rb") as stream, mmap.mmap(
        stream.fileno(), 0, access=mmap.ACCESS_READ
    ) as payload:
        for ordinal, face_index in enumerate(face_indices):
            if ordinal % 128 == 0:
                _cancelled(cancelled)
            base = len(positions)
            for corner in range(3):
                record_index = face_index * 3 + corner
                values = _PREVIEW_CORE_VERTEX.unpack_from(
                    payload,
                    record_index * _PREVIEW_CORE_VERTEX.size,
                )
                positions.append(
                    (
                        values[0] / scale + center[0],
                        values[1] / scale + center[1],
                        values[2] / scale + center[2],
                    )
                )
                uvs.append((values[9], values[10]))
            faces.append((base, base + 1, base + 2))
    _cancelled(cancelled)
    return positions, uvs, faces


def _preview_core_metadata_mesh(
    package_dir: Path,
    manifest: Mapping[str, object],
    prepared_batches: Sequence[tuple[Mapping[str, object], Path, int]],
    *,
    center: tuple[float, float, float],
    scale: float,
    cancelled: Callable[[], bool] | None,
) -> ParsedMesh:
    submeshes: list[SubMesh] = []
    for fallback_index, (raw_batch, geometry_path, vertex_count) in enumerate(prepared_batches):
        batch = _rebased_preview_core_batch(package_dir, raw_batch)
        identity = batch.get("editor_identity")
        identity = identity if isinstance(identity, Mapping) else {}
        raw_index = _preview_core_int(batch.get("index"), fallback_index)
        source_index = _preview_core_int(identity.get("source_submesh_index"), raw_index)
        local_index = _preview_core_int(identity.get("source_local_submesh_index"), 0)
        component_index = _preview_core_int(identity.get("source_component_index"), 0)
        component_label = str(identity.get("source_component_label", "") or "prefab")
        positions, uvs, faces = _preview_core_material_sample(
            geometry_path,
            vertex_count=vertex_count,
            center=center,
            scale=scale,
            cancelled=cancelled,
        )
        submesh = SubMesh(
            name=f"reference_prefab_{component_index}_{local_index}_{component_label}",
            material=str(batch.get("material_name", "") or component_label),
            texture=str(batch.get("texture_name", "") or ""),
            vertices=positions,
            uvs=uvs,
            faces=faces,
            vertex_count=len(positions),
            face_count=len(faces),
            source_index_count=vertex_count,
        )
        setattr(submesh, "source_submesh_index", source_index)
        setattr(submesh, "preview_role", "archive_model")
        setattr(
            submesh,
            "preview_source_asset_path",
            str(identity.get("source_asset_path", "") or manifest.get("source_path", "") or ""),
        )
        setattr(submesh, "cdmw_material_authority_profile", "native_preview_core_direct")
        setattr(submesh, "cdmw_mesh_edit_topology_source_submesh_index", raw_index)
        setattr(submesh, "cdmw_native_source_submesh_index", source_index)
        setattr(submesh, "cdmw_native_source_local_submesh_index", local_index)
        setattr(submesh, "cdmw_native_source_component_index", component_index)
        setattr(submesh, "cdmw_native_source_component_label", component_label)
        setattr(submesh, "cdmw_native_prefab_component", bool(identity.get("prefab_component", False)))
        setattr(submesh, "cdmw_native_context_component", bool(identity.get("context_component", False)))
        setattr(submesh, "cdmw_native_editor_identity", copy.deepcopy(dict(identity)))
        apply_dotnet_native_material_batch_binding(submesh, batch)
        # The draw/source index can differ from the PAC material owner. Keep
        # exact owner identity so the shared skin shader receives its factors.
        material_owners = {
            _preview_core_int(getattr(item, "owner_slot_index", -1), -1)
            for item in getattr(submesh, "preview_material_texture_inputs", ())
            if str(getattr(item, "binding_authority", "")).strip().casefold()
            in {"authoritative", "exact"}
            and _preview_core_int(getattr(item, "owner_slot_index", -1), -1) >= 0
        }
        if len(material_owners) == 1:
            setattr(submesh, "preview_pac_material_owner_slot_index", material_owners.pop())
        submeshes.append(submesh)

    extent = 1.0 / abs(scale)
    mesh = ParsedMesh(
        path=str(manifest.get("source_path", "") or package_dir),
        format=str(manifest.get("format", "") or "pac").strip().lower(),
        bbox_min=tuple(center[axis] - extent for axis in range(3)),
        bbox_max=tuple(center[axis] + extent for axis in range(3)),
        submeshes=submeshes,
        total_vertices=sum(vertex_count for _batch, _path, vertex_count in prepared_batches),
        total_faces=sum(vertex_count // 3 for _batch, _path, vertex_count in prepared_batches),
        has_uvs=True,
    )
    setattr(mesh, "cdmw_preview_core_package_path", str(package_dir))
    return mesh


def _texture_status(textures: Sequence[object], quality: str) -> dict[str, object]:
    return {
        "available": bool(textures),
        "resource_count": len(textures),
        "quality": quality,
        "reason": "" if textures else "No readable DDS preview textures were resolved.",
    }


def _preview_core_scene_frame(metadata_mesh, center, scale, part_identities, preview_overlays, cancelled):
    frame = build_authoritative_static_scene_frame(
        metadata_mesh,
        metadata_mesh,
        StaticReplacementTransform(
            alignment_mode="manual",
            scale_to_original_length=False,
        ),
        source_identity=static_scene_source_identity(metadata_mesh, None),
        scene_generation=1,
        comparison_mode="replacement_only",
        interaction_mode="preview",
        reference_draw="wire",
        cancelled=cancelled,
    )
    framing_extent = max(0.01, 2.0 / abs(scale))
    framing_bounds = StaticWorldBounds(
        tuple(center[axis] - framing_extent * 0.5 for axis in range(3)),
        tuple(center[axis] + framing_extent * 0.5 for axis in range(3)),
    )
    empty_bounds = StaticWorldBounds((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    frame = replace(
        frame,
        editable=replace(frame.editable, world_bounds=framing_bounds),
        reference=StaticSceneRoleFrame(
            role="reference",
            model_matrix=frame.reference.model_matrix,
            world_bounds=empty_bounds,
            visible=False,
            submesh_indices=(),
        ),
        framing_bounds=framing_bounds,
        framing_extent=framing_extent,
    )
    session_id = uuid4().hex
    scene_payload = frame.to_protocol_payload()
    scene_payload.update(
        {
            "renderer_authority": "rust_wgpu_resident_scene",
            "session_id": session_id,
            "part_identities": part_identities,
        }
    )
    if isinstance(preview_overlays, Mapping):
        for source, target_key in (
            ("skeleton", "skeleton_overlay"),
            ("cloth", "cloth_overlay"),
            ("effects", "effects_overlay"),
        ):
            value = preview_overlays.get(source)
            if isinstance(value, Mapping):
                scene_payload[target_key] = dict(value)
    return frame, session_id, scene_payload


def _prepare_preview_core_materials(
    package_dir, metadata_mesh, root_identity, quality, source_package, raw_batches, cancelled,
    include_material_resources,
):
    from cdmw.services.mesh_rust_authoring import (
        _RustMaterialSynthesisState,
        _mesh_material_presentations,
        _mesh_texture_payloads,
    )

    synthesis = _RustMaterialSynthesisState()
    stop_event = _CancellationView(cancelled)
    textures = (
        _mesh_texture_payloads(
            package_dir,
            metadata_mesh,
            expected_root_identity=root_identity,
            stop_event=stop_event,  # type: ignore[arg-type]
            synthesis_state=synthesis,
            material_package_path=source_package,
            enable_material_synthesis=False,
        )
        if include_material_resources
        else []
    )
    preview_core_material_graph = _build_preview_core_material_graph(
        source_package,
        package_dir,
        raw_batches,
        quality=quality,
        textures=textures,
        expected_root_identity=root_identity,
        cancelled=cancelled,
    )
    presentations = _mesh_material_presentations(
        metadata_mesh,
        generated_overrides=synthesis.presentation_overrides,
    )
    _cancelled(cancelled)
    return textures, preview_core_material_graph, presentations


def _copy_preview_core_geometry(raw_batches, source_package, package_dir, root_identity, cancelled):
    prepared_batches: list[tuple[Mapping[str, object], Path, int]] = []
    direct_batches: list[dict[str, object]] = []
    part_identities: list[dict[str, object]] = []
    total_vertices = 0
    batch_indices: set[int] = set()
    for fallback_index, raw_batch in enumerate(raw_batches):
        _cancelled(cancelled)
        if not isinstance(raw_batch, Mapping):
            raise ValueError("Preview Core package contains an invalid batch.")
        raw_index = _preview_core_int(raw_batch.get("index"), fallback_index)
        vertex_count = _preview_core_int(raw_batch.get("vertex_count"), 0)
        if (
            raw_index < 0
            or raw_index > 0xFFFF_FFFF
            or raw_index in batch_indices
            or vertex_count <= 0
            or vertex_count % 3
            or total_vertices + vertex_count > _PREVIEW_CORE_VERTEX_LIMIT
        ):
            raise ValueError("Preview Core batch identity or vertex count is invalid.")
        batch_indices.add(raw_index)
        source_geometry = _preview_core_child(source_package, raw_batch.get("vertex_file"))
        if source_geometry is None:
            raise ValueError("Preview Core geometry is missing or escaped its package.")
        geometry_reference = _copy_preview_core_binary(
            package_dir,
            source_geometry,
            file_index=fallback_index,
            kind="geometry",
            data_type="preview_core_vertices_f32x23_le",
            element_count=vertex_count,
            expected_byte_length=vertex_count * _PREVIEW_CORE_VERTEX.size,
            expected_root_identity=root_identity,
            cancelled=cancelled,
        )
        identity = raw_batch.get("editor_identity")
        identity = identity if isinstance(identity, Mapping) else {}
        identity_reference: dict[str, object] | None = None
        source_identity = _preview_core_child(source_package, identity.get("identity_file"))
        if source_identity is not None:
            try:
                identity_size_matches = (
                    source_identity.stat().st_size
                    == vertex_count * _PREVIEW_CORE_IDENTITY.size
                )
            except OSError:
                identity_size_matches = False
            if identity_size_matches:
                identity_reference = _copy_preview_core_binary(
                    package_dir,
                    source_identity,
                    file_index=fallback_index,
                    kind="identity",
                    data_type="preview_core_identity_i32x2_le",
                    element_count=vertex_count,
                    expected_byte_length=vertex_count * _PREVIEW_CORE_IDENTITY.size,
                    expected_root_identity=root_identity,
                    cancelled=cancelled,
                )
        source_index = _preview_core_int(identity.get("source_submesh_index"), raw_index)
        local_index = _preview_core_int(identity.get("source_local_submesh_index"), 0)
        component_index = _preview_core_int(identity.get("source_component_index"), 0)
        component_label = str(identity.get("source_component_label", "") or "prefab")
        name = f"reference_prefab_{component_index}_{local_index}_{component_label}"
        material = str(raw_batch.get("material_name", "") or component_label)
        direct_batches.append(
            {
                "index": raw_index,
                "name": name,
                "material": material,
                "vertex_count": vertex_count,
                "vertices": geometry_reference,
                "identity": identity_reference,
            }
        )
        part_identities.append(
            {
                "scene_submesh_index": fallback_index,
                "source_submesh_index": source_index,
                "name": name,
                "material": material,
            }
        )
        destination_geometry = package_dir / str(geometry_reference["path"])
        prepared_batches.append((raw_batch, destination_geometry, vertex_count))
        total_vertices += vertex_count
    return prepared_batches, direct_batches, part_identities


def _validated_preview_core_source(preview_core_package_dir, source_manifest):
    source_package = Path(preview_core_package_dir).expanduser().resolve(strict=True)
    manifest = dict(source_manifest or {})
    if not manifest:
        try:
            loaded = json.loads((source_package / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Preview Core manifest is missing or invalid.") from exc
        if not isinstance(loaded, Mapping):
            raise ValueError("Preview Core manifest is not an object.")
        manifest = loaded
    source_schema = _preview_core_int(manifest.get("schema_version"), 0)
    material_graph_version = _preview_core_int(
        manifest.get("material_graph_version"), 0
    )
    material_semantics_version = _preview_core_int(
        manifest.get("material_semantics_version"), 0
    )
    center = _preview_core_vec3(manifest.get("normalization_center"))
    scale = _preview_core_float(manifest.get("normalization_scale"), 0.0)
    source_format = str(manifest.get("format", "") or "").strip().lower()
    raw_batches = manifest.get("batches")
    raw_material_conservation = manifest.get("material_conservation")
    if source_schema < _PREVIEW_CORE_SCHEMA_MINIMUM:
        raise ValueError("Direct preview requires Preview Core schema 8 or newer.")
    if (
        material_graph_version != _PREVIEW_CORE_MATERIAL_GRAPH_VERSION
        or material_semantics_version != _PREVIEW_CORE_MATERIAL_SEMANTICS_VERSION
    ):
        raise ValueError(
            "Direct preview requires Preview Core material graph v4 and semantics v10."
        )
    if (
        not isinstance(raw_material_conservation, Mapping)
        or raw_material_conservation.get("conserved") is not True
    ):
        raise ValueError(
            "Direct preview requires a conserved Preview Core material graph."
        )
    if center is None or abs(scale) <= 1.0e-12:
        raise ValueError("Preview Core normalization is invalid.")
    if source_format not in {"pac", "pam", "pamlod"}:
        raise ValueError("Preview Core source format is not supported by Preview.")
    if (
        not isinstance(raw_batches, Sequence)
        or isinstance(raw_batches, (str, bytes, bytearray))
        or not raw_batches
        or len(raw_batches) > _PREVIEW_CORE_BATCH_LIMIT
    ):
        raise ValueError("Preview Core batch list is invalid or exceeds the package limit.")
    return source_package, manifest, source_schema, material_graph_version, material_semantics_version, center, scale, source_format, raw_batches, raw_material_conservation


@atomic_preview_publication
def build_rust_preview_package_from_preview_core(
    preview_core_package_dir: Path | str,
    *,
    source_manifest: Mapping[str, object] | None = None,
    output_root: Path | str | None = None,
    output_package_dir: Path | str | None = None,
    preview_overlays: Mapping[str, object] | None = None,
    include_material_resources: bool = True,
    material_quality: str = "full",
    theme: Mapping[str, object] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> RustPreviewPackage:
    """Publish schema-8 Preview Core geometry without a Python/JSON round trip."""

    from cdmw.services.mesh_rust_authoring import _atomic_write_payload, _session_root_identity

    quality = normalize_rust_preview_material_quality(material_quality)
    (
        source_package, manifest, source_schema, material_graph_version, material_semantics_version, center,
        scale, source_format, raw_batches, raw_material_conservation,
    ) = _validated_preview_core_source(
        preview_core_package_dir, source_manifest,
    )

    _cancelled(cancelled)
    root = (
        Path(output_root)
        if output_root is not None
        else Path(tempfile.gettempdir()) / "cdmw_rust_preview"
    )
    package_dir = (
        Path(output_package_dir)
        if output_package_dir is not None
        else root / f"package_{int(time.time() * 1000)}_{uuid4().hex[:8]}"
    )
    package_dir.mkdir(parents=True, exist_ok=False)
    root_identity = _session_root_identity(package_dir)
    document = _atomic_write_payload(
        package_dir,
        "document.json",
        {
            "schema_version": 1,
            "geometry_authority": "manifest.preview_core_geometry",
        },
        data_type="mesh_document_pointer_json",
        element_count=1,
        expected_root_identity=root_identity,
    )

    (
        prepared_batches, direct_batches, part_identities,
    ) = _copy_preview_core_geometry(
        raw_batches, source_package, package_dir, root_identity, cancelled,
    )

    channels = _atomic_write_payload(
        package_dir,
        "channels.json",
        {
            "schema_version": 1,
            "geometry_authority": "manifest.preview_core_geometry",
            "vertex_format": "f32x23_le",
            "identity_format": "i32x2_le",
        },
        data_type="mesh_channels_pointer_json",
        element_count=len(direct_batches),
        expected_root_identity=root_identity,
    )
    metadata_mesh = _preview_core_metadata_mesh(
        source_package,
        manifest,
        prepared_batches,
        center=center,
        scale=scale,
        cancelled=cancelled,
    )
    # Production full-material work is completed by Rust from the conserved
    # Preview Core graph. Python packages only directly upload already authored
    # base/support maps; the Python combiner remains available as an oracle.
    (
        textures, preview_core_material_graph, presentations,
    ) = _prepare_preview_core_materials(
        package_dir, metadata_mesh, root_identity, quality, source_package, raw_batches, cancelled,
        include_material_resources,
    )
    frame, session_id, scene_payload = _preview_core_scene_frame(metadata_mesh, center, scale, part_identities, preview_overlays, cancelled)

    source_sha256 = str(manifest.get("source_sha256", "") or "").strip().upper()
    manifest_payload = {
        "schema": RUST_PREVIEW_PACKAGE,
        "protocol": RUST_PREVIEW_PROTOCOL,
        "session_id": session_id,
        "process_generation": 1,
        "base_revision": 0,
        "shadow_revision": 0,
        "renderer": RUST_MESH_RENDERER,
        "edit_backend": RUST_PREVIEW_BACKEND,
        "interaction_profile": "read_only",
        "document": document,
        "channels": channels,
        "preview_core_geometry": {
            "schema_version": source_schema,
            "material_graph_version": material_graph_version,
            "material_semantics_version": material_semantics_version,
            "format": source_format,
            "source_sha256": source_sha256,
            "normalization_center": list(center),
            "normalization_scale": scale,
            "batches": direct_batches,
        },
        "material_contract": {
            "graph_version": material_graph_version,
            "semantics_version": material_semantics_version,
            "conservation": copy.deepcopy(
                dict(raw_material_conservation)
            ),
        },
        "preview_core_material_graph": preview_core_material_graph,
        "textures": textures,
        "material_presentations": presentations,
        "texture_status": _texture_status(textures, quality),
        "source": {
            "path": str(manifest.get("source_path", "") or source_package),
            "format": source_format,
            "sha256": source_sha256,
            "lod_index": 0,
        },
        "output_policy": {"policy": "read_only_preview", "archive_writes": False},
        "theme": dict(theme or {}),
        "state": {"preview_scene": scene_payload},
    }
    manifest_path = package_dir / "manifest.json"
    atomic_write_text(
        manifest_path,
        json.dumps(manifest_payload, separators=(",", ":"), sort_keys=True),
    )
    return RustPreviewPackage(
        package_dir=package_dir,
        manifest_path=manifest_path,
        status_path=package_dir / "rust-preview-status.json",
        output_dir=package_dir,
        edit_operations_path=package_dir / "rust-preview-read-only.json",
        material_signature="",
        scene_frame=frame,
        scene_session_id=session_id,
        editable_submesh_count=len(direct_batches),
        reference_submesh_count=0,
    )


def _populate_preview_scene_overlays(
    scene_payload, session_id, scene, mesh, framing_bounds, initial_view, preview_overlays, effects_overlay,
    effect_texture_resources, package_dir, root_identity, cancelled,
):
    if framing_bounds is not None:
        low, high = framing_bounds
        minimum = [float(low[index]) for index in range(3)]
        maximum = [float(high[index]) for index in range(3)]
        bounds = {
            "min": minimum,
            "max": maximum,
            "center": [
                (minimum[index] + maximum[index]) * 0.5 for index in range(3)
            ],
        }
        extent = max(
            0.01,
            max(maximum[index] - minimum[index] for index in range(3)),
        )
        scene_payload["bounds"] = bounds
        scene_payload["framing"] = {"bounds": bounds, "extent": extent}
        grid = scene_payload.get("grid")
        if isinstance(grid, dict):
            grid["spacing"] = max(extent / 10.0, 0.01)
    if isinstance(initial_view, Mapping):
        framing = scene_payload.setdefault("framing", {})
        if isinstance(framing, dict):
            semantic = {
                key: list(value)
                for key in ("view_direction", "screen_up_direction", "fit_bounds")
                if isinstance((value := initial_view.get(key)), Sequence)
                and not isinstance(value, (str, bytes, bytearray))
            }
            if semantic:
                framing["initial_view"] = semantic
    scene_payload.update(
        {
            "renderer_authority": "rust_wgpu_resident_scene",
            "session_id": session_id,
            "part_identities": _part_identities(scene),
        }
    )
    overlays = preview_overlays or getattr(mesh, "cdmw_preview_overlays", None)
    if isinstance(overlays, Mapping):
        for source, target_key in (("skeleton", "skeleton_overlay"), ("cloth", "cloth_overlay"), ("effects", "effects_overlay")):
            value = overlays.get(source)
            if isinstance(value, Mapping):
                scene_payload[target_key] = dict(value)
    effect_texture_references: list[dict[str, object]] = []
    if isinstance(effects_overlay, Mapping):
        effect_payload = copy.deepcopy(dict(effects_overlay))
        if effect_texture_resources:
            texture_files, effect_texture_references = _write_effect_texture_resources(
                package_dir,
                effect_texture_resources,
                expected_root_identity=root_identity,
                cancelled=cancelled,
            )
            effect_payload["texture_files"] = texture_files
        else:
            effect_payload.setdefault("texture_files", {})
        scene_payload["effects_overlay"] = effect_payload
    return effect_texture_references


def _write_preview_mesh_resources(package_dir, scene, root_identity, include_material_resources, material_package_path, quality, cancelled):
    from cdmw.services.mesh_rust_authoring import (
        _RustMaterialSynthesisState,
        _atomic_write_payload,
        _mesh_channel_payload,
        _mesh_document_payload,
        _mesh_lods,
        _mesh_material_presentations,
        _mesh_texture_payloads,
    )

    document = _atomic_write_payload(
        package_dir,
        "document.json",
        _mesh_document_payload(scene, allow_preview_formats=True),
        data_type="mesh_document_json",
        element_count=sum(len(level) for level in _mesh_lods(scene)),
        expected_root_identity=root_identity,
    )
    channels = _atomic_write_payload(
        package_dir,
        "channels.json",
        _mesh_channel_payload(scene),
        data_type="mesh_channels_compact_json",
        element_count=sum(
            len(tuple(getattr(submesh, "vertices", ()) or ()))
            for level in _mesh_lods(scene)
            for submesh in level
        ),
        expected_root_identity=root_identity,
    )
    synthesis = _RustMaterialSynthesisState()
    stop_event = _CancellationView(cancelled)
    if include_material_resources:
        with tempfile.TemporaryDirectory(
            prefix="cdmw-rust-preview-images-",
            dir=package_dir.parent,
        ) as preview_image_staging:
            image_overrides = _encode_non_dds_preview_textures(
                scene,
                Path(preview_image_staging),
                stop_event,
                synthesis,
            )
            textures = _mesh_texture_payloads(
                package_dir,
                scene,
                expected_root_identity=root_identity,
                stop_event=stop_event,  # type: ignore[arg-type]
                synthesis_state=synthesis,
                material_package_path=material_package_path or "",
                preview_texture_overrides=image_overrides,
                enable_material_synthesis=quality == "full",
            )
    else:
        textures = []
    presentations = _mesh_material_presentations(
        scene,
        generated_overrides=synthesis.presentation_overrides,
    )
    _cancelled(cancelled)
    return document, channels, textures, presentations


@atomic_preview_publication
def build_rust_preview_package(
    mesh: ParsedMesh,
    *,
    output_root: Path | str | None = None,
    output_package_dir: Path | str | None = None,
    reference_mesh: ParsedMesh | None = None,
    comparison_mode: str = "replacement_only",
    reference_draw: str = "wire",
    grid_normal_axis: str = "y",
    interaction_profile: str = "read_only",
    interaction_mode: str | None = None,
    scene_transform: StaticReplacementTransform | None = None,
    scene_generation: int = 1,
    scene_session_id: str = "",
    selection_pivot_source: tuple[float, float, float] | None = None,
    preview_overlays: Mapping[str, object] | None = None,
    effects_overlay: Mapping[str, object] | None = None,
    effect_texture_resources: Mapping[str, bytes] | None = None,
    framing_bounds: tuple[Sequence[float], Sequence[float]] | None = None,
    initial_view: Mapping[str, object] | None = None,
    material_package_path: Path | str | None = None,
    include_material_resources: bool = True,
    material_quality: str = "full",
    theme: Mapping[str, object] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> RustPreviewPackage:
    """Publish one immutable Rust preview package.

    ``static_replacement`` is the only profile allowed to advertise preview
    mesh-edit input.  Both profiles remain read-only with respect to PAMT/PAZ.
    """

    from cdmw.services.mesh_rust_authoring import _session_root_identity, _source_hash

    quality = normalize_rust_preview_material_quality(material_quality)
    profile = str(interaction_profile or "read_only").strip().lower()
    if profile not in {"read_only", "static_replacement"}:
        raise ValueError(f"Unsupported preview interaction profile: {profile}")
    mode = str(
        interaction_mode
        or ("mesh_edit" if profile == "static_replacement" else "preview")
    ).strip().lower()
    if mode not in {"preview", "placement", "mesh_edit"}:
        raise ValueError(f"Unsupported preview interaction mode: {mode}")
    _cancelled(cancelled)
    root = (
        Path(output_root)
        if output_root is not None
        else Path(tempfile.gettempdir()) / "cdmw_rust_preview"
    )
    package_dir = (
        Path(output_package_dir)
        if output_package_dir is not None
        else root / f"package_{int(time.time() * 1000)}_{uuid4().hex[:8]}"
    )
    package_dir.mkdir(parents=True, exist_ok=False)
    root_identity = _session_root_identity(package_dir)

    scene = _scene_mesh(mesh, reference_mesh)
    editable_count = len(tuple(getattr(mesh, "submeshes", ()) or ()))
    reference_count = len(tuple(getattr(reference_mesh, "submeshes", ()) or ())) if reference_mesh else 0
    target = reference_mesh if reference_mesh is not None else mesh
    frame = build_authoritative_static_scene_frame(
        target,
        mesh,
        scene_transform
        or StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
        source_identity=static_scene_source_identity(mesh, reference_mesh),
        scene_generation=max(1, int(scene_generation)),
        comparison_mode=str(comparison_mode or "replacement_only"),
        interaction_mode=mode,
        reference_draw=str(reference_draw or "wire"),
        grid_normal_axis=str(grid_normal_axis or "y"),
        selection_pivot_source=selection_pivot_source,
        cancelled=cancelled,
    )
    if reference_mesh is None:
        empty = StaticWorldBounds((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        frame = replace(
            frame,
            reference=StaticSceneRoleFrame(
                role="reference",
                model_matrix=frame.reference.model_matrix,
                world_bounds=empty,
                visible=False,
                submesh_indices=(),
            ),
            framing_bounds=frame.editable.world_bounds,
            framing_extent=max(0.01, frame.editable.world_bounds.extent),
        )
    _cancelled(cancelled)
    (
        document, channels, textures, presentations,
    ) = _write_preview_mesh_resources(
        package_dir, scene, root_identity, include_material_resources, material_package_path, quality,
        cancelled,
    )
    session_id = str(scene_session_id or uuid4().hex)
    scene_payload = frame.to_protocol_payload()
    effect_texture_references = _populate_preview_scene_overlays(
        scene_payload, session_id, scene, mesh, framing_bounds, initial_view, preview_overlays,
        effects_overlay, effect_texture_resources, package_dir, root_identity, cancelled,
    )
    manifest = {
        "schema": RUST_PREVIEW_PACKAGE,
        "protocol": RUST_PREVIEW_PROTOCOL,
        "session_id": session_id,
        "process_generation": 1,
        "base_revision": 0,
        "shadow_revision": 0,
        "renderer": RUST_MESH_RENDERER,
        "edit_backend": RUST_PREVIEW_BACKEND,
        "interaction_profile": profile,
        "document": document,
        "channels": channels,
        "textures": textures,
        "effect_textures": effect_texture_references,
        "material_presentations": presentations,
        "texture_status": _texture_status(textures, quality),
        "source": {
            "path": str(getattr(mesh, "path", "") or ""),
            "format": str(getattr(mesh, "format", "") or ""),
            "sha256": _source_hash(mesh),
            "lod_index": 0,
        },
        "output_policy": {"policy": "read_only_preview", "archive_writes": False},
        "theme": dict(theme or {}),
        "state": {"preview_scene": scene_payload},
    }
    manifest_path = package_dir / "manifest.json"
    atomic_write_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True))
    return RustPreviewPackage(
        package_dir=package_dir,
        manifest_path=manifest_path,
        status_path=package_dir / "rust-preview-status.json",
        output_dir=package_dir,
        edit_operations_path=package_dir / "rust-preview-read-only.json",
        material_signature=_source_hash(scene) or _source_hash(mesh),
        scene_frame=frame,
        scene_session_id=session_id,
        editable_submesh_count=editable_count,
        reference_submesh_count=reference_count,
    )


def _read_preview_manifest(path: Path | str) -> tuple[Path, dict]:
    package_dir = Path(path)
    if package_dir.is_file():
        package_dir = package_dir.parent
    manifest_path = package_dir / "manifest.json"
    if manifest_path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("preview manifest exceeds its size limit")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("preview manifest is not an object")
    expected = {
        "schema": RUST_PREVIEW_PACKAGE,
        "protocol": RUST_PREVIEW_PROTOCOL,
        "renderer": RUST_MESH_RENDERER,
        "edit_backend": RUST_PREVIEW_BACKEND,
    }
    for key, value in expected.items():
        if str(payload.get(key, "") or "") != value:
            raise ValueError(f"preview manifest {key} does not match")
    return package_dir, payload


def rust_preview_package_from_path(path: Path | str) -> RustPreviewPackage:
    package_dir, payload = _read_preview_manifest(path)
    manifest_path = package_dir / "manifest.json"
    return RustPreviewPackage(
        package_dir=package_dir.resolve(),
        manifest_path=manifest_path.resolve(),
        status_path=package_dir / "rust-preview-status.json",
        output_dir=package_dir,
        edit_operations_path=package_dir / "rust-preview-read-only.json",
        scene_session_id=str(payload.get("session_id", "") or ""),
    )


def validate_rust_preview_package(path: Path | str) -> tuple[str, ...]:
    try:
        package_dir, payload = _read_preview_manifest(path)
        validate_preview_files(package_dir, payload)
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        return (str(exc),)
    return ()


def build_rust_preview_prewarm_package(cache_root: Path | str) -> RustPreviewPackage:
    root = Path(cache_root) / "rust_preview" / "prewarm"
    root.mkdir(parents=True, exist_ok=True)
    for candidate in sorted(root.glob("package_*"), reverse=True):
        try:
            if not validate_rust_preview_package(candidate):
                return rust_preview_package_from_path(candidate)
        except OSError:
            continue
    submesh = SubMesh(
        name="rust_preview_prewarm",
        material="prewarm",
        vertices=[(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.0, 0.5, 0.0)],
        uvs=[(0.0, 1.0), (1.0, 1.0), (0.5, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 1, 2)],
        vertex_count=3,
        face_count=1,
    )
    mesh = ParsedMesh(
        path="procedural://rust-preview-prewarm",
        format="procedural",
        bbox_min=(-0.5, -0.5, 0.0),
        bbox_max=(0.5, 0.5, 0.0),
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )
    return build_rust_preview_package(mesh, output_root=root)


__all__ = [
    "RustPreviewPackage",
    "build_rust_preview_package",
    "build_rust_preview_package_from_preview_core",
    "build_rust_preview_prewarm_package",
    "normalize_rust_preview_material_quality",
    "rust_preview_package_from_path",
    "validate_rust_preview_package",
]
