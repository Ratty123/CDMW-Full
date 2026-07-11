namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private Dictionary<string, object?> RenderSurfaceStatusPayload()
    {
        System.Windows.Forms.Control surface =
            (System.Windows.Forms.Control?)_d3d11Viewport
            ?? (System.Windows.Forms.Control?)_gpuHost
            ?? this;
        var form = FindForm();
        if (!surface.IsHandleCreated)
        {
            return new Dictionary<string, object?> { ["hwnd"] = 0L, ["form_hwnd"] = 0L };
        }
        var origin = surface.PointToScreen(System.Drawing.Point.Empty);
        var formOrigin = form?.PointToScreen(System.Drawing.Point.Empty) ?? origin;
        return new Dictionary<string, object?>
        {
            ["hwnd"] = surface.Handle.ToInt64(),
            ["form_hwnd"] = form?.Handle.ToInt64() ?? 0L,
            ["screen_x"] = origin.X,
            ["screen_y"] = origin.Y,
            ["width"] = Math.Max(1, surface.ClientSize.Width),
            ["height"] = Math.Max(1, surface.ClientSize.Height),
            ["form_screen_x"] = formOrigin.X,
            ["form_screen_y"] = formOrigin.Y,
            ["form_width"] = Math.Max(1, form?.ClientSize.Width ?? 0),
            ["form_height"] = Math.Max(1, form?.ClientSize.Height ?? 0),
            ["visible"] = surface.Visible,
        };
    }
}
