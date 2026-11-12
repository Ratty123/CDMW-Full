"""Review of 5d59a69e (section 8.8 R8): a clean mark appended after a crash cut-off.

Through the real MeshService over a real draft, as Build reaches it. Strict
xfail: it fails on the reviewed code; remove the marker with the fix.
"""

from __future__ import annotations

import pytest

from cdmw.services import mesh_history_journal as journal
from tests.test_mesh_history_journal import _move, _open

_REVIEW = "Review of 5d59a69e (REPORT-review.md): mark_clean appends onto a cut-off last line"


def test_a_build_after_a_crash_mid_append_keeps_the_journal_writable(tmp_path) -> None:
    """A crash in the middle of an append leaves a last line without its newline;
    R8 lets the next write rewrite over it. mark_clean appends instead, so the clean
    mark is glued onto the cut-off line: one unreadable line that is no longer the
    cut-off tail. From then on the journal is never written again, in any session."""

    service, session_id = _open(tmp_path)
    _move(service, session_id, 0.25)
    service.close_edit_session(session_id)
    project_root = tmp_path / "mesh_layers"
    path = journal.journal_path(project_root)
    good = journal.read_journal(project_root).records[-1]
    with path.open("a", encoding="utf-8") as handle:
        handle.write(good.line()[:40])  # a crash in the middle of the next append
    assert journal.read_journal(project_root).unreadable_lines == 0, "the cut-off tail may be written over"

    service, session_id = _open(tmp_path)
    service.mark_history_clean(session_id)  # as Build does, the state being saved
    assert journal.read_journal(project_root).unreadable_lines == 0, "the clean mark broke the journal"
    _move(service, session_id, 0.25)
    assert not service.session_view(session_id).history_journal_error
    service.close_edit_session(session_id)
