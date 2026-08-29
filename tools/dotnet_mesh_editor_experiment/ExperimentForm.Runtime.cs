using System.Diagnostics;
using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private const double PlacementTransformProtocolIntervalMs = 30.0;
    private const double ViewStateProtocolIntervalMs = 50.0;
    // One frame, matching the timer that flushes this. The host's live-stroke
    // dispatcher is single-flight and coalesces to depth one, so raising the
    // emission rate costs it nothing and only makes the sample it picks up
    // younger -- the 30ms gate meant Move and Grab acted on pointer positions
    // that were already up to two frames stale before the round trip started.
    private const double StrokeUpdateProtocolIntervalMs = 16.0;
    private Dictionary<string, object?>? _pendingPlacementTransformPayload;
    private Dictionary<string, object?>? _pendingViewStatePayload;
    private Dictionary<string, object?>? _pendingStrokeUpdatePayload;
    private long _lastPlacementTransformProtocolTimestamp;
    private long _lastViewStateProtocolTimestamp;
    private long _lastStrokeUpdateProtocolTimestamp;

    private void HandleViewportEditorEvent(string eventName, Dictionary<string, object?> payload)
    {
        if (string.Equals(eventName, "select_request", StringComparison.OrdinalIgnoreCase))
        {
            RefreshCreatePartFromSelectionButton();
        }
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
        // newest intermediate sample carries the projection state, while the
        // bounded screen path preserves endpoints, turns, and spaced samples;
        // the phases that carry meaning are always written through.
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
        if (string.Equals(phase, "end", StringComparison.OrdinalIgnoreCase)
            || string.Equals(phase, "begin", StringComparison.OrdinalIgnoreCase))
        {
            // Terminal samples are written at once. "begin" carries the exact start
            // placement the host subtracts drag deltas from; coalescing it behind
            // the next update would replace the one value that must be exact.
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
        var path = StrokeSamplePath(pending, pendingDrag);
        foreach (var point in StrokeSamplePath(merged, newestDrag))
        {
            if (path.Count > 0
                && Equals(path[^1].GetValueOrDefault("x"), point.GetValueOrDefault("x"))
                && Equals(path[^1].GetValueOrDefault("y"), point.GetValueOrDefault("y")))
            {
                continue;
            }
            path.Add(point);
        }
        merged["screen_path"] = BoundedProtocolStrokePath(path);
        return merged;
    }

    internal static List<Dictionary<string, object?>> BoundedProtocolStrokePath(
        IReadOnlyList<Dictionary<string, object?>> path)
    {
        var samples = new StrokeSampleBuffer();
        for (var index = 0; index < path.Count; index += 1)
        {
            try
            {
                var x = Convert.ToDouble(path[index].GetValueOrDefault("x"));
                var y = Convert.ToDouble(path[index].GetValueOrDefault("y"));
                if (double.IsFinite(x) && double.IsFinite(y))
                {
                    samples.Add(
                        new Point((int)Math.Round(x), (int)Math.Round(y)),
                        index);
                }
            }
            catch (FormatException)
            {
                // The protocol parser reports malformed coordinates. They
                // must not bypass this size bound by failing simplification.
            }
            catch (InvalidCastException)
            {
                // The protocol parser reports malformed coordinates. They
                // must not bypass this size bound by failing simplification.
            }
            catch (OverflowException)
            {
                // The protocol parser will report malformed coordinates. They
                // must not bypass this size bound by failing simplification.
            }
        }
        return samples.Select(point => new Dictionary<string, object?>
        {
            ["x"] = (double)point.X,
            ["y"] = (double)point.Y,
        }).ToList();
    }

    private static List<Dictionary<string, object?>> StrokeSamplePath(
        Dictionary<string, object?> payload,
        Dictionary<string, object?> drag)
    {
        if (payload.GetValueOrDefault("screen_path") is IEnumerable<Dictionary<string, object?>> existing)
        {
            return existing.Select(point => new Dictionary<string, object?>(point)).ToList();
        }
        return new List<Dictionary<string, object?>>
        {
            new()
            {
                ["x"] = drag.GetValueOrDefault("start_x"),
                ["y"] = drag.GetValueOrDefault("start_y"),
            },
            new()
            {
                ["x"] = drag.GetValueOrDefault("end_x"),
                ["y"] = drag.GetValueOrDefault("end_y"),
            },
        };
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
            if (_options.Embedded && _embeddedParentHwnd > 0 && _embeddedViewportActive)
            {
                if ((now - _lastEmbeddedHostMaintenanceUtc).TotalMilliseconds >= 8)
                {
                    _lastEmbeddedHostMaintenanceUtc = now;
                    MaintainEmbeddedHostSize(new IntPtr(_embeddedParentHwnd));
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
        // Once the host is gone the close is already under way, and resizing to
        // a dead parent only recreates a handle on a disposing form -- which
        // faults into the UI exception guard and turns a clean exit into a
        // reported crash.
        if (_hostDisconnected || IsDisposed || Disposing)
        {
            return;
        }
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
