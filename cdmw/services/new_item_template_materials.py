"""Bake selected layered template materials for the texture-driven glass shader."""

from dataclasses import fields
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import hashlib
import threading

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.new_item_planning import NewItemPlanError


_BAKE_CACHE_MAX_BYTES = 64 * 1024 * 1024
_BAKE_CACHE_MAX_ENTRIES = 16
_BAKE_CACHE = OrderedDict()
_BAKE_CACHE_LOCK = threading.Lock()


def bake_template_translucency(snapshot, text, model_path, settings, *, on_log=None, on_progress=None, stop_event=None):
    from cdmw.core.archive_model_references import _parse_archive_model_sidecar_texture_bindings
    from cdmw.core.archive_model_texture_semantics import _is_placeholder_model_texture
    from cdmw.core.pac_xml_standard_material import PlainMaterial, find_material_wrappers, rewrite_materials
    from cdmw.core.texture_native import native_texture_backend_identity
    from cdmw.services.new_item_variants import xml_path

    selected = [row for row in find_material_wrappers(text)
                if row.submesh_name.casefold() in settings and (
                    not row.textures.get("_baseColorTexture")
                    or _is_placeholder_model_texture(row.textures["_baseColorTexture"]))]
    if not selected:
        return text, {}, ()
    # The shared combiner resolves each shader's declared colour and surface
    # inputs, including cloth and fur. Eligibility depends on usable output,
    # not a separate shader-name allowlist in the template workflow.
    bindings = _parse_archive_model_sidecar_texture_bindings(text, sidecar_path=xml_path(model_path))
    replacements, side, notes = {}, {}, []
    source_hash = hashlib.sha256(text.encode("utf-8")).digest()
    backend = native_texture_backend_identity()
    payloads = {}
    with TemporaryDirectory(prefix="cdmw_template_glass_") as temp:
        root = Path(temp)
        for index, row in enumerate(selected):
            raise_if_cancelled(stop_event)
            def report(message):
                detail = f"Material {index + 1}/{len(selected)}: {row.submesh_name}. {message}"
                if on_log is not None:
                    on_log(detail)
                if on_progress is not None:
                    on_progress(index, len(selected), detail)

            report("Reading source textures...")
            material_bindings = tuple(binding for binding in bindings
                if binding.submesh_name.casefold() == row.submesh_name.casefold()
                and not _is_placeholder_model_texture(binding.texture_path))
            fingerprints = []
            for path in dict.fromkeys(binding.texture_path for binding in material_bindings):
                raise_if_cancelled(stop_event)
                if path not in payloads:
                    if not snapshot.has_entry(path):
                        raise NewItemPlanError(f"{row.submesh_name}: cannot prepare translucency; missing texture {path}.")
                    # Read even on cache hits so the snapshot tracks current provenance.
                    payloads[path] = bytes(snapshot.payload(path))
                fingerprints.append((path, hashlib.sha256(payloads[path]).digest()))
            # Absorption values affect XML, not the baked pixels. Keep them out
            # of the key; all authored XML, DDS bytes and the encoder are included.
            key = (model_path, row.submesh_name, source_hash, tuple(fingerprints), backend)
            report("Checking prepared textures...")
            while not _BAKE_CACHE_LOCK.acquire(timeout=0.05):
                raise_if_cancelled(stop_event)
            try:
                raise_if_cancelled(stop_event)
                if key in _BAKE_CACHE:
                    maps = _BAKE_CACHE[key]
                    _BAKE_CACHE.move_to_end(key)
                    report("Reusing prepared textures.")
                else:
                    maps = _bake_material_maps(row, material_bindings, payloads, model_path,
                        root / str(index), index, report, stop_event)
                    raise_if_cancelled(stop_event)
                    size = sum(map(len, maps.values()))
                    if size <= _BAKE_CACHE_MAX_BYTES:
                        while _BAKE_CACHE and (len(_BAKE_CACHE) >= _BAKE_CACHE_MAX_ENTRIES
                                or sum(len(data) for entry in _BAKE_CACHE.values() for data in entry.values()) + size > _BAKE_CACHE_MAX_BYTES):
                            _BAKE_CACHE.popitem(last=False)
                        _BAKE_CACHE[key] = maps
            finally:
                _BAKE_CACHE_LOCK.release()
            raise_if_cancelled(stop_event)
            identity = hashlib.sha256(row.submesh_name.casefold().encode()).hexdigest()[:12]
            stem = str(PurePosixPath(model_path.replace("character/model/", "character/texture/")).with_suffix(""))
            paths = {}
            for role, data in maps.items():
                path = f"{stem}_cdmw_glass_{identity}_{role}.dds"
                side[path] = data
                paths[role] = path
            replacements[row.submesh_name] = PlainMaterial(**paths,
                emissive_texture=row.textures.get("_emissiveIntensityTexture", ""),
                emissive_color=row.value("_emissiveColor") or "#FFFFFFFF",
                emissive_intensity=float(row.value("_emissiveIntensity") or 1.0),
                render_flag=int(row.value("_renderSettingFlag")) if row.value("_renderSettingFlag") else None,
                translucency=settings[row.submesh_name.casefold()])
            notes.append(f"{row.submesh_name}: layered template colours and surface maps baked for translucency (up to 2048px); dye colours are fixed in the baked textures.")
            detail = f"Prepared materials: {index + 1}/{len(selected)}."
            if on_log is not None:
                on_log(detail)
            if on_progress is not None:
                on_progress(index + 1, len(selected), detail)
    return rewrite_materials(text, replacements).text, side, tuple(notes)


def _bake_material_maps(row, bindings, payloads, model_path, output, index, report, stop_event):
    from cdmw.core.texture_native import ensure_directxtex_dds_preview_pngs
    from cdmw.models import PreviewMaterialTextureInput
    from cdmw.rendering.crimson_shader_registry import decode_crimson_texture_binding
    from cdmw.rendering.material_combiner import MaterialPreviewCombinerSettings, combine_preview_material

    output.mkdir()
    sources, jobs, inputs = {}, {}, []
    input_fields = {field.name for field in fields(PreviewMaterialTextureInput)}
    for binding in bindings:
        raise_if_cancelled(stop_event)
        path = binding.texture_path
        decode = decode_crimson_texture_binding(shader_family=binding.shader_family,
            parameter_name=binding.parameter_name, source_path=path,
            sidecar_kind=binding.sidecar_kind, parameter_declared_by=binding.parameter_declared_by)
        slot = str(decode["slot"])
        if path not in sources:
            source = output / f"source_{len(sources)}.dds"
            source.write_bytes(payloads[path])
            sources[path] = source
        source = sources[path]
        jobs[str(source)] = {"dds_path": str(source), "max_dimension": 2048,
            "normal_space": "directx",
            "slot_kind": slot if slot in {"base", "normal", "height", "emissive"} else "material"}
        values = {name: getattr(binding, name) for name in input_fields if hasattr(binding, name)}
        inputs.append(PreviewMaterialTextureInput(**values, slot_kind=slot,
            source_texture_path=path, source_dds_path=str(source), texture_name=PurePosixPath(path).name,
            semantic_type=slot, semantic_subtype=str(decode.get("semantic_subtype", "")), visualized=True))
    report("Decoding source textures...")
    decoded = ensure_directxtex_dds_preview_pngs(tuple(jobs.values()), on_log=report, stop_event=stop_event)
    for item in inputs:
        preview = decoded.get(item.source_dds_path)
        if preview is None:
            raise NewItemPlanError(f"{row.submesh_name}: cannot decode translucency texture {item.source_texture_path}.")
        item.preview_texture_path = str(preview)
    report("Combining material layers...")
    combined = combine_preview_material(SimpleNamespace(material_name=row.submesh_name,
        source_path=model_path, material_texture_inputs=tuple(inputs), tangents_usable=True,
        texture_flip_vertical=False, alpha_mode="blend"), output, index,
        settings=MaterialPreviewCombinerSettings(support_map_max_dimension=2048,
            preserve_texture_orientation=True,
            requested_output_channels=frozenset({"base", "normal", "roughness", "metalness", "legacy_material"})),
        cancelled=stop_event.is_set if stop_event is not None else None)
    if not combined.base_source:
        raise NewItemPlanError(f"{row.submesh_name}: the layered material could not produce a base colour texture for translucency.")
    if any(item.binding_disposition == "layer_material_response" for item in inputs) and not combined.legacy_material_source:
        raise NewItemPlanError(f"{row.submesh_name}: the layered surface maps could not be prepared for translucency; check the material's detail masks.")
    maps = {}
    for role, source in (("base", combined.base_source), ("normal", combined.normal_source),
                         ("material", combined.legacy_material_source)):
        if source:
            if role == "base":
                report("Compressing colour texture...")
            elif role == "normal":
                report("Compressing normal map...")
            else:
                report("Compressing surface map...")
            maps[role] = _encode_baked_map(source, output / f"{role}.png", role,
                material=row.submesh_name, on_log=report, stop_event=stop_event)
    return maps


def _encode_baked_map(source, png, role, *, material, stop_event, on_log=None):
    from PIL import Image, ImageOps
    from PySide6.QtCore import QUrl
    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.domain.textures.output import max_mips_for_size

    raise_if_cancelled(stop_event)
    with Image.open(QUrl(source).toLocalFile() or source) as image:
        pixels = image.convert("RGBA" if role == "base" else "RGB")
    if role == "normal":
        # The preview combiner emits OpenGL normals; the game consumes DirectX.
        red, green, blue = pixels.split()
        pixels = Image.merge("RGB", (red, ImageOps.invert(green), blue))
    elif role == "material":
        _, green, blue = pixels.split()
        pixels = Image.merge("RGB", (Image.new("L", pixels.size, 255), green, blue))
    pixels.save(png)
    dds = png.with_suffix(".dds")
    report = encode_dds_with_directxtex(png, dds,
        dds_format={"base": "BC7_UNORM", "normal": "BC5_UNORM", "material": "BC1_UNORM"}[role],
        width=pixels.width, height=pixels.height, mip_count=max_mips_for_size(*pixels.size),
        source_color_policy="ignore_srgb_metadata", on_log=on_log, stop_event=stop_event)
    raise_if_cancelled(stop_event)
    if not report or not dds.is_file() or not dds.stat().st_size:
        raise NewItemPlanError(f"{material}: could not encode the {role} texture for translucency.")
    return dds.read_bytes()
