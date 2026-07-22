using System.Diagnostics;
using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private const double PlacementTransformProtocolIntervalMs = 30.0;
    private const double ViewStateProtocolIntervalMs = 50.0;
    private Dictionary<string, object?>? _pendingPlacementTransformPayload;
    private Dictionary<string, object?>? _pendingViewStatePayload;
    private long _lastPlacementTransformProtocolTimestamp;
    private long _lastViewStateProtocolTimestamp;

    private void HandleViewportEditorEvent(string eventName, Dictionary<string, object?> payload)
    {
        if (string.Equals(eventName, "view_state_changed", StringComparison.OrdinalIgnoreCase))
        {
            _pendingViewStatePayload = new Dictionary<string, object?>(payload);
            FlushPendingViewState();
            return;
        }
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

    private void FlushPendingViewState(bool force = false)
    {
        if (_pendingViewStatePayload is null)
        {
            return;
        }
        var now = Stopwatch.GetTimestamp();
        var elapsedMs = _lastViewStateProtocolTimestamp <= 0
            ? double.MaxValue
            : (now - _lastViewStateProtocolTimestamp) * 1000.0 / Stopwatch.Frequency;
        if (!force && elapsedMs < ViewStateProtocolIntervalMs)
        {
            return;
        }
        var payload = _pendingViewStatePayload;
        _pendingViewStatePayload = null;
        WriteProtocolEvent("view_state_changed", payload);
        _lastViewStateProtocolTimestamp = Stopwatch.GetTimestamp();
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
            ContinuePendingPerformanceCapture();
            var now = DateTime.UtcNow;
            if (_options.Embedded && _options.ParentHwnd > 0 && _embeddedViewportActive)
            {
                if ((now - _lastEmbeddedHostMaintenanceUtc).TotalMilliseconds >= 8)
                {
                    _lastEmbeddedHostMaintenanceUtc = now;
                    MaintainEmbeddedHostSize(new IntPtr(_options.ParentHwnd));
                }
                if ((now - _lastEmbeddedCloseCheckUtc).TotalMilliseconds >= 100)
                {
                    _lastEmbeddedCloseCheckUtc = now;
                    if (File.Exists(_options.CloseRequestPath))
                    {
                        Close();
                        return;
                    }
                }
            }
            if (!_embeddedViewportActive)
            {
                return;
            }
            _viewport.EnsureRenderScheduled();
            FlushPendingPlacementTransform();
            FlushPendingViewState();
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
                    _viewport.RendererBackendName,
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
                PreviewPerformanceCapture.SampleWorkingSet();
                var metricsPayload = MetricsPayload(_viewport.Metrics);
                metricsPayload["renderer"] = _viewport.RendererLiveMetricsPayload();
                metricsPayload["lifecycle_counts"] = LifecycleCountsPayload();
                WriteProtocolEvent("metrics", metricsPayload);
            }
        };
        _timer.Start();
    }

    private void MaintainEmbeddedHostSize(IntPtr parent)
    {
        if (!NativeWindowHost.TryGetClientSize(parent, out var desired))
        {
            return;
        }
        if (Width == desired.Width && Height == desired.Height)
        {
            _pendingEmbeddedParentSize = Size.Empty;
            _pendingEmbeddedParentSizeTimestamp = 0L;
            return;
        }
        var now = Stopwatch.GetTimestamp();
        if (_pendingEmbeddedParentSize != desired)
        {
            if (!_pendingEmbeddedParentSize.IsEmpty)
            {
                _embeddedHostResizeCoalescedCount++;
            }
            _pendingEmbeddedParentSize = desired;
            _pendingEmbeddedParentSizeTimestamp = now;
            _embeddedHostResizeDeferredCount++;
            return;
        }
        if (_pendingEmbeddedParentSizeTimestamp <= 0
            || (now - _pendingEmbeddedParentSizeTimestamp) * 1000.0 / Stopwatch.Frequency < 200.0)
        {
            return;
        }
        NativeWindowHost.ResizeToParent(this, parent);
        _embeddedHostResizeCommitCount++;
        _pendingEmbeddedParentSize = Size.Empty;
        _pendingEmbeddedParentSizeTimestamp = 0L;
    }
}
