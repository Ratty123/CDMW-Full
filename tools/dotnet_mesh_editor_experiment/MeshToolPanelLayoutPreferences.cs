using System.IO;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal readonly record struct MeshToolPanelLayout(int LeftWidth, int RightWidth)
{
    internal const int DefaultLeftWidth = 360;
    internal const int DefaultRightWidth = 380;
    internal const int MinimumLeftWidth = 330;
    internal const int MinimumRightWidth = 360;
    internal const int MaximumPanelWidth = 960;

    internal static MeshToolPanelLayout Default { get; } = new(
        DefaultLeftWidth,
        DefaultRightWidth);

    internal MeshToolPanelLayout Normalized() => new(
        Math.Clamp(LeftWidth, MinimumLeftWidth, MaximumPanelWidth),
        Math.Clamp(RightWidth, MinimumRightWidth, MaximumPanelWidth));
}

internal static class MeshToolPanelLayoutPreferences
{
    internal const string Schema = "cdmw_mesh_tool_panel_layout_v1";

    internal static string SettingsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "CrimsonDesertModWorkbench",
        "mesh-editor-tool-panels.json");

    internal static MeshToolPanelLayout Load()
    {
        try
        {
            var path = SettingsPath;
            if (!File.Exists(path))
            {
                return MeshToolPanelLayout.Default;
            }
            using var document = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
            var root = document.RootElement;
            var schema = root.TryGetProperty("schema", out var schemaValue)
                ? schemaValue.GetString() ?? string.Empty
                : string.Empty;
            if (!string.Equals(schema, Schema, StringComparison.Ordinal))
            {
                return MeshToolPanelLayout.Default;
            }
            return new MeshToolPanelLayout(
                ParseWidth(root, "left_width", MeshToolPanelLayout.DefaultLeftWidth),
                ParseWidth(root, "right_width", MeshToolPanelLayout.DefaultRightWidth)).Normalized();
        }
        catch
        {
            return MeshToolPanelLayout.Default;
        }
    }

    internal static bool TrySave(MeshToolPanelLayout layout, out string error)
    {
        var path = SettingsPath;
        var staging = $"{path}.{Environment.ProcessId}.tmp";
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var normalized = layout.Normalized();
            var payload = new Dictionary<string, object?>
            {
                ["schema"] = Schema,
                ["left_width"] = normalized.LeftWidth,
                ["right_width"] = normalized.RightWidth,
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
                // Preference cleanup must not affect the resident editor.
            }
        }
    }

    private static int ParseWidth(JsonElement root, string propertyName, int fallback)
    {
        return root.TryGetProperty(propertyName, out var value)
            && value.TryGetInt32(out var parsed)
            ? parsed
            : fallback;
    }
}
