"""Finish, Discard or Keep editing: the one question before an edit is replaced (P4 V3).

Everything that would replace a pending edit in its viewport asks through
``resolve_pending_edit``: previewing another file in Browse while editing,
opening another mesh, and closing the app. P14 and P15 rely on the same call.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QMessageBox, QWidget

FINISH = "finish"
DISCARD = "discard"
KEEP = "keep"
#: No edit was pending, so nothing was asked.
NONE = "none"

#: Tests answer the prompt here instead of showing it: ``lambda parent, label: DISCARD``.
prompt_override: Callable[[QWidget | None, str], str] | None = None
#: Tests read the notice here instead of a message box: ``lambda parent, text: ...``.
notice_override: Callable[[QWidget | None, str], None] | None = None
FINISH_UNAVAILABLE = ("Finish is not available while the editor is starting, restarting or parked. "
                      "Show its tab and try again when the editor is ready, or choose Discard.")


def pending_edit_revision(tab: object) -> int:
    """The accepted revision of the Mesh Editor's open session, 0 when nothing is edited."""

    has_session = getattr(tab, "has_active_standalone_session", None)
    try:
        if not callable(has_session) or not has_session():
            return 0
        controller = getattr(tab, "standalone_controller", None)
        return int(controller.session_view().revision) if controller is not None else 0
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        return 0


def unfinished_editor_steps(tab: object) -> int:
    """Editor steps no Finish has taken yet, whether or not the editor is ready,
    parked or restarting (section 8.8)."""

    session = getattr(tab, "standalone_rust_authoring_session", None)
    if session is None or getattr(session, "closed", True):
        return 0
    steps = getattr(session, "unfinished_steps", None)
    try:
        return int(steps()) if callable(steps) else 0
    except Exception:
        return 1  # cannot tell: ask rather than lose them


def has_pending_edit(tab: object) -> bool:
    """The one definition of a pending edit (section 8.8, cause 3).

    A document with a session and accepted steps, unfinished editor steps or a
    recovery point, whether its editor is ready, parked, restarting or still
    opening; or an editor open in its viewport. Every close, shutdown, discard
    and "preview instead" path asks through this.
    """

    live_edit = getattr(tab, "live_edit", None)
    if bool(getattr(live_edit, "is_ready", False)) or pending_edit_revision(tab) > 0:
        return True
    if unfinished_editor_steps(tab) > 0 or _preparing_over_recovery(tab):
        return True
    session = getattr(tab, "standalone_rust_authoring_session", None)
    holds = getattr(session, "holds_recovery_point", None)
    try:
        return bool(session is not None and not getattr(session, "closed", True)
                    and callable(holds) and holds())
    except Exception:
        return True


def ask_to_end_edit(parent: QWidget | None, file_label: str, *, finish_available: bool = True) -> str:
    """Show the question and return FINISH, DISCARD or KEEP."""

    if prompt_override is not None:
        return prompt_override(parent, file_label)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Unfinished Mesh Edit")
    box.setText(f"You are editing {file_label or 'a mesh'}.")
    # Discard closes the whole session (section 8.7 A8): say so.
    box.setInformativeText(
        "Finish keeps your changes as a pending edit. Discard closes the edit: changes made since the "
        "last Finish are lost, and a draft keeps what was finished. Keep editing returns to the editor."
        + ("" if finish_available else "\n\n" + FINISH_UNAVAILABLE)
    )
    finish = box.addButton("Finish", QMessageBox.ButtonRole.AcceptRole)
    finish.setEnabled(bool(finish_available))
    discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
    keep = box.addButton("Keep editing", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(keep)
    box.setEscapeButton(keep)
    box.exec()
    clicked = box.clickedButton()
    if clicked is finish:
        return FINISH
    if clicked is discard:
        return DISCARD
    return KEEP


def resolve_pending_edit(parent: QWidget | None, tab: object, *, file_label: str = "") -> str:
    """Ask about the pending edit and act on the answer.

    FINISH asks the editor to finish (it completes in the background; the caller
    does not go on). DISCARD closes the session, so the caller may go on. KEEP
    does nothing. NONE: no edit was pending; the caller may go on.
    """

    if not has_pending_edit(tab):
        return NONE
    if not file_label:
        target = getattr(tab, "_current_target_entry", None)
        entry = target() if callable(target) else None
        file_label = str(getattr(entry, "basename", "") or getattr(entry, "path", "") or "")
    live_edit = getattr(tab, "live_edit", None)
    answer = ask_to_end_edit(parent, file_label, finish_available=bool(getattr(live_edit, "is_ready", False)))
    if answer == FINISH:
        request = getattr(live_edit, "request_finish", None)
        if not callable(request) or not request():
            # Nothing could finish it: the edit stays, and the user is told why (8.7 A8).
            _tell(parent, FINISH_UNAVAILABLE)
            return KEEP
    elif answer == DISCARD:
        mark_discarded(tab)
        close = getattr(tab, "close_standalone_session", None)
        if callable(close):
            close()
    return answer


def mark_discarded(tab: object) -> None:
    """The user chose Discard: this document's close ends its recovery point."""

    session = getattr(tab, "standalone_rust_authoring_session", None)
    if session is not None:
        try:
            session.discard_requested = True
        except AttributeError:
            pass


def _preparing_over_recovery(tab: object) -> bool:
    """An editor still opening over a draft that keeps unfinished edits (section 8.9):
    closing now must ask, since the edits are not in a session yet."""

    if getattr(tab, "standalone_rust_prepare_thread", None) is None:
        return False
    controller = getattr(tab, "standalone_controller", None)
    service = getattr(controller, "mesh_service", None)
    session_id = str(getattr(controller, "active_session_id", "") or "")
    try:
        project = service._session(session_id).mesh_layer_project_path if service and session_id else None
    except (AttributeError, KeyError, RuntimeError):
        return False
    from pathlib import Path

    return bool(project is not None and (Path(project).parent / "editor_recovery.json").is_file())


def _tell(parent: QWidget | None, text: str) -> None:
    if notice_override is not None:
        notice_override(parent, text)
        return
    QMessageBox.information(parent, "Finish Is Not Available", text)


__all__ = [
    "DISCARD", "FINISH", "KEEP", "NONE", "ask_to_end_edit", "has_pending_edit",
    "pending_edit_revision", "prompt_override", "resolve_pending_edit", "unfinished_editor_steps",
]
