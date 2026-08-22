"""Repeated Subdivide reproducers: region containment, cracks, selection growth.

The 2026-08-22 user report: subdividing a selected region repeatedly densified
faces scattered across the whole mesh, wireframes turned "weird" at random
spots, and after a few clicks the editor stalled and failed with a message that
named nothing. Three native defects compounded:

- the session read its own remapped compact face offsets back as ancestor
  source-face ids, so the second Subdivide split every descendant of colliding
  ancestor ids anywhere on the mesh;
- a split face's unselected neighbour kept spanning the whole original edge
  over the new midpoint, leaving T-junction cracks along every region border;
- the post-Subdivide remap selected every generated midpoint, so the split
  region and the visible selection quadrupled with each click, and the
  face-limit rejection tore the healthy session down as lost.

Each test here fails against the pre-fix native core and passes after it.
"""

from __future__ import annotations

import unittest
from collections import defaultdict
from uuid import uuid4

from cdmw.modding import mesh_native_core
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

_GRID = 11  # vertices per side; (_GRID - 1)^2 quads, two triangles each


def _grid_mesh() -> ParsedMesh:
    vertices = [(float(x), float(y), 0.0) for y in range(_GRID) for x in range(_GRID)]
    faces = []
    for y in range(_GRID - 1):
        for x in range(_GRID - 1):
            a = y * _GRID + x
            faces.append((a, a + 1, a + _GRID))
            faces.append((a + 1, a + _GRID + 1, a + _GRID))
    submesh = SubMesh(
        name="grid",
        material="mat",
        texture="t.dds",
        vertices=vertices,
        uvs=[(v[0] / (_GRID - 1), v[1] / (_GRID - 1)) for v in vertices],
        normals=[(0.0, 0.0, 1.0)] * len(vertices),
        faces=faces,
        vertex_count=len(vertices),
        face_count=len(faces),
    )
    return ParsedMesh(
        path="grid.pac",
        format="pac",
        submeshes=[submesh],
        total_vertices=len(vertices),
        total_faces=len(faces),
        has_uvs=True,
    )


def _center_vertex_blob() -> list[int]:
    return sorted(y * _GRID + x for y in range(4, 7) for x in range(4, 7))


def _center_quad_faces() -> list[int]:
    selected = []
    for y in range(4, 6):
        for x in range(4, 6):
            quad = y * (_GRID - 1) + x
            selected.extend((2 * quad, 2 * quad + 1))
    return sorted(selected)


def _subdivided_face_bbox(mesh: ParsedMesh) -> tuple[float, float, float, float] | None:
    """Bounding box of faces smaller than the grid's uniform 0.5 triangle area."""
    submesh = mesh.submeshes[0]
    xs: list[float] = []
    ys: list[float] = []
    for face in submesh.faces:
        (ax, ay, _), (bx, by, _), (cx, cy, _) = (submesh.vertices[index] for index in face)
        if abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2.0 < 0.49:
            xs.extend((ax, bx, cx))
            ys.extend((ay, by, cy))
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _interior_crack_edge_count(mesh: ParsedMesh) -> int:
    """Edges used by exactly one face that do not lie on the grid's outer rim.

    A closed grid interior is two-manifold, so any interior edge with a single
    user is a crack: the far side spans the whole original edge while this side
    stops at a midpoint.
    """
    submesh = mesh.submeshes[0]
    edge_use: dict[tuple[int, int], int] = defaultdict(int)
    for a, b, c in submesh.faces:
        for left, right in ((a, b), (b, c), (c, a)):
            edge_use[(min(left, right), max(left, right))] += 1
    rim = float(_GRID - 1)
    cracks = 0
    for (left, right), count in edge_use.items():
        if count != 1:
            continue
        lx, ly, _ = submesh.vertices[left]
        rx, ry, _ = submesh.vertices[right]
        on_rim = (
            (lx == 0.0 and rx == 0.0)
            or (lx == rim and rx == rim)
            or (ly == 0.0 and ry == 0.0)
            or (ly == rim and ry == rim)
        )
        if not on_rim:
            cracks += 1
    return cracks


class NativeSubdivideRepeatTests(unittest.TestCase):
    def setUp(self) -> None:
        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

    def _open_session(self, mesh: ParsedMesh) -> str:
        session_id = f"subdivide-repeat-{uuid4().hex}"
        self.assertIsNotNone(
            mesh_native_core.open_native_mesh_editor_session(mesh, session_id, timeout_seconds=10.0)
        )
        self.addCleanup(mesh_native_core.close_native_mesh_editor_session, session_id)
        return session_id

    def _subdivide(self, session_id: str) -> dict[str, object]:
        report = mesh_native_core.apply_native_mesh_editor_session(
            session_id,
            {"operation": "subdivide", "max_faces_per_submesh": 200000},
            timeout_seconds=10.0,
        )
        self.assertIsNotNone(report)
        return report

    def test_repeat_face_subdivide_stays_inside_the_selected_region(self) -> None:
        mesh = _grid_mesh()
        session_id = self._open_session(mesh)
        self.assertIsNotNone(
            mesh_native_core.select_native_mesh_editor_session(
                session_id,
                {"faces_by_submesh": {0: _center_quad_faces()}},
                timeout_seconds=10.0,
            )
        )
        self._subdivide(session_id)
        self._subdivide(session_id)
        self.assertTrue(mesh_native_core.export_native_mesh_editor_session_to_mesh(mesh, session_id))
        bbox = _subdivided_face_bbox(mesh)
        self.assertIsNotNone(bbox)
        # The selected 2x2 quad block spans (4, 4)-(6, 6); stitching the
        # unselected neighbours may extend density one quad further. Before the
        # fix the second click read its remapped offsets as ancestor ids and
        # smeared splits across the grid's whole width.
        min_x, min_y, max_x, max_y = bbox
        self.assertGreaterEqual(min_x, 3.0)
        self.assertGreaterEqual(min_y, 3.0)
        self.assertLessEqual(max_x, 7.0)
        self.assertLessEqual(max_y, 7.0)

    def test_subdivide_leaves_no_interior_cracks(self) -> None:
        mesh = _grid_mesh()
        session_id = self._open_session(mesh)
        self.assertIsNotNone(
            mesh_native_core.select_native_mesh_editor_session(
                session_id,
                {"vertices_by_submesh": {0: _center_vertex_blob()}},
                timeout_seconds=10.0,
            )
        )
        self._subdivide(session_id)
        self._subdivide(session_id)
        self.assertTrue(mesh_native_core.export_native_mesh_editor_session_to_mesh(mesh, session_id))
        self.assertEqual(0, _interior_crack_edge_count(mesh))

    def test_subdivide_selects_only_midpoints_of_fully_selected_edges(self) -> None:
        mesh = _grid_mesh()
        session_id = self._open_session(mesh)
        blob = _center_vertex_blob()
        self.assertIsNotNone(
            mesh_native_core.select_native_mesh_editor_session(
                session_id,
                {"vertices_by_submesh": {0: blob}},
                timeout_seconds=10.0,
            )
        )
        report = self._subdivide(session_id)
        selection = mesh_native_core.native_mesh_editor_session_selection_from_report(report)
        self.assertIsNotNone(selection)
        selected = selection["vertices_by_submesh"][0]
        # The 3x3 blob keeps its 9 vertices and adopts the 16 midpoints of the
        # edges between them, and nothing else: the blob spans (4, 4)-(6, 6),
        # so every selected vertex stays inside it. Before the fix every
        # generated midpoint joined the selection, dragging in the bled
        # boundary ring and quadrupling the region on the next click.
        self.assertEqual(25, len(selected))
        self.assertTrue(mesh_native_core.export_native_mesh_editor_session_to_mesh(mesh, session_id))
        for vertex_index in selected:
            x, y, _ = mesh.submeshes[0].vertices[vertex_index]
            self.assertGreaterEqual(x, 4.0)
            self.assertGreaterEqual(y, 4.0)
            self.assertLessEqual(x, 6.0)
            self.assertLessEqual(y, 6.0)

    def test_face_limit_rejection_names_the_reason_and_keeps_the_session(self) -> None:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
        from cdmw.services.mesh_service import MeshService

        service = MeshService()
        view = service.open_edit_session(_grid_mesh(), session_id="subdivide-cap-rejection", mode="edit")
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: tuple(_center_vertex_blob())})

        first = service.apply_command(
            view.session_id,
            MeshEditCommand("subdivide", selection=selection, mode="edit"),
        )
        self.assertTrue(first.ok)
        faces_after_first = service.session_view(view.session_id).face_count

        with self.assertRaisesRegex(RuntimeError, "per-submesh face limit"):
            service.apply_command(
                view.session_id,
                MeshEditCommand(
                    "subdivide",
                    selection=selection,
                    params={"max_faces_per_submesh": faces_after_first},
                    mode="edit",
                ),
            )

        # The native core refused by policy and threw before its first
        # mutation, so the resident session is intact: no lost-session
        # recovery runs, and the next Subdivide continues from the first
        # click's geometry instead of a rolled-back mesh.
        session = service._session(view.session_id)
        self.assertEqual(0, session.native_editor_lost_recoveries)
        third = service.apply_command(
            view.session_id,
            MeshEditCommand("subdivide", selection=selection, mode="edit"),
        )
        self.assertTrue(third.ok)
        self.assertGreater(service.session_view(view.session_id).face_count, faces_after_first)
        service.close_edit_session(view.session_id)


if __name__ == "__main__":
    unittest.main()
