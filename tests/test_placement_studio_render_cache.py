"""Stationary scene reuse preserves the full image and keeps live overlays responsive."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from tools.paa_motion.pose import IDENTITY_MATRIX
from tools.placement_studio.model import Vec3
from tools.placement_studio.skeleton import BoneHierarchy, BoneNode
from tools.placement_studio.viewport import SkeletonViewport
from tools.placement_studio.window import PosedMesh


_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def view():
    widget = SkeletonViewport()
    widget.resize(360, 320)
    hierarchy = BoneHierarchy([BoneNode(0, 'root', -1, IDENTITY_MATRIX, Vec3())], 'cache')
    widget.set_scene(hierarchy, [])
    widget._camera.target = Vec3(0., .7, 0.)
    widget._camera.distance = 3.2
    points = np.array([[-.4, 0., 0.], [.4, 0., 0.], [0., 1.4, 0.], [0., .6, .4]])
    faces = ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3))
    widget.set_meshes(PosedMesh(points, faces))
    try:
        yield widget
    finally:
        widget.close()


def render(view):
    image = QImage(view.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    view.render(image)
    return bytes(image.constBits())


def test_stationary_redraw_reuses_geometry_but_updates_attachments(view, monkeypatch):
    draws = []
    draw = view._draw_meshes
    monkeypatch.setattr(view, '_draw_meshes', lambda painter: (draws.append(1), draw(painter)))
    initial = render(view)
    assert render(view) == initial and len(draws) == 1
    view.set_attachments({'held': Vec3(0., .7, 0.)})
    assert render(view) != initial and len(draws) == 1
    view.set_attachments({})
    assert render(view) == initial and len(draws) == 1


def test_camera_style_resize_and_mesh_publication_invalidate_the_image(view, monkeypatch):
    draws = []
    draw = view._draw_meshes
    monkeypatch.setattr(view, '_draw_meshes', lambda painter: (draws.append(1), draw(painter)))
    render(view)
    for change in (lambda: setattr(view._camera, 'yaw', 75.),
                   lambda: view.set_solid(True),
                   lambda: view.resize(view.width() + 64, view.height() + 32),
                   lambda: view.set_meshes(view._body)):
        before = len(draws)
        change()
        render(view)
        assert len(draws) == before + 1
    shown = render(view)
    view.set_show_meshes(False)
    assert render(view) != shown
    view.set_show_meshes(True)
    assert render(view) == shown


def test_motion_draws_fresh_frames_and_restores_full_detail_picking(view):
    stationary = render(view)
    coordinates = tuple(np.array(values, copy=True) for values in view._body_screen)
    for flag in ('_moving', '_dragging_view'):
        setattr(view, flag, True)
        render(view)
        assert view._scene_background is None
        setattr(view, flag, False)
        assert render(view) == stationary
        for before, after in zip(coordinates, view._body_screen):
            np.testing.assert_array_equal(before, after)


def test_large_viewport_keeps_drawing_without_allocating_a_scene_image(view):
    view.resize(2200, 2200)
    target = QImage(4, 4, QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(target)
    try:
        view._draw_scene_background(painter)
    finally:
        painter.end()
    assert view._scene_background is None
