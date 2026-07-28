from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.preview_core_prewarm import (
    ARCHIVE_PREVIEW_CORE_PREWARM_SCAN_ROWS,
    ArchivePreviewCorePrewarmMixin,
)
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(path, Path("0.pamt"), Path("0.paz"), 0, 20, 40, 0, 0)


class _Harness(ArchivePreviewCorePrewarmMixin):
    def __init__(self, entries: tuple[ArchiveEntry, ...], *, backend: str = ARCHIVE_MODEL_RENDERER_D3D11) -> None:
        self._shutting_down = False
        self._backend = backend
        self.archive_filtered_entries = entries
        self.archive_tree = None
        self.archive_remote_bridge = None
        self.archive_preview_request_id = 0
        self.archive_preview_thread = None
        self.archive_preview_core_prewarm_done = False
        self.archive_preview_core_prewarm_task = None
        self.archive_preview_core_prewarm_stop_event = None
        self.archive_package_root_edit = SimpleNamespace(text=lambda: "C:/game")
        self.started: list[object] = []
        self.events: list[tuple[str, dict]] = []
        self.logs: list[str] = []

    def _startup_benchmark_enabled(self) -> bool:
        return False

    def _archive_model_renderer_backend(self) -> str:
        return self._backend

    def _native_preview_core_cache_root(self) -> Path:
        return Path("C:/cache/preview/native")

    def _current_model_preview_render_settings(self) -> object:
        return SimpleNamespace(use_textures_by_default=False)

    def _record_runtime_event(self, event: str, **fields: object) -> None:
        self.events.append((event, dict(fields)))

    def append_archive_log(self, message: str, **_kwargs: object) -> None:
        self.logs.append(message)


class _RecordingHarness(_Harness):
    """Captures the task instead of dispatching it to the global thread pool."""

    def _start_archive_preview_core_prewarm(self) -> bool:
        import cdmw.ui.archive_browser.preview_core_prewarm as module

        pool = module.QThreadPool
        module.QThreadPool = SimpleNamespace(
            globalInstance=lambda: SimpleNamespace(start=self.started.append)
        )
        try:
            return super()._start_archive_preview_core_prewarm()
        finally:
            module.QThreadPool = pool


def test_prewarm_picks_the_first_model_row_and_runs_once() -> None:
    harness = _RecordingHarness((_entry("readme.txt"), _entry("character/sword.pac")))

    assert harness._start_archive_preview_core_prewarm() is True
    assert len(harness.started) == 1
    assert harness.started[0].entry.path == "character/sword.pac"
    assert harness.started[0].package_root == Path("C:/game")
    assert ("archive_preview_core_prewarm_started", {"path": "character/sword.pac"}) in harness.events

    # One shot per session: a second call must not queue more preview-core work.
    assert harness._start_archive_preview_core_prewarm() is False
    assert len(harness.started) == 1


def test_prewarm_skips_rows_beyond_the_first_screenful() -> None:
    filler = tuple(_entry(f"docs/note_{index}.txt") for index in range(ARCHIVE_PREVIEW_CORE_PREWARM_SCAN_ROWS))
    harness = _RecordingHarness((*filler, _entry("character/sword.pac")))

    assert harness._start_archive_preview_core_prewarm() is False
    assert harness.started == []


def test_prewarm_stands_down_once_the_session_has_previewed() -> None:
    harness = _RecordingHarness((_entry("character/sword.pac"),))
    harness.archive_preview_request_id = 1

    assert harness._start_archive_preview_core_prewarm() is False
    assert harness.started == []


def test_prewarm_only_runs_for_the_native_d3d11_backend() -> None:
    harness = _RecordingHarness((_entry("character/sword.pac"),), backend="something_else")

    assert harness._start_archive_preview_core_prewarm() is False
    assert harness.started == []


def test_cancelling_the_prewarm_releases_the_preview_core_service() -> None:
    harness = _RecordingHarness((_entry("character/sword.pac"),))
    assert harness._start_archive_preview_core_prewarm() is True
    stop_event = harness.archive_preview_core_prewarm_stop_event
    assert isinstance(stop_event, threading.Event)
    assert not stop_event.is_set()

    harness._cancel_archive_preview_core_prewarm()

    assert stop_event.is_set()
    assert harness.started[0].stop_event.is_set()


def test_prewarm_reads_rows_from_the_remote_model_when_v2_displays() -> None:
    rows = (_entry("folder"), _entry("character/sword.pac"))

    class _Model:
        def rowCount(self) -> int:
            return len(rows)

        def index(self, row: int, _column: int) -> int:
            return row

    class _Bridge:
        displays_v2 = True

        @staticmethod
        def compatibility_entry_for_index(row: int) -> ArchiveEntry | None:
            entry = rows[row]
            return None if entry.path == "folder" else entry

    harness = _RecordingHarness(())
    harness.archive_remote_bridge = _Bridge()
    harness.archive_tree = SimpleNamespace(model=_Model)

    assert harness._start_archive_preview_core_prewarm() is True
    assert harness.started[0].entry.path == "character/sword.pac"
