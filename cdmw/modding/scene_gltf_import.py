from __future__ import annotations

import base64
import json
import re
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput
from cdmw.core.common import raise_if_cancelled

from .mesh_parser import ParsedMesh, SubMesh, _compute_smooth_normals
from .scene_gltf_geometry import (
    _GLTF_COMPONENT_FORMATS,
    _GLTF_TYPE_COUNTS,
    _attach_gltf_vertex_color_summary,
    _gltf_buffer_view,
    _normalize_gltf_component,
    _parse_gltf_primitive,
    _read_gltf_accessor,
    _read_gltf_buffer_view_bytes,
    _read_gltf_vertex_colors,
)
from .scene_gltf_embedded_images import (
    _MIME_EXTENSIONS as _GLTF_IMAGE_MIME_EXTENSIONS,
    _embedded_gltf_extract_dir,
    write_embedded_gltf_image,
)
from .scene_gltf_uv import (
    GltfMaterialUvPlan,
    _gltf_texture_info_texcoord,
    _gltf_texture_transform,
    _validate_gltf_image_payload,
    build_gltf_material_uv_plan,
    build_gltf_uv_bake_report,
    read_gltf_primitive_uv_inputs,
)
from .scene_gltf_uv_bake import (
    GltfGeneralUvBakeOutcome,
    GltfUvPrimitiveRecord,
    bake_general_gltf_uvs,
    ensure_gltf_source_tangents,
)
from .scene_geometry_utils import (
    _bbox,
    _copy_submesh_with_transform,
    _dedupe_text,
    _identity_matrix,
    _invert_affine_matrix,
    _float_list,
    _multiply_matrix,
    _normalize_vec,
    _resolve_scene_uri,
    _safe_int,
    _transform_point,
    _transform_vector,
)
from .scene_material_audit import (
    ImportedMaterialBinding,
    SceneMaterialTextureSlot,
    _append_scene_parameter,
    _apply_scene_material_slots_to_submesh,
    _result_with_external_audit,
    _scene_material_slot,
    _scene_preview_color_parameter,
    _scene_preview_float_parameter,
    _scene_parameter_color,
    _scene_parameter_numeric,
)

SCENE_TEXTURE_SOURCE_EXTENSIONS = {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp"}
SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS = {".ktx", ".ktx2"}
_GltfMaterialInfo = tuple[
    dict[int, str],
    dict[int, str],
    dict[int, tuple[float, float, float]],
    dict[int, dict[str, SceneMaterialTextureSlot]],
    dict[int, str],
    dict[int, dict[str, object]],
    dict[int, tuple[PreviewMaterialParameterInput, ...]],
]


def _dedupe_paths(values: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for value in values:
        try:
            key = value.expanduser().resolve().as_posix().lower()
        except OSError:
            key = value.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


@dataclass(slots=True)
class _GltfPayload:
    document: dict[str, Any]
    buffers: list[bytes]
    source_path: Path
    format_name: str
    diagnostics: list[str]
    extracted_embedded_files: list[Path]
    discovered_texture_files: list[Path]
    material_uv_plans: dict[int, GltfMaterialUvPlan]
    tolerate_missing_texture_files: bool = False


@dataclass(slots=True, frozen=True)
class _GltfMeshInstance:
    mesh_index: int
    transform: tuple[float, ...]
    node_name: str
    node_index: int = -1
    skin_index: int = -1


def _collect_gltf_geometry(
    payload: _GltfPayload,
    material_info: _GltfMaterialInfo,
    stop_event: threading.Event | None,
) -> tuple[list[SubMesh], list[ImportedMaterialBinding], list[GltfUvPrimitiveRecord], int]:
    (
        material_names,
        material_textures,
        material_colors,
        material_texture_slots,
        material_workflows,
        material_flags,
        material_preview_parameters,
    ) = material_info
    submeshes: list[SubMesh] = []
    bindings: list[ImportedMaterialBinding] = []
    uv_records: list[GltfUvPrimitiveRecord] = []
    instances = _iter_gltf_mesh_instances(payload.document) or [
        _GltfMeshInstance(index, _identity_matrix(), "")
        for index, _mesh in enumerate(payload.document.get("meshes", []) or [])
    ]
    skin_matrix_cache: dict[tuple[int, int], tuple[tuple[float, ...], ...]] = {}
    baked_skin_count = 0
    for instance in instances:
        raise_if_cancelled(stop_event, "glTF import cancelled during geometry parsing.")
        gltf_meshes = payload.document.get("meshes", []) or []
        if not 0 <= instance.mesh_index < len(gltf_meshes):
            continue
        mesh_entry = gltf_meshes[instance.mesh_index]
        mesh_name = str(mesh_entry.get("name", "") or "")
        for primitive_index, primitive in enumerate(mesh_entry.get("primitives", []) or []):
            if not isinstance(primitive, dict):
                continue
            primitive_label = f"{mesh_name or instance.mesh_index}:{primitive_index}"
            mode = _safe_int(primitive.get("mode"), 4)
            attributes = primitive.get("attributes", {})
            if mode not in {4, 5, 6}:
                payload.diagnostics.append(f"Skipped glTF primitive {primitive_label} because its topology mode is unsupported.")
                continue
            if not isinstance(attributes, dict) or "POSITION" not in attributes:
                payload.diagnostics.append(f"Skipped glTF primitive {primitive_label} because it has no POSITION attribute.")
                continue
            material_index = _safe_int(primitive.get("material"), -1)
            material_name = (material_names.get(material_index, "") or f"material_{material_index}") if material_index >= 0 else ""
            uv_plan = payload.material_uv_plans.get(material_index)
            uv_inputs = (
                read_gltf_primitive_uv_inputs(
                    payload.document,
                    primitive,
                    uv_plan,
                    primitive_label,
                    lambda accessor_index: _read_gltf_accessor(payload, accessor_index, expected_components=2),
                )
                if uv_plan is not None
                else None
            )
            submesh = _parse_gltf_primitive(
                payload,
                primitive,
                name=instance.node_name or mesh_name or f"mesh_{instance.mesh_index}_{primitive_index}",
                material=material_name or instance.node_name or mesh_name or primitive_label,
                texture=material_textures.get(material_index, ""),
                texcoord_index=(
                    uv_plan.source_texcoord
                    if uv_plan is not None and uv_plan.slots
                    else _gltf_material_texcoord_index(material_texture_slots, material_index)
                ),
                texcoord_transform=(uv_plan.transform if uv_plan is not None and uv_plan.bakes_transform else ()),
                texcoord_rows=(uv_inputs.rows(uv_plan.source_texcoord) if uv_inputs is not None and uv_plan is not None else None),
            )
            skin_matrices: tuple[tuple[float, ...], ...] = ()
            if instance.skin_index >= 0 and instance.node_index >= 0:
                cache_key = (instance.node_index, instance.skin_index)
                if cache_key not in skin_matrix_cache:
                    skin_matrix_cache[cache_key] = _gltf_skin_joint_matrices(
                        payload, node_index=instance.node_index, skin_index=instance.skin_index
                    )
                skin_matrices = skin_matrix_cache[cache_key]
            if skin_matrices and _bake_gltf_skin_primitive(payload, primitive, submesh, skin_matrices):
                baked_skin_count += 1
            if not submesh.faces:
                payload.diagnostics.append(f"Skipped glTF primitive {primitive_label} because it produced no triangle faces.")
                continue
            copied = _copy_submesh_with_transform(submesh, instance.transform)
            if uv_plan is not None and uv_inputs is not None and not uv_plan.requires_raster_bake and any(
                "normal" in slot.slot_kind.lower() for slot in uv_plan.slots
            ):
                ensure_gltf_source_tangents(copied, uv_inputs.rows(uv_plan.source_texcoord), uv_plan.source_texcoord, stop_event=stop_event)
            _apply_gltf_preview_material_metadata(
                copied,
                material_index,
                material_colors=material_colors,
                material_texture_slots=material_texture_slots,
                material_flags=material_flags,
                material_preview_parameters=material_preview_parameters,
            )
            submeshes.append(copied)
            if uv_plan is not None and uv_inputs is not None:
                uv_records.append(GltfUvPrimitiveRecord(material_index, len(submeshes) - 1, primitive_label, uv_inputs))
            flags = material_flags.get(material_index, {})
            bindings.append(
                ImportedMaterialBinding(
                    material_index=material_index,
                    material_name=material_name or copied.material,
                    submesh_index=len(submeshes) - 1,
                    submesh_name=copied.name,
                    texture_slots=tuple(
                        (str(slot_kind), Path(str(slot.path)).expanduser())
                        for slot_kind, slot in sorted(material_texture_slots.get(material_index, {}).items())
                        if isinstance(slot, SceneMaterialTextureSlot) and str(slot.path or "").strip()
                    ),
                    pbr_workflow=str(material_workflows.get(material_index, "") or ""),
                    alpha_mode=str(flags.get("alpha_mode", "") or ""),
                    double_sided=bool(flags.get("double_sided", False)),
                )
            )
    return submeshes, bindings, uv_records, baked_skin_count


def _apply_general_gltf_bake(
    mesh: ParsedMesh,
    payload: _GltfPayload,
    material_info: _GltfMaterialInfo,
    records: Sequence[GltfUvPrimitiveRecord],
    bindings: Sequence[ImportedMaterialBinding],
    source_path: Path,
    stop_event: threading.Event | None,
) -> GltfGeneralUvBakeOutcome:
    _names, _textures, colors, slots_by_material, _workflows, flags, preview_parameters = material_info
    outcome = bake_general_gltf_uvs(
        mesh, payload.material_uv_plans, records, slots_by_material, source_path, stop_event=stop_event
    )
    payload.discovered_texture_files.extend(outcome.generated_paths)
    for material_index in outcome.material_reports:
        slots = slots_by_material.get(material_index, {})
        for record in records:
            if record.material_index != material_index:
                continue
            mesh.submeshes[record.submesh_index].preview_normal_texture_strength = 1.0
            _apply_gltf_preview_material_metadata(
                mesh.submeshes[record.submesh_index],
                material_index,
                material_colors=colors,
                material_texture_slots=slots_by_material,
                material_flags=flags,
                material_preview_parameters=preview_parameters,
            )
        binding_slots = tuple(
            (str(slot_kind), Path(str(slot.path)).expanduser())
            for slot_kind, slot in sorted(slots.items())
            if str(slot.path or "").strip()
        )
        for binding in bindings:
            if binding.material_index == material_index:
                binding.texture_slots = binding_slots
    if outcome.generated_paths:
        vertices = [vertex for submesh in mesh.submeshes for vertex in submesh.vertices]
        mesh.bbox_min, mesh.bbox_max = _bbox(vertices)
        mesh.total_vertices = sum(len(submesh.vertices) for submesh in mesh.submeshes)
        mesh.total_faces = sum(len(submesh.faces) for submesh in mesh.submeshes)
        mesh.has_uvs = any(len(submesh.uvs) == len(submesh.vertices) for submesh in mesh.submeshes)
    return outcome


def import_gltf(
    path: str | Path,
    *,
    include_external_audit: bool = True,
    tolerate_missing_texture_files: bool = False,
    stop_event: threading.Event | None = None,
) -> SceneImportResult:
    from .scene_importer import SceneImportResult

    source_path = Path(path).expanduser().resolve()
    raise_if_cancelled(stop_event, "glTF import cancelled before source parsing.")
    payload = _load_gltf_payload(
        source_path,
        tolerate_missing_texture_files=tolerate_missing_texture_files,
    )
    _validate_gltf_static_payload(payload)
    (
        material_names,
        material_textures,
        material_colors,
        material_texture_slots,
        material_workflows,
        material_flags,
        material_preview_parameters,
    ) = _gltf_material_info(payload)
    material_info = (
        material_names,
        material_textures,
        material_colors,
        material_texture_slots,
        material_workflows,
        material_flags,
        material_preview_parameters,
    )
    submeshes, material_bindings, primitive_uv_records, baked_skin_primitive_count = _collect_gltf_geometry(
        payload, material_info, stop_event
    )
    if not submeshes:
        raise ValueError(f"glTF import did not contain supported uncompressed triangle geometry: {source_path}")
    vertices = [vertex for submesh in submeshes for vertex in submesh.vertices]
    bbox_min, bbox_max = _bbox(vertices)
    mesh = ParsedMesh(
        path=str(source_path),
        format=payload.format_name,
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        submeshes=submeshes,
        total_vertices=sum(len(submesh.vertices) for submesh in submeshes),
        total_faces=sum(len(submesh.faces) for submesh in submeshes),
        has_uvs=any(submesh.uvs for submesh in submeshes),
        has_bones=False,
    )
    general_bake = _apply_general_gltf_bake(
        mesh,
        payload,
        material_info,
        primitive_uv_records,
        material_bindings,
        source_path,
        stop_event,
    )
    if payload.extracted_embedded_files:
        payload.diagnostics.append(
            f"Extracted {len(payload.extracted_embedded_files):,} embedded glTF texture file(s) for supplemental import."
        )
    if payload.discovered_texture_files:
        payload.diagnostics.append(
            f"Discovered {len(payload.discovered_texture_files):,} glTF texture reference(s)."
        )
    if baked_skin_primitive_count:
        payload.diagnostics.append(
            f"Baked glTF skin weights into static geometry for {baked_skin_primitive_count:,} primitive(s)."
        )
    return _result_with_external_audit(
        source_path,
        SceneImportResult(
            mesh=mesh,
            diagnostics=tuple(_dedupe_text(payload.diagnostics)),
            discovered_texture_files=tuple(_dedupe_paths(payload.discovered_texture_files)),
            extracted_embedded_files=tuple(_dedupe_paths(payload.extracted_embedded_files)),
            material_bindings=tuple(material_bindings),
            uv_bake_report=build_gltf_uv_bake_report(
                tuple(payload.material_uv_plans.values()),
                general_bake.material_reports,
            ),
        ),
        enabled=include_external_audit,
    )


def _load_gltf_payload(
    source_path: Path,
    *,
    tolerate_missing_texture_files: bool = False,
) -> _GltfPayload:
    diagnostics: list[str] = []
    extracted_embedded_files: list[Path] = []
    discovered_texture_files: list[Path] = []
    suffix = source_path.suffix.lower()
    if suffix == ".glb":
        document, bin_chunk = _read_glb(source_path)
        format_name = "glb"
    else:
        try:
            document = json.loads(source_path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            document = json.loads(source_path.read_text(encoding="utf-8-sig"))
        bin_chunk = b""
        format_name = "gltf"
    if not isinstance(document, dict):
        raise ValueError(f"glTF document is not a JSON object: {source_path}")
    asset = document.get("asset", {})
    version = str(asset.get("version", "") if isinstance(asset, dict) else "")
    if version and not version.startswith("2."):
        diagnostics.append(f"glTF asset version is {version}; importer is written for glTF 2.0.")
    buffers: list[bytes] = []
    for index, buffer_entry in enumerate(document.get("buffers", []) or []):
        if not isinstance(buffer_entry, dict):
            buffers.append(b"")
            continue
        uri = str(buffer_entry.get("uri", "") or "")
        if suffix == ".glb" and index == 0 and not uri:
            buffers.append(bin_chunk)
        elif uri.startswith("data:"):
            buffers.append(_decode_data_uri(uri))
        elif uri:
            buffer_path = _resolve_scene_uri(source_path.parent, uri)
            buffers.append(buffer_path.read_bytes())
        else:
            buffers.append(b"")
    return _GltfPayload(
        document=document,
        buffers=buffers,
        source_path=source_path,
        format_name=format_name,
        diagnostics=diagnostics,
        extracted_embedded_files=extracted_embedded_files,
        discovered_texture_files=discovered_texture_files,
        tolerate_missing_texture_files=bool(tolerate_missing_texture_files),
        material_uv_plans={},
    )


def _read_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    if len(data) < 20:
        raise ValueError(f"GLB file is too small: {path}")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise ValueError(f"Invalid GLB header: {path}")
    if version != 2:
        raise ValueError(f"Unsupported GLB version {version}; export as GLB 2.0.")
    cursor = 12
    document: dict[str, Any] | None = None
    bin_chunk = b""
    while cursor + 8 <= min(length, len(data)):
        chunk_length, chunk_type = struct.unpack_from("<II", data, cursor)
        cursor += 8
        chunk_data = data[cursor : cursor + chunk_length]
        cursor += chunk_length
        if chunk_type == 0x4E4F534A:
            document = json.loads(chunk_data.rstrip(b"\x00 ").decode("utf-8"))
        elif chunk_type == 0x004E4942:
            bin_chunk = bytes(chunk_data)
    if document is None:
        raise ValueError(f"GLB file does not contain a JSON chunk: {path}")
    return document, bin_chunk


def _validate_gltf_static_payload(payload: _GltfPayload) -> None:
    doc = payload.document
    used_extensions = set(doc.get("extensionsUsed", []) or []) | set(doc.get("extensionsRequired", []) or [])
    compressed = sorted(ext for ext in used_extensions if ext in {"KHR_draco_mesh_compression", "EXT_meshopt_compression"})
    if compressed:
        raise ValueError(
            "This glTF/GLB uses compressed mesh data "
            f"({', '.join(compressed)}). Export an uncompressed GLB/glTF before importing."
        )
    if doc.get("skins"):
        payload.diagnostics.append("glTF skins/bones are baked into static geometry when possible; Mesh Replacement remains static.")
    if doc.get("animations"):
        payload.diagnostics.append("glTF animations are ignored; import will use static Mesh Replacement only.")
    warned_morphs = False
    for mesh in doc.get("meshes", []) or []:
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives", []) or []:
            if isinstance(primitive, dict) and primitive.get("targets") and not warned_morphs:
                payload.diagnostics.append("glTF morph targets are ignored for static Mesh Replacement.")
                warned_morphs = True


def _gltf_texture_info_parameters(
    slot_kind: str,
    texture_info: object,
    *,
    normalize_uv: bool = False,
) -> tuple[PreviewMaterialParameterInput, ...]:
    slot_key = re.sub(r"[^A-Za-z0-9_]+", "_", str(slot_kind or "").strip()) or "texture"
    parameters: list[PreviewMaterialParameterInput] = []
    if not normalize_uv:
        texcoord = _gltf_texture_info_texcoord(texture_info)
        if texcoord > 0:
            _append_scene_parameter(parameters, _scene_preview_float_parameter(f"_gltfTexCoord_{slot_key}", texcoord))
        transform = _gltf_texture_transform(texture_info)
        if transform:
            parameters.append(
                PreviewMaterialParameterInput(
                    parameter_kind="string",
                    parameter_name=f"_gltfTextureTransform_{slot_key}",
                    value=",".join(f"{value:.6f}" for value in transform),
                )
            )
    if isinstance(texture_info, Mapping) and "scale" in texture_info:
        _append_scene_parameter(parameters, _scene_preview_float_parameter(f"_gltfTextureScale_{slot_key}", texture_info.get("scale")))
    if isinstance(texture_info, Mapping) and "strength" in texture_info:
        _append_scene_parameter(parameters, _scene_preview_float_parameter(f"_gltfTextureStrength_{slot_key}", texture_info.get("strength")))
    return tuple(parameters)


def _gltf_material_texcoord_index(
    material_texture_slots: Mapping[int, Mapping[str, SceneMaterialTextureSlot]],
    material_index: int,
) -> int:
    slots = tuple((material_texture_slots.get(material_index, {}) or {}).values())
    texcoords = [int(slot.texcoord) for slot in slots if isinstance(slot, SceneMaterialTextureSlot) and int(slot.texcoord) > 0]
    if not texcoords:
        return 0
    return min(texcoords)


def _gltf_scene_material_slot(
    payload: _GltfPayload,
    textures: list[object],
    images: list[object],
    slot_kind: str,
    texture_info: object,
    *,
    parameter_name: str = "",
    source: str = "gltf",
    normalize_uv: bool = False,
) -> Optional[SceneMaterialTextureSlot]:
    image_path = _gltf_texture_image_path(payload, textures, images, texture_info)
    if image_path is None:
        return None
    suffix = image_path.suffix.lower()
    if suffix in SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS or suffix not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
        raise ValueError(
            f"glTF {slot_kind} texture uses unsupported image format {suffix or '<none>'}. "
            "Convert it to PNG, JPEG, WebP, TGA, BMP, TIFF, or DDS and export the glTF again."
        )
    source_texcoord = _gltf_texture_info_texcoord(texture_info)
    if source_texcoord > 0:
        action = "import reads it before runtime TEXCOORD_0 normalization" if normalize_uv else "preview selects that UV set when present"
        payload.diagnostics.append(f"glTF {slot_kind} texture requests TEXCOORD_{source_texcoord}; {action}.")
    return _scene_material_slot(
        slot_kind,
        image_path.as_posix(),
        parameter_name=parameter_name,
        texcoord=0 if normalize_uv else source_texcoord,
        transform=() if normalize_uv else _gltf_texture_transform(texture_info),
        source=source,
        parameters=_gltf_texture_info_parameters(slot_kind, texture_info, normalize_uv=normalize_uv),
    )


def _record_gltf_material_uv_plan(
    payload: _GltfPayload,
    material_index: int,
    material_name: str,
    texture_infos: Sequence[tuple[str, str, object, str]],
) -> GltfMaterialUvPlan:
    plan = build_gltf_material_uv_plan(
        payload.document,
        material_index,
        material_name,
        texture_infos,
    )
    payload.material_uv_plans[material_index] = plan
    if plan.requires_raster_bake:
        payload.diagnostics.append(
            f"Raster-baking glTF material {plan.material_name} slots into one xatlas TEXCOORD_0 layout."
        )
    elif plan.bakes_transform:
        payload.diagnostics.append(
            f"Baked glTF material {plan.material_name} shared KHR_texture_transform from "
            f"TEXCOORD_{plan.source_texcoord} into runtime TEXCOORD_0."
        )
    elif plan.slots and plan.source_texcoord > 0:
        payload.diagnostics.append(
            f"Normalized glTF material {plan.material_name} TEXCOORD_{plan.source_texcoord} into runtime TEXCOORD_0."
        )
    return plan


def _gltf_material_info(payload: _GltfPayload) -> _GltfMaterialInfo:
    material_names: dict[int, str] = {}
    material_textures: dict[int, str] = {}
    material_colors: dict[int, tuple[float, float, float]] = {}
    material_texture_slots: dict[int, dict[str, SceneMaterialTextureSlot]] = {}
    material_workflows: dict[int, str] = {}
    material_flags: dict[int, dict[str, object]] = {}
    material_preview_parameters: dict[int, tuple[PreviewMaterialParameterInput, ...]] = {}
    textures = payload.document.get("textures", []) or []
    images = payload.document.get("images", []) or []
    payload.material_uv_plans.clear()
    for material_index, material in enumerate(payload.document.get("materials", []) or []):
        if not isinstance(material, dict):
            continue
        material_names[material_index] = str(material.get("name", "") or f"material_{material_index}")
        material_flags[material_index] = {
            "alpha_mode": str(material.get("alphaMode", "") or ""),
            "double_sided": bool(material.get("doubleSided", False)),
            "unlit": False,
        }
        preview_parameters: list[PreviewMaterialParameterInput] = []
        alpha_mode = str(material.get("alphaMode", "") or "").strip()
        if alpha_mode:
            preview_parameters.append(
                PreviewMaterialParameterInput(
                    parameter_kind="string",
                    parameter_name="_gltfAlphaMode",
                    value=alpha_mode,
                )
            )
        if "alphaCutoff" in material:
            _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_gltfAlphaCutoff", material.get("alphaCutoff")))
        if bool(material.get("doubleSided", False)):
            preview_parameters.append(
                PreviewMaterialParameterInput(
                    parameter_kind="bool",
                    parameter_name="_gltfDoubleSided",
                    value="true",
                    numeric_value=1.0,
                )
            )
        pbr = material.get("pbrMetallicRoughness", {})
        material_slots: dict[str, SceneMaterialTextureSlot] = {}
        texture_infos: list[tuple[str, str, object, str]] = []
        if isinstance(pbr, dict):
            material_workflows[material_index] = "metallicRoughness"
            base_color_factor = pbr.get("baseColorFactor")
            if isinstance(base_color_factor, Sequence) and len(base_color_factor) >= 3:
                color_values: list[float] = []
                for value in base_color_factor[:3]:
                    try:
                        color_values.append(max(0.0, min(1.0, float(value))))
                    except (TypeError, ValueError, OverflowError):
                        color_values.append(1.0)
                material_colors[material_index] = (color_values[0], color_values[1], color_values[2])
            else:
                material_colors[material_index] = (1.0, 1.0, 1.0)
            _append_scene_parameter(preview_parameters, _scene_preview_color_parameter("_baseColorFactor", pbr.get("baseColorFactor")))
            texture_infos.append(("base", "base", pbr.get("baseColorTexture"), "_baseColorTexture"))
            texture_infos.append(("material", "material", pbr.get("metallicRoughnessTexture"), "_metallicRoughnessTexture"))
            for key, parameter_name in (
                ("metallicFactor", "_metallicFactor"),
                ("roughnessFactor", "_roughnessFactor"),
            ):
                if key in pbr:
                    _append_scene_parameter(preview_parameters, _scene_preview_float_parameter(parameter_name, pbr.get(key)))
        else:
            material_colors[material_index] = (1.0, 1.0, 1.0)
        extensions = material.get("extensions", {})
        specular_gloss = (
            extensions.get("KHR_materials_pbrSpecularGlossiness")
            if isinstance(extensions, dict)
            else None
        )
        if isinstance(specular_gloss, dict):
            material_workflows[material_index] = "specularGlossiness"
            diffuse_factor = specular_gloss.get("diffuseFactor")
            if isinstance(diffuse_factor, Sequence) and len(diffuse_factor) >= 3:
                color_values = []
                for value in diffuse_factor[:3]:
                    try:
                        color_values.append(max(0.0, min(1.0, float(value))))
                    except (TypeError, ValueError, OverflowError):
                        color_values.append(1.0)
                material_colors[material_index] = (color_values[0], color_values[1], color_values[2])
            _append_scene_parameter(preview_parameters, _scene_preview_color_parameter("_diffuseFactor", specular_gloss.get("diffuseFactor")))
            _append_scene_parameter(preview_parameters, _scene_preview_color_parameter("_specularFactor", specular_gloss.get("specularFactor")))
            _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_glossinessFactor", specular_gloss.get("glossinessFactor", 1.0)))
            texture_infos.append(("base", "base", specular_gloss.get("diffuseTexture"), "_diffuseTexture"))
            texture_infos.append(("specular_glossiness", "specular_glossiness", specular_gloss.get("specularGlossinessTexture"), "_specularGlossinessTexture"))
        texture_infos.extend(
            (
                ("normal", "normal", material.get("normalTexture"), "_normalTexture"),
                ("occlusion", "occlusion", material.get("occlusionTexture"), "_occlusionTexture"),
                ("emissive", "emissive", material.get("emissiveTexture"), "_emissiveTexture"),
            )
        )
        emissive_factor = material.get("emissiveFactor")
        emissive_factor_active = False
        if isinstance(emissive_factor, Sequence) and len(emissive_factor) >= 3:
            try:
                rgb = tuple(max(0.0, min(1.0, float(value))) for value in emissive_factor[:3])
            except (TypeError, ValueError, OverflowError):
                rgb = ()
            if rgb:
                emissive_factor_active = any(component > 1e-6 for component in rgb)
                preview_parameters.append(
                    PreviewMaterialParameterInput(
                        parameter_kind="color",
                        parameter_name="_emissiveColor",
                        value="#" + "".join(f"{int(round(component * 255)):02x}" for component in rgb),
                        color_value=rgb,
                    )
                )
        emissive_strength = 0.0
        emissive_extension = (
            extensions.get("KHR_materials_emissive_strength")
            if isinstance(extensions, dict)
            else None
        )
        if isinstance(emissive_extension, dict):
            try:
                emissive_strength = max(0.0, float(emissive_extension.get("emissiveStrength", 0.0)))
            except (TypeError, ValueError, OverflowError):
                emissive_strength = 0.0
        if emissive_strength <= 0.0 and emissive_factor_active:
            emissive_strength = 1.0
        if emissive_strength <= 0.0 and material.get("emissiveTexture") is not None:
            emissive_strength = 1.0
        if emissive_strength > 0.0:
            preview_parameters.append(
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_emissiveIntensity",
                    value=f"{emissive_strength:.6f}",
                    numeric_value=emissive_strength,
                )
            )
        if isinstance(extensions, dict):
            if isinstance(extensions.get("KHR_materials_unlit"), dict):
                material_flags[material_index]["unlit"] = True
                material_workflows[material_index] = "unlit"
                preview_parameters.append(
                    PreviewMaterialParameterInput(
                        parameter_kind="bool",
                        parameter_name="_gltfUnlit",
                        value="true",
                        numeric_value=1.0,
                    )
                )
                payload.diagnostics.append(
                    f"glTF material {material_names[material_index]} uses KHR_materials_unlit; preview uses flat non-PBR approximation."
                )
            specular_ext = extensions.get("KHR_materials_specular")
            if isinstance(specular_ext, dict):
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_specularFactor", specular_ext.get("specularFactor", 1.0)))
                _append_scene_parameter(preview_parameters, _scene_preview_color_parameter("_specularColorFactor", specular_ext.get("specularColorFactor", (1.0, 1.0, 1.0))))
                texture_infos.append(("specular", "specular", specular_ext.get("specularTexture"), "_specularTexture"))
                texture_infos.append(("specular_color", "specular", specular_ext.get("specularColorTexture"), "_specularColorTexture"))
            clearcoat_ext = extensions.get("KHR_materials_clearcoat")
            if isinstance(clearcoat_ext, dict):
                payload.diagnostics.append(
                    f"glTF material {material_names[material_index]} uses KHR_materials_clearcoat; preview approximates it as stronger specular response."
                )
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_clearcoatFactor", clearcoat_ext.get("clearcoatFactor", 0.0)))
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_clearcoatRoughnessFactor", clearcoat_ext.get("clearcoatRoughnessFactor", 0.0)))
                texture_infos.append(("clearcoat", "clearcoat", clearcoat_ext.get("clearcoatTexture"), "_clearcoatTexture"))
                texture_infos.append(("clearcoat_roughness", "clearcoat_roughness", clearcoat_ext.get("clearcoatRoughnessTexture"), "_clearcoatRoughnessTexture"))
                texture_infos.append(("clearcoat_normal", "clearcoat_normal", clearcoat_ext.get("clearcoatNormalTexture"), "_clearcoatNormalTexture"))
            sheen_ext = extensions.get("KHR_materials_sheen")
            if isinstance(sheen_ext, dict):
                payload.diagnostics.append(
                    f"glTF material {material_names[material_index]} uses KHR_materials_sheen; preview approximates it as soft specular response."
                )
                _append_scene_parameter(preview_parameters, _scene_preview_color_parameter("_sheenColorFactor", sheen_ext.get("sheenColorFactor", (0.0, 0.0, 0.0))))
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_sheenRoughnessFactor", sheen_ext.get("sheenRoughnessFactor", 0.0)))
                texture_infos.append(("sheen", "sheen", sheen_ext.get("sheenColorTexture"), "_sheenColorTexture"))
                texture_infos.append(("sheen_roughness", "sheen_roughness", sheen_ext.get("sheenRoughnessTexture"), "_sheenRoughnessTexture"))
            transmission_ext = extensions.get("KHR_materials_transmission")
            if isinstance(transmission_ext, dict):
                payload.diagnostics.append(
                    f"glTF material {material_names[material_index]} uses KHR_materials_transmission; preview records it but does not render true glass."
                )
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_transmissionFactor", transmission_ext.get("transmissionFactor", 0.0)))
                texture_infos.append(("transmission", "transmission", transmission_ext.get("transmissionTexture"), "_transmissionTexture"))
            volume_ext = extensions.get("KHR_materials_volume")
            if isinstance(volume_ext, dict):
                payload.diagnostics.append(
                    f"glTF material {material_names[material_index]} uses KHR_materials_volume; preview records attenuation/thickness only."
                )
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_thicknessFactor", volume_ext.get("thicknessFactor", 0.0)))
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_attenuationDistance", volume_ext.get("attenuationDistance", 0.0)))
                _append_scene_parameter(preview_parameters, _scene_preview_color_parameter("_attenuationColor", volume_ext.get("attenuationColor", (1.0, 1.0, 1.0))))
                texture_infos.append(("volume", "volume", volume_ext.get("thicknessTexture"), "_thicknessTexture"))
            ior_ext = extensions.get("KHR_materials_ior")
            if isinstance(ior_ext, dict):
                payload.diagnostics.append(
                    f"glTF material {material_names[material_index]} uses KHR_materials_ior; preview records IOR as a specular hint."
                )
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_ior", ior_ext.get("ior", 1.5)))
            anisotropy_ext = extensions.get("KHR_materials_anisotropy")
            if isinstance(anisotropy_ext, dict):
                payload.diagnostics.append(
                    f"glTF material {material_names[material_index]} uses KHR_materials_anisotropy; preview records it as diagnostic-only."
                )
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_anisotropyStrength", anisotropy_ext.get("anisotropyStrength", 0.0)))
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_anisotropyRotation", anisotropy_ext.get("anisotropyRotation", 0.0)))
                texture_infos.append(("anisotropy", "anisotropy", anisotropy_ext.get("anisotropyTexture"), "_anisotropyTexture"))
            iridescence_ext = extensions.get("KHR_materials_iridescence")
            if isinstance(iridescence_ext, dict):
                payload.diagnostics.append(
                    f"glTF material {material_names[material_index]} uses KHR_materials_iridescence; preview records it as diagnostic-only."
                )
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_iridescenceFactor", iridescence_ext.get("iridescenceFactor", 0.0)))
                _append_scene_parameter(preview_parameters, _scene_preview_float_parameter("_iridescenceIor", iridescence_ext.get("iridescenceIor", 1.3)))
                texture_infos.append(("iridescence", "iridescence", iridescence_ext.get("iridescenceTexture"), "_iridescenceTexture"))
        uv_plan = _record_gltf_material_uv_plan(
            payload, material_index, material_names[material_index], texture_infos
        )
        for slot_key, slot_kind, texture_info, parameter_name in texture_infos:
            slot = _gltf_scene_material_slot(
                payload,
                textures,
                images,
                slot_kind,
                texture_info,
                parameter_name=parameter_name,
                normalize_uv=bool(uv_plan.slots),
            )
            if slot is None:
                continue
            material_slots[slot_key] = slot
            if slot_key == "base":
                material_textures[material_index] = slot.path
            texture_path = Path(slot.path)
            if texture_path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                payload.discovered_texture_files.append(texture_path)
        missing_slots = sorted({slot.slot_key for slot in uv_plan.slots} - set(material_slots))
        if missing_slots:
            raise ValueError(
                f"glTF material {uv_plan.material_name} failed material-slot resolution for {', '.join(missing_slots)}. "
                "Re-export every referenced slot with one valid core texture source and decodable image."
            )
        if material_slots:
            material_texture_slots[material_index] = material_slots
        if preview_parameters:
            material_preview_parameters[material_index] = tuple(preview_parameters)
    return (
        material_names,
        material_textures,
        material_colors,
        material_texture_slots,
        material_workflows,
        material_flags,
        material_preview_parameters,
    )


def _apply_gltf_preview_material_metadata(
    submesh: SubMesh,
    material_index: int,
    *,
    material_colors: Mapping[int, tuple[float, float, float]],
    material_texture_slots: Mapping[int, Mapping[str, SceneMaterialTextureSlot]],
    material_flags: Mapping[int, Mapping[str, object]] = {},
    material_preview_parameters: Mapping[int, tuple[PreviewMaterialParameterInput, ...]] = {},
) -> None:
    if material_index < 0:
        return
    flags = material_flags.get(material_index, {})
    alpha_mode = str(flags.get("alpha_mode", "") or "").strip()
    if alpha_mode:
        submesh.preview_alpha_mode = alpha_mode
    if bool(flags.get("double_sided", False)):
        submesh.preview_double_sided = True
    color = material_colors.get(material_index)
    if color is not None:
        submesh.preview_color = tuple(float(component) for component in color[:3])
    slots = material_texture_slots.get(material_index, {})
    preview_parameters = tuple(material_preview_parameters.get(material_index, ()) or ())
    if preview_parameters:
        submesh.preview_material_parameters = preview_parameters
    _apply_scene_material_slots_to_submesh(
        submesh,
        tuple(slots.values()),
        material_parameters=preview_parameters,
        confidence="gltf",
    )


def _gltf_texture_image_path(
    payload: _GltfPayload,
    textures: list[object],
    images: list[object],
    texture_info: object,
) -> Optional[Path]:
    if not isinstance(texture_info, dict):
        return None
    texture_index = _safe_int(texture_info.get("index"), -1)
    if texture_index < 0 or texture_index >= len(textures) or not isinstance(textures[texture_index], dict):
        return None
    image_index = _safe_int(textures[texture_index].get("source"), -1)
    if image_index < 0 or image_index >= len(images) or not isinstance(images[image_index], dict):
        return None
    return _resolve_gltf_image(payload, images[image_index], image_index)


def _resolve_gltf_image(payload: _GltfPayload, image: dict[str, Any], image_index: int) -> Optional[Path]:
    uri = str(image.get("uri", "") or "")
    if uri:
        if uri.startswith("data:"):
            try:
                mime_type, data = _decode_data_uri_with_mime(uri)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"glTF image {image_index} has an invalid data URI; embed a valid supported image.") from exc
            return _write_embedded_gltf_image(payload, image_index, data, mime_type)
        image_path = _resolve_scene_uri(payload.source_path.parent, uri)
        if not image_path.is_file():
            if payload.tolerate_missing_texture_files:
                payload.diagnostics.append(
                    f"glTF image {image_index} is missing at {image_path}; audit retained the unresolved reference."
                )
                return image_path.resolve()
            raise ValueError(
                f"glTF image {image_index} is missing at {image_path}. Restore that file or embed it, then export again."
            )
        _validate_gltf_image_payload(image_path, image_index, image_path.suffix)
        return image_path.resolve()
    buffer_view_index = _safe_int(image.get("bufferView"), -1)
    if buffer_view_index >= 0:
        view = _gltf_buffer_view(payload, buffer_view_index)
        buffer_index = view.get("buffer")
        offset, length = view.get("byteOffset", 0), view.get("byteLength")
        if (
            isinstance(buffer_index, bool) or not isinstance(buffer_index, int) or not 0 <= buffer_index < len(payload.buffers)
            or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
            or isinstance(length, bool) or not isinstance(length, int) or length <= 0
            or offset + length > len(payload.buffers[buffer_index])
        ):
            raise ValueError(
                f"glTF image {image_index} has invalid bufferView {buffer_view_index} bounds. "
                "Embed one complete supported image payload and export again."
            )
        image_bytes = payload.buffers[buffer_index][offset : offset + length]
        mime_type = str(image.get("mimeType", "") or "")
        return _write_embedded_gltf_image(payload, image_index, image_bytes, mime_type)
    return None


def _write_embedded_gltf_image(payload: _GltfPayload, image_index: int, data: bytes, mime_type: str) -> Path:
    return write_embedded_gltf_image(payload, image_index, data, mime_type, SCENE_TEXTURE_SOURCE_EXTENSIONS)


def _iter_gltf_mesh_instances(document: dict[str, Any]) -> list[_GltfMeshInstance]:
    scenes = document.get("scenes", []) or []
    scene_index = _safe_int(document.get("scene"), 0)
    root_nodes: list[int] = []
    if 0 <= scene_index < len(scenes) and isinstance(scenes[scene_index], dict):
        root_nodes = [_safe_int(value, -1) for value in scenes[scene_index].get("nodes", []) or []]
    if not root_nodes:
        root_nodes = list(range(len(document.get("nodes", []) or [])))
    instances: list[_GltfMeshInstance] = []
    for node_index in root_nodes:
        _walk_gltf_node(document, node_index, _identity_matrix(), instances)
    return instances


def _walk_gltf_node(
    document: dict[str, Any],
    node_index: int,
    parent_matrix: tuple[float, ...],
    instances: list[_GltfMeshInstance],
) -> None:
    nodes = document.get("nodes", []) or []
    if node_index < 0 or node_index >= len(nodes) or not isinstance(nodes[node_index], dict):
        return
    node = nodes[node_index]
    matrix = _multiply_matrix(parent_matrix, _gltf_node_matrix(node))
    mesh_index = _safe_int(node.get("mesh"), -1)
    node_name = str(node.get("name", "") or "")
    if mesh_index >= 0:
        instances.append(
            _GltfMeshInstance(
                mesh_index=mesh_index,
                transform=matrix,
                node_name=node_name,
                node_index=node_index,
                skin_index=_safe_int(node.get("skin"), -1),
            )
        )
    for child_index in node.get("children", []) or []:
        _walk_gltf_node(document, _safe_int(child_index, -1), matrix, instances)


def _gltf_node_world_matrices(document: dict[str, Any]) -> tuple[tuple[float, ...], ...]:
    nodes = document.get("nodes", []) or []
    parents = [-1] * len(nodes)
    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        for child in node.get("children", []) or []:
            child_index = _safe_int(child, -1)
            if 0 <= child_index < len(parents):
                parents[child_index] = node_index
    local_matrices = [
        _gltf_node_matrix(node if isinstance(node, dict) else {})
        for node in nodes
    ]
    cache: list[Optional[tuple[float, ...]]] = [None] * len(nodes)

    def resolve(node_index: int, stack: set[int]) -> tuple[float, ...]:
        if node_index < 0 or node_index >= len(nodes):
            return _identity_matrix()
        cached = cache[node_index]
        if cached is not None:
            return cached
        if node_index in stack:
            return _identity_matrix()
        parent_index = parents[node_index]
        if parent_index >= 0:
            matrix = _multiply_matrix(resolve(parent_index, stack | {node_index}), local_matrices[node_index])
        else:
            matrix = local_matrices[node_index]
        cache[node_index] = matrix
        return matrix

    return tuple(resolve(index, set()) for index in range(len(nodes)))


def _gltf_skin_joint_matrices(
    payload: _GltfPayload,
    *,
    node_index: int,
    skin_index: int,
) -> tuple[tuple[float, ...], ...]:
    skins = payload.document.get("skins", []) or []
    if skin_index < 0 or skin_index >= len(skins) or not isinstance(skins[skin_index], dict):
        return ()
    world_matrices = _gltf_node_world_matrices(payload.document)
    if node_index < 0 or node_index >= len(world_matrices):
        return ()
    node_inverse = _invert_affine_matrix(world_matrices[node_index])
    if node_inverse is None:
        payload.diagnostics.append("Skipped glTF skin bake because the skinned mesh node transform is not invertible.")
        return ()
    skin = skins[skin_index]
    joints = [_safe_int(value, -1) for value in skin.get("joints", []) or []]
    if not joints:
        return ()
    inverse_bind_matrices = _gltf_inverse_bind_matrices(
        payload,
        accessor_index=_safe_int(skin.get("inverseBindMatrices"), -1),
        joint_count=len(joints),
    )
    matrices: list[tuple[float, ...]] = []
    for joint_position, joint_index in enumerate(joints):
        if 0 <= joint_index < len(world_matrices):
            joint_world = world_matrices[joint_index]
        else:
            joint_world = _identity_matrix()
        inverse_bind = inverse_bind_matrices[joint_position] if joint_position < len(inverse_bind_matrices) else _identity_matrix()
        matrices.append(_multiply_matrix(_multiply_matrix(node_inverse, joint_world), inverse_bind))
    return tuple(matrices)


def _gltf_inverse_bind_matrices(
    payload: _GltfPayload,
    *,
    accessor_index: int,
    joint_count: int,
) -> tuple[tuple[float, ...], ...]:
    if accessor_index < 0:
        return tuple(_identity_matrix() for _index in range(joint_count))
    rows = _read_gltf_accessor(payload, accessor_index, expected_components=16)
    matrices = [_gltf_mat4_to_row_major(row) for row in rows[:joint_count]]
    while len(matrices) < joint_count:
        matrices.append(_identity_matrix())
    return tuple(matrices)


def _gltf_mat4_to_row_major(values: tuple[float, ...]) -> tuple[float, ...]:
    if len(values) < 16:
        return _identity_matrix()
    return (
        float(values[0]), float(values[4]), float(values[8]), float(values[12]),
        float(values[1]), float(values[5]), float(values[9]), float(values[13]),
        float(values[2]), float(values[6]), float(values[10]), float(values[14]),
        float(values[3]), float(values[7]), float(values[11]), float(values[15]),
    )


def _bake_gltf_skin_primitive(
    payload: _GltfPayload,
    primitive: dict[str, Any],
    submesh: SubMesh,
    skin_matrices: Sequence[tuple[float, ...]],
) -> bool:
    attributes = primitive.get("attributes", {})
    if not isinstance(attributes, dict):
        return False
    joints_accessor = _safe_int(attributes.get("JOINTS_0"), -1)
    weights_accessor = _safe_int(attributes.get("WEIGHTS_0"), -1)
    if joints_accessor < 0 or weights_accessor < 0:
        return False
    joints = _read_gltf_accessor(payload, joints_accessor, expected_components=4)
    weights = _read_gltf_accessor(payload, weights_accessor, expected_components=4)
    if not joints or not weights:
        return False
    vertices = list(submesh.vertices)
    normals = list(submesh.normals)
    if len(joints) != len(vertices) or len(weights) != len(vertices):
        raise ValueError("glTF JOINTS_0/WEIGHTS_0 contain invalid skin rows; export one complete skin row per vertex.")
    for vertex_index, weight_values in enumerate(weights):
        weight_sum = sum(max(0.0, float(weight)) for weight in weight_values)
        if not weight_sum > 1e-8:
            raise ValueError(
                f"glTF WEIGHTS_0 contains an invalid zero-sum skin row at vertex {vertex_index}; "
                "export normalized non-zero weights for every skinned vertex."
            )
    baked_vertices: list[tuple[float, float, float]] = []
    baked_normals: list[tuple[float, float, float]] = []
    for vertex_index, vertex in enumerate(vertices):
        joint_values = joints[vertex_index]
        weight_values = weights[vertex_index]
        weight_sum = sum(max(0.0, float(weight)) for weight in weight_values)
        position_accumulator = [0.0, 0.0, 0.0]
        normal_accumulator = [0.0, 0.0, 0.0]
        has_normal = vertex_index < len(normals)
        for joint_value, raw_weight in zip(joint_values, weight_values):
            weight = max(0.0, float(raw_weight)) / weight_sum
            if weight <= 0.0:
                continue
            joint_index = int(joint_value)
            matrix = skin_matrices[joint_index] if 0 <= joint_index < len(skin_matrices) else _identity_matrix()
            transformed = _transform_point(tuple(float(component) for component in vertex[:3]), matrix)
            position_accumulator[0] += transformed[0] * weight
            position_accumulator[1] += transformed[1] * weight
            position_accumulator[2] += transformed[2] * weight
            if has_normal:
                transformed_normal = _transform_vector(tuple(float(component) for component in normals[vertex_index][:3]), matrix)
                normal_accumulator[0] += transformed_normal[0] * weight
                normal_accumulator[1] += transformed_normal[1] * weight
                normal_accumulator[2] += transformed_normal[2] * weight
        baked_vertices.append((position_accumulator[0], position_accumulator[1], position_accumulator[2]))
        if has_normal:
            baked_normals.append(_normalize_vec((normal_accumulator[0], normal_accumulator[1], normal_accumulator[2])))
    submesh.vertices = baked_vertices
    submesh.vertex_count = len(baked_vertices)
    if len(baked_normals) == len(baked_vertices):
        submesh.normals = baked_normals
    else:
        submesh.normals = _compute_smooth_normals(baked_vertices, submesh.faces)
    return True


def _gltf_node_matrix(node: dict[str, Any]) -> tuple[float, ...]:
    matrix = node.get("matrix")
    if isinstance(matrix, list) and len(matrix) >= 16:
        values = [float(value) for value in matrix[:16]]
        return (
            values[0], values[4], values[8], values[12],
            values[1], values[5], values[9], values[13],
            values[2], values[6], values[10], values[14],
            values[3], values[7], values[11], values[15],
        )
    translation = _float_list(node.get("translation"), 3, (0.0, 0.0, 0.0))
    rotation = _float_list(node.get("rotation"), 4, (0.0, 0.0, 0.0, 1.0))
    scale = _float_list(node.get("scale"), 3, (1.0, 1.0, 1.0))
    return _compose_trs_matrix(translation, rotation, scale)


def _compose_trs_matrix(
    translation: tuple[float, ...],
    rotation: tuple[float, ...],
    scale: tuple[float, ...],
) -> tuple[float, ...]:
    x, y, z, w = rotation
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    sx, sy, sz = scale
    return (
        (1.0 - 2.0 * (yy + zz)) * sx,
        (2.0 * (xy - wz)) * sy,
        (2.0 * (xz + wy)) * sz,
        translation[0],
        (2.0 * (xy + wz)) * sx,
        (1.0 - 2.0 * (xx + zz)) * sy,
        (2.0 * (yz - wx)) * sz,
        translation[1],
        (2.0 * (xz - wy)) * sx,
        (2.0 * (yz + wx)) * sy,
        (1.0 - 2.0 * (xx + yy)) * sz,
        translation[2],
        0.0,
        0.0,
        0.0,
        1.0,
    )


def _decode_data_uri(uri: str) -> bytes:
    _mime_type, data = _decode_data_uri_with_mime(uri)
    return data


def _decode_data_uri_with_mime(uri: str) -> tuple[str, bytes]:
    header, _sep, payload = uri.partition(",")
    mime_type = header[5:].split(";", 1)[0] if header.startswith("data:") else ""
    if ";base64" in header.lower():
        return mime_type, base64.b64decode(payload)
    return mime_type, unquote(payload).encode("utf-8")
