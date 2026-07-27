"""Colours and gizmo geometry shared by the viewport and its rotation gizmo.

Split out so `gizmo.py` and `viewport.py` can both reach these without importing each other:
the viewport mixes the gizmo in, so a constant living in either one would close a cycle.
"""

from __future__ import annotations

from PySide6.QtGui import QColor

from .model import Vec3

_BONE_COLOR = QColor(120, 128, 140)
_BONE_COLOR_CARRYING = QColor(176, 186, 200)
_SOCKET_USED = QColor(96, 176, 240)
_SOCKET_UNUSED = QColor(110, 116, 124)
_SOCKET_SELECTED = QColor(255, 196, 64)
_ATTACH_STOWED = QColor(120, 220, 140)
_ATTACH_HELD = QColor(240, 128, 160)
_GRID = QColor(88, 95, 108)
# The two lines through the origin. Brighter than the grid so the centre of the stage is
# findable at a glance. There is no floor fill and there are no walls: anything that covers
# area has to be hidden where it would occlude the character, which makes what you see depend
# on where you are looking — and a stage that changes as you orbit reads as the world moving.
_STAGE_EDGE = QColor(126, 134, 150)
_TEXT = QColor(226, 230, 238)
_BACKGROUND = QColor(26, 28, 32)
_BODY_FILL = QColor(70, 76, 88, 150)
_BODY_SOLID = QColor(96, 103, 116)

# Roughly how many triangles a frame should fill before detail starts being dropped.
_TRIANGLE_BUDGET = 6000
# Shade levels for the solid body. A flat silhouette hides its own form, and depth is already
# computed for sorting, so nearer triangles are simply drawn brighter. Quantised and cached
# because constructing a QColor per triangle would cost more than the shading is worth.
_SHADE_LEVELS = 10
_WEAPON_FILL = QColor(198, 176, 120, 225)
_CLIP_FILL = QColor(226, 88, 88, 235)
# Conventional axis colours: X red, Y green, Z blue.
_AXIS_X = QColor(232, 106, 106)
_AXIS_Y = QColor(132, 216, 138)
_AXIS_Z = QColor(122, 162, 240)

# Each ring is named by the axis it rotates *about*; the pair is an orthonormal basis for the
# plane it lies in, shared by drawing, hit-testing and the angle measurement so they cannot
# disagree about which circle is which.
_RING_BASIS = {
    "X": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "Y": ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
    "Z": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
}
_RING_AXES = {"X": Vec3(1.0, 0.0, 0.0), "Y": Vec3(0.0, 1.0, 0.0), "Z": Vec3(0.0, 0.0, 1.0)}

# Below this |dot(view ray, plane normal)| the ring is edge-on and a ray/plane intersection is
# numerically useless, so a screen-space model takes over.
_EDGE_ON_LIMIT = 0.12
