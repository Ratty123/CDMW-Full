from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from cdmw.domain.mesh import MESH_EDIT_ACTIONS, MeshEditSelection
from cdmw.domain.mesh.skeleton import (
    MeshAnimationClip,
    MeshAnimationKeyframe,
    MeshAnimationSequenceSegment,
    MeshAnimationTrack,
)
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.ui.mesh_editor.native_preview_payloads import (
    mesh_edit_material_override_groups,
    mesh_edit_selection_groups,
    mesh_edit_triangle_groups,
    mesh_edit_vertex_update_groups,
    mesh_to_native_preview,
)
from cdmw.ui.mesh_editor.actions import MESH_EDITOR_ACTIONS
from cdmw.ui.mesh_editor.native_preview_runtime import (
    mesh_editor_native_preview_command,
    mesh_editor_write_native_preview_package,
)
from cdmw.models import ArchiveEntry
from tools.mesh_editor_dev_harness import (
    _papr_constraint_metadata_summary,
    _png_capture_summary,
    _real_archive_papr_read_status,
    _sample_real_archive_paa_playback,
    _sequence_event_marker_overlap,
    _sequence_lane_pair_summary,
    _sequence_path_record_context,
    _sequence_reference_overlap,
    _sequence_timeline_field_overlap,
    _sequence_timeline_field_semantic_aliases,
    build_synthetic_mesh,
    run_scenario,
)


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)


def _write_rgb_png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


class MeshEditorDevHarnessTests(unittest.TestCase):
    def test_sequence_reference_overlap_summarizes_source_compiled_clip_refs(self) -> None:
        overlap = _sequence_reference_overlap(
            (
                "character/motion/a_idle.paa",
                "character/motion/b_idle.paa",
                "effect/hit.paem",
            ),
            (
                "CHARACTER/MOTION/A_IDLE.PAA",
                "character/motion/c_idle.paa",
            ),
            active_path="character/motion/a_idle.paa",
        )

        self.assertEqual("source_compiled_clip_reference_overlap", overlap["status"])
        self.assertEqual("proven_reference_string_overlap", overlap["confidence"])
        self.assertEqual(3, overlap["source_reference_count"])
        self.assertEqual(2, overlap["compiled_reference_count"])
        self.assertEqual(1, overlap["overlap_reference_count"])
        self.assertEqual(2, overlap["source_only_reference_count"])
        self.assertEqual(1, overlap["compiled_only_reference_count"])
        self.assertEqual(1, overlap["overlap_paa_reference_count"])
        self.assertTrue(overlap["active_clip_in_overlap"])
        self.assertEqual(("character/motion/a_idle.paa",), overlap["overlap_paths"])

    def test_sequence_lane_pair_summary_maps_source_and_compiled_lane_offsets(self) -> None:
        source_timeline = {
            "lanes": (
                {"index": 0, "path": "character/motion/a_idle.paa", "source_offset": 120, "confidence": "string_path"},
                {"index": 1, "path": "character/motion/b_idle.paa", "source_offset": 240, "confidence": "string_path"},
            )
        }
        compiled_timeline = {
            "lanes": (
                {"index": 0, "path": "CHARACTER/MOTION/A_IDLE.PAA", "source_offset": 48, "confidence": "string_path"},
            )
        }

        summary = _sequence_lane_pair_summary(
            source_timeline,
            compiled_timeline,
            active_path="character/motion/a_idle.paa",
        )

        self.assertEqual("source_compiled_lane_pair_overlap", summary["status"])
        self.assertEqual(2, summary["source_lane_count"])
        self.assertEqual(1, summary["compiled_lane_count"])
        self.assertEqual(1, summary["lane_pair_count"])
        self.assertEqual(1, summary["active_lane_pair_count"])
        pair = summary["lane_pairs"][0]
        self.assertEqual("character/motion/a_idle.paa", pair["path"])
        self.assertEqual(0, pair["source_lane_index"])
        self.assertEqual(0, pair["compiled_lane_index"])
        self.assertEqual(120, pair["source_offset"])
        self.assertEqual(48, pair["compiled_offset"])
        self.assertTrue(pair["active_clip"])
        self.assertEqual("source_compiled_lane_pair_read_only", pair["status"])

    def test_sequence_event_marker_overlap_maps_source_and_compiled_offsets(self) -> None:
        summary = _sequence_event_marker_overlap(
            {
                "event_markers": (
                    {"text": "Trigger_00", "offset": 120, "role": "event"},
                    {"text": "_startTimePiece", "offset": 240, "role": "timing"},
                    {"text": "source_only", "offset": 360, "role": "event"},
                )
            },
            {
                "event_markers": (
                    {"text": "trigger_00", "offset": 48, "role": "event"},
                    {"text": "compiled_only", "offset": 96, "role": "event"},
                )
            },
        )

        self.assertEqual("source_compiled_event_marker_overlap", summary["status"])
        self.assertEqual("proven_readable_string_overlap", summary["confidence"])
        self.assertEqual(3, summary["source_marker_count"])
        self.assertEqual(2, summary["compiled_marker_count"])
        self.assertEqual(1, summary["overlap_marker_count"])
        self.assertEqual(2, summary["source_only_marker_count"])
        self.assertEqual(1, summary["compiled_only_marker_count"])
        row = summary["overlap_markers"][0]
        self.assertEqual("Trigger_00", row["text"])
        self.assertEqual(120, row["source_offset"])
        self.assertEqual(48, row["compiled_offset"])
        self.assertEqual("source_compiled_event_marker_overlap_read_only", row["status"])

    def test_sequence_timeline_field_overlap_deduplicates_field_names(self) -> None:
        summary = _sequence_timeline_field_overlap(
            {
                "timeline_fields": (
                    {"name": "_startTimePiece", "offset": 120, "role": "timing", "declared_type": "int32"},
                    {"name": "_startTimePiece", "offset": 240, "role": "timing", "declared_type": "int32"},
                    {"name": "_framesPerSecond", "offset": 360, "role": "timing", "declared_type": "int32"},
                )
            },
            {
                "timeline_fields": (
                    {"name": "_STARTTIMEPIECE", "offset": 48, "role": "timing", "declared_type": "int32"},
                    {"name": "_startBlendTime", "offset": 96, "role": "timing", "declared_type": "float"},
                )
            },
        )

        self.assertEqual("source_compiled_timeline_field_overlap", summary["status"])
        self.assertEqual("proven_field_name_overlap", summary["confidence"])
        self.assertEqual(2, summary["source_unique_field_count"])
        self.assertEqual(2, summary["compiled_unique_field_count"])
        self.assertEqual(1, summary["overlap_field_count"])
        self.assertEqual(1, summary["source_only_field_count"])
        self.assertEqual(1, summary["compiled_only_field_count"])
        row = summary["overlap_fields"][0]
        self.assertEqual("_startTimePiece", row["name"])
        self.assertEqual(120, row["source_offset"])
        self.assertEqual(48, row["compiled_offset"])
        self.assertEqual(("_framesPerSecond",), summary["source_only_fields"])
        self.assertEqual(("_startBlendTime",), summary["compiled_only_fields"])

    def test_sequence_timeline_field_semantic_aliases_match_source_only_fields(self) -> None:
        summary = _sequence_timeline_field_semantic_aliases(
            {
                "timeline_fields": (
                    {"name": "_startBlendingTime", "offset": 120, "role": "timing", "declared_type": "float"},
                    {"name": "_endBlendingTime", "offset": 180, "role": "timing", "declared_type": "float"},
                    {"name": "_hasTransformBlend", "offset": 240, "role": "timing", "declared_type": "bool"},
                )
            },
            {
                "timeline_fields": (
                    {"name": "_startBlendTime", "offset": 48, "role": "timing", "declared_type": "float"},
                    {"name": "_hasTransformBlend", "offset": 96, "role": "timing", "declared_type": "bool"},
                )
            },
        )

        self.assertEqual("source_compiled_timeline_field_semantic_aliases", summary["status"])
        self.assertEqual("inferred_name_alias_value_unbound", summary["confidence"])
        self.assertEqual(1, summary["alias_count"])
        row = summary["alias_rows"][0]
        self.assertEqual("_startBlendingTime", row["source_name"])
        self.assertEqual("_startBlendTime", row["compiled_name"])
        self.assertEqual("startblendtime", row["alias_key"])
        self.assertEqual(120, row["source_offset"])
        self.assertEqual(48, row["compiled_offset"])
        self.assertIn("_endBlendingTime", summary["unmatched_source_fields"])
        self.assertNotIn("_hasTransformBlend", summary["unmatched_source_fields"])

    def test_sequence_path_record_context_reports_read_only_byte_window(self) -> None:
        path = "character/motion/a_idle.paa"
        actor = b"actor"
        path_bytes = path.encode("ascii")
        data = (
            b"\x00" * 8
            + struct.pack("<I", len(actor))
            + actor
            + struct.pack("<I", len(path_bytes))
            + path_bytes
            + struct.pack("<I", 30)
            + struct.pack("<f", 2.0)
        )

        context = _sequence_path_record_context(data, path, window_before=24, window_after=len(path_bytes) + 12)

        text_offset = data.index(path_bytes)
        self.assertEqual("path_record_window_recovered", context["status"])
        self.assertEqual("active_lane_record_layout_unbound", context["binding_status"])
        self.assertEqual(text_offset, context["path_text_offset"])
        self.assertEqual(text_offset - 4, context["path_length_offset"])
        self.assertEqual(2, context["length_prefixed_string_count"])
        self.assertEqual(1, context["fps_like_u32_count"])
        self.assertEqual(1, context["float32_candidate_count"])
        self.assertEqual("actor", context["length_prefixed_strings"][0]["text"])
        self.assertEqual(path, context["length_prefixed_strings"][1]["text"])
        self.assertIn((text_offset + len(path_bytes), 30), tuple((row["offset"], row["u32"]) for row in context["scalar_rows"]))

    def test_mesh_editor_native_runtime_writes_preview_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "preview_package"

            package_dir = mesh_editor_write_native_preview_package(
                build_synthetic_mesh("pam"),
                output_root=output_dir,
                use_textures=False,
            )
            manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(output_dir, package_dir)
            self.assertEqual("pam", manifest["format"])
            self.assertEqual(1, len(manifest["batches"]))
            self.assertTrue((package_dir / "geometry" / "geometry.bin").is_file())

    def test_mesh_editor_native_runtime_writes_overlay_compare_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "compare_package"
            source_mesh = build_synthetic_mesh("pam")
            edited_mesh = build_synthetic_mesh("pam")
            edited_mesh.submeshes[0].vertices[0] = (0.0, 0.0, 0.5)

            package_dir = mesh_editor_write_native_preview_package(
                edited_mesh,
                reference_mesh=source_mesh,
                output_root=output_dir,
                use_textures=False,
                display_mode="overlay",
            )
            manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual("overlay", manifest["display_mode"])
            self.assertEqual(2, len(manifest["batches"]))
            self.assertEqual("original_reference", manifest["batches"][0]["editor_identity"]["role"])
            self.assertFalse(manifest["batches"][0]["editor_identity"]["editable"])
            self.assertEqual("replacement_preview", manifest["batches"][1]["editor_identity"]["role"])
            self.assertTrue(manifest["batches"][1]["editor_identity"]["editable"])

    def test_mesh_editor_native_runtime_builds_host_command(self) -> None:
        package_dir = Path("C:/tmp/mesh-editor-package")
        status_file = Path("C:/tmp/mesh-editor-status.json")
        host = Path("C:/native/cdmw-d3d11-preview.exe")

        with patch("cdmw.ui.mesh_editor.native_preview_runtime.find_native_d3d11_host", return_value=host):
            program, args = mesh_editor_native_preview_command(
                package_dir,
                status_file,
                crash_dir=Path("C:/tmp/crash"),
                diagnostic_log=Path("C:/tmp/native.jsonl"),
            )

        self.assertEqual(str(host), program)
        self.assertIn("--preview-package", args)
        self.assertIn(str(package_dir), args)
        self.assertIn("--status-file", args)
        self.assertIn(str(status_file), args)
        self.assertIn("--crash-dir", args)
        self.assertIn(str(Path("C:/tmp/crash")), args)

    def test_real_archive_playback_sampler_reports_preview_only_geometry(self) -> None:
        mesh = build_synthetic_mesh("pac")
        mesh.has_bones = True
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        skeleton = Skeleton(bones=[Bone(index=0, name="Root", parent_index=-1)], bone_count=1)
        clip = MeshAnimationClip(
            source="sequence_clip.paa",
            duration_seconds=1.0,
            tracks=(
                MeshAnimationTrack(
                    bone_name="Root",
                    rotation_keyframes=(
                        MeshAnimationKeyframe(0.0, (0.0, 0.0, 0.0)),
                        MeshAnimationKeyframe(1.0, (0.0, 0.0, 90.0)),
                    ),
                ),
            ),
            sequence_segments=(
                MeshAnimationSequenceSegment(
                    sequence_path="sequencer/binary__/sequence_sample.paseqc",
                    clip_path="sequence_clip.paa",
                    lane_index=5,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    status="paseqc_lane_bound_to_paa_clip_preview_only_sequence_semantics_unknown",
                ),
            ),
            frame_rate=30.0,
            timing_confidence="inferred",
            timing_status="default_30fps_unproven",
        )

        sample = _sample_real_archive_paa_playback(mesh, skeleton, clip)

        self.assertTrue(sample["ready"])
        self.assertTrue(sample["enabled"])
        self.assertGreater(sample["sampled_bone_count"], 0)
        self.assertEqual(sample["sampled_bone_count"], sample["repeat_sampled_bone_count"])
        self.assertEqual(5, sample["active_sequence_lane_index"])
        self.assertEqual("sequencer/binary__/sequence_sample.paseqc", sample["active_sequence_path"])
        self.assertEqual("sequence_clip.paa", sample["active_sequence_clip_path"])
        self.assertIn("paseqc_lane_bound", sample["active_sequence_status"])
        self.assertTrue(sample["pose_changed"])
        self.assertTrue(sample["deterministic_repeat_seek"])
        self.assertEqual(sample["time_seconds"], sample["repeat_time_seconds"])
        self.assertTrue(sample["export_geometry_unchanged"])
        self.assertEqual("default_30fps_unproven", sample["timing_status"])

    def test_papr_constraint_summary_exposes_record_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = ArchiveEntry(
                path="character/model/body.papr",
                pamt_path=root / "0009" / "0.pamt",
                paz_file=root / "0009" / "0.paz",
                offset=0,
                comp_size=0,
                orig_size=0,
                flags=0,
                paz_index=0,
            )
            gap = struct.pack("<I", 0) + struct.pack("<f", 0.5) + struct.pack("<I", 24) + struct.pack("<I", 1)
            data = (
                b"PAR "
                + b"Bip01 Head\x00" + gap + b"P_Bip01 Head\x00" + gap + b"Bip01 Head_Dummy\x00"
            )
            data += (b"\x00" * (((len(data) + 3) & ~3) - len(data))) + struct.pack("<f", 3.0) + struct.pack("<f", 30.5) + gap
            data += b"Local_Euler_Z*3+30.5\x00" + gap + b"amin(Local_Euler_Z*5+9.8) -1\x00"

            summary = _papr_constraint_metadata_summary(data, entry)

            self.assertEqual(5, summary["constraint_string_evidence"])
            self.assertGreaterEqual(summary["constraint_record_candidates"], 2)
            self.assertGreaterEqual(len(summary["constraint_record_candidate_rows"]), 2)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["channel_counts"]["Local_Euler_Z"], 2)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["shape_counts"]["linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["shape_counts"]["limit_linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["numeric_role_counts"]["channel_coefficient"], 2)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["numeric_role_counts"]["additive_offset"], 2)
            self.assertGreaterEqual(summary["constraint_expression_evidence"]["numeric_role_counts"]["limit_argument"], 1)
            self.assertGreaterEqual(
                sum(summary["constraint_expression_evidence"]["syntax_signature_counts"].values()),
                1,
            )
            self.assertTrue(
                any(
                    "shape=linear_channel_transform_candidate" in signature
                    for signature in summary["constraint_expression_evidence"]["syntax_signature_counts"]
                )
            )
            self.assertEqual("unknown", summary["constraint_expression_evidence"]["semantics_confidence"])
            self.assertGreaterEqual(summary["constraint_expression_shape_counts"]["linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(summary["constraint_expression_numeric_role_counts"]["channel_coefficient"], 2)
            self.assertGreaterEqual(summary["constraint_expression_channel_counts"]["Local_Euler_Z"], 2)
            self.assertGreaterEqual(summary["constraint_limit_operator_counts"]["amin"], 1)
            self.assertGreaterEqual(summary["constraint_expression_numeric_values"], 1)
            self.assertGreaterEqual(summary["constraint_offset_evidence"]["target_offset_count"], 1)
            self.assertEqual("proven", summary["constraint_offset_evidence"]["offset_confidence"])
            self.assertGreaterEqual(summary["constraint_offset_field_counts"]["target"], 1)
            layout = summary["constraint_record_layout_evidence"]
            self.assertEqual("nearby_string_span_layout_evidence", layout["status"])
            self.assertGreaterEqual(layout["candidate_count"], 2)
            self.assertGreater(layout["max_span_size"], 0)
            self.assertGreaterEqual(layout["field_sequence_counts"]["parent>helper>target>expression"], 2)
            self.assertEqual("proven_decoded_string_offset_order", layout["field_sequence_confidence"])
            self.assertGreaterEqual(layout["gap_status_counts"]["binary_like_interfield_gap_bytes_unbound"], 1)
            self.assertGreaterEqual(sum(layout["gap_class_counts"].values()), 1)
            self.assertGreaterEqual(layout["gap_pair_count"], 1)
            self.assertGreater(layout["max_gap_size"], 0)
            self.assertGreaterEqual(layout["gap_scalar_status_counts"]["unbound_interfield_scalar_candidates"], 1)
            self.assertGreaterEqual(layout["gap_scalar_kind_counts"]["f32_unit_candidate"], 1)
            self.assertGreaterEqual(layout["gap_aligned_word_count"], 1)
            self.assertGreaterEqual(layout["gap_scalar_candidate_count"], 1)
            self.assertGreaterEqual(layout["gap_numeric_match_status_counts"]["unbound_scalar_numeric_constant_matches"], 1)
            self.assertGreaterEqual(layout["gap_numeric_match_role_counts"]["channel_coefficient"], 1)
            self.assertGreaterEqual(layout["gap_numeric_match_role_counts"]["additive_offset"], 1)
            self.assertGreaterEqual(layout["gap_numeric_match_pair_counts"]["target>expression"], 1)
            self.assertGreaterEqual(sum(layout["gap_numeric_match_value_confidence_counts"].values()), 1)
            self.assertGreaterEqual(
                layout["gap_numeric_match_value_confidence_counts"]["exact_float32_numeric_value_match_layout_unproven"],
                1,
            )
            self.assertGreaterEqual(layout["gap_numeric_match_family_counts"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(layout["gap_numeric_match_family_row_counts"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(
                layout["gap_numeric_match_family_role_counts"]["driver_expression_candidate"]["channel_coefficient"],
                1,
            )
            self.assertGreaterEqual(
                layout["gap_numeric_match_family_pair_counts"]["driver_expression_candidate"]["target>expression"],
                1,
            )
            self.assertGreaterEqual(
                layout["gap_numeric_match_family_value_confidence_counts"]["driver_expression_candidate"][
                    "exact_float32_numeric_value_match_layout_unproven"
                ],
                1,
            )
            self.assertGreaterEqual(sum(layout["gap_numeric_match_signature_counts"].values()), 1)
            self.assertGreaterEqual(sum(layout["gap_numeric_match_candidate_relative_signature_counts"].values()), 1)
            self.assertTrue(
                any(
                    "family=driver_expression_candidate" in signature
                    and "role=channel_coefficient" in signature
                    for signature in layout["gap_numeric_match_signature_counts"]
                )
            )
            self.assertTrue(
                any(
                    "family=driver_expression_candidate" in signature
                    and "rel=" in signature
                    for signature in layout["gap_numeric_match_candidate_relative_signature_counts"]
                )
            )
            self.assertGreaterEqual(sum(layout["gap_numeric_match_previous_delta_counts"].values()), 1)
            self.assertGreaterEqual(sum(layout["gap_numeric_match_next_delta_counts"].values()), 1)
            self.assertGreaterEqual(sum(layout["gap_numeric_match_candidate_relative_offset_counts"].values()), 1)
            self.assertEqual(
                "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
                layout["gap_numeric_match_offset_confidence"],
            )
            self.assertEqual(
                "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
                layout["gap_numeric_match_candidate_relative_offset_confidence"],
            )
            self.assertGreaterEqual(layout["gap_numeric_match_count"], 1)
            self.assertGreaterEqual(len(layout["gap_numeric_match_rows"]), 1)
            self.assertEqual(
                summary["constraint_record_candidate_rows"][0]["offset"],
                layout["gap_numeric_match_rows"][0]["candidate_offset"],
            )
            self.assertEqual(
                layout["gap_numeric_match_rows"][0]["match_offset"]
                - layout["gap_numeric_match_rows"][0]["candidate_offset"],
                layout["gap_numeric_match_rows"][0]["candidate_relative_offset"],
            )
            self.assertEqual("driver_expression_candidate", layout["gap_numeric_match_rows"][0]["constraint_type"])
            self.assertEqual("target>expression", layout["gap_numeric_match_rows"][0]["between_fields"])
            self.assertIn(
                layout["gap_numeric_match_rows"][0]["value_confidence"],
                {
                    "exact_u32_numeric_value_match_layout_unproven",
                    "exact_float32_numeric_value_match_layout_unproven",
                    "approx_float32_numeric_value_match_layout_unproven",
                },
            )
            self.assertIn("candidate_relative_match_signature", layout["gap_numeric_match_rows"][0])
            self.assertGreaterEqual(
                layout["layout_status_counts"]["nearby_string_span_only_value_layout_unproven"],
                2,
            )
            first_candidate = summary["constraint_record_candidate_rows"][0]
            self.assertGreater(first_candidate["record_span_size"], 0)
            self.assertGreaterEqual(first_candidate["record_span_field_count"], 2)
            self.assertEqual(
                "nearby_string_span_only_value_layout_unproven",
                first_candidate["record_layout_status"],
            )
            self.assertEqual(("parent", "helper", "target", "expression"), first_candidate["record_field_sequence"])
            self.assertEqual("proven_decoded_string_offset_order", first_candidate["record_field_sequence_confidence"])
            self.assertEqual("linear_channel_transform_candidate", first_candidate["expression_shape"])
            self.assertIn("shape=linear_channel_transform_candidate", first_candidate["expression_syntax_signature"])
            self.assertEqual("inferred_readable_expression_syntax", first_candidate["expression_shape_confidence"])
            self.assertEqual("solver_semantics_unknown", first_candidate["expression_shape_status"])
            self.assertEqual(("channel_coefficient", "additive_offset"), first_candidate["expression_numeric_roles"])
            self.assertEqual("inferred_readable_expression_syntax", first_candidate["expression_numeric_role_confidence"])
            self.assertEqual("binary_like_interfield_gap_bytes_unbound", first_candidate["record_gap_status"])
            self.assertGreaterEqual(sum(first_candidate["record_gap_class_counts"].values()), 1)
            self.assertGreater(first_candidate["record_gap_max_size"], 0)
            self.assertEqual("unbound_interfield_scalar_candidates", first_candidate["record_gap_scalar_status"])
            self.assertGreaterEqual(first_candidate["record_gap_scalar_kind_counts"]["f32_unit_candidate"], 1)
            self.assertGreaterEqual(first_candidate["record_gap_scalar_candidate_count"], 1)
            self.assertEqual("unbound_scalar_numeric_constant_matches", first_candidate["record_gap_numeric_match_status"])
            self.assertGreaterEqual(first_candidate["record_gap_numeric_match_role_counts"]["channel_coefficient"], 1)
            self.assertGreaterEqual(first_candidate["record_gap_numeric_match_role_counts"]["additive_offset"], 1)
            self.assertGreaterEqual(first_candidate["record_gap_numeric_match_pair_counts"]["target>expression"], 1)
            self.assertGreaterEqual(
                first_candidate["record_gap_numeric_match_value_confidence_counts"][
                    "exact_float32_numeric_value_match_layout_unproven"
                ],
                1,
            )
            self.assertGreaterEqual(sum(first_candidate["record_gap_numeric_match_signature_counts"].values()), 1)
            self.assertGreaterEqual(
                sum(first_candidate["record_gap_numeric_match_candidate_relative_signature_counts"].values()),
                1,
            )
            self.assertGreaterEqual(sum(first_candidate["record_gap_numeric_match_previous_delta_counts"].values()), 1)
            self.assertGreaterEqual(sum(first_candidate["record_gap_numeric_match_next_delta_counts"].values()), 1)
            self.assertGreaterEqual(
                sum(first_candidate["record_gap_numeric_match_candidate_relative_offset_counts"].values()),
                1,
            )
            self.assertGreaterEqual(first_candidate["record_gap_numeric_match_count"], 1)
            self.assertEqual("blocked_record_layout_unproven", summary["constraint_record_candidate_rows"][0]["solver_status"])
            self.assertFalse(summary["constraint_solving_supported"])

    def test_papr_read_status_aggregates_expression_and_offset_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = ArchiveEntry(
                path="character/model/body.papr",
                pamt_path=root / "0009" / "0.pamt",
                paz_file=root / "0009" / "0.paz",
                offset=0,
                comp_size=0,
                orig_size=0,
                flags=0,
                paz_index=0,
            )
            gap = struct.pack("<I", 0) + struct.pack("<f", 0.5) + struct.pack("<I", 24) + struct.pack("<I", 1)
            data = (
                b"PAR "
                + b"Bip01 Head\x00" + gap + b"P_Bip01 Head\x00" + gap + b"Bip01 Head_Dummy\x00"
            )
            data += (b"\x00" * (((len(data) + 3) & ~3) - len(data))) + struct.pack("<f", 3.0) + struct.pack("<f", 30.5) + gap
            data += b"Local_Euler_Z*3+30.5\x00" + gap + b"amin(Local_Euler_Z*5+9.8) -1\x00"

            with patch("tools.mesh_editor_dev_harness.read_archive_entry_data", return_value=(data, False, "plain")):
                status = _real_archive_papr_read_status((entry,))

            self.assertEqual(1, status["entry_count"])
            self.assertEqual(1, status["read_ok_count"])
            self.assertGreaterEqual(status["constraint_expression_shape_totals"]["linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(status["constraint_expression_shape_totals"]["limit_linear_channel_transform_candidate"], 1)
            self.assertGreaterEqual(sum(status["constraint_expression_syntax_signature_totals"].values()), 1)
            self.assertTrue(
                any(
                    "shape=linear_channel_transform_candidate" in signature
                    for signature in status["constraint_expression_syntax_signature_totals"]
                )
            )
            self.assertGreaterEqual(status["constraint_expression_numeric_role_totals"]["channel_coefficient"], 2)
            self.assertGreaterEqual(status["constraint_expression_numeric_role_totals"]["additive_offset"], 2)
            self.assertGreaterEqual(status["constraint_expression_numeric_role_totals"]["limit_argument"], 1)
            self.assertGreaterEqual(status["constraint_expression_channel_totals"]["Local_Euler_Z"], 2)
            self.assertGreaterEqual(status["constraint_limit_operator_totals"]["amin"], 1)
            self.assertGreaterEqual(status["constraint_metadata_totals"]["constraint_expression_numeric_values"], 1)
            self.assertGreaterEqual(status["constraint_offset_field_totals"]["target"], 1)
            self.assertGreaterEqual(status["constraint_candidate_family_totals"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(status["constraint_candidate_family_totals"]["local_transform_limit_candidate"], 1)
            self.assertGreaterEqual(status["constraint_candidate_solver_status_totals"]["blocked_record_layout_unproven"], 2)
            self.assertGreaterEqual(status["constraint_candidate_family_field_totals"]["driver_expression_candidate"]["target"], 1)
            self.assertGreaterEqual(status["constraint_candidate_family_field_totals"]["local_transform_limit_candidate"]["expression"], 1)
            self.assertGreaterEqual(
                status["constraint_candidate_family_channel_totals"]["driver_expression_candidate"]["Local_Euler_Z"],
                1,
            )
            self.assertGreaterEqual(
                status["constraint_candidate_family_channel_totals"]["local_transform_limit_candidate"]["Local_Euler_Z"],
                1,
            )
            self.assertGreaterEqual(status["constraint_candidate_family_limit_totals"]["local_transform_limit_candidate"]["amin"], 1)
            self.assertGreaterEqual(
                status["constraint_record_layout_status_totals"]["nearby_string_span_only_value_layout_unproven"],
                2,
            )
            self.assertGreaterEqual(status["constraint_record_field_sequence_totals"]["parent>helper>target>expression"], 2)
            self.assertGreater(status["constraint_record_layout_max_span_size"], 0)
            self.assertGreaterEqual(status["constraint_record_gap_status_totals"]["binary_like_interfield_gap_bytes_unbound"], 1)
            self.assertGreaterEqual(sum(status["constraint_record_gap_class_totals"].values()), 1)
            self.assertGreaterEqual(status["constraint_record_gap_pair_total"], 1)
            self.assertGreater(status["constraint_record_gap_max_size"], 0)
            self.assertGreaterEqual(status["constraint_record_gap_scalar_status_totals"]["unbound_interfield_scalar_candidates"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_scalar_kind_totals"]["f32_unit_candidate"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_aligned_word_total"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_scalar_candidate_total"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_status_totals"]["unbound_scalar_numeric_constant_matches"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_role_totals"]["channel_coefficient"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_role_totals"]["additive_offset"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_pair_totals"]["target>expression"], 1)
            self.assertGreaterEqual(
                sum(status["constraint_record_gap_numeric_match_value_confidence_totals"].values()),
                1,
            )
            self.assertGreaterEqual(
                status["constraint_record_gap_numeric_match_value_confidence_totals"][
                    "exact_float32_numeric_value_match_layout_unproven"
                ],
                1,
            )
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_family_totals"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_family_row_totals"]["driver_expression_candidate"], 1)
            self.assertGreaterEqual(
                status["constraint_record_gap_numeric_match_family_role_totals"][
                    "driver_expression_candidate"
                ]["channel_coefficient"],
                1,
            )
            self.assertGreaterEqual(
                status["constraint_record_gap_numeric_match_family_pair_totals"][
                    "driver_expression_candidate"
                ]["target>expression"],
                1,
            )
            self.assertGreaterEqual(
                status["constraint_record_gap_numeric_match_family_value_confidence_totals"][
                    "driver_expression_candidate"
                ]["exact_float32_numeric_value_match_layout_unproven"],
                1,
            )
            self.assertGreaterEqual(
                sum(status["constraint_record_gap_numeric_match_signature_totals"].values()),
                1,
            )
            self.assertGreaterEqual(
                sum(status["constraint_record_gap_numeric_match_candidate_relative_signature_totals"].values()),
                1,
            )
            self.assertTrue(
                any(
                    "family=driver_expression_candidate" in signature
                    and "role=channel_coefficient" in signature
                    for signature in status["constraint_record_gap_numeric_match_signature_totals"]
                )
            )
            self.assertTrue(
                any(
                    "family=driver_expression_candidate" in signature
                    and "rel=" in signature
                    for signature in status["constraint_record_gap_numeric_match_candidate_relative_signature_totals"]
                )
            )
            self.assertGreaterEqual(sum(status["constraint_record_gap_numeric_match_previous_delta_totals"].values()), 1)
            self.assertGreaterEqual(sum(status["constraint_record_gap_numeric_match_next_delta_totals"].values()), 1)
            self.assertGreaterEqual(
                sum(status["constraint_record_gap_numeric_match_candidate_relative_offset_totals"].values()),
                1,
            )
            self.assertEqual(
                "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
                status["constraint_record_gap_numeric_match_offset_confidence"],
            )
            self.assertEqual(
                "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
                status["constraint_record_gap_numeric_match_candidate_relative_offset_confidence"],
            )
            self.assertGreaterEqual(status["constraint_record_gap_numeric_match_total"], 1)
            self.assertGreaterEqual(len(status["constraint_record_gap_numeric_match_rows"]), 1)
            self.assertEqual("character/model/body.papr", status["constraint_record_gap_numeric_match_rows"][0]["path"])
            self.assertEqual("driver_expression_candidate", status["constraint_record_gap_numeric_match_rows"][0]["constraint_type"])
            self.assertEqual("target>expression", status["constraint_record_gap_numeric_match_rows"][0]["between_fields"])
            self.assertFalse(status["constraint_solving_supported"])

    def test_service_smoke_writes_result_json_without_starting_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("service-smoke", output_dir)

            self.assertTrue(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            evidence_report = json.loads((output_dir / "evidence_report.json").read_text(encoding="utf-8"))
            self.assertEqual("cdmw_mesh_editor_evidence_report_v1", evidence_report["schema"])
            self.assertEqual("service-smoke", evidence_report["scenario"])
            self.assertIn("preview-only", evidence_report["state_labels"])
            self.assertIn(".paseqc", evidence_report["corpus_manifest"]["formats"])
            self.assertTrue(any(row["feature"] == "Direct archive mutation" and row["state"] == "blocked" for row in evidence_report["feature_status_rows"]))
            self.assertEqual("service-smoke", result["scenario"])
            self.assertGreater(result["service"]["session"]["face_count"], 2)
            selection_operations = result["service"]["selection_operations"]
            self.assertTrue(selection_operations["ok"])
            self.assertEqual({"0": [0, 3]}, selection_operations["added"]["vertices_by_submesh"])
            self.assertEqual({"0": [[1, 2]]}, selection_operations["subtracted"]["edges_by_submesh"])
            self.assertEqual({"0": [2]}, selection_operations["toggled"]["vertices_by_submesh"])
            self.assertEqual({}, selection_operations["toggled"]["faces_by_submesh"])
            selection_pruning = result["service"]["selection_pruning"]
            self.assertTrue(selection_pruning["ok"])
            self.assertEqual({"0": [[0, 1]]}, selection_pruning["malformed"]["edges_by_submesh"])
            self.assertEqual({"0": [1]}, selection_pruning["malformed"]["faces_by_submesh"])
            self.assertEqual({"0": [[0, 3]]}, selection_pruning["loose_edge"]["edges_by_submesh"])
            history_selection = result["service"]["history_selection"]
            self.assertTrue(history_selection["ok"])
            self.assertEqual([1], history_selection["before_undo"]["source_indices"])
            self.assertEqual({}, history_selection["after_undo"]["faces_by_submesh"])
            self.assertEqual([], history_selection["after_undo"]["source_indices"])
            self.assertEqual(1, history_selection["submesh_count_after_undo"])
            history_context = result["service"]["history_context"]
            self.assertTrue(history_context["ok"])
            self.assertEqual({"0": [0]}, history_context["after_undo"]["faces_by_submesh"])
            self.assertEqual({"1": [0]}, history_context["after_redo"]["faces_by_submesh"])
            self.assertEqual([1], history_context["after_redo"]["source_indices"])
            self.assertEqual("object", history_context["mode_restore"]["after_undo"])
            self.assertEqual("edit", history_context["mode_restore"]["after_redo"])
            uv_operations = result["service"]["uv_operations"]
            self.assertTrue(uv_operations["ok"])
            self.assertEqual({"0": [1, 2]}, uv_operations["pivot_flip"]["changed_vertices"])
            self.assertEqual([-0.5, -0.5], uv_operations["pivot_flip"]["uvs"][1])
            self.assertEqual([0.5, 0.5], uv_operations["pivot_flip"]["uvs"][2])
            transform_targets = result["service"]["transform_targets"]
            self.assertTrue(transform_targets["ok"])
            self.assertEqual([], transform_targets["empty"]["command"]["affected_submesh_indices"])
            self.assertEqual([-0.75, -0.75, 0.0], transform_targets["empty"]["vertices"][0])
            self.assertEqual([], transform_targets["stale_edge"]["command"]["affected_submesh_indices"])
            self.assertEqual([-0.75, -0.75, 0.0], transform_targets["stale_edge"]["vertices"][0])
            self.assertEqual([], transform_targets["non_edge"]["command"]["affected_submesh_indices"])

            self.assertEqual([-0.75, -0.75, 0.0], transform_targets["non_edge"]["vertices"][0])
            self.assertEqual([0.75, 0.75, 0.0], transform_targets["non_edge"]["vertices"][3])
            self.assertEqual([-0.75, -0.75, 0.5], transform_targets["source"]["vertices"][0])
            topology_targets = result["service"]["topology_targets"]
            self.assertTrue(topology_targets["ok"])
            self.assertEqual([], topology_targets["duplicate_empty"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["duplicate_empty"]["submesh_count"])
            self.assertEqual([], topology_targets["duplicate_invalid_face"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["duplicate_invalid_face"]["submesh_count"])
            self.assertEqual([], topology_targets["duplicate_malformed_face"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["duplicate_malformed_face"]["submesh_count"])
            self.assertEqual([], topology_targets["mirror_empty"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["mirror_empty"]["submesh_count"])
            self.assertEqual([], topology_targets["mirror_invalid_face"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["mirror_invalid_face"]["submesh_count"])
            self.assertEqual([1], topology_targets["duplicate_source"]["command"]["affected_submesh_indices"])
            self.assertEqual([1], topology_targets["mirror_source"]["command"]["affected_submesh_indices"])
            material_operations = result["service"]["material_operations"]
            self.assertTrue(material_operations["ok"])
            self.assertTrue(material_operations["face_assign"]["command"]["topology_changed"])
            self.assertEqual(["harness_material", "face_material"], [submesh["material"] for submesh in material_operations["face_assign"]["submeshes"]])
            self.assertEqual({"roughness": 0.4}, material_operations["face_assign"]["submeshes"][1]["overrides"])
            self.assertTrue(material_operations["face_copy"]["command"]["topology_changed"])
            self.assertEqual(["harness_material", "harness_material_b", "harness_material"], [submesh["material"] for submesh in material_operations["face_copy"]["submeshes"]])
            self.assertEqual({"roughness": 0.2, "metalness": 0.6}, material_operations["face_copy"]["submeshes"][2]["overrides"])
            plain_reset = material_operations["plain_assign_reset"]
            self.assertEqual("plain_material", plain_reset["material"])
            self.assertFalse(plain_reset["has_route_metadata"])
            self.assertEqual({}, plain_reset["overrides"])
            edge_face_topology = result["service"]["edge_face_topology"]
            self.assertTrue(edge_face_topology["ok"])
            self.assertEqual(3, edge_face_topology["copied_vertex_count"])
            self.assertEqual(1, edge_face_topology["copied_face_count"])
            self.assertEqual([[0, 1, 2]], edge_face_topology["copied_faces"])
            self.assertEqual(2, edge_face_topology["mirror"]["submesh_count"])
            self.assertEqual(3, edge_face_topology["mirror"]["vertex_count"])
            self.assertEqual(1, edge_face_topology["mirror"]["face_count"])
            self.assertEqual([[0, 2, 1]], edge_face_topology["mirror"]["faces"])
            self.assertEqual([[0.75, -0.75, 0.0], [-0.75, -0.75, 0.0], [0.75, 0.75, 0.0]], edge_face_topology["mirror"]["vertices"])
            self.assertEqual(3, edge_face_topology["delete"]["vertex_count"])
            self.assertEqual(1, edge_face_topology["delete"]["face_count"])
            self.assertEqual([[0, 2, 1]], edge_face_topology["delete"]["faces"])
            self.assertEqual(4, edge_face_topology["dissolve"]["vertex_count"])
            self.assertEqual(1, edge_face_topology["dissolve"]["face_count"])
            self.assertEqual([[1, 3, 2]], edge_face_topology["dissolve"]["faces"])
            self.assertEqual(4, edge_face_topology["internal_dissolve"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["internal_dissolve"]["face_count"])
            self.assertEqual([[0, 1, 3], [0, 3, 2]], edge_face_topology["internal_dissolve"]["faces"])
            self.assertEqual(7, edge_face_topology["subdivide"]["vertex_count"])
            self.assertEqual(5, edge_face_topology["subdivide"]["face_count"])
            self.assertEqual([1, 3, 2], edge_face_topology["subdivide"]["faces"][-1])
            self.assertEqual(5, edge_face_topology["loop_cut_two_edges"]["vertex_count"])
            self.assertEqual(3, edge_face_topology["loop_cut_two_edges"]["face_count"])
            self.assertEqual([[3, 1, 4], [0, 3, 4], [0, 4, 2]], edge_face_topology["loop_cut_two_edges"]["faces"])
            self.assertEqual({"0": [3, 4]}, edge_face_topology["loop_cut_two_edges"]["changed_vertices"])
            self.assertEqual(5, edge_face_topology["loop_cut_multi"]["vertex_count"])
            self.assertEqual(3, edge_face_topology["loop_cut_multi"]["face_count"])
            self.assertEqual([[0, 3, 2], [3, 4, 2], [4, 1, 2]], edge_face_topology["loop_cut_multi"]["faces"])
            self.assertEqual({"0": [3, 4]}, edge_face_topology["loop_cut_multi"]["changed_vertices"])
            self.assertAlmostEqual(-0.25, edge_face_topology["loop_cut_multi"]["vertices"][3][0], places=6)
            self.assertAlmostEqual(0.25, edge_face_topology["loop_cut_multi"]["vertices"][4][0], places=6)
            self.assertAlmostEqual(1.0, edge_face_topology["loop_cut_multi"]["uvs"][3][1], places=6)
            self.assertAlmostEqual(1.0, edge_face_topology["loop_cut_multi"]["uvs"][4][1], places=6)
            self.assertEqual(4, edge_face_topology["loop_cut_factor"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["loop_cut_factor"]["face_count"])
            self.assertEqual({"0": [3]}, edge_face_topology["loop_cut_factor"]["changed_vertices"])
            self.assertAlmostEqual(-0.375, edge_face_topology["loop_cut_factor"]["vertices"][3][0], places=6)
            self.assertAlmostEqual(0.25, edge_face_topology["loop_cut_factor"]["uvs"][3][0], places=6)
            self.assertEqual([[0, 3, 2], [3, 1, 2]], edge_face_topology["loop_cut_factor"]["faces"])
            self.assertEqual(1, edge_face_topology["split"]["submesh_count"])
            self.assertEqual(6, edge_face_topology["split"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["split"]["face_count"])
            self.assertEqual([[0, 4, 5], [1, 3, 2]], edge_face_topology["split"]["faces"])
            self.assertEqual({"0": [4, 5]}, edge_face_topology["split"]["changed_vertices"])
            self.assertEqual(2, edge_face_topology["separate"]["submesh_count"])
            self.assertEqual(1, edge_face_topology["separate"]["source_face_count"])
            self.assertEqual(1, edge_face_topology["separate"]["moved_face_count"])
            self.assertEqual(3, edge_face_topology["fill"]["face_count"])
            self.assertEqual([0, 1, 3], edge_face_topology["fill"]["faces"][-1])
            self.assertEqual(2, edge_face_topology["quad_fill"]["face_count"])
            self.assertEqual([[0, 1, 3], [0, 3, 2]], edge_face_topology["quad_fill"]["faces"])
            self.assertEqual(2, edge_face_topology["face_fill"]["face_count"])
            self.assertEqual(2, edge_face_topology["existing_fill"]["face_count"])
            self.assertEqual(8, edge_face_topology["extrude"]["vertex_count"])
            self.assertEqual(12, edge_face_topology["extrude"]["face_count"])
            self.assertEqual({"0": [4, 5, 6, 7]}, edge_face_topology["extrude"]["changed_vertices"])
            self.assertEqual(6, edge_face_topology["edge_extrude"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["edge_extrude"]["face_count"])
            self.assertEqual([[0, 1, 5], [0, 5, 4]], edge_face_topology["edge_extrude"]["faces"])
            self.assertEqual({"0": [4, 5]}, edge_face_topology["edge_extrude"]["changed_vertices"])
            self.assertAlmostEqual(0.2, edge_face_topology["edge_extrude"]["vertices"][4][2], places=6)
            self.assertAlmostEqual(0.2, edge_face_topology["edge_extrude"]["vertices"][5][2], places=6)
            self.assertEqual(edge_face_topology["edge_extrude"]["uvs"][0], edge_face_topology["edge_extrude"]["uvs"][4])
            self.assertEqual(edge_face_topology["edge_extrude"]["uvs"][1], edge_face_topology["edge_extrude"]["uvs"][5])
            self.assertFalse(edge_face_topology["non_edge_extrude"]["command"]["topology_changed"])
            self.assertEqual([], edge_face_topology["non_edge_extrude"]["command"]["affected_submesh_indices"])
            self.assertEqual(4, edge_face_topology["non_edge_extrude"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["non_edge_extrude"]["face_count"])
            self.assertEqual(8, edge_face_topology["inset"]["vertex_count"])
            self.assertEqual(10, edge_face_topology["inset"]["face_count"])
            self.assertEqual({"0": [4, 5, 6, 7]}, edge_face_topology["inset"]["changed_vertices"])
            self.assertEqual(4, edge_face_topology["inset_zero"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["inset_zero"]["face_count"])
            self.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["inset_zero"]["faces"])
            self.assertFalse(edge_face_topology["inset_zero"]["command"]["topology_changed"])
            self.assertEqual(4, edge_face_topology["merge"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["merge"]["face_count"])
            self.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["merge"]["faces"])
            self.assertEqual(4, edge_face_topology["weld"]["vertex_count"])
            self.assertEqual(2, edge_face_topology["weld"]["face_count"])
            self.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["weld"]["faces"])
            self.assertEqual(2, edge_face_topology["bridge"]["face_count"])
            self.assertEqual([[0, 1, 3], [0, 3, 2]], edge_face_topology["bridge"]["faces"])
            self.assertEqual(2, edge_face_topology["filled_bridge"]["face_count"])
            self.assertEqual(2, edge_face_topology["face_flip_normals"]["face_count"])
            self.assertEqual([], edge_face_topology["empty_recalculate_normals"]["command"]["affected_submesh_indices"])
            self.assertEqual([[0.0, 0.0, -1.0]] * 4, edge_face_topology["empty_recalculate_normals"]["normals"])
            self.assertEqual([0], edge_face_topology["source_recalculate_normals"]["command"]["affected_submesh_indices"])
            self.assertEqual([[0.0, 0.0, 1.0]] * 4, edge_face_topology["source_recalculate_normals"]["normals"])
            self.assertEqual([[0, 2, 1], [1, 3, 2]], edge_face_topology["face_flip_normals"]["faces"])
            self.assertFalse(edge_face_topology["face_flip_normals"]["command"]["topology_changed"])
            self.assertEqual(2, edge_face_topology["empty_flip_normals"]["face_count"])
            self.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["empty_flip_normals"]["faces"])
            self.assertFalse(edge_face_topology["empty_flip_normals"]["command"]["topology_changed"])
            self.assertEqual([], edge_face_topology["empty_flip_normals"]["command"]["affected_submesh_indices"])
            self.assertEqual(2, edge_face_topology["source_flip_normals"]["face_count"])
            self.assertEqual([[0, 2, 1], [1, 2, 3]], edge_face_topology["source_flip_normals"]["faces"])
            self.assertFalse(edge_face_topology["source_flip_normals"]["command"]["topology_changed"])
            self.assertEqual([0], edge_face_topology["source_flip_normals"]["command"]["affected_submesh_indices"])
            coverage = result["service"]["coverage"]
            self.assertTrue(coverage["ok"])
            self.assertEqual([], coverage["missing_actions"])
            self.assertEqual(set(MESH_EDIT_ACTIONS) | {"undo", "redo"}, set(coverage["covered_actions"]))
            self.assertEqual(["pac", "pam", "pamlod"], coverage["covered_formats"])
            palette = result["service"]["palette"]
            self.assertTrue(palette["ok"])
            self.assertEqual([], palette["missing_actions"])
            self.assertEqual({action.key for action in MESH_EDITOR_ACTIONS}, set(palette["covered_actions"]))
            commands = {command["key"]: command for command in palette["commands"]}
            self.assertGreater(commands["select_face"]["selection_group_count"], 0)
            self.assertTrue(commands["select_face"]["selection_refresh"])
            self.assertTrue(commands["duplicate"]["selection_refresh"])
            self.assertTrue(commands["undo"]["selection_refresh"])
            self.assertGreater(commands["uv_flip_u"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_normalize"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_align_u"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_align_v"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_planar_project"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_box_project"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_cylindrical_project"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_pack"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_snap_grid"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["uv_snap_pixels"]["vertex_update_group_count"], 0)
            self.assertGreater(commands["material_assign"]["material_override_group_count"], 0)
            self.assertGreater(commands["material_copy"]["material_override_group_count"], 0)

    def test_real_archive_rigging_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-rigging-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_animation_binding_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-animation-binding-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive_animation"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_sequence_binding_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-sequence-binding-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive_sequence"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_app_workflow_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-app-workflow-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive_app"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_png_capture_summary_rejects_blank_capture(self) -> None:
        width = 64
        height = 64
        blank_row = bytes((0, 0, 0)) * width
        visible_rows: list[bytes] = []
        for y in range(height):
            row = bytearray()
            for x in range(width):
                row.extend((220, 220, 220) if x == y or x == width - y - 1 else (18, 24, 30))
            visible_rows.append(bytes(row))

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            blank_path = output_dir / "blank.png"
            visible_path = output_dir / "visible.png"
            _write_rgb_png(blank_path, width, height, [blank_row] * height)
            _write_rgb_png(visible_path, width, height, visible_rows)

            blank_summary = _png_capture_summary(blank_path)
            visible_summary = _png_capture_summary(visible_path)

            self.assertFalse(blank_summary["ok"])
            self.assertEqual(1, blank_summary["unique_rgb_count"])
            self.assertTrue(visible_summary["ok"])
            self.assertGreater(visible_summary["unique_rgb_count"], 1)
            self.assertGreater(visible_summary["bright_sample_count"], 0)

    def test_synthetic_mesh_builder_covers_target_formats(self) -> None:
        for mesh_format in ("pac", "pam", "pamlod"):
            with self.subTest(mesh_format=mesh_format):
                mesh = build_synthetic_mesh(mesh_format)

                self.assertEqual(mesh_format, mesh.format)
                self.assertTrue(str(mesh.path).endswith(f".{mesh_format}"))

        with self.assertRaisesRegex(ValueError, "Unsupported synthetic mesh format"):
            build_synthetic_mesh("fbx")

    def test_preview_and_live_edit_payloads_use_source_identity(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].preview_native_material_overrides = {"roughness": 0.4, "metalness": 0.2}
        prepared = mesh_to_native_preview(mesh)
        triangle_groups = mesh_edit_triangle_groups(mesh)
        material_groups = mesh_edit_material_override_groups(mesh, (0,))
        mesh_to_reset = build_synthetic_mesh()
        reset_material_groups = mesh_edit_material_override_groups(mesh_to_reset, (0,), include_defaults=True)
        vertex_groups = mesh_edit_vertex_update_groups(mesh, {0: (0, 2)})
        selection_groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}))

        self.assertEqual(1, len(prepared.batches))
        self.assertEqual({"roughness": 0.4, "metalness": 0.2}, prepared.batches[0].preview_native_material_overrides)
        self.assertEqual(6, prepared.batches[0].index_count)
        self.assertEqual((0, 1, 2, 1, 3, 2), prepared.batches[0].source_vertex_indices)
        self.assertEqual([0], [group["source_submesh_index"] for group in triangle_groups])
        self.assertEqual("harness_material", triangle_groups[0]["material_name"])
        self.assertEqual([0], material_groups[0]["source_submesh_indices"])
        self.assertEqual(0.4, material_groups[0]["roughness"])
        self.assertEqual(str(mesh_to_reset.submeshes[0].material), reset_material_groups[0]["material_name"])
        self.assertEqual(0.0, reset_material_groups[0]["roughness"])
        self.assertEqual(0.0, reset_material_groups[0]["metalness"])
        self.assertEqual(1.0, reset_material_groups[0]["texture_brightness"])
        self.assertEqual([0, 1, 2, 3], triangle_groups[0]["source_vertex_indices"])
        self.assertEqual(8, len(triangle_groups[0]["uvs"]))
        self.assertEqual([0, 2], vertex_groups[0]["source_vertex_indices"])
        self.assertEqual(6, len(vertex_groups[0]["positions"]))
        self.assertEqual([0.0, 1.0, 0.0, 0.0], vertex_groups[0]["uvs"])
        self.assertEqual([0, 1, 2], selection_groups[0]["source_vertex_indices"])
        self.assertEqual([0], selection_groups[0]["source_face_indices"])
        self.assertEqual(1, len(selection_groups[0]["source_face_indices"]))
        edge_selection_groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)}))
        self.assertEqual([[1, 2]], edge_selection_groups[0]["source_edges"])
        non_edge_selection_groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3),)}))
        self.assertEqual([], non_edge_selection_groups)

        loose_edge_mesh = build_synthetic_mesh()
        loose_edge_mesh.submeshes[0].faces = []
        loose_edge_mesh.submeshes[0].face_count = 0
        loose_edge_mesh.total_faces = 0
        loose_edge_selection_groups = mesh_edit_selection_groups(
            loose_edge_mesh,
            MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3),)}),
        )
        self.assertEqual([[0, 3]], loose_edge_selection_groups[0]["source_edges"])
        self.assertEqual([0, 3], loose_edge_selection_groups[0]["source_vertex_indices"])

    def test_preview_payloads_ignore_malformed_faces(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].faces = [(0, "bad", 2), (0, 1, 2), (0, float("inf"), 2), (1, 99, 2), (-1, 2, 3)]  # type: ignore[list-item]
        mesh.submeshes[0].face_count = len(mesh.submeshes[0].faces)
        mesh.total_faces = len(mesh.submeshes[0].faces)

        prepared = mesh_to_native_preview(mesh)
        triangle_groups = mesh_edit_triangle_groups(mesh)
        selection_groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1, 2)}))

        self.assertEqual(1, prepared.face_count)
        self.assertEqual(3, prepared.batches[0].index_count)
        self.assertEqual((0, 1, 2), prepared.batches[0].source_vertex_indices)
        self.assertEqual((1,), prepared.batches[0].source_face_indices)
        self.assertEqual([1], triangle_groups[0]["source_face_indices"])
        self.assertEqual([0, 1, 2], triangle_groups[0]["indices"])
        self.assertEqual([0, 1, 2], selection_groups[0]["source_vertex_indices"])
        self.assertEqual([1], selection_groups[0]["source_face_indices"])

    def test_preview_payloads_sanitize_non_finite_vertex_data(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.total_vertices = float("inf")  # type: ignore[assignment]
        mesh.submeshes[0].vertices[1] = (float("inf"), 5.0, float("nan"))  # type: ignore[index]
        mesh.submeshes[0].normals[1] = (float("nan"), 0.5, float("inf"))  # type: ignore[index]
        mesh.submeshes[0].uvs[1] = (float("inf"), float("nan"))  # type: ignore[index]
        mesh.submeshes[0].preview_native_material_overrides = {
            "texture_brightness": "1.2",
            "roughness": float("inf"),
            "metalness": 0.2,
            "specular": True,
            "emissive_color": "bad",
            "tint_color": [0.2, 0.3, 0.4],
        }

        prepared = mesh_to_native_preview(mesh)
        triangle_groups = mesh_edit_triangle_groups(mesh, source_submesh_indices=(True, 0.5, 0, float("inf")))  # type: ignore[arg-type]
        material_groups = mesh_edit_material_override_groups(mesh, (0,))
        reset_material_groups = mesh_edit_material_override_groups(mesh, (0,), include_defaults=True)
        vertex_groups = mesh_edit_vertex_update_groups(
            mesh,
            {0: (True, 1.0, 1.9, float("inf"), "bad"), float("inf"): (0,)},  # type: ignore[dict-item]
        )

        vertex_record = struct.Struct("<23f").unpack_from(prepared.batches[0].vertex_blob, 23 * 4)
        self.assertEqual(0, prepared.vertex_count)
        self.assertEqual((0.0, 5.0, 0.0), vertex_record[:3])
        self.assertEqual((0.0, 0.5, 0.0), vertex_record[3:6])
        self.assertEqual((0.0, 0.0), vertex_record[9:11])
        self.assertEqual([0.0, 5.0, 0.0], triangle_groups[0]["positions"][3:6])
        self.assertEqual([0.0, 0.5, 0.0], triangle_groups[0]["normals"][3:6])
        self.assertEqual([0.0, 0.0], triangle_groups[0]["uvs"][2:4])
        self.assertEqual([1], vertex_groups[0]["source_vertex_indices"])
        self.assertEqual([0.0, 5.0, 0.0], vertex_groups[0]["positions"])
        self.assertEqual([0.0, 0.5, 0.0], vertex_groups[0]["normals"])
        self.assertEqual([0.0, 0.0], vertex_groups[0]["uvs"])
        self.assertEqual(1.2, material_groups[0]["texture_brightness"])
        self.assertEqual(0.2, material_groups[0]["metalness"])
        self.assertEqual([0.2, 0.3, 0.4], material_groups[0]["tint_color"])
        self.assertNotIn("roughness", material_groups[0])
        self.assertNotIn("specular", material_groups[0])
        self.assertNotIn("emissive_color", material_groups[0])
        self.assertEqual(0.0, reset_material_groups[0]["roughness"])
        self.assertEqual(0.0, reset_material_groups[0]["specular"])
        self.assertEqual([0.35, 0.68, 1.0], reset_material_groups[0]["emissive_color"])
        self.assertEqual([], mesh_edit_triangle_groups(mesh, source_submesh_indices=float("inf")))  # type: ignore[arg-type]
        self.assertEqual([], mesh_edit_vertex_update_groups(mesh, {0: float("inf")}))  # type: ignore[dict-item]


if __name__ == "__main__":
    unittest.main()
