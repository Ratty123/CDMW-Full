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
            WriteViewportDisplayResult("viewport_display_failed", sessionId, mode, "session_mismatch", sessionError);
            return;
        }
        if (!_viewport.TrySetDisplayMode(mode, out var error))
        {
            WriteViewportDisplayResult("viewport_display_failed", sessionId, mode, "invalid_mode", error);
            return;
        }
        _statusLabel.Text = $"Viewport display: {_viewport.DisplayMode}.";
        WriteViewportDisplayResult("viewport_display_applied", sessionId, _viewport.DisplayMode, string.Empty, string.Empty);
    }

    private void WriteViewportDisplayResult(
        string eventName,
        string sessionId,
        string mode,
        string reason,
        string message)
    {
        WriteProtocolEvent(eventName, new Dictionary<string, object?>
        {
            ["session_id"] = sessionId,
            ["mode"] = mode,
            ["reason"] = reason,
            ["message"] = message,
            ["show_solid"] = _viewport.ShowSolid,
            ["show_wire"] = _viewport.ShowWire,
            ["show_vertices"] = _viewport.ShowVertices,
            ["textures_enabled"] = _viewport.TexturesEnabled,
            ["renderer"] = RendererCompactStatusWithLifecycle(),
            ["capabilities"] = new[] { ViewportDisplayModesCapability },
        });
    }
}
