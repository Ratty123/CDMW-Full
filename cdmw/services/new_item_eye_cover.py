"""Owned texture channels for the experimental EyeCover equipment export."""
import hashlib
import time
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.mesh.shader_controls import EYE_COVER, EYE_COVER_TEXTURE_FIELDS


def prepare_eye_cover_textures(text, choices, model_path, read_texture, *, stop_event=None, on_log=None):
    """Return private bindings by material offset plus payloads, preserving source maps."""
    settings = {name.casefold(): controls for name, controls in choices if controls.shader == EYE_COVER.shader}
    paths, files = {}, {}
    stem = str(PurePosixPath(model_path.replace("\\", "/").replace("/modelproperty/", "/texture/", 1)
                            .replace("/model/", "/texture/", 1)).with_suffix(""))
    for wrapper in find_material_wrappers(text):
        key = wrapper.submesh_name.casefold()
        if key not in settings:
            continue
        raise_if_cancelled(stop_event)
        controls = settings[key]
        controls.validate()
        values = controls.effective_values()
        paths[wrapper.start] = {}
        for parameter in ("_alphaTexture", "_materialTexture"):
            mask = (controls.colour_mask_for_output() if parameter == "_materialTexture"
                    else controls.surface_response_mask)
            channels = {channel: values[name][0] for name, (texture, channel) in EYE_COVER_TEXTURE_FIELDS.items()
                        if texture == parameter and name in values}
            source = wrapper.textures.get(parameter, "")
            if not channels and source and mask is None:
                continue
            payload = read_texture(source) if source else None
            if source and payload is None:
                raise ValueError(f"{wrapper.submesh_name}: missing EyeCover source texture {source}.")
            # Explicit neutral defaults avoid the EyeCover material's stock face maps.
            default = (255, 255, 255, 255) if parameter == "_alphaTexture" else (0, 0, 0, 255)
            label = "surface alpha" if parameter == "_alphaTexture" else "material"
            def report(message):
                if on_log:
                    on_log(f"{wrapper.submesh_name}: EyeCover {label}: {message}")
            report("Preparing texture...")
            data = _encode_channels(payload, channels, default, wrapper.submesh_name,
                                    stop_event=stop_event, on_log=report, mask=mask,
                                    invert_mask=parameter == "_alphaTexture")
            identity = hashlib.sha256((wrapper.submesh_name.casefold() + "\0" + parameter + "\0" + source.casefold()).encode() + data).hexdigest()[:24]
            path = f"{stem}_cdmw_eyecover_{identity}.dds"
            files[path] = data
            paths[wrapper.start][parameter] = path
    return paths, files


def _encode_channels(payload, channels, default, part_name, *, stop_event=None, on_log=None, mask=None, invert_mask=False):
    from PIL import Image
    from cdmw.core.texture_native import ensure_directxtex_dds_preview_png, encode_dds_with_directxtex
    from cdmw.domain.textures.output import max_mips_for_size

    raise_if_cancelled(stop_event)
    with TemporaryDirectory(prefix="cdmw_eyecover_") as directory:
        root = Path(directory)
        if payload is not None:
            source = root / "source.dds"
            source.write_bytes(payload)
            decoded = ensure_directxtex_dds_preview_png(source, max_dimension=0, slot_kind="material",
                                                       srgb="off", stop_event=stop_event, on_log=on_log)
            if decoded is None:
                raise ValueError(f"{part_name}: cannot decode the EyeCover source texture.")
            with Image.open(decoded) as image:
                rgba = image.convert("RGBA")
        else:
            rgba = Image.new("RGBA", (4, 4), default)
        planes = list(rgba.split())
        for channel, value in channels.items():
            planes[channel].paste(round(value * 255), (0, 0, rgba.width, rgba.height))
        source = root / "channels.png"
        rgba = Image.merge("RGBA", planes)
        if mask is not None:
            from cdmw.services.transparency_masks import masked_texture
            rgba = masked_texture(rgba, mask, 0, invert=invert_mask)
        rgba.save(source)
        output = root / "channels.dds"
        raise_if_cancelled(stop_event)
        mip_count = max_mips_for_size(*rgba.size)
        if on_log:
            on_log(f"Encoding {rgba.width} x {rgba.height} BC7 texture ({mip_count} mip levels)...")
        started = time.monotonic()
        report = encode_dds_with_directxtex(source, output, dds_format="BC7_UNORM",
            width=rgba.width, height=rgba.height, mip_count=mip_count,
            source_color_policy="ignore_srgb_metadata", stop_event=stop_event, on_log=on_log)
        raise_if_cancelled(stop_event)
        if not report or not output.is_file() or not output.stat().st_size:
            raise ValueError(f"{part_name}: cannot encode the EyeCover texture.")
        if on_log:
            on_log(f"Encoded texture in {time.monotonic() - started:.1f}s.")
        return output.read_bytes()
