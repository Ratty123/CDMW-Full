namespace Cdmw.MeshEditorExperiment;

internal static class DotNetPreviewViewModes
{
    public const string Default = "lit";

    public static IReadOnlyList<string> Supported { get; } =
    [
        "lit",
        "game_outdoor",
        "base_direct",
        "normal",
        "uv_checker",
        "base_alpha",
        "part_id",
        "material_response",
        "layer_mask",
    ];

    public static string Normalize(string? value)
    {
        var normalized = (value ?? string.Empty).Trim().ToLowerInvariant();
        return normalized switch
        {
            "lit" or "game_outdoor" or "base_direct" or "normal" or "uv_checker"
                or "base_alpha" or "part_id" or "material_response" or "layer_mask" => normalized,
            _ => Default,
        };
    }

    public static int MaterialDebugMode(string? value) => Normalize(value) switch
    {
        "base_direct" => 1,
        "normal" => 2,
        "uv_checker" => 8,
        "base_alpha" => 9,
        "part_id" => 10,
        "material_response" => 11,
        "layer_mask" => 12,
        _ => 0,
    };

    public static bool UsesGameOutdoorLighting(string? value) =>
        string.Equals(Normalize(value), "game_outdoor", StringComparison.Ordinal);
}
