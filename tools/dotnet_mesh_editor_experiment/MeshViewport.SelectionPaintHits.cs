using System.Diagnostics;
using System.Drawing;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
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
        if (cache is null)
        {
            if (!_paintProjectionColdFirstDabRecorded)
            {
                _paintProjectionColdFirstDabCount++;
                _paintProjectionColdFirstDabRecorded = true;
            }
            _pendingPaintSample = new PendingPaintSample(start, end, radius, operation, _selectionStrokeId);
            return;
        }
        if (!_paintProjectionFirstDabMeasured)
        {
            _paintProjectionWarmFirstDabCount++;
            _paintProjectionLastWarmFirstDabMs = _paintProjectionFirstDabStartedTicks > 0
                ? Math.Max(0.0, Stopwatch.GetElapsedTime(_paintProjectionFirstDabStartedTicks).TotalMilliseconds)
                : 0.0;
            _paintProjectionFirstDabMeasured = true;
        }
        EnsurePaintOcclusionForBounds(cache, RectangleF.FromLTRB(
            (float)(Math.Min(start.X, end.X) - radius),
            (float)(Math.Min(start.Y, end.Y) - radius),
            (float)(Math.Max(start.X, end.X) + radius),
            (float)(Math.Max(start.Y, end.Y) + radius)));
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
        var edges = cache.Edges;
        if (cache.EdgeVisitStamps.Length != edges.Length)
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
                || SelectionGeometry.SegmentDistanceSquared(
                    start,
                    end,
                    points[edge.VertexA],
                    points[edge.VertexB]) > radiusSquared)
            {
                continue;
            }
            if (SelectionGeometry.RequiresVisibleDepth(ShowXRay)
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
            var faces = cache.Faces[submeshIndex];
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
            var left = Math.Clamp((int)MathF.Floor(bandBounds.Left / PaintProjectionCellPixels), 0, cache.GridColumns - 1);
            var right = Math.Clamp((int)MathF.Floor(bandBounds.Right / PaintProjectionCellPixels), 0, cache.GridColumns - 1);
            var top = Math.Clamp((int)MathF.Floor(bandBounds.Top / PaintProjectionCellPixels), 0, cache.GridRows - 1);
            var bottom = Math.Clamp((int)MathF.Floor(bandBounds.Bottom / PaintProjectionCellPixels), 0, cache.GridRows - 1);
            faceQueryCandidates.Clear();
            for (var row = top; row <= bottom; row++)
            {
                for (var column = left; column <= right; column++)
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
                var face = faces[faceIndex];
                var a = face.A;
                var b = face.B;
                var c = face.C;
                if (!SweptBandIntersectsTriangle(start, end, radius, points[a], points[b], points[c]))
                {
                    continue;
                }
                if (SelectionGeometry.RequiresVisibleDepth(ShowXRay)
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
                        if (SelectionGeometry.PointSegmentDistance(points[vertexIndex], start, end) > radius)
                        {
                            continue;
                        }
                        if (SelectionGeometry.RequiresVisibleDepth(ShowXRay)
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
