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
                ["memory_mb"] = Process.GetCurrentProcess().WorkingSet64 / (1024.0 * 1024.0)
            }
        };
    }

    private static string RendererMetricsText(RenderMetrics metrics, IReadOnlyDictionary<string, object?> renderer, bool compact)
    {
        var backend = renderer.TryGetValue("backend", out var rawBackend)
            ? Convert.ToString(rawBackend, CultureInfo.InvariantCulture)
            : "unknown";
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
                    var captured = line;
                    try
                    {
                        BeginInvoke(new Action(() => HandleProtocolLine(captured)));
                    }
                    catch (InvalidOperationException)
                    {
                        break;
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
            var eventName = JsonString(document.RootElement, "event");
            if (eventName.Length == 0)
            {
                eventName = JsonString(document.RootElement, "type");
            }
            switch (eventName.Trim().ToLowerInvariant())
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
                    var requestedMaterialSignature = JsonString(document.RootElement, "material_signature");
                    if (requestedMaterialSignature.Length > 0 && !string.Equals(requestedMaterialSignature, _materials.Signature, StringComparison.Ordinal))
                    {
                        RequestMaterialSync(requestedMaterialSignature);
                        break;
                    }
                    _ = ActivateResidentViewport();
                    break;
                case "session_state":
                    ObserveResidentSession(document.RootElement);
                    ApplyHistoryState(document.RootElement);
                    ApplySelectionUpdate(document.RootElement, requireCorrelation: false);
                    _statusLabel.Text = "Live MeshService bridge connected.";
                    break;
                case "tool_state": ApplyHostToolState(document.RootElement); break;
                case "selection_update":
                    if (ApplySelectionUpdate(document.RootElement))
                    {
                        _statusLabel.Text = "Selection updated by MeshService.";
                    }
                    else
                    {
                        _statusLabel.Text = "Ignored stale or uncorrelated selection update.";
                    }
                    break;
                case "preview_vertex_update":
                    ApplyPreviewVertexUpdate(document.RootElement);
                    break;
                case "preview_triangle_update":
                    ApplyPreviewTriangleUpdate(document.RootElement);
                    break;
                case "resident_state_resync":
                    ApplyResidentStateResync(document.RootElement);
                    break;
                case "material_state_update":
                    HandleMaterialStateUpdate(document.RootElement);
                    break;
                case "material_parameter_update":
                    HandleMaterialParameterUpdate(document.RootElement);
                    break;
                case "texture_region_update":
                    HandleTextureRegionUpdate(document.RootElement);
                    break;
                case "viewport_display_update":
                    HandleViewportDisplayUpdate(document.RootElement);
                    break;
                case "scene_state_update":
                    HandleSceneStateUpdate(document.RootElement);
                    break;
                case "presentation_state_update":
                    HandlePresentationStateUpdate(document.RootElement);
                    break;
                case "capture_request":
                    HandleCaptureRequest(document.RootElement);
                    break;
                case "command_result":
                    HandleCommandResult(document.RootElement);
                    break;
            }
        }
        catch (JsonException ex)
        {
            WriteProtocolEvent("error", new Dictionary<string, object?> { ["message"] = $"Malformed protocol JSON: {ex.Message}" });
        }
    }

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

    private void ApplyPreviewVertexUpdate(JsonElement root)
    {
        var revision = ProtocolEditRevision(root);
        if (!CanApplyEditRevision(revision, out var rejectionReason))
        {
            WriteEditRevisionAck(root, "preview_vertex_update_ack", "rejected", revision, 0, rejectionReason);
            return;
        }
        if (!root.TryGetProperty("vertex_groups", out var groups) || groups.ValueKind != JsonValueKind.Array)
        {
            WriteEditRevisionAck(root, "preview_vertex_update_ack", "rejected", revision, 0, "invalid_payload");
            return;
        }
        if (!TryParsePreviewVertexGroups(_document, groups, out var parsedGroups))
        {
            WriteEditRevisionAck(root, "preview_vertex_update_ack", "rejected", revision, 0, "invalid_payload");
            return;
        }
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

    private void ApplyPreviewTriangleUpdate(JsonElement root)
    {
        var revision = ProtocolEditRevision(root);
        if (!CanApplyEditRevision(revision, out var rejectionReason))
        {
            WriteEditRevisionAck(root, "preview_triangle_update_ack", "rejected", revision, 0, rejectionReason);
            return;
        }
        if (!root.TryGetProperty("triangle_groups", out var groups) || groups.ValueKind != JsonValueKind.Array)
        {
            WriteEditRevisionAck(root, "preview_triangle_update_ack", "rejected", revision, 0, "invalid_payload");
            return;
        }
        if (!TryApplyPreviewTriangleGroups(
                _document,
                root,
                groups,
                out var changedCount,
                out var affectedSubmeshes,
                out var materialSources,
                out var replaceAll))
        {
            WriteEditRevisionAck(root, "preview_triangle_update_ack", "rejected", revision, 0, "invalid_payload");
            return;
        }
        if (changedCount > 0)
        {
            _externalTopologyDirty = true;
            _editedSubmeshes.UnionWith(affectedSubmeshes.Where(index => index < _document.Submeshes.Count));
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
