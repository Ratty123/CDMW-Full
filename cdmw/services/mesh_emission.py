"""Undoable glow edits using the Mesh Editor's captured material dependencies."""
from dataclasses import replace
from pathlib import PurePosixPath

from cdmw.core.common import raise_if_cancelled
from cdmw.domain.mesh.emission import EmissionChoice
from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.services.mesh_replacement_materials import _sidecar_text


def build_emission_files(state, original, companion_files, *, stop_event=None):
    from cdmw.core.pac_xml_standard_material import find_material_wrappers, rewrite_emission
    from cdmw.core.pac_xml_emission import rewrite_emission_animation
    from cdmw.services.new_item_materials import encode_emissive_solid

    settings = {}
    for part in state.parts:
        source = original.submeshes[part.target_index]
        name = (source.material or source.name).casefold()
        if name in settings and settings[name] != part.emission:
            raise ValueError("Select all parts sharing this material and use the same glow settings.")
        if part.emission is not None:
            part.emission.validate()
            if part.translucency is not None and (part.emission.animation.active or part.emission.rgb is not None):
                raise ValueError("Animated glow cannot share a part with translucency.")
        settings[name] = part.emission
    settings = {name: value for name, value in settings.items() if value is not None}
    if not settings:
        return tuple(companion_files)
    if original.format.casefold() != "pac":
        raise ValueError("Glow editing requires a PAC and its material sidecar.")
    path = state.target_path.replace("\\", "/").casefold().replace("/model/", "/modelproperty/", 1) + "_xml"
    files = {file.path.replace("\\", "/").casefold(): file for file in companion_files}
    sources = {file.path.replace("\\", "/").casefold(): file for file in state.dependencies}
    if len(files) != len(companion_files) or len(sources) != len(state.dependencies):
        raise ValueError("Glow material sources are ambiguous.")
    source = files.get(path, sources.get(path))
    if source is None:
        raise ValueError("The matching PAC XML is missing. Open this item from the archive to edit glow.")
    text = _sidecar_text(source.data)
    text = rewrite_emission_animation(text, {name: value.animation for name, value in settings.items()})
    emission = {}
    for wrapper in find_material_wrappers(text):
        raise_if_cancelled(stop_event)
        value = settings.get(wrapper.submesh_name.casefold())
        if value is None:
            continue
        texture = wrapper.textures.get("_emissiveIntensityTexture", "")
        if not texture and value.rgb is not None:
            texture = wrapper.textures.get("_emissiveProgressTexture", "")
            if not texture:
                raise ValueError(f"{wrapper.submesh_name}: RGB glow needs a source glow texture.")
        if not texture:
            texture = str(PurePosixPath(state.target_path.replace("/model/", "/texture/", 1)).with_suffix("")) + "_cdmw_glow.dds"
            if texture.casefold() not in files:
                files[texture.casefold()] = ReplacementFile(texture, encode_emissive_solid())
        emission[wrapper.submesh_name] = (texture, value.hex_color(), value.intensity)
    text = rewrite_emission(text, emission)
    from cdmw.core.pac_xml_emission import rewrite_rgb_emission
    text = rewrite_rgb_emission(text, {name: (value.rgb, value.hex_color()) for name, value in settings.items()})
    files[path] = replace(source, data=(b"\xef\xbb\xbf" if source.data.startswith(b"\xef\xbb\xbf") else b"") + text.encode("utf-8"))
    return tuple(files.values())


def emission_ui_state(authoring, replacement):
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    reason = replacement["reason"]
    if session.mesh_format != "pac":
        reason = "Glow editing requires a PAC and its material sidecar."
    elif session.hair_state is not None:
        reason = "Finish the hair workflow before changing the material shader."
    bindings = {part.part_id: part for part in session.replacement_state.parts} if session.replacement_state else {}
    return {"available": not reason, "reason": reason, "parts": [
        {**part, "emission": bindings[part["id"]].emission.to_dict()
         if part["id"] in bindings and bindings[part["id"]].emission is not None else None}
        for part in replacement["parts"]]}


def set_emission(authoring, snapshot, args, *, entry, dependencies, stop_event):
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids, commit_replacement
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    from cdmw.services.mesh_rust_replacement_materials import stage_replacement_materials
    from cdmw.services.mesh_translucency import build_translucency_files

    ui = emission_ui_state(authoring, replacement_ui_state(authoring))
    if not ui["available"]:
        raise ValueError(ui["reason"])
    keys = args.get("part_ids")
    if (not isinstance(keys, (list, tuple)) or not keys
            or any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys)
            or not set(keys) <= {part["id"] for part in ui["parts"]}):
        raise ValueError("Select at least one material part for glow.")
    reset = args.get("reset", False)
    if type(reset) is not bool:
        raise ValueError("Invalid glow reset request.")
    value = None if reset else EmissionChoice.from_dict(args.get("emission"))
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    parts = tuple(replace(part, emission=value) if part.part_id in keys else part for part in state.parts)
    if parts == state.parts:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    state = replace(state, parts=parts, revision=state.revision + 1)
    original = parse_mesh(snapshot.original_data, state.target_path)
    companions = build_translucency_files(state, original, state.companion_files, stop_event=stop_event)
    build_emission_files(state, original, companions, stop_event=stop_event)
    mesh = mesh_with_part_ids(snapshot, state)
    stage_replacement_materials(authoring, mesh, state, stop_event)
    return commit_replacement(authoring.shadow_service, snapshot, mesh, state,
                              label="Restore material glow" if reset else "Edit material glow", stop_event=stop_event)
