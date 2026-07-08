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
            viewport = new D3D11MaterialViewport(_document, _materials, _textureSet) { Dock = DockStyle.Fill };
            viewport.MouseDown += (_, e) => OnMouseDown(e);
            viewport.MouseUp += (_, e) => OnMouseUp(e);
            viewport.MouseMove += (_, e) => OnMouseMove(e);
            viewport.MouseWheel += (_, e) => OnMouseWheel(e);
            viewport.BackendUnavailable += HandleD3D11BackendUnavailable;
            viewport.FrameRendered += RecordRenderedFrame;
            if (!viewport.TryInitialize(out var error))
            {
                viewport.Dispose();
                _lastD3D11Error = error;
                var nextStep = ProductionD3D11Required ? "blocking renderer" : "trying WPF fallback";
                StatusRequested?.Invoke($"D3D11/Vortice material viewport unavailable; {nextStep}: {error}");
                return false;
            }
            _d3d11Viewport = viewport;
            Controls.Add(_d3d11Viewport);
            _d3d11Viewport.BringToFront();
            StatusRequested?.Invoke("D3D11/Vortice HLSL material viewport initialized.");
            return true;
        }
        catch (Exception ex)
        {
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
            _gpuHost = new System.Windows.Forms.Integration.ElementHost
            {
                Dock = DockStyle.Fill,
                Child = _gpuViewport.Root,
                BackColor = BackColor,
            };
            _gpuHost.MouseDown += (_, e) => OnMouseDown(e);
            _gpuHost.MouseUp += (_, e) => OnMouseUp(e);
            _gpuHost.MouseMove += (_, e) => OnMouseMove(e);
            _gpuHost.MouseWheel += (_, e) => OnMouseWheel(e);
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

    private void HandleD3D11BackendUnavailable(string message)
    {
        var failed = _d3d11Viewport;
        if (failed is null)
        {
            return;
        }
        failed.BackendUnavailable -= HandleD3D11BackendUnavailable;
        failed.FrameRendered -= RecordRenderedFrame;
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
            _d3d11Viewport.UpdateCamera(_camera);
            _d3d11Viewport.UpdateOverlay(_edgeTopology, _selectedEdges, _hoverEdgeId, _edgeDragActive ? EdgeDragRectangle() : null, _selectedVertices, _selectedFaces, _selectedSources, SelectedSubmeshIndex, ShowWire, ShowXRay);
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
}
