using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

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
    private const int MaximumDimension = 512;

    public static Bitmap? Compile(Bitmap? baseBitmap, IReadOnlyList<NetMaterialLayerSource> layers)
    {
        var firstLayer = layers.FirstOrDefault(layer => layer.Diffuse.Width > 0 && layer.Diffuse.Height > 0);
        var source = baseBitmap ?? firstLayer?.Diffuse;
        if (source is null || source.Width <= 0 || source.Height <= 0)
        {
            return null;
        }

        var scale = Math.Min(1.0, MaximumDimension / (double)Math.Max(source.Width, source.Height));
        var width = Math.Max(1, (int)Math.Round(source.Width * scale));
        var height = Math.Max(1, (int)Math.Round(source.Height * scale));
        var target = ScaleToBgra(source, width, height);
        var targetPixels = ReadBgra(target);
        ApplyColorSeedPalette(targetPixels, width, height, layers);
        var layerSeed = baseBitmap is null ? firstLayer : null;
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
            var seededR = 255.0f * (
                palette[0].TintR * redWeight
                + palette[1].TintR * greenWeight
                + palette[2].TintR * blueWeight) / total;
            var seededG = 255.0f * (
                palette[0].TintG * redWeight
                + palette[1].TintG * greenWeight
                + palette[2].TintG * blueWeight) / total;
            var seededB = 255.0f * (
                palette[0].TintB * redWeight
                + palette[1].TintB * greenWeight
                + palette[2].TintB * blueWeight) / total;
            targetPixels[offset] = Blend(targetPixels[offset], seededB, coverage);
            targetPixels[offset + 1] = Blend(targetPixels[offset + 1], seededG, coverage);
            targetPixels[offset + 2] = Blend(targetPixels[offset + 2], seededR, coverage);
        }
        return true;
    }

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

        var scale = Math.Min(1.0, MaximumDimension / (double)Math.Max(source.Width, source.Height));
        var width = Math.Max(1, (int)Math.Round(source.Width * scale));
        var height = Math.Max(1, (int)Math.Round(source.Height * scale));
        var target = ScaleToBgra(source, width, height);
        var targetPixels = ReadBgra(target);
        var layerSeed = baseMaterial is null ? firstLayer : null;
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
        using var baseBitmap = new Bitmap(4, 1, PixelFormat.Format32bppArgb);
        using var diffuse = new Bitmap(4, 1, PixelFormat.Format32bppArgb);
        using var selector = new Bitmap(4, 1, PixelFormat.Format32bppArgb);
        using (var baseGraphics = Graphics.FromImage(baseBitmap)) baseGraphics.Clear(Color.FromArgb(255, 64, 64, 64));
        using (var diffuseGraphics = Graphics.FromImage(diffuse)) diffuseGraphics.Clear(Color.White);
        selector.SetPixel(0, 0, Color.Red);
        selector.SetPixel(1, 0, Color.FromArgb(255, 0, 255, 0));
        selector.SetPixel(2, 0, Color.Blue);
        selector.SetPixel(3, 0, Color.FromArgb(255, 128, 128, 0));
        var red = new NetMaterialLayerBinding("color_seed", "r", 1.0f, 1.0f, 0.0f, 0.0f, "base", "selector");
        var green = new NetMaterialLayerBinding("color_seed", "g", 1.0f, 0.0f, 1.0f, 0.0f, "base", "selector");
        var blue = new NetMaterialLayerBinding("color_seed", "b", 1.0f, 0.0f, 0.0f, 1.0f, "base", "selector");
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
        var greenPixel = compiled.GetPixel(1, 0);
        var bluePixel = compiled.GetPixel(2, 0);
        var mixedPixel = compiled.GetPixel(3, 0);
        return redPixel.R > 245 && redPixel.G < 10 && redPixel.B < 10
            && greenPixel.G > 245 && greenPixel.R < 10 && greenPixel.B < 10
            && bluePixel.B > 245 && bluePixel.R < 10 && bluePixel.G < 10
            && Math.Abs(mixedPixel.R - mixedPixel.G) <= 2
            && mixedPixel.R > 120 && mixedPixel.B < 10;
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
