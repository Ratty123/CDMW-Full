using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private const string MeshEditRevisionCapability = "mesh_edit_revision_ack_v1";
    private const string MutationEnvelopeCapability = "resident_mutation_envelope_v2";
    private const string ResidentMaterialUpdatesCapability = "resident_material_updates_v2";
    private const string ResidentMaterialParameterUpdatesCapability = "resident_material_parameter_updates_v1";
    private const string ViewportDisplayModesCapability = "viewport_display_modes_v1";
    private const string ResidentSceneCapability = "resident_scene_state_v1";
    private const string AuthoritativeResidentSceneCapability = "authoritative_resident_scene_frame_v2";
    private long _lastAppliedEditRevision;
    private long _lastObservedSessionRevision;
    private long _outgoingMutationRequestSequence;
    private long _residentProcessGeneration;
    private bool _applyingResidentStateResync;
    private readonly Queue<ParsedProtocolMessage> _parsedProtocolMessages = new();
    private readonly Dictionary<string, ParsedProtocolMessage> _latestParsedProtocolMessages = new(StringComparer.Ordinal);
    private readonly object _parsedProtocolMessageLock = new();
    private readonly SemaphoreSlim _orderedProtocolSlots = new(MaximumParsedProtocolBacklog, MaximumParsedProtocolBacklog);
    private readonly SemaphoreSlim _latestProtocolSlot = new(1, 1);
    private int _parsedProtocolMessageCount;
    private int _protocolDrainScheduled;
    private long _parsedProtocolArrivalSequence;
    private const int MaximumParsedProtocolBacklog = 2048;

    private readonly record struct ParsedProtocolMessage(
        JsonElement Root,
        string EventName,
        IReadOnlyList<PreviewVertexGroup>? PreparedVertexUpdate = null,
        bool VertexUpdatePrepared = false,
        PreviewTriangleUpdatePlan? PreparedTriangleUpdate = null,
        bool TriangleUpdatePrepared = false,
        long ArrivalSequence = 0L);

    private static Dictionary<string, object?> MetricsPayload(RenderMetrics metrics)
    {
        return new Dictionary<string, object?>
        {
            ["metrics"] = new Dictionary<string, object?>
            {
                ["average_fps"] = metrics.AverageFps,
                ["frame_time_ms"] = metrics.AverageFrameMs,
                ["render_time_ms"] = metrics.AverageRenderMs,
                ["frame_interval_ms"] = metrics.AverageFrameIntervalMs,
                ["frame_interval_p95_ms"] = metrics.FrameIntervalP95Ms,
                ["frame_interval_max_ms"] = metrics.FrameIntervalMaxMs,
                ["frame_pacing_jitter_ms"] = metrics.FramePacingJitterMs,
                ["present_time_ms"] = metrics.AveragePresentMs,
                ["dirty_to_present_ms"] = metrics.AverageDirtyToPresentMs,
                ["dropped_frames"] = metrics.DroppedFrames,
                ["responsiveness_ms"] = metrics.AverageResponsivenessMs,
                ["frame_count"] = metrics.FrameCount,
                ["has_rendered_frame"] = metrics.HasRenderedFrame,
                ["memory_mb"] = Environment.WorkingSet / (1024.0 * 1024.0)
            }
        };
    }

    private static string RendererMetricsText(RenderMetrics metrics, string backend, bool compact)
    {
        if (!metrics.HasRenderedFrame)
        {
            return compact
                ? "FPS -- | Frame -- ms"
                : $"Renderer ready, waiting for first frame | Backend: {backend}";
        }
        return compact
            ? $"FPS {metrics.AverageFps:0.0} | Interval {metrics.AverageFrameIntervalMs:0.00} ms | P95 {metrics.FrameIntervalP95Ms:0.00} ms"
            : $"FPS: {metrics.AverageFps:0.0} | Interval: {metrics.AverageFrameIntervalMs:0.00} ms | P95: {metrics.FrameIntervalP95Ms:0.00} ms | Render: {metrics.AverageRenderMs:0.00} ms | Present: {metrics.AveragePresentMs:0.00} ms | Backend: {backend}";
    }

    private void StartProtocolReader()
    {
        _ = Task.Run(() =>
        {
            try
            {
                using var reader = new StreamReader(
                    Console.OpenStandardInput(),
                    Encoding.UTF8,
                    detectEncodingFromByteOrderMarks: true,
                    bufferSize: 4096,
                    leaveOpen: true);
                var protocolCapabilities = HelperBuildProvenance.RequiredProtocolCapabilities;
                WriteProtocolEvent("protocol_ready", new Dictionary<string, object?>
                {
                    ["capabilities"] = protocolCapabilities,
                    ["provenance"] = HelperBuildProvenance.Payload(protocolCapabilities),
                });
                string? line;
                while ((line = reader.ReadLine()) is not null)
                {
                    var received = Stopwatch.GetTimestamp();
                    var allocatedBytesBefore = PreviewPerformanceCapture.IsActive
                        ? GC.GetAllocatedBytesForCurrentThread()
                        : 0L;
                    if (PreviewPerformanceCapture.IsActive)
                    {
                        PreviewPerformanceCapture.RecordPhase(
                            PreviewPerformancePhase.ProtocolReceive,
                            received,
                            received,
                            allocatedBytesBefore);
                    }
                    try
                    {
                        using var document = JsonDocument.Parse(line);
                        if (document.RootElement.ValueKind != JsonValueKind.Object)
                        {
                            continue;
                        }
                        var root = document.RootElement.Clone();
                        var eventName = JsonString(root, "event");
                        if (eventName.Length == 0)
                        {
                            eventName = JsonString(root, "type");
                        }
                        eventName = eventName.Trim().ToLowerInvariant();
                        var parsed = Stopwatch.GetTimestamp();
                        if (PreviewPerformanceCapture.IsActive)
                        {
                            PreviewPerformanceCapture.RecordPhase(
                                PreviewPerformancePhase.ProtocolParse,
                                received,
                                parsed,
                                allocatedBytesBefore,
                                JsonLongValue(root, "request_id"));
                        }
                        if (IsPerformanceInputEvent(eventName))
                        {
                            PreviewPerformanceCapture.RecordInputAtTimestamp(
                                PreviewPerformanceInputKind.Protocol,
                                JsonLongValue(root, "request_id"),
                                received);
                        }
                        if (eventName == "performance_heartbeat")
                        {
                            PreviewPerformanceCapture.RecordHeartbeat(PreviewPerformanceHeartbeatKind.QtHost);
                            continue;
                        }
                        if (eventName == "performance_input")
                        {
                            continue;
                        }
                        IReadOnlyList<PreviewVertexGroup>? preparedVertexUpdate = null;
                        var vertexUpdatePrepared = false;
                        if (eventName == "preview_vertex_update")
                        {
                            vertexUpdatePrepared = true;
                            var vertexAllocatedBytesBefore = PreviewPerformanceCapture.IsActive
                                ? GC.GetAllocatedBytesForCurrentThread()
                                : 0L;
                            var vertexStarted = Stopwatch.GetTimestamp();
                            if (root.TryGetProperty("vertex_groups", out var vertexGroups)
                                && vertexGroups.ValueKind == JsonValueKind.Array)
                            {
                                _ = TryParsePreviewVertexGroups(vertexGroups, out preparedVertexUpdate);
                            }
                            if (PreviewPerformanceCapture.IsActive)
                            {
                                PreviewPerformanceCapture.RecordPhase(
                                    PreviewPerformancePhase.VertexPrepare,
                                    vertexStarted,
                                    Stopwatch.GetTimestamp(),
                                    vertexAllocatedBytesBefore,
                                    JsonLongValue(root, "request_id"));
                            }
                        }
                        PreviewTriangleUpdatePlan? preparedTriangleUpdate = null;
                        var triangleUpdatePrepared = false;
                        if (eventName == "preview_triangle_update")
                        {
                            triangleUpdatePrepared = true;
                            var topologyAllocatedBytesBefore = PreviewPerformanceCapture.IsActive
                                ? GC.GetAllocatedBytesForCurrentThread()
                                : 0L;
                            var topologyStarted = Stopwatch.GetTimestamp();
                            if (root.TryGetProperty("triangle_groups", out var triangleGroups)
                                && triangleGroups.ValueKind == JsonValueKind.Array)
                            {
                                _ = TryPreparePreviewTriangleGroups(root, triangleGroups, out preparedTriangleUpdate);
                            }
                            if (PreviewPerformanceCapture.IsActive)
                            {
                                PreviewPerformanceCapture.RecordPhase(
                                    PreviewPerformancePhase.TopologyPrepare,
                                    topologyStarted,
                                    Stopwatch.GetTimestamp(),
                                    topologyAllocatedBytesBefore,
                                    JsonLongValue(root, "request_id"));
                            }
                        }
                        QueueParsedProtocolMessage(new ParsedProtocolMessage(
                            root,
                            eventName,
                            preparedVertexUpdate,
                            vertexUpdatePrepared,
                            preparedTriangleUpdate,
                            triangleUpdatePrepared));
                    }
                    catch (JsonException ex)
                    {
                        WriteProtocolEvent("error", new Dictionary<string, object?>
                        {
                            ["message"] = $"Malformed protocol JSON: {ex.Message}",
                        });
                    }
                }
            }
            catch (IOException)
            {
            }
        });
    }

    private void HandleProtocolLine(string line)
    {
        if (string.IsNullOrWhiteSpace(line))
        {
            return;
        }
        try
        {
            using var document = JsonDocument.Parse(line);
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                return;
            }
            var root = document.RootElement;
            var eventName = JsonString(root, "event");
            if (eventName.Length == 0)
            {
                eventName = JsonString(root, "type");
            }
            HandleParsedProtocolMessage(new ParsedProtocolMessage(root.Clone(), eventName.Trim().ToLowerInvariant()));
        }
        catch (JsonException ex)
        {
            WriteProtocolEvent("error", new Dictionary<string, object?> { ["message"] = $"Malformed protocol JSON: {ex.Message}" });
        }
    }

    private void QueueParsedProtocolMessage(ParsedProtocolMessage message)
    {
        message = message with { ArrivalSequence = Interlocked.Increment(ref _parsedProtocolArrivalSequence) };
        var coalescingKey = ProtocolCoalescingKey(message);
        if (coalescingKey is not null)
        {
            lock (_parsedProtocolMessageLock)
            {
                if (_latestParsedProtocolMessages.ContainsKey(coalescingKey))
                {
                    PreviewPerformanceCapture.RecordProtocolInputCoalesced();
                    _latestParsedProtocolMessages[coalescingKey] = message;
                    PreviewPerformanceCapture.RecordProtocolInputQueueDepth(1);
                    ScheduleProtocolDrain();
                    return;
                }
            }
            _latestProtocolSlot.Wait();
            lock (_parsedProtocolMessageLock)
            {
                _latestParsedProtocolMessages[coalescingKey] = message;
                _parsedProtocolMessageCount++;
            }
            PreviewPerformanceCapture.RecordProtocolInputQueueDepth(1);
            ScheduleProtocolDrain();
            return;
        }
        _orderedProtocolSlots.Wait();
        int orderedDepth;
        lock (_parsedProtocolMessageLock)
        {
            _parsedProtocolMessages.Enqueue(message);
            _parsedProtocolMessageCount++;
            orderedDepth = _parsedProtocolMessages.Count;
        }
        PreviewPerformanceCapture.RecordOrderedProtocolInputQueueDepth(orderedDepth);
        ScheduleProtocolDrain();
    }

    private static string? ProtocolCoalescingKey(ParsedProtocolMessage message)
    {
        var root = message.Root;
        var sessionId = JsonString(root, "session_id").Trim();
        return message.EventName switch
        {
            "preview_vertex_update" or "preview_triangle_update" => $"{message.EventName}|{sessionId}",
            "texture_region_update" => $"{message.EventName}|{JsonString(root, "resource_id").Trim()}",
            "material_state_update" or "material_parameter_update" => $"{message.EventName}|{sessionId}",
            "viewport_display_update" or "scene_state_update" or "presentation_state_update" => message.EventName,
            _ => null,
        };
    }

    private void ScheduleProtocolDrain()
    {
        if (Interlocked.CompareExchange(ref _protocolDrainScheduled, 1, 0) != 0)
        {
            return;
        }
        try
        {
            BeginInvoke(new Action(DrainParsedProtocolMessages));
        }
        catch (InvalidOperationException)
        {
            Interlocked.Exchange(ref _protocolDrainScheduled, 0);
        }
    }

    private void DrainParsedProtocolMessages()
    {
        const int maximumMessagesPerDispatch = 32;
        var processed = 0;
        while (processed < maximumMessagesPerDispatch && TryDequeueParsedProtocolMessage(out var message))
        {
            HandleParsedProtocolMessage(message);
            processed++;
        }
        Interlocked.Exchange(ref _protocolDrainScheduled, 0);
        lock (_parsedProtocolMessageLock)
        {
            if (_parsedProtocolMessageCount > 0)
            {
                ScheduleProtocolDrain();
            }
        }
    }

    private bool TryDequeueParsedProtocolMessage(out ParsedProtocolMessage message)
    {
        var releaseOrderedSlot = false;
        var releaseLatestSlot = false;
        lock (_parsedProtocolMessageLock)
        {
            var hasOrdered = _parsedProtocolMessages.TryPeek(out var ordered);
            string? latestKey = null;
            ParsedProtocolMessage latest = default;
            foreach (var pair in _latestParsedProtocolMessages)
            {
                if (latestKey is null || pair.Value.ArrivalSequence < latest.ArrivalSequence)
                {
                    latestKey = pair.Key;
                    latest = pair.Value;
                }
            }
            if (!hasOrdered && latestKey is null)
            {
                message = default;
                return false;
            }
            if (hasOrdered && (latestKey is null || ordered.ArrivalSequence < latest.ArrivalSequence))
            {
                message = _parsedProtocolMessages.Dequeue();
                releaseOrderedSlot = true;
            }
            else
            {
                message = latest;
                _latestParsedProtocolMessages.Remove(latestKey!);
                releaseLatestSlot = true;
            }
            _parsedProtocolMessageCount--;
        }
        if (releaseOrderedSlot)
        {
            _orderedProtocolSlots.Release();
        }
        if (releaseLatestSlot)
        {
            _latestProtocolSlot.Release();
        }
        return true;
    }

    private void HandleParsedProtocolMessage(ParsedProtocolMessage message)
    {
        var root = message.Root;
        var eventName = message.EventName;
        var captureActive = PreviewPerformanceCapture.IsActive;
        var allocatedBytesBefore = captureActive ? GC.GetAllocatedBytesForCurrentThread() : 0L;
        var applyStarted = captureActive ? Stopwatch.GetTimestamp() : 0L;
        try
        {
            switch (eventName)
            {
                case "close_request":
                    Close();
                    break;
                case "deactivate_request":
                    _embeddedViewportActive = false;
                    Hide();
                    WriteProtocolEvent("deactivated");
                    break;
                case "activate_request":
                    var requestedMaterialSignature = JsonString(root, "material_signature");
                    if (requestedMaterialSignature.Length > 0 && !string.Equals(requestedMaterialSignature, _materials.Signature, StringComparison.Ordinal))
                    {
                        RequestMaterialSync(requestedMaterialSignature);
                        break;
                    }
                    _ = ActivateResidentViewport();
                    break;
                case "session_state":
                    ObserveResidentSession(root);
                    ApplyHistoryState(root);
                    ApplySelectionUpdate(root, requireCorrelation: false);
                    _statusLabel.Text = "Live MeshService bridge connected.";
                    break;
                case "tool_state": ApplyHostToolState(root); break;
                case "selection_update":
                    if (ApplySelectionUpdate(root))
                    {
                        _statusLabel.Text = "Selection updated by MeshService.";
                    }
                    else
                    {
                        _statusLabel.Text = "Ignored stale or uncorrelated selection update.";
                    }
                    break;
                case "preview_vertex_update":
                    ApplyPreviewVertexUpdate(
                        root,
                        message.PreparedVertexUpdate,
                        message.VertexUpdatePrepared);
                    break;
                case "preview_triangle_update":
                    ApplyPreviewTriangleUpdate(
                        root,
                        message.PreparedTriangleUpdate,
                        message.TriangleUpdatePrepared);
                    break;
                case "resident_state_resync":
                    ApplyResidentStateResync(root);
                    break;
                case "material_state_update":
                    HandleMaterialStateUpdate(root);
                    break;
                case "material_parameter_update":
                    HandleMaterialParameterUpdate(root);
                    break;
                case "texture_region_update":
                    HandleTextureRegionUpdate(root);
                    break;
                case "viewport_display_update":
                    HandleViewportDisplayUpdate(root);
                    break;
                case "scene_state_update":
                    HandleSceneStateUpdate(root);
                    break;
                case "presentation_state_update":
                    HandlePresentationStateUpdate(root);
                    break;
                case "capture_request":
                    HandleCaptureRequest(root);
                    break;
                case "performance_capture_start":
                    HandlePerformanceCaptureStart(root);
                    break;
                case "performance_capture_stop":
                    HandlePerformanceCaptureStop(root);
                    break;
                case "performance_heartbeat":
                    HandlePerformanceHeartbeat(root);
                    break;
                case "performance_input":
                    break;
                case "command_result":
                    HandleCommandResult(root);
                    break;
            }
        }
        finally
        {
            if (captureActive)
            {
                PreviewPerformanceCapture.RecordPhase(
                    PreviewPerformancePhase.ProtocolApply,
                    applyStarted,
                    Stopwatch.GetTimestamp(),
                    allocatedBytesBefore,
                    JsonLongValue(root, "request_id"));
            }
        }
    }

    private static bool IsPerformanceInputEvent(string eventName) => eventName is
        "performance_input" or
        "preview_vertex_update" or
        "preview_triangle_update" or
        "texture_region_update" or
        "material_state_update" or
        "material_parameter_update" or
        "viewport_display_update" or
        "scene_state_update" or
        "presentation_state_update";

    private void HandleCaptureRequest(JsonElement root)
    {
        void Reject(string message)
        {
            var rejected = new Dictionary<string, object?>
            {
                ["status"] = "rejected",
                ["message"] = message,
            };
            CopyMutationEnvelope(root, rejected);
            WriteProtocolEvent("capture_result", rejected);
        }

        var sessionId = JsonString(root, "session_id").Trim();
        var requestId = JsonLongValue(root, "request_id");
        var processGeneration = JsonLongValue(root, "process_generation");
        var sessionMatches = AcceptMaterialSession(sessionId, out var sessionError);
        if (requestId <= 0
            || processGeneration != _residentProcessGeneration
            || !sessionMatches)
        {
            Reject(string.IsNullOrWhiteSpace(sessionError)
                ? "Capture request correlation does not match the resident process."
                : sessionError);
            return;
        }
        var requestedPath = JsonString(root, "output_path");
        string outputRoot;
        string outputPath;
        try
        {
            outputRoot = Path.GetFullPath(_options.OutputDir);
            outputPath = Path.IsPathRooted(requestedPath)
                ? Path.GetFullPath(requestedPath)
                : Path.GetFullPath(Path.Combine(outputRoot, requestedPath));
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            Reject($"Invalid capture output path: {ex.Message}");
            return;
        }
        var outputRootPrefix = outputRoot.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        if (!outputPath.StartsWith(outputRootPrefix, StringComparison.OrdinalIgnoreCase))
        {
            Reject("Capture output must remain inside the package output directory.");
            return;
        }
        if (CapturePathTraversesReparsePoint(outputRoot, outputPath))
        {
            Reject("Capture output must not traverse a reparse-point alias.");
            return;
        }
        var width = (int)Math.Clamp(JsonLongValue(root, "width"), 64, 2048);
        var height = (int)Math.Clamp(JsonLongValue(root, "height"), 64, 2048);
        var ok = _viewport.TryCaptureReplacementPng(outputPath, width, height, out var sha256, out var error);
        var payload = new Dictionary<string, object?>
        {
            ["status"] = ok ? "captured" : "error",
            ["output_path"] = ok ? outputPath : string.Empty,
            ["sha256"] = sha256,
            ["width"] = width,
            ["height"] = height,
            ["ui_excluded"] = true,
            ["grid_excluded"] = true,
            ["gizmo_excluded"] = true,
            ["selection_excluded"] = true,
            ["hover_excluded"] = true,
            ["visible_view_mutated"] = false,
            ["message"] = error,
        };
        CopyMutationEnvelope(root, payload);
        WriteProtocolEvent("capture_result", payload);
    }

    private static bool CapturePathTraversesReparsePoint(string outputRoot, string outputPath)
    {
        static bool IsReparsePoint(string path)
        {
            try
            {
                return File.Exists(path) || Directory.Exists(path)
                    ? (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0
                    : false;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                return true;
            }
        }

        if (IsReparsePoint(outputRoot))
        {
            return true;
        }
        var relative = Path.GetRelativePath(outputRoot, outputPath);
        var current = outputRoot;
        foreach (var component in relative.Split(
            new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar },
            StringSplitOptions.RemoveEmptyEntries)[..^1])
        {
            current = Path.Combine(current, component);
            if (IsReparsePoint(current))
            {
                return true;
            }
        }
        return IsReparsePoint(outputPath);
    }

    private void ApplyPreviewVertexUpdate(JsonElement root) =>
        ApplyPreviewVertexUpdate(root, null, vertexUpdatePrepared: false);

    private void ApplyPreviewVertexUpdate(
        JsonElement root,
        IReadOnlyList<PreviewVertexGroup>? preparedVertexUpdate,
        bool vertexUpdatePrepared)
    {
        var revision = ProtocolEditRevision(root);
        if (!CanApplyEditRevision(revision, out var rejectionReason))
        {
            WriteEditRevisionAck(root, "preview_vertex_update_ack", "rejected", revision, 0, rejectionReason);
            return;
        }
        IReadOnlyList<PreviewVertexGroup> parsedGroups;
        if (vertexUpdatePrepared)
        {
            if (preparedVertexUpdate is null
                || !ValidatePreviewVertexGroups(_document, preparedVertexUpdate))
            {
                WriteEditRevisionAck(root, "preview_vertex_update_ack", "rejected", revision, 0, "invalid_payload");
                return;
            }
            parsedGroups = preparedVertexUpdate;
        }
        else
        {
            if (!root.TryGetProperty("vertex_groups", out var groups)
                || groups.ValueKind != JsonValueKind.Array
                || !TryParsePreviewVertexGroups(_document, groups, out parsedGroups))
            {
                WriteEditRevisionAck(root, "preview_vertex_update_ack", "rejected", revision, 0, "invalid_payload");
                return;
            }
        }
        var captureVertex = PreviewPerformanceCapture.IsActive;
        var vertexAllocatedBytesBefore = captureVertex ? GC.GetAllocatedBytesForCurrentThread() : 0L;
        var vertexStarted = captureVertex ? Stopwatch.GetTimestamp() : 0L;
        var changedPositions = new Dictionary<int, HashSet<int>>();
        var changedNormals = new Dictionary<int, HashSet<int>>();
        var changedUvs = new Dictionary<int, HashSet<int>>();
        foreach (var group in parsedGroups)
        {
            var submesh = _document.Submeshes[group.SubmeshIndex];
            var updateCount = group.Indices.Count;
            var applyNormals = group.Normals.Count > 0;
            var applyUvs = group.Uvs.Count > 0;
            if (applyNormals)
            {
                EnsureVertexAlignedNormals(submesh);
            }
            if (applyUvs)
            {
                EnsureVertexAlignedUvs(submesh);
            }
            for (var i = 0; i < updateCount; i++)
            {
                var vertexIndex = group.Indices[i];
                var p = i * 3;
                submesh.Vertices[vertexIndex] = new Vec3(
                    (float)group.Positions[p],
                    (float)group.Positions[p + 1],
                    (float)group.Positions[p + 2]);
                AddChangedChannel(changedPositions, group.SubmeshIndex, vertexIndex);
                if (applyNormals)
                {
                    submesh.Normals[vertexIndex] = new Vec3(
                        (float)group.Normals[p],
                        (float)group.Normals[p + 1],
                        (float)group.Normals[p + 2]);
                    AddChangedChannel(changedNormals, group.SubmeshIndex, vertexIndex);
                }
                var uv = i * 2;
                if (applyUvs)
                {
                    submesh.Uvs[vertexIndex] = new Vec2((float)group.Uvs[uv], (float)group.Uvs[uv + 1]);
                    AddChangedChannel(changedUvs, group.SubmeshIndex, vertexIndex);
                }
            }
            if (updateCount > 0)
            {
                _editedSubmeshes.Add(group.SubmeshIndex);
            }
        }
        if (changedPositions.Count > 0)
        {
            var changedChannels = changedPositions.Keys
                .Concat(changedNormals.Keys)
                .Concat(changedUvs.Keys)
                .Distinct()
                .ToDictionary(
                    submeshIndex => submeshIndex,
                    submeshIndex => new MeshVertexChannelChanges(
                        ChangedChannel(changedPositions, submeshIndex),
                        ChangedChannel(changedNormals, submeshIndex),
                        ChangedChannel(changedUvs, submeshIndex)));
            _viewport.RefreshVertexGeometry(changedChannels);
            _viewport.Invalidate();
            _statusLabel.Text = "Vertex update applied from MeshService.";
        }
        if (captureVertex)
        {
            PreviewPerformanceCapture.RecordPhase(
                PreviewPerformancePhase.VertexCommit,
                vertexStarted,
                Stopwatch.GetTimestamp(),
                vertexAllocatedBytesBefore,
                JsonLongValue(root, "request_id"));
        }
        MarkEditRevisionApplied(revision);
        WriteEditRevisionAck(
            root,
            "preview_vertex_update_ack",
            "applied",
            revision,
            changedPositions.Values.Sum(indices => indices.Count),
            "");
    }

    private static void AddChangedChannel(Dictionary<int, HashSet<int>> changed, int submeshIndex, int sourceIndex)
    {
        if (!changed.TryGetValue(submeshIndex, out var indices))
        {
            indices = new HashSet<int>();
            changed[submeshIndex] = indices;
        }
        indices.Add(sourceIndex);
    }

    private static IReadOnlyCollection<int> ChangedChannel(
        IReadOnlyDictionary<int, HashSet<int>> changed,
        int submeshIndex)
    {
        return changed.TryGetValue(submeshIndex, out var indices) ? indices : Array.Empty<int>();
    }

    private void ApplyPreviewTriangleUpdate(JsonElement root) =>
        ApplyPreviewTriangleUpdate(root, null, triangleUpdatePrepared: false);

    private void ApplyPreviewTriangleUpdate(
        JsonElement root,
        PreviewTriangleUpdatePlan? preparedTriangleUpdate,
        bool triangleUpdatePrepared)
    {
        var revision = ProtocolEditRevision(root);
        if (!CanApplyEditRevision(revision, out var rejectionReason))
        {
            WriteEditRevisionAck(root, "preview_triangle_update_ack", "rejected", revision, 0, rejectionReason);
            return;
        }
        JsonElement groups = default;
        if ((!triangleUpdatePrepared
                && (!root.TryGetProperty("triangle_groups", out groups) || groups.ValueKind != JsonValueKind.Array))
            || (triangleUpdatePrepared && preparedTriangleUpdate is null))
        {
            WriteEditRevisionAck(root, "preview_triangle_update_ack", "rejected", revision, 0, "invalid_payload");
            return;
        }
        var captureTopology = PreviewPerformanceCapture.IsActive;
        var topologyAllocatedBytesBefore = captureTopology ? GC.GetAllocatedBytesForCurrentThread() : 0L;
        var topologyStarted = captureTopology ? Stopwatch.GetTimestamp() : 0L;
        var previousEditableSubmeshCount = Math.Clamp(
            _scene.EditableSubmeshCount,
            0,
            _document.Submeshes.Count);
        var preservedReferenceSubmeshCount = _document.Submeshes.Count - previousEditableSubmeshCount;
        var applied = triangleUpdatePrepared
            ? TryCommitPreviewTriangleGroups(
                _document,
                preparedTriangleUpdate!,
                previousEditableSubmeshCount,
                out var changedCount,
                out var affectedSubmeshes,
                out var materialSources,
                out var topologySources,
                out var replaceAll)
            : TryApplyPreviewTriangleGroups(
                _document,
                root,
                groups,
                previousEditableSubmeshCount,
                out changedCount,
                out affectedSubmeshes,
                out materialSources,
                out topologySources,
                out replaceAll);
        if (captureTopology)
        {
            PreviewPerformanceCapture.RecordPhase(
                PreviewPerformancePhase.TopologyCommit,
                topologyStarted,
                Stopwatch.GetTimestamp(),
                topologyAllocatedBytesBefore,
                JsonLongValue(root, "request_id"));
        }
        if (!applied)
        {
            WriteEditRevisionAck(root, "preview_triangle_update_ack", "rejected", revision, 0, "invalid_payload");
            return;
        }
        if (changedCount > 0)
        {
            var editableSubmeshCount = Math.Max(
                0,
                _document.Submeshes.Count - preservedReferenceSubmeshCount);
            _scene.RemapTopologyState(
                topologySources,
                editableSubmeshCount,
                _document.Submeshes.Count);
            _externalTopologyDirty = true;
            _editedSubmeshes.UnionWith(affectedSubmeshes.Where(index => index >= 0 && index < editableSubmeshCount));
            var reboundMaterials = _materials.RemapTopologyState(materialSources, _document.Submeshes.Count);
            var residentMaterialSources = materialSources.ToDictionary(
                pair => pair.Key,
                pair => reboundMaterials.Contains(pair.Key) ? pair.Key : pair.Value);
            _viewport.RefreshTopologyGeometry(affectedSubmeshes, residentMaterialSources, replaceAll);
            RefreshSubmeshList();
            _viewport.Invalidate();
            _statusLabel.Text = "Topology preview updated by MeshService; Python session remains authoritative.";
        }
        MarkEditRevisionApplied(revision);
        WriteEditRevisionAck(root, "preview_triangle_update_ack", "applied", revision, changedCount, "");
    }

    private static long ProtocolEditRevision(JsonElement root)
    {
        foreach (var name in new[] { "edit_revision", "revision" })
        {
            if (!root.TryGetProperty(name, out var value))
            {
                continue;
            }
            if (value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number))
            {
                return Math.Max(0, number);
            }
            if (value.ValueKind == JsonValueKind.String && long.TryParse(
                    value.GetString(),
                    NumberStyles.Integer,
                    CultureInfo.InvariantCulture,
                    out number))
            {
                return Math.Max(0, number);
            }
        }
        return 0;
    }

    private bool CanApplyEditRevision(long revision, out string reason)
    {
        reason = "";
        if (revision <= 0)
        {
            return true;
        }
        if (revision < _lastAppliedEditRevision)
        {
            reason = "stale_or_out_of_order";
            return false;
        }
        return true;
    }

    private void MarkEditRevisionApplied(long revision)
    {
        if (revision <= 0)
        {
            return;
        }
        if (revision > _lastAppliedEditRevision)
        {
            _lastAppliedEditRevision = revision;
        }
    }

    private void WriteEditRevisionAck(
        JsonElement request,
        string eventName,
        string status,
        long revision,
        int changedItems,
        string reason)
    {
        if (_applyingResidentStateResync)
        {
            return;
        }
        var payload = new Dictionary<string, object?>
        {
            ["status"] = status,
            ["edit_revision"] = revision,
            ["revision"] = revision,
            ["last_applied_revision"] = _lastAppliedEditRevision,
            ["changed_items"] = changedItems,
            ["capabilities"] = new[] { MeshEditRevisionCapability, MutationEnvelopeCapability }
        };
        CopyMutationEnvelope(request, payload);
        if (!string.IsNullOrWhiteSpace(reason))
        {
            payload["reason"] = reason;
        }
        WriteProtocolEvent(eventName, payload);
    }

    private void ApplyResidentStateResync(JsonElement root)
    {
        var sessionId = JsonString(root, "session_id").Trim();
        var targetRevision = Math.Max(0, JsonLongValue(root, "target_revision"));
        if (string.IsNullOrWhiteSpace(sessionId)
            || !string.Equals(sessionId, _residentMaterialSessionId, StringComparison.Ordinal)
            || !root.TryGetProperty("packets", out var packets)
            || packets.ValueKind != JsonValueKind.Array)
        {
            WriteResidentStateResyncAck(root, "rejected", targetRevision, "invalid_session_or_snapshot");
            return;
        }
        var baseRevision = Math.Max(0, JsonLongValue(root, "base_revision"));
        _lastAppliedEditRevision = baseRevision;
        var sawGeometry = false;
        _applyingResidentStateResync = true;
        try
        {
            foreach (var packet in packets.EnumerateArray())
            {
                if (packet.ValueKind != JsonValueKind.Object)
                {
                    continue;
                }
                var eventName = JsonString(packet, "event").Trim().ToLowerInvariant();
                if (eventName == "preview_vertex_update")
                {
                    sawGeometry = true;
                    ApplyPreviewVertexUpdate(packet);
                }
                else if (eventName == "preview_triangle_update")
                {
                    sawGeometry = true;
                    ApplyPreviewTriangleUpdate(packet);
                }
                else if (eventName == "selection_update")
                {
                    ApplySelectionUpdate(packet, requireCorrelation: false);
                }
            }
        }
        finally
        {
            _applyingResidentStateResync = false;
        }
        if (!sawGeometry || _lastAppliedEditRevision < targetRevision)
        {
            WriteResidentStateResyncAck(root, "rejected", targetRevision, "snapshot_incomplete");
            return;
        }
        _lastObservedSessionRevision = Math.Max(_lastObservedSessionRevision, targetRevision);
        CompleteAuthoritativeResidentResync();
        WriteResidentStateResyncAck(root, "applied", targetRevision, "");
    }

    private void WriteResidentStateResyncAck(
        JsonElement request,
        string status,
        long revision,
        string reason)
    {
        var payload = new Dictionary<string, object?>
        {
            ["status"] = status,
            ["edit_revision"] = revision,
            ["revision"] = revision,
            ["last_applied_revision"] = _lastAppliedEditRevision,
            ["capabilities"] = new[] { MeshEditRevisionCapability, MutationEnvelopeCapability },
        };
        if (!string.IsNullOrWhiteSpace(reason))
        {
            payload["reason"] = reason;
        }
        CopyMutationEnvelope(request, payload);
        WriteProtocolEvent("resident_state_resync_ack", payload);
    }

    private static void CopyMutationEnvelope(
        JsonElement request,
        Dictionary<string, object?> response)
    {
        response["session_id"] = JsonString(request, "session_id").Trim();
        response["request_id"] = JsonLongValue(request, "request_id");
        response["base_revision"] = JsonLongValue(request, "base_revision");
        response["process_generation"] = JsonLongValue(request, "process_generation");
        response["protocol_version"] = Math.Max(2, JsonLongValue(request, "protocol_version"));
    }

    private bool ValidateMutationEnvelope(JsonElement request, out string reason)
    {
        var requestId = JsonLongValue(request, "request_id");
        var baseRevision = JsonLongValue(request, "base_revision");
        var editRevision = ProtocolEditRevision(request);
        var processGeneration = JsonLongValue(request, "process_generation");
        var protocolVersion = JsonLongValue(request, "protocol_version");
        if (requestId <= 0)
        {
            reason = "missing_request_id";
            return false;
        }
        if (processGeneration <= 0 || processGeneration != _residentProcessGeneration)
        {
            reason = "stale_process_generation";
            return false;
        }
        if (protocolVersion < 2 || baseRevision < 0 || editRevision < baseRevision)
        {
            reason = "invalid_mutation_envelope";
            return false;
        }
        reason = string.Empty;
        return true;
    }

    private void HandleSceneStateUpdate(JsonElement root)
    {
        var requestedProcessGeneration = JsonLongValue(root, "process_generation");
        var processMatches = requestedProcessGeneration > 0
            && (_residentProcessGeneration <= 0 || requestedProcessGeneration == _residentProcessGeneration);
        var rejectionReason = string.Empty;
        var applied = false;
        if (processMatches)
        {
            applied = _scene.TryApplyResidentUpdate(root, _document.Submeshes.Count, out rejectionReason);
        }
        else
        {
            rejectionReason = "stale_process_generation";
        }
        if (applied)
        {
            CompleteAuthoritativeSceneState();
            ApplyInteractionModeControls();
            _viewport.ApplySceneState();
            RefreshSubmeshList();
        }
        var payload = new Dictionary<string, object?>
        {
            ["status"] = applied ? "applied" : "rejected",
            ["reason"] = applied ? "" : rejectionReason,
            ["source_identity"] = JsonString(root, "source_identity"),
            ["scene_generation"] = JsonLongValue(root, "scene_generation"),
            ["comparison_mode"] = _scene.ComparisonMode,
            ["interaction_mode"] = _scene.InteractionMode,
            ["capabilities"] = new[] { ResidentSceneCapability, AuthoritativeResidentSceneCapability },
        };
        CopyMutationEnvelope(root, payload);
        WriteProtocolEvent("scene_state_update_ack", payload);
    }

    private bool ApplySelectionUpdate(JsonElement root, bool requireCorrelation = true)
    {
        if (!root.TryGetProperty("selection", out var selection) || selection.ValueKind != JsonValueKind.Object)
        {
            return false;
        }
        PendingMutationRequest? pending = null;
        var revision = Math.Max(0, ProtocolEditRevision(root));
        if (requireCorrelation
            && !TryPrepareCorrelatedSelectionUpdate(root, out pending, out revision))
        {
            return false;
        }
        var vertices = JsonSelectionMap(selection, "vertices_by_submesh");
        var faces = JsonSelectionMap(selection, "faces_by_submesh");
        var edges = JsonEdgeSelectionMap(selection, "edges_by_submesh");
        if (edges.Count == 0)
        {
            edges = JsonEdgeDescriptorSelectionMap(selection, "edge_descriptors");
        }
        var sources = JsonIntSet(selection, "source_indices");
        var requestId = requireCorrelation ? JsonLongValue(root, "request_id") : 0;
        if (!_viewport.UpdateSelection(vertices, faces, edges, sources, requestId, revision))
        {
            return false;
        }
        if (pending is not null)
        {
            CompleteCorrelatedSelectionUpdate(pending);
        }
        _viewport.Invalidate();
        return true;
    }
}
