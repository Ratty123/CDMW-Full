using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static partial class VisualAuditBatch
{
    /// <summary>
    /// Optional per-submesh isolation for a measured asset.
    /// </summary>
    /// <remarks>
    /// A whole-object colour average is dominated by whichever part covers the
    /// most pixels, so a thin blade seen near edge-on is drowned out by its own
    /// guard and grip and the measurement says nothing about the blade. Naming
    /// the submeshes to keep hides the rest, which lets one part be measured on
    /// its own. An absent or empty list leaves the scene as authored.
    /// </remarks>
    private static void ApplyRequestedSubmeshIsolation(
        JsonElement asset,
        NetSceneState scene,
        int submeshCount)
    {
        if (!asset.TryGetProperty("only_submesh_indices", out var only)
            || only.ValueKind != JsonValueKind.Array)
        {
            return;
        }
        var keep = only.EnumerateArray()
            .Where(value => value.ValueKind == JsonValueKind.Number)
            .Select(value => value.GetInt32())
            .ToHashSet();
        if (keep.Count == 0)
        {
            return;
        }
        scene.SetPresentationHiddenSubmeshes(
            Enumerable.Range(0, submeshCount).Where(index => !keep.Contains(index)));
    }
}
