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
    def test_empty_morph_selectors_start_without_an_invalid_selected_index(self) -> None:
        source = _resident_controls_source()

        self.assertIn("combo.Items.Count == 0", source)
        self.assertIn("? -1", source)
        self.assertIn(": Math.Clamp(selectedIndex, 0, combo.Items.Count - 1)", source)
        self.assertNotIn("Math.Max(0, combo.Items.Count - 1)", source)

    def test_existing_edit_mesh_exposes_resident_morph_refit_and_removes_target_import_controls(self) -> None:
        legacy_source = _mesh_edit_source()
        resident_source = _resident_morph_source()

        self.assertIn('StyledButton("▾  Morph & Refit"', resident_source)
        self.assertIn('LabeledControl("Profile", _morphProfile)', resident_source)
        self.assertIn('LabeledControl("Value preset", _morphPreset)', resident_source)
        self.assertIn('StyledActionButton("1. Set Selected Driver Parts"', resident_source)
        self.assertIn('StyledActionButton("2. Bind Selected Garment Parts"', resident_source)
        self.assertIn('StyledActionButton("Clear Refit"', resident_source)
        self.assertIn('StyledActionButton("Reset"', resident_source)
        self.assertIn('StyledActionButton("Bake"', resident_source)
        self.assertIn('Name = "MorphProfileWizard"', resident_source)
        self.assertIn('"1. Profile", "2. Parts", "3. Deformation", "4. Preview & Save"', resident_source)
        self.assertIn('Name = "MorphWizardPartList"', resident_source)
        self.assertIn('Name = "MorphWizardUseMeshSelection"', resident_source)
        self.assertIn('Name = "MorphWizardReplaceSelection"', resident_source)
        self.assertNotIn('MorphWizardRefreshPartsButton', resident_source)
        self.assertIn('Text = "Save Profile"', resident_source)
        self.assertIn('("morph_author_definition", MorphAuthorPayload(', resident_source)
        self.assertIn('"morph_delete_definition"', resident_source)
        self.assertIn("_profileId.ReadOnly = true", resident_source)
        self.assertIn("_definitionId.ReadOnly = true", resident_source)
        self.assertIn("Saving a profile never bakes the mesh", resident_source)
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
        self.assertIn('payload["preserve_selection"] = preserveExistingSelection', source)
        self.assertIn('["preserve_selection"] = true', source)
        self.assertIn('dialog.PreserveExistingSelection', source)
        self.assertIn("SelectedMorphParts", source)
        self.assertIn('Name = "MorphRefitEnabledCheckBox"', source)
        self.assertIn('Name = "MorphRefitModeSelector"', source)
        self.assertIn('Name = "MorphRefitIntensityNumeric"', source)
        self.assertIn('Name = "MorphRefitClearanceNumeric"', source)
        self.assertIn('RequestMorphUiCommand("morph_configure_refit"', source)
        self.assertIn("BeginMorphWizardCommandSequence", source)
        self.assertIn('"morph_state_update" => $"{message.EventName}|{sessionId}"', source)
        self.assertNotIn("Process.Start", (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.MorphRefit.cs").read_text(encoding="utf-8"))

    def test_morph_wizard_serializes_correlated_preview_and_save_commands(self) -> None:
        source = _resident_morph_form_source()
        preview_start = source.index("    private void PreviewMorphAuthorDialog(")
        preview_end = source.index("    private static Dictionary<string, object?> MorphWizardChangePayload(", preview_start)
        preview_body = source[preview_start:preview_end]
        sequence_start = source.index("    private bool BeginMorphWizardCommandSequence(")
        sequence_end = source.index("    private static Dictionary<string, object?> MorphAuthorPayload(", sequence_start)
        sequence_body = source[sequence_start:sequence_end]

        self.assertIn('commands.Add(("morph_author_definition",', preview_body)
        self.assertIn('commands.Add(("morph_change",', preview_body)
        self.assertIn("BeginMorphWizardCommandSequence(", preview_body)
        self.assertNotIn("WriteCommandRequest(", preview_body)
        self.assertIn("_morphWizardSequenceActive = true", sequence_body)
        self.assertIn("_morphWizardCommandQueue.Enqueue", sequence_body)
        self.assertIn("_morphWizardCommandRequestId = WriteCommandRequest(command, payload)", sequence_body)
        self.assertIn("BeginInvoke((Action)SendNextMorphWizardCommand)", source)
        self.assertIn("CompleteMorphWizardCommandSequence(accepted: false)", source)

    def test_new_profile_cancel_deletes_the_temporary_profile_and_edit_preserves_scope(self) -> None:
        source = _resident_morph_form_source()
        wizard_source = (
            ROOT / "tools" / "dotnet_mesh_editor_experiment" / "MorphAuthorWizard.cs"
        ).read_text(encoding="utf-8")

        cancel_start = source.index("        var cancellation = new List<")
        cancel_end = source.index("    private void PreviewMorphAuthorDialog(", cancel_start)
        cancel_body = source[cancel_start:cancel_end]
        self.assertIn('cancellation.Add(("morph_delete_profile"', cancel_body)
        self.assertIn('["profile_id"] = dialog.ProfileId', cancel_body)
        self.assertNotIn('cancellation.Add(("morph_delete_definition"', cancel_body)
        self.assertIn("public bool PreserveExistingSelection", wizard_source)
        self.assertIn("&& !PreserveExistingSelection", wizard_source)

    def test_morph_slider_paces_updates_and_flushes_only_after_acknowledgement(self) -> None:
        source = _resident_morph_form_source()
        completion_start = source.index("    private void CompleteMorphCommandResult(")
        completion_end = source.index("    private void RegisterTopologyMutationButton(", completion_start)
        completion_body = source[completion_start:completion_end]

        self.assertIn("new() { Interval = 33 }", source)
        self.assertIn("if (_morphUpdateRequestId > 0)", source)
        self.assertIn("_pendingMorphUpdateControls = controls", source)
        self.assertIn("DiscardPendingMorphUpdate();\n                SendMorphValue(controls, \"end\"", source)
        self.assertLess(
            completion_body.index('pending.Phase == "update"'),
            completion_body.index('pending.Command != "morph_finish"'),
        )
        self.assertIn("_morphUpdateRequestId = 0", completion_body)
        self.assertIn("BeginInvoke((Action)FlushPendingMorphUpdate)", completion_body)

    def test_vortice_vertex_overlay_reuses_resident_geometry_buffers(self) -> None:
        overlay_source = (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "D3D11MaterialViewport.Overlay.cs").read_text(encoding="utf-8")
        selection_source = (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "MeshViewport.SelectionPicking.cs").read_text(encoding="utf-8")

        self.assertIn("private void DrawD3D11VertexOverlay()", overlay_source)
        self.assertIn("_context.IASetVertexBuffer(0u, ActiveVertexBuffer(batch)", overlay_source)
        self.assertIn("_context.DrawIndexed((uint)batch.IndexCount", overlay_source)
        self.assertIn("PrimitiveTopology.PointList", overlay_source)
        self.assertIn("VertexIdsInRectangle", selection_source)
        self.assertIn("FaceIdsInRectangle", selection_source)


if __name__ == "__main__":
    unittest.main()
