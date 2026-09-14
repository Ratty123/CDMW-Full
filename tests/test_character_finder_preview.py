from __future__ import annotations

from dataclasses import asdict, replace
import json
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import ArchiveLookupResult
from cdmw.domain.archives.catalogue_operations import PrepareEntriesResult
from cdmw.domain.archives.character_catalogue import CharacterCatalogFile, CharacterCatalogComponent
from cdmw.domain.character_finder import CharacterRenderResult, character_preview_detail
from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.character_finder import preview_controller as module
from cdmw.ui.character_finder.preview_preparation import CharacterPreviewPreparation
from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet
from cdmw.workers.character_finder_workers import CharacterFinderRenderWorker, character_render_key, cached_character_render
from cdmw.workers.character_finder_workers import cached_character_package, cached_character_row, character_row_cache_root
from tests.test_character_finder_dialog import row, detail
from tests.test_archive_remote_preview_dependencies import _CatalogueService, _dto, _prepared


_APP = None


def wait_for(predicate, timeout=3):
    until = time.monotonic() + timeout
    while not predicate() and time.monotonic() < until:
        _APP.processEvents()
        time.sleep(.001)
    assert predicate(), "Qt operation did not complete within the focused test deadline"


class Service(_CatalogueService):
    def get_character_catalog_detail(self, request, **kw):
        self.requests.append((request, kw))
        return f"detail-{len(self.requests)}"


class Preparation(QObject):
    ready = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, service, parent):
        super().__init__(parent)

    def cancel(self): pass
    def start(self, selected, token): self.ready.emit(token, selected)


@pytest.fixture
def controller(monkeypatch, tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    service = Service()
    monkeypatch.setattr(module, "CharacterPreviewPreparation", Preparation)
    controller = module._CharacterPreviewLane(service, fingerprint="fp", cache_root=tmp_path,
        settings=ModelPreviewRenderSettings())
    yield controller, service
    controller.shutdown()
    wait_for(lambda: not controller.busy)
    controller.deleteLater()
    _APP.processEvents()


def test_parallel_page_continues_without_scroll_and_preserves_selection_priority(monkeypatch, tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module.os, "cpu_count", lambda: 8)
    service = Service()
    original_detail = service.get_character_catalog_detail
    def get_detail(request, **kw):
        token = original_detail(request, **kw)
        selected = detail(row(int(request.key.split(":")[-1])))
        QTimer.singleShot(0, lambda: service.result_ready.emit(token, "get_character_catalog_detail", selected))
        return token
    service.get_character_catalog_detail = get_detail
    monkeypatch.setattr(module, "CharacterPreviewPreparation", Preparation)
    monkeypatch.setattr(module, "cached_character_render", lambda *_: None)
    jobs, delivered, packages = [], [], []
    release = threading.Event()

    class Worker(QObject):
        package_ready = Signal(int, object)
        completed = Signal(int, object)
        failed = Signal(int, str)
        finished = Signal()
        def __init__(self, token, selected, **kw):
            super().__init__()
            self.token, self.selected = token, selected
            self.stopped = threading.Event()
            jobs.append(self)
        def stop(self): self.stopped.set()
        def run(self):
            try:
                while not release.wait(.005):
                    if self.stopped.is_set(): return
                result = CharacterRenderResult(self.selected.row.key, "package", "thumbnail", "base_appearance", ())
                self.package_ready.emit(self.token, result)
                self.completed.emit(self.token, result)
            finally:
                self.finished.emit()

    monkeypatch.setattr(module, "CharacterFinderRenderWorker", Worker)
    owner = module.CharacterFinderPreviewController(service, fingerprint="fp", cache_root=tmp_path,
        settings=ModelPreviewRenderSettings())
    owner.thumbnail_ready.connect(lambda key, _: delivered.append(key))
    owner.package_ready.connect(lambda key, _: packages.append(key))
    try:
        owner.visible([row(i) for i in range(9)], session_id="session-a", generation=1)
        wait_for(lambda: len(jobs) == 4)
        assert sum(kind != "character_finder_cache" for kind, *_ in owner.iter_shutdown_workers()) == 4
        owner.visible([row(i) for i in reversed(range(9))], session_id="session-a", generation=1)
        QTest.qWait(25)
        assert len(jobs) == 4 and not any(job.stopped.is_set() for job in jobs)
        owner.select(detail(row(99)), 2)
        wait_for(lambda: len(jobs) == 5)
        assert sum(job.stopped.is_set() for job in jobs[:4]) == 1
        assert jobs[-1].selected.row.key == "asset:99"
        release.set()
        wait_for(lambda: len(set(delivered)) == 10 and not owner.busy)
        assert packages == ["asset:99"]
        assert len(delivered) == 10
    finally:
        owner.shutdown()
        release.set()
        wait_for(lambda: not owner.busy)
        owner.deleteLater()
        _APP.processEvents()


@pytest.fixture
def page_scheduler(monkeypatch, tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    service = Service()
    original = service.get_character_catalog_detail
    def get_detail(request, **kwargs):
        token = original(request, **kwargs)
        selected = detail(row(int(request.key.split(":")[-1])))
        QTimer.singleShot(0, lambda: service.result_ready.emit(token, "detail", selected))
        return token
    service.get_character_catalog_detail = get_detail
    monkeypatch.setattr(module, "CharacterPreviewPreparation", Preparation)
    monkeypatch.setattr(module, "cached_character_render", lambda *_: None)
    jobs = []
    class Worker(QObject):
        package_ready = Signal(int, object)
        completed = Signal(int, object)
        failed = Signal(int, str)
        finished = Signal()
        def __init__(self, token, selected, **kwargs):
            super().__init__()
            self.token, self.selected = token, selected
            self.release, self.stopped = threading.Event(), threading.Event()
            jobs.append(self)
        def stop(self): self.stopped.set()
        def run(self):
            try:
                while not self.release.wait(.005):
                    if self.stopped.is_set(): return
                result = CharacterRenderResult(self.selected.row.key, "package", "thumbnail", "base_appearance", ())
                self.package_ready.emit(self.token, result)
                self.completed.emit(self.token, result)
            finally:
                self.finished.emit()
    monkeypatch.setattr(module, "CharacterFinderRenderWorker", Worker)
    owner = module.CharacterFinderPreviewController(service, fingerprint="fp", cache_root=tmp_path,
        settings=ModelPreviewRenderSettings(), max_lanes=2)
    yield owner, jobs
    owner.shutdown()
    for job in jobs:
        job.release.set()
    wait_for(lambda: not owner.busy)
    owner.deleteLater()
    _APP.processEvents()


def test_scheduling_pause_finishes_active_startup_jobs_without_starting_more(page_scheduler):
    owner, jobs = page_scheduler
    owner.visible([row(i) for i in range(4)], session_id="session-a", generation=1)
    wait_for(lambda: len(jobs) == 2)
    owner.pause_scheduling()
    for job in jobs:
        job.release.set()
    wait_for(lambda: not owner.busy)
    QTest.qWait(25)
    assert len(jobs) == 2 and not any(job.stopped.is_set() for job in jobs)
    assert not owner.page_complete
    owner.resume_scheduling()
    wait_for(lambda: len(jobs) == 4)
    for job in jobs:
        job.release.set()
    wait_for(lambda: owner.page_complete)


def test_prefetch_runs_one_job_after_visible_cards_and_promotes_it_on_next_page(page_scheduler):
    owner, jobs = page_scheduler
    packages = []
    owner.package_ready.connect(lambda key, _: packages.append(key))
    owner.visible([row(1), row(2)], session_id="session-a", generation=1)
    owner.prefetch([row(3), row(4), row(5)], session_id="session-a", generation=1)
    wait_for(lambda: len(jobs) == 2)
    QTest.qWait(25)
    assert {job.selected.row.key for job in jobs} == {"asset:1", "asset:2"}
    for job in jobs:
        job.release.set()
    wait_for(lambda: len(jobs) == 3)
    QTest.qWait(25)
    assert len(jobs) == 3 and jobs[2].selected.row.key == "asset:3"
    assert not packages  # Preloading never swaps the selected interactive scene.
    owner.visible([row(3), row(4), row(5)], session_id="session-a", generation=1)
    owner.prefetch([], session_id="session-a", generation=1)
    owner.select(detail(row(3)), 1)
    wait_for(lambda: len(jobs) == 4)
    assert not jobs[2].stopped.is_set()
    assert jobs[3].selected.row.key == "asset:4"
    for job in jobs:
        job.release.set()
    wait_for(lambda: len(jobs) == 5)
    jobs[-1].release.set()
    wait_for(lambda: owner.page_complete)
    assert [job.selected.row.key for job in jobs].count("asset:3") == 1
    assert packages == ["asset:3"]


def test_prefetch_yields_to_a_new_selection_and_rejects_obsolete_pages(page_scheduler):
    owner, jobs = page_scheduler
    owner.visible([row(1)], session_id="session-a", generation=1)
    owner.prefetch([row(2), row(3)], session_id="session-a", generation=1)
    wait_for(lambda: len(jobs) == 1)
    jobs[0].release.set()
    wait_for(lambda: len(jobs) == 2)
    assert jobs[-1].selected.row.key == "asset:2"
    owner.select(detail(row(1)), 1)
    wait_for(lambda: len(jobs) == 3)
    assert jobs[1].stopped.is_set() and jobs[-1].selected.row.key == "asset:1"
    QTest.qWait(25)
    assert len(jobs) == 3
    owner.clear_page()
    owner.visible([row(7)], session_id="session-a", generation=2)
    owner.prefetch([row(8)], session_id="session-a", generation=1)
    assert not owner._prefetch_rows
    wait_for(lambda: len(jobs) == 4)
    jobs[-1].release.set()
    wait_for(lambda: owner.page_complete)
    assert jobs[-1].selected.row.key == "asset:7"


def test_revisited_page_without_row_index_can_reload_its_exact_cache(monkeypatch, tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    service = Service()
    original = service.get_character_catalog_detail
    selected = detail(row(1))
    result = CharacterRenderResult("cache", "package", "thumbnail", "base_appearance", ())
    def get_detail(request, **kwargs):
        token = original(request, **kwargs)
        QTimer.singleShot(0, lambda: service.result_ready.emit(token, "get_character_catalog_detail", selected))
        return token
    service.get_character_catalog_detail = get_detail
    monkeypatch.setattr(module, "cached_character_row", lambda *_: None)
    monkeypatch.setattr(module, "cached_character_render", lambda *_: result)
    owner = module.CharacterFinderPreviewController(service, fingerprint="fp", cache_root=tmp_path,
        settings=ModelPreviewRenderSettings())
    delivered = []
    owner.thumbnail_ready.connect(lambda key, _: delivered.append(key))
    try:
        owner._done.add(selected.row.key)
        owner.visible([selected.row], session_id="session-a", generation=1)
        wait_for(lambda: delivered == [selected.row.key] and not owner.busy)
        assert len(service.requests) == 1
        assert owner.cached_detail(selected.row.key, selected.session_id) is selected
        owner.clear_page()
        owner.visible([selected.row], session_id="session-a", generation=1)
        wait_for(lambda: len(delivered) == 2 and not owner.busy)
        assert len(service.requests) == 1  # Revisit reuses the original full detail.
    finally:
        owner.shutdown()
        wait_for(lambda: not owner.busy)
        owner.deleteLater()
        _APP.processEvents()


def test_revisited_thumbnail_records_use_memory_and_recover_after_eviction_or_rescan(page_scheduler, monkeypatch, tmp_path):
    owner, jobs = page_scheduler
    images = {f"asset:{i}": tmp_path / f"thumb-{i}.png" for i in (1, 2)}
    for path in images.values():
        path.write_bytes(b"fixture")
    lookups, file_checks, delivered = [], [], []
    owner.thumbnail_ready.connect(lambda key, _: delivered.append(key))
    gui_thread = threading.get_ident()
    original_is_file = type(tmp_path).is_file
    def is_file(path):
        if path in images.values():
            file_checks.append(threading.get_ident())
        return original_is_file(path)
    monkeypatch.setattr(type(tmp_path), "is_file", is_file)
    def lookup(_root, _rows, key):
        lookups.append(key)
        path = images[key]
        if path.exists():
            return CharacterRenderResult(key, "package", str(path), "base_appearance", (), True)
        return None
    monkeypatch.setattr(module, "cached_character_row", lookup)
    rows = [row(1), row(2)]
    owner.visible(rows, session_id="session-a", generation=1)
    wait_for(lambda: len(delivered) == 2 and owner.page_complete)
    assert lookups == ["asset:1", "asset:2"] and not jobs
    owner.clear_page()
    owner.visible(rows, session_id="session-a", generation=2)
    wait_for(lambda: len(delivered) == 4 and owner.page_complete)
    assert lookups == ["asset:1", "asset:2"]  # No repeated row/thumbnail JSON reads.
    assert file_checks and gui_thread not in file_checks
    images["asset:2"].unlink()
    owner.clear_page()
    owner.visible(rows, session_id="session-a", generation=2)
    wait_for(lambda: len(jobs) == 1)
    assert lookups == ["asset:1", "asset:2", "asset:2"]
    assert jobs[0].selected.row.key == "asset:2"
    jobs[0].release.set()
    wait_for(lambda: len(delivered) == 6 and owner.page_complete)
    owner.clear_page()
    owner.visible([row(1)], session_id="session-b", generation=3)
    wait_for(lambda: len(delivered) == 7 and owner.page_complete)
    assert lookups == ["asset:1", "asset:2", "asset:2", "asset:1"]


def test_detail_memory_is_bounded_and_scoped_to_the_archive_session(tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    owner = module.CharacterFinderPreviewController(Service(), fingerprint="fp", cache_root=tmp_path,
        settings=ModelPreviewRenderSettings())
    try:
        for index in range(144):
            owner._remember_detail(detail(row(index)))
        assert owner.cached_detail("asset:0", "session-a") is not None
        owner._remember_detail(detail(row(144)))
        assert len(owner._details) == 144
        assert owner.cached_detail("asset:1", "session-a") is None
        assert owner.cached_detail("asset:0", "session-a") is not None
        assert owner.cached_detail("asset:0", "different-session") is None
    finally:
        owner.shutdown()
        owner.deleteLater()
        _APP.processEvents()


def test_selecting_a_running_card_reuses_its_package_without_restarting(monkeypatch, tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    service = Service()
    original = service.get_character_catalog_detail
    def get_detail(request, **kwargs):
        token = original(request, **kwargs)
        selected = detail(row(int(request.key.split(":")[-1])))
        QTimer.singleShot(0, lambda: service.result_ready.emit(token, "detail", selected))
        return token
    service.get_character_catalog_detail = get_detail
    monkeypatch.setattr(module, "CharacterPreviewPreparation", Preparation)
    monkeypatch.setattr(module, "cached_character_render", lambda *_: None)
    jobs, packages = [], []
    release = threading.Event()

    class Worker(QObject):
        package_ready = Signal(int, object)
        completed = Signal(int, object)
        failed = Signal(int, str)
        finished = Signal()
        def __init__(self, token, selected, **kwargs):
            super().__init__()
            self.token, self.selected = token, selected
            self.stopped = threading.Event()
            jobs.append(self)
        def stop(self): self.stopped.set()
        def run(self):
            try:
                result = CharacterRenderResult(self.selected.row.key, "package", "thumbnail", "base_appearance", ())
                self.package_ready.emit(self.token, result)
                while not release.wait(.005):
                    if self.stopped.is_set(): return
                self.completed.emit(self.token, result)
            finally:
                self.finished.emit()

    monkeypatch.setattr(module, "CharacterFinderRenderWorker", Worker)
    owner = module.CharacterFinderPreviewController(service, fingerprint="fp", cache_root=tmp_path,
        settings=ModelPreviewRenderSettings(), max_lanes=2)
    owner.package_ready.connect(lambda key, result: packages.append((key, result)))
    try:
        owner.visible([row(1), row(2)], session_id="session-a", generation=1)
        wait_for(lambda: len(jobs) == 2 and all(lane._active_package for lane in owner._lanes))
        assert not packages
        owner.select(detail(row(2)), 1)
        assert packages[-1][0] == "asset:2"
        owner.select(detail(row(1)), 1)
        assert [key for key, _ in packages] == ["asset:2", "asset:1"]
        assert len(jobs) == 2 and not any(job.stopped.is_set() for job in jobs)
        release.set()
        wait_for(lambda: owner.page_complete)
    finally:
        release.set()
        owner.shutdown()
        wait_for(lambda: not owner.busy)
        owner.deleteLater()
        _APP.processEvents()


@pytest.mark.parametrize("prefetch", [False, True])
def test_uncached_cards_render_while_later_page_cache_lookups_are_blocked(page_scheduler, monkeypatch, prefetch):
    owner, jobs = page_scheduler
    blocked, release = threading.Event(), threading.Event()
    cached = CharacterRenderResult("cache", "package", "thumbnail", "base_appearance", ())
    def lookup(_root, _rows, key):
        if key == "asset:3":
            blocked.set()
            release.wait(10)
            return cached
        return None
    monkeypatch.setattr(module, "cached_character_row", lookup)
    if prefetch:
        owner.visible([row(0)], session_id="session-a", generation=1)
        wait_for(lambda: len(jobs) == 1)
        jobs[0].release.set()
        wait_for(lambda: owner.page_complete)
        jobs.clear()
    delivered = []
    owner.thumbnail_ready.connect(lambda key, _: delivered.append(key))
    try:
        submit = owner.prefetch if prefetch else owner.visible
        submit([row(1), row(2), row(3)], session_id="session-a", generation=1)
        wait_for(lambda: blocked.is_set() and len(jobs) == (1 if prefetch else 2))
        assert owner._cache_thread.isRunning()
        for job in jobs:
            job.release.set()
        wait_for(lambda: len(jobs) == 2)
        jobs[-1].release.set()
        wait_for(lambda: set(delivered) == {"asset:1", "asset:2"})
        assert not release.is_set() and owner._cache_thread.isRunning()
        assert {job.selected.row.key for job in jobs} == {"asset:1", "asset:2"}
        release.set()
        wait_for(lambda: owner.page_complete)
        assert sorted(delivered) == ["asset:1", "asset:2", "asset:3"]
        assert len(jobs) == 2  # The slow cached card never starts a render.
    finally:
        release.set()


def test_obsolete_streamed_cache_misses_do_not_start_jobs_for_the_previous_page(page_scheduler, monkeypatch):
    owner, jobs = page_scheduler
    blocked, release = threading.Event(), threading.Event()
    def lookup(_root, _rows, key):
        if key == "asset:1":
            blocked.set()
            release.wait(10)
        return None
    monkeypatch.setattr(module, "cached_character_row", lookup)
    try:
        owner.visible([row(1), row(2)], session_id="session-a", generation=1)
        wait_for(blocked.is_set)
        owner.clear_page()
        owner.visible([row(3)], session_id="session-a", generation=2)
        release.set()
        wait_for(lambda: len(jobs) == 1)
        assert jobs[0].selected.row.key == "asset:3"
        jobs[0].release.set()
        wait_for(lambda: owner.page_complete)
        assert len(jobs) == 1
    finally:
        release.set()


def test_paused_startup_does_not_dispatch_streamed_cache_misses(page_scheduler, monkeypatch):
    owner, jobs = page_scheduler
    blocked, release = threading.Event(), threading.Event()
    def lookup(*_):
        blocked.set()
        release.wait(10)
        return None
    monkeypatch.setattr(module, "cached_character_row", lookup)
    try:
        owner.visible([row(1), row(2)], session_id="session-a", generation=1)
        wait_for(blocked.is_set)
        owner.pause_scheduling()
        release.set()
        wait_for(lambda: not owner.busy)
        QTest.qWait(25)
        assert not jobs
        owner.resume_scheduling()
        wait_for(lambda: len(jobs) == 2)
        for job in jobs:
            job.release.set()
        wait_for(lambda: owner.page_complete)
    finally:
        release.set()


def test_cached_cards_arrive_while_later_disk_lookups_are_still_running(monkeypatch, tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    blocked, release = threading.Event(), threading.Event()
    result = CharacterRenderResult("cache", "package", "thumbnail", "base_appearance", ())
    def lookup(_root, _rows, key):
        if key == "asset:2":
            blocked.set()
            assert release.wait(3)
        return result
    monkeypatch.setattr(module, "cached_character_row", lookup)
    owner = module.CharacterFinderPreviewController(Service(), fingerprint="fp", cache_root=tmp_path,
        settings=ModelPreviewRenderSettings())
    delivered = []
    owner.thumbnail_ready.connect(lambda key, _: delivered.append(key))
    try:
        owner.visible([row(1), row(2)], session_id="session-a", generation=1)
        wait_for(lambda: blocked.is_set() and delivered == ["asset:1"])
        assert owner.busy
        release.set()
        wait_for(lambda: delivered == ["asset:1", "asset:2"] and owner.page_complete)
    finally:
        release.set()
        owner.shutdown()
        wait_for(lambda: not owner.busy)
        owner.deleteLater()
        _APP.processEvents()


def test_empty_preload_page_reports_idle_without_waiting_for_a_scroll(tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    owner = module.CharacterFinderPreviewController(Service(), fingerprint="fp", cache_root=tmp_path,
        settings=ModelPreviewRenderSettings(), max_lanes=2)
    idle = []
    owner.idle.connect(lambda: idle.append(True))
    try:
        owner.visible([], session_id="session-a", generation=1)
        wait_for(lambda: idle)
        assert owner.page_complete
    finally:
        owner.shutdown()
        wait_for(lambda: not owner.busy)
        owner.deleteLater()
        _APP.processEvents()


def test_page_cache_close_retains_worker_and_rejects_late_results(monkeypatch, tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    started, release = threading.Event(), threading.Event()
    result = CharacterRenderResult("cache", "package", "thumbnail", "base_appearance", ())

    def lookup(*_):
        started.set()
        assert release.wait(3)
        return result

    monkeypatch.setattr(module, "cached_character_row", lookup)
    owner = module.CharacterFinderPreviewController(Service(), fingerprint="fp", cache_root=tmp_path,
        settings=ModelPreviewRenderSettings())
    delivered = []
    owner.thumbnail_ready.connect(lambda key, _: delivered.append(key))
    try:
        owner.visible([row(1)], session_id="session-a", generation=1)
        wait_for(started.is_set)
        owner.shutdown()
        assert owner.busy and len(list(owner.iter_shutdown_workers())) == 1
        release.set()
        wait_for(lambda: not owner.busy)
        assert not delivered
    finally:
        release.set()
        owner.shutdown()
        wait_for(lambda: not owner.busy)
        owner.deleteLater()
        _APP.processEvents()


def test_cached_page_loads_without_catalogue_details_and_invalidates_stale_links(monkeypatch, tmp_path):
    from cdmw.workers.character_finder_workers import remember_character_thumbnail, cached_character_row, character_row_cache_root
    global _APP
    _APP = QApplication.instance() or QApplication([])
    service = Service()
    service.get_character_catalog_detail = lambda *_a, **_kw: pytest.fail("A cached page repeated catalogue detail requests")
    owner = module.CharacterFinderPreviewController(service, fingerprint="fp", cache_root=tmp_path,
        settings=ModelPreviewRenderSettings())
    package = tmp_path / "package"
    package.mkdir()
    manifest = package / "manifest.json"
    manifest.write_text("{}")
    thumbnail_root = tmp_path / "character_finder" / "thumbnails"
    thumbnail_root.mkdir(parents=True)
    for index in range(72):
        key = f"{index:064x}"
        path = thumbnail_root / (key + ".png")
        path.write_bytes(b"fixture")
        result = CharacterRenderResult(key, str(package), str(path), "base_appearance", ())
        path.with_suffix(".json").write_text(json.dumps(asdict(result)))
        remember_character_thumbnail(owner._row_root, row(index).key, result)
    delivered = []
    owner.thumbnail_ready.connect(lambda key, _: delivered.append(key))
    try:
        owner.visible([row(i) for i in range(72)], session_id="session-a", generation=1)
        wait_for(lambda: len(delivered) == 72 and not owner.busy)
        assert not service.requests
        assert cached_character_row(tmp_path, character_row_cache_root(tmp_path, "changed", owner._settings), row(0).key) is None
        manifest.unlink()
        assert cached_character_row(tmp_path, owner._row_root, row(0).key) is not None
        assert cached_character_render(tmp_path, f"{0:064x}") is None
        token = owner._cache_token
        owner.clear_page()
        owner._page_cache_ready(token, [("stale", result)])
        assert len(delivered) == 72
    finally:
        owner.shutdown()
        wait_for(lambda: not owner.busy)
        owner.deleteLater()
        _APP.processEvents()


def test_selected_job_cancels_old_thread_and_rejects_its_late_result(controller, monkeypatch):
    owner, service = controller
    jobs, delivered = [], []
    monkeypatch.setattr(module, "cached_character_render", lambda *_: None)

    class Worker(QObject):
        package_ready = Signal(int, object)
        completed = Signal(int, object)
        failed = Signal(int, str)
        finished = Signal()

        def __init__(self, token, selected, **kw):
            super().__init__()
            self.token, self.selected = token, selected
            self.stopped, self.release, self.exited = threading.Event(), threading.Event(), threading.Event()
            jobs.append(self)

        def stop(self): self.stopped.set()

        def run(self):
            self.release.wait(3)
            result = CharacterRenderResult(self.selected.row.key, "package", "thumbnail", "base_appearance", ())
            self.package_ready.emit(self.token, result)
            self.completed.emit(self.token, result)
            self.exited.set()
            self.finished.emit()

    monkeypatch.setattr(module, "CharacterFinderRenderWorker", Worker)
    owner.package_ready.connect(lambda key, value: delivered.append(key))
    owner.visible([row(3)], session_id="session-a", generation=1)
    owner.select(detail(row(1)), 1)
    wait_for(lambda: len(jobs) == 1)
    owner.select(detail(row(2)), 2)
    assert jobs[0].stopped.is_set()
    QTest.qWait(25)
    assert len(jobs) == 1  # Replacement waits for actual teardown, not just stop().
    jobs[0].release.set()
    wait_for(lambda: len(jobs) == 2)
    assert jobs[0].exited.is_set() and jobs[1].selected.row.key == row(2).key
    assert not delivered
    started = time.monotonic()
    owner.shutdown()
    assert time.monotonic() - started < .2 and owner.busy
    jobs[1].release.set()
    wait_for(lambda: not owner.busy)
    assert not delivered and not service.requests


def test_warm_thumbnail_and_preview_reuse_without_preparation(controller, tmp_path):
    owner, _ = controller
    selected = detail(row(1))
    key = character_render_key(selected, "fp", owner._settings)
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest.json").write_text("{}")
    root = tmp_path / "character_finder" / "thumbnails"
    root.mkdir(parents=True)
    image = root / (key + ".png")
    image.write_bytes(b"cached fixture image")
    result = CharacterRenderResult(key, str(package), str(image), "base_appearance", ())
    (root / (key + ".json")).write_text(json.dumps(asdict(result)))
    delivered = []
    owner.thumbnail_ready.connect(lambda _, value: delivered.append(value))
    owner._preparation.start = lambda *_: pytest.fail("warm cache unnecessarily prepared archive entries")
    owner.select(selected, 1)
    wait_for(lambda: len(delivered) == 1 and not owner.busy)
    assert delivered[0].cache_hit
    assert key != character_render_key(selected, "refreshed", owner._settings)
    assert key != character_render_key(replace(selected, context_key="other appearance"), "fp", owner._settings)
    (package / "manifest.json").unlink()
    assert cached_character_render(tmp_path, key) is None


def test_extra_context_lookup_cannot_publish_missing_entries_as_complete():
    service = Service()
    preparation = CharacterPreviewPreparation(service)
    model = _dto(1, "character/body.pac")
    selected = replace(detail(row(1)), models=(model,), files=(
        CharacterCatalogFile(2, "character/body.pabc", ".pabc", "dependency", "fixture"),), total_file_count=1)
    snapshot = ArchivePreviewDependencySet.from_dtos(model, (), total_candidates=0, truncated=False,
        prepared={1: _prepared(model)})
    preparation._provider.request = lambda *_a, **_kw: True
    results = []
    preparation.ready.connect(lambda _token, value: results.append(value))
    preparation.start(selected, 9)
    preparation._model_ready(9, snapshot)
    request = preparation._request
    service.result_ready.emit(request, "resolve_entries", ArchiveLookupResult("session-a", (), 1, True))
    assert len(results) == 1 and not results[0].dependencies_complete
    preparation.start(selected, 10)
    preparation._model_ready(10, snapshot)
    failures = []
    preparation.failed.connect(lambda token, message: failures.append((token, message)))
    service.request_cancelled.emit(preparation._request)
    assert failures[0][0] == 10 and preparation._detail is None


def test_combined_body_reuses_only_identical_rendered_components():
    body, head = _dto(1, "character/body.pac"), _dto(2, "character/head.pac")
    body_component = CharacterCatalogComponent("body", "body_variant", (1,), (3,), 1.02, {}, "resolved")
    head_component = CharacterCatalogComponent("head", "head_variant", (2,), (4,), .95, {}, "resolved")
    files = tuple(CharacterCatalogFile(i, f"character/{i}.pabc", ".pabc", "dependency", "fixture") for i in range(1, 5))
    first = replace(detail(row(1, embedded_face=True)), models=(body, head),
                    components=(body_component, head_component), files=files, total_file_count=4)
    preview = character_preview_detail(first)
    assert preview.models == (body,) and preview.components == (body_component,)
    assert {f.entry_id for f in preview.files} == {1, 3} and preview.total_file_count == 2
    assert first.models == (body, head)  # UI ownership/details remain complete.
    settings = ModelPreviewRenderSettings()
    key = character_render_key(first, "fp", settings)
    other_owner = replace(first, row=replace(first.row, key="other-owner"), context_key="other-owner",
                          components=(body_component, replace(head_component, name="different_head")))
    assert character_render_key(other_owner, "fp", settings) == key
    assert character_render_key(replace(first, components=(replace(body_component, scale=1.1), head_component)), "fp", settings) != key
    assert character_render_key(replace(first, components=(replace(body_component, name="other_pabc_variant"), head_component)), "fp", settings) != key
    assert character_render_key(replace(first, files=(*files[:2], replace(files[2], path="different/material.dds"), files[3])), "fp", settings) != key
    assert character_preview_detail(replace(first, files=files[:2])).models == (body, head)


def test_heads_share_complete_shape_and_material_inputs_but_keep_variants_distinct():
    head = _dto(1, "character/head.pac")
    component = CharacterCatalogComponent("head", "head_variant", (1,), (2,), .97, {"Name": "head_variant"}, "resolved")
    shape = CharacterCatalogFile(2, "character/head_variant.prefabdata_xml", ".prefabdata_xml", "dependency", "fixture")
    custom = CharacterCatalogFile(3, "character/custom.paccd", ".paccd", "dependency", "fixture")
    owner = CharacterCatalogFile(4, "character/first.app_xml", ".app_xml", "direct", "fixture")
    first = replace(detail(row(1, role="head")), models=(head,), components=(component,),
        files=(shape, custom, owner), total_file_count=3, appearance_path=owner.path)
    second = replace(first, row=replace(first.row, key="other-owner", label="Other owner"), context_key="other-owner",
        appearance_path="character/second.app_xml", files=(shape, custom, replace(owner, entry_id=5, path="character/second.app_xml")))
    settings = ModelPreviewRenderSettings()
    key = character_render_key(first, "fp", settings)
    assert character_render_key(second, "fp", settings) == key
    assert character_preview_detail(first).files == (shape, custom)
    assert first.files == (shape, custom, owner)
    variants = (
        replace(second, components=(replace(component, scale=1.0),)),
        replace(second, components=(replace(component, name="other_shape"),)),
        replace(second, components=(replace(component, attributes={"Name": "head_variant", "Color": "2"}),)),
        replace(second, files=(replace(shape, path="character/other.pabc"), custom)),
        replace(second, files=(shape, replace(custom, entry_id=6, path="character/other.paccd"))),
        replace(second, total_file_count=300),
    )
    assert all(character_render_key(variant, "fp", settings) != key for variant in variants)
    declared_app = replace(first, components=(replace(component, context_entry_ids=(2, 4)),))
    assert owner in character_preview_detail(declared_app).files


def test_extra_context_consumes_streamed_lookup_and_prepared_batches():
    service = Service()
    preparation = CharacterPreviewPreparation(service)
    model = _dto(1, "character/head.pac")
    extra = _dto(2, "character/head.pabc")
    selected = replace(detail(row(1)), models=(model,), files=(
        CharacterCatalogFile(2, extra.path, ".pabc", "dependency", "fixture"),), total_file_count=1)
    snapshot = ArchivePreviewDependencySet.from_dtos(model, (), total_candidates=0, truncated=False,
        prepared={1: _prepared(model)})
    preparation._provider.request = lambda *_a, **_kw: True
    results = []
    preparation.ready.connect(lambda _token, value: results.append(value))
    preparation.start(selected, 9)
    preparation._model_ready(9, snapshot)
    request = preparation._request
    service.batch_ready.emit(request, "resolve_entries", ArchiveLookupResult("session-a", (extra,), 1, False))
    service.result_ready.emit(request, "resolve_entries", ArchiveLookupResult("session-a", (), 1, False))
    assert not results
    request = preparation._request
    service.batch_ready.emit(request, "prepare_entry", PrepareEntriesResult("session-a", (_prepared(extra),), 1, 1, 40))
    service.result_ready.emit(request, "prepare_entry", PrepareEntriesResult("session-a", (), 1, 1, 40))
    assert len(results) == 1 and results[0].dependencies_complete
    assert {entry.path for entry in results[0].entries} == {model.path, extra.path}
    assert str(results[0].entries_by_id[2].prepared_path).replace("\\", "/") == "C:/cache/2.pabc"


def test_prepared_model_dependencies_keep_ids_for_authored_descriptor_selection():
    service = Service()
    preparation = CharacterPreviewPreparation(service)
    model = _dto(1, "character/body.pac")
    descriptor = _dto(2, "character/body_variant.prefabdata_xml")
    selected = replace(detail(row(1)), models=(model,), files=(
        CharacterCatalogFile(2, descriptor.path, ".prefabdata_xml", "dependency", "fixture"),), total_file_count=1)
    snapshot = ArchivePreviewDependencySet.from_dtos(model, (descriptor,), total_candidates=1,
        truncated=False, prepared={1: _prepared(model), 2: _prepared(descriptor)})
    preparation._provider.request = lambda *_a, **_kw: True
    results = []
    preparation.ready.connect(lambda _token, value: results.append(value))
    preparation.start(selected, 1)
    preparation._model_ready(1, snapshot)
    assert len(results) == 1 and results[0].entries_by_id[2].path == descriptor.path
    assert not service.requests  # Already prepared; no repeated lookup/extraction.


def test_incomplete_character_dependencies_cannot_trigger_an_archive_wide_native_scan(tmp_path):
    worker = CharacterFinderRenderWorker(1, SimpleNamespace(dependencies_complete=False),
        cache_root=tmp_path, fingerprint="fp", settings=ModelPreviewRenderSettings())
    with pytest.raises(ValueError, match="dependencies are incomplete"):
        worker._build_package("fixture")
    assert not list(tmp_path.iterdir())


def test_cancel_after_capture_preserves_existing_metadata(tmp_path):
    selected = detail(row(1))
    worker = CharacterFinderRenderWorker(1, SimpleNamespace(detail=selected), cache_root=tmp_path,
        fingerprint="fp", settings=ModelPreviewRenderSettings())
    worker._build_package = lambda _: (SimpleNamespace(package_dir=tmp_path / "package"), "base_appearance", ())
    target = tmp_path / "image.png"
    metadata = target.with_suffix(".json")
    metadata.write_text("old usable metadata")
    def capture(*_):
        worker.stop()
        return target
    worker._capture = capture
    delivered = []
    worker.completed.connect(lambda *_: delivered.append(True))
    worker.run()
    assert not delivered and metadata.read_text() == "old usable metadata"
    assert not list(tmp_path.rglob("*.tmp"))


def _ready_package(root):
    from cdmw.services.mesh_rust_contract import (
        RUST_PREVIEW_PACKAGE, RUST_PREVIEW_PROTOCOL, RUST_MESH_RENDERER, RUST_PREVIEW_BACKEND,
    )
    from cdmw.services.mesh_rust_preview_package import rust_preview_package_from_path
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps({"schema": RUST_PREVIEW_PACKAGE,
        "protocol": RUST_PREVIEW_PROTOCOL, "renderer": RUST_MESH_RENDERER, "edit_backend": RUST_PREVIEW_BACKEND}))
    return rust_preview_package_from_path(root)


def _capture_fixture(root, key):
    image = root / "character_finder" / "thumbnails" / (key + ".png")
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"owned thumbnail fixture")
    return image


@pytest.mark.parametrize("cancelled", [True, False])
def test_interrupted_thumbnail_retains_ready_3d_package_and_retries_only_capture(tmp_path, cancelled):
    from cdmw.models import RunCancelled
    from cdmw.rendering.native_preview_package_cache import native_preview_package_live_paths_guard
    selected = detail(row(1))
    settings = replace(ModelPreviewRenderSettings(), use_textures_by_default=True)
    key = character_render_key(selected, "fp", settings)
    package = _ready_package(tmp_path / "package")
    first = CharacterFinderRenderWorker(1, SimpleNamespace(detail=selected),
        cache_root=tmp_path, fingerprint="fp", settings=settings)
    builds, delivered = [], []
    def build(_key):
        builds.append(_key)
        return package, "base_appearance", ("authored shape",)
    def capture(*_):
        assert cached_character_package(tmp_path, key) is not None
        with native_preview_package_live_paths_guard() as paths:
            assert package.package_dir in paths
        if cancelled:
            first.stop()
            raise RunCancelled("fixture cancellation")
        raise RuntimeError("fixture capture failure")
    first._build_package, first._capture = build, capture
    first.completed.connect(lambda *_: delivered.append(True))
    first.run()
    assert not delivered and cached_character_render(tmp_path, key) is None
    assert cached_character_package(tmp_path, key).notes == ("authored shape",)
    second = CharacterFinderRenderWorker(2, SimpleNamespace(detail=selected),
        cache_root=tmp_path, fingerprint="fp", settings=settings, cache_only=True)
    second._build_package = lambda *_: pytest.fail("A ready 3D package was rebuilt")
    second._capture = lambda _package, _key: _capture_fixture(tmp_path, _key)
    second.completed.connect(lambda _token, result: delivered.append(result))
    second.run()
    assert len(builds) == 1 and len(delivered) == 1 and delivered[0].cache_hit
    assert cached_character_render(tmp_path, key) is not None
    assert not list(tmp_path.rglob("*.tmp"))


def test_ready_3d_selection_skips_archive_preparation_and_loads_host_only_once(controller, tmp_path, monkeypatch):
    owner, _ = controller
    selected = detail(row(1))
    key = character_render_key(selected, "fp", owner._settings)
    package = _ready_package(tmp_path / "package")
    metadata = tmp_path / "character_finder" / "thumbnails" / (key + ".package.json")
    metadata.parent.mkdir(parents=True)
    result = CharacterRenderResult(key, str(package.package_dir), "", "base_appearance", ())
    metadata.write_text(json.dumps(asdict(result)))
    monkeypatch.setattr(CharacterFinderRenderWorker, "_capture",
        lambda self, _package, _key: _capture_fixture(tmp_path, _key))
    owner._preparation.start = lambda *_: pytest.fail("Cached 3D selection prepared archive inputs again")
    packages, thumbnails = [], []
    owner.package_ready.connect(lambda _key, result: packages.append(result))
    owner.thumbnail_ready.connect(lambda _key, result: thumbnails.append(result))
    owner.select(selected, 1)
    wait_for(lambda: thumbnails and not owner.busy)
    assert len(packages) == 1 and thumbnails[0].thumbnail_path


def test_evicted_3d_cache_returns_to_preparation_after_capture_worker_teardown(controller, monkeypatch):
    owner, _ = controller
    monkeypatch.setattr(module, "cached_character_package", lambda *_:
        CharacterRenderResult("stale", "evicted-package", "", "base_appearance", ()))
    prepared = []
    def prepare(selected, token):
        assert owner._thread is None
        prepared.append(selected)
        owner._fail("end fixture after preparation fallback")
    owner._preparation.start = prepare
    selected = detail(row(1))
    owner.select(selected, 1)
    wait_for(lambda: prepared and not owner.busy)
    assert prepared == [selected]


def test_duplicate_render_jobs_share_one_build_and_capture_but_keep_each_row_link(tmp_path):
    from PySide6.QtCore import Qt
    from cdmw.workers import character_finder_workers as workers
    component = CharacterCatalogComponent("head", "shared_head", (1,), (), 1.0, {}, "resolved")
    first_detail = replace(detail(row(1, role="head")), models=(_dto(1, "character/head.pac"),), components=(component,))
    settings = replace(ModelPreviewRenderSettings(), use_textures_by_default=True)
    gate, entered = threading.Event(), threading.Event()
    counts = {"build": 0, "capture": 0}
    jobs, threads, results, failures = [], [], [], []
    def build(key):
        counts["build"] += 1
        entered.set()
        assert gate.wait(3)
        return _ready_package(tmp_path / "package"), "base_appearance", ()
    def capture(_package, key):
        counts["capture"] += 1
        return _capture_fixture(tmp_path, key)
    for index in range(4):
        selected = replace(first_detail, row=replace(first_detail.row, key=f"owner:{index}"), context_key=f"owner:{index}")
        worker = workers.CharacterFinderRenderWorker(index, SimpleNamespace(detail=selected),
            cache_root=tmp_path, fingerprint="fp", settings=settings)
        worker._build_package, worker._capture = build, capture
        worker.completed.connect(lambda _token, result: results.append(result), Qt.ConnectionType.DirectConnection)
        worker.failed.connect(lambda _token, message: failures.append(message), Qt.ConnectionType.DirectConnection)
        jobs.append(worker)
        threads.append(threading.Thread(target=worker.run))
    try:
        for thread in threads:
            thread.start()
        assert entered.wait(2)
        gate.set()
        for thread in threads:
            thread.join(3)
        assert not any(thread.is_alive() for thread in threads)
        assert not failures and len(results) == 4
        assert counts == {"build": 1, "capture": 1}
        assert sum(result.cache_hit for result in results) == 3
        root = character_row_cache_root(tmp_path, "fp", settings)
        assert all(cached_character_row(tmp_path, root, f"owner:{i}") for i in range(4))
    finally:
        gate.set()
        for worker in jobs:
            worker.stop()
        for thread in threads:
            thread.join(3)


def test_waiting_for_a_matching_render_is_cancellable_without_blocking_other_keys(tmp_path):
    from cdmw.rendering.dotnet_preview_package_cache import dotnet_preview_package_cache_build_lock
    settings = replace(ModelPreviewRenderSettings(), use_textures_by_default=True)
    selected = detail(row(1))
    key = character_render_key(selected, "fp", settings)
    lock = dotnet_preview_package_cache_build_lock(tmp_path / "character_finder", key)
    worker = CharacterFinderRenderWorker(1, SimpleNamespace(detail=selected),
        cache_root=tmp_path, fingerprint="fp", settings=settings, cache_only=True)
    other = CharacterFinderRenderWorker(2, SimpleNamespace(detail=detail(row(2))),
        cache_root=tmp_path, fingerprint="fp", settings=settings, cache_only=True)
    thread, unrelated = threading.Thread(target=worker.run), threading.Thread(target=other.run)
    lock.acquire()
    try:
        thread.start()
        unrelated.start()
        unrelated.join(1)
        assert not unrelated.is_alive()
        assert thread.is_alive()
        worker.stop()
        thread.join(1)
        assert not thread.is_alive()
    finally:
        lock.release()
        worker.stop()
        thread.join(3)
        unrelated.join(3)


def test_matching_request_receives_ready_3d_before_shared_thumbnail_finishes(tmp_path):
    from PySide6.QtCore import Qt
    selected = detail(row(1))
    settings = replace(ModelPreviewRenderSettings(), use_textures_by_default=True)
    first = CharacterFinderRenderWorker(1, SimpleNamespace(detail=selected),
        cache_root=tmp_path, fingerprint="fp", settings=settings)
    second = CharacterFinderRenderWorker(2, SimpleNamespace(detail=selected),
        cache_root=tmp_path, fingerprint="fp", settings=settings)
    capture_started, finish_capture, ready = threading.Event(), threading.Event(), threading.Event()
    failures = []
    first._build_package = lambda _key: (_ready_package(tmp_path / "package"), "base_appearance", ())
    def capture(_package, key):
        capture_started.set()
        assert finish_capture.wait(3)
        return _capture_fixture(tmp_path, key)
    first._capture = capture
    second._build_package = lambda *_: pytest.fail("Matching request rebuilt the model")
    second._capture = lambda *_: pytest.fail("Matching request repeated capture")
    second.package_ready.connect(lambda *_: ready.set(), Qt.ConnectionType.DirectConnection)
    for worker in (first, second):
        worker.failed.connect(lambda _token, message: failures.append(message), Qt.ConnectionType.DirectConnection)
    threads = [threading.Thread(target=worker.run) for worker in (first, second)]
    try:
        threads[0].start()
        assert capture_started.wait(2)
        threads[1].start()
        assert ready.wait(2)
        assert not finish_capture.is_set() and threads[1].is_alive()
        finish_capture.set()
        for thread in threads:
            thread.join(3)
        assert not any(thread.is_alive() for thread in threads) and not failures
    finally:
        finish_capture.set()
        first.stop()
        second.stop()
        for thread in threads:
            if thread.ident is not None:
                thread.join(3)


@pytest.mark.parametrize("unavailable", [False, True])
def test_finder_passes_authored_shape_to_primary_and_attached_meshes(tmp_path, monkeypatch, unavailable):
    import copy
    import struct
    from cdmw.domain.character_finder import CharacterPreviewInputs
    from tests.test_release_inspired_improvements import _entry
    from tests.test_pabc_neutral_bind_frames import _fixture

    body = _entry("character/model/body_base.pac")
    attached = _entry("character/model/underwear.pac")
    variant = _entry("character/prefab/body_variant.prefabdata_xml")
    base = _entry("character/prefab/body_base.prefabdata_xml")
    component = CharacterCatalogComponent("body", "body_variant", (1, 2), (3, 4), 1.02, {}, "resolved")
    selected = replace(detail(row(1, embedded_face=True)), models=(_dto(1, body.path), _dto(2, attached.path)),
        components=(component,))
    inputs = CharacterPreviewInputs(selected, {1: body, 2: attached, 3: variant, 4: base},
        (body, attached, variant, base), True)
    worker = CharacterFinderRenderWorker(1, inputs, cache_root=tmp_path, fingerprint="fp", settings=ModelPreviewRenderSettings())
    _rig, raw = _fixture()
    changed = copy.deepcopy(raw)
    changed.submeshes[0].vertices[0] = (.2, 1.7, .03)
    changed._cdmw_skeleton_variation_source = "character/variant.pabc"
    calls = []

    def appearance(entry, parsed, data, **kwargs):
        assert kwargs["authored_descriptor"] == variant
        if unavailable:
            raise ValueError("The declared skeleton variation is unavailable")
        return changed, ("Applied authored variant",)

    def native(entry, **kwargs):
        calls.append((entry, kwargs))
        return SimpleNamespace(succeeded=True, package_path=str(tmp_path / "native"))

    monkeypatch.setattr("cdmw.core.archive.read_archive_entry_data", lambda *a, **kw: (b"owned PAC", False, ""))
    monkeypatch.setattr("cdmw.modding.mesh_parser.parse_mesh", lambda *a, **kw: raw)
    monkeypatch.setattr("cdmw.core.archive_mesh_appearance.apply_archive_mesh_appearance", appearance)
    monkeypatch.setattr("cdmw.workers.archive_preview_native.native_preview_model_property_indices", lambda *a: ())
    monkeypatch.setattr("cdmw.rendering.native_preview_core.run_native_preview_core_preview_job", native)
    monkeypatch.setattr("cdmw.services.preview_material_status.native_preview_missing_texture_reason", lambda *a: None)
    monkeypatch.setattr("cdmw.services.mesh_rust_preview_cache.build_or_lookup_rust_preview_package", lambda *a, **kw: "package")
    if unavailable:
        with pytest.raises(ValueError, match="declared skeleton variation"):
            worker._build_package("fixture")
        assert not calls  # No raw-geometry retry advertised as the true appearance.
        return
    package, status, notes = worker._build_package("fixture")
    assert package == "package" and status == "base_appearance" and "Applied authored variant" in notes
    assert len(calls) == 1 and calls[0][0] == body
    kwargs = calls[0][1]
    assert kwargs["cache_root"] == kwargs["output_root"].parent / "native-cache"
    assert not kwargs["cache_root"].parent.exists()  # Owned scratch retires after package publication.
    primary = struct.unpack_from("<6f", kwargs["presentation_geometry_payload"], 24)[:3]
    assert primary == pytest.approx(tuple(v * 1.02 for v in changed.submeshes[0].vertices[0]))
    context = kwargs["preview_context_components"]
    assert len(context) == 1 and context[0].entry == attached and context[0].scale == 1.02
    assert context[0].presentation_geometry_source == changed._cdmw_skeleton_variation_source
    assert struct.unpack_from("<6f", context[0].presentation_geometry_payload, 24)[:3] == pytest.approx(changed.submeshes[0].vertices[0])
