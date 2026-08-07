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
    private string _provisionalSelectionStrokeId = string.Empty;
    private long _provisionalSelectionStrokeSequence = -1;
    private SelectionAuthoritySnapshot? _selectionStrokeBase;

    public long AcknowledgedSelectionRevision => _acknowledgedSelection.Revision;
    public bool HasPendingSelectionAuthority => _provisionalSelectionRequestId > 0;

    public void BeginProvisionalSelection(
        long requestId,
        long baseRevision,
        string strokeId = "",
        long strokeSequence = -1,
        string strokePhase = "")
    {
        if (requestId <= 0 || requestId < _provisionalSelectionRequestId)
        {
            return;
        }
        _provisionalSelectionRequestId = requestId;
        _provisionalSelectionBaseRevision = Math.Max(0, baseRevision);
        var normalizedStrokeId = (strokeId ?? string.Empty).Trim();
        var normalizedPhase = (strokePhase ?? string.Empty).Trim().ToLowerInvariant();
        if (normalizedStrokeId.Length == 0 || strokeSequence < 0)
        {
            return;
        }
        if (normalizedPhase == "begin"
            || !string.Equals(_provisionalSelectionStrokeId, normalizedStrokeId, StringComparison.Ordinal))
        {
            _selectionStrokeBase = new SelectionAuthoritySnapshot(
                CloneSelectionMap(_selectedVertices),
                CloneSelectionMap(_selectedFaces),
                new HashSet<int>(_selectedEdges),
                new HashSet<int>(_selectedSources),
                requestId,
                Math.Max(0, baseRevision));
            _provisionalSelectionStrokeId = normalizedStrokeId;
            _provisionalSelectionStrokeSequence = strokeSequence;
            return;
        }
        _provisionalSelectionStrokeSequence = Math.Max(_provisionalSelectionStrokeSequence, strokeSequence);
    }

    public bool RejectProvisionalSelection(long requestId)
    {
        if (requestId <= 0 || requestId != _provisionalSelectionRequestId)
        {
            return false;
        }
        if (_selectionStrokeBase is not null)
        {
            RestoreSelectionSnapshot(_selectionStrokeBase);
        }
        else
        {
            RestoreAcknowledgedSelection();
        }
        _provisionalSelectionRequestId = 0;
        _provisionalSelectionBaseRevision = 0;
        _provisionalSelectionStrokeId = string.Empty;
        _provisionalSelectionStrokeSequence = -1;
        _selectionStrokeBase = null;
        return true;
    }

    public void ResetSelectionAuthority()
    {
        ClearProvisionalEditorStroke();
        RestoreAcknowledgedSelection();
        _provisionalSelectionRequestId = 0;
        _provisionalSelectionBaseRevision = 0;
        _provisionalSelectionStrokeId = string.Empty;
        _provisionalSelectionStrokeSequence = -1;
        _selectionStrokeBase = null;
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

    private bool AcceptAuthoritativeSelection(
        long requestId,
        long revision,
        string strokeId = "",
        long strokeSequence = -1,
        string strokePhase = "")
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
        var normalizedStrokeId = (strokeId ?? string.Empty).Trim();
        var normalizedPhase = (strokePhase ?? string.Empty).Trim().ToLowerInvariant();
        var correlatedStroke = normalizedStrokeId.Length > 0
            && string.Equals(_provisionalSelectionStrokeId, normalizedStrokeId, StringComparison.Ordinal);
        var terminalAcknowledgement = correlatedStroke
            && strokeSequence >= _provisionalSelectionStrokeSequence
            && normalizedPhase is "end" or "cancel";
        if (!correlatedStroke)
        {
            ClearProvisionalSelectionEcho();
            if (_selectionPaintActive)
            {
                ReplaceSelectionMap(_provisionalSelectedVertices, _selectedVertices);
                ReplaceSelectionMap(_provisionalSelectedFaces, _selectedFaces);
                _provisionalSelectedEdges.UnionWith(_selectedEdges);
                _provisionalPartSelectionActive = _selectionDragTargetMode is "source" or "part";
                if (_provisionalPartSelectionActive)
                {
                    _provisionalSelectedSources.UnionWith(_selectedSources);
                }
            }
            else
            {
                _provisionalPartSelectionActive = false;
            }
        }
        else if (terminalAcknowledgement)
        {
            ClearProvisionalSelectionEcho();
            _provisionalSelectionStrokeId = string.Empty;
            _provisionalSelectionStrokeSequence = -1;
            _selectionStrokeBase = null;
        }
        if (requestId <= 0 || requestId == _provisionalSelectionRequestId)
        {
            _provisionalSelectionRequestId = 0;
            _provisionalSelectionBaseRevision = 0;
        }
        return true;
    }

    private bool HasNewerProvisionalSelection(
        long requestId,
        string strokeId = "",
        long strokeSequence = -1,
        string strokePhase = "")
    {
        var normalizedStrokeId = (strokeId ?? string.Empty).Trim();
        if (normalizedStrokeId.Length > 0
            && string.Equals(_provisionalSelectionStrokeId, normalizedStrokeId, StringComparison.Ordinal))
        {
            var normalizedPhase = (strokePhase ?? string.Empty).Trim().ToLowerInvariant();
            return strokeSequence < _provisionalSelectionStrokeSequence
                || normalizedPhase is not ("end" or "cancel");
        }
        return _provisionalSelectionRequestId > 0
            && _provisionalSelectionRequestId > requestId;
    }

    private void RestoreAcknowledgedSelection()
    {
        RestoreSelectionSnapshot(_acknowledgedSelection);
    }

    private void RestoreSelectionSnapshot(SelectionAuthoritySnapshot snapshot)
    {
        ClearProvisionalSelectionEcho();
        ReplaceSelectionMap(_selectedVertices, snapshot.Vertices);
        ReplaceSelectionMap(_selectedFaces, snapshot.Faces);
        _selectedEdges.Clear();
        _selectedEdges.UnionWith(snapshot.Edges.Where(_edgeTopology.Contains));
        _selectedSources.Clear();
        _selectedSources.UnionWith(snapshot.Sources);
        SyncSelectedPartFocus();
        UpdateGpuViewport();
        Invalidate();
    }

    private static Dictionary<int, HashSet<int>> CloneSelectionMap(
        IReadOnlyDictionary<int, HashSet<int>> source) =>
        source.ToDictionary(pair => pair.Key, pair => new HashSet<int>(pair.Value));
}
