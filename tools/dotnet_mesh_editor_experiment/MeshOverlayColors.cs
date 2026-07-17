using System.Drawing;
using System.IO;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal readonly record struct MeshOverlayColors(Color Wire, Color Vertex)
{
    public static MeshOverlayColors Default { get; } = new(
        Color.FromArgb(0, 0, 0),
        Color.FromArgb(255, 174, 40));

    public static Color AutomaticXRayWire { get; } = Color.FromArgb(245, 248, 252);
    public static Color AutomaticXRayVertex { get; } = Color.FromArgb(255, 88, 214);

    public MeshOverlayColors Normalized() => new(
        Color.FromArgb(Wire.R, Wire.G, Wire.B),
        Color.FromArgb(Vertex.R, Vertex.G, Vertex.B));

    public Color ActiveWire(bool xray) => xray ? AutomaticXRayWire : Wire;

    public Color ActiveVertex(bool xray) => xray ? AutomaticXRayVertex : Vertex;

    public static string Hex(Color color) => $"#{color.R:X2}{color.G:X2}{color.B:X2}";
}

internal readonly record struct MeshOverlaySizing(float WireWidthPixels, float VertexMarkerSizePixels)
{
    internal const float DefaultWireWidthPixels = 1.35f;
    internal const float MinimumWireWidthPixels = 1.0f;
    internal const float MaximumWireWidthPixels = 6.0f;
    internal const float DefaultVertexMarkerSizePixels = 7.0f;
    internal const float MinimumVertexMarkerSizePixels = 1.0f;
    internal const float MaximumVertexMarkerSizePixels = 24.0f;

    public static MeshOverlaySizing Default { get; } = new(
        DefaultWireWidthPixels,
        DefaultVertexMarkerSizePixels);

    public MeshOverlaySizing Normalized() => new(
        Math.Clamp(WireWidthPixels, MinimumWireWidthPixels, MaximumWireWidthPixels),
        Math.Clamp(VertexMarkerSizePixels, MinimumVertexMarkerSizePixels, MaximumVertexMarkerSizePixels));
}

internal readonly record struct MeshOverlaySettings(MeshOverlayColors Colors, MeshOverlaySizing Sizing)
{
    public static MeshOverlaySettings Default { get; } = new(
        MeshOverlayColors.Default,
        MeshOverlaySizing.Default);

    public MeshOverlaySettings Normalized() => new(
        Colors.Normalized(),
        Sizing.Normalized());
}

internal static class MeshOverlayPreferences
{
    internal const string Schema = "cdmw_mesh_overlay_preferences_v2";
    internal const string LegacyColorSchema = "cdmw_mesh_overlay_colors_v1";

    internal static string SettingsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "CrimsonDesertModWorkbench",
        "mesh-editor-overlay-colors.json");

    internal static MeshOverlaySettings Load()
    {
        try
        {
            var path = SettingsPath;
            if (!File.Exists(path))
            {
                return MeshOverlaySettings.Default;
            }
            using var document = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
            var root = document.RootElement;
            var schema = root.TryGetProperty("schema", out var schemaValue)
                ? schemaValue.GetString() ?? string.Empty
                : string.Empty;
            if (!string.Equals(schema, Schema, StringComparison.Ordinal)
                && !string.Equals(schema, LegacyColorSchema, StringComparison.Ordinal))
            {
                return MeshOverlaySettings.Default;
            }
            var colors = new MeshOverlayColors(
                ParseColor(root, "wire_color", MeshOverlayColors.Default.Wire),
                ParseColor(root, "vertex_color", MeshOverlayColors.Default.Vertex));
            var sizing = string.Equals(schema, Schema, StringComparison.Ordinal)
                ? new MeshOverlaySizing(
                    ParseSingle(root, "wire_width_pixels", MeshOverlaySizing.Default.WireWidthPixels),
                    ParseSingle(root, "vertex_marker_size_pixels", MeshOverlaySizing.Default.VertexMarkerSizePixels))
                : MeshOverlaySizing.Default;
            return new MeshOverlaySettings(colors, sizing).Normalized();
        }
        catch
        {
            return MeshOverlaySettings.Default;
        }
    }

    internal static bool TrySave(MeshOverlaySettings settings, out string error)
    {
        var path = SettingsPath;
        var staging = $"{path}.{Environment.ProcessId}.tmp";
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var normalized = settings.Normalized();
            var payload = new Dictionary<string, object?>
            {
                ["schema"] = Schema,
                ["wire_color"] = MeshOverlayColors.Hex(normalized.Colors.Wire),
                ["vertex_color"] = MeshOverlayColors.Hex(normalized.Colors.Vertex),
                ["wire_width_pixels"] = normalized.Sizing.WireWidthPixels,
                ["vertex_marker_size_pixels"] = normalized.Sizing.VertexMarkerSizePixels,
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

    private static float ParseSingle(JsonElement root, string propertyName, float fallback)
    {
        return root.TryGetProperty(propertyName, out var value)
            && value.ValueKind == JsonValueKind.Number
            && value.TryGetSingle(out var parsed)
                ? parsed
                : fallback;
    }
}
