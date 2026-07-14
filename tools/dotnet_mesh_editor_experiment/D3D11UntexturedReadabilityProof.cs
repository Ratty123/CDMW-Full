using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;

namespace Cdmw.MeshEditorExperiment;

internal static class D3D11UntexturedReadabilityProof
{
    private const int CaptureSize = 128;
    private const double MinimumCenterMeanLuma = 60.0;
    private const double MinimumCenterP10Luma = 52.0;
    private const double MaximumCenterBackgroundFraction = 0.02;

    public static Dictionary<string, object?> Run()
    {
        var evidenceDirectory = Path.Combine(
            Path.GetTempPath(),
            "cdmw-untextured-readability",
            Environment.ProcessId.ToString(System.Globalization.CultureInfo.InvariantCulture));
        var rows = new List<Dictionary<string, object?>>();
        try
        {
            Directory.CreateDirectory(evidenceDirectory);
            var document = BuildTwoSidedPlane();
            var bounds = document.Bounds();
            var center = new Vec3(
                (bounds.Min.X + bounds.Max.X) * 0.5f,
                (bounds.Min.Y + bounds.Max.Y) * 0.5f,
                (bounds.Min.Z + bounds.Max.Z) * 0.5f);
            var materials = NetMaterialSet.Empty;
            using var textures = NetTextureSet.Load(materials);
            using var host = CreateHiddenHost();
            using var viewport = new D3D11MaterialViewport(
                document,
                materials,
                textures,
                NetSceneState.Load(string.Empty, document.Submeshes.Count))
            {
                Dock = DockStyle.Fill,
                ShowSolid = true,
                TexturesEnabled = false,
            };
            host.Controls.Add(viewport);
            host.CreateControl();
            _ = host.Handle;
            viewport.CreateControl();
            _ = viewport.Handle;
            if (!viewport.TryInitialize(out var initializeError))
            {
                throw new InvalidOperationException(
                    $"Hidden untextured readability viewport initialization failed: {initializeError}");
            }
            viewport.ApplyPresentationSettings(new D3D11PresentationSettings
            {
                CullBackFaces = false,
                DisableLighting = false,
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
                    && Convert.ToDouble(metrics.GetValueOrDefault("center_mean_luma") ?? 0.0)
                        >= MinimumCenterMeanLuma
                    && Convert.ToDouble(metrics.GetValueOrDefault("center_p10_luma") ?? 0.0)
                        >= MinimumCenterP10Luma
                    && Convert.ToDouble(metrics.GetValueOrDefault("center_background_fraction") ?? 1.0)
                        <= MaximumCenterBackgroundFraction;
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
                ["front_back_and_oblique_captures_readable"] = rows.Count == views.Length
                    && rows.All(row => row.GetValueOrDefault("readable") is true),
            };
            return new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_untextured_readability_v1",
                ["evidence_class"] = "hidden_synthetic_gpu_regression",
                ["minimum_center_mean_luma"] = MinimumCenterMeanLuma,
                ["minimum_center_p10_luma"] = MinimumCenterP10Luma,
                ["maximum_center_background_fraction"] = MaximumCenterBackgroundFraction,
                ["captures"] = rows,
                ["gates"] = gates,
                ["ok"] = gates.Values.All(value => value),
            };
        }
        catch (Exception ex)
        {
            return new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_untextured_readability_v1",
                ["evidence_class"] = "hidden_synthetic_gpu_regression",
                ["captures"] = rows,
                ["ok"] = false,
                ["error"] = $"{ex.GetType().Name}: {ex.Message}",
            };
        }
    }

    private static ObjDocument BuildTwoSidedPlane()
    {
        var document = new ObjDocument();
        var submesh = new ObjSubmesh("untextured_readability", 0, 0, 0);
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
        var backgroundCount = 0;
        for (var y = top; y < bottom; y++)
        {
            for (var x = left; x < right; x++)
            {
                var color = bitmap.GetPixel(x, y);
                lumas.Add(0.2126 * color.R + 0.7152 * color.G + 0.0722 * color.B);
                if (Math.Abs(color.R - 18) + Math.Abs(color.G - 20) + Math.Abs(color.B - 26) <= 12)
                {
                    backgroundCount++;
                }
            }
        }
        lumas.Sort();
        var p10Index = Math.Clamp((int)Math.Floor(lumas.Count * 0.10), 0, Math.Max(0, lumas.Count - 1));
        return new Dictionary<string, object?>
        {
            ["center_sample_count"] = lumas.Count,
            ["center_mean_luma"] = lumas.Count > 0 ? lumas.Average() : 0.0,
            ["center_p10_luma"] = lumas.Count > 0 ? lumas[p10Index] : 0.0,
            ["center_background_fraction"] = lumas.Count > 0
                ? (double)backgroundCount / lumas.Count
                : 1.0,
        };
    }

    private static Form CreateHiddenHost() => new()
    {
        Text = "CDMW hidden untextured readability proof",
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
