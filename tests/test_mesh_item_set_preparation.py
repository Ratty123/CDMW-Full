from dataclasses import replace
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal

from cdmw.domain.archives.catalogue import ArchiveAssociationResult
from cdmw.domain.archives.catalogue_operations import PrepareEntriesResult
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.mesh_editor.item_set_preparation import ItemSetEditorPreparation
from tests.test_archive_remote_preview_dependencies import _CatalogueService, _dto, _prepared
from tests.test_archive_remote_window_bridge import _app
from unittest.mock import patch
import pytest


class _Service(_CatalogueService):
    session_published = Signal(object)
    current_session = SimpleNamespace(session_id="session-a")


def _complete(service, number, model, dependencies=()):
    service.result_ready.emit(f"association-{number}", "find_association_candidates",
        ArchiveAssociationResult("session-a", model.entry_id, dependencies, len(dependencies), False))
    rows = (model, *dependencies)
    service.result_ready.emit(f"prepare-{number + 1}", "prepare_entry",
        PrepareEntriesResult("session-a", tuple(_prepared(row) for row in rows), len(rows), len(rows), 40*len(rows)))


def test_set_editor_prepares_each_files_owned_context_and_selected_file_first():
    _app()
    service = _Service()
    preparation = ItemSetEditorPreparation(service)
    upper, lower = _dto(1, "upper.pac"), _dto(2, "lower.pac")
    ready = []
    preparation.ready.connect(ready.append)
    assert preparation.start(ArchiveCatalogueService.compatibility_entry(lower), (upper, lower))
    assert service.requests[0][0].entry_id == lower.entry_id
    _complete(service, 1, lower, (_dto(12, "lower.dds"),))
    assert not ready and service.requests[-1][0].entry_id == upper.entry_id
    _complete(service, 3, upper, (_dto(11, "upper.dds"),))
    assert len(ready) == 1 and not preparation.pending
    contexts = ready[0]
    assert [context.selected_entry.path for context in contexts] == ["lower.pac", "upper.pac"]
    assert [set(context.entries_by_normalized_path) for context in contexts] == [
        {"lower.pac", "lower.dds"}, {"upper.pac", "upper.dds"}]
    assert all(context.selected_entry.prepared_path is not None for context in contexts)


def test_set_editor_preparation_cancels_superseded_requests_and_rejects_late_completion():
    _app()
    service = _Service()
    preparation = ItemSetEditorPreparation(service)
    upper, lower = _dto(1, "upper.pac"), _dto(2, "lower.pac")
    ready = []
    preparation.ready.connect(ready.append)
    assert preparation.start(ArchiveCatalogueService.compatibility_entry(upper), (upper, lower))
    assert preparation.start(ArchiveCatalogueService.compatibility_entry(lower), (upper, lower))
    service.result_ready.emit("association-1", "find_association_candidates",
        ArchiveAssociationResult("session-a", 1, (), 0, False))
    assert service.cancelled == ["association-1"] and not ready
    preparation.cancel()
    _complete(service, 2, lower)
    assert service.cancelled == ["association-1", "association-2"] and not ready


def test_set_editor_preparation_rejects_partial_context_on_failure_or_catalogue_change():
    _app()
    service = _Service()
    preparation = ItemSetEditorPreparation(service)
    upper, lower = _dto(1, "upper.pac"), _dto(2, "lower.pac")
    ready, failures = [], []
    preparation.ready.connect(ready.append)
    preparation.failed.connect(failures.append)
    assert preparation.start(ArchiveCatalogueService.compatibility_entry(upper), (upper, lower))
    _complete(service, 1, upper)
    service.request_failed.emit("association-3", SimpleNamespace(message="Missing lower material"))
    assert failures == ["Missing lower material"] and not ready and not preparation.pending
    assert preparation.start(ArchiveCatalogueService.compatibility_entry(upper), (upper, lower))
    service.session_published.emit(SimpleNamespace(session_id="new-session"))
    assert len(failures) == 2 and not preparation.pending
    assert not preparation.start(ArchiveCatalogueService.compatibility_entry(upper),
        (upper, replace(lower, session_id="other-session")))


def test_set_editor_preparation_does_not_outlive_its_owner():
    app = _app()
    service = _Service()
    owner = QObject()
    preparation = ItemSetEditorPreparation(service, owner)
    upper = _dto(1, "upper.pac")
    ready = []
    preparation.ready.connect(ready.append)
    assert preparation.start(ArchiveCatalogueService.compatibility_entry(upper), (upper,))
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(owner, QEvent.DeferredDelete)
    _complete(service, 1, upper)
    app.processEvents()
    assert service.cancelled == ["association-1"] and not ready


@pytest.mark.parametrize("close", ["close_standalone_session", "request_shutdown"])
def test_editor_close_cancels_pending_set_and_ignores_late_results(tmp_path, close):
    from tests.test_mesh_rust_editor_selection import _tab
    app = _app()
    tab = _tab(tmp_path)
    service = _Service()
    tab.item_set_preparation = ItemSetEditorPreparation(service, tab)
    ready = []
    tab.item_set_preparation.ready.connect(ready.append)
    upper = _dto(1, "upper.pac")
    tab.item_set_preparation.start(ArchiveCatalogueService.compatibility_entry(upper), (upper,))
    getattr(tab, close)()
    _complete(service, 1, upper)
    app.processEvents()
    assert service.cancelled == ["association-1"] and not ready
    tab.deleteLater()


def test_switch_uses_captured_context_and_existing_close_confirmation(tmp_path):
    from cdmw.ui.mesh_editor.item_set_preparation import switch_item_piece
    from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin
    from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
    from tests.test_mesh_rust_editor_selection import _tab
    app = _app()
    tab = _tab(tmp_path)
    entries = tuple(ArchiveCatalogueService.compatibility_entry(_dto(i, f"piece-{i}.pac")) for i in (1, 2))
    contexts = tuple(ArchiveWorkflowDependencyContext(e, (e,), {e.path: e}, {e.basename: (e,)}, True) for e in entries)
    tab.item_set_contexts = contexts
    confirmations = []
    class Shell:
        mesh_editor_tab = tab
        _shutting_down = False
        _open_archive_mesh_editor_with_dependencies = MeshEditorShellBridgeMixin._open_archive_mesh_editor_with_dependencies
        def _prepare_mesh_editor_archive_launch(self, entry):
            confirmations.append(entry)
            return False
    switch_item_piece(Shell(), 1)
    assert confirmations == [entries[1]]
    assert tab.item_set_contexts == contexts  # Declining preserves the existing session.
    switch_item_piece(Shell(), -1)
    assert confirmations == [entries[1]]
    tab.deleteLater()
    app.processEvents()


def test_set_context_survives_queued_editor_close(tmp_path):
    from tests.test_mesh_rust_editor_selection import _tab
    from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
    app = _app()
    tab = _tab(tmp_path)
    entry = ArchiveCatalogueService.compatibility_entry(_dto(1, "piece.pac"))
    context = ArchiveWorkflowDependencyContext(entry, (entry,), {entry.path: entry}, {entry.basename: (entry,)}, True)
    with patch.object(tab, "close_standalone_session", return_value=False):
        tab.open_archive_session(entry, archive_dependencies=context, item_set_contexts=(context,))
    assert tab.archive_session_open_pending["item_set_contexts"] == (context,)
    with patch.object(tab, "_start_archive_session_load_when_indexes_ready"):
        tab._resume_queued_archive_session_open()
    assert tab.item_set_contexts == (context,)
    tab.close_standalone_session()
    assert tab.item_set_contexts == ()
    tab.deleteLater()
    app.processEvents()


def test_reference_switch_event_is_bounded_to_the_current_idle_session(tmp_path):
    from tests.test_mesh_rust_editor_selection import _tab
    from cdmw.services.mesh_rust_contract import RUST_MESH_EDITOR_PROTOCOL
    app = _app()
    tab = _tab(tmp_path)
    tab.item_set_contexts = (object(), object())
    tab.standalone_rust_authoring_session = SimpleNamespace(session_id="owned")
    tab.standalone_rust_process_generation = 9
    tab.standalone_rust_ready = True
    switched = []
    tab.switch_item_piece_requested.connect(switched.append)
    event = {"event": "switch_item_piece", "protocol": RUST_MESH_EDITOR_PROTOCOL,
             "session_id": "owned", "process_generation": 9, "index": 1}
    for index in (-1, 0, 2, True, "1"):
        tab._handle_rust_protocol_event({**event, "index": index})
    assert not switched
    tab.standalone_rust_protocol_queue = [{"event": "command_request"}]
    tab._handle_rust_protocol_event(event)
    assert not switched
    tab.standalone_rust_protocol_queue.clear()
    tab._handle_rust_protocol_event(event)
    assert switched == [1]
    with patch.object(tab, "_fail_rust_editor") as failure:
        tab._handle_rust_protocol_event({**event, "process_generation": 8})
    failure.assert_called_once()
    assert switched == [1]
    tab.standalone_rust_authoring_session = None
    tab.deleteLater()
    app.processEvents()


def test_set_editor_does_not_borrow_combined_browser_material_owners(tmp_path):
    from tests.test_mesh_rust_archive_texture_launch import _entry, _package, _LaunchHarness
    from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
    entry = _entry(tmp_path, "upper.pac")
    shell = _LaunchHarness(entry, _package(tmp_path / "combined", entry, textured=True))
    context = ArchiveWorkflowDependencyContext(entry, (entry,), {entry.path: entry}, {entry.basename: (entry,)}, True)
    shell._open_archive_mesh_editor_with_dependencies(entry, context, item_set_contexts=(context,))
    _, arguments = shell.opened[0]
    assert arguments["item_set_contexts"] == (context,)
    assert arguments["archive_dependencies"] is context
    assert arguments["material_package_path"] == ""
    assert arguments["material_preview_model"] is None
    assert not arguments["material_context_verified_for_rust"]
