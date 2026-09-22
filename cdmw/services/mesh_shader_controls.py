"""Undoable experimental material edits in the existing Mesh Editor workflow."""
from dataclasses import replace
from pathlib import PurePosixPath

from cdmw.core.common import raise_if_cancelled
from cdmw.core.material_shader_controls import rewrite_shader_controls
from cdmw.domain.mesh.shader_controls import ShaderControls, catalogue_payload, family_for
from cdmw.services.mesh_replacement_materials import _sidecar_text, material_binding_name, material_binding_names


def shader_settings(state, original):
    if not any(part.shader_controls is not None for part in state.parts):
        return ()
    names = material_binding_names(state)
    settings = {}
    for part in state.parts:
        source = original.submeshes[part.target_index]
        name = material_binding_name(source, names)
        if name in settings and settings[name] != part.shader_controls:
            raise ValueError("Select all parts sharing this material and use the same shader controls.")
        if part.shader_controls is not None:
            part.shader_controls.validate()
            if part.translucency is not None or part.emission is not None:
                raise ValueError(f"{name}: restore Glow and Translucency before choosing another shader experiment.")
        settings[name] = part.shader_controls
    return tuple((name, value) for name, value in settings.items() if value is not None)


def build_shader_control_files(state, original, companion_files, *, stop_event=None):
    choices = shader_settings(state, original)
    if not choices:
        return tuple(companion_files)
    static = original.format.casefold() != "pac"
    files = {file.path.replace("\\", "/").casefold(): file for file in companion_files}
    sources = {file.path.replace("\\", "/").casefold(): file for file in state.dependencies}
    if len(files) != len(companion_files) or len(sources) != len(state.dependencies):
        raise ValueError("Shader material sources are ambiguous.")
    target = state.target_path.replace("\\", "/").casefold()
    paths = [str(PurePosixPath(target).with_suffix(".pami"))] if static else [target.replace("/model/", "/modelproperty/", 1) + "_xml"]
    # A static model can have several captured PAMI variants. Restrict to its
    # captured material documents; never search or edit unrelated archive files.
    if static:
        paths = [key for key in dict.fromkeys((*sources, *files)) if key.endswith(".pami")]
    found = set()
    for path in paths:
        raise_if_cancelled(stop_event)
        source = files.get(path, sources.get(path))
        if source is None:
            continue
        from cdmw.domain.pac_xml_editor import decode_pac_xml_payload
        source_text, source_format = decode_pac_xml_payload(source.data)
        text, matches = rewrite_shader_controls(source_text, choices, static=static, allow_missing=True)
        if matches:
            found.update(matches)
            files[path] = replace(source, data=source_format.bom + text.encode(source_format.encoding))
    missing = {name for name, _ in choices} - found
    if missing:
        raise ValueError("The matching material sidecar is missing or incomplete for: " + ", ".join(sorted(missing)))
    return tuple(files.values())


def shader_controls_ui_state(authoring, replacement):
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    reason = replacement["reason"]
    if session.hair_state is not None:
        reason = "Finish the hair workflow before changing shader controls."
    bindings = {part.part_id: part for part in session.replacement_state.parts} if session.replacement_state else {}
    diagnostics = {}
    if session.replacement_state is not None:
        from cdmw.services.mesh_rust_replacement_materials import replacement_material_key
        key = replacement_material_key(session.working_mesh, session.replacement_state)
        diagnostics = authoring.archive_refit_material_cache.get(key, {}).get("shader_diagnostics", {})
    return {"available": not reason, "reason": reason, "catalogue": catalogue_payload(),
            "static": session.mesh_format != "pac", "parts": [
                {**part, "diagnostic": diagnostics.get(part["id"], ""),
                 "shader_controls": bindings[part["id"]].shader_controls.to_dict()
                 if part["id"] in bindings and bindings[part["id"]].shader_controls is not None else None}
                for part in replacement["parts"]]}


def set_shader_controls(authoring, snapshot, args, *, entry, dependencies, stop_event):
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids, commit_replacement
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    from cdmw.services.mesh_rust_replacement_materials import stage_replacement_materials

    ui = shader_controls_ui_state(authoring, replacement_ui_state(authoring))
    if not ui["available"]:
        raise ValueError(ui["reason"])
    keys, reset = args.get("part_ids"), args.get("reset", False)
    if (not isinstance(keys, (list, tuple)) or not keys or any(not isinstance(key, str) for key in keys)
            or len(set(keys)) != len(keys) or not set(keys) <= {part["id"] for part in ui["parts"]}):
        raise ValueError("Select at least one material part for shader controls.")
    if type(reset) is not bool:
        raise ValueError("Invalid shader-control reset request.")
    value = None if reset else ShaderControls.from_dict(args.get("shader_controls"))
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    parts = tuple(replace(part, shader_controls=value) if part.part_id in keys else part for part in state.parts)
    if parts == state.parts:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    state = replace(state, parts=parts, revision=state.revision + 1)
    original = parse_mesh(snapshot.original_data, state.target_path)
    prepared = build_shader_control_files(state, original, state.companion_files, stop_event=stop_event)
    if value is not None:
        state = _capture_control_textures(state, original, prepared, args.get("_archive_dependencies"), stop_event)
    mesh = mesh_with_part_ids(snapshot, state)
    stage_replacement_materials(authoring, mesh, state, stop_event)
    return commit_replacement(authoring.shadow_service, snapshot, mesh, state,
                              label="Restore shader controls" if reset else "Edit shader controls", stop_event=stop_event)


def _capture_control_textures(state, original, prepared, context, stop_event):
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.domain.mesh.replacement import ReplacementFile
    from cdmw.services.mesh_replacement_import import archive_location
    from cdmw.core.material_shader_controls import control_material_sources
    from cdmw.services.shader_controls_preview import EFFECT_NORMAL_PARAMETER
    settings = dict(shader_settings(state, original))
    required = set()
    for file in prepared:
        if not file.path.casefold().endswith((".pac_xml", ".pami")):
            continue
        for name, (_, _, textures) in control_material_sources(_sidecar_text(file.data), static=file.path.casefold().endswith(".pami")).items():
            controls = settings.get(name)
            if controls is not None:
                required.add(textures.get(family_for(controls.shader).mask, ""))
                if controls.shader == "SkinnedMeshAnisotropy":
                    required.add(textures.get(EFFECT_NORMAL_PARAMETER, ""))
    captured = list(state.dependencies)
    existing = {file.path.casefold() for file in (*captured, *state.companion_files)}
    total = sum(len(file.data) for file in captured)
    for path in sorted(required - {""}):
        if path.casefold() in existing:
            continue
        raise_if_cancelled(stop_event)
        matches = tuple(context.entries_by_normalized_path.get(path.casefold(), ())) if context is not None else ()
        if not matches:
            raise ValueError(f"The shader mask is unavailable: {path}. Reopen this mesh from Browse Archives.")
        data, _, _ = read_archive_entry_data(matches[0], stop_event=stop_event)
        total += len(data)
        if total > 512 * 1024 * 1024:
            raise ValueError("Shader dependencies exceed the 512 MiB snapshot limit.")
        captured.append(ReplacementFile(path, bytes(data), archive_location(matches[0])))
        existing.add(path.casefold())
    return replace(state, dependencies=tuple(captured))
