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
        try
        {
            var input = Path.Combine(root, "input");
            var output = Path.Combine(root, "output");
            Directory.CreateDirectory(input);
            Directory.CreateDirectory(output);
            var document = HeadlessGpuSparseSoak.BuildSyntheticDocument(300);
            using var form = new ExperimentForm(Options(input, output, embedded: false), document, sourceParseCount: 1);
            var solidTextured = form.SolidTexturedViewProof();
            var sceneInspector = form.SceneInspectorEntryLayoutProof();
            // The helper the workbench launches is embedded, and an embedded
            // helper defers building its authoring panels until the first
            // mesh-edit entry. The rail then adopts sections that were never
            // laid out in a placement flank, which is a different transition
            // from the standalone one above and the one readers actually meet.
            using var embeddedForm = new ExperimentForm(
                Options(input, output, embedded: true),
                document,
                sourceParseCount: 1);
            var embeddedSceneInspector = embeddedForm.SceneInspectorEntryLayoutProof();
            var report = new Dictionary<string, object?>
            {
                ["ok"] = solidTextured.GetValueOrDefault("ok") is true
                    && sceneInspector.GetValueOrDefault("ok") is true
                    && embeddedSceneInspector.GetValueOrDefault("ok") is true,
                ["solid_textured_view"] = solidTextured,
                ["scene_inspector_entry_layout"] = sceneInspector,
                ["scene_inspector_entry_layout_embedded"] = embeddedSceneInspector,
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

    private static LaunchOptions Options(string input, string output, bool embedded) => new(
        input,
        Path.Combine(input, "scene.obj"),
        Path.Combine(input, "metadata.json"),
        Path.Combine(input, "status.json"),
        output,
        Path.Combine(input, "edit_operations.json"),
        Path.Combine(input, "evaluation.md"),
        HeadlessSmoke: false,
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
