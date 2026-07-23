"""Startup-owned catalogue and icon warmup for the remote Item Finder."""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QImage

from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.item_catalogue import (
    BuildNameIndexResult,
    ItemCatalogSearchRequest,
    ItemCatalogSearchResult,
    ItemIconBatchRequest,
    ItemIconBatchResult,
    migrate_legacy_item_catalogue_filter,
)
from cdmw.workers.archive_item_finder_workers import ArchiveItemThumbnailWorker


_INITIAL_PAGE_SIZE = 72
_CATALOGUE_PAGE_SIZE = 256
_VISIBLE_ICON_BATCH_SIZE = 24
_BACKGROUND_ICON_BATCH_SIZE = 8
_MEMORY_ICON_LIMIT = 96
_SEARCH_CACHE_LIMIT = 4


@dataclass(frozen=True, slots=True)
class _WarmupRequest:
    kind: str
    generation: int
    item_ids: tuple[int, ...] = ()
    page_start: int = 0


@dataclass(frozen=True, slots=True)
class _WarmupThread:
    worker: ArchiveItemThumbnailWorker
    generation: int
    item_ids: tuple[int, ...]


class RemoteItemFinderWarmupController(QObject):
    """Prewarm the saved Finder page, then its durable icon cache while idle."""

    iconsReady = Signal(str, object)
    iconsFailed = Signal(str, object)

    def __init__(
        self,
        service: object,
        settings: object | None,
        *,
        background_allowed: Callable[[], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._settings = settings
        self._background_allowed = background_allowed
        self._closing = False
        self._generation = 0
        self._session_id = ""
        self._fingerprint = ""
        self._ui_generation = 0
        self._state = "idle"
        self._catalogue_ready = False
        self._initial_search_complete = False
        self._enumeration_page_start = 0
        self._enumeration_done = False
        self._requests: dict[str, _WarmupRequest] = {}
        self._threads: dict[QThread, _WarmupThread] = {}
        self._pending_icons: deque[int] = deque()
        self._pending_icon_ids: set[int] = set()
        self._inflight_icon_ids: set[int] = set()
        self._priority_icon_ids: set[int] = set()
        self._startup_item_ids: set[int] = set()
        self._processed_icon_ids: set[int] = set()
        self._failed_icon_ids: set[int] = set()
        self._startup_icon_cache: OrderedDict[int, tuple[str, QImage]] = OrderedDict()
        self._icon_cache: OrderedDict[int, tuple[str, QImage]] = OrderedDict()
        self._search_cache: OrderedDict[ItemCatalogSearchRequest, ItemCatalogSearchResult] = OrderedDict()
        self._initial_request: ItemCatalogSearchRequest | None = None
        self._continue_timer = QTimer(self)
        self._continue_timer.setSingleShot(True)
        self._continue_timer.timeout.connect(self._continue_warmup)
        service.result_ready.connect(self._handle_result)
        service.request_failed.connect(self._handle_failure)
        service.request_cancelled.connect(self._handle_cancelled)

    @property
    def session_id(self) -> str:
        return self._session_id

    def start(self, session: ArchiveSessionHandle, *, ui_generation: int) -> None:
        if self._closing:
            return
        same_session = (
            self._session_id == session.session_id
            and self._fingerprint == session.fingerprint
        )
        self._ui_generation = max(self._ui_generation, int(ui_generation))
        if same_session and self._state not in {"idle", "failed"}:
            return
        self.invalidate()
        self._session_id = session.session_id
        self._fingerprint = session.fingerprint
        self._ui_generation = int(ui_generation)
        self._state = "scheduled"
        self._initial_request = self._saved_search_request(session.session_id)
        self._continue_timer.start(0)

    def invalidate(self) -> None:
        self._generation += 1
        self._continue_timer.stop()
        for request_id in tuple(self._requests):
            try:
                self._service.cancel(request_id)
            except Exception:
                pass
        self._requests.clear()
        for handle in tuple(self._threads.values()):
            handle.worker.stop()
        self._session_id = ""
        self._fingerprint = ""
        self._state = "idle"
        self._catalogue_ready = False
        self._initial_search_complete = False
        self._enumeration_page_start = 0
        self._enumeration_done = False
        self._pending_icons.clear()
        self._pending_icon_ids.clear()
        self._inflight_icon_ids.clear()
        self._priority_icon_ids.clear()
        self._startup_item_ids.clear()
        self._processed_icon_ids.clear()
        self._failed_icon_ids.clear()
        self._startup_icon_cache.clear()
        self._icon_cache.clear()
        self._search_cache.clear()
        self._initial_request = None

    def request_shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.invalidate()

    def iter_shutdown_workers(self) -> Iterator[tuple[str, QThread, ArchiveItemThumbnailWorker]]:
        for thread, handle in tuple(self._threads.items()):
            yield "archive_item_finder_warmup", thread, handle.worker

    def cached_search(self, request: ItemCatalogSearchRequest) -> ItemCatalogSearchResult | None:
        if request.session_id != self._session_id:
            return None
        result = self._search_cache.get(request)
        if result is not None:
            self._search_cache.move_to_end(request)
        return result

    def cached_icons(
        self,
        session_id: str,
        item_ids: Sequence[int],
    ) -> dict[int, tuple[str, QImage]]:
        if str(session_id) != self._session_id:
            return {}
        result: dict[int, tuple[str, QImage]] = {}
        for raw_item_id in item_ids:
            item_id = int(raw_item_id)
            cached = self._startup_icon_cache.get(item_id)
            if cached is None:
                cached = self._icon_cache.get(item_id)
                if cached is not None:
                    self._icon_cache.move_to_end(item_id)
            if cached is not None:
                result[item_id] = cached
        return result

    def prioritize_icons(self, session_id: str, item_ids: Sequence[int]) -> tuple[int, ...]:
        if (
            self._closing
            or str(session_id) != self._session_id
            or not self._catalogue_ready
        ):
            return ()
        accepted: list[int] = []
        to_queue: list[int] = []
        for raw_item_id in item_ids:
            item_id = int(raw_item_id)
            if item_id in self._failed_icon_ids:
                continue
            accepted.append(item_id)
            if self._cached_icon(item_id) is not None:
                continue
            if item_id in self._pending_icon_ids or item_id in self._inflight_icon_ids:
                self._priority_icon_ids.add(item_id)
                continue
            to_queue.append(item_id)
        self._queue_icon_ids(to_queue, priority=True, allow_processed=True)
        if accepted:
            self._schedule_continue(0)
        return tuple(accepted)

    def _saved_search_request(self, session_id: str) -> ItemCatalogSearchRequest:
        category, group = migrate_legacy_item_catalogue_filter(
            self._setting("ui/item_finder_category"),
            self._setting("ui/item_finder_group"),
        )
        return ItemCatalogSearchRequest(
            session_id,
            query=self._setting("ui/item_finder_search_text"),
            category=category,
            group=group,
            material_tag=self._setting("ui/item_finder_material_tag") or None,
            page_start=0,
            page_size=_INITIAL_PAGE_SIZE,
        )

    def _setting(self, key: str) -> str:
        if self._settings is None:
            return ""
        try:
            return str(self._settings.value(key, "") or "").strip()
        except Exception:
            return ""

    def _schedule_continue(self, delay_ms: int) -> None:
        if self._closing or not self._session_id:
            return
        if not self._continue_timer.isActive() or int(delay_ms) == 0:
            self._continue_timer.start(max(0, int(delay_ms)))

    @Slot()
    def _continue_warmup(self) -> None:
        if self._closing or not self._session_id or self._requests or self._threads:
            return
        if self._state == "scheduled":
            self._start_catalogue_build()
            return
        priority_pending = any(item_id in self._priority_icon_ids for item_id in self._pending_icons)
        if self._pending_icons:
            if not priority_pending and not self._background_work_allowed():
                self._schedule_continue(600)
                return
            self._start_icon_batch(priority=priority_pending)
            return
        if not self._initial_search_complete or self._enumeration_done:
            if self._enumeration_done:
                self._state = "ready"
            return
        if not self._background_work_allowed():
            self._schedule_continue(600)
            return
        self._start_catalogue_page()

    def _background_work_allowed(self) -> bool:
        if self._background_allowed is None:
            return True
        try:
            return bool(self._background_allowed())
        except Exception:
            return True

    def _start_catalogue_build(self) -> None:
        try:
            request_id = self._service.build_name_index(
                self._session_id,
                ui_generation=self._ui_generation,
            )
        except Exception:
            self._state = "failed"
            return
        self._state = "building"
        self._requests[request_id] = _WarmupRequest("build", self._generation)

    def _start_initial_search(self) -> None:
        request = self._initial_request
        if request is None:
            self._state = "failed"
            return
        try:
            request_id = self._service.search_item_catalog(
                request,
                ui_generation=self._ui_generation,
            )
        except Exception:
            self._state = "failed"
            return
        self._state = "initial_search"
        self._requests[request_id] = _WarmupRequest("initial_search", self._generation)

    def _start_catalogue_page(self) -> None:
        page_start = self._enumeration_page_start
        request = ItemCatalogSearchRequest(
            self._session_id,
            page_start=page_start,
            page_size=_CATALOGUE_PAGE_SIZE,
        )
        try:
            request_id = self._service.search_item_catalog(
                request,
                ui_generation=self._ui_generation,
            )
        except Exception:
            self._enumeration_done = True
            self._state = "ready"
            return
        self._state = "catalogue_scan"
        self._requests[request_id] = _WarmupRequest(
            "catalogue_page",
            self._generation,
            page_start=page_start,
        )

    def _start_icon_batch(self, *, priority: bool) -> None:
        batch_size = _VISIBLE_ICON_BATCH_SIZE if priority else _BACKGROUND_ICON_BATCH_SIZE
        batch = self._take_icon_batch(batch_size, priority=priority)
        if not batch:
            self._schedule_continue(0)
            return
        self._inflight_icon_ids.update(batch)
        try:
            request_id = self._service.load_item_icons(
                ItemIconBatchRequest(self._session_id, batch, thumbnail_size=120),
                ui_generation=self._ui_generation,
            )
        except Exception:
            self._inflight_icon_ids.difference_update(batch)
            self._mark_icons_failed(batch)
            self._schedule_continue(80)
            return
        self._state = "icon_warmup"
        self._requests[request_id] = _WarmupRequest(
            "icons",
            self._generation,
            item_ids=batch,
        )

    def _take_icon_batch(self, limit: int, *, priority: bool) -> tuple[int, ...]:
        pending = list(self._pending_icons)
        if priority:
            selected = [item_id for item_id in pending if item_id in self._priority_icon_ids][:limit]
        else:
            selected = pending[:limit]
        if not selected:
            return ()
        selected_set = set(selected)
        self._pending_icons = deque(item_id for item_id in pending if item_id not in selected_set)
        self._pending_icon_ids.difference_update(selected_set)
        return tuple(selected)

    def _queue_icon_ids(
        self,
        item_ids: Sequence[int],
        *,
        priority: bool,
        allow_processed: bool = False,
    ) -> None:
        ordered: list[int] = []
        seen: set[int] = set()
        for raw_item_id in item_ids:
            item_id = int(raw_item_id)
            if item_id in seen or item_id in self._failed_icon_ids:
                continue
            seen.add(item_id)
            if not allow_processed and item_id in self._processed_icon_ids:
                continue
            if self._cached_icon(item_id) is not None or item_id in self._inflight_icon_ids:
                if priority:
                    self._priority_icon_ids.add(item_id)
                continue
            ordered.append(item_id)
        if not ordered:
            return
        if priority:
            self._priority_icon_ids.update(ordered)
            requested = set(ordered)
            retained = [item_id for item_id in self._pending_icons if item_id not in requested]
            self._pending_icons = deque((*ordered, *retained))
            self._pending_icon_ids.update(ordered)
            return
        for item_id in ordered:
            if item_id in self._pending_icon_ids:
                continue
            self._pending_icons.append(item_id)
            self._pending_icon_ids.add(item_id)

    @Slot(str, str, object)
    def _handle_result(self, request_id: str, _operation: str, result: object) -> None:
        tracked = self._requests.pop(request_id, None)
        if tracked is None or tracked.generation != self._generation or self._closing:
            return
        if tracked.kind == "build" and isinstance(result, BuildNameIndexResult):
            if result.session_id != self._session_id or not result.available:
                self._state = "failed"
                return
            self._catalogue_ready = True
            self._start_initial_search()
            return
        if tracked.kind in {"initial_search", "catalogue_page"} and isinstance(result, ItemCatalogSearchResult):
            if result.session_id != self._session_id:
                self._state = "failed"
                return
            if tracked.kind == "initial_search":
                self._publish_initial_search(result)
            else:
                self._publish_catalogue_page(result, tracked.page_start)
            return
        if tracked.kind == "icons" and isinstance(result, ItemIconBatchResult):
            self._publish_icon_sources(result, tracked.item_ids)
            return
        self._handle_tracked_failure(tracked)

    def _publish_initial_search(self, result: ItemCatalogSearchResult) -> None:
        request = self._initial_request
        if request is not None:
            self._remember_search(request, result)
        self._initial_search_complete = True
        self._enumeration_page_start = 0
        initial_ids = tuple(row.item_id for row in result.items if row.icon_paths)
        self._startup_item_ids.update(initial_ids)
        self._queue_icon_ids(initial_ids, priority=True)
        self._schedule_continue(0)

    def _publish_catalogue_page(self, result: ItemCatalogSearchResult, page_start: int) -> None:
        if page_start == 0:
            self._remember_search(
                ItemCatalogSearchRequest(
                    self._session_id,
                    page_start=0,
                    page_size=_CATALOGUE_PAGE_SIZE,
                ),
                result,
            )
        self._queue_icon_ids(
            tuple(row.item_id for row in result.items if row.icon_paths),
            priority=False,
        )
        next_start = page_start + len(result.items)
        if not result.items or next_start >= result.total_matches:
            self._enumeration_done = True
        else:
            self._enumeration_page_start = next_start
        self._schedule_continue(80)

    def _publish_icon_sources(self, result: ItemIconBatchResult, requested_ids: tuple[int, ...]) -> None:
        if result.session_id != self._session_id:
            self._inflight_icon_ids.difference_update(requested_ids)
            self._mark_icons_failed(requested_ids)
            self._schedule_continue(80)
            return
        returned = {item.item_id: item for item in result.items}
        sources: dict[int, str] = {}
        failed: list[int] = []
        for item_id in requested_ids:
            item = returned.get(item_id)
            source = (item.png_path or item.source_path) if item is not None else None
            if source:
                sources[item_id] = source
            else:
                failed.append(item_id)
        if failed:
            self._inflight_icon_ids.difference_update(failed)
            self._mark_icons_failed(failed)
        if not sources:
            self._schedule_continue(80)
            return
        self._start_decode_worker(sources, requested_ids=tuple(sources))

    def _start_decode_worker(self, sources: dict[int, str], *, requested_ids: tuple[int, ...]) -> None:
        thread = QThread(self)
        thread.setObjectName("remote_item_finder_icon_warmup")
        worker = ArchiveItemThumbnailWorker(
            self._generation,
            sources,
            self.thread(),
            max_dimension=120,
        )
        worker.moveToThread(thread)
        self._threads[thread] = _WarmupThread(worker, self._generation, requested_ids)
        thread.started.connect(worker.run)
        worker.icon_ready.connect(self._handle_icon_ready)
        worker.icon_failed.connect(self._handle_icon_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._handle_thread_finished, Qt.QueuedConnection)
        try:
            thread.start(QThread.LowPriority)
        except Exception:
            thread.start()

    @Slot(int, int, str, object)
    def _handle_icon_ready(self, generation: int, item_id: int, path: str, image: object) -> None:
        if (
            generation != self._generation
            or self._closing
            or not isinstance(image, QImage)
            or image.isNull()
        ):
            return
        item_id = int(item_id)
        self._cache_icon(item_id, str(path), image)
        self._processed_icon_ids.add(item_id)
        self._failed_icon_ids.discard(item_id)
        self._priority_icon_ids.discard(item_id)
        self._inflight_icon_ids.discard(item_id)
        self.iconsReady.emit(self._session_id, (item_id,))

    @Slot(int, int, str)
    def _handle_icon_failed(self, generation: int, item_id: int, _message: str) -> None:
        if generation != self._generation or self._closing:
            return
        self._inflight_icon_ids.discard(int(item_id))
        self._mark_icons_failed((int(item_id),))

    def _handle_thread_finished(self) -> None:
        thread = self.sender()
        if isinstance(thread, QThread):
            self._cleanup_thread(thread)

    def _cleanup_thread(self, thread: QThread) -> None:
        if not thread.wait(0):
            QTimer.singleShot(1, lambda thread=thread: self._cleanup_thread(thread))
            return
        handle = self._threads.pop(thread, None)
        thread.deleteLater()
        if handle is None:
            return
        if handle.generation == self._generation and not self._closing:
            remaining = tuple(item_id for item_id in handle.item_ids if item_id in self._inflight_icon_ids)
            self._inflight_icon_ids.difference_update(remaining)
            if remaining:
                self._mark_icons_failed(remaining)
        if not self._threads and not self._closing:
            self._schedule_continue(40)

    def _cache_icon(self, item_id: int, path: str, image: QImage) -> None:
        cache = self._startup_icon_cache if item_id in self._startup_item_ids else self._icon_cache
        cache[item_id] = (path, image)
        cache.move_to_end(item_id)
        limit = _INITIAL_PAGE_SIZE if cache is self._startup_icon_cache else _MEMORY_ICON_LIMIT
        while len(cache) > limit:
            cache.popitem(last=False)

    def _cached_icon(self, item_id: int) -> tuple[str, QImage] | None:
        cached = self._startup_icon_cache.get(item_id)
        if cached is not None:
            return cached
        cached = self._icon_cache.get(item_id)
        if cached is not None:
            self._icon_cache.move_to_end(item_id)
        return cached

    def _remember_search(
        self,
        request: ItemCatalogSearchRequest,
        result: ItemCatalogSearchResult,
    ) -> None:
        self._search_cache[request] = result
        self._search_cache.move_to_end(request)
        while len(self._search_cache) > _SEARCH_CACHE_LIMIT:
            self._search_cache.popitem(last=False)

    @Slot(str, object)
    def _handle_failure(self, request_id: str, _error: object) -> None:
        tracked = self._requests.pop(request_id, None)
        if tracked is not None and tracked.generation == self._generation:
            self._handle_tracked_failure(tracked)

    @Slot(str)
    def _handle_cancelled(self, request_id: str) -> None:
        tracked = self._requests.pop(request_id, None)
        if tracked is not None and tracked.generation == self._generation:
            self._handle_tracked_failure(tracked)

    def _handle_tracked_failure(self, tracked: _WarmupRequest) -> None:
        if tracked.kind == "icons":
            self._inflight_icon_ids.difference_update(tracked.item_ids)
            self._mark_icons_failed(tracked.item_ids)
            self._schedule_continue(250)
        elif tracked.kind == "catalogue_page":
            self._enumeration_done = True
            self._state = "ready"
        else:
            self._state = "failed"

    def _mark_icons_failed(self, item_ids: Sequence[int]) -> None:
        failed = tuple(dict.fromkeys(int(item_id) for item_id in item_ids))
        if not failed:
            return
        self._failed_icon_ids.update(failed)
        self._processed_icon_ids.update(failed)
        self._priority_icon_ids.difference_update(failed)
        self.iconsFailed.emit(self._session_id, failed)


__all__ = ["RemoteItemFinderWarmupController"]
