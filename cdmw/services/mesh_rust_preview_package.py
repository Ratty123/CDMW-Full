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
import logging
import math
import mmap
import os
import struct
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from cdmw.services.mesh_rust_authoring import _RustMaterialSynthesisState

from cdmw.core.atomic_file import atomic_write_bytes, atomic_write_text
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.material_layer_uv import (
    pac_blend_layer_surface,
    pac_blend_height_uv_transform,
    pac_blend_layer_uv_transform,
    pac_color_bytes,
    pac_grime_blend_bytes,
    pac_grime_uv_transform,
    pac_layer_uv_transform,
    pac_scratch_bytes,
)
from cdmw.services import mesh_rust_preview_files as _preview_files
from cdmw.services.mesh_rust_preview_files import atomic_preview_publication, validate_preview_files
from cdmw.services.json_file_facts import json_file_fact
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

_LOGGER = logging.getLogger(__name__)
_PREVIEW_CORE_VERTEX = struct.Struct("<23f")
_PREVIEW_CORE_IDENTITY = struct.Struct("<2i")
_PREVIEW_CORE_SCHEMA_MINIMUM = 8
_PREVIEW_CORE_MATERIAL_GRAPH_VERSION = 5
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
_PREVIEW_MANIFEST_MAX_BYTES = 16 * 1024 * 1024


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
            atomic_write_bytes(package_dir / Path(relative), data, durable=_preview_files.PREVIEW_CACHE_FSYNC)
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

    The thinnest/template-normal axis faces the camera. Horizontal grids are viewed
    from above with the longest remaining axis across the screen; X/Z normals keep
    their conventional upright side/front view at every DPI and aspect ratio.
    ``grounded`` selects the broadside automatically, keeps world Y upright for
    standing models, and looks slightly down so a horizontal floor stays visible.
    """

    low, high = bounds
    minimum = [float(low[index]) for index in range(3)]
    maximum = [float(high[index]) for index in range(3)]
    extents = [abs(maximum[index] - minimum[index]) for index in range(3)]
    mode = str(normal_axis or "y").casefold()
    grounded = mode == "grounded"
    axis = (min((2, 0, 1), key=extents.__getitem__) if grounded
            else {"x": 0, "y": 1, "z": 2}.get(mode, 1))
    plane_axes = [index for index in range(3) if index != axis]
    upright = (
        min(plane_axes, key=extents.__getitem__)
        if axis == 1
        else 1 if grounded else max(plane_axes, key=extents.__getitem__)
    )
    view_direction = [0.0, 0.0, 0.0]
    screen_up_direction = [0.0, 0.0, 0.0]
    # This vector points from the eye to the model. Looking down from +Y
    # therefore needs -Y, otherwise the placement grid opens from underneath.
    view_direction[axis] = -1.0 if axis == 1 else 1.0
    if grounded and axis != 1:
        view_direction[1] = -0.35
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
        _RUST_SYNTHESIZED_SCALAR_ROLES,
        _encode_rust_preview_dds_batch,
        _material_input_dds_path,
        _material_input_is_renderer_role_eligible,
        _material_input_texture_role,
        _mesh_lods,
    )

    overrides: dict[tuple[int, int, str], Path] = {}
    encoded_sources: dict[tuple[Path, str], Path] = {}
    bindings: list[tuple[object, str, int, int, str, Path]] = []
    for lod_index, submeshes in enumerate(_mesh_lods(mesh)):
        for submesh_index, submesh in enumerate(submeshes):
            direct_roles: set[str] = set()
            for role, dds_attribute, image_attributes in _PREVIEW_IMAGE_TEXTURES:
                declared_dds = str(getattr(submesh, dds_attribute, "") or "").strip()
                if declared_dds:
                    try:
                        dds_path = Path(declared_dds).expanduser().resolve(strict=True)
                    except (OSError, RuntimeError):
                        dds_path = None
                    if dds_path is not None and dds_path.is_file():
                        direct_roles.add(role)
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
                direct_roles.add(role)

            # Separate PBR maps live in material inputs, not the legacy top-level
            # texture attributes. Publish them through the same DDS handoff as
            # packed metallic/roughness images instead of silently losing them.
            material_inputs = tuple(
                getattr(submesh, "preview_material_texture_inputs", ()) or ()
            )
            for role in sorted(_RUST_SYNTHESIZED_SCALAR_ROLES):
                if role in {"roughness", "metalness"} and "material" in direct_roles:
                    continue  # The packed map already owns its G/B channels.
                candidates = tuple(
                    item for item in material_inputs
                    if _material_input_texture_role(item) == role
                    and _material_input_is_renderer_role_eligible(submesh, item, role)
                    and len(tuple(getattr(item, "packed_channels", ()) or ())) <= 1
                )
                if any(_material_input_dds_path(item) is not None for item in candidates):
                    continue  # Existing source DDS remains authoritative.
                image_paths = {
                    path for item in candidates
                    if (path := _existing_preview_image(
                        item, ("preview_texture_path", "source_texture_path")
                    )) is not None
                }
                if len(image_paths) != 1:
                    continue
                image_path = next(iter(image_paths))
                source_key = (image_path, role)
                target = encoded_sources.get(source_key)
                if target is None:
                    target = staging_root / f"texture-{len(encoded_sources):04d}-{role}.dds"
                    encoded_sources[source_key] = target
                bindings.append((submesh, "", lod_index, submesh_index, role, target))

    _encode_rust_preview_dds_batch(
        tuple(
            (image_path, target, role)
            for (image_path, role), target in encoded_sources.items()
        ),
        stop_event,  # type: ignore[arg-type]
        synthesis,
    )
    for submesh, dds_attribute, lod_index, submesh_index, role, target in bindings:
        if dds_attribute:
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
        if scene.lod_levels:
            # The preview renders LOD0, whose cloned list is separate from
            # submeshes. Serialize the same parts that its scene roles name.
            scene.lod_levels[0] = scene.submeshes
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
            if _preview_files.PREVIEW_CACHE_FSYNC:
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
    durable: bool = True,
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
        linked = False
        if not durable:
            # A Mesh Editor session on the cache's volume shares the immutable
            # cache file instead of rewriting it; it is still hashed below.
            try:
                os.link(source, temporary)
                linked = True
            except OSError:
                linked = False
        if linked:
            source_before = os.stat(source)
            with temporary.open("rb") as reader:
                while True:
                    _cancelled(cancelled)
                    block = reader.read(_PREVIEW_CORE_COPY_CHUNK_BYTES)
                    if not block:
                        break
                    digest.update(block)
                    byte_length += len(block)
                    if aggregate_bytes + byte_length > _PREVIEW_CORE_MATERIAL_RESOURCE_BYTES:
                        raise ValueError(
                            "Preview Core material DDS resources exceed the 512 MiB package limit."
                        )
            source_after = os.stat(source)
        else:
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
                if durable and _preview_files.PREVIEW_CACHE_FSYNC:
                    # Cache packages are verified on read and rebuilt when
                    # damaged, so they are not flushed file by file either.
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


def _preview_core_layer_parameter_index(parameters):
    """Keep layer sampling and blend controls tied to their exact wrapper."""
    result = {}
    for parameter in parameters:
        if not isinstance(parameter, Mapping):
            continue
        name = str(parameter.get("parameter_name", ""))
        if name.casefold().lstrip("_") not in {
            "dyeingtransformproperty0", "dyeingtransformproperty1",
            "dyeingtransformproperty3", "dyeingpropertyblend",
            "colorblendingflag", "dyeingglobalopacity",
            "dyeingdetaillayercolormaskr", "dyeingdetaillayercolormaskg",
            "dyeingdetaillayercolormaskb",
            "grimeblendingparameterr", "grimeblendingparameterg", "grimeblendingparameterb",
            "grimeblendingopacityparameter", "grimeblendingopacityparameter1",
            "tintcolorr", "tintcolorg", "tintcolorb", "detailmasktexture",
            "scratchroughness", "scratchmetallic",
            "scratchtintcolorr", "scratchtintcolorg", "scratchtintcolorb",
            "masktexture", "dyeingcolormaskr", "dyeingcolormaskg", "dyeingcolormaskb",
            "detaildiffusemaskr", "detaildiffusemaskg", "detaildiffusemaskb",
            "overlaycolortexture", "dyeingcustompropertymaskr", "dyeingcustompropertymaskg",
            "dyeingcustompropertymaskb",
            "detaildiffuseblend", "dyeingdetaillayercolorblend", "dyeingtransformproperty4",
            "dyeingblendtexturetranslation", "colorblendingoptionbitflag",
            "eyeproperty0", "eyeproperty1", "eyeproperty2", "irisbrightness",
            "irisnormaltexture", "irismaterialtexture",
            "detailnormalblend", "detailmaterialblend",
            "detailscreenspacedisplacementscale", "screenspacedisplacementscale",
        }:
            continue
        key = (
            str(parameter.get("component_scope_id", "") or ""),
            str(parameter.get("owner_wrapper_item_id", "") or ""),
            _preview_core_int(parameter.get("material_wrapper_index"), -1),
        )
        value = parameter.get("integer_value")
        if value is None:
            value = parameter.get("value", "")
        if name.casefold().lstrip("_") in {
            "detailmasktexture", "masktexture", "overlaycolortexture", "detaildiffuseblend",
            "irisnormaltexture", "irismaterialtexture",
            "detailnormalblend", "detailmaterialblend",
        }:
            # A texture parameter: the layer rule needs the file, not a number.
            value = {
                "source": str(parameter.get("resolved_source_path", "") or "").strip(),
                "archive_path": str(parameter.get("resolved_archive_path", "") or "").strip(),
            }
        result.setdefault(key, []).append((name, value))
    return result


def _preview_core_detail_mask(values, source_package, name="detailmasktexture"):
    """The wrapper's `_detailMaskTexture` as (source, archive path), when its file is there.

    The map is optional: without it the layer keeps its plain form, so a pruned
    or unresolved mask costs the wear, not the preview. `name` reads another
    texture parameter of the wrapper the same way.
    """
    mask = values.get(name)
    if not isinstance(mask, Mapping) or not mask.get("source") or not mask.get("archive_path"):
        return None
    if _preview_core_material_source(source_package, mask["source"]) is None:
        return None
    return str(mask["source"]), str(mask["archive_path"]).replace("\\", "/")


def _preview_core_ver2_grime(layer, role, channel, mask_parameter, parameters, source_package):
    """State the game's grime rule on a Ver2 grime layer; return its detail mask.

    The game draws grime where `_detailMaskTexture` green passes a ramp, sampled
    with the grime layer's own tiling and tinted by `_tintColor{R,G,B}`. A layer
    gets these fields only when every input is authored and resolved; without
    them the renderer keeps the layer hidden, as before.
    """
    if role != "grime" or mask_parameter != "_colorBlendingMaskTexture" or not parameters:
        return None
    values = {str(name).casefold().lstrip("_"): value for name, value in parameters}
    blend = pac_grime_blend_bytes(parameters, channel)
    transform = pac_grime_uv_transform(values.get(f"grimeblendingparameter{channel}"))
    mask = _preview_core_detail_mask(values, source_package)
    if blend is None or transform is None or mask is None:
        return None
    layer["uv_transform"] = list(transform)
    layer["grime_blend"] = list(blend)
    tint = pac_color_bytes(values.get(f"tintcolor{channel}"))
    # No authored `_tintColor` leaves the grime texture's own colour.
    layer["tint"] = list(tint) if tint is not None else [1.0, 1.0, 1.0, 0.0]
    return mask


def _preview_core_ver2_scratch(layer, role, channel, mask_parameter, parameters, source_package):
    """State the game's scratch rule on a Ver2 colour layer; return its detail mask.

    Where `_detailMaskTexture` red marks a scratch, the game moves the layer's
    roughness and metal by signed bytes and overlays `_scratchTintColor{R,G,B}`.
    """
    if role != "detail" or mask_parameter != "_colorBlendingMaskTexture" or not parameters:
        return None
    values = {str(name).casefold().lstrip("_"): value for name, value in parameters}
    scratch = pac_scratch_bytes(parameters, channel)
    tint = pac_color_bytes(values.get(f"scratchtintcolor{channel}"))
    mask = _preview_core_detail_mask(values, source_package)
    if (scratch is None and tint is None) or mask is None:
        return None
    if scratch is not None:
        layer["scratch"] = list(scratch)
    if tint is not None:
        layer["scratch_tint"] = list(tint)
    return mask


# The game's shader families that dye the base colour through `_maskTexture` with
# `_dyeingColorMaskR/G/B` (the non-Ver2 Standard group). No Ver2 shader reads those
# colours, and the BlendHeight families have no dye.
_LEGACY_DYE_FAMILIES = frozenset({
    "skinnedmeshstandard", "skinnedmeshcloth", "skinnedmeshfur", "skinnedmeshemissive",
    "skinnedmeshamplifiedglare", "skinnedmeshwing", "skinnedmeshposter",
})


def _preview_core_legacy_dye_layers(raw_layers, parameter_index, source_package):
    """The legacy dye of a batch as `color_seed` rows on `_maskTexture`.

    The game colours a legacy part's base through `_maskTexture`: red, green and
    blue select `_dyeingColorMaskR/G/B`, alpha shades the result (an overlay
    blend whose base is the alpha: 0 black, 0.5 the dye, 1 white). Preview Core
    states the first colour as a whole-part tint only, so the rows are made here
    from the wrapper's own parameters: one per authored colour with alpha above
    zero, each naming the mask. Without the mask's file there is no dye.
    """
    base = raw_layers[0]
    if (
        not isinstance(base, Mapping)
        or str(base.get("layer_role", "") or "").strip().casefold() != "base"
        or str(base.get("shader_family", "") or "").strip().casefold() not in _LEGACY_DYE_FAMILIES
        or any(
            isinstance(layer, Mapping)
            and str(layer.get("layer_role", "") or "").strip().casefold() == "color_seed"
            for layer in raw_layers
        )
    ):
        return []
    owner = str(base.get("owner_wrapper_item_id", "") or "").strip()
    wrapper_index = _preview_core_int(base.get("material_wrapper_index"), -1)
    parameters = parameter_index.get(
        (str(base.get("component_scope_id", "") or ""), owner, wrapper_index), (),
    )
    if not owner or wrapper_index < 0 or not parameters:
        return []
    values = {str(name).casefold().lstrip("_"): value for name, value in parameters}
    mask = _preview_core_detail_mask(values, source_package, "masktexture")
    if mask is None:
        return []
    layers = []
    for channel in "rgb":
        colour = pac_color_bytes(values.get(f"dyeingcolormask{channel}"))
        if colour is None or colour[3] <= 0.0:
            continue
        layers.append({
            "component_scope_id": str(base.get("component_scope_id", "") or ""),
            "owner_wrapper_item_id": owner,
            "material_wrapper_index": wrapper_index,
            "layer_role": "color_seed",
            "mask_channel": channel,
            "shader_family": base.get("shader_family", ""),
            "shader_rule": base.get("shader_rule", ""),
            "evidence_grade": base.get("evidence_grade", ""),
            "source_parameter": f"_dyeingColorMask{channel.upper()}",
            "mask_parameter": "_maskTexture",
            "weight": 1.0,
            "tint": list(colour),
            "mask_source": mask[0],
            "mask_archive_path": mask[1],
        })
    return layers


# The game's BlendHeight families: layers chosen by height, no dye.
_BLEND_HEIGHT_FAMILIES = frozenset({"skinnedmeshblendheight", "skinnedmeshstaticblendheight"})


def _preview_core_blend_height_layer(layer, channel, parameters, values):
    """State the BlendHeight rule's inputs on one of its colour layers.

    The game samples a layer's four maps at the mesh UV divided by bytes 0 and 1
    of its transform property (no rotation, no offset), and blends by height:
    a layer's height is `_maskTexture` channel times `_detailHeightMask*` red
    times its `_dyeingGlobalOpacity` byte; the base's is `_heightTexture` red
    times `_screenSpaceDisplacementScale`; `_detailScreenSpaceDisplacementScale`
    (at least 0.01) is the blend width. `blend_height` carries the width and the
    base height scale; the opacity byte is `blend_opacity`.
    """
    layer["uv_transform"] = list(pac_blend_height_uv_transform(parameters, channel))

    def number(name):
        try:
            value = float(values.get(name, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return value if math.isfinite(value) else 0.0

    layer["blend_height"] = [
        max(0.01, number("_detailscreenspacedisplacementscale")),
        max(0.0, number("_screenspacedisplacementscale")),
    ]


# The game's Ver2 shader families. Each runs the overlay step after grime and
# scratch: albedo = overlay(base = `_overlayColorTexture`, blend = albedo).
_VER2_LAYER_FAMILIES = frozenset({
    "skinnedmeshstandard_ver2", "skinnedmeshcloth_ver2", "skinnedmeshfur_ver2",
    "skinnedmeshemissive_ver2", "skinnedmeshamplifiedglare_ver2", "skinnedmeshstaticstandard",
    "skinnedmeshsail_ver2", "skinnedmeshtorncloth_ver2",
})


def _preview_core_ver2_wrapper(raw_layers, parameter_index):
    """The Ver2 wrapper a batch's colour layers belong to: (a layer row of it, its parameters)."""
    for layer in raw_layers:
        if (
            isinstance(layer, Mapping)
            and str(layer.get("layer_role", "") or "").strip().casefold() == "detail"
            and str(layer.get("mask_parameter", "") or "").strip() == "_colorBlendingMaskTexture"
            and str(layer.get("shader_family", "") or "").strip().casefold() in _VER2_LAYER_FAMILIES
        ):
            owner = str(layer.get("owner_wrapper_item_id", "") or "").strip()
            wrapper_index = _preview_core_int(layer.get("material_wrapper_index"), -1)
            if not owner or wrapper_index < 0:
                return None
            parameters = parameter_index.get(
                (str(layer.get("component_scope_id", "") or ""), owner, wrapper_index), (),
            )
            return layer, {str(name).casefold().lstrip("_"): value for name, value in parameters}
    return None


def _preview_core_ver2_overlay_layer(raw_layers, parameter_index, source_package):
    """The Ver2 overlay step of a batch as one `overlay` row.

    The game applies `_overlayColorTexture` to every pixel of a Ver2 material,
    after grime and scratch, as an overlay blend whose base is the map (0.5 is
    neutral). A layer whose `_dyeingCustomPropertyMask*` has bit 0x10000
    overlays the map's luma: one bit per layer in `blend_flags` (1 R, 2 G, 4 B).

    A wrapper without the parameter reads the engine's default there,
    `texture/nonetexture0xff888888.dds`, whose pixels are 0x80 whatever its name
    says: neutral, so such a wrapper gets no row. A declared map whose file is
    not there gets none either: its content is not known.
    """
    if any(
        isinstance(layer, Mapping)
        and str(layer.get("source_parameter", "") or "").strip() == "_overlayColorTexture"
        for layer in raw_layers
    ):
        return []
    wrapper = _preview_core_ver2_wrapper(raw_layers, parameter_index)
    if wrapper is None:
        return []
    owner_layer, values = wrapper
    row = {
        "component_scope_id": str(owner_layer.get("component_scope_id", "") or ""),
        "owner_wrapper_item_id": owner_layer.get("owner_wrapper_item_id", ""),
        "material_wrapper_index": owner_layer.get("material_wrapper_index"),
        "layer_role": "overlay",
        "mask_channel": "",
        "shader_family": owner_layer.get("shader_family", ""),
        "shader_rule": owner_layer.get("shader_rule", ""),
        "evidence_grade": owner_layer.get("evidence_grade", ""),
        "source_parameter": "_overlayColorTexture",
        "mask_parameter": "",
        "weight": 1.0,
        "tint": [1.0, 1.0, 1.0, 0.0],
    }
    overlay = _preview_core_detail_mask(values, source_package, "overlaycolortexture")
    if overlay is None:
        return []
    row["diffuse_source"], row["diffuse_archive_path"] = overlay
    row["blend_flags"] = sum(
        1 << bit
        for bit, channel in enumerate("rgb")
        if _preview_core_int(values.get(f"dyeingcustompropertymask{channel}"), 0) & 0x10000
    )
    return [row]


def _preview_core_ver2_blend_layer(raw_layers, parameter_index, source_package):
    """The Ver2 blend layer of a batch (the game's "symbol") as one `overlay` row.

    The game draws `_detailDiffuseBlend` after the overlay step, only when byte 3
    of `_dyeingGlobalOpacity` is not zero: dyed by `_dyeingDetailLayerColorBlend`
    as a colour layer is, laid over by its own alpha times that byte, at one place
    of the mesh UV (`pac_blend_layer_uv_transform`). Its normal and material maps
    (`_detailNormalBlend`, `_detailMaterialBlend`) ride on the row when their files
    are there, with the switches and steps of `pac_blend_layer_surface` in
    `blend_flags` and `blend_surface`.
    """
    if any(
        isinstance(layer, Mapping)
        and str(layer.get("source_parameter", "") or "").strip() == "_detailDiffuseBlend"
        for layer in raw_layers
    ):
        return []
    wrapper = _preview_core_ver2_wrapper(raw_layers, parameter_index)
    if wrapper is None:
        return []
    owner_layer, values = wrapper
    opacity = (_preview_core_int(values.get("dyeingglobalopacity"), 0) >> 24) & 255
    colour_map = _preview_core_detail_mask(values, source_package, "detaildiffuseblend")
    if not opacity or colour_map is None:
        return []
    tint = pac_color_bytes(values.get("dyeingdetaillayercolorblend"))
    flags, surface = pac_blend_layer_surface(values.items())
    row = {
        "component_scope_id": str(owner_layer.get("component_scope_id", "") or ""),
        "owner_wrapper_item_id": owner_layer.get("owner_wrapper_item_id", ""),
        "material_wrapper_index": owner_layer.get("material_wrapper_index"),
        "layer_role": "overlay",
        "mask_channel": "",
        "shader_family": owner_layer.get("shader_family", ""),
        "shader_rule": owner_layer.get("shader_rule", ""),
        "evidence_grade": owner_layer.get("evidence_grade", ""),
        "source_parameter": "_detailDiffuseBlend",
        "mask_parameter": "",
        "weight": 1.0,
        # No authored dye leaves the layer's own colour.
        "tint": list(tint) if tint is not None else [1.0, 1.0, 1.0, 0.0],
        "diffuse_source": colour_map[0],
        "diffuse_archive_path": colour_map[1],
        "uv_transform": list(pac_blend_layer_uv_transform(values.items())),
        "blend_opacity": opacity / 255.0,
        "blend_flags": flags,
        "blend_surface": list(surface),
    }
    for role, name in (("normal", "detailnormalblend"), ("material", "detailmaterialblend")):
        found = _preview_core_detail_mask(values, source_package, name)
        if found is not None:
            row[f"{role}_source"], row[f"{role}_archive_path"] = found
    return [row]


# `_eyeProperty0/1/2` at the game's defaults (skinnedmeshparameters.xml, Byte4: byte i is
# DefaultValue{i} * 255, rounded). P0: PupilSize 0, PupilStretchMinSize 0.1, PupilStretchMaxSize
# 0.25, IrisSize 0.5. P1: UVScaleX 1, UVScaleY 1, UseMaterialTextureRoughness 0, EyeImageScale 1.
# P2: IrisEmissiveIntensity 0, DynamicEyeColor 1.
_EYE_PROPERTY_DEFAULTS = (0x80401A00, 0xFF00FFFF, 0x0000FF00)


def _preview_core_eye_layers(raw_layers, parameter_index, source_package):
    """The eye's own surface inputs, stated on its rows.

    SkinnedMeshEye mixes sclera, iris and pupil by the iris and pupil alphas, at
    UVs set by `_eyeProperty0/1` (EyeImageScale, IrisSize, the pupil's size and
    stretch), and lerps the normal (`_irisNormalTexture`) and, with
    UseMaterialTextureRoughness, the roughness (`_irisMaterialTexture` green)
    toward the iris by the same alpha. The base row gets the three property words
    and `_irisBrightness`; the iris row gets the iris normal and material maps
    when their files are there.
    """
    base = raw_layers[0] if raw_layers else None
    if (
        not isinstance(base, Mapping)
        or str(base.get("layer_role", "") or "").strip().casefold() != "base"
        or str(base.get("shader_family", "") or "").strip().casefold() != "skinnedmesheye"
    ):
        return raw_layers
    parameters = parameter_index.get(
        (
            str(base.get("component_scope_id", "") or ""),
            str(base.get("owner_wrapper_item_id", "") or "").strip(),
            _preview_core_int(base.get("material_wrapper_index"), -1),
        ),
        (),
    )
    values = {str(name).casefold().lstrip("_"): value for name, value in parameters}
    words = []
    for index, default in enumerate(_EYE_PROPERTY_DEFAULTS):
        # An empty value is the parameter left at its default.
        word = _preview_core_int(values.get(f"eyeproperty{index}"), -1)
        words.append(word & 0xFFFFFFFF if word >= 0 else default)
    brightness = _preview_core_float(values.get("irisbrightness"), 0.5)
    result = [dict(base, eye_properties=words, iris_brightness=max(0.0, min(1.0, brightness)))]
    for layer in raw_layers[1:]:
        if (
            isinstance(layer, Mapping)
            and str(layer.get("source_parameter", "") or "").strip() == "_irisDiffuseTexture"
            and str(layer.get("layer_role", "") or "").strip().casefold() == "overlay"
        ):
            layer = dict(layer)
            for role, name in (("normal", "irisnormaltexture"), ("material", "irismaterialtexture")):
                found = _preview_core_detail_mask(values, source_package, name)
                if found is not None and not str(layer.get(f"{role}_source", "") or "").strip():
                    layer[f"{role}_source"], layer[f"{role}_archive_path"] = found
        result.append(layer)
    return result
def _preview_core_batch_material_inputs(raw_batch: Mapping[str, object]) -> tuple[object, ...]:
    """The batch's material inputs: Preview Core packages keep them under
    ``dds_textures``; a batch can also carry them at its top level."""
    found: list[object] = []
    dds_textures = raw_batch.get("dds_textures")
    for raw_inputs in (raw_batch.get("material_inputs"),
                       dds_textures.get("material_inputs") if isinstance(dds_textures, Mapping) else None):
        if isinstance(raw_inputs, Sequence) and not isinstance(raw_inputs, (str, bytes, bytearray)):
            found.extend(raw_inputs)
    return tuple(found)


def _is_net_veil_wrapper(parameters: Sequence[object]) -> bool:
    return any(isinstance(parameter, Mapping)
               and str(parameter.get("parameter_name", "") or "").strip().casefold() == "_netpitch"
               for parameter in parameters)


def _copy_preview_core_material_layers(
    raw_batches, source_package, package_dir, quality, resources, next_index, aggregate_bytes, copied_sources,
    materials, source_edge_count, cancelled, expected_root_identity, parameter_index, durable=True,
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
        raw_layers = list(raw_layers)
        raw_layers.extend(
            (
                _preview_core_legacy_dye_layers(raw_layers, parameter_index, source_package)
                + _preview_core_ver2_overlay_layer(raw_layers, parameter_index, source_package)
                + _preview_core_ver2_blend_layer(raw_layers, parameter_index, source_package)
            )[: _PREVIEW_CORE_MATERIAL_LAYER_LIMIT - len(raw_layers)]
        )
        raw_layers = _preview_core_eye_layers(raw_layers, parameter_index, source_package)
        layers: list[dict[str, object]] = []
        # Each wrapper's authored parameters, as the batch's material inputs carry them.
        wrapper_parameters: dict[str, Sequence[object]] = {}
        for raw_input in _preview_core_batch_material_inputs(raw_batch):
            if isinstance(raw_input, Mapping):
                input_owner = str(raw_input.get("owner_wrapper_item_id", "") or "").strip()
                input_parameters = raw_input.get("material_parameters")
                if (input_owner and input_owner not in wrapper_parameters and isinstance(input_parameters, Sequence)
                        and not isinstance(input_parameters, (str, bytes))):
                    wrapper_parameters[input_owner] = input_parameters
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
            if role in {"detail", "grime"} and channel in {"r", "g", "b"}:
                parameter_key = (
                    str(raw_layer.get("component_scope_id", "") or ""), owner, wrapper_index,
                )
                parameters = parameter_index.get(parameter_key, ())
                layer["uv_transform"] = list(pac_layer_uv_transform(parameters, channel))
                if role == "detail" and parameters:
                    values = {str(name).casefold(): value for name, value in parameters}
                    shift = {"r": 0, "g": 1, "b": 2}[channel]
                    flags = _preview_core_int(values.get("_colorblendingflag"), 0xFFFFFFFF)
                    opacity = _preview_core_int(values.get("_dyeingglobalopacity"), 0xFFFFFFFF)
                    layer["blend_flags"] = (flags >> (shift * 4)) & 15
                    layer["blend_opacity"] = ((opacity >> (shift * 8)) & 255) / 255.0
                    if f"_dyeingdetaillayercolormask{channel}" not in values:
                        # A native default white is not an authored white dye.
                        layer["tint"][3] = 0.0
                    if (
                        layer["shader_family"].casefold() in _LEGACY_DYE_FAMILIES
                        and f"_detaildiffusemask{channel}" not in values
                    ):
                        # Preview Core pairs a layer's normal map with the file of the
                        # same name without the suffix. When the wrapper declares no
                        # `_detailDiffuseMask*` that file is not a colour map (it is
                        # often `_detailHeightMask*`), and the game draws no colour.
                        layer["colour_authored"] = False
                    if layer["shader_family"].casefold() in _BLEND_HEIGHT_FAMILIES:
                        _preview_core_blend_height_layer(layer, channel, parameters, values)
                detail_mask = _preview_core_ver2_grime(
                    layer, role, channel, mask_parameter, parameters, source_package,
                ) or _preview_core_ver2_scratch(
                    layer, role, channel, mask_parameter, parameters, source_package,
                )
            else:
                detail_mask = None
            if role == "base" and "eye_properties" in raw_layer:
                layer["eye_properties"] = [int(word) & 0xFFFFFFFF for word in raw_layer["eye_properties"]][:3]
                layer["iris_brightness"] = _preview_core_layer_float(raw_layer.get("iris_brightness"), fallback=0.5)
            if role == "overlay" and source_parameter == "_overlayColorTexture" and "blend_flags" in raw_layer:
                layer["blend_flags"] = _preview_core_int(raw_layer.get("blend_flags"), 0) & 7
            if role == "overlay" and source_parameter == "_detailDiffuseBlend" and "uv_transform" in raw_layer:
                layer["uv_transform"] = [
                    _preview_core_float(value, 0.0) for value in tuple(raw_layer["uv_transform"])[:6]
                ]
                layer["blend_opacity"] = _preview_core_layer_float(raw_layer.get("blend_opacity"))
                if "blend_flags" in raw_layer:
                    layer["blend_flags"] = _preview_core_int(raw_layer.get("blend_flags"), 0) & 15
                if "blend_surface" in raw_layer:
                    layer["blend_surface"] = [
                        _preview_core_float(value, 0.0) for value in tuple(raw_layer["blend_surface"])[:3]
                    ]
            layer_has_source = False
            # A net veil's detail height is not blended over its base height: the
            # game adds it to the thread width, and the renderer samples it itself.
            veil_detail = role != "base" and _is_net_veil_wrapper(wrapper_parameters.get(owner, ()))
            for resource_role in ("diffuse", "normal", "material", "height", "mask", "detail_mask"):
                _cancelled(cancelled)
                source_key = f"{resource_role}_source"
                archive_key = f"{resource_role}_archive_path"
                source_text = str(raw_layer.get(source_key, "") or "").strip()
                if veil_detail and resource_role == "height":
                    source_text = ""
                archive_path = str(raw_layer.get(archive_key, "") or "").strip().replace("\\", "/")
                if resource_role == "detail_mask":
                    if detail_mask is None:
                        # Only layers drawn by the game's Ver2 rule carry this map,
                        # so every other layer keeps its five-resource shape.
                        continue
                    source_text, archive_path = detail_mask
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
                                    durable=durable,
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


# SkinnedMeshGhost defaults (material/dist skinnedmeshghost.material).
_GHOST_DEFAULTS = {
    "ghostopacity": 1.0, "ghostfresnelalpha": -0.1, "ghostmaskradius": 1.0, "ghostmaskhardness": 4.0,
    "ghostmetallic": 0.0, "ghostroughness": 1.0,
}
_GHOST_DEFAULT_MASK_POSITION = (0.0, -3.0, 0.0)
_GHOST_DEFAULT_COLOUR = (0x88 / 255.0, 0xA4 / 255.0, 0xA7 / 255.0)


def _preview_core_ghost_floats(value, count):
    try:
        numbers = [float(part) for part in str(value or "").replace(",", " ").split()]
    except ValueError:
        return None
    # A value the reader could not make sense of (the archive holds a few
    # denormal or huge floats here) is not an authored number.
    if len(numbers) != count or any(not math.isfinite(number) or abs(number) > 1.0e6 for number in numbers):
        return None
    return numbers


def _preview_core_batch_centre(source_package, raw_batch, center, scale):
    """Mean model-space position of a batch (23 floats a vertex, position first)."""
    path = _preview_core_child(Path(source_package), raw_batch.get("vertex_file"))
    count = _preview_core_int(raw_batch.get("vertex_count"), 0)
    if path is None or count <= 0 or not scale:
        return None
    step = max(1, count // 4096)
    total = [0.0, 0.0, 0.0]
    used = 0
    try:
        with path.open("rb") as handle:
            for index in range(0, count, step):
                handle.seek(index * 92)
                record = handle.read(12)
                if len(record) != 12:
                    break
                for axis, value in enumerate(struct.unpack("<3f", record)):
                    total[axis] += value
                used += 1
    except OSError:
        return None
    if not used:
        return None
    return tuple(total[axis] / used / float(scale) + float(center[axis]) for axis in range(3))


def ghost_shell_presentation(parameters, centre):
    """How the preview draws a SkinnedMeshGhost part: a blended shell.

    The game's Ghost shader reads no texture colour (permutation
    3fe935f0e737c889). Its coverage is
        a = saturate(F ^ |_ghostFresnelAlpha| * mask * _ghostOpacity)
        F = |N.V|, or 1 - |N.V| when _ghostFresnelAlpha is negative
        mask = saturate((d - _ghostMaskRadius + noise)
                        / max(0.001, _ghostMaskHardness * saturate(_ghostMaskRadius * 10)))
    drawn by a dithered discard, with _ghostColor as colour and emission, and
    _ghostMetallic and _ghostRoughness as the surface. The distance d arrives
    from the vertex shader; it is taken here as the distance from
    _ghostMaskPosition in model space (inferred: under that reading the monocle
    lens of cd_phm_00_hel_00_0451 is nearly clear, as its icon shows). The
    preview has no dither, so the shell is blended at one coverage for the
    part: F at its mean over a facing sphere, the mask at the centre of the
    part, no noise.
    """
    values = dict(_GHOST_DEFAULTS)
    position = _GHOST_DEFAULT_MASK_POSITION
    colour = _GHOST_DEFAULT_COLOUR
    for name, value in parameters.items():
        key = str(name).casefold().lstrip("_")
        if key in values:
            number = _preview_core_ghost_floats(value, 1)
            if number is not None:
                values[key] = number[0]
        elif key == "ghostmaskposition":
            position = tuple(_preview_core_ghost_floats(value, 3) or position)
        elif key == "ghostcolor":
            authored = pac_color_bytes(value)
            if authored is not None:
                colour = authored[:3]
    power = abs(values["ghostfresnelalpha"])
    # Mean of F^k over the projected area of a sphere (weight 2 N.V over N.V in 0..1).
    fresnel = 2.0 / (power + 2.0) if values["ghostfresnelalpha"] >= 0.0 else 2.0 / ((power + 1.0) * (power + 2.0))
    mask = 1.0
    if centre is not None:
        radius = values["ghostmaskradius"]
        mask = (math.dist(centre, position) - radius) / max(
            0.001, values["ghostmaskhardness"] * max(0.0, min(1.0, radius * 10.0)),
        )
        mask = max(0.0, min(1.0, mask))
    return {
        "alpha_mode": "blend",
        "opacity": max(0.0, min(1.0, fresnel * mask * max(0.0, min(1.0, values["ghostopacity"])))),
        "metalness": max(0.0, min(1.0, values["ghostmetallic"])),
        "roughness": max(0.0, min(1.0, values["ghostroughness"])),
        "colour": [float(component) for component in colour],
    }


def _apply_preview_core_ghost_shells(presentations, graph, raw_batches, parameters, source_package, center, scale):
    """Draw the parts of the game's Ghost shader as blended shells.

    A Ghost wrapper usually names no texture, so its batch has no binding: no
    layer row and no presentation row carries its shader family or wrapper.
    The conservation table keeps every declared parameter with its family, its
    model (component scope) and its submesh name, and a batch states the same
    two, so the wrapper is found by them.
    """
    ghosts: dict[tuple[str, str], dict[str, object]] = {}
    for parameter in parameters:
        if (
            isinstance(parameter, Mapping)
            and str(parameter.get("shader_family", "") or "").casefold() == "skinnedmeshghost"
        ):
            key = (
                str(parameter.get("component_scope_id", "") or ""),
                str(parameter.get("material_name", "") or "").casefold(),
            )
            ghosts.setdefault(key, {})[str(parameter.get("parameter_name", ""))] = parameter.get("value", "")
    materials = graph.get("materials") if isinstance(graph, Mapping) else None
    if not ghosts or not isinstance(materials, list):
        return
    rows = {
        (row.get("lod_index"), row.get("material_index")): row
        for row in presentations if isinstance(row, dict)
    }
    for raw_batch, material in zip(raw_batches, materials):
        identity = raw_batch.get("editor_identity") if isinstance(raw_batch, Mapping) else None
        if not isinstance(identity, Mapping) or not isinstance(material, dict):
            continue
        wrapper = ghosts.get((
            str(identity.get("component_scope_id", "") or ""),
            str(identity.get("part_name", "") or "").casefold(),
        ))
        row = rows.get((material.get("lod_index"), material.get("material_index")))
        if wrapper is None or row is None:
            continue
        shell = ghost_shell_presentation(
            wrapper, _preview_core_batch_centre(source_package, raw_batch, center, scale),
        )
        material["base_color"] = shell.pop("colour")
        row.update(shell)
        row["alpha_cutoff"] = 0.0


# The game's leaf shaders (GrassLeaf, TreeLeaf, TreeFrond): roughness by face,
# (front, back), from no texture and no parameter.
_LEAF_ROUGHNESS = {
    "skinnedmeshgrassleaf": (0.45, 0.45),
    "skinnedmeshtreeleaf": (1.0, 0.30),
    "skinnedmeshtreefrond": (1.0, 0.60),
}
# shader_controls[0] of a leaf part: the renderer's leaf rule.
LEAF_SHADER_KIND = 20.0


def leaf_surface_presentation(family, parameters):
    """How the preview draws a part of the game's leaf shaders, or None.

    GrassLeaf, TreeLeaf and TreeFrond share one pixel shader (permutations
    c148717afa198273, 0bfb2ab3479b9972, c37dd47c3db87f5d and their AlphaTest
    twins); they differ in roughness only:

        gc = srgb_to_linear(_grassColor.rgb),  ga = _grassColor.a
        t  = sqrt(base * gc);  tint = t * Y(base) / max(0.001, Y(t))
        albedo = lerp(base, tint, ga * mb),  times 1.1 on back faces
        roughness = GrassLeaf 0.45 + 0.005 d (both faces)
                    TreeLeaf  front 1.0, back 0.30 + 0.005 d
                    TreeFrond front 1.0, back 0.60 + 0.005 d
        no metal (the metal byte holds a per-family constant)
        AlphaTest: discard if base alpha < 0.5 (with the instance's alpha-test bit)

    d is a view distance (inferred from the form); the preview takes the ramp's
    start. `_materialTexture` gives neither roughness nor metal: the shader reads
    only its blue, and only as mb when `_grassBitFlag` bit 0 is set, which no
    shipped wrapper does, so mb is 1 here. The alpha-test bit is per instance; a
    leaf part with the AlphaTest permutation is taken to have it set.

    Returns presentation fields: shader_controls (kind 20; lanes 4 and 5 the
    front and back roughness, lane 6 the tint strength, lanes 7 to 9 the tint
    colour as sRGB), alpha_mode and alpha_cutoff.
    """
    roughness = _LEAF_ROUGHNESS.get(str(family or "").strip().casefold())
    if roughness is None:
        return None
    values = {str(name).casefold().lstrip("_"): value for name, value in dict(parameters).items()}
    colour = pac_color_bytes(values.get("grasscolor")) or (0.0, 0.0, 0.0, 0.0)
    controls = [0.0] * 32
    controls[0] = LEAF_SHADER_KIND
    controls[4], controls[5] = roughness
    controls[6] = float(colour[3])
    controls[7:10] = [float(component) for component in colour[:3]]
    alpha_test = _preview_core_int(values.get("alphatest"), 0) != 0
    return {
        "shader_controls": controls,
        "alpha_mode": "cutout" if alpha_test else "opaque",
        "alpha_cutoff": 0.5 if alpha_test else 0.0,
    }


# shader_controls[0] of a Wing part: the renderer's wing rule (its flow-map
# discard). Lane 20 asks for the alpha-test step's rgb / a.
WING_SHADER_KIND = 1.0
# The preview's _wingFlowProgress where the wrapper sets none: the formula's
# own "whole wing shown" point (inferred, see wing_surface_presentation).
WING_DEFAULT_PROGRESS = 2.0


def wing_flow_discard(flow_red, flow_blue, progress, inverse):
    """The second discard of the game's Wing shader (permutation 20670511ba45c617).

        g = (_wingFlowInverse >= 0.001) ? 1 - fb : fb
        p = saturate(2 g - _wingFlowProgress) * 2
        discard if saturate(p - fr) > 0.001

    fr is `_wingFlowTex1` red at uv * 4, fb its blue at uv. The renderer's
    shader kind 1 draws this rule; this is its statement for tests.
    """
    g = 1.0 - flow_blue if inverse >= 0.001 else flow_blue
    p = min(1.0, max(0.0, 2.0 * g - progress)) * 2.0
    return min(1.0, max(0.0, p - flow_red)) > 0.001


def wing_surface_presentation(parameters):
    """How the preview draws a part of the game's Wing shader.

    Wing is the Standard albedo path (the first 673 instructions of its pixel
    shader match Standard's alpha-test permutation) plus two discards, both
    unconditional because ALPHA_TEST is a define of the material file:

        discard if _baseColorTexture.a < 0.5 (with the instance's alpha-test bit),
        then base = rgb / a
        the flow-map discard of `wing_flow_discard`

    `_fresnelAlpha` only shades the emissive colour by view angle and no
    wrapper sets it (default 0: no shading). No shipped wrapper sets
    `_wingFlowProgress`, `_wingFlowInverse` or `_wingFlowTex1` either; the
    material's default progress, -0.1, keeps 0.5% of the default flow map
    (cdfx_wing_flowmap.dds). The game drives the progress at run time from
    the unfold effect, which is not in the material, so the preview takes 2.0,
    where the formula shows the whole wing, unless the wrapper states one.

    Returns shader_controls (kind 1: lane 4 the progress, lane 5 the inverse
    switch, lane 20 the rgb / a step), alpha_mode and alpha_cutoff.
    """
    values = {str(name).casefold().lstrip("_"): value for name, value in dict(parameters).items()}

    def number(name, default):
        try:
            value = float(values.get(name, default))
        except (TypeError, ValueError):
            return default
        return value if math.isfinite(value) else default

    controls = [0.0] * 32
    controls[0] = WING_SHADER_KIND
    controls[4] = number("wingflowprogress", WING_DEFAULT_PROGRESS)
    controls[5] = number("wingflowinverse", 0.0)
    controls[20] = 1.0
    return {"shader_controls": controls, "alpha_mode": "cutout", "alpha_cutoff": 0.5}


def _family_surface_presentation(family, parameters):
    family = str(family or "").strip().casefold()
    if family == "skinnedmeshwing":
        return wing_surface_presentation(parameters)
    return leaf_surface_presentation(family, parameters)


def _apply_preview_core_family_surfaces(presentations, graph, raw_batches, parameters):
    """Draw the parts of the game's leaf and Wing shaders by their own rules.

    The wrapper is the base layer's: its model scope, wrapper item and index.
    """
    wrappers: dict[tuple[str, str, int], tuple[str, dict[str, object]]] = {}
    for parameter in parameters:
        if (
            isinstance(parameter, Mapping)
            and (
                str(parameter.get("shader_family", "") or "").casefold() in _LEAF_ROUGHNESS
                or str(parameter.get("shader_family", "") or "").casefold() == "skinnedmeshwing"
            )
        ):
            key = (
                str(parameter.get("component_scope_id", "") or ""),
                str(parameter.get("owner_wrapper_item_id", "") or ""),
                _preview_core_int(parameter.get("material_wrapper_index"), -1),
            )
            wrappers.setdefault(key, (str(parameter.get("shader_family", "")), {}))[1][
                str(parameter.get("parameter_name", ""))
            ] = parameter.get("value", "")
    materials = graph.get("materials") if isinstance(graph, Mapping) else None
    if not wrappers or not isinstance(materials, list):
        return
    rows = {
        (row.get("lod_index"), row.get("material_index")): row
        for row in presentations if isinstance(row, dict)
    }
    for raw_batch, material in zip(raw_batches, materials):
        if not isinstance(raw_batch, Mapping) or not isinstance(material, dict):
            continue
        base = next(
            (
                layer for layer in raw_batch.get("material_layers", ()) or ()
                if isinstance(layer, Mapping)
                and str(layer.get("layer_role", "") or "").casefold() == "base"
            ),
            None,
        )
        row = rows.get((material.get("lod_index"), material.get("material_index")))
        if base is None or row is None:
            continue
        wrapper = wrappers.get((
            str(base.get("component_scope_id", "") or ""),
            str(base.get("owner_wrapper_item_id", "") or ""),
            _preview_core_int(base.get("material_wrapper_index"), -1),
        ))
        if wrapper is None:
            continue
        surface = _family_surface_presentation(*wrapper)
        if surface is not None:
            row.update(surface)


def _apply_preview_core_no_render_parts(presentations, graph, raw_batches, wrappers):
    """Leave out the parts the game does not draw.

    SkinnedMeshNoRender ships no shader (technique SkinnedMeshNoRender): the
    part exists for the engine, a socket or a cover, and is never drawn. Its
    wrapper declares no parameter and names no texture, so no binding, layer
    row or parameter row carries its family. Preview Core states every wrapper
    of the model in the conservation table's wrapper list; the part is found
    there by its model (component scope) and submesh name, and is stated as a
    blended shell of no coverage. The part keeps its place in the part list.

    A model whose every part is NoRender (a socket opened on its own) keeps
    its parts drawn: hiding them would leave nothing to look at, and the
    headless capture refuses a frame that holds only the clear colour.
    """
    hidden = {
        (
            str(wrapper.get("component_scope_id", "") or ""),
            str(wrapper.get("material_name", "") or "").casefold(),
        )
        for wrapper in wrappers
        if isinstance(wrapper, Mapping)
        and str(wrapper.get("shader_family", "") or "").casefold() == "skinnedmeshnorender"
    }
    materials = graph.get("materials") if isinstance(graph, Mapping) else None
    if not hidden or not isinstance(materials, list):
        return
    rows = {
        (row.get("lod_index"), row.get("material_index")): row
        for row in presentations if isinstance(row, dict)
    }
    targets = []
    for raw_batch, material in zip(raw_batches, materials):
        identity = raw_batch.get("editor_identity") if isinstance(raw_batch, Mapping) else None
        if not isinstance(identity, Mapping) or not isinstance(material, dict):
            continue
        key = (
            str(identity.get("component_scope_id", "") or ""),
            str(identity.get("part_name", "") or "").casefold(),
        )
        row = rows.get((material.get("lod_index"), material.get("material_index")))
        if key in hidden and row is not None:
            targets.append(row)
    if len({id(row) for row in targets}) >= len(rows):
        return
    for row in targets:
        row.update({"alpha_mode": "blend", "opacity": 0.0, "alpha_cutoff": 0.0})


def _build_preview_core_material_graph(
    source_package: Path,
    package_dir: Path,
    raw_batches: Sequence[object],
    *,
    quality: str,
    textures: Sequence[object],
    expected_root_identity: tuple[int, int],
    cancelled: Callable[[], bool] | None,
    material_parameters: Sequence[object] = (),
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
        _preview_core_layer_parameter_index(material_parameters),
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
    include_material_resources, material_parameters,
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
        material_parameters=material_parameters,
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
    jobs = []
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
        total_vertices += vertex_count
        jobs.append((fallback_index, raw_batch, raw_index, vertex_count))

    abort = threading.Event()

    def copy_cancelled():
        return abort.is_set() or bool(cancelled and cancelled())

    def copy_batch(job):
        fallback_index, raw_batch, raw_index, vertex_count = job
        _cancelled(copy_cancelled)
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
            cancelled=copy_cancelled,
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
                    cancelled=copy_cancelled,
                )
        source_index = _preview_core_int(identity.get("source_submesh_index"), raw_index)
        local_index = _preview_core_int(identity.get("source_local_submesh_index"), 0)
        component_index = _preview_core_int(identity.get("source_component_index"), 0)
        component_label = str(identity.get("source_component_label", "") or "prefab")
        name = f"reference_prefab_{component_index}_{local_index}_{component_label}"
        material = str(raw_batch.get("material_name", "") or component_label)
        direct = {
            "index": raw_index,
            "name": name,
            "material": material,
            "vertex_count": vertex_count,
            "vertices": geometry_reference,
            "identity": identity_reference,
        }
        part = {
            "scene_submesh_index": fallback_index,
            "source_submesh_index": source_index,
            "name": name,
            "material": material,
        }
        destination_geometry = package_dir / str(geometry_reference["path"])
        return (raw_batch, destination_geometry, vertex_count), direct, part

    if len(jobs) <= 1:
        copied = [copy_batch(job) for job in jobs]
    else:
        copied = []
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="cdmw-geometry-copy") as pool:
            for start in range(0, len(jobs), 4):
                futures = [pool.submit(copy_batch, job) for job in jobs[start : start + 4]]
                try:
                    copied.extend(future.result() for future in futures)
                except BaseException:
                    abort.set()
                    for future in futures:
                        future.cancel()
                    raise  # Join every worker before atomic-publication cleanup.
    for prepared, direct, part in copied:
        prepared_batches.append(prepared)
        direct_batches.append(direct)
        part_identities.append(part)
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
        material_graph_version not in {4, _PREVIEW_CORE_MATERIAL_GRAPH_VERSION}
        or material_semantics_version != _PREVIEW_CORE_MATERIAL_SEMANTICS_VERSION
    ):
        raise ValueError(
            "Direct preview requires Preview Core material graph v4 or v5 and semantics v10."
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
        raw_material_conservation.get("parameters", ()),
    )
    _apply_preview_core_ghost_shells(
        presentations, preview_core_material_graph, raw_batches,
        raw_material_conservation.get("parameters", ()), source_package, center, scale,
    )
    _apply_preview_core_family_surfaces(
        presentations, preview_core_material_graph, raw_batches,
        raw_material_conservation.get("parameters", ()),
    )
    _apply_preview_core_no_render_parts(
        presentations, preview_core_material_graph, raw_batches,
        raw_material_conservation.get("wrappers", ()),
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
            "material_graph_version": _PREVIEW_CORE_MATERIAL_GRAPH_VERSION,
            "material_semantics_version": material_semantics_version,
            "format": source_format,
            "source_sha256": source_sha256,
            "normalization_center": list(center),
            "normalization_scale": scale,
            "batches": direct_batches,
        },
        "material_contract": {
            "graph_version": _PREVIEW_CORE_MATERIAL_GRAPH_VERSION,
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
        durable=_preview_files.PREVIEW_CACHE_FSYNC,
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
        # Only texture_files changes here. Avoid copying every surface vertex,
        # normal and triangle a second time while preparing the same package.
        effect_payload = dict(effects_overlay)
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


def _composite_preview_core_material_graph(package_dir, scene, textures, presentations, quality, root_identity, cancelled):
    """Copy native layers with scene-local draw indices, including reference roles."""
    from cdmw.services.mesh_rust_authoring import _mesh_lods
    from cdmw.services.mesh_preview_material_source import unedited_preview_core_material_source

    sources = []
    for lod_index, submeshes in enumerate(_mesh_lods(scene)):
        for material_index, submesh in enumerate(submeshes):
            overrides = getattr(submesh, "preview_native_material_overrides", {}) or {}
            source = unedited_preview_core_material_source(submesh)
            if source is not None:
                painted = overrides.get("painted_texture_channels", {})
                channels = (1 if "opacity" in painted else 0) | (2 if "material" in painted else 0)
                sources.append((lod_index, material_index, source, channels))
    if not sources:
        return None
    if len(sources) > _PREVIEW_CORE_BATCH_LIMIT:
        raise ValueError("Combined preview exceeds the bounded material graph limit.")
    resources, next_index, aggregate_bytes = _preview_core_material_resource_index(package_dir, textures)
    initial_resources = set(resources)
    copied_sources, materials = {}, []
    source_edge_count = 0
    slots = {(row["lod_index"], row["material_index"]): row["material_slot_index"] for row in presentations}
    for lod_index, material_index, source, channels in sources:
        _cancelled(cancelled)
        aggregate_bytes, source_edge_count = _copy_preview_core_material_layers(
            [source["batch"]], Path(source["package"]), package_dir, quality, resources,
            next_index, aggregate_bytes, copied_sources, materials, source_edge_count, cancelled, root_identity,
            _preview_core_layer_parameter_index(source["conservation"].get("parameters", ())),
            durable=False,
        )
        materials[-1].update(lod_index=lod_index, material_index=material_index,
                             material_slot_index=slots.get((lod_index, material_index), material_index))
        if channels:
            materials[-1]["authoring_channels"] = channels
        next_index = max(next_index, len(resources))
    return {
        "schema_version": _PREVIEW_CORE_MATERIAL_GRAPH_SCHEMA,
        "graph_version": _PREVIEW_CORE_MATERIAL_GRAPH_VERSION,
        "semantics_version": _PREVIEW_CORE_MATERIAL_SEMANTICS_VERSION,
        "quality": quality, "resources_included": quality == "full",
        "source_edge_count": source_edge_count,
        "unique_resource_count": len(resources),
        "copied_resource_count": len(set(resources) - initial_resources),
        "unique_resource_bytes": aggregate_bytes, "materials": materials,
    }


def _finite_preview_document(document: dict[str, object]) -> dict[str, object]:
    """Keep NaN and infinity out of document.json, which the Rust host reads as strict JSON.

    Some shipped static meshes store NaN bit patterns in the UV field of their vertex records
    (456 PAMLOD levels in game 1.0.0.3446). The preview draws those UVs at 0 and lists them in
    the document warnings. A non-finite position or normal is not authored data, so the package
    is refused with the part named instead of being written as JSON the host cannot read.
    """
    for lod in document["lods"]:
        for part in lod["submeshes"]:
            for channel in ("positions", "normals"):
                if not _finite_rows(part[channel]):
                    raise ValueError(
                        f"Preview refused: LOD {lod['level']} part '{part['name']}' has a vertex "
                        f"{channel[:-1]} that is not a finite number, so its geometry was not read correctly."
                    )
            if not _finite_rows(part["uvs"]):
                rows = part["uvs"]
                count = sum(1 for row in rows if not all(math.isfinite(value) for value in row))
                part["uvs"] = [[value if math.isfinite(value) else 0.0 for value in row] for row in rows]
                document["warnings"].append(
                    f"LOD {lod['level']} part '{part['name']}': {count} source UVs are not finite numbers "
                    "and are drawn at 0."
                )
    return document


def _finite_rows(rows) -> bool:
    # The nested sum stays in C, and any NaN or infinity makes the total non-finite. A total that
    # overflows from large finite values falls through to the exact per-value check.
    return math.isfinite(sum(map(sum, rows))) or all(math.isfinite(value) for row in rows for value in row)


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
        _finite_preview_document(_mesh_document_payload(scene, allow_preview_formats=True)),
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
    return document, channels, textures, presentations, synthesis


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
        document, channels, textures, presentations, synthesis,
    ) = _write_preview_mesh_resources(
        package_dir, scene, root_identity, include_material_resources, material_package_path, quality,
        cancelled,
    )
    texture_status = _texture_status(textures, quality)
    if synthesis.budget_skipped:
        # These parts keep their direct DDS instead of composed materials.
        texture_status["material_synthesis_budget_skipped"] = len(synthesis.budget_skipped)
        _LOGGER.warning(
            "rust_preview_material_synthesis_budget source=%s parts=%d",
            str(getattr(mesh, "path", "") or ""),
            len(synthesis.budget_skipped),
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
        "texture_status": texture_status,
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
    if include_material_resources:
        graph = _composite_preview_core_material_graph(
            package_dir, scene, textures, presentations, quality, root_identity, cancelled,
        )
        if graph is not None:
            manifest["preview_core_material_graph"] = graph
            from cdmw.services.mesh_preview_material_source import preview_core_material_contract
            manifest["material_contract"] = preview_core_material_contract(scene)
    manifest_path = package_dir / "manifest.json"
    # Dense effect surfaces can exceed the shared Python/Rust 16 MiB limit
    # from indentation alone. Keep every value, and reject genuinely oversized
    # inputs on this worker before atomic publication or viewport handoff.
    manifest_json = json.dumps(manifest, separators=(",", ":"), sort_keys=True)
    if len(manifest_json) > _PREVIEW_MANIFEST_MAX_BYTES:  # ensure_ascii keeps bytes == characters
        raise ValueError("preview manifest exceeds its size limit")
    atomic_write_text(manifest_path, manifest_json, durable=_preview_files.PREVIEW_CACHE_FSYNC)
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


def _preview_manifest_package_dir(path: Path | str) -> tuple[Path, Path]:
    package_dir = Path(path)
    if package_dir.is_file():
        package_dir = package_dir.parent
    manifest_path = package_dir / "manifest.json"
    if manifest_path.stat().st_size > _PREVIEW_MANIFEST_MAX_BYTES:
        raise ValueError("preview manifest exceeds its size limit")
    return package_dir, manifest_path


def _checked_preview_manifest(payload: object) -> dict:
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
    return payload


def _read_preview_manifest(path: Path | str) -> tuple[Path, dict]:
    package_dir, manifest_path = _preview_manifest_package_dir(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return package_dir, _checked_preview_manifest(payload)


def _preview_manifest_session_id(payload: object) -> str:
    return str(_checked_preview_manifest(payload).get("session_id", "") or "")


def rust_preview_package_from_path(path: Path | str) -> RustPreviewPackage:
    # The session is all this needs of a manifest that can be megabytes; it is
    # read once per unchanged file (the UI thread asks on every package load).
    package_dir, manifest_path = _preview_manifest_package_dir(path)
    session_id = json_file_fact(manifest_path, _preview_manifest_session_id)
    return RustPreviewPackage(
        package_dir=package_dir.resolve(),
        manifest_path=manifest_path.resolve(),
        status_path=package_dir / "rust-preview-status.json",
        output_dir=package_dir,
        edit_operations_path=package_dir / "rust-preview-read-only.json",
        scene_session_id=session_id,
    )


# Packages this process found valid, with the identity of their manifest and
# of every folder that holds one of their files. Published preview files are
# never rewritten in place: a file added, removed, renamed or replaced (a
# cache prune included) changes its folder's modification time, and any
# manifest rewrite changes the manifest's identity. While both hold, the UI
# thread's structural check (hash_unverified=False) is not repeated: a set's
# packages hold hundreds of files and the walk held the UI thread 275 ms in
# the review. Full checks (hash_unverified=True) always run in full.
_VALID_PACKAGE_LIMIT = 4096
_VALID_PACKAGE_MIN_AGE_NS = 100_000_000
_valid_packages_lock = threading.Lock()
_valid_packages: "OrderedDict[str, tuple]" = OrderedDict()


def _package_stamp(manifest_path: Path, folders) -> tuple | None:
    try:
        manifest = os.stat(manifest_path)
        if not int(getattr(manifest, "st_ino", 0) or 0):
            return None
        stamps = [(str(manifest_path), manifest.st_dev, manifest.st_ino, manifest.st_size, manifest.st_mtime_ns)]
        for folder in sorted(folders, key=str):
            identity = os.lstat(folder)
            stamps.append((str(folder), identity.st_dev, identity.st_ino, identity.st_mtime_ns))
    except OSError:
        return None
    return tuple(stamps)


# Volumes whose times are whole 10 ms steps (FAT, exFAT) do not reliably
# change a folder's time when a file in it goes: nothing is remembered there.
_VALID_PACKAGE_COARSE_STEP_NS = 10_000_000


def _stamp_older_than(stamp: tuple, started_ns: int) -> bool:
    return all(
        started_ns - int(item[-1]) >= _VALID_PACKAGE_MIN_AGE_NS
        and int(item[-1]) % _VALID_PACKAGE_COARSE_STEP_NS != 0
        for item in stamp
    )


def _known_valid_package(package_dir: Path) -> bool:
    key = os.path.normcase(os.path.abspath(package_dir))
    with _valid_packages_lock:
        known = _valid_packages.get(key)
    if known is None:
        return False
    manifest_path, folders, stamp = known
    if _package_stamp(manifest_path, folders) != stamp:
        with _valid_packages_lock:
            if _valid_packages.get(key) is known:
                del _valid_packages[key]
        return False
    with _valid_packages_lock:
        if key in _valid_packages:
            _valid_packages.move_to_end(key)
    return True


def _remember_valid_package(package_dir: Path, folders: set[Path], started_ns: int) -> None:
    manifest_path = package_dir / "manifest.json"
    stamp = _package_stamp(manifest_path, folders)
    if stamp is None or not _stamp_older_than(stamp, started_ns):
        return
    key = os.path.normcase(os.path.abspath(package_dir))
    with _valid_packages_lock:
        _valid_packages[key] = (manifest_path, tuple(folders), stamp)
        _valid_packages.move_to_end(key)
        while len(_valid_packages) > _VALID_PACKAGE_LIMIT:
            _valid_packages.popitem(last=False)


def forget_valid_preview_packages() -> None:
    """Start from an empty memo (tests)."""

    with _valid_packages_lock:
        _valid_packages.clear()


def validate_rust_preview_package(path: Path | str, *, hash_unverified: bool = True) -> tuple[str, ...]:
    try:
        if not hash_unverified:
            package_dir, _manifest_path = _preview_manifest_package_dir(path)
            if _known_valid_package(package_dir):
                return ()
        started_ns = time.time_ns()
        package_dir, payload = _read_preview_manifest(path)
        folders: set[Path] = set()
        validate_preview_files(package_dir, payload, hash_unverified=hash_unverified, checked_dirs=folders)
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        return (str(exc),)
    _remember_valid_package(package_dir, folders, started_ns)
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
