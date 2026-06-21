from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _mesh_edit_source() -> str:
    return "\n".join(
        (
            (ROOT / "cdmw" / "ui" / "shell" / "app_window.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_shell.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_open.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_setup.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_state_callbacks.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_transform.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_base.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_state_a.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_state_b.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_callbacks.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_ui_sections.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_callback_factories.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_mesh_edit_callbacks.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_remaining_callbacks.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_combo_options.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_mesh_edit_state.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_morph_slider_state.py").read_text(encoding="utf-8"),
        )
    )


class MeshMorphSliderUiSourceGuardTests(unittest.TestCase):
    def test_mesh_editing_tab_exposes_morph_slider_controls(self) -> None:
        source = _mesh_edit_source()

        self.assertIn("morph_slider_title_label = QLabel(_morph_slider_title_text_helper())", source)
        self.assertIn("morph_slider_create_button = QPushButton(_morph_slider_create_action_text_helper())", source)
        self.assertIn("morph_slider_manage_button = QPushButton(_morph_slider_manage_action_text_helper())", source)
        self.assertIn("morph_slider_import_action = morph_slider_manage_menu.addAction(_morph_slider_import_action_text_helper())", source)
        self.assertIn("morph_slider_add_action = morph_slider_manage_menu.addAction(_morph_slider_add_target_action_text_helper())", source)
        self.assertIn("morph_slider_reset_button = QPushButton(_morph_slider_reset_action_text_helper())", source)
        self.assertIn("reset_button = QPushButton(row_state.reset_text)", source)
        self.assertIn("def morph_slider_row_reset_action_text() -> str:", source)
        self.assertIn("morph_slider_bake_button = QPushButton(_morph_slider_bake_action_text_helper())", source)
        self.assertIn("_populate_combo_options_helper(mesh_edit_selection_mode_combo, MESH_EDIT_SELECTION_MODE_OPTIONS)", source)
        self.assertIn('("Lasso Select", "lasso")', source)
        self.assertIn('("Rectangle Select", "rectangle")', source)
        self.assertIn('mesh_edit_grow_selection_button = QPushButton(mesh_edit_action_control_text["grow_selection"])', source)
        self.assertIn('mesh_edit_shrink_selection_button = QPushButton(mesh_edit_action_control_text["shrink_selection"])', source)
        self.assertIn('mesh_edit_smooth_selection_button = QPushButton(mesh_edit_action_control_text["smooth_selection"])', source)
        self.assertIn("morph_slider_profile_root = self.settings_file_path.parent / \"mesh_slider_profiles\"", source)
        self.assertIn("load_morph_slider_profiles(", source)
        self.assertIn("create_region_volume_slider_profile(", source)
        self.assertIn("import_body_slider_profile(", source)
        self.assertIn("import_single_morph_slider_profile(", source)
        self.assertIn("load_morph_slider_delta(", source)
        self.assertIn("apply_morph_slider_values(", source)
        self.assertIn("mesh_edit_layout_page.addWidget(morph_slider_group, 0)", source)

    def test_morph_sliders_are_layered_and_export_through_edited_source_mesh(self) -> None:
        main_source = _mesh_edit_source()
        static_source = "\n".join(
            (
                (ROOT / "cdmw" / "modding" / "static_mesh_replacer.py").read_text(encoding="utf-8"),
                (ROOT / "cdmw" / "modding" / "static_mesh_types.py").read_text(encoding="utf-8"),
                (ROOT / "cdmw" / "modding" / "static_mesh_analysis.py").read_text(encoding="utf-8"),
                (ROOT / "cdmw" / "modding" / "static_mesh_runtime_builder.py").read_text(encoding="utf-8"),
            )
        )

        self.assertIn("morph_slider_post_edit_deltas", main_source)
        self.assertIn("def _morph_slider_capture_post_edit_deltas", main_source)
        self.assertIn("def _morph_slider_apply_to_working_mesh", main_source)
        self.assertIn("Bake or reset Morph Sliders before removing faces.", main_source)
        self.assertIn("_morph_slider_mark_topology_changed", main_source)
        self.assertIn("edited_source_mesh = clone_mesh_for_editing(replacement_mesh_for_mapping)", main_source)
        self.assertIn("edited_source_mesh: ParsedMesh | None = None", static_source)
        self.assertIn("def _replacement_mesh_from_options", static_source)

    def test_native_vertex_dots_use_instanced_overlay_and_cached_screen_vertices(self) -> None:
        native_source = (ROOT / "native" / "cdmw_d3d11_preview" / "src" / "main.cpp").read_text(encoding="utf-8")

        self.assertIn("struct MeshEditScreenVertexCache", native_source)
        self.assertIn("mesh_edit_screen_vertices_for_view", native_source)
        self.assertIn("draw_mesh_edit_vertex_dots_instanced", native_source)
        self.assertIn("DrawInstanced", native_source)
        self.assertIn('std::string selection_mode = "brush";', native_source)
        self.assertIn('mesh_edit_.selection_mode == "lasso"', native_source)
        self.assertIn('mesh_edit_.selection_mode == "rectangle"', native_source)
        self.assertIn('command == "set_mesh_edit_selection"', native_source)
        dot_draw_start = native_source.index("void draw_mesh_edit_vertex_dots_instanced")
        dot_draw_end = native_source.index("void draw_mesh_edit_overlay", dot_draw_start)
        dot_draw_body = native_source[dot_draw_start:dot_draw_end]
        self.assertNotIn("add_disc", dot_draw_body)


if __name__ == "__main__":
    unittest.main()
