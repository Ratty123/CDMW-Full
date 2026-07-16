using System.Diagnostics;
using System.Drawing.Imaging;
using System.IO;
using Vortice.Direct3D;
using Vortice.Direct3D11;
using Vortice.DXGI;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private static readonly ID3D11ShaderResourceView?[] EmptyMaterialShaderResources = new ID3D11ShaderResourceView?[10];
    private bool _materialResourcesDirty;
    private bool _textureResourceRefreshActive;
    private long _textureSrvCreateCount;
    private long _textureSrvDisposeCount;
    private long _textureSrvReuseCount;
    private long _materialBindingArrayCreateCount;
    private long _materialStateApplyCount;
    private long _materialStateApplyFailureCount;
    private long _affectedMaterialBatchRebindCount;
    private long _supersededTextureSrvPruneCount;
    private long _nativeDdsSrvCreateCount;
    private long _bitmapTextureSrvCreateCount;
    private long _nativeDdsFallbackCount;
    private long _textureResidentBytes;
    private long _peakTextureResidentBytes;
    private long _peakTextureRefreshBytesEstimate;
    private double _maxDisposedTextureResourceLifetimeMs;

    public int NativeDdsTextureCount => _textureSrvCache.Values.Count(entry => entry.NativeDds);
    public int BitmapFallbackTextureCount => _textureSrvCache.Values.Count(entry => !entry.NativeDds);
    public long NativeDdsFallbackCount => _nativeDdsFallbackCount;

    public void RefreshTextures()
    {
        _materialResourcesDirty = true;
        Invalidate();
    }

    private void RebuildMaterialResourcesIfDirty()
    {
        if (!_materialResourcesDirty)
        {
            return;
        }
        if (!TryApplyMaterialState(_batches.Select(batch => batch.SubmeshIndex).ToArray(), out var error))
        {
            LastError = error;
        }
    }

    public bool TryApplyMaterialState(IReadOnlyCollection<int> affectedSubmeshes, out string error)
    {
        error = string.Empty;
        if (_device is null)
        {
            error = "D3D11 device is not initialized.";
            _materialStateApplyFailureCount++;
            return false;
        }
        var affected = affectedSubmeshes.ToHashSet();
        var targets = _batches.Where(batch => affected.Contains(batch.SubmeshIndex)).ToArray();
        var replacements = new List<(D3D11SubmeshBatch Batch, D3D11MaterialResources Materials)>(targets.Length);
        _materialResourcesDirty = true;
        BeginTextureResourceRefresh();
        try
        {
            foreach (var batch in targets)
            {
                replacements.Add((batch, CreateMaterialResources(batch.MaterialSubmeshIndex)));
            }
            UnbindGeometryResources();
            foreach (var replacement in replacements)
            {
                replacement.Batch.Materials = replacement.Materials;
            }
            _affectedMaterialBatchRebindCount += replacements.Count;
            PruneTextureCacheToActiveBindings();
            _materialStateApplyCount++;
            LastError = string.Empty;
            Invalidate();
            return true;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            LastError = ex.Message;
            _materialStateApplyFailureCount++;
            PruneTextureCacheToActiveBindings();
            return false;
        }
        finally
        {
            EndTextureResourceRefresh();
        }
    }

    private void BeginTextureResourceRefresh()
    {
        if (!_materialResourcesDirty || _textureResourceRefreshActive)
        {
            return;
        }
        UnbindGeometryResources();
        _textureResourceRefreshActive = true;
    }

    private void EndTextureResourceRefresh()
    {
        if (!_textureResourceRefreshActive)
        {
            return;
        }
        _peakTextureRefreshBytesEstimate = Math.Max(
            _peakTextureRefreshBytesEstimate,
            _textureResidentBytes);
        _textureResourceRefreshActive = false;
        _materialResourcesDirty = false;
    }

    private D3D11MaterialResources CreateMaterialResources(int submeshIndex)
    {
        var baseTexture = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "base", "albedo", "diffuse"));
        var normal = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "normal"));
        var specular = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "specular"));
        var roughness = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "roughness"));
        var metallic = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "metallic"));
        var height = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "height"));
        var emissive = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "emissive"));
        var layerMask = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "layer_mask", "mask"));
        var opacity = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "opacity"));
        var occlusion = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "occlusion", "ao"));
        var resources = new D3D11MaterialResources(
            baseTexture.View,
            normal.View,
            specular.View,
            roughness.View,
            metallic.View,
            height.View,
            emissive.View,
            layerMask.View,
            opacity.View,
            occlusion.View,
            new[] { baseTexture.CacheKey, normal.CacheKey, specular.CacheKey, roughness.CacheKey, metallic.CacheKey, height.CacheKey, emissive.CacheKey, layerMask.CacheKey, opacity.CacheKey, occlusion.CacheKey }
                .Where(key => !string.IsNullOrWhiteSpace(key))
                .ToHashSet(StringComparer.OrdinalIgnoreCase));
        _materialBindingArrayCreateCount++;
        return resources;
    }

    private D3D11TextureBinding CreateTextureSrv(NetMaterialTextureReference reference)
    {
        if (_device is null || reference.IsEmpty)
        {
            return D3D11TextureBinding.Empty;
        }
        var cacheKey = reference.CacheKey;
        if (_editableTextureRegions.TryGetValue(reference.ResourceId, out var editable)
            && string.Equals(editable.SourceCacheKey, cacheKey, StringComparison.OrdinalIgnoreCase))
        {
            _textureSrvReuseCount++;
            return new D3D11TextureBinding(editable.View, cacheKey);
        }
        if (_textureSrvCache.TryGetValue(cacheKey, out var cached))
        {
            _textureSrvReuseCount++;
            return new D3D11TextureBinding(cached.View, cacheKey);
        }
        var nativeDds = _textureSet.NativeDdsForReference(reference);
        var nativeFallbackReason = string.Empty;
        if (nativeDds is not null)
        {
            try
            {
                return CreateNativeDdsSrv(reference, nativeDds, cacheKey);
            }
            catch (Exception ex)
            {
                nativeFallbackReason = $"native_upload_failed:{ex.GetType().Name}";
                _nativeDdsFallbackCount++;
            }
        }
        var bitmap = _textureSet.BitmapForReference(reference);
        if (bitmap is null)
        {
            return D3D11TextureBinding.Empty;
        }
        using var converted = new Bitmap(bitmap.Width, bitmap.Height, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(converted))
        {
            graphics.DrawImageUnscaled(bitmap, 0, 0);
        }
        var rect = new Rectangle(0, 0, converted.Width, converted.Height);
        var data = converted.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        ID3D11Texture2D? texture = null;
        ID3D11ShaderResourceView? view = null;
        try
        {
            var mipCount = EditableMipLevelCount(converted.Width, converted.Height);
            var description = new Texture2DDescription
            {
                Width = (uint)converted.Width,
                Height = (uint)converted.Height,
                MipLevels = (uint)mipCount,
                ArraySize = 1,
                Format = Format.B8G8R8A8_Typeless,
                SampleDescription = new SampleDescription(1, 0),
                Usage = ResourceUsage.Default,
                BindFlags = BindFlags.ShaderResource | BindFlags.RenderTarget,
                MiscFlags = ResourceOptionFlags.GenerateMips,
            };
            texture = _device.CreateTexture2D(description);
            _context!.UpdateSubresource(
                texture,
                0,
                null,
                data.Scan0,
                (uint)data.Stride,
                0);
            var viewFormat = string.Equals(reference.ColorSpace, "srgb", StringComparison.OrdinalIgnoreCase)
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
            _context.GenerateMips(view);
            var entry = new D3D11TextureSrvCacheEntry(
                texture,
                view,
                converted.Width,
                converted.Height,
                EditableMipBytes(converted.Width, converted.Height),
                reference.ResourceId,
                reference.SourceReference,
                reference.Semantic,
                reference.SemanticAuthority,
                Path.GetExtension(reference.Path).TrimStart('.').ToUpperInvariant(),
                1,
                reference.ColorSpace,
                "bitmap_bgra32_generated_mip_chain",
                viewFormat.ToString(),
                mipCount,
                string.IsNullOrWhiteSpace(nativeFallbackReason)
                    ? nativeDds is null ? "native_dds_not_available" : string.Empty
                    : nativeFallbackReason,
                false);
            _textureSrvCache[cacheKey] = entry;
            texture = null;
            view = null;
            _textureSrvCreateCount++;
            _bitmapTextureSrvCreateCount++;
            _textureResidentBytes += entry.EstimatedBytes;
            _peakTextureResidentBytes = Math.Max(_peakTextureResidentBytes, _textureResidentBytes);
            _peakTextureRefreshBytesEstimate = Math.Max(
                _peakTextureRefreshBytesEstimate,
                _textureResidentBytes);
            return new D3D11TextureBinding(entry.View, cacheKey);
        }
        finally
        {
            try
            {
                converted.UnlockBits(data);
            }
            finally
            {
                view?.Dispose();
                texture?.Dispose();
            }
        }
    }

    private unsafe D3D11TextureBinding CreateNativeDdsSrv(
        NetMaterialTextureReference reference,
        NetDdsNativeTextureData nativeDds,
        string cacheKey)
    {
        if (_device is null)
        {
            return D3D11TextureBinding.Empty;
        }
        var useSrgb = nativeDds.SourceSrgb
            || string.Equals(reference.ColorSpace, "srgb", StringComparison.OrdinalIgnoreCase);
        var (resourceFormat, viewFormat) = NativeDdsFormats(nativeDds.FormatKey, useSrgb);
        ID3D11Texture2D? texture = null;
        ID3D11ShaderResourceView? view = null;
        var subresources = new SubresourceData[nativeDds.Subresources.Count];
        fixed (byte* dataPointer = nativeDds.Data)
        {
            for (var index = 0; index < nativeDds.Subresources.Count; index++)
            {
                var subresource = nativeDds.Subresources[index];
                subresources[index] = new SubresourceData(
                    (IntPtr)(dataPointer + subresource.Offset),
                    (uint)subresource.RowPitch,
                    (uint)subresource.SlicePitch);
            }
            var description = new Texture2DDescription
            {
                Width = (uint)nativeDds.Width,
                Height = (uint)nativeDds.Height,
                MipLevels = (uint)nativeDds.MipCount,
                ArraySize = 1,
                Format = resourceFormat,
                SampleDescription = new SampleDescription(1, 0),
                Usage = ResourceUsage.Immutable,
                BindFlags = BindFlags.ShaderResource,
            };
            texture = _device.CreateTexture2D(description, subresources);
        }
        try
        {
            view = _device.CreateShaderResourceView(
                texture,
                new ShaderResourceViewDescription(
                    texture,
                    ShaderResourceViewDimension.Texture2D,
                    viewFormat,
                    0,
                    (uint)nativeDds.MipCount,
                    0,
                    1));
            var entry = new D3D11TextureSrvCacheEntry(
                texture,
                view,
                nativeDds.Width,
                nativeDds.Height,
                nativeDds.Data.LongLength,
                reference.ResourceId,
                reference.SourceReference,
                reference.Semantic,
                reference.SemanticAuthority,
                nativeDds.FormatKey,
                nativeDds.MipCount,
                useSrgb ? "srgb" : "linear",
                "native_dds_mip_chain",
                viewFormat.ToString(),
                nativeDds.MipCount,
                string.Empty,
                true);
            _textureSrvCache[cacheKey] = entry;
            texture = null;
            view = null;
            _textureSrvCreateCount++;
            _nativeDdsSrvCreateCount++;
            _textureResidentBytes += entry.EstimatedBytes;
            _peakTextureResidentBytes = Math.Max(_peakTextureResidentBytes, _textureResidentBytes);
            _peakTextureRefreshBytesEstimate = Math.Max(_peakTextureRefreshBytesEstimate, _textureResidentBytes);
            return new D3D11TextureBinding(entry.View, cacheKey);
        }
        finally
        {
            view?.Dispose();
            texture?.Dispose();
        }
    }

    private static (Format ResourceFormat, Format ViewFormat) NativeDdsFormats(string formatKey, bool useSrgb)
    {
        return formatKey switch
        {
            "BC1" => (Format.BC1_Typeless, useSrgb ? Format.BC1_UNorm_SRgb : Format.BC1_UNorm),
            "BC2" => (Format.BC2_Typeless, useSrgb ? Format.BC2_UNorm_SRgb : Format.BC2_UNorm),
            "BC3" => (Format.BC3_Typeless, useSrgb ? Format.BC3_UNorm_SRgb : Format.BC3_UNorm),
            "BC4_UNORM" => (Format.BC4_Typeless, Format.BC4_UNorm),
            "BC4_SNORM" => (Format.BC4_Typeless, Format.BC4_SNorm),
            "BC5_UNORM" => (Format.BC5_Typeless, Format.BC5_UNorm),
            "BC5_SNORM" => (Format.BC5_Typeless, Format.BC5_SNorm),
            "BC6H_UF16" => (Format.BC6H_Typeless, Format.BC6H_Uf16),
            "BC6H_SF16" => (Format.BC6H_Typeless, Format.BC6H_Sf16),
            "BC7" => (Format.BC7_Typeless, useSrgb ? Format.BC7_UNorm_SRgb : Format.BC7_UNorm),
            "RGBA8" => (Format.R8G8B8A8_Typeless, useSrgb ? Format.R8G8B8A8_UNorm_SRgb : Format.R8G8B8A8_UNorm),
            "BGRA8" => (Format.B8G8R8A8_Typeless, useSrgb ? Format.B8G8R8A8_UNorm_SRgb : Format.B8G8R8A8_UNorm),
            "BGRX8" => (Format.B8G8R8X8_Typeless, useSrgb ? Format.B8G8R8X8_UNorm_SRgb : Format.B8G8R8X8_UNorm),
            "R8" => (Format.R8_UNorm, Format.R8_UNorm),
            "RG8" => (Format.R8G8_UNorm, Format.R8G8_UNorm),
            "R16" => (Format.R16_UNorm, Format.R16_UNorm),
            "RGBA16_FLOAT" => (Format.R16G16B16A16_Float, Format.R16G16B16A16_Float),
            _ => throw new InvalidDataException($"Unsupported native DDS upload format: {formatKey}"),
        };
    }

    public IReadOnlyList<Dictionary<string, object?>> TextureResourceDiagnosticsPayload()
    {
        return _textureSrvCache
            .OrderBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase)
            .Select(pair => new Dictionary<string, object?>
            {
                ["resource_id"] = pair.Value.ResourceId,
                ["source_reference"] = pair.Value.SourceReference,
                ["semantic"] = pair.Value.Semantic,
                ["semantic_authority"] = pair.Value.SemanticAuthority,
                ["source_format"] = pair.Value.SourceFormat,
                ["source_width"] = pair.Value.Width,
                ["source_height"] = pair.Value.Height,
                ["source_mip_count"] = pair.Value.SourceMipCount,
                ["estimated_bytes"] = pair.Value.EstimatedBytes,
                ["color_space"] = pair.Value.ColorSpace,
                ["upload_mode"] = pair.Value.UploadMode,
                ["gpu_format"] = pair.Value.GpuFormat,
                ["gpu_mip_count"] = pair.Value.GpuMipCount,
                ["native_dds"] = pair.Value.NativeDds,
                ["fallback_reason"] = pair.Value.FallbackReason,
            })
            .ToArray();
    }

    private void PruneTextureCacheToActiveBindings()
    {
        PruneEditableTextureRegions();
        var activeKeys = _batches
            .SelectMany(batch => batch.Materials.CacheKeys)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        foreach (var cacheKey in _textureSrvCache.Keys.Where(key => !activeKeys.Contains(key)).ToArray())
        {
            if (DisposeTextureCacheEntry(cacheKey))
            {
                _supersededTextureSrvPruneCount++;
            }
        }
    }

    private void ClearTextureCache()
    {
        ClearEditableTextureRegions();
        foreach (var entry in _textureSrvCache.Values)
        {
            _maxDisposedTextureResourceLifetimeMs = Math.Max(
                _maxDisposedTextureResourceLifetimeMs,
                ElapsedMilliseconds(entry.CreatedTimestamp));
            entry.View.Dispose();
            entry.Texture.Dispose();
            _textureSrvDisposeCount++;
        }
        _textureSrvCache.Clear();
        _textureResidentBytes = 0;
    }

    private bool DisposeTextureCacheEntry(string cacheKey)
    {
        if (!_textureSrvCache.TryGetValue(cacheKey, out var entry))
        {
            return false;
        }
        _maxDisposedTextureResourceLifetimeMs = Math.Max(
            _maxDisposedTextureResourceLifetimeMs,
            ElapsedMilliseconds(entry.CreatedTimestamp));
        try
        {
            entry.View.Dispose();
            entry.Texture.Dispose();
        }
        catch
        {
            return false;
        }
        _textureSrvCache.Remove(cacheKey);
        _textureSrvDisposeCount++;
        _textureResidentBytes = Math.Max(0, _textureResidentBytes - entry.EstimatedBytes);
        return true;
    }

    private void DiscardTextureResourceRefreshState()
    {
        _textureResourceRefreshActive = false;
        _materialResourcesDirty = false;
    }
}

internal sealed class D3D11MaterialResources : IDisposable
{
    public D3D11MaterialResources(
        ID3D11ShaderResourceView? baseTexture,
        ID3D11ShaderResourceView? normal,
        ID3D11ShaderResourceView? specular,
        ID3D11ShaderResourceView? roughness,
        ID3D11ShaderResourceView? metallic,
        ID3D11ShaderResourceView? height,
        ID3D11ShaderResourceView? emissive,
        ID3D11ShaderResourceView? layerMask,
        ID3D11ShaderResourceView? opacity,
        ID3D11ShaderResourceView? occlusion,
        IReadOnlySet<string> cacheKeys)
    {
        Base = baseTexture;
        Normal = normal;
        Specular = specular;
        Roughness = roughness;
        Metallic = metallic;
        Height = height;
        Emissive = emissive;
        LayerMask = layerMask;
        Opacity = opacity;
        Occlusion = occlusion;
        ShaderResources = new[] { Base, Normal, Specular, Roughness, Metallic, Height, Emissive, LayerMask, Opacity, Occlusion };
        CacheKeys = cacheKeys;
    }

    public ID3D11ShaderResourceView? Base { get; }
    public ID3D11ShaderResourceView? Normal { get; }
    public ID3D11ShaderResourceView? Specular { get; }
    public ID3D11ShaderResourceView? Roughness { get; }
    public ID3D11ShaderResourceView? Metallic { get; }
    public ID3D11ShaderResourceView? Height { get; }
    public ID3D11ShaderResourceView? Emissive { get; }
    public ID3D11ShaderResourceView? LayerMask { get; }
    public ID3D11ShaderResourceView? Opacity { get; }
    public ID3D11ShaderResourceView? Occlusion { get; }
    public ID3D11ShaderResourceView?[] ShaderResources { get; }
    public IReadOnlySet<string> CacheKeys { get; }

    public D3D11MaterialResources WithShaderResource(int index, ID3D11ShaderResourceView view)
    {
        var resources = ShaderResources.ToArray();
        resources[index] = view;
        return new D3D11MaterialResources(
            resources[0], resources[1], resources[2], resources[3],
            resources[4], resources[5], resources[6], resources[7],
            resources[8], resources[9], CacheKeys);
    }

    public void Dispose()
    {
        // SRVs are device-scoped and shared by D3D11MaterialViewport's texture cache.
    }
}

internal readonly record struct D3D11TextureBinding(ID3D11ShaderResourceView? View, string CacheKey)
{
    public static D3D11TextureBinding Empty { get; } = new(null, string.Empty);
}

internal sealed record D3D11TextureSrvCacheEntry(
    ID3D11Texture2D Texture,
    ID3D11ShaderResourceView View,
    int Width,
    int Height,
    long EstimatedBytes,
    string ResourceId,
    string SourceReference,
    string Semantic,
    string SemanticAuthority,
    string SourceFormat,
    int SourceMipCount,
    string ColorSpace,
    string UploadMode,
    string GpuFormat,
    int GpuMipCount,
    string FallbackReason,
    bool NativeDds,
    long CreatedTimestamp)
{
    public D3D11TextureSrvCacheEntry(
        ID3D11Texture2D texture,
        ID3D11ShaderResourceView view,
        int width,
        int height,
        long estimatedBytes,
        string resourceId,
        string sourceReference,
        string semantic,
        string semanticAuthority,
        string sourceFormat,
        int sourceMipCount,
        string colorSpace,
        string uploadMode,
        string gpuFormat,
        int gpuMipCount,
        string fallbackReason,
        bool nativeDds)
        : this(
            texture,
            view,
            width,
            height,
            estimatedBytes,
            resourceId,
            sourceReference,
            semantic,
            semanticAuthority,
            sourceFormat,
            sourceMipCount,
            colorSpace,
            uploadMode,
            gpuFormat,
            gpuMipCount,
            fallbackReason,
            nativeDds,
            Stopwatch.GetTimestamp())
    {
    }
}
