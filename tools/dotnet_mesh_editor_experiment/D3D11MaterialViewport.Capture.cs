using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
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
    long SolidDrawCount);

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

    public bool TryCaptureReplacementPng(
        string outputPath,
        int requestedWidth,
        int requestedHeight,
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
        var targetDescription = new Texture2DDescription
        {
            Width = (uint)width,
            Height = (uint)height,
            MipLevels = 1,
            ArraySize = 1,
            Format = Format.B8G8R8A8_Typeless,
            SampleDescription = new SampleDescription(1, 0),
            Usage = ResourceUsage.Default,
            BindFlags = BindFlags.RenderTarget,
        };
        var depthDescription = new Texture2DDescription
        {
            Width = (uint)width,
            Height = (uint)height,
            MipLevels = 1,
            ArraySize = 1,
            Format = Format.D24_UNorm_S8_UInt,
            SampleDescription = new SampleDescription(1, 0),
            Usage = ResourceUsage.Default,
            BindFlags = BindFlags.DepthStencil,
        };
        var stagingDescription = targetDescription;
        stagingDescription.Usage = ResourceUsage.Staging;
        stagingDescription.BindFlags = BindFlags.None;
        stagingDescription.CPUAccessFlags = CpuAccessFlags.Read;

        using var targetTexture = _device.CreateTexture2D(targetDescription);
        using var targetView = _device.CreateRenderTargetView(
            targetTexture,
            new RenderTargetViewDescription(
                targetTexture,
                RenderTargetViewDimension.Texture2D,
                Format.B8G8R8A8_UNorm_SRgb,
                0,
                0,
                1));
        using var depthTexture = _device.CreateTexture2D(depthDescription);
        using var depthView = _device.CreateDepthStencilView(depthTexture);
        using var stagingTexture = _device.CreateTexture2D(stagingDescription);

        var previousTarget = _renderTargetView;
        var previousDepth = _depthStencilView;
        var previousWidth = _renderWidth;
        var previousHeight = _renderHeight;
        var cameraForCapture = _camera;
        var solidDrawCountBefore = _texturedSolidBatchDrawCount + _untexturedSolidBatchDrawCount;
        var mapped = false;
        try
        {
            _context.OMSetRenderTargets((ID3D11RenderTargetView?)null, null);
            _renderTargetView = targetView;
            _depthStencilView = depthView;
            _renderWidth = width;
            _renderHeight = height;
            _ = RenderFrame(present: false, includeOverlays: false, replacementOnly: true);
            _context.CopyResource(stagingTexture, targetTexture);
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
                (_texturedSolidBatchDrawCount + _untexturedSolidBatchDrawCount) - solidDrawCountBefore);
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
            if (previousTarget is not null)
            {
                _context.OMSetRenderTargets(previousTarget, previousDepth);
            }
        }
    }
}
