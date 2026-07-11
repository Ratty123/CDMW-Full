from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.core.text_search import (
    TextSearchResult,
    TextSearchRunStats,
    export_text_search_results,
    search_archive_text_entries,
)
from cdmw.models import RunCancelled
from cdmw.ui.text_search.export_actions import TextSearchExportMixin
from cdmw.ui.text_search.tab import TextSearchTab


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(predicate, *, timeout: float = 4.0) -> None:
    app = _app()
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


def _tab(root: Path) -> TextSearchTab:
    return TextSearchTab(
        settings=QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat),
        base_dir=root,
        theme_key="graphite",
    )


def test_text_export_dispatch_is_nonblocking_and_worker_owned() -> None:
    _app()
    started = threading.Event()
    release = threading.Event()

    def slow_export(*_args, stop_event=None, **_kwargs):
        started.set()
        while not release.wait(0.005):
            if stop_event is not None and stop_event.is_set():
                raise RunCancelled("Text export stopped by user.")
        return {"total": 1, "exported": 1, "renamed": 0, "failed": 0}

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "source.txt"
        source.write_text("match", encoding="utf-8")
        result = TextSearchResult(
            source_kind="loose",
            relative_path=source.name,
            extension=".txt",
            match_count=1,
            snippet="match",
            loose_root=root,
            loose_path=source,
        )
        tab = _tab(root)
        try:
            with (
                patch.object(TextSearchExportMixin, "_confirm_export", return_value=True),
                patch("cdmw.ui.text_search.workers.export_text_search_results", side_effect=slow_export),
            ):
                before = time.perf_counter()
                tab._export_results((result,), label="selected")
                assert time.perf_counter() - before < 0.05
                assert started.wait(1.0)
                assert ("export_thread", tab.export_thread, tab.export_worker) in tab.iter_shutdown_workers()
                release.set()
                _wait_until(lambda: tab.export_thread is None)
            assert "Exported 1 file" in tab.search_progress_label.text()
        finally:
            release.set()
            tab.request_shutdown()
            _wait_until(lambda: tab.export_thread is None)


def test_text_search_dispatch_is_nonblocking_under_slow_file_io() -> None:
    _app()
    started = threading.Event()
    release = threading.Event()

    def slow_search(root: Path, _query: str, **_kwargs):
        started.set()
        assert release.wait(2.0)
        result = TextSearchResult(
            source_kind="loose",
            relative_path="match.txt",
            extension=".txt",
            match_count=1,
            snippet="match",
            loose_root=root,
            loose_path=root / "match.txt",
        )
        return [result], TextSearchRunStats(source_kind="loose", candidate_count=1, searched_count=1)

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "match.txt").write_text("match", encoding="utf-8")
        tab = _tab(root)
        tab.source_combo.setCurrentIndex(tab.source_combo.findData("loose"))
        tab.loose_root_edit.setText(str(root))
        tab.query_edit.setText("match")
        try:
            with patch("cdmw.ui.text_search.workers.search_loose_text_files", side_effect=slow_search):
                before = time.perf_counter()
                tab.start_search()
                assert time.perf_counter() - before < 0.05
                assert started.wait(1.0)
                release.set()
                _wait_until(lambda: tab.search_thread is None)
            assert [result.relative_path for result in tab.search_results] == ["match.txt"]
        finally:
            release.set()
            tab.request_shutdown()
            _wait_until(lambda: tab.preview_thread is None)


def test_text_export_stale_result_is_ignored() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        tab = _tab(Path(temp_dir))
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error: messages.append((message, error)))
        try:
            tab.export_request_id = 4
            tab._handle_export_complete(
                3,
                {"exported": 99, "renamed": 0, "failed": 0},
                "stale",
            )
            assert messages == []
            assert "99" not in tab.search_progress_label.text()
        finally:
            tab.request_shutdown()


def test_text_search_stale_result_is_ignored() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        result = TextSearchResult(
            source_kind="loose",
            relative_path="current.txt",
            extension=".txt",
            match_count=1,
            snippet="current",
            loose_root=root,
            loose_path=root / "current.txt",
        )
        tab = _tab(root)
        try:
            tab.search_request_id = 4
            tab.search_results = [result]
            tab._handle_search_complete(3, {"results": [], "source_kind": "loose"})
            assert tab.search_results == [result]
        finally:
            tab.request_shutdown()


def test_text_export_shutdown_cancels_without_blocking() -> None:
    _app()
    started = threading.Event()

    def cancellable_export(*_args, stop_event=None, **_kwargs):
        started.set()
        while stop_event is not None and not stop_event.wait(0.005):
            pass
        raise RunCancelled("Text export stopped by user.")

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "source.txt"
        source.write_text("match", encoding="utf-8")
        result = TextSearchResult(
            source_kind="loose",
            relative_path=source.name,
            extension=".txt",
            match_count=1,
            snippet="match",
            loose_root=root,
            loose_path=source,
        )
        tab = _tab(root)
        with (
            patch.object(TextSearchExportMixin, "_confirm_export", return_value=True),
            patch("cdmw.ui.text_search.workers.export_text_search_results", side_effect=cancellable_export),
        ):
            tab._export_results((result,), label="selected")
            assert started.wait(1.0)
            before = time.perf_counter()
            tab.request_shutdown()
            assert time.perf_counter() - before < 0.05
            _wait_until(lambda: tab.export_thread is None)
        assert tab.export_worker is None


def test_text_export_cancellation_preserves_target_and_removes_staging_file() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "source.txt"
        source.write_text("new", encoding="utf-8")
        output_root = root / "out"
        output_root.mkdir()
        target = output_root / source.name
        target.write_text("old", encoding="utf-8")
        stop_event = threading.Event()
        result = TextSearchResult(
            source_kind="loose",
            relative_path=source.name,
            extension=".txt",
            match_count=1,
            snippet="new",
            loose_root=root,
            loose_path=source,
        )

        def interrupted_copy(_source: Path, staged: Path, _stop_event: threading.Event) -> None:
            Path(staged).write_text("partial", encoding="utf-8")
            stop_event.set()

        with patch("cdmw.core.text_search._copy_loose_text_result", side_effect=interrupted_copy):
            with pytest.raises(RunCancelled, match="stopped by user"):
                export_text_search_results((result,), output_root, stop_event=stop_event)

        assert target.read_text(encoding="utf-8") == "old"
        assert not tuple(output_root.glob("*.cdmw-tmp"))
        assert not tuple(output_root.glob(".*.cdmw-tmp"))


def test_text_export_atomically_publishes_loose_file() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "source.txt"
        source.write_text("complete", encoding="utf-8")
        output_root = root / "out"
        result = TextSearchResult(
            source_kind="loose",
            relative_path="nested/source.txt",
            extension=".txt",
            match_count=1,
            snippet="complete",
            loose_root=root,
            loose_path=source,
        )

        stats = export_text_search_results((result,), output_root)

        assert stats == {"total": 1, "exported": 1, "renamed": 0, "failed": 0}
        assert (output_root / "nested" / "source.txt").read_text(encoding="utf-8") == "complete"
        assert not tuple(output_root.rglob("*.cdmw-tmp"))


def test_archive_search_progress_is_bounded_for_large_nonmatching_index() -> None:
    entries = [
        SimpleNamespace(path=f"binary/{index}.bin", extension=".bin", encrypted=False)
        for index in range(20_000)
    ]
    progress: list[int] = []

    results, stats = search_archive_text_entries(
        entries,  # type: ignore[arg-type]
        "needle",
        extension_filters=(".xml",),
        on_progress=lambda current, _total, _detail: progress.append(current),
    )

    assert results == []
    assert stats.candidate_count == 0
    assert len(progress) <= 205
