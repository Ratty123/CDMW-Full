"""The New Item Studio's inline item preview: what it builds a package from, and when."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ItemPreviewPackageTests(unittest.TestCase):
    def test_a_preview_model_goes_the_textured_route_and_a_mesh_the_bare_one(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item import item_preview

        root = Path(tempfile.mkdtemp(prefix="cdmw_item_preview_"))
        seen = {}

        def fake_from_model(model, **kwargs):
            seen["model"] = (model, kwargs)
            return SimpleNamespace(package_dir=root / "cdmw_dotnet_preview_x" / "package")

        def fake_from_mesh(mesh, **kwargs):
            seen["mesh"] = (mesh, kwargs)
            return SimpleNamespace(package_dir=root / "mesh_pkg")

        model = SimpleNamespace(meshes=[object()])
        mesh = ParsedMesh(path="b", format="pac", submeshes=[SubMesh(name="b", vertices=[(0, 0, 0)] * 3, faces=[(0, 1, 2)])])
        with patch("cdmw.services.mesh_dotnet_preview_package.build_or_lookup_dotnet_preview_package_from_model", fake_from_model),              patch("cdmw.services.mesh_dotnet_experiment.build_mesh_dotnet_experiment_package", fake_from_mesh):
            out = item_preview.build_item_preview_package(lambda _stop: model, token=("t", 1), output_root=root, stop_event=threading.Event())
            self.assertEqual(out, root / "cdmw_dotnet_preview_x" / "package")
            self.assertIs(seen["model"][0], model)
            self.assertEqual(seen["model"][1]["cache_mode"], "off", "a transient build, the frame removes it")
            self.assertEqual(seen["model"][1]["cache_root"], root)
            out = item_preview.build_item_preview_package(mesh, token=2, output_root=root, stop_event=threading.Event())
            self.assertEqual(out, root / "mesh_pkg")
            self.assertIs(seen["mesh"][0], mesh)
            with self.assertRaises(ValueError):
                item_preview.build_item_preview_package(lambda _stop: None, token=3, output_root=root, stop_event=threading.Event())
        # cleanup removes the transient parent for the model route, the package itself otherwise
        self.assertEqual(item_preview.package_cleanup_root(root / "cdmw_dotnet_preview_x" / "package", root), root / "cdmw_dotnet_preview_x")
        self.assertEqual(item_preview.package_cleanup_root(root / "mesh_pkg", root), root / "mesh_pkg")
        self.assertEqual(item_preview.package_cleanup_root(root / "other" / "package", root), root / "other" / "package")


class ItemPreviewFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_the_same_token_is_not_rebuilt_and_a_newer_one_supersedes(self) -> None:
        from PySide6.QtWidgets import QWidget

        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        class FakeController:
            def __init__(self):
                from PySide6.QtCore import QObject, Signal

                class Signals(QObject):
                    state_changed = Signal(str, str)
                    capture_completed = Signal(object)

                self._signals = Signals()
                self.state_changed = self._signals.state_changed
                self.capture_completed = self._signals.capture_completed

            def shutdown(self):
                pass

        class FakeHost(QWidget):
            def __init__(self, parent):
                super().__init__(parent)
                self.controller = FakeController()

        frame = ItemPreviewFrame(output_root=Path(tempfile.mkdtemp(prefix="cdmw_item_preview_")), host_factory=FakeHost)
        started = []

        def fake_start(self_, request):
            started.append(request[0])
            self_._thread = object()  # a build in flight

        with patch.object(ItemPreviewFrame, "_start_package", fake_start):
            frame.show(lambda _stop: None, token="a")
            self.assertEqual(started, ["a"])
            frame.show(lambda _stop: None, token="a")
            self.assertEqual(started, ["a"], "the token in flight is left alone")
            frame.show(lambda _stop: None, token="b")
            self.assertEqual(started, ["a"], "a newer token waits for the build in flight")
            self.assertEqual(frame._pending[0], "b")
            frame._thread = None  # the build finished without showing "b" (is_ready stays False)
            frame.show(lambda _stop: None, token="b")
            self.assertEqual(started, ["a", "b"], "once idle and not showing it, the newest request is built")
            frame._thread = None
            frame.is_ready = True  # "b" is on screen now
            frame.show(lambda _stop: None, token="b")
            self.assertEqual(started, ["a", "b"], "what is shown is not rebuilt")
            frame.show(None)
            self.assertIsNone(frame._pending)
        frame._closed = True


if __name__ == "__main__":
    unittest.main()
