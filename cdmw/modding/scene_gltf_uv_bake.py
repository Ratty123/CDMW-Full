"""General multi-UV glTF conversion through the bundled xatlas/MikkTSpace path."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import math
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.core.common import raise_if_cancelled

from .mesh_native_normals import apply_native_mesh_generate_tangents
from .mesh_native_uv import apply_native_mesh_auto_uv, release_native_temporary_mesh_sessions
from .mesh_parser import ParsedMesh, SubMesh
from .scene_gltf_uv import (
    GLTF_UV_BAKE_REMEDY,
    GltfMaterialUvPlan,
    GltfPrimitiveUvInputs,
    GltfTextureSlotUvProvenance,
)
from .scene_gltf_uv_raster import (
    GltfRasterSource,
    load_gltf_raster_source,
    publish_gltf_raster_png,
    rasterize_gltf_slot,
)
from .scene_material_audit import SceneMaterialTextureSlot


@dataclass(slots=True, frozen=True)
class GltfUvPrimitiveRecord:
    material_index: int
    submesh_index: int
    primitive_label: str
    uv_inputs: GltfPrimitiveUvInputs


@dataclass(slots=True)
class GltfGeneralUvBakeOutcome:
    generated_paths: tuple[Path, ...]
    material_reports: dict[int, dict[str, object]]


@dataclass(slots=True)
class _CombinedMaterial:
    mesh: ParsedMesh
    source_uvs: dict[int, list[tuple[float, float]]]
    source_owners: list[tuple[int, int]]
    input_face_signatures: Counter[tuple[int, int, int]]
    records: tuple[GltfUvPrimitiveRecord, ...]
    authored_tangents: list[tuple[float, float, float]]
    authored_signs: list[float]
    authored_valid: list[bool]
    source_tangent_frames: dict[int, tuple[list[tuple[float, float, float]], list[float]]]


def _valid_tangent_frame(submesh: SubMesh) -> tuple[list[tuple[float, float, float]], list[float], list[bool]]:
    vertex_count = len(submesh.vertices)
    tangents = list(tuple(getattr(submesh, "tangents", ()) or ()))
    signs = list(tuple(getattr(submesh, "tangent_signs", ()) or ()))
    output_tangents: list[tuple[float, float, float]] = []
    output_signs: list[float] = []
    valid: list[bool] = []
    for index in range(vertex_count):
        tangent = tangents[index] if index < len(tangents) else ()
        try:
            sign = float(signs[index]) if index < len(signs) else 0.0
        except (TypeError, ValueError, OverflowError):
            sign = 0.0
        try:
            values = tuple(float(value) for value in tuple(tangent)[:3])
        except (TypeError, ValueError, OverflowError):
            values = ()
        try:
            normal = tuple(float(value) for value in submesh.normals[index][:3])
        except (TypeError, ValueError, OverflowError):
            normal = ()
        cross_length_squared = (
            (normal[1] * values[2] - normal[2] * values[1]) ** 2
            + (normal[2] * values[0] - normal[0] * values[2]) ** 2
            + (normal[0] * values[1] - normal[1] * values[0]) ** 2
            if len(values) == 3 and len(normal) == 3
            else 0.0
        )
        is_valid = (
            len(values) == 3
            and all(math.isfinite(value) for value in values)
            and sum(value * value for value in values) > 1.0e-12
            and cross_length_squared > 1.0e-12
            and math.isfinite(sign)
            and abs(abs(sign) - 1.0) <= 1.0e-4
        )
        output_tangents.append(values if is_valid else (1.0, 0.0, 0.0))  # type: ignore[arg-type]
        output_signs.append(1.0 if sign >= 0.0 else -1.0)
        valid.append(is_valid)
    return output_tangents, output_signs, valid


def _build_combined_material(
    mesh: ParsedMesh,
    plan: GltfMaterialUvPlan,
    records: Sequence[GltfUvPrimitiveRecord],
) -> _CombinedMaterial:
    ordered = tuple(sorted(records, key=lambda item: item.submesh_index))
    combined = SubMesh(name=f"gltf_uv_bake_material_{plan.material_index}", material=plan.material_name)
    source_uvs = {texcoord: [] for texcoord in plan.source_texcoords}
    source_owners: list[tuple[int, int]] = []
    input_face_signatures: Counter[tuple[int, int, int]] = Counter()
    authored_tangents: list[tuple[float, float, float]] = []
    authored_signs: list[float] = []
    authored_valid: list[bool] = []
    for record_index, record in enumerate(ordered):
        if not 0 <= record.submesh_index < len(mesh.submeshes):
            raise ValueError(f"glTF UV bake lost primitive {record.primitive_label}.")
        source = mesh.submeshes[record.submesh_index]
        vertex_count = len(source.vertices)
        if not vertex_count or not source.faces:
            raise ValueError(f"glTF UV bake primitive {record.primitive_label} has no triangle geometry.")
        base = len(combined.vertices)
        combined.vertices.extend(source.vertices)
        if len(source.normals) == vertex_count:
            combined.normals.extend(source.normals)
        else:
            raise ValueError(f"glTF UV bake primitive {record.primitive_label} has incomplete normals.")
        tangents, signs, valid = _valid_tangent_frame(source)
        authored_tangents.extend(tangents)
        authored_signs.extend(signs)
        authored_valid.extend(valid)
        source_owners.extend((record_index, local_index) for local_index in range(vertex_count))
        for texcoord in plan.source_texcoords:
            rows = record.uv_inputs.rows(texcoord)
            if len(rows) != vertex_count:
                raise ValueError(
                    f"glTF UV bake primitive {record.primitive_label} lost TEXCOORD_{texcoord}. {GLTF_UV_BAKE_REMEDY}"
                )
            source_uvs[texcoord].extend(rows)
        for face in source.faces:
            remapped = tuple(int(index) + base for index in face)
            combined.faces.append(remapped)
            input_face_signatures[tuple(sorted(remapped))] += 1
    combined.vertex_count = len(combined.vertices)
    combined.face_count = len(combined.faces)
    combined.source_vertex_map = list(range(combined.vertex_count))
    temporary = ParsedMesh(
        path=mesh.path,
        format=mesh.format,
        submeshes=[combined],
        total_vertices=combined.vertex_count,
        total_faces=combined.face_count,
        has_uvs=False,
        has_bones=False,
    )
    return _CombinedMaterial(
        mesh=temporary,
        source_uvs=source_uvs,
        source_owners=source_owners,
        input_face_signatures=input_face_signatures,
        records=ordered,
        authored_tangents=authored_tangents,
        authored_signs=authored_signs,
        authored_valid=authored_valid,
        source_tangent_frames={},
    )


def _derive_tangent_signs(submesh: SubMesh) -> list[float]:
    import numpy as np

    vertices = np.asarray(submesh.vertices, dtype=np.float64)
    normals = np.asarray(submesh.normals, dtype=np.float64)
    tangents = np.asarray(submesh.tangents, dtype=np.float64)
    uvs = np.asarray(submesh.uvs, dtype=np.float64)
    signs: list[float | None] = [None] * len(vertices)
    for face in submesh.faces:
        indices = np.asarray(face, dtype=np.int64)
        if len(indices) != 3 or int(indices.min()) < 0 or int(indices.max()) >= len(vertices):
            raise ValueError("glTF UV bake native tangent output has invalid topology.")
        points = vertices[indices]
        coords = uvs[indices]
        edge1, edge2 = points[1] - points[0], points[2] - points[0]
        duv1, duv2 = coords[1] - coords[0], coords[2] - coords[0]
        determinant = float(duv1[0] * duv2[1] - duv1[1] * duv2[0])
        if abs(determinant) <= 1.0e-12:
            raise ValueError("glTF UV bake source UV set is degenerate for MikkTSpace.")
        bitangent = (edge2 * duv1[0] - edge1 * duv2[0]) / determinant
        for index in indices:
            normal = normals[index]
            tangent = tangents[index]
            value = -1.0 if float(np.dot(np.cross(normal, tangent), bitangent)) < 0.0 else 1.0
            old = signs[int(index)]
            if old is not None and old != value:
                raise ValueError("glTF UV bake source tangent signs require unsupported corner splitting.")
            signs[int(index)] = value
    if any(value is None for value in signs):
        raise ValueError("glTF UV bake source tangent generation left unreferenced vertices.")
    return [float(value) for value in signs]


def _generate_native_tangent_frame(
    source: SubMesh,
    source_uvs: Sequence[Sequence[float]],
    label: str,
    *,
    stop_event: object,
) -> tuple[list[tuple[float, float, float]], list[float]]:
    temporary_submesh = copy.copy(source)
    temporary_submesh.vertices = list(source.vertices)
    temporary_submesh.normals = list(source.normals)
    temporary_submesh.faces = list(source.faces)
    temporary_submesh.uvs = [tuple(float(value) for value in row[:2]) for row in source_uvs]
    temporary_submesh.tangents = []
    temporary_submesh.source_vertex_map = list(range(len(source.vertices)))
    setattr(temporary_submesh, "tangent_signs", [])
    temporary = ParsedMesh(
        path="",
        format="gltf",
        submeshes=[temporary_submesh],
        total_vertices=len(temporary_submesh.vertices),
        total_faces=len(temporary_submesh.faces),
        has_uvs=True,
    )
    try:
        result = apply_native_mesh_generate_tangents(
            temporary,
            {0},
            stop_event=stop_event,
            timeout_seconds=60.0,
        )
        if result is None:
            raise ValueError(f"glTF UV bake could not generate {label} MikkTSpace tangents. {GLTF_UV_BAKE_REMEDY}")
        output = temporary.submeshes[0]
        if (
            len(output.vertices) != len(source.vertices)
            or list(output.source_vertex_map) != list(range(len(source.vertices)))
            or Counter(tuple(sorted(face)) for face in output.faces)
            != Counter(tuple(sorted(face)) for face in source.faces)
            or len(output.tangents) != len(source.vertices)
        ):
            raise ValueError("glTF UV bake source MikkTSpace requires unsupported topology splitting.")
        tangent_report = getattr(output, "tangent_face_corner_report", {})
        backend = str(tangent_report.get("backend") or "") if isinstance(tangent_report, Mapping) else ""
        if backend and not backend.startswith("mikktspace"):
            raise ValueError(f"glTF UV bake source tangents used unsupported backend {backend}.")
        signs = list(tuple(getattr(output, "tangent_signs", ()) or ()))
        if len(signs) != len(output.vertices):
            signs = _derive_tangent_signs(output)
        return list(output.tangents), [1.0 if float(value) >= 0.0 else -1.0 for value in signs]
    finally:
        release_native_temporary_mesh_sessions(temporary, {0})


def ensure_gltf_source_tangents(
    submesh: SubMesh,
    source_uvs: Sequence[Sequence[float]],
    texcoord: int,
    *,
    stop_event: object = None,
) -> None:
    _tangents, _signs, valid = _valid_tangent_frame(submesh)
    if valid and all(valid):
        return
    if len(source_uvs) != len(submesh.vertices):
        raise ValueError(f"glTF normal tangent generation lost TEXCOORD_{texcoord}. {GLTF_UV_BAKE_REMEDY}")
    tangents, signs = _generate_native_tangent_frame(
        submesh,
        source_uvs,
        f"source TEXCOORD_{texcoord}",
        stop_event=stop_event,
    )
    submesh.tangents = tangents
    setattr(submesh, "tangent_signs", signs)


def _generate_source_tangent_frame(
    combined: _CombinedMaterial,
    texcoord: int,
    *,
    stop_event: object,
) -> tuple[list[tuple[float, float, float]], list[float]]:
    return _generate_native_tangent_frame(
        combined.mesh.submeshes[0],
        combined.source_uvs[texcoord],
        f"source TEXCOORD_{texcoord}",
        stop_event=stop_event,
    )


def _prepare_source_tangent_frames(
    combined: _CombinedMaterial,
    texcoords: Sequence[int],
    *,
    stop_event: object,
) -> None:
    for texcoord in sorted(set(int(value) for value in texcoords)):
        if all(combined.authored_valid):
            combined.source_tangent_frames[texcoord] = (
                list(combined.authored_tangents),
                list(combined.authored_signs),
            )
            continue
        tangents, signs = _generate_source_tangent_frame(combined, texcoord, stop_event=stop_event)
        combined.source_tangent_frames[texcoord] = (tangents, signs)


def _layout_material_native(
    combined: _CombinedMaterial,
    resolution: int,
    padding: int,
    *,
    stop_event: object,
) -> dict[str, object]:
    changed = apply_native_mesh_auto_uv(
        combined.mesh,
        {0},
        resolution=resolution,
        padding=padding,
        allow_topology_change=True,
        stop_event=stop_event,
        timeout_seconds=60.0,
    )
    if changed is None:
        raise ValueError(f"glTF UV raster bake could not create the bundled xatlas layout. {GLTF_UV_BAKE_REMEDY}")
    submesh = combined.mesh.submeshes[0]
    vertex_count = len(submesh.vertices)
    source_map = tuple(int(value) for value in tuple(submesh.source_vertex_map or ()))
    if len(submesh.uvs) != vertex_count or len(source_map) != vertex_count:
        raise ValueError("glTF UV raster bake received an incomplete xatlas vertex remap.")
    if any(index < 0 or index >= len(combined.source_owners) for index in source_map):
        raise ValueError("glTF UV raster bake received an out-of-range xatlas vertex remap.")
    raise_if_cancelled(stop_event, "glTF UV bake cancelled after xatlas layout.")
    tangents = apply_native_mesh_generate_tangents(
        combined.mesh,
        {0},
        stop_event=stop_event,
        timeout_seconds=60.0,
    )
    if tangents is None:
        raise ValueError("glTF UV raster bake could not regenerate native MikkTSpace tangents.")
    submesh = combined.mesh.submeshes[0]
    if len(submesh.tangents) == len(submesh.vertices) and len(
        tuple(getattr(submesh, "tangent_signs", ()) or ())
    ) != len(submesh.vertices):
        setattr(submesh, "tangent_signs", _derive_tangent_signs(submesh))
    if (
        len(submesh.tangents) != len(submesh.vertices)
        or len(tuple(getattr(submesh, "tangent_signs", ()) or ())) != len(submesh.vertices)
        or len(submesh.source_vertex_map) != len(submesh.vertices)
    ):
        raise ValueError("glTF UV raster bake received incomplete native MikkTSpace output.")
    tangent_report = getattr(submesh, "tangent_face_corner_report", {})
    backend = str(tangent_report.get("backend") or "") if isinstance(tangent_report, Mapping) else ""
    if backend and not backend.startswith("mikktspace"):
        raise ValueError(f"glTF UV raster bake used unsupported tangent backend {backend}.")
    auto_report = dict(getattr(submesh, "auto_uv_report", {}) or {})
    return {
        "backend": str(auto_report.get("unwrap_backend") or "xatlas"),
        "chart_count": int(auto_report.get("chart_count") or 0),
        "topology_changed": bool(auto_report.get("topology_changed")),
        "input_vertex_count": len(combined.source_owners),
        "output_vertex_count": len(submesh.vertices),
        "output_face_count": len(submesh.faces),
        "resolution": int(resolution),
        "padding": int(padding),
        "requested_padding": 8,
        "effective_padding": int(padding),
    }


def _layout_material(
    combined: _CombinedMaterial,
    resolution: int,
    padding: int,
    *,
    stop_event: object,
) -> dict[str, object]:
    try:
        return _layout_material_native(combined, resolution, padding, stop_event=stop_event)
    finally:
        release_native_temporary_mesh_sessions(combined.mesh, {0})


def _effective_layout_padding(sources: Mapping[str, GltfRasterSource], resolution: int) -> int:
    minimum_dimension = min(
        (min(int(source.width), int(source.height)) for source in sources.values()),
        default=resolution,
    )
    if resolution <= 0 or minimum_dimension <= 0:
        raise ValueError("glTF UV bake received invalid output texture dimensions.")
    return max(8, int(math.ceil(8.0 * float(resolution) / float(minimum_dimension))))


def _hash_layout(submesh: SubMesh, *, stop_event: object = None) -> str:
    digest = hashlib.sha256()
    for index, vertex in enumerate(submesh.vertices):
        if index % 16384 == 0:
            raise_if_cancelled(stop_event, "glTF UV bake cancelled during layout hashing.")
        digest.update(struct.pack("<3d", *(float(value) for value in vertex[:3])))
    for index, uv in enumerate(submesh.uvs):
        if index % 16384 == 0:
            raise_if_cancelled(stop_event, "glTF UV bake cancelled during layout hashing.")
        digest.update(struct.pack("<2d", *(float(value) for value in uv[:2])))
    for index, face in enumerate(submesh.faces):
        if index % 16384 == 0:
            raise_if_cancelled(stop_event, "glTF UV bake cancelled during layout hashing.")
        digest.update(struct.pack("<3q", *(int(value) for value in face[:3])))
    for index, source_index in enumerate(submesh.source_vertex_map):
        if index % 16384 == 0:
            raise_if_cancelled(stop_event, "glTF UV bake cancelled during layout hashing.")
        digest.update(struct.pack("<q", int(source_index)))
    raise_if_cancelled(stop_event, "glTF UV bake cancelled during layout hashing.")
    return digest.hexdigest()


def _source_uvs_for_slot(
    combined: _CombinedMaterial,
    slot: GltfTextureSlotUvProvenance,
) -> list[tuple[float, float]]:
    source_rows = combined.source_uvs.get(slot.texcoord, ())
    output: list[tuple[float, float]] = []
    for source_index in combined.mesh.submeshes[0].source_vertex_map:
        if not 0 <= int(source_index) < len(source_rows):
            raise ValueError(f"glTF UV bake lost TEXCOORD_{slot.texcoord} through topology remapping.")
        output.append(source_rows[int(source_index)])
    return output


def _source_tangent_frame_for_slot(
    combined: _CombinedMaterial,
    slot: GltfTextureSlotUvProvenance,
) -> tuple[list[tuple[float, float, float]], list[float]]:
    frame = combined.source_tangent_frames.get(slot.texcoord)
    if frame is None:
        raise ValueError(f"glTF normal bake lost source TEXCOORD_{slot.texcoord} tangent frame.")
    tangents, signs = frame
    source_map = tuple(int(value) for value in combined.mesh.submeshes[0].source_vertex_map)
    if any(index < 0 or index >= len(tangents) or index >= len(signs) for index in source_map):
        raise ValueError("glTF normal bake received an invalid source tangent remap.")
    return [tangents[index] for index in source_map], [signs[index] for index in source_map]


def _texture_sources(
    plan: GltfMaterialUvPlan,
    material_slots: Mapping[str, SceneMaterialTextureSlot],
    *,
    stop_event: object,
) -> dict[str, GltfRasterSource]:
    result: dict[str, GltfRasterSource] = {}
    for slot in plan.slots:
        published_slot = material_slots.get(slot.slot_key)
        if published_slot is None or not str(published_slot.path or "").strip():
            raise ValueError(f"glTF UV bake material {plan.material_name} is missing texture slot {slot.slot_key}.")
        result[slot.slot_key] = load_gltf_raster_source(
            published_slot.path,
            slot.slot_key,
            stop_event=stop_event,
        )
    return result


def _bake_material_slots(
    source_path: Path,
    plan: GltfMaterialUvPlan,
    combined: _CombinedMaterial,
    material_slots: Mapping[str, SceneMaterialTextureSlot],
    sources: Mapping[str, GltfRasterSource],
    layout_report: Mapping[str, object],
    *,
    stop_event: object,
) -> tuple[dict[str, SceneMaterialTextureSlot], list[Path], list[dict[str, object]], list[str]]:
    updated = dict(material_slots)
    generated_paths: list[Path] = []
    slot_reports: list[dict[str, object]] = []
    warnings: list[str] = []
    layout_hash = _hash_layout(combined.mesh.submeshes[0], stop_event=stop_event)
    for slot in plan.slots:
        raise_if_cancelled(stop_event, "glTF UV bake cancelled between material slots.")
        source = sources[slot.slot_key]
        source_uvs = _source_uvs_for_slot(combined, slot)
        source_tangents: Sequence[Sequence[float]] = ()
        source_signs: Sequence[float] = ()
        if source.mode == "normal":
            source_tangents, source_signs = _source_tangent_frame_for_slot(combined, slot)
        raster = rasterize_gltf_slot(
            combined.mesh.submeshes[0],
            source_uvs,
            slot.transform,
            source,
            wrap_s=slot.wrap_s,
            wrap_t=slot.wrap_t,
            min_filter=slot.min_filter,
            mag_filter=slot.mag_filter,
            normal_scale=slot.normal_scale,
            source_tangents=source_tangents,
            source_tangent_signs=source_signs,
            release_source=True,
            stop_event=stop_event,
        )
        provenance = {
            "schema": "cdmw_gltf_uv_raster_provenance_v1",
            "material_index": plan.material_index,
            "material_name": plan.material_name,
            "slot_key": slot.slot_key,
            "slot_kind": slot.slot_kind,
            "source_sha256": source.source_sha256,
            "source_dimensions": [source.source_width, source.source_height],
            "output_dimensions": [source.width, source.height],
            "texcoord": slot.texcoord,
            "transform": list(slot.transform),
            "sampler": [slot.wrap_s, slot.wrap_t, slot.min_filter, slot.mag_filter],
            "normal_scale": slot.normal_scale,
            "layout_sha256": layout_hash,
            "layout": dict(layout_report),
        }
        output_path, publication = publish_gltf_raster_png(
            raster,
            source_path,
            slot.slot_key,
            provenance,
            stop_event=stop_event,
        )
        generated_paths.append(output_path)
        updated[slot.slot_key] = dataclasses.replace(
            material_slots[slot.slot_key],
            path=output_path.as_posix(),
            texcoord=0,
            transform=(),
            source="gltf_uv_bake",
            parameters=tuple(
                parameter
                for parameter in material_slots[slot.slot_key].parameters
                if "gltfTextureScale" not in str(parameter.parameter_name or "")
            ),
        )
        if source.downscaled:
            warnings.append(
                f"Downscaled {slot.slot_key} from {source.source_width}x{source.source_height} to "
                f"{source.width}x{source.height} for the 4096 runtime ceiling."
            )
        slot_reports.append(
            {
                "slot_key": slot.slot_key,
                "slot_kind": slot.slot_kind,
                "source_uv_set": f"TEXCOORD_{slot.texcoord}",
                "source_transform": list(slot.transform),
                "normal_scale": slot.normal_scale,
                "source_sha256": source.source_sha256,
                "source_dimensions": [source.source_width, source.source_height],
                "output_dimensions": [source.width, source.height],
                "downscaled": source.downscaled,
                **publication,
            }
        )
    return updated, generated_paths, slot_reports, warnings


def _split_material_mesh(
    target: ParsedMesh,
    combined: _CombinedMaterial,
) -> None:
    source_map = [int(value) for value in combined.mesh.submeshes[0].source_vertex_map]
    output = combined.mesh.submeshes[0]
    faces_by_record: dict[int, list[tuple[int, int, int]]] = {}
    for face in output.faces:
        source_face = tuple(source_map[int(index)] for index in face)
        signature = tuple(sorted(source_face))
        if combined.input_face_signatures[signature] <= 0:
            raise ValueError("glTF UV bake xatlas output no longer maps to an input triangle.")
        combined.input_face_signatures[signature] -= 1
        owners = {combined.source_owners[source_index][0] for source_index in source_face}
        if len(owners) != 1:
            raise ValueError("glTF UV bake xatlas output crossed primitive ownership.")
        record_index = next(iter(owners))
        faces_by_record.setdefault(record_index, []).append(tuple(int(index) for index in face))
    if any(count for count in combined.input_face_signatures.values()):
        raise ValueError("glTF UV bake xatlas output omitted one or more input triangles.")
    signs = list(tuple(getattr(output, "tangent_signs", ()) or ()))
    for record_index, record in enumerate(combined.records):
        global_faces = faces_by_record.get(record_index, [])
        if not global_faces:
            raise ValueError(f"glTF UV bake lost all faces for primitive {record.primitive_label}.")
        global_to_local: dict[int, int] = {}
        ordered_vertices: list[int] = []
        local_faces: list[tuple[int, int, int]] = []
        for face in global_faces:
            local_face: list[int] = []
            for global_index in face:
                if global_index not in global_to_local:
                    global_to_local[global_index] = len(ordered_vertices)
                    ordered_vertices.append(global_index)
                local_face.append(global_to_local[global_index])
            local_faces.append(tuple(local_face))  # type: ignore[arg-type]
        old = target.submeshes[record.submesh_index]
        replacement = copy.copy(old)
        replacement.vertices = [output.vertices[index] for index in ordered_vertices]
        replacement.uvs = [output.uvs[index] for index in ordered_vertices]
        replacement.normals = [output.normals[index] for index in ordered_vertices]
        replacement.tangents = [output.tangents[index] for index in ordered_vertices]
        replacement.faces = local_faces
        replacement.source_vertex_map = [
            combined.source_owners[source_map[index]][1] for index in ordered_vertices
        ]
        replacement.source_vertex_map_authority = "topology"
        replacement.source_vertex_offsets = []
        replacement.vertex_count = len(replacement.vertices)
        replacement.face_count = len(replacement.faces)
        setattr(replacement, "tangent_signs", [signs[index] for index in ordered_vertices])
        target.submeshes[record.submesh_index] = replacement


def bake_general_gltf_uvs(
    mesh: ParsedMesh,
    plans: Mapping[int, GltfMaterialUvPlan],
    primitive_records: Sequence[GltfUvPrimitiveRecord],
    material_slots: dict[int, dict[str, SceneMaterialTextureSlot]],
    source_path: Path,
    *,
    stop_event: object = None,
) -> GltfGeneralUvBakeOutcome:
    generated_paths: list[Path] = []
    reports: dict[int, dict[str, object]] = {}
    for material_index, plan in sorted(plans.items()):
        if not plan.requires_raster_bake:
            continue
        raise_if_cancelled(stop_event, "glTF UV bake cancelled before material conversion.")
        records = [record for record in primitive_records if record.material_index == material_index]
        if not records:
            continue
        slots = material_slots.get(material_index, {})
        sources = _texture_sources(plan, slots, stop_event=stop_event)
        resolution = max((max(source.width, source.height) for source in sources.values()), default=0)
        padding = _effective_layout_padding(sources, resolution)
        combined = _build_combined_material(mesh, plan, records)
        _prepare_source_tangent_frames(
            combined,
            [slot.texcoord for slot in plan.slots if sources[slot.slot_key].mode == "normal"],
            stop_event=stop_event,
        )
        layout_report = _layout_material(combined, resolution, padding, stop_event=stop_event)
        updated, paths, slot_reports, warnings = _bake_material_slots(
            source_path,
            plan,
            combined,
            slots,
            sources,
            layout_report,
            stop_event=stop_event,
        )
        _split_material_mesh(mesh, combined)
        material_slots[material_index] = updated
        generated_paths.extend(paths)
        reports[material_index] = {
            "mode": "xatlas_raster_bake",
            "layout": layout_report,
            "generated_slots": slot_reports,
            "generated_texture_hashes": {
                row["slot_key"]: row["output_sha256"] for row in slot_reports
            },
            "output_dimensions": {
                row["slot_key"]: row["output_dimensions"] for row in slot_reports
            },
            "warnings": warnings,
            "review_required": bool(warnings),
        }
    return GltfGeneralUvBakeOutcome(tuple(generated_paths), reports)


__all__ = [
    "GltfGeneralUvBakeOutcome",
    "GltfUvPrimitiveRecord",
    "bake_general_gltf_uvs",
    "ensure_gltf_source_tangents",
]
