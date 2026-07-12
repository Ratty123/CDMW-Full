from __future__ import annotations

from types import SimpleNamespace

import pytest

from cdmw.ui.archive_browser import filter_workers as filter_workers_module
from cdmw.ui.archive_browser import workers as preview_workers_module
from cdmw.ui.archive_browser.filter_workers import ArchiveFilterWorkerMixin
from cdmw.ui.archive_browser.static_replacement_d3d11_request_state import (
    alignment_d3d11_clear_original_texture_worker_refs,
    alignment_d3d11_clear_package_worker_refs,
    alignment_d3d11_take_pending_request,
)
from cdmw.ui.archive_browser.static_replacement_dialog_callback_factories import (
    create_alignment_d3d11_package_lifecycle_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_texture_callbacks import (
    create_alignment_original_texture_material_callbacks,
)
from cdmw.ui.archive_browser.workers import ArchivePreviewWorkerMixin
from cdmw.ui.shell import startup_path_task_controller as startup_path_module
from cdmw.ui.shell.startup_path_task_controller import StartupPathTaskControllerMixin


class _FakeThread:
    def __init__(self) -> None:
        self.wait_results = [False, True]
        self.deleted = 0

    def wait(self, _milliseconds: int) -> bool:
        return self.wait_results.pop(0)

    def deleteLater(self) -> None:
        self.deleted += 1


class _FakeWorker:
    pass


class _FakeQObject:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass


def _fake_slot(*_args: object, **_kwargs: object):
    return lambda function: function


def _timer_type():
    class _FakeTimer:
        callbacks: list[object] = []

        @classmethod
        def singleShot(cls, _milliseconds: int, callback: object) -> None:
            cls.callbacks.append(callback)

    return _FakeTimer


@pytest.mark.parametrize("lane", ("structure", "filter", "preview", "startup"))
def test_ui_worker_cleanup_retains_refs_until_native_thread_joins(monkeypatch, lane: str) -> None:
    timer = _timer_type()
    thread = _FakeThread()
    worker = _FakeWorker()

    if lane == "structure":
        class _Owner(ArchiveFilterWorkerMixin):
            pass

        owner = _Owner()
        owner.archive_structure_filter_thread = thread
        owner.archive_structure_filter_worker = worker
        monkeypatch.setattr(filter_workers_module, "QTimer", timer)
        cleanup = lambda: owner._cleanup_archive_structure_filter_refs(thread, worker)
        refs = lambda: (owner.archive_structure_filter_thread, owner.archive_structure_filter_worker)
    elif lane == "filter":
        class _Owner(ArchiveFilterWorkerMixin):
            def _cleanup_worker_refs(self, owner_thread: object) -> None:
                assert owner_thread is self.worker_thread
                self.worker_thread = None
                self.archive_filter_worker = None

        owner = _Owner()
        owner.worker_thread = thread
        owner.archive_filter_worker = worker
        monkeypatch.setattr(filter_workers_module, "QTimer", timer)
        cleanup = lambda: owner._cleanup_archive_filter_worker_refs(thread, worker)
        refs = lambda: (owner.worker_thread, owner.archive_filter_worker)
    elif lane == "preview":
        class _Owner(ArchivePreviewWorkerMixin):
            pass

        owner = _Owner()
        owner.archive_preview_thread = thread
        owner.archive_preview_worker = worker
        owner._shutting_down = True
        owner.pending_archive_preview_request = None
        owner.scheduled_archive_preview_request = None
        monkeypatch.setattr(preview_workers_module, "QTimer", timer)
        cleanup = lambda: owner._cleanup_archive_preview_refs(thread, worker)
        refs = lambda: (owner.archive_preview_thread, owner.archive_preview_worker)
    else:
        class _Owner(StartupPathTaskControllerMixin):
            def isVisible(self) -> bool:
                return False

        owner = _Owner()
        owner._path_task_thread = thread
        owner._path_task_worker = worker
        owner._pending_path_task = None
        monkeypatch.setattr(startup_path_module, "QTimer", timer)
        cleanup = lambda: owner._handle_path_task_finished(thread)
        refs = lambda: (owner._path_task_thread, owner._path_task_worker)

    cleanup()

    assert refs() == (thread, worker)
    assert thread.deleted == 0
    assert len(timer.callbacks) == 1

    timer.callbacks.pop()()

    assert refs() == (None, None)
    assert thread.deleted == 1


@pytest.mark.parametrize("lane", ("package", "original_texture"))
def test_modify_original_worker_cleanup_retains_refs_until_native_thread_joins(lane: str) -> None:
    timer = _timer_type()
    thread = _FakeThread()
    worker = _FakeWorker()

    if lane == "package":
        state = {"thread": thread, "worker": worker}
        callbacks = create_alignment_d3d11_package_lifecycle_callbacks(
            {
                "ModelPreviewData": type("FakeModelPreviewData", (), {}),
                "QObject": _FakeQObject,
                "QThread": _FakeThread,
                "QTimer": timer,
                "Slot": _fake_slot,
                "alignment_d3d11_state": state,
                "dialog": object(),
                "preview_mode_combo": SimpleNamespace(currentData=lambda: "side_by_side"),
                "_alignment_d3d11_clear_package_worker_refs_helper": alignment_d3d11_clear_package_worker_refs,
                "_alignment_d3d11_take_pending_request_helper": alignment_d3d11_take_pending_request,
                "_alignment_dialog_widgets_live": lambda: False,
            }
        )
        cleanup = lambda: callbacks._cleanup_alignment_d3d11_package_worker_refs(thread, worker)
        refs = lambda: (state["thread"], state["worker"])
    else:
        state = {"original_texture_thread": thread, "original_texture_worker": worker}
        callbacks = create_alignment_original_texture_material_callbacks(
            {
                "AlignmentOriginalTexturePreviewWorker": _FakeWorker,
                "QThread": _FakeThread,
                "QTimer": timer,
                "alignment_d3d11_state": state,
                "dialog": SimpleNamespace(destroyed=SimpleNamespace(connect=lambda _callback: None)),
                "_alignment_d3d11_clear_original_texture_worker_refs_helper": alignment_d3d11_clear_original_texture_worker_refs,
            }
        )
        cleanup = lambda: callbacks._cleanup_original_reference_texture_worker_refs(thread, worker)
        refs = lambda: (state["original_texture_thread"], state["original_texture_worker"])

    cleanup()

    assert refs() == (thread, worker)
    assert thread.deleted == 0
    assert len(timer.callbacks) == 1

    timer.callbacks.pop()()

    assert refs() == (None, None)
    assert thread.deleted == 1
