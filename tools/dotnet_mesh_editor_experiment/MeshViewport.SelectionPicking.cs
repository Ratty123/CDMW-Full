using System.Drawing;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private const double SelectionClickRadiusPixels = 14.0;
    private const int SelectionRegionTolerancePixels = 6;
    private const double SelectionPaintSampleIntervalMs = 30.0;
    private const int SelectionPaintSampleMinimumStepPixels = 3;

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
        if (_selectionLassoPoints.Count > 0 && _selectionLassoPoints[^1] != point)
        {
            // MouseUp is not guaranteed to be preceded by a MouseMove at the
            // same location. Keep the terminal point so the polygon committed
            // to native selection is exactly the outline that reached the
            // cursor, including a fast three-point gesture.
            _selectionLassoPoints.Add(point);
        }
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
        if (lassoPoints is null && rectangle.Width < 4 && rectangle.Height < 4)
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
        if (cache is null)
        {
            // The authoritative region request still carries the polygon to
            // native selection. Local echo waits for the correlated cache build
            // instead of touching a partially built projection from input.
            return;
        }
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
                    || !SelectionPolygonIntersectsSegment(polygon, points[edge.VertexA], points[edge.VertexB]))
                {
                    continue;
                }
                var edgeDepths = cache.Depths[edge.SubmeshIndex];
                if (!ShowXRay
                    && !PaintSegmentVisible(
                        cache,
                        points[edge.VertexA],
                        edgeDepths[edge.VertexA],
                        points[edge.VertexB],
                        edgeDepths[edge.VertexB]))
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
                var depths = cache.Depths[submeshIndex];
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
                            || !SelectionPolygonIntersectsTriangle(polygon, points[a], points[b], points[c]))
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
                    if (!SelectionPointInPolygon(points[vertexIndex], polygon)
                        || (!ShowXRay
                            && !PaintPointVisible(cache, points[vertexIndex].X, points[vertexIndex].Y, depths[vertexIndex])))
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
        var orientationScratch = new Dictionary<int, sbyte[]>();
        foreach (var edge in _edgeTopology.Edges)
        {
            if (!IsSubmeshVisibleForViewportSelection(edge.SubmeshIndex))
            {
                continue;
            }
            if (!ShowXRay && !IsEdgeFrontFacing(edge, camera, orientationScratch))
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
        // Hover runs this on every mouse move. Both visibility questions are
        // therefore answered once per call, not once per edge: each face's
        // orientation is memoized (a face serves up to three edges), and the
        // occlusion scan for the cursor ray runs a single time instead of
        // re-walking every face for each candidate within click radius.
        var orientationScratch = new Dictionary<int, sbyte[]>();
        var hasOcclusion = false;
        var rayOrigin = Vector3.Zero;
        var rayDirection = Vector3.Zero;
        var nearestSurfaceDistance = float.PositiveInfinity;
        if (!ShowXRay && TryScreenRay(point, out rayOrigin, out rayDirection))
        {
            hasOcclusion = TryNearestVisibleSurface(
                rayOrigin,
                rayDirection,
                out nearestSurfaceDistance,
                out _,
                out _,
                orientationScratch);
        }
        var depthTolerance = Math.Max(_scene.SceneExtent * 0.01f, 0.0005f);
        foreach (var edge in _edgeTopology.Edges)
        {
            if (!IsSubmeshVisibleForViewportSelection(edge.SubmeshIndex))
            {
                continue;
            }
            if (!ShowXRay && !IsEdgeFrontFacing(edge, camera, orientationScratch))
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
            if (distance >= bestDistance)
            {
                continue;
            }
            if (hasOcclusion)
            {
                var edgePoint = Vector3.Lerp(
                    SceneWorldPoint(edge.SubmeshIndex, submesh.Vertices[edge.VertexA]),
                    SceneWorldPoint(edge.SubmeshIndex, submesh.Vertices[edge.VertexB]),
                    ScreenSegmentParameter(point, a, b));
                if (WorldPointBehindNearestSurface(
                    rayOrigin,
                    rayDirection,
                    nearestSurfaceDistance,
                    depthTolerance,
                    edgePoint))
                {
                    continue;
                }
            }
            bestDistance = distance;
            bestEdgeId = edge.Id;
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
        return IsEdgeFrontFacing(edge, camera, null);
    }

    private bool IsEdgeFrontFacing(NetEdge edge, NetViewportCamera camera, Dictionary<int, sbyte[]>? orientationScratch)
    {
        if (edge.AdjacentFaces.Count == 0)
        {
            return true;
        }
        foreach (var faceIndex in edge.AdjacentFaces)
        {
            if (IsFaceFrontFacingCached(edge.SubmeshIndex, faceIndex, camera, orientationScratch))
            {
                return true;
            }
        }
        return false;
    }

    /// <summary>
    /// Memoized face orientation for one pick or drag sample. A face is shared
    /// by up to three edges, so an edge sweep without the scratch projects
    /// every face's corners up to three times over.
    /// </summary>
    private bool IsFaceFrontFacingCached(
        int submeshIndex,
        int faceIndex,
        NetViewportCamera camera,
        Dictionary<int, sbyte[]>? orientationScratch)
    {
        if (orientationScratch is null)
        {
            return IsFaceFrontFacing(submeshIndex, faceIndex, camera);
        }
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return false;
        }
        var faceCount = _document.Submeshes[submeshIndex].Faces.Count;
        if (faceIndex < 0 || faceIndex >= faceCount)
        {
            return false;
        }
        if (!orientationScratch.TryGetValue(submeshIndex, out var states))
        {
            states = new sbyte[faceCount];
            orientationScratch[submeshIndex] = states;
        }
        if (states[faceIndex] == 0)
        {
            states[faceIndex] = IsFaceFrontFacing(submeshIndex, faceIndex, camera) ? (sbyte)1 : (sbyte)-1;
        }
        return states[faceIndex] > 0;
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
