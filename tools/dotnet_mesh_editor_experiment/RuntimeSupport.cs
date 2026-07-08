using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed class RenderMetrics
{
    private readonly Queue<double> _frameMs = new();
    private readonly Queue<double> _presentMs = new();
    private readonly Queue<double> _dirtyToPresentMs = new();
    private readonly Queue<double> _responsivenessMs = new();

    public double AverageFrameMs { get; private set; }
    public double AveragePresentMs { get; private set; }
    public double AverageDirtyToPresentMs { get; private set; }
    public double AverageResponsivenessMs { get; private set; }
    public int DroppedFrames { get; private set; }
    public int FrameCount { get; private set; }
    public bool HasRenderedFrame => FrameCount > 0;
    public string DeviceRemovedReason { get; private set; } = string.Empty;
    public double AverageFps => AverageFrameMs > 0.0001 ? 1000.0 / AverageFrameMs : 0.0;

    public void Record(double frameMs, double presentMs, double dirtyToPresentMs, string deviceRemovedReason)
    {
        var normalizedFrameMs = Math.Max(0.0, frameMs);
        FrameCount++;
        _frameMs.Enqueue(normalizedFrameMs);
        _presentMs.Enqueue(Math.Max(0.0, presentMs));
        _dirtyToPresentMs.Enqueue(Math.Max(0.0, dirtyToPresentMs));
        while (_frameMs.Count > 120)
        {
            _frameMs.Dequeue();
        }
        while (_presentMs.Count > 120)
        {
            _presentMs.Dequeue();
        }
        while (_dirtyToPresentMs.Count > 120)
        {
            _dirtyToPresentMs.Dequeue();
        }
        if (normalizedFrameMs > 16.7)
        {
            DroppedFrames++;
        }
        if (!string.IsNullOrWhiteSpace(deviceRemovedReason))
        {
            DeviceRemovedReason = deviceRemovedReason;
        }
        AverageFrameMs = _frameMs.Count == 0 ? 0.0 : _frameMs.Average();
        AveragePresentMs = _presentMs.Count == 0 ? 0.0 : _presentMs.Average();
        AverageDirtyToPresentMs = _dirtyToPresentMs.Count == 0 ? 0.0 : _dirtyToPresentMs.Average();
    }

    public void RecordResponsiveness(double responsivenessMs)
    {
        _responsivenessMs.Enqueue(Math.Max(0.0, responsivenessMs));
        while (_responsivenessMs.Count > 120)
        {
            _responsivenessMs.Dequeue();
        }
        AverageResponsivenessMs = _responsivenessMs.Count == 0 ? 0.0 : _responsivenessMs.Average();
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
