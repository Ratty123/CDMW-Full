"""Undo and Redo through one history for mesh and texture edits (Work B item 4), on the tab.

The Rust editor sends ``undo`` and ``redo`` as commands. Before one goes to the authoring
worker, ``route_history_step`` looks at what the shared history says comes next: a mesh
step goes on as it is; a texture step is made here, on the UI thread, in the Texture
Editor's session for that texture, and the worker is asked only for the state (which
carries the merged history back to the editor). Texture edits made in the dock reach the
editor's History between requests as a ``history_update`` message.
"""

from __future__ import annotations

from typing import Mapping

from cdmw.ui.mesh_editor.shared_edit_history import SharedEditHistory


def attach_shared_history(tab, session) -> SharedEditHistory:
    """One history per document: kept on the tab, so a reopened editor session (after
    Finish) still has the document's texture entries; handed to the authoring session,
    whose state builders merge it."""

    history = getattr(tab, "_shared_edit_history", None)
    if history is None:
        history = SharedEditHistory()
        tab._shared_edit_history = history
    session.shared_history = history
    dock = _dock(tab)
    if dock is not None:
        dock.shared_history = history
    return history


def _dock(tab):
    panel = getattr(tab, "_texture_tools_panel", None)
    try:
        return panel() if callable(panel) else None
    except RuntimeError:
        return None


def route_history_step(tab, event: Mapping[str, object]) -> dict[str, object]:
    """The event to hand the worker for a queued Rust request (UI thread)."""

    event = dict(event)
    command = str(event.get("command", "") or "")
    if event.get("event") != "command_request" or command not in {"undo", "redo"}:
        return event
    history: SharedEditHistory | None = getattr(tab, "_shared_edit_history", None)
    if history is None:
        return event
    step = history.next_undo() if command == "undo" else history.next_redo()
    if step is not None and step.kind == "mesh":
        history.expect_mesh(command)
        return event
    if step is not None and not texture_step(tab, history, step.texture_key, command):
        history.forget_texture(step.texture_key)
    # Nothing (or a texture) to step: the mesh stacks stay as they are. A hidden mesh redo
    # (dropped by a later texture edit) is never redone.
    return {**event, "command": "state", "arguments": {}}


def texture_step(tab, history: SharedEditHistory, texture_key: str, command: str) -> bool:
    """Undo or redo one edit of ``texture_key`` in its Texture Editor session, bringing
    that texture forward in the dock first. False when its session is gone."""

    dock = _dock(tab)
    targets = getattr(dock, "_targets", {}) if dock is not None else {}
    target = targets.get(texture_key)
    if target is None or getattr(dock, "editor", None) is None:
        return False
    if getattr(dock, "target", None) is not target:
        dock.open_target(target)
    editor = dock.editor
    before = int(getattr(editor, "history_index", 0) or 0)
    dock.stepping = True
    try:
        (editor.undo if command == "undo" else editor.redo)()
    finally:
        dock.stepping = False
    after = int(getattr(editor, "history_index", 0) or 0)
    if after == before:
        return False
    history.texture_stepped(texture_key, command, after)
    # The editor's own history list moved too; tell the dock what it now holds.
    observe = getattr(dock, "observe_history", None)
    if callable(observe):
        observe(target)
    return True


def send_history_update(tab) -> bool:
    """Send the merged history to the Rust editor (after a texture edit made in the dock).
    Rust takes it while a request is pending; that request's reply is checked after it."""

    history: SharedEditHistory | None = getattr(tab, "_shared_edit_history", None)
    if history is None or not getattr(tab, "standalone_rust_ready", False):
        return False
    fields = history.current_history_payload()
    tab._history_update_sent_revision = fields["history_revision"]
    return bool(tab._send_rust_message(tab._rust_host_message("history_update", request_id=0,
                                                              extra={"payload": fields})))


def step_from_dock(tab, step: str) -> bool:
    """The dock's Undo or Redo: the editor runs its own Undo or Redo, which comes back as a
    request and is routed like Ctrl+Z there. False when no editor is running."""

    if step not in {"undo", "redo"} or not getattr(tab, "standalone_rust_ready", False):
        return False
    return bool(tab._send_rust_message(tab._rust_host_message("run_command", request_id=0,
                                                              extra={"command": f"session.{step}"})))


def texture_history_changed(tab) -> None:
    """The dock's texture history moved (UI thread): show it in the editor now, and again
    after a reply that was being built meanwhile, since that reply may carry the older one
    (a large reply goes as a file, so its history cannot be checked here)."""

    send_history_update(tab)
    if getattr(tab, "standalone_rust_protocol_thread", None) is not None:
        tab._history_update_after_reply = True


def follow_reply(tab) -> None:
    """After a reply went to the editor: resend the history if it moved while it was built."""

    if getattr(tab, "_history_update_after_reply", False):
        tab._history_update_after_reply = False
        send_history_update(tab)


__all__ = ["attach_shared_history", "follow_reply", "route_history_step", "send_history_update", "step_from_dock",
           "texture_history_changed",
           "texture_step"]
