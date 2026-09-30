"""Authored material handoff and portable texture companions for mesh exchange."""

from __future__ import annotations

import copy
import hashlib
import io
import math
import json
from pathlib import Path

from cdmw.core.atomic_file import atomic_write_bytes


_SLOT_KEYS = {
    "base": "baseColorTexture", "diffuse": "baseColorTexture", "basecolor": "baseColorTexture",
    "normal": "normalTexture", "material": "metallicRoughnessTexture",
    "metallicroughness": "metallicRoughnessTexture", "orm": "metallicRoughnessTexture",
    "occlusion": "occlusionTexture", "ao": "occlusionTexture",
    "emission": "emissiveTexture", "emissive": "emissiveTexture",
    "roughness": "roughnessTexture", "metallic": "metallicTexture",
    "specular": "specularTexture", "opacity": "opacityTexture", "alpha": "opacityTexture",
}


def _number(value, default):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def interchange_material(submesh) -> dict:
    """Use the authored source definition when present, otherwise resolved inputs."""
    source = getattr(submesh, "interchange_material", None)
    if source:
        return copy.deepcopy(source)
    parameters = {
        str(getattr(row, "parameter_name", "")).lstrip("_").casefold(): row
        for row in getattr(submesh, "preview_material_parameters", ()) or ()
    }

    def scalar(names, default):
        for name in names:
            row = parameters.get(name.casefold())
            if row is not None:
                return _number(getattr(row, "numeric_value", None) if getattr(row, "numeric_value", None) is not None
                               else getattr(row, "value", None), default)
        return default

    def color(names, default):
        for name in names:
            row = parameters.get(name.casefold())
            values = getattr(row, "color_value", ()) if row is not None else ()
            if len(values or ()) >= 3:
                return [_number(v, 1.0) for v in values[:3]]
        return list(default)

    source_color = getattr(submesh, "preview_color", ()) or ()
    rgba = color(("baseColorFactor", "diffuseFactor"), source_color[:3] if len(source_color) >= 3 else (0.8, 0.8, 0.8))
    rgba.append(scalar(("gltfBaseColorAlphaFactor", "gltfDiffuseAlphaFactor", "opacity", "alpha"), 1.0))
    result = {
        "pbrMetallicRoughness": {"baseColorFactor": rgba,
                                 "metallicFactor": scalar(("metallicFactor", "metallic", "metalness"), 0.0),
                                 "roughnessFactor": scalar(("roughnessFactor", "roughness"), 0.5)},
        "emissiveFactor": color(("emissiveColor", "emissionColor", "emissiveFactor"), (0.0, 0.0, 0.0)),
        "alphaMode": str(getattr(submesh, "preview_alpha_mode", "OPAQUE") or "OPAQUE"),
        "doubleSided": bool(getattr(submesh, "preview_double_sided", False)),
        "textures": {},
    }
    strength = scalar(("emissiveStrength", "emissionStrength", "gltfEmissiveStrength"), 1.0)
    if strength != 1.0:
        result["extensions"] = {"KHR_materials_emissive_strength": {"emissiveStrength": strength}}
    slots = result["textures"]
    for row in getattr(submesh, "texture_slots", ()) or ():
        if isinstance(row, (tuple, list)) and len(row) >= 2:
            kind, path = str(row[0]), str(row[1])
            key = _SLOT_KEYS.get(kind.replace("_", "").casefold())
            if key and path:
                slots[key] = {"path": path, "texCoord": 0}
    for row in getattr(submesh, "preview_material_texture_inputs", ()) or ():
        kind = str(getattr(row, "semantic_subtype", "") or getattr(row, "semantic_type", "") or "")
        parameter = str(getattr(row, "parameter_name", ""))
        key = _SLOT_KEYS.get(kind.replace("_", "").casefold())
        if key is None:
            token = parameter.casefold()
            key = next((value for kind, value in _SLOT_KEYS.items() if kind in token), None)
        path = str(getattr(row, "source_path", "") or getattr(row, "texture_path", "") or "")
        if key and path:
            slots[key] = {"path": path, "texCoord": int(getattr(row, "texcoord", 0) or 0)}
    for key, attr in (("baseColorTexture", "preview_texture_path"), ("normalTexture", "preview_normal_texture_path"),
                      ("metallicRoughnessTexture", "preview_material_texture_path")):
        value = str(getattr(submesh, attr, "") or "")
        if value and key not in slots:
            slots[key] = {"path": value, "texCoord": 0}
    emission_path = str(getattr(submesh, "preview_emissive_texture_path", "") or "")
    if emission_path and "emissiveTexture" not in slots:
        slots["emissiveTexture"] = {"path": emission_path, "texCoord": 0}
    if "baseColorTexture" not in slots and getattr(submesh, "texture", ""):
        slots["baseColorTexture"] = {"path": str(submesh.texture), "texCoord": 0}
    if "normalTexture" in slots and "scale" not in slots["normalTexture"]:
        strength = float(getattr(submesh, "preview_normal_texture_strength", 0.0) or 0.0)
        slots["normalTexture"]["scale"] = scalar(("normalScale", "normalStrength", "gltfNormalScale"), strength if strength else 1.0)
    return result


def prepare_interchange_material(submesh, output_dir: Path, source_dir: Path | None = None) -> tuple[dict, list[str], list[str]]:
    """Copy complete inputs; DDS is retained and gets a PNG interchange copy."""
    material = interchange_material(submesh)
    material["_cdmw_texture_sources"] = {}
    companions, missing = [], []
    for key, info in material.get("textures", {}).items():
        reference = str(info.get("path", "") or "")
        if not reference:
            continue
        path = Path(reference)
        candidates = [path] if path.is_absolute() else [output_dir / path] + ([source_dir / path] if source_dir else [])
        source = next((candidate for candidate in candidates if candidate.is_file()), None)
        if source is None:
            missing.append(f"{submesh.material or submesh.name}: {key}: {reference}")
            info["missing"] = True
            continue
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()[:12]
        safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in source.stem)[:70] or "texture"
        target = output_dir / "textures" / f"{safe_stem}-{digest}{source.suffix.lower()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() != source.resolve():
            atomic_write_bytes(target, raw)
        companions.append(str(target))
        info["original_reference"] = reference
        info["original_path"] = target.relative_to(output_dir).as_posix()
        material["_cdmw_texture_sources"][reference] = info["original_path"]
        if source.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as image:
                converted = io.BytesIO()
                image.convert("RGBA").save(converted, format="PNG")
            target = target.with_suffix(".png")
            atomic_write_bytes(target, converted.getvalue())
            companions.append(str(target))
        info["path"] = target.relative_to(output_dir).as_posix()
    packed = material.get("textures", {}).get("metallicRoughnessTexture", {})
    if packed.get("path") and not packed.get("missing"):
        from PIL import Image
        with Image.open(output_dir / packed["path"]) as image:
            rgb = image.convert("RGB")
            for key, channel in (("roughnessTexture", "G"), ("metallicTexture", "B")):
                if key in material["textures"]:
                    continue
                target = (output_dir / packed["path"]).with_name(Path(packed["path"]).stem + f"-{channel}.png")
                encoded = io.BytesIO()
                rgb.getchannel(channel).save(encoded, format="PNG")
                atomic_write_bytes(target, encoded.getvalue())
                companions.append(str(target))
                material["textures"][key] = {"path": target.relative_to(output_dir).as_posix(), "texCoord": int(packed.get("texCoord", 0)), "derived": True}
    companions.extend(_pack_standard_textures(material, output_dir))
    return material, companions, missing


def portable_texture_sources(material):
    return dict(material.get("_cdmw_texture_sources", {})) | {info["original_reference"]: info["original_path"]
            for info in material.get("textures", {}).values()
            if info.get("original_reference") and info.get("original_path")}


def resolve_companion_material_paths(payload, folder):
    """Resolve protected source maps from the portable package after a move."""
    sources = payload.get("interchange_texture_sources", {})
    entries = list(payload.get("submeshes", []))
    entries.extend(part for lod in payload.get("lods", []) for part in lod.get("submeshes", []))
    for entry in entries:
        for info in entry.get("interchange_material", {}).get("textures", {}).values():
            reference = str(info.get("path", ""))
            portable = sources.get(reference)
            if portable:
                path = (folder / portable).resolve()
                if not path.is_relative_to(folder.resolve()):
                    raise ValueError("Companion texture path escapes the exported package.")
                info["path"] = str(path)


def restore_companion_material(incoming, protected):
    """Recover omitted channels while keeping imported material edits authoritative."""
    result = copy.deepcopy(incoming)
    for key, value in protected.items():
        if key not in result:
            result[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(result[key], dict):
            if key == "textures":
                # A present binding may be an intentional texture/UV edit.
                for slot, binding in value.items():
                    result[key].setdefault(slot, copy.deepcopy(binding))
            else:
                result[key] = restore_companion_material(result[key], value)
    return result


def companion_material_slots(material):
    """Use recovered authored maps in the existing preview/import material path."""
    from cdmw.models import PreviewMaterialParameterInput
    from .scene_material_audit import SceneMaterialTextureSlot
    kinds = {"baseColorTexture": ("base", "base"), "normalTexture": ("normal", "normal"),
             "metallicRoughnessTexture": ("material", "metallic_roughness"),
             "emissiveTexture": ("emissive", "emissive"), "occlusionTexture": ("occlusion", "ao"),
             "roughnessTexture": ("roughness", "roughness"), "metallicTexture": ("metalness", "metallic"),
             "specularTexture": ("specular", "specular"), "opacityTexture": ("opacity", "opacity")}
    slots = []
    for key, info in material.get("textures", {}).items():
        if key not in kinds or not info.get("path") or info.get("missing") or not Path(info["path"]).is_file():
            continue
        kind, subtype = kinds[key]
        uv = info.get("extensions", {}).get("KHR_texture_transform", {})
        transform = (*uv.get("offset", (0, 0)), *uv.get("scale", (1, 1)), uv.get("rotation", 0)) if uv else ()
        parameters = ()
        if key == "normalTexture":
            scale = float(info.get("scale", 1))
            parameters = (PreviewMaterialParameterInput(parameter_kind="float", parameter_name="_gltfTextureScale",
                                                        value=str(scale), numeric_value=scale),)
        slots.append(SceneMaterialTextureSlot(slot_kind=kind, path=str(info["path"]), parameter_name="_" + key,
                     semantic_type=kind, semantic_subtype=subtype, texcoord=int(uv.get("texCoord", info.get("texCoord", 0))),
                     transform=transform, packed_channels=("occlusion", "roughness", "metallic") if kind == "material" else (),
                     srgb_mode="srgb" if kind in {"base", "emissive"} else "linear", parameters=parameters,
                     source="cdmw_companion"))
    return slots


def restore_companion_texture_inputs(submesh, incoming_material):
    from .scene_material_audit import _apply_scene_material_slots_to_submesh
    existing = incoming_material.get("textures", {})
    missing = {key: info for key, info in submesh.interchange_material.get("textures", {}).items() if key not in existing}
    slots = companion_material_slots({"textures": missing})
    _apply_scene_material_slots_to_submesh(submesh, slots, confidence="cdmw_companion")


def _pack_standard_textures(material: dict, output_dir: Path) -> list[str]:
    """Represent separate scalar maps in glTF's packed channels without loss."""
    from PIL import Image
    textures = material.get("textures", {})
    files = []
    def resolved(key):
        info = textures.get(key, {})
        return info if info.get("path") and not info.get("missing") else None
    def compatible(infos):
        bindings = {(int(i.get("texCoord", 0)), json.dumps(i.get("extensions", {}), sort_keys=True)) for i in infos}
        if len(bindings) > 1:
            raise ValueError("Separate material maps use different UV bindings; they cannot share a packed texture.")
    def image(info):
        with Image.open(output_dir / info["path"]) as source:
            return source.convert("RGBA")
    def publish(name, packed, infos):
        encoded = io.BytesIO()
        packed.save(encoded, format="PNG")
        raw = encoded.getvalue()
        path = output_dir / "textures" / f"{name}-{hashlib.sha256(raw).hexdigest()[:12]}.png"
        atomic_write_bytes(path, raw)
        files.append(str(path))
        info = {k: copy.deepcopy(v) for k, v in infos[0].items() if k in {"texCoord", "extensions", "sampler"}}
        info["path"] = path.relative_to(output_dir).as_posix()
        return info
    rough, metal = resolved("roughnessTexture"), resolved("metallicTexture")
    if not resolved("metallicRoughnessTexture") and (rough or metal):
        infos = [i for i in (rough, metal) if i]
        compatible(infos)
        images = [image(i) for i in infos]
        size = (max(i.width for i in images), max(i.height for i in images))
        white = Image.new("L", size, 255)
        def scalar(info):
            return image(info).getchannel("R").resize(size) if info else white
        textures["metallicRoughnessTexture"] = publish("metallic-roughness", Image.merge("RGB", (white, scalar(rough), scalar(metal))), infos)
    opacity, base = resolved("opacityTexture"), resolved("baseColorTexture")
    if opacity:
        infos = [i for i in (base, opacity) if i]
        compatible(infos)
        alpha = image(opacity).getchannel("R")
        rgba = image(base) if base else Image.new("RGBA", alpha.size, (255, 255, 255, 255))
        from PIL import ImageChops
        rgba.putalpha(ImageChops.multiply(rgba.getchannel("A"), alpha.resize(rgba.size)))
        textures["baseColorTexture"] = publish("base-opacity", rgba, infos)
        # The original opacity input remains on disk and in the source sidecar;
        # the packed base alpha now carries its contribution exactly once.
        textures.pop("opacityTexture", None)
    return files


def material_fbx_payload(material: dict) -> dict:
    """Blender's FBX reader recognises these legacy material properties."""
    pbr = material.get("pbrMetallicRoughness", {})
    color = list(pbr.get("baseColorFactor", (0.8, 0.8, 0.8, 1.0)))
    roughness = _number(pbr.get("roughnessFactor"), 0.5)
    emission = list(material.get("emissiveFactor", (0.0, 0.0, 0.0)))
    strength = material.get("extensions", {}).get("KHR_materials_emissive_strength", {}).get("emissiveStrength", 1.0)
    return {"diffuse_color": color[:3], "opacity": color[3] if len(color) > 3 else 1.0,
            "metallic": _number(pbr.get("metallicFactor"), 0.0), "roughness": roughness,
            "emissive_color": emission, "emissive_factor": _number(strength, 1.0),
            "normal_strength": _number(material.get("textures", {}).get("normalTexture", {}).get("scale"), 1.0),
            "textures": [dict(info, semantic=key) for key, info in material.get("textures", {}).items()
                         if info.get("path") and not info.get("missing")]}


def prepare_legacy_material(material: dict, output_dir: Path) -> tuple[dict, list[str]]:
    """Bake factors that Blender's OBJ/FBX readers ignore on linked textures.

    Original images and the authored definition remain in the companion.
    Colour factors multiply linear colour, while scalar/alpha maps are linear.
    """
    from PIL import Image
    material = copy.deepcopy(material)
    pbr = material.setdefault("pbrMetallicRoughness", {})
    textures = material.setdefault("textures", {})
    files = []
    rgba = list(pbr.get("baseColorFactor", (1.0, 1.0, 1.0, 1.0)))
    emission = list(material.get("emissiveFactor", (0, 0, 0)))
    strength = material.get("extensions", {}).get("KHR_materials_emissive_strength", {}).get("emissiveStrength", 1.0)
    factors = {"baseColorTexture": rgba, "emissiveTexture": [v * strength for v in emission] + [1.0],
               "roughnessTexture": [pbr.get("roughnessFactor", 1.0)] * 4,
               "metallicTexture": [pbr.get("metallicFactor", 1.0)] * 4}
    for key, values in factors.items():
        info = textures.get(key, {})
        if not info.get("path") or info.get("missing"):
            continue
        source = output_dir / info["path"]
        with Image.open(source) as image:
            image = image.convert("RGBA")
        if key == "baseColorTexture" and material.get("alphaMode", "OPAQUE") == "OPAQUE":
            image.putalpha(255)
            values = values[:3] + [1.0]
        if key == "emissiveTexture":
            # Keep intensity above one as a material property, not clipped pixels.
            values = emission + [1.0]
        channels = dict(zip("RGBA", image.split()))
        for channel, factor in zip("RGBA", values):
            if factor == 1.0:
                continue
            color = key in {"baseColorTexture", "emissiveTexture"} and channel != "A"
            def scale(value):
                value /= 255.0
                if color:
                    value = value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                value = max(0.0, min(1.0, value * float(factor)))
                if color:
                    value = value * 12.92 if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055
                return round(value * 255)
            channels[channel] = channels[channel].point([scale(i) for i in range(256)])
        image = Image.merge("RGBA", tuple(channels[channel] for channel in "RGBA"))
        token = hashlib.sha256(json.dumps(values).encode()).hexdigest()[:10]
        target = source.with_name(f"{source.stem}-legacy-{token}.png")
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        atomic_write_bytes(target, encoded.getvalue())
        files.append(str(target))
        info["path"] = target.relative_to(output_dir).as_posix()
        if key == "baseColorTexture":
            pbr["baseColorFactor"] = [1.0] * 4
            if material.get("alphaMode", "OPAQUE") != "OPAQUE":
                alpha_path = target.with_name(target.stem + "-alpha.png")
                alpha = image.getchannel("A")
                alpha_rgba = Image.merge("RGBA", (alpha, alpha, alpha, alpha))
                encoded = io.BytesIO()
                alpha_rgba.save(encoded, format="PNG")
                atomic_write_bytes(alpha_path, encoded.getvalue())
                files.append(str(alpha_path))
                textures["opacityTexture"] = {"path": alpha_path.relative_to(output_dir).as_posix(), "texCoord": info.get("texCoord", 0)}
        elif key == "emissiveTexture":
            material["emissiveFactor"] = [1.0] * 3
        else:
            pbr["roughnessFactor" if key == "roughnessTexture" else "metallicFactor"] = 1.0
    return material, files


def interchange_report(mesh, format_name: str, *, missing=(), resolved_skeleton=False) -> dict:
    """Describe actual channels and format restrictions, including absent assets."""
    omitted = []
    if format_name == "obj":
        for title, present in (("skeleton and skin weights", any(s.bone_indices for s in mesh.submeshes)),
                               ("morph targets", any(s.morph_targets for s in mesh.submeshes)),
                               ("additional UV sets", any(len(s.uv_sets) > 1 for s in mesh.submeshes)),
                               ("vertex colors", any(s.vertex_colors for s in mesh.submeshes))):
            if present:
                omitted.append(title)
    if format_name != "glb":
        if getattr(mesh, "interchange_nodes", None):
            omitted.append("mesh scene hierarchy (retained in the CDMW companion)")
        if getattr(mesh, "interchange_animations", None):
            omitted.append("animation clips (retained in the CDMW companion)")
        omitted.append("exact PBR material extensions, samplers and texture transforms (retained in the CDMW companion)")
        if any("occlusionTexture" in interchange_material(s).get("textures", {}) for s in mesh.submeshes):
            omitted.append("occlusion texture shader binding (image retained)")
        if any(int(info.get("texCoord", 0)) != 0 for s in mesh.submeshes
               for info in interchange_material(s).get("textures", {}).values()):
            omitted.append("texture shader selection of extra UV sets (retained in the CDMW companion)")
    resolved = resolved_skeleton or bool(getattr(mesh, "interchange_skeleton", None)) or any(s.interchange_skin for s in mesh.submeshes)
    if format_name in {"glb", "fbx"} and any(s.bone_indices for s in mesh.submeshes) and not resolved:
        omitted.append("unresolved skeleton and skin binding (source weights retained in the CDMW companion)")
    return {"format": format_name, "missing_textures": list(missing), "omitted_from_interchange": omitted,
            "game_metadata": "retained in CDMW sidecar; keep it beside the edited file",
            "animation_data": "embedded" if format_name == "glb" else "retained in CDMW companion",
            "animation_editing": "unsupported"}


def interchange_metadata_payload(submesh):
    return {"channel_presence": {"uv0": bool(submesh.uvs), "normals": bool(submesh.normals), "tangents": bool(submesh.tangents)},
            "interchange_material": interchange_material(submesh),
            "interchange_vertices": [list(v) for v in submesh.vertices],
            "interchange_faces": [list(f) for f in submesh.faces],
            "interchange_uv_sets": {str(k): [list(row) for row in rows] for k, rows in submesh.uv_sets.items()},
            "interchange_vertex_colors": [list(row) for row in submesh.vertex_colors],
            "interchange_morph_targets": {name: [list(row) for row in rows] for name, rows in submesh.morph_targets.items()},
            "interchange_morph_normals": {name: [list(row) for row in rows] for name, rows in submesh.morph_normals.items()},
            "interchange_morph_tangents": {name: [list(row) for row in rows] for name, rows in submesh.morph_tangents.items()},
            "interchange_morph_weights": dict(submesh.morph_weights),
            "interchange_bone_indices": [list(row) for row in submesh.bone_indices],
            "interchange_bone_weights": [list(row) for row in submesh.bone_weights],
            "interchange_node_index": int(getattr(submesh, "interchange_node_index", -1)),
            "interchange_transform": list(getattr(submesh, "interchange_transform", ())),
            "interchange_skin": copy.deepcopy(submesh.interchange_skin)}
