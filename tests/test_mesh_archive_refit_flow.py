from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.archive_refit_flow import prepare_archive_refit_event
from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveSessionLoadWorker
from tests.test_replace_from_archive_dialog import _entry, _context


def test_archive_refit_picker_uses_only_host_prepared_archive_objects():
    target, armor = _entry("body.pac", 1), _entry("armor.pac", 2)
    session = object()
    dependencies = _context(armor)
    calls = []

    def choose(entry, role):
        calls.append((entry, role))
        return armor, dependencies

    tab = SimpleNamespace(
        _archive_refit_picker=SimpleNamespace(choose=choose),
        _current_target_entry=lambda: target,
        standalone_rust_authoring_session=session, standalone_rust_closing=False,
    )
    event = {"command": "refit_choose_archive", "arguments": {
        "role": "armor", "path": "untrusted.obj", "_archive_entry": "untrusted",
    }}
    prepared = prepare_archive_refit_event(tab, session, event)
    assert calls == [(target, "armor")]
    assert prepared["arguments"]["_archive_entry"] is armor
    assert prepared["arguments"]["_archive_dependencies"] is dependencies
    assert "path" not in prepared["arguments"]


@pytest.mark.parametrize("change", ["session", "target", "close"])
def test_archive_refit_picker_rejects_stale_session_target_and_close(change):
    target, armor = _entry("body.pac", 1), _entry("armor.pac", 2)
    session = object()
    tab = SimpleNamespace(standalone_rust_authoring_session=session, standalone_rust_closing=False,
                          _current_target_entry=lambda: target)

    def choose(_entry, _role):
        if change == "session":
            tab.standalone_rust_authoring_session = object()
        elif change == "target":
            tab._current_target_entry = lambda: armor
        else:
            tab.standalone_rust_closing = True
        return armor, _context(armor)

    tab._archive_refit_picker = SimpleNamespace(choose=choose)
    with pytest.raises(ValueError, match="closed|changed"):
        prepare_archive_refit_event(tab, session, {"arguments": {"role": "armor"}})


def test_archive_picker_keeps_protocol_queue_single_flight():
    tab = SimpleNamespace(_archive_refit_picker_active=True)
    # No protocol worker or queue fields are touched while the modal picker runs.
    MeshEditorRustProcessMixin._start_next_rust_protocol_worker(tab)


def test_cancel_after_archive_session_open_disposes_unpublished_native_session():
    app = QApplication.instance() or QApplication([])
    worker = MeshArchiveSessionLoadWorker(3, _entry("body.pac", 1))
    closed, loaded, finished = [], [], []

    class Service:
        def load_mesh_bytes(self, *_args, **_kwargs):
            return SimpleNamespace()

        def open_edit_session(self, *_args, **_kwargs):
            worker.stop()
            return SimpleNamespace(session_id="cancelled-refit-load")

        def close_edit_session(self, session_id, *, force_without_saving):
            closed.append((session_id, force_without_saving))

    worker.loaded.connect(lambda *_args: loaded.append(True))
    worker.finished.connect(lambda: finished.append(True))
    with patch("cdmw.workers.mesh_editor_aux_workers.MeshService", Service), patch(
        "cdmw.workers.mesh_editor_aux_workers.read_archive_entry_data", return_value=(b"owned", False, ""),
    ):
        worker.run()
    assert not loaded
    assert closed == [("cancelled-refit-load", True)]
    assert finished == [True]
    app.processEvents()
