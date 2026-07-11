from __future__ import annotations

from tests.mesh_harness_support import (
    unittest,
    MeshEditSelection,
    _f64_descriptor_values,
    _i32_descriptor_values,
    build_synthetic_mesh,
    clear_native_mesh_core_fallback_counts,
    mesh_edit_material_override_groups,
    mesh_edit_selection_groups,
    mesh_edit_triangle_groups,
    mesh_edit_vertex_update_groups,
    mesh_to_native_preview,
    native_mesh_core_fallback_counts,
    native_mesh_core_fallback_events,
    patch,
)

class MeshHarnessPreviewFallbackTests(unittest.TestCase):
    def test_large_standalone_initial_preview_python_fallback_blocks_when_native_available(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].vertices = [(0.0, 0.0, 0.0)] * 10_001
        mesh.submeshes[0].normals = [(0.0, 0.0, 1.0)] * 10_001
        mesh.submeshes[0].uvs = [(0.0, 0.0)] * 10_001
        mesh.submeshes[0].faces = [(0, 1, 2)]
        mesh.submeshes[0].vertex_count = 10_001
        mesh.submeshes[0].face_count = 1
        mesh.total_vertices = 10_001
        mesh.total_faces = 1

        clear_native_mesh_core_fallback_counts()
        try:
            with (
                patch("cdmw.services.mesh_workflow_service.native_mesh_core_available", return_value=True),
                patch("cdmw.services.mesh_workflow_service.find_native_mesh_core_binary", return_value=None),
            ):
                with self.assertRaisesRegex(RuntimeError, "native Mesh Editor preview geometry unavailable"):
                    mesh_to_native_preview(mesh)

            self.assertEqual({"preview_geometry.blocked": 1}, native_mesh_core_fallback_counts())
            self.assertEqual(
                "Python preview fallback blocked while native mesh core is available",
                native_mesh_core_fallback_events()[0]["reason"],
            )
        finally:
            clear_native_mesh_core_fallback_counts()

    def test_selection_overlay_groups_use_native_helper_when_available(self) -> None:
        mesh = build_synthetic_mesh()
        calls: list[dict[str, object]] = []

        def _fake_native_selection_groups(mesh_arg: object, **kwargs: object) -> list[dict[str, object]]:
            calls.append(dict(kwargs))
            return [
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_indices": [0, 1, 2],
                    "source_face_indices": [0],
                }
            ]

        with patch("cdmw.services.mesh_workflow_service.build_native_mesh_selection_groups", side_effect=_fake_native_selection_groups):
            groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}))

        self.assertEqual("cdmw_mesh_core", groups[0]["preview_backend"])
        self.assertEqual({0: {0}}, calls[0]["faces_by_submesh"])
        self.assertEqual({}, calls[0]["vertices_by_submesh"])

    def test_selection_overlay_python_fallback_uses_compact_ranges(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.services.mesh_workflow_service.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_selection_groups_native", return_value=None),
        ):
            whole_groups = mesh_edit_selection_groups(
                mesh,
                MeshEditSelection(source_indices=(0,)),
                allow_python_fallback=True,
            )
            face_groups = mesh_edit_selection_groups(
                mesh,
                MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
                allow_python_fallback=True,
            )

        self.assertEqual(0, whole_groups[0]["source_vertex_start"])
        self.assertEqual(4, whole_groups[0]["source_vertex_count"])
        self.assertNotIn("source_vertex_indices", whole_groups[0])
        self.assertEqual(0, face_groups[0]["source_vertex_start"])
        self.assertEqual(3, face_groups[0]["source_vertex_count"])
        self.assertEqual(0, face_groups[0]["source_face_start"])
        self.assertEqual(1, face_groups[0]["source_face_count"])
        self.assertNotIn("source_vertex_indices", face_groups[0])
        self.assertNotIn("source_face_indices", face_groups[0])

    def test_selection_overlay_python_fallback_is_legacy_opt_in(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.services.mesh_workflow_service.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_selection_groups_native", return_value=None),
        ):
            groups = mesh_edit_selection_groups(mesh, MeshEditSelection(source_indices=(0,)))

        self.assertEqual([], groups)

    def test_large_standalone_preview_python_fallback_blocks_when_native_available(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].vertices = [(0.0, 0.0, 0.0)] * 10_001
        mesh.submeshes[0].normals = [(0.0, 0.0, 1.0)] * 10_001
        mesh.submeshes[0].uvs = [(0.0, 0.0)] * 10_001
        mesh.submeshes[0].faces = [(0, 1, 2)]
        mesh.submeshes[0].vertex_count = 10_001
        mesh.submeshes[0].face_count = 1
        mesh.total_vertices = 10_001
        mesh.total_faces = 1

        clear_native_mesh_core_fallback_counts()
        try:
            with (
                patch("cdmw.services.mesh_workflow_service.native_mesh_core_available", return_value=True),
                patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_triangle_groups_native", return_value={}),
                patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_vertex_update_groups_native", return_value={}),
                patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_selection_groups_native", return_value=None),
            ):
                triangle_groups = mesh_edit_triangle_groups(mesh)
                vertex_groups = mesh_edit_vertex_update_groups(mesh, {0: range(0, 10_001)})
                selection_groups = mesh_edit_selection_groups(mesh, MeshEditSelection(source_indices=(0,)))

            self.assertEqual([], triangle_groups)
            self.assertEqual([], vertex_groups)
            self.assertEqual([], selection_groups)
            self.assertEqual(
                {
                    "preview_triangle_group.blocked": 1,
                    "preview_vertex_update.blocked": 1,
                    "selection_overlay.blocked": 1,
                },
                native_mesh_core_fallback_counts(),
            )
        finally:
            clear_native_mesh_core_fallback_counts()

    def test_large_selection_overlay_blocks_before_python_work_estimate(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].vertices = [(0.0, 0.0, 0.0)] * 10_001
        mesh.submeshes[0].normals = [(0.0, 0.0, 1.0)] * 10_001
        mesh.submeshes[0].uvs = [(0.0, 0.0)] * 10_001
        mesh.submeshes[0].vertex_count = 10_001
        mesh.total_vertices = 10_001

        clear_native_mesh_core_fallback_counts()
        try:
            with (
                patch("cdmw.services.mesh_workflow_service.native_mesh_core_available", return_value=True),
                patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_selection_groups_native", return_value=None),
                patch(
                    "cdmw.ui.mesh_editor.native_preview_payloads._selection_preview_fallback_work",
                    side_effect=AssertionError("selection fallback work should be blocked first"),
                ),
            ):
                groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(vertices_by_submesh={0: range(10_001)}))

            self.assertEqual([], groups)
            self.assertEqual({"selection_overlay.blocked": 1}, native_mesh_core_fallback_counts())
        finally:
            clear_native_mesh_core_fallback_counts()

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
        prepared_identity = {
            "source_vertex_indices": list(prepared.batches[0].source_vertex_indices),
            "source_vertex_indices_binary": prepared.batches[0].source_vertex_indices_binary,
            "source_vertex_start": prepared.batches[0].source_vertex_range_start,
            "source_vertex_count": prepared.batches[0].source_vertex_range_count,
            "source_face_indices": list(prepared.batches[0].source_face_indices),
            "source_face_indices_binary": prepared.batches[0].source_face_indices_binary,
            "source_face_start": prepared.batches[0].source_face_range_start,
            "source_face_count": prepared.batches[0].source_face_range_count,
        }
        self.assertEqual([0, 1, 2], _i32_descriptor_values(prepared_identity, "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([1], _i32_descriptor_values(prepared_identity, "source_face_indices", "source_face_indices_binary"))
        self.assertEqual([1], _i32_descriptor_values(triangle_groups[0], "source_face_indices", "source_face_indices_binary"))
        self.assertEqual([0, 1, 2], _i32_descriptor_values(triangle_groups[0], "indices", "indices_binary"))
        self.assertEqual([0, 1, 2], _i32_descriptor_values(selection_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([1], _i32_descriptor_values(selection_groups[0], "source_face_indices", "source_face_indices_binary"))

    def test_vertex_update_consumes_native_group_before_scanning_changed_ids(self) -> None:
        class CountOnlyIndices:
            def __len__(self) -> int:
                return 2

            def __iter__(self):  # type: ignore[no-untyped-def]
                raise AssertionError("python changed-id scan")

        mesh = build_synthetic_mesh()
        mesh.submeshes[0].cdmw_native_preview_vertex_update_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [0, 2],
            "positions": [0.0, 0.0, 0.0, 1.0, 1.0, 0.0],
            "normals": [0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
            "uvs": [0.0, 0.0, 1.0, 1.0],
        }

        with patch(
            "cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_vertex_update_groups_native",
            side_effect=AssertionError("native generator fallback"),
        ):
            groups = mesh_edit_vertex_update_groups(mesh, {0: CountOnlyIndices()})  # type: ignore[dict-item]

        self.assertEqual([0, 2], groups[0]["source_vertex_indices"])
        self.assertEqual([0.0, 0.0, 0.0, 1.0, 1.0, 0.0], groups[0]["positions"])

    def test_vertex_update_descriptor_reaches_native_generator_before_python_scan(self) -> None:
        mesh = build_synthetic_mesh()
        descriptor_input = {
            "changed_vertices_binary": {"path": "changed.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True}
        }
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices_binary": {"path": "changed.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
            "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 2, "components": 2, "type": "f64", "delete_after": True},
        }

        def native_groups(_mesh: object, changed_vertices_by_submesh: object) -> dict[int, dict[str, object]]:
            self.assertEqual({0: descriptor_input}, changed_vertices_by_submesh)
            return {0: native_group}

        with (
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_vertex_update_groups_native", side_effect=native_groups),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._source_vertex_indices", side_effect=AssertionError("python id scan")),
        ):
            groups = mesh_edit_vertex_update_groups(mesh, {0: descriptor_input})

        self.assertEqual([native_group], groups)

    def test_vertex_update_native_generator_retries_after_session_invalidation(self) -> None:
        from cdmw.ui.mesh_editor import native_preview_payloads

        mesh = build_synthetic_mesh()
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 0,
            "source_vertex_count": 4,
            "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
        }
        calls: list[dict[int, object]] = []
        invalidated: list[int] = []

        def native_groups(_mesh: object, changed_vertices_by_submesh: object) -> list[dict[str, object]]:
            calls.append(dict(changed_vertices_by_submesh))  # type: ignore[arg-type]
            return [] if len(calls) == 1 else [native_group]

        def invalidate(_mesh: object, submesh_indices: object) -> None:
            invalidated.extend(int(index) for index in submesh_indices)  # type: ignore[arg-type]

        with (
            patch("cdmw.services.mesh_workflow_service.build_native_mesh_preview_vertex_update_groups", side_effect=native_groups),
            patch("cdmw.services.mesh_workflow_service.invalidate_native_mesh_session_submeshes", side_effect=invalidate),
        ):
            groups = native_preview_payloads._mesh_edit_vertex_update_groups_native(mesh, {0: range(0, 4)})

        self.assertEqual([{0: range(0, 4)}, {0: range(0, 4)}], calls)
        self.assertEqual([0], invalidated)
        self.assertEqual(native_group, groups[0])

    def test_vertex_update_native_generator_sends_sanitized_request(self) -> None:
        from cdmw.ui.mesh_editor import native_preview_payloads

        mesh = build_synthetic_mesh()
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 0,
            "source_vertex_count": 4,
            "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64"},
        }
        calls: list[dict[int, object]] = []

        def native_groups(_mesh: object, changed_vertices_by_submesh: object) -> list[dict[str, object]]:
            calls.append(dict(changed_vertices_by_submesh))  # type: ignore[arg-type]
            return [native_group]

        with patch("cdmw.services.mesh_workflow_service.build_native_mesh_preview_vertex_update_groups", side_effect=native_groups):
            groups = native_preview_payloads._mesh_edit_vertex_update_groups_native(
                mesh,
                {0: range(0, 4), -1: range(0, 1), 999: range(0, 1), "bad": range(0, 1)},  # type: ignore[dict-item]
            )

        self.assertEqual([{0: range(0, 4)}], calls)
        self.assertEqual(native_group, groups[0])

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

        with self.assertRaisesRegex(RuntimeError, "native Mesh Editor preview geometry unavailable"):
            mesh_to_native_preview(mesh)
        with patch("cdmw.services.mesh_workflow_service.native_mesh_core_available", return_value=False):
            triangle_groups = mesh_edit_triangle_groups(
                mesh,
                source_submesh_indices=(True, 0.5, 0, float("inf")),  # type: ignore[arg-type]
                allow_python_fallback=True,
            )
            vertex_groups = mesh_edit_vertex_update_groups(
                mesh,
                {0: (True, 1.0, 1.9, float("inf"), "bad"), float("inf"): (0,)},  # type: ignore[dict-item]
                allow_python_fallback=True,
            )
        material_groups = mesh_edit_material_override_groups(mesh, (0,))
        reset_material_groups = mesh_edit_material_override_groups(mesh, (0,), include_defaults=True)

        self.assertEqual([0.0, 5.0, 0.0], _f64_descriptor_values(triangle_groups[0], "positions", "positions_binary")[3:6])
        self.assertEqual([0.0, 0.5, 0.0], _f64_descriptor_values(triangle_groups[0], "normals", "normals_binary")[3:6])
        self.assertEqual([0.0, 0.0], _f64_descriptor_values(triangle_groups[0], "uvs", "uvs_binary")[2:4])
        self.assertEqual([1], _i32_descriptor_values(vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([0.0, 5.0, 0.0], _f64_descriptor_values(vertex_groups[0], "positions", "positions_binary"))
        self.assertEqual([0.0, 0.5, 0.0], _f64_descriptor_values(vertex_groups[0], "normals", "normals_binary"))
        self.assertEqual([0.0, 0.0], _f64_descriptor_values(vertex_groups[0], "uvs", "uvs_binary"))
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
