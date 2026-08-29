using System.Globalization;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
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
        ReassertDirectAuthoringBlockedButtons();
        ApplyOutputPolicyControls();
        RefreshCreatePartFromSelectionButton();
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
        ApplySelectedMorphRefitSettings(showSelectionDiagnostic: failure.Length == 0 && !_morphBusy);
        var acknowledgement = new Dictionary<string, object?>
        {
            ["session_id"] = sessionId,
            ["process_generation"] = processGeneration,
            ["state_revision"] = stateRevision,
            ["change_id"] = changeId,
        };
        UpdateMorphWorkflowHint();
        CopyMutationEnvelope(root, acknowledgement);
        WriteProtocolEvent("morph_state_update_ack", acknowledgement);
        ResumePendingFinishIfClear();
        BeginInvoke((Action)ResumeQueuedMorphUiCommandIfClear);
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
            FlushPendingMorphUpdate();
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
            if (_morphActiveChangeId.Length > 0)
            {
                QueueMorphUpdate(controls, _morphActiveChangeId);
            }
            else
            {
                SendMorphValue(controls, "end", Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture));
            }
        };
        track.MouseUp += (_, _) =>
        {
            if (_morphActiveChangeId.Length > 0)
            {
                DiscardPendingMorphUpdate();
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
            DiscardPendingMorphUpdate();
            SendMorphValue(controls, "end", Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture));
        };
        var reset = StyledActionButton("Reset", () =>
        {
            DiscardPendingMorphUpdate();
            SetMorphSliderValue(controls, controls.DefaultValue);
            SendMorphValue(controls, "end", Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture));
        });
        reset.MinimumSize = new Size(58, reset.MinimumSize.Height);
        var edit = StyledActionButton("Edit...", () => ShowMorphAuthorDialog(definition));
        var delete = StyledActionButton("Delete", () => RequestMorphUiCommand(
            "morph_delete_definition",
            new Dictionary<string, object?> { ["definition_id"] = definitionId }));
        delete.Name = $"MorphDeleteDefinition_{definitionId}";
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
        else if (phase == "update")
        {
            _morphUpdateRequestId = requestId;
        }
    }

    private void ApplyMorphRefitStatus(JsonElement root)
    {
        var drivers = JsonIntValues(root, "driver_submesh_indices");
        _morphDriverPartIndices.Clear();
        _morphDriverPartIndices.UnionWith(drivers);
        _morphBoundGarmentPartIndices.Clear();
        _morphGarmentSettings.Clear();
        if (_morphRefitSettingsControl is not null)
        {
            _morphRefitSettingsControl.Enabled = false;
        }
        _morphDriverStatus.Text = drivers.Count > 0
            ? $"Driver: {string.Join(", ", drivers.Select(MorphPartDisplayName))}"
            : "Driver: not set";
        if (!root.TryGetProperty("refit", out var refit) || refit.ValueKind != JsonValueKind.Object)
        {
            _morphBindingStatus.Text = "Garment: not bound";
            return;
        }
        var garments = JsonIntValues(refit, "garment_submesh_indices");
        var bound = JsonLongValue(refit, "bound_vertex_count");
        _morphBoundGarmentPartIndices.UnionWith(garments);
        if (garments.Count == 0 || bound <= 0)
        {
            _morphBindingStatus.Text = "Garment: not bound";
            _morphBindingStatus.ForeColor = ThemeMutedText;
            return;
        }
        if (refit.TryGetProperty("garment_settings", out var rawSettings)
            && rawSettings.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in rawSettings.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Object)
                {
                    continue;
                }
                var submeshIndex = (int)JsonLongValue(item, "submesh_index");
                if (!_morphBoundGarmentPartIndices.Contains(submeshIndex))
                {
                    continue;
                }
                var enabled = !item.TryGetProperty("enabled", out _) || JsonBoolean(item, "enabled");
                _morphGarmentSettings[submeshIndex] = new MorphRefitGarmentState(
                    enabled,
                    JsonDoubleValue(item, "intensity_percent", 100.0),
                    JsonString(item, "mode").Trim().ToLowerInvariant() is { Length: > 0 } mode ? mode : "surface",
                    JsonDoubleValue(item, "clearance_percent", 0.0));
            }
        }
        foreach (var garment in garments)
        {
            _morphGarmentSettings.TryAdd(garment, new MorphRefitGarmentState(true, 100.0, "surface", 0.0));
        }
        var maximum = JsonDoubleValue(refit, "maximum_distance", 0.0);
        var p95 = JsonDoubleValue(refit, "p95_distance", 0.0);
        var warning = JsonBoolean(refit, "distance_warning");
        _morphBindingStatus.Text = $"Garment: {string.Join(", ", garments.Select(MorphPartDisplayName))} | {bound} vertices | max {maximum:G4} | p95 {p95:G4}";
        _morphBindingStatus.ForeColor = warning ? Color.Gold : ThemeMutedText;
        if (_morphRefitSettingsControl is not null)
        {
            _morphRefitSettingsControl.Enabled = true;
        }
    }

    private void ApplySelectedMorphRefitSettings(bool showSelectionDiagnostic = true)
    {
        var selectedParts = SelectedMorphParts();
        var selected = selectedParts
            .Where(part => _morphGarmentSettings.ContainsKey(part.Index))
            .Select(part => _morphGarmentSettings[part.Index])
            .ToArray();
        if (selectedParts.Count == 0 && _morphGarmentSettings.Count == 1)
        {
            selected = new[] { _morphGarmentSettings.Values.Single() };
        }
        var unboundSelected = selectedParts.Any(part => !_morphGarmentSettings.ContainsKey(part.Index));
        var mixed = selected.Length > 1 && selected.Skip(1).Any(settings => settings != selected[0]);
        if (selected.Length == 0 || unboundSelected || mixed)
        {
            if (_morphRefitSettingsControl is not null)
            {
                _morphRefitSettingsControl.Enabled = false;
            }
            if (showSelectionDiagnostic)
            {
                _morphDiagnosticStatus.ForeColor = ThemeMutedText;
                _morphDiagnosticStatus.Text = mixed
                    ? "Selected garments use different refit settings. Select garments with matching settings before applying a batch change."
                    : "Select one or more bound garment parts in the viewport, then apply the refit settings.";
            }
            return;
        }
        if (_morphRefitSettingsControl is not null)
        {
            _morphRefitSettingsControl.Enabled = true;
        }
        var current = selected[0];
        _morphRefitEnabled.Checked = current.Enabled;
        _morphRefitIntensity.Value = Math.Clamp(
            (decimal)current.IntensityPercent,
            _morphRefitIntensity.Minimum,
            _morphRefitIntensity.Maximum);
        _morphRefitClearance.Value = Math.Clamp(
            (decimal)current.ClearancePercent,
            _morphRefitClearance.Minimum,
            _morphRefitClearance.Maximum);
        var modeIndex = _morphRefitMode.Items.Cast<object>()
            .Select((item, index) => (item, index))
            .FirstOrDefault(pair => pair.item is MorphChoice choice
                && string.Equals(choice.Id, current.Mode, StringComparison.OrdinalIgnoreCase)).index;
        _morphRefitMode.SelectedIndex = Math.Max(0, modeIndex);
    }

    private IReadOnlyList<MorphPartChoice> SelectedMorphParts()
    {
        return _viewport.SelectedSubmeshIndices
            .Where(index => index >= 0 && index < _document.Submeshes.Count)
            .Distinct()
            .OrderBy(index => index)
            .Select(index => new MorphPartChoice(index, _document.Submeshes[index].Name))
            .ToArray();
    }

    private IReadOnlyList<MorphPartChoice> AllMorphParts()
    {
        return Enumerable.Range(0, Math.Min(_scene.EditableSubmeshCount, _document.Submeshes.Count))
            .Select(index => new MorphPartChoice(index, _document.Submeshes[index].Name))
            .ToArray();
    }

    private string MorphPartDisplayName(int index)
    {
        return index >= 0 && index < _document.Submeshes.Count
            ? $"{_document.Submeshes[index].Name} (Part {index})"
            : $"Part {index}";
    }

    private void RequestMorphSetDriver()
    {
        var selected = SelectedMorphParts();
        if (selected.Count == 0)
        {
            _morphDiagnosticStatus.ForeColor = Color.Salmon;
            _morphDiagnosticStatus.Text = "Select one or more driver parts in the viewport, then choose Set Selected Driver Parts.";
            return;
        }
        RequestMorphUiCommand("morph_set_driver");
    }

    private void RequestMorphBind()
    {
        var selected = SelectedMorphParts();
        if (selected.Count == 0)
        {
            _morphDiagnosticStatus.ForeColor = Color.Salmon;
            _morphDiagnosticStatus.Text = "Select one or more garment parts in the viewport, then choose Bind Selected Garment Parts.";
            return;
        }
        var overlap = selected.Where(part => _morphDriverPartIndices.Contains(part.Index)).ToArray();
        if (overlap.Length > 0)
        {
            _morphDiagnosticStatus.ForeColor = Color.Salmon;
            _morphDiagnosticStatus.Text = $"A part cannot be both driver and garment: {string.Join(", ", overlap.Select(part => part.Name))}.";
            return;
        }
        RequestMorphUiCommand("morph_bind");
    }

    private void RequestMorphConfigureRefit()
    {
        var selected = SelectedMorphParts();
        if (selected.Count == 0)
        {
            _morphDiagnosticStatus.ForeColor = Color.Salmon;
            _morphDiagnosticStatus.Text = "Select one or more bound garment parts in the viewport, then apply the refit settings.";
            return;
        }
        var unbound = selected.Where(part => !_morphBoundGarmentPartIndices.Contains(part.Index)).ToArray();
        if (unbound.Length > 0)
        {
            _morphDiagnosticStatus.ForeColor = Color.Salmon;
            _morphDiagnosticStatus.Text = $"Refit settings only apply to bound garments: {string.Join(", ", unbound.Select(part => part.Name))}.";
            return;
        }
        var mode = _morphRefitMode.SelectedItem is MorphChoice choice ? choice.Id : "surface";
        RequestMorphUiCommand("morph_configure_refit", new Dictionary<string, object?>
        {
            ["enabled"] = _morphRefitEnabled.Checked,
            ["intensity_percent"] = (double)_morphRefitIntensity.Value,
            ["mode"] = mode,
            ["clearance_percent"] = (double)_morphRefitClearance.Value,
        });
    }

    private void ShowMorphAuthorDialog(JsonElement? definition = null)
    {
        if (_morphWizardSequenceActive)
        {
            _morphDiagnosticStatus.ForeColor = Color.Salmon;
            _morphDiagnosticStatus.Text = "Finish the current Morph profile preview or save before opening another wizard.";
            return;
        }
        if (_viewport.HasPendingSelectionAuthority)
        {
            _morphDiagnosticStatus.ForeColor = Color.Gold;
            _morphDiagnosticStatus.Text = "Wait for the viewport selection to finish, then open Create Profile again.";
            return;
        }
        var selectedParts = SelectedMorphParts();
        var capturedMeshSelection = _viewport.SelectionSnapshotPayload();
        using var dialog = new MorphAuthorDialog(
            _morphProfile.SelectedItem is MorphChoice profile ? profile.Id : string.Empty,
            _morphProfile.SelectedItem is MorphChoice namedProfile ? namedProfile.Name : string.Empty,
            definition,
            AllMorphParts(),
            selectedParts,
            capturedMeshSelection,
            ThemeWindowBackground,
            ThemeSectionBackground,
            ThemeInputBackground,
            ThemeText,
            ThemeMutedText);
        dialog.PreviewRequested += (_, value) => PreviewMorphAuthorDialog(dialog, definition, value);
        var result = dialog.ShowDialog(this);
        if (result == DialogResult.OK)
        {
            var commands = new List<(string Command, Dictionary<string, object?> Payload)>();
            if (dialog.PreviewWasSent)
            {
                commands.Add(("morph_change", MorphWizardChangePayload(dialog.DefinitionId, 0.0)));
            }
            commands.Add(("morph_author_definition", MorphAuthorPayload(
                dialog.Payload,
                definition,
                dialog.PreserveExistingSelection)));
            commands.Add(("morph_change", MorphWizardChangePayload(dialog.DefinitionId, 0.0)));
            commands.Add(("morph_save_profile", new Dictionary<string, object?>()));
            _ = BeginMorphWizardCommandSequence(
                null,
                commands,
                "Morph profile saved at zero. Bake remains a separate action.");
            return;
        }
        if (!dialog.PreviewWasSent)
        {
            return;
        }
        var cancellation = new List<(string Command, Dictionary<string, object?> Payload)>
        {
            ("morph_change", MorphWizardChangePayload(dialog.DefinitionId, 0.0)),
        };
        if (definition.HasValue)
        {
            cancellation.Add(("morph_author_definition", OriginalMorphAuthorPayload(
                    definition.Value,
                    _morphProfile.SelectedItem is MorphChoice currentProfile ? currentProfile.Id : dialog.ProfileId,
                    _morphProfile.SelectedItem is MorphChoice currentNamedProfile ? currentNamedProfile.Name : dialog.ProfileName)));
            cancellation.Add(("morph_change", MorphWizardChangePayload(dialog.DefinitionId, 0.0)));
        }
        else
        {
            cancellation.Add(("morph_delete_profile", new Dictionary<string, object?>
            {
                ["profile_id"] = dialog.ProfileId,
            }));
        }
        _ = BeginMorphWizardCommandSequence(
            null,
            cancellation,
            "Morph profile preview cancelled and temporary changes removed.");
    }

    private void PreviewMorphAuthorDialog(MorphAuthorDialog dialog, JsonElement? definition, double value)
    {
        var commands = new List<(string Command, Dictionary<string, object?> Payload)>();
        if (dialog.PreviewDefinitionCreated)
        {
            commands.Add(("morph_change", MorphWizardChangePayload(dialog.DefinitionId, 0.0)));
        }
        commands.Add(("morph_author_definition", MorphAuthorPayload(
            dialog.Payload,
            definition,
            dialog.PreserveExistingSelection)));
        commands.Add(("morph_change", MorphWizardChangePayload(dialog.DefinitionId, value)));
        if (!BeginMorphWizardCommandSequence(
                dialog,
                commands,
                $"Morph preview ready at {value:0.#}%.",
                accepted =>
                {
                    if (accepted)
                    {
                        dialog.MarkPreviewDefinitionCreated();
                    }
                }))
        {
            dialog.SetProtocolBusy(false, "Another Morph profile command is still running.");
        }
    }

    private void QueueMorphUpdate(MorphSliderControls controls, string changeId)
    {
        if (_pendingMorphUpdateControls is not null
            && (!ReferenceEquals(_pendingMorphUpdateControls, controls)
                || !string.Equals(_pendingMorphUpdateChangeId, changeId, StringComparison.Ordinal)))
        {
            FlushPendingMorphUpdate();
        }
        _pendingMorphUpdateControls = controls;
        _pendingMorphUpdateChangeId = changeId;
        if (!_morphUpdateTimerWired)
        {
            _morphUpdateTimerWired = true;
            _morphUpdateTimer.Tick += (_, _) => FlushPendingMorphUpdate();
        }
        _morphUpdateTimer.Start();
    }

    private void FlushPendingMorphUpdate()
    {
        _morphUpdateTimer.Stop();
        if (_morphUpdateRequestId > 0)
        {
            return;
        }
        var controls = _pendingMorphUpdateControls;
        var changeId = _pendingMorphUpdateChangeId;
        _pendingMorphUpdateControls = null;
        _pendingMorphUpdateChangeId = string.Empty;
        if (controls is not null && changeId.Length > 0)
        {
            SendMorphValue(controls, "update", changeId);
        }
    }

    private void DiscardPendingMorphUpdate()
    {
        _morphUpdateTimer.Stop();
        _pendingMorphUpdateControls = null;
        _pendingMorphUpdateChangeId = string.Empty;
    }

    private static Dictionary<string, object?> MorphWizardChangePayload(
        string definitionId,
        double value)
    {
        return new Dictionary<string, object?>
        {
            ["definition_id"] = definitionId,
            ["value"] = value,
            ["phase"] = "end",
            ["change_id"] = Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture),
        };
    }

    private bool BeginMorphWizardCommandSequence(
        MorphAuthorDialog? dialog,
        IEnumerable<(string Command, Dictionary<string, object?> Payload)> commands,
        string successMessage,
        Action<bool>? completed = null)
    {
        if (_morphWizardSequenceActive)
        {
            return false;
        }
        foreach (var (command, payload) in commands)
        {
            _morphWizardCommandQueue.Enqueue((command, new Dictionary<string, object?>(payload)));
        }
        if (_morphWizardCommandQueue.Count == 0)
        {
            return false;
        }
        _morphWizardActiveDialog = dialog;
        _morphWizardSequenceCompleted = completed;
        _morphWizardSuccessMessage = successMessage;
        _morphWizardSequenceActive = true;
        dialog?.SetProtocolBusy(true, "Applying the correlated Morph preview commands...");
        SendNextMorphWizardCommand();
        return _morphWizardCommandRequestId > 0 || _morphWizardCommandQueue.Count > 0;
    }

    private void SendNextMorphWizardCommand()
    {
        if (_morphWizardCommandRequestId > 0)
        {
            return;
        }
        if (_morphWizardCommandQueue.Count == 0)
        {
            CompleteMorphWizardCommandSequence(accepted: true);
            return;
        }
        var (command, payload) = _morphWizardCommandQueue.Dequeue();
        _morphWizardCommandRequestId = WriteCommandRequest(command, payload);
        if (_morphWizardCommandRequestId <= 0)
        {
            CompleteMorphWizardCommandSequence(accepted: false);
        }
    }

    private void CompleteMorphWizardCommandSequence(bool accepted)
    {
        var hadSequence = _morphWizardSequenceActive
            || _morphWizardCommandRequestId > 0
            || _morphWizardCommandQueue.Count > 0
            || _morphWizardActiveDialog is not null
            || _morphWizardSequenceCompleted is not null
            || _morphWizardSuccessMessage.Length > 0;
        if (!hadSequence)
        {
            return;
        }
        _morphWizardCommandRequestId = 0;
        _morphWizardCommandQueue.Clear();
        _morphWizardSequenceActive = false;
        var dialog = _morphWizardActiveDialog;
        var completed = _morphWizardSequenceCompleted;
        var successMessage = _morphWizardSuccessMessage;
        _morphWizardActiveDialog = null;
        _morphWizardSequenceCompleted = null;
        _morphWizardSuccessMessage = string.Empty;
        completed?.Invoke(accepted);
        if (dialog is not null && !dialog.IsDisposed)
        {
            dialog.SetProtocolBusy(
                false,
                accepted ? successMessage : "The Morph preview command was rejected; no further preview commands were sent.");
        }
        _statusLabel.Text = accepted
            ? successMessage
            : "Morph profile command sequence stopped after a rejected step.";
        ResumePendingFinishIfClear();
        BeginInvoke((Action)ResumeQueuedMorphUiCommandIfClear);
    }

    private static Dictionary<string, object?> MorphAuthorPayload(
        Dictionary<string, object?> payload,
        JsonElement? definition,
        bool preserveExistingSelection)
    {
        payload["preserve_selection"] = preserveExistingSelection;
        payload["source_definition_id"] = definition.HasValue
            ? JsonString(definition.Value, "definition_id").Trim()
            : string.Empty;
        payload["local_basis"] = MorphLocalBasis(definition);
        return payload;
    }

    private static Dictionary<string, object?> OriginalMorphAuthorPayload(
        JsonElement definition,
        string profileId,
        string profileName)
    {
        var definitionId = JsonString(definition, "definition_id").Trim();
        return new Dictionary<string, object?>
        {
            ["profile_id"] = profileId,
            ["profile_name"] = profileName,
            ["definition_id"] = definitionId,
            ["label"] = JsonString(definition, "label"),
            ["category"] = JsonString(definition, "category"),
            ["rule"] = JsonString(definition, "rule"),
            ["axis"] = JsonString(definition, "axis"),
            ["amount"] = JsonDoubleValue(definition, "amount", 0.1),
            ["feather"] = JsonLongValue(definition, "feather"),
            ["falloff"] = JsonString(definition, "falloff"),
            ["mirror_mode"] = JsonString(definition, "mirror_mode"),
            ["min_percent"] = JsonDoubleValue(definition, "min_percent", -100.0),
            ["max_percent"] = JsonDoubleValue(definition, "max_percent", 100.0),
            ["default_percent"] = JsonDoubleValue(definition, "default_percent", 0.0),
            ["preserve_selection"] = true,
            ["source_definition_id"] = definitionId,
            ["local_basis"] = MorphLocalBasis(definition),
        };
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
}
