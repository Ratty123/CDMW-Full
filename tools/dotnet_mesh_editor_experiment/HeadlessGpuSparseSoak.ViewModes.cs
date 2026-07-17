using System.Drawing;
using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal static partial class HeadlessGpuSparseSoak
{
    private const int DotNetViewModeCaptureSize = 256;

    private static Dictionary<string, object?> DotNetViewModeProof(
        D3D11MaterialViewport viewport,
        NetViewportCamera camera,
        Size clientSize)
    {
        var rows = new List<Dictionary<string, object?>>();
        var outputHashes = new HashSet<string>(StringComparer.Ordinal);
        string? litOutputHash = null;
        var evidenceDirectory = Path.Combine(
            Path.GetTempPath(),
            $"cdmw-dotnet-view-mode-proof-{Guid.NewGuid():N}");
        foreach (var mode in DotNetPreviewViewModes.Supported)
        {
            var debugMode = DotNetPreviewViewModes.MaterialDebugMode(mode);
            viewport.MaterialDebugMode = debugMode;
            viewport.ShowSolid = true;
            viewport.TexturesEnabled = true;
            viewport.ApplyPresentationSettings(new D3D11PresentationSettings
            {
                ViewMode = mode,
                GameOutdoorApprox = DotNetPreviewViewModes.UsesGameOutdoorLighting(mode),
            });
            viewport.UpdateRenderPanes(
                new[]
                {
                    new D3D11RenderPane(
                        new Rectangle(Point.Empty, clientSize),
                        camera,
                        "editable",
                        "textured",
                        debugMode,
                        true,
                        true,
                        false,
                        false,
                        true),
                });
            var resolveCountBefore = viewport.MultisampleResolveCount;
            var rendered = viewport.TryRunHeadlessFrame(
                out var frameMs,
                out _,
                out var error);
            var capturePath = Path.Combine(evidenceDirectory, $"{mode}.png");
            var captured = viewport.TryCaptureReplacementPng(
                capturePath,
                DotNetViewModeCaptureSize,
                DotNetViewModeCaptureSize,
                out var sha256,
                out var captureError);
            if (captured && !string.IsNullOrWhiteSpace(sha256))
            {
                outputHashes.Add(sha256);
                if (string.Equals(mode, DotNetPreviewViewModes.Default, StringComparison.Ordinal))
                {
                    litOutputHash = sha256;
                }
            }
            var outputChangedFromLit = captured
                && !string.IsNullOrWhiteSpace(litOutputHash)
                && (string.Equals(mode, DotNetPreviewViewModes.Default, StringComparison.Ordinal)
                    || !string.Equals(sha256, litOutputHash, StringComparison.Ordinal));
            var rowOk = rendered
                && captured
                && outputChangedFromLit
                && viewport.MultisampleResolveCount > resolveCountBefore
                && viewport.MaterialDebugMode == debugMode
                && string.Equals(viewport.PresentationSettings.ViewMode, mode, StringComparison.Ordinal)
                && viewport.PresentationSettings.GameOutdoorApprox
                    == DotNetPreviewViewModes.UsesGameOutdoorLighting(mode);
            rows.Add(new Dictionary<string, object?>
            {
                ["mode"] = mode,
                ["material_debug_mode"] = debugMode,
                ["rendered"] = rendered,
                ["multisample_resolved"] = viewport.MultisampleResolveCount > resolveCountBefore,
                ["renderer_mode_observed"] = viewport.PresentationSettings.ViewMode,
                ["renderer_debug_mode_observed"] = viewport.MaterialDebugMode,
                ["game_outdoor_lighting"] = viewport.PresentationSettings.GameOutdoorApprox,
                ["frame_ms"] = frameMs,
                ["error"] = error,
                ["capture_path"] = capturePath,
                ["capture_sha256"] = sha256,
                ["capture_error"] = captureError,
                ["output_changed_from_lit"] = outputChangedFromLit,
                ["ok"] = rowOk,
            });
        }

        viewport.ApplyPresentationSettings(new D3D11PresentationSettings());
        viewport.MaterialDebugMode = 0;
        return new Dictionary<string, object?>
        {
            ["ok"] = rows.Count == DotNetPreviewViewModes.Supported.Count
                && rows.All(row => row.GetValueOrDefault("ok") is true),
            ["all_non_lit_outputs_change_from_lit"] = rows.All(row =>
                row.GetValueOrDefault("output_changed_from_lit") is true),
            ["distinct_output_count"] = outputHashes.Count,
            ["evidence_directory"] = evidenceDirectory,
            ["supported_modes"] = DotNetPreviewViewModes.Supported,
            ["rendered_modes"] = rows,
        };
    }
}
