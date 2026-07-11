using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private static readonly HashSet<string> HostTools = new(StringComparer.OrdinalIgnoreCase)
    {
        "orbit", "select", "move", "grab", "smooth", "inflate", "pinch"
    };

    private void ApplyHostToolState(JsonElement root)
    {
        var tool = JsonString(root, "tool").Trim().ToLowerInvariant();
        if (!HostTools.Contains(tool))
        {
            WriteProtocolEvent("error", new Dictionary<string, object?>
            {
                ["code"] = "invalid_tool_state",
                ["message"] = $"Unsupported Mesh .NET tool: {tool}"
            });
            return;
        }
        var target = JsonString(root, "target_mode").Trim();
        var targetItem = _selectionTarget.Items.Cast<object>()
            .FirstOrDefault(item => string.Equals(Convert.ToString(item), target, StringComparison.OrdinalIgnoreCase));
        if (targetItem is not null)
        {
            _selectionTarget.SelectedItem = targetItem;
        }
        _viewport.ActiveTool = tool;
        _statusLabel.Text = $"Tool: {tool}";
        WriteProtocolEvent("tool_state_applied", new Dictionary<string, object?>
        {
            ["tool"] = tool,
            ["target_mode"] = _viewport.CurrentTargetMode()
        });
    }
}
