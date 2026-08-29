using System.Drawing;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Pure screen-space geometry shared by local echo, resident selection request
/// construction, and bounded stroke sampling.
///
/// Policy: calculations use double precision; coordinate/collinearity and
/// boundary comparisons use 1e-9, matching the native screen-selection owner;
/// squared segment length and projected triangle area at or below 1e-12 are
/// degenerate; boundaries count as hits. Visible-facing UI selection keeps its
/// established 0.01 pixel-squared projected-area threshold, while XRay bypasses
/// visibility/depth rejection but never submesh or geometry-layer rejection.
/// </summary>
internal static class SelectionGeometry
{
    internal const double CoordinateEpsilon = 1.0e-9;
    internal const double DegenerateSquaredLength = 1.0e-12;
    internal const double DegenerateProjectedArea = 1.0e-12;
    internal const double FrontFacingProjectedArea = 0.01;

    internal static double Orientation(PointF first, PointF second, PointF third) =>
        ((double)second.X - first.X) * ((double)third.Y - first.Y)
        - ((double)second.Y - first.Y) * ((double)third.X - first.X);

    internal static double ProjectedTriangleArea(PointF a, PointF b, PointF c) =>
        Orientation(a, b, c);

    internal static bool IsProjectedTriangleDegenerate(PointF a, PointF b, PointF c) =>
        Math.Abs(ProjectedTriangleArea(a, b, c)) <= DegenerateProjectedArea;

    internal static bool IsFrontFacingProjectedTriangle(PointF a, PointF b, PointF c) =>
        ProjectedTriangleArea(a, b, c) < -FrontFacingProjectedArea;

    internal static bool PointOnSegment(PointF point, PointF start, PointF end) =>
        Math.Abs(Orientation(start, end, point)) <= CoordinateEpsilon
        && point.X >= Math.Min(start.X, end.X) - CoordinateEpsilon
        && point.X <= Math.Max(start.X, end.X) + CoordinateEpsilon
        && point.Y >= Math.Min(start.Y, end.Y) - CoordinateEpsilon
        && point.Y <= Math.Max(start.Y, end.Y) + CoordinateEpsilon;

    internal static bool SegmentsIntersect(PointF a, PointF b, PointF c, PointF d)
    {
        var abC = Orientation(a, b, c);
        var abD = Orientation(a, b, d);
        var cdA = Orientation(c, d, a);
        var cdB = Orientation(c, d, b);
        if (OppositeSides(abC, abD) && OppositeSides(cdA, cdB))
        {
            return true;
        }
        return PointOnSegment(c, a, b)
            || PointOnSegment(d, a, b)
            || PointOnSegment(a, c, d)
            || PointOnSegment(b, c, d);
    }

    internal static double PointSegmentDistanceSquared(PointF point, PointF start, PointF end)
    {
        var dx = (double)end.X - start.X;
        var dy = (double)end.Y - start.Y;
        var lengthSquared = dx * dx + dy * dy;
        var t = lengthSquared <= DegenerateSquaredLength
            ? 0.0
            : Math.Clamp(
                (((double)point.X - start.X) * dx + ((double)point.Y - start.Y) * dy)
                / lengthSquared,
                0.0,
                1.0);
        var nearestX = start.X + t * dx;
        var nearestY = start.Y + t * dy;
        var deltaX = point.X - nearestX;
        var deltaY = point.Y - nearestY;
        return deltaX * deltaX + deltaY * deltaY;
    }

    internal static double PointSegmentDistance(PointF point, PointF start, PointF end) =>
        Math.Sqrt(PointSegmentDistanceSquared(point, start, end));

    internal static double SegmentDistanceSquared(PointF a, PointF b, PointF c, PointF d)
    {
        if (SegmentsIntersect(a, b, c, d))
        {
            return 0.0;
        }
        return Math.Min(
            Math.Min(PointSegmentDistanceSquared(a, c, d), PointSegmentDistanceSquared(b, c, d)),
            Math.Min(PointSegmentDistanceSquared(c, a, b), PointSegmentDistanceSquared(d, a, b)));
    }

    internal static bool PointInTriangle(PointF point, PointF a, PointF b, PointF c)
    {
        if (IsProjectedTriangleDegenerate(a, b, c))
        {
            return false;
        }
        var ab = Orientation(a, b, point);
        var bc = Orientation(b, c, point);
        var ca = Orientation(c, a, point);
        var hasNegative = ab < -CoordinateEpsilon
            || bc < -CoordinateEpsilon
            || ca < -CoordinateEpsilon;
        var hasPositive = ab > CoordinateEpsilon
            || bc > CoordinateEpsilon
            || ca > CoordinateEpsilon;
        return !(hasNegative && hasPositive);
    }

    internal static bool PointInPolygon(PointF point, IReadOnlyList<Point> polygon)
    {
        if (polygon.Count < 3)
        {
            return false;
        }
        var inside = false;
        var previous = new PointF(polygon[^1].X, polygon[^1].Y);
        foreach (var rawCurrent in polygon)
        {
            var current = new PointF(rawCurrent.X, rawCurrent.Y);
            if (PointOnSegment(point, previous, current))
            {
                return true;
            }
            var crosses = (current.Y > point.Y) != (previous.Y > point.Y);
            if (crosses)
            {
                var slopeX = ((double)previous.X - current.X) * (point.Y - current.Y)
                    / (previous.Y - current.Y) + current.X;
                if (point.X <= slopeX + CoordinateEpsilon)
                {
                    inside = !inside;
                }
            }
            previous = current;
        }
        return inside;
    }

    internal static bool PolygonIntersectsSegment(
        IReadOnlyList<Point> polygon,
        PointF start,
        PointF end)
    {
        if (polygon.Count < 3)
        {
            return false;
        }
        if (PointInPolygon(start, polygon) || PointInPolygon(end, polygon))
        {
            return true;
        }
        for (var index = 0; index < polygon.Count; index += 1)
        {
            var first = polygon[index];
            var second = polygon[(index + 1) % polygon.Count];
            if (SegmentsIntersect(start, end, first, second))
            {
                return true;
            }
        }
        return false;
    }

    internal static bool PolygonIntersectsTriangle(
        IReadOnlyList<Point> polygon,
        PointF a,
        PointF b,
        PointF c)
    {
        if (polygon.Count < 3 || IsProjectedTriangleDegenerate(a, b, c))
        {
            return false;
        }
        if (PointInPolygon(a, polygon)
            || PointInPolygon(b, polygon)
            || PointInPolygon(c, polygon))
        {
            return true;
        }
        foreach (var point in polygon)
        {
            if (PointInTriangle(point, a, b, c))
            {
                return true;
            }
        }
        return PolygonIntersectsSegment(polygon, a, b)
            || PolygonIntersectsSegment(polygon, b, c)
            || PolygonIntersectsSegment(polygon, c, a);
    }

    internal static bool SegmentIntersectsRectangle(PointF start, PointF end, Rectangle rectangle)
    {
        if (PointInRectangle(start, rectangle) || PointInRectangle(end, rectangle))
        {
            return true;
        }
        var topLeft = new PointF(rectangle.Left, rectangle.Top);
        var topRight = new PointF(rectangle.Right, rectangle.Top);
        var bottomRight = new PointF(rectangle.Right, rectangle.Bottom);
        var bottomLeft = new PointF(rectangle.Left, rectangle.Bottom);
        return SegmentsIntersect(start, end, topLeft, topRight)
            || SegmentsIntersect(start, end, topRight, bottomRight)
            || SegmentsIntersect(start, end, bottomRight, bottomLeft)
            || SegmentsIntersect(start, end, bottomLeft, topLeft);
    }

    internal static bool RectangleIntersectsTriangle(
        Rectangle rectangle,
        PointF a,
        PointF b,
        PointF c)
    {
        if (IsProjectedTriangleDegenerate(a, b, c))
        {
            return false;
        }
        if (PointInRectangle(a, rectangle)
            || PointInRectangle(b, rectangle)
            || PointInRectangle(c, rectangle))
        {
            return true;
        }
        var corners = new[]
        {
            new PointF(rectangle.Left, rectangle.Top),
            new PointF(rectangle.Right, rectangle.Top),
            new PointF(rectangle.Right, rectangle.Bottom),
            new PointF(rectangle.Left, rectangle.Bottom),
        };
        if (corners.Any(point => PointInTriangle(point, a, b, c)))
        {
            return true;
        }
        return SegmentIntersectsRectangle(a, b, rectangle)
            || SegmentIntersectsRectangle(b, c, rectangle)
            || SegmentIntersectsRectangle(c, a, rectangle);
    }

    internal static bool RequiresVisibleDepth(bool xrayEnabled) => !xrayEnabled;

    internal static bool DepthAllowsSelection(bool xrayEnabled, bool visibleAtSample) =>
        xrayEnabled || visibleAtSample;

    internal static bool SubmeshAllowsSelection(
        bool indexInRange,
        bool geometryLayerSelectable,
        bool paneIncludesSubmesh,
        bool materialVisible) =>
        indexInRange && geometryLayerSelectable && paneIncludesSubmesh && materialVisible;

    private static bool OppositeSides(double first, double second) =>
        (first > CoordinateEpsilon && second < -CoordinateEpsilon)
        || (first < -CoordinateEpsilon && second > CoordinateEpsilon);

    private static bool PointInRectangle(PointF point, Rectangle rectangle) =>
        point.X >= rectangle.Left - CoordinateEpsilon
        && point.X <= rectangle.Right + CoordinateEpsilon
        && point.Y >= rectangle.Top - CoordinateEpsilon
        && point.Y <= rectangle.Bottom + CoordinateEpsilon;
}
