namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private const int ToolRailWidth = 74;
    private const int ToolRailButtonHeight = 48;
    private const int ToolPropertyWidth = 340;
    private const int SceneInspectorWidth = 336;

    private enum EditMeshLayoutMode
    {
        Classic,
        ToolRail,
    }

    /// <summary>
    /// The modal tools, one rail button each. Only these swap with the rail —
    /// the scene groups (Parts, Action History, Viewport) are not modal and
    /// live permanently in the right inspector. Declaration order is rail order.
    /// </summary>
    private enum ToolRailPage
    {
        Selection,
        Transform,
        Brush,
        Topology,
        Colour,
        MorphRefit,
    }

    private readonly Dictionary<ToolRailPage, Button> _toolRailButtons = new();
    private readonly Dictionary<ToolRailPage, Panel> _toolRailPages = new();
    // Entering Edit Mesh presents the tool rail. Classic remains the control
    // tree's construction and non-mesh-mode state, and stays reachable from
    // the session bar.
    private EditMeshLayoutMode _requestedEditMeshLayout = EditMeshLayoutMode.ToolRail;
    private EditMeshLayoutMode _activeEditMeshLayout = EditMeshLayoutMode.Classic;
    private ToolRailPage _selectedToolRailPage = ToolRailPage.Selection;
    private bool _toolRailPageSelected;
    private bool _applyingToolRailSplitterLayout;
    private Point _classicLeftScrollPosition;
    private Point _classicRightScrollPosition;

    private TableLayoutPanel? _editMeshLayoutHost;
    private Control? _classicEditMeshLayoutRoot;
    private SplitContainer? _viewportWorkspaceSplit;
    private Control? _compactSessionBar;
    private FlowLayoutPanel? _compactSessionCommandHost;
    private Panel? _compactSessionFinishHost;
    private Panel? _leftToolModeHost;
    private Panel? _rightToolModeHost;
    private TableLayoutPanel? _toolDock;
    private Label? _toolRailPanelHeader;
    private TableLayoutPanel? _railSelectionStack;
    private TableLayoutPanel? _sceneInspectorColumn;
    private Control? _presentationViewportRegion;

    private Button? _sessionFinishButton;
    private Button? _sessionClearSelectionButton;
    private Button? _sessionSelectAllButton;
    private Button? _sessionInvertButton;
    private Control? _classicSessionSelectionRow;
    private Control? _classicSessionHistoryRow;
    private GroupBox? _classicSessionSection;
    private TableLayoutPanel? _classicSessionBody;
    private GroupBox? _actionHistorySection;
    private Control? _morphRefitSection;
    private GroupBox? _partPickSection;
    private GroupBox? _partsSection;
    private GroupBox? _selectionSection;
    private GroupBox? _placementSection;
    private GroupBox? _transformSection;
    private GroupBox? _brushSection;
    private GroupBox? _topologySection;
    private GroupBox? _viewportSection;

    private bool IsToolRailActive =>
        _activeEditMeshLayout == EditMeshLayoutMode.ToolRail;

    private void InitializeEditMeshLayoutHost(Control classicRoot)
    {
        _classicEditMeshLayoutRoot = classicRoot;
        _classicEditMeshLayoutRoot.Dock = DockStyle.Fill;
        BuildPermanentViewportWorkspace();
        BuildPermanentToolModeHosts();

        _editMeshLayoutHost = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "DotNetMeshEditorLayoutHost",
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemeWindowBackground,
        };
        _editMeshLayoutHost.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _editMeshLayoutHost.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));
        _editMeshLayoutHost.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _editMeshLayoutHost.Resize += (_, _) =>
        {
            if (IsToolRailActive)
            {
                ApplyToolRailSplitterLayout();
            }
        };
        _editMeshLayoutHost.Controls.Add(_classicEditMeshLayoutRoot, 0, 1);
        Controls.Add(_editMeshLayoutHost);
        // The session bar belongs to the tool rail Edit Mesh layout, so it
        // follows the same schedule as the panels it sits above.
        if (!DeferAuthoringToolPanels)
        {
            AttachCompactSessionBar();
        }
    }

    /// <summary>
    /// The session bar occupies row 0 of the layout host, a zero-height row
    /// until the tool rail claims it, so attaching it later is only a cell
    /// assignment and never touches the viewport's ancestry.
    /// </summary>
    private void AttachCompactSessionBar()
    {
        if (_options.SimplePreview || _compactSessionBar is not null || _editMeshLayoutHost is null)
        {
            return;
        }
        _compactSessionBar = BuildCompactSessionBar();
        _compactSessionBar.Visible = false;
        _editMeshLayoutHost.Controls.Add(_compactSessionBar, 0, 0);
    }

    private void BuildPermanentViewportWorkspace()
    {
        if (_rightToolSplit is null || _presentationViewportRegion is null)
        {
            throw new InvalidOperationException(
                "The permanent Edit Mesh viewport host requires the classic viewport split.");
        }
        // Panel2 stays collapsed in both layouts. The split is kept because it
        // is the resident renderer's permanent ancestor: re-parenting the D3D
        // surface to shorten this chain would recreate its Win32 handle.
        _viewportWorkspaceSplit = CreateCompactSplit(
            "EditMeshViewportWorkspaceSplit",
            Orientation.Horizontal,
            FixedPanel.Panel2);
        _viewportWorkspaceSplit.Panel2Collapsed = true;
        _rightToolSplit.Panel1.Controls.Add(_viewportWorkspaceSplit);
        // Attach the live viewport region only after its permanent ancestor
        // chain is in place. This is the sole Win32 parent assignment for the
        // resident renderer subtree.
        _viewportWorkspaceSplit.Panel1.Controls.Add(_presentationViewportRegion);
    }

    /// <summary>
    /// Both flanks host two mutually exclusive children: the classic scrolling
    /// tool panel, and this layout's dock. Swapping visibility keeps every live
    /// control instance parented to a stable ancestor.
    /// </summary>
    private void BuildPermanentToolModeHosts()
    {
        if (DeferAuthoringToolPanels)
        {
            // Preview never builds these; an embedded authoring host builds them
            // on first mesh-edit entry. Either way the flanks stay empty and
            // collapsed and the viewport keeps the same split ancestry.
            return;
        }
        AttachPermanentToolModeHosts();
    }

    private void AttachPermanentToolModeHosts()
    {
        if (_options.SimplePreview || _leftToolModeHost is not null)
        {
            return;
        }
        if (_leftToolSplit is null
            || _rightToolSplit is null
            || _leftToolPanel is null
            || _rightToolPanel is null)
        {
            throw new InvalidOperationException(
                "The permanent Edit Mesh tool hosts require the classic tool panels.");
        }

        _leftToolModeHost = new MeshEditorBufferedPanel
        {
            Name = "DotNetMeshEditorLeftToolModeHost",
            Dock = DockStyle.Fill,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        _leftToolPanel.Visible = true;
        _leftToolModeHost.Controls.Add(_leftToolPanel);
        var toolDock = BuildToolDock();
        toolDock.Visible = false;
        _leftToolModeHost.Controls.Add(toolDock);
        _leftToolSplit.Panel1.Controls.Add(_leftToolModeHost);

        _rightToolModeHost = new MeshEditorBufferedPanel
        {
            Name = "DotNetMeshEditorRightToolModeHost",
            Dock = DockStyle.Fill,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        _rightToolPanel.Visible = true;
        _rightToolModeHost.Controls.Add(_rightToolPanel);
        var inspector = BuildSceneInspector();
        inspector.Visible = false;
        _rightToolModeHost.Controls.Add(inspector);
        _rightToolSplit.Panel2.Controls.Add(_rightToolModeHost);
    }

    private Control BuildCompactSessionBar()
    {
        var bar = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "EditMeshSessionBar",
            Dock = DockStyle.Fill,
            ColumnCount = 4,
            RowCount = 1,
            Margin = new Padding(0),
            Padding = new Padding(14, 7, 14, 7),
            BackColor = ThemePanelBackground,
        };
        bar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        bar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        bar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        bar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        bar.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var title = new Label
        {
            Name = "EditMeshSessionTitle",
            Text = "Mesh Edit Session",
            AutoSize = true,
            UseMnemonic = false,
            Anchor = AnchorStyles.Left,
            Margin = new Padding(0, 0, 16, 0),
            ForeColor = ThemeStrongText,
            BackColor = ThemePanelBackground,
            Font = new Font(Font, FontStyle.Bold),
            AccessibleName = "Mesh Edit Session, Editable view",
        };
        _compactSessionCommandHost = new FlowLayoutPanel
        {
            Name = "EditMeshSessionCommands",
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            AutoScroll = true,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        ApplyDarkScrollbars(_compactSessionCommandHost);
        _compactSessionFinishHost = new MeshEditorBufferedPanel
        {
            Name = "EditMeshSessionFinishHost",
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Anchor = AnchorStyles.Right,
            Margin = new Padding(12, 0, 0, 0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        var useClassic = StyledActionButton(
            "Classic Layout",
            () => RequestEditMeshLayout(EditMeshLayoutMode.Classic));
        useClassic.Name = "UseClassicEditMeshLayoutButton";
        useClassic.AccessibleName = "Use Classic Edit Mesh layout";
        useClassic.AccessibleDescription =
            "Returns the same live Edit Mesh controls and viewport to the classic side-panel layout.";
        useClassic.Margin = new Padding(8, 0, 0, 0);
        useClassic.Anchor = AnchorStyles.Right;

        bar.Controls.Add(title, 0, 0);
        bar.Controls.Add(_compactSessionCommandHost, 1, 0);
        bar.Controls.Add(_compactSessionFinishHost, 2, 0);
        bar.Controls.Add(useClassic, 3, 0);
        return bar;
    }

    /// <summary>
    /// Left flank: the tool rail on the outer edge and the active tool's
    /// properties beside it. Only the selected tool is realised, so an inactive
    /// tool never reserves space.
    /// </summary>
    private TableLayoutPanel BuildToolDock()
    {
        _toolDock = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "EditMeshToolDock",
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        _toolDock.ColumnStyles.Add(
            new ColumnStyle(SizeType.Absolute, ScaleToolPanelWidth(ToolRailWidth)));
        _toolDock.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _toolDock.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _toolDock.Controls.Add(BuildToolRail(), 0, 0);
        _toolDock.Controls.Add(BuildToolPropertyPanel(), 1, 0);
        return _toolDock;
    }

    private Control BuildToolRail()
    {
        var rail = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "EditMeshToolRail",
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 7,
            Margin = new Padding(0),
            Padding = new Padding(6, 8, 6, 8),
            BackColor = ThemeRailBackground,
        };
        rail.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        var buttonHeight = ScaleToolPanelWidth(ToolRailButtonHeight);
        for (var row = 0; row < 6; row++)
        {
            rail.RowStyles.Add(new RowStyle(SizeType.Absolute, buttonHeight));
        }
        rail.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        AddToolRailButton(rail, ToolRailPage.Selection, "◰", "Select", 0,
            "Vertex, face and part selection, X-Ray and Part Pick.");
        AddToolRailButton(rail, ToolRailPage.Transform, "✥", "Move", 1,
            "Translate step, Move and Grab.");
        AddToolRailButton(rail, ToolRailPage.Brush, "◍", "Brush", 2,
            "Smooth, Inflate and Pinch with radius, strength and falloff.");
        AddToolRailButton(rail, ToolRailPage.Topology, "△", "Topo", 3,
            "Subdivide and Refine Smooth.");
        AddToolRailButton(rail, ToolRailPage.Colour, "◧", "Colour", 4,
            "Per-part tint, recolour and glow for the current selection.");
        AddToolRailButton(rail, ToolRailPage.MorphRefit, "◑", "Morph", 5,
            "Definition profiles, shape sliders and garment refit binding.");
        return rail;
    }

    private void AddToolRailButton(
        TableLayoutPanel rail,
        ToolRailPage page,
        string glyph,
        string caption,
        int row,
        string description)
    {
        // Glyph over caption: the caption keeps the rail readable even where a
        // symbol falls back, and is the seam to swap in a real icon set later.
        var button = StyledButton($"{glyph}\n{caption}", height: ToolRailButtonHeight);
        button.Name = $"EditMeshToolRail{page}Button";
        button.AutoSize = false;
        button.Dock = DockStyle.Fill;
        button.Margin = new Padding(0, 0, 0, 4);
        button.Padding = new Padding(0);
        button.TextAlign = ContentAlignment.MiddleCenter;
        button.AccessibleName = $"{ToolRailPageTitle(page)} tool";
        SetHelpText(button, description);
        button.Click += (_, _) => ShowToolRailPage(page);
        _toolRailButtons.Add(page, button);
        rail.Controls.Add(button, 0, row);
    }

    private static string ToolRailPageTitle(ToolRailPage page) => page switch
    {
        ToolRailPage.Selection => "Selection",
        ToolRailPage.Transform => "Transform",
        ToolRailPage.Brush => "Brush",
        ToolRailPage.Topology => "Topology",
        ToolRailPage.Colour => "Colour",
        _ => "Morph & Refit",
    };

    private Control BuildToolPropertyPanel()
    {
        var panel = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "EditMeshToolPropertyPanel",
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        panel.RowStyles.Add(new RowStyle(SizeType.Absolute, ScaleToolPanelWidth(32)));
        panel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        _toolRailPanelHeader = CreateDockHeader("EditMeshToolPropertyHeader", "SELECTION");

        var scroll = new MeshEditorBufferedPanel
        {
            Name = "EditMeshToolPropertyScroll",
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Margin = new Padding(0),
            Padding = new Padding(10, 8, 10, 10),
            BackColor = ThemePanelBackground,
        };
        ApplyDarkScrollbars(scroll);

        foreach (var page in Enum.GetValues<ToolRailPage>())
        {
            var host = CreateToolRailPage(page);
            _toolRailPages.Add(page, host);
            scroll.Controls.Add(host);
        }

        // Selection is the one tool that owns two sections, so it needs a grid
        // rather than a single docked child.
        _railSelectionStack = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "EditMeshToolRailSelectionStack",
            Dock = DockStyle.Top,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            ColumnCount = 1,
            RowCount = 2,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        _railSelectionStack.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _railSelectionStack.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _railSelectionStack.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        _toolRailPages[ToolRailPage.Selection].Controls.Add(_railSelectionStack);

        panel.Controls.Add(_toolRailPanelHeader, 0, 0);
        panel.Controls.Add(scroll, 0, 1);
        return panel;
    }

    /// <summary>
    /// Right flank: the groups every tool reads and changes. None of them are
    /// modal, so they are all visible at once instead of hiding behind tabs.
    /// </summary>
    private Control BuildSceneInspector()
    {
        var panel = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "EditMeshSceneInspector",
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        panel.RowStyles.Add(new RowStyle(SizeType.Absolute, ScaleToolPanelWidth(32)));
        panel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var header = CreateDockHeader("EditMeshSceneInspectorHeader", "SCENE");

        var scroll = new MeshEditorBufferedPanel
        {
            Name = "EditMeshSceneInspectorScroll",
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Margin = new Padding(0),
            Padding = new Padding(10, 8, 10, 10),
            BackColor = ThemePanelBackground,
        };
        ApplyDarkScrollbars(scroll);

        _sceneInspectorColumn = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "EditMeshSceneInspectorColumn",
            Dock = DockStyle.Top,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            ColumnCount = 1,
            RowCount = 3,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        _sceneInspectorColumn.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        for (var row = 0; row < 3; row++)
        {
            _sceneInspectorColumn.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        }
        scroll.Controls.Add(_sceneInspectorColumn);

        panel.Controls.Add(header, 0, 0);
        panel.Controls.Add(scroll, 0, 1);
        return panel;
    }

    private Label CreateDockHeader(string name, string text)
    {
        return new Label
        {
            Name = name,
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
            UseMnemonic = false,
            Margin = new Padding(0),
            Padding = new Padding(12, 0, 12, 0),
            ForeColor = ThemeMutedText,
            BackColor = ThemeRailBackground,
            Font = new Font(Font.FontFamily, Font.Size - 0.5f, FontStyle.Bold),
            Text = text,
        };
    }

    private static Panel CreateToolRailPage(ToolRailPage page)
    {
        // Natural height, so the scrolling column measures only the visible tool.
        return new MeshEditorBufferedPanel
        {
            Name = $"EditMeshToolRail{page}Page",
            Dock = DockStyle.Top,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Visible = false,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
            TabStop = true,
        };
    }

    private SplitContainer CreateCompactSplit(
        string name,
        Orientation orientation,
        FixedPanel fixedPanel)
    {
        var split = new MeshEditorBufferedSplitContainer
        {
            Name = name,
            Dock = DockStyle.Fill,
            Orientation = orientation,
            FixedPanel = fixedPanel,
            IsSplitterFixed = false,
            SplitterIncrement = 8,
            SplitterWidth = ScaleToolPanelWidth(ToolPanelSplitterWidth),
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemeBorder,
            TabStop = false,
        };
        split.Panel1.BackColor = ThemeWindowBackground;
        split.Panel2.BackColor = ThemePanelBackground;
        return split;
    }

    private void RequestEditMeshLayout(EditMeshLayoutMode layout)
    {
        _requestedEditMeshLayout = layout;
        if (!_meshEditInteractionActive)
        {
            return;
        }
        if (!TryActivateEditMeshLayout(layout, preserveRequestedLayout: false))
        {
            return;
        }
        _statusLabel.Text = layout == EditMeshLayoutMode.ToolRail
            ? "Tool rail active. All Edit Mesh tools still operate on the same resident session."
            : "Classic Edit Mesh layout restored.";
    }

    private void ApplyRequestedEditMeshLayout()
    {
        if (!_meshEditInteractionActive)
        {
            return;
        }
        _ = TryActivateEditMeshLayout(_requestedEditMeshLayout, preserveRequestedLayout: false);
    }

    private void RestoreClassicLayoutForNonMeshMode()
    {
        var requestedBeforeRestore = _requestedEditMeshLayout;
        try
        {
            // Always normalize the live control tree on mode exit. This also
            // repairs any interrupted rail transition before placement
            // controls (including Mesh View) become interactive again.
            ActivateClassicEditMeshLayout();
        }
        finally
        {
            _requestedEditMeshLayout = requestedBeforeRestore;
        }
    }

    private bool TryActivateEditMeshLayout(
        EditMeshLayoutMode layout,
        bool preserveRequestedLayout)
    {
        if (_activeEditMeshLayout == layout)
        {
            // A scene update can arrive with mesh edit already on. The sections
            // are still in place, but the flanks were just uncollapsed against
            // the classic saved widths, so the dock width has to be re-asserted.
            if (layout == EditMeshLayoutMode.ToolRail)
            {
                ApplyToolRailSplitterLayout();
            }
            return true;
        }
        var requestedBeforeSwitch = _requestedEditMeshLayout;
        // Both directions re-parent live sections between the flanks. Freezing
        // the window for the swap keeps the reader from seeing sections land one
        // at a time against a half-empty panel.
        using var redraw = BeginRedrawBatch();
        try
        {
            if (layout == EditMeshLayoutMode.ToolRail)
            {
                ActivateToolRailLayout();
            }
            else
            {
                ActivateClassicEditMeshLayout();
            }
            if (preserveRequestedLayout)
            {
                _requestedEditMeshLayout = requestedBeforeSwitch;
            }
            return true;
        }
        catch (Exception ex)
        {
            try
            {
                ActivateClassicEditMeshLayout();
            }
            catch
            {
                // The classic tree is also rebuilt on the next interaction-mode
                // update. Keep the original layout exception as the actionable
                // status instead of replacing it with best-effort recovery noise.
            }
            _requestedEditMeshLayout = EditMeshLayoutMode.Classic;
            _activeEditMeshLayout = EditMeshLayoutMode.Classic;
            _statusLabel.Text =
                $"The tool rail could not be activated; Classic layout remains in use. {ex.Message}";
            return false;
        }
    }

    private void ActivateToolRailLayout()
    {
        if (_activeEditMeshLayout == EditMeshLayoutMode.ToolRail
            || _classicEditMeshLayoutRoot is null
            || _editMeshLayoutHost is null
            || _compactSessionBar is null
            || _compactSessionCommandHost is null
            || _toolDock is null
            || _sceneInspectorColumn is null
            || _railSelectionStack is null
            || _viewportWorkspaceSplit is null
            || _leftToolSplit is null
            || _rightToolSplit is null
            || _leftToolPanel is null
            || _rightToolPanel is null
            || _presentationViewportRegion is null)
        {
            return;
        }

        CaptureToolPanelLayout(persist: false);
        CaptureClassicScrollPositions();
        // Sections are re-parented one at a time below. SuspendLayout defers
        // their measurement but not their painting, so without this the reader
        // sees them land at construction-time bounds: captionless group boxes,
        // clipped combo text and unpainted buttons.
        using var redraw = BeginRedrawBatch();
        SuspendAllEditMeshLayouts();
        try
        {
            MoveSessionControlsToCompactBar();
            ConfigurePresentationRegion(compactEditableOnly: true);
            // The Morph & Refit card grid was built for a full-width bottom
            // deck. In a single tool column its classic stacked form is both
            // correct and already responsive, so unwind the grid here.
            ExitCompactMorphLayout();
            // The dock header already names the tool, so the section's own
            // collapse header would just repeat it.
            SetMorphCollapseHeaderVisible(false);

            // Left: only the modal tools swap with the rail. Selection owns two
            // sections, so it gets a grid; the rest own one page each.
            AddRailSection(_railSelectionStack, _selectionSection, row: 0);
            AddRailSection(_railSelectionStack, _partPickSection, row: 1);
            AddRailSection(_toolRailPages[ToolRailPage.Transform], _transformSection);
            AddRailSection(_toolRailPages[ToolRailPage.Brush], _brushSection);
            AddRailSection(_toolRailPages[ToolRailPage.Topology], _topologySection);
            AddRailSection(_toolRailPages[ToolRailPage.Colour], _colourSection);
            AddRailSection(_toolRailPages[ToolRailPage.MorphRefit], _morphRefitSection);

            // Right: the scene groups every tool reads and changes, all visible.
            AddRailSection(_sceneInspectorColumn, _partsSection, row: 0);
            AddRailSection(_sceneInspectorColumn, _actionHistorySection, row: 1);
            AddRailSection(_sceneInspectorColumn, _viewportSection, row: 2);

            _compactSessionBar.Visible = true;
            _editMeshLayoutHost.RowStyles[0].Height = ScaleToolPanelWidth(46);
            _leftToolPanel.Visible = false;
            _rightToolPanel.Visible = false;
            _toolDock.Visible = true;
            _toolDock.BringToFront();
            _sceneInspectorColumn.Parent!.Parent!.Visible = true;
            _sceneInspectorColumn.Parent!.Parent!.BringToFront();
            _leftToolSplit.Panel1Collapsed = false;
            _rightToolSplit.Panel2Collapsed = false;
            _viewportWorkspaceSplit.Panel2Collapsed = true;
            _activeEditMeshLayout = EditMeshLayoutMode.ToolRail;
            ApplyToolRailSplitterLayout();
            if (!_toolRailPageSelected)
            {
                _selectedToolRailPage = ToolRailPageForActiveTool();
                _toolRailPageSelected = true;
            }
            ShowToolRailPage(_selectedToolRailPage);
        }
        finally
        {
            ResumeAllEditMeshLayouts();
        }
    }

    private void ActivateClassicEditMeshLayout()
    {
        if (_classicEditMeshLayoutRoot is null
            || _editMeshLayoutHost is null)
        {
            return;
        }
        // RebuildClassicToolStacks clears and re-adds every section, so the same
        // partial-paint window applies on the way back to Classic.
        using var redraw = BeginRedrawBatch();
        SuspendAllEditMeshLayouts();
        try
        {
            ExitCompactMorphLayout();
            SetMorphCollapseHeaderVisible(true);
            MoveSessionControlsToClassicSection();
            RebuildClassicToolStacks();
            ConfigurePresentationRegion(compactEditableOnly: false);
            if (_viewportWorkspaceSplit is not null)
            {
                _viewportWorkspaceSplit.Panel2Collapsed = true;
            }
            if (_compactSessionBar is not null)
            {
                _compactSessionBar.Visible = false;
            }
            _editMeshLayoutHost.RowStyles[0].Height = 0;
            if (_toolDock is not null)
            {
                _toolDock.Visible = false;
            }
            if (_sceneInspectorColumn?.Parent?.Parent is { } inspector)
            {
                inspector.Visible = false;
            }
            if (_leftToolPanel is not null)
            {
                _leftToolPanel.Visible = true;
                _leftToolPanel.BringToFront();
            }
            if (_rightToolPanel is not null)
            {
                _rightToolPanel.Visible = true;
                _rightToolPanel.BringToFront();
            }
            // The read-only preview profile builds no tool panels at all, so
            // both flanks are empty. Un-collapsing them here would undo the
            // collapse applied at construction and leave two blank bands: this
            // runs on every exit from mesh-edit mode, including the
            // ApplyInteractionModeControls call in the constructor.
            if (_leftToolSplit is not null && !_options.SimplePreview)
            {
                _leftToolSplit.Panel1Collapsed = false;
            }
            if (_rightToolSplit is not null && !_options.SimplePreview)
            {
                _rightToolSplit.Panel2Collapsed = false;
            }
            _classicEditMeshLayoutRoot.Visible = true;
            _activeEditMeshLayout = EditMeshLayoutMode.Classic;
            ApplySavedToolPanelLayout();
        }
        finally
        {
            ResumeAllEditMeshLayouts();
        }
        // The stacks are rebuilt while suspended and resume without their own
        // layout pass, so their new rows keep construction-time bounds until
        // something forces the measure. Do it here rather than relying on an
        // incidental resize.
        PerformClassicToolStackLayout();
        RestoreClassicScrollPositions();
    }

    private void MoveSessionControlsToCompactBar()
    {
        if (_compactSessionCommandHost is null || _compactSessionFinishHost is null)
        {
            return;
        }
        _compactSessionCommandHost.Controls.Clear();
        foreach (var button in SessionCommandButtons())
        {
            button.Dock = DockStyle.None;
            button.Margin = new Padding(0, 0, 6, 0);
            button.MinimumSize = new Size(
                Math.Max(button.MinimumSize.Width, button.GetPreferredSize(Size.Empty).Width),
                Math.Max(30, button.MinimumSize.Height));
            // Finishing the session is the bar's primary command, so it is
            // pinned to the right edge and accented instead of scrolling with
            // the selection and history commands.
            var host = ReferenceEquals(button, _sessionFinishButton)
                ? (Control)_compactSessionFinishHost
                : _compactSessionCommandHost;
            EditMeshLayoutContracts.MoveControl(button, host, DockStyle.None);
        }
        if (_sessionFinishButton is not null)
        {
            SetButtonAccent(_sessionFinishButton, true);
        }
    }

    private void MoveSessionControlsToClassicSection()
    {
        if (_classicSessionBody is null
            || _classicSessionSelectionRow is not TableLayoutPanel selectionRow
            || _classicSessionHistoryRow is not TableLayoutPanel historyRow
            || _sessionFinishButton is null
            || _sessionClearSelectionButton is null
            || _sessionSelectAllButton is null
            || _sessionInvertButton is null
            || _undoButton is null
            || _redoButton is null)
        {
            return;
        }
        SetButtonAccent(_sessionFinishButton, false);
        EditMeshLayoutContracts.MoveControl(
            _sessionFinishButton,
            _classicSessionBody,
            0,
            0,
            DockStyle.Top);
        RestoreButtonRow(
            selectionRow,
            _sessionClearSelectionButton,
            _sessionSelectAllButton);
        RestoreButtonRow(
            historyRow,
            _sessionInvertButton,
            _undoButton,
            _redoButton);
    }

    private IEnumerable<Button> SessionCommandButtons()
    {
        if (_sessionClearSelectionButton is not null) yield return _sessionClearSelectionButton;
        if (_sessionSelectAllButton is not null) yield return _sessionSelectAllButton;
        if (_sessionInvertButton is not null) yield return _sessionInvertButton;
        if (_undoButton is not null) yield return _undoButton;
        if (_redoButton is not null) yield return _redoButton;
        if (_sessionFinishButton is not null) yield return _sessionFinishButton;
    }

    private static void RestoreButtonRow(TableLayoutPanel row, params Button[] buttons)
    {
        for (var index = 0; index < buttons.Length; index++)
        {
            var button = buttons[index];
            button.Dock = DockStyle.Fill;
            button.Margin = new Padding(
                index == 0 ? 0 : 3,
                0,
                index == buttons.Length - 1 ? 0 : 3,
                0);
            EditMeshLayoutContracts.MoveControl(
                button,
                row,
                index,
                0,
                DockStyle.Fill);
        }
    }

    private void RebuildClassicToolStacks()
    {
        if (_leftToolStack is not null)
        {
            RebuildClassicStack(
                _leftToolStack,
                _classicSessionSection,
                _partPickSection,
                _selectionSection,
                _placementSection,
                _transformSection,
                _brushSection,
                _topologySection);
        }
        if (_rightToolStack is not null)
        {
            RebuildClassicStack(
                _rightToolStack,
                _actionHistorySection,
                _morphRefitSection,
                _partsSection,
                _viewportSection);
        }
    }

    private static void RebuildClassicStack(
        TableLayoutPanel stack,
        params Control?[] sections)
    {
        stack.Controls.Clear();
        stack.RowStyles.Clear();
        stack.RowCount = 0;
        foreach (var section in sections)
        {
            if (section is null)
            {
                continue;
            }
            RestoreClassicSectionStyle(section);
            AddStackRow(stack, section);
        }
    }

    /// <summary>
    /// Moves one live section into a dock column. Sections keep their natural
    /// height and the column scrolls, so nothing reserves space it does not use.
    /// </summary>
    private static void AddRailSection(Control host, Control? section, int row = -1)
    {
        if (section is null)
        {
            return;
        }
        RestoreClassicSectionStyle(section);
        section.Margin = new Padding(0, 0, 0, 10);

        if (host is TableLayoutPanel table && row >= 0)
        {
            EditMeshLayoutContracts.MoveControl(section, table, 0, row, DockStyle.Top);
        }
        else
        {
            EditMeshLayoutContracts.MoveControl(section, host, DockStyle.Top);
        }
        section.BringToFront();
    }

    private static void RestoreClassicSectionStyle(Control section)
    {
        section.AutoSize = true;
        section.Dock = DockStyle.Top;
        section.Margin = new Padding(0, 0, 0, 10);
        if (section is not GroupBox group
            || group.Controls.OfType<TableLayoutPanel>().SingleOrDefault() is not { } body)
        {
            return;
        }
        body.AutoSize = true;
        body.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        body.Dock = DockStyle.Top;
        foreach (RowStyle rowStyle in body.RowStyles)
        {
            rowStyle.SizeType = SizeType.AutoSize;
            rowStyle.Height = 0;
        }
        foreach (Control child in body.Controls)
        {
            child.Dock = DockStyle.Top;
        }
    }

    private void ConfigurePresentationRegion(bool compactEditableOnly)
    {
        if (_presentationViewportRegion is null)
        {
            return;
        }
        if (_presentationViewportRegion is TableLayoutPanel viewportRegion
            && viewportRegion.RowStyles.Count > 0
            && _presentationViewSelector is not null)
        {
            _presentationViewSelector.Visible = !compactEditableOnly;
            viewportRegion.RowStyles[0].SizeType = SizeType.Absolute;
            viewportRegion.RowStyles[0].Height = compactEditableOnly ? 0 : 34;
        }
        if (compactEditableOnly)
        {
            _viewport.ActivatePresentationView("editable");
        }
    }

    /// <summary>
    /// The tool a rail page puts the viewport into. Topology and Morph &amp; Refit
    /// are command pages rather than modal tools, so they leave the active tool
    /// alone and return null.
    /// </summary>
    private static string? DefaultToolForRailPage(ToolRailPage page) => page switch
    {
        ToolRailPage.Selection => "select",
        ToolRailPage.Transform => "move",
        ToolRailPage.Brush => "smooth",
        _ => null,
    };

    private static bool RailPageOwnsTool(ToolRailPage page, string tool) => page switch
    {
        ToolRailPage.Selection => string.Equals(tool, "select", StringComparison.OrdinalIgnoreCase),
        ToolRailPage.Transform => tool.ToLowerInvariant() is "move" or "grab",
        ToolRailPage.Brush => tool.ToLowerInvariant() is "smooth" or "inflate" or "pinch",
        _ => false,
    };

    private void ShowToolRailPage(ToolRailPage page)
    {
        _selectedToolRailPage = page;
        _toolRailPageSelected = true;
        // A rail button that names a tool has to select that tool. Revealing the
        // page alone left the viewport in whatever mode it was already in, so
        // clicking "Select" and then clicking the model did nothing.
        var defaultTool = DefaultToolForRailPage(page);
        if (defaultTool is not null
            && _meshEditInteractionActive
            && !RailPageOwnsTool(page, _viewport.ActiveTool))
        {
            ActivateTool(defaultTool, ToolRailPageTitle(page));
        }
        if (page == ToolRailPage.Colour)
        {
            // Colour edits land on the base texture, and the editable viewport
            // defaults to Wire + Vertices, which draws no surface at all. Opening
            // the page in that mode would hide every edit it makes.
            EnsureColourVisibleDisplayMode();
        }
        foreach (var pair in _toolRailPages)
        {
            pair.Value.Visible = pair.Key == page;
            if (pair.Key == page)
            {
                pair.Value.BringToFront();
            }
        }
        foreach (var pair in _toolRailButtons)
        {
            SetButtonAccent(pair.Value, pair.Key == page);
        }
        if (_toolRailPanelHeader is not null)
        {
            _toolRailPanelHeader.Text = ToolRailPageTitle(page).ToUpperInvariant();
        }
    }

    private ToolRailPage ToolRailPageForActiveTool()
    {
        return _viewport.ActiveTool.ToLowerInvariant() switch
        {
            "move" or "grab" => ToolRailPage.Transform,
            "smooth" or "inflate" or "pinch" => ToolRailPage.Brush,
            _ => ToolRailPage.Selection,
        };
    }

    /// <summary>
    /// Keeps the rail highlight on the page that owns the active tool when the
    /// tool is changed from the page's own buttons rather than from the rail.
    /// </summary>
    private void SyncToolRailPageToActiveTool()
    {
        if (!IsToolRailActive)
        {
            return;
        }
        var page = ToolRailPageForActiveTool();
        if (page != _selectedToolRailPage && RailPageOwnsTool(page, _viewport.ActiveTool))
        {
            ShowToolRailPage(page);
        }
    }

    private void ApplyToolRailSplitterLayout()
    {
        if (_applyingToolRailSplitterLayout
            || _leftToolSplit is null
            || _rightToolSplit is null)
        {
            return;
        }
        _applyingToolRailSplitterLayout = true;
        try
        {
            _editMeshLayoutHost?.PerformLayout();
            _leftToolSplit.PerformLayout();
            _rightToolSplit.PerformLayout();

            var toolDockWidth = ScaleToolPanelWidth(ToolRailWidth + ToolPropertyWidth);
            ApplySplitterDistance(
                _leftToolSplit,
                toolDockWidth,
                toolDockWidth,
                ScaleToolPanelWidth(MinimumViewportWidth + SceneInspectorWidth),
                prioritizePanelOne: true);
            _leftToolSplit.PerformLayout();
            EditMeshLayoutContracts.ApplyPanelTwoSize(
                _rightToolSplit,
                ScaleToolPanelWidth(SceneInspectorWidth),
                ScaleToolPanelWidth(MinimumViewportWidth),
                ScaleToolPanelWidth(280));
        }
        finally
        {
            _applyingToolRailSplitterLayout = false;
        }
    }

    /// <summary>
    /// The Morph &amp; Refit section carries its own collapse header for the
    /// classic stack. In the tool dock the header row is redundant, and the
    /// body must not stay collapsed from a previous classic session.
    /// </summary>
    private void SetMorphCollapseHeaderVisible(bool visible)
    {
        if (_morphSectionHeader is null
            || _morphSectionLayout is null
            || _morphSectionLayout.RowStyles.Count == 0)
        {
            return;
        }
        _morphSectionHeader.Visible = visible;
        _morphSectionLayout.RowStyles[0].SizeType =
            visible ? SizeType.AutoSize : SizeType.Absolute;
        _morphSectionLayout.RowStyles[0].Height = 0;
        if (_morphSectionBody is not null)
        {
            _morphSectionBody.Visible = !visible || _morphClassicExpanded;
        }
    }

    private void PerformClassicToolStackLayout()
    {
        _morphSectionBody?.PerformLayout();
        _morphSectionLayout?.PerformLayout();
        _leftToolStack?.PerformLayout();
        _rightToolStack?.PerformLayout();
        _leftToolPanel?.PerformLayout();
        _rightToolPanel?.PerformLayout();
    }

    private void CaptureClassicScrollPositions()
    {
        _classicLeftScrollPosition = CaptureScrollPosition(_leftToolStack);
        _classicRightScrollPosition = CaptureScrollPosition(_rightToolStack);
    }

    private void RestoreClassicScrollPositions()
    {
        RestoreScrollPosition(_leftToolStack, _classicLeftScrollPosition);
        RestoreScrollPosition(_rightToolStack, _classicRightScrollPosition);
    }

    private static Point CaptureScrollPosition(Control? stack)
    {
        if (stack?.Parent is not ScrollableControl scroll)
        {
            return Point.Empty;
        }
        return new Point(-scroll.AutoScrollPosition.X, -scroll.AutoScrollPosition.Y);
    }

    private static void RestoreScrollPosition(Control? stack, Point position)
    {
        if (stack?.Parent is ScrollableControl scroll)
        {
            scroll.AutoScrollPosition = position;
        }
    }

    private void SuspendAllEditMeshLayouts()
    {
        _editMeshLayoutHost?.SuspendLayout();
        _classicEditMeshLayoutRoot?.SuspendLayout();
        _viewportWorkspaceSplit?.SuspendLayout();
        _leftToolModeHost?.SuspendLayout();
        _rightToolModeHost?.SuspendLayout();
        _toolDock?.SuspendLayout();
        _sceneInspectorColumn?.SuspendLayout();
        _railSelectionStack?.SuspendLayout();
        SuspendToolPanelLayout();
    }

    private void ResumeAllEditMeshLayouts()
    {
        ResumeToolPanelLayout();
        _railSelectionStack?.ResumeLayout(performLayout: false);
        _sceneInspectorColumn?.ResumeLayout(performLayout: false);
        _toolDock?.ResumeLayout(performLayout: false);
        _rightToolModeHost?.ResumeLayout(performLayout: true);
        _leftToolModeHost?.ResumeLayout(performLayout: true);
        _viewportWorkspaceSplit?.ResumeLayout(performLayout: true);
        _classicEditMeshLayoutRoot?.ResumeLayout(performLayout: true);
        _editMeshLayoutHost?.ResumeLayout(performLayout: true);
    }
}
