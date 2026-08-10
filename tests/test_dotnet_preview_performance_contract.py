from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET / name).read_text(encoding="utf-8")


def test_sustained_frame_pacing_cli_and_evidence_contract_are_versioned() -> None:
    entry = _source("ProgramEntry.cs")
    options = _source("HeadlessGpuFramePacingSoakOptions.cs")
    soak = _source("HeadlessGpuFramePacingSoak.cs")
    report = _source("PreviewPerformanceReport.cs")

    assert entry.index("HeadlessGpuFramePacingSoak.IsRequested(args)") < entry.index("LaunchOptions.Parse(args)")
    assert '"--headless-gpu-frame-pacing-soak"' in entry
    for option in (
        "frame-pacing-report",
        "frame-pacing-duration-seconds",
        "frame-pacing-target-hz",
    ):
        assert option in options
    assert 'Number(values, "frame-pacing-duration-seconds", smoke ? 2.0 : 30.0' in options
    assert 'Number(values, "frame-pacing-target-hz", 144.0' in options
    assert 'Integer(values, "frame-pacing-warmup-frames", smoke ? 16 : 300' in options
    assert "Application.Run" not in soak
    assert "PresentSyncInterval == 1" in soak
    for gate in (
        "offscreen_msaa_resolve_active",
        "resolve_count_matches_presented_frames",
        "stable_render_surface_identity",
        "no_render_surface_recreation_during_capture",
    ):
        assert f'gates["{gate}"]' in soak
    assert '["anti_aliasing_mode"] = viewport.AntiAliasingMode' in soak
    assert '["render_sample_count"] = viewport.RenderSampleCount' in soak
    assert 'Schema = "cdmw_dotnet_preview_performance_v1"' in report
    assert "every frame in the snapshot is part of the measured interval" in report
    assert ".Skip(Math.Min(capture.Options.WarmupFrames" not in report
    assert '["raw"]' in report
    for field in (
        "frame_intervals_ms",
        "render_ms",
        "present_ms",
        "gpu_ms",
        "input_to_present_ms",
        "managed_allocated_bytes_per_frame",
        "winforms_heartbeat_gaps_ms",
        "qt_heartbeat_gaps_ms",
    ):
        assert f'["{field}"]' in report
    for gate in (
        "frame_interval_p95_at_most_8_68_ms",
        "frame_interval_p99_at_most_13_89_ms",
        "fewer_than_0_1_percent_over_13_89_ms",
        "no_frame_over_20_83_ms",
        "input_to_present_p95_at_most_13_89_ms",
        "host_heartbeat_at_most_33_3_ms",
        "zero_gen1_collections",
        "zero_gen2_collections",
        "every_input_accounted_for",
        "gpu_timing_samples_present",
        "configured_resolution",
    ):
        assert f'["{gate}"]' in report
    assert "inputToPresent.Length > 0" in report
    assert "winFormsHeartbeat.Length > 0" in report
    assert "qtHeartbeat.Length > 0" in report
    assert "capture.InputsReceived > 0" in report


def test_interaction_soak_drives_real_provisional_paths_and_required_gates() -> None:
    entry = _source("ProgramEntry.cs")
    soak = _source("HeadlessGpuInteractionSoak.cs")
    probe = _source("MeshViewport.InteractionSoak.cs")
    strokes = _source("MeshViewport.ProvisionalStrokes.cs")
    picking = _source("MeshViewport.SelectionPicking.cs") + _source("MeshViewport.SelectionPaint.cs")
    input_source = _source("MeshViewport.Input.cs")

    assert entry.index("HeadlessGpuInteractionSoak.IsRequested(args)") < entry.index(
        "LaunchOptions.Parse(args)"
    )
    assert '"--headless-gpu-interaction-soak"' in entry
    for mode in ("select_brush", "move", "grab", "smooth", "inflate", "pinch"):
        assert f'"{mode}"' in soak + probe
    assert "BeginSelectionDrag(start, \"vertex\")" in probe
    assert "BeginEditorStroke(start)" in probe
    assert "UpdateProvisionalEditorStroke(point)" in probe
    assert "FinishEdgeDrag(point)" in probe
    assert "CommitInteractionSoakGeometry" in probe
    assert "CompleteProvisionalAuthoritativeUpdate" in probe
    assert "SpatialBuckets" in strokes
    assert "GrabIndices" in strokes
    assert "VertexBuckets" in picking
    assert "DrawOverlayPrimitive(\n                PrimitiveTopology.PointList" in _source("D3D11MaterialViewport.Overlay.cs")
    assert "PrimitiveTopology.PointList when command.LineWidthPixels > 0.0f" in _source("D3D11MaterialViewport.Overlay.cs")
    provisional = _source("D3D11MaterialViewport.ProvisionalGeometry.cs")
    assert "ProvisionalRotatingFaceThreshold" in provisional
    assert "CreateProvisionalVertexBuffers" in provisional
    assert "AdvanceProvisionalVertexBuffer" in provisional
    assert "new SubresourceData((IntPtr)source)" in provisional
    assert "stableChangedSet: true" in _source("MeshViewport.ProvisionalStrokes.cs")
    assert "CaptureStableFaceRanges" in provisional
    assert "ActiveVertexBuffer(batch)" in _source("D3D11MaterialViewport.cs")
    assert "EditorStrokeProtocolIntervalMs = 16.0" in input_source
    assert "_strokeProtocolPrevious" in input_source
    for gate in (
        "input_to_present_p95_at_most_13_89_ms",
        "no_frame_over_20_83_ms",
        "host_heartbeat_at_most_33_3_ms",
        "protocol_pending_depth_at_most_one",
        "no_lost_cursor_coverage",
        "stale_result_did_not_roll_back_live_stroke",
        "zero_gen1_collections",
        "zero_gen2_collections",
        "final_authority_matches_visible_provisional_result",
        "viewport_tools_did_not_select_parts",
    ):
        assert f'["{gate}"]' in soak


def test_metric_capture_hot_paths_use_fixed_storage_and_deferred_statistics() -> None:
    metrics = _source("RuntimeSupport.cs")
    capture = _source("PreviewPerformanceCapture.cs")
    record = metrics.split("public void Record(double value)", maxsplit=1)[1].split(
        "public double Percentile", maxsplit=1
    )[0]

    assert "FixedMetricRing" in metrics
    assert "private readonly double[] _values;" in metrics
    assert "_sumSquares" in metrics
    assert "Queue<double>" not in metrics
    assert "OrderBy" not in record
    assert "ToArray" not in record
    assert "CadenceResetThresholdMs = 250.0" in metrics
    assert "if (intervalMs <= CadenceResetThresholdMs)" in metrics
    assert "new PreviewPerformanceFrameSample[frameCapacity]" in capture
    assert "new PreviewPerformancePhaseSample" in capture
    assert "new PreviewPerformanceHeartbeatSample" in capture
    assert "inputsCoalesced" in capture
    assert "lock (_inputSync)" in capture
    assert "CurrentWorkingSet() => Environment.WorkingSet" in capture
    assert "Process.GetCurrentProcess()" not in capture
    assert "CommitArrayPages(_frames)" in capture
    assert "CommitArrayPages(_phases)" in capture
    assert "CommitArrayPages(_heartbeats)" in capture
    assert "Volatile.Write(ref bytes[offset], (byte)0)" in capture
    assert '"preallocated_capture_storage_bytes"' in _source("PreviewPerformanceReport.cs")
    assert "PreviewPerformancePhase.SyntheticDriver" in _source("HeadlessGpuFramePacingSoak.cs")
    assert 'PreviewPerformancePhase.SyntheticDriver => "synthetic_driver"' in _source(
        "PreviewPerformanceReport.cs"
    )


def test_capture_samples_gc_before_allocating_snapshot_arrays() -> None:
    capture = _source("PreviewPerformanceCapture.cs")
    stop = capture.split(
        "public PreviewPerformanceCaptureSnapshot StopAndSnapshot()", maxsplit=1
    )[1].split("public void DisposeWithoutSnapshot()", maxsplit=1)[0]

    counter_sample = stop.index("var gcCount0Stop = GC.CollectionCount(0);")
    first_snapshot_array = stop.index(
        "var frames = new PreviewPerformanceFrameSample[frameCount];"
    )
    report = stop.index("return new PreviewPerformanceCaptureSnapshot(")

    assert counter_sample < first_snapshot_array < report
    assert "new[] { gcCount0Stop, gcCount1Stop, gcCount2Stop }" in stop
    assert "new[] { GC.CollectionCount(0)" not in stop


def test_gpu_timing_is_delayed_nonblocking_and_allocation_free_in_frame_capture() -> None:
    gpu = _source("D3D11MaterialViewport.GpuTiming.cs")
    renderer = _source("D3D11MaterialViewport.cs")
    headless = _source("D3D11MaterialViewport.Headless.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")
    report = _source("PreviewPerformanceReport.cs")

    assert "GpuTimingQuerySlotCount = 8" in gpu
    assert "CreateQuery(QueryType.TimestampDisjoint)" in gpu
    assert gpu.count("CreateQuery(QueryType.Timestamp)") == 2
    assert "AsyncGetDataFlags.DoNotFlush" in gpu
    assert "_context.Flush()" not in gpu
    assert "querySet.PerformanceFrameOrdinal = PreviewPerformanceCapture.NextFrameOrdinal" in gpu
    assert "PreviewPerformanceCapture.RecordGpuTime(querySet.PerformanceFrameOrdinal, gpuMs)" in gpu
    assert "with { GpuMs = gpuMs }" in _source("PreviewPerformanceCapture.cs")
    assert "BeginGpuTimingFrame(present && PreviewPerformanceCapture.IsActive);" in renderer
    assert "ResolvedGpuTimeForFrameMs" in renderer
    assert "ResolvedGpuTimeForFrameMs" in headless
    for metric in (
        "gpu_timestamp_queries_issued",
        "gpu_timestamp_queries_resolved",
        "gpu_timestamp_queries_disjoint",
        "gpu_timestamp_queries_dropped",
    ):
        assert f'["{metric}"]' in metrics
    assert '"d3d11_timestamp_disjoint_delayed_nonblocking"' in report
    assert '["gpu_timestamp_query_coverage"]' in report
    assert '["zero_gpu_timestamp_disjoint_or_dropped"]' in report


def test_protocol_io_is_bounded_ordered_and_telemetry_is_latest_wins() -> None:
    writer = _source("ProtocolOutputWriter.cs")
    output = _source("ExperimentForm.Output.cs")
    protocol = _source("ExperimentForm.Protocol.cs")
    program = _source("ProgramEntry.cs")

    assert "MaximumCriticalBacklog = 4096" in writer
    assert "ConcurrentQueue<IReadOnlyDictionary<string, object?>>" in writer
    assert "lock (_stateLock)" in writer
    assert "_latestTelemetry = message;" in writer
    assert "Interlocked.Increment(ref _telemetryCoalesced);" in writer
    assert "JsonSerializer.Serialize(message)" in writer
    assert "Console.Out.FlushAsync()" in writer
    assert "WaitForDrain(TimeSpan grace)" in writer
    assert 'string.Equals(eventName, "metrics", StringComparison.OrdinalIgnoreCase)' in output
    assert "EnqueueLatestTelemetry(message)" in output
    assert "EnqueueCritical(message)" in output
    assert "JsonDocument.Parse(line)" in protocol
    assert "QueueParsedProtocolMessage" in protocol
    assert "MaximumParsedProtocolBacklog = 2048" in protocol
    assert "_latestProtocolSlot = new(1, 1)" in protocol
    assert "_latestParsedProtocolMessages" in protocol
    assert "ProtocolCoalescingKey" in protocol
    assert "_orderedProtocolSlots.Wait()" in protocol
    assert "TryDequeueParsedProtocolMessage" in protocol
    assert "maximumMessagesPerDispatch = 32" in protocol
    assert 'eventName == "performance_input"' in protocol
    assert "RecordInputAtTimestamp" in protocol
    assert "PreviewPerformancePhase.ProtocolReceive" in protocol
    assert "DrainPerformanceReport(TimeSpan.FromSeconds(2))" in program
    assert "DrainProtocolOutput(TimeSpan.FromMilliseconds(750))" in program


def test_performance_protocol_capability_and_compact_completion_stay_additive() -> None:
    provenance = _source("HelperBuildProvenance.cs")
    status = _source("MeshViewport.Status.cs")
    protocol = _source("ExperimentForm.Protocol.cs")
    performance = _source("ExperimentForm.PerformanceProtocol.cs")
    runtime = _source("ExperimentForm.Runtime.cs")
    viewport = _source("Program.cs")
    packaging = (ROOT / "build_pyside6_app.ps1").read_text(encoding="utf-8")
    python_protocol = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_protocol.py").read_text(encoding="utf-8")

    for source in (provenance, status):
        assert '"performance_capture_v1"' in source
    # The packaged manifest no longer restates the capability list; it reads it
    # out of HelperBuildProvenance.cs, which is the copy asserted above. Naming
    # the literal here again would require the duplication that failed the
    # release build, so this asserts the derivation that replaced it.
    # tests/test_dotnet_helper_manifest_contract.py covers the parse itself.
    assert "function Get-DotNetMeshEditorHelperContract" in packaging
    assert "$helperContract = Get-DotNetMeshEditorHelperContract" in packaging
    assert '"performance_capture_v1"' not in packaging
    assert 'case "performance_capture_start":' in protocol
    assert 'case "performance_capture_stop":' in protocol
    assert '"performance_capture_complete"' in performance
    assert '"performance_capture_warming"' in performance
    assert "_performanceWarmupStartFrameCount" in performance
    assert "Metrics.FrameCount - _performanceWarmupStartFrameCount < options.WarmupFrames" in performance
    assert "ContinuePendingPerformanceCapture();" in runtime
    assert "new System.Threading.Timer(" in viewport
    assert 'DllImport("winmm.dll", EntryPoint = "timeBeginPeriod")' in viewport
    assert 'DllImport("winmm.dll", EntryPoint = "timeEndPeriod")' in viewport
    assert "TimeBeginPeriod(PerformanceTimerResolutionMilliseconds)" in viewport
    assert "TimeEndPeriod(PerformanceTimerResolutionMilliseconds)" in viewport
    assert "QueuePerformanceRenderFrame" in viewport
    assert "PerformanceRenderPumpState" in viewport
    assert "current.MinimumIntervalTicks == minimumIntervalTicks" in viewport
    assert "pump.Generation != Interlocked.Read(ref _performanceRenderPumpGeneration)" in viewport
    assert "Interlocked.CompareExchange(ref pump.Queued, 1, 0)" in viewport
    assert "BeginInvoke(pump.UiCallback)" in viewport
    assert "PreviewPerformanceCapture.RecordHeartbeat(PreviewPerformanceHeartbeatKind.WinForms)" in viewport
    assert "_viewport.PumpPerformanceRenderFrame();" not in runtime
    assert "_timer.Interval = 1;" not in performance
    assert "PreviewPerformanceReport.WriteAtomic" in performance
    assert "WritePreparedProtocolEventThreadSafe" in performance
    assert "SHA256.HashData" in performance
    assert '"report_path"' in performance
    assert '"report_size_bytes"' in performance
    assert '"report_sha256"' in performance
    assert '"performance_capture_complete"' in python_protocol


def test_retained_overlays_and_texture_updates_have_explicit_generation_and_frame_boundaries() -> None:
    overlay = _source("D3D11MaterialViewport.Overlay.cs")
    renderer = _source("D3D11MaterialViewport.cs")
    texture = _source("D3D11MaterialViewport.TextureRegions.cs")
    texture_protocol = _source("ExperimentForm.TextureRegionProtocol.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")
    lifecycle = _source("D3D11MaterialViewport.ControlLifecycle.cs")

    assert "D3D11OverlayGeometryGenerationKey" in overlay
    assert "_scene.PresentationGeneration" in overlay
    assert "_materialParameterApplyCount" in overlay
    assert "_comparisonWireOverlayCache" in overlay
    assert "_gridGeometryValid" in overlay
    assert "_retainedOverlayCacheHitCount++" in overlay
    assert "FlushOverlayPrimitives();" in overlay
    assert overlay.count("MapMode.WriteDiscard") == 1
    assert "private Dictionary<int, HashSet<int>> _overlaySelectedVertices" in renderer
    assert "_resizeCommitTimer.Start();" in lifecycle
    assert "_renderResourcesDirty = true;" in lifecycle
    assert "ApplyPendingTextureRegion();" in renderer
    assert "TryQueueTextureRegion" in texture
    assert "_pendingTextureRegions.TryGetValue(update.ResourceId, out var superseded)" in texture
    assert "_pendingTextureRegionOrder.Enqueue(update.ResourceId);" in texture
    assert "MaximumPendingTextureResources = 64" in texture
    assert "_textureRegionGpuUploadPassCount++" in texture
    assert "CompleteQueuedTextureRegionUpdate" in texture_protocol
    for metric in (
        "retained_overlay_cache_hits",
        "retained_overlay_rebuilds",
        "texture_region_gpu_upload_pass_count",
        "texture_region_coalesced_count",
        "texture_region_maximum_pending_depth",
        "swap_chain_resize_coalesced_count",
        "swap_chain_resize_commit_count",
        "render_sample_count",
        "render_sample_quality",
        "multisample_resolve_count",
        "render_surface_create_count",
        "render_surface_dispose_count",
        "render_surface_identity",
        "render_surface_bytes_estimate",
        "peak_render_surface_bytes_estimate",
        "peak_offscreen_capture_surface_bytes_estimate",
    ):
        assert f'["{metric}"]' in metrics
