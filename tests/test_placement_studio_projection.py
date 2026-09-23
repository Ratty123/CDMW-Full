"""Batched projection retains the same visible bone segments and near-plane rules."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication

from tools.placement_studio.meshes import Mesh
from tools.placement_studio.model import Vec3
from tools.placement_studio.skeleton import BoneHierarchy, BoneNode, IDENTITY_MATRIX
from tools.placement_studio.viewport import SkeletonViewport

_app = QApplication.instance() or QApplication([])


def test_vector_projection_matches_scalar_segments_including_clipped_and_short_bones():
    viewport = SkeletonViewport()
    viewport.resize(800, 600)
    _, _, forward, eye, *_ = viewport._view_frame()
    behind = tuple(a - b for a, b in zip((eye.x, eye.y, eye.z), (forward.x, forward.y, forward.z)))
    nodes = []
    for index, (point, parent) in enumerate([
        ((0, 0, 0), -1), ((1, 1, 0), 0), ((.5, 2, 0), 1),
        ((.5, 2, 0), 2), (behind, 1), ((1, 1, 1), 99),
    ]):
        matrix = list(IDENTITY_MATRIX)
        matrix[12:15] = point
        nodes.append(BoneNode(index, str(index), parent, tuple(matrix), Vec3(*point)))
    viewport._hierarchy = BoneHierarchy(nodes)
    viewport._carrying_bones = {'2'}
    expected = [QPainterPath(), QPainterPath()]
    for bone in nodes:
        if not 0 <= bone.parent_index < len(nodes):
            continue
        start = viewport._project(nodes[bone.parent_index].world_position)
        end = viewport._project(bone.world_position)
        if start is None or end is None:
            continue
        if abs(start.x() - end.x()) + abs(start.y() - end.y()) < 2:
            continue
        path = expected[int(bone.name in viewport._carrying_bones)]
        path.moveTo(start)
        path.lineTo(end)
    class Painter:
        paths = []
        def setBrush(self, *_): pass
        def setPen(self, *_): pass
        def drawPath(self, path): self.paths.append(QPainterPath(path))
    painter = Painter()
    viewport._draw_bones(painter)
    assert len(painter.paths) == 2
    for actual, wanted in zip(painter.paths, expected):
        assert actual.elementCount() == wanted.elementCount() == 2
        for index in range(wanted.elementCount()):
            a, b = actual.elementAt(index), wanted.elementAt(index)
            assert (a.x, a.y) == pytest.approx((b.x, b.y))
            assert a.type == b.type
    viewport.close()


def _draw_mesh(viewport):
    image = QImage(viewport.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing,
                              not (viewport._moving or viewport._dragging_view))
        viewport._draw_meshes(painter)
    finally:
        painter.end()
    return bytes(image.constBits())


def test_rigid_projection_reuses_lighting_coordinates_across_camera_moves():
    reads = []

    class Vertex:
        def __init__(self, point):
            self.point = point

        def coordinate(self, index):
            reads.append(index)
            return self.point[index]

        x = property(lambda self: self.coordinate(0))
        y = property(lambda self: self.coordinate(1))
        z = property(lambda self: self.coordinate(2))

    viewport = SkeletonViewport()
    points = ((-.4, .3, 0.), (.4, .3, 0.), (0., 1.5, .2))
    mesh = Mesh('rigid', tuple(Vertex(p) for p in points), ((0, 1, 2),))
    try:
        viewport.set_meshes(weapon=mesh)
        first = _draw_mesh(viewport)
        assert any(first)
        assert len(reads) == 3 * len(points)
        viewport._camera.yaw += 45.
        assert _draw_mesh(viewport) != first
        assert len(reads) == 3 * len(points)
    finally:
        viewport.close()


@pytest.mark.parametrize('mode', ('paused', 'playing', 'orbit'))
@pytest.mark.parametrize('slot', ('body', 'weapon'))
@pytest.mark.parametrize('solid', (False, True))
def test_rigid_and_posed_meshes_keep_identical_pixels_and_picking(mode, slot, solid):
    viewport = SkeletonViewport()
    viewport.resize(640, 480)
    viewport.set_solid(solid)
    viewport.set_moving(mode == 'playing')
    viewport._dragging_view = mode == 'orbit'
    points = np.array([[-.4, .2, 0.], [.4, .2, 0.], [0., 1.4, 0.], [0., .6, .4]])
    faces = ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3))
    vertices = tuple(Vec3(*p) for p in points.tolist())
    try:
        viewport.set_meshes(**{slot: Mesh('rigid', vertices, faces)}, clipping=(1,))
        rigid = _draw_mesh(viewport)
        assert any(rigid)
        screen = np.array(viewport._body_screen if slot == 'body' else viewport._weapon_screen)
        assert screen.size
        if slot == 'body':
            projected = viewport._project(vertices[0])
            assert viewport.pick_surface(QPoint(round(projected.x()), round(projected.y()))) == vertices[0]
        viewport.set_meshes(**{slot: SimpleNamespace(points=points, triangles=faces)}, clipping=(1,))
        assert _draw_mesh(viewport) == rigid
        np.testing.assert_allclose(
            viewport._body_screen if slot == 'body' else viewport._weapon_screen, screen,
            rtol=0, atol=1e-10,
        )
    finally:
        viewport.close()


def test_rigid_projection_preserves_scalar_near_plane_and_refreshes_replaced_vertices():
    viewport = SkeletonViewport()
    viewport.resize(800, 600)
    faces = ((0, 2, 1),)
    try:
        for yaw in (0., 85., 210.):
            viewport._camera.yaw = yaw
            _, _, forward, eye, *_ = viewport._view_frame()
            vertices = [Vec3(-.4, .2, 0.), Vec3(.4, .2, 0.), Vec3(0., 1.4, 0.)]
            for depth in (-1., .019, .021):
                vertices.append(Vec3(eye.x + forward.x * depth, eye.y + forward.y * depth,
                                     eye.z + forward.z * depth))
            mesh = Mesh('rigid', tuple(vertices), faces)
            viewport.set_meshes(body=mesh)
            _draw_mesh(viewport)
            sx, sy, depths = viewport._body_screen
            for index, vertex in enumerate(vertices):
                depth = ((vertex.x - eye.x) * forward.x + (vertex.y - eye.y) * forward.y
                         + (vertex.z - eye.z) * forward.z)
                assert depths[index] == pytest.approx(depth, abs=1e-12)
                point = viewport._project(vertex)
                expected = (0., 0.) if point is None else (point.x(), point.y())
                assert (sx[index], sy[index]) == pytest.approx(expected, abs=1e-10)
    finally:
        viewport.close()
