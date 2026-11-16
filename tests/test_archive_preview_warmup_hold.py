"""Browse's preview build holds the background warm-ups until it is done.

Finder thumbnails and Create New Item's table preload run Python in CDMW's own
process. Left running during a Browse preview, they and the preview worker
take turns at Python's lock with the window thread, and the window paused for
up to two seconds at a time in the review after a model was selected.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cdmw.ui.archive_browser import workers as workers_module
from cdmw.ui.archive_browser.workers import ArchivePreviewWorkerMixin

ARCHIVE_PREVIEW_WARMUP_HOLD = getattr(workers_module, "ARCHIVE_PREVIEW_WARMUP_HOLD", "no hold")


class _Timer:
    def __init__(self) -> None:
        self.calls: list[tuple[int, object]] = []

    def singleShot(self, milliseconds, *args) -> None:  # noqa: N802 - Qt name
        self.calls.append((int(milliseconds), args[-1]))


class _Thread:
    def __init__(self, *_args: object) -> None:
        self.started = MagicMock()
        self.finished = MagicMock()
        self.running = False

    def start(self) -> None:
        self.running = True

    def quit(self) -> None:
        pass

    def wait(self, _milliseconds: int) -> bool:
        return True

    def deleteLater(self) -> None:
        pass


class _Owner(ArchivePreviewWorkerMixin):
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.shell = SimpleNamespace(_shutting_down=False, _record_runtime_event=lambda *a, **k: None)
        self.archive_package_root_edit = SimpleNamespace(text=lambda: "")
        self.archive_preview_thread = None
        self.archive_preview_worker = None
        self.pending_archive_preview_request = None
        self.scheduled_archive_preview_request = None
        self._native_preview_package_cache_mode = lambda: "off"
        self._native_preview_package_cache_budget = lambda: (0, 0)

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        return MagicMock(name=name)

    def hold_background_warmups(self, owner: object) -> None:
        self.events.append(("hold", owner))

    def release_background_warmups(self, owner: object) -> None:
        self.events.append(("release", owner))

    def sender(self):
        return self.archive_preview_thread


@pytest.fixture
def owner(monkeypatch):
    timer = _Timer()
    monkeypatch.setattr(workers_module, "QTimer", timer)
    monkeypatch.setattr(workers_module, "QThread", _Thread)
    monkeypatch.setattr(workers_module, "ArchivePreviewWorker", MagicMock(name="ArchivePreviewWorker"))
    result = _Owner()
    result.timer = timer
    return result


def _start(owner: _Owner, request_id: int = 1) -> None:
    owner._start_archive_preview_worker(request_id, None, ())


def test_a_preview_build_holds_the_warmups_until_its_worker_ends(owner):
    _start(owner)

    assert owner.events == [("hold", ARCHIVE_PREVIEW_WARMUP_HOLD)]
    owner._cleanup_archive_preview_refs(owner.archive_preview_thread, owner.archive_preview_worker)

    assert owner.events == [("hold", ARCHIVE_PREVIEW_WARMUP_HOLD), ("release", ARCHIVE_PREVIEW_WARMUP_HOLD)]
    assert owner.archive_preview_thread is None


def test_a_queued_preview_keeps_the_hold_for_its_own_worker(owner):
    _start(owner)
    owner.pending_archive_preview_request = (2, None, False)
    owner._flush_scheduled_archive_preview_request = lambda: _start(owner, 2)

    owner._cleanup_archive_preview_refs(owner.archive_preview_thread, owner.archive_preview_worker)

    # The next worker started from the queue: no release in between.
    assert [kind for kind, _ in owner.events] == ["hold", "hold"]
    owner._cleanup_archive_preview_refs(owner.archive_preview_thread, owner.archive_preview_worker)
    assert [kind for kind, _ in owner.events] == ["hold", "hold", "release"]


def test_a_preview_that_never_ends_releases_the_warmups_after_its_limit(owner):
    _start(owner)
    limits = [(ms, callback) for ms, callback in owner.timer.calls if ms >= 60_000]
    assert len(limits) == 1

    limits[0][1]()

    assert owner.events[-1] == ("release", ARCHIVE_PREVIEW_WARMUP_HOLD)


def test_an_old_limit_does_not_release_a_newer_preview(owner):
    _start(owner)
    old_limit = owner.timer.calls[-1][1]
    owner._cleanup_archive_preview_refs(owner.archive_preview_thread, owner.archive_preview_worker)
    _start(owner, 2)
    events = list(owner.events)

    old_limit()

    assert owner.events == events
