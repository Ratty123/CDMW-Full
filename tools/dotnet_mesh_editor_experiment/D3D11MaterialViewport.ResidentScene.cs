namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    public long ResidentSceneLoadCount { get; private set; } = 1;

    public void ReplaceResidentScene(
        ObjDocument document,
        NetMaterialSet materials,
        NetTextureSet textureSet,
        NetSceneState scene)
    {
        if (_device is null || _context is null || !IsInitialized)
        {
            throw new InvalidOperationException("D3D11 resident renderer is not initialized.");
        }
        var previousDocument = _document;
        var previousMaterials = _materials;
        var previousTextureSet = _textureSet;
        var previousScene = _scene;
        var previousGeometryDirty = _geometryDirty;
        var previousMaterialResourcesDirty = _materialResourcesDirty;
        _document = document;
        _materials = materials;
        _textureSet = textureSet;
        _scene = scene;
        _materialResourcesDirty = true;
        _geometryDirty = true;
        try
        {
            RebuildGeometry(requireTextureResources: true);
            ResidentSceneLoadCount++;
            // The first real package ends the placeholder's tenure; from here
            // every frame draws the scene someone actually asked for.
            ScenePresentationSuppressed = false;
            LastError = string.Empty;
            Invalidate();
        }
        catch
        {
            _document = previousDocument;
            _materials = previousMaterials;
            _textureSet = previousTextureSet;
            _scene = previousScene;
            DiscardTextureResourceRefreshState();
            _geometryDirty = previousGeometryDirty;
            _materialResourcesDirty = previousMaterialResourcesDirty;
            if (_geometryDirty || _materialResourcesDirty)
            {
                Invalidate();
            }
            throw;
        }
    }
}
