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
        if (tool is "vertex" or "remove")
        {
            tool = "select";
        }
        var enabled = !root.TryGetProperty("enabled", out var enabledElement)
            || enabledElement.ValueKind != JsonValueKind.False;
        if (!enabled)
        {
            if (!string.Equals("orbit", _viewport.ActiveTool, StringComparison.OrdinalIgnoreCase))
            {
                ActivateTool("orbit", "Orbit");
            }
            WriteProtocolEvent("tool_state_applied", new Dictionary<string, object?>
            {
                ["enabled"] = false,
                ["tool"] = "orbit",
                ["target_mode"] = _viewport.CurrentTargetMode(),
                ["local_selection"] = _viewport.SelectionSnapshotPayload(),
                ["selected_part_index"] = _viewport.SelectedSubmeshIndex,
                ["parts_list_selected_index"] = _submeshList.SelectedIndex,
                ["parts_list_selected_indices"] = _submeshList.SelectedIndices.Cast<int>().ToArray(),
            });
            return;
        }
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
        // Re-asserting the tool the viewport already has is not a no-op: it runs
        // SyncToolRailPageToActiveTool, which closes whichever rail page is open.
        // The host republishes this state on every control refresh, so without
        // the guard a Topology, Colour or Morph page cannot stay open at all.
        if (!string.Equals(tool, _viewport.ActiveTool, StringComparison.OrdinalIgnoreCase))
        {
            ActivateTool(tool, tool[..1].ToUpperInvariant() + tool[1..]);
        }
        WriteProtocolEvent("tool_state_applied", new Dictionary<string, object?>
        {
            ["enabled"] = true,
            ["tool"] = tool,
            ["target_mode"] = _viewport.CurrentTargetMode(),
            ["local_selection"] = _viewport.SelectionSnapshotPayload(),
            ["selected_part_index"] = _viewport.SelectedSubmeshIndex,
            ["parts_list_selected_index"] = _submeshList.SelectedIndex,
            ["parts_list_selected_indices"] = _submeshList.SelectedIndices.Cast<int>().ToArray(),
        });
    }
}
