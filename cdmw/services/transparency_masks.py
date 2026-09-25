"""Worker-side texture preparation shared by mask painting, preview and export."""
from dataclasses import replace
import hashlib
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.textures.transparency_mask import TransparencyMask


def decode_texture(payload, *, stop_event=None):
    raise_if_cancelled(stop_event)
    if not payload.startswith(b"DDS "):
        with Image.open(BytesIO(payload)) as image:
            return image.convert("RGBA")
    from cdmw.core.texture_native import ensure_directxtex_dds_preview_png
    with TemporaryDirectory(prefix="cdmw-mask-read-") as directory:
        source = Path(directory) / "source.dds"
        source.write_bytes(payload)
        decoded = ensure_directxtex_dds_preview_png(source, max_dimension=0, slot_kind="material",
                                                   srgb="off", stop_event=stop_event)
        if decoded is None:
            raise ValueError("Cannot decode the source texture for transparency painting.")
        with Image.open(decoded) as image:
            return image.convert("RGBA")


def mask_plane(mask, size=None, *, invert=False):
    plane = Image.frombytes("L", (mask.width, mask.height), mask.pixels)
    if size is not None and plane.size != size:
        plane = plane.resize(size, Image.Resampling.BILINEAR)
    return ImageOps.invert(plane) if invert else plane


def masked_texture(image, mask, channel, *, invert=False):
    # A missing material map starts at 4x4. Do not crush a painted mask to that
    # neutral map's resolution; retain the original channels at the larger size.
    size = (max(image.width, mask.width), max(image.height, mask.height))
    image = image.resize(size, Image.Resampling.BILINEAR) if image.size != size else image.copy()
    planes = list(image.split())
    planes[channel] = mask_plane(mask, size, invert=invert)
    return Image.merge("RGBA", planes)


def encode_masked_texture(image, *, stop_event=None, on_log=None):
    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.domain.textures.output import max_mips_for_size
    with TemporaryDirectory(prefix="cdmw-mask-export-") as directory:
        source, output = Path(directory) / "mask.png", Path(directory) / "mask.dds"
        image.save(source)
        raise_if_cancelled(stop_event)
        report = encode_dds_with_directxtex(source, output, dds_format="BC7_UNORM",
            width=image.width, height=image.height, mip_count=max_mips_for_size(*image.size),
            source_color_policy="ignore_srgb_metadata", stop_event=stop_event, on_log=on_log)
        raise_if_cancelled(stop_event)
        if not report or not output.is_file() or not output.stat().st_size:
            raise ValueError("The transparency mask texture could not be encoded.")
        return output.read_bytes()


def apply_translucency_masks(text, masks, model_path, read_texture, *, stop_event=None, on_log=None):
    """Override only base alpha, including explicitly painted OPAQUE imports."""
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    from cdmw.core.material_shader_controls import _write_parameter
    masks = {name.casefold(): mask for name, mask in masks.items() if mask is not None}
    if not masks:
        return text, {}
    files, found = {}, set()
    stem = str(PurePosixPath(model_path.replace("\\", "/").replace("/modelproperty/", "/texture/")
                            .replace("/model/", "/texture/")).with_suffix(""))
    for wrapper in reversed(find_material_wrappers(text)):
        mask = masks.get(wrapper.submesh_name.casefold())
        if mask is None:
            continue
        raise_if_cancelled(stop_event)
        source = wrapper.textures.get("_baseColorTexture", "")
        payload = read_texture(source) if source else None
        if payload is None:
            raise ValueError(f"{wrapper.submesh_name}: the base colour texture is unavailable for transparency painting.")
        image = masked_texture(decode_texture(payload, stop_event=stop_event), mask, 3, invert=True)
        data = encode_masked_texture(image, stop_event=stop_event, on_log=on_log)
        path = f"{stem}_cdmw_transparency_{hashlib.sha256(data).hexdigest()[:16]}.dds"
        files[path] = data
        block = _write_parameter(text[wrapper.start:wrapper.end], "_baseColorTexture", "Texture", path, "0", static=False)
        text = text[:wrapper.start] + block + text[wrapper.end:]
        found.add(wrapper.submesh_name.casefold())
    if masks.keys() - found:
        raise ValueError("Transparency mask materials were not found: " + ", ".join(sorted(masks.keys() - found)))
    return text, files


def preview_masked_part(part, mask, *, glass=False, snapshot=None, stop_event=None, part_index=0):
    """Use lossless derived DDS resources; preview never invokes the BC7 encoder."""
    from types import SimpleNamespace
    from cdmw.services.shader_controls_preview import publish_preview_texture
    import copy
    parameter = "_baseColorTexture" if glass else "_materialTexture"
    inputs = list(getattr(part, "preview_material_texture_inputs", ()) or ())
    aliases = {parameter} if glass else {parameter, "_metallicRoughnessTexture"}
    def field(row, name):
        return row.get(name, "") if isinstance(row, dict) else getattr(row, name, "")
    current = next((row for row in inputs if field(row, "parameter_name") in aliases), None)
    attributes = (("preview_texture_dds_path", "preview_texture_path", "texture") if glass else
                  ("preview_material_texture_dds_path", "preview_material_texture_path"))
    candidates = tuple(str(path) for path in (
        *(field(current, name) for name in ("source_dds_path", "preview_texture_path", "source_texture_path")),
        *(getattr(part, name, "") for name in attributes)) if path)
    payload = None
    for path in candidates:
        raise_if_cancelled(stop_event)
        if Path(path).is_file():
            payload = Path(path).read_bytes()
            break
        if snapshot is not None and snapshot.has_entry(path):
            payload = snapshot.payload(path)
            break
    if payload is None and (glass or candidates):
        raise ValueError(f"{part.name}: the preview texture is unavailable for the painted transparency mask.")
    # glTF scalar roughness/metallic multiply the sampled channels. Without a
    # source map those channels must remain identity when adding our red mask.
    factors = getattr(part, "preview_native_material_overrides", {}) or {}
    neutral = (0, 255, 255, 255) if factors.get("gltf_metallic_roughness") else (0, 0, 0, 255)
    image = decode_texture(payload, stop_event=stop_event) if payload else Image.new("RGBA", (4, 4), neutral)
    image = masked_texture(image, mask, 3 if glass else 0, invert=glass)
    buffer = BytesIO()
    raise_if_cancelled(stop_event)
    image.save(buffer, format="DDS")
    raise_if_cancelled(stop_event)
    resource = publish_preview_texture(buffer.getvalue())
    # Carry UV transforms, scalar factors and ownership from the existing input.
    if current is not None:
        binding = copy.copy(current)
        # Frozen preview input records are common; replace retains their contract.
        fields = dict(parameter_name=parameter, source_texture_path=resource,
                      source_dds_path=resource, preview_texture_path=resource)
        if isinstance(current, dict):
            binding = {**current, **fields}
        elif hasattr(current, "__dataclass_fields__"):
            fields = {key: value for key, value in fields.items() if key in current.__dataclass_fields__}
            binding = replace(current, **fields)
        else:
            for key, value in fields.items():
                setattr(binding, key, value)
    else:
        binding = SimpleNamespace(parameter_name=parameter, slot_kind="base" if glass else "material", source_texture_path=resource,
            source_dds_path=resource, preview_texture_path=resource,
            shader_family="SkinnedMeshTranslucent" if glass else "SkinnedMeshEyeCover",
            material_name=part.material, submesh_name=part.name, binding_authority="authoritative",
            owner_slot_index=max(0, int(getattr(part, "preview_pac_material_owner_slot_index", part_index))))
    clone = copy.copy(part)
    clone.preview_material_texture_inputs = tuple(row for row in inputs if field(row, "parameter_name") not in aliases) + (binding,)
    for attribute in attributes[:2]:
        setattr(clone, attribute, resource)
    if glass:
        # Explicit painting replaces alpha even when glTF declares OPAQUE. The
        # renderer's absorption gate must therefore sample these authored pixels.
        clone.preview_alpha_mode = "BLEND"
        clone.preview_native_material_overrides = dict(getattr(part, "preview_native_material_overrides", {}) or {})
        clone.preview_native_material_overrides["alpha_mode"] = "blend"
    return clone
