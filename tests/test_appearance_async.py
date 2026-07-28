from __future__ import annotations

import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QDialog

from cdmw.core.archive import build_archive_entry_basename_index, build_archive_entry_path_index
from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.ui.shell.request_task_controller import RequestTaskController
from cdmw.ui.shell.utility_controller import UtilityControllerMixin
from cdmw.workers.appearance_workers import (
    AppearanceCompositePlanRequest,
    AppearanceExactMatchRequest,
    AppearanceExactMatchResult,
    run_appearance_composite_plan,
    run_appearance_exact_match,
)


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


def _entries(tmp_path: Path, payloads: tuple[tuple[str, bytes], ...]) -> tuple[ArchiveEntry, ...]:
    paz_path = tmp_path / "0.paz"
    pamt_path = tmp_path / "0.pamt"
    offset = 0
    entries: list[ArchiveEntry] = []
    with paz_path.open("wb") as handle:
        for path, payload in payloads:
            handle.write(payload)
            entries.append(ArchiveEntry(path, pamt_path, paz_path, offset, len(payload), len(payload), 0, 0))
            offset += len(payload)
    return tuple(entries)


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


def test_exact_appearance_match_is_index_scoped_and_cancellable(tmp_path: Path) -> None:
    donor, match, nonmatch = _entries(
        tmp_path,
        (
            ("character/model/target_body.pac", b"PAR "),
            ("character/appearance/a.app_xml", b'<Appearance><Nude Name="target_body" /></Appearance>'),
            ("character/appearance/b.app_xml", b'<Appearance><Nude Name="different" /></Appearance>'),
        ),
    )
    result = run_appearance_exact_match(AppearanceExactMatchRequest(donor, (match, nonmatch)))
    assert result.candidates == (match,)

    stop_event = threading.Event()
    stop_event.set()
    try:
        run_appearance_exact_match(
            AppearanceExactMatchRequest(donor, (match, nonmatch)),
            stop_event=stop_event,
        )
    except RunCancelled:
        pass
    else:
        raise AssertionError("pre-cancelled appearance search must stop")


def test_composite_plan_runs_from_frozen_snapshot(tmp_path: Path) -> None:
    app_entry, model_entry = _entries(
        tmp_path,
        (
            ("character/appearance/body.app_xml", b'<Appearance><Nude><Prefab Name="body" /></Nude></Appearance>'),
            ("character/model/body.pac", b"PAR "),
        ),
    )
    entries = (app_entry, model_entry)
    request = AppearanceCompositePlanRequest(
        app_entry,
        model_entry,
        entries,
        build_archive_entry_path_index(entries),
        build_archive_entry_basename_index(entries),
    )
    result = run_appearance_composite_plan(request)
    assert result.request is request
    assert result.plan.appearance_entry is app_entry


#: Well under the 2 s the operation blocks for, and well above the thread
#: setup a loaded runner needs. It is a delegation check, not a benchmark.
_DELEGATION_BUDGET_MS = 500.0


def test_appearance_controller_delegates_immediately_and_rejects_close() -> None:
    app = _app()
    owner = _UtilityOwner()
    dialog = QDialog()
    controller = RequestTaskController(owner, dialog, worker_label="appearance")
    started = threading.Event()
    cancelled = threading.Event()
    completed: list[object] = []

    def slow_operation(
        request: AppearanceExactMatchRequest,
        *,
        stop_event: threading.Event,
    ) -> AppearanceExactMatchResult:
        started.set()
        if stop_event.wait(2.0):
            cancelled.set()
            raise RunCancelled("Appearance search cancelled.")
        return AppearanceExactMatchResult(request.request_id, request.donor_model_entry, ())

    placeholder = ArchiveEntry("body.pac", Path("0.pamt"), Path("0.paz"), 0, 0, 0, 0, 0)
    before = time.perf_counter()
    assert controller.start(
        AppearanceExactMatchRequest(placeholder, ()),
        slow_operation,
        status_message="Searching...",
        on_complete=completed.append,
        on_error=lambda _message: None,
    )
    # The point is that start() hands the work to a thread instead of running it
    # inline, and the operation blocks for 2 s, so anything far below that proves
    # it. The old budget was 50 ms, which measured how busy the machine was: a
    # loaded CI runner took 158 ms to create the thread and failed a test about
    # delegation. `completed` staying empty is the assertion that actually says
    # the work had not run.
    assert (time.perf_counter() - before) * 1000.0 < _DELEGATION_BUDGET_MS
    assert not completed
    assert started.wait(1.0)
    before = time.perf_counter()
    controller.request_shutdown()
    assert (time.perf_counter() - before) * 1000.0 < _DELEGATION_BUDGET_MS
    assert cancelled.wait(1.0)
    assert _wait_for(app, lambda: owner.worker_thread is None)
    assert completed == []
    assert controller.iter_shutdown_workers() == ()
    dialog.deleteLater()
    app.processEvents()


def test_appearance_ui_only_dispatches_worker_plans() -> None:
    swap_source = Path("cdmw/ui/archive_browser/appearance_swap.py").read_text(encoding="utf-8")
    common_source = Path("cdmw/ui/archive_browser/appearance_common.py").read_text(encoding="utf-8")

    assert "build_appearance_composite_preview_plan(" not in swap_source
    assert "build_appearance_single_pac_swap_plan(" not in swap_source
    assert "run_appearance_composite_plan" in swap_source
    assert "run_appearance_swap_plan" in swap_source
    assert 'extension_index.get(".app_xml"' in swap_source
    assert "stop_event=stop_event" in common_source
