"""Export and preview the same selected surface edits without changing emission."""
import copy
from dataclasses import replace
import hashlib
import re

from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.surface import validate_surface_settings
from cdmw.services.new_item_glow_surface import encode_glow_surface, glow_surface_regions
from cdmw.services.new_item_planning import NewItemPlanError
from cdmw.services.translucency_surface import _encode_surface


def apply_surface_settings(files, choices, *, result=None, scene=None, stop_event=None):
    if not choices:
        return files
    validate_surface_settings(choices)
    from cdmw.services.new_item_materials import _plain_pbr_inputs, source_materials_from_import

    sources = source_materials_from_import(result, scene) if result is not None and scene is not None else {}
    source_by_base = {}
    if sources:
        inputs = _plain_pbr_inputs(files, sources)
        # Builder clones can share an import-owned dependency with their source.
        # A shared template texture or an ambiguous source is not an owner.
        source_by_base = {path: source for path, source in inputs[-1].items() if path in inputs[3]}
    side, found = dict(files.side_files), set()
    by_lower = {path.replace("\\", "/").casefold(): path for path in side}
    for key in tuple(side):
        if not key.casefold().endswith(".pac_xml"):
            continue
        data = side[key]
        text = data.decode("utf-8-sig")
        for wrapper in reversed(find_material_wrappers(text)):
            base = wrapper.textures.get("_baseColorTexture", "")
            source = sources.get(wrapper.submesh_name.casefold()) or source_by_base.get(base.replace("\\", "/").casefold())
            edits = []
            for name, choice in choices:
                regions = glow_surface_regions(source, wrapper.submesh_name, {name.casefold()})
                if regions:
                    found.add(name.casefold())
                    if choice.wanted:
                        edits.append((choice, regions))
            if not edits:
                continue
            block = text[wrapper.start:wrapper.end]
            for role in ("_baseColorTexture", "_materialTexture"):
                selected = [(choice, regions) for choice, regions in edits if
                            (choice.color is not None if role == "_baseColorTexture" else
                             choice.roughness is not None or choice.metallic is not None)]
                if not selected:
                    continue
                original = wrapper.textures.get(role, "")
                local = by_lower.get(original.replace("\\", "/").casefold())
                if local is None:
                    raise NewItemPlanError(f"{wrapper.submesh_name}: surface editing needs the owned {role} texture.")
                payload = side[local]
                for choice, regions in selected:
                    raise_if_cancelled(stop_event)
                    if role == "_baseColorTexture":
                        color = "#" + "".join(f"{round(channel * 255):02X}" for channel in choice.color) + "FF"
                        payload = encode_glow_surface(payload, color, regions,
                            part_name=wrapper.submesh_name, stop_event=stop_event)
                    else:
                        payload = _encode_surface(payload, (choice.roughness, choice.metallic),
                            part_name=wrapper.submesh_name, stop_event=stop_event, regions=regions)
                identity = hashlib.sha256(payload).hexdigest()[:16]
                target = original.removesuffix(".dds") + f"_surface_{identity}.dds"
                side[target] = payload
                pattern = (r'(<MaterialParameterTexture\b[^>]*\b_name="' + re.escape(role)
                           + r'"[^>]*>[\s\S]*?\b_path=")[^"]*(")')
                block, count = re.subn(pattern, lambda match: match[1] + target + match[2], block)
                if count != 1:
                    raise NewItemPlanError(f"{wrapper.submesh_name}: surface texture binding is ambiguous.")
            text = text[:wrapper.start] + block + text[wrapper.end:]
        side[key] = (b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b"") + text.encode("utf-8")
    missing = {name.casefold() for name, _ in choices} - found
    if missing:
        raise NewItemPlanError("Surface material bindings were not found: " + ", ".join(sorted(missing)))
    return replace(files, side_files=side, notes=(*files.notes, "Surface colour and reflections adjusted on selected materials."))


def surface_preview_groups(mesh, choices, *, translucency=None):
    """Overlay explicit channels after the complete Glow/Translucency statement."""
    validate_surface_settings(choices)
    from cdmw.services.new_item_materials import appearance_preview_part_names

    wanted = {name.casefold(): choice for name, choice in choices}
    groups = []
    for index, part in enumerate(getattr(mesh, "submeshes", ())):
        matched = {wanted[name.casefold()] for name in appearance_preview_part_names(part) if name.casefold() in wanted}
        if not matched:
            continue
        if len(matched) > 1:
            raise ValueError("Parts sharing one material need the same surface settings.")
        choice = matched.pop()
        group = {"source_submesh_indices": [index], "editor_role": "replacement_preview"}
        if choice.color is not None:
            # The existing renderer field replaces hue while preserving value.
            group["glow_surface_color"] = [round(value * 255) / 255 for value in choice.color]
        if choice.roughness is not None or choice.metallic is not None:
            inherited = translucency.surface_for(*appearance_preview_part_names(part)) if translucency else None
            group["translucency_surface"] = [value if value is not None else previous
                for value, previous in zip((choice.roughness, choice.metallic), inherited or (None, None))]
        groups.append(group)
    return tuple(groups)


def surface_preview_mesh(mesh, choices):
    if not choices:
        return mesh
    result = copy.copy(mesh)
    result.submeshes = [copy.copy(part) for part in mesh.submeshes]
    for group in surface_preview_groups(mesh, choices):
        for index in group["source_submesh_indices"]:
            part = result.submeshes[index]
            overrides = dict(getattr(part, "preview_native_material_overrides", {}) or {})
            for name in ("glow_surface_color", "translucency_surface"):
                if name in group:
                    value = group[name]
                    if name == "translucency_surface":
                        value = [v if v is not None else old for v, old in zip(value, overrides.get(name) or (None, None))]
                    overrides[name] = value
            part.preview_native_material_overrides = overrides
    return result
