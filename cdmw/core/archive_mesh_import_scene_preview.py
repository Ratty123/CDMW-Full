from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.model_preview import _build_lod_summary, _build_model_preview
from cdmw.models import (
    ModelPreviewData,
    ModelPreviewMesh,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_mesh
from cdmw.modding.scene_importer import (
    SCENE_TEXTURE_SOURCE_EXTENSIONS,
    SceneImportResult,
)

def _preview_meshes_from_submeshes(submeshes: Sequence[SubMesh]) -> List[ModelPreviewMesh]:
    preview_meshes: List[ModelPreviewMesh] = []
    for submesh_index, submesh in enumerate(submeshes):
        if not submesh.vertices or not submesh.faces:
            continue
        indices: List[int] = []
        for face in submesh.faces:
            indices.extend(int(index) for index in face[:3])
        preview_mesh = ModelPreviewMesh(
            material_name=str(submesh.material or submesh.name or ""),
            texture_name=str(submesh.texture or ""),
            positions=[tuple(vertex) for vertex in submesh.vertices],
            texture_coordinates=[tuple(uv) for uv in submesh.uvs[: len(submesh.vertices)]],
            normals=[tuple(normal) for normal in submesh.normals[: len(submesh.vertices)]],
            indices=indices,
            source_submesh_index=submesh_index,
            source_vertex_range_start=0,
            source_vertex_range_count=len(submesh.vertices),
            source_face_range_start=0,
            source_face_range_count=len(submesh.faces),
        )
        preview_color = tuple(getattr(submesh, "preview_color", ()) or ())
        if len(preview_color) >= 3:
            preview_mesh.preview_color = tuple(float(component) for component in preview_color[:3])
        preview_texture_path = str(getattr(submesh, "preview_texture_path", "") or "").strip()
        if preview_texture_path:
            preview_mesh.preview_texture_path = preview_texture_path
            preview_mesh.preview_texture_image = None
        preview_texture_tint = tuple(getattr(submesh, "preview_texture_tint", ()) or ())
        if len(preview_texture_tint) >= 3:
            preview_mesh.preview_texture_tint = tuple(float(component) for component in preview_texture_tint[:3])
        preview_texture_uv_scale = tuple(getattr(submesh, "preview_texture_uv_scale", ()) or ())
        if len(preview_texture_uv_scale) >= 2:
            preview_mesh.preview_texture_uv_scale = tuple(float(component) for component in preview_texture_uv_scale[:2])
        preview_vertex_color = tuple(getattr(submesh, "preview_vertex_color_mean", ()) or ())
        if len(preview_vertex_color) >= 3:
            preview_mesh.preview_vertex_color_mean = tuple(float(component) for component in preview_vertex_color[:3])
            preview_mesh.preview_vertex_color_count = int(getattr(submesh, "preview_vertex_color_count", 0) or 0)
        preview_vertex_alpha_mean = getattr(submesh, "preview_vertex_alpha_mean", None)
        if preview_vertex_alpha_mean is not None:
            try:
                preview_mesh.preview_vertex_alpha_mean = float(preview_vertex_alpha_mean)
            except (TypeError, ValueError, OverflowError):
                pass
        preview_vertex_alpha_min = getattr(submesh, "preview_vertex_alpha_min", None)
        if preview_vertex_alpha_min is not None:
            try:
                preview_mesh.preview_vertex_alpha_min = float(preview_vertex_alpha_min)
            except (TypeError, ValueError, OverflowError):
                pass
        preview_texture_brightness = getattr(submesh, "preview_texture_brightness", None)
        if preview_texture_brightness is not None:
            try:
                preview_mesh.preview_texture_brightness = float(preview_texture_brightness)
            except (TypeError, ValueError, OverflowError):
                pass
        preview_native_material_overrides = getattr(submesh, "preview_native_material_overrides", None)
        if isinstance(preview_native_material_overrides, dict):
            preview_mesh.preview_native_material_overrides = dict(preview_native_material_overrides)
        preview_mesh.preview_alpha_mode = str(getattr(submesh, "preview_alpha_mode", "") or "").strip()
        preview_mesh.preview_double_sided = bool(getattr(submesh, "preview_double_sided", False))
        preview_normal_texture_path = str(getattr(submesh, "preview_normal_texture_path", "") or "").strip()
        if preview_normal_texture_path:
            preview_mesh.preview_normal_texture_path = preview_normal_texture_path
            preview_mesh.preview_normal_texture_name = str(
                getattr(submesh, "preview_normal_texture_name", "") or Path(preview_normal_texture_path).name
            )
            preview_mesh.preview_normal_texture_strength = float(
                getattr(submesh, "preview_normal_texture_strength", 0.75) or 0.75
            )
        preview_material_texture_path = str(getattr(submesh, "preview_material_texture_path", "") or "").strip()
        if preview_material_texture_path:
            preview_mesh.preview_material_texture_path = preview_material_texture_path
            preview_mesh.preview_material_texture_name = str(
                getattr(submesh, "preview_material_texture_name", "") or Path(preview_material_texture_path).name
            )
            preview_mesh.preview_material_texture_type = str(getattr(submesh, "preview_material_texture_type", "") or "").strip()
            preview_mesh.preview_material_texture_subtype = str(
                getattr(submesh, "preview_material_texture_subtype", "") or ""
            ).strip()
            preview_mesh.preview_material_texture_packed_channels = tuple(
                str(channel or "").strip()
                for channel in (getattr(submesh, "preview_material_texture_packed_channels", ()) or ())
                if str(channel or "").strip()
            )
        preview_height_texture_path = str(getattr(submesh, "preview_height_texture_path", "") or "").strip()
        if preview_height_texture_path:
            preview_mesh.preview_height_texture_path = preview_height_texture_path
            preview_mesh.preview_height_texture_name = str(
                getattr(submesh, "preview_height_texture_name", "") or Path(preview_height_texture_path).name
            )
        preview_emissive_texture_path = str(getattr(submesh, "preview_emissive_texture_path", "") or "").strip()
        if preview_emissive_texture_path:
            preview_mesh.preview_emissive_texture_path = preview_emissive_texture_path
            preview_mesh.preview_emissive_texture_name = str(
                getattr(submesh, "preview_emissive_texture_name", "") or Path(preview_emissive_texture_path).name
            )
        preview_material_texture_inputs = tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ())
        if preview_material_texture_inputs:
            preview_mesh.preview_material_texture_inputs = preview_material_texture_inputs
            if any(
                "emissive" in str(getattr(item, "shader_family", "") or "").lower()
                or str(getattr(item, "slot_kind", "") or "").lower() == "emissive"
                for item in preview_material_texture_inputs
            ):
                preview_mesh.preview_sidecar_shader_family = "SkinnedMeshEmissive_Ver2"
        preview_meshes.append(preview_mesh)
    return preview_meshes

def parsed_mesh_to_preview_model(parsed_mesh: ParsedMesh) -> ModelPreviewData:
    if parsed_mesh.format == "pamlod" and parsed_mesh.lod_levels:
        source_submeshes = parsed_mesh.lod_levels[0]
        preview_model = _build_model_preview(parsed_mesh.path, "pamlod", _preview_meshes_from_submeshes(source_submeshes), "lod mesh")
        preview_model.lod_index = 0
        preview_model.lod_count = len(parsed_mesh.lod_levels)
        preview_model.summary = _build_lod_summary(
            parsed_mesh.path,
            displayed_lod_index=0,
            recovered_lod_count=len(parsed_mesh.lod_levels),
            vertex_count=preview_model.vertex_count,
            face_count=preview_model.face_count,
        )
        return preview_model

    source_submeshes = parsed_mesh.submeshes
    label = "submesh" if parsed_mesh.format != "pac" else "mesh"
    preview_model = _build_model_preview(parsed_mesh.path, parsed_mesh.format, _preview_meshes_from_submeshes(source_submeshes), label)
    return preview_model

def _compact_scene_texture_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _scene_texture_slot(path: Path) -> str:
    stem = _compact_scene_texture_name(path.stem)
    rules = (
        (("emissive", "emission", "glow", "illumination", "illum"), "emissive"),
        (("normalmap", "normalgl", "normaldx", "normal", "nrm", "bump"), "normal"),
        (("heightmap", "height", "displacement", "disp", "depth"), "height"),
        (("basecolor", "basecolour", "albedo", "diffuse", "diffusemap", "colormap"), "base"),
    )
    for tokens, slot in rules:
        if any(token in stem for token in tokens):
            return slot
    technical = ("metallicroughness", "roughnessmetallic", "occlusionroughnessmetallic", "roughness", "metallic", "metalness", "ambientocclusion", "occlusion", "specular", "glossiness", "gloss", "opacity", "alpha", "orm", "rma", "mra", "arm", "mask")
    return "material" if any(token in stem for token in technical) else "base"


def _scene_material_subtype(path: Path) -> str:
    stem = _compact_scene_texture_name(path.stem)
    rules = (("occlusionroughnessmetallic", "orm"), ("metallicroughness", "metalrough", "metallicrough"), ("roughnessmetallic", "rma"), ("metallic", "metalness"), ("roughness",), ("occlusion",), ("specular",))
    values = ("orm", "metallic_roughness", "rma", "metallic", "roughness", "ao", "specular")
    for tokens, value in zip(rules, values):
        if any(token in stem for token in tokens) or (value == "ao" and stem.endswith("ao")):
            return value
    return "packed"


def _scene_material_channels(subtype: str) -> Tuple[str, ...]:
    return {
        "specular": ("specular", "glossiness"),
        "metallic_roughness": ("roughness", "metallic"),
        "orm": ("ao", "roughness", "metallic"),
        "rma": ("roughness", "metallic", "ao"),
    }.get(subtype, ())


def _scene_texture_group_key(path: Path) -> str:
    stem = _compact_scene_texture_name(path.stem)
    for token in ("metallicroughness", "roughnessmetallic", "occlusionroughnessmetallic", "basecolor", "basecolour", "diffuse", "albedo", "normalmap", "normalgl", "normaldx", "normal", "nrm", "bump", "roughness", "metallic", "metalness", "ambientocclusion", "occlusion", "specular", "glossiness", "gloss", "heightmap", "height", "displacement", "disp", "depth", "emissive", "emission", "glow", "illumination", "illum", "opacity", "alpha", "orm", "rma", "mra", "arm", "mask", "color", "colour", "base"):
        stem = stem.replace(token, "")
    return stem or _compact_scene_texture_name(path.stem)


def _collect_scene_texture_paths(preview_model: ModelPreviewData, result: SceneImportResult, source_path: Path) -> List[Path]:
    paths = [candidate.resolve() for candidate in tuple(result.discovered_texture_files or ()) + tuple(result.extracted_embedded_files or ()) if isinstance(candidate, Path) and candidate.is_file()]
    for mesh in preview_model.meshes:
        for attr in ("preview_texture_path", "preview_normal_texture_path", "preview_material_texture_path", "preview_height_texture_path"):
            candidate = Path(str(getattr(mesh, attr, "") or "").strip())
            if str(candidate) and candidate.is_file():
                paths.append(candidate.resolve())
    if not paths:
        for root in (source_path.parent, source_path.parent / "textures", source_path.parent.parent / "textures"):
            if not root.is_dir():
                continue
            try:
                paths.extend(candidate.resolve() for candidate in root.iterdir() if candidate.is_file() and candidate.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS)
            except OSError:
                continue
    return list(dict.fromkeys(paths))


def _scene_texture_lookup(paths: Sequence[Path]) -> Dict[str, Path]:
    lookup: Dict[str, Path] = {}
    for path in paths:
        lookup[str(path).replace("\\", "/").lower()] = path
        lookup[path.as_posix().lower()] = path
        lookup[path.name.lower()] = path
        lookup[path.stem.lower()] = path
    return lookup


def _resolve_scene_texture(value: object, source_path: Path, lookup: Mapping[str, Path]) -> Optional[Path]:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return None
    direct = Path(text)
    if direct.is_file():
        return direct.resolve()
    local = source_path.parent.joinpath(*PurePosixPath(text).parts)
    if local.is_file():
        return local.resolve()
    return lookup.get(text.lower()) or lookup.get(Path(text).name.lower()) or lookup.get(Path(text).stem.lower())


def _append_scene_material_input(mesh: ModelPreviewMesh, slot: str, path: Path, semantic_type: str, subtype: str, channels: Sequence[str] = ()) -> int:
    existing = list(getattr(mesh, "preview_material_texture_inputs", ()) or ())
    normalized = str(path).replace("\\", "/").lower()
    if any(str(getattr(item, "slot_kind", "") or "").lower() == slot and (str(getattr(item, "texture_name", "") or "").lower() == path.name.lower() or str(getattr(item, "preview_texture_path", "") or getattr(item, "source_texture_path", "") or "").replace("\\", "/").lower() == normalized) for item in existing):
        return 0
    parameter = {"base": "_baseColorTexture", "normal": "_normalTexture", "material": "_metallicRoughnessTexture", "ao": "_occlusionTexture", "emissive": "_emissiveIntensityTexture", "height": "_heightTexture"}.get(slot, "")
    parameters = (PreviewMaterialParameterInput(parameter_kind="float", parameter_name="_emissiveIntensity", value="1.000000", numeric_value=1.0),) if slot == "emissive" else ()
    existing.append(PreviewMaterialTextureInput(slot_kind=slot, parameter_name=parameter, source_texture_path=str(path), source_dds_path=str(path) if path.suffix.lower() == ".dds" else "", texture_name=path.name, preview_texture_path=str(path), semantic_type=semantic_type, semantic_subtype=subtype, packed_channels=tuple(str(value) for value in channels if str(value)), material_name=str(getattr(mesh, "material_name", "") or "").strip(), shader_family="SkinnedMeshEmissive_Ver2" if slot == "emissive" else "", confidence="scene", visualized=True, material_parameters=parameters))
    mesh.preview_material_texture_inputs = tuple(existing)
    if slot == "emissive":
        mesh.preview_sidecar_shader_family = "SkinnedMeshEmissive_Ver2"
    return 1


def _resolve_scene_mesh_textures(mesh: ModelPreviewMesh, source_path: Path, lookup: Mapping[str, Path], grouped: Mapping[str, Mapping[str, Path]], single_base: Optional[Path]) -> Dict[str, Path]:
    resolved: Dict[str, Path] = {}
    for slot, attr in (("base", "preview_texture_path"), ("normal", "preview_normal_texture_path"), ("material", "preview_material_texture_path"), ("height", "preview_height_texture_path")):
        value = _resolve_scene_texture(getattr(mesh, attr, ""), source_path, lookup)
        if value is not None:
            resolved[slot] = value
    named = _resolve_scene_texture(getattr(mesh, "texture_name", ""), source_path, lookup)
    if named is not None:
        slot = _scene_texture_slot(named)
        resolved.setdefault(slot if slot in {"base", "normal", "height"} else "material", named)
    for item in tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ()):
        slot = str(getattr(item, "slot_kind", "") or "").strip().lower()
        if slot in {"base", "normal", "material", "ao", "emissive", "height"}:
            value = _resolve_scene_texture(str(getattr(item, "preview_texture_path", "") or getattr(item, "source_texture_path", "") or getattr(item, "texture_name", "") or ""), source_path, lookup)
            if value is not None:
                resolved.setdefault(slot, value)
    group_source = resolved.get("base") or resolved.get("material") or resolved.get("normal") or resolved.get("height")
    siblings = grouped.get(_scene_texture_group_key(group_source), {}) if group_source is not None else {}
    material_key = _compact_scene_texture_name(getattr(mesh, "material_name", ""))
    if "base" not in resolved and material_key:
        for group_key, group in grouped.items():
            base = group.get("base")
            compact_key = _compact_scene_texture_name(group_key)
            if base is not None and compact_key and (compact_key in material_key or material_key in compact_key):
                resolved["base"], siblings = base, group
                break
    if "base" not in resolved and siblings.get("base") is not None:
        group_key = _compact_scene_texture_name(_scene_texture_group_key(group_source)) if group_source is not None else ""
        if not material_key or (group_key and (group_key in material_key or material_key in group_key)):
            resolved["base"] = siblings["base"]
    if "base" not in resolved and single_base is not None:
        resolved["base"] = single_base
    for slot in ("normal", "material", "emissive", "height"):
        if siblings.get(slot) is not None:
            resolved.setdefault(slot, siblings[slot])
    return resolved


def _assign_scene_mesh_textures(mesh: ModelPreviewMesh, paths: Mapping[str, Path]) -> int:
    count = 0
    base = paths.get("base")
    if base is not None:
        mesh.preview_texture_path = str(base); mesh.preview_texture_image = None
        mesh.preview_base_texture_default_path = str(base); mesh.preview_base_texture_default_name = base.name; count += 1
    normal = paths.get("normal")
    if normal is not None:
        mesh.preview_normal_texture_path = str(normal); mesh.preview_normal_texture_name = normal.name
        mesh.preview_normal_texture_strength = float(getattr(mesh, "preview_normal_texture_strength", 0.0) or 0.75)
        mesh.preview_normal_texture_default_path = str(normal); mesh.preview_normal_texture_default_name = normal.name
        mesh.preview_normal_texture_default_strength = mesh.preview_normal_texture_strength; count += 1
    material = paths.get("material")
    if material is not None:
        subtype = _scene_material_subtype(material)
        mesh.preview_material_texture_path = str(material); mesh.preview_material_texture_name = material.name
        mesh.preview_material_texture_type = subtype if subtype in {"ao", "specular", "roughness", "metallic"} else "material"
        mesh.preview_material_texture_subtype = subtype; mesh.preview_material_texture_packed_channels = _scene_material_channels(subtype)
        mesh.preview_material_texture_default_path = str(material); mesh.preview_material_texture_default_name = material.name
        mesh.preview_material_texture_default_type = mesh.preview_material_texture_type; mesh.preview_material_texture_default_subtype = subtype
        mesh.preview_material_texture_default_packed_channels = mesh.preview_material_texture_packed_channels; count += 1
        count += _append_scene_material_input(mesh, "material", material, "material", subtype, _scene_material_channels(subtype))
    if paths.get("ao") is not None:
        count += _append_scene_material_input(mesh, "ao", paths["ao"], "ao", "ao", ("ao",))
    if paths.get("emissive") is not None:
        count += _append_scene_material_input(mesh, "emissive", paths["emissive"], "emissive", "emissive")
    height = paths.get("height")
    if height is not None:
        mesh.preview_height_texture_path = str(height); mesh.preview_height_texture_name = height.name
        mesh.preview_height_texture_default_path = str(height); mesh.preview_height_texture_default_name = height.name; count += 1
    return count


def attach_scene_preview_textures(preview_model: object, scene_result: SceneImportResult, scene_path: str | Path) -> int:
    if not isinstance(preview_model, ModelPreviewData):
        return 0
    source_path = Path(scene_path).expanduser()
    try:
        source_path = source_path.resolve()
    except OSError:
        source_path = source_path.absolute()
    texture_paths = _collect_scene_texture_paths(preview_model, scene_result, source_path)
    lookup = _scene_texture_lookup(texture_paths)
    grouped: Dict[str, Dict[str, Path]] = defaultdict(dict)
    for path in texture_paths:
        grouped[_scene_texture_group_key(path)].setdefault(_scene_texture_slot(path), path)
    meshes = [mesh for mesh in preview_model.meshes if isinstance(mesh, ModelPreviewMesh)]
    bases = [path for path in texture_paths if _scene_texture_slot(path) == "base"]
    single_base = bases[0] if len(meshes) == 1 and len(bases) == 1 else None
    return sum(_assign_scene_mesh_textures(mesh, _resolve_scene_mesh_textures(mesh, source_path, lookup, grouped, single_base)) for mesh in meshes)

def _restore_rebuilt_mesh_texture_identity(
    source_mesh: ParsedMesh,
    rebuilt_mesh: ParsedMesh,
) -> int:
    if not source_mesh.submeshes or not rebuilt_mesh.submeshes:
        return 0

    def _normalize_identity(value: str) -> str:
        return str(value or "").strip().lower()

    source_by_name: Dict[str, SubMesh] = {}
    duplicate_names: set[str] = set()
    for submesh in source_mesh.submeshes:
        normalized_name = _normalize_identity(submesh.name)
        if not normalized_name:
            continue
        if normalized_name in source_by_name:
            duplicate_names.add(normalized_name)
            continue
        source_by_name[normalized_name] = submesh
    for duplicate_name in duplicate_names:
        source_by_name.pop(duplicate_name, None)

    restored_count = 0
    for index, rebuilt_submesh in enumerate(rebuilt_mesh.submeshes):
        source_submesh: Optional[SubMesh] = None
        normalized_name = _normalize_identity(rebuilt_submesh.name)
        if normalized_name:
            source_submesh = source_by_name.get(normalized_name)
        if source_submesh is None and index < len(source_mesh.submeshes):
            source_submesh = source_mesh.submeshes[index]
        if source_submesh is None:
            continue

        source_texture = str(getattr(source_submesh, "texture", "") or "").strip()
        if source_texture and str(getattr(rebuilt_submesh, "texture", "") or "").strip() != source_texture:
            rebuilt_submesh.texture = source_texture
            restored_count += 1
        if not str(getattr(rebuilt_submesh, "material", "") or "").strip():
            rebuilt_submesh.material = str(getattr(source_submesh, "material", "") or "").strip()
        if not str(getattr(rebuilt_submesh, "name", "") or "").strip():
            rebuilt_submesh.name = str(getattr(source_submesh, "name", "") or "").strip()
    return restored_count

def build_mesh_preview_from_bytes(data: bytes, virtual_path: str) -> Tuple[ModelPreviewData, ParsedMesh]:
    parsed_mesh = parse_mesh(data, virtual_path)
    preview_model = parsed_mesh_to_preview_model(parsed_mesh)
    return preview_model, parsed_mesh
