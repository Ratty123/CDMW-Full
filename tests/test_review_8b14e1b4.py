"""Review of 8b14e1b4 (section 8.8 R1, cause 3): gaps left in the pending-edit definition.

Real Mesh Editor tabs, the real prepared-session handler and the real dispose
worker over a real authoring session. Only the helper process is absent.
Strict xfails: they fail on the reviewed code; remove the marker with the fix.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.live_edit import end_edit_prompt
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from tests.test_p15_round2_pending import _authoring

_APP = QApplication.instance() or QApplication([])
_REVIEW = "Review of 8b14e1b4 (REPORT-review.md): an unasked dispose deletes the recovery point"


def _recovery_point(session, root: Path) -> Path:
    """A session that opened on restored edits: its draft keeps a recovery point."""

    session.recovery_project_root = root
    session.recovered_edits_at = 1.0
    marker = root / "editor_recovery.json"
    marker.write_text("{}", encoding="utf-8")
    return marker


def test_a_session_prepared_after_its_document_closed_keeps_the_recovery_point(tmp_path) -> None:
    """R1, "while an editor opens on restored edits".

    While the shadow session prepares, the tab has no authoring session, so
    has_pending_edit() says False and closing the tab or CDMW asks nothing. When
    the prepared session then arrives for a context that has ended, the handler
    gives it to the dispose worker, which calls cancel(), and cancel() deletes the
    recovery point as if the user had chosen Discard. The unfinished edits are gone.
    """

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    tab = MeshEditorTab(settings=settings)
    try:
        root = tmp_path / "session"
        root.mkdir()
        session = _authoring(root)
        marker = _recovery_point(session, tmp_path)
        assert not end_edit_prompt.has_pending_edit(tab), "nothing to ask about while preparing"
        # The document was closed (or its preparation superseded): no prepare context.
        tab.standalone_rust_prepare_controller = None
        tab._handle_rust_session_prepared(tab.standalone_rust_prepare_active_request_id, session)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and tab.standalone_rust_dispose_thread is not None:
            _APP.processEvents()
            time.sleep(0.01)
        assert tab.standalone_rust_dispose_thread is None, "the dispose never finished"
        assert session.closed
        assert marker.is_file(), "an unasked dispose deleted the unfinished edits' recovery point"
    finally:
        tab.deleteLater()
        _APP.processEvents()


def test_an_answered_discard_still_deletes_the_recovery_point(tmp_path) -> None:
    """The intended half: Discard, which the user chose, ends the recovery point (P14)."""

    root = tmp_path / "session"
    root.mkdir()
    session = _authoring(root)
    marker = _recovery_point(session, tmp_path)
    session.cancel()
    assert session.closed
    assert not marker.exists()
