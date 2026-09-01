namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    internal Dictionary<string, object?> MorphPageActivationStabilityProof()
    {
        BuildAuthoringToolPanels();
        ActivateToolRailLayout();
        ShowToolRailPage(null);
        PerformLayout();
        var before = MorphPageActivationSnapshot();

        bool StableExceptForArmedTool(Dictionary<string, object?> current) => before
            .Where(pair => !string.Equals(pair.Key, "active_tool", StringComparison.Ordinal))
            .All(pair => current.TryGetValue(pair.Key, out var value)
                && string.Equals(
                    System.Text.Json.JsonSerializer.Serialize(pair.Value),
                    System.Text.Json.JsonSerializer.Serialize(value),
                    StringComparison.Ordinal));

        static bool SameSnapshot(
            Dictionary<string, object?> left,
            Dictionary<string, object?> right) => string.Equals(
                System.Text.Json.JsonSerializer.Serialize(left),
                System.Text.Json.JsonSerializer.Serialize(right),
                StringComparison.Ordinal);

        static bool HasLiveViewport(Dictionary<string, object?> snapshot) =>
            snapshot.GetValueOrDefault("viewport_control_live") is true;

        var activationCases = new List<Dictionary<string, object?>>();
        foreach (var tool in EditMeshLayoutContracts.RailToolOrder)
        {
            SetActiveTool(tool);
            var first = MorphPageActivationSnapshot();
            var pageGeneration = _toolRailPagePresentationGeneration;
            var expansionGeneration = _toolListExpansionGeneration;
            SetActiveTool(tool);
            var repeated = MorphPageActivationSnapshot();
            activationCases.Add(new Dictionary<string, object?>
            {
                ["name"] = tool,
                ["kind"] = "tool",
                ["stable"] = StableExceptForArmedTool(first)
                    && StableExceptForArmedTool(repeated)
                    && HasLiveViewport(first)
                    && HasLiveViewport(repeated),
                ["idempotent"] = SameSnapshot(first, repeated)
                    && _toolRailPagePresentationGeneration == pageGeneration
                    && _toolListExpansionGeneration == expansionGeneration,
            });
        }
        foreach (var page in EditMeshLayoutContracts.RailCommandPageOrder)
        {
            ShowToolRailPage(page);
            var first = MorphPageActivationSnapshot();
            var pageGeneration = _toolRailPagePresentationGeneration;
            var expansionGeneration = _toolListExpansionGeneration;
            ShowToolRailPage(page);
            var repeated = MorphPageActivationSnapshot();
            activationCases.Add(new Dictionary<string, object?>
            {
                ["name"] = page.ToString(),
                ["kind"] = "page",
                ["stable"] = StableExceptForArmedTool(first)
                    && StableExceptForArmedTool(repeated)
                    && HasLiveViewport(first)
                    && HasLiveViewport(repeated),
                ["idempotent"] = SameSnapshot(first, repeated)
                    && _toolRailPagePresentationGeneration == pageGeneration
                    && _toolListExpansionGeneration == expansionGeneration,
            });
        }

        SetActiveTool("orbit");
        ShowToolRailPage(ToolRailPage.MorphRefit);
        var after = MorphPageActivationSnapshot();
        var unchanged = before.Keys.All(key => string.Equals(
            System.Text.Json.JsonSerializer.Serialize(before[key]),
            System.Text.Json.JsonSerializer.Serialize(after[key]),
            StringComparison.Ordinal));
        return new Dictionary<string, object?>
        {
            ["ok"] = unchanged
                && activationCases.All(item => item.GetValueOrDefault("stable") is true)
                && activationCases.All(item => item.GetValueOrDefault("idempotent") is true)
                && HasLiveViewport(before)
                && HasLiveViewport(after)
                && _selectedToolRailPage == ToolRailPage.MorphRefit
                && _toolRailPages.GetValueOrDefault(ToolRailPage.MorphRefit)?.Parent is not null,
            ["redraw_scope"] = "tool_column",
            ["activation_cases"] = activationCases,
            ["before"] = before,
            ["after"] = after,
        };
    }

    private Dictionary<string, object?> MorphPageActivationSnapshot()
    {
        var renderer = _viewport.RendererStatusPayload();
        var viewport = (Dictionary<string, object?>)renderer["viewport"]!;
        var presentation = (Dictionary<string, object?>)renderer["presentation"]!;
        var resources = (Dictionary<string, object?>)renderer["geometry_resources"]!;
        var surfaceHwnd = new IntPtr(Convert.ToInt64(viewport.GetValueOrDefault("hwnd") ?? 0L));
        var surfaceParent = surfaceHwnd == IntPtr.Zero
            ? IntPtr.Zero
            : ToolRailNative.GetParent(surfaceHwnd);
        ToolRailNative.Rect surfaceRect = default;
        var surfaceRectAvailable = surfaceHwnd != IntPtr.Zero
            && ToolRailNative.GetWindowRect(surfaceHwnd, out surfaceRect);
        var surfaceWidth = surfaceRectAvailable ? surfaceRect.Right - surfaceRect.Left : 0;
        var surfaceHeight = surfaceRectAvailable ? surfaceRect.Bottom - surfaceRect.Top : 0;
        var surfaceOwnVisible = surfaceHwnd != IntPtr.Zero
            && (ToolRailNative.GetWindowLong(surfaceHwnd, ToolRailNative.GwlStyle)
                & ToolRailNative.WsVisible) != 0;
        var renderSurfaceIdentity = Convert.ToInt64(
            resources.GetValueOrDefault("render_surface_identity") ?? 0L);
        // The standalone smoke intentionally never maps its top-level form, so
        // GetWindowRect for a descendant can remain zero even though the real
        // D3D child has been created with WS_VISIBLE and owns a sized render
        // surface. Use raw (unclamped) WinForms bounds plus the native child,
        // parent and render-surface identity; visible packaged-app proof checks
        // the mapped OS rectangle separately.
        var viewportControlLive = surfaceHwnd != IntPtr.Zero
            && ToolRailNative.IsWindow(surfaceHwnd)
            && surfaceParent != IntPtr.Zero
            && ToolRailNative.IsWindow(surfaceParent)
            && OwnVisibleState(_viewport)
            && surfaceOwnVisible
            && _viewport.ClientSize.Width > 0
            && _viewport.ClientSize.Height > 0
            && renderSurfaceIdentity != 0;
        return new Dictionary<string, object?>
        {
            ["source_parse_count"] = _sourceParseCount,
            ["geometry_upload_count"] = _viewport.GeometryUploadCount,
            ["device_reset_count"] = _viewport.DeviceResetCount,
            ["device_reset_attempt_count"] = _viewport.DeviceResetAttemptCount,
            ["device_identity"] = resources.GetValueOrDefault("device_identity"),
            ["geometry_buffer_identity"] = resources.GetValueOrDefault("geometry_buffer_identity"),
            ["render_surface_identity"] = renderSurfaceIdentity,
            ["render_surface_create_count"] = resources.GetValueOrDefault("render_surface_create_count"),
            ["render_surface_dispose_count"] = resources.GetValueOrDefault("render_surface_dispose_count"),
            ["swap_chain_resize_commit_count"] = resources.GetValueOrDefault("swap_chain_resize_commit_count"),
            ["full_geometry_rebuilds"] = resources.GetValueOrDefault("full_geometry_rebuilds"),
            ["helper_pid"] = Environment.ProcessId,
            ["viewport_hwnd"] = surfaceHwnd.ToInt64(),
            ["viewport_parent_hwnd"] = surfaceParent.ToInt64(),
            ["viewport_own_visible"] = OwnVisibleState(_viewport),
            ["viewport_native_visible"] = surfaceOwnVisible,
            ["viewport_client_width"] = _viewport.ClientSize.Width,
            ["viewport_client_height"] = _viewport.ClientSize.Height,
            ["viewport_native_width"] = surfaceWidth,
            ["viewport_native_height"] = surfaceHeight,
            ["viewport_control_live"] = viewportControlLive,
            ["viewport_bounds"] = _viewportWorkspaceSplit?.Bounds.ToString(),
            ["controls_splitter_distance"] = _rightToolSplit?.SplitterDistance,
            ["form_hwnd"] = viewport.GetValueOrDefault("form_hwnd"),
            ["active_tool"] = _viewport.ActiveTool,
            ["presentation_generation"] = presentation.GetValueOrDefault("presentation_generation"),
            ["presentation_fingerprint"] = presentation.GetValueOrDefault("presentation_fingerprint"),
            ["active_camera_context"] = presentation.GetValueOrDefault("active_camera_context"),
            ["view_contexts"] = presentation.GetValueOrDefault("view_contexts"),
        };
    }

    /// <summary>
    /// Show or hide one rail page without taking the whole helper down with it.
    /// </summary>
    /// <remarks>
    /// Revealing a page for the first time makes WinForms create its handle and
    /// then re-parent every already-realised child onto it. Embedded under the
    /// host window, that SetParent has been seen to fail with ERROR_INVALID_STATE
    /// (5023). An exception escaping here reaches the UI guard, which exits the
    /// process, so a rail click reads as the whole tool crashing. Report the
    /// window state the failure needs instead and leave the rail usable.
    /// </remarks>
    private bool RevealToolRailPage(Panel page, bool visible)
    {
        try
        {
            page.TabStop = visible;
            _ = ToolRailNative.EnableWindow(page.Handle, visible);
            _ = ToolRailNative.ShowWindow(
                page.Handle,
                visible ? ToolRailNative.SwShowNoActivate : ToolRailNative.SwHide);
            return true;
        }
        catch (System.ComponentModel.Win32Exception ex)
        {
            WriteProtocolEvent("tool_rail_page_reveal_failed", new Dictionary<string, object?>
            {
                ["page"] = page.Name,
                ["requested_visible"] = visible,
                ["native_error"] = ex.NativeErrorCode,
                ["message"] = ex.Message,
                ["embedded_parent_hwnd"] = _options.ParentHwnd,
                ["page_handle_created"] = page.IsHandleCreated,
                ["page_hwnd"] = page.IsHandleCreated ? page.Handle.ToInt64() : 0L,
                ["page_parent_hwnd"] = ToolRailWindowParent(page),
                ["scroll_handle_created"] = page.Parent?.IsHandleCreated ?? false,
                ["form_handle_created"] = IsHandleCreated,
                ["form_parent_hwnd"] = ToolRailWindowParent(this),
                ["children"] = ToolRailChildDiagnostics(page),
            });
            _statusLabel.Text =
                $"The {ToolListPageDisplayName(page, _selectedToolRailPage)} panel could not be shown "
                + $"(Win32 {ex.NativeErrorCode}). The rail stays on the previous tool.";
            return false;
        }
    }

    private static long ToolRailWindowParent(Control control)
    {
        return control.IsHandleCreated
            ? ToolRailNative.GetParent(control.Handle).ToInt64()
            : 0L;
    }

    /// <summary>
    /// The per-child window state that says why the deferred re-parent failed:
    /// which children were already realised, who owns them now, and whether that
    /// owner is still a window.
    /// </summary>
    private static List<Dictionary<string, object?>> ToolRailChildDiagnostics(Control page)
    {
        var rows = new List<Dictionary<string, object?>>();
        foreach (Control child in page.Controls)
        {
            var handle = child.IsHandleCreated ? child.Handle : IntPtr.Zero;
            var parent = handle == IntPtr.Zero ? IntPtr.Zero : ToolRailNative.GetParent(handle);
            rows.Add(new Dictionary<string, object?>
            {
                ["name"] = child.Name,
                ["type"] = child.GetType().Name,
                ["visible"] = child.Visible,
                ["handle_created"] = child.IsHandleCreated,
                ["hwnd"] = handle.ToInt64(),
                ["current_parent_hwnd"] = parent.ToInt64(),
                ["current_parent_is_window"] = parent != IntPtr.Zero && ToolRailNative.IsWindow(parent),
                ["disposed"] = child.IsDisposed,
            });
        }
        return rows;
    }

    private static class ToolRailNative
    {
        internal const int GwlStyle = -16;
        internal const int WsVisible = 0x10000000;
        internal const int SwHide = 0;
        internal const int SwShowNoActivate = 4;

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        internal struct Rect
        {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
        }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        internal static extern IntPtr GetParent(IntPtr hwnd);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        internal static extern bool IsWindow(IntPtr hwnd);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        internal static extern bool EnableWindow(IntPtr hwnd, bool enable);

        [System.Runtime.InteropServices.DllImport("user32.dll", EntryPoint = "GetWindowLongW")]
        internal static extern int GetWindowLong(IntPtr hwnd, int index);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        internal static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        internal static extern bool ShowWindow(IntPtr hwnd, int command);
    }
}
