"""glTF UV provenance, validation, and runtime-safe shared-transform baking."""

from __future__ import annotations

import io
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .scene_geometry_utils import _float_list, _safe_int


GLTF_IDENTITY_UV_TRANSFORM = (0.0, 0.0, 1.0, 1.0, 0.0)
GLTF_UV_BAKE_REMEDY = (
    "Bake every texture used by this material to one UV set (for example TEXCOORD_0), "
    "apply KHR_texture_transform into those UVs or the texture pixels, then export again."
)
_GLTF_UV_ACCESSOR_REMEDY = (
    "Export an uncompressed GLB/glTF with a complete, non-sparse VEC2 accessor for every referenced TEXCOORD_n."
)
_GLTF_TEXTURE_REMEDY = (
    "Export each material texture through textures[].source to a valid images[] PNG, JPEG, WebP, TGA, BMP, TIFF, or DDS payload."
)
_GLTF_IMAGE_FORMAT_SUFFIXES = {
    "BMP": {".bmp"},
    "DDS": {".dds"},
    "JPEG": {".jpg", ".jpeg"},
    "PNG": {".png"},
    "TGA": {".tga"},
    "TIFF": {".tif", ".tiff"},
    "WEBP": {".webp"},
}
_GLTF_IMAGE_MAX_SOURCE_BYTES = 256 * 1024 * 1024
_GLTF_IMAGE_MAX_DIMENSION = 8192
_GLTF_IMAGE_MAX_PIXELS = 4096 * 4096


@dataclass(slots=True, frozen=True)
class GltfTextureSlotUvProvenance:
    slot_key: str
    slot_kind: str
    texture_index: int
    image_index: int
    sampler_index: int
    texcoord: int
    transform: tuple[float, float, float, float, float]
    wrap_s: int
    wrap_t: int
    min_filter: int
    mag_filter: int
    normal_scale: float = 1.0


@dataclass(slots=True, frozen=True)
class GltfMaterialUvPlan:
    material_index: int
    material_name: str
    slots: tuple[GltfTextureSlotUvProvenance, ...]
    source_texcoord: int
    transform: tuple[float, float, float, float, float]

    @property
    def bakes_transform(self) -> bool:
        return bool(
            self.slots
            and not self.requires_raster_bake
            and self.transform != GLTF_IDENTITY_UV_TRANSFORM
        )

    @property
    def source_texcoords(self) -> tuple[int, ...]:
        return tuple(sorted({slot.texcoord for slot in self.slots}))

    @property
    def transforms(self) -> tuple[tuple[float, float, float, float, float], ...]:
        return tuple(sorted({slot.transform for slot in self.slots}))

    @property
    def requires_raster_bake(self) -> bool:
        return len(self.source_texcoords) > 1 or len(self.transforms) > 1


@dataclass(slots=True, frozen=True)
class GltfPrimitiveUvSet:
    texcoord: int
    accessor_index: int
    raw_gltf_uvs: tuple[tuple[float, float], ...]


@dataclass(slots=True, frozen=True)
class GltfPrimitiveUvInputs:
    primitive_label: str
    sets: tuple[GltfPrimitiveUvSet, ...]

    def rows(self, texcoord: int) -> tuple[tuple[float, float], ...]:
        for uv_set in self.sets:
            if uv_set.texcoord == texcoord:
                return uv_set.raw_gltf_uvs
        return ()


def _gltf_texture_info_texcoord(texture_info: object) -> int:
    if not isinstance(texture_info, Mapping):
        return 0
    texcoord = max(0, _safe_int(texture_info.get("texCoord"), 0))
    extensions = texture_info.get("extensions", {})
    transform = extensions.get("KHR_texture_transform") if isinstance(extensions, Mapping) else None
    if isinstance(transform, Mapping) and "texCoord" in transform:
        return max(0, _safe_int(transform.get("texCoord"), texcoord))
    return texcoord


def _gltf_texture_transform(texture_info: object) -> tuple[float, ...]:
    if not isinstance(texture_info, Mapping):
        return ()
    extensions = texture_info.get("extensions", {})
    transform = extensions.get("KHR_texture_transform") if isinstance(extensions, Mapping) else None
    if not isinstance(transform, Mapping):
        return ()
    offset = _float_list(transform.get("offset"), 2, (0.0, 0.0))
    scale = _float_list(transform.get("scale"), 2, (1.0, 1.0))
    try:
        rotation = float(transform.get("rotation", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        rotation = 0.0
    return (offset[0], offset[1], scale[0], scale[1], rotation)


def _canonical_transform(texture_info: object, material_name: str) -> tuple[float, float, float, float, float]:
    transform = tuple(_gltf_texture_transform(texture_info) or GLTF_IDENTITY_UV_TRANSFORM)
    if len(transform) != 5 or not all(math.isfinite(value) for value in transform):
        raise ValueError(
            f"glTF material {material_name} has a non-finite KHR_texture_transform. {GLTF_UV_BAKE_REMEDY}"
        )
    return transform  # type: ignore[return-value]


def _sequence(document: Mapping[str, object], key: str) -> Sequence[object]:
    value = document.get(key, ())
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _required_index(value: object, label: str, material_name: str, slot_key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"glTF material {material_name} slot {slot_key} has invalid {label} {value!r}. {_GLTF_TEXTURE_REMEDY}"
        )
    return value


def _validated_image_reference(
    document: Mapping[str, object], material_name: str, slot_key: str, image_index: int
) -> None:
    images = _sequence(document, "images")
    image = images[image_index] if 0 <= image_index < len(images) else None
    if not isinstance(image, Mapping):
        raise ValueError(
            f"glTF material {material_name} slot {slot_key} references invalid image index {image_index}. {_GLTF_TEXTURE_REMEDY}"
        )
    uri = image.get("uri")
    if "uri" in image and not isinstance(uri, str):
        raise ValueError(f"glTF image {image_index} has an invalid URI. {_GLTF_TEXTURE_REMEDY}")
    has_uri = bool(str(uri or "").strip())
    has_view = "bufferView" in image
    if has_uri == has_view:
        blocker = "both URI and bufferView" if has_uri else "neither URI nor bufferView"
        raise ValueError(f"glTF image {image_index} has {blocker}. {_GLTF_TEXTURE_REMEDY}")
    if not has_view:
        return
    view_index = _required_index(image.get("bufferView"), "image bufferView index", material_name, slot_key)
    views = _sequence(document, "bufferViews")
    view = views[view_index] if 0 <= view_index < len(views) else None
    if not isinstance(view, Mapping):
        raise ValueError(f"glTF image {image_index} references invalid bufferView {view_index}. {_GLTF_TEXTURE_REMEDY}")
    buffer_index = _required_index(view.get("buffer"), "image buffer index", material_name, slot_key)
    buffers = _sequence(document, "buffers")
    if buffer_index >= len(buffers) or not isinstance(buffers[buffer_index], Mapping):
        raise ValueError(f"glTF image {image_index} bufferView {view_index} references invalid buffer {buffer_index}. {_GLTF_TEXTURE_REMEDY}")
    if not isinstance(image.get("mimeType"), str) or not str(image.get("mimeType") or "").strip():
        raise ValueError(f"glTF image {image_index} bufferView {view_index} has no MIME type. {_GLTF_TEXTURE_REMEDY}")


def _validate_gltf_image_payload(
    source: bytes | Path, image_index: int, expected_suffix: str
) -> None:
    from PIL import Image

    try:
        source_bytes = source.stat().st_size if isinstance(source, Path) else len(source)
    except OSError as exc:
        raise ValueError(f"glTF image {image_index} payload cannot be read. {_GLTF_TEXTURE_REMEDY}") from exc
    if source_bytes <= 0 or source_bytes > _GLTF_IMAGE_MAX_SOURCE_BYTES:
        raise ValueError(
            f"glTF image {image_index} payload is {source_bytes:,} bytes; maximum is {_GLTF_IMAGE_MAX_SOURCE_BYTES:,}. "
            f"{_GLTF_TEXTURE_REMEDY}"
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source if isinstance(source, Path) else io.BytesIO(source)) as image:
                image_format = str(image.format or "").upper()
                width, height = int(image.width), int(image.height)
                image.verify()
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError(f"glTF image {image_index} exceeds safe decode dimensions. {_GLTF_TEXTURE_REMEDY}") from exc
    except Exception as exc:
        raise ValueError(f"glTF image {image_index} has an invalid image payload. {_GLTF_TEXTURE_REMEDY}") from exc
    if (
        width <= 0
        or height <= 0
        or width > _GLTF_IMAGE_MAX_DIMENSION
        or height > _GLTF_IMAGE_MAX_DIMENSION
        or width * height > _GLTF_IMAGE_MAX_PIXELS
    ):
        raise ValueError(
            f"glTF image {image_index} dimensions {width}x{height} exceed the "
            f"{_GLTF_IMAGE_MAX_DIMENSION}px/{_GLTF_IMAGE_MAX_PIXELS:,}-pixel limit. {_GLTF_TEXTURE_REMEDY}"
        )
    allowed_suffixes = _GLTF_IMAGE_FORMAT_SUFFIXES.get(image_format, set())
    if expected_suffix.lower() not in allowed_suffixes:
        raise ValueError(
            f"glTF image {image_index} is declared as {expected_suffix or '<unknown>'} but contains {image_format or 'unknown'} data. "
            f"{_GLTF_TEXTURE_REMEDY}"
        )


def _slot_provenance(
    document: Mapping[str, object],
    material_name: str,
    slot_key: str,
    slot_kind: str,
    texture_info: Mapping[str, object],
) -> GltfTextureSlotUvProvenance:
    texture_index = _required_index(texture_info.get("index"), "texture index", material_name, slot_key)
    textures = _sequence(document, "textures")
    texture = textures[texture_index] if 0 <= texture_index < len(textures) else None
    if not isinstance(texture, Mapping):
        raise ValueError(
            f"glTF material {material_name} slot {slot_key} references invalid texture index {texture_index}. {_GLTF_TEXTURE_REMEDY}"
        )
    extensions = texture.get("extensions")
    if extensions is not None and not isinstance(extensions, Mapping):
        raise ValueError(f"glTF texture {texture_index} has invalid extensions metadata. {_GLTF_TEXTURE_REMEDY}")
    extension_sources = sorted(
        str(name)
        for name, value in (extensions.items() if isinstance(extensions, Mapping) else ())
        if name == "KHR_texture_basisu" or (isinstance(value, Mapping) and "source" in value)
    )
    if extension_sources:
        raise ValueError(
            f"glTF material {material_name} slot {slot_key} uses unsupported texture extension source "
            f"{', '.join(extension_sources)}. Decode it first. {_GLTF_TEXTURE_REMEDY}"
        )
    image_index = _required_index(texture.get("source"), "texture source index", material_name, slot_key)
    _validated_image_reference(document, material_name, slot_key, image_index)
    sampler_index = _safe_int(texture.get("sampler"), -1)
    samplers = _sequence(document, "samplers")
    sampler = samplers[sampler_index] if 0 <= sampler_index < len(samplers) else {}
    sampler = sampler if isinstance(sampler, Mapping) else {}
    normal_scale = 1.0
    if "normal" in str(slot_kind).lower():
        try:
            normal_scale = float(texture_info.get("scale", 1.0) or 0.0)
        except (TypeError, ValueError, OverflowError):
            normal_scale = math.nan
        if not math.isfinite(normal_scale):
            raise ValueError(f"glTF material {material_name} has an invalid {slot_key} normal scale.")
    return GltfTextureSlotUvProvenance(
        slot_key=str(slot_key),
        slot_kind=str(slot_kind),
        texture_index=texture_index,
        image_index=image_index,
        sampler_index=sampler_index,
        texcoord=_gltf_texture_info_texcoord(texture_info),
        transform=_canonical_transform(texture_info, material_name),
        wrap_s=_safe_int(sampler.get("wrapS"), 10497),
        wrap_t=_safe_int(sampler.get("wrapT"), 10497),
        min_filter=_safe_int(sampler.get("minFilter"), -1),
        mag_filter=_safe_int(sampler.get("magFilter"), -1),
        normal_scale=normal_scale,
    )


def build_gltf_material_uv_plan(
    document: Mapping[str, object],
    material_index: int,
    material_name: str,
    texture_infos: Sequence[tuple[str, str, object, str]],
) -> GltfMaterialUvPlan:
    invalid_slot = next(
        (slot_key for slot_key, _kind, texture_info, _name in texture_infos if texture_info is not None and not isinstance(texture_info, Mapping)),
        "",
    )
    if invalid_slot:
        raise ValueError(f"glTF material {material_name} slot {invalid_slot} has invalid texture metadata. {_GLTF_TEXTURE_REMEDY}")
    slots = tuple(sorted(
        (
            _slot_provenance(document, material_name, slot_key, slot_kind, texture_info)
            for slot_key, slot_kind, texture_info, _parameter_name in texture_infos
            if isinstance(texture_info, Mapping)
        ),
        key=lambda slot: (
            slot.slot_key,
            slot.slot_kind,
            slot.texcoord,
            slot.transform,
            slot.texture_index,
            slot.image_index,
        ),
    ))
    return GltfMaterialUvPlan(
        material_index=material_index,
        material_name=material_name,
        slots=slots,
        source_texcoord=min((slot.texcoord for slot in slots), default=0),
        transform=min((slot.transform for slot in slots), default=GLTF_IDENTITY_UV_TRANSFORM),
    )


def validate_gltf_primitive_uvs(
    document: Mapping[str, object],
    primitive: Mapping[str, object],
    plan: GltfMaterialUvPlan,
    primitive_label: str,
) -> int:
    inputs = read_gltf_primitive_uv_inputs(document, primitive, plan, primitive_label, None)
    return inputs.sets[0].accessor_index if inputs.sets else -1


def _validated_gltf_uv_accessor(
    document: Mapping[str, object],
    primitive: Mapping[str, object],
    plan: GltfMaterialUvPlan,
    primitive_label: str,
    texcoord: int,
) -> int:
    if not plan.slots:
        return -1
    attributes = primitive.get("attributes", {})
    attributes = attributes if isinstance(attributes, Mapping) else {}
    texcoord_name = f"TEXCOORD_{texcoord}"
    if texcoord_name not in attributes:
        raise ValueError(
            f"glTF primitive {primitive_label} material {plan.material_name} references {texcoord_name}, but the primitive "
            f"does not provide it. {_GLTF_UV_ACCESSOR_REMEDY}"
        )
    accessor_index = _safe_int(attributes.get(texcoord_name), -1)
    accessors = _sequence(document, "accessors")
    accessor = accessors[accessor_index] if 0 <= accessor_index < len(accessors) else None
    if not isinstance(accessor, Mapping):
        raise ValueError(
            f"glTF primitive {primitive_label} material {plan.material_name} references invalid {texcoord_name} accessor "
            f"{accessor_index}. {_GLTF_UV_ACCESSOR_REMEDY}"
        )
    if "sparse" in accessor:
        raise ValueError(
            f"glTF primitive {primitive_label} material {plan.material_name} references sparse {texcoord_name} accessor "
            f"{accessor_index}, which this import path cannot safely expand. {_GLTF_UV_ACCESSOR_REMEDY}"
        )
    position_index = _safe_int(attributes.get("POSITION"), -1)
    position = accessors[position_index] if 0 <= position_index < len(accessors) else None
    position_count = _safe_int(position.get("count"), -1) if isinstance(position, Mapping) else -1
    if str(accessor.get("type", "") or "") != "VEC2" or _safe_int(accessor.get("count"), -1) != position_count:
        raise ValueError(
            f"glTF primitive {primitive_label} material {plan.material_name} has incomplete {texcoord_name}; expected one "
            f"VEC2 row for each of {position_count} positions. {_GLTF_UV_ACCESSOR_REMEDY}"
        )
    return accessor_index


def read_gltf_primitive_uv_inputs(
    document: Mapping[str, object],
    primitive: Mapping[str, object],
    plan: GltfMaterialUvPlan,
    primitive_label: str,
    read_accessor: Callable[[int], Sequence[Sequence[float]]] | None,
) -> GltfPrimitiveUvInputs:
    sets: list[GltfPrimitiveUvSet] = []
    for texcoord in plan.source_texcoords:
        accessor_index = _validated_gltf_uv_accessor(
            document, primitive, plan, primitive_label, texcoord
        )
        rows = (
            tuple((float(row[0]), float(row[1])) for row in read_accessor(accessor_index))
            if read_accessor is not None
            else ()
        )
        sets.append(
            GltfPrimitiveUvSet(
                texcoord=texcoord,
                accessor_index=accessor_index,
                raw_gltf_uvs=rows,
            )
        )
    return GltfPrimitiveUvInputs(primitive_label=primitive_label, sets=tuple(sets))


def read_gltf_primitive_uv_set(
    document: Mapping[str, object],
    primitive: Mapping[str, object],
    plan: GltfMaterialUvPlan,
    primitive_label: str,
    read_accessor: Callable[[int], Sequence[Sequence[float]]],
) -> GltfPrimitiveUvSet | None:
    inputs = read_gltf_primitive_uv_inputs(
        document, primitive, plan, primitive_label, read_accessor
    )
    return inputs.sets[0] if inputs.sets else None


def transform_gltf_uv(
    uv: Sequence[float],
    transform: Sequence[float],
) -> tuple[float, float]:
    """Apply KHR_texture_transform in glTF UV space; callers may flip V afterwards."""
    u, v = float(uv[0]), float(uv[1])
    offset_u, offset_v, scale_u, scale_v, rotation = tuple(transform[:5])
    scaled_u, scaled_v = u * scale_u, v * scale_v
    cosine, sine = math.cos(rotation), math.sin(rotation)
    return (
        offset_u + cosine * scaled_u - sine * scaled_v,
        offset_v + sine * scaled_u + cosine * scaled_v,
    )


def build_gltf_uv_bake_report(
    plans: Sequence[GltfMaterialUvPlan],
    general_reports: Mapping[int, Mapping[str, object]] = {},
) -> dict[str, object]:
    material_rows: list[dict[str, object]] = []
    for plan in sorted(plans, key=lambda item: item.material_index):
        if not plan.slots:
            continue
        row: dict[str, object] = {
                "material_index": plan.material_index,
                "material_name": plan.material_name,
                "mode": (
                    "raster_bake"
                    if plan.requires_raster_bake
                    else "shared_affine_transform"
                    if plan.bakes_transform
                    else "single_uv_normalization"
                ),
                "source_uv_sets": [f"TEXCOORD_{index}" for index in plan.source_texcoords],
                "source_transforms": [list(transform) for transform in plan.transforms],
                "output_uv_set": "TEXCOORD_0",
                "output_transform": list(GLTF_IDENTITY_UV_TRANSFORM),
                "slots": [
                    {
                        "slot_key": slot.slot_key,
                        "slot_kind": slot.slot_kind,
                        "texture_index": slot.texture_index,
                        "image_index": slot.image_index,
                        "sampler_index": slot.sampler_index,
                        "texcoord": slot.texcoord,
                        "transform": list(slot.transform),
                        "sampler": {
                            "wrap_s": slot.wrap_s,
                            "wrap_t": slot.wrap_t,
                            "min_filter": slot.min_filter,
                            "mag_filter": slot.mag_filter,
                        },
                        "normal_scale": slot.normal_scale,
                    }
                    for slot in plan.slots
                ],
                "generated_texture_hashes": {},
                "output_dimensions": {},
                "warnings": [],
                "review_required": False,
            }
        if not plan.requires_raster_bake:
            row["source_transform"] = list(plan.transform)
        general_report = dict(general_reports.get(plan.material_index, {}))
        for key in ("generated_texture_hashes", "output_dimensions"):
            if isinstance(general_report.get(key), Mapping):
                general_report[key] = dict(sorted(general_report[key].items()))
        if isinstance(general_report.get("generated_slots"), Sequence):
            general_report["generated_slots"] = sorted(
                general_report["generated_slots"], key=lambda item: str(item.get("slot_key", "")) if isinstance(item, Mapping) else ""
            )
        if isinstance(general_report.get("warnings"), Sequence):
            general_report["warnings"] = sorted(str(value) for value in general_report["warnings"])
        for key in sorted(general_report):
            row[key] = general_report[key]
        material_rows.append(row)
    baked = bool(general_reports) or any(plan.bakes_transform for plan in plans)
    normalized = any(slot.texcoord != 0 for plan in plans for slot in plan.slots)
    warnings = [
        str(warning)
        for _material_index, report in sorted(general_reports.items())
        for warning in sorted(tuple(report.get("warnings", ()) or ()))
    ]
    return {
        "schema": "cdmw_gltf_uv_bake_report_v1",
        "schema_version": 1,
        "status": "baked" if baked else "normalized" if normalized else "not_required",
        "output_layout": (
            "xatlas_non_overlapping_texcoord_0"
            if general_reports
            else "source_affine_to_texcoord_0"
            if material_rows
            else "unchanged"
        ),
        "materials": material_rows,
        "generated_texture_hashes": {
            f"{material_index}:{slot}": str(digest)
            for material_index, report in sorted(general_reports.items())
            for slot, digest in sorted(dict(report.get("generated_texture_hashes", {}) or {}).items())
        },
        "output_dimensions": {
            f"{material_index}:{slot}": dimensions
            for material_index, report in sorted(general_reports.items())
            for slot, dimensions in sorted(dict(report.get("output_dimensions", {}) or {}).items())
        },
        "warnings": warnings,
        "review_required": any(bool(report.get("review_required")) for report in general_reports.values()),
    }


__all__ = [
    "GLTF_IDENTITY_UV_TRANSFORM",
    "GLTF_UV_BAKE_REMEDY",
    "GltfMaterialUvPlan",
    "GltfPrimitiveUvInputs",
    "GltfPrimitiveUvSet",
    "GltfTextureSlotUvProvenance",
    "build_gltf_material_uv_plan",
    "build_gltf_uv_bake_report",
    "read_gltf_primitive_uv_set",
    "read_gltf_primitive_uv_inputs",
    "transform_gltf_uv",
    "validate_gltf_primitive_uvs",
]
