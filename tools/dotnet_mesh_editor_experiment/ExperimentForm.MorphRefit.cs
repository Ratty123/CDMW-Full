using System.Globalization;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private sealed record MorphChoice(string Id, string Name)
    {
        public override string ToString() => Name;
    }

    private sealed class MorphSliderControls
    {
        public required string DefinitionId { get; init; }
        public required double Minimum { get; init; }
        public required double Maximum { get; init; }
        public required double DefaultValue { get; init; }
        public required TrackBar Track { get; init; }
        public required NumericUpDown Numeric { get; init; }
        public bool Synchronizing { get; set; }
    }

    private readonly ComboBox _morphProfile = new();
    private readonly ComboBox _morphPreset = new();
    private readonly TableLayoutPanel _morphSliderStack = new();
    private readonly Label _morphDriverStatus = new();
    private readonly Label _morphBindingStatus = new();
    private readonly Label _morphDiagnosticStatus = new();
    private readonly Dictionary<string, MorphSliderControls> _morphSliders = new(StringComparer.Ordinal);
    private readonly List<Button> _topologyMutationButtons = new();
    private bool _syncingMorphUi;
    private bool _morphStateReceived;
    private bool _morphRefreshRequested;
    private bool _morphUnbaked;
    private bool _morphBusy;
    private long _morphStateRevision = -1;
    private long _morphStateRequestId;
    private long _morphFinishRequestId;
    private long _morphEndRequestId;
    private bool _morphFinishPending;
    private string _morphSessionId = string.Empty;
    private string _morphDefinitionSignature = string.Empty;
    private string _morphActiveChangeId = string.Empty;

    private Control BuildMorphRefitSection(TableLayoutPanel stack)
    {
        ConfigureCombo(_morphProfile, Array.Empty<object>(), selectedIndex: 0);
        ConfigureCombo(_morphPreset, Array.Empty<object>(), selectedIndex: 0);
        _morphProfile.Name = "MorphProfileSelector";
        _morphPreset.Name = "MorphPresetSelector";
        _morphProfile.SelectedIndexChanged += (_, _) =>
        {
            if (!_syncingMorphUi && _morphProfile.SelectedItem is MorphChoice choice)
            {
                WriteCommandRequest("morph_activate", new Dictionary<string, object?> { ["profile_id"] = choice.Id });
            }
        };
        _morphPreset.SelectedIndexChanged += (_, _) =>
        {
            if (!_syncingMorphUi && _morphPreset.SelectedItem is MorphChoice choice && choice.Id.Length > 0)
            {
                WriteCommandRequest("morph_apply_preset", new Dictionary<string, object?> { ["preset_id"] = choice.Id });
            }
        };

        ConfigureMorphStatusLabel(_morphDriverStatus, "Driver: not set");
        ConfigureMorphStatusLabel(_morphBindingStatus, "Garment: not bound");
        ConfigureMorphStatusLabel(_morphDiagnosticStatus, "Select or author a topology-matched profile.");
        _morphDiagnosticStatus.MaximumSize = new Size(460, 0);

        _morphSliderStack.Name = "MorphSliderStack";
        _morphSliderStack.ColumnCount = 1;
        _morphSliderStack.RowCount = 0;
        _morphSliderStack.AutoSize = true;
        _morphSliderStack.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        _morphSliderStack.BackColor = ThemeSectionBackground;
        _morphSliderStack.Margin = new Padding(0);
        _morphSliderStack.Padding = new Padding(0);
        _morphSliderStack.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

        var author = StyledActionButton("Author Slider...", () => ShowMorphAuthorDialog());
        var saveProfile = StyledActionButton("Save Profile", () => WriteCommandRequest("morph_save_profile"));
        var deleteProfile = StyledActionButton("Delete Profile", () =>
        {
            if (_morphProfile.SelectedItem is MorphChoice choice)
            {
                WriteCommandRequest("morph_delete_profile", new Dictionary<string, object?> { ["profile_id"] = choice.Id });
            }
        });
        var savePreset = StyledActionButton("Save Preset...", SaveMorphPreset);
        var deletePreset = StyledActionButton("Delete Preset", () =>
        {
            if (_morphPreset.SelectedItem is MorphChoice choice && choice.Id.Length > 0)
            {
                WriteCommandRequest("morph_delete_preset", new Dictionary<string, object?> { ["preset_id"] = choice.Id });
            }
        });
        var setDriver = StyledActionButton("Set Driver", () => WriteCommandRequest("morph_set_driver"));
        var bind = StyledActionButton("Bind Selected Parts", () => WriteCommandRequest("morph_bind"));
        var clear = StyledActionButton("Clear Refit", () => WriteCommandRequest("morph_clear_refit"));
        var reset = StyledActionButton("Reset All", () => WriteCommandRequest("morph_reset"));
        var bake = StyledActionButton("Bake", () => WriteCommandRequest("morph_bake"));

        var body = StackControls(
            LabeledControl("Definition profile", _morphProfile),
            ButtonRow(author, saveProfile, deleteProfile),
            LabeledControl("Value preset", _morphPreset),
            ButtonRow(savePreset, deletePreset),
            _morphSliderStack,
            _morphDriverStatus,
            _morphBindingStatus,
            ButtonRow(setDriver, bind, clear),
            ButtonRow(reset, bake),
            _morphDiagnosticStatus);
        var section = new TableLayoutPanel
        {
            Name = "MorphRefitSection",
            ColumnCount = 1,
            RowCount = 2,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 0, 10),
            Padding = new Padding(0),
        };
        section.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        section.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        section.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        var header = StyledButton("▾  Morph & Refit", 32);
        header.Name = "MorphRefitCollapseButton";
        header.TextAlign = ContentAlignment.MiddleLeft;
        header.Click += (_, _) =>
        {
            body.Visible = !body.Visible;
            header.Text = body.Visible ? "▾  Morph & Refit" : "▸  Morph & Refit";
            section.PerformLayout();
        };
        body.Dock = DockStyle.Top;
        section.Controls.Add(header, 0, 0);
        section.Controls.Add(body, 0, 1);
        AddStackRow(stack, section);
        _meshEditOnlySections.Add(section);
        return section;
    }

    private static void ConfigureMorphStatusLabel(Label label, string text)
    {
        label.Text = text;
        label.AutoSize = true;
        label.ForeColor = ThemeMutedText;
        label.BackColor = ThemeSectionBackground;
        label.Margin = new Padding(0, 0, 0, 6);
    }

    private void RequestMorphStateRefresh()
    {
        if (_morphRefreshRequested
            || _residentMaterialSessionId.Length == 0
            || (_morphStateReceived && string.Equals(_morphSessionId, _residentMaterialSessionId, StringComparison.Ordinal)))
        {
            return;
        }
        _morphRefreshRequested = true;
        WriteCommandRequest("morph_refresh");
    }

    private void ResetMorphStateAuthority()
    {
        _morphStateReceived = false;
        _morphRefreshRequested = false;
        _morphStateRevision = -1;
        _morphStateRequestId = 0;
        _morphSessionId = string.Empty;
        _morphActiveChangeId = string.Empty;
        _morphFinishRequestId = 0;
        _morphEndRequestId = 0;
        _morphFinishPending = false;
        _morphUnbaked = false;
        _morphBusy = false;
        foreach (var button in _topologyMutationButtons)
        {
            button.Enabled = true;
            _helpToolTip.SetToolTip(button, string.Empty);
        }
    }

    private void RequestFinishEditMesh()
    {
        _morphFinishPending = true;
        if (_residentMaterialSessionId.Length > 0
            && (!_morphStateReceived || !string.Equals(_morphSessionId, _residentMaterialSessionId, StringComparison.Ordinal)))
        {
            RequestMorphStateRefresh();
            _statusLabel.Text = "Waiting for resident Morph & Refit state before Finish Edit Mesh...";
            return;
        }
        if (_morphActiveChangeId.Length > 0
            || _morphEndRequestId > 0
            || _morphBusy
            || _pendingMutationRequests.Values.Any(pending =>
                pending.Command.StartsWith("morph_", StringComparison.Ordinal)
                && pending.Command != "morph_finish"))
        {
            _statusLabel.Text = "Waiting for the final Morph & Refit value before Finish Edit Mesh...";
            return;
        }
        BeginFinishCommitOrSave();
    }

    private void BeginFinishCommitOrSave()
    {
        if (!_morphFinishPending)
        {
            return;
        }
        if (!_morphUnbaked)
        {
            _morphFinishPending = false;
            WriteProtocolEvent("save_request");
            return;
        }
        _morphFinishRequestId = WriteCommandRequest("morph_finish");
        if (_morphFinishRequestId <= 0)
        {
            _morphFinishPending = false;
            return;
        }
        _statusLabel.Text = "Committing visible Morph & Refit state before Finish Edit Mesh...";
    }

    private void CompleteMorphCommandResult(PendingMutationRequest pending, bool accepted)
    {
        if (pending.Command == "morph_refresh")
        {
            _morphRefreshRequested = false;
        }
        if (pending.Command == "morph_change" && pending.Phase == "end" && pending.RequestId == _morphEndRequestId)
        {
            _morphEndRequestId = 0;
            if (!accepted)
            {
                _morphBusy = false;
                _morphFinishPending = false;
            }
        }
        if (!accepted && pending.Command.StartsWith("morph_", StringComparison.Ordinal) && pending.Command != "morph_refresh")
        {
            _morphFinishPending = false;
        }
        if (pending.Command != "morph_finish" || pending.RequestId != _morphFinishRequestId)
        {
            return;
        }
        _morphFinishRequestId = 0;
        _morphFinishPending = false;
        if (accepted)
        {
            _morphUnbaked = false;
            WriteProtocolEvent("save_request");
        }
    }

    private void RegisterTopologyMutationButton(Button button)
    {
        _topologyMutationButtons.Add(button);
        button.Enabled = !_morphUnbaked;
    }

    private void HandleMorphStateUpdate(JsonElement root)
    {
        var sessionId = JsonString(root, "session_id").Trim();
        var processGeneration = JsonLongValue(root, "process_generation");
        var requestId = JsonLongValue(root, "request_id");
        var stateRevision = JsonLongValue(root, "state_revision");
        var editRevision = JsonLongValue(root, "edit_revision");
        if (sessionId.Length == 0
            || !string.Equals(sessionId, _residentMaterialSessionId, StringComparison.Ordinal)
            || processGeneration != _residentProcessGeneration
            || requestId <= _morphStateRequestId
            || editRevision < _lastObservedSessionRevision
            || (_morphStateReceived && stateRevision <= _morphStateRevision))
        {
            _statusLabel.Text = "Ignored stale Morph & Refit state.";
            return;
        }
        var changeId = JsonString(root, "change_id").Trim();
        if (_morphActiveChangeId.Length > 0
            && changeId.Length > 0
            && !string.Equals(changeId, _morphActiveChangeId, StringComparison.Ordinal)
            && JsonBoolean(root, "busy"))
        {
            _statusLabel.Text = "Ignored stale Morph & Refit change.";
            return;
        }
        _morphSessionId = sessionId;
        _morphStateRequestId = requestId;
        _morphStateRevision = stateRevision;
        _morphStateReceived = true;
        _morphRefreshRequested = false;
        _morphUnbaked = JsonBoolean(root, "unbaked");
        _morphBusy = JsonBoolean(root, "busy");
        foreach (var button in _topologyMutationButtons)
        {
            button.Enabled = !_morphUnbaked;
            _helpToolTip.SetToolTip(button, _morphUnbaked
                ? "Bake or Reset active procedural sliders before changing topology."
                : string.Empty);
        }
        ApplyMorphChoices(root, "available_profiles", "profile_id", _morphProfile, JsonString(root, "profile_id"));
        ApplyMorphChoices(root, "available_presets", "preset_id", _morphPreset, JsonString(root, "preset_id"), includeEmpty: true);
        ApplyMorphDefinitions(root);
        ApplyMorphRefitStatus(root);
        var diagnostics = JsonStringArray(root, "diagnostics");
        var failure = JsonString(root, "failure").Trim();
        _morphDiagnosticStatus.ForeColor = failure.Length > 0 ? Color.Salmon : ThemeMutedText;
        _morphDiagnosticStatus.Text = failure.Length > 0
            ? failure
            : _morphBusy
                ? "Applying the latest Morph & Refit value..."
                : diagnostics.Count > 0
                ? string.Join(" ", diagnostics)
                : _morphUnbaked
                    ? "Active procedural values are non-destructive. Bake or Reset before topology edits."
                    : "Morph & Refit is ready.";
        var acknowledgement = new Dictionary<string, object?>
        {
            ["session_id"] = sessionId,
            ["process_generation"] = processGeneration,
            ["state_revision"] = stateRevision,
            ["change_id"] = changeId,
        };
        CopyMutationEnvelope(root, acknowledgement);
        WriteProtocolEvent("morph_state_update_ack", acknowledgement);
        if (_morphFinishPending
            && _morphActiveChangeId.Length == 0
            && _morphEndRequestId == 0
            && !_morphBusy
            && !_pendingMutationRequests.Values.Any(pending =>
                pending.Command.StartsWith("morph_", StringComparison.Ordinal)
                && pending.Command != "morph_finish"))
        {
            BeginFinishCommitOrSave();
        }
    }

    private void ApplyMorphChoices(
        JsonElement root,
        string propertyName,
        string idName,
        ComboBox combo,
        string selectedId,
        bool includeEmpty = false)
    {
        if (!root.TryGetProperty(propertyName, out var values) || values.ValueKind != JsonValueKind.Array)
        {
            return;
        }
        var choices = new List<MorphChoice>();
        if (includeEmpty)
        {
            choices.Add(new MorphChoice(string.Empty, "(Current values)"));
        }
        foreach (var item in values.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var id = JsonString(item, idName).Trim();
            if (id.Length > 0)
            {
                choices.Add(new MorphChoice(id, JsonString(item, "name").Trim() is { Length: > 0 } name ? name : id));
            }
        }
        _syncingMorphUi = true;
        try
        {
            combo.BeginUpdate();
            combo.Items.Clear();
            combo.Items.AddRange(choices.Cast<object>().ToArray());
            var selectedIndex = choices.FindIndex(choice => string.Equals(choice.Id, selectedId, StringComparison.Ordinal));
            combo.SelectedIndex = selectedIndex >= 0 ? selectedIndex : includeEmpty && choices.Count > 0 ? 0 : -1;
            if (combo.Items.Count == 0)
            {
                combo.SelectedIndex = -1;
            }
            combo.EndUpdate();
        }
        finally
        {
            _syncingMorphUi = false;
        }
    }

    private void ApplyMorphDefinitions(JsonElement root)
    {
        if (!root.TryGetProperty("definitions", out var definitions) || definitions.ValueKind != JsonValueKind.Array)
        {
            return;
        }
        var items = definitions.EnumerateArray()
            .Where(item => item.ValueKind == JsonValueKind.Object)
            .Select(item => new
            {
                Element = item.Clone(),
                Id = JsonString(item, "definition_id").Trim(),
                Label = JsonString(item, "label").Trim(),
                Category = JsonString(item, "category").Trim(),
                Minimum = JsonDoubleValue(item, "min_percent", -100.0),
                Maximum = JsonDoubleValue(item, "max_percent", 100.0),
                Default = JsonDoubleValue(item, "default_percent", 0.0),
                Value = JsonDoubleValue(item, "value", 0.0),
                Rule = JsonString(item, "rule").Trim(),
                Axis = JsonString(item, "axis").Trim(),
                Amount = JsonDoubleValue(item, "amount", 0.1),
                Feather = JsonLongValue(item, "feather"),
                Falloff = JsonString(item, "falloff").Trim(),
                Mirror = JsonString(item, "mirror_mode").Trim(),
            })
            .Where(item => item.Id.Length > 0)
            .OrderBy(item => item.Category, StringComparer.OrdinalIgnoreCase)
            .ThenBy(item => item.Label, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var signature = string.Join("|", items.Select(item =>
            $"{item.Category}\u001f{item.Id}\u001f{item.Label}\u001f{item.Minimum:R}\u001f{item.Maximum:R}\u001f{item.Default:R}\u001f{item.Rule}\u001f{item.Axis}\u001f{item.Amount:R}\u001f{item.Feather}\u001f{item.Falloff}\u001f{item.Mirror}"));
        if (!string.Equals(signature, _morphDefinitionSignature, StringComparison.Ordinal))
        {
            _morphDefinitionSignature = signature;
            _morphSliders.Clear();
            _morphSliderStack.SuspendLayout();
            _morphSliderStack.Controls.Clear();
            _morphSliderStack.RowStyles.Clear();
            _morphSliderStack.RowCount = 0;
            string? category = null;
            foreach (var item in items)
            {
                if (!string.Equals(category, item.Category, StringComparison.Ordinal))
                {
                    category = item.Category.Length > 0 ? item.Category : "General";
                    var heading = new Label
                    {
                        Text = category,
                        AutoSize = true,
                        Font = new Font(Font, FontStyle.Bold),
                        ForeColor = ThemeAccent,
                        BackColor = ThemeSectionBackground,
                        Margin = new Padding(0, 5, 0, 4),
                    };
                    AddStackRow(_morphSliderStack, heading);
                }
                AddStackRow(_morphSliderStack, CreateMorphSlider(item.Element, item.Id, item.Label, item.Minimum, item.Maximum, item.Default, item.Value));
            }
            _morphSliderStack.ResumeLayout(performLayout: true);
        }
        else
        {
            foreach (var item in items)
            {
                if (_morphSliders.TryGetValue(item.Id, out var controls))
                {
                    SetMorphSliderValue(controls, item.Value);
                }
            }
        }
    }

    private Control CreateMorphSlider(
        JsonElement definition,
        string definitionId,
        string label,
        double minimum,
        double maximum,
        double defaultValue,
        double value)
    {
        const int resolution = 10;
        var track = new TrackBar
        {
            Name = $"MorphSlider_{definitionId}",
            Minimum = (int)Math.Floor(minimum * resolution),
            Maximum = (int)Math.Ceiling(maximum * resolution),
            TickFrequency = Math.Max(1, (int)Math.Round((maximum - minimum) * resolution / 8.0)),
            SmallChange = 1,
            LargeChange = 10,
            AutoSize = false,
            Height = 34,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0),
        };
        var numeric = new NumericUpDown();
        ConfigureNumeric(
            numeric,
            decimalPlaces: 1,
            minimum: (decimal)minimum,
            maximum: (decimal)maximum,
            value: (decimal)Math.Clamp(value, minimum, maximum),
            increment: 1.0M);
        numeric.Width = 74;
        var controls = new MorphSliderControls
        {
            DefinitionId = definitionId,
            Minimum = minimum,
            Maximum = maximum,
            DefaultValue = defaultValue,
            Track = track,
            Numeric = numeric,
        };
        _morphSliders[definitionId] = controls;
        SetMorphSliderValue(controls, value);
        track.MouseDown += (_, _) =>
        {
            _morphActiveChangeId = Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture);
            SendMorphValue(controls, "begin", _morphActiveChangeId);
        };
        track.ValueChanged += (_, _) =>
        {
            if (controls.Synchronizing)
            {
                return;
            }
            controls.Synchronizing = true;
            numeric.Value = Math.Clamp((decimal)track.Value / resolution, numeric.Minimum, numeric.Maximum);
            controls.Synchronizing = false;
            SendMorphValue(controls, _morphActiveChangeId.Length > 0 ? "update" : "end", _morphActiveChangeId);
        };
        track.MouseUp += (_, _) =>
        {
            if (_morphActiveChangeId.Length > 0)
            {
                SendMorphValue(controls, "end", _morphActiveChangeId);
                _morphActiveChangeId = string.Empty;
            }
        };
        numeric.ValueChanged += (_, _) =>
        {
            if (controls.Synchronizing)
            {
                return;
            }
            controls.Synchronizing = true;
            track.Value = Math.Clamp((int)Math.Round((double)numeric.Value * resolution), track.Minimum, track.Maximum);
            controls.Synchronizing = false;
            SendMorphValue(controls, "end", Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture));
        };
        var reset = StyledActionButton("Reset", () =>
        {
            SetMorphSliderValue(controls, controls.DefaultValue);
            SendMorphValue(controls, "end", Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture));
        });
        reset.MinimumSize = new Size(58, reset.MinimumSize.Height);
        var edit = StyledActionButton("Edit...", () => ShowMorphAuthorDialog(definition));
        var delete = StyledActionButton("Delete", () => WriteCommandRequest(
            "morph_delete_definition",
            new Dictionary<string, object?> { ["definition_id"] = definitionId }));
        var labelControl = new Label
        {
            Text = label.Length > 0 ? label : definitionId,
            AutoSize = true,
            ForeColor = ThemeText,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 0, 2),
        };
        return StackControls(labelControl, track, ButtonRow(numeric, reset, edit, delete));
    }

    private static void SetMorphSliderValue(MorphSliderControls controls, double value)
    {
        const int resolution = 10;
        controls.Synchronizing = true;
        try
        {
            var normalized = Math.Clamp(value, controls.Minimum, controls.Maximum);
            controls.Track.Value = Math.Clamp((int)Math.Round(normalized * resolution), controls.Track.Minimum, controls.Track.Maximum);
            controls.Numeric.Value = Math.Clamp((decimal)normalized, controls.Numeric.Minimum, controls.Numeric.Maximum);
        }
        finally
        {
            controls.Synchronizing = false;
        }
    }

    private void SendMorphValue(MorphSliderControls controls, string phase, string changeId)
    {
        var id = changeId.Length > 0 ? changeId : Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture);
        _morphBusy = true;
        var requestId = WriteCommandRequest("morph_change", new Dictionary<string, object?>
        {
            ["definition_id"] = controls.DefinitionId,
            ["value"] = (double)controls.Numeric.Value,
            ["phase"] = phase,
            ["change_id"] = id,
        });
        if (requestId <= 0)
        {
            _morphBusy = false;
        }
        else if (phase == "end")
        {
            _morphEndRequestId = requestId;
        }
    }

    private void ApplyMorphRefitStatus(JsonElement root)
    {
        var drivers = JsonIntValues(root, "driver_submesh_indices");
        _morphDriverStatus.Text = drivers.Count > 0
            ? $"Driver: {string.Join(", ", drivers.Select(index => $"Part {index}"))}"
            : "Driver: not set";
        if (!root.TryGetProperty("refit", out var refit) || refit.ValueKind != JsonValueKind.Object)
        {
            _morphBindingStatus.Text = "Garment: not bound";
            return;
        }
        var garments = JsonIntValues(refit, "garment_submesh_indices");
        var bound = JsonLongValue(refit, "bound_vertex_count");
        if (garments.Count == 0 || bound <= 0)
        {
            _morphBindingStatus.Text = "Garment: not bound";
            _morphBindingStatus.ForeColor = ThemeMutedText;
            return;
        }
        var maximum = JsonDoubleValue(refit, "maximum_distance", 0.0);
        var p95 = JsonDoubleValue(refit, "p95_distance", 0.0);
        var warning = JsonBoolean(refit, "distance_warning");
        _morphBindingStatus.Text = $"Garment: {bound} vertices | max {maximum:G4} | p95 {p95:G4}";
        _morphBindingStatus.ForeColor = warning ? Color.Gold : ThemeMutedText;
    }

    private void ShowMorphAuthorDialog(JsonElement? definition = null)
    {
        using var dialog = new MorphAuthorDialog(
            _morphProfile.SelectedItem is MorphChoice profile ? profile.Id : string.Empty,
            _morphProfile.SelectedItem is MorphChoice namedProfile ? namedProfile.Name : string.Empty,
            definition,
            ThemeWindowBackground,
            ThemeSectionBackground,
            ThemeInputBackground,
            ThemeText,
            ThemeMutedText);
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }
        var payload = dialog.Payload;
        payload["preserve_selection"] = definition.HasValue;
        payload["source_definition_id"] = definition.HasValue
            ? JsonString(definition.Value, "definition_id").Trim()
            : string.Empty;
        payload["local_basis"] = MorphLocalBasis(definition);
        WriteCommandRequest("morph_author_definition", payload);
    }

    private static double[][] MorphLocalBasis(JsonElement? definition)
    {
        static double[][] Identity() =>
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ];
        if (!definition.HasValue
            || !definition.Value.TryGetProperty("local_basis", out var rawBasis)
            || rawBasis.ValueKind != JsonValueKind.Array)
        {
            return Identity();
        }
        var basis = new List<double[]>();
        foreach (var rawAxis in rawBasis.EnumerateArray())
        {
            if (rawAxis.ValueKind != JsonValueKind.Array)
            {
                return Identity();
            }
            var axis = rawAxis.EnumerateArray()
                .Select(value => value.TryGetDouble(out var number) && double.IsFinite(number) ? number : double.NaN)
                .ToArray();
            if (axis.Length != 3 || axis.Any(value => !double.IsFinite(value)))
            {
                return Identity();
            }
            basis.Add(axis);
        }
        return basis.Count == 3 ? basis.ToArray() : Identity();
    }

    private void SaveMorphPreset()
    {
        using var dialog = new MorphPresetNameDialog(ThemeWindowBackground, ThemeInputBackground, ThemeText);
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }
        WriteCommandRequest("morph_save_preset", new Dictionary<string, object?>
        {
            ["preset_id"] = dialog.PresetId,
            ["name"] = dialog.PresetName,
        });
    }

    private static List<string> JsonStringArray(JsonElement root, string propertyName)
    {
        var result = new List<string>();
        if (!root.TryGetProperty(propertyName, out var values) || values.ValueKind != JsonValueKind.Array)
        {
            return result;
        }
        foreach (var item in values.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.String && item.GetString() is { Length: > 0 } value)
            {
                result.Add(value);
            }
        }
        return result;
    }
}

internal sealed class MorphAuthorDialog : Form
{
    private readonly TextBox _profileId = new();
    private readonly TextBox _profileName = new();
    private readonly TextBox _definitionId = new();
    private readonly TextBox _label = new();
    private readonly TextBox _category = new();
    private readonly ComboBox _rule = new();
    private readonly ComboBox _axis = new();
    private readonly ComboBox _falloff = new();
    private readonly ComboBox _mirror = new();
    private readonly NumericUpDown _amount = new();
    private readonly NumericUpDown _feather = new();
    private readonly NumericUpDown _minimum = new();
    private readonly NumericUpDown _maximum = new();

    public Dictionary<string, object?> Payload => new()
    {
        ["profile_id"] = _profileId.Text.Trim(),
        ["profile_name"] = _profileName.Text.Trim(),
        ["definition_id"] = _definitionId.Text.Trim(),
        ["label"] = _label.Text.Trim(),
        ["category"] = _category.Text.Trim(),
        ["rule"] = Convert.ToString(_rule.SelectedItem, CultureInfo.InvariantCulture)?.ToLowerInvariant(),
        ["axis"] = Convert.ToString(_axis.SelectedItem, CultureInfo.InvariantCulture)?.ToLowerInvariant(),
        ["amount"] = (double)_amount.Value,
        ["feather"] = (int)_feather.Value,
        ["falloff"] = Convert.ToString(_falloff.SelectedItem, CultureInfo.InvariantCulture)?.ToLowerInvariant(),
        ["mirror_mode"] = Convert.ToString(_mirror.SelectedItem, CultureInfo.InvariantCulture)?.ToLowerInvariant(),
        ["min_percent"] = (double)_minimum.Value,
        ["max_percent"] = (double)_maximum.Value,
        ["default_percent"] = 0.0,
    };

    public MorphAuthorDialog(
        string profileId,
        string profileName,
        JsonElement? definition,
        Color background,
        Color section,
        Color input,
        Color text,
        Color muted)
    {
        var hasDefinition = definition.HasValue && definition.Value.ValueKind == JsonValueKind.Object;
        string DefinitionString(string name, string fallback)
        {
            if (!hasDefinition || !definition!.Value.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String)
            {
                return fallback;
            }
            return value.GetString()?.Trim() is { Length: > 0 } textValue ? textValue : fallback;
        }
        double DefinitionDouble(string name, double fallback)
        {
            if (!hasDefinition || !definition!.Value.TryGetProperty(name, out var value) || !value.TryGetDouble(out var number) || !double.IsFinite(number))
            {
                return fallback;
            }
            return number;
        }
        int DefinitionInt(string name, int fallback)
        {
            if (!hasDefinition || !definition!.Value.TryGetProperty(name, out var value) || !value.TryGetInt32(out var number))
            {
                return fallback;
            }
            return number;
        }

        Text = hasDefinition ? "Edit Procedural Slider" : "Author Procedural Slider";
        Width = 480;
        Height = 650;
        MinimumSize = new Size(440, 560);
        StartPosition = FormStartPosition.CenterParent;
        BackColor = background;
        ForeColor = text;
        FormBorderStyle = FormBorderStyle.SizableToolWindow;
        _profileId.Text = profileId.Length > 0 ? profileId : $"profile-{Guid.NewGuid():N}"[..18];
        _profileName.Text = profileName.Length > 0 ? profileName : "My Morph Profile";
        _definitionId.Text = DefinitionString("definition_id", $"slider-{Guid.NewGuid():N}"[..17]);
        _label.Text = DefinitionString("label", "New Slider");
        _category.Text = DefinitionString("category", "Body");
        foreach (var combo in new[] { _rule, _axis, _falloff, _mirror })
        {
            combo.DropDownStyle = ComboBoxStyle.DropDownList;
            combo.BackColor = input;
            combo.ForeColor = text;
            combo.FlatStyle = FlatStyle.Flat;
        }
        _rule.Items.AddRange(new object[] { "Volume", "Scale", "Move", "Flatten", "Taper", "Twist" });
        _axis.Items.AddRange(new object[] { "X", "Y", "Z" });
        _falloff.Items.AddRange(new object[] { "Smooth", "Linear", "Constant" });
        _mirror.Items.AddRange(new object[] { "Off", "X", "Y", "Z" });
        SelectComboValue(_rule, DefinitionString("rule", "volume"));
        SelectComboValue(_axis, DefinitionString("axis", "y"));
        SelectComboValue(_falloff, DefinitionString("falloff", "smooth"));
        SelectComboValue(_mirror, DefinitionString("mirror_mode", "off"));
        ConfigureNumber(_amount, -1000, 1000, (decimal)Math.Clamp(DefinitionDouble("amount", 0.1), -1000.0, 1000.0), 0.01M, 4, input, text);
        ConfigureNumber(_feather, 0, 64, Math.Clamp(DefinitionInt("feather", 2), 0, 64), 1, 0, input, text);
        ConfigureNumber(_minimum, -1000, 1000, (decimal)Math.Clamp(DefinitionDouble("min_percent", -100.0), -1000.0, 1000.0), 5, 1, input, text);
        ConfigureNumber(_maximum, -1000, 1000, (decimal)Math.Clamp(DefinitionDouble("max_percent", 100.0), -1000.0, 1000.0), 5, 1, input, text);
        foreach (var box in new[] { _profileId, _profileName, _definitionId, _label, _category })
        {
            box.BackColor = input;
            box.ForeColor = text;
            box.BorderStyle = BorderStyle.FixedSingle;
        }
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            ColumnCount = 1,
            RowCount = 0,
            Padding = new Padding(12),
            BackColor = section,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        AddField(layout, "Profile id", _profileId, muted, section);
        AddField(layout, "Profile name", _profileName, muted, section);
        AddField(layout, "Slider id", _definitionId, muted, section);
        AddField(layout, "Slider label", _label, muted, section);
        AddField(layout, "Category", _category, muted, section);
        AddField(layout, "Procedural rule", _rule, muted, section);
        AddField(layout, "Local axis (World XYZ basis)", _axis, muted, section);
        AddField(layout, "100% amount", _amount, muted, section);
        AddField(layout, "Selection feather rings", _feather, muted, section);
        AddField(layout, "Falloff", _falloff, muted, section);
        AddField(layout, "Strict mirror", _mirror, muted, section);
        AddField(layout, "Minimum percent", _minimum, muted, section);
        AddField(layout, "Maximum percent", _maximum, muted, section);
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, FlowDirection = FlowDirection.RightToLeft };
        var ok = new Button { Text = hasDefinition ? "Update" : "Create", DialogResult = DialogResult.OK, AutoSize = true };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, AutoSize = true };
        buttons.Controls.Add(ok);
        buttons.Controls.Add(cancel);
        layout.RowCount++;
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.Controls.Add(buttons, 0, layout.RowCount - 1);
        Controls.Add(layout);
        AcceptButton = ok;
        CancelButton = cancel;
    }

    private static void SelectComboValue(ComboBox combo, string value)
    {
        for (var index = 0; index < combo.Items.Count; index++)
        {
            if (string.Equals(Convert.ToString(combo.Items[index], CultureInfo.InvariantCulture), value, StringComparison.OrdinalIgnoreCase))
            {
                combo.SelectedIndex = index;
                return;
            }
        }
        combo.SelectedIndex = combo.Items.Count > 0 ? 0 : -1;
    }

    private static void ConfigureNumber(NumericUpDown control, decimal min, decimal max, decimal value, decimal increment, int decimals, Color input, Color text)
    {
        control.Minimum = min;
        control.Maximum = max;
        control.Value = value;
        control.Increment = increment;
        control.DecimalPlaces = decimals;
        control.BackColor = input;
        control.ForeColor = text;
        control.BorderStyle = BorderStyle.FixedSingle;
    }

    private static void AddField(TableLayoutPanel layout, string label, Control control, Color muted, Color section)
    {
        var caption = new Label { Text = label, AutoSize = true, ForeColor = muted, BackColor = section, Margin = new Padding(0, 5, 0, 2) };
        control.Dock = DockStyle.Top;
        layout.RowCount++;
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.Controls.Add(caption, 0, layout.RowCount - 1);
        layout.RowCount++;
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.Controls.Add(control, 0, layout.RowCount - 1);
    }
}

internal sealed class MorphPresetNameDialog : Form
{
    private readonly TextBox _name = new();
    public string PresetName => _name.Text.Trim();
    public string PresetId => string.Join("-", PresetName.ToLowerInvariant().Split(
        new[] { ' ', '\t', '/', '\\', '.', ':' }, StringSplitOptions.RemoveEmptyEntries));

    public MorphPresetNameDialog(Color background, Color input, Color text)
    {
        Text = "Save Morph Preset";
        Width = 380;
        Height = 150;
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedToolWindow;
        BackColor = background;
        ForeColor = text;
        _name.Text = "My Preset";
        _name.BackColor = input;
        _name.ForeColor = text;
        _name.Dock = DockStyle.Top;
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, AutoSize = true, FlowDirection = FlowDirection.RightToLeft };
        var save = new Button { Text = "Save", DialogResult = DialogResult.OK, AutoSize = true };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, AutoSize = true };
        buttons.Controls.Add(save);
        buttons.Controls.Add(cancel);
        Controls.Add(_name);
        Controls.Add(buttons);
        AcceptButton = save;
        CancelButton = cancel;
    }
}
