namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    internal void RegisterResidentInteractionRequest(long requestId, ulong gestureId)
    {
        if (requestId <= 0
            || !_residentNativeTransactions.TryGetValue(gestureId, out var lease))
        {
            return;
        }
        lease.RequestId = requestId;
        _residentNativeTransactionsByRequest[requestId] = lease;
    }

    internal void AcceptResidentInteraction(
        long requestId,
        long targetMeshRevision,
        long targetSelectionRevision,
        long topologyGeneration)
    {
        if (!_residentNativeTransactionsByRequest.TryGetValue(requestId, out var lease))
        {
            return;
        }
        AcknowledgeResidentInteractionCommit(
            requestId,
            lease.TransactionSequence,
            lease.Sha256,
            targetMeshRevision,
            targetSelectionRevision,
            topologyGeneration);
    }

    internal bool AcknowledgeResidentInteractionCommit(
        long requestId,
        ulong transactionSequence,
        string sha256,
        long targetMeshRevision,
        long targetSelectionRevision,
        long topologyGeneration)
    {
        if (!_residentNativeTransactionsByRequest.TryGetValue(requestId, out var lease)
            || lease.TransactionSequence != transactionSequence
            || !string.Equals(lease.Sha256, sha256, StringComparison.OrdinalIgnoreCase)
            || lease.TargetMeshRevision != checked((ulong)Math.Max(0, targetMeshRevision))
            || lease.TargetSelectionRevision != checked((ulong)Math.Max(0, targetSelectionRevision))
            || lease.TopologyGeneration != checked((ulong)Math.Max(0, topologyGeneration)))
        {
            return false;
        }
        var oldest = _residentNativeTransactions.Values
            .OrderBy(candidate => candidate.TransactionSequence)
            .FirstOrDefault();
        if (!ReferenceEquals(oldest, lease))
        {
            return false;
        }
        _residentNativeDurableRevision = lease.TargetMeshRevision;
        _residentNativeDurableSelectionRevision = lease.TargetSelectionRevision;
        _residentNativeDurableTopologyGeneration = lease.TopologyGeneration;
        RemoveResidentNativeTransaction(lease);
        if (!ResidentNativeReplicationPending)
        {
            StatusRequested?.Invoke("Mesh edits synchronized.");
        }
        return true;
    }

    internal void RejectResidentInteraction(long requestId, string reason)
    {
        if (!_residentNativeTransactionsByRequest.TryGetValue(requestId, out var lease))
        {
            return;
        }
        var rejected = _residentNativeTransactions.Values
            .Where(candidate => candidate.TransactionSequence >= lease.TransactionSequence)
            .OrderByDescending(candidate => candidate.TransactionSequence)
            .ToArray();
        foreach (var candidate in rejected)
        {
            RestoreResidentNativeTransactionBaseline(candidate);
        }
        _residentNativeMeshRevision = lease.BaseMeshRevision;
        _residentNativeSelectionRevision = lease.BaseSelectionRevision;
        _residentNativeTopologyGeneration = lease.TopologyGeneration;
        _residentNativeDurableRevision = lease.BaseMeshRevision;
        _residentNativeDurableSelectionRevision = lease.BaseSelectionRevision;
        _residentNativeDurableTopologyGeneration = lease.TopologyGeneration;
        _residentNativeReplicationRejected = true;
        CloseResidentNativeSession();
        OpenResidentNativeSession(
            lease.BaseMeshRevision,
            lease.BaseSelectionRevision,
            lease.TopologyGeneration);
        foreach (var candidate in rejected)
        {
            _editOperators.Reject(
                candidate.OperatorGestureId,
                "resident_interaction_rejected",
                reason);
            RemoveResidentNativeTransaction(candidate);
        }
        ClearResidentNativePreview();
        StatusRequested?.Invoke($"Mesh edit sync was rejected: {reason}. Restored the last durable state.");
    }

    internal void ApplyResidentNativeHistory(
        string command,
        long baseMeshRevision,
        long targetMeshRevision,
        long targetSelectionRevision,
        long topologyGeneration)
    {
        if (!ResidentNativeInteractionReady || _residentNativeAwaitingAuthority)
        {
            return;
        }
        var action = string.Equals(command, "undo", StringComparison.OrdinalIgnoreCase)
            ? NativeMeshInteractionAuthorityAction.Undo
            : NativeMeshInteractionAuthorityAction.Redo;
        var result = RequireResidentNativeSession().ApplyAuthority(
            new NativeMeshInteractionAuthorityRequest(
                0,
                action,
                checked((ulong)Math.Max(0, baseMeshRevision)),
                checked((ulong)Math.Max(0, targetMeshRevision)),
                _residentNativeSelectionRevision,
                checked((ulong)Math.Max(0, targetSelectionRevision)),
                _residentNativeTopologyGeneration,
                checked((ulong)Math.Max(0, topologyGeneration))));
        var targetMesh = checked((ulong)Math.Max(0, targetMeshRevision));
        var targetSelection = checked((ulong)Math.Max(0, targetSelectionRevision));
        var targetTopology = checked((ulong)Math.Max(0, topologyGeneration));
        if (result.IsSuccess)
        {
            _residentNativeMeshRevision = targetMesh;
            _residentNativeSelectionRevision = targetSelection;
            _residentNativeTopologyGeneration = targetTopology;
        }
        try
        {
            SynchronizeResidentNativeDocument(targetMesh, targetSelection, targetTopology);
        }
        catch
        {
            CloseResidentNativeSession();
            OpenResidentNativeSession(targetMesh, targetSelection, targetTopology);
        }
    }

    internal void SynchronizeResidentNativeAfterOneShot(
        long meshRevision,
        long selectionRevision,
        long topologyGeneration)
    {
        if (!ResidentNativeInteractionReady || _residentNativeAwaitingAuthority)
        {
            return;
        }
        SynchronizeResidentNativeDocument(
            checked((ulong)Math.Max(0, meshRevision)),
            checked((ulong)Math.Max(0, selectionRevision)),
            checked((ulong)Math.Max(0, topologyGeneration)));
    }

    private void RejectResidentNativeGestureWithoutHost(
        ResidentNativeGesture gesture,
        string reason)
    {
        if (_residentNativeTransactions.TryGetValue(gesture.GestureId, out var lease))
        {
            try { ApplyResidentNativeRejection(lease); }
            finally { RemoveResidentNativeTransaction(lease); }
        }
        else
        {
            var result = RequireResidentNativeSession().ApplyAuthority(
                new NativeMeshInteractionAuthorityRequest(
                    gesture.GestureId,
                    NativeMeshInteractionAuthorityAction.Rejected,
                    _residentNativeMeshRevision,
                    _residentNativeMeshRevision,
                    _residentNativeSelectionRevision,
                    _residentNativeSelectionRevision,
                    _residentNativeTopologyGeneration,
                    _residentNativeTopologyGeneration));
            if (result.Status is not NativeMeshInteractionStatus.Ok
                and not NativeMeshInteractionStatus.Rejected)
            {
                _residentNativeFailure = result.Message;
            }
        }
        _residentNativeAwaitingAuthority = false;
        ClearResidentNativePreview();
        _editOperators.Cancel(gesture.OperatorGestureId);
        StatusRequested?.Invoke($"Mesh Editor gesture produced {reason.Replace('_', ' ')}.");
    }

    private void ApplyResidentNativeRejection(ResidentInteractionTransactionLease lease)
    {
        var result = RequireResidentNativeSession().ApplyAuthority(
            new NativeMeshInteractionAuthorityRequest(
                lease.GestureId,
                NativeMeshInteractionAuthorityAction.Rejected,
                lease.BaseMeshRevision,
                lease.BaseMeshRevision,
                lease.BaseSelectionRevision,
                lease.BaseSelectionRevision,
                lease.TopologyGeneration,
                lease.TopologyGeneration));
        if (result.Status is not NativeMeshInteractionStatus.Ok
            and not NativeMeshInteractionStatus.Rejected)
        {
            throw new InvalidOperationException(
                $"Native authoritative rejection failed: {result.Status} {result.Message}");
        }
        _residentNativeMeshRevision = lease.BaseMeshRevision;
        _residentNativeSelectionRevision = lease.BaseSelectionRevision;
        _residentNativeTopologyGeneration = lease.TopologyGeneration;
    }

    private void RecoverResidentNativeAfterAcceptedFailure(
        ResidentInteractionTransactionLease lease,
        Exception exception)
    {
        _residentNativeFailure = exception.Message;
        CloseResidentNativeSession();
        OpenResidentNativeSession(
            lease.TargetMeshRevision,
            lease.TargetSelectionRevision,
            lease.TopologyGeneration);
        _editOperators.ApplyAuthoritativeResult(lease.OperatorGestureId);
        ClearResidentNativePreview();
        _editOperators.CompleteRenderer(lease.OperatorGestureId);
    }

    private void RemoveResidentNativeTransaction(ResidentInteractionTransactionLease lease)
    {
        _residentNativeTransactions.Remove(lease.GestureId);
        if (lease.RequestId > 0)
        {
            _residentNativeTransactionsByRequest.Remove(lease.RequestId);
        }
        _residentNativePendingTransactionBytes = Math.Max(
            0,
            _residentNativePendingTransactionBytes - lease.Length);
        lease.Dispose();
        _residentNativeAwaitingAuthority = false;
    }

    private void RejectAllResidentNativeTransactions(string reason)
    {
        if (_residentNativeGesture is not null && _residentNativeSession is not null)
        {
            try { CancelResidentNativeGesture(_residentNativeGesture, reason); }
            catch { _residentNativeGesture = null; }
        }
        foreach (var lease in _residentNativeTransactions.Values.ToArray())
        {
            lease.Dispose();
            _editOperators.Reject(lease.OperatorGestureId, "resident_interaction_reset", reason);
        }
        _residentNativeTransactions.Clear();
        _residentNativeTransactionsByRequest.Clear();
        _residentNativePendingTransactionBytes = 0;
        _residentNativeAwaitingAuthority = false;
        ClearResidentNativePreview();
    }
}
