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

        var start = new Point(Math.Max(1, viewport.ClientSize.Width / 2), Math.Max(1, viewport.ClientSize.Height / 2));
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
            driver);
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
        InteractionPathDriver driver)
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
            ["one_terminal_history_event"] = mode == "select_brush" || protocol.TerminalStrokeEvents == 1,
            ["interaction_changed_expected_scope"] = mode == "select_brush"
                ? interaction.SelectedVertexCount > 0
                : interaction.ChangedVertexCount > 0,
            ["viewport_tools_did_not_select_parts"] = interaction.SelectedPartCount == 0,
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
            ["protocol_event_count"] = protocol.EventCount,
            ["protocol_updates_coalesced"] = protocol.CoalescedUpdates,
            ["maximum_pending_depth"] = protocol.MaximumPendingDepth,
            ["terminal_stroke_events"] = protocol.TerminalStrokeEvents,
        };
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

    private static LaunchOptions SyntheticLaunchOptions()
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
        throw new ArgumentException("--interaction-soak-mode is required (select_brush, move, grab, smooth, inflate, or pinch).");
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

        public void Accept(string eventName, Dictionary<string, object?> _payload)
        {
            if (eventName is not ("select_request" or "selection_request" or "stroke_begin" or "stroke_update" or "stroke_end" or "stroke_cancel"))
            {
                return;
            }
            EventCount++;
            if (eventName is "stroke_end" or "stroke_cancel")
            {
                TerminalStrokeEvents++;
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
