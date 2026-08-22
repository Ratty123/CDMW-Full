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

    // The pointer polyline since the last emitted sample, starting at that
    // sample. When the throttled emission has to cover more than a dab, the
    // native request carries this actual path, not the straight chord between
    // samples: a fast curved stroke's echo and its authoritative result must
    // agree about which band was painted.
    private readonly List<Point> _selectionPaintPendingPath = new();

    private void AppendSelectionPaintPendingPoint(Point point)
    {
        if (_selectionPaintPendingPath.Count == 0 || _selectionPaintPendingPath[^1] != point)
        {
            _selectionPaintPendingPath.Add(point);
        }
    }

    private bool SelectionPaintPathLeavesChord(Point previous, Point point, double radius)
    {
        var limit = radius * 0.5;
        foreach (var pathPoint in _selectionPaintPendingPath)
        {
            if (DistanceToSegment(new PointF(pathPoint.X, pathPoint.Y), previous, point) > limit)
            {
                return true;
            }
        }
        return false;
    }

    /// <summary>
    /// One sample of a brush-select drag, throttled to the stroke protocol
    /// cadence and a minimum step. A short step is an add/subtract
    /// `screen_brush` dab at the cursor; a step longer than the brush radius,
    /// or one whose pointer path bowed away from the straight chord, becomes a
    /// `screen_region` brush-path band over the polyline actually swept, so
    /// the painted band unions without holes at any cursor speed or curvature
    /// -- the cadence bounds message rate, not coverage. The plain click keeps
    /// the precise pick path. The first sample carries the combo operation
    /// (replace starts the new selection); every later one adds or subtracts.
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
                    AppendSelectionPaintPendingPoint(point);
                }
                return;
            }
        }
        if (final && _selectionPaintPainted && point == _selectionPaintLastSample)
        {
            if (SelectionPaintPathLeavesChord(_selectionPaintLastSample, point, SelectionPaintRadiusPixels()))
            {
                // The echo advanced along a loop that returned to the sample
                // point inside one cadence window; flush that band before the
                // terminal packet so the authoritative result covers it.
                EmitSelectionSweepPath(point, SelectionPaintRadiusPixels(), _selectionPaintOperation);
            }
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
        AppendSelectionPaintPendingPoint(point);
        if (_selectionPaintPainted
            && (stepLength > radius || SelectionPaintPathLeavesChord(previous, point, radius)))
        {
            EmitSelectionSweepPath(point, radius, operation);
            // The band covers the swept polyline; the trailing dab below keeps
            // the round tip at the cursor so the visible ring and the
            // selection agree at the stroke's leading edge.
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
        _selectionPaintPendingPath.Clear();
        _selectionPaintPendingPath.Add(point);
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

    /// <summary>
    /// The swept-band half of a throttled paint sample: a `screen_region` in
    /// native brush mode carrying the pointer polyline actually swept since
    /// the last emitted sample plus the brush radius. The straight quad this
    /// replaces covered only the chord between two samples, so a fast curved
    /// stroke selected along the chord while the echo painted the curve.
    /// </summary>
    private void EmitSelectionSweepPath(Point end, double radius, string operation)
    {
        AppendSelectionPaintPendingPoint(end);
        if (_selectionPaintPendingPath.Count < 2)
        {
            return;
        }
        var region = ScreenDragPayload(_selectionPaintPendingPath[0], end);
        region["mode"] = "brush";
        region["selection_mode"] = "brush";
        region["points"] = _selectionPaintPendingPath
            .Select(pathPoint => new[] { (double)pathPoint.X, (double)pathPoint.Y })
            .ToArray();
        region["radius_pixels"] = radius;
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
    /// it lasts: where each editable vertex lands on screen (with its depth),
    /// spatial buckets for vertices, faces and edges, and a coarse front-depth
    /// raster standing in for the native occlusion mask.
    /// </summary>
    /// <remarks>
    /// All of it used to be recomputed for every dab — the front-facing test
    /// walked every face of the submesh per vertex, O(vertices × faces) per dab
    /// on the UI thread, which is what made brush select stutter and lag behind
    /// the cursor instead of painting. Built once per drag it is
    /// O(vertices + faces + edges), and every dab after it is a bucket query.
    /// The depth raster replaces the old front-facing gate for visible-mode
    /// echo: the authoritative native result filters by its own depth mask, so
    /// an echo that only tested facing tinted occluded geometry the result then
    /// un-selected, which read as the brush failing to select.
    /// </remarks>
    private sealed class PaintProjectionCache
    {
        public required Matrix4x4 Camera { get; init; }
        public required int GridColumns { get; init; }
        public required int GridRows { get; init; }
        // The pane size these screen positions were computed for: a resize that
        // leaves the matrix untouched must not reuse positions measured at the
        // old size, and an X-Ray toggle must not reuse a drag's depth raster.
        public required int ViewportWidth { get; init; }
        public required int ViewportHeight { get; init; }
        public required bool BuiltForXRay { get; init; }
        public Dictionary<int, PointF[]> Points { get; } = new();
        public Dictionary<int, float[]> Depths { get; } = new();
        public Dictionary<int, RectangleF> PartBounds { get; } = new();
        public Dictionary<int, int[][]> VertexBuckets { get; } = new();
        public Dictionary<int, int[][]> FaceBuckets { get; } = new();
        public Dictionary<int, int[]> LargeFaceCandidates { get; } = new();
        public Dictionary<int, List<int>> FaceQueryCandidates { get; } = new();
        public Dictionary<int, int[]> FaceVisitStamps { get; } = new();
        public Dictionary<int, RectangleF[]> FaceBounds { get; } = new();
        // One grid over the whole pane for edges, indexed by position in
        // _edgeTopology.Edges. Edges got no buckets when vertices and faces
        // did, leaving the edge echo a full O(edges) scan per pointer sample.
        public int[][] EdgeBuckets = Array.Empty<int[]>();
        public int[] LargeEdgeCandidates = Array.Empty<int>();
        public int[] EdgeVisitStamps = Array.Empty<int>();
        public List<int> EdgeQueryCandidates { get; } = new();
        // Coarse min-depth raster over the pane (empty in X-Ray mode). The
        // local stand-in for the native selection depth mask.
        public float[] OcclusionDepths = Array.Empty<float>();
        public int OcclusionColumns;
        public int OcclusionRows;
        private int _faceVisitStamp;

        public int BeginFaceQuery()
        {
            if (_faceVisitStamp == int.MaxValue)
            {
                foreach (var stamps in FaceVisitStamps.Values)
                {
                    Array.Clear(stamps);
                }
                Array.Clear(EdgeVisitStamps);
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
        var liveViewport = ActivePaneBounds();
        if (_paintProjection is { } cached
            && cached.Camera.Equals(camera.WorldViewProjection)
            && cached.ViewportWidth == Math.Max(1, liveViewport.Width)
            && cached.ViewportHeight == Math.Max(1, liveViewport.Height)
            && cached.BuiltForXRay == ShowXRay)
        {
            return cached;
        }
        var viewport = liveViewport;
        var cache = new PaintProjectionCache
        {
            Camera = camera.WorldViewProjection,
            GridColumns = Math.Max(1, (viewport.Width + PaintProjectionCellPixels - 1) / PaintProjectionCellPixels),
            GridRows = Math.Max(1, (viewport.Height + PaintProjectionCellPixels - 1) / PaintProjectionCellPixels),
            ViewportWidth = Math.Max(1, viewport.Width),
            ViewportHeight = Math.Max(1, viewport.Height),
            BuiltForXRay = ShowXRay,
        };
        PreparePaintOcclusionGrid(cache);
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount && submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            if (!IsSubmeshVisibleForViewportSelection(submeshIndex))
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            var points = new PointF[submesh.Vertices.Count];
            var depths = new float[submesh.Vertices.Count];
            var pendingVertexBuckets = new List<int>?[cache.GridColumns * cache.GridRows];
            var minX = float.PositiveInfinity;
            var minY = float.PositiveInfinity;
            var maxX = float.NegativeInfinity;
            var maxY = float.NegativeInfinity;
            for (var vertexIndex = 0; vertexIndex < points.Length; vertexIndex++)
            {
                points[vertexIndex] = SceneProjectedPointWithDepth(
                    camera,
                    submeshIndex,
                    submesh.Vertices[vertexIndex],
                    out depths[vertexIndex]);
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
            cache.Depths[submeshIndex] = depths;
            cache.VertexBuckets[submeshIndex] = pendingVertexBuckets
                .Select(bucket => bucket?.ToArray() ?? Array.Empty<int>())
                .ToArray();
            if (points.Length > 0)
            {
                cache.PartBounds[submeshIndex] = RectangleF.FromLTRB(minX, minY, maxX, maxY);
            }
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
                RasterizePaintOcclusionTriangle(cache, points[a], depths[a], points[b], depths[b], points[c], depths[c]);
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
            cache.FaceBuckets[submeshIndex] = pendingFaceBuckets
                .Select(bucket => bucket?.ToArray() ?? Array.Empty<int>())
                .ToArray();
            cache.LargeFaceCandidates[submeshIndex] = largeFaceCandidates.ToArray();
            cache.FaceQueryCandidates[submeshIndex] = new List<int>();
            cache.FaceVisitStamps[submeshIndex] = new int[submesh.Faces.Count];
            cache.FaceBounds[submeshIndex] = faceBounds;
        }
        BuildPaintEdgeBuckets(cache);
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
            PaintEchoEdgeHits(cache, start, end, radius, operation, bandBounds);
        }
        else if (_selectionDragTargetMode == "face")
        {
            PaintEchoFaceHits(cache, start, end, radius, operation, bandBounds);
        }
        else
        {
            PaintEchoVertexHits(cache, start, end, radius, operation, bandBounds);
        }
        RecordPickProbe(cache, start, end, radius);
        _provisionalPartSelectionActive = false;
        UpdateGpuViewport();
        Invalidate();
    }

    private void PaintEchoEdgeHits(
        PaintProjectionCache cache,
        Point start,
        Point end,
        double radius,
        string operation,
        RectangleF bandBounds)
    {
        var edges = _edgeTopology.Edges;
        if (cache.EdgeVisitStamps.Length != edges.Count)
        {
            return;
        }
        var stamp = cache.BeginFaceQuery();
        var candidates = cache.EdgeQueryCandidates;
        candidates.Clear();
        var left = Math.Clamp((int)MathF.Floor(bandBounds.Left / PaintProjectionCellPixels), 0, cache.GridColumns - 1);
        var right = Math.Clamp((int)MathF.Floor(bandBounds.Right / PaintProjectionCellPixels), 0, cache.GridColumns - 1);
        var top = Math.Clamp((int)MathF.Floor(bandBounds.Top / PaintProjectionCellPixels), 0, cache.GridRows - 1);
        var bottom = Math.Clamp((int)MathF.Floor(bandBounds.Bottom / PaintProjectionCellPixels), 0, cache.GridRows - 1);
        for (var row = top; row <= bottom; row++)
        {
            for (var column = left; column <= right; column++)
            {
                foreach (var edgeIndex in cache.EdgeBuckets[row * cache.GridColumns + column])
                {
                    if (cache.EdgeVisitStamps[edgeIndex] == stamp)
                    {
                        continue;
                    }
                    cache.EdgeVisitStamps[edgeIndex] = stamp;
                    candidates.Add(edgeIndex);
                }
            }
        }
        foreach (var edgeIndex in cache.LargeEdgeCandidates)
        {
            if (cache.EdgeVisitStamps[edgeIndex] == stamp)
            {
                continue;
            }
            cache.EdgeVisitStamps[edgeIndex] = stamp;
            candidates.Add(edgeIndex);
        }
        var radiusSquared = radius * radius;
        foreach (var edgeIndex in candidates)
        {
            var edge = edges[edgeIndex];
            if (!cache.Points.TryGetValue(edge.SubmeshIndex, out var points)
                || !cache.Depths.TryGetValue(edge.SubmeshIndex, out var depths)
                || edge.VertexA < 0
                || edge.VertexA >= points.Length
                || edge.VertexB < 0
                || edge.VertexB >= points.Length
                || SegmentDistanceSquared(start, end, points[edge.VertexA], points[edge.VertexB]) > radiusSquared)
            {
                continue;
            }
            if (!ShowXRay
                && !PaintSegmentVisible(
                    cache,
                    points[edge.VertexA],
                    depths[edge.VertexA],
                    points[edge.VertexB],
                    depths[edge.VertexB]))
            {
                continue;
            }
            ApplyProvisionalHit(_provisionalSelectedEdges, edge.Id, operation, _selectionPaintToggleTouchedEdges);
        }
    }

    private void PaintEchoFaceHits(
        PaintProjectionCache cache,
        Point start,
        Point end,
        double radius,
        string operation,
        RectangleF bandBounds)
    {
        var faceQueryStamp = cache.BeginFaceQuery();
        foreach (var pair in cache.Points)
        {
            var submeshIndex = pair.Key;
            var points = pair.Value;
            if (!cache.PartBounds.TryGetValue(submeshIndex, out var partBounds)
                || !partBounds.IntersectsWith(bandBounds))
            {
                continue;
            }
            var depths = cache.Depths[submeshIndex];
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
                if (!SweptBandIntersectsTriangle(start, end, radius, points[a], points[b], points[c]))
                {
                    continue;
                }
                if (!ShowXRay
                    && !PaintTriangleVisible(cache, points[a], depths[a], points[b], depths[b], points[c], depths[c]))
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
        }
    }

    private void PaintEchoVertexHits(
        PaintProjectionCache cache,
        Point start,
        Point end,
        double radius,
        string operation,
        RectangleF bandBounds)
    {
        foreach (var pair in cache.Points)
        {
            var submeshIndex = pair.Key;
            var points = pair.Value;
            if (!cache.PartBounds.TryGetValue(submeshIndex, out var partBounds)
                || !partBounds.IntersectsWith(bandBounds))
            {
                continue;
            }
            var depths = cache.Depths[submeshIndex];
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
                        if (DistanceToSegment(points[vertexIndex], start, end) > radius)
                        {
                            continue;
                        }
                        if (!ShowXRay
                            && !PaintPointVisible(cache, points[vertexIndex].X, points[vertexIndex].Y, depths[vertexIndex]))
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
