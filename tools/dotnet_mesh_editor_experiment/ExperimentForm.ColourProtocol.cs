using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Transport and local preview for the Colour tool page.
///
/// The host owns every stored value. This side keeps one pending request so a
/// slider drag cannot flood the pipe, applies the same edit to the resident
/// parameter mirror for immediate feedback, and lets the acknowledged
/// material parameter update overwrite that mirror with the exact result.
/// </summary>
internal sealed partial class ExperimentForm
{
    private void EnsurePartColourAuthorityTimer()
    {
        if (_partColourAuthorityTimer is not null)
        {
            return;
        }
        _partColourAuthorityTimer = new System.Windows.Forms.Timer
        {
            Interval = PartColourAuthorityIntervalMs,
        };
        _partColourAuthorityTimer.Tick += (_, _) => FlushPartColourEdit();
    }

    private void QueuePartColourEdit(Dictionary<string, object?> edit)
    {
        if (_loadingPartColourControls)
        {
            return;
        }
        var targets = PartColourTargetIndices();
        if (targets.Length == 0)
        {
            RefreshPartColourControlsEnabled();
            return;
        }
        ApplyPartColourEditLocally(edit, targets);
        var payload = new Dictionary<string, object?>(edit)
        {
            ["source_submesh_indices"] = targets,
        };
        // Latest wins: an older pending edit for the same controls is stale by
        // definition, and the host only ever needs the value the user landed on.
        _pendingPartColourEdit = payload;
        EnsurePartColourAuthorityTimer();
        if (_partColourAuthorityTimer is { Enabled: false })
        {
            _partColourAuthorityTimer.Start();
        }
    }

    /// <summary>Publish the final value immediately, bypassing the pacing timer.</summary>
    private void FlushPartColourEdit()
    {
        _partColourAuthorityTimer?.Stop();
        var payload = _pendingPartColourEdit;
        _pendingPartColourEdit = null;
        if (payload is null)
        {
            return;
        }
        WriteProtocolEvent("part_material_edit_request", payload);
    }

    /// <summary>
    /// The parts this page will write to. A whole-part selection names them
    /// directly; a vertex or face selection names the parts it sits on, because
    /// colour is stored per part and the page going dead on a sub-part selection
    /// is worse than colouring the part the reader is working inside.
    /// <see cref="PartColourScopeIsWiderThanSelection"/> is what says so on screen.
    /// </summary>
    private int[] PartColourTargetIndices()
    {
        var selected = _viewport.SelectedSubmeshIndices
            .Where(index => index >= 0 && index < _scene.EditableSubmeshCount)
            .Distinct()
            .OrderBy(index => index)
            .ToArray();
        if (selected.Length > 0)
        {
            return selected;
        }
        return _viewport.SubmeshIndicesTouchedBySelection
            .Where(index => index >= 0 && index < _scene.EditableSubmeshCount)
            .ToArray();
    }

    /// <summary>
    /// True when the reader picked vertices or faces but the edit will land on
    /// the whole part. Splitting the selection into its own part is the way to
    /// narrow it, and that is a topology change worth asking for explicitly.
    /// </summary>
    private bool PartColourScopeIsWiderThanSelection() =>
        _viewport.SelectedSubmeshIndices.Length == 0 && _viewport.HasSubPartSelection;

    /// <summary>
    /// Whether the selection can be split into a part of its own. Separating
    /// moves whole faces, so a vertex-only selection cannot narrow anything.
    /// </summary>
    private bool PartColourSelectionCanBecomeItsOwnPart() =>
        _viewport.SelectedSubmeshIndices.Length == 0 && _viewport.HasFaceSelection;

    private void ApplyPartColourEditLocally(Dictionary<string, object?> edit, int[] targets)
    {
        var delta = PartColourParameterDelta(edit);
        if (delta is null)
        {
            return;
        }
        var update = new NetMaterialParameterUpdate(
            _residentMaterialSessionId,
            Math.Max(_lastAppliedEditRevision, _lastObservedSessionRevision),
            0,
            new[] { new NetMaterialParameterGroup(targets, false, delta.Value) },
            targets);
        _materials.ApplyParameterUpdate(update);
        _viewport.Invalidate();
    }

    private NetMaterialParameterDelta? PartColourParameterDelta(Dictionary<string, object?> edit)
    {
        if (edit.ContainsKey("reset"))
        {
            return new NetMaterialParameterDelta
            {
                TintColor = Specified(Vector3.One),
                BaseTintColor = Specified(Vector3.One),
                BaseTintStrength = Specified(0f),
                BaseTintAuthored = Specified(false),
                EmissiveIntensity = new NetOptionalParameter<float>(true, null),
                EmissiveColor = new NetOptionalParameter<Vector3>(true, null),
                MaterialRole = new NetOptionalTextParameter(true, null),
            };
        }
        var delta = new NetMaterialParameterDelta();
        if (TryColourVector(edit, "tint_rgb", out var tint))
        {
            delta = delta with { TintColor = Specified(tint) };
        }
        if (TryColourVector(edit, "colourise_rgb", out var recolour))
        {
            // Authored: the shader must skip its metal-category damping, or a
            // saturated colour on a blade renders as a 5% wash.
            delta = delta with
            {
                BaseTintColor = Specified(recolour),
                BaseTintAuthored = Specified(true),
            };
        }
        if (edit.TryGetValue("colourise_strength", out var rawStrength)
            && rawStrength is float strength)
        {
            delta = delta with { BaseTintStrength = Specified(Math.Clamp(strength, 0f, 1f)) };
        }
        if (TryColourVector(edit, "emissive_rgb", out var glow))
        {
            delta = delta with { EmissiveColor = Specified(glow) };
        }
        if (edit.TryGetValue("emissive_strength", out var rawGlow) && rawGlow is float glowStrength)
        {
            delta = delta with
            {
                EmissiveIntensity = Specified(Math.Clamp(glowStrength, 0f, 20f)),
            };
        }
        if (edit.TryGetValue("emissive", out var rawEmissive) && rawEmissive is bool emissive)
        {
            delta = delta with
            {
                MaterialRole = new NetOptionalTextParameter(true, emissive ? "emissive" : null),
            };
            if (!emissive)
            {
                delta = delta with
                {
                    EmissiveIntensity = new NetOptionalParameter<float>(true, null),
                };
            }
        }
        return delta.HasChanges ? delta : null;
    }

    private static NetOptionalParameter<T> Specified<T>(T value) where T : struct =>
        new(true, value);

    private static bool TryColourVector(
        Dictionary<string, object?> edit,
        string key,
        out Vector3 colour)
    {
        colour = Vector3.One;
        if (!edit.TryGetValue(key, out var raw) || raw is not int[] bytes || bytes.Length < 3)
        {
            return false;
        }
        colour = new Vector3(
            Math.Clamp(bytes[0], 0, 255) / 255f,
            Math.Clamp(bytes[1], 0, 255) / 255f,
            Math.Clamp(bytes[2], 0, 255) / 255f);
        return true;
    }

    /// <summary>Reload the Colour page from the resident parameter mirror.</summary>
    private void LoadPartColourControls()
    {
        if (_partRecolourStrength is null || _partEmissiveCheck is null)
        {
            return;
        }
        var targets = PartColourTargetIndices();
        _loadingPartColourControls = true;
        try
        {
            var parameters = targets.Length == 0
                ? NetMaterialParameters.Empty
                : _materials.ParametersForSubmesh(targets[0]);
            SetPartColourSwatch(_partTintButton, ColourFrom(parameters.TintColor));
            SetPartColourSwatch(_partRecolourButton, ColourFrom(parameters.BaseTintColor));
            SetPartColourSwatch(_partEmissiveButton, ColourFrom(parameters.EmissiveColor));
            _partRecolourStrength.Value = (int)Math.Round(
                Math.Clamp(parameters.BaseTintStrength ?? 0f, 0f, 1f) * 100f);
            UpdateRecolourStrengthLabel();
            _partEmissiveCheck.Checked = !string.IsNullOrWhiteSpace(parameters.MaterialRole);
            if (_partEmissiveStrength is not null)
            {
                _partEmissiveStrength.Value = (decimal)Math.Clamp(
                    parameters.EmissiveIntensity ?? 1f,
                    0f,
                    20f);
            }
        }
        finally
        {
            _loadingPartColourControls = false;
        }
        RefreshPartColourControlsEnabled();
    }

    private static Color ColourFrom(Vector3? colour)
    {
        if (colour is not { } value)
        {
            return NeutralPartColour;
        }
        return Color.FromArgb(
            (int)Math.Round(Math.Clamp(value.X, 0f, 1f) * 255f),
            (int)Math.Round(Math.Clamp(value.Y, 0f, 1f) * 255f),
            (int)Math.Round(Math.Clamp(value.Z, 0f, 1f) * 255f));
    }

    /// <summary>
    /// Enable the page only when an edit can actually reach the host, and say
    /// why when it cannot. A control that silently does nothing is worse than
    /// a disabled one.
    /// </summary>
    private void RefreshPartColourControlsEnabled()
    {
        if (_partColourStatus is null)
        {
            return;
        }
        var targets = PartColourTargetIndices();
        var reason = targets.Length == 0
            ? "Select a part, or any vertices or faces on one, to recolour."
            : string.Empty;
        var enabled = reason.Length == 0;
        foreach (var control in new Control?[]
                 {
                     _partTintButton,
                     _partRecolourButton,
                     _partRecolourStrength,
                     _partEmissiveCheck,
                     _partColourResetButton,
                 })
        {
            if (control is not null)
            {
                control.Enabled = enabled;
            }
        }
        if (_partColourSplitButton is not null)
        {
            _partColourSplitButton.Visible = PartColourSelectionCanBecomeItsOwnPart();
            _partColourSplitButton.Enabled = _partColourSplitButton.Visible && !_morphUnbaked;
        }
        var emissiveEnabled = enabled && _partEmissiveCheck is { Checked: true };
        if (_partEmissiveButton is not null)
        {
            _partEmissiveButton.Enabled = emissiveEnabled;
        }
        if (_partEmissiveStrength is not null)
        {
            _partEmissiveStrength.Enabled = emissiveEnabled;
        }
        var scope = targets.Length == 1
            ? $"Editing part {targets[0]}."
            : $"Editing {targets.Length} selected parts.";
        if (PartColourScopeIsWiderThanSelection())
        {
            // Say plainly that the edit is wider than what is highlighted, so a
            // whole-part recolour is never a surprise.
            scope += " Colour is stored per part, so this covers the whole part,"
                + " not only the selected vertices and faces.";
            if (PartColourSelectionCanBecomeItsOwnPart())
            {
                scope += " Split the selection into a part to colour just it.";
            }
        }
        if (reason.Length == 0 && !HasResidentTextureResources())
        {
            // The shader gates the recolour on a bound base texture, and the
            // bake rewrites that texture's pixels. With none bound, Recolour is
            // a no-op and only the multiply tint has anything to act on.
            scope += " No base texture is bound, so Recolour has nothing to repaint.";
        }
        _partColourStatus.Text = reason.Length > 0 ? reason : scope;
        RefreshPartColourSwatchPaint();
    }
}
