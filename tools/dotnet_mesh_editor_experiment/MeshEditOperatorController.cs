namespace Cdmw.MeshEditorExperiment;

internal enum MeshEditOperatorState
{
    Idle,
    Armed,
    Preparing,
    Running,
    Confirming,
    AwaitingCommit,
    AwaitingRenderer,
    Recovering,
    Failed,
}

internal enum MeshEditOperatorTerminalState
{
    None,
    Finished,
    Cancelled,
    Rejected,
    Failed,
}

internal sealed record MeshEditOperatorSnapshot(
    string Kind,
    string Tool,
    string Mode,
    string SelectionDomain,
    string GestureId,
    long SnapshotGeneration,
    long BaseGeometryRevision,
    long BaseSelectionRevision,
    long TopologyGeneration);

/// <summary>
/// One modal edit gesture and its legal lifecycle. It owns coordination only;
/// native MeshEditSession owns committed geometry, selection, and history.
/// </summary>
internal sealed class MeshEditOperatorController : IDisposable
{
    private CancellationTokenSource? _cancellation;

    public MeshEditOperatorState State { get; private set; } = MeshEditOperatorState.Idle;
    public MeshEditOperatorTerminalState LastTerminalState { get; private set; }
        = MeshEditOperatorTerminalState.None;
    public MeshEditOperatorSnapshot? Active { get; private set; }
    public string LastFailureCode { get; private set; } = string.Empty;
    public string LastFailureMessage { get; private set; } = string.Empty;
    public CancellationToken CancellationToken =>
        _cancellation?.Token ?? CancellationToken.None;

    public bool CanStart(out string reason)
    {
        reason = State == MeshEditOperatorState.Idle
            ? string.Empty
            : $"active_operator_conflict:{Active?.Kind ?? State.ToString().ToLowerInvariant()}";
        return State == MeshEditOperatorState.Idle;
    }

    public bool Begin(MeshEditOperatorSnapshot snapshot, out string reason)
    {
        if (!CanStart(out reason))
        {
            return false;
        }
        if (string.IsNullOrWhiteSpace(snapshot.GestureId)
            || string.IsNullOrWhiteSpace(snapshot.Kind)
            || snapshot.BaseGeometryRevision < 0
            || snapshot.BaseSelectionRevision < 0
            || snapshot.TopologyGeneration < 0)
        {
            reason = "invalid_operator_snapshot";
            return false;
        }
        _cancellation?.Dispose();
        _cancellation = new CancellationTokenSource();
        Active = snapshot;
        LastTerminalState = MeshEditOperatorTerminalState.None;
        LastFailureCode = string.Empty;
        LastFailureMessage = string.Empty;
        State = MeshEditOperatorState.Armed;
        State = MeshEditOperatorState.Preparing;
        State = MeshEditOperatorState.Running;
        return true;
    }

    public bool Update(string gestureId) =>
        State == MeshEditOperatorState.Running && IdentityMatches(gestureId);

    public bool Confirm(string gestureId)
    {
        if (State != MeshEditOperatorState.Running || !IdentityMatches(gestureId))
        {
            return false;
        }
        State = MeshEditOperatorState.Confirming;
        State = MeshEditOperatorState.AwaitingCommit;
        return true;
    }

    public bool ApplyAuthoritativeResult(string gestureId)
    {
        if (State != MeshEditOperatorState.AwaitingCommit || !IdentityMatches(gestureId))
        {
            return false;
        }
        State = MeshEditOperatorState.AwaitingRenderer;
        return true;
    }

    public bool CompleteRenderer(string gestureId)
    {
        if (State != MeshEditOperatorState.AwaitingRenderer || !IdentityMatches(gestureId))
        {
            return false;
        }
        Settle(MeshEditOperatorTerminalState.Finished);
        return true;
    }

    public bool RollbackProvisionalState(string gestureId, Action rollback)
    {
        if (State == MeshEditOperatorState.Idle || !IdentityMatches(gestureId))
        {
            return false;
        }
        rollback();
        return true;
    }

    public bool Cancel(string gestureId, Action? rollback = null)
    {
        if (State == MeshEditOperatorState.Idle || !IdentityMatches(gestureId))
        {
            return false;
        }
        _cancellation?.Cancel();
        rollback?.Invoke();
        Settle(MeshEditOperatorTerminalState.Cancelled);
        return true;
    }

    public bool Reject(string gestureId, string code, string message)
    {
        if (State == MeshEditOperatorState.Idle || !IdentityMatches(gestureId))
        {
            return false;
        }
        LastFailureCode = string.IsNullOrWhiteSpace(code) ? "operator_rejected" : code;
        LastFailureMessage = message ?? string.Empty;
        Settle(MeshEditOperatorTerminalState.Rejected, preserveFailure: true);
        return true;
    }

    public void Fail(string code, string message)
    {
        _cancellation?.Cancel();
        LastFailureCode = string.IsNullOrWhiteSpace(code) ? "operator_failed" : code;
        LastFailureMessage = message ?? string.Empty;
        LastTerminalState = MeshEditOperatorTerminalState.Failed;
        State = MeshEditOperatorState.Failed;
    }

    public bool RecoverToIdle()
    {
        if (State != MeshEditOperatorState.Failed)
        {
            return false;
        }
        State = MeshEditOperatorState.Recovering;
        ClearActive();
        State = MeshEditOperatorState.Idle;
        return true;
    }

    public Dictionary<string, object?> Diagnostics() => new()
    {
        ["state"] = State.ToString().ToLowerInvariant(),
        ["terminal_state"] = LastTerminalState.ToString().ToLowerInvariant(),
        ["kind"] = Active?.Kind ?? string.Empty,
        ["tool"] = Active?.Tool ?? string.Empty,
        ["mode"] = Active?.Mode ?? string.Empty,
        ["selection_domain"] = Active?.SelectionDomain ?? string.Empty,
        ["gesture_id"] = Active?.GestureId ?? string.Empty,
        ["snapshot_generation"] = Active?.SnapshotGeneration ?? 0,
        ["base_geometry_revision"] = Active?.BaseGeometryRevision ?? 0,
        ["base_selection_revision"] = Active?.BaseSelectionRevision ?? 0,
        ["topology_generation"] = Active?.TopologyGeneration ?? 0,
        ["failure_code"] = LastFailureCode,
        ["failure_message"] = LastFailureMessage,
    };

    public void Dispose()
    {
        _cancellation?.Cancel();
        ClearActive();
        State = MeshEditOperatorState.Idle;
    }

    private bool IdentityMatches(string gestureId) =>
        Active is not null
        && string.Equals(Active.GestureId, gestureId, StringComparison.Ordinal);

    private void Settle(
        MeshEditOperatorTerminalState terminalState,
        bool preserveFailure = false)
    {
        LastTerminalState = terminalState;
        if (!preserveFailure)
        {
            LastFailureCode = string.Empty;
            LastFailureMessage = string.Empty;
        }
        ClearActive();
        State = MeshEditOperatorState.Idle;
    }

    private void ClearActive()
    {
        Active = null;
        _cancellation?.Dispose();
        _cancellation = null;
    }
}
