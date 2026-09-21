from dataclasses import replace
from types import SimpleNamespace
import threading

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import ArchiveAssociationResult, ArchiveLookupResult
from cdmw.domain.archives.catalogue_operations import PrepareEntriesResult
from cdmw.domain.cancellation import RunCancelled
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.new_item.template_preview_dependencies import TemplatePreviewDependencies
from tests.test_archive_remote_preview_dependencies import _CatalogueService, _dto, _prepared
from tests.test_new_item_template_authoring import _events_until


def setup():
    service = _CatalogueService()
    service.current_session = SimpleNamespace(session_id="session-a", fingerprint="revision-a")
    preparer = TemplatePreviewDependencies(service)
    model = _dto(7, "character/model/sword.pac")
    return service, preparer, model, ArchiveCatalogueService.compatibility_entry(model)


def resolve(service, model, *others):
    service.result_ready.emit(f"resolve-{len(service.requests)}", "resolve_entries",
                             ArchiveLookupResult("session-a", (model, *others), 1 + len(others), False))


def complete(service, model):
    sidecar = _dto(8, "character/modelproperty/sword.pac_xml")
    texture = _dto(9, "character/texture/sword_d.dds")
    service.result_ready.emit(f"association-{len(service.requests)}", "find_association_candidates",
                             ArchiveAssociationResult("session-a", model.entry_id, (sidecar, texture), 2, False))
    assert service.requests[-1][0].content_analysis_entry_id is None
    service.result_ready.emit(f"prepare-{len(service.requests)}", "prepare_entry",
                             PrepareEntriesResult("session-a", tuple(_prepared(dto) for dto in (model, sidecar, texture)), 3, 3, 120))


def test_template_dependency_wait_keeps_gui_alive_and_reuses_complete_archive_inputs():
    app = QApplication.instance() or QApplication([])
    service, preparer, model, entry = setup()
    ticket = preparer.capture((entry,), ())
    assert preparer.capture((entry,), ()) is ticket
    results, ticks = [], []
    worker = threading.Thread(target=lambda: results.append(ticket.wait(threading.Event())))
    timer = QTimer()
    timer.setInterval(1)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    worker.start()
    try:
        _events_until(app, lambda: len(ticks) >= 4)
        assert worker.is_alive()
        resolve(service, model)
        complete(service, model)
        _events_until(app, lambda: not worker.is_alive())
        assert [entry.path for entry in results[0]] == [model.path, "character/modelproperty/sword.pac_xml", "character/texture/sword_d.dds"]
        assert all(entry.prepared_path and entry.prepared_sha256 for entry in results[0])
        count = len(service.requests)
        assert preparer.capture((entry,), ()) is ticket
        assert len(service.requests) == count
    finally:
        timer.stop()
        preparer.shutdown()
        worker.join(1)


@pytest.mark.parametrize("outcome", ["superseded", "shutdown", "truncated", "wrong_source", "changed_session"])
def test_template_dependencies_reject_stale_or_incomplete_inputs(outcome):
    app = QApplication.instance() or QApplication([])
    service, preparer, model, entry = setup()
    ticket = preparer.capture((entry,), ())
    if outcome == "superseded":
        next_entry = ArchiveCatalogueService.compatibility_entry(_dto(10, "other.pac"))
        preparer.capture((next_entry,), ())
        assert "resolve-1" in service.cancelled
        service.result_ready.emit("resolve-1", "resolve_entries", ArchiveLookupResult("session-a", (model,), 1, False))
    elif outcome == "shutdown":
        preparer.shutdown()
    elif outcome == "wrong_source":
        resolve(service, replace(model, offset=model.offset + 1))
    else:
        resolve(service, model)
        if outcome == "truncated":
            service.result_ready.emit("association-2", "find_association_candidates",
                                     ArchiveAssociationResult("session-a", model.entry_id, (), 1, True))
        else:
            service.current_session = SimpleNamespace(session_id="session-b", fingerprint="revision-b")
            complete(service, model)
    assert ticket.done.is_set()
    assert not ticket.entries
    with pytest.raises(Exception):
        ticket.wait(threading.Event())
    preparer.shutdown()


def test_cancelled_preview_worker_never_consumes_prepared_texture_inputs():
    app = QApplication.instance() or QApplication([])
    service, preparer, model, entry = setup()
    ticket = preparer.capture((entry,), ())
    resolve(service, model)
    complete(service, model)
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        ticket.wait(stop)
    preparer.shutdown()


def test_new_item_caller_supplies_prepared_complete_inputs_to_native_preview(tmp_path, monkeypatch):
    from cdmw.services import preview_rendering_service
    from cdmw.ui.new_item.tab import NewItemStudioTab

    app = QApplication.instance() or QApplication([])
    service, unused, model, entry = setup()
    unused.shutdown()
    tab = NewItemStudioTab(window=SimpleNamespace(archive=SimpleNamespace(archive_catalogue_service=service)))
    controller = tab.controller
    controller.snapshot = SimpleNamespace(payload=lambda _: pytest.fail("must use prepared input"))
    controller.draft.template_key = 17
    monkeypatch.setattr(controller, "template_entries", lambda: (entry,))
    monkeypatch.setattr(controller, "template_primary_entry", lambda: entry)
    monkeypatch.setattr(controller, "template_prefab_entries", lambda: ())
    calls = []

    def native_job(selected, **kwargs):
        calls.append((selected, kwargs))
        output = kwargs["output_root"]
        output.mkdir(parents=True)
        return SimpleNamespace(succeeded=True, package_path=output)

    monkeypatch.setattr(preview_rendering_service, "run_native_preview_core_preview_job", native_job)
    try:
        _token, build = controller._template_preview_build()
        resolve(service, model)
        complete(service, model)
        result = build(threading.Event(), output_root=tmp_path / "output",
                       native_preview_core_cache_root=tmp_path / "native", cache_mode="off",
                       consume_native_package=lambda _: "consumed")
        assert result == "consumed"
        selected, kwargs = calls[0]
        assert selected.prepared_sha256 == "sha-7"
        assert kwargs["dependency_entries_complete"] is True
        assert len(kwargs["dependency_entries"]) == 3
        assert kwargs["render_settings"].use_textures_by_default
    finally:
        tab.shutdown()


def test_template_prepares_each_component_and_keeps_selected_prefab_first():
    app = QApplication.instance() or QApplication([])
    service, preparer, model, entry = setup()
    second = _dto(10, "character/model/scabbard.pac")
    prefab = _dto(11, "character/item_variant.prefab")
    convert = ArchiveCatalogueService.compatibility_entry
    ticket = preparer.capture((entry, convert(second)), (convert(prefab),))
    resolve(service, model, second, prefab)
    for selected in (model, second):
        resolve(service, prefab)  # Exact preferred prefab scope before associations.
        texture = _dto(selected.entry_id + 20, f"character/texture/{selected.entry_id}.dds")
        service.result_ready.emit(f"association-{len(service.requests)}", "find_association_candidates",
                                 ArchiveAssociationResult("session-a", selected.entry_id, (texture,), 1, False))
        requested = service.requests[-1][0]
        assert requested.entry_ids == (selected.entry_id, prefab.entry_id, texture.entry_id)
        service.result_ready.emit(f"prepare-{len(service.requests)}", "prepare_entry",
                                 PrepareEntriesResult("session-a", tuple(_prepared(dto) for dto in (selected, prefab, texture)), 3, 3, 120))
    assert ticket.done.is_set() and ticket.error is None
    assert [item.path for item in ticket.entries] == [model.path, prefab.path, "character/texture/7.dds", second.path, "character/texture/10.dds"]
    preparer.shutdown()


def test_shutdown_releases_texture_waiters_after_archive_service_closes(monkeypatch):
    app = QApplication.instance() or QApplication([])
    service, preparer, _model, entry = setup()
    ticket = preparer.capture((entry,), ())

    def closed(_request):
        raise RuntimeError("archive process closed")

    monkeypatch.setattr(service, "cancel", closed)
    preparer.shutdown()
    assert ticket.done.is_set()
    with pytest.raises(RunCancelled):
        ticket.wait(threading.Event())
