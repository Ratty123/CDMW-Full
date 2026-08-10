from __future__ import annotations

import unittest

from cdmw.domain.mesh import MeshEditSelection


class MeshEditSelectionNormalizationTests(unittest.TestCase):
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
