from __future__ import annotations

import unittest

from cdmw.domain.mesh import MESH_EDIT_ACTIONS, MESH_EDIT_MODES
from cdmw.ui.mesh_editor.actions import (
    MESH_EDITOR_ACTIONS,
    NATIVE_EDITOR_SESSION_COMMANDS,
    mesh_editor_actions_by_key,
    mesh_editor_actions_for_category,
    validate_mesh_editor_actions,
)


class MeshEditorActionsTests(unittest.TestCase):
    def test_action_palette_uses_valid_domain_commands_and_modes(self) -> None:
        validate_mesh_editor_actions()

        keys = [action.key for action in MESH_EDITOR_ACTIONS]
        commands = {action.command for action in MESH_EDITOR_ACTIONS}
        modes = {action.mode for action in MESH_EDITOR_ACTIONS if action.mode}
        shortcuts = [action.shortcut for action in MESH_EDITOR_ACTIONS]

        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(shortcuts), len(set(shortcuts)))
        self.assertTrue(all(action.icon_key for action in MESH_EDITOR_ACTIONS))
        self.assertTrue(all(action.shortcut for action in MESH_EDITOR_ACTIONS))
        self.assertTrue(all(action.tooltip for action in MESH_EDITOR_ACTIONS))
        self.assertTrue(commands.issubset(set(MESH_EDIT_ACTIONS) | {"undo", "redo"}))
        self.assertEqual(set(MESH_EDIT_MODES), modes)

    def test_action_palette_covers_v1_tool_surface(self) -> None:
        actions = mesh_editor_actions_by_key()

        for key in (
            "select_vertex",
            "select_edge",
            "select_face",
            "transform_move",
            "transform_rotate",
            "transform_scale",
            "brush_grab",
            "brush_smooth",
            "brush_inflate",
            "brush_pinch",
            "delete",
            "dissolve",
            "subdivide",
            "refine_smooth",
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
            "remove_doubles",
            "delete_loose_vertices",
            "compact_orphans",
            "fix_winding",
            "fill_holes",
            "recalculate_normals",
            "generate_tangents",
            "flip_normals",
            "sharpen_normals",
            "soften_normals",
            "weighted_normals",
            "copy_normals",
            "uv_transform",
            "uv_flip_u",
            "uv_flip_v",
            "uv_rotate_90",
            "uv_island_transform",
            "uv_normalize",
            "uv_align_u",
            "uv_align_v",
            "uv_planar_project",
            "uv_box_project",
            "uv_cylindrical_project",
            "uv_auto_unwrap",
            "uv_pack",
            "uv_snap_grid",
            "uv_snap_pixels",
            "material_assign",
            "material_copy",
            "undo",
            "redo",
        ):
            with self.subTest(key=key):
                self.assertIn(key, actions)

    def test_action_palette_groups_edge_topology_and_uv_tools(self) -> None:
        topology = {action.key: action for action in mesh_editor_actions_for_category("topology")}
        transform = {action.key: action for action in mesh_editor_actions_for_category("transform")}
        sculpt = {action.key: action for action in mesh_editor_actions_for_category("sculpt")}
        uv = {action.key: action for action in mesh_editor_actions_for_category("uv")}
        normals = {action.key: action for action in mesh_editor_actions_for_category("normals")}
        material = {action.key: action for action in mesh_editor_actions_for_category("material")}
        cleanup = {action.key: action for action in mesh_editor_actions_for_category("cleanup")}

        self.assertEqual("edge", topology["loop_cut"].selection_mode)
        self.assertEqual("edge", topology["edge_split"].selection_mode)
        self.assertEqual("edge", topology["bridge"].selection_mode)
        self.assertEqual("Ctrl+R", topology["loop_cut"].shortcut)
        self.assertEqual("Ctrl+Shift+E", topology["refine_smooth"].shortcut)
        self.assertEqual((("smooth_iterations", 2), ("smooth_strength", 0.5)), topology["refine_smooth"].params)
        self.assertEqual((("rotate", (0.0, 0.0, 15.0)),), transform["transform_rotate"].params)
        self.assertEqual((("scale", (1.1, 1.1, 1.1)),), transform["transform_scale"].params)
        self.assertEqual("edit", topology["extrude"].mode)
        self.assertEqual("edit", topology["loop_cut"].mode)
        self.assertEqual("edit", cleanup["remove_doubles"].mode)
        self.assertEqual("Ctrl+Alt+W", cleanup["remove_doubles"].shortcut)
        self.assertEqual("edit", uv["uv_transform"].mode)
        self.assertEqual("edit", material["material_assign"].mode)
        self.assertEqual("edit", material["material_copy"].mode)
        self.assertEqual((("flip_u", True),), uv["uv_flip_u"].params)
        self.assertEqual((("flip_v", True),), uv["uv_flip_v"].params)
        self.assertEqual((("rotate", 90.0), ("pivot", (0.5, 0.5))), uv["uv_rotate_90"].params)
        self.assertEqual((("uv_island", True),), uv["uv_island_transform"].params)
        self.assertEqual((("normalize", True),), uv["uv_normalize"].params)
        self.assertEqual((("align_u", "min"),), uv["uv_align_u"].params)
        self.assertEqual((("align_v", "min"),), uv["uv_align_v"].params)
        self.assertEqual((("projection", "planar"), ("plane", "xy")), uv["uv_planar_project"].params)
        self.assertEqual((("projection", "box"),), uv["uv_box_project"].params)
        self.assertEqual((("projection", "cylindrical"), ("axis", "z")), uv["uv_cylindrical_project"].params)
        self.assertEqual((("auto_uv", True), ("allow_topology_change", True)), uv["uv_auto_unwrap"].params)
        self.assertEqual((("pack", True),), uv["uv_pack"].params)
        self.assertEqual((("snap_grid", 0.125),), uv["uv_snap_grid"].params)
        self.assertEqual((("pixel_snap", True), ("texture_size", (1024.0, 1024.0))), uv["uv_snap_pixels"].params)
        self.assertEqual("Shift+U", uv["uv_flip_u"].shortcut)
        self.assertEqual("Alt+U", uv["uv_rotate_90"].shortcut)
        self.assertEqual("Ctrl+Alt+U", uv["uv_normalize"].shortcut)
        self.assertEqual("Ctrl+P", uv["uv_planar_project"].shortcut)
        self.assertEqual("Alt+P", uv["uv_pack"].shortcut)
        self.assertEqual("Ctrl+Alt+H", normals["sharpen_normals"].shortcut)
        self.assertEqual("Ctrl+Alt+Shift+S", normals["weighted_normals"].shortcut)
        self.assertEqual("Ctrl+Alt+Shift+N", normals["copy_normals"].shortcut)
        self.assertFalse(sculpt["brush_grab"].requires_selection)
        self.assertFalse(sculpt["brush_smooth"].requires_selection)
        self.assertFalse(cleanup["remove_doubles"].requires_selection)
        self.assertFalse(cleanup["delete_loose_vertices"].requires_selection)
        self.assertFalse(cleanup["fix_winding"].requires_selection)
        self.assertTrue(material["material_assign"].requires_selection)
        self.assertTrue(material["material_copy"].requires_selection)
        self.assertTrue(mesh_editor_actions_by_key()["recalculate_normals"].requires_selection)
        self.assertTrue(mesh_editor_actions_by_key()["generate_tangents"].requires_selection)
        self.assertTrue(mesh_editor_actions_by_key()["flip_normals"].requires_selection)
        self.assertTrue(mesh_editor_actions_by_key()["sharpen_normals"].requires_selection)
        self.assertTrue(mesh_editor_actions_by_key()["soften_normals"].requires_selection)
        self.assertTrue(mesh_editor_actions_by_key()["weighted_normals"].requires_selection)
        self.assertTrue(mesh_editor_actions_by_key()["copy_normals"].requires_selection)
        self.assertNotIn("triangulate_display", mesh_editor_actions_by_key())
        self.assertNotIn("quadrangulate_display", mesh_editor_actions_by_key())

    def test_native_unavailable_gate_covers_native_session_commands(self) -> None:
        expected = set(MESH_EDIT_ACTIONS) - {"set_mode", "select", "triangulate_display", "quadrangulate_display"}
        self.assertEqual(expected, set(NATIVE_EDITOR_SESSION_COMMANDS))
        self.assertNotIn("select", NATIVE_EDITOR_SESSION_COMMANDS)
        self.assertNotIn("triangulate_display", NATIVE_EDITOR_SESSION_COMMANDS)
        self.assertNotIn("quadrangulate_display", NATIVE_EDITOR_SESSION_COMMANDS)


if __name__ == "__main__":
    unittest.main()
