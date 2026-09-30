"""Authored glTF channels retained by the editable interchange reader."""

from __future__ import annotations

import copy

from .scene_gltf_geometry import _GLTF_TYPE_COUNTS, _read_gltf_accessor


def authored_material(payload, material_index):
    from .scene_gltf_import import _gltf_texture_image_path
    materials = payload.document.get("materials", [])
    if not 0 <= material_index < len(materials):
        return {}
    material = copy.deepcopy(materials[material_index])
    textures = {}
    def visit(value, location=()):
        if not isinstance(value, dict):
            return
        for key, child in list(value.items()):
            path = location + (key,)
            if key.endswith("Texture") and isinstance(child, dict) and "index" in child:
                resolved = _gltf_texture_image_path(payload, payload.document.get("textures", []), payload.document.get("images", []), child)
                info = copy.deepcopy(child)
                info.pop("index", None)
                info.update(path=str(resolved or ""), location=list(path))
                texture = payload.document.get("textures", [])[int(child["index"])]
                sampler_index = int(texture.get("sampler", -1))
                if sampler_index >= 0:
                    info["sampler"] = copy.deepcopy(payload.document["samplers"][sampler_index])
                textures[key if key not in textures else ".".join(path)] = info
                value.pop(key)
            else:
                visit(child, path)
    visit(material)
    material["textures"] = textures
    return material


def authored_skin(payload, skin_index):
    skins = payload.document.get("skins", [])
    if not 0 <= skin_index < len(skins):
        raise ValueError("glTF mesh references an invalid skin.")
    skin = skins[skin_index]
    nodes = payload.document.get("nodes", [])
    joints = [int(index) for index in skin.get("joints", ())]
    if not joints or len(set(joints)) != len(joints) or any(not 0 <= i < len(nodes) for i in joints):
        raise ValueError("glTF skin has invalid or duplicate joints.")
    matrices = _read_gltf_accessor(payload, int(skin.get("inverseBindMatrices", -1)), expected_components=16)
    if matrices and len(matrices) != len(joints):
        raise ValueError("glTF inverse-bind matrix count differs from joint count.")
    clean_nodes = [{key: copy.deepcopy(value) for key, value in node.items()
                    if key in {"name", "matrix", "translation", "rotation", "scale", "children", "extras"}}
                   for node in nodes]
    return {"name": str(skin.get("name", "")), "joints": joints, "skeleton": int(skin.get("skeleton", -1)),
            "nodes": clean_nodes, "inverse_bind_matrices": [list(row) for row in matrices]}


def authored_animations(payload):
    """Retain existing clips for export without supplying animation editing."""
    clips = []
    for source in payload.document.get("animations", ()):
        clip = {"name": str(source.get("name", "")), "channels": copy.deepcopy(source.get("channels", [])), "samplers": []}
        for sampler in source.get("samplers", []):
            accessor = payload.document["accessors"][int(sampler["output"])]
            type_name = str(accessor["type"])
            clip["samplers"].append({"input": _read_gltf_accessor(payload, int(sampler["input"]), expected_components=1),
                                     "output": _read_gltf_accessor(payload, int(sampler["output"]), expected_components=_GLTF_TYPE_COUNTS[type_name]),
                                     "type": type_name, "interpolation": str(sampler.get("interpolation", "LINEAR"))})
        clips.append(clip)
    return clips
