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
            seen.setdefault("mesh_calls", []).append((mesh, kwargs))
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
            # a placement scene: the model is the editable role, the template the reference, the
            # placement baked into the scene frame as the pipeline's own transform
            from cdmw.ui.new_item.model_import import ModelPlacement

            scene = item_preview.PlacementScene(template=mesh, model=mesh, placement=ModelPlacement(offset=(0.0, 0.0, -0.3), rotation=(90.0, 0.0, 0.0), scale=(2.0, 2.0, 2.0)))
            item_preview.build_item_preview_package(scene, token=4, output_root=root, stop_event=threading.Event())
            _mesh, kwargs = seen["mesh_calls"][-1]
            self.assertIs(kwargs["reference_mesh"], mesh)
            self.assertEqual(kwargs["comparison_mode"], "overlay")
            transform = kwargs["scene_transform"]
            self.assertEqual(transform.alignment_mode, "manual")
            self.assertEqual(transform.offset_xyz, (0.0, 0.0, -0.3))
            self.assertEqual(transform.rotate_xyz_degrees, (90.0, 0.0, 0.0))
            self.assertEqual(transform.scale_xyz, (2.0, 2.0, 2.0))
        # cleanup removes the transient parent for the model route, the package itself otherwise
        self.assertEqual(item_preview.package_cleanup_root(root / "cdmw_dotnet_preview_x" / "package", root), root / "cdmw_dotnet_preview_x")
        self.assertEqual(item_preview.package_cleanup_root(root / "mesh_pkg", root), root / "mesh_pkg")
        self.assertEqual(item_preview.package_cleanup_root(root / "other" / "package", root), root / "other" / "package")


class PlacementConventionTests(unittest.TestCase):
    def test_the_host_matrix_is_the_pipeline_transform_and_the_pivot_follows(self) -> None:
        """One convention: the host's fallback matrix (what the helper draws and what its
        own gizmo drag rebuilds) equals the static replacement pipeline's transform for the
        same numbers, and the placement pivot (where the gizmo sits) is the source anchor
        under the placement, so it rides along with the model."""

        import random

        from cdmw.modding.static_mesh_geometry import _rotate_xyz
        from cdmw.ui.new_item.model_import import ModelPlacement
        from cdmw.ui.preview.dotnet_host import _apply_placement_to_editable_role

        random.seed(7)
        for _ in range(50):
            rotation = tuple(random.uniform(-180.0, 180.0) for _ in range(3))
            placement = ModelPlacement(offset=(0.3, -0.2, 1.1), rotation=rotation, scale=(0.5, 2.0, 1.5))
            point = tuple(random.uniform(-2.0, 2.0) for _ in range(3))
            shown = placement.apply(point)
            rotated = _rotate_xyz((point[0] * 0.5, point[1] * 2.0, point[2] * 1.5), rotation)
            built = (rotated[0] + 0.3, rotated[1] - 0.2, rotated[2] + 1.1)
            for axis in range(3):
                self.assertAlmostEqual(shown[axis], built[axis], places=9)
        # the build transform carries the numbers as they are
        transform = ModelPlacement(offset=(1, 2, 3), rotation=(10, 20, 30), scale=(2, 2, 2)).build_transform()
        self.assertEqual(transform.rotate_xyz_degrees, (10.0, 20.0, 30.0))
        self.assertEqual(transform.offset_xyz, (1.0, 2.0, 3.0))
        self.assertEqual(transform.scale_xyz, (2.0, 2.0, 2.0))
        self.assertEqual(transform.alignment_mode, "manual")
        # the pivot: the anchor under the placement (the model's origin with no anchor)
        state = {"roles": {"editable": {"model_matrix": [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0], "world_bounds": {"min": [0, 0, 0], "max": [1, 1, 1]}}}}
        _apply_placement_to_editable_role(state, {"translation": (0.25, 0.0, -0.4), "rotation_degrees": (0.0, 90.0, 0.0), "scale": (2.0, 2.0, 2.0)})
        self.assertEqual([round(v, 6) for v in state["placement_pivot"]], [0.25, 0.0, -0.4])
        state["automatic_alignment"] = {"source_anchor": [0.0, 0.0, 1.0]}
        _apply_placement_to_editable_role(state, {"translation": (0.25, 0.0, -0.4), "rotation_degrees": (0.0, 90.0, 0.0), "scale": (2.0, 2.0, 2.0)})
        # (0, 0, 1) scaled by 2 and turned 90 degrees about y lands on +x: (2, 0, 0), then the offset
        self.assertEqual([round(v, 6) for v in state["placement_pivot"]], [2.25, 0.0, -0.4])
        self.assertEqual([round(v, 6) for v in state["roles"]["editable"]["world_bounds"]["min"]], [0.25, 0.0, -2.4])


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
                if name.startswith("set_") or name in {"load_package", "capture_replacement_icon", "reset_view", "remember_editable_local_bounds"}:
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
        frame._ensure_host()  # as if the frame had been on screen: the viewport exists
        moves = []
        frame.placement_changed.connect(lambda p, done: moves.append((p, done)))
        start = ModelPlacement(offset=(0.0, 0.0, -0.2), scale=(0.5, 0.5, 0.5))
        with patch.object(ItemPreviewFrame, "_start_package", lambda self_, request: setattr(self_, "_thread", object())):
            frame.show_placement(lambda _stop: PlacementScene(template=None, model=None), token="p", placement=start, model_bounds=((0, 0, 0), (1, 1, 1)))
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
        self.assertNotIn("source_submesh_indices", state[2], "no source highlight: the model draws as itself")
        self.assertIn(("remember_editable_local_bounds", ((0, 0, 0), (1, 1, 1)), {}), host.calls)
        pushed = next(c for c in host.calls if c[0] == "set_alignment_preview_transform")
        self.assertEqual(pushed[2]["translation"], (0.0, 0.0, -0.2))
        self.assertEqual(pushed[2]["scale_xyz"], (0.5, 0.5, 0.5))
        # a move drag: deltas are totals since the drag began, added to the base; nothing
        # is pushed to the helper until the drag ends (it draws the provisional itself)
        host.calls.clear()
        host.alignment_drag_started.emit()
        host.alignment_drag_changed.emit(0.1, 0.0, 0.0)
        host.alignment_drag_changed.emit(0.2, 0.0, 0.0)
        self.assertFalse([c for c in host.calls if c[0] == "set_alignment_preview_transform"], "no push mid-drag")
        host.alignment_drag_finished.emit(0.25, 0.0, 0.05)
        self.assertEqual(len([c for c in host.calls if c[0] == "set_alignment_preview_transform"]), 1, "one push, at the end")
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
        frame.show_placement(lambda _stop: None, token="p", placement=ModelPlacement())
        self.assertIn("set_alignment_preview_transform", [c[0] for c in host.calls])
        # leaving for a plain source forgets the placement
        frame.show(None)
        self.assertIsNone(frame.placement)
        frame._closed = True

    def test_a_hidden_frame_builds_the_package_and_loads_it_when_shown(self) -> None:
        """The package builds ahead of the step (shown or not); the viewport starts, and the
        package loads, when the frame comes on screen."""

        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        FakeHost = self._fake_host_class()
        frame = ItemPreviewFrame(output_root=Path(tempfile.mkdtemp(prefix="cdmw_item_preview_")), host_factory=FakeHost)
        started = []
        with patch.object(ItemPreviewFrame, "_start_package", lambda self_, request: started.append(request[0])):
            frame.show(lambda _stop: None, token="t")
        self.assertEqual(started, ["t"], "the build starts while hidden")
        self.assertIsNone(frame.host, "no viewport until the frame shows")
        frame._package_ready(Path("pkg"))
        self.assertIsNone(frame.host)
        self.assertEqual(frame._deferred_package, Path("pkg"))
        with patch.object(ItemPreviewFrame, "isVisible", lambda self_: True):
            frame.showEvent(None)
        self.assertIsNotNone(frame.host, "the viewport starts on show")
        self.assertIsNone(frame._deferred_package)
        self.assertIn("load_package", [c[0] for c in frame.host.calls])
        frame._closed = True

    def test_the_same_token_is_not_rebuilt_and_a_newer_one_supersedes(self) -> None:
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        FakeHost = self._fake_host_class()
        frame = ItemPreviewFrame(output_root=Path(tempfile.mkdtemp(prefix="cdmw_item_preview_")), host_factory=FakeHost)
        frame._ensure_host()
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
