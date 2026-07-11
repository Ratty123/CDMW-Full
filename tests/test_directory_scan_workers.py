from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QApplication

from cdmw.models import RunCancelled
from cdmw.ui.archive_browser.loose_donor_scan import LooseDonorScanController, LooseDonorScanResult
from cdmw.workers.directory_scan_workers import DirectoryScanRequest, scan_directory_files


def test_directory_scan_filters_compound_suffixes_and_skips_symlink_directories(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    wanted = nested / "body.sockets.xml"
    wanted.write_text("x", encoding="utf-8")
    (nested / "ignore.txt").write_text("x", encoding="utf-8")

    result = scan_directory_files(
        DirectoryScanRequest(1, tmp_path, suffixes=(".pac", ".sockets.xml"))
    )

    assert result.paths == (wanted,)
    assert not result.truncated


def test_directory_scan_has_result_and_entry_limits(tmp_path: Path) -> None:
    for index in range(8):
        (tmp_path / f"mesh-{index}.pac").write_bytes(b"x")

    result = scan_directory_files(
        DirectoryScanRequest(2, tmp_path, suffixes=(".pac",), max_results=3)
    )

    assert len(result.paths) == 3
    assert result.truncated


def test_directory_scan_honours_pre_cancel(tmp_path: Path) -> None:
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(RunCancelled):
        scan_directory_files(DirectoryScanRequest(3, tmp_path), stop_event=cancelled)


def test_loose_donor_folder_scan_is_worker_owned_and_incrementally_applied() -> None:
    dialog_source = Path("cdmw/ui/archive_browser/attachment_donor_picker_dialog.py").read_text(
        encoding="utf-8"
    )
    controller_source = Path("cdmw/ui/archive_browser/loose_donor_scan.py").read_text(encoding="utf-8")

    assert "LooseDonorScanController(" in dialog_source
    assert "DirectoryScanWorker(request)" in controller_source
    assert "self._mapping_timer.start(0)" in controller_source
    assert 'list(files_root.rglob("*"))' not in dialog_source


def test_loose_donor_controller_delivers_mapping_on_owner_thread(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    for index in range(20):
        (tmp_path / f"mesh-{index}.pac").write_bytes(b"x")
    owner = QObject()
    completed: list[tuple[LooseDonorScanResult, bool]] = []
    controller = LooseDonorScanController(
        thread_parent=owner,
        map_file=lambda path: (SimpleNamespace(key=path.name),),
        entry_key=lambda entry: entry.key,
        parent=owner,
    )
    controller.completed.connect(
        lambda payload: completed.append((payload, QThread.currentThread() is app.thread()))
    )

    controller.start(
        folder=tmp_path,
        files_root=tmp_path,
        suffixes=(".pac",),
        existing_keys=(),
    )
    deadline = time.perf_counter() + 3.0
    while not completed and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.002)

    controller.close()
    cleanup_deadline = time.perf_counter() + 1.0
    while controller.is_running() and time.perf_counter() < cleanup_deadline:
        app.processEvents()
        time.sleep(0.002)
    assert completed
    result, on_owner_thread = completed[0]
    assert len(result.candidates) == 20
    assert on_owner_thread
    assert not controller.is_running()
