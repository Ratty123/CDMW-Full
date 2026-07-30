namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    public bool TryInitialize(out string error)
    {
        error = string.Empty;
        try
        {
            CreateControl();
            if (!IsHandleCreated)
            {
                throw new InvalidOperationException("D3D11 viewport handle was not created.");
            }
            InitializeDevice();
            if (_device is null || _context is null || _swapChain is null || _vertexShader is null || _pixelShader is null || _inputLayout is null || _cameraBuffer is null || _overlayVertexShader is null || _vertexMarkerGeometryShader is null || _overlayPixelShader is null || _overlayInputLayout is null || _overlayCameraBuffer is null)
            {
                throw new InvalidOperationException("D3D11 device, shaders, swap chain, overlay pipeline, or pipeline state did not initialize.");
            }
            ResizeSwapChainResources();
            RebuildGeometry();
            if (_renderTargetView is null || _depthStencilView is null)
            {
                throw new InvalidOperationException("D3D11 render or depth target did not initialize.");
            }
            LastError = string.Empty;
            _consecutiveRenderFailures = 0;
            return true;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            LastError = ex.Message;
            DisposeDeviceResources(clearDeviceContext: true);
            return false;
        }
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        var width = Math.Max(1, ClientSize.Width);
        var height = Math.Max(1, ClientSize.Height);
        if (_swapChain is null || _renderTargetView is null || _renderWidth <= 0 || _renderHeight <= 0)
        {
            _renderResourcesDirty = true;
        }
        else if (_renderWidth == width && _renderHeight == height)
        {
            _resizeCommitTimer.Stop();
        }
        else
        {
            if (_resizeCommitTimer.Enabled)
            {
                _swapChainResizeCoalescedCount++;
            }
            _swapChainResizeDeferredCount++;
            _resizeCommitTimer.Stop();
            _resizeCommitTimer.Start();
        }
        Invalidate();
    }

    /// <summary>True while a coalesced resize is still waiting to be committed.</summary>
    public bool ResizeCommitPending => _resizeCommitTimer.Enabled;

    /// <summary>
    /// The size the swap chain was last resized to, which is the size the frames
    /// actually being presented were rendered at. It lags <see cref="System.Windows.Forms.Control.ClientSize"/>
    /// by design, because resizes are coalesced through <see cref="ResizeCommitPending"/>,
    /// so a diagnostic asking whether a presented frame matches its window has to
    /// read this rather than the control.
    /// </summary>
    public System.Drawing.Size PresentedRenderSize => new(_renderWidth, _renderHeight);

    public void CommitResizeImmediately()
    {
        _resizeCommitTimer.Stop();
        if (_swapChain is null)
        {
            return;
        }
        if (_renderWidth != Math.Max(1, ClientSize.Width)
            || _renderHeight != Math.Max(1, ClientSize.Height))
        {
            _renderResourcesDirty = true;
        }
        Invalidate();
    }

    private void OnResizeCommitTimerTick(object? sender, EventArgs e)
    {
        _resizeCommitTimer.Stop();
        if (IsDisposed || _swapChain is null)
        {
            return;
        }
        if (_renderWidth == Math.Max(1, ClientSize.Width)
            && _renderHeight == Math.Max(1, ClientSize.Height))
        {
            return;
        }
        _renderResourcesDirty = true;
        Invalidate();
    }
}
