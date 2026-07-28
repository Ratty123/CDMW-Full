namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private static string NormalizeSelectionTarget(string targetMode)
    {
        var normalized = (targetMode ?? string.Empty).Trim().ToLowerInvariant();
        return normalized == "source" ? "part" : normalized;
    }

    /// <summary>
    /// How many leading submeshes these commands are allowed to touch. The
    /// document holds the editable submeshes first and the reference copies
    /// after them, and only the editable ones can be edited: every payload the
    /// viewport sends the host is clamped the same way. Selecting into the
    /// reference range would offer the reader geometry no edit can reach.
    /// </summary>
    private int EditableSelectionLimit() =>
        Math.Clamp(_scene.EditableSubmeshCount, 0, _document.Submeshes.Count);

    private int SelectionCountForTarget(string targetMode)
    {
        return NormalizeSelectionTarget(targetMode) switch
        {
            "vertex" => _selectedVertices.Values.Sum(values => values.Count),
            "face" => _selectedFaces.Values.Sum(values => values.Count),
            "edge" => _selectedEdges.Count,
            "part" => _selectedSources.Count,
            _ => 0,
        };
    }

    private void ClearSelectionForTarget(string targetMode)
    {
        if (targetMode == "vertex")
        {
            _selectedVertices.Clear();
        }
        else if (targetMode == "face")
        {
            _selectedFaces.Clear();
        }
        else if (targetMode == "edge")
        {
            _selectedEdges.Clear();
            _hoverEdgeId = -1;
        }
        else if (targetMode == "part")
        {
            _selectedSources.Clear();
            SyncSelectedPartFocus();
        }
    }

    private void SelectAllForTarget(string targetMode)
    {
        ClearSelectionForTarget(targetMode);
        var editableCount = EditableSelectionLimit();
        if (targetMode == "vertex")
        {
            for (var index = 0; index < editableCount; index++)
            {
                _selectedVertices[index] = Enumerable.Range(0, _document.Submeshes[index].Vertices.Count).ToHashSet();
            }
        }
        else if (targetMode == "face")
        {
            for (var index = 0; index < editableCount; index++)
            {
                _selectedFaces[index] = Enumerable.Range(0, _document.Submeshes[index].Faces.Count).ToHashSet();
            }
        }
        else if (targetMode == "edge")
        {
            foreach (var edge in _edgeTopology.Edges)
            {
                if (edge.SubmeshIndex < editableCount)
                {
                    _selectedEdges.Add(edge.Id);
                }
            }
        }
        else if (targetMode == "part")
        {
            for (var index = 0; index < editableCount; index++)
            {
                _selectedSources.Add(index);
            }
            SyncSelectedPartFocus();
        }
    }

    private void InvertSelectionForTarget(string targetMode)
    {
        var editableCount = EditableSelectionLimit();
        if (targetMode == "vertex")
        {
            for (var index = 0; index < editableCount; index++)
            {
                var selected = _selectedVertices.TryGetValue(index, out var current) ? current : new HashSet<int>();
                var inverted = Enumerable.Range(0, _document.Submeshes[index].Vertices.Count).Where(item => !selected.Contains(item)).ToHashSet();
                if (inverted.Count > 0)
                {
                    _selectedVertices[index] = inverted;
                }
                else
                {
                    _selectedVertices.Remove(index);
                }
            }
        }
        else if (targetMode == "face")
        {
            for (var index = 0; index < editableCount; index++)
            {
                var selected = _selectedFaces.TryGetValue(index, out var current) ? current : new HashSet<int>();
                var inverted = Enumerable.Range(0, _document.Submeshes[index].Faces.Count).Where(item => !selected.Contains(item)).ToHashSet();
                if (inverted.Count > 0)
                {
                    _selectedFaces[index] = inverted;
                }
                else
                {
                    _selectedFaces.Remove(index);
                }
            }
        }
        else if (targetMode == "edge")
        {
            var selected = _selectedEdges.ToHashSet();
            _selectedEdges.Clear();
            foreach (var edge in _edgeTopology.Edges)
            {
                if (edge.SubmeshIndex < editableCount && !selected.Contains(edge.Id))
                {
                    _selectedEdges.Add(edge.Id);
                }
            }
        }
        else if (targetMode == "part")
        {
            var selected = _selectedSources.ToHashSet();
            _selectedSources.Clear();
            for (var index = 0; index < editableCount; index++)
            {
                if (!selected.Contains(index))
                {
                    _selectedSources.Add(index);
                }
            }
            SyncSelectedPartFocus();
        }
    }

    private void GrowSelectionForTarget(string targetMode)
    {
        var editableCount = EditableSelectionLimit();
        if (targetMode == "vertex")
        {
            var grown = CopySelectionMap(_selectedVertices);
            foreach (var edge in _edgeTopology.Edges)
            {
                if (edge.SubmeshIndex >= editableCount
                    || !_selectedVertices.TryGetValue(edge.SubmeshIndex, out var selected))
                {
                    continue;
                }
                if (!grown.TryGetValue(edge.SubmeshIndex, out var target))
                {
                    target = new HashSet<int>();
                    grown[edge.SubmeshIndex] = target;
                }
                if (selected.Contains(edge.VertexA)) target.Add(edge.VertexB);
                if (selected.Contains(edge.VertexB)) target.Add(edge.VertexA);
            }
            ReplaceSelectionMap(_selectedVertices, grown);
        }
        else if (targetMode == "face")
        {
            var grown = CopySelectionMap(_selectedFaces);
            foreach (var edge in _edgeTopology.Edges)
            {
                if (edge.SubmeshIndex >= editableCount
                    || !_selectedFaces.TryGetValue(edge.SubmeshIndex, out var selected)
                    || !edge.AdjacentFaces.Any(selected.Contains))
                {
                    continue;
                }
                if (!grown.TryGetValue(edge.SubmeshIndex, out var target))
                {
                    target = new HashSet<int>();
                    grown[edge.SubmeshIndex] = target;
                }
                foreach (var face in edge.AdjacentFaces)
                {
                    target.Add(face);
                }
            }
            ReplaceSelectionMap(_selectedFaces, grown);
        }
        else if (targetMode == "edge")
        {
            // One pass to index the edges by endpoint, then one pass over the
            // selection. Scanning the whole edge list per candidate edge instead
            // is quadratic, and a shipped mesh carries enough edges for that to
            // stall the UI thread outright.
            var edgesByEndpoint = BuildEdgesByEndpointIndex();
            var selected = _selectedEdges.ToHashSet();
            foreach (var edgeId in selected)
            {
                foreach (var neighbor in EdgeNeighbors(edgeId, edgesByEndpoint))
                {
                    var edge = _edgeTopology.EdgeById(neighbor);
                    if (edge is not null && edge.SubmeshIndex < editableCount)
                    {
                        _selectedEdges.Add(neighbor);
                    }
                }
            }
        }
        else if (targetMode == "part")
        {
            var selected = _selectedSources.ToHashSet();
            foreach (var part in selected)
            {
                if (part >= 0 && part < editableCount)
                {
                    _selectedSources.Add(part);
                    foreach (var neighbor in PartNeighbors(part))
                    {
                        if (neighbor < editableCount)
                        {
                            _selectedSources.Add(neighbor);
                        }
                    }
                }
            }
            SyncSelectedPartFocus();
        }
    }

    private void ShrinkSelectionForTarget(string targetMode)
    {
        if (targetMode == "vertex")
        {
            var neighborsByVertex = BuildVertexNeighborIndex();
            var shrunk = new Dictionary<int, HashSet<int>>();
            foreach (var pair in _selectedVertices)
            {
                var keep = new HashSet<int>();
                foreach (var vertex in pair.Value)
                {
                    var neighbors = VertexNeighbors(pair.Key, vertex, neighborsByVertex);
                    if (neighbors.Count > 0 && neighbors.All(pair.Value.Contains))
                    {
                        keep.Add(vertex);
                    }
                }
                if (keep.Count > 0)
                {
                    shrunk[pair.Key] = keep;
                }
            }
            ReplaceSelectionMap(_selectedVertices, shrunk);
        }
        else if (targetMode == "face")
        {
            var neighborsByFace = BuildFaceNeighborIndex();
            var shrunk = new Dictionary<int, HashSet<int>>();
            foreach (var pair in _selectedFaces)
            {
                var keep = new HashSet<int>();
                foreach (var face in pair.Value)
                {
                    var neighbors = FaceNeighbors(pair.Key, face, neighborsByFace);
                    if (neighbors.Count > 0 && neighbors.All(pair.Value.Contains))
                    {
                        keep.Add(face);
                    }
                }
                if (keep.Count > 0)
                {
                    shrunk[pair.Key] = keep;
                }
            }
            ReplaceSelectionMap(_selectedFaces, shrunk);
        }
        else if (targetMode == "edge")
        {
            var edgesByEndpoint = BuildEdgesByEndpointIndex();
            var keep = new HashSet<int>();
            foreach (var edgeId in _selectedEdges)
            {
                var neighbors = EdgeNeighbors(edgeId, edgesByEndpoint);
                if (neighbors.Count > 0 && neighbors.All(_selectedEdges.Contains))
                {
                    keep.Add(edgeId);
                }
            }
            _selectedEdges.Clear();
            foreach (var edgeId in keep)
            {
                _selectedEdges.Add(edgeId);
            }
        }
        else if (targetMode == "part")
        {
            var keep = new HashSet<int>();
            foreach (var part in _selectedSources)
            {
                var neighbors = PartNeighbors(part).ToArray();
                if (neighbors.Length > 0 && neighbors.All(_selectedSources.Contains))
                {
                    keep.Add(part);
                }
            }
            _selectedSources.Clear();
            foreach (var part in keep)
            {
                _selectedSources.Add(part);
            }
            SyncSelectedPartFocus();
        }
    }

    /// <summary>
    /// Vertex adjacency for every submesh, built in a single pass over the edge
    /// list so a whole grow or shrink costs one walk rather than one per
    /// selected element.
    /// </summary>
    private Dictionary<(int SubmeshIndex, int VertexIndex), HashSet<int>> BuildVertexNeighborIndex()
    {
        var index = new Dictionary<(int SubmeshIndex, int VertexIndex), HashSet<int>>();
        foreach (var edge in _edgeTopology.Edges)
        {
            Link(edge.SubmeshIndex, edge.VertexA, edge.VertexB);
            Link(edge.SubmeshIndex, edge.VertexB, edge.VertexA);
        }
        return index;

        void Link(int submeshIndex, int from, int to)
        {
            var key = (submeshIndex, from);
            if (!index.TryGetValue(key, out var neighbors))
            {
                neighbors = new HashSet<int>();
                index[key] = neighbors;
            }
            neighbors.Add(to);
        }
    }

    private Dictionary<(int SubmeshIndex, int FaceIndex), HashSet<int>> BuildFaceNeighborIndex()
    {
        var index = new Dictionary<(int SubmeshIndex, int FaceIndex), HashSet<int>>();
        foreach (var edge in _edgeTopology.Edges)
        {
            foreach (var face in edge.AdjacentFaces)
            {
                var key = (edge.SubmeshIndex, face);
                if (!index.TryGetValue(key, out var neighbors))
                {
                    neighbors = new HashSet<int>();
                    index[key] = neighbors;
                }
                foreach (var other in edge.AdjacentFaces)
                {
                    if (other != face)
                    {
                        neighbors.Add(other);
                    }
                }
            }
        }
        return index;
    }

    private Dictionary<(int SubmeshIndex, int VertexIndex), List<int>> BuildEdgesByEndpointIndex()
    {
        var index = new Dictionary<(int SubmeshIndex, int VertexIndex), List<int>>();
        foreach (var edge in _edgeTopology.Edges)
        {
            Link(edge.SubmeshIndex, edge.VertexA, edge.Id);
            Link(edge.SubmeshIndex, edge.VertexB, edge.Id);
        }
        return index;

        void Link(int submeshIndex, int vertexIndex, int edgeId)
        {
            var key = (submeshIndex, vertexIndex);
            if (!index.TryGetValue(key, out var edgeIds))
            {
                edgeIds = new List<int>();
                index[key] = edgeIds;
            }
            edgeIds.Add(edgeId);
        }
    }

    private static IReadOnlyCollection<int> VertexNeighbors(
        int submeshIndex,
        int vertexIndex,
        Dictionary<(int SubmeshIndex, int VertexIndex), HashSet<int>> index)
    {
        return index.TryGetValue((submeshIndex, vertexIndex), out var neighbors)
            ? neighbors
            : Array.Empty<int>();
    }

    private static IReadOnlyCollection<int> FaceNeighbors(
        int submeshIndex,
        int faceIndex,
        Dictionary<(int SubmeshIndex, int FaceIndex), HashSet<int>> index)
    {
        return index.TryGetValue((submeshIndex, faceIndex), out var neighbors)
            ? neighbors
            : Array.Empty<int>();
    }

    private IReadOnlyCollection<int> EdgeNeighbors(
        int edgeId,
        Dictionary<(int SubmeshIndex, int VertexIndex), List<int>> edgesByEndpoint)
    {
        var edge = _edgeTopology.EdgeById(edgeId);
        if (edge is null)
        {
            return Array.Empty<int>();
        }
        var neighbors = new HashSet<int>();
        Collect(edge.SubmeshIndex, edge.VertexA);
        Collect(edge.SubmeshIndex, edge.VertexB);
        neighbors.Remove(edge.Id);
        return neighbors;

        void Collect(int submeshIndex, int vertexIndex)
        {
            if (edgesByEndpoint.TryGetValue((submeshIndex, vertexIndex), out var edgeIds))
            {
                foreach (var candidate in edgeIds)
                {
                    neighbors.Add(candidate);
                }
            }
        }
    }

    private IEnumerable<int> PartNeighbors(int submeshIndex)
    {
        return _partAdjacency.TryGetValue(submeshIndex, out var neighbors)
            ? neighbors
            : Array.Empty<int>();
    }

    private static Dictionary<int, HashSet<int>> CopySelectionMap(Dictionary<int, HashSet<int>> source)
    {
        return source.ToDictionary(pair => pair.Key, pair => new HashSet<int>(pair.Value));
    }
}
