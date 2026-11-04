"""The New Item Studio's inline item preview: what it builds a package from, and when."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ItemPreviewPackageTests(unittest.TestCase):
    def test_preview_model_adapter_keeps_complete_canonical_material_bindings(self) -> None:
        from cdmw.models import ModelPreviewData, ModelPreviewMesh
        from cdmw.modding.mesh_deformer import _EXTRA_SUBMESH_ATTRS
        from cdmw.services.mesh_dotnet_material_bindings import _DOTNET_PREVIEW_MATERIAL_ATTRS
        from cdmw.services.mesh_rust_preview_cache import parsed_mesh_from_model_preview

        self.assertEqual(set(_DOTNET_PREVIEW_MATERIAL_ATTRS) - set(_EXTRA_SUBMESH_ATTRS), set())

        source = ModelPreviewMesh(
            material_name="handle",
            texture_name="handle_base",
            positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            normals=[(0.0, 0.0, 1.0)] * 3,
            indices=[0, 1, 2],
            source_submesh_index=0,
            preview_texture_path="handle_base.png",
            preview_texture_dds_path="handle_base.dds",
            preview_normal_texture_default_path="handle_normal.dds",
            preview_normal_texture_default_name="handle_normal.dds",
            preview_normal_texture_default_strength=0.8,
            preview_material_texture_default_path="handle_material.dds",
            preview_material_texture_default_name="handle_material.dds",
            preview_material_texture_default_type="material",
            preview_material_texture_default_subtype="standard_v2_material",
            preview_material_texture_default_packed_channels=("ao", "roughness", "metalness"),
            preview_height_texture_default_path="handle_height.dds",
            preview_height_texture_default_name="handle_height.dds",
            preview_emissive_texture_default_path="handle_emissive.dds",
            preview_emissive_texture_default_name="handle_emissive.dds",
        )
        model = ModelPreviewData(path="character/weapon/handle.pac", format="pac", meshes=[source])

        converted = parsed_mesh_from_model_preview(model).submeshes[0]

        self.assertEqual(converted.preview_normal_texture_default_path, "handle_normal.dds")
        self.assertEqual(converted.preview_normal_texture_default_strength, 0.8)
        self.assertEqual(converted.preview_material_texture_default_subtype, "standard_v2_material")
        self.assertEqual(
            converted.preview_material_texture_default_packed_channels,
            ("ao", "roughness", "metalness"),
        )
        self.assertEqual(converted.preview_height_texture_default_path, "handle_height.dds")
        self.assertEqual(converted.preview_emissive_texture_default_path, "handle_emissive.dds")
        self.assertEqual(converted.preview_source_asset_path, "character/weapon/handle.pac")


class ItemPreviewFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        from PySide6.QtCore import QEventLoop
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        frames = [widget for widget in self.app.allWidgets() if isinstance(widget, ItemPreviewFrame)]
        for frame in frames:
            frame.request_shutdown()
        deadline = time.monotonic() + 3
        while any(frame.iter_shutdown_workers() for frame in frames) and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertFalse(any(frame.iter_shutdown_workers() for frame in frames))

    @staticmethod
    def _fake_host_class():
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtWidgets import QWidget

        class Signals(QObject):
            state_changed = Signal(str, str)
            capture_completed = Signal(object)

        class FakeController:
            def __init__(self):
                self._signals = Signals()
                self.state_changed = self._signals.state_changed
                self.capture_completed = self._signals.capture_completed

            def shutdown(self):
                pass

        class FakeHost(QWidget):
            alignment_drag_started = Signal()
            alignment_drag_changed = Signal(float, float, float)
            alignment_drag_finished = Signal(float, float, float)
            alignment_rotation_changed = Signal(float, float, float)
            alignment_rotation_finished = Signal(float, float, float)
            alignment_scale_changed = Signal(float, float, float)
            alignment_scale_finished = Signal(float, float, float)

            def __init__(self, parent):
                super().__init__(parent)
                self.controller = FakeController()
                self.calls = []

            def __getattr__(self, name):
                if name.startswith("set_") or name in {"load_package", "capture_replacement_icon", "reset_view", "remember_editable_local_bounds"}:
                    def record(*args, **kwargs):
                        self.calls.append((name, args, kwargs))
                        return True

                    return record
                raise AttributeError(name)

        return FakeHost

    def test_an_icon_capture_renders_the_viewport_shape_at_full_resolution(self) -> None:
        """A pane-sized frame left the icon selection to be upscaled and blurry."""

        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        workspace = tempfile.TemporaryDirectory(prefix="cdmw-item-preview-capture-")
        self.addCleanup(workspace.cleanup)
        frame = ItemPreviewFrame(output_root=Path(workspace.name) / "output", host_factory=self._fake_host_class())
        self.assertTrue(frame._ensure_host())
        frame.host.resize(450, 300)
        frame.is_ready = True
        self.assertTrue(frame.capture())
        captures = [kwargs for name, _args, kwargs in frame.host.calls if name == "capture_replacement_icon"]
        self.assertEqual(captures, [{"width": 2048, "height": 1365}])

    def test_a_borrowed_view_hides_the_gizmo_and_ignores_drags(self) -> None:
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame
        from cdmw.ui.new_item.model_import import ModelPlacement

        workspace = tempfile.TemporaryDirectory(prefix="cdmw-item-preview-editable-")
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        frame = ItemPreviewFrame(output_root=root / "output", host_factory=self._fake_host_class())
        frame.gizmo_visible.blockSignals(True)
        frame.gizmo_visible.setChecked(True)
        frame.gizmo_visible.blockSignals(False)
        moved = []
        frame.placement_changed.connect(lambda placement, finished: moved.append((placement, finished)))
        self.assertTrue(frame._ensure_host())
        host = frame.host
        with patch.object(ItemPreviewFrame, "_start_package", lambda *_args, **_kwargs: None):
            frame.show_placement(object(), token="scene", placement=ModelPlacement())
        # outside the preview workspace, so the frame never tries to delete it
        frame._package_ready(root / "elsewhere" / "package_scene", token="scene", is_placement=True)
        host.controller.state_changed.emit("ready", "")
        self.assertTrue(frame.showing_placement)

        def gizmo_shown() -> bool:
            states = [kwargs for name, _args, kwargs in host.calls if name == "set_alignment_state"]
            return bool(states[-1]["enabled"])

        self.assertTrue(gizmo_shown())
        frame.set_placement_editable(False)
        self.assertFalse(gizmo_shown())
        host.alignment_drag_started.emit()
        host.alignment_drag_finished.emit(1.0, 0.0, 0.0)
        self.assertEqual(moved, [], "a drag on a view that only shows the item moves nothing")
        self.assertEqual(frame.placement, ModelPlacement())

        frame.set_placement_editable(True)
        self.assertTrue(gizmo_shown())
        host.alignment_drag_started.emit()
        host.alignment_drag_finished.emit(1.0, 0.0, 0.0)
        self.assertEqual(moved, [(ModelPlacement(offset=(1.0, 0.0, 0.0)), True)])
        self.assertEqual(frame.placement.offset, (1.0, 0.0, 0.0))

    def test_reselecting_a_cached_template_frames_it_with_a_grounded_package(self) -> None:
        """Template A, template B, back to A: the warm cache loaded A's Preview Core
        package first with a camera reset. It has bounds but no grounded initial
        view, and the viewport said "Full textures loaded" over an empty scene."""

        from PySide6.QtCore import QEventLoop
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame, ProgressivePreviewSource

        workspace = tempfile.TemporaryDirectory(prefix="cdmw-item-preview-reselect-")
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        native_root = root / "native"

        def write_package(path: Path, *, grounded: bool) -> Path:
            path.mkdir(parents=True, exist_ok=True)
            framing = {"bounds": {"min": [0, 0, 0], "max": [1, 1, 1]}}
            if grounded:
                framing["initial_view"] = {"view_direction": [0, 0, -1], "screen_up_direction": [0, 1, 0]}
            (path / "manifest.json").write_text(
                json.dumps({"state": {"preview_scene": {"framing": framing}}}), encoding="utf-8")
            return path

        counter = iter(range(1000))

        def fake_python_package(source, **_kwargs):
            # Geometry packages are built by the Python writer with a grounded view.
            return write_package(root / "output" / f"geometry_{next(counter)}" / "package", grounded=True)

        geometry_calls = []

        def template_source(key):
            native = write_package(root / "output" / "rust_wgpu_v1" / "packages" / f"t{key}" / "package",
                                   grounded=False)

            def geometry(_stop):
                geometry_calls.append(key)
                return object()

            def materials(_stop, **_context):
                return native

            def cached(_stop, **_context):
                return native

            return ProgressivePreviewSource(geometry, materials, supports_fast_material_package=True,
                                            cached_materials=cached, geometry_token=("template-scene", key))

        frame = ItemPreviewFrame(output_root=root / "output", native_preview_core_cache_root=native_root,
                                 host_factory=self._fake_host_class())
        frame.set_cache_mode("balanced")
        self.assertTrue(frame._ensure_host())
        host = frame.host
        loads = []

        def load_package(package, *_args, reset_view=False, **_kwargs):
            # Retired transient packages are removed later; read the framing now.
            manifest = json.loads((Path(package) / "manifest.json").read_text(encoding="utf-8"))
            framing = manifest["state"]["preview_scene"]["framing"]
            loads.append((Path(package), bool(reset_view), "initial_view" in framing))
            return True

        host.load_package = load_package

        def settle():
            deadline = time.monotonic() + 5
            while (frame._thread is not None or frame._upgrade_request is not None) and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            host.controller.state_changed.emit("ready", "")

        with patch("cdmw.ui.new_item.item_preview.build_item_preview_package", fake_python_package):
            for key in (1, 2, 1):
                frame.show(template_source(key), token=("template", key), framing_key=key)
                settle()
            loads_before_same_frame = len(geometry_calls)
            # Same template framed already (another token for it): the cached
            # material package may land directly, without re-reading geometry.
            frame.show(template_source(1), token=("template", 1, "glow"), framing_key=1)
            settle()

        self.assertTrue(loads)
        for package, reset_view, grounded in loads:
            if reset_view:
                self.assertTrue(grounded, f"{package} took a camera reset without a grounded view")
        self.assertEqual(geometry_calls[:3], [1, 2, 1], "a newly framed template builds its geometry stage")
        self.assertEqual(len(geometry_calls), loads_before_same_frame, "an already framed template reuses the cache")
        self.assertEqual(loads[-1][0].parent.name, "t1")


if __name__ == "__main__":
    unittest.main()
