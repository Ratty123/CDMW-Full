from __future__ import annotations
from cdmw.models import ArchiveEntry
from collections.abc import Mapping
from pathlib import Path
from collections.abc import Sequence
import os
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.modding.skeleton_parser import parse_pab
from cdmw.core.skeleton_resolver import resolve_skeleton_for_model
from tools.mesh_harness.constants import _REAL_ARCHIVE_RIGGING_SAMPLES
from tools.mesh_harness.evidence import _mesh_editor_advanced_authoring_corpus_manifest
from tools.mesh_harness.papr import _papr_constraint_evidence_for_path
from tools.mesh_harness.real_common import _archive_entry_indexes, _archive_key, _read_archive_payload
from tools.mesh_harness.real_rigging import _weighted_bone_candidates
from tools.mesh_harness.service_summary import _mesh_vertices_changed

def run_real_archive_app_workflow_smoke(game_root: Path, output_dir: Path) -> dict[str, object]:
    pamt_path = game_root / '0009' / '0.pamt'
    if not pamt_path.is_file():
        return {'ok': False, 'read_only': True, 'skipped': f'missing PAMT: {pamt_path}', 'game_root': str(game_root), 'pamt_path': str(pamt_path)}
    entries = parse_archive_pamt(pamt_path)
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    result = _run_real_archive_app_workflow_sample(_REAL_ARCHIVE_RIGGING_SAMPLES[0], entries, entries_by_path, entries_by_basename, output_dir, game_root=game_root, pamt_path=pamt_path)
    result['corpus_manifest'] = _mesh_editor_advanced_authoring_corpus_manifest(entries, entries_by_path)
    return result

def _run_real_archive_app_workflow_sample(model_path: str, entries: Sequence[ArchiveEntry], entries_by_path: Mapping[str, Sequence[ArchiveEntry]], entries_by_basename: Mapping[str, Sequence[ArchiveEntry]], output_dir: Path, *, game_root: Path, pamt_path: Path) -> dict[str, object]:
    model_entry = next(iter(entries_by_path.get(_archive_key(model_path), ())), None)
    if model_entry is None:
        return {'ok': False, 'read_only': True, 'model_path': model_path, 'error': 'model entry not found'}
    try:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtCore import QSettings, Qt
        from PySide6.QtWidgets import QApplication, QToolButton, QTreeWidget
        from cdmw.ui.mesh_editor import MeshEditorTab
        pac_data = _read_archive_payload(model_entry)
        mesh = parse_mesh(pac_data, model_entry.path)
        skeleton_entry, report = resolve_skeleton_for_model(model_entry, entries, archive_entries_by_normalized_path=entries_by_path, archive_entries_by_basename=entries_by_basename, pac_data=pac_data, read_entry_data=_read_archive_payload)
        if skeleton_entry is None:
            return {'ok': False, 'read_only': True, 'model_path': model_entry.path, 'confidence': report.confidence, 'descriptor_path': report.descriptor_path, 'error': 'skeleton entry not resolved'}
        skeleton = parse_pab(_read_archive_payload(skeleton_entry), skeleton_entry.path)
        constraint_evidence = _papr_constraint_evidence_for_path(entries_by_path, entries_by_basename, report.animation_constraint_path)
        app = QApplication.instance() or QApplication(['mesh-editor-real-archive-app-workflow'])
        settings_file = output_dir / 'mesh_editor_app_workflow.ini'
        settings = QSettings(str(settings_file), QSettings.Format.IniFormat)
        settings.setFallbacksEnabled(False)
        tab = MeshEditorTab(settings=settings)
        try:
            view = tab.open_mesh_session(mesh, target_entry=model_entry, session_id='real-archive-app-workflow', mode='edit')
            if tab.standalone_controller is None:
                return {'ok': False, 'read_only': True, 'model_path': model_entry.path, 'error': 'controller missing'}
            controller = tab.standalone_controller
            controller.attach_skeleton(skeleton, source_path=skeleton_entry.path, skeleton_descriptor_source=report.descriptor_path, skeleton_variation_source=report.skeleton_variation_path, animation_constraint_source=report.animation_constraint_path, animation_constraint_evidence=constraint_evidence, socket_source=report.socket_path)
            tab.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
            app.processEvents()
            skeleton_tree = tab.standalone_workspace.findChild(QTreeWidget, 'MeshEditorSkeletonPanel')
            if skeleton_tree is None:
                return {'ok': False, 'read_only': True, 'model_path': model_entry.path, 'error': 'skeleton panel missing'}
            selected_bone = next(iter(_weighted_bone_candidates(controller.working_mesh(clone=False), len(getattr(skeleton, 'bones', ()) or ()))), -1)
            clicked_bone = False
            for index in range(skeleton_tree.topLevelItemCount()):
                item = skeleton_tree.topLevelItem(index)
                try:
                    item_bone = int(item.data(0, Qt.ItemDataRole.UserRole))
                except (TypeError, ValueError):
                    continue
                if item_bone == selected_bone:
                    tab.standalone_workspace._skeleton_tree_item_clicked(item, 0)
                    clicked_bone = True
                    break
            pose_button = tab.standalone_workspace.findChild(QToolButton, 'MeshEditorPosePreviewButton')
            rotate_button = tab.standalone_workspace.findChild(QToolButton, 'MeshEditorPoseRotateYButton')
            if pose_button is not None:
                pose_button.click()
            if rotate_button is not None:
                rotate_button.click()
            app.processEvents()
            summary = controller.skeleton_summary()
            pose_changed = _mesh_vertices_changed(controller.working_mesh(clone=False), controller.pose_preview_mesh())
            rows = [(skeleton_tree.topLevelItem(index).text(0), skeleton_tree.topLevelItem(index).text(1)) for index in range(skeleton_tree.topLevelItemCount())]
            resolver_row = next((value for label, value in rows if label == 'Resolver'), '')
            animation_row = next((value for label, value in rows if label == 'Animation'), '')
            constraint_row = next((value for label, value in rows if label == 'Constraint Evidence'), '')
            constraint_family_row = next((value for label, value in rows if label == 'Constraint Families'), '')
            constraint_match_row = next((value for label, value in rows if label == 'Constraint Bone Matches'), '')
            constraint_expression_row = next((value for label, value in rows if label == 'Constraint Expressions'), '')
            constraint_offset_row = next((value for label, value in rows if label == 'Constraint Field Offsets'), '')
            constraint_numeric_match_row = next((value for label, value in rows if label == 'Constraint Numeric Matches'), '')
            constraint_solver_row = next((value for label, value in rows if label == 'Constraint Solver Readiness'), '')
            constraint_family_detail_rows = {label: value for label, value in rows if str(label).startswith('Constraint Family:')}
            driver_family_row = constraint_family_detail_rows.get('Constraint Family: driver_expression_candidate', '')
            limit_family_row = constraint_family_detail_rows.get('Constraint Family: local_transform_limit_candidate', '')
            constraint_candidate_rows = [value for label, value in rows if str(label).startswith('Constraint Candidate:')]
            ok = bool(tab.current_archive_selection is model_entry and controller.active_session_id and clicked_bone and pose_changed and (report.confidence == 'descriptor') and report.descriptor_path and report.skeleton_variation_path and ('playback blocked' in animation_row) and ('solver blocked' in constraint_row) and ('driver_expression_candidate=49' in constraint_family_row) and ('local_transform_limit_candidate=16' in constraint_family_row) and ('candidate rows' in constraint_match_row) and ('target suffix_base_name' in constraint_match_row) and ('helper exact_name' in constraint_match_row) and ('parent prefix_base_name' in constraint_match_row) and ('channel Local_Euler_Z' in constraint_expression_row) and ('shape linear_channel_transform_candidate' in constraint_expression_row) and ('numeric role channel_coefficient' in constraint_expression_row) and ('syntax signatures 17 unique' in constraint_expression_row) and ('semantics unknown' in constraint_expression_row) and ('target=59' in constraint_offset_row) and ('helper=36' in constraint_offset_row) and ('parent=32' in constraint_offset_row) and ('10 unbound text/scalar numeric matches' in constraint_numeric_match_row) and ('unbound_scalar_numeric_constant_matches=5' in constraint_numeric_match_row) and ('channel_coefficient=5' in constraint_numeric_match_row) and ('limit_argument=5' in constraint_numeric_match_row) and ('storage f32=9' in constraint_numeric_match_row) and ('u32=1' in constraint_numeric_match_row) and ('pairs parent>expression=5' in constraint_numeric_match_row) and ('parent>helper=2' in constraint_numeric_match_row) and ('parent>target=3' in constraint_numeric_match_row) and ('value confidence approx_float32_numeric_value_match_layout_unproven=6' in constraint_numeric_match_row) and ('exact_float32_numeric_value_match_layout_unproven=3' in constraint_numeric_match_row) and ('exact_u32_numeric_value_match_layout_unproven=1' in constraint_numeric_match_row) and ('families driver_expression_candidate=5' in constraint_numeric_match_row) and ('local_transform_limit_candidate=5' in constraint_numeric_match_row) and ('family rows driver_expression_candidate=3' in constraint_numeric_match_row) and ('local_transform_limit_candidate=2' in constraint_numeric_match_row) and ('rel signatures 10 unique' in constraint_numeric_match_row) and ('prev deltas 11=1' in constraint_numeric_match_row) and ('20=2' in constraint_numeric_match_row) and ('380=1 (range 11-380)' in constraint_numeric_match_row) and ('next deltas 5=1' in constraint_numeric_match_row) and ('167=2' in constraint_numeric_match_row) and ('611=1 (range 5-611)' in constraint_numeric_match_row) and ('candidate rel offsets -615=1' in constraint_numeric_match_row) and ('-81=1' in constraint_numeric_match_row) and ('-77=1 (range -615--77)' in constraint_numeric_match_row) and ('observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven' in constraint_numeric_match_row) and ('observed_relative_to_inferred_candidate_offset_value_layout_unproven' in constraint_numeric_match_row) and ('value layout unproven' in constraint_numeric_match_row) and ('solver ready=0' in constraint_solver_row) and ('target bound=59' in constraint_solver_row) and ('record layout unproven=65' in constraint_solver_row) and ('expression semantics unknown=65' in constraint_solver_row) and ('candidates=49' in driver_family_row) and ('target bound=45' in driver_family_row) and ('helper bound=24' in driver_family_row) and ('parent bound=19' in driver_family_row) and ('record layout unproven=49' in driver_family_row) and ('expression semantics unknown=49' in driver_family_row) and ('candidates=16' in limit_family_row) and ('target bound=14' in limit_family_row) and ('helper bound=12' in limit_family_row) and ('parent bound=6' in limit_family_row) and ('record layout unproven=16' in limit_family_row) and ('expression semantics unknown=16' in limit_family_row) and constraint_candidate_rows and any(('disabled' in value and 'blocked_record_layout_unproven' in value for value in constraint_candidate_rows)) and any(('(#' in value and 'exact_name' in value for value in constraint_candidate_rows)) and any(('suffix_base_name' in value for value in constraint_candidate_rows)) and any(('prefix_base_name' in value for value in constraint_candidate_rows)) and any(('channels proven: Local_Euler_Z' in value and 'numeric constants=' in value for value in constraint_candidate_rows)) and any(('shape inferred_readable_expression_syntax' in value for value in constraint_candidate_rows)) and any(('numeric roles inferred_readable_expression_syntax' in value for value in constraint_candidate_rows)) and any(('limits proven: amin' in value for value in constraint_candidate_rows)) and any(('semantics unknown' in value for value in constraint_candidate_rows)) and any(('fields proven_decoded_string_offsets' in value and 'expr@' in value and ('target@' in value) for value in constraint_candidate_rows)) and any(('gaps binary_like_interfield_gap_bytes_unbound' in value for value in constraint_candidate_rows)) and any(('scalars unbound_interfield_scalar_candidates' in value for value in constraint_candidate_rows)))
            return {'ok': ok, 'read_only': True, 'workflow': 'PAMT target lookup -> MeshEditorTab standalone session -> Skeleton panel pose controls', 'game_root': str(game_root), 'pamt_path': str(pamt_path), 'settings_file': str(settings_file), 'entry_count': len(entries), 'model_path': model_entry.path, 'skeleton_path': skeleton_entry.path, 'confidence': report.confidence, 'descriptor_path': report.descriptor_path, 'skeleton_variation_path': report.skeleton_variation_path, 'animation_constraint_path': report.animation_constraint_path, 'socket_path': report.socket_path, 'session_id': controller.active_session_id, 'pose_changed': pose_changed, 'selected_bone_index': selected_bone, 'clicked_bone': clicked_bone, 'weighted_vertex_count': summary.weighted_vertex_count, 'animation_status': summary.animation_status, 'animation_playback_ready': summary.animation_playback_ready, 'constraint_evidence_status': summary.animation_constraint_evidence.status, 'constraint_string_evidence': summary.animation_constraint_evidence.string_evidence_count, 'constraint_record_candidates': summary.animation_constraint_evidence.record_candidate_count, 'constraint_related_physics': summary.animation_constraint_evidence.related_physics_count, 'animation_row': animation_row, 'constraint_row': constraint_row, 'constraint_family_row': constraint_family_row, 'constraint_match_row': constraint_match_row, 'constraint_expression_row': constraint_expression_row, 'constraint_offset_row': constraint_offset_row, 'constraint_numeric_match_row': constraint_numeric_match_row, 'constraint_solver_row': constraint_solver_row, 'constraint_family_detail_rows': constraint_family_detail_rows, 'constraint_candidate_rows': constraint_candidate_rows, 'resolver_row': resolver_row}
        finally:
            tab.close_standalone_session()
            tab.deleteLater()
            app.processEvents()
            settings.sync()
    except Exception as exc:
        return {'ok': False, 'read_only': True, 'model_path': model_entry.path, 'error': f'{type(exc).__name__}: {exc}'}
