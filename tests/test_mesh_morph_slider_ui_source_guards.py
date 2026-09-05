from __future__ import annotations

import unittest
from pathlib import Path

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
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.MorphAuthoring.cs",
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "MorphAuthorWizard.cs",
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.MutationAuthority.cs",
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.Protocol.cs",
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "Program.cs",
    )
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def _resident_morph_form_source() -> str:
    return "\n".join(
        (ROOT / "tools" / "dotnet_mesh_editor_experiment" / name).read_text(encoding="utf-8")
        for name in ("ExperimentForm.MorphRefit.cs", "ExperimentForm.MorphAuthoring.cs")
    )


def _resident_controls_source() -> str:
    return (
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.Controls.cs"
    ).read_text(encoding="utf-8")


class MeshMorphSliderUiSourceGuardTests(unittest.TestCase):

    def test_existing_edit_mesh_exposes_resident_morph_refit_and_removes_target_import_controls(self) -> None:
        legacy_source = _mesh_edit_source()

        self.assertNotIn("import_body_slider_profile(", legacy_source)
        self.assertNotIn("import_single_morph_slider_profile(", legacy_source)
        self.assertNotIn("morph_slider_import_action =", legacy_source)
        self.assertNotIn("morph_slider_add_action =", legacy_source)
        self.assertNotIn("_state.mesh_edit_layout_page.addWidget(_state.morph_slider_group, 0)", legacy_source)







if __name__ == "__main__":
    unittest.main()
