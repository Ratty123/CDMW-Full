from __future__ import annotations

import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.domain.mesh import MeshEditCommand, MeshEditResult, MeshEditSelection
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.ui.mesh_editor import MeshEditorController, MeshEditorNativeUpdate, apply_native_update_to_host
from cdmw.ui.mesh_editor.actions import mesh_editor_actions_by_key
from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession, apply_static_replacement_edit
from tools.mesh_editor_dev_harness import _build_two_part_synthetic_mesh, build_synthetic_mesh


def _selection_i32_values(group: object, json_key: str, binary_key: str) -> list[int]:
    if not isinstance(group, dict):
        return []
    raw_json = group.get(json_key)
    if isinstance(raw_json, list):
        return [int(value) for value in raw_json]
    if "vertex" in json_key:
        start_key, count_key = "source_vertex_start", "source_vertex_count"
    elif "face" in json_key:
        start_key, count_key = "source_face_start", "source_face_count"
    else:
        start_key, count_key = "", ""
    if start_key:
        try:
            raw_start = group.get(start_key, -1)
            raw_count = group.get(count_key, 0)
            start = int(raw_start if raw_start is not None else -1)
            count = int(raw_count if raw_count is not None else 0)
        except (TypeError, ValueError, OverflowError):
            start, count = -1, 0
        if start >= 0 and count > 0:
            return list(range(start, start + count))
    raw_descriptor = group.get(binary_key)
    if not isinstance(raw_descriptor, dict):
        return []
    data = Path(str(raw_descriptor.get("path") or "")).read_bytes()
    if len(data) % 4:
        return []
    return list(struct.unpack("<" + "i" * (len(data) // 4), data))


def _f64_values(group: object, json_key: str, binary_key: str) -> list[float]:
    if not isinstance(group, dict):
        return []
    raw_json = group.get(json_key)
    if isinstance(raw_json, list):
        return [float(value) for value in raw_json]
    raw_descriptor = group.get(binary_key)
    if not isinstance(raw_descriptor, dict):
        return []
    data = Path(str(raw_descriptor.get("path") or "")).read_bytes()
    if len(data) % 8:
        return []
    return list(struct.unpack("<" + "d" * (len(data) // 8), data))


def _selection_edges(group: object) -> list[list[int]]:
    if isinstance(group, dict) and isinstance(group.get("source_edges"), list):
        return [[int(edge[0]), int(edge[1])] for edge in group["source_edges"] if isinstance(edge, list) and len(edge) >= 2]
    values = _selection_i32_values(group, "source_edges", "source_edges_binary")
    return [[values[index], values[index + 1]] for index in range(0, len(values) - 1, 2)]


class _NativeUpdateHost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def update_mesh_edit_vertices(self, groups: object) -> bool:
        self.calls.append(("vertices", groups))
        return True

    def replace_mesh_edit_triangles(
        self,
        groups: object,
        *,
        replace_all: bool = False,
        source_submesh_indices: object = (),
    ) -> bool:
        self.calls.append(("triangles", (groups, replace_all, source_submesh_indices)))
        return True

    def set_material_overrides(self, **kwargs: object) -> bool:
        self.calls.append(("material", kwargs))
        return True

    def set_mesh_edit_selection_groups(self, groups: object) -> bool:
        self.calls.append(("selection", groups))
        return True


class _SelectionClearOnlyHost:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def clear_mesh_edit_vertex_selection(self) -> bool:
        self.calls.append("clear")
        return True


class _FailingVertexUpdateHost(_NativeUpdateHost):
    def update_mesh_edit_vertices(self, groups: object) -> bool:
        self.calls.append(("vertices", groups))
        return False


class MeshEditorControllerTests(unittest.TestCase):
    def test_controller_routes_edit_commands_through_service_and_vertex_updates(self) -> None:
        controller = MeshEditorController()
        view = controller.open_mesh(build_synthetic_mesh(), session_id="controller", mode="edit")

        controller.select(vertices_by_submesh={0: (0, 2)})
        result = controller.apply("transform", translate=(0.0, 0.0, 0.5))
        update = controller.native_update_for_result(result)

        self.assertEqual("controller", view.session_id)
        self.assertTrue(result.ok)
        self.assertEqual((), update.triangle_groups)
        self.assertEqual("cdmw_mesh_core", update.vertex_groups[0].get("preview_backend"))
        self.assertEqual(
            [0, 2],
            _selection_i32_values(update.vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"),
        )
        self.assertEqual((-0.75, 0.75, 0.5), controller.working_mesh().submeshes[0].vertices[2])

    def test_controller_select_uses_native_selection_groups_without_working_mesh_refresh(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="direct-selection-preview", mode="edit")
        result = controller.select(
            vertices_by_submesh={0: (0, 2)},
            edges_by_submesh={0: ((0, 1),)},
            faces_by_submesh={0: (0,)},
            source_indices=(0,),
        )

        with patch.object(controller, "working_mesh", side_effect=AssertionError("full mesh refresh")):
            update = controller.native_update_for_result(result)

        self.assertTrue(result.ok)
        self.assertTrue(update.refresh_selection)
        self.assertEqual(1, len(update.selection_groups))
        group = update.selection_groups[0]
        self.assertEqual(0, group["source_submesh_index"])
        self.assertEqual([0, 1, 2, 3], _selection_i32_values(group, "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([[0, 1]], _selection_edges(group))
        self.assertEqual([0], _selection_i32_values(group, "source_face_indices", "source_face_indices_binary"))

    def test_controller_exposes_export_validation_report(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].normals = []
        controller = MeshEditorController()
        controller.open_mesh(mesh, session_id="export-validation", mode="edit")

        report = controller.export_validation_report(available_textures=("harness.dds",))

        self.assertFalse(report.ok)
        self.assertIn("missing_normals", {issue.code for issue in report.blockers})

    def test_controller_exposes_workspace_part_summary(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(_build_two_part_synthetic_mesh(), session_id="workspace-summary", mode="edit")
        controller.select(source_indices=(1,))

        summary = controller.workspace_summary()

        self.assertEqual(2, summary.part_count)
        self.assertEqual(1, summary.selected_part_count)
        self.assertEqual("harness_material", summary.parts[0].material)
        self.assertTrue(summary.parts[1].selected)

    def test_controller_exposes_source_vs_edited_compare_summary(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="compare-summary", mode="edit")
        controller.apply(
            "transform",
            selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
            mode="edit",
            translate=(0.0, 0.0, 0.5),
        )

        with self.assertRaisesRegex(RuntimeError, "Python mesh state is stale"):
            controller.compare_summary()

        controller.working_mesh()
        summary = controller.compare_summary()

        self.assertTrue(summary.bounds_changed)
        self.assertEqual(1, summary.changed_part_count)
        self.assertGreater(summary.edited_bounds.size[2], summary.original_bounds.size[2])

    def test_controller_exposes_uv_island_summary(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="uv-summary", mode="edit")
        controller.select(vertices_by_submesh={0: (0,)})

        summary = controller.uv_summary()

        self.assertEqual(1, summary.island_count)
        self.assertEqual(1, summary.selected_island_count)
        self.assertEqual("harness.dds", summary.islands[0].texture)
        self.assertTrue(summary.islands[0].selected)

    def test_controller_exposes_skeleton_summary(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (1, 2), (2,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.6, 0.4), (0.75,)]
        mesh.has_bones = True
        controller = MeshEditorController()
        controller.open_mesh(mesh, session_id="skeleton-summary", mode="edit")
        controller.select(source_indices=(0,))

        summary = controller.skeleton_summary()

        self.assertTrue(summary.skinned)
        self.assertEqual(3, summary.inferred_bone_count)
        self.assertEqual(1, summary.weighted_part_count)
        self.assertEqual(1, summary.unnormalized_vertex_count)
        self.assertTrue(summary.parts[0].selected)

    def test_controller_attaches_skeleton_hierarchy(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.7, 0.3), (1.0,)]
        mesh.has_bones = True
        controller = MeshEditorController()
        controller.open_mesh(mesh, session_id="attach-skeleton", mode="edit")
        skeleton = Skeleton(
            path="character/model/body.pab",
            bones=[
                Bone(index=0, name="Root", parent_index=-1),
                Bone(index=1, name="Spine", parent_index=0),
            ],
            bone_count=2,
        )

        summary = controller.attach_skeleton(skeleton)
        overlay = controller.skeleton_overlay_data()
        selected = controller.select_bone(1)
        controller.set_pose_preview(True)
        posed = controller.rotate_selected_bone((0.0, 12.5, 0.0))
        posed_overlay = controller.skeleton_overlay_data()
        controller.select(vertices_by_submesh={0: (2,)})
        controller.working_mesh(clone=False).submeshes[0].bone_indices[2] = ()
        controller.working_mesh(clone=False).submeshes[0].bone_weights[2] = ()
        transferred = controller.transfer_selected_vertex_weights_from_source(source_skeleton=skeleton)
        weighted = controller.adjust_selected_vertex_bone_weight(0.2)

        self.assertEqual(2, summary.skeleton_bone_count)
        self.assertEqual("Root", summary.bones[1].parent_name)
        self.assertEqual("character/model/body.pab", summary.skeleton_source)
        self.assertEqual("Spine", selected.pose.selected_bone_name)
        self.assertTrue(posed.pose.enabled)
        self.assertEqual((0.0, 12.5, 0.0), posed.pose.rotation_degrees)
        self.assertAlmostEqual(0.3, transferred.selected_vertex_weights[0].selected_bone_weight)
        self.assertAlmostEqual(0.5, weighted.selected_vertex_weights[0].selected_bone_weight)
        assert overlay is not None
        self.assertEqual(2, len(overlay.bones))
        self.assertEqual("mesh_editor_attached_skeleton", overlay.bones[1].confidence)
        self.assertEqual("Root", overlay.bones[1].parent_name)
        assert posed_overlay is not None
        self.assertTrue(posed_overlay.skeleton_pose_enabled)
        self.assertEqual(1, posed_overlay.skeleton_selected_bone_index)
        self.assertEqual(((1, (0.0, 12.5, 0.0)),), posed_overlay.skeleton_pose_rotations)

    def test_controller_native_preview_uses_pose_deformed_mesh(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        mesh.has_bones = True
        controller = MeshEditorController()
        controller.open_mesh(mesh, session_id="posed-native-preview", mode="edit")
        controller.attach_skeleton(Skeleton(bones=[Bone(index=0, name="Root", parent_index=-1)], bone_count=1))
        original_vertex = controller.working_mesh().submeshes[0].vertices[1]
        expected_vertex = (-original_vertex[1], original_vertex[0], original_vertex[2])
        controller.select_bone(0)
        controller.rotate_selected_bone((0.0, 0.0, 90.0))

        preview_mesh = controller.pose_preview_mesh()
        prepared = controller.native_preview_data()
        second_face_vertex = struct.unpack_from("<23f", prepared.batches[0].vertex_blob, 23 * 4)

        self.assertAlmostEqual(expected_vertex[0], preview_mesh.submeshes[0].vertices[1][0], places=6)
        self.assertAlmostEqual(expected_vertex[1], preview_mesh.submeshes[0].vertices[1][1], places=6)
        self.assertAlmostEqual(expected_vertex[0], second_face_vertex[0], places=6)
        self.assertAlmostEqual(expected_vertex[1], second_face_vertex[1], places=6)
        self.assertEqual(original_vertex, controller.working_mesh().submeshes[0].vertices[1])

    def test_controller_native_preview_uses_direct_native_pose_payload_before_pose_clone(self) -> None:
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        mesh.has_bones = True
        controller = MeshEditorController()
        controller.open_mesh(mesh, session_id="posed-native-preview-direct", mode="edit")
        controller.attach_skeleton(Skeleton(bones=[Bone(index=0, name="Root", parent_index=-1)], bone_count=1))
        controller.select_bone(0)
        controller.rotate_selected_bone((0.0, 0.0, 90.0))
        native_preview = object()

        with (
            patch("cdmw.ui.mesh_editor.controller.mesh_pose_to_native_preview", return_value=native_preview) as native,
            patch.object(controller, "pose_preview_mesh", side_effect=AssertionError("pose clone fallback reached")),
        ):
            result = controller.native_preview_data()

        self.assertIs(native_preview, result)
        self.assertEqual(1, native.call_count)

    def test_controller_exposes_selected_texture_edit_target(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(_build_two_part_synthetic_mesh(), session_id="texture-target", mode="edit")
        controller.select(source_indices=(1,))

        target = controller.texture_edit_target()

        assert target is not None
        self.assertEqual(1, target.submesh_index)
        self.assertEqual("harness_quad_b", target.part_name)
        self.assertEqual("harness_b.dds", target.texture)

    def test_controller_native_preview_data_marks_local_dds_texture_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            texture_path = Path(temp_dir) / "local.dds"
            texture_path.write_bytes(b"dds")
            mesh = build_synthetic_mesh()
            mesh.submeshes[0].texture = str(texture_path)
            controller = MeshEditorController()
            controller.open_mesh(mesh, session_id="local-dds-preview", mode="edit")

            preview = controller.native_preview_data()

            batch = preview.batches[0]
            self.assertEqual(str(texture_path.resolve()), batch.preview_texture_path)
            self.assertEqual(str(texture_path.resolve()), batch.preview_texture_dds_path)

    def test_controller_topology_edit_returns_triangle_replacement_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="topology", mode="edit")
        controller.select(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)})

        result = controller.apply("extrude", offset=(0.0, 0.0, 0.25))
        update = controller.native_update_for_result(result)

        self.assertTrue(result.topology_changed)
        self.assertEqual((), update.vertex_groups)
        self.assertEqual([0], [group["source_submesh_index"] for group in update.triangle_groups])
        self.assertGreater(len(_selection_i32_values(update.triangle_groups[0], "indices", "indices_binary")), 6)
        self.assertFalse(update.replace_all_triangles)
        self.assertEqual((0,), update.triangle_source_submesh_indices)
        self.assertEqual([0], update.material_override_groups[0]["source_submesh_indices"])
        self.assertEqual(0.0, update.material_override_groups[0]["roughness"])
        self.assertEqual(1.0, update.material_override_groups[0]["texture_brightness"])

    def test_controller_topology_duplicate_returns_material_override_payload_for_new_part(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="topology-material", mode="edit")
        controller.select(source_indices=(0,))
        controller.apply(
            "material_assign",
            selection=controller.session_view().selection,
            material="routed",
            texture="routed.dds",
            roughness=0.45,
            metalness=0.1,
        )

        duplicated = controller.apply(
            "duplicate",
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
        )
        update = controller.native_update_for_result(duplicated)
        groups = {tuple(group["source_submesh_indices"]): group for group in update.material_override_groups}

        self.assertTrue(duplicated.topology_changed)
        self.assertFalse(update.replace_all_triangles)
        self.assertEqual((1,), update.triangle_source_submesh_indices)
        self.assertEqual([1], [group["source_submesh_index"] for group in update.triangle_groups])
        self.assertEqual(0, update.triangle_groups[0]["material_source_submesh_index"])
        self.assertEqual(0.45, groups[(1,)]["roughness"])
        self.assertEqual(0.1, groups[(1,)]["metalness"])
        self.assertEqual("routed", groups[(1,)]["material_name"])

    def test_controller_uv_transform_returns_live_uv_update_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="uv", mode="edit")
        controller.select(vertices_by_submesh={0: (0,)})

        result = controller.apply("uv_transform", offset=(0.25, 0.0))
        update = controller.native_update_for_result(result)

        self.assertTrue(result.ok)
        self.assertEqual((), update.triangle_groups)
        self.assertEqual([0], _selection_i32_values(update.vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([0.25, 1.0], _f64_values(update.vertex_groups[0], "uvs", "uvs_binary"))

    def test_controller_uv_rotation_returns_live_uv_update_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="uv-rotate", mode="edit")
        controller.select(vertices_by_submesh={0: (3,)})

        result = controller.apply("uv_transform", rotate=90.0, pivot=(0.5, 0.5))
        update = controller.native_update_for_result(result)

        self.assertTrue(result.ok)
        uvs = _f64_values(update.vertex_groups[0], "uvs", "uvs_binary")
        self.assertEqual([3], _selection_i32_values(update.vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertAlmostEqual(1.0, uvs[0], places=6)
        self.assertAlmostEqual(1.0, uvs[1], places=6)

    def test_controller_uv_island_transform_updates_whole_island_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="uv-island", mode="edit")
        controller.select(vertices_by_submesh={0: (0,)})

        result = controller.apply("uv_transform", uv_island=True, offset=(0.1, 0.0))
        update = controller.native_update_for_result(result)

        self.assertTrue(result.ok)
        self.assertEqual([0, 1, 2, 3], _selection_i32_values(update.vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([0.1, 1.0, 1.1, 1.0, 0.1, 0.0, 1.1, 0.0], _f64_values(update.vertex_groups[0], "uvs", "uvs_binary"))

    def test_controller_uv_region_selection_returns_native_selection_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="uv-region-select", mode="edit")

        result = controller.select_uv_region((0.0, 0.0), (0.1, 1.0))
        update = controller.native_update_for_result(result)

        self.assertTrue(result.ok)
        self.assertTrue(update.refresh_selection)
        self.assertEqual([0, 2], _selection_i32_values(update.selection_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))

    def test_controller_uv_lasso_selection_returns_native_selection_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="uv-lasso-select", mode="edit")

        result = controller.select_uv_lasso(((-0.1, -0.1), (0.2, -0.1), (0.2, 1.1), (-0.1, 1.1)))
        update = controller.native_update_for_result(result)

        self.assertTrue(result.ok)
        self.assertTrue(update.refresh_selection)
        self.assertEqual([0, 2], _selection_i32_values(update.selection_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))

    def test_controller_select_returns_native_selection_payload_for_vertices_edges_and_faces(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="selection", mode="edit")

        result = controller.select(edges_by_submesh={0: ((1, 2),)}, faces_by_submesh={0: (1,)})
        update = controller.native_update_for_result(result)

        self.assertTrue(result.ok)
        self.assertEqual("select", result.action)
        self.assertTrue(update.refresh_selection)
        self.assertEqual([1, 2, 3], _selection_i32_values(update.selection_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([[1, 2]], _selection_edges(update.selection_groups[0]))
        self.assertEqual([1], _selection_i32_values(update.selection_groups[0], "source_face_indices", "source_face_indices_binary"))

    def test_controller_select_add_operation_returns_combined_native_selection_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="selection-add", mode="edit")
        controller.select(vertices_by_submesh={0: (0,)})

        result = controller.select(edges_by_submesh={0: ((1, 2),)}, faces_by_submesh={0: (1,)}, operation="add")
        update = controller.native_update_for_result(result)

        self.assertTrue(result.ok)
        self.assertTrue(update.refresh_selection)
        self.assertEqual([0, 1, 2, 3], _selection_i32_values(update.selection_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([[1, 2]], _selection_edges(update.selection_groups[0]))
        self.assertEqual([1], _selection_i32_values(update.selection_groups[0], "source_face_indices", "source_face_indices_binary"))

    def test_controller_material_assign_returns_route_and_native_override_payloads(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="material", mode="edit")
        controller.select(source_indices=(0,))

        result = controller.apply(
            "material_assign",
            selection=controller.session_view().selection,
            material="edited_material",
            texture="edited.dds",
            material_authority_profile="material_authority_detail_mask",
            target_material_slot_index=2,
            roughness=0.45,
            metalness=0.1,
        )
        update = controller.native_update_for_result(result)

        submesh = controller.working_mesh().submeshes[0]
        self.assertTrue(result.ok)
        self.assertEqual("true_source_authority_detail_mask", getattr(submesh, "cdmw_material_authority_contract"))
        self.assertEqual("edited_material", update.triangle_groups[0]["material_name"])
        self.assertEqual("edited.dds", update.triangle_groups[0]["texture_name"])
        self.assertEqual([0], update.material_override_groups[0]["source_submesh_indices"])
        self.assertEqual(0.45, update.material_override_groups[0]["roughness"])
        self.assertEqual(0.1, update.material_override_groups[0]["metalness"])

    def test_controller_material_assign_native_update_does_not_hydrate_python_mesh(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="material-native-only", mode="edit")
        controller.select(source_indices=(0,))
        result = controller.apply(
            "material_assign",
            selection=controller.session_view().selection,
            material="edited_material",
            texture="edited.dds",
            roughness=0.45,
        )

        with patch.object(controller, "working_mesh", side_effect=AssertionError("python mesh fallback")):
            update = controller.native_update_for_result(result)

        self.assertTrue(result.ok)
        self.assertEqual((0,), update.triangle_source_submesh_indices)
        self.assertEqual("edited_material", update.triangle_groups[0]["material_name"])
        self.assertEqual(0.45, update.material_override_groups[0]["roughness"])

    def test_controller_face_material_assign_returns_full_triangle_refresh(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="face-material", mode="edit")
        controller.select(faces_by_submesh={0: (0,)})

        result = controller.apply(
            "material_assign",
            selection=controller.session_view().selection,
            material="face_material",
            texture="face.dds",
            roughness=0.4,
        )
        update = controller.native_update_for_result(result)

        mesh = controller.working_mesh()
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertFalse(update.replace_all_triangles)
        self.assertTrue(update.refresh_selection)
        self.assertEqual(2, len(mesh.submeshes))
        self.assertEqual((0, 1), update.triangle_source_submesh_indices)
        self.assertEqual({0, 1}, {group["source_submesh_index"] for group in update.triangle_groups})
        material_groups = {tuple(group["source_submesh_indices"]): group for group in update.material_override_groups}
        self.assertEqual("face_material", material_groups[(1,)]["material_name"])
        self.assertEqual(0.4, material_groups[(1,)]["roughness"])

    def test_controller_face_material_copy_returns_full_triangle_refresh(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(_build_two_part_synthetic_mesh(), session_id="face-material-copy", mode="edit")
        controller.select(faces_by_submesh={1: (0,)})

        result = controller.apply(
            "material_copy",
            selection=controller.session_view().selection,
            source_submesh_index=0,
        )
        update = controller.native_update_for_result(result)

        mesh = controller.working_mesh()
        self.assertTrue(result.ok)
        self.assertTrue(result.topology_changed)
        self.assertFalse(update.replace_all_triangles)
        self.assertTrue(update.refresh_selection)
        self.assertEqual(3, len(mesh.submeshes))
        self.assertEqual((1, 2), update.triangle_source_submesh_indices)
        self.assertEqual({1, 2}, {group["source_submesh_index"] for group in update.triangle_groups})
        material_groups = {tuple(group["source_submesh_indices"]): group for group in update.material_override_groups}
        self.assertEqual("harness_material", material_groups[(2,)]["material_name"])
        self.assertEqual(0.2, material_groups[(2,)]["roughness"])
        self.assertEqual(0.6, material_groups[(2,)]["metalness"])

    def test_controller_normal_edits_return_native_refresh_payloads(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="normals", mode="edit")
        controller.select(source_indices=(0,))
        controller.working_mesh(clone=False).submeshes[0].normals = [(0.0, 0.0, -1.0)] * 4

        recalc = controller.apply("recalculate_normals")
        recalc_update = controller.native_update_for_result(recalc)
        tangents = controller.apply("generate_tangents")
        tangent_update = controller.native_update_for_result(tangents)
        tangent_count_after_generate = len(getattr(controller.working_mesh().submeshes[0], "tangents", ()))
        flipped = controller.apply("flip_normals")
        flip_update = controller.native_update_for_result(flipped)
        copied = controller.apply("copy_normals")
        copy_update = controller.native_update_for_result(copied)

        self.assertEqual("recalculate_normals", recalc.action)
        self.assertEqual((), recalc_update.triangle_groups)
        recalc_vertex_group = recalc_update.vertex_groups[0]
        self.assertNotIn("source_vertex_indices", recalc_vertex_group)
        self.assertNotIn("normals", recalc_vertex_group)
        self.assertEqual(
            [0, 1, 2, 3],
            _selection_i32_values(recalc_vertex_group, "source_vertex_indices", "source_vertex_indices_binary"),
        )
        self.assertEqual(4, recalc_vertex_group["normals_binary"]["count"])
        self.assertEqual("generate_tangents", tangents.action)
        self.assertEqual((0,), tangents.affected_submesh_indices)
        self.assertEqual((), tangent_update.vertex_groups)
        self.assertEqual(4, tangent_count_after_generate)
        self.assertEqual("flip_normals", flipped.action)
        self.assertTrue(any("Invalidated tangents" in message for message in flipped.diagnostics))
        self.assertEqual([], getattr(controller.working_mesh().submeshes[0], "tangents", ()))
        self.assertEqual((), flip_update.vertex_groups)
        self.assertEqual([0], [group["source_submesh_index"] for group in flip_update.triangle_groups])
        self.assertEqual([0, 2, 1, 1, 2, 3], _selection_i32_values(flip_update.triangle_groups[0], "indices", "indices_binary"))
        self.assertEqual([0.0, 0.0, -1.0], _f64_values(flip_update.triangle_groups[0], "normals", "normals_binary")[:3])
        self.assertEqual("copy_normals", copied.action)
        self.assertEqual([0, 1, 2, 3], _selection_i32_values(copy_update.vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual([0.0, 0.0, 1.0], _f64_values(copy_update.vertex_groups[0], "normals", "normals_binary")[:3])

    def test_controller_recalculate_normals_uses_native_payload_before_full_scan(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="normals-native-delta", mode="edit")
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [1],
            "positions": [1.0, 0.0, 0.0],
            "normals": [0.0, 0.0, 1.0],
            "uvs": [1.0, 0.0],
        }
        result = MeshEditResult(
            action="recalculate_normals",
            status="ok",
            revision=1,
            affected_submesh_indices=(0,),
            changed_vertices_by_submesh=((0, (1,)),),
            native_preview_vertex_update_groups=(native_group,),
        )

        with patch(
            "cdmw.ui.mesh_editor.controller._all_vertices_by_submesh",
            side_effect=AssertionError("full scan"),
        ):
            update = controller.native_update_for_result(result)

        self.assertEqual([1], _selection_i32_values(update.vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"))

    def test_controller_vertex_update_uses_native_generator_before_python_packing(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-vertex-update-generator", mode="edit")
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [1],
            "positions": [1.0, 0.0, 0.0],
            "normals": [0.0, 0.0, 1.0],
            "uvs": [1.0, 0.0],
        }
        result = MeshEditResult(
            action="undo",
            status="ok",
            revision=2,
            changed_vertices_by_submesh=((0, (1,)),),
        )

        with (
            patch("cdmw.services.mesh_workflow_service.build_native_mesh_preview_vertex_update_groups", return_value=[native_group]) as native_groups,
            patch("cdmw.ui.mesh_editor.native_preview_payloads._vec3", side_effect=AssertionError("python vertex packing")),
        ):
            update = controller.legacy_python_update_for_result(result, allow_archive_legacy_preview_rebuild=True)

        native_groups.assert_called_once()
        self.assertEqual("cdmw_mesh_core", update.vertex_groups[0]["preview_backend"])
        self.assertEqual([1], update.vertex_groups[0]["source_vertex_indices"])

    def test_controller_native_vertex_update_result_does_not_hydrate_python_mesh(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-vertex-update-result", mode="edit")
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [1],
            "positions": [1.0, 0.0, 0.0],
            "normals": [0.0, 0.0, 1.0],
            "uvs": [1.0, 0.0],
        }
        result = MeshEditResult(
            action="transform",
            status="ok",
            revision=2,
            changed_vertices_by_submesh=((0, (1,)),),
            metrics={"native_apply_roundtrip_ms": 1.0},
            native_preview_vertex_update_groups=(native_group,),
        )

        with patch.object(controller, "working_mesh", side_effect=AssertionError("python mesh fallback")):
            update = controller.native_update_for_result(result)

        self.assertEqual("cdmw_mesh_core", update.vertex_groups[0]["preview_backend"])
        self.assertEqual([1], update.vertex_groups[0]["source_vertex_indices"])

    def test_controller_rejects_native_vertex_update_without_preview_groups(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-vertex-update-missing", mode="edit")
        result = MeshEditResult(
            action="transform",
            status="ok",
            revision=2,
            changed_vertices_by_submesh=((0, (1,)),),
            metrics={"native_apply_roundtrip_ms": 1.0},
        )

        with self.assertRaisesRegex(RuntimeError, "Python vertex preview rebuild is disabled"):
            controller.native_update_for_result(result)

    def test_controller_rejects_active_native_result_without_preview_payload_even_without_metrics(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="active-native-no-preview", mode="edit")
        result = MeshEditResult(
            action="transform",
            status="ok",
            revision=2,
            changed_vertices_by_submesh=((0, (1,)),),
        )

        with (
            patch.object(controller, "working_mesh", side_effect=AssertionError("python mesh fallback")),
            self.assertRaisesRegex(RuntimeError, "active native transform result did not include preview payload"),
        ):
            controller.native_update_for_result(result)

    def test_controller_active_native_noop_does_not_read_working_mesh(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="active-native-noop", mode="edit")
        result = MeshEditResult(action="transform", status="ok", revision=2)

        with patch.object(controller, "working_mesh", side_effect=AssertionError("python mesh fallback")):
            update = controller.native_update_for_result(result)

        self.assertFalse(update.vertex_groups)
        self.assertFalse(update.triangle_groups)

    def test_controller_legacy_python_update_requires_archive_opt_in(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="active-legacy-update-blocked", mode="edit")
        result = MeshEditResult(action="transform", status="ok", revision=2)

        with (
            patch.object(controller, "working_mesh", side_effect=AssertionError("python mesh fallback")),
            self.assertRaisesRegex(RuntimeError, "archive-only"),
        ):
            controller.legacy_python_update_for_result(result)

    def test_controller_vertex_update_compacts_contiguous_changed_vertices(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-vertex-update-no-copy", mode="edit")
        changed_indices = (0, 1, 2, 3)
        result = MeshEditResult(
            action="undo",
            status="ok",
            revision=2,
            changed_vertices_by_submesh=((0, changed_indices),),
        )

        def native_groups(_mesh: object, changed_vertices_by_submesh: object) -> list[dict[str, object]]:
            self.assertEqual({0: range(0, 4)}, changed_vertices_by_submesh)
            return []

        with patch("cdmw.services.mesh_workflow_service.build_native_mesh_preview_vertex_update_groups", side_effect=native_groups):
            controller.legacy_python_update_for_result(result, allow_archive_legacy_preview_rebuild=True)

    def test_controller_preserves_large_changed_vertex_set_for_native_update(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-vertex-update-large-set", mode="edit")
        changed_set = set(range(10_001))
        result = MeshEditResult(
            action="undo",
            status="ok",
            revision=2,
            changed_vertices_by_submesh=((0, changed_set),),
        )

        def vertex_groups(_mesh: object, changed_vertices_by_submesh: object, **_kwargs: object) -> list[dict[str, object]]:
            self.assertIs(changed_vertices_by_submesh[0], changed_set)  # type: ignore[index]
            return []

        with patch("cdmw.ui.mesh_editor.controller.mesh_edit_vertex_update_groups", side_effect=vertex_groups):
            controller.legacy_python_update_for_result(result, allow_archive_legacy_preview_rebuild=True)

    def test_controller_preserves_changed_vertex_descriptor_for_native_update(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-vertex-update-descriptor", mode="edit")
        descriptor = {
            "changed_vertices_binary": {
                "path": "changed.bin",
                "count": 2,
                "components": 1,
                "type": "i32",
            }
        }
        result = MeshEditResult(
            action="undo",
            status="ok",
            revision=2,
            changed_vertices_by_submesh=((0, descriptor),),
        )

        def vertex_groups(_mesh: object, changed_vertices_by_submesh: object, **_kwargs: object) -> list[dict[str, object]]:
            self.assertIs(changed_vertices_by_submesh[0], descriptor)  # type: ignore[index]
            return []

        with patch("cdmw.ui.mesh_editor.controller.mesh_edit_vertex_update_groups", side_effect=vertex_groups):
            controller.legacy_python_update_for_result(result, allow_archive_legacy_preview_rebuild=True)

    def test_controller_rejects_deferred_native_topology_without_preview_groups(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-topology-no-preview", mode="edit")
        result = MeshEditResult(
            action="subdivide",
            status="ok",
            revision=2,
            topology_changed=True,
            submesh_counts=((5, 4),),
            metrics={"python_apply_deferred": 1.0},
        )

        with self.assertRaisesRegex(RuntimeError, "Python preview rebuild is disabled"):
            controller.native_update_for_result(result)

    def test_controller_rejects_native_material_result_without_preview_groups(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-material-no-preview", mode="edit")
        result = MeshEditResult(
            action="material_assign",
            status="ok",
            revision=2,
            affected_submesh_indices=(0,),
            metrics={"native_apply_roundtrip_ms": 1.0},
        )

        with self.assertRaisesRegex(RuntimeError, "Python preview rebuild is disabled"):
            controller.native_update_for_result(result)

    def test_controller_rejects_native_affected_result_without_preview_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-affected-no-preview", mode="edit")
        result = MeshEditResult(
            action="recalculate_normals",
            status="ok",
            revision=2,
            affected_submesh_indices=(0,),
            metrics={"native_apply_roundtrip_ms": 1.0},
        )

        with self.assertRaisesRegex(RuntimeError, "Python preview rebuild is disabled"):
            controller.native_update_for_result(result)

    def test_controller_rejects_active_native_affected_result_without_preview_payload_even_without_metrics(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-recalc-all-range", mode="edit")
        result = MeshEditResult(
            action="recalculate_normals",
            status="ok",
            revision=2,
            affected_submesh_indices=(0,),
        )

        with (
            patch.object(controller, "working_mesh", side_effect=AssertionError("python mesh fallback")),
            self.assertRaisesRegex(RuntimeError, "active native recalculate_normals result did not include preview payload"),
        ):
            controller.native_update_for_result(result)

    def test_controller_sparse_history_undo_uses_vertex_update_before_full_refresh(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="history-sparse-delta", mode="edit")
        result = MeshEditResult(
            action="undo",
            status="ok",
            revision=2,
            changed_vertices_by_submesh=((0, (1,)),),
        )
        vertex_payload = {"source_submesh_index": 0, "source_vertex_indices": (1,), "positions": (0.0, 0.0, 0.0)}
        vertex_payloads = [vertex_payload]

        with (
            patch("cdmw.ui.mesh_editor.controller.mesh_edit_triangle_groups", side_effect=AssertionError("full refresh")),
            patch("cdmw.ui.mesh_editor.controller.mesh_edit_vertex_update_groups", return_value=vertex_payloads) as vertex_groups,
        ):
            update = controller.legacy_python_update_for_result(result, allow_archive_legacy_preview_rebuild=True)

        vertex_groups.assert_called_once()
        self.assertFalse(update.replace_all_triangles)
        self.assertIs(vertex_payloads, update.vertex_groups)
        self.assertEqual((), update.triangle_groups)
        self.assertTrue(update.refresh_selection)

    def test_controller_history_refresh_uses_native_triangle_group_generator(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="history-native-triangles", mode="edit")
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": [0, 1, 2, 3],
            "source_face_indices": [0, 1],
            "positions": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0],
            "normals": [0.0, 0.0, 1.0] * 4,
            "uvs": [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0],
            "indices": [0, 1, 2, 1, 3, 2],
        }
        result = MeshEditResult(action="undo", status="ok", revision=2)

        with (
            patch("cdmw.services.mesh_workflow_service.build_native_mesh_preview_triangle_groups", return_value=[native_group]) as native_groups,
            patch("cdmw.ui.mesh_editor.native_preview_payloads._valid_face_items", side_effect=AssertionError("python triangle packing")),
        ):
            update = controller.legacy_python_update_for_result(result, allow_archive_legacy_preview_rebuild=True)

        native_groups.assert_called_once()
        self.assertTrue(update.replace_all_triangles)
        self.assertEqual("cdmw_mesh_core", update.triangle_groups[0]["preview_backend"])
        self.assertEqual([0, 1, 2, 1, 3, 2], update.triangle_groups[0]["indices"])

    def test_controller_preview_data_and_history(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="history", mode="sculpt")
        controller.select(vertices_by_submesh={0: (0,)})
        brushed = controller.apply("brush", tool="grab", center=(-0.75, -0.75, 0.0), radius=1.0, strength=1.0, delta=(0.0, 0.0, 0.5))
        brushed_update = controller.native_update_for_result(brushed)

        with self.assertRaisesRegex(RuntimeError, "Python mesh state is stale"):
            controller.native_preview_data()

        controller.working_mesh()
        prepared = controller.native_preview_data()
        self.assertEqual(1, len(prepared.batches))
        self.assertEqual(6, prepared.batches[0].index_count)
        self.assertEqual("cdmw_mesh_core", brushed_update.vertex_groups[0].get("preview_backend"))
        self.assertEqual(
            [0],
            _selection_i32_values(brushed_update.vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"),
        )

        self.assertTrue(controller.undo().ok)
        self.assertEqual((-0.75, -0.75, 0.0), controller.working_mesh().submeshes[0].vertices[0])
        self.assertTrue(controller.redo().ok)
        self.assertEqual((-0.75, -0.75, 0.5), controller.working_mesh().submeshes[0].vertices[0])

    def test_controller_history_actions_return_incremental_topology_refresh_payloads(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-history", mode="edit")
        controller.select(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)})
        controller.apply("extrude", offset=(0.0, 0.0, 0.25))

        undo = controller.undo()
        undo_update = controller.native_update_for_result(undo)
        redo = controller.redo()
        redo_update = controller.native_update_for_result(redo)

        self.assertEqual("undo", undo.action)
        self.assertTrue(undo.topology_changed)
        self.assertFalse(undo_update.replace_all_triangles)
        self.assertEqual((0,), undo_update.triangle_source_submesh_indices)
        self.assertTrue(undo_update.refresh_selection)
        self.assertEqual([0], [group["source_submesh_index"] for group in undo_update.triangle_groups])
        self.assertEqual(6, len(_selection_i32_values(undo_update.triangle_groups[0], "indices", "indices_binary")))
        self.assertEqual("redo", redo.action)
        self.assertTrue(redo.topology_changed)
        self.assertFalse(redo_update.replace_all_triangles)
        self.assertEqual((0,), redo_update.triangle_source_submesh_indices)
        self.assertTrue(redo_update.refresh_selection)
        self.assertGreater(len(_selection_i32_values(redo_update.triangle_groups[0], "indices", "indices_binary")), 6)

    def test_controller_topology_refresh_clears_pruned_native_selection_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-topology-selection-prune", mode="edit")
        controller.select(faces_by_submesh={0: (1,)})

        deleted = controller.apply("delete")
        update = controller.native_update_for_result(deleted)

        self.assertTrue(deleted.ok)
        self.assertTrue(deleted.topology_changed)
        self.assertFalse(update.replace_all_triangles)
        self.assertEqual((0,), update.triangle_source_submesh_indices)
        self.assertTrue(update.refresh_selection)
        self.assertFalse(update.selection_groups)
        self.assertEqual("cdmw_mesh_core", update.triangle_groups[0].get("preview_backend"))

    def test_controller_uses_result_native_topology_groups_without_working_mesh_refresh(self) -> None:
        controller = MeshEditorController()
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 0,
            "source_vertex_count": 3,
            "source_face_start": 0,
            "source_face_count": 1,
            "positions": [0.0] * 9,
            "normals": [0.0, 0.0, 1.0] * 3,
            "uvs": [0.0] * 6,
            "indices": [0, 1, 2],
        }
        result = MeshEditResult(
            action="subdivide",
            status="ok",
            revision=1,
            affected_submesh_indices=(0,),
            native_preview_triangle_groups=(native_group,),
            topology_changed=True,
        )

        with patch.object(controller, "working_mesh", side_effect=AssertionError("full mesh refresh")):
            update = controller.native_update_for_result(result)

        self.assertEqual((0,), update.triangle_source_submesh_indices)
        self.assertEqual((native_group,), tuple(update.triangle_groups))
        self.assertTrue(update.refresh_selection)
        self.assertFalse(update.selection_groups)
        self.assertFalse(update.replace_all_triangles)

    def test_controller_uses_append_native_topology_groups_without_working_mesh_refresh(self) -> None:
        controller = MeshEditorController()
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 1,
            "material_source_submesh_index": 0,
            "material_name": "routed",
            "texture_name": "routed.dds",
            "roughness": 0.45,
            "metalness": 0.1,
            "source_vertex_start": 0,
            "source_vertex_count": 3,
            "source_face_start": 0,
            "source_face_count": 1,
            "positions": [0.0] * 9,
            "normals": [0.0, 0.0, 1.0] * 3,
            "uvs": [0.0] * 6,
            "indices": [0, 1, 2],
        }
        result = MeshEditResult(
            action="duplicate",
            status="ok",
            revision=1,
            affected_submesh_indices=(1,),
            native_preview_triangle_groups=(native_group,),
            topology_changed=True,
            submesh_count_delta=1,
        )

        with patch.object(controller, "working_mesh", side_effect=AssertionError("full mesh refresh")):
            update = controller.native_update_for_result(result)

        self.assertEqual((1,), update.triangle_source_submesh_indices)
        self.assertEqual((native_group,), tuple(update.triangle_groups))
        groups = {tuple(group["source_submesh_indices"]): group for group in update.material_override_groups}
        self.assertEqual("routed", groups[(1,)]["material_name"])
        self.assertEqual(0.45, groups[(1,)]["roughness"])
        self.assertEqual(0.1, groups[(1,)]["metalness"])

    def test_controller_history_refresh_clears_pruned_native_selection_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-history-selection-prune", mode="edit")
        controller.apply("duplicate", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}))
        controller.select(faces_by_submesh={1: (0,)}, source_indices=(1,))

        selection_undo = controller.undo()
        with patch.object(controller, "working_mesh", side_effect=AssertionError("full mesh refresh")):
            selection_update = controller.native_update_for_result(selection_undo)
        undo = controller.undo()
        with patch.object(controller, "working_mesh", side_effect=AssertionError("full mesh refresh")):
            update = controller.native_update_for_result(undo)

        self.assertTrue(selection_undo.ok)
        self.assertFalse(selection_update.triangle_groups)
        self.assertTrue(selection_update.refresh_selection)
        self.assertFalse(selection_update.selection_groups)
        self.assertTrue(undo.ok)
        self.assertEqual((False, 1), (update.replace_all_triangles, update.final_submesh_count))
        self.assertEqual((1,), update.triangle_source_submesh_indices)
        self.assertEqual((), update.triangle_groups)
        self.assertTrue(update.refresh_selection)
        self.assertFalse(update.selection_groups)

    def test_controller_negative_native_topology_groups_include_removed_sources_without_working_mesh_refresh(self) -> None:
        controller = MeshEditorController()
        native_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_start": 0,
            "source_vertex_count": 3,
            "source_face_start": 0,
            "source_face_count": 1,
            "positions": [0.0] * 9,
            "normals": [0.0, 0.0, 1.0] * 3,
            "uvs": [0.0] * 6,
            "indices": [0, 1, 2],
        }
        result = MeshEditResult(
            action="undo",
            status="ok",
            revision=2,
            affected_submesh_indices=(0, 2),
            native_preview_triangle_groups=(native_group,),
            topology_changed=True,
            submesh_count_delta=-1,
            submesh_counts=((3, 1), (3, 1)),
        )

        with patch.object(controller, "working_mesh", side_effect=AssertionError("full mesh refresh")):
            update = controller.native_update_for_result(result)

        self.assertFalse(update.replace_all_triangles)
        self.assertEqual((2, (0, 1, 2)), (update.final_submesh_count, update.triangle_source_submesh_indices))
        self.assertEqual((native_group,), tuple(update.triangle_groups))
        self.assertTrue(update.refresh_selection)

    def test_controller_negative_topology_restores_direct_selection_without_working_mesh_refresh(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="negative-topology-direct-selection", mode="edit")
        controller.select(faces_by_submesh={0: (0,)}, source_indices=(0,))
        result = MeshEditResult(
            action="undo",
            status="ok",
            revision=2,
            affected_submesh_indices=(1,),
            topology_changed=True,
            submesh_count_delta=-1,
        )

        with patch.object(controller, "working_mesh", side_effect=AssertionError("full mesh refresh")):
            update = controller.native_update_for_result(result)

        self.assertFalse(update.replace_all_triangles)
        self.assertEqual((1, (1,)), (update.final_submesh_count, update.triangle_source_submesh_indices))
        self.assertEqual((), update.triangle_groups)
        self.assertTrue(update.refresh_selection)
        self.assertEqual(1, len(update.selection_groups))
        group = update.selection_groups[0]
        self.assertEqual(0, group["source_submesh_index"])
        self.assertEqual([0], _selection_i32_values(group, "source_face_indices", "source_face_indices_binary"))
        self.assertIs(True, group["source_selected"])

    def test_controller_history_refresh_restores_native_selection_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-history-selection-restore", mode="edit")
        controller.select(faces_by_submesh={0: (0,)})
        controller.apply("duplicate")
        controller.select(faces_by_submesh={1: (0,)}, source_indices=(1,))

        undo = controller.undo()
        with patch.object(controller, "working_mesh", side_effect=AssertionError("full mesh refresh")):
            undo_update = controller.native_update_for_result(undo)
        redo = controller.redo()
        with patch.object(controller, "working_mesh", side_effect=AssertionError("full mesh refresh")):
            redo_update = controller.native_update_for_result(redo)

        self.assertTrue(undo.ok)
        self.assertEqual([0], _selection_i32_values(undo_update.selection_groups[0], "source_face_indices", "source_face_indices_binary"))
        self.assertEqual(0, undo_update.selection_groups[0]["source_submesh_index"])
        self.assertTrue(redo.ok)
        self.assertEqual((), redo_update.triangle_groups)
        self.assertEqual([0], _selection_i32_values(redo_update.selection_groups[0], "source_face_indices", "source_face_indices_binary"))
        self.assertEqual(1, redo_update.selection_groups[0]["source_submesh_index"])

    def test_controller_history_restores_mode_before_action_palette_switch(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-history-mode-restore", mode="object")
        controller.select(faces_by_submesh={0: (0,)})

        duplicated = controller.apply_editor_action("duplicate")
        after_duplicate_mode = controller.session_view().mode
        undo = controller.undo()
        undo_update = controller.native_update_for_result(undo)
        after_undo_mode = controller.session_view().mode
        redo = controller.redo()
        redo_update = controller.native_update_for_result(redo)
        after_redo_mode = controller.session_view().mode

        self.assertTrue(duplicated.ok)
        self.assertEqual("edit", after_duplicate_mode)
        self.assertTrue(undo.ok)
        self.assertEqual("object", after_undo_mode)
        self.assertEqual([0], _selection_i32_values(undo_update.selection_groups[0], "source_face_indices", "source_face_indices_binary"))
        self.assertTrue(redo.ok)
        self.assertEqual("edit", after_redo_mode)
        self.assertEqual([0], _selection_i32_values(redo_update.selection_groups[0], "source_face_indices", "source_face_indices_binary"))

    def test_controller_history_material_updates_clear_stale_native_overrides(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-material-history", mode="edit")
        controller.select(source_indices=(0,))

        assigned = controller.apply(
            "material_assign",
            selection=controller.session_view().selection,
            material="edited_material",
            texture="edited.dds",
            roughness=0.45,
            metalness=0.1,
        )
        assigned_update = controller.native_update_for_result(assigned)
        undo = controller.undo()
        undo_update = controller.native_update_for_result(undo)
        redo = controller.redo()
        redo_update = controller.native_update_for_result(redo)

        self.assertEqual(0.45, assigned_update.material_override_groups[0]["roughness"])
        self.assertEqual(0.1, assigned_update.material_override_groups[0]["metalness"])
        self.assertEqual("undo", undo.action)
        self.assertEqual("harness_material", undo_update.material_override_groups[0]["material_name"])
        self.assertEqual(0.0, undo_update.material_override_groups[0]["roughness"])
        self.assertEqual(0.0, undo_update.material_override_groups[0]["metalness"])
        self.assertEqual(1.0, undo_update.material_override_groups[0]["texture_brightness"])
        self.assertEqual("redo", redo.action)
        self.assertEqual("edited_material", redo_update.material_override_groups[0]["material_name"])
        self.assertEqual(0.45, redo_update.material_override_groups[0]["roughness"])
        self.assertEqual(0.1, redo_update.material_override_groups[0]["metalness"])

    def test_controller_plain_material_assign_sends_native_override_reset(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="native-material-assign-reset", mode="edit")
        controller.select(source_indices=(0,))
        selection = controller.session_view().selection

        controller.apply(
            "material_assign",
            selection=selection,
            material="routed_material",
            texture="routed.dds",
            material_profile="runtime_xml",
            route_status="ready",
            roughness=0.45,
            metalness=0.1,
        )
        plain = controller.apply(
            "material_assign",
            selection=selection,
            material="plain_material",
            texture="plain.dds",
        )
        update = controller.native_update_for_result(plain)

        submesh = controller.working_mesh().submeshes[0]
        self.assertFalse(hasattr(submesh, "cdmw_material_authority_profile"))
        self.assertFalse(hasattr(submesh, "preview_native_material_overrides"))
        self.assertEqual("plain_material", update.material_override_groups[0]["material_name"])
        self.assertEqual(0.0, update.material_override_groups[0]["roughness"])
        self.assertEqual(0.0, update.material_override_groups[0]["metalness"])
        self.assertEqual(1.0, update.material_override_groups[0]["texture_brightness"])

    def test_native_update_dispatcher_sends_preview_host_commands_in_live_order(self) -> None:
        host = _NativeUpdateHost()
        update = MeshEditorNativeUpdate(
            vertex_groups=({"source_submesh_index": 0, "source_vertex_indices": [0]},),
            triangle_groups=({"source_submesh_index": 0, "indices": [0, 1, 2]},),
            selection_groups=({"source_submesh_index": 0, "source_edges": [[0, 1]]},),
            refresh_selection=True,
            material_override_groups=(
                {
                    "source_submesh_indices": [0],
                    "material_name": "ignored_by_host_override",
                    "roughness": 0.4,
                    "metalness": 0.2, "emissive_scalar_mask": True,
                },
            ),
            replace_all_triangles=True,
        )

        ok = apply_native_update_to_host(host, update)

        self.assertTrue(ok)
        self.assertEqual(["vertices", "triangles", "material", "selection"], [name for name, _payload in host.calls])
        self.assertEqual(True, host.calls[1][1][1])
        self.assertEqual((), host.calls[1][1][2])
        self.assertEqual({"source_submesh_indices": (0,), "roughness": 0.4, "metalness": 0.2, "emissive_scalar_mask": True}, host.calls[2][1])
        self.assertEqual(update.selection_groups, host.calls[3][1])

    def test_native_update_dispatcher_stops_after_failed_preview_command(self) -> None:
        host = _FailingVertexUpdateHost()
        update = MeshEditorNativeUpdate(
            vertex_groups=({"source_submesh_index": 0, "source_vertex_indices": [0]},),
            triangle_groups=({"source_submesh_index": 0, "indices": [0, 1, 2]},),
            selection_groups=({"source_submesh_index": 0, "source_face_indices": [0]},),
            refresh_selection=True,
            material_override_groups=({"source_submesh_indices": [0], "roughness": 0.4},),
        )

        ok = apply_native_update_to_host(host, update)

        self.assertFalse(ok)
        self.assertEqual(["vertices"], [name for name, _payload in host.calls])

    def test_native_update_dispatcher_can_clear_selection_on_legacy_hosts(self) -> None:
        host = _SelectionClearOnlyHost()

        ok = apply_native_update_to_host(host, MeshEditorNativeUpdate(refresh_selection=True))

        self.assertTrue(ok)
        self.assertEqual(["clear"], host.calls)

    def test_controller_requires_active_session(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no active"):
            MeshEditorController().session_view()

    def test_controller_applies_action_palette_mode_selection_and_brush_descriptors(self) -> None:
        actions = mesh_editor_actions_by_key()
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="palette", mode="object")

        mode_result = controller.apply_editor_action(actions["mode_sculpt"])
        selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})
        select_result = controller.apply_editor_action("select_vertex", selection=selection)
        brush_result = controller.apply_editor_action(
            actions["brush_grab"],
            center=(-0.75, -0.75, 0.0),
            radius=1.0,
            strength=1.0,
            delta=(0.0, 0.0, 0.25),
        )

        self.assertTrue(mode_result.ok)
        self.assertEqual("sculpt", controller.session_view().mode)
        self.assertTrue(select_result.ok)
        self.assertEqual("vertex", controller.active_selection_mode)
        self.assertEqual("brush_grab", controller.active_action_key)
        self.assertTrue(brush_result.ok)
        self.assertEqual("brush", brush_result.action)
        self.assertEqual((-0.75, -0.75, 0.25), controller.working_mesh().submeshes[0].vertices[0])

    def test_controller_selection_palette_without_payload_only_switches_tool_mode(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="palette-selection-tool", mode="edit")
        controller.select(faces_by_submesh={0: (0,)})
        before = controller.session_view()

        result = controller.apply_editor_action("select_edge")
        native_update = controller.native_update_for_result(result)
        after = controller.session_view()

        self.assertEqual("noop", result.status)
        self.assertEqual("select", result.action)
        self.assertEqual("edge", controller.active_selection_mode)
        self.assertEqual(before.selection, after.selection)
        self.assertEqual(before.revision, after.revision)
        self.assertFalse(native_update.refresh_selection)
        self.assertEqual((), native_update.selection_groups)

    def test_controller_brush_action_can_run_without_existing_selection(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="palette-brush-empty", mode="sculpt")

        result = controller.apply_editor_action(
            "brush_grab",
            center=(-0.75, -0.75, 0.0),
            radius=0.1,
            strength=1.0,
            delta=(0.0, 0.0, 0.25),
        )

        self.assertTrue(result.ok)
        self.assertEqual("brush", result.action)
        self.assertEqual(((0, range(0, 1)),), result.changed_vertices_by_submesh)
        self.assertEqual((-0.75, -0.75, 0.25), controller.working_mesh().submeshes[0].vertices[0])

    def test_controller_action_palette_routes_undo_and_redo(self) -> None:
        actions = mesh_editor_actions_by_key()
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="palette-history", mode="edit")
        controller.select(vertices_by_submesh={0: (0,)})
        controller.apply_editor_action("transform_move", translate=(0.0, 0.0, 0.25))

        undo = controller.apply_editor_action(actions["undo"])
        self.assertEqual("undo", undo.action)
        self.assertEqual((-0.75, -0.75, 0.0), controller.working_mesh().submeshes[0].vertices[0])

        redo = controller.apply_editor_action("redo")
        self.assertEqual("redo", redo.action)
        self.assertEqual((-0.75, -0.75, 0.25), controller.working_mesh().submeshes[0].vertices[0])

    def test_controller_action_palette_selection_required_actions_noop_without_selection(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="palette-selection-required", mode="edit")
        before = tuple(controller.working_mesh().submeshes[0].vertices)
        before_material = controller.working_mesh().submeshes[0].material

        moved = controller.apply_editor_action("transform_move", translate=(0.0, 0.0, 0.25))
        material = controller.apply_editor_action("material_assign", material="edited_material", texture="edited.dds")

        self.assertEqual("noop", moved.status)
        self.assertEqual("transform", moved.action)
        self.assertIn("needs a selection", moved.diagnostics[0])
        self.assertEqual("noop", material.status)
        self.assertEqual("material_assign", material.action)
        self.assertIn("needs a selection", material.diagnostics[0])
        self.assertEqual(0, controller.session_view().revision)
        self.assertEqual(before, tuple(controller.working_mesh().submeshes[0].vertices))
        self.assertEqual(before_material, controller.working_mesh().submeshes[0].material)

    def test_controller_action_palette_rotate_and_scale_have_operator_defaults(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="palette-transform", mode="edit")
        controller.select(vertices_by_submesh={0: (0, 1)})
        before = tuple(controller.working_mesh().submeshes[0].vertices[:2])

        rotated = controller.apply_editor_action("transform_rotate")
        after_rotate = tuple(controller.working_mesh().submeshes[0].vertices[:2])
        scaled = controller.apply_editor_action("transform_scale")
        after_scale = tuple(controller.working_mesh().submeshes[0].vertices[:2])

        self.assertEqual("transform", rotated.action)
        self.assertEqual(((0, range(0, 2)),), rotated.changed_vertices_by_submesh)
        self.assertNotEqual(before, after_rotate)
        self.assertEqual("transform", scaled.action)
        self.assertEqual(((0, range(0, 2)),), scaled.changed_vertices_by_submesh)
        self.assertNotEqual(after_rotate, after_scale)

    def test_controller_runs_action_palette_and_returns_native_update(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="palette-native", mode="object")
        controller.select(vertices_by_submesh={0: (0,)})

        moved = controller.run_editor_action("transform_move", translate=(0.0, 0.0, 0.25))
        controller.select(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)})
        extruded = controller.run_editor_action("extrude", offset=(0.0, 0.0, 0.25))
        mode_after_extrude = controller.session_view().mode
        undone = controller.run_editor_action("undo")
        mode_after_undo = controller.session_view().mode

        self.assertEqual("transform", moved.edit_result.action)
        self.assertEqual(
            [0],
            _selection_i32_values(moved.native_update.vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"),
        )
        self.assertEqual("extrude", extruded.edit_result.action)
        self.assertEqual("edit", mode_after_extrude)
        self.assertGreater(len(_selection_i32_values(extruded.native_update.triangle_groups[0], "indices", "indices_binary")), 6)
        self.assertEqual("undo", undone.edit_result.action)
        self.assertEqual("object", mode_after_undo)
        self.assertEqual([0], [group["source_submesh_index"] for group in undone.native_update.triangle_groups])

    def test_run_editor_action_does_not_call_python_selection_overlay_update(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="palette-native-stop-event", mode="edit")
        controller.select(faces_by_submesh={0: (0,)})
        cancel_event = threading.Event()

        with patch("cdmw.ui.mesh_editor.controller.mesh_edit_selection_groups", side_effect=AssertionError("python selection overlay")) as patched:
            result = controller.run_editor_action("extrude", offset=(0.0, 0.0, 0.25), stop_event=cancel_event)

        self.assertEqual("extrude", result.edit_result.action)
        self.assertEqual(0, patched.call_count)
        self.assertTrue(result.native_update.triangle_groups)

    def test_controller_constrained_transform_returns_native_vertex_payload(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="palette-axis-snap", mode="edit")
        controller.select(vertices_by_submesh={0: (0, 3)})

        moved = controller.run_editor_action(
            "transform_move",
            translate=(0.26, 0.26, 0.26),
            axis="z",
            snap=0.25,
        )

        self.assertEqual("transform", moved.edit_result.action)
        self.assertEqual(0, moved.edit_result.changed_vertices_by_submesh[0][0])
        self.assertEqual(
            [0, 3],
            _selection_i32_values(
                moved.edit_result.changed_vertices_by_submesh[0][1],
                "changed_vertices",
                "changed_vertices_binary",
            ),
        )
        self.assertEqual("cdmw_mesh_core", moved.native_update.vertex_groups[0].get("preview_backend"))
        self.assertNotIn("source_vertex_indices", moved.native_update.vertex_groups[0])
        self.assertEqual(
            [0, 3],
            _selection_i32_values(moved.native_update.vertex_groups[0], "source_vertex_indices", "source_vertex_indices_binary"),
        )
        self.assertNotIn("positions", moved.native_update.vertex_groups[0])
        positions_binary = moved.native_update.vertex_groups[0]["positions_binary"]
        source_binary = moved.native_update.vertex_groups[0]["source_vertex_indices_binary"]
        positions_path = Path(positions_binary["path"])
        source_path = Path(source_binary["path"])
        self.assertTrue(positions_path.is_file())
        self.assertTrue(source_path.is_file())
        self.assertEqual(
            [-0.75, -0.75, 0.25, 0.75, 0.75, 0.25],
            list(struct.unpack("<6d", positions_path.read_bytes())),
        )
        self.assertEqual([0, 3], list(struct.unpack("<2i", source_path.read_bytes())))
        positions_path.unlink(missing_ok=True)
        source_path.unlink(missing_ok=True)

    def test_controller_rejects_unknown_action_palette_key(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="bad-action", mode="edit")

        with self.assertRaisesRegex(ValueError, "Unknown Mesh Editor action"):
            controller.apply_editor_action("not-real")

    def test_controller_rejects_legacy_display_cleanup_actions(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(build_synthetic_mesh(), session_id="legacy-display-cleanup", mode="edit")

        with self.assertRaisesRegex(RuntimeError, "legacy display-shape cleanup"):
            controller.apply("quadrangulate_display")
        with self.assertRaisesRegex(RuntimeError, "legacy display-shape cleanup"):
            controller.apply_command(MeshEditCommand("triangulate_display"))

    def test_static_replacement_adapter_routes_delete_through_mesh_editor_service(self) -> None:
        mesh = build_synthetic_mesh()

        result = apply_static_replacement_edit(mesh, "delete", faces_by_submesh={0: (0,)})

        self.assertEqual(1, result.removed_face_count)
        self.assertEqual((0,), result.affected_submesh_indices)
        self.assertTrue(result.edit_result.topology_changed)
        self.assertEqual(((3, 1),), result.edit_result.submesh_counts)
        self.assertEqual(2, len(mesh.submeshes[0].faces))
        self.assertEqual([0], [group["source_submesh_index"] for group in result.native_update.triangle_groups])

    def test_static_replacement_native_topology_uses_counts_without_hydrating_python_mesh(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        session = StaticReplacementMeshEditSession(session_id="static-no-hydrate")
        session.open(build_synthetic_mesh())
        try:
            with (
                patch(
                    "cdmw.services.mesh_service.export_native_mesh_editor_session_to_mesh",
                    side_effect=AssertionError("static replacement should not hydrate dirty native topology"),
                ),
            ):
                result = session.apply(
                    "subdivide",
                    vertices_by_submesh={0: (0,)},
                    max_faces_per_submesh=512,
                )
        finally:
            session.close()

        self.assertEqual(1.0, result.edit_result.metrics["python_apply_deferred"])
        self.assertGreater(result.added_face_count, 0)
        self.assertTrue(result.edit_result.submesh_counts)
        self.assertEqual([0], [group["source_submesh_index"] for group in result.native_update.triangle_groups])

    def test_static_replacement_native_result_without_counts_rejects_python_hydration(self) -> None:
        session = StaticReplacementMeshEditSession(session_id="static-missing-counts")
        session.open(build_synthetic_mesh())
        malformed_native_results = (
            MeshEditResult(
                action="transform",
                status="ok",
                revision=2,
                affected_submesh_indices=(0,),
                metrics={"native_apply_roundtrip_ms": 1.0},
            ),
            MeshEditResult(
                action="transform",
                status="ok",
                revision=2,
                affected_submesh_indices=(0,),
                metrics={"python_apply_deferred": 1.0},
            ),
            MeshEditResult(
                action="transform",
                status="ok",
                revision=2,
                affected_submesh_indices=(0,),
            ),
        )

        try:
            with (
                patch.object(session.controller, "native_update_for_result", return_value=MeshEditorNativeUpdate()),
                patch.object(session.controller, "working_mesh", side_effect=AssertionError("working_mesh should not hydrate")),
            ):
                for malformed_native_result in malformed_native_results:
                    with self.subTest(metrics=bool(malformed_native_result.metrics)):
                        with self.assertRaisesRegex(RuntimeError, "did not include submesh counts"):
                            session._result(
                                malformed_native_result,
                                before=session.submesh_counts,
                                selection=MeshEditSelection(vertices_by_submesh=((0, (0,)),)),
                            )
        finally:
            session.close()

    def test_static_replacement_adapter_brush_inflate_selected_face_changes_vertices(self) -> None:
        mesh = build_synthetic_mesh()

        result = apply_static_replacement_edit(
            mesh,
            "brush",
            faces_by_submesh={0: (0,)},
            mode="sculpt",
            tool="inflate",
            center=(0.0, 0.0, 0.0),
            radius=2.0,
            strength=1.0,
            amount=0.1,
            falloff="smooth",
        )

        changed = result.changed_vertices_by_submesh or {}
        self.assertEqual(range(0, 4), changed.get(0))
        self.assertEqual(1.0, result.edit_result.metrics["python_apply_deferred"])
        self.assertTrue(all(result.mesh.submeshes[0].vertices[index][2] == 0.0 for index in (0, 1, 2, 3)))
        self.assertTrue(all(mesh.submeshes[0].vertices[index][2] == 0.0 for index in (0, 1, 2, 3)))
        self.assertEqual([0], [group["source_submesh_index"] for group in result.native_update.vertex_groups])

    def test_static_replacement_adapter_syncs_deferred_native_edit_to_python_mesh(self) -> None:
        from cdmw.modding import mesh_native_core

        if not mesh_native_core.native_mesh_core_available():
            self.skipTest("native mesh core binary not available")

        mesh = build_synthetic_mesh()
        session = StaticReplacementMeshEditSession(session_id="static-sync-working-mesh")
        session.open(mesh)
        try:
            result = session.apply("transform", vertices_by_submesh={0: (0,)}, translate=(0.0, 0.0, 0.25))
            self.assertEqual(1.0, result.edit_result.metrics["python_apply_deferred"])
            self.assertEqual(0.0, mesh.submeshes[0].vertices[0][2])

            synced = session.sync_working_mesh()
        finally:
            session.close()

        self.assertIs(session.mesh, synced)
        self.assertEqual(((4, 2),), session.submesh_counts)
        self.assertAlmostEqual(0.25, synced.submeshes[0].vertices[0][2])

    def test_static_replacement_adapter_preserves_compact_changed_vertex_range(self) -> None:
        from cdmw.ui.mesh_editor.static_replacement_adapter import _static_result

        mesh = build_synthetic_mesh()
        edit_result = MeshEditResult(
            action="transform",
            status="ok",
            revision=2,
            affected_submesh_indices=(0,),
            changed_vertices_by_submesh=((0, range(0, 4)),),
        )

        result = _static_result(
            mesh,
            edit_result,
            MeshEditorNativeUpdate(),
            before=((4, 2),),
            selection=MeshEditSelection(),
        )

        self.assertEqual(range(0, 4), (result.changed_vertices_by_submesh or {})[0])

    def test_static_replacement_adapter_preserves_changed_vertices_binary_descriptor(self) -> None:
        from cdmw.ui.mesh_editor.static_replacement_adapter import _static_result

        descriptor = {
            "changed_vertices_binary": {
                "path": "changed.bin",
                "count": 2,
                "components": 1,
                "type": "i32",
            }
        }
        mesh = build_synthetic_mesh()
        edit_result = MeshEditResult(
            action="transform",
            status="ok",
            revision=2,
            affected_submesh_indices=(0,),
            changed_vertices_by_submesh=((0, descriptor),),  # type: ignore[arg-type]
        )

        result = _static_result(
            mesh,
            edit_result,
            MeshEditorNativeUpdate(),
            before=((4, 2),),
            selection=MeshEditSelection(),
        )

        self.assertEqual(descriptor, (result.changed_vertices_by_submesh or {})[0])

    def test_static_replacement_adapter_preserves_source_vertex_indices_descriptor(self) -> None:
        from cdmw.ui.mesh_editor.static_replacement_adapter import _static_result

        descriptor = {
            "source_vertex_indices_binary": {
                "path": "changed.bin",
                "count": 2,
                "components": 1,
                "type": "i32",
            }
        }
        mesh = build_synthetic_mesh()
        edit_result = MeshEditResult(
            action="transform",
            status="ok",
            revision=2,
            affected_submesh_indices=(0,),
            changed_vertices_by_submesh=((0, descriptor),),  # type: ignore[arg-type]
        )

        result = _static_result(
            mesh,
            edit_result,
            MeshEditorNativeUpdate(),
            before=((4, 2),),
            selection=MeshEditSelection(),
        )

        self.assertEqual(descriptor, (result.changed_vertices_by_submesh or {})[0])

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
