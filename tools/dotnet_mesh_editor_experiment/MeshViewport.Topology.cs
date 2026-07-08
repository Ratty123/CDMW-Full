namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    public void RefreshBounds()
    {
        _bounds = _document.Bounds();
        _center = new Vec3(
            (_bounds.Min.X + _bounds.Max.X) * 0.5f,
            (_bounds.Min.Y + _bounds.Max.Y) * 0.5f,
            (_bounds.Min.Z + _bounds.Max.Z) * 0.5f);
        RebuildEdgeTopology();
        RebuildPartAdjacency();
        if (_d3d11Viewport is not null)
        {
            _d3d11Viewport.RefreshGeometry();
        }
        _gpuViewport?.RefreshGeometry();
        UpdateGpuViewport();
    }

    private NetViewportCamera CurrentCamera()
    {
        return NetViewportCamera.Create(
            _center,
            _bounds,
            _yaw,
            _pitch,
            _zoom,
            _panX,
            _panY,
            Math.Max(1, Width),
            Math.Max(1, Height));
    }

    private void RebuildEdgeTopology()
    {
        var selectedKeys = _selectedEdges
            .Select(edgeId => _edgeTopology.EdgeById(edgeId)?.StableKey)
            .Where(key => !string.IsNullOrWhiteSpace(key))
            .ToArray();
        var hoverKey = _edgeTopology.EdgeById(_hoverEdgeId)?.StableKey ?? string.Empty;
        _edgeTopology = NetEdgeTopology.Build(_document, _edgeTopology.Generation + 1);
        _selectedEdges.Clear();
        foreach (var key in selectedKeys)
        {
            var edge = _edgeTopology.EdgeByStableKey(key!);
            if (edge is not null)
            {
                _selectedEdges.Add(edge.Id);
            }
        }
        _hoverEdgeId = _edgeTopology.EdgeByStableKey(hoverKey)?.Id ?? -1;
    }

    private void RebuildPartAdjacency()
    {
        _partAdjacency.Clear();
        for (var index = 0; index < _document.Submeshes.Count; index++)
        {
            _partAdjacency[index] = new HashSet<int>();
        }
        var size = Math.Max(_bounds.Max.X - _bounds.Min.X, Math.Max(_bounds.Max.Y - _bounds.Min.Y, _bounds.Max.Z - _bounds.Min.Z));
        var tolerance = Math.Max(0.0001f, size * 0.001f);
        for (var left = 0; left < _document.Submeshes.Count; left++)
        {
            for (var right = left + 1; right < _document.Submeshes.Count; right++)
            {
                if (SubmeshesAdjacent(left, right, tolerance))
                {
                    _partAdjacency[left].Add(right);
                    _partAdjacency[right].Add(left);
                }
            }
        }
    }

    private bool SubmeshesAdjacent(int leftIndex, int rightIndex, float tolerance)
    {
        var left = _document.Submeshes[leftIndex];
        var right = _document.Submeshes[rightIndex];
        if (left.Vertices.Count == 0 || right.Vertices.Count == 0)
        {
            return false;
        }
        var leftBounds = SubmeshBounds(left);
        var rightBounds = SubmeshBounds(right);
        if (!BoundsTouchOrOverlap(leftBounds, rightBounds, tolerance))
        {
            return false;
        }
        var toleranceSquared = tolerance * tolerance;
        foreach (var a in left.Vertices)
        {
            foreach (var b in right.Vertices)
            {
                var dx = a.X - b.X;
                var dy = a.Y - b.Y;
                var dz = a.Z - b.Z;
                if ((dx * dx) + (dy * dy) + (dz * dz) <= toleranceSquared)
                {
                    return true;
                }
            }
        }
        return true;
    }

    private static (Vec3 Min, Vec3 Max) SubmeshBounds(ObjSubmesh submesh)
    {
        if (submesh.Vertices.Count == 0)
        {
            return (new Vec3(0, 0, 0), new Vec3(0, 0, 0));
        }
        return (
            new Vec3(submesh.Vertices.Min(vertex => vertex.X), submesh.Vertices.Min(vertex => vertex.Y), submesh.Vertices.Min(vertex => vertex.Z)),
            new Vec3(submesh.Vertices.Max(vertex => vertex.X), submesh.Vertices.Max(vertex => vertex.Y), submesh.Vertices.Max(vertex => vertex.Z)));
    }

    private static bool BoundsTouchOrOverlap((Vec3 Min, Vec3 Max) left, (Vec3 Min, Vec3 Max) right, float tolerance)
    {
        return left.Min.X <= right.Max.X + tolerance && left.Max.X + tolerance >= right.Min.X
            && left.Min.Y <= right.Max.Y + tolerance && left.Max.Y + tolerance >= right.Min.Y
            && left.Min.Z <= right.Max.Z + tolerance && left.Max.Z + tolerance >= right.Min.Z;
    }

    public void FrameMesh()
    {
        RefreshBounds();
        var size = Math.Max(_bounds.Max.X - _bounds.Min.X, Math.Max(_bounds.Max.Y - _bounds.Min.Y, _bounds.Max.Z - _bounds.Min.Z));
        _zoom = size > 0.0001f ? 380.0f / size : 220.0f;
        _panX = 0;
        _panY = 0;
        UpdateGpuViewport();
        Invalidate();
    }

    private static void ReplaceSelectionMap(Dictionary<int, HashSet<int>> target, Dictionary<int, HashSet<int>> source)
    {
        target.Clear();
        foreach (var pair in source)
        {
            target[pair.Key] = new HashSet<int>(pair.Value);
        }
    }

    public void UpdateSelection(
        Dictionary<int, HashSet<int>> vertices,
        Dictionary<int, HashSet<int>> faces,
        Dictionary<int, HashSet<(int A, int B)>> edges,
        HashSet<int> sources)
    {
        ReplaceSelectionMap(_selectedVertices, vertices);
        ReplaceSelectionMap(_selectedFaces, faces);
        _selectedEdges.Clear();
        foreach (var pair in edges)
        {
            foreach (var edgePair in pair.Value)
            {
                var edge = _edgeTopology.EdgeByVertices(pair.Key, edgePair.A, edgePair.B);
                if (edge is not null)
                {
                    _selectedEdges.Add(edge.Id);
                }
            }
        }
        _selectedSources.Clear();
        foreach (var source in sources)
        {
            _selectedSources.Add(source);
        }
        UpdateGpuViewport();
    }
}
