"""GLB editable-package interchange for Mesh Editor v2."""

from __future__ import annotations

import json
import copy
import math
import struct
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.core.atomic_file import atomic_write_bytes

from .mesh_exporter import write_roundtrip_manifest
from .mesh_interchange_materials import interchange_report, prepare_interchange_material, portable_texture_sources, resolve_companion_material_paths
from .mesh_glb_assets import append_animations, append_material, append_skin, skeleton_skin, transpose
from .mesh_obj_importer import (
    _OBJ_ROUNDTRIP_SIDECAR_FORMATS,
    _OBJ_ROUNDTRIP_SUPPORTED_SCHEMA_VERSION,
    _attach_obj_sidecar_edit_operations,
    _attach_obj_sidecar_lod_identity,
    _attach_obj_sidecar_source_identity,
    _attach_obj_sidecar_unknown_fields,
    _attach_obj_sidecar_warnings,
    _match_obj_roundtrip_sidecar_submeshes,
    _normalize_obj_sidecar_source_vertex_map,
    _normalize_obj_sidecar_texture_name,
    _obj_sidecar_int,
    _obj_sidecar_original_index_count,
    _obj_sidecar_original_vertex_stride,
    _obj_sidecar_source_vertex_offsets,
    _validate_obj_sidecar_skinning_metadata,
    _validate_obj_sidecar_source_index_maps,
    _validate_obj_sidecar_stable_ids,
)
from .mesh_parser import ParsedMesh, SubMesh
from .scene_geometry_utils import _restore_interchange_coordinates


def export_glb(
    mesh: ParsedMesh,
    output_dir: str | Path,
    name: str = "mesh",
    *,
    extra_payload: Mapping[str, object] | None = None,
    skeleton: object = None,
    bone_palette: Sequence[int] | None = None,
) -> list[str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    glb_path = root / f"{name or 'mesh'}.glb"
    companions, missing = [], []
    materials = []
    for submesh in mesh.submeshes:
        material, files, absent = prepare_interchange_material(submesh, root, Path(mesh.path).parent if mesh.path else None)
        materials.append(material)
        companions.extend(files)
        missing.extend(absent)
    atomic_write_bytes(glb_path, _build_glb(mesh, materials=materials, output_dir=root, skeleton=skeleton, bone_palette=bone_palette))
    payload = dict(extra_payload or {})
    payload["interchange_report"] = interchange_report(mesh, "glb", missing=missing, resolved_skeleton=bool(skeleton))
    payload["interchange_texture_sources"] = {reference: path for material in materials
                                              for reference, path in portable_texture_sources(material).items()}
    payload["interchange_joint_slots"] = _joint_slots(mesh, skeleton, bone_palette)
    payload["interchange_source_skins"] = _source_slot_skins(mesh, skeleton, bone_palette)
    if any(payload["interchange_joint_slots"]):
        from .mesh_exporter import _OBJ_ROUNDTRIP_ALLOWED_EDIT_OPERATIONS
        payload["allowed_edit_operations"] = [*_OBJ_ROUNDTRIP_ALLOWED_EDIT_OPERATIONS, "replace_skin_weights_same_count"]
    sidecar_path = write_roundtrip_manifest(mesh, glb_path, extra_payload=payload)
    return list(dict.fromkeys([str(glb_path), str(sidecar_path), *companions]))


def import_glb_with_sidecar(path: str | Path) -> ParsedMesh:
    glb_path = _editable_glb_path(Path(path))
    sidecar = _load_glb_roundtrip_sidecar(glb_path)
    from .scene_gltf_import import import_gltf
    mesh = import_gltf(glb_path, preserve_authoring=True).mesh
    _attach_glb_sidecar(mesh, sidecar, glb_path.name)
    return mesh


def _editable_glb_path(path: Path) -> Path:
    if path.is_dir():
        for name in ("mesh.glb", "edited_mesh.glb", "edited.glb"):
            candidate = path / name
            if candidate.is_file():
                return candidate
    return path


def _load_glb_roundtrip_sidecar(glb_path: Path) -> dict[str, object]:
    for candidate in (Path(f"{glb_path}.meta.json"), glb_path.parent / "mesh.cdmeta.json"):
        if not candidate.is_file():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"GLB sidecar is not a JSON object: {candidate}")
        payload_format = str(payload.get("format", "") or "").strip()
        if payload_format and payload_format not in _OBJ_ROUNDTRIP_SIDECAR_FORMATS:
            raise ValueError(f"Unsupported GLB sidecar format: {payload_format!r}.")
        schema_version = payload.get("schema_version")
        if schema_version is not None and int(schema_version) != _OBJ_ROUNDTRIP_SUPPORTED_SCHEMA_VERSION:
            raise ValueError(f"Unsupported GLB sidecar schema version: {schema_version!r}.")
        _validate_obj_sidecar_stable_ids(payload)
        _validate_obj_sidecar_skinning_metadata(payload)
        _validate_obj_sidecar_source_index_maps(payload)
        resolve_companion_material_paths(payload, candidate.parent)
        return payload
    raise ValueError("GLB sidecar is required for editable mesh package import.")


def _attach_glb_sidecar(mesh: ParsedMesh, sidecar: dict[str, object], source_name: str) -> None:
    mesh.path = str(sidecar.get("source_path", "") or mesh.path or "")
    mesh.format = str(sidecar.get("source_format", "") or mesh.format or "")
    submesh_list = [{"name": str(submesh.name or ""), "material": str(submesh.material or "")} for submesh in mesh.submeshes]
    matched_entries = _match_obj_roundtrip_sidecar_submeshes(
        sidecar,
        submesh_list,
        source_path=str(sidecar.get("source_path", "") or ""),
        source_format=str(sidecar.get("source_format", "") or ""),
    )
    _attach_obj_sidecar_source_identity(mesh, sidecar)
    _attach_obj_sidecar_lod_identity(mesh, sidecar)
    _attach_obj_sidecar_warnings(mesh, matched_entries, {})
    joint_slots = sidecar.get("interchange_joint_slots", [])
    source_skins = sidecar.get("interchange_source_skins", [])
    for submesh, entry in zip(mesh.submeshes, matched_entries):
        has_incoming_weights = bool(submesh.bone_indices)
        if has_incoming_weights and not submesh.interchange_skin:
            raise ValueError("Edited mesh joint attributes have no skin binding.")
        entry_index = int(entry.get("submesh_index", -1)) if isinstance(entry, dict) else -1
        source_skin = source_skins[entry_index] if 0 <= entry_index < len(source_skins) else None
        _attach_glb_submesh_sidecar(submesh, entry, source_skin=source_skin,
                                   legacy_bind_coordinates=sidecar.get("interchange_report", {}).get("format") in {"obj", "fbx"})
        if isinstance(entry, dict):
            entry_index = int(entry.get("submesh_index", -1))
            slots = joint_slots[entry_index] if 0 <= entry_index < len(joint_slots) else {}
            if has_incoming_weights:
                _restore_source_joint_slots(submesh, slots, entry)
            if "interchange_node_index" in entry:
                submesh.interchange_node_index = int(entry["interchange_node_index"])
            if 0 <= entry_index < len(source_skins) and source_skins[entry_index]:
                submesh.interchange_skin = copy.deepcopy(source_skins[entry_index])
    # Geometry is restored to source coordinates; its graph and existing clips
    # must follow the same frame. Animation editing is intentionally excluded.
    mesh.interchange_nodes = copy.deepcopy(sidecar.get("interchange_nodes", []))
    mesh.interchange_animations = copy.deepcopy(sidecar.get("interchange_animations", []))
    _attach_obj_sidecar_edit_operations(mesh, matched_entries, sidecar, source_name)


def _attach_glb_submesh_sidecar(submesh: SubMesh, entry: object, *, source_skin=None, legacy_bind_coordinates=False) -> None:
    if not isinstance(entry, dict):
        return
    _restore_interchange_coordinates(submesh, entry, source_skin, legacy_bind_coordinates=legacy_bind_coordinates)
    exported_map = _normalize_obj_sidecar_source_vertex_map(entry, expected_count=int(entry.get("original_vertex_count", len(submesh.vertices))))
    ids = _recover_vertex_ids(submesh, entry)
    if ids:
        submesh.interchange_vertex_ids = ids
    source_vertex_map = [exported_map[i] for i in ids] if ids and exported_map else exported_map
    submesh.source_vertex_map = source_vertex_map
    submesh.source_vertex_map_authority = "target_donor_record" if source_vertex_map else ""
    submesh.source_vertex_offsets = _obj_sidecar_source_vertex_offsets(entry, source_vertex_map)
    submesh.source_index_offset = _obj_sidecar_int(entry, "original_index_offset")
    submesh.source_index_count = _obj_sidecar_original_index_count(entry)
    submesh.source_vertex_stride = _obj_sidecar_original_vertex_stride(entry)
    submesh.source_descriptor_offset = _obj_sidecar_int(entry, "original_descriptor_offset")
    submesh.texture = _normalize_obj_sidecar_texture_name(entry) or submesh.texture
    _attach_obj_sidecar_unknown_fields(submesh, entry)


def _recover_vertex_ids(submesh, entry):
    vertices = entry.get("interchange_vertices", [])
    if not vertices:
        return []  # Older packages retain their existing positional contract.
    ids = list(getattr(submesh, "interchange_vertex_ids", ()) or ())
    if ids:
        if len(ids) != len(submesh.vertices) or any(not 0 <= i < len(vertices) for i in ids):
            raise ValueError("Edited mesh contains invalid CDMW vertex identifiers.")
        return ids
    # FBX and some Blender exports drop custom attributes. Only recover a
    # missing identifier from unambiguous, unchanged source coordinates.
    lookup = {}
    for i, vertex in enumerate(vertices):
        lookup.setdefault(tuple(round(float(v), 5) for v in vertex), []).append(i)
    for vertex in submesh.vertices:
        candidates = lookup.get(tuple(round(float(v), 5) for v in vertex), [])
        if len(candidates) != 1:
            raise ValueError("Cannot prove edited vertex identity; retain the CDMW vertex attribute in GLB, or use the OBJ package.")
        ids.append(candidates[0])
    return ids


def _joint_slots(mesh, skeleton=None, palette=None):
    resolved = skeleton_skin(skeleton or getattr(mesh, "interchange_skeleton", None))
    if palette is None:
        palette = getattr(mesh, "interchange_bone_palette", None)
    result = []
    for part in mesh.submeshes:
        skin = part.interchange_skin or resolved
        slots = {}
        if skin and part.bone_indices and (part.interchange_skin or palette is None or palette):
            source_slots = range(len(skin["joints"])) if part.interchange_skin or palette is None else range(len(palette))
            for slot in source_slots:
                joint = slot if part.interchange_skin else skin["bone_map"].get(palette[slot] if palette is not None else slot, -1)
                if not 0 <= joint < len(skin["joints"]):
                    raise ValueError("Source influence slot is unresolved against its skeleton.")
                name = str(skin["nodes"][skin["joints"][joint]].get("name", ""))
                if not name or name in slots:
                    raise ValueError("Source skeleton requires unique joint names for editable interchange.")
                slots[name] = slot
        result.append(slots)
    return result


def _source_slot_skins(mesh, skeleton=None, palette=None):
    resolved = skeleton_skin(skeleton or getattr(mesh, "interchange_skeleton", None))
    if palette is None:
        palette = getattr(mesh, "interchange_bone_palette", None)
    result = []
    for part in mesh.submeshes:
        skin = copy.deepcopy(part.interchange_skin or resolved)
        if not part.bone_indices or not skin or (not part.interchange_skin and palette is not None and not palette):
            result.append({})
            continue
        if not part.interchange_skin and palette is not None:
            order = [skin["bone_map"][bone] for bone in palette]
            skin["joints"] = [skin["joints"][i] for i in order]
            skin["inverse_bind_matrices"] = [skin["inverse_bind_matrices"][i] for i in order]
        result.append(skin)
    return result


def _restore_source_joint_slots(part, slots, entry):
    if not part.bone_indices:
        return
    if not slots and not part.interchange_skin:
        return  # Unresolved bindings are protected source data in the companion.
    if not slots:
        raise ValueError("Edited skin has no verified source joint mapping; re-export with the resolved skeleton.")
    skin = part.interchange_skin
    names = [str(skin["nodes"][joint].get("name", "")) for joint in skin.get("joints", [])]
    if len(set(names)) != len(names):
        raise ValueError("Edited skeleton has duplicate joint names.")
    restored = []
    for indices, weights in zip(part.bone_indices, part.bone_weights):
        row = []
        for joint, weight in zip(indices, weights):
            if not 0 <= joint < len(names) or (weight > 0 and names[joint] not in slots):
                raise ValueError("Edited skin references a joint absent from the source palette.")
            row.append(int(slots.get(names[joint], 0)))
        restored.append(tuple(row))
    part.bone_indices = restored
    original_indices = entry.get("interchange_bone_indices", [])
    original_weights = entry.get("interchange_bone_weights", [])
    changed = False
    for i, source in enumerate(getattr(part, "interchange_vertex_ids", ()) or part.source_vertex_map):
        if source >= len(original_indices) or source >= len(original_weights):
            continue
        def influences(indices, weights):
            result = {}
            total = sum(weights)
            if total <= 0:
                return result
            for joint, weight in zip(indices, weights):
                if weight > 0:
                    result[joint] = result.get(joint, 0.0) + weight / total
            return result
        actual = influences(part.bone_indices[i], part.bone_weights[i])
        expected = influences(original_indices[source], original_weights[source])
        if actual.keys() == expected.keys() and all(abs(actual[joint] - expected[joint]) <= 1e-5 for joint in actual):
            part.bone_indices[i] = tuple(original_indices[source])
            part.bone_weights[i] = tuple(original_weights[source])
        else:
            changed = True
    if changed:
        for i, (indices, weights) in enumerate(zip(part.bone_indices, part.bone_weights)):
            merged = influences(indices, weights)
            part.bone_indices[i] = tuple(merged)
            part.bone_weights[i] = tuple(merged.values())
    if entry.get("interchange_skin"):
        part.interchange_skin = copy.deepcopy(entry["interchange_skin"])
    part._cdmw_source_palette_size = max(int(slot) for slot in slots.values()) + 1
    part._cdmw_verified_skin_mapping = True
    part._cdmw_skin_weights_changed = changed


def _glb_geometry(submesh, floats, indices):
    vertices = [tuple(float(value) for value in vertex[:3]) for vertex in tuple(submesh.vertices or ())]
    faces = [tuple(int(value) for value in face[:3]) for face in tuple(submesh.faces or ())]
    if not vertices or not faces:
        raise ValueError("GLB editable export requires triangle geometry.")
    if any(len(face) != 3 or min(face) < 0 or max(face) >= len(vertices) for face in faces):
        raise ValueError("GLB face references a missing vertex.")
    attributes = {"POSITION": floats(vertices, "VEC3", include_min_max=True)}
    attributes["_CDMW_VERTEX_ID"] = floats([(float(i),) for i in range(len(vertices))], "SCALAR")
    for key, rows, type_name in (("NORMAL", submesh.normals, "VEC3"), ("COLOR_0", submesh.vertex_colors, "VEC4")):
        if rows:
            if len(rows) != len(vertices):
                raise ValueError(f"GLB {key} count differs from vertex count.")
            attributes[key] = floats(rows, type_name)
    uv_sets = dict(submesh.uv_sets)
    if submesh.uvs:
        uv_sets[0] = submesh.uvs
    for uv_index, rows in sorted(uv_sets.items()):
        if len(rows) != len(vertices):
            raise ValueError("GLB UV count differs from vertex count.")
        # glTF uses the same image origin as the game. OBJ/FBX use the
        # opposite origin and perform their own V conversion.
        attributes[f"TEXCOORD_{uv_index}"] = floats(rows, "VEC2")
    if submesh.tangents:
        signs = getattr(submesh, "tangent_signs", [1.0] * len(vertices))
        if len(submesh.tangents) != len(vertices) or len(signs) != len(vertices):
            raise ValueError("GLB tangent count differs from vertex count.")
        attributes["TANGENT"] = floats([tuple(row) + (float(sign),) for row, sign in zip(submesh.tangents, signs)], "VEC4")
    index_accessor = indices([value for face in faces for value in face])
    return vertices, attributes, index_accessor


def _glb_skin_attributes(submesh, skin, bone_palette, vertices, attributes, floats, integers):
    width = max((len(row) for row in submesh.bone_indices), default=0)
    if len(submesh.bone_indices) != len(vertices) or len(submesh.bone_weights) != len(vertices):
        raise ValueError("GLB skin count differs from vertex count.")
    mapped_rows = []
    for indices, weights in zip(submesh.bone_indices, submesh.bone_weights):
        if len(indices) != len(weights) or not weights or sum(weights) <= 0 or any(w < 0 or not math.isfinite(w) for w in weights):
            raise ValueError("GLB skin contains invalid weights.")
        mapped = []
        for joint, weight in zip(indices, weights):
            if weight == 0:
                mapped.append(0)  # Unused PAC padding slots need no binding.
                continue
            if not submesh.interchange_skin:
                if bone_palette is not None and not 0 <= joint < len(bone_palette):
                    raise ValueError("GLB influence slot is outside its source palette.")
                joint = bone_palette[joint] if bone_palette is not None else joint
                joint = skin["bone_map"].get(joint, -1)
            if not 0 <= joint < len(skin["joints"]):
                raise ValueError("GLB joint is unresolved against its skeleton.")
            mapped.append(joint)
        mapped_rows.append(mapped)
    for group in range((width + 3) // 4):
        joints, weights = [], []
        for row, values in zip(mapped_rows, submesh.bone_weights):
            total = sum(values)
            joints.append(tuple((row + [0] * (width + 4))[group * 4:group * 4 + 4]))
            weights.append(tuple(([v / total for v in values] + [0.0] * (width + 4))[group * 4:group * 4 + 4]))
        attributes[f"JOINTS_{group}"] = integers(joints, "VEC4")
        attributes[f"WEIGHTS_{group}"] = floats(weights, "VEC4")


def _build_glb(mesh: ParsedMesh, *, materials=None, output_dir=None, skeleton=None, bone_palette=None) -> bytes:
    buffer = bytearray()
    buffer_views: list[dict[str, object]] = []
    accessors: list[dict[str, object]] = []
    gltf_meshes: list[dict[str, object]] = []
    nodes: list[dict[str, object]] = []
    document = {"asset": {"version": "2.0", "generator": "Crimson Desert Mod Workbench"},
                "scene": 0, "scenes": [{"nodes": []}], "nodes": nodes, "meshes": gltf_meshes,
                "materials": [], "bufferViews": buffer_views, "accessors": accessors}
    def floats(rows, type_name, target=34962, **kwargs):
        return _float_accessor(buffer, buffer_views, accessors, rows, type_name, target, **kwargs)
    def indices(values):
        return _index_accessor(buffer, buffer_views, accessors, values)
    def integers(rows, type_name):
        return _integer_accessor(buffer, buffer_views, accessors, rows, type_name)
    resolved_skin = skeleton_skin(skeleton or getattr(mesh, "interchange_skeleton", None))
    if bone_palette is None:
        bone_palette = getattr(mesh, "interchange_bone_palette", None)
    skins_by_identity, node_mapping = {}, {}
    source_nodes = getattr(mesh, "interchange_nodes", ())
    source_mapping = None
    occupied_nodes = set()
    if source_nodes:
        nodes.extend([{k: copy.deepcopy(v) for k, v in node.items()
                       if k in {"name", "matrix", "translation", "rotation", "scale", "children", "extras"}}
                      for node in source_nodes])
        source_mapping = {i: i for i in range(len(nodes))}
        node_mapping.update({i: [i] for i in range(len(nodes))})
        children = {int(child) for node in nodes for child in node.get("children", [])}
        document["scenes"][0]["nodes"] = [i for i in range(len(nodes)) if i not in children]
    for index, submesh in enumerate(tuple(mesh.submeshes or ())):
        vertices, attributes, index_accessor = _glb_geometry(submesh, floats, indices)
        material = materials[index] if materials is not None else {"pbrMetallicRoughness": {"metallicFactor": 0.0}}
        material = append_material(document, material, Path(output_dir or "."),
                                   lambda raw: _append_buffer_view(buffer, buffer_views, raw, 0))
        material["name"] = str(submesh.material or submesh.name or f"material_{index}")
        material_index = len(document["materials"])
        document["materials"].append(material)
        name = str(submesh.name or f"submesh_{index}")
        primitive = {"attributes": attributes, "indices": index_accessor, "material": material_index}
        if submesh.morph_targets:
            primitive["targets"] = []
            for name, rows in submesh.morph_targets.items():
                if len(rows) != len(vertices):
                    raise ValueError(f"GLB morph target count mismatch: {name}.")
                target = {"POSITION": floats([tuple(t[a] - v[a] for a in range(3)) for t, v in zip(rows, vertices)], "VEC3", include_min_max=True)}
                if name in submesh.morph_normals:
                    normal_rows = submesh.morph_normals[name]
                    if len(normal_rows) != len(vertices) or len(submesh.normals) != len(vertices):
                        raise ValueError("GLB morph normal count mismatch.")
                    target["NORMAL"] = floats([tuple(t[a] - v[a] for a in range(3)) for t, v in zip(normal_rows, submesh.normals)], "VEC3")
                if name in submesh.morph_tangents:
                    tangent_rows = submesh.morph_tangents[name]
                    if len(tangent_rows) != len(vertices) or len(submesh.tangents) != len(vertices):
                        raise ValueError("GLB morph tangent count mismatch.")
                    target["TANGENT"] = floats([tuple(t[a] - v[a] for a in range(3)) for t, v in zip(tangent_rows, submesh.tangents)], "VEC3")
                primitive["targets"].append(target)
        name = str(submesh.name or f"submesh_{index}")
        gltf_meshes.append(
            {
                "name": name,
                "primitives": [primitive],
            }
        )
        if submesh.morph_targets:
            gltf_meshes[-1]["extras"] = {"targetNames": list(submesh.morph_targets)}
            gltf_meshes[-1]["weights"] = [float(submesh.morph_weights.get(name, 0.0)) for name in submesh.morph_targets]
        node = {"name": name, "mesh": index}
        original_node = getattr(submesh, "interchange_node_index", -1)
        has_original_node = source_mapping is not None and original_node in source_mapping
        transform = getattr(submesh, "interchange_transform", ())
        if transform and not has_original_node:
            node["matrix"] = list(transpose(transform))
        skin = submesh.interchange_skin or resolved_skin
        if skin and submesh.bone_indices and (submesh.interchange_skin or bone_palette is None or bone_palette):
            identity = json.dumps(skin, sort_keys=True)
            if identity not in skins_by_identity:
                skins_by_identity[identity] = append_skin(document, skin, floats, source_mapping if submesh.interchange_skin else None)
            skin_index, mapping = skins_by_identity[identity]
            node["skin"] = skin_index
            for old, new in mapping.items():
                node_mapping.setdefault(old, [])
                if new not in node_mapping[old]:
                    node_mapping[old].append(new)
            _glb_skin_attributes(submesh, skin, bone_palette, vertices, attributes, floats, integers)
        if has_original_node and original_node not in occupied_nodes:
            node_index = original_node
            nodes[node_index].update({k: v for k, v in node.items() if k != "name"})
            occupied_nodes.add(original_node)
        else:
            node_index = len(nodes)
            nodes.append(node)
            if has_original_node:
                nodes[original_node].setdefault("children", []).append(node_index)
            else:
                document["scenes"][0]["nodes"].append(node_index)
        if has_original_node:
            node_mapping.setdefault((original_node, "weights"), []).append(node_index)
        elif original_node >= 0:
            node_mapping.setdefault(original_node, []).append(node_index)
    append_animations(document, mesh, node_mapping, floats)
    extensions = set()
    def find_extensions(value):
        if isinstance(value, dict):
            extensions.update(value.get("extensions", {}).keys())
            for child in value.values():
                find_extensions(child)
        elif isinstance(value, list):
            for child in value:
                find_extensions(child)
    find_extensions(document)
    if extensions:
        document["extensionsUsed"] = sorted(extensions)
    document["buffers"] = [{"byteLength": len(buffer)}]
    return _pack_glb(document, bytes(buffer))


def _rows_or_default(rows: Sequence[Sequence[float]], count: int, default: tuple[float, ...]) -> list[tuple[float, ...]]:
    values = [tuple(float(value) for value in tuple(row)[: len(default)]) for row in tuple(rows or ())]
    if len(values) != count:
        return [default] * count
    return values


def _float_accessor(
    buffer: bytearray,
    buffer_views: list[dict[str, object]],
    accessors: list[dict[str, object]],
    rows: Sequence[Sequence[float]],
    type_name: str,
    target: int,
    *,
    include_min_max: bool = False,
) -> int:
    component_count = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[type_name]
    if any(len(row) != component_count or any(not math.isfinite(float(v)) for v in row) for row in rows):
        raise ValueError(f"GLB {type_name} contains incomplete or non-finite values.")
    raw = b"".join(struct.pack("<" + ("f" * component_count), *tuple(row)[:component_count]) for row in rows)
    view = _append_buffer_view(buffer, buffer_views, raw, target)
    accessor: dict[str, object] = {"bufferView": view, "componentType": 5126, "count": len(rows), "type": type_name}
    if include_min_max and rows:
        accessor["min"] = [min(float(row[axis]) for row in rows) for axis in range(component_count)]
        accessor["max"] = [max(float(row[axis]) for row in rows) for axis in range(component_count)]
    accessors.append(accessor)
    return len(accessors) - 1


def _integer_accessor(buffer, buffer_views, accessors, rows, type_name):
    width = 4 if type_name == "VEC4" else 1
    if any(len(row) != width or any(int(v) != v or v < 0 or v > 65535 for v in row) for row in rows):
        raise ValueError("GLB integer vertex attribute is invalid.")
    raw = b"".join(struct.pack("<" + "H" * width, *row) for row in rows)
    view = _append_buffer_view(buffer, buffer_views, raw, 34962)
    accessors.append({"bufferView": view, "componentType": 5123, "count": len(rows), "type": type_name})
    return len(accessors) - 1


def _index_accessor(
    buffer: bytearray,
    buffer_views: list[dict[str, object]],
    accessors: list[dict[str, object]],
    indices: Sequence[int],
) -> int:
    max_index = max(indices, default=0)
    component_type = 5123 if max_index <= 65535 else 5125
    pack_code = "H" if component_type == 5123 else "I"
    raw = b"".join(struct.pack("<" + pack_code, int(index)) for index in indices)
    view = _append_buffer_view(buffer, buffer_views, raw, 34963)
    accessors.append(
        {
            "bufferView": view,
            "componentType": component_type,
            "count": len(indices),
            "type": "SCALAR",
            "min": [min(indices) if indices else 0],
            "max": [max_index],
        }
    )
    return len(accessors) - 1


def _append_buffer_view(buffer: bytearray, buffer_views: list[dict[str, object]], raw: bytes, target: int) -> int:
    offset = len(buffer)
    buffer.extend(raw)
    buffer.extend(b"\x00" * ((4 - (len(buffer) % 4)) % 4))
    buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), **({"target": target} if target else {})})
    return len(buffer_views) - 1


def _pack_glb(document: dict[str, object], binary: bytes) -> bytes:
    json_chunk = _pad4(json.dumps(document, separators=(",", ":")).encode("utf-8"), b" ")
    bin_chunk = _pad4(binary, b"\x00")
    total_length = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    return b"glTF" + struct.pack("<II", 2, total_length) + struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk + struct.pack(
        "<I4s", len(bin_chunk), b"BIN\x00"
    ) + bin_chunk


def _pad4(data: bytes, pad_byte: bytes) -> bytes:
    return data + pad_byte * ((4 - (len(data) % 4)) % 4)
