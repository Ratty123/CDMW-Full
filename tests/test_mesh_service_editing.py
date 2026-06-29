from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.domain.mesh import (
    MeshAnimationClip,
    MeshAnimationKeyframe,
    MeshAnimationSequenceSegment,
    MeshAnimationTrack,
    MeshEditCommand,
    MeshEditSelection,
    mesh_animation_clip_from_document,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services.mesh_service import MeshService


def _quad_mesh(*, two_parts: bool = False) -> ParsedMesh:
    submesh = SubMesh(
        name="quad",
        material="mat_a",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[(0, 1, 2), (1, 3, 2)],
        vertex_count=4,
        face_count=2,
    )
    submeshes = [submesh]
    if two_parts:
        second = SubMesh(
            name="quad_b",
            material="mat_b",
            texture="b.dds",
            vertices=list(submesh.vertices),
            uvs=list(submesh.uvs),
            normals=list(submesh.normals),
            faces=list(submesh.faces),
            vertex_count=4,
            face_count=2,
        )
        submeshes.append(second)
    return ParsedMesh(path="quad.pac", format="pac", submeshes=submeshes, total_vertices=4 * len(submeshes), total_faces=2 * len(submeshes), has_uvs=True)


def _bent_two_face_mesh() -> ParsedMesh:
    return ParsedMesh(
        path="bent.pac",
        format="pac",
        submeshes=[
            SubMesh(
                name="bent",
                material="mat_a",
                texture="a.dds",
                vertices=[
                    (0.0, 0.0, 0.0),
                    (1.0, 0.0, 0.0),
                    (0.0, 1.0, 0.0),
                    (0.0, 0.0, 1.0),
                ],
                uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 4,
                faces=[(0, 1, 2), (0, 1, 3)],
                vertex_count=4,
                face_count=2,
            )
        ],
        total_vertices=4,
        total_faces=2,
        has_uvs=True,
    )


def _malformed_face_mesh() -> ParsedMesh:
    mesh = _quad_mesh()
    submesh = mesh.submeshes[0]
    submesh.faces = [
        (0, "bad", 3),
        (0, 1, 2),
        (0, float("inf"), 2),
        (0, True, 2),
        (0, 1.9, 2),
    ]  # type: ignore[list-item]
    submesh.face_count = len(submesh.faces)
    mesh.total_faces = len(submesh.faces)
    return mesh


def _loose_edge_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="loose_edges",
        material="mat_a",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[],
        vertex_count=4,
        face_count=0,
    )
    return ParsedMesh(path="loose_edges.pac", format="pac", submeshes=[submesh], total_vertices=4, total_faces=0, has_uvs=True)


def _triangle_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="triangle",
        material="mat_a",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 1, 2)],
        vertex_count=3,
        face_count=1,
    )
    return ParsedMesh(path="triangle.pac", format="pac", submeshes=[submesh], total_vertices=3, total_faces=1, has_uvs=True)


def _duplicate_vertex_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="duplicate_vertex",
        material="mat_a",
        texture="a.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 5,
        faces=[(0, 1, 2), (1, 3, 2), (0, 4, 2)],
        vertex_count=5,
        face_count=3,
    )
    return ParsedMesh(path="duplicate_vertex.pac", format="pac", submeshes=[submesh], total_vertices=5, total_faces=3, has_uvs=True)


def _two_uv_island_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="uv_islands",
        material="mat",
        texture="uv.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (3.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (3.0, 1.0, 0.0),
        ],
        uvs=[
            (0.0, 0.0),
            (0.5, 0.0),
            (0.0, 0.5),
            (2.0, 0.0),
            (2.5, 0.0),
            (2.0, 0.5),
        ],
        normals=[(0.0, 0.0, 1.0)] * 6,
        faces=[(0, 1, 2), (3, 4, 5)],
        vertex_count=6,
        face_count=2,
    )
    return ParsedMesh(path="uv_islands.pac", format="pac", submeshes=[submesh], total_vertices=6, total_faces=2, has_uvs=True)


def _overlapping_uv_island_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="overlapping_uv_islands",
        material="mat",
        texture="uv.dds",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (3.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (3.0, 1.0, 0.0),
        ],
        uvs=[
            (0.0, 0.0),
            (1.0, 0.0),
            (0.0, 1.0),
            (0.0, 0.0),
            (1.0, 0.0),
            (0.0, 1.0),
        ],
        normals=[(0.0, 0.0, 1.0)] * 6,
        faces=[(0, 1, 2), (3, 4, 5)],
        vertex_count=6,
        face_count=2,
    )
    return ParsedMesh(path="overlapping_uv_islands.pac", format="pac", submeshes=[submesh], total_vertices=6, total_faces=2, has_uvs=True)


class MeshServiceEditingTests(unittest.TestCase):
    def test_load_mesh_file_parses_supported_file_without_opening_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mesh_path = Path(temp_dir) / "part.pam"
            mesh_path.write_bytes(b"mesh-bytes")
            parsed = _quad_mesh()
            parsed.path = ""
            parsed.format = "pam"
            service = MeshService()

            with patch("cdmw.services.mesh_service.parse_mesh", return_value=parsed) as parser:
                mesh = service.load_mesh_file(mesh_path)

            parser.assert_called_once_with(b"mesh-bytes", str(mesh_path))
            self.assertIs(parsed, mesh)
            self.assertEqual(str(mesh_path), mesh.path)
            self.assertEqual(4, mesh.total_vertices)
            self.assertEqual(2, mesh.total_faces)
            self.assertEqual({}, service._sessions)

    def test_load_mesh_file_rejects_unsupported_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mesh_path = Path(temp_dir) / "part.txt"
            mesh_path.write_text("nope", encoding="utf-8")
            service = MeshService()

            with patch("cdmw.services.mesh_service.parse_mesh") as parser:
                with self.assertRaises(ValueError):
                    service.load_mesh_file(mesh_path)

            parser.assert_not_called()

    def test_whole_part_delete_removes_submesh_rows_and_undo_restores_them(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="delete-part", mode="edit")

        deleted = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "delete",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={"delete_parts": True},
                mode="edit",
            ),
        )
        after_delete = service.working_mesh(view.session_id)
        selection_after_delete = service.session_view(view.session_id).selection.source_indices
        undo = service.undo(view.session_id)
        after_undo = service.working_mesh(view.session_id)

        self.assertTrue(deleted.ok)
        self.assertTrue(deleted.topology_changed)
        self.assertEqual((0,), deleted.affected_submesh_indices)
        self.assertEqual(["quad_b"], [part.name for part in after_delete.submeshes])
        self.assertEqual((), selection_after_delete)
        self.assertTrue(undo.ok)
        self.assertEqual(["quad", "quad_b"], [part.name for part in after_undo.submeshes])

    def test_export_validator_reports_format_geometry_material_and_skinning_blockers(self) -> None:
        mesh = _malformed_face_mesh()
        submesh = mesh.submeshes[0]
        submesh.faces.append((0, 1, 99))
        submesh.uvs = submesh.uvs[:2]
        submesh.normals = []
        submesh.texture = "missing.dds"
        submesh.bone_indices = [(0, 1, 2, 3, 4)] * len(submesh.vertices)
        submesh.bone_weights = [(0.2, 0.2, 0.2, 0.2, 0.2)] * len(submesh.vertices)
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-invalid", mode="edit")

        report = service.validate_export(view.session_id, available_textures=())
        blocker_codes = {issue.code for issue in report.blockers}

        self.assertFalse(report.ok)
        self.assertIn("invalid_face", blocker_codes)
        self.assertIn("invalid_face_index", blocker_codes)
        self.assertIn("uv_count_mismatch", blocker_codes)
        self.assertIn("missing_normals", blocker_codes)
        self.assertIn("missing_referenced_texture", blocker_codes)
        self.assertIn("too_many_bone_influences", blocker_codes)
        self.assertIn("missing_skeleton_metadata", blocker_codes)
        self.assertIn("missing_tangents", {issue.code for issue in report.warnings})

    def test_export_validator_blocks_pam_topology_changes_against_original_session_mesh(self) -> None:
        mesh = _quad_mesh()
        mesh.format = "pam"
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="export-pam-topology", mode="edit")

        duplicate = service.apply_command(
            view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )
        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertTrue(duplicate.topology_changed)
        self.assertIn("unsupported_pam_topology_change", {issue.code for issue in report.blockers})
        self.assertIn("material_slot_count_mismatch", {issue.code for issue in report.warnings})

    def test_workspace_summary_reports_parts_material_routes_and_selection(self) -> None:
        mesh = _quad_mesh(two_parts=True)
        first = mesh.submeshes[0]
        setattr(first, "cdmw_target_material_slot_index", 3)
        setattr(first, "cdmw_material_slot_kind", "base")
        setattr(first, "cdmw_source_texture_set_key", "body_set")
        first.bone_indices = [(0,), (0,), (0,), (0,)]
        first.bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="workspace-summary", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)}, faces_by_submesh={0: (0,)}, source_indices=(0,)),
            ),
        )

        summary = service.workspace_summary(view.session_id)

        self.assertEqual(2, summary.part_count)
        self.assertEqual(1, summary.selected_part_count)
        self.assertEqual("quad", summary.parts[0].name)
        self.assertEqual("mat_a", summary.parts[0].material)
        self.assertEqual("a.dds", summary.parts[0].texture)
        self.assertEqual("complete", summary.parts[0].uv_coverage)
        self.assertEqual("missing", summary.parts[0].tangent_coverage)
        self.assertEqual(3, summary.parts[0].material_slot_index)
        self.assertEqual("base", summary.parts[0].material_slot_kind)
        self.assertEqual("body_set", summary.parts[0].source_texture_set_key)
        self.assertTrue(summary.parts[0].has_skinning)
        self.assertEqual(2, summary.parts[0].selected_vertex_count)
        self.assertEqual(1, summary.parts[0].selected_face_count)

    def test_skeleton_summary_reports_skinning_rows_and_linked_metadata(self) -> None:
        mesh = _quad_mesh(two_parts=True)
        first = mesh.submeshes[0]
        first.bone_indices = [(0,), (1,), (1, 2), (4,)]
        first.bone_weights = [(1.0,), (1.0,), (0.6, 0.4), (0.8,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="skeleton-summary", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        summary = service.skeleton_summary(view.session_id)
        skeleton = Skeleton(
            bones=[
                Bone(index=0, name="Root", parent_index=-1),
                Bone(index=1, name="Bip01 Head", parent_index=0),
                Bone(index=2, name="Bip01 Head_Dummy", parent_index=1),
                Bone(index=3, name="Bip01 Chest", parent_index=0),
            ],
            bone_count=4,
        )
        linked = service.attach_skeleton(
            view.session_id,
            skeleton,
            source_path="body.pab",
            skeleton_descriptor_source="body.prefabdata_xml",
            skeleton_variation_source="body.pabc",
            animation_constraint_source="body.papr",
            animation_constraint_evidence={
                "status": "read_only_constraint_string_evidence",
                "string_evidence_count": 7,
                "record_candidate_count": 2,
                "record_candidates": (
                    {
                        "offset": 48,
                        "constraint_type": "driver_expression_candidate",
                        "target_bone": "Bip01 Head:1:2",
                        "helper_bone": "Bip01 Head_Dummy",
                        "parent_bone": "P_Bip01 Chest",
                        "expression": "Local_Euler_Z*3+30.5",
                        "expression_offset": 48,
                        "target_bone_offset": 12,
                        "target_bone_delta": 36,
                        "helper_bone_offset": 20,
                        "helper_bone_delta": 28,
                        "parent_bone_offset": 28,
                        "parent_bone_delta": 20,
                        "field_confidence": "proven_readable_strings",
                        "field_offset_confidence": "proven_decoded_string_offsets",
                        "record_span_start": 12,
                        "record_span_end": 69,
                        "record_span_size": 57,
                        "record_span_field_count": 4,
                        "record_field_sequence": ("target", "helper", "parent", "expression"),
                        "record_field_sequence_confidence": "proven_decoded_string_offset_order",
                        "record_gap_status": "binary_like_interfield_gap_bytes_unbound",
                        "record_gap_classes": ("binary_gap", "binary_gap", "binary_gap"),
                        "record_gap_class_counts": {"binary_gap": 3},
                        "record_gap_count": 3,
                        "record_gap_total_size": 18,
                        "record_gap_max_size": 6,
                        "record_gap_confidence": "observed_between_decoded_string_offsets",
                        "record_gap_scalar_status": "unbound_interfield_scalar_candidates",
                        "record_gap_scalar_kind_counts": {"f32_unit_candidate": 2, "u32_u8_candidate": 1},
                        "record_gap_aligned_word_count": 6,
                        "record_gap_scalar_candidate_count": 3,
                        "record_gap_scalar_confidence": "unbound_aligned_interfield_gap_scan",
                        "record_gap_numeric_match_status": "unbound_scalar_numeric_constant_matches",
                        "record_gap_numeric_match_role_counts": {"channel_coefficient": 1, "additive_offset": 1},
                        "record_gap_numeric_match_scalar_kind_counts": {"f32_small_candidate": 1, "f32_angle_candidate": 1},
                        "record_gap_numeric_match_storage_counts": {"f32": 2},
                        "record_gap_numeric_match_pair_counts": {"target>expression": 2},
                        "record_gap_numeric_match_value_confidence_counts": {
                            "approx_float32_numeric_value_match_layout_unproven": 1,
                            "exact_float32_numeric_value_match_layout_unproven": 1,
                        },
                        "record_gap_numeric_match_signature_counts": {
                            (
                                "role=channel_coefficient|pair=target>expression|storage=f32|"
                                "scalar=f32_small_candidate|"
                                "value=approx_float32_numeric_value_match_layout_unproven|"
                                "prev=0|next=8"
                            ): 1,
                            (
                                "role=additive_offset|pair=target>expression|storage=f32|"
                                "scalar=f32_angle_candidate|"
                                "value=exact_float32_numeric_value_match_layout_unproven|"
                                "prev=4|next=12"
                            ): 1,
                        },
                        "record_gap_numeric_match_candidate_relative_signature_counts": {
                            (
                                "role=channel_coefficient|pair=target>expression|storage=f32|"
                                "scalar=f32_small_candidate|"
                                "value=approx_float32_numeric_value_match_layout_unproven|"
                                "prev=0|next=8|rel=-16"
                            ): 1,
                            (
                                "role=additive_offset|pair=target>expression|storage=f32|"
                                "scalar=f32_angle_candidate|"
                                "value=exact_float32_numeric_value_match_layout_unproven|"
                                "prev=4|next=12|rel=-12"
                            ): 1,
                        },
                        "record_gap_numeric_match_previous_delta_counts": {"0": 1, "4": 1},
                        "record_gap_numeric_match_next_delta_counts": {"8": 1, "12": 1},
                        "record_gap_numeric_match_candidate_relative_offset_counts": {"-16": 1, "-12": 1},
                        "record_gap_numeric_match_count": 2,
                        "record_gap_numeric_match_min_previous_delta": 0,
                        "record_gap_numeric_match_max_previous_delta": 4,
                        "record_gap_numeric_match_min_next_delta": 8,
                        "record_gap_numeric_match_max_next_delta": 12,
                        "record_gap_numeric_match_min_candidate_relative_offset": -16,
                        "record_gap_numeric_match_max_candidate_relative_offset": -12,
                        "record_gap_numeric_match_offset_confidence": "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
                        "record_gap_numeric_match_candidate_relative_offset_confidence": "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
                        "record_gap_numeric_match_confidence": "exact_numeric_text_vs_interfield_scalar_match_value_layout_unproven",
                        "record_layout_status": "nearby_string_span_only_value_layout_unproven",
                        "expression_channels": ("Local_Euler_Z",),
                        "expression_channel_confidence": "proven",
                        "limit_operators": (),
                        "limit_operator_confidence": "unknown",
                        "expression_numeric_values": ("3", "30.5"),
                        "expression_numeric_value_confidence": "proven",
                        "expression_numeric_roles": ("channel_coefficient", "additive_offset"),
                        "expression_numeric_role_confidence": "inferred_readable_expression_syntax",
                        "expression_shape": "linear_channel_transform_candidate",
                        "expression_syntax_signature": (
                            "shape=linear_channel_transform_candidate|channels=Local_Euler_Z|"
                            "limits=none|numeric_roles=channel_coefficient>additive_offset"
                        ),
                        "expression_shape_confidence": "inferred_readable_expression_syntax",
                        "expression_shape_status": "solver_semantics_unknown",
                        "expression_semantics_confidence": "unknown",
                        "record_confidence": "inferred_nearby_string_order",
                        "solver_status": "blocked_record_layout_unproven",
                    },
                ),
                "constraint_expression_evidence": {
                    "status": "readable_expression_tokens_solver_semantics_unknown",
                    "token_confidence": "proven",
                    "semantics_confidence": "unknown",
                    "expression_role_counts": {"driver_expression": 1},
                    "shape_counts": {"linear_channel_transform_candidate": 1},
                    "channel_counts": {"Local_Euler_Z": 1},
                    "limit_operator_counts": {},
                    "numeric_role_counts": {"channel_coefficient": 1, "additive_offset": 1},
                    "syntax_signature_counts": {
                        (
                            "role=driver_expression|shape=linear_channel_transform_candidate|"
                            "channels=Local_Euler_Z|limits=none|"
                            "numeric_roles=channel_coefficient>additive_offset"
                        ): 1,
                    },
                    "numeric_value_count": 2,
                },
                "constraint_offset_evidence": {
                    "status": "readable_string_offsets_candidate_record_map",
                    "offset_confidence": "proven",
                    "record_confidence": "inferred_nearby_string_order",
                    "target_offset_count": 1,
                    "helper_offset_count": 1,
                    "parent_offset_count": 1,
                },
                "role_counts": {"bone_reference": 3, "driver_expression": 2},
                "related_physics_rows": ({"resolved_archive_path": "body.hkx"},),
                "constraint_solving_supported": False,
                "proof_gap": "record binding unknown",
            },
            socket_source="body.pab.sockets.xml",
        )

        self.assertTrue(summary.skinned)
        self.assertFalse(summary.skeleton_linked)
        self.assertEqual(1, summary.weighted_part_count)
        self.assertEqual(4, summary.weighted_vertex_count)
        self.assertEqual(5, summary.inferred_bone_count)
        self.assertEqual(1, summary.unnormalized_vertex_count)
        self.assertEqual(0, summary.invalid_row_count)
        self.assertTrue(summary.parts[0].selected)
        self.assertEqual(2, summary.parts[0].max_influences)
        self.assertEqual((0, 1, 2, 4), summary.parts[0].unique_bone_indices)
        self.assertTrue(linked.skeleton_linked)
        self.assertEqual(1, linked.invalid_row_count)
        self.assertEqual("body.pab", linked.skeleton_source)
        self.assertEqual("body.prefabdata_xml", linked.skeleton_descriptor_source)
        self.assertEqual("body.pabc", linked.skeleton_variation_source)
        self.assertEqual("linked_read_only_hash_records", linked.skeleton_variation_status)
        self.assertEqual("body.papr", linked.animation_constraint_source)
        self.assertEqual("linked_read_only_par_metadata_solver_blocked", linked.animation_constraint_status)
        self.assertEqual("read_only_constraint_string_evidence", linked.animation_constraint_evidence.status)
        self.assertEqual(7, linked.animation_constraint_evidence.string_evidence_count)
        self.assertEqual(2, linked.animation_constraint_evidence.record_candidate_count)
        self.assertEqual(1, len(linked.animation_constraint_evidence.record_candidates))
        candidate = linked.animation_constraint_evidence.record_candidates[0]
        self.assertEqual("Bip01 Head:1:2", candidate.target_bone)
        self.assertEqual(1, candidate.target_bone_index)
        self.assertEqual("suffix_base_name", candidate.target_bone_confidence)
        self.assertEqual(2, candidate.helper_bone_index)
        self.assertEqual(3, candidate.parent_bone_index)
        self.assertEqual("prefix_base_name", candidate.parent_bone_confidence)
        self.assertEqual("blocked_record_layout_unproven", candidate.solver_status)
        self.assertEqual(48, candidate.expression_offset)
        self.assertEqual(12, candidate.target_bone_offset)
        self.assertEqual(36, candidate.target_bone_delta)
        self.assertEqual(20, candidate.helper_bone_offset)
        self.assertEqual(28, candidate.helper_bone_delta)
        self.assertEqual(28, candidate.parent_bone_offset)
        self.assertEqual(20, candidate.parent_bone_delta)
        self.assertEqual("proven_readable_strings", candidate.field_confidence)
        self.assertEqual("proven_decoded_string_offsets", candidate.field_offset_confidence)
        self.assertEqual(12, candidate.record_span_start)
        self.assertEqual(69, candidate.record_span_end)
        self.assertEqual(57, candidate.record_span_size)
        self.assertEqual(4, candidate.record_span_field_count)
        self.assertEqual(("target", "helper", "parent", "expression"), candidate.record_field_sequence)
        self.assertEqual("proven_decoded_string_offset_order", candidate.record_field_sequence_confidence)
        self.assertEqual("binary_like_interfield_gap_bytes_unbound", candidate.record_gap_status)
        self.assertEqual((("binary_gap", 3),), candidate.record_gap_class_counts)
        self.assertEqual(3, candidate.record_gap_count)
        self.assertEqual(18, candidate.record_gap_total_size)
        self.assertEqual(6, candidate.record_gap_max_size)
        self.assertEqual("observed_between_decoded_string_offsets", candidate.record_gap_confidence)
        self.assertEqual("unbound_interfield_scalar_candidates", candidate.record_gap_scalar_status)
        self.assertEqual((("f32_unit_candidate", 2), ("u32_u8_candidate", 1)), candidate.record_gap_scalar_kind_counts)
        self.assertEqual(6, candidate.record_gap_aligned_word_count)
        self.assertEqual(3, candidate.record_gap_scalar_candidate_count)
        self.assertEqual("unbound_aligned_interfield_gap_scan", candidate.record_gap_scalar_confidence)
        self.assertEqual("unbound_scalar_numeric_constant_matches", candidate.record_gap_numeric_match_status)
        self.assertEqual((("additive_offset", 1), ("channel_coefficient", 1)), candidate.record_gap_numeric_match_role_counts)
        self.assertEqual((("f32_angle_candidate", 1), ("f32_small_candidate", 1)), candidate.record_gap_numeric_match_scalar_kind_counts)
        self.assertEqual((("f32", 2),), candidate.record_gap_numeric_match_storage_counts)
        self.assertEqual((("target>expression", 2),), candidate.record_gap_numeric_match_pair_counts)
        self.assertEqual(
            (
                ("approx_float32_numeric_value_match_layout_unproven", 1),
                ("exact_float32_numeric_value_match_layout_unproven", 1),
            ),
            candidate.record_gap_numeric_match_value_confidence_counts,
        )
        self.assertEqual(2, len(candidate.record_gap_numeric_match_signature_counts))
        self.assertEqual(2, len(candidate.record_gap_numeric_match_candidate_relative_signature_counts))
        self.assertEqual((("0", 1), ("4", 1)), candidate.record_gap_numeric_match_previous_delta_counts)
        self.assertEqual((("12", 1), ("8", 1)), candidate.record_gap_numeric_match_next_delta_counts)
        self.assertEqual(2, candidate.record_gap_numeric_match_count)
        self.assertEqual(0, candidate.record_gap_numeric_match_min_previous_delta)
        self.assertEqual(4, candidate.record_gap_numeric_match_max_previous_delta)
        self.assertEqual(8, candidate.record_gap_numeric_match_min_next_delta)
        self.assertEqual(12, candidate.record_gap_numeric_match_max_next_delta)
        self.assertEqual(
            "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
            candidate.record_gap_numeric_match_offset_confidence,
        )
        self.assertEqual(
            "exact_numeric_text_vs_interfield_scalar_match_value_layout_unproven",
            candidate.record_gap_numeric_match_confidence,
        )
        self.assertEqual("nearby_string_span_only_value_layout_unproven", candidate.record_layout_status)
        self.assertEqual(("Local_Euler_Z",), candidate.expression_channels)
        self.assertEqual("proven", candidate.expression_channel_confidence)
        self.assertEqual(("3", "30.5"), candidate.expression_numeric_values)
        self.assertEqual("proven", candidate.expression_numeric_value_confidence)
        self.assertEqual(("channel_coefficient", "additive_offset"), candidate.expression_numeric_roles)
        self.assertEqual("inferred_readable_expression_syntax", candidate.expression_numeric_role_confidence)
        self.assertEqual("linear_channel_transform_candidate", candidate.expression_shape)
        self.assertEqual(
            "shape=linear_channel_transform_candidate|channels=Local_Euler_Z|"
            "limits=none|numeric_roles=channel_coefficient>additive_offset",
            candidate.expression_syntax_signature,
        )
        self.assertEqual("inferred_readable_expression_syntax", candidate.expression_shape_confidence)
        self.assertEqual("solver_semantics_unknown", candidate.expression_shape_status)
        self.assertEqual("unknown", candidate.expression_semantics_confidence)
        self.assertIn(("target_suffix_base_name", 1), linked.animation_constraint_evidence.bone_match_counts)
        self.assertIn(("helper_exact_name", 1), linked.animation_constraint_evidence.bone_match_counts)
        self.assertIn(("parent_prefix_base_name", 1), linked.animation_constraint_evidence.bone_match_counts)
        self.assertEqual(1, linked.animation_constraint_evidence.bone_match_candidate_count)
        self.assertIn(("driver_expression_candidate", 1), linked.animation_constraint_evidence.candidate_family_counts)
        self.assertIn(
            (
                "driver_expression_candidate",
                "solver_blocked_until_record_layout_and_expression_semantics_proven",
                (
                    ("candidates", 1),
                    ("solver ready", 0),
                    ("target bound", 1),
                    ("helper bound", 1),
                    ("parent bound", 1),
                    ("record layout unproven", 1),
                    ("expression semantics unknown", 1),
                ),
            ),
            linked.animation_constraint_evidence.family_readiness_rows,
        )
        self.assertEqual("readable_expression_tokens_solver_semantics_unknown", linked.animation_constraint_evidence.expression_status)
        self.assertIn(("channel Local_Euler_Z", 1), linked.animation_constraint_evidence.expression_counts)
        self.assertEqual(1, len(linked.animation_constraint_evidence.expression_syntax_signature_counts))
        self.assertEqual(2, linked.animation_constraint_evidence.expression_numeric_value_count)
        self.assertEqual("readable_string_offsets_candidate_record_map", linked.animation_constraint_evidence.field_offset_status)
        self.assertIn(("target", 1), linked.animation_constraint_evidence.field_offset_counts)
        self.assertIn(("helper", 1), linked.animation_constraint_evidence.field_offset_counts)
        self.assertIn(("parent", 1), linked.animation_constraint_evidence.field_offset_counts)
        self.assertEqual(2, linked.animation_constraint_evidence.numeric_match_count)
        self.assertIn(("unbound_scalar_numeric_constant_matches", 1), linked.animation_constraint_evidence.numeric_match_status_counts)
        self.assertIn(("channel_coefficient", 1), linked.animation_constraint_evidence.numeric_match_role_counts)
        self.assertIn(("additive_offset", 1), linked.animation_constraint_evidence.numeric_match_role_counts)
        self.assertIn(("f32", 2), linked.animation_constraint_evidence.numeric_match_storage_counts)
        self.assertIn(("target>expression", 2), linked.animation_constraint_evidence.numeric_match_pair_counts)
        self.assertIn(
            ("approx_float32_numeric_value_match_layout_unproven", 1),
            linked.animation_constraint_evidence.numeric_match_value_confidence_counts,
        )
        self.assertIn(
            ("exact_float32_numeric_value_match_layout_unproven", 1),
            linked.animation_constraint_evidence.numeric_match_value_confidence_counts,
        )
        self.assertIn(("driver_expression_candidate", 2), linked.animation_constraint_evidence.numeric_match_family_counts)
        self.assertIn(("driver_expression_candidate", 1), linked.animation_constraint_evidence.numeric_match_family_row_counts)
        self.assertIn(
            (
                "driver_expression_candidate",
                (("additive_offset", 1), ("channel_coefficient", 1)),
            ),
            linked.animation_constraint_evidence.numeric_match_family_role_counts,
        )
        self.assertIn(
            (
                "driver_expression_candidate",
                (("target>expression", 2),),
            ),
            linked.animation_constraint_evidence.numeric_match_family_pair_counts,
        )
        self.assertIn(
            (
                "driver_expression_candidate",
                (
                    ("approx_float32_numeric_value_match_layout_unproven", 1),
                    ("exact_float32_numeric_value_match_layout_unproven", 1),
                ),
            ),
            linked.animation_constraint_evidence.numeric_match_family_value_confidence_counts,
        )
        self.assertEqual(2, len(linked.animation_constraint_evidence.numeric_match_signature_counts))
        self.assertEqual(2, len(linked.animation_constraint_evidence.numeric_match_candidate_relative_signature_counts))
        self.assertIn(("0", 1), linked.animation_constraint_evidence.numeric_match_previous_delta_counts)
        self.assertIn(("4", 1), linked.animation_constraint_evidence.numeric_match_previous_delta_counts)
        self.assertIn(("8", 1), linked.animation_constraint_evidence.numeric_match_next_delta_counts)
        self.assertIn(("12", 1), linked.animation_constraint_evidence.numeric_match_next_delta_counts)
        self.assertIn(("-16", 1), candidate.record_gap_numeric_match_candidate_relative_offset_counts)
        self.assertIn(("-12", 1), candidate.record_gap_numeric_match_candidate_relative_offset_counts)
        self.assertIn(("-16", 1), linked.animation_constraint_evidence.numeric_match_candidate_relative_offset_counts)
        self.assertIn(("-12", 1), linked.animation_constraint_evidence.numeric_match_candidate_relative_offset_counts)
        self.assertEqual(0, linked.animation_constraint_evidence.numeric_match_min_previous_delta)
        self.assertEqual(4, linked.animation_constraint_evidence.numeric_match_max_previous_delta)
        self.assertEqual(8, linked.animation_constraint_evidence.numeric_match_min_next_delta)
        self.assertEqual(12, linked.animation_constraint_evidence.numeric_match_max_next_delta)
        self.assertEqual(-16, candidate.record_gap_numeric_match_min_candidate_relative_offset)
        self.assertEqual(-12, candidate.record_gap_numeric_match_max_candidate_relative_offset)
        self.assertEqual(-16, linked.animation_constraint_evidence.numeric_match_min_candidate_relative_offset)
        self.assertEqual(-12, linked.animation_constraint_evidence.numeric_match_max_candidate_relative_offset)
        self.assertEqual(
            "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
            linked.animation_constraint_evidence.numeric_match_offset_confidence,
        )
        self.assertEqual(
            "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
            candidate.record_gap_numeric_match_candidate_relative_offset_confidence,
        )
        self.assertEqual(
            "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
            linked.animation_constraint_evidence.numeric_match_candidate_relative_offset_confidence,
        )
        self.assertEqual(
            "solver_blocked_until_record_layout_and_expression_semantics_proven",
            linked.animation_constraint_evidence.solver_readiness_status,
        )
        self.assertIn(("solver ready", 0), linked.animation_constraint_evidence.solver_readiness_counts)
        self.assertIn(("target bound", 1), linked.animation_constraint_evidence.solver_readiness_counts)
        self.assertIn(("record layout unproven", 1), linked.animation_constraint_evidence.solver_readiness_counts)
        self.assertIn(("expression semantics unknown", 1), linked.animation_constraint_evidence.solver_readiness_counts)
        self.assertEqual(1, linked.animation_constraint_evidence.related_physics_count)
        self.assertIn(("bone_reference", 3), linked.animation_constraint_evidence.role_counts)
        self.assertFalse(linked.animation_constraint_evidence.solver_supported)
        self.assertEqual("body.pab.sockets.xml", linked.socket_source)
        self.assertEqual("constraint_metadata_only", linked.animation_status)
        self.assertFalse(linked.animation_playback_ready)
        self.assertTrue(any("bone-track binding" in blocker for blocker in linked.animation_blockers))
        authoring = {row.feature: row for row in linked.authoring_status_rows}
        self.assertEqual("preview-only", authoring["Pose preview"].state)
        self.assertEqual("blocked", authoring["Weight edits"].state)
        self.assertEqual("blocked", authoring["PAPR constraints"].state)
        self.assertEqual("blocked", authoring["Archive mutation"].state)

    def test_attach_skeleton_reports_hierarchy_and_satisfies_export_metadata(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.6, 0.4), (1.0,)]
        mesh.has_bones = True
        skeleton = Skeleton(
            path="character/model/body.pab",
            bones=[
                Bone(index=0, name="Root", parent_index=-1, position=(0.0, 0.0, 0.0)),
                Bone(index=1, name="Spine", parent_index=0, position=(0.0, 1.0, 0.0)),
            ],
            bone_count=2,
            parser_mode="fixed",
        )
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="attached-skeleton", mode="edit")

        summary = service.attach_skeleton(view.session_id, skeleton)
        report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertTrue(summary.skeleton_linked)
        self.assertEqual(2, summary.skeleton_bone_count)
        self.assertEqual(1, summary.root_bone_count)
        self.assertEqual(1, summary.max_depth)
        self.assertEqual("Root", summary.bones[1].parent_name)
        self.assertEqual("fixed", summary.skeleton_parser_mode)
        self.assertNotIn("missing_skeleton_metadata", {issue.code for issue in report.blockers})

        selected = service.select_bone(view.session_id, 1)
        enabled = service.set_pose_preview(view.session_id, True)
        rotated = service.rotate_selected_bone(view.session_id, (10.0, -5.0, "2.5"))
        reset = service.reset_pose(view.session_id)

        self.assertEqual(1, selected.pose.selected_bone_index)
        self.assertEqual("Spine", selected.pose.selected_bone_name)
        self.assertTrue(enabled.pose.enabled)
        self.assertEqual((10.0, -5.0, 2.5), rotated.pose.rotation_degrees)
        self.assertEqual(1, rotated.pose.posed_bone_count)
        self.assertEqual((0.0, 0.0, 0.0), reset.pose.rotation_degrees)
        self.assertEqual(0, reset.pose.posed_bone_count)

        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (2,)})),
        )
        service.select_bone(view.session_id, 1)
        working = service.working_mesh(view.session_id)
        working.submeshes[0].bone_indices[2] = ()
        working.submeshes[0].bone_weights[2] = ()
        transferred = service.transfer_selected_vertex_weights_from_source(view.session_id)
        self.assertEqual((0, 1), working.submeshes[0].bone_indices[2])
        self.assertEqual((0.6, 0.4), working.submeshes[0].bone_weights[2])
        self.assertAlmostEqual(0.4, transferred.selected_vertex_weights[0].selected_bone_weight)

        weighted = service.adjust_selected_vertex_bone_weight(view.session_id, 0.2)

        self.assertEqual(1, len(weighted.selected_vertex_weights))
        self.assertAlmostEqual(0.6, weighted.selected_vertex_weights[0].selected_bone_weight)
        self.assertEqual((0, 1), service.working_mesh(view.session_id).submeshes[0].bone_indices[2])
        self.assertAlmostEqual(0.4, service.working_mesh(view.session_id).submeshes[0].bone_weights[2][0])
        self.assertAlmostEqual(0.6, service.working_mesh(view.session_id).submeshes[0].bone_weights[2][1])
        self.assertEqual(2, service.session_view(view.session_id).undo_count)

    def test_pose_preview_mesh_applies_skinned_bone_rotation_without_mutating_working_mesh(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="pose-preview", mode="edit")
        skeleton = Skeleton(bones=[Bone(index=0, name="Root", parent_index=-1)], bone_count=1)
        service.attach_skeleton(view.session_id, skeleton)
        service.select_bone(view.session_id, 0)
        service.rotate_selected_bone(view.session_id, (0.0, 0.0, 90.0))

        preview = service.pose_preview_mesh(view.session_id)

        self.assertAlmostEqual(0.0, preview.submeshes[0].vertices[1][0], places=6)
        self.assertAlmostEqual(1.0, preview.submeshes[0].vertices[1][1], places=6)
        self.assertEqual((1.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[1])

    def test_animation_clip_document_bridge_accepts_explicit_bone_tracks(self) -> None:
        document = {
            "source": {"path": "object/animation/animation/test_idle_00.paa.json"},
            "summary": {"duration_seconds": 1.0, "frame_rate": 60.0, "frame_rate_confidence": "proven"},
            "animation": {
                "parser_mode": "unit_explicit_tracks",
                "bone_tracks": [
                    {
                        "bone_name": "Root",
                        "rotation_keyframes": [
                            {"time_seconds": 0.0, "rotation_degrees": (0.0, 0.0, 0.0)},
                            {"time_seconds": 1.0, "rotation_degrees": (0.0, 0.0, 90.0)},
                        ],
                    }
                ],
            },
        }

        clip = mesh_animation_clip_from_document(document)

        self.assertIsNotNone(clip)
        assert clip is not None
        self.assertEqual("object/animation/animation/test_idle_00.paa.json", clip.source)
        self.assertEqual("unit_explicit_tracks", clip.parser_mode)
        self.assertEqual(60.0, clip.frame_rate)
        self.assertEqual("proven", clip.timing_confidence)
        self.assertEqual("document_frame_rate_proven", clip.timing_status)
        self.assertTrue(clip.game_accurate_timing)
        self.assertEqual(1, len(clip.tracks))
        self.assertEqual("Root", clip.tracks[0].bone_name)
        self.assertAlmostEqual(1.0, clip.duration_seconds)
        self.assertAlmostEqual(90.0, clip.tracks[0].rotation_keyframes[-1].rotation_degrees[2])

    def test_animation_clip_document_bridge_rejects_archive_only_keyframe_tables(self) -> None:
        document = {
            "source": {"path": "object/animation/animation/test_idle_00.paa"},
            "animation": {
                "keyframe_table_candidates": [
                    {
                        "offset": 64,
                        "row_format": "u16 frame + 4 half-float values",
                        "preview_rows": [
                            {"frame": 1, "values": [0.1, 0.0, 0.0, 0.99]},
                        ],
                    }
                ]
            },
        }

        self.assertIsNone(mesh_animation_clip_from_document(document))

    def test_animation_playback_samples_parsed_clip_into_preview_deformation(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="animation-preview", mode="edit")
        skeleton = Skeleton(bones=[Bone(index=0, name="Root", parent_index=-1)], bone_count=1)
        service.attach_skeleton(view.session_id, skeleton)
        clip = MeshAnimationClip(
            source="safe_clip.paa.json",
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
                    sequence_path="sequencer/binary__/unit_combo.paseqc",
                    clip_path="safe_clip.paa.json",
                    lane_index=7,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    status="paseqc_lane_bound_to_paa_clip_preview_only_sequence_semantics_unknown",
                    field_confidence=(("clip_path", "proven"), ("blend_weight", "unknown")),
                ),
            ),
            parser_mode="unit_safe_parser",
            frame_rate=60.0,
            timing_confidence="proven",
            timing_status="unit_sequence_fps_proven",
        )

        attached = service.attach_animation_clip(view.session_id, clip)
        playing = service.set_animation_playback(view.session_id, True)
        sampled = service.seek_animation(view.session_id, 0.5)
        preview = service.pose_preview_mesh(view.session_id)

        self.assertTrue(attached.animation_playback_ready)
        self.assertTrue(playing.animation_playback.enabled)
        self.assertEqual("playback_ready", sampled.animation_status)
        self.assertEqual("safe_clip.paa.json", sampled.animation_playback.source)
        self.assertEqual(60.0, sampled.animation_playback.frame_rate)
        self.assertEqual("proven", sampled.animation_playback.timing_confidence)
        self.assertEqual("unit_sequence_fps_proven", sampled.animation_playback.timing_status)
        self.assertTrue(sampled.animation_playback.game_accurate_timing)
        self.assertEqual(1, sampled.animation_playback.sequence_segment_count)
        self.assertEqual(7, sampled.animation_playback.active_sequence_lane_index)
        self.assertEqual("sequencer/binary__/unit_combo.paseqc", sampled.animation_playback.active_sequence_path)
        self.assertEqual("safe_clip.paa.json", sampled.animation_playback.active_sequence_clip_path)
        self.assertEqual(
            "paseqc_lane_bound_to_paa_clip_preview_only_sequence_semantics_unknown",
            sampled.animation_playback.active_sequence_status,
        )
        self.assertEqual("proven", dict(sampled.animation_playback.active_sequence_field_confidence)["clip_path"])
        loop_off = service.set_animation_loop(view.session_id, False)
        speeded = service.set_animation_speed(view.session_id, 2.0)
        advanced = service.step_animation(view.session_id, 0.25)
        scrubbed = service.scrub_animation_fraction(view.session_id, 0.25)
        paused = service.set_animation_playback(view.session_id, False)
        authoring = {row.feature: row for row in sampled.authoring_status_rows}
        self.assertEqual("preview-only", authoring["Animation playback"].state)
        self.assertEqual("proven", authoring["Animation playback"].confidence)
        self.assertIn("unit_sequence_fps_proven", authoring["Animation playback"].detail)
        self.assertAlmostEqual(0.5, sampled.animation_playback.time_seconds)
        self.assertFalse(loop_off.animation_playback.loop)
        self.assertEqual(2.0, speeded.animation_playback.playback_speed)
        self.assertAlmostEqual(1.0, advanced.animation_playback.time_seconds)
        self.assertAlmostEqual(0.25, scrubbed.animation_playback.time_seconds)
        self.assertFalse(paused.animation_playback.enabled)
        self.assertAlmostEqual(2 ** 0.5 / 2.0, preview.submeshes[0].vertices[1][0], places=6)
        self.assertAlmostEqual(2 ** 0.5 / 2.0, preview.submeshes[0].vertices[1][1], places=6)
        self.assertEqual((1.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[1])

    def test_animation_playback_blocks_clip_without_attached_skeleton(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="animation-no-skeleton", mode="edit")
        clip = MeshAnimationClip(
            source="safe_clip.paa.json",
            duration_seconds=1.0,
            tracks=(
                MeshAnimationTrack(
                    bone_index=0,
                    rotation_keyframes=(MeshAnimationKeyframe(0.0, (0.0, 0.0, 15.0)),),
                ),
            ),
        )

        summary = service.attach_animation_clip(view.session_id, clip)
        playing = service.set_animation_playback(view.session_id, True)

        self.assertFalse(summary.animation_playback_ready)
        self.assertEqual("playback_blocked", summary.animation_status)
        self.assertTrue(any("attached parsed skeleton" in blocker for blocker in summary.animation_blockers))
        self.assertFalse(playing.animation_playback.enabled)

    def test_transfer_selected_part_weights_from_source(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (1,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.25, 0.75), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="part-weight-transfer", mode="edit")
        working = service.working_mesh(view.session_id)
        working.submeshes[0].bone_indices = [(), (), (), ()]
        working.submeshes[0].bone_weights = [(), (), (), ()]
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        summary = service.transfer_selected_vertex_weights_from_source(view.session_id)

        self.assertTrue(summary.skinned)
        self.assertEqual([(0,), (1,), (0, 1), (1,)], working.submeshes[0].bone_indices)
        self.assertEqual([(1.0,), (1.0,), (0.25, 0.75), (1.0,)], working.submeshes[0].bone_weights)
        self.assertEqual(1, service.session_view(view.session_id).undo_count)

    def test_transfer_selected_weights_can_remap_bones_by_name(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (1,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.25, 0.75), (1.0,)]
        mesh.has_bones = True
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="mapped-weight-transfer", mode="edit")
        working = service.working_mesh(view.session_id)
        working.submeshes[0].bone_indices = [(), (), (), ()]
        working.submeshes[0].bone_weights = [(), (), (), ()]
        source_skeleton = Skeleton(
            bones=[
                Bone(index=0, name="Root"),
                Bone(index=1, name="Spine"),
            ],
            bone_count=2,
        )
        target_skeleton = Skeleton(
            bones=[
                Bone(index=4, name="Spine"),
                Bone(index=9, name="Root"),
            ],
            bone_count=2,
        )
        service.attach_skeleton(view.session_id, target_skeleton)
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (2,)})),
        )

        summary = service.transfer_selected_vertex_weights_from_source(view.session_id, source_skeleton=source_skeleton)

        self.assertEqual((4, 9), working.submeshes[0].bone_indices[2])
        self.assertEqual((0.75, 0.25), working.submeshes[0].bone_weights[2])
        self.assertEqual(9, summary.parts[0].max_bone_index)
        self.assertAlmostEqual(0.0, summary.selected_vertex_weights[0].selected_bone_weight)

    def test_compare_summary_reports_material_uv_bounds_and_topology_differences(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="compare-summary", mode="edit")
        edited = service.working_mesh(view.session_id, clone=False).submeshes[0]
        edited.material = "mat_changed"
        edited.texture = "changed.dds"
        edited.uvs[0] = (0.25, 0.25)
        edited.vertices[3] = (2.0, 1.0, 0.0)
        edited.faces.append((0, 1, 2))
        edited.face_count = len(edited.faces)

        summary = service.compare_summary(view.session_id)

        self.assertTrue(summary.changed)
        self.assertTrue(summary.topology_changed)
        self.assertTrue(summary.bounds_changed)
        self.assertGreater(summary.scale_ratio, 1.0)
        self.assertEqual(1, summary.material_mismatch_count)
        self.assertEqual(1, summary.texture_mismatch_count)
        self.assertEqual(1, summary.uv_mismatch_count)
        self.assertEqual(1, summary.bounds_mismatch_count)
        self.assertEqual("topology, material, texture, uv, bounds", summary.parts[0].change_text)

    def test_cleanup_tools_repair_doubles_loose_vertices_winding_holes_and_display_faces(self) -> None:
        service = MeshService()
        cleanup_mesh = _duplicate_vertex_mesh()
        cleanup_submesh = cleanup_mesh.submeshes[0]
        cleanup_submesh.vertices.append((99.0, 99.0, 99.0))
        cleanup_submesh.uvs.append((0.0, 0.0))
        cleanup_submesh.normals.append((0.0, 0.0, 1.0))
        cleanup_submesh.vertex_count = len(cleanup_submesh.vertices)
        cleanup_mesh.total_vertices = len(cleanup_submesh.vertices)
        view = service.open_edit_session(cleanup_mesh, session_id="cleanup-doubles", mode="edit")

        removed = service.apply_command(view.session_id, MeshEditCommand("remove_doubles", mode="edit", params={"threshold": 0.001}))
        cleaned = service.working_mesh(view.session_id).submeshes[0]

        self.assertTrue(removed.topology_changed)
        self.assertEqual((0,), removed.affected_submesh_indices)
        self.assertEqual(4, cleaned.vertex_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], cleaned.faces)

        winding_mesh = _triangle_mesh()
        winding_mesh.submeshes[0].faces = [(0, 2, 1)]
        winding_view = service.open_edit_session(winding_mesh, session_id="cleanup-winding", mode="edit")
        winding = service.apply_command(winding_view.session_id, MeshEditCommand("fix_winding", mode="edit"))
        self.assertTrue(winding.topology_changed)
        self.assertEqual([(0, 1, 2)], service.working_mesh(winding_view.session_id).submeshes[0].faces)

        hole_submesh = SubMesh(
            name="open_tetra",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
            uvs=[(0.0, 0.0)] * 4,
            normals=[(0.0, 0.0, 1.0)] * 4,
            faces=[(0, 1, 3), (1, 2, 3), (2, 0, 3)],
            vertex_count=4,
            face_count=3,
        )
        hole_mesh = ParsedMesh(path="hole.pac", format="pac", submeshes=[hole_submesh], total_vertices=4, total_faces=3)
        hole_view = service.open_edit_session(hole_mesh, session_id="cleanup-hole", mode="edit")
        filled = service.apply_command(hole_view.session_id, MeshEditCommand("fill_holes", mode="edit"))
        self.assertTrue(filled.topology_changed)
        self.assertEqual(4, service.working_mesh(hole_view.session_id).submeshes[0].face_count)

        display_mesh = _quad_mesh()
        display_mesh.submeshes[0].faces = [(0, 1, 3, 2)]  # type: ignore[list-item]
        display_view = service.open_edit_session(display_mesh, session_id="cleanup-triangulate", mode="edit")
        triangulated = service.apply_command(display_view.session_id, MeshEditCommand("triangulate_display", mode="edit"))
        self.assertTrue(triangulated.topology_changed)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], service.working_mesh(display_view.session_id).submeshes[0].faces)

    def test_uv_summary_reports_connected_islands_textures_and_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_two_uv_island_mesh(), session_id="uv-summary", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})),
        )

        summary = service.uv_summary(view.session_id)

        self.assertEqual(2, summary.island_count)
        self.assertEqual(1, summary.selected_island_count)
        self.assertEqual((0.0, 0.0), summary.islands[0].uv_min)
        self.assertEqual((0.5, 0.5), summary.islands[0].uv_max)
        self.assertEqual("uv.dds", summary.islands[0].texture)
        self.assertTrue(summary.islands[0].selected)
        self.assertFalse(summary.islands[1].selected)
        self.assertEqual(3, summary.islands[0].vertex_count)
        self.assertEqual(1, summary.islands[0].face_count)

    def test_uv_summary_keeps_overlapping_disconnected_islands_separate(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_overlapping_uv_island_mesh(), session_id="uv-summary-overlap", mode="edit")

        summary = service.uv_summary(view.session_id)

        self.assertEqual(2, summary.island_count)
        self.assertEqual({(0.0, 0.0)}, {island.uv_min for island in summary.islands})
        self.assertEqual({(1.0, 1.0)}, {island.uv_max for island in summary.islands})

    def test_texture_edit_target_uses_selected_textured_part(self) -> None:
        mesh = _quad_mesh(two_parts=True)
        setattr(mesh.submeshes[1], "cdmw_source_texture_set_key", "part_b_set")
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="texture-target", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(1,))),
        )

        target = service.texture_edit_target(view.session_id)

        assert target is not None
        self.assertEqual(1, target.submesh_index)
        self.assertEqual("quad_b", target.part_name)
        self.assertEqual("mat_b", target.material)
        self.assertEqual("b.dds", target.texture)
        self.assertEqual("part_b_set", target.source_texture_set_key)

    def test_texture_edit_target_does_not_fallback_when_selected_part_has_no_texture(self) -> None:
        mesh = _quad_mesh(two_parts=True)
        mesh.submeshes[0].texture = ""
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="texture-target-selected-missing", mode="edit")

        fallback = service.texture_edit_target(view.session_id)
        assert fallback is not None
        self.assertEqual(1, fallback.submesh_index)

        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        self.assertIsNone(service.texture_edit_target(view.session_id))

    def test_transform_uses_session_selection_and_undo_redo_keeps_original_mesh_clean(self) -> None:
        original = _quad_mesh()
        service = MeshService()
        view = service.open_edit_session(original, session_id="edit", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 3)})

        service.apply_command(view.session_id, MeshEditCommand("select", selection=selection))
        result = service.apply_command(view.session_id, MeshEditCommand("transform", params={"translate": (0.0, 0.0, 1.0)}))

        self.assertTrue(result.ok)
        self.assertEqual(((0, (0, 3)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0, 1.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertEqual((0.0, 0.0, 0.0), original.submeshes[0].vertices[0])

        self.assertTrue(service.undo(view.session_id).ok)
        self.assertEqual((0.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertTrue(service.redo(view.session_id).ok)
        self.assertEqual((0.0, 0.0, 1.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_select_can_add_subtract_and_toggle_existing_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="select-ops", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (0,)},
                    edges_by_submesh={0: ((0, 1),)},
                    faces_by_submesh={0: (0,)},
                    source_indices=(0,),
                ),
            ),
        )
        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (3,)},
                    edges_by_submesh={0: ((1, 2),)},
                    faces_by_submesh={0: (1,)},
                    source_indices=(1,),
                ),
                params={"operation": "add"},
            ),
        )
        added = service.session_view(view.session_id).selection
        self.assertEqual({0: {0, 3}}, added.vertex_map())
        self.assertEqual({0: {(0, 1), (1, 2)}}, added.edge_map())
        self.assertEqual({0: {0, 1}}, added.face_map())
        self.assertEqual((0, 1), added.source_indices)

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (0,)},
                    edges_by_submesh={0: ((0, 1),)},
                    faces_by_submesh={0: (0,)},
                    source_indices=(0,),
                ),
                params={"operation": "subtract"},
            ),
        )
        subtracted = service.session_view(view.session_id).selection
        self.assertEqual({0: {3}}, subtracted.vertex_map())
        self.assertEqual({0: {(1, 2)}}, subtracted.edge_map())
        self.assertEqual({0: {1}}, subtracted.face_map())
        self.assertEqual((1,), subtracted.source_indices)

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (2, 3)},
                    edges_by_submesh={0: ((1, 2), (2, 3))},
                    faces_by_submesh={0: (1,)},
                    source_indices=(1, 2),
                ),
                params={"operation": "toggle"},
            ),
        )
        toggled = service.session_view(view.session_id).selection
        self.assertEqual({0: {2}}, toggled.vertex_map())
        self.assertEqual({0: {(2, 3)}}, toggled.edge_map())
        self.assertEqual({}, toggled.face_map())
        self.assertEqual((), toggled.source_indices)

    def test_select_prunes_indices_outside_current_mesh(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="select-prune", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (0, 99), 4: (0,)},
                    edges_by_submesh={0: ((0, 1), (0, 3), (1, 99)), 4: ((0, 1),)},
                    faces_by_submesh={0: (0, 9), 4: (0,)},
                    source_indices=(0, 4),
                ),
            ),
        )

        selection = service.session_view(view.session_id).selection
        self.assertEqual({0: {0}}, selection.vertex_map())
        self.assertEqual({0: {(0, 1)}}, selection.edge_map())
        self.assertEqual({0: {0}}, selection.face_map())
        self.assertEqual((0,), selection.source_indices)

    def test_select_prunes_malformed_faces_and_non_face_edges(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_malformed_face_mesh(), session_id="select-prune-malformed", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(
                    vertices_by_submesh={0: (0, 3)},
                    edges_by_submesh={0: ((0, 1), (0, 3))},
                    faces_by_submesh={0: (0, 1, 2)},
                ),
            ),
        )

        selection = service.session_view(view.session_id).selection
        self.assertEqual({0: {0, 3}}, selection.vertex_map())
        self.assertEqual({0: {(0, 1)}}, selection.edge_map())
        self.assertEqual({0: {1}}, selection.face_map())

    def test_select_preserves_loose_edges_on_mesh_without_faces(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_loose_edge_mesh(), session_id="select-prune-loose-edge", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3), (1, 99))})),
        )

        self.assertEqual({0: {(0, 3)}}, service.session_view(view.session_id).selection.edge_map())

    def test_topology_edit_prunes_deleted_face_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="topology-selection-prune", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (1,)})),
        )
        deleted = service.apply_command(view.session_id, MeshEditCommand("delete"))

        self.assertTrue(deleted.ok)
        self.assertTrue(deleted.topology_changed)
        self.assertTrue(service.session_view(view.session_id).selection.is_empty())

    def test_undo_prunes_selection_referencing_removed_topology(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="history-selection-prune", mode="edit")

        duplicated = service.apply_command(
            view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
        )
        view_after_duplicate = service.session_view(view.session_id)
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}, source_indices=(1,))),
        )
        selected = service.session_view(view.session_id).selection

        undo = service.undo(view.session_id)
        view_after_undo = service.session_view(view.session_id)

        self.assertTrue(duplicated.ok)
        self.assertTrue(duplicated.topology_changed)
        self.assertEqual(2, view_after_duplicate.submesh_count)
        self.assertEqual((1,), selected.source_indices)
        self.assertTrue(undo.ok)
        self.assertEqual(1, view_after_undo.submesh_count)
        self.assertEqual(1, view_after_undo.redo_count)
        self.assertTrue(view_after_undo.selection.is_empty())

    def test_undo_redo_restore_selection_context_snapshots(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="history-selection-context", mode="edit")
        original_selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})

        service.apply_command(view.session_id, MeshEditCommand("select", selection=original_selection))
        duplicated = service.apply_command(view.session_id, MeshEditCommand("duplicate"))
        service.apply_command(
            view.session_id,
            MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}, source_indices=(1,))),
        )
        undo = service.undo(view.session_id)
        after_undo = service.session_view(view.session_id)
        redo = service.redo(view.session_id)
        after_redo = service.session_view(view.session_id)

        self.assertTrue(duplicated.ok)
        self.assertTrue(duplicated.topology_changed)
        self.assertTrue(undo.ok)
        self.assertEqual({0: {0}}, after_undo.selection.face_map())
        self.assertEqual((), after_undo.selection.source_indices)
        self.assertTrue(redo.ok)
        self.assertEqual({1: {0}}, after_redo.selection.face_map())
        self.assertEqual((1,), after_redo.selection.source_indices)

    def test_undo_redo_restore_mode_before_command_mode_switch(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="history-mode-context", mode="object")
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})

        service.apply_command(view.session_id, MeshEditCommand("select", selection=selection))
        duplicated = service.apply_command(view.session_id, MeshEditCommand("duplicate", mode="edit"))
        after_duplicate = service.session_view(view.session_id)
        undo = service.undo(view.session_id)
        after_undo = service.session_view(view.session_id)
        redo = service.redo(view.session_id)
        after_redo = service.session_view(view.session_id)

        self.assertTrue(duplicated.ok)
        self.assertEqual("edit", after_duplicate.mode)
        self.assertTrue(undo.ok)
        self.assertEqual("object", after_undo.mode)
        self.assertEqual({0: {0}}, after_undo.selection.face_map())
        self.assertTrue(redo.ok)
        self.assertEqual("edit", after_redo.mode)
        self.assertEqual({0: {0}}, after_redo.selection.face_map())

    def test_no_history_transform_updates_revision_without_undo_snapshot_and_clears_redo(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="live", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        service.apply_command(
            view.session_id,
            MeshEditCommand("transform", selection=selection, params={"translate": (0.0, 0.0, 1.0)}),
        )
        self.assertEqual(1, service.session_view(view.session_id).undo_count)
        self.assertTrue(service.undo(view.session_id).ok)
        self.assertEqual(1, service.session_view(view.session_id).redo_count)

        live = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={"translate": (0.0, 0.0, 0.25), "record_history": "false"},
            ),
        )

        state = service.session_view(view.session_id)
        self.assertTrue(live.ok)
        self.assertEqual(3, state.revision)
        self.assertEqual(0, state.undo_count)
        self.assertEqual(0, state.redo_count)
        self.assertEqual((0.0, 0.0, 0.25), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertEqual("noop", service.undo(view.session_id).status)
        self.assertEqual((0.0, 0.0, 0.25), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_identity_transform_does_not_create_revision(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="identity-transform", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("transform", selection=selection, params={"translate": (0.0, 0.0, 0.0), "scale": (1.0, 1.0, 1.0), "rotate": (0.0, 0.0, 0.0)}),
        )

        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_transform_uses_native_mesh_core_when_available(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-transform", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})
        calls: list[dict[str, object]] = []

        def native_transform(mesh: ParsedMesh, vertices_by_submesh: object, **params: object) -> dict[int, set[int]]:
            calls.append({"vertices_by_submesh": vertices_by_submesh, **params})
            mesh.submeshes[0].vertices[0] = (0.0, 0.0, 2.0)
            return {0: {0}}

        with patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_transform", side_effect=native_transform):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("transform", selection=selection, params={"translate": (0.0, 0.0, 2.0)}),
            )

        self.assertTrue(result.ok)
        self.assertEqual(((0, (0,)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0, 2.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertEqual({0: {0}}, calls[0]["vertices_by_submesh"])
        self.assertEqual((0.0, 0.0, 2.0), calls[0]["translate"])

    def test_transform_requires_explicit_selection_or_source_target(self) -> None:
        service = MeshService()
        empty_view = service.open_edit_session(_quad_mesh(), session_id="empty-transform-target", mode="edit")

        empty = service.apply_command(
            empty_view.session_id,
            MeshEditCommand("transform", params={"translate": (0.0, 0.0, 1.0)}),
        )

        empty_mesh = service.working_mesh(empty_view.session_id)
        self.assertTrue(empty.ok)
        self.assertEqual((), empty.affected_submesh_indices)
        self.assertEqual((), empty.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(empty_view.session_id).revision)
        self.assertEqual((0.0, 0.0, 0.0), empty_mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 1.0, 0.0), empty_mesh.submeshes[0].vertices[3])

        source_view = service.open_edit_session(_quad_mesh(), session_id="source-transform-target", mode="edit")
        source = service.apply_command(
            source_view.session_id,
            MeshEditCommand(
                "transform",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={"translate": (0.0, 0.0, 1.0)},
            ),
        )

        source_mesh = service.working_mesh(source_view.session_id)
        self.assertTrue(source.ok)
        self.assertEqual((0,), source.affected_submesh_indices)
        self.assertEqual(((0, (0, 1, 2, 3)),), source.changed_vertices_by_submesh)
        self.assertEqual(1, service.session_view(source_view.session_id).revision)
        self.assertEqual((0.0, 0.0, 1.0), source_mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 1.0, 1.0), source_mesh.submeshes[0].vertices[3])

    def test_stale_edge_selection_does_not_partially_edit_valid_endpoint(self) -> None:
        stale_edge = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)})
        service = MeshService()
        transform_view = service.open_edit_session(_quad_mesh(), session_id="stale-edge-transform", mode="edit")

        moved = service.apply_command(
            transform_view.session_id,
            MeshEditCommand("transform", selection=stale_edge, params={"translate": (0.0, 0.0, 1.0)}),
        )

        transform_submesh = service.working_mesh(transform_view.session_id).submeshes[0]
        self.assertTrue(moved.ok)
        self.assertEqual((), moved.affected_submesh_indices)
        self.assertEqual((0.0, 0.0, 0.0), transform_submesh.vertices[0])
        self.assertEqual(0, service.session_view(transform_view.session_id).revision)

        uv_view = service.open_edit_session(_quad_mesh(), session_id="stale-edge-uv", mode="edit")
        uv = service.apply_command(
            uv_view.session_id,
            MeshEditCommand("uv_transform", selection=stale_edge, params={"offset": (0.25, 0.0)}),
        )

        uv_submesh = service.working_mesh(uv_view.session_id).submeshes[0]
        self.assertTrue(uv.ok)
        self.assertEqual((), uv.affected_submesh_indices)
        self.assertEqual((0.0, 0.0), uv_submesh.uvs[0])
        self.assertEqual(0, service.session_view(uv_view.session_id).revision)

    def test_non_existing_edge_selection_does_not_edit_mesh_with_faces(self) -> None:
        non_edge = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3),)})
        service = MeshService()
        transform_view = service.open_edit_session(_quad_mesh(), session_id="non-edge-transform", mode="edit")

        moved = service.apply_command(
            transform_view.session_id,
            MeshEditCommand("transform", selection=non_edge, params={"translate": (0.0, 0.0, 1.0)}),
        )

        transform_submesh = service.working_mesh(transform_view.session_id).submeshes[0]
        self.assertTrue(moved.ok)
        self.assertEqual((), moved.affected_submesh_indices)
        self.assertEqual((0.0, 0.0, 0.0), transform_submesh.vertices[0])
        self.assertEqual((1.0, 1.0, 0.0), transform_submesh.vertices[3])
        self.assertEqual(0, service.session_view(transform_view.session_id).revision)

        uv_view = service.open_edit_session(_quad_mesh(), session_id="non-edge-uv", mode="edit")
        uv = service.apply_command(
            uv_view.session_id,
            MeshEditCommand("uv_transform", selection=non_edge, params={"offset": (0.25, 0.0)}),
        )

        uv_submesh = service.working_mesh(uv_view.session_id).submeshes[0]
        self.assertTrue(uv.ok)
        self.assertEqual((), uv.affected_submesh_indices)
        self.assertEqual((0.0, 0.0), uv_submesh.uvs[0])
        self.assertEqual(0, service.session_view(uv_view.session_id).revision)

        extrude_view = service.open_edit_session(_quad_mesh(), session_id="non-edge-extrude", mode="edit")
        extruded = service.apply_command(
            extrude_view.session_id,
            MeshEditCommand("extrude", selection=non_edge, params={"offset": (0.0, 0.0, 0.25)}),
        )

        extrude_submesh = service.working_mesh(extrude_view.session_id).submeshes[0]
        self.assertTrue(extruded.ok)
        self.assertFalse(extruded.topology_changed)
        self.assertEqual((), extruded.affected_submesh_indices)
        self.assertEqual(4, extrude_submesh.vertex_count)
        self.assertEqual(2, extrude_submesh.face_count)
        self.assertEqual(0, service.session_view(extrude_view.session_id).revision)

    def test_malformed_faces_are_ignored_by_shared_face_targeting(self) -> None:
        service = MeshService()
        malformed = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})
        malformed_view = service.open_edit_session(_malformed_face_mesh(), session_id="malformed-face-explicit", mode="edit")

        malformed_result = service.apply_command(malformed_view.session_id, MeshEditCommand("duplicate", selection=malformed))

        self.assertTrue(malformed_result.ok)
        self.assertFalse(malformed_result.topology_changed)
        self.assertEqual((), malformed_result.affected_submesh_indices)
        self.assertEqual(1, service.session_view(malformed_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(malformed_view.session_id).revision)

        edge_view = service.open_edit_session(_malformed_face_mesh(), session_id="malformed-face-edge", mode="edit")
        edge_result = service.apply_command(
            edge_view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        edge_mesh = service.working_mesh(edge_view.session_id)
        self.assertTrue(edge_result.ok)
        self.assertTrue(edge_result.topology_changed)
        self.assertEqual((1,), edge_result.affected_submesh_indices)
        self.assertEqual([(0, 1, 2)], edge_mesh.submeshes[1].faces)

        vertex_view = service.open_edit_session(_malformed_face_mesh(), session_id="malformed-face-vertex", mode="edit")
        vertex_result = service.apply_command(
            vertex_view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})),
        )

        vertex_mesh = service.working_mesh(vertex_view.session_id)
        self.assertTrue(vertex_result.ok)
        self.assertTrue(vertex_result.topology_changed)
        self.assertEqual((1,), vertex_result.affected_submesh_indices)
        self.assertEqual([(0, 1, 2)], vertex_mesh.submeshes[1].faces)

    def test_malformed_faces_do_not_crash_face_scanning_edit_ops(self) -> None:
        cases = (
            ("extrude", MeshEditSelection.from_maps(faces_by_submesh={0: (1,)}), {"offset": (0.0, 0.0, 0.25)}),
            ("inset", MeshEditSelection.from_maps(faces_by_submesh={0: (1,)}), {"amount": 0.25}),
            ("loop_cut", MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), {}),
            ("edge_split", MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), {}),
            ("fill", MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2, 3)}), {}),
            ("bridge", MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))}), {}),
            ("merge", MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 3)}), {}),
        )
        for action, selection, params in cases:
            with self.subTest(action=action):
                service = MeshService()
                view = service.open_edit_session(_malformed_face_mesh(), session_id=f"malformed-face-{action}", mode="edit")

                result = service.apply_command(view.session_id, MeshEditCommand(action, selection=selection, params=params))

                self.assertTrue(result.ok)
                if result.affected_submesh_indices or result.topology_changed:
                    for submesh in service.working_mesh(view.session_id).submeshes:
                        for face in submesh.faces:
                            self.assertEqual(3, len(face))
                            self.assertTrue(all(isinstance(index, int) for index in face))

    def test_mirror_aware_identity_transform_does_not_create_revision(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="identity-mirror-transform", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={
                    "translate": (0.0, 0.0, 0.0),
                    "mirror_x": True,
                    "mirror_pairs_by_submesh": {0: {0: 1, 1: 0}},
                },
            ),
        )

        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual((0.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertEqual((1.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[1])

    def test_empty_selection_brush_uses_radius_instead_of_whole_submesh(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="brush-radius", mode="sculpt")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                params={
                    "tool": "grab",
                    "center": (0.0, 0.0, 0.0),
                    "radius": 0.1,
                    "strength": 1.0,
                    "delta": (0.0, 0.0, 0.25),
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual(((0, (0,)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0, 0.25), mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 0.0, 0.0), mesh.submeshes[0].vertices[1])

    def test_identity_brush_does_not_create_revision(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="identity-brush", mode="sculpt")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                selection=selection,
                params={"tool": "grab", "center": (0.0, 0.0, 0.0), "radius": 1.0, "strength": 1.0, "delta": (0.0, 0.0, 0.0)},
            ),
        )

        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual((0.0, 0.0, 0.0), service.working_mesh(view.session_id).submeshes[0].vertices[0])

    def test_brush_rejects_non_finite_numeric_params(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="brush-non-finite", mode="sculpt")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                selection=selection,
                params={
                    "tool": "grab",
                    "center": (float("inf"), 0.0, 0.0),
                    "radius": float("inf"),
                    "strength": float("nan"),
                    "delta": (0.0, 0.0, float("inf")),
                    "amount": float("nan"),
                    "iterations": float("inf"),
                    "vertex_weights": {0: float("nan"), 1: float("inf")},
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), tuple(mesh.submeshes[0].vertices[:2]))

    def test_mode_specific_commands_noop_until_mode_matches(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="mode-gates", mode="object")
        face_selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})
        vertex_selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        blocked_topology = service.apply_command(
            view.session_id,
            MeshEditCommand("extrude", selection=face_selection, params={"offset": (0.0, 0.0, 0.25)}),
        )
        extruded = service.apply_command(
            view.session_id,
            MeshEditCommand("extrude", selection=face_selection, mode="edit", params={"offset": (0.0, 0.0, 0.25)}),
        )
        blocked_brush = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                selection=vertex_selection,
                params={"tool": "grab", "center": (0.0, 0.0, 0.0), "radius": 1.0, "strength": 1.0, "delta": (0.0, 0.0, 0.25)},
            ),
        )
        brushed = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "brush",
                selection=vertex_selection,
                mode="sculpt",
                params={"tool": "grab", "center": (0.0, 0.0, 0.0), "radius": 1.0, "strength": 1.0, "delta": (0.0, 0.0, 0.25)},
            ),
        )

        self.assertEqual("noop", blocked_topology.status)
        self.assertIn("requires edit mode", blocked_topology.diagnostics[0])
        self.assertTrue(extruded.ok)
        self.assertTrue(extruded.topology_changed)
        self.assertEqual("noop", blocked_brush.status)
        self.assertIn("requires sculpt mode", blocked_brush.diagnostics[0])
        self.assertTrue(brushed.ok)
        self.assertEqual("sculpt", service.session_view(view.session_id).mode)
        self.assertEqual(((0, (0,)),), brushed.changed_vertices_by_submesh)

    def test_material_commands_require_edit_mode(self) -> None:
        service = MeshService()
        assign_view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-assign-mode-gate", mode="object")
        target = MeshEditSelection.from_maps(source_indices=(0,))

        blocked_assign = service.apply_command(
            assign_view.session_id,
            MeshEditCommand("material_assign", selection=target, params={"material": "blocked", "texture": "blocked.dds"}),
        )
        assigned = service.apply_command(
            assign_view.session_id,
            MeshEditCommand("material_assign", selection=target, mode="edit", params={"material": "edited", "texture": "edited.dds"}),
        )

        assign_mesh = service.working_mesh(assign_view.session_id)
        self.assertEqual("noop", blocked_assign.status)
        self.assertIn("requires edit mode", blocked_assign.diagnostics[0])
        self.assertTrue(assigned.ok)
        self.assertEqual("edited", assign_mesh.submeshes[0].material)
        self.assertEqual("edited.dds", assign_mesh.submeshes[0].texture)

        copy_view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-copy-mode-gate", mode="object")
        blocked_copy = service.apply_command(
            copy_view.session_id,
            MeshEditCommand("material_copy", selection=MeshEditSelection.from_maps(source_indices=(1,)), params={"source_submesh_index": 0}),
        )
        copied = service.apply_command(
            copy_view.session_id,
            MeshEditCommand("material_copy", selection=MeshEditSelection.from_maps(source_indices=(1,)), mode="edit", params={"source_submesh_index": 0}),
        )

        copy_mesh = service.working_mesh(copy_view.session_id)
        self.assertEqual("noop", blocked_copy.status)
        self.assertIn("requires edit mode", blocked_copy.diagnostics[0])
        self.assertTrue(copied.ok)
        self.assertEqual("mat_a", copy_mesh.submeshes[1].material)
        self.assertEqual("a.dds", copy_mesh.submeshes[1].texture)

    def test_extrude_reuses_region_vertices_and_skips_internal_edges(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="extrude-region", mode="edit")
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)})

        extruded = service.apply_command(
            view.session_id,
            MeshEditCommand("extrude", selection=selection, params={"offset": (0.0, 0.0, 0.5)}),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(extruded.ok)
        self.assertTrue(extruded.topology_changed)
        self.assertEqual(((0, (4, 5, 6, 7)),), extruded.changed_vertices_by_submesh)
        self.assertEqual(8, submesh.vertex_count)
        self.assertEqual(12, submesh.face_count)
        self.assertEqual([(4, 5, 6), (5, 7, 6)], submesh.faces[2:4])
        self.assertFalse(any({1, 2}.issubset(set(face)) for face in submesh.faces[4:]))

    def test_extrude_can_pull_selected_loose_edge_into_faces(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_loose_edge_mesh(), session_id="extrude-loose-edge", mode="edit")

        extruded = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "extrude",
                selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}),
                params={"offset": (0.0, 0.0, 0.5)},
            ),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(extruded.ok)
        self.assertTrue(extruded.topology_changed)
        self.assertEqual(((0, (4, 5)),), extruded.changed_vertices_by_submesh)
        self.assertEqual(6, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual((0.0, 0.0, 0.5), submesh.vertices[4])
        self.assertEqual((1.0, 0.0, 0.5), submesh.vertices[5])
        self.assertEqual((0.0, 0.0), submesh.uvs[4])
        self.assertEqual((1.0, 0.0), submesh.uvs[5])
        self.assertEqual([(0, 1, 5), (0, 5, 4)], submesh.faces)

    def test_inset_reuses_region_vertices_and_skips_internal_edges(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="inset-region", mode="edit")
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)})

        inset = service.apply_command(
            view.session_id,
            MeshEditCommand("inset", selection=selection, params={"amount": 0.5}),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(inset.ok)
        self.assertTrue(inset.topology_changed)
        self.assertEqual(((0, (4, 5, 6, 7)),), inset.changed_vertices_by_submesh)
        self.assertEqual(8, submesh.vertex_count)
        self.assertEqual(10, submesh.face_count)
        self.assertEqual([(4, 5, 6), (5, 7, 6)], submesh.faces[:2])
        self.assertFalse(any({1, 2}.issubset(set(face)) for face in submesh.faces[2:]))

    def test_inset_zero_amount_noops_without_topology_or_revision(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="inset-zero", mode="edit")
        selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)})

        inset = service.apply_command(
            view.session_id,
            MeshEditCommand("inset", selection=selection, params={"amount": 0.0}),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(inset.ok)
        self.assertFalse(inset.topology_changed)
        self.assertEqual((), inset.affected_submesh_indices)
        self.assertEqual((), inset.changed_vertices_by_submesh)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], submesh.faces)
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_topology_uv_material_and_normals_commands_are_service_callable(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="suite", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)}, source_indices=(0,))
        service.apply_command(view.session_id, MeshEditCommand("select", selection=selection))

        extrude = service.apply_command(view.session_id, MeshEditCommand("extrude", params={"offset": (0.0, 0.0, 0.5)}))
        self.assertTrue(extrude.ok)
        self.assertTrue(extrude.topology_changed)
        self.assertGreater(service.working_mesh(view.session_id).total_faces, 4)

        uv = service.apply_command(view.session_id, MeshEditCommand("uv_transform", params={"flip_u": True, "offset": (0.25, 0.0)}))
        self.assertTrue(uv.ok)
        changed_uv_vertices = dict(uv.changed_vertices_by_submesh)[0]
        self.assertTrue({0, 1, 2, 3}.issubset(changed_uv_vertices))

        material = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                params={
                    "material": "edited",
                    "texture": "edited.dds",
                    "material_authority_profile": "material_authority_detail_mask",
                    "source_material_name": "source_mat",
                    "target_material_slot_index": 3,
                    "source_texture_set_key": "source_mat",
                    "roughness": 0.35,
                    "metalness": 0.8,
                },
            ),
        )
        self.assertTrue(material.ok)
        edited_submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertEqual("edited", edited_submesh.material)
        self.assertEqual("edited.dds", edited_submesh.texture)
        self.assertEqual("material_authority_detail_mask", getattr(edited_submesh, "cdmw_material_authority_profile"))
        self.assertEqual("true_source_authority_detail_mask", getattr(edited_submesh, "cdmw_material_authority_contract"))
        self.assertEqual("source_mat", getattr(edited_submesh, "cdmw_source_material_name"))
        self.assertEqual(3, getattr(edited_submesh, "cdmw_target_material_slot_index"))
        self.assertEqual("source_mat", getattr(edited_submesh, "cdmw_source_texture_set_key"))
        self.assertEqual({"roughness": 0.35, "metalness": 0.8}, getattr(edited_submesh, "preview_native_material_overrides"))

        recalc = service.apply_command(view.session_id, MeshEditCommand("recalculate_normals"))
        flip = service.apply_command(view.session_id, MeshEditCommand("flip_normals"))
        self.assertTrue(recalc.ok)
        self.assertTrue(flip.ok)

    def test_recalculate_normals_noops_when_normals_are_already_current(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="normal-noop", mode="edit")
        selection = MeshEditSelection.from_maps(source_indices=(0,))

        clean = service.apply_command(view.session_id, MeshEditCommand("recalculate_normals", selection=selection))
        service.working_mesh(view.session_id).submeshes[0].normals = [(0.0, 0.0, -1.0)] * 4
        stale = service.apply_command(view.session_id, MeshEditCommand("recalculate_normals", selection=selection))

        self.assertTrue(clean.ok)
        self.assertEqual((), clean.affected_submesh_indices)
        self.assertTrue(stale.ok)
        self.assertEqual((0,), stale.affected_submesh_indices)
        self.assertEqual(1, service.session_view(view.session_id).revision)

    def test_recalculate_normals_uses_native_mesh_core_when_available(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-normal-recalc", mode="edit")
        submesh = service.working_mesh(view.session_id).submeshes[0]
        submesh.normals = [(0.0, 0.0, -1.0)] * 4
        calls: list[set[int]] = []

        def native_recalculate(mesh: ParsedMesh, submesh_indices: set[int]) -> set[int]:
            calls.append(set(submesh_indices))
            mesh.submeshes[0].normals = [(0.0, 0.0, 1.0)] * 4
            return {0}

        with patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_recalculate_normals", side_effect=native_recalculate):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("recalculate_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
            )

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual([{0}], calls)
        self.assertEqual([(0.0, 0.0, 1.0)] * 4, submesh.normals)

    def test_generate_tangents_fills_tangent_channel_and_clears_export_warning(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="tangent-generate", mode="edit")
        before_report = service.validate_export(view.session_id, available_textures=("a.dds",))

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("generate_tangents", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )
        submesh = service.working_mesh(view.session_id).submeshes[0]
        after_report = service.validate_export(view.session_id, available_textures=("a.dds",))

        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(4, len(getattr(submesh, "tangents", ())))
        self.assertAlmostEqual(1.0, submesh.tangents[0][0], places=6)
        self.assertAlmostEqual(0.0, submesh.tangents[0][1], places=6)
        self.assertAlmostEqual(0.0, submesh.tangents[0][2], places=6)
        self.assertIn("missing_tangents", {issue.code for issue in before_report.warnings})
        self.assertNotIn("missing_tangents", {issue.code for issue in after_report.warnings})

    def test_sharpen_soften_and_copy_normals_are_service_routed(self) -> None:
        service = MeshService()
        sharp_view = service.open_edit_session(_bent_two_face_mesh(), session_id="normal-sharpen", mode="edit")

        sharp = service.apply_command(
            sharp_view.session_id,
            MeshEditCommand("sharpen_normals", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (1,)})),
        )
        sharp_submesh = service.working_mesh(sharp_view.session_id).submeshes[0]

        self.assertTrue(sharp.ok)
        self.assertEqual((0,), sharp.affected_submesh_indices)
        self.assertEqual({0, 1, 3}, set(dict(sharp.changed_vertices_by_submesh)[0]))
        self.assertEqual((0.0, -1.0, 0.0), sharp_submesh.normals[0])
        self.assertEqual((0.0, 0.0, 1.0), sharp_submesh.normals[2])

        soften = service.apply_command(
            sharp_view.session_id,
            MeshEditCommand("soften_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        self.assertTrue(soften.ok)
        self.assertEqual((0,), soften.affected_submesh_indices)
        self.assertNotEqual((0.0, -1.0, 0.0), sharp_submesh.normals[0])

        copy_view = service.open_edit_session(_quad_mesh(), session_id="normal-copy", mode="edit")
        copy_submesh = service.working_mesh(copy_view.session_id).submeshes[0]
        copy_submesh.normals = [(1.0, 0.0, 0.0)] * 4
        copied = service.apply_command(
            copy_view.session_id,
            MeshEditCommand("copy_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        self.assertTrue(copied.ok)
        self.assertEqual((0,), copied.affected_submesh_indices)
        self.assertEqual([(0.0, 0.0, 1.0)] * 4, copy_submesh.normals)

    def test_recalculate_normals_requires_explicit_selection_for_whole_part(self) -> None:
        service = MeshService()
        empty_view = service.open_edit_session(_quad_mesh(), session_id="empty-normal-recalc", mode="edit")
        service.working_mesh(empty_view.session_id).submeshes[0].normals = [(0.0, 0.0, -1.0)] * 4

        empty = service.apply_command(empty_view.session_id, MeshEditCommand("recalculate_normals"))

        empty_submesh = service.working_mesh(empty_view.session_id).submeshes[0]
        self.assertTrue(empty.ok)
        self.assertEqual((), empty.affected_submesh_indices)
        self.assertEqual([(0.0, 0.0, -1.0)] * 4, empty_submesh.normals)
        self.assertEqual(0, service.session_view(empty_view.session_id).revision)

        stale_edge_view = service.open_edit_session(_quad_mesh(), session_id="stale-edge-normal-recalc", mode="edit")
        stale_edge_submesh = service.working_mesh(stale_edge_view.session_id).submeshes[0]
        stale_edge_submesh.normals = [(0.0, 0.0, -1.0)] * 4
        stale_edge = service.apply_command(
            stale_edge_view.session_id,
            MeshEditCommand("recalculate_normals", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)})),
        )

        self.assertTrue(stale_edge.ok)
        self.assertEqual((), stale_edge.affected_submesh_indices)
        self.assertEqual([(0.0, 0.0, -1.0)] * 4, stale_edge_submesh.normals)
        self.assertEqual(0, service.session_view(stale_edge_view.session_id).revision)

        source_view = service.open_edit_session(_quad_mesh(), session_id="source-normal-recalc", mode="edit")
        source_submesh = service.working_mesh(source_view.session_id).submeshes[0]
        source_submesh.normals = [(0.0, 0.0, -1.0)] * 4
        source = service.apply_command(
            source_view.session_id,
            MeshEditCommand("recalculate_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        self.assertTrue(source.ok)
        self.assertEqual((0,), source.affected_submesh_indices)
        self.assertEqual([(0.0, 0.0, 1.0)] * 4, source_submesh.normals)
        self.assertEqual(1, service.session_view(source_view.session_id).revision)

    def test_flip_normals_can_target_selected_face_only(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="face-normal-flip", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("flip_normals", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertFalse(result.topology_changed)
        self.assertEqual([(0, 2, 1), (1, 3, 2)], submesh.faces)
        self.assertEqual(1, service.session_view(view.session_id).revision)

    def test_flip_normals_requires_explicit_selection_for_whole_part(self) -> None:
        service = MeshService()
        empty_view = service.open_edit_session(_quad_mesh(), session_id="empty-normal-flip", mode="edit")

        empty = service.apply_command(empty_view.session_id, MeshEditCommand("flip_normals"))

        empty_submesh = service.working_mesh(empty_view.session_id).submeshes[0]
        self.assertTrue(empty.ok)
        self.assertEqual((), empty.affected_submesh_indices)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], empty_submesh.faces)
        self.assertEqual(0, service.session_view(empty_view.session_id).revision)

        source_view = service.open_edit_session(_quad_mesh(), session_id="source-normal-flip", mode="edit")
        source = service.apply_command(
            source_view.session_id,
            MeshEditCommand("flip_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )

        source_submesh = service.working_mesh(source_view.session_id).submeshes[0]
        self.assertTrue(source.ok)
        self.assertEqual((0,), source.affected_submesh_indices)
        self.assertEqual([(0, 2, 1), (1, 2, 3)], source_submesh.faces)
        self.assertEqual(1, service.session_view(source_view.session_id).revision)

    def test_material_copy_preserves_authority_route_metadata(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-copy", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={
                    "material": "source_authority",
                    "texture": "source_authority.dds",
                    "material_profile": "runtime_xml",
                    "route_status": "ready",
                    "native_material_overrides": {"roughness": 0.2},
                },
            ),
        )
        copied = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_copy",
                selection=MeshEditSelection.from_maps(source_indices=(1,)),
                params={"source_submesh_index": 0},
            ),
        )

        target = service.working_mesh(view.session_id).submeshes[1]
        self.assertTrue(copied.ok)
        self.assertEqual("source_authority", target.material)
        self.assertEqual("source_authority.dds", target.texture)
        self.assertEqual("runtime_xml", getattr(target, "cdmw_material_authority_profile"))
        self.assertEqual("runtime_xml_preserve", getattr(target, "cdmw_material_authority_contract"))
        self.assertEqual("ready", getattr(target, "cdmw_material_route_status"))
        self.assertEqual({"roughness": 0.2}, getattr(target, "preview_native_material_overrides"))

    def test_material_copy_clears_stale_target_route_metadata(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-copy-clear", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(1,)),
                params={
                    "material": "routed_target",
                    "texture": "routed_target.dds",
                    "material_profile": "runtime_xml",
                    "route_status": "ready",
                    "native_material_overrides": {"roughness": 0.2},
                },
            ),
        )
        copied = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_copy",
                selection=MeshEditSelection.from_maps(source_indices=(1,)),
                params={"source_submesh_index": 0},
            ),
        )

        target = service.working_mesh(view.session_id).submeshes[1]
        self.assertTrue(copied.ok)
        self.assertEqual("mat_a", target.material)
        self.assertEqual("a.dds", target.texture)
        self.assertFalse(hasattr(target, "cdmw_material_authority_profile"))
        self.assertFalse(hasattr(target, "cdmw_material_authority_contract"))
        self.assertFalse(hasattr(target, "cdmw_material_route_status"))
        self.assertFalse(hasattr(target, "preview_native_material_overrides"))

    def test_plain_material_assign_clears_stale_route_metadata_and_overrides(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="material-assign-clear", mode="edit")
        selection = MeshEditSelection.from_maps(source_indices=(0,))

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=selection,
                params={
                    "material": "routed",
                    "texture": "routed.dds",
                    "material_profile": "runtime_xml",
                    "route_status": "ready",
                    "native_material_overrides": {"roughness": 0.2, "metalness": 0.6},
                },
            ),
        )
        plain = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=selection,
                params={"material": "plain", "texture": "plain.dds"},
            ),
        )

        target = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(plain.ok)
        self.assertEqual((0,), plain.affected_submesh_indices)
        self.assertEqual("plain", target.material)
        self.assertEqual("plain.dds", target.texture)
        self.assertFalse(hasattr(target, "cdmw_material_authority_profile"))
        self.assertFalse(hasattr(target, "cdmw_material_authority_contract"))
        self.assertFalse(hasattr(target, "cdmw_material_route_status"))
        self.assertFalse(hasattr(target, "preview_native_material_overrides"))

    def test_material_assign_can_target_selected_faces_by_splitting_material_part(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="face-material-assign", mode="edit")

        assigned = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={
                    "material": "face_material",
                    "texture": "face.dds",
                    "material_profile": "runtime_xml",
                    "native_material_overrides": {"roughness": 0.4},
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(assigned.ok)
        self.assertTrue(assigned.topology_changed)
        self.assertEqual((1,), assigned.affected_submesh_indices)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual(1, mesh.submeshes[0].face_count)
        self.assertEqual(1, mesh.submeshes[1].face_count)
        self.assertEqual("mat_a", mesh.submeshes[0].material)
        self.assertEqual("face_material", mesh.submeshes[1].material)
        self.assertEqual("face.dds", mesh.submeshes[1].texture)
        self.assertEqual("runtime_xml", getattr(mesh.submeshes[1], "cdmw_material_authority_profile"))
        self.assertEqual({"roughness": 0.4}, getattr(mesh.submeshes[1], "preview_native_material_overrides"))

    def test_material_copy_can_target_selected_faces_by_splitting_material_part(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="face-material-copy", mode="edit")

        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={
                    "material": "source_authority",
                    "texture": "source.dds",
                    "material_profile": "runtime_xml",
                    "route_status": "ready",
                    "native_material_overrides": {"roughness": 0.2},
                },
            ),
        )
        copied = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_copy",
                selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}),
                params={"source_submesh_index": 0},
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(copied.ok)
        self.assertTrue(copied.topology_changed)
        self.assertEqual((2,), copied.affected_submesh_indices)
        self.assertEqual(3, len(mesh.submeshes))
        self.assertEqual(1, mesh.submeshes[1].face_count)
        self.assertEqual(1, mesh.submeshes[2].face_count)
        self.assertEqual("mat_b", mesh.submeshes[1].material)
        self.assertEqual("source_authority", mesh.submeshes[2].material)
        self.assertEqual("source.dds", mesh.submeshes[2].texture)
        self.assertEqual("runtime_xml", getattr(mesh.submeshes[2], "cdmw_material_authority_profile"))
        self.assertEqual("ready", getattr(mesh.submeshes[2], "cdmw_material_route_status"))
        self.assertEqual({"roughness": 0.2}, getattr(mesh.submeshes[2], "preview_native_material_overrides"))

    def test_duplicate_preserves_material_route_metadata_on_face_copy(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="duplicate-material-route", mode="edit")

        assigned = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={
                    "material": "source_authority",
                    "texture": "source_authority.dds",
                    "material_profile": "runtime_xml",
                    "route_status": "ready",
                    "native_material_overrides": {"roughness": 0.2},
                },
            ),
        )
        duplicated = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "duplicate",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            ),
        )

        mesh = service.working_mesh(view.session_id)
        source = mesh.submeshes[0]
        copied = mesh.submeshes[1]
        self.assertTrue(assigned.ok)
        self.assertTrue(duplicated.ok)
        self.assertTrue(duplicated.topology_changed)
        self.assertEqual((1,), duplicated.affected_submesh_indices)
        self.assertEqual("source_authority", copied.material)
        self.assertEqual("source_authority.dds", copied.texture)
        self.assertEqual(getattr(source, "cdmw_material_authority_profile"), getattr(copied, "cdmw_material_authority_profile"))
        self.assertEqual(getattr(source, "cdmw_material_authority_contract"), getattr(copied, "cdmw_material_authority_contract"))
        self.assertEqual(getattr(source, "cdmw_material_route_status"), getattr(copied, "cdmw_material_route_status"))
        self.assertEqual({"roughness": 0.2}, getattr(copied, "preview_native_material_overrides"))

    def test_duplicate_and_mirror_require_explicit_selection_or_source_target(self) -> None:
        service = MeshService()

        duplicate_empty_view = service.open_edit_session(_quad_mesh(), session_id="duplicate-empty-target", mode="edit")
        duplicate_empty = service.apply_command(duplicate_empty_view.session_id, MeshEditCommand("duplicate"))
        self.assertTrue(duplicate_empty.ok)
        self.assertFalse(duplicate_empty.topology_changed)
        self.assertEqual((), duplicate_empty.affected_submesh_indices)
        self.assertEqual(1, service.session_view(duplicate_empty_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(duplicate_empty_view.session_id).revision)

        invalid_face_view = service.open_edit_session(_quad_mesh(), session_id="duplicate-invalid-face-target", mode="edit")
        invalid_face = service.apply_command(
            invalid_face_view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (99,)})),
        )
        self.assertTrue(invalid_face.ok)
        self.assertFalse(invalid_face.topology_changed)
        self.assertEqual((), invalid_face.affected_submesh_indices)
        self.assertEqual(1, service.session_view(invalid_face_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(invalid_face_view.session_id).revision)

        invalid_all_view = service.open_edit_session(_quad_mesh(), session_id="duplicate-invalid-all-target", mode="edit")
        invalid_all = service.apply_command(
            invalid_all_view.session_id,
            MeshEditCommand(
                "duplicate",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (99,)}, source_indices=(99,)),
                params={"all": True},
            ),
        )
        self.assertTrue(invalid_all.ok)
        self.assertFalse(invalid_all.topology_changed)
        self.assertEqual((), invalid_all.affected_submesh_indices)
        self.assertEqual(1, service.session_view(invalid_all_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(invalid_all_view.session_id).revision)

        duplicate_all_view = service.open_edit_session(_quad_mesh(), session_id="duplicate-all-target", mode="edit")
        duplicate_all = service.apply_command(
            duplicate_all_view.session_id,
            MeshEditCommand("duplicate", params={"all": True}),
        )
        self.assertTrue(duplicate_all.ok)
        self.assertTrue(duplicate_all.topology_changed)
        self.assertEqual((1,), duplicate_all.affected_submesh_indices)
        self.assertEqual(2, service.session_view(duplicate_all_view.session_id).submesh_count)

        duplicate_source_view = service.open_edit_session(_quad_mesh(), session_id="duplicate-source-target", mode="edit")
        duplicate_source = service.apply_command(
            duplicate_source_view.session_id,
            MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )
        duplicate_source_mesh = service.working_mesh(duplicate_source_view.session_id)
        self.assertTrue(duplicate_source.ok)
        self.assertTrue(duplicate_source.topology_changed)
        self.assertEqual((1,), duplicate_source.affected_submesh_indices)
        self.assertEqual(2, len(duplicate_source_mesh.submeshes))
        self.assertEqual(2, duplicate_source_mesh.submeshes[1].face_count)

        mirror_empty_view = service.open_edit_session(_quad_mesh(), session_id="mirror-empty-target", mode="edit")
        mirror_empty = service.apply_command(mirror_empty_view.session_id, MeshEditCommand("mirror", params={"axis": "x"}))
        self.assertTrue(mirror_empty.ok)
        self.assertFalse(mirror_empty.topology_changed)
        self.assertEqual((), mirror_empty.affected_submesh_indices)
        self.assertEqual(1, service.session_view(mirror_empty_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(mirror_empty_view.session_id).revision)

        mirror_invalid_face_view = service.open_edit_session(_quad_mesh(), session_id="mirror-invalid-face-target", mode="edit")
        mirror_invalid_face = service.apply_command(
            mirror_invalid_face_view.session_id,
            MeshEditCommand("mirror", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (99,)}), params={"axis": "x"}),
        )
        self.assertTrue(mirror_invalid_face.ok)
        self.assertFalse(mirror_invalid_face.topology_changed)
        self.assertEqual((), mirror_invalid_face.affected_submesh_indices)
        self.assertEqual(1, service.session_view(mirror_invalid_face_view.session_id).submesh_count)
        self.assertEqual(0, service.session_view(mirror_invalid_face_view.session_id).revision)

        mirror_source_view = service.open_edit_session(_quad_mesh(), session_id="mirror-source-target", mode="edit")
        mirror_source = service.apply_command(
            mirror_source_view.session_id,
            MeshEditCommand("mirror", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"axis": "x"}),
        )
        mirror_source_mesh = service.working_mesh(mirror_source_view.session_id)
        self.assertTrue(mirror_source.ok)
        self.assertTrue(mirror_source.topology_changed)
        self.assertEqual((1,), mirror_source.affected_submesh_indices)
        self.assertEqual(2, len(mirror_source_mesh.submeshes))
        self.assertEqual((0.0, 0.0, 0.0), mirror_source_mesh.submeshes[1].vertices[0])
        self.assertEqual((-1.0, 0.0, 0.0), mirror_source_mesh.submeshes[1].vertices[1])

        mirror_in_place_empty_view = service.open_edit_session(_quad_mesh(), session_id="mirror-in-place-empty-target", mode="edit")
        mirror_in_place_empty = service.apply_command(
            mirror_in_place_empty_view.session_id,
            MeshEditCommand("mirror", params={"axis": "x", "in_place": True}),
        )
        mirror_in_place_empty_mesh = service.working_mesh(mirror_in_place_empty_view.session_id)
        self.assertTrue(mirror_in_place_empty.ok)
        self.assertEqual((), mirror_in_place_empty.affected_submesh_indices)
        self.assertEqual((), mirror_in_place_empty.changed_vertices_by_submesh)
        self.assertEqual((1.0, 0.0, 0.0), mirror_in_place_empty_mesh.submeshes[0].vertices[1])

    def test_duplicate_derives_face_copy_targets_from_edge_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="duplicate-edge-face", mode="edit")

        duplicated = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "duplicate",
                selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}),
            ),
        )

        mesh = service.working_mesh(view.session_id)
        copied = mesh.submeshes[1]
        self.assertTrue(duplicated.ok)
        self.assertTrue(duplicated.topology_changed)
        self.assertEqual((1,), duplicated.affected_submesh_indices)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual(3, copied.vertex_count)
        self.assertEqual(1, copied.face_count)
        self.assertEqual([(0, 1, 2)], copied.faces)

    def test_mirror_derives_face_copy_targets_from_edge_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="mirror-edge-face", mode="edit")
        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={"material": "routed", "texture": "routed.dds", "material_profile": "runtime_xml", "route_status": "ready"},
            ),
        )

        mirrored = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "mirror",
                selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}),
                params={"axis": "x"},
            ),
        )

        mesh = service.working_mesh(view.session_id)
        copied = mesh.submeshes[1]
        self.assertTrue(mirrored.ok)
        self.assertTrue(mirrored.topology_changed)
        self.assertEqual((1,), mirrored.affected_submesh_indices)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual(3, copied.vertex_count)
        self.assertEqual(1, copied.face_count)
        self.assertEqual([(0, 2, 1)], copied.faces)
        self.assertEqual([(0.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], copied.vertices)
        self.assertEqual("routed", copied.material)
        self.assertEqual("runtime_xml", getattr(copied, "cdmw_material_authority_profile"))
        self.assertEqual("ready", getattr(copied, "cdmw_material_route_status"))

    def test_duplicate_noops_when_edge_selection_matches_no_faces(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="duplicate-stale-edge", mode="edit")

        duplicated = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "duplicate",
                selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)}),
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(duplicated.ok)
        self.assertFalse(duplicated.topology_changed)
        self.assertEqual((), duplicated.affected_submesh_indices)
        self.assertEqual(1, len(mesh.submeshes))
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_split_detaches_selected_faces_in_place(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="split-edge-face", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("split", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        mesh = service.working_mesh(view.session_id)
        submesh = mesh.submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(((0, (4, 5)),), result.changed_vertices_by_submesh)
        self.assertEqual(1, len(mesh.submeshes))
        self.assertEqual(6, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual([(0, 4, 5), (1, 3, 2)], submesh.faces)
        self.assertEqual((1.0, 0.0, 0.0), submesh.vertices[4])
        self.assertEqual((0.0, 1.0, 0.0), submesh.vertices[5])

    def test_separate_derives_exact_face_targets_from_edge_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="separate-edge-face", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("separate", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        mesh = service.working_mesh(view.session_id)
        source = mesh.submeshes[0]
        moved = mesh.submeshes[1]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0, 1), result.affected_submesh_indices)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual(3, source.vertex_count)
        self.assertEqual(1, source.face_count)
        self.assertEqual([(0, 2, 1)], source.faces)
        self.assertEqual(3, moved.vertex_count)
        self.assertEqual(1, moved.face_count)
        self.assertEqual([(0, 1, 2)], moved.faces)

    def test_split_noops_when_edge_selection_matches_no_faces(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="split-stale-edge", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("split", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)})),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertFalse(result.topology_changed)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual(1, len(mesh.submeshes))
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_subdivide_derives_exact_face_targets_from_edge_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="subdivide-edge-face", mode="edit")

        subdivided = service.apply_command(
            view.session_id,
            MeshEditCommand("subdivide", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        changed_vertices = dict(subdivided.changed_vertices_by_submesh)[0]
        self.assertTrue(subdivided.ok)
        self.assertTrue(subdivided.topology_changed)
        self.assertEqual((0,), subdivided.affected_submesh_indices)
        self.assertEqual(7, submesh.vertex_count)
        self.assertEqual(5, submesh.face_count)
        self.assertEqual((1, 3, 2), submesh.faces[-1])
        self.assertEqual({0, 1, 2, 4, 5, 6}, set(changed_vertices))

    def test_subdivide_noops_when_edge_selection_matches_no_faces(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="subdivide-stale-edge", mode="edit")

        subdivided = service.apply_command(
            view.session_id,
            MeshEditCommand("subdivide", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)})),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(subdivided.ok)
        self.assertFalse(subdivided.topology_changed)
        self.assertEqual((), subdivided.affected_submesh_indices)
        self.assertEqual(1, len(mesh.submeshes))
        self.assertEqual(4, mesh.submeshes[0].vertex_count)
        self.assertEqual(2, mesh.submeshes[0].face_count)
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_delete_derives_exact_face_targets_from_edge_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="delete-edge-face", mode="edit")

        deleted = service.apply_command(
            view.session_id,
            MeshEditCommand("delete", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(deleted.ok)
        self.assertTrue(deleted.topology_changed)
        self.assertEqual((0,), deleted.affected_submesh_indices)
        self.assertEqual(3, submesh.vertex_count)
        self.assertEqual(1, submesh.face_count)
        self.assertEqual([(0, 2, 1)], submesh.faces)

    def test_dissolve_derives_exact_face_targets_from_edge_selection_without_orphan_compaction(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="dissolve-edge-face", mode="edit")

        dissolved = service.apply_command(
            view.session_id,
            MeshEditCommand("dissolve", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(dissolved.ok)
        self.assertTrue(dissolved.topology_changed)
        self.assertEqual((0,), dissolved.affected_submesh_indices)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual(1, submesh.face_count)
        self.assertEqual([(1, 3, 2)], submesh.faces)

    def test_dissolve_internal_edge_retriangulates_quad_region(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="dissolve-internal-edge", mode="edit")

        dissolved = service.apply_command(
            view.session_id,
            MeshEditCommand("dissolve", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(dissolved.ok)
        self.assertTrue(dissolved.topology_changed)
        self.assertEqual((0,), dissolved.affected_submesh_indices)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], submesh.faces)

    def test_material_actions_noop_without_assign_params_or_copy_target_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-noop", mode="edit")

        assign = service.apply_command(
            view.session_id,
            MeshEditCommand("material_assign", selection=MeshEditSelection.from_maps(source_indices=(0,))),
        )
        untargeted_assign = service.apply_command(
            view.session_id,
            MeshEditCommand("material_assign", params={"material": "untargeted", "texture": "untargeted.dds"}),
        )
        copy = service.apply_command(
            view.session_id,
            MeshEditCommand("material_copy", params={"source_submesh_index": 0}),
        )

        mesh = service.working_mesh(view.session_id)
        state = service.session_view(view.session_id)
        self.assertTrue(assign.ok)
        self.assertEqual((), assign.affected_submesh_indices)
        self.assertTrue(untargeted_assign.ok)
        self.assertEqual((), untargeted_assign.affected_submesh_indices)
        self.assertTrue(copy.ok)
        self.assertEqual((), copy.affected_submesh_indices)
        self.assertEqual(0, state.revision)
        self.assertEqual(0, state.undo_count)
        self.assertEqual("mat_a", mesh.submeshes[0].material)
        self.assertEqual("a.dds", mesh.submeshes[0].texture)
        self.assertEqual("mat_b", mesh.submeshes[1].material)
        self.assertEqual("b.dds", mesh.submeshes[1].texture)

    def test_material_copy_noops_on_malformed_source_index(self) -> None:
        malformed_values = ("bad", float("inf"), 0.5, True)
        for value in malformed_values:
            with self.subTest(value=value):
                service = MeshService()
                view = service.open_edit_session(_quad_mesh(two_parts=True), session_id=f"material-copy-bad-source-{value}", mode="edit")
                before = [(submesh.material, submesh.texture) for submesh in service.working_mesh(view.session_id).submeshes]

                result = service.apply_command(
                    view.session_id,
                    MeshEditCommand(
                        "material_copy",
                        selection=MeshEditSelection.from_maps(source_indices=(1,)),
                        params={"source_submesh_index": value},
                    ),
                )

                self.assertTrue(result.ok)
                self.assertEqual((), result.affected_submesh_indices)
                self.assertFalse(result.topology_changed)
                self.assertEqual(0, service.session_view(view.session_id).revision)
                self.assertEqual(before, [(submesh.material, submesh.texture) for submesh in service.working_mesh(view.session_id).submeshes])

    def test_identity_material_assign_and_copy_do_not_create_revision(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(two_parts=True), session_id="material-identity", mode="edit")

        assign = service.apply_command(
            view.session_id,
            MeshEditCommand("material_assign", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"material": "mat_a", "texture": "a.dds"}),
        )
        copy = service.apply_command(
            view.session_id,
            MeshEditCommand("material_copy", selection=MeshEditSelection.from_maps(source_indices=(1,)), params={"source_submesh_index": 0}),
        )
        copy_again = service.apply_command(
            view.session_id,
            MeshEditCommand("material_copy", selection=MeshEditSelection.from_maps(source_indices=(1,)), params={"source_submesh_index": 0}),
        )

        mesh = service.working_mesh(view.session_id)
        state = service.session_view(view.session_id)
        self.assertTrue(assign.ok)
        self.assertEqual((), assign.affected_submesh_indices)
        self.assertTrue(copy.ok)
        self.assertEqual((1,), copy.affected_submesh_indices)
        self.assertTrue(copy_again.ok)
        self.assertEqual((), copy_again.affected_submesh_indices)
        self.assertEqual(1, state.revision)
        self.assertEqual("mat_a", mesh.submeshes[0].material)
        self.assertEqual("mat_a", mesh.submeshes[1].material)

    def test_uv_transform_can_expand_to_selected_uv_island(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_two_uv_island_mesh(), session_id="uv-island", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"uv_island": True, "offset": (0.25, 0.0)}),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual(((0, (0, 1, 2)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.25, 0.0), mesh.submeshes[0].uvs[0])
        self.assertEqual((0.75, 0.0), mesh.submeshes[0].uvs[1])
        self.assertEqual((0.25, 0.5), mesh.submeshes[0].uvs[2])
        self.assertEqual((2.0, 0.0), mesh.submeshes[0].uvs[3])

    def test_uv_transform_can_normalize_selected_uv_bounds(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_two_uv_island_mesh(), session_id="uv-normalize", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (3, 4, 5)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"normalize": True}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, (3, 4, 5)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0), uvs[3])
        self.assertEqual((1.0, 0.0), uvs[4])
        self.assertEqual((0.0, 1.0), uvs[5])
        self.assertEqual((0.0, 0.0), uvs[0])

    def test_uv_transform_can_align_selected_uv_axis(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-align", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 3)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"align_v": "min"}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, (3,)),), result.changed_vertices_by_submesh)
        self.assertEqual((1.0, 0.0), uvs[1])
        self.assertEqual((1.0, 0.0), uvs[3])
        self.assertEqual((0.0, 1.0), uvs[2])

    def test_uv_transform_can_project_selected_vertices_planar(self) -> None:
        service = MeshService()
        mesh = _quad_mesh()
        mesh.submeshes[0].uvs = [(0.0, 0.0)] * 4
        view = service.open_edit_session(mesh, session_id="uv-planar", mode="edit")
        selection = MeshEditSelection.from_maps(source_indices=(0,))

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"projection": "planar", "plane": "xy"}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, (1, 2, 3)),), result.changed_vertices_by_submesh)
        self.assertEqual(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)), tuple(uvs))

    def test_uv_transform_can_project_selected_vertices_box(self) -> None:
        service = MeshService()
        submesh = SubMesh(
            name="box_projection",
            material="mat",
            texture="uv.dds",
            vertices=[(5.0, 0.0, 0.0), (5.0, 1.0, 0.0), (5.0, 0.0, 2.0)],
            uvs=[(0.0, 0.0)] * 3,
            normals=[(1.0, 0.0, 0.0)] * 3,
            faces=[(0, 1, 2)],
            vertex_count=3,
            face_count=1,
        )
        view = service.open_edit_session(
            ParsedMesh(path="box.pac", format="pac", submeshes=[submesh], total_vertices=3, total_faces=1, has_uvs=True),
            session_id="uv-box",
            mode="edit",
        )

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"projection": "box"}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, (1, 2)),), result.changed_vertices_by_submesh)
        self.assertEqual(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)), tuple(uvs))

    def test_uv_transform_can_project_selected_vertices_cylindrical(self) -> None:
        service = MeshService()
        submesh = SubMesh(
            name="cylinder_projection",
            material="mat",
            texture="uv.dds",
            vertices=[(1.0, 0.0, 0.0), (0.0, 1.0, 1.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 1.0)],
            uvs=[(0.0, 0.0)] * 4,
            normals=[(0.0, 0.0, 1.0)] * 4,
            faces=[(0, 1, 2), (0, 3, 2)],
            vertex_count=4,
            face_count=2,
        )
        view = service.open_edit_session(
            ParsedMesh(path="cyl.pac", format="pac", submeshes=[submesh], total_vertices=4, total_faces=2, has_uvs=True),
            session_id="uv-cyl",
            mode="edit",
        )

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"projection": "cylindrical"}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, (0, 1, 2, 3)),), result.changed_vertices_by_submesh)
        self.assertAlmostEqual(0.5, uvs[0][0], places=6)
        self.assertAlmostEqual(0.0, uvs[0][1], places=6)
        self.assertAlmostEqual(0.75, uvs[1][0], places=6)
        self.assertAlmostEqual(1.0, uvs[1][1], places=6)
        self.assertAlmostEqual(1.0, uvs[2][0], places=6)
        self.assertAlmostEqual(0.0, uvs[2][1], places=6)
        self.assertAlmostEqual(0.25, uvs[3][0], places=6)
        self.assertAlmostEqual(1.0, uvs[3][1], places=6)

    def test_uv_transform_can_pack_selected_uv_islands(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_two_uv_island_mesh(), session_id="uv-pack", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"pack": True, "padding": 0.0}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, (2, 3, 4, 5)),), result.changed_vertices_by_submesh)
        self.assertEqual(((0.0, 0.0), (0.5, 0.0), (0.0, 1.0), (0.5, 0.0), (1.0, 0.0), (0.5, 1.0)), tuple(uvs))

    def test_uv_transform_can_snap_selected_uvs_to_grid_and_pixels(self) -> None:
        service = MeshService()
        mesh = _quad_mesh()
        mesh.submeshes[0].uvs[0] = (0.12, 0.39)
        mesh.submeshes[0].uvs[1] = (0.13, 0.62)
        view = service.open_edit_session(mesh, session_id="uv-snap", mode="edit")

        grid = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), params={"snap_grid": 0.25}),
        )
        pixels = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "uv_transform",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)}),
                params={"pixel_snap": True, "texture_size": (4.0, 4.0)},
            ),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(grid.ok)
        self.assertTrue(pixels.ok)
        self.assertEqual((0.0, 0.5), uvs[0])
        self.assertEqual((0.25, 0.5), uvs[1])

    def test_select_uv_region_updates_session_selection_without_editing_mesh(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-region-select", mode="edit")

        result = service.select_uv_region(view.session_id, (0.0, 0.0), (0.1, 1.0))

        selection = service.session_view(view.session_id).selection
        summary = service.uv_summary(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual("select", result.action)
        self.assertEqual(0, result.revision)
        self.assertEqual({0: {0, 2}}, selection.vertex_map())
        self.assertEqual(1, summary.selected_island_count)

    def test_select_uv_lasso_updates_session_selection_without_editing_mesh(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-lasso-select", mode="edit")

        result = service.select_uv_lasso(
            view.session_id,
            ((-0.1, -0.1), (0.2, -0.1), (0.2, 1.1), (-0.1, 1.1)),
        )

        selection = service.session_view(view.session_id).selection
        self.assertTrue(result.ok)
        self.assertEqual("select", result.action)
        self.assertEqual(0, result.revision)
        self.assertEqual({0: {0, 2}}, selection.vertex_map())

    def test_uv_transform_uses_native_mesh_core_when_available(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="native-uv-transform", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)})
        calls: list[dict[str, object]] = []

        def native_uv_transform(mesh: ParsedMesh, vertices_by_submesh: object, **params: object) -> dict[int, set[int]]:
            calls.append({"vertices_by_submesh": vertices_by_submesh, **params})
            mesh.submeshes[0].uvs[1] = (1.25, 0.0)
            return {0: {1}}

        with patch("cdmw.modding.mesh_edit_ops.apply_native_mesh_uv_transform", side_effect=native_uv_transform):
            result = service.apply_command(
                view.session_id,
                MeshEditCommand("uv_transform", selection=selection, params={"offset": (0.25, 0.0)}),
            )

        self.assertTrue(result.ok)
        self.assertEqual(((0, (1,)),), result.changed_vertices_by_submesh)
        self.assertEqual((1.25, 0.0), service.working_mesh(view.session_id).submeshes[0].uvs[1])
        self.assertEqual({0: {1}}, calls[0]["vertices_by_submesh"])
        self.assertEqual((0.25, 0.0), calls[0]["offset"])
        self.assertEqual((1.0, 1.0), calls[0]["scale"])
        self.assertEqual(0.0, calls[0]["rotate_degrees"])
        self.assertEqual((0.0, 0.0), calls[0]["pivot"])

    def test_uv_transform_can_rotate_selected_uvs_around_pivot(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-rotate", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"rotate": 90.0, "pivot": (0.5, 0.5)}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, (1, 2)),), result.changed_vertices_by_submesh)
        self.assertAlmostEqual(1.0, uvs[1][0], places=6)
        self.assertAlmostEqual(1.0, uvs[1][1], places=6)
        self.assertAlmostEqual(0.0, uvs[2][0], places=6)
        self.assertAlmostEqual(0.0, uvs[2][1], places=6)

    def test_uv_transform_flip_uses_explicit_pivot(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-flip-pivot", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"flip_u": True, "flip_v": True, "pivot": (0.25, 0.25)}),
        )

        uvs = service.working_mesh(view.session_id).submeshes[0].uvs
        self.assertTrue(result.ok)
        self.assertEqual(((0, (1, 2)),), result.changed_vertices_by_submesh)
        self.assertEqual((-0.5, 0.5), uvs[1])
        self.assertEqual((0.5, -0.5), uvs[2])

    def test_uv_transform_does_not_merge_disconnected_overlapping_uv_islands(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_overlapping_uv_island_mesh(), session_id="uv-overlap-island", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"uv_island": True, "offset": (0.25, 0.0)}),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual(((0, (0, 1, 2)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.25, 0.0), mesh.submeshes[0].uvs[0])
        self.assertEqual((1.25, 0.0), mesh.submeshes[0].uvs[1])
        self.assertEqual((0.25, 1.0), mesh.submeshes[0].uvs[2])
        self.assertEqual((0.0, 0.0), mesh.submeshes[0].uvs[3])
        self.assertEqual((1.0, 0.0), mesh.submeshes[0].uvs[4])
        self.assertEqual((0.0, 1.0), mesh.submeshes[0].uvs[5])

    def test_uv_transform_noops_without_selection(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-no-selection", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", params={"offset": (0.25, 0.0)}),
        )

        mesh = service.working_mesh(view.session_id)
        state = service.session_view(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, state.revision)
        self.assertEqual(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)), tuple(mesh.submeshes[0].uvs))

    def test_uv_transform_noops_when_selected_uvs_do_not_change(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-identity", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("uv_transform", selection=selection, params={"offset": (0.0, 0.0), "scale": (1.0, 1.0), "rotate": 0.0}),
        )

        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)

    def test_uv_transform_rejects_non_finite_vector_params(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="uv-non-finite", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "uv_transform",
                selection=selection,
                params={
                    "offset": (float("inf"), 0.0),
                    "scale": (float("nan"), 1.0),
                    "pivot": (float("inf"), float("nan")),
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)), tuple(mesh.submeshes[0].uvs))

    def test_transform_can_apply_mirror_aware_vertex_drag_through_service(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="mirror", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={
                    "translate": (0.25, 0.0, 0.0),
                    "mirror_x": True,
                    "mirror_pairs_by_submesh": {0: {0: 1, 1: 0}},
                    "recompute_normals": False,
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual(((0, (0, 1)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.25, 0.0, 0.0), mesh.submeshes[0].vertices[0])
        self.assertEqual((0.75, 0.0, 0.0), mesh.submeshes[0].vertices[1])

    def test_transform_can_skip_normal_recompute_for_live_preview_drag(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="live-transform-no-normal", mode="edit")
        mesh = service.working_mesh(view.session_id)
        mesh.submeshes[0].normals = [(0.0, 0.0, -1.0)] * 4
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={"translate": (0.0, 0.0, 0.25), "recompute_normals": False, "record_history": False},
            ),
        )

        self.assertTrue(result.ok)
        self.assertEqual(((0, (0,)),), result.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0, 0.25), service.working_mesh(view.session_id).submeshes[0].vertices[0])
        self.assertEqual([(0.0, 0.0, -1.0)] * 4, service.working_mesh(view.session_id).submeshes[0].normals)

    def test_transform_rejects_non_finite_vector_params(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="transform-non-finite", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={
                    "translate": (float("inf"), 0.0, 0.0),
                    "scale": (float("nan"), 1.0, 1.0),
                    "rotate": (0.0, 0.0, float("inf")),
                    "pivot": (float("nan"), 0.0, 0.0),
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), tuple(mesh.submeshes[0].vertices[:2]))

    def test_transform_can_rotate_and_scale_selected_vertices_through_service(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="rotate-scale", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2)})

        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={
                    "pivot": (0.0, 0.0, 0.0),
                    "scale": (2.0, 1.0, 1.0),
                    "rotate": (0.0, 0.0, 90.0),
                    "translate": (1.0, 1.0, 0.0),
                },
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual(((0, (1,)),), result.changed_vertices_by_submesh)
        self.assertAlmostEqual(1.0, mesh.submeshes[0].vertices[1][0], places=6)
        self.assertAlmostEqual(3.0, mesh.submeshes[0].vertices[1][1], places=6)
        self.assertAlmostEqual(0.0, mesh.submeshes[0].vertices[2][0], places=6)
        self.assertAlmostEqual(1.0, mesh.submeshes[0].vertices[2][1], places=6)

    def test_transform_can_constrain_axis_and_snap_to_increment(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="axis-snap", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 3)})

        moved = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=selection,
                params={"translate": (0.26, 0.26, 0.26), "axis": "z", "snap": 0.25},
            ),
        )

        mesh = service.working_mesh(view.session_id)
        self.assertTrue(moved.ok)
        self.assertEqual(((0, (0, 3)),), moved.changed_vertices_by_submesh)
        self.assertEqual((0.0, 0.0, 0.25), mesh.submeshes[0].vertices[0])
        self.assertEqual((1.0, 1.0, 0.25), mesh.submeshes[0].vertices[3])

        scaled = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (3,)}),
                params={"pivot": (0.0, 0.0, 0.0), "scale": (2.0, 2.0, 2.0), "axis": "x"},
            ),
        )

        self.assertTrue(scaled.ok)
        self.assertEqual((2.0, 1.0, 0.25), service.working_mesh(view.session_id).submeshes[0].vertices[3])

    def test_edge_split_can_split_selected_edge_seam(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="edge-split", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})

        result = service.apply_command(view.session_id, MeshEditCommand("edge_split", selection=selection))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, (4, 5)),), result.changed_vertices_by_submesh)
        self.assertEqual(6, len(submesh.vertices))
        self.assertEqual(6, len(submesh.uvs))
        self.assertEqual((0, 1, 2), submesh.faces[0])
        self.assertEqual((4, 3, 5), submesh.faces[1])

    def test_bridge_connects_loose_edges_and_rejects_already_filled_pairs(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_loose_edge_mesh(), session_id="bridge", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))})

        result = service.apply_command(view.session_id, MeshEditCommand("bridge", selection=selection))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual(2, len(submesh.faces))
        self.assertEqual((0, 1, 3), submesh.faces[-2])
        self.assertEqual((0, 3, 2), submesh.faces[-1])

        filled_view = service.open_edit_session(_quad_mesh(), session_id="bridge-filled", mode="edit")
        rejected = service.apply_command(filled_view.session_id, MeshEditCommand("bridge", selection=selection))
        filled_submesh = service.working_mesh(filled_view.session_id).submeshes[0]

        self.assertTrue(rejected.ok)
        self.assertFalse(rejected.topology_changed)
        self.assertEqual((), rejected.affected_submesh_indices)
        self.assertEqual(2, filled_submesh.face_count)
        self.assertEqual(0, service.session_view(filled_view.session_id).revision)

    def test_fill_uses_explicit_vertices_and_edges_without_expanding_face_selection(self) -> None:
        service = MeshService()
        edge_view = service.open_edit_session(_quad_mesh(), session_id="fill-edge", mode="edit")

        filled = service.apply_command(
            edge_view.session_id,
            MeshEditCommand("fill", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 3), (0, 3))})),
        )

        edge_submesh = service.working_mesh(edge_view.session_id).submeshes[0]
        self.assertTrue(filled.ok)
        self.assertTrue(filled.topology_changed)
        self.assertEqual((0,), filled.affected_submesh_indices)
        self.assertEqual(3, edge_submesh.face_count)
        self.assertEqual((0, 1, 3), edge_submesh.faces[-1])

        quad_view = service.open_edit_session(_loose_edge_mesh(), session_id="fill-quad-loop", mode="edit")
        quad_fill = service.apply_command(
            quad_view.session_id,
            MeshEditCommand("fill", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 3), (2, 3), (0, 2))})),
        )
        quad_submesh = service.working_mesh(quad_view.session_id).submeshes[0]

        self.assertTrue(quad_fill.ok)
        self.assertTrue(quad_fill.topology_changed)
        self.assertEqual(2, quad_submesh.face_count)
        self.assertEqual([(0, 1, 3), (0, 3, 2)], quad_submesh.faces)

        face_view = service.open_edit_session(_quad_mesh(), session_id="fill-face-noop", mode="edit")
        face_fill = service.apply_command(
            face_view.session_id,
            MeshEditCommand("fill", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}, source_indices=(0,))),
        )

        face_submesh = service.working_mesh(face_view.session_id).submeshes[0]
        self.assertTrue(face_fill.ok)
        self.assertFalse(face_fill.topology_changed)
        self.assertEqual((), face_fill.affected_submesh_indices)
        self.assertEqual(2, face_submesh.face_count)
        self.assertEqual(0, service.session_view(face_view.session_id).revision)

        existing_view = service.open_edit_session(_quad_mesh(), session_id="fill-existing-noop", mode="edit")
        existing_fill = service.apply_command(
            existing_view.session_id,
            MeshEditCommand("fill", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 2), (0, 2))})),
        )
        existing_quad = service.apply_command(
            existing_view.session_id,
            MeshEditCommand("fill", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)})),
        )
        existing_submesh = service.working_mesh(existing_view.session_id).submeshes[0]
        self.assertTrue(existing_fill.ok)
        self.assertFalse(existing_fill.topology_changed)
        self.assertTrue(existing_quad.ok)
        self.assertFalse(existing_quad.topology_changed)
        self.assertEqual(2, existing_submesh.face_count)
        self.assertEqual(0, service.session_view(existing_view.session_id).revision)

    def test_loop_cut_can_split_selected_edge_with_midpoint(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="loop-cut", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})

        result = service.apply_command(view.session_id, MeshEditCommand("loop_cut", selection=selection))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, (4,)),), result.changed_vertices_by_submesh)
        self.assertEqual(5, len(submesh.vertices))
        self.assertEqual(5, len(submesh.uvs))
        self.assertEqual((0.5, 0.5, 0.0), submesh.vertices[4])
        self.assertEqual((0.5, 0.5), submesh.uvs[4])
        self.assertEqual(4, len(submesh.faces))
        self.assertTrue(all(set(face) & {4} for face in submesh.faces))

    def test_loop_cut_can_create_multiple_cuts_on_selected_edge(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_triangle_mesh(), session_id="loop-cut-multi", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})

        result = service.apply_command(view.session_id, MeshEditCommand("loop_cut", selection=selection, params={"cuts": 2}))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, (3, 4)),), result.changed_vertices_by_submesh)
        self.assertEqual(5, submesh.vertex_count)
        self.assertEqual(3, submesh.face_count)
        self.assertAlmostEqual(1.0 / 3.0, submesh.vertices[3][0], places=6)
        self.assertAlmostEqual(2.0 / 3.0, submesh.vertices[4][0], places=6)
        self.assertEqual((1.0 / 3.0, 0.0), submesh.uvs[3])
        self.assertEqual((2.0 / 3.0, 0.0), submesh.uvs[4])
        self.assertEqual([(0, 3, 2), (3, 4, 2), (4, 1, 2)], submesh.faces)

    def test_loop_cut_can_place_single_cut_at_factor(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_triangle_mesh(), session_id="loop-cut-factor", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})

        result = service.apply_command(view.session_id, MeshEditCommand("loop_cut", selection=selection, params={"factor": 0.25}))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, (3,)),), result.changed_vertices_by_submesh)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual((0.25, 0.0, 0.0), submesh.vertices[3])
        self.assertEqual((0.25, 0.0), submesh.uvs[3])
        self.assertEqual([(0, 3, 2), (3, 1, 2)], submesh.faces)

    def test_loop_cut_two_edges_only_splits_selected_edges(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_triangle_mesh(), session_id="loop-cut-two-edges", mode="edit")
        selection = MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 2))})

        result = service.apply_command(view.session_id, MeshEditCommand("loop_cut", selection=selection))

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual(((0, (3, 4)),), result.changed_vertices_by_submesh)
        self.assertEqual(5, submesh.vertex_count)
        self.assertEqual(3, submesh.face_count)
        self.assertEqual((0.5, 0.0, 0.0), submesh.vertices[3])
        self.assertEqual((0.5, 0.5, 0.0), submesh.vertices[4])
        self.assertEqual([(3, 1, 4), (0, 3, 4), (0, 4, 2)], submesh.faces)

    def test_weld_only_merges_selected_vertices_within_threshold(self) -> None:
        service = MeshService()
        distant_view = service.open_edit_session(_quad_mesh(), session_id="weld-distant", mode="edit")

        distant = service.apply_command(
            distant_view.session_id,
            MeshEditCommand("weld", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})),
        )

        distant_submesh = service.working_mesh(distant_view.session_id).submeshes[0]
        self.assertTrue(distant.ok)
        self.assertFalse(distant.topology_changed)
        self.assertEqual(4, distant_submesh.vertex_count)
        self.assertEqual(2, distant_submesh.face_count)
        self.assertEqual(0, service.session_view(distant_view.session_id).revision)

        duplicate_view = service.open_edit_session(_duplicate_vertex_mesh(), session_id="weld-duplicate", mode="edit")
        welded = service.apply_command(
            duplicate_view.session_id,
            MeshEditCommand("weld", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 4)}), params={"threshold": 0.001}),
        )

        duplicate_submesh = service.working_mesh(duplicate_view.session_id).submeshes[0]
        self.assertTrue(welded.ok)
        self.assertTrue(welded.topology_changed)
        self.assertEqual((0,), welded.affected_submesh_indices)
        self.assertEqual((), welded.changed_vertices_by_submesh)
        self.assertEqual(4, duplicate_submesh.vertex_count)
        self.assertEqual(2, duplicate_submesh.face_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], duplicate_submesh.faces)

    def test_compacting_topology_actions_do_not_emit_stale_vertex_deltas(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_duplicate_vertex_mesh(), session_id="merge-compact", mode="edit")

        result = service.apply_command(
            view.session_id,
            MeshEditCommand("merge", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 4)})),
        )

        submesh = service.working_mesh(view.session_id).submeshes[0]
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertEqual((), result.changed_vertices_by_submesh)
        self.assertEqual(4, submesh.vertex_count)
        self.assertEqual(2, submesh.face_count)
        self.assertEqual([(0, 1, 2), (1, 3, 2)], submesh.faces)

    def test_all_named_v1_actions_return_results(self) -> None:
        actions = (
            "set_mode",
            "select",
            "transform",
            "brush",
            "delete",
            "dissolve",
            "subdivide",
            "split",
            "separate",
            "duplicate",
            "mirror",
            "extrude",
            "inset",
            "loop_cut",
            "edge_split",
            "merge",
            "weld",
            "bridge",
            "fill",
            "recalculate_normals",
            "generate_tangents",
            "flip_normals",
            "sharpen_normals",
            "soften_normals",
            "copy_normals",
            "uv_transform",
            "material_assign",
            "material_copy",
        )
        for action in actions:
            with self.subTest(action=action):
                service = MeshService()
                view = service.open_edit_session(_quad_mesh(two_parts=True), session_id=action, mode="edit")
                selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)}, source_indices=(0,))
                command = MeshEditCommand(action, selection=selection, mode="sculpt" if action == "set_mode" else None)
                if action == "material_copy":
                    command = MeshEditCommand(action, selection=MeshEditSelection.from_maps(source_indices=(1,)), params={"source_submesh_index": 0})
                result = service.apply_command(view.session_id, command)
                self.assertIn(result.status, {"ok", "noop"})

    def test_selection_normalizes_invalid_indices(self) -> None:
        selection = MeshEditSelection.from_maps(
            vertices_by_submesh={0: (2, 2, -1, "bad", True, 1.9, float("inf")), True: (7,), 0.5: (8,)},  # type: ignore[dict-item]
            edges_by_submesh={0: ((3, 1), (1, 3), (4, "bad"), (True, 2), (1.9, 3))},  # type: ignore[list-item]
            faces_by_submesh={1: (5, "bad", True, 1.9, float("nan"))},
            source_indices=(2, -1, "bad", True, 1.9, float("inf")),
        )

        self.assertEqual({0: {2}}, selection.vertex_map())
        self.assertEqual({0: {(1, 3)}}, selection.edge_map())
        self.assertEqual({1: {5}}, selection.face_map())
        self.assertEqual((2,), selection.source_indices)

    def test_selection_normalizes_malformed_payload_shapes(self) -> None:
        selection = MeshEditSelection.from_maps(
            vertices_by_submesh={0: 2, 1: None, 2: ("4", "bad"), "bad": (9,)},  # type: ignore[arg-type]
            edges_by_submesh={0: (3, 1), 1: (None, (4, "bad"), [7, 5], "12", object())},  # type: ignore[arg-type]
            faces_by_submesh={0: 1, 1: ("2", "bad"), "bad": (3,)},  # type: ignore[arg-type]
            source_indices=5,  # type: ignore[arg-type]
        )
        empty = MeshEditSelection.from_maps(
            vertices_by_submesh=42,  # type: ignore[arg-type]
            edges_by_submesh=42,  # type: ignore[arg-type]
            faces_by_submesh=42,  # type: ignore[arg-type]
            source_indices=object(),  # type: ignore[arg-type]
        )

        self.assertEqual({0: {2}, 2: {4}}, selection.vertex_map())
        self.assertEqual({0: {(1, 3)}, 1: {(5, 7)}}, selection.edge_map())
        self.assertEqual({0: {1}, 1: {2}}, selection.face_map())
        self.assertEqual((5,), selection.source_indices)
        self.assertTrue(empty.is_empty())


if __name__ == "__main__":
    unittest.main()
