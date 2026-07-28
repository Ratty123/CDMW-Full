namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    public long ResidentSceneLoadCount => _d3d11Viewport?.ResidentSceneLoadCount ?? 0;

    /// <summary>
    /// The view a freshly loaded package settles on. Read-only previews show
    /// wire over untextured geometry by default, and plain textured geometry
    /// once textures are resolved; the wire overlay is the authoring default,
    /// not the preview one.
    /// </summary>
    internal string InitialResidentDisplayMode(bool hasTextureResources)
    {
        if (_options.SimplePreview)
        {
            return hasTextureResources ? "textured" : "untextured_wire";
        }
        return hasTextureResources ? "textured_wire" : "untextured_wire";
    }

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
        var preserveArchiveCamera = !string.IsNullOrWhiteSpace(_scene.ArchivePreviewSourcePath)
            && string.Equals(
                _scene.ArchivePreviewSourcePath,
                scene.ArchivePreviewSourcePath,
                StringComparison.OrdinalIgnoreCase);
        var previousCamera = (_yaw, _pitch, _zoom, _panX, _panY);

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
        // Grid and gizmo visibility are host-owned display toggles, not package
        // content. Adopting the incoming scene's values here made a package
        // swap silently drop the grid whenever the package was written by a
        // builder that defaults it off.
        _scene.SetPresentationOverlayVisibility(_presentationGridVisible, _presentationGizmoVisible);
        _presentationStateFingerprint = string.Empty;
        FrameMesh();
        if (preserveArchiveCamera)
        {
            (_yaw, _pitch, _zoom, _panX, _panY) = previousCamera;
        }
        else
        {
            ApplyArchivePreviewInitialCamera();
        }
        InitializePresentationContexts();
        var hasTextureResources = materials.TextureLoadResources().Any()
            || textureSet.DecodedCount > 0
            || textureSet.NativeDdsResourceCount > 0;
        // Land on the mode the host is going to ask for anyway. Picking a
        // different one here made every swap present an intermediate view
        // before the host's own display update corrected it.
        _ = TrySetSynchronizedDisplayMode(
            InitialResidentDisplayMode(hasTextureResources),
            out _);
        ApplySceneState();
    }

    private void ApplyArchivePreviewInitialCamera()
    {
        if (!_scene.HasArchivePreviewCamera)
        {
            // Only where the package declares nothing: the preview pipeline
            // already frames by equipment slot -- weapons and shields overhead
            // at pitch -89 so a flat face is toward the camera, helmets and
            // torsos from the front -- and that authored choice outranks
            // anything inferred from bounds here.
            (_yaw, _pitch) = NetViewportCamera.FramingAnglesFor(
                SceneBoundsForContext(_activeCameraContextId),
                _yaw,
                _pitch);
            UpdateGpuViewport();
            return;
        }
        _yaw = _scene.ArchivePreviewYawDegrees * MathF.PI / 180.0f;
        _pitch = Math.Clamp(_scene.ArchivePreviewPitchDegrees, -89.0f, 89.0f) * MathF.PI / 180.0f;
        _panX = 0.0f;
        _panY = 0.0f;
        if (_scene.ArchivePreviewFitToView)
        {
            var fitZoom = FitZoomForBounds(SceneBoundsForContext(_activeCameraContextId));
            _zoom = CameraZoomPolicy.ApplyZoomFactor(
                fitZoom,
                fitZoom,
                _scene.ArchivePreviewFitRelativeZoom);
        }
        UpdateGpuViewport();
    }
}
