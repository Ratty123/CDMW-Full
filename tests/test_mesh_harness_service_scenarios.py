from __future__ import annotations

from tests.mesh_harness_support import (
    unittest,
    ASSET_AUTHORING_MESH_HEALTH_SCHEMA,
    ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA,
    ASSET_AUTHORING_TANGENT_REPORT_SCHEMA,
    ASSET_AUTHORING_UV_REPORT_SCHEMA,
    MESH_EDITOR_ACTIONS,
    MESH_EDIT_ACTIONS,
    Path,
    json,
    run_scenario,
    tempfile,
)


def _assert_edge_face_topology(test: unittest.TestCase, edge_face_topology: dict[str, object]) -> None:
    test.assertTrue(edge_face_topology["ok"])
    test.assertEqual(3, edge_face_topology["copied_vertex_count"])
    test.assertEqual(1, edge_face_topology["copied_face_count"])
    test.assertEqual([[0, 1, 2]], edge_face_topology["copied_faces"])
    test.assertEqual(2, edge_face_topology["mirror"]["submesh_count"])
    test.assertEqual(3, edge_face_topology["mirror"]["vertex_count"])
    test.assertEqual(1, edge_face_topology["mirror"]["face_count"])
    test.assertEqual([[0, 2, 1]], edge_face_topology["mirror"]["faces"])
    test.assertEqual([[0.75, -0.75, 0.0], [-0.75, -0.75, 0.0], [0.75, 0.75, 0.0]], edge_face_topology["mirror"]["vertices"])
    test.assertEqual(3, edge_face_topology["delete"]["vertex_count"])
    test.assertEqual(1, edge_face_topology["delete"]["face_count"])
    test.assertEqual([[0, 2, 1]], edge_face_topology["delete"]["faces"])
    test.assertEqual(4, edge_face_topology["dissolve"]["vertex_count"])
    test.assertEqual(1, edge_face_topology["dissolve"]["face_count"])
    test.assertEqual([[1, 3, 2]], edge_face_topology["dissolve"]["faces"])
    test.assertEqual(4, edge_face_topology["internal_dissolve"]["vertex_count"])
    test.assertEqual(2, edge_face_topology["internal_dissolve"]["face_count"])
    test.assertEqual([[0, 1, 3], [0, 3, 2]], edge_face_topology["internal_dissolve"]["faces"])
    test.assertEqual(7, edge_face_topology["subdivide"]["vertex_count"])
    test.assertEqual(5, edge_face_topology["subdivide"]["face_count"])
    test.assertEqual([1, 3, 2], edge_face_topology["subdivide"]["faces"][-1])
    test.assertEqual(5, edge_face_topology["loop_cut_two_edges"]["vertex_count"])
    test.assertEqual(3, edge_face_topology["loop_cut_two_edges"]["face_count"])
    test.assertEqual([[3, 1, 4], [0, 3, 4], [0, 4, 2]], edge_face_topology["loop_cut_two_edges"]["faces"])
    test.assertEqual({"0": [3, 4]}, edge_face_topology["loop_cut_two_edges"]["changed_vertices"])
    test.assertEqual(5, edge_face_topology["loop_cut_multi"]["vertex_count"])
    test.assertEqual(3, edge_face_topology["loop_cut_multi"]["face_count"])
    test.assertEqual([[0, 3, 2], [3, 4, 2], [4, 1, 2]], edge_face_topology["loop_cut_multi"]["faces"])
    test.assertEqual({"0": [3, 4]}, edge_face_topology["loop_cut_multi"]["changed_vertices"])
    test.assertAlmostEqual(-0.25, edge_face_topology["loop_cut_multi"]["vertices"][3][0], places=6)
    test.assertAlmostEqual(0.25, edge_face_topology["loop_cut_multi"]["vertices"][4][0], places=6)
    test.assertAlmostEqual(1.0, edge_face_topology["loop_cut_multi"]["uvs"][3][1], places=6)
    test.assertAlmostEqual(1.0, edge_face_topology["loop_cut_multi"]["uvs"][4][1], places=6)
    test.assertEqual(4, edge_face_topology["loop_cut_factor"]["vertex_count"])
    test.assertEqual(2, edge_face_topology["loop_cut_factor"]["face_count"])
    test.assertEqual({"0": [3]}, edge_face_topology["loop_cut_factor"]["changed_vertices"])
    test.assertAlmostEqual(-0.375, edge_face_topology["loop_cut_factor"]["vertices"][3][0], places=6)
    test.assertAlmostEqual(0.25, edge_face_topology["loop_cut_factor"]["uvs"][3][0], places=6)
    test.assertEqual([[0, 3, 2], [3, 1, 2]], edge_face_topology["loop_cut_factor"]["faces"])
    test.assertEqual(1, edge_face_topology["split"]["submesh_count"])
    test.assertEqual(6, edge_face_topology["split"]["vertex_count"])
    test.assertEqual(2, edge_face_topology["split"]["face_count"])
    test.assertEqual([[0, 4, 5], [1, 3, 2]], edge_face_topology["split"]["faces"])
    test.assertEqual({"0": [4, 5]}, edge_face_topology["split"]["changed_vertices"])
    test.assertEqual(2, edge_face_topology["separate"]["submesh_count"])
    test.assertEqual(1, edge_face_topology["separate"]["source_face_count"])
    test.assertEqual(1, edge_face_topology["separate"]["moved_face_count"])
    test.assertEqual(3, edge_face_topology["fill"]["face_count"])
    test.assertEqual([0, 1, 3], edge_face_topology["fill"]["faces"][-1])
    test.assertEqual(2, edge_face_topology["quad_fill"]["face_count"])
    test.assertEqual([[0, 1, 3], [0, 3, 2]], edge_face_topology["quad_fill"]["faces"])
    test.assertEqual(2, edge_face_topology["face_fill"]["face_count"])
    test.assertEqual(2, edge_face_topology["existing_fill"]["face_count"])
    test.assertEqual(8, edge_face_topology["extrude"]["vertex_count"])
    test.assertEqual(12, edge_face_topology["extrude"]["face_count"])
    test.assertEqual({"0": [4, 5, 6, 7]}, edge_face_topology["extrude"]["changed_vertices"])
    test.assertEqual(6, edge_face_topology["edge_extrude"]["vertex_count"])
    test.assertEqual(2, edge_face_topology["edge_extrude"]["face_count"])
    test.assertEqual([[0, 1, 5], [0, 5, 4]], edge_face_topology["edge_extrude"]["faces"])
    test.assertEqual({"0": [4, 5]}, edge_face_topology["edge_extrude"]["changed_vertices"])
    test.assertAlmostEqual(0.2, edge_face_topology["edge_extrude"]["vertices"][4][2], places=6)
    test.assertAlmostEqual(0.2, edge_face_topology["edge_extrude"]["vertices"][5][2], places=6)
    test.assertEqual(edge_face_topology["edge_extrude"]["uvs"][0], edge_face_topology["edge_extrude"]["uvs"][4])
    test.assertEqual(edge_face_topology["edge_extrude"]["uvs"][1], edge_face_topology["edge_extrude"]["uvs"][5])
    test.assertFalse(edge_face_topology["non_edge_extrude"]["command"]["topology_changed"])
    test.assertEqual([], edge_face_topology["non_edge_extrude"]["command"]["affected_submesh_indices"])
    test.assertEqual(4, edge_face_topology["non_edge_extrude"]["vertex_count"])
    test.assertEqual(2, edge_face_topology["non_edge_extrude"]["face_count"])
    test.assertEqual(8, edge_face_topology["inset"]["vertex_count"])
    test.assertEqual(10, edge_face_topology["inset"]["face_count"])
    test.assertEqual({"0": [4, 5, 6, 7]}, edge_face_topology["inset"]["changed_vertices"])
    test.assertEqual(4, edge_face_topology["inset_zero"]["vertex_count"])
    test.assertEqual(2, edge_face_topology["inset_zero"]["face_count"])
    test.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["inset_zero"]["faces"])
    test.assertFalse(edge_face_topology["inset_zero"]["command"]["topology_changed"])
    test.assertEqual(4, edge_face_topology["merge"]["vertex_count"])
    test.assertEqual(2, edge_face_topology["merge"]["face_count"])
    test.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["merge"]["faces"])
    test.assertEqual(4, edge_face_topology["weld"]["vertex_count"])
    test.assertEqual(2, edge_face_topology["weld"]["face_count"])
    test.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["weld"]["faces"])
    test.assertEqual(2, edge_face_topology["bridge"]["face_count"])
    test.assertEqual([[0, 1, 3], [0, 3, 2]], edge_face_topology["bridge"]["faces"])
    test.assertEqual(2, edge_face_topology["filled_bridge"]["face_count"])
    test.assertEqual(2, edge_face_topology["face_flip_normals"]["face_count"])
    test.assertEqual([], edge_face_topology["empty_recalculate_normals"]["command"]["affected_submesh_indices"])
    test.assertEqual([[0.0, 0.0, -1.0]] * 4, edge_face_topology["empty_recalculate_normals"]["normals"])
    test.assertEqual([0], edge_face_topology["source_recalculate_normals"]["command"]["affected_submesh_indices"])
    test.assertEqual([[0.0, 0.0, 1.0]] * 4, edge_face_topology["source_recalculate_normals"]["normals"])
    test.assertEqual([[0, 2, 1], [1, 3, 2]], edge_face_topology["face_flip_normals"]["faces"])
    test.assertFalse(edge_face_topology["face_flip_normals"]["command"]["topology_changed"])
    test.assertEqual(2, edge_face_topology["empty_flip_normals"]["face_count"])
    test.assertEqual([[0, 1, 2], [1, 3, 2]], edge_face_topology["empty_flip_normals"]["faces"])
    test.assertFalse(edge_face_topology["empty_flip_normals"]["command"]["topology_changed"])
    test.assertEqual([], edge_face_topology["empty_flip_normals"]["command"]["affected_submesh_indices"])
    test.assertEqual(2, edge_face_topology["source_flip_normals"]["face_count"])
    test.assertEqual([[0, 2, 1], [1, 2, 3]], edge_face_topology["source_flip_normals"]["faces"])
    test.assertFalse(edge_face_topology["source_flip_normals"]["command"]["topology_changed"])
    test.assertEqual([0], edge_face_topology["source_flip_normals"]["command"]["affected_submesh_indices"])


def _assert_coverage_and_palette(test: unittest.TestCase, result: dict[str, object]) -> None:
    coverage = result["service"]["coverage"]
    test.assertTrue(coverage["ok"])
    test.assertEqual([], coverage["missing_actions"])
    test.assertEqual(set(MESH_EDIT_ACTIONS) | {"undo", "redo"}, set(coverage["covered_actions"]))
    test.assertEqual(["pac", "pam", "pamlod"], coverage["covered_formats"])
    palette = result["service"]["palette"]
    test.assertTrue(palette["ok"])
    test.assertEqual([], palette["missing_actions"])
    test.assertEqual({action.key for action in MESH_EDITOR_ACTIONS}, set(palette["covered_actions"]))
    commands = {command["key"]: command for command in palette["commands"]}
    test.assertGreater(commands["select_face"]["selection_group_count"], 0)
    test.assertTrue(commands["select_face"]["selection_refresh"])
    test.assertTrue(commands["duplicate"]["selection_refresh"])
    test.assertTrue(commands["undo"]["selection_refresh"])
    for action in (
        "uv_flip_u",
        "uv_normalize",
        "uv_align_u",
        "uv_align_v",
        "uv_planar_project",
        "uv_box_project",
        "uv_cylindrical_project",
        "uv_pack",
        "uv_snap_grid",
        "uv_snap_pixels",
    ):
        test.assertGreater(commands[action]["vertex_update_group_count"], 0)
    test.assertGreater(commands["material_assign"]["material_override_group_count"], 0)
    test.assertGreater(commands["material_copy"]["material_override_group_count"], 0)


class MeshHarnessServiceScenarioTests(unittest.TestCase):
    def test_asset_authoring_mesh_health_scenario_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("asset-authoring-mesh-health", output_dir)
            report = json.loads(Path(result["asset_authoring"]["report_path"]).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(ASSET_AUTHORING_MESH_HEALTH_SCHEMA, report["schema"])
        self.assertTrue(report["topology"]["topology_changed"])
        self.assertGreaterEqual(report["totals"]["duplicate_vertices"], 1)
        self.assertGreaterEqual(report["totals"]["degenerate_faces"], 1)
        self.assertGreaterEqual(report["totals"]["invalid_indices"], 1)

    def test_asset_authoring_uv_report_scenario_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("asset-authoring-uv-report", output_dir)
            report = json.loads(Path(result["asset_authoring"]["report_path"]).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(ASSET_AUTHORING_UV_REPORT_SCHEMA, report["schema"])
        self.assertGreaterEqual(report["island_count"], 1)
        self.assertTrue(report["uv_bounds"]["available"])

    def test_asset_authoring_tangent_report_scenario_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("asset-authoring-tangent-report", output_dir)
            report = json.loads(Path(result["asset_authoring"]["report_path"]).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(ASSET_AUTHORING_TANGENT_REPORT_SCHEMA, report["schema"])
        self.assertEqual("generate_tangents", report["operation"])
        self.assertGreaterEqual(report["before"]["totals"]["missing_tangent_parts"], 1)
        self.assertGreaterEqual(report["totals"]["complete_tangent_parts"], 1)
        self.assertEqual("ok", report["command"]["status"])

    def test_asset_authoring_openimageio_report_scenario_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("asset-authoring-openimageio-report", output_dir)
            report = json.loads(Path(result["asset_authoring"]["report_path"]).read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA, report["schema"])
        self.assertEqual("helper_unavailable", report["status"])
        self.assertTrue(report["openimageio_source_candidate"])
        self.assertFalse(report["can_convert"])
        self.assertEqual("helper_unavailable", report["metadata_command"]["status"])
        self.assertEqual("helper_unavailable", report["convert_command"]["status"])

    def test_service_smoke_writes_result_json_without_starting_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result = run_scenario("service-smoke", output_dir)

            self.assertTrue(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            evidence_report = json.loads((output_dir / "evidence_report.json").read_text(encoding="utf-8"))
            self.assertEqual("cdmw_mesh_editor_evidence_report_v2", evidence_report["schema"])
            self.assertEqual("service-smoke", evidence_report["scenario"])
            self.assertIn("preview-only", evidence_report["state_labels"])
            self.assertIn(".paseqc", evidence_report["corpus_manifest"]["formats"])
            self.assertTrue(any(row["feature"] == "Direct archive mutation" and row["state"] == "blocked" for row in evidence_report["feature_status_rows"]))
            self.assertEqual("service-smoke", result["scenario"])
            self.assertGreater(result["service"]["session"]["face_count"], 2)
            selection_operations = result["service"]["selection_operations"]
            self.assertTrue(selection_operations["ok"])
            self.assertEqual({"0": [0, 3]}, selection_operations["added"]["vertices_by_submesh"])
            self.assertEqual({"0": [[1, 2]]}, selection_operations["subtracted"]["edges_by_submesh"])
            self.assertEqual({"0": [2]}, selection_operations["toggled"]["vertices_by_submesh"])
            self.assertEqual({}, selection_operations["toggled"]["faces_by_submesh"])
            selection_pruning = result["service"]["selection_pruning"]
            self.assertTrue(selection_pruning["ok"])
            self.assertEqual({"0": [[0, 1]]}, selection_pruning["malformed"]["edges_by_submesh"])
            self.assertEqual({}, selection_pruning["malformed"]["faces_by_submesh"])
            self.assertEqual({"0": [[0, 3]]}, selection_pruning["loose_edge"]["edges_by_submesh"])
            history_selection = result["service"]["history_selection"]
            self.assertTrue(history_selection["ok"])
            self.assertEqual([1], history_selection["before_undo"]["source_indices"])
            self.assertEqual({}, history_selection["after_undo"]["faces_by_submesh"])
            self.assertEqual([], history_selection["after_undo"]["source_indices"])
            self.assertEqual(1, history_selection["submesh_count_after_undo"])
            history_context = result["service"]["history_context"]
            self.assertTrue(history_context["ok"])
            self.assertEqual({"0": [0]}, history_context["after_undo"]["faces_by_submesh"])
            self.assertEqual({"1": [0]}, history_context["after_redo"]["faces_by_submesh"])
            self.assertEqual([1], history_context["after_redo"]["source_indices"])
            self.assertEqual("object", history_context["mode_restore"]["after_undo"])
            self.assertEqual("edit", history_context["mode_restore"]["after_redo"])
            uv_operations = result["service"]["uv_operations"]
            self.assertTrue(uv_operations["ok"])
            self.assertEqual({"0": [1, 2]}, uv_operations["pivot_flip"]["changed_vertices"])
            self.assertEqual([-0.5, -0.5], uv_operations["pivot_flip"]["uvs"][1])
            self.assertEqual([0.5, 0.5], uv_operations["pivot_flip"]["uvs"][2])
            transform_targets = result["service"]["transform_targets"]
            self.assertTrue(transform_targets["ok"])
            self.assertEqual([], transform_targets["empty"]["command"]["affected_submesh_indices"])
            self.assertEqual([-0.75, -0.75, 0.0], transform_targets["empty"]["vertices"][0])
            self.assertEqual([], transform_targets["stale_edge"]["command"]["affected_submesh_indices"])
            self.assertEqual([-0.75, -0.75, 0.0], transform_targets["stale_edge"]["vertices"][0])
            self.assertEqual([], transform_targets["non_edge"]["command"]["affected_submesh_indices"])

            self.assertEqual([-0.75, -0.75, 0.0], transform_targets["non_edge"]["vertices"][0])
            self.assertEqual([0.75, 0.75, 0.0], transform_targets["non_edge"]["vertices"][3])
            self.assertEqual([-0.75, -0.75, 0.5], transform_targets["source"]["vertices"][0])
            topology_targets = result["service"]["topology_targets"]
            self.assertTrue(topology_targets["ok"])
            self.assertEqual([], topology_targets["duplicate_empty"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["duplicate_empty"]["submesh_count"])
            self.assertEqual([], topology_targets["duplicate_invalid_face"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["duplicate_invalid_face"]["submesh_count"])
            self.assertEqual([], topology_targets["duplicate_malformed_face"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["duplicate_malformed_face"]["submesh_count"])
            self.assertEqual([], topology_targets["mirror_empty"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["mirror_empty"]["submesh_count"])
            self.assertEqual([], topology_targets["mirror_invalid_face"]["command"]["affected_submesh_indices"])
            self.assertEqual(1, topology_targets["mirror_invalid_face"]["submesh_count"])
            self.assertEqual([1], topology_targets["duplicate_source"]["command"]["affected_submesh_indices"])
            self.assertEqual([1], topology_targets["mirror_source"]["command"]["affected_submesh_indices"])
            material_operations = result["service"]["material_operations"]
            self.assertTrue(material_operations["ok"])
            self.assertTrue(material_operations["face_assign"]["command"]["topology_changed"])
            self.assertEqual(["harness_material", "face_material"], [submesh["material"] for submesh in material_operations["face_assign"]["submeshes"]])
            self.assertEqual({"roughness": 0.4}, material_operations["face_assign"]["submeshes"][1]["overrides"])
            self.assertTrue(material_operations["face_copy"]["command"]["topology_changed"])
            self.assertEqual(["harness_material", "harness_material_b", "harness_material"], [submesh["material"] for submesh in material_operations["face_copy"]["submeshes"]])
            self.assertEqual({"roughness": 0.2, "metalness": 0.6}, material_operations["face_copy"]["submeshes"][2]["overrides"])
            plain_reset = material_operations["plain_assign_reset"]
            self.assertEqual("plain_material", plain_reset["material"])
            self.assertFalse(plain_reset["has_route_metadata"])
            self.assertEqual({}, plain_reset["overrides"])
            _assert_edge_face_topology(self, result["service"]["edge_face_topology"])
            _assert_coverage_and_palette(self, result)
