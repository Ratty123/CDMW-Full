from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.item_catalogue import (
    BuildNameIndexResult,
    ItemCatalogRow,
    ItemCatalogSearchRequest,
    ItemCatalogSearchResult,
    ItemIconBatchResult,
    ItemIconResult,
)
from cdmw.ui.archive_browser.remote_finder_warmup import RemoteItemFinderWarmupController
from cdmw.ui.archive_browser import remote_finder_warmup as warmup_module
from cdmw.workers.archive_item_finder_workers import ArchiveItemThumbnailWorker


_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def _drain() -> None:
    for _ in range(12):
        _app().processEvents()


def _wait_until(predicate: object, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _app().processEvents()
        if callable(predicate) and predicate():
            return
        time.sleep(0.005)
    assert callable(predicate) and predicate()


class _Service(QObject):
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.builds: list[tuple[str, int]] = []
        self.searches: list[tuple[ItemCatalogSearchRequest, int]] = []
        self.icons: list[object] = []
        self.cancelled: list[str] = []

    def build_name_index(self, session_id: str, *, ui_generation: int) -> str:
        self.builds.append((session_id, ui_generation))
        return f"build-{len(self.builds)}"

    def search_item_catalog(self, request: ItemCatalogSearchRequest, *, ui_generation: int) -> str:
        self.searches.append((request, ui_generation))
        return f"search-{len(self.searches)}"

    def load_item_icons(self, request: object, *, ui_generation: int) -> str:
        self.icons.append((request, ui_generation))
        return f"icons-{len(self.icons)}"

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True


class _Settings:
    def __init__(self) -> None:
        self.values = {
            "ui/item_finder_search_text": "sword",
            "ui/item_finder_category": "Equipment",
            "ui/item_finder_group": "Weapon",
            "ui/item_finder_material_tag": "metal",
        }

    def value(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)


def _session(value: str = "a") -> ArchiveSessionHandle:
    return ArchiveSessionHandle(
        f"session-{value}",
        "C:/Game",
        f"fingerprint-{value}",
        20,
        3,
        True,
    )


def _row(item_id: int, *, with_icon: bool) -> ItemCatalogRow:
    return ItemCatalogRow(
        item_id,
        f"item_{item_id}",
        f"Item {item_id}",
        "Equipment",
        "Weapon",
        "path classification",
        (f"equipment/weapon/item_{item_id}.pac",),
        (f"item_{item_id}",),
        (f"ui/icon/item_{item_id}.dds",) if with_icon else (),
        (),
        ("metal",),
        1,
        "model link",
    )


def test_startup_builds_catalogue_and_caches_the_restored_first_page() -> None:
    _app()
    service = _Service()
    controller = RemoteItemFinderWarmupController(service, _Settings())

    controller.start(_session(), ui_generation=7)
    _drain()
    assert service.builds == [("session-a", 7)]

    service.result_ready.emit(
        "build-1",
        "build_name_index",
        BuildNameIndexResult("session-a", True, False, 5, 9, item_count=1),
    )
    assert len(service.searches) == 1
    request = service.searches[0][0]
    assert request == ItemCatalogSearchRequest(
        "session-a",
        query="sword",
        category="Equipment",
        group="Weapon",
        material_tag="metal",
        page_start=0,
        page_size=72,
    )
    result = ItemCatalogSearchResult("session-a", 1, 0, 72, (_row(7, with_icon=False),), (), (), True)
    service.result_ready.emit("search-1", "search_item_catalog", result)

    assert controller.cached_search(request) is result
    _drain()
    assert len(service.searches) == 2
    catalogue_page = service.searches[1][0]
    assert catalogue_page.query == ""
    assert catalogue_page.page_start == 0
    assert catalogue_page.page_size == 256
    controller.request_shutdown()


def test_new_archive_cancels_old_warmup_and_rejects_its_late_result() -> None:
    _app()
    service = _Service()
    controller = RemoteItemFinderWarmupController(service, _Settings())

    controller.start(_session("a"), ui_generation=2)
    _drain()
    controller.start(_session("b"), ui_generation=3)
    _drain()

    assert "build-1" in service.cancelled
    assert service.builds[-1] == ("session-b", 3)
    service.result_ready.emit(
        "build-1",
        "build_name_index",
        BuildNameIndexResult("session-a", True, False, 1, 1, item_count=1),
    )
    assert service.searches == []
    controller.request_shutdown()


def test_new_session_resumes_after_a_stale_conversion_thread_finishes() -> None:
    _app()
    service = _Service()
    controller = RemoteItemFinderWarmupController(service, _Settings())
    stale_thread = QThread(controller)
    stale_worker = ArchiveItemThumbnailWorker(0, {}, controller.thread())
    controller._threads[stale_thread] = warmup_module._WarmupThread(  # type: ignore[attr-defined]
        stale_worker,
        0,
        (),
    )

    controller.start(_session("b"), ui_generation=6)
    _drain()
    assert service.builds == []
    controller._cleanup_thread(stale_thread)
    _wait_until(lambda: service.builds == [("session-b", 6)])

    controller.request_shutdown()


def test_startup_icon_warmup_decodes_off_thread_and_serves_memory_hit(tmp_path) -> None:
    _app()
    service = _Service()
    controller = RemoteItemFinderWarmupController(service, _Settings())
    ready: list[tuple[str, tuple[int, ...]]] = []
    controller.iconsReady.connect(lambda session_id, ids: ready.append((session_id, tuple(ids))))

    controller.start(_session(), ui_generation=4)
    _drain()
    service.result_ready.emit(
        "build-1",
        "build_name_index",
        BuildNameIndexResult("session-a", True, False, 1, 1, item_count=1),
    )
    result = ItemCatalogSearchResult("session-a", 1, 0, 72, (_row(11, with_icon=True),), (), (), True)
    service.result_ready.emit("search-1", "search_item_catalog", result)
    _wait_until(lambda: len(service.icons) == 1)
    assert service.icons[0][0].item_ids == (11,)

    png_path = tmp_path / "item_11.png"
    image = QImage(16, 16, QImage.Format_ARGB32)
    image.fill(0xFFFF0000)
    assert image.save(str(png_path))
    service.result_ready.emit(
        "icons-1",
        "load_item_icons",
        ItemIconBatchResult("session-a", (ItemIconResult(11, str(png_path), None),)),
    )

    _wait_until(lambda: bool(controller.cached_icons("session-a", (11,))))
    cached = controller.cached_icons("session-a", (11,))[11]
    assert cached[0] == str(png_path)
    assert not cached[1].isNull()
    assert ready == [("session-a", (11,))]

    controller.request_shutdown()
    _wait_until(lambda: not tuple(controller.iter_shutdown_workers()))


def test_background_warmup_scans_every_catalogue_page_and_queues_all_icons(monkeypatch) -> None:
    _app()
    service = _Service()
    controller = RemoteItemFinderWarmupController(service, _Settings())
    decoded_batches: list[tuple[int, ...]] = []

    def complete_decode(_sources: object, *, requested_ids: tuple[int, ...]) -> None:
        decoded_batches.append(requested_ids)
        controller._inflight_icon_ids.difference_update(requested_ids)
        controller._processed_icon_ids.update(requested_ids)
        controller._schedule_continue(0)

    monkeypatch.setattr(controller, "_start_decode_worker", complete_decode)
    controller.start(_session(), ui_generation=8)
    _drain()
    service.result_ready.emit(
        "build-1",
        "build_name_index",
        BuildNameIndexResult("session-a", True, False, 4, 4, item_count=4),
    )
    service.result_ready.emit(
        "search-1",
        "search_item_catalog",
        ItemCatalogSearchResult("session-a", 0, 0, 72, (), (), (), True),
    )
    _wait_until(lambda: len(service.searches) == 2)

    first_rows = (_row(101, with_icon=True), _row(102, with_icon=True))
    service.result_ready.emit(
        "search-2",
        "search_item_catalog",
        ItemCatalogSearchResult("session-a", 4, 0, 256, first_rows, (), (), True),
    )
    _wait_until(lambda: len(service.icons) == 1)
    service.result_ready.emit(
        "icons-1",
        "load_item_icons",
        ItemIconBatchResult(
            "session-a",
            tuple(ItemIconResult(item_id, None, f"C:/icons/{item_id}.dds") for item_id in (101, 102)),
        ),
    )
    _wait_until(lambda: len(service.searches) == 3)
    assert service.searches[2][0].page_start == 2

    second_rows = (_row(103, with_icon=True), _row(104, with_icon=True))
    service.result_ready.emit(
        "search-3",
        "search_item_catalog",
        ItemCatalogSearchResult("session-a", 4, 2, 256, second_rows, (), (), True),
    )
    _wait_until(lambda: len(service.icons) == 2)
    service.result_ready.emit(
        "icons-2",
        "load_item_icons",
        ItemIconBatchResult(
            "session-a",
            tuple(ItemIconResult(item_id, None, f"C:/icons/{item_id}.dds") for item_id in (103, 104)),
        ),
    )
    _wait_until(lambda: controller._state == "ready")

    assert decoded_batches == [(101, 102), (103, 104)]
    assert tuple(item_id for request, _generation in service.icons for item_id in request.item_ids) == (
        101,
        102,
        103,
        104,
    )
    controller.request_shutdown()


def test_thumbnail_worker_converts_one_dds_batch_instead_of_one_process_per_icon(
    tmp_path,
    monkeypatch,
) -> None:
    _app()
    dds_paths = (tmp_path / "one.dds", tmp_path / "two.dds")
    for path in dds_paths:
        path.write_bytes(b"DDS test")
    png_path = tmp_path / "ready.png"
    image = QImage(12, 12, QImage.Format_ARGB32)
    image.fill(0xFF00FF00)
    assert image.save(str(png_path))
    batches: list[tuple[dict[str, object], ...]] = []
    cache_dirnames: list[str] = []

    def fake_batch(jobs: object, **kwargs: object) -> dict[str, object]:
        frozen = tuple(dict(job) for job in jobs)
        batches.append(frozen)
        cache_dirnames.append(str(kwargs.get("cache_dirname") or ""))
        return {
            str(path.resolve()): png_path
            for path in dds_paths
        }

    monkeypatch.setattr(
        "cdmw.core.texture_native.ensure_directxtex_dds_preview_pngs",
        fake_batch,
    )
    ready: list[int] = []
    worker = ArchiveItemThumbnailWorker(
        3,
        {1: str(dds_paths[0]), 2: str(dds_paths[1])},
        QThread.currentThread(),
    )
    worker.icon_ready.connect(lambda _generation, item_id, _path, _image: ready.append(item_id))

    worker.run()

    assert len(batches) == 1
    assert len(batches[0]) == 2
    assert cache_dirnames == ["preview/item-icons"]
    assert ready == [1, 2]
