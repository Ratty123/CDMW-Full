using System.Drawing;
using System.IO;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal readonly record struct GizmoAppearance(
    Color XAxis,
    Color YAxis,
    Color ZAxis,
    Color Highlight,
    Color Label,
    float LineThicknessPixels,
    float SizeScale,
    float LabelSizePixels,
    float HandleSizePixels)
{
    internal const float MinimumLineThicknessPixels = 1.0f;
    internal const float MaximumLineThicknessPixels = 6.0f;
    internal const float MinimumSizeScale = 0.5f;
    internal const float MaximumSizeScale = 3.0f;
    internal const float MinimumLabelSizePixels = 8.0f;
    internal const float MaximumLabelSizePixels = 32.0f;
    internal const float MinimumHandleSizePixels = 4.0f;
    internal const float MaximumHandleSizePixels = 24.0f;

    public static GizmoAppearance Default { get; } = new(
        Color.FromArgb(235, 75, 75),
        Color.FromArgb(80, 220, 105),
        Color.FromArgb(75, 145, 255),
        Color.FromArgb(255, 225, 95),
        Color.FromArgb(245, 248, 252),
        1.0f,
        1.0f,
        12.0f,
        8.0f);

    public GizmoAppearance Normalized() => new(
        Opaque(XAxis),
        Opaque(YAxis),
        Opaque(ZAxis),
        Opaque(Highlight),
        Opaque(Label),
        Math.Clamp(LineThicknessPixels, MinimumLineThicknessPixels, MaximumLineThicknessPixels),
        Math.Clamp(SizeScale, MinimumSizeScale, MaximumSizeScale),
        Math.Clamp(LabelSizePixels, MinimumLabelSizePixels, MaximumLabelSizePixels),
        Math.Clamp(HandleSizePixels, MinimumHandleSizePixels, MaximumHandleSizePixels));

    public Color Axis(string handle) => handle switch
    {
        "x" => XAxis,
        "y" => YAxis,
        _ => ZAxis,
    };

    public float ScaleLength(float baseLength) => Math.Max(0.0001f, baseLength * SizeScale);

    public static string Hex(Color color) => $"#{color.R:X2}{color.G:X2}{color.B:X2}";

    private static Color Opaque(Color color) => Color.FromArgb(color.R, color.G, color.B);
}

internal static class GizmoAppearancePreferences
{
    internal const string Schema = "cdmw_mesh_gizmo_appearance_v1";

    internal static string SettingsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "CrimsonDesertModWorkbench",
        "mesh-editor-gizmo-appearance.json");

    internal static GizmoAppearance Load()
    {
        try
        {
            var path = SettingsPath;
            if (!File.Exists(path))
            {
                return GizmoAppearance.Default;
            }
            using var document = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
            var root = document.RootElement;
            if (!string.Equals(
                    root.TryGetProperty("schema", out var schema) ? schema.GetString() : string.Empty,
                    Schema,
                    StringComparison.Ordinal))
            {
                return GizmoAppearance.Default;
            }
            var defaults = GizmoAppearance.Default;
            return new GizmoAppearance(
                ParseColor(root, "x_axis_color", defaults.XAxis),
                ParseColor(root, "y_axis_color", defaults.YAxis),
                ParseColor(root, "z_axis_color", defaults.ZAxis),
                ParseColor(root, "highlight_color", defaults.Highlight),
                ParseColor(root, "label_color", defaults.Label),
                ParseFloat(root, "line_thickness_pixels", defaults.LineThicknessPixels),
                ParseFloat(root, "size_scale", defaults.SizeScale),
                ParseFloat(root, "label_size_pixels", defaults.LabelSizePixels),
                ParseFloat(root, "handle_size_pixels", defaults.HandleSizePixels)).Normalized();
        }
        catch
        {
            return GizmoAppearance.Default;
        }
    }

    internal static bool TrySave(GizmoAppearance appearance, out string error)
    {
        var path = SettingsPath;
        var staging = $"{path}.{Environment.ProcessId}.tmp";
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var normalized = appearance.Normalized();
            var payload = new Dictionary<string, object?>
            {
                ["schema"] = Schema,
                ["x_axis_color"] = GizmoAppearance.Hex(normalized.XAxis),
                ["y_axis_color"] = GizmoAppearance.Hex(normalized.YAxis),
                ["z_axis_color"] = GizmoAppearance.Hex(normalized.ZAxis),
                ["highlight_color"] = GizmoAppearance.Hex(normalized.Highlight),
                ["label_color"] = GizmoAppearance.Hex(normalized.Label),
                ["line_thickness_pixels"] = normalized.LineThicknessPixels,
                ["size_scale"] = normalized.SizeScale,
                ["label_size_pixels"] = normalized.LabelSizePixels,
                ["handle_size_pixels"] = normalized.HandleSizePixels,
            };
            File.WriteAllText(
                staging,
                JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine,
                new UTF8Encoding(false));
            File.Move(staging, path, overwrite: true);
            error = string.Empty;
            return true;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            return false;
        }
        finally
        {
            try
            {
                if (File.Exists(staging))
                {
                    File.Delete(staging);
                }
            }
            catch
            {
                // A failed preference cleanup must not affect the editor session.
            }
        }
    }

    private static float ParseFloat(JsonElement root, string propertyName, float fallback)
    {
        return root.TryGetProperty(propertyName, out var value)
            && value.ValueKind == JsonValueKind.Number
            && value.TryGetSingle(out var parsed)
            && float.IsFinite(parsed)
                ? parsed
                : fallback;
    }

    private static Color ParseColor(JsonElement root, string propertyName, Color fallback)
    {
        if (!root.TryGetProperty(propertyName, out var value) || value.ValueKind != JsonValueKind.String)
        {
            return fallback;
        }
        var text = (value.GetString() ?? string.Empty).Trim();
        if (text.Length != 7 || text[0] != '#')
        {
            return fallback;
        }
        return int.TryParse(text.AsSpan(1, 2), System.Globalization.NumberStyles.HexNumber, null, out var red)
            && int.TryParse(text.AsSpan(3, 2), System.Globalization.NumberStyles.HexNumber, null, out var green)
            && int.TryParse(text.AsSpan(5, 2), System.Globalization.NumberStyles.HexNumber, null, out var blue)
                ? Color.FromArgb(red, green, blue)
                : fallback;
    }
}
