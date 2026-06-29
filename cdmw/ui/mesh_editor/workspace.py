"""Standalone Mesh Editor workspace layout."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
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
from cdmw.ui.mesh_editor.actions import MESH_EDITOR_ACTIONS, MeshEditorAction, mesh_editor_actions_by_key
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
_MODE_ACTION_BY_TEXT = {"object": "mode_object", "edit": "mode_edit", "sculpt": "mode_sculpt"}
_SELECTION_ACTION_BY_TEXT = {"vertex": "select_vertex", "edge": "select_edge", "face": "select_face"}
_SKELETON_PANEL_BONE_LIMIT = 512
_SKELETON_PANEL_WEIGHT_LIMIT = 32


class MeshEditorWorkspace(QFrame):
    action_requested = Signal(object)
    native_preview_requested = Signal()
    texture_edit_requested = Signal()
    compare_view_requested = Signal(str)
    skeleton_pose_requested = Signal(str, object)
    part_selection_requested = Signal(int, str)
    part_context_action_requested = Signal(str, int)
    uv_region_selected = Signal(tuple, tuple, str)
    uv_lasso_selected = Signal(tuple, str)

    def __init__(
        self,
        *,
        theme_key: str = "graphite",
        actions: Sequence[MeshEditorAction] = MESH_EDITOR_ACTIONS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MeshEditorStandaloneWorkspace")
        self._actions_by_key = {action.key: action for action in actions}
        self._buttons_by_key: dict[str, QToolButton] = {}
        self._updating_state = False
        self._has_editor_target = False
        self._workspace_summary: MeshWorkspaceSummary | None = None
        self._uv_summary: MeshUvSummary | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)
        root.addWidget(self._build_top_bar())
        root.addWidget(self._build_body(theme_key), 1)
        root.addWidget(self._build_status_strip())

    def button_for_key(self, key: str) -> QToolButton | None:
        return self._buttons_by_key.get(str(key or ""))

    def update_action_state(
        self,
        *,
        has_target: bool,
        selection_empty: bool = True,
        mode: str = "",
        active_selection_mode: str = "",
        undo_count: int = 0,
        redo_count: int = 0,
    ) -> None:
        self._has_editor_target = bool(has_target)
        self.setEnabled(bool(has_target))
        self._sync_combo(self.mode_combo, str(mode or "object"))
        self._sync_combo(self.selection_combo, str(active_selection_mode or "vertex"))
        current_mode = str(mode or "").strip().lower()
        for action in self._actions_by_key.values():
            button = self.button_for_key(action.key)
            if button is None:
                continue
            enabled = bool(has_target)
            if action.mode and action.category != "mode" and action.mode != current_mode:
                enabled = False
            if action.requires_selection and selection_empty:
                enabled = False
            if action.command == "undo" and int(undo_count or 0) <= 0:
                enabled = False
            if action.command == "redo" and int(redo_count or 0) <= 0:
                enabled = False
            button.setEnabled(enabled)
        open_texture_button = getattr(self, "open_texture_button", None)
        if open_texture_button is not None:
            self._sync_part_controls()
        compare_combo = getattr(self, "compare_mode_combo", None)
        if compare_combo is not None:
            compare_combo.setEnabled(bool(has_target))

    def update_session_summary(self, view: MeshEditSessionView | None, *, mesh_label: str = "") -> None:
        if view is None:
            self.outliner.clear()
            self.outliner.addTopLevelItem(QTreeWidgetItem(("No mesh", "0", "")))
            self.properties_tree.clear()
            self.properties_tree.addTopLevelItem(QTreeWidgetItem(("Session", "none")))
            self.history_list.clear()
            self.history_list.addItem("No history")
            self.skeleton_tree.clear()
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("No skeleton", "")))
            return
        label = str(mesh_label or view.session_id or "mesh")
        self.outliner.clear()
        self.outliner.addTopLevelItem(QTreeWidgetItem((label, "", str(view.revision))))
        self.properties_tree.clear()
        for key, value in (
            ("Session", view.session_id),
            ("Mode", view.mode),
            ("Revision", view.revision),
            ("Undo", view.undo_count),
            ("Redo", view.redo_count),
        ):
            self.properties_tree.addTopLevelItem(QTreeWidgetItem((str(key), str(value))))
        self.history_list.clear()
        self.history_list.addItems((f"Undo: {int(view.undo_count or 0)}", f"Redo: {int(view.redo_count or 0)}"))

    def update_workspace_summary(self, summary: MeshWorkspaceSummary | None) -> None:
        self._workspace_summary = summary
        if summary is None:
            self.outliner.clear()
            self.outliner.addTopLevelItem(QTreeWidgetItem(("No mesh", "0", "")))
            self.material_tree.clear()
            self.material_tree.addTopLevelItem(QTreeWidgetItem(("No material", "", "")))
            self.uv_tree.clear()
            self.uv_tree.addTopLevelItem(QTreeWidgetItem(("No UV data", "")))
            self.uv_canvas.set_uv_summary(None)
            self.skeleton_tree.clear()
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("No skeleton", "")))
            self._sync_part_controls()
            return
        self.outliner.clear()
        self.material_tree.clear()
        self.uv_tree.clear()
        self.skeleton_tree.clear()
        for part in summary.parts:
            selected = "*" if part.selected else ""
            outliner_item = QTreeWidgetItem(
                (
                    f"{selected}{part.index}: {part.name}",
                    f"{part.face_count}",
                    f"{part.vertex_count} verts",
                )
            )
            self._configure_part_item(outliner_item, part.index, part.selected)
            self.outliner.addTopLevelItem(outliner_item)
            material_slot = str(part.material_slot_index) if part.material_slot_index >= 0 else ""
            texture_note = part.texture or "missing texture"
            if part.source_texture_set_key:
                texture_note = f"{texture_note} | set={part.source_texture_set_key}"
            material_item = QTreeWidgetItem(
                (
                    f"{selected}{part.index}: {part.material or 'missing material'}",
                    texture_note,
                    material_slot or part.material_slot_kind,
                )
            )
            self._configure_part_item(material_item, part.index, part.selected)
            self.material_tree.addTopLevelItem(material_item)
            self.uv_tree.addTopLevelItem(
                QTreeWidgetItem(
                    (
                        f"{part.index}: {part.name}",
                        f"UV {part.uv_coverage} | normal {part.normal_coverage} | tangent {part.tangent_coverage}",
                    )
                )
            )
            if part.has_skinning:
                self.skeleton_tree.addTopLevelItem(QTreeWidgetItem((f"{part.index}: {part.name}", "weighted part")))
        if not summary.parts:
            self.outliner.addTopLevelItem(QTreeWidgetItem(("No mesh", "0", "")))
        if self.skeleton_tree.topLevelItemCount() <= 0:
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("No skeleton", "")))
        self._sync_part_controls()

    def update_uv_summary(self, summary: MeshUvSummary | None) -> None:
        self._uv_summary = summary
        self.uv_canvas.set_uv_summary(summary)
        self.uv_tree.clear()
        workspace_summary = self._workspace_summary
        if workspace_summary is not None:
            for part in workspace_summary.parts:
                self.uv_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            f"{part.index}: {part.name}",
                            f"UV {part.uv_coverage} | normal {part.normal_coverage} | tangent {part.tangent_coverage}",
                        )
                    )
                )
        if summary is None:
            if self.uv_tree.topLevelItemCount() <= 0:
                self.uv_tree.addTopLevelItem(QTreeWidgetItem(("No UV data", "")))
            return
        if not summary.islands:
            self.uv_tree.addTopLevelItem(QTreeWidgetItem(("No UV islands", "0 connected islands")))
            return
        for island in summary.islands:
            selected = "*" if island.selected else ""
            texture = island.texture or "missing texture"
            self.uv_tree.addTopLevelItem(
                QTreeWidgetItem(
                    (
                        f"{selected}Island {island.index} | part {island.submesh_index}: {island.part_name}",
                        f"{island.vertex_count} verts | {island.face_count} faces | {island.bounds_text} | {texture}",
                    )
                )
            )

    def update_skeleton_summary(self, summary: MeshSkeletonSummary | None) -> None:
        self.skeleton_tree.clear()
        self._sync_skeleton_pose_controls(summary)
        if summary is None or not (summary.skinned or summary.skeleton_linked or summary.bones):
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("No skeleton", "")))
            return
        metadata = "linked" if summary.skeleton_linked else "missing metadata"
        if summary.skeleton_source:
            metadata = f"linked: {summary.skeleton_source}"
        elif summary.skeleton_bone_count is not None:
            metadata = f"linked: {summary.skeleton_bone_count} bones"
        self.skeleton_tree.addTopLevelItem(
            QTreeWidgetItem(
                (
                    "Summary",
                    (
                        f"{metadata} | inferred {summary.inferred_bone_count} bones | "
                        f"{summary.weighted_part_count}/{summary.part_count} weighted parts | "
                        f"{summary.weighted_vertex_count}/{summary.vertex_count} weighted vertices"
                    ),
                )
            )
        )
        resolver_bits = [
            f"descriptor {summary.skeleton_descriptor_source}" if summary.skeleton_descriptor_source else "",
            f"variation {summary.skeleton_variation_source}" if summary.skeleton_variation_source else "",
            f"constraint {summary.animation_constraint_source}" if summary.animation_constraint_source else "",
            f"sockets {summary.socket_source}" if summary.socket_source else "",
        ]
        resolver_text = " | ".join(bit for bit in resolver_bits if bit)
        if resolver_text:
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("Resolver", resolver_text)))
        rig_metadata_bits = [
            f"PABC {summary.skeleton_variation_status}" if summary.skeleton_variation_status else "",
            f"PAPR {summary.animation_constraint_status}" if summary.animation_constraint_status else "",
        ]
        rig_metadata_text = " | ".join(bit for bit in rig_metadata_bits if bit)
        if rig_metadata_text:
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("Rig Metadata", rig_metadata_text)))
        constraint_evidence = summary.animation_constraint_evidence
        if constraint_evidence.recognized:
            solver_text = "solver enabled" if constraint_evidence.solver_supported else "solver blocked"
            status_text = constraint_evidence.status or "read_only_constraint_evidence"
            self.skeleton_tree.addTopLevelItem(
                QTreeWidgetItem(
                    (
                        "Constraint Evidence",
                        (
                            f"{status_text} | {constraint_evidence.string_evidence_count} strings | "
                            f"{constraint_evidence.record_candidate_count} record candidates | "
                            f"{constraint_evidence.related_physics_count} physics refs | {solver_text}"
                        ),
                    )
                )
            )
            if constraint_evidence.candidate_family_counts:
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            "Constraint Families",
                            _constraint_counts_text(constraint_evidence.candidate_family_counts),
                        )
                    )
                )
            for family, status, readiness_rows in constraint_evidence.family_readiness_rows[:6]:
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            f"Constraint Family: {family}",
                            _constraint_solver_readiness_text(status, readiness_rows),
                        )
                    )
                )
            if constraint_evidence.bone_match_counts:
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            "Constraint Bone Matches",
                            _constraint_bone_match_counts_text(
                                constraint_evidence.bone_match_candidate_count,
                                constraint_evidence.bone_match_counts,
                            ),
                        )
                    )
                )
            if constraint_evidence.expression_counts or constraint_evidence.expression_numeric_value_count:
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            "Constraint Expressions",
                            _constraint_expression_evidence_text(
                                constraint_evidence.expression_status,
                                constraint_evidence.expression_token_confidence,
                                constraint_evidence.expression_semantics_confidence,
                                constraint_evidence.expression_counts,
                                constraint_evidence.expression_syntax_signature_counts,
                                constraint_evidence.expression_numeric_value_count,
                            ),
                        )
                    )
                )
            if constraint_evidence.field_offset_counts:
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            "Constraint Field Offsets",
                            _constraint_field_offset_text(
                                constraint_evidence.field_offset_status,
                                constraint_evidence.field_offset_confidence,
                                constraint_evidence.field_offset_record_confidence,
                                constraint_evidence.field_offset_counts,
                            ),
                        )
                    )
                )
            if constraint_evidence.numeric_match_count or constraint_evidence.numeric_match_role_counts:
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            "Constraint Numeric Matches",
                            _constraint_numeric_match_text(
                                constraint_evidence.numeric_match_count,
                                constraint_evidence.numeric_match_status_counts,
                                constraint_evidence.numeric_match_role_counts,
                                constraint_evidence.numeric_match_storage_counts,
                                constraint_evidence.numeric_match_pair_counts,
                                constraint_evidence.numeric_match_value_confidence_counts,
                                constraint_evidence.numeric_match_family_counts,
                                constraint_evidence.numeric_match_family_row_counts,
                                constraint_evidence.numeric_match_family_role_counts,
                                constraint_evidence.numeric_match_family_pair_counts,
                                constraint_evidence.numeric_match_family_value_confidence_counts,
                                constraint_evidence.numeric_match_signature_counts,
                                constraint_evidence.numeric_match_candidate_relative_signature_counts,
                                constraint_evidence.numeric_match_previous_delta_counts,
                                constraint_evidence.numeric_match_next_delta_counts,
                                constraint_evidence.numeric_match_candidate_relative_offset_counts,
                                constraint_evidence.numeric_match_min_previous_delta,
                                constraint_evidence.numeric_match_max_previous_delta,
                                constraint_evidence.numeric_match_min_next_delta,
                                constraint_evidence.numeric_match_max_next_delta,
                                constraint_evidence.numeric_match_min_candidate_relative_offset,
                                constraint_evidence.numeric_match_max_candidate_relative_offset,
                                constraint_evidence.numeric_match_offset_confidence,
                                constraint_evidence.numeric_match_candidate_relative_offset_confidence,
                            ),
                        )
                    )
                )
            if constraint_evidence.solver_readiness_counts:
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            "Constraint Solver Readiness",
                            _constraint_solver_readiness_text(
                                constraint_evidence.solver_readiness_status,
                                constraint_evidence.solver_readiness_counts,
                            ),
                        )
                    )
                )
            for role, count in constraint_evidence.role_counts[:6]:
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem((f"Constraint: {role}", f"{count} readable string(s) | role inferred"))
                )
            for candidate in constraint_evidence.record_candidates:
                context_bits = [
                    _constraint_bone_label("target", candidate.target_bone, candidate.target_bone_index, candidate.target_bone_confidence),
                    _constraint_bone_label("helper", candidate.helper_bone, candidate.helper_bone_index, candidate.helper_bone_confidence),
                    _constraint_bone_label("parent", candidate.parent_bone, candidate.parent_bone_index, candidate.parent_bone_confidence),
                ]
                context_text = " | ".join(bit for bit in context_bits if bit) or "target unknown"
                expression = candidate.expression
                if len(expression) > 96:
                    expression = f"{expression[:93]}..."
                token_text = _constraint_candidate_token_text(candidate)
                field_offset_text = _constraint_candidate_field_offset_text(candidate)
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            f"Constraint Candidate: {candidate.offset_text}",
                            (
                                f"disabled | {candidate.constraint_type} | {context_text} | "
                                f"expr {expression}"
                                f"{f' | {token_text}' if token_text else ''} | "
                                f"{f'{field_offset_text} | ' if field_offset_text else ''}"
                                f"record {candidate.record_confidence} | {candidate.solver_status}"
                            ),
                        )
                    )
                )
            if constraint_evidence.proof_gap:
                self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("Constraint Gap", constraint_evidence.proof_gap)))
        for row in summary.authoring_status_rows:
            detail = f"{row.state} | {row.confidence}"
            if row.detail:
                detail = f"{detail} | {row.detail}"
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem((f"Authoring: {row.feature}", detail)))
        if summary.animation_status:
            playback = summary.animation_playback
            blocker_text = "; ".join(summary.animation_blockers[:2])
            playback_text = ""
            if playback.ready:
                source_text = f" | {playback.source}" if playback.source else ""
                timing_text = f" | timing {playback.timing_status or playback.timing_confidence}"
                if playback.game_accurate_timing:
                    timing_text = f"{timing_text} | game accurate"
                segment_text = (
                    f" | {playback.sequence_segment_count} segment(s)" if playback.sequence_segment_count else ""
                )
                if playback.active_sequence_lane_index >= 0:
                    segment_text = f"{segment_text} | lane {playback.active_sequence_lane_index}"
                if playback.active_sequence_status:
                    segment_text = f"{segment_text} | {playback.active_sequence_status}"
                playback_text = f" | {playback.track_count} tracks{segment_text} | {playback.time_text}{source_text}{timing_text}"
            self.skeleton_tree.addTopLevelItem(
                QTreeWidgetItem(
                    (
                        "Animation",
                        f"{summary.animation_status} | playback {'ready' if summary.animation_playback_ready else 'blocked'}"
                        f"{playback_text}{' | ' + blocker_text if blocker_text else ''}",
                    )
                )
            )
        pose = summary.pose
        if pose.enabled or pose.selected_bone_index >= 0 or pose.posed_bone_count:
            selected = pose.selected_bone_name or "none"
            if pose.selected_bone_index >= 0:
                selected = f"{pose.selected_bone_index}: {selected}"
            self.skeleton_tree.addTopLevelItem(
                QTreeWidgetItem(
                    (
                        "Pose",
                        (
                            f"{'on' if pose.enabled else 'off'} | selected {selected} | "
                            f"rot {pose.rotation_text} | posed {pose.posed_bone_count}"
                        ),
                    )
                )
            )
        if summary.invalid_row_count or summary.unnormalized_vertex_count:
            self.skeleton_tree.addTopLevelItem(
                QTreeWidgetItem(
                    (
                        "Validation",
                        f"{summary.invalid_row_count} invalid rows | {summary.unnormalized_vertex_count} unnormalized vertices",
                    )
                )
            )
        if summary.selected_vertex_weights:
            self.skeleton_tree.addTopLevelItem(
                QTreeWidgetItem(
                    (
                        "Weights",
                        f"{len(summary.selected_vertex_weights)} selected vertices | bone {pose.selected_bone_index}: {pose.selected_bone_name or 'selected'}",
                    )
                )
            )
            bone_names = {bone.index: bone.name for bone in summary.bones}
            for weight in summary.selected_vertex_weights[:_SKELETON_PANEL_WEIGHT_LIMIT]:
                selected_name = pose.selected_bone_name or bone_names.get(pose.selected_bone_index, "")
                detail = (
                    f"selected {pose.selected_bone_index}{' ' + selected_name if selected_name else ''}: "
                    f"{weight.selected_bone_weight:.3f} | total {weight.total_weight:.3f} | {weight.influences_text}"
                )
                if weight.invalid:
                    detail = f"{detail} | invalid"
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem((f"Weight {weight.submesh_index}:{weight.vertex_index}", detail))
                )
            if len(summary.selected_vertex_weights) > _SKELETON_PANEL_WEIGHT_LIMIT:
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            "Weights truncated",
                            f"showing first {_SKELETON_PANEL_WEIGHT_LIMIT} of {len(summary.selected_vertex_weights)} selected vertices",
                        )
                    )
                )
        if summary.bones:
            parser_note = f" | parser {summary.skeleton_parser_mode}" if summary.skeleton_parser_mode else ""
            self.skeleton_tree.addTopLevelItem(
                QTreeWidgetItem(
                    (
                        "Bones",
                        f"{len(summary.bones)} bones | {summary.root_bone_count} roots | depth {summary.max_depth}{parser_note}",
                    )
                )
            )
            for bone in summary.bones[:_SKELETON_PANEL_BONE_LIMIT]:
                indent = "  " * min(max(0, int(bone.depth or 0)), 12)
                selected = "*" if bone.index == summary.pose.selected_bone_index else ""
                parent = bone.parent_name or "root"
                position = f" | pos {bone.position_text}" if bone.position_text else ""
                item = QTreeWidgetItem(
                    (
                        f"{indent}{selected}{bone.index}: {bone.name}",
                        f"parent {parent} | children {bone.child_count}{position}",
                    )
                )
                item.setData(0, Qt.ItemDataRole.UserRole, bone.index)
                self.skeleton_tree.addTopLevelItem(item)
            if len(summary.bones) > _SKELETON_PANEL_BONE_LIMIT:
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            "Truncated",
                            f"showing first {_SKELETON_PANEL_BONE_LIMIT} of {len(summary.bones)} bones",
                        )
                    )
                )
        for part in summary.parts:
            if not part.skinned:
                continue
            selected = "*" if part.selected else ""
            detail = (
                f"{part.weighted_vertex_count}/{part.vertex_count} weighted | "
                f"{part.bone_count} bones | max influences {part.max_influences}"
            )
            if part.invalid_row_count or part.unnormalized_vertex_count:
                detail = f"{detail} | invalid {part.invalid_row_count} | unnormalized {part.unnormalized_vertex_count}"
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem((f"{selected}{part.index}: {part.name}", detail)))
        if self.skeleton_tree.topLevelItemCount() <= 1 and not any(part.skinned for part in summary.parts):
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("No skinned parts", "")))

    def append_log(self, message: str) -> None:
        text = str(message or "").strip()
        if text:
            self.log_list.addItem(text)
            self.log_list.scrollToBottom()

    def _build_top_bar(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorTopModeBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.mode_combo = self._combo("MeshEditorModeCombo", ("Object", "Edit", "Sculpt"))
        self.selection_combo = self._combo("MeshEditorSelectionCombo", ("Vertex", "Edge", "Face"))
        self.snap_combo = self._combo("MeshEditorSnapModeCombo", ("Off", "Grid", "Vertex", "Pixel"))
        self.pivot_combo = self._combo("MeshEditorPivotCombo", ("Median", "Center", "Cursor", "Individual"))
        self.orientation_combo = self._combo("MeshEditorOrientationCombo", ("Global", "Local", "Normal", "View"))
        for label_text, widget in (
            ("Mode", self.mode_combo),
            ("Select", self.selection_combo),
            ("Snap", self.snap_combo),
            ("Pivot", self.pivot_combo),
            ("Orient", self.orientation_combo),
        ):
            label = QLabel(label_text, frame)
            label.setObjectName(f"{widget.objectName()}Label")
            layout.addWidget(label)
            layout.addWidget(widget)
        layout.addStretch(1)
        self.mode_combo.currentTextChanged.connect(self._mode_changed)
        self.selection_combo.currentTextChanged.connect(self._selection_changed)
        return frame

    def _build_body(self, theme_key: str) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName("MeshEditorWorkspaceBody")
        splitter.addWidget(self._build_left_palette())
        splitter.addWidget(self._build_preview_area(theme_key))
        splitter.addWidget(self._build_right_panels())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes((190, 900, 340))
        return splitter

    def _build_left_palette(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorLeftToolPalette")
        frame.setMinimumWidth(168)
        frame.setMaximumWidth(230)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.left_tool_pages = QTabWidget(frame)
        self.left_tool_pages.setObjectName("MeshEditorLeftToolPages")
        self.left_tool_pages.setTabPosition(QTabWidget.TabPosition.North)
        for title, categories in _LEFT_TOOL_PAGES:
            page = self._build_left_tool_page(title, categories)
            self.left_tool_pages.addTab(page, title)
        layout.addWidget(self.left_tool_pages, 1)
        return frame

    def _build_left_tool_page(self, title: str, categories: Sequence[str]) -> QWidget:
        page = QFrame(self)
        page.setObjectName(f"MeshEditorLeftToolPage_{title.replace(' ', '')}")
        layout = QGridLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setHorizontalSpacing(4)
        layout.setVerticalSpacing(4)
        row = 0
        if str(title).strip().lower() == "rig":
            row = self._add_rig_palette_controls(page, layout, row)
        for category in categories:
            category_actions = tuple(action for action in self._actions_by_key.values() if action.category == category)
            if not category_actions:
                continue
            label = QLabel(_LEFT_CATEGORY_LABELS.get(category, category.title()), page)
            label.setObjectName(f"MeshEditorToolCategory_{category}")
            layout.addWidget(label, row, 0, 1, 3)
            row += 1
            for index, action in enumerate(category_actions):
                button = self._workspace_action_button(page, action)
                layout.addWidget(button, row + index // 3, index % 3)
            row += (len(category_actions) + 2) // 3
        layout.setRowStretch(row, 1)
        return page

    def _workspace_action_button(self, parent: QWidget, action: MeshEditorAction) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName(f"MeshEditorWorkspaceAction_{action.key}")
        button.setText(action.text)
        button.setAccessibleName(action.text)
        button.setIcon(mesh_editor_action_icon(action.icon_key, self.palette()))
        button.setIconSize(QSize(18, 18))
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setToolTip(_workspace_action_tooltip(action))
        button.setProperty("meshEditorActionKey", action.key)
        button.setAutoRaise(True)
        button.setFixedSize(42, 36)
        button.clicked.connect(lambda _checked=False, current=action: self.action_requested.emit(current))
        self._buttons_by_key[action.key] = button
        return button

    def _add_rig_palette_controls(self, parent: QWidget, layout: QGridLayout, row: int) -> int:
        label = QLabel("Character Preview", parent)
        label.setObjectName("MeshEditorToolCategory_rig")
        layout.addWidget(label, row, 0, 1, 3)
        row += 1
        self.rig_skeleton_button = self._rig_palette_button(
            parent,
            "MeshEditorRigSkeletonButton",
            "Skeleton",
            "select_edge",
            "Open the Skeleton panel.",
        )
        self.rig_skeleton_button.clicked.connect(lambda _checked=False: self._focus_right_panel("Skeleton"))
        layout.addWidget(self.rig_skeleton_button, row, 0)
        self.rig_pose_button = self._rig_palette_button(
            parent,
            "MeshEditorRigPosePreviewButton",
            "Pose",
            "transform_rotate",
            "Toggle skinned pose preview.",
            checkable=True,
        )
        self.rig_pose_button.clicked.connect(
            lambda checked=False: self.skeleton_pose_requested.emit("set_pose_preview", bool(checked))
        )
        layout.addWidget(self.rig_pose_button, row, 1)
        self.rig_weight_transfer_button = self._rig_palette_button(
            parent,
            "MeshEditorRigWeightTransferButton",
            "Transfer W",
            "select_vertex",
            "Transfer selected vertex weights from the source mesh.",
        )
        self.rig_weight_transfer_button.clicked.connect(
            lambda _checked=False: self.skeleton_pose_requested.emit("transfer_selected_vertex_weights_from_source", None)
        )
        layout.addWidget(self.rig_weight_transfer_button, row, 2)
        row += 1
        self.rig_weight_normalize_button = self._rig_palette_button(
            parent,
            "MeshEditorRigWeightNormalizeButton",
            "Norm W",
            "select_vertex",
            "Normalize selected vertex weights.",
        )
        self.rig_weight_normalize_button.clicked.connect(
            lambda _checked=False: self.skeleton_pose_requested.emit("normalize_selected_vertex_weights", None)
        )
        layout.addWidget(self.rig_weight_normalize_button, row, 0)
        return row + 1

    def _rig_palette_button(
        self,
        parent: QWidget,
        object_name: str,
        text: str,
        icon_key: str,
        tooltip: str,
        *,
        checkable: bool = False,
    ) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName(object_name)
        button.setText(text)
        button.setAccessibleName(text)
        button.setToolTip(tooltip)
        button.setIcon(mesh_editor_action_icon(icon_key, self.palette()))
        button.setIconSize(QSize(18, 18))
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setAutoRaise(True)
        button.setCheckable(checkable)
        button.setEnabled(False)
        button.setFixedSize(42, 36)
        return button

    def _build_preview_area(self, theme_key: str) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorCentralPreview")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.preview_stack = QStackedWidget(frame)
        self.preview_stack.setObjectName("MeshEditorStandalonePreviewStack")
        self.native_host_frame = NativeD3D11PreviewHostFrame(frame)
        self.native_host_frame.setObjectName("MeshEditorStandaloneNativeD3D11Host")
        self.preview = NativePreviewPanel("Mesh Editor preview.", theme_key=theme_key)
        self.preview.setObjectName("MeshEditorStandalonePreview")
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview_stack.addWidget(self.native_host_frame)
        self.preview_stack.addWidget(self.preview)
        self.preview_stack.setCurrentWidget(self.preview)
        layout.addWidget(self.preview_stack, 1)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.native_preview_button = QPushButton("D3D11", frame)
        self.native_preview_button.setObjectName("MeshEditorStandaloneNativePreviewButton")
        self.native_preview_button.setToolTip("Start native D3D11 preview.")
        self.native_preview_button.setMinimumHeight(28)
        self.native_preview_button.clicked.connect(self.native_preview_requested.emit)
        controls.addWidget(self.native_preview_button)
        self.native_part_pick_status_label = QLabel("Part pick: preview off", frame)
        self.native_part_pick_status_label.setObjectName("MeshEditorNativePartPickStatus")
        self.native_part_pick_status_label.setProperty("nativePartPickingAvailable", False)
        controls.addWidget(self.native_part_pick_status_label)
        self.preview_skeleton_button = QToolButton(frame)
        self.preview_skeleton_button.setObjectName("MeshEditorPreviewSkeletonButton")
        self.preview_skeleton_button.setText("Skeleton")
        self.preview_skeleton_button.setAccessibleName("Show skeleton preview")
        self.preview_skeleton_button.setToolTip("Open Skeleton panel and reload native preview with skeleton overlay metadata.")
        self.preview_skeleton_button.setIcon(mesh_editor_action_icon("select_edge", self.palette()))
        self.preview_skeleton_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.preview_skeleton_button.setEnabled(False)
        self.preview_skeleton_button.clicked.connect(self._request_skeleton_native_preview)
        controls.addWidget(self.preview_skeleton_button)
        self.preview_pose_button = QToolButton(frame)
        self.preview_pose_button.setObjectName("MeshEditorPreviewPoseButton")
        self.preview_pose_button.setText("Pose")
        self.preview_pose_button.setAccessibleName("Toggle pose preview")
        self.preview_pose_button.setToolTip("Toggle skinned pose preview deformation.")
        self.preview_pose_button.setIcon(mesh_editor_action_icon("transform_rotate", self.palette()))
        self.preview_pose_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.preview_pose_button.setCheckable(True)
        self.preview_pose_button.setEnabled(False)
        self.preview_pose_button.clicked.connect(
            lambda checked=False: self.skeleton_pose_requested.emit("set_pose_preview", bool(checked))
        )
        controls.addWidget(self.preview_pose_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        return frame

    def _build_right_panels(self) -> QTabWidget:
        tabs = QTabWidget(self)
        tabs.setObjectName("MeshEditorRightPanels")
        tabs.setMinimumWidth(300)
        tabs.setMaximumWidth(430)
        self.right_panels = tabs
        self.outliner = self._tree(("Part", "Faces", "Rev"), "MeshEditorOutlinerPanel")
        self._configure_part_tree(self.outliner)
        self.properties_tree = self._tree(("Property", "Value"), "MeshEditorPropertiesPanel")
        uv_panel = self._build_uv_panel()
        material_panel = self._build_material_panel()
        compare_panel = self._build_compare_panel()
        self.validator_tree = self._tree(("Severity", "Code", "Message"), "MeshEditorValidatorPanel")
        self.history_list = QListWidget(tabs)
        self.history_list.setObjectName("MeshEditorHistoryPanel")
        skeleton_panel = self._build_skeleton_panel()
        for widget, title in (
            (self.outliner, "Outliner"),
            (self.properties_tree, "Properties"),
            (skeleton_panel, "Skeleton"),
            (uv_panel, "UV"),
            (material_panel, "Parts & Routing"),
            (compare_panel, "Compare"),
            (self.validator_tree, "Validator"),
            (self.history_list, "History"),
        ):
            tabs.addTab(widget, title)
        self.update_session_summary(None)
        self.update_workspace_summary(None)
        self.update_uv_summary(None)
        self.update_export_validation(None)
        self.update_compare_summary(None)
        self.update_skeleton_summary(None)
        return tabs

    def _focus_right_panel(self, title: str) -> None:
        tabs = getattr(self, "right_panels", None)
        if tabs is None:
            return
        normalized = str(title or "").strip().lower()
        for index in range(tabs.count()):
            if tabs.tabText(index).strip().lower() == normalized:
                tabs.setCurrentIndex(index)
                return

    def _request_skeleton_native_preview(self) -> None:
        self._focus_right_panel("Skeleton")
        self.native_preview_requested.emit()

    def _build_uv_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorUVPanelFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.uv_canvas = MeshUvCanvas(frame)
        self.uv_canvas.region_selected.connect(self.uv_region_selected.emit)
        self.uv_canvas.lasso_selected.connect(self.uv_lasso_selected.emit)
        layout.addWidget(self.uv_canvas)
        self.uv_tree = self._tree(("UV", "Value"), "MeshEditorUVPanel")
        layout.addWidget(self.uv_tree, 1)
        return frame

    def _build_skeleton_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorSkeletonPanelFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)
        self.pose_preview_button = self._skeleton_pose_button("MeshEditorPosePreviewButton", "Pose", "toggle", checkable=True)
        self.pose_preview_button.clicked.connect(
            lambda checked=False: self.skeleton_pose_requested.emit("set_pose_preview", bool(checked))
        )
        controls.addWidget(self.pose_preview_button)
        for object_name, attr_name, text, rotation in (
            ("MeshEditorPoseRotateXButton", "pose_rotate_x_button", "Rot X", (15.0, 0.0, 0.0)),
            ("MeshEditorPoseRotateYButton", "pose_rotate_y_button", "Rot Y", (0.0, 15.0, 0.0)),
            ("MeshEditorPoseRotateZButton", "pose_rotate_z_button", "Rot Z", (0.0, 0.0, 15.0)),
        ):
            button = self._skeleton_pose_button(object_name, text, "transform_rotate")
            setattr(self, attr_name, button)
            button.clicked.connect(
                lambda _checked=False, current=rotation: self.skeleton_pose_requested.emit("rotate_selected_bone", current)
            )
            controls.addWidget(button)
        self.pose_reset_button = self._skeleton_pose_button("MeshEditorPoseResetButton", "Reset", "undo")
        self.pose_reset_button.clicked.connect(lambda _checked=False: self.skeleton_pose_requested.emit("reset_pose", None))
        controls.addWidget(self.pose_reset_button)
        self.animation_play_button = self._skeleton_pose_button("MeshEditorAnimationPlayButton", "Play", "transform_rotate", checkable=True)
        self.animation_play_button.clicked.connect(
            lambda checked=False: self.skeleton_pose_requested.emit("set_animation_playback", bool(checked))
        )
        controls.addWidget(self.animation_play_button)
        self.animation_step_button = self._skeleton_pose_button("MeshEditorAnimationStepButton", "Step", "redo")
        self.animation_step_button.clicked.connect(lambda _checked=False: self.skeleton_pose_requested.emit("step_animation_frame", 1))
        controls.addWidget(self.animation_step_button)
        self.animation_rewind_button = self._skeleton_pose_button("MeshEditorAnimationRewindButton", "Rewind", "undo")
        self.animation_rewind_button.clicked.connect(lambda _checked=False: self.skeleton_pose_requested.emit("seek_animation", 0.0))
        controls.addWidget(self.animation_rewind_button)
        self.animation_loop_button = self._skeleton_pose_button("MeshEditorAnimationLoopButton", "Loop", "toggle", checkable=True)
        self.animation_loop_button.clicked.connect(
            lambda checked=False: self.skeleton_pose_requested.emit("set_animation_loop", bool(checked))
        )
        controls.addWidget(self.animation_loop_button)
        self.animation_speed_combo = QComboBox(frame)
        self.animation_speed_combo.setObjectName("MeshEditorAnimationSpeedCombo")
        for label, value in (("0.25x", 0.25), ("0.5x", 0.5), ("1x", 1.0), ("2x", 2.0), ("4x", 4.0)):
            self.animation_speed_combo.addItem(label, value)
        self.animation_speed_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.animation_speed_combo.currentIndexChanged.connect(self._animation_speed_changed)
        controls.addWidget(self.animation_speed_combo)
        self.animation_scrub_slider = QSlider(Qt.Orientation.Horizontal, frame)
        self.animation_scrub_slider.setObjectName("MeshEditorAnimationScrubSlider")
        self.animation_scrub_slider.setRange(0, 1000)
        self.animation_scrub_slider.setFixedWidth(120)
        self.animation_scrub_slider.valueChanged.connect(self._animation_scrub_changed)
        controls.addWidget(self.animation_scrub_slider)
        for object_name, attr_name, text, command, payload in (
            ("MeshEditorWeightIncreaseButton", "weight_increase_button", "W+", "adjust_selected_vertex_bone_weight", 0.1),
            ("MeshEditorWeightDecreaseButton", "weight_decrease_button", "W-", "adjust_selected_vertex_bone_weight", -0.1),
            ("MeshEditorWeightNormalizeButton", "weight_normalize_button", "Norm W", "normalize_selected_vertex_weights", None),
            ("MeshEditorWeightTransferButton", "weight_transfer_button", "Transfer W", "transfer_selected_vertex_weights_from_source", None),
        ):
            button = self._skeleton_pose_button(object_name, text, "select_vertex")
            setattr(self, attr_name, button)
            button.clicked.connect(
                lambda _checked=False, current_command=command, current_payload=payload: self.skeleton_pose_requested.emit(
                    current_command,
                    current_payload,
                )
            )
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.skeleton_tree = self._tree(("Skeleton", "Value"), "MeshEditorSkeletonPanel")
        self.skeleton_tree.itemClicked.connect(self._skeleton_tree_item_clicked)
        layout.addWidget(self.skeleton_tree, 1)
        return frame

    def _skeleton_pose_button(
        self,
        object_name: str,
        text: str,
        icon_key: str,
        *,
        checkable: bool = False,
    ) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName(object_name)
        button.setText(text)
        button.setAccessibleName(text)
        button.setIcon(mesh_editor_action_icon(icon_key, self.palette()))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setAutoRaise(True)
        button.setCheckable(checkable)
        button.setEnabled(False)
        return button

    def _build_material_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorMaterialPanelFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.part_selection_summary_label = QLabel("Selected parts: no mesh.", frame)
        self.part_selection_summary_label.setObjectName("MeshEditorPartSelectionSummary")
        self.part_selection_summary_label.setWordWrap(True)
        layout.addWidget(self.part_selection_summary_label)

        selection_controls = QHBoxLayout()
        selection_controls.setContentsMargins(0, 0, 0, 0)
        selection_controls.setSpacing(4)
        self.part_select_all_button = self._part_control_button(
            frame,
            "MeshEditorPartSelectAllButton",
            "All",
            "select_face",
            "Select all mesh parts.",
            lambda _checked=False: self.part_selection_requested.emit(-1, "select_all"),
        )
        self.part_clear_selection_button = self._part_control_button(
            frame,
            "MeshEditorPartClearSelectionButton",
            "Clear",
            "delete",
            "Clear selected mesh parts.",
            lambda _checked=False: self.part_selection_requested.emit(-1, "clear"),
        )
        self.part_invert_selection_button = self._part_control_button(
            frame,
            "MeshEditorPartInvertSelectionButton",
            "Invert",
            "toggle",
            "Invert selected mesh parts.",
            lambda _checked=False: self.part_selection_requested.emit(-1, "invert"),
        )
        for button in (self.part_select_all_button, self.part_clear_selection_button, self.part_invert_selection_button):
            selection_controls.addWidget(button)
        selection_controls.addStretch(1)
        layout.addLayout(selection_controls)

        action_grid = QGridLayout()
        action_grid.setContentsMargins(0, 0, 0, 0)
        action_grid.setHorizontalSpacing(4)
        action_grid.setVerticalSpacing(4)
        self.part_clone_button = self._part_action_button(
            frame, "MeshEditorPartCloneButton", "Clone", "duplicate", "Clone selected part(s).", "duplicate"
        )
        self.part_delete_button = self._part_action_button(
            frame, "MeshEditorPartDeleteButton", "Delete", "delete", "Delete selected part(s).", "delete"
        )
        self.part_recalculate_normals_button = self._part_action_button(
            frame,
            "MeshEditorPartRecalculateNormalsButton",
            "Recalc",
            "recalculate_normals",
            "Recalculate normals for selected part(s).",
            "recalculate_normals",
        )
        self.part_flip_normals_button = self._part_action_button(
            frame,
            "MeshEditorPartFlipNormalsButton",
            "Flip",
            "flip_normals",
            "Flip normals for selected part(s).",
            "flip_normals",
        )
        self.open_texture_button = QToolButton(frame)
        self.open_texture_button.setObjectName("MeshEditorOpenTextureButton")
        self.open_texture_button.setText("Texture")
        self.open_texture_button.setAccessibleName("Open selected texture")
        self.open_texture_button.setToolTip("Open selected material texture in Texture Editor.")
        self.open_texture_button.setIcon(mesh_editor_action_icon("material", self.palette()))
        self.open_texture_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.open_texture_button.setEnabled(False)
        self.open_texture_button.clicked.connect(self.texture_edit_requested.emit)
        for index, button in enumerate(
            (
                self.part_clone_button,
                self.part_delete_button,
                self.part_recalculate_normals_button,
                self.part_flip_normals_button,
                self.open_texture_button,
            )
        ):
            action_grid.addWidget(button, index // 3, index % 3)
        action_grid.setColumnStretch(2, 1)
        layout.addLayout(action_grid)
        self.material_tree = self._tree(("Material", "Texture", "Slot"), "MeshEditorMaterialPanel")
        self._configure_part_tree(self.material_tree)
        layout.addWidget(self.material_tree, 1)
        return frame

    def _part_control_button(
        self,
        parent: QWidget,
        object_name: str,
        text: str,
        icon_key: str,
        tooltip: str,
        callback: object,
    ) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName(object_name)
        button.setText(text)
        button.setAccessibleName(text)
        button.setToolTip(tooltip)
        button.setIcon(mesh_editor_action_icon(icon_key, self.palette()))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setEnabled(False)
        button.clicked.connect(callback)  # type: ignore[arg-type]
        return button

    def _part_action_button(
        self,
        parent: QWidget,
        object_name: str,
        text: str,
        icon_key: str,
        tooltip: str,
        command: str,
    ) -> QToolButton:
        return self._part_control_button(
            parent,
            object_name,
            text,
            icon_key,
            tooltip,
            lambda _checked=False, current=command: self._emit_selected_part_action(current),
        )

    def _emit_selected_part_action(self, command: str) -> None:
        part_index = self._first_selected_part_index()
        if part_index >= 0:
            self.part_context_action_requested.emit(str(command or ""), part_index)

    def _first_selected_part_index(self) -> int:
        summary = self._workspace_summary
        if summary is None:
            return -1
        for part in summary.parts:
            if part.selected:
                return int(part.index)
        return -1

    def _sync_part_controls(self) -> None:
        summary = self._workspace_summary
        parts = tuple(summary.parts if summary is not None else ())
        selected = tuple(part for part in parts if part.selected)
        part_count = len(parts)
        selected_count = len(selected)
        has_parts = bool(self._has_editor_target and summary is not None and part_count)
        has_selection = bool(has_parts and selected_count)
        has_selected_texture = any(str(part.texture or "").strip() for part in selected)
        for label_name, value in (
            ("part_selection_summary_label", _part_selection_summary_text(summary)),
            ("part_status_label", _part_selection_status_text(summary)),
        ):
            label = getattr(self, label_name, None)
            if label is not None:
                label.setText(value)
                label.setProperty("selectedPartCount", selected_count)
        for name, enabled in (
            ("part_select_all_button", has_parts and selected_count < part_count),
            ("part_clear_selection_button", has_selection),
            ("part_invert_selection_button", has_parts),
            ("part_clone_button", has_selection),
            ("part_delete_button", has_selection),
            ("part_recalculate_normals_button", has_selection),
            ("part_flip_normals_button", has_selection),
            ("open_texture_button", has_selection and has_selected_texture),
        ):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(bool(enabled))

    def set_native_part_picking_status(self, message: str, *, available: bool = False) -> None:
        label = getattr(self, "native_part_pick_status_label", None)
        if label is None:
            return
        label.setText(str(message or "Part pick: unavailable"))
        label.setProperty("nativePartPickingAvailable", bool(available))

    def _build_compare_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorComparePanelFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(QLabel("View", frame))
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
        if report is None:
            self.validator_tree.addTopLevelItem(QTreeWidgetItem(("Info", "not_run", "No active export validation.")))
            return
        summary = (
            f"{len(report.blockers)} blocker(s), {len(report.warnings)} warning(s), "
            f"{report.submesh_count} part(s), {report.vertex_count} vertex/vertices, {report.face_count} face(s)"
        )
        self.validator_tree.addTopLevelItem(QTreeWidgetItem(("OK" if report.ok else "Blocked", "summary", summary)))
        for issue in report.issues:
            location = _issue_location(issue.submesh_index, issue.vertex_index, issue.face_index)
            message = f"{issue.message}{' ' + location if location else ''}"
            self.validator_tree.addTopLevelItem(QTreeWidgetItem((issue.severity.title(), issue.code, message)))

    def _build_status_strip(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorBottomStatusStrip")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.status_label = QLabel("No active edit session.", frame)
        self.status_label.setObjectName("MeshEditorStandaloneStatus")
        self.status_label.setWordWrap(True)
        self.part_status_label = QLabel("Parts: no mesh.", frame)
        self.part_status_label.setObjectName("MeshEditorPartStatusStrip")
        self.part_status_label.setWordWrap(True)
        self.log_list = QListWidget(frame)
        self.log_list.setObjectName("MeshEditorWorkspaceLog")
        self.log_list.setMaximumHeight(54)
        layout.addWidget(self.status_label)
        layout.addWidget(self.part_status_label)
        layout.addWidget(self.log_list)
        return frame

    def _combo(self, object_name: str, values: Iterable[str]) -> QComboBox:
        combo = QComboBox(self)
        combo.setObjectName(object_name)
        combo.addItems(tuple(values))
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        return combo

    def _tree(self, headers: Sequence[str], object_name: str) -> QTreeWidget:
        tree = QTreeWidget(self)
        tree.setObjectName(object_name)
        tree.setHeaderLabels(tuple(headers))
        tree.setRootIsDecorated(False)
        return tree

    def _configure_part_tree(self, tree: QTreeWidget) -> None:
        tree.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        tree.itemClicked.connect(self._part_tree_item_clicked)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(
            lambda position, current=tree: self._show_part_context_menu(current, position)
        )

    def _configure_part_item(self, item: QTreeWidgetItem, part_index: int, selected: bool) -> None:
        item.setData(0, Qt.ItemDataRole.UserRole, int(part_index))
        item.setSelected(bool(selected))
        item.setToolTip(0, "Click to toggle part selection. Right-click for part actions.")

    def _part_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        part_index = self._part_index_from_item(item)
        if part_index >= 0:
            self.part_selection_requested.emit(part_index, "toggle")

    def show_part_context_menu_for_part(self, part_index: int, global_pos: object | None = None) -> None:
        try:
            normalized_index = int(part_index)
        except (TypeError, ValueError):
            normalized_index = -1
        if normalized_index < 0:
            return
        position = global_pos if global_pos is not None else self.mapToGlobal(self.rect().center())
        self._exec_part_context_menu(normalized_index, position, self)

    def _show_part_context_menu(self, tree: QTreeWidget, position: object) -> None:
        item = tree.itemAt(position)  # type: ignore[arg-type]
        part_index = self._part_index_from_item(item)
        if part_index < 0:
            return
        self._exec_part_context_menu(part_index, tree.viewport().mapToGlobal(position), tree)  # type: ignore[arg-type]

    def _exec_part_context_menu(self, part_index: int, global_pos: object, parent: QWidget) -> None:
        menu = QMenu(parent)
        actions = (
            ("Select Only", "select_only"),
            ("Toggle Selection", "toggle_selection"),
            ("Clone Part", "duplicate"),
            ("Delete Part", "delete"),
            ("Recalculate Normals", "recalculate_normals"),
            ("Flip Normals", "flip_normals"),
            ("Open Texture", "open_texture"),
        )
        action_by_command = {command: menu.addAction(label) for label, command in actions}
        chosen = menu.exec(global_pos)  # type: ignore[arg-type]
        for command, action in action_by_command.items():
            if chosen is action:
                self.part_context_action_requested.emit(command, part_index)
                return

    def _part_index_from_item(self, item: QTreeWidgetItem | None) -> int:
        if item is None:
            return -1
        try:
            return int(item.data(0, Qt.ItemDataRole.UserRole))
        except (TypeError, ValueError):
            return -1

    def _mode_changed(self, text: str) -> None:
        if self._updating_state:
            return
        action = mesh_editor_actions_by_key().get(_MODE_ACTION_BY_TEXT.get(str(text or "").strip().lower(), ""))
        if action is not None:
            self.action_requested.emit(action)

    def _compare_view_changed(self, text: str) -> None:
        mode = str(text or "Edited").strip().lower().replace(" ", "_")
        if mode not in {"edited", "source", "ghost"}:
            mode = "edited"
        self.compare_view_requested.emit(mode)

    def _skeleton_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        try:
            bone_index = int(item.data(0, Qt.ItemDataRole.UserRole))
        except (TypeError, ValueError):
            return
        if bone_index >= 0:
            self.skeleton_pose_requested.emit("select_bone", bone_index)

    def _sync_skeleton_pose_controls(self, summary: MeshSkeletonSummary | None) -> None:
        pose = summary.pose if summary is not None else None
        has_bones = bool(summary is not None and summary.bones)
        has_rig_summary = bool(summary is not None and (summary.skinned or summary.skeleton_linked or summary.bones))
        selected = int(pose.selected_bone_index if pose is not None else -1)
        for name in ("pose_preview_button", "preview_pose_button", "rig_pose_button"):
            pose_button = getattr(self, name, None)
            if pose_button is None:
                continue
            previous = pose_button.blockSignals(True)
            try:
                pose_button.setChecked(bool(pose is not None and pose.enabled))
            finally:
                pose_button.blockSignals(previous)
            pose_button.setEnabled(has_bones)
        for name in ("preview_skeleton_button", "rig_skeleton_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(has_rig_summary)
        for name in ("pose_rotate_x_button", "pose_rotate_y_button", "pose_rotate_z_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(has_bones and selected >= 0)
        has_selected_weights = bool(summary is not None and summary.selected_vertex_weights)
        has_selected_part = bool(summary is not None and any(part.selected for part in summary.parts))
        for name in ("weight_increase_button", "weight_decrease_button", "weight_normalize_button", "rig_weight_normalize_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(has_bones and selected >= 0 and has_selected_weights)
        for name in ("weight_transfer_button", "rig_weight_transfer_button"):
            transfer_button = getattr(self, name, None)
            if transfer_button is not None:
                transfer_button.setEnabled(has_bones and (has_selected_weights or has_selected_part))
        reset_button = getattr(self, "pose_reset_button", None)
        if reset_button is not None:
            reset_button.setEnabled(has_bones and bool(pose is not None and (pose.posed_bone_count or selected >= 0)))
        playback = summary.animation_playback if summary is not None else None
        playback_ready = bool(playback is not None and playback.ready)
        play_button = getattr(self, "animation_play_button", None)
        if play_button is not None:
            previous = play_button.blockSignals(True)
            try:
                play_button.setChecked(bool(playback is not None and playback.enabled))
            finally:
                play_button.blockSignals(previous)
            play_button.setEnabled(playback_ready)
        for name in ("animation_step_button", "animation_rewind_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(playback_ready)
        loop_button = getattr(self, "animation_loop_button", None)
        if loop_button is not None:
            previous = loop_button.blockSignals(True)
            try:
                loop_button.setChecked(bool(playback is not None and playback.loop))
            finally:
                loop_button.blockSignals(previous)
            loop_button.setEnabled(playback_ready)
        speed_combo = getattr(self, "animation_speed_combo", None)
        if speed_combo is not None:
            self._sync_animation_speed_combo(speed_combo, float(getattr(playback, "playback_speed", 1.0) if playback is not None else 1.0))
            speed_combo.setEnabled(playback_ready)
        scrub_slider = getattr(self, "animation_scrub_slider", None)
        if scrub_slider is not None:
            duration = float(getattr(playback, "duration_seconds", 0.0) if playback is not None else 0.0)
            time_seconds = float(getattr(playback, "time_seconds", 0.0) if playback is not None else 0.0)
            value = int(round(1000.0 * min(1.0, max(0.0, time_seconds / duration)))) if duration > 0.0 else 0
            previous = scrub_slider.blockSignals(True)
            try:
                scrub_slider.setValue(value)
            finally:
                scrub_slider.blockSignals(previous)
            scrub_slider.setEnabled(playback_ready and duration > 0.0)

    def _selection_changed(self, text: str) -> None:
        if self._updating_state:
            return
        action = mesh_editor_actions_by_key().get(_SELECTION_ACTION_BY_TEXT.get(str(text or "").strip().lower(), ""))
        if action is not None:
            self.action_requested.emit(action)

    def _sync_combo(self, combo: QComboBox, value: str) -> None:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return
        for index in range(combo.count()):
            if combo.itemText(index).strip().lower() == normalized:
                if combo.currentIndex() == index:
                    return
                self._updating_state = True
                try:
                    combo.setCurrentIndex(index)
                finally:
                    self._updating_state = False
                return

    def _animation_speed_changed(self, _index: int) -> None:
        if self._updating_state:
            return
        combo = getattr(self, "animation_speed_combo", None)
        if combo is None:
            return
        self.skeleton_pose_requested.emit("set_animation_speed", combo.currentData())

    def _animation_scrub_changed(self, value: int) -> None:
        if self._updating_state:
            return
        self.skeleton_pose_requested.emit("scrub_animation_fraction", max(0.0, min(1.0, float(value) / 1000.0)))

    def _sync_animation_speed_combo(self, combo: QComboBox, value: float) -> None:
        best_index = 0
        best_delta = float("inf")
        for index in range(combo.count()):
            try:
                current = float(combo.itemData(index))
            except (TypeError, ValueError, OverflowError):
                continue
            delta = abs(current - value)
            if delta < best_delta:
                best_index = index
                best_delta = delta
        previous = combo.blockSignals(True)
        try:
            combo.setCurrentIndex(best_index)
        finally:
            combo.blockSignals(previous)


def _issue_location(submesh_index: int, vertex_index: int, face_index: int) -> str:
    parts: list[str] = []
    if submesh_index >= 0:
        parts.append(f"part {submesh_index}")
    if vertex_index >= 0:
        parts.append(f"vertex {vertex_index}")
    if face_index >= 0:
        parts.append(f"face {face_index}")
    return f"({' / '.join(parts)})" if parts else ""


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
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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


__all__ = ["MeshEditorWorkspace"]
