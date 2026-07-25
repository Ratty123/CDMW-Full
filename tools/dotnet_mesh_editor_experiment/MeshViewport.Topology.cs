namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    public void RefreshBounds()
    {
        RefreshModelBounds();
        RebuildEdgeTopology();
        RebuildPartAdjacency();
        if (_d3d11Viewport is not null)
        {
            _d3d11Viewport.RefreshGeometry();
        }
        _gpuViewport?.RefreshGeometry();
        UpdateGpuViewport();
    }

    public void RefreshTopologyGeometry(
        IReadOnlyCollection<int> affectedSubmeshes,
        IReadOnlyDictionary<int, int> materialSources,
        bool replaceAll)
    {
        var viewCenter = _center;
        RefreshModelBounds();
        _center = viewCenter;
        RebuildEdgeTopology();
        RebuildPartAdjacency();
        _d3d11Viewport?.RefreshTopologyGeometry(affectedSubmeshes, materialSources, replaceAll);
        _gpuViewport?.RefreshGeometry();
        UpdateGpuViewport();
    }

    public void RefreshVertexGeometry(IReadOnlyDictionary<int, IReadOnlyCollection<int>> changedVertices)
    {
        var changed = new Dictionary<int, IReadOnlyCollection<int>>();
        foreach (var (submeshIndex, sourceVertices) in changedVertices)
        {
            if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var valid = sourceVertices
                .Where(index => index >= 0 && index < _document.Submeshes[submeshIndex].Vertices.Count)
                .Distinct()
                .ToArray();
            if (valid.Length > 0)
            {
                changed[submeshIndex] = valid;
            }
        }
        if (changed.Count == 0)
        {
            return;
        }
        ExpandModelBounds(changed);
        _d3d11Viewport?.RefreshVertexGeometry(changed);
        _gpuViewport?.RefreshGeometry();
        UpdateGpuViewport();
    }

    public void RefreshVertexGeometry(IReadOnlyDictionary<int, MeshVertexChannelChanges> changedChannels)
    {
        var changed = new Dictionary<int, MeshVertexChannelChanges>();
        foreach (var (submeshIndex, channels) in changedChannels)
        {
            if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            var positions = ValidChannelIndices(channels.Positions, submesh.Vertices.Count);
            var normals = ValidChannelIndices(channels.Normals, submesh.Normals.Count);
            var uvs = ValidChannelIndices(channels.Uvs, submesh.Uvs.Count);
            if (positions.Length > 0 || normals.Length > 0 || uvs.Length > 0)
            {
                changed[submeshIndex] = new MeshVertexChannelChanges(positions, normals, uvs);
            }
        }
        if (changed.Count == 0)
        {
            return;
        }
        var changedPositions = changed
            .Where(pair => pair.Value.Positions.Count > 0)
            .ToDictionary(pair => pair.Key, pair => pair.Value.Positions);
        if (changedPositions.Count > 0)
        {
            ExpandModelBounds(changedPositions);
        }
        _d3d11Viewport?.RefreshVertexGeometry(changed);
        _gpuViewport?.RefreshGeometry();
        UpdateGpuViewport();
    }

    private static int[] ValidChannelIndices(IEnumerable<int> indices, int count)
    {
        return indices.Where(index => index >= 0 && index < count).Distinct().ToArray();
    }

    public void RefreshVertexGeometry(IEnumerable<int> changedSubmeshes)
    {
        RefreshVertexGeometry(changedSubmeshes
            .Where(index => index >= 0 && index < _document.Submeshes.Count)
            .Distinct()
            .ToDictionary(
                index => index,
                index => (IReadOnlyCollection<int>)Enumerable.Range(0, _document.Submeshes[index].Vertices.Count).ToArray()));
    }

    private void ExpandModelBounds(IReadOnlyDictionary<int, IReadOnlyCollection<int>> changedVertices)
    {
        var viewCenter = _center;
        SparseBounds.Update(changedVertices);
        ApplySparseBounds();
        _center = viewCenter;
    }

    private void RefreshModelBounds()
    {
        SparseBounds.Rebase();
        ApplySparseBounds();
    }

    private NetViewportCamera CurrentCamera()
    {
        var viewport = ActivePaneBounds();
        var cameraBounds = CameraBoundsForContext(_activeCameraContextId);
        return NetViewportCamera.Create(
            BoundsCenter(cameraBounds),
            cameraBounds,
            _yaw,
            _pitch,
            _zoom,
            _panX,
            _panY,
            Math.Max(1, viewport.Width),
            Math.Max(1, viewport.Height));
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
        var editableSubmeshCount = Math.Min(_scene.EditableSubmeshCount, _document.Submeshes.Count);
        for (var index = 0; index < editableSubmeshCount; index++)
        {
            _partAdjacency[index] = new HashSet<int>();
        }
        var size = Math.Max(_bounds.Max.X - _bounds.Min.X, Math.Max(_bounds.Max.Y - _bounds.Min.Y, _bounds.Max.Z - _bounds.Min.Z));
        var tolerance = Math.Max(0.0001f, size * 0.001f);
        for (var left = 0; left < editableSubmeshCount; left++)
        {
            for (var right = left + 1; right < editableSubmeshCount; right++)
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
        return BoundsTouchOrOverlap(SubmeshBounds(left), SubmeshBounds(right), tolerance);
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
        if (_scene.HasAuthoritativeFrame)
        {
            _bounds = (
                new Vec3(
                    _scene.FramingBoundsMinimum.X,
                    _scene.FramingBoundsMinimum.Y,
                    _scene.FramingBoundsMinimum.Z),
                new Vec3(
                    _scene.FramingBoundsMaximum.X,
                    _scene.FramingBoundsMaximum.Y,
                    _scene.FramingBoundsMaximum.Z));
            _center = new Vec3(
                (_bounds.Min.X + _bounds.Max.X) * 0.5f,
                (_bounds.Min.Y + _bounds.Max.Y) * 0.5f,
                (_bounds.Min.Z + _bounds.Max.Z) * 0.5f);
        }
        else
        {
            RefreshModelBounds();
        }
        if (_edgeTopology.Generation == 0)
        {
            RebuildEdgeTopology();
            RebuildPartAdjacency();
        }
        var cameraBounds = SceneBoundsForContext(_activeCameraContextId);
        if (_presentationContexts.Count > 0)
        {
            ReframePresentationContext(_activeCameraContextId);
            cameraBounds = CameraBoundsForContext(_activeCameraContextId);
        }
        _zoom = FitZoomForBounds(cameraBounds);
        _panX = 0;
        _panY = 0;
        if (_presentationContexts.TryGetValue(_activeCameraContextId, out var context))
        {
            context.Zoom = _zoom;
            context.PanX = 0.0f;
            context.PanY = 0.0f;
        }
        // Reframing moves the camera exactly as an orbit or wheel zoom does, and
        // those report it. Without this the host keeps the pre-fit zoom and pan.
        NotifyViewStateChanged();
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

    public bool UpdateSelection(
        Dictionary<int, HashSet<int>> vertices,
        Dictionary<int, HashSet<int>> faces,
        Dictionary<int, HashSet<(int A, int B)>> edges,
        HashSet<int> sources,
        long requestId = 0,
        long revision = 0)
    {
        if (!CanAcceptAuthoritativeSelection(requestId, revision))
        {
            return false;
        }
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
        if (!AcceptAuthoritativeSelection(requestId, revision))
        {
            return false;
        }
        if (!HasNewerProvisionalSelection(requestId))
        {
            SyncSelectedPartFocus();
        }
        UpdateGpuViewport();
        return true;
    }
}
