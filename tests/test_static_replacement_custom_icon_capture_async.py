from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from cdmw.models import RunCancelled
from cdmw.ui.archive_browser.static_replacement_dialog_custom_icon_callbacks import (
    create_alignment_custom_icon_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_generated_icon_output import (
    AlignmentGeneratedIconOutputController,
)
from cdmw.ui.archive_browser.static_replacement_custom_icon import (
    write_custom_item_icon_image_atomic,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(predicate, *, timeout: float = 2.0) -> None:  # type: ignore[no-untyped-def]
    app = _app()
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.002)
    app.processEvents()
    assert predicate()


class _Screen:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.grabbed_at = 0.0

    def grabWindow(self, window_id: int) -> QPixmap:
        self.grabbed_at = time.perf_counter()
        self.events.append(f"grab:{window_id}")
        pixmap = QPixmap(8, 8)
        pixmap.fill(QColor("red"))
        return pixmap


class _D3dHost:
    def __init__(self, events: list[str], screen: _Screen) -> None:
        self.events = events
        self._screen = screen

    def view_state_snapshot(self) -> str:
        return "previous"

    def restore_view_state(self, state: object) -> None:
        self.events.append(f"restore:{state}")

    def set_icon_capture_mode(self, enabled: bool) -> None:
        self.events.append(f"capture:{enabled}")

    def set_display_mode(self, mode: str) -> None:
        self.events.append(f"mode:{mode}")

    def set_highlighted_alignment_submeshes(self, **_kwargs: object) -> None:
        self.events.append("highlights:off")

    def set_hidden_source_submeshes(self, _indices: object) -> None:
        self.events.append("hidden:off")

    def set_alignment_state(self, **_kwargs: object) -> None:
        self.events.append("alignment:off")

    def screen(self) -> _Screen:
        return self._screen

    def winId(self) -> int:
        return 42


def _callbacks_for_d3d(dialog: QWidget, events: list[str], screen: _Screen):  # type: ignore[no-untyped-def]
    host = _D3dHost(events, screen)
    def capture(callback) -> bool:  # type: ignore[no-untyped-def]
        events.append("offscreen:requested")
        pixmap = QPixmap(8, 8)
        pixmap.fill(QColor("red"))
        QTimer.singleShot(0, lambda: callback(pixmap))
        return True
    setattr(dialog, "_mesh_editor_embedded_capture_icon", capture)
    return create_alignment_custom_icon_callbacks(
        {
            "Optional": Optional,
            "QApplication": QApplication,
            "QPixmap": QPixmap,
            "QTimer": QTimer,
            "dialog": dialog,
            "generate_alignment_icon_button": QPushButton(dialog),
            "alignment_d3d11_preview_host": host,
            "preview_mode_combo": SimpleNamespace(currentData=lambda: "side_by_side"),
            "_alignment_d3d11_preview_active": lambda: True,
            "_alignment_current_camera_state": lambda: "capture-view",
            "_sync_highlight_sets": lambda: events.append("sync:highlights"),
            "_sync_mesh_edit_preview_settings": lambda: events.append("sync:preview"),
            "_replay_alignment_d3d11_fast_transform": lambda: events.append("sync:transform"),
        }
    )


def test_d3d_icon_capture_uses_resident_offscreen_request_without_blocking_ui_thread() -> None:
    _app()
    dialog = QWidget()
    events: list[str] = []
    screen = _Screen(events)
    callbacks = _callbacks_for_d3d(dialog, events, screen)
    captured: list[Optional[QPixmap]] = []

    started_at = time.perf_counter()
    result = callbacks._capture_alignment_replacement_icon_pixmap(
        lambda pixmap: (events.append("callback"), captured.append(pixmap))
    )
    elapsed = time.perf_counter() - started_at

    assert result is None
    assert elapsed < 0.05
    assert not captured
    assert "grab:42" not in events
    _wait_until(lambda: bool(captured))

    assert captured[0] is not None and not captured[0].isNull()
    assert events == ["offscreen:requested", "callback"]
    dialog.deleteLater()


def test_capture_source_has_no_nested_event_pump_or_ui_sleep() -> None:
    capture_source = Path(
        "cdmw/ui/archive_browser/static_replacement_dialog_custom_icon_callbacks.py"
    ).read_text(encoding="utf-8")
    output_source = Path(
        "cdmw/ui/archive_browser/static_replacement_generated_icon_output.py"
    ).read_text(encoding="utf-8")
    source = capture_source + "\n" + output_source

    assert "QThread.msleep" not in capture_source
    assert "QApplication.processEvents" not in capture_source
    assert "timer.timeout.connect(_run)" in capture_source
    assert "screen.grabWindow" not in capture_source
    assert "_mesh_editor_embedded_capture_icon" in capture_source
    assert "set_icon_capture_mode" not in capture_source
    assert "set_display_mode(\"replacement_only\")" not in capture_source
    assert "self.capture(lambda pixmap: self._finish_capture(pixmap, generation))" in output_source
    assert "icon_image.save(" not in source
    assert "pixmap.toImage().copy()" in output_source
    assert "shell._run_utility_task_when_idle(" in output_source
    assert "task_accepts_cancel=True" in output_source
    assert "selection_dialog.open()" in output_source
    assert "selection_dialog.exec(" not in output_source


class _SignalProbe:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:  # type: ignore[no-untyped-def]
        self.callback = callback

    def emit(self) -> None:
        assert self.callback is not None
        self.callback()


class _SelectionDialogProbe:
    def __init__(self, selection: tuple[int, int, int, int]) -> None:
        self.accepted = _SignalProbe()
        self.rejected = _SignalProbe()
        self.selection = selection
        self.opened = False
        self.deleted = False

    def selected_source_rect(self) -> tuple[int, int, int, int]:
        return self.selection

    def open(self) -> None:
        self.opened = True

    def deleteLater(self) -> None:
        self.deleted = True


def test_generated_icon_capture_waits_for_region_acceptance_before_queueing_output(
) -> None:
    _app()
    pixmap = QPixmap(40, 20)
    pixmap.fill(QColor("red"))
    selection_dialog = _SelectionDialogProbe((3, 4, 20, 10))
    queued: list[tuple[object, tuple[int, int, int, int], int]] = []
    context = {
        "dialog": SimpleNamespace(isVisible=lambda: True),
        "generate_alignment_icon_button": SimpleNamespace(setEnabled=lambda _enabled: None),
        "_alignment_icon_selection_dialog_factory": lambda _image, _parent: selection_dialog,
    }
    controller = AlignmentGeneratedIconOutputController(
        context,
        capture=lambda _callback: None,
        refresh_status=lambda: None,
    )
    controller.generation = 6
    controller._queue_output = lambda image, selection, generation: queued.append(  # type: ignore[method-assign]
        (image, selection, generation)
    )

    controller._finish_capture(pixmap, 6)

    assert selection_dialog.opened
    assert queued == []
    selection_dialog.accepted.emit()
    assert len(queued) == 1
    assert queued[0][1:] == ((3, 4, 20, 10), 6)
    assert selection_dialog.deleted
    assert controller.selection_dialog is None


def test_cancelling_icon_region_selection_reenables_generate_button() -> None:
    _app()
    pixmap = QPixmap(40, 20)
    pixmap.fill(QColor("red"))
    selection_dialog = _SelectionDialogProbe((0, 0, 40, 20))
    enabled: list[bool] = []
    context = {
        "dialog": SimpleNamespace(isVisible=lambda: True),
        "generate_alignment_icon_button": SimpleNamespace(
            setEnabled=lambda value: enabled.append(bool(value))
        ),
        "_alignment_icon_selection_dialog_factory": lambda _image, _parent: selection_dialog,
    }
    controller = AlignmentGeneratedIconOutputController(
        context,
        capture=lambda _callback: None,
        refresh_status=lambda: None,
    )
    controller.generation = 2

    controller._finish_capture(pixmap, 2)
    selection_dialog.rejected.emit()

    assert enabled == [True]
    assert selection_dialog.deleted
    assert controller.selection_dialog is None


def test_cancelled_generated_icon_encode_preserves_previous_file(tmp_path: Path) -> None:
    target = tmp_path / "icon.png"
    target.write_bytes(b"old")
    image = QImage(512, 512, QImage.Format.Format_RGBA8888)
    image.fill(QColor("red"))
    stop_event = threading.Event()
    entered = threading.Event()
    release = threading.Event()
    real_fsync = os.fsync
    errors: list[Exception] = []

    def paused_fsync(fd: int) -> None:
        entered.set()
        assert release.wait(2.0)
        real_fsync(fd)

    def run_write() -> None:
        try:
            write_custom_item_icon_image_atomic(image, target, stop_event=stop_event)
        except Exception as exc:
            errors.append(exc)

    with patch(
        "cdmw.ui.archive_browser.static_replacement_custom_icon.os.fsync",
        side_effect=paused_fsync,
    ):
        thread = threading.Thread(
            target=run_write,
        )
        thread.start()
        assert entered.wait(2.0)
        stop_event.set()
        release.set()
        thread.join(2.0)

    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], RunCancelled)
    assert target.read_bytes() == b"old"
    assert not tuple(tmp_path.glob(".icon.png.*.tmp"))
