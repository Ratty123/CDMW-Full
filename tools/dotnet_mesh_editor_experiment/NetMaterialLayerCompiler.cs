using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed record NetMaterialLayerSource(
    NetMaterialLayerBinding Binding,
    Bitmap Diffuse,
    Bitmap? Mask);

internal sealed record NetMaterialLayerSurfaceSource(
    NetMaterialLayerBinding Binding,
    Bitmap Material,
    Bitmap? Mask);

internal static class NetMaterialLayerCompiler
{
    // Preserve the highest authored skin/armour maps used by the real PAC
    // material graphs.  The previous 1024 cap reduced 2048 body surface maps
    // before Rust ever received them, while still leaving the original albedo
    // and normal maps at 2048 and making the response look visibly softer.
    private const int MaximumDimension = 2048;

    public static Bitmap? Compile(Bitmap? baseBitmap, IReadOnlyList<NetMaterialLayerSource> layers)
    {
        var firstLayer = layers.FirstOrDefault(layer => layer.Diffuse.Width > 0 && layer.Diffuse.Height > 0);
        var source = baseBitmap ?? firstLayer?.Diffuse;
        if (source is null || source.Width <= 0 || source.Height <= 0)
        {
            return null;
        }

        var layerSeed = baseBitmap is null ? firstLayer : null;
        var (width, height) = OutputSize(
            baseBitmap,
            ColorSizingSources(layers, layerSeed));
        var target = ScaleToBgra(source, width, height);
        var targetPixels = ReadBgra(target);
        ApplyColorSeedPalette(targetPixels, width, height, layers);
        if (layerSeed is not null)
        {
            ApplyTint(targetPixels, layerSeed.Binding);
        }
        foreach (var layer in layers)
        {
            if (string.Equals(layer.Binding.LayerRole, "base", StringComparison.OrdinalIgnoreCase)
                || string.Equals(layer.Binding.LayerRole, "color_seed", StringComparison.OrdinalIgnoreCase)
                || ReferenceEquals(layer, layerSeed)
                || layer.Binding.Weight <= 0.001f)
            {
                continue;
            }
            using var diffuse = ScaleToBgra(layer.Diffuse, width, height);
            using var mask = layer.Mask is null ? null : ScaleToBgra(layer.Mask, width, height);
            var diffusePixels = ReadBgra(diffuse);
            var maskPixels = mask is null ? null : ReadBgra(mask);
            var maskOffset = LayerChannelOffset(layer.Binding.MaskChannel);
            var weight = Math.Clamp(layer.Binding.Weight, 0.0f, 1.0f);
            var tintB = Math.Clamp(layer.Binding.TintB, 0.0f, 2.0f);
            var tintG = Math.Clamp(layer.Binding.TintG, 0.0f, 2.0f);
            var tintR = Math.Clamp(layer.Binding.TintR, 0.0f, 2.0f);
            for (var offset = 0; offset < targetPixels.Length; offset += 4)
            {
                var alpha = weight * (maskPixels is null ? 1.0f : maskPixels[offset + maskOffset] / 255.0f);
                if (alpha <= 0.0001f)
                {
                    continue;
                }
                targetPixels[offset] = Blend(targetPixels[offset], diffusePixels[offset] * tintB, alpha);
                targetPixels[offset + 1] = Blend(targetPixels[offset + 1], diffusePixels[offset + 1] * tintG, alpha);
                targetPixels[offset + 2] = Blend(targetPixels[offset + 2], diffusePixels[offset + 2] * tintR, alpha);
            }
        }
        WriteBgra(target, targetPixels);
        return target;
    }

    private static bool ApplyColorSeedPalette(
        byte[] targetPixels,
        int width,
        int height,
        IReadOnlyList<NetMaterialLayerSource> layers)
    {
        var seeds = layers
            .Where(layer => string.Equals(
                layer.Binding.LayerRole,
                "color_seed",
                StringComparison.OrdinalIgnoreCase))
            .ToArray();
        var red = seeds.FirstOrDefault(layer => string.Equals(layer.Binding.MaskChannel, "r", StringComparison.OrdinalIgnoreCase));
        var green = seeds.FirstOrDefault(layer => string.Equals(layer.Binding.MaskChannel, "g", StringComparison.OrdinalIgnoreCase));
        var blue = seeds.FirstOrDefault(layer => string.Equals(layer.Binding.MaskChannel, "b", StringComparison.OrdinalIgnoreCase));
        if (red?.Mask is null || green?.Mask is null || blue?.Mask is null
            || !string.Equals(red.Binding.MaskResourceId, green.Binding.MaskResourceId, StringComparison.OrdinalIgnoreCase)
            || !string.Equals(red.Binding.MaskResourceId, blue.Binding.MaskResourceId, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        using var selector = ScaleToBgra(red.Mask, width, height);
        var selectorPixels = ReadBgra(selector);
        var palette = new[] { red.Binding, green.Binding, blue.Binding };
        var referenceLumas = SelectorReferenceLumas(targetPixels, selectorPixels);
        for (var offset = 0; offset < targetPixels.Length; offset += 4)
        {
            var redWeight = selectorPixels[offset + 2] / 255.0f;
            var greenWeight = selectorPixels[offset + 1] / 255.0f;
            var blueWeight = selectorPixels[offset] / 255.0f;
            var total = redWeight + greenWeight + blueWeight;
            if (total <= 0.001f)
            {
                continue;
            }
            var coverage = Math.Clamp(total, 0.0f, 1.0f);
            var sourceLuma = PixelLuma(targetPixels, offset);
            var referenceLuma = (
                referenceLumas[0] * redWeight
                + referenceLumas[1] * greenWeight
                + referenceLumas[2] * blueWeight) / total;
            // The RGB selector supplies hue regions, not a replacement for the
            // authored fabric/metal value map.  Replacing every selected texel
            // with the palette constant erased seams, wear and weave, then the
            // lit pass had one flat value to lift into a blown-looking panel.
            // Preserve the source's local luminance around the mean of the
            // selector channel while bounding the modulation so a bright stitch
            // cannot clip a pale dye before the renderer sees it.
            var detailScale = Math.Clamp(
                sourceLuma / Math.Max(referenceLuma, 1.0f / 255.0f),
                0.55f,
                1.25f);
            var seededR = 255.0f * (
                palette[0].TintR * redWeight
                + palette[1].TintR * greenWeight
                + palette[2].TintR * blueWeight) / total * detailScale;
            var seededG = 255.0f * (
                palette[0].TintG * redWeight
                + palette[1].TintG * greenWeight
                + palette[2].TintG * blueWeight) / total * detailScale;
            var seededB = 255.0f * (
                palette[0].TintB * redWeight
                + palette[1].TintB * greenWeight
                + palette[2].TintB * blueWeight) / total * detailScale;
            targetPixels[offset] = Blend(targetPixels[offset], seededB, coverage);
            targetPixels[offset + 1] = Blend(targetPixels[offset + 1], seededG, coverage);
            targetPixels[offset + 2] = Blend(targetPixels[offset + 2], seededR, coverage);
        }
        return true;
    }

    private static float[] SelectorReferenceLumas(byte[] targetPixels, byte[] selectorPixels)
    {
        var weightedLumas = new double[3];
        var weightTotals = new double[3];
        double visibleLuma = 0.0;
        var visibleCount = 0;
        for (var offset = 0; offset < targetPixels.Length; offset += 4)
        {
            var luma = PixelLuma(targetPixels, offset);
            if (luma <= 1.0f / 255.0f)
            {
                continue;
            }
            visibleLuma += luma;
            visibleCount++;
            var weights = new[]
            {
                selectorPixels[offset + 2] / 255.0,
                selectorPixels[offset + 1] / 255.0,
                selectorPixels[offset] / 255.0,
            };
            for (var channel = 0; channel < weights.Length; channel++)
            {
                weightedLumas[channel] += luma * weights[channel];
                weightTotals[channel] += weights[channel];
            }
        }
        var fallback = visibleCount > 0 ? visibleLuma / visibleCount : 0.5;
        return Enumerable.Range(0, 3)
            .Select(channel => QuantizeReferenceLuma(
                weightTotals[channel] > 0.001
                    ? weightedLumas[channel] / weightTotals[channel]
                    : fallback))
            .ToArray();
    }

    private static float PixelLuma(byte[] pixels, int offset) =>
        (float)(
            (pixels[offset + 2] / 255.0) * 0.2126
            + (pixels[offset + 1] / 255.0) * 0.7152
            + (pixels[offset] / 255.0) * 0.0722);

    private static float QuantizeReferenceLuma(double value) =>
        (float)(Math.Round(Math.Clamp(value, 1.0 / 255.0, 1.0) * 4096.0) / 4096.0);

    // The surface companion of Compile. Crimson gives every colour layer its own
    // packed surface map, and the mask that chooses which layer's colour owns a
    // texel chooses that layer's roughness and metal too. Compositing through the
    // same mask keeps the two in step; averaging the layers instead would pin the
    // whole surface near one constant and describe no material that is present.
    //
    // No tint is applied: a tint recolours albedo, and multiplying it into a
    // roughness or metal channel would invent surface properties the source
    // never authored.
    public static Bitmap? CompileSurface(
        Bitmap? baseMaterial,
        IReadOnlyList<NetMaterialLayerSurfaceSource> layers)
    {
        var firstLayer = layers.FirstOrDefault(layer => layer.Material.Width > 0 && layer.Material.Height > 0);
        var source = baseMaterial ?? firstLayer?.Material;
        if (source is null || source.Width <= 0 || source.Height <= 0)
        {
            return null;
        }

        var layerSeed = baseMaterial is null ? firstLayer : null;
        var (width, height) = OutputSize(
            baseMaterial,
            SurfaceSizingSources(layers, layerSeed));
        var target = ScaleToBgra(source, width, height);
        var targetPixels = ReadBgra(target);
        foreach (var layer in layers)
        {
            if (string.Equals(layer.Binding.LayerRole, "base", StringComparison.OrdinalIgnoreCase)
                || ReferenceEquals(layer, layerSeed)
                || layer.Binding.Weight <= 0.001f)
            {
                continue;
            }
            using var material = ScaleToBgra(layer.Material, width, height);
            using var mask = layer.Mask is null ? null : ScaleToBgra(layer.Mask, width, height);
            var materialPixels = ReadBgra(material);
            var maskPixels = mask is null ? null : ReadBgra(mask);
            var maskOffset = LayerChannelOffset(layer.Binding.MaskChannel);
            var weight = Math.Clamp(layer.Binding.Weight, 0.0f, 1.0f);
            for (var offset = 0; offset < targetPixels.Length; offset += 4)
            {
                var alpha = weight * (maskPixels is null ? 1.0f : maskPixels[offset + maskOffset] / 255.0f);
                if (alpha <= 0.0001f)
                {
                    continue;
                }
                targetPixels[offset] = Blend(targetPixels[offset], materialPixels[offset], alpha);
                targetPixels[offset + 1] = Blend(targetPixels[offset + 1], materialPixels[offset + 1], alpha);
                targetPixels[offset + 2] = Blend(targetPixels[offset + 2], materialPixels[offset + 2], alpha);
            }
        }
        WriteBgra(target, targetPixels);
        return target;
    }

    private static void ApplyTint(byte[] pixels, NetMaterialLayerBinding binding)
    {
        var tintB = Math.Clamp(binding.TintB, 0.0f, 2.0f);
        var tintG = Math.Clamp(binding.TintG, 0.0f, 2.0f);
        var tintR = Math.Clamp(binding.TintR, 0.0f, 2.0f);
        for (var offset = 0; offset < pixels.Length; offset += 4)
        {
            pixels[offset] = Scale(pixels[offset], tintB);
            pixels[offset + 1] = Scale(pixels[offset + 1], tintG);
            pixels[offset + 2] = Scale(pixels[offset + 2], tintR);
        }
    }

    private static byte Scale(byte value, float factor) => (byte)Math.Clamp(
        (int)Math.Round(value * factor),
        0,
        255);

    public static bool PreservesSourceOrientation()
    {
        using var baseBitmap = new Bitmap(4, 4, PixelFormat.Format32bppArgb);
        using var overlay = new Bitmap(4, 4, PixelFormat.Format32bppArgb);
        using var mask = new Bitmap(4, 4, PixelFormat.Format32bppArgb);
        using (var baseGraphics = Graphics.FromImage(baseBitmap)) baseGraphics.Clear(Color.Blue);
        using (var overlayGraphics = Graphics.FromImage(overlay)) overlayGraphics.Clear(Color.Red);
        for (var y = 0; y < 4; y++)
        {
            for (var x = 0; x < 4; x++)
            {
                mask.SetPixel(x, y, y < 2 ? Color.White : Color.Black);
            }
        }
        var binding = new NetMaterialLayerBinding("detail", "r", 1.0f, 1.0f, 1.0f, 1.0f, "overlay", "mask");
        using var compiled = Compile(baseBitmap, new[] { new NetMaterialLayerSource(binding, overlay, mask) });
        return compiled is not null
            && compiled.GetPixel(1, 0).R > 220
            && compiled.GetPixel(1, 0).B < 35
            && compiled.GetPixel(1, 3).B > 220
            && compiled.GetPixel(1, 3).R < 35;
    }

    // Surface layers must follow the mask that selects their colour, and must not
    // take the layer tint: a tint recolours albedo, and folding it into roughness
    // or metal would invent surface properties the source never authored.
    public static bool CompositesSurfaceThroughMask()
    {
        using var seed = new Bitmap(4, 4, PixelFormat.Format32bppArgb);
        using var overlay = new Bitmap(4, 4, PixelFormat.Format32bppArgb);
        using var mask = new Bitmap(4, 4, PixelFormat.Format32bppArgb);
        // Seed reads roughness 1.0 / metal 0.0; the overlay reads the opposite.
        using (var seedGraphics = Graphics.FromImage(seed)) seedGraphics.Clear(Color.FromArgb(255, 0, 255, 0));
        using (var overlayGraphics = Graphics.FromImage(overlay)) overlayGraphics.Clear(Color.FromArgb(255, 0, 0, 255));
        for (var y = 0; y < 4; y++)
        {
            for (var x = 0; x < 4; x++)
            {
                mask.SetPixel(x, y, y < 2 ? Color.White : Color.Black);
            }
        }
        var seedBinding = new NetMaterialLayerBinding("base", "r", 1.0f, 1.0f, 1.0f, 1.0f, "", "", "seed");
        // A saturated tint that must leave no trace in the composite.
        var overlayBinding = new NetMaterialLayerBinding("detail", "r", 1.0f, 0.0f, 0.0f, 2.0f, "", "mask", "overlay");
        using var compiled = CompileSurface(
            seed,
            new[]
            {
                new NetMaterialLayerSurfaceSource(seedBinding, seed, null),
                new NetMaterialLayerSurfaceSource(overlayBinding, overlay, mask),
            });
        if (compiled is null)
        {
            return false;
        }
        var covered = compiled.GetPixel(1, 0);
        var uncovered = compiled.GetPixel(1, 3);
        return covered.B > 220 && covered.G < 35
            && uncovered.G > 220 && uncovered.B < 35;
    }

    public static bool CompositesColorPaletteThroughSelector()
    {
        using var baseBitmap = new Bitmap(8, 1, PixelFormat.Format32bppArgb);
        using var diffuse = new Bitmap(8, 1, PixelFormat.Format32bppArgb);
        using var selector = new Bitmap(8, 1, PixelFormat.Format32bppArgb);
        for (var x = 0; x < baseBitmap.Width; x++)
        {
            var value = x % 2 == 0 ? 48 : 96;
            baseBitmap.SetPixel(x, 0, Color.FromArgb(255, value, value, value));
        }
        using (var diffuseGraphics = Graphics.FromImage(diffuse)) diffuseGraphics.Clear(Color.White);
        selector.SetPixel(0, 0, Color.Red);
        selector.SetPixel(1, 0, Color.Red);
        selector.SetPixel(2, 0, Color.FromArgb(255, 0, 255, 0));
        selector.SetPixel(3, 0, Color.FromArgb(255, 0, 255, 0));
        selector.SetPixel(4, 0, Color.Blue);
        selector.SetPixel(5, 0, Color.Blue);
        selector.SetPixel(6, 0, Color.FromArgb(255, 128, 128, 0));
        selector.SetPixel(7, 0, Color.FromArgb(255, 128, 128, 0));
        var red = new NetMaterialLayerBinding("color_seed", "r", 1.0f, 0.18f, 0.40f, 0.25f, "base", "selector");
        var green = new NetMaterialLayerBinding("color_seed", "g", 1.0f, 0.76f, 0.58f, 0.40f, "base", "selector");
        var blue = new NetMaterialLayerBinding("color_seed", "b", 1.0f, 0.79f, 0.79f, 0.79f, "base", "selector");
        using var compiled = Compile(
            baseBitmap,
            new[]
            {
                new NetMaterialLayerSource(red, diffuse, selector),
                new NetMaterialLayerSource(green, diffuse, selector),
                new NetMaterialLayerSource(blue, diffuse, selector),
            });
        if (compiled is null)
        {
            return false;
        }
        var redPixel = compiled.GetPixel(0, 0);
        var redHighlight = compiled.GetPixel(1, 0);
        var greenPixel = compiled.GetPixel(2, 0);
        var greenHighlight = compiled.GetPixel(3, 0);
        var bluePixel = compiled.GetPixel(4, 0);
        var blueHighlight = compiled.GetPixel(5, 0);
        var mixedPixel = compiled.GetPixel(6, 0);
        var mixedHighlight = compiled.GetPixel(7, 0);
        return redPixel.G > redPixel.R + 20 && redPixel.G > redPixel.B + 15
            && greenPixel.R > greenPixel.B + 30 && greenPixel.G > greenPixel.B + 20
            && Math.Max(bluePixel.R, Math.Max(bluePixel.G, bluePixel.B))
                - Math.Min(bluePixel.R, Math.Min(bluePixel.G, bluePixel.B)) <= 2
            && Math.Abs(mixedPixel.R - mixedPixel.G) <= 10
            && mixedPixel.R > mixedPixel.B + 20
            && redHighlight.G > redPixel.G + 30
            && greenHighlight.R > greenPixel.R + 30
            && blueHighlight.B > bluePixel.B + 30
            && mixedHighlight.R > mixedPixel.R + 30
            && new[] { redHighlight, greenHighlight, blueHighlight, mixedHighlight }
                .All(color => Math.Max(color.R, Math.Max(color.G, color.B)) < 254);
    }

    public static Dictionary<string, object?> BoundedSourceSizingProof()
    {
        var binding = new NetMaterialLayerBinding(
            "detail", "r", 1.0f, 1.0f, 1.0f, 1.0f, "detail", "");
        using var seed64 = new Bitmap(64, 64, PixelFormat.Format32bppArgb);
        using var detail512 = new Bitmap(512, 512, PixelFormat.Format32bppArgb);
        using var promoted = CompileSurface(
            seed64,
            new[] { new NetMaterialLayerSurfaceSource(binding, detail512, null) });
        using var colorPromoted = Compile(
            seed64,
            new[] { new NetMaterialLayerSource(binding, detail512, null) });

        using var detail2048 = new Bitmap(2048, 1024, PixelFormat.Format32bppArgb);
        using var capped = CompileSurface(
            null,
            new[] { new NetMaterialLayerSurfaceSource(binding, detail2048, null) });

        using var detail4096 = new Bitmap(4096, 1024, PixelFormat.Format32bppArgb);
        using var bounded = CompileSurface(
            null,
            new[] { new NetMaterialLayerSurfaceSource(binding, detail4096, null) });

        using var detail800x400 = new Bitmap(800, 400, PixelFormat.Format32bppArgb);
        using var aspect = CompileSurface(
            null,
            new[] { new NetMaterialLayerSurfaceSource(binding, detail800x400, null) });

        using var baseTie = new Bitmap(512, 256, PixelFormat.Format32bppArgb);
        using var layerTie = new Bitmap(256, 512, PixelFormat.Format32bppArgb);
        using var tied = CompileSurface(
            baseTie,
            new[] { new NetMaterialLayerSurfaceSource(binding, layerTie, null) });

        using var base256 = new Bitmap(256, 256, PixelFormat.Format32bppArgb);
        using var detail256 = new Bitmap(256, 256, PixelFormat.Format32bppArgb);
        using var mask512 = new Bitmap(512, 512, PixelFormat.Format32bppArgb);
        using var colorMaskPromoted = Compile(
            base256,
            new[] { new NetMaterialLayerSource(binding, detail256, mask512) });
        using var surfaceMaskPromoted = CompileSurface(
            base256,
            new[] { new NetMaterialLayerSurfaceSource(binding, detail256, mask512) });

        var gates = new Dictionary<string, bool>
        {
            ["small_seed_uses_512_detail_resolution"] = promoted is not null
                && promoted.Width == 512 && promoted.Height == 512,
            ["colour_compiler_uses_512_detail_resolution"] = colorPromoted is not null
                && colorPromoted.Width == 512 && colorPromoted.Height == 512,
            ["2048_source_is_preserved"] = capped is not null
                && capped.Width == 2048 && capped.Height == 1024,
            ["4096_source_is_bounded_at_2048"] = bounded is not null
                && bounded.Width == 2048 && bounded.Height == 512,
            ["non_square_aspect_is_preserved"] = aspect is not null
                && aspect.Width == 800 && aspect.Height == 400,
            ["base_wins_equal_resolution_tie"] = tied is not null
                && tied.Width == 512 && tied.Height == 256,
            ["active_colour_mask_preserves_512_coverage_detail"] = colorMaskPromoted is not null
                && colorMaskPromoted.Width == 512 && colorMaskPromoted.Height == 512,
            ["active_surface_mask_preserves_512_coverage_detail"] = surfaceMaskPromoted is not null
                && surfaceMaskPromoted.Width == 512 && surfaceMaskPromoted.Height == 512,
            ["existing_source_orientation_is_preserved"] = PreservesSourceOrientation(),
            ["existing_surface_mask_composite_is_preserved"] = CompositesSurfaceThroughMask(),
            ["existing_colour_palette_composite_is_preserved"] = CompositesColorPaletteThroughSelector(),
        };
        return new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_material_layer_compiler_sizing_v1",
            ["maximum_dimension"] = MaximumDimension,
            ["promoted_dimensions"] = Dimensions(promoted),
            ["color_promoted_dimensions"] = Dimensions(colorPromoted),
            ["capped_dimensions"] = Dimensions(capped),
            ["bounded_dimensions"] = Dimensions(bounded),
            ["aspect_dimensions"] = Dimensions(aspect),
            ["tie_dimensions"] = Dimensions(tied),
            ["colour_mask_dimensions"] = Dimensions(colorMaskPromoted),
            ["surface_mask_dimensions"] = Dimensions(surfaceMaskPromoted),
            ["gates"] = gates,
            ["ok"] = gates.Values.All(value => value),
        };
    }

    private static Dictionary<string, int>? Dimensions(Bitmap? bitmap) => bitmap is null
        ? null
        : new Dictionary<string, int>
        {
            ["width"] = bitmap.Width,
            ["height"] = bitmap.Height,
        };

    private static (int Width, int Height) OutputSize(
        Bitmap? baseSource,
        IEnumerable<Bitmap> layerSources)
    {
        Bitmap? selected = IsUsable(baseSource) ? baseSource : null;
        foreach (var candidate in layerSources)
        {
            if (!IsUsable(candidate))
            {
                continue;
            }
            if (selected is null || HasHigherResolution(candidate, selected))
            {
                selected = candidate;
            }
        }
        if (selected is null)
        {
            throw new InvalidOperationException("Material layer compilation requires a usable colour or material source.");
        }

        // The strictly-higher test keeps the base source authoritative for
        // equal-resolution ties. Active masks are candidates because their
        // authored coverage edges are visible in the compiled result.
        var scale = Math.Min(
            1.0,
            MaximumDimension / (double)Math.Max(selected.Width, selected.Height));
        return (
            Math.Max(1, (int)Math.Round(selected.Width * scale)),
            Math.Max(1, (int)Math.Round(selected.Height * scale)));
    }

    private static IEnumerable<Bitmap> ColorSizingSources(
        IReadOnlyList<NetMaterialLayerSource> layers,
        NetMaterialLayerSource? layerSeed)
    {
        foreach (var layer in layers)
        {
            yield return layer.Diffuse;
            if (layer.Mask is not null
                && !ReferenceEquals(layer, layerSeed)
                && !string.Equals(layer.Binding.LayerRole, "base", StringComparison.OrdinalIgnoreCase)
                && (string.Equals(layer.Binding.LayerRole, "color_seed", StringComparison.OrdinalIgnoreCase)
                    || layer.Binding.Weight > 0.001f))
            {
                yield return layer.Mask;
            }
        }
    }

    private static IEnumerable<Bitmap> SurfaceSizingSources(
        IReadOnlyList<NetMaterialLayerSurfaceSource> layers,
        NetMaterialLayerSurfaceSource? layerSeed)
    {
        foreach (var layer in layers)
        {
            yield return layer.Material;
            if (layer.Mask is not null
                && !ReferenceEquals(layer, layerSeed)
                && !string.Equals(layer.Binding.LayerRole, "base", StringComparison.OrdinalIgnoreCase)
                && layer.Binding.Weight > 0.001f)
            {
                yield return layer.Mask;
            }
        }
    }

    private static bool IsUsable(Bitmap? bitmap) => bitmap is not null
        && bitmap.Width > 0
        && bitmap.Height > 0;

    private static bool HasHigherResolution(Bitmap candidate, Bitmap current)
    {
        var candidateArea = checked((long)candidate.Width * candidate.Height);
        var currentArea = checked((long)current.Width * current.Height);
        if (candidateArea != currentArea)
        {
            return candidateArea > currentArea;
        }
        var candidateLongestSide = Math.Max(candidate.Width, candidate.Height);
        var currentLongestSide = Math.Max(current.Width, current.Height);
        return candidateLongestSide > currentLongestSide;
    }

    private static byte Blend(byte background, float foreground, float alpha)
    {
        return (byte)Math.Clamp(
            (int)Math.Round((background * (1.0f - alpha)) + (Math.Clamp(foreground, 0.0f, 255.0f) * alpha)),
            0,
            255);
    }

    private static int LayerChannelOffset(string channel)
    {
        return channel.Trim().ToLowerInvariant() switch
        {
            "g" => 1,
            "r" => 2,
            "a" => 3,
            _ => 0,
        };
    }

    private static Bitmap ScaleToBgra(Bitmap source, int width, int height)
    {
        var result = new Bitmap(width, height, PixelFormat.Format32bppArgb);
        using var graphics = Graphics.FromImage(result);
        graphics.CompositingMode = CompositingMode.SourceCopy;
        graphics.CompositingQuality = CompositingQuality.HighQuality;
        graphics.InterpolationMode = InterpolationMode.HighQualityBilinear;
        graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
        graphics.DrawImage(source, new Rectangle(0, 0, width, height));
        return result;
    }

    private static byte[] ReadBgra(Bitmap bitmap)
    {
        var rectangle = new Rectangle(0, 0, bitmap.Width, bitmap.Height);
        var data = bitmap.LockBits(rectangle, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        try
        {
            var rowBytes = checked(bitmap.Width * 4);
            var result = new byte[checked(rowBytes * bitmap.Height)];
            for (var y = 0; y < bitmap.Height; y++)
            {
                Marshal.Copy(IntPtr.Add(data.Scan0, y * data.Stride), result, y * rowBytes, rowBytes);
            }
            return result;
        }
        finally
        {
            bitmap.UnlockBits(data);
        }
    }

    private static void WriteBgra(Bitmap bitmap, byte[] pixels)
    {
        var rectangle = new Rectangle(0, 0, bitmap.Width, bitmap.Height);
        var data = bitmap.LockBits(rectangle, ImageLockMode.WriteOnly, PixelFormat.Format32bppArgb);
        try
        {
            var rowBytes = checked(bitmap.Width * 4);
            for (var y = 0; y < bitmap.Height; y++)
            {
                Marshal.Copy(pixels, y * rowBytes, IntPtr.Add(data.Scan0, y * data.Stride), rowBytes);
            }
        }
        finally
        {
            bitmap.UnlockBits(data);
        }
    }
}

internal static class MaterialLayerCompilerSizingProof
{
    private const string ProofFlag = "--material-layer-compiler-sizing-proof";

    public static bool IsRequested(string[] args) => Array.Exists(
        args,
        argument => string.Equals(argument, ProofFlag, StringComparison.OrdinalIgnoreCase));

    public static int Run()
    {
        var report = NetMaterialLayerCompiler.BoundedSourceSizingProof();
        Console.WriteLine(JsonSerializer.Serialize(report));
        return report.GetValueOrDefault("ok") is true ? 0 : 1;
    }
}
