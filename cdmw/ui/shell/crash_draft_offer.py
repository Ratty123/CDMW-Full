"""Offer the autosaved draft after CDMW itself closed unexpectedly (P4 V4).

A few seconds after start-up, never during the first click's work, the shell
looks for Mesh Editor drafts saved while the session that died was running
and offers to open Drafts & Mods on them. The notice does not block the app.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

#: Delay after start-up before the drafts are looked up.
OFFER_DELAY_MS = 3000


class _Found(QObject):
    found = Signal(object)


def schedule_crash_draft_offer(window: QWidget) -> None:
    heartbeat = getattr(window, "_previous_heartbeat", None)
    if not heartbeat or getattr(window, "_crash_draft_offer_scheduled", False):
        return
    window._crash_draft_offer_scheduled = True
    QTimer.singleShot(OFFER_DELAY_MS, lambda: _look_up_drafts(window, dict(heartbeat)))


def _look_up_drafts(window: QWidget, heartbeat: dict) -> None:
    from cdmw.services.crash_draft_recovery import drafts_saved_during

    root_getter = getattr(window, "_mesh_saved_work_root", None)
    if not callable(root_getter):
        return
    try:
        root = root_getter()
    except (OSError, RuntimeError, TypeError, ValueError):
        return
    signals = _Found(window)
    signals.found.connect(lambda rows: show_crash_draft_offer(window, rows))

    def look() -> None:
        try:
            rows = drafts_saved_during(heartbeat, root)
        except (OSError, RuntimeError, TypeError, ValueError):
            rows = ()
        signals.found.emit(tuple(rows))

    threading.Thread(target=look, name="cdmw-crash-draft-offer", daemon=True).start()


def crash_draft_offer_text(rows: tuple) -> str:
    newest = rows[0]
    saved = time.strftime("%H:%M", time.localtime(float(newest.saved_at)))
    name = str(getattr(newest, "display_name", "") or getattr(newest, "source_archive_path", "") or "")
    if len(rows) == 1:
        return f"Your draft of {name} was saved at {saved} and is kept."
    return f"{len(rows)} drafts were saved while you were editing; the newest, {name}, at {saved}. They are kept."


def show_crash_draft_offer(window: QWidget, rows: tuple) -> QMessageBox | None:
    """Non-modal: Open Drafts & Mods on the newest draft, or not now."""

    if not rows:
        return None
    box = QMessageBox(window)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("Recover Your Edit")
    box.setText("CDMW closed unexpectedly while you were editing.")
    box.setInformativeText(crash_draft_offer_text(rows))
    open_button = box.addButton("Open Drafts & Mods", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
    path = str(getattr(rows[0], "source_archive_path", "") or "")

    def answered(_result: int) -> None:
        if box.clickedButton() is open_button:
            opener = getattr(window, "_open_mesh_editor_saved_work", None)
            if callable(opener):
                opener(path)

    box.finished.connect(answered)
    box.open()
    window._crash_draft_offer_box = box
    return box


__all__ = ["OFFER_DELAY_MS", "crash_draft_offer_text", "schedule_crash_draft_offer", "show_crash_draft_offer"]
