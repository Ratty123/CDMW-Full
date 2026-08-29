namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private readonly List<Button> _directAuthoringBlockedButtons = new();
    private bool _directAuthoringExactOutputRequired;
    private bool DirectAuthoringRestrictionsActive =>
        _options.DirectAuthoring && _directAuthoringExactOutputRequired;

    private void BlockDirectAuthoringButton(Button button, string reason)
    {
        if (!_options.DirectAuthoring)
        {
            return;
        }
        SetHelpText(button, reason);
        _directAuthoringBlockedButtons.Add(button);
        ReassertDirectAuthoringBlockedButtons();
    }

    private void ReassertDirectAuthoringBlockedButtons()
    {
        foreach (var button in _directAuthoringBlockedButtons)
        {
            // Unsupported exact-PAC operations stay visible so the Topology,
            // Parts and Layers surfaces are complete and their help can explain
            // the writeback boundary. Hiding them made the editor look broken.
            button.Visible = true;
            if (DirectAuthoringRestrictionsActive)
            {
                button.Enabled = false;
            }
        }
    }

    private void ApplyDirectAuthoringOutputContract(bool exactOutputRequired)
    {
        _directAuthoringExactOutputRequired = exactOutputRequired;
        foreach (var button in _topologyMutationButtons)
        {
            button.Enabled = !_morphUnbaked;
        }
        RefreshCreatePartFromSelectionButton();
        RefreshGeometryLayerButtonState();
        RefreshPartDetail();
        ReassertDirectAuthoringBlockedButtons();
        if (_toolRailPageButtons.TryGetValue(ToolRailPage.Topology, out var topologyRow))
        {
            ApplyToolListRowDescription(topologyRow, "topology");
        }
    }

    private static string DirectAuthoringCommandBlocker(string command) => command switch
    {
        "duplicate" => "Duplicate is unavailable because the exact PAC writer cannot add protected geometry records.",
        "separate" => "Create Part is unavailable because the exact PAC writer cannot add a protected submesh record.",
        "subdivide" => "Subdivide is unavailable because derived PAC vertices cannot preserve protected bytes.",
        "refine_smooth" => "Refine Smooth is unavailable because derived PAC vertices cannot preserve protected bytes.",
        "extrude" => "Extrude has no exact protected-record writeback route.",
        "inset" => "Inset has no exact protected-record writeback route.",
        "loop_cut" => "Loop Cut derives vertices whose protected bytes cannot be derived.",
        "edge_split" => "Edge Split has no exact protected-record writeback route.",
        "bridge" => "Bridge has no exact protected-record writeback route.",
        "merge" => "Merge has no exact protected-record writeback route.",
        "weld" => "Weld has no exact protected-record writeback route.",
        "fill" => "Fill has no exact protected-record writeback route.",
        "copy" or "paste" or "layer_delete" => "Geometry layers that change topology have no exact PAC writeback route.",
        "toggle_visibility" => "Part visibility editing has no stored output authority in direct authoring.",
        _ => string.Empty,
    };

    private void ConfigureToolPanelListsAndFinish()
    {
    _submeshList.BackColor = ThemeInputBackground;
    _submeshList.ForeColor = ThemeText;
    _submeshList.BorderStyle = BorderStyle.FixedSingle;
    _submeshList.Height = 96;
    _submeshList.Font = new Font(Font.FontFamily, 8.5f);
    ApplyDarkScrollbars(_submeshList);
    _actionHistoryList.Name = "ResidentActionHistoryList";
    _actionHistoryList.BackColor = ThemeInputBackground;
    _actionHistoryList.ForeColor = ThemeText;
    _actionHistoryList.BorderStyle = BorderStyle.FixedSingle;
    _actionHistoryList.IntegralHeight = false;
    _actionHistoryList.SelectionMode = SelectionMode.None;
    _actionHistoryList.Height = 96;
    _actionHistoryList.Font = new Font(Font.FontFamily, 8.5f);
    _actionHistoryList.Items.Add("No edit actions yet");
    ApplyDarkScrollbars(_actionHistoryList);

    if (!_options.DirectAuthoring)
    {
        var finish = StyledButton(_options.Embedded ? "Finish Edit Mesh" : "Save Edited Package", height: 30);
        finish.Click += (_, _) =>
        {
            if (_options.Embedded)
            {
                RequestFinishEditMesh();
            }
            else
            {
                SaveAndReport();
            }
        };
        _sessionFinishButton = finish;
    }

    ConfigureCheckBox(_partPick, "Part Pick", isChecked: false);
    _partPick.CheckedChanged += (_, _) =>
    {
        _viewport.PartPickEnabled = _partPick.Checked;
        if (_partPick.Checked)
        {
            _statusLabel.Text = "Part Pick enabled; selection requests target source parts.";
        }
        else
        {
            _statusLabel.Text = "Part Pick disabled; clearing selection.";
            WriteCommandRequest("clear_selection");
        }
    };
    }

    private (Panel Left, Panel Right) BuildToolPanels()
    {
        ConfigureToolPanelListsAndFinish();
        var left = CreateToolPanel(
            "DotNetMeshEditorLeftToolPanel",
            "DotNetMeshEditorLeftToolScroll",
            "DotNetMeshEditorLeftToolStack",
            _toolPanelLayout.LeftWidth,
            out var leftStack);
        var right = CreateToolPanel(
            "DotNetMeshEditorRightToolPanel",
            "DotNetMeshEditorRightToolScroll",
            "DotNetMeshEditorRightToolStack",
            _toolPanelLayout.RightWidth,
            out var rightStack);
        _leftToolStack = leftStack;
        _rightToolStack = rightStack;
        StartupTiming.Mark("tool_panels_created");
        // Every section below is appended as its own row, and an AutoSize
        // stack re-measures its whole column on each append. The stacks are
        // detached while they are built, so nothing is on screen to keep
        // current; one layout when the panels are attached is the right amount.
        leftStack.SuspendLayout();
        rightStack.SuspendLayout();
        try
        {
            BuildToolPanelSections(leftStack, rightStack);
        }
        finally
        {
            leftStack.ResumeLayout(performLayout: false);
            rightStack.ResumeLayout(performLayout: false);
        }
        StartupTiming.Mark("viewport_section_built");

        return (left, right);
    }

    private void BuildToolPanelSections(TableLayoutPanel leftStack, TableLayoutPanel rightStack)
    {

        // The session commands live on the compact session bar, which adopts
        // them when it is attached; until then they are parentless.
        var clearSelectionButton = CommandButton("Clear Selection", "clear_selection");
        var selectAllButton = CommandButton("Select All", "select_all");
        var invertButton = CommandButton("Invert", "invert");
        var undoButton = CommandButton("Undo", "undo");
        var redoButton = CommandButton("Redo", "redo");
        _sessionClearSelectionButton = clearSelectionButton;
        _sessionSelectAllButton = selectAllButton;
        _sessionInvertButton = invertButton;
        _undoButton = undoButton;
        _redoButton = redoButton;
        undoButton.Enabled = false;
        redoButton.Enabled = false;
        _actionHistorySection = AddHelpSection(
            rightStack,
            "Action History",
            "Every applied mesh edit and selection change appears here. Undone actions remain visible for Redo.",
            out _,
            _actionHistoryList);
        _actionHistorySection.Name = "CompactActionHistorySection";
        _meshEditOnlySections.Add(_actionHistorySection);
        StartupTiming.Mark("action_history_section_built");
        _morphRefitSection = BuildMorphRefitSection(rightStack);
        StartupTiming.Mark("morph_refit_section_built");
        // The Part Pick section is gone: the Parts panel on the right is the
        // only part-selection surface. The hidden compatibility control remains
        // unchecked so no viewport input path can arm source-part picking.
        _partPick.Visible = false;
        _partPickSection = null;
        var duplicatePartButton = StyledActionButton(
            "Duplicate",
            () => WriteCommandRequest("duplicate", new Dictionary<string, object?>
            {
                ["target_mode"] = "source",
            }));
        var deletePartButton = StyledActionButton(
            "Delete",
            () => WriteCommandRequest("delete", new Dictionary<string, object?>
            {
                ["target_mode"] = "source",
            }));
        BlockDirectAuthoringButton(
            duplicatePartButton,
            "Duplicate Part is unavailable because the exact PAC writer cannot add a protected submesh record.");
        BlockDirectAuthoringButton(
            deletePartButton,
            "Delete Part is unavailable because the exact PAC writer cannot remove a protected submesh record.");
        RegisterTopologyMutationButton(duplicatePartButton);
        RegisterTopologyMutationButton(deletePartButton);
        _partsSection = BuildPartsSection(rightStack, duplicatePartButton, deletePartButton);
        _partsSection.Name = "CompactPartsSection";
        _meshEditOnlySections.Add(_partsSection);
        StartupTiming.Mark("parts_section_built");
        _layersSection = BuildGeometryLayersSection(rightStack);
        _layersSection.Name = "CompactGeometryLayersSection";
        _meshEditOnlySections.Add(_layersSection);
        StartupTiming.Mark("layers_section_built");
        var createPartButton = CreatePartFromSelectionButton();
        var selectionControls = new List<Control>
        {
            LabeledControl("Selection target", _selectionTarget),
            LabeledControl("Select shape", _selectionShape),
            LabeledControl("Selection mode", _selectionOperation),
            _xray,
            // No Select button: its list row arms the tool. Grow and Shrink are commands, so they stay.
            ButtonRow(CommandButton("Grow", "grow"), CommandButton("Shrink", "shrink")),
        };
        selectionControls.Add(createPartButton);
        var selectionSection = AddHelpSection(
            leftStack,
            "Selection",
            "Click or drag on the mesh to select vertices, wires, or faces. Brush, Rectangle and Lasso never select PARTS; X-Ray selects through the mesh.",
            out _,
            selectionControls.ToArray());
        selectionSection.Name = "CompactSelectionSection";
        _selectionSection = selectionSection;
        _meshEditOnlySections.Add(selectionSection);
        _selectionTarget.SelectedIndexChanged += (_, _) => RefreshCreatePartFromSelectionButton();
        _placementSection = AddSection(leftStack, "Placement",
            SceneComparisonControl(),
            ButtonRow(GizmoButton("Move", "move"), GizmoButton("Rotate", "rotate"), GizmoButton("Scale", "scale")));
        _placementSection.Name = "ClassicPlacementSection";
        _placementOnlySections.Add(_placementSection);
        StartupTiming.Mark("selection_and_placement_sections_built");
        var transformSection = AddHelpSection(
            leftStack,
            "Transform",
            "Move drags the current selection freely in screen space; Grab pulls vertices under the brush. "
            + "The axis buttons nudge the selection by the exact translate step.",
            out _,
            LabeledControl("Translate step", _translateStep),
            LabeledControl("Grab radius", _grabRadius),
            AxisNudgeRow("x"),
            AxisNudgeRow("y"),
            AxisNudgeRow("z"));
        transformSection.Name = "CompactTransformSection";
        _transformSection = transformSection;
        _meshEditOnlySections.Add(transformSection);
        var brushSection = AddHelpSection(
            leftStack,
            "Brush Tools",
            "Brushes paint the replacement under the yellow circle; no preselection is required. Left-drag to apply. Right-drag pans; wheel zooms.",
            out _,
            LabeledControl("Radius", _radius),
            LabeledControl("Strength", _strength),
            LabeledControl("Falloff", _falloff),
            BuildFalloffCurve());
        brushSection.Name = "CompactBrushSection";
        _brushSection = brushSection;
        _meshEditOnlySections.Add(brushSection);
        BuildOutputPolicyTopologySection(leftStack);
        StartupTiming.Mark("transform_brush_topology_sections_built");
        _viewportSection = AddHelpSection(
            leftStack,
            "Viewport",
            "Choose the preview mode, topology appearance, viewport background, or a camera preset. Mouse and keyboard bindings update with the active tool.",
            out var viewportHelpMarker,
            PreviewModeControl(),
            OverlayAppearanceControls(),
            ViewportColorControls(),
            // Four rows of three rather than three plus a lone Orbit: the whole
            // group has to fit above the fold, or the camera presets are behind
            // a scroll on a 1080p column.
            ButtonRow(CameraButton("Front", "front"), CameraButton("Back", "back"), CameraButton("Top", "top")),
            ButtonRow(CameraButton("Left", "left"), CameraButton("Right", "right"), CameraButton("Bottom", "bottom")),
            ButtonRow(StyledActionButton("-15", () => _viewport.RotateYawDegrees(-15.0f)), StyledActionButton("+15", () => _viewport.RotateYawDegrees(15.0f)), StyledActionButton("Fit", _viewport.FrameMesh)),
            ToolButton("Orbit", "orbit"));
        _viewportSection.Name = "CompactViewportSection";
        _viewportHelpMarker = viewportHelpMarker;
    }
}
