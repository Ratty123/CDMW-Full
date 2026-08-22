namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The tool-property pages, one per tool family or command group. The rail
/// itself lists individual tools, several of which share a page — the
/// scene groups (Parts, Action History, Viewport) are not modal and live
/// permanently in the right inspector.
/// </summary>
internal enum ToolRailPage
{
    Selection,
    Transform,
    Brush,
    Topology,
    MorphRefit,
}

internal static class EditMeshLayoutContracts
{
    /// <summary>
    /// Every armable tool, in rail order. Each is its own rail button and
    /// clicking one arms exactly that tool — nothing else in the rail arms
    /// anything.
    /// </summary>
    public static readonly string[] RailToolOrder =
    {
        "select",
        "move",
        "grab",
        "smooth",
        "inflate",
        "pinch",
    };

    /// <summary>
    /// The command pages that keep a rail entry of their own, in rail order.
    /// Their entries only reveal the page: Topology and Morph &amp; Refit
    /// hold one-shot commands and settings, not modal tools, so revealing one
    /// leaves the active tool alone.
    /// </summary>
    public static readonly ToolRailPage[] RailCommandPageOrder =
    {
        ToolRailPage.Topology,
        ToolRailPage.MorphRefit,
    };

    /// <summary>
    /// True for a page that owns modal tools. Only a modal page follows the
    /// active tool — and only a modal page may be closed because the tool
    /// dropped back to orbit. Command pages sit on orbit the whole time they
    /// are open, so the tool says nothing about whether to close them.
    /// </summary>
    public static bool RailPageIsModal(ToolRailPage page) =>
        page is ToolRailPage.Selection or ToolRailPage.Transform or ToolRailPage.Brush;

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
    /// Edit Mesh opens on <c>orbit</c>, and the camera is not a rail entry: it is
    /// always available through the modifiers named on the navigation strip. So
    /// orbit — and any tool the rail has not been taught — selects no page at
    /// all, and the rail opens with nothing highlighted and nothing armed.
    /// </remarks>
    public static ToolRailPage? ToolRailPageForTool(string? tool) =>
        (tool ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            "select" => ToolRailPage.Selection,
            "move" or "grab" => ToolRailPage.Transform,
            "smooth" or "inflate" or "pinch" => ToolRailPage.Brush,
            _ => null,
        };

    /// <summary>
    /// Fails construction when the built rail disagrees with the contract's
    /// tool and command-page inventories. The rail is built from literals so
    /// each caption stays a translatable callsite, and this is what keeps
    /// those literals from drifting away from the executed contract.
    /// </summary>
    public static void RequireCompleteRail(
        IReadOnlyCollection<string> builtTools,
        IReadOnlyCollection<ToolRailPage> builtCommandPages)
    {
        ArgumentNullException.ThrowIfNull(builtTools);
        ArgumentNullException.ThrowIfNull(builtCommandPages);
        if (!RailToolOrder.SequenceEqual(builtTools, StringComparer.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                "The Edit Mesh rail's tool buttons do not match the contract's tool inventory.");
        }
        if (!RailCommandPageOrder.SequenceEqual(builtCommandPages))
        {
            throw new InvalidOperationException(
                "The Edit Mesh rail's command-page buttons do not match the contract's page inventory.");
        }
    }

    public static int MorphColumnsForLogicalWidth(int logicalWidth)
    {
        return logicalWidth >= 1500 ? 4 : logicalWidth >= 900 ? 2 : 1;
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
