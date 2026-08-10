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

        ShowToolRailPage(ToolRailPage.MorphRefit);
        PerformLayout();
        var after = MorphPageActivationSnapshot();
        var unchanged = before.Keys.All(key => string.Equals(
            System.Text.Json.JsonSerializer.Serialize(before[key]),
            System.Text.Json.JsonSerializer.Serialize(after[key]),
            StringComparison.Ordinal));
        return new Dictionary<string, object?>
        {
            ["ok"] = unchanged
                && _selectedToolRailPage == ToolRailPage.MorphRefit
                && _toolRailPages.GetValueOrDefault(ToolRailPage.MorphRefit)?.Parent is not null,
            ["redraw_scope"] = "tool_column",
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
        return new Dictionary<string, object?>
        {
            ["source_parse_count"] = _sourceParseCount,
            ["geometry_upload_count"] = _viewport.GeometryUploadCount,
            ["device_reset_count"] = _viewport.DeviceResetCount,
            ["device_reset_attempt_count"] = _viewport.DeviceResetAttemptCount,
            ["device_identity"] = resources.GetValueOrDefault("device_identity"),
            ["geometry_buffer_identity"] = resources.GetValueOrDefault("geometry_buffer_identity"),
            ["render_surface_identity"] = resources.GetValueOrDefault("render_surface_identity"),
            ["full_geometry_rebuilds"] = resources.GetValueOrDefault("full_geometry_rebuilds"),
            ["helper_pid"] = Environment.ProcessId,
            ["viewport_hwnd"] = viewport.GetValueOrDefault("hwnd"),
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
    private void RevealToolRailPage(Panel page, bool visible)
    {
        try
        {
            page.Visible = visible;
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
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        internal static extern IntPtr GetParent(IntPtr hwnd);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        internal static extern bool IsWindow(IntPtr hwnd);
    }
}
