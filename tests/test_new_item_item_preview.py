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
                if name.startswith("set_") or name in {"load_package", "capture_replacement_icon", "reset_view"}:
                    def record(*args, **kwargs):
                        self.calls.append((name, args, kwargs))
                        return True

                    return record
                raise AttributeError(name)

        return FakeHost

    def test_a_placement_scene_takes_the_gizmo_and_the_numbers(self) -> None:
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame, PlacementScene
        from cdmw.ui.new_item.model_import import ModelPlacement

        FakeHost = self._fake_host_class()
        frame = ItemPreviewFrame(output_root=Path(tempfile.mkdtemp(prefix="cdmw_item_preview_")), host_factory=FakeHost)
        moves = []
        frame.placement_changed.connect(lambda p, done: moves.append((p, done)))
        start = ModelPlacement(offset=(0.0, 0.0, -0.2), scale=(0.5, 0.5, 0.5))
        with patch.object(ItemPreviewFrame, "_start_package", lambda self_, request: setattr(self_, "_thread", object())):
            frame.show_placement(lambda _stop: PlacementScene(template=None, model=None), token="p", placement=start, model_submesh_count=3)
        self.assertIs(frame.placement, start)
        host = frame.host
        # the package is ready: the scene's presentation goes out, not the icon capture mode
        frame._thread = None
        frame._host_state("ready", "")
        frame._package_dir = Path("x")
        frame._host_state("ready", "")
        names = [c[0] for c in host.calls]
        self.assertIn("set_alignment_state", names)
        self.assertIn("set_alignment_gizmo_tool", names)
        self.assertIn("set_alignment_preview_transform", names)
        self.assertIn(("set_icon_capture_mode", (False,), {}), host.calls)
        self.assertIn("reset_view", names, "the camera is framed on the placed model once")
        state = next(c for c in host.calls if c[0] == "set_alignment_state")
        self.assertTrue(state[2]["enabled"])
        self.assertEqual(tuple(state[2]["source_submesh_indices"]), (0, 1, 2))
        pushed = next(c for c in host.calls if c[0] == "set_alignment_preview_transform")
        self.assertEqual(pushed[2]["translation"], (0.0, 0.0, -0.2))
        self.assertEqual(pushed[2]["scale_xyz"], (0.5, 0.5, 0.5))
        # a move drag: deltas are totals since the drag began, added to the base
        host.alignment_drag_started.emit()
        host.alignment_drag_changed.emit(0.1, 0.0, 0.0)
        host.alignment_drag_changed.emit(0.2, 0.0, 0.0)
        host.alignment_drag_finished.emit(0.25, 0.0, 0.05)
        self.assertEqual(tuple(round(v, 9) for v in moves[-1][0].offset), (0.25, 0.0, -0.15))
        self.assertTrue(moves[-1][1])
        self.assertEqual(moves[0][0].offset, (0.1, 0.0, -0.2))
        self.assertFalse(moves[0][1])
        # a rotate drag adds degrees; a scale drag adds per axis and never reaches zero
        host.alignment_drag_started.emit()
        host.alignment_rotation_finished.emit(0.0, 90.0, 0.0)
        self.assertEqual(frame.placement.rotation, (0.0, 90.0, 0.0))
        host.alignment_drag_started.emit()
        host.alignment_scale_finished.emit(-0.9, 0.0, 0.0)
        self.assertGreater(frame.placement.scale[0], 0.0)
        self.assertEqual(frame.placement.scale[1], 0.5)
        # the numbers: set_placement pushes at once; the tool and view go to the host
        host.calls.clear()
        frame.set_placement(ModelPlacement(offset=(1.0, 2.0, 3.0)))
        self.assertEqual(host.calls[-1][2]["translation"], (1.0, 2.0, 3.0))
        frame.set_gizmo_tool("rotate")
        self.assertIn(("set_alignment_gizmo_tool", ("rotate",), {}), host.calls)
        frame.set_view_mode("side_by_side")
        self.assertIn(("set_display_mode", ("side_by_side",), {}), host.calls)
        frame.set_gizmo_enabled(False)
        self.assertFalse(next(c for c in reversed(host.calls) if c[0] == "set_alignment_state")[2]["enabled"])
        # the same token with a new placement only re-presents
        host.calls.clear()
        frame.show_placement(lambda _stop: None, token="p", placement=ModelPlacement(), model_submesh_count=3)
        self.assertIn("set_alignment_preview_transform", [c[0] for c in host.calls])
        # leaving for a plain source forgets the placement
        frame.show(None)
        self.assertIsNone(frame.placement)
        frame._closed = True

    def test_the_same_token_is_not_rebuilt_and_a_newer_one_supersedes(self) -> None:
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        FakeHost = self._fake_host_class()
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
