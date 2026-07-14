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
        var fullBounds = new System.Drawing.Rectangle(
            0,
            0,
            Math.Max(1, surface.ClientSize.Width),
            Math.Max(1, surface.ClientSize.Height));
        var panes = HasSimultaneousRolePanes
            ? RolePaneBounds()
            : (fullBounds, fullBounds);
        Dictionary<string, object?> SurfaceRectangle(System.Drawing.Rectangle rectangle) => new()
        {
            ["hwnd"] = surface.Handle.ToInt64(),
            ["client_x"] = rectangle.X,
            ["client_y"] = rectangle.Y,
            ["screen_x"] = origin.X + rectangle.X,
            ["screen_y"] = origin.Y + rectangle.Y,
            ["width"] = Math.Max(1, rectangle.Width),
            ["height"] = Math.Max(1, rectangle.Height),
            ["visible"] = surface.Visible,
        };
        var editable = HasSimultaneousRolePanes ? panes.Item2 : fullBounds;
        return new Dictionary<string, object?>
        {
            ["hwnd"] = surface.Handle.ToInt64(),
            ["form_hwnd"] = form?.Handle.ToInt64() ?? 0L,
            // Compatibility: input/projection payloads are editable-pane-local,
            // so the legacy viewport rectangle must identify that same pane.
            ["screen_x"] = origin.X + editable.X,
            ["screen_y"] = origin.Y + editable.Y,
            ["client_x"] = editable.X,
            ["client_y"] = editable.Y,
            ["width"] = Math.Max(1, editable.Width),
            ["height"] = Math.Max(1, editable.Height),
            ["form_screen_x"] = formOrigin.X,
            ["form_screen_y"] = formOrigin.Y,
            ["form_width"] = Math.Max(1, form?.ClientSize.Width ?? 0),
            ["form_height"] = Math.Max(1, form?.ClientSize.Height ?? 0),
            ["visible"] = surface.Visible,
            ["full_surface"] = SurfaceRectangle(fullBounds),
            ["viewports"] = new Dictionary<string, object?>
            {
                ["reference"] = SurfaceRectangle(panes.Item1),
                ["editable"] = SurfaceRectangle(panes.Item2),
            },
        };
    }
}
