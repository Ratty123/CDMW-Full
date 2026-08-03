using System.Drawing;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed record MeshInteractionSoakResult(
    bool FinalAuthorityMatches,
    bool StaleResultIgnored,
    bool ProvisionalCleared,
    double CursorCoveragePixels,
    int ChangedVertexCount,
    int SelectedPartCount,
    int SelectedVertexCount);

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
            BeginSelectionDrag(start, "vertex");
            MaybeEmitSelectionPaintSample(start);
            return;
        }
        var selectedVertexCount = Math.Max(1, _document.Submeshes[0].Vertices.Count / 4);
        _ = UpdateSelection(
            new Dictionary<int, HashSet<int>>
            {
                [0] = Enumerable.Range(0, selectedVertexCount).ToHashSet(),
            },
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<(int A, int B)>>(),
            new HashSet<int>(),
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
            var expected = CloneSelectionMap(_provisionalSelectedVertices);
            var selectionRequestId = Math.Max(1L, _authoritativeEditRevision + 1L);
            BeginProvisionalSelection(selectionRequestId, _authoritativeEditRevision);
            var accepted = UpdateSelection(
                expected,
                new Dictionary<int, HashSet<int>>(),
                new Dictionary<int, HashSet<(int A, int B)>>(),
                new HashSet<int>(),
                selectionRequestId,
                _authoritativeEditRevision + 1L);
            _selectionPaintActive = false;
            ReleasePaintProjectionCache();
            var matches = accepted
                && expected.Count == _selectedVertices.Count
                && expected.All(pair => _selectedVertices.TryGetValue(pair.Key, out var selected)
                    && pair.Value.SetEquals(selected));
            return new MeshInteractionSoakResult(
                matches,
                true,
                !_provisionalPartSelectionActive,
                _interactionSoakCoveragePixels,
                0,
                _selectedSources.Count,
                _selectedVertices.Values.Sum(values => values.Count));
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
            _selectedSources.Count,
            _selectedVertices.Values.Sum(values => values.Count));
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
            var authoritative = candidate.Baseline.ToArray();
            var indices = new List<int>(candidate.EditableIndices.Length);
            foreach (var vertexIndex in candidate.EditableIndices)
            {
                var value = candidate.Working[vertexIndex];
                if (Vector3.DistanceSquared(
                        ToVector3(value),
                        ToVector3(candidate.Baseline[vertexIndex])) <= 0.000000000001f)
                {
                    continue;
                }
                authoritative[vertexIndex] = value;
                submesh.Vertices[vertexIndex] = value;
                indices.Add(vertexIndex);
            }
            expected[candidate.SubmeshIndex] = authoritative;
            if (indices.Count > 0)
            {
                changed[candidate.SubmeshIndex] = indices;
                changedCount += indices.Count;
            }
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
            "smooth" => "smooth",
            "pinch" => "pinch",
            _ => throw new ArgumentOutOfRangeException(nameof(mode), "Interaction soak mode must be select_brush, move, grab, smooth, inflate, or pinch."),
        };
}
