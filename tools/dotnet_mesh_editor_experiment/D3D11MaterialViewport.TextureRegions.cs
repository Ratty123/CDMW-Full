using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using Vortice.Direct3D;
using Vortice.Direct3D11;
using Vortice.DXGI;
using Vortice.Mathematics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private readonly Dictionary<string, D3D11EditableTextureRegion> _editableTextureRegions = new(StringComparer.Ordinal);
    private long _textureRegionPatchCount;
    private long _textureRegionBytesUploaded;
    private long _textureRegionFailureCount;
    private long _textureRegionAffectedBatchRebindCount;
    private long _textureRegionMipGenerationCount;

    public bool TryApplyTextureRegion(
        NetTextureRegionUpdate update,
        ReadOnlySpan<byte> pixels,
        out int bytesUploaded,
        out string error)
    {
        bytesUploaded = 0;
        error = string.Empty;
        if (_device is null || _context is null)
        {
            return TextureRegionFailure("D3D11 texture renderer is not initialized.", out error);
        }
        var channelIndex = TextureRegionChannelIndex(update.Channel);
        if (channelIndex < 0)
        {
            return TextureRegionFailure($"Unsupported texture patch channel: {update.Channel}", out error);
        }
        var expectedBytes = checked(update.RowPitch * update.Rect.Height);
        if (pixels.Length != expectedBytes)
        {
            return TextureRegionFailure("Texture patch byte length does not match row_pitch and rect height.", out error);
        }
        var affected = update.AffectedSubmeshes.ToHashSet();
        if (affected.Any(index => index < 0 || index >= _document.Submeshes.Count))
        {
            return TextureRegionFailure("Texture patch references an unknown submesh.", out error);
        }
        var targets = _batches.Where(batch => affected.Contains(batch.SubmeshIndex)).ToArray();
        if (targets.Length == 0 || targets.Select(batch => batch.SubmeshIndex).Distinct().Count() != affected.Count)
        {
            return TextureRegionFailure("Texture patch has no resident render batch for every affected submesh.", out error);
        }

        var references = targets
            .Select(batch => TextureRegionReference(batch.MaterialSubmeshIndex, update.Channel))
            .ToArray();
        if (references.Any(reference => reference.IsEmpty || !string.Equals(reference.ResourceId, update.ResourceId, StringComparison.Ordinal)))
        {
            return TextureRegionFailure("Texture patch resource_id does not match the active affected-submesh channel.", out error);
        }
        var sourceCacheKey = references[0].CacheKey;
        if (references.Any(reference => !string.Equals(reference.CacheKey, sourceCacheKey, StringComparison.OrdinalIgnoreCase)))
        {
            return TextureRegionFailure("Texture patch affected submeshes do not share one active texture resource.", out error);
        }

        if (_editableTextureRegions.TryGetValue(update.ResourceId, out var editable))
        {
            if (!string.Equals(editable.SourceCacheKey, sourceCacheKey, StringComparison.OrdinalIgnoreCase)
                || editable.Width != update.TextureWidth || editable.Height != update.TextureHeight)
            {
                return TextureRegionFailure("Texture patch dimensions or source identity changed; send a material-state update first.", out error);
            }
            if (targets.Any(batch => !ReferenceEquals(batch.Materials.ShaderResources[channelIndex], editable.View)))
            {
                return TextureRegionFailure("Editable texture is not bound to every affected batch.", out error);
            }
            try
            {
                UploadTextureRegion(editable.Texture, update, pixels);
                _context.GenerateMips(editable.View);
                _textureRegionMipGenerationCount++;
                RecordTextureRegionApplied(expectedBytes);
                bytesUploaded = expectedBytes;
                Invalidate();
                return true;
            }
            catch (Exception ex)
            {
                return TextureRegionFailure(ex.Message, out error);
            }
        }

        if (!_textureSrvCache.TryGetValue(sourceCacheKey, out var source))
        {
            return TextureRegionFailure("Last-good immutable source texture is not resident.", out error);
        }
        if (source.Width != update.TextureWidth || source.Height != update.TextureHeight)
        {
            return TextureRegionFailure("Texture patch dimensions do not match the resident source texture.", out error);
        }

        ID3D11Texture2D? texture = null;
        ID3D11ShaderResourceView? view = null;
        try
        {
            var sourceBitmap = _textureSet.BitmapForReference(references[0]);
            if (sourceBitmap is null)
            {
                return TextureRegionFailure(
                    "The source DDS is GPU-native only and cannot enter the editable BGRA texture path.",
                    out error);
            }
            using var converted = new Bitmap(sourceBitmap.Width, sourceBitmap.Height, PixelFormat.Format32bppArgb);
            using (var graphics = Graphics.FromImage(converted))
            {
                graphics.DrawImageUnscaled(sourceBitmap, 0, 0);
            }
            var bitmapRect = new Rectangle(0, 0, converted.Width, converted.Height);
            var bitmapData = converted.LockBits(bitmapRect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            var mipCount = EditableMipLevelCount(source.Width, source.Height);
            try
            {
                texture = _device.CreateTexture2D(
                    new Texture2DDescription
                    {
                        Width = (uint)source.Width,
                        Height = (uint)source.Height,
                        MipLevels = (uint)mipCount,
                        ArraySize = 1,
                        Format = Format.B8G8R8A8_Typeless,
                        SampleDescription = new SampleDescription(1, 0),
                        Usage = ResourceUsage.Default,
                        BindFlags = BindFlags.ShaderResource | BindFlags.RenderTarget,
                        MiscFlags = ResourceOptionFlags.GenerateMips,
                    });
                _context.UpdateSubresource(
                    texture,
                    0,
                    null,
                    bitmapData.Scan0,
                    (uint)bitmapData.Stride,
                    0);
            }
            finally
            {
                converted.UnlockBits(bitmapData);
            }
            var viewFormat = string.Equals(references[0].ColorSpace, "srgb", StringComparison.OrdinalIgnoreCase)
                ? Format.B8G8R8A8_UNorm_SRgb
                : Format.B8G8R8A8_UNorm;
            view = _device.CreateShaderResourceView(
                texture,
                new ShaderResourceViewDescription(
                    texture,
                    ShaderResourceViewDimension.Texture2D,
                    viewFormat,
                    0,
                    (uint)mipCount,
                    0,
                    1));
            UploadTextureRegion(texture, update, pixels);
            _context.GenerateMips(view);
            _textureRegionMipGenerationCount++;

            var replacements = targets
                .Select(batch => (Batch: batch, Materials: batch.Materials.WithShaderResource(channelIndex, view)))
                .ToArray();
            UnbindGeometryResources();
            foreach (var replacement in replacements)
            {
                replacement.Batch.Materials = replacement.Materials;
            }
            var estimatedBytes = EditableMipBytes(source.Width, source.Height);
            var entry = new D3D11EditableTextureRegion(
                texture,
                view,
                sourceCacheKey,
                source.Width,
                source.Height,
                mipCount,
                estimatedBytes);
            _editableTextureRegions.Add(update.ResourceId, entry);
            texture = null;
            view = null;
            _textureSrvCreateCount++;
            _materialBindingArrayCreateCount += replacements.Length;
            _affectedMaterialBatchRebindCount += replacements.Length;
            _textureRegionAffectedBatchRebindCount += replacements.Length;
            _textureResidentBytes += estimatedBytes;
            _peakTextureResidentBytes = Math.Max(_peakTextureResidentBytes, _textureResidentBytes);
            _peakTextureRefreshBytesEstimate = Math.Max(_peakTextureRefreshBytesEstimate, _textureResidentBytes);
            RecordTextureRegionApplied(expectedBytes);
            bytesUploaded = expectedBytes;
            Invalidate();
            return true;
        }
        catch (Exception ex)
        {
            view?.Dispose();
            texture?.Dispose();
            return TextureRegionFailure(ex.Message, out error);
        }
    }

    private void UploadTextureRegion(ID3D11Texture2D texture, NetTextureRegionUpdate update, ReadOnlySpan<byte> pixels)
    {
        _context!.UpdateSubresource(
            pixels,
            texture,
            0,
            (uint)update.RowPitch,
            0,
            new Box(
                update.Rect.X,
                update.Rect.Y,
                0,
                checked(update.Rect.X + update.Rect.Width),
                checked(update.Rect.Y + update.Rect.Height),
                1));
    }

    private static int EditableMipLevelCount(int width, int height)
    {
        var mipCount = 1;
        while (width > 1 || height > 1)
        {
            width = Math.Max(1, width / 2);
            height = Math.Max(1, height / 2);
            mipCount++;
        }
        return mipCount;
    }

    private static long EditableMipBytes(int width, int height)
    {
        long bytes = 0;
        while (true)
        {
            bytes = checked(bytes + checked((long)width * height * 4));
            if (width == 1 && height == 1)
            {
                return bytes;
            }
            width = Math.Max(1, width / 2);
            height = Math.Max(1, height / 2);
        }
    }

    private void RecordTextureRegionApplied(int bytesUploaded)
    {
        _textureRegionPatchCount++;
        _textureRegionBytesUploaded += bytesUploaded;
        LastError = string.Empty;
    }

    private bool TextureRegionFailure(string message, out string error)
    {
        _textureRegionFailureCount++;
        LastError = message;
        error = message;
        return false;
    }

    private NetMaterialTextureReference TextureRegionReference(int submeshIndex, string channel)
    {
        return TextureRegionChannelIndex(channel) switch
        {
            0 => _materials.TextureReferenceForSubmesh(submeshIndex, "base", "albedo", "diffuse"),
            1 => _materials.TextureReferenceForSubmesh(submeshIndex, "normal"),
            2 => _materials.TextureReferenceForSubmesh(submeshIndex, "specular"),
            3 => _materials.TextureReferenceForSubmesh(submeshIndex, "roughness"),
            4 => _materials.TextureReferenceForSubmesh(submeshIndex, "metallic"),
            5 => _materials.TextureReferenceForSubmesh(submeshIndex, "height"),
            6 => _materials.TextureReferenceForSubmesh(submeshIndex, "emissive"),
            7 => _materials.TextureReferenceForSubmesh(submeshIndex, "layer_mask", "mask"),
            8 => _materials.TextureReferenceForSubmesh(submeshIndex, "opacity"),
            9 => _materials.TextureReferenceForSubmesh(submeshIndex, "occlusion", "ao"),
            _ => NetMaterialTextureReference.Empty,
        };
    }

    private static int TextureRegionChannelIndex(string channel)
    {
        return channel.Trim().ToLowerInvariant() switch
        {
            "base" or "albedo" or "diffuse" => 0,
            "normal" => 1,
            "specular" => 2,
            "roughness" => 3,
            "metallic" => 4,
            "height" => 5,
            "emissive" => 6,
            "layer_mask" or "mask" => 7,
            "opacity" => 8,
            "occlusion" or "ao" => 9,
            _ => -1,
        };
    }

    private void PruneEditableTextureRegions()
    {
        foreach (var resourceId in _editableTextureRegions.Keys.ToArray())
        {
            var entry = _editableTextureRegions[resourceId];
            if (_batches.Any(batch => batch.Materials.ShaderResources.Any(view => ReferenceEquals(view, entry.View))))
            {
                continue;
            }
            DisposeEditableTextureRegion(resourceId, entry);
        }
    }

    private void ClearEditableTextureRegions()
    {
        foreach (var pair in _editableTextureRegions.ToArray())
        {
            DisposeEditableTextureRegion(pair.Key, pair.Value);
        }
    }

    private void DisposeEditableTextureRegion(string resourceId, D3D11EditableTextureRegion entry)
    {
        entry.View.Dispose();
        entry.Texture.Dispose();
        _editableTextureRegions.Remove(resourceId);
        _textureSrvDisposeCount++;
        _textureResidentBytes = Math.Max(0, _textureResidentBytes - entry.EstimatedBytes);
        _maxDisposedTextureResourceLifetimeMs = Math.Max(
            _maxDisposedTextureResourceLifetimeMs,
            ElapsedMilliseconds(entry.CreatedTimestamp));
    }
}

internal sealed record D3D11EditableTextureRegion(
    ID3D11Texture2D Texture,
    ID3D11ShaderResourceView View,
    string SourceCacheKey,
    int Width,
    int Height,
    int MipCount,
    long EstimatedBytes,
    long CreatedTimestamp)
{
    public D3D11EditableTextureRegion(
        ID3D11Texture2D texture,
        ID3D11ShaderResourceView view,
        string sourceCacheKey,
        int width,
        int height,
        int mipCount,
        long estimatedBytes)
        : this(texture, view, sourceCacheKey, width, height, mipCount, estimatedBytes, Stopwatch.GetTimestamp())
    {
    }
}
