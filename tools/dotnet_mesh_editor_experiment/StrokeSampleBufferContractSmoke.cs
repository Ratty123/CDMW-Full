using System.Diagnostics;
using System.Drawing;
using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal static class StrokeSampleBufferContractSmoke
{
    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(arg, "--headless-stroke-sample-buffer-contract", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var straight = new StrokeSampleBuffer();
        for (var index = 0; index < 2400; index += 1)
        {
            straight.Add(new Point(index, 20), index);
        }

        var curved = new StrokeSampleBuffer();
        for (var index = 0; index < 2400; index += 1)
        {
            curved.Add(new Point(index, index % 2 == 0 ? 0 : 40), index);
        }

        var slow = new StrokeSampleBuffer();
        for (var index = 0; index <= 100; index += 1)
        {
            slow.Add(new Point(index, 0), index * 10L);
        }

        var corners = new StrokeSampleBuffer(maxIntervalMilliseconds: 1000);
        corners.Add(new Point(0, 0), 0);
        corners.Add(new Point(20, 0), 10);
        corners.Add(new Point(20, 20), 20);
        corners.Add(new Point(40, 20), 30);

        var smoothRaw = Enumerable.Range(0, 1200)
            .Select(index => new Point(index, (int)Math.Round(Math.Sin(index / 30.0) * 30.0)))
            .ToArray();
        var smooth = new StrokeSampleBuffer(maxIntervalMilliseconds: 1000);
        for (var index = 0; index < smoothRaw.Length; index += 1)
        {
            smooth.Add(smoothRaw[index], index);
        }
        var smoothTolerance = smoothRaw.Max(point => DistanceToPath(point, smooth));

        var terminalTimer = Stopwatch.StartNew();
        curved.Add(new Point(2400, 0), 2400);
        terminalTimer.Stop();
        var protocolPath = ExperimentForm.BoundedProtocolStrokePath(
            Enumerable.Range(0, 2400)
                .Select(index => new Dictionary<string, object?>
                {
                    ["x"] = (double)index,
                    ["y"] = index % 2 == 0 ? 0.0 : 40.0,
                })
                .ToArray());

        var gates = new Dictionary<string, bool>(StringComparer.Ordinal)
        {
            ["first_sample_exact"] = straight[0] == new Point(0, 20),
            ["final_sample_exact"] = straight[^1] == new Point(2399, 20),
            ["straight_path_simplified"] = straight.Count < 60,
            ["high_curvature_bounded"] = curved.Count == StrokeSampleBuffer.DefaultMaxSamples
                && curved.OverflowCount > 0,
            ["slow_motion_time_sampled"] = slow.Count >= 17,
            ["curvature_corners_retained"] = corners.Contains(new Point(20, 0))
                && corners.Contains(new Point(20, 20)),
            ["smooth_coverage_within_tolerance"] = smoothTolerance <= 3.0,
            ["protocol_path_bounded"] = protocolPath.Count <= StrokeSampleBuffer.DefaultMaxSamples
                && Convert.ToDouble(protocolPath[0]["x"]) == 0.0
                && Convert.ToDouble(protocolPath[^1]["x"]) == 2399.0,
            ["terminal_processing_bounded"] = terminalTimer.Elapsed.TotalMilliseconds < 10.0,
        };
        var ok = gates.Values.All(value => value);
        PreviewPerformanceReport.WriteAtomic(ReportPath(args), new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_stroke_sample_buffer_contract_v1",
            ["schema_version"] = 1,
            ["ok"] = ok,
            ["gates"] = gates,
            ["raw_samples"] = 2401,
            ["straight_retained_samples"] = straight.Count,
            ["curved_retained_samples"] = curved.Count,
            ["slow_retained_samples"] = slow.Count,
            ["max_samples"] = StrokeSampleBuffer.DefaultMaxSamples,
            ["min_spacing_pixels"] = StrokeSampleBuffer.DefaultMinSpacingPixels,
            ["max_interval_ms"] = StrokeSampleBuffer.DefaultMaxIntervalMilliseconds,
            ["curvature_degrees"] = StrokeSampleBuffer.DefaultCurvatureDegrees,
            ["terminal_processing_ms"] = terminalTimer.Elapsed.TotalMilliseconds,
            ["smooth_coverage_max_error_pixels"] = smoothTolerance,
        });
        return ok ? 0 : 1;
    }

    private static string ReportPath(string[] args)
    {
        var index = Array.FindIndex(args, arg =>
            string.Equals(arg, "--stroke-sample-buffer-report", StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index + 1 >= args.Length)
        {
            throw new ArgumentException("--stroke-sample-buffer-report requires an output path.");
        }
        return Path.GetFullPath(args[index + 1]);
    }

    private static double DistanceToPath(Point point, IReadOnlyList<Point> path)
    {
        var minimum = double.MaxValue;
        for (var index = 0; index < path.Count - 1; index += 1)
        {
            minimum = Math.Min(
                minimum,
                SelectionGeometry.PointSegmentDistance(point, path[index], path[index + 1]));
        }
        return minimum;
    }
}
