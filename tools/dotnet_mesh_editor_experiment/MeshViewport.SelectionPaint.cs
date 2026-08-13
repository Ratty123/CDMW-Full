using System.Drawing;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private void BeginSelectionStroke()
    {
        _selectionStrokeId = Guid.NewGuid().ToString("N");
        _selectionStrokeSequence = 0;
        EmitSelectionRequest(
            new Dictionary<string, object?>
            {
                ["operation"] = CurrentSelectionOperation(),
                ["target_mode"] = _selectionDragTargetMode,
                ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
            },
            "begin");
    }

    private void EmitSelectionRequest(Dictionary<string, object?> payload, string phase)
    {
        if (string.IsNullOrWhiteSpace(_selectionStrokeId))
        {
            return;
        }
        var normalizedPhase = (phase ?? string.Empty).Trim().ToLowerInvariant();
        payload["stroke_id"] = _selectionStrokeId;
        payload["phase"] = normalizedPhase;
        payload["sequence"] = _selectionStrokeSequence++;
        EditorEventRequested?.Invoke("select_request", payload);
        if (normalizedPhase is "end" or "cancel")
        {
            _selectionStrokeId = string.Empty;
        }
    }

    private void CancelSelectionStroke()
    {
        if (string.IsNullOrWhiteSpace(_selectionStrokeId))
        {
            return;
        }
        EmitSelectionRequest(
            new Dictionary<string, object?>
            {
                ["operation"] = "replace",
                ["target_mode"] = _selectionDragTargetMode,
                ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
            },
            "cancel");
    }

    /// <summary>
    /// One sample of a brush-select drag, throttled to the stroke protocol
    /// cadence and a minimum step. A short step is an add/subtract
    /// `screen_brush` dab at the cursor; a step longer than the brush radius
    /// becomes a `screen_region` quad covering the swept segment (extended a
    /// radius past both ends so consecutive quads overlap their joints), so
    /// the painted band unions without holes at any cursor speed -- the
    /// cadence bounds message rate, not coverage. The quad's square ends can
    /// reach slightly outside the round brush tip; a paint sweep is area
    /// coverage, not a precision pick, and the plain click keeps the precise
    /// pick path. The first sample carries the combo operation (replace
    /// starts the new selection); every later one adds or subtracts.
    /// </summary>
    private void MaybeEmitSelectionPaintSample(Point point, bool final = false)
    {
        var toggleGesture = _selectionPaintFirstOperation == "toggle";
        var now = Environment.TickCount64;
        if (toggleGesture)
        {
            var previousEcho = _selectionPaintPainted ? _selectionPaintLastEcho : point;
            var echoMoved = Math.Abs(point.X - previousEcho.X) + Math.Abs(point.Y - previousEcho.Y)
                >= SelectionPaintSampleMinimumStepPixels;
            if (!_selectionPaintPainted || echoMoved || final)
            {
                if (_selectionPaintPathPoints.Count == 0 || _selectionPaintPathPoints[^1] != point)
                {
                    _selectionPaintPathPoints.Add(point);
                }
                UpdateProvisionalPaintHits(
                    previousEcho,
                    point,
                    SelectionPaintRadiusPixels(),
                    "toggle");
                _selectionPaintLastEcho = point;
                _selectionPaintPainted = true;
            }
            if (!final)
            {
                return;
            }
            EmitFinalTogglePaintSelection();
            return;
        }
        if (!final && _selectionPaintPainted)
        {
            var tooSoon = now - _selectionPaintLastSampleTicks < (long)SelectionPaintSampleIntervalMs;
            var tooClose = Math.Abs(point.X - _selectionPaintLastSample.X)
                + Math.Abs(point.Y - _selectionPaintLastSample.Y)
                < SelectionPaintSampleMinimumStepPixels;
            if (tooSoon || tooClose)
            {
                // The cadence bounds how often the host is asked for an
                // authoritative result, not how often the reader sees the
                // stroke. Holding the local echo back too made a brush drag
                // paint in visible steps a frame behind the cursor rather than
                // under it, which is the whole complaint about brush select.
                // The echo is a superset of what the next emitted sample asks
                // for, so nothing it tints is lost when that result lands.
                if (!tooClose)
                {
                    UpdateProvisionalPaintHits(
                        _selectionPaintLastEcho,
                        point,
                        SelectionPaintRadiusPixels(),
                        _selectionPaintOperation);
                    _selectionPaintLastEcho = point;
                }
                return;
            }
        }
        if (final && _selectionPaintPainted && point == _selectionPaintLastSample)
        {
            EmitSelectionRequest(
                new Dictionary<string, object?>
                {
                    ["operation"] = _selectionPaintOperation,
                    ["target_mode"] = _selectionDragTargetMode,
                    ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
                    ["paint_sample"] = true,
                    ["paint_final"] = true,
                },
                "end");
            return;
        }
        var radius = SelectionPaintRadiusPixels();
        var operation = _selectionPaintPainted ? _selectionPaintOperation : _selectionPaintFirstOperation;
        var previous = _selectionPaintLastSample;
        var stepX = (double)(point.X - previous.X);
        var stepY = (double)(point.Y - previous.Y);
        var stepLength = Math.Sqrt(stepX * stepX + stepY * stepY);
        if (!_selectionPaintPainted && operation == "replace")
        {
            ClearProvisionalSelectionEcho();
        }
        UpdateProvisionalPaintHits(
            _selectionPaintPainted ? previous : point,
            point,
            radius,
            operation);
        if (_selectionPaintPainted && stepLength > radius)
        {
            EmitSelectionSweepQuad(previous, point, radius, operation, stepX / stepLength, stepY / stepLength);
            // The quad covers the segment; the trailing dab below keeps the
            // round tip at the cursor so the visible ring and the selection
            // agree at the stroke's leading edge.
        }
        var payload = new Dictionary<string, object?>
        {
            ["operation"] = operation,
            ["target_mode"] = _selectionDragTargetMode,
            ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
            ["paint_sample"] = true,
            ["paint_final"] = final,
            ["screen_brush"] = ScreenPayload(point, radius),
        };
        EmitSelectionRequest(payload, final ? "end" : "update");
        _selectionPaintPainted = true;
        _selectionPaintLastSample = point;
        _selectionPaintLastEcho = point;
        _selectionPaintLastSampleTicks = now;
    }

    private void EmitFinalTogglePaintSelection()
    {
        var path = _selectionPaintPathPoints.Count > 0
            ? _selectionPaintPathPoints
            : new List<Point> { _selectionPaintLastEcho };
        var region = ScreenDragPayload(path[0], path[^1]);
        region["mode"] = "brush";
        region["selection_mode"] = "brush";
        region["points"] = path
            .Select(pathPoint => new[] { (double)pathPoint.X, (double)pathPoint.Y })
            .ToArray();
        region["radius_pixels"] = SelectionPaintRadiusPixels();
        EmitSelectionRequest(new Dictionary<string, object?>
        {
            ["operation"] = "toggle",
            ["target_mode"] = _selectionDragTargetMode,
            ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
            ["paint_sample"] = true,
            ["paint_final"] = true,
            ["screen_region"] = region,
        }, "end");
    }

    private void EmitSelectionSweepQuad(
        Point start,
        Point end,
        double radius,
        string operation,
        double directionX,
        double directionY)
    {
        var extendedStartX = start.X - directionX * radius;
        var extendedStartY = start.Y - directionY * radius;
        var extendedEndX = end.X + directionX * radius;
        var extendedEndY = end.Y + directionY * radius;
        var normalX = -directionY * radius;
        var normalY = directionX * radius;
        var region = ScreenDragPayload(start, end);
        region["mode"] = "lasso";
        region["points"] = new[]
        {
            new[] { extendedStartX + normalX, extendedStartY + normalY },
            new[] { extendedEndX + normalX, extendedEndY + normalY },
            new[] { extendedEndX - normalX, extendedEndY - normalY },
            new[] { extendedStartX - normalX, extendedStartY - normalY },
        };
        EmitSelectionRequest(new Dictionary<string, object?>
        {
            ["operation"] = operation,
            ["target_mode"] = _selectionDragTargetMode,
            ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
            ["paint_sample"] = true,
            ["paint_final"] = false,
            ["screen_region"] = region,
        }, "update");
    }

    private double SelectionPaintRadiusPixels()
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        return Math.Clamp(NumberOption(options, "radius", 24.0), 2.0, 256.0);
    }

    /// <summary>
    /// Everything a paint drag needs about the scene that does not change while
    /// it lasts: where each editable vertex lands on screen, and whether any
    /// face it belongs to faces the camera.
    /// </summary>
    /// <remarks>
    /// Both used to be recomputed for every dab. The projection is one matrix
    /// transform per vertex, but the front-facing test walked every face of the
    /// submesh looking for one that contains the vertex — O(vertices × faces)
    /// per dab, which on a real garment part is tens of millions of triangle
    /// orientations at the 30ms sample cadence, on the UI thread. That is what
    /// made brush select stutter and lag behind the cursor instead of painting.
    /// Built once per drag it is O(vertices + faces), and every dab after it is
    /// a distance test.
    /// </remarks>
    private sealed class PaintProjectionCache
    {
        public required Matrix4x4 Camera { get; init; }
        public required int GridColumns { get; init; }
        public required int GridRows { get; init; }
        // The pane size these screen positions were computed for. The cache is
        // keyed on the camera matrix alone, and a resize that leaves the matrix
        // untouched would otherwise reuse positions measured at the old size.
        public required int ViewportWidth { get; init; }
        public required int ViewportHeight { get; init; }
        public Dictionary<int, PointF[]> Points { get; } = new();
        public Dictionary<int, bool[]> FrontFacingVertices { get; } = new();
        public Dictionary<int, RectangleF> PartBounds { get; } = new();
        public Dictionary<int, int[][]> VertexBuckets { get; } = new();
        public Dictionary<int, int[][]> FaceBuckets { get; } = new();
        public Dictionary<int, int[]> LargeFaceCandidates { get; } = new();
        public Dictionary<int, List<int>> FaceQueryCandidates { get; } = new();
        public Dictionary<int, int[]> FaceVisitStamps { get; } = new();
        public Dictionary<int, RectangleF[]> FaceBounds { get; } = new();
        private int _faceVisitStamp;

        public int BeginFaceQuery()
        {
            if (_faceVisitStamp == int.MaxValue)
            {
                foreach (var stamps in FaceVisitStamps.Values)
                {
                    Array.Clear(stamps);
                }
                _faceVisitStamp = 0;
            }
            return ++_faceVisitStamp;
        }
    }

    private const int PaintProjectionCellPixels = 16;
    private const int PaintProjectionMaximumFaceBucketCells = 16;
    private PaintProjectionCache? _paintProjection;

    internal static bool PaintProjectionFaceUsesLargeCandidateList(
        int leftCell,
        int rightCell,
        int topCell,
        int bottomCell) =>
        (long)(rightCell - leftCell + 1) * (bottomCell - topCell + 1)
            > PaintProjectionMaximumFaceBucketCells;

    internal static bool RoutePaintProjectionFaceCandidate(
        List<int>?[] faceBuckets,
        List<int> largeFaceCandidates,
        int faceIndex,
        int gridColumns,
        int leftCell,
        int rightCell,
        int topCell,
        int bottomCell)
    {
        if (PaintProjectionFaceUsesLargeCandidateList(leftCell, rightCell, topCell, bottomCell))
        {
            largeFaceCandidates.Add(faceIndex);
            return true;
        }
        for (var row = topCell; row <= bottomCell; row++)
        {
            for (var column = leftCell; column <= rightCell; column++)
            {
                var bucketIndex = row * gridColumns + column;
                (faceBuckets[bucketIndex] ??= new List<int>()).Add(faceIndex);
            }
        }
        return false;
    }

    /// <summary>
    /// Drops the per-drag projection cache. Called when the gesture ends, so a
    /// camera move between drags can never be answered from stale screen
    /// positions.
    /// </summary>
    private void ReleasePaintProjectionCache()
    {
        _paintProjection = null;
    }

    private PaintProjectionCache EnsurePaintProjectionCache(NetViewportCamera camera)
    {
        if (_paintProjection is { } cached && cached.Camera.Equals(camera.WorldViewProjection))
        {
            return cached;
        }
        var viewport = ActivePaneBounds();
        var cache = new PaintProjectionCache
        {
            Camera = camera.WorldViewProjection,
            GridColumns = Math.Max(1, (viewport.Width + PaintProjectionCellPixels - 1) / PaintProjectionCellPixels),
            GridRows = Math.Max(1, (viewport.Height + PaintProjectionCellPixels - 1) / PaintProjectionCellPixels),
            ViewportWidth = Math.Max(1, viewport.Width),
            ViewportHeight = Math.Max(1, viewport.Height),
        };
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount && submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            if (!IsSubmeshVisibleForViewportSelection(submeshIndex))
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            var points = new PointF[submesh.Vertices.Count];
            var pendingVertexBuckets = new List<int>?[cache.GridColumns * cache.GridRows];
            var minX = float.PositiveInfinity;
            var minY = float.PositiveInfinity;
            var maxX = float.NegativeInfinity;
            var maxY = float.NegativeInfinity;
            for (var vertexIndex = 0; vertexIndex < points.Length; vertexIndex++)
            {
                points[vertexIndex] = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
                minX = Math.Min(minX, points[vertexIndex].X);
                minY = Math.Min(minY, points[vertexIndex].Y);
                maxX = Math.Max(maxX, points[vertexIndex].X);
                maxY = Math.Max(maxY, points[vertexIndex].Y);
                var column = (int)MathF.Floor(points[vertexIndex].X / PaintProjectionCellPixels);
                var row = (int)MathF.Floor(points[vertexIndex].Y / PaintProjectionCellPixels);
                if (column >= 0 && column < cache.GridColumns && row >= 0 && row < cache.GridRows)
                {
                    var bucketIndex = row * cache.GridColumns + column;
                    (pendingVertexBuckets[bucketIndex] ??= new List<int>()).Add(vertexIndex);
                }
            }
            cache.Points[submeshIndex] = points;
            cache.VertexBuckets[submeshIndex] = pendingVertexBuckets
                .Select(bucket => bucket?.ToArray() ?? Array.Empty<int>())
                .ToArray();
            if (points.Length > 0)
            {
                cache.PartBounds[submeshIndex] = RectangleF.FromLTRB(minX, minY, maxX, maxY);
            }
            var frontFacing = new bool[submesh.Vertices.Count];
            var faceBounds = new RectangleF[submesh.Faces.Count];
            var pendingFaceBuckets = new List<int>?[cache.GridColumns * cache.GridRows];
            var largeFaceCandidates = new List<int>();
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                var face = submesh.Faces[faceIndex];
                if (face.Corners.Length != 3)
                {
                    continue;
                }
                var a = face.Corners[0].VertexIndex;
                var b = face.Corners[1].VertexIndex;
                var c = face.Corners[2].VertexIndex;
                if (a < 0 || b < 0 || c < 0 || a >= points.Length || b >= points.Length || c >= points.Length)
                {
                    continue;
                }
                var area = ((points[b].X - points[a].X) * (points[c].Y - points[a].Y))
                    - ((points[b].Y - points[a].Y) * (points[c].X - points[a].X));
                if (area < -0.01f)
                {
                    frontFacing[a] = true;
                    frontFacing[b] = true;
                    frontFacing[c] = true;
                }
                var faceLeft = MathF.Min(points[a].X, MathF.Min(points[b].X, points[c].X));
                var faceTop = MathF.Min(points[a].Y, MathF.Min(points[b].Y, points[c].Y));
                var faceRight = MathF.Max(points[a].X, MathF.Max(points[b].X, points[c].X));
                var faceBottom = MathF.Max(points[a].Y, MathF.Max(points[b].Y, points[c].Y));
                faceBounds[faceIndex] = RectangleF.FromLTRB(faceLeft, faceTop, faceRight, faceBottom);
                if (faceRight < 0.0f
                    || faceBottom < 0.0f
                    || faceLeft >= viewport.Width
                    || faceTop >= viewport.Height)
                {
                    continue;
                }
                var leftCell = Math.Clamp(
                    (int)MathF.Floor(faceLeft / PaintProjectionCellPixels),
                    0,
                    cache.GridColumns - 1);
                var rightCell = Math.Clamp(
                    (int)MathF.Floor(faceRight / PaintProjectionCellPixels),
                    0,
                    cache.GridColumns - 1);
                var topCell = Math.Clamp(
                    (int)MathF.Floor(faceTop / PaintProjectionCellPixels),
                    0,
                    cache.GridRows - 1);
                var bottomCell = Math.Clamp(
                    (int)MathF.Floor(faceBottom / PaintProjectionCellPixels),
                    0,
                    cache.GridRows - 1);
                _ = RoutePaintProjectionFaceCandidate(
                    pendingFaceBuckets,
                    largeFaceCandidates,
                    faceIndex,
                    cache.GridColumns,
                    leftCell,
                    rightCell,
                    topCell,
                    bottomCell);
            }
            cache.FrontFacingVertices[submeshIndex] = frontFacing;
            cache.FaceBuckets[submeshIndex] = pendingFaceBuckets
                .Select(bucket => bucket?.ToArray() ?? Array.Empty<int>())
                .ToArray();
            cache.LargeFaceCandidates[submeshIndex] = largeFaceCandidates.ToArray();
            cache.FaceQueryCandidates[submeshIndex] = new List<int>();
            cache.FaceVisitStamps[submeshIndex] = new int[submesh.Faces.Count];
            cache.FaceBounds[submeshIndex] = faceBounds;
        }
        _paintProjection = cache;
        return cache;
    }

    /// <summary>
    /// Instant local echo of one paint dab or sweep. The active target owns the
    /// provisional domain; whole-part selection remains reserved for PARTS.
    /// Projection, visibility and spatial buckets are immutable for the drag,
    /// so dense meshes do not turn each pointer sample into a whole-mesh scan.
    /// </summary>
    // What the picker last compared, in its own numbers: the segment it tested,
    // the pane size in force at that moment, and the pane size the projected
    // positions were actually built for. A pick that reads correct from inside
    // the helper and lands elsewhere from outside is only distinguishable with
    // both sizes side by side.
    internal Dictionary<string, object?>? LastPickProbe { get; private set; }

    private void RecordPickProbe(PaintProjectionCache cache, Point start, Point end, double radius)
    {
        var live = ActivePaneBounds();
        var sample = _provisionalSelectedVertices
            .FirstOrDefault(pair => pair.Value.Count > 0 && cache.Points.ContainsKey(pair.Key));
        var probe = new Dictionary<string, object?>
        {
            ["segment_start_x"] = start.X,
            ["segment_start_y"] = start.Y,
            ["segment_end_x"] = end.X,
            ["segment_end_y"] = end.Y,
            ["radius_pixels"] = radius,
            ["cache_viewport_width"] = cache.ViewportWidth,
            ["cache_viewport_height"] = cache.ViewportHeight,
            ["live_viewport_width"] = live.Width,
            ["live_viewport_height"] = live.Height,
            ["cache_matches_live_viewport"] =
                cache.ViewportWidth == live.Width && cache.ViewportHeight == live.Height,
        };
        if (sample.Value is { Count: > 0 })
        {
            var vertexIndex = sample.Value.First();
            var points = cache.Points[sample.Key];
            if (vertexIndex >= 0 && vertexIndex < points.Length)
            {
                probe["sample_submesh_index"] = sample.Key;
                probe["sample_vertex_index"] = vertexIndex;
                probe["sample_cache_point_x"] = points[vertexIndex].X;
                probe["sample_cache_point_y"] = points[vertexIndex].Y;
            }
        }
        LastPickProbe = probe;
    }

    private void UpdateProvisionalPaintHits(Point start, Point end, double radius, string operation)
    {
        var cache = EnsurePaintProjectionCache(CurrentCamera());
        var bandBounds = RectangleF.FromLTRB(
            (float)(Math.Min(start.X, end.X) - radius),
            (float)(Math.Min(start.Y, end.Y) - radius),
            (float)(Math.Max(start.X, end.X) + radius),
            (float)(Math.Max(start.Y, end.Y) + radius));
        if (_selectionDragTargetMode == "edge")
        {
            foreach (var edge in _edgeTopology.Edges)
            {
                if (!cache.Points.TryGetValue(edge.SubmeshIndex, out var points)
                    || !cache.PartBounds.TryGetValue(edge.SubmeshIndex, out var partBounds)
                    || !partBounds.IntersectsWith(bandBounds)
                    || edge.VertexA < 0
                    || edge.VertexA >= points.Length
                    || edge.VertexB < 0
                    || edge.VertexB >= points.Length
                    || (!ShowXRay
                        && !cache.FrontFacingVertices[edge.SubmeshIndex][edge.VertexA]
                        && !cache.FrontFacingVertices[edge.SubmeshIndex][edge.VertexB])
                    || SegmentDistanceSquared(start, end, points[edge.VertexA], points[edge.VertexB]) > radius * radius)
                {
                    continue;
                }
                ApplyProvisionalHit(_provisionalSelectedEdges, edge.Id, operation, _selectionPaintToggleTouchedEdges);
            }
            _provisionalPartSelectionActive = false;
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        var faceQueryStamp = _selectionDragTargetMode == "face" ? cache.BeginFaceQuery() : 0;
        foreach (var pair in cache.Points)
        {
            var submeshIndex = pair.Key;
            var points = pair.Value;
            if (!cache.PartBounds.TryGetValue(submeshIndex, out var partBounds)
                || !partBounds.IntersectsWith(bandBounds))
            {
                continue;
            }
            var frontFacing = cache.FrontFacingVertices[submeshIndex];
            if (_selectionDragTargetMode == "face")
            {
                var submesh = _document.Submeshes[submeshIndex];
                var faceBuckets = cache.FaceBuckets[submeshIndex];
                var largeFaceCandidates = cache.LargeFaceCandidates[submeshIndex];
                var faceQueryCandidates = cache.FaceQueryCandidates[submeshIndex];
                var faceVisitStamps = cache.FaceVisitStamps[submeshIndex];
                var faceBounds = cache.FaceBounds[submeshIndex];
                if (!_provisionalSelectedFaces.TryGetValue(submeshIndex, out var selectedFaces))
                {
                    selectedFaces = new HashSet<int>();
                    if (operation != "subtract")
                    {
                        _provisionalSelectedFaces[submeshIndex] = selectedFaces;
                    }
                }
                var faceQueryLeft = Math.Clamp((int)MathF.Floor(bandBounds.Left / PaintProjectionCellPixels), 0, cache.GridColumns - 1);
                var faceQueryRight = Math.Clamp((int)MathF.Floor(bandBounds.Right / PaintProjectionCellPixels), 0, cache.GridColumns - 1);
                var faceQueryTop = Math.Clamp((int)MathF.Floor(bandBounds.Top / PaintProjectionCellPixels), 0, cache.GridRows - 1);
                var faceQueryBottom = Math.Clamp((int)MathF.Floor(bandBounds.Bottom / PaintProjectionCellPixels), 0, cache.GridRows - 1);
                faceQueryCandidates.Clear();
                for (var row = faceQueryTop; row <= faceQueryBottom; row++)
                {
                    for (var column = faceQueryLeft; column <= faceQueryRight; column++)
                    {
                        foreach (var faceIndex in faceBuckets[row * cache.GridColumns + column])
                        {
                            if (faceVisitStamps[faceIndex] == faceQueryStamp)
                            {
                                continue;
                            }
                            faceVisitStamps[faceIndex] = faceQueryStamp;
                            faceQueryCandidates.Add(faceIndex);
                        }
                    }
                }
                foreach (var faceIndex in largeFaceCandidates)
                {
                    if (faceVisitStamps[faceIndex] == faceQueryStamp)
                    {
                        continue;
                    }
                    faceVisitStamps[faceIndex] = faceQueryStamp;
                    faceQueryCandidates.Add(faceIndex);
                }
                foreach (var faceIndex in faceQueryCandidates)
                {
                    var candidateBounds = faceBounds[faceIndex];
                    if (candidateBounds.Right < bandBounds.Left
                        || candidateBounds.Left > bandBounds.Right
                        || candidateBounds.Bottom < bandBounds.Top
                        || candidateBounds.Top > bandBounds.Bottom)
                    {
                        continue;
                    }
                    var face = submesh.Faces[faceIndex];
                    var a = face.Corners[0].VertexIndex;
                    var b = face.Corners[1].VertexIndex;
                    var c = face.Corners[2].VertexIndex;
                    if (!ShowXRay && !frontFacing[a] && !frontFacing[b] && !frontFacing[c])
                    {
                        continue;
                    }
                    if (!SweptBandIntersectsTriangle(start, end, radius, points[a], points[b], points[c]))
                    {
                        continue;
                    }
                    ApplyProvisionalHit(
                        selectedFaces,
                        faceIndex,
                        operation,
                        _selectionPaintToggleTouchedFaces,
                        (submeshIndex, faceIndex));
                }
                if (selectedFaces.Count == 0)
                {
                    _provisionalSelectedFaces.Remove(submeshIndex);
                }
                continue;
            }
            var vertexBuckets = cache.VertexBuckets[submeshIndex];
            if (!_provisionalSelectedVertices.TryGetValue(submeshIndex, out var selected))
            {
                selected = new HashSet<int>();
                if (operation != "subtract")
                {
                    _provisionalSelectedVertices[submeshIndex] = selected;
                }
            }
            var left = Math.Clamp((int)MathF.Floor(bandBounds.Left / PaintProjectionCellPixels), 0, cache.GridColumns - 1);
            var right = Math.Clamp((int)MathF.Floor(bandBounds.Right / PaintProjectionCellPixels), 0, cache.GridColumns - 1);
            var top = Math.Clamp((int)MathF.Floor(bandBounds.Top / PaintProjectionCellPixels), 0, cache.GridRows - 1);
            var bottom = Math.Clamp((int)MathF.Floor(bandBounds.Bottom / PaintProjectionCellPixels), 0, cache.GridRows - 1);
            for (var row = top; row <= bottom; row++)
            {
                for (var column = left; column <= right; column++)
                {
                    foreach (var vertexIndex in vertexBuckets[row * cache.GridColumns + column])
                    {
                        if (!ShowXRay && !frontFacing[vertexIndex])
                        {
                            continue;
                        }
                        if (DistanceToSegment(points[vertexIndex], start, end) > radius)
                        {
                            continue;
                        }
                        if (operation == "subtract")
                        {
                            selected.Remove(vertexIndex);
                        }
                        else if (operation == "toggle")
                        {
                            if (!_selectionPaintToggleTouchedVertices.Add((submeshIndex, vertexIndex)))
                            {
                                continue;
                            }
                            if (!selected.Remove(vertexIndex))
                            {
                                selected.Add(vertexIndex);
                            }
                        }
                        else
                        {
                            selected.Add(vertexIndex);
                        }
                    }
                }
            }
            if (selected.Count == 0)
            {
                _provisionalSelectedVertices.Remove(submeshIndex);
            }
        }
        RecordPickProbe(cache, start, end, radius);
        _provisionalPartSelectionActive = false;
        UpdateGpuViewport();
        Invalidate();
    }

    private static void ApplyProvisionalHit<T>(
        HashSet<T> selected,
        T value,
        string operation,
        HashSet<T> toggleTouched)
        where T : notnull
    {
        if (operation == "subtract")
        {
            selected.Remove(value);
        }
        else if (operation == "toggle")
        {
            if (toggleTouched.Add(value) && !selected.Remove(value))
            {
                selected.Add(value);
            }
        }
        else
        {
            selected.Add(value);
        }
    }

    private static void ApplyProvisionalHit<TValue, TTouch>(
        HashSet<TValue> selected,
        TValue value,
        string operation,
        HashSet<TTouch> toggleTouched,
        TTouch touchValue)
        where TValue : notnull
        where TTouch : notnull
    {
        if (operation == "subtract")
        {
            selected.Remove(value);
        }
        else if (operation == "toggle")
        {
            if (toggleTouched.Add(touchValue) && !selected.Remove(value))
            {
                selected.Add(value);
            }
        }
        else
        {
            selected.Add(value);
        }
    }
}
