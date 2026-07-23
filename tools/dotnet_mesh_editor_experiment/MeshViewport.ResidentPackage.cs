namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    public long ResidentSceneLoadCount => _d3d11Viewport?.ResidentSceneLoadCount ?? 0;

    public void ReplaceResidentPackage(
        ObjDocument document,
        NetMaterialSet materials,
        NetTextureSet textureSet,
        NetSceneState scene)
    {
        ArgumentNullException.ThrowIfNull(document);
        ArgumentNullException.ThrowIfNull(materials);
        ArgumentNullException.ThrowIfNull(textureSet);
        ArgumentNullException.ThrowIfNull(scene);
        if (InvokeRequired)
        {
            throw new InvalidOperationException("Resident package replacement must run on the viewport owner thread.");
        }
        var renderer = _d3d11Viewport
            ?? throw new InvalidOperationException("The production D3D11 renderer is not available for resident package replacement.");

        renderer.ReplaceResidentScene(document, materials, textureSet, scene);
        _document = document;
        _materials = materials;
        _textureSet = textureSet;
        _scene = scene;
        _selectedVertices.Clear();
        _selectedFaces.Clear();
        _selectedEdges.Clear();
        _selectedSources.Clear();
        _acknowledgedSelection = new SelectionAuthoritySnapshot(
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<int>>(),
            new HashSet<int>(),
            new HashSet<int>(),
            0,
            0);
        _provisionalSelectionRequestId = 0;
        _provisionalSelectionBaseRevision = 0;
        _hoverEdgeId = -1;
        _edgeTopology = NetEdgeTopology.Empty;
        _partAdjacency.Clear();
        _presentationContexts.Clear();
        _activeCameraContextId = "editable";
        _presentationGridVisible = scene.GridVisible;
        _presentationGizmoVisible = scene.GizmoVisible;
        _presentationStateFingerprint = string.Empty;
        FrameMesh();
        InitializePresentationContexts();
        var hasTextureResources = materials.TextureLoadResources().Any()
            || textureSet.DecodedCount > 0
            || textureSet.NativeDdsResourceCount > 0;
        _ = TrySetSynchronizedDisplayMode(
            hasTextureResources ? "textured" : "untextured_faces",
            out _);
        ApplySceneState();
    }
}
