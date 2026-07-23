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
    preferences = _source("MeshToolPanelLayoutPreferences.cs")

    left_width = int(re.search(r"DefaultLeftWidth = (\d+)", preferences).group(1))
    right_width = int(re.search(r"DefaultRightWidth = (\d+)", preferences).group(1))
    assert left_width >= 330
    assert right_width >= 360
    assert 'CreateToolPanelSplit("DotNetMeshEditorLeftViewportSplit", FixedPanel.Panel1)' in program
    assert 'CreateToolPanelSplit("DotNetMeshEditorViewportRightSplit", FixedPanel.Panel2)' in program
    assert "_leftToolSplit.Panel1.Controls.Add(_leftToolPanel);" in program
    assert "_presentationViewportRegion = BuildPresentationViewportRegion();" in program
    assert "_rightToolSplit.Panel1.Controls.Add(_presentationViewportRegion);" in program
    assert "_rightToolSplit.Panel2.Controls.Add(_rightToolPanel);" in program
    assert "_leftToolSplit.Panel2.Controls.Add(_rightToolSplit);" in program
    assert "InitializeEditMeshLayoutHost(_leftToolSplit);" in program

    assert _section_stack(program, "Mesh Edit Session") == "leftStack"
    assert _section_stack(program, "Part Pick") == "leftStack"
    assert _section_stack(program, "Selection") == "leftStack"
    assert _section_stack(program, "Transform") == "leftStack"
    assert _section_stack(program, "Brush Tools") == "leftStack"
    assert _section_stack(program, "Topology") == "leftStack"
    assert _section_stack(program, "Action History") == "rightStack"
    assert _section_stack(program, "Parts") == "rightStack"
    assert _section_stack(program, "Viewport") == "rightStack"

    assert "_leftToolSplit.Panel1Collapsed = true;" in controls
    assert "_rightToolSplit.Panel2Collapsed = true;" in controls
    assert "_leftToolSplit.Panel1Collapsed = false;" in controls
    assert "_rightToolSplit.Panel2Collapsed = false;" in controls
    collapsed = controls.split("private void ApplyEmbeddedToolPanelVisibility", 1)[1]
    collapsed = collapsed.split("var applyingBeforeExpand", 1)[0]
    assert "_leftToolSplit.Panel1MinSize = 0;" in collapsed
    assert "_leftToolSplit.Panel2MinSize = 0;" in collapsed
    assert "_rightToolSplit.Panel1MinSize = 0;" in collapsed
    assert "_rightToolSplit.Panel2MinSize = 0;" in collapsed


def test_both_tool_panel_widths_are_resizable_and_persisted() -> None:
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")
    preferences = _source("MeshToolPanelLayoutPreferences.cs")

    assert "IsSplitterFixed = false" in controls
    assert "FixedPanel = fixedPanel" in controls
    assert controls.count("SplitterMoved +=") == 2
    assert 'Schema = "cdmw_mesh_tool_panel_layout_v1"' in preferences
    assert '"mesh-editor-tool-panels.json"' in preferences
    assert 'ParseWidth(root, "left_width"' in preferences
    assert 'ParseWidth(root, "right_width"' in preferences
    assert '["left_width"] = normalized.LeftWidth' in preferences
    assert '["right_width"] = normalized.RightWidth' in preferences
    assert "File.Move(staging, path, overwrite: true);" in preferences
    assert "MeshToolPanelLayoutPreferences.Load()" in program
    assert "SaveToolPanelLayout();" in program
    assert "CaptureToolPanelLayout(persist: false);" in controls
    assert "ApplySavedToolPanelLayout();" in controls
    assert "ScaleToolPanelWidth" in controls
    assert "LogicalToolPanelWidth" in controls


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

    assert "RowCount = simplePreview ? 2 : 3" in presentation
    simple_preview_footer = re.search(
        r"if \(simplePreview\)\s*\{\s*region\.Controls\.Add\(_controlsHintLabel, 0, 1\);\s*\}",
        presentation,
    )
    assert simple_preview_footer is not None


def test_edit_mesh_left_navigation_and_status_use_the_available_space() -> None:
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")
    presentation = _source("ExperimentForm.PresentationProtocol.cs")

    assert 'navigator.Name = "DotNetMeshEditorLeftToolNavigator"' in controls
    assert "scrollPanel.ScrollControlIntoView(item.Target);" in controls
    for label in ("Select", "Move", "Brush", "Topology"):
        assert f'("{label}", ' in program
    assert "left.Controls.Add(leftNavigator);" in program
    assert "leftNavigator.BringToFront();" in program
    assert "_meshEditOnlySections.Add(leftNavigator);" in program

    assert "left.Controls.Add(statusFooter);" not in program
    assert 'Name = "ResidentViewportStatusFooter"' in presentation
    assert "region.Controls.Add(BuildAuthoringStatusFooter(), 0, 2);" in presentation
    assert "footer.Controls.Add(_statusLabel, 0, 0);" in presentation
    assert "footer.Controls.Add(_fpsLabel, 1, 0);" in presentation


def test_edit_mesh_text_controls_expand_for_the_active_font() -> None:
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")
    preferences = _source("MeshToolPanelLayoutPreferences.cs")

    checkbox = controls.split("private static void ConfigureCheckBox", 1)[1]
    checkbox = checkbox.split("private static CheckBox ToolCheckBox", 1)[0]
    assert "checkBox.AutoSize = true;" in checkbox
    assert "SingleLineControlHeight(checkBox)" in checkbox

    labeled = controls.split("private static Control LabeledControl", 1)[1]
    labeled = labeled.split("private static Control ButtonRow", 1)[0]
    assert "AutoSize = true" in labeled
    assert "AutoSize = false" not in labeled
    assert "ColumnCount = 2" in labeled
    assert "RowCount = 1" in labeled
    assert "new ColumnStyle(SizeType.AutoSize)" in labeled
    assert "new ColumnStyle(SizeType.Percent, 100)" in labeled
    assert "control.Dock = DockStyle.Fill;" in labeled

    button = controls.split("private static Button StyledButton", 1)[1]
    button = button.split("private static Button StyledActionButton", 1)[0]
    assert "AutoSize = true" in button
    assert "AutoSizeMode = AutoSizeMode.GrowAndShrink" in button
    assert "MinimumSize = new Size(0, buttonHeight)" in button

    button_row = controls.split("private static Control ButtonRow", 1)[1]
    button_row = button_row.split("private static GroupBox AddSection", 1)[0]
    assert "control.GetPreferredSize(Size.Empty).Width" in button_row
    assert "panel.MinimumSize = new Size(minimumRowWidth, 0);" in button_row
    assert "MinimumRightWidth = 360" in preferences
    assert "_submeshList.HorizontalScrollbar = true;" in program


def test_panel_reveal_is_atomic_and_has_no_recursive_width_forcing() -> None:
    controls = _source("ExperimentForm.Controls.cs")
    program = _source("Program.cs")

    interaction = controls.split("private void ApplyInteractionModeControls()", 1)[1]
    interaction = interaction.split("private void ApplyEmbeddedToolPanelVisibility", 1)[0]
    assert interaction.index("SuspendToolPanelLayout();") < interaction.index(
        "foreach (var section in _meshEditOnlySections)"
    )
    assert interaction.index("ApplyEmbeddedToolPanelVisibility(meshEdit: false);") < interaction.index(
        "section.Visible = meshEdit;"
    )
    assert "ResumeToolPanelLayout();" in interaction
    assert "ResizeToolStack" not in controls
    assert "scrollPanel.Resize +=" not in program
    assert "MeshEditorBufferedPanel" in controls
    assert "MeshEditorBufferedTableLayoutPanel" in controls
    assert "MeshEditorBufferedSplitContainer" in controls


def test_bottom_tool_deck_is_opt_in_and_reuses_the_live_editor_controls() -> None:
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    transfer = _source("EditMeshLayoutContracts.cs")

    assert "_requestedEditMeshLayout = EditMeshLayoutMode.Classic;" in layout
    assert "_activeEditMeshLayout = EditMeshLayoutMode.Classic;" in layout
    assert '"Try Bottom Tool Deck"' in program
    assert '"Use Classic Layout"' in layout
    assert "RequestEditMeshLayout(EditMeshLayoutMode.BottomToolDeck)" in program
    assert "RequestEditMeshLayout(EditMeshLayoutMode.Classic)" in layout

    assert "MoveSessionControlsToCompactBar();" in layout
    assert "MoveSessionControlsToClassicSection();" in layout
    assert "MovePresentationRegion(_compactViewportHost, compactEditableOnly: true);" in layout
    assert "MovePresentationRegion(_rightToolSplit.Panel1, compactEditableOnly: false);" in layout
    assert "EditMeshLayoutContracts.MoveControl(" in layout
    assert "host.Controls.Add(control);" in transfer
    assert "control.IsDisposed || host.IsDisposed" in transfer
    assert "new MeshViewport" not in layout
    assert "CommandButton(" not in layout
    assert "ToolButton(" not in layout

    interaction = controls.split("private void ApplyInteractionModeControls()", 1)[1]
    interaction = interaction.split("private void ApplyEmbeddedToolPanelVisibility", 1)[0]
    assert "RestoreClassicLayoutForNonMeshMode();" in interaction
    assert "ApplyRequestedEditMeshLayout();" in interaction
    assert "if (!IsBottomToolDeckActive)" in controls

    classic_restore = layout.split("private void RebuildClassicToolStacks()", 1)[1]
    classic_restore = classic_restore.split("private static void RebuildClassicStack", 1)[0]
    for earlier, later in (
        ("_classicSessionSection", "_partPickSection"),
        ("_partPickSection", "_selectionSection"),
        ("_selectionSection", "_placementSection"),
        ("_placementSection", "_transformSection"),
        ("_transformSection", "_brushSection"),
        ("_brushSection", "_topologySection"),
        ("_actionHistorySection", "_morphRefitSection"),
        ("_morphRefitSection", "_partsSection"),
        ("_partsSection", "_viewportSection"),
    ):
        assert classic_restore.index(earlier) < classic_restore.index(later)


def test_bottom_tool_deck_groups_every_edit_tool_and_keeps_editable_only_view() -> None:
    layout = _source("ExperimentForm.EditMeshLayouts.cs")

    for page, label in (
        ("Selection", "Selection"),
        ("Transform", "Transform"),
        ("Brush", "Brush"),
        ("Topology", "Topology"),
        ("MorphRefit", "Morph & Refit"),
    ):
        assert f"CompactToolPage.{page}, \"{label}\"" in layout

    assert "AddCompactSection(_compactSelectionGrid, _partPickSection, 0, 0);" in layout
    assert "AddCompactSection(_compactSelectionGrid, _selectionSection, 1, 0);" in layout
    assert "AddCompactSection(_compactTransformHost, _transformSection);" in layout
    assert "AddCompactSection(_compactBrushHost, _brushSection);" in layout
    assert "AddCompactSection(_compactTopologyHost, _topologySection);" in layout
    assert "AddCompactSection(_compactMorphHost, _morphRefitSection);" in layout
    assert "AddCompactInspectorSection(_partsSection, 0, stretchFirstRow: true);" in layout
    assert "AddCompactInspectorSection(_actionHistorySection, 1, stretchFirstRow: true);" in layout
    assert "AddCompactInspectorSection(_viewportSection, 2);" in layout
    assert '_viewport.ActivatePresentationView("editable");' in layout
    assert "_presentationViewSelector.Visible = !compactEditableOnly;" in layout


def test_bottom_tool_deck_morph_layout_is_responsive_and_session_only() -> None:
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    morph = _source("ExperimentForm.MorphRefit.cs")
    transfer = _source("EditMeshLayoutContracts.cs")

    assert "logicalWidth >= 1500 ? 4 : logicalWidth >= 900 ? 2 : 1" in transfer
    assert "EnterCompactMorphLayout(columnCount);" in layout
    assert "AddMorphCompactSpanningRow(" in morph
    for title in (
        "Definition",
        "Presets",
        "Shape Sliders",
        "Garment Refit",
        "Review & Apply",
    ):
        assert f'"{title}"' in morph
    assert "_compactInspectorWidthLogical" in layout
    assert "_compactToolDeckHeightLogical" in layout
    assert "DefaultInspectorWidth(" in transfer
    assert "DefaultToolDeckHeight(" in transfer
    assert "MeshToolPanelLayoutPreferences" not in layout


def test_bottom_tool_deck_defers_splitter_minimums_until_real_size_exists() -> None:
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    transfer = _source("EditMeshLayoutContracts.cs")

    workspace_builder = layout.split("private Control BuildCompactWorkspace()", 1)[1]
    workspace_builder = workspace_builder.split("private Control BuildCompactToolDeck()", 1)[0]
    assert "_compactWorkspaceSplit.Panel1MinSize" not in workspace_builder
    assert "_compactWorkspaceSplit.Panel2MinSize" not in workspace_builder
    assert transfer.index("split.Panel1MinSize = 0;") < transfer.index(
        "if (available <= 0)"
    )
    assert transfer.index("split.Panel2MinSize = 0;") < transfer.index(
        "if (available <= 0)"
    )
    assert "EditMeshLayoutContracts.ApplyPanelTwoSize(" in layout


def test_bottom_tool_deck_has_a_nonvisual_round_trip_construction_gate() -> None:
    entry = _source("ProgramEntry.cs")
    smoke = _source("EditMeshLayoutSmoke.cs")

    assert "EditMeshLayoutSmoke.IsRequested(args)" in entry
    assert "return EditMeshLayoutSmoke.Run(args);" in entry
    assert '"--headless-edit-mesh-layout-smoke"' in smoke
    assert '"--layout-report"' in smoke
    assert '["renderer_started"] = false' in smoke
    assert '["visible_window_started"] = false' in smoke
    assert "same_control_instances" in smoke
    assert "same_viewport_instance" in smoke
    assert "same_viewport_handle" in smoke
    assert "zero_size_splitter_construction" in smoke
    for page in ("Selection", "Transform", "Brush", "Topology", "Morph & Refit"):
        assert f'"{page}"' in smoke
