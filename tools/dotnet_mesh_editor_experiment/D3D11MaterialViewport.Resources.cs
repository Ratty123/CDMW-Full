using System.Diagnostics;
using System.Drawing.Imaging;
using System.IO;
using Vortice.Direct3D11;
using Vortice.DXGI;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private static readonly ID3D11ShaderResourceView?[] EmptyMaterialShaderResources = new ID3D11ShaderResourceView?[7];
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
    private long _textureResidentBytes;
    private long _peakTextureResidentBytes;
    private long _peakTextureRefreshBytesEstimate;
    private double _maxDisposedTextureResourceLifetimeMs;

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
        var specular = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "specular", "material"));
        var roughness = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "roughness", "material"));
        var metallic = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "metallic", "material"));
        var height = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "height"));
        var emissive = CreateTextureSrv(_materials.TextureReferenceForSubmesh(submeshIndex, "emissive"));
        var resources = new D3D11MaterialResources(
            baseTexture.View,
            normal.View,
            specular.View,
            roughness.View,
            metallic.View,
            height.View,
            emissive.View,
            new[] { baseTexture.CacheKey, normal.CacheKey, specular.CacheKey, roughness.CacheKey, metallic.CacheKey, height.CacheKey, emissive.CacheKey }
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
        try
        {
            var description = new Texture2DDescription
            {
                Width = (uint)converted.Width,
                Height = (uint)converted.Height,
                MipLevels = 1,
                ArraySize = 1,
                Format = Format.B8G8R8A8_UNorm,
                SampleDescription = new SampleDescription(1, 0),
                Usage = ResourceUsage.Immutable,
                BindFlags = BindFlags.ShaderResource,
            };
            var texture = _device.CreateTexture2D(description, new[] { new SubresourceData(data.Scan0, (uint)data.Stride) });
            ID3D11ShaderResourceView view;
            try
            {
                view = _device.CreateShaderResourceView(texture);
            }
            catch
            {
                texture.Dispose();
                throw;
            }
            var estimatedBytes = checked((long)converted.Width * converted.Height * 4);
            _textureSrvCache[cacheKey] = new D3D11TextureSrvCacheEntry(texture, view, converted.Width, converted.Height, estimatedBytes);
            _textureSrvCreateCount++;
            _textureResidentBytes += estimatedBytes;
            _peakTextureResidentBytes = Math.Max(_peakTextureResidentBytes, _textureResidentBytes);
            _peakTextureRefreshBytesEstimate = Math.Max(
                _peakTextureRefreshBytesEstimate,
                _textureResidentBytes);
            return new D3D11TextureBinding(view, cacheKey);
        }
        finally
        {
            converted.UnlockBits(data);
        }
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
        IReadOnlySet<string> cacheKeys)
    {
        Base = baseTexture;
        Normal = normal;
        Specular = specular;
        Roughness = roughness;
        Metallic = metallic;
        Height = height;
        Emissive = emissive;
        ShaderResources = new[] { Base, Normal, Specular, Roughness, Metallic, Height, Emissive };
        CacheKeys = cacheKeys;
    }

    public ID3D11ShaderResourceView? Base { get; }
    public ID3D11ShaderResourceView? Normal { get; }
    public ID3D11ShaderResourceView? Specular { get; }
    public ID3D11ShaderResourceView? Roughness { get; }
    public ID3D11ShaderResourceView? Metallic { get; }
    public ID3D11ShaderResourceView? Height { get; }
    public ID3D11ShaderResourceView? Emissive { get; }
    public ID3D11ShaderResourceView?[] ShaderResources { get; }
    public IReadOnlySet<string> CacheKeys { get; }

    public D3D11MaterialResources WithShaderResource(int index, ID3D11ShaderResourceView view)
    {
        var resources = ShaderResources.ToArray();
        resources[index] = view;
        return new D3D11MaterialResources(
            resources[0], resources[1], resources[2], resources[3],
            resources[4], resources[5], resources[6], CacheKeys);
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
    long CreatedTimestamp)
{
    public D3D11TextureSrvCacheEntry(ID3D11Texture2D texture, ID3D11ShaderResourceView view, int width, int height, long estimatedBytes)
        : this(texture, view, width, height, estimatedBytes, Stopwatch.GetTimestamp())
    {
    }
}
