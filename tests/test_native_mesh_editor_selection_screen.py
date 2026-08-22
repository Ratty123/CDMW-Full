"""Native screen-selection behavior added with the brush responsiveness pass.

Covers the selection semantics the Mesh Editor brush now relies on:

- ``screen_region`` mode ``brush`` (a pointer polyline plus radius) selecting
  edges along the actual swept path, which the .NET viewport emits for fast or
  curved strokes instead of a straight chord quad.
- Edges with an endpoint outside the projectable depth window still selecting
  by their visible span instead of being rejected whole.
- Visible-mode depth acceptance sampling along an edge's in-region span, so a
  single occluded sample point cannot hide a mostly visible wire.
- Coalesced ``screen_brushes`` arrays selecting the union of their dabs while
  sharing one occlusion mask.
"""

import unittest
from uuid import uuid4

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _screen_wvp() -> list[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 0.5, 0.0,
        0.0, 0.0, 0.5, 1.0,
    ]


def _mesh_from_submeshes(submeshes: list[SubMesh], path: str) -> ParsedMesh:
    return ParsedMesh(
        path=path,
        format="pac",
        submeshes=submeshes,
        total_vertices=sum(len(submesh.vertices) for submesh in submeshes),
        total_faces=sum(len(submesh.faces) for submesh in submeshes),
        has_uvs=True,
    )


def _submesh(name: str, vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]) -> SubMesh:
    return SubMesh(
        name=name,
        material=f"{name}_mat",
        texture=f"{name}.dds",
        vertices=vertices,
        uvs=[(0.0, 0.0)] * len(vertices),
        normals=[(0.0, 0.0, 1.0)] * len(vertices),
        faces=faces,
        vertex_count=len(vertices),
        face_count=len(faces),
    )


def _quad_mesh() -> ParsedMesh:
    return _mesh_from_submeshes(
        [
            _submesh(
                "quad",
                [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
                [(0, 1, 2), (1, 3, 2)],
            )
        ],
        "quad.pac",
    )


class NativeScreenSelectionBehaviorTests(unittest.TestCase):
    def _require_native(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

    def _select(self, service, session_id: str, payload: dict[str, object]):
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection

        return service.apply_command(
            session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection(),
                params={
                    "operation": "replace",
                    "_native_screen_selection_payload": payload,
                },
            ),
        )

    def test_brush_path_region_selects_edges_along_the_swept_polyline(self) -> None:
        """The band around an L-shaped pointer path selects both legs' edges.

        The .NET viewport emits this payload for fast or curved strokes; a
        chord between the path's endpoints would miss both legs entirely.
        """

        self._require_native()
        from cdmw.services.mesh_service import MeshService

        service = MeshService()
        view = service.open_edit_session(
            _quad_mesh(), session_id=f"native-brush-path-edges-{uuid4().hex}", mode="edit"
        )
        try:
            result = self._select(
                service,
                view.session_id,
                {
                    "target_mode": "edge",
                    "selection_depth_mode": "xray",
                    "screen_region": {
                        "mode": "brush",
                        "selection_mode": "brush",
                        "points": [[100.0, 100.0], [200.0, 100.0], [200.0, 0.0]],
                        "radius_pixels": 6.0,
                        "start_x": 100.0,
                        "start_y": 100.0,
                        "end_x": 200.0,
                        "end_y": 0.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": _screen_wvp(),
                    },
                },
            )
            selected = service.session_view(view.session_id).selection.edge_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok, result.diagnostics)
        # First leg runs along the bottom edge (0, 1); second along the right
        # edge (1, 3). Edges merely touching the path's corners may join them;
        # the two legs themselves must be present.
        self.assertIn(0, selected)
        self.assertLessEqual({(0, 1), (1, 3)}, selected[0])

    def test_edge_with_endpoint_outside_depth_window_selects_by_visible_span(self) -> None:
        """One endpoint past the projectable z range no longer rejects the edge.

        A region payload on purpose: region edge selection has no world-space
        ray fallback, so before the clipped projection the failing endpoint
        rejected the whole edge no matter how much of it crossed the region.
        """

        self._require_native()
        from cdmw.services.mesh_service import MeshService

        # Vertex 2 sits at world z 3.0: ndc z = 2.0, outside [0, 1], so its
        # projection fails and only the clipped visible span can match. The
        # rectangle covers screen (190..210, 70..90), a stretch of the edge's
        # visible span only.
        mesh = _mesh_from_submeshes(
            [
                _submesh(
                    "spike",
                    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 3.0)],
                    [(0, 1, 2)],
                )
            ],
            "spike.pac",
        )
        service = MeshService()
        view = service.open_edit_session(
            mesh, session_id=f"native-clipped-edge-{uuid4().hex}", mode="edit"
        )
        try:
            result = self._select(
                service,
                view.session_id,
                {
                    "target_mode": "edge",
                    "selection_depth_mode": "xray",
                    "screen_region": {
                        "mode": "rectangle",
                        "start_x": 190.0,
                        "start_y": 70.0,
                        "end_x": 210.0,
                        "end_y": 90.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": _screen_wvp(),
                    },
                },
            )
            selected = service.session_view(view.session_id).selection.edge_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok, result.diagnostics)
        self.assertIn(0, selected)
        self.assertIn((1, 2), selected[0])

    def test_visible_edge_survives_one_occluded_region_sample(self) -> None:
        """Depth acceptance walks the in-region span, not one boundary point.

        The occluder hides exactly the point where the edge crosses the region
        boundary -- the single sample the old test used -- while most of the
        edge's in-region span stays visible.
        """

        self._require_native()
        from cdmw.services.mesh_service import MeshService

        mesh = _mesh_from_submeshes(
            [
                _submesh(
                    "quad",
                    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
                    [(0, 1, 2), (1, 3, 2)],
                ),
                # A small nearer triangle covering screen (140, 100), where the
                # quad's bottom edge crosses the region's left boundary.
                _submesh(
                    "occluder",
                    [(0.35, -0.1, -0.5), (0.45, -0.1, -0.5), (0.4, 0.1, -0.5)],
                    [(0, 1, 2)],
                ),
            ],
            "occluded.pac",
        )
        service = MeshService()
        view = service.open_edit_session(
            mesh, session_id=f"native-edge-depth-span-{uuid4().hex}", mode="edit"
        )
        try:
            result = self._select(
                service,
                view.session_id,
                {
                    "target_mode": "edge",
                    "selection_depth_mode": "visible",
                    "screen_region": {
                        "mode": "rectangle",
                        "start_x": 140.0,
                        "start_y": 90.0,
                        "end_x": 260.0,
                        "end_y": 110.0,
                        "viewport_width": 200.0,
                        "viewport_height": 200.0,
                        "world_view_projection": _screen_wvp(),
                    },
                },
            )
            selected = service.session_view(view.session_id).selection.edge_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok, result.diagnostics)
        self.assertIn(0, selected)
        self.assertIn((0, 1), selected[0])

    def test_coalesced_screen_brushes_select_the_union_of_their_dabs(self) -> None:
        """A merged dab array in visible mode selects what each dab would."""

        self._require_native()
        from cdmw.services.mesh_service import MeshService

        def dab(x: float, y: float) -> dict[str, object]:
            return {
                "x": x,
                "y": y,
                "radius_pixels": 2.0,
                "viewport_width": 200.0,
                "viewport_height": 200.0,
                "world_view_projection": _screen_wvp(),
            }

        # Vertices at screen x 100 and 150: both interior, because the depth
        # mask's clamped right boundary has always excluded a point sitting
        # exactly on the viewport edge, which is not what this test is about.
        mesh = _mesh_from_submeshes(
            [
                _submesh(
                    "half_quad",
                    [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0), (0.5, 0.5, 0.0)],
                    [(0, 1, 2), (1, 3, 2)],
                )
            ],
            "half_quad.pac",
        )
        service = MeshService()
        view = service.open_edit_session(
            mesh, session_id=f"native-coalesced-dabs-{uuid4().hex}", mode="edit"
        )
        try:
            result = self._select(
                service,
                view.session_id,
                {
                    "target_mode": "vertex",
                    "selection_depth_mode": "visible",
                    "screen_brushes": [dab(100.0, 100.0), dab(150.0, 100.0)],
                },
            )
            selected = service.session_view(view.session_id).selection.vertex_map()
        finally:
            service.close_edit_session(view.session_id)

        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual({0: {0, 1}}, selected)


if __name__ == "__main__":
    unittest.main()
