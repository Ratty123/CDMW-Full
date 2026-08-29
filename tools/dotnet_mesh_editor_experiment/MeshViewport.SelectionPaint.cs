using System.Drawing;
using System.Diagnostics;
using System.Numerics;
using System.Threading;
using System.Threading.Tasks;

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
    private readonly StrokeSampleBuffer _selectionPaintPendingPath = new();

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
        IReadOnlyList<Point> path = _selectionPaintPathPoints.Count > 0
            ? _selectionPaintPathPoints
            : new[] { _selectionPaintLastEcho };
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
    /// the cursor instead of painting. The resident cache is prepared from an
    /// immutable snapshot off the input path, so every dab after publication is
    /// a bucket query and short gestures reuse the same projection data.
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
        public required long GeometryRevision { get; init; }
        public required int TopologyGeneration { get; init; }
        public required int EditableSubmeshCount { get; init; }
        public required int[] VisibleSubmeshIndices { get; init; }
        public required Dictionary<int, Matrix4x4> ModelMatrices { get; init; }
        public Dictionary<int, PointF[]> Points { get; } = new();
        public Dictionary<int, float[]> Depths { get; } = new();
        public Dictionary<int, PaintProjectionFace[]> Faces { get; } = new();
        public PaintProjectionEdge[] Edges { get; set; } = Array.Empty<PaintProjectionEdge>();
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
        public bool[] OcclusionPrepared = Array.Empty<bool>();
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

    private readonly record struct PaintProjectionFace(int A, int B, int C);

    private readonly record struct PaintProjectionEdge(
        int Id,
        int SubmeshIndex,
        int VertexA,
        int VertexB);

    private sealed record PaintProjectionSubmeshSnapshot(
        int Index,
        Vec3[] Vertices,
        PaintProjectionFace[] Faces,
        Matrix4x4 ModelMatrix);

    private sealed record PaintProjectionBuildSnapshot(
        Matrix4x4 Camera,
        int ViewportWidth,
        int ViewportHeight,
        bool BuiltForXRay,
        long GeometryRevision,
        int TopologyGeneration,
        int EditableSubmeshCount,
        int[] VisibleSubmeshIndices,
        PaintProjectionSubmeshSnapshot[] Submeshes,
        PaintProjectionEdge[] Edges);

    private readonly record struct PendingPaintSample(
        Point Start,
        Point End,
        double Radius,
        string Operation,
        string StrokeId);

    private const int PaintProjectionCellPixels = 16;
    private const int PaintProjectionMaximumFaceBucketCells = 16;
    private PaintProjectionCache? _paintProjection;
    private CancellationTokenSource? _paintProjectionBuildCancellation;
    private PaintProjectionBuildSnapshot? _paintProjectionBuildSnapshot;
    private long _paintProjectionBuildRequest;
    private long _paintProjectionGeometryRevision;
    private bool _paintProjectionBuildActive;
    private PendingPaintSample? _pendingPaintSample;
    private long _paintProjectionFirstDabStartedTicks;
    private bool _paintProjectionFirstDabMeasured;
    private bool _paintProjectionColdFirstDabRecorded;
    private int _paintProjectionBuildCount;
    private int _paintProjectionCacheHitCount;
    private int _paintProjectionInvalidationCount;
    private int _paintProjectionStaleBuildCount;
    private int _paintProjectionColdFirstDabCount;
    private int _paintProjectionWarmFirstDabCount;
    private double _paintProjectionLastColdFirstDabMs;
    private double _paintProjectionLastWarmFirstDabMs;
    private double _paintProjectionLastBuildMs;
    private string _paintProjectionLastInvalidation = string.Empty;

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
    /// The projection cache is resident across short gestures. Only geometry,
    /// topology, camera/model matrices, pane size, X-Ray, or selectable-part
    /// state can retire it. A build is cancelled cooperatively and its result
    /// is accepted only when the captured immutable snapshot is still current.
    /// </summary>
    private void InvalidatePaintProjectionCache(string reason, bool geometryChanged = false)
    {
        if (geometryChanged)
        {
            _paintProjectionGeometryRevision++;
        }
        _paintProjectionInvalidationCount++;
        _paintProjectionLastInvalidation = reason ?? string.Empty;
        _paintProjection = null;
        _paintProjectionBuildRequest++;
        _paintProjectionBuildCancellation?.Cancel();
        _paintProjectionBuildCancellation?.Dispose();
        _paintProjectionBuildCancellation = null;
        _paintProjectionBuildSnapshot = null;
        _paintProjectionBuildActive = false;
        _pendingPaintSample = null;
    }

    private PaintProjectionBuildSnapshot CapturePaintProjectionSnapshot(
        NetViewportCamera camera,
        Rectangle viewport)
    {
        var visible = VisibleEditableSubmeshIndices();
        var visibleSet = visible.ToHashSet();
        var submeshes = new List<PaintProjectionSubmeshSnapshot>(visible.Length);
        foreach (var submeshIndex in visible)
        {
            var source = _document.Submeshes[submeshIndex];
            var faces = source.Faces
                .Select(face => face.Corners.Length == 3
                    ? new PaintProjectionFace(
                        face.Corners[0].VertexIndex,
                        face.Corners[1].VertexIndex,
                        face.Corners[2].VertexIndex)
                    : new PaintProjectionFace(-1, -1, -1))
                .ToArray();
            submeshes.Add(new PaintProjectionSubmeshSnapshot(
                submeshIndex,
                source.Vertices.ToArray(),
                faces,
                ActiveSceneModelMatrix(submeshIndex)));
        }
        var edges = _edgeTopology.Edges
            .Where(edge => visibleSet.Contains(edge.SubmeshIndex))
            .Select(edge => new PaintProjectionEdge(edge.Id, edge.SubmeshIndex, edge.VertexA, edge.VertexB))
            .ToArray();
        return new PaintProjectionBuildSnapshot(
            camera.WorldViewProjection,
            Math.Max(1, viewport.Width),
            Math.Max(1, viewport.Height),
            ShowXRay,
            _paintProjectionGeometryRevision,
            _edgeTopology.Generation,
            Math.Clamp(_scene.EditableSubmeshCount, 0, _document.Submeshes.Count),
            visible,
            submeshes.ToArray(),
            edges);
    }

    private bool PaintProjectionViewMatches(PaintProjectionBuildSnapshot snapshot)
    {
        var liveViewport = ActivePaneBounds();
        if (snapshot.GeometryRevision != _paintProjectionGeometryRevision
            || snapshot.TopologyGeneration != _edgeTopology.Generation
            || snapshot.EditableSubmeshCount != Math.Clamp(_scene.EditableSubmeshCount, 0, _document.Submeshes.Count)
            || snapshot.BuiltForXRay != ShowXRay
            || snapshot.ViewportWidth != Math.Max(1, liveViewport.Width)
            || snapshot.ViewportHeight != Math.Max(1, liveViewport.Height)
            || !snapshot.Camera.Equals(CurrentCamera().WorldViewProjection))
        {
            return false;
        }
        var visible = VisibleEditableSubmeshIndices();
        if (!snapshot.VisibleSubmeshIndices.SequenceEqual(visible))
        {
            return false;
        }
        foreach (var submeshIndex in visible)
        {
            if (snapshot.Submeshes.FirstOrDefault(item => item.Index == submeshIndex) is not { } captured
                || !captured.ModelMatrix.Equals(ActiveSceneModelMatrix(submeshIndex)))
            {
                return false;
            }
        }
        return true;
    }

    private bool PaintProjectionCacheMatchesLive(PaintProjectionCache cache)
    {
        var viewport = ActivePaneBounds();
        if (cache.GeometryRevision != _paintProjectionGeometryRevision
            || cache.TopologyGeneration != _edgeTopology.Generation
            || cache.EditableSubmeshCount != Math.Clamp(_scene.EditableSubmeshCount, 0, _document.Submeshes.Count)
            || cache.BuiltForXRay != ShowXRay
            || cache.ViewportWidth != Math.Max(1, viewport.Width)
            || cache.ViewportHeight != Math.Max(1, viewport.Height)
            || !cache.Camera.Equals(CurrentCamera().WorldViewProjection))
        {
            return false;
        }
        var visible = VisibleEditableSubmeshIndices();
        return cache.VisibleSubmeshIndices.SequenceEqual(visible)
            && visible.All(index =>
                cache.ModelMatrices.TryGetValue(index, out var model)
                && model.Equals(ActiveSceneModelMatrix(index)));
    }

    private void InvalidatePaintProjectionCacheIfStale(string reason)
    {
        if (_paintProjection is { } cache && !PaintProjectionCacheMatchesLive(cache))
        {
            InvalidatePaintProjectionCache(reason);
            return;
        }
        if (_paintProjectionBuildActive
            && _paintProjectionBuildSnapshot is { } snapshot
            && !PaintProjectionViewMatches(snapshot))
        {
            InvalidatePaintProjectionCache(reason);
        }
    }

    private static PointF ProjectPaintPoint(
        Matrix4x4 camera,
        Matrix4x4 model,
        Vec3 vertex,
        float viewportWidth,
        float viewportHeight,
        out float depth)
    {
        var transformed = Vector3.Transform(new Vector3(vertex.X, vertex.Y, vertex.Z), model);
        var clip = Vector4.Transform(new Vector4(transformed, 1.0f), camera);
        if (Math.Abs(clip.W) > 0.000001f)
        {
            clip /= clip.W;
        }
        depth = clip.Z;
        return new PointF(
            (clip.X * 0.5f + 0.5f) * viewportWidth,
            (0.5f - clip.Y * 0.5f) * viewportHeight);
    }

    private static PaintProjectionCache BuildPaintProjectionCache(
        PaintProjectionBuildSnapshot snapshot,
        CancellationToken stopToken)
    {
        var cache = new PaintProjectionCache
        {
            Camera = snapshot.Camera,
            GridColumns = Math.Max(1, (snapshot.ViewportWidth + PaintProjectionCellPixels - 1) / PaintProjectionCellPixels),
            GridRows = Math.Max(1, (snapshot.ViewportHeight + PaintProjectionCellPixels - 1) / PaintProjectionCellPixels),
            ViewportWidth = snapshot.ViewportWidth,
            ViewportHeight = snapshot.ViewportHeight,
            BuiltForXRay = snapshot.BuiltForXRay,
            GeometryRevision = snapshot.GeometryRevision,
            TopologyGeneration = snapshot.TopologyGeneration,
            EditableSubmeshCount = snapshot.EditableSubmeshCount,
            VisibleSubmeshIndices = snapshot.VisibleSubmeshIndices,
            ModelMatrices = snapshot.Submeshes.ToDictionary(item => item.Index, item => item.ModelMatrix),
        };
        cache.Edges = snapshot.Edges;
        PreparePaintOcclusionGrid(cache);
        foreach (var snapshotSubmesh in snapshot.Submeshes)
        {
            stopToken.ThrowIfCancellationRequested();
            var points = new PointF[snapshotSubmesh.Vertices.Length];
            var depths = new float[snapshotSubmesh.Vertices.Length];
            var pendingVertexBuckets = new List<int>?[cache.GridColumns * cache.GridRows];
            var minX = float.PositiveInfinity;
            var minY = float.PositiveInfinity;
            var maxX = float.NegativeInfinity;
            var maxY = float.NegativeInfinity;
            for (var vertexIndex = 0; vertexIndex < points.Length; vertexIndex++)
            {
                if ((vertexIndex & 1023) == 0)
                {
                    stopToken.ThrowIfCancellationRequested();
                }
                points[vertexIndex] = ProjectPaintPoint(
                    snapshot.Camera,
                    snapshotSubmesh.ModelMatrix,
                    snapshotSubmesh.Vertices[vertexIndex],
                    snapshot.ViewportWidth,
                    snapshot.ViewportHeight,
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
            cache.Points[snapshotSubmesh.Index] = points;
            cache.Depths[snapshotSubmesh.Index] = depths;
            cache.VertexBuckets[snapshotSubmesh.Index] = pendingVertexBuckets
                .Select(bucket => bucket?.ToArray() ?? Array.Empty<int>())
                .ToArray();
            if (points.Length > 0)
            {
                cache.PartBounds[snapshotSubmesh.Index] = RectangleF.FromLTRB(minX, minY, maxX, maxY);
            }
            var faceBounds = new RectangleF[snapshotSubmesh.Faces.Length];
            var pendingFaceBuckets = new List<int>?[cache.GridColumns * cache.GridRows];
            var largeFaceCandidates = new List<int>();
            for (var faceIndex = 0; faceIndex < snapshotSubmesh.Faces.Length; faceIndex++)
            {
                if ((faceIndex & 1023) == 0)
                {
                    stopToken.ThrowIfCancellationRequested();
                }
                var face = snapshotSubmesh.Faces[faceIndex];
                var a = face.A;
                var b = face.B;
                var c = face.C;
                if (a < 0 || b < 0 || c < 0 || a >= points.Length || b >= points.Length || c >= points.Length)
                {
                    continue;
                }
                var faceLeft = MathF.Min(points[a].X, MathF.Min(points[b].X, points[c].X));
                var faceTop = MathF.Min(points[a].Y, MathF.Min(points[b].Y, points[c].Y));
                var faceRight = MathF.Max(points[a].X, MathF.Max(points[b].X, points[c].X));
                var faceBottom = MathF.Max(points[a].Y, MathF.Max(points[b].Y, points[c].Y));
                faceBounds[faceIndex] = RectangleF.FromLTRB(faceLeft, faceTop, faceRight, faceBottom);
                if (faceRight < 0.0f
                    || faceBottom < 0.0f
                    || faceLeft >= snapshot.ViewportWidth
                    || faceTop >= snapshot.ViewportHeight)
                {
                    continue;
                }
                _ = RoutePaintProjectionFaceCandidate(
                    pendingFaceBuckets,
                    largeFaceCandidates,
                    faceIndex,
                    cache.GridColumns,
                    Math.Clamp((int)MathF.Floor(faceLeft / PaintProjectionCellPixels), 0, cache.GridColumns - 1),
                    Math.Clamp((int)MathF.Floor(faceRight / PaintProjectionCellPixels), 0, cache.GridColumns - 1),
                    Math.Clamp((int)MathF.Floor(faceTop / PaintProjectionCellPixels), 0, cache.GridRows - 1),
                    Math.Clamp((int)MathF.Floor(faceBottom / PaintProjectionCellPixels), 0, cache.GridRows - 1));
            }
            cache.Faces[snapshotSubmesh.Index] = snapshotSubmesh.Faces;
            cache.FaceBuckets[snapshotSubmesh.Index] = pendingFaceBuckets
                .Select(bucket => bucket?.ToArray() ?? Array.Empty<int>())
                .ToArray();
            cache.LargeFaceCandidates[snapshotSubmesh.Index] = largeFaceCandidates.ToArray();
            cache.FaceQueryCandidates[snapshotSubmesh.Index] = new List<int>();
            cache.FaceVisitStamps[snapshotSubmesh.Index] = new int[snapshotSubmesh.Faces.Length];
            cache.FaceBounds[snapshotSubmesh.Index] = faceBounds;
        }
        BuildPaintEdgeBuckets(cache, snapshot.Edges);
        return cache;
    }

    private void QueuePaintProjectionPrewarm(NetViewportCamera? requestedCamera = null)
    {
        if (!IsHandleCreated
            || IsDisposed
            || Disposing
            || _document.Submeshes.Count == 0
            || !string.Equals(ActiveTool, "select", StringComparison.OrdinalIgnoreCase))
        {
            return;
        }
        var camera = requestedCamera ?? CurrentCamera();
        var viewport = ActivePaneBounds();
        var snapshot = CapturePaintProjectionSnapshot(camera, viewport);
        if (_paintProjection is { } cached && PaintProjectionCacheMatchesSnapshot(cached, snapshot))
        {
            return;
        }
        if (_paintProjectionBuildActive)
        {
            return;
        }
        StartPaintProjectionBuild(snapshot);
    }

    private bool PaintProjectionCacheMatchesSnapshot(
        PaintProjectionCache cache,
        PaintProjectionBuildSnapshot snapshot) =>
        cache.Camera.Equals(snapshot.Camera)
        && cache.ViewportWidth == snapshot.ViewportWidth
        && cache.ViewportHeight == snapshot.ViewportHeight
        && cache.BuiltForXRay == snapshot.BuiltForXRay
        && cache.GeometryRevision == snapshot.GeometryRevision
        && cache.TopologyGeneration == snapshot.TopologyGeneration
        && cache.EditableSubmeshCount == snapshot.EditableSubmeshCount
        && cache.VisibleSubmeshIndices.SequenceEqual(snapshot.VisibleSubmeshIndices)
        && snapshot.Submeshes.All(item =>
            cache.ModelMatrices.TryGetValue(item.Index, out var model)
            && model.Equals(item.ModelMatrix));

    private void StartPaintProjectionBuild(PaintProjectionBuildSnapshot snapshot)
    {
        _paintProjectionBuildCancellation?.Cancel();
        var cancellation = new CancellationTokenSource();
        var request = ++_paintProjectionBuildRequest;
        _paintProjectionBuildCancellation = cancellation;
        _paintProjectionBuildSnapshot = snapshot;
        _paintProjectionBuildActive = true;
        _paintProjectionBuildCount++;
        var started = Stopwatch.GetTimestamp();
        _ = Task.Run(
            () => BuildPaintProjectionCache(snapshot, cancellation.Token),
            cancellation.Token).ContinueWith(task =>
        {
            try
            {
                if (IsDisposed || request != _paintProjectionBuildRequest)
                {
                    return;
                }
                BeginInvoke(new Action(() =>
                    PublishPaintProjectionBuild(request, snapshot, task, started)));
            }
            catch (InvalidOperationException)
            {
                // The form is closing; the owner will dispose the cancellation
                // source and no late cache may be published into a dead handle.
            }
        }, CancellationToken.None, TaskContinuationOptions.None, TaskScheduler.Default);
    }

    private void PublishPaintProjectionBuild(
        long request,
        PaintProjectionBuildSnapshot snapshot,
        Task<PaintProjectionCache> task,
        long started)
    {
        if (request != _paintProjectionBuildRequest)
        {
            return;
        }
        _paintProjectionBuildActive = false;
        _paintProjectionBuildCancellation?.Dispose();
        _paintProjectionBuildCancellation = null;
        _paintProjectionBuildSnapshot = null;
        if (task.IsCanceled || task.IsFaulted || !PaintProjectionViewMatches(snapshot))
        {
            _paintProjectionStaleBuildCount++;
            _paintProjectionLastInvalidation = task.IsFaulted ? "build_failed" : "stale_build";
            return;
        }
        _paintProjection = task.Result;
        var elapsedMs = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
        _paintProjectionLastBuildMs = Math.Max(0.0, elapsedMs);
        if (!_paintProjectionFirstDabMeasured && _paintProjectionFirstDabStartedTicks > 0)
        {
            _paintProjectionLastColdFirstDabMs = Math.Max(
                0.0,
                Stopwatch.GetElapsedTime(_paintProjectionFirstDabStartedTicks).TotalMilliseconds);
            _paintProjectionFirstDabMeasured = true;
        }
        var pending = _pendingPaintSample;
        _pendingPaintSample = null;
        if (pending is { } sample
            && _edgeDragActive
            && string.Equals(sample.StrokeId, _selectionStrokeId, StringComparison.Ordinal))
        {
            UpdateProvisionalPaintHits(sample.Start, sample.End, sample.Radius, sample.Operation);
        }
    }

    private PaintProjectionCache? EnsurePaintProjectionCache(NetViewportCamera camera)
    {
        if (_paintProjection is { } cached)
        {
            if (PaintProjectionCacheMatchesLive(cached))
            {
                _paintProjectionCacheHitCount++;
                return cached;
            }
            InvalidatePaintProjectionCache("projection_key_changed");
        }
        if (!_paintProjectionBuildActive)
        {
            StartPaintProjectionBuild(CapturePaintProjectionSnapshot(camera, ActivePaneBounds()));
        }
        return null;
    }

    internal Dictionary<string, object?> PaintProjectionDiagnosticsPayload()
    {
        return new Dictionary<string, object?>
        {
            ["build_count"] = _paintProjectionBuildCount,
            ["cache_hits"] = _paintProjectionCacheHitCount,
            ["invalidation_count"] = _paintProjectionInvalidationCount,
            ["stale_build_count"] = _paintProjectionStaleBuildCount,
            ["cold_first_dab_count"] = _paintProjectionColdFirstDabCount,
            ["warm_first_dab_count"] = _paintProjectionWarmFirstDabCount,
            ["cold_first_dab_ms"] = _paintProjectionLastColdFirstDabMs,
            ["warm_first_dab_ms"] = _paintProjectionLastWarmFirstDabMs,
            ["last_build_ms"] = _paintProjectionLastBuildMs,
            ["build_active"] = _paintProjectionBuildActive,
            ["pending_sample"] = _pendingPaintSample is not null,
            ["retained"] = _paintProjection is not null,
            ["last_invalidation"] = _paintProjectionLastInvalidation,
        };
    }

    private void BeginPaintProjectionGesture()
    {
        _pendingPaintSample = null;
        _paintProjectionFirstDabStartedTicks = Stopwatch.GetTimestamp();
        _paintProjectionFirstDabMeasured = false;
        _paintProjectionColdFirstDabRecorded = false;
        QueuePaintProjectionPrewarm();
    }

    private void EndPaintProjectionGesture()
    {
        _pendingPaintSample = null;
        _paintProjectionFirstDabStartedTicks = 0;
        _paintProjectionFirstDabMeasured = false;
        _paintProjectionColdFirstDabRecorded = false;
    }

    private void CancelPaintProjectionBuild()
    {
        _paintProjectionBuildRequest++;
        _paintProjectionBuildCancellation?.Cancel();
        _paintProjectionBuildCancellation?.Dispose();
        _paintProjectionBuildCancellation = null;
        _paintProjectionBuildSnapshot = null;
        _paintProjectionBuildActive = false;
        _pendingPaintSample = null;
    }

}
