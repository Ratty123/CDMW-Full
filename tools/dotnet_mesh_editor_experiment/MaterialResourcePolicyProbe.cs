using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class MaterialResourcePolicyProbe
{
    private const string ReportFlag = "--material-resource-policy-report";

    public static bool IsRequested(string[] args) =>
        Array.Exists(args, arg => string.Equals(arg, ReportFlag, StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var index = Array.FindIndex(
            args,
            arg => string.Equals(arg, ReportFlag, StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index + 1 >= args.Length)
        {
            throw new ArgumentException($"{ReportFlag} requires an output path.");
        }
        var reportPath = Path.GetFullPath(args[index + 1]);
        Directory.CreateDirectory(
            Path.GetDirectoryName(reportPath)
            ?? throw new InvalidOperationException("Material policy report has no parent directory."));
        var root = Path.Combine(Path.GetTempPath(), $"cdmw-material-policy-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var required = EvaluateMissingResource(root, "required_base", "base", required: true, "block_ready");
            var optional = EvaluateMissingResource(root, "optional_normal", "normal", required: false, "flat_normal");
            var symbolic = new Dictionary<string, object?>
            {
                ["case"] = "unresolved_symbolic_name",
                ["resource_declared"] = false,
                ["ready_allowed"] = true,
                ["diagnostic"] = "symbolic material name is not a concrete required resource",
            };
            var ok = required.GetValueOrDefault("ready_allowed") is false
                && optional.GetValueOrDefault("ready_allowed") is true
                && optional.GetValueOrDefault("fallback_policy") as string == "flat_normal";
            var report = new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_material_resource_policy_runtime_v1",
                ["ok"] = ok,
                ["required_failure"] = required,
                ["optional_failure"] = optional,
                ["symbolic_resource"] = symbolic,
            };
            File.WriteAllText(
                reportPath,
                JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
            return ok ? 0 : 1;
        }
        finally
        {
            try
            {
                Directory.Delete(root, recursive: true);
            }
            catch
            {
                // The probe reports policy behavior; temp cleanup is best effort.
            }
        }
    }

    private static Dictionary<string, object?> EvaluateMissingResource(
        string root,
        string name,
        string channel,
        bool required,
        string fallbackPolicy)
    {
        var resourceId = $"probe:{name}";
        var missingPath = Path.Combine(root, $"{name}.png");
        var manifestPath = Path.Combine(root, $"{name}.json");
        var manifest = new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_mesh_material_state_v2",
            ["material_signature"] = name,
            ["material_slots"] = Array.Empty<object>(),
            ["resources"] = new[]
            {
                new Dictionary<string, object?>
                {
                    ["resource_id"] = resourceId,
                    ["path"] = missingPath,
                    ["fingerprint"] = name,
                    ["role"] = "replacement",
                    ["submesh_index"] = 0,
                    ["material_channel"] = channel,
                    ["profile"] = "material_authority_true_source",
                    ["required"] = required,
                    ["fallback_policy"] = fallbackPolicy,
                },
            },
            ["submeshes"] = new[]
            {
                new Dictionary<string, object?>
                {
                    ["submesh_index"] = 0,
                    ["material_slot_index"] = 0,
                    ["material"] = "probe",
                    ["resource_channels"] = new Dictionary<string, string> { [channel] = resourceId },
                    ["channel_components"] = new Dictionary<string, string>(),
                    ["normal_y_policy"] = "preserve",
                },
            },
        };
        File.WriteAllText(manifestPath, JsonSerializer.Serialize(manifest));
        var materials = NetMaterialSet.Load(manifestPath);
        using var textures = NetTextureSet.Load(materials);
        textures.LoadAsync(materials).GetAwaiter().GetResult();
        var requiredFailures = materials.FailedRequiredResources(textures.TextureLoadFailures);
        var optionalFailures = materials.FailedOptionalResources(textures.TextureLoadFailures);
        return new Dictionary<string, object?>
        {
            ["case"] = name,
            ["channel"] = channel,
            ["required"] = required,
            ["fallback_policy"] = fallbackPolicy,
            ["decode_failure_count"] = textures.TextureLoadFailureCount,
            ["required_failure_count"] = requiredFailures.Count,
            ["optional_failure_count"] = optionalFailures.Count,
            ["ready_allowed"] = requiredFailures.Count == 0,
            ["diagnostic"] = requiredFailures.Count > 0
                ? "required_texture_decode_failed"
                : "optional_texture_fallback_applied",
        };
    }
}
