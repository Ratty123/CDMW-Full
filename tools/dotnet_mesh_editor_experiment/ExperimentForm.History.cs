using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private sealed record ResidentMutationHistoryUiState(
        bool? UndoEnabled,
        bool? RedoEnabled,
        string[] Items,
        int TopIndex);

    private ResidentMutationHistoryUiState CaptureResidentMutationHistoryState()
    {
        return new ResidentMutationHistoryUiState(
            _undoButton?.Enabled,
            _redoButton?.Enabled,
            _actionHistoryList.Items.Cast<object>()
                .Select(item => item?.ToString() ?? string.Empty)
                .ToArray(),
            _actionHistoryList.TopIndex);
    }

    private void RestoreResidentMutationHistoryState(ResidentMutationHistoryUiState state)
    {
        if (_undoButton is not null && state.UndoEnabled.HasValue)
        {
            _undoButton.Enabled = state.UndoEnabled.Value;
        }
        if (_redoButton is not null && state.RedoEnabled.HasValue)
        {
            _redoButton.Enabled = state.RedoEnabled.Value;
        }
        _actionHistoryList.BeginUpdate();
        try
        {
            _actionHistoryList.Items.Clear();
            _actionHistoryList.Items.AddRange(state.Items.Cast<object>().ToArray());
            if (_actionHistoryList.Items.Count > 0)
            {
                _actionHistoryList.TopIndex = Math.Clamp(
                    state.TopIndex,
                    0,
                    _actionHistoryList.Items.Count - 1);
            }
        }
        finally
        {
            _actionHistoryList.EndUpdate();
        }
    }

    private void ApplyHistoryState(JsonElement root)
    {
        var undoCount = Math.Max(0, JsonLongValue(root, "undo_count"));
        var redoCount = Math.Max(0, JsonLongValue(root, "redo_count"));
        if (_undoButton is not null)
        {
            _undoButton.Enabled = undoCount > 0;
        }
        if (_redoButton is not null)
        {
            _redoButton.Enabled = redoCount > 0;
        }

        _actionHistoryList.BeginUpdate();
        try
        {
            _actionHistoryList.Items.Clear();
            if (!root.TryGetProperty("history_entries", out var entries)
                || entries.ValueKind != JsonValueKind.Array
                || entries.GetArrayLength() == 0)
            {
                _actionHistoryList.Items.Add("No edit actions yet");
                return;
            }

            var cursor = (int)Math.Clamp(
                JsonLongValue(root, "history_cursor"),
                0,
                entries.GetArrayLength());
            var index = 0;
            foreach (var entry in entries.EnumerateArray())
            {
                var label = JsonString(entry, "label").Trim();
                if (label.Length == 0)
                {
                    label = JsonString(entry, "action").Replace('_', ' ').Trim();
                }
                if (label.Length == 0)
                {
                    label = "Mesh edit";
                }
                var state = JsonString(entry, "state").Trim().ToLowerInvariant();
                var marker = state == "undone"
                    ? "[undone] "
                    : index == cursor - 1 ? "> " : "  ";
                _actionHistoryList.Items.Add($"{index + 1:00}  {marker}{label}");
                index++;
            }

            if (_actionHistoryList.Items.Count > 0)
            {
                var focusIndex = cursor > 0 ? cursor - 1 : 0;
                _actionHistoryList.TopIndex = Math.Max(0, focusIndex - 3);
            }
        }
        finally
        {
            _actionHistoryList.EndUpdate();
        }
    }
}
