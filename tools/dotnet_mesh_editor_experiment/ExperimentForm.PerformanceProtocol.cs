using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private Dictionary<string, object?>? _performanceResourcesBefore;
    private PreviewPerformanceCaptureOptions? _pendingPerformanceCaptureOptions;
    private JsonElement? _pendingPerformanceCaptureRequest;
    private int _performanceWarmupStartFrameCount;
    private Task? _performanceReportTask;

    private void StartPerformanceRenderPump(double targetHz)
    {
        _viewport.StartPerformanceRenderPump(targetHz);
    }

    private void StopPerformanceRenderPump()
    {
        _viewport.StopPerformanceRenderPump();
    }

    private void HandlePerformanceCaptureStart(JsonElement root)
    {
        if (!TryPerformanceCorrelation(root, out var captureId, out var rejection))
        {
            WritePerformanceProtocolResult("performance_capture_complete", root, captureId, "rejected", rejection);
            return;
        }
        if (PreviewPerformanceCapture.IsActive
            || _pendingPerformanceCaptureOptions is not null
            || _performanceReportTask is { IsCompleted: false })
        {
            WritePerformanceProtocolResult(
                "performance_capture_complete",
                root,
                captureId,
                "rejected",
                "Another performance capture is already active.");
            return;
        }
        string reportPath;
        try
        {
            reportPath = ResolvePerformanceReportPath(JsonString(root, "report_path"));
        }
        catch (Exception ex) when (ex is ArgumentException or IOException or UnauthorizedAccessException or NotSupportedException or PathTooLongException)
        {
            WritePerformanceProtocolResult("performance_capture_complete", root, captureId, "rejected", ex.Message);
            return;
        }
        var durationSeconds = JsonDoubleValue(root, "duration_seconds", 30.0);
        var targetHz = JsonDoubleValue(root, "target_hz", 144.0);
        var warmupFrames = (int)Math.Clamp(JsonLongValue(root, "warmup_frames"), 0, 10_000);
        var width = (int)Math.Clamp(JsonLongValue(root, "width"), 64, 7680);
        var height = (int)Math.Clamp(JsonLongValue(root, "height"), 64, 4320);
        if (width == 64 && !root.TryGetProperty("width", out _))
        {
            width = Math.Max(64, _viewport.ClientSize.Width);
        }
        if (height == 64 && !root.TryGetProperty("height", out _))
        {
            height = Math.Max(64, _viewport.ClientSize.Height);
        }
        var options = new PreviewPerformanceCaptureOptions(
            captureId,
            "resident_protocol",
            reportPath,
            durationSeconds,
            targetHz,
            warmupFrames,
            width,
            height,
            JsonObjectPayload(root, "asset_provenance"));
        if (warmupFrames > 0)
        {
            _pendingPerformanceCaptureOptions = options;
            _pendingPerformanceCaptureRequest = root.Clone();
            _performanceWarmupStartFrameCount = _viewport.Metrics.FrameCount;
            StartPerformanceRenderPump(targetHz);
            WritePerformanceProtocolResult("performance_capture_warming", root, captureId, "warming", string.Empty);
            return;
        }

        StartPreparedPerformanceCapture(options, root);
    }

    private void ContinuePendingPerformanceCapture()
    {
        var options = _pendingPerformanceCaptureOptions;
        var request = _pendingPerformanceCaptureRequest;
        if (options is null || request is null)
        {
            return;
        }
        if (_viewport.Metrics.FrameCount - _performanceWarmupStartFrameCount < options.WarmupFrames)
        {
            return;
        }
        _pendingPerformanceCaptureOptions = null;
        _pendingPerformanceCaptureRequest = null;
        StartPreparedPerformanceCapture(options, request.Value);
    }

    private void StartPreparedPerformanceCapture(PreviewPerformanceCaptureOptions options, JsonElement request)
    {
        try
        {
            _viewport.PrepareRendererPerformanceCapture();
            _performanceResourcesBefore = _viewport.RendererResourceMetricsPayload();
            GC.Collect(2, GCCollectionMode.Forced, blocking: true, compacting: false);
            GC.WaitForPendingFinalizers();
            GC.Collect(2, GCCollectionMode.Forced, blocking: true, compacting: false);
            if (!PreviewPerformanceCapture.TryStart(options, out _, out var startError))
            {
                _performanceResourcesBefore = null;
                StopPerformanceRenderPump();
                WritePerformanceProtocolResult(
                    "performance_capture_complete",
                    request,
                    options.CaptureId,
                    "rejected",
                    startError);
                return;
            }
            StartPerformanceRenderPump(options.TargetHz);
        }
        catch (Exception ex) when (ex is ArgumentException or ArgumentOutOfRangeException or InvalidOperationException)
        {
            _performanceResourcesBefore = null;
            StopPerformanceRenderPump();
            WritePerformanceProtocolResult(
                "performance_capture_complete",
                request,
                options.CaptureId,
                "rejected",
                ex.Message);
            return;
        }
        WritePerformanceProtocolResult(
            "performance_capture_started",
            request,
            options.CaptureId,
            "capturing",
            string.Empty);
    }

    private void HandlePerformanceCaptureStop(JsonElement root)
    {
        if (!TryPerformanceCorrelation(root, out var captureId, out var rejection))
        {
            WritePerformanceProtocolResult("performance_capture_complete", root, captureId, "rejected", rejection);
            return;
        }
        if (_pendingPerformanceCaptureOptions is { } pending
            && string.Equals(pending.CaptureId, captureId, StringComparison.Ordinal))
        {
            _pendingPerformanceCaptureOptions = null;
            _pendingPerformanceCaptureRequest = null;
            StopPerformanceRenderPump();
            WritePerformanceProtocolResult(
                "performance_capture_complete",
                root,
                captureId,
                "cancelled",
                "Performance capture was stopped during warm-up.");
            return;
        }
        var snapshot = PreviewPerformanceCapture.Stop(captureId, out var stopError);
        if (snapshot is null)
        {
            WritePerformanceProtocolResult("performance_capture_complete", root, captureId, "rejected", stopError);
            return;
        }
        StopPerformanceRenderPump();
        var resourcesBefore = _performanceResourcesBefore
            ?? new Dictionary<string, object?> { ["available"] = false };
        _performanceResourcesBefore = null;
        var resourcesAfter = _viewport.RendererResourceMetricsPayload();
        var lifecycle = LifecycleCountsPayload();
        var rendererStatus = _viewport.RendererStatusPayload();
        lifecycle["backend"] = rendererStatus.GetValueOrDefault("backend");
        lifecycle["edit_backend"] = "cdmw_mesh_core_0.1";
        lifecycle["viewport_client_width"] = _viewport.ClientSize.Width;
        lifecycle["viewport_client_height"] = _viewport.ClientSize.Height;
        lifecycle["performance_render_pump"] = "threadpool_timer_ui_owner_post";
        lifecycle["performance_timer_resolution_requested_ms"] = 1;
        lifecycle["performance_timer_resolution_begin_result"] = _viewport.PerformanceTimerResolutionBeginResult;
        var completionEnvelope = PerformanceCorrelationPayload(root, captureId);
        WritePerformanceProtocolResult("performance_capture_stopping", root, captureId, "writing", string.Empty);
        _performanceReportTask = Task.Run(() => BuildAndPublishPerformanceReport(
            snapshot,
            resourcesBefore,
            resourcesAfter,
            lifecycle,
            completionEnvelope));
    }

    private void HandlePerformanceHeartbeat(JsonElement root)
    {
        var captureId = JsonString(root, "capture_id").Trim();
        if (string.IsNullOrWhiteSpace(captureId))
        {
            return;
        }
        PreviewPerformanceCapture.RecordHeartbeat(PreviewPerformanceHeartbeatKind.QtHost);
    }

    private void CancelPerformanceCaptureForShutdown()
    {
        StopPerformanceRenderPump();
        var pendingOptions = _pendingPerformanceCaptureOptions;
        var pendingRequest = _pendingPerformanceCaptureRequest;
        _pendingPerformanceCaptureOptions = null;
        _pendingPerformanceCaptureRequest = null;
        if (pendingOptions is not null && pendingRequest is not null)
        {
            WritePerformanceProtocolResult(
                "performance_capture_complete",
                pendingRequest.Value,
                pendingOptions.CaptureId,
                "cancelled",
                "Performance capture warm-up was cancelled during helper shutdown.");
        }
        if (!PreviewPerformanceCapture.IsActive)
        {
            return;
        }
        var snapshot = PreviewPerformanceCapture.Stop(string.Empty, out _);
        _performanceResourcesBefore = null;
        if (snapshot is null)
        {
            return;
        }
        WriteProtocolEvent("performance_capture_complete", new Dictionary<string, object?>
        {
            ["capture_id"] = snapshot.Options.CaptureId,
            ["status"] = "cancelled",
            ["schema"] = PreviewPerformanceReport.Schema,
            ["message"] = "Performance capture was cancelled during helper shutdown.",
        });
    }

    private void BuildAndPublishPerformanceReport(
        PreviewPerformanceCaptureSnapshot snapshot,
        IReadOnlyDictionary<string, object?> resourcesBefore,
        IReadOnlyDictionary<string, object?> resourcesAfter,
        IReadOnlyDictionary<string, object?> lifecycle,
        Dictionary<string, object?> completionEnvelope)
    {
        Dictionary<string, object?> completion;
        try
        {
            var report = PreviewPerformanceReport.Build(snapshot, resourcesBefore, resourcesAfter, lifecycle);
            PreviewPerformanceReport.WriteAtomic(snapshot.Options.ReportPath, report);
            var file = new FileInfo(snapshot.Options.ReportPath);
            var sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(file.FullName))).ToLowerInvariant();
            completion = new Dictionary<string, object?>(completionEnvelope, StringComparer.Ordinal)
            {
                ["status"] = report.GetValueOrDefault("ok") is true ? "complete" : "failed_gates",
                ["ok"] = report.GetValueOrDefault("ok") is true,
                ["schema"] = PreviewPerformanceReport.Schema,
                ["report_path"] = file.FullName,
                ["report_size_bytes"] = file.Length,
                ["report_sha256"] = sha256,
                ["frame_pacing"] = report.GetValueOrDefault("frame_pacing"),
                ["gates"] = report.GetValueOrDefault("gates"),
            };
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or InvalidOperationException)
        {
            completion = new Dictionary<string, object?>(completionEnvelope, StringComparer.Ordinal)
            {
                ["status"] = "error",
                ["ok"] = false,
                ["schema"] = PreviewPerformanceReport.Schema,
                ["report_path"] = snapshot.Options.ReportPath,
                ["message"] = ex.Message,
            };
        }
        try
        {
            WritePreparedProtocolEventThreadSafe("performance_capture_complete", completion);
        }
        catch (InvalidOperationException)
        {
        }
    }

    public bool DrainPerformanceReport(TimeSpan grace)
    {
        var task = _performanceReportTask;
        if (task is null)
        {
            return true;
        }
        try
        {
            return task.Wait(grace);
        }
        catch (AggregateException)
        {
            return false;
        }
    }

    private bool TryPerformanceCorrelation(JsonElement root, out string captureId, out string rejection)
    {
        captureId = JsonString(root, "capture_id").Trim();
        if (string.IsNullOrWhiteSpace(captureId))
        {
            rejection = "performance capture requires capture_id";
            return false;
        }
        var requestId = JsonLongValue(root, "request_id");
        var processGeneration = JsonLongValue(root, "process_generation");
        if (requestId <= 0)
        {
            rejection = "performance capture requires request_id";
            return false;
        }
        if (_residentProcessGeneration > 0 && processGeneration != _residentProcessGeneration)
        {
            rejection = "performance capture process_generation is stale";
            return false;
        }
        var sessionId = JsonString(root, "session_id").Trim();
        if (!string.IsNullOrWhiteSpace(_residentMaterialSessionId)
            && !string.Equals(sessionId, _residentMaterialSessionId, StringComparison.Ordinal))
        {
            rejection = "performance capture session_id is stale";
            return false;
        }
        rejection = string.Empty;
        return true;
    }

    private string ResolvePerformanceReportPath(string requestedPath)
    {
        var outputRoot = Path.GetFullPath(_options.OutputDir);
        var reportPath = string.IsNullOrWhiteSpace(requestedPath)
            ? Path.Combine(outputRoot, $"dotnet-preview-performance-{Guid.NewGuid():N}.json")
            : Path.IsPathRooted(requestedPath)
                ? Path.GetFullPath(requestedPath)
                : Path.GetFullPath(Path.Combine(outputRoot, requestedPath));
        var outputPrefix = outputRoot.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        if (!reportPath.StartsWith(outputPrefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException("Performance report must remain inside the package output directory.");
        }
        if (CapturePathTraversesReparsePoint(outputRoot, reportPath))
        {
            throw new ArgumentException("Performance report must not traverse a reparse-point alias.");
        }
        return reportPath;
    }

    private void WritePerformanceProtocolResult(
        string eventName,
        JsonElement request,
        string captureId,
        string status,
        string message)
    {
        var payload = PerformanceCorrelationPayload(request, captureId);
        payload["status"] = status;
        payload["schema"] = PreviewPerformanceReport.Schema;
        if (!string.IsNullOrWhiteSpace(message))
        {
            payload["message"] = message;
        }
        WriteProtocolEvent(eventName, payload);
    }

    private static Dictionary<string, object?> PerformanceCorrelationPayload(JsonElement request, string captureId) => new()
    {
        ["capture_id"] = captureId,
        ["session_id"] = JsonString(request, "session_id").Trim(),
        ["request_id"] = JsonLongValue(request, "request_id"),
        ["process_generation"] = JsonLongValue(request, "process_generation"),
        ["protocol_version"] = Math.Max(2, JsonLongValue(request, "protocol_version")),
    };

    private static Dictionary<string, object?> JsonObjectPayload(JsonElement root, string propertyName)
    {
        if (!root.TryGetProperty(propertyName, out var value) || value.ValueKind != JsonValueKind.Object)
        {
            return new Dictionary<string, object?>();
        }
        return value.EnumerateObject().ToDictionary(
            property => property.Name,
            property => (object?)property.Value.Clone(),
            StringComparer.Ordinal);
    }

    private static double JsonDoubleValue(JsonElement root, string propertyName, double fallback)
    {
        if (!root.TryGetProperty(propertyName, out var value))
        {
            return fallback;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number) && double.IsFinite(number))
        {
            return number;
        }
        if (value.ValueKind == JsonValueKind.String
            && double.TryParse(value.GetString(), NumberStyles.Float, CultureInfo.InvariantCulture, out number)
            && double.IsFinite(number))
        {
            return number;
        }
        return fallback;
    }
}
