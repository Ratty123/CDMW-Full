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
        var layerSeed = baseBitmap is null ? firstLayer : null;
        if (layerSeed is not null)
        {
            ApplyTint(targetPixels, layerSeed.Binding);
        }
        foreach (var layer in layers)
        {
            if (string.Equals(layer.Binding.LayerRole, "base", StringComparison.OrdinalIgnoreCase)
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
