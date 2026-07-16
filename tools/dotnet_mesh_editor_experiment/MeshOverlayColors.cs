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

internal static class MeshOverlayColorPreferences
{
    internal const string Schema = "cdmw_mesh_overlay_colors_v1";

    internal static string SettingsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "CrimsonDesertModWorkbench",
        "mesh-editor-overlay-colors.json");

    internal static MeshOverlayColors Load()
    {
        try
        {
            var path = SettingsPath;
            if (!File.Exists(path))
            {
                return MeshOverlayColors.Default;
            }
            using var document = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
            var root = document.RootElement;
            if (!string.Equals(
                    root.TryGetProperty("schema", out var schema) ? schema.GetString() : string.Empty,
                    Schema,
                    StringComparison.Ordinal))
            {
                return MeshOverlayColors.Default;
            }
            return new MeshOverlayColors(
                ParseColor(root, "wire_color", MeshOverlayColors.Default.Wire),
                ParseColor(root, "vertex_color", MeshOverlayColors.Default.Vertex)).Normalized();
        }
        catch
        {
            return MeshOverlayColors.Default;
        }
    }

    internal static bool TrySave(MeshOverlayColors colors, out string error)
    {
        var path = SettingsPath;
        var staging = $"{path}.{Environment.ProcessId}.tmp";
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var normalized = colors.Normalized();
            var payload = new Dictionary<string, object?>
            {
                ["schema"] = Schema,
                ["wire_color"] = MeshOverlayColors.Hex(normalized.Wire),
                ["vertex_color"] = MeshOverlayColors.Hex(normalized.Vertex),
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
}
