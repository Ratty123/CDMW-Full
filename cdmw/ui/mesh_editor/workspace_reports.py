"""WorkspaceReportMixin methods for the Mesh Editor workspace."""

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


from cdmw.ui.mesh_editor.workspace_views import (
    MeshUvCanvas,
    _issue_location,
    _short_hash,
    _join_report_values,
    _rebuild_report_operation_names,
    _workspace_action_tooltip,
    _part_selection_summary_text,
    _part_selection_status_text,
    _part_detail_text,
    _clamped01,
    _selection_operation_from_modifiers,
    _constraint_bone_label,
    _constraint_candidate_token_text,
    _constraint_candidate_field_offset_text,
    _constraint_bone_match_counts_text,
    _constraint_counts_text,
    _constraint_delta_counts_text,
    _constraint_numeric_match_text,
    _constraint_nested_counts_text,
    _constraint_expression_evidence_text,
    _constraint_field_offset_text,
    _constraint_solver_readiness_text,
)

class WorkspaceReportMixin:
    def set_native_part_picking_status(self, message: str, *, available: bool = False) -> None:
        label = getattr(self, "native_part_pick_status_label", None)
        if label is None:
            return
        label.setText(str(message or "Part pick: unavailable"))
        label.setProperty("nativePartPickingAvailable", bool(available))

    def set_native_performance_status(self, payload: Mapping[str, object] | None) -> None:
        label = getattr(self, "native_performance_status_label", None)
        current_fps = self._native_performance_number(payload, "current_fps", "fps")
        average_fps = self._native_performance_number(payload, "average_fps", "avg_fps")
        frame_ms = self._native_performance_number(payload, "frame_time_ms", "frame_ms", "last_frame_ms", "first_frame_ms")
        cpu_ms = self._native_performance_number(payload, "cpu_update_ms", "cpu_ms", "update_ms")
        gpu_ms = self._native_performance_number(payload, "gpu_upload_ms", "gpu_upload_time_ms", "geometry_upload_ms")
        draw_calls = self._native_performance_int(payload, "draw_call_count", "draw_calls")
        vertex_count = self._native_performance_int(payload, "vertex_count", "vertices")
        index_count = self._native_performance_int(payload, "index_count", "indices")
        visible_submesh_count = self._native_performance_int(
            payload,
            "visible_submesh_count",
            "visible_submeshes",
            "submesh_count",
            "batch_count",
        )
        texture_memory = self._native_performance_int(payload, "texture_memory_bytes", "texture_memory_estimate_bytes")
        if current_fps is None and average_fps is None and frame_ms is not None and frame_ms > 0:
            current_fps = 1000.0 / frame_ms
        fps = current_fps if current_fps is not None else average_fps
        parts = [
            f"FPS: {fps:.1f}" if fps is not None and fps > 0 else "FPS: --",
            f"Frame: {frame_ms:.2f} ms" if frame_ms is not None and frame_ms > 0 else "Frame: -- ms",
        ]
        if average_fps is not None and average_fps > 0 and current_fps is not None and abs(average_fps - current_fps) >= 0.05:
            parts[0] = f"{parts[0]} (avg {average_fps:.1f})"
        if cpu_ms is not None and cpu_ms > 0:
            parts.append(f"CPU: {cpu_ms:.2f} ms")
        if gpu_ms is not None and gpu_ms > 0:
            parts.append(f"GPU: {gpu_ms:.2f} ms")
        available = bool(
            (fps is not None and fps > 0)
            or (frame_ms is not None and frame_ms > 0)
            or (cpu_ms is not None and cpu_ms > 0)
            or (gpu_ms is not None and gpu_ms > 0)
        )
        if label is not None:
            label.setText(" | ".join(parts))
            label.setProperty("nativePerformanceAvailable", available)
        tree = getattr(self, "performance_tree", None)
        if tree is not None:
            tree.clear()
            rows = (
                ("Current FPS", self._format_metric(current_fps, "{:.1f}")),
                ("Average FPS", self._format_metric(average_fps, "{:.1f}")),
                ("Frame time", self._format_metric(frame_ms, "{:.2f} ms")),
                ("CPU update", self._format_metric(cpu_ms, "{:.2f} ms")),
                ("GPU upload", self._format_metric(gpu_ms, "{:.2f} ms")),
                ("Draw calls", self._format_count(draw_calls)),
                ("Vertices", self._format_count(vertex_count)),
                ("Indices", self._format_count(index_count)),
                ("Visible submeshes", self._format_count(visible_submesh_count)),
                ("Texture memory", self._format_bytes(texture_memory)),
            )
            for metric, value in rows:
                tree.addTopLevelItem(QTreeWidgetItem((metric, value)))
        self._log_slow_native_frame(
            frame_ms=frame_ms,
            cpu_ms=cpu_ms,
            gpu_ms=gpu_ms,
            draw_calls=draw_calls,
            visible_submesh_count=visible_submesh_count,
        )

    @staticmethod
    def _native_performance_number(payload: Mapping[str, object] | None, *keys: str) -> float | None:
        if not isinstance(payload, Mapping):
            return None
        sources: list[Mapping[str, object]] = [payload]
        metrics = payload.get("metrics")
        if isinstance(metrics, Mapping):
            sources.insert(0, metrics)
        for source in sources:
            for key in keys:
                raw = source.get(key)
                if raw in (None, ""):
                    continue
                try:
                    value = float(raw)
                except (TypeError, ValueError, OverflowError):
                    continue
                if math.isfinite(value):
                    return value
        return None

    @classmethod
    def _native_performance_int(cls, payload: Mapping[str, object] | None, *keys: str) -> int | None:
        value = cls._native_performance_number(payload, *keys)
        if value is None or value < 0:
            return None
        return int(value)

    @staticmethod
    def _format_metric(value: float | None, pattern: str) -> str:
        return pattern.format(value) if value is not None and value > 0 else "--"

    @staticmethod
    def _format_count(value: int | None) -> str:
        return f"{value:,}" if value is not None and value >= 0 else "--"

    @staticmethod
    def _format_bytes(value: int | None) -> str:
        if value is None or value <= 0:
            return "--"
        return f"{value / (1024 * 1024):.1f} MiB"

    def _log_slow_native_frame(
        self,
        *,
        frame_ms: float | None,
        cpu_ms: float | None,
        gpu_ms: float | None,
        draw_calls: int | None,
        visible_submesh_count: int | None,
    ) -> None:
        if frame_ms is None or frame_ms <= _SLOW_FRAME_MS:
            self._last_slow_frame_log_key = None
            return
        key = (
            round(frame_ms, 2),
            round(cpu_ms or 0.0, 2),
            round(gpu_ms or 0.0, 2),
            draw_calls,
            visible_submesh_count,
        )
        if key == self._last_slow_frame_log_key:
            return
        self._last_slow_frame_log_key = key
        parts = [f"Slow native preview frame: {frame_ms:.2f} ms"]
        if cpu_ms is not None and cpu_ms > 0:
            parts.append(f"CPU {cpu_ms:.2f} ms")
        if gpu_ms is not None and gpu_ms > 0:
            parts.append(f"GPU {gpu_ms:.2f} ms")
        if draw_calls is not None:
            parts.append(f"{draw_calls:,} draw call(s)")
        if visible_submesh_count is not None:
            parts.append(f"{visible_submesh_count:,} visible submesh(es)")
        self.append_log(" | ".join(parts))

    def _build_compare_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorComparePanelFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        compare_view_label = QLabel("View", frame)
        compare_view_label.setObjectName("MeshEditorCompareViewLabel")
        self._ui_font_widgets.append(compare_view_label)
        controls.addWidget(compare_view_label)
        self.compare_mode_combo = self._combo("MeshEditorCompareModeCombo", ("Edited", "Source", "Ghost"))
        self.compare_mode_combo.setToolTip("Switch Mesh Editor preview between edited, source, and source ghost overlay modes.")
        self.compare_mode_combo.currentTextChanged.connect(self._compare_view_changed)
        controls.addWidget(self.compare_mode_combo)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.compare_tree = self._tree(("Compare", "Source", "Edited"), "MeshEditorComparePanel")
        layout.addWidget(self.compare_tree, 1)
        return frame

    def update_compare_summary(self, summary: MeshCompareSummary | None) -> None:
        self.compare_tree.clear()
        if summary is None:
            self.compare_tree.addTopLevelItem(QTreeWidgetItem(("Info", "No source comparison.", "")))
            return
        state = "Changed" if summary.changed else "Matching"
        self.compare_tree.addTopLevelItem(
            QTreeWidgetItem(
                (
                    "Summary",
                    f"{summary.original_part_count} parts | {summary.original_vertex_count} verts | {summary.original_face_count} faces",
                    f"{state}: {summary.edited_part_count} parts | {summary.edited_vertex_count} verts | {summary.edited_face_count} faces",
                )
            )
        )
        self.compare_tree.addTopLevelItem(
            QTreeWidgetItem(("Bounds", summary.original_bounds.size_text, summary.edited_bounds.size_text))
        )
        self.compare_tree.addTopLevelItem(
            QTreeWidgetItem(("Scale", f"diag {summary.original_bounds.diagonal:.3f}", summary.scale_text))
        )
        self.compare_tree.addTopLevelItem(
            QTreeWidgetItem(
                (
                    "Orientation",
                    summary.original_bounds.axis_profile_text,
                    f"{summary.edited_bounds.axis_profile_text}{' | axis changed' if summary.orientation_changed else ''}",
                )
            )
        )
        self.compare_tree.addTopLevelItem(
            QTreeWidgetItem(("Materials", "source slots", f"{summary.material_mismatch_count} mismatch(es)"))
        )
        self.compare_tree.addTopLevelItem(
            QTreeWidgetItem(("Textures", "source routes", f"{summary.texture_mismatch_count} mismatch(es)"))
        )
        self.compare_tree.addTopLevelItem(
            QTreeWidgetItem(("UV", "source islands/channels", f"{summary.uv_mismatch_count} mismatch(es)"))
        )
        for part in summary.parts:
            if not part.changed:
                continue
            self.compare_tree.addTopLevelItem(
                QTreeWidgetItem(
                    (
                        part.label,
                        f"{part.original_material or 'missing material'} | {part.original_texture or 'missing texture'}",
                        f"{part.change_text}: {part.edited_material or 'missing material'} | {part.edited_texture or 'missing texture'}",
                    )
                )
            )

    def update_export_validation(self, report: MeshExportValidationReport | None) -> None:
        self.validator_tree.clear()
        self._has_export_validation_report = report is not None
        self._export_validation_ok = bool(report is not None and report.ok)
        copy_button = getattr(self, "copy_validation_report_button", None)
        if copy_button is not None:
            copy_button.setEnabled(
                self._has_editor_target and self._has_export_validation_report and not self._embedded_controls_only
            )
        rebuild_asset_button = getattr(self, "rebuild_asset_button", None)
        if rebuild_asset_button is not None:
            rebuild_asset_button.setEnabled(
                self._has_editor_target and self._export_validation_ok and not self._embedded_controls_only
            )
        if report is None:
            self.validator_tree.addTopLevelItem(QTreeWidgetItem(("Info", "not_run", "No active export validation.")))
            return
        summary = (
            f"{len(report.blockers)} blocker(s), {len(report.warnings)} warning(s), "
            f"{report.submesh_count} part(s), {report.vertex_count} vertex/vertices, {report.face_count} face(s)"
        )
        self.validator_tree.addTopLevelItem(QTreeWidgetItem(("OK" if report.ok else "Blocked", "summary", summary)))
        self._add_validation_status_rows(report)
        if report.parse_confidence:
            self.validator_tree.addTopLevelItem(QTreeWidgetItem(("Info", "parse_confidence", report.parse_confidence)))
        if report.no_op_roundtrip_status:
            roundtrip_bits = [report.no_op_roundtrip_status]
            if report.no_op_byte_identical is not None:
                roundtrip_bits.append("byte-identical yes" if report.no_op_byte_identical else "byte-identical no")
            roundtrip_bits.append(f"unexpected byte changes {report.no_op_unexpected_differences}")
            self.validator_tree.addTopLevelItem(QTreeWidgetItem(("Info", "no_op_roundtrip", " | ".join(roundtrip_bits))))
        for issue in report.issues:
            location = _issue_location(issue.submesh_index, issue.vertex_index, issue.face_index)
            message = f"{issue.message}{' ' + location if location else ''}"
            self.validator_tree.addTopLevelItem(QTreeWidgetItem((issue.severity.title(), issue.code, message)))

    def _add_validation_status_rows(self, report: MeshExportValidationReport) -> None:
        rows = (
            ("Asset hash match", "present" if report.source_asset_hash else "unknown"),
            ("Sidecar status", self._validation_status(report, category="sidecar", ok_text="ready")),
            ("Validation status", "pass" if report.ok else "blocked"),
            ("Topology status", self._validation_status(report, category="topology", code_terms=("topology", "vertex_count", "index_count"), ok_text="safe")),
            ("Bone data status", self._validation_status(report, category="skeleton", code_terms=("bone", "skinning"), ok_text="preserved")),
            ("LOD identity status", self._validation_status(report, code_terms=("lod_identity", "lod_count"), ok_text="preserved")),
            ("Submesh identity status", self._validation_status(report, code_terms=("submesh", "part_count", "stable_id"), ok_text="preserved")),
            ("Rebuild allowed", "yes" if report.ok else "no"),
        )
        for label, value in rows:
            self.validator_tree.addTopLevelItem(QTreeWidgetItem(("Status", label, value)))

    @staticmethod
    def _validation_status(
        report: MeshExportValidationReport,
        *,
        category: str = "",
        code_terms: Sequence[str] = (),
        ok_text: str,
    ) -> str:
        matches = []
        category_key = str(category or "").casefold()
        terms = tuple(str(term).casefold() for term in code_terms)
        for issue in report.issues:
            issue_category = str(getattr(issue, "category", "") or "").casefold()
            issue_code = str(getattr(issue, "code", "") or "").casefold()
            if (category_key and issue_category == category_key) or any(term in issue_code for term in terms):
                matches.append(issue)
        if not matches:
            return ok_text
        blockers = sum(1 for issue in matches if str(getattr(issue, "severity", "") or "").casefold() == "blocker")
        warnings = len(matches) - blockers
        parts = []
        if blockers:
            parts.append(f"{blockers} blocker(s)")
        if warnings:
            parts.append(f"{warnings} warning(s)")
        return ", ".join(parts) or ok_text

    def update_rebuild_report(self, report: object | None) -> None:
        self.rebuild_tree.clear()
        self._has_rebuild_report = report is not None
        self._has_rebuilt_asset_output = bool(str(getattr(report, "output_path", "") or "").strip())
        save_button = getattr(self, "save_rebuild_report_button", None)
        if save_button is not None:
            save_button.setEnabled(
                self._has_editor_target and self._has_rebuild_report and not self._embedded_controls_only
            )
        preview_rebuilt_button = getattr(self, "preview_rebuilt_asset_button", None)
        if preview_rebuilt_button is not None:
            preview_rebuilt_button.setEnabled(
                self._has_editor_target and self._has_rebuilt_asset_output and not self._embedded_controls_only
            )
        package_rebuilt_button = getattr(self, "package_rebuilt_asset_button", None)
        if package_rebuilt_button is not None:
            package_rebuilt_button.setEnabled(
                self._has_editor_target and self._has_rebuilt_asset_output and not self._embedded_controls_only
            )
        if report is None:
            self.rebuild_tree.addTopLevelItem(QTreeWidgetItem(("Status", "No rebuild report.")))
            return
        rows = (
            ("Validation", report.validation_status),
            ("Format", report.mesh_format),
            ("Parse confidence", report.parse_confidence),
            ("Source hash", _short_hash(report.source_asset_hash)),
            ("Rebuilt hash", _short_hash(report.rebuilt_asset_hash)),
            ("Size", f"{report.source_size} -> {report.rebuilt_size} bytes"),
            ("Byte identical", "yes" if report.byte_identical else "no"),
            ("Changed byte ranges", str(report.changed_range_count)),
            ("Edited LODs", _join_report_values(report.edited_lods)),
            ("Edited submeshes", _join_report_values(report.edited_submeshes)),
            ("Changed channels", _join_report_values(report.changed_channels)),
            ("Recomputed fields", _join_report_values(report.recomputed_fields)),
            ("Edit operations", _join_report_values(_rebuild_report_operation_names(report))),
            ("Warnings", _join_report_values(report.warnings)),
            ("Developer overrides", _join_report_values(getattr(report, "developer_overrides", ()))),
            ("Output", report.output_path or "not written"),
        )
        for label, value in rows:
            self.rebuild_tree.addTopLevelItem(QTreeWidgetItem((label, str(value or "none"))))
