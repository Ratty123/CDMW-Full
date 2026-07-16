using System.Diagnostics;
using System.Globalization;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class HeadlessGpuFramePacingSoak
{
    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(arg, "--headless-gpu-frame-pacing-soak", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var reportPath = HeadlessGpuFramePacingSoakOptions.ReportPathFrom(args);
        try
        {
            var options = HeadlessGpuFramePacingSoakOptions.Parse(args);
            return Execute(options);
        }
        catch (Exception ex)
        {
            var report = new Dictionary<string, object?>
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
            };
            PreviewPerformanceReport.WriteAtomic(reportPath, report);
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                schema = PreviewPerformanceReport.Schema,
                ok = false,
                report_path = reportPath,
                error = ex.Message,
            }));
            return 1;
        }
        finally
        {
            _ = PreviewPerformanceCapture.StopActive();
        }
    }

    private static int Execute(HeadlessGpuFramePacingSoakOptions options)
    {
        var document = HeadlessGpuSparseSoak.BuildSyntheticDocument(options.VertexCount);
        var materials = NetMaterialSet.Empty;
        using var textures = NetTextureSet.Load(materials);
        using var host = CreateHiddenHost(options);
        using var viewport = new D3D11MaterialViewport(
            document,
            materials,
            textures,
            NetSceneState.Load(string.Empty, document.Submeshes.Count))
        {
            Dock = DockStyle.Fill,
        };
        host.Controls.Add(viewport);
        host.CreateControl();
        _ = host.Handle;
        NativeWindowHost.ResizeHidden(host, options.Width, options.Height);
        host.PerformLayout();
        viewport.CreateControl();
        _ = viewport.Handle;
        if (!viewport.TryInitialize(out var initializeError))
        {
            throw new InvalidOperationException($"Hidden frame-pacing viewport initialization failed: {initializeError}");
        }
        var camera = HeadlessGpuSparseSoak.CameraFor(document, host.ClientSize);
        viewport.UpdateCamera(camera);
        for (var warmup = 0; warmup < options.WarmupFrames; warmup++)
        {
            viewport.UpdateCamera(OrbitCamera(camera, warmup));
            if (!viewport.TryRunHeadlessFrame(out _, out _, out var warmupError))
            {
                throw new InvalidOperationException($"Hidden frame-pacing warm-up frame {warmup} failed: {warmupError}");
            }
        }
        viewport.PreparePerformanceCapture();
        var resourcesBefore = viewport.ResourceMetricsPayload();
        var captureId = $"headless-{Guid.NewGuid():N}";
        var captureOptions = new PreviewPerformanceCaptureOptions(
            captureId,
            "headless_gpu_frame_pacing_soak",
            options.ReportPath,
            options.DurationSeconds,
            options.TargetHz,
            options.WarmupFrames,
            options.Width,
            options.Height,
            new Dictionary<string, object?>
            {
                ["kind"] = "generated_in_memory",
                ["checked_in_asset_used"] = false,
                ["source_vertex_count"] = document.Submeshes.Sum(submesh => submesh.Vertices.Count),
                ["triangle_count"] = document.Submeshes.Sum(submesh => submesh.Faces.Count),
                ["submesh_count"] = document.Submeshes.Count,
                ["sha256"] = string.Empty,
            });
        if (!PreviewPerformanceCapture.TryStart(captureOptions, out _, out var startError))
        {
            throw new InvalidOperationException(startError);
        }
        var duration = Stopwatch.StartNew();
        long frame = 0;
        while (duration.Elapsed.TotalSeconds < options.DurationSeconds)
        {
            var driverAllocatedBytesBefore = GC.GetAllocatedBytesForCurrentThread();
            var driverStartedTimestamp = Stopwatch.GetTimestamp();
            PreviewPerformanceCapture.RecordInput(PreviewPerformanceInputKind.Synthetic, frame + 1);
            viewport.UpdateCamera(OrbitCamera(camera, options.WarmupFrames + frame));
            if (!viewport.TryRunHeadlessFrame(out _, out _, out var frameError))
            {
                throw new InvalidOperationException($"Hidden frame-pacing frame {frame} failed: {frameError}");
            }
            PreviewPerformanceCapture.RecordHeartbeat(PreviewPerformanceHeartbeatKind.WinForms);
            PreviewPerformanceCapture.RecordPhase(
                PreviewPerformancePhase.SyntheticDriver,
                driverStartedTimestamp,
                Stopwatch.GetTimestamp(),
                driverAllocatedBytesBefore,
                frame + 1);
            frame++;
            if (frame % Math.Max(1L, (long)Math.Round(options.TargetHz, MidpointRounding.AwayFromZero)) == 0)
            {
                PreviewPerformanceCapture.SampleWorkingSet();
            }
        }
        duration.Stop();
        var snapshot = PreviewPerformanceCapture.Stop(captureId, out var stopError)
            ?? throw new InvalidOperationException(stopError);
        var resourcesAfter = viewport.ResourceMetricsPayload();
        var lifecycle = new Dictionary<string, object?>
        {
            ["process_restart_count"] = 0,
            ["device_reset_attempt_count"] = viewport.DeviceResetAttemptCount,
            ["device_reset_count"] = viewport.DeviceResetCount,
            ["device_removed_reason"] = viewport.DeviceRemovedReason,
            ["backend"] = viewport.BackendName,
            ["edit_backend"] = "cdmw_mesh_core_0.1",
            ["present_sync_interval"] = viewport.PresentSyncInterval,
            ["maximum_frame_latency"] = viewport.MaximumFrameLatency,
            ["presentation_model"] = viewport.PresentationModel,
            ["host_visible"] = host.Visible,
            ["show_in_taskbar"] = host.ShowInTaskbar,
            ["application_run_called"] = false,
            ["host_client_width"] = host.ClientSize.Width,
            ["host_client_height"] = host.ClientSize.Height,
            ["viewport_client_width"] = viewport.ClientSize.Width,
            ["viewport_client_height"] = viewport.ClientSize.Height,
        };
        var report = PreviewPerformanceReport.Build(snapshot, resourcesBefore, resourcesAfter, lifecycle);
        var gates = (Dictionary<string, bool>)report["gates"]!;
        gates["production_d3d11_backend"] = string.Equals(viewport.BackendName, "d3d11_vortice_shader", StringComparison.Ordinal);
        gates["vsync_preserved"] = viewport.PresentSyncInterval == 1;
        gates["native_window_remained_hidden"] = !host.Visible && !host.ShowInTaskbar;
        gates["configured_duration_completed"] = snapshot.ElapsedSeconds >= options.DurationSeconds * 0.98;
        gates["configured_resolution"] = viewport.ClientSize.Width == options.Width
            && viewport.ClientSize.Height == options.Height;
        var ok = gates.Values.All(value => value);
        report["ok"] = ok;
        report["release_gate_eligible"] = !options.Smoke
            && options.DurationSeconds >= 30.0
            && options.WarmupFrames >= 300
            && options.Width == 1920
            && options.Height == 1080
            && options.TargetHz >= 144.0;
        report["full_scale_gate_ok"] = report["release_gate_eligible"] is true && ok;
        PreviewPerformanceReport.WriteAtomic(options.ReportPath, report);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            schema = PreviewPerformanceReport.Schema,
            ok,
            smoke = options.Smoke,
            report_path = options.ReportPath,
            captured_frames = snapshot.Frames.Length,
        }));
        return options.Smoke ? (snapshot.Frames.Length > 0 ? 0 : 2) : (ok ? 0 : 2);
    }

    private static Form CreateHiddenHost(HeadlessGpuFramePacingSoakOptions options) => new()
    {
        Text = "CDMW hidden D3D11 frame-pacing soak",
        AutoScaleMode = AutoScaleMode.None,
        ClientSize = new Size(options.Width, options.Height),
        StartPosition = FormStartPosition.Manual,
        Location = new Point(-32000, -32000),
        FormBorderStyle = FormBorderStyle.None,
        ShowInTaskbar = false,
        Visible = false,
    };

    private static NetViewportCamera OrbitCamera(NetViewportCamera baseline, long frame)
    {
        var phase = (float)(frame % 720) / 720.0f;
        return NetViewportCamera.Create(
            baseline.Center,
            baseline.Bounds,
            baseline.Yaw + MathF.Sin(phase * MathF.Tau) * 0.12f,
            baseline.Pitch + MathF.Cos(phase * MathF.Tau) * 0.05f,
            baseline.Zoom,
            baseline.PanX,
            baseline.PanY,
            Math.Max(1, (int)MathF.Round(baseline.ViewportWidth)),
            Math.Max(1, (int)MathF.Round(baseline.ViewportHeight)));
    }
}
