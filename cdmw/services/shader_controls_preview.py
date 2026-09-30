"""Shared preview parameters and exact source resources for shader experiments."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

from cdmw.core.temp_cache import session_generated_cache_path

from cdmw.core.common import raise_if_cancelled
from cdmw.domain.mesh.shader_controls import EYE_COVER, family_for, preview_factors, eye_cover_colour_range


EFFECT_MASK_PARAMETERS = frozenset({"_wingFlowTex1", "_tornPatternTexture", "_posterGlowNoiseTex",
                                    "_dissolveNoiseTex", "_hairAnisotropyDetailMaskTexture"})
EFFECT_NORMAL_PARAMETER = "_hairAnisotropyDetailNormalTexture"
EYE_COVER_ALPHA_PARAMETER = "_cdmwEyeCoverAlphaTexture"


def source_inputs(part):
    def field(row, name, default=None):
        return row.get(name, default) if isinstance(row, dict) else getattr(row, name, default)
    inputs = tuple(getattr(part, "preview_material_texture_inputs", ()) or ())
    parameters = list(getattr(part, "preview_material_parameters", ()) or ())
    textures, values = {}, {}
    for item in inputs:
        parameters.extend(field(item, "material_parameters", ()) or ())
        textures[field(item, "parameter_name", "")] = field(item, "source_texture_path", "")
    for parameter in parameters:
        values[field(parameter, "parameter_name", "")] = field(parameter, "value", field(parameter, "numeric_value", ""))
    return values, textures


def shader_control_diagnostic(part, controls, authored):
    """Read actual mask gates during worker preparation, never during UI repaint."""
    if controls.shader == EYE_COVER.shader:
        low, high = eye_cover_colour_range(controls, authored)
        warning = (f" Raw colour contribution can be outside 0–1 ({low:.4f} to {high:.4f}); "
                   "the viewport clamps it, while the inspected game expression does not.") if low < 0 or high > 1 else ""
        return EYE_COVER.note + warning
    if controls.shader in {"SkinnedMeshTornCloth_Ver2", "SkinnedMeshHairAnimatedUV"}:
        total = len(part.vertices)
        masks = getattr(part, "shader_masks", ())
        known = [value for value in masks if value[2] >= .5] if len(masks) == total else []
        if not known:
            return "Vertex R/G masks are unavailable; this preview leaves the vertices unchanged."
        red = sum(value[0] < 1 for value in known)
        green = sum(value[1] < 1 for value in known)
        ranges = "; ".join(f"{channel} {min(value[i] for value in known):.3f}–{max(value[i] for value in known):.3f}"
                           for i, channel in enumerate(("R", "G")))
        gate = (f"Tear masks: {red} length-grain, {green} cross-grain vertices."
                if controls.shader == "SkinnedMeshTornCloth_Ver2" else f"UV motion mask: {green} vertices below white green.")
        return f"Known masks: {len(known)}/{total}; {ranges}. {gate} Unknown vertices stay unchanged."
    if controls.shader == "SkinnedMeshAnisotropy":
        factors = preview_factors(controls, authored)
        gate = "active" if factors[1] else "inactive (source dye alpha is zero)"
        return f"Roughness byte: {factors[6]:g}/255; dye gate {gate}. Other packed bytes are preserved."
    return ""


def shader_preview_groups(mesh, choices, *, plain_pbr=False):
    from cdmw.services.new_item_materials import appearance_preview_part_names
    settings = {name.casefold(): controls for name, controls in choices}
    result = []
    for index, part in enumerate(mesh.submeshes):
        selected = [settings[name.casefold()] for name in appearance_preview_part_names(part) if name.casefold() in settings]
        if selected and any(value != selected[0] for value in selected):
            raise ValueError("Parts sharing a preview material need the same shader controls.")
        values, _ = source_inputs(part)
        if selected and plain_pbr and selected[0].shader == "SkinnedMeshWing":
            # Plain PBR conversion starts fully revealed in the output writer.
            # Explicit control values still win in preview_factors.
            values = {"_wingFlowProgress": "2"}
        if selected and plain_pbr and selected[0].shader == EYE_COVER.shader:
            values = {}
        result.append({"source_submesh_indices": [index], "editor_role": "replacement_preview",
                       "shader_controls": list(preview_factors(selected[0], values))
                       if selected else None})
    return tuple(result)


def publish_preview_texture(data):
    """Content-addressed derived DDS cache. Called by material preparation workers."""
    from cdmw.services.mesh_rust_replacement_materials import _replacement_texture_path
    directory = session_generated_cache_path("cdmw-shader-preview-v1")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(data).hexdigest() + ".dds")
    if not path.exists():
        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile(dir=directory, suffix=".dds", delete=False) as file:
            file.write(data)
            temporary = Path(file.name)
        try:
            _replacement_texture_path(temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    _replacement_texture_path(path)
    return str(path)


def attach_source_masks(part, source):
    """Match canonical preview vertices without guessing through ambiguous seams."""
    masks = getattr(source, "shader_masks", ())
    if len(masks) != len(source.vertices) or len(source.uvs) != len(source.vertices):
        return
    source_offsets = getattr(source, "source_vertex_offsets", ())
    offsets = getattr(part, "source_vertex_offsets", ())
    if len(source_offsets) == len(masks) and len(offsets) == len(part.vertices) and offsets:
        from cdmw.modding.mesh_deformer import shader_masks_by_source_offset
        lookup = shader_masks_by_source_offset(source)
        part.shader_masks = [lookup.get(offset, (1., 1., 0.)) for offset in offsets]
        return
    def key(position, uv):
        return tuple(round(float(v), 5) for v in (*position, *uv))
    lookup = {}
    for position, uv, mask in zip(source.vertices, source.uvs, masks):
        identity = key(position, uv)
        value = tuple(mask)
        if identity in lookup and lookup[identity] != value:
            lookup[identity] = None
        else:
            lookup[identity] = value
    if len(part.uvs) == len(part.vertices):
        part.shader_masks = [lookup.get(key(position, uv)) or (1., 1., 0.)
                             for position, uv in zip(part.vertices, part.uvs)]


def shader_preview_mesh(mesh, choices, *, snapshot=None, stop_event=None, plain_pbr=False):
    if not choices:
        return mesh
    from cdmw.services.new_item_materials import appearance_preview_part_names
    from cdmw.core.material_shader_controls import control_material_sources, rewrite_shader_controls
    settings = {name.casefold(): controls for name, controls in choices}
    result = copy.copy(mesh)
    result.submeshes = []
    decoded, source_meshes = {}, {}
    for part_index, part in enumerate(mesh.submeshes):
        raise_if_cancelled(stop_event)
        names = [name.casefold() for name in appearance_preview_part_names(part)]
        selected = [settings[name] for name in names if name in settings]
        if not selected:
            result.submeshes.append(part)
            continue
        controls = selected[0]
        controls.validate()
        if any(value != controls for value in selected):
            raise ValueError("Parts sharing a preview material need the same shader controls.")
        clone = copy.copy(part)
        values, textures = source_inputs(part)
        if plain_pbr and controls.shader == "SkinnedMeshWing":
            values = {"_wingFlowProgress": "2"}
            textures.pop("_wingFlowTex1", None)
        if plain_pbr and controls.shader == EYE_COVER.shader:
            values = {}
            textures.pop("_alphaTexture", None)
        path = str(getattr(part, "preview_source_asset_path", "") or mesh.path).replace("\\", "/")
        if not plain_pbr and snapshot is not None and path.casefold().endswith(".pac"):
            if path not in decoded:
                xml = path.replace("/model/", "/modelproperty/", 1) + "_xml"
                text = snapshot.payload(xml).decode("utf-8-sig") if snapshot.has_entry(xml) else ""
                decoded[path] = (text, control_material_sources(text))
            text, sources = decoded[path]
            source_name = next((name for name in names if name in sources), None)
            if source_name is not None:
                # Use the same compatibility checks and inherited values as
                # output, including Wing's visible starting pose on conversion.
                if controls.shader == EYE_COVER.shader or controls.cutout_mask is not None:
                    # Read inherited values without generating export BC7 maps
                    # on every preview edit. The GPU applies channel overrides.
                    _, values, textures = sources[source_name]
                else:
                    edited, _ = rewrite_shader_controls(text, ((source_name, controls),))
                    _, values, textures = control_material_sources(edited)[source_name]
            if controls.shader in {"SkinnedMeshTornCloth_Ver2", "SkinnedMeshHairAnimatedUV"} and snapshot.has_entry(path):
                if path not in source_meshes:
                    from cdmw.modding.mesh_parser import parse_pac
                    raise_if_cancelled(stop_event)
                    source_meshes[path] = parse_pac(snapshot.payload(path), path)
                for source_part in source_meshes[path].submeshes:
                    if source_part.name.casefold() in names or source_part.material.casefold() in names:
                        if len(getattr(clone, "shader_masks", ())) != len(clone.vertices):
                            attach_source_masks(clone, source_part)
                        break
        family = family_for(controls.shader)
        bindings = list(getattr(part, "preview_material_texture_inputs", ()) or ())
        resources = ((family.mask, textures.get(family.mask, family.default_mask), family.mask),
                     (EFFECT_NORMAL_PARAMETER, textures.get(EFFECT_NORMAL_PARAMETER, "") if controls.shader == "SkinnedMeshAnisotropy" else "", EFFECT_NORMAL_PARAMETER))
        if family == EYE_COVER:
            resources = ((EYE_COVER_ALPHA_PARAMETER, textures.get("_alphaTexture", ""), "_alphaTexture"),)
        if controls.cutout_mask is not None:
            from cdmw.services.transparency_masks import encode_cutout_texture
            resource = publish_preview_texture(encode_cutout_texture(controls.cutout_mask, compressed=False, stop_event=stop_event))
            bindings = [item for item in bindings if getattr(item, "parameter_name", "") != "_wingFlowTex1"]
            bindings.append(SimpleNamespace(parameter_name="_wingFlowTex1", source_texture_path=resource,
                source_dds_path=resource, preview_texture_path=resource, shader_family=family.shader,
                material_name=part.material, submesh_name=part.name, binding_authority="authoritative",
                owner_slot_index=max(0, int(getattr(part, "preview_pac_material_owner_slot_index", part_index)))))
            resources = ()
        for parameter, source_path, source_parameter in resources:
            if not source_path:
                continue
            if snapshot is None or not snapshot.has_entry(source_path):
                existing = next((item for item in bindings if getattr(item, "parameter_name", "") == source_parameter
                                 and (getattr(item, "source_dds_path", "") or getattr(item, "preview_texture_path", ""))), None)
                if existing is None:
                    raise ValueError(f"{part.name}: the shader preview texture is unavailable: {source_path}.")
                if parameter == source_parameter:
                    continue
                resource = getattr(existing, "source_dds_path", "") or existing.preview_texture_path
            else:
                raise_if_cancelled(stop_event)
                data = snapshot.payload(source_path)
                raise_if_cancelled(stop_event)
                resource = publish_preview_texture(data)
            bindings = [item for item in bindings if getattr(item, "parameter_name", "") != parameter]
            bindings.append(SimpleNamespace(parameter_name=parameter, source_texture_path=source_path,
                source_dds_path=resource, preview_texture_path=resource, shader_family=family.shader,
                material_name=part.material, submesh_name=part.name, binding_authority="authoritative",
                owner_slot_index=max(0, int(getattr(part, "preview_pac_material_owner_slot_index", part_index)))))
        clone.preview_material_texture_inputs = tuple(bindings)
        if controls.transparency_mask is not None:
            from cdmw.services.transparency_masks import preview_masked_part
            clone = preview_masked_part(clone, controls.colour_mask_for_output(), snapshot=snapshot, stop_event=stop_event,
                                        part_index=part_index)
        if controls.surface_response_mask is not None:
            from cdmw.services.transparency_masks import preview_masked_part
            clone = preview_masked_part(clone, controls.surface_response_mask, surface=True, snapshot=snapshot,
                                        stop_event=stop_event, part_index=part_index)
        clone.preview_native_material_overrides = dict(getattr(clone, "preview_native_material_overrides", {}) or {})
        clone.preview_native_material_overrides["shader_controls"] = list(preview_factors(controls, values))
        result.submeshes.append(clone)
    result.lod_levels = [result.submeshes]
    return result
