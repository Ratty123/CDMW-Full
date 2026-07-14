using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed class RenderMetrics
{
    private const int SampleWindow = 120;
    private const double CadenceResetThresholdMs = 250.0;
    private readonly Queue<double> _renderMs = new();
    private readonly Queue<double> _frameIntervalMs = new();
    private readonly Queue<double> _presentMs = new();
    private readonly Queue<double> _dirtyToPresentMs = new();
    private readonly Queue<double> _responsivenessMs = new();
    private long _lastFrameTimestamp;

    public double AverageRenderMs { get; private set; }
    public double AverageFrameIntervalMs { get; private set; }
    public double FrameIntervalP95Ms { get; private set; }
    public double FrameIntervalMaxMs { get; private set; }
    public double FramePacingJitterMs { get; private set; }
    public double AverageFrameMs => AverageFrameIntervalMs > 0.0001 ? AverageFrameIntervalMs : AverageRenderMs;
    public double AveragePresentMs { get; private set; }
    public double AverageDirtyToPresentMs { get; private set; }
    public double AverageResponsivenessMs { get; private set; }
    public int DroppedFrames { get; private set; }
    public int FrameCount { get; private set; }
    public bool HasRenderedFrame => FrameCount > 0;
    public string DeviceRemovedReason { get; private set; } = string.Empty;
    public double AverageFps => AverageFrameIntervalMs > 0.0001 ? 1000.0 / AverageFrameIntervalMs : 0.0;

    public void Record(double frameMs, double presentMs, double dirtyToPresentMs, string deviceRemovedReason)
    {
        var now = Stopwatch.GetTimestamp();
        var normalizedRenderMs = Math.Max(0.0, frameMs);
        FrameCount++;
        _renderMs.Enqueue(normalizedRenderMs);
        _presentMs.Enqueue(Math.Max(0.0, presentMs));
        _dirtyToPresentMs.Enqueue(Math.Max(0.0, dirtyToPresentMs));
        while (_renderMs.Count > SampleWindow)
        {
            _renderMs.Dequeue();
        }
        while (_presentMs.Count > SampleWindow)
        {
            _presentMs.Dequeue();
        }
        while (_dirtyToPresentMs.Count > SampleWindow)
        {
            _dirtyToPresentMs.Dequeue();
        }

        if (_lastFrameTimestamp > 0)
        {
            var intervalMs = (now - _lastFrameTimestamp) * 1000.0 / Stopwatch.Frequency;
            if (intervalMs <= CadenceResetThresholdMs)
            {
                _frameIntervalMs.Enqueue(Math.Max(0.0, intervalMs));
                while (_frameIntervalMs.Count > SampleWindow)
                {
                    _frameIntervalMs.Dequeue();
                }
                if (intervalMs > 16.7)
                {
                    DroppedFrames++;
                }
            }
        }
        _lastFrameTimestamp = now;
        if (!string.IsNullOrWhiteSpace(deviceRemovedReason))
        {
            DeviceRemovedReason = deviceRemovedReason;
        }
        AverageRenderMs = _renderMs.Count == 0 ? 0.0 : _renderMs.Average();
        AverageFrameIntervalMs = _frameIntervalMs.Count == 0 ? 0.0 : _frameIntervalMs.Average();
        FrameIntervalP95Ms = Percentile(_frameIntervalMs, 0.95);
        FrameIntervalMaxMs = _frameIntervalMs.Count == 0 ? 0.0 : _frameIntervalMs.Max();
        FramePacingJitterMs = StandardDeviation(_frameIntervalMs, AverageFrameIntervalMs);
        AveragePresentMs = _presentMs.Count == 0 ? 0.0 : _presentMs.Average();
        AverageDirtyToPresentMs = _dirtyToPresentMs.Count == 0 ? 0.0 : _dirtyToPresentMs.Average();
    }

    public void RecordResponsiveness(double responsivenessMs)
    {
        _responsivenessMs.Enqueue(Math.Max(0.0, responsivenessMs));
        while (_responsivenessMs.Count > SampleWindow)
        {
            _responsivenessMs.Dequeue();
        }
        AverageResponsivenessMs = _responsivenessMs.Count == 0 ? 0.0 : _responsivenessMs.Average();
    }

    private static double Percentile(IEnumerable<double> samples, double percentile)
    {
        var ordered = samples.OrderBy(value => value).ToArray();
        if (ordered.Length == 0)
        {
            return 0.0;
        }
        var index = Math.Clamp((int)Math.Ceiling(percentile * ordered.Length) - 1, 0, ordered.Length - 1);
        return ordered[index];
    }

    private static double StandardDeviation(IEnumerable<double> samples, double average)
    {
        var values = samples as ICollection<double> ?? samples.ToArray();
        return values.Count == 0
            ? 0.0
            : Math.Sqrt(values.Sum(value => Math.Pow(value - average, 2.0)) / values.Count);
    }
}

internal static class HeadlessRenderer
{
    public static RenderMetrics Measure(ObjDocument document, int frameCount = 60)
    {
        var metrics = new RenderMetrics();
        var bounds = document.Bounds();
        var center = new Vec3(
            (bounds.Min.X + bounds.Max.X) * 0.5f,
            (bounds.Min.Y + bounds.Max.Y) * 0.5f,
            (bounds.Min.Z + bounds.Max.Z) * 0.5f);
        var size = Math.Max(bounds.Max.X - bounds.Min.X, Math.Max(bounds.Max.Y - bounds.Min.Y, bounds.Max.Z - bounds.Min.Z));
        var zoom = size > 0.0001f ? 380.0f / size : 220.0f;
        for (var frame = 0; frame < frameCount; frame++)
        {
            var yaw = -0.35f + frame * 0.01f;
            var pitch = 0.25f;
            var started = Stopwatch.GetTimestamp();
            var projected = 0;
            foreach (var submesh in document.Submeshes)
            {
                foreach (var face in submesh.Faces)
                {
                    foreach (var corner in face.Corners)
                    {
                        if (corner.VertexIndex < 0 || corner.VertexIndex >= submesh.Vertices.Count)
                        {
                            continue;
                        }
                        _ = Project(submesh.Vertices[corner.VertexIndex], center, yaw, pitch, zoom);
                        projected++;
                    }
                }
            }
            var elapsedMs = (Stopwatch.GetTimestamp() - started) * 1000.0 / Stopwatch.Frequency;
            metrics.Record(elapsedMs, 0.0, 0.0, string.Empty);
            metrics.RecordResponsiveness(elapsedMs / Math.Max(1, projected));
        }
        return metrics;
    }

    private static PointF Project(Vec3 vertex, Vec3 center, float yaw, float pitch, float zoom)
    {
        var bounds = (new Vec3(center.X - 1.0f, center.Y - 1.0f, center.Z - 1.0f), new Vec3(center.X + 1.0f, center.Y + 1.0f, center.Z + 1.0f));
        var projected = NetViewportCamera.Create(center, bounds, yaw, pitch, zoom, 0.0f, 0.0f, 2, 2).Project(vertex);
        return new PointF(projected.X - 1.0f, projected.Y - 1.0f);
    }
}

internal sealed record LaunchOptions(
    string InputPackage,
    string MeshPath,
    string MetadataPath,
    string StatusPath,
    string OutputDir,
    string EditOperationsPath,
    string EvaluationPath,
    bool HeadlessSmoke,
    bool Embedded,
    bool DeveloperRendererFallback,
    long ParentHwnd)
{
    public string CloseRequestPath => Path.Combine(InputPackage, "dotnet_close_requested.txt");
    public string MaterialsPath => Path.Combine(InputPackage, "net_materials.json");
    public string ScenePath => Path.Combine(InputPackage, "dotnet_scene.json");

    public static LaunchOptions Parse(string[] args)
    {
        var values = ParseArgs(args);
        string Required(string name)
        {
            if (!values.TryGetValue(name, out var value) || string.IsNullOrWhiteSpace(value))
            {
                throw new ArgumentException($"Missing required argument: --{name}");
            }
            return Path.GetFullPath(value);
        }

        return new LaunchOptions(
            Required("input-package"),
            Required("mesh"),
            Required("metadata"),
            Required("status"),
            Required("output"),
            Required("edit-operations"),
            values.TryGetValue("evaluation", out var evaluation) && !string.IsNullOrWhiteSpace(evaluation)
                ? Path.GetFullPath(evaluation)
                : Path.Combine(Required("input-package"), "dotnet_evaluation.md"),
            values.ContainsKey("headless-smoke"),
            values.ContainsKey("embedded"),
            values.ContainsKey("developer-renderer-fallback")
                || IsTruthy(Environment.GetEnvironmentVariable("CDMW_MESH_DOTNET_DEVELOPER_RENDERER_FALLBACK")),
            values.TryGetValue("parent-hwnd", out var parentHwnd) && long.TryParse(parentHwnd, NumberStyles.Integer, CultureInfo.InvariantCulture, out var hwnd)
                ? hwnd
                : 0L);
    }

    private static bool IsTruthy(string? value)
    {
        return string.Equals(value, "1", StringComparison.OrdinalIgnoreCase)
            || string.Equals(value, "true", StringComparison.OrdinalIgnoreCase)
            || string.Equals(value, "yes", StringComparison.OrdinalIgnoreCase)
            || string.Equals(value, "on", StringComparison.OrdinalIgnoreCase);
    }

    public static LaunchOptions? TryParse(string[] args)
    {
        try
        {
            return Parse(args);
        }
        catch
        {
            return null;
        }
    }

    private static Dictionary<string, string> ParseArgs(string[] args)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i < args.Length; i++)
        {
            var arg = args[i];
            if (!arg.StartsWith("--", StringComparison.Ordinal))
            {
                continue;
            }
            var key = arg[2..];
            if (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
            {
                result[key] = args[++i];
            }
            else
            {
                result[key] = "true";
            }
        }
        return result;
    }
}
