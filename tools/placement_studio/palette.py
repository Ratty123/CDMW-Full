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

# Roughly how many triangles a still frame should fill before detail starts being dropped.
#
# Was 6,000, chosen when the "body" was a 5,379-triangle coat. A real anatomy is 28,316 and a
# dressed one 38,944, so the rule that scales the minimum triangle size by `count / budget` was
# demanding 3.25 px per face — which at any distance is most of a head. Zooming out took the
# face off the character.
#
# Drawing all 38,944 costs 31.9 ms, once, and only while nothing moves. That is the frame the
# whole view exists for: it is where clipping is judged, so it is the one that has to be whole.
_TRIANGLE_BUDGET = 24000
# Shade levels for the solid body. A flat silhouette hides its own form, so triangles are drawn
# at different brightnesses. Quantised and cached because constructing a QColor per triangle
# would cost more than the shading is worth.
_SHADE_LEVELS = 10

# Where the key light sits *relative to the camera*: x right, y up, z towards the viewer. So
# it is over the viewer's left shoulder and above — the studio convention — and it travels with
# the camera the way a modelling viewport's does.
#
# Fixing it in world space instead was measured and rejected. Whichever direction is chosen,
# orbiting to the other side of the character puts the light behind everything on screen: a
# fixed light left 70% of the visible body clamped flat at the ambient floor, which is exactly
# the "I can't see any difference" case. A light that follows the eye guarantees that whatever
# is being looked at is lit, and lets surface angle do the modelling.
_LIGHT_DIR = (-0.40, 0.55, 0.73)
# What a surface turned fully out of the light keeps, so nothing falls to unreadable black.
# Pure Lambert leaves the shaded side of a cloak a silhouette.
_LIGHT_AMBIENT = 0.12

# Worn pieces are tinted apart from the body and from each other. These are deliberately close
# in value and unsaturated: the point is to tell a helmet from a hood from a collar, not to
# make the character look like a colour chart. Assigned by load order and reused per piece.
_PIECE_TINTS = (
    QColor(150, 154, 166),
    QColor(122, 132, 152),
    QColor(158, 146, 130),
    QColor(128, 146, 140),
    QColor(146, 132, 148),
    QColor(134, 140, 122),
    QColor(160, 152, 144),
    QColor(116, 138, 150),
)
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


#: Group boxes carry the only headings in the window — "Find and play a clip", "Action chart
#: contents". Qt draws a box title in the ordinary text colour at the ordinary weight, so it
#: reads as one more line of content sitting on a border rather than as the name of what is
#: below it. Bold and tinted, it says which pane you are looking at without being read.
GROUP_BOX_STYLE = """
QGroupBox {
    border: 1px solid #3a4152;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 9px;
    padding: 0 5px;
    color: #8fbcf0;
    font-weight: bold;
}
"""


#: A row whose animation was borrowed from the other playable character. Amber rather than red:
#: it is a caveat, not a fault — the clip plays, it was simply authored for a different body.
_BORROWED = QColor(224, 170, 96)
