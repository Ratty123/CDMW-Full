namespace Cdmw.MeshEditorExperiment;

internal static class EditMeshLayoutContracts
{
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

    public static int DefaultToolDeckHeight(int clientLogicalHeight)
    {
        return Math.Clamp(
            (int)Math.Round(Math.Max(1, clientLogicalHeight) * 0.30),
            280,
            420);
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
