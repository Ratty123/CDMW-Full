"""Archive browser shared formatting and status-color helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import List

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidgetItem


class ArchiveUiFormattingMixin:
    """Small UI color/label helpers reused across archive browser panes."""

    @staticmethod
    def _ui_compact_status_line(parts: Sequence[object]) -> str:
        seen: set[str] = set()
        ordered: List[str] = []
        for raw_part in parts:
            part = str(raw_part or "").strip()
            normalized = part.casefold()
            if part and normalized not in seen:
                ordered.append(part)
                seen.add(normalized)
        return "  |  ".join(ordered)

    @staticmethod
    def _ui_evidence_label(value: object) -> str:
        key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        labels = {
            "fixup_backed": "Fixup-backed",
            "ptch": "Fixup-backed",
            "exact": "Exact",
            "declared_owner_array": "Owner-array",
            "owner_array": "Owner-array",
            "typed_layout": "Typed layout",
            "inferred": "Inferred",
            "spatial_fallback": "Spatial fallback",
            "raw_observation": "Raw context",
            "descriptor_context": "Context hint",
            "strong_inference": "Strong inference",
            "generated_from_current_xml": "Generated",
            "experimental": "Experimental",
        }
        return labels.get(key, str(value or "").replace("_", " ").strip().title() or "Evidence")

    @staticmethod
    def _ui_risk_color(value: object) -> QColor:
        key = str(value or "").strip().casefold()
        if key in {"safe", "low", "patchable", "exact", "sidecar", "selected", "model ok", "resolved"} or "safe" in key:
            return QColor("#86efac")
        if key in {"medium", "inferred", "context only", "partial", "same stem", "path hint", "name hint", "prefab"} or "inferred" in key:
            return QColor("#fde68a")
        if key in {"high", "experimental", "mostly read-only", "missing", "unresolved"} or "high" in key or "experimental" in key:
            return QColor("#fca5a5")
        return QColor("#cbd5e1")

    def _ui_style_status_columns(self, item: QTreeWidgetItem, values_by_column: Mapping[int, object]) -> None:
        for column, value in values_by_column.items():
            item.setForeground(int(column), QBrush(self._ui_risk_color(value)))

    @staticmethod
    def _archive_role_color(role: str) -> QColor:
        normalized = str(role or "").casefold()
        if "texture" in normalized:
            return QColor("#93c5fd")
        if "material" in normalized:
            return QColor("#f9a8d4")
        if "physics" in normalized or "hkx" in normalized:
            return QColor("#fbbf24")
        if "skeleton" in normalized or "rig" in normalized:
            return QColor("#c4b5fd")
        if "prefab" in normalized or "metadata" in normalized:
            return QColor("#67e8f9")
        if "mesh" in normalized:
            return QColor("#86efac")
        if "audio" in normalized or "video" in normalized:
            return QColor("#fdba74")
        if "ui" in normalized:
            return QColor("#a7f3d0")
        return QColor("#cbd5e1")

    def _style_archive_role_columns(self, item: QTreeWidgetItem, role: str, *columns: int) -> None:
        color = self._archive_role_color(role)
        for column in columns:
            item.setForeground(column, QBrush(color))

    @staticmethod
    def _archive_override_state_color(state: str) -> QColor:
        normalized = str(state or "").casefold()
        if "active mod" in normalized or "mod-added" in normalized:
            return QColor("#86efac")
        if "active original" in normalized:
            return QColor("#93c5fd")
        if "shadowed" in normalized:
            return QColor("#fca5a5")
        return QColor("#8b949e")

    def _style_archive_override_state_column(self, item: QTreeWidgetItem, state: str, column: int) -> None:
        item.setForeground(column, QBrush(self._archive_override_state_color(state)))
        if str(state or "").casefold().startswith("active"):
            font = item.font(column)
            font.setBold(True)
            item.setFont(column, font)


__all__ = ["ArchiveUiFormattingMixin"]
