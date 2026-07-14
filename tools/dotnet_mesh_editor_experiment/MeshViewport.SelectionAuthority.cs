namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private sealed record SelectionAuthoritySnapshot(
        Dictionary<int, HashSet<int>> Vertices,
        Dictionary<int, HashSet<int>> Faces,
        HashSet<int> Edges,
        HashSet<int> Sources,
        long RequestId,
        long Revision);

    private SelectionAuthoritySnapshot _acknowledgedSelection = new(
        new Dictionary<int, HashSet<int>>(),
        new Dictionary<int, HashSet<int>>(),
        new HashSet<int>(),
        new HashSet<int>(),
        0,
        0);
    private long _provisionalSelectionRequestId;
    private long _provisionalSelectionBaseRevision;

    public long AcknowledgedSelectionRevision => _acknowledgedSelection.Revision;

    public void BeginProvisionalSelection(long requestId, long baseRevision)
    {
        if (requestId <= 0 || requestId < _provisionalSelectionRequestId)
        {
            return;
        }
        _provisionalSelectionRequestId = requestId;
        _provisionalSelectionBaseRevision = Math.Max(0, baseRevision);
    }

    public bool RejectProvisionalSelection(long requestId)
    {
        if (requestId <= 0 || requestId != _provisionalSelectionRequestId)
        {
            return false;
        }
        RestoreAcknowledgedSelection();
        _provisionalSelectionRequestId = 0;
        _provisionalSelectionBaseRevision = 0;
        return true;
    }

    public void ResetSelectionAuthority()
    {
        RestoreAcknowledgedSelection();
        _provisionalSelectionRequestId = 0;
        _provisionalSelectionBaseRevision = 0;
    }

    private bool CanAcceptAuthoritativeSelection(long requestId, long revision)
    {
        var normalizedRevision = Math.Max(0, revision);
        if (normalizedRevision < _acknowledgedSelection.Revision)
        {
            return false;
        }
        return normalizedRevision != _acknowledgedSelection.Revision
            || requestId <= 0
            || requestId >= _acknowledgedSelection.RequestId;
    }

    private bool AcceptAuthoritativeSelection(long requestId, long revision)
    {
        if (!CanAcceptAuthoritativeSelection(requestId, revision))
        {
            return false;
        }
        _acknowledgedSelection = new SelectionAuthoritySnapshot(
            CloneSelectionMap(_selectedVertices),
            CloneSelectionMap(_selectedFaces),
            new HashSet<int>(_selectedEdges),
            new HashSet<int>(_selectedSources),
            Math.Max(0, requestId),
            Math.Max(0, revision));
        if (requestId <= 0 || requestId == _provisionalSelectionRequestId)
        {
            _provisionalSelectionRequestId = 0;
            _provisionalSelectionBaseRevision = 0;
        }
        return true;
    }

    private bool HasNewerProvisionalSelection(long requestId) =>
        _provisionalSelectionRequestId > 0
        && _provisionalSelectionRequestId > requestId;

    private void RestoreAcknowledgedSelection()
    {
        ReplaceSelectionMap(_selectedVertices, _acknowledgedSelection.Vertices);
        ReplaceSelectionMap(_selectedFaces, _acknowledgedSelection.Faces);
        _selectedEdges.Clear();
        _selectedEdges.UnionWith(_acknowledgedSelection.Edges.Where(_edgeTopology.Contains));
        _selectedSources.Clear();
        _selectedSources.UnionWith(_acknowledgedSelection.Sources);
        SyncSelectedPartFocus();
        UpdateGpuViewport();
        Invalidate();
    }

    private static Dictionary<int, HashSet<int>> CloneSelectionMap(
        IReadOnlyDictionary<int, HashSet<int>> source) =>
        source.ToDictionary(pair => pair.Key, pair => new HashSet<int>(pair.Value));
}
