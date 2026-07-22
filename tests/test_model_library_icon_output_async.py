from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from cdmw.models import RunCancelled
from cdmw.services.settings_service import create_settings
from cdmw.ui.model_library import icon_output as icon_output_module
from cdmw.ui.model_library.tab import ModelLibraryTab
from cdmw.workers import model_library_workers as worker_module
from cdmw.workers.model_library_workers import (
    ModelLibraryIconOutputRequest,
    write_model_library_preview_icon,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    app = _app()
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def _image(width: int = 8, height: int = 4) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor(25, 80, 140, 255))
    return image


def _tab_with_selection(root: Path) -> tuple[ModelLibraryTab, dict[str, object], QTreeWidgetItem]:
    tab = ModelLibraryTab(
        settings=create_settings(settings_file_path=root / "settings.ini"),
        base_dir=root,
    )
    tab.catalogue_dir_edit.setText(str(root / "catalogue"))
    payload: dict[str, object] = {
        "kind": "local",
        "name": "Async Hero",
        "path": str(root / "hero.obj"),
    }
    item = QTreeWidgetItem(["", "Async Hero"])
    item.setData(0, Qt.ItemDataRole.UserRole, payload)
    tab.results_tree.addTopLevelItem(item)
    tab.results_tree.setCurrentItem(item)
    tab._inline_preview_loaded_payload = dict(payload)
    tab._inline_preview_loaded_import_path = root / "hero.obj"
    return tab, payload, item


def test_icon_output_is_square_atomic_and_collision_safe(tmp_path: Path) -> None:
    output_dir = tmp_path / "icons"
    output_dir.mkdir()
    prior = output_dir / "hero.png"
    prior.write_bytes(b"prior-output")
    request = ModelLibraryIconOutputRequest(
        request_id=7,
        image=_image(),
        output_dir=output_dir,
        output_stem="hero",
        square_crop=True,
        size=4,
    )

    result = write_model_library_preview_icon(request)

    assert prior.read_bytes() == b"prior-output"
    assert result.output_path == output_dir / "hero_2.png"
    written = QImage(str(result.output_path))
    assert (written.width(), written.height()) == (4, 4)
    assert not tuple(output_dir.glob(".*.cdmw-tmp.png"))


def test_cancel_after_encode_preserves_prior_output_and_removes_staging(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "icons"
    output_dir.mkdir()
    prior = output_dir / "hero.png"
    prior.write_bytes(b"prior-output")
    request = ModelLibraryIconOutputRequest(
        request_id=8,
        image=_image(),
        output_dir=output_dir,
        output_stem="hero",
        square_crop=True,
        size=4,
    )
    stop_event = threading.Event()
    real_fsync = os.fsync

    def cancel_after_sync(file_descriptor: int) -> None:
        real_fsync(file_descriptor)
        stop_event.set()

    monkeypatch.setattr(worker_module.os, "fsync", cancel_after_sync)

    with pytest.raises(RunCancelled):
        write_model_library_preview_icon(request, stop_event=stop_event)

    assert prior.read_bytes() == b"prior-output"
    assert not (output_dir / "hero_2.png").exists()
    assert not tuple(output_dir.glob(".*.cdmw-tmp.png"))


def test_icon_encode_dispatch_returns_before_delayed_worker_io(tmp_path: Path, monkeypatch) -> None:
    _app()
    tab, payload, _item = _tab_with_selection(tmp_path)
    started = threading.Event()
    release = threading.Event()
    emitted: list[tuple[str, dict[str, object]]] = []
    real_write = write_model_library_preview_icon

    def delayed_write(request, *, stop_event=None):
        started.set()
        assert release.wait(2.0)
        return real_write(request, stop_event=stop_event)

    monkeypatch.setattr(icon_output_module, "write_model_library_preview_icon", delayed_write)
    tab.item_icon_source_generated.connect(lambda path, value: emitted.append((path, dict(value))))
    try:
        started_at = time.perf_counter()
        tab._queue_inline_preview_icon_output(
            _image(),
            payload=dict(payload),
            loaded_path=tmp_path / "hero.obj",
            native_capture=False,
        )
        elapsed = time.perf_counter() - started_at

        assert elapsed < 0.05
        _wait_until(started.is_set)
        release.set()
        _wait_until(lambda: bool(emitted) and tab._task_thread is None)
        assert Path(emitted[0][0]).is_file()
        assert emitted[0][1]["name"] == "Async Hero"
    finally:
        release.set()
        tab.request_shutdown()
        _wait_until(lambda: tab._task_thread is None)
        tab.deleteLater()
        _app().processEvents()


def test_selection_change_cancels_icon_output_and_rejects_stale_delivery(tmp_path: Path, monkeypatch) -> None:
    _app()
    tab, payload, _item = _tab_with_selection(tmp_path)
    started = threading.Event()
    cancelled = threading.Event()
    emitted: list[str] = []

    def blocked_write(_request, *, stop_event=None):
        started.set()
        while stop_event is not None and not stop_event.is_set():
            time.sleep(0.005)
        cancelled.set()
        raise RunCancelled("cancelled")

    monkeypatch.setattr(icon_output_module, "write_model_library_preview_icon", blocked_write)
    tab.item_icon_source_generated.connect(lambda path, _value: emitted.append(path))
    try:
        tab._queue_inline_preview_icon_output(
            _image(),
            payload=dict(payload),
            loaded_path=tmp_path / "hero.obj",
            native_capture=False,
        )
        _wait_until(started.is_set)
        other_payload = {"kind": "local", "name": "Other", "path": str(tmp_path / "other.obj")}
        other = QTreeWidgetItem(["", "Other"])
        other.setData(0, Qt.ItemDataRole.UserRole, other_payload)
        tab.results_tree.addTopLevelItem(other)
        tab.results_tree.setCurrentItem(other)

        _wait_until(lambda: cancelled.is_set() and tab._task_thread is None)
        assert emitted == []
        assert not tuple((tmp_path / "catalogue").rglob("*.cdmw-tmp.png"))
    finally:
        tab.request_shutdown()
        _wait_until(lambda: tab._task_thread is None)
        tab.deleteLater()
        _app().processEvents()


def test_preview_and_dotnet_host_keep_encoding_out_of_capture_handler() -> None:
    preview_source = Path("cdmw/ui/model_library/preview.py").read_text(encoding="utf-8")
    output_source = Path("cdmw/ui/model_library/icon_output.py").read_text(encoding="utf-8")
    capture_start = preview_source.index("    def _capture_inline_preview_icon")
    capture_end = preview_source.index("    def closeEvent", capture_start)
    capture_body = preview_source[capture_start:capture_end]
    worker_source = Path("cdmw/workers/model_library_workers.py").read_text(encoding="utf-8")
    host_source = Path("cdmw/ui/preview/dotnet_host.py").read_text(encoding="utf-8")

    assert ".save(" not in capture_body
    assert ".scaled(" not in capture_body
    assert "capture_replacement_icon(capture_path)" in capture_body
    assert "write_model_library_preview_icon(request, stop_event=stop_event)" in output_source
    assert "os.link(staging, candidate)" in worker_source
    assert "def capture_replacement_icon" in host_source
