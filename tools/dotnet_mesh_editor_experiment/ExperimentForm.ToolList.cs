using RowKeys = Cdmw.MeshEditorExperiment.EditMeshToolListContract.Keys;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The Edit Mesh tool list: one column where every tool is a row and the armed
/// tool's settings open underneath the row that armed them.
/// </summary>
/// <remarks>
/// This replaces a rail beside a property panel. Two surfaces meant a tool could
/// be named twice — once on the rail and again on the page it opened — and it
/// was, for all five modal tools. One surface makes that impossible: the row is
/// the header of its own settings, so there is nowhere for a duplicate to live.
/// </remarks>
internal sealed partial class ExperimentForm
{
    private const int ToolListRowHeight = 34;

    private MeshEditorBufferedTableLayoutPanel? _toolListTable;
    private MeshEditorBufferedPanel? _toolListBodyHost;
    private MeshEditorBufferedPanel? _toolListScroll;
    private Label? _toolListGroupLabel;
    private readonly Dictionary<string, ToolListRow> _toolListRowsByKey =
        new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<ToolRailPage, int> _columnWidthByPage = new();
    private int? _collapsedColumnWidth;
    private int? _sharedOpenColumnWidth;
    private int? _inspectorWidth;

    /// <summary>
    /// The single column: a scrolling list of rows with one body host that moves
    /// to sit under whichever row is open.
    /// </summary>
    private Control BuildToolListColumn()
    {
        _toolListScroll = new MeshEditorBufferedPanel
        {
            Name = "EditMeshToolListScroll",
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Margin = new Padding(0),
            Padding = new Padding(10, 8, 10, 10),
            BackColor = ThemePanelBackground,
        };
        ApplyDarkScrollbars(_toolListScroll);

        _toolListTable = new MeshEditorBufferedTableLayoutPanel
        {
            Name = "EditMeshToolListTable",
            Dock = DockStyle.Top,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            ColumnCount = 1,
            RowCount = EditMeshToolListContract.TableRowCount,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        _toolListTable.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        for (var cell = 0; cell < EditMeshToolListContract.TableRowCount; cell++)
        {
            _toolListTable.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        }

        foreach (var row in EditMeshToolListContract.RowOrder)
        {
            AddToolListRow(row);
        }
        EditMeshToolListContract.RequireCompleteList(
            EditMeshToolListContract.RowOrder.Select(row => row.Key).ToArray());

        _toolListGroupLabel = BuildToolListGroupLabel();
        _toolListTable.Controls.Add(
            _toolListGroupLabel,
            0,
            EditMeshToolListContract.GroupLabelBaseCell);

        // Every page lives in this one host for the life of the session. Opening
        // a row moves the host's cell, not the pages, so revealing a page never
        // re-parents a realised control tree — which is the operation that has
        // been seen to fail with ERROR_INVALID_STATE under an embedded host.
        _toolListBodyHost = new MeshEditorBufferedPanel
        {
            Name = "EditMeshToolListBodyHost",
            Dock = DockStyle.Top,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Margin = new Padding(0, 0, 0, 6),
            Padding = new Padding(10, 8, 8, 4),
            BackColor = ThemeSectionBackground,
        };
        foreach (var page in Enum.GetValues<ToolRailPage>())
        {
            var host = CreateToolRailPage(page);
            _toolRailPages.Add(page, host);
            _toolListBodyHost.Controls.Add(host);
        }

        // Selection is the one page that owns two sections, so it gets a grid
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

        _toolListTable.Controls.Add(_toolListBodyHost, 0, EditMeshToolListContract.ParkedBodyCell);
        _toolListBodyHost.Visible = false;

        _toolListScroll.Controls.Add(_toolListTable);
        return _toolListScroll;
    }

    /// <summary>
    /// A row's glyph. Kept beside the caption so a row is described in one place.
    /// </summary>
    private static string ToolListRowGlyph(string key) => key switch
    {
        RowKeys.Select => "◰",
        RowKeys.Move => "✥",
        RowKeys.Grab => "✜",
        RowKeys.Smooth => "◍",
        RowKeys.Inflate => "◉",
        RowKeys.Pinch => "◇",
        RowKeys.Topology => "△",
        RowKeys.Colour => "◧",
        _ => "◑",
    };

    /// <summary>
    /// A row's caption. These are the visible name of every tool, so they live
    /// at the callsite the localization manifest keys them from.
    /// </summary>
    private static string ToolListRowCaption(string key) => key switch
    {
        RowKeys.Select => "Select",
        RowKeys.Move => "Move",
        RowKeys.Grab => "Grab",
        RowKeys.Smooth => "Smooth",
        RowKeys.Inflate => "Inflate",
        RowKeys.Pinch => "Pinch",
        RowKeys.Topology => "Topology",
        RowKeys.Colour => "Colour",
        _ => "Morph & Refit",
    };

    /// <summary>
    /// What a row's page holds, shown on hover. Rows that share a page share
    /// their description, because they open the same settings.
    /// </summary>
    private static string ToolListRowDescription(string key) => key switch
    {
        RowKeys.Select => "Whole-part selection: drag shape, combine mode and X-Ray.",
        RowKeys.Move or RowKeys.Grab => "Translate step, Move and Grab.",
        RowKeys.Smooth or RowKeys.Inflate or RowKeys.Pinch =>
            "Smooth, Inflate and Pinch with radius, strength and falloff.",
        RowKeys.Topology => "Subdivide and Refine Smooth.",
        RowKeys.Colour => "Per-part tint, recolour and glow for the current selection.",
        _ => "Definition profiles, shape sliders and garment refit binding.",
    };

    private void AddToolListRow(ToolListRow row)
    {
        var caption = ToolListRowCaption(row.Key);
        var button = BuildToolListRowButton(row);
        _toolListRowsByKey[row.Key] = row;
        if (row.Kind == ToolListRowKind.Tool)
        {
            button.Name = $"EditMeshToolList{caption}ToolButton";
            button.AccessibleName = $"{caption} tool";
            // Arming is what opens the page: SetActiveTool routes through
            // SyncToolRailPageToActiveTool, so the row that armed the tool is
            // the row that ends up open however the tool was chosen.
            button.Click += (_, _) => ActivateTool(row.Key, caption, announce: true);
            _toolRailToolButtons.Add(row.Key, button);
        }
        else
        {
            button.Name = $"EditMeshToolList{row.Page}PageButton";
            button.AccessibleName = $"{caption} commands";
            // A command row only reveals. Topology, Colour and Morph & Refit
            // hold one-shot commands, so opening one must leave the armed tool
            // exactly as it was.
            button.Click += (_, _) => ShowToolRailPage(row.Page);
            _toolRailPageButtons.Add(row.Page, button);
        }
        _toolListTable!.Controls.Add(
            button,
            0,
            EditMeshToolListContract.BaseCell(EditMeshToolListContract.IndexOfRow(row)));
    }

    /// <summary>
    /// A row reads left to right — glyph, then caption — because it is a list
    /// entry rather than a rail tile. The glyph keeps its column so the captions
    /// align down the list.
    /// </summary>
    private Button BuildToolListRowButton(ToolListRow row)
    {
        var button = StyledButton(
            $"{ToolListRowGlyph(row.Key)}    {ToolListRowCaption(row.Key)}",
            height: ToolListRowHeight);
        button.AutoSize = false;
        button.Dock = DockStyle.Top;
        button.Height = ScaleToolPanelWidth(ToolListRowHeight);
        button.Margin = new Padding(0, 0, 0, 2);
        button.Padding = new Padding(10, 0, 8, 0);
        button.TextAlign = ContentAlignment.MiddleLeft;
        SetHelpText(button, ToolListRowDescription(row.Key));
        return button;
    }

    private Label BuildToolListGroupLabel()
    {
        var label = new Label
        {
            // The break earns its line: everything below it opens a page without
            // arming anything, and the reader can see that before clicking.
            Text = "COMMANDS",
            Dock = DockStyle.Top,
            AutoSize = false,
            Height = ScaleToolPanelWidth(24),
            TextAlign = ContentAlignment.BottomLeft,
            Margin = new Padding(0, 8, 0, 2),
            Padding = new Padding(2, 0, 0, 3),
            ForeColor = ThemeMutedText,
            BackColor = ThemePanelBackground,
        };
        // Assigned outside the initializer: a control name sitting beside a Text
        // literal is picked up by the localization scanner as if it were one.
        label.Name = "EditMeshToolListCommandGroupLabel";
        return label;
    }

    /// <summary>
    /// Moves the open body under the row that opened it and pushes everything
    /// below down one cell. Cell moves inside one parent are not re-parents, so
    /// this never issues a SetParent and cannot hit the embedded-host failure
    /// that page reveal has to guard against.
    /// </summary>
    private void ApplyToolListExpansion(ToolRailPage? page)
    {
        if (_toolListTable is null || _toolListBodyHost is null || _toolListGroupLabel is null)
        {
            return;
        }
        var expandedRow = page is null ? null : ToolListRowForPage(page.Value);
        int? expandedBaseCell = expandedRow is null
            ? null
            : EditMeshToolListContract.BaseCell(EditMeshToolListContract.IndexOfRow(expandedRow));

        // Batched here as well as in ShowToolRailPage, because the two tools
        // that share a page reach this without going through it: arming Inflate
        // after Smooth leaves the page where it is, so only the open body moves.
        // SuspendLayout defers the measurement but not the painting, so without
        // this the reader watches the rows shuffle up and the body land. The
        // batch is refcounted, so arriving from ShowToolRailPage still paints
        // once for the whole click.
        using var redraw = BeginRedrawBatch();
        _toolListTable.SuspendLayout();
        try
        {
            foreach (var row in EditMeshToolListContract.RowOrder)
            {
                var button = ToolListButtonFor(row);
                if (button is null)
                {
                    continue;
                }
                var baseCell = EditMeshToolListContract.BaseCell(
                    EditMeshToolListContract.IndexOfRow(row));
                _toolListTable.SetCellPosition(
                    button,
                    new TableLayoutPanelCellPosition(
                        0,
                        EditMeshToolListContract.ResolvedCell(baseCell, expandedBaseCell)));
            }
            _toolListTable.SetCellPosition(
                _toolListGroupLabel,
                new TableLayoutPanelCellPosition(
                    0,
                    EditMeshToolListContract.ResolvedCell(
                        EditMeshToolListContract.GroupLabelBaseCell,
                        expandedBaseCell)));
            _toolListTable.SetCellPosition(
                _toolListBodyHost,
                new TableLayoutPanelCellPosition(
                    0,
                    expandedBaseCell is { } cell
                        ? EditMeshToolListContract.BodyCell(cell)
                        : EditMeshToolListContract.ParkedBodyCell));
            _toolListBodyHost.Visible = expandedBaseCell is not null;
        }
        finally
        {
            _toolListTable.ResumeLayout(performLayout: true);
        }
        ScrollOpenRowIntoView(expandedRow);
    }

    /// <summary>
    /// Moves the open settings to the row that is armed now, when the page did
    /// not change but the tool did.
    /// </summary>
    /// <remarks>
    /// Move and Grab share the Transform page, and Smooth, Inflate and Pinch
    /// share Brush. Switching between two tools of one page leaves the page
    /// exactly where it was, so nothing above this notices — and the settings
    /// stayed open under the tool the reader had just left, with the highlight
    /// on the new one further down the list.
    /// </remarks>
    private void ReopenExpandedRowForActiveTool(ToolRailPage? page)
    {
        if (page is { } value)
        {
            ApplyToolListExpansion(value);
        }
    }

    /// <summary>
    /// Opening the last row puts its settings below the fold, so the row and as
    /// much of its body as fits are brought into view. Scrolling to the body
    /// alone would push the row that names it off the top.
    /// </summary>
    private void ScrollOpenRowIntoView(ToolListRow? expandedRow)
    {
        if (expandedRow is null || _toolListScroll is null || !_toolListScroll.AutoScroll)
        {
            return;
        }
        var button = ToolListButtonFor(expandedRow);
        if (button is null || !button.IsHandleCreated)
        {
            return;
        }
        // Only scroll when the row is actually out of view. ScrollControlIntoView
        // walks and re-lays out the scroll host every time it is called, and for
        // the rows already on screen -- which is most clicks -- that work buys
        // nothing and is felt as the column hitching under the pointer.
        var top = button.Top + _toolListScroll.AutoScrollPosition.Y;
        if (top >= 0 && top + button.Height <= _toolListScroll.ClientSize.Height)
        {
            return;
        }
        _toolListScroll.ScrollControlIntoView(button);
    }

    /// <summary>
    /// What to call a page in a failure message. A page has no name of its own
    /// here, so it borrows the caption of the first row that opens it, and falls
    /// back to the control name when no page is selected to borrow from.
    /// </summary>
    private static string ToolListPageDisplayName(Control page, ToolRailPage? selected)
    {
        if (selected is not { } value)
        {
            return page.Name;
        }
        var row = EditMeshToolListContract.FirstRowForPage(value);
        return row is null ? page.Name : ToolListRowCaption(row.Key);
    }

    private Button? ToolListButtonFor(ToolListRow row) =>
        row.Kind == ToolListRowKind.Tool
            ? _toolRailToolButtons.GetValueOrDefault(row.Key)
            : _toolRailPageButtons.GetValueOrDefault(row.Page);

    /// <summary>
    /// Which row a page belongs to. A command page owns exactly one row. A modal
    /// page is shared — Move and Grab share Transform, and the three brushes
    /// share Brush — so the armed tool decides, and only falls back to the
    /// page's first row when the armed tool is not one of them.
    /// </summary>
    private ToolListRow ToolListRowForPage(ToolRailPage page)
    {
        var armed = EditMeshToolListContract.RowForTool(_viewport.ActiveTool);
        if (armed is not null && armed.Page == page)
        {
            return armed;
        }
        return Array.Find(EditMeshToolListContract.RowOrder, row => row.Page == page)
            ?? EditMeshToolListContract.RowOrder[0];
    }

    /// <summary>
    /// How wide the column has to be for what is currently in it. Measured, not
    /// assumed: the old dock reserved a constant 414 logical pixels whether a
    /// page was open or not.
    /// </summary>
    /// <summary>
    /// How wide the column has to be for what is currently in it.
    /// </summary>
    /// <remarks>
    /// Every capped page resolves to one shared width rather than its own. The
    /// dock lives in a splitter whose other side holds the D3D11 viewport, so
    /// changing this number resizes the swap chain — and a per-page width meant
    /// every tool click resized the preview, which is what the flicker was.
    /// Sharing one width leaves exactly two transitions: the first tool opened,
    /// and Morph &amp; Refit, which is the one page allowed to be wider.
    /// </remarks>
    private int MeasureToolColumnWidth()
    {
        var key = _selectedToolRailPage;
        if (key is null)
        {
            return _collapsedColumnWidth ??= MeasureColumnWidthFor(null);
        }
        if (EditMeshToolColumnMetrics.PageWidthIsUncapped(key.Value))
        {
            if (!_columnWidthByPage.TryGetValue(key.Value, out var uncapped))
            {
                uncapped = MeasureColumnWidthFor(key.Value);
                _columnWidthByPage[key.Value] = uncapped;
            }
            return uncapped;
        }
        if (_sharedOpenColumnWidth is { } shared)
        {
            return shared;
        }
        // The widest capped page decides for all of them, so opening any of
        // them lands on the same splitter distance.
        var widest = 0;
        foreach (var page in Enum.GetValues<ToolRailPage>())
        {
            if (!EditMeshToolColumnMetrics.PageWidthIsUncapped(page))
            {
                widest = Math.Max(widest, MeasureColumnWidthFor(page));
            }
        }
        _sharedOpenColumnWidth = widest;
        return widest;
    }

    private int MeasureColumnWidthFor(ToolRailPage? page)
    {
        var content = 0;
        if (page is { } open && _toolRailPages.TryGetValue(open, out var host))
        {
            content = host.GetPreferredSize(Size.Empty).Width;
            if (_toolListBodyHost is not null)
            {
                content += _toolListBodyHost.Padding.Horizontal;
            }
        }
        foreach (var row in EditMeshToolListContract.RowOrder)
        {
            var button = ToolListButtonFor(row);
            if (button is not null)
            {
                content = Math.Max(content, button.GetPreferredSize(Size.Empty).Width);
            }
        }
        return EditMeshToolColumnMetrics.PreferredColumnWidth(
            LogicalToolPanelWidth(content),
            page);
    }

    private int MeasureInspectorWidth()
    {
        if (_inspectorWidth is { } cached)
        {
            return cached;
        }
        var content = 0;
        if (_sceneInspectorColumn is not null)
        {
            content = _sceneInspectorColumn.GetPreferredSize(Size.Empty).Width;
        }
        var width = EditMeshToolColumnMetrics.PreferredInspectorWidth(
            LogicalToolPanelWidth(content));
        _inspectorWidth = width;
        return width;
    }

    /// <summary>
    /// Drops the measured widths so the next layout re-measures.
    /// </summary>
    /// <remarks>
    /// A page's preferred width is a property of its controls and the font they
    /// are drawn in, so it does not change when the reader picks a different
    /// tool — and re-measuring the whole scene inspector plus every page on each
    /// click is most of what made opening one feel slow. Only a font or DPI
    /// change can move these numbers.
    /// </remarks>
    private void InvalidateToolColumnWidths()
    {
        _columnWidthByPage.Clear();
        _collapsedColumnWidth = null;
        _sharedOpenColumnWidth = null;
        _inspectorWidth = null;
        _appliedToolDockWidth = -1;
        _appliedInspectorWidth = -1;
    }

    protected override void OnDpiChanged(DpiChangedEventArgs e)
    {
        base.OnDpiChanged(e);
        InvalidateToolColumnWidths();
    }

    /// <summary>
    /// The embedded helper is a child window, and a child is told about a DPI
    /// change through this rather than through <see cref="OnDpiChanged"/> — which
    /// only ever fires for a top-level window. Dragging the app to a monitor at a
    /// different scale is exactly the case the cached widths must not survive.
    /// </summary>
    protected override void OnDpiChangedAfterParent(EventArgs e)
    {
        base.OnDpiChangedAfterParent(e);
        InvalidateToolColumnWidths();
        if (!IsToolRailActive)
        {
            return;
        }
        // Posted rather than run inline. The layout pass opens a redraw batch,
        // and WM_SETREDRAW(FALSE) clears WS_VISIBLE for as long as the batch is
        // held. A DPI change is exactly when WinForms rescales fonts and can
        // recreate handles, and a recreation landing inside the batch rebuilds
        // this window from a style that has lost WS_VISIBLE -- the failure
        // CreateParams already had to be taught to rescue. Running it on a
        // later message does the same work with the DPI change settled.
        try
        {
            BeginInvoke(new Action(() =>
            {
                if (!IsDisposed && !Disposing && IsToolRailActive)
                {
                    ApplyToolRailSplitterLayout();
                }
            }));
        }
        catch (InvalidOperationException)
        {
            // No message loop to post to yet; the next resize or page change
            // runs the same pass.
        }
    }

    protected override void OnFontChanged(EventArgs e)
    {
        base.OnFontChanged(e);
        InvalidateToolColumnWidths();
    }
}
