using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private void ConfigureResidentNativeInteraction(JsonElement root)
    {
        _viewport.ConfigureResidentNativeInteraction(
            JsonString(root, "session_id"),
            ProtocolEditRevision(root),
            JsonLongValue(root, "selection_revision"),
            JsonLongValue(root, "topology_generation"));
    }

    private void CompleteResidentNativeBatchAuthority(JsonElement root)
    {
        var requestId = JsonLongValue(root, "request_id");
        if (requestId <= 0)
        {
            return;
        }
        var baseRevision = JsonLongValue(root, "base_revision");
        var targetRevision = JsonLongValue(root, "target_revision");
        var selectionRevision = JsonLongValue(root, "selection_revision");
        var topologyGeneration = JsonLongValue(root, "topology_generation");
        if (!_pendingMutationRequests.TryGetValue(requestId, out var pending))
        {
            _viewport.SynchronizeResidentNativeAfterOneShot(
                targetRevision,
                selectionRevision,
                topologyGeneration);
            return;
        }
        if (pending.EventName == "resident_interaction_transaction")
        {
            _viewport.AcceptResidentInteraction(
                requestId,
                targetRevision,
                selectionRevision,
                topologyGeneration);
            _pendingMutationRequests.Remove(requestId);
            return;
        }
        if (pending.EventName != "command_request")
        {
            _viewport.SynchronizeResidentNativeAfterOneShot(
                targetRevision,
                selectionRevision,
                topologyGeneration);
            return;
        }
        if (pending.Command is "undo" or "redo")
        {
            _viewport.ApplyResidentNativeHistory(
                pending.Command,
                baseRevision,
                targetRevision,
                selectionRevision,
                topologyGeneration);
        }
        else
        {
            _viewport.SynchronizeResidentNativeAfterOneShot(
                targetRevision,
                selectionRevision,
                topologyGeneration);
        }
    }

    private void RejectResidentNativeBatchAuthority(JsonElement root, string reason)
    {
        var requestId = JsonLongValue(root, "request_id");
        if (requestId <= 0
            || !_pendingMutationRequests.TryGetValue(requestId, out var pending)
            || pending.EventName != "resident_interaction_transaction")
        {
            return;
        }
        _viewport.RejectResidentInteraction(requestId, reason);
        _pendingMutationRequests.Remove(requestId);
    }
}
