"""Qt-painted 3D viewport for the skeleton and its sockets.

Phase 2 needs sockets visible at correct positions, which a projected skeleton answers
directly. It deliberately does *not* drive the resident D3D11 preview yet: that helper is a
separate process, the embedded placement preview is documented as able to freeze the host, and
none of it is needed to verify socket geometry. The mesh render belongs in Phase 3, where
judging clipping actually requires it.

Everything here is read-only. Orbit with the left button, pan with the middle, wheel to zoom.
"""

from __future__ import annotations

import math
from operator import itemgetter as _itemgetter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as _np

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .gizmo import GizmoMixin
from .model import Vec3
from .palette import (
    _ATTACH_HELD,
    _ATTACH_STOWED,
    _BACKGROUND,
    _BODY_FILL,
    _BODY_SOLID,
    _BONE_COLOR,
    _BONE_COLOR_CARRYING,
    _CLIP_FILL,
    _LIGHT_AMBIENT,
    _LIGHT_DIR,
    _PIECE_TINTS,
    _GRID,
    _SHADE_LEVELS,
    _SOCKET_SELECTED,
    _SOCKET_UNUSED,
    _STAGE_EDGE,
    _SOCKET_USED,
    _TEXT,
    _TRIANGLE_BUDGET,
    _WEAPON_FILL,
)
from .skeleton import BoneHierarchy, PlacedSocket

def _key_light(right: Vec3, up: Vec3, forward: Vec3) -> "_np.ndarray":
    """The key light in world space, placed relative to the camera.

    `_LIGHT_DIR` is read in camera axes — right, up, and towards the viewer — so the light
    travels with the eye. Normalised here because the shading divides by the face normal's
    length alone; a light of any other length would scale every surface by the same wrong
    constant and wash the whole character out.
    """

    lx, ly, lz = _LIGHT_DIR
    light = _np.array((
        right.x * lx + up.x * ly - forward.x * lz,
        right.y * lx + up.y * ly - forward.y * lz,
        right.z * lx + up.z * ly - forward.z * lz,
    ), dtype=float)
    return light / (_np.linalg.norm(light) or 1.0)

#: Faces drawn per mesh while the playhead is running.
#:
#: 1,500 was measured against a 5,379-triangle coat, where it kept 94% of the filled area. The
#: same number against a 38,944-triangle character keeps 11%, and what is left is not a body —
#: it is a scatter of shards with the limbs missing.
#:
#: 4,000 holds ~77 fps on a fully dressed character in a bent-over pose, against 126 at 1,500.
#: 5,000 measured 62, which is too close to the floor to spend. The headroom came from the face
#: pass, which was reading numpy scalars one at a time and cost 4.2 us per triangle before it
#: was gathered into lists.
_MOVING_FACE_BUDGET = 4000




@dataclass(slots=True)
class Camera:
    """Orbit camera around a target point."""

    yaw: float = 30.0
    pitch: float = -12.0
    distance: float = 3.2
    target: Vec3 = field(default_factory=lambda: Vec3(0.0, 0.9, 0.0))
    fov: float = 45.0

    def clamp(self) -> None:
        self.pitch = max(-89.0, min(89.0, self.pitch))
        self.distance = max(0.35, min(14.0, self.distance))

    def basis(self) -> Tuple[Vec3, Vec3, Vec3]:
        """Camera right / up / forward unit vectors."""

        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        forward = Vec3(
            math.cos(pitch) * math.sin(yaw),
            math.sin(pitch),
            math.cos(pitch) * math.cos(yaw),
        )
        right = Vec3(math.cos(yaw), 0.0, -math.sin(yaw))
        up = Vec3(
            -math.sin(pitch) * math.sin(yaw),
            math.cos(pitch),
            -math.sin(pitch) * math.cos(yaw),
        )
        return right, up, forward

    def eye(self) -> Vec3:
        _right, _up, forward = self.basis()
        return Vec3(
            self.target.x - forward.x * self.distance,
            self.target.y - forward.y * self.distance,
            self.target.z - forward.z * self.distance,
        )


class SkeletonViewport(GizmoMixin, QWidget):
    """Projects bones and sockets, and reports clicks on socket markers."""

    socket_clicked = Signal(str)
    # World-space delta produced by dragging the selected socket, already snapped.
    socket_dragged = Signal(str, float, float, float)
    # World-space rotation axis plus a snapped angle in degrees.
    socket_rotated = Signal(str, float, float, float, float)
    # The weapon mesh was clicked, so the caller can select whatever positions it.
    weapon_clicked = Signal()
    # Tilt: a snapped roll in degrees. The axis is *not* sent — a roll must happen about the
    # item's own local long axis, and only the caller knows that; a world axis converted into
    # bone space rotates the item about the wrong thing and changes where the blade points.
    socket_rolled = Signal(str, float)
    # A point picked off the body surface: world x, y, z. Emitted in "pick" edit mode.
    surface_picked = Signal(float, float, float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 420)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._camera = Camera()
        self._hierarchy: Optional[BoneHierarchy] = None
        self._sockets: List[PlacedSocket] = []
        self._usage: Dict[str, int] = {}
        self._selected = ""
        self._hovered = ""
        self._attachments: Dict[str, Vec3] = {}
        self._carrying_bones: set[str] = set()
        self._show_bones = True
        self._show_labels = True
        self._show_unused = True
        self._screen: Dict[str, QPointF] = {}
        self._last_mouse: Optional[QPoint] = None
        self._drag_button = Qt.NoButton
        self._edit_mode = "off"   # off | move | rotate | tilt
        # Blade direction in world space, supplied by the caller: tilt rolls about the item's
        # own long axis, which no world X/Y/Z ring ever lines up with.
        self._blade_axis: Optional[Vec3] = None
        self._weapon_screen: List[Tuple[float, float, float, float, float, float]] = []
        # Projected body vertices from the last paint, parallel to `self._body.vertices`.
        # Picking reuses the paint's projection rather than re-deriving a ray: the surface
        # the user clicked is the surface they were looking at.
        self._body_screen: Optional[Tuple[List[float], List[float], List[float]]] = None
        self._snap = 0.020
        self._angle_snap = 5.0
        self._gizmo_anchor: Optional[Vec3] = None
        # Projected ring polylines, cached during paint so a press can hit-test them.
        self._rings: Dict[str, List[QPointF]] = {}
        self._ring_centre: Optional[QPointF] = None
        self._grabbed_axis = ""
        self._hovered_axis = ""
        self._angle_residual = 0.0
        self._grab_angle: Optional[float] = None
        self._solid = False
        # Camera frame cache. `_project` used to recompute the basis and eye for *every* point,
        # which meant ~36,600 basis() calls and 1.7M trig calls per frame at 12 FPS.
        self._frame_key: Optional[tuple] = None
        self._frame: Optional[tuple] = None

        self._drag_residual = Vec3()
        self._dragging_socket = ""
        self._body = None
        self._weapon = None
        self._clipping: set[int] = set()
        self._body_tris = None
        self._weapon_tris = None
        self._body_tris_src = None
        # World positions as arrays, for the surface lighting. A `Mesh` keeps its vertices as
        # Vec3 objects; rebuilding the array per frame costs more than the shading it feeds.
        # Keyed by the vertex tuple, which also keeps it alive, so the body and the weapon do
        # not evict each other every frame.
        self._points_cache: Dict[int, tuple] = {}
        self._show_meshes = True
        # Which rig the camera was last framed for; see `set_scene`.
        self._framed_source: Optional[str] = None
        self._ground_extent = self.GROUND_EXTENT
        # Camera tracking through travelling clips; see `set_scene`.
        self._follow = True
        self._follow_anchor: Optional[Vec3] = None
        self._dragging_view = False
        # Set while the playhead runs: heavy geometry thins out so the frame keeps up.
        self._moving = False

    # ── inputs ──────────────────────────────────────────────────────

    def set_scene(
        self,
        hierarchy: Optional[BoneHierarchy],
        sockets: Sequence[PlacedSocket],
        usage: Optional[Dict[str, int]] = None,
    ) -> None:
        self._hierarchy = hierarchy
        self._sockets = list(sockets)
        self._usage = dict(usage or {})
        self._carrying_bones = {
            placed.bone.name for placed in self._sockets if placed.bone is not None
        }
        # Frame the camera when the *rig* changes, not on every scene update: playback pushes
        # a new scene every frame, and re-framing there threw away the user's orbit and zoom
        # thirty times a second. Afterwards the camera only *tracks* — the target follows the
        # character's root by its delta, so a clip that travels ten metres stays in view while
        # any orbit, zoom or pan the user applied is preserved.
        source = hierarchy.source if hierarchy is not None else ""
        anchor = self._root_anchor(hierarchy)
        if hierarchy is not None and len(hierarchy) and source != self._framed_source:
            self._framed_source = source
            low, high = hierarchy.bounds()
            self._camera.target = Vec3((low.x + high.x) / 2, (low.y + high.y) / 2, (low.z + high.z) / 2)
            span = max(high.y - low.y, high.x - low.x, 0.6)
            self._camera.distance = span * 1.9
            self._camera.clamp()
        elif anchor is not None and self._follow_anchor is not None and self._follow:
            self._camera.target = Vec3(
                self._camera.target.x + (anchor.x - self._follow_anchor.x),
                self._camera.target.y + (anchor.y - self._follow_anchor.y),
                self._camera.target.z + (anchor.z - self._follow_anchor.z),
            )
        self._follow_anchor = anchor
        self.update()

    def set_moving(self, value: bool) -> None:
        """Whether the playhead is running.

        A body proxy is 5,379 triangles and every one of them becomes a QPolygonF. Holding
        full detail through playback costs more than it shows at 30 fps, so the budget
        tightens while moving and snaps back the moment you pause.
        """

        value = bool(value)
        if value != self._moving:
            self._moving = value
            self.update()

    def set_follow(self, value: bool) -> None:
        """Whether the camera tracks the character through a travelling clip."""

        self._follow = bool(value)

    @staticmethod
    def _root_anchor(hierarchy: Optional[BoneHierarchy]) -> Optional[Vec3]:
        """The character's root position — the thing worth tracking.

        Deliberately not the bounds centre: limbs swing it around by a hand's width every
        frame, which reads as the camera shaking.
        """

        if hierarchy is None or not len(hierarchy):
            return None
        for name in ("Bip01", "Bip01 Pelvis", "B_MoveControl_01"):
            bone = hierarchy.by_name(name)
            if bone is not None:
                return bone.world_position
        roots = hierarchy.roots()
        return roots[0].world_position if roots else None

    def set_selected(self, socket_name: str) -> None:
        self._selected = socket_name or ""
        self.update()

    def set_attachments(self, points: Dict[str, Vec3]) -> None:
        """Stowed/held attachment points for the selected equipment row."""

        self._attachments = {k: v for k, v in (points or {}).items() if v is not None}
        self.update()

    def set_show_bones(self, value: bool) -> None:
        self._show_bones = bool(value)
        self.update()

    def set_show_labels(self, value: bool) -> None:
        self._show_labels = bool(value)
        self.update()

    def set_show_unused(self, value: bool) -> None:
        self._show_unused = bool(value)
        self.update()

    def set_meshes(self, body=None, weapon=None, clipping: Sequence[int] = ()) -> None:
        """Body proxy and the placed weapon, plus the weapon vertices inside the body."""

        # Triangle indices as an array, built when the geometry changes rather than every
        # frame: the per-frame cost is the projection and the fill, not the topology.
        # Keyed on the triangle list itself, not on the mesh. A posed body is a fresh object
        # every frame while its topology is the same tuple throughout, so identity on the mesh
        # rebuilt a 5,379-row index array on every frame of playback for no change.
        body_tris_src = getattr(body, "triangles", None)
        if body_tris_src is not self._body_tris_src:
            self._body_tris_src = body_tris_src
            self._body_tris = (
                _np.asarray(body.triangles, dtype=_np.int32)
                if body is not None and len(getattr(body, "triangles", ())) else None
            )
        if weapon is not self._weapon:
            self._weapon_tris = (
                _np.asarray(weapon.triangles, dtype=_np.int32)
                if weapon is not None and len(getattr(weapon, "triangles", ())) else None
            )
        self._body = body
        self._weapon = weapon
        self._clipping = set(int(i) for i in clipping)
        self.update()

    def set_show_meshes(self, value: bool) -> None:
        self._show_meshes = bool(value)
        self.update()

    def set_solid(self, value: bool) -> None:
        """Opaque body instead of see-through. Backface culling is what makes it read solid."""

        self._solid = bool(value)
        self.update()

    def set_edit_mode(self, mode: str) -> None:
        """`off` orbits; `move` drags; `rotate` twists; `tilt` rolls; `route` re-points a row.

        `route` deliberately grabs nothing. It is a pure pick — a click names the socket the
        selected part should use — so no gesture can nudge geometry while the user is aiming.
        `pick` is the same idea for geometry: a click names a point on the body.
        """

        self._edit_mode = (
            mode if mode in ("off", "move", "rotate", "tilt", "route", "pick") else "off"
        )
        if self._edit_mode != "rotate":
            # Only rotate mode paints (and hit-tests) rings. Leaving them cached would let a
            # stale grab survive a mode change.
            self._rings = {}
            self._ring_centre = None
            self._grabbed_axis = ""
            self._hovered_axis = ""
        self.setCursor(
            {
                "move": Qt.SizeAllCursor,
                "rotate": Qt.CrossCursor,
                "tilt": Qt.SplitHCursor,
                "route": Qt.PointingHandCursor,
            }.get(self._edit_mode, Qt.ArrowCursor)
        )
        self.update()

    @property
    def edit_mode(self) -> str:
        return self._edit_mode

    def set_snap(self, step: float) -> None:
        self._snap = max(0.0, float(step))

    def set_angle_snap(self, degrees: float) -> None:
        self._angle_snap = max(0.0, float(degrees))

    def set_blade_axis(self, axis: Optional[Vec3]) -> None:
        """The item's long axis in world space, for tilt (roll along the blade)."""

        self._blade_axis = axis

    def set_gizmo_anchor(self, point: Optional[Vec3]) -> None:
        """Where to draw the rotation rings.

        A child socket has no world position of its own, so the caller supplies the composed
        attachment point instead — otherwise rotate mode shows no gizmo at all for exactly the
        sockets that control held orientation.
        """

        self._gizmo_anchor = point
        self.update()

    def reset_view(self) -> None:
        self._camera.yaw, self._camera.pitch = 30.0, -12.0
        # Framing is otherwise skipped for the rig already on screen, which is the whole
        # point of this button.
        self._framed_source = None
        self._follow_anchor = None
        self.set_scene(self._hierarchy, self._sockets, self._usage)

    # ── projection ──────────────────────────────────────────────────

    def _view_frame(self):
        """Camera basis, eye, and projection scale, recomputed only when the view changes."""

        key = (
            self._camera.yaw, self._camera.pitch, self._camera.distance,
            self._camera.target.x, self._camera.target.y, self._camera.target.z,
            self._camera.fov, self.width(), self.height(),
        )
        if key != self._frame_key:
            right, up, forward = self._camera.basis()
            eye = self._camera.eye()
            scale = (self.height() / 2.0) / math.tan(math.radians(self._camera.fov) / 2.0)
            self._frame = (right, up, forward, eye, scale,
                           self.width() / 2.0, self.height() / 2.0)
            self._frame_key = key
        return self._frame

    def _project(self, point: Vec3) -> Optional[QPointF]:
        right, up, forward, eye, scale, cx, cy = self._view_frame()
        rx = point.x - eye.x
        ry = point.y - eye.y
        rz = point.z - eye.z
        depth = rx * forward.x + ry * forward.y + rz * forward.z
        if depth <= 0.02:
            return None
        inv = scale / depth
        sx = (rx * right.x + ry * right.y + rz * right.z) * inv
        sy = (rx * up.x + ry * up.y + rz * up.z) * inv
        return QPointF(cx + sx, cy - sy)

    # ── painting ────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        painter = QPainter(self)
        # Antialiasing costs ~40% of the mesh draw. At 30 fps the stair-stepping is not
        # visible on a moving silhouette, and it comes straight back the moment you pause.
        painter.setRenderHint(
            QPainter.Antialiasing, not (self._moving or self._dragging_view)
        )
        painter.fillRect(self.rect(), _BACKGROUND)

        if self._hierarchy is None or not len(self._hierarchy):
            painter.setPen(QPen(_TEXT))
            painter.drawText(self.rect(), Qt.AlignCenter, "No skeleton loaded")
            return

        self._draw_ground(painter)
        if self._show_meshes:
            self._draw_meshes(painter)
        if self._show_bones:
            self._draw_bones(painter)
        self._draw_sockets(painter)
        if self._edit_mode == "rotate" and self._selected:
            self._draw_rotation_rings(painter)
        elif self._edit_mode == "tilt" and self._selected:
            self._draw_blade_axis(painter)
        self._draw_attachments(painter)
        self._draw_legend(painter)

    #: Half-width of the room, in metres. Fixed on purpose: a stage that resized itself per
    #: clip meant the floor squares changed size under the character and the walls jumped,
    #: which reads as the world moving rather than the character. Big enough for a ten metre
    #: run, and the camera tracks the character across it.
    GROUND_EXTENT = 9.0

    def set_ground_extent(self, extent: float) -> None:
        """Retained for callers; the room no longer resizes."""

        return

    #: How near the camera a point may be before it stops projecting. A segment crossing this
    #: plane is trimmed to it rather than discarded.
    _NEAR = 0.02

    def _project_segment(self, a: Vec3, b: Vec3):
        """Project a line, trimming it to the near plane instead of dropping it.

        `_project` returns nothing for a point behind the camera, so a naive draw discards any
        line with one endpoint behind — and a grid line runs the full width of the stage, so
        the moment the camera passes over it the whole line disappears at once. That is the
        grid "changing with the view": lines blinking out as they cross behind the eye, worst
        exactly when the camera is low or inside the grid.

        Trimming to the near plane keeps the visible part of every line on screen, so the grid
        stays the same grid from any position.
        """

        right, up, forward, eye, scale, cx, cy = self._view_frame()

        def depth_of(point: Vec3) -> float:
            return (
                (point.x - eye.x) * forward.x
                + (point.y - eye.y) * forward.y
                + (point.z - eye.z) * forward.z
            )

        da, db = depth_of(a), depth_of(b)
        if da <= self._NEAR and db <= self._NEAR:
            return None  # wholly behind the camera
        if da <= self._NEAR or db <= self._NEAR:
            # Slide the behind-camera end forward to where the line crosses the near plane.
            t = (self._NEAR - da) / (db - da)
            crossing = Vec3(
                a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, a.z + (b.z - a.z) * t
            )
            a, b = (crossing, b) if da <= self._NEAR else (a, crossing)

        out = []
        for point in (a, b):
            rx, ry, rz = point.x - eye.x, point.y - eye.y, point.z - eye.z
            inv = scale / max(rx * forward.x + ry * forward.y + rz * forward.z, self._NEAR)
            out.append(
                QPointF(
                    cx + (rx * right.x + ry * right.y + rz * right.z) * inv,
                    cy - (rx * up.x + ry * up.y + rz * up.z) * inv,
                )
            )
        return out[0], out[1]

    def _draw_ground(self, painter: QPainter) -> None:
        """A measured grid, and nothing else.

        No fill and no walls. Both were attempts to give the floor solidity, and both had the
        same defect: what they looked like depended on where the camera was, so the ground
        appeared to move while the character stood still. A wire grid is a fixed set of lines
        in the world — it can only change by perspective, which is the one change that reads
        as the camera moving rather than the scene.
        """

        extent = self.GROUND_EXTENT
        step = 1.0  # one metre squares, always
        ticks = int(extent / step)

        minor = QPen(_GRID, 1)
        major = QPen(_GRID.lighter(140), 1)
        origin = QPen(_STAGE_EDGE, 2)
        painter.setBrush(Qt.NoBrush)
        for i in range(-ticks, ticks + 1):
            offset = i * step
            # Every fifth line brighter, and the pair through the origin brighter still, so
            # the plane reads as a measured floor rather than wallpaper.
            painter.setPen(origin if i == 0 else (major if i % 5 == 0 else minor))
            for a, b in (
                (Vec3(-extent, 0.0, offset), Vec3(extent, 0.0, offset)),
                (Vec3(offset, 0.0, -extent), Vec3(offset, 0.0, extent)),
            ):
                segment = self._project_segment(a, b)
                if segment is not None:
                    painter.drawLine(segment[0], segment[1])

    def _world_points(self, mesh, points):
        """World positions as an (N, 3) array, whatever the mesh keeps them in.

        A posed body already hands over an array. A plain `Mesh` keeps Vec3 objects, and
        rebuilding the array from three thousand of them every frame would cost more than the
        lighting it feeds — so it is cached against the vertex tuple, which only changes when
        the geometry does.
        """

        if points is not None:
            return points
        vertices = getattr(mesh, "vertices", None)
        if not vertices:
            return None
        held = self._points_cache.get(id(vertices))
        if held is not None and held[0] is vertices:
            return held[1]
        array = _np.asarray([(v.x, v.y, v.z) for v in vertices], dtype=float)
        if len(self._points_cache) > 4:
            self._points_cache.clear()
        self._points_cache[id(vertices)] = (vertices, array)
        return array

    def _piece_tints(self, base: QColor, groups) -> list:
        """One colour per worn piece, with the body keeping the colour it already had.

        The tints carry the base colour's alpha so the see-through view stays see-through:
        picking a helmet must not quietly make the head opaque.
        """

        count = int(groups.max()) + 1 if len(groups) else 1
        key = (base.rgba(), count)
        if getattr(self, "_tint_key", None) == key:
            return self._tint_cache
        tints = [base]
        for index in range(1, count):
            tint = QColor(_PIECE_TINTS[(index - 1) % len(_PIECE_TINTS)])
            tint.setAlpha(base.alpha())
            tints.append(tint)
        self._tint_key = key
        self._tint_cache = tints
        return tints

    def _draw_meshes(self, painter: QPainter) -> None:
        """Body proxy then weapon, depth-sorted back to front.

        Vertices are projected *once per mesh*, not once per triangle that uses them: a body
        proxy has 3,038 vertices but 5,379 triangles, so the naive version did 3x the work.
        Back-facing triangles are dropped by screen winding, which halves the fill and is what
        makes an opaque body read as solid rather than as a wire ball.
        """

        rgt, upv, forward, eye, scale, cx, cy = self._view_frame()
        fx, fy, fz = forward.x, forward.y, forward.z
        ex, ey, ez = eye.x, eye.y, eye.z
        light = _key_light(rgt, upv, forward)

        faces: List[Tuple[float, QPolygonF, QColor]] = []
        for mesh, fill, cull in (
            (self._body, _BODY_SOLID if self._solid else _BODY_FILL, True),
            (self._weapon, _WEAPON_FILL, False),
        ):
            if mesh is None or not getattr(mesh, "triangles", ()):
                continue

            # Project inline into plain floats. Going through `_project` meant a `_view_frame`
            # call and a QPointF per vertex, then six QPointF accessor calls per triangle for
            # the winding test — about 400,000 Qt calls a frame on Damian. Qt objects are now
            # built only for triangles that survive.
            # A posed mesh hands over its vertices as an array. Building 3,000+ Vec3
            # objects a frame purely to read three floats off each was costing more than
            # the projection itself.
            points = getattr(mesh, "points", None)
            if points is not None:
                rel = points - _np.array((ex, ey, ez))
                depth_arr = rel @ _np.array((fx, fy, fz))
                inv = scale / _np.where(depth_arr > 0.02, depth_arr, 1.0)
                sx_arr = cx + (rel @ _np.array((rgt.x, rgt.y, rgt.z))) * inv
                sy_arr = cy - (rel @ _np.array((upv.x, upv.y, upv.z))) * inv
                behind = depth_arr <= 0.02
                sx_arr[behind] = 0.0
                sy_arr[behind] = 0.0
                sx = sx_arr.tolist()
                sy = sy_arr.tolist()
                depths = depth_arr.tolist()
            else:
                sx = []
                sy = []
                depths = []
                for vertex in mesh.vertices:
                    rx = vertex.x - ex
                    ry = vertex.y - ey
                    rz = vertex.z - ez
                    depth = rx * fx + ry * fy + rz * fz
                    depths.append(depth)
                    if depth <= 0.02:
                        sx.append(0.0)
                        sy.append(0.0)
                        continue
                    inv = scale / depth
                    sx.append(cx + (rx * rgt.x + ry * rgt.y + rz * rgt.z) * inv)
                    sy.append(cy - (rx * upv.x + ry * upv.y + rz * upv.z) * inv)

            clipping = self._clipping
            is_weapon = mesh is self._weapon
            if not is_weapon:
                self._body_screen = (sx, sy, depths)
            tri = self._weapon_tris if is_weapon else self._body_tris
            if is_weapon:
                self._weapon_screen = []
            count = len(mesh.triangles)
            budget = _TRIANGLE_BUDGET // 4 if self._moving else _TRIANGLE_BUDGET
            min_area = (
                0.5 if is_weapon or count <= budget
                else 0.5 * count / budget
            )
            if tri is None:
                continue
            # The per-triangle test used to be a Python loop over every face doing a dozen
            # index lookups each — about half the mesh draw. Selecting in NumPy leaves Qt
            # objects to be built only for the faces that actually survive.
            sxa = _np.asarray(sx)
            sya = _np.asarray(sy)
            dpa = _np.asarray(depths)
            i0, i1, i2 = tri[:, 0], tri[:, 1], tri[:, 2]
            da, db, dc = dpa[i0], dpa[i1], dpa[i2]
            ax, ay = sxa[i0], sya[i0]
            bx, by = sxa[i1], sya[i1]
            gx, gy = sxa[i2], sya[i2]
            area = (bx - ax) * (gy - ay) - (gx - ax) * (by - ay)
            keep = (da > 0.02) & (db > 0.02) & (dc > 0.02)
            keep &= (area >= min_area) if cull else (_np.abs(area) >= min_area)
            picked = _np.flatnonzero(keep)
            # While the playhead runs, keep only the largest faces. On the body the visible
            # 2,656 triangles carry 94% of their filled area in the largest 1,500, and the
            # ones dropped are the dense clusters around fingers and seams where neighbours
            # already overlap. Everything comes back the moment playback stops.
            if (self._moving or self._dragging_view) and len(picked) > _MOVING_FACE_BUDGET:
                sizes = _np.abs(area[picked])
                picked = picked[
                    _np.argpartition(sizes, len(picked) - _MOVING_FACE_BUDGET)[
                        -_MOVING_FACE_BUDGET:
                    ]
                ]
            mid = (da + db + dc) / 3.0

            # Light every surviving face by the direction it *faces*, not by how near it is.
            # Depth shading brightens the near edge of an arm and the near edge of the chest
            # identically, so the two merge into one flat patch; surface lighting separates
            # them and is what makes a limb read as round. The normal is taken from the world
            # positions, so nothing has to be carried through skinning — and it is turned
            # towards the eye, which makes it independent of winding. That matters because the
            # body is back-face culled and the weapon deliberately is not.
            world = self._world_points(mesh, points)
            levels: Optional[list] = None
            if world is not None and len(picked):
                corner = world[i0[picked]]
                normals = _np.cross(
                    world[i1[picked]] - corner, world[i2[picked]] - corner
                )
                towards = _np.array((ex, ey, ez), dtype=float) - corner
                normals[_np.einsum("ij,ij->i", normals, towards) < 0.0] *= -1.0
                length = _np.linalg.norm(normals, axis=1)
                length[length == 0.0] = 1.0
                lit = _np.clip((normals @ light) / length, 0.0, 1.0)
                shade = _LIGHT_AMBIENT + (1.0 - _LIGHT_AMBIENT) * lit
                levels = _np.clip(
                    (shade * (_SHADE_LEVELS - 1)).astype(_np.int32), 0, _SHADE_LEVELS - 1
                ).tolist()

            # Worn pieces arrive as separate meshes and are merged for drawing; `groups` is the
            # only surviving record of where one ends, and it is what lets a helmet be told
            # from the head under it.
            groups = None if is_weapon else getattr(mesh, "groups", None)
            tints = None if groups is None else self._piece_tints(fill, groups)
            piece = None if groups is None else groups[picked].tolist()

            # Gather every per-face column into plain Python lists in one vectorised step.
            # Reading them as `ax[index]` inside the loop meant eight *numpy scalar* lookups
            # per triangle, and a numpy scalar costs some 30x what a list element does: the
            # whole face pass ran at 4.2 us per triangle, which is what made drawing a real
            # body unaffordable and forced the thinning that left it full of holes.
            ax_l, ay_l = ax[picked].tolist(), ay[picked].tolist()
            bx_l, by_l = bx[picked].tolist(), by[picked].tolist()
            gx_l, gy_l = gx[picked].tolist(), gy[picked].tolist()
            mid_l = mid[picked].tolist()
            area_l = None if cull else area[picked].tolist()
            corners = None
            if is_weapon and clipping:
                corners = _np.stack((i0[picked], i1[picked], i2[picked]), axis=1).tolist()

            for order in range(len(mid_l)):
                colour = fill if tints is None else tints[piece[order]]
                if corners is not None:
                    if not clipping.isdisjoint(corners[order]):
                        colour = _CLIP_FILL
                level = (_SHADE_LEVELS - 1) if levels is None else levels[order]
                pax, pay = ax_l[order], ay_l[order]
                pbx, pby = bx_l[order], by_l[order]
                pgx, pgy = gx_l[order], gy_l[order]
                if area_l is not None and area_l[order] < 0.0:
                    # Emit every triangle wound the same way round. A filled triangle looks
                    # identical either way, but a winding fill *cancels* where two opposed
                    # triangles overlap and punches a hole through the weapon — which is why
                    # un-culled meshes used to be drawn one path at a time. Normalising here
                    # is what lets them share a path with everything else.
                    pbx, pby, pgx, pgy = pgx, pgy, pbx, pby
                if is_weapon:
                    self._weapon_screen.append((pax, pay, pbx, pby, pgx, pgy))
                # Plain floats, not a QPolygonF. Constructing one polygon and three QPointF
                # per triangle measured 3.05 ms against 1.18 ms for writing the same
                # coordinates straight into a reused path — 2.6x the cost of the fill it
                # feeds. The path is built once per shade run below.
                faces.append((mid_l[order], pax, pay, pbx, pby, pgx, pgy, colour, level))

        # `itemgetter` sorts in C; a `lambda item: -item[0]` calls back into Python once per
        # triangle, which at these counts is a measurable slice of the frame on its own.
        faces.sort(key=_itemgetter(0), reverse=True)
        if not faces:
            return

        shades: Dict[tuple, QColor] = {}
        pens: Dict[int, QPen] = {}

        def brush_for(colour: QColor, level: int) -> QColor:
            key = (colour.rgba(), level)
            brush = shades.get(key)
            if brush is None:
                # 60 = a little over half the base lightness, 168 = two thirds brighter. The
                # old span was 68..150, which was enough for depth fog but too narrow to model
                # a shape: the difference between a shoulder and the chest under it landed
                # inside one step and read as flat.
                factor = 60 + int(level * (168 - 60) / max(1, _SHADE_LEVELS - 1))
                brush = QColor(colour).lighter(factor)
                brush.setAlpha(colour.alpha())
                shades[key] = brush
            return brush

        # The outline exists only to hide an antialiasing artefact: with NoPen, AA leaves a
        # sub-pixel gap along every shared edge and the background bleeds through as a
        # stipple. Antialiasing is already off while anything moves, so there is nothing to
        # hide then — and stroking every triangle edge costs 0.62 ms of the 1.48 ms paint.
        outline = not (self._moving or self._dragging_view)

        def flush(path: Optional[QPainterPath], brush: Optional[QColor]) -> None:
            if path is None or brush is None:
                return
            if outline:
                painter.setBrush(brush)
                painter.setPen(pens.setdefault(brush.rgba(), QPen(brush, 1.0)))
                painter.drawPath(path)
            else:
                painter.fillPath(path, brush)

        # Batch same-shade triangles into one path per slab of depth-sorted faces.
        #
        # Batching used to key on *runs* of adjacent faces, which worked only because the shade
        # came from depth: neighbours in a depth-sorted list share a depth, so the runs were
        # thousands long. Lighting by surface direction breaks that — two faces at the same
        # depth can face opposite ways — and the naive version measured 1,977 paths a frame
        # against a few dozen, for 17 ms.
        #
        # So faces are collected into one path per shade *within a slab*, and the slab is
        # flushed before the next begins. Ordering between shades inside a slab is lost, but a
        # slab is a sixteenth of the depth range — a few centimetres on a character — and the
        # faces there are almost never the ones that occlude each other. Ordering *between*
        # slabs, which is what makes an arm sit in front of a chest, is kept exactly.
        # A fixed 128 faces per slab, not a fraction of the frame, because the artefact this
        # controls scales with geometry rather than with the picture. Clothing sits directly on
        # skin, so a coat and the chest under it are near enough coplanar that a mean-depth sort
        # flips between them — and the body speckles through the coat. Those speckles look
        # exactly like the weapon clipping this view exists to judge, which makes them worth
        # paying for: 128 costs 7.6 ms more on an idle repaint than slabs of 2,400 did, and
        # removes them. Nothing is paid while anything moves, where the face budget caps the
        # list at 1,500 and a slab is a twelfth of it.
        slab = 128
        buckets: Dict[tuple, QPainterPath] = {}
        brushes: Dict[tuple, QColor] = {}
        pending = 0

        for depth, pax, pay, pbx, pby, pgx, pgy, colour, level in faces:
            # 0 = turned away from the light, _SHADE_LEVELS-1 = facing it square on.
            key = (colour.rgba(), level)
            path = buckets.get(key)
            if path is None:
                path = QPainterPath()
                path.setFillRule(Qt.WindingFill)
                buckets[key] = path
                brushes[key] = brush_for(colour, level)
            path.moveTo(pax, pay)
            path.lineTo(pbx, pby)
            path.lineTo(pgx, pgy)
            path.closeSubpath()
            pending += 1
            if pending >= slab:
                for done, built in buckets.items():
                    flush(built, brushes[done])
                buckets.clear()
                pending = 0
        for done, built in buckets.items():
            flush(built, brushes[done])

    def _draw_bones(self, painter: QPainter) -> None:
        """Every bone segment, batched by colour into two paths.

        434 separate `drawLine` calls with a pen change between them cost ~2 ms a frame; the
        segments only ever take one of two colours, so two paths cover them.
        """

        if self._hierarchy is None:
            return
        plain = QPainterPath()
        carrying = QPainterPath()
        for bone in self._hierarchy:
            if bone.parent_index < 0 or bone.parent_index >= len(self._hierarchy):
                continue
            parent = self._hierarchy.bones[bone.parent_index]
            start = self._project(parent.world_position)
            end = self._project(bone.world_position)
            if start is None or end is None:
                continue
            if abs(end.x() - start.x()) + abs(end.y() - start.y()) < 2.0:
                continue  # shorter than a couple of pixels: nothing to see, and there are
                          # hundreds of them clustered in the hands and face
            target = carrying if bone.name in self._carrying_bones else plain
            target.moveTo(start)
            target.lineTo(end)
        painter.setBrush(Qt.NoBrush)
        for path, colour in ((plain, _BONE_COLOR), (carrying, _BONE_COLOR_CARRYING)):
            if not path.isEmpty():
                painter.setPen(QPen(colour, 1))
                painter.drawPath(path)

    def _draw_bones_unbatched(self, painter: QPainter) -> None:
        for bone in self._hierarchy:
            if bone.parent_index < 0 or bone.parent_index >= len(self._hierarchy):
                continue
            parent = self._hierarchy.bones[bone.parent_index]
            start, end = self._project(parent.world_position), self._project(bone.world_position)
            if start is None or end is None:
                continue
            carrying = bone.name in self._carrying_bones or parent.name in self._carrying_bones
            painter.setPen(QPen(_BONE_COLOR_CARRYING if carrying else _BONE_COLOR, 2 if carrying else 1))
            painter.drawLine(start, end)

    def _draw_sockets(self, painter: QPainter) -> None:
        self._screen = {}
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.0))
        painter.setFont(font)
        metrics = painter.fontMetrics()

        # Sockets cluster tightly at the hips, hands and upper back, where unmanaged labels
        # overprint into an unreadable smear. Claim a rect per label and skip any that
        # collides; the selected and hovered labels are drawn first so they always win.
        claimed: List[QRectF] = []

        def claim(anchor: QPointF, text: str) -> Optional[QPointF]:
            width = metrics.horizontalAdvance(text)
            height = metrics.height()
            rect = QRectF(anchor.x(), anchor.y() - height + 3, width, height)
            for taken in claimed:
                if rect.intersects(taken):
                    return None
            claimed.append(rect)
            return anchor

        # Selected socket paints last so its marker is never hidden behind a neighbour.
        ordered = sorted(self._sockets, key=lambda p: p.name == self._selected)
        for placed in ordered:
            used = self._usage.get(placed.name, 0) > 0
            if not used and not self._show_unused and placed.name != self._selected:
                continue
            position = self._project(placed.world_position)
            if position is None:
                continue
            self._screen[placed.name] = position

            selected = placed.name == self._selected
            hovered = placed.name == self._hovered
            color = _SOCKET_SELECTED if selected else (_SOCKET_USED if used else _SOCKET_UNUSED)
            radius = 6.0 if selected else (4.0 if used else 3.0)

            painter.setPen(QPen(color.darker(160), 1))
            painter.setBrush(color)
            painter.drawEllipse(position, radius, radius)

            if selected:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(_SOCKET_SELECTED, 1, Qt.DashLine))
                painter.drawEllipse(position, radius + 5, radius + 5)
                if placed.bone is not None:
                    origin = self._project(placed.bone.world_position)
                    if origin is not None:
                        painter.setPen(QPen(_SOCKET_SELECTED.darker(130), 1, Qt.DotLine))
                        painter.drawLine(origin, position)

            if self._show_labels and (selected or hovered or used):
                anchor = position + QPointF(radius + 3, radius - 1)
                if selected or hovered:
                    # Always readable: reserve the space and let neighbours yield.
                    claim(anchor, placed.name)
                    placed_anchor = anchor
                else:
                    placed_anchor = claim(anchor, placed.name)
                if placed_anchor is not None:
                    painter.setPen(QPen(_TEXT if selected else color.lighter(130)))
                    painter.drawText(placed_anchor, placed.name)

    def _draw_attachments(self, painter: QPainter) -> None:
        for role, point in self._attachments.items():
            position = self._project(point)
            if position is None:
                continue
            color = _ATTACH_STOWED if role == "stowed" else _ATTACH_HELD
            painter.setPen(QPen(color, 2))
            painter.setBrush(Qt.NoBrush)
            size = 7.0
            painter.drawLine(position + QPointF(-size, -size), position + QPointF(size, size))
            painter.drawLine(position + QPointF(-size, size), position + QPointF(size, -size))
            painter.drawText(position + QPointF(size + 2, -size), role)

    def _draw_legend(self, painter: QPainter) -> None:
        rows = [
            (_SOCKET_USED, "socket in use"),
            (_SOCKET_UNUSED, "socket unused"),
            (_SOCKET_SELECTED, "selected"),
            (_ATTACH_STOWED, "stowed attach"),
            (_ATTACH_HELD, "held attach"),
            (_WEAPON_FILL, "weapon mesh"),
            (_CLIP_FILL, "inside the body"),
        ]
        painter.setPen(QPen(_TEXT))
        y = 18
        for color, label in rows:
            painter.setBrush(color)
            painter.setPen(QPen(color.darker(150), 1))
            painter.drawEllipse(QPointF(14, y - 4), 4, 4)
            painter.setPen(QPen(_TEXT))
            painter.drawText(QPointF(26, y), label)
            y += 15
        if self._edit_mode != "off":
            snap = (
                f"snap {self._snap:.3f}"
                if self._edit_mode == "move"
                else f"snap {self._angle_snap:.0f}°"
            )
            if self._edit_mode == "tilt" and self._blade_axis is None:
                snap += "   [no item axis - select a weapon]"
            painter.setPen(QPen(_SOCKET_SELECTED))
            painter.drawText(
                QPointF(14, self.height() - 26),
                f"{self._edit_mode.upper()} MODE — drag edits "
                f"{self._selected or '(select a socket)'}   {snap}"
                + (f"   [{self._grabbed_axis or self._hovered_axis} axis]"
                   if (self._grabbed_axis or self._hovered_axis) else ""),
            )
        painter.setPen(QPen(_TEXT))
        painter.drawText(
            QPointF(14, self.height() - 10),
            ("middle-drag: pan   wheel: zoom   " if self._edit_mode != "off"
             else "drag: orbit   middle-drag: pan   wheel: zoom   ")
            + f"yaw {self._camera.yaw:.0f}  pitch {self._camera.pitch:.0f}",
        )

    # ── interaction ─────────────────────────────────────────────────

    def _socket_at(self, position: QPoint) -> str:
        best, best_distance = "", 12.0
        for name, point in self._screen.items():
            distance = math.dist((position.x(), position.y()), (point.x(), point.y()))
            if distance < best_distance:
                best, best_distance = name, distance
        return best

    def pick_surface(self, position: QPoint) -> Optional[Vec3]:
        """The body vertex nearest the click, in world space.

        Snapping to a vertex rather than solving a ray/triangle intersection keeps the
        result on geometry that exists, which is what a socket wants to hang off. It also
        costs nothing: the projection was already computed to draw the frame.
        """

        if self._body is None or self._body_screen is None:
            return None
        sx, sy, depths = self._body_screen
        points = getattr(self._body, "points", None)
        vertices = self._body.vertices
        count = len(points) if points is not None else len(vertices)
        if count == 0 or len(sx) < count:
            return None
        px, py = float(position.x()), float(position.y())
        best = None
        best_d2 = 26.0 ** 2  # a generous grab radius in pixels
        for index in range(count):
            if depths[index] <= 0.02:
                continue
            dx = sx[index] - px
            dy = sy[index] - py
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best_d2 = d2
                best = index
        if best is None:
            return None
        if points is not None:
            x, y, z = points[best]
            return Vec3(float(x), float(y), float(z))
        return vertices[best]

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        if self._edit_mode == "pick" and event.button() == Qt.LeftButton:
            point = self.pick_surface(event.position().toPoint())
            if point is not None:
                self.surface_picked.emit(point.x, point.y, point.z)
                event.accept()
                return
        return self._mouse_press_default(event)

    def _mouse_press_default(self, event) -> None:
        self._dragging_view = True
        self._last_mouse = event.position().toPoint()
        self._drag_button = event.button()
        self._drag_residual = Vec3()
        self._dragging_socket = ""
        if event.button() != Qt.LeftButton:
            return

        if self._edit_mode == "rotate" and self._selected:
            # A ring under the cursor constrains the twist to that axis; anywhere else
            # falls back to free trackball, so the gizmo never blocks a coarse adjustment.
            self._grabbed_axis = self._ring_at(self._last_mouse)
            self._angle_residual = 0.0
            self._grab_angle = None

        # Marker picking belongs to the *selection* modes only. In an edit mode it stole the
        # gesture: every child socket projects to the same attachment point, so there are always
        # other markers under the gizmo centre, and a twist meant for `Basic_ChildSocket` landed
        # on `Gimmick_Sub_Socket_01` instead. It applied cleanly to a socket that positions
        # nothing, so the weapon did not move and the mode looked dead.
        picked = ""
        if self._edit_mode in ("off", "route"):
            picked = self._socket_at(self._last_mouse)
            if picked:
                self.socket_clicked.emit(picked)

        if (
            not picked
            and not self._grabbed_axis
            and self._edit_mode != "route"
            and self._weapon_at(self._last_mouse)
        ):
            # Clicking the item is the fastest way to reach what positions it, and it works in
            # the edit modes too — the handler re-selects synchronously, so the drag started
            # below already targets the newly selected socket. Not in route mode, where a click
            # has to mean "use this socket" and nothing else.
            self.weapon_clicked.emit()

        if self._edit_mode in ("move", "rotate", "tilt") and self._selected:
            # Grabbing anywhere drags the selected socket: at these marker sizes, requiring a
            # pixel-perfect hit on the dot makes the gizmo unusable.
            self._dragging_socket = self._selected

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        current = event.position().toPoint()
        if self._last_mouse is None or self._drag_button == Qt.NoButton:
            hovered = self._socket_at(current)
            ring = self._ring_at(current) if self._edit_mode == "rotate" else ""
            if hovered != self._hovered or ring != self._hovered_axis:
                self._hovered = hovered
                self._hovered_axis = ring
                self.setCursor(Qt.OpenHandCursor if ring else Qt.CrossCursor
                               if self._edit_mode == "rotate" else Qt.ArrowCursor)
                self.update()
            self._last_mouse = current
            return

        dx = current.x() - self._last_mouse.x()
        dy = current.y() - self._last_mouse.y()
        if self._drag_button == Qt.LeftButton and self._dragging_socket:
            if self._edit_mode == "tilt":
                self._tilt_socket(dx, dy)
            elif self._edit_mode == "rotate" and self._grabbed_axis:
                self._rotate_about_axis(self._last_mouse, current)
            elif self._edit_mode == "rotate":
                self._rotate_socket(dx, dy)
            else:
                self._drag_socket(dx, dy)
        elif self._drag_button == Qt.LeftButton:
            self._camera.yaw -= dx * 0.4
            self._camera.pitch -= dy * 0.4
        elif self._drag_button == Qt.MiddleButton:
            right, up, _forward = self._camera.basis()
            scale = self._camera.distance * 0.0022
            self._camera.target = Vec3(
                self._camera.target.x - (right.x * dx - up.x * dy) * scale,
                self._camera.target.y - (right.y * dx - up.y * dy) * scale,
                self._camera.target.z - (right.z * dx - up.z * dy) * scale,
            )
        self._camera.clamp()
        self._last_mouse = current
        self.update()

    def _drag_socket(self, dx: float, dy: float) -> None:
        """Turn screen movement into a snapped world-space delta along the camera plane.

        Sub-step movement accumulates in a residual rather than being discarded, so a slow
        drag still advances one step at a time instead of feeling dead.
        """

        right, up, _forward = self._camera.basis()
        scale = self._camera.distance * 0.0016
        move = Vec3(
            self._drag_residual.x + (right.x * dx - up.x * dy) * scale,
            self._drag_residual.y + (right.y * dx - up.y * dy) * scale,
            self._drag_residual.z + (right.z * dx - up.z * dy) * scale,
        )
        if self._snap <= 0.0:
            self._drag_residual = Vec3()
            self.socket_dragged.emit(self._dragging_socket, move.x, move.y, move.z)
            return

        steps = [round(value / self._snap) * self._snap for value in (move.x, move.y, move.z)]
        self._drag_residual = Vec3(move.x - steps[0], move.y - steps[1], move.z - steps[2])
        if any(abs(value) > 1e-9 for value in steps):
            self.socket_dragged.emit(self._dragging_socket, steps[0], steps[1], steps[2])

    def _rotate_socket(self, dx: float, dy: float) -> None:
        """Trackball twist: horizontal drag spins about camera up, vertical about camera right.

        The axis is emitted in *world* space; converting it into the socket's own space is the
        caller's job, because only the session knows which bone a socket hangs off.
        """

        right, up, _forward = self._camera.basis()
        # Screen-space drag distance maps to degrees; sign chosen so the surface follows the
        # cursor rather than moving against it.
        yaw = -dx * 0.5
        pitch = -dy * 0.5

        for axis, degrees in ((up, yaw), (right, pitch)):
            if abs(degrees) < 1e-9:
                continue
            step = self._angle_snap
            if step > 0.0:
                snapped = round(degrees / step) * step
                if abs(snapped) < 1e-9:
                    continue
                degrees = snapped
            self.socket_rotated.emit(self._dragging_socket, axis.x, axis.y, axis.z, degrees)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        # Full detail comes back as soon as the drag ends.
        self._dragging_view = False
        self.update()
        self._drag_button = Qt.NoButton
        self._dragging_socket = ""
        self._drag_residual = Vec3()
        self._grabbed_axis = ""
        self._angle_residual = 0.0
        self._grab_angle = None

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        self._camera.distance *= 0.88 if event.angleDelta().y() > 0 else 1.14
        self._camera.clamp()
        self.update()
