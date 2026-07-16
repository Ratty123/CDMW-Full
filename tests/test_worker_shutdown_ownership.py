from __future__ import annotations

import os
import threading
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.ui.model_library.tab import ModelLibraryTab
from cdmw.ui.recolor_variants_tab import RecolorVariantBuildWorker, RecolorVariantsTab
from cdmw.ui.texture_workflow.editor_worker_lifecycle import TextureEditorWorkerLifecycleMixin
from cdmw.models import RunCancelled


class _Timer:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _Thread:
    def __init__(self) -> None:
        self.interrupted = False
        self.quit_requested = False

    def isRunning(self) -> bool:
        return True

    def requestInterruption(self) -> None:
        self.interrupted = True

    def quit(self) -> None:
        self.quit_requested = True


class _StopEvent:
    def __init__(self) -> None:
        self.set_called = False

    def set(self) -> None:
        self.set_called = True


def test_model_library_shutdown_cancels_task_and_native_preview() -> None:
    thread = _Thread()
    stop_event = _StopEvent()

    class Owner:
        request_shutdown = ModelLibraryTab.request_shutdown
        iter_shutdown_workers = ModelLibraryTab.iter_shutdown_workers

        def __init__(self) -> None:
            self._auto_preview_timer = _Timer()
            self._results_filter_timer = _Timer()
            self._results_population_timer = _Timer()
            self._pending_inline_preview_request = object()
            self._pending_results_rows = [object()]
            self._stop_event = stop_event
            self._task_thread = thread
            self._task_worker = object()
            self.preview_stopped = False

        def _stop_inline_d3d11_process(self, **kwargs: object) -> None:
            self.preview_stopped = kwargs == {"cleanup_packages": True}

    owner = Owner()
    assert owner.iter_shutdown_workers() == (("task", thread, owner._task_worker),)

    owner.request_shutdown()

    assert stop_event.set_called
    assert thread.interrupted
    assert not thread.quit_requested
    assert owner.preview_stopped
    assert owner._pending_inline_preview_request is None
    assert owner._pending_results_rows == []


def test_recolor_shutdown_stops_and_tracks_build_worker() -> None:
    thread = _Thread()
    worker = object()

    class Owner:
        request_shutdown = RecolorVariantsTab.request_shutdown
        iter_shutdown_workers = RecolorVariantsTab.iter_shutdown_workers

        def __init__(self) -> None:
            self.worker_thread = thread
            self.build_worker = worker
            self.stop_called = False

        def stop_build(self) -> None:
            self.stop_called = True

    owner = Owner()
    assert owner.iter_shutdown_workers() == (("build", thread, worker),)

    owner.request_shutdown()

    assert owner.stop_called
    assert thread.interrupted and thread.quit_requested


def test_recolor_build_worker_stops_cooperatively_under_load() -> None:
    started = threading.Event()

    def build(*_args: object, stop_event: threading.Event, **_kwargs: object) -> object:
        started.set()
        assert stop_event.wait(2.0)
        raise RunCancelled("cancelled")

    worker = RecolorVariantBuildWorker(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        Path("unused"),
        (),
        overwrite_existing=False,
    )
    with mock.patch("cdmw.workers.recolor_variant_workers.build_recolor_variant_outputs", side_effect=build):
        runner = threading.Thread(target=worker.run)
        runner.start()
        assert started.wait(1.0)
        worker.stop()
        runner.join(1.0)

    assert not runner.is_alive()


def test_archive_picker_close_paths_never_wait_on_preview_threads() -> None:
    for relative_path in (
        "cdmw/ui/archive_browser/source_picker_dialog.py",
        "cdmw/ui/archive_browser/attachment_donor_picker_dialog.py",
    ):
        source = Path(relative_path).read_text(encoding="utf-8")
        assert ".wait(" not in source


def test_texture_editor_shutdown_releases_history_encoder() -> None:
    class Owner(TextureEditorWorkerLifecycleMixin):
        _task_worker = None
        _task_thread = None
        _ui_constraint_worker = None
        _ui_constraint_thread = None

        def flush_settings_save(self) -> None:
            return

    with mock.patch(
        "cdmw.ui.texture_workflow.editor_worker_lifecycle.shutdown_texture_editor_history_encoder"
    ) as shutdown_encoder:
        Owner().request_shutdown()

    shutdown_encoder.assert_called_once_with()


def test_texture_editor_shutdown_clears_resident_texture_patch_when_owned() -> None:
    class Owner(TextureEditorWorkerLifecycleMixin):
        _task_worker = None
        _task_thread = None
        _ui_constraint_worker = None
        _ui_constraint_thread = None

        def __init__(self) -> None:
            self.patch_cleared = False

        def _clear_resident_texture_patch_state(self) -> None:
            self.patch_cleared = True

        def flush_settings_save(self) -> None:
            return

    owner = Owner()
    owner.request_shutdown()

    assert owner.patch_cleared
