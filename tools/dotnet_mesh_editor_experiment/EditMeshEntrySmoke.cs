using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Runs the two Edit Mesh entry proofs against a real <see cref="ExperimentForm"/>.
/// The layout smoke builds stand-in controls, which is why neither of the
/// defects these cover could be seen there.
/// </summary>
internal static class EditMeshEntrySmoke
{
    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(arg, "--headless-edit-mesh-entry-smoke", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var reportPath = RequiredValue(args, "--edit-mesh-entry-report");
        Directory.CreateDirectory(
            Path.GetDirectoryName(reportPath)
                ?? throw new InvalidOperationException("Edit Mesh entry report has no parent directory."));
        var root = Path.Combine(
            Path.GetTempPath(),
            $"cdmw-edit-mesh-entry-{Environment.ProcessId}-{Guid.NewGuid():N}");
        var stage = "setup";
        try
        {
            var input = Path.Combine(root, "input");
            var output = Path.Combine(root, "output");
            Directory.CreateDirectory(input);
            Directory.CreateDirectory(output);
            WriteTexturedMaterialPackage(input);
            stage = "synthetic_document";
            var document = HeadlessGpuSparseSoak.BuildSyntheticDocument(300);
            stage = "standalone_form";
            using var form = new ExperimentForm(Options(input, output, embedded: false), document, sourceParseCount: 1);
            stage = "solid_textured_view";
            var solidTextured = form.SolidTexturedViewProof();
            stage = "scene_inspector_entry_layout";
            var sceneInspector = form.SceneInspectorEntryLayoutProof();
            // The helper the workbench launches is embedded, and an embedded
            // helper defers building its authoring panels until the first
            // mesh-edit entry. The rail then adopts sections that were never
            // laid out in a placement flank, which is a different transition
            // from the standalone one above and the one readers actually meet.
            stage = "embedded_form";
            using var embeddedForm = new ExperimentForm(
                Options(input, output, embedded: true),
                document,
                sourceParseCount: 1);
            stage = "scene_inspector_entry_layout_embedded";
            var embeddedSceneInspector = embeddedForm.SceneInspectorEntryLayoutProof();
            stage = "missing_texture_readiness";
            var missingTextureReadiness = form.ResidentPackageTextureFailureProof(
                WriteMissingTexturePackage(root));
            stage = "gpu_binding_rollback";
            var gpuBindingRollback = form.ResidentPackageGpuBindingFailureProof(
                WriteUnbindableTexturePackage(root));
            var report = new Dictionary<string, object?>
            {
                ["ok"] = solidTextured.GetValueOrDefault("ok") is true
                    && sceneInspector.GetValueOrDefault("ok") is true
                    && embeddedSceneInspector.GetValueOrDefault("ok") is true
                    && missingTextureReadiness.GetValueOrDefault("ok") is true
                    && gpuBindingRollback.GetValueOrDefault("ok") is true,
                ["solid_textured_view"] = solidTextured,
                ["scene_inspector_entry_layout"] = sceneInspector,
                ["scene_inspector_entry_layout_embedded"] = embeddedSceneInspector,
                ["missing_texture_readiness"] = missingTextureReadiness,
                ["gpu_binding_rollback"] = gpuBindingRollback,
            };
            File.WriteAllText(
                reportPath,
                JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
            return report.GetValueOrDefault("ok") is true ? 0 : 1;
        }
        catch (Exception ex)
        {
            // A WinExe gate that throws would otherwise surface only as exit
            // code 1 with nothing said about which proof failed to run.
            File.WriteAllText(
                reportPath,
                JsonSerializer.Serialize(
                    new Dictionary<string, object?>
                    {
                        ["ok"] = false,
                        ["stage"] = stage,
                        ["error"] = ex.Message,
                        ["error_type"] = ex.GetType().FullName,
                        ["error_detail"] = ex.ToString(),
                    },
                    new JsonSerializerOptions { WriteIndented = true }));
            return 1;
        }
        finally
        {
            try
            {
                Directory.Delete(root, recursive: true);
            }
            catch
            {
                // The report owns the result; temp cleanup cannot replace it.
            }
        }
    }

    private static void WriteTexturedMaterialPackage(string input)
    {
        var texturePath = Path.Combine(input, "solid-textured-proof.png");
        using (var bitmap = new Bitmap(2, 2))
        {
            bitmap.SetPixel(0, 0, Color.Red);
            bitmap.SetPixel(1, 0, Color.Green);
            bitmap.SetPixel(0, 1, Color.Blue);
            bitmap.SetPixel(1, 1, Color.White);
            bitmap.Save(texturePath, ImageFormat.Png);
        }
        var resourceId = "proof:base";
        var manifest = new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_mesh_material_state_v2",
            ["version"] = 2,
            ["material_signature"] = "solid-textured-proof",
            ["material_slots"] = Array.Empty<object>(),
            ["resources"] = new[]
            {
                new Dictionary<string, object?>
                {
                    ["resource_id"] = resourceId,
                    ["path"] = texturePath,
                    ["fingerprint"] = "solid-textured-proof-base",
                    ["role"] = "replacement",
                    ["submesh_index"] = 0,
                    ["material_channel"] = "base",
                    ["semantic"] = "base",
                    ["color_space"] = "srgb",
                    ["profile"] = "material_authority_true_source",
                    ["required"] = true,
                    ["fallback_policy"] = "block_ready",
                },
            },
            ["submeshes"] = new[]
            {
                new Dictionary<string, object?>
                {
                    ["submesh_index"] = 0,
                    ["material_slot_index"] = 0,
                    ["material"] = "solid-textured-proof",
                    ["resource_channels"] = new Dictionary<string, string>
                    {
                        ["base"] = resourceId,
                    },
                },
            },
        };
        File.WriteAllText(
            Path.Combine(input, "net_materials.json"),
            JsonSerializer.Serialize(manifest));
    }

    private static string WriteMissingTexturePackage(string root)
    {
        var packagePath = Path.Combine(root, "missing-texture-package");
        Directory.CreateDirectory(packagePath);
        var manifestPath = Path.Combine(packagePath, "net_materials.json");
        var missingPath = Path.Combine(packagePath, "missing-base.png");
        var resourceId = "proof:missing-base";
        File.WriteAllText(
            manifestPath,
            JsonSerializer.Serialize(new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_mesh_material_state_v2",
                ["version"] = 2,
                ["material_signature"] = "missing-texture-proof",
                ["material_slots"] = Array.Empty<object>(),
                ["resources"] = new[]
                {
                    new Dictionary<string, object?>
                    {
                        ["resource_id"] = resourceId,
                        ["path"] = missingPath,
                        ["fingerprint"] = "missing-texture-proof-base",
                        ["role"] = "replacement",
                        ["submesh_index"] = 0,
                        ["material_channel"] = "base",
                        ["semantic"] = "base",
                        ["color_space"] = "srgb",
                        ["profile"] = "material_authority_true_source",
                        ["required"] = true,
                        ["fallback_policy"] = "block_ready",
                    },
                },
                ["submeshes"] = new[]
                {
                    new Dictionary<string, object?>
                    {
                        ["submesh_index"] = 0,
                        ["material_slot_index"] = 0,
                        ["material"] = "missing-texture-proof",
                        ["resource_channels"] = new Dictionary<string, string>
                        {
                            ["base"] = resourceId,
                        },
                    },
                },
            }));
        File.WriteAllText(
            Path.Combine(packagePath, "scene.obj"),
            "o missing_texture_proof\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nvn 0 0 1\nf 1/1/1 2/2/1 3/3/1\n");
        File.WriteAllText(Path.Combine(packagePath, "mesh.cdmeta.json"), "{}");
        File.WriteAllText(Path.Combine(packagePath, "dotnet_scene.json"), "{}");
        return packagePath;
    }

    private static string WriteUnbindableTexturePackage(string root)
    {
        var packagePath = Path.Combine(root, "unbindable-texture-package");
        Directory.CreateDirectory(packagePath);
        var texturePath = Path.Combine(packagePath, "decoded-unsupported-channel.png");
        using (var bitmap = new Bitmap(2, 2))
        {
            bitmap.SetPixel(0, 0, Color.Red);
            bitmap.SetPixel(1, 0, Color.Green);
            bitmap.SetPixel(0, 1, Color.Blue);
            bitmap.SetPixel(1, 1, Color.White);
            bitmap.Save(texturePath, ImageFormat.Png);
        }
        var resourceId = "proof:unsupported-channel";
        File.WriteAllText(
            Path.Combine(packagePath, "net_materials.json"),
            JsonSerializer.Serialize(new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_mesh_material_state_v2",
                ["version"] = 2,
                ["material_signature"] = "gpu-binding-rollback-proof",
                ["material_slots"] = Array.Empty<object>(),
                ["resources"] = new[]
                {
                    new Dictionary<string, object?>
                    {
                        ["resource_id"] = resourceId,
                        ["path"] = texturePath,
                        ["fingerprint"] = "gpu-binding-rollback-proof-texture",
                        ["role"] = "replacement",
                        ["submesh_index"] = 0,
                        ["material_channel"] = "unsupported_proof_channel",
                        ["semantic"] = "unsupported_proof_channel",
                        ["color_space"] = "srgb",
                        ["profile"] = "material_authority_true_source",
                        ["required"] = true,
                        ["fallback_policy"] = "block_ready",
                    },
                },
                ["submeshes"] = new[]
                {
                    new Dictionary<string, object?>
                    {
                        ["submesh_index"] = 0,
                        ["material_slot_index"] = 0,
                        ["material"] = "gpu-binding-rollback-proof",
                        ["resource_channels"] = new Dictionary<string, string>
                        {
                            ["unsupported_proof_channel"] = resourceId,
                        },
                    },
                },
            }));
        File.WriteAllText(
            Path.Combine(packagePath, "scene.obj"),
            "o gpu_binding_rollback_proof\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nvn 0 0 1\nf 1/1/1 2/2/1 3/3/1\n");
        File.WriteAllText(Path.Combine(packagePath, "mesh.cdmeta.json"), "{}");
        File.WriteAllText(Path.Combine(packagePath, "dotnet_scene.json"), "{}");
        return packagePath;
    }

    private static LaunchOptions Options(string input, string output, bool embedded) => new(
        input,
        Path.Combine(input, "scene.obj"),
        Path.Combine(input, "metadata.json"),
        Path.Combine(input, "status.json"),
        output,
        Path.Combine(input, "edit_operations.json"),
        Path.Combine(input, "evaluation.md"),
        HeadlessSmoke: true,
        Embedded: embedded,
        Profile: "authoring",
        DeveloperRendererFallback: true,
        // No parent window: this gate exercises the deferred panel build that
        // Embedded selects, not the host reparent, which needs a real HWND.
        ParentHwnd: 0L);

    private static string RequiredValue(string[] args, string name)
    {
        var index = Array.FindIndex(
            args,
            arg => string.Equals(arg, name, StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index + 1 >= args.Length || string.IsNullOrWhiteSpace(args[index + 1]))
        {
            throw new ArgumentException($"{name} requires an output path.");
        }
        return Path.GetFullPath(args[index + 1]);
    }
}
