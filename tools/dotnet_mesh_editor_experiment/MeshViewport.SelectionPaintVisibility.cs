using System.Drawing;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The per-drag visibility half of the paint projection cache: a coarse
/// min-depth raster of the visible submeshes and the samplers the echo uses
/// against it, plus the edge bucket grid. The raster is the local stand-in for
/// the native selection depth mask, so what the echo tints in visible mode and
/// what the authoritative result keeps finally agree about occlusion instead
/// of the echo tinting anything front-facing and the result dropping the
/// hidden part of it.
/// </summary>
internal sealed partial class MeshViewport
{
    private const int PaintOcclusionCellPixels = 4;
    // Matches the native depth mask's acceptance bias so the echo and the
    // authoritative filter disagree as rarely as possible.
    private const float PaintOcclusionDepthBias = 0.0035f;
    // Edges get bucketed a margin beyond the pane so a brush centred inside
    // the pane can still reach geometry just past its border; anything
    // further out than the largest brush radius can never be painted.
    private const int PaintEdgeBucketViewportMarginPixels = 288;

    private void PreparePaintOcclusionGrid(PaintProjectionCache cache)
    {
        if (cache.BuiltForXRay)
        {
            return;
        }
        cache.OcclusionColumns = Math.Max(
            1,
            (cache.ViewportWidth + PaintOcclusionCellPixels - 1) / PaintOcclusionCellPixels);
        cache.OcclusionRows = Math.Max(
            1,
            (cache.ViewportHeight + PaintOcclusionCellPixels - 1) / PaintOcclusionCellPixels);
        cache.OcclusionDepths = new float[cache.OcclusionColumns * cache.OcclusionRows];
        Array.Fill(cache.OcclusionDepths, float.PositiveInfinity);
    }

    private static void RasterizePaintOcclusionTriangle(
        PaintProjectionCache cache,
        PointF a,
        float depthA,
        PointF b,
        float depthB,
        PointF c,
        float depthC)
    {
        if (cache.OcclusionDepths.Length == 0)
        {
            return;
        }
        var area = ((b.X - a.X) * (c.Y - a.Y)) - ((b.Y - a.Y) * (c.X - a.X));
        if (Math.Abs(area) <= 1.0e-9f)
        {
            return;
        }
        var minColumn = Math.Clamp(
            (int)MathF.Floor(MathF.Min(a.X, MathF.Min(b.X, c.X)) / PaintOcclusionCellPixels),
            0,
            cache.OcclusionColumns - 1);
        var maxColumn = Math.Clamp(
            (int)MathF.Floor(MathF.Max(a.X, MathF.Max(b.X, c.X)) / PaintOcclusionCellPixels),
            0,
            cache.OcclusionColumns - 1);
        var minRow = Math.Clamp(
            (int)MathF.Floor(MathF.Min(a.Y, MathF.Min(b.Y, c.Y)) / PaintOcclusionCellPixels),
            0,
            cache.OcclusionRows - 1);
        var maxRow = Math.Clamp(
            (int)MathF.Floor(MathF.Max(a.Y, MathF.Max(b.Y, c.Y)) / PaintOcclusionCellPixels),
            0,
            cache.OcclusionRows - 1);
        for (var row = minRow; row <= maxRow; row++)
        {
            var y = (row + 0.5f) * PaintOcclusionCellPixels;
            for (var column = minColumn; column <= maxColumn; column++)
            {
                var x = (column + 0.5f) * PaintOcclusionCellPixels;
                var w0 = (((b.X - x) * (c.Y - y)) - ((b.Y - y) * (c.X - x))) / area;
                var w1 = (((c.X - x) * (a.Y - y)) - ((c.Y - y) * (a.X - x))) / area;
                var w2 = 1.0f - w0 - w1;
                if (w0 < -0.001f || w1 < -0.001f || w2 < -0.001f)
                {
                    continue;
                }
                var depth = (w0 * depthA) + (w1 * depthB) + (w2 * depthC);
                if (!float.IsFinite(depth))
                {
                    continue;
                }
                var offset = (row * cache.OcclusionColumns) + column;
                if (depth < cache.OcclusionDepths[offset])
                {
                    cache.OcclusionDepths[offset] = depth;
                }
            }
        }
    }

    /// <summary>
    /// Visible when nothing rasterized nearer at the point's cell. A cell that
    /// occludes the point still yields to the 3x3 neighborhood's farthest
    /// front depth: with 4px cells a glancing surface's own depth can vary
    /// more across one cell than the acceptance bias, and a point lying on
    /// that surface must not read as hidden behind itself.
    /// </summary>
    private static bool PaintPointVisible(PaintProjectionCache cache, float x, float y, float depth)
    {
        if (cache.OcclusionDepths.Length == 0)
        {
            return true;
        }
        var column = (int)MathF.Floor(x / PaintOcclusionCellPixels);
        var row = (int)MathF.Floor(y / PaintOcclusionCellPixels);
        if (column < 0 || row < 0 || column >= cache.OcclusionColumns || row >= cache.OcclusionRows)
        {
            return true;
        }
        var front = cache.OcclusionDepths[(row * cache.OcclusionColumns) + column];
        if (!float.IsFinite(front) || depth <= front + PaintOcclusionDepthBias)
        {
            return true;
        }
        var farthestNear = float.NegativeInfinity;
        for (var neighborRow = Math.Max(0, row - 1); neighborRow <= Math.Min(cache.OcclusionRows - 1, row + 1); neighborRow++)
        {
            for (var neighborColumn = Math.Max(0, column - 1); neighborColumn <= Math.Min(cache.OcclusionColumns - 1, column + 1); neighborColumn++)
            {
                var neighborDepth = cache.OcclusionDepths[(neighborRow * cache.OcclusionColumns) + neighborColumn];
                if (float.IsFinite(neighborDepth) && neighborDepth > farthestNear)
                {
                    farthestNear = neighborDepth;
                }
            }
        }
        return depth <= farthestNear + PaintOcclusionDepthBias;
    }

    private static bool PaintSegmentVisible(
        PaintProjectionCache cache,
        PointF a,
        float depthA,
        PointF b,
        float depthB)
    {
        if (cache.OcclusionDepths.Length == 0)
        {
            return true;
        }
        // A wire is selectable when any part of it shows: endpoint, midpoint,
        // and quarter samples cover partial occlusion without walking pixels.
        for (var sample = 0; sample <= 4; sample++)
        {
            var t = sample * 0.25f;
            if (PaintPointVisible(
                cache,
                a.X + ((b.X - a.X) * t),
                a.Y + ((b.Y - a.Y) * t),
                depthA + ((depthB - depthA) * t)))
            {
                return true;
            }
        }
        return false;
    }

    private static bool PaintTriangleVisible(
        PaintProjectionCache cache,
        PointF a,
        float depthA,
        PointF b,
        float depthB,
        PointF c,
        float depthC)
    {
        if (cache.OcclusionDepths.Length == 0)
        {
            return true;
        }
        return PaintPointVisible(cache, a.X, a.Y, depthA)
            || PaintPointVisible(cache, b.X, b.Y, depthB)
            || PaintPointVisible(cache, c.X, c.Y, depthC)
            || PaintPointVisible(
                cache,
                (a.X + b.X + c.X) / 3.0f,
                (a.Y + b.Y + c.Y) / 3.0f,
                (depthA + depthB + depthC) / 3.0f);
    }

    private void BuildPaintEdgeBuckets(PaintProjectionCache cache)
    {
        var edges = _edgeTopology.Edges;
        var pendingBuckets = new List<int>?[cache.GridColumns * cache.GridRows];
        var largeCandidates = new List<int>();
        var marginLeft = -(float)PaintEdgeBucketViewportMarginPixels;
        var marginTop = -(float)PaintEdgeBucketViewportMarginPixels;
        var marginRight = cache.ViewportWidth + (float)PaintEdgeBucketViewportMarginPixels;
        var marginBottom = cache.ViewportHeight + (float)PaintEdgeBucketViewportMarginPixels;
        for (var edgeIndex = 0; edgeIndex < edges.Count; edgeIndex++)
        {
            var edge = edges[edgeIndex];
            if (!cache.Points.TryGetValue(edge.SubmeshIndex, out var points)
                || edge.VertexA < 0
                || edge.VertexA >= points.Length
                || edge.VertexB < 0
                || edge.VertexB >= points.Length)
            {
                continue;
            }
            var a = points[edge.VertexA];
            var b = points[edge.VertexB];
            var left = MathF.Min(a.X, b.X);
            var top = MathF.Min(a.Y, b.Y);
            var right = MathF.Max(a.X, b.X);
            var bottom = MathF.Max(a.Y, b.Y);
            if (right < marginLeft || bottom < marginTop || left > marginRight || top > marginBottom)
            {
                continue;
            }
            _ = RoutePaintProjectionFaceCandidate(
                pendingBuckets,
                largeCandidates,
                edgeIndex,
                cache.GridColumns,
                Math.Clamp((int)MathF.Floor(left / PaintProjectionCellPixels), 0, cache.GridColumns - 1),
                Math.Clamp((int)MathF.Floor(right / PaintProjectionCellPixels), 0, cache.GridColumns - 1),
                Math.Clamp((int)MathF.Floor(top / PaintProjectionCellPixels), 0, cache.GridRows - 1),
                Math.Clamp((int)MathF.Floor(bottom / PaintProjectionCellPixels), 0, cache.GridRows - 1));
        }
        cache.EdgeBuckets = pendingBuckets
            .Select(bucket => bucket?.ToArray() ?? Array.Empty<int>())
            .ToArray();
        cache.LargeEdgeCandidates = largeCandidates.ToArray();
        cache.EdgeVisitStamps = new int[edges.Count];
    }
}
