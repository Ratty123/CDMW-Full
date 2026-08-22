using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Numerics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using Vortice.Direct3D11;
using Vortice.DXGI;

namespace Cdmw.MeshEditorExperiment;

#pragma warning disable CS8625

internal readonly record struct D3D11RenderedCameraEvidence(
    string Role,
    double YawDegrees,
    double PitchDegrees,
    int ViewportWidth,
    int ViewportHeight,
    double[] WorldViewProjection,
    long SolidDrawCount,
    uint SampleCount,
    uint SampleQuality,
    bool MultisampleResolved);

internal sealed partial class D3D11MaterialViewport
{
    public bool TryCaptureReplacementPng(
        string outputPath,
        int requestedWidth,
        int requestedHeight,
        out string sha256,
        out string error) =>
        TryCaptureReplacementPng(
            outputPath,
            requestedWidth,
            requestedHeight,
            out sha256,
            out error,
            out _);

    /// <summary>
    /// The whole scene as the viewport draws it -- both roles, overlays and all -- into a
    /// PNG. <see cref="TryCaptureReplacementPng(string, int, int, out string, out string)"/>
    /// exists to make an item icon, so it renders the replacement alone with the grid and
    /// the gizmo left out; that is the wrong picture for anyone asking what the viewport
    /// is showing, which is what a check of a placement scene needs.
    /// </summary>
    public bool TryCaptureScenePng(
        string outputPath,
        int requestedWidth,
        int requestedHeight,
        out string sha256,
        out string error) =>
        TryCaptureViewportPng(
            outputPath,
            requestedWidth,
            requestedHeight,
            replacementOnly: false,
            includeOverlays: true,
            out sha256,
            out error,
            out _);

    public bool TryCaptureReplacementPng(
        string outputPath,
        int requestedWidth,
        int requestedHeight,
        out string sha256,
        out string error,
        out D3D11RenderedCameraEvidence renderedCamera) =>
        TryCaptureViewportPng(
            outputPath,
            requestedWidth,
            requestedHeight,
            replacementOnly: true,
            includeOverlays: false,
            out sha256,
            out error,
            out renderedCamera);

    private bool TryCaptureViewportPng(
        string outputPath,
        int requestedWidth,
        int requestedHeight,
        bool replacementOnly,
        bool includeOverlays,
        out string sha256,
        out string error,
        out D3D11RenderedCameraEvidence renderedCamera)
    {
        sha256 = string.Empty;
        error = string.Empty;
        renderedCamera = default;
        if (!EnsureDeviceReady() || _device is null || _context is null)
        {
            error = "D3D11 capture requires an initialized production renderer.";
            return false;
        }

        var width = Math.Clamp(requestedWidth, 64, 2048);
        var height = Math.Clamp(requestedHeight, 64, 2048);
        var samples = CurrentRenderSampleDescription;
        var multisampled = _renderSampleCount > 1;
        var targetDescription = ColorRenderTargetDescription(width, height, samples);
        var depthDescription = DepthRenderTargetDescription(width, height, samples);
        var resolvedDescription = ColorRenderTargetDescription(
            width,
            height,
            new SampleDescription(1, 0));
        var stagingDescription = resolvedDescription;
        stagingDescription.Usage = ResourceUsage.Staging;
        stagingDescription.BindFlags = BindFlags.None;
        stagingDescription.CPUAccessFlags = CpuAccessFlags.Read;

        using var targetTexture = _device.CreateTexture2D(targetDescription);
        using var targetView = CreateSrgbRenderTargetView(targetTexture, multisampled);
        using var depthTexture = _device.CreateTexture2D(depthDescription);
        using var depthView = CreateDepthStencilView(depthTexture, multisampled);
        using var resolvedTexture = multisampled
            ? _device.CreateTexture2D(resolvedDescription)
            : null;
        using var stagingTexture = _device.CreateTexture2D(stagingDescription);
        _offscreenCaptureSurfaceBytesEstimate = EstimateOffscreenCaptureSurfaceBytes(
            width,
            height,
            _renderSampleCount);
        _peakOffscreenCaptureSurfaceBytesEstimate = Math.Max(
            _peakOffscreenCaptureSurfaceBytesEstimate,
            _offscreenCaptureSurfaceBytesEstimate);

        var previousTarget = _renderTargetView;
        var previousDepth = _depthStencilView;
        var previousWidth = _renderWidth;
        var previousHeight = _renderHeight;
        var visibleCamera = _camera;
        var cameraForCapture = CameraForCaptureViewport(visibleCamera, width, height);
        var solidDrawCountBefore =
            _texturedSolidBatchDrawCount
            + _untexturedSolidBatchDrawCount
            + _transparentSolidBatchDrawCount;
        var mapped = false;
        var multisampleResolved = false;
        try
        {
            _context.OMSetRenderTargets((ID3D11RenderTargetView?)null, null);
            _renderTargetView = targetView;
            _depthStencilView = depthView;
            _renderWidth = width;
            _renderHeight = height;
            _camera = cameraForCapture;
            _ = RenderFrame(present: false, includeOverlays: includeOverlays, replacementOnly: replacementOnly);
            _context.OMSetRenderTargets((ID3D11RenderTargetView?)null, null);
            ID3D11Texture2D captureSource = targetTexture;
            if (multisampled)
            {
                _context.ResolveSubresource(
                    resolvedTexture!,
                    0,
                    targetTexture,
                    0,
                    Format.B8G8R8A8_UNorm);
                _offscreenMultisampleResolveCount++;
                multisampleResolved = true;
                captureSource = resolvedTexture!;
            }
            _context.CopyResource(stagingTexture, captureSource);
            _context.Map(stagingTexture, 0, MapMode.Read, Vortice.Direct3D11.MapFlags.None, out var mappedResource).CheckError();
            mapped = true;

            using var bitmap = new Bitmap(width, height, PixelFormat.Format32bppArgb);
            var bitmapData = bitmap.LockBits(
                new Rectangle(0, 0, width, height),
                ImageLockMode.WriteOnly,
                PixelFormat.Format32bppArgb);
            try
            {
                var row = new byte[checked(width * 4)];
                for (var y = 0; y < height; y++)
                {
                    Marshal.Copy(
                        mappedResource.DataPointer + checked(y * (int)mappedResource.RowPitch),
                        row,
                        0,
                        row.Length);
                    Marshal.Copy(row, 0, bitmapData.Scan0 + checked(y * bitmapData.Stride), row.Length);
                }
            }
            finally
            {
                bitmap.UnlockBits(bitmapData);
            }

            var fullPath = Path.GetFullPath(outputPath);
            Directory.CreateDirectory(Path.GetDirectoryName(fullPath) ?? throw new InvalidOperationException("Capture output has no parent directory."));
            var temporaryPath = fullPath + $".{Guid.NewGuid():N}.tmp";
            try
            {
                bitmap.Save(temporaryPath, ImageFormat.Png);
                File.Move(temporaryPath, fullPath, overwrite: true);
            }
            finally
            {
                if (File.Exists(temporaryPath))
                {
                    File.Delete(temporaryPath);
                }
            }
            sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(fullPath))).ToLowerInvariant();
            renderedCamera = new D3D11RenderedCameraEvidence(
                "editable",
                cameraForCapture.Yaw * 180.0 / Math.PI,
                cameraForCapture.Pitch * 180.0 / Math.PI,
                width,
                height,
                cameraForCapture.WorldViewProjectionRowMajorArray(),
                (_texturedSolidBatchDrawCount
                    + _untexturedSolidBatchDrawCount
                    + _transparentSolidBatchDrawCount)
                - solidDrawCountBefore,
                _renderSampleCount,
                _renderSampleQuality,
                multisampleResolved);
            return true;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            return false;
        }
        finally
        {
            if (mapped)
            {
                _context.Unmap(stagingTexture, 0);
            }
            _context.OMSetRenderTargets((ID3D11RenderTargetView?)null, null);
            _renderTargetView = previousTarget;
            _depthStencilView = previousDepth;
            _renderWidth = previousWidth;
            _renderHeight = previousHeight;
            _camera = visibleCamera;
            if (previousTarget is not null)
            {
                _context.OMSetRenderTargets(previousTarget, previousDepth);
            }
            _offscreenCaptureSurfaceBytesEstimate = 0;
        }
    }

    /// <summary>
    /// The visible camera re-aimed at a capture of <paramref name="width"/> x
    /// <paramref name="height"/>: the same view, its zoom scaled by how the capture's
    /// size compares with the viewport's and its pan scaled with it, so a capture at
    /// the viewport's own size is exactly what is on screen and a smaller square shows
    /// a little more around the subject.
    /// </summary>
    /// <remarks>
    /// The screen draws from <see cref="NetViewportCamera.WorldViewProjection"/>, so the
    /// capture is that matrix with its x and y rescaled: each clip axis is 2 * zoom /
    /// extent with the pan riding on the same scale, which makes this exactly
    /// <see cref="NetViewportCamera.Create"/> re-run at the scaled zoom and pan, and for
    /// <see cref="NetViewportCamera.CreateArchiveAudit"/> exactly its World times the
    /// capture projection. Neither constructor is recreated through the other, so the
    /// audit keeps its Archive Browser object-rotation basis and the interactive camera
    /// keeps the editor's. Building the capture from <see cref="NetViewportCamera.World"/>
    /// and a fresh projection (this method from 2026-07-17 to 2026-08-22) agreed with
    /// the screen only at yaw 0: the interactive constructor then wrote World and
    /// WorldViewProjection as two separate hand-built matrices that did not encode the
    /// same rotation and folded the pan in at different points, so an icon taken from an
    /// orbited view came out at another angle. World is the projection's view frame
    /// since then (the parity proof holds it there), but the screen's matrix stays the
    /// capture's source: it is the one thing the capture must equal.
    /// </remarks>
    internal static NetViewportCamera CameraForCaptureViewport(
        NetViewportCamera camera,
        int width,
        int height)
    {
        var sourceWidth = Math.Max(1.0f, camera.ViewportWidth);
        var sourceHeight = Math.Max(1.0f, camera.ViewportHeight);
        var uniformScale = Math.Max(
            0.001f,
            Math.Min(width / sourceWidth, height / sourceHeight));
        var sourceZoom = Math.Max(0.001f, camera.Zoom);
        var captureZoom = Math.Max(0.001f, camera.Zoom * uniformScale);
        var captureWidth = Math.Max(1.0f, width);
        var captureHeight = Math.Max(1.0f, height);
        var captureScale = Matrix4x4.CreateScale(
            (captureZoom / sourceZoom) * (sourceWidth / captureWidth),
            (captureZoom / sourceZoom) * (sourceHeight / captureHeight),
            1.0f);

        return camera with
        {
            Zoom = captureZoom,
            PanX = camera.PanX * uniformScale,
            PanY = camera.PanY * uniformScale,
            ViewportWidth = captureWidth,
            ViewportHeight = captureHeight,
            WorldViewProjection = camera.WorldViewProjection * captureScale,
        };
    }
}
