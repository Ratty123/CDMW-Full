"""Reversible per-part translucency, built from captured material sidecars."""

from dataclasses import replace

from cdmw.domain.mesh.translucency import translucency_values, translucency_surface_values
from cdmw.services.mesh_replacement_materials import _sidecar_text


def build_translucency_files(state, original, companion_files, *, stop_event=None):
    """Preserve source data; export selected absorption and optional surface maps."""
    settings, surfaces = {}, {}
    for part in state.parts:
        source = original.submeshes[part.target_index]
        name = (source.material or source.name).casefold()
        value = translucency_values(part.translucency) if part.translucency is not None else None
        surface = translucency_surface_values(part.translucency_surface)
        if surface is not None and value is None:
            raise ValueError("Surface overrides require translucency on the same part.")
        if name in settings and (settings[name] != value or surfaces[name] != surface):
            raise ValueError("Select all parts sharing this material and use the same translucency settings.")
        settings[name] = value
        surfaces[name] = surface
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
    from cdmw.domain.mesh.replacement import ReplacementFile
    from cdmw.services.translucency_surface import apply_translucency_surface

    def read_texture(path):
        key = path.replace("\\", "/").casefold()
        file = files.get(key, sources.get(key))
        return file.data if file is not None else None

    text, generated = apply_translucency_surface(_sidecar_text(source.data), settings, surfaces,
                                               state.target_path, read_texture, stop_event=stop_event)
    for key, data in generated.items():
        files[key.casefold()] = ReplacementFile(key, data)
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
        {**part, "translucency": bindings[part["id"]].translucency if part["id"] in bindings else None,
         "translucency_surface": bindings[part["id"]].translucency_surface if part["id"] in bindings else None}
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
    surface = None if reset else translucency_surface_values(args.get("translucency_surface"))
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    parts = tuple(replace(part, translucency=value,
                         translucency_surface=surface if reset or "translucency_surface" in args else part.translucency_surface)
                  if part.part_id in keys else part for part in state.parts)
    if parts == state.parts:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    state = replace(state, parts=parts, revision=state.revision + 1)
    # Validate the exact eventual sidecar before the undoable state changes.
    build_translucency_files(state, parse_mesh(snapshot.original_data, state.target_path), state.companion_files, stop_event=stop_event)
    mesh = mesh_with_part_ids(snapshot, state)
    stage_replacement_materials(authoring, mesh, state, stop_event)
    return commit_replacement(authoring.shadow_service, snapshot, mesh, state,
                              label="Restore material translucency" if reset else "Edit material translucency",
                              stop_event=stop_event)
