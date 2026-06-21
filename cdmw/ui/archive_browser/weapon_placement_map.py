from __future__ import annotations

import math
from pathlib import PurePosixPath
from typing import Dict, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QFrame, QWidget

from cdmw.core.weapon_swap_templates import WeaponSwapSocketRow, weapon_swap_template_socket_rows


class WeaponPlacementStudioPlacementMap(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(500, 340))
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._template_id = ""
        self._rows: Tuple[WeaponSwapSocketRow, ...] = ()
        self._baseline_rows: Tuple[WeaponSwapSocketRow, ...] = ()
        self._weapon_paths: Tuple[str, ...] = ()
        self._body_path = ""
        self._native_note = ""
        self._show_shield = False
        self._view_mode = "back"

    def set_view_mode(self, view_mode: object) -> None:
        normalized = str(view_mode or "back").strip().casefold()
        self._view_mode = normalized if normalized in {"back", "side", "top"} else "back"
        self.update()

    def set_preview_state(
        self,
        *,
        template_id: str,
        rows: Sequence[WeaponSwapSocketRow],
        baseline_rows: Sequence[WeaponSwapSocketRow] = (),
        weapon_paths: Sequence[str] = (),
        body_path: str = "",
        native_note: str = "",
        show_shield: bool,
    ) -> None:
        self._template_id = str(template_id or "")
        self._rows = tuple(row for row in rows if isinstance(row, WeaponSwapSocketRow))
        self._baseline_rows = tuple(row for row in baseline_rows if isinstance(row, WeaponSwapSocketRow))
        self._weapon_paths = tuple(str(path or "") for path in tuple(weapon_paths or ()) if str(path or "").strip())
        self._body_path = str(body_path or "").strip()
        self._native_note = str(native_note or "").strip()
        self._show_shield = bool(show_shield)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = self.rect().adjusted(10, 10, -10, -10)
            background = QLinearGradient(rect.topLeft(), rect.bottomRight())
            background.setColorAt(0.0, QColor("#0f172a"))
            background.setColorAt(1.0, QColor("#101820"))
            painter.fillRect(rect, background)

            canvas = QRectF(rect.left() + 10, rect.top() + 10, rect.width() - 20, max(190, int(rect.height() * 0.66)))
            readout = QRectF(rect.left() + 10, canvas.bottom() + 10, rect.width() - 20, rect.bottom() - canvas.bottom() - 18)

            def point(x: float, y: float) -> QPointF:
                return QPointF(
                    canvas.left() + (max(0.0, min(1.0, float(x))) * canvas.width()),
                    canvas.top() + (max(0.0, min(1.0, float(y))) * canvas.height()),
                )

            def soft_pen(color: str, width: int = 1, style: Qt.PenStyle = Qt.PenStyle.SolidLine) -> QPen:
                pen = QPen(QColor(color), width, style)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                return pen

            painter.setPen(soft_pen("#203040", 1))
            for index in range(1, 6):
                y = canvas.top() + (canvas.height() * index / 6.0)
                painter.drawLine(QPointF(canvas.left(), y), QPointF(canvas.right(), y))
            for index in range(1, 4):
                x = canvas.left() + (canvas.width() * index / 4.0)
                painter.drawLine(QPointF(x, canvas.top()), QPointF(x, canvas.bottom()))

            def text_rect(x: float, y: float, w: float, h: float) -> QRectF:
                return QRectF(
                    rect.left() + (rect.width() * x),
                    rect.top() + (rect.height() * y),
                    rect.width() * w,
                    rect.height() * h,
                )

            def draw_label(text: str, pos: QPointF, color: str = "#cbd5e1", *, bold: bool = False) -> None:
                font = painter.font()
                font.setBold(bool(bold))
                painter.setFont(font)
                painter.setPen(soft_pen(color, 1))
                painter.drawText(pos, str(text or ""))
                font.setBold(False)
                painter.setFont(font)

            skeleton_bone = QColor("#d8e0ea")
            skeleton_joint = QColor("#f8fafc")
            skeleton_shadow = QColor("#0b1220")
            skeleton_guide = QColor(148, 163, 184, 74)
            socket_color = QColor("#35d48b")
            planned_color = QColor("#35d48b")
            baseline_color = QColor("#6ea8ff")

            def draw_bone(start: QPointF, end: QPointF, width: int = 3, color: QColor = skeleton_bone) -> None:
                painter.setPen(QPen(skeleton_shadow, width + 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawLine(start, end)
                painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawLine(start, end)

            def draw_joint(center: QPointF, radius: float = 4.0, color: QColor = skeleton_joint) -> None:
                painter.setPen(soft_pen("#0b1220", 2))
                painter.setBrush(QBrush(color))
                painter.drawEllipse(center, radius, radius)

            def draw_socket_anchor(label: str, center: QPointF) -> None:
                painter.setPen(soft_pen("#052e16", 5))
                painter.drawEllipse(center, 7, 7)
                painter.setPen(soft_pen(socket_color.name(), 2))
                painter.setBrush(QBrush(QColor(53, 212, 139, 72)))
                painter.drawEllipse(center, 6, 6)
                draw_label(label, center + QPointF(8, -8), "#86efac", bold=True)

            def draw_ribs(center_x: float, ys: Sequence[float], half_widths: Sequence[float]) -> None:
                painter.setPen(soft_pen("#94a3b8", 2))
                for y, half_width in zip(ys, half_widths):
                    painter.drawLine(point(center_x - half_width, y), point(center_x + half_width, y))

            def draw_back_body() -> None:
                # Human skeleton schematic: bones and sockets, not a blob/body proxy.
                head = point(0.50, 0.10)
                neck = point(0.50, 0.19)
                chest = point(0.50, 0.34)
                spine = point(0.50, 0.58)
                pelvis = point(0.50, 0.72)
                left_shoulder, right_shoulder = point(0.37, 0.25), point(0.63, 0.25)
                left_elbow, right_elbow = point(0.31, 0.45), point(0.69, 0.45)
                left_hand, right_hand = point(0.35, 0.64), point(0.65, 0.64)
                left_hip, right_hip = point(0.42, 0.72), point(0.58, 0.72)
                left_knee, right_knee = point(0.43, 0.86), point(0.57, 0.86)
                left_foot, right_foot = point(0.39, 0.94), point(0.61, 0.94)
                painter.setPen(soft_pen("#64748b", 2, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(skeleton_guide))
                painter.drawRoundedRect(QRectF(point(0.36, 0.20), point(0.64, 0.82)), 18, 18)
                painter.setPen(soft_pen("#475569", 1, Qt.PenStyle.DashLine))
                painter.drawLine(point(0.50, 0.18), point(0.50, 0.94))
                draw_bone(head, neck, 2)
                draw_bone(neck, chest, 4)
                draw_bone(chest, spine, 4)
                draw_bone(spine, pelvis, 4)
                draw_bone(left_shoulder, right_shoulder, 4)
                draw_ribs(0.50, (0.33, 0.39, 0.45, 0.51), (0.095, 0.120, 0.108, 0.085))
                draw_bone(left_shoulder, left_elbow)
                draw_bone(left_elbow, left_hand)
                draw_bone(right_shoulder, right_elbow)
                draw_bone(right_elbow, right_hand)
                draw_bone(left_hip, right_hip, 4)
                draw_bone(left_hip, left_knee)
                draw_bone(left_knee, left_foot)
                draw_bone(right_hip, right_knee)
                draw_bone(right_knee, right_foot)
                for joint in (neck, chest, spine, pelvis, left_shoulder, right_shoulder, left_elbow, right_elbow, left_hand, right_hand, left_hip, right_hip, left_knee, right_knee):
                    draw_joint(joint, 3.6)
                draw_joint(head, 11.0, QColor("#e2e8f0"))
                draw_socket_anchor("Spine2", chest + QPointF(0, -4))
                draw_socket_anchor("Pelvis_L", left_hip + QPointF(-6, 4))
                draw_label("human skeleton back", point(0.03, 0.07), "#93c5fd", bold=True)

            def draw_side_body() -> None:
                head = point(0.52, 0.10)
                neck = point(0.53, 0.20)
                chest = point(0.55, 0.35)
                spine = point(0.54, 0.57)
                pelvis = point(0.52, 0.72)
                shoulder = point(0.56, 0.26)
                elbow = point(0.64, 0.45)
                hand = point(0.61, 0.64)
                hip = point(0.55, 0.72)
                knee = point(0.58, 0.86)
                foot = point(0.64, 0.94)
                painter.setPen(soft_pen("#64748b", 2, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(skeleton_guide))
                painter.drawRoundedRect(QRectF(point(0.42, 0.20), point(0.62, 0.82)), 18, 18)
                draw_bone(head, neck, 2)
                draw_bone(neck, chest, 4)
                draw_bone(chest, spine, 4)
                draw_bone(spine, pelvis, 4)
                draw_bone(point(0.48, 0.29), shoulder, 4)
                draw_bone(shoulder, elbow)
                draw_bone(elbow, hand)
                draw_bone(point(0.48, 0.72), hip, 4)
                draw_bone(hip, knee)
                draw_bone(knee, foot)
                painter.setPen(soft_pen("#94a3b8", 2))
                for y, width in ((0.36, 0.070), (0.43, 0.082), (0.50, 0.065)):
                    painter.drawLine(point(0.49, y), point(0.49 + width, y + 0.01))
                for joint in (neck, chest, spine, pelvis, shoulder, elbow, hand, hip, knee):
                    draw_joint(joint, 3.6)
                draw_joint(head, 10.5, QColor("#e2e8f0"))
                draw_socket_anchor("back depth", point(0.60, 0.44))
                draw_socket_anchor("hip", point(0.57, 0.68))
                draw_label("human skeleton side", point(0.03, 0.07), "#93c5fd", bold=True)

            def draw_top_body() -> None:
                painter.setPen(soft_pen("#64748b", 2, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(skeleton_guide))
                painter.drawEllipse(point(0.50, 0.55), canvas.width() * 0.23, canvas.height() * 0.22)
                head = point(0.50, 0.31)
                neck = point(0.50, 0.40)
                spine = point(0.50, 0.55)
                pelvis = point(0.50, 0.72)
                left_shoulder, right_shoulder = point(0.33, 0.46), point(0.67, 0.46)
                left_hip, right_hip = point(0.40, 0.70), point(0.60, 0.70)
                draw_bone(head, neck, 2)
                draw_bone(neck, spine, 4)
                draw_bone(spine, pelvis, 4)
                draw_bone(left_shoulder, right_shoulder, 4)
                draw_bone(left_hip, right_hip, 4)
                draw_bone(left_shoulder, point(0.25, 0.55))
                draw_bone(right_shoulder, point(0.75, 0.55))
                draw_bone(left_hip, point(0.34, 0.84))
                draw_bone(right_hip, point(0.66, 0.84))
                painter.setPen(soft_pen("#94a3b8", 2))
                painter.drawLine(point(0.38, 0.54), point(0.62, 0.54))
                painter.drawLine(point(0.41, 0.61), point(0.59, 0.61))
                for joint in (neck, spine, pelvis, left_shoulder, right_shoulder, left_hip, right_hip):
                    draw_joint(joint, 3.6)
                draw_joint(head, 10.0, QColor("#e2e8f0"))
                draw_socket_anchor("Spine2", spine + QPointF(0, -5))
                draw_socket_anchor("Pelvis", pelvis + QPointF(0, 5))
                draw_label("human skeleton top", point(0.03, 0.07), "#93c5fd", bold=True)

            if self._view_mode == "top":
                draw_top_body()
            elif self._view_mode == "side":
                draw_side_body()
            else:
                draw_back_body()

            if self._show_shield and "dual_onehand" in self._template_id:
                shield_center = point(0.38, 0.48) if self._view_mode == "back" else point(0.64, 0.50)
                if self._view_mode == "top":
                    shield_center = point(0.35, 0.54)
                painter.setPen(soft_pen("#f97316", 2))
                painter.setBrush(QBrush(QColor(249, 115, 22, 48)))
                painter.drawEllipse(shield_center, canvas.width() * 0.12, canvas.height() * 0.18)
                draw_label("shield", shield_center + QPointF(12, 4), "#fdba74")

            def row_map(rows: Sequence[WeaponSwapSocketRow]) -> Dict[str, WeaponSwapSocketRow]:
                return {str(row.name or "").casefold(): row for row in rows if isinstance(row, WeaponSwapSocketRow)}

            base_rows = self._baseline_rows
            if not base_rows:
                try:
                    base_rows = weapon_swap_template_socket_rows(self._template_id)
                except Exception:
                    base_rows = ()
            base_by_name = row_map(base_rows)

            def row_delta(row: WeaponSwapSocketRow) -> Tuple[float, float, float]:
                base = base_by_name.get(str(row.name or "").casefold())
                if isinstance(base, WeaponSwapSocketRow):
                    return (
                        float(row.translation[0]) - float(base.translation[0]),
                        float(row.translation[1]) - float(base.translation[1]),
                        float(row.translation[2]) - float(base.translation[2]),
                    )
                return (0.0, 0.0, 0.0)

            def display_rows(rows: Sequence[WeaponSwapSocketRow]) -> Tuple[WeaponSwapSocketRow, ...]:
                valid_rows = tuple(row for row in rows if isinstance(row, WeaponSwapSocketRow))
                if "dual_onehand" in self._template_id:
                    spine_rows = tuple(row for row in valid_rows if str(row.name or "").startswith("Spine2_"))
                    return spine_rows or valid_rows[:2]
                subweapon_rows = tuple(row for row in valid_rows if "childsocket" in str(row.name or "").casefold())
                return (subweapon_rows or valid_rows)[:1]

            def line_for_row(row: WeaponSwapSocketRow, *, planned: bool) -> Tuple[QPointF, QPointF]:
                dx, dy, dz = row_delta(row)
                if "dual_onehand" in self._template_id:
                    is_left = str(row.name or "").endswith("_L_Socket")
                    side = 1.0 if is_left else -1.0
                    tx = float(row.translation[0])
                    ty = float(row.translation[1])
                    tz = float(row.translation[2])
                    if self._view_mode == "top":
                        start = point(0.50 + (tx * 0.92), 0.55 - (tz * 1.85))
                        end = point(0.50 + ((tx + side * 0.24) * 0.92), 0.56 - (tz * 1.40))
                    elif self._view_mode == "side":
                        start = point(0.55 + (tz * 1.80), 0.36 - (ty * 0.62))
                        end = point(0.47 + (tz * 1.45), 0.90 - (ty * 0.18))
                    else:
                        sx = 0.50 + (tx * 0.92)
                        sy = 0.44 - (ty * 0.62)
                        if "crossed" in self._template_id:
                            ex = sx + (0.23 * side)
                        else:
                            ex = sx - 0.12
                        start = point(sx, sy)
                        end = point(ex, 0.90 - (ty * 0.16))
                    return start, end
                if self._view_mode == "top":
                    start = point(0.34 + (dx * 0.90), 0.62 - (dy * 1.45))
                    end = point(0.70 + (dx * 0.55), 0.73 - (dy * 1.12))
                elif self._view_mode == "side":
                    start = point(0.58 + (dy * -0.45), 0.62 - (dz * 0.62))
                    end = point(0.69 + (dy * -0.32), 0.90 - (dz * 0.18))
                else:
                    start = point(0.36 + (dx * 0.70), 0.64 - (dz * 0.62))
                    end = point(0.69 + (dx * 0.48), 0.91 - (dz * 0.18))
                return start, end

            def draw_weapon_line(start: QPointF, end: QPointF, color: QColor, label: str, *, planned: bool) -> None:
                dx = end.x() - start.x()
                dy = end.y() - start.y()
                length = max(1.0, math.sqrt((dx * dx) + (dy * dy)))
                ux, uy = dx / length, dy / length
                px, py = -uy, ux
                painter.setPen(soft_pen("#111827", 9 if planned else 6))
                painter.drawLine(start + QPointF(px * 2.0, py * 2.0), end + QPointF(px * 2.0, py * 2.0))
                painter.setPen(soft_pen(color.name(), 6 if planned else 4, Qt.PenStyle.SolidLine if planned else Qt.PenStyle.DashLine))
                painter.drawLine(start, end)
                painter.setPen(soft_pen("#e5e7eb", 2 if planned else 1, Qt.PenStyle.SolidLine if planned else Qt.PenStyle.DashLine))
                painter.drawLine(start, end)
                guard_center = start + QPointF(ux * 18.0, uy * 18.0)
                painter.setPen(soft_pen("#f59e0b", 4 if planned else 2))
                painter.drawLine(
                    guard_center + QPointF(px * 13.0, py * 13.0),
                    guard_center - QPointF(px * 13.0, py * 13.0),
                )
                painter.setPen(soft_pen("#fbbf24", 5 if planned else 3))
                painter.drawLine(start - QPointF(ux * 26.0, uy * 26.0), start + QPointF(ux * 12.0, uy * 12.0))
                painter.setBrush(QBrush(QColor("#f59e0b" if planned else "#60a5fa")))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(start, 5 if planned else 4, 5 if planned else 4)
                if planned:
                    draw_label(label, start + QPointF(8, -6), color.name(), bold=True)

            for row in display_rows(base_rows):
                if not isinstance(row, WeaponSwapSocketRow):
                    continue
                start, end = line_for_row(row, planned=False)
                draw_weapon_line(start, end, baseline_color, "baseline", planned=False)
            for row in display_rows(self._rows):
                start, end = line_for_row(row, planned=True)
                label = str(row.name or "planned").replace("_Socket", "").replace("_ChildSocket", "")
                draw_weapon_line(start, end, planned_color, label, planned=True)

            painter.setPen(soft_pen("#60a5fa", 2, Qt.PenStyle.DashLine))
            painter.drawLine(point(0.05, 0.95), point(0.17, 0.95))
            draw_label("baseline", point(0.18, 0.96), "#93c5fd")
            painter.setPen(soft_pen("#35d48b", 4))
            painter.drawLine(point(0.34, 0.95), point(0.46, 0.95))
            draw_label("planned", point(0.47, 0.96), "#86efac")

            painter.setPen(soft_pen("#334155", 1))
            painter.setBrush(QBrush(QColor(15, 23, 42, 160)))
            painter.drawRoundedRect(readout, 6, 6)
            readout_font = painter.font()
            readout_font.setPointSize(max(8, readout_font.pointSize()))
            painter.setFont(readout_font)
            painter.setPen(soft_pen("#cbd5e1", 1))
            readout_lines = []
            if "dual_onehand" in self._template_id:
                readout_lines.append("Dual axes: body socket Y = height; body socket Z = body distance; X = left/right spread.")
            else:
                readout_lines.append("2H axes: hip socket placement plus weapon child tilt; mounted socket patch is package-only.")
            for row in display_rows(self._rows)[:3]:
                dx, dy, dz = row_delta(row)
                readout_lines.append(
                    f"{row.name}: T {row.translation[0]:+.3f} {row.translation[1]:+.3f} {row.translation[2]:+.3f}; delta {dx:+.3f} {dy:+.3f} {dz:+.3f}"
                )
            if self._body_path:
                readout_lines.append(f"Body PAC candidate: {PurePosixPath(self._body_path).name}")
            if self._weapon_paths:
                names = ", ".join(PurePosixPath(path).name for path in self._weapon_paths[:2])
                if len(self._weapon_paths) > 2:
                    names += f" +{len(self._weapon_paths) - 2}"
                readout_lines.append(f"Weapon PAC: {names}")
            if self._native_note:
                readout_lines.append(self._native_note)
            line_y = readout.top() + 18
            for line in readout_lines[:6]:
                painter.drawText(QRectF(readout.left() + 10, line_y - 12, readout.width() - 20, 18), Qt.AlignLeft | Qt.AlignVCenter, line)
                line_y += 18
        finally:
            painter.end()


__all__ = ["WeaponPlacementStudioPlacementMap"]
