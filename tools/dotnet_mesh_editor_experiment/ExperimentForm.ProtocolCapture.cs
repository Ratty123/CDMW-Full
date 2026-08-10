using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private void HandleCaptureRequest(JsonElement root)
    {
        void Reject(string message)
        {
            var rejected = new Dictionary<string, object?>
            {
                ["status"] = "rejected",
                ["message"] = message,
            };
            CopyMutationEnvelope(root, rejected);
            WriteProtocolEvent("capture_result", rejected);
        }

        var sessionId = JsonString(root, "session_id").Trim();
        var requestId = JsonLongValue(root, "request_id");
        var processGeneration = JsonLongValue(root, "process_generation");
        var sessionMatches = AcceptMaterialSession(sessionId, out var sessionError);
        if (requestId <= 0
            || processGeneration != _residentProcessGeneration
            || !sessionMatches)
        {
            Reject(string.IsNullOrWhiteSpace(sessionError)
                ? "Capture request correlation does not match the resident process."
                : sessionError);
            return;
        }
        var requestedPath = JsonString(root, "output_path");
        string outputRoot;
        string outputPath;
        try
        {
            outputRoot = Path.GetFullPath(_options.OutputDir);
            outputPath = Path.IsPathRooted(requestedPath)
                ? Path.GetFullPath(requestedPath)
                : Path.GetFullPath(Path.Combine(outputRoot, requestedPath));
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            Reject($"Invalid capture output path: {ex.Message}");
            return;
        }
        var outputRootPrefix = outputRoot.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        if (!outputPath.StartsWith(outputRootPrefix, StringComparison.OrdinalIgnoreCase))
        {
            Reject("Capture output must remain inside the package output directory.");
            return;
        }
        if (CapturePathTraversesReparsePoint(outputRoot, outputPath))
        {
            Reject("Capture output must not traverse a reparse-point alias.");
            return;
        }
        var width = (int)Math.Clamp(JsonLongValue(root, "width"), 64, 2048);
        var height = (int)Math.Clamp(JsonLongValue(root, "height"), 64, 2048);
        var ok = _viewport.TryCaptureReplacementPng(outputPath, width, height, out var sha256, out var error);
        var payload = new Dictionary<string, object?>
        {
            ["status"] = ok ? "captured" : "error",
            ["output_path"] = ok ? outputPath : string.Empty,
            ["sha256"] = sha256,
            ["width"] = width,
            ["height"] = height,
            ["ui_excluded"] = true,
            ["grid_excluded"] = true,
            ["gizmo_excluded"] = true,
            ["selection_excluded"] = true,
            ["hover_excluded"] = true,
            ["visible_view_mutated"] = false,
            ["message"] = error,
        };
        CopyMutationEnvelope(root, payload);
        WriteProtocolEvent("capture_result", payload);
    }

    private static bool CapturePathTraversesReparsePoint(string outputRoot, string outputPath)
    {
        static bool IsReparsePoint(string path)
        {
            try
            {
                return File.Exists(path) || Directory.Exists(path)
                    ? (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0
                    : false;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                return true;
            }
        }

        if (IsReparsePoint(outputRoot))
        {
            return true;
        }
        var relative = Path.GetRelativePath(outputRoot, outputPath);
        var current = outputRoot;
        foreach (var component in relative.Split(
            new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar },
            StringSplitOptions.RemoveEmptyEntries)[..^1])
        {
            current = Path.Combine(current, component);
            if (IsReparsePoint(current))
            {
                return true;
            }
        }
        return IsReparsePoint(outputPath);
    }
}
