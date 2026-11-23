"""The Mesh Editor's documents by numbers: open a file or one piece, close a tab, switch
the editable piece of a set, jump the history, and show or hide reference pieces.

Each goes the way its control goes: the document tabs' close button, the Reference
pieces' Switch editable piece menu and View boxes, and the History list's Undo from
here and Restore through here. An unfinished edit is never replaced without an answer:
a file opens in a new document beside it, and closing its tab needs ``discard_edit``.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, READ
from cdmw.mcp.tools import ON_WORKER, Tool, object_schema

#: The files the Mesh Editor opens from disk (MeshFileSessionLoadWorker).
LOCAL_MESH_SUFFIXES = (".pac", ".pam", ".pamlod", ".obj", ".glb", ".fbx")
HISTORY_S = 60.0
NO_EDITOR_VIEW = "Open the Mesh Editor first (mesh_open, or its rail page)."


def _view(context):
    from cdmw.mcp.mesh_tools import _view as view

    found = view(context)
    if found is None:
        raise ToolError(UNAVAILABLE, NO_EDITOR_VIEW)
    return found


def _free_document(context):
    """The shown document, or a new one beside it when it has an unfinished edit."""

    from cdmw.ui.mesh_editor.live_edit.end_edit_prompt import has_pending_edit

    view = _view(context)
    tab = getattr(view, "active", None) or view
    if has_pending_edit(tab):
        opened = getattr(view, "open_new_document", None)
        tab = opened() if callable(opened) else None
        if tab is None:
            raise ToolError(UNAVAILABLE, "The shown document has an unfinished edit and no other document can be "
                                         "opened; finish or close one first.")
    return tab


# ----- opening ------------------------------------------------------------------------------
def _open_file(call) -> dict[str, object]:
    from cdmw.mcp.mesh_tools import _act, _status

    path = Path(str(call.arguments["path"]))
    if path.suffix.lower() not in LOCAL_MESH_SUFFIXES or not path.is_absolute() or not path.is_file():
        raise ToolError(INVALID_ARGUMENTS, "Give the full path of an existing .pac, .pam, .pamlod, .obj, .glb or "
                                           ".fbx file.")

    def open_it() -> dict[str, object]:
        tab = _free_document(call.context)
        request = tab.open_mesh_file_session_async(path)
        if request is None:
            raise ToolError(UNAVAILABLE, _status(tab) or "The Mesh Editor did not open the file.")
        return {"opening": True, "path": str(path),
                "message": "The Mesh Editor is opening the file; mesh_state says when it is ready. A file from "
                           "disk has no archive target, so Build Mod is not offered for it."}

    return _act(call, open_it)


def _open_piece(call) -> dict[str, object]:
    """One file of a worn set on its own: Browse's set scope is cleared first (Clear Scope)."""

    from cdmw.mcp.mesh_tools import _act, _open

    window = getattr(call.context, "window", None)
    archive = getattr(window, "archive", None)

    def clear_scope() -> dict[str, object]:
        bridge = getattr(archive, "archive_remote_bridge", None)
        members = tuple(getattr(bridge, "item_set_members", ()) or ())
        button = getattr(archive, "archive_clear_asset_scope_button", None)
        if members and button is not None and button.isEnabled():
            button.click()
            return {"cleared_scope": True}
        return {"cleared_scope": False}

    if archive is None:
        from cdmw.ui.ai_connections.context import NO_ARCHIVES

        raise ToolError(UNAVAILABLE, NO_ARCHIVES)
    cleared = _act(call, clear_scope)
    alone = SimpleNamespace(context=call.context, arguments={"path": str(call.arguments["path"])},
                            check_cancelled=call.check_cancelled)
    return {**_open(alone), "cleared_scope": bool(cleared.get("cleared_scope"))}


# ----- closing and switching ------------------------------------------------------------------
def _close(call) -> dict[str, object]:
    from cdmw.mcp.mesh_tools import _act
    from cdmw.ui.mesh_editor.documents import document_label
    from cdmw.ui.mesh_editor.live_edit.end_edit_prompt import has_pending_edit, mark_discarded

    index = int(call.arguments["index"])
    discard = bool(call.arguments.get("discard_edit", False))

    def close() -> dict[str, object]:
        view = _view(call.context)
        documents = tuple(getattr(view, "documents", ()) or ())
        if not 0 <= index < len(documents):
            raise ToolError(NOT_FOUND, f"The Mesh Editor has {len(documents)} open documents.")
        document = documents[index]
        label = document_label(document)
        if has_pending_edit(document):
            if not discard:
                raise ToolError(UNAVAILABLE, f"{label} has an unfinished edit: finish it (mesh_finish), or close "
                                             "with discard_edit true to drop its steps.")
            # As the close question's Discard: the session ends and its recovery point with it.
            mark_discarded(document)
            document.close_standalone_session()
        if not view.close_document(index):
            raise ToolError(UNAVAILABLE, f"{label} was not closed; mesh_state says why.")
        return {"closed": index, "label": label, "discarded": discard,
                "documents": len(tuple(getattr(view, "documents", ()) or ()))}

    return _act(call, close)


def _close_effect(call) -> str:
    return DESTRUCTIVE if call.arguments.get("discard_edit") else EDIT


def _switch_piece(call) -> dict[str, object]:
    from cdmw.mcp.mesh_tools import _act, _busy, ready_document

    piece = int(call.arguments["piece"])

    def switch() -> dict[str, object]:
        tab = ready_document(call.context)
        contexts = tuple(getattr(tab, "item_set_contexts", ()) or ())
        names = [str(getattr(getattr(context, "selected_entry", None), "path", "") or "") for context in contexts]
        if len(contexts) < 2:
            raise ToolError(UNAVAILABLE, "The shown document is not one piece of a set; Switch editable piece is "
                                         "offered for a set opened with its reference pieces.")
        if not 0 < piece < len(contexts):
            raise ToolError(INVALID_ARGUMENTS, f"Piece 0 ({names[0]}) is the one being edited; switch to 1 to "
                                               f"{len(contexts) - 1}.")
        if _busy(tab):
            from cdmw.mcp.mesh_tools import BUSY

            raise ToolError(UNAVAILABLE, BUSY)
        # As the helper's Switch editable piece menu (tab_rust_process, switch_item_piece).
        tab.switch_item_piece_requested.emit(piece)
        return {"switching_to": names[piece], "pieces": names,
                "message": "The Mesh Editor is opening that piece with the others as references; mesh_state says "
                           "when it is ready."}

    return _act(call, switch)


# ----- history and reference pieces (editor_control "document") --------------------------------
def _history_jump(call) -> dict[str, object]:
    from cdmw.mcp.editor_control import editor_control
    from cdmw.mcp.mesh_edit_tools import history_now

    before = history_now(call)
    answer = editor_control(call, "document", {"action": "history_cursor", "cursor": int(call.arguments["cursor"])})
    state = answer.get("state") or {}
    if answer.get("ok"):
        # Each step is one Undo or Redo the host answers, as the list's own jump.
        deadline = time.monotonic() + HISTORY_S
        while isinstance(state, dict) and (state.get("history") or {}).get("traversing"):
            call.check_cancelled()
            if time.monotonic() > deadline:
                break
            time.sleep(0.1)
            state = editor_control(call, "document", {"action": "state"}).get("state") or {}
    outcome: dict[str, object] = {"done": bool(answer.get("ok")), "history_before": before,
                                  "history": history_now(call), "document": state}
    if not answer.get("ok"):
        outcome["message"] = answer.get("message")
    return outcome


def _reference_pieces(call) -> dict[str, object]:
    from cdmw.mcp.editor_control import control_outcome, editor_control

    a = call.arguments
    if a.get("piece") is None and a.get("visible") is None:
        return control_outcome(editor_control(call, "document", {"action": "state"}), "document")
    if a.get("piece") is None or a.get("visible") is None:
        raise ToolError(INVALID_ARGUMENTS, "Give piece and visible together, or neither to read the pieces.")
    return control_outcome(editor_control(call, "document", {"action": "reference_piece", "piece": int(a["piece"]),
                                                             "visible": bool(a["visible"])}), "document")


def _reference_effect(call) -> str:
    return READ if call.arguments.get("visible") is None else EDIT


def mesh_document_tools() -> list[Tool]:
    path = {"type": "string", "minLength": 3, "maxLength": 1024}
    return [
        Tool(name="mesh.open_file", family="mesh", title="Open a mesh file",
             description="Opens a mesh file from disk in the Mesh Editor (.pac, .pam, .pamlod, .obj, .glb or .fbx at "
                         "the full 'path'), in the shown document or, beside an unfinished edit, in a new one. "
                         "Returns at once; mesh_state says when it is ready. A file from disk has no archive "
                         "target: edit and export it, but Build Mod needs an archive mesh (mesh_open).",
             input_schema=object_schema({"path": path}, ["path"]), effect=EDIT,
             route="ui:open_mesh_file_session_async", handler=_open_file, runs_on=ON_WORKER),
        Tool(name="mesh.open_piece", family="mesh", title="Open one piece alone",
             description="Opens one file of a worn set on its own, without the set's other pieces as references: "
                         "Browse Archives' set scope is cleared first (Clear Scope), then the file at 'path' opens "
                         "as mesh_open opens it. Use it for panels that work on a single file; mesh_open of a piece "
                         "while Browse shows its set opens it with the set (or shows the set's document when that "
                         "set is already open).",
             input_schema=object_schema({"path": {"type": "string", "minLength": 3, "maxLength": 512}}, ["path"]),
             effect=EDIT, route="ui:archive_clear_asset_scope_button + shell._open_current_archive_mesh_editor",
             handler=_open_piece, runs_on=ON_WORKER),
        Tool(name="mesh.close_document", family="mesh", title="Close a document",
             description="Closes one of the Mesh Editor's documents by its number (mesh_state lists them), as its "
                         "tab's close button does, shown, inactive or parked. A document with an unfinished edit "
                         "is closed only with 'discard_edit' true, which drops its unfinished steps as the close "
                         "question's Discard does; otherwise finish it first (mesh_finish).",
             input_schema=object_schema({"index": {"type": "integer", "minimum": 0},
                                         "discard_edit": {"type": "boolean", "default": False}}, ["index"]),
             effect=DESTRUCTIVE, effect_of=_close_effect, route="ui:MeshDocumentsView.close_document",
             handler=_close, runs_on=ON_WORKER),
        Tool(name="mesh.switch_piece", family="mesh", title="Switch editable piece",
             description="For one piece of a set open with its reference pieces: edits another piece instead, as "
                         "the Reference pieces' Switch editable piece menu does. 'piece' is its number in the set "
                         "(mesh_reference_pieces lists the set's files; 0 is the one being edited). The current "
                         "piece's unfinished edit stays in its own document.",
             input_schema=object_schema({"piece": {"type": "integer", "minimum": 1}}, ["piece"]), effect=EDIT,
             route="ui:switch_item_piece_requested", handler=_switch_piece, runs_on=ON_WORKER),
        Tool(name="mesh.history_jump", family="mesh", title="Jump the history",
             description="Moves the shown document's history to 'cursor' (how many History entries stay "
                         "applied), as the History list's Undo from here and Restore through here do: one Undo or "
                         "Redo at a time, each answered by CDMW. Waits until it is there and returns the history "
                         "before and after.",
             input_schema=object_schema({"cursor": {"type": "integer", "minimum": 0}}, ["cursor"]), effect=EDIT,
             route="helper:editor_control document history_cursor", handler=_history_jump, runs_on=ON_WORKER),
        Tool(name="mesh.reference_pieces", family="mesh", title="Reference pieces",
             description="The shown document's Reference pieces (the set's other files drawn read-only around "
                         "the piece being edited) and the set's files: without arguments it reads them; with "
                         "'piece' and 'visible' it shows or hides one in the view, as its View box does.",
             input_schema=object_schema({"piece": {"type": "integer", "minimum": 0}, "visible": {"type": "boolean"}}),
             effect=EDIT, effect_of=_reference_effect, route="helper:editor_control document reference_piece",
             handler=_reference_pieces, runs_on=ON_WORKER),
    ]


__all__ = ["LOCAL_MESH_SUFFIXES", "mesh_document_tools"]
