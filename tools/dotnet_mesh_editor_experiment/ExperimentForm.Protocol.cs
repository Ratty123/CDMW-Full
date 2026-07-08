using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
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
                string? line;
                while ((line = Console.In.ReadLine()) is not null)
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
                case "session_state":
                    ApplySelectionUpdate(document.RootElement);
                    _statusLabel.Text = "Live MeshService bridge connected.";
                    break;
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
        if (!root.TryGetProperty("vertex_groups", out var groups) || groups.ValueKind != JsonValueKind.Array)
        {
            return;
        }
        var changed = false;
        foreach (var group in groups.EnumerateArray())
        {
            if (group.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var submeshIndex = JsonInt(group, "source_submesh_index", JsonInt(group, "index", -1));
            if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            var positions = JsonDoubleValues(group, "positions");
            if (positions.Count == 0 && group.TryGetProperty("positions_binary", out var positionsBinary))
            {
                positions = ReadDoubleBinary(positionsBinary);
            }
            if (positions.Count < 3)
            {
                continue;
            }
            var indices = JsonIntValues(group, "source_vertex_indices");
            if (indices.Count == 0 && group.TryGetProperty("source_vertex_indices_binary", out var indicesBinary))
            {
                indices = ReadIntBinary(indicesBinary);
            }
            if (indices.Count == 0)
            {
                var start = JsonInt(group, "source_vertex_start", -1);
                var count = JsonInt(group, "source_vertex_count", 0);
                if (start >= 0 && count > 0)
                {
                    indices = Enumerable.Range(start, count).ToList();
                }
            }
            if (indices.Count == 0 && positions.Count / 3 == submesh.Vertices.Count)
            {
                indices = Enumerable.Range(0, submesh.Vertices.Count).ToList();
            }
            var updateCount = Math.Min(indices.Count, positions.Count / 3);
            for (var i = 0; i < updateCount; i++)
            {
                var vertexIndex = indices[i];
                if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
                {
                    continue;
                }
                var p = i * 3;
                submesh.Vertices[vertexIndex] = new Vec3((float)positions[p], (float)positions[p + 1], (float)positions[p + 2]);
                changed = true;
            }
            if (updateCount > 0)
            {
                _editedSubmeshes.Add(submeshIndex);
            }
        }
        if (changed)
        {
            _viewport.RefreshBounds();
            _viewport.Invalidate();
            _statusLabel.Text = "Vertex update applied from MeshService.";
        }
    }

    private void ApplyPreviewTriangleUpdate(JsonElement root)
    {
        if (!root.TryGetProperty("triangle_groups", out var groups) || groups.ValueKind != JsonValueKind.Array)
        {
            return;
        }
        var changed = false;
        foreach (var group in groups.EnumerateArray())
        {
            if (group.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var submeshIndex = JsonInt(group, "source_submesh_index", JsonInt(group, "index", -1));
            if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var positions = JsonDoubleValues(group, "positions");
            if (positions.Count == 0 && group.TryGetProperty("positions_binary", out var positionsBinary))
            {
                positions = ReadDoubleBinary(positionsBinary);
            }
            var indices = JsonIntValues(group, "indices");
            if (indices.Count == 0 && group.TryGetProperty("indices_binary", out var indicesBinary))
            {
                indices = ReadIntBinary(indicesBinary);
            }
            if (positions.Count == 0 || indices.Count == 0)
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            submesh.Vertices.Clear();
            for (var i = 0; i + 2 < positions.Count; i += 3)
            {
                submesh.Vertices.Add(new Vec3((float)positions[i], (float)positions[i + 1], (float)positions[i + 2]));
            }
            var normals = JsonDoubleValues(group, "normals");
            if (normals.Count == 0 && group.TryGetProperty("normals_binary", out var normalsBinary))
            {
                normals = ReadDoubleBinary(normalsBinary);
            }
            submesh.Normals.Clear();
            for (var i = 0; i + 2 < normals.Count; i += 3)
            {
                submesh.Normals.Add(new Vec3((float)normals[i], (float)normals[i + 1], (float)normals[i + 2]));
            }
            var uvs = JsonDoubleValues(group, "uvs");
            if (uvs.Count == 0 && group.TryGetProperty("uvs_binary", out var uvsBinary))
            {
                uvs = ReadDoubleBinary(uvsBinary);
            }
            submesh.Uvs.Clear();
            for (var i = 0; i + 1 < uvs.Count; i += 2)
            {
                submesh.Uvs.Add(new Vec2((float)uvs[i], (float)uvs[i + 1]));
            }
            submesh.Faces.Clear();
            for (var i = 0; i + 2 < indices.Count; i += 3)
            {
                submesh.Faces.Add(new ObjFace(new[]
                {
                    new ObjCorner(indices[i], indices[i], indices[i]),
                    new ObjCorner(indices[i + 1], indices[i + 1], indices[i + 1]),
                    new ObjCorner(indices[i + 2], indices[i + 2], indices[i + 2])
                }));
            }
            changed = true;
        }
        if (changed)
        {
            _externalTopologyDirty = true;
            _viewport.RefreshBounds();
            _viewport.Invalidate();
            _statusLabel.Text = "Topology preview updated by MeshService; Python session remains authoritative.";
        }
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
