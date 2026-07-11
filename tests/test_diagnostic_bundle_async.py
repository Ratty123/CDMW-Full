from __future__ import annotations

import json
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.models import RunCancelled
from cdmw.services.diagnostic_bundle_service import (
    ChainnerDiagnosticSnapshot,
    DiagnosticBundleRequest,
    DiagnosticBundleResult,
    build_diagnostic_bundle,
)
from cdmw.ui.shell.profile_controller import ProfileControllerMixin


def _request(root: Path, target: Path) -> DiagnosticBundleRequest:
    settings = root / "settings.ini"
    settings.write_text("[ui]\ntheme=graphite\n", encoding="utf-8")
    readme = root / "README.md"
    readme.write_text("docs", encoding="utf-8")
    cache_root = root / "cache"
    cache_root.mkdir(exist_ok=True)
    (cache_root / "index.json").write_text("{}", encoding="utf-8")
    crash_root = root / "crashes"
    crash_root.mkdir(exist_ok=True)
    return DiagnosticBundleRequest(
        target=target,
        app_title="CDMW Test",
        app_version="1.0",
        theme="graphite",
        settings_file_path=settings,
        archive_cache_root=cache_root,
        crash_reports_dir=crash_root,
        profile_json=json.dumps({"profile_format": 3}),
        chainner=ChainnerDiagnosticSnapshot(),
        live_log="live",
        archive_scan_log="archive",
        crash_context_json=json.dumps({"current_tab": "Archive"}),
        text_search_entries=(("text_search_log.txt", "search"),),
        documentation_files=(readme,),
    )


def test_diagnostic_bundle_service_builds_expected_atomic_zip() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        target = root / "out" / "diagnostics.zip"
        request = _request(root, target)

        result = build_diagnostic_bundle(request)

        assert result == DiagnosticBundleResult(target=target, chainner_warning_count=None)
        with zipfile.ZipFile(target) as archive:
            names = set(archive.namelist())
            assert {
                "diagnostics.json",
                "issue_summary.txt",
                "diagnostics_index.json",
                "chainner_analysis.txt",
                "live_log.txt",
                "archive_scan_log.txt",
                "settings.ini",
                "README.md",
                "text_search_log.txt",
            } <= names
            diagnostics = json.loads(archive.read("diagnostics.json"))
            assert diagnostics["profile"] == {"profile_format": 3}
            assert diagnostics["archive_cache_files"][0]["name"] == "index.json"
            assert "Current tab: Archive" in archive.read("issue_summary.txt").decode("utf-8")
        assert not tuple(target.parent.glob("*.cdmw-tmp"))
        assert not tuple(target.parent.glob(".*.cdmw-tmp"))


def test_diagnostic_bundle_cancellation_preserves_old_target_and_cleans_temp() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        target = root / "diagnostics.zip"
        target.write_bytes(b"old")
        request = _request(root, target)
        stop_event = threading.Event()
        original_writestr = zipfile.ZipFile.writestr
        write_count = 0

        def interrupt_after_first_write(archive, *args, **kwargs):
            nonlocal write_count
            result = original_writestr(archive, *args, **kwargs)
            write_count += 1
            if write_count == 1:
                stop_event.set()
            return result

        with patch(
            "cdmw.services.diagnostic_bundle_service.zipfile.ZipFile.writestr",
            new=interrupt_after_first_write,
        ):
            with pytest.raises(RunCancelled, match="stopped by user"):
                build_diagnostic_bundle(request, stop_event=stop_event)

        assert target.read_bytes() == b"old"
        assert not tuple(root.glob("*.cdmw-tmp"))
        assert not tuple(root.glob(".*.cdmw-tmp"))


def test_diagnostic_export_handler_only_snapshots_and_dispatches() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        request = _request(root, root / "diagnostics.zip")

        class Owner:
            export_diagnostic_bundle = ProfileControllerMixin.export_diagnostic_bundle

            def __init__(self) -> None:
                self.settings_file_path = root / "settings.ini"
                self._diagnostic_bundle_request_id = 0
                self.dispatched = None
                self.status: list[tuple[str, bool]] = []
                self.logs: list[str] = []
                self._collect_crash_context = lambda: {}

            def _diagnostic_bundle_request(self, _target: Path) -> DiagnosticBundleRequest:
                return request

            def _run_utility_task(self, **kwargs) -> None:
                self.dispatched = kwargs

            def set_status_message(self, message: str, *, error: bool = False) -> None:
                self.status.append((message, error))

            def append_log(self, message: str) -> None:
                self.logs.append(message)

        owner = Owner()
        with patch(
            "cdmw.ui.shell.profile_controller.QFileDialog.getSaveFileName",
            return_value=(str(request.target), "ZIP archive (*.zip)"),
        ):
            before = time.perf_counter()
            owner.export_diagnostic_bundle()
            elapsed = time.perf_counter() - before

        assert elapsed < 0.05
        assert owner.dispatched is not None
        assert owner.dispatched["task_accepts_cancel"] is True
        assert callable(owner.dispatched["task"])
        assert request.target.exists() is False


def test_diagnostic_request_snapshot_does_not_read_source_files() -> None:
    class Text:
        def __init__(self, value: str = "") -> None:
            self.value = value

        def text(self) -> str:
            return self.value

        def toPlainText(self) -> str:
            return self.value

    class Owner:
        _diagnostic_bundle_request = ProfileControllerMixin._diagnostic_bundle_request
        _chainner_diagnostic_snapshot = ProfileControllerMixin._chainner_diagnostic_snapshot
        _diagnostic_context_snapshot = ProfileControllerMixin._diagnostic_context_snapshot

        def __init__(self, root: Path) -> None:
            self.current_theme_key = "graphite"
            self.settings_file_path = root / "settings.ini"
            self.archive_cache_root = root / "cache"
            self.text_search_tab = None
            self.log_view = Text("live")
            self.archive_log_view = Text("archive")
            self.chainner_chain_path_edit = Text()
            self.original_dds_edit = Text()
            self.dds_staging_root_edit = Text()
            self.png_root_edit = Text()
            self.chainner_override_edit = Text()

        def _crash_reports_dir(self) -> Path:
            return self.settings_file_path.parent / "logs"

        def _collect_profile_payload(self, *, flush: bool) -> dict[str, object]:
            assert flush is False
            return {"profile_format": 3}

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        owner = Owner(root)
        with (
            patch.object(Path, "exists", side_effect=AssertionError("UI snapshot performed file I/O")),
            patch.object(Path, "read_text", side_effect=AssertionError("UI snapshot performed file I/O")),
            patch.object(Path, "glob", side_effect=AssertionError("UI snapshot performed file I/O")),
        ):
            before = time.perf_counter()
            request = owner._diagnostic_bundle_request(root / "out.zip")
            elapsed = time.perf_counter() - before

        assert elapsed < 0.05
        assert request.profile_json == '{\n  "profile_format": 3\n}'


def test_diagnostic_bundle_stale_completion_is_ignored() -> None:
    class Owner:
        _handle_diagnostic_bundle_complete = ProfileControllerMixin._handle_diagnostic_bundle_complete

        def __init__(self) -> None:
            self._diagnostic_bundle_request_id = 8
            self.status: list[str] = []
            self.logs: list[str] = []

        def set_status_message(self, message: str, *, error: bool = False) -> None:
            self.status.append(message)

        def append_log(self, message: str) -> None:
            self.logs.append(message)

    owner = Owner()
    result = DiagnosticBundleResult(Path("new.zip"), None)
    owner._handle_diagnostic_bundle_complete(7, result)
    assert owner.status == []
    assert owner.logs == []

    owner._handle_diagnostic_bundle_complete(8, result)
    assert owner.status == ["Diagnostic bundle exported to new.zip"]
