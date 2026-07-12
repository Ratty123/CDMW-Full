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
        ActivateTool(tool, tool[..1].ToUpperInvariant() + tool[1..]);
        WriteProtocolEvent("tool_state_applied", new Dictionary<string, object?>
        {
            ["tool"] = tool,
            ["target_mode"] = _viewport.CurrentTargetMode(),
            ["local_selection"] = _viewport.SelectionSnapshotPayload(),
            ["selected_part_index"] = _viewport.SelectedSubmeshIndex,
            ["parts_list_selected_index"] = _submeshList.SelectedIndex,
            ["parts_list_selected_indices"] = _submeshList.SelectedIndices.Cast<int>().ToArray(),
        });
    }
}
