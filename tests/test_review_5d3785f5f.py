"""Review of 5d3785f5f: journal a new draft's opened state with its first step (D3, option a).

The real MeshService, a real draft and the real native core, with the commit's own
helpers.
"""

from __future__ import annotations

import pytest

journal_tests = pytest.importorskip("tests.test_mesh_history_journal")
if not hasattr(journal_tests, "_replace_moved"):
    pytest.skip("5d3785f5f is not on this branch", allow_module_level=True)

from cdmw.services import mesh_history_journal as journal  # noqa: E402

_OPTIONAL = ("Review of 5d3785f5f (REPORT-review.md): a failure writing the optional opened-state generation "
             "makes the draft's own save fail, on every autosave")


def test_the_draft_s_own_first_save_survives_a_failed_opened_state(tmp_path, monkeypatch) -> None:
    """_save_mesh_layer_project_locked calls _save_opened_state_generation_locked before the
    draft's own generation, inside the same journal lock, with nothing catching it. When
    writing the opened state fails (its native export, the disk), the user's first step is
    not saved either, and every later autosave retries it the same way: the journal stays
    empty, so the optional write is attempted, and fails, each time."""

    from cdmw.services import mesh_service as module

    real = module.save_mesh_layer_project

    def failing_for_the_opened_state(*args, **kwargs):
        if str(kwargs.get("session_id", "")).endswith(":opened-state"):
            raise OSError("the opened state could not be written")
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "save_mesh_layer_project", failing_for_the_opened_state)
    service, session_id = journal_tests._open(tmp_path)
    try:
        try:
            journal_tests._replace_moved(service, session_id, 0.25)
        except OSError:
            pass  # today the optional write's failure comes out of the draft's own autosave
        records = journal.read_journal(tmp_path / "mesh_layers").records
        assert records, "the draft's own first step was not saved because the optional opened state failed"
    finally:
        try:
            service.close_edit_session(session_id)
        except RuntimeError:
            pass  # today the session then holds "unsaved geometry layers" and refuses to close
