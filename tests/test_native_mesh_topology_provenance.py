"""Native durability of the topology provenance contract.

These exercise the real ``cdmw-mesh-core`` session: identity at open, composition
before mutation for the three admitted operations, invalidation for everything
else, and byte-identical restoration through undo and redo.
"""

from __future__ import annotations

import unittest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.domain.mesh.topology import TOPOLOGY_PROVENANCE_CAPABILITY, TOPOLOGY_PROVENANCE_VERSION
from cdmw.modding import mesh_native_session_api as native_api
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_service import MeshService


def _grid_mesh(rows: int = 5, columns: int = 5) -> ParsedMesh:
    vertices: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    for row in range(rows):
        for column in range(columns):
            vertices.append((float(column), float(row), 0.0))
            uvs.append((column / max(1, columns - 1), row / max(1, rows - 1)))
    faces: list[tuple[int, int, int]] = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            a = row * columns + column
            b = a + 1
            c = (row + 1) * columns + column
            d = c + 1
            faces.append((a, b, c))
            faces.append((b, d, c))
    submesh = SubMesh(
        name="provenance_grid",
        material="grid_material",
        texture="grid.dds",
        vertices=vertices,
        uvs=uvs,
        normals=[(0.0, 0.0, 1.0)] * len(vertices),
        faces=faces,
        vertex_count=len(vertices),
        face_count=len(faces),
    )
    return ParsedMesh(
        path="provenance.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=len(vertices),
        total_faces=len(faces),
        has_uvs=True,
    )


def _summary(session_id: str) -> dict[str, object]:
    report = native_api.native_mesh_editor_session_command("summary", session_id, {}) or {}
    submeshes = tuple(report.get("submeshes") or ())
    return dict(submeshes[0]) if submeshes else {}


@unittest.skipUnless(native_mesh_core_available(), "native mesh core binary is unavailable")
class NativeTopologyProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MeshService()
        self.session_id = f"topology-provenance-{self._testMethodName}"
        self.view = self.service.open_edit_session(_grid_mesh(), session_id=self.session_id, mode="edit")
        self.addCleanup(self.service.close_edit_session, self.view.session_id)
        # The service opens the native session lazily, on the first command.
        self.service.apply_command(
            self.view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"operation": "replace"},
                mode="edit",
            ),
        )

    def test_open_reports_the_capability_and_identity_origins(self) -> None:
        opened = native_api.open_native_mesh_editor_session(_grid_mesh(), session_id=f"{self.session_id}-open")
        self.assertIsNotNone(opened)
        assert opened is not None
        self.addCleanup(
            native_api.native_mesh_editor_session_command, "close", f"{self.session_id}-open", {}
        )

        self.assertIn(TOPOLOGY_PROVENANCE_CAPABILITY, tuple(opened.get("capabilities") or ()))
        self.assertEqual(TOPOLOGY_PROVENANCE_VERSION, opened.get("topology_contract"))
        submesh = dict(tuple(opened.get("submeshes") or ())[0])
        self.assertTrue(submesh["topology_rebuild_valid"])
        self.assertEqual("", submesh["topology_blocker"])
        self.assertEqual(25, submesh["topology_original_vertex_count"])
        self.assertEqual(32, submesh["topology_original_face_count"])
        self.assertEqual(25, submesh["topology_direct_vertex_count"])
        self.assertEqual(0, submesh["topology_derived_vertex_count"])
        self.assertEqual(25, submesh["topology_provenance_parent_entries"])

    def test_face_delete_keeps_every_survivor_direct(self) -> None:
        result = self.service.apply_command(
            self.view.session_id,
            MeshEditCommand(
                "delete",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"_include_preview_deltas": False},
                mode="edit",
            ),
        )
        self.assertTrue(result.ok)

        summary = _summary(self.session_id)
        self.assertTrue(summary["topology_rebuild_valid"])
        self.assertEqual(25, summary["topology_original_vertex_count"])
        self.assertEqual(32, summary["topology_original_face_count"])
        self.assertEqual(0, summary["topology_derived_vertex_count"])
        self.assertEqual(summary["vertex_count"], summary["topology_direct_vertex_count"])
        self.assertEqual(summary["vertex_count"], summary["topology_provenance_parent_entries"])

    def test_midpoint_subdivide_derives_two_parent_origins(self) -> None:
        result = self.service.apply_command(
            self.view.session_id,
            MeshEditCommand(
                "subdivide",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"max_faces_per_submesh": 4096, "_include_preview_deltas": False},
                mode="edit",
            ),
        )
        self.assertTrue(result.ok)

        summary = _summary(self.session_id)
        self.assertTrue(summary["topology_rebuild_valid"])
        self.assertEqual(25, summary["topology_original_vertex_count"])
        self.assertEqual(32, summary["topology_original_face_count"])
        self.assertEqual(3, summary["topology_derived_vertex_count"])
        self.assertEqual(25, summary["topology_direct_vertex_count"])
        # Three midpoints, each naming two original parents.
        self.assertEqual(25 + 3 * 2, summary["topology_provenance_parent_entries"])

    def test_chained_subdivide_stays_original_relative(self) -> None:
        for _pass in range(2):
            result = self.service.apply_command(
                self.view.session_id,
                MeshEditCommand(
                    "subdivide",
                    selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                    params={"max_faces_per_submesh": 4096, "_include_preview_deltas": False},
                    mode="edit",
                ),
            )
            self.assertTrue(result.ok)

        summary = _summary(self.session_id)
        self.assertTrue(summary["topology_rebuild_valid"])
        # The anchor never moves, however many times the mesh is subdivided.
        self.assertEqual(25, summary["topology_original_vertex_count"])
        self.assertEqual(32, summary["topology_original_face_count"])
        self.assertGreater(summary["topology_derived_vertex_count"], 3)

    def test_an_unsupported_topology_operation_marks_the_submesh_non_rebuildable(self) -> None:
        result = self.service.apply_command(
            self.view.session_id,
            MeshEditCommand(
                "refine_smooth",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"max_faces_per_submesh": 4096, "_include_preview_deltas": False},
                mode="edit",
            ),
        )
        self.assertTrue(result.ok)

        summary = _summary(self.session_id)
        self.assertFalse(summary["topology_rebuild_valid"])
        self.assertEqual("TOPOLOGY_OPERATION_NOT_REBUILDABLE", summary["topology_blocker"])

    def test_undo_and_redo_restore_provenance_exactly(self) -> None:
        before = _summary(self.session_id)
        self.assertTrue(
            self.service.apply_command(
                self.view.session_id,
                MeshEditCommand(
                    "subdivide",
                    selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                    params={"max_faces_per_submesh": 4096, "_include_preview_deltas": False},
                    mode="edit",
                ),
            ).ok
        )
        after = _summary(self.session_id)
        self.assertNotEqual(before["topology_provenance_parent_entries"], after["topology_provenance_parent_entries"])

        self.assertTrue(self.service.undo(self.view.session_id).ok)
        restored = _summary(self.session_id)
        for key in (
            "topology_rebuild_valid",
            "topology_blocker",
            "topology_original_vertex_count",
            "topology_original_face_count",
            "topology_direct_vertex_count",
            "topology_derived_vertex_count",
            "topology_provenance_parent_entries",
        ):
            self.assertEqual(before[key], restored[key], key)

        self.assertTrue(self.service.redo(self.view.session_id).ok)
        redone = _summary(self.session_id)
        for key in (
            "topology_rebuild_valid",
            "topology_blocker",
            "topology_original_vertex_count",
            "topology_original_face_count",
            "topology_direct_vertex_count",
            "topology_derived_vertex_count",
            "topology_provenance_parent_entries",
        ):
            self.assertEqual(after[key], redone[key], key)

    def test_undo_restores_validity_after_an_unsupported_topology_edit(self) -> None:
        before = _summary(self.session_id)
        self.assertTrue(before["topology_rebuild_valid"])
        self.assertTrue(
            self.service.apply_command(
                self.view.session_id,
                MeshEditCommand(
                    "refine_smooth",
                    selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                    params={"max_faces_per_submesh": 4096, "_include_preview_deltas": False},
                    mode="edit",
                ),
            ).ok
        )
        self.assertFalse(_summary(self.session_id)["topology_rebuild_valid"])

        self.assertTrue(self.service.undo(self.view.session_id).ok)
        restored = _summary(self.session_id)

        self.assertTrue(restored["topology_rebuild_valid"])
        self.assertEqual("", restored["topology_blocker"])
        self.assertEqual(
            before["topology_provenance_parent_entries"], restored["topology_provenance_parent_entries"]
        )

    def test_apply_metrics_report_provenance_cost_and_parent_entries(self) -> None:
        result = self.service.apply_command(
            self.view.session_id,
            MeshEditCommand(
                "subdivide",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"max_faces_per_submesh": 4096, "_include_preview_deltas": False},
                mode="edit",
            ),
        )
        self.assertTrue(result.ok)

        metrics = dict(result.metrics or {})
        self.assertIn("topology_provenance_ms", metrics)
        self.assertIn("topology_provenance_parent_entries", metrics)
        self.assertEqual(25 + 3 * 2, int(metrics["topology_provenance_parent_entries"]))
        self.assertGreaterEqual(float(metrics["topology_provenance_ms"]), 0.0)

    def test_history_retained_bytes_include_the_csr_capacity(self) -> None:
        result = self.service.apply_command(
            self.view.session_id,
            MeshEditCommand(
                "subdivide",
                selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                params={"max_faces_per_submesh": 4096, "_include_preview_deltas": False},
                mode="edit",
            ),
        )
        metrics = dict(result.metrics or {})

        self.assertGreater(float(metrics["native_history_retained_bytes"]), 0.0)
        self.assertEqual(268435456.0, float(metrics["native_history_max_bytes"]))
        self.assertEqual(64.0, float(metrics["native_history_max_operations"]))


if __name__ == "__main__":
    unittest.main()
