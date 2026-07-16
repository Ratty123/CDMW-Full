using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Vortice.Direct3D11;
using Vortice.DXGI;

namespace Cdmw.MeshEditorExperiment;

internal static class PreviewPerformanceReport
{
    public const string Schema = "cdmw_dotnet_preview_performance_v1";
    private const double FrameP95BudgetMs = 8.68;
    private const double FrameP99BudgetMs = 13.89;
    private const double MaximumHitchRatio = 0.001;
    private const double MaximumFrameMs = 20.83;
    private const double InputP95BudgetMs = 13.89;
    private const double HeartbeatBudgetMs = 33.3;
    private const double SafetyBudgetMs = 16.7;
    private const double MaximumGrowthRatio = 0.05;

    public static Dictionary<string, object?> Build(
        PreviewPerformanceCaptureSnapshot capture,
        IReadOnlyDictionary<string, object?> resourcesBefore,
        IReadOnlyDictionary<string, object?> resourcesAfter,
        IReadOnlyDictionary<string, object?> lifecycle,
        IReadOnlyDictionary<string, object?>? externalEvidence = null)
    {
        // Both capture entry points complete their warm-up before TryStart, so
        // every frame in the snapshot is part of the measured interval.
        var capturedFrames = capture.Frames;
        var intervals = capturedFrames
            .Select(frame => frame.IntervalMs)
            .Where(double.IsFinite)
            .ToArray();
        var render = capturedFrames.Select(frame => frame.RenderMs).Where(double.IsFinite).ToArray();
        var present = capturedFrames.Select(frame => frame.PresentMs).Where(double.IsFinite).ToArray();
        var gpu = capturedFrames.Select(frame => frame.GpuMs).Where(value => double.IsFinite(value) && value >= 0.0).ToArray();
        var inputToPresent = capturedFrames
            .Select(frame => frame.InputToPresentMs)
            .Where(double.IsFinite)
            .ToArray();
        var managedAllocations = capturedFrames.Select(frame => frame.ManagedAllocatedBytes).ToArray();
        var winFormsHeartbeat = capture.Heartbeats
            .Where(sample => sample.Kind == PreviewPerformanceHeartbeatKind.WinForms)
            .Select(sample => sample.GapMs)
            .ToArray();
        var qtHeartbeat = capture.Heartbeats
            .Where(sample => sample.Kind == PreviewPerformanceHeartbeatKind.QtHost)
            .Select(sample => sample.GapMs)
            .ToArray();
        var refreshBudgetMs = 1000.0 / capture.Options.TargetHz;
        var overP99Budget = intervals.Count(value => value > FrameP99BudgetMs);
        var overMaximumBudget = intervals.Count(value => value > MaximumFrameMs);
        var hitchRatio = intervals.Length == 0 ? 1.0 : overP99Budget / (double)intervals.Length;
        var frameSummary = Distribution(intervals);
        var renderSummary = Distribution(render);
        var presentSummary = Distribution(present);
        var gpuSummary = Distribution(gpu);
        var inputSummary = Distribution(inputToPresent);
        var winFormsHeartbeatSummary = Distribution(winFormsHeartbeat);
        var qtHeartbeatSummary = Distribution(qtHeartbeat);
        var workingSetGrowth = GrowthRatio(capture.WorkingSetBytesStart, capture.WorkingSetBytesStop);
        var vramStart = UnsignedMetric(resourcesBefore, "dxgi_local_memory_current_usage_bytes");
        var vramStop = UnsignedMetric(resourcesAfter, "dxgi_local_memory_current_usage_bytes");
        var vramGrowth = GrowthRatio(vramStart, vramStop);
        var gcDeltas = Enumerable.Range(0, 3)
            .Select(index => capture.GcCountsStop[index] - capture.GcCountsStart[index])
            .ToArray();
        var frameP95 = SummaryMetric(frameSummary, "p95_ms");
        var frameP99 = SummaryMetric(frameSummary, "p99_ms");
        var frameMaximum = SummaryMetric(frameSummary, "max_ms");
        var inputP95 = SummaryMetric(inputSummary, "p95_ms");
        var gpuP99 = SummaryMetric(gpuSummary, "p99_ms");
        var gpuQuerySlots = Math.Max(0L, SignedMetric(resourcesAfter, "gpu_timestamp_query_slots"));
        var gpuQueriesIssued = MetricDelta(resourcesBefore, resourcesAfter, "gpu_timestamp_queries_issued");
        var gpuQueriesResolved = MetricDelta(resourcesBefore, resourcesAfter, "gpu_timestamp_queries_resolved");
        var gpuQueriesDisjoint = MetricDelta(resourcesBefore, resourcesAfter, "gpu_timestamp_queries_disjoint");
        var gpuQueriesDropped = MetricDelta(resourcesBefore, resourcesAfter, "gpu_timestamp_queries_dropped");
        var minimumResolvedGpuQueries = Math.Max(1L, gpuQueriesIssued - gpuQuerySlots);
        var validResolvedGpuQueries = Math.Max(0L, gpuQueriesResolved - gpuQueriesDisjoint);
        var allocationsTotal = managedAllocations.Sum();
        var inputsOutstanding = Math.Max(0L, capture.InputsReceived - capture.InputsPresented - capture.InputsCoalesced);
        var residentCapture = string.Equals(capture.Options.Source, "resident_protocol", StringComparison.Ordinal);
        var configuredResolution = SignedMetric(lifecycle, "viewport_client_width") == capture.Options.Width
            && SignedMetric(lifecycle, "viewport_client_height") == capture.Options.Height;
        var gates = new Dictionary<string, bool>
        {
            ["frame_samples_present"] = intervals.Length >= Math.Max(1, (int)Math.Floor(capture.Options.DurationSeconds * capture.Options.TargetHz * 0.75)),
            ["frame_interval_p95_at_most_8_68_ms"] = intervals.Length > 0 && frameP95 <= FrameP95BudgetMs,
            ["frame_interval_p99_at_most_13_89_ms"] = intervals.Length > 0 && frameP99 <= FrameP99BudgetMs,
            ["fewer_than_0_1_percent_over_13_89_ms"] = intervals.Length > 0 && hitchRatio < MaximumHitchRatio,
            ["no_frame_over_20_83_ms"] = intervals.Length > 0 && overMaximumBudget == 0,
            ["input_to_present_p95_at_most_13_89_ms"] = inputToPresent.Length > 0 && inputP95 <= InputP95BudgetMs,
            ["host_heartbeat_at_most_33_3_ms"] = winFormsHeartbeat.Length > 0
                && SummaryMetric(winFormsHeartbeatSummary, "max_ms") <= HeartbeatBudgetMs
                && (!residentCapture
                    || (qtHeartbeat.Length > 0
                        && SummaryMetric(qtHeartbeatSummary, "max_ms") <= HeartbeatBudgetMs)),
            ["zero_managed_allocations_in_captured_frames"] = allocationsTotal == 0,
            ["zero_gen1_collections"] = gcDeltas[1] == 0,
            ["zero_gen2_collections"] = gcDeltas[2] == 0,
            ["protocol_queue_depth_at_most_one"] = capture.MaximumProtocolQueueDepth <= 1,
            ["every_captured_input_presented"] = capture.InputsReceived > 0 && inputsOutstanding == 0,
            ["every_input_accounted_for"] = capture.InputsReceived > 0 && inputsOutstanding == 0,
            ["zero_renderer_restarts_or_resets"] = SignedMetric(lifecycle, "process_restart_count") == 0
                && SignedMetric(lifecycle, "device_reset_count") == 0,
            ["stable_geometry_resource_identity"] = SignedMetric(resourcesBefore, "geometry_buffer_identity") == SignedMetric(resourcesAfter, "geometry_buffer_identity"),
            ["stable_material_binding_identity"] = SignedMetric(resourcesBefore, "material_binding_array_identity") == SignedMetric(resourcesAfter, "material_binding_array_identity"),
            ["post_warmup_ram_growth_at_most_five_percent"] = workingSetGrowth <= MaximumGrowthRatio,
            ["post_warmup_vram_growth_at_most_five_percent"] = vramStart == 0 || vramGrowth <= MaximumGrowthRatio,
            ["cpu_p99_below_60hz_safety_budget"] = render.Length > 0 && SummaryMetric(renderSummary, "p99_ms") < SafetyBudgetMs,
            ["gpu_p99_below_60hz_safety_budget_or_unavailable"] = gpu.Length == 0 || gpuP99 < SafetyBudgetMs,
            ["gpu_timing_samples_present"] = gpu.Length > 0,
            ["gpu_timestamp_query_coverage"] = gpuQueriesIssued > 0
                && gpuQueriesResolved >= minimumResolvedGpuQueries
                && gpu.LongLength == validResolvedGpuQueries,
            ["zero_gpu_timestamp_disjoint_or_dropped"] = gpuQueriesDisjoint == 0
                && gpuQueriesDropped == 0,
            ["configured_resolution"] = configuredResolution,
            ["no_capture_buffer_overflow"] = capture.DroppedFrameSamples == 0
                && capture.DroppedPhaseSamples == 0
                && capture.DroppedHeartbeatSamples == 0,
        };
        var ok = gates.Values.All(value => value);
        return new Dictionary<string, object?>
        {
            ["schema"] = Schema,
            ["schema_version"] = 1,
            ["ok"] = ok,
            ["generated_at_utc"] = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture),
            ["capture"] = new Dictionary<string, object?>
            {
                ["capture_id"] = capture.Options.CaptureId,
                ["source"] = capture.Options.Source,
                ["started_at_utc"] = capture.StartedAtUtc.ToString("O", CultureInfo.InvariantCulture),
                ["stopped_at_utc"] = capture.StoppedAtUtc.ToString("O", CultureInfo.InvariantCulture),
                ["elapsed_seconds"] = capture.ElapsedSeconds,
                ["requested_duration_seconds"] = capture.Options.DurationSeconds,
                ["target_hz"] = capture.Options.TargetHz,
                ["target_interval_ms"] = refreshBudgetMs,
                ["warmup_frames_excluded"] = capture.Options.WarmupFrames,
                ["width"] = capture.Options.Width,
                ["height"] = capture.Options.Height,
                ["asset_provenance"] = capture.Options.AssetProvenance,
            },
            ["raw"] = new Dictionary<string, object?>
            {
                ["frame_intervals_ms"] = intervals,
                ["render_ms"] = render,
                ["present_ms"] = present,
                ["gpu_ms"] = gpu,
                ["input_to_present_ms"] = inputToPresent,
                ["managed_allocated_bytes_per_frame"] = managedAllocations,
                ["winforms_heartbeat_gaps_ms"] = winFormsHeartbeat,
                ["qt_heartbeat_gaps_ms"] = qtHeartbeat,
                ["frames"] = capturedFrames.Select(FramePayload).ToArray(),
                ["phases"] = capture.Phases.Select(PhasePayload).ToArray(),
            },
            ["frame_pacing"] = new Dictionary<string, object?>
            {
                ["summary"] = frameSummary,
                ["refresh_misses"] = intervals.Count(value => value > refreshBudgetMs),
                ["over_13_89_ms_count"] = overP99Budget,
                ["over_13_89_ms_ratio"] = hitchRatio,
                ["over_20_83_ms_count"] = overMaximumBudget,
                ["effective_fps"] = intervals.Length == 0 || intervals.Average() <= 0.0 ? 0.0 : 1000.0 / intervals.Average(),
            },
            ["timings"] = new Dictionary<string, object?>
            {
                ["render"] = renderSummary,
                ["present"] = presentSummary,
                ["gpu"] = gpuSummary,
                ["gpu_timestamp_queries"] = new Dictionary<string, object?>
                {
                    ["available"] = gpu.Length > 0,
                    ["method"] = gpu.Length > 0 ? "d3d11_timestamp_disjoint_delayed_nonblocking" : "unavailable",
                    ["query_slots"] = gpuQuerySlots,
                    ["issued"] = gpuQueriesIssued,
                    ["resolved"] = gpuQueriesResolved,
                    ["disjoint"] = gpuQueriesDisjoint,
                    ["dropped"] = gpuQueriesDropped,
                    ["minimum_required_resolved"] = minimumResolvedGpuQueries,
                    ["valid_samples"] = gpu.LongLength,
                },
                ["input_to_present"] = inputSummary,
                ["winforms_heartbeat"] = winFormsHeartbeatSummary,
                ["qt_heartbeat"] = qtHeartbeatSummary,
                ["phases"] = PhaseSummaries(capture.Phases),
            },
            ["managed_runtime"] = new Dictionary<string, object?>
            {
                ["allocated_bytes_start"] = capture.TotalAllocatedBytesStart,
                ["allocated_bytes_stop"] = capture.TotalAllocatedBytesStop,
                ["allocated_bytes_delta"] = Math.Max(0, capture.TotalAllocatedBytesStop - capture.TotalAllocatedBytesStart),
                ["captured_frame_allocated_bytes"] = allocationsTotal,
                ["gc_collection_counts_start"] = capture.GcCountsStart,
                ["gc_collection_counts_stop"] = capture.GcCountsStop,
                ["gc_collection_count_deltas"] = gcDeltas,
                ["gc_pause_ms_start"] = capture.GcPauseMsStart,
                ["gc_pause_ms_stop"] = capture.GcPauseMsStop,
                ["gc_pause_ms_delta"] = Math.Max(0.0, capture.GcPauseMsStop - capture.GcPauseMsStart),
            },
            ["protocol"] = new Dictionary<string, object?>
            {
                ["maximum_queue_depth"] = capture.MaximumProtocolQueueDepth,
                ["maximum_ordered_control_queue_depth"] = capture.MaximumOrderedProtocolQueueDepth,
                ["maximum_output_queue_depth"] = capture.MaximumProtocolOutputQueueDepth,
                ["inputs_received"] = capture.InputsReceived,
                ["inputs_presented"] = capture.InputsPresented,
                ["inputs_coalesced"] = capture.InputsCoalesced,
                ["inputs_outstanding"] = inputsOutstanding,
                ["input_updates_coalesced"] = capture.ProtocolInputUpdatesCoalesced,
                ["telemetry_coalesced"] = capture.ProtocolTelemetryCoalesced,
                ["critical_events_written"] = capture.ProtocolCriticalWritten,
                ["telemetry_events_written"] = capture.ProtocolTelemetryWritten,
                ["write_failures"] = capture.ProtocolWriteFailures,
            },
            ["memory"] = new Dictionary<string, object?>
            {
                ["working_set_start_bytes"] = capture.WorkingSetBytesStart,
                ["working_set_stop_bytes"] = capture.WorkingSetBytesStop,
                ["working_set_peak_sampled_bytes"] = capture.PeakWorkingSetBytes,
                ["working_set_growth_ratio"] = workingSetGrowth,
                ["dxgi_local_usage_start_bytes"] = vramStart,
                ["dxgi_local_usage_stop_bytes"] = vramStop,
                ["dxgi_local_usage_growth_ratio"] = vramGrowth,
            },
            ["resources_before"] = resourcesBefore,
            ["resources_after"] = resourcesAfter,
            ["lifecycle"] = lifecycle,
            ["environment"] = EnvironmentPayload(),
            ["instrumentation"] = InstrumentationPayload(capture),
            ["external_evidence"] = externalEvidence ?? new Dictionary<string, object?>(),
            ["gates"] = gates,
        };
    }

    public static void WriteAtomic(string path, IReadOnlyDictionary<string, object?> report)
    {
        var fullPath = Path.GetFullPath(path);
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath) ?? Environment.CurrentDirectory);
        var json = JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true });
        var staging = $"{fullPath}.{Guid.NewGuid():N}.tmp";
        try
        {
            File.WriteAllText(staging, json + Environment.NewLine, new UTF8Encoding(false));
            File.Move(staging, fullPath, overwrite: true);
        }
        finally
        {
            if (File.Exists(staging))
            {
                File.Delete(staging);
            }
        }
    }

    private static Dictionary<string, object?> FramePayload(PreviewPerformanceFrameSample frame) => new()
    {
        ["ordinal"] = frame.Ordinal,
        ["timestamp_ms"] = frame.TimestampMs,
        ["interval_ms"] = double.IsFinite(frame.IntervalMs) ? frame.IntervalMs : null,
        ["render_ms"] = frame.RenderMs,
        ["present_ms"] = frame.PresentMs,
        ["gpu_ms"] = double.IsFinite(frame.GpuMs) ? frame.GpuMs : null,
        ["input_to_present_ms"] = double.IsFinite(frame.InputToPresentMs) ? frame.InputToPresentMs : null,
        ["managed_allocated_bytes"] = frame.ManagedAllocatedBytes,
        ["protocol_queue_depth"] = frame.ProtocolQueueDepth,
        ["input_sequence"] = frame.InputSequence,
        ["input_correlation"] = frame.InputCorrelation,
    };

    private static Dictionary<string, object?> PhasePayload(PreviewPerformancePhaseSample phase) => new()
    {
        ["phase"] = PhaseName(phase.Phase),
        ["correlation"] = phase.Correlation,
        ["managed_thread_id"] = phase.ManagedThreadId,
        ["timestamp_ms"] = phase.TimestampMs,
        ["duration_ms"] = phase.DurationMs,
        ["managed_allocated_bytes"] = phase.ManagedAllocatedBytes,
    };

    private static Dictionary<string, object?> PhaseSummaries(IEnumerable<PreviewPerformancePhaseSample> phases)
    {
        return phases
            .GroupBy(sample => sample.Phase)
            .OrderBy(group => group.Key)
            .ToDictionary(
                group => PhaseName(group.Key),
                group => (object?)new Dictionary<string, object?>
                {
                    ["duration"] = Distribution(group.Select(sample => sample.DurationMs).ToArray()),
                    ["managed_allocated_bytes"] = Distribution(group.Select(sample => (double)sample.ManagedAllocatedBytes).ToArray(), "bytes"),
                    ["managed_allocated_bytes_total"] = group.Sum(sample => sample.ManagedAllocatedBytes),
                },
                StringComparer.Ordinal);
    }

    private static Dictionary<string, object?> Distribution(double[] values, string unit = "ms")
    {
        var finite = values.Where(double.IsFinite).ToArray();
        if (finite.Length == 0)
        {
            return new Dictionary<string, object?>
            {
                ["available"] = false,
                ["sample_count"] = 0,
                [$"p50_{unit}"] = 0.0,
                [$"p95_{unit}"] = 0.0,
                [$"p99_{unit}"] = 0.0,
                [$"max_{unit}"] = 0.0,
                [$"average_{unit}"] = 0.0,
            };
        }
        Array.Sort(finite);
        return new Dictionary<string, object?>
        {
            ["available"] = true,
            ["sample_count"] = finite.Length,
            [$"p50_{unit}"] = PercentileSorted(finite, 0.50),
            [$"p95_{unit}"] = PercentileSorted(finite, 0.95),
            [$"p99_{unit}"] = PercentileSorted(finite, 0.99),
            [$"max_{unit}"] = finite[^1],
            [$"average_{unit}"] = finite.Average(),
        };
    }

    private static double PercentileSorted(double[] sorted, double percentile)
    {
        var index = Math.Clamp((int)Math.Ceiling(sorted.Length * percentile) - 1, 0, sorted.Length - 1);
        return sorted[index];
    }

    private static double SummaryMetric(IReadOnlyDictionary<string, object?> summary, string key)
    {
        return summary.TryGetValue(key, out var raw) && raw is not null
            ? Convert.ToDouble(raw, CultureInfo.InvariantCulture)
            : 0.0;
    }

    private static long SignedMetric(IReadOnlyDictionary<string, object?> values, string key)
    {
        return values.TryGetValue(key, out var raw) && raw is not null
            ? Convert.ToInt64(raw, CultureInfo.InvariantCulture)
            : 0L;
    }

    private static long MetricDelta(
        IReadOnlyDictionary<string, object?> before,
        IReadOnlyDictionary<string, object?> after,
        string key) => Math.Max(0L, SignedMetric(after, key) - SignedMetric(before, key));

    private static ulong UnsignedMetric(IReadOnlyDictionary<string, object?> values, string key)
    {
        return values.TryGetValue(key, out var raw) && raw is not null
            ? Convert.ToUInt64(raw, CultureInfo.InvariantCulture)
            : 0UL;
    }

    private static double GrowthRatio(long start, long stop) =>
        Math.Max(0.0, stop - start) / Math.Max(1.0, start);

    private static double GrowthRatio(ulong start, ulong stop) =>
        stop <= start ? 0.0 : (stop - start) / Math.Max(1.0, start);

    private static Dictionary<string, object?> InstrumentationPayload(PreviewPerformanceCaptureSnapshot capture)
    {
        const int iterations = 100_000;
        var samples = new long[iterations];
        for (var warmup = 0; warmup < 1_000; warmup++)
        {
            _ = Stopwatch.GetTimestamp();
            _ = GC.GetAllocatedBytesForCurrentThread();
        }
        var started = Stopwatch.GetTimestamp();
        for (var index = 0; index < samples.Length; index++)
        {
            samples[index] = Stopwatch.GetTimestamp() ^ GC.GetAllocatedBytesForCurrentThread();
        }
        var elapsed = Stopwatch.GetTimestamp() - started;
        GC.KeepAlive(samples);
        return new Dictionary<string, object?>
        {
            ["capture_enabled_only_on_request"] = true,
            ["hot_path_storage"] = "preallocated_fixed_arrays",
            ["statistics_computed_after_capture"] = true,
            ["probe_iterations"] = iterations,
            ["probe_average_ns"] = elapsed * 1_000_000_000.0 / Stopwatch.Frequency / iterations,
            ["preallocated_capture_storage_bytes"] = capture.PreallocatedStorageBytes,
            ["preallocated_capture_storage_pages_committed_before_baseline"] = true,
            ["dropped_frame_samples"] = capture.DroppedFrameSamples,
            ["dropped_phase_samples"] = capture.DroppedPhaseSamples,
            ["dropped_heartbeat_samples"] = capture.DroppedHeartbeatSamples,
        };
    }

    private static Dictionary<string, object?> EnvironmentPayload()
    {
        var assembly = Assembly.GetExecutingAssembly();
        var display = CurrentDisplayMode();
        return new Dictionary<string, object?>
        {
            ["os_version"] = Environment.OSVersion.VersionString,
            ["framework"] = RuntimeInformation.FrameworkDescription,
            ["process_architecture"] = RuntimeInformation.ProcessArchitecture.ToString(),
            ["processor_count"] = Environment.ProcessorCount,
            ["helper_version"] = assembly.GetName().Version?.ToString() ?? string.Empty,
            ["vortice_direct3d11_version"] = typeof(ID3D11Device).Assembly.GetName().Version?.ToString() ?? string.Empty,
            ["vortice_dxgi_version"] = typeof(IDXGISwapChain1).Assembly.GetName().Version?.ToString() ?? string.Empty,
            ["provenance"] = HelperBuildProvenance.Payload(HelperBuildProvenance.RequiredProtocolCapabilities),
            ["display"] = display,
        };
    }

    private static Dictionary<string, object?> CurrentDisplayMode()
    {
        var mode = new DevMode { Size = (short)Marshal.SizeOf<DevMode>() };
        var available = EnumDisplaySettings(null, -1, ref mode);
        return new Dictionary<string, object?>
        {
            ["available"] = available,
            ["width"] = available ? mode.PelsWidth : Screen.PrimaryScreen?.Bounds.Width ?? 0,
            ["height"] = available ? mode.PelsHeight : Screen.PrimaryScreen?.Bounds.Height ?? 0,
            ["refresh_hz"] = available ? mode.DisplayFrequency : 0,
            ["bits_per_pixel"] = available ? mode.BitsPerPel : 0,
        };
    }

    private static string PhaseName(PreviewPerformancePhase phase) => phase switch
    {
        PreviewPerformancePhase.ProtocolReceive => "protocol_receive",
        PreviewPerformancePhase.ProtocolParse => "protocol_parse",
        PreviewPerformancePhase.ProtocolApply => "protocol_apply",
        PreviewPerformancePhase.Invalidation => "invalidation",
        PreviewPerformancePhase.Paint => "paint",
        PreviewPerformancePhase.OpaquePass => "opaque_pass",
        PreviewPerformancePhase.TransparentPass => "transparent_pass",
        PreviewPerformancePhase.OverlayPass => "overlay_pass",
        PreviewPerformancePhase.Present => "present",
        PreviewPerformancePhase.Acknowledgement => "acknowledgement",
        PreviewPerformancePhase.TextureUpload => "texture_upload",
        PreviewPerformancePhase.TopologyPrepare => "topology_prepare",
        PreviewPerformancePhase.TopologyCommit => "topology_commit",
        PreviewPerformancePhase.VertexPrepare => "vertex_prepare",
        PreviewPerformancePhase.VertexCommit => "vertex_commit",
        PreviewPerformancePhase.SyntheticDriver => "synthetic_driver",
        _ => "unknown",
    };

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct DevMode
    {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        public string DeviceName;
        public short SpecVersion;
        public short DriverVersion;
        public short Size;
        public short DriverExtra;
        public int Fields;
        public int PositionX;
        public int PositionY;
        public int DisplayOrientation;
        public int DisplayFixedOutput;
        public short Color;
        public short Duplex;
        public short YResolution;
        public short TTOption;
        public short Collate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        public string FormName;
        public short LogPixels;
        public int BitsPerPel;
        public int PelsWidth;
        public int PelsHeight;
        public int DisplayFlags;
        public int DisplayFrequency;
        public int ICMMethod;
        public int ICMIntent;
        public int MediaType;
        public int DitherType;
        public int Reserved1;
        public int Reserved2;
        public int PanningWidth;
        public int PanningHeight;
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumDisplaySettings(string? deviceName, int modeNumber, ref DevMode devMode);
}
