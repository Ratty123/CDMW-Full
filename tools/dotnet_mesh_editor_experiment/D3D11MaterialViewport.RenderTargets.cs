using System.Runtime.CompilerServices;
using Vortice.Direct3D11;
using Vortice.DXGI;

namespace Cdmw.MeshEditorExperiment;

#pragma warning disable CS8625

internal sealed partial class D3D11MaterialViewport
{
    private const uint PreferredRenderSampleCount = 4;
    private static readonly uint[] RenderSampleCountCandidates = { PreferredRenderSampleCount, 2 };

    private ID3D11Texture2D? _swapChainBackBuffer;
    private ID3D11RenderTargetView? _swapChainRenderTargetView;
    private ID3D11Texture2D? _multisampleColorTexture;
    private uint _renderSampleCount = 1;
    private uint _renderSampleQuality;
    private string _antiAliasingFallbackReason = string.Empty;
    private long _multisampleResolveCount;
    private long _offscreenMultisampleResolveCount;
    private long _renderSurfaceCreateCount;
    private long _renderSurfaceDisposeCount;
    private long _renderSurfaceBytesEstimate;
    private long _peakRenderSurfaceBytesEstimate;
    private long _offscreenCaptureSurfaceBytesEstimate;
    private long _peakOffscreenCaptureSurfaceBytesEstimate;

    public uint RenderSampleCount => _renderSampleCount;
    public uint RenderSampleQuality => _renderSampleQuality;
    public string AntiAliasingMode => _renderSampleCount > 1
        ? "offscreen_msaa_resolve"
        : "single_sample_fallback";
    public string AntiAliasingFallbackReason => _antiAliasingFallbackReason;
    public long MultisampleResolveCount => _multisampleResolveCount;
    public int RenderSurfaceIdentity => CurrentRenderSurfaceIdentity();

    private SampleDescription CurrentRenderSampleDescription =>
        new(_renderSampleCount, _renderSampleQuality);

    private void CreateSwapChainRenderTargets()
    {
        if (_device is null || _swapChain is null)
        {
            return;
        }

        _swapChainBackBuffer = _swapChain.GetBuffer<ID3D11Texture2D>(0);
        _swapChainRenderTargetView = CreateSrgbRenderTargetView(
            _swapChainBackBuffer,
            multisampled: false);

        var samples = SelectRenderSampleDescription();
        _renderSampleCount = samples.Count;
        _renderSampleQuality = samples.Quality;
        if (_renderSampleCount > 1)
        {
            var colorDescription = ColorRenderTargetDescription(
                _renderWidth,
                _renderHeight,
                samples);
            _multisampleColorTexture = _device.CreateTexture2D(colorDescription);
            _renderTargetView = CreateSrgbRenderTargetView(
                _multisampleColorTexture,
                multisampled: true);
        }
        else
        {
            _renderTargetView = _swapChainRenderTargetView;
        }

        var depthDescription = DepthRenderTargetDescription(
            _renderWidth,
            _renderHeight,
            samples);
        _depthTexture = _device.CreateTexture2D(depthDescription);
        _depthStencilView = CreateDepthStencilView(
            _depthTexture,
            multisampled: _renderSampleCount > 1);
        _renderSurfaceBytesEstimate = EstimateRenderSurfaceBytes(
            _renderWidth,
            _renderHeight,
            _renderSampleCount);
        _peakRenderSurfaceBytesEstimate = Math.Max(
            _peakRenderSurfaceBytesEstimate,
            _renderSurfaceBytesEstimate);
        _renderSurfaceCreateCount++;
    }

    private SampleDescription SelectRenderSampleDescription()
    {
        if (_device is null)
        {
            _antiAliasingFallbackReason = "d3d11_device_unavailable";
            return new SampleDescription(1, 0);
        }

        foreach (var sampleCount in RenderSampleCountCandidates)
        {
            var linearColorLevels = _device.CheckMultisampleQualityLevels(
                Format.B8G8R8A8_UNorm,
                sampleCount);
            var srgbColorLevels = _device.CheckMultisampleQualityLevels(
                Format.B8G8R8A8_UNorm_SRgb,
                sampleCount);
            var depthLevels = _device.CheckMultisampleQualityLevels(
                Format.D24_UNorm_S8_UInt,
                sampleCount);
            if (linearColorLevels > 0 && srgbColorLevels > 0 && depthLevels > 0)
            {
                _antiAliasingFallbackReason = sampleCount == PreferredRenderSampleCount
                    ? string.Empty
                    : $"requested_{PreferredRenderSampleCount}x_unsupported_selected_{sampleCount}x";
                return new SampleDescription(sampleCount, 0);
            }
        }

        _antiAliasingFallbackReason = $"requested_{PreferredRenderSampleCount}x_and_2x_unsupported";
        return new SampleDescription(1, 0);
    }

    private static Texture2DDescription ColorRenderTargetDescription(
        int width,
        int height,
        SampleDescription samples) =>
        new()
        {
            Width = (uint)Math.Max(1, width),
            Height = (uint)Math.Max(1, height),
            MipLevels = 1,
            ArraySize = 1,
            Format = Format.B8G8R8A8_Typeless,
            SampleDescription = samples,
            Usage = ResourceUsage.Default,
            BindFlags = BindFlags.RenderTarget,
        };

    private static Texture2DDescription DepthRenderTargetDescription(
        int width,
        int height,
        SampleDescription samples) =>
        new()
        {
            Width = (uint)Math.Max(1, width),
            Height = (uint)Math.Max(1, height),
            MipLevels = 1,
            ArraySize = 1,
            Format = Format.D24_UNorm_S8_UInt,
            SampleDescription = samples,
            Usage = ResourceUsage.Default,
            BindFlags = BindFlags.DepthStencil,
        };

    private ID3D11RenderTargetView CreateSrgbRenderTargetView(
        ID3D11Texture2D texture,
        bool multisampled)
    {
        if (_device is null)
        {
            throw new InvalidOperationException("D3D11 device is unavailable.");
        }
        return _device.CreateRenderTargetView(
            texture,
            new RenderTargetViewDescription(
                texture,
                multisampled
                    ? RenderTargetViewDimension.Texture2DMultisampled
                    : RenderTargetViewDimension.Texture2D,
                Format.B8G8R8A8_UNorm_SRgb,
                0,
                0,
                1));
    }

    private ID3D11DepthStencilView CreateDepthStencilView(
        ID3D11Texture2D texture,
        bool multisampled)
    {
        if (_device is null)
        {
            throw new InvalidOperationException("D3D11 device is unavailable.");
        }
        return _device.CreateDepthStencilView(
            texture,
            new DepthStencilViewDescription(
                texture,
                multisampled
                    ? DepthStencilViewDimension.Texture2DMultisampled
                    : DepthStencilViewDimension.Texture2D,
                Format.D24_UNorm_S8_UInt,
                0,
                0,
                1,
                DepthStencilViewFlags.None));
    }

    private void ResolveRenderTargetForPresentation()
    {
        if (_renderSampleCount <= 1)
        {
            return;
        }
        if (_context is null || _swapChainBackBuffer is null || _multisampleColorTexture is null)
        {
            throw new InvalidOperationException("D3D11 multisample resolve resources are unavailable.");
        }

        _context.OMSetRenderTargets((ID3D11RenderTargetView?)null, null);
        _context.ResolveSubresource(
            _swapChainBackBuffer,
            0,
            _multisampleColorTexture,
            0,
            Format.B8G8R8A8_UNorm);
        _multisampleResolveCount++;
    }

    private void DisposeRenderTargets()
    {
        _context?.OMSetRenderTargets((ID3D11RenderTargetView?)null, null);
        var hadResources = _renderTargetView is not null
            || _depthStencilView is not null
            || _multisampleColorTexture is not null
            || _swapChainRenderTargetView is not null
            || _swapChainBackBuffer is not null;
        var activeTarget = _renderTargetView;
        _renderTargetView = null;
        _depthStencilView?.Dispose();
        _depthStencilView = null;
        _depthTexture?.Dispose();
        _depthTexture = null;
        if (activeTarget is not null && !ReferenceEquals(activeTarget, _swapChainRenderTargetView))
        {
            activeTarget.Dispose();
        }
        _multisampleColorTexture?.Dispose();
        _multisampleColorTexture = null;
        _swapChainRenderTargetView?.Dispose();
        _swapChainRenderTargetView = null;
        _swapChainBackBuffer?.Dispose();
        _swapChainBackBuffer = null;
        _renderSurfaceBytesEstimate = 0;
        if (hadResources)
        {
            _renderSurfaceDisposeCount++;
        }
    }

    private static long EstimateRenderSurfaceBytes(int width, int height, uint sampleCount)
    {
        var pixels = checked((long)Math.Max(1, width) * Math.Max(1, height));
        var depthBytes = checked(pixels * 4L * Math.Max(1u, sampleCount));
        var multisampleColorBytes = sampleCount > 1
            ? checked(pixels * 4L * sampleCount)
            : 0L;
        return checked(depthBytes + multisampleColorBytes);
    }

    private int CurrentRenderSurfaceIdentity()
    {
        if (_swapChainBackBuffer is null
            || _renderTargetView is null
            || _depthStencilView is null)
        {
            return 0;
        }
        return HashCode.Combine(
            RuntimeHelpers.GetHashCode(_swapChainBackBuffer),
            RuntimeHelpers.GetHashCode(_renderTargetView),
            RuntimeHelpers.GetHashCode(_depthStencilView),
            _multisampleColorTexture is null
                ? 0
                : RuntimeHelpers.GetHashCode(_multisampleColorTexture));
    }

    private static long EstimateOffscreenCaptureSurfaceBytes(
        int width,
        int height,
        uint sampleCount)
    {
        var pixels = checked((long)Math.Max(1, width) * Math.Max(1, height));
        var samples = Math.Max(1u, sampleCount);
        var renderColorAndDepth = checked(pixels * 8L * samples);
        var resolveBytes = sampleCount > 1 ? checked(pixels * 4L) : 0L;
        return checked(renderColorAndDepth + resolveBytes);
    }
}
