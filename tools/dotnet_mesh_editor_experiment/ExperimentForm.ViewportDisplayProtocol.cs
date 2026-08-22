using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private void HandleViewportDisplayUpdate(JsonElement root)
    {
        var sessionId = JsonString(root, "session_id").Trim();
        var mode = JsonString(root, "mode").Trim().ToLowerInvariant();
        if (!AcceptMaterialSession(sessionId, out var sessionError))
        {
            WriteViewportDisplayResult(root, "viewport_display_failed", sessionId, mode, "session_mismatch", sessionError);
            return;
        }
        // Synchronized, like the helper's own Preview mode combo: a bare
        // TrySetDisplayMode writes the new mode into the active pane's context
        // only, so a host-driven change left every other pane rendering the mode
        // it had before. The tool rail drives this route, which is why Edit Mesh
        // and the Builder combo disagreed about what the viewport was showing.
        if (!_viewport.TrySetSynchronizedDisplayMode(mode, out var error))
        {
            WriteViewportDisplayResult(root, "viewport_display_failed", sessionId, mode, "invalid_mode", error);
            return;
        }
        _viewport.MarkHostDisplayModeAuthoritative();
        var textureRequestPending = JsonBoolean(root, "texture_request_pending");
        // Already localized by the host: why a requested textured view stayed
        // on the fallback. Without it this label's last words were the pending
        // "Loading textures..." line, and the snapped-back selector read as a
        // dead control.
        var failureText = JsonBoolean(root, "texture_request_failed")
            ? JsonString(root, "failure_text").Trim()
            : string.Empty;
        SyncPreviewModeSelection(_viewport.DisplayMode);
        _statusLabel.Text = failureText.Length > 0
            ? failureText
            : textureRequestPending
                ? "Loading textures in the resident viewport..."
                : $"Viewport display: {_viewport.DisplayMode}.";
        WriteViewportDisplayResult(root, "viewport_display_applied", sessionId, _viewport.DisplayMode, string.Empty, string.Empty);
    }

    private void WriteViewportDisplayResult(
        JsonElement request,
        string eventName,
        string sessionId,
        string mode,
        string reason,
        string message)
    {
        var payload = new Dictionary<string, object?>
        {
            ["session_id"] = sessionId,
            ["mode"] = mode,
            ["reason"] = reason,
            ["message"] = message,
            ["show_solid"] = _viewport.ShowSolid,
            ["show_wire"] = _viewport.ShowWire,
            ["show_vertices"] = _viewport.ShowVertices,
            ["show_xray"] = _viewport.ShowXRay,
            ["textures_enabled"] = _viewport.TexturesEnabled,
            // A display-mode change is a rare, user-initiated state change, not
            // a per-frame event, so the compact payload's per-frame cost saving
            // does not apply. The full status is what carries texture resource
            // and decode counters, without which a host cannot tell whether
            // switching modes reused resident textures or re-decoded them.
            ["renderer"] = RendererStatusWithLifecycle(),
            ["capabilities"] = new[] { ViewportDisplayModesCapability },
        };
        CopyMutationEnvelope(request, payload);
        WriteProtocolEvent(eventName, payload);
    }
}
