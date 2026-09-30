"""Materials, resolved skeletons and retained clips for GLB mesh interchange."""

from __future__ import annotations

import copy
from pathlib import Path

from .scene_geometry_utils import _identity_matrix, _invert_affine_matrix, _multiply_matrix


def transpose(matrix):
    return tuple(float(matrix[column * 4 + row]) for row in range(4) for column in range(4))


def skeleton_skin(skeleton):
    from .scene_gltf_import import _compose_trs_matrix
    bones = list(getattr(skeleton, "bones", ()) or ())
    if not bones:
        return {}
    by_id = {int(bone.index): bone for bone in bones}
    slots = {int(bone.index): index for index, bone in enumerate(bones)}
    globals_by_id, visiting = {}, set()
    def global_matrix(index):
        if index in globals_by_id:
            return globals_by_id[index]
        if index in visiting:
            raise ValueError("Skeleton contains a parent cycle.")
        visiting.add(index)
        bone = by_id[index]
        if len(bone.bind_matrix) == 16:
            matrix = transpose(bone.bind_matrix)
        else:
            matrix = _compose_trs_matrix(tuple(bone.position), tuple(bone.rotation), tuple(bone.scale))
            if bone.parent_index in by_id:
                matrix = _multiply_matrix(global_matrix(bone.parent_index), matrix)
        globals_by_id[index] = matrix
        visiting.remove(index)
        return matrix
    nodes, inverses = [], []
    for bone in bones:
        matrix = global_matrix(int(bone.index))
        inverse = _invert_affine_matrix(matrix)
        if inverse is None:
            raise ValueError(f"Skeleton bind matrix is singular: {bone.name}.")
        local = matrix
        if bone.parent_index in by_id:
            parent_inverse = _invert_affine_matrix(global_matrix(int(bone.parent_index)))
            if parent_inverse is None:
                raise ValueError("Skeleton parent bind matrix is singular.")
            local = _multiply_matrix(parent_inverse, matrix)
        nodes.append({"name": str(bone.name), "matrix": list(transpose(local)),
                      "children": [slots[int(child.index)] for child in bones if child.parent_index == bone.index],
                      "extras": {"cdmw_bone_index": int(bone.index)}})
        inverses.append(list(transpose(inverse)))
    return {"nodes": nodes, "joints": list(range(len(nodes))), "inverse_bind_matrices": inverses,
            "bone_map": slots, "name": Path(str(getattr(skeleton, "path", "") or "Skeleton")).stem}


def authored_fbx_skeleton(mesh):
    """Resolve a retained glTF joint hierarchy for the existing native FBX writer."""
    import json
    from .scene_gltf_import import _gltf_node_matrix
    from .skeleton_parser import Bone, Skeleton
    skins = [part.interchange_skin for part in mesh.submeshes if part.interchange_skin and part.bone_indices]
    if not skins:
        return None, None
    if len({json.dumps(skin, sort_keys=True) for skin in skins}) != 1:
        raise ValueError("FBX export requires one shared skeleton; use GLB for a scene with different rigs.")
    skin = skins[0]
    nodes = skin["nodes"]
    parents = {child: index for index, node in enumerate(nodes) for child in node.get("children", [])}
    selected = set(skin["joints"])
    for joint in tuple(selected):
        seen = set()
        while joint in parents:
            if joint in seen:
                raise ValueError("Authored skeleton contains a parent cycle.")
            seen.add(joint)
            joint = parents[joint]
            selected.add(joint)
    slots = {node: i for i, node in enumerate(sorted(selected))}
    matrices = {}
    def world(index):
        if index not in matrices:
            local = _gltf_node_matrix(nodes[index])
            matrices[index] = _multiply_matrix(world(parents[index]), local) if index in parents else local
        return matrices[index]
    bones = []
    for index in sorted(selected):
        matrix = world(index)
        inverse = _invert_affine_matrix(matrix)
        if inverse is None:
            raise ValueError("Authored skeleton has a singular bind matrix.")
        bones.append(Bone(index=slots[index], name=str(nodes[index].get("name", f"joint_{index}")),
                          parent_index=slots.get(parents.get(index), -1), bind_matrix=transpose(matrix),
                          inv_bind_matrix=transpose(inverse), position=(matrix[3], matrix[7], matrix[11])))
    return Skeleton(path=skin.get("name", "Skeleton"), bones=bones, bone_count=len(bones)), [slots[index] for index in skin["joints"]]


def append_material(document, material, output_dir, append_view):
    material = copy.deepcopy(material)
    material.pop("_cdmw_texture_sources", None)
    textures = material.pop("textures", {})
    for key, info in textures.items():
        if key in {"roughnessTexture", "metallicTexture", "opacityTexture"}:
            continue
        if info.get("missing") or not info.get("path"):
            continue
        path = Path(info["path"])
        path = path if path.is_absolute() else output_dir / path
        if not path.is_file():
            continue
        raw = path.read_bytes()
        mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError(f"GLB texture was not converted to PNG/JPEG: {path}.")
        images = document.setdefault("images", [])
        images.append({"name": path.stem, "mimeType": mime, "bufferView": append_view(raw)})
        gltf_textures = document.setdefault("textures", [])
        texture = {"source": len(images) - 1}
        if "sampler" in info:
            samplers = document.setdefault("samplers", [])
            if info["sampler"] not in samplers:
                samplers.append(copy.deepcopy(info["sampler"]))
            texture["sampler"] = samplers.index(info["sampler"])
        gltf_textures.append(texture)
        texture_info = {k: copy.deepcopy(v) for k, v in info.items() if k in {"texCoord", "scale", "strength", "extensions"}}
        texture_info["index"] = len(gltf_textures) - 1
        location = info.get("location") or (["pbrMetallicRoughness", key] if key in {"baseColorTexture", "metallicRoughnessTexture"} else [key])
        if key == "specularTexture" and not info.get("location"):
            location = ["extensions", "KHR_materials_specular", "specularColorTexture"]
        target = material
        for segment in location[:-1]:
            target = target.setdefault(segment, {})
        target[location[-1]] = texture_info
    return material


def append_skin(document, skin, float_accessor, source_mapping=None):
    nodes = document["nodes"]
    start = len(nodes)
    # Only joints and their ancestors belong in the skeleton, not source meshes.
    parents = {int(child): index for index, node in enumerate(skin["nodes"]) for child in node.get("children", ())}
    selected = set(int(i) for i in skin["joints"])
    for joint in tuple(selected):
        seen = set()
        while joint in parents:
            if joint in seen:
                raise ValueError("glTF skeleton contains a node cycle.")
            seen.add(joint)
            joint = parents[joint]
            selected.add(joint)
    mapping = source_mapping or {index: start + position for position, index in enumerate(sorted(selected))}
    if source_mapping is None:
        for index in sorted(selected):
            node = copy.deepcopy(skin["nodes"][index])
            node["children"] = [mapping[child] for child in node.get("children", ()) if child in mapping]
            if not node["children"]:
                node.pop("children")
            nodes.append(node)
        roots = [mapping[index] for index in selected if index not in parents or parents[index] not in selected]
        document["scenes"][0]["nodes"].extend(roots)
    result = {"name": skin.get("name", "Skeleton"), "joints": [mapping[i] for i in skin["joints"]]}
    matrices = skin.get("inverse_bind_matrices", ())
    if matrices:
        result["inverseBindMatrices"] = float_accessor(matrices, "MAT4", 0)
    skeleton = int(skin.get("skeleton", -1))
    if skeleton in mapping:
        result["skeleton"] = mapping[skeleton]
    document.setdefault("skins", []).append(result)
    return len(document["skins"]) - 1, mapping


def append_animations(document, mesh, node_mapping, float_accessor):
    animations = []
    for source in getattr(mesh, "interchange_animations", ()):
        channels = []
        for channel in source["channels"]:
            original = int(channel["target"].get("node", -1))
            targets = node_mapping.get((original, "weights"), ()) if channel["target"].get("path") == "weights" else ()
            targets = targets or node_mapping.get(original, ())
            if not targets:
                raise ValueError(f"Cannot preserve animation target node {original}; export would lose a channel.")
            for node in targets:
                copied = copy.deepcopy(channel)
                copied["target"]["node"] = node
                channels.append(copied)
        samplers = [{"input": float_accessor(s["input"], "SCALAR", 0, include_min_max=True),
                     "output": float_accessor(s["output"], s["type"], 0), "interpolation": s["interpolation"]}
                    for s in source["samplers"]]
        animations.append({"name": source["name"], "channels": channels, "samplers": samplers})
    if animations:
        document["animations"] = animations
