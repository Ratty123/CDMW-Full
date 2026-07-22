from __future__ import annotations

import unittest
from pathlib import Path

from tests.native_source_text import d3d11_preview_source
from tests.static_replacement_source_support import (
    static_replacement_callback_factory_source,
    static_replacement_mesh_edit_implementation_source,
    static_replacement_remaining_callback_source,
    static_replacement_ui_section_source,
)


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
            static_replacement_ui_section_source(ROOT),
            static_replacement_callback_factory_source(ROOT),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_mesh_edit_callbacks.py").read_text(encoding="utf-8"),
            static_replacement_mesh_edit_implementation_source(ROOT),
            static_replacement_remaining_callback_source(ROOT),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_combo_options.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_mesh_edit_state.py").read_text(encoding="utf-8"),
            (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_morph_slider_state.py").read_text(encoding="utf-8"),
        )
    )


def _resident_morph_source() -> str:
    paths = (
        ROOT / "cdmw" / "services" / "mesh_service_morph.py",
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_commands.py",
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_payloads.py",
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_protocol.py",
        ROOT / "native" / "cdmw_mesh_core" / "src" / "owners" / "session_morph_01.cpp",
        ROOT / "native" / "cdmw_mesh_core" / "src" / "owners" / "session_state_05.cpp",
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.MorphRefit.cs",
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.MutationAuthority.cs",
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.Protocol.cs",
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "Program.cs",
    )
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


class MeshMorphSliderUiSourceGuardTests(unittest.TestCase):
    def test_existing_edit_mesh_exposes_resident_morph_refit_and_removes_target_import_controls(self) -> None:
        legacy_source = _mesh_edit_source()
        resident_source = _resident_morph_source()

        self.assertIn('StyledButton("▾  Morph & Refit"', resident_source)
        self.assertIn('LabeledControl("Definition profile", _morphProfile)', resident_source)
        self.assertIn('LabeledControl("Value preset", _morphPreset)', resident_source)
        self.assertIn('StyledActionButton("Set Driver"', resident_source)
        self.assertIn('StyledActionButton("Bind Selected Parts"', resident_source)
        self.assertIn('StyledActionButton("Clear Refit"', resident_source)
        self.assertIn('StyledActionButton("Reset All"', resident_source)
        self.assertIn('StyledActionButton("Bake"', resident_source)
        self.assertIn('WriteCommandRequest("morph_author_definition"', resident_source)
        self.assertIn('"morph_delete_definition"', resident_source)
        self.assertIn("RequestFinishEditMesh", resident_source)
        self.assertNotIn("import_body_slider_profile(", legacy_source)
        self.assertNotIn("import_single_morph_slider_profile(", legacy_source)
        self.assertNotIn("morph_slider_import_action =", legacy_source)
        self.assertNotIn("morph_slider_add_action =", legacy_source)
        self.assertNotIn("_state.mesh_edit_layout_page.addWidget(_state.morph_slider_group, 0)", legacy_source)

    def test_morph_refit_uses_mesh_service_and_resident_cpp_without_renderer_restart(self) -> None:
        source = _resident_morph_source()

        self.assertIn("class MeshMorphServiceMixin", source)
        self.assertIn('native_mesh_editor_session_command(', source)
        self.assertIn('"morph_upload"', source)
        self.assertIn("mesh_editor_recompose_morph", source)
        self.assertIn("mesh_editor_add_refit_layer", source)
        self.assertIn("mesh_editor_morph_topology_blocked", source)
        self.assertIn('command == "morph_bake" || command == "morph_finish"', source)
        self.assertIn('case "morph_state_update":', source)
        self.assertIn('"morph_state_update_ack"', source)
        self.assertIn("requestId <= _morphStateRequestId", source)
        self.assertIn('payload["preserve_selection"] = definition.HasValue', source)
        self.assertIn('"morph_state_update" => $"{message.EventName}|{sessionId}"', source)
        self.assertNotIn("Process.Start", (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.MorphRefit.cs").read_text(encoding="utf-8"))

    def test_native_vertex_dots_use_instanced_overlay_and_cached_screen_vertices(self) -> None:
        native_source = d3d11_preview_source()

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
