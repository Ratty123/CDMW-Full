from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame

from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.services.archive_mesh_comparison import build_archive_mesh_comparison
from cdmw.services.mesh_rust_preview_package import validate_rust_preview_package
from cdmw.ui.mesh_editor.archive_mesh_comparison import ArchiveMeshComparisonPreview


def _wait(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


class _Controller(QObject):
    package_applied = Signal(str, int)

    def __init__(self, parent):
        super().__init__(parent)
        self.applied_package_path = self.desired_package_path = ""
        self.closed = False

    def shutdown(self):
        self.closed = True
        self.applied_package_path = self.desired_package_path = ""


class _PreviewHost(QFrame):
    """Replace only the external renderer boundary for worker/Qt wiring tests."""

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self.controller = _Controller(self)
        self.loads = []
        self.resets = 0

    def clear_preview(self):
        self.controller.applied_package_path = self.controller.desired_package_path = ""

    def reset_view(self):
        self.resets += 1

    def set_display_mode(self, mode):
        self.comparison_mode = mode

    def set_viewport_display_mode(self, mode):
        self.display_mode = mode

    def load_package(self, package, **kwargs):
        self.loads.append((package, kwargs))
        self.controller.applied_package_path = self.controller.desired_package_path = str(package.package_dir)
        self.controller.package_applied.emit(str(package.package_dir), len(self.loads))
        return True


@pytest.fixture
def preview_host(monkeypatch):
    monkeypatch.setattr("cdmw.ui.mesh_editor.archive_mesh_comparison.RustPreviewHostFrame", _PreviewHost)


def test_comparison_coalesces_changes_discards_stale_packages_and_closes_without_waiting(tmp_path, monkeypatch, preview_host):
    app = QApplication.instance() or QApplication([])
    gate, started = threading.Event(), threading.Event()
    calls, paths = [], []
    concurrent = [0, 0]

    def build(target, source, **kwargs):
        concurrent[0] += 1
        concurrent[1] = max(concurrent)
        calls.append((target, source, kwargs))
        started.set()
        try:
            if len(calls) in {1, 3}:
                assert gate.wait(3)
            directory = kwargs["output_root"] / f"package_{len(calls)}"
            directory.mkdir(parents=True)
            paths.append(directory)
            return SimpleNamespace(package_dir=directory), "untextured_faces"
        finally:
            concurrent[0] -= 1

    monkeypatch.setattr("cdmw.ui.mesh_editor.archive_mesh_comparison.build_archive_mesh_comparison", build)
    widget = ArchiveMeshComparisonPreview(refit_role="armor")
    widget._output_root = tmp_path
    body, armor = ModelPreviewData(path="body.pac"), ModelPreviewData(path="armor.pac")
    try:
        widget.set_models(body, armor)
        _wait(app, started.is_set)
        widget.source_mode_combo.setCurrentIndex(0)
        widget.target_mode_combo.setCurrentIndex(1)
        assert len(calls) == 1 and calls[0][2]["stop_event"].is_set()
        gate.set()
        _wait(app, lambda: not widget.has_live_workers)
        assert len(calls) == 2 and concurrent[1] == 1
        assert calls[1][0] is body and calls[1][1] is armor
        assert calls[1][2]["target_mode"] == "wire" and calls[1][2]["source_mode"] == "solid"
        assert len(widget.viewport.loads) == 1
        assert not paths[0].exists() and paths[1].exists()
        assert widget.viewport.loads[0][1]["reset_view"]
        widget.reset_view_button.click()
        assert widget.viewport.resets == 1
        widget.resize(800, 700)
        app.processEvents()
        assert len(calls) == 2  # Camera/resize uses the resident renderer.

        gate.clear()
        started.clear()
        widget.source_mode_combo.setCurrentIndex(1)
        _wait(app, started.is_set)
        before = time.perf_counter()
        widget.request_shutdown()
        assert time.perf_counter() - before < 0.2
        assert widget.viewport.controller.closed and widget.iter_shutdown_workers()
        assert calls[-1][2]["stop_event"].is_set()
        gate.set()
        _wait(app, lambda: not widget.has_live_workers)
        assert len(widget.viewport.loads) == 1 and all(not path.exists() for path in paths)
    finally:
        widget.request_shutdown()
        gate.set()
        _wait(app, lambda: not widget.has_live_workers)
        widget.deleteLater()
        app.processEvents()


def test_body_picker_defaults_and_missing_preview_notes(preview_host):
    app = QApplication.instance() or QApplication([])
    widget = ArchiveMeshComparisonPreview(refit_role="body")
    try:
        assert widget.target_mode_combo.currentText() == "Wire"
        assert widget.source_mode_combo.currentText() == "Solid"
        widget.set_models(None, None, target_note="Preview unavailable.", source_note="Select a source row.")
        assert widget._target_name.text() == "Preview unavailable."
        assert widget._source_name.text() == "Select a source row."
        assert widget._status.text() == "No preview available."
        assert not widget.has_live_workers
    finally:
        widget.request_shutdown()
        widget.deleteLater()
        app.processEvents()


def test_comparison_failure_is_visible_and_resize_does_not_retry(monkeypatch, preview_host):
    app = QApplication.instance() or QApplication([])
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise ValueError("Invalid geometry coordinates in the selected archive mesh.")

    monkeypatch.setattr("cdmw.ui.mesh_editor.archive_mesh_comparison.build_archive_mesh_comparison", fail)
    widget = ArchiveMeshComparisonPreview()
    try:
        widget.setAttribute(Qt.WA_DontShowOnScreen, True)
        widget.show()
        widget.set_models(ModelPreviewData(path="body.pac"), None)
        _wait(app, lambda: not widget.has_live_workers)
        assert widget._status.text() == "Preview unavailable."
        assert "Invalid geometry coordinates" in widget._status.toolTip()
        widget.resize(800, 650)
        app.processEvents()
        assert len(calls) == 1 and not widget.has_live_workers
    finally:
        widget.request_shutdown()
        _wait(app, lambda: not widget.has_live_workers)
        widget.deleteLater()
        app.processEvents()


def _model(path, scale, center):
    from cdmw.models import HkxPhysicsOverlayBone, HkxPhysicsOverlayData
    positions = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)]
    return ModelPreviewData(path=path, normalization_scale=scale, normalization_center=center,
                            physics_overlay=HkxPhysicsOverlayData(bones=(HkxPhysicsOverlayBone(
                                index=1, parent_index=0, position=(0., 1., 0.),
                                parent_position=(0., 0., 0.),
                            ),)),
                            meshes=[ModelPreviewMesh(positions=[tuple((p[i] - center[i]) * scale for i in range(3))
                                                               for p in positions], indices=[0, 1, 2])])


@pytest.mark.parametrize("target_mode,source_mode", [("solid", "wire"), ("wire", "solid"), ("solid", "solid"), ("wire", "wire")])
def test_comparison_package_preserves_world_coordinates_and_all_display_pairs(tmp_path, target_mode, source_mode):
    package, display = build_archive_mesh_comparison(
        _model("body.pac", 2., (3., 2., 1.)), _model("armor.pac", 5., (-2., 1., 4.)),
        target_mode=target_mode, source_mode=source_mode, output_root=tmp_path,
        scene_session_id="comparison", scene_generation=7, stop_event=threading.Event(),
    )
    assert not validate_rust_preview_package(package.package_dir)
    manifest = json.loads(package.manifest_path.read_text())
    document = json.loads((package.package_dir / "document.json").read_text())
    for part in document["lods"][0]["submeshes"]:
        assert part["positions"] == [[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]
    assert not manifest["textures"]
    assert display == ("wire" if target_mode == source_mode == "wire" else "untextured_faces")
    scene = manifest["state"]["preview_scene"]
    assert not scene.get("skeleton_overlay", {}).get("bones")
    assert scene["comparison_mode"] == "overlay"
    assert scene["reference_draw"] == ("solid" if target_mode == source_mode == "solid" else "wire")
