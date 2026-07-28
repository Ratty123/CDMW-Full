using System.Globalization;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private sealed class PendingMutationRequest
    {
        public required string EventName { get; init; }
        public required string SessionId { get; init; }
        public required long RequestId { get; init; }
        public required long BaseRevision { get; init; }
        public required long ProcessGeneration { get; init; }
        public string Command { get; init; } = string.Empty;
        public string Phase { get; init; } = string.Empty;
        public bool SelectionApplied { get; set; }
        public bool CommandAccepted { get; set; }
    }

    private readonly Dictionary<long, PendingMutationRequest> _pendingMutationRequests = new();

    private void RegisterOutgoingMutation(
        string eventName,
        IReadOnlyDictionary<string, object?> envelope)
    {
        var normalizedEvent = eventName.Trim().ToLowerInvariant();
        var requestId = DictionaryLong(envelope, "request_id");
        if (requestId <= 0)
        {
            return;
        }
        var pending = new PendingMutationRequest
        {
            EventName = normalizedEvent,
            SessionId = Convert.ToString(envelope.GetValueOrDefault("session_id"), CultureInfo.InvariantCulture) ?? string.Empty,
            RequestId = requestId,
            BaseRevision = Math.Max(0, DictionaryLong(envelope, "base_revision")),
            ProcessGeneration = Math.Max(0, DictionaryLong(envelope, "process_generation")),
            Command = Convert.ToString(envelope.GetValueOrDefault("command"), CultureInfo.InvariantCulture)?.Trim().ToLowerInvariant() ?? string.Empty,
            Phase = Convert.ToString(envelope.GetValueOrDefault("phase"), CultureInfo.InvariantCulture)?.Trim().ToLowerInvariant() ?? string.Empty,
        };
        _pendingMutationRequests[requestId] = pending;
        if (IsProvisionalSelectionRequest(normalizedEvent))
        {
            _viewport.BeginProvisionalSelection(requestId, pending.BaseRevision);
        }
        else if (normalizedEvent == "placement_transform_request")
        {
            _scene.TrackProvisionalPlacementRequest(requestId);
        }
        PrunePendingMutationRequests();
    }

    private void HandleCommandResult(JsonElement root)
    {
        if (!TryMatchPendingMutation(root, out var pending, out _))
        {
            _statusLabel.Text = "Ignored stale or uncorrelated command result.";
            return;
        }
        var status = JsonString(root, "status").Trim().ToLowerInvariant();
        var accepted = IsAcceptedMutationStatus(status);
        if (!accepted)
        {
            var restored = false;
            if (IsProvisionalSelectionRequest(pending.EventName)
                && _viewport.RejectProvisionalSelection(pending.RequestId))
            {
                SyncSubmeshListSelection();
                restored = true;
            }
            if (pending.EventName == "placement_transform_request"
                && _scene.RejectProvisionalPlacement(pending.RequestId))
            {
                _viewport.ApplySceneState();
                restored = true;
            }
            CompleteMorphCommandResult(pending, accepted: false);
            _pendingMutationRequests.Remove(pending.RequestId);
            _statusLabel.Text = restored
                ? $"Command result: {status}. Restored last acknowledged state."
                : $"Ignored stale {status} result; a newer provisional request is active.";
            return;
        }

        pending.CommandAccepted = true;
        CompleteMorphCommandResult(pending, accepted: true);
        if (status == "coalesced"
            || pending.EventName == "placement_transform_request"
            || !MutationMayReturnSelection(pending)
            || pending.SelectionApplied)
        {
            _pendingMutationRequests.Remove(pending.RequestId);
        }
        _statusLabel.Text = $"Command result: {status}.";
    }

    private bool TryPrepareCorrelatedSelectionUpdate(
        JsonElement root,
        out PendingMutationRequest pending,
        out long revision)
    {
        if (!TryMatchPendingMutation(root, out pending, out revision)
            || !MutationMayReturnSelection(pending)
            || revision < _viewport.AcknowledgedSelectionRevision)
        {
            pending = null!;
            return false;
        }
        return true;
    }

    private void CompleteCorrelatedSelectionUpdate(PendingMutationRequest pending)
    {
        pending.SelectionApplied = true;
        if (pending.CommandAccepted)
        {
            _pendingMutationRequests.Remove(pending.RequestId);
        }
    }

    private void CompleteAuthoritativeSceneState()
    {
        if (!_scene.AcceptAuthoritativePlacementFrame())
        {
            return;
        }
        foreach (var requestId in _pendingMutationRequests
            .Where(pair => pair.Value.EventName == "placement_transform_request")
            .Select(pair => pair.Key)
            .ToArray())
        {
            _pendingMutationRequests.Remove(requestId);
        }
    }

    private void CompleteAuthoritativeResidentResync()
    {
        _pendingMutationRequests.Clear();
        _viewport.ResetSelectionAuthority();
        _scene.ForceAcceptAuthoritativePlacementFrame();
    }

    private void ResetPendingMutationAuthority()
    {
        _pendingMutationRequests.Clear();
        _viewport.ResetSelectionAuthority();
        _scene.ResetProvisionalPlacement();
        ResetMorphStateAuthority();
    }

    private bool TryMatchPendingMutation(
        JsonElement root,
        out PendingMutationRequest pending,
        out long revision)
    {
        pending = null!;
        revision = 0;
        var requestId = JsonLongValue(root, "request_id");
        if (requestId <= 0 || !_pendingMutationRequests.TryGetValue(requestId, out var candidate))
        {
            return false;
        }
        var sessionId = JsonString(root, "session_id").Trim();
        var processGeneration = JsonLongValue(root, "process_generation");
        if (!string.Equals(sessionId, candidate.SessionId, StringComparison.Ordinal)
            || !string.Equals(sessionId, _residentMaterialSessionId, StringComparison.Ordinal)
            || processGeneration != candidate.ProcessGeneration
            || processGeneration != _residentProcessGeneration)
        {
            return false;
        }
        revision = Math.Max(
            Math.Max(0, JsonLongValue(root, "base_revision")),
            Math.Max(JsonLongValue(root, "revision"), JsonLongValue(root, "edit_revision")));
        if (revision < candidate.BaseRevision)
        {
            return false;
        }
        pending = candidate;
        return true;
    }

    private static bool IsProvisionalSelectionRequest(string eventName) =>
        eventName is "select_request" or "selection_request";

    /// <summary>
    /// Whether the host may answer this request with a correlated
    /// <c>selection_update</c>, which is what keeps the pending entry alive past
    /// the command result so the update can still be matched to it.
    /// </summary>
    /// <remarks>
    /// Only <c>command_request</c> carries a <c>command</c> field
    /// (see <c>WriteCommandRequest</c>). Selection requests and strokes are
    /// built from the pointer payload, which has none, so qualifying them by
    /// command name made every one of them answer false: an ordinary click's
    /// authoritative selection was rejected as uncorrelated and only landed on
    /// the next uncorrelated <c>session_state</c> broadcast.
    ///
    /// Strokes stay excluded on purpose. The host sets its refresh flag on any
    /// stroke result that carries vertex groups while a selection exists, so
    /// nearly every stroke event would answer true — and since a brush or
    /// transform never edits the selection, that update only ever echoes back
    /// what the viewport already has. Holding a pending entry open for each one
    /// would fill the request table at pointer-move rate and start evicting
    /// live selection requests, which are the entries that still need to roll
    /// back.
    /// </remarks>
    private static bool MutationMayReturnSelection(PendingMutationRequest pending) => pending.EventName switch
    {
        "select_request" or "selection_request" => true,
        "command_request" => pending.Command is
            "clear_selection" or "select_all" or "grow" or "shrink" or "invert" or
            "undo" or "redo" or "delete" or "duplicate" or "subdivide" or "refine_smooth",
        _ => false,
    };

    private static bool IsAcceptedMutationStatus(string status) => status switch
    {
        "applied" or "ok" or "no_change" or "coalesced" or "saved" => true,
        _ => false,
    };

    private static long DictionaryLong(IReadOnlyDictionary<string, object?> values, string key)
    {
        if (!values.TryGetValue(key, out var value) || value is null || value is bool)
        {
            return 0;
        }
        try
        {
            return Convert.ToInt64(value, CultureInfo.InvariantCulture);
        }
        catch (Exception ex) when (ex is FormatException or InvalidCastException or OverflowException)
        {
            return 0;
        }
    }

    private void PrunePendingMutationRequests()
    {
        const int maximumPendingRequests = 256;
        while (_pendingMutationRequests.Count > maximumPendingRequests)
        {
            var oldest = _pendingMutationRequests.Keys.Min();
            _pendingMutationRequests.Remove(oldest);
        }
    }
}
