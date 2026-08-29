using System.Drawing;
using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal static class SelectionGeometryContractSmoke
{
    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(arg, "--headless-selection-geometry-contract", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var triangleA = new PointF(0.0f, 0.0f);
        var triangleB = new PointF(10.0f, 0.0f);
        var triangleC = new PointF(5.0f, 10.0f);
        var containingLasso = Polygon((0, -2), (12, -2), (12, 12), (0, 12));
        var oneEdgeLasso = Polygon((4, -2), (6, -2), (6, 2), (4, 2));
        var overlappingFaceHit = SelectionGeometry.PointInTriangle(
            Point(5, 4),
            triangleA,
            triangleB,
            triangleC);

        var repeatedExpected = SelectionGeometry.PolygonIntersectsTriangle(
            oneEdgeLasso,
            triangleA,
            triangleB,
            triangleC);
        var repeatedStable = true;
        for (var iteration = 0; iteration < 1000; iteration += 1)
        {
            repeatedStable &= SelectionGeometry.PolygonIntersectsTriangle(
                oneEdgeLasso,
                triangleA,
                triangleB,
                triangleC) == repeatedExpected;
        }

        var gates = new Dictionary<string, bool>(StringComparer.Ordinal)
        {
            ["01_crossing_segments"] = SelectionGeometry.SegmentsIntersect(
                Point(0, 0), Point(10, 10), Point(0, 10), Point(10, 0)),
            ["02_disjoint_collinear_segments"] = !SelectionGeometry.SegmentsIntersect(
                Point(0, 0), Point(10, 0), Point(20, 0), Point(30, 0)),
            ["03_overlapping_collinear_segments"] = SelectionGeometry.SegmentsIntersect(
                Point(0, 0), Point(10, 0), Point(5, 0), Point(15, 0)),
            ["04_endpoint_touching"] = SelectionGeometry.SegmentsIntersect(
                Point(0, 0), Point(10, 0), Point(10, 0), Point(10, 10)),
            ["05_near_collinear_floating_point"] = SelectionGeometry.SegmentsIntersect(
                Point(0.0f, 0.0f),
                Point(10.0f, 0.0000001f),
                Point(5.0f, 0.00000005005f),
                Point(15.0f, 0.00000015f)),
            ["06_zero_length_against_zero_length"] = SelectionGeometry.SegmentsIntersect(
                Point(4, 4), Point(4, 4), Point(4, 4), Point(4, 4)),
            ["07_zero_length_against_segment"] = SelectionGeometry.SegmentsIntersect(
                    Point(5, 0), Point(5, 0), Point(0, 0), Point(10, 0))
                && SelectionGeometry.PointSegmentDistanceSquared(
                    Point(5, 2), Point(5, 0), Point(5, 0)) == 4.0,
            ["08_point_inside_triangle"] = SelectionGeometry.PointInTriangle(
                Point(5, 4), triangleA, triangleB, triangleC),
            ["09_point_on_triangle_boundary"] = SelectionGeometry.PointInTriangle(
                Point(5, 0), triangleA, triangleB, triangleC),
            ["10_point_outside_triangle"] = !SelectionGeometry.PointInTriangle(
                Point(15, 4), triangleA, triangleB, triangleC),
            ["11_zero_area_triangle"] = SelectionGeometry.IsProjectedTriangleDegenerate(
                    Point(0, 0), Point(5, 0), Point(10, 0))
                && !SelectionGeometry.PointInTriangle(
                    Point(5, 0), Point(0, 0), Point(5, 0), Point(10, 0)),
            ["12_near_zero_area_projected_triangle"] = SelectionGeometry.IsProjectedTriangleDegenerate(
                    Point(0.0f, 0.0f), Point(1.0f, 0.0f), Point(1.0f, 0.0000000000005f))
                && !SelectionGeometry.PointInTriangle(
                    Point(0.5f, 0.0f),
                    Point(0.0f, 0.0f),
                    Point(1.0f, 0.0f),
                    Point(1.0f, 0.0000000000005f)),
            ["13_rectangle_contains_triangle_vertex"] = SelectionGeometry.RectangleIntersectsTriangle(
                new Rectangle(0, 0, 10, 10), Point(5, 5), Point(20, 5), Point(5, 20)),
            ["14_rectangle_crosses_triangle_edge"] = SelectionGeometry.RectangleIntersectsTriangle(
                new Rectangle(4, 4, 4, 4), Point(0, 6), Point(12, 6), Point(6, 20)),
            ["15_rectangle_inside_triangle"] = SelectionGeometry.RectangleIntersectsTriangle(
                new Rectangle(8, 8, 2, 2), Point(0, 0), Point(20, 0), Point(10, 20)),
            ["16_lasso_contains_triangle"] = SelectionGeometry.PolygonIntersectsTriangle(
                containingLasso, Point(3, 3), Point(9, 3), Point(6, 8)),
            ["17_triangle_contains_lasso_point"] = SelectionGeometry.PolygonIntersectsTriangle(
                Polygon((5, 4), (20, 4), (20, 20)), triangleA, triangleB, triangleC),
            ["18_polygon_crosses_one_triangle_edge"] = repeatedExpected,
            ["19_reversed_winding"] = SelectionGeometry.PolygonIntersectsTriangle(
                    containingLasso.Reverse().ToArray(), triangleA, triangleC, triangleB)
                == SelectionGeometry.PolygonIntersectsTriangle(
                    containingLasso, triangleA, triangleB, triangleC),
            ["20_edge_on_projected_face"] = !SelectionGeometry.IsFrontFacingProjectedTriangle(
                Point(0, 0), Point(10, 0), Point(20, -0.0001f)),
            ["21_xray_overlapping_faces"] = overlappingFaceHit
                && SelectionGeometry.DepthAllowsSelection(true, true)
                && SelectionGeometry.DepthAllowsSelection(true, false),
            ["22_visible_depth_overlapping_faces"] = overlappingFaceHit
                && SelectionGeometry.DepthAllowsSelection(false, true)
                && !SelectionGeometry.DepthAllowsSelection(false, false),
            ["23_hidden_submesh_exclusion"] = overlappingFaceHit
                && !SelectionGeometry.SubmeshAllowsSelection(true, true, false, true),
            ["24_inactive_geometry_layer_exclusion"] = overlappingFaceHit
                && !SelectionGeometry.SubmeshAllowsSelection(true, false, true, true),
            ["25_repeated_identical_input"] = repeatedStable,
        };

        var ok = gates.Count == 25 && gates.Values.All(value => value);
        PreviewPerformanceReport.WriteAtomic(ReportPath(args), new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_selection_geometry_contract_v1",
            ["schema_version"] = 1,
            ["ok"] = ok,
            ["gates"] = gates,
            ["case_count"] = gates.Count,
            ["coordinate_epsilon"] = SelectionGeometry.CoordinateEpsilon,
            ["degenerate_squared_length"] = SelectionGeometry.DegenerateSquaredLength,
            ["degenerate_projected_area"] = SelectionGeometry.DegenerateProjectedArea,
            ["front_facing_projected_area"] = SelectionGeometry.FrontFacingProjectedArea,
            ["boundary_policy"] = "inclusive",
            ["repeated_iterations"] = 1000,
        });
        return ok ? 0 : 1;
    }

    private static PointF Point(float x, float y) => new(x, y);

    private static Point[] Polygon(params (int X, int Y)[] points) =>
        points.Select(point => new Point(point.X, point.Y)).ToArray();

    private static string ReportPath(string[] args)
    {
        var index = Array.FindIndex(args, arg => string.Equals(
            arg,
            "--selection-geometry-report",
            StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index + 1 >= args.Length)
        {
            throw new ArgumentException("--selection-geometry-report requires an output path.");
        }
        return Path.GetFullPath(args[index + 1]);
    }
}
