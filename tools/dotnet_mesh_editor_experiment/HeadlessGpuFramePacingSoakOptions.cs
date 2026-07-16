using System.Globalization;
using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal sealed record HeadlessGpuFramePacingSoakOptions(
    string ReportPath,
    double DurationSeconds,
    double TargetHz,
    int WarmupFrames,
    int Width,
    int Height,
    int VertexCount,
    bool Smoke)
{
    public static HeadlessGpuFramePacingSoakOptions Parse(string[] args)
    {
        var values = ParseArgs(args);
        var smoke = values.ContainsKey("frame-pacing-smoke");
        return new HeadlessGpuFramePacingSoakOptions(
            ReportPathFrom(args),
            Number(values, "frame-pacing-duration-seconds", smoke ? 2.0 : 30.0, smoke ? 0.25 : 1.0, 600.0),
            Number(values, "frame-pacing-target-hz", 144.0, 30.0, 360.0),
            Integer(values, "frame-pacing-warmup-frames", smoke ? 16 : 300, 0, 10_000),
            Integer(values, "frame-pacing-width", smoke ? 640 : 1920, 64, 7680),
            Integer(values, "frame-pacing-height", smoke ? 360 : 1080, 64, 4320),
            Integer(values, "frame-pacing-vertices", smoke ? 30_000 : 180_000, 3, 2_000_000),
            smoke);
    }

    public static string ReportPathFrom(string[] args)
    {
        var values = ParseArgs(args);
        return values.TryGetValue("frame-pacing-report", out var path) && !string.IsNullOrWhiteSpace(path)
            ? Path.GetFullPath(path)
            : Path.Combine(Environment.CurrentDirectory, "dotnet-preview-frame-pacing.json");
    }

    private static int Integer(
        IReadOnlyDictionary<string, string> values,
        string key,
        int fallback,
        int minimum,
        int maximum)
    {
        if (!values.TryGetValue(key, out var raw))
        {
            return fallback;
        }
        if (!int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value)
            || value < minimum
            || value > maximum)
        {
            throw new ArgumentOutOfRangeException(key, $"--{key} must be from {minimum:N0} through {maximum:N0}.");
        }
        return value;
    }

    private static double Number(
        IReadOnlyDictionary<string, string> values,
        string key,
        double fallback,
        double minimum,
        double maximum)
    {
        if (!values.TryGetValue(key, out var raw))
        {
            return fallback;
        }
        if (!double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var value)
            || !double.IsFinite(value)
            || value < minimum
            || value > maximum)
        {
            throw new ArgumentOutOfRangeException(key, $"--{key} must be from {minimum} through {maximum}.");
        }
        return value;
    }

    private static Dictionary<string, string> ParseArgs(string[] args)
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var index = 0; index < args.Length; index++)
        {
            if (!args[index].StartsWith("--", StringComparison.Ordinal))
            {
                continue;
            }
            var key = args[index][2..];
            values[key] = index + 1 < args.Length && !args[index + 1].StartsWith("--", StringComparison.Ordinal)
                ? args[++index]
                : "true";
        }
        return values;
    }
}
