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
