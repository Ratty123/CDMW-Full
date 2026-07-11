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
    private const string ResidentMaterialUpdatesCapability = "resident_material_updates_v2";
    private const string ResidentMaterialParameterUpdatesCapability = "resident_material_parameter_updates_v1";
    private const string ViewportDisplayModesCapability = "viewport_display_modes_v1";
    private long _lastAppliedEditRevision;
    private long _lastObservedSessionRevision;
    private readonly HashSet<string> _appliedPacketKindsForRevision = new(StringComparer.Ordinal);

    private static Dictionary<string, object?> MetricsPayload(RenderMetrics metrics)
    {
        return new Dictionary<string, object?>
        {
            ["metrics"] = new Dictionary<string, object?>
            {
                ["average_fps"] = metrics.AverageFps,
                ["frame_time_ms"] = metrics.AverageFrameMs,
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

    private static string RendererMetricsText(RenderMetrics metrics, IReadOnlyDictionary<string, object?> renderer, bool renderRequested)
    {
        var backend = renderer.TryGetValue("backend", out var rawBackend)
            ? Convert.ToString(rawBackend, CultureInfo.InvariantCulture)
            : "unknown";
        if (!metrics.HasRenderedFrame)
        {
            return $"Renderer ready, waiting for first frame | Backend: {backend}";
        }
        var state = renderRequested ? "render requested" : "idle";
        return $"FPS: {metrics.AverageFps:0.0} | Frame: {metrics.AverageFrameMs:0.00} ms | Present: {metrics.AveragePresentMs:0.00} ms | {state} | Backend: {backend}";
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
                WriteProtocolEvent("protocol_ready", new Dictionary<string, object?>
                {
                    ["capabilities"] = new[]
                    {
                        MeshEditRevisionCapability,
                        "host_tool_state_v1",
                        ResidentMaterialUpdatesCapability,
                        ResidentMaterialParameterUpdatesCapability,
                        ResidentTextureRegionUpdatesCapability,
                        ViewportDisplayModesCapability,
                    }
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
                    ApplySelectionUpdate(document.RootElement);
                    _statusLabel.Text = "Live MeshService bridge connected.";
                    break;
                case "tool_state": ApplyHostToolState(document.RootElement); break;
                case "selection_update":
                    ApplySelectionUpdate(document.RootElement);
                    _statusLabel.Text = "Selection updated by MeshService.";
                    break;
                case "preview_vertex_update":
                    ApplyPreviewVertexUpdate(document.RootElement);
                    break;
                case "preview_triangle_update":
                    ApplyPreviewTriangleUpdate(document.RootElement);
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
                case "command_result":
                    _statusLabel.Text = $"Command result: {JsonString(document.RootElement, "status")}";
                    break;
            }
        }
        catch (JsonException ex)
        {
            WriteProtocolEvent("error", new Dictionary<string, object?> { ["message"] = $"Malformed protocol JSON: {ex.Message}" });
        }
    }

    private void ApplyPreviewVertexUpdate(JsonElement root)
    {
        var revision = ProtocolEditRevision(root);
        if (!CanApplyEditRevision(revision, "preview_vertex_update", out var rejectionReason))
        {
            WriteEditRevisionAck("preview_vertex_update_ack", "rejected", revision, 0, rejectionReason);
            return;
        }
        if (!root.TryGetProperty("vertex_groups", out var groups) || groups.ValueKind != JsonValueKind.Array)
        {
            WriteEditRevisionAck("preview_vertex_update_ack", "rejected", revision, 0, "invalid_payload");
            return;
        }
        if (!TryParsePreviewVertexGroups(_document, groups, out var parsedGroups))
        {
            WriteEditRevisionAck("preview_vertex_update_ack", "rejected", revision, 0, "invalid_payload");
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
        MarkEditRevisionApplied(revision, "preview_vertex_update");
        WriteEditRevisionAck(
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
        if (!CanApplyEditRevision(revision, "preview_triangle_update", out var rejectionReason))
        {
            WriteEditRevisionAck("preview_triangle_update_ack", "rejected", revision, 0, rejectionReason);
            return;
        }
        if (!root.TryGetProperty("triangle_groups", out var groups) || groups.ValueKind != JsonValueKind.Array)
        {
            WriteEditRevisionAck("preview_triangle_update_ack", "rejected", revision, 0, "invalid_payload");
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
            WriteEditRevisionAck("preview_triangle_update_ack", "rejected", revision, 0, "invalid_payload");
            return;
        }
        if (changedCount > 0)
        {
            _externalTopologyDirty = true;
            _editedSubmeshes.UnionWith(affectedSubmeshes.Where(index => index < _document.Submeshes.Count));
            _viewport.RefreshTopologyGeometry(affectedSubmeshes, materialSources, replaceAll);
            _viewport.Invalidate();
            _statusLabel.Text = "Topology preview updated by MeshService; Python session remains authoritative.";
        }
        MarkEditRevisionApplied(revision, "preview_triangle_update");
        WriteEditRevisionAck("preview_triangle_update_ack", "applied", revision, changedCount, "");
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

    private bool CanApplyEditRevision(long revision, string packetKind, out string reason)
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
        if (revision == _lastAppliedEditRevision && _appliedPacketKindsForRevision.Contains(packetKind))
        {
            reason = "duplicate";
            return false;
        }
        return true;
    }

    private void MarkEditRevisionApplied(long revision, string packetKind)
    {
        if (revision <= 0)
        {
            return;
        }
        if (revision > _lastAppliedEditRevision)
        {
            _lastAppliedEditRevision = revision;
            _appliedPacketKindsForRevision.Clear();
        }
        _appliedPacketKindsForRevision.Add(packetKind);
    }

    private void WriteEditRevisionAck(
        string eventName,
        string status,
        long revision,
        int changedItems,
        string reason)
    {
        var payload = new Dictionary<string, object?>
        {
            ["status"] = status,
            ["edit_revision"] = revision,
            ["revision"] = revision,
            ["last_applied_revision"] = _lastAppliedEditRevision,
            ["changed_items"] = changedItems,
            ["capabilities"] = new[] { MeshEditRevisionCapability }
        };
        if (!string.IsNullOrWhiteSpace(reason))
        {
            payload["reason"] = reason;
        }
        WriteProtocolEvent(eventName, payload);
    }

    private void ApplySelectionUpdate(JsonElement root)
    {
        if (!root.TryGetProperty("selection", out var selection) || selection.ValueKind != JsonValueKind.Object)
        {
            return;
        }
        var vertices = JsonSelectionMap(selection, "vertices_by_submesh");
        var faces = JsonSelectionMap(selection, "faces_by_submesh");
        var edges = JsonEdgeSelectionMap(selection, "edges_by_submesh");
        if (edges.Count == 0)
        {
            edges = JsonEdgeDescriptorSelectionMap(selection, "edge_descriptors");
        }
        var sources = JsonIntSet(selection, "source_indices");
        _viewport.UpdateSelection(vertices, faces, edges, sources);
        _viewport.Invalidate();
    }
}
