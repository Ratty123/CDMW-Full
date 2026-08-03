using System.Drawing;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed record MeshInteractionSoakResult(
    bool FinalAuthorityMatches,
    bool StaleResultIgnored,
    bool ProvisionalCleared,
    double CursorCoveragePixels,
    int ChangedVertexCount,
    int SelectedPartCount);

/// <summary>
/// Drives the same local gesture methods used by WinForms mouse input while a
/// hidden D3D11 viewport is measured. This is test-harness plumbing only: it
/// does not add a protocol surface or a second mutation authority.
/// </summary>
internal sealed partial class MeshViewport
{
    private string _interactionSoakMode = string.Empty;
    private Point _interactionSoakPrevious;
    private double _interactionSoakCoveragePixels;

    internal bool TryRunHeadlessRendererFrame(out double frameMs, out double presentMs, out string error)
    {
        if (_d3d11Viewport is null)
        {
            frameMs = 0.0;
            presentMs = 0.0;
            error = "The production D3D11 renderer is unavailable.";
            return false;
        }
        return _d3d11Viewport.TryRunHeadlessFrame(out frameMs, out presentMs, out error);
    }

    internal void BeginInteractionSoak(string mode, Point start)
    {
        _interactionSoakMode = NormalizeInteractionSoakMode(mode);
        _interactionSoakPrevious = start;
        _interactionSoakCoveragePixels = 0.0;
        _scene.SetInteractionMode("mesh_edit");
        if (_interactionSoakMode == "select_brush")
        {
            _ = UpdateSelection(
                new Dictionary<int, HashSet<int>>(),
                new Dictionary<int, HashSet<int>>(),
                new Dictionary<int, HashSet<(int A, int B)>>(),
                new HashSet<int>(),
                revision: _authoritativeEditRevision);
            ActiveTool = "select";
            SetSelectionDragMode("brush");
            BeginSelectionDrag(start, "source");
            MaybeEmitSelectionPaintSample(start);
            return;
        }
        _ = UpdateSelection(
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<(int A, int B)>>(),
            new HashSet<int> { 0 },
            revision: _authoritativeEditRevision);
        ActiveTool = _interactionSoakMode;
        BeginEditorStroke(start);
        if (!_editorStrokeActive)
        {
            throw new InvalidOperationException($"Could not begin {_interactionSoakMode} interaction soak stroke.");
        }
    }

    internal void StepInteractionSoak(Point point)
    {
        var dx = point.X - _interactionSoakPrevious.X;
        var dy = point.Y - _interactionSoakPrevious.Y;
        _interactionSoakCoveragePixels += Math.Sqrt((double)dx * dx + (double)dy * dy);
        if (_interactionSoakMode == "select_brush")
        {
            MaybeEmitSelectionPaintSample(point);
        }
        else
        {
            UpdateProvisionalEditorStroke(point);
            MaybeEmitEditorStrokeUpdate(point);
            _strokePrevious = point;
        }
        _interactionSoakPrevious = point;
    }

    internal MeshInteractionSoakResult FinishInteractionSoak(Point point)
    {
        StepInteractionSoak(point);
        if (_interactionSoakMode == "select_brush")
        {
            FinishEdgeDrag(point);
            var expected = new HashSet<int>(_provisionalSelectedSources);
            var selectionRequestId = Math.Max(1L, _authoritativeEditRevision + 1L);
            BeginProvisionalSelection(selectionRequestId, _authoritativeEditRevision);
            var accepted = UpdateSelection(
                new Dictionary<int, HashSet<int>>(),
                new Dictionary<int, HashSet<int>>(),
                new Dictionary<int, HashSet<(int A, int B)>>(),
                expected,
                selectionRequestId,
                _authoritativeEditRevision + 1L);
            _selectionPaintActive = false;
            ReleasePaintProjectionCache();
            var matches = accepted && expected.SetEquals(_selectedSources);
            return new MeshInteractionSoakResult(
                matches,
                true,
                !_provisionalPartSelectionActive,
                _interactionSoakCoveragePixels,
                0,
                _selectedSources.Count);
        }

        var state = _provisionalStroke
            ?? throw new InvalidOperationException("The provisional stroke ended before its authority check.");
        CompleteProvisionalStrokeRequest(
            long.MaxValue,
            $"stale-{state.StrokeId}",
            "stroke_end",
            accepted: false,
            status: "rejected");
        var staleIgnored = ReferenceEquals(state, _provisionalStroke);
        EndEditorStroke(point, cancelled: false);
        var changed = CommitInteractionSoakGeometry(state, out var finalAuthorityMatches);
        var requestId = Math.Max(1L, _authoritativeEditRevision + 1L);
        var revision = _authoritativeEditRevision + 1L;
        RegisterProvisionalStrokeRequest(requestId, state.BaseRevision, state.StrokeId, "stroke_end");
        _ = AcceptProvisionalStrokeUpdate(requestId, state.StrokeId, revision);
        CompleteProvisionalStrokeRequest(
            requestId,
            state.StrokeId,
            "stroke_end",
            accepted: true,
            status: "accepted",
            authoritativeGeometryPending: true,
            revision: revision);
        CompleteProvisionalAuthoritativeUpdate(requestId, state.StrokeId, revision);
        SetAuthoritativeEditRevision(revision);
        return new MeshInteractionSoakResult(
            finalAuthorityMatches,
            staleIgnored,
            !HasProvisionalStroke,
            _interactionSoakCoveragePixels,
            changed,
            _selectedSources.Count);
    }

    private int CommitInteractionSoakGeometry(
        ProvisionalStrokeState state,
        out bool finalAuthorityMatches)
    {
        var changed = new Dictionary<int, IReadOnlyCollection<int>>();
        var expected = new Dictionary<int, Vec3[]>();
        var changedCount = 0;
        foreach (var candidate in state.Submeshes)
        {
            var submesh = _document.Submeshes[candidate.SubmeshIndex];
            var authoritative = new Vec3[candidate.Baseline.Length];
            var indices = new int[candidate.Baseline.Length];
            for (var vertexIndex = 0; vertexIndex < authoritative.Length; vertexIndex++)
            {
                var value = state.Tool == "move"
                    ? FromVector3(ToVector3(candidate.Baseline[vertexIndex]) + candidate.LastTranslation)
                    : candidate.Working[vertexIndex];
                authoritative[vertexIndex] = value;
                submesh.Vertices[vertexIndex] = value;
                indices[vertexIndex] = vertexIndex;
            }
            expected[candidate.SubmeshIndex] = authoritative;
            changed[candidate.SubmeshIndex] = indices;
            changedCount += indices.Length;
        }
        RefreshVertexGeometry(changed);
        finalAuthorityMatches = expected.All(pair =>
        {
            var vertices = _document.Submeshes[pair.Key].Vertices;
            var wanted = pair.Value;
            return vertices.Count == wanted.Length
                && vertices.Select((vertex, index) => Vector3.Distance(ToVector3(vertex), ToVector3(wanted[index])))
                    .All(distance => distance <= 0.000001f);
        });
        return changedCount;
    }

    private static string NormalizeInteractionSoakMode(string mode) =>
        (mode ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            "select" or "select_brush" => "select_brush",
            "move" => "move",
            "grab" => "grab",
            "sculpt" or "inflate" => "inflate",
            _ => throw new ArgumentOutOfRangeException(nameof(mode), "Interaction soak mode must be select_brush, move, grab, or inflate."),
        };
}
