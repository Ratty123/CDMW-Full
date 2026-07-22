from __future__ import annotations

from importlib import import_module
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.mesh_harness.cli import main

_EXPORTS = {
    "_HarnessSignal": "tools.mesh_harness.stroke_harness_host",
    "_StandaloneStrokeHarnessHost": "tools.mesh_harness.stroke_harness_host",
    "_analyse_real_archive_animation_entry": "tools.mesh_harness.real_animation",
    "_archive_content_fingerprints": "tools.mesh_harness.archive_provenance",
    "_archive_entry_indexes": "tools.mesh_harness.real_common",
    "_archive_entry_provenance": "tools.mesh_harness.archive_provenance",
    "_archive_key": "tools.mesh_harness.real_common",
    "_archive_source_file_snapshot": "tools.mesh_harness.archive_provenance",
    "_binary_timing_probe_counts": "tools.mesh_harness.sequence_analysis",
    "_build_long_edit_mesh": "tools.mesh_harness.fixtures",
    "_build_loose_edge_mesh": "tools.mesh_harness.fixtures",
    "_build_malformed_face_mesh": "tools.mesh_harness.fixtures",
    "_build_two_part_synthetic_mesh": "tools.mesh_harness.fixtures",
    "_clip_sequence_segments_json": "tools.mesh_harness.sequence_analysis",
    "_command_summary": "tools.mesh_harness.service_summary",
    "_counter_update_ints": "tools.mesh_harness.papr",
    "_coverage_command": "tools.mesh_harness.service_coverage",
    "_document_asset_reference_paths": "tools.mesh_harness.sequence_analysis",
    "_document_paseq_timing_evidence": "tools.mesh_harness.sequence_analysis",
    "_document_related_resolved_paths": "tools.mesh_harness.sequence_analysis",
    "_edge_face_topology_smoke": "tools.mesh_harness.service_topology",
    "_entry_by_archive_path": "tools.mesh_harness.real_common",
    "_evenly_spaced_entries": "tools.mesh_harness.real_animation",
    "_feature_status_row": "tools.mesh_harness.evidence",
    "_history_context_smoke": "tools.mesh_harness.service_selection",
    "_history_selection_smoke": "tools.mesh_harness.service_selection",
    "_host_window_rect": "tools.mesh_harness.win32_input",
    "_long_edit_split_selection": "tools.mesh_harness.fixtures",
    "_long_edit_topology_selection": "tools.mesh_harness.fixtures",
    "_long_edit_vertex_selection": "tools.mesh_harness.fixtures",
    "_material_operation_smoke": "tools.mesh_harness.service_targets",
    "_mesh_editor_advanced_authoring_corpus_manifest": "tools.mesh_harness.evidence",
    "_mesh_editor_evidence_report": "tools.mesh_harness.evidence",
    "_mesh_editor_feature_status_rows": "tools.mesh_harness.evidence",
    "_mesh_editor_sample_family_rows": "tools.mesh_harness.evidence",
    "_mesh_face_count": "tools.mesh_harness.service_summary",
    "_mesh_geometry_signature": "tools.mesh_harness.service_summary",
    "_mesh_textures": "tools.mesh_harness.service_summary",
    "_mesh_vertex_count": "tools.mesh_harness.service_summary",
    "_mesh_vertices_changed": "tools.mesh_harness.service_summary",
    "_palette_action_input": "tools.mesh_harness.service_coverage",
    "_palette_command_summary": "tools.mesh_harness.service_summary",
    "_papr_candidate_family_update": "tools.mesh_harness.papr",
    "_papr_constraint_evidence_for_path": "tools.mesh_harness.papr",
    "_papr_constraint_metadata_summary": "tools.mesh_harness.papr",
    "_paseq_lane_for_path": "tools.mesh_harness.sequence_analysis",
    "_png_capture_summary": "tools.mesh_harness.png_evidence",
    "_png_paeth": "tools.mesh_harness.png_evidence",
    "_png_unfilter_scanline": "tools.mesh_harness.png_evidence",
    "_proof_artifact": "tools.mesh_harness.evidence",
    "_prove_pose_deformation": "tools.mesh_harness.real_rigging",
    "_prove_real_archive_paa_playback_deformation": "tools.mesh_harness.real_animation",
    "_read_archive_payload": "tools.mesh_harness.real_common",
    "_read_i32_descriptor_values": "tools.mesh_harness.fixtures",
    "_real_archive_all_pamt_entries": "tools.mesh_harness.real_common",
    "_real_archive_animation_binding_blockers": "tools.mesh_harness.real_animation",
    "_real_archive_animation_sample_entries": "tools.mesh_harness.real_animation",
    "_real_archive_extension_counts_by_package": "tools.mesh_harness.real_common",
    "_real_archive_papr_read_status": "tools.mesh_harness.papr",
    "_real_archive_sequence_timing_corpus_summary": "tools.mesh_harness.sequence_analysis",
    "_real_archive_skeleton_variation_summary": "tools.mesh_harness.real_animation",
    "_real_game_mesh_evidence": "tools.mesh_harness.evidence",
    "_resolve_real_archive_mesh_textures": "tools.mesh_harness.archive_provenance",
    "_result_contains_read_only": "tools.mesh_harness.evidence",
    "_result_corpus_manifest": "tools.mesh_harness.evidence",
    "_run_long_topology_edit_tool": "tools.mesh_harness.native_workflow",
    "_run_long_vertex_edit_tool": "tools.mesh_harness.native_workflow",
    "_run_mesh_edit_command_worker_qt": "tools.mesh_harness.qt_probes",
    "_run_real_archive_app_workflow_sample": "tools.mesh_harness.real_app",
    "_run_real_archive_rigging_sample": "tools.mesh_harness.real_rigging",
    "_sample_real_archive_paa_playback": "tools.mesh_harness.real_animation",
    "_selection_edges_from_group": "tools.mesh_harness.fixtures",
    "_selection_faces_from_group": "tools.mesh_harness.fixtures",
    "_selection_operation_smoke": "tools.mesh_harness.service_selection",
    "_selection_pruning_smoke": "tools.mesh_harness.service_selection",
    "_selection_snapshot": "tools.mesh_harness.service_summary",
    "_send_mouse_message": "tools.mesh_harness.win32_input",
    "_sequence_event_marker_overlap": "tools.mesh_harness.sequence_analysis",
    "_sequence_frame_rate_metadata": "tools.mesh_harness.real_animation",
    "_sequence_lane_pair_summary": "tools.mesh_harness.sequence_analysis",
    "_sequence_path_record_context": "tools.mesh_harness.sequence_analysis",
    "_sequence_reference_overlap": "tools.mesh_harness.sequence_analysis",
    "_sequence_timeline_field_overlap": "tools.mesh_harness.sequence_analysis",
    "_sequence_timeline_field_semantic_aliases": "tools.mesh_harness.sequence_analysis",
    "_sha256_file": "tools.mesh_harness.archive_provenance",
    "_skeleton_bone_name_bytes": "tools.mesh_harness.real_animation",
    "_source_sequence_path_for_compiled_sequence": "tools.mesh_harness.sequence_analysis",
    "_topology_target_smoke": "tools.mesh_harness.service_targets",
    "_transform_target_smoke": "tools.mesh_harness.service_targets",
    "_tuple_row": "tools.mesh_harness.service_summary",
    "_uv_operation_smoke": "tools.mesh_harness.service_targets",
    "_vec3": "tools.mesh_harness.service_summary",
    "_weighted_bone_candidates": "tools.mesh_harness.real_rigging",
    "_write_checker_png": "tools.mesh_harness.png_evidence",
    "_write_json_atomic": "tools.mesh_harness.evidence",
    "_write_real_archive_visual_edit_proof": "tools.mesh_harness.png_evidence",
    "build_native_benchmark_mesh": "tools.mesh_harness.fixtures",
    "build_synthetic_mesh": "tools.mesh_harness.fixtures",
    "run_asset_authoring_discovery": "tools.mesh_harness.asset_authoring",
    "run_asset_authoring_mesh_health": "tools.mesh_harness.asset_authoring",
    "run_asset_authoring_openimageio_report": "tools.mesh_harness.asset_authoring",
    "run_asset_authoring_tangent_report": "tools.mesh_harness.asset_authoring",
    "run_asset_authoring_uv_report": "tools.mesh_harness.asset_authoring",
    "run_controller_action_palette_coverage": "tools.mesh_harness.service_coverage",
    "run_long_edit_mesh_tools": "tools.mesh_harness.native_workflow",
    "run_mesh_dotnet_native_parity_report": "tools.mesh_harness.parity",
    "run_native_mesh_editor_benchmark": "tools.mesh_harness.native_workflow",
    "run_native_mesh_editor_qt_cancellation": "tools.mesh_harness.qt_probes",
    "run_native_mesh_editor_qt_responsiveness": "tools.mesh_harness.qt_probes",
    "run_native_mesh_editor_standalone_stroke": "tools.mesh_harness.native_strokes",
    "run_native_mesh_editor_static_replacement_screen_stroke": "tools.mesh_harness.native_strokes",
    "run_native_mesh_editor_workflow": "tools.mesh_harness.native_workflow",
    "run_real_archive_animation_binding_smoke": "tools.mesh_harness.real_animation",
    "run_real_archive_app_workflow_smoke": "tools.mesh_harness.real_app",
    "run_real_archive_mesh_editor_dotnet_edit_smoke": "tools.mesh_harness.real_dotnet",
    "run_real_archive_rigging_smoke": "tools.mesh_harness.real_rigging",
    "run_real_archive_sequence_binding_smoke": "tools.mesh_harness.real_sequence",
    "run_scenario": "tools.mesh_harness.scenario_runner",
    "run_service_command_coverage": "tools.mesh_harness.service_coverage",
    "run_service_smoke": "tools.mesh_harness.service_smoke",
}

_EXPORTS.update(dict.fromkeys((
    "_ADVANCED_AUTHORING_CONFIDENCE_LABELS", "_ADVANCED_AUTHORING_CORPUS_EXTENSIONS",
    "_ADVANCED_AUTHORING_STATE_LABELS", "_DEFAULT_GAME_ROOT", "_DOTNET_NATIVE_PARITY_SCENARIO",
    "_LEGACY_SCREEN_CAMERA_FIELDS", "_MK_LBUTTON", "_REAL_ARCHIVE_ANIMATION_PREFERRED_PAA",
    "_REAL_ARCHIVE_ANIMATION_SAMPLE_LIMIT", "_REAL_ARCHIVE_RIGGING_SAMPLES", "_REAL_ARCHIVE_SEQUENCE_EXTENSIONS",
    "_REAL_ARCHIVE_SEQUENCE_PTM_DESCRIPTOR", "_REAL_ARCHIVE_SEQUENCE_PTM_PAA", "_REAL_ARCHIVE_SEQUENCE_PTM_PAB",
    "_REAL_ARCHIVE_SEQUENCE_PTM_PAPR", "_REAL_ARCHIVE_SEQUENCE_SAMPLE", "_REAL_MESH_EDITOR_DOTNET_SCENARIO",
    "_REAL_MESH_EDITOR_VISUAL_SCENARIO",
    "_SYNTHETIC_MESH_FORMATS", "_WM_LBUTTONDOWN", "_WM_LBUTTONUP", "_WM_MOUSEMOVE",
), "tools.mesh_harness.constants"))


def __getattr__(name: str) -> object:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


if __name__ == "__main__":
    raise SystemExit(main())
