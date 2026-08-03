using System.Drawing;
using System.IO;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The viewport's clear colour and world-grid colour, as chosen in the editor's
/// own Viewport section.
/// </summary>
/// <remarks>
/// These ride beside the topology appearance rather than in the host's Preview
/// Settings on purpose: they are picked on the viewport they change, in the same
/// group as the wire and vertex colours, and they have to survive a host that
/// republishes its presentation snapshot after every accepted scene frame. A
/// value chosen here therefore becomes an override the presentation lane cannot
/// overwrite, and is persisted next to the overlay preferences.
/// </remarks>
internal readonly record struct MeshViewportBackgroundColors(Color Background, Color Grid)
{
    // The resident renderer's own defaults, so "not chosen yet" and "chosen back
    // to the default" render identically.
    public static MeshViewportBackgroundColors Default { get; } = new(
        Color.FromArgb(0x3B, 0x3B, 0x3B),
        Color.FromArgb(0x50, 0x50, 0x50));

    public MeshViewportBackgroundColors Normalized() => new(
        Color.FromArgb(Background.R, Background.G, Background.B),
        Color.FromArgb(Grid.R, Grid.G, Grid.B));
}

internal static class MeshViewportBackgroundPreferences
{
    internal const string Schema = "cdmw_mesh_viewport_background_v1";

    internal static string SettingsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "CrimsonDesertModWorkbench",
        "mesh-editor-viewport-background.json");

    internal static MeshViewportBackgroundColors Load()
    {
        try
        {
            var path = SettingsPath;
            if (!File.Exists(path))
            {
                return MeshViewportBackgroundColors.Default;
            }
            using var document = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
            var root = document.RootElement;
            var schema = root.TryGetProperty("schema", out var schemaValue)
                ? schemaValue.GetString() ?? string.Empty
                : string.Empty;
            if (!string.Equals(schema, Schema, StringComparison.Ordinal))
            {
                return MeshViewportBackgroundColors.Default;
            }
            return new MeshViewportBackgroundColors(
                ParseColor(root, "background_color", MeshViewportBackgroundColors.Default.Background),
                ParseColor(root, "grid_color", MeshViewportBackgroundColors.Default.Grid)).Normalized();
        }
        catch
        {
            return MeshViewportBackgroundColors.Default;
        }
    }

    internal static bool TrySave(MeshViewportBackgroundColors colors, out string error)
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
                ["background_color"] = MeshOverlayColors.Hex(normalized.Background),
                ["grid_color"] = MeshOverlayColors.Hex(normalized.Grid),
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
