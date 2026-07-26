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

    private int[] PartColourTargetIndices()
    {
        var selected = _viewport.SelectedSubmeshIndices
            .Where(index => index >= 0 && index < _scene.EditableSubmeshCount)
            .Distinct()
            .OrderBy(index => index)
            .ToArray();
        return selected;
    }

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

    /// <summary>
    /// Put the viewport into a mode that can actually show a colour edit.
    ///
    /// Prefers textured, because that is what a recolour changes. Without
    /// resident texture resources it settles for lit faces, which at least
    /// shows the multiply tint, rather than leaving a wireframe on screen.
    /// </summary>
    private void EnsureColourVisibleDisplayMode()
    {
        var current = _viewport.DisplayMode ?? string.Empty;
        if (current.StartsWith("textured", StringComparison.OrdinalIgnoreCase))
        {
            return;
        }
        // Requesting textures needs an established resident session; without one
        // RequestResidentViewportDisplay only re-labels the combo and leaves the
        // viewport on whatever it was showing, which desyncs the two.
        var residentReady = !string.IsNullOrWhiteSpace(_residentMaterialSessionId)
            && _residentProcessGeneration > 0;
        if (residentReady && HasResidentTextureResources())
        {
            if (!_colourDisplayModeRequested)
            {
                _colourDisplayModeRequested = true;
                RequestResidentViewportDisplay("textured");
            }
            return;
        }
        // No textures reachable yet: show lit faces so the surface is at least
        // visible, and let the status line explain what colour can reach.
        if (_viewport.TrySetSynchronizedDisplayMode("untextured_faces", out _))
        {
            SyncPreviewModeSelection("untextured_faces");
        }
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
            ? "Select at least one part to recolour."
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
