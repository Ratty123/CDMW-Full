namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The modal tools, one rail button each. Only these swap with the rail — the
/// scene groups (Parts, Action History, Viewport) are not modal and live
/// permanently in the right inspector. Declaration order is rail order.
/// </summary>
internal enum ToolRailPage
{
    Selection,
    Transform,
    Brush,
    Topology,
    Colour,
    MorphRefit,
}

internal static class EditMeshLayoutContracts
{
    /// <summary>
    /// The tool a rail page puts the viewport into. Topology, Colour and
    /// Morph &amp; Refit are command pages rather than modal tools, so they leave
    /// the active tool alone and return null.
    /// </summary>
    public static string? DefaultToolForRailPage(ToolRailPage page) => page switch
    {
        ToolRailPage.Selection => "select",
        ToolRailPage.Transform => "move",
        ToolRailPage.Brush => "smooth",
        _ => null,
    };

    public static bool RailPageOwnsTool(ToolRailPage page, string? tool)
    {
        var normalized = (tool ?? string.Empty).Trim().ToLowerInvariant();
        return page switch
        {
            ToolRailPage.Selection => normalized == "select",
            ToolRailPage.Transform => normalized is "move" or "grab",
            ToolRailPage.Brush => normalized is "smooth" or "inflate" or "pinch",
            _ => false,
        };
    }

    /// <summary>
    /// The page that owns a tool, or null when no page does.
    /// </summary>
    /// <remarks>
    /// Edit Mesh opens on <c>orbit</c>, and the camera is not a rail page: it is
    /// always available through the modifiers named on the navigation strip. So
    /// orbit — and any tool the rail has not been taught — selects no page at
    /// all. Returning a page here instead is what used to arm Select on entry,
    /// because the rail asserts the selected page's own default tool.
    /// </remarks>
    public static ToolRailPage? ToolRailPageForTool(string? tool) =>
        (tool ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            "select" => ToolRailPage.Selection,
            "move" or "grab" => ToolRailPage.Transform,
            "smooth" or "inflate" or "pinch" => ToolRailPage.Brush,
            _ => null,
        };

    public static int MorphColumnsForLogicalWidth(int logicalWidth)
    {
        return logicalWidth >= 1500 ? 4 : logicalWidth >= 900 ? 2 : 1;
    }

    public static int DefaultInspectorWidth(int clientLogicalWidth)
    {
        return Math.Clamp(
            (int)Math.Round(Math.Max(1, clientLogicalWidth) * 0.23),
            380,
            560);
    }

    /// <summary>
    /// Width of the whole right dock: the contextual panel plus the rail beside
    /// it. The rail is fixed, so only the panel share scales with the window.
    /// </summary>
    public static int DefaultToolRailPanelWidth(int clientLogicalWidth, int railWidth)
    {
        // The floor is set by the widest three-button row in Morph & Refit
        // ("Author Slider… / Save Profile / Delete Profile"); below it those
        // rows clip instead of wrapping.
        var panel = Math.Clamp(
            (int)Math.Round(Math.Max(1, clientLogicalWidth) * 0.19),
            380,
            520);
        return panel + Math.Max(0, railWidth);
    }

    public static void ApplyPanelTwoSize(
        SplitContainer split,
        int panelTwoSize,
        int requestedPanelOneMinimum,
        int requestedPanelTwoMinimum)
    {
        ArgumentNullException.ThrowIfNull(split);

        // Compact splitters are created while their hidden parent still has
        // construction-time dimensions. Clear stale/default minimums first so
        // a zero-size pass cannot make SplitterDistance invalid.
        split.Panel1MinSize = 0;
        split.Panel2MinSize = 0;
        var available = split.Orientation == Orientation.Vertical
            ? split.ClientSize.Width - split.SplitterWidth
            : split.ClientSize.Height - split.SplitterWidth;
        available = Math.Max(0, available);
        if (available <= 0)
        {
            return;
        }

        var panelTwoMinimum = Math.Min(
            Math.Max(0, requestedPanelTwoMinimum),
            available);
        var panelOneMinimum = Math.Min(
            Math.Max(0, requestedPanelOneMinimum),
            available - panelTwoMinimum);
        split.SplitterDistance = Math.Clamp(
            available - Math.Max(0, panelTwoSize),
            panelOneMinimum,
            Math.Max(panelOneMinimum, available - panelTwoMinimum));
        split.Panel1MinSize = panelOneMinimum;
        split.Panel2MinSize = panelTwoMinimum;
    }

    public static void MoveControl(Control control, Control host, DockStyle dock)
    {
        ArgumentNullException.ThrowIfNull(control);
        ArgumentNullException.ThrowIfNull(host);
        if (control.IsDisposed || host.IsDisposed)
        {
            throw new InvalidOperationException("A disposed Edit Mesh control cannot be moved between layouts.");
        }
        if (!ReferenceEquals(control.Parent, host))
        {
            host.Controls.Add(control);
        }
        control.Dock = dock;
    }

    public static void MoveControl(
        Control control,
        TableLayoutPanel host,
        int column,
        int row,
        DockStyle dock)
    {
        ArgumentNullException.ThrowIfNull(control);
        ArgumentNullException.ThrowIfNull(host);
        if (control.IsDisposed || host.IsDisposed)
        {
            throw new InvalidOperationException("A disposed Edit Mesh control cannot be moved between layouts.");
        }
        if (ReferenceEquals(control.Parent, host))
        {
            host.SetCellPosition(
                control,
                new TableLayoutPanelCellPosition(column, row));
        }
        else
        {
            host.Controls.Add(control, column, row);
        }
        control.Dock = dock;
    }
}
