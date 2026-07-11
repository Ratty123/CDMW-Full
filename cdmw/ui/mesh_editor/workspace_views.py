"""Canvas and display helpers for the Mesh Editor workspace."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSlider,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.mesh import (
    MeshCompareSummary,
    MeshEditSessionView,
    MeshExportValidationReport,
    MeshSkeletonSummary,
    MeshUvSummary,
    MeshWorkspaceSummary,
)
from cdmw.ui.mesh_editor.actions import (
    MESH_EDITOR_ACTIONS,
    NATIVE_EDITOR_SESSION_COMMANDS,
    MeshEditorAction,
    mesh_editor_actions_by_key,
)
from cdmw.ui.mesh_editor.icons import mesh_editor_action_icon
from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame
from cdmw.ui.native_preview_panel import NativePreviewPanel


_LEFT_TOOL_PAGES = (
    ("Tools", ("selection", "transform", "sculpt")),
    ("Edit", ("topology", "cleanup", "normals", "history")),
    ("UV", ("uv", "material")),
    ("Rig", ()),
)
_LEFT_CATEGORY_LABELS = {
    "selection": "Selection",
    "transform": "Transform",
    "sculpt": "Sculpt",
    "topology": "Topology",
    "cleanup": "Cleanup",
    "normals": "Normals",
    "uv": "UV",
    "material": "Material",
    "history": "History",
}

_SLOW_FRAME_MS = 1000.0 / 60.0
_MODE_ACTION_BY_TEXT = {"object": "mode_object", "edit": "mode_edit", "sculpt": "mode_sculpt"}
_SELECTION_ACTION_BY_TEXT = {"vertex": "select_vertex", "edge": "select_edge", "face": "select_face"}
_SKELETON_PANEL_BONE_LIMIT = 512
_SKELETON_PANEL_WEIGHT_LIMIT = 32


def _issue_location(submesh_index: int, vertex_index: int, face_index: int) -> str:
    parts: list[str] = []
    if submesh_index >= 0:
        parts.append(f"part {submesh_index}")
    if vertex_index >= 0:
        parts.append(f"vertex {vertex_index}")
    if face_index >= 0:
        parts.append(f"face {face_index}")
    return f"({' / '.join(parts)})" if parts else ""


def _short_hash(value: str) -> str:
    text = str(value or "").strip()
    return text[:12] if text else ""


def _join_report_values(values: Iterable[object]) -> str:
    items = tuple(str(value) for value in tuple(values or ()) if str(value))
    return ", ".join(items)


def _rebuild_report_operation_names(report: object) -> tuple[str, ...]:
    names: list[str] = []
    for operation in tuple(getattr(report, "edit_operations", ()) or ()):
        if isinstance(operation, dict):
            name = str(operation.get("operation", "") or "").strip()
            if name:
                names.append(name)
    return tuple(names)


def _workspace_action_tooltip(action: MeshEditorAction) -> str:
    tooltip = str(action.tooltip or action.text or "").strip()
    shortcut = str(action.shortcut or "").strip()
    if shortcut:
        return f"{tooltip}\nShortcut: {shortcut}" if tooltip else f"Shortcut: {shortcut}"
    return tooltip


def _part_selection_summary_text(summary: MeshWorkspaceSummary | None) -> str:
    if summary is None:
        return "Selected parts: no mesh."
    selected = tuple(part for part in summary.parts if part.selected)
    if not selected:
        return f"Selected parts: 0/{int(summary.part_count or 0)}. Click rows or D3D11 viewport parts to select."
    details = "; ".join(_part_detail_text(part) for part in selected[:4])
    if len(selected) > 4:
        details = f"{details}; +{len(selected) - 4} more"
    return f"Selected parts: {len(selected)}/{int(summary.part_count or 0)} | {details}"


def _part_selection_status_text(summary: MeshWorkspaceSummary | None) -> str:
    if summary is None:
        return "Parts: no mesh."
    selected = tuple(part for part in summary.parts if part.selected)
    if not selected:
        return f"Parts: 0/{int(summary.part_count or 0)} selected."
    names = ", ".join(f"{part.index}:{part.name}" for part in selected[:5])
    if len(selected) > 5:
        names = f"{names}, +{len(selected) - 5} more"
    return f"Parts: {len(selected)}/{int(summary.part_count or 0)} selected | {names}"


def _part_detail_text(part: object) -> str:
    name = str(getattr(part, "name", "") or f"part_{getattr(part, 'index', '')}")
    material = str(getattr(part, "material", "") or "missing material")
    texture = str(getattr(part, "texture", "") or "missing texture")
    return f"{int(getattr(part, 'index', -1))}: {name} | mat {material} | tex {texture}"


class MeshUvCanvas(QFrame):
    region_selected = Signal(tuple, tuple, str)
    lasso_selected = Signal(tuple, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MeshEditorUVCanvas")
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._summary: MeshUvSummary | None = None
        self._drag_start_uv: tuple[float, float] | None = None
        self._drag_current_uv: tuple[float, float] | None = None
        self._lasso_points_uv: list[tuple[float, float]] = []
        self.setProperty("uvIslandCount", 0)
        self.setProperty("uvSelectedIslandCount", 0)
        self.setProperty("uvTextureNames", "")

    def set_uv_summary(self, summary: MeshUvSummary | None) -> None:
        self._summary = summary
        textures = sorted({island.texture for island in tuple(summary.islands if summary is not None else ()) if island.texture})
        self.setProperty("uvIslandCount", int(summary.island_count if summary is not None else 0))
        self.setProperty("uvSelectedIslandCount", int(summary.selected_island_count if summary is not None else 0))
        self.setProperty("uvTextureNames", ", ".join(textures))
        self.setToolTip(
            "No UV islands"
            if summary is None or not summary.islands
            else f"{summary.island_count} UV island(s) on {', '.join(textures) or 'missing texture'}"
        )
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        background = QColor(28, 32, 36)
        grid = QColor(74, 84, 94)
        accent = QColor(90, 170, 255)
        selected = QColor(255, 190, 72)
        text = QColor(225, 230, 235)
        painter.fillRect(self.rect(), background)
        tile = self._tile_rect()
        painter.fillRect(tile, QColor(42, 46, 52))
        for index in range(1, 4):
            x = tile.left() + tile.width() * index / 4.0
            y = tile.top() + tile.height() * index / 4.0
            painter.setPen(QPen(grid, 1))
            painter.drawLine(int(x), int(tile.top()), int(x), int(tile.bottom()))
            painter.drawLine(int(tile.left()), int(y), int(tile.right()), int(y))
        painter.setPen(QPen(QColor(150, 160, 170), 1.4))
        painter.drawRect(tile)
        summary = self._summary
        if summary is None or not summary.islands:
            painter.setPen(QPen(text, 1))
            painter.drawText(tile, Qt.AlignmentFlag.AlignCenter, "No UV islands")
            painter.end()
            return
        for island in summary.islands:
            rect = self._island_rect(tile, island.uv_min, island.uv_max)
            painter.setPen(QPen(selected if island.selected else accent, 2.0 if island.selected else 1.3))
            painter.drawRect(rect)
            painter.drawText(rect.adjusted(3, 2, -2, -2), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, str(island.index))
        if self._drag_start_uv is not None and self._drag_current_uv is not None:
            rect = self._island_rect(tile, self._drag_start_uv, self._drag_current_uv)
            painter.setPen(QPen(selected, 1.6, Qt.PenStyle.DashLine))
            painter.drawRect(rect)
        if self._lasso_points_uv:
            painter.setPen(QPen(selected, 1.6, Qt.PenStyle.DashLine))
            previous = self._position_from_uv(tile, self._lasso_points_uv[0])
            for point in self._lasso_points_uv[1:]:
                current = self._position_from_uv(tile, point)
                painter.drawLine(previous, current)
                previous = current
        texture_names = str(self.property("uvTextureNames") or "missing texture")
        painter.setPen(QPen(text, 1))
        painter.drawText(self.rect().adjusted(8, 4, -8, -4), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, texture_names)
        painter.end()

    def mousePressEvent(self, event: object) -> None:
        button = getattr(event, "button", lambda: None)()
        if button == Qt.MouseButton.RightButton:
            self._lasso_points_uv = [self._uv_from_event(event)]
            getattr(event, "accept", lambda: None)()
            self.update()
            return
        if button != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)  # type: ignore[arg-type]
            return
        self._drag_start_uv = self._uv_from_event(event)
        self._drag_current_uv = self._drag_start_uv
        getattr(event, "accept", lambda: None)()
        self.update()

    def mouseMoveEvent(self, event: object) -> None:
        if self._lasso_points_uv:
            point = self._uv_from_event(event)
            if point != self._lasso_points_uv[-1]:
                self._lasso_points_uv.append(point)
            getattr(event, "accept", lambda: None)()
            self.update()
            return
        if self._drag_start_uv is None:
            super().mouseMoveEvent(event)  # type: ignore[arg-type]
            return
        self._drag_current_uv = self._uv_from_event(event)
        getattr(event, "accept", lambda: None)()
        self.update()

    def mouseReleaseEvent(self, event: object) -> None:
        button = getattr(event, "button", lambda: None)()
        if button == Qt.MouseButton.RightButton and self._lasso_points_uv:
            self._lasso_points_uv.append(self._uv_from_event(event))
            points = tuple(self._lasso_points_uv)
            self._lasso_points_uv = []
            operation = _selection_operation_from_modifiers(getattr(event, "modifiers", lambda: Qt.KeyboardModifier.NoModifier)())
            if len(points) >= 3:
                self.lasso_selected.emit(points, operation)
            getattr(event, "accept", lambda: None)()
            self.update()
            return
        if self._drag_start_uv is None or button != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)  # type: ignore[arg-type]
            return
        end_uv = self._uv_from_event(event)
        start_uv = self._drag_start_uv
        self._drag_start_uv = None
        self._drag_current_uv = None
        operation = _selection_operation_from_modifiers(getattr(event, "modifiers", lambda: Qt.KeyboardModifier.NoModifier)())
        self.region_selected.emit(start_uv, end_uv, operation)
        getattr(event, "accept", lambda: None)()
        self.update()

    def _tile_rect(self) -> QRectF:
        bounds = self.contentsRect().adjusted(10, 20, -10, -10)
        side = max(1, min(bounds.width(), bounds.height()))
        return QRectF(bounds.left(), bounds.top(), side, side)

    def _uv_from_event(self, event: object) -> tuple[float, float]:
        position_getter = getattr(event, "position", None)
        position = position_getter() if callable(position_getter) else getattr(event, "pos", lambda: QPointF())()
        return self._uv_from_position(QPointF(position))

    def _uv_from_position(self, position: QPointF) -> tuple[float, float]:
        tile = self._tile_rect()
        u = 0.0 if tile.width() <= 0.0 else (position.x() - tile.left()) / tile.width()
        v = 0.0 if tile.height() <= 0.0 else (tile.bottom() - position.y()) / tile.height()
        return (_clamped01(u), _clamped01(v))

    def _position_from_uv(self, tile: QRectF, uv: tuple[float, float]) -> QPointF:
        return QPointF(tile.left() + tile.width() * _clamped01(uv[0]), tile.bottom() - tile.height() * _clamped01(uv[1]))

    def _island_rect(self, tile: QRectF, uv_min: tuple[float, float], uv_max: tuple[float, float]) -> QRectF:
        left = tile.left() + tile.width() * _clamped01(uv_min[0])
        right = tile.left() + tile.width() * _clamped01(uv_max[0])
        top = tile.bottom() - tile.height() * _clamped01(uv_max[1])
        bottom = tile.bottom() - tile.height() * _clamped01(uv_min[1])
        return QRectF(left, top, max(1.0, right - left), max(1.0, bottom - top))


def _clamped01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _selection_operation_from_modifiers(modifiers: object) -> str:
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        return "toggle"
    if modifiers & Qt.KeyboardModifier.AltModifier:
        return "subtract"
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        return "add"
    return "replace"


def _constraint_bone_label(role: str, name: str, index: int, confidence: str) -> str:
    clean_name = str(name or "").strip()
    if not clean_name:
        return ""
    if index >= 0:
        return f"{role} {clean_name} (#{index} {confidence or 'exact_name'})"
    return f"{role} {clean_name} ({confidence or 'unmatched'})"


def _constraint_candidate_token_text(candidate: object) -> str:
    parts: list[str] = []
    channels = tuple(getattr(candidate, "expression_channels", ()) or ())
    if channels:
        confidence = str(getattr(candidate, "expression_channel_confidence", "") or "unknown")
        parts.append(f"channels {confidence}: {', '.join(channels)}")
    limits = tuple(getattr(candidate, "limit_operators", ()) or ())
    if limits:
        confidence = str(getattr(candidate, "limit_operator_confidence", "") or "unknown")
        parts.append(f"limits {confidence}: {', '.join(limits)}")
    numeric_values = tuple(getattr(candidate, "expression_numeric_values", ()) or ())
    if numeric_values:
        confidence = str(getattr(candidate, "expression_numeric_value_confidence", "") or "unknown")
        parts.append(f"numeric constants={len(numeric_values)} {confidence}")
    numeric_roles = tuple(str(value) for value in getattr(candidate, "expression_numeric_roles", ()) or () if str(value))
    if numeric_roles:
        counts: dict[str, int] = {}
        for role in numeric_roles:
            counts[role] = counts.get(role, 0) + 1
        confidence = str(getattr(candidate, "expression_numeric_role_confidence", "") or "unknown")
        parts.append(
            "numeric roles "
            f"{confidence}: "
            + ", ".join(f"{role}={count}" for role, count in sorted(counts.items()))
        )
    shape = str(getattr(candidate, "expression_shape", "") or "")
    if shape:
        confidence = str(getattr(candidate, "expression_shape_confidence", "") or "unknown")
        parts.append(f"shape {confidence}: {shape}")
    semantics = str(getattr(candidate, "expression_semantics_confidence", "") or "")
    if semantics:
        parts.append(f"semantics {semantics}")
    return " | ".join(parts)


def _constraint_candidate_field_offset_text(candidate: object) -> str:
    fields: list[str] = []
    for label, offset_name, delta_name in (
        ("expr", "expression_offset", ""),
        ("target", "target_bone_offset", "target_bone_delta"),
        ("helper", "helper_bone_offset", "helper_bone_delta"),
        ("parent", "parent_bone_offset", "parent_bone_delta"),
    ):
        offset = int(getattr(candidate, offset_name, 0) or 0)
        if offset <= 0:
            continue
        delta = int(getattr(candidate, delta_name, 0) or 0) if delta_name else 0
        suffix = f"(+{delta})" if delta > 0 else ""
        fields.append(f"{label}@0x{offset:X}{suffix}")
    if not fields:
        return ""
    confidence = str(getattr(candidate, "field_offset_confidence", "") or "unknown")
    span_start = int(getattr(candidate, "record_span_start", 0) or 0)
    span_end = int(getattr(candidate, "record_span_end", 0) or 0)
    if span_start > 0 and span_end > span_start:
        fields.append(f"span 0x{span_start:X}-0x{span_end:X}")
    sequence = tuple(str(value) for value in getattr(candidate, "record_field_sequence", ()) or () if str(value))
    if sequence:
        fields.append(f"order {'>'.join(sequence)}")
    layout_status = str(getattr(candidate, "record_layout_status", "") or "")
    if layout_status:
        fields.append(f"layout {layout_status}")
    gap_status = str(getattr(candidate, "record_gap_status", "") or "")
    gap_counts = tuple(getattr(candidate, "record_gap_class_counts", ()) or ())
    if gap_status or gap_counts:
        gap_parts = [f"gaps {gap_status or 'unknown'}"]
        if gap_counts:
            gap_parts.append(", ".join(f"{label}={count}" for label, count in gap_counts))
        gap_max = int(getattr(candidate, "record_gap_max_size", 0) or 0)
        if gap_max > 0:
            gap_parts.append(f"max={gap_max}")
        fields.append(" ".join(gap_parts))
    scalar_counts = tuple(getattr(candidate, "record_gap_scalar_kind_counts", ()) or ())
    if scalar_counts:
        scalar_status = str(getattr(candidate, "record_gap_scalar_status", "") or "unknown")
        scalar_total = int(getattr(candidate, "record_gap_scalar_candidate_count", 0) or 0)
        scalar_parts = [f"scalars {scalar_status}"]
        scalar_parts.append(", ".join(f"{label}={count}" for label, count in scalar_counts))
        if scalar_total > 0:
            scalar_parts.append(f"count={scalar_total}")
        fields.append(" ".join(scalar_parts))
    match_counts = tuple(getattr(candidate, "record_gap_numeric_match_role_counts", ()) or ())
    if match_counts:
        match_status = str(getattr(candidate, "record_gap_numeric_match_status", "") or "unknown")
        match_total = int(getattr(candidate, "record_gap_numeric_match_count", 0) or 0)
        match_parts = [f"numeric matches {match_status}"]
        match_parts.append(", ".join(f"{label}={count}" for label, count in match_counts))
        storage_counts = tuple(getattr(candidate, "record_gap_numeric_match_storage_counts", ()) or ())
        if storage_counts:
            match_parts.append(", ".join(f"{label}={count}" for label, count in storage_counts))
        pair_counts = tuple(getattr(candidate, "record_gap_numeric_match_pair_counts", ()) or ())
        if pair_counts:
            match_parts.append("pairs " + ", ".join(f"{label}={count}" for label, count in pair_counts))
        value_confidence_counts = tuple(getattr(candidate, "record_gap_numeric_match_value_confidence_counts", ()) or ())
        if value_confidence_counts:
            match_parts.append("value confidence " + _constraint_counts_text(value_confidence_counts))
        previous_delta_counts = tuple(getattr(candidate, "record_gap_numeric_match_previous_delta_counts", ()) or ())
        if previous_delta_counts:
            match_parts.append(
                "prev deltas "
                + _constraint_delta_counts_text(
                    previous_delta_counts,
                    int(getattr(candidate, "record_gap_numeric_match_min_previous_delta", 0) or 0),
                    int(getattr(candidate, "record_gap_numeric_match_max_previous_delta", 0) or 0),
                )
            )
        next_delta_counts = tuple(getattr(candidate, "record_gap_numeric_match_next_delta_counts", ()) or ())
        if next_delta_counts:
            match_parts.append(
                "next deltas "
                + _constraint_delta_counts_text(
                    next_delta_counts,
                    int(getattr(candidate, "record_gap_numeric_match_min_next_delta", 0) or 0),
                    int(getattr(candidate, "record_gap_numeric_match_max_next_delta", 0) or 0),
                )
            )
        if match_total > 0:
            match_parts.append(f"count={match_total}")
        fields.append(" ".join(match_parts))
    return f"fields {confidence}: {', '.join(fields)}"


def _constraint_bone_match_counts_text(candidate_count: int, rows: tuple[tuple[str, int], ...]) -> str:
    parts: list[str] = [f"{candidate_count} candidate rows"] if candidate_count else []
    for key, count in rows:
        role, _, confidence = key.partition("_")
        parts.append(f"{role} {confidence}={count}")
    return " | ".join(parts)


def _constraint_counts_text(rows: tuple[tuple[str, int], ...]) -> str:
    return " | ".join(f"{label}={count}" for label, count in rows)


def _constraint_delta_counts_text(rows: tuple[tuple[str, int], ...], minimum: int, maximum: int) -> str:
    def sort_key(row: tuple[str, int]) -> tuple[int, str]:
        label, _count = row
        try:
            return int(label), label
        except ValueError:
            return 2**31 - 1, label

    text = ", ".join(f"{label}={count}" for label, count in sorted(rows, key=sort_key))
    return f"{text} (range {minimum}-{maximum})" if text else f"range {minimum}-{maximum}"


def _constraint_numeric_match_text(
    match_count: int,
    status_counts: tuple[tuple[str, int], ...],
    role_counts: tuple[tuple[str, int], ...],
    storage_counts: tuple[tuple[str, int], ...],
    pair_counts: tuple[tuple[str, int], ...],
    value_confidence_counts: tuple[tuple[str, int], ...],
    family_counts: tuple[tuple[str, int], ...],
    family_row_counts: tuple[tuple[str, int], ...],
    family_role_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...],
    family_pair_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...],
    family_value_confidence_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...],
    signature_counts: tuple[tuple[str, int], ...],
    candidate_relative_signature_counts: tuple[tuple[str, int], ...],
    previous_delta_counts: tuple[tuple[str, int], ...],
    next_delta_counts: tuple[tuple[str, int], ...],
    candidate_relative_offset_counts: tuple[tuple[str, int], ...],
    min_previous_delta: int,
    max_previous_delta: int,
    min_next_delta: int,
    max_next_delta: int,
    min_candidate_relative_offset: int,
    max_candidate_relative_offset: int,
    offset_confidence: str,
    candidate_relative_offset_confidence: str,
) -> str:
    parts = [f"{match_count} unbound text/scalar numeric matches"]
    if status_counts:
        parts.append(_constraint_counts_text(status_counts))
    if role_counts:
        parts.append("roles " + _constraint_counts_text(role_counts))
    if storage_counts:
        parts.append("storage " + _constraint_counts_text(storage_counts))
    if pair_counts:
        parts.append("pairs " + _constraint_counts_text(pair_counts))
    if value_confidence_counts:
        parts.append("value confidence " + _constraint_counts_text(value_confidence_counts))
    if family_counts:
        parts.append("families " + _constraint_counts_text(family_counts))
    if family_row_counts:
        parts.append("family rows " + _constraint_counts_text(family_row_counts))
    if family_role_counts:
        parts.append("family roles " + _constraint_nested_counts_text(family_role_counts))
    if family_pair_counts:
        parts.append("family pairs " + _constraint_nested_counts_text(family_pair_counts))
    if family_value_confidence_counts:
        parts.append("family value confidence " + _constraint_nested_counts_text(family_value_confidence_counts))
    if signature_counts:
        parts.append(f"signatures {len(signature_counts)} unique")
    if candidate_relative_signature_counts:
        parts.append(f"rel signatures {len(candidate_relative_signature_counts)} unique")
    if previous_delta_counts:
        parts.append("prev deltas " + _constraint_delta_counts_text(previous_delta_counts, min_previous_delta, max_previous_delta))
    if next_delta_counts:
        parts.append("next deltas " + _constraint_delta_counts_text(next_delta_counts, min_next_delta, max_next_delta))
    if candidate_relative_offset_counts:
        parts.append(
            "candidate rel offsets "
            + _constraint_delta_counts_text(
                candidate_relative_offset_counts,
                min_candidate_relative_offset,
                max_candidate_relative_offset,
            )
        )
    if offset_confidence:
        parts.append(offset_confidence)
    if candidate_relative_offset_confidence:
        parts.append(candidate_relative_offset_confidence)
    parts.append("value layout unproven")
    return " | ".join(parts)


def _constraint_nested_counts_text(
    rows: tuple[tuple[str, tuple[tuple[str, int], ...]], ...],
) -> str:
    return "; ".join(f"{label}: {_constraint_counts_text(counts)}" for label, counts in rows if counts)


def _constraint_expression_evidence_text(
    status: str,
    token_confidence: str,
    semantics_confidence: str,
    rows: tuple[tuple[str, int], ...],
    syntax_signature_counts: tuple[tuple[str, int], ...],
    numeric_value_count: int,
) -> str:
    parts: list[str] = []
    if status:
        parts.append(status)
    if token_confidence or semantics_confidence:
        parts.append(f"tokens {token_confidence or 'unknown'}")
        parts.append(f"semantics {semantics_confidence or 'unknown'}")
    for label, count in rows[:8]:
        parts.append(f"{label}={count}")
    if syntax_signature_counts:
        parts.append(f"syntax signatures {len(syntax_signature_counts)} unique")
    if numeric_value_count:
        parts.append(f"numeric constants={numeric_value_count}")
    return " | ".join(parts)


def _constraint_field_offset_text(
    status: str,
    offset_confidence: str,
    record_confidence: str,
    rows: tuple[tuple[str, int], ...],
) -> str:
    parts: list[str] = []
    if status:
        parts.append(status)
    if offset_confidence:
        parts.append(f"offsets {offset_confidence}")
    if record_confidence:
        parts.append(f"record {record_confidence}")
    for label, count in rows:
        parts.append(f"{label}={count}")
    return " | ".join(parts)


def _constraint_solver_readiness_text(status: str, rows: tuple[tuple[str, int], ...]) -> str:
    parts: list[str] = [status] if status else []
    for label, count in rows:
        parts.append(f"{label}={count}")
    return " | ".join(parts)
