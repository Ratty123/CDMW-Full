using System.Drawing;
using System.IO;
using System.Numerics;
using System.Runtime.InteropServices;

namespace Cdmw.MeshEditorExperiment;

internal static class D3D11UntexturedReadabilityProof
{
    private const int CaptureSize = 128;
    private const double MinimumCenterMeanLuma = 60.0;
    private const double MinimumCenterP10Luma = 52.0;
    private const double MinimumCenterLumaRange = 10.0;
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
            var document = BuildFacetedShape();
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
                    && Convert.ToDouble(metrics.GetValueOrDefault("center_p90_luma") ?? 0.0)
                        - Convert.ToDouble(metrics.GetValueOrDefault("center_p10_luma") ?? 0.0)
                        >= MinimumCenterLumaRange
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

            var archiveLiteWireProof = CaptureArchiveLiteWireProof(
                viewport,
                document,
                center,
                bounds,
                evidenceDirectory,
                rows);

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
                ["archive_lite_matte_wire_overlay_rendered"] = archiveLiteWireProof.GetValueOrDefault("ok") is true,
            };
            return new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_untextured_readability_v1",
                ["evidence_class"] = "hidden_synthetic_gpu_regression",
                ["minimum_center_mean_luma"] = MinimumCenterMeanLuma,
                ["minimum_center_p10_luma"] = MinimumCenterP10Luma,
                ["minimum_center_luma_range"] = MinimumCenterLumaRange,
                ["maximum_center_background_fraction"] = MaximumCenterBackgroundFraction,
                ["captures"] = rows,
                ["archive_lite_matte_wire_proof"] = archiveLiteWireProof,
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

    private static Dictionary<string, object?> CaptureArchiveLiteWireProof(
        D3D11MaterialViewport viewport,
        ObjDocument document,
        Vec3 center,
        (Vec3 Min, Vec3 Max) bounds,
        string evidenceDirectory,
        IReadOnlyList<Dictionary<string, object?>> plainCaptures)
    {
        var camera = NetViewportCamera.Create(
            center,
            bounds,
            0.62f,
            0.22f,
            48.0f,
            0.0f,
            0.0f,
            CaptureSize,
            CaptureSize);
        var overlay = new MeshOverlaySettings(
            new MeshOverlayColors(Color.FromArgb(48, 60, 74), MeshOverlayColors.Default.Vertex),
            new MeshOverlaySizing(1.0f, MeshOverlaySizing.Default.VertexMarkerSizePixels));
        viewport.SetOverlaySettings(overlay);
        viewport.UpdateRenderPanes(new[]
        {
            new D3D11RenderPane(
                new Rectangle(Point.Empty, new Size(CaptureSize, CaptureSize)),
                camera,
                "editable",
                "untextured_wire",
                0,
                false,
                true,
                false,
                false,
                true),
        });
        viewport.UpdateOverlay(
            NetEdgeTopology.Build(document),
            new HashSet<int>(),
            -1,
            null,
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<int>>(),
            new HashSet<int>(),
            -1,
            showWire: true,
            showVertices: false,
            showXRay: false,
            brushCursor: null,
            brushRadius: 24.0f);
        var before = viewport.ResourceMetricsPayload();
        var rendered = viewport.TryRunHeadlessFrame(out var frameMs, out _, out var renderError);
        var capturePath = Path.Combine(evidenceDirectory, "archive_lite_matte_wire.png");
        var captured = viewport.TryCaptureReplacementPng(
            capturePath,
            CaptureSize,
            CaptureSize,
            out var sha256,
            out var captureError);
        var after = viewport.ResourceMetricsPayload();
        var wireDrawAdvanced = Convert.ToInt64(after.GetValueOrDefault("wire_overlay_draws") ?? 0L)
            > Convert.ToInt64(before.GetValueOrDefault("wire_overlay_draws") ?? 0L);
        var configuredStyle = string.Equals(
                after.GetValueOrDefault("wire_overlay_color") as string,
                "#303C4A",
                StringComparison.Ordinal)
            && Math.Abs(Convert.ToSingle(after.GetValueOrDefault("wire_overlay_width_pixels") ?? 0.0f) - 1.0f) <= 0.0001f;
        var plainHash = plainCaptures
            .FirstOrDefault(row => string.Equals(row.GetValueOrDefault("name") as string, "front_oblique", StringComparison.Ordinal))
            ?.GetValueOrDefault("sha256") as string;
        var outputChanged = captured
            && !string.IsNullOrWhiteSpace(sha256)
            && !string.Equals(sha256, plainHash, StringComparison.Ordinal);
        return new Dictionary<string, object?>
        {
            ["ok"] = rendered && captured && wireDrawAdvanced && configuredStyle,
            ["mode"] = "untextured_wire",
            ["textures_enabled"] = false,
            ["capture_scope"] = "solid_only",
            ["rendered"] = rendered,
            ["frame_ms"] = frameMs,
            ["render_error"] = renderError,
            ["captured"] = captured,
            ["capture_path"] = capturePath,
            ["capture_sha256"] = sha256,
            ["capture_error"] = captureError,
            ["output_changed_from_plain"] = outputChanged,
            ["wire_draw_advanced"] = wireDrawAdvanced,
            ["wire_color"] = after.GetValueOrDefault("wire_overlay_color"),
            ["wire_width_pixels"] = after.GetValueOrDefault("wire_overlay_width_pixels"),
        };
    }

    private static ObjDocument BuildFacetedShape()
    {
        var document = new ObjDocument();
        var submesh = new ObjSubmesh("untextured_readability", 0, 0, 0);
        document.Submeshes.Add(submesh);
        var top = new Vector3(0.0f, 1.2f, 0.0f);
        var bottom = new Vector3(0.0f, -1.2f, 0.0f);
        var left = new Vector3(-1.0f, 0.0f, 0.0f);
        var right = new Vector3(1.0f, 0.0f, 0.0f);
        var near = new Vector3(0.0f, 0.0f, -0.85f);
        var far = new Vector3(0.0f, 0.0f, 0.85f);
        AddTriangle(submesh, top, near, right);
        AddTriangle(submesh, top, right, far);
        AddTriangle(submesh, top, far, left);
        AddTriangle(submesh, top, left, near);
        AddTriangle(submesh, bottom, right, near);
        AddTriangle(submesh, bottom, far, right);
        AddTriangle(submesh, bottom, left, far);
        AddTriangle(submesh, bottom, near, left);
        return document;
    }

    private static void AddTriangle(ObjSubmesh submesh, Vector3 first, Vector3 second, Vector3 third)
    {
        var normal = Vector3.Normalize(Vector3.Cross(second - first, third - first));
        var offset = submesh.Vertices.Count;
        foreach (var vertex in new[] { first, second, third })
        {
            submesh.Vertices.Add(new Vec3(vertex.X, vertex.Y, vertex.Z));
            submesh.Normals.Add(new Vec3(normal.X, normal.Y, normal.Z));
        }
        submesh.Uvs.AddRange(new[]
        {
            new Vec2(0.5f, 0.0f),
            new Vec2(0.0f, 1.0f),
            new Vec2(1.0f, 1.0f),
        });
        submesh.Faces.Add(new ObjFace(new[]
        {
            new ObjCorner(offset, offset, offset),
            new ObjCorner(offset + 1, offset + 1, offset + 1),
            new ObjCorner(offset + 2, offset + 2, offset + 2),
        }));
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
        var p90Index = Math.Clamp((int)Math.Floor(lumas.Count * 0.90), 0, Math.Max(0, lumas.Count - 1));
        return new Dictionary<string, object?>
        {
            ["center_sample_count"] = lumas.Count,
            ["center_mean_luma"] = lumas.Count > 0 ? lumas.Average() : 0.0,
            ["center_p10_luma"] = lumas.Count > 0 ? lumas[p10Index] : 0.0,
            ["center_p90_luma"] = lumas.Count > 0 ? lumas[p90Index] : 0.0,
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
