using System.Drawing;
using System.Globalization;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private static bool PointInTriangle(Point point, PointF a, PointF b, PointF c)
    {
        static float Sign(PointF p1, PointF p2, PointF p3)
        {
            return ((p1.X - p3.X) * (p2.Y - p3.Y)) - ((p2.X - p3.X) * (p1.Y - p3.Y));
        }
        var p = new PointF(point.X, point.Y);
        var d1 = Sign(p, a, b);
        var d2 = Sign(p, b, c);
        var d3 = Sign(p, c, a);
        var hasNegative = d1 < 0 || d2 < 0 || d3 < 0;
        var hasPositive = d1 > 0 || d2 > 0 || d3 > 0;
        return !(hasNegative && hasPositive);
    }

    private static bool SegmentIntersectsRectangle(PointF a, PointF b, Rectangle rectangle)
    {
        if (rectangle.Contains(Point.Round(a)) || rectangle.Contains(Point.Round(b)))
        {
            return true;
        }
        var topLeft = new PointF(rectangle.Left, rectangle.Top);
        var topRight = new PointF(rectangle.Right, rectangle.Top);
        var bottomLeft = new PointF(rectangle.Left, rectangle.Bottom);
        var bottomRight = new PointF(rectangle.Right, rectangle.Bottom);
        return LinesIntersect(a, b, topLeft, topRight)
            || LinesIntersect(a, b, topRight, bottomRight)
            || LinesIntersect(a, b, bottomRight, bottomLeft)
            || LinesIntersect(a, b, bottomLeft, topLeft);
    }

    private static bool LinesIntersect(PointF a, PointF b, PointF c, PointF d)
    {
        static float Cross(PointF p, PointF q, PointF r)
        {
            return ((q.X - p.X) * (r.Y - p.Y)) - ((q.Y - p.Y) * (r.X - p.X));
        }
        var ab1 = Cross(a, b, c);
        var ab2 = Cross(a, b, d);
        var cd1 = Cross(c, d, a);
        var cd2 = Cross(c, d, b);
        return (ab1 == 0.0f || ab2 == 0.0f || Math.Sign(ab1) != Math.Sign(ab2))
            && (cd1 == 0.0f || cd2 == 0.0f || Math.Sign(cd1) != Math.Sign(cd2));
    }

    private static double DistanceToSegment(Point point, PointF a, PointF b)
    {
        var vx = b.X - a.X;
        var vy = b.Y - a.Y;
        var wx = point.X - a.X;
        var wy = point.Y - a.Y;
        var lengthSquared = (vx * vx) + (vy * vy);
        var t = lengthSquared > 0.0001f ? Math.Clamp(((wx * vx) + (wy * vy)) / lengthSquared, 0.0f, 1.0f) : 0.0f;
        var x = a.X + (t * vx);
        var y = a.Y + (t * vy);
        var dx = point.X - x;
        var dy = point.Y - y;
        return Math.Sqrt((dx * dx) + (dy * dy));
    }

    private static double NumberOption(Dictionary<string, object?> options, string key, double fallback)
    {
        return options.TryGetValue(key, out var value) && value is IConvertible
            ? Convert.ToDouble(value, CultureInfo.InvariantCulture)
            : fallback;
    }
}
