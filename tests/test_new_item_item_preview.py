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


if __name__ == "__main__":
    unittest.main()
