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
    private readonly FixedMetricRing _renderMs = new(SampleWindow);
    private readonly FixedMetricRing _frameIntervalMs = new(SampleWindow);
    private readonly FixedMetricRing _presentMs = new(SampleWindow);
    private readonly FixedMetricRing _dirtyToPresentMs = new(SampleWindow);
    private readonly FixedMetricRing _responsivenessMs = new(SampleWindow);
    private long _lastFrameTimestamp;

    public double AverageRenderMs => _renderMs.Average;
    public double AverageFrameIntervalMs => _frameIntervalMs.Average;
    public double FrameIntervalP95Ms => _frameIntervalMs.Percentile(0.95);
    public double FrameIntervalMaxMs => _frameIntervalMs.Maximum;
    public double FramePacingJitterMs => _frameIntervalMs.StandardDeviation;
    public double AverageFrameMs => AverageFrameIntervalMs > 0.0001 ? AverageFrameIntervalMs : AverageRenderMs;
    public double AveragePresentMs => _presentMs.Average;
    public double AverageDirtyToPresentMs => _dirtyToPresentMs.Average;
    public double AverageResponsivenessMs => _responsivenessMs.Average;
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
        _renderMs.Record(normalizedRenderMs);
        _presentMs.Record(Math.Max(0.0, presentMs));
        _dirtyToPresentMs.Record(Math.Max(0.0, dirtyToPresentMs));

        if (_lastFrameTimestamp > 0)
        {
            var intervalMs = (now - _lastFrameTimestamp) * 1000.0 / Stopwatch.Frequency;
            if (intervalMs <= CadenceResetThresholdMs)
            {
                _frameIntervalMs.Record(Math.Max(0.0, intervalMs));
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
    }

    public void RecordResponsiveness(double responsivenessMs)
    {
        _responsivenessMs.Record(Math.Max(0.0, responsivenessMs));
    }
}

internal sealed class FixedMetricRing
{
    private readonly double[] _values;
    private int _next;
    private int _count;
    private long _version;
    private long _orderedVersion = -1;
    private double[]? _ordered;
    private double _sum;
    private double _sumSquares;

    public FixedMetricRing(int capacity)
    {
        if (capacity <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(capacity));
        }
        _values = new double[capacity];
    }

    public int Count => _count;
    public int Capacity => _values.Length;
    public double Average => _count == 0 ? 0.0 : _sum / _count;
    public double StandardDeviation
    {
        get
        {
            if (_count == 0)
            {
                return 0.0;
            }
            var average = _sum / _count;
            return Math.Sqrt(Math.Max(0.0, (_sumSquares / _count) - (average * average)));
        }
    }
    public double Maximum => _count == 0 ? 0.0 : Ordered()[_count - 1];

    public void Record(double value)
    {
        if (_count == _values.Length)
        {
            var replaced = _values[_next];
            _sum -= replaced;
            _sumSquares -= replaced * replaced;
        }
        else
        {
            _count++;
        }
        _values[_next] = value;
        _next = (_next + 1) % _values.Length;
        _sum += value;
        _sumSquares += value * value;
        _version++;
    }

    public double Percentile(double percentile)
    {
        if (_count == 0)
        {
            return 0.0;
        }
        var values = Ordered();
        var index = Math.Clamp((int)Math.Ceiling(percentile * _count) - 1, 0, _count - 1);
        return values[index];
    }

    public double[] CopyChronological()
    {
        var result = new double[_count];
        var start = _count == _values.Length ? _next : 0;
        for (var index = 0; index < _count; index++)
        {
            result[index] = _values[(start + index) % _values.Length];
        }
        return result;
    }

    private double[] Ordered()
    {
        if (_orderedVersion == _version && _ordered is not null && _ordered.Length == _count)
        {
            return _ordered;
        }
        var ordered = new double[_count];
        Array.Copy(_values, ordered, _count);
        Array.Sort(ordered);
        _ordered = ordered;
        _orderedVersion = _version;
        return ordered;
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
    bool SimplePreview,
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
            values.ContainsKey("simple-preview"),
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
