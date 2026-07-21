from __future__ import annotations

import re
from pathlib import Path


DOTNET_ROOT = (
    Path(__file__).resolve().parents[1] / "tools" / "dotnet_mesh_editor_experiment"
)


def _source(name: str) -> str:
    return (DOTNET_ROOT / name).read_text(encoding="utf-8")


def _section_stack(program_source: str, title: str) -> str:
    match = re.search(
        rf"Add(?:Help)?Section\(\s*(\w+),\s*\"{re.escape(title)}\"",
        program_source,
    )
    assert match is not None, f"section not found: {title}"
    return match.group(1)


def test_edit_mesh_panels_flank_the_viewport_with_requested_sections() -> None:
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")

    left_width = int(re.search(r"LeftToolPanelWidth = (\d+)", program).group(1))
    right_width = int(re.search(r"RightToolPanelWidth = (\d+)", program).group(1))
    assert left_width >= 330
    assert right_width >= 300
    assert "ColumnCount = 3" in program
    assert "Controls.Add(_leftToolPanel, 0, 0);" in program
    assert "Controls.Add(BuildPresentationViewportRegion(), 1, 0);" in program
    assert "Controls.Add(_rightToolPanel, 2, 0);" in program

    assert _section_stack(program, "Mesh Edit Session") == "leftStack"
    assert _section_stack(program, "Part Pick") == "leftStack"
    assert _section_stack(program, "Selection") == "leftStack"
    assert _section_stack(program, "Transform") == "leftStack"
    assert _section_stack(program, "Brush Tools") == "leftStack"
    assert _section_stack(program, "Topology") == "leftStack"
    assert _section_stack(program, "Action History") == "rightStack"
    assert _section_stack(program, "Parts") == "rightStack"
    assert _section_stack(program, "Viewport") == "rightStack"

    assert "ColumnStyles[0].Width = meshEdit ? LeftToolPanelWidth : 0;" in controls
    assert "ColumnStyles[2].Width = meshEdit ? RightToolPanelWidth : 0;" in controls
    assert "_leftToolPanel.Visible = meshEdit;" in controls
    assert "_rightToolPanel.Visible = meshEdit;" in controls


def test_long_edit_mesh_help_is_available_from_question_mark_tooltips() -> None:
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")
    presentation = _source("ExperimentForm.PresentationProtocol.cs")

    for title in ("Action History", "Selection", "Brush Tools", "Viewport"):
        assert re.search(
            rf"AddHelpSection\(\s*\w+,\s*\"{re.escape(title)}\"",
            program,
        )
    assert 'Text = "?"' in controls
    assert "Cursors.Help" in controls
    assert "_helpToolTip.SetToolTip(marker, helpText);" in controls
    assert "AccessibleDescription = helpText" in controls
    assert "SetHelpText(" in controls
    assert "_viewportHelpMarker" in controls

    build_panels = program.split("private (Panel Left, Panel Right) BuildToolPanels()", 1)[1]
    build_panels = build_panels.split("private static Panel CreateToolPanel", 1)[0]
    assert "MaximumSize = new Size(248, 0)" not in build_panels
    assert "OverlayAppearanceXRayHint" not in controls

    assert "RowCount = 2" in presentation
    simple_preview_footer = re.search(
        r"if \(simplePreview\)\s*\{\s*region\.Controls\.Add\(_controlsHintLabel, 0, 1\);\s*\}",
        presentation,
    )
    assert simple_preview_footer is not None


def test_edit_mesh_text_controls_expand_for_the_active_font() -> None:
    controls = _source("ExperimentForm.Controls.cs")

    checkbox = controls.split("private static void ConfigureCheckBox", 1)[1]
    checkbox = checkbox.split("private static CheckBox ToolCheckBox", 1)[0]
    assert "checkBox.AutoSize = true;" in checkbox
    assert "SingleLineControlHeight(checkBox)" in checkbox

    labeled = controls.split("private static Control LabeledControl", 1)[1]
    labeled = labeled.split("private static Control ButtonRow", 1)[0]
    assert "AutoSize = true" in labeled
    assert "AutoSize = false" not in labeled

    button = controls.split("private static Button StyledButton", 1)[1]
    button = button.split("private static Button StyledActionButton", 1)[0]
    assert "AutoSize = true" in button
    assert "AutoSizeMode = AutoSizeMode.GrowAndShrink" in button
    assert "MinimumSize = new Size(0, buttonHeight)" in button
