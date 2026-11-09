"""The Placement viewport draws new geometry off the UI thread and skips unchanged geometry.

On the UI thread a mesh layer cost 40 ms alone and 2.7 s while a background loader ran
Python, so a body or weapon arriving during loading froze the window. A layer with new
geometry under an unchanged camera is now drawn by a worker while the picture already on
screen stays up; a camera change still draws at once. Synthetic geometry only.
"""

from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication

from tools.placement_studio import viewport as viewport_module
from tools.placement_studio.meshes import Mesh
from tools.placement_studio.model import Vec3
from tools.placement_studio.skeleton import BoneHierarchy, BoneNode
from tools.placement_studio.viewport import (
    SkeletonViewport,
    _MeshPaintCache,
    _render_layer,
    _same_geometry,
    _triangle_paths,
)

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0)

# A closed box, wound outwards.
_BOX_TRIANGLES = (
    (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
    (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
)


class _Posed:
    """What the window hands the viewport for a posed body: an array and triangles."""

    __slots__ = ("points", "triangles", "groups")

    def __init__(self, points, triangles, groups=None) -> None:
        self.points = points
        self.triangles = triangles
        self.groups = groups


def _box(shift: float = 0.0) -> _Posed:
    corners = np.array(
        [(x, y, z) for z in (-0.2, 0.2) for x, y in ((-0.2, 0.8), (0.2, 0.8), (0.2, 1.2), (-0.2, 1.2))],
        dtype=float,
    )
    corners[:, 0] += shift
    return _Posed(corners, _BOX_TRIANGLES, np.zeros(len(_BOX_TRIANGLES), dtype=np.int32))


def _view() -> SkeletonViewport:
    QApplication.instance() or QApplication([])
    hierarchy = BoneHierarchy([BoneNode(0, "Root", -1, _IDENTITY, Vec3(0.0, 1.0, 0.0))], "test")
    view = SkeletonViewport()
    view.resize(800, 600)
    view.set_scene(hierarchy, [], {})
    return view


def _wait(predicate, seconds: float = 10.0) -> bool:
    app = QApplication.instance()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _settled(view: SkeletonViewport) -> SkeletonViewport:
    view.grab()
    assert _wait(lambda: view._pending_layer is None)
    view.grab()
    assert view._shown_layer[1] == view._mesh_generation
    return view


# ── unchanged geometry ──────────────────────────────────────────────


def test_equal_geometry_in_fresh_objects_is_the_same() -> None:
    assert _same_geometry(_box(), _box())
    assert not _same_geometry(_box(), _box(0.01))
    assert not _same_geometry(None, _box())
    vertices = tuple(Vec3(*map(float, point)) for point in _box().points)
    assert _same_geometry(
        Mesh(name="a", vertices=vertices, triangles=_BOX_TRIANGLES),
        Mesh(name="b", vertices=tuple(vertices), triangles=_BOX_TRIANGLES),
    )
    moved = _box()
    moved.groups = np.ones(len(_BOX_TRIANGLES), dtype=np.int32)
    assert not _same_geometry(_box(), moved)


def test_setting_the_same_meshes_again_does_not_redraw() -> None:
    view = _view()
    view.set_meshes(_box(), None)
    generation = view._mesh_generation
    view.set_meshes(_box(), None)
    assert view._mesh_generation == generation
    view.set_meshes(_box(0.05), None)
    assert view._mesh_generation == generation + 1
    view.set_meshes(_box(0.05), None, clipping=[1])
    assert view._mesh_generation == generation + 2


# ── layers drawn off the UI thread ──────────────────────────────────


def test_the_first_picture_shows_the_floor_while_the_meshes_draw() -> None:
    view = _view()
    view.set_meshes(_box(), None)
    view.grab()
    assert view._pending_layer is not None
    assert view._shown_layer[1] == -1  # the floor-only picture
    _settled(view)
    assert view._body_screen is not None


def test_new_geometry_keeps_the_picture_on_screen_until_it_is_ready() -> None:
    view = _settled(_view_with_box())
    shown = view._shown_layer
    view.set_meshes(_box(0.1), None)
    view.grab()
    assert view._shown_layer == shown
    assert view._pending_layer == (shown[0], view._mesh_generation)
    _settled(view)
    assert view._shown_layer != shown


def test_a_camera_change_draws_at_once() -> None:
    view = _settled(_view_with_box())
    view._camera.yaw += 0.4
    view.set_meshes(_box(0.1), None)
    view.grab()
    assert view._pending_layer is None
    assert view._shown_layer == view._scene_background[0]
    assert view._shown_layer[1] == view._mesh_generation


def test_a_resize_shows_the_old_picture_scaled_until_the_new_one_is_drawn() -> None:
    view = _settled(_view_with_box())
    shown = view._shown_layer
    view.resize(700, 450)
    view.grab()
    assert view._shown_layer == shown
    assert view._pending_layer is not None
    _settled(view)
    assert view._shown_layer[0][:2] == (700, 450)


def test_a_resize_is_a_scale_about_the_centre() -> None:
    """What `_draw_resized` relies on: the projection only scales and shifts with the size."""

    view = _view()
    point = Vec3(0.13, 1.07, -0.05)
    before = view._project(point)
    old_width, old_height = view.width(), view.height()
    view.resize(640, 420)
    after = view._project(point)
    scale = 420 / old_height
    assert after.x() == pytest.approx(320 + (before.x() - old_width / 2) * scale)
    assert after.y() == pytest.approx(210 + (before.y() - old_height / 2) * scale)


def test_a_failing_worker_falls_back_to_drawing_here(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _settled(_view_with_box())
    real = viewport_module._render_layer

    def main_thread_only(*args):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("worker broke")
        return real(*args)

    monkeypatch.setattr(viewport_module, "_render_layer", main_thread_only)
    view.set_meshes(_box(0.1), None)
    view.grab()
    assert _wait(lambda: not view.background_layers)
    view.grab()
    assert view._shown_layer[1] == view._mesh_generation


def test_a_stopped_viewport_draws_on_the_ui_thread() -> None:
    view = _settled(_view_with_box())
    view.stop_rendering()
    view.set_meshes(_box(0.1), None)
    view.grab()
    assert view._pending_layer is None
    assert view._shown_layer[1] == view._mesh_generation


def test_a_worker_draws_the_same_pixels_as_the_ui_thread() -> None:
    view = _view_with_box()
    weapon_points = tuple(Vec3(float(x) + 0.3, float(y), float(z)) for x, y, z in _box().points)
    view.set_meshes(_box(), Mesh(name="w", vertices=weapon_points, triangles=_BOX_TRIANGLES), [0, 1])
    args = (800, 600, 1.0, view.rect(), view._view_frame(), view.GROUND_EXTENT, view._NEAR,
            view._mesh_scene())
    here = _render_layer(*args, _MeshPaintCache())
    there = {}
    worker = threading.Thread(target=lambda: there.setdefault("layer", _render_layer(*args, _MeshPaintCache())))
    worker.start()
    worker.join()
    assert bytes(here[0].constBits()) == bytes(there["layer"][0].constBits())
    assert here[2] == there["layer"][2] and here[2]  # the weapon is hit-testable


def test_a_superseded_layer_stops_early() -> None:
    view = _view_with_box()
    args = (800, 600, 1.0, view.rect(), view._view_frame(), view.GROUND_EXTENT, view._NEAR,
            view._mesh_scene(), _MeshPaintCache())
    assert _render_layer(*args, lambda: True) is None
    assert _render_layer(*args, lambda: False)[1] is not None


def _view_with_box() -> SkeletonViewport:
    view = _view()
    view.set_meshes(_box(), None)
    return view


# ── the paths read from one stream ──────────────────────────────────


def test_stream_built_paths_match_moveto_lineto_paths() -> None:
    """Pins the QDataStream layout: a PySide upgrade that changed it would fail here."""

    xy = np.array(
        [(0.0, 0.0, 10.0, 0.0, 0.0, 10.0), (5.5, 5.0, 15.0, 5.25, 5.0, 15.0), (1, 2, 3, 4, 5, 7)],
        dtype=float,
    )
    built = list(_triangle_paths(xy, [2, 1]))
    expected = []
    for rows in (xy[:2], xy[2:]):
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        for ax, ay, bx, by, cx, cy in rows.tolist():
            path.moveTo(ax, ay)
            path.lineTo(bx, by)
            path.lineTo(cx, cy)
            path.closeSubpath()
        expected.append(path)
    assert len(built) == 2
    for got, want in zip(built, expected):
        assert got.fillRule() == Qt.WindingFill
        assert got.elementCount() == want.elementCount()
        assert got == want
