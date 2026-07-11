from __future__ import annotations

import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from cdmw.models import ArchiveEntry, AssetFamilyGraph, RunCancelled
from cdmw.ui.archive_browser.attachment_task_controller import (
    AttachmentTaskController,
    attachment_task_controller_for_guard,
)
from cdmw.ui.archive_browser.attachment_plan import ArchiveAttachmentPlanMixin
from cdmw.ui.shell.utility_controller import UtilityControllerMixin
from cdmw.workers.attachment_io_workers import (
    AttachmentContextRequest,
    AttachmentPayloadReadRequest,
    AttachmentPayloadReadResult,
    run_attachment_context_resolution,
    run_attachment_payload_read,
)
from cdmw.workers.attachment_loose_workers import (
    AttachmentLoosePreflightRequest,
    AttachmentLoosePreflightResult,
    prepare_attachment_loose_targets,
)
from cdmw.workers.directory_scan_workers import DirectoryScanResult


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_for(app: QApplication, predicate: object, timeout: float = 5.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


class _UtilityOwner(UtilityControllerMixin, QObject):
    def __init__(self) -> None:
        QObject.__init__(self)
        self.worker_thread = None
        self.utility_worker = None
        self._utility_completion_handler = None
        self._utility_error_handler = None
        self._utility_updates_archive_progress = False

    def _background_task_active(self) -> bool:
        return self.worker_thread is not None

    def set_status_message(self, *_args: object, **_kwargs: object) -> None:
        pass

    def append_log(self, *_args: object, **_kwargs: object) -> None:
        pass

    def set_busy(self, *_args: object, **_kwargs: object) -> None:
        pass

    def _handle_utility_log_message(self, _message: str) -> None:
        pass

    def _handle_utility_progress_changed(self, _current: int, _total: int, _detail: str) -> None:
        pass

    def _handle_worker_error(self, message: str) -> None:
        if self._utility_error_handler is not None:
            self._utility_error_handler(message)

    def _cleanup_worker_refs(self) -> None:
        self.worker_thread = None
        self.utility_worker = None
        self._utility_completion_handler = None
        self._utility_error_handler = None


def _archive_entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(path, Path("archive.pamt"), Path("0.paz"), 1, 1, 1, 0, 0)


class _PlacementOwner(ArchiveAttachmentPlanMixin, _UtilityOwner):
    def __init__(self) -> None:
        super().__init__()
        self.archive_entries_by_normalized_path = {}
        self.archive_entries_by_basename = {}
        self.archive_item_asset_catalog = ()
        self._shutting_down = False

    def append_archive_log(self, *_args: object, **_kwargs: object) -> None:
        pass

    def _reset_archive_load_progress(self) -> None:
        pass

    def _set_archive_load_progress(self, *_args: object, **_kwargs: object) -> None:
        pass

    def _build_archive_asset_family_graph_from_snapshots(
        self,
        entry: ArchiveEntry,
        **_kwargs: object,
    ) -> tuple[AssetFamilyGraph, tuple[object, ...]]:
        time.sleep(0.08)
        return AssetFamilyGraph(root_path=entry.path, family_key=entry.basename, summary=""), ()

    def _attachment_package_weapon_subclass_tokens(
        self,
        *_args: object,
        stop_event: threading.Event | None = None,
        **_kwargs: object,
    ) -> set[str]:
        if stop_event is not None and stop_event.is_set():
            raise RunCancelled("Attachment placement preparation cancelled.")
        return set()

    def _attachment_socket_entry_from_selection(self, _graph: object) -> None:
        return None

    def _attachment_package_graph_entries(self, entry: ArchiveEntry, _graph: object) -> list[ArchiveEntry]:
        return [entry]

    def _attachment_visual_model_entry(self, entry: ArchiveEntry, _graph: object) -> ArchiveEntry:
        return entry

    def _attachment_package_material_sidecar_for_model(self, *_args: object) -> None:
        return None

    def _attachment_package_item_icon_entries(self, *_args: object) -> list[ArchiveEntry]:
        return []

    def _attachment_package_target_support_entries(self, *_args: object) -> list[object]:
        return []

    def _remember_archive_asset_family_graph(self, *_args: object) -> None:
        pass

    @staticmethod
    def _attachment_package_entry_key(entry: ArchiveEntry) -> tuple[str, str, int]:
        return entry.path.casefold(), str(entry.pamt_path).casefold(), entry.offset


def test_attachment_payload_reader_is_bounded_and_cancellable(tmp_path: Path) -> None:
    payload_path = tmp_path / "profile.xml"
    payload_path.write_bytes(b"<profile />")
    result = run_attachment_payload_read(AttachmentPayloadReadRequest(file_path=payload_path))
    assert result.data == b"<profile />"
    assert result.source_path == str(payload_path)

    try:
        run_attachment_payload_read(
            AttachmentPayloadReadRequest(file_path=payload_path, max_bytes=4)
        )
    except ValueError as exc:
        assert "maximum 4" in str(exc)
    else:
        raise AssertionError("attachment payload reader must enforce its byte ceiling")

    stop_event = threading.Event()
    stop_event.set()
    try:
        run_attachment_payload_read(
            AttachmentPayloadReadRequest(file_path=payload_path),
            stop_event=stop_event,
        )
    except RunCancelled:
        pass
    else:
        raise AssertionError("pre-cancelled attachment payload read must stop")


def test_attachment_context_resolver_honors_pre_cancel() -> None:
    stop_event = threading.Event()
    stop_event.set()
    called = False

    def resolver(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    try:
        run_attachment_context_resolution(
            AttachmentContextRequest(
                target_graph=AssetFamilyGraph(root_path="", family_key="", summary=""),
                target_evidence=None,
                target_model_entry=None,
                target_socket_entry=None,
            ),
            resolver=resolver,
            stop_event=stop_event,
        )
    except RunCancelled:
        pass
    else:
        raise AssertionError("pre-cancelled attachment context resolution must stop")
    assert not called


def test_attachment_controller_dispatches_slow_io_under_50_ms() -> None:
    app = _app()
    owner = _UtilityOwner()
    dialog = QDialog()
    controller = AttachmentTaskController(owner, dialog)
    main_thread = threading.get_ident()
    worker_threads: list[int] = []
    completed: list[AttachmentPayloadReadResult] = []

    def slow_operation(
        request: AttachmentPayloadReadRequest,
        *,
        stop_event: threading.Event,
    ) -> AttachmentPayloadReadResult:
        worker_threads.append(threading.get_ident())
        time.sleep(0.15)
        return AttachmentPayloadReadResult(request.request_id, "slow", b"ok")

    before = time.perf_counter()
    assert controller.start(
        AttachmentPayloadReadRequest(),
        slow_operation,
        status_message="Reading...",
        on_complete=completed.append,
        on_error=lambda message: (_ for _ in ()).throw(AssertionError(message)),
    )
    assert (time.perf_counter() - before) * 1000.0 < 50.0
    assert _wait_for(app, lambda: len(completed) == 1)
    assert len(worker_threads) == 1
    assert worker_threads[0] != main_thread
    assert owner.worker_thread is None
    dialog.deleteLater()
    app.processEvents()


def test_attachment_controller_close_cancels_and_rejects_stale_result() -> None:
    app = _app()
    owner = _UtilityOwner()
    dialog = QDialog()
    controller = attachment_task_controller_for_guard(owner, dialog)
    started = threading.Event()
    cancelled = threading.Event()
    completed: list[object] = []

    def cancellable(
        request: AttachmentPayloadReadRequest,
        *,
        stop_event: threading.Event,
    ) -> AttachmentPayloadReadResult:
        started.set()
        if stop_event.wait(2.0):
            cancelled.set()
            raise RunCancelled("Attachment payload read cancelled.")
        return AttachmentPayloadReadResult(request.request_id, "slow", b"late")

    assert controller.start(
        AttachmentPayloadReadRequest(),
        cancellable,
        status_message="Reading...",
        on_complete=completed.append,
        on_error=lambda _message: None,
    )
    assert started.wait(1.0)
    before = time.perf_counter()
    dialog.reject()
    app.processEvents()
    assert (time.perf_counter() - before) * 1000.0 < 50.0
    assert cancelled.wait(1.0)
    assert _wait_for(app, lambda: owner.worker_thread is None)
    assert completed == []
    assert controller.iter_shutdown_workers() == ()
    dialog.deleteLater()
    app.processEvents()


def test_attachment_placement_preflight_is_latest_wins_and_cancel_drains() -> None:
    app = _app()
    owner = _PlacementOwner()
    first = _archive_entry("character/model/first.pac")
    latest = _archive_entry("character/model/latest.pac")
    first_results: list[object] = []
    latest_results: list[object] = []

    assert owner._run_archive_attachment_placement_prepare(
        first,
        None,
        status_message="Preparing first...",
        on_prepared=first_results.append,
    )
    before = time.perf_counter()
    assert owner._run_archive_attachment_placement_prepare(
        latest,
        None,
        status_message="Preparing latest...",
        on_prepared=latest_results.append,
    )
    assert (time.perf_counter() - before) * 1000.0 < 50.0
    assert _wait_for(app, lambda: bool(latest_results), timeout=3.0)
    assert first_results == []
    assert latest_results[0].target_entry.path == latest.path
    assert latest_results[0].request_id == 2
    assert _wait_for(app, lambda: owner.worker_thread is None)

    cancelled_results: list[object] = []
    assert owner._run_archive_attachment_placement_prepare(
        first,
        None,
        status_message="Preparing cancel...",
        on_prepared=cancelled_results.append,
    )
    before = time.perf_counter()
    owner._cancel_archive_attachment_placement_prepare()
    assert (time.perf_counter() - before) * 1000.0 < 50.0
    assert _wait_for(app, lambda: owner.worker_thread is None)
    assert cancelled_results == []


def test_attachment_loose_preflight_keeps_slow_discovery_and_large_candidate_scan_responsive(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    import cdmw.workers.attachment_loose_workers as loose_workers

    app = _app()
    owner = _UtilityOwner()
    dialog = QDialog()
    controller = AttachmentTaskController(owner, dialog)
    target = _archive_entry("character/model/test_weapon.pac")
    package_root = tmp_path / "package"
    files_root = package_root / "files"
    model = files_root / "character" / "model" / "test_weapon.pac"
    sidecar = files_root / "character" / "modelproperty" / "test_weapon.pac_xml"
    texture = files_root / "character" / "texture" / "test_weapon_base.dds"
    model.parent.mkdir(parents=True)
    sidecar.parent.mkdir(parents=True)
    texture.parent.mkdir(parents=True)
    model.write_bytes(b"PAC")
    sidecar.write_text('<Texture Path="character/texture/test_weapon_base.dds"/>', encoding="utf-8")
    texture.write_bytes(b"DDS")
    main_thread = threading.get_ident()
    worker_threads: list[int] = []
    original_iterdir = Path.iterdir
    original_read = loose_workers.read_text_file_cancellable

    def slow_iterdir(path: Path) -> object:
        worker_threads.append(threading.get_ident())
        time.sleep(0.08)
        return original_iterdir(path)

    def slow_read(*args: object, **kwargs: object) -> str:
        worker_threads.append(threading.get_ident())
        time.sleep(0.08)
        return original_read(*args, **kwargs)

    large_candidates = tuple(Path(f"irrelevant/candidate-{index}.hkx") for index in range(100_000))

    def large_scan(*_args: object, **_kwargs: object) -> DirectoryScanResult:
        worker_threads.append(threading.get_ident())
        return DirectoryScanResult(large_candidates, len(large_candidates), 0, False)

    monkeypatch.setattr(Path, "iterdir", slow_iterdir)
    monkeypatch.setattr(loose_workers, "read_text_file_cancellable", slow_read)
    monkeypatch.setattr(loose_workers, "scan_directory_files", large_scan)
    completed: list[AttachmentLoosePreflightResult] = []
    heartbeat: list[float] = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeat.append(time.perf_counter()))
    timer.start()
    before = time.perf_counter()
    assert controller.start(
        AttachmentLoosePreflightRequest(
            target_entry=target,
            output_root_paths=(str(package_root),),
            material_sidecar_paths=("character/modelproperty/test_weapon.pac_xml",),
            archive_entries_by_normalized_path={target.path.casefold(): (target,)},
        ),
        prepare_attachment_loose_targets,
        status_message="Preparing loose target...",
        on_complete=completed.append,
        on_error=lambda message: (_ for _ in ()).throw(AssertionError(message)),
    )
    assert (time.perf_counter() - before) * 1000.0 < 50.0
    assert _wait_for(app, lambda: bool(completed), timeout=5.0)
    timer.stop()
    assert worker_threads and all(thread_id != main_thread for thread_id in worker_threads)
    assert len(heartbeat) >= 5
    assert max(b - a for a, b in zip(heartbeat, heartbeat[1:])) < 0.2
    specs = completed[0].roots[0].specs
    assert any(spec.target_path == "character/texture/test_weapon_base.dds" for spec in specs)
    dialog.deleteLater()
    app.processEvents()


def test_attachment_ui_io_paths_dispatch_or_use_prepared_payloads() -> None:
    diff_source = Path(
        "cdmw/ui/archive_browser/attachment_placement_diff_dialog.py"
    ).read_text(encoding="utf-8")
    socket_source = Path("cdmw/ui/archive_browser/attachment_socket_editor.py").read_text(
        encoding="utf-8"
    )
    plan_source = Path("cdmw/ui/archive_browser/attachment_plan.py").read_text(encoding="utf-8")
    loose_worker_source = Path("cdmw/workers/attachment_loose_workers.py").read_text(encoding="utf-8")

    assert "read_archive_entry_data" not in diff_source
    assert ".read_bytes()" not in diff_source
    assert "read_archive_entry_data" not in socket_source
    assert ".read_bytes()" not in socket_source
    assert "start_attachment_profile_import(" in diff_source
    assert "AttachmentPreparedPayloads(preparation)" in diff_source
    assert "run_attachment_payload_read(" in plan_source
    assert "archive_payloads=tuple(archive_payloads)" in plan_source
    assert "prepare_attachment_loose_targets(" in plan_source
    assert "target_loose_roots=loose_result.roots" in plan_source
    assert "_attachment_package_loose_target_roots_for_entry" not in diff_source
    assert "DirectoryScanWorker" not in diff_source
    assert "read_text_file_cancellable(" in loose_worker_source
