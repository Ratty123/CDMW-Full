"""Scene-file import helpers for static mesh replacement.

OBJ remains the strict round-trip format.  This module accepts broader scene
formats only for static replacement and normalizes them into ParsedMesh.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import mimetypes
import re
import struct
import tempfile
import xml.etree.ElementTree as ET
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import unquote, urlparse

from .logging import get_logger
from .mesh_importer import import_obj
from .mesh_parser import ParsedMesh, SubMesh, _compute_smooth_normals, parse_mesh
from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput

logger = get_logger("core.scene_importer")

LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS = {".pac", ".pam", ".pamlod"}
SCENE_IMPORT_EXTENSIONS = {".obj", ".dae", ".gltf", ".glb", ".zip"} | LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS
SCENE_TEXTURE_SOURCE_EXTENSIONS = {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp"}
SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS = {".ktx", ".ktx2"}
SCENE_SIDECAR_SOURCE_EXTENSIONS = {
    ".xml",
    ".pami",
    ".pac_xml",
    ".pam_xml",
    ".pamlod_xml",
    ".app_xml",
    ".prefabdata_xml",
}
SCENE_COMPANION_SOURCE_EXTENSIONS = {
    ".prefab",
    ".meshinfo",
    ".material",
    ".paa_metabin",
}
_MATERIAL_CLASS_TEXTURE_ROLE_TOKENS = (
    "metallicroughness",
    "metallic_roughness",
    "roughnessmetallic",
    "roughness_metallic",
    "metalnessroughness",
    "metalness_roughness",
    "roughnessmetalness",
    "roughness_metalness",
    "occlusionroughnessmetallic",
    "occlusion_roughness_metallic",
    "orm",
    "mro",
    "rma",
    "arm",
    "basecolor",
    "base_color",
    "diffuse",
    "albedo",
    "normal",
    "roughness",
    "metallic",
    "metalness",
    "specular",
    "glossiness",
    "emissive",
    "emission",
    "opacity",
    "alpha",
    "transmission",
    "occlusion",
    "ao",
    "height",
)
_GLTF_COMPONENT_FORMATS = {
    5120: ("b", 1, True),
    5121: ("B", 1, False),
    5122: ("h", 2, True),
    5123: ("H", 2, False),
    5125: ("I", 4, False),
    5126: ("f", 4, True),
}
_GLTF_TYPE_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
_GLTF_IMAGE_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/vnd-ms.dds": ".dds",
    "image/x-dds": ".dds",
    "image/tga": ".tga",
    "image/bmp": ".bmp",
    "image/tiff": ".tif",
    "image/webp": ".webp",
    "image/ktx": ".ktx",
    "image/ktx2": ".ktx2",
}
_SCENE_TEXTURE_DISCOVERY_MAX_FILES = 5000
_SCENE_TEXTURE_DISCOVERY_FALLBACK_MAX_TEXTURES = 256
_SCENE_TEXTURE_FACT_CHANNEL_STATS_MAX_PIXELS = 64 * 1024 * 1024


@dataclass(slots=True)
class ImportedMaterialBinding:
    material_index: int = -1
    material_name: str = ""
    submesh_index: int = -1
    submesh_name: str = ""
    texture_slots: tuple[tuple[str, Path], ...] = ()
    pbr_workflow: str = ""
    alpha_mode: str = ""
    double_sided: bool = False


@dataclass(slots=True, frozen=True)
class SceneMaterialTextureSlot:
    slot_kind: str
    path: str = ""
    parameter_name: str = ""
    semantic_type: str = ""
    semantic_subtype: str = ""
    packed_channels: tuple[str, ...] = ()
    shader_family: str = ""
    srgb_mode: str = ""
    texcoord: int = 0
    transform: tuple[float, ...] = ()
    source: str = ""
    parameters: tuple[PreviewMaterialParameterInput, ...] = ()


@dataclass(slots=True, frozen=True)
class ExternalMaterialTextureInventory:
    slot_kind: str = ""
    parameter_name: str = ""
    texture_path: str = ""
    texture_name: str = ""
    image_format: str = ""
    resolution: tuple[int, int] = ()
    channel_stats: tuple[tuple[str, float], ...] = ()
    semantic_type: str = ""
    semantic_subtype: str = ""
    packed_channels: tuple[str, ...] = ()
    color_space: str = ""
    texcoord: int = 0
    uv_transform: tuple[float, ...] = ()
    source: str = ""
    confidence: str = ""
    evidence: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ExternalMaterialClassEvidence:
    material_class: str = "unknown"
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ExternalMaterialSectionInventory:
    section_index: int = -1
    section_name: str = ""
    material_name: str = ""
    vertex_count: int = 0
    face_count: int = 0
    has_uvs: bool = False
    has_normals: bool = False
    has_tangents: bool = False
    has_skinning: bool = False
    texture_texcoord_sets: tuple[int, ...] = ()
    bounds_min: tuple[float, ...] = ()
    bounds_max: tuple[float, ...] = ()


@dataclass(slots=True, frozen=True)
class ExternalMaterialInventory:
    material_index: int = -1
    material_name: str = ""
    submesh_indices: tuple[int, ...] = ()
    submesh_names: tuple[str, ...] = ()
    sections: tuple[ExternalMaterialSectionInventory, ...] = ()
    texture_slots: tuple[ExternalMaterialTextureInventory, ...] = ()
    pbr_workflow: str = ""
    alpha_mode: str = ""
    double_sided: bool = False
    scalar_hints: tuple[tuple[str, float], ...] = ()
    color_factor: tuple[float, float, float] = ()
    vertex_color_factor: tuple[float, float, float] = ()
    vertex_alpha: tuple[float, float] = ()
    emissive_color: tuple[float, float, float] = ()
    material_classes: tuple[ExternalMaterialClassEvidence, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class ExternalModelAudit:
    source_path: str = ""
    verified_category: str = "unknown"
    confidence: float = 0.0
    mesh_count: int = 0
    material_count: int = 0
    texture_slots: tuple[str, ...] = ()
    pbr_workflows: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    false_positive: bool = False
    mixed_model: bool = False
    evidence: tuple[str, ...] = ()
    material_inventory: tuple[ExternalMaterialInventory, ...] = ()
    material_classes: tuple[ExternalMaterialClassEvidence, ...] = ()


@dataclass(slots=True)
class SceneImportResult:
    mesh: ParsedMesh
    diagnostics: tuple[str, ...] = ()
    discovered_texture_files: tuple[Path, ...] = ()
    extracted_embedded_files: tuple[Path, ...] = ()
    discovered_supplemental_files: tuple[Path, ...] = ()
    material_bindings: tuple[ImportedMaterialBinding, ...] = ()
    external_audit: Optional[ExternalModelAudit] = None


_SCENE_SLOT_PARAMETER_NAMES = {
    "base": "_baseColorTexture",
    "normal": "_normalTexture",
    "occlusion": "_occlusionTexture",
    "ao": "_occlusionTexture",
    "material": "_metallicRoughnessTexture",
    "roughness": "_roughnessTexture",
    "metalness": "_metallicTexture",
    "metallic": "_metallicTexture",
    "specular": "_specularTexture",
    "glossiness": "_glossinessTexture",
    "specular_glossiness": "_specularGlossinessTexture",
    "emissive": "_emissiveTexture",
    "opacity": "_opacityTexture",
    "height": "_heightTexture",
    "clearcoat": "_clearcoatTexture",
    "clearcoat_roughness": "_clearcoatRoughnessTexture",
    "clearcoat_normal": "_clearcoatNormalTexture",
    "sheen": "_sheenColorTexture",
    "sheen_roughness": "_sheenRoughnessTexture",
    "transmission": "_transmissionTexture",
    "volume": "_thicknessTexture",
    "anisotropy": "_anisotropyTexture",
    "iridescence": "_iridescenceTexture",
}


def _scene_slot_semantics(slot_kind: str) -> tuple[str, str, str, tuple[str, ...]]:
    slot = str(slot_kind or "").strip().lower()
    if slot == "base":
        return "base", "color", "albedo", ()
    if slot == "normal":
        return "normal", "normal", "normal", ()
    if slot in {"occlusion", "ao"}:
        return "occlusion", "ao", "ao", ("ao",)
    if slot == "material":
        return "material", "material", "metallic_roughness", ("roughness", "metallic")
    if slot in {"metalness", "metallic"}:
        return "metalness", "metallic", "metallic", ("metallic",)
    if slot == "roughness":
        return "roughness", "roughness", "roughness", ("roughness",)
    if slot == "glossiness":
        return "glossiness", "roughness", "glossiness", ("glossiness",)
    if slot == "specular":
        return "specular", "specular", "specular", ("specular",)
    if slot == "specular_glossiness":
        return "material", "specular", "specular_glossiness", ("specular", "glossiness")
    if slot == "emissive":
        return "emissive", "emissive", "emissive", ()
    if slot == "opacity":
        return "opacity", "opacity", "opacity", ("alpha",)
    if slot == "height":
        return "height", "height", "height", ("height",)
    if slot == "clearcoat_roughness":
        return "roughness", "roughness", "clearcoat_roughness", ("roughness",)
    if slot == "clearcoat_normal":
        return "normal", "normal", "clearcoat_normal", ()
    if slot == "clearcoat":
        return "specular", "specular", "clearcoat", ("clearcoat",)
    if slot == "sheen_roughness":
        return "roughness", "roughness", "sheen_roughness", ("roughness",)
    if slot == "sheen":
        return "specular", "specular", "sheen", ("sheen",)
    if slot in {"transmission", "volume", "anisotropy", "iridescence"}:
        return "material", "material", slot, (slot,)
    return slot, slot, slot, ()


def _scene_material_slot(
    slot_kind: str,
    path_text: str = "",
    *,
    parameter_name: str = "",
    texcoord: int = 0,
    transform: Sequence[float] = (),
    source: str = "",
    parameters: Sequence[PreviewMaterialParameterInput] = (),
) -> SceneMaterialTextureSlot:
    input_slot, semantic_type, semantic_subtype, packed_channels = _scene_slot_semantics(slot_kind)
    parameter = str(parameter_name or "").strip() or _SCENE_SLOT_PARAMETER_NAMES.get(str(slot_kind or "").strip().lower(), "")
    return SceneMaterialTextureSlot(
        slot_kind=input_slot,
        path=str(path_text or "").strip(),
        parameter_name=parameter,
        semantic_type=semantic_type,
        semantic_subtype=semantic_subtype,
        packed_channels=packed_channels,
        shader_family="SkinnedMeshEmissive_Ver2" if input_slot == "emissive" else "",
        texcoord=max(0, int(texcoord or 0)),
        transform=tuple(float(value) for value in tuple(transform or ())[:5]),
        source=str(source or "").strip(),
        parameters=tuple(parameters),
    )


def _scene_preview_float_parameter(name: str, value: object) -> Optional[PreviewMaterialParameterInput]:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return PreviewMaterialParameterInput(
        parameter_kind="float",
        parameter_name=str(name or ""),
        value=f"{numeric:.6f}",
        numeric_value=numeric,
    )


def _scene_preview_string_parameter(name: str, value: object) -> Optional[PreviewMaterialParameterInput]:
    text = str(value or "").strip()
    if not text:
        return None
    return PreviewMaterialParameterInput(parameter_kind="string", parameter_name=str(name or ""), value=text)


def _scene_preview_color_parameter(name: str, values: object) -> Optional[PreviewMaterialParameterInput]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)) or len(values) < 3:
        return None
    try:
        rgb = tuple(max(0.0, min(1.0, float(value))) for value in values[:3])
    except (TypeError, ValueError, OverflowError):
        return None
    return PreviewMaterialParameterInput(
        parameter_kind="color",
        parameter_name=str(name or ""),
        value="#" + "".join(f"{int(round(component * 255)):02x}" for component in rgb),
        color_value=rgb,
    )


def _append_scene_parameter(target: list[PreviewMaterialParameterInput], parameter: Optional[PreviewMaterialParameterInput]) -> None:
    if parameter is not None:
        target.append(parameter)


@dataclass(slots=True, frozen=True)
class SceneMeshAppendResult:
    source_indices: tuple[int, ...]
    texture_files: tuple[Path, ...] = ()
    supplemental_files: tuple[Path, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class SceneMeshQualityReductionReport:
    original_vertices: int
    original_faces: int
    reduced_vertices: int
    reduced_faces: int
    reduced_submeshes: int
    max_faces_per_submesh: int
    max_vertices_per_submesh: int


@dataclass(slots=True)
class _ColladaGeometry:
    geometry_id: str
    name: str
    primitives: list[SubMesh]


@dataclass(slots=True)
class _GltfPayload:
    document: dict[str, Any]
    buffers: list[bytes]
    source_path: Path
    format_name: str
    diagnostics: list[str]
    extracted_embedded_files: list[Path]
    discovered_texture_files: list[Path]


@dataclass(slots=True, frozen=True)
class _GltfMeshInstance:
    mesh_index: int
    transform: tuple[float, ...]
    node_name: str
    node_index: int = -1
    skin_index: int = -1


def _scene_result_context(scene_result: SceneImportResult) -> dict[str, object]:
    return {
        "material_bindings": tuple(getattr(scene_result, "material_bindings", ()) or ()),
        "external_audit": getattr(scene_result, "external_audit", None),
    }


def import_scene_mesh(path: str | Path) -> ParsedMesh:
    return import_scene_mesh_with_report(path).mesh


def refresh_parsed_mesh_totals(mesh: ParsedMesh) -> None:
    vertices = [vertex for submesh in mesh.submeshes for vertex in submesh.vertices]
    mesh.bbox_min, mesh.bbox_max = _bbox(vertices)
    mesh.total_vertices = sum(len(submesh.vertices) for submesh in mesh.submeshes)
    mesh.total_faces = sum(len(submesh.faces) for submesh in mesh.submeshes)
    mesh.has_uvs = any(bool(submesh.uvs) for submesh in mesh.submeshes)
    mesh.has_bones = any(bool(getattr(submesh, "bone_indices", None) or getattr(submesh, "bone_weights", None)) for submesh in mesh.submeshes)


def _decimate_submesh_for_import_quality(
    submesh: SubMesh,
    *,
    max_faces: int,
    max_vertices: int,
) -> tuple[SubMesh, bool]:
    faces = list(getattr(submesh, "faces", None) or [])
    vertices = list(getattr(submesh, "vertices", None) or [])
    if not faces or not vertices:
        return copy.deepcopy(submesh), False
    if len(faces) <= max_faces and len(vertices) <= max_vertices:
        return copy.deepcopy(submesh), False

    face_budget = max(1, int(max_faces))
    vertex_budget = max(3, int(max_vertices))
    xs = [float(vertex[0]) for vertex in vertices]
    ys = [float(vertex[1]) for vertex in vertices]
    zs = [float(vertex[2]) for vertex in vertices]
    bmin = (min(xs), min(ys), min(zs))
    bmax = (max(xs), max(ys), max(zs))
    extent = (
        max(bmax[0] - bmin[0], 1e-8),
        max(bmax[1] - bmin[1], 1e-8),
        max(bmax[2] - bmin[2], 1e-8),
    )
    normals = list(getattr(submesh, "normals", None) or [])
    uvs = list(getattr(submesh, "uvs", None) or [])
    has_normals = len(normals) == len(vertices)
    has_uvs = len(uvs) == len(vertices)

    def _triangle_area(face: tuple[int, int, int], reduced_vertices: list[tuple[float, float, float]]) -> float:
        a, b, c = face
        p0, p1, p2 = reduced_vertices[a], reduced_vertices[b], reduced_vertices[c]
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        cx = (uy * vz) - (uz * vy)
        cy = (uz * vx) - (ux * vz)
        cz = (ux * vy) - (uy * vx)
        return (cx * cx + cy * cy + cz * cz) ** 0.5

    def _cluster(decisions: int) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], list[tuple[float, float, float]], list[tuple[float, float]], list[int]]:
        divisions = max(1, int(decisions))
        cluster_order: list[tuple[int, int, int]] = []
        cluster_accum: dict[tuple[int, int, int], list[float]] = {}
        source_to_cluster: list[tuple[int, int, int]] = []
        scale = max(1, divisions - 1)
        for vertex_index, vertex in enumerate(vertices):
            key = (
                max(0, min(scale, int(((float(vertex[0]) - bmin[0]) / extent[0]) * scale))),
                max(0, min(scale, int(((float(vertex[1]) - bmin[1]) / extent[1]) * scale))),
                max(0, min(scale, int(((float(vertex[2]) - bmin[2]) / extent[2]) * scale))),
            )
            source_to_cluster.append(key)
            accum = cluster_accum.get(key)
            if accum is None:
                accum = [0.0] * 9
                cluster_accum[key] = accum
                cluster_order.append(key)
            accum[0] += 1.0
            accum[1] += float(vertex[0])
            accum[2] += float(vertex[1])
            accum[3] += float(vertex[2])
            if has_normals:
                normal = normals[vertex_index]
                accum[4] += float(normal[0])
                accum[5] += float(normal[1])
                accum[6] += float(normal[2])
            if has_uvs:
                uv = uvs[vertex_index]
                accum[7] += float(uv[0])
                accum[8] += float(uv[1])

        cluster_to_index = {key: index for index, key in enumerate(cluster_order)}
        reduced_vertices: list[tuple[float, float, float]] = []
        reduced_normals: list[tuple[float, float, float]] = []
        reduced_uvs: list[tuple[float, float]] = []
        for key in cluster_order:
            count, sx, sy, sz, nx, ny, nz, su, sv = cluster_accum[key]
            inv = 1.0 / max(count, 1.0)
            reduced_vertices.append((sx * inv, sy * inv, sz * inv))
            if has_normals:
                length = max((nx * nx + ny * ny + nz * nz) ** 0.5, 1e-8)
                reduced_normals.append((nx / length, ny / length, nz / length))
            if has_uvs:
                reduced_uvs.append((su * inv, sv * inv))

        reduced_faces: list[tuple[int, int, int]] = []
        seen_faces: set[tuple[int, int, int]] = set()
        for face in faces:
            remapped: list[int] = []
            for raw_index in face[:3]:
                try:
                    source_index = int(raw_index)
                except (TypeError, ValueError):
                    remapped = []
                    break
                if source_index < 0 or source_index >= len(source_to_cluster):
                    remapped = []
                    break
                remapped.append(cluster_to_index[source_to_cluster[source_index]])
            if len(remapped) != 3 or len(set(remapped)) != 3:
                continue
            normalized_face = tuple(remapped)
            dedupe_key = tuple(sorted(normalized_face))
            if dedupe_key in seen_faces:
                continue
            seen_faces.add(dedupe_key)
            reduced_faces.append(normalized_face)  # type: ignore[arg-type]
        if len(reduced_faces) > face_budget:
            ranked = sorted(
                enumerate(reduced_faces),
                key=lambda item: _triangle_area(item[1], reduced_vertices),
                reverse=True,
            )
            keep_indices = {index for index, _face in ranked[:face_budget]}
            reduced_faces = [face for index, face in enumerate(reduced_faces) if index in keep_indices]
        used_vertices = sorted({index for face in reduced_faces for index in face})
        if not used_vertices:
            return [], [], [], [], []
        remap = {old: new for new, old in enumerate(used_vertices)}
        compact_vertices = [reduced_vertices[index] for index in used_vertices]
        compact_normals = [reduced_normals[index] for index in used_vertices] if has_normals else []
        compact_uvs = [reduced_uvs[index] for index in used_vertices] if has_uvs else []
        compact_faces = [(remap[a], remap[b], remap[c]) for a, b, c in reduced_faces]
        return compact_vertices, compact_faces, compact_normals, compact_uvs, used_vertices

    divisions = max(2, int(math.ceil(vertex_budget ** (1.0 / 3.0))) * 2)
    best: tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], list[tuple[float, float, float]], list[tuple[float, float]], list[int]] | None = None
    for _attempt in range(18):
        candidate = _cluster(divisions)
        candidate_vertices, candidate_faces, _candidate_normals, _candidate_uvs, _candidate_used = candidate
        if candidate_vertices and candidate_faces:
            best = candidate
            if len(candidate_vertices) <= vertex_budget and len(candidate_faces) <= face_budget:
                break
        if divisions <= 1:
            break
        divisions = max(1, int(divisions * 0.75))

    if best is None or not best[0] or not best[1]:
        return copy.deepcopy(submesh), False
    preview_vertices, sampled_faces, reduced_normals, reduced_uvs, used_cluster_indices = best
    reduced = copy.deepcopy(submesh)
    reduced.vertices = preview_vertices
    reduced.faces = sampled_faces
    reduced.uvs = reduced_uvs if len(reduced_uvs) == len(preview_vertices) else []
    reduced.normals = reduced_normals if len(reduced_normals) == len(preview_vertices) else []
    if not reduced.normals or len(reduced.normals) != len(reduced.vertices):
        reduced.normals = _compute_smooth_normals(reduced.vertices, reduced.faces)
    reduced.bone_indices = []
    reduced.bone_weights = []
    reduced.source_vertex_map = [int(index) for index in used_cluster_indices]
    reduced.source_vertex_offsets = []
    reduced.source_index_offset = -1
    reduced.source_index_count = len(reduced.faces) * 3
    reduced.vertex_count = len(reduced.vertices)
    reduced.face_count = len(reduced.faces)
    return reduced, True


def reduce_scene_import_result_quality(
    scene_result: SceneImportResult,
    *,
    max_faces_per_submesh: int = 45_000,
    max_vertices_per_submesh: int = 55_000,
) -> tuple[SceneImportResult, SceneMeshQualityReductionReport]:
    """Return a session-only lower-density copy of an imported scene mesh."""
    if not isinstance(scene_result, SceneImportResult):
        raise TypeError("reduce_scene_import_result_quality requires a SceneImportResult.")
    source_mesh = scene_result.mesh
    reduced_mesh = copy.deepcopy(source_mesh)
    reduced_submeshes: list[SubMesh] = []
    changed_count = 0
    for submesh in getattr(source_mesh, "submeshes", ()) or ():
        reduced_submesh, changed = _decimate_submesh_for_import_quality(
            submesh,
            max_faces=max(1, int(max_faces_per_submesh)),
            max_vertices=max(1, int(max_vertices_per_submesh)),
        )
        reduced_submeshes.append(reduced_submesh)
        if changed:
            changed_count += 1
    reduced_mesh.submeshes = reduced_submeshes
    refresh_parsed_mesh_totals(reduced_mesh)
    report = SceneMeshQualityReductionReport(
        original_vertices=sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in getattr(source_mesh, "submeshes", ()) or ()),
        original_faces=sum(len(getattr(submesh, "faces", ()) or ()) for submesh in getattr(source_mesh, "submeshes", ()) or ()),
        reduced_vertices=sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in reduced_submeshes),
        reduced_faces=sum(len(getattr(submesh, "faces", ()) or ()) for submesh in reduced_submeshes),
        reduced_submeshes=changed_count,
        max_faces_per_submesh=max(1, int(max_faces_per_submesh)),
        max_vertices_per_submesh=max(1, int(max_vertices_per_submesh)),
    )
    diagnostics = tuple(scene_result.diagnostics or ())
    if changed_count:
        diagnostics += (
            "Session-only mesh quality reduction: "
            f"{report.original_vertices:,} vertices/{report.original_faces:,} faces -> "
            f"{report.reduced_vertices:,} vertices/{report.reduced_faces:,} faces.",
        )
    return (
        SceneImportResult(
            mesh=reduced_mesh,
            diagnostics=diagnostics,
            discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
            extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
            discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
            **_scene_result_context(scene_result),
        ),
        report,
    )


def flatten_scene_import_result_parts(
    scene_result: SceneImportResult,
    *,
    part_name: str = "",
    material_name: str = "",
) -> SceneImportResult:
    """Return a session-only copy whose appendable scene submeshes are one source part."""
    if not isinstance(scene_result, SceneImportResult):
        raise TypeError("flatten_scene_import_result_parts requires a SceneImportResult.")
    source_mesh = scene_result.mesh
    imported_submeshes = [
        submesh
        for submesh in tuple(getattr(source_mesh, "submeshes", ()) or ())
        if getattr(submesh, "vertices", None) and getattr(submesh, "faces", None)
    ]
    if len(imported_submeshes) <= 1:
        return SceneImportResult(
            mesh=copy.deepcopy(source_mesh),
            diagnostics=tuple(scene_result.diagnostics or ()),
            discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
            extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
            discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
            **_scene_result_context(scene_result),
        )

    def unique_values(attribute_name: str) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for submesh in imported_submeshes:
            value = str(getattr(submesh, attribute_name, "") or "").strip()
            key = value.lower()
            if value and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    mesh_path = Path(str(getattr(source_mesh, "path", "") or ""))
    fallback_name = str(part_name or mesh_path.stem or "flattened_part").strip() or "flattened_part"
    material_values = unique_values("material")
    texture_values = unique_values("texture")
    flattened_material = str(material_name or "").strip()
    if not flattened_material:
        flattened_material = material_values[0] if len(material_values) == 1 else fallback_name
    flattened_texture = texture_values[0] if len(texture_values) == 1 else ""
    combined = SubMesh(name=fallback_name, material=flattened_material, texture=flattened_texture)

    wants_uvs = any(len(getattr(submesh, "uvs", ()) or ()) == len(getattr(submesh, "vertices", ()) or ()) for submesh in imported_submeshes)
    can_copy_normals = all(
        len(getattr(submesh, "normals", ()) or ()) == len(getattr(submesh, "vertices", ()) or ())
        for submesh in imported_submeshes
    )
    can_copy_bones = all(
        len(getattr(submesh, "bone_indices", ()) or ()) == len(getattr(submesh, "vertices", ()) or ())
        and len(getattr(submesh, "bone_weights", ()) or ()) == len(getattr(submesh, "vertices", ()) or ())
        for submesh in imported_submeshes
    )
    skipped_faces = 0
    for submesh in imported_submeshes:
        vertices = list(getattr(submesh, "vertices", ()) or ())
        base_index = len(combined.vertices)
        combined.vertices.extend(copy.deepcopy(vertices))
        uvs = list(getattr(submesh, "uvs", ()) or ())
        if wants_uvs:
            if len(uvs) == len(vertices):
                combined.uvs.extend(copy.deepcopy(uvs))
            else:
                combined.uvs.extend([(0.0, 0.0)] * len(vertices))
        if can_copy_normals:
            combined.normals.extend(copy.deepcopy(list(getattr(submesh, "normals", ()) or ())))
        if can_copy_bones:
            combined.bone_indices.extend(copy.deepcopy(list(getattr(submesh, "bone_indices", ()) or ())))
            combined.bone_weights.extend(copy.deepcopy(list(getattr(submesh, "bone_weights", ()) or ())))
        for face in getattr(submesh, "faces", ()) or ():
            if len(face) != 3:
                skipped_faces += 1
                continue
            try:
                a, b, c = int(face[0]), int(face[1]), int(face[2])
            except (TypeError, ValueError):
                skipped_faces += 1
                continue
            if min(a, b, c) < 0 or max(a, b, c) >= len(vertices):
                skipped_faces += 1
                continue
            combined.faces.append((a + base_index, b + base_index, c + base_index))

    if not combined.vertices or not combined.faces:
        raise ValueError("Flattened mesh did not contain triangle geometry.")
    if not can_copy_normals:
        combined.normals = _compute_smooth_normals(combined.vertices, combined.faces)
    combined.vertex_count = len(combined.vertices)
    combined.face_count = len(combined.faces)
    combined.source_vertex_offsets = []
    combined.source_vertex_map = []
    combined.source_index_offset = -1
    combined.source_index_count = len(combined.faces) * 3

    flattened_mesh = copy.deepcopy(source_mesh)
    flattened_mesh.submeshes = [combined]
    refresh_parsed_mesh_totals(flattened_mesh)
    diagnostics = list(scene_result.diagnostics or ())
    diagnostics.append(
        f"Flattened {len(imported_submeshes):,} imported part(s) into one source part "
        f"({len(combined.vertices):,} vertices, {len(combined.faces):,} faces)."
    )
    if len(material_values) > 1:
        diagnostics.append(
            "Flattening collapsed multiple source materials into one in-session material. "
            "Use a baked/atlased texture set or route one material in the Textures tab."
        )
    if skipped_faces:
        diagnostics.append(f"Skipped {skipped_faces:,} invalid face(s) while flattening imported parts.")
    return SceneImportResult(
        mesh=flattened_mesh,
        diagnostics=tuple(diagnostics),
        discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
        extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
        discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
        **_scene_result_context(scene_result),
    )


def group_scene_import_result_parts_by_material(
    scene_result: SceneImportResult,
    *,
    part_name: str = "",
) -> SceneImportResult:
    """Return a session-only copy with imported parts flattened per material."""
    if not isinstance(scene_result, SceneImportResult):
        raise TypeError("group_scene_import_result_parts_by_material requires a SceneImportResult.")
    source_mesh = scene_result.mesh
    imported_submeshes = [
        submesh
        for submesh in tuple(getattr(source_mesh, "submeshes", ()) or ())
        if getattr(submesh, "vertices", None) and getattr(submesh, "faces", None)
    ]
    if len(imported_submeshes) <= 1:
        return SceneImportResult(
            mesh=copy.deepcopy(source_mesh),
            diagnostics=tuple(scene_result.diagnostics or ()),
            discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
            extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
            discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
            **_scene_result_context(scene_result),
        )

    grouped: "OrderedDict[str, list[SubMesh]]" = OrderedDict()
    display_names: dict[str, str] = {}
    for submesh in imported_submeshes:
        material = str(getattr(submesh, "material", "") or getattr(submesh, "texture", "") or getattr(submesh, "name", "") or "").strip()
        key = material.lower() or f"group_{len(grouped)}"
        grouped.setdefault(key, []).append(submesh)
        display_names.setdefault(key, material or f"group_{len(grouped)}")

    mesh_path = Path(str(getattr(source_mesh, "path", "") or ""))
    base_name = str(part_name or mesh_path.stem or "grouped_part").strip() or "grouped_part"
    grouped_submeshes: list[SubMesh] = []
    diagnostics = list(scene_result.diagnostics or ())
    for group_key, submeshes in grouped.items():
        material = display_names.get(group_key, group_key) or group_key
        temp_mesh = copy.deepcopy(source_mesh)
        temp_mesh.submeshes = [copy.deepcopy(submesh) for submesh in submeshes]
        refresh_parsed_mesh_totals(temp_mesh)
        temp_result = SceneImportResult(
            mesh=temp_mesh,
            diagnostics=(),
            discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
            extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
            discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
            **_scene_result_context(scene_result),
        )
        grouped_name = f"{base_name}: {material}" if len(grouped) > 1 else base_name
        flattened = flatten_scene_import_result_parts(
            temp_result,
            part_name=grouped_name,
            material_name=material,
        )
        if flattened.mesh.submeshes:
            grouped_submeshes.append(flattened.mesh.submeshes[0])

    grouped_mesh = copy.deepcopy(source_mesh)
    grouped_mesh.submeshes = grouped_submeshes
    refresh_parsed_mesh_totals(grouped_mesh)
    diagnostics.append(
        f"Grouped {len(imported_submeshes):,} imported part(s) into {len(grouped_submeshes):,} material group(s)."
    )
    return SceneImportResult(
        mesh=grouped_mesh,
        diagnostics=tuple(diagnostics),
        discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
        extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
        discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
        **_scene_result_context(scene_result),
    )


def append_scene_import_to_mesh(
    target_mesh: ParsedMesh,
    base_mesh: ParsedMesh,
    scene_result: SceneImportResult,
    *,
    source_path: str | Path | None = None,
    label_prefix: str = "",
) -> SceneMeshAppendResult:
    """Append imported scene submeshes to the active and reset/base meshes."""
    if not isinstance(target_mesh, ParsedMesh) or not isinstance(base_mesh, ParsedMesh):
        raise TypeError("append_scene_import_to_mesh requires active and base ParsedMesh instances.")
    if not isinstance(scene_result, SceneImportResult):
        raise TypeError("append_scene_import_to_mesh requires a SceneImportResult.")
    imported_mesh = scene_result.mesh
    imported_submeshes = list(getattr(imported_mesh, "submeshes", ()) or ())
    if not imported_submeshes:
        raise ValueError("The selected mesh did not contain appendable submeshes.")
    path_label = ""
    if source_path is not None:
        path_label = Path(source_path).expanduser().stem
    if not path_label:
        path_label = Path(str(getattr(imported_mesh, "path", "") or "")).stem
    prefix = str(label_prefix or path_label or "appended").strip()
    start_index = len(target_mesh.submeshes)
    added_indices: list[int] = []
    for imported_index, source_submesh in enumerate(imported_submeshes):
        if not getattr(source_submesh, "vertices", None) or not getattr(source_submesh, "faces", None):
            continue
        active_submesh = copy.deepcopy(source_submesh)
        base_submesh = copy.deepcopy(source_submesh)
        base_name = str(getattr(source_submesh, "name", "") or getattr(source_submesh, "material", "") or f"part_{imported_index}")
        display_name = f"{prefix}: {base_name}" if prefix and not base_name.lower().startswith(prefix.lower()) else base_name
        active_submesh.name = display_name
        base_submesh.name = display_name
        if not str(getattr(active_submesh, "material", "") or "").strip():
            active_submesh.material = display_name
            base_submesh.material = display_name
        target_mesh.submeshes.append(active_submesh)
        base_mesh.submeshes.append(base_submesh)
        added_indices.append(start_index + len(added_indices))
    if not added_indices:
        raise ValueError("The selected mesh did not contain triangle geometry that can be appended.")
    refresh_parsed_mesh_totals(target_mesh)
    refresh_parsed_mesh_totals(base_mesh)
    texture_files = tuple(_dedupe_paths(list(scene_result.discovered_texture_files) + list(scene_result.extracted_embedded_files)))
    supplemental_files = tuple(
        _dedupe_paths(
            list(texture_files)
            + list(getattr(scene_result, "discovered_supplemental_files", ()) or ())
        )
    )
    diagnostics = tuple(scene_result.diagnostics) + (
        f"Appended {len(added_indices):,} source part(s) from {Path(source_path).name if source_path else prefix}.",
    )
    return SceneMeshAppendResult(
        source_indices=tuple(added_indices),
        texture_files=texture_files,
        supplemental_files=supplemental_files,
        diagnostics=diagnostics,
    )


def import_scene_mesh_with_report(path: str | Path) -> SceneImportResult:
    source_path = Path(path).expanduser().resolve()
    suffix = source_path.suffix.lower()
    if suffix == ".zip":
        from cdmw.core.model_catalogue import resolve_importable_model_path, zip_importable_members

        members = zip_importable_members(source_path)
        resolved_path = resolve_importable_model_path(source_path)
        if resolved_path is None:
            raise ValueError(
                f"ZIP file does not contain an importable model: {source_path}. "
                "Expected OBJ, DAE, glTF, GLB, PAC, PAM, or PAMLOD."
            )
        result = import_scene_mesh_with_report(resolved_path)
        member_label = members[0] if members else resolved_path.name
        result.diagnostics = (
            f"Resolved ZIP archive {source_path.name} to {member_label}.",
        ) + tuple(result.diagnostics or ())
        return result
    if suffix == ".obj":
        mesh = import_obj(str(source_path))
        if not str(getattr(mesh, "format", "") or "").strip():
            mesh.format = "obj"
        if not str(getattr(mesh, "path", "") or "").strip():
            mesh.path = source_path.as_posix()
        material_slots = _obj_material_texture_slots(source_path)
        material_parameters = _obj_material_parameters(source_path)
        material_slots_by_lower = {str(name or "").strip().lower(): slots for name, slots in material_slots.items()}
        material_parameters_by_lower = {str(name or "").strip().lower(): parameters for name, parameters in material_parameters.items()}
        for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
            material_key = str(getattr(submesh, "material", "") or "").strip()
            slots = material_slots.get(material_key) or material_slots_by_lower.get(material_key.lower()) or ()
            parameters = material_parameters.get(material_key) or material_parameters_by_lower.get(material_key.lower()) or ()
            if slots or parameters:
                _apply_scene_material_slots_to_submesh(submesh, slots, material_parameters=parameters, confidence="obj_mtl")
        discovered_textures = discover_scene_texture_files(source_path, mesh)
        _attach_fallback_texture_references(mesh, discovered_textures)
        attached_slots = _attach_sibling_material_texture_slots(mesh, discovered_textures)
        diagnostics = (
            (f"Attached {attached_slots:,} sibling OBJ texture support slot(s) by filename fallback.",)
            if attached_slots
            else ()
        )
        return _result_with_external_audit(
            source_path,
            SceneImportResult(mesh=mesh, diagnostics=diagnostics, discovered_texture_files=discovered_textures),
        )
    if suffix == ".dae":
        mesh = import_dae(source_path)
        discovered_textures = discover_scene_texture_files(source_path, mesh)
        attached_slots = _attach_sibling_material_texture_slots(mesh, discovered_textures)
        diagnostics = (
            (f"Attached {attached_slots:,} sibling DAE texture support slot(s) by filename fallback.",)
            if attached_slots
            else ()
        )
        return _result_with_external_audit(
            source_path,
            SceneImportResult(mesh=mesh, diagnostics=diagnostics, discovered_texture_files=discovered_textures),
        )
    if suffix in {".gltf", ".glb"}:
        return import_gltf(source_path)
    if suffix in LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS:
        mesh = parse_mesh(source_path.read_bytes(), source_path.as_posix())
        if not mesh.submeshes or mesh.total_faces <= 0:
            raise ValueError(f"{source_path.suffix.upper().lstrip('.')} source did not contain recoverable mesh geometry: {source_path}")
        discovered_files = discover_local_mesh_supplemental_files(source_path, mesh)
        discovered_textures = tuple(path for path in discovered_files if path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS)
        discovered_supplemental = tuple(
            path
            for path in discovered_files
            if path.suffix.lower() in SCENE_SIDECAR_SOURCE_EXTENSIONS
            or path.suffix.lower() in SCENE_COMPANION_SOURCE_EXTENSIONS
        )
        discovered_sidecars = tuple(path for path in discovered_supplemental if path.suffix.lower() in SCENE_SIDECAR_SOURCE_EXTENSIONS)
        discovered_companions = tuple(
            path for path in discovered_supplemental if path.suffix.lower() in SCENE_COMPANION_SOURCE_EXTENSIONS
        )
        diagnostics = [
            f"Parsed local {source_path.suffix.upper().lstrip('.')} mesh source for Mesh Replacement.",
        ]
        if mesh.has_bones:
            diagnostics.append(
                "Source bone weights were detected; Mesh Replacement uses the selected target's donor skeleton/layout."
            )
        if discovered_sidecars:
            diagnostics.append(f"Discovered {len(discovered_sidecars):,} local material sidecar file(s).")
        if discovered_companions:
            diagnostics.append(f"Discovered {len(discovered_companions):,} local Crimson companion metadata file(s).")
        if discovered_textures:
            diagnostics.append(f"Discovered {len(discovered_textures):,} local DDS/texture file(s).")
        return _result_with_external_audit(
            source_path,
            SceneImportResult(
                mesh=mesh,
                diagnostics=tuple(diagnostics),
                discovered_texture_files=discovered_textures,
                discovered_supplemental_files=discovered_supplemental,
            ),
        )
    if suffix in {".fbx", ".blend", ".usd", ".usda", ".usdc", ".usdz"}:
        raise ValueError(
            f"{source_path.suffix.upper().lstrip('.')} files are browsable but not preview-importable in this build. "
            "Export OBJ, DAE, GLB, or glTF to keep material/texture preview support without external converter dependencies."
        )
    raise ValueError(f"Unsupported mesh import format: {source_path.suffix or source_path.name}")


def _result_with_external_audit(source_path: Path, result: SceneImportResult) -> SceneImportResult:
    if not isinstance(result, SceneImportResult):
        return result
    if result.external_audit is None:
        result.external_audit = audit_external_model(source_path, result)
    return result


def audit_external_model(source_path: str | Path, scene_result: SceneImportResult) -> ExternalModelAudit:
    """Classify an imported model using geometry, material, and texture evidence."""
    source = Path(source_path)
    mesh = scene_result.mesh
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    material_inventory = _build_external_material_inventory(scene_result)
    material_names = {
        str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or "").strip()
        for submesh in submeshes
        if str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or "").strip()
    }
    texture_paths = tuple(
        path
        for path in tuple(scene_result.discovered_texture_files or ())
        + tuple(scene_result.extracted_embedded_files or ())
        + tuple(scene_result.discovered_supplemental_files or ())
        if isinstance(path, Path) and path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS
    )
    binding_slots = [
        slot_kind
        for binding in tuple(getattr(scene_result, "material_bindings", ()) or ())
        for slot_kind, _path in tuple(getattr(binding, "texture_slots", ()) or ())
    ]
    inventory_slots = [
        slot.slot_kind
        for material in material_inventory
        for slot in tuple(material.texture_slots or ())
        if str(slot.slot_kind or "").strip()
    ]
    texture_slots = tuple(
        sorted(
            set(
                binding_slots
                + inventory_slots
                + [_audit_texture_slot_from_path(path) for path in texture_paths if _audit_texture_slot_from_path(path)]
            )
        )
    )
    workflows = tuple(
        sorted(
            {
                str(getattr(binding, "pbr_workflow", "") or "").strip()
                for binding in tuple(getattr(scene_result, "material_bindings", ()) or ())
                if str(getattr(binding, "pbr_workflow", "") or "").strip()
            }
        )
    )
    text = " ".join(
        [str(source), str(getattr(mesh, "path", "") or "")]
        + [str(name) for name in material_names]
        + [path.stem for path in texture_paths]
    ).lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    extent = _mesh_extent(mesh)
    longest = max(extent) if extent else 0.0
    shortest = max(min(value for value in extent if value > 1e-8), 1e-8) if extent else 1e-8
    slender_ratio = longest / shortest if shortest > 0.0 else 0.0
    scores = {"sword": 0.0, "axe": 0.0, "helmet": 0.0}
    if tokens & {"sword", "blade", "dagger", "katana", "scimitar", "greatsword", "longsword"}:
        scores["sword"] += 0.50
    if tokens & {"axe", "hatchet", "halberd", "ax"}:
        scores["axe"] += 0.48
    if tokens & {"helmet", "helm", "mask", "visor"}:
        scores["helmet"] += 0.55
    if slender_ratio >= 5.0:
        scores["sword"] += 0.22
        scores["axe"] += 0.10
    if 1.1 <= slender_ratio <= 3.2 and tokens & {"helmet", "helm", "mask", "visor"}:
        scores["helmet"] += 0.18
    if any(slot in texture_slots for slot in ("base", "normal")):
        for key in scores:
            scores[key] += 0.06
    character_tokens = {"character", "body", "head", "hair", "skin", "arm", "hand", "leg", "foot", "nude", "torso"}
    false_positive = bool((tokens & {"axem", "axe"}) and len(tokens & character_tokens) >= 2)
    if "axem" in text.replace("-", "").replace("_", ""):
        false_positive = True
    if false_positive:
        scores["axe"] *= 0.30
    category, confidence = max(scores.items(), key=lambda item: item[1])
    if confidence < 0.35:
        category = "unknown"
    mixed_categories = [name for name, score in scores.items() if score >= 0.35]
    warnings: list[str] = []
    evidence: list[str] = []
    if false_positive:
        warnings.append("Filename/tag evidence looks like an axe, but mesh/material evidence looks like a mixed character asset.")
    if len(mixed_categories) > 1:
        warnings.append("Model has mixed category evidence; verify the intended subpart before replacement.")
    if texture_paths and "base" not in texture_slots:
        warnings.append("Textures were found but no clear visible base/diffuse texture was identified.")
    if not texture_paths:
        warnings.append("No external texture files were discovered.")
    if slender_ratio:
        evidence.append(f"shape ratio {slender_ratio:.1f}:1")
    if texture_slots:
        evidence.append("texture roles " + ", ".join(texture_slots[:8]))
    if workflows:
        evidence.append("PBR " + ", ".join(workflows))
    material_classes = _aggregate_external_material_classes(material_inventory)
    if material_classes:
        evidence.append(
            "material classes "
            + ", ".join(f"{item.material_class}:{item.confidence:.0%}" for item in material_classes[:6])
        )
    return ExternalModelAudit(
        source_path=str(source),
        verified_category=category,
        confidence=max(0.0, min(1.0, float(confidence))),
        mesh_count=len(submeshes),
        material_count=len(material_names),
        texture_slots=texture_slots,
        pbr_workflows=workflows,
        warnings=tuple(warnings),
        false_positive=false_positive,
        mixed_model=len(mixed_categories) > 1 or false_positive,
        evidence=tuple(evidence),
        material_inventory=material_inventory,
        material_classes=material_classes,
    )


def _build_external_material_inventory(scene_result: SceneImportResult) -> tuple[ExternalMaterialInventory, ...]:
    mesh = getattr(scene_result, "mesh", None)
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    bindings = tuple(getattr(scene_result, "material_bindings", ()) or ())
    if bindings:
        groups: OrderedDict[tuple[int, str], list[ImportedMaterialBinding]] = OrderedDict()
        for binding in bindings:
            material_index = _safe_int(getattr(binding, "material_index", -1), -1)
            material_name = str(getattr(binding, "material_name", "") or "").strip()
            key = (material_index, material_name.casefold())
            groups.setdefault(key, []).append(binding)
        return tuple(
            _external_material_inventory_from_binding_group(group, submeshes)
            for group in groups.values()
        )

    by_material: OrderedDict[str, list[tuple[int, SubMesh]]] = OrderedDict()
    for index, submesh in enumerate(submeshes):
        material_name = str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or f"submesh_{index}").strip()
        by_material.setdefault(material_name.casefold(), []).append((index, submesh))
    return tuple(
        _external_material_inventory_from_submesh_group(group, material_index=index)
        for index, group in enumerate(by_material.values())
    )


def _external_material_inventory_from_binding_group(
    bindings: Sequence[ImportedMaterialBinding],
    submeshes: Sequence[SubMesh],
) -> ExternalMaterialInventory:
    binding_tuple = tuple(bindings or ())
    first = binding_tuple[0] if binding_tuple else ImportedMaterialBinding()
    submesh_indices = tuple(
        _safe_int(getattr(binding, "submesh_index", -1), -1)
        for binding in binding_tuple
        if _safe_int(getattr(binding, "submesh_index", -1), -1) >= 0
    )
    group_submeshes = tuple(
        submeshes[index]
        for index in submesh_indices
        if 0 <= index < len(submeshes)
    )
    section_pairs = tuple((index, submeshes[index]) for index in submesh_indices if 0 <= index < len(submeshes))
    material_name = str(getattr(first, "material_name", "") or "").strip()
    if not material_name and group_submeshes:
        material_name = str(getattr(group_submeshes[0], "material", "") or getattr(group_submeshes[0], "name", "") or "").strip()
    texture_slots = _external_inventory_texture_slots(group_submeshes, binding_tuple)
    sections = _external_material_section_inventory(section_pairs)
    workflow = _normalize_external_pbr_workflow(
        next((str(getattr(binding, "pbr_workflow", "") or "") for binding in binding_tuple if str(getattr(binding, "pbr_workflow", "") or "").strip()), "")
    )
    alpha_mode = _external_inventory_alpha_mode(group_submeshes, binding_tuple)
    double_sided = any(bool(getattr(binding, "double_sided", False)) for binding in binding_tuple) or any(
        bool(getattr(submesh, "preview_double_sided", False)) for submesh in group_submeshes
    )
    scalar_hints = _external_inventory_scalar_hints(group_submeshes)
    color_factor = _external_inventory_color_factor(group_submeshes)
    vertex_color_factor = _external_inventory_vertex_color_factor(group_submeshes)
    vertex_alpha = _external_inventory_vertex_alpha(group_submeshes)
    emissive_color = _external_inventory_emissive_color(group_submeshes)
    classes = _classify_external_material(
        material_name=material_name,
        texture_slots=texture_slots,
        pbr_workflow=workflow,
        alpha_mode=alpha_mode,
        double_sided=double_sided,
        scalar_hints=scalar_hints,
        color_factor=color_factor,
        vertex_color_factor=vertex_color_factor,
        vertex_alpha=vertex_alpha,
        emissive_color=emissive_color,
    )
    warnings = _external_inventory_warnings(texture_slots, workflow, alpha_mode, classes)
    return ExternalMaterialInventory(
        material_index=_safe_int(getattr(first, "material_index", -1), -1),
        material_name=material_name,
        submesh_indices=submesh_indices,
        submesh_names=tuple(_dedupe_text([str(getattr(binding, "submesh_name", "") or "") for binding in binding_tuple])),
        sections=sections,
        texture_slots=texture_slots,
        pbr_workflow=workflow,
        alpha_mode=alpha_mode,
        double_sided=double_sided,
        scalar_hints=scalar_hints,
        color_factor=color_factor,
        vertex_color_factor=vertex_color_factor,
        vertex_alpha=vertex_alpha,
        emissive_color=emissive_color,
        material_classes=classes,
        warnings=warnings,
    )


def _external_material_inventory_from_submesh_group(
    group: Sequence[tuple[int, SubMesh]],
    *,
    material_index: int,
) -> ExternalMaterialInventory:
    group_tuple = tuple(group or ())
    submesh_indices = tuple(index for index, _submesh in group_tuple)
    submeshes = tuple(submesh for _index, submesh in group_tuple)
    material_name = ""
    if submeshes:
        material_name = str(getattr(submeshes[0], "material", "") or getattr(submeshes[0], "name", "") or "").strip()
    texture_slots = _external_inventory_texture_slots(submeshes, ())
    sections = _external_material_section_inventory(group_tuple)
    alpha_mode = _external_inventory_alpha_mode(submeshes, ())
    double_sided = any(bool(getattr(submesh, "preview_double_sided", False)) for submesh in submeshes)
    scalar_hints = _external_inventory_scalar_hints(submeshes)
    workflow = _external_inventory_workflow_from_slots(texture_slots, scalar_hints)
    color_factor = _external_inventory_color_factor(submeshes)
    vertex_color_factor = _external_inventory_vertex_color_factor(submeshes)
    vertex_alpha = _external_inventory_vertex_alpha(submeshes)
    emissive_color = _external_inventory_emissive_color(submeshes)
    classes = _classify_external_material(
        material_name=material_name,
        texture_slots=texture_slots,
        pbr_workflow=workflow,
        alpha_mode=alpha_mode,
        double_sided=double_sided,
        scalar_hints=scalar_hints,
        color_factor=color_factor,
        vertex_color_factor=vertex_color_factor,
        vertex_alpha=vertex_alpha,
        emissive_color=emissive_color,
    )
    return ExternalMaterialInventory(
        material_index=material_index,
        material_name=material_name,
        submesh_indices=submesh_indices,
        submesh_names=tuple(_dedupe_text([str(getattr(submesh, "name", "") or "") for submesh in submeshes])),
        sections=sections,
        texture_slots=texture_slots,
        pbr_workflow=workflow,
        alpha_mode=alpha_mode,
        double_sided=double_sided,
        scalar_hints=scalar_hints,
        color_factor=color_factor,
        vertex_color_factor=vertex_color_factor,
        vertex_alpha=vertex_alpha,
        emissive_color=emissive_color,
        material_classes=classes,
        warnings=_external_inventory_warnings(texture_slots, workflow, alpha_mode, classes),
    )


def _external_inventory_texture_slots(
    submeshes: Sequence[SubMesh],
    bindings: Sequence[ImportedMaterialBinding],
) -> tuple[ExternalMaterialTextureInventory, ...]:
    output: list[ExternalMaterialTextureInventory] = []
    seen: set[tuple[str, str, str]] = set()

    def add(slot: ExternalMaterialTextureInventory) -> None:
        key = (
            str(slot.slot_kind or "").strip().lower(),
            str(slot.parameter_name or "").strip().lower(),
            str(slot.texture_path or "").replace("\\", "/").lower(),
        )
        if not key[0] or not key[2] or key in seen:
            return
        seen.add(key)
        output.append(slot)

    for submesh in tuple(submeshes or ()):
        for texture_input in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()):
            if isinstance(texture_input, PreviewMaterialTextureInput):
                add(_external_texture_inventory_from_input(texture_input))
    for binding in tuple(bindings or ()):
        for slot_kind, path in tuple(getattr(binding, "texture_slots", ()) or ()):
            path_text = str(path or "").strip()
            if not path_text:
                continue
            add(_external_texture_inventory_from_path(str(slot_kind or ""), path_text, source="binding"))
    return tuple(sorted(output, key=lambda item: (item.slot_kind, item.semantic_subtype, item.texture_name.lower())))


def _external_material_section_inventory(
    section_pairs: Sequence[tuple[int, SubMesh]],
) -> tuple[ExternalMaterialSectionInventory, ...]:
    sections: list[ExternalMaterialSectionInventory] = []
    seen: set[int] = set()
    for section_index, submesh in tuple(section_pairs or ()):
        index = _safe_int(section_index, -1)
        if index in seen:
            continue
        seen.add(index)
        vertices = list(getattr(submesh, "vertices", ()) or ())
        faces = list(getattr(submesh, "faces", ()) or ())
        uvs = list(getattr(submesh, "uvs", ()) or ())
        normals = list(getattr(submesh, "normals", ()) or ())
        tangents = list(getattr(submesh, "tangents", ()) or ())
        bone_indices = list(getattr(submesh, "bone_indices", ()) or ())
        bone_weights = list(getattr(submesh, "bone_weights", ()) or ())
        bounds_min, bounds_max = _bbox(vertices)
        texcoord_sets = sorted(
            {
                _external_texture_input_texcoord(texture_input)
                for texture_input in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ())
                if isinstance(texture_input, PreviewMaterialTextureInput)
            }
        )
        sections.append(
            ExternalMaterialSectionInventory(
                section_index=index,
                section_name=str(getattr(submesh, "name", "") or ""),
                material_name=str(getattr(submesh, "material", "") or ""),
                vertex_count=len(vertices) or _safe_int(getattr(submesh, "vertex_count", 0), 0),
                face_count=len(faces) or _safe_int(getattr(submesh, "face_count", 0), 0),
                has_uvs=bool(uvs and (not vertices or len(uvs) == len(vertices))),
                has_normals=bool(normals and (not vertices or len(normals) == len(vertices))),
                has_tangents=bool(tangents and (not vertices or len(tangents) == len(vertices))),
                has_skinning=bool((bone_indices or bone_weights) and (not vertices or len(bone_indices) == len(vertices) or len(bone_weights) == len(vertices))),
                texture_texcoord_sets=tuple(texcoord_sets),
                bounds_min=tuple(round(float(value), 6) for value in bounds_min),
                bounds_max=tuple(round(float(value), 6) for value in bounds_max),
            )
        )
    return tuple(sections)


def _external_texture_inventory_from_input(texture_input: PreviewMaterialTextureInput) -> ExternalMaterialTextureInventory:
    path_text = str(
        getattr(texture_input, "preview_texture_path", "")
        or getattr(texture_input, "source_texture_path", "")
        or getattr(texture_input, "source_dds_path", "")
        or ""
    ).strip()
    slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
    parameter_name = str(getattr(texture_input, "parameter_name", "") or "").strip()
    semantic_type = str(getattr(texture_input, "semantic_type", "") or "").strip()
    semantic_subtype = str(getattr(texture_input, "semantic_subtype", "") or "").strip()
    packed_channels = tuple(str(value or "").strip().lower() for value in tuple(getattr(texture_input, "packed_channels", ()) or ()) if str(value or "").strip())
    texcoord = _external_texture_input_texcoord(texture_input)
    uv_transform = _external_texture_input_uv_transform(texture_input)
    resolution, channel_stats = _texture_image_facts(path_text)
    evidence = [
        f"slot:{slot_kind}",
        f"parameter:{parameter_name}" if parameter_name else "",
        f"semantic:{semantic_type}/{semantic_subtype}" if semantic_type or semantic_subtype else "",
        f"packed:{','.join(packed_channels)}" if packed_channels else "",
        f"texcoord:{texcoord}" if texcoord else "",
        "uv_transform" if uv_transform else "",
        _channel_stats_evidence(channel_stats),
        f"confidence:{getattr(texture_input, 'confidence', '')}" if str(getattr(texture_input, "confidence", "") or "").strip() else "",
    ]
    return ExternalMaterialTextureInventory(
        slot_kind=slot_kind,
        parameter_name=parameter_name,
        texture_path=path_text,
        texture_name=str(getattr(texture_input, "texture_name", "") or Path(path_text).name),
        image_format=Path(path_text).suffix.lower().lstrip("."),
        resolution=resolution,
        channel_stats=channel_stats,
        semantic_type=semantic_type,
        semantic_subtype=semantic_subtype,
        packed_channels=packed_channels,
        color_space=_external_slot_color_space(slot_kind, semantic_subtype, str(getattr(texture_input, "srgb_mode", "") or "")),
        texcoord=texcoord,
        uv_transform=uv_transform,
        source=_external_texture_input_source(texture_input),
        confidence=str(getattr(texture_input, "confidence", "") or ""),
        evidence=tuple(item for item in evidence if item),
    )


def _external_texture_inventory_from_path(slot_kind: str, path_text: str, *, source: str) -> ExternalMaterialTextureInventory:
    slot, semantic_type, semantic_subtype, packed_channels = _scene_slot_semantics(slot_kind)
    resolution, channel_stats = _texture_image_facts(path_text)
    return ExternalMaterialTextureInventory(
        slot_kind=slot,
        parameter_name=_SCENE_SLOT_PARAMETER_NAMES.get(slot_kind.strip().lower(), ""),
        texture_path=path_text,
        texture_name=Path(path_text).name,
        image_format=Path(path_text).suffix.lower().lstrip("."),
        resolution=resolution,
        channel_stats=channel_stats,
        semantic_type=semantic_type,
        semantic_subtype=semantic_subtype,
        packed_channels=packed_channels,
        color_space=_external_slot_color_space(slot, semantic_subtype, ""),
        texcoord=0,
        uv_transform=(),
        source=source,
        confidence="binding",
        evidence=tuple(item for item in (f"slot:{slot}", f"source:{source}", _channel_stats_evidence(channel_stats)) if item),
    )


def _external_texture_input_source(texture_input: PreviewMaterialTextureInput) -> str:
    for flag in tuple(getattr(texture_input, "blend_flags", ()) or ()):
        text = str(flag or "").strip()
        if text.startswith("source:"):
            return text.split(":", 1)[1]
    sidecar_kind = str(getattr(texture_input, "sidecar_kind", "") or "").strip()
    if sidecar_kind:
        return sidecar_kind
    return str(getattr(texture_input, "confidence", "") or "scene")


def _external_texture_input_texcoord(texture_input: PreviewMaterialTextureInput) -> int:
    for flag in tuple(getattr(texture_input, "blend_flags", ()) or ()):
        match = re.match(r"texcoord:(\d+)\s*$", str(flag or "").strip(), flags=re.IGNORECASE)
        if match:
            return max(0, _safe_int(match.group(1), 0))
    for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
        name = str(getattr(parameter, "parameter_name", "") or "")
        if "_gltfTexCoord" not in name:
            continue
        value = getattr(parameter, "numeric_value", None)
        if value is None:
            value = getattr(parameter, "value", 0)
        return max(0, _safe_int(value, 0))
    return 0


def _external_texture_input_uv_transform(texture_input: PreviewMaterialTextureInput) -> tuple[float, ...]:
    for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
        name = str(getattr(parameter, "parameter_name", "") or "")
        if "_gltfTextureTransform" not in name:
            continue
        raw_values = re.split(r"[\s,]+", str(getattr(parameter, "value", "") or "").strip())
        try:
            values = tuple(float(value) for value in raw_values if value)
        except (TypeError, ValueError, OverflowError):
            return ()
        return tuple(round(float(value), 6) for value in values[:5]) if len(values) >= 5 else ()
    return ()


def _texture_image_facts(path_text: str) -> tuple[tuple[int, int], tuple[tuple[str, float], ...]]:
    if not str(path_text or "").strip():
        return (), ()
    try:
        from PIL import Image, ImageStat

        previous_max_pixels = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = None
            with Image.open(path_text) as image:
                resolution = (int(image.width), int(image.height))
                if int(image.width) * int(image.height) > _SCENE_TEXTURE_FACT_CHANNEL_STATS_MAX_PIXELS:
                    return resolution, ()
                rgba = image.convert("RGBA")
        finally:
            Image.MAX_IMAGE_PIXELS = previous_max_pixels
        try:
            if max(rgba.size or (0, 0)) > 64:
                rgba.thumbnail((64, 64))
            stat = ImageStat.Stat(rgba)
            means = [max(0.0, min(1.0, float(value) / 255.0)) for value in stat.mean[:4]]
            extrema = rgba.getextrema()
            alpha_min = max(0.0, min(1.0, float(extrema[3][0]) / 255.0))
            alpha_max = max(0.0, min(1.0, float(extrema[3][1]) / 255.0))
            luma = max(0.0, min(1.0, 0.2126 * means[0] + 0.7152 * means[1] + 0.0722 * means[2]))
            return resolution, (
                ("r_mean", round(means[0], 4)),
                ("g_mean", round(means[1], 4)),
                ("b_mean", round(means[2], 4)),
                ("a_mean", round(means[3], 4)),
                ("a_min", round(alpha_min, 4)),
                ("a_max", round(alpha_max, 4)),
                ("luma_mean", round(luma, 4)),
            )
        finally:
            try:
                rgba.close()
            except Exception:
                pass
    except Exception:
        return (), ()


def _texture_resolution(path_text: str) -> tuple[int, int]:
    resolution, _stats = _texture_image_facts(path_text)
    return resolution


def _channel_stats_evidence(channel_stats: Sequence[tuple[str, float]]) -> str:
    stats = {str(key): float(value) for key, value in tuple(channel_stats or ())}
    if not stats:
        return ""
    return (
        "channels:"
        f"r={stats.get('r_mean', 0.0):.2f},"
        f"g={stats.get('g_mean', 0.0):.2f},"
        f"b={stats.get('b_mean', 0.0):.2f},"
        f"a={stats.get('a_mean', 0.0):.2f}"
    )


def _external_slot_color_space(slot_kind: str, semantic_subtype: str, srgb_mode: str) -> str:
    mode = str(srgb_mode or "").strip().lower()
    if mode in {"srgb", "s_rgb", "true", "1", "yes"}:
        return "srgb"
    if mode in {"linear", "false", "0", "no"}:
        return "linear"
    slot = str(slot_kind or "").strip().lower()
    subtype = str(semantic_subtype or "").strip().lower()
    if slot in {"base", "emissive"} or subtype in {"albedo", "emissive", "specular"}:
        return "srgb"
    return "linear"


def _normalize_external_pbr_workflow(value: object) -> str:
    text = str(value or "").strip()
    compact = re.sub(r"[^a-z0-9]+", "", text.lower())
    if compact in {"metallicroughness", "metalnessroughness", "pbrmetallicroughness"}:
        return "metallic_roughness"
    if compact in {"specularglossiness", "specgloss", "pbrspecularglossiness"}:
        return "specular_glossiness"
    if compact == "unlit":
        return "unlit"
    return text


def _external_inventory_workflow_from_slots(
    slots: Sequence[ExternalMaterialTextureInventory],
    scalar_hints: Sequence[tuple[str, float]] = (),
) -> str:
    subtypes = {str(slot.semantic_subtype or "").strip().lower() for slot in tuple(slots or ())}
    kinds = {str(slot.slot_kind or "").strip().lower() for slot in tuple(slots or ())}
    scalar_keys = {str(key or "").strip().lower() for key, _value in tuple(scalar_hints or ())}
    if "specular_glossiness" in subtypes or {"specular", "glossiness"} <= kinds:
        return "specular_glossiness"
    if {"specular", "glossiness"} <= scalar_keys and "metalness" not in scalar_keys:
        return "specular_glossiness"
    if "metallic_roughness" in subtypes or "metalness" in kinds or "roughness" in kinds:
        return "metallic_roughness"
    if "metalness" in scalar_keys or "roughness" in scalar_keys:
        return "metallic_roughness"
    return ""


def _external_inventory_alpha_mode(
    submeshes: Sequence[SubMesh],
    bindings: Sequence[ImportedMaterialBinding],
) -> str:
    for binding in tuple(bindings or ()):
        alpha_mode = str(getattr(binding, "alpha_mode", "") or "").strip()
        if alpha_mode:
            return alpha_mode
    for submesh in tuple(submeshes or ()):
        alpha_mode = str(getattr(submesh, "preview_alpha_mode", "") or "").strip()
        if alpha_mode:
            return alpha_mode
    return ""


def _external_inventory_scalar_hints(submeshes: Sequence[SubMesh]) -> tuple[tuple[str, float], ...]:
    values: OrderedDict[str, float] = OrderedDict()
    for submesh in tuple(submeshes or ()):
        for parameter in tuple(getattr(submesh, "preview_material_parameters", ()) or ()):
            normalized = _normalized_material_scalar_name(getattr(parameter, "parameter_name", ""))
            if not normalized:
                continue
            numeric = getattr(parameter, "numeric_value", None)
            if numeric is None:
                numeric = _safe_float_or_none(getattr(parameter, "value", ""))
            else:
                numeric = _safe_float_or_none(numeric)
            if numeric is not None:
                values.setdefault(normalized, numeric)
        overrides = getattr(submesh, "preview_native_material_overrides", {}) or {}
        if isinstance(overrides, Mapping):
            for key, value in overrides.items():
                normalized = _normalized_material_scalar_name(key)
                if not normalized:
                    continue
                numeric = _safe_float_or_none(value)
                if numeric is not None:
                    values.setdefault(normalized, numeric)
        for texture_input in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()):
            if not isinstance(texture_input, PreviewMaterialTextureInput):
                continue
            for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
                normalized = _normalized_material_scalar_name(getattr(parameter, "parameter_name", ""))
                if not normalized:
                    continue
                numeric = getattr(parameter, "numeric_value", None)
                if numeric is None:
                    numeric = _safe_float_or_none(getattr(parameter, "value", ""))
                else:
                    numeric = _safe_float_or_none(numeric)
                if numeric is not None:
                    values.setdefault(normalized, numeric)
    return tuple(values.items())


def _safe_float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


def _normalized_material_scalar_name(value: object) -> str:
    key = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    if "roughness" in key:
        return "roughness"
    if "metallic" in key or "metalness" in key:
        return "metalness"
    if "glossiness" in key or key == "gloss":
        return "glossiness"
    if "specular" in key:
        return "specular"
    if "emissiveintensity" in key or key == "emissive":
        return "emissive_intensity"
    if "transmission" in key or "thickness" in key or "attenuation" in key:
        return "transmission"
    if "alphacutoff" in key or "alphathreshold" in key:
        return "alpha_cutoff"
    if "clearcoat" in key:
        return "clearcoat"
    if key == "ior":
        return "ior"
    return ""


def _external_inventory_color_factor(submeshes: Sequence[SubMesh]) -> tuple[float, float, float]:
    for submesh in tuple(submeshes or ()):
        for attr_name in ("preview_texture_tint", "preview_color"):
            values = tuple(getattr(submesh, attr_name, ()) or ())
            if len(values) >= 3:
                try:
                    return tuple(max(0.0, min(1.0, float(value))) for value in values[:3])  # type: ignore[return-value]
                except (TypeError, ValueError, OverflowError):
                    continue
    return ()


def _external_inventory_vertex_color_factor(submeshes: Sequence[SubMesh]) -> tuple[float, float, float]:
    for submesh in tuple(submeshes or ()):
        values = tuple(getattr(submesh, "preview_vertex_color_mean", ()) or ())
        if len(values) >= 3:
            try:
                return tuple(max(0.0, min(1.0, float(value))) for value in values[:3])  # type: ignore[return-value]
            except (TypeError, ValueError, OverflowError):
                continue
    return ()


def _external_inventory_vertex_alpha(submeshes: Sequence[SubMesh]) -> tuple[float, float]:
    for submesh in tuple(submeshes or ()):
        mean_value = getattr(submesh, "preview_vertex_alpha_mean", None)
        min_value = getattr(submesh, "preview_vertex_alpha_min", None)
        if mean_value is None and min_value is None:
            continue
        try:
            alpha_mean = max(0.0, min(1.0, float(1.0 if mean_value is None else mean_value)))
            alpha_min = max(0.0, min(1.0, float(alpha_mean if min_value is None else min_value)))
            return (alpha_mean, alpha_min)
        except (TypeError, ValueError, OverflowError):
            continue
    return ()


def _external_inventory_emissive_color(submeshes: Sequence[SubMesh]) -> tuple[float, float, float]:
    for submesh in tuple(submeshes or ()):
        overrides = getattr(submesh, "preview_native_material_overrides", {}) or {}
        if isinstance(overrides, Mapping):
            color = _hex_color_to_rgb(overrides.get("emissive_color"))
            if color:
                return color
        for texture_input in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()):
            if not isinstance(texture_input, PreviewMaterialTextureInput):
                continue
            for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
                key = re.sub(r"[^a-z0-9]+", "", str(getattr(parameter, "parameter_name", "") or "").lower())
                if "emissivecolor" not in key:
                    continue
                color = tuple(getattr(parameter, "color_value", ()) or ())
                if len(color) >= 3:
                    try:
                        return tuple(max(0.0, min(1.0, float(value))) for value in color[:3])  # type: ignore[return-value]
                    except (TypeError, ValueError, OverflowError):
                        pass
                color = _hex_color_to_rgb(getattr(parameter, "value", ""))
                if color:
                    return color
    return ()


def _hex_color_to_rgb(value: object) -> tuple[float, float, float]:
    text = str(value or "").strip().lstrip("#")
    if len(text) < 6:
        return ()
    try:
        return (int(text[0:2], 16) / 255.0, int(text[2:4], 16) / 255.0, int(text[4:6], 16) / 255.0)
    except ValueError:
        return ()


def _classify_external_material(
    *,
    material_name: str,
    texture_slots: Sequence[ExternalMaterialTextureInventory],
    pbr_workflow: str,
    alpha_mode: str,
    double_sided: bool,
    scalar_hints: Sequence[tuple[str, float]],
    color_factor: Sequence[float],
    vertex_color_factor: Sequence[float],
    vertex_alpha: Sequence[float],
    emissive_color: Sequence[float],
) -> tuple[ExternalMaterialClassEvidence, ...]:
    evidence_by_class: dict[str, list[str]] = defaultdict(list)
    scores: dict[str, float] = defaultdict(float)
    raw_text = " ".join(
        [material_name]
        + [_material_class_texture_token_text(slot.texture_name) for slot in tuple(texture_slots or ())]
    )
    split_text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw_text)
    text = split_text.lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    compact_tokens = {
        re.sub(r"[^a-z0-9]+", "", token)
        for token in re.split(r"[\s._/\-\\]+", raw_text.lower())
        if re.sub(r"[^a-z0-9]+", "", token)
    }
    tokens.update(compact_tokens)
    scalar_map = {str(key): float(value) for key, value in tuple(scalar_hints or ())}
    slot_kinds = {str(slot.slot_kind or "").strip().lower() for slot in tuple(texture_slots or ())}
    slot_subtypes = {str(slot.semantic_subtype or "").strip().lower() for slot in tuple(texture_slots or ())}
    slots = tuple(texture_slots or ())

    def slot_stats(slot: ExternalMaterialTextureInventory) -> dict[str, float]:
        return {str(key): float(value) for key, value in tuple(getattr(slot, "channel_stats", ()) or ())}

    def first_stats_for(*slot_names: str) -> dict[str, float]:
        wanted = {str(name or "").strip().lower() for name in slot_names if str(name or "").strip()}
        for slot in slots:
            if (
                str(slot.slot_kind or "").strip().lower() in wanted
                or str(slot.semantic_subtype or "").strip().lower() in wanted
            ):
                stats = slot_stats(slot)
                if stats:
                    return stats
        return {}

    def add(material_class: str, amount: float, reason: str) -> None:
        if amount <= 0.0:
            return
        scores[material_class] += amount
        if reason not in evidence_by_class[material_class]:
            evidence_by_class[material_class].append(reason)

    def has_any(*terms: str) -> bool:
        wanted = {str(term or "").strip().lower() for term in terms if str(term or "").strip()}
        if tokens & wanted:
            return True
        for token in tokens:
            for term in wanted:
                if len(term) >= 5 and (token.startswith(term) or token.endswith(term)):
                    return True
        return False

    metalness = float(scalar_map.get("metalness", 0.0) or 0.0)
    roughness = float(scalar_map.get("roughness", 0.0) or 0.0)
    if metalness >= 0.5:
        add("metal", 0.55 + min(0.25, metalness * 0.25), f"metallic factor {metalness:.2f}")
    material_stats = first_stats_for("material", "metallic_roughness")
    metallic_channel = material_stats.get("b_mean")
    if metallic_channel is not None and "metallic_roughness" in slot_subtypes:
        if metallic_channel >= 0.45:
            add("metal", 0.35 + min(0.25, metallic_channel * 0.25), f"metallic-roughness B channel mean {metallic_channel:.2f}")
    metalness_stats = first_stats_for("metalness", "metallic")
    metalness_luma = metalness_stats.get("luma_mean")
    if metalness_luma is not None and metalness_luma >= 0.45:
        add("metal", 0.35 + min(0.25, metalness_luma * 0.25), f"metalness texture mean {metalness_luma:.2f}")
    if has_any("metal", "steel", "iron", "silver", "chrome", "blade", "sword", "armor", "armour"):
        add("metal", 0.35, "metal material/name token")
    if has_any("painted", "paint", "paintjob", "coated", "enamel") and (metalness >= 0.2 or "metal" in scores):
        add("painted_metal", 0.70, "painted/coated token with metal evidence")

    rgb = tuple(float(value) for value in tuple(color_factor or ())[:3]) if len(tuple(color_factor or ())) >= 3 else ()
    rgb_source = "base factor"
    base_stats = first_stats_for("base", "albedo")
    if base_stats and (not rgb or all(abs(value - 1.0) <= 1e-6 for value in rgb)):
        if {"r_mean", "g_mean", "b_mean"} <= set(base_stats):
            rgb = (base_stats["r_mean"], base_stats["g_mean"], base_stats["b_mean"])
            rgb_source = "base texture mean"
    vertex_rgb = (
        tuple(float(value) for value in tuple(vertex_color_factor or ())[:3])
        if len(tuple(vertex_color_factor or ())) >= 3
        else ()
    )
    if vertex_rgb and (not rgb or all(abs(value - 1.0) <= 1e-6 for value in rgb)):
        rgb = vertex_rgb
        rgb_source = "vertex color mean"
    if has_any("gold", "gilded"):
        add("gold", 0.90, "gold material/name token")
    if has_any("bronze", "brass"):
        add("bronze", 0.88, "bronze/brass material/name token")
    if has_any("copper"):
        add("copper", 0.88, "copper material/name token")
    if rgb and (metalness >= 0.35 or scores.get("metal", 0.0) >= 0.35):
        r, g, b = rgb
        if r >= 0.65 and g >= 0.45 and b <= 0.38:
            add("gold", 0.60, f"metallic yellow {rgb_source} {r:.2f},{g:.2f},{b:.2f}")
        elif r >= 0.55 and 0.20 <= g <= 0.55 and b <= 0.35:
            add("copper", 0.50, f"warm metallic {rgb_source} {r:.2f},{g:.2f},{b:.2f}")
        elif r >= 0.45 and g >= 0.25 and b <= 0.30:
            add("bronze", 0.45, f"bronze-like metallic {rgb_source} {r:.2f},{g:.2f},{b:.2f}")

    if has_any("cloth", "fabric", "linen", "cotton", "canvas", "textile", "garment"):
        add("cloth", 0.80, "cloth/fabric material/name token")
    if double_sided and has_any("cloth", "fabric", "linen", "cotton", "canvas", "textile", "garment", "cape", "flag"):
        add("cloth", 0.18, "double-sided fabric surface")
    if has_any("leather", "hide", "suede"):
        add("leather", 0.85, "leather material/name token")
    if has_any("wood", "wooden", "timber", "oak", "pine", "walnut", "bark"):
        add("wood", 0.85, "wood material/name token")
    if has_any("stone", "rock", "granite", "marble", "concrete", "slate", "ceramic"):
        add("stone", 0.85, "stone/rock material/name token")
    if has_any("skin", "organic", "flesh", "body", "face", "hand", "arm", "leg", "head"):
        add("skin_organic", 0.82, "skin/organic material/name token")
    if rgb and metalness < 0.2:
        r, g, b = rgb
        spread = max(rgb) - min(rgb)
        if r >= 0.22 and g >= 0.12 and b <= 0.18 and r >= g >= b:
            if roughness >= 0.55:
                add("leather", 0.28, f"rough warm brown {rgb_source} {r:.2f},{g:.2f},{b:.2f}")
            add("wood", 0.24, f"warm brown {rgb_source} {r:.2f},{g:.2f},{b:.2f}")
        if spread <= 0.12 and 0.20 <= max(rgb) <= 0.75 and roughness >= 0.45:
            add("stone", 0.22, f"rough neutral {rgb_source} {r:.2f},{g:.2f},{b:.2f}")

    alpha_text = str(alpha_mode or "").strip().upper()
    transmission = float(scalar_map.get("transmission", 0.0) or 0.0)
    if has_any("glass", "crystal", "gem", "lens", "transparent", "translucent", "transmission"):
        add("glass_crystal", 0.86, "glass/crystal material/name token")
    if transmission > 0.0 or "transmission" in slot_subtypes:
        add("glass_crystal", 0.62, f"transmission evidence {transmission:.2f}")
    if alpha_text in {"BLEND", "MASK"} or "opacity" in slot_kinds:
        add("glass_crystal", 0.24, f"alpha mode {alpha_text or 'opacity texture'}")
    alpha_stats = first_stats_for("base", "opacity")
    if alpha_stats.get("a_min", 1.0) < 0.98 or alpha_stats.get("a_mean", 1.0) < 0.98:
        add(
            "glass_crystal",
            0.22,
            f"source alpha channel mean {alpha_stats.get('a_mean', 1.0):.2f} min {alpha_stats.get('a_min', 1.0):.2f}",
        )
    vertex_alpha_values = tuple(float(value) for value in tuple(vertex_alpha or ())[:2]) if len(tuple(vertex_alpha or ())) >= 2 else ()
    if vertex_alpha_values and (vertex_alpha_values[0] < 0.98 or vertex_alpha_values[1] < 0.98):
        add(
            "glass_crystal",
            0.16,
            f"vertex alpha mean {vertex_alpha_values[0]:.2f} min {vertex_alpha_values[1]:.2f}",
        )

    emissive_intensity = float(scalar_map.get("emissive_intensity", 0.0) or 0.0)
    emissive_stats = first_stats_for("emissive")
    if "emissive" in slot_kinds or emissive_intensity > 0.0 or len(tuple(emissive_color or ())) >= 3 or emissive_stats.get("luma_mean", 0.0) > 0.03:
        reasons = []
        if "emissive" in slot_kinds:
            reasons.append("emissive texture slot")
        if emissive_intensity > 0.0:
            reasons.append(f"emissive intensity {emissive_intensity:.2f}")
        if len(tuple(emissive_color or ())) >= 3:
            reasons.append("emissive color factor")
        if emissive_stats.get("luma_mean", 0.0) > 0.03:
            reasons.append(f"emissive texture luma {emissive_stats.get('luma_mean', 0.0):.2f}")
        add("emissive", 0.90, ", ".join(reasons))

    if not scores:
        return (
            ExternalMaterialClassEvidence(
                material_class="unknown",
                confidence=0.0,
                evidence=("no decisive material-class evidence",),
            ),
        )
    results = [
        ExternalMaterialClassEvidence(
            material_class=material_class,
            confidence=max(0.0, min(1.0, score)),
            evidence=tuple(evidence_by_class.get(material_class, ())),
        )
        for material_class, score in scores.items()
    ]
    return tuple(sorted(results, key=lambda item: (-item.confidence, item.material_class)))


def _material_class_texture_token_text(texture_name: object) -> str:
    stem = PurePosixPath(str(texture_name or "").replace("\\", "/")).stem
    if not stem:
        return ""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", stem).lower()
    for token in _MATERIAL_CLASS_TEXTURE_ROLE_TOKENS:
        text = re.sub(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", " ", text)
    return text


def _external_inventory_warnings(
    texture_slots: Sequence[ExternalMaterialTextureInventory],
    workflow: str,
    alpha_mode: str,
    material_classes: Sequence[ExternalMaterialClassEvidence],
) -> tuple[str, ...]:
    warnings: list[str] = []
    slot_kinds = {str(slot.slot_kind or "").strip().lower() for slot in tuple(texture_slots or ())}
    if texture_slots and "base" not in slot_kinds:
        warnings.append("Material has support textures but no explicit base/albedo slot.")
    if workflow == "specular_glossiness" and "material" in slot_kinds and "roughness" not in slot_kinds:
        warnings.append("Specular-glossiness workflow needs conversion before Crimson metallic/roughness export.")
    if str(alpha_mode or "").strip().upper() in {"MASK", "BLEND"} and "opacity" not in slot_kinds:
        warnings.append("Alpha mode is active without a separate opacity texture; base alpha must be preserved.")
    if material_classes and material_classes[0].material_class == "unknown":
        warnings.append("Material class is ambiguous; keep evidence in the authority report.")
    return tuple(warnings)


def _aggregate_external_material_classes(
    inventory: Sequence[ExternalMaterialInventory],
) -> tuple[ExternalMaterialClassEvidence, ...]:
    by_class: dict[str, ExternalMaterialClassEvidence] = {}
    for material in tuple(inventory or ()):
        for item in tuple(material.material_classes or ()):
            current = by_class.get(item.material_class)
            if current is None or item.confidence > current.confidence:
                by_class[item.material_class] = item
    return tuple(sorted(by_class.values(), key=lambda item: (-item.confidence, item.material_class)))


def _mesh_extent(mesh: ParsedMesh) -> tuple[float, float, float]:
    vertices = [vertex for submesh in tuple(getattr(mesh, "submeshes", ()) or ()) for vertex in tuple(getattr(submesh, "vertices", ()) or ())]
    if not vertices:
        return (0.0, 0.0, 0.0)
    xs = [float(vertex[0]) for vertex in vertices]
    ys = [float(vertex[1]) for vertex in vertices]
    zs = [float(vertex[2]) for vertex in vertices]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def _audit_texture_slot_from_path(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    if any(token in stem for token in ("basecolor", "basecolour", "albedo", "diffuse", "color", "colour")):
        return "base"
    if any(token in stem for token in ("normal", "normalmap", "nrm")):
        return "normal"
    if any(token in stem for token in ("metallicroughness", "roughnessmetallic", "metalrough")):
        return "roughness"
    if "roughness" in stem:
        return "roughness"
    if any(token in stem for token in ("metallic", "metalness")):
        return "metallic"
    if any(token in stem for token in ("specularglossiness", "specular", "glossiness")):
        return "specular"
    if any(token in stem for token in ("emissive", "emission", "glow")):
        return "emissive"
    if any(token in stem for token in ("height", "displacement", "bump")):
        return "height"
    if any(token in stem for token in ("ao", "occlusion")):
        return "ao"
    return ""


def _visible_texture_score(path: Path) -> int:
    stem = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    if any(
        token in stem
        for token in (
            "normal",
            "normalmap",
            "nrm",
            "roughness",
            "metallic",
            "height",
            "displacement",
            "ambientocclusion",
            "mixedao",
            "occlusion",
            "emissive",
            "emission",
        )
    ):
        return 0
    if any(token in stem for token in ("basecolor", "basecolour", "basecol")):
        return 100
    if any(token in stem for token in ("albedo", "diffuse")):
        return 90
    if any(token in stem for token in ("color", "colour", "base")):
        return 80
    return 45


def _attach_fallback_texture_references(mesh: ParsedMesh, texture_files: Sequence[Path]) -> None:
    """Attach colocated texture-folder images to unreferenced scene submeshes when safe."""
    if not isinstance(mesh, ParsedMesh):
        return
    submeshes = [submesh for submesh in getattr(mesh, "submeshes", ()) or () if getattr(submesh, "vertices", None) and getattr(submesh, "faces", None)]
    if not submeshes:
        return
    if all(str(getattr(submesh, "texture", "") or "").strip() for submesh in submeshes):
        return
    visible_textures = sorted(
        (path for path in tuple(texture_files or ()) if isinstance(path, Path) and path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS),
        key=lambda path: (_visible_texture_score(path), -len(path.name)),
        reverse=True,
    )
    visible_textures = [path for path in visible_textures if _visible_texture_score(path) > 0]
    if not visible_textures:
        return
    if len(visible_textures) == 1:
        texture_name = visible_textures[0].name
    else:
        best_score = _visible_texture_score(visible_textures[0])
        second_score = _visible_texture_score(visible_textures[1])
        if best_score < 80 or best_score <= second_score:
            return
        texture_name = visible_textures[0].name
    for submesh in submeshes:
        if not str(getattr(submesh, "texture", "") or "").strip():
            submesh.texture = texture_name


def _scene_texture_fallback_slot_kind(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    if any(token in stem for token in ("basecolor", "basecolour", "albedo", "diffuse", "diffusemap", "colormap")):
        return "base"
    if any(token in stem for token in ("normalmap", "normalgl", "normaldx", "normal", "nrm")):
        return "normal"
    if any(token in stem for token in ("heightmap", "height", "displacement", "disp", "depth", "bump")):
        return "height"
    if any(token in stem for token in ("emissive", "emission", "glow", "illumination", "illum")):
        return "emissive"
    if any(token in stem for token in ("specularglossiness", "specgloss", "speculargloss")):
        return "specular_glossiness"
    if "glossiness" in stem or "gloss" in stem:
        return "glossiness"
    if any(token in stem for token in ("metallicroughness", "roughnessmetallic", "metalrough", "metallicrough")):
        return "material"
    if "roughness" in stem or "rough" in stem:
        return "roughness"
    if any(token in stem for token in ("metallic", "metalness", "metal")):
        return "metalness"
    if any(token in stem for token in ("ambientocclusion", "occlusion", "mixedao")) or stem.endswith("ao"):
        return "occlusion"
    if "specular" in stem or stem.endswith("spec"):
        return "specular"
    if any(token in stem for token in ("opacity", "alpha", "transparent")):
        return "opacity"
    return ""


def _scene_texture_group_key(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    for token in (
        "metallicroughness",
        "roughnessmetallic",
        "occlusionroughnessmetallic",
        "specularglossiness",
        "basecolor",
        "basecolour",
        "diffusemap",
        "diffuse",
        "albedo",
        "colormap",
        "normalmap",
        "normalgl",
        "normaldx",
        "normal",
        "nrm",
        "heightmap",
        "height",
        "displacement",
        "disp",
        "depth",
        "ambientocclusion",
        "occlusion",
        "mixedao",
        "ao",
        "roughness",
        "rough",
        "metallic",
        "metalness",
        "metal",
        "glossiness",
        "gloss",
        "specular",
        "spec",
        "emissive",
        "emission",
        "glow",
        "illumination",
        "illum",
        "opacity",
        "alpha",
        "transparent",
        "base",
        "color",
        "colour",
    ):
        stem = stem.replace(token, "")
    return stem or re.sub(r"[^a-z0-9]+", "", path.stem.lower())


def _scene_texture_candidate_priority(path: Path) -> tuple[int, int]:
    suffix_priority = {
        ".png": 90,
        ".webp": 80,
        ".tga": 70,
        ".tif": 65,
        ".tiff": 65,
        ".dds": 60,
        ".bmp": 45,
        ".jpg": 35,
        ".jpeg": 35,
    }.get(path.suffix.lower(), 0)
    return (suffix_priority, -len(path.name))


def _resolve_scene_texture_path_reference(value: object, texture_files: Sequence[Path]) -> Optional[Path]:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_file():
        try:
            return candidate.resolve()
        except OSError:
            return candidate
    name = PurePosixPath(text).name.lower()
    stem = PurePosixPath(text).stem.lower()
    normalized = text.lower()
    for texture_path in tuple(texture_files or ()):
        try:
            resolved = texture_path.resolve()
        except OSError:
            resolved = texture_path
        path_text = resolved.as_posix().lower()
        if path_text == normalized or resolved.name.lower() == name or resolved.stem.lower() == stem:
            return resolved
    return None


def _attach_sibling_material_texture_slots(mesh: ParsedMesh, texture_files: Sequence[Path]) -> int:
    """Attach same-stem support maps when explicit material slots did not provide them."""
    if not isinstance(mesh, ParsedMesh):
        return 0
    candidate_files = list(texture_files or ())
    source_text = str(getattr(mesh, "path", "") or "").strip()
    source_path = Path(source_text) if source_text else None
    search_roots: list[Path] = []
    if source_path is not None:
        search_roots.extend([source_path.parent, source_path.parent / "textures", source_path.parent.parent / "textures"])
    for root in search_roots:
        if not root.is_dir():
            continue
        try:
            candidate_files.extend(
                path
                for path in root.iterdir()
                if path.is_file() and path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS
            )
        except OSError:
            continue
    candidate_files = _dedupe_paths([path for path in candidate_files if isinstance(path, Path)])
    texture_paths = tuple(
        path.resolve()
        for path in tuple(candidate_files or ())
        if isinstance(path, Path) and path.is_file() and path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS
    )
    if not texture_paths:
        return 0
    grouped: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    for texture_path in texture_paths:
        slot_kind = _scene_texture_fallback_slot_kind(texture_path)
        if not slot_kind:
            continue
        grouped[_scene_texture_group_key(texture_path)][slot_kind].append(texture_path)
    for group in grouped.values():
        for candidates in group.values():
            candidates.sort(key=_scene_texture_candidate_priority, reverse=True)

    attached = 0
    support_order = (
        "normal",
        "material",
        "occlusion",
        "roughness",
        "metalness",
        "specular_glossiness",
        "specular",
        "glossiness",
        "emissive",
        "height",
        "opacity",
    )
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        base_path = _resolve_scene_texture_path_reference(
            str(getattr(submesh, "preview_texture_path", "") or "") or str(getattr(submesh, "texture", "") or ""),
            texture_paths,
        )
        if base_path is None:
            continue
        base_path_text = base_path.as_posix()
        if not str(getattr(submesh, "preview_texture_path", "") or "").strip():
            submesh.preview_texture_path = base_path_text
            submesh.preview_texture_name = base_path.name
        if not str(getattr(submesh, "texture", "") or "").strip():
            submesh.texture = base_path_text
        sibling_group = grouped.get(_scene_texture_group_key(base_path), {})
        if not sibling_group:
            continue
        existing = tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ())
        existing_keys = {
            (
                str(getattr(item, "slot_kind", "") or "").strip().lower(),
                str(getattr(item, "semantic_subtype", "") or "").strip().lower(),
            )
            for item in existing
        }
        slots: list[SceneMaterialTextureSlot] = []
        for slot_kind in support_order:
            candidates = tuple(sibling_group.get(slot_kind, ()) or ())
            if not candidates:
                continue
            semantic_slot, _semantic_type, semantic_subtype, _channels = _scene_slot_semantics(slot_kind)
            if (semantic_slot, semantic_subtype) in existing_keys:
                continue
            if slot_kind == "normal" and str(getattr(submesh, "preview_normal_texture_path", "") or "").strip():
                continue
            if slot_kind == "height" and str(getattr(submesh, "preview_height_texture_path", "") or "").strip():
                continue
            if slot_kind in {"material", "roughness", "metalness", "specular_glossiness", "specular", "glossiness", "occlusion"}:
                material_subtype = str(getattr(submesh, "preview_material_texture_subtype", "") or "").strip().lower()
                if material_subtype and semantic_subtype == material_subtype:
                    continue
            slots.append(
                _scene_material_slot(
                    slot_kind,
                    candidates[0].as_posix(),
                    source="filename",
                )
            )
        if not slots:
            continue
        before_count = len(tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()))
        _apply_scene_material_slots_to_submesh(submesh, slots, confidence="filename")
        after_count = len(tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()))
        attached += max(0, after_count - before_count)
    return attached


def import_gltf(path: str | Path) -> SceneImportResult:
    source_path = Path(path).expanduser().resolve()
    payload = _load_gltf_payload(source_path)
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
    submeshes: list[SubMesh] = []
    material_bindings: list[ImportedMaterialBinding] = []
    mesh_instances = _iter_gltf_mesh_instances(payload.document)
    if not mesh_instances:
        mesh_instances = [
            _GltfMeshInstance(index, _identity_matrix(), "")
            for index, _mesh in enumerate(payload.document.get("meshes", []) or [])
        ]
    skin_matrix_cache: dict[tuple[int, int], tuple[tuple[float, ...], ...]] = {}
    baked_skin_primitive_count = 0
    for instance in mesh_instances:
        mesh_index = instance.mesh_index
        transform = instance.transform
        node_name = instance.node_name
        gltf_meshes = payload.document.get("meshes", []) or []
        if mesh_index < 0 or mesh_index >= len(gltf_meshes):
            continue
        mesh_entry = gltf_meshes[mesh_index]
        mesh_name = str(mesh_entry.get("name", "") or "")
        for primitive_index, primitive in enumerate(mesh_entry.get("primitives", []) or []):
            if not isinstance(primitive, dict):
                continue
            mode = int(primitive.get("mode", 4) or 4)
            if mode != 4:
                payload.diagnostics.append(
                    f"Skipped glTF primitive {mesh_name or mesh_index}:{primitive_index} because only TRIANGLES mode is supported."
                )
                continue
            attributes = primitive.get("attributes", {})
            if not isinstance(attributes, dict) or "POSITION" not in attributes:
                payload.diagnostics.append(
                    f"Skipped glTF primitive {mesh_name or mesh_index}:{primitive_index} because it has no POSITION attribute."
                )
                continue
            material_index = _safe_int(primitive.get("material"), -1)
            material_name = (material_names.get(material_index, "") or f"material_{material_index}") if material_index >= 0 else ""
            texture_path = material_textures.get(material_index, "")
            submesh = _parse_gltf_primitive(
                payload,
                primitive,
                name=node_name or mesh_name or f"mesh_{mesh_index}_{primitive_index}",
                material=material_name or node_name or mesh_name or f"mesh_{mesh_index}_{primitive_index}",
                texture=texture_path,
                texcoord_index=_gltf_material_texcoord_index(material_texture_slots, material_index),
            )
            skin_matrices: tuple[tuple[float, ...], ...] = ()
            if instance.skin_index >= 0 and instance.node_index >= 0:
                cache_key = (instance.node_index, instance.skin_index)
                skin_matrices = skin_matrix_cache.get(cache_key, ())
                if cache_key not in skin_matrix_cache:
                    skin_matrices = _gltf_skin_joint_matrices(
                        payload,
                        node_index=instance.node_index,
                        skin_index=instance.skin_index,
                    )
                    skin_matrix_cache[cache_key] = skin_matrices
            if skin_matrices and _bake_gltf_skin_primitive(payload, primitive, submesh, skin_matrices):
                baked_skin_primitive_count += 1
            if not submesh.faces:
                payload.diagnostics.append(
                    f"Skipped glTF primitive {mesh_name or mesh_index}:{primitive_index} because it produced no triangle faces."
                )
                continue
            copied = _copy_submesh_with_transform(submesh, transform)
            copied.name = submesh.name
            copied.material = submesh.material
            copied.texture = submesh.texture
            _apply_gltf_preview_material_metadata(
                copied,
                material_index,
                material_colors=material_colors,
                material_texture_slots=material_texture_slots,
                material_flags=material_flags,
                material_preview_parameters=material_preview_parameters,
            )
            submeshes.append(copied)
            slots = tuple(
                (str(slot_kind), Path(str(slot.path)).expanduser())
                for slot_kind, slot in sorted(material_texture_slots.get(material_index, {}).items())
                if isinstance(slot, SceneMaterialTextureSlot) and str(slot.path or "").strip()
            )
            flags = material_flags.get(material_index, {})
            material_bindings.append(
                ImportedMaterialBinding(
                    material_index=material_index,
                    material_name=material_name or copied.material,
                    submesh_index=len(submeshes) - 1,
                    submesh_name=copied.name,
                    texture_slots=slots,
                    pbr_workflow=str(material_workflows.get(material_index, "") or ""),
                    alpha_mode=str(flags.get("alpha_mode", "") or ""),
                    double_sided=bool(flags.get("double_sided", False)),
                )
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
        ),
    )


def import_dae(path: str | Path) -> ParsedMesh:
    dae_path = Path(path).expanduser().resolve()
    tree = ET.parse(dae_path)
    root = tree.getroot()
    ns_uri = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    ns = {"c": ns_uri} if ns_uri else {}
    prefix = "c:" if ns_uri else ""

    material_names = _collada_material_names(root, prefix, ns)
    material_texture_slots = _collada_material_texture_slots(root, prefix, ns, dae_path)
    material_parameters = _collada_material_parameters(root, prefix, ns)
    geometries: dict[str, _ColladaGeometry] = {}
    for geometry in root.findall(f".//{prefix}library_geometries/{prefix}geometry", ns):
        parsed = _parse_collada_geometry(geometry, material_names, prefix, ns)
        geometries[parsed.geometry_id] = parsed

    submeshes: list[SubMesh] = []
    for instance in _iter_collada_geometry_instances(root, prefix, ns):
        geometry = geometries.get(instance["geometry_id"])
        if geometry is None:
            continue
        transform = instance["matrix"]
        node_name = instance["node_name"]
        for primitive in geometry.primitives:
            material = instance["materials"].get(primitive.material, primitive.material)
            material = material_names.get(str(material), str(material))
            name = node_name or geometry.name or primitive.name or geometry.geometry_id
            copied = _copy_submesh_with_transform(primitive, transform)
            copied.name = name
            copied.material = material or primitive.material or name
            copied.texture = _guess_scene_material_texture(dae_path, copied.material)
            slots = (
                material_texture_slots.get(str(material))
                or material_texture_slots.get(str(copied.material))
                or material_texture_slots.get(str(primitive.material))
                or ()
            )
            parameters = (
                material_parameters.get(str(material))
                or material_parameters.get(str(copied.material))
                or material_parameters.get(str(primitive.material))
                or ()
            )
            if slots or parameters:
                _apply_scene_material_slots_to_submesh(copied, slots, material_parameters=parameters, confidence="dae")
            submeshes.append(copied)

    if not submeshes:
        for geometry in geometries.values():
            for primitive in geometry.primitives:
                copied = _copy_submesh_with_transform(primitive, _identity_matrix())
                copied.name = geometry.name or primitive.name or geometry.geometry_id
                copied.material = material_names.get(primitive.material, primitive.material) or copied.name
                copied.texture = _guess_scene_material_texture(dae_path, copied.material)
                slots = material_texture_slots.get(str(primitive.material)) or material_texture_slots.get(str(copied.material)) or ()
                parameters = material_parameters.get(str(primitive.material)) or material_parameters.get(str(copied.material)) or ()
                if slots or parameters:
                    _apply_scene_material_slots_to_submesh(copied, slots, material_parameters=parameters, confidence="dae")
                submeshes.append(copied)

    if not submeshes:
        raise ValueError(f"DAE import did not contain supported triangle/polylist geometry: {dae_path}")
    vertices = [vertex for submesh in submeshes for vertex in submesh.vertices]
    bbox_min, bbox_max = _bbox(vertices)
    return ParsedMesh(
        path=str(dae_path),
        format="dae",
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        submeshes=submeshes,
        total_vertices=sum(len(submesh.vertices) for submesh in submeshes),
        total_faces=sum(len(submesh.faces) for submesh in submeshes),
        has_uvs=any(submesh.uvs for submesh in submeshes),
        has_bones=False,
    )


def import_fbx(path: str | Path) -> ParsedMesh:
    fbx_path = Path(path).expanduser().resolve()
    raise ValueError(
        f"FBX import is disabled in this build because it required launching Blender: {fbx_path}. "
        "Export the model as OBJ or DAE first."
    )


def _obj_material_library_paths(obj_path: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    seen: set[str] = set()
    try:
        with obj_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or not line.lower().startswith("mtllib "):
                    continue
                for raw_value in line[7:].split():
                    candidate = (obj_path.parent / raw_value).expanduser().resolve()
                    key = str(candidate).lower()
                    if key not in seen:
                        seen.add(key)
                        candidates.append(candidate)
    except OSError:
        pass
    fallback = obj_path.with_suffix(".mtl").expanduser().resolve()
    if str(fallback).lower() not in seen:
        candidates.append(fallback)
    return tuple(candidates)


def _obj_material_texture_references(obj_path: Path) -> tuple[str, ...]:
    references: list[str] = []
    seen: set[str] = set()
    texture_keys = {
        "map_kd",
        "map_ka",
        "map_ks",
        "map_ke",
        "map_bump",
        "bump",
        "norm",
        "map_ns",
        "map_pr",
        "map_pm",
        "map_d",
        "map_tr",
        "disp",
        "map_pbr",
        "map_orm",
        "map_roughness",
        "map_metallic",
    }
    for material_path in _obj_material_library_paths(obj_path):
        if not material_path.is_file():
            continue
        try:
            with material_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 2 or parts[0].lower() not in texture_keys:
                        continue
                    reference = _obj_map_reference_from_parts(parts[1:])
                    if not reference:
                        continue
                    key = reference.replace("\\", "/").lower()
                    if reference and key not in seen:
                        seen.add(key)
                        references.append(reference)
        except OSError as exc:
            logger.warning("Failed to read OBJ material library %s: %s", material_path, exc)
    return tuple(references)


def _obj_map_reference_from_parts(parts: Sequence[str]) -> str:
    value_parts = list(parts)
    option_value_counts = {
        "-blendu": 1,
        "-blendv": 1,
        "-boost": 1,
        "-mm": 2,
        "-o": 3,
        "-s": 3,
        "-t": 3,
        "-texres": 1,
        "-clamp": 1,
        "-bm": 1,
        "-imfchan": 1,
        "-type": 1,
        "-cc": 1,
    }
    output: list[str] = []
    index = 0
    while index < len(value_parts):
        item = value_parts[index]
        if item.startswith("-"):
            skip = option_value_counts.get(item.lower(), 1)
            index += 1 + skip
            continue
        output.extend(value_parts[index:])
        break
    return " ".join(output).strip().strip('"')


def _obj_material_texture_slots(obj_path: Path) -> dict[str, tuple[SceneMaterialTextureSlot, ...]]:
    texture_kind_by_key = {
        "map_kd": "base",
        "map_ka": "base",
        "map_bump": "normal",
        "bump": "normal",
        "norm": "normal",
        "disp": "height",
        "map_ks": "specular",
        "map_ns": "glossiness",
        "map_pr": "roughness",
        "map_roughness": "roughness",
        "map_pm": "metalness",
        "map_metallic": "metalness",
        "map_ke": "emissive",
        "map_d": "opacity",
        "map_tr": "opacity",
        "map_orm": "material",
        "map_pbr": "material",
    }
    output: dict[str, list[SceneMaterialTextureSlot]] = {}
    for material_path in _obj_material_library_paths(obj_path):
        if not material_path.is_file():
            continue
        current_material = ""
        try:
            with material_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 1:
                        continue
                    key = parts[0].lower()
                    if key == "newmtl":
                        current_material = " ".join(parts[1:]).strip()
                        continue
                    if not current_material or key not in texture_kind_by_key or len(parts) < 2:
                        continue
                    reference = _obj_map_reference_from_parts(parts[1:])
                    if not reference:
                        continue
                    resolved = _resolve_local_texture_reference(obj_path, reference)
                    if resolved is None:
                        continue
                    slot_kind = texture_kind_by_key[key]
                    output.setdefault(current_material, []).append(
                        _scene_material_slot(
                            slot_kind,
                            resolved.as_posix(),
                            parameter_name={
                                "map_kd": "_objMapKd",
                                "map_ka": "_objMapKa",
                                "map_bump": "_objMapBump",
                                "bump": "_objBump",
                                "norm": "_objNormal",
                                "disp": "_objDisplacement",
                                "map_ks": "_objMapKs",
                                "map_ns": "_objMapNs",
                                "map_pr": "_objMapPr",
                                "map_roughness": "_objMapRoughness",
                                "map_pm": "_objMapPm",
                                "map_metallic": "_objMapMetallic",
                                "map_ke": "_objMapKe",
                                "map_d": "_objMapD",
                                "map_tr": "_objMapTr",
                                "map_orm": "_objMapOrm",
                                "map_pbr": "_objMapPbr",
                            }.get(key, ""),
                            source="obj_mtl",
                        )
                    )
        except OSError as exc:
            logger.warning("Failed to read OBJ material library %s: %s", material_path, exc)
            continue
    return {material: tuple(slots) for material, slots in output.items()}


def _obj_material_parameters(obj_path: Path) -> dict[str, tuple[PreviewMaterialParameterInput, ...]]:
    output: dict[str, list[PreviewMaterialParameterInput]] = {}

    def parse_float(parts: Sequence[str]) -> Optional[float]:
        if not parts:
            return None
        try:
            return float(parts[0])
        except (TypeError, ValueError, OverflowError):
            return None

    def parse_color(parts: Sequence[str]) -> tuple[float, float, float]:
        if len(parts) < 3:
            return ()
        try:
            return tuple(max(0.0, min(1.0, float(value))) for value in parts[:3])  # type: ignore[return-value]
        except (TypeError, ValueError, OverflowError):
            return ()

    def add_parameter(material: str, parameter: Optional[PreviewMaterialParameterInput]) -> None:
        if parameter is not None:
            output.setdefault(material, []).append(parameter)

    for material_path in _obj_material_library_paths(obj_path):
        if not material_path.is_file():
            continue
        current_material = ""
        try:
            with material_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if not parts:
                        continue
                    key = parts[0].lower()
                    values = parts[1:]
                    if key == "newmtl":
                        current_material = " ".join(values).strip()
                        continue
                    if not current_material:
                        continue
                    if key == "kd":
                        add_parameter(current_material, _scene_preview_color_parameter("_diffuseFactor", parse_color(values)))
                    elif key == "ks":
                        add_parameter(current_material, _scene_preview_color_parameter("_specularColorFactor", parse_color(values)))
                    elif key == "ke":
                        color = parse_color(values)
                        add_parameter(current_material, _scene_preview_color_parameter("_emissiveColor", color))
                        if color and any(component > 0.003 for component in color):
                            add_parameter(current_material, _scene_preview_float_parameter("_emissiveIntensity", 1.0))
                    elif key == "ns":
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_glossinessFactor", max(0.0, min(1.0, numeric / 1000.0))))
                    elif key in {"pr", "roughness"}:
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_roughnessFactor", max(0.0, min(1.0, numeric))))
                    elif key in {"pm", "metallic"}:
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_metallicFactor", max(0.0, min(1.0, numeric))))
                    elif key == "d":
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_alphaFactor", max(0.0, min(1.0, numeric))))
                    elif key == "tr":
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_alphaFactor", 1.0 - max(0.0, min(1.0, numeric))))
                    elif key == "ni":
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_ior", max(0.0, numeric)))
                    elif key == "illum":
                        add_parameter(current_material, _scene_preview_string_parameter("_objIlluminationModel", " ".join(values)))
        except OSError as exc:
            logger.warning("Failed to read OBJ material library %s: %s", material_path, exc)
            continue
    return {material: tuple(parameters) for material, parameters in output.items()}


def _obj_material_texture_paths(obj_path: Path) -> list[Path]:
    discovered: list[Path] = []
    for reference in _obj_material_texture_references(obj_path):
        resolved = _resolve_local_texture_reference(obj_path, reference)
        if resolved is not None:
            discovered.append(resolved)
    return discovered


def discover_scene_texture_files(path: str | Path, mesh: Optional[ParsedMesh] = None) -> tuple[Path, ...]:
    scene_path = Path(path).expanduser().resolve()
    discovered: list[Path] = []
    if scene_path.suffix.lower() == ".obj":
        discovered.extend(_obj_material_texture_paths(scene_path))
    elif scene_path.suffix.lower() == ".dae":
        discovered.extend(_collada_image_paths(scene_path))
    elif scene_path.suffix.lower() in {".gltf", ".glb"}:
        try:
            payload = _load_gltf_payload(scene_path)
            _gltf_material_info(payload)
            discovered.extend(payload.discovered_texture_files)
            discovered.extend(payload.extracted_embedded_files)
        except Exception as exc:
            logger.warning("Failed to discover glTF texture files for %s: %s", scene_path, exc)
    elif scene_path.suffix.lower() in LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS:
        discovered.extend(
            path
            for path in discover_local_mesh_supplemental_files(scene_path, mesh)
            if path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS
        )
    material_names = {
        str(submesh.material or submesh.name or "").strip().lower()
        for submesh in (mesh.submeshes if mesh is not None else [])
        if str(submesh.material or submesh.name or "").strip()
    }
    explicit_texture_references = {
        str(getattr(submesh, "texture", "") or "").strip()
        for submesh in (mesh.submeshes if mesh is not None else [])
        if str(getattr(submesh, "texture", "") or "").strip()
    }
    for texture_reference in explicit_texture_references:
        resolved_reference = _resolve_local_texture_reference(scene_path, texture_reference)
        if resolved_reference is not None:
            discovered.append(resolved_reference)
    discovered.extend(_discover_material_named_texture_files(scene_path, material_names))
    if not discovered or not explicit_texture_references:
        discovered.extend(_discover_nearby_scene_texture_files(scene_path))
    unique: dict[str, Path] = {}
    for candidate in discovered:
        if candidate.is_file():
            unique.setdefault(str(candidate.resolve()).lower(), candidate.resolve())
    return tuple(unique.values())


def discover_local_mesh_supplemental_files(path: str | Path, mesh: Optional[ParsedMesh] = None) -> tuple[Path, ...]:
    source_path = Path(path).expanduser().resolve()
    if source_path.suffix.lower() not in LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS:
        return ()
    discovered: list[Path] = []
    sidecars = _discover_local_mesh_sidecars(source_path)
    discovered.extend(sidecars)
    discovered.extend(_discover_local_mesh_companion_files(source_path))
    for texture_reference in _local_sidecar_texture_references(sidecars):
        texture_path = _resolve_local_texture_reference(source_path, texture_reference)
        if texture_path is not None:
            discovered.append(texture_path)
    if mesh is not None:
        material_names = {
            str(value or "").strip().lower()
            for submesh in mesh.submeshes
            for value in (submesh.texture, submesh.material, submesh.name)
            if str(value or "").strip()
        }
        discovered.extend(_discover_material_named_texture_files(source_path, material_names))
    return tuple(_dedupe_paths(discovered))


def _local_package_root(source_path: Path) -> Path:
    for parent in (source_path.parent, *source_path.parents):
        if parent.name.lower() == "files":
            return parent
    return source_path.parent


def _scene_texture_search_roots(scene_path: Path) -> list[Path]:
    candidates = [
        scene_path.parent,
        scene_path.parent / "textures",
        scene_path.parent / "texture",
        scene_path.parent.parent / "textures",
        scene_path.parent.parent / "texture",
    ]
    package_root = _local_package_root(scene_path)
    if package_root != scene_path.parent:
        candidates.extend([package_root, package_root / "textures", package_root / "texture"])
    seen: set[str] = set()
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except Exception:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _discover_material_named_texture_files(scene_path: Path, material_names: set[str]) -> list[Path]:
    names = {name for name in material_names if name}
    if not names:
        return []
    discovered: list[Path] = []
    scanned_files = 0
    search_limited = False
    for root in _scene_texture_search_roots(scene_path):
        if not root.is_dir():
            continue
        for candidate in root.rglob("*"):
            scanned_files += 1
            if scanned_files > _SCENE_TEXTURE_DISCOVERY_MAX_FILES:
                search_limited = True
                break
            if not candidate.is_file() or candidate.suffix.lower() not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                continue
            stem = candidate.stem.lower()
            if any(stem.startswith(material_name) or material_name in stem for material_name in names):
                discovered.append(candidate)
        if search_limited:
            break
    if search_limited:
        logger.info(
            "Stopped scene texture discovery for %s after scanning %d filesystem entries. "
            "Add additional textures through Supplemental Files if needed.",
            scene_path,
            _SCENE_TEXTURE_DISCOVERY_MAX_FILES,
        )
    return discovered


def _nearby_scene_texture_roots(scene_path: Path) -> list[Path]:
    candidates = [
        scene_path.parent / "textures",
        scene_path.parent / "texture",
        scene_path.parent,
        scene_path.parent.parent / "textures",
        scene_path.parent.parent / "texture",
    ]
    seen: set[str] = set()
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except Exception:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _discover_nearby_scene_texture_files(scene_path: Path) -> list[Path]:
    """Find likely colocated source textures when OBJ/scene material names are incomplete."""
    discovered: list[Path] = []
    seen: set[str] = set()
    scanned_files = 0
    search_limited = False
    for root in _nearby_scene_texture_roots(scene_path):
        if not root.is_dir():
            continue
        try:
            for candidate in root.rglob("*"):
                scanned_files += 1
                if scanned_files > _SCENE_TEXTURE_DISCOVERY_MAX_FILES:
                    search_limited = True
                    break
                if not candidate.is_file() or candidate.suffix.lower() not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                    continue
                try:
                    resolved = candidate.expanduser().resolve()
                except Exception:
                    continue
                key = str(resolved).lower()
                if key in seen:
                    continue
                seen.add(key)
                discovered.append(resolved)
                if len(discovered) >= _SCENE_TEXTURE_DISCOVERY_FALLBACK_MAX_TEXTURES:
                    search_limited = True
                    break
        except OSError:
            continue
        if search_limited:
            break
    if search_limited:
        logger.info(
            "Stopped fallback scene texture discovery for %s after %d filesystem entries or %d texture files. "
            "Add additional textures through Supplemental Files if needed.",
            scene_path,
            scanned_files,
            _SCENE_TEXTURE_DISCOVERY_FALLBACK_MAX_TEXTURES,
        )
    return discovered


def _discover_local_mesh_sidecars(source_path: Path) -> tuple[Path, ...]:
    suffix = source_path.suffix.lower()
    direct_candidates = [
        source_path.with_suffix(f"{suffix}_xml"),
        source_path.with_name(f"{source_path.name}.xml"),
        source_path.with_suffix(".xml"),
    ]
    if suffix in {".pam", ".pamlod"}:
        direct_candidates.append(source_path.with_suffix(".pami"))

    discovered: list[Path] = []
    for candidate in direct_candidates:
        if candidate.is_file() and candidate.suffix.lower() in SCENE_SIDECAR_SOURCE_EXTENSIONS:
            discovered.append(candidate)

    stem_key = source_path.stem.lower()
    try:
        for candidate in source_path.parent.iterdir():
            if not candidate.is_file() or candidate.suffix.lower() not in SCENE_SIDECAR_SOURCE_EXTENSIONS:
                continue
            candidate_name = candidate.name.lower()
            candidate_stem = candidate.stem.lower()
            if candidate_stem.startswith(stem_key) or candidate_name.startswith(f"{stem_key}{suffix}"):
                discovered.append(candidate)
    except OSError:
        pass
    return tuple(_dedupe_paths(discovered))


def _discover_local_mesh_companion_files(source_path: Path) -> tuple[Path, ...]:
    """Find non-texture Crimson companion files that may affect a complete swap."""
    if source_path.suffix.lower() not in LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS:
        return ()
    stem_key = source_path.stem.lower()
    discovered: list[Path] = []
    for extension in SCENE_COMPANION_SOURCE_EXTENSIONS:
        candidate = source_path.with_suffix(extension)
        if candidate.is_file():
            discovered.append(candidate)

    search_roots = [source_path.parent]
    package_root = _local_package_root(source_path)
    if package_root != source_path.parent:
        search_roots.append(package_root)
    seen_roots: set[str] = set()
    scanned = 0
    for root in search_roots:
        if not root.is_dir():
            continue
        root_key = str(root).lower()
        if root_key in seen_roots:
            continue
        seen_roots.add(root_key)
        try:
            iterator = root.rglob("*") if root == package_root else root.iterdir()
            for candidate in iterator:
                scanned += 1
                if scanned > _SCENE_TEXTURE_DISCOVERY_MAX_FILES:
                    logger.info(
                        "Stopped local Crimson companion discovery for %s after scanning %d filesystem entries.",
                        source_path,
                        _SCENE_TEXTURE_DISCOVERY_MAX_FILES,
                    )
                    return tuple(_dedupe_paths(discovered))
                if not candidate.is_file() or candidate.suffix.lower() not in SCENE_COMPANION_SOURCE_EXTENSIONS:
                    continue
                if candidate.stem.lower().startswith(stem_key):
                    discovered.append(candidate)
        except OSError:
            continue
    return tuple(_dedupe_paths(discovered))


def _local_sidecar_texture_references(sidecar_paths: Sequence[Path]) -> tuple[str, ...]:
    try:
        from cdmw.core.upscale_profiles import parse_texture_sidecar_bindings
    except Exception:
        return ()

    references: list[str] = []
    seen: set[str] = set()
    for sidecar_path in sidecar_paths:
        try:
            sidecar_text = _read_local_sidecar_text(sidecar_path)
        except Exception:
            continue
        try:
            bindings = parse_texture_sidecar_bindings(sidecar_text, sidecar_path=sidecar_path.name)
        except Exception:
            bindings = ()
        for binding in bindings:
            texture_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
            if not texture_path:
                continue
            key = texture_path.lower()
            if key in seen:
                continue
            seen.add(key)
            references.append(texture_path)
    return tuple(references)


def _read_local_sidecar_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-8", "cp1252"):
        try:
            return data.decode(encoding).replace("\ufeff", "")
        except UnicodeError:
            continue
    return data.decode("utf-8", errors="replace").replace("\ufeff", "")


def _find_first_local_file_by_basename(root: Path, basename: str) -> Optional[Path]:
    if not root.is_dir() or not basename:
        return None
    scanned_files = 0
    lowered_basename = basename.lower()
    try:
        for candidate in root.rglob("*"):
            scanned_files += 1
            if scanned_files > _SCENE_TEXTURE_DISCOVERY_MAX_FILES:
                break
            if candidate.is_file() and candidate.name.lower() == lowered_basename:
                return candidate.resolve()
    except OSError:
        return None
    return None


def _resolve_local_texture_reference(source_path: Path, texture_reference: str) -> Optional[Path]:
    normalized_reference = unquote(str(texture_reference or "").replace("\\", "/")).strip().strip("/")
    if not normalized_reference:
        return None
    reference_suffix = PurePosixPath(normalized_reference).suffix.lower()
    if reference_suffix not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
        return None

    direct_candidate = Path(normalized_reference).expanduser()
    if direct_candidate.is_absolute() and direct_candidate.is_file():
        return direct_candidate.resolve()

    package_root = _local_package_root(source_path)
    reference_parts = PurePosixPath(normalized_reference).parts
    basename = PurePosixPath(normalized_reference).name
    candidates: list[Path] = []
    if reference_parts:
        candidates.append(source_path.parent.joinpath(*reference_parts))
        candidates.append(package_root.joinpath(*reference_parts))
        collapsed_parts = tuple(part for part in reference_parts if part.lower() not in {"texture", "textures"})
        if collapsed_parts and collapsed_parts != reference_parts:
            candidates.append(package_root.joinpath(*collapsed_parts))
    if basename:
        candidates.extend(
            [
                source_path.parent / basename,
                source_path.parent / "texture" / basename,
                source_path.parent / "textures" / basename,
            ]
        )
        if reference_parts:
            candidates.append(package_root / reference_parts[0] / basename)

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except Exception:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file():
            return resolved

    for root in (source_path.parent, package_root):
        found = _find_first_local_file_by_basename(root, basename)
        if found is not None:
            return found
    return None


def _load_gltf_payload(source_path: Path) -> _GltfPayload:
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


def _gltf_texture_info_texcoord(texture_info: object) -> int:
    if not isinstance(texture_info, Mapping):
        return 0
    return max(0, _safe_int(texture_info.get("texCoord"), 0))


def _gltf_texture_transform(texture_info: object) -> tuple[float, ...]:
    if not isinstance(texture_info, Mapping):
        return ()
    extensions = texture_info.get("extensions", {})
    transform = extensions.get("KHR_texture_transform") if isinstance(extensions, Mapping) else None
    if not isinstance(transform, Mapping):
        return ()
    offset = _float_list(transform.get("offset"), 2, (0.0, 0.0))
    scale = _float_list(transform.get("scale"), 2, (1.0, 1.0))
    rotation = 0.0
    try:
        rotation = float(transform.get("rotation", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        rotation = 0.0
    return (offset[0], offset[1], scale[0], scale[1], rotation)


def _gltf_texture_info_parameters(slot_kind: str, texture_info: object) -> tuple[PreviewMaterialParameterInput, ...]:
    slot_key = re.sub(r"[^A-Za-z0-9_]+", "_", str(slot_kind or "").strip()) or "texture"
    parameters: list[PreviewMaterialParameterInput] = []
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
) -> Optional[SceneMaterialTextureSlot]:
    image_path = _gltf_texture_image_path(payload, textures, images, texture_info)
    if image_path is None:
        return None
    suffix = image_path.suffix.lower()
    if suffix in SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS:
        payload.diagnostics.append(
            f"glTF {slot_kind} texture uses {suffix.upper().lstrip('.')} and is recorded as diagnostic-only; "
            "export PNG/WebP/JPEG/TGA/DDS for preview decoding."
        )
        return None
    if suffix.lower() not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
        payload.diagnostics.append(
            f"glTF {slot_kind} texture has unsupported image extension {suffix or '<none>'}; preview skips this slot."
        )
        return None
    texcoord = _gltf_texture_info_texcoord(texture_info)
    transform = _gltf_texture_transform(texture_info)
    if texcoord > 0:
        payload.diagnostics.append(f"glTF {slot_kind} texture requests TEXCOORD_{texcoord}; preview selects that UV set when present.")
    if transform:
        offset_u, offset_v, scale_u, scale_v, rotation = transform
        if abs(offset_u) > 1e-6 or abs(offset_v) > 1e-6 or abs(rotation) > 1e-6:
            payload.diagnostics.append(
                f"glTF {slot_kind} texture uses KHR_texture_transform offset/rotation; preview records it but only UV scale is rendered."
            )
    return _scene_material_slot(
        slot_kind,
        image_path.as_posix(),
        parameter_name=parameter_name,
        texcoord=texcoord,
        transform=transform,
        source=source,
        parameters=_gltf_texture_info_parameters(slot_kind, texture_info),
    )


def _gltf_material_info(
    payload: _GltfPayload,
) -> tuple[
    dict[int, str],
    dict[int, str],
    dict[int, tuple[float, float, float]],
    dict[int, dict[str, SceneMaterialTextureSlot]],
    dict[int, str],
    dict[int, dict[str, object]],
    dict[int, tuple[PreviewMaterialParameterInput, ...]],
]:
    material_names: dict[int, str] = {}
    material_textures: dict[int, str] = {}
    material_colors: dict[int, tuple[float, float, float]] = {}
    material_texture_slots: dict[int, dict[str, SceneMaterialTextureSlot]] = {}
    material_workflows: dict[int, str] = {}
    material_flags: dict[int, dict[str, object]] = {}
    material_preview_parameters: dict[int, tuple[PreviewMaterialParameterInput, ...]] = {}
    textures = payload.document.get("textures", []) or []
    images = payload.document.get("images", []) or []
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

        for slot_key, slot_kind, texture_info, parameter_name in texture_infos:
            slot = _gltf_scene_material_slot(
                payload,
                textures,
                images,
                slot_kind,
                texture_info,
                parameter_name=parameter_name,
            )
            if slot is None:
                continue
            material_slots[slot_key] = slot
            if slot_key == "base":
                material_textures[material_index] = slot.path
            texture_path = Path(slot.path)
            if texture_path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                payload.discovered_texture_files.append(texture_path)
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


def _scene_parameter_numeric(parameters: Sequence[PreviewMaterialParameterInput], *names: str) -> Optional[float]:
    normalized_names = tuple(re.sub(r"[^a-z0-9]+", "", str(name or "").lower()) for name in names if str(name or "").strip())
    if not normalized_names:
        return None
    for parameter in tuple(parameters or ()):
        key = re.sub(r"[^a-z0-9]+", "", str(getattr(parameter, "parameter_name", "") or "").lower())
        if not key or not any(name in key for name in normalized_names):
            continue
        numeric_value = getattr(parameter, "numeric_value", None)
        if numeric_value is not None:
            try:
                return float(numeric_value)
            except (TypeError, ValueError, OverflowError):
                pass
        try:
            return float(str(getattr(parameter, "value", "") or ""))
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def _scene_parameter_color(parameters: Sequence[PreviewMaterialParameterInput], *names: str) -> tuple[float, float, float]:
    normalized_names = tuple(re.sub(r"[^a-z0-9]+", "", str(name or "").lower()) for name in names if str(name or "").strip())
    if not normalized_names:
        return ()
    for parameter in tuple(parameters or ()):
        key = re.sub(r"[^a-z0-9]+", "", str(getattr(parameter, "parameter_name", "") or "").lower())
        if not key or not any(name in key for name in normalized_names):
            continue
        color = tuple(getattr(parameter, "color_value", ()) or ())
        if len(color) >= 3:
            try:
                return tuple(max(0.0, min(2.0, float(value))) for value in color[:3])  # type: ignore[return-value]
            except (TypeError, ValueError, OverflowError):
                return ()
    return ()


def _apply_scene_material_parameters_to_submesh(
    submesh: SubMesh,
    parameters: Sequence[PreviewMaterialParameterInput],
) -> None:
    parameter_tuple = tuple(parameters or ())
    if parameter_tuple:
        existing = tuple(getattr(submesh, "preview_material_parameters", ()) or ())
        submesh.preview_material_parameters = tuple(existing + tuple(parameter for parameter in parameter_tuple if parameter not in existing))
    base_tint = _scene_parameter_color(parameter_tuple, "basecolorfactor") or _scene_parameter_color(parameter_tuple, "diffusefactor")
    if base_tint:
        submesh.preview_texture_tint = base_tint
    alpha_cutoff = _scene_parameter_numeric(parameter_tuple, "gltfalphacutoff")
    native_overrides = dict(getattr(submesh, "preview_native_material_overrides", {}) or {})
    if alpha_cutoff is not None:
        native_overrides["alpha_threshold"] = max(0.0, min(0.95, float(alpha_cutoff)))
    alpha_factor = _scene_parameter_numeric(parameter_tuple, "alphafactor", "opacityfactor")
    if alpha_factor is not None:
        alpha_value = max(0.0, min(1.0, float(alpha_factor)))
        if alpha_value < 0.999:
            submesh.preview_alpha_mode = "BLEND"
            submesh.preview_vertex_alpha_mean = alpha_value
            submesh.preview_vertex_alpha_min = alpha_value
    if _scene_parameter_numeric(parameter_tuple, "gltfunlit") is not None:
        native_overrides.setdefault("material_shader_family", "gltf_unlit")
        native_overrides.setdefault("roughness", 1.0)
        native_overrides.setdefault("specular", 0.0)
    roughness_factor = _scene_parameter_numeric(parameter_tuple, "roughnessfactor")
    if roughness_factor is not None:
        native_overrides.setdefault("roughness", max(0.0, min(1.0, float(roughness_factor))))
    glossiness_factor = _scene_parameter_numeric(parameter_tuple, "glossinessfactor")
    if glossiness_factor is not None:
        native_overrides.setdefault("roughness", max(0.0, min(1.0, 1.0 - float(glossiness_factor))))
    metallic_factor = _scene_parameter_numeric(parameter_tuple, "metallicfactor")
    if metallic_factor is not None:
        native_overrides.setdefault("metalness", max(0.0, min(1.0, float(metallic_factor))))
    specular_factor = _scene_parameter_numeric(parameter_tuple, "specularfactor")
    specular_color = _scene_parameter_color(parameter_tuple, "specularcolorfactor", "specularfactor")
    if specular_factor is not None or specular_color:
        specular_value = max(0.0, min(1.0, float(specular_factor))) if specular_factor is not None else 1.0
        if specular_color:
            specular_value *= max(0.0, min(1.0, (0.299 * specular_color[0]) + (0.587 * specular_color[1]) + (0.114 * specular_color[2])))
        native_overrides.setdefault("specular", max(0.0, min(1.0, specular_value)))
    clearcoat_factor = _scene_parameter_numeric(parameter_tuple, "clearcoatfactor")
    if clearcoat_factor is not None and clearcoat_factor > 0.0:
        native_overrides["specular"] = max(float(native_overrides.get("specular", 0.0) or 0.0), max(0.0, min(1.0, float(clearcoat_factor))))
    sheen_color = _scene_parameter_color(parameter_tuple, "sheencolorfactor")
    if sheen_color:
        sheen_luma = max(0.0, min(1.0, (0.299 * sheen_color[0]) + (0.587 * sheen_color[1]) + (0.114 * sheen_color[2])))
        native_overrides["specular"] = max(float(native_overrides.get("specular", 0.0) or 0.0), sheen_luma * 0.5)
    emissive_intensity = _scene_parameter_numeric(parameter_tuple, "emissiveintensity")
    emissive_color = _scene_parameter_color(parameter_tuple, "emissivecolor")
    if emissive_intensity is not None and emissive_intensity > 0.0:
        native_overrides["emissive_intensity"] = max(0.0, min(32.0, float(emissive_intensity)))
    if emissive_color:
        native_overrides["emissive_color"] = "#" + "".join(
            f"{max(0, min(255, int(round(component * 255)))):02x}"
            for component in emissive_color[:3]
        )
    if native_overrides:
        submesh.preview_native_material_overrides = native_overrides


def _apply_scene_material_slots_to_submesh(
    submesh: SubMesh,
    slots: Sequence[SceneMaterialTextureSlot],
    *,
    material_parameters: Sequence[PreviewMaterialParameterInput] = (),
    confidence: str = "scene",
) -> None:
    parameter_tuple = tuple(material_parameters or ())
    _apply_scene_material_parameters_to_submesh(submesh, parameter_tuple)
    normalized_slots = tuple(slot for slot in tuple(slots or ()) if isinstance(slot, SceneMaterialTextureSlot) and str(slot.path or "").strip())
    if not normalized_slots:
        return
    material_inputs: list[PreviewMaterialTextureInput] = []

    def add_input(slot: SceneMaterialTextureSlot) -> None:
        material_inputs.append(
            PreviewMaterialTextureInput(
                slot_kind=slot.slot_kind,
                parameter_name=slot.parameter_name,
                source_texture_path=slot.path,
                texture_name=Path(slot.path).name,
                preview_texture_path=slot.path,
                semantic_type=slot.semantic_type,
                semantic_subtype=slot.semantic_subtype,
                packed_channels=tuple(slot.packed_channels),
                material_name=str(submesh.material or submesh.name or "").strip(),
                shader_family=slot.shader_family,
                confidence=confidence,
                visualized=True,
                srgb_mode=slot.srgb_mode,
                blend_flags=tuple(
                    value
                    for value in (
                        f"texcoord:{slot.texcoord}" if slot.texcoord else "",
                        "texture_transform" if slot.transform else "",
                        f"source:{slot.source}" if slot.source else "",
                    )
                    if value
                ),
                material_parameters=tuple(parameter_tuple + tuple(slot.parameters or ())),
            )
        )

    for slot in normalized_slots:
        path_text = str(slot.path or "").strip()
        if not path_text:
            continue
        add_input(slot)
        slot_kind = str(slot.slot_kind or "").strip().lower()
        subtype = str(slot.semantic_subtype or "").strip().lower()
        if slot_kind == "base":
            submesh.texture = path_text
            submesh.preview_texture_path = path_text
            submesh.preview_texture_name = Path(path_text).name
            if len(slot.transform) >= 5:
                offset_u, offset_v, scale_u, scale_v, rotation = slot.transform[:5]
                if abs(offset_u) <= 1e-6 and abs(offset_v) <= 1e-6 and abs(rotation) <= 1e-6:
                    submesh.preview_texture_uv_scale = (float(scale_u), float(scale_v))
        elif slot_kind == "normal" and subtype != "clearcoat_normal":
            submesh.preview_normal_texture_path = path_text
            submesh.preview_normal_texture_name = Path(path_text).name
            submesh.preview_normal_texture_strength = max(
                0.0,
                min(
                    2.0,
                    _scene_parameter_numeric(slot.parameters, "gltftexturescale", "normaltexturescale")
                    or float(getattr(submesh, "preview_normal_texture_strength", 0.0) or 0.75),
                ),
            )
        elif slot_kind == "height":
            submesh.preview_height_texture_path = path_text
            submesh.preview_height_texture_name = Path(path_text).name
    material_priority = {
        "metallic_roughness": 100,
        "specular_glossiness": 98,
        "roughness": 84,
        "glossiness": 83,
        "metallic": 82,
        "specular": 80,
        "ao": 76,
        "clearcoat": 62,
        "clearcoat_roughness": 61,
        "sheen": 58,
        "transmission": 40,
        "volume": 38,
        "anisotropy": 36,
        "iridescence": 34,
    }
    material_slot = max(
        (
            slot
            for slot in normalized_slots
            if str(slot.slot_kind or "").strip().lower() in {"material", "roughness", "metalness", "specular", "glossiness", "occlusion"}
        ),
        key=lambda slot: material_priority.get(str(slot.semantic_subtype or slot.slot_kind or "").strip().lower(), 0),
        default=None,
    )
    if material_slot is not None:
        submesh.preview_material_texture_path = material_slot.path
        submesh.preview_material_texture_name = Path(material_slot.path).name
        submesh.preview_material_texture_type = material_slot.semantic_type
        submesh.preview_material_texture_subtype = material_slot.semantic_subtype
        submesh.preview_material_texture_packed_channels = tuple(material_slot.packed_channels)
    if material_inputs:
        existing = tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ())
        merged: list[PreviewMaterialTextureInput] = []
        seen_inputs: set[tuple[str, str, str]] = set()
        for item in existing + tuple(material_inputs):
            key = (
                str(getattr(item, "slot_kind", "") or "").strip().lower(),
                str(getattr(item, "parameter_name", "") or "").strip().lower(),
                str(getattr(item, "preview_texture_path", "") or getattr(item, "source_texture_path", "") or "").replace("\\", "/").lower(),
            )
            if key in seen_inputs:
                continue
            seen_inputs.add(key)
            merged.append(item)
        submesh.preview_material_texture_inputs = tuple(merged)
    if any(str(slot.slot_kind or "").strip().lower() == "emissive" for slot in normalized_slots):
        submesh.preview_sidecar_shader_family = "SkinnedMeshEmissive_Ver2"


def _resolve_gltf_image(payload: _GltfPayload, image: dict[str, Any], image_index: int) -> Optional[Path]:
    uri = str(image.get("uri", "") or "")
    if uri:
        if uri.startswith("data:"):
            mime_type, data = _decode_data_uri_with_mime(uri)
            return _write_embedded_gltf_image(payload, image_index, data, mime_type)
        image_path = _resolve_scene_uri(payload.source_path.parent, uri)
        return image_path.resolve() if image_path.is_file() else image_path
    buffer_view_index = _safe_int(image.get("bufferView"), -1)
    if buffer_view_index >= 0:
        image_bytes = _read_gltf_buffer_view_bytes(payload, buffer_view_index)
        mime_type = str(image.get("mimeType", "") or "")
        return _write_embedded_gltf_image(payload, image_index, image_bytes, mime_type)
    return None


def _write_embedded_gltf_image(payload: _GltfPayload, image_index: int, data: bytes, mime_type: str) -> Path:
    ext = _GLTF_IMAGE_MIME_EXTENSIONS.get(str(mime_type or "").lower(), "")
    if not ext:
        guessed = mimetypes.guess_extension(str(mime_type or "")) or ""
        ext = guessed if guessed.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS else ".bin"
    export_dir = _embedded_gltf_extract_dir(payload.source_path)
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"image_{image_index}{ext}"
    if not path.is_file() or path.read_bytes() != data:
        path.write_bytes(data)
    payload.extracted_embedded_files.append(path.resolve())
    return path.resolve()


def _embedded_gltf_extract_dir(source_path: Path) -> Path:
    try:
        stat = source_path.stat()
        key = f"{source_path}|{stat.st_mtime_ns}|{stat.st_size}"
    except OSError:
        key = str(source_path)
    digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "cdmw_gltf_imports" / digest


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
    baked_vertices: list[tuple[float, float, float]] = []
    baked_normals: list[tuple[float, float, float]] = []
    for vertex_index, vertex in enumerate(vertices):
        joint_values = joints[vertex_index] if vertex_index < len(joints) else (0.0, 0.0, 0.0, 0.0)
        weight_values = weights[vertex_index] if vertex_index < len(weights) else (1.0, 0.0, 0.0, 0.0)
        weight_sum = sum(max(0.0, float(weight)) for weight in weight_values)
        if weight_sum <= 1e-8:
            baked_vertices.append(tuple(float(component) for component in vertex[:3]))
            if vertex_index < len(normals):
                baked_normals.append(_normalize_vec(tuple(float(component) for component in normals[vertex_index][:3])))
            continue
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


def _parse_gltf_primitive(
    payload: _GltfPayload,
    primitive: dict[str, Any],
    *,
    name: str,
    material: str,
    texture: str,
    texcoord_index: int = 0,
) -> SubMesh:
    attributes = primitive.get("attributes", {})
    positions = _read_gltf_accessor(payload, _safe_int(attributes.get("POSITION"), -1), expected_components=3)
    normals = _read_gltf_accessor(payload, _safe_int(attributes.get("NORMAL"), -1), expected_components=3)
    texcoord_name = f"TEXCOORD_{max(0, int(texcoord_index or 0))}"
    texcoord_accessor = _safe_int(attributes.get(texcoord_name), -1)
    if texcoord_accessor < 0 and texcoord_name != "TEXCOORD_0":
        payload.diagnostics.append(f"glTF primitive {name} does not provide {texcoord_name}; falling back to TEXCOORD_0.")
        texcoord_accessor = _safe_int(attributes.get("TEXCOORD_0"), -1)
    uvs = _read_gltf_accessor(payload, texcoord_accessor, expected_components=2)
    vertex_colors = _read_gltf_vertex_colors(payload, _safe_int(attributes.get("COLOR_0"), -1))
    index_accessor = _safe_int(primitive.get("indices"), -1)
    if index_accessor >= 0:
        raw_indices = [int(values[0]) for values in _read_gltf_accessor(payload, index_accessor, expected_components=1)]
    else:
        raw_indices = list(range(len(positions)))
    faces = [
        (raw_indices[index], raw_indices[index + 1], raw_indices[index + 2])
        for index in range(0, len(raw_indices) - 2, 3)
        if max(raw_indices[index], raw_indices[index + 1], raw_indices[index + 2]) < len(positions)
    ]
    normalized_uvs = [(float(uv[0]), 1.0 - float(uv[1])) for uv in uvs]
    if len(normalized_uvs) != len(positions):
        normalized_uvs = [(0.0, 0.0)] * len(positions)
    if len(normals) != len(positions):
        normals = _compute_smooth_normals(positions, faces)
    submesh = SubMesh(
        name=name,
        material=material,
        texture=texture,
        vertices=[(float(v[0]), float(v[1]), float(v[2])) for v in positions],
        uvs=normalized_uvs,
        normals=[(float(n[0]), float(n[1]), float(n[2])) for n in normals],
        faces=faces,
        vertex_count=len(positions),
        face_count=len(faces),
    )
    if len(vertex_colors) == len(positions):
        _attach_gltf_vertex_color_summary(submesh, vertex_colors)
    return submesh


def _read_gltf_vertex_colors(payload: _GltfPayload, accessor_index: int) -> list[tuple[float, float, float, float]]:
    if accessor_index < 0:
        return []
    color_rows = _read_gltf_accessor(payload, accessor_index, expected_components=4)
    if not color_rows:
        rgb_rows = _read_gltf_accessor(payload, accessor_index, expected_components=3)
        color_rows = [tuple(row[:3]) + (1.0,) for row in rgb_rows]
    output: list[tuple[float, float, float, float]] = []
    for row in color_rows:
        if len(row) < 3:
            continue
        rgba = tuple(max(0.0, min(1.0, float(value))) for value in (tuple(row[:4]) + (1.0,))[:4])
        output.append(rgba)  # type: ignore[arg-type]
    return output


def _attach_gltf_vertex_color_summary(
    submesh: SubMesh,
    vertex_colors: Sequence[Sequence[float]],
) -> None:
    rows = [tuple(float(value) for value in tuple(row or ())[:4]) for row in tuple(vertex_colors or ()) if len(tuple(row or ())) >= 4]
    if not rows:
        return
    count = float(len(rows))
    mean = tuple(sum(row[index] for row in rows) / count for index in range(4))
    setattr(submesh, "preview_vertex_color_mean", tuple(round(max(0.0, min(1.0, value)), 4) for value in mean[:3]))
    setattr(submesh, "preview_vertex_alpha_mean", round(max(0.0, min(1.0, mean[3])), 4))
    setattr(submesh, "preview_vertex_alpha_min", round(max(0.0, min(1.0, min(row[3] for row in rows))), 4))
    setattr(submesh, "preview_vertex_color_count", len(rows))


def _read_gltf_accessor(payload: _GltfPayload, accessor_index: int, *, expected_components: int) -> list[tuple[float, ...]]:
    accessors = payload.document.get("accessors", []) or []
    if accessor_index < 0:
        return []
    if accessor_index >= len(accessors) or not isinstance(accessors[accessor_index], dict):
        raise ValueError(f"glTF accessor index is invalid: {accessor_index}")
    accessor = accessors[accessor_index]
    if accessor.get("sparse"):
        payload.diagnostics.append("glTF sparse accessors are not expanded; affected attributes may import incompletely.")
    component_type = int(accessor.get("componentType", 0) or 0)
    type_name = str(accessor.get("type", "SCALAR") or "SCALAR")
    component_count = _GLTF_TYPE_COUNTS.get(type_name, 1)
    if expected_components > component_count:
        return []
    count = int(accessor.get("count", 0) or 0)
    buffer_view_index = _safe_int(accessor.get("bufferView"), -1)
    if buffer_view_index < 0:
        return [(0.0,) * expected_components for _index in range(count)]
    view = _gltf_buffer_view(payload, buffer_view_index)
    fmt, component_size, _signed = _GLTF_COMPONENT_FORMATS.get(component_type, ("", 0, False))
    if not fmt or component_size <= 0:
        raise ValueError(f"Unsupported glTF accessor component type: {component_type}")
    buffer_index = _safe_int(view.get("buffer"), -1)
    if buffer_index < 0 or buffer_index >= len(payload.buffers):
        raise ValueError(f"glTF accessor references missing buffer {buffer_index}.")
    buffer_data = payload.buffers[buffer_index]
    view_offset = int(view.get("byteOffset", 0) or 0)
    accessor_offset = int(accessor.get("byteOffset", 0) or 0)
    byte_stride = int(view.get("byteStride", 0) or 0) or component_size * component_count
    start = view_offset + accessor_offset
    normalized = bool(accessor.get("normalized", False))
    rows: list[tuple[float, ...]] = []
    unpack = struct.Struct("<" + fmt)
    for row_index in range(count):
        row_start = start + row_index * byte_stride
        values: list[float] = []
        for component_index in range(component_count):
            offset = row_start + component_index * component_size
            if offset + component_size > len(buffer_data):
                values.append(0.0)
                continue
            value = unpack.unpack_from(buffer_data, offset)[0]
            values.append(float(_normalize_gltf_component(value, component_type)) if normalized else float(value))
        rows.append(tuple(values[:expected_components]))
    return rows


def _gltf_buffer_view(payload: _GltfPayload, view_index: int) -> dict[str, Any]:
    views = payload.document.get("bufferViews", []) or []
    if view_index < 0 or view_index >= len(views) or not isinstance(views[view_index], dict):
        raise ValueError(f"glTF bufferView index is invalid: {view_index}")
    return views[view_index]


def _read_gltf_buffer_view_bytes(payload: _GltfPayload, view_index: int) -> bytes:
    view = _gltf_buffer_view(payload, view_index)
    buffer_index = _safe_int(view.get("buffer"), -1)
    if buffer_index < 0 or buffer_index >= len(payload.buffers):
        raise ValueError(f"glTF image references missing buffer {buffer_index}.")
    offset = int(view.get("byteOffset", 0) or 0)
    length = int(view.get("byteLength", 0) or 0)
    return payload.buffers[buffer_index][offset : offset + length]


def _normalize_gltf_component(value: object, component_type: int) -> float:
    number = float(value)
    if component_type == 5120:
        return max(number / 127.0, -1.0)
    if component_type == 5121:
        return number / 255.0
    if component_type == 5122:
        return max(number / 32767.0, -1.0)
    if component_type == 5123:
        return number / 65535.0
    if component_type == 5125:
        return number / 4294967295.0
    return number


def _decode_data_uri(uri: str) -> bytes:
    _mime_type, data = _decode_data_uri_with_mime(uri)
    return data


def _decode_data_uri_with_mime(uri: str) -> tuple[str, bytes]:
    header, _sep, payload = uri.partition(",")
    mime_type = header[5:].split(";", 1)[0] if header.startswith("data:") else ""
    if ";base64" in header.lower():
        return mime_type, base64.b64decode(payload)
    return mime_type, unquote(payload).encode("utf-8")


def _resolve_scene_uri(base_dir: Path, uri: str) -> Path:
    parsed = urlparse(uri)
    raw_path = unquote(parsed.path if parsed.scheme == "file" else uri)
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = base_dir / raw_path
    return candidate.expanduser().resolve()


def _parse_collada_geometry(
    geometry: ET.Element,
    material_names: dict[str, str],
    prefix: str,
    ns: dict[str, str],
) -> _ColladaGeometry:
    geometry_id = geometry.attrib.get("id", "")
    geometry_name = geometry.attrib.get("name", "") or geometry_id
    mesh = geometry.find(f"{prefix}mesh", ns)
    if mesh is None:
        return _ColladaGeometry(geometry_id=geometry_id, name=geometry_name, primitives=[])

    sources = _collada_sources(mesh, prefix, ns)
    vertices_sources = _collada_vertices_sources(mesh, prefix, ns)
    primitives: list[SubMesh] = []
    for primitive in list(mesh.findall(f"{prefix}triangles", ns)) + list(mesh.findall(f"{prefix}polylist", ns)):
        material_symbol = primitive.attrib.get("material", "")
        material_name = material_names.get(material_symbol, material_symbol)
        submesh = _parse_collada_primitive(
            primitive,
            sources,
            vertices_sources,
            name=geometry_name,
            material=material_name,
            prefix=prefix,
            ns=ns,
        )
        if submesh.faces:
            primitives.append(submesh)
    return _ColladaGeometry(geometry_id=geometry_id, name=geometry_name, primitives=primitives)


def _collada_sources(mesh: ET.Element, prefix: str, ns: dict[str, str]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for source in mesh.findall(f"{prefix}source", ns):
        source_id = source.attrib.get("id", "")
        array = source.find(f"{prefix}float_array", ns)
        accessor = source.find(f"{prefix}technique_common/{prefix}accessor", ns)
        if not source_id or array is None:
            continue
        values = _parse_float_list(array.text or "")
        stride = 3
        if accessor is not None:
            try:
                stride = max(1, int(accessor.attrib.get("stride", "3")))
            except ValueError:
                stride = 3
        result[source_id] = {"values": values, "stride": stride}
    return result


def _collada_vertices_sources(mesh: ET.Element, prefix: str, ns: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for vertices in mesh.findall(f"{prefix}vertices", ns):
        vertices_id = vertices.attrib.get("id", "")
        for input_element in vertices.findall(f"{prefix}input", ns):
            if input_element.attrib.get("semantic", "").upper() == "POSITION":
                result[vertices_id] = input_element.attrib.get("source", "").lstrip("#")
    return result


def _parse_collada_primitive(
    primitive: ET.Element,
    sources: dict[str, dict[str, object]],
    vertices_sources: dict[str, str],
    *,
    name: str,
    material: str,
    prefix: str,
    ns: dict[str, str],
) -> SubMesh:
    inputs = []
    for input_element in primitive.findall(f"{prefix}input", ns):
        try:
            offset = int(input_element.attrib.get("offset", "0"))
        except ValueError:
            offset = 0
        semantic = input_element.attrib.get("semantic", "").upper()
        source_id = input_element.attrib.get("source", "").lstrip("#")
        if semantic == "VERTEX":
            source_id = vertices_sources.get(source_id, source_id)
            semantic = "POSITION"
        inputs.append((offset, semantic, source_id))
    if not inputs:
        return SubMesh(name=name, material=material)
    index_stride = max(offset for offset, _semantic, _source in inputs) + 1
    p_element = primitive.find(f"{prefix}p", ns)
    if p_element is None or not (p_element.text or "").strip():
        return SubMesh(name=name, material=material)
    raw_indices = [int(value) for value in (p_element.text or "").split()]
    polygon_counts: list[int]
    vcount_element = primitive.find(f"{prefix}vcount", ns)
    if vcount_element is not None and (vcount_element.text or "").strip():
        polygon_counts = [int(value) for value in (vcount_element.text or "").split()]
    else:
        polygon_counts = [3] * (len(raw_indices) // (index_stride * 3))

    vertices: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    normals: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    corner_to_index: dict[tuple[str, int, str, int, str, int], int] = {}
    cursor = 0
    for polygon_size in polygon_counts:
        corners = []
        for _corner_index in range(polygon_size):
            chunk = raw_indices[cursor : cursor + index_stride]
            cursor += index_stride
            corners.append(_collada_corner_index(chunk, inputs))
        if len(corners) < 3:
            continue
        for tri_index in range(1, len(corners) - 1):
            face_indices = []
            for corner in (corners[0], corners[tri_index], corners[tri_index + 1]):
                local_index = corner_to_index.get(corner)
                if local_index is None:
                    position = _source_tuple(sources, corner[0], corner[1], 3)
                    uv = _source_tuple(sources, corner[2], corner[3], 2) if corner[3] >= 0 else (0.0, 0.0)
                    normal = _source_tuple(sources, corner[4], corner[5], 3) if corner[5] >= 0 else (0.0, 1.0, 0.0)
                    local_index = len(vertices)
                    corner_to_index[corner] = local_index
                    vertices.append(position)  # type: ignore[arg-type]
                    uvs.append((float(uv[0]), 1.0 - float(uv[1])))
                    normals.append(normal)  # type: ignore[arg-type]
                face_indices.append(local_index)
            if len(face_indices) == 3:
                faces.append((face_indices[0], face_indices[1], face_indices[2]))
    if not normals or len(normals) != len(vertices):
        normals = _compute_smooth_normals(vertices, faces)
    return SubMesh(
        name=name,
        material=material,
        texture="",
        vertices=vertices,
        uvs=uvs,
        normals=normals,
        faces=faces,
        vertex_count=len(vertices),
        face_count=len(faces),
    )


def _collada_corner_index(chunk: list[int], inputs: list[tuple[int, str, str]]) -> tuple[str, int, str, int, str, int]:
    position_index = -1
    uv_index = -1
    normal_index = -1
    position_source = ""
    uv_source = ""
    normal_source = ""
    for offset, semantic, _source_id in inputs:
        if offset >= len(chunk):
            continue
        if semantic == "POSITION":
            position_index = chunk[offset]
            position_source = _source_id
        elif semantic == "TEXCOORD" and uv_index < 0:
            uv_index = chunk[offset]
            uv_source = _source_id
        elif semantic == "NORMAL":
            normal_index = chunk[offset]
            normal_source = _source_id
    return position_source, position_index, uv_source, uv_index, normal_source, normal_index


def _source_tuple(
    sources: dict[str, dict[str, object]],
    source_id: str,
    index: int,
    expected: int,
) -> tuple[float, ...]:
    source = sources.get(source_id)
    if source is not None:
        stride = int(source.get("stride", expected) or expected)
        values = source.get("values", [])
        if isinstance(values, list):
            start = index * stride
            if 0 <= start and start + expected <= len(values):
                return tuple(float(values[start + item]) for item in range(expected))
    return (0.0, 0.0) if expected == 2 else (0.0, 0.0, 0.0)


def _collada_material_names(root: ET.Element, prefix: str, ns: dict[str, str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for material in root.findall(f".//{prefix}library_materials/{prefix}material", ns):
        material_id = material.attrib.get("id", "")
        material_name = material.attrib.get("name", "") or material_id
        if material_id:
            names[material_id] = material_name
        if material_name:
            names[material_name] = material_name
    return names


def _collada_material_texture_slots(
    root: ET.Element,
    prefix: str,
    ns: dict[str, str],
    dae_path: Path,
) -> dict[str, tuple[SceneMaterialTextureSlot, ...]]:
    images: dict[str, Path] = {}
    for image in root.findall(f".//{prefix}library_images/{prefix}image", ns):
        raw_text = str((image.findtext(f"{prefix}init_from", default="", namespaces=ns) or "")).strip()
        if not raw_text:
            continue
        resolved = _resolve_collada_image_reference(dae_path, raw_text)
        if resolved is None:
            continue
        for key in (image.attrib.get("id", ""), image.attrib.get("name", ""), resolved.name):
            if key:
                images[str(key)] = resolved

    effect_slots: dict[str, tuple[SceneMaterialTextureSlot, ...]] = {}
    collada_tags = (
        ("diffuse", "base", "_colladaDiffuseTexture"),
        ("emission", "emissive", "_colladaEmissionTexture"),
        ("specular", "specular", "_colladaSpecularTexture"),
        ("shininess", "glossiness", "_colladaShininessTexture"),
        ("transparent", "opacity", "_colladaTransparentTexture"),
        ("bump", "normal", "_colladaBumpTexture"),
        ("reflective", "specular", "_colladaReflectiveTexture"),
    )
    for effect in root.findall(f".//{prefix}library_effects/{prefix}effect", ns):
        effect_id = effect.attrib.get("id", "")
        if not effect_id:
            continue
        surface_sources: dict[str, str] = {}
        sampler_sources: dict[str, str] = {}
        for newparam in effect.findall(f".//{prefix}newparam", ns):
            sid = newparam.attrib.get("sid", "")
            if not sid:
                continue
            init_from = newparam.find(f".//{prefix}surface/{prefix}init_from", ns)
            if init_from is not None and str(init_from.text or "").strip():
                surface_sources[sid] = str(init_from.text or "").strip()
            sampler_source = newparam.find(f".//{prefix}sampler2D/{prefix}source", ns)
            if sampler_source is not None and str(sampler_source.text or "").strip():
                sampler_sources[sid] = str(sampler_source.text or "").strip()

        def resolve_texture_ref(texture_ref: str) -> Optional[Path]:
            ref = str(texture_ref or "").strip()
            if not ref:
                return None
            seen: set[str] = set()
            while ref and ref not in seen:
                seen.add(ref)
                if ref in images:
                    return images[ref]
                if ref in sampler_sources:
                    ref = sampler_sources[ref]
                    continue
                if ref in surface_sources:
                    ref = surface_sources[ref]
                    continue
                break
            direct = _resolve_local_texture_reference(dae_path, ref)
            return direct

        slots: list[SceneMaterialTextureSlot] = []
        seen_slots: set[tuple[str, str]] = set()
        for tag_name, slot_kind, parameter_name in collada_tags:
            for channel in effect.findall(f".//{prefix}{tag_name}", ns):
                for texture_element in channel.findall(f"{prefix}texture", ns):
                    texture_ref = texture_element.attrib.get("texture", "")
                    resolved = resolve_texture_ref(texture_ref)
                    if resolved is None or resolved.suffix.lower() not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                        continue
                    key = (slot_kind, str(resolved).lower())
                    if key in seen_slots:
                        continue
                    seen_slots.add(key)
                    slots.append(
                        _scene_material_slot(
                            slot_kind,
                            resolved.as_posix(),
                            parameter_name=parameter_name,
                            source="dae_effect",
                        )
                    )
        if slots:
            effect_slots[effect_id] = tuple(slots)

    material_slots: dict[str, tuple[SceneMaterialTextureSlot, ...]] = {}
    for material in root.findall(f".//{prefix}library_materials/{prefix}material", ns):
        effect_ref = ""
        instance_effect = material.find(f"{prefix}instance_effect", ns)
        if instance_effect is not None:
            effect_ref = instance_effect.attrib.get("url", "").lstrip("#")
        slots = effect_slots.get(effect_ref, ())
        if not slots:
            continue
        for key in (material.attrib.get("id", ""), material.attrib.get("name", "")):
            if key:
                material_slots[str(key)] = slots
    return material_slots


def _collada_material_parameters(
    root: ET.Element,
    prefix: str,
    ns: dict[str, str],
) -> dict[str, tuple[PreviewMaterialParameterInput, ...]]:
    effect_parameters: dict[str, tuple[PreviewMaterialParameterInput, ...]] = {}

    def channel_element(effect: ET.Element, tag_name: str) -> Optional[ET.Element]:
        return effect.find(f".//{prefix}{tag_name}", ns)

    def channel_color(effect: ET.Element, tag_name: str) -> tuple[float, ...]:
        channel = channel_element(effect, tag_name)
        if channel is None:
            return ()
        color = channel.find(f"{prefix}color", ns)
        if color is None:
            return ()
        values = _parse_float_list(color.text or "")
        return tuple(max(0.0, min(1.0, float(value))) for value in values[:4]) if len(values) >= 3 else ()

    def channel_float(effect: ET.Element, tag_name: str) -> Optional[float]:
        value = effect.find(f".//{prefix}{tag_name}/{prefix}float", ns)
        if value is None:
            return None
        values = _parse_float_list(value.text or "")
        return float(values[0]) if values else None

    def append_parameter(target: list[PreviewMaterialParameterInput], parameter: Optional[PreviewMaterialParameterInput]) -> None:
        if parameter is not None:
            target.append(parameter)

    def transparent_opacity(effect: ET.Element) -> Optional[float]:
        transparent_element = channel_element(effect, "transparent")
        transparent_color = channel_color(effect, "transparent") if transparent_element is not None else ()
        transparency = channel_float(effect, "transparency")
        if not transparent_color and transparency is None:
            return None
        opacity = 1.0
        if transparent_color:
            mode = str(transparent_element.attrib.get("opaque", "A_ONE") if transparent_element is not None else "A_ONE").strip().upper()
            alpha = float(transparent_color[3]) if len(transparent_color) >= 4 else 1.0
            luminance = (
                (0.299 * float(transparent_color[0]))
                + (0.587 * float(transparent_color[1]))
                + (0.114 * float(transparent_color[2]))
            )
            if mode == "A_ZERO":
                opacity = 1.0 - alpha
            elif mode == "RGB_ZERO":
                opacity = 1.0 - luminance
            elif mode == "RGB_ONE":
                opacity = luminance
            else:
                opacity = alpha
        if transparency is not None:
            opacity *= float(transparency)
        return max(0.0, min(1.0, opacity))

    for effect in root.findall(f".//{prefix}library_effects/{prefix}effect", ns):
        effect_id = effect.attrib.get("id", "")
        if not effect_id:
            continue
        parameters: list[PreviewMaterialParameterInput] = []
        alpha_candidates: list[float] = []
        diffuse = channel_color(effect, "diffuse")
        if diffuse:
            append_parameter(parameters, _scene_preview_color_parameter("_diffuseFactor", diffuse[:3]))
            if len(diffuse) >= 4 and diffuse[3] < 0.999:
                alpha_candidates.append(float(diffuse[3]))
        specular = channel_color(effect, "specular")
        if specular:
            append_parameter(parameters, _scene_preview_color_parameter("_specularColorFactor", specular[:3]))
        emission = channel_color(effect, "emission")
        if emission:
            append_parameter(parameters, _scene_preview_color_parameter("_emissiveColor", emission[:3]))
            if any(component > 0.003 for component in emission[:3]):
                append_parameter(parameters, _scene_preview_float_parameter("_emissiveIntensity", 1.0))
        shininess = channel_float(effect, "shininess")
        if shininess is not None:
            glossiness = shininess if 0.0 <= shininess <= 1.0 else shininess / 100.0
            append_parameter(parameters, _scene_preview_float_parameter("_glossinessFactor", max(0.0, min(1.0, glossiness))))
        opacity = transparent_opacity(effect)
        if opacity is not None:
            alpha_candidates.append(float(opacity))
        if alpha_candidates:
            append_parameter(parameters, _scene_preview_float_parameter("_alphaFactor", min(alpha_candidates)))
        if parameters:
            effect_parameters[effect_id] = tuple(parameters)

    material_parameters: dict[str, tuple[PreviewMaterialParameterInput, ...]] = {}
    for material in root.findall(f".//{prefix}library_materials/{prefix}material", ns):
        effect_ref = ""
        instance_effect = material.find(f"{prefix}instance_effect", ns)
        if instance_effect is not None:
            effect_ref = instance_effect.attrib.get("url", "").lstrip("#")
        parameters = effect_parameters.get(effect_ref, ())
        if not parameters:
            continue
        for key in (material.attrib.get("id", ""), material.attrib.get("name", "")):
            if key:
                material_parameters[str(key)] = parameters
    return material_parameters


def _iter_collada_geometry_instances(
    root: ET.Element,
    prefix: str,
    ns: dict[str, str],
) -> list[dict[str, object]]:
    instances: list[dict[str, object]] = []
    for node in root.findall(f".//{prefix}library_visual_scenes/{prefix}visual_scene//{prefix}node", ns):
        node_name = node.attrib.get("name", "") or node.attrib.get("id", "")
        matrix = _collada_node_matrix(node, prefix, ns)
        for instance_geometry in node.findall(f"{prefix}instance_geometry", ns):
            geometry_id = instance_geometry.attrib.get("url", "").lstrip("#")
            if not geometry_id:
                continue
            materials: dict[str, str] = {}
            for instance_material in instance_geometry.findall(f".//{prefix}instance_material", ns):
                symbol = instance_material.attrib.get("symbol", "")
                target = instance_material.attrib.get("target", "").lstrip("#")
                if symbol:
                    materials[symbol] = target or symbol
            instances.append(
                {
                    "geometry_id": geometry_id,
                    "node_name": node_name,
                    "matrix": matrix,
                    "materials": materials,
                }
            )
    return instances


def _collada_node_matrix(
    node: ET.Element,
    prefix: str,
    ns: dict[str, str],
) -> tuple[float, ...]:
    matrix_element = node.find(f"{prefix}matrix", ns)
    if matrix_element is not None:
        values = _parse_float_list(matrix_element.text or "")
        if len(values) >= 16:
            return tuple(values[:16])
    matrix = list(_identity_matrix())
    for translate in node.findall(f"{prefix}translate", ns):
        values = _parse_float_list(translate.text or "")
        if len(values) >= 3:
            matrix[3] += values[0]
            matrix[7] += values[1]
            matrix[11] += values[2]
    for scale in node.findall(f"{prefix}scale", ns):
        values = _parse_float_list(scale.text or "")
        if len(values) >= 3:
            matrix[0] *= values[0]
            matrix[5] *= values[1]
            matrix[10] *= values[2]
    return tuple(matrix)


def _copy_submesh_with_transform(
    submesh: SubMesh,
    matrix: tuple[float, ...],
) -> SubMesh:
    vertices = [_transform_point(vertex, matrix) for vertex in submesh.vertices]
    normals = [_normalize_vec(_transform_vector(normal, matrix)) for normal in submesh.normals]
    copied = SubMesh(
        name=submesh.name,
        material=submesh.material,
        texture=submesh.texture,
        vertices=vertices,
        uvs=list(submesh.uvs),
        normals=normals if len(normals) == len(vertices) else _compute_smooth_normals(vertices, submesh.faces),
        faces=list(submesh.faces),
        vertex_count=len(vertices),
        face_count=len(submesh.faces),
    )
    for attr_name in (
        "texture_slots",
        "preview_color",
        "preview_texture_path",
        "preview_texture_name",
        "preview_texture_tint",
        "preview_texture_brightness",
        "preview_texture_uv_scale",
        "preview_vertex_color_mean",
        "preview_vertex_alpha_mean",
        "preview_vertex_alpha_min",
        "preview_vertex_color_count",
        "preview_alpha_mode",
        "preview_double_sided",
        "preview_native_material_overrides",
        "preview_normal_texture_path",
        "preview_normal_texture_name",
        "preview_normal_texture_strength",
        "preview_material_texture_path",
        "preview_material_texture_name",
        "preview_material_texture_type",
        "preview_material_texture_subtype",
        "preview_material_texture_packed_channels",
        "preview_material_texture_inputs",
        "preview_material_parameters",
        "preview_height_texture_path",
        "preview_height_texture_name",
        "preview_sidecar_shader_family",
    ):
        if hasattr(submesh, attr_name):
            setattr(copied, attr_name, getattr(submesh, attr_name))
    return copied


def _transform_point(
    vertex: tuple[float, float, float],
    matrix: tuple[float, ...],
) -> tuple[float, float, float]:
    x, y, z = vertex
    return (
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    )


def _transform_vector(
    vertex: tuple[float, float, float],
    matrix: tuple[float, ...],
) -> tuple[float, float, float]:
    x, y, z = vertex
    return (
        matrix[0] * x + matrix[1] * y + matrix[2] * z,
        matrix[4] * x + matrix[5] * y + matrix[6] * z,
        matrix[8] * x + matrix[9] * y + matrix[10] * z,
    )


def _normalize_vec(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2])
    if length <= 1e-8:
        return (0.0, 1.0, 0.0)
    return (value[0] / length, value[1] / length, value[2] / length)


def _identity_matrix() -> tuple[float, ...]:
    return (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def _invert_affine_matrix(matrix: tuple[float, ...]) -> Optional[tuple[float, ...]]:
    if len(matrix) < 16:
        return None
    a, b, c, tx = matrix[0], matrix[1], matrix[2], matrix[3]
    d, e, f, ty = matrix[4], matrix[5], matrix[6], matrix[7]
    g, h, i, tz = matrix[8], matrix[9], matrix[10], matrix[11]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(determinant) <= 1e-12:
        return None
    scale = 1.0 / determinant
    r00 = (e * i - f * h) * scale
    r01 = (c * h - b * i) * scale
    r02 = (b * f - c * e) * scale
    r10 = (f * g - d * i) * scale
    r11 = (a * i - c * g) * scale
    r12 = (c * d - a * f) * scale
    r20 = (d * h - e * g) * scale
    r21 = (b * g - a * h) * scale
    r22 = (a * e - b * d) * scale
    return (
        r00, r01, r02, -(r00 * tx + r01 * ty + r02 * tz),
        r10, r11, r12, -(r10 * tx + r11 * ty + r12 * tz),
        r20, r21, r22, -(r20 * tx + r21 * ty + r22 * tz),
        0.0, 0.0, 0.0, 1.0,
    )


def _multiply_matrix(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    values: list[float] = []
    for row in range(4):
        for column in range(4):
            values.append(
                left[row * 4 + 0] * right[0 * 4 + column]
                + left[row * 4 + 1] * right[1 * 4 + column]
                + left[row * 4 + 2] * right[2 * 4 + column]
                + left[row * 4 + 3] * right[3 * 4 + column]
            )
    return tuple(values)


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return default


def _float_list(value: object, count: int, default: tuple[float, ...]) -> tuple[float, ...]:
    if isinstance(value, list) and len(value) >= count:
        try:
            return tuple(float(item) for item in value[:count])
        except Exception:
            return default
    return default


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dedupe_paths(values: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for value in values:
        try:
            path = value.expanduser().resolve()
        except Exception:
            continue
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _bbox(
    vertices: list[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs, ys, zs = zip(*vertices)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _parse_float_list(text: str) -> list[float]:
    values: list[float] = []
    for raw_value in str(text or "").split():
        try:
            values.append(float(raw_value))
        except ValueError:
            continue
    return values


def _collada_image_paths(dae_path: Path) -> list[Path]:
    try:
        root = ET.parse(dae_path).getroot()
    except Exception:
        return []
    ns_uri = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    ns = {"c": ns_uri} if ns_uri else {}
    prefix = "c:" if ns_uri else ""
    paths: list[Path] = []
    for init_from in root.findall(f".//{prefix}library_images/{prefix}image/{prefix}init_from", ns):
        raw_text = str(init_from.text or "").strip()
        if not raw_text:
            continue
        resolved = _resolve_collada_image_reference(dae_path, raw_text)
        if resolved is not None:
            paths.append(resolved)
    return paths


def _resolve_collada_image_reference(dae_path: Path, image_reference: str) -> Optional[Path]:
    resolved = _resolve_local_texture_reference(dae_path, image_reference)
    if resolved is not None:
        return resolved

    normalized_reference = unquote(str(image_reference or "").replace("\\", "/")).strip().strip("/")
    if not normalized_reference:
        return None
    parsed = urlparse(normalized_reference)
    suffix_source = parsed.path if parsed.scheme == "file" else normalized_reference
    if PurePosixPath(suffix_source).suffix.lower() not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
        return None
    if parsed.scheme and parsed.scheme != "file" and len(parsed.scheme) != 1:
        return None
    try:
        return _resolve_scene_uri(dae_path.parent, normalized_reference)
    except OSError:
        return None


def _guess_scene_material_texture(scene_path: Path, material: str) -> str:
    material_key = str(material or "").strip().lower()
    if not material_key:
        return ""
    for root in (scene_path.parent, scene_path.parent / "textures", scene_path.parent.parent / "textures"):
        if not root.is_dir():
            continue
        for candidate in root.rglob("*"):
            if not candidate.is_file() or candidate.suffix.lower() not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                continue
            stem = candidate.stem.lower()
            if stem.startswith(material_key) and any(token in stem for token in ("albedo", "base", "diffuse", "color")):
                return candidate.resolve().as_posix()
    return ""
