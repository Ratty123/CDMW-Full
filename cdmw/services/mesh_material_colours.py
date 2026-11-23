"""Undoable edits of the colours a part's PAC material declares (Material colours panel).

Armour colour mostly lives in ``_tintColorR/G/B`` and its neighbours in the
``.pac_xml``, applied through the wrapper's colour mask. These edits change the
RGB of rows the wrapper already has, keep each row's alpha, and ride the same
replacement-state route as Glow and Shader experiments: one Undo step per edit,
kept in the draft, written into the mod by Build Mod.
"""
from __future__ import annotations

import copy
import re
from dataclasses import replace

from cdmw.core.common import raise_if_cancelled
from cdmw.domain.mesh.material_colours import (colours_to_dict, material_colour_label, material_colour_order,
                                               normalize_material_colours, owned_elsewhere)
from cdmw.services.mesh_replacement_materials import material_binding_name, material_binding_names

_COLOUR = re.compile(r"#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})?")


def _sidecar_path(state):
    return state.target_path.replace("\\", "/").casefold().replace("/model/", "/modelproperty/", 1) + "_xml"


def material_colour_settings(state, original):
    """{material binding name: {row: "#RRGGBB"}} for the parts with colour edits; checks conflicts."""

    if not any(part.material_colours for part in state.parts):
        return {}
    names = material_binding_names(state)
    settings = {}
    for part in state.parts:
        name = material_binding_name(original.submeshes[part.target_index], names)
        value = part.material_colours
        if name in settings and settings[name] != value:
            raise ValueError(f"{name}: parts that share a material must use the same material colours.")
        if value:
            if part.material_choice == "imported":
                raise ValueError(f"{name}: an imported material does not use the original material colours. "
                                 "Keep Original Materials to change them.")
            controls = part.shader_controls
            if controls is not None and controls.rebuild:
                raise ValueError(f"{name}: Shader experiments rewrite this material with its own rows. "
                                 "Turn off the rewrite or restore shader controls before changing material colours.")
            if controls is not None and {n.casefold() for n, _ in controls.values} & {n.casefold() for n, _ in value}:
                raise ValueError(f"{name}: a colour is set both in Shader experiments and in Material colours.")
        settings[name] = value
    return {name: colours_to_dict(value) for name, value in settings.items() if value}


def build_material_colour_files(state, original, companion_files, *, stop_event=None):
    """Write the chosen colours into the target's PAC XML among ``companion_files``."""

    from cdmw.core.material_colours import rewrite_material_colours
    from cdmw.domain.pac_xml_editor import decode_pac_xml_payload

    settings = material_colour_settings(state, original)
    if not settings:
        return tuple(companion_files)
    if original.format.casefold() != "pac":
        raise ValueError("Material colours require a PAC and its material sidecar.")
    path = _sidecar_path(state)
    files = {file.path.replace("\\", "/").casefold(): file for file in companion_files}
    sources = {file.path.replace("\\", "/").casefold(): file for file in state.dependencies}
    if len(files) != len(companion_files) or len(sources) != len(state.dependencies):
        raise ValueError("Material colour sources are ambiguous.")
    source = files.get(path, sources.get(path))
    if source is None:
        raise ValueError("The matching PAC XML is missing. Open this item from the archive to change its colours.")
    raise_if_cancelled(stop_event)
    text, source_format = decode_pac_xml_payload(source.data)
    text = rewrite_material_colours(text, settings)
    files[path] = replace(source, data=source_format.bom + text.encode(source_format.encoding))
    return tuple(files.values())


def _rows_for(authored):
    """The colour rows of the first (viewport) variant, then rows only other variants declare."""

    rows, seen = [], set()
    for variant in authored or ():
        for row in variant.get("rows", ()) or ():
            name, value = str(row.get("name", "")), str(row.get("value", ""))
            match = _COLOUR.fullmatch(value)
            if (not match or row.get("kind", "") not in {"Color", ""} or owned_elsewhere(name)
                    or name.casefold() in seen):
                continue
            seen.add(name.casefold())
            rows.append({"name": name, "label": material_colour_label(name),
                         "original": "#" + match.group(1).upper(),
                         "alpha": int(match.group(2), 16) if match.group(2) else 255})
    return sorted(rows, key=lambda row: material_colour_order(row["name"]))


def material_colours_ui_state(authoring, replacement, shader_state):
    """What the Material colours section shows, built on the shader panel's source rows."""

    session = authoring.shadow_service._session(authoring.shadow_session_id)
    reason = replacement["reason"]
    if session.mesh_format != "pac":
        reason = "Material colours require a PAC and its material sidecar."
    elif session.hair_state is not None:
        reason = "Finish the hair workflow before changing material colours."
    bindings = {part.part_id: part for part in session.replacement_state.parts} if session.replacement_state else {}
    sources = {row["id"]: row for row in shader_state.get("parts", ())}
    shared = {}
    for row in sources.values():
        shared.setdefault(str(row.get("source", {}).get("part", "")), []).append(row["id"])
    parts = []
    for part in replacement["parts"]:
        source = sources.get(part["id"], {})
        material = str(source.get("source", {}).get("part", ""))
        binding = bindings.get(part["id"])
        blocked = ""
        if binding is not None and binding.material_choice == "imported":
            blocked = "This part uses imported materials, which do not read the original material colours."
        elif binding is not None and binding.shader_controls is not None and binding.shader_controls.rebuild:
            blocked = "Shader experiments rewrite this material with its own rows. Turn off the rewrite to change its colours."
        parts.append({**part, "material": material, "shared": shared.get(material, [part["id"]]) if material else [part["id"]],
                      "rows": _rows_for(source.get("authored")), "blocked": blocked,
                      "material_colours": colours_to_dict(binding.material_colours)
                      if binding is not None and binding.material_colours else None})
    return {"available": not reason, "reason": reason, "parts": parts}


def set_material_colours(authoring, snapshot, args, *, entry, dependencies, stop_event):
    """``{part_ids, colours: {row: "#RRGGBB"}}`` or ``{part_ids, reset: true}``.

    Every part that shares a selected part's material gets the same colours,
    since they are one wrapper in the file. One Undo step.
    """
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_replacement_import import commit_replacement, initial_replacement_state, mesh_with_part_ids
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    from cdmw.services.mesh_rust_replacement_materials import stage_replacement_materials
    from cdmw.services.mesh_shader_controls import shader_controls_ui_state

    replacement = replacement_ui_state(authoring)
    ui = material_colours_ui_state(authoring, replacement, shader_controls_ui_state(authoring, replacement))
    if not ui["available"]:
        raise ValueError(ui["reason"])
    parts = {part["id"]: part for part in ui["parts"]}
    keys = args.get("part_ids")
    if (not isinstance(keys, (list, tuple)) or not keys or any(not isinstance(key, str) for key in keys)
            or len(set(keys)) != len(keys) or not set(keys) <= set(parts)):
        raise ValueError("Select at least one material part for material colours.")
    reset = args.get("reset", False)
    if type(reset) is not bool:
        raise ValueError("Invalid material colour reset request.")
    for key in keys:
        if parts[key]["blocked"] and not reset:
            raise ValueError(parts[key]["blocked"])
    value = () if reset else normalize_material_colours(args.get("colours"))
    if not reset:
        available = {row["name"].casefold() for key in keys for row in parts[key]["rows"]}
        unknown = [name for name, _ in value if name.casefold() not in available]
        if unknown:
            raise ValueError("The selected material has no colour row named " + ", ".join(unknown) + ".")
    targets = {member for key in keys for member in parts[key]["shared"] if member in parts}
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    edited = tuple(replace(part, material_colours=value) if part.part_id in targets else part for part in state.parts)
    if edited == state.parts:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    state = replace(state, parts=edited, revision=state.revision + 1)
    # Prove the export can write it before it becomes an Undo step.
    original = parse_mesh(snapshot.original_data, state.target_path)
    from cdmw.services.mesh_shader_controls import build_shader_control_files
    prepared = build_material_colour_files(state, original, state.companion_files, stop_event=stop_event)
    build_shader_control_files(state, original, prepared, stop_event=stop_event)
    mesh = mesh_with_part_ids(snapshot, state)
    stage_replacement_materials(authoring, mesh, state, stop_event)
    return commit_replacement(authoring.shadow_service, snapshot, mesh, state,
                              label="Restore material colours" if reset else "Edit material colours",
                              stop_event=stop_event)


# ----- preview --------------------------------------------------------------------------

def _key(name):
    return str(name).casefold().lstrip("_")


def _tint_candidates(role, channel):
    """The colour rows Preview Core reads for a layer's tint, in its order.

    Mirrors ``tint_for_layer`` in ``native/cdmw_preview_core/src/owners/material_selection_cache.cpp``.
    """
    c = channel
    if role == "color_seed":
        return (f"dyeingcolormask{c}",)
    if role == "grime":
        return (f"tintcolor{c}", f"dyeingdetaillayercolormask{c}", f"scratchtintcolor{c}")
    if role == "detail":
        return (f"dyeingdetaillayercolormask{c}", f"dyeingcolormask{c}", f"tintcolor{c}")
    if role == "overlay":
        return ("overlaycolor", f"tintcolor{c}", "tintcolor")
    return (f"tintcolor{c}", f"dyeingcolormask{c}", f"basecolor{c}", f"diffusecolor{c}", f"albedocolor{c}",
            f"materialcolor{c}", "basecolor", "diffusecolor", "albedocolor", "materialcolor", "tintcolor")


#: Colours the preview promotes to a whole-surface tint (``preview_tint_contract``).
_SURFACE_TINTS = ("albedocolor", "basecolor", "baseheighttintcolor", "tintcolor")


def _rgb(colour):
    value = colour.lstrip("#")
    return [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def _set_rgb(target, colour):
    if isinstance(target, list) and len(target) >= 3:
        target[:3] = _rgb(colour)


def recolour_preview_graph(payload, owners, present, edits):
    """Retint the graph layers and presentations the edited colours feed.

    ``owners`` maps (lod, material index) to a wrapper key; ``present`` gives
    each wrapper key's colour row names, ``edits`` its {row: "#RRGGBB"}. A layer
    takes the edited colour only where that row is the first one Preview Core
    would read for it, so precedence matches the original preview.
    """
    graph = payload.get("preview_core_material_graph") or {}
    for row in graph.get("materials", ()) or ():
        key = owners.get((row.get("lod_index"), row.get("material_index")))
        if key is None:
            continue
        names = {_key(name) for name in present.get(key, ())}
        colours = {_key(name): colour for name, colour in edits.get(key, {}).items()}
        for layer in row.get("layers", ()) or ():
            role = str(layer.get("layer_role", "")).casefold()
            channel = str(layer.get("mask_channel", "")).casefold()
            source = next((name for name in _tint_candidates(role, channel) if name in names), None)
            if source in colours:
                _set_rgb(layer.get("tint"), colours[source])
            scratch = f"scratchtintcolor{channel}"
            if role == "detail" and scratch in colours and isinstance(layer.get("scratch_tint"), list):
                _set_rgb(layer["scratch_tint"], colours[scratch])
    for row in payload.get("material_presentations", ()) or ():
        key = owners.get((row.get("lod_index"), row.get("material_index")))
        if key is None or not isinstance(row.get("texture_tint"), list):
            continue
        colours = {_key(name): colour for name, colour in edits.get(key, {}).items()}
        source = next((name for name in _SURFACE_TINTS if name in {_key(n) for n in present.get(key, ())}), None)
        if source in colours:
            _set_rgb(row["texture_tint"], colours[source])


def recolour_preview_parameters(part, colours):
    """A copy of ``part`` whose preview material parameters carry the edited colours.

    Used where an edited part's maps are composed again (Glow, Translucency and
    Shader experiments re-bake their layers), so that bake sees the new colours.
    """
    if not colours:
        return part
    folded = {_key(name): colour for name, colour in colours.items()}

    def patched(parameters):
        result = []
        for parameter in parameters or ():
            name = parameter.get("parameter_name", "") if isinstance(parameter, dict) else getattr(parameter, "parameter_name", "")
            colour = folded.get(_key(name))
            if colour is None:
                result.append(parameter)
                continue
            parameter = copy.copy(parameter)
            old = parameter.get("value", "") if isinstance(parameter, dict) else getattr(parameter, "value", "")
            match = _COLOUR.fullmatch(str(old))
            value = colour.upper() + (match.group(2).upper() if match and match.group(2) else "")
            if isinstance(parameter, dict):
                parameter["value"] = value
                if "color_value" in parameter:
                    parameter["color_value"] = tuple(_rgb(colour))
            else:
                parameter.value = value
                if hasattr(parameter, "color_value"):
                    parameter.color_value = tuple(_rgb(colour))
            result.append(parameter)
        return type(parameters)(result) if isinstance(parameters, tuple) else result

    part = copy.copy(part)
    if getattr(part, "preview_material_parameters", None):
        part.preview_material_parameters = patched(part.preview_material_parameters)
    inputs = []
    for item in getattr(part, "preview_material_texture_inputs", ()) or ():
        item = copy.copy(item)
        if isinstance(item, dict):
            item["material_parameters"] = patched(item.get("material_parameters", ()))
        else:
            item.material_parameters = patched(item.material_parameters)
        inputs.append(item)
    if inputs:
        part.preview_material_texture_inputs = type(part.preview_material_texture_inputs)(inputs) \
            if isinstance(part.preview_material_texture_inputs, tuple) else inputs
    return part


def stage_colour_preview(mesh, state, payload):
    """Apply the parts' colour edits to an already staged material payload."""
    from cdmw.core.material_colours import wrapper_colours
    from cdmw.domain.mesh.replacement import bound_part_indices
    from cdmw.services.mesh_replacement_materials import _sidecar_text
    from cdmw.services.mesh_rust_authoring import _mesh_lods
    from cdmw.services.shader_controls_preview import preview_material_variant

    names = material_binding_names(state)
    edits = {}
    indices = bound_part_indices(mesh, state)
    for part in state.parts:
        if part.material_colours:
            edits[material_binding_name(mesh.submeshes[indices[part.part_id]], names)] = colours_to_dict(part.material_colours)
    if not edits:
        return
    files = {file.path.replace("\\", "/").casefold(): file for file in (*state.dependencies, *state.companion_files)}
    sidecar = files.get(_sidecar_path(state))
    text = _sidecar_text(sidecar.data) if sidecar is not None else ""
    owners, present = {}, {}
    for lod_index, level in enumerate(_mesh_lods(mesh)):
        for index, part in enumerate(level):
            key = material_binding_name(part, names)
            if key not in edits:
                continue
            owners[(lod_index, index)] = key
            if text and key not in present:
                for variant in wrapper_colours(preview_material_variant(text, part)):
                    if key in variant:
                        present[key] = tuple(variant[key])
                        break
            present.setdefault(key, tuple(edits[key]))
    recolour_preview_graph(payload, owners, present, edits)
