namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private static class SurfaceGeometryNative
    {
        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        internal struct Rect
        {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
        }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        internal static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);
    }

    /// <summary>
    /// Sample, at one instant, the three sizes that must agree for a screen-space
    /// reading of this surface to mean anything: what WinForms believes its client
    /// area is, what Windows says the same window is, and what the swap chain last
    /// rendered at. A harness that projects through one and photographs another gets
    /// a scaled answer and no way to tell.
    /// </summary>
    private Dictionary<string, object?> SurfaceGeometryAudit(System.Windows.Forms.Control surface)
    {
        var clientWidth = Math.Max(1, surface.ClientSize.Width);
        var clientHeight = Math.Max(1, surface.ClientSize.Height);
        var presented = _d3d11Viewport?.PresentedRenderSize ?? System.Drawing.Size.Empty;
        Dictionary<string, object?> window = new() { ["available"] = false };
        if (surface.IsHandleCreated
            && SurfaceGeometryNative.GetWindowRect(surface.Handle, out var rect))
        {
            window = new Dictionary<string, object?>
            {
                ["available"] = true,
                ["screen_x"] = rect.Left,
                ["screen_y"] = rect.Top,
                ["width"] = rect.Right - rect.Left,
                ["height"] = rect.Bottom - rect.Top,
            };
        }
        var windowWidth = window["available"] is true ? (int)window["width"]! : -1;
        var windowHeight = window["available"] is true ? (int)window["height"]! : -1;
        return new Dictionary<string, object?>
        {
            ["winforms_client"] = new Dictionary<string, object?>
            {
                ["width"] = clientWidth,
                ["height"] = clientHeight,
            },
            ["os_window"] = window,
            ["presented_render_size"] = new Dictionary<string, object?>
            {
                ["width"] = presented.Width,
                ["height"] = presented.Height,
            },
            ["client_matches_os_window"] = windowWidth == clientWidth && windowHeight == clientHeight,
            ["presented_matches_client"] = presented.Width == clientWidth && presented.Height == clientHeight,
            ["presented_matches_os_window"] = presented.Width == windowWidth && presented.Height == windowHeight,
            ["resize_commit_pending"] = _d3d11Viewport?.ResizeCommitPending ?? false,
        };
    }

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
            ["geometry_audit"] = SurfaceGeometryAudit(surface),
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
