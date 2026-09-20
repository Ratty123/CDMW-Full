"""Reversible per-part translucency, built from captured material sidecars."""

from dataclasses import replace
import re

from cdmw.core.pac_xml_standard_material import find_material_wrappers, TRANSLUCENT_SHADER
from cdmw.domain.mesh.translucency import translucency_values
from cdmw.services.mesh_replacement_materials import _sidecar_text


def build_translucency_files(state, original, companion_files):
    """Preserve all source material data; edit only the shader and absorption."""
    settings = {}
    for part in state.parts:
        source = original.submeshes[part.target_index]
        name = (source.material or source.name).casefold()
        value = translucency_values(part.translucency) if part.translucency is not None else None
        if name in settings and settings[name] != value:
            raise ValueError("Select all parts sharing this material and use the same translucency settings.")
        settings[name] = value
    settings = {name: value for name, value in settings.items() if value is not None}
    if not settings:
        return tuple(companion_files)
    if original.format.casefold() != "pac":
        raise ValueError("Translucency requires a PAC and its material sidecar.")
    path = state.target_path.replace("\\", "/").casefold().replace("/model/", "/modelproperty/", 1) + "_xml"
    files = {file.path.replace("\\", "/").casefold(): file for file in companion_files}
    sources = {file.path.replace("\\", "/").casefold(): file for file in state.dependencies}
    if len(files) != len(companion_files) or len(sources) != len(state.dependencies):
        raise ValueError("Translucency material sources are ambiguous.")
    source = files.get(path, sources.get(path))
    if source is None:
        raise ValueError("The matching PAC XML is missing. Open this item from the archive to edit translucency.")
    text = _sidecar_text(source.data)
    if len(text) > 16 * 1024 * 1024:
        raise ValueError("Translucency material sidecar exceeds the supported size limit.")
    edits, found = [], set()
    for wrapper in find_material_wrappers(text):
        name = wrapper.submesh_name.casefold()
        if name not in settings:
            continue
        if not wrapper.textures.get("_baseColorTexture"):
            raise ValueError(
                f"{wrapper.submesh_name}: this material has no base colour texture. "
                "Convert it to Plain PBR before using translucency."
            )
        found.add(name)
        block = text[wrapper.start:wrapper.end]
        block = block.replace(f'_materialName="{wrapper.shader}"', f'_materialName="{TRANSLUCENT_SHADER}"', 1)
        newline = "\r\n" if "\r\n" in block else "\n"
        for parameter, item_id, value in (
            ("_thickness", "3214133184954366", settings[name][0]),
            ("_extinctionCoefficient", "3161969463918590", settings[name][1]),
        ):
            # Remove only these two overrides, leaving emission, permutations,
            # texture paths and unfamiliar game parameters intact.
            block = re.sub(r'<MaterialParameterFloat\b[^>]*\bStringItemID="' + parameter
                           + r'"[^>]*/>', "", block)
            used = [int(index) for index in re.findall(r'\bIndex="(\d+)"', block)]
            row = (f'<MaterialParameterFloat StringItemID="{parameter}" ItemID="{item_id}" '
                   f'_name="{parameter}" _value="{value:.6f}" Index="{max(used, default=-1) + 1}"/>')
            position = block.rfind("</Vector>")
            if position < 0:
                raise ValueError("The material has no editable parameter vector.")
            block = block[:position] + row + newline + wrapper.indent + "\t" + block[position:]
        edits.append((wrapper.start, wrapper.end, block))
    if settings.keys() - found:
        raise ValueError("Translucency material bindings were not found: " + ", ".join(sorted(settings.keys() - found)))
    for start, end, block in reversed(edits):
        text = text[:start] + block + text[end:]
    files[path] = replace(source, data=text.encode("utf-8"))
    return tuple(files.values())


def translucency_ui_state(authoring, replacement):
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    reason = replacement["reason"]
    if session.mesh_format != "pac":
        reason = "Translucency requires a PAC and its material sidecar."
    elif session.hair_state is not None:
        reason = "Finish the hair workflow before changing the material shader."
    bindings = {part.part_id: part for part in session.replacement_state.parts} if session.replacement_state else {}
    return {"available": not reason, "reason": reason, "parts": [
        {**part, "translucency": bindings[part["id"]].translucency if part["id"] in bindings else None}
        for part in replacement["parts"]
    ]}


def set_translucency(authoring, snapshot, args, *, entry, dependencies, stop_event):
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids, commit_replacement
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    from cdmw.services.mesh_rust_replacement_materials import stage_replacement_materials

    ui = translucency_ui_state(authoring, replacement_ui_state(authoring))
    if not ui["available"]:
        raise ValueError(ui["reason"])
    keys = args.get("part_ids")
    if (not isinstance(keys, (list, tuple)) or not keys
            or any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys)
            or not set(keys) <= {part["id"] for part in ui["parts"]}):
        raise ValueError("Select at least one material part for translucency.")
    reset = args.get("reset", False)
    if type(reset) is not bool:
        raise ValueError("Invalid translucency reset request.")
    value = None if reset else translucency_values(args.get("translucency"))
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    parts = tuple(replace(part, translucency=value) if part.part_id in keys else part for part in state.parts)
    if parts == state.parts:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    state = replace(state, parts=parts, revision=state.revision + 1)
    # Validate the exact eventual sidecar before the undoable state changes.
    build_translucency_files(state, parse_mesh(snapshot.original_data, state.target_path), state.companion_files)
    mesh = mesh_with_part_ids(snapshot, state)
    stage_replacement_materials(authoring, mesh, state, stop_event)
    return commit_replacement(authoring.shadow_service, snapshot, mesh, state,
                              label="Restore material translucency" if reset else "Edit material translucency",
                              stop_event=stop_event)
