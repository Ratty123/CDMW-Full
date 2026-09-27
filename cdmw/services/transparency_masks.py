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


def read_mask_image(path, size, channel="Gray", *, stop_event=None):
    """Bounded lossless import: explicit channel, exact layout, no hidden flip."""
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Mask images must be at most 64 MiB.")
    if channel not in {"Gray", "R", "G", "B", "A"}:
        raise ValueError("Select a valid mask image channel.")
    raise_if_cancelled(stop_event)
    with Image.open(path) as source:
        if (source.format != "PNG" or source.size != size or source.width * source.height > 16_777_216
                or not all(1 <= value <= 8192 for value in source.size)):
            raise ValueError(f"Import a PNG matching this mask's {size[0]} × {size[1]} pixels. Images are never stretched.")
        if source.mode not in {"L", "RGB", "RGBA"}:
            raise ValueError("Use an 8-bit grayscale, RGB or RGBA PNG for the mask.")
        if source.getexif().get(274, 1) != 1:
            raise ValueError("Normalize the image orientation before importing the mask.")
        if channel == "Gray":
            if source.mode != "L":
                raise ValueError("Select an explicit R, G, B or A channel for a colour image.")
            plane = source.copy()
        else:
            if channel == "A" and "A" not in source.getbands():
                raise ValueError("This image has no alpha channel.")
            plane = source.convert("RGBA").getchannel(channel)
        raise_if_cancelled(stop_event)
        return TransparencyMask(*size, plane.tobytes())


def write_mask_image(path, mask, *, stop_event=None):
    from cdmw.core.atomic_file import atomic_write_bytes
    if Path(path).suffix.casefold() != ".png":
        raise ValueError("Export masks as lossless PNG files.")
    buffer = BytesIO()
    mask_plane(mask).save(buffer, format="PNG")
    raise_if_cancelled(stop_event)
    atomic_write_bytes(Path(path), buffer.getvalue())
    return str(path)


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


def preview_masked_part(part, mask, *, glass=False, surface=False, snapshot=None, stop_event=None, part_index=0):
    """Use lossless derived DDS resources; preview never invokes the BC7 encoder."""
    from types import SimpleNamespace
    from cdmw.services.shader_controls_preview import publish_preview_texture
    import copy
    parameter = "_baseColorTexture" if glass else "_cdmwEyeCoverAlphaTexture" if surface else "_materialTexture"
    inputs = list(getattr(part, "preview_material_texture_inputs", ()) or ())
    aliases = {parameter, "_alphaTexture"} if surface else {parameter} if glass else {parameter, "_metallicRoughnessTexture"}
    def field(row, name):
        return row.get(name, "") if isinstance(row, dict) else getattr(row, name, "")
    current = next((row for row in inputs if field(row, "parameter_name") in aliases), None)
    attributes = (() if surface else ("preview_texture_dds_path", "preview_texture_path", "texture") if glass else
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
    if payload is None and candidates:
        raise ValueError(f"{part.name}: the preview texture is unavailable for the painted transparency mask.")
    factors = getattr(part, "preview_native_material_overrides", {}) or {}
    if glass or surface:
        # Colour-only imports keep their tint in the material factors. White
        # supplies an alpha-bearing texture without multiplying that tint twice.
        neutral = (255, 255, 255, 255)
    else:
        # glTF scalar roughness/metallic multiply the sampled channels. Without a
        # source map those channels must remain identity when adding our red mask.
        neutral = (0, 255, 255, 255) if factors.get("gltf_metallic_roughness") else (0, 0, 0, 255)
    image = decode_texture(payload, stop_event=stop_event) if payload else Image.new("RGBA", (4, 4), neutral)
    image = masked_texture(image, mask, 3 if glass else 0, invert=glass or surface)
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
    clone.preview_native_material_overrides = dict(factors)
    # The native graph must preserve this derived channel at its final handoff.
    authored = dict(factors.get("painted_texture_channels", {}))
    authored["opacity" if glass else "eye_surface" if surface else "material"] = resource
    clone.preview_native_material_overrides["painted_texture_channels"] = authored
    clone.preview_material_texture_inputs = tuple(row for row in inputs if field(row, "parameter_name") not in aliases) + (binding,)
    for attribute in attributes[:2]:
        setattr(clone, attribute, resource)
    if glass:
        # Explicit painting replaces alpha even when glTF declares OPAQUE. The
        # renderer's absorption gate must therefore sample these authored pixels.
        clone.preview_alpha_mode = "BLEND"
        clone.preview_native_material_overrides["alpha_mode"] = "blend"
        # Export replaces the complete base alpha, including any source factor.
        clone.preview_native_material_overrides["opacity"] = 1.
    return clone


def cutout_mips(mask, *, stop_event=None):
    """Wing recipe: R=1 at every UV; B=fade, progress=.5, inversion=0.

    cut = saturate(2*saturate(2*B-.5)-1); discard when cut>.001,
    hence B>.50025. Lower mips preserve the nearest representable removed
    pixel count at this fixed threshold. No alpha-channel coverage heuristic.
    """
    import numpy as np
    plane = mask_plane(mask)
    removed = sum(count for value, count in enumerate(plane.histogram()) if value / 255 > .50025)
    fraction = removed / (mask.width * mask.height)
    first = True
    while True:
        raise_if_cancelled(stop_event)
        blue = plane
        if not first:
            values = np.asarray(plane).ravel()
            count = round(fraction * len(values))
            pixels = np.zeros(len(values), dtype=np.uint8)
            if count:
                pixels[np.argsort(values, kind="stable")[-count:]] = 255
            blue = Image.frombytes("L", plane.size, pixels.tobytes())
        yield Image.merge("RGBA", (Image.new("L", plane.size, 255), Image.new("L", plane.size, 0),
                                    blue, Image.new("L", plane.size, 255)))
        if plane.size == (1, 1):
            break
        plane = plane.resize((max(1, plane.width // 2), max(1, plane.height // 2)), Image.Resampling.BOX)
        first = False


def encode_cutout_texture(mask, *, compressed=True, stop_event=None, on_log=None):
    """Encode each owned mip once, then assemble that exact DDS mip chain."""
    import struct
    from cdmw.core.texture_native import encode_dds_with_directxtex
    header, payloads = None, []
    with TemporaryDirectory(prefix="cdmw-cutout-") as directory:
        root = Path(directory)
        for image in cutout_mips(mask, stop_event=stop_event):
            if compressed:
                source, output = root / "mip.png", root / "mip.dds"
                image.save(source)
                report = encode_dds_with_directxtex(source, output, dds_format="BC7_UNORM",
                    width=image.width, height=image.height, mip_count=1, source_color_policy="ignore_srgb_metadata",
                    stop_event=stop_event, on_log=on_log)
                raise_if_cancelled(stop_event)
                if not report or not output.is_file():
                    raise ValueError("The cutout mask texture could not be encoded.")
                data, offset = output.read_bytes(), 148
                if data[84:88] != b"DX10" or struct.unpack_from("<I", data, 128)[0] != 98:
                    raise ValueError("The cutout encoder did not return BC7_UNORM.")
                expected = ((image.width + 3) // 4) * ((image.height + 3) // 4) * 16
            else:
                buffer = BytesIO()
                image.save(buffer, format="DDS")
                data, offset = buffer.getvalue(), 128
                expected = image.width * image.height * 4
            if len(data) != offset + expected:
                raise ValueError("Invalid cutout mip payload size.")
            if header is None:
                header = bytearray(data[:offset])
            payloads.append(data[offset:])
        struct.pack_into("<I", header, 28, len(payloads))
        if len(payloads) > 1:
            struct.pack_into("<I", header, 8, struct.unpack_from("<I", header, 8)[0] | 0x20000)
            struct.pack_into("<I", header, 108, struct.unpack_from("<I", header, 108)[0] | 0x400008)
        raise_if_cancelled(stop_event)
        return bytes(header) + b"".join(payloads)


def prepare_cutout_textures(wrappers, settings, model_path, *, stop_event=None, on_log=None):
    paths, files = {}, {}
    stem = str(PurePosixPath(model_path.replace("\\", "/").replace("/modelproperty/", "/texture/", 1)
                            .replace("/model/", "/texture/", 1)).with_suffix(""))
    for wrapper in wrappers:
        mask = settings[wrapper.submesh_name.casefold()].cutout_mask
        if mask is None:
            continue
        data = encode_cutout_texture(mask, stop_event=stop_event, on_log=on_log)
        identity = hashlib.sha256(wrapper.submesh_name.encode() + b"\0wing-cutout-v1\0" + data).hexdigest()[:24]
        path = f"{stem}_cdmw_cutout_{identity}.dds"
        paths[wrapper.start] = {"_wingFlowTex1": path}
        files[path] = data
    return paths, files
