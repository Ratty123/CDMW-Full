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

#: Faces drawn per mesh while the playhead is running. Chosen from the area
#: distribution rather than guessed: it is the knee of the coverage curve.
_MOVING_FACE_BUDGET = 1500




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
        if body is not self._body:
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
            for index in picked.tolist():
                colour = fill
                if is_weapon and clipping:
                    if (int(i0[index]) in clipping or int(i1[index]) in clipping
                            or int(i2[index]) in clipping):
                        colour = _CLIP_FILL
                pax, pay = ax[index], ay[index]
                pbx, pby = bx[index], by[index]
                pgx, pgy = gx[index], gy[index]
                if is_weapon:
                    self._weapon_screen.append((pax, pay, pbx, pby, pgx, pgy))
                # Plain floats, not a QPolygonF. Constructing one polygon and three QPointF
                # per triangle measured 3.05 ms against 1.18 ms for writing the same
                # coordinates straight into a reused path — 2.6x the cost of the fill it
                # feeds. The path is built once per shade run below.
                faces.append((mid[index], pax, pay, pbx, pby, pgx, pgy, colour, cull))

        faces.sort(key=lambda item: -item[0])
        if not faces:
            return

        near = faces[-1][0]
        far = faces[0][0]
        spread = (far - near) or 1.0
        shades: Dict[tuple, QColor] = {}
        pens: Dict[int, QPen] = {}

        def brush_for(colour: QColor, level: int) -> QColor:
            key = (colour.rgba(), level)
            brush = shades.get(key)
            if brush is None:
                factor = 68 + int(level * (150 - 68) / max(1, _SHADE_LEVELS - 1))
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

        # Batch runs of same-shade triangles into one path. Depth-sorted order means the
        # shade level barely changes from one triangle to the next, so the runs are long:
        # a dressed character drops from ~48,000 Qt calls a frame to a few dozen. Only
        # back-face-culled meshes are batched — mixed winding under a winding fill would
        # cancel where two triangles overlap and punch holes through the weapon.
        run_path: Optional[QPainterPath] = None
        run_brush: Optional[QColor] = None
        run_key: Optional[tuple] = None
        for depth, pax, pay, pbx, pby, pgx, pgy, colour, batchable in faces:
            # 0 = farthest, _SHADE_LEVELS-1 = nearest.
            level = int((far - depth) / spread * (_SHADE_LEVELS - 1))
            brush = brush_for(colour, level)
            if not batchable:
                flush(run_path, run_brush)
                run_path, run_brush, run_key = None, None, None
                lone = QPainterPath()
                lone.moveTo(pax, pay)
                lone.lineTo(pbx, pby)
                lone.lineTo(pgx, pgy)
                lone.closeSubpath()
                flush(lone, brush)
                continue
            key = (colour.rgba(), level)
            if key != run_key:
                flush(run_path, run_brush)
                run_path = QPainterPath()
                run_path.setFillRule(Qt.WindingFill)
                run_brush, run_key = brush, key
            run_path.moveTo(pax, pay)
            run_path.lineTo(pbx, pby)
            run_path.lineTo(pgx, pgy)
            run_path.closeSubpath()
        flush(run_path, run_brush)

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
