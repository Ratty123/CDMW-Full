"""Batched projection retains the same visible bone segments and near-plane rules."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication

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
