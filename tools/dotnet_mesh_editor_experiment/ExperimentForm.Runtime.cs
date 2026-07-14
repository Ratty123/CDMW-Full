using System.Diagnostics;
using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private const double PlacementTransformProtocolIntervalMs = 30.0;
    private Dictionary<string, object?>? _pendingPlacementTransformPayload;
    private long _lastPlacementTransformProtocolTimestamp;

    private void HandleViewportEditorEvent(string eventName, Dictionary<string, object?> payload)
    {
        if (!string.Equals(eventName, "placement_transform_request", StringComparison.OrdinalIgnoreCase))
        {
            WriteProtocolEvent(eventName, payload);
            return;
        }

        var phase = payload.TryGetValue("placement_phase", out var rawPhase)
            ? Convert.ToString(rawPhase) ?? "update"
            : "update";
        if (string.Equals(phase, "end", StringComparison.OrdinalIgnoreCase))
        {
            _pendingPlacementTransformPayload = null;
            WriteProtocolEvent(eventName, payload);
            _lastPlacementTransformProtocolTimestamp = Stopwatch.GetTimestamp();
            return;
        }

        _pendingPlacementTransformPayload = new Dictionary<string, object?>(payload);
        FlushPendingPlacementTransform();
    }

    private void FlushPendingPlacementTransform(bool force = false)
    {
        if (_pendingPlacementTransformPayload is null)
        {
            return;
        }
        var now = Stopwatch.GetTimestamp();
        var elapsedMs = _lastPlacementTransformProtocolTimestamp <= 0
            ? double.MaxValue
            : (now - _lastPlacementTransformProtocolTimestamp) * 1000.0 / Stopwatch.Frequency;
        if (!force && elapsedMs < PlacementTransformProtocolIntervalMs)
        {
            return;
        }
        var payload = _pendingPlacementTransformPayload;
        _pendingPlacementTransformPayload = null;
        WriteProtocolEvent("placement_transform_request", payload);
        _lastPlacementTransformProtocolTimestamp = Stopwatch.GetTimestamp();
    }

    private void StartFrameTimer()
    {
        _timer.Interval = 16;
        _timer.Tick += (_, _) =>
        {
            var now = DateTime.UtcNow;
            if (_options.Embedded
                && _options.ParentHwnd > 0
                && _embeddedViewportActive
                && (now - _lastEmbeddedHostMaintenanceUtc).TotalMilliseconds >= 100)
            {
                _lastEmbeddedHostMaintenanceUtc = now;
                NativeWindowHost.ResizeToParent(this, new IntPtr(_options.ParentHwnd));
                if (File.Exists(_options.CloseRequestPath))
                {
                    Close();
                    return;
                }
            }
            if (!_embeddedViewportActive)
            {
                return;
            }
            _viewport.EnsureRenderScheduled();
            FlushPendingPlacementTransform();
            if (_readyPendingFirstFrame && _viewport.HasRenderedRequiredPresentation)
            {
                _readyPendingFirstFrame = false;
                PublishReady(_pendingTextureState, _pendingTextureError);
            }
            if ((now - _lastMetricsUiUtc).TotalMilliseconds >= 250)
            {
                _lastMetricsUiUtc = now;
                var metricsText = RendererMetricsText(
                    _viewport.Metrics,
                    RendererStatusWithLifecycle(),
                    compact: _options.Embedded);
                if (!string.Equals(metricsText, _lastMetricsUiText, StringComparison.Ordinal))
                {
                    _lastMetricsUiText = metricsText;
                    _fpsLabel.Text = metricsText;
                }
            }
            if ((now - _lastMetricsProtocolUtc).TotalMilliseconds >= 500)
            {
                _lastMetricsProtocolUtc = now;
                var metricsPayload = MetricsPayload(_viewport.Metrics);
                metricsPayload["renderer"] = RendererStatusWithLifecycle();
                metricsPayload["lifecycle_counts"] = LifecycleCountsPayload();
                WriteProtocolEvent("metrics", metricsPayload);
            }
        };
        _timer.Start();
    }
}
