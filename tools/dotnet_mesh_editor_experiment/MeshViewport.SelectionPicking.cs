using System.Drawing;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private const double SelectionClickRadiusPixels = 14.0;
    private const int SelectionRegionTolerancePixels = 6;
    private const double SelectionPaintSampleIntervalMs = 30.0;
    private const int SelectionPaintSampleMinimumStepPixels = 3;

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
        public Dictionary<int, PointF[]> Points { get; } = new();
        public Dictionary<int, bool[]> FrontFacingVertices { get; } = new();
        public Dictionary<int, RectangleF> PartBounds { get; } = new();
        public Dictionary<int, int[][]> VertexBuckets { get; } = new();
    }

    private const int PaintProjectionCellPixels = 32;
    private PaintProjectionCache? _paintProjection;

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
            for (var vertexIndex = 0; vertexIndex < points.Length; vertexIndex++)
            {
                points[vertexIndex] = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
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
                var minX = points.Min(point => point.X);
                var minY = points.Min(point => point.Y);
                var maxX = points.Max(point => point.X);
                var maxY = points.Max(point => point.Y);
                cache.PartBounds[submeshIndex] = RectangleF.FromLTRB(minX, minY, maxX, maxY);
            }
            var frontFacing = new bool[submesh.Vertices.Count];
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
            }
            cache.FrontFacingVertices[submeshIndex] = frontFacing;
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
                if (!_provisionalSelectedFaces.TryGetValue(submeshIndex, out var selectedFaces))
                {
                    selectedFaces = new HashSet<int>();
                    if (operation != "subtract")
                    {
                        _provisionalSelectedFaces[submeshIndex] = selectedFaces;
                    }
                }
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

    private void ClearProvisionalSelectionEcho()
    {
        _provisionalSelectedVertices.Clear();
        _provisionalSelectedFaces.Clear();
        _provisionalSelectedEdges.Clear();
        _provisionalSelectedSources.Clear();
        _provisionalPartSelectionActive = false;
    }

    private static bool SweptBandIntersectsTriangle(
        Point start,
        Point end,
        double radius,
        PointF a,
        PointF b,
        PointF c)
    {
        if (SelectionPointInTriangle(start, a, b, c) || SelectionPointInTriangle(end, a, b, c))
        {
            return true;
        }
        var radiusSquared = radius * radius;
        return SegmentDistanceSquared(start, end, a, a) <= radiusSquared
            || SegmentDistanceSquared(start, end, b, b) <= radiusSquared
            || SegmentDistanceSquared(start, end, c, c) <= radiusSquared
            || SegmentDistanceSquared(start, end, a, b) <= radiusSquared
            || SegmentDistanceSquared(start, end, b, c) <= radiusSquared
            || SegmentDistanceSquared(start, end, c, a) <= radiusSquared;
    }

    private static bool SelectionPointInTriangle(Point point, PointF a, PointF b, PointF c)
    {
        static float Sign(float px, float py, PointF first, PointF second) =>
            (px - second.X) * (first.Y - second.Y) - (first.X - second.X) * (py - second.Y);
        var d1 = Sign(point.X, point.Y, a, b);
        var d2 = Sign(point.X, point.Y, b, c);
        var d3 = Sign(point.X, point.Y, c, a);
        var hasNegative = d1 < 0.0f || d2 < 0.0f || d3 < 0.0f;
        var hasPositive = d1 > 0.0f || d2 > 0.0f || d3 > 0.0f;
        return !(hasNegative && hasPositive);
    }

    private static double SegmentDistanceSquared(Point firstStart, Point firstEnd, PointF secondStart, PointF secondEnd)
    {
        if (SelectionSegmentsIntersect(firstStart, firstEnd, secondStart, secondEnd))
        {
            return 0.0;
        }
        return Math.Min(
            Math.Min(PointSegmentDistanceSquared(firstStart.X, firstStart.Y, secondStart, secondEnd),
                PointSegmentDistanceSquared(firstEnd.X, firstEnd.Y, secondStart, secondEnd)),
            Math.Min(PointSegmentDistanceSquared(secondStart.X, secondStart.Y, firstStart, firstEnd),
                PointSegmentDistanceSquared(secondEnd.X, secondEnd.Y, firstStart, firstEnd)));
    }

    private static double PointSegmentDistanceSquared(float x, float y, PointF start, PointF end)
    {
        var dx = end.X - start.X;
        var dy = end.Y - start.Y;
        var lengthSquared = dx * dx + dy * dy;
        var t = lengthSquared <= 0.000001f
            ? 0.0f
            : Math.Clamp(((x - start.X) * dx + (y - start.Y) * dy) / lengthSquared, 0.0f, 1.0f);
        var nearestX = start.X + t * dx;
        var nearestY = start.Y + t * dy;
        var deltaX = x - nearestX;
        var deltaY = y - nearestY;
        return deltaX * deltaX + deltaY * deltaY;
    }

    internal static bool SelectionSegmentsIntersect(PointF a, PointF b, PointF c, PointF d)
    {
        static float Cross(PointF first, PointF second, PointF third) =>
            (second.X - first.X) * (third.Y - first.Y) - (second.Y - first.Y) * (third.X - first.X);
        static bool OnSegment(PointF point, PointF start, PointF end) =>
            point.X >= Math.Min(start.X, end.X) - 0.00001f
            && point.X <= Math.Max(start.X, end.X) + 0.00001f
            && point.Y >= Math.Min(start.Y, end.Y) - 0.00001f
            && point.Y <= Math.Max(start.Y, end.Y) + 0.00001f;
        var abC = Cross(a, b, c);
        var abD = Cross(a, b, d);
        var cdA = Cross(c, d, a);
        var cdB = Cross(c, d, b);
        if (Math.Sign(abC) != Math.Sign(abD) && Math.Sign(cdA) != Math.Sign(cdB))
        {
            return true;
        }
        return (Math.Abs(abC) <= 0.00001f && OnSegment(c, a, b))
            || (Math.Abs(abD) <= 0.00001f && OnSegment(d, a, b))
            || (Math.Abs(cdA) <= 0.00001f && OnSegment(a, c, d))
            || (Math.Abs(cdB) <= 0.00001f && OnSegment(b, c, d));
    }

    private (int SubmeshIndex, int ItemIndex)? PickVertexAt(Point point)
    {
        var camera = CurrentCamera();
        var bestDistance = SelectionClickRadiusPixels;
        (int SubmeshIndex, int ItemIndex)? best = null;
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount; submeshIndex++)
        {
            if (!IsSubmeshVisibleForViewportSelection(submeshIndex))
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            for (var vertexIndex = 0; vertexIndex < submesh.Vertices.Count; vertexIndex++)
            {
                if (!ShowXRay && !IsVertexFrontFacing(submeshIndex, vertexIndex, camera))
                {
                    continue;
                }
                var projected = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
                var dx = point.X - projected.X;
                var dy = point.Y - projected.Y;
                var distance = Math.Sqrt((dx * dx) + (dy * dy));
                if (distance < bestDistance
                    && (ShowXRay
                        || !IsWorldPointOccluded(
                            point,
                            SceneWorldPoint(submeshIndex, submesh.Vertices[vertexIndex]))))
                {
                    bestDistance = distance;
                    best = (submeshIndex, vertexIndex);
                }
            }
        }
        return best;
    }

    private (int SubmeshIndex, int ItemIndex)? PickFaceAt(Point point)
    {
        if (!ShowXRay)
        {
            return TryNearestVisibleSurface(point, out _, out var visibleSubmesh, out var visibleFace)
                ? (visibleSubmesh, visibleFace)
                : null;
        }
        var camera = CurrentCamera();
        var bestScore = double.MaxValue;
        (int SubmeshIndex, int ItemIndex)? best = null;
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount; submeshIndex++)
        {
            if (!IsSubmeshVisibleForViewportSelection(submeshIndex))
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                if (!ShowXRay && !IsFaceFrontFacing(submeshIndex, faceIndex, camera))
                {
                    continue;
                }
                var face = submesh.Faces[faceIndex];
                if (face.Corners.Length != 3)
                {
                    continue;
                }
                var points = new PointF[3];
                var valid = true;
                for (var cornerIndex = 0; cornerIndex < 3; cornerIndex++)
                {
                    var vertexIndex = face.Corners[cornerIndex].VertexIndex;
                    if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
                    {
                        valid = false;
                        break;
                    }
                    points[cornerIndex] = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
                }
                if (!valid || !PointInTriangle(point, points[0], points[1], points[2]))
                {
                    continue;
                }
                var centerX = (points[0].X + points[1].X + points[2].X) / 3.0;
                var centerY = (points[0].Y + points[1].Y + points[2].Y) / 3.0;
                var score = Math.Pow(point.X - centerX, 2.0) + Math.Pow(point.Y - centerY, 2.0);
                if (score < bestScore)
                {
                    bestScore = score;
                    best = (submeshIndex, faceIndex);
                }
            }
        }
        return best;
    }

    private bool IsVertexFrontFacing(int submeshIndex, int vertexIndex, NetViewportCamera camera)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count || vertexIndex < 0)
        {
            return false;
        }
        var submesh = _document.Submeshes[submeshIndex];
        if (vertexIndex >= submesh.Vertices.Count)
        {
            return false;
        }
        for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
        {
            var face = submesh.Faces[faceIndex];
            if (face.Corners.Any(corner => corner.VertexIndex == vertexIndex)
                && IsFaceFrontFacing(submeshIndex, faceIndex, camera))
            {
                return true;
            }
        }
        return false;
    }

    private void BeginEdgeDrag(Point point)
    {
        BeginSelectionDrag(point, "edge");
    }

    private void FinishEdgeDrag(Point point)
    {
        _edgeDragCurrent = point;
        var rectangle = EdgeDragRectangle();
        var targetMode = _selectionDragTargetMode;
        _edgeDragActive = false;
        var paintActive = _selectionPaintActive;
        var paintPainted = _selectionPaintPainted;
        _selectionPaintActive = false;
        var simplifiedLasso = _selectionLassoPoints.Count >= 3
            ? SimplifyLassoPoints(_selectionLassoPoints)
            : Array.Empty<Point>();
        var lassoPoints = simplifiedLasso.Length >= 3 ? simplifiedLasso : null;
        _selectionLassoPoints.Clear();
        var draggedBeyondClick = rectangle.Width >= 4 || rectangle.Height >= 4;
        if (paintActive && (paintPainted || draggedBeyondClick))
        {
            // The drag painted (or moved far enough that it should have): the
            // final dab closes the sweep. A plain click falls through to the
            // precise 14px click pick below instead of a full-radius dab.
            MaybeEmitSelectionPaintSample(point, final: true);
            StatusRequested?.Invoke($"{targetMode} selection awaiting authoritative depth-resolved result.");
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        var payload = new Dictionary<string, object?>
        {
            ["operation"] = CurrentSelectionOperation(),
            ["target_mode"] = targetMode,
            ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
        };
        if (_options.SimplePreview && targetMode is "source" or "part")
        {
            int[] sourceIndices;
            if (rectangle.Width < 4 && rectangle.Height < 4)
            {
                var sourceIndex = PickPartAt(point);
                sourceIndices = sourceIndex >= 0 ? new[] { sourceIndex } : Array.Empty<int>();
            }
            else
            {
                sourceIndices = PartIdsInRectangle(rectangle);
            }
            payload["source_indices"] = sourceIndices;
            payload["sources"] = sourceIndices;
            payload["active_pane"] = ActivePresentationPane;
            payload["hit"] = sourceIndices.Length > 0;
            EditorEventRequested?.Invoke("part_pick_result", payload);
            StatusRequested?.Invoke(sourceIndices.Length > 0
                ? $"Preview part pick: {string.Join(", ", sourceIndices)}"
                : "Preview part pick: no hit.");
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        if (rectangle.Width < 4 && rectangle.Height < 4)
        {
            var clickOperation = CurrentSelectionOperation();
            if (clickOperation == "replace")
            {
                ClearProvisionalSelectionEcho();
            }
            UpdateProvisionalPaintHits(point, point, SelectionClickRadiusPixels, clickOperation);
            payload["screen_brush"] = ScreenPayload(point, SelectionClickRadiusPixels);
            EmitSelectionRequest(payload, "end");
            StatusRequested?.Invoke($"{targetMode} selection awaiting authoritative depth-resolved result.");
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        var region = ScreenDragPayload(_edgeDragStart, point);
        if (lassoPoints is not null)
        {
            // Native screen selection reads mode "lasso" plus the swept
            // polygon; the rectangle endpoints stay in the payload as the
            // fallback older cores use.
            region["mode"] = "lasso";
            // Both spellings: the native reader accepts either key, and the
            // redundancy survives any intermediate that strips one of them.
            region["selection_mode"] = "lasso";
            region["points"] = lassoPoints
                .Select(lassoPoint => new[] { (double)lassoPoint.X, (double)lassoPoint.Y })
                .ToArray();
        }
        UpdateProvisionalRegionHits(lassoPoints, rectangle, CurrentSelectionOperation());
        payload["screen_region"] = region;
        EmitSelectionRequest(payload, "end");
        StatusRequested?.Invoke($"{targetMode} region selection awaiting authoritative depth-resolved result.");
        _hoverEdgeId = -1;
        UpdateGpuViewport();
        Invalidate();
    }

    private static Point[] SimplifyLassoPoints(IReadOnlyList<Point> points)
    {
        var simplified = new List<Point>(points.Count);
        foreach (var point in points)
        {
            if (simplified.Count > 0)
            {
                var previous = simplified[^1];
                var dx = point.X - previous.X;
                var dy = point.Y - previous.Y;
                if (dx * dx + dy * dy <= 4)
                {
                    continue;
                }
            }
            while (simplified.Count >= 2)
            {
                var first = simplified[^2];
                var second = simplified[^1];
                var cross = (second.X - first.X) * (point.Y - second.Y)
                    - (second.Y - first.Y) * (point.X - second.X);
                if (Math.Abs(cross) > 2)
                {
                    break;
                }
                simplified.RemoveAt(simplified.Count - 1);
            }
            simplified.Add(point);
        }
        if (simplified.Count >= 3)
        {
            return simplified.ToArray();
        }
        return points.Distinct().ToArray();
    }

    private void UpdateProvisionalRegionHits(
        IReadOnlyList<Point>? lassoPoints,
        Rectangle rectangle,
        string operation)
    {
        if (operation == "replace")
        {
            ClearProvisionalSelectionEcho();
        }
        var polygon = lassoPoints is { Count: >= 3 }
            ? lassoPoints
            : new[]
            {
                new Point(rectangle.Left, rectangle.Top),
                new Point(rectangle.Right, rectangle.Top),
                new Point(rectangle.Right, rectangle.Bottom),
                new Point(rectangle.Left, rectangle.Bottom),
            };
        var bounds = RectangleF.FromLTRB(
            polygon.Min(point => point.X),
            polygon.Min(point => point.Y),
            polygon.Max(point => point.X),
            polygon.Max(point => point.Y));
        var cache = EnsurePaintProjectionCache(CurrentCamera());
        if (_selectionDragTargetMode == "edge")
        {
            foreach (var edge in _edgeTopology.Edges)
            {
                if (!cache.Points.TryGetValue(edge.SubmeshIndex, out var points)
                    || !cache.PartBounds.TryGetValue(edge.SubmeshIndex, out var partBounds)
                    || !partBounds.IntersectsWith(bounds)
                    || edge.VertexA < 0
                    || edge.VertexA >= points.Length
                    || edge.VertexB < 0
                    || edge.VertexB >= points.Length
                    || (!ShowXRay
                        && !cache.FrontFacingVertices[edge.SubmeshIndex][edge.VertexA]
                        && !cache.FrontFacingVertices[edge.SubmeshIndex][edge.VertexB])
                    || !SelectionPolygonIntersectsSegment(polygon, points[edge.VertexA], points[edge.VertexB]))
                {
                    continue;
                }
                ApplyProvisionalHit(_provisionalSelectedEdges, edge.Id, operation, _selectionPaintToggleTouchedEdges);
            }
        }
        else
        {
            foreach (var pair in cache.Points)
            {
                var submeshIndex = pair.Key;
                var points = pair.Value;
                if (!cache.PartBounds.TryGetValue(submeshIndex, out var partBounds)
                    || !partBounds.IntersectsWith(bounds))
                {
                    continue;
                }
                var frontFacing = cache.FrontFacingVertices[submeshIndex];
                if (_selectionDragTargetMode == "face")
                {
                    var submesh = _document.Submeshes[submeshIndex];
                    if (!_provisionalSelectedFaces.TryGetValue(submeshIndex, out var selectedFaces))
                    {
                        selectedFaces = new HashSet<int>();
                        if (operation != "subtract")
                        {
                            _provisionalSelectedFaces[submeshIndex] = selectedFaces;
                        }
                    }
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
                        if (a < 0 || b < 0 || c < 0 || a >= points.Length || b >= points.Length || c >= points.Length
                            || (!ShowXRay && !frontFacing[a] && !frontFacing[b] && !frontFacing[c])
                            || !SelectionPolygonIntersectsTriangle(polygon, points[a], points[b], points[c]))
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
                if (!_provisionalSelectedVertices.TryGetValue(submeshIndex, out var selectedVertices))
                {
                    selectedVertices = new HashSet<int>();
                    if (operation != "subtract")
                    {
                        _provisionalSelectedVertices[submeshIndex] = selectedVertices;
                    }
                }
                for (var vertexIndex = 0; vertexIndex < points.Length; vertexIndex++)
                {
                    if ((!ShowXRay && !frontFacing[vertexIndex])
                        || !SelectionPointInPolygon(points[vertexIndex], polygon))
                    {
                        continue;
                    }
                    ApplyProvisionalHit(
                        selectedVertices,
                        vertexIndex,
                        operation,
                        _selectionPaintToggleTouchedVertices,
                        (submeshIndex, vertexIndex));
                }
                if (selectedVertices.Count == 0)
                {
                    _provisionalSelectedVertices.Remove(submeshIndex);
                }
            }
        }
        _provisionalPartSelectionActive = false;
        UpdateGpuViewport();
        Invalidate();
    }

    private static bool SelectionPolygonIntersectsTriangle(
        IReadOnlyList<Point> polygon,
        PointF a,
        PointF b,
        PointF c)
    {
        var center = new PointF((a.X + b.X + c.X) / 3.0f, (a.Y + b.Y + c.Y) / 3.0f);
        if (SelectionPointInPolygon(a, polygon)
            || SelectionPointInPolygon(b, polygon)
            || SelectionPointInPolygon(c, polygon)
            || SelectionPointInPolygon(center, polygon))
        {
            return true;
        }
        foreach (var point in polygon)
        {
            if (SelectionPointInTriangle(point, a, b, c))
            {
                return true;
            }
        }
        return SelectionPolygonIntersectsSegment(polygon, a, b)
            || SelectionPolygonIntersectsSegment(polygon, b, c)
            || SelectionPolygonIntersectsSegment(polygon, c, a);
    }

    private static bool SelectionPolygonIntersectsSegment(
        IReadOnlyList<Point> polygon,
        PointF start,
        PointF end)
    {
        if (SelectionPointInPolygon(start, polygon) || SelectionPointInPolygon(end, polygon))
        {
            return true;
        }
        for (var index = 0; index < polygon.Count; index++)
        {
            var first = polygon[index];
            var second = polygon[(index + 1) % polygon.Count];
            if (SelectionSegmentsIntersect(start, end, first, second))
            {
                return true;
            }
        }
        return false;
    }

    private static bool SelectionPointInPolygon(PointF point, IReadOnlyList<Point> polygon)
    {
        var inside = false;
        for (var index = 0; index < polygon.Count; index++)
        {
            var first = polygon[index];
            var second = polygon[(index + polygon.Count - 1) % polygon.Count];
            if ((first.Y > point.Y) != (second.Y > point.Y)
                && point.X < (second.X - first.X) * (point.Y - first.Y)
                    / (second.Y - first.Y) + first.X)
            {
                inside = !inside;
            }
        }
        return inside;
    }

    private Rectangle EdgeDragRectangle()
    {
        var left = Math.Min(_edgeDragStart.X, _edgeDragCurrent.X);
        var top = Math.Min(_edgeDragStart.Y, _edgeDragCurrent.Y);
        var right = Math.Max(_edgeDragStart.X, _edgeDragCurrent.X);
        var bottom = Math.Max(_edgeDragStart.Y, _edgeDragCurrent.Y);
        return Rectangle.FromLTRB(left, top, right, bottom);
    }

    private (int SubmeshIndex, int ItemIndex)[] VertexIdsInRectangle(Rectangle rectangle)
    {
        var camera = CurrentCamera();
        var expanded = Rectangle.Inflate(rectangle, SelectionRegionTolerancePixels, SelectionRegionTolerancePixels);
        var result = new List<(int SubmeshIndex, int ItemIndex)>();
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount; submeshIndex++)
        {
            if (!IsSubmeshVisibleForViewportSelection(submeshIndex))
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            for (var vertexIndex = 0; vertexIndex < submesh.Vertices.Count; vertexIndex++)
            {
                if (!ShowXRay && !IsVertexFrontFacing(submeshIndex, vertexIndex, camera))
                {
                    continue;
                }
                var point = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
                if (expanded.Contains(Point.Round(point)))
                {
                    result.Add((submeshIndex, vertexIndex));
                }
            }
        }
        return result.OrderBy(hit => hit.SubmeshIndex).ThenBy(hit => hit.ItemIndex).ToArray();
    }

    private (int SubmeshIndex, int ItemIndex)[] FaceIdsInRectangle(Rectangle rectangle)
    {
        var camera = CurrentCamera();
        var expanded = Rectangle.Inflate(rectangle, SelectionRegionTolerancePixels, SelectionRegionTolerancePixels);
        var result = new List<(int SubmeshIndex, int ItemIndex)>();
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount; submeshIndex++)
        {
            if (!IsSubmeshVisibleForViewportSelection(submeshIndex))
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                if (!ShowXRay && !IsFaceFrontFacing(submeshIndex, faceIndex, camera))
                {
                    continue;
                }
                if (FaceIntersectsRectangle(submeshIndex, submesh, submesh.Faces[faceIndex], expanded, camera))
                {
                    result.Add((submeshIndex, faceIndex));
                }
            }
        }
        return result.OrderBy(hit => hit.SubmeshIndex).ThenBy(hit => hit.ItemIndex).ToArray();
    }

    private int[] PartIdsInRectangle(Rectangle rectangle)
    {
        return FaceIdsInRectangle(rectangle)
            .Select(hit => hit.SubmeshIndex)
            .Distinct()
            .OrderBy(index => index)
            .ToArray();
    }

    private bool FaceIntersectsRectangle(int submeshIndex, ObjSubmesh submesh, ObjFace face, Rectangle rectangle, NetViewportCamera camera)
    {
        if (face.Corners.Length != 3)
        {
            return false;
        }
        var points = new PointF[3];
        for (var i = 0; i < 3; i++)
        {
            var vertexIndex = face.Corners[i].VertexIndex;
            if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
            {
                return false;
            }
            points[i] = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
        }
        var center = new PointF((points[0].X + points[1].X + points[2].X) / 3.0f, (points[0].Y + points[1].Y + points[2].Y) / 3.0f);
        return rectangle.Contains(Point.Round(points[0]))
            || rectangle.Contains(Point.Round(points[1]))
            || rectangle.Contains(Point.Round(points[2]))
            || rectangle.Contains(Point.Round(center))
            || SegmentIntersectsRectangle(points[0], points[1], rectangle)
            || SegmentIntersectsRectangle(points[1], points[2], rectangle)
            || SegmentIntersectsRectangle(points[2], points[0], rectangle);
    }

    private int[] EdgeIdsInRectangle(Rectangle rectangle)
    {
        var camera = CurrentCamera();
        var expanded = Rectangle.Inflate(rectangle, SelectionRegionTolerancePixels, SelectionRegionTolerancePixels);
        var result = new List<int>();
        foreach (var edge in _edgeTopology.Edges)
        {
            if (!IsSubmeshVisibleForViewportSelection(edge.SubmeshIndex))
            {
                continue;
            }
            if (!ShowXRay && !IsEdgeFrontFacing(edge, camera))
            {
                continue;
            }
            if (edge.SubmeshIndex < 0 || edge.SubmeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[edge.SubmeshIndex];
            if (edge.VertexA < 0 || edge.VertexA >= submesh.Vertices.Count || edge.VertexB < 0 || edge.VertexB >= submesh.Vertices.Count)
            {
                continue;
            }
            var a = SceneProjectedPoint(camera, edge.SubmeshIndex, submesh.Vertices[edge.VertexA]);
            var b = SceneProjectedPoint(camera, edge.SubmeshIndex, submesh.Vertices[edge.VertexB]);
            var midpoint = new PointF((a.X + b.X) * 0.5f, (a.Y + b.Y) * 0.5f);
            if (expanded.Contains(Point.Round(a)) || expanded.Contains(Point.Round(b)) || expanded.Contains(Point.Round(midpoint)) || SegmentIntersectsRectangle(a, b, expanded))
            {
                result.Add(edge.Id);
            }
        }
        return result.OrderBy(edgeId => edgeId).ToArray();
    }

    private void UpdateHoverEdge(Point point)
    {
        var edgeId = PickEdgeAt(point);
        if (edgeId == _hoverEdgeId)
        {
            return;
        }
        _hoverEdgeId = edgeId;
        StatusRequested?.Invoke($"Edge mode: selected={_selectedEdges.Count} hover={(edgeId >= 0 ? 1 : 0)} xray={(ShowXRay ? "on" : "off")}");
        UpdateGpuViewport();
        Invalidate();
    }

    private int PickEdgeAt(Point point)
    {
        var camera = CurrentCamera();
        var bestEdgeId = -1;
        var bestDistance = SelectionClickRadiusPixels;
        foreach (var edge in _edgeTopology.Edges)
        {
            if (!IsSubmeshVisibleForViewportSelection(edge.SubmeshIndex))
            {
                continue;
            }
            if (!ShowXRay && !IsEdgeFrontFacing(edge, camera))
            {
                continue;
            }
            if (edge.SubmeshIndex < 0 || edge.SubmeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[edge.SubmeshIndex];
            if (edge.VertexA < 0 || edge.VertexA >= submesh.Vertices.Count || edge.VertexB < 0 || edge.VertexB >= submesh.Vertices.Count)
            {
                continue;
            }
            var a = SceneProjectedPoint(camera, edge.SubmeshIndex, submesh.Vertices[edge.VertexA]);
            var b = SceneProjectedPoint(camera, edge.SubmeshIndex, submesh.Vertices[edge.VertexB]);
            var distance = DistanceToSegment(point, a, b);
            var edgePoint = Vector3.Lerp(
                SceneWorldPoint(edge.SubmeshIndex, submesh.Vertices[edge.VertexA]),
                SceneWorldPoint(edge.SubmeshIndex, submesh.Vertices[edge.VertexB]),
                ScreenSegmentParameter(point, a, b));
            if (distance < bestDistance && (ShowXRay || !IsWorldPointOccluded(point, edgePoint)))
            {
                bestDistance = distance;
                bestEdgeId = edge.Id;
            }
        }
        return bestEdgeId;
    }

    private bool IsSubmeshVisibleForViewportSelection(int submeshIndex)
    {
        return submeshIndex >= 0
            && submeshIndex < _document.Submeshes.Count
            && IsSelectableGeometryLayerSubmesh(submeshIndex)
            && ActivePaneIncludesForPicking(submeshIndex)
            && _materials.ParametersForSubmesh(submeshIndex).Visible is not false;
    }

    private bool IsEdgeFrontFacing(NetEdge edge, NetViewportCamera camera)
    {
        if (edge.AdjacentFaces.Count == 0)
        {
            return true;
        }
        foreach (var faceIndex in edge.AdjacentFaces)
        {
            if (IsFaceFrontFacing(edge.SubmeshIndex, faceIndex, camera))
            {
                return true;
            }
        }
        return false;
    }

    private bool IsFaceFrontFacing(int submeshIndex, int faceIndex, NetViewportCamera camera)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return false;
        }
        var submesh = _document.Submeshes[submeshIndex];
        if (faceIndex < 0 || faceIndex >= submesh.Faces.Count)
        {
            return false;
        }
        var face = submesh.Faces[faceIndex];
        if (face.Corners.Length != 3)
        {
            return false;
        }
        var points = new PointF[3];
        for (var i = 0; i < 3; i++)
        {
            var vertexIndex = face.Corners[i].VertexIndex;
            if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
            {
                return false;
            }
            points[i] = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
        }
        var area = ((points[1].X - points[0].X) * (points[2].Y - points[0].Y)) - ((points[1].Y - points[0].Y) * (points[2].X - points[0].X));
        return area < -0.01f;
    }

    /// <summary>
    /// Edit Mesh viewport selection paints vertices. Whole-part selection is a
    /// separate explicit action from the PARTS list.
    /// </summary>
    internal string CurrentTargetMode()
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        return options.TryGetValue("target_mode", out var value)
            ? (value?.ToString() ?? "vertex").Trim().ToLowerInvariant()
            : "vertex";
    }

    private string CurrentSelectionOperation()
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        return options.TryGetValue("operation", out var value)
            ? (value?.ToString() ?? "add").Trim().ToLowerInvariant()
            : "add";
    }
}
