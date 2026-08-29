using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private string _outputPolicy = "read_only";
    private string _outputPolicyReason = "Waiting for session output policy.";
    private string _outputDestination = string.Empty;
    private string _meshFormat = string.Empty;
    private string _exactWriteStatus = "read_only";
    private int _outputLodIndex;
    private bool _outputDestinationReady;
    private bool _outputAuthoringEnabled;
    private Label? _outputPolicyLabel;
    private Button? _configureFreeEditButton;
    private Button? _exportFreeEditButton;
    private readonly Dictionary<string, string> _unavailableActionReasons =
        new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _availableActionKeys =
        new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Button> _freeEditOnlyButtons =
        new(StringComparer.OrdinalIgnoreCase);

    private void EnsureOutputPolicyControls()
    {
        _configureFreeEditButton ??= StyledActionButton(
            "Free Edit Output...",
            () => WriteCommandRequest("configure_free_edit"));
        _exportFreeEditButton ??= StyledActionButton(
            "Export Free Edit OBJ",
            () => WriteCommandRequest("export_free_edit"));
        SetHelpText(
            _configureFreeEditButton,
            "Choose a new non-exact OBJ output folder. The source asset remains unchanged.");
        SetHelpText(
            _exportFreeEditButton,
            "Atomically publish the active Free Edit revision as an OBJ package. This is not exact archive writeback.");
    }

    private Button FreeEditTopologyButton(string text, string command)
    {
        var button = CommandButton(text, command);
        button.Visible = false;
        button.Enabled = false;
        _freeEditOnlyButtons[command] = button;
        RegisterTopologyMutationButton(button);
        SetHelpText(button, $"{text} is available only with a proven Free Edit OBJ output destination.");
        return button;
    }

    private void ApplyOutputPolicyState(JsonElement root)
    {
        _meshFormat = JsonString(root, "mesh_format").Trim().ToUpperInvariant();
        _outputLodIndex = Math.Max(0, JsonInt(root, "lod_index", 0));
        _outputPolicy = JsonString(root, "output_policy").Trim().ToLowerInvariant();
        _outputDestination = JsonString(root, "output_destination").Trim();
        _outputDestinationReady = JsonBoolean(root, "output_destination_ready");
        _outputAuthoringEnabled = JsonBoolean(root, "authoring_enabled");
        _exactWriteStatus = JsonString(root, "exact_write_status").Trim().ToLowerInvariant();
        _outputPolicyReason = JsonString(root, "output_policy_reason").Trim();
        _unavailableActionReasons.Clear();
        _availableActionKeys.Clear();
        if (root.TryGetProperty("actions", out var actions)
            && actions.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in actions.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.String
                    && item.GetString() is { Length: > 0 } action)
                {
                    _availableActionKeys.Add(action);
                }
            }
        }
        if (root.TryGetProperty("unavailable_action_reasons", out var reasons)
            && reasons.ValueKind == JsonValueKind.Object)
        {
            foreach (var item in reasons.EnumerateObject())
            {
                if (item.Value.ValueKind == JsonValueKind.String)
                {
                    _unavailableActionReasons[item.Name] = item.Value.GetString() ?? string.Empty;
                }
            }
        }

        ApplyDirectAuthoringOutputContract(
            string.Equals(_outputPolicy, "exact_game_asset", StringComparison.Ordinal));
        ApplyOutputPolicyControls();
    }

    private void ApplyDiagnosticOutputPolicyState(
        string policy,
        bool destinationReady,
        bool authoringEnabled)
    {
        _meshFormat = "PAC";
        _outputLodIndex = 0;
        _outputPolicy = policy;
        _outputDestination = destinationReady ? @"C:\diagnostic\free-edit" : string.Empty;
        _outputDestinationReady = destinationReady;
        _outputAuthoringEnabled = authoringEnabled;
        _exactWriteStatus = policy == "exact_game_asset" ? "exact" : "rebuild";
        _outputPolicyReason = authoringEnabled
            ? string.Empty
            : "Choose a Free Edit output folder before authoring.";
        _availableActionKeys.Clear();
        _availableActionKeys.UnionWith(_freeEditOnlyButtons.Keys);
        ApplyDirectAuthoringOutputContract(policy == "exact_game_asset");
        ApplyOutputPolicyControls();
    }

    private void ApplyOutputPolicyControls()
    {
        EnsureOutputPolicyControls();
        RefreshGeometryLayerButtonState();
        RefreshCreatePartFromSelectionButton();
        ReassertDirectAuthoringBlockedButtons();
        var freeEdit = string.Equals(_outputPolicy, "free_edit_rebuild", StringComparison.Ordinal);
        var readOnly = string.Equals(_outputPolicy, "read_only", StringComparison.Ordinal);
        foreach (var pair in _freeEditOnlyButtons)
        {
            var available = freeEdit && _availableActionKeys.Contains(pair.Key);
            pair.Value.Visible = available;
            pair.Value.Enabled = available && _outputAuthoringEnabled && !_morphUnbaked;
            SetHelpText(
                pair.Value,
                _unavailableActionReasons.GetValueOrDefault(pair.Key)
                ?? (pair.Value.Enabled
                    ? "Free Edit operation; output is a non-exact OBJ package."
                    : _outputPolicyReason));
        }
        foreach (var pair in _toolButtons)
        {
            pair.Value.Enabled = !readOnly || string.Equals(pair.Key, "orbit", StringComparison.OrdinalIgnoreCase)
                || string.Equals(pair.Key, "select", StringComparison.OrdinalIgnoreCase);
            if (!pair.Value.Enabled)
            {
                SetHelpText(pair.Value, _outputPolicyReason);
            }
        }
        foreach (var pair in _toolRailToolButtons)
        {
            pair.Value.Enabled = !readOnly || string.Equals(pair.Key, "select", StringComparison.OrdinalIgnoreCase);
            if (!pair.Value.Enabled)
            {
                SetHelpText(pair.Value, _outputPolicyReason);
            }
        }
        if (_toolRailPageButtons.TryGetValue(ToolRailPage.Topology, out var topology))
        {
            topology.Visible = !readOnly;
            topology.Enabled = !readOnly && _outputAuthoringEnabled;
        }
        if (_toolRailPageButtons.TryGetValue(ToolRailPage.MorphRefit, out var morph))
        {
            morph.Visible = !readOnly;
            morph.Enabled = !readOnly && _outputAuthoringEnabled;
        }
        if (!_outputAuthoringEnabled)
        {
            foreach (var button in _topologyMutationButtons)
            {
                button.Enabled = false;
                SetHelpText(button, _outputPolicyReason);
            }
        }
        if (_configureFreeEditButton is not null)
        {
            _configureFreeEditButton.Visible = !readOnly;
            _configureFreeEditButton.Enabled = !readOnly;
            _configureFreeEditButton.Text = freeEdit
                ? "Change Free Edit Output..."
                : "Free Edit Output...";
        }
        if (_exportFreeEditButton is not null)
        {
            _exportFreeEditButton.Visible = freeEdit;
            _exportFreeEditButton.Enabled = freeEdit && _outputDestinationReady;
        }
        if (_outputPolicyLabel is not null)
        {
            var format = _meshFormat.Length > 0 ? _meshFormat : "UNKNOWN";
            var policy = _outputPolicy switch
            {
                "exact_game_asset" => "Exact Game Asset",
                "free_edit_rebuild" => "Free Edit / Rebuild",
                _ => "Read Only",
            };
            _outputPolicyLabel.Text =
                $"{format} LOD{_outputLodIndex} | {policy} | exact: {_exactWriteStatus.Replace('_', '-')}";
            _outputPolicyLabel.AccessibleName = _outputPolicyLabel.Text;
            SetHelpText(
                _outputPolicyLabel,
                string.Join(
                    Environment.NewLine,
                    new[]
                    {
                        _outputPolicyReason,
                        _outputDestination.Length > 0 ? $"Output: {_outputDestination}" : string.Empty,
                        _unavailableActionReasons.Count > 0
                            ? $"Unavailable operations: {string.Join("; ", _unavailableActionReasons.Values.Distinct())}"
                            : string.Empty,
                        "The writer and validator remain final authority at output time.",
                    }.Where(value => value.Length > 0)));
        }
        foreach (var pair in new[]
        {
            (Button: _layerCopyButton, Action: "copy"),
            (Button: _layerPasteButton, Action: "paste"),
            (Button: _layerDeleteButton, Action: "layer_delete"),
        })
        {
            if (pair.Button is null)
            {
                continue;
            }
            pair.Button.Visible = !readOnly;
            pair.Button.Enabled = pair.Button.Enabled && _outputAuthoringEnabled;
            if (!pair.Button.Enabled)
            {
                SetHelpText(
                    pair.Button,
                    _unavailableActionReasons.GetValueOrDefault(pair.Action)
                    ?? _outputPolicyReason);
            }
        }
        if (_partVisibilityButton is not null)
        {
            _partVisibilityButton.Enabled = !DirectAuthoringRestrictionsActive;
            SetHelpText(
                _partVisibilityButton,
                _partVisibilityButton.Enabled
                    ? "Part visibility is presentation-only and is not stored by any output policy."
                    : _unavailableActionReasons.GetValueOrDefault("toggle_visibility")
                        ?? DirectAuthoringCommandBlocker("toggle_visibility"));
        }
    }

    private bool OutputPolicyBlocksCommand(string command, out string reason)
    {
        reason = string.Empty;
        if (command is "configure_free_edit" or "export_free_edit" or "toggle_visibility"
            or "clear_selection" or "select_all" or "invert" or "grow" or "shrink")
        {
            return false;
        }
        if (_outputAuthoringEnabled)
        {
            return false;
        }
        reason = _unavailableActionReasons.GetValueOrDefault(command)
            ?? (_outputPolicyReason.Length > 0
                ? _outputPolicyReason
                : "Authoring is unavailable for this output policy.");
        return true;
    }
}
