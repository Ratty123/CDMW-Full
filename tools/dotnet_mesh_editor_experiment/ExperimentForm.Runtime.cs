using System.Diagnostics;
using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private const double PlacementTransformProtocolIntervalMs = 30.0;
    private const double ViewStateProtocolIntervalMs = 50.0;
    private const double StrokeUpdateProtocolIntervalMs = 30.0;
    private Dictionary<string, object?>? _pendingPlacementTransformPayload;
    private Dictionary<string, object?>? _pendingViewStatePayload;
    private Dictionary<string, object?>? _pendingStrokeUpdatePayload;
    private long _lastPlacementTransformProtocolTimestamp;
    private long _lastViewStateProtocolTimestamp;
    private long _lastStrokeUpdateProtocolTimestamp;

    private void HandleViewportEditorEvent(string eventName, Dictionary<string, object?> payload)
    {
        if (string.Equals(eventName, "view_state_changed", StringComparison.OrdinalIgnoreCase))
        {
            _pendingViewStatePayload = new Dictionary<string, object?>(payload);
            FlushPendingViewState();
            return;
        }
        // A drag reports every mouse move, and each stroke payload carries a
        // projection matrix per editable submesh. Left unpaced that is megabytes
        // per second of protocol traffic on a multi-part model, which overruns
        // the host's read buffer and takes the editor down mid-stroke. Only the
        // newest intermediate sample matters, so coalesce to it; the phases that
        // carry meaning are always written through.
        if (string.Equals(eventName, "stroke_update", StringComparison.OrdinalIgnoreCase))
        {
            _pendingStrokeUpdatePayload = CoalesceStrokeSample(_pendingStrokeUpdatePayload, payload);
            FlushPendingStrokeUpdate();
            return;
        }
        if (eventName is "stroke_begin" or "stroke_end" or "stroke_cancel")
        {
            // The terminal phase absorbs whatever span is still pending, so the
            // host never sees an update arrive after the stroke closed and no
            // pointer motion is dropped on the way out.
            var terminal = CoalesceStrokeSample(_pendingStrokeUpdatePayload, payload);
            _pendingStrokeUpdatePayload = null;
            WriteProtocolEvent(eventName, terminal);
            _lastStrokeUpdateProtocolTimestamp = Stopwatch.GetTimestamp();
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

    /// <summary>
    /// Folds a pending stroke sample into the newest one. Each sample's
    /// screen_drag is the motion since the previous sample, so a coalesced
    /// sample has to keep the older start point: taking only the newest sample
    /// would silently discard the pointer motion the dropped ones carried.
    /// </summary>
    private static Dictionary<string, object?> CoalesceStrokeSample(
        Dictionary<string, object?>? pending,
        Dictionary<string, object?> newest)
    {
        var merged = new Dictionary<string, object?>(newest);
        if (pending is null
            || pending.GetValueOrDefault("screen_drag") is not Dictionary<string, object?> pendingDrag
            || merged.GetValueOrDefault("screen_drag") is not Dictionary<string, object?> newestDrag)
        {
            return merged;
        }
        var drag = new Dictionary<string, object?>(newestDrag);
        foreach (var key in new[] { "start_x", "start_y" })
        {
            if (pendingDrag.TryGetValue(key, out var start))
            {
                drag[key] = start;
            }
        }
        merged["screen_drag"] = drag;
        return merged;
    }

    private void FlushPendingStrokeUpdate(bool force = false)
    {
        if (_pendingStrokeUpdatePayload is null)
        {
            return;
        }
        var now = Stopwatch.GetTimestamp();
        var elapsedMs = _lastStrokeUpdateProtocolTimestamp <= 0
            ? double.MaxValue
            : (now - _lastStrokeUpdateProtocolTimestamp) * 1000.0 / Stopwatch.Frequency;
        if (!force && elapsedMs < StrokeUpdateProtocolIntervalMs)
        {
            return;
        }
        var payload = _pendingStrokeUpdatePayload;
        _pendingStrokeUpdatePayload = null;
        WriteProtocolEvent("stroke_update", payload);
        _lastStrokeUpdateProtocolTimestamp = Stopwatch.GetTimestamp();
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
            FlushPendingStrokeUpdate();
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
