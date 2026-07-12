using System.Globalization;
using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal sealed record HeadlessGpuSparseSoakOptions(
    string ReportPath,
    int VertexCount,
    int UpdateCount,
    int WarmupUpdates,
    bool EnforceCadence,
    bool Smoke,
    double TargetUpdatesPerSecond)
{
    public static HeadlessGpuSparseSoakOptions Parse(string[] args)
    {
        var values = ParseArgs(args);
        var smoke = values.ContainsKey("gpu-soak-smoke");
        var vertices = Integer(values, "gpu-soak-vertices", 1_000_000, 3, 2_000_000);
        var updates = Integer(values, "gpu-soak-updates", 1_000, 1, 10_000);
        var warmup = Integer(values, "gpu-soak-warmup", 64, 0, 1_000);
        var enforceCadence = !values.ContainsKey("gpu-soak-no-cadence");
        if (!smoke && (vertices < 1_000_000 || updates < 1_000 || !enforceCadence))
        {
            throw new ArgumentException("Full GPU soak requires at least 1,000,000 vertices, 1,000 updates, and cadence; use --gpu-soak-smoke for a reduced diagnostic run.");
        }
        return new HeadlessGpuSparseSoakOptions(
            ReportPathFrom(args),
            vertices,
            updates,
            warmup,
            enforceCadence,
            smoke,
            60.0);
    }

    public static string ReportPathFrom(string[] args)
    {
        var values = ParseArgs(args);
        return values.TryGetValue("gpu-soak-report", out var path) && !string.IsNullOrWhiteSpace(path)
            ? Path.GetFullPath(path)
            : Path.Combine(Environment.CurrentDirectory, "dotnet-gpu-sparse-soak.json");
    }

    private static int Integer(IReadOnlyDictionary<string, string> values, string key, int fallback, int minimum, int maximum)
    {
        if (!values.TryGetValue(key, out var raw))
        {
            return fallback;
        }
        if (!int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) || value < minimum || value > maximum)
        {
            throw new ArgumentOutOfRangeException(key, $"--{key} must be from {minimum:N0} through {maximum:N0}.");
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
