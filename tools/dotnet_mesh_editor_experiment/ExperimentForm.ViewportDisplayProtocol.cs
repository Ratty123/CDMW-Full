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
        if (!_viewport.TrySetDisplayMode(mode, out var error))
        {
            WriteViewportDisplayResult(root, "viewport_display_failed", sessionId, mode, "invalid_mode", error);
            return;
        }
        SyncPreviewModeSelection(_viewport.DisplayMode);
        _statusLabel.Text = JsonBoolean(root, "texture_request_pending")
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
            ["renderer"] = RendererCompactStatusWithLifecycle(),
            ["capabilities"] = new[] { ViewportDisplayModesCapability },
        };
        CopyMutationEnvelope(request, payload);
        WriteProtocolEvent(eventName, payload);
    }
}
