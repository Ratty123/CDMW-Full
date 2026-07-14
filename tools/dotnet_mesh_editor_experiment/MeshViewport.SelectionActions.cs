using System.Drawing;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private void AddSelectedVertices(int submeshIndex, HashSet<int> result)
    {
        var submesh = _document.Submeshes[submeshIndex];
        if (!_selectedVertices.TryGetValue(submeshIndex, out var selectedVertices))
        {
            return;
        }
        foreach (var vertexIndex in selectedVertices)
        {
            if (vertexIndex >= 0 && vertexIndex < submesh.Vertices.Count)
            {
                result.Add(vertexIndex);
            }
        }
    }

    private void AddSelectedFaceVertices(int submeshIndex, HashSet<int> result)
    {
        var submesh = _document.Submeshes[submeshIndex];
        if (!_selectedFaces.TryGetValue(submeshIndex, out var selectedFaces))
        {
            return;
        }
        foreach (var faceIndex in selectedFaces)
        {
            if (faceIndex < 0 || faceIndex >= submesh.Faces.Count)
            {
                continue;
            }
            foreach (var corner in submesh.Faces[faceIndex].Corners)
            {
                if (corner.VertexIndex >= 0 && corner.VertexIndex < submesh.Vertices.Count)
                {
                    result.Add(corner.VertexIndex);
                }
            }
        }
    }

    private HashSet<int> SelectionVerticesForSubmesh(int submeshIndex)
    {
        var result = new HashSet<int>();
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return result;
        }
        AddSelectedVertices(submeshIndex, result);
        AddSelectedFaceVertices(submeshIndex, result);
        return result;
    }

    public int[] EditableVertexIndicesForSubmesh(int submeshIndex)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return Array.Empty<int>();
        }
        return SelectionVerticesForSubmesh(submeshIndex).OrderBy(index => index).ToArray();
    }

    public void SelectPartFromList(int submeshIndex)
    {
        SelectPartsFromList(new[] { submeshIndex });
    }

    public void SelectPartsFromList(IEnumerable<int> submeshIndices)
    {
        var requestedSources = submeshIndices
            .Where(index => index >= 0 && index < _document.Submeshes.Count)
            .Distinct()
            .OrderBy(index => index)
            .ToArray();
        EditorEventRequested?.Invoke("selection_request", new Dictionary<string, object?>
        {
            ["operation"] = "replace",
            ["target_mode"] = "source",
            ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
            ["local_selection"] = new Dictionary<string, object?>
            {
                ["vertices_by_submesh"] = new Dictionary<string, int[]>(),
                ["faces_by_submesh"] = new Dictionary<string, int[]>(),
                ["edges_by_submesh"] = new Dictionary<string, int[][]>(),
                ["source_indices"] = requestedSources,
                ["sources"] = requestedSources,
            },
        });
        StatusRequested?.Invoke("Part selection awaiting authoritative acceptance.");
    }

    private void SyncSelectedPartFocus()
    {
        _selectedSources.RemoveWhere(index => index < 0 || index >= _document.Submeshes.Count);
        SubmeshSelectedRequested?.Invoke(SelectedSubmeshIndex);
    }

    private void SelectVertexAt(Point point)
    {
        var hit = PickVertexAt(point);
        if (hit is null)
        {
            if (string.Equals(CurrentSelectionOperation(), "replace", StringComparison.OrdinalIgnoreCase))
            {
                _selectedVertices.Clear();
            }
            StatusRequested?.Invoke($"Vertex mode: selected={_selectedVertices.Values.Sum(vertices => vertices.Count)} hit=0 xray={(ShowXRay ? "on" : "off")}");
            NotifyLocalSelectionChanged();
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        ApplySelectionMapOperation(_selectedVertices, hit.Value.SubmeshIndex, hit.Value.ItemIndex, CurrentSelectionOperation());
        StatusRequested?.Invoke($"Vertex mode: selected={_selectedVertices.Values.Sum(vertices => vertices.Count)} hit=1 xray={(ShowXRay ? "on" : "off")}");
        NotifyLocalSelectionChanged();
        UpdateGpuViewport();
        Invalidate();
    }

    private void SelectFaceAt(Point point)
    {
        var hit = PickFaceAt(point);
        if (hit is null)
        {
            if (string.Equals(CurrentSelectionOperation(), "replace", StringComparison.OrdinalIgnoreCase))
            {
                _selectedFaces.Clear();
            }
            StatusRequested?.Invoke($"Face mode: selected={_selectedFaces.Values.Sum(faces => faces.Count)} hit=0 xray={(ShowXRay ? "on" : "off")}");
            NotifyLocalSelectionChanged();
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        ApplySelectionMapOperation(_selectedFaces, hit.Value.SubmeshIndex, hit.Value.ItemIndex, CurrentSelectionOperation());
        StatusRequested?.Invoke($"Face mode: selected={_selectedFaces.Values.Sum(faces => faces.Count)} hit=1 xray={(ShowXRay ? "on" : "off")}");
        NotifyLocalSelectionChanged();
        UpdateGpuViewport();
        Invalidate();
    }

    private void SelectPartAt(Point point)
    {
        var submeshIndex = PickPartAt(point);
        if (submeshIndex < 0)
        {
            if (string.Equals(CurrentSelectionOperation(), "replace", StringComparison.OrdinalIgnoreCase))
            {
                _selectedSources.Clear();
                SyncSelectedPartFocus();
            }
            StatusRequested?.Invoke($"Part mode: selected={_selectedSources.Count} hit=0 xray={(ShowXRay ? "on" : "off")}");
            NotifyLocalSelectionChanged();
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        ApplyPartSelectionOperation(new[] { submeshIndex }, CurrentSelectionOperation());
        StatusRequested?.Invoke($"Part mode: selected={_selectedSources.Count} hit=1 xray={(ShowXRay ? "on" : "off")}");
        NotifyLocalSelectionChanged();
        UpdateGpuViewport();
        Invalidate();
    }

    private int PickPartAt(Point point)
    {
        var face = PickFaceAt(point);
        return face?.SubmeshIndex ?? -1;
    }

    private void ApplyPartSelectionOperation(IEnumerable<int> sourceIndices, string operation)
    {
        var ids = sourceIndices.Where(index => index >= 0 && index < _document.Submeshes.Count).Distinct().ToArray();
        var normalized = (operation ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized == "replace")
        {
            _selectedSources.Clear();
        }
        foreach (var id in ids)
        {
            if (normalized == "subtract")
            {
                _selectedSources.Remove(id);
            }
            else if (normalized == "toggle")
            {
                if (!_selectedSources.Remove(id))
                {
                    _selectedSources.Add(id);
                }
            }
            else
            {
                _selectedSources.Add(id);
            }
        }
        SyncSelectedPartFocus();
    }

    private void ApplySelectionMapOperation(Dictionary<int, HashSet<int>> target, int submeshIndex, int itemIndex, string operation)
    {
        if (submeshIndex < 0 || itemIndex < 0)
        {
            return;
        }
        var normalized = (operation ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized == "replace")
        {
            target.Clear();
        }
        if (!target.TryGetValue(submeshIndex, out var set))
        {
            set = new HashSet<int>();
            target[submeshIndex] = set;
        }
        if (normalized == "subtract")
        {
            set.Remove(itemIndex);
        }
        else if (normalized == "toggle")
        {
            if (!set.Remove(itemIndex))
            {
                set.Add(itemIndex);
            }
        }
        else
        {
            set.Add(itemIndex);
        }
        if (set.Count == 0)
        {
            target.Remove(submeshIndex);
        }
    }

    private void ApplySelectionMapOperation(Dictionary<int, HashSet<int>> target, IEnumerable<(int SubmeshIndex, int ItemIndex)> hits, string operation)
    {
        var items = hits.Where(hit => hit.SubmeshIndex >= 0 && hit.ItemIndex >= 0).Distinct().ToArray();
        var normalized = (operation ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized == "replace")
        {
            target.Clear();
        }
        foreach (var item in items)
        {
            if (!target.TryGetValue(item.SubmeshIndex, out var set))
            {
                set = new HashSet<int>();
                target[item.SubmeshIndex] = set;
            }
            if (normalized == "subtract")
            {
                set.Remove(item.ItemIndex);
            }
            else if (normalized == "toggle")
            {
                if (!set.Remove(item.ItemIndex))
                {
                    set.Add(item.ItemIndex);
                }
            }
            else
            {
                set.Add(item.ItemIndex);
            }
            if (set.Count == 0)
            {
                target.Remove(item.SubmeshIndex);
            }
        }
    }
}
