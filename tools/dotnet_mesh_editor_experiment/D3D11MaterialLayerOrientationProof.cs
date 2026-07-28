using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Numerics;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class D3D11MaterialLayerOrientationProof
{
    private const int CaptureSize = 128;

    public static Dictionary<string, object?> Run()
    {
        var evidenceDirectory = Path.Combine(
            Path.GetTempPath(),
            "cdmw-material-layer-orientation",
            Environment.ProcessId.ToString(System.Globalization.CultureInfo.InvariantCulture));
        try
        {
            Directory.CreateDirectory(evidenceDirectory);
            var basePath = Path.Combine(evidenceDirectory, "base.png");
            var layerPath = Path.Combine(evidenceDirectory, "layer.png");
            var maskPath = Path.Combine(evidenceDirectory, "mask.png");
            var manifestPath = Path.Combine(evidenceDirectory, "net-materials.json");
            WriteSolidTexture(basePath, Color.FromArgb(28, 56, 220));
            WriteSolidTexture(layerPath, Color.FromArgb(224, 38, 24));
            WriteTopHalfMask(maskPath);
            WriteMaterialManifest(manifestPath, basePath, layerPath, maskPath);

            var materials = NetMaterialSet.Load(manifestPath);
            using var textures = NetTextureSet.Load(materials);
            textures.LoadAsync(materials).GetAwaiter().GetResult();
            var compiledReference = textures.SynthesizedBaseReferenceForSubmesh(materials, 0);
            var compiled = textures.BitmapForReference(compiledReference);
            var sourceRowsPreserved = compiled is not null
                && compiled.GetPixel(compiled.Width / 2, compiled.Height / 8).R
                    > compiled.GetPixel(compiled.Width / 2, compiled.Height / 8).B + 100
                && compiled.GetPixel(compiled.Width / 2, compiled.Height * 7 / 8).B
                    > compiled.GetPixel(compiled.Width / 2, compiled.Height * 7 / 8).R + 100;

            var document = BuildPlane();
            var bounds = document.Bounds();
            var center = new Vec3(
                (bounds.Min.X + bounds.Max.X) * 0.5f,
                (bounds.Min.Y + bounds.Max.Y) * 0.5f,
                (bounds.Min.Z + bounds.Max.Z) * 0.5f);
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
                    $"Hidden material-layer orientation viewport initialization failed: {initializeError}");
            }
            viewport.ApplyPresentationSettings(new D3D11PresentationSettings
            {
                CullBackFaces = false,
                DisableLighting = true,
                ToneExposure = 1.0f,
                ToneContrast = 1.0f,
                ToneGamma = 1.0f,
            });
            viewport.UpdateCamera(NetViewportCamera.Create(
                center,
                bounds,
                0.0f,
                0.0f,
                48.0f,
                0.0f,
                0.0f,
                CaptureSize,
                CaptureSize));
            var capturePath = Path.Combine(evidenceDirectory, "single-shader-flip.png");
            var captured = viewport.TryCaptureReplacementPng(
                capturePath,
                CaptureSize,
                CaptureSize,
                out var sha256,
                out var captureError,
                out var renderedCamera);
            var metrics = captured ? OrientationMetrics(capturePath) : new Dictionary<string, object?>();
            var topRedMinusBlue = Metric(metrics, "top_red_minus_blue");
            var bottomBlueMinusRed = Metric(metrics, "bottom_blue_minus_red");
            var windowsHidden = host.IsHandleCreated
                && viewport.IsHandleCreated
                && !host.Visible
                && !viewport.Visible
                && !IsWindowVisible(host.Handle)
                && !IsWindowVisible(viewport.Handle)
                && !host.ShowInTaskbar;
            var gates = new Dictionary<string, bool>
            {
                ["managed_compiler_preserves_source_rows"] = sourceRowsPreserved
                    && NetMaterialLayerCompiler.PreservesSourceOrientation(),
                ["managed_surface_layers_follow_their_mask"] =
                    NetMaterialLayerCompiler.CompositesSurfaceThroughMask(),
                ["managed_layer_composite_created_once"] = textures.MaterialLayerCompositeCount == 1,
                ["production_d3d11_backend"] = viewport.IsInitialized
                    && string.Equals(viewport.BackendName, "d3d11_vortice_shader", StringComparison.Ordinal),
                ["native_windows_remained_hidden"] = windowsHidden,
                ["capture_completed"] = captured
                    && string.IsNullOrWhiteSpace(captureError)
                    && renderedCamera.MultisampleResolved,
                // Source top is red and source bottom is blue. In this D3D plane
                // projection, screen Y and mesh Y oppose each other; the one
                // requested texture-V flip restores red above blue. Omitting it
                // or baking a second flip reverses these assertions.
                ["asset_vertical_flip_applied_exactly_once"] = topRedMinusBlue >= 70.0
                    && bottomBlueMinusRed >= 70.0,
            };
            return new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_material_layer_orientation_v1",
                ["evidence_class"] = "hidden_synthetic_gpu_regression",
                ["capture_path"] = capturePath,
                ["capture_sha256"] = sha256,
                ["capture_error"] = captureError,
                ["metrics"] = metrics,
                ["gates"] = gates,
                ["ok"] = gates.Values.All(value => value),
            };
        }
        catch (Exception ex)
        {
            return new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_material_layer_orientation_v1",
                ["evidence_class"] = "hidden_synthetic_gpu_regression",
                ["ok"] = false,
                ["error"] = $"{ex.GetType().Name}: {ex.Message}",
            };
        }
    }

    private static void WriteSolidTexture(string path, Color color)
    {
        using var bitmap = new Bitmap(64, 64, PixelFormat.Format32bppArgb);
        using var graphics = Graphics.FromImage(bitmap);
        graphics.Clear(color);
        bitmap.Save(path, ImageFormat.Png);
    }

    private static void WriteTopHalfMask(string path)
    {
        using var bitmap = new Bitmap(64, 64, PixelFormat.Format32bppArgb);
        using var graphics = Graphics.FromImage(bitmap);
        graphics.Clear(Color.Black);
        graphics.FillRectangle(Brushes.White, 0, 0, bitmap.Width, bitmap.Height / 2);
        bitmap.Save(path, ImageFormat.Png);
    }

    private static void WriteMaterialManifest(
        string path,
        string basePath,
        string layerPath,
        string maskPath)
    {
        var resources = new[]
        {
            Resource("layer-orientation:base", basePath, "base", "srgb"),
            Resource("layer-orientation:detail", layerPath, "layer_diffuse", "srgb"),
            Resource("layer-orientation:mask", maskPath, "layer_mask", "linear"),
        };
        var manifest = new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_mesh_material_state_v2",
            ["material_signature"] = "material-layer-orientation",
            ["material_slots"] = Array.Empty<object>(),
            ["resources"] = resources,
            ["submeshes"] = new[]
            {
                new Dictionary<string, object?>
                {
                    ["submesh_index"] = 0,
                    ["material_slot_index"] = 0,
                    ["material"] = "material_layer_orientation",
                    ["resolved_channels"] = new Dictionary<string, string> { ["base"] = basePath },
                    ["resource_channels"] = new Dictionary<string, string> { ["base"] = "layer-orientation:base" },
                    ["channel_color_spaces"] = new Dictionary<string, string> { ["base"] = "srgb" },
                    ["texture_flip_vertical"] = true,
                    ["alpha_mode"] = "opaque",
                    ["double_sided"] = true,
                    ["material_layers"] = new object[]
                    {
                        new Dictionary<string, object?>
                        {
                            ["layer_role"] = "base",
                            ["mask_channel"] = "r",
                            ["weight"] = 1.0f,
                            ["tint"] = new[] { 1.0f, 1.0f, 1.0f },
                            ["diffuse_resource_id"] = "layer-orientation:base",
                            ["mask_resource_id"] = "",
                        },
                        new Dictionary<string, object?>
                        {
                            ["layer_role"] = "detail",
                            ["mask_channel"] = "r",
                            ["weight"] = 1.0f,
                            ["tint"] = new[] { 1.0f, 1.0f, 1.0f },
                            ["diffuse_resource_id"] = "layer-orientation:detail",
                            ["mask_resource_id"] = "layer-orientation:mask",
                        },
                    },
                    ["parameters"] = new Dictionary<string, object?>
                    {
                        ["roughness"] = 0.5f,
                        ["metalness"] = 0.0f,
                        ["specular"] = 0.0f,
                    },
                },
            },
        };
        File.WriteAllText(path, JsonSerializer.Serialize(manifest));
    }

    private static Dictionary<string, object?> Resource(
        string resourceId,
        string path,
        string channel,
        string colorSpace) => new()
    {
        ["resource_id"] = resourceId,
        ["path"] = path,
        ["source_reference"] = path,
        ["fingerprint"] = resourceId,
        ["role"] = "replacement",
        ["submesh_index"] = 0,
        ["material_channel"] = channel,
        ["semantic"] = channel,
        ["color_space"] = colorSpace,
        ["required"] = true,
        ["fallback_policy"] = "reject",
    };

    private static ObjDocument BuildPlane()
    {
        var document = new ObjDocument();
        var submesh = new ObjSubmesh("material_layer_orientation", 0, 0, 0);
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

    private static Dictionary<string, object?> OrientationMetrics(string path)
    {
        using var bitmap = new Bitmap(path);
        var top = RegionMean(bitmap, bitmap.Height / 4, bitmap.Height / 2 - 6);
        var bottom = RegionMean(bitmap, bitmap.Height / 2 + 6, bitmap.Height * 3 / 4);
        return new Dictionary<string, object?>
        {
            ["top_mean_red"] = top.R,
            ["top_mean_blue"] = top.B,
            ["top_red_minus_blue"] = top.R - top.B,
            ["bottom_mean_red"] = bottom.R,
            ["bottom_mean_blue"] = bottom.B,
            ["bottom_blue_minus_red"] = bottom.B - bottom.R,
        };
    }

    private static (double R, double B) RegionMean(Bitmap bitmap, int top, int bottom)
    {
        double red = 0.0;
        double blue = 0.0;
        var count = 0;
        for (var y = top; y < bottom; y++)
        {
            for (var x = bitmap.Width / 4; x < bitmap.Width * 3 / 4; x++)
            {
                var color = bitmap.GetPixel(x, y);
                if (Math.Max(color.R, color.B) < 80)
                {
                    continue;
                }
                red += color.R;
                blue += color.B;
                count++;
            }
        }
        return count > 0 ? (red / count, blue / count) : (0.0, 0.0);
    }

    private static double Metric(IReadOnlyDictionary<string, object?> metrics, string key) =>
        Convert.ToDouble(metrics.GetValueOrDefault(key) ?? 0.0);

    private static Form CreateHiddenHost() => new()
    {
        Text = "CDMW hidden material-layer orientation proof",
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
