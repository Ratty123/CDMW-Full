using System.Drawing;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private const double SelectionClickRadiusPixels = 14.0;
    private const int SelectionRegionTolerancePixels = 6;
    private const double SelectionPaintSampleIntervalMs = 30.0;
    private const int SelectionPaintSampleMinimumStepPixels = 3;

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
        var now = Environment.TickCount64;
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
            _provisionalSelectedVertices.Clear();
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
        EditorEventRequested?.Invoke("select_request", payload);
        _selectionPaintPainted = true;
        _selectionPaintLastSample = point;
        _selectionPaintLastEcho = point;
        _selectionPaintLastSampleTicks = now;
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
        EditorEventRequested?.Invoke("select_request", new Dictionary<string, object?>
        {
            ["operation"] = operation,
            ["target_mode"] = _selectionDragTargetMode,
            ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
            ["paint_sample"] = true,
            ["paint_final"] = false,
            ["screen_region"] = region,
        });
    }

    private double SelectionPaintRadiusPixels()
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        return Math.Clamp(NumberOption(options, "radius", 24.0), 2.0, 256.0);
    }

    private const int ProvisionalSelectionVertexBudget = 200_000;

    private bool ProvisionalSelectionAffordable()
    {
        var total = 0;
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount && submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            total += _document.Submeshes[submeshIndex].Vertices.Count;
            if (total > ProvisionalSelectionVertexBudget)
            {
                return false;
            }
        }
        return true;
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
        public Dictionary<int, PointF[]> Points { get; } = new();
        public Dictionary<int, bool[]> FrontFacing { get; } = new();
    }

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
        var cache = new PaintProjectionCache { Camera = camera.WorldViewProjection };
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount && submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            if (!IsSubmeshVisibleForViewportSelection(submeshIndex))
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            var points = new PointF[submesh.Vertices.Count];
            for (var vertexIndex = 0; vertexIndex < points.Length; vertexIndex++)
            {
                points[vertexIndex] = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
            }
            cache.Points[submeshIndex] = points;
            var frontFacing = new bool[points.Length];
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
                if (area >= -0.01f)
                {
                    continue;
                }
                frontFacing[a] = true;
                frontFacing[b] = true;
                frontFacing[c] = true;
            }
            cache.FrontFacing[submeshIndex] = frontFacing;
        }
        _paintProjection = cache;
        return cache;
    }

    /// <summary>
    /// Instant local echo of one paint dab or sweep: the vertices the segment
    /// from <paramref name="start"/> to <paramref name="end"/> (a point, for a
    /// dab) covers are tinted immediately, then replaced when the
    /// authoritative native result lands one round trip later. Skipped above
    /// a vertex budget, where the projection walk would cost more than the
    /// latency it hides.
    /// </summary>
    private void UpdateProvisionalPaintHits(Point start, Point end, double radius, string operation)
    {
        if (!ProvisionalSelectionAffordable())
        {
            return;
        }
        var cache = EnsurePaintProjectionCache(CurrentCamera());
        var radiusSquared = radius * radius;
        var segmentX = (double)(end.X - start.X);
        var segmentY = (double)(end.Y - start.Y);
        var segmentLengthSquared = segmentX * segmentX + segmentY * segmentY;
        var subtract = operation == "subtract";
        foreach (var pair in cache.Points)
        {
            var submeshIndex = pair.Key;
            var points = pair.Value;
            var frontFacing = cache.FrontFacing.GetValueOrDefault(submeshIndex);
            HashSet<int>? bucket = null;
            for (var vertexIndex = 0; vertexIndex < points.Length; vertexIndex++)
            {
                var projected = points[vertexIndex];
                double deltaX;
                double deltaY;
                if (segmentLengthSquared <= 0.0001)
                {
                    deltaX = projected.X - start.X;
                    deltaY = projected.Y - start.Y;
                }
                else
                {
                    var t = Math.Clamp(
                        ((projected.X - start.X) * segmentX + (projected.Y - start.Y) * segmentY) / segmentLengthSquared,
                        0.0,
                        1.0);
                    deltaX = projected.X - (start.X + t * segmentX);
                    deltaY = projected.Y - (start.Y + t * segmentY);
                }
                if (deltaX * deltaX + deltaY * deltaY > radiusSquared)
                {
                    continue;
                }
                if (!ShowXRay && (frontFacing is null || !frontFacing[vertexIndex]))
                {
                    continue;
                }
                if (subtract)
                {
                    if (_provisionalSelectedVertices.TryGetValue(submeshIndex, out var existing))
                    {
                        existing.Remove(vertexIndex);
                    }
                }
                else
                {
                    bucket ??= _provisionalSelectedVertices.TryGetValue(submeshIndex, out var current)
                        ? current
                        : _provisionalSelectedVertices[submeshIndex] = new HashSet<int>();
                    bucket.Add(vertexIndex);
                }
            }
        }
        UpdateGpuViewport();
        Invalidate();
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
        var lassoPoints = _selectionLassoPoints.Count >= 3
            ? _selectionLassoPoints.ToArray()
            : null;
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
                _provisionalSelectedVertices.Clear();
            }
            UpdateProvisionalPaintHits(point, point, SelectionClickRadiusPixels, clickOperation);
            payload["screen_brush"] = ScreenPayload(point, SelectionClickRadiusPixels);
            EditorEventRequested?.Invoke("select_request", payload);
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
        payload["screen_region"] = region;
        EditorEventRequested?.Invoke("select_request", payload);
        StatusRequested?.Invoke($"{targetMode} region selection awaiting authoritative depth-resolved result.");
        _hoverEdgeId = -1;
        UpdateGpuViewport();
        Invalidate();
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
    /// Parts are the only selectable element, so "source" is the fallback here
    /// as well as the combo's only value: a provider that is not attached yet
    /// must not answer with a target the surface no longer offers.
    /// </summary>
    internal string CurrentTargetMode()
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        return options.TryGetValue("target_mode", out var value)
            ? (value?.ToString() ?? "source").Trim().ToLowerInvariant()
            : "source";
    }

    private string CurrentSelectionOperation()
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        return options.TryGetValue("operation", out var value)
            ? (value?.ToString() ?? "add").Trim().ToLowerInvariant()
            : "add";
    }
}
