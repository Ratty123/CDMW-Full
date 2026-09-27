"""Prepare one part's painter from the same material routing used by export."""
from dataclasses import dataclass, replace

from PIL import Image, ImageOps

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.mesh.shader_controls import EYE_COVER, ShaderControls
from cdmw.domain.new_item.spec import MaterialRoute
from cdmw.domain.textures.transparency_mask import TransparencyMask
from cdmw.services.transparency_masks import decode_texture


@dataclass(frozen=True)
class TransparencyPaintSource:
    mask: TransparencyMask
    reference_rgba: bytes
    surface_mask: TransparencyMask | None = None
    controls: ShaderControls | None = None
    mode: str = "blending"


def prepare_transparency_paint(snapshot, appearance, part, mode, *, template_key=None, result=None, scene=None,
                               on_log=None, stop_event=None):
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    from cdmw.services.new_item_materials import route_model_files, source_materials_from_import
    from cdmw.services.new_item_planning import ModelFiles, NewItemPlanError, model_files_from_import
    from cdmw.services.new_item_shader_controls import shader_control_bindings
    from cdmw.services.new_item_surface import apply_surface_settings
    from cdmw.services.new_item_template_model import prepare_template_model
    from cdmw.services.new_item_translucency import apply_prebuilt_translucency
    from cdmw.services.new_item_variants import variant_family

    glass = mode == "translucency"
    controls = dict(appearance.shader_controls).get(part)
    if (mode not in {"translucency", "blending", "cutout"}
            or (glass and (appearance.translucency is None or not appearance.translucency.matches(part)))
            or (not glass and (controls is None or controls.shader !=
                              ("SkinnedMeshWing" if mode == "cutout" else EYE_COVER.shader)))):
        raise ValueError("Enable transparency on this part before painting its mask.")
    current = (appearance.translucency.mask_for(part) if glass else controls.cutout_mask
               if mode == "cutout" else controls.transparency_mask)
    # Prepare from source inputs, not the previous BC7 export. Saved authored
    # masks below are lossless and never pass through the export writer here.
    appearance = replace(appearance, shader_controls=(), translucency=(
        replace(appearance.translucency, masks=()) if appearance.translucency is not None else None))
    raise_if_cancelled(stop_event)
    source_slots = []
    if appearance.custom_model:
        if result is None:
            raise ValueError("Apply the placement before painting this imported model's transparency.")
        sources = source_materials_from_import(result, scene) if scene is not None else {}
        for name, source in sources.items():
            if source.atlas_section is not None and part.casefold() in {
                    name, source.name.casefold(), *(item.name.casefold() for item in source.atlas_sources)}:
                raise ValueError("Painted transparency needs separate material textures. Import these atlas parts separately before painting.")
        if isinstance(result, ModelFiles):
            files = result
        else:
            family = variant_family(snapshot.family(template_key), appearance)
            files = model_files_from_import(result, family=family)
        if glass:
            if MaterialRoute(appearance.material_route) is not MaterialRoute.PLAIN_PBR:
                raise NewItemPlanError("Enable Plain PBR materials to export translucency.")
            # Only source colour/alpha is needed by this canvas. Running the export
            # route here recompresses glass, glow and surface maps for every part.
            for name, source in sources.items():
                if part.casefold() in {name, source.name.casefold()} and source.base_slot is not None:
                    if source.base_slot not in source_slots:
                        source_slots.append(source.base_slot)
        else:
            if isinstance(result, ModelFiles):
                files = apply_prebuilt_translucency(files, MaterialRoute(appearance.material_route),
                    appearance.translucency, on_log=on_log, stop_event=stop_event)
            else:
                files = route_model_files(files, MaterialRoute(appearance.material_route), result=result, scene=scene,
                    glow=appearance.glow_choice(), translucency=appearance.translucency, on_log=on_log, stop_event=stop_event)
            files = apply_surface_settings(files, appearance.surface_settings, result=result, scene=scene, stop_event=stop_event)
    else:
        if glass:
            files = prepare_template_model(snapshot, [appearance.model_path], glow=appearance.glow_choice(),
                translucency=appearance.translucency, stop_event=stop_event, on_log=on_log)
        else:
            from cdmw.services.new_item_variants import xml_path
            path = xml_path(appearance.model_path)
            if not snapshot.has_entry(path):
                raise ValueError("The source material document is unavailable for transparency painting.")
            files = ModelFiles(b"", {path: snapshot.payload(path)})
    mapped = shader_control_bindings(files, ((part, ShaderControls(EYE_COVER.shader)),), result=result, scene=scene)
    payloads = {path.replace("\\", "/").casefold(): data for path, data in files.side_files.items()}

    def read(path):
        key = path.replace("\\", "/").casefold()
        data = payloads.get(key)
        if data is None and snapshot.has_entry(path):
            data = snapshot.payload(path)
        if data is None:
            raise ValueError(f"The transparency painter cannot read texture {path}.")
        return decode_texture(data, stop_event=stop_event)

    targets = []
    for path, names in mapped.items():
        selected = {name.casefold() for name, _ in names}
        targets.extend(row for row in find_material_wrappers(files.side_files[path].decode("utf-8-sig"))
                       if row.submesh_name.casefold() in selected)
    base_paths = {row.textures.get("_baseColorTexture") or (
        row.textures.get("_overlayColorTexture", "") if glass and appearance.custom_model else "") for row in targets}
    if len(base_paths) != 1 or len(source_slots) > 1:
        raise ValueError("This part uses several texture layouts. Import it as separate materials to paint each texture.")
    if source_slots and source_slots[0].source_path.suffix.casefold() != ".dds":
        from cdmw.modding.material_texture_payloads import _source_slot_png_with_base_color_factor_path
        slot = source_slots[0]
        path = _source_slot_png_with_base_color_factor_path(slot, stop_event=stop_event)
        reference = decode_texture(path.read_bytes(), stop_event=stop_event)
        if slot.alpha_mode.upper() == "OPAQUE":
            reference.putalpha(255)
    else:
        reference = read(next(iter(base_paths))) if next(iter(base_paths)) else Image.new("RGBA", (512, 512), "white")
    if mode == "blending":
        for parameter in ("_materialTexture", "_alphaTexture"):
            if len({row.textures.get(parameter, "") for row in targets}) != 1:
                raise ValueError("This part uses several transparency maps. Import it as separate materials before painting.")
    if current is not None:
        size = (current.width, current.height)
    else:
        # Bound interactive painting memory, retaining the texture's aspect ratio.
        scale = min(1., 2048 / max(reference.size))
        size = tuple(max(1, round(value * scale)) for value in reference.size)
        parameter = "_baseColorTexture" if glass else "_materialTexture"
        paths = base_paths if glass else {row.textures.get(parameter, "") for row in targets}
        if len(paths) != 1:
            raise ValueError("This part uses several transparency maps. Import it as separate materials before painting.")
        image = reference if glass else (
            read(next(iter(paths))) if next(iter(paths)) and mode != "cutout"
            else Image.new("RGBA", size, (0, 0, 0, 255)))
        plane = image.getchannel("A" if glass else "R").resize(size, Image.Resampling.BILINEAR)
        if glass:
            plane = ImageOps.invert(plane)
        elif mode == "cutout" or controls.coverage_mapping == "calibrated_v1":
            plane = Image.new("L", size, 0)
        elif "material_red" in dict(controls.values):
            plane = Image.new("L", size, round(dict(controls.values)["material_red"][0] * 255))
        current = TransparencyMask(*size, plane.tobytes())
    surface = None
    if mode == "blending":
        surface = controls.surface_response_mask
        if surface is None:
            paths = {row.textures.get("_alphaTexture", "") for row in targets}
            if len(paths) != 1:
                raise ValueError("This part uses several surface maps. Import it as separate materials before painting.")
            path = next(iter(paths))
            plane = read(path).getchannel("R").resize(size, Image.Resampling.BILINEAR) if path else Image.new("L", size, 255)
            if "surface_alpha" in dict(controls.values):
                plane = Image.new("L", size, round(dict(controls.values)["surface_alpha"][0] * 255))
            surface = TransparencyMask(*size, ImageOps.invert(plane).tobytes())
    raise_if_cancelled(stop_event)
    return TransparencyPaintSource(current, reference.resize(size, Image.Resampling.BILINEAR).tobytes(),
                                   surface, controls if not glass else None, mode)
