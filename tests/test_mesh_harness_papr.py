from __future__ import annotations

from tests.mesh_harness_support import (
    unittest,
    ArchiveEntry,
    Path,
    _papr_constraint_metadata_summary,
    _real_archive_papr_read_status,
    patch,
    struct,
    tempfile,
)


def _assert_first_constraint_candidate(
    test: unittest.TestCase,
    summary: dict[str, object],
) -> None:
    first_candidate = summary["constraint_record_candidate_rows"][0]
    test.assertGreater(first_candidate["record_span_size"], 0)
    test.assertGreaterEqual(first_candidate["record_span_field_count"], 2)
    test.assertEqual(
        "nearby_string_span_only_value_layout_unproven",
        first_candidate["record_layout_status"],
    )
    test.assertEqual(("parent", "helper", "target", "expression"), first_candidate["record_field_sequence"])
    test.assertEqual("proven_decoded_string_offset_order", first_candidate["record_field_sequence_confidence"])
    test.assertEqual("linear_channel_transform_candidate", first_candidate["expression_shape"])
    test.assertIn("shape=linear_channel_transform_candidate", first_candidate["expression_syntax_signature"])
    test.assertEqual("inferred_readable_expression_syntax", first_candidate["expression_shape_confidence"])
    test.assertEqual("solver_semantics_unknown", first_candidate["expression_shape_status"])
    test.assertEqual(("channel_coefficient", "additive_offset"), first_candidate["expression_numeric_roles"])
    test.assertEqual("inferred_readable_expression_syntax", first_candidate["expression_numeric_role_confidence"])
    test.assertEqual("binary_like_interfield_gap_bytes_unbound", first_candidate["record_gap_status"])
    test.assertGreaterEqual(sum(first_candidate["record_gap_class_counts"].values()), 1)
    test.assertGreater(first_candidate["record_gap_max_size"], 0)
    test.assertEqual("unbound_interfield_scalar_candidates", first_candidate["record_gap_scalar_status"])
    test.assertGreaterEqual(first_candidate["record_gap_scalar_kind_counts"]["f32_unit_candidate"], 1)
    test.assertGreaterEqual(first_candidate["record_gap_scalar_candidate_count"], 1)
    test.assertEqual("unbound_scalar_numeric_constant_matches", first_candidate["record_gap_numeric_match_status"])
    test.assertGreaterEqual(first_candidate["record_gap_numeric_match_role_counts"]["channel_coefficient"], 1)
    test.assertGreaterEqual(first_candidate["record_gap_numeric_match_role_counts"]["additive_offset"], 1)
    test.assertGreaterEqual(first_candidate["record_gap_numeric_match_pair_counts"]["target>expression"], 1)
    test.assertGreaterEqual(
        first_candidate["record_gap_numeric_match_value_confidence_counts"][
            "exact_float32_numeric_value_match_layout_unproven"
        ],
        1,
    )
    test.assertGreaterEqual(sum(first_candidate["record_gap_numeric_match_signature_counts"].values()), 1)
    test.assertGreaterEqual(
        sum(first_candidate["record_gap_numeric_match_candidate_relative_signature_counts"].values()),
        1,
    )
    test.assertGreaterEqual(sum(first_candidate["record_gap_numeric_match_previous_delta_counts"].values()), 1)
    test.assertGreaterEqual(sum(first_candidate["record_gap_numeric_match_next_delta_counts"].values()), 1)
    test.assertGreaterEqual(
        sum(first_candidate["record_gap_numeric_match_candidate_relative_offset_counts"].values()),
        1,
    )
    test.assertGreaterEqual(first_candidate["record_gap_numeric_match_count"], 1)
    test.assertEqual("blocked_record_layout_unproven", first_candidate["solver_status"])
    test.assertFalse(summary["constraint_solving_supported"])


class MeshHarnessPaprTests(unittest.TestCase):
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
            _assert_first_constraint_candidate(self, summary)

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

            with patch("tools.mesh_harness.papr.read_archive_entry_data", return_value=(data, False, "plain")):
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
