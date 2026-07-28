using System.Security.Cryptography;
using System.Text;
using System.Globalization;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class NetTextureSet
{
    private long _materialLayerCompositeCount;

    public long MaterialLayerCompositeCount
    {
        get { lock (_gate) return _materialLayerCompositeCount; }
    }

    // Composited roughness/metal for a submesh whose surface response exists only
    // per colour layer. Returns Empty when the submesh binds its own surface map,
    // which stays authoritative, or when no layer carries one.
    public NetMaterialTextureReference SynthesizedSurfaceReferenceForSubmesh(
        NetMaterialSet materials,
        int submeshIndex)
    {
        if (!materials.TextureReferenceForSubmesh(submeshIndex, "roughness").IsEmpty
            || !materials.TextureReferenceForSubmesh(submeshIndex, "metallic").IsEmpty)
        {
            return NetMaterialTextureReference.Empty;
        }
        var layers = materials.MaterialLayersForSubmesh(submeshIndex);
        if (!layers.Any(layer => !string.IsNullOrWhiteSpace(layer.MaterialResourceId)))
        {
            return NetMaterialTextureReference.Empty;
        }

        var layerReferences = layers.Select(layer => (
            Binding: layer,
            Material: materials.TextureReferenceForResource(
                layer.MaterialResourceId,
                "layer_material",
                "linear"),
            Mask: materials.TextureReferenceForResource(
                layer.MaskResourceId,
                "layer_mask",
                "linear")))
            .ToArray();
        var signatureText = string.Join(
            "|",
            materials.Signature,
            submeshIndex,
            "surface",
            string.Join(";", layerReferences.Select(item => string.Join(
                ",",
                item.Binding.LayerRole,
                item.Binding.MaskChannel,
                item.Binding.Weight.ToString("R", CultureInfo.InvariantCulture),
                item.Binding.MaterialResourceId,
                item.Binding.MaskResourceId,
                item.Material.SourceCacheKey,
                item.Mask.SourceCacheKey))));
        var fingerprint = "managed-surface-layer-" + Convert.ToHexString(
            SHA256.HashData(Encoding.UTF8.GetBytes(signatureText))).ToLowerInvariant();
        var resourceId = $"material-surface-layer:{fingerprint}";
        var path = layerReferences
            .Select(item => item.Material)
            .FirstOrDefault(reference => !reference.IsEmpty).Path;
        if (string.IsNullOrWhiteSpace(path))
        {
            return NetMaterialTextureReference.Empty;
        }
        var reference = new NetMaterialTextureReference(
            resourceId,
            path,
            fingerprint,
            "roughness",
            "linear",
            path,
            "archive_lite_managed_surface_layer_compiler_v1");

        lock (_gate)
        {
            if (_decodedByFingerprint.ContainsKey(reference.SourceCacheKey))
            {
                return reference;
            }
            var sources = new List<NetMaterialLayerSurfaceSource>();
            foreach (var item in layerReferences)
            {
                if (item.Material.IsEmpty)
                {
                    continue;
                }
                var material = BitmapForReference(item.Material);
                if (material is null)
                {
                    continue;
                }
                var mask = item.Mask.IsEmpty ? null : BitmapForReference(item.Mask);
                if (!string.IsNullOrWhiteSpace(item.Binding.MaskResourceId) && mask is null)
                {
                    continue;
                }
                sources.Add(new NetMaterialLayerSurfaceSource(item.Binding, material, mask));
            }
            if (sources.Count == 0)
            {
                return NetMaterialTextureReference.Empty;
            }
            var compiled = NetMaterialLayerCompiler.CompileSurface(null, sources);
            if (compiled is null)
            {
                return NetMaterialTextureReference.Empty;
            }
            _decodedByFingerprint[reference.SourceCacheKey] = compiled;
            _lastGoodResourceKeys[resourceId] = reference.SourceCacheKey;
            _materialLayerCompositeCount++;
            return reference;
        }
    }

    public NetMaterialTextureReference SynthesizedBaseReferenceForSubmesh(
        NetMaterialSet materials,
        int submeshIndex)
    {
        var layers = materials.MaterialLayersForSubmesh(submeshIndex);
        if (layers.Count == 0 || !layers.Any(layer =>
            !string.Equals(layer.LayerRole, "base", StringComparison.OrdinalIgnoreCase)))
        {
            return NetMaterialTextureReference.Empty;
        }

        var baseReference = materials.TextureReferenceForSubmesh(submeshIndex, "base", "albedo", "diffuse");
        var layerReferences = layers.Select(layer => (
            Binding: layer,
            Diffuse: materials.TextureReferenceForResource(
                layer.DiffuseResourceId,
                "layer_diffuse",
                "srgb"),
            Mask: materials.TextureReferenceForResource(
                layer.MaskResourceId,
                "layer_mask",
                "linear")))
            .ToArray();
        var signatureText = string.Join(
            "|",
            materials.Signature,
            submeshIndex,
            baseReference.SourceCacheKey,
            string.Join(";", layerReferences.Select(item => string.Join(
                ",",
                item.Binding.LayerRole,
                item.Binding.MaskChannel,
                item.Binding.Weight.ToString("R", CultureInfo.InvariantCulture),
                item.Binding.TintR.ToString("R", CultureInfo.InvariantCulture),
                item.Binding.TintG.ToString("R", CultureInfo.InvariantCulture),
                item.Binding.TintB.ToString("R", CultureInfo.InvariantCulture),
                item.Binding.DiffuseResourceId,
                item.Binding.MaskResourceId,
                item.Diffuse.SourceCacheKey,
                item.Mask.SourceCacheKey))));
        var fingerprint = "managed-layer-" + Convert.ToHexString(
            SHA256.HashData(Encoding.UTF8.GetBytes(signatureText))).ToLowerInvariant();
        var resourceId = $"material-layer:{fingerprint}";
        var path = baseReference.IsEmpty
            ? layerReferences.Select(item => item.Diffuse)
                .FirstOrDefault(reference => !reference.IsEmpty).Path
            : baseReference.Path;
        if (string.IsNullOrWhiteSpace(path))
        {
            return NetMaterialTextureReference.Empty;
        }
        var reference = new NetMaterialTextureReference(
            resourceId,
            path,
            fingerprint,
            "base",
            "srgb",
            path,
            "archive_lite_managed_albedo_layer_compiler_v1");

        lock (_gate)
        {
            if (_decodedByFingerprint.ContainsKey(reference.SourceCacheKey))
            {
                return reference;
            }
            var baseBitmap = baseReference.IsEmpty ? null : BitmapForReference(baseReference);
            var sources = new List<NetMaterialLayerSource>();
            foreach (var item in layerReferences)
            {
                var layer = item.Binding;
                var diffuse = BitmapForReference(item.Diffuse);
                if (diffuse is null)
                {
                    continue;
                }
                var mask = item.Mask.IsEmpty ? null : BitmapForReference(item.Mask);
                if (!string.IsNullOrWhiteSpace(layer.MaskResourceId) && mask is null)
                {
                    continue;
                }
                sources.Add(new NetMaterialLayerSource(layer, diffuse, mask));
            }
            if (!sources.Any(source =>
                !string.Equals(source.Binding.LayerRole, "base", StringComparison.OrdinalIgnoreCase)))
            {
                return NetMaterialTextureReference.Empty;
            }
            var compiled = NetMaterialLayerCompiler.Compile(baseBitmap, sources);
            if (compiled is null)
            {
                return NetMaterialTextureReference.Empty;
            }
            _decodedByFingerprint[reference.SourceCacheKey] = compiled;
            _lastGoodResourceKeys[resourceId] = reference.SourceCacheKey;
            _materialLayerCompositeCount++;
            return reference;
        }
    }
}
