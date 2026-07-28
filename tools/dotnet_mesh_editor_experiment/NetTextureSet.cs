using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class NetTextureSet : IDisposable
{
    private readonly object _gate = new();
    private readonly Dictionary<string, Bitmap> _decoded = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Bitmap> _decodedByFingerprint = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, string> _lastGoodResourceKeys = new(StringComparer.Ordinal);
    private readonly Dictionary<string, Bitmap> _materialPreviews = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, NetDdsTextureInfo> _ddsResources = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, NetDdsNativeTextureData> _nativeDdsByFingerprint = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<string> _textureLoadFailures = new();
    private Task? _loadTask;
    private bool _disposed;

    private NetTextureSet()
    {
    }

    public int DecodedCount { get { lock (_gate) return _decoded.Count; } }
    public int DdsResourceCount { get { lock (_gate) return _ddsResources.Count; } }
    public int DdsDecodedCount { get { lock (_gate) return _ddsResources.Values.Count(info => info.Decoded); } }
    public int NativeDdsResourceCount { get { lock (_gate) return _nativeDdsByFingerprint.Count; } }
    public int TextureLoadFailureCount { get { lock (_gate) return _textureLoadFailures.Count; } }
    public IReadOnlyDictionary<string, NetDdsTextureInfo> DdsResources { get { lock (_gate) return new Dictionary<string, NetDdsTextureInfo>(_ddsResources); } }
    public IReadOnlyList<string> TextureLoadFailures { get { lock (_gate) return _textureLoadFailures.ToArray(); } }
    public long DecodeAttemptCount { get { lock (_gate) return _decodeAttemptCount; } }
    public long DecodeSuccessCount { get { lock (_gate) return _decodeSuccessCount; } }
    public long DecodeReuseCount { get { lock (_gate) return _decodeReuseCount; } }
    public long IncrementalDecodeCount { get { lock (_gate) return _incrementalDecodeCount; } }

    public static NetTextureSet Load(NetMaterialSet materials)
    {
        _ = materials;
        return new NetTextureSet();
    }

    public Task LoadAsync(NetMaterialSet materials)
    {
        lock (_gate)
        {
            return _loadTask ??= Task.Run(() => LoadTextures(materials));
        }
    }

    private void LoadTextures(NetMaterialSet materials)
    {
        _ = DecodeResources(materials.TextureLoadResources(), incremental: false);
        foreach (var submeshIndex in materials.MaterialLayerSubmeshIndices())
        {
            _ = SynthesizedBaseReferenceForSubmesh(materials, submeshIndex);
            _ = SynthesizedSurfaceReferenceForSubmesh(materials, submeshIndex);
        }
    }

    public Bitmap? BitmapForPath(string path)
    {
        lock (_gate)
        {
            return _decoded.TryGetValue(path, out var bitmap) ? bitmap : null;
        }
    }

    public Color? AverageColorForPath(string path)
    {
        var bitmap = BitmapForPath(path);
        if (bitmap is null)
        {
            return null;
        }
        var stepX = Math.Max(1, bitmap.Width / 64);
        var stepY = Math.Max(1, bitmap.Height / 64);
        long a = 0;
        long r = 0;
        long g = 0;
        long b = 0;
        long count = 0;
        for (var y = 0; y < bitmap.Height; y += stepY)
        {
            for (var x = 0; x < bitmap.Width; x += stepX)
            {
                var color = bitmap.GetPixel(x, y);
                a += color.A;
                r += color.R;
                g += color.G;
                b += color.B;
                count++;
            }
        }
        if (count == 0)
        {
            return null;
        }
        return Color.FromArgb((int)(a / count), (int)(r / count), (int)(g / count), (int)(b / count));
    }

    public double AverageBrightnessForPath(string path)
    {
        var color = AverageColorForPath(path);
        return color is null ? 0.0 : ((color.Value.R + color.Value.G + color.Value.B) / (255.0 * 3.0));
    }

    public Bitmap? MaterialPreviewBitmap(string basePath, string normalPath, string specularPath, string roughnessPath, string metallicPath, string heightPath)
    {
        var baseBitmap = BitmapForPath(basePath);
        if (baseBitmap is null)
        {
            return null;
        }
        var key = string.Join("|", basePath, normalPath, specularPath, roughnessPath, metallicPath, heightPath);
        if (_materialPreviews.TryGetValue(key, out var cached))
        {
            return cached;
        }
        var normalBitmap = BitmapForPath(normalPath);
        var specularBitmap = BitmapForPath(specularPath);
        var roughnessBitmap = BitmapForPath(roughnessPath);
        var metallicBitmap = BitmapForPath(metallicPath);
        var heightBitmap = BitmapForPath(heightPath);
        var maxDimension = Math.Max(baseBitmap.Width, baseBitmap.Height);
        var scale = maxDimension > 1024 ? 1024.0 / maxDimension : 1.0;
        var width = Math.Max(1, (int)Math.Round(baseBitmap.Width * scale));
        var height = Math.Max(1, (int)Math.Round(baseBitmap.Height * scale));
        var preview = new Bitmap(width, height, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        var light = Normalize3(-0.35, -0.45, 0.82);
        var view = Normalize3(0.0, 0.0, 1.0);
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var u = width <= 1 ? 0.0 : x / (double)(width - 1);
                var v = height <= 1 ? 0.0 : y / (double)(height - 1);
                var baseColor = SampleBitmap(baseBitmap, u, v) ?? Color.Black;
                var normalColor = SampleBitmap(normalBitmap, u, v) ?? Color.FromArgb(255, 128, 128, 255);
                var specularColor = SampleBitmap(specularBitmap, u, v) ?? Color.FromArgb(255, 96, 96, 96);
                var roughnessColor = SampleBitmap(roughnessBitmap, u, v) ?? Color.FromArgb(255, 96, 96, 96);
                var metallicColor = SampleBitmap(metallicBitmap, u, v) ?? Color.FromArgb(255, 0, 0, 0);
                var heightColor = SampleBitmap(heightBitmap, u, v) ?? Color.FromArgb(255, 128, 128, 128);
                var normal = Normalize3((normalColor.R / 127.5) - 1.0, (normalColor.G / 127.5) - 1.0, (normalColor.B / 127.5) - 1.0);
                var ndotl = Math.Max(0.0, Dot(normal, light));
                var halfVector = Normalize3(light.X + view.X, light.Y + view.Y, light.Z + view.Z);
                var ndoth = Math.Max(0.0, Dot(normal, halfVector));
                var roughness = Math.Clamp((roughnessColor.R + roughnessColor.G + roughnessColor.B) / (255.0 * 3.0), 0.04, 1.0);
                var metallic = Math.Clamp((metallicColor.R + metallicColor.G + metallicColor.B) / (255.0 * 3.0), 0.0, 1.0);
                var heightGain = ((heightColor.R + heightColor.G + heightColor.B) / (255.0 * 3.0) - 0.5) * 0.12;
                var specStrength = Math.Clamp((specularColor.R + specularColor.G + specularColor.B) / (255.0 * 3.0), 0.0, 1.0);
                var specPower = Math.Clamp(96.0 - (roughness * 72.0), 8.0, 128.0);
                var diffuse = Math.Clamp(0.22 + ndotl * 0.86 + heightGain, 0.0, 1.3);
                var spec = Math.Pow(ndoth, specPower) * specStrength * (0.35 + metallic * 0.65);
                var r = Math.Clamp((int)Math.Round(baseColor.R * diffuse + 255.0 * spec), 0, 255);
                var g = Math.Clamp((int)Math.Round(baseColor.G * diffuse + 255.0 * spec), 0, 255);
                var b = Math.Clamp((int)Math.Round(baseColor.B * diffuse + 255.0 * spec), 0, 255);
                preview.SetPixel(x, y, Color.FromArgb(baseColor.A, r, g, b));
            }
        }
        _materialPreviews[key] = preview;
        return preview;
    }

    private static Color? SampleBitmap(Bitmap? bitmap, double u, double v)
    {
        if (bitmap is null || bitmap.Width <= 0 || bitmap.Height <= 0)
        {
            return null;
        }
        var x = Math.Clamp((int)Math.Round(u * (bitmap.Width - 1)), 0, bitmap.Width - 1);
        var y = Math.Clamp((int)Math.Round(v * (bitmap.Height - 1)), 0, bitmap.Height - 1);
        return bitmap.GetPixel(x, y);
    }

    private static (double X, double Y, double Z) Normalize3(double x, double y, double z)
    {
        var length = Math.Sqrt((x * x) + (y * y) + (z * z));
        return length <= 0.000001 ? (0.0, 0.0, 1.0) : (x / length, y / length, z / length);
    }

    private static double Dot((double X, double Y, double Z) a, (double X, double Y, double Z) b)
    {
        return (a.X * b.X) + (a.Y * b.Y) + (a.Z * b.Z);
    }

    public void Dispose()
    {
        lock (_gate)
        {
            _disposed = true;
            var bitmaps = new HashSet<Bitmap>(_decoded.Values, ReferenceEqualityComparer.Instance);
            bitmaps.UnionWith(_decodedByFingerprint.Values);
            foreach (var bitmap in bitmaps)
            {
                bitmap.Dispose();
            }
            _decoded.Clear();
            _decodedByFingerprint.Clear();
            _lastGoodResourceKeys.Clear();
            foreach (var bitmap in _materialPreviews.Values)
            {
                bitmap.Dispose();
            }
            _materialPreviews.Clear();
            _ddsResources.Clear();
            _nativeDdsByFingerprint.Clear();
            _textureLoadFailures.Clear();
        }
    }

}
