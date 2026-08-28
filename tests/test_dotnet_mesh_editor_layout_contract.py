from __future__ import annotations

import re
from pathlib import Path


DOTNET_ROOT = (
    Path(__file__).resolve().parents[1] / "tools" / "dotnet_mesh_editor_experiment"
)


def _source(name: str) -> str:
    owners = {
        # The hidden startup realisation is a further partial of the same class.
        "Program.cs": (
            "Program.cs",
            "ExperimentForm.ToolPanels.cs",
            "ExperimentForm.StartupRealization.cs",
        ),
        # The flat button is a further partial of the same class.
        "ExperimentForm.Controls.cs": (
            "ExperimentForm.Controls.cs",
            "ExperimentForm.AppearanceControls.cs",
            "ExperimentForm.FlatButton.cs",
        ),
        # Layout suspend and resume are a second partial of the same class.
        "ExperimentForm.EditMeshLayouts.cs": (
            "ExperimentForm.EditMeshLayouts.cs",
            "ExperimentForm.EditMeshLayouts.Suspend.cs",
        ),
    }.get(name, (name,))
    return "\n".join((DOTNET_ROOT / owner).read_text(encoding="utf-8") for owner in owners)


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

    # The placement stacks are the construction nursery for every section; the
    # session commands are built bare and adopted by the compact session bar.
    # The Part Pick section is removed outright: the Parts panel is the part
    # surface, and picking is always available.
    assert 'AddSection(leftStack, "Part Pick"' not in program
    assert "_partPickSection = null;" in program
    assert _section_stack(program, "Selection") == "leftStack"
    assert _section_stack(program, "Transform") == "leftStack"
    assert _section_stack(program, "Brush Tools") == "leftStack"
    assert _section_stack(program, "Topology") == "leftStack"
    assert "CreatePartFromSelectionButton" in _source("ExperimentForm.PartsSection.cs")
    assert 'CreatePartFromSelectionButton()' in program
    assert 'CommandButton("Split Selection Into Part", "separate")' not in program
    assert "ButtonRow(separateSelectionButton)" not in program
    diagnostics = _source("ExperimentForm.EditMeshToolDiagnostics.cs")
    assert '"direct_authoring_controls"' in diagnostics
    assert '"mixed_morph_refit_selection"' in diagnostics
    assert "!_createPartFromSelectionButton.Visible" in diagnostics
    command_guard = program.split(
        "private long WriteCommandRequest", maxsplit=1
    )[1].split("var targetMode = SelectionTarget();", maxsplit=1)[0]
    assert 'normalizedCommand is "subdivide" or "refine_smooth" or "separate"' in command_guard
    assert 'or "refine_smooth" or "separate" or "copy"' in command_guard
    assert 'ApplyDirectAuthoringOutputContract(JsonBoolean(root, "exact_output_required"));' in _source(
        "ExperimentForm.Protocol.cs"
    )
    assert _section_stack(program, "Action History") == "rightStack"
    assert _section_stack(program, "Viewport") == "leftStack"
    # Parts builds through its own owner, which carries the selected-part
    # detail; it is still constructed into the right placement stack.
    assert "_partsSection = BuildPartsSection(rightStack, " in program
    assert _section_stack(_source("ExperimentForm.PartsSection.cs"), "Parts") == "stack"

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


def test_long_edit_mesh_help_is_available_from_section_tooltips() -> None:
    """Help hangs off the section, not off a "?" badge.

    The badge was pinned into the caption row, so every section reserved empty
    height for it even where the caption is blanked — which put a dead band
    above each tool's first field. The help text is unchanged; only its handle
    moved onto the section itself.
    """
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")
    presentation = _source("ExperimentForm.PresentationProtocol.cs")

    for title in ("Action History", "Selection", "Brush Tools", "Viewport"):
        assert re.search(
            rf"AddHelpSection\(\s*\w+,\s*\"{re.escape(title)}\"",
            program,
        )
    assert 'Text = "?"' not in controls
    assert "Cursors.Help" not in controls
    assert "SetHelpText(group, helpText);" in controls
    assert "_helpToolTip.SetToolTip(marker, helpText);" in controls
    assert "SetHelpText(" in controls
    assert "_viewportHelpMarker" in controls
    # A blanked caption reserves no height, which is what the badge's row was.
    assert "public void FitCaptionHeight()" in controls
    assert "string.IsNullOrEmpty(base.Text) ? 8" in controls

    build_panels = program.split("private (Panel Left, Panel Right) BuildToolPanels()", 1)[1]
    build_panels = build_panels.split("private static Panel CreateToolPanel", 1)[0]
    assert "MaximumSize = new Size(248, 0)" not in build_panels
    assert "OverlayAppearanceXRayHint" not in controls

    assert "var embeddedAuthoring = _options.Embedded && !simplePreview;" in presentation
    assert "RowCount = simplePreview || embeddedAuthoring ? 2 : 3" in presentation
    simple_preview_footer = re.search(
        r"if \(simplePreview\)\s*\{\s*region\.Controls\.Add\(_controlsHintLabel, 0, 1\);\s*\}",
        presentation,
    )
    assert simple_preview_footer is not None


def test_embedded_edit_mesh_status_uses_the_header_instead_of_a_footer() -> None:
    """The rail lists every tool directly, so the classic scroll navigator is gone.

    The navigator existed to jump the classic scrolling stack to a tool's
    section. With the tool rail as the only Edit Mesh layout there is no
    scrolling stack of tool sections to navigate — the rail itself is the flat
    list of tools.
    """
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")
    presentation = _source("ExperimentForm.PresentationProtocol.cs")

    assert "BuildToolNavigator" not in controls
    assert "BuildToolNavigator" not in program
    assert "DotNetMeshEditorLeftToolNavigator" not in controls

    assert "left.Controls.Add(statusFooter);" not in program
    assert 'Name = "ResidentViewportStatusFooter"' in presentation
    assert "else if (!embeddedAuthoring)" in presentation
    assert "region.Controls.Add(BuildAuthoringStatusFooter(), 0, 2);" in presentation
    assert "footer.Controls.Add(_statusLabel, 0, 0);" in presentation
    assert "footer.Controls.Add(_fpsLabel, 1, 0);" in presentation
    assert '_statusLabel.Dock = DockStyle.Left;' in presentation
    assert 'button.Controls.Add(_statusLabel);' in presentation
    assert '_fpsLabel.Dock = DockStyle.Right;' in presentation
    assert '_fpsLabel.Width = 320;' in presentation
    assert '_fpsLabel.Padding = new Padding(8, 0, 24, 0);' in presentation
    assert 'button.Controls.Add(_fpsLabel);' in presentation


def test_edit_mesh_side_controls_use_compact_density_values() -> None:
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    tool_list = _source("ExperimentForm.ToolList.cs")

    assert "private static int SingleLineControlHeight(Control control, int minimum = 24)" in controls
    assert 'private static Button StyledButton(string text, int height = 26)' in controls
    assert 'Padding = new Padding(8, 20, 8, 7)' in controls
    assert 'Margin = new Padding(0, 0, 0, 6)' in controls
    assert controls.count('button.Height = 40;') == 2
    assert controls.count('button.Font = new Font(button.Font.FontFamily, 8f);') == 2
    assert '_submeshList.Height = 96;' in program
    assert '_actionHistoryList.Height = 96;' in program
    assert 'private const int ToolListRowHeight = 30;' in tool_list
    assert '_toolDock.Font = new Font(Font.FontFamily, 8.5f);' in layout
    assert 'panel.Font = new Font(Font.FontFamily, 8.5f);' in layout
    assert '_options.SimplePreview ? 0 : Math.Max(30, Font.Height + 8)' in layout


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


def test_reveal_restores_the_active_layout_widths_not_the_placement_ones() -> None:
    """A scene update with mesh edit already on must not shrink the tool rail.

    The embedded host re-runs the interaction-mode controls on every scene
    update. Uncollapsing the flanks against the saved *placement* widths left
    the rail's property column at the placement minimum, where its own tool
    pages no longer fit.
    """
    controls = _source("ExperimentForm.Controls.cs")
    layout = _source("ExperimentForm.EditMeshLayouts.cs")

    reveal = controls.split("private void ApplyEmbeddedToolPanelVisibility", 1)[1]
    reveal = reveal.split("private Control SceneComparisonControl", 1)[0]
    assert "if (IsToolRailActive)" in reveal
    assert reveal.index("ApplyToolRailSplitterLayout();") < reveal.index(
        "ApplySavedToolPanelLayout();"
    )

    already_active = layout.split("private void ApplyToolRailEditMeshLayout()", 1)[1]
    already_active = already_active.split("private void ActivateToolRailLayout()", 1)[0]
    assert "if (_toolRailLayoutActive)" in already_active
    assert "ApplyToolRailSplitterLayout();" in already_active


def test_tool_rail_is_the_only_layout_and_reuses_the_live_editor_controls() -> None:
    program = _source("Program.cs")
    controls = _source("ExperimentForm.Controls.cs")
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    transfer = _source("EditMeshLayoutContracts.cs")

    # The Classic Edit Mesh layout is gone: entering mesh edit always presents
    # the tool rail, and leaving mesh edit restores only the placement flanks.
    # There is no layout mode, no layout request, and no toggle button.
    assert "EditMeshLayoutMode" not in layout
    assert "EditMeshLayoutMode" not in program
    assert "RequestEditMeshLayout" not in layout
    assert "RequestEditMeshLayout" not in program
    assert "ActivateClassicEditMeshLayout" not in layout
    assert '"Classic Layout"' not in layout
    assert '"Use Tool Rail Layout"' not in program
    assert "UseClassicEditMeshLayoutButton" not in layout
    assert "UseToolRailEditMeshLayoutButton" not in program
    assert "private bool _toolRailLayoutActive;" in layout
    assert "private bool IsToolRailActive => _toolRailLayoutActive;" in layout

    # The compact session bar is the session commands' only home; it adopts
    # them once when it is attached.
    attach = layout.split("private void AttachCompactSessionBar()", 1)[1]
    attach = attach.split("private void BuildPermanentViewportWorkspace()", 1)[0]
    assert "MoveSessionControlsToCompactBar();" in attach
    assert "MoveSessionControlsToClassicSection" not in layout
    assert "RebuildClassicToolStacks" not in layout

    assert "ConfigurePresentationRegion(compactEditableOnly: true);" in layout
    assert "ConfigurePresentationRegion(compactEditableOnly: false);" in layout
    assert "MoveControl(_presentationViewportRegion" not in layout
    assert "EditMeshLayoutContracts.MoveControl(" in layout
    assert "host.Controls.Add(control);" in transfer
    assert "control.IsDisposed || host.IsDisposed" in transfer
    assert "new MeshViewport" not in layout
    assert "CommandButton(" not in layout
    # The rail arms tools through ActivateTool, not by minting a second set of
    # in-page ToolButton instances. (AddToolRailToolButton is the rail's own
    # builder, hence the lookbehind.)
    assert not re.search(r"(?<!Rail)ToolButton\(", layout)

    interaction = controls.split("private void ApplyInteractionModeControls()", 1)[1]
    interaction = interaction.split("private void ApplyEmbeddedToolPanelVisibility", 1)[0]
    assert "RestorePlacementLayoutForNonMeshMode();" in interaction
    assert "ApplyToolRailEditMeshLayout();" in interaction
    assert "if (!IsToolRailActive)" in controls

    # Leaving mesh edit returns only the sections placement mode shares with
    # the rail, in the cells they were built in; the mesh-edit-only sections
    # keep their rail pages as their one home.
    activate = layout.split("private void ActivateToolRailLayout()", 1)[1]
    activate = activate.split("private void RestorePlacementLayoutForNonMeshMode()", 1)[0]
    assert "CapturePlacementSectionHomes();" in activate
    restore = layout.split("private void RestorePlacementLayoutForNonMeshMode()", 1)[1]
    restore = restore.split("private void CapturePlacementSectionHomes()", 1)[0]
    assert "ReturnPlacementSectionsToFlanks();" in restore
    assert "ApplySavedToolPanelLayout();" in restore
    homes = layout.split("private void CapturePlacementSectionHomes()", 1)[1]
    homes = homes.split("private void ReturnPlacementSectionsToFlanks()", 1)[0]
    assert "_leftToolStack.GetCellPosition(_partPickSection)" in homes
    assert "_leftToolStack.GetCellPosition(_viewportSection)" in homes


def test_tool_rail_is_a_flat_tool_list_and_pins_the_scene_groups() -> None:
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    contracts = _source("EditMeshLayoutContracts.cs")
    rows = _source("EditMeshToolListContract.cs")

    # One flat list: every armable tool is its own row that arms exactly the
    # tool it names, and the command pages keep one reveal-only row each. There
    # are no category rows.
    tool_list = _source("ExperimentForm.ToolList.cs")
    for key, const, caption in (
        ("select", "Select", "Select"),
        ("move", "Move", "Move"),
        ("grab", "Grab", "Grab"),
        ("smooth", "Smooth", "Smooth"),
        ("inflate", "Inflate", "Inflate"),
        ("pinch", "Pinch", "Pinch"),
    ):
        assert f'public const string {const} = "{key}";' in rows
        assert f"new(ToolListRowKind.Tool, Keys.{const}," in rows
        # The caption is a literal at the callsite that sinks it, so the
        # localization manifest can key it.
        assert f'RowKeys.{const} => "{caption}",' in tool_list
    for page, const, caption in (
        ("Topology", "Topology", "Topology"),
        ("MorphRefit", "Morph", "Morph & Refit"),
        ("Viewport", "Viewport", "Viewport"),
    ):
        assert f"new(ToolListRowKind.CommandPage, Keys.{const}, ToolRailPage.{page})" in rows
        assert f'"{caption}"' in tool_list
    assert rows.count("new(ToolListRowKind.CommandPage") == 3
    assert "Keys.Colour" not in rows
    assert "ToolRailPage.Colour" not in contracts
    assert rows.count("new(ToolListRowKind.Tool") == 6
    # The built list is checked against the executed contract inventories, and
    # those inventories are still the rail's.
    assert "EditMeshToolListContract.RequireCompleteList(" in _source(
        "ExperimentForm.ToolList.cs"
    )
    assert "EditMeshLayoutContracts.RailToolOrder.SequenceEqual(toolKeys" in rows
    assert "public static readonly string[] RailToolOrder" in contracts
    assert "public static readonly ToolRailPage[] RailCommandPageOrder" in contracts

    # Parts and Action History remain nonmodal scene data. Viewport settings
    # move into one reveal-only row in the left list to free the right column.
    for absent in ("ToolRailPage.Parts", "ToolRailPage.History"):
        assert absent not in layout
        assert absent not in rows
    assert "ToolRailPage.Viewport" in layout
    assert "ToolRailPage.Viewport" in rows

    activate = layout.split("private void ActivateToolRailLayout()", 1)[1]
    activate = activate.split("private void RestorePlacementLayoutForNonMeshMode", 1)[0]
    assert "AddRailSection(_railSelectionStack, _selectionSection, row: 0);" in activate
    assert "AddRailSection(_railSelectionStack, _partPickSection, row: 1);" in activate
    for page, section in (
        ("Transform", "_transformSection"),
        ("Brush", "_brushSection"),
        ("Topology", "_topologySection"),
        ("MorphRefit", "_morphRefitSection"),
        ("Viewport", "_viewportSection"),
    ):
        assert f"AddRailSection(_toolRailPages[ToolRailPage.{page}], {section});" in activate
    # The scene column keeps its data-heavy groups ordered and always on screen.
    assert "AddRailSection(_sceneInspectorColumn, _partsSection, row: 0);" in activate
    assert "AddRailSection(_sceneInspectorColumn, _layersSection, row: 1);" in activate
    assert "AddRailSection(_sceneInspectorColumn, _actionHistorySection, row: 2);" in activate
    assert "AddRailSection(_sceneInspectorColumn, _viewportSection" not in activate

    # Both flanks are in use: the mesh is tall and narrow, so width is the
    # cheap axis and the viewport keeps the full window height.
    assert "_leftToolSplit.Panel1Collapsed = false;" in activate
    assert "_rightToolSplit.Panel2Collapsed = false;" in activate
    assert "_viewportWorkspaceSplit.Panel2Collapsed = true;" in activate
    assert '_viewport.ActivatePresentationView("editable");' in layout
    assert "_presentationViewSelector.Visible = !compactEditableOnly;" in layout


def test_rail_reveals_never_arm_and_only_tool_buttons_arm() -> None:
    """Revealing a page and choosing a tool are fully separate.

    A rail tool button arms exactly the tool it names, through the same
    ActivateTool path as the buttons inside the pages. Revealing a page —
    whether from a command-page entry, a layout re-activation, or the sync
    that follows the active tool — never arms anything, so a command page can
    open without disturbing the live tool and a redundant mesh_edit frame
    cannot throw the reader back to Select.
    """
    layout = _source("ExperimentForm.EditMeshLayouts.cs")
    contracts = _source("EditMeshLayoutContracts.cs")
    program = _source("Program.cs")

    assert "internal enum ToolRailPage" in contracts
    assert "public static ToolRailPage? ToolRailPageForTool(string? tool)" in contracts
    assert "_ => null," in contracts
    # No page may answer for orbit, or entering Edit Mesh arms a tool.
    assert "ToolRailPage.Camera" not in contracts
    assert "ToolRailPage.Camera" not in layout
    assert '"orbit"' not in contracts.split("RailPageOwnsTool", 1)[1].split("ToolRailPageForTool", 1)[0]

    rows = _source("EditMeshToolListContract.cs")
    tool_list = _source("ExperimentForm.ToolList.cs")

    # The camera has no list row and no tool panel of its own.
    assert '"orbit"' not in rows
    assert "_cameraSection" not in layout
    assert "_cameraSection" not in program

    # A tool row arms exactly the tool it names; a command row only reveals.
    # The click also announces the choice, because the host keeps its own notion
    # of the tool and republishes it on every control refresh -- without the
    # announcement that refresh takes the reader's tool away again.
    assert (
        "button.Click += (_, _) => ActivateTool(row.Key, caption, announce: true);"
        in tool_list
    )
    assert "button.Click += (_, _) => ShowToolRailPage(row.Page);" in tool_list

    # Revealing is pure: ShowToolRailPage takes no arming flag and never
    # activates a tool. The old page-default arming seam is gone entirely.
    assert "private void ShowToolRailPage(ToolRailPage? page)" in layout
    assert "armDefaultTool" not in layout
    assert "DefaultToolForRailPage" not in layout
    assert "DefaultToolForRailPage" not in contracts
    show = layout.split("private void ShowToolRailPage(ToolRailPage? page)", 1)[1]
    show = show.split("private void RevealToolRailPage", 1)[0]
    assert "ActivateTool(" not in show
    assert "SetButtonAccent(pair.Value, pair.Key == page);" in show
    # There is no dock header to retitle. The open row is the page's name, so a
    # header naming a family while a tool was armed cannot come back.
    assert "_toolRailPanelHeader" not in layout
    assert "ApplyToolListExpansion(page);" in show
    # A null page collapses the list back to rows and parks the body host.
    expand = tool_list.split("private void ApplyToolListExpansion", 1)[1]
    assert "_toolListBodyHost.Visible = expandedBaseCell is not null;" in expand
    assert "EditMeshToolListContract.ParkedBodyCell" in expand

    # The unopened rail resolves its page from the live tool rather than from a
    # remembered default, and only then marks itself chosen.
    assert "private ToolRailPage? _selectedToolRailPage;" in layout
    first_reveal = layout.split("if (!_toolRailPageSelected)", 1)[1]
    first_reveal = first_reveal.split("ShowToolRailPage(_selectedToolRailPage", 1)[0]
    assert "_selectedToolRailPage = ToolRailPageForActiveTool();" in first_reveal
    assert "ShowToolRailPage(_selectedToolRailPage);" in layout

    # One owner for the rules: ExperimentForm must not keep a second copy that
    # the executed smoke would not be checking.
    assert "private static bool RailPageOwnsTool" not in layout
    assert "private static bool RailPageIsModal" not in layout
    assert "EditMeshLayoutContracts.ToolRailPageForTool(_viewport.ActiveTool)" in layout

    # Clearing the rail because the tool is orbit must only close a modal page.
    # Topology, Morph & Refit and Viewport arm nothing, so the viewport sits on
    # orbit the whole time one is open -- closing on the tool alone shut them
    # the moment the host published a disabled mesh-edit tool state, which it
    # does on every selection change.
    sync = layout.split("private void SyncToolRailPageToActiveTool()", 1)[1]
    sync = sync.split("private void ApplyToolRailSplitterLayout", 1)[0]
    assert "EditMeshLayoutContracts.RailPageIsModal(_selectedToolRailPage.Value)" in sync
    assert "if (page is null || EditMeshLayoutContracts.RailPageOwnsTool(" not in sync

    # The rail's tool buttons accent by the armed tool however it was chosen.
    controls = _source("ExperimentForm.Controls.cs")
    refresh = controls.split("private void RefreshToolButtonStates()", 1)[1]
    refresh = refresh.split("private void RefreshGizmoButtonStates()", 1)[0]
    assert "_toolRailToolButtons" in refresh


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

    # The badge names whatever the modifier is bound to now — and whichever of
    # the middle and right drags share the move — one whole literal per
    # combination so each stays a single translatable phrase.
    update = presentation.split("private void UpdateViewportNavigationStrip(", 1)[1]
    update = update.split("private Control BuildAuthoringStatusFooter", 1)[0]
    assert "_orbitChipBadge.Text = CameraGestureBadgeText(" in update
    assert "_panChipBadge.Text = CameraGestureBadgeText(" in update
    for literal in (
        '"Alt + left-drag"',
        '"Ctrl + left-drag"',
        '"Shift + left-drag"',
        '"Alt or Ctrl + left-drag"',
        '"Shift + left-drag, or middle / right-drag"',
        '"Shift + left-drag, or middle-drag"',
        '"Shift + left-drag, or right-drag"',
    ):
        assert literal in update, literal

    # The drag buttons resolve through their bindings the same way, so a
    # middle-drag or right-drag can orbit instead of pan.
    assert "string.Equals(CameraMiddleDrag, CameraModifierBindings.DragPan" in input_source
    assert "string.Equals(CameraRightDrag, CameraModifierBindings.DragOrbit" in input_source

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
    # uses the stacked form instead.
    activate = layout.split("private void ActivateToolRailLayout()", 1)[1]
    activate = activate.split("private void RestorePlacementLayoutForNonMeshMode", 1)[0]
    assert "ExitCompactMorphLayout();" in activate
    assert "SetMorphCollapseHeaderVisible(false);" in activate
    assert "EnterCompactMorphLayout(" not in layout
    # The dock header names the page, so the section's own collapse header
    # never comes back: the rail is the only Edit Mesh layout.
    assert "SetMorphCollapseHeaderVisible(true);" not in layout


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


def test_returning_to_placement_forces_its_own_layout_pass() -> None:
    layout = _source("ExperimentForm.EditMeshLayouts.cs")

    restore = layout.split("private void RestorePlacementLayoutForNonMeshMode()", 1)[1]
    restore = restore.split("private void CapturePlacementSectionHomes()", 1)[0]
    # The returned sections land while suspended and resume without their own
    # layout pass, so they keep dock-time bounds until something forces the
    # measure.
    assert restore.index("ResumeAllEditMeshLayouts();") < restore.index(
        "PerformPlacementFlankLayout();"
    )
    performer = layout.split("private void PerformPlacementFlankLayout()", 1)[1]
    performer = performer.split("private void SuspendAllEditMeshLayouts", 1)[0]
    for target in ("_leftToolStack", "_rightToolStack", "_leftToolPanel", "_rightToolPanel"):
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
    # The two sizes share a row so the camera presets stay above the fold.
    assert 'LabeledControl("Wire px", wireWidth)' in overlay
    assert 'LabeledControl("Vertex px", vertexSize)' in overlay


def test_edit_mesh_has_a_nonvisual_round_trip_construction_gate() -> None:
    entry = _source("ProgramEntry.cs")
    smoke = _source("EditMeshLayoutSmoke.cs")
    gate = (DOTNET_ROOT.parents[1] / "scripts" / "codex_check.ps1").read_text(
        encoding="utf-8-sig"
    )

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
    assert "MoveControl(viewport," not in smoke
    assert 'MoveControl(viewportSection, pages["Viewport"]' in smoke
    assert "zero_size_splitter_construction" in smoke
    # The round trip is mesh-edit entry and the return to the placement
    # flanks: the Classic layout is gone.
    assert '["round_trip_layout"] = "placement"' in smoke
    assert '"classic"' not in smoke
    # The flat rail inventories are executed, not just quoted.
    assert "EditMeshLayoutContracts.RailToolOrder" in smoke
    assert "EditMeshLayoutContracts.RailCommandPageOrder" in smoke
    assert "rail_tool_count" in smoke
    assert "rail_command_page_count" in smoke
    assert "$LayoutPayload.pages_visited.Count -ne 6" in gate
    assert "$LayoutPayload.rail_command_page_count -ne 3" in gate
    assert "RailPageIsModal" in smoke
    assert "RequireCompleteRail" in smoke
    for page in ("Selection", "Transform", "Brush", "Topology", "Morph & Refit", "Viewport"):
        assert f'"{page}"' in smoke


def test_resident_editor_accepts_the_host_application_theme() -> None:
    program = _source("Program.cs")
    protocol = _source("ExperimentForm.Protocol.cs")
    theme = _source("ExperimentForm.UiTheme.cs")
    provenance = _source("HelperBuildProvenance.cs")

    assert "static readonly Color ThemeWindowBackground" not in program
    assert 'case "ui_theme_state": HandleUiThemeState(root); break;' in protocol
    assert '"ui_theme_state_v1"' in provenance
    assert "TryApplyUiThemeState" in theme
    assert "ApplyThemeToControlTree(this, previous, palette);" in theme
    assert 'ThemeUsesDarkControls() ? "DarkMode_Explorer" : "Explorer"' in theme


def test_embedded_authoring_tool_panels_build_hidden_before_reveal() -> None:
    """The expensive panel tree must be complete before the user can see it.

    Embedded startup already stays hidden through renderer and texture
    preparation. Building the authoring panels in that hidden interval prevents
    the torn intermediate WinForms layout and leaves Edit Mesh with no panel
    construction work on its click path. Mesh-edit entry remains an idempotent
    backstop for nonstandard construction paths.

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

    # Embedded startup builds and realizes the full authoring tree while the
    # host still owns the visible loading surface.
    startup_body = program.split("private void RunStartupRealization()", maxsplit=1)[1].split(
        "private void PublishReady(", maxsplit=1
    )[0]
    assert "EnsureAuthoringToolPanelsReady();" in startup_body
    assert startup_body.index("EnsureAuthoringToolPanelsReady();") < startup_body.index(
        "RealizeClassicToolFlanks();"
    )

    # Ready publication may not mutate the visible control tree afterwards.
    ready_body = program.split("private void PublishReady(", maxsplit=1)[1].split(
        "private bool TryEmbedOrFail(", maxsplit=1
    )[0]
    assert "EnsureAuthoringToolPanelsReady" not in ready_body

    # Mesh-edit entry remains a backstop, before anything walks the section lists.
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
    ensure_body = program.split("private void EnsureAuthoringToolPanelsReady()", maxsplit=1)[1].split(
        "\n    private ", maxsplit=1
    )[0]
    assert ensure_body.index("PrimeToolRailSectionOwnership();") < ensure_body.index(
        "ApplySavedToolPanelLayout();"
    )
    prime_body = layouts.split("private void PrimeToolRailSectionOwnership()", maxsplit=1)[1].split(
        "\n    private ", maxsplit=1
    )[0]
    assert "AddRailSection(_railSelectionStack, _selectionSection, row: 0);" in prime_body
    assert "AddRailSection(_sceneInspectorColumn, _actionHistorySection, row: 2);" in prime_body
    assert "_partPickSection" not in prime_body
    assert "_viewportSection" not in prime_body

    # And the result has to stay observable from outside the process.
    assert '["authoring_tool_panels_present"] = _leftToolPanel is not null && _rightToolPanel is not null' in material_protocol
    assert '["lifecycle_counts"] = LifecycleCountsPayload(),' in protocol


def test_tool_list_pages_never_repeat_the_row_that_opened_them() -> None:
    """A page holds settings; the row that opened it holds the tool's name.

    This is the defect the tool list exists to remove. The Brush page carried
    Smooth / Inflate / Pinch buttons while the rail carried the same three, so
    arming Inflate on the left lit an Inflate button on the right and the header
    above it said BRUSH. Transform did the same with Move and Grab, and Selection
    with Select.
    """
    program = _source("Program.cs")

    # Orbit is the one tool that keeps an in-page button: it has no list row,
    # because the camera is reached through the navigation strip's modifiers.
    in_page_tools = set(re.findall(r'ToolButton\("[^"]+",\s*"(\w+)"\)', program))
    assert in_page_tools == {"orbit"}, (
        "A page mints a tool button for a tool the list already names: "
        f"{sorted(in_page_tools - {'orbit'})}"
    )

    # Grow and Shrink are commands, not a second way to arm Select, so the
    # Selection page keeps them.
    assert 'CommandButton("Grow", "grow")' in program
    assert 'CommandButton("Shrink", "shrink")' in program


def test_brush_page_previews_the_falloff_it_will_apply() -> None:
    program = _source("Program.cs")
    curve = _source("ExperimentForm.FalloffCurve.cs")

    assert "BuildFalloffCurve()" in program
    # Strength scales the profile and the falloff reshapes it, so both redraw.
    # Radius does not: the profile is normalised over it.
    assert "_falloff.SelectedIndexChanged += (_, _) => RefreshFalloffCurve();" in curve
    assert "_strength.ValueChanged += (_, _) => RefreshFalloffCurve();" in curve
    assert "_radius.ValueChanged" not in curve


def test_falloff_preview_matches_the_native_brush_weight() -> None:
    """The preview draws what native mesh core applies, or it misreports strokes.

    ``brush_falloff_weight`` in native mesh core is the authority. This guards
    the C# copy against drifting away from it; the executed values are asserted
    in the headless layout gate.
    """
    profile = _source("BrushFalloffProfile.cs")
    native = (
        Path(__file__).resolve().parents[1]
        / "native"
        / "cdmw_mesh_core"
        / "src"
        / "owners"
        / "geometry_uv_04.cpp"
    ).read_text(encoding="utf-8")

    body = native.split("double brush_falloff_weight(", 1)[1].split("\n}", 1)[0]

    # Every branch the authority has, with the same expression.
    for expression in (
        "distance <= 1e-8 ? 1.0 : 0.0",
        "1.0 - normalized",
        "(1.0 - normalized) * (1.0 - normalized)",
        "1.0 - (t * t * (3.0 - 2.0 * t))",
    ):
        assert expression in body, f"the C++ authority changed: {expression}"
        assert expression in profile, f"the C# port drifted: {expression}"

    # Same guards, same order of tests, same fallback.
    for guard in ("radius <= 1e-8", "normalized >= 1.0"):
        assert guard in body
        assert guard in profile
    for name in ("linear", "sharp", "constant"):
        assert f'== "{name}"' in body or f'falloff == "{name}"' in body
        assert f'= "{name}"' in profile

    # The pointer back to the authority has to survive, or the next reader will
    # not know which copy to change first.
    assert "geometry_uv_04.cpp" in profile


def test_provisional_grab_echo_weights_with_the_active_falloff_profile() -> None:
    """The grab echo weights with the shared native-profile port and the live option.

    A private falloff copy hardcoded to "smooth" made every non-smooth grab
    snap at stroke end, when the authoritative surface replaced a provisional
    one shaped by a different profile.
    """
    strokes = _source("MeshViewport.ProvisionalStrokes.cs")

    assert "BrushFalloffProfile.Weight(distance, Math.Max(radius, 0.001f), falloff)" in strokes
    assert "FalloffOption(options)" in strokes
    # The private duplicate profile stays gone; BrushFalloffProfile is the one
    # guarded port of the native weight.
    assert "BrushFalloffWeight(" not in strokes
    assert '"smooth"' not in strokes


def test_tool_column_width_is_measured_rather_than_reserved() -> None:
    metrics = _source("EditMeshToolColumnMetrics.cs")
    tool_list = _source("ExperimentForm.ToolList.cs")
    layout = _source("ExperimentForm.EditMeshLayouts.cs")

    # The fixed reservations the rail-and-panel layout used are gone.
    for gone in ("ToolRailWidth", "ToolPropertyWidth", "SceneInspectorWidth"):
        assert gone not in layout, f"a fixed dock width survived: {gone}"

    # The dock asks what is in it.
    assert "GetPreferredSize(Size.Empty)" in tool_list
    assert "ScaleToolPanelWidth(MeasureToolColumnWidth())" in layout
    assert "MeasureInspectorWidth()" in layout

    # A closed column collapses to its rows; Morph & Refit is the one page
    # allowed past the ceiling, because its three-button row clips rather
    # than wraps.
    collapsed = int(re.search(r"CollapsedFloor = (\d+)", metrics).group(1))
    expanded = int(re.search(r"ExpandedFloor = (\d+)", metrics).group(1))
    ceiling = int(re.search(r"ExpandedCeiling = (\d+)", metrics).group(1))
    uncapped = int(re.search(r"UncappedCeiling = (\d+)", metrics).group(1))
    assert collapsed < expanded < ceiling < uncapped
    assert "page == ToolRailPage.MorphRefit" in metrics
