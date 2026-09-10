from __future__ import annotations

import threading
import time

from PySide6.QtGui import QColor, QImage
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.models import ModelPreviewData
from cdmw.ui.mesh_editor.archive_mesh_comparison import ArchiveMeshComparisonPreview


def _wait(app, predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_comparison_coalesces_changes_ignores_stale_images_and_closes_without_waiting(monkeypatch):
    app = QApplication.instance() or QApplication([])
    gate = threading.Event()
    started = threading.Event()
    calls = []
    concurrent = [0, 0]

    def render(target, source, **kwargs):
        concurrent[0] += 1
        concurrent[1] = max(concurrent)
        calls.append((target, source, kwargs))
        started.set()
        try:
            if len(calls) in {1, 3}:
                assert gate.wait(2)
            result = QImage(320, 260, QImage.Format_ARGB32)
            result.fill(QColor("red" if len(calls) == 1 else "blue"))
            return result  # Deliberately publish even after cancellation.
        finally:
            concurrent[0] -= 1

    monkeypatch.setattr("cdmw.ui.mesh_editor.archive_mesh_comparison.render_static_model_comparison_image", render)
    widget = ArchiveMeshComparisonPreview(refit_role="armor")
    body, armor = ModelPreviewData(path="body.pac"), ModelPreviewData(path="armor.pac")
    try:
        widget.set_models(body, armor)
        _wait(app, started.is_set)
        widget.source_mode_combo.setCurrentIndex(0)
        widget.target_mode_combo.setCurrentIndex(1)
        app.processEvents()
        assert len(calls) == 1
        assert calls[0][2]["stop_event"].is_set()
        assert widget.image is None
        gate.set()
        _wait(app, lambda: not widget.has_live_workers)
        assert len(calls) == 2 and concurrent[1] == 1
        assert calls[1][0] is body and calls[1][1] is armor
        assert calls[1][2]["target_mode"] == "wireframe"
        assert calls[1][2]["source_mode"] == "solid"
        assert widget.image.pixelColor(0, 0) == QColor("blue")

        gate.clear()
        started.clear()
        widget.source_mode_combo.setCurrentIndex(1)
        _wait(app, started.is_set)
        accepted = widget.image
        before = time.perf_counter()
        widget.request_shutdown()
        assert time.perf_counter() - before < 0.2
        assert widget.iter_shutdown_workers()
        assert calls[-1][2]["stop_event"].is_set()
        widget.set_models(None, None)
        gate.set()
        _wait(app, lambda: not widget.has_live_workers)
        assert widget.image is accepted and len(calls) == 3
    finally:
        widget.request_shutdown()
        gate.set()
        _wait(app, lambda: not widget.has_live_workers)
        widget.deleteLater()
        app.processEvents()


def test_body_picker_defaults_to_solid_body_and_wire_target_and_shows_missing_preview_notes():
    app = QApplication.instance() or QApplication([])
    widget = ArchiveMeshComparisonPreview(refit_role="body")
    try:
        assert widget.target_mode_combo.currentText() == "Wire"
        assert widget.source_mode_combo.currentText() == "Solid"
        widget.set_models(None, None, target_note="Preview unavailable.", source_note="Select a source row.")
        assert widget._target_name.text() == "Preview unavailable."
        assert widget._source_name.text() == "Select a source row."
        assert widget.image_label.text() == "No preview available."
        assert not widget.has_live_workers
    finally:
        widget.request_shutdown()
        widget.deleteLater()
        app.processEvents()


def test_comparison_render_failure_is_visible_and_does_not_start_a_resize_retry_loop(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise ValueError("Invalid geometry coordinates in the selected archive mesh.")

    monkeypatch.setattr("cdmw.ui.mesh_editor.archive_mesh_comparison.render_static_model_comparison_image", fail)
    widget = ArchiveMeshComparisonPreview()
    try:
        widget.setAttribute(Qt.WA_DontShowOnScreen, True)
        widget.resize(600, 600)
        widget.show()
        app.processEvents()
        widget.set_models(ModelPreviewData(path="body.pac"), None)
        _wait(app, lambda: not widget.has_live_workers)
        assert widget.image_label.text() == "Preview unavailable."
        assert "Invalid geometry coordinates" in widget._status.toolTip()
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert len(calls) == 1
        assert not widget.has_live_workers and not widget._resize_timer.isActive()
    finally:
        widget.request_shutdown()
        _wait(app, lambda: not widget.has_live_workers)
        widget.deleteLater()
        app.processEvents()
