from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional
from urllib.parse import unquote, urlparse

from cdmw.models import PreviewMaterialParameterInput

from .mesh_parser import ParsedMesh, SubMesh, _compute_smooth_normals
from .scene_geometry_utils import (
    _bbox,
    _copy_submesh_with_transform,
    _dedupe_paths,
    _identity_matrix,
    _multiply_matrix,
    _parse_float_list,
    _resolve_scene_uri,
)
from .scene_material_audit import (
    SceneMaterialTextureSlot,
    _apply_scene_material_slots_to_submesh,
    _scene_material_slot,
    _scene_preview_color_parameter,
    _scene_preview_float_parameter,
)

SCENE_TEXTURE_SOURCE_EXTENSIONS = {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp"}


def _resolve_local_texture_reference(source_path: Path, texture_reference: str) -> Optional[Path]:
    from .scene_importer import _resolve_local_texture_reference as resolve

    return resolve(source_path, texture_reference)

@dataclass(slots=True)
class _ColladaGeometry:
    geometry_id: str
    name: str
    primitives: list[SubMesh]


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
    asset_matrix = _collada_asset_matrix(root, prefix, ns)
    geometries: dict[str, _ColladaGeometry] = {}
    for geometry in root.findall(f".//{prefix}library_geometries/{prefix}geometry", ns):
        parsed = _parse_collada_geometry(geometry, material_names, prefix, ns)
        geometries[parsed.geometry_id] = parsed

    submeshes: list[SubMesh] = []
    for instance in _iter_collada_geometry_instances(root, prefix, ns, asset_matrix=asset_matrix):
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
                copied = _copy_submesh_with_transform(primitive, asset_matrix)
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
    has_uv_input = any(semantic == "TEXCOORD" for _offset, semantic, _source in inputs)
    has_normal_input = any(semantic == "NORMAL" for _offset, semantic, _source in inputs)
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
                    local_index = len(vertices)
                    corner_to_index[corner] = local_index
                    vertices.append(position)  # type: ignore[arg-type]
                    if has_uv_input:
                        uv = _source_tuple(sources, corner[2], corner[3], 2)
                        uvs.append((float(uv[0]), 1.0 - float(uv[1])))
                    if has_normal_input:
                        normal = _source_tuple(sources, corner[4], corner[5], 3)
                        normals.append(normal)  # type: ignore[arg-type]
                face_indices.append(local_index)
            if len(face_indices) == 3:
                faces.append((face_indices[0], face_indices[1], face_indices[2]))
    if len(uvs) != len(vertices):
        uvs = []
    if len(normals) != len(vertices):
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
    *,
    asset_matrix: Optional[tuple[float, ...]] = None,
) -> list[dict[str, object]]:
    instances: list[dict[str, object]] = []
    visual_scene = _collada_visual_scene(root, prefix, ns)
    if visual_scene is None:
        return instances

    def walk(node: ET.Element, parent_matrix: tuple[float, ...]) -> None:
        world_matrix = _multiply_matrix(parent_matrix, _collada_node_matrix(node, prefix, ns))
        node_name = node.attrib.get("name", "") or node.attrib.get("id", "")
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
                    "matrix": world_matrix,
                    "materials": materials,
                }
            )
        for child in node.findall(f"{prefix}node", ns):
            walk(child, world_matrix)

    root_matrix = asset_matrix or _collada_asset_matrix(root, prefix, ns)
    for node in visual_scene.findall(f"{prefix}node", ns):
        walk(node, root_matrix)
    return instances


def _collada_visual_scene(
    root: ET.Element,
    prefix: str,
    ns: dict[str, str],
) -> Optional[ET.Element]:
    visual_scenes = root.findall(f".//{prefix}library_visual_scenes/{prefix}visual_scene", ns)
    selected = root.find(f"{prefix}scene/{prefix}instance_visual_scene", ns)
    selected_id = selected.attrib.get("url", "").lstrip("#") if selected is not None else ""
    if selected_id:
        for visual_scene in visual_scenes:
            if visual_scene.attrib.get("id", "") == selected_id:
                return visual_scene
    return visual_scenes[0] if visual_scenes else None


def _collada_asset_matrix(
    root: ET.Element,
    prefix: str,
    ns: dict[str, str],
) -> tuple[float, ...]:
    unit_scale = 1.0
    unit = root.find(f"{prefix}asset/{prefix}unit", ns)
    if unit is not None:
        try:
            candidate = float(unit.attrib.get("meter", "1") or 1.0)
            if math.isfinite(candidate) and candidate > 0.0:
                unit_scale = candidate
        except ValueError:
            pass
    up_axis = str(root.findtext(f"{prefix}asset/{prefix}up_axis", default="Y_UP", namespaces=ns) or "Y_UP").strip().upper()
    if up_axis == "Z_UP":
        axis_matrix = (
            1.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, -1.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        )
    elif up_axis == "X_UP":
        axis_matrix = (0.0, -1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    else:
        axis_matrix = _identity_matrix()
    scale_matrix = (
        unit_scale, 0.0, 0.0, 0.0,
        0.0, unit_scale, 0.0, 0.0,
        0.0, 0.0, unit_scale, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )
    return _multiply_matrix(axis_matrix, scale_matrix)


def _collada_node_matrix(
    node: ET.Element,
    prefix: str,
    ns: dict[str, str],
) -> tuple[float, ...]:
    del prefix, ns
    matrix = _identity_matrix()
    for child in list(node):
        operation = _collada_transform_matrix(_collada_local_name(child.tag), _parse_float_list(child.text or ""))
        if operation is not None:
            matrix = _multiply_matrix(matrix, operation)
    return matrix


def _collada_local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def _collada_transform_matrix(kind: str, values: list[float]) -> Optional[tuple[float, ...]]:
    if kind == "matrix" and len(values) >= 16:
        return tuple(values[column * 4 + row] for row in range(4) for column in range(4))
    if kind == "translate" and len(values) >= 3:
        return (1.0, 0.0, 0.0, values[0], 0.0, 1.0, 0.0, values[1], 0.0, 0.0, 1.0, values[2], 0.0, 0.0, 0.0, 1.0)
    if kind == "scale" and len(values) >= 3:
        return (values[0], 0.0, 0.0, 0.0, 0.0, values[1], 0.0, 0.0, 0.0, 0.0, values[2], 0.0, 0.0, 0.0, 0.0, 1.0)
    if kind == "rotate" and len(values) >= 4:
        return _collada_axis_rotation(values[0], values[1], values[2], values[3])
    return None


def _collada_axis_rotation(x: float, y: float, z: float, degrees: float) -> tuple[float, ...]:
    length = math.sqrt(x * x + y * y + z * z)
    if length <= 1e-12:
        return _identity_matrix()
    x, y, z = x / length, y / length, z / length
    angle = math.radians(degrees)
    cosine, sine = math.cos(angle), math.sin(angle)
    complement = 1.0 - cosine
    return (
        cosine + x * x * complement, x * y * complement - z * sine, x * z * complement + y * sine, 0.0,
        y * x * complement + z * sine, cosine + y * y * complement, y * z * complement - x * sine, 0.0,
        z * x * complement - y * sine, z * y * complement + x * sine, cosine + z * z * complement, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )


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
