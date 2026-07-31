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
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    preferences = _source("MeshToolPanelLayoutPreferences.cs")

    left_width = int(re.search(r"DefaultLeftWidth = (\d+)", preferences).group(1))
    right_width = int(re.search(r"DefaultRightWidth = (\d+)", preferences).group(1))
    assert left_width >= 330
    assert right_width >= 360
    assert 'CreateToolPanelSplit("DotNetMeshEditorLeftViewportSplit", FixedPanel.Panel1)' in program
    assert 'CreateToolPanelSplit("DotNetMeshEditorViewportRightSplit", FixedPanel.Panel2)' in program
    assert "_leftToolSplit.Panel1.Controls.Add(_leftToolPanel);" in program
    assert "_presentationViewportRegion = BuildPresentationViewportRegion();" in program
    assert "_leftToolSplit.Panel2.Controls.Add(_rightToolSplit);" in program
    assert "InitializeEditMeshLayoutHost(_leftToolSplit);" in program
    assert "BuildPermanentViewportWorkspace();" in layout
    assert "BuildPermanentToolModeHosts();" in layout
    assert "_viewportWorkspaceSplit.Panel1.Controls.Add(_presentationViewportRegion);" in layout
    assert "_leftToolModeHost.Controls.Add(_leftToolPanel);" in layout
    assert "_rightToolModeHost.Controls.Add(_rightToolPanel);" in layout
    assert layout.count("Controls.Add(_presentationViewportRegion)") == 1
    assert layout.index(
        "_rightToolSplit.Panel1.Controls.Add(_viewportWorkspaceSplit);"
    ) < layout.index(
        "_viewportWorkspaceSplit.Panel1.Controls.Add(_presentationViewportRegion);"
    )

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
    # The row's floor is one button, not the whole row: a row held at its full
    # single-line width can never reflow inside a narrower tool column, so its
    # buttons overlap each other instead of wrapping.
    assert "panel.MinimumSize = new Size(widestCellWidth, 0);" in button_row
    assert "panel.Configure(cellWidths);" in button_row
    assert "MinimumRightWidth = 360" in preferences
    assert "_submeshList.HorizontalScrollbar = true;" in program


def test_button_rows_reflow_instead_of_overlapping_in_a_narrow_column() -> None:
    row = _source("ExperimentForm.ButtonRow.cs")

    assert "private sealed class MeshEditorButtonRow : TableLayoutPanel" in row
    assert "protected override void OnLayout" in row
    # The parent resizes the row after the layout pass that picked the column
    # count, so the count has to be re-checked on the new width.
    assert "protected override void OnSizeChanged" in row
    assert "private int ColumnsThatFit(int available)" in row
    assert "private bool FitsWithColumns(int columns, int available)" in row
    assert "var columnWidth = available / columns;" in row
    assert "SetCellPosition(cell, new TableLayoutPanelCellPosition(column, row));" in row


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


def test_reveal_restores_the_active_layout_widths_not_the_classic_ones() -> None:
    """A scene update with mesh edit already on must not shrink the tool rail.

    The embedded host re-runs the interaction-mode controls on every scene
    update. Uncollapsing the flanks against the saved *classic* widths left the
    rail's property column at the classic minimum, where its own tool pages no
    longer fit.
    """
    controls = _source("ExperimentForm.Controls.cs")
    layout = _source("ExperimentForm.EditMeshLayouts.cs")

    reveal = controls.split("private void ApplyEmbeddedToolPanelVisibility", 1)[1]
    reveal = reveal.split("private Control SceneComparisonControl", 1)[0]
    assert "if (IsToolRailActive)" in reveal
    assert reveal.index("ApplyToolRailSplitterLayout();") < reveal.index(
        "ApplySavedToolPanelLayout();"
    )

    already_active = layout.split("if (_activeEditMeshLayout == layout)", 1)[1]
    already_active = already_active.split("var requestedBeforeSwitch", 1)[0]
    assert "if (layout == EditMeshLayoutMode.ToolRail)" in already_active
    assert "ApplyToolRailSplitterLayout();" in already_active


def test_tool_rail_is_the_default_and_reuses_the_live_editor_controls() -> None:
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    transfer = _source("EditMeshLayoutContracts.cs")

    # Entering Edit Mesh presents the tool rail. Classic stays the
    # construction/non-mesh-mode state and remains reachable from the session
    # bar, but it is no longer what the user is dropped into.
    assert (
        "private EditMeshLayoutMode _requestedEditMeshLayout = "
        "EditMeshLayoutMode.ToolRail;"
    ) in layout
    assert (
        "private EditMeshLayoutMode _activeEditMeshLayout = "
        "EditMeshLayoutMode.Classic;"
    ) in layout
    assert '"Use Tool Rail Layout"' in program
    # The layout toggle is not gated on the embedded host: the standalone
    # authoring window has to be able to reach both layouts too.
    assert "classicLayoutToggleButton.Visible = _options.Embedded;" not in program
    assert '"Classic Layout"' in layout
    assert "RequestEditMeshLayout(EditMeshLayoutMode.ToolRail)" in program
    assert "RequestEditMeshLayout(EditMeshLayoutMode.Classic)" in layout

    assert "MoveSessionControlsToCompactBar();" in layout
    assert "MoveSessionControlsToClassicSection();" in layout
    assert "ConfigurePresentationRegion(compactEditableOnly: true);" in layout
    assert "ConfigurePresentationRegion(compactEditableOnly: false);" in layout
    assert "MoveControl(_presentationViewportRegion" not in layout
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
    assert "if (!IsToolRailActive)" in controls

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


def test_tool_rail_swaps_only_modal_tools_and_pins_the_scene_groups() -> None:
    layout = _source("ExperimentForm.EditMeshLayouts.cs")

    # Only the modal tools get a rail button. Parts, Action History and
    # Viewport are not modal, so hiding them behind a rail button would trade a
    # full-height column for a click.
    for page, caption in (
        ("Selection", "Select"),
        ("Transform", "Move"),
        ("Brush", "Brush"),
        ("Topology", "Topo"),
        ("MorphRefit", "Morph"),
    ):
        assert f"ToolRailPage.{page}, " in layout
        assert f'"{caption}"' in layout
    assert "ToolRailPage.Parts" not in layout
    assert "ToolRailPage.History" not in layout
    assert "ToolRailPage.Viewport" not in layout

    activate = layout.split("private void ActivateToolRailLayout()", 1)[1]
    activate = activate.split("private void ActivateClassicEditMeshLayout", 1)[0]
    assert "AddRailSection(_railSelectionStack, _selectionSection, row: 0);" in activate
    assert "AddRailSection(_railSelectionStack, _partPickSection, row: 1);" in activate
    for page, section in (
        ("Transform", "_transformSection"),
        ("Brush", "_brushSection"),
        ("Topology", "_topologySection"),
        ("MorphRefit", "_morphRefitSection"),
    ):
        assert f"AddRailSection(_toolRailPages[ToolRailPage.{page}], {section});" in activate
    # The scene column keeps its order and is always on screen.
    assert "AddRailSection(_sceneInspectorColumn, _partsSection, row: 0);" in activate
    assert "AddRailSection(_sceneInspectorColumn, _actionHistorySection, row: 1);" in activate
    assert "AddRailSection(_sceneInspectorColumn, _viewportSection, row: 2);" in activate

    # Both flanks are in use: the mesh is tall and narrow, so width is the
    # cheap axis and the viewport keeps the full window height.
    assert "_leftToolSplit.Panel1Collapsed = false;" in activate
    assert "_rightToolSplit.Panel2Collapsed = false;" in activate
    assert "_viewportWorkspaceSplit.Panel2Collapsed = true;" in activate
    assert '_viewport.ActivatePresentationView("editable");' in layout
    assert "_presentationViewSelector.Visible = !compactEditableOnly;" in layout


def test_edit_mesh_opens_with_no_tool_armed_and_the_camera_on_the_button() -> None:
    """Edit Mesh used to open with Select armed.

    The rail selects the page owning the viewport's tool and that page then
    asserts its own default tool. The viewport boots on ``orbit``, which no page
    owned, so the fallback landed on Selection and the very first click on the
    model changed the selection instead of turning the model.

    The camera is not a rail page — it is always available through the modifiers
    the navigation strip names — so orbit resolves to no page at all and the rail
    opens cleared. The mapping itself is executed by the ``mesh-unit`` layout
    smoke; this guards the wiring around it, which the smoke cannot construct.
    """
    contracts = _source("EditMeshLayoutContracts.cs")
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    program = _source("Program.cs")

    assert "internal enum ToolRailPage" in contracts
    assert "public static ToolRailPage? ToolRailPageForTool(string? tool)" in contracts
    assert "_ => null," in contracts
    # No page may answer for orbit, or entering Edit Mesh arms that page's tool.
    assert "ToolRailPage.Camera" not in contracts
    assert 'ToolRailPage.Camera' not in layout
    assert '"orbit"' not in contracts.split("RailPageOwnsTool", 1)[1].split("ToolRailPageForTool", 1)[0]

    # The camera has no rail button and no tool panel of its own.
    assert "AddToolRailButton(rail, ToolRailPage.Camera," not in layout
    assert "_cameraSection" not in layout
    assert "_cameraSection" not in program

    # The unopened rail resolves its page from the live tool rather than from a
    # remembered default, and only then marks itself chosen.
    assert "private ToolRailPage? _selectedToolRailPage;" in layout
    assert "private void ShowToolRailPage(ToolRailPage? page, bool armDefaultTool = true)" in layout
    first_reveal = layout.split("if (!_toolRailPageSelected)", 1)[1]
    first_reveal = first_reveal.split("ShowToolRailPage(_selectedToolRailPage", 1)[0]
    assert "_selectedToolRailPage = ToolRailPageForActiveTool();" in first_reveal

    # Re-revealing the rail is not a tool choice. Layout activation runs on every
    # redundant mesh_edit frame, and arming there replaced the live tool with the
    # page's default -- almost always Select, because no page owns orbit, morph or
    # topo. That is what threw the reader back to Selection > Select after using
    # Move, a brush, or Clear selection.
    assert "ShowToolRailPage(_selectedToolRailPage, armDefaultTool: false);" in layout

    # Nothing selected means no accent and no header, not a page shown blank.
    show = layout.split("private void ShowToolRailPage(ToolRailPage? page, bool armDefaultTool = true)", 1)[1]
    show = show.split("private void RevealToolRailPage", 1)[0]
    # A rail button the reader clicks still selects the tool it names.
    assert "if (armDefaultTool" in show
    assert "SetButtonAccent(pair.Value, pair.Key == page);" in show
    assert "? string.Empty" in show

    # One owner for the rules: ExperimentForm must not keep a second copy that
    # the executed smoke would not be checking.
    assert "private static string? DefaultToolForRailPage" not in layout
    assert "private static bool RailPageOwnsTool" not in layout
    assert "EditMeshLayoutContracts.ToolRailPageForTool(_viewport.ActiveTool)" in layout

    # Clearing the rail because the tool is orbit must only close a page that
    # armed a tool. Topology, Colour and Morph & Refit arm none, so the viewport
    # sits on orbit the whole time one is open -- closing on the tool alone shut
    # them the moment the host published a disabled mesh-edit tool state, which
    # it does on every selection change.
    sync = layout.split("private void SyncToolRailPageToActiveTool()", 1)[1]
    sync = sync.split("private void ApplyToolRailSplitterLayout", 1)[0]
    assert (
        "EditMeshLayoutContracts.DefaultToolForRailPage(_selectedToolRailPage.Value) is not null"
        in sync
    )
    assert "if (page is null || EditMeshLayoutContracts.RailPageOwnsTool(" not in sync


def test_edit_tools_show_the_camera_modifiers_that_still_work() -> None:
    """The camera modifiers are on screen while an edit tool owns the button.

    A brush claims the left button, so the only way to turn the model without
    dropping the tool is a modifier. Nothing on screen said so: the hint label
    carrying those bindings was added to the region in the simple-preview
    profile only, and Edit Mesh runs the authoring profile.
    """
    controls = _source("ExperimentForm.Controls.cs")
    presentation = _source("ExperimentForm.PresentationProtocol.cs")
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    input_source = _source("MeshViewport.Input.cs")
    program = _source("Program.cs")

    # Both gestures resolve their key through the binding rather than testing
    # ModifierKeys directly, or a rebind would leave the strip promising a key
    # that does nothing.
    assert "CameraModifierBindings.IsHeld(CameraPanModifier, ModifierKeys)" in input_source
    assert "CameraModifierBindings.IsHeld(CameraOrbitModifier, ModifierKeys)" in input_source
    assert "Keys.Control" not in input_source
    assert "Keys.Shift" not in input_source

    # Full window width, not the viewport column: both flanks are open in Edit
    # Mesh, and the bindings do not fit in what is left between them.
    assert (
        "_editMeshLayoutHost.Controls.Add(BuildViewportNavigationStrip(), 0, 2);"
        in layout
    )
    assert "region.Controls.Add(BuildViewportNavigationStrip()" not in presentation

    strip = presentation.split("private Control BuildViewportNavigationStrip()", 1)[1]
    strip = strip.split("private Control NavigationChip", 1)[0]
    assert 'Name = "ResidentViewportNavigationStrip"' in strip
    assert 'NavigationChip("Orbit", out _orbitChipBadge)' in strip
    assert 'NavigationChip("Pan", out _panChipBadge)' in strip
    assert 'NavigationChip("Zoom", out var zoomBadge)' in strip
    assert 'zoomBadge.Text = "Wheel";' in strip

    # The badge names whatever the modifier is bound to now, one whole literal
    # per binding so each stays a single translatable phrase.
    update = presentation.split("private void UpdateViewportNavigationStrip(", 1)[1]
    update = update.split("private Control BuildAuthoringStatusFooter", 1)[0]
    assert "_orbitChipBadge.Text = _viewport.CameraOrbitModifier switch" in update
    assert "_panChipBadge.Text = _viewport.CameraPanModifier switch" in update
    for literal in (
        '"Alt + left-drag"',
        '"Ctrl + left-drag"',
        '"Shift + left-drag"',
        '"Alt or Ctrl + left-drag"',
        '"Shift + left-drag, or middle / right-drag"',
    ):
        assert literal in update, literal

    # A rebind arrives on the presentation payload, and the strip is the only
    # thing that reports it, so applying one has to refresh the strip.
    applied = presentation.split("if (applied)", 1)[1].split("var payload", 1)[0]
    assert "UpdateViewportControlsHint();" in applied

    # The badges are highlighted exactly while an edit tool owns the left
    # button, which is when the modifiers are the only way to move the camera.
    hint = controls.split("private void UpdateViewportControlsHint()", 1)[1]
    hint = hint.split("protected override bool ProcessCmdKey", 1)[0]
    assert "UpdateViewportNavigationStrip(" in hint
    assert 'modifiersOwnTheCamera: meshEdit' in hint
    assert '!string.Equals(tool, "orbit", StringComparison.OrdinalIgnoreCase)' in hint
    assert "badge.BackColor = modifiersOwnTheCamera ? ThemeAccent" in presentation


def test_tool_rail_uses_the_stacked_morph_section_not_the_deck_card_grid() -> None:
    layout = _source("ExperimentForm.EditMeshLayouts.cs")

    # The Morph & Refit card grid was sized for a full-width bottom deck and
    # cannot lay out inside a single tool column, so the rail unwinds it and
    # uses the classic stacked form instead.
    activate = layout.split("private void ActivateToolRailLayout()", 1)[1]
    activate = activate.split("private void ActivateClassicEditMeshLayout", 1)[0]
    assert "ExitCompactMorphLayout();" in activate
    assert "SetMorphCollapseHeaderVisible(false);" in activate
    assert "EnterCompactMorphLayout(" not in layout
    # The dock header names the active tool, so the section's own collapse
    # header only comes back in the classic stack.
    classic = layout.split("private void ActivateClassicEditMeshLayout()", 1)[1]
    classic = classic.split("private void MoveSessionControlsToCompactBar", 1)[0]
    assert "SetMorphCollapseHeaderVisible(true);" in classic


def test_edit_mesh_chrome_matches_the_workbench_shell() -> None:
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")

    # The editor is embedded in the Qt shell, so it uses the shell's graphite
    # scheme rather than its own navy one.
    for token in (
        "Color.FromArgb(30, 30, 30)",
        "Color.FromArgb(37, 37, 38)",
        "Color.FromArgb(45, 45, 48)",
        "Color.FromArgb(0, 122, 204)",
        "Color.FromArgb(204, 204, 204)",
    ):
        assert token in program
    assert "Color.FromArgb(92, 169, 255)" not in program

    # Flat rounded chrome, not the beveled highlight/shadow border.
    assert "ControlPaint.DrawBorder" not in controls
    assert "ThemeButtonHighlight" not in controls
    assert "ThemeButtonShadow" not in controls
    assert "class MeshEditorFlatButton : Button" in controls
    assert "class MeshEditorSectionBox : GroupBox" in controls
    assert "GraphicsPath RoundedPath(" in controls
    assert "var group = new MeshEditorSectionBox" in controls


def test_edit_mesh_defers_splitter_minimums_until_real_size_exists() -> None:
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    transfer = _source("EditMeshLayoutContracts.cs")

    workspace_builder = layout.split("private void BuildPermanentViewportWorkspace()", 1)[1]
    workspace_builder = workspace_builder.split("private void BuildPermanentToolModeHosts()", 1)[0]
    assert "_viewportWorkspaceSplit.Panel1MinSize" not in workspace_builder
    assert "_viewportWorkspaceSplit.Panel2MinSize" not in workspace_builder
    assert transfer.index("split.Panel1MinSize = 0;") < transfer.index(
        "if (available <= 0)"
    )
    assert transfer.index("split.Panel2MinSize = 0;") < transfer.index(
        "if (available <= 0)"
    )
    assert "EditMeshLayoutContracts.ApplyPanelTwoSize(" in layout


def test_returning_to_classic_forces_its_own_layout_pass() -> None:
    layout = _source("ExperimentForm.EditMeshLayouts.cs")

    classic = layout.split("private void ActivateClassicEditMeshLayout()", 1)[1]
    classic = classic.split("private void MoveSessionControlsToCompactBar", 1)[0]
    # The classic stacks are rebuilt while suspended and resume without their
    # own layout pass, so their new rows keep construction-time bounds until
    # something forces the measure.
    assert classic.index("ResumeAllEditMeshLayouts();") < classic.index(
        "PerformClassicToolStackLayout();"
    )
    performer = layout.split("private void PerformClassicToolStackLayout()", 1)[1]
    performer = performer.split("private void CaptureClassicScrollPositions", 1)[0]
    for target in ("_morphSectionBody", "_rightToolStack", "_leftToolStack"):
        assert f"{target}?.PerformLayout();" in performer


def test_edit_mesh_captions_and_inputs_survive_theming_and_resize() -> None:
    controls = _source("ExperimentForm.Controls.cs")
    morph = _source("ExperimentForm.MorphRefit.cs")

    # "Morph & Refit" and "Review & Apply" lose their ampersand to mnemonic
    # parsing unless the caption opts out. Buttons and labels switch it off;
    # section titles are drawn by MeshEditorSectionBox with NoPrefix, so they
    # must NOT be escaped or the escape renders literally.
    assert "UseMnemonic = false" in controls
    assert "MnemonicSafeCaption" not in controls
    assert "MnemonicSafeCaption" not in morph
    assert "TextFormatFlags.NoPrefix" in controls

    # A flat DropDownList keeps its stale paint when the layout widens it.
    combo = controls.split("private static void ConfigureCombo", 1)[1]
    combo = combo.split("private static void ConfigureCheckBox", 1)[0]
    assert "combo.Resize += (_, _) => combo.Invalidate();" in combo

    # Wire width and vertex size each own a full-width row; nesting them under
    # a shared label pushed the vertex control past the inspector edge.
    overlay = controls.split("private Control OverlayAppearanceControls()", 1)[1]
    overlay = overlay.split("private Button OverlayColorButton", 1)[0]
    assert 'LabeledControl(\n            "Topology appearance",' not in overlay
    assert 'LabeledControl("Wire width (px)", _wireOverlayWidth)' in overlay
    assert 'LabeledControl("Vertex size (px)", _vertexMarkerSize)' in overlay


def test_edit_mesh_has_a_nonvisual_round_trip_construction_gate() -> None:
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
    assert "stable_viewport_parent" in smoke
    assert "MoveControl(viewport" not in smoke
    assert "zero_size_splitter_construction" in smoke
    for page in ("Selection", "Transform", "Brush", "Topology", "Morph & Refit"):
        assert f'"{page}"' in smoke


def test_deferred_authoring_tool_panels_have_two_build_triggers() -> None:
    """The panels skip startup, so something must still guarantee they appear.

    Building them before the first frame cost roughly 1.5 s of editor startup.
    Deferring is only safe because two independent paths build them: a post to
    the message loop once ``ready`` is published, and mesh-edit entry as a
    backstop for a user who gets there first. Losing either one is what would
    leave the Mesh Editor with no tool panels at all.

    tools/mesh_harness/real_dotnet_tool_panel_lifecycle.py asserts the runtime
    behaviour; this only guards the wiring.
    """

    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")
    layouts = _source("ExperimentForm.EditMeshLayouts.cs")
    material_protocol = _source("ExperimentForm.MaterialProtocol.cs")
    protocol = _source("ExperimentForm.Protocol.cs")

    # Preview never builds them; a standalone window still builds them up front.
    assert "private bool DeferAuthoringToolPanels => _options.SimplePreview || _options.Embedded;" in program
    assert "if (!DeferAuthoringToolPanels)" in program

    # Trigger 1: posted once the first frame is out.
    ready_body = program.split("private void PublishReady(", maxsplit=1)[1].split(
        "private bool TryEmbedOrFail(", maxsplit=1
    )[0]
    assert "BeginInvoke(new Action(EnsureAuthoringToolPanelsReady));" in ready_body

    # Trigger 2: mesh-edit entry, before anything walks the section lists.
    interaction_body = controls.split("private void ApplyInteractionModeControls()", maxsplit=1)[1].split(
        "\n    private ", maxsplit=1
    )[0]
    assert "EnsureAuthoringToolPanelsReady();" in interaction_body
    assert interaction_body.index("EnsureAuthoringToolPanelsReady();") < interaction_body.index(
        "foreach (var section in _meshEditOnlySections)"
    )

    # Both builders must be idempotent, since either trigger can fire first.
    assert "if (_options.SimplePreview || _authoringToolPanelsBuilt)" in program
    assert "if (_options.SimplePreview || _leftToolModeHost is not null)" in layouts
    assert "if (_options.SimplePreview || _compactSessionBar is not null" in layouts

    # And the result has to stay observable from outside the process.
    assert '["authoring_tool_panels_present"] = _leftToolPanel is not null && _rightToolPanel is not null' in material_protocol
    assert '["lifecycle_counts"] = LifecycleCountsPayload(),' in protocol
