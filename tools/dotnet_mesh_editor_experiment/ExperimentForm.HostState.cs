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
        // The host's tool_state carries a target_mode, but it names how a stroke
        // applies ("vertex" for the select cursor, "brush"/"selection" for
        // sculpt), not what the Selection target combo should show. The host
        // republishes this state on every control refresh, and "vertex" is the
        // one value that happens to match a combo item -- so writing it here
        // reset a reader's Face/Edge/Part choice back to Vertex after every
        // selection. The combo belongs to this editor; the host never has an
        // authoritative vertex/face/edge/part choice to push.
        // The Select drag mode (brush/lasso/rectangle) IS host state: the
        // builder's Selection combo publishes it. Adopted only when the host
        // value changes: the host republishes tool_state on every control
        // refresh, and re-applying the same combo value would stomp a mode
        // picked on this side between refreshes.
        //
        // Anything that is not one of the three drag shapes is not a drag shape
        // and is discarded before it can touch either the combo or the record
        // of what the host last said. Two publishers write this one field with
        // two vocabularies: the builder sends brush/lasso/rectangle, and the
        // Mesh Editor tab sends its element mode (vertex/face/edge/part).
        // Recording the element mode as "the host's last drag shape" made the
        // builder's very next refresh look like a change back to brush, combo
        // assignment and all -- so a reader who picked Lasso had it taken away
        // again on the next control refresh, every time, which is why lasso
        // appeared not to work at all.
        var selectionDragMode = JsonString(root, "selection_mode").Trim().ToLowerInvariant();
        if (selectionDragMode is "brush" or "lasso" or "rectangle"
            && !string.Equals(selectionDragMode, _lastHostSelectionDragMode, StringComparison.OrdinalIgnoreCase))
        {
            _lastHostSelectionDragMode = selectionDragMode;
            _viewport.SetSelectionDragMode(selectionDragMode);
            var shapeItem = _selectionShape.Items.Cast<object>()
                .FirstOrDefault(item => string.Equals(Convert.ToString(item), selectionDragMode, StringComparison.OrdinalIgnoreCase));
            if (shapeItem is not null)
            {
                _selectionShape.SelectedItem = shapeItem;
            }
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
