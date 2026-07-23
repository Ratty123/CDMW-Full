namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private enum EditMeshLayoutMode
    {
        Classic,
        BottomToolDeck,
    }

    private enum CompactToolPage
    {
        Selection,
        Transform,
        Brush,
        Topology,
        MorphRefit,
    }

    private readonly Dictionary<CompactToolPage, Button> _compactToolTabButtons = new();
    private readonly Dictionary<CompactToolPage, Panel> _compactToolPages = new();
    private EditMeshLayoutMode _requestedEditMeshLayout = EditMeshLayoutMode.Classic;
    private EditMeshLayoutMode _activeEditMeshLayout = EditMeshLayoutMode.Classic;
    private CompactToolPage _compactSelectedToolPage = CompactToolPage.Selection;
    private bool _compactToolPageSelected;
    private bool _applyingCompactSplitterLayout;
    private int _compactInspectorWidthLogical;
    private int _compactToolDeckHeightLogical;
    private int _compactMorphColumnCount;
    private Point _classicLeftScrollPosition;
    private Point _classicRightScrollPosition;

    private TableLayoutPanel? _editMeshLayoutHost;
    private Control? _classicEditMeshLayoutRoot;
    private SplitContainer? _compactWorkspaceSplit;
    private Control? _compactSessionBar;
    private FlowLayoutPanel? _compactSessionCommandHost;
    private Panel? _rightToolModeHost;
    private TableLayoutPanel? _compactInspectorGrid;
    private TableLayoutPanel? _compactSelectionGrid;
    private Panel? _compactTransformHost;
    private Panel? _compactBrushHost;
    private Panel? _compactTopologyHost;
    private Panel? _compactMorphHost;
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

    private bool IsBottomToolDeckActive =>
        _activeEditMeshLayout == EditMeshLayoutMode.BottomToolDeck;

    private void InitializeEditMeshLayoutHost(Control classicRoot)
    {
        _classicEditMeshLayoutRoot = classicRoot;
        _classicEditMeshLayoutRoot.Dock = DockStyle.Fill;
        BuildPermanentViewportWorkspace();
        BuildPermanentRightToolModeHost();

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
            if (IsBottomToolDeckActive)
            {
                ApplyCompactSplitterLayout();
            }
        };
        _compactSessionBar = BuildCompactSessionBar();
        _compactSessionBar.Visible = false;
        _editMeshLayoutHost.Controls.Add(_compactSessionBar, 0, 0);
        _editMeshLayoutHost.Controls.Add(_classicEditMeshLayoutRoot, 0, 1);
        Controls.Add(_editMeshLayoutHost);
    }

    private void BuildPermanentViewportWorkspace()
    {
        if (_rightToolSplit is null || _presentationViewportRegion is null)
        {
            throw new InvalidOperationException(
                "The permanent Edit Mesh viewport host requires the classic viewport split.");
        }
        _compactWorkspaceSplit = CreateCompactSplit(
            "BottomToolDeckWorkspaceSplit",
            Orientation.Horizontal,
            FixedPanel.Panel2);
        _compactWorkspaceSplit.Panel2.Controls.Add(BuildCompactToolDeck());
        _compactWorkspaceSplit.Panel2Collapsed = true;
        _compactWorkspaceSplit.SplitterMoved += (_, _) => CaptureCompactSplitterLayout();
        _rightToolSplit.Panel1.Controls.Add(_compactWorkspaceSplit);
        // Attach the live viewport region only after its permanent ancestor
        // chain is in place. This is the sole Win32 parent assignment for the
        // resident renderer subtree.
        _compactWorkspaceSplit.Panel1.Controls.Add(_presentationViewportRegion);
    }

    private void BuildPermanentRightToolModeHost()
    {
        if (_rightToolSplit is null || _rightToolPanel is null)
        {
            throw new InvalidOperationException(
                "The permanent Edit Mesh inspector host requires the classic right tool panel.");
        }
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
        var compactInspector = BuildCompactInspector();
        compactInspector.Visible = false;
        _rightToolModeHost.Controls.Add(compactInspector);
        _rightToolSplit.Panel2.Controls.Add(_rightToolModeHost);
    }

    private Control BuildCompactSessionBar()
    {
        var bar = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "BottomToolDeckSessionBar",
            Dock = DockStyle.Fill,
            ColumnCount = 3,
            RowCount = 1,
            Margin = new Padding(0),
            Padding = new Padding(10, 6, 10, 6),
            BackColor = ThemePanelBackground,
        };
        bar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        bar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        bar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        bar.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var title = new Label
        {
            Name = "BottomToolDeckSessionTitle",
            Text = "EDIT MESH  •  EDITABLE",
            AutoSize = true,
            Anchor = AnchorStyles.Left,
            Margin = new Padding(0, 0, 14, 0),
            ForeColor = ThemeAccent,
            BackColor = ThemePanelBackground,
            Font = new Font(Font, FontStyle.Bold),
            AccessibleName = "Edit Mesh, Editable view",
        };
        _compactSessionCommandHost = new FlowLayoutPanel
        {
            Name = "BottomToolDeckSessionCommands",
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            AutoScroll = true,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        ApplyDarkScrollbars(_compactSessionCommandHost);
        var useClassic = StyledActionButton(
            "Use Classic Layout",
            () => RequestEditMeshLayout(EditMeshLayoutMode.Classic));
        useClassic.Name = "UseClassicEditMeshLayoutButton";
        useClassic.AccessibleName = "Use Classic Edit Mesh layout";
        useClassic.AccessibleDescription =
            "Returns the same live Edit Mesh controls and viewport to the classic side-panel layout.";
        useClassic.Margin = new Padding(12, 0, 0, 0);
        useClassic.Anchor = AnchorStyles.Right;

        bar.Controls.Add(title, 0, 0);
        bar.Controls.Add(_compactSessionCommandHost, 1, 0);
        bar.Controls.Add(useClassic, 2, 0);
        return bar;
    }

    private Control BuildCompactToolDeck()
    {
        var deck = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "BottomToolDeck",
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        deck.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        deck.RowStyles.Add(new RowStyle(SizeType.Absolute, ScaleToolPanelWidth(42)));
        deck.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var tabs = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "BottomToolDeckTabs",
            Dock = DockStyle.Fill,
            ColumnCount = 5,
            RowCount = 1,
            Margin = new Padding(0),
            Padding = new Padding(8, 6, 8, 4),
            BackColor = ThemePanelBackground,
        };
        tabs.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        foreach (var _ in Enum.GetValues<CompactToolPage>())
        {
            tabs.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 20));
        }
        AddCompactToolTab(tabs, CompactToolPage.Selection, "Selection", 0);
        AddCompactToolTab(tabs, CompactToolPage.Transform, "Transform", 1);
        AddCompactToolTab(tabs, CompactToolPage.Brush, "Brush", 2);
        AddCompactToolTab(tabs, CompactToolPage.Topology, "Topology", 3);
        AddCompactToolTab(tabs, CompactToolPage.MorphRefit, "Morph & Refit", 4);

        var pageHost = new MeshEditorBufferedPanel
        {
            Name = "BottomToolDeckPageHost",
            Dock = DockStyle.Fill,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        foreach (var page in Enum.GetValues<CompactToolPage>())
        {
            var panel = CreateCompactToolPage(page);
            _compactToolPages.Add(page, panel);
            pageHost.Controls.Add(panel);
        }
        _compactSelectionGrid = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "BottomToolDeckSelectionGrid",
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            Margin = new Padding(0),
            Padding = new Padding(8),
            BackColor = ThemePanelBackground,
        };
        _compactSelectionGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 35));
        _compactSelectionGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 65));
        _compactSelectionGrid.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _compactToolPages[CompactToolPage.Selection].Controls.Add(_compactSelectionGrid);

        _compactTransformHost = CreateCompactSingleSectionHost("BottomToolDeckTransformHost");
        _compactBrushHost = CreateCompactSingleSectionHost("BottomToolDeckBrushHost");
        _compactTopologyHost = CreateCompactSingleSectionHost("BottomToolDeckTopologyHost");
        _compactMorphHost = CreateCompactSingleSectionHost("BottomToolDeckMorphRefitHost");
        _compactMorphHost.Resize += (_, _) => UpdateCompactMorphLayout();
        _compactToolPages[CompactToolPage.Transform].Controls.Add(_compactTransformHost);
        _compactToolPages[CompactToolPage.Brush].Controls.Add(_compactBrushHost);
        _compactToolPages[CompactToolPage.Topology].Controls.Add(_compactTopologyHost);
        _compactToolPages[CompactToolPage.MorphRefit].Controls.Add(_compactMorphHost);

        deck.Controls.Add(tabs, 0, 0);
        deck.Controls.Add(pageHost, 0, 1);
        return deck;
    }

    private void AddCompactToolTab(
        TableLayoutPanel tabs,
        CompactToolPage page,
        string text,
        int column)
    {
        var button = StyledButton(text, height: 30);
        button.Name = $"BottomToolDeck{page}Tab";
        button.AutoSize = false;
        button.Dock = DockStyle.Fill;
        button.Margin = new Padding(column == 0 ? 0 : 3, 0, column == 4 ? 0 : 3, 0);
        button.AccessibleName = $"{text} tools";
        button.Click += (_, _) => ShowCompactToolPage(page);
        _compactToolTabButtons.Add(page, button);
        tabs.Controls.Add(button, column, 0);
    }

    private static Panel CreateCompactToolPage(CompactToolPage page)
    {
        var panel = new MeshEditorBufferedPanel
        {
            Name = $"BottomToolDeck{page}Page",
            Dock = DockStyle.Fill,
            Visible = false,
            AutoScroll = true,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
            TabStop = true,
        };
        ApplyDarkScrollbars(panel);
        return panel;
    }

    private static Panel CreateCompactSingleSectionHost(string name)
    {
        var panel = new MeshEditorBufferedPanel
        {
            Name = name,
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Margin = new Padding(0),
            Padding = new Padding(8),
            BackColor = ThemePanelBackground,
        };
        ApplyDarkScrollbars(panel);
        return panel;
    }

    private Control BuildCompactInspector()
    {
        _compactInspectorGrid = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "BottomToolDeckInspector",
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Margin = new Padding(0),
            Padding = new Padding(8),
            BackColor = ThemePanelBackground,
        };
        _compactInspectorGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _compactInspectorGrid.RowStyles.Add(new RowStyle(SizeType.Percent, 29));
        _compactInspectorGrid.RowStyles.Add(new RowStyle(SizeType.Percent, 24));
        _compactInspectorGrid.RowStyles.Add(new RowStyle(SizeType.Percent, 47));
        return _compactInspectorGrid;
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
        _statusLabel.Text = layout == EditMeshLayoutMode.BottomToolDeck
            ? "Bottom Tool Deck active. All Edit Mesh tools still operate on the same resident session."
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
            // repairs any interrupted compact transition before placement
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
            return true;
        }
        var requestedBeforeSwitch = _requestedEditMeshLayout;
        try
        {
            if (layout == EditMeshLayoutMode.BottomToolDeck)
            {
                ActivateBottomToolDeckLayout();
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
                $"Bottom Tool Deck could not be activated; Classic layout remains in use. {ex.Message}";
            return false;
        }
    }

    private void ActivateBottomToolDeckLayout()
    {
        if (_activeEditMeshLayout == EditMeshLayoutMode.BottomToolDeck
            || _classicEditMeshLayoutRoot is null
            || _editMeshLayoutHost is null
            || _compactSessionBar is null
            || _compactSessionCommandHost is null
            || _compactInspectorGrid is null
            || _compactSelectionGrid is null
            || _compactTransformHost is null
            || _compactBrushHost is null
            || _compactTopologyHost is null
            || _compactMorphHost is null
            || _compactWorkspaceSplit is null
            || _leftToolSplit is null
            || _rightToolSplit is null
            || _rightToolPanel is null
            || _presentationViewportRegion is null)
        {
            return;
        }

        CaptureToolPanelLayout(persist: false);
        CaptureClassicScrollPositions();
        SuspendAllEditMeshLayouts();
        try
        {
            MoveSessionControlsToCompactBar();
            ConfigurePresentationRegion(compactEditableOnly: true);

            AddCompactSection(_compactSelectionGrid, _partPickSection, 0, 0);
            AddCompactSection(_compactSelectionGrid, _selectionSection, 1, 0);
            AddCompactSection(_compactTransformHost, _transformSection);
            AddCompactSection(_compactBrushHost, _brushSection);
            AddCompactSection(_compactTopologyHost, _topologySection);
            AddCompactSection(_compactMorphHost, _morphRefitSection);
            AddCompactInspectorSection(_partsSection, 0, stretchFirstRow: true);
            AddCompactInspectorSection(_actionHistorySection, 1, stretchFirstRow: true);
            AddCompactInspectorSection(_viewportSection, 2);

            _compactSessionBar.Visible = true;
            _editMeshLayoutHost.RowStyles[0].Height = ScaleToolPanelWidth(48);
            _rightToolPanel.Visible = false;
            _compactInspectorGrid.Visible = true;
            _compactInspectorGrid.BringToFront();
            _leftToolSplit.Panel1Collapsed = true;
            _rightToolSplit.Panel2Collapsed = false;
            _compactWorkspaceSplit.Panel2Collapsed = false;
            _activeEditMeshLayout = EditMeshLayoutMode.BottomToolDeck;
            ApplyCompactSplitterLayout();
            if (!_compactToolPageSelected)
            {
                _compactSelectedToolPage = CompactPageForActiveTool();
                _compactToolPageSelected = true;
            }
            ShowCompactToolPage(_compactSelectedToolPage);
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
        SuspendAllEditMeshLayouts();
        try
        {
            ExitCompactMorphLayout();
            MoveSessionControlsToClassicSection();
            RebuildClassicToolStacks();
            ConfigurePresentationRegion(compactEditableOnly: false);
            if (_compactWorkspaceSplit is not null)
            {
                _compactWorkspaceSplit.Panel2Collapsed = true;
            }
            if (_compactSessionBar is not null)
            {
                _compactSessionBar.Visible = false;
            }
            _editMeshLayoutHost.RowStyles[0].Height = 0;
            if (_compactInspectorGrid is not null)
            {
                _compactInspectorGrid.Visible = false;
            }
            if (_rightToolPanel is not null)
            {
                _rightToolPanel.Visible = true;
                _rightToolPanel.BringToFront();
            }
            if (_leftToolSplit is not null)
            {
                _leftToolSplit.Panel1Collapsed = false;
            }
            if (_rightToolSplit is not null)
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
        RestoreClassicScrollPositions();
    }

    private void MoveSessionControlsToCompactBar()
    {
        if (_compactSessionCommandHost is null)
        {
            return;
        }
        _compactSessionCommandHost.Controls.Clear();
        foreach (var button in SessionCommandButtons())
        {
            button.Dock = DockStyle.None;
            button.Margin = new Padding(3, 0, 3, 0);
            button.MinimumSize = new Size(
                Math.Max(button.MinimumSize.Width, button.GetPreferredSize(Size.Empty).Width),
                Math.Max(30, button.MinimumSize.Height));
            EditMeshLayoutContracts.MoveControl(
                button,
                _compactSessionCommandHost,
                DockStyle.None);
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

    private static void AddCompactSection(
        Control host,
        Control? section,
        int column = -1,
        int row = -1)
    {
        if (section is null)
        {
            return;
        }
        ApplyCompactSectionStyle(section);
        if (host is TableLayoutPanel table && column >= 0 && row >= 0)
        {
            EditMeshLayoutContracts.MoveControl(
                section,
                table,
                column,
                row,
                DockStyle.Fill);
        }
        else
        {
            EditMeshLayoutContracts.MoveControl(section, host, DockStyle.Fill);
        }
        section.BringToFront();
    }

    private void AddCompactInspectorSection(
        Control? section,
        int row,
        bool stretchFirstRow = false)
    {
        if (_compactInspectorGrid is null || section is null)
        {
            return;
        }
        ApplyCompactSectionStyle(section);
        if (stretchFirstRow && section is GroupBox group)
        {
            ConfigureCompactStretchBody(group);
        }
        EditMeshLayoutContracts.MoveControl(
            section,
            _compactInspectorGrid,
            0,
            row,
            DockStyle.Fill);
    }

    private static void ApplyCompactSectionStyle(Control section)
    {
        section.AutoSize = false;
        section.Dock = DockStyle.Fill;
        section.Margin = new Padding(4);
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
    }

    private static void ConfigureCompactStretchBody(GroupBox group)
    {
        if (group.Controls.OfType<TableLayoutPanel>().SingleOrDefault() is not { } body
            || body.RowStyles.Count == 0)
        {
            return;
        }
        body.AutoSize = false;
        body.Dock = DockStyle.Fill;
        for (var row = 0; row < body.RowStyles.Count; row++)
        {
            body.RowStyles[row].SizeType = row == 0
                ? SizeType.Percent
                : SizeType.AutoSize;
            body.RowStyles[row].Height = row == 0 ? 100 : 0;
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

    private void ShowCompactToolPage(CompactToolPage page)
    {
        _compactSelectedToolPage = page;
        _compactToolPageSelected = true;
        foreach (var pair in _compactToolPages)
        {
            pair.Value.Visible = pair.Key == page;
            if (pair.Key == page)
            {
                pair.Value.BringToFront();
            }
        }
        foreach (var pair in _compactToolTabButtons)
        {
            SetButtonLatched(pair.Value, pair.Key == page);
        }
        if (page == CompactToolPage.MorphRefit)
        {
            UpdateCompactMorphLayout();
        }
    }

    private CompactToolPage CompactPageForActiveTool()
    {
        return _viewport.ActiveTool.ToLowerInvariant() switch
        {
            "move" or "grab" => CompactToolPage.Transform,
            "smooth" or "inflate" or "pinch" => CompactToolPage.Brush,
            _ => CompactToolPage.Selection,
        };
    }

    private void UpdateCompactMorphLayout()
    {
        if (!IsBottomToolDeckActive || _compactMorphHost is null)
        {
            return;
        }
        var columnCount = CompactMorphColumnCount();
        if (columnCount == _compactMorphColumnCount)
        {
            return;
        }
        _compactMorphColumnCount = columnCount;
        EnterCompactMorphLayout(columnCount);
    }

    private int CompactMorphColumnCount()
    {
        var deviceWidth = Math.Max(
            1,
            _compactMorphHost?.ClientSize.Width
                ?? _compactWorkspaceSplit?.Panel2.ClientSize.Width
                ?? ClientSize.Width);
        var logicalWidth = LogicalToolPanelWidth(deviceWidth);
        return EditMeshLayoutContracts.MorphColumnsForLogicalWidth(logicalWidth);
    }

    private void ApplyCompactSplitterLayout()
    {
        if (_applyingCompactSplitterLayout
            || _rightToolSplit is null
            || _compactWorkspaceSplit is null)
        {
            return;
        }
        _applyingCompactSplitterLayout = true;
        try
        {
            _editMeshLayoutHost?.PerformLayout();
            _rightToolSplit.PerformLayout();
            _compactWorkspaceSplit.PerformLayout();

            var inspectorWidth = _compactInspectorWidthLogical > 0
                ? _compactInspectorWidthLogical
                : EditMeshLayoutContracts.DefaultInspectorWidth(
                    LogicalToolPanelWidth(ClientSize.Width));
            var deckHeight = _compactToolDeckHeightLogical > 0
                ? _compactToolDeckHeightLogical
                : EditMeshLayoutContracts.DefaultToolDeckHeight(
                    LogicalToolPanelWidth(ClientSize.Height));
            EditMeshLayoutContracts.ApplyPanelTwoSize(
                _rightToolSplit,
                ScaleToolPanelWidth(inspectorWidth),
                ScaleToolPanelWidth(360),
                ScaleToolPanelWidth(300));
            EditMeshLayoutContracts.ApplyPanelTwoSize(
                _compactWorkspaceSplit,
                ScaleToolPanelWidth(deckHeight),
                ScaleToolPanelWidth(MinimumViewportWidth),
                ScaleToolPanelWidth(220));
        }
        finally
        {
            _applyingCompactSplitterLayout = false;
        }
    }

    private void CaptureCompactSplitterLayout()
    {
        if (_applyingCompactSplitterLayout
            || !IsBottomToolDeckActive
            || _rightToolSplit is null
            || _compactWorkspaceSplit is null)
        {
            return;
        }
        var inspectorWidth = Math.Max(
            0,
            _rightToolSplit.ClientSize.Width
                - _rightToolSplit.SplitterWidth
                - _rightToolSplit.SplitterDistance);
        var deckHeight = Math.Max(
            0,
            _compactWorkspaceSplit.ClientSize.Height
                - _compactWorkspaceSplit.SplitterWidth
                - _compactWorkspaceSplit.SplitterDistance);
        _compactInspectorWidthLogical = LogicalToolPanelWidth(inspectorWidth);
        _compactToolDeckHeightLogical = LogicalToolPanelWidth(deckHeight);
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
        _compactWorkspaceSplit?.SuspendLayout();
        _rightToolModeHost?.SuspendLayout();
        _compactInspectorGrid?.SuspendLayout();
        _compactSelectionGrid?.SuspendLayout();
        SuspendToolPanelLayout();
    }

    private void ResumeAllEditMeshLayouts()
    {
        ResumeToolPanelLayout();
        _compactSelectionGrid?.ResumeLayout(performLayout: false);
        _compactInspectorGrid?.ResumeLayout(performLayout: false);
        _rightToolModeHost?.ResumeLayout(performLayout: true);
        _compactWorkspaceSplit?.ResumeLayout(performLayout: true);
        _classicEditMeshLayoutRoot?.ResumeLayout(performLayout: true);
        _editMeshLayoutHost?.ResumeLayout(performLayout: true);
    }
}
