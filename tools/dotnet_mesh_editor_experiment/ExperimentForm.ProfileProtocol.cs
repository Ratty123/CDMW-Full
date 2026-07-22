using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private static bool IsPreviewProfileMutation(string eventName) =>
        (eventName ?? string.Empty).Trim().ToLowerInvariant() is
            "session_state"
            or "tool_state"
            or "selection_update"
            or "preview_vertex_update"
            or "preview_triangle_update"
            or "resident_state_resync"
            or "morph_state_update"
            or "command_result";

    private static Dictionary<string, object?> PreviewProfileMutationRejectionPayload(
        JsonElement root,
        string eventName)
    {
        var payload = new Dictionary<string, object?>
        {
            ["status"] = "rejected",
            ["reason"] = "preview_profile_read_only",
            ["profile"] = "preview",
            ["requested_event"] = eventName,
        };
        foreach (var name in new[]
        {
            "request_id",
            "generation",
            "process_generation",
            "revision",
            "edit_revision",
            "session_id",
        })
        {
            if (!root.TryGetProperty(name, out var value))
            {
                continue;
            }
            payload[name] = value.ValueKind switch
            {
                JsonValueKind.String => value.GetString(),
                JsonValueKind.Number when value.TryGetInt64(out var number) => number,
                _ => value.GetRawText(),
            };
        }
        return payload;
    }

    private void PublishPreviewProfileMutationRejection(JsonElement root, string eventName)
    {
        WriteProtocolEvent(
            "protocol_command_rejected",
            PreviewProfileMutationRejectionPayload(root, eventName));
    }

    private void PublishPreviewProfileMutationRejectionThreadSafe(JsonElement root, string eventName)
    {
        WritePreparedProtocolEventThreadSafe(
            "protocol_command_rejected",
            PreviewProfileMutationRejectionPayload(root, eventName));
    }
}
