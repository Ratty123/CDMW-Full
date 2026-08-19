using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Render one prepared package into a PNG with no window on screen.
///
/// The viewport is a Direct3D control and has always needed a real window handle, so
/// looking at what a package draws meant opening the editor and watching it. That is no
/// good while the machine is being used for something else, and no good in a check that
/// wants to compare two renders. The readability proofs already render into a form parked
/// off-screen and never shown; this does the same for a package on disk, so a caller can
/// build a package, capture it, and look at the file.
///
///   cdmw-mesh-dotnet-editor.exe --capture-package &lt;package dir&gt; --capture-out &lt;png&gt;
///                               [--capture-size 900] [--capture-mode textured]
/// </summary>
internal static class PackageCaptureProof
{
    public static bool Matches(string[] args) =>
        args.Any(arg => string.Equals(arg, "--capture-package", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var packageDirectory = ValueFor(args, "--capture-package");
        var outputPath = ValueFor(args, "--capture-out");
        var size = int.TryParse(ValueFor(args, "--capture-size"), System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out var requested) ? Math.Clamp(requested, 64, 4096) : 900;
        var mode = ValueFor(args, "--capture-mode");
        if (string.IsNullOrWhiteSpace(packageDirectory) || string.IsNullOrWhiteSpace(outputPath))
        {
            Console.Error.WriteLine("usage: --capture-package <package dir> --capture-out <png> [--capture-size N] [--capture-mode textured]");
            return 2;
        }
        var geometryPath = Path.Combine(packageDirectory, "scene.obj");
        if (!File.Exists(geometryPath))
        {
            geometryPath = Path.Combine(packageDirectory, "mesh.obj");
        }
        if (!File.Exists(geometryPath))
        {
            Console.Error.WriteLine($"no scene.obj or mesh.obj in {packageDirectory}");
            return 2;
        }
        try
        {
            var document = ObjDocument.Load(geometryPath);
            var materialsPath = Path.Combine(packageDirectory, "net_materials.json");
            var materials = File.Exists(materialsPath) ? NetMaterialSet.Load(materialsPath) : NetMaterialSet.Empty;
            using var textures = NetTextureSet.Load(materials);
            var scene = NetSceneState.Load(Path.Combine(packageDirectory, "dotnet_scene.json"), document.Submeshes.Count);
            // no Text: the form is never shown, and a title on it would be a UI string the
            // catalogs would have to carry for a window nobody can see
            using var host = new Form
            {
                ClientSize = new Size(size, size),
                StartPosition = FormStartPosition.Manual,
                Location = new Point(-32000, -32000),
                FormBorderStyle = FormBorderStyle.None,
                ShowInTaskbar = false,
                Visible = false,
            };
            using var viewport = new D3D11MaterialViewport(document, materials, textures, scene)
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
                Console.Error.WriteLine($"viewport initialization failed: {initializeError}");
                return 3;
            }
            if (!string.IsNullOrWhiteSpace(mode)
                && MeshDisplayModeState.TryResolve(mode, out var display, out _))
            {
                viewport.ShowSolid = display.Solid;
                viewport.TexturesEnabled = display.Textures;
            }
            var hidden = ValueFor(args, "--capture-hide-submeshes");
            if (!string.IsNullOrWhiteSpace(hidden))
            {
                // what the dialog does when a control hides part of the scene
                scene.SetPresentationHiddenSubmeshes(hidden
                    .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                    .Select(part => int.TryParse(part, System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out var index) ? index : -1));
            }
            viewport.LoadEffectParticlePreview(packageDirectory);
            if (HasFlag(args, "--capture-hide-particles"))
            {
                // what the dialog's Show the particles box does: the item without the fire
                viewport.SetEffectParticlesEnabled(false);
            }
            // frame the whole scene the way a freshly opened viewport does: the camera the
            // capture builds is the one on screen, so it has to be pointed first
            var bounds = document.Bounds();
            var focus = ValueFor(args, "--capture-focus");
            if (string.Equals(focus, "framing", StringComparison.OrdinalIgnoreCase))
            {
                // what the dialog opens on: the framing bounds the package declares
                bounds = (
                    new Vec3(scene.FramingBoundsMinimum.X, scene.FramingBoundsMinimum.Y, scene.FramingBoundsMinimum.Z),
                    new Vec3(scene.FramingBoundsMaximum.X, scene.FramingBoundsMaximum.Y, scene.FramingBoundsMaximum.Z));
            }
            else if (string.Equals(focus, "reference", StringComparison.OrdinalIgnoreCase)
                && scene.ReferenceSubmeshCount > 0)
            {
                // what the dialog frames on: the item, not the effect's reach around it
                var minimum = new Vec3(float.MaxValue, float.MaxValue, float.MaxValue);
                var maximum = new Vec3(float.MinValue, float.MinValue, float.MinValue);
                for (var index = scene.EditableSubmeshCount; index < document.Submeshes.Count; index++)
                {
                    foreach (var vertex in document.Submeshes[index].Vertices)
                    {
                        minimum = new Vec3(
                            Math.Min(minimum.X, vertex.X),
                            Math.Min(minimum.Y, vertex.Y),
                            Math.Min(minimum.Z, vertex.Z));
                        maximum = new Vec3(
                            Math.Max(maximum.X, vertex.X),
                            Math.Max(maximum.Y, vertex.Y),
                            Math.Max(maximum.Z, vertex.Z));
                    }
                }
                if (minimum.X <= maximum.X)
                {
                    bounds = (minimum, maximum);
                }
            }
            var center = new Vec3(
                (bounds.Min.X + bounds.Max.X) * 0.5f,
                (bounds.Min.Y + bounds.Max.Y) * 0.5f,
                (bounds.Min.Z + bounds.Max.Z) * 0.5f);
            var yaw = float.TryParse(ValueFor(args, "--capture-yaw"), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var requestedYaw) ? requestedYaw : 0.62f;
            var pitch = float.TryParse(ValueFor(args, "--capture-pitch"), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var requestedPitch) ? requestedPitch : 0.22f;
            // zoom is pixels per world unit: a subject of extent E fills the frame at
            // 0.8 * width / E, so a sword and a boss effect both arrive framed
            var extent = MathF.Max(
                bounds.Max.X - bounds.Min.X,
                MathF.Max(bounds.Max.Y - bounds.Min.Y, bounds.Max.Z - bounds.Min.Z));
            var zoom = extent > 0.0001f ? 0.8f * size / extent : 48.0f;
            viewport.UpdateCamera(NetViewportCamera.Create(center, bounds, yaw, pitch, zoom, 0.0f, 0.0f, size, size));
            // The particle simulation steps by the real time between frames, so a burst of
            // frames back to back is a few microseconds of fire and nothing has spawned
            // yet. Let real time pass between them when a caller asks to see particles.
            var warmupSeconds = float.TryParse(ValueFor(args, "--capture-warmup-seconds"), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var requestedWarmup)
                ? Math.Clamp(requestedWarmup, 0.0f, 30.0f)
                : 0.0f;
            var frames = warmupSeconds > 0.0f ? (int)Math.Ceiling(warmupSeconds / 0.033f) : 6;
            for (var frame = 0; frame < frames; frame++)
            {
                _ = viewport.TryRunHeadlessFrame(out _, out _, out var frameError);
                if (!string.IsNullOrEmpty(frameError))
                {
                    Console.Error.WriteLine($"frame {frame}: {frameError}");
                }
                if (warmupSeconds > 0.0f)
                {
                    System.Threading.Thread.Sleep(33);
                }
            }
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath)) ?? ".");
            var iconOnly = args.Any(arg => string.Equals(arg, "--capture-icon", StringComparison.OrdinalIgnoreCase));
            var captured = iconOnly
                ? viewport.TryCaptureReplacementPng(outputPath, size, size, out var sha256, out var captureError)
                : viewport.TryCaptureScenePng(outputPath, size, size, out sha256, out captureError);
            if (!captured)
            {
                Console.Error.WriteLine($"capture failed: {captureError}");
                return 4;
            }
            var status = new Dictionary<string, object?>
            {
                ["package"] = packageDirectory,
                ["output"] = outputPath,
                ["sha256"] = sha256,
                ["submeshes"] = document.Submeshes.Count,
                ["editable_submeshes"] = scene.EditableSubmeshCount,
                ["reference_submeshes"] = scene.ReferenceSubmeshCount,
                ["comparison_mode"] = scene.ComparisonMode,
                ["reference_draws_solid"] = scene.ReferenceDrawsSolid,
                ["effect_particles"] = viewport.EffectParticlePreviewStatus(),
                ["metrics"] = viewport.LiveMetricsPayload(),
            };
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(status));
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception.ToString());
            return 5;
        }
    }

    private static bool HasFlag(string[] args, string name)
    {
        return args.Any(argument => string.Equals(argument, name, StringComparison.OrdinalIgnoreCase));
    }

    private static string ValueFor(string[] args, string name)
    {
        for (var index = 0; index < args.Length - 1; index++)
        {
            if (string.Equals(args[index], name, StringComparison.OrdinalIgnoreCase))
            {
                return args[index + 1];
            }
        }
        return string.Empty;
    }
}
