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

    from cdmw.services.mesh_asset_context import is_item_set

    session = authoring.shadow_service._session(authoring.shadow_session_id)
    item_set = is_item_set(getattr(session, "archive_refit_context", None))
    # A set refuses Import Replacement, not colour edits: its pieces keep their own files.
    reason = "" if item_set else replacement["reason"]
    if session.mesh_format != "pac":
        reason = "Material colours require a PAC and its material sidecar."
    elif session.hair_state is not None:
        reason = "Finish the hair workflow before changing material colours."
    bindings = {part.part_id: part for part in session.replacement_state.parts} if session.replacement_state else {}
    set_colours = ({f"{asset}|{material}": colours for asset, material, colours in session.archive_refit_context.material_colours}
                   if item_set else {})
    sources = {row["id"]: row for row in shader_state.get("parts", ())}

    def material_of(part):
        if item_set:
            # Pieces of a set can reuse a wrapper name; the piece is part of the identity.
            return set_material_key(part)
        return str(sources.get(part["id"], {}).get("source", {}).get("part", "") or "")

    shared = {}
    for part in replacement["parts"]:
        shared.setdefault(material_of(part), []).append(part["id"])
    parts = []
    for part in replacement["parts"]:
        source = sources.get(part["id"], {})
        material = material_of(part)
        binding = bindings.get(part["id"])
        blocked = ""
        if binding is not None and binding.material_choice == "imported":
            blocked = "This part uses imported materials, which do not read the original material colours."
        elif binding is not None and binding.shader_controls is not None and binding.shader_controls.rebuild:
            blocked = "Shader experiments rewrite this material with its own rows. Turn off the rewrite to change its colours."
        saved = set_colours.get(material) if item_set else (binding.material_colours if binding is not None else ())
        rows = _rows_for(source.get("authored"))
        if item_set and not rows:
            rows = _captured_set_rows(session.archive_refit_context, material)
        parts.append({**part, "material": material, "shared": shared.get(material, [part["id"]]) if material else [part["id"]],
                      "rows": rows, "blocked": blocked,
                      "material_colours": colours_to_dict(saved) if saved else None})
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


# ----- item sets ------------------------------------------------------------------------
# A set (Open set in Mesh Editor, or ticked Scene parts) has no replacement state: its
# pieces keep their own files. Material colours and Glow edits of its pieces live in the
# set context, keyed by the piece (asset id) and the folded wrapper name, with each edited
# piece's .pac_xml captured once; Build Mod writes that file through the same writers a
# single file uses (colours, then Glow).

def _captured_set_rows(context, material):
    """A set part's colour rows from its piece's captured material file, when there is one."""
    from cdmw.core.material_colours import wrapper_colours
    from cdmw.domain.pac_xml_editor import decode_pac_xml_payload

    asset, _, name = material.partition("|")
    data = next((data for owner, _entry, data in context.material_colour_files if owner == asset), None)
    if data is None:
        return []
    try:
        variants = wrapper_colours(decode_pac_xml_payload(data)[0])
    except ValueError:
        return []
    return _rows_for([{"rows": [{"kind": "Color", "name": row, "value": value} for row, value in variant[name].items()]}
                      for variant in variants if name in variant])


def set_material_key(part_row):
    """``"<asset id>|<folded material name>"`` for a set part row of the replacement state."""
    name = str(part_row.get("set_material") or part_row.get("name", "")).strip().casefold()
    return f"{part_row.get('asset_id', '')}|{name}"


def _set_rows(rows, context, invalid, foreign, twice):
    if not isinstance(rows, list) or len(rows) > 4096:
        raise ValueError(invalid)
    assets = {asset.asset_id for asset in context.assets}
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("asset") not in assets or not isinstance(row.get("material"), str):
            raise ValueError(foreign)
        key = (row["asset"], row["material"].strip().casefold())
        if key in seen:
            raise ValueError(twice)
        seen.add(key)
        yield key, row


def load_item_set_colours(rows, context):
    """The set context's colour edits from a draft, checked against the set's pieces."""
    result = {key: normalize_material_colours(row.get("colours")) for key, row in _set_rows(
        rows, context, "Item set draft has invalid material colours",
        "Item set draft material colours name a piece that is not in the set",
        "Item set draft lists a material's colours twice")}
    return tuple(sorted((asset, material, colours) for (asset, material), colours in result.items()))


def load_item_set_emissions(rows, context):
    """The set context's Glow edits from a draft."""
    from cdmw.domain.mesh.emission import EmissionChoice
    result = {key: EmissionChoice.from_dict(row.get("emission")) for key, row in _set_rows(
        rows, context, "Item set draft has invalid glow settings",
        "Item set draft glow settings name a piece that is not in the set",
        "Item set draft lists a material's glow twice")}
    return tuple((asset, material, value) for (asset, material), value in sorted(result.items(), key=lambda item: item[0]))


def _edited_assets(context):
    return ({asset for asset, _material, _value in context.material_colours}
            | {asset for asset, _material, _value in getattr(context, "emissions", ())})


def _set_part_keys(ui, args, unselected, invalid_reset):
    parts = {part["id"]: part for part in ui["parts"]}
    keys = args.get("part_ids")
    if (not isinstance(keys, (list, tuple)) or not keys or any(not isinstance(key, str) for key in keys)
            or len(set(keys)) != len(keys) or not set(keys) <= set(parts)):
        raise ValueError(unselected)
    reset = args.get("reset", False)
    if type(reset) is not bool:
        raise ValueError(invalid_reset)
    return parts, keys, reset


def _commit_set_edit(authoring, args, owners, update, label, *, capture):
    """Capture the edited pieces' material files, prove the write, record one Undo step."""
    service, session_id = authoring.shadow_service, authoring.shadow_session_id
    session = service._session(session_id)
    context = session.archive_refit_context
    # Read each edited piece's material file once, before the lock, and prove the
    # write works now rather than at Build Mod.
    files = {asset: (entry, data) for asset, entry, data in context.material_colour_files}
    if capture:
        for asset in context.assets:
            if asset.asset_id in owners and asset.asset_id not in files:
                _owner, entry, data = _capture_set_colour_file(
                    asset, args.get("_archive_dependencies"), index_source=args.get("_archive_index_source"))
                files[asset.asset_id] = (entry, data)
    with session.export_lock:
        if session.archive_refit_context is not context:
            raise ValueError("The set changed while its material file was read. Try again.")
        edited = update(context)
        if edited == context:
            return service.session_view(session_id)
        kept = _edited_assets(edited)
        edited = replace(edited, material_colour_files=tuple(
            (asset, entry, data) for asset, (entry, data) in sorted(files.items(), key=lambda item: item[0])
            if asset in kept))
        item_set_material_files(edited)
        service._push_history(session, prefer_native=True, action="item_set_material_edit", label=label)
        session.undo_stack[-1].restore_archive_refit_context = True
        session.undo_stack[-1].archive_refit_context = context
        session.archive_refit_context = edited
        session.revision += 1
        service._schedule_mesh_layer_autosave(session)
    return service.session_view(session_id)


def set_item_set_material_colours(authoring, args):
    """Material colours for a set's piece: one Undo step, kept in the set context."""
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    from cdmw.services.mesh_shader_controls import shader_controls_ui_state

    replacement = replacement_ui_state(authoring)
    ui = material_colours_ui_state(authoring, replacement, shader_controls_ui_state(authoring, replacement))
    if not ui["available"]:
        raise ValueError(ui["reason"])
    parts, keys, reset = _set_part_keys(ui, args, "Select at least one material part for material colours.",
                                        "Invalid material colour reset request.")
    value = () if reset else normalize_material_colours(args.get("colours"))
    if not reset:
        available = {row["name"].casefold() for key in keys for row in parts[key]["rows"]}
        unknown = [name for name, _ in value if name.casefold() not in available]
        if unknown:
            raise ValueError("The selected material has no colour row named " + ", ".join(unknown) + ".")
    materials = {tuple(parts[key]["material"].split("|", 1)) for key in keys}

    def update(context):
        current = {(asset, material): colours for asset, material, colours in context.material_colours}
        for material in materials:
            if reset:
                current.pop(material, None)
            else:
                current[material] = value
        return replace(context, material_colours=tuple(
            sorted((asset, material, rows) for (asset, material), rows in current.items())))

    return _commit_set_edit(authoring, args, {owner for owner, _ in materials}, update,
                            "Restore material colours" if reset else "Edit material colours", capture=not reset)


def set_item_set_emission(authoring, args):
    """Glow for a set's piece: ``{part_ids, emission}`` or ``{part_ids, reset: true}``."""
    from cdmw.domain.mesh.emission import EmissionChoice
    from cdmw.services.mesh_emission import emission_ui_state
    from cdmw.services.mesh_rust_replacement import replacement_ui_state

    ui = emission_ui_state(authoring, replacement_ui_state(authoring))
    if not ui["available"]:
        raise ValueError(ui["reason"])
    parts, keys, reset = _set_part_keys(ui, args, "Select at least one material part for glow.",
                                        "Invalid glow reset request.")
    value = None if reset else EmissionChoice.from_dict(args.get("emission"))
    if value is not None:
        value.validate()
    materials = {tuple(set_material_key(parts[key]).split("|", 1)) for key in keys}

    def update(context):
        current = {(asset, material): choice for asset, material, choice in context.emissions}
        for material in materials:
            if reset:
                current.pop(material, None)
            else:
                current[material] = value
        return replace(context, emissions=tuple(
            (asset, material, choice) for (asset, material), choice in sorted(current.items(), key=lambda item: item[0])))

    return _commit_set_edit(authoring, args, {owner for owner, _ in materials}, update,
                            "Restore material glow" if reset else "Edit material glow", capture=not reset)


def _set_sidecar_path(entry):
    return str(entry.path).replace("\\", "/").casefold().replace("/model/", "/modelproperty/", 1) + "_xml"


def _capture_set_colour_file(asset, dependencies, stop_event=None, *, index_source=None):
    """(asset_id, ArchiveEntry, bytes) of a set piece's .pac_xml.

    The file is looked up in the archive context the edit came with, then in the
    piece's own preview dependencies, then in the loaded archives' index: a set's
    other files (lower body, accessories, ``_sub01`` pieces) are rarely in the
    first file's dependency list.
    """
    from cdmw.core.archive_extraction import read_archive_entry_data

    path = _set_sidecar_path(asset.entry)
    matches = ()
    for context in (dependencies, getattr(asset.preview_lease, "archive_dependencies", None)):
        index = getattr(context, "entries_by_normalized_path", None)
        if index:
            matches = tuple(index.get(path, ()))
        if not matches:
            matches = tuple(item for item in getattr(context, "entries", ()) or ()
                            if str(item.path).replace("\\", "/").casefold() == path)
        if matches:
            break
    if not matches and index_source is not None:
        entry = index_source.open(stop_event).active_entry(path)
        if entry is not None:
            matches = (entry,)
    if not matches:
        raise ValueError(f"{asset.entry.basename}: its material file was not found in the archive. "
                         "Reopen the set from Browse Archives to change its colours.")
    data, _, _ = read_archive_entry_data(matches[0], stop_event=stop_event)
    return asset.asset_id, matches[0], bytes(data)


def item_set_material_files(context, stop_event=None):
    """Per edited set piece: (asset, sidecar entry, original bytes, written bytes, new files).

    Colours are written first, then Glow through the single-file Glow writer, so a
    piece's material file carries both. New files are the generated glow textures a
    wrapper without its own glow map needs.
    """
    from cdmw.core.material_colours import rewrite_material_colours
    from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementFile, ReplacementPart
    from cdmw.domain.pac_xml_editor import decode_pac_xml_payload

    files = {asset: (entry, data) for asset, entry, data in context.material_colour_files}
    result = []
    for asset in context.assets:
        colours = {material: colours_to_dict(rows) for owner, material, rows in context.material_colours
                   if owner == asset.asset_id}
        glows = {material: choice for owner, material, choice in getattr(context, "emissions", ())
                 if owner == asset.asset_id}
        if not colours and not glows:
            continue
        raise_if_cancelled(stop_event)
        if asset.asset_id not in files:
            raise ValueError(f"{asset.entry.basename}: its material file was not captured. "
                             "Reopen the set from Browse Archives to change its colours.")
        entry, original = files[asset.asset_id]
        written, extras = original, ()
        if colours:
            text, source_format = decode_pac_xml_payload(written)
            written = source_format.bom + rewrite_material_colours(text, colours).encode(source_format.encoding)
        if glows:
            from cdmw.core.pac_xml_standard_material import find_material_wrappers, wrapper_key
            from cdmw.services.mesh_emission import build_emission_files

            text, _ = decode_pac_xml_payload(written)
            names = {wrapper_key(row.submesh_name) for row in find_material_wrappers(text)}
            mesh = asset.source.mesh

            def glow_for(part):
                return glows.get(material_binding_name(part, names),
                                 glows.get(str(part.name or part.material or "").strip().casefold()))

            state = MeshReplacementState(
                str(asset.entry.path), "0" * 64,
                tuple(ReplacementPart(f"set:{index}", index, emission=glow_for(part))
                      for index, part in enumerate(mesh.submeshes)),
                dependencies=(ReplacementFile(str(entry.path), written),))
            built = build_emission_files(state, mesh, (), stop_event=stop_event)
            sidecar = str(entry.path).replace("\\", "/").casefold()
            written = next(file.data for file in built if file.path.replace("\\", "/").casefold() == sidecar)
            extras = tuple(file for file in built if file.path.replace("\\", "/").casefold() != sidecar)
        result.append((asset, entry, original, written, extras))
    return result


def item_set_colour_files(context, stop_event=None):
    """[(sidecar entry, original bytes, written bytes)] for each edited set piece."""
    return [(entry, original, written) for _asset, entry, original, written, _extras
            in item_set_material_files(context, stop_event)]


def stage_item_set_colour_preview(authoring, mesh, context, base_key):
    """The material key the editor should draw for a set with colour or Glow edits."""
    import hashlib
    from cdmw.services.mesh_asset_context import ASSET_ATTRIBUTE
    from cdmw.services.mesh_rust_authoring import _atomic_write_payload, _mesh_lods
    from cdmw.services.mesh_rust_preview_package import conserve_preview_core_material_graph
    from cdmw.services.mesh_rust_replacement_materials import _bake_edited_native_layers
    from cdmw.services.mesh_shader_controls import _owner_slot
    from cdmw.services.shader_controls_preview import source_inputs

    cache, references = authoring.archive_refit_material_cache, authoring.archive_refit_material_references
    if base_key not in cache:
        return base_key
    emissions = tuple(getattr(context, "emissions", ()))
    key = base_key
    if context.material_colours or emissions:
        identity = (base_key, context.material_colours,
                    tuple((asset, material, choice.to_dict()) for asset, material, choice in emissions))
        key = hashlib.sha256(repr(identity).encode()).hexdigest()[:32]
    if key not in cache:
        payload = copy.deepcopy(cache[base_key])
        payload["key"] = key
        edits = {f"{asset}|{material}": colours_to_dict(colours) for asset, material, colours in context.material_colours}
        glows = {f"{asset}|{material}": choice for asset, material, choice in emissions}
        owners, glow_owners, present = {}, {}, {}
        for lod_index, level in enumerate(_mesh_lods(mesh)):
            for index, part in enumerate(level):
                owner = f"{getattr(part, ASSET_ATTRIBUTE, '')}|{(part.name or part.material or '').strip().casefold()}"
                if owner in glows:
                    glow_owners[(lod_index, index)] = owner
                if owner not in edits:
                    continue
                owners[(lod_index, index)] = owner
                if owner not in present:
                    values, _ = source_inputs(part, _owner_slot(part))
                    present[owner] = tuple(name for name, value in values.items() if _COLOUR.fullmatch(str(value)))
        for owner, colours in edits.items():
            if not present.get(owner):
                present[owner] = tuple(colours)
        if glow_owners:
            # As for a single file: glowing parts draw from composed maps, with their colours.
            _bake_edited_native_layers(authoring, mesh, payload, set(glow_owners), None,
                                       colours={slot: edits[owner] for slot, owner in owners.items()
                                                if slot in glow_owners})
        recolour_preview_graph(payload, owners, present, edits)
        presentations = {(row["lod_index"], row["material_index"]): row for row in payload.get("material_presentations", ())}
        for (lod_index, index), owner in glow_owners.items():
            choice = glows[owner]
            row = presentations.setdefault((lod_index, index), {"lod_index": lod_index, "material_index": index})
            row["emissive_color"] = list(choice.color)
            row["emissive_intensity"] = choice.intensity
            row["emission_animation"] = list(choice.animation.factors())
            row["emission_reveal"] = list(choice.rgb.factors()) if choice.rgb is not None else [0.0, 1.0, 0.0, -1.0]
        payload["material_presentations"] = list(presentations.values())
        conserve_preview_core_material_graph(payload)
        cache[key] = payload
    # The base needs a file too, so restoring every edit switches the editor back.
    for cache_key in dict.fromkeys((base_key, key)):
        if cache_key not in references:
            references[cache_key] = _atomic_write_payload(
                authoring.root, f"material-state-{cache_key}.json", cache[cache_key], data_type="mesh_materials_json",
                element_count=1, expected_root_identity=authoring.root_identity)
    return key
