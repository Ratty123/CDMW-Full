using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private bool ProductionD3D11Required => _options.Embedded && !_options.DeveloperRendererFallback;

    private void InitializeGpuViewport()
    {
        if (TryStartD3D11Viewport())
        {
            return;
        }
        if (ProductionD3D11Required)
        {
            BlockRendererUnavailable(
                string.IsNullOrWhiteSpace(_lastD3D11Error)
                    ? "Embedded production mode requires the D3D11 material renderer."
                    : $"Embedded production mode requires the D3D11 material renderer: {_lastD3D11Error}");
            return;
        }
        _ = TryStartWpfViewport();
    }

    private void BlockRendererUnavailable(string message)
    {
        _rendererBlocked = true;
        _rendererBlockReason = string.IsNullOrWhiteSpace(message)
            ? "Embedded production mode requires the D3D11 material renderer."
            : message;
        StatusRequested?.Invoke($"blocked_renderer_unavailable: {_rendererBlockReason}");
    }

    private bool TryStartD3D11Viewport()
    {
        D3D11MaterialViewport? viewport = null;
        try
        {
            viewport = new D3D11MaterialViewport(_document, _materials, _textureSet, _scene)
            {
                Dock = DockStyle.None,
                Bounds = ClientRectangle,
            };
            viewport.SetOverlaySettings(_overlaySettings);
            viewport.SetGizmoAppearance(_gizmoAppearance);
            viewport.MouseDown += (_, e) => ForwardRendererMouseDown(e);
            viewport.MouseUp += (_, e) => ForwardRendererMouseUp(e);
            viewport.MouseMove += (_, e) => ForwardRendererMouseMove(e);
            viewport.MouseWheel += (_, e) => ForwardRendererMouseWheel(e);
            viewport.MouseEnter += (_, _) => OnMouseEnter(EventArgs.Empty);
            viewport.MouseLeave += (_, _) => OnMouseLeave(EventArgs.Empty);
            viewport.BackendUnavailable += HandleD3D11BackendUnavailable;
            viewport.FrameRendered += RecordRenderedFrame;
            viewport.TextureRegionCompleted += HandleTextureRegionCompleted;
            if (!viewport.TryInitialize(out var error))
            {
                RetainD3D11LifecycleCounts(viewport);
                viewport.Dispose();
                _lastD3D11Error = error;
                var nextStep = ProductionD3D11Required ? "blocking renderer" : "trying WPF fallback";
                StatusRequested?.Invoke($"D3D11/Vortice material viewport unavailable; {nextStep}: {error}");
                return false;
            }
            _d3d11Viewport = viewport;
            _d3d11Viewport.ApplyPresentationSettings(_residentPresentationSettings);
            Controls.Add(_d3d11Viewport);
            CommitInitialRenderSurfaceSize();
            _d3d11Viewport.BringToFront();
            StatusRequested?.Invoke("D3D11/Vortice HLSL material viewport initialized.");
            return true;
        }
        catch (Exception ex)
        {
            if (viewport is not null)
            {
                RetainD3D11LifecycleCounts(viewport);
            }
            viewport?.Dispose();
            _d3d11Viewport = null;
            _lastD3D11Error = ex.Message;
            var nextStep = ProductionD3D11Required ? "blocking renderer" : "trying WPF fallback";
            StatusRequested?.Invoke($"D3D11/Vortice material viewport unavailable; {nextStep}: {ex.Message}");
            return false;
        }
    }

    private bool TryStartWpfViewport()
    {
        try
        {
            _gpuViewport = new WpfGpuMeshViewport(_document, _materials, _textureSet);
            _gpuViewport.SetOverlaySettings(_overlaySettings);
            _gpuHost = new System.Windows.Forms.Integration.ElementHost
            {
                Dock = DockStyle.Fill,
                Child = _gpuViewport.Root,
                BackColor = BackColor,
            };
            _gpuHost.MouseDown += (_, e) => ForwardRendererMouseDown(e);
            _gpuHost.MouseUp += (_, e) => ForwardRendererMouseUp(e);
            _gpuHost.MouseMove += (_, e) => ForwardRendererMouseMove(e);
            _gpuHost.MouseWheel += (_, e) => ForwardRendererMouseWheel(e);
            _gpuHost.MouseEnter += (_, _) => OnMouseEnter(EventArgs.Empty);
            _gpuHost.MouseLeave += (_, _) => OnMouseLeave(EventArgs.Empty);
            Controls.Add(_gpuHost);
            _gpuHost.BringToFront();
            StatusRequested?.Invoke("WPF GPU material viewport initialized.");
            return true;
        }
        catch (Exception ex)
        {
            _gpuViewport?.Dispose();
            _gpuHost?.Dispose();
            _gpuViewport = null;
            _gpuHost = null;
            StatusRequested?.Invoke($"WPF GPU material viewport unavailable; using software fallback: {ex.Message}");
            return false;
        }
    }

    private void ForwardRendererMouseWheel(MouseEventArgs e)
    {
        PreviewPerformanceCapture.RecordInput(PreviewPerformanceInputKind.Physical);
        OnMouseWheel(e);
        if (e is HandledMouseEventArgs handled)
        {
            handled.Handled = true;
        }
    }

    private void ForwardRendererMouseDown(MouseEventArgs e)
    {
        PreviewPerformanceCapture.RecordInput(PreviewPerformanceInputKind.Physical);
        OnMouseDown(e);
    }

    private void ForwardRendererMouseUp(MouseEventArgs e)
    {
        PreviewPerformanceCapture.RecordInput(PreviewPerformanceInputKind.Physical);
        OnMouseUp(e);
    }

    private void ForwardRendererMouseMove(MouseEventArgs e)
    {
        if (e.Button != MouseButtons.None)
        {
            PreviewPerformanceCapture.RecordInput(PreviewPerformanceInputKind.Physical);
        }
        OnMouseMove(e);
    }

    private void HandleD3D11BackendUnavailable(string message)
    {
        var failed = _d3d11Viewport;
        if (failed is null)
        {
            return;
        }
        failed.BackendUnavailable -= HandleD3D11BackendUnavailable;
        failed.FrameRendered -= RecordRenderedFrame;
        failed.TextureRegionCompleted -= HandleTextureRegionCompleted;
        RetainD3D11LifecycleCounts(failed);
        Controls.Remove(failed);
        _d3d11Viewport = null;
        failed.Dispose();
        if (ProductionD3D11Required)
        {
            BlockRendererUnavailable($"{message} Embedded production mode requires the D3D11 material renderer.");
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        StatusRequested?.Invoke($"{message} Falling back to WPF/GDI renderer.");
        if (_gpuViewport is null && _gpuHost is null)
        {
            _ = TryStartWpfViewport();
        }
        UpdateGpuViewport();
        Invalidate();
    }

    private void UpdateGpuViewport()
    {
        RequestFrame();
        _camera = CurrentCamera();
        if (_d3d11Viewport is not null)
        {
            _d3d11Viewport.MaterialDebugMode = MaterialDebugMode;
            _d3d11Viewport.ShowSolid = ShowSolid;
            _d3d11Viewport.TexturesEnabled = TexturesEnabled;
            _d3d11Viewport.UpdateCamera(_camera);
            _d3d11Viewport.UpdateRenderPanes(_currentRenderPanes, PopulateCurrentRenderPanes());
            var brushTool = ActiveTool is "grab" or "smooth" or "inflate" or "pinch";
            var brushRadius = brushTool
                ? (float)NumberOption(
                    ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>(),
                    "radius",
                    24.0)
                : 24.0f;
            _presentedSources.Clear();
            _presentedSources.UnionWith(_selectedSources);
            _presentedSources.UnionWith(_presentationHighlightedSources);
            foreach (var originalIndex in _presentationHighlightedOriginals)
            {
                var sourceIndex = _scene.EditableSubmeshCount + originalIndex;
                if (sourceIndex >= 0)
                {
                    _presentedSources.Add(sourceIndex);
                }
            }
            var presentedSourceIndex = _presentationHoveredSource >= 0
                ? _presentationHoveredSource
                : MinimumPresentedSourceIndex();
            _d3d11Viewport.UpdateOverlay(_edgeTopology, _selectedEdges, _hoverEdgeId, _edgeDragActive ? EdgeDragRectangle() : null, _selectedVertices, _selectedFaces, _presentedSources, presentedSourceIndex, ShowWire, ShowVertices, ShowXRay, brushTool && _pointerInside ? _pointerLocation : null, brushRadius);
            return;
        }
        var viewport = _gpuViewport;
        if (viewport is null)
        {
            return;
        }
        viewport.UpdateCamera(_camera);
        viewport.UpdateOverlay(
            _edgeTopology,
            _selectedEdges,
            _hoverEdgeId,
            _edgeDragActive ? EdgeDragRectangle() : null,
            _selectedVertices,
            _selectedFaces,
            _selectedSources,
            SelectedSubmeshIndex,
            ShowWire,
            ShowXRay,
            _camera.Project);
    }

    private int MinimumPresentedSourceIndex()
    {
        var minimum = int.MaxValue;
        foreach (var sourceIndex in _presentedSources)
        {
            minimum = Math.Min(minimum, sourceIndex);
        }
        return minimum == int.MaxValue ? -1 : minimum;
    }

    private void QueueRenderSurfaceResize()
    {
        var viewport = _d3d11Viewport;
        if (viewport is null)
        {
            return;
        }
        RequestFrame();
        if (viewport.Bounds == ClientRectangle)
        {
            _renderSurfaceResizeTimer.Stop();
            UpdateGpuViewport();
            return;
        }
        _renderSurfaceResizeTimer.Stop();
        _renderSurfaceResizeTimer.Start();
    }

    private void CommitInitialRenderSurfaceSize()
    {
        var viewport = _d3d11Viewport;
        if (viewport is null || ClientSize.Width <= 1 || ClientSize.Height <= 1)
        {
            return;
        }
        _renderSurfaceResizeTimer.Stop();
        viewport.Bounds = ClientRectangle;
        viewport.CommitResizeImmediately();
    }

    private void OnRenderSurfaceResizeTimerTick(object? sender, EventArgs e)
    {
        _renderSurfaceResizeTimer.Stop();
        var viewport = _d3d11Viewport;
        if (viewport is null || viewport.IsDisposed)
        {
            return;
        }
        viewport.Bounds = ClientRectangle;
        UpdateGpuViewport();
    }

    public void InvalidateRenderSurface()
    {
        if (_d3d11Viewport is not null)
        {
            _d3d11Viewport.Invalidate();
            return;
        }
        if (_gpuHost is not null)
        {
            _gpuHost.Invalidate();
            return;
        }
        Invalidate();
    }

    public void EnsureRenderScheduled()
    {
        if (_frameDirty && !_renderInvalidationQueued)
        {
            QueueRenderSurfaceInvalidation();
        }
    }

    private void QueueRenderSurfaceInvalidation()
    {
        if (_renderInvalidationQueued || IsDisposed || Disposing || !IsHandleCreated)
        {
            return;
        }
        _renderInvalidationQueued = true;
        try
        {
            BeginInvoke((Action)(() =>
            {
                _renderInvalidationQueued = false;
                if (IsDisposed || Disposing || !IsHandleCreated)
                {
                    return;
                }
                if (ConsumeRenderRequest())
                {
                    InvalidateRenderSurface();
                }
            }));
        }
        catch (InvalidOperationException)
        {
            _renderInvalidationQueued = false;
        }
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        CommitInitialRenderSurfaceSize();
        EnsureRenderScheduled();
    }

    protected override void OnHandleDestroyed(EventArgs e)
    {
        _renderInvalidationQueued = false;
        base.OnHandleDestroyed(e);
    }

    public void ApplySceneState()
    {
        if (_scene.HasAuthoritativeFrame)
        {
            var viewCenter = _center;
            _bounds = (
                new Vec3(
                    _scene.FramingBoundsMinimum.X,
                    _scene.FramingBoundsMinimum.Y,
                    _scene.FramingBoundsMinimum.Z),
                new Vec3(
                    _scene.FramingBoundsMaximum.X,
                    _scene.FramingBoundsMaximum.Y,
                    _scene.FramingBoundsMaximum.Z));
            _center = viewCenter;
        }
        _d3d11Viewport?.Invalidate();
        RequestFrame();
        UpdateGpuViewport();
        Invalidate();
    }

    public void RefreshTextures()
    {
        _d3d11Viewport?.RefreshTextures();
        RequestFrame();
        Invalidate();
    }

    public bool TryApplyMaterialState(IReadOnlyCollection<int> affectedSubmeshes, out string error)
    {
        if (_d3d11Viewport is not null)
        {
            var applied = _d3d11Viewport.TryApplyMaterialState(affectedSubmeshes, out error);
            if (applied)
            {
                RequestFrame();
                Invalidate();
            }
            return applied;
        }
        if (ProductionD3D11Required || _rendererBlocked)
        {
            error = string.IsNullOrWhiteSpace(_rendererBlockReason)
                ? "D3D11 material renderer is unavailable."
                : _rendererBlockReason;
            return false;
        }
        error = string.Empty;
        RequestFrame();
        Invalidate();
        return true;
    }

    public bool TryApplyMaterialParameters(IReadOnlyCollection<int> affectedSubmeshes, out string error)
    {
        if (_d3d11Viewport is null)
        {
            error = ProductionD3D11Required || _rendererBlocked
                ? (string.IsNullOrWhiteSpace(_rendererBlockReason) ? "D3D11 material renderer is unavailable." : _rendererBlockReason)
                : "Material parameter updates require the D3D11 material renderer; WPF/GDI fallback is unsupported.";
            return false;
        }
        if (!_d3d11Viewport.TryApplyMaterialParameters(affectedSubmeshes, out error))
        {
            return false;
        }
        RequestFrame();
        Invalidate();
        return true;
    }

    private void HandleTextureRegionCompleted(NetTextureRegionUpdate update, int bytesUploaded, string error) =>
        TextureRegionCompleted?.Invoke(update, bytesUploaded, error);

    public bool TryQueueTextureRegion(NetTextureRegionUpdate update, byte[] pixels, out string error)
    {
        if (_d3d11Viewport is null)
        {
            error = ProductionD3D11Required || _rendererBlocked
                ? (string.IsNullOrWhiteSpace(_rendererBlockReason) ? "D3D11 material renderer is unavailable." : _rendererBlockReason)
                : "Texture region updates require the D3D11 material renderer.";
            return false;
        }
        if (!_d3d11Viewport.TryQueueTextureRegion(update, pixels, out error))
        {
            return false;
        }
        RequestFrame();
        Invalidate();
        return true;
    }

    public bool TryCaptureReplacementPng(
        string outputPath,
        int width,
        int height,
        out string sha256,
        out string error)
    {
        sha256 = string.Empty;
        if (_d3d11Viewport is null || ProductionD3D11Required && _rendererBlocked)
        {
            error = "Deterministic icon capture requires the D3D11/Vortice production renderer.";
            return false;
        }
        return _d3d11Viewport.TryCaptureReplacementPng(outputPath, width, height, out sha256, out error);
    }
}
