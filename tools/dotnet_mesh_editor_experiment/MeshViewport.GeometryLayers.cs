namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private readonly HashSet<int> _geometryLayerSelectableSubmeshes = new();
    private bool _geometryLayerSelectionFilterActive;

    public void SetGeometryLayerState(
        IEnumerable<int> selectableSubmeshIndices,
        IEnumerable<int> hiddenSubmeshIndices)
    {
        InvalidatePaintProjectionCache("visible_editable_parts");
        _geometryLayerSelectableSubmeshes.Clear();
        _geometryLayerSelectableSubmeshes.UnionWith(selectableSubmeshIndices.Where(index => index >= 0));
        _geometryLayerSelectionFilterActive = true;
        _scene.SetPresentationHiddenSubmeshes(hiddenSubmeshIndices.Where(index => index >= 0));
        PruneSelectionToActiveGeometryLayer();
        ApplySceneState();
        QueuePaintProjectionPrewarm();
        NotifyViewStateChanged();
    }

    private bool IsSelectableGeometryLayerSubmesh(int submeshIndex) =>
        !_geometryLayerSelectionFilterActive || _geometryLayerSelectableSubmeshes.Contains(submeshIndex);

    private void PruneSelectionToActiveGeometryLayer()
    {
        static void PruneMap(Dictionary<int, HashSet<int>> values, HashSet<int> allowed)
        {
            foreach (var index in values.Keys.Where(index => !allowed.Contains(index)).ToArray())
            {
                values.Remove(index);
            }
        }

        PruneMap(_selectedVertices, _geometryLayerSelectableSubmeshes);
        PruneMap(_selectedFaces, _geometryLayerSelectableSubmeshes);
        PruneMap(_provisionalSelectedVertices, _geometryLayerSelectableSubmeshes);
        PruneMap(_provisionalSelectedFaces, _geometryLayerSelectableSubmeshes);
        _selectedSources.RemoveWhere(index => !_geometryLayerSelectableSubmeshes.Contains(index));
        _provisionalSelectedSources.RemoveWhere(index => !_geometryLayerSelectableSubmeshes.Contains(index));
        _selectedEdges.RemoveWhere(edgeId =>
            _edgeTopology.EdgeById(edgeId) is not { } edge
            || !_geometryLayerSelectableSubmeshes.Contains(edge.SubmeshIndex));
        _provisionalSelectedEdges.RemoveWhere(edgeId =>
            _edgeTopology.EdgeById(edgeId) is not { } edge
            || !_geometryLayerSelectableSubmeshes.Contains(edge.SubmeshIndex));
    }
}
