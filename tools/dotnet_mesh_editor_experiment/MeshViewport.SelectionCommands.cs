namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private static string NormalizeSelectionTarget(string targetMode)
    {
        var normalized = (targetMode ?? string.Empty).Trim().ToLowerInvariant();
        return normalized == "source" ? "part" : normalized;
    }

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
        }
    }

    private void SelectAllForTarget(string targetMode)
    {
        ClearSelectionForTarget(targetMode);
        if (targetMode == "vertex")
        {
            for (var index = 0; index < _document.Submeshes.Count; index++)
            {
                _selectedVertices[index] = Enumerable.Range(0, _document.Submeshes[index].Vertices.Count).ToHashSet();
            }
        }
        else if (targetMode == "face")
        {
            for (var index = 0; index < _document.Submeshes.Count; index++)
            {
                _selectedFaces[index] = Enumerable.Range(0, _document.Submeshes[index].Faces.Count).ToHashSet();
            }
        }
        else if (targetMode == "edge")
        {
            foreach (var edge in _edgeTopology.Edges)
            {
                _selectedEdges.Add(edge.Id);
            }
        }
        else if (targetMode == "part")
        {
            for (var index = 0; index < _document.Submeshes.Count; index++)
            {
                _selectedSources.Add(index);
            }
        }
    }

    private void InvertSelectionForTarget(string targetMode)
    {
        if (targetMode == "vertex")
        {
            for (var index = 0; index < _document.Submeshes.Count; index++)
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
            for (var index = 0; index < _document.Submeshes.Count; index++)
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
                if (!selected.Contains(edge.Id))
                {
                    _selectedEdges.Add(edge.Id);
                }
            }
        }
        else if (targetMode == "part")
        {
            var selected = _selectedSources.ToHashSet();
            _selectedSources.Clear();
            for (var index = 0; index < _document.Submeshes.Count; index++)
            {
                if (!selected.Contains(index))
                {
                    _selectedSources.Add(index);
                }
            }
        }
    }

    private void GrowSelectionForTarget(string targetMode)
    {
        if (targetMode == "vertex")
        {
            var grown = CopySelectionMap(_selectedVertices);
            foreach (var edge in _edgeTopology.Edges)
            {
                if (!_selectedVertices.TryGetValue(edge.SubmeshIndex, out var selected))
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
                if (!_selectedFaces.TryGetValue(edge.SubmeshIndex, out var selected) || !edge.AdjacentFaces.Any(selected.Contains))
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
            var selected = _selectedEdges.ToHashSet();
            foreach (var edge in _edgeTopology.Edges)
            {
                if (selected.Contains(edge.Id))
                {
                    continue;
                }
                if (_edgeTopology.Edges.Any(other => selected.Contains(other.Id) && other.SubmeshIndex == edge.SubmeshIndex && (other.VertexA == edge.VertexA || other.VertexA == edge.VertexB || other.VertexB == edge.VertexA || other.VertexB == edge.VertexB)))
                {
                    _selectedEdges.Add(edge.Id);
                }
            }
        }
        else if (targetMode == "part")
        {
            var selected = _selectedSources.Count > 0 ? _selectedSources.ToHashSet() : new HashSet<int> { SelectedSubmeshIndex };
            foreach (var part in selected)
            {
                if (part >= 0 && part < _document.Submeshes.Count)
                {
                    _selectedSources.Add(part);
                    foreach (var neighbor in PartNeighbors(part))
                    {
                        _selectedSources.Add(neighbor);
                    }
                }
            }
        }
    }

    private void ShrinkSelectionForTarget(string targetMode)
    {
        if (targetMode == "vertex")
        {
            var shrunk = new Dictionary<int, HashSet<int>>();
            foreach (var pair in _selectedVertices)
            {
                var keep = new HashSet<int>();
                foreach (var vertex in pair.Value)
                {
                    var neighbors = VertexNeighbors(pair.Key, vertex).ToArray();
                    if (neighbors.Length > 0 && neighbors.All(pair.Value.Contains))
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
            var shrunk = new Dictionary<int, HashSet<int>>();
            foreach (var pair in _selectedFaces)
            {
                var keep = new HashSet<int>();
                foreach (var face in pair.Value)
                {
                    var neighbors = FaceNeighbors(pair.Key, face).ToArray();
                    if (neighbors.Length > 0 && neighbors.All(pair.Value.Contains))
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
            var keep = new HashSet<int>();
            foreach (var edgeId in _selectedEdges)
            {
                var neighbors = EdgeNeighbors(edgeId).ToArray();
                if (neighbors.Length > 0 && neighbors.All(_selectedEdges.Contains))
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
        }
    }

    private IEnumerable<int> VertexNeighbors(int submeshIndex, int vertexIndex)
    {
        foreach (var edge in _edgeTopology.Edges)
        {
            if (edge.SubmeshIndex != submeshIndex)
            {
                continue;
            }
            if (edge.VertexA == vertexIndex)
            {
                yield return edge.VertexB;
            }
            else if (edge.VertexB == vertexIndex)
            {
                yield return edge.VertexA;
            }
        }
    }

    private IEnumerable<int> FaceNeighbors(int submeshIndex, int faceIndex)
    {
        foreach (var edge in _edgeTopology.Edges)
        {
            if (edge.SubmeshIndex == submeshIndex && edge.AdjacentFaces.Contains(faceIndex))
            {
                foreach (var neighbor in edge.AdjacentFaces)
                {
                    if (neighbor != faceIndex)
                    {
                        yield return neighbor;
                    }
                }
            }
        }
    }

    private IEnumerable<int> EdgeNeighbors(int edgeId)
    {
        var edge = _edgeTopology.EdgeById(edgeId);
        if (edge is null)
        {
            yield break;
        }
        foreach (var other in _edgeTopology.Edges)
        {
            if (other.Id != edge.Id && other.SubmeshIndex == edge.SubmeshIndex && (other.VertexA == edge.VertexA || other.VertexA == edge.VertexB || other.VertexB == edge.VertexA || other.VertexB == edge.VertexB))
            {
                yield return other.Id;
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
