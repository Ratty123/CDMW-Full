using Vortice.Direct3D11;
using Vortice.DXGI;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private void UnbindGeometryResources()
    {
        if (_context is null)
        {
            return;
        }
        _context.PSSetShaderResources(0u, EmptyMaterialShaderResources);
        // The native D3D11 unbind calls accept null COM pointers. Vortice's
        // generated annotations mark these two parameters as non-null even
        // though null is the documented way to release the current binding.
        _context.IASetVertexBuffer(0u, null!, 0u);
        _context.IASetIndexBuffer((ID3D11Buffer?)null, Format.Unknown, 0);
        _context.OMSetRenderTargets((ID3D11RenderTargetView)null!, null);
    }

    private void DisposeBatches()
    {
        UnbindGeometryResources();
        foreach (var batch in _batches)
        {
            DisposeBatch(batch);
        }
        _batches.Clear();
        _residentGeometryBytes = 0;
    }

    private void DisposeDeviceResources(bool clearDeviceContext)
    {
        DisposeBatches();
        DiscardPendingTextureRegion("The D3D11 renderer stopped before the pending texture update was rendered.");
        ClearTextureCache();
        DiscardTextureResourceRefreshState();
        DisposeOverlayDynamicResources();
        DisposeGpuTimingQueries();
        DisposeEffectParticleDeviceResources();
        _blendState?.Dispose();
        _transparentBlendState?.Dispose();
        _overlayBlendState?.Dispose();
        _depthState?.Dispose();
        _transparentDepthState?.Dispose();
        _overlayDepthState?.Dispose();
        _overlayNoDepthState?.Dispose();
        _gizmoDepthState?.Dispose();
        _rasterizerState?.Dispose();
        _doubleSidedRasterizerState?.Dispose();
        _cameraBuffer?.Dispose();
        _overlayCameraBuffer?.Dispose();
        _samplerState?.Dispose();
        _inputLayout?.Dispose();
        _overlayInputLayout?.Dispose();
        _pixelShader?.Dispose();
        _overlayPixelShader?.Dispose();
        _wireGeometryShader?.Dispose();
        _vertexMarkerGeometryShader?.Dispose();
        _vertexShader?.Dispose();
        _overlayVertexShader?.Dispose();
        DisposeRenderTargets();
        _swapChain?.Dispose();
        if (clearDeviceContext)
        {
            _context?.ClearState();
            _context?.Flush();
            _context?.Dispose();
            _device?.Dispose();
            _context = null;
            _device = null;
            _maximumFrameLatency = 0;
        }
        _blendState = null;
        _transparentBlendState = null;
        _overlayBlendState = null;
        _depthState = null;
        _transparentDepthState = null;
        _overlayDepthState = null;
        _overlayNoDepthState = null;
        _gizmoDepthState = null;
        _rasterizerState = null;
        _doubleSidedRasterizerState = null;
        _cameraBuffer = null;
        _overlayCameraBuffer = null;
        _samplerState = null;
        _inputLayout = null;
        _overlayInputLayout = null;
        _pixelShader = null;
        _overlayPixelShader = null;
        _wireGeometryShader = null;
        _vertexMarkerGeometryShader = null;
        _vertexShader = null;
        _overlayVertexShader = null;
        _swapChain = null;
        _renderResourcesDirty = true;
        DiscardPendingVertexUpdates();
        _geometryDirty = true;
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _resizeCommitTimer.Stop();
            _resizeCommitTimer.Tick -= OnResizeCommitTimerTick;
            _resizeCommitTimer.Dispose();
            if (_effectParticlePump is not null)
            {
                _effectParticlePump.Stop();
                _effectParticlePump.Tick -= OnEffectParticlePumpTick;
                _effectParticlePump.Dispose();
                _effectParticlePump = null;
            }
            DisposeDeviceResources(clearDeviceContext: true);
        }
        base.Dispose(disposing);
    }
}
