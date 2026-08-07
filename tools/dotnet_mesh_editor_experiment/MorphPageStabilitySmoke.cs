using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class MorphPageStabilitySmoke
{
    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(arg, "--headless-morph-page-stability-smoke", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var reportPath = RequiredValue(args, "--morph-stability-report");
        Directory.CreateDirectory(
            Path.GetDirectoryName(reportPath)
                ?? throw new InvalidOperationException("Morph stability report has no parent directory."));
        var root = Path.Combine(
            Path.GetTempPath(),
            $"cdmw-morph-page-stability-{Environment.ProcessId}-{Guid.NewGuid():N}");
        try
        {
            var input = Path.Combine(root, "input");
            var output = Path.Combine(root, "output");
            Directory.CreateDirectory(input);
            Directory.CreateDirectory(output);
            var options = new LaunchOptions(
                input,
                Path.Combine(input, "scene.obj"),
                Path.Combine(input, "metadata.json"),
                Path.Combine(input, "status.json"),
                output,
                Path.Combine(input, "edit_operations.json"),
                Path.Combine(input, "evaluation.md"),
                HeadlessSmoke: false,
                Embedded: false,
                Profile: "authoring",
                DeveloperRendererFallback: true,
                ParentHwnd: 0L);
            var document = HeadlessGpuSparseSoak.BuildSyntheticDocument(300);
            using var form = new ExperimentForm(options, document, sourceParseCount: 1);
            var proof = form.MorphPageActivationStabilityProof();
            File.WriteAllText(
                reportPath,
                JsonSerializer.Serialize(proof, new JsonSerializerOptions { WriteIndented = true }));
            return proof.GetValueOrDefault("ok") is true ? 0 : 1;
        }
        catch (Exception ex)
        {
            File.WriteAllText(
                reportPath,
                JsonSerializer.Serialize(
                    new Dictionary<string, object?>
                    {
                        ["ok"] = false,
                        ["error"] = ex.Message,
                        ["error_type"] = ex.GetType().FullName,
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
