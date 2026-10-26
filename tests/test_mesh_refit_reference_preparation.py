from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.catalogue import (
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRef,
    ArchiveEntryRole,
    ArchivePage,
    ArchiveQueryHandle,
)
from cdmw.domain.archives.catalogue_operations import (
    PrepareEntriesResult,
    PrepareEntryResult,
)
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_refit_reference_lookup import PreparedRefitReferenceArchive
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependencyContext,
)
from cdmw.ui.mesh_editor import refit_reference_preparation as preparation

OUTFIT = "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_01_phm/armor_desert/9_upperbody/cd_m0001_00_de_phm_ub_11002.pac"
DRIVER = "character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_0001_damian.pac"
PHM_PAB = "character/model/1_pc/1_phm/phm_01.pab"
PHW_PAB = "character/model/1_pc/2_phw/phw_01.pab"
PHM_NUDE = "character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac"


class _Service(QObject):
    result_ready = Signal(str, str, object)
    batch_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)
    session_published = Signal(object)

    def __init__(self):
        super().__init__()
        self.current_session = SimpleNamespace(session_id="s1")
        self._minimum_ui_generation = 7
        self.calls = []

    def _record(self, name, request, ui_generation):
        self.calls.append((name, request, ui_generation))
        return f"{name}-{len(self.calls)}"

    def create_query(self, query, *, ui_generation):
        return self._record("create_query", query, ui_generation)

    def fetch_page(self, request, *, ui_generation):
        return self._record("fetch_page", request, ui_generation)

    def prepare_entries(self, request, *, ui_generation):
        return self._record("prepare_entries", request, ui_generation)

    def cancel(self, request):
        self.calls.append(("cancel", request, None))
        return True


def _entry(path):
    return ArchiveEntry(path, Path("0009/0.pamt"), Path("0009/0.paz"), len(path), 10, 10, 0, 0)


def _set(*paths):
    entries = tuple(_entry(path) for path in paths)
    return ArchiveWorkflowDependencyContext(
        entries[0], entries, {path: (entry,) for path, entry in zip(paths, entries)},
        {entry.basename: (entry,) for entry in entries}, True)


def _dto(entry_id, path):
    return ArchiveEntryDto(
        "s1", entry_id, ArchiveDurableIdentity(path, "0009/0.pamt", 0, entry_id), path, "0009/0.pamt",
        "0009/0.paz", 0, entry_id, 10, 10, 0, ".pac", "0009", ArchiveEntryRole.MODEL, "model", True)


def _start():
    service = _Service()
    prepared = preparation.RefitReferencePreparation(service)
    ticket = prepared.capture((_set(OUTFIT, PHM_PAB), None, _set(DRIVER, PHW_PAB)))
    return service, prepared, ticket


def test_the_nude_body_of_each_rig_is_listed_prepared_and_merged_for_the_fit():
    service, _prepared, ticket = _start()
    name, query, generation = service.calls[0]
    assert name == "create_query" and generation == 7 and query.extensions == (".pac",)
    assert query.include_text == "character/model/1_pc/1_phm/nude/*.pac;character/model/1_pc/2_phw/nude/*.pac"
    service.result_ready.emit("create_query-1", "create_query", ArchiveQueryHandle("s1", "q", 1, 3))
    assert service.calls[1][0] == "fetch_page" and service.calls[1][1].page_size == 3
    rows = (_dto(1, PHM_NUDE), _dto(2, "character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001_lod_1.pac"),
            _dto(3, DRIVER))
    service.result_ready.emit("fetch_page-2", "fetch_page", ArchivePage("s1", "q", 1, 3, 0, rows))
    # Each rig's chooser answer is prepared once; lower details are not.
    request = service.calls[2][1]
    assert service.calls[2][0] == "prepare_entries" and sorted(request.entry_ids) == [1, 3]
    assert not ticket.done.is_set()
    items = tuple(PrepareEntryResult(ArchiveEntryRef("s1", entry_id, row.identity, row.path), f"prepared/{entry_id}", 10, "AB")
                  for entry_id, row in ((1, rows[0]), (3, rows[2])))
    # Like the worker: prepared files arrive as batches, then an empty final result.
    service.batch_ready.emit("prepare_entries-3", "prepare_entries", PrepareEntriesResult("s1", items[:1], 2, 2, 20))
    service.batch_ready.emit("prepare_entries-3", "prepare_entries", PrepareEntriesResult("s1", items[1:], 2, 2, 20))
    assert not ticket.done.is_set()
    service.result_ready.emit("prepare_entries-3", "prepare_entries", PrepareEntriesResult("s1", (), 2, 2, 20))
    archive = ticket.wait()
    assert archive.reason == ""
    body = archive.dependencies.entry_for_path(PHM_NUDE)
    assert body.prepared_path == Path("prepared/1")
    assert archive.dependencies.entry_for_path(PHM_PAB) is not None
    assert archive.dependencies.entry_for_path(OUTFIT) is not None


def test_an_unchanged_archive_reuses_the_prepared_set():
    service, prepared, ticket = _start()
    service.result_ready.emit("create_query-1", "create_query", ArchiveQueryHandle("s1", "q", 1, 1))
    service.result_ready.emit("fetch_page-2", "fetch_page", ArchivePage("s1", "q", 1, 1, 0, (_dto(1, PHM_NUDE),)))
    row = _dto(1, PHM_NUDE)
    service.result_ready.emit("prepare_entries-3", "prepare_entries", PrepareEntriesResult(
        "s1", (PrepareEntryResult(ArchiveEntryRef("s1", 1, row.identity, PHM_NUDE), "prepared/1", 10, "AB"),), 1, 1, 10))
    first = ticket.wait().dependencies
    again = prepared.capture((_set(OUTFIT, PHM_PAB), _set(DRIVER, PHW_PAB)))
    assert again.wait().dependencies is first and len(service.calls) == 3


def test_failures_finish_the_ticket_with_a_reason_instead_of_holding_the_fit():
    service, _prepared, ticket = _start()
    service.request_failed.emit("create_query-1", SimpleNamespace(message="worker stopped"))
    assert ticket.wait().reason == "the archive worker could not list the authored bodies (worker stopped)"
    service, _prepared, ticket = _start()
    service.result_ready.emit("create_query-1", "create_query", ArchiveQueryHandle("s1", "q", 1, 0))
    assert "no nude body was found in the archive for 1_phm, 2_phw" in ticket.wait().reason
    service, _prepared, ticket = _start()
    service.result_ready.emit("create_query-1", "create_query", ArchiveQueryHandle("s1", "q", 1, 1))
    service.result_ready.emit("fetch_page-2", "fetch_page", ArchivePage("s1", "q", 1, 1, 0, (_dto(1, PHM_NUDE),)))
    service.result_ready.emit("prepare_entries-3", "prepare_entries", PrepareEntriesResult("s1", (), 1, 0, 0))
    assert ticket.wait().reason == "the archive worker did not prepare the authored bodies"
    service, _prepared, ticket = _start()
    service.session_published.emit(object())
    assert ticket.wait().reason == "the archive catalogue changed during the Fit"
    assert service.calls[-1] == ("cancel", "create_query-1", None)


def test_local_or_missing_archive_sets_need_no_preparation():
    service = _Service()
    local = _set(DRIVER, PHW_PAB)
    object.__setattr__(local, "remote", False)
    ticket = preparation.RefitReferencePreparation(service).capture((None, local))
    assert ticket.wait() == PreparedRefitReferenceArchive().archive and service.calls == []


def test_the_fit_event_carries_a_ticket_only_for_archive_refit_with_the_authored_body():
    context = SimpleNamespace(assets=(SimpleNamespace(preview_lease=SimpleNamespace(
        archive_dependencies=_set(DRIVER, PHW_PAB))),))
    shadow = SimpleNamespace(archive_refit_context=context)
    session = SimpleNamespace(shadow_service=SimpleNamespace(_session=lambda _sid: shadow), shadow_session_id="x")
    service = _Service()

    class _Tab(QObject):
        archive_session_dependencies = _set(OUTFIT, PHM_PAB)

        def window(self):
            return SimpleNamespace(archive=SimpleNamespace(archive_catalogue_service=service))

    tab = _Tab()
    event = {"command": "refit_fit_to_body", "arguments": {}}
    prepared = preparation.prepare_refit_fit_event(tab, session, event)
    assert isinstance(prepared["arguments"]["_reference_archive"], PreparedRefitReferenceArchive)
    assert service.calls[0][0] == "create_query"
    off = {"command": "refit_fit_to_body", "arguments": {"reference_body": False}}
    assert preparation.prepare_refit_fit_event(tab, session, off) is off
    shadow.archive_refit_context = None
    assert preparation.prepare_refit_fit_event(tab, session, event) is event
