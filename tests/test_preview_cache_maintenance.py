import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin
from cdmw.ui.archive_browser.preview_settings import ArchivePreviewSettingsMixin
from cdmw.ui.archive_browser.preview_cache_maintenance import PreviewCacheMaintenanceController
from cdmw.workers import preview_cache_maintenance as worker
from tests.test_native_preview_package_cache_concurrency import _raw_cache_entry


def _pump_until(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


class _Owner(QObject, ArchivePreviewCacheMixin, ArchivePreviewSettingsMixin):
    def __init__(self, root):
        super().__init__()
        self.root = root
        self.messages = []
        self.delivery_threads = []
        self.shell = SimpleNamespace(
            settings_file_path=root / "settings.ini",
            append_archive_log=self.record,
            set_status_message=self.record,
        )
        self.archive_preview_cache = {"old": object()}
        self.archive_preview_cache_keys = ["old"]

    def record(self, message):
        self.messages.append(message)
        self.delivery_threads.append(threading.get_ident())

    def _native_preview_package_cache_root(self):
        return self.root


def test_clear_button_keeps_qt_alive_and_delivers_completion_on_gui_thread(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    owner = _Owner(tmp_path)
    entry = _raw_cache_entry(tmp_path, "expired")
    started, release = threading.Event(), threading.Event()
    threads = []
    real_clear = worker.clear_native_preview_package_cache_tiers

    def delayed_clear(root):
        threads.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        real_clear(root)

    monkeypatch.setattr(worker, "clear_native_preview_package_cache_tiers", delayed_clear)
    monkeypatch.setattr(worker, "clear_pac_xml_profile_index_cache", lambda root: threads.append(threading.get_ident()))
    ticks = []
    heartbeat = QTimer()
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: ticks.append(1))
    heartbeat.start()
    try:
        owner._handle_clear_archive_preview_cache_requested()
        assert not owner.archive_preview_cache
        _pump_until(app, lambda: started.is_set() and len(ticks) >= 3)
        assert not release.is_set()
        assert not owner.messages, "completion was reported before disk cleanup"
        assert entry.exists()
        assert owner._preview_cache_maintenance.iter_shutdown_workers()
        release.set()
        _pump_until(app, lambda: "Archive preview cache cleared." in owner.messages)
        assert not entry.exists()
        assert all(value != threading.get_ident() for value in threads)
        assert set(owner.delivery_threads) == {threading.get_ident()}
    finally:
        heartbeat.stop()
        release.set()
        owner._preview_cache_maintenance.request_shutdown()
        _pump_until(app, lambda: not owner._preview_cache_maintenance.iter_shutdown_workers())


def test_cache_mode_requests_coalesce_and_run_serially(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    owner = _Owner(tmp_path)
    controller = PreviewCacheMaintenanceController(owner, owner.shell)
    started, release = threading.Event(), threading.Event()
    budgets = []

    def prune(root, *, max_bytes, target_bytes):
        budgets.append(max_bytes)
        if len(budgets) == 1:
            started.set()
            assert release.wait(5)

    monkeypatch.setattr(worker, "prune_native_preview_package_cache_tiers", prune)
    try:
        controller.request(worker.PreviewCacheMaintenanceRequest(tmp_path, max_bytes=10, target_bytes=5))
        _pump_until(app, started.is_set)
        for budget in range(100, 200):
            controller.request(worker.PreviewCacheMaintenanceRequest(tmp_path, max_bytes=budget, target_bytes=5))
        assert len(controller._pending) == 1
        release.set()
        _pump_until(app, lambda: controller._active is None and not controller.iter_shutdown_workers())
        assert budgets == [10, 199]
    finally:
        release.set()
        controller.request_shutdown()
        _pump_until(app, lambda: not controller.iter_shutdown_workers())


def test_shutdown_discards_queued_requests_and_late_completion(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    owner = _Owner(tmp_path)
    started, release = threading.Event(), threading.Event()
    calls = []

    def clear(root):
        calls.append(root)
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(worker, "clear_native_preview_package_cache_tiers", clear)
    monkeypatch.setattr(worker, "clear_pac_xml_profile_index_cache", lambda root: None)
    owner._handle_clear_archive_preview_cache_requested()
    controller = owner._preview_cache_maintenance
    try:
        _pump_until(app, started.is_set)
        owner._handle_clear_archive_preview_cache_requested()
        controller.request_shutdown()
        assert not controller._pending
        assert controller.iter_shutdown_workers()
    finally:
        release.set()
        _pump_until(app, lambda: controller._active is None and not controller.iter_shutdown_workers())
    assert len(calls) == 1
    assert not owner.messages


def test_clear_failure_is_reported_without_success(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    owner = _Owner(tmp_path)

    def fail(root):
        raise OSError("cache cleanup denied")

    monkeypatch.setattr(worker, "clear_native_preview_package_cache_tiers", fail)
    owner._handle_clear_archive_preview_cache_requested()
    controller = owner._preview_cache_maintenance
    try:
        _pump_until(app, lambda: controller._active is None and not controller.iter_shutdown_workers())
        assert owner.messages == ["cache cleanup denied", "cache cleanup denied"]
    finally:
        controller.request_shutdown()
