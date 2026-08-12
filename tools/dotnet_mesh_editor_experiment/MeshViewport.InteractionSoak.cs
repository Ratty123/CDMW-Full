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
    int SelectedVertexCount,
    int SelectedEdgeCount,
    int SelectedFaceCount);

/// <summary>
/// Drives the same local gesture methods used by WinForms mouse input while a
/// hidden D3D11 viewport is measured. This is test-harness plumbing only: it
/// does not add a protocol surface or a second mutation authority.
/// </summary>
internal sealed partial class MeshViewport
{
    private string _interactionSoakMode = string.Empty;
    private string _interactionSoakSelectionShape = string.Empty;
    private string _interactionSoakSelectionTarget = string.Empty;
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

    internal Point InteractionSoakMeshAnchor()
    {
        var submesh = _document.Submeshes[0];
        var vertex = submesh.Vertices[Math.Max(0, submesh.Vertices.Count / 2)];
        var projected = SceneProjectedPoint(CurrentCamera(), 0, vertex);
        return new Point(
            Math.Clamp((int)Math.Round(projected.X), 1, Math.Max(1, ClientSize.Width - 2)),
            Math.Clamp((int)Math.Round(projected.Y), 1, Math.Max(1, ClientSize.Height - 2)));
    }

    internal void BeginInteractionSoak(string mode, Point start)
    {
        _interactionSoakMode = NormalizeInteractionSoakMode(mode);
        (_interactionSoakSelectionShape, _interactionSoakSelectionTarget) =
            SelectionInteractionSoakMode(_interactionSoakMode);
        _interactionSoakPrevious = start;
        _interactionSoakCoveragePixels = 0.0;
        _scene.SetInteractionMode("mesh_edit");
        if (_interactionSoakSelectionShape.Length > 0)
        {
            _ = UpdateSelection(
                new Dictionary<int, HashSet<int>>(),
                new Dictionary<int, HashSet<int>>(),
                new Dictionary<int, HashSet<(int A, int B)>>(),
                new HashSet<int>(),
                revision: _authoritativeEditRevision);
            ActiveTool = "select";
            SetSelectionDragMode(_interactionSoakSelectionShape);
            BeginSelectionDrag(start, _interactionSoakSelectionTarget);
            if (_interactionSoakSelectionShape == "brush")
            {
                MaybeEmitSelectionPaintSample(start);
            }
            return;
        }
        var selectedVertexCount = Math.Max(1, _document.Submeshes[0].Vertices.Count / 4);
        var selectedVertices = new Dictionary<int, HashSet<int>>
        {
            [0] = _interactionSoakMode == "move"
                ? Enumerable.Range(0, selectedVertexCount).ToHashSet()
                : Enumerable.Range(0, _document.Submeshes[0].Vertices.Count).ToHashSet(),
        };
        _ = UpdateSelection(
            selectedVertices,
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
        if (_interactionSoakSelectionShape == "brush")
        {
            MaybeEmitSelectionPaintSample(point);
        }
        else if (_interactionSoakSelectionShape == "lasso")
        {
            _edgeDragCurrent = point;
            if (_selectionLassoPoints.Count == 0
                || Math.Abs(point.X - _selectionLassoPoints[^1].X)
                    + Math.Abs(point.Y - _selectionLassoPoints[^1].Y) >= 3)
            {
                _selectionLassoPoints.Add(point);
            }
        }
        else if (_interactionSoakSelectionShape == "rectangle")
        {
            _edgeDragCurrent = point;
        }
        else
        {
            UpdateProvisionalEditorStroke(point);
            MaybeEmitEditorStrokeUpdate(point);
            _strokePrevious = point;
        }
        _interactionSoakPrevious = point;
    }

    internal void FinishLassoInteractionSoakWithoutFinalMove(Point point)
    {
        if (_interactionSoakSelectionShape != "lasso")
        {
            throw new InvalidOperationException("The release-only diagnostic requires a lasso selection gesture.");
        }
        FinishEdgeDrag(point);
        ReleasePaintProjectionCache();
    }

    internal MeshInteractionSoakResult FinishInteractionSoak(Point point)
    {
        StepInteractionSoak(point);
        if (_interactionSoakSelectionShape.Length > 0)
        {
            FinishEdgeDrag(point);
            var expectedVertices = CloneSelectionMap(_provisionalSelectedVertices);
            var expectedFaces = CloneSelectionMap(_provisionalSelectedFaces);
            var expectedEdges = _provisionalSelectedEdges
                .Select(edgeId => _edgeTopology.EdgeById(edgeId))
                .Where(edge => edge is not null)
                .GroupBy(edge => edge!.SubmeshIndex)
                .ToDictionary(
                    group => group.Key,
                    group => group
                        .Select(edge => (edge!.VertexA, edge.VertexB))
                        .ToHashSet());
            var selectionRequestId = Math.Max(1L, _authoritativeEditRevision + 1L);
            BeginProvisionalSelection(selectionRequestId, _authoritativeEditRevision);
            var accepted = UpdateSelection(
                expectedVertices,
                expectedFaces,
                expectedEdges,
                new HashSet<int>(),
                selectionRequestId,
                _authoritativeEditRevision + 1L);
            _selectionPaintActive = false;
            ReleasePaintProjectionCache();
            var matches = accepted && SelectionMapsMatch(expectedVertices, _selectedVertices)
                && SelectionMapsMatch(expectedFaces, _selectedFaces)
                && expectedEdges.Sum(pair => pair.Value.Count) == _selectedEdges.Count;
            return new MeshInteractionSoakResult(
                matches,
                true,
                !_provisionalPartSelectionActive,
                _interactionSoakCoveragePixels,
                0,
                _selectedSources.Count,
                _selectedVertices.Values.Sum(values => values.Count),
                _selectedEdges.Count,
                _selectedFaces.Values.Sum(values => values.Count));
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
            _selectedVertices.Values.Sum(values => values.Count),
            _selectedEdges.Count,
            _selectedFaces.Values.Sum(values => values.Count));
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

    private static bool SelectionMapsMatch(
        IReadOnlyDictionary<int, HashSet<int>> expected,
        IReadOnlyDictionary<int, HashSet<int>> actual) =>
        expected.Count == actual.Count
        && expected.All(pair => actual.TryGetValue(pair.Key, out var selected)
            && pair.Value.SetEquals(selected));

    private static (string Shape, string Target) SelectionInteractionSoakMode(string mode)
    {
        var pieces = mode.Split('_', StringSplitOptions.RemoveEmptyEntries);
        return pieces.Length == 3 && pieces[0] == "select"
            ? (pieces[1], pieces[2])
            : (string.Empty, string.Empty);
    }

    private static string NormalizeInteractionSoakMode(string mode) =>
        (mode ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            "select" or "select_brush" or "select_brush_vertex" => "select_brush_vertex",
            "select_brush_edge" => "select_brush_edge",
            "select_brush_face" => "select_brush_face",
            "select_lasso_vertex" => "select_lasso_vertex",
            "select_lasso_edge" => "select_lasso_edge",
            "select_lasso_face" => "select_lasso_face",
            "select_rectangle_vertex" => "select_rectangle_vertex",
            "select_rectangle_edge" => "select_rectangle_edge",
            "select_rectangle_face" => "select_rectangle_face",
            "move" => "move",
            "grab" => "grab",
            "sculpt" or "inflate" => "inflate",
            "smooth" => "smooth",
            "pinch" => "pinch",
            _ => throw new ArgumentOutOfRangeException(
                nameof(mode),
                "Interaction soak mode must be a vertex/edge/face Select brush/lasso/rectangle, Move, Grab, Smooth, Inflate, or Pinch."),
        };
}
