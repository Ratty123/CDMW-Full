using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class HeadlessGpuInteractionSoak
{
    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(arg, "--headless-gpu-interaction-soak", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var reportPath = HeadlessGpuFramePacingSoakOptions.ReportPathFrom(args);
        try
        {
            var options = HeadlessGpuFramePacingSoakOptions.Parse(args);
            var mode = InteractionMode(args);
            return Execute(options, mode);
        }
        catch (Exception ex)
        {
            PreviewPerformanceReport.WriteAtomic(reportPath, new Dictionary<string, object?>
            {
                ["schema"] = PreviewPerformanceReport.Schema,
                ["schema_version"] = 1,
                ["ok"] = false,
                ["generated_at_utc"] = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture),
                ["error"] = new Dictionary<string, object?>
                {
                    ["type"] = ex.GetType().FullName,
                    ["message"] = ex.Message,
                },
            });
            return 1;
        }
        finally
        {
            _ = PreviewPerformanceCapture.StopActive();
        }
    }

    private static int Execute(HeadlessGpuFramePacingSoakOptions options, string mode)
    {
        if (MeshViewport.SelectionSegmentsIntersect(
                new PointF(0.0f, 0.0f),
                new PointF(10.0f, 0.0f),
                new PointF(20.0f, 0.0f),
                new PointF(30.0f, 0.0f))
            || !MeshViewport.SelectionSegmentsIntersect(
                new PointF(0.0f, 0.0f),
                new PointF(10.0f, 10.0f),
                new PointF(0.0f, 10.0f),
                new PointF(10.0f, 0.0f)))
        {
            throw new InvalidOperationException("Selection swept-band segment intersection contract failed.");
        }
        var document = HeadlessGpuSparseSoak.BuildSyntheticDocument(options.VertexCount);
        var materials = NetMaterialSet.Empty;
        using var textures = NetTextureSet.Load(materials);
        var scene = NetSceneState.Load(string.Empty, document.Submeshes.Count);
        scene.SetInteractionMode("mesh_edit");
        using var host = CreateHiddenHost(options, mode);
        using var viewport = new MeshViewport(
            document,
            materials,
            textures,
            scene,
            SyntheticLaunchOptions())
        {
            Dock = DockStyle.Fill,
        };
        var toolOptions = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase)
        {
            ["target_mode"] = "vertex",
            ["operation"] = "add",
            ["radius"] = 24.0,
            ["strength"] = 0.5,
            ["falloff"] = "smooth",
            ["invert"] = false,
        };
        viewport.ToolOptionsProvider = () => toolOptions;
        var protocol = new InteractionProtocolProbe();
        viewport.EditorEventRequested = protocol.Accept;
        if (!viewport.TrySetDisplayMode("untextured_wire", out var displayModeError))
        {
            throw new InvalidOperationException($"Hidden Edit Mesh wire mode failed: {displayModeError}");
        }
        host.Controls.Add(viewport);
        host.CreateControl();
        _ = host.Handle;
        NativeWindowHost.ResizeHidden(host, options.Width, options.Height);
        host.PerformLayout();
        viewport.CreateControl();
        _ = viewport.Handle;
        if (!viewport.EnsureRendererInitialized())
        {
            throw new InvalidOperationException($"Hidden {mode} interaction viewport did not initialize the production renderer.");
        }

        var lassoReleaseProof = CaptureLassoReleaseProof(viewport);
        var shortFaceBrushProof = CaptureShortFaceBrushProof(viewport);
        viewport.EditorEventRequested = protocol.Accept;

        var start = mode.StartsWith("select_", StringComparison.Ordinal)
            ? viewport.InteractionSoakMeshAnchor()
            : new Point(Math.Max(1, viewport.ClientSize.Width / 2), Math.Max(1, viewport.ClientSize.Height / 2));
        viewport.BeginInteractionSoak(mode, start);
        var driver = new InteractionPathDriver(start, viewport.ClientSize);
        for (var warmup = 0; warmup < options.WarmupFrames; warmup++)
        {
            var point = driver.Next();
            viewport.StepInteractionSoak(point);
            if (!viewport.TryRunHeadlessRendererFrame(out _, out _, out var warmupError))
            {
                throw new InvalidOperationException($"Hidden {mode} interaction warm-up frame {warmup} failed: {warmupError}");
            }
            protocol.CompleteOne();
        }
        GC.Collect(2, GCCollectionMode.Forced, blocking: true, compacting: false);
        GC.WaitForPendingFinalizers();
        viewport.PrepareRendererPerformanceCapture();
        var resourcesBefore = viewport.RendererResourceMetricsPayload();
        var captureId = $"interaction-{mode}-{Guid.NewGuid():N}";
        if (!PreviewPerformanceCapture.TryStart(
            new PreviewPerformanceCaptureOptions(
                captureId,
                $"headless_gpu_{mode}_interaction_soak",
                options.ReportPath,
                options.DurationSeconds,
                options.TargetHz,
                options.WarmupFrames,
                options.Width,
                options.Height,
                new Dictionary<string, object?>
                {
                    ["kind"] = "generated_in_memory",
                    ["interaction_mode"] = mode,
                    ["checked_in_asset_used"] = false,
                    ["source_vertex_count"] = document.Submeshes.Sum(submesh => submesh.Vertices.Count),
                    ["triangle_count"] = document.Submeshes.Sum(submesh => submesh.Faces.Count),
                    ["submesh_count"] = document.Submeshes.Count,
                    ["sha256"] = string.Empty,
                }),
            out _,
            out var startError))
        {
            throw new InvalidOperationException(startError);
        }

        var duration = Stopwatch.StartNew();
        long frame = 0;
        while (duration.Elapsed.TotalSeconds < options.DurationSeconds)
        {
            PreviewPerformanceCapture.RecordInput(PreviewPerformanceInputKind.Synthetic, frame + 1);
            viewport.StepInteractionSoak(driver.Next());
            if (!viewport.TryRunHeadlessRendererFrame(out _, out _, out var frameError))
            {
                throw new InvalidOperationException($"Hidden {mode} interaction frame {frame} failed: {frameError}");
            }
            PreviewPerformanceCapture.RecordHeartbeat(PreviewPerformanceHeartbeatKind.WinForms);
            protocol.CompleteOne();
            frame++;
            if (frame % Math.Max(1L, (long)Math.Round(options.TargetHz, MidpointRounding.AwayFromZero)) == 0)
            {
                PreviewPerformanceCapture.SampleWorkingSet();
            }
        }
        duration.Stop();
        var snapshot = PreviewPerformanceCapture.Stop(captureId, out var stopError)
            ?? throw new InvalidOperationException(stopError);
        var interaction = viewport.FinishInteractionSoak(driver.Current);
        protocol.CompleteAll();
        if (!viewport.TryRunHeadlessRendererFrame(out _, out _, out var finalFrameError))
        {
            throw new InvalidOperationException($"Hidden {mode} authoritative reconciliation frame failed: {finalFrameError}");
        }
        var resourcesAfter = viewport.RendererResourceMetricsPayload();
        return BuildInteractionReport(
            options,
            mode,
            host,
            viewport,
            snapshot,
            resourcesBefore,
            resourcesAfter,
            interaction,
            protocol,
            driver,
            lassoReleaseProof,
            shortFaceBrushProof);
    }

    private static Dictionary<string, object?> CaptureShortFaceBrushProof(MeshViewport viewport)
    {
        const int gestureCount = 12;
        var previousHandler = viewport.EditorEventRequested;
        var probe = new InteractionProtocolProbe();
        var inputSamples = new List<double>(gestureCount);
        var maximumHeartbeatGapMs = 0.0;
        var selectedGestureCount = 0;
        var cacheReady = true;
        var anchor = viewport.InteractionSoakMeshAnchor();
        var beforeSelectionPayload = viewport.SelectionSnapshotPayload();
        var beforeDiagnostics = beforeSelectionPayload.GetValueOrDefault("selection_cache")
            as IReadOnlyDictionary<string, object?>
            ?? new Dictionary<string, object?>();
        var buildsBefore = Convert.ToInt32(beforeDiagnostics.GetValueOrDefault("build_count") ?? 0);
        var hitsBefore = Convert.ToInt32(beforeDiagnostics.GetValueOrDefault("cache_hits") ?? 0);
        var coldBefore = Convert.ToInt32(beforeDiagnostics.GetValueOrDefault("cold_first_dab_count") ?? 0);
        var warmBefore = Convert.ToInt32(beforeDiagnostics.GetValueOrDefault("warm_first_dab_count") ?? 0);
        viewport.EditorEventRequested = probe.Accept;
        viewport.ResetPaintProjectionCacheForInteractionSoak();
        // Arming Select is a separate user action and begins the cold prewarm. The
        // measured first dab may arrive immediately while that build is still active.
        viewport.ActiveTool = "select";
        try
        {
            for (var gesture = 0; gesture < gestureCount; gesture++)
            {
                var start = new Point(anchor.X + gesture % 3, anchor.Y + (gesture / 3) % 3);
                var end = new Point(start.X + 3, start.Y + 2);
                var inputStarted = Stopwatch.GetTimestamp();
                viewport.BeginShortFaceBrushInteractionSoak(start);
                inputSamples.Add(Stopwatch.GetElapsedTime(inputStarted).TotalMilliseconds);
                inputStarted = Stopwatch.GetTimestamp();
                viewport.StepInteractionSoak(end);
                inputSamples.Add(Stopwatch.GetElapsedTime(inputStarted).TotalMilliseconds);
                cacheReady = viewport.WaitForPaintProjectionCacheForInteractionSoak(
                    10_000,
                    out var heartbeatGapMs);
                maximumHeartbeatGapMs = Math.Max(maximumHeartbeatGapMs, heartbeatGapMs);
                if (!cacheReady)
                {
                    break;
                }
                var interaction = viewport.FinishInteractionSoak(end);
                if (interaction.SelectedFaceCount > 0)
                {
                    selectedGestureCount++;
                }
                probe.CompleteAll();
                if (!viewport.TryRunHeadlessRendererFrame(out _, out _, out var frameError))
                {
                    throw new InvalidOperationException(
                        $"Hidden short Face Brush gesture {gesture} failed to render: {frameError}");
                }
                Application.DoEvents();
            }
        }
        finally
        {
            viewport.EditorEventRequested = previousHandler;
        }
        var ordered = inputSamples.OrderBy(value => value).ToArray();
        var p95Index = ordered.Length == 0
            ? 0
            : Math.Clamp((int)Math.Ceiling(ordered.Length * 0.95) - 1, 0, ordered.Length - 1);
        var inputP95Ms = ordered.Length == 0 ? double.PositiveInfinity : ordered[p95Index];
        var selectionPayload = viewport.SelectionSnapshotPayload();
        var diagnostics = selectionPayload.GetValueOrDefault("selection_cache")
            as IReadOnlyDictionary<string, object?>
            ?? new Dictionary<string, object?>();
        var buildCount = Convert.ToInt32(diagnostics.GetValueOrDefault("build_count") ?? 0);
        var cacheHits = Convert.ToInt32(diagnostics.GetValueOrDefault("cache_hits") ?? 0);
        var coldFirstDabs = Convert.ToInt32(diagnostics.GetValueOrDefault("cold_first_dab_count") ?? 0);
        var warmFirstDabs = Convert.ToInt32(diagnostics.GetValueOrDefault("warm_first_dab_count") ?? 0);
        var buildDelta = buildCount - buildsBefore;
        var hitDelta = cacheHits - hitsBefore;
        var coldDelta = coldFirstDabs - coldBefore;
        var warmDelta = warmFirstDabs - warmBefore;
        var inputGate = inputP95Ms <= 13.89;
        var heartbeatGate = maximumHeartbeatGapMs <= 33.3;
        var reuseGate = buildDelta == 1
            && hitDelta >= gestureCount - 1
            && coldDelta >= 1
            && warmDelta >= gestureCount - 1;
        return new Dictionary<string, object?>
        {
            ["ok"] = cacheReady
                && inputSamples.Count == gestureCount * 2
                && selectedGestureCount == gestureCount
                && inputGate
                && heartbeatGate
                && reuseGate,
            ["gesture_count"] = gestureCount,
            ["completed_gesture_count"] = inputSamples.Count / 2,
            ["selected_gesture_count"] = selectedGestureCount,
            ["input_p95_ms"] = inputP95Ms,
            ["maximum_heartbeat_gap_ms"] = maximumHeartbeatGapMs,
            ["input_p95_at_most_13_89_ms"] = inputGate,
            ["host_heartbeat_at_most_33_3_ms"] = heartbeatGate,
            ["resident_cache_reused"] = reuseGate,
            ["cache_ready"] = cacheReady,
            ["cache_build_delta"] = buildDelta,
            ["cache_hit_delta"] = hitDelta,
            ["cold_first_dab_delta"] = coldDelta,
            ["warm_first_dab_delta"] = warmDelta,
            ["selection_cache"] = diagnostics,
        };
    }

    private static Dictionary<string, object?> CaptureLassoReleaseProof(MeshViewport viewport)
    {
        var resourcesBefore = viewport.RendererResourceMetricsPayload();
        var openStart = new Point(40, 40);
        var openMove = new Point(Math.Max(80, viewport.ClientSize.Width - 40), 40);
        var openRelease = new Point(
            Math.Max(60, viewport.ClientSize.Width / 2),
            Math.Max(80, viewport.ClientSize.Height - 40));
        var open = CaptureLassoReleaseCase(
            viewport,
            new[] { openStart, openMove, openRelease },
            renderClearedFrame: false);

        var closedStart = new Point(40, 40);
        var closedRight = Math.Max(80, viewport.ClientSize.Width - 40);
        var closedBottom = Math.Max(80, viewport.ClientSize.Height - 40);
        var closed = CaptureLassoReleaseCase(
            viewport,
            new[]
            {
                closedStart,
                new Point(closedRight, 40),
                new Point(closedRight, closedBottom),
                new Point(40, closedBottom),
                new Point(42, 42),
            },
            renderClearedFrame: true);
        var createsBefore = Convert.ToInt64(resourcesBefore.GetValueOrDefault("retained_overlay_buffer_creates") ?? 0);
        var disposalsBefore = Convert.ToInt64(resourcesBefore.GetValueOrDefault("retained_overlay_buffer_disposals") ?? 0);
        var createsAfterOpen = Convert.ToInt64(open.GetValueOrDefault("retained_overlay_buffer_creates_after_selection") ?? 0);
        var disposalsAfterOpen = Convert.ToInt64(open.GetValueOrDefault("retained_overlay_buffer_disposals_after_selection") ?? 0);
        var createsAfterClear = Convert.ToInt64(closed.GetValueOrDefault("retained_overlay_buffer_creates_after_clear") ?? 0);
        var disposalsAfterClear = Convert.ToInt64(closed.GetValueOrDefault("retained_overlay_buffer_disposals_after_clear") ?? 0);
        var createsAfterRebuild = Convert.ToInt64(closed.GetValueOrDefault("retained_overlay_buffer_creates_after_selection") ?? 0);
        var disposalsAfterRebuild = Convert.ToInt64(closed.GetValueOrDefault("retained_overlay_buffer_disposals_after_selection") ?? 0);
        var clearRebuildOk = createsAfterOpen >= createsBefore + 2
            && disposalsAfterOpen >= disposalsBefore
            && disposalsAfterClear >= disposalsAfterOpen + 2
            && createsAfterRebuild >= createsAfterClear + 2
            && disposalsAfterRebuild >= disposalsAfterClear;
        var mismatchReconciliation = CaptureTerminalSelectionMismatchProof(
            viewport,
            createsAfterRebuild,
            disposalsAfterRebuild);
        return new Dictionary<string, object?>
        {
            ["ok"] = open.GetValueOrDefault("ok") is true
                && closed.GetValueOrDefault("ok") is true
                && clearRebuildOk
                && mismatchReconciliation.GetValueOrDefault("ok") is true,
            ["open_release"] = open,
            ["closed_release"] = closed,
            ["terminal_mismatch_reconciliation"] = mismatchReconciliation,
            ["retained_overlay_clear_rebuild_ok"] = clearRebuildOk,
            ["retained_overlay_buffer_creates_before"] = createsBefore,
            ["retained_overlay_buffer_creates_after_open"] = createsAfterOpen,
            ["retained_overlay_buffer_creates_after_clear"] = createsAfterClear,
            ["retained_overlay_buffer_creates_after_rebuild"] = createsAfterRebuild,
            ["retained_overlay_buffer_disposals_before"] = disposalsBefore,
            ["retained_overlay_buffer_disposals_after_open"] = disposalsAfterOpen,
            ["retained_overlay_buffer_disposals_after_clear"] = disposalsAfterClear,
            ["retained_overlay_buffer_disposals_after_rebuild"] = disposalsAfterRebuild,
        };
    }

    private static Dictionary<string, object?> CaptureTerminalSelectionMismatchProof(
        MeshViewport viewport,
        long createsBefore,
        long disposalsBefore)
    {
        _ = viewport.UpdateSelection(
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<(int A, int B)>>(),
            new HashSet<int>(),
            revision: viewport.AcknowledgedSelectionRevision + 1);
        if (!viewport.TryRunHeadlessRendererFrame(out _, out _, out var reconciliationFrameError))
        {
            throw new InvalidOperationException($"Hidden terminal selection mismatch frame failed: {reconciliationFrameError}");
        }
        var afterFirstFrame = viewport.RendererResourceMetricsPayload();
        if (!viewport.TryRunHeadlessRendererFrame(out _, out _, out var stableFrameError))
        {
            throw new InvalidOperationException($"Hidden terminal selection stability frame failed: {stableFrameError}");
        }
        var afterSecondFrame = viewport.RendererResourceMetricsPayload();
        var createsAfterFirst = Convert.ToInt64(afterFirstFrame.GetValueOrDefault("retained_overlay_buffer_creates") ?? 0);
        var disposalsAfterFirst = Convert.ToInt64(afterFirstFrame.GetValueOrDefault("retained_overlay_buffer_disposals") ?? 0);
        var createsAfterSecond = Convert.ToInt64(afterSecondFrame.GetValueOrDefault("retained_overlay_buffer_creates") ?? 0);
        var disposalsAfterSecond = Convert.ToInt64(afterSecondFrame.GetValueOrDefault("retained_overlay_buffer_disposals") ?? 0);
        var rebuildsAfterFirst = Convert.ToInt64(afterFirstFrame.GetValueOrDefault("retained_overlay_rebuilds") ?? 0);
        var rebuildsAfterSecond = Convert.ToInt64(afterSecondFrame.GetValueOrDefault("retained_overlay_rebuilds") ?? 0);
        return new Dictionary<string, object?>
        {
            ["ok"] = createsAfterFirst == createsBefore
                && disposalsAfterFirst >= disposalsBefore + 2
                && createsAfterSecond == createsAfterFirst
                && disposalsAfterSecond == disposalsAfterFirst
                && rebuildsAfterSecond == rebuildsAfterFirst,
            ["creates_before"] = createsBefore,
            ["creates_after_first_frame"] = createsAfterFirst,
            ["creates_after_second_frame"] = createsAfterSecond,
            ["disposals_before"] = disposalsBefore,
            ["disposals_after_first_frame"] = disposalsAfterFirst,
            ["disposals_after_second_frame"] = disposalsAfterSecond,
            ["rebuilds_after_first_frame"] = rebuildsAfterFirst,
            ["rebuilds_after_second_frame"] = rebuildsAfterSecond,
        };
    }

    private static Dictionary<string, object?> CaptureLassoReleaseCase(
        MeshViewport viewport,
        IReadOnlyList<Point> path,
        bool renderClearedFrame)
    {
        var probe = new InteractionProtocolProbe();
        viewport.EditorEventRequested = probe.Accept;
        viewport.BeginInteractionSoak("select_lasso_face", path[0]);
        if (!viewport.WaitForPaintProjectionCacheForInteractionSoak(10_000, out _))
        {
            throw new InvalidOperationException("Hidden lasso projection cache did not finish before the release proof.");
        }
        long? createsAfterClear = null;
        long? disposalsAfterClear = null;
        if (renderClearedFrame
            && !viewport.TryRunHeadlessRendererFrame(out _, out _, out var clearedFrameError))
        {
            throw new InvalidOperationException($"Hidden lasso cleared-overlay proof frame failed: {clearedFrameError}");
        }
        if (renderClearedFrame)
        {
            var resourcesAfterClear = viewport.RendererResourceMetricsPayload();
            createsAfterClear = Convert.ToInt64(resourcesAfterClear.GetValueOrDefault("retained_overlay_buffer_creates") ?? 0);
            disposalsAfterClear = Convert.ToInt64(resourcesAfterClear.GetValueOrDefault("retained_overlay_buffer_disposals") ?? 0);
        }
        for (var index = 1; index < path.Count - 1; index++)
        {
            viewport.StepInteractionSoak(path[index]);
        }
        viewport.FinishLassoInteractionSoakWithoutFinalMove(path[^1]);
        if (!viewport.TryRunHeadlessRendererFrame(out _, out _, out var selectionFrameError))
        {
            throw new InvalidOperationException($"Hidden lasso selected-overlay proof frame failed: {selectionFrameError}");
        }
        var resourcesAfterSelection = viewport.RendererResourceMetricsPayload();
        probe.CompleteAll();
        var actual = probe.TerminalSelectionPoints;
        return new Dictionary<string, object?>
        {
            ["ok"] = probe.TerminalSelectionMode == "lasso"
                && actual.SequenceEqual(path),
            ["selection_mode"] = probe.TerminalSelectionMode,
            ["expected_points"] = path.Select(point => new[] { point.X, point.Y }).ToArray(),
            ["actual_points"] = actual.Select(point => new[] { point.X, point.Y }).ToArray(),
            ["retained_overlay_buffer_creates_after_clear"] = createsAfterClear,
            ["retained_overlay_buffer_disposals_after_clear"] = disposalsAfterClear,
            ["retained_overlay_buffer_creates_after_selection"] =
                Convert.ToInt64(resourcesAfterSelection.GetValueOrDefault("retained_overlay_buffer_creates") ?? 0),
            ["retained_overlay_buffer_disposals_after_selection"] =
                Convert.ToInt64(resourcesAfterSelection.GetValueOrDefault("retained_overlay_buffer_disposals") ?? 0),
        };
    }

    private static Dictionary<string, object?> CaptureFaceProjectionCandidateRoutingProof()
    {
        const int largeFaceIndex = 37;
        var largeBuckets = new List<int>?[20];
        var largeCandidates = new List<int>();
        var routedLarge = MeshViewport.RoutePaintProjectionFaceCandidate(
            largeBuckets,
            largeCandidates,
            largeFaceIndex,
            gridColumns: 5,
            leftCell: 0,
            rightCell: 4,
            topCell: 0,
            bottomCell: 3);

        const int bucketedFaceIndex = 41;
        var smallBuckets = new List<int>?[16];
        var smallLargeCandidates = new List<int>();
        var routedSmallAsLarge = MeshViewport.RoutePaintProjectionFaceCandidate(
            smallBuckets,
            smallLargeCandidates,
            bucketedFaceIndex,
            gridColumns: 4,
            leftCell: 0,
            rightCell: 3,
            topCell: 0,
            bottomCell: 3);
        var largeEntryCount = largeCandidates.Count(candidate => candidate == largeFaceIndex);
        var largeBucketEntryCount = largeBuckets.Sum(bucket => bucket?.Count ?? 0);
        var smallBucketEntryCount = smallBuckets.Sum(bucket => bucket?.Count ?? 0);
        var ok = routedLarge
            && !routedSmallAsLarge
            && largeEntryCount == 1
            && largeBucketEntryCount == 0
            && smallLargeCandidates.Count == 0
            && smallBucketEntryCount == 16
            && smallBuckets.All(bucket => bucket is { Count: 1 } && bucket[0] == bucketedFaceIndex);
        return new Dictionary<string, object?>
        {
            ["ok"] = ok,
            ["large_candidate_entry_count"] = largeEntryCount,
            ["large_candidate_bucket_entry_count"] = largeBucketEntryCount,
            ["threshold_candidate_bucket_entry_count"] = smallBucketEntryCount,
        };
    }

    private static int BuildInteractionReport(
        HeadlessGpuFramePacingSoakOptions options,
        string mode,
        Form host,
        MeshViewport viewport,
        PreviewPerformanceCaptureSnapshot snapshot,
        Dictionary<string, object?> resourcesBefore,
        Dictionary<string, object?> resourcesAfter,
        MeshInteractionSoakResult interaction,
        InteractionProtocolProbe protocol,
        InteractionPathDriver driver,
        Dictionary<string, object?> lassoReleaseProof,
        Dictionary<string, object?> shortFaceBrushProof)
    {
        var lifecycle = new Dictionary<string, object?>
        {
            ["process_restart_count"] = 0,
            ["device_reset_count"] = viewport.DeviceResetCount,
            ["backend"] = viewport.RendererBackendName,
            ["host_visible"] = host.Visible,
            ["show_in_taskbar"] = host.ShowInTaskbar,
            ["viewport_client_width"] = viewport.ClientSize.Width,
            ["viewport_client_height"] = viewport.ClientSize.Height,
        };
        var report = PreviewPerformanceReport.Build(snapshot, resourcesBefore, resourcesAfter, lifecycle);
        var rendererGates = new Dictionary<string, bool>((Dictionary<string, bool>)report["gates"]!);
        var faceProjectionRoutingProof = CaptureFaceProjectionCandidateRoutingProof();
        var gcDeltas = snapshot.GcCountsStop
            .Select((count, index) => count - snapshot.GcCountsStart[index])
            .ToArray();
        var interactionGates = new Dictionary<string, bool>
        {
            ["input_to_present_p95_at_most_13_89_ms"] = rendererGates["input_to_present_p95_at_most_13_89_ms"],
            ["no_frame_over_20_83_ms"] = rendererGates["no_frame_over_20_83_ms"],
            ["host_heartbeat_at_most_33_3_ms"] = rendererGates["host_heartbeat_at_most_33_3_ms"],
            ["protocol_pending_depth_at_most_one"] = protocol.MaximumPendingDepth <= 1,
            ["no_lost_cursor_coverage"] = Math.Abs(interaction.CursorCoveragePixels - driver.CoveragePixels) <= 0.001,
            ["stale_result_did_not_roll_back_live_stroke"] = interaction.StaleResultIgnored,
            ["zero_gen1_collections"] = gcDeltas[1] == 0,
            ["zero_gen2_collections"] = gcDeltas[2] == 0,
            ["final_authority_matches_visible_provisional_result"] = interaction.FinalAuthorityMatches,
            ["provisional_state_cleared_after_authority"] = interaction.ProvisionalCleared,
            ["one_terminal_history_event"] = protocol.TerminalStrokeEvents == 1,
            ["interaction_changed_expected_scope"] = mode.StartsWith("select_", StringComparison.Ordinal)
                ? interaction.SelectedVertexCount + interaction.SelectedEdgeCount + interaction.SelectedFaceCount > 0
                : interaction.ChangedVertexCount > 0,
            ["viewport_tools_did_not_select_parts"] = interaction.SelectedPartCount == 0,
            ["release_only_lasso_commits_exact_polygon"] = lassoReleaseProof.GetValueOrDefault("ok") is true,
            ["retained_overlay_clear_rebuild_is_discard_safe"] =
                lassoReleaseProof.GetValueOrDefault("retained_overlay_clear_rebuild_ok") is true,
            ["terminal_depth_mismatch_discards_provisional_overlay_once"] =
                lassoReleaseProof.GetValueOrDefault("terminal_mismatch_reconciliation")
                    is IReadOnlyDictionary<string, object?> mismatchProof
                && mismatchProof.GetValueOrDefault("ok") is true,
            ["oversized_face_projection_uses_bounded_candidate_list"] =
                faceProjectionRoutingProof.GetValueOrDefault("ok") is true,
            ["repeated_short_face_brush_meets_input_and_heartbeat_budgets"] =
                shortFaceBrushProof.GetValueOrDefault("ok") is true,
            ["wire_overlay_gpu_buffer_retained"] =
                Convert.ToInt64(resourcesBefore.GetValueOrDefault("retained_wire_overlay_buffer_creates") ?? 0) > 0
                && Convert.ToInt64(resourcesAfter.GetValueOrDefault("retained_wire_overlay_buffer_creates") ?? 0)
                    == Convert.ToInt64(resourcesBefore.GetValueOrDefault("retained_wire_overlay_buffer_creates") ?? 0)
                && Convert.ToInt64(resourcesAfter.GetValueOrDefault("retained_wire_overlay_buffer_disposals") ?? 0)
                    == Convert.ToInt64(resourcesBefore.GetValueOrDefault("retained_wire_overlay_buffer_disposals") ?? 0),
            ["production_d3d11_backend"] = string.Equals(viewport.RendererBackendName, "d3d11_vortice_shader", StringComparison.Ordinal),
            ["native_window_remained_hidden"] = !host.Visible && !host.ShowInTaskbar,
        };
        var ok = interactionGates.Values.All(value => value);
        report["renderer_gates"] = rendererGates;
        report["gates"] = interactionGates;
        report["interaction"] = new Dictionary<string, object?>
        {
            ["mode"] = mode,
            ["synthetic_hidden_evidence_only"] = true,
            ["cursor_coverage_pixels"] = interaction.CursorCoveragePixels,
            ["expected_cursor_coverage_pixels"] = driver.CoveragePixels,
            ["changed_vertex_count"] = interaction.ChangedVertexCount,
            ["selected_part_count"] = interaction.SelectedPartCount,
            ["selected_vertex_count"] = interaction.SelectedVertexCount,
            ["selected_edge_count"] = interaction.SelectedEdgeCount,
            ["selected_face_count"] = interaction.SelectedFaceCount,
            ["protocol_event_count"] = protocol.EventCount,
            ["protocol_updates_coalesced"] = protocol.CoalescedUpdates,
            ["maximum_pending_depth"] = protocol.MaximumPendingDepth,
            ["terminal_stroke_events"] = protocol.TerminalStrokeEvents,
        };
        report["lasso_release_proof"] = lassoReleaseProof;
        report["short_face_brush_proof"] = shortFaceBrushProof;
        report["face_projection_candidate_routing_proof"] = faceProjectionRoutingProof;
        report["ok"] = ok;
        report["release_gate_eligible"] = !options.Smoke
            && options.DurationSeconds >= 30.0
            && options.WarmupFrames >= 300
            && options.Width == 1920
            && options.Height == 1080
            && options.TargetHz >= 144.0;
        report["full_scale_gate_ok"] = report["release_gate_eligible"] is true && ok;
        PreviewPerformanceReport.WriteAtomic(options.ReportPath, report);
        return options.Smoke ? (snapshot.Frames.Length > 0 && ok ? 0 : 2) : (ok ? 0 : 2);
    }

    private static Form CreateHiddenHost(HeadlessGpuFramePacingSoakOptions options, string mode) => new()
    {
        Text = string.Empty,
        AutoScaleMode = AutoScaleMode.None,
        ClientSize = new Size(options.Width, options.Height),
        StartPosition = FormStartPosition.Manual,
        Location = new Point(-32000, -32000),
        FormBorderStyle = FormBorderStyle.None,
        ShowInTaskbar = false,
        Visible = false,
    };

    /// <summary>Launch options for a viewport built with no files behind it; shared with
    /// the layout gate, which builds one to prove a presentation payload reaches the renderer.</summary>
    internal static LaunchOptions SyntheticLaunchOptions()
    {
        var root = Path.Combine(Path.GetTempPath(), "cdmw-mesh-interaction-soak");
        return new LaunchOptions(
            root,
            Path.Combine(root, "synthetic.obj"),
            Path.Combine(root, "metadata.json"),
            Path.Combine(root, "status.json"),
            root,
            Path.Combine(root, "edits.json"),
            Path.Combine(root, "evaluation.md"),
            false,
            true,
            "authoring",
            false,
            0L);
    }

    private static string InteractionMode(string[] args)
    {
        for (var index = 0; index < args.Length - 1; index++)
        {
            if (string.Equals(args[index], "--interaction-soak-mode", StringComparison.OrdinalIgnoreCase))
            {
                return args[index + 1].Trim().ToLowerInvariant();
            }
        }
        throw new ArgumentException(
            "--interaction-soak-mode is required (select_brush_vertex, select_brush_face, select_lasso_face, move, grab, smooth, inflate, or pinch).");
    }

    private sealed class InteractionPathDriver
    {
        private readonly Point _center;
        private readonly Size _size;
        private long _step;

        public InteractionPathDriver(Point start, Size size)
        {
            Current = start;
            _center = start;
            _size = size;
        }

        public Point Current { get; private set; }
        public double CoveragePixels { get; private set; }

        public Point Next()
        {
            _step++;
            var phase = (_step % 720L) / 720.0 * Math.Tau;
            var next = new Point(
                _center.X + (int)Math.Round(Math.Sin(phase) * Math.Max(8, _size.Width * 0.18)),
                _center.Y + (int)Math.Round(Math.Sin(phase * 2.0) * Math.Max(8, _size.Height * 0.14)));
            var dx = next.X - Current.X;
            var dy = next.Y - Current.Y;
            CoveragePixels += Math.Sqrt((double)dx * dx + (double)dy * dy);
            Current = next;
            return next;
        }
    }

    private sealed class InteractionProtocolProbe
    {
        private bool _inFlight;
        private bool _pending;

        public long EventCount { get; private set; }
        public long CoalescedUpdates { get; private set; }
        public int MaximumPendingDepth { get; private set; }
        public int TerminalStrokeEvents { get; private set; }
        public string TerminalSelectionMode { get; private set; } = string.Empty;
        public Point[] TerminalSelectionPoints { get; private set; } = Array.Empty<Point>();

        public void Accept(string eventName, Dictionary<string, object?> payload)
        {
            if (eventName is not ("select_request" or "selection_request" or "stroke_begin" or "stroke_update" or "stroke_end" or "stroke_cancel"))
            {
                return;
            }
            EventCount++;
            var phase = Convert.ToString(payload.GetValueOrDefault("phase"))?.Trim().ToLowerInvariant() ?? string.Empty;
            if (eventName is "stroke_end" or "stroke_cancel" || phase is "end" or "cancel")
            {
                TerminalStrokeEvents++;
            }
            if (eventName is "select_request"
                && phase == "end"
                && payload.GetValueOrDefault("screen_region") is IReadOnlyDictionary<string, object?> region)
            {
                TerminalSelectionMode = Convert.ToString(region.GetValueOrDefault("mode"))?.Trim().ToLowerInvariant()
                    ?? string.Empty;
                if (region.GetValueOrDefault("points") is IEnumerable<double[]> points)
                {
                    TerminalSelectionPoints = points
                        .Where(point => point.Length >= 2)
                        .Select(point => new Point((int)Math.Round(point[0]), (int)Math.Round(point[1])))
                        .ToArray();
                }
            }
            if (!_inFlight)
            {
                _inFlight = true;
                return;
            }
            if (_pending)
            {
                CoalescedUpdates++;
                PreviewPerformanceCapture.RecordProtocolInputCoalesced();
            }
            _pending = true;
            MaximumPendingDepth = 1;
            PreviewPerformanceCapture.RecordProtocolInputQueueDepth(1);
        }

        public void CompleteOne()
        {
            if (!_inFlight)
            {
                return;
            }
            if (_pending)
            {
                _pending = false;
                return;
            }
            _inFlight = false;
        }

        public void CompleteAll()
        {
            _pending = false;
            _inFlight = false;
        }
    }
}
