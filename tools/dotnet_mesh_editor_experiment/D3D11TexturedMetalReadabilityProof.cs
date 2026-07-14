using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class D3D11TexturedMetalReadabilityProof
{
    private const int CaptureSize = 128;
    private const double MinimumCenterMeanLuma = 18.0;
    private const double MinimumCenterP10Luma = 5.0;
    private const double MinimumCenterLumaDeviation = 4.0;
    private const double MaximumCenterBackgroundFraction = 0.02;
    private const double MinimumOppositeViewLumaRatio = 0.40;
    private const double MinimumAllViewLumaRatio = 0.65;
    private const double MaximumViewChromaticityDistance = 0.10;
    private const double MaximumCenterWhiteFraction = 0.08;
    private const double MinimumCenterChromaticitySpan = 0.18;

    public static Dictionary<string, object?> Run()
    {
        var evidenceDirectory = Path.Combine(
            Path.GetTempPath(),
            "cdmw-textured-metal-readability",
            Environment.ProcessId.ToString(System.Globalization.CultureInfo.InvariantCulture));
        var rows = new List<Dictionary<string, object?>>();
        try
        {
            Directory.CreateDirectory(evidenceDirectory);
            var texturePath = Path.Combine(evidenceDirectory, "metal-checker.png");
            var manifestPath = Path.Combine(evidenceDirectory, "net-materials.json");
            WriteMetalCheckerTexture(texturePath);
            WriteMaterialManifest(manifestPath, texturePath);

            var document = BuildTwoSidedPlane();
            var bounds = document.Bounds();
            var center = new Vec3(
                (bounds.Min.X + bounds.Max.X) * 0.5f,
                (bounds.Min.Y + bounds.Max.Y) * 0.5f,
                (bounds.Min.Z + bounds.Max.Z) * 0.5f);
            var materials = NetMaterialSet.Load(manifestPath);
            using var textures = NetTextureSet.Load(materials);
            textures.LoadAsync(materials).GetAwaiter().GetResult();
            using var host = CreateHiddenHost();
            using var viewport = new D3D11MaterialViewport(
                document,
                materials,
                textures,
                NetSceneState.Load(string.Empty, document.Submeshes.Count))
            {
                Dock = DockStyle.Fill,
                ShowSolid = true,
                TexturesEnabled = true,
            };
            host.Controls.Add(viewport);
            host.CreateControl();
            _ = host.Handle;
            viewport.CreateControl();
            _ = viewport.Handle;
            if (!viewport.TryInitialize(out var initializeError))
            {
                throw new InvalidOperationException(
                    $"Hidden textured-metal readability viewport initialization failed: {initializeError}");
            }
            viewport.ApplyPresentationSettings(new D3D11PresentationSettings
            {
                CullBackFaces = false,
                DisableLighting = false,
                LightAzimuthDegrees = -10.0f,
                LightElevationDegrees = 0.0f,
                AoStrength = 0.45f,
                RoughnessBias = -0.04f,
                MetalnessScale = 1.45f,
                EnvironmentStrength = 0.62f,
                ToneExposure = 1.0f,
                ToneContrast = 1.08f,
                ToneGamma = 1.0f,
                AmbientStrength = 0.84f,
                DiffuseWrapBias = 0.58f,
                DiffuseLightScale = 0.62f,
                SpecularBase = 0.055f,
                SpecularMax = 0.52f,
            });

            var views = new (string Name, float Yaw, float Pitch)[]
            {
                ("front", 0.0f, 0.0f),
                ("front_oblique", 0.62f, 0.22f),
                ("back", MathF.PI, 0.0f),
                ("back_oblique", MathF.PI + 0.62f, -0.22f),
            };
            foreach (var view in views)
            {
                viewport.UpdateCamera(NetViewportCamera.Create(
                    center,
                    bounds,
                    view.Yaw,
                    view.Pitch,
                    48.0f,
                    0.0f,
                    0.0f,
                    CaptureSize,
                    CaptureSize));
                var capturePath = Path.Combine(evidenceDirectory, $"{view.Name}.png");
                var captured = viewport.TryCaptureReplacementPng(
                    capturePath,
                    CaptureSize,
                    CaptureSize,
                    out var sha256,
                    out var captureError);
                var metrics = captured
                    ? CenterPatchMetrics(capturePath)
                    : new Dictionary<string, object?>();
                var readable = captured
                    && Metric(metrics, "center_mean_luma") >= MinimumCenterMeanLuma
                    && Metric(metrics, "center_p10_luma") >= MinimumCenterP10Luma
                    && Metric(metrics, "center_luma_deviation") >= MinimumCenterLumaDeviation
                    && Metric(metrics, "center_background_fraction") <= MaximumCenterBackgroundFraction;
                rows.Add(new Dictionary<string, object?>
                {
                    ["name"] = view.Name,
                    ["yaw_radians"] = view.Yaw,
                    ["pitch_radians"] = view.Pitch,
                    ["captured"] = captured,
                    ["capture_path"] = capturePath,
                    ["sha256"] = sha256,
                    ["error"] = captureError,
                    ["metrics"] = metrics,
                    ["readable"] = readable,
                });
            }

            var frontBackRatio = OppositeViewLumaRatio(rows, "front", "back");
            var obliqueRatio = OppositeViewLumaRatio(rows, "front_oblique", "back_oblique");
            var allViewLumaRatio = AllViewLumaRatio(rows);
            var maximumChromaticityDistance = MaximumChromaticityDistance(rows);
            var windowsHidden = host.IsHandleCreated
                && viewport.IsHandleCreated
                && !host.Visible
                && !viewport.Visible
                && !IsWindowVisible(host.Handle)
                && !IsWindowVisible(viewport.Handle)
                && !host.ShowInTaskbar;
            var gates = new Dictionary<string, bool>
            {
                ["production_d3d11_backend"] = viewport.IsInitialized
                    && string.Equals(viewport.BackendName, "d3d11_vortice_shader", StringComparison.Ordinal),
                ["native_windows_remained_hidden"] = windowsHidden,
                ["base_texture_decoded"] = textures.BitmapForPath(texturePath) is not null
                    && textures.TextureLoadFailureCount == 0,
                ["textured_metal_front_back_and_oblique_readable"] = rows.Count == views.Length
                    && rows.All(row => row.GetValueOrDefault("readable") is true),
                ["double_sided_opposite_views_balanced"] = frontBackRatio >= MinimumOppositeViewLumaRatio
                    && obliqueRatio >= MinimumOppositeViewLumaRatio,
                ["angle_color_identity_stable"] = maximumChromaticityDistance <= MaximumViewChromaticityDistance
                    && rows.All(row => row.GetValueOrDefault("metrics") is Dictionary<string, object?> metrics
                        && Metric(metrics, "center_white_fraction") <= MaximumCenterWhiteFraction
                        && Metric(metrics, "center_chromaticity_span") >= MinimumCenterChromaticitySpan),
                ["angle_brightness_stable"] = allViewLumaRatio >= MinimumAllViewLumaRatio,
            };
            return new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_textured_metal_readability_v2",
                ["evidence_class"] = "hidden_synthetic_gpu_regression",
                ["material_contract"] = new Dictionary<string, object?>
                {
                    ["base_texture"] = texturePath,
                    ["roughness"] = 0.38,
                    ["metalness"] = 1.0,
                    ["double_sided"] = true,
                },
                ["minimum_center_mean_luma"] = MinimumCenterMeanLuma,
                ["minimum_center_p10_luma"] = MinimumCenterP10Luma,
                ["minimum_center_luma_deviation"] = MinimumCenterLumaDeviation,
                ["maximum_center_background_fraction"] = MaximumCenterBackgroundFraction,
                ["minimum_opposite_view_luma_ratio"] = MinimumOppositeViewLumaRatio,
                ["minimum_all_view_luma_ratio"] = MinimumAllViewLumaRatio,
                ["maximum_view_chromaticity_distance"] = MaximumViewChromaticityDistance,
                ["maximum_center_white_fraction"] = MaximumCenterWhiteFraction,
                ["minimum_center_chromaticity_span"] = MinimumCenterChromaticitySpan,
                ["front_back_mean_luma_ratio"] = frontBackRatio,
                ["oblique_mean_luma_ratio"] = obliqueRatio,
                ["all_view_mean_luma_ratio"] = allViewLumaRatio,
                ["measured_maximum_view_chromaticity_distance"] = maximumChromaticityDistance,
                ["captures"] = rows,
                ["gates"] = gates,
                ["ok"] = gates.Values.All(value => value),
            };
        }
        catch (Exception ex)
        {
            return new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_textured_metal_readability_v2",
                ["evidence_class"] = "hidden_synthetic_gpu_regression",
                ["captures"] = rows,
                ["ok"] = false,
                ["error"] = $"{ex.GetType().Name}: {ex.Message}",
            };
        }
    }

    private static void WriteMetalCheckerTexture(string path)
    {
        using var bitmap = new Bitmap(64, 64);
        for (var y = 0; y < bitmap.Height; y++)
        {
            for (var x = 0; x < bitmap.Width; x++)
            {
                var light = ((x / 8) + (y / 8)) % 2 == 0;
                bitmap.SetPixel(
                    x,
                    y,
                    light ? Color.FromArgb(198, 132, 48) : Color.FromArgb(66, 44, 16));
            }
        }
        bitmap.Save(path, ImageFormat.Png);
    }

    private static void WriteMaterialManifest(string path, string texturePath)
    {
        var manifest = new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_mesh_material_state_v2",
            ["material_signature"] = "textured-metal-readability",
            ["material_slots"] = Array.Empty<object>(),
            ["resources"] = new[]
            {
                new Dictionary<string, object?>
                {
                    ["resource_id"] = "textured-metal:base",
                    ["path"] = texturePath,
                    ["fingerprint"] = "textured-metal-readability-base",
                    ["role"] = "replacement",
                    ["submesh_index"] = 0,
                    ["material_channel"] = "base",
                    ["profile"] = "hidden_gpu_regression",
                    ["required"] = true,
                    ["fallback_policy"] = "reject",
                },
            },
            ["submeshes"] = new[]
            {
                new Dictionary<string, object?>
                {
                    ["submesh_index"] = 0,
                    ["material_slot_index"] = 0,
                    ["material"] = "textured_metal_readability",
                    ["resolved_channels"] = new Dictionary<string, string>
                    {
                        ["base"] = texturePath,
                    },
                    ["resource_channels"] = new Dictionary<string, string>
                    {
                        ["base"] = "textured-metal:base",
                    },
                    ["channel_color_spaces"] = new Dictionary<string, string>
                    {
                        ["base"] = "srgb",
                    },
                    ["alpha_mode"] = "opaque",
                    ["double_sided"] = true,
                    ["parameters"] = new Dictionary<string, object?>
                    {
                        ["roughness"] = 0.38,
                        ["metalness"] = 1.0,
                        ["specular"] = 1.0,
                    },
                },
            },
        };
        File.WriteAllText(path, JsonSerializer.Serialize(manifest));
    }

    private static ObjDocument BuildTwoSidedPlane()
    {
        var document = new ObjDocument();
        var submesh = new ObjSubmesh("textured_metal_readability", 0, 0, 0);
        document.Submeshes.Add(submesh);
        submesh.Vertices.AddRange(new[]
        {
            new Vec3(-1.0f, -1.0f, 0.0f),
            new Vec3(1.0f, -1.0f, 0.0f),
            new Vec3(1.0f, 1.0f, 0.0f),
            new Vec3(-1.0f, 1.0f, 0.0f),
        });
        submesh.Normals.AddRange(Enumerable.Repeat(new Vec3(0.0f, 0.0f, 1.0f), 4));
        submesh.Uvs.AddRange(new[]
        {
            new Vec2(0.0f, 1.0f),
            new Vec2(1.0f, 1.0f),
            new Vec2(1.0f, 0.0f),
            new Vec2(0.0f, 0.0f),
        });
        submesh.Faces.Add(new ObjFace(new[]
        {
            new ObjCorner(0, 0, 0),
            new ObjCorner(1, 1, 1),
            new ObjCorner(2, 2, 2),
        }));
        submesh.Faces.Add(new ObjFace(new[]
        {
            new ObjCorner(0, 0, 0),
            new ObjCorner(2, 2, 2),
            new ObjCorner(3, 3, 3),
        }));
        return document;
    }

    private static Dictionary<string, object?> CenterPatchMetrics(string path)
    {
        using var bitmap = new Bitmap(path);
        var left = bitmap.Width * 35 / 100;
        var right = bitmap.Width * 65 / 100;
        var top = bitmap.Height * 35 / 100;
        var bottom = bitmap.Height * 65 / 100;
        var lumas = new List<double>((right - left) * (bottom - top));
        double redTotal = 0.0;
        double greenTotal = 0.0;
        double blueTotal = 0.0;
        var backgroundCount = 0;
        var whiteCount = 0;
        for (var y = top; y < bottom; y++)
        {
            for (var x = left; x < right; x++)
            {
                var color = bitmap.GetPixel(x, y);
                lumas.Add(0.2126 * color.R + 0.7152 * color.G + 0.0722 * color.B);
                redTotal += color.R;
                greenTotal += color.G;
                blueTotal += color.B;
                if (Math.Abs(color.R - 18) + Math.Abs(color.G - 20) + Math.Abs(color.B - 26) <= 12)
                {
                    backgroundCount++;
                }
                if (color.R >= 245 && color.G >= 245 && color.B >= 245)
                {
                    whiteCount++;
                }
            }
        }
        lumas.Sort();
        var mean = lumas.Count > 0 ? lumas.Average() : 0.0;
        var deviation = lumas.Count > 0
            ? Math.Sqrt(lumas.Average(value => (value - mean) * (value - mean)))
            : 0.0;
        var p10Index = Math.Clamp((int)Math.Floor(lumas.Count * 0.10), 0, Math.Max(0, lumas.Count - 1));
        var channelTotal = redTotal + greenTotal + blueTotal;
        var chromaticityRed = channelTotal > 1e-6 ? redTotal / channelTotal : 0.0;
        var chromaticityGreen = channelTotal > 1e-6 ? greenTotal / channelTotal : 0.0;
        var chromaticityBlue = channelTotal > 1e-6 ? blueTotal / channelTotal : 0.0;
        return new Dictionary<string, object?>
        {
            ["center_sample_count"] = lumas.Count,
            ["center_mean_luma"] = mean,
            ["center_p10_luma"] = lumas.Count > 0 ? lumas[p10Index] : 0.0,
            ["center_luma_deviation"] = deviation,
            ["center_background_fraction"] = lumas.Count > 0
                ? (double)backgroundCount / lumas.Count
                : 1.0,
            ["center_mean_red"] = lumas.Count > 0 ? redTotal / lumas.Count : 0.0,
            ["center_mean_green"] = lumas.Count > 0 ? greenTotal / lumas.Count : 0.0,
            ["center_mean_blue"] = lumas.Count > 0 ? blueTotal / lumas.Count : 0.0,
            ["center_chromaticity_red"] = chromaticityRed,
            ["center_chromaticity_green"] = chromaticityGreen,
            ["center_chromaticity_blue"] = chromaticityBlue,
            ["center_chromaticity_span"] = Math.Max(chromaticityRed, Math.Max(chromaticityGreen, chromaticityBlue))
                - Math.Min(chromaticityRed, Math.Min(chromaticityGreen, chromaticityBlue)),
            ["center_white_fraction"] = lumas.Count > 0
                ? (double)whiteCount / lumas.Count
                : 1.0,
        };
    }

    private static double MaximumChromaticityDistance(
        IReadOnlyList<Dictionary<string, object?>> rows)
    {
        var maximum = 0.0;
        for (var left = 0; left < rows.Count; left++)
        {
            for (var right = left + 1; right < rows.Count; right++)
            {
                maximum = Math.Max(maximum, ChromaticityDistance(rows[left], rows[right]));
            }
        }
        return maximum;
    }

    private static double ChromaticityDistance(
        IReadOnlyDictionary<string, object?> left,
        IReadOnlyDictionary<string, object?> right)
    {
        if (left.GetValueOrDefault("metrics") is not Dictionary<string, object?> leftMetrics
            || right.GetValueOrDefault("metrics") is not Dictionary<string, object?> rightMetrics)
        {
            return double.PositiveInfinity;
        }
        return Math.Abs(Metric(leftMetrics, "center_chromaticity_red") - Metric(rightMetrics, "center_chromaticity_red"))
            + Math.Abs(Metric(leftMetrics, "center_chromaticity_green") - Metric(rightMetrics, "center_chromaticity_green"))
            + Math.Abs(Metric(leftMetrics, "center_chromaticity_blue") - Metric(rightMetrics, "center_chromaticity_blue"));
    }

    private static double OppositeViewLumaRatio(
        IReadOnlyList<Dictionary<string, object?>> rows,
        string first,
        string second)
    {
        var firstMean = ViewMeanLuma(rows, first);
        var secondMean = ViewMeanLuma(rows, second);
        var maximum = Math.Max(firstMean, secondMean);
        return maximum > 1e-6 ? Math.Min(firstMean, secondMean) / maximum : 0.0;
    }

    private static double AllViewLumaRatio(IReadOnlyList<Dictionary<string, object?>> rows)
    {
        var means = rows
            .Select(row => row.GetValueOrDefault("metrics") is Dictionary<string, object?> metrics
                ? Metric(metrics, "center_mean_luma")
                : 0.0)
            .ToArray();
        var maximum = means.Length > 0 ? means.Max() : 0.0;
        return maximum > 1e-6 ? means.Min() / maximum : 0.0;
    }

    private static double ViewMeanLuma(
        IReadOnlyList<Dictionary<string, object?>> rows,
        string name)
    {
        var row = rows.FirstOrDefault(item => string.Equals(
            Convert.ToString(item.GetValueOrDefault("name")),
            name,
            StringComparison.Ordinal));
        return row?.GetValueOrDefault("metrics") is Dictionary<string, object?> metrics
            ? Metric(metrics, "center_mean_luma")
            : 0.0;
    }

    private static double Metric(IReadOnlyDictionary<string, object?> metrics, string key)
    {
        return Convert.ToDouble(metrics.GetValueOrDefault(key) ?? 0.0);
    }

    private static Form CreateHiddenHost() => new()
    {
        Text = "CDMW hidden textured-metal readability proof",
        ClientSize = new Size(CaptureSize, CaptureSize),
        StartPosition = FormStartPosition.Manual,
        Location = new Point(-32000, -32000),
        FormBorderStyle = FormBorderStyle.None,
        ShowInTaskbar = false,
        Visible = false,
    };

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsWindowVisible(IntPtr hWnd);
}
