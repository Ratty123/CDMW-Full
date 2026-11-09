"""Collision volume edits through the Mesh Editor's replacement transaction.

Two kinds of source can be edited:

* the PAC's own volume set (``"model"``), written into the built PAC;
* a body or head PABV chosen from the game archives as a cloth collision input,
  shipped by Build Mod as an edited copy of that archive file.

A PABV is shared by every model on that body, so its edits affect them all; the
UI says so. Edits are captured against the exact source bytes and replayed by
the shared writers in ``cdmw.modding.collision_volume_edit``.
"""

from __future__ import annotations

from dataclasses import replace

from cdmw.domain.mesh.collision_volumes import (
    MODEL_SOURCE, CollisionVolumeChange, CollisionVolumeCopy, CollisionVolumeEdit,
)
from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.modding.collision_volume_edit import (
    apply_pabv_volume_edit, apply_pac_volume_edit, pabv_volume_set, pac_volume_set, volume_rows,
)

COLLISION_ARGUMENTS = frozenset({"source", "changes", "copies", "reset", "_archive_entry", "_archive_dependencies"})


def _bone_names(session) -> dict[int, str]:
    names = {}
    for bone in getattr(getattr(session, "skeleton", None), "bones", ()) or ():
        names.setdefault(int(bone.name_hash), str(bone.name))
    return names


def _edits(session) -> dict[str, CollisionVolumeEdit]:
    state = session.replacement_state
    return {edit.source: edit for edit in (state.collision_edits if state else ())}


def collision_sources(authoring, session) -> list[tuple[str, str, bytes | None]]:
    """(source, role, PABV bytes or None for the model) for every editable source."""
    rows = []
    if session.mesh_format == "pac" and session.hair_state is None and session.original_data:
        rows.append((MODEL_SOURCE, "model", None))
    for role in ("body", "head"):
        source = getattr(authoring, "cloth_collision_sources", {}).get(role)
        if source is not None and source[0]:
            rows.append((source[0], role, source[1]))
    return rows


def collision_volume_ui_state(authoring, replacement) -> dict[str, object]:
    """Cached per source bytes, loaded inputs, edits and availability."""
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    key = (id(session.original_data), session.mesh_format, session.hair_state is None, replacement["reason"],
           tuple(sorted(_edits(session).items())),
           tuple(sorted((role, value[0], id(value[1])) for role, value in authoring.cloth_collision_sources.items())),
           tuple(sorted((bone.name_hash, bone.name) for bone in getattr(session.skeleton, "bones", ()) or ())))
    cached = authoring.collision_volume_cache
    if cached is not None and cached[0] == key:
        return cached[1]
    result = _collision_volume_ui_state(authoring, session, replacement)
    authoring.collision_volume_cache = (key, result)
    return result


def _collision_volume_ui_state(authoring, session, replacement) -> dict[str, object]:
    edits = _edits(session)
    names = _bone_names(session)
    reason = replacement["reason"]
    sources = []
    for source, role, data in collision_sources(authoring, session):
        row = {"source": source, "role": role, "shared": source != MODEL_SOURCE,
               "edit": edits[source].to_dict() if source in edits else None}
        try:
            volume_set = pac_volume_set(session.original_data) if data is None else pabv_volume_set(data, source)
            row.update(available=not reason, reason=reason, sha256=volume_set.sha256,
                       rows=volume_rows(volume_set, bone_names=names))
            if source in edits:
                edited = (pac_volume_set(apply_pac_volume_edit(session.original_data, edits[source])) if data is None
                          else pabv_volume_set(apply_pabv_volume_edit(data, source, edits[source]), source))
                row["edited_rows"] = volume_rows(edited, bone_names=names)
        except ValueError as exc:
            row.update(available=False, reason=str(exc), rows=[])
        sources.append(row)
    # An edit whose PABV is no longer loaded as an input still ships; show it so it can be restored.
    loaded = {row["source"] for row in sources}
    for source, edit in edits.items():
        if source not in loaded:
            sources.append({"source": source, "role": "saved", "shared": True, "edit": edit.to_dict(),
                            "available": False, "rows": [],
                            "reason": "Load this PABV as a body or head collision input to edit it again."})
    return {"available": not reason and bool(sources), "reason": reason, "sources": sources,
            "active": bool(edits)}


def _parse_rows(values, factory, name):
    if not isinstance(values, (list, tuple)) or len(values) > 256:
        raise ValueError(f"Invalid collision volume {name}.")
    return tuple(factory(value) for value in values)


def set_collision_volume_edit(authoring, snapshot, args, *, entry, dependencies, stop_event):
    from cdmw.services.mesh_replacement_import import commit_replacement, initial_replacement_state, mesh_with_part_ids
    from cdmw.services.mesh_rust_replacement import replacement_ui_state

    if set(args) - COLLISION_ARGUMENTS or not isinstance(args.get("source"), str):
        raise ValueError("Choose a collision volume set to edit.")
    reset = args.get("reset", False)
    if type(reset) is not bool or (reset and ({"changes", "copies"} & set(args))):
        raise ValueError("Invalid collision volume restore request.")
    ui = collision_volume_ui_state(authoring, replacement_ui_state(authoring))
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    source = args["source"]
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    edits = {edit.source: edit for edit in state.collision_edits}
    dependency_files = list(state.dependencies)
    if reset:
        if source not in edits:
            return authoring.shadow_service.session_view(authoring.shadow_session_id)
        edits.pop(source)
        if source != MODEL_SOURCE and not any(edit.source == source for edit in edits.values()):
            dependency_files = [file for file in dependency_files if file.path.casefold() != source.casefold()
                                or file.archive_location is not None]
    else:
        if ui["reason"]:
            raise ValueError(ui["reason"])
        row = next((row for row in ui["sources"] if row["source"] == source), None)
        if row is None or not row.get("available"):
            raise ValueError(row["reason"] if row else "Load that collision volume set before editing it.")
        changes = _parse_rows(args.get("changes", []), CollisionVolumeChange.from_dict, "edits")
        copies = _parse_rows(args.get("copies", []), CollisionVolumeCopy.from_dict, "copies")
        edit = CollisionVolumeEdit(source, row["sha256"], tuple(sorted(changes, key=lambda c: c.ordinal)), copies)
        authoring._raise_if_cancelled(stop_event)
        if source == MODEL_SOURCE:
            apply_pac_volume_edit(session.original_data, edit)
        else:
            data = next(data for name, _, data in collision_sources(authoring, session) if name == source)
            apply_pabv_volume_edit(data, source, edit)
            existing = [file for file in dependency_files if file.path.casefold() == source.casefold()]
            if existing and any(file.data != data for file in existing):
                raise ValueError("Another file with this PABV's path is already part of this edit.")
            if not existing:
                dependency_files.append(ReplacementFile(source, data))
        edits[source] = edit
    ordered = tuple(edits[key] for key in sorted(edits, key=lambda key: (key != MODEL_SOURCE, key.casefold())))
    if ordered == state.collision_edits and tuple(dependency_files) == state.dependencies:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    state = replace(state, collision_edits=ordered, dependencies=tuple(dependency_files), revision=state.revision + 1)
    return commit_replacement(authoring.shadow_service, snapshot, mesh_with_part_ids(snapshot, state), state,
                              label="Restore collision volumes" if reset else "Edit collision volumes",
                              stop_event=stop_event)


def build_collision_volume_files(state, companion_files):
    """Edited PABV copies for Build Mod, next to the other companions."""
    files = list(companion_files)
    taken = {file.path.casefold() for file in files}
    for edit in state.collision_edits:
        if edit.source == MODEL_SOURCE:
            continue
        source = [file for file in state.dependencies if file.path.casefold() == edit.source.casefold()]
        if len(source) != 1:
            raise ValueError(f"The collision volume source {edit.source} is missing from this edit.")
        if edit.source.casefold() in taken:
            raise ValueError(f"Duplicate replacement companion: {edit.source}")
        files.append(ReplacementFile(edit.source, apply_pabv_volume_edit(source[0].data, edit.source, edit),
                                     source[0].archive_location))
        taken.add(edit.source.casefold())
    return tuple(files)


def preview_volume_inputs(authoring, session, *, inputs=None, sources=None):
    """Model data and body/head inputs with the current edits applied, for the cloth preview.

    Returns (model data, {role: PabvVolumes}, reason). An edit that no longer
    applies is reported and its source is used unedited, never half-applied.
    """
    from cdmw.modding.pabv_parser import decode_pabv

    data = session.original_data
    inputs = authoring.cloth_collision_inputs if inputs is None else inputs
    inputs = {role: value[1] for role, value in inputs.items() if role in ("body", "head")}
    sources = authoring.cloth_collision_sources if sources is None else sources
    if authoring.replacement_comparison == "original":
        return data, inputs, ""
    edits, reasons = _edits(session), []
    if MODEL_SOURCE in edits:
        try:
            data = apply_pac_volume_edit(data, edits[MODEL_SOURCE])
        except ValueError as exc:
            reasons.append(str(exc))
    for role in ("body", "head"):
        source = sources.get(role)
        if source is None or not source[0] or source[0] not in edits or role not in inputs:
            continue
        try:
            inputs[role] = decode_pabv(apply_pabv_volume_edit(source[1], source[0], edits[source[0]]))
        except ValueError as exc:
            reasons.append(str(exc))
    return data, inputs, " ".join(reasons)


def preview_volume_key(authoring, session):
    edits = _edits(session)
    sources = getattr(authoring, "cloth_collision_sources", {})
    return (authoring.replacement_comparison, tuple(sorted(edits.items())),
            tuple(sorted((role, value[0]) for role, value in sources.items())),
            tuple(sorted((role, value[0]) for role, value in authoring.cloth_collision_inputs.items())))
