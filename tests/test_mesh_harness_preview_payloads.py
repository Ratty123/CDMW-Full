from __future__ import annotations

from tests.mesh_harness_support import (
    unittest,
    MeshEditSelection,
    Path,
    _edge_descriptor_values,
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
    struct,
)

class MeshHarnessPreviewPayloadTests(unittest.TestCase):
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
        self.assertEqual([0, 1, 2, 1, 3, 2], _i32_descriptor_values(prepared_identity, "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([0, 1], _i32_descriptor_values(prepared_identity, "source_face_indices", "source_face_indices_binary"))
        self.assertEqual([0], [group["source_submesh_index"] for group in triangle_groups])
        self.assertEqual("harness_material", triangle_groups[0]["material_name"])
        self.assertEqual([0], material_groups[0]["source_submesh_indices"])
        self.assertEqual(0.4, material_groups[0]["roughness"])
        self.assertEqual(str(mesh_to_reset.submeshes[0].material), reset_material_groups[0]["material_name"])
        self.assertEqual(0.0, reset_material_groups[0]["roughness"])
        self.assertEqual(0.0, reset_material_groups[0]["metalness"])
        self.assertEqual(1.0, reset_material_groups[0]["texture_brightness"])
        self.assertEqual([0, 1, 2, 3], _i32_descriptor_values(triangle_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual(8, len(_f64_descriptor_values(triangle_groups[0], "uvs", "uvs_binary")))
        self.assertEqual([0, 2], _i32_descriptor_values(vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual(6, len(_f64_descriptor_values(vertex_groups[0], "positions", "positions_binary")))
        self.assertEqual([0.0, 1.0, 0.0, 0.0], _f64_descriptor_values(vertex_groups[0], "uvs", "uvs_binary"))
        self.assertEqual([0, 1, 2], _i32_descriptor_values(selection_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([0], _i32_descriptor_values(selection_groups[0], "source_face_indices", "source_face_indices_binary"))
        self.assertEqual(1, len(_i32_descriptor_values(selection_groups[0], "source_face_indices", "source_face_indices_binary")))
        edge_selection_groups = mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)}))
        self.assertEqual([[1, 2]], _edge_descriptor_values(edge_selection_groups[0]))
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
        self.assertEqual([[0, 3]], _edge_descriptor_values(loose_edge_selection_groups[0]))
        self.assertEqual([0, 3], _i32_descriptor_values(loose_edge_selection_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))

    def test_live_material_payload_preserves_scalar_emissive_and_rejects_invalid_color_authority(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].preview_native_material_overrides = {
            "emissive_scalar_mask": True,
            "emissive_color": ["invalid", 0.4, 0.6],
            "emissive_color_authoritative": True,
        }

        incremental = mesh_edit_material_override_groups(mesh, (0,))
        refresh = mesh_edit_material_override_groups(mesh, (0,), include_defaults=True)

        self.assertEqual(1, len(incremental))
        self.assertNotIn("emissive_color", incremental[0])
        self.assertFalse(incremental[0]["emissive_color_authoritative"])
        self.assertTrue(incremental[0]["emissive_scalar_mask"])
        self.assertEqual([0.35, 0.68, 1.0], refresh[0]["emissive_color"])
        self.assertFalse(refresh[0]["emissive_color_authoritative"])
        self.assertTrue(refresh[0]["emissive_scalar_mask"])

        mesh.submeshes[0].preview_native_material_overrides = {
            "emissive_color": ["invalid", 0.4, 0.6],
        }
        self.assertEqual([], mesh_edit_material_override_groups(mesh, (0,)))
        implicit_refresh = mesh_edit_material_override_groups(mesh, (0,), include_defaults=True)
        self.assertEqual([0.35, 0.68, 1.0], implicit_refresh[0]["emissive_color"])
        self.assertFalse(implicit_refresh[0]["emissive_color_authoritative"])

        mesh.submeshes[0].preview_native_material_overrides = {
            "emissive_color": [0.2, 0.4, 0.6],
        }
        valid = mesh_edit_material_override_groups(mesh, (0,))
        self.assertEqual([0.2, 0.4, 0.6], valid[0]["emissive_color"])
        self.assertTrue(valid[0]["emissive_color_authoritative"])

    def test_live_vertex_update_groups_forward_native_binary_descriptors(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].cdmw_native_preview_vertex_update_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices_binary": {"path": "ids.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
            "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 2, "components": 2, "type": "f64", "delete_after": True},
        }

        groups = mesh_edit_vertex_update_groups(mesh, {0: (0, 2)})

        self.assertEqual(
            [
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_indices_binary": {"path": "ids.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
                    "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
                    "normals_binary": {"path": "normals.bin", "count": 2, "components": 3, "type": "f64", "delete_after": True},
                    "uvs_binary": {"path": "uvs.bin", "count": 2, "components": 2, "type": "f64", "delete_after": True},
                }
            ],
            groups,
        )
        self.assertFalse(hasattr(mesh.submeshes[0], "cdmw_native_preview_vertex_update_group"))

    def test_live_vertex_update_groups_forward_native_full_range(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].cdmw_native_preview_vertex_update_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 0,
            "source_vertex_count": 4,
            "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 4, "components": 2, "type": "f64", "delete_after": True},
        }

        groups = mesh_edit_vertex_update_groups(mesh, {0: range(0, 4)})

        self.assertEqual(
            [
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_start": 0,
                    "source_vertex_count": 4,
                    "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
                    "normals_binary": {"path": "normals.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
                    "uvs_binary": {"path": "uvs.bin", "count": 4, "components": 2, "type": "f64", "delete_after": True},
                }
            ],
            groups,
        )
        self.assertFalse(hasattr(mesh.submeshes[0], "cdmw_native_preview_vertex_update_group"))

    def test_live_vertex_update_python_fallback_uses_compact_source_range(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.services.mesh_workflow_service.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_vertex_update_groups_native", return_value={}),
        ):
            groups = mesh_edit_vertex_update_groups(mesh, {0: range(0, 4)}, allow_python_fallback=True)

        self.assertEqual(1, len(groups))
        self.assertEqual(0, groups[0]["source_vertex_start"])
        self.assertEqual(4, groups[0]["source_vertex_count"])
        self.assertNotIn("source_vertex_indices", groups[0])

    def test_live_vertex_update_python_fallback_is_legacy_opt_in(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.services.mesh_workflow_service.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_vertex_update_groups_native", return_value={}),
        ):
            groups = mesh_edit_vertex_update_groups(mesh, {0: range(0, 4)})

        self.assertEqual([], groups)

    def test_triangle_groups_forward_native_binary_descriptors(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].cdmw_native_preview_triangle_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices_binary": {"path": "source_vertices.bin", "count": 4, "components": 1, "type": "i32", "delete_after": True},
            "source_face_indices_binary": {"path": "source_faces.bin", "count": 2, "components": 1, "type": "i32", "delete_after": True},
            "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 4, "components": 2, "type": "f64", "delete_after": True},
            "indices_binary": {"path": "indices.bin", "count": 6, "components": 1, "type": "i32", "delete_after": True},
        }

        groups = mesh_edit_triangle_groups(mesh, (0,))

        self.assertEqual("cdmw_mesh_core", groups[0]["preview_backend"])
        self.assertEqual("positions.bin", groups[0]["positions_binary"]["path"])
        self.assertEqual("indices.bin", groups[0]["indices_binary"]["path"])
        self.assertNotIn("positions", groups[0])
        self.assertFalse(hasattr(mesh.submeshes[0], "cdmw_native_preview_triangle_group"))

    def test_triangle_groups_forward_native_source_ranges(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].cdmw_native_preview_triangle_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 7,
            "source_vertex_count": 4,
            "source_face_start": 3,
            "source_face_count": 2,
            "positions_binary": {"path": "positions.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "normals_binary": {"path": "normals.bin", "count": 4, "components": 3, "type": "f64", "delete_after": True},
            "uvs_binary": {"path": "uvs.bin", "count": 4, "components": 2, "type": "f64", "delete_after": True},
            "indices_binary": {"path": "indices.bin", "count": 6, "components": 1, "type": "i32", "delete_after": True},
        }

        groups = mesh_edit_triangle_groups(mesh, (0,))

        self.assertEqual("cdmw_mesh_core", groups[0]["preview_backend"])
        self.assertEqual([7, 8, 9, 10], _i32_descriptor_values(groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([3, 4], _i32_descriptor_values(groups[0], "source_face_indices", "source_face_indices_binary"))
        self.assertNotIn("source_vertex_indices", groups[0])
        self.assertNotIn("source_vertex_indices_binary", groups[0])
        self.assertNotIn("source_face_indices", groups[0])
        self.assertNotIn("source_face_indices_binary", groups[0])
        self.assertFalse(hasattr(mesh.submeshes[0], "cdmw_native_preview_triangle_group"))

    def test_triangle_group_python_fallback_uses_compact_identity_ranges(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.services.mesh_workflow_service.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_triangle_groups_native", return_value={}),
        ):
            groups = mesh_edit_triangle_groups(mesh, (0,), allow_python_fallback=True)

        self.assertEqual(0, groups[0]["source_vertex_start"])
        self.assertEqual(4, groups[0]["source_vertex_count"])
        self.assertEqual(0, groups[0]["source_face_start"])
        self.assertEqual(2, groups[0]["source_face_count"])
        self.assertNotIn("source_vertex_indices", groups[0])
        self.assertNotIn("source_face_indices", groups[0])

    def test_triangle_group_python_fallback_is_legacy_opt_in(self) -> None:
        mesh = build_synthetic_mesh()

        with (
            patch("cdmw.services.mesh_workflow_service.native_mesh_core_available", return_value=False),
            patch("cdmw.ui.mesh_editor.native_preview_payloads._mesh_edit_triangle_groups_native", return_value={}),
        ):
            groups = mesh_edit_triangle_groups(mesh, (0,))

        self.assertEqual([], groups)

    def test_standalone_preview_initial_blob_uses_native_geometry_writer(self) -> None:
        mesh = build_synthetic_mesh()
        vertex_struct = struct.Struct("<23f")
        native_blob = b"".join(
            vertex_struct.pack(
                float(index),
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.25,
                0.55,
                0.85,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
            )
            for index in range(6)
        )
        identity_blob = struct.pack(
            "<iiiiiiiiiiiiiiiiii",
            0,
            0,
            0,
            0,
            1,
            0,
            0,
            2,
            0,
            0,
            1,
            1,
            0,
            3,
            1,
            0,
            2,
            1,
        )
        calls: list[dict[str, object]] = []

        def _fake_native_geometry(output_path: Path, **kwargs: object) -> dict[str, object]:
            calls.append(dict(kwargs))
            Path(output_path).write_bytes(native_blob)
            identity_output_path = kwargs.get("identity_output_path")
            if identity_output_path:
                Path(identity_output_path).write_bytes(identity_blob)
            return {
                "vertex_count": 6,
                "geometry_size": len(native_blob),
                "batches": [
                    {
                        "mesh_index": 0,
                        "first_vertex": 0,
                        "vertex_count": 6,
                        "has_texture_coordinates": True,
                        "source_vertex_indices": [0, 1, 2, 1, 3, 2],
                        "source_face_indices": [0, 1],
                        "identity_offset": 0,
                        "identity_size": len(identity_blob),
                    }
                ],
            }

        with (
            patch("cdmw.services.mesh_workflow_service.find_native_mesh_core_binary", return_value=Path("native.exe")),
            patch("cdmw.services.mesh_workflow_service._ensure_native_mesh_session_submesh", return_value="session-0"),
            patch("cdmw.services.mesh_workflow_service.write_native_preview_geometry_blob", side_effect=_fake_native_geometry),
        ):
            prepared = mesh_to_native_preview(mesh)

        self.assertEqual(1, len(calls))
        self.assertEqual("session-0", calls[0]["meshes"][0]["session_id"])
        self.assertNotIn("positions", calls[0]["meshes"][0])
        self.assertNotIn("normals", calls[0]["meshes"][0])
        self.assertNotIn("texture_coordinates", calls[0]["meshes"][0])
        self.assertNotIn("faces", calls[0]["meshes"][0])
        self.assertNotIn("source_vertex_indices", calls[0]["meshes"][0])
        self.assertNotIn("source_face_indices", calls[0]["meshes"][0])
        self.assertNotIn("indices", calls[0]["meshes"][0])
        self.assertEqual(6, prepared.batches[0].index_count)
        self.assertEqual((0, 1, 2, 1, 3, 2), prepared.batches[0].source_vertex_indices)
        self.assertEqual((0, 1), prepared.batches[0].source_face_indices)
        self.assertEqual(identity_blob, prepared.batches[0].editor_identity_blob)

    def test_standalone_preview_records_native_geometry_fallback(self) -> None:
        clear_native_mesh_core_fallback_counts()
        try:
            with (
                patch("cdmw.services.mesh_workflow_service.find_native_mesh_core_binary", return_value=None),
                patch("cdmw.services.mesh_workflow_service.native_mesh_core_available", return_value=False),
            ):
                with self.assertRaisesRegex(RuntimeError, "native Mesh Editor preview geometry unavailable"):
                    mesh_to_native_preview(build_synthetic_mesh())

            self.assertEqual({"preview_geometry": 1}, native_mesh_core_fallback_counts())
            self.assertEqual("native preview geometry unavailable", native_mesh_core_fallback_events()[0]["reason"])
        finally:
            clear_native_mesh_core_fallback_counts()
