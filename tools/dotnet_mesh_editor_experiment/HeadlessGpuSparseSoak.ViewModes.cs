using System.Drawing;

namespace Cdmw.MeshEditorExperiment;

internal static partial class HeadlessGpuSparseSoak
{
    private static Dictionary<string, object?> DotNetViewModeProof(
        D3D11MaterialViewport viewport,
        NetViewportCamera camera,
        Size clientSize)
    {
        var rows = new List<Dictionary<string, object?>>();
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
            var rowOk = rendered
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
                ["ok"] = rowOk,
            });
        }

        viewport.ApplyPresentationSettings(new D3D11PresentationSettings());
        viewport.MaterialDebugMode = 0;
        return new Dictionary<string, object?>
        {
            ["ok"] = rows.Count == DotNetPreviewViewModes.Supported.Count
                && rows.All(row => row.GetValueOrDefault("ok") is true),
            ["supported_modes"] = DotNetPreviewViewModes.Supported,
            ["rendered_modes"] = rows,
        };
    }
}
