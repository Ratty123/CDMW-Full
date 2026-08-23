using System.Drawing;
using System.Diagnostics;
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
    int SelectedFaceCount,
    bool AuthorityStreamed);

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

    internal void ResetPaintProjectionCacheForInteractionSoak() =>
        InvalidatePaintProjectionCache("interaction_soak_cold_start");

    internal bool WaitForPaintProjectionCacheForInteractionSoak(
        int timeoutMilliseconds,
        out double maximumHeartbeatGapMs)
    {
        var deadline = Stopwatch.StartNew();
        var previous = Stopwatch.GetTimestamp();
        maximumHeartbeatGapMs = 0.0;
        while (_paintProjectionBuildActive && deadline.ElapsedMilliseconds < Math.Max(1, timeoutMilliseconds))
        {
            Application.DoEvents();
            Thread.Sleep(1);
            var current = Stopwatch.GetTimestamp();
            maximumHeartbeatGapMs = Math.Max(
                maximumHeartbeatGapMs,
                Stopwatch.GetElapsedTime(previous, current).TotalMilliseconds);
            previous = current;
        }
        Application.DoEvents();
        return !_paintProjectionBuildActive && _paintProjection is not null;
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

    internal void BeginShortFaceBrushInteractionSoak(Point start)
    {
        _interactionSoakMode = "select_brush_face";
        (_interactionSoakSelectionShape, _interactionSoakSelectionTarget) =
            SelectionInteractionSoakMode(_interactionSoakMode);
        _interactionSoakPrevious = start;
        _interactionSoakCoveragePixels = 0.0;
        _scene.SetInteractionMode("mesh_edit");
        ActiveTool = "select";
        SetSelectionDragMode(_interactionSoakSelectionShape);
        BeginSelectionDrag(start, _interactionSoakSelectionTarget);
        MaybeEmitSelectionPaintSample(start);
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
        FinishSelectionGesture(point, cancelled: false);
    }

    internal void FinishSelectionInteractionSoakAfterLostMouseUp(Point point)
    {
        if (_interactionSoakSelectionShape.Length == 0)
        {
            throw new InvalidOperationException("The lost-release diagnostic requires a selection gesture.");
        }
        OnMouseMove(new MouseEventArgs(MouseButtons.None, 0, point.X, point.Y, 0));
    }

    internal bool SelectionInteractionSoakStateClean =>
        !_edgeDragActive
        && !_selectionPaintActive
        && !_selectionPaintPainted
        && string.IsNullOrWhiteSpace(_selectionStrokeId)
        && _selectionLassoPoints.Count == 0
        && _selectionPaintPathPoints.Count == 0
        && _selectionPaintToggleTouchedVertices.Count == 0
        && _selectionPaintToggleTouchedFaces.Count == 0
        && _selectionPaintToggleTouchedEdges.Count == 0
        && _pendingPaintSample is null;

    internal MeshInteractionSoakResult FinishInteractionSoak(
        Point point,
        bool deferStreamedAuthority = false)
    {
        StepInteractionSoak(point);
        if (_interactionSoakSelectionShape.Length > 0)
        {
            FinishSelectionGesture(point, cancelled: false);
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
                _selectedFaces.Values.Sum(values => values.Count),
                false);
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
        if (deferStreamedAuthority && !state.LocalGeometryPreview)
        {
            return new MeshInteractionSoakResult(
                false,
                staleIgnored,
                false,
                _interactionSoakCoveragePixels,
                0,
                _selectedSources.Count,
                _selectedVertices.Values.Sum(values => values.Count),
                _selectedEdges.Count,
                _selectedFaces.Values.Sum(values => values.Count),
                false);
        }
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
            _selectedFaces.Values.Sum(values => values.Count),
            !state.LocalGeometryPreview);
    }

    internal bool BeginPendingFaceSelectionCommandDiagnostic()
    {
        if (_document.Submeshes.Count == 0 || _document.Submeshes[0].Faces.Count == 0)
        {
            return false;
        }
        _ = UpdateSelection(
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<(int A, int B)>>(),
            new HashSet<int>(),
            revision: _authoritativeEditRevision);
        _provisionalSelectedFaces[0] = new HashSet<int> { 0 };
        BeginProvisionalSelection(
            Math.Max(1L, _authoritativeEditRevision + 1L),
            _authoritativeEditRevision,
            "pending-topology-diagnostic",
            0,
            "end");
        return HasPendingSelectionAuthority
            && !HasEditableSelection
            && _provisionalSelectedFaces.TryGetValue(0, out var faces)
            && faces.Contains(0);
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

    /// <summary>
    /// Which way a plain left drag turns the subject. The contract is that the side
    /// facing the reader follows the pointer -- right for a drag to the right, down for a
    /// drag downward -- the way pan does and the way Blender and Maya orbit. It is read
    /// through the renderer's own projection and depth, on the vertex drawn nearest the
    /// reader, so it holds whatever sign the camera's angles carry. A synthetic viewport
    /// with no files behind it, like the layout smoke's backdrop contract: no renderer,
    /// no window.
    /// </summary>
    internal static Dictionary<string, object?> OrbitFollowsPointerContract()
    {
        var document = HeadlessGpuSparseSoak.BuildSyntheticDocument(64);
        var materials = NetMaterialSet.Empty;
        using var textures = NetTextureSet.Load(materials);
        var scene = NetSceneState.Load(string.Empty, document.Submeshes.Count);
        scene.SetInteractionMode("mesh_edit");
        using var viewport = new MeshViewport(document, materials, textures, scene, HeadlessGpuInteractionSoak.SyntheticLaunchOptions())
        {
            Size = new Size(640, 480),
        };
        viewport.ActiveTool = "orbit";
        // A three-quarter view: the synthetic mesh is a strip along x, and seen from an
        // angle it has a near end. Each drag starts from the same view.
        const float startYaw = MathF.PI * 0.25f;
        const float startPitch = 0.35f;
        viewport.PointCameraForContract(startYaw, startPitch);
        var start = new Point(320, 240);
        var before = viewport.NearestVertexScreenPoint(out var vertex);
        var afterRight = viewport.OrbitDragThenProject(vertex, start, new Point(start.X + 40, start.Y));
        viewport.PointCameraForContract(startYaw, startPitch);
        var afterDown = viewport.OrbitDragThenProject(vertex, start, new Point(start.X, start.Y + 40));
        var followsRight = afterRight.X > before.X + 0.5f;
        var followsDown = afterDown.Y > before.Y + 0.5f;
        return new Dictionary<string, object?>
        {
            ["ok"] = followsRight && followsDown,
            ["near_side_follows_drag_right"] = followsRight,
            ["near_side_follows_drag_down"] = followsDown,
            ["near_vertex"] = new[] { vertex.X, vertex.Y, vertex.Z },
            ["near_vertex_px_before"] = new[] { before.X, before.Y },
            ["near_vertex_px_after_drag_right"] = new[] { afterRight.X, afterRight.Y },
            ["near_vertex_px_after_drag_down"] = new[] { afterDown.X, afterDown.Y },
        };
    }

    private void PointCameraForContract(float yaw, float pitch)
    {
        _yaw = yaw;
        _pitch = pitch;
        _panX = 0.0f;
        _panY = 0.0f;
    }

    /// <summary>The vertex the renderer draws nearest the reader, by its own depth, and
    /// where it lands on screen.</summary>
    private PointF NearestVertexScreenPoint(out Vec3 vertex)
    {
        var camera = CurrentCamera();
        var submesh = _document.Submeshes[0];
        vertex = submesh.Vertices[0];
        var point = PointF.Empty;
        var nearest = float.MaxValue;
        foreach (var candidate in submesh.Vertices)
        {
            var projected = SceneProjectedPointWithDepth(camera, 0, candidate, out var depth);
            if (depth < nearest)
            {
                nearest = depth;
                vertex = candidate;
                point = projected;
            }
        }
        return point;
    }

    /// <summary>A plain left drag from one point to another through the move handler
    /// WinForms drives, then where the vertex is drawn afterwards.</summary>
    private PointF OrbitDragThenProject(Vec3 vertex, Point from, Point to)
    {
        _rotating = true;
        _panning = false;
        _lastMouse = from;
        OnMouseMove(new MouseEventArgs(MouseButtons.Left, 0, to.X, to.Y, 0));
        _rotating = false;
        return SceneProjectedPoint(CurrentCamera(), 0, vertex);
    }
}
