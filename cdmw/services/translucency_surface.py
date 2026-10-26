"""Export selected surface overrides to private DDS maps, leaving sources intact."""

import hashlib
import struct
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from cdmw.core.material_shader_controls import edit_material_variants
from cdmw.core.pac_xml_standard_material import PacXmlMaterialError, find_material_wrappers, rewrite_translucency
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.mesh.translucency import translucency_surface_values


def apply_translucency_surface(text, settings, surfaces, model_path, read_texture, *, stop_event=None):
    """Return rewritten XML and generated maps. Only explicit channels are replaced."""
    surfaces = {name.casefold(): translucency_surface_values(value) for name, value in surfaces.items()}
    surfaces = {name: value for name, value in surfaces.items() if value is not None}
    if not surfaces:
        return rewrite_translucency(text, settings), {}
    settings = {name.casefold(): values for name, values in settings.items()}
    if surfaces.keys() - settings.keys():
        raise ValueError("Surface overrides require translucency on the same part.")
    files, found = {}, set()
    stem = str(PurePosixPath(model_path.replace("\\", "/").replace("/model/", "/texture/", 1)
                            .replace("/modelproperty/", "/texture/", 1)).with_suffix(""))

    def edit(fragment):
        # Variants repeat part names with their own maps; each derives its own override.
        rows = find_material_wrappers(fragment)
        paths = {}
        for row in rows:
            name = row.submesh_name.casefold()
            if name not in surfaces:
                continue
            if name in paths:
                raise ValueError(f"Ambiguous translucent surface binding: {row.submesh_name}")
            raise_if_cancelled(stop_event)
            source = row.textures.get("_materialTexture", "")
            payload = read_texture(source) if source else None
            if source and payload is None:
                raise ValueError(f"{row.submesh_name}: cannot edit the surface; missing material texture {source}.")
            identity = hashlib.sha256(name.encode() + repr(surfaces[name]).encode() + (payload or b"")).hexdigest()[:16]
            path = f"{stem}_cdmw_surface_{identity}.dds"
            if path not in files:
                files[path] = _encode_surface(payload, surfaces[name], part_name=row.submesh_name, stop_event=stop_event)
            paths[name] = path
        present = {row.submesh_name.casefold() for row in rows}
        found.update(present)
        return rewrite_translucency(fragment, {name: values for name, values in settings.items() if name in present},
                                    material_paths=paths), None

    text, _ = edit_material_variants(text, edit)
    if surfaces.keys() - found:
        raise ValueError("Translucent surface material bindings were not found: " + ", ".join(sorted(surfaces.keys() - found)))
    if settings.keys() - found:
        raise PacXmlMaterialError("Translucency material bindings were not found: " + ", ".join(sorted(settings.keys() - found)))
    return text, files


def _encode_surface(payload, values, *, part_name, stop_event, regions=((0.0, 0.0, 1.0, 1.0),)):
    from PIL import Image
    from cdmw.core.texture_native import ensure_directxtex_dds_preview_png, encode_dds_with_directxtex
    from cdmw.domain.textures.output import max_mips_for_size

    with TemporaryDirectory(prefix="cdmw_translucent_surface_") as directory:
        root = Path(directory)
        if payload is not None:
            source = root / "source.dds"
            source.write_bytes(payload)
            decoded = ensure_directxtex_dds_preview_png(source, max_dimension=0, slot_kind="material",
                                                       srgb="off", stop_event=stop_event)
            if decoded is None:
                raise ValueError(f"{part_name}: cannot decode the material texture for surface editing.")
            with Image.open(decoded) as image:
                rgba = image.convert("RGBA")
        else:
            # A missing _materialTexture reads as zero roughness and metallic in game.
            # R follows shipped `_sp` maps; the translucent shader samples only G and B.
            rgba = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
        channels = list(rgba.split())
        for index, value in zip((1, 2), values):
            if value is not None:
                # The Rust UI and viewport use f32. Match their multiplication
                # before rounding, including JSON's 0.899999976 form of 0.9.
                f32_value = struct.unpack("<f", struct.pack("<f", value))[0]
                scaled = struct.unpack("<f", struct.pack("<f", f32_value * 255))[0]
                for x, y, w, h in regions:
                    box = (round(x * rgba.width), round((1 - y - h) * rgba.height),
                           round((x + w) * rgba.width), round((1 - y) * rgba.height))
                    channels[index].paste(round(scaled), box)
        output = root / "surface.png"
        Image.merge("RGBA", channels).save(output)
        raise_if_cancelled(stop_event)
        dds = root / "surface.dds"
        report = encode_dds_with_directxtex(output, dds, dds_format="BC7_UNORM",
            width=rgba.width, height=rgba.height, mip_count=max_mips_for_size(*rgba.size),
            source_color_policy="ignore_srgb_metadata", stop_event=stop_event)
        if not report or not dds.is_file() or not dds.stat().st_size:
            raise ValueError(f"{part_name}: could not encode the translucent surface texture.")
        return dds.read_bytes()
