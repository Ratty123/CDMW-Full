"""Bake selected layered template materials for the texture-driven glass shader."""

from dataclasses import fields
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import hashlib

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.new_item_planning import NewItemPlanError


def bake_template_translucency(snapshot, text, model_path, settings, *, stop_event=None):
    from cdmw.core.archive_model_references import _parse_archive_model_sidecar_texture_bindings
    from cdmw.core.archive_model_texture_semantics import _is_placeholder_model_texture
    from cdmw.core.pac_xml_standard_material import PlainMaterial, find_material_wrappers, rewrite_materials
    from cdmw.core.texture_native import ensure_directxtex_dds_preview_pngs
    from cdmw.models import PreviewMaterialTextureInput
    from cdmw.rendering.crimson_shader_registry import decode_crimson_texture_binding
    from cdmw.rendering.material_combiner import MaterialPreviewCombinerSettings, combine_preview_material
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
    input_fields = {field.name for field in fields(PreviewMaterialTextureInput)}
    with TemporaryDirectory(prefix="cdmw_template_glass_") as temp:
        root = Path(temp)
        sources, jobs = {}, {}
        for index, row in enumerate(selected):
            raise_if_cancelled(stop_event)
            inputs = []
            for binding in bindings:
                if binding.submesh_name.casefold() != row.submesh_name.casefold():
                    continue
                path = binding.texture_path
                if _is_placeholder_model_texture(path):
                    continue
                decode = decode_crimson_texture_binding(shader_family=binding.shader_family,
                    parameter_name=binding.parameter_name, source_path=path,
                    sidecar_kind=binding.sidecar_kind, parameter_declared_by=binding.parameter_declared_by)
                slot = str(decode["slot"])
                if path.casefold() not in sources:
                    raise_if_cancelled(stop_event)
                    if not snapshot.has_entry(path):
                        raise NewItemPlanError(f"{row.submesh_name}: cannot prepare translucency; missing texture {path}.")
                    source = root / f"source_{len(sources)}.dds"
                    source.write_bytes(snapshot.payload(path))
                    sources[path.casefold()] = source
                source = sources[path.casefold()]
                jobs[str(source)] = {"dds_path": str(source), "max_dimension": 2048,
                    "normal_space": "directx",
                    "slot_kind": slot if slot in {"base", "normal", "height", "emissive"} else "material"}
                values = {name: getattr(binding, name) for name in input_fields if hasattr(binding, name)}
                inputs.append(PreviewMaterialTextureInput(**values, slot_kind=slot,
                    source_texture_path=path, source_dds_path=str(source), texture_name=PurePosixPath(path).name,
                    semantic_type=slot, semantic_subtype=str(decode.get("semantic_subtype", "")), visualized=True))
            decoded = ensure_directxtex_dds_preview_pngs(tuple(jobs.values()), stop_event=stop_event)
            for item in inputs:
                preview = decoded.get(item.source_dds_path)
                if preview is None:
                    raise NewItemPlanError(f"{row.submesh_name}: cannot decode translucency texture {item.source_texture_path}.")
                item.preview_texture_path = str(preview)
            output = root / str(index)
            output.mkdir()
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
            identity = hashlib.sha256(row.submesh_name.casefold().encode()).hexdigest()[:12]
            stem = str(PurePosixPath(model_path.replace("character/model/", "character/texture/")).with_suffix(""))
            paths = {}
            for role, source in (("base", combined.base_source), ("normal", combined.normal_source),
                                 ("material", combined.legacy_material_source)):
                if source:
                    path = f"{stem}_cdmw_glass_{identity}_{role}.dds"
                    side[path] = _encode_baked_map(source, output / f"{role}.png", role,
                                                  material=row.submesh_name, stop_event=stop_event)
                    paths[role] = path
            replacements[row.submesh_name] = PlainMaterial(**paths,
                emissive_texture=row.textures.get("_emissiveIntensityTexture", ""),
                emissive_color=row.value("_emissiveColor") or "#FFFFFFFF",
                emissive_intensity=float(row.value("_emissiveIntensity") or 1.0),
                render_flag=int(row.value("_renderSettingFlag")) if row.value("_renderSettingFlag") else None,
                translucency=settings[row.submesh_name.casefold()])
            notes.append(f"{row.submesh_name}: layered template colours and surface maps baked for translucency (up to 2048px); dye colours are fixed in the baked textures.")
    return rewrite_materials(text, replacements).text, side, tuple(notes)


def _encode_baked_map(source, png, role, *, material, stop_event):
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
        source_color_policy="ignore_srgb_metadata", stop_event=stop_event)
    if not report or not dds.is_file():
        raise NewItemPlanError(f"{material}: could not encode the {role} texture for translucency.")
    return dds.read_bytes()
