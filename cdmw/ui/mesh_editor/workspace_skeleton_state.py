"""WorkspaceSkeletonStateMixin methods for the Mesh Editor workspace."""

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
from cdmw.ui.preview import DotNetPreviewHostFrame, DotNetPreviewProfile
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

class WorkspaceSkeletonStateMixin:
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
        if self._embedded_controls_only:
            self._update_embedded_skeleton_summary(summary)
            return
        self._append_skeleton_sources(summary)
        self._append_constraint_evidence(summary.animation_constraint_evidence)
        self._append_skeleton_status(summary)
        self._append_skeleton_weights(summary)
        self._append_skeleton_bones(summary)
        self._append_skeleton_parts(summary)

    def _append_skeleton_sources(self, summary: MeshSkeletonSummary) -> None:
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

    def _append_constraint_evidence(self, constraint_evidence: object) -> None:
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
            self._append_constraint_numeric_evidence(constraint_evidence)
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
            self._append_constraint_candidates(constraint_evidence)
            if constraint_evidence.proof_gap:
                self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("Constraint Gap", constraint_evidence.proof_gap)))

    def _append_constraint_numeric_evidence(self, constraint_evidence: object) -> None:
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

    def _append_constraint_candidates(self, constraint_evidence: object) -> None:
        for candidate in constraint_evidence.record_candidates:
            context_bits = [
                _constraint_bone_label(
                    "target", candidate.target_bone, candidate.target_bone_index, candidate.target_bone_confidence
                ),
                _constraint_bone_label(
                    "helper", candidate.helper_bone, candidate.helper_bone_index, candidate.helper_bone_confidence
                ),
                _constraint_bone_label(
                    "parent", candidate.parent_bone, candidate.parent_bone_index, candidate.parent_bone_confidence
                ),
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
                            f"disabled | {candidate.constraint_type} | {context_text} | expr {expression}"
                            f"{f' | {token_text}' if token_text else ''} | "
                            f"{f'{field_offset_text} | ' if field_offset_text else ''}"
                            f"record {candidate.record_confidence} | {candidate.solver_status}"
                        ),
                    )
                )
            )

    def _append_skeleton_status(self, summary: MeshSkeletonSummary) -> None:
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

    def _append_skeleton_weights(self, summary: MeshSkeletonSummary) -> None:
        pose = summary.pose
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

    def _append_skeleton_bones(self, summary: MeshSkeletonSummary) -> None:
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

    def _append_skeleton_parts(self, summary: MeshSkeletonSummary) -> None:
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

    def _update_embedded_skeleton_summary(self, summary: MeshSkeletonSummary) -> None:
        if summary.skeleton_descriptor_source or summary.skeleton_variation_source or summary.animation_constraint_source:
            sources = " | ".join(
                bit
                for bit in (
                    f"descriptor {summary.skeleton_descriptor_source}" if summary.skeleton_descriptor_source else "",
                    f"variation {summary.skeleton_variation_source}" if summary.skeleton_variation_source else "",
                    f"constraint {summary.animation_constraint_source}" if summary.animation_constraint_source else "",
                )
                if bit
            )
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("Rig source", sources)))
        pose = summary.pose
        if pose.selected_bone_index >= 0:
            selected = pose.selected_bone_name or "selected bone"
            self.skeleton_tree.addTopLevelItem(
                QTreeWidgetItem(("Selected bone", f"{pose.selected_bone_index}: {selected} | rot {pose.rotation_text}"))
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
        if summary.animation_status:
            self.skeleton_tree.addTopLevelItem(
                QTreeWidgetItem(
                    (
                        "Animation",
                        f"{summary.animation_status} | {'ready' if summary.animation_playback_ready else 'not editable here'}",
                    )
                )
            )
        if summary.bones:
            parser_note = f" | parser {summary.skeleton_parser_mode}" if summary.skeleton_parser_mode else ""
            self.skeleton_tree.addTopLevelItem(
                QTreeWidgetItem(("Bones", f"{len(summary.bones)} bones | {summary.root_bone_count} roots | depth {summary.max_depth}{parser_note}"))
            )
            for bone in summary.bones[:_SKELETON_PANEL_BONE_LIMIT]:
                indent = "  " * min(max(0, int(bone.depth or 0)), 8)
                selected = "*" if bone.index == summary.pose.selected_bone_index else ""
                parent = bone.parent_name or "root"
                position = f" | pos {bone.position_text}" if bone.position_text else ""
                item = QTreeWidgetItem((f"{indent}{selected}{bone.index}: {bone.name}", f"parent {parent} | children {bone.child_count}{position}"))
                item.setData(0, Qt.ItemDataRole.UserRole, bone.index)
                self.skeleton_tree.addTopLevelItem(item)
            if len(summary.bones) > _SKELETON_PANEL_BONE_LIMIT:
                self.skeleton_tree.addTopLevelItem(
                    QTreeWidgetItem(("Truncated", f"showing first {_SKELETON_PANEL_BONE_LIMIT} of {len(summary.bones)} bones"))
                )
        skinned_parts = [part for part in summary.parts if part.skinned]
        if skinned_parts:
            self.skeleton_tree.addTopLevelItem(
                QTreeWidgetItem(("Weighted parts", f"{summary.weighted_part_count}/{summary.part_count} parts use skeleton weights"))
            )
            for part in skinned_parts[:32]:
                selected = "*" if part.selected else ""
                detail = f"{part.weighted_vertex_count}/{part.vertex_count} weighted | {part.bone_count} bones"
                self.skeleton_tree.addTopLevelItem(QTreeWidgetItem((f"{selected}{part.index}: {part.name}", detail)))
            if len(skinned_parts) > 32:
                self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("Parts truncated", f"showing first 32 of {len(skinned_parts)} skinned parts")))
        if self.skeleton_tree.topLevelItemCount() <= 1:
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("No skinned parts", "")))
