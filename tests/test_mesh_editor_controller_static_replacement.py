from __future__ import annotations

import unittest

from cdmw.ui.mesh_editor.static_replacement_adapter import (
    StaticReplacementMeshEditSession,
    apply_static_replacement_edit,
)
from tools.mesh_editor_dev_harness import build_synthetic_mesh


class StaticReplacementMeshEditorControllerTests(unittest.TestCase):
    def test_static_replacement_session_switches_brush_and_edit_modes(self) -> None:
        session = StaticReplacementMeshEditSession(session_id="static-mode-switch")
        session.open(build_synthetic_mesh())
        try:
            brushed = session.apply(
                "brush",
                faces_by_submesh={0: (0,)},
                tool="inflate",
                center=(0.0, 0.0, 0.0),
                radius=2.0,
                strength=1.0,
                amount=0.1,
                falloff="smooth",
            )
            deleted = session.apply("delete", faces_by_submesh={0: (1,)})

            self.assertTrue(brushed.changed_vertices_by_submesh)
            self.assertEqual(1, deleted.removed_face_count)
            self.assertEqual("edit", session.controller.session_view().mode)
            self.assertEqual("delete", deleted.edit_result.action)
            self.assertNotEqual("noop", deleted.edit_result.status)
            self.assertEqual(((3, 1),), deleted.edit_result.submesh_counts)
        finally:
            session.close()

    def test_static_replacement_adapter_keeps_subdivide_status_fields(self) -> None:
        result = apply_static_replacement_edit(
            build_synthetic_mesh(),
            "subdivide",
            vertices_by_submesh={0: (0,)},
            max_faces_per_submesh=512,
        )

        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertGreater(result.added_face_count, 0)
        self.assertIn(0, result.changed_vertices_by_submesh or {})

    def test_static_replacement_adapter_keeps_refine_smooth_status_fields(self) -> None:
        result = apply_static_replacement_edit(
            build_synthetic_mesh(),
            "refine_smooth",
            vertices_by_submesh={0: (0,)},
            max_faces_per_submesh=512,
            smooth_iterations=2,
            smooth_strength=0.5,
        )

        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertGreater(result.added_face_count, 0)
        self.assertIn(0, result.changed_vertices_by_submesh or {})

    def test_static_replacement_adapter_keeps_split_status_fields(self) -> None:
        result = apply_static_replacement_edit(build_synthetic_mesh(), "split", faces_by_submesh={0: (0,)})

        self.assertEqual("separate", result.edit_result.action)
        self.assertEqual(0, result.source_submesh_index)
        self.assertEqual(1, result.new_submesh_index)
        self.assertEqual(1, result.moved_face_count)
        self.assertGreater(result.moved_vertex_count, 0)
        self.assertEqual(2, len(result.edit_result.submesh_counts))

    def test_static_replacement_adapter_material_assign_selected_faces_reports_created_part(self) -> None:
        result = apply_static_replacement_edit(
            build_synthetic_mesh(),
            "material_assign",
            faces_by_submesh={0: (0,)},
            material="face_material",
            texture="face.dds",
            material_authority_profile="material_authority_detail_mask",
        )

        self.assertEqual("material_assign", result.edit_result.action)
        self.assertTrue(result.edit_result.topology_changed)
        self.assertEqual(0, result.source_submesh_index)
        self.assertEqual(1, result.new_submesh_index)
        self.assertEqual(1, result.moved_face_count)
        self.assertEqual(2, len(result.edit_result.submesh_counts))
        self.assertFalse(result.native_update.replace_all_triangles)
        self.assertEqual((0, 1), result.native_update.triangle_source_submesh_indices)
        self.assertEqual({0, 1}, {group["source_submesh_index"] for group in result.native_update.triangle_groups})
        self.assertIn("face_material", {group.get("material_name") for group in result.native_update.triangle_groups})

    def test_static_replacement_adapter_session_exposes_service_history(self) -> None:
        original = build_synthetic_mesh()
        session = StaticReplacementMeshEditSession(session_id="static-history")
        session.open(original)
        try:
            deleted = session.apply("delete", faces_by_submesh={0: (0,)})
            self.assertEqual(((3, 1),), deleted.edit_result.submesh_counts)
            self.assertEqual(1, session.view().undo_count)
            self.assertEqual(0, session.view().redo_count)

            undone = session.undo()
            self.assertEqual("undo", undone.edit_result.action)
            self.assertEqual(((4, 2),), undone.edit_result.submesh_counts)
            self.assertEqual([0], [group["source_submesh_index"] for group in undone.native_update.triangle_groups])
            self.assertEqual(0, session.view().undo_count)
            self.assertEqual(1, session.view().redo_count)

            redone = session.redo()
            self.assertEqual("redo", redone.edit_result.action)
            self.assertEqual(((3, 1),), redone.edit_result.submesh_counts)
            self.assertEqual([0], [group["source_submesh_index"] for group in redone.native_update.triangle_groups])
            self.assertEqual(1, session.view().undo_count)
        finally:
            session.close()
        self.assertEqual(2, len(original.submeshes[0].faces))


if __name__ == "__main__":
    unittest.main()
