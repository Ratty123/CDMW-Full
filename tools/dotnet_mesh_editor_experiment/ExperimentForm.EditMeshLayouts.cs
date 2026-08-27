namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    // Column widths are measured from content in EditMeshToolColumnMetrics
    // rather than reserved here; the rail-and-panel layout reserved 414 always.
    private readonly Dictionary<string, Button> _toolRailToolButtons = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<ToolRailPage, Button> _toolRailPageButtons = new();
    private readonly Dictionary<ToolRailPage, Panel> _toolRailPages = new();
    // The only Edit Mesh layout; the placement flanks remain construction state.
    private bool _toolRailLayoutActive;
    // Null means no tool is armed: Edit Mesh opens this way, with the camera on
    // the left button and the navigation strip naming the modifiers.
    private ToolRailPage? _selectedToolRailPage;
    private bool _toolRailPageSelected;
    private bool _applyingToolRailSplitterLayout;
    // The dock widths on screen, so a pass that would move nothing is skipped.
    private int _appliedToolDockWidth = -1;
    private int _appliedInspectorWidth = -1;
    private int _appliedLayoutDpi = -1;
    private int _appliedToolRailHostWidth = -1;
    // The construction cells of the two sections placement mode shares with the
    // rail, so leaving mesh edit can put them back where they were built.
    private TableLayoutPanelCellPosition? _partPickPlacementCell;
    private TableLayoutPanelCellPosition? _viewportSectionPlacementCell;

    private TableLayoutPanel? _editMeshLayoutHost;
    private Control? _placementEditMeshLayoutRoot;
    private SplitContainer? _viewportWorkspaceSplit;
    private Control? _compactSessionBar;
    private FlowLayoutPanel? _compactSessionCommandHost;
    private Panel? _compactSessionFinishHost;
    private Panel? _leftToolModeHost;
    private Panel? _rightToolModeHost;
    private TableLayoutPanel? _toolDock;
    private TableLayoutPanel? _railSelectionStack;
    private TableLayoutPanel? _sceneInspectorColumn;
    private Control? _presentationViewportRegion;

    private Button? _sessionFinishButton;
    private Button? _sessionClearSelectionButton;
    private Button? _sessionSelectAllButton;
    private Button? _sessionInvertButton;
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

    private bool IsToolRailActive => _toolRailLayoutActive;

    private void InitializeEditMeshLayoutHost(Control placementRoot)
    {
        _placementEditMeshLayoutRoot = placementRoot;
        _placementEditMeshLayoutRoot.Dock = DockStyle.Fill;
        BuildPermanentViewportWorkspace();
        BuildPermanentToolModeHosts();

        _editMeshLayoutHost = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "DotNetMeshEditorLayoutHost",
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemeWindowBackground,
        };
        _editMeshLayoutHost.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _editMeshLayoutHost.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));
        _editMeshLayoutHost.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _editMeshLayoutHost.RowStyles.Add(new RowStyle(
            SizeType.Absolute,
            _options.SimplePreview ? 0 : Math.Max(30, Font.Height + 8)));
        _editMeshLayoutHost.Resize += (_, _) =>
        {
            if (!IsToolRailActive)
            {
                return;
            }
            ApplyToolRailSplitterLayout();
            // A resize moves the splitter without changing the measured column
            // widths, so the pass above finds nothing to move and returns before
            // reaching its own invalidate. The strip of flank the dock is
            // resized across keeps whatever was painted there last, which after
            // an entry from placement is the placement panel -- the panel the
            // reader sees briefly behind the tool dock while dragging the
            // window edge. Nothing else asks for that region back.
            _leftToolSplit?.Panel1.Invalidate(invalidateChildren: true);
            _rightToolSplit?.Panel2.Invalidate(invalidateChildren: true);
        };
        _editMeshLayoutHost.Controls.Add(_placementEditMeshLayoutRoot, 0, 1);
        if (!_options.SimplePreview)
        {
            // Full window width: the legend has to stay readable with both tool
            // flanks open, which the viewport column alone cannot manage.
            _editMeshLayoutHost.Controls.Add(BuildViewportNavigationStrip(), 0, 2);
            UpdateViewportControlsHint();
        }
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
    /// assignment and never touches the viewport's ancestry. The session
    /// commands are adopted here once — the bar is their only home.
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
        MoveSessionControlsToCompactBar();
    }

    private void BuildPermanentViewportWorkspace()
    {
        if (_rightToolSplit is null || _presentationViewportRegion is null)
        {
            throw new InvalidOperationException(
                "The permanent Edit Mesh viewport host requires the placement viewport split.");
        }
        // Panel2 stays collapsed in both modes. The split is kept because it
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
    /// Both flanks host two mutually exclusive children: the placement
    /// scrolling tool panel, and the rail's dock. Swapping visibility keeps
    /// every live control instance parented to a stable ancestor.
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
                "The permanent Edit Mesh tool hosts require the placement tool panels.");
        }

        // Composited, not merely double buffered: this subtree is the tool list,
        // its rows and every tool's settings, and each of them is its own HWND.
        // See MeshEditorCompositedPanel for why the flanks get this and the form
        // must not.
        _leftToolModeHost = new MeshEditorCompositedPanel
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

        // The Parts list, Action History and Viewport groups: selecting a part
        // repainted this column one child window at a time.
        _rightToolModeHost = new MeshEditorCompositedPanel
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
        // The session commands scroll in a flow panel and the finish button is
        // accented on state changes, so this row repaints on its own schedule.
        var barHost = new MeshEditorCompositedPanel
        {
            Name = "EditMeshSessionBarHost",
            Dock = DockStyle.Fill,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        var bar = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "EditMeshSessionBar",
            Dock = DockStyle.Fill,
            ColumnCount = 3,
            RowCount = 1,
            Margin = new Padding(0),
            Padding = new Padding(14, 7, 14, 7),
            BackColor = ThemePanelBackground,
        };
        bar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        bar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
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

        bar.Controls.Add(title, 0, 0);
        bar.Controls.Add(_compactSessionCommandHost, 1, 0);
        bar.Controls.Add(_compactSessionFinishHost, 2, 0);
        barHost.Controls.Add(bar);
        return barHost;
    }

    /// <summary>
    /// Left flank: one column listing every tool, with the open tool's settings
    /// inline beneath the row that opened them. Only the open page is realised,
    /// so a closed tool never reserves space.
    /// </summary>
    private TableLayoutPanel BuildToolDock()
    {
        _toolDock = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "EditMeshToolDock",
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 1,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        _toolDock.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _toolDock.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _toolDock.Font = new Font(Font.FontFamily, 8.5f);
        _toolDock.Controls.Add(BuildToolListColumn(), 0, 0);
        return _toolDock;
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
            RowCount = 1,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        panel.Font = new Font(Font.FontFamily, 8.5f);
        // No "SCENE" header: Parts, Action History and Viewport name themselves,
        // so the band above them only cost height.
        panel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var scroll = new MeshEditorBufferedPanel
        {
            Name = "EditMeshSceneInspectorScroll",
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Margin = new Padding(0),
            Padding = new Padding(8, 6, 8, 8),
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
        for (var row = 0; row < 4; row++)
        {
            _sceneInspectorColumn.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        }
        scroll.Controls.Add(_sceneInspectorColumn);

        panel.Controls.Add(scroll, 0, 0);
        return panel;
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

    /// <summary>
    /// The tool rail is the only Edit Mesh layout. Re-running on a redundant
    /// mesh_edit frame only re-asserts the dock widths, because the flanks were
    /// just uncollapsed against the saved placement widths.
    /// </summary>
    private void ApplyToolRailEditMeshLayout()
    {
        if (!_meshEditInteractionActive)
        {
            return;
        }
        if (_toolRailLayoutActive)
        {
            ApplyToolRailSplitterLayout();
            return;
        }
        try
        {
            ActivateToolRailLayout();
        }
        catch (Exception ex)
        {
            // Every move below is idempotent, so the next scene frame retries
            // the activation rather than leaving the session without tools.
            _statusLabel.Text =
                $"The Edit Mesh tool rail could not be activated. {ex.Message}";
        }
    }

    private void ActivateToolRailLayout()
    {
        if (_toolRailLayoutActive
            || _placementEditMeshLayoutRoot is null
            || _editMeshLayoutHost is null
            || _compactSessionBar is null
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
        CapturePlacementSectionHomes();
        // Sections are re-parented one at a time below. SuspendLayout defers
        // their measurement but not their painting, so without this the reader
        // sees them land at construction-time bounds: captionless group boxes,
        // clipped combo text and unpainted buttons.
        using var redraw = BeginRedrawBatch();
        SuspendAllEditMeshLayouts();
        try
        {
            ConfigurePresentationRegion(compactEditableOnly: true);
            // The Morph & Refit card grid was built for a full-width bottom
            // deck. In a single tool column its stacked form is both correct
            // and already responsive, so unwind the grid here.
            ExitCompactMorphLayout();
            // The list row that opened the page already names it, so the
            // section's own collapse header would just repeat it.
            SetMorphCollapseHeaderVisible(false);
            HideRailToolSectionCaptions();

            // Left: the tool and command sections swap with the rail. Selection
            // owns two sections, so it gets a grid; the rest own one page each.
            AddRailSection(_railSelectionStack, _selectionSection, row: 0);
            if (_partPickSection is not null)
            {
                AddRailSection(_railSelectionStack, _partPickSection, row: 1);
            }
            AddRailSection(_toolRailPages[ToolRailPage.Transform], _transformSection);
            AddRailSection(_toolRailPages[ToolRailPage.Brush], _brushSection);
            AddRailSection(_toolRailPages[ToolRailPage.Topology], _topologySection);
            AddRailSection(_toolRailPages[ToolRailPage.MorphRefit], _morphRefitSection);

            // Right: the scene groups every tool reads and changes, all visible.
            AddRailSection(_sceneInspectorColumn, _partsSection, row: 0);
            AddRailSection(_sceneInspectorColumn, _layersSection, row: 1);
            AddRailSection(_sceneInspectorColumn, _actionHistorySection, row: 2);
            AddRailSection(_sceneInspectorColumn, _viewportSection, row: 3);

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
            _toolRailLayoutActive = true;
            // Entering lands on the saved placement widths.
            _appliedToolDockWidth = -1;
            _appliedInspectorWidth = -1;
            _appliedToolRailHostWidth = -1;
            ApplyToolRailSplitterLayout();
            if (!_toolRailPageSelected)
            {
                _selectedToolRailPage = ToolRailPageForActiveTool();
                _toolRailPageSelected = true;
            }
            // A placement boot reaches this after embedding, so OnShown's pass
            // could not have covered the pages just populated here.
            RealizeControlTree(_toolDock);
            ShowToolRailPage(_selectedToolRailPage);
        }
        finally
        {
            ResumeAllEditMeshLayouts();
        }
    }

    /// <summary>
    /// Leaving mesh edit returns the flanks to the placement panels. Only the
    /// two sections placement mode shares with the rail move back — everything
    /// else in the dock is mesh-edit-only and simply stops being shown. This
    /// also repairs any interrupted rail transition before placement controls
    /// (including Mesh View) become interactive again.
    /// </summary>
    private void RestorePlacementLayoutForNonMeshMode()
    {
        if (_placementEditMeshLayoutRoot is null
            || _editMeshLayoutHost is null)
        {
            return;
        }
        using var redraw = BeginRedrawBatch();
        SuspendAllEditMeshLayouts();
        try
        {
            ReturnPlacementSectionsToFlanks();
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
                RevealToolFlank(_leftToolPanel);
                _leftToolPanel.BringToFront();
            }
            if (_rightToolPanel is not null)
            {
                RevealToolFlank(_rightToolPanel);
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
            _placementEditMeshLayoutRoot.Visible = true;
            _toolRailLayoutActive = false;
            ApplySavedToolPanelLayout();
        }
        finally
        {
            ResumeAllEditMeshLayouts();
        }
        // The returned sections land while suspended and resume without their
        // own layout pass, so they keep dock-time bounds until something forces
        // the measure. Do it here rather than relying on an incidental resize.
        PerformPlacementFlankLayout();
    }

    /// <summary>
    /// Records where the shared sections sit in the placement stacks before the
    /// rail adopts them, so leaving mesh edit can put them back in the same
    /// cells. Captured once — the placement stacks never rearrange.
    /// </summary>
    private void CapturePlacementSectionHomes()
    {
        if (_partPickPlacementCell is null
            && _leftToolStack is not null
            && _partPickSection is not null
            && ReferenceEquals(_partPickSection.Parent, _leftToolStack))
        {
            _partPickPlacementCell = _leftToolStack.GetCellPosition(_partPickSection);
        }
        if (_viewportSectionPlacementCell is null
            && _rightToolStack is not null
            && _viewportSection is not null
            && ReferenceEquals(_viewportSection.Parent, _rightToolStack))
        {
            _viewportSectionPlacementCell = _rightToolStack.GetCellPosition(_viewportSection);
        }
    }

    private void ReturnPlacementSectionsToFlanks()
    {
        if (_leftToolStack is not null
            && _partPickSection is not null
            && _partPickPlacementCell is { } partPickCell)
        {
            NormalizeSectionStyle(_partPickSection);
            EditMeshLayoutContracts.MoveControl(
                _partPickSection,
                _leftToolStack,
                partPickCell.Column,
                partPickCell.Row,
                DockStyle.Top);
        }
        if (_rightToolStack is not null
            && _viewportSection is not null
            && _viewportSectionPlacementCell is { } viewportCell)
        {
            NormalizeSectionStyle(_viewportSection);
            EditMeshLayoutContracts.MoveControl(
                _viewportSection,
                _rightToolStack,
                viewportCell.Column,
                viewportCell.Row,
                DockStyle.Top);
        }
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

    private IEnumerable<Button> SessionCommandButtons()
    {
        if (_sessionClearSelectionButton is not null) yield return _sessionClearSelectionButton;
        if (_sessionSelectAllButton is not null) yield return _sessionSelectAllButton;
        if (_sessionInvertButton is not null) yield return _sessionInvertButton;
        if (_undoButton is not null) yield return _undoButton;
        if (_redoButton is not null) yield return _redoButton;
        if (_sessionFinishButton is not null) yield return _sessionFinishButton;
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
        if (ReferenceEquals(section.Parent, host)
            && section.Dock == DockStyle.Top
            && section.Margin == new Padding(0, 0, 0, 10)
            && (host is not TableLayoutPanel existingTable
                || row < 0
                || existingTable.GetCellPosition(section) == new TableLayoutPanelCellPosition(0, row)))
        {
            return;
        }
        NormalizeSectionStyle(section);
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

    /// <summary>
    /// Gives rail-only sections their permanent parents during hidden startup.
    /// </summary>
    /// <remarks>
    /// Placement and Edit Mesh genuinely share only Part Pick and Viewport, so
    /// those two still move on a mode switch. The remaining sections never
    /// return to the placement flanks; moving all nine of them for the first
    /// time on the Edit Mesh click spent hundreds of milliseconds creating
    /// native parent transitions the hidden startup can finish in advance.
    /// </remarks>
    private void PrimeToolRailSectionOwnership()
    {
        if (_toolDock is null
            || _sceneInspectorColumn is null
            || _railSelectionStack is null
            || _toolRailPages.Count == 0)
        {
            return;
        }
        AddRailSection(_railSelectionStack, _selectionSection, row: 0);
        AddRailSection(_toolRailPages[ToolRailPage.Transform], _transformSection);
        AddRailSection(_toolRailPages[ToolRailPage.Brush], _brushSection);
        AddRailSection(_toolRailPages[ToolRailPage.Topology], _topologySection);
        AddRailSection(_toolRailPages[ToolRailPage.MorphRefit], _morphRefitSection);
        AddRailSection(_sceneInspectorColumn, _partsSection, row: 0);
        AddRailSection(_sceneInspectorColumn, _layersSection, row: 1);
        AddRailSection(_sceneInspectorColumn, _actionHistorySection, row: 2);
    }

    private static void NormalizeSectionStyle(Control section)
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
    /// Reveals one rail page, or none of them when <paramref name="page"/> is
    /// null. No page means no tool is armed and the left button belongs to the
    /// camera, which is how Edit Mesh opens. Revealing never arms a tool: the
    /// rail's tool buttons are the only thing that arms one, so a command page
    /// opens without disturbing the active tool and a layout re-activation
    /// restores the rail's appearance without replacing the live tool.
    /// </summary>
    private void ShowToolRailPage(ToolRailPage? page)
    {
        _selectedToolRailPage = page;
        _toolRailPageSelected = true;
        // Opening a row is four separate paints without this: every page's
        // visibility flips, then the list table re-lays out around the moved
        // body cell, then the column may scroll, then the splitter pass runs.
        // The reader saw that sequence rather than the result, which is what
        // made a tool click feel like it lagged. Every other layout switch here
        // already holds a batch; this was the one that did not, and it is the
        // one on the click path.
        using var redraw = BeginRedrawBatch(_toolDock);
        foreach (var pair in _toolRailPages)
        {
            RevealToolRailPage(pair.Value, pair.Key == page);
            if (pair.Key == page)
            {
                pair.Value.BringToFront();
            }
        }
        foreach (var pair in _toolRailPageButtons)
        {
            SetButtonAccent(pair.Value, pair.Key == page);
        }
        // The tool buttons accent by the armed tool, not the visible page.
        RefreshToolButtonStates();
        // No dock header to retitle: the open row names the page, which is why
        // the header could never disagree with the armed tool again.
        ApplyToolListExpansion(page);
        // Selecting or clearing a page changes how wide the dock needs to be.
        if (IsToolRailActive)
        {
            ApplyToolRailSplitterLayout();
        }
    }

    private ToolRailPage? ToolRailPageForActiveTool() =>
        EditMeshLayoutContracts.ToolRailPageForTool(_viewport.ActiveTool);

    /// <summary>
    /// Keeps the rail in step with the active tool however the tool was chosen:
    /// a rail button, a button inside a page, or the host re-asserting a state.
    /// Dropping back to orbit owns no page, so a modal tool page clears.
    /// </summary>
    /// <remarks>
    /// Topology, Colour and Morph &amp; Refit are command pages: they never arm
    /// a tool, so the viewport sits on orbit the whole time one is open. Closing
    /// a page on "the tool is now orbit" alone would therefore shut them the
    /// moment anything re-asserted orbit — and the host does exactly that every
    /// time it publishes a disabled mesh-edit tool state.
    /// </remarks>
    private void SyncToolRailPageToActiveTool()
    {
        if (!IsToolRailActive)
        {
            return;
        }
        var page = ToolRailPageForActiveTool();
        if (page == _selectedToolRailPage)
        {
            ReopenExpandedRowForActiveTool(page);
            return;
        }
        if (page is null)
        {
            if (_selectedToolRailPage is not null
                && EditMeshLayoutContracts.RailPageIsModal(_selectedToolRailPage.Value))
            {
                ShowToolRailPage(null);
            }
            return;
        }
        if (EditMeshLayoutContracts.RailPageOwnsTool(page.Value, _viewport.ActiveTool))
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
        // As wide as what is open and no wider, so closing a tool hands the
        // width back to the viewport instead of a full-height empty panel.
        var inspectorWidth = MeasureInspectorWidth();
        var toolDockWidth = ScaleToolPanelWidth(MeasureToolColumnWidth());
        var hostWidth = _editMeshLayoutHost?.ClientSize.Width ?? -1;
        // Nothing to move. Laying the splitter out anyway resizes the D3D11
        // swap chain beside it, which reads as the preview flickering.
        // Keyed on DPI too: the applied width is in device pixels, so a stale
        // match on another monitor would skip the pass that resizes it.
        if (_appliedToolDockWidth == toolDockWidth
            && _appliedInspectorWidth == inspectorWidth
            && _appliedLayoutDpi == DeviceDpi
            && _appliedToolRailHostWidth == hostWidth)
        {
            return;
        }
        _applyingToolRailSplitterLayout = true;
        // Freezing the window here is what makes opening a tool one step rather
        // than a visible sequence: without it the reader sees the splitter move,
        // then the column re-lay out, then the page paint into it.
        using var redraw = BeginRedrawBatch(_toolDock);
        try
        {
            _editMeshLayoutHost?.PerformLayout();
            _leftToolSplit.PerformLayout();
            _rightToolSplit.PerformLayout();

            ApplySplitterDistance(
                _leftToolSplit,
                toolDockWidth,
                toolDockWidth,
                ScaleToolPanelWidth(MinimumViewportWidth + inspectorWidth),
                prioritizePanelOne: true);
            _leftToolSplit.PerformLayout();
            EditMeshLayoutContracts.ApplyPanelTwoSize(
                _rightToolSplit,
                ScaleToolPanelWidth(inspectorWidth),
                ScaleToolPanelWidth(MinimumViewportWidth),
                ScaleToolPanelWidth(EditMeshToolColumnMetrics.InspectorFloor));
            // Selecting a tool widens this dock and clearing it narrows it. The
            // strip of flank that the property column vacates keeps whatever was
            // painted there until something asks for it back.
            _leftToolSplit.Panel1.Invalidate(invalidateChildren: true);
            _appliedToolDockWidth = toolDockWidth;
            _appliedInspectorWidth = inspectorWidth;
            _appliedLayoutDpi = DeviceDpi;
            _appliedToolRailHostWidth = hostWidth;
        }
        finally
        {
            _applyingToolRailSplitterLayout = false;
        }
    }
}
