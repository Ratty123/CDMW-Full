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

    private void HandleResidentInteractionCommitAck(JsonElement root)
    {
        var requestId = JsonLongValue(root, "request_id");
        if (requestId <= 0
            || !_pendingMutationRequests.TryGetValue(requestId, out var pending)
            || pending.EventName != "resident_interaction_transaction"
            || !string.Equals(pending.SessionId, JsonString(root, "session_id"), StringComparison.Ordinal)
            || pending.ProcessGeneration != JsonLongValue(root, "process_generation")
            || pending.HelperProcessId != JsonLongValue(root, "helper_process_id")
            || pending.HelperProcessId != Environment.ProcessId
            || pending.GestureId != checked((ulong)Math.Max(0, JsonLongValue(root, "gesture_id")))
            || pending.TransactionSequence != checked((ulong)Math.Max(0, JsonLongValue(root, "transaction_sequence")))
            || !string.Equals(
                pending.TransactionDigest,
                JsonString(root, "sha256").Trim(),
                StringComparison.OrdinalIgnoreCase))
        {
            _statusLabel.Text = "Ignored stale or uncorrelated resident interaction acknowledgement.";
            return;
        }
        var status = JsonString(root, "status").Trim().ToLowerInvariant();
        var durableRevision = Math.Max(0, JsonLongValue(root, "durable_revision"));
        var durableSelectionRevision = Math.Max(
            0,
            JsonLongValue(root, "durable_selection_revision"));
        var durableTopology = Math.Max(
            0,
            JsonLongValue(root, "durable_topology_generation"));
        if (status == "applied")
        {
            if (!_viewport.AcknowledgeResidentInteractionCommit(
                    requestId,
                    pending.TransactionSequence,
                    pending.TransactionDigest,
                    durableRevision,
                    durableSelectionRevision,
                    durableTopology))
            {
                _statusLabel.Text = "Rejected an out-of-order resident interaction acknowledgement.";
                return;
            }
            _lastDurableEditRevision = durableRevision;
            _lastObservedSessionRevision = Math.Max(_lastObservedSessionRevision, durableRevision);
            ApplyHistoryState(root);
            _pendingMutationRequests.Remove(requestId);
            _statusLabel.Text = _viewport.ResidentNativeReplicationPending
                ? "Syncing edits…"
                : "Mesh edits synchronized.";
        }
        else
        {
            var reason = JsonStringArray(root, "diagnostics").FirstOrDefault()?.Trim();
            _viewport.RejectResidentInteraction(
                requestId,
                string.IsNullOrWhiteSpace(reason) ? status : reason);
            _lastAppliedEditRevision = durableRevision;
            _lastDurableEditRevision = durableRevision;
            _lastObservedSessionRevision = durableRevision;
            _authoritativeRevisionInitialized = true;
            _viewport.SetAuthoritativeEditRevision(durableRevision);
            ApplyHistoryState(root);
            _pendingMutationRequests.Remove(requestId);
        }
        ApplyOutputPolicyControls();
    }
}
