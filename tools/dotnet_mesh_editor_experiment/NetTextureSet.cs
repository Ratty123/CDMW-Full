using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed class NetTextureSet : IDisposable
{
    private readonly Dictionary<string, Bitmap> _decoded = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Bitmap> _materialPreviews = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, NetDdsTextureInfo> _ddsResources = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<string> _textureLoadFailures = new();

    private NetTextureSet()
    {
    }

    public int DecodedCount => _decoded.Count;
    public int DdsResourceCount => _ddsResources.Count;
    public int DdsDecodedCount => _ddsResources.Values.Count(info => info.Decoded);
    public int TextureLoadFailureCount => _textureLoadFailures.Count;
    public IReadOnlyDictionary<string, NetDdsTextureInfo> DdsResources => _ddsResources;
    public IReadOnlyList<string> TextureLoadFailures => _textureLoadFailures;

    public static NetTextureSet Load(NetMaterialSet materials)
    {
        var set = new NetTextureSet();
        foreach (var path in materials.SubmeshTexturePaths()
            .Where(value => !string.IsNullOrWhiteSpace(value) && File.Exists(value))
            .Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (IsDdsPath(path))
            {
                var dds = DecodeDds(path);
                if (dds.Info is not null)
                {
                    set._ddsResources[path] = dds.Info;
                    if (dds.Bitmap is not null)
                    {
                        set._decoded[path] = dds.Bitmap;
                    }
                }
                else
                {
                    set._textureLoadFailures.Add(path);
                }
                continue;
            }
            if (!IsDecodableImagePath(path))
            {
                continue;
            }
            try
            {
                set._decoded[path] = new Bitmap(path);
            }
            catch
            {
                set._textureLoadFailures.Add(path);
            }
        }
        return set;
    }

    public Bitmap? BitmapForPath(string path)
    {
        return _decoded.TryGetValue(path, out var bitmap) ? bitmap : null;
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
        foreach (var bitmap in _decoded.Values)
        {
            bitmap.Dispose();
        }
        _decoded.Clear();
        foreach (var bitmap in _materialPreviews.Values)
        {
            bitmap.Dispose();
        }
        _materialPreviews.Clear();
        _ddsResources.Clear();
        _textureLoadFailures.Clear();
    }

    private static bool IsDecodableImagePath(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || !File.Exists(value))
        {
            return false;
        }
        var extension = Path.GetExtension(value).ToLowerInvariant();
        return extension is ".png" or ".jpg" or ".jpeg" or ".bmp" or ".gif" or ".tif" or ".tiff";
    }

    private static bool IsDdsPath(string value)
    {
        return !string.IsNullOrWhiteSpace(value) && Path.GetExtension(value).Equals(".dds", StringComparison.OrdinalIgnoreCase);
    }

    private static (NetDdsTextureInfo? Info, Bitmap? Bitmap) DecodeDds(string path)
    {
        try
        {
            using var stream = File.OpenRead(path);
            using var reader = new BinaryReader(stream, Encoding.ASCII, leaveOpen: false);
            if (stream.Length < 128)
            {
                return (null, null);
            }
            var magic = reader.ReadBytes(4);
            if (magic.Length != 4 || magic[0] != (byte)'D' || magic[1] != (byte)'D' || magic[2] != (byte)'S' || magic[3] != (byte)' ')
            {
                return (null, null);
            }
            var headerSize = reader.ReadInt32();
            if (headerSize != 124)
            {
                return (null, null);
            }
            _ = reader.ReadInt32();
            var height = Math.Max(0, reader.ReadInt32());
            var width = Math.Max(0, reader.ReadInt32());
            _ = reader.ReadInt32();
            _ = reader.ReadInt32();
            var mipCount = Math.Max(1, reader.ReadInt32());
            stream.Position = 80;
            var pixelFlags = reader.ReadUInt32();
            var fourCcBytes = reader.ReadBytes(4);
            var fourCc = Encoding.ASCII.GetString(fourCcBytes).TrimEnd('\0', ' ');
            var rgbBitCount = reader.ReadInt32();
            var rMask = reader.ReadUInt32();
            var gMask = reader.ReadUInt32();
            var bMask = reader.ReadUInt32();
            var aMask = reader.ReadUInt32();
            var dxgiFormat = 0;
            var formatKey = fourCc;
            if (string.Equals(fourCc, "DX10", StringComparison.OrdinalIgnoreCase) && stream.Length >= 148)
            {
                stream.Position = 128;
                dxgiFormat = reader.ReadInt32();
                _ = reader.ReadInt32();
                _ = reader.ReadInt32();
                _ = reader.ReadInt32();
                _ = reader.ReadInt32();
                formatKey = DxgiDecodeKey(dxgiFormat);
                fourCc = $"DXGI_{dxgiFormat}";
            }
            var dataOffset = dxgiFormat != 0 ? 148 : 128;
            stream.Position = Math.Min(stream.Length, dataOffset);
            var data = reader.ReadBytes((int)Math.Max(0, stream.Length - stream.Position));
            var bitmap = DecodeDdsBitmap(width, height, formatKey, rgbBitCount, rMask, gMask, bMask, aMask, data)
                ?? DecodeDdsWithCdTextureDx(path)
                ?? DecodeDdsWithTexconv(path);
            return (new NetDdsTextureInfo(path, width, height, mipCount, fourCc, bitmap is not null), bitmap);
        }
        catch
        {
            return (null, null);
        }
    }

    private static Bitmap? DecodeDdsWithCdTextureDx(string path)
    {
        var converter = FindCdTextureDxExecutable();
        if (string.IsNullOrWhiteSpace(converter) || !File.Exists(converter))
        {
            return null;
        }
        var outputDir = Path.Combine(Path.GetTempPath(), "cdmw-dotnet-dds", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(outputDir);
        try
        {
            var outputPng = Path.Combine(outputDir, "preview.png");
            var jobPath = Path.Combine(outputDir, "job.json");
            var reportPath = Path.Combine(outputDir, "report.json");
            var job = new Dictionary<string, object?>
            {
                ["jobs"] = new[]
                {
                    new Dictionary<string, object?>
                    {
                        ["input"] = path,
                        ["output"] = outputPng,
                        ["slot"] = "dotnet_preview",
                        ["max_dimension"] = 4096,
                        ["srgb"] = true,
                        ["normal_space"] = string.Empty,
                    }
                }
            };
            File.WriteAllText(jobPath, JsonSerializer.Serialize(job), Encoding.UTF8);
            var start = new ProcessStartInfo
            {
                FileName = converter,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardError = true,
                RedirectStandardOutput = true,
            };
            start.ArgumentList.Add("batch-preview-json");
            start.ArgumentList.Add(jobPath);
            start.ArgumentList.Add(reportPath);
            using var process = Process.Start(start);
            if (process is null)
            {
                return null;
            }
            if (!process.WaitForExit(10000) || process.ExitCode != 0 || !File.Exists(outputPng))
            {
                return null;
            }
            using var decoded = new Bitmap(outputPng);
            return new Bitmap(decoded);
        }
        catch
        {
            return null;
        }
        finally
        {
            try
            {
                Directory.Delete(outputDir, recursive: true);
            }
            catch
            {
                // Best-effort temp cleanup.
            }
        }
    }

    private static Bitmap? DecodeDdsWithTexconv(string path)
    {
        var texconv = FindTexconvExecutable();
        if (string.IsNullOrWhiteSpace(texconv) || !File.Exists(texconv))
        {
            return null;
        }
        var outputDir = Path.Combine(Path.GetTempPath(), "cdmw-dotnet-dds", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(outputDir);
        try
        {
            var start = new ProcessStartInfo
            {
                FileName = texconv,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardError = true,
                RedirectStandardOutput = true,
            };
            start.ArgumentList.Add("-y");
            start.ArgumentList.Add("-ft");
            start.ArgumentList.Add("png");
            start.ArgumentList.Add("-o");
            start.ArgumentList.Add(outputDir);
            start.ArgumentList.Add(path);
            using var process = Process.Start(start);
            if (process is null)
            {
                return null;
            }
            if (!process.WaitForExit(10000) || process.ExitCode != 0)
            {
                return null;
            }
            var png = Directory.EnumerateFiles(outputDir, "*.png").FirstOrDefault();
            if (string.IsNullOrWhiteSpace(png) || !File.Exists(png))
            {
                return null;
            }
            using var decoded = new Bitmap(png);
            return new Bitmap(decoded);
        }
        catch
        {
            return null;
        }
        finally
        {
            try
            {
                Directory.Delete(outputDir, recursive: true);
            }
            catch
            {
                // Best-effort temp cleanup.
            }
        }
    }

    private static string FindCdTextureDxExecutable()
    {
        var env = Environment.GetEnvironmentVariable("CDMW_CD_TEXTURE_DX_EXE");
        var baseDir = AppContext.BaseDirectory;
        var candidates = new[]
        {
            env,
            Path.Combine(baseDir, "cd-texture-dx.exe"),
            Path.Combine(baseDir, "native", "cd-texture-dx.exe"),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cd_texture_dx", "build", "Release", "cd-texture-dx.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cd_texture_dx", "build", "Debug", "cd-texture-dx.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cd_texture_dx", "build", "Release", "cd-texture-dx.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cd_texture_dx", "build", "Debug", "cd-texture-dx.exe")),
        };
        foreach (var candidate in candidates)
        {
            if (!string.IsNullOrWhiteSpace(candidate) && File.Exists(candidate))
            {
                return candidate;
            }
        }
        return string.Empty;
    }

    private static string FindTexconvExecutable()
    {
        var env = Environment.GetEnvironmentVariable("CDMW_TEXCONV_EXE");
        var baseDir = AppContext.BaseDirectory;
        var candidates = new[]
        {
            env,
            Path.Combine(baseDir, "texconv.exe"),
            Path.Combine(baseDir, "native", "texconv.exe"),
            Path.Combine(baseDir, "native", "cd_texture_dx", "texconv.exe"),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cd_texture_dx", "build", "bin", "Release", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cd_texture_dx", "build", "bin", "Debug", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cdmw_d3d11_preview", "build", "bin", "Release", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cdmw_d3d11_preview", "build", "bin", "Debug", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cd_texture_dx", "build", "bin", "Release", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cd_texture_dx", "build", "bin", "Debug", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cdmw_d3d11_preview", "build", "bin", "Release", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cdmw_d3d11_preview", "build", "bin", "Debug", "texconv.exe")),
        };
        foreach (var candidate in candidates)
        {
            if (!string.IsNullOrWhiteSpace(candidate) && File.Exists(candidate))
            {
                return candidate;
            }
        }
        return string.Empty;
    }

    private static string DxgiDecodeKey(int dxgiFormat)
    {
        return dxgiFormat switch
        {
            28 or 29 => "RGBA8",
            49 => "RG8",
            56 => "R16",
            61 => "R8",
            70 or 71 => "BC1",
            72 or 73 => "BC2",
            74 or 75 => "BC3",
            76 or 77 => "BC4",
            80 or 83 => "BC5",
            87 or 91 => "BGRA8",
            88 or 93 => "BGRX8",
            _ => $"DXGI_{dxgiFormat}",
        };
    }

    private static Bitmap? DecodeDdsBitmap(int width, int height, string fourCc, int rgbBitCount, uint rMask, uint gMask, uint bMask, uint aMask, byte[] data)
    {
        if (width <= 0 || height <= 0 || data.Length == 0)
        {
            return null;
        }
        var normalized = (fourCc ?? string.Empty).Trim().ToUpperInvariant();
        return normalized switch
        {
            "DXT1" => DecodeBc1(width, height, data),
            "DXT3" => DecodeBc2(width, height, data),
            "DXT5" => DecodeBc3(width, height, data),
            "BC1" => DecodeBc1(width, height, data),
            "BC2" => DecodeBc2(width, height, data),
            "BC3" => DecodeBc3(width, height, data),
            "BC4" => DecodeBc4(width, height, data),
            "BC5" => DecodeBc5(width, height, data),
            "RGBA8" => DecodeRgba32(width, height, data),
            "BGRA8" => DecodeBgra32(width, height, data, opaqueAlpha: false),
            "BGRX8" => DecodeBgra32(width, height, data, opaqueAlpha: true),
            "R8" => DecodeR8(width, height, data),
            "RG8" => DecodeRg8(width, height, data),
            _ when rgbBitCount == 32 => DecodeUncompressed32(width, height, rMask, gMask, bMask, aMask, data),
            _ => null,
        };
    }

    private static Bitmap? DecodeBc1(int width, int height, byte[] data)
    {
        var pixels = new byte[width * height * 4];
        var blocksWide = Math.Max(1, (width + 3) / 4);
        var blocksHigh = Math.Max(1, (height + 3) / 4);
        var offset = 0;
        for (var by = 0; by < blocksHigh; by++)
        {
            for (var bx = 0; bx < blocksWide; bx++)
            {
                if (offset + 8 > data.Length)
                {
                    return BitmapFromBgra(width, height, pixels);
                }
                DecodeBcColorBlock(width, height, pixels, bx * 4, by * 4, data, offset, allowPunchThroughAlpha: true);
                offset += 8;
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeBc2(int width, int height, byte[] data)
    {
        var pixels = new byte[width * height * 4];
        var blocksWide = Math.Max(1, (width + 3) / 4);
        var blocksHigh = Math.Max(1, (height + 3) / 4);
        var offset = 0;
        for (var by = 0; by < blocksHigh; by++)
        {
            for (var bx = 0; bx < blocksWide; bx++)
            {
                if (offset + 16 > data.Length)
                {
                    return BitmapFromBgra(width, height, pixels);
                }
                DecodeBcColorBlock(width, height, pixels, bx * 4, by * 4, data, offset + 8, allowPunchThroughAlpha: false);
                for (var row = 0; row < 4; row++)
                {
                    var alphaRow = data[offset + (row * 2)] | (data[offset + (row * 2) + 1] << 8);
                    for (var col = 0; col < 4; col++)
                    {
                        var alpha4 = (alphaRow >> (col * 4)) & 0x0F;
                        SetAlpha(pixels, width, height, bx * 4 + col, by * 4 + row, (byte)((alpha4 << 4) | alpha4));
                    }
                }
                offset += 16;
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeBc3(int width, int height, byte[] data)
    {
        var pixels = new byte[width * height * 4];
        var blocksWide = Math.Max(1, (width + 3) / 4);
        var blocksHigh = Math.Max(1, (height + 3) / 4);
        var offset = 0;
        for (var by = 0; by < blocksHigh; by++)
        {
            for (var bx = 0; bx < blocksWide; bx++)
            {
                if (offset + 16 > data.Length)
                {
                    return BitmapFromBgra(width, height, pixels);
                }
                DecodeBcColorBlock(width, height, pixels, bx * 4, by * 4, data, offset + 8, allowPunchThroughAlpha: false);
                var alphas = Bc3AlphaPalette(data[offset], data[offset + 1]);
                ulong alphaBits = 0;
                for (var i = 0; i < 6; i++)
                {
                    alphaBits |= ((ulong)data[offset + 2 + i]) << (8 * i);
                }
                for (var row = 0; row < 4; row++)
                {
                    for (var col = 0; col < 4; col++)
                    {
                        var pixelIndex = row * 4 + col;
                        var alphaIndex = (int)((alphaBits >> (3 * pixelIndex)) & 0x07);
                        SetAlpha(pixels, width, height, bx * 4 + col, by * 4 + row, alphas[alphaIndex]);
                    }
                }
                offset += 16;
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeBc4(int width, int height, byte[] data)
    {
        var pixels = new byte[width * height * 4];
        var blocksWide = Math.Max(1, (width + 3) / 4);
        var blocksHigh = Math.Max(1, (height + 3) / 4);
        var offset = 0;
        for (var by = 0; by < blocksHigh; by++)
        {
            for (var bx = 0; bx < blocksWide; bx++)
            {
                if (offset + 8 > data.Length)
                {
                    return BitmapFromBgra(width, height, pixels);
                }
                var values = DecodeBc4Block(data, offset);
                for (var row = 0; row < 4; row++)
                {
                    for (var col = 0; col < 4; col++)
                    {
                        var value = values[row * 4 + col];
                        SetBgra(pixels, width, height, bx * 4 + col, by * 4 + row, value, value, value, 255);
                    }
                }
                offset += 8;
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeBc5(int width, int height, byte[] data)
    {
        var pixels = new byte[width * height * 4];
        var blocksWide = Math.Max(1, (width + 3) / 4);
        var blocksHigh = Math.Max(1, (height + 3) / 4);
        var offset = 0;
        for (var by = 0; by < blocksHigh; by++)
        {
            for (var bx = 0; bx < blocksWide; bx++)
            {
                if (offset + 16 > data.Length)
                {
                    return BitmapFromBgra(width, height, pixels);
                }
                var red = DecodeBc4Block(data, offset);
                var green = DecodeBc4Block(data, offset + 8);
                for (var row = 0; row < 4; row++)
                {
                    for (var col = 0; col < 4; col++)
                    {
                        var pixelIndex = row * 4 + col;
                        var rx = (red[pixelIndex] / 127.5) - 1.0;
                        var gy = (green[pixelIndex] / 127.5) - 1.0;
                        var bz = Math.Sqrt(Math.Max(0.0, 1.0 - (rx * rx) - (gy * gy)));
                        var blue = (byte)Math.Clamp((int)Math.Round((bz * 0.5 + 0.5) * 255.0), 0, 255);
                        SetBgra(pixels, width, height, bx * 4 + col, by * 4 + row, red[pixelIndex], green[pixelIndex], blue, 255);
                    }
                }
                offset += 16;
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static byte[] DecodeBc4Block(byte[] data, int offset)
    {
        var palette = Bc3AlphaPalette(data[offset], data[offset + 1]);
        ulong bits = 0;
        for (var i = 0; i < 6; i++)
        {
            bits |= ((ulong)data[offset + 2 + i]) << (8 * i);
        }
        var values = new byte[16];
        for (var i = 0; i < 16; i++)
        {
            values[i] = palette[(int)((bits >> (3 * i)) & 0x07)];
        }
        return values;
    }

    private static void DecodeBcColorBlock(int width, int height, byte[] pixels, int originX, int originY, byte[] data, int offset, bool allowPunchThroughAlpha)
    {
        var c0 = BitConverter.ToUInt16(data, offset);
        var c1 = BitConverter.ToUInt16(data, offset + 2);
        var palette = BcColorPalette(c0, c1, allowPunchThroughAlpha);
        var bits = BitConverter.ToUInt32(data, offset + 4);
        for (var row = 0; row < 4; row++)
        {
            for (var col = 0; col < 4; col++)
            {
                var index = (int)((bits >> (2 * (row * 4 + col))) & 0x03);
                var color = palette[index];
                SetBgra(pixels, width, height, originX + col, originY + row, color.R, color.G, color.B, color.A);
            }
        }
    }

    private static DdsColor[] BcColorPalette(ushort color0, ushort color1, bool allowPunchThroughAlpha)
    {
        var first = ColorFrom565(color0);
        var second = ColorFrom565(color1);
        var palette = new DdsColor[4];
        palette[0] = new DdsColor(first.R, first.G, first.B, 255);
        palette[1] = new DdsColor(second.R, second.G, second.B, 255);
        if (color0 > color1 || !allowPunchThroughAlpha)
        {
            palette[2] = new DdsColor((byte)((2 * first.R + second.R) / 3), (byte)((2 * first.G + second.G) / 3), (byte)((2 * first.B + second.B) / 3), 255);
            palette[3] = new DdsColor((byte)((first.R + 2 * second.R) / 3), (byte)((first.G + 2 * second.G) / 3), (byte)((first.B + 2 * second.B) / 3), 255);
        }
        else
        {
            palette[2] = new DdsColor((byte)((first.R + second.R) / 2), (byte)((first.G + second.G) / 2), (byte)((first.B + second.B) / 2), 255);
            palette[3] = new DdsColor(0, 0, 0, 0);
        }
        return palette;
    }

    private static DdsColor ColorFrom565(ushort value)
    {
        var r = (byte)((((value >> 11) & 0x1F) * 255 + 15) / 31);
        var g = (byte)((((value >> 5) & 0x3F) * 255 + 31) / 63);
        var b = (byte)(((value & 0x1F) * 255 + 15) / 31);
        return new DdsColor(r, g, b, 255);
    }

    private static byte[] Bc3AlphaPalette(byte alpha0, byte alpha1)
    {
        var alphas = new byte[8];
        alphas[0] = alpha0;
        alphas[1] = alpha1;
        if (alpha0 > alpha1)
        {
            for (var i = 1; i <= 6; i++)
            {
                alphas[i + 1] = (byte)(((7 - i) * alpha0 + i * alpha1) / 7);
            }
        }
        else
        {
            for (var i = 1; i <= 4; i++)
            {
                alphas[i + 1] = (byte)(((5 - i) * alpha0 + i * alpha1) / 5);
            }
            alphas[6] = 0;
            alphas[7] = 255;
        }
        return alphas;
    }

    private static Bitmap? DecodeRgba32(int width, int height, byte[] data)
    {
        if (data.Length < width * height * 4)
        {
            return null;
        }
        var pixels = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var offset = ((y * width) + x) * 4;
                SetBgra(pixels, width, height, x, y, data[offset], data[offset + 1], data[offset + 2], data[offset + 3]);
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeBgra32(int width, int height, byte[] data, bool opaqueAlpha)
    {
        if (data.Length < width * height * 4)
        {
            return null;
        }
        var pixels = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var sourceOffset = ((y * width) + x) * 4;
                var targetOffset = ((y * width) + x) * 4;
                pixels[targetOffset] = data[sourceOffset];
                pixels[targetOffset + 1] = data[sourceOffset + 1];
                pixels[targetOffset + 2] = data[sourceOffset + 2];
                pixels[targetOffset + 3] = opaqueAlpha ? (byte)255 : data[sourceOffset + 3];
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeR8(int width, int height, byte[] data)
    {
        if (data.Length < width * height)
        {
            return null;
        }
        var pixels = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var value = data[(y * width) + x];
                SetBgra(pixels, width, height, x, y, value, value, value, 255);
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeRg8(int width, int height, byte[] data)
    {
        if (data.Length < width * height * 2)
        {
            return null;
        }
        var pixels = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var offset = ((y * width) + x) * 2;
                SetBgra(pixels, width, height, x, y, data[offset], data[offset + 1], 128, 255);
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeUncompressed32(int width, int height, uint rMask, uint gMask, uint bMask, uint aMask, byte[] data)
    {
        if (data.Length < width * height * 4)
        {
            return null;
        }
        var pixels = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var sourceOffset = ((y * width) + x) * 4;
                var packed = BitConverter.ToUInt32(data, sourceOffset);
                var r = ExtractMaskedChannel(packed, rMask, defaultValue: 0);
                var g = ExtractMaskedChannel(packed, gMask, defaultValue: 0);
                var b = ExtractMaskedChannel(packed, bMask, defaultValue: 0);
                var a = ExtractMaskedChannel(packed, aMask, defaultValue: 255);
                SetBgra(pixels, width, height, x, y, r, g, b, a);
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static byte ExtractMaskedChannel(uint packed, uint mask, byte defaultValue)
    {
        if (mask == 0)
        {
            return defaultValue;
        }
        var shift = 0;
        var shiftedMask = mask;
        while ((shiftedMask & 1) == 0)
        {
            shiftedMask >>= 1;
            shift++;
        }
        var value = (packed & mask) >> shift;
        return shiftedMask == 0 ? defaultValue : (byte)Math.Clamp((int)(value * 255 / shiftedMask), 0, 255);
    }

    private static void SetBgra(byte[] pixels, int width, int height, int x, int y, byte r, byte g, byte b, byte a)
    {
        if (x < 0 || y < 0 || x >= width || y >= height)
        {
            return;
        }
        var offset = ((y * width) + x) * 4;
        pixels[offset] = b;
        pixels[offset + 1] = g;
        pixels[offset + 2] = r;
        pixels[offset + 3] = a;
    }

    private static void SetAlpha(byte[] pixels, int width, int height, int x, int y, byte a)
    {
        if (x < 0 || y < 0 || x >= width || y >= height)
        {
            return;
        }
        pixels[((y * width) + x) * 4 + 3] = a;
    }

    private static Bitmap BitmapFromBgra(int width, int height, byte[] pixels)
    {
        var bitmap = new Bitmap(width, height, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        var rect = new Rectangle(0, 0, width, height);
        var locked = bitmap.LockBits(rect, System.Drawing.Imaging.ImageLockMode.WriteOnly, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        try
        {
            if (locked.Stride == width * 4)
            {
                Marshal.Copy(pixels, 0, locked.Scan0, pixels.Length);
            }
            else
            {
                for (var y = 0; y < height; y++)
                {
                    Marshal.Copy(pixels, y * width * 4, locked.Scan0 + y * locked.Stride, width * 4);
                }
            }
        }
        finally
        {
            bitmap.UnlockBits(locked);
        }
        return bitmap;
    }
}
