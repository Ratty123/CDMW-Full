"""The Mesh Editor's tools: what is open, its geometry and selection, and what its buttons do.

Reading comes from the session the editor's helper edits (the same
``shadow_service`` the app itself reads): parts, counts, the selection of
vertices, edges and faces, and the history. Those reads wait for the
session's lock, so they run on a worker, never on the UI thread.

Acting goes the way the editor's own controls go:

* the editor's commands (tools, modes, topology, transforms, Undo, Redo,
  Finish) are sent to the helper by their id, as CDMW's palette sends them;
* whole-part selection, the part highlight, Import Replacement and Export Mesh
  File are the messages the Parts list, the Textures panel and the panel
  buttons send;
* Build Mod presses the document's own button with its options dialog filled
  from the call.

The helper draws its own panels, so vertices, edges and faces are selected
with its commands and pointer, not by index, until it takes a message for it
(``coverage.json``: ``mesh.select_components``).
"""

from __future__ import annotations

import time
from pathlib import Path

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ
from cdmw.mcp.tools import ON_CALL, ON_UI, ON_WORKER, Tool, object_schema

NO_EDITOR = "Open a mesh in the Mesh Editor first (mesh_open, or Browse Archives > Open in Mesh Editor)."
NOT_READY = "The Mesh Editor is still preparing this mesh; mesh_state says when it is ready."
BUSY = "The Mesh Editor is working on the last request; try again in a moment."
OPEN_TIMEOUT_S = 60.0
GEOMETRY = ("summary", "vertices", "triangles", "uvs", "normals", "selection")
_PART = {"type": "integer", "minimum": 0, "description": "A part's number, as mesh_state lists it."}


def _answers_schema() -> dict[str, object]:
    from cdmw.mcp.ui_actions import ANSWERS_SCHEMA

    return dict(ANSWERS_SCHEMA)


# ----- the shown document (UI thread) ----------------------------------------------------
def _view(context):
    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    shell = getattr(getattr(context, "window", None), "shell", None)
    return created_tool_widget(getattr(shell, "mesh_editor_tab", None))


def shown_document(context):
    """The Mesh Editor document that is shown, or None (never builds the tab)."""

    view = _view(context)
    return getattr(view, "active", None) or view


def ready_document(context, *, commands: bool = False):
    tab = shown_document(context)
    if tab is None or getattr(tab, "standalone_rust_authoring_session", None) is None:
        raise ToolError(UNAVAILABLE, NO_EDITOR)
    if not getattr(tab, "standalone_rust_ready", False):
        raise ToolError(UNAVAILABLE, NOT_READY)
    if commands and not getattr(tab, "standalone_rust_host_commands_supported", False):
        raise ToolError(UNAVAILABLE, "This Mesh Editor helper does not take commands from CDMW; it is older "
                                     "than this app.")
    return tab


def _busy(tab) -> bool:
    return bool(getattr(tab, "standalone_rust_protocol_thread", None) is not None
                or getattr(tab, "standalone_rust_protocol_queue", None))


def _status(tab) -> str:
    label = getattr(tab, "standalone_status_label", None)
    try:
        return str(label.text()) if label is not None else ""
    except RuntimeError:
        return ""


def _unavailable_reason(tab) -> str:
    """The reason the page gives when the editor cannot start, as its status line shows it."""

    reason = str(getattr(tab, "standalone_rust_incompatible_reason", "") or "") if tab is not None else ""
    if reason:
        return f"Mesh Editor unavailable: {reason}"
    status = _status(tab) if tab is not None else ""
    return status if "unavailable" in status.casefold() else ""


DRAFT_ANSWERS = {"resume": "draft_resume_button", "fresh": "draft_start_fresh_button",
                 "choose": "draft_choose_button", "cancel": "draft_choice_cancel_button"}


def _draft_question(tab) -> dict[str, object] | None:
    """"Continue where you left off?" when the page shows it: the open waits for an answer."""

    showing = getattr(tab, "_draft_choice_showing", None) if tab is not None else None
    if not (callable(showing) and showing()):
        return None
    label = getattr(tab, "draft_choice_label", None)
    return {"question": "Continue where you left off?", "text": str(label.text()) if label is not None else "",
            "answers": sorted(DRAFT_ANSWERS), "tool": "mesh_draft_choice"}


def _documents(context) -> tuple[list[dict[str, object]], object, object]:
    from cdmw.ui.mesh_editor.documents import document_label

    view = _view(context)
    tab = getattr(view, "active", None) or view
    rows = []
    for index, document in enumerate(tuple(getattr(view, "documents", ()) or ())):
        rows.append({"index": index, "label": document_label(document), "shown": document is tab,
                     "ready": bool(getattr(document, "standalone_rust_ready", False)),
                     "parked": bool(getattr(document, "standalone_rust_parked", False)),
                     # The edit is drawn in Browse Archives' view, not in a tab of its own.
                     "in_browse": getattr(getattr(document, "live_edit", None), "viewport_binding", None) is not None})
    return rows, view, tab


# ----- mesh.state -----------------------------------------------------------------------
def _bounds(vertices) -> dict[str, list[float]] | None:
    if not vertices:
        return None
    xs, ys, zs = zip(*((v[0], v[1], v[2]) for v in vertices))
    return {"min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]}


def _owners(service, session_id) -> dict[int, tuple[str, int]]:
    """A set's parts belong to its files: part number -> (file, the part's number in that file)."""

    owners: dict[int, tuple[str, int]] = {}
    try:
        context = service._session(session_id).archive_refit_context
    except Exception:
        return owners
    for asset in getattr(context, "assets", ()) or ():
        path = str(getattr(getattr(asset, "entry", None), "path", "") or "")
        for local, index in enumerate(getattr(asset, "part_indices", ()) or ()):
            owners[int(index)] = (path, local)
    return owners


def _selection(selection) -> dict[str, object]:
    by_part: dict[int, dict[str, int]] = {}
    for field, key in (("vertices_by_submesh", "vertices"), ("edges_by_submesh", "edges"),
                       ("faces_by_submesh", "faces")):
        for part, items in getattr(selection, field, ()) or ():
            if items:
                by_part.setdefault(int(part), {"part": int(part), "vertices": 0, "edges": 0, "faces": 0})[key] = len(
                    items)
    rows = [by_part[part] for part in sorted(by_part)]
    return {"parts": sorted(int(i) for i in getattr(selection, "source_indices", ()) or ()),
            "vertices": sum(row["vertices"] for row in rows), "edges": sum(row["edges"] for row in rows),
            "faces": sum(row["faces"] for row in rows), "by_part": rows}


def _hair(service, session_id) -> dict[str, object] | None:
    """The hairstyle being made in this session (Hair Tools), or None."""

    try:
        state = service._session(session_id).hair_state
    except Exception:
        return None
    if state is None:
        return None
    payload = state.payload
    template = payload.get("template") or {}
    return {"style_name": str(payload.get("style_name") or ""), "preset": str(payload.get("startup_preset") or ""),
            "template": str(template.get("path") or ""), "character": str(template.get("character") or ""),
            "guides": len(payload.get("guides") or ()), "groups": len(payload.get("groups") or ()),
            "locks": len(payload.get("locks") or ()), "prepared_parts": len(payload.get("prepared_parts") or ()),
            "revision": int(state.revision)}


def _session_of(call):
    """(the UI's facts, the session) for the shown document, read on the UI thread."""

    context = call.context

    def read():
        rows, _view_widget, tab = _documents(context)
        facts: dict[str, object] = {"documents": rows, "open": False}
        session = getattr(tab, "standalone_rust_authoring_session", None) if tab is not None else None
        if tab is None or session is None or getattr(session, "closed", False):
            # Why there is no edit yet: the page's own lines, such as "Mesh Editor unavailable: ...".
            reason = _unavailable_reason(tab)
            if reason:
                facts["unavailable"] = reason
            asking = _draft_question(tab)
            if asking:
                facts["asks"] = asking
            return facts, None
        registry = context.command_registry()
        busy_output = getattr(tab, "_mesh_direct_output_busy", None)
        facts.update({
            "open": True,
            "ready": bool(getattr(tab, "standalone_rust_ready", False)),
            "status": _status(tab),
            "busy": _busy(tab),
            "building": bool(busy_output()) if callable(busy_output) else False,
            "session_folder": str(getattr(tab, "standalone_rust_session_root", "") or ""),
            "commands": len(registry.commands("mesh_editor")) if registry is not None else 0,
            # Whether this helper takes editing by numbers (mesh_select, mesh_topology ...).
            "edits_by_number": bool(getattr(tab, "standalone_rust_host_edit_commands_supported", False)),
            "helper_capabilities": list(getattr(tab, "standalone_rust_capabilities", ()) or ()),
        })
        # The session's own reason: a set's Load Archive changes it after the open.
        reason = str(getattr(session, "texture_unavailable_reason", "") or "") or str(
            getattr(tab, "standalone_rust_texture_unavailable_reason", "") or "")
        if reason:
            facts["textures_unavailable"] = reason
        return facts, session

    return context.ui_call(read)


def _state(call) -> dict[str, object]:
    facts, session = _session_of(call)
    if session is None:
        return facts
    service, session_id = session.shadow_service, session.shadow_session_id
    try:
        view = service.session_view(session_id)
        mesh = service.working_mesh(session_id)
    except (KeyError, RuntimeError) as exc:
        facts["mesh_error"] = str(exc) or "The session is closing."
        return facts
    owners = _owners(service, session_id)
    parts = []
    for index, part in enumerate(getattr(mesh, "submeshes", ()) or ()):
        row: dict[str, object] = {"index": index, "name": str(getattr(part, "name", "") or ""),
                                  "material": str(getattr(part, "material", "") or ""),
                                  "vertices": len(part.vertices), "triangles": len(part.faces)}
        if index in owners:
            row["file"], row["index_in_file"] = owners[index]
        parts.append(row)
    facts.update({
        "format": str(getattr(view, "mesh_format", "") or getattr(mesh, "format", "") or ""),
        "file": str(getattr(mesh, "path", "") or ""),
        "parts": parts,
        "vertices": sum(row["vertices"] for row in parts),
        "triangles": sum(row["triangles"] for row in parts),
        "selection": _selection(view.selection),
        "revision": int(view.revision),
        "history": {
            "undo": int(view.undo_count), "redo": int(view.redo_count),
            "can_undo": bool(view.undo_count or view.journal_undo_available),
            "can_redo": bool(view.redo_count or view.journal_redo_available),
            # Nothing was done since the last Finish or Build.
            "clean": bool(view.history_clean),
            "steps": [str(getattr(entry, "label", "") or getattr(entry, "action", "") or "")
                      for entry in view.history_entries][-50:],
            "cursor": int(view.history_cursor),
        },
        "output": {"policy": view.output_policy, "destination": view.output_destination,
                   "reason": view.output_policy_reason},
    })
    shared = _shared_history(session)
    if shared is not None:
        # Texture edits share the document's one history (Undo takes whichever came last),
        # as the editor's own History list and Undo show it.
        facts["history"].update(shared, mesh_undo=int(view.undo_count), mesh_redo=int(view.redo_count))
    textures = _textures(session, mesh, view, owners)
    if textures is not None:
        facts["textures"] = textures
        if textures["available"] and "textures_unavailable" in facts:
            # Some parts are drawn textured: the reason is about the others.
            textures["warning"] = facts.pop("textures_unavailable")
    hair = _hair(service, session_id)
    if hair is not None:
        facts["hair"] = hair
    return facts


def _shared_history(session) -> dict[str, object] | None:
    """The document's merged mesh and texture history, or None when it has no texture edits."""

    history = getattr(session, "shared_history", None)
    current = getattr(history, "current_history_payload", None)
    if not callable(current):
        return None
    payload = current()
    entries = list(payload.get("history_entries") or ())
    if not any("texture" in entry for entry in entries):
        return None
    cursor, undo, redo = (int(payload.get(key) or 0) for key in ("history_cursor", "undo_count", "redo_count"))
    steps = [str(entry.get("label") or entry.get("action") or "") + (
        f" ({entry['texture']})" if entry.get("texture") else "") for entry in entries]
    return {"undo": undo, "redo": redo, "can_undo": undo > 0, "can_redo": redo > 0, "steps": steps[-50:],
            "cursor": cursor}


def _textures(session, mesh, view, owners) -> dict[str, object] | None:
    """Which parts the editor draws textured, from the materials it was given: DDS
    payloads and Preview Core material layers, the two routes its view uses."""

    coverage_of = getattr(session, "live_texture_coverage", None)
    if not callable(coverage_of):
        return None
    try:
        coverage = coverage_of(tuple(getattr(mesh, "submeshes", ()) or ()), int(view.lod_index))
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    untextured = []
    for row in coverage["untextured_parts"]:
        row = dict(row)
        if row["index"] in owners:
            row["file"] = owners[row["index"]][0]
        untextured.append(row)
    return {"available": bool(coverage["textured_part_count"]), "parts": coverage["part_count"],
            "textured_parts": coverage["textured_part_count"],
            "from_dds": coverage["dds_part_count"], "from_material_layers": coverage["material_graph_part_count"],
            "untextured_parts": untextured}


# ----- mesh.geometry --------------------------------------------------------------------
def _geometry(call) -> dict[str, object]:
    facts, session = _session_of(call)
    if session is None:
        raise ToolError(UNAVAILABLE, NO_EDITOR)
    service, session_id = session.shadow_service, session.shadow_session_id
    try:
        view = service.session_view(session_id)
        mesh = service.working_mesh(session_id)
    except (KeyError, RuntimeError) as exc:
        raise ToolError(UNAVAILABLE, str(exc) or NOT_READY) from None
    parts = list(getattr(mesh, "submeshes", ()) or ())
    index = int(call.arguments["part"])
    if not 0 <= index < len(parts):
        raise ToolError(NOT_FOUND, f"The mesh has parts 0 to {len(parts) - 1}.")
    part = parts[index]
    what = str(call.arguments.get("what") or "summary")
    head = {"part": index, "name": str(part.name or ""), "what": what, "revision": int(view.revision)}
    if what == "summary":
        weights = [len(row) for row in part.bone_weights]
        return {**head, "material": str(part.material or ""), "texture": str(part.texture or ""),
                "vertices": len(part.vertices), "triangles": len(part.faces), "bounds": _bounds(part.vertices),
                "uv_sets": 1 + len(part.uv_sets) if part.uvs else len(part.uv_sets),
                "has_normals": bool(part.normals), "has_tangents": bool(part.tangents),
                "has_vertex_colours": bool(part.vertex_colors),
                "skinned": bool(part.bone_indices),
                "bones": len({bone for row in part.bone_indices for bone in row}),
                "most_weights_per_vertex": max(weights) if weights else 0,
                "morphs": sorted(part.morph_targets)}
    if what == "selection":
        def of(field):
            return next((list(items) for owner, items in getattr(view.selection, field, ()) or ()
                         if int(owner) == index), [])

        return {**head, "whole_part": index in set(view.selection.source_indices),
                "vertices": of("vertices_by_submesh"), "faces": of("faces_by_submesh"),
                "edges": [list(edge) for edge in of("edges_by_submesh")]}
    source = {"vertices": part.vertices, "triangles": part.faces, "uvs": part.uvs, "normals": part.normals}[what]
    # Row n is vertex n (or triangle n: its three vertex numbers).
    return {**head, "rows": [list(row) for row in source]}


# ----- acting ----------------------------------------------------------------------------
def _act(call, function, answers=None) -> dict[str, object]:
    from cdmw.mcp.ui_actions import run_action

    outcome = run_action(call.context, function, answers)
    result = outcome.get("result")
    rest = {key: value for key, value in outcome.items() if key != "result" and value}
    return {**(result if isinstance(result, dict) else {"done": True}), **rest}


def _refuse(error: Exception) -> ToolError:
    return ToolError(INVALID_ARGUMENTS if isinstance(error, ValueError) else UNAVAILABLE, str(error))


def _scope_set(call, archive, paths: list[str], label: str) -> None:
    """Scope Browse Archives to a worn set, as Item Finder's Open all parts does (worker thread)."""

    import threading

    from cdmw.domain.archives.catalogue import ArchiveLookupKind
    from cdmw.ui.archive_browser.remote_entry_lookup import lookup_requests, start_live_catalogue_lookup

    wanted = [path.casefold() for path in paths]
    done = threading.Event()
    box: dict[str, object] = {}

    def found(outcome) -> None:
        by_path: dict[str, int] = {}
        for dto in outcome.entries:
            key = dto.path.replace("\\", "/").strip("/").casefold()
            if key in wanted and (key not in by_path or dto.is_active_override):
                by_path[key] = dto.entry_id
        missing = [path for path, key in zip(paths, wanted) if key not in by_path]
        if missing:
            box["error"] = ToolError(NOT_FOUND, f"The archives have no file {missing[0]}.")
        # The files named are the scene, as Add to scene collects them: none is left out.
        elif not archive.archive_remote_bridge.apply_entry_id_scope(
                [by_path[key] for key in wanted], label=label, worn_set=True,
                kept_entry_ids=[by_path[key] for key in wanted]):
            box["error"] = ToolError(UNAVAILABLE, "Browse Archives could not show this set.")
        done.set()

    def failed(message) -> None:
        box["error"] = ToolError(UNAVAILABLE, str(message))
        done.set()

    def start() -> None:
        archive._note_archive_ui_activity()
        bridge = archive.archive_remote_bridge
        session = getattr(bridge, "current_session", None)
        if session is None:
            failed("Load the archives in Browse Archives first.")
            return
        start_live_catalogue_lookup(archive, "_mcp_set_lookup",
                                    lookup_requests(session.session_id, ArchiveLookupKind.EXACT_PATHS, paths),
                                    on_done=found, on_error=failed)

    call.context.ui_call(start)
    deadline = time.monotonic() + OPEN_TIMEOUT_S
    while not done.wait(0.05):
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, "Browse Archives did not find the set's files in time.")
    if "error" in box:
        raise box["error"]


def _select_listed_path(archive, path: str) -> bool:
    """Make the listed row of ``path`` the current one, as a click on it does. False when it is not listed."""

    from PySide6.QtCore import QItemSelectionModel

    tree = getattr(archive, "archive_tree", None)
    selection = tree.selectionModel() if tree is not None else None
    model = selection.model() if selection is not None else None
    entry_for_index = getattr(model, "entry_for_index", None)
    if not callable(entry_for_index):
        return False
    wanted = path.replace("\\", "/").strip("/").casefold()
    for row in range(model.rowCount()):
        index = model.index(row, 0)
        entry = entry_for_index(index)
        if str(getattr(entry, "path", "") or "").replace("\\", "/").strip("/").casefold() != wanted:
            continue
        flags = QItemSelectionModel.SelectionFlag
        tree.setCurrentIndex(index)
        selection.select(index, flags.ClearAndSelect | flags.Rows)
        return True
    return False


def _open_set(call, archive, window, paths: list[str]) -> dict[str, object]:
    from cdmw.ui.mesh_editor.item_set_preparation import prepare_item_set_for_editor

    context = call.context
    _scope_set(call, archive, paths, str(call.arguments.get("label") or "Item set"))

    def current() -> str:
        entry = archive._current_archive_mesh_entry()
        return str(getattr(entry, "path", "") or "").replace("\\", "/").strip("/")

    first = paths[0]

    # The set scope selects its first file itself once its rows are listed. Revealing that file
    # here would replace the set with a one-file scope, and the set could never be opened.
    def ready() -> bool:
        contains = getattr(archive.archive_remote_bridge, "item_set_contains", None)
        if not callable(contains):
            return False
        if current().casefold() != first.casefold():
            _select_listed_path(archive, first)
        return current().casefold() == first.casefold() and bool(contains(archive._current_archive_entry()))

    deadline = time.monotonic() + OPEN_TIMEOUT_S
    while not context.ui_call(ready):
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(NOT_FOUND, f"Browse Archives did not show {first} as part of the set.")
        time.sleep(0.05)

    def open_it() -> dict[str, object]:
        entry = archive._current_archive_entry()
        contains = getattr(archive.archive_remote_bridge, "item_set_contains", None)
        if entry is None or not (callable(contains) and contains(entry)):
            raise ToolError(UNAVAILABLE, "Offered for a model that is part of a worn set opened from Item Finder.")
        take = getattr(window.shell, "_take_pending_hidden_parts_for_open", None)
        if callable(take):
            take()
        if not prepare_item_set_for_editor(window.shell, entry, edit_set=True):
            raise ToolError(UNAVAILABLE, "The Mesh Editor did not open this set; app_state shows why.")
        return {"opening": True, "set": paths,
                "message": "The Mesh Editor is opening this set; mesh_state says when it is ready."}

    return _act(call, open_it)


def _open_ticked(call, archive) -> dict[str, object]:
    def press() -> dict[str, object]:
        panel = getattr(archive, "archive_item_set_components", None)
        button = getattr(panel, "edit_set_button", None)
        if button is None or not button.isVisible() or not button.isEnabled():
            reason = button.toolTip() if button is not None else ""
            raise ToolError(UNAVAILABLE, reason or "The Scene panel has no ticked parts of a set to open.")
        button.click()
        return {"opening": True, "message": "The Mesh Editor is opening the ticked parts; mesh_state says when "
                                            "it is ready."}

    return _act(call, press)


def _open(call) -> dict[str, object]:
    from cdmw.ui.ai_connections.context import NO_ARCHIVES

    context = call.context
    window = getattr(context, "window", None)
    archive = getattr(window, "archive", None)
    if archive is None:
        raise ToolError(UNAVAILABLE, NO_ARCHIVES)
    chosen = [name for name in ("path", "set", "ticked_parts") if call.arguments.get(name)]
    if len(chosen) > 1:
        raise ToolError(INVALID_ARGUMENTS, "Give path, set or ticked_parts, not more than one.")
    if call.arguments.get("set"):
        paths = [str(path).replace("\\", "/").strip().strip("/") for path in call.arguments["set"]]
        if len({path.casefold() for path in paths}) != len(paths):
            raise ToolError(INVALID_ARGUMENTS, "The set names a file twice.")
        return _open_set(call, archive, window, paths)
    if call.arguments.get("ticked_parts"):
        return _open_ticked(call, archive)
    wanted = str(call.arguments.get("path") or "").replace("\\", "/").strip().strip("/")

    def current() -> str:
        entry = archive._current_archive_mesh_entry()
        return str(getattr(entry, "path", "") or "").replace("\\", "/").strip("/")

    # A file that is already the current row is opened as it stands. Revealing it again re-lists
    # Browse around it, and Open would be pressed in the moment its row is gone: nothing opened.
    if wanted and context.ui_call(current).casefold() != wanted.casefold():
        def reveal() -> bool:
            archive._note_archive_ui_activity()
            return bool(archive._reveal_archive_path_in_live_catalogue(wanted))

        if not context.ui_call(reveal):
            raise ToolError(UNAVAILABLE, NO_ARCHIVES)
        deadline = time.monotonic() + OPEN_TIMEOUT_S
        while context.ui_call(current).casefold() != wanted.casefold():
            call.check_cancelled()
            if time.monotonic() > deadline:
                raise ToolError(NOT_FOUND, f"Browse Archives did not show {wanted} as a mesh it can open. "
                                           "search_archive finds the path of a .pac, .pam or .pamlod file.")
            time.sleep(0.05)
    elif not wanted and not context.ui_call(current):
        raise ToolError(UNAVAILABLE, "Select a mesh in Browse Archives first, or give its path.")
    path = context.ui_call(current)

    def press() -> object:
        # Checked where the button is pressed: the row can go between the wait above and this call.
        if not path or current().casefold() != path.casefold():
            raise ToolError(UNAVAILABLE, "Browse Archives is listing its files again; call mesh_open once more.")
        return window.shell._open_current_archive_mesh_editor()

    outcome = _act(call, press)
    return {**outcome, "opening": True, "path": path,
            "message": "The Mesh Editor is opening this mesh; mesh_state says when it is ready."}


def _draft_choice(call) -> dict[str, object]:
    context = call.context
    answer = str(call.arguments["answer"])

    def press() -> dict[str, object]:
        tab = shown_document(context)
        if _draft_question(tab) is None:
            raise ToolError(UNAVAILABLE, "The Mesh Editor is not asking whether to continue a draft.")
        getattr(tab, DRAFT_ANSWERS[answer]).click()
        message = {"cancel": "",
                   "choose": "Drafts & Mods opens with this file's drafts: read them with saved_list and open "
                             "one with saved_change (action continue)."}.get(answer,
                                                                           "mesh_state says when the editor is ready.")
        return {"answered": answer, "message": message}

    return _act(call, press)


def _show_document(call) -> dict[str, object]:
    rows, view, _tab = _documents(call.context)
    index = int(call.arguments["index"])
    if view is None or not 0 <= index < len(rows):
        raise ToolError(NOT_FOUND, f"The Mesh Editor has {len(rows)} open documents." if rows else NO_EDITOR)
    view.set_active(index)
    return {"shown": index, "label": rows[index]["label"]}


def _select_parts(call) -> dict[str, object]:
    context = call.context
    indices = sorted({int(index) for index in call.arguments["parts"]})

    def send() -> dict[str, object]:
        tab = ready_document(context)
        message = tab._rust_host_message("select_parts", request_id=0, extra={"indices": indices})
        if not tab._send_rust_message(message):
            raise ToolError(FAILED, "The Mesh Editor did not take the selection.")
        return {"selected_parts": indices}

    return _act(call, send)


def _highlight(call) -> dict[str, object]:
    tab = ready_document(call.context)
    part = call.arguments.get("part")
    highlight = getattr(getattr(tab, "live_edit", None), "highlight_part_in_view", None)
    if not callable(highlight):
        raise ToolError(UNAVAILABLE, "This Mesh Editor cannot light a part up.")
    highlight(int(part) if part is not None else None)
    return {"highlighted": part}


def _helper_command_id(call) -> str:
    from cdmw.ui.mesh_editor.editor_commands import registry_id

    text = str(call.arguments["command"])
    return text if text.startswith("mesh_editor.") else registry_id(text)


def _helper_command(call):
    registry = call.context.command_registry()
    command_id = _helper_command_id(call)
    if registry is None or command_id not in registry:
        ready_document(call.context)  # says why, when no editor is open
        raise ToolError(NOT_FOUND, f"The Mesh Editor has no command {call.arguments['command']}. commands_list "
                                   "with context mesh_editor lists them.")
    return registry.get(command_id)


def _command_effect(call) -> str:
    from cdmw.mcp.control_tools import command_effect

    return command_effect(_helper_command(call))


def _run_helper(call, command_id: str, answers=None, *, direct: str = "") -> dict[str, object]:
    context = call.context

    def run() -> dict[str, object]:
        registry = context.command_registry()
        if registry is None or command_id not in registry:
            tab = ready_document(context)
            # A helper that does not list this command in its keymap still takes it by id.
            if direct and tab._send_rust_command(direct):
                return {"sent": True, "command": command_id}
            raise ToolError(UNAVAILABLE, NOT_READY)
        if registry.run(command_id) is False:
            raise ToolError(FAILED, "The Mesh Editor did not take the command.")
        return {"sent": True, "command": command_id}

    return _act(call, run, answers)


def _command(call) -> dict[str, object]:
    return _run_helper(call, _helper_command_id(call), call.arguments.get("answers"))


def _fixed_command(helper_id: str):
    def handler(call) -> dict[str, object]:
        from cdmw.ui.mesh_editor.editor_commands import registry_id

        return _run_helper(call, registry_id(helper_id), direct=helper_id)
    return handler


def _discard(call) -> dict[str, object]:
    context = call.context

    def close() -> dict[str, object]:
        tab = shown_document(context)
        if tab is None or getattr(tab, "standalone_rust_authoring_session", None) is None:
            raise ToolError(UNAVAILABLE, NO_EDITOR)
        return {"discarded": bool(tab.close_standalone_session())}

    return _act(call, close)


def _build_mod(call) -> dict[str, object]:
    context = call.context
    a = call.arguments
    folder = str(a["output_folder"])

    def build() -> dict[str, object]:
        from cdmw.ui.mesh_editor import tab_direct_output

        tab = shown_document(context)
        # After Finish the helper has closed and its session with it; the document keeps the
        # finished edit and Build Mod builds from it, as the page's button does then.
        if tab is None or (getattr(tab, "standalone_rust_authoring_session", None) is None
                           and getattr(tab, "standalone_controller", None) is None):
            raise ToolError(UNAVAILABLE, NO_EDITOR)
        original = tab_direct_output.MeshModExportDialog
        shown: dict[str, object] = {}

        class _Answered(original):  # type: ignore[misc, valid-type]
            """Build Mod's options dialog, filled from the call and accepted as OK does."""

            def exec(self) -> int:
                self.output_parent.setText(folder)
                if a.get("mod_name"):
                    self.mod_name.setText(str(a["mod_name"]))
                for name in ("version", "author", "description"):
                    if a.get(name) is not None:
                        getattr(self, name).setText(str(a[name]))
                self.create_zip.setChecked(bool(a.get("create_zip", False)))
                self.open_folder.setChecked(False)
                if a.get("manager"):
                    wanted = str(a["manager"]).casefold()
                    index = next((row for row in range(self.manager.count())
                                  if wanted in {str(self.manager.itemData(row)[0]).casefold(),
                                                self.manager.itemText(row).casefold()}), -1)
                    if index < 0:
                        shown["refused"] = "The mod managers are: " + ", ".join(
                            str(self.manager.itemData(row)[0]) for row in range(self.manager.count())) + "."
                        return int(self.DialogCode.Rejected)
                    self.manager.setCurrentIndex(index)
                # The dialog is never shown, so its controls are never "visible": the ones it
                # leaves out for this build are the ones it hid.
                offers_body = not self.include_body.isHidden()
                if a.get("include_body") is not None and offers_body:
                    self.include_body.setChecked(bool(a["include_body"]))
                hair = bool(getattr(self, "_hair_mode", False))
                if not hair:
                    for name in ("hair_stem", "custom_icon_path", "send_to_dmm"):
                        if a.get(name):
                            shown["refused"] = f"'{name}' is for a hairstyle made with Hair Tools; this is a mesh mod."
                            return int(self.DialogCode.Rejected)
                else:
                    if a.get("hair_stem") is not None:
                        if self.hair_stem.isHidden():
                            shown["refused"] = "Replace Existing Hairstyle keeps the replaced hairstyle's ID: leave out 'hair_stem'."
                            return int(self.DialogCode.Rejected)
                        self.hair_stem.setText(str(a["hair_stem"]))
                    if a.get("custom_icon_path"):
                        self.custom_icon_path.setText(str(a["custom_icon_path"]))
                    if a.get("send_to_dmm"):
                        if not self.send_to_dmm.isEnabled() or self.send_to_dmm.isHidden():
                            shown["refused"] = (self.send_to_dmm.toolTip()
                                                or "DMM's mods folder was not found; open DMM once so it exists.")
                            return int(self.DialogCode.Rejected)
                    self.send_to_dmm.setChecked(bool(a.get("send_to_dmm")))
                layers = [str(name) for name in a.get("keep_layers") or ()]
                if layers and hair:
                    shown["refused"] = "A hairstyle mod keeps no layers underneath."
                    return int(self.DialogCode.Rejected)
                self.keep_layers.setChecked(bool(layers))
                names = {str(self.layers.item(row).data(QT_USER_ROLE)): row for row in range(self.layers.count())}
                unknown = sorted(set(layers) - set(names))
                if unknown:
                    shown["refused"] = (f"No layer {', '.join(unknown)}. The layers are: "
                                        + ", ".join(names) + ".")
                    return int(self.DialogCode.Rejected)
                for name, row in names.items():
                    self.layers.item(row).setCheckState(QT_CHECKED if name in layers else QT_UNCHECKED)
                if not self.build_button.isEnabled():
                    # The dialog's own check: Build Mod stays disabled, and its line says why.
                    shown["refused"] = (self.destination.text().strip()
                                        or "Build Mod's options are incomplete: give a mod name and an output folder.")
                    return int(self.DialogCode.Rejected)
                shown.update(mod_name=self.mod_name.text(), output_folder=self.output_parent.text(),
                             manager=str(self.manager.currentData()[0]), kept_layers=list(self.kept_layers()),
                             include_body=bool(offers_body and self.include_body.isChecked()),
                             destination=str(self.output_path()))
                if hair:
                    shown.update(hair_stem=self.target_stem(), send_to_dmm=bool(self.send_to_dmm_enabled()),
                                 custom_icon_path=str(self.custom_icon() or ""))
                return int(self.DialogCode.Accepted)

        from PySide6.QtCore import Qt

        QT_USER_ROLE, QT_CHECKED, QT_UNCHECKED = (Qt.ItemDataRole.UserRole, Qt.CheckState.Checked,
                                                  Qt.CheckState.Unchecked)
        tab_direct_output.MeshModExportDialog = _Answered
        try:
            tab._start_mesh_mod_build_requested()
        finally:
            tab_direct_output.MeshModExportDialog = original
        if shown.get("refused"):
            raise ToolError(INVALID_ARGUMENTS, str(shown["refused"]))
        busy = getattr(tab, "_mesh_direct_output_busy", None)
        return {"started": bool(busy()) if callable(busy) else bool(shown), **shown, "status": _status(tab)}

    outcome = _act(call, build)
    if not outcome.get("started"):
        outcome["message"] = ("Build Mod did not start: 'asked' and 'status' say why. A mesh edit must be "
                              "finished (mesh_finish) and pass validation first.")
    else:
        outcome["message"] = "Build Mod is running; mesh_state shows 'building' until it is done."
    return outcome


def _export(call) -> dict[str, object]:
    context = call.context
    path = Path(str(call.arguments["path"]))
    format_name = path.suffix.lower().lstrip(".")
    if format_name not in ("obj", "glb", "fbx"):
        raise ToolError(INVALID_ARGUMENTS, "Export a .glb, .fbx or .obj file, as the editor's Export menu offers.")

    def send() -> dict[str, object]:
        from cdmw.automation.authoring_commands import _send

        tab = ready_document(context, commands=True)
        if _busy(tab):
            raise ToolError(UNAVAILABLE, BUSY)
        if not _send(tab, "export_mesh", {"path": str(path), "format": format_name}):
            raise ToolError(FAILED, "The Mesh Editor did not take the export.")
        return {"sent": True, "path": str(path), "format": format_name}

    return _act(call, send)


def _replacement(name: str):
    """Import Replacement's steps, by the functions the automated runs use (the panel's own messages)."""

    def handler(call) -> dict[str, object]:
        from cdmw.automation import authoring_commands

        context = call.context
        arguments = {key: value for key, value in call.arguments.items() if value is not None}

        def run() -> dict[str, object]:
            window = getattr(context, "window", None)
            if shown_document(context) is None:
                raise ToolError(UNAVAILABLE, NO_EDITOR)
            try:
                result = dict(getattr(authoring_commands, name)(window, arguments))
            except (ValueError, RuntimeError) as error:
                raise _refuse(error) from None
            if result.get("busy"):
                raise ToolError(UNAVAILABLE, BUSY)
            return result

        if name == "replacement_state":
            return run()
        return _act(call, run)
    return handler


def _settled(handler):
    """A helper command, then what it did: the history before and after and the status line."""

    from cdmw.mcp.mesh_edit_tools import settled

    return settled(handler)


def _replacement_import(call) -> dict[str, object]:
    """Import Replacement, waited for. The chooser's answer is used by this import only: when the
    helper sent nothing (it refused, or was busy), the answer must not wait for the user's next click."""

    from cdmw.ui.mesh_editor import replacement_flow

    try:
        return _settled(_replacement("replacement_import"))(call)
    finally:
        def forget() -> None:
            if replacement_flow.source_path_override == str(Path(str(call.arguments.get("path") or ""))):
                replacement_flow.source_path_override = None

        call.context.ui_call(forget)


def mesh_tools() -> list[Tool]:
    text = {"type": "string", "maxLength": 256}
    return [
        Tool(name="mesh.state", family="mesh", title="Mesh Editor state",
             description="The Mesh Editor now: its open documents (tabs) and, for the shown one, whether it is "
                         "ready, its status line, every part with its name, material, vertex and triangle "
                         "counts and (for a set) the file it belongs to, the selection (whole parts, and how "
                         "many vertices, edges and faces in each part), the history (steps, can undo, can "
                         "redo), where its output goes, which parts are drawn textured (and which are not, by name), "
                         "and, for a hairstyle made with Hair Tools, its style, "
                         "template and how many guides, groups and locks it has.",
             input_schema=object_schema(), effect=READ, route="service:MeshService.session_view+working_mesh",
             handler=_state, runs_on=ON_WORKER, paged="parts"),
        Tool(name="mesh.geometry", family="mesh", title="Mesh geometry",
             description="One part's geometry in the shown document: 'summary' (counts, bounds, UV sets, "
                         "skinning, morphs), 'vertices' (positions; row n is vertex n), 'triangles' (three "
                         "vertex numbers each), 'uvs', 'normals', or 'selection' (the selected vertex, face and "
                         "edge numbers of this part).",
             input_schema=object_schema({"part": _PART, "what": {"type": "string", "enum": list(GEOMETRY),
                                                                  "default": "summary"}}, ["part"]),
             effect=READ, route="service:MeshService.working_mesh", handler=_geometry, runs_on=ON_WORKER,
             paged="rows"),
        Tool(name="mesh.open", family="mesh", title="Open in Mesh Editor",
             description="Opens an archive mesh (.pac, .pam, .pamlod) in the Mesh Editor, as Browse Archives' "
                         "Open in Mesh Editor does: with 'path' it is selected in Browse Archives first, "
                         "without it the selected mesh is opened. Returns at once; mesh_state says when the "
                         "editor is ready, or 'asks' when it waits for an answer such as whether to continue "
                         "a saved draft (mesh_draft_choice). With 'set' (two or more archive paths, such as "
                         "an item's worn parts from search_items, or any .pac files to edit together, as Add to scene "
                         "collects them) Browse is scoped to that set, every file named is kept, and Open set in "
                         "Mesh Editor edits the pieces together; 'label' names the set. With 'ticked_parts' "
                         "the Scene panel's Open ticked parts button opens the parts ticked there.",
             input_schema=object_schema({
                 "path": {"type": "string", "maxLength": 512},
                 "set": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 512},
                         "minItems": 2, "maxItems": 64},
                 "label": {"type": "string", "maxLength": 120},
                 "ticked_parts": {"type": "boolean"}}), effect=EDIT,
             route="ui:shell._open_current_archive_mesh_editor", handler=_open, runs_on=ON_WORKER),
        Tool(name="mesh.draft_choice", family="mesh", title="Continue where you left off?",
             description="Answers the question the Mesh Editor asks when the mesh being opened has saved "
                         "drafts (mesh_state shows it as 'asks'): 'resume' the newest draft, start 'fresh' from "
                         "the file (the drafts are kept either way), 'choose' another draft in Drafts & Mods "
                         "(Choose a Draft...), or 'cancel' the open.",
             input_schema=object_schema({"answer": {"type": "string", "enum": sorted(DRAFT_ANSWERS)}}, ["answer"]),
             effect=EDIT, route="ui:draft_choice buttons", handler=_draft_choice, runs_on=ON_CALL),
        Tool(name="mesh.show_document", family="mesh", title="Show a document",
             description="Shows one of the Mesh Editor's open documents, as a click on its tab does.",
             input_schema=object_schema({"index": {"type": "integer", "minimum": 0}}, ["index"]), effect=READ,
             route="ui:MeshDocuments.set_active", handler=_show_document, runs_on=ON_UI),
        Tool(name="mesh.select_parts", family="mesh", title="Select parts",
             description="Selects whole parts in the shown document by their numbers, as clicking their rows "
                         "in the Parts list does; an empty list clears the selection.",
             input_schema=object_schema({"parts": {"type": "array", "maxItems": 4096, "items": _PART}},
                                        ["parts"]),
             effect=EDIT, route="helper:select_parts", handler=_settled(_select_parts), runs_on=ON_CALL),
        Tool(name="mesh.highlight_part", family="mesh", title="Highlight a part",
             description="Lights one whole part up in the 3D view, as pointing at its row does, so a picture "
                         "(view_capture) shows which part it is; without 'part' the highlight ends. The "
                         "selection is not touched.",
             input_schema=object_schema({"part": _PART}), effect=READ, route="helper:highlight_part",
             handler=_highlight, runs_on=ON_UI),
        Tool(name="mesh.command", family="mesh", title="Mesh Editor command",
             description="Runs one of the Mesh Editor's own commands in the shown document, as its key or "
                         "button does: choosing a tool (tool.grab, tool.move ...; using it needs the "
                         "pointer), vertex, edge and face modes, select all, invert, grow, shrink, linked, "
                         "delete selection, camera presets and showing a page (page.uv ...; its controls are "
                         "the helper's own and are not reachable here). commands_list with context "
                         "mesh_editor lists them with their ids, whether each can run now and why not. "
                         "A command that deletes or exports asks as that class.",
             input_schema=object_schema({"command": {"type": "string", "minLength": 2, "maxLength": 128},
                                         "answers": _answers_schema()}, ["command"]),
             effect=EDIT, route="registry:mesh_editor.<id>", handler=_settled(_command), runs_on=ON_CALL,
             effect_of=_command_effect, approval_key=_helper_command_id),
        Tool(name="mesh.undo", family="mesh", title="Undo",
             description="Undo in the shown Mesh Editor document, as Ctrl+Z does there.",
             input_schema=object_schema(), effect=EDIT, route="registry:mesh_editor.session.undo",
             handler=_settled(_fixed_command("session.undo")), runs_on=ON_CALL),
        Tool(name="mesh.redo", family="mesh", title="Redo",
             description="Redo in the shown Mesh Editor document.",
             input_schema=object_schema(), effect=EDIT, route="registry:mesh_editor.session.redo",
             handler=_settled(_fixed_command("session.redo")), runs_on=ON_CALL),
        Tool(name="mesh.finish", family="mesh", title="Finish Edit Mesh",
             description="Finish Edit Mesh in the shown document, as its Finish button does: the edit is "
                         "validated and accepted, ready for Build Mod. mesh_state's status says how it went.",
             input_schema=object_schema(), effect=EDIT, route="registry:mesh_editor.session.finish",
             handler=_fixed_command("session.finish"), runs_on=ON_CALL),
        Tool(name="mesh.discard", family="mesh", title="Close the edit",
             description="Closes the shown document's edit session, as closing its mesh does. Steps not "
                         "finished are kept in its draft only as far as the draft saves them.",
             input_schema=object_schema(), effect=DESTRUCTIVE, route="ui:close_standalone_session",
             handler=_discard, runs_on=ON_CALL),
        Tool(name="mesh.build_mod", family="mesh", title="Build Mod",
             description="Build Mod for the shown document, as its button does, with the options dialog "
                         "filled from the call: the mod is written as a new folder inside 'output_folder' "
                         "(an existing folder outside the game), named in 'destination'. A hairstyle made with "
                         "Hair Tools gets the hairstyle dialog: its package mode ('manager'), Hairstyle ID, "
                         "barber icon and Send to DMM. Returns once the build has started; "
                         "mesh_state shows 'building' until it is done. When it does not start, 'asked' and "
                         "'status' carry the app's reason.",
             input_schema=object_schema({"output_folder": {"type": "string", "minLength": 3, "maxLength": 1024},
                                         "mod_name": text, "version": {"type": "string", "maxLength": 32},
                                         "author": text, "description": {"type": "string", "maxLength": 1024},
                                         "create_zip": {"type": "boolean", "default": False},
                                         "manager": {"type": "string", "maxLength": 64,
                                                     "description": "For a mesh: dmm_loose (DMM Loose Mesh, the "
                                                                    "default) or dmm_archive (DMM Archive Group). "
                                                                    "For a hairstyle made with Hair Tools (Package "
                                                                    "mode): hair_add (Add New Barber Hairstyle, DMM "
                                                                    "Additive), hair_replace_loose (Replace Existing "
                                                                    "Hairstyle, DMM Loose Mod) or hair_add_full (Add "
                                                                    "New Barber Hairstyle, Full Tables Archive)."},
                                         "include_body": {"type": "boolean",
                                                          "description": "Include the body (offered for worn "
                                                                         "garments only)."},
                                         "keep_layers": {"type": "array", "maxItems": 32,
                                                         "items": {"type": "string", "maxLength": 64},
                                                         "description": "Keep layers underneath "
                                                                        "(experimental): the clothing layers "
                                                                        "this garment stops cutting."},
                                         "hair_stem": {"type": "string", "maxLength": 64,
                                                       "description": "Hairstyle only: the new hairstyle's ID "
                                                                      "(Hairstyle ID), for hair_add and "
                                                                      "hair_add_full. By default it follows the "
                                                                      "mod name."},
                                         "custom_icon_path": {"type": "string", "minLength": 3, "maxLength": 1024,
                                                              "description": "Hairstyle only: an existing image "
                                                                             "or DDS file for the barber icon; "
                                                                             "without it the donor's icon is "
                                                                             "used."},
                                         "send_to_dmm": {"type": "boolean", "default": False,
                                                         "description": "Hairstyle only: write the mod straight "
                                                                        "into DMM's mods folder instead of "
                                                                        "'output_folder', replacing CDMW's earlier "
                                                                        "folder of the same name there. Refused "
                                                                        "when DMM's mods folder is not found."}},
                                        ["output_folder"]),
             effect=OUTPUT, route="ui:_start_mesh_mod_build_requested", handler=_build_mod, runs_on=ON_CALL,
             output_folders=("output_folder",)),
        Tool(name="mesh.export", family="mesh", title="Export Mesh File",
             description="Export Mesh File: the shown document's mesh as GLB, FBX or OBJ at 'path' (a new "
                         "file outside the game; the suffix picks the format), as the editor's Export menu does "
                         "after its file chooser. Waits for the export; the status line says how it went.",
             input_schema=object_schema({"path": {"type": "string", "minLength": 3, "maxLength": 1024}},
                                        ["path"]),
             effect=OUTPUT, route="helper:cdmw_command export_mesh", handler=_settled(_export), runs_on=ON_WORKER,
             output_paths=("path",)),
        Tool(name="mesh.replacement_state", family="mesh", title="Import Replacement state",
             description="Import Replacement in the shown document: whether it is offered and why not, the "
                         "parts, and the imported model waiting in the mapping step with its parts, the "
                         "suggested targets and the weights choices.",
             input_schema=object_schema(), effect=READ, route="service:mesh_rust_replacement.replacement_ui_state",
             handler=_replacement("replacement_state"), runs_on=ON_UI),
        Tool(name="mesh.replacement_import", family="mesh", title="Import Replacement",
             description="Import Replacement... with the mesh file at 'path' (OBJ, DAE, glTF, GLB, or FBX "
                         "when a Blender to read it is already chosen): scope 'entire' (Entire Mesh) or "
                         "'selected' with 'part_ids'. Waits for the import; the model then waits in the "
                         "mapping step: read it with mesh_replacement_state. The status line says why when "
                         "the import was refused.",
             input_schema=object_schema({"path": {"type": "string", "minLength": 3, "maxLength": 1024},
                                         "scope": {"type": "string", "enum": ["entire", "selected"],
                                                   "default": "entire"},
                                         "part_ids": {"type": "array", "maxItems": 4096,
                                                      "items": {"type": "string", "maxLength": 128}}}, ["path"]),
             effect=EDIT, route="helper:cdmw_command replacement_choose",
             handler=_replacement_import, runs_on=ON_WORKER),
        Tool(name="mesh.replacement_apply", family="mesh", title="Apply Replacement",
             description="Apply Replacement on the model in the mapping step: 'targets' gives each imported "
                         "part's target part id (by default the suggested ones), 'materials' is original or "
                         "imported, 'weights' the choice for a rigged model (preserve, reduce, fold, extend or "
                         "transfer). One History step; returns the history before and after and the status line.",
             input_schema=object_schema({"targets": {"type": "array", "maxItems": 4096,
                                                     "items": {"type": "string", "maxLength": 128}},
                                         "fallback_target": {"type": "string", "maxLength": 128},
                                         "materials": {"type": "string", "enum": ["original", "imported"],
                                                       "default": "original"},
                                         "weights": {"type": "string", "enum": ["preserve", "reduce", "fold",
                                                                                "extend", "transfer"]}}),
             effect=EDIT, route="helper:cdmw_command replacement_apply",
             handler=_settled(_replacement("replacement_apply")), runs_on=ON_WORKER),
        Tool(name="mesh.replacement_cancel", family="mesh", title="Cancel Import",
             description="Cancel Import in Import Replacement's mapping step.",
             input_schema=object_schema(), effect=EDIT, route="helper:cdmw_command replacement_cancel",
             handler=_settled(_replacement("replacement_cancel")), runs_on=ON_WORKER),
    ]


__all__ = ["mesh_tools", "ready_document", "shown_document"]
