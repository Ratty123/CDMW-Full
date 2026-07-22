using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private void HandleOverlayStateUpdate(JsonElement root)
    {
        var sessionId = JsonString(root, "session_id").Trim();
        var requestId = JsonLongValue(root, "request_id");
        var processGeneration = JsonLongValue(root, "process_generation");
        var applied = false;
        var reason = string.Empty;
        if (requestId <= 0)
        {
            reason = "missing_request_id";
        }
        else if (processGeneration <= 0 || processGeneration != _residentProcessGeneration)
        {
            reason = "stale_process_generation";
        }
        else if (!AcceptMaterialSession(sessionId, out var sessionError))
        {
            reason = string.IsNullOrWhiteSpace(sessionError) ? "stale_session" : sessionError;
        }
        else
        {
            applied = _viewport.TryApplyPreviewOverlayState(root, out reason);
        }
        var payload = new Dictionary<string, object?>
        {
            ["status"] = applied ? "applied" : "rejected",
            ["reason"] = applied ? string.Empty : reason,
            ["overlay_state"] = _scene.PreviewOverlays.StatusPayload(),
            ["renderer"] = RendererCompactStatusWithLifecycle(),
            ["capabilities"] = new[]
            {
                "overlay_state_update_v1",
                "skeleton_overlay_v1",
                "pbd_cloth_overlay_v1",
            },
        };
        CopyMutationEnvelope(root, payload);
        WriteProtocolEvent("overlay_state_update_ack", payload);
    }
}

internal sealed partial class MeshViewport
{
    public bool TryApplyPreviewOverlayState(JsonElement root, out string reason)
    {
        if (!_scene.PreviewOverlays.ApplyControlUpdate(root, out reason))
        {
            return false;
        }
        _d3d11Viewport?.ResetPreviewOverlaySimulationIfRequested();
        RequestFrame();
        UpdateGpuViewport();
        Invalidate();
        return true;
    }
}
