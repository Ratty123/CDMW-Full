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
    TextSearchPreview,
    TextSearchResult,
    TextSearchRunStats,
    _path_matches_filter,
    export_text_search_results,
    search_archive_text_entries,
    search_loose_text_files,
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


def _loose_result(root: Path, index: int) -> TextSearchResult:
    return TextSearchResult(
        source_kind="loose",
        relative_path=f"f{index}.txt",
        extension=".txt",
        match_count=1,
        snippet="needle",
        loose_root=root,
        loose_path=root / f"f{index}.txt",
    )


def test_reference_review_stops_pending_result_population() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        tab = _tab(root)
        try:
            results = [_loose_result(root, index) for index in range(tab.RESULT_POPULATION_BATCH_SIZE * 3)]
            stats = TextSearchRunStats(source_kind="loose", candidate_count=len(results), searched_count=len(results))
            tab._handle_search_complete(tab.search_request_id, {"results": results, "stats": stats})
            tab._flush_result_population_batch()
            assert tab._results_population_timer.isActive()

            entry = SimpleNamespace(path="ui/reference.xml", extension=".xml", package_label="0009")
            with patch.object(tab, "_schedule_preview"):
                assert tab.review_archive_entry(entry, highlight_query="needle")  # type: ignore[arg-type]
            assert not tab._results_population_timer.isActive()
            tab._flush_result_population_batch()
            assert tab.results_tree.topLevelItemCount() == 1
            assert tab.results_tree.topLevelItem(0).text(3) == "ui/reference.xml"
        finally:
            tab.request_shutdown()


@pytest.mark.parametrize("ending", ["cancelled", "error"])
def test_unfinished_search_clears_in_progress_labels(ending: str) -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        tab = _tab(root)
        try:
            tab.source_combo.setCurrentIndex(tab.source_combo.findData("loose"))
            tab.loose_root_edit.setText(str(root))
            tab.query_edit.setText("needle")
            with patch("cdmw.ui.text_search.controller.TextSearchWorker"), patch(
                "cdmw.ui.text_search.controller.QThread"
            ):
                tab.start_search()
            assert tab.results_summary_label.text() == "Search in progress..."
            assert tab.preview_title_label.text() == "Searching..."
            tab.search_thread = None
            tab.search_worker = None

            handler = tab._handle_search_cancelled if ending == "cancelled" else tab._handle_search_error
            handler(tab.search_request_id, "Search ended early.")

            assert tab.results_summary_label.text() == "Search ended early."
            assert tab.preview_title_label.text() == "Select a matching file"
            assert tab.preview_find_status_label.text() == "No preview loaded."
        finally:
            tab.request_shutdown()


def test_large_preview_keeps_search_highlights_and_centres_first_match() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        tab = _tab(Path(temp_dir))
        try:
            filler = "filler line\n" * 30_000
            text = f"{filler}needle\n"
            start = len(filler)
            tab._handle_preview_ready(
                tab.preview_request_id,
                TextSearchPreview("big.txt", "", "", text, [(start, start + 6)]),
            )

            assert tab.preview_search_spans == [(start, start + 6)]
            assert tab.preview_text_edit.textCursor().selectedText() == "needle"
            assert tab.preview_find_status_label.text() == "Search highlights: 1"
        finally:
            tab.request_shutdown()


def test_truncated_preview_drops_only_highlights_past_the_display_limit() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        tab = _tab(Path(temp_dir))
        try:
            limit = tab.PREVIEW_DISPLAY_CHAR_LIMIT
            text = "needle" + "x" * limit + "needle"
            tab._handle_preview_ready(
                tab.preview_request_id,
                TextSearchPreview("big.txt", "", "", text, [(0, 6), (limit + 6, limit + 12)]),
            )

            assert tab.preview_search_spans == [(0, 6)]
        finally:
            tab.request_shutdown()


# The standalone archive worker applies the same rules; see its text_search_matching_rules test.
@pytest.mark.parametrize(
    ("path", "path_filter", "expected"),
    [
        ("ui/Sub/Panel.XML", "sub/", True),
        ("ui/panel.xml", "*.json", False),
        ("ui/sub/panel.xml", "*.xml", True),
        ("ui/a.xml/panel.txt", "*.xml", False),
        ("a/b/c.xml", "a*.xml", False),
        ("character/object/x.xml", "object/*", True),
        ("ui/sub/panel.xml", "ui/*.xml", True),
        ("game/ui/panel.xml", "/ui/*", False),
        (r"ui\panel_01.xml", "panel_??.xml", True),
    ],
)
def test_path_filter_wildcards_match_the_archive_worker(path: str, path_filter: str, expected: bool) -> None:
    assert _path_matches_filter(path, path_filter) is expected


def test_loose_search_applies_wildcard_path_filter(tmp_path: Path) -> None:
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "panel.xml").write_text("needle", encoding="utf-8")
    (tmp_path / "ui" / "panel.txt").write_text("needle", encoding="utf-8")

    results, _stats = search_loose_text_files(
        tmp_path, "needle", extension_filters=(".xml", ".txt"), path_filter="*.xml"
    )

    assert [result.relative_path for result in results] == ["ui/panel.xml"]
