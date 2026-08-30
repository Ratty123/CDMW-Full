namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private void PrepareResidentNativeGeometryPreview()
    {
        _residentNativePreviewPositions.Clear();
        var scope = VisibleEditableSubmeshIndices();
        foreach (var submeshIndex in scope)
        {
            _residentNativePreviewPositions[submeshIndex] =
                new List<Vec3>(_document.Submeshes[submeshIndex].Vertices);
        }
        _d3d11Viewport?.BeginProvisionalVertexGeometry(scope);
    }

    private void PrepareResidentNativeSelectionPreview()
    {
        ReplaceSelectionMap(_provisionalSelectedVertices, _selectedVertices);
        ReplaceSelectionMap(_provisionalSelectedFaces, _selectedFaces);
        _provisionalSelectedEdges.Clear();
        _provisionalSelectedEdges.UnionWith(_selectedEdges);
        _provisionalSelectedSources.Clear();
        _provisionalSelectedSources.UnionWith(_selectedSources);
        _provisionalPartSelectionActive = false;
    }

    private void ApplyResidentNativeResult(NativeMeshInteractionResult result)
    {
        ApplyResidentNativeDirtyRanges(result.DirtyRanges);
        ApplyResidentNativeSelectionChanges(result.SelectionChanges);
        UpdateGpuViewport();
        Invalidate();
    }

    private void ApplyResidentNativeDirtyRanges(IReadOnlyList<NativeMeshDirtyRange> ranges)
    {
        foreach (var range in ranges)
        {
            if (range.SubmeshIndex < 0
                || range.SubmeshIndex >= _document.Submeshes.Count
                || range.VertexCount == 0)
            {
                continue;
            }
            var read = RequireResidentNativeSession().ReadVertices(
                range.SubmeshIndex,
                range.FirstVertex,
                range.VertexCount);
            RequireResidentNativeSuccess(read.Result, "provisional vertex read");
            if (!_residentNativePreviewPositions.TryGetValue(range.SubmeshIndex, out var positions))
            {
                positions = new List<Vec3>(_document.Submeshes[range.SubmeshIndex].Vertices);
                _residentNativePreviewPositions[range.SubmeshIndex] = positions;
            }
            var changed = new int[read.WrittenVertexCount];
            for (var offset = 0; offset < read.WrittenVertexCount; offset++)
            {
                var vertexIndex = checked((int)(range.FirstVertex + offset));
                if (vertexIndex < 0 || vertexIndex >= positions.Count)
                {
                    throw new InvalidOperationException("Native dirty vertex range exceeds the resident mesh.");
                }
                var positionOffset = checked((int)offset * 3);
                positions[vertexIndex] = new Vec3(
                    checked((float)read.PositionsXyz[positionOffset]),
                    checked((float)read.PositionsXyz[positionOffset + 1]),
                    checked((float)read.PositionsXyz[positionOffset + 2]));
                changed[offset] = vertexIndex;
            }
            _d3d11Viewport?.UpdateProvisionalVertexPositions(
                range.SubmeshIndex,
                positions,
                changed,
                changed.Length,
                stableChangedSet: false);
        }
    }

    private void ApplyResidentNativeSelectionChanges(
        IReadOnlyList<NativeMeshSelectionChange> changes)
    {
        foreach (var change in changes)
        {
            var first = checked((int)change.FirstElement);
            if (change.Target == NativeMeshSelectionTarget.Vertex)
            {
                ChangeResidentSelectionMap(
                    _provisionalSelectedVertices,
                    change.SubmeshIndex,
                    first,
                    change.Selected);
            }
            else if (change.Target == NativeMeshSelectionTarget.Face)
            {
                ChangeResidentSelectionMap(
                    _provisionalSelectedFaces,
                    change.SubmeshIndex,
                    first,
                    change.Selected);
            }
            else
            {
                var edge = _edgeTopology.EdgeByVertices(
                    change.SubmeshIndex,
                    first,
                    checked((int)change.SecondElement));
                if (edge is not null)
                {
                    if (change.Selected) _provisionalSelectedEdges.Add(edge.Id);
                    else _provisionalSelectedEdges.Remove(edge.Id);
                }
            }
        }
    }

    private static void ChangeResidentSelectionMap(
        Dictionary<int, HashSet<int>> values,
        int submeshIndex,
        int elementIndex,
        bool selected)
    {
        if (!values.TryGetValue(submeshIndex, out var elements))
        {
            elements = new HashSet<int>();
            values[submeshIndex] = elements;
        }
        if (selected) elements.Add(elementIndex);
        else elements.Remove(elementIndex);
        if (elements.Count == 0) values.Remove(submeshIndex);
    }

    private void ClearResidentNativePreview()
    {
        _residentNativePreviewPositions.Clear();
        _d3d11Viewport?.ClearProvisionalGeometry();
        ClearProvisionalSelectionEcho();
        UpdateGpuViewport();
        Invalidate();
    }
}
