using System.Diagnostics;
using System.Drawing;
using System.Numerics;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Hidden end-to-end diagnostics for every row exposed by Edit Mesh.
/// The proof uses the real form, production D3D11 viewport, material bindings,
/// pointer gesture methods, rail pages, and protocol writers.
/// </summary>
internal sealed partial class ExperimentForm
{
    private Action<string, IReadOnlyDictionary<string, object?>>? _diagnosticProtocolObserver;

    internal Dictionary<string, object?> AllEditMeshToolsDiagnosticProof()
    {
        _directAuthoringExactOutputRequired = _options.DirectAuthoring;
        BuildAuthoringToolPanels();
        ActivateToolRailLayout();
        ApplyDiagnosticOutputPolicyState(
            "exact_game_asset",
            destinationReady: false,
            authoringEnabled: true);
        _scene.SetInteractionMode("mesh_edit");
        var displayApplied = _viewport.TrySetSynchronizedDisplayMode("textured", out var displayError);
        var materialApplied = _viewport.TryApplyMaterialState(
            Enumerable.Range(0, _document.Submeshes.Count).ToArray(),
            out var materialError);

        var protocolEvents = new List<(string Name, Dictionary<string, object?> Payload)>();
        var formProtocolEvents = new List<(string Name, Dictionary<string, object?> Payload)>();
        void Capture(string name, Dictionary<string, object?> payload) =>
            protocolEvents.Add((name, new Dictionary<string, object?>(payload)));
        var previousProtocolObserver = _diagnosticProtocolObserver;
        _diagnosticProtocolObserver = (name, payload) =>
            formProtocolEvents.Add((name, new Dictionary<string, object?>(payload)));

        _viewport.EditorEventRequested += Capture;
        try
        {
            var interactionCases = RunAllEditMeshInteractionDiagnostics(
                protocolEvents,
                formProtocolEvents);
            var commandPages = RunEditMeshCommandPageDiagnostics();
            var selectionReleaseRecovery = RunSelectionReleaseRecoveryDiagnostic(protocolEvents);
            var pendingSelectionTopology = RunPendingSelectionTopologyDiagnostic(formProtocolEvents);
            var controlSurface = RunEditMeshControlSurfaceDiagnostics();
            var createPartControl = RunCreatePartFromSelectionDiagnostic(formProtocolEvents);
            var partCommandTargets = RunPartCommandTargetDiagnostic(formProtocolEvents);
            var mixedMorphRefit = RunMixedMorphRefitSelectionDiagnostic();
            var restrictedControlsVisible = _directAuthoringBlockedButtons.All(button => OwnVisibleState(button) && !button.Enabled);
            var directAuthoringControls = RunOutputPolicyControlDiagnostic(restrictedControlsVisible);
            var finalFrame = RunEditMeshDiagnosticFrame();
            return BuildAllEditMeshToolsDiagnosticReport(
                displayApplied,
                displayError,
                materialApplied,
                materialError,
                protocolEvents,
                formProtocolEvents,
                interactionCases,
                commandPages,
                selectionReleaseRecovery,
                pendingSelectionTopology,
                controlSurface,
                createPartControl,
                partCommandTargets,
                mixedMorphRefit,
                directAuthoringControls,
                finalFrame);
        }
        finally
        {
            _viewport.EditorEventRequested -= Capture;
            _diagnosticProtocolObserver = previousProtocolObserver;
        }
    }

    private Dictionary<string, object?> RunEditMeshControlSurfaceDiagnostics()
    {
        static string[] ComboItems(ComboBox combo) => combo.Items
            .Cast<object>()
            .Select(item => Convert.ToString(item) ?? string.Empty)
            .ToArray();

        var requiredButtons = new[]
        {
            "◰    Select", "✥    Move", "✜    Grab", "◍    Smooth", "◉    Inflate",
            "◇    Pinch", "△    Topology", "◑    Morph & Refit", "▣    Viewport",
            "Clear Selection", "Select All", "Invert", "Undo", "Redo",
            "Free Edit Output...",
            "Grow", "Shrink", "-X", "+X", "-Y", "+Y", "-Z", "+Z",
            "Delete Selection", "Duplicate Selection", "Subdivide", "Refine Smooth",
            "All", "None", "Duplicate", "Delete", "Copy", "Paste",
            "Rename", "Up", "Down",
            "Create Profile...", "Save Profile", "Delete Profile", "Save Preset...", "Delete Preset",
            "1. Set Selected Driver Parts", "2. Bind Selected Garment Parts", "Clear Refit",
            "Apply to Selected Garments", "Reset", "Bake",
            "Front", "Back", "Top", "Left", "Right", "Bottom", "-15", "+15", "Fit", "Orbit",
        };
        var requiredDynamicButtonPrefixes = new[]
        {
            "Background\n", "Grid\n", "Wire\n", "Vertices\n", "Selected\n", "Live\n",
        };
        var knownPlacementButtons = new[]
        {
            "Imported / Modify (focus)", "Original (focus)", "Move", "Rotate", "Scale",
        };
        var buttonInventory = DescendantControls(this)
            .OfType<Button>()
            .Where(OwnVisibleState)
            .Select(button => button.Text)
            .Where(text => !string.IsNullOrWhiteSpace(text))
            .Distinct(StringComparer.Ordinal)
            .OrderBy(text => text, StringComparer.Ordinal)
            .ToArray();
        var missingButtons = requiredButtons
            .Where(text => !buttonInventory.Contains(text, StringComparer.Ordinal))
            .ToArray();
        var missingDynamicButtons = requiredDynamicButtonPrefixes
            .Where(prefix => !buttonInventory.Any(text =>
                text.StartsWith(prefix, StringComparison.Ordinal)))
            .ToArray();
        var unexpectedButtons = buttonInventory
            .Where(text => !requiredButtons.Contains(text, StringComparer.Ordinal)
                && !knownPlacementButtons.Contains(text, StringComparer.Ordinal)
                && !requiredDynamicButtonPrefixes.Any(prefix =>
                    text.StartsWith(prefix, StringComparison.Ordinal)))
            .ToArray();

        var expectedDisplayModes = new[]
        {
            "textured", "untextured_faces", "untextured_wire", "wire",
            "vertices", "wire_vertices", "xray",
        };
        var previewCases = new List<Dictionary<string, object?>>();
        for (var index = 0; index < _previewMode.Items.Count; index++)
        {
            _previewMode.SelectedIndex = index;
            var frame = RunEditMeshDiagnosticFrame();
            var expectedMode = index < expectedDisplayModes.Length
                ? expectedDisplayModes[index]
                : string.Empty;
            var modeMatches = string.Equals(
                _viewport.DisplayMode,
                expectedMode,
                StringComparison.OrdinalIgnoreCase);
            var xrayMatches = _viewport.ShowXRay == (index == 6);
            var paneTexturesMatch = _viewport.PresentationContextTexturesEnabled()
                == _viewport.TexturesEnabled;
            previewCases.Add(new Dictionary<string, object?>
            {
                ["index"] = index,
                ["label"] = Convert.ToString(_previewMode.Items[index]),
                ["display_mode"] = _viewport.DisplayMode,
                ["frame"] = frame,
                ["mode_matches"] = modeMatches,
                ["xray_matches"] = xrayMatches,
                ["viewport_textures_enabled"] = _viewport.TexturesEnabled,
                ["pane_textures_match"] = paneTexturesMatch,
                ["ok"] = frame.GetValueOrDefault("ok") is true
                    && modeMatches
                    && xrayMatches
                    && paneTexturesMatch,
            });
        }
        _previewMode.SelectedIndex = 6;
        var xrayEnabled = _xray.Checked && _viewport.ShowXRay;
        _xray.Checked = false;
        var xrayDisabledConsistently = _previewMode.SelectedIndex == 4
            && !_xray.Checked
            && !_viewport.ShowXRay;
        _previewMode.SelectedIndex = 0;
        var restoredTextured = string.Equals(
                _viewport.DisplayMode,
                "textured",
                StringComparison.OrdinalIgnoreCase)
            && _viewport.TexturesEnabled
            && _viewport.HasTexturedMaterialResources;

        var cameraExpectations = new (string Preset, float Yaw, float Pitch)[]
        {
            ("front", 0.0f, 0.0f),
            ("back", 180.0f, 0.0f),
            ("top", 0.0f, -1.35f * 180.0f / MathF.PI),
            ("left", -90.0f, 0.0f),
            ("right", 90.0f, 0.0f),
            ("bottom", 0.0f, 1.35f * 180.0f / MathF.PI),
        };
        var cameraCases = new List<Dictionary<string, object?>>();
        foreach (var expected in cameraExpectations)
        {
            _viewport.SetCameraPreset(expected.Preset);
            var frame = RunEditMeshDiagnosticFrame();
            var camera = EditMeshDiagnosticCameraState();
            var yaw = Convert.ToSingle(camera.GetValueOrDefault("yaw_degrees"));
            var pitch = Convert.ToSingle(camera.GetValueOrDefault("pitch_degrees"));
            var cameraMatches = MathF.Abs(yaw - expected.Yaw) <= 0.01f
                && MathF.Abs(pitch - expected.Pitch) <= 0.01f;
            cameraCases.Add(new Dictionary<string, object?>
            {
                ["command"] = expected.Preset,
                ["yaw_degrees"] = yaw,
                ["pitch_degrees"] = pitch,
                ["camera_matches"] = cameraMatches,
                ["ok"] = frame.GetValueOrDefault("ok") is true && cameraMatches,
                ["frame"] = frame,
            });
        }
        var yawStart = Convert.ToSingle(
            EditMeshDiagnosticCameraState().GetValueOrDefault("yaw_degrees"));
        _viewport.RotateYawDegrees(-15.0f);
        var yawNegative = Convert.ToSingle(
            EditMeshDiagnosticCameraState().GetValueOrDefault("yaw_degrees"));
        _viewport.RotateYawDegrees(30.0f);
        var yawPositive = Convert.ToSingle(
            EditMeshDiagnosticCameraState().GetValueOrDefault("yaw_degrees"));
        _viewport.RotateYawDegrees(-15.0f);
        var yawRestored = Convert.ToSingle(
            EditMeshDiagnosticCameraState().GetValueOrDefault("yaw_degrees"));
        var yawRoundTrip = MathF.Abs(yawNegative - (yawStart - 15.0f)) <= 0.01f
            && MathF.Abs(yawPositive - (yawStart + 15.0f)) <= 0.01f
            && MathF.Abs(yawRestored - yawStart) <= 0.01f;
        _viewport.FrameMesh();
        var fitRelativeZoom = Convert.ToSingle(
            EditMeshDiagnosticCameraState().GetValueOrDefault("fit_relative_zoom"));
        var fitAtBaseline = MathF.Abs(fitRelativeZoom - 1.0f) <= 0.001f;
        ActivateTool("orbit", "Orbit", announce: false);
        var orbitFrame = RunEditMeshDiagnosticFrame();
        var orbitActivated = string.Equals(
            _viewport.ActiveTool,
            "orbit",
            StringComparison.OrdinalIgnoreCase);
        ActivateTool("select", "Select", announce: false);

        var targetItems = ComboItems(_selectionTarget);
        var shapeItems = ComboItems(_selectionShape);
        var operationItems = ComboItems(_selectionOperation);
        var falloffItems = ComboItems(_falloff);
        var comboContractOk = targetItems.SequenceEqual(new[] { "Vertices", "Wires", "Faces" })
            && shapeItems.SequenceEqual(new[] { "Brush", "Rectangle", "Lasso" })
            && operationItems.SequenceEqual(new[] { "Add", "Replace", "Subtract", "Toggle" })
            && falloffItems.SequenceEqual(new[] { "Smooth", "Linear", "Constant" });
        var translateStepPositive = _translateStep.Minimum > 0 && _translateStep.Value > 0;
        var previousSelectionTarget = _selectionTarget.SelectedIndex;
        _selectionTarget.SelectedItem = "Wires";
        UpdateViewportControlsHint();
        var selectionHintTracksTarget = _controlsHintLabel.Text.Contains("Wires", StringComparison.Ordinal);
        _selectionTarget.SelectedIndex = previousSelectionTarget;
        UpdateViewportControlsHint();
        _ = _viewport.UpdateSelection(
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<(int A, int B)>>(),
            new HashSet<int> { 0 },
            revision: _viewport.AcknowledgedSelectionRevision + 1);
        RefreshPartDetail();
        var visibleActionReadsHide = string.Equals(_partVisibilityButton?.Text, "Hide", StringComparison.Ordinal);
        _materials.ApplyParameterUpdate(new NetMaterialParameterUpdate(
            string.Empty,
            0,
            1,
            new[]
            {
                new NetMaterialParameterGroup(
                    new[] { 0 },
                    false,
                    new NetMaterialParameterDelta
                    {
                        Visible = new NetOptionalParameter<bool>(true, false),
                    }),
            },
            new[] { 0 }));
        RefreshPartDetail();
        var hiddenActionReadsShow = string.Equals(_partVisibilityButton?.Text, "Show", StringComparison.Ordinal);
        _materials.ApplyParameterUpdate(new NetMaterialParameterUpdate(
            string.Empty,
            0,
            2,
            new[]
            {
                new NetMaterialParameterGroup(
                    new[] { 0 },
                    false,
                    new NetMaterialParameterDelta
                    {
                        Visible = new NetOptionalParameter<bool>(true, true),
                    }),
            },
            new[] { 0 }));
        RefreshPartDetail();
        return new Dictionary<string, object?>
        {
            ["ok"] = missingButtons.Length == 0
                && missingDynamicButtons.Length == 0
                && unexpectedButtons.Length == 0
                && comboContractOk
                && previewCases.All(item => item.GetValueOrDefault("ok") is true)
                && cameraCases.All(item => item.GetValueOrDefault("ok") is true)
                && yawRoundTrip
                && fitAtBaseline
                && orbitActivated
                && orbitFrame.GetValueOrDefault("ok") is true
                && xrayEnabled
                && xrayDisabledConsistently
                && restoredTextured
                && translateStepPositive
                && selectionHintTracksTarget
                && visibleActionReadsHide
                && hiddenActionReadsShow,
            ["button_inventory"] = buttonInventory,
            ["required_buttons"] = requiredButtons,
            ["missing_buttons"] = missingButtons,
            ["required_dynamic_button_prefixes"] = requiredDynamicButtonPrefixes,
            ["missing_dynamic_buttons"] = missingDynamicButtons,
            ["known_placement_buttons"] = knownPlacementButtons,
            ["unexpected_buttons"] = unexpectedButtons,
            ["selection_targets"] = targetItems,
            ["selection_shapes"] = shapeItems,
            ["selection_operations"] = operationItems,
            ["brush_falloffs"] = falloffItems,
            ["combo_contract_ok"] = comboContractOk,
            ["translate_step_positive"] = translateStepPositive,
            ["selection_hint_tracks_target"] = selectionHintTracksTarget,
            ["preview_cases"] = previewCases,
            ["camera_cases"] = cameraCases,
            ["yaw_round_trip"] = yawRoundTrip,
            ["yaw_samples"] = new[] { yawStart, yawNegative, yawPositive, yawRestored },
            ["fit_relative_zoom"] = fitRelativeZoom,
            ["fit_at_baseline"] = fitAtBaseline,
            ["orbit_activated"] = orbitActivated,
            ["orbit_frame"] = orbitFrame,
            ["xray_enabled"] = xrayEnabled,
            ["xray_disabled_consistently"] = xrayDisabledConsistently,
            ["restored_solid_textured"] = restoredTextured,
            ["visible_part_action_reads_hide"] = visibleActionReadsHide,
            ["hidden_part_action_reads_show"] = hiddenActionReadsShow,
            ["dialog_backed_controls"] = new[]
            {
                "Create Profile...", "Save Preset...",
            },
        };
    }

    private Dictionary<string, object?> RunCreatePartFromSelectionDiagnostic(
        List<(string Name, Dictionary<string, object?> Payload)> formProtocolEvents)
    {
        if (_createPartFromSelectionButton is null || _document.Submeshes.Count == 0)
        {
            return new Dictionary<string, object?>
            {
                ["ok"] = false,
                ["reason"] = "Create Part control was not constructed.",
            };
        }
        var previousTarget = _selectionTarget.SelectedIndex;
        var protocolStart = formProtocolEvents.Count;
        try
        {
            ActivateTool("select", "Select");
            _selectionTarget.SelectedItem = "Faces";
            _ = _viewport.UpdateSelection(
                new Dictionary<int, HashSet<int>>(),
                new Dictionary<int, HashSet<int>> { [0] = new HashSet<int> { 0 } },
                new Dictionary<int, HashSet<(int A, int B)>>(),
                new HashSet<int>(),
                revision: _viewport.AcknowledgedSelectionRevision + 1);
            RefreshCreatePartFromSelectionButton();
            var enabled = _createPartFromSelectionButton.Enabled;
            var clickMethod = typeof(Button).GetMethod(
                "OnClick",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            clickMethod?.Invoke(_createPartFromSelectionButton, new object[] { EventArgs.Empty });
            var emitted = formProtocolEvents
                .Skip(protocolStart)
                .Where(item => item.Name == "command_request")
                .Select(item => item.Payload)
                .ToArray();
            var payload = emitted.LastOrDefault();
            var requestId = payload is null ? 0 : Convert.ToInt64(payload.GetValueOrDefault("request_id") ?? 0);
            if (requestId > 0)
            {
                _pendingMutationRequests.Remove(requestId);
            }
            return new Dictionary<string, object?>
            {
                ["ok"] = !enabled
                    && !_createPartFromSelectionButton.Visible
                    && payload is null
                    && requestId == 0,
                ["button_enabled"] = enabled,
                ["button_visible"] = _createPartFromSelectionButton.Visible,
                ["command"] = payload?.GetValueOrDefault("command"),
                ["target_mode"] = payload?.GetValueOrDefault("target_mode"),
                ["request_id"] = requestId,
            };
        }
        finally
        {
            _viewport.ResetSelectionAuthority();
            if (previousTarget >= 0 && previousTarget < _selectionTarget.Items.Count)
            {
                _selectionTarget.SelectedIndex = previousTarget;
            }
            RefreshCreatePartFromSelectionButton();
        }
    }

    private List<Dictionary<string, object?>> RunAllEditMeshInteractionDiagnostics(
        List<(string Name, Dictionary<string, object?> Payload)> protocolEvents,
        List<(string Name, Dictionary<string, object?> Payload)> formProtocolEvents)
    {
        var cases = new List<Dictionary<string, object?>>();
        foreach (var target in new[] { "vertex", "edge", "face" })
        {
            foreach (var shape in new[] { "brush", "lasso", "rectangle" })
            {
                cases.Add(RunEditMeshInteractionDiagnostic(
                    $"select_{shape}_{target}",
                    protocolEvents,
                    formProtocolEvents,
                    sustained: shape == "brush" && target == "face"));
            }
        }
        foreach (var tool in new[] { "move", "grab", "smooth", "inflate", "pinch" })
        {
            cases.Add(RunEditMeshInteractionDiagnostic(
                tool,
                protocolEvents,
                formProtocolEvents,
                sustained: true));
        }
        return cases;
    }

    private Dictionary<string, object?> BuildAllEditMeshToolsDiagnosticReport(
        bool displayApplied,
        string displayError,
        bool materialApplied,
        string materialError,
        List<(string Name, Dictionary<string, object?> Payload)> protocolEvents,
        List<(string Name, Dictionary<string, object?> Payload)> formProtocolEvents,
        List<Dictionary<string, object?>> interactionCases,
        List<Dictionary<string, object?>> commandPages,
        Dictionary<string, object?> selectionReleaseRecovery,
        Dictionary<string, object?> pendingSelectionTopology,
        Dictionary<string, object?> controlSurface,
        Dictionary<string, object?> createPartControl,
        Dictionary<string, object?> partCommandTargets,
        Dictionary<string, object?> mixedMorphRefit,
        Dictionary<string, object?> directAuthoringControls,
        Dictionary<string, object?> finalFrame)
    {
        var formProtocolOk = formProtocolEvents.Any(item =>
                item.Name == "command_request"
                && Convert.ToString(item.Payload.GetValueOrDefault("command")) == "recalculate_normals")
            && formProtocolEvents.Any(item =>
                item.Name == "command_request"
                && Convert.ToString(item.Payload.GetValueOrDefault("command")) == "morph_state_request")
            && formProtocolEvents.All(item => item.Name != "part_material_edit_request");
        var requiredRows = EditMeshToolListContract.RowOrder.Select(row => row.Key).ToArray();
        var coveredRows = interactionCases
            .Select(item => Convert.ToString(item.GetValueOrDefault("rail_row")) ?? string.Empty)
            .Concat(commandPages.Select(item =>
                Convert.ToString(item.GetValueOrDefault("rail_row")) ?? string.Empty))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var allRowsCovered = requiredRows.All(row =>
            coveredRows.Contains(row, StringComparer.OrdinalIgnoreCase));
        var ok = displayApplied
            && materialApplied
            && _viewport.TexturesEnabled
            && _viewport.HasTexturedMaterialResources
            && interactionCases.All(item => item.GetValueOrDefault("ok") is true)
            && commandPages.All(item => item.GetValueOrDefault("ok") is true)
            && selectionReleaseRecovery.GetValueOrDefault("ok") is true
            && pendingSelectionTopology.GetValueOrDefault("ok") is true
            && controlSurface.GetValueOrDefault("ok") is true
            && createPartControl.GetValueOrDefault("ok") is true
            && partCommandTargets.GetValueOrDefault("ok") is true
            && mixedMorphRefit.GetValueOrDefault("ok") is true
            && directAuthoringControls.GetValueOrDefault("ok") is true
            && formProtocolOk
            && finalFrame.GetValueOrDefault("ok") is true
            && allRowsCovered
            && string.Equals(_viewport.RendererBackendName, "d3d11_vortice_shader", StringComparison.Ordinal);
        return new Dictionary<string, object?>
        {
            ["ok"] = ok,
            ["hidden"] = !Visible && !ShowInTaskbar,
            ["renderer_backend"] = _viewport.RendererBackendName,
            ["display_mode"] = _viewport.DisplayMode,
            ["textures_enabled"] = _viewport.TexturesEnabled,
            ["bound_texture_resources"] = _viewport.HasTexturedMaterialResources,
            ["display_applied"] = displayApplied,
            ["display_error"] = displayError,
            ["material_applied"] = materialApplied,
            ["material_error"] = materialError,
            ["required_rail_rows"] = requiredRows,
            ["covered_rail_rows"] = coveredRows,
            ["all_rail_rows_covered"] = allRowsCovered,
            ["interaction_cases"] = interactionCases,
            ["command_pages"] = commandPages,
            ["selection_release_recovery"] = selectionReleaseRecovery,
            ["pending_selection_topology"] = pendingSelectionTopology,
            ["control_surface"] = controlSurface,
            ["create_part_from_selection"] = createPartControl,
            ["part_command_targets"] = partCommandTargets,
            ["mixed_morph_refit_selection"] = mixedMorphRefit,
            ["direct_authoring_controls"] = directAuthoringControls,
            ["form_protocol_ok"] = formProtocolOk,
            ["captured_viewport_protocol_events"] = protocolEvents.Count,
            ["captured_form_protocol_events"] = formProtocolEvents.Select(item =>
                new Dictionary<string, object?>
                {
                    ["event"] = item.Name,
                    ["command"] = item.Payload.GetValueOrDefault("command"),
                    ["request_id"] = item.Payload.GetValueOrDefault("request_id"),
                }).ToArray(),
            ["final_frame"] = finalFrame,
            ["renderer_resources"] = _viewport.RendererResourceMetricsPayload(),
        };
    }

    private Dictionary<string, object?> RunMixedMorphRefitSelectionDiagnostic()
    {
        if (_document.Submeshes.Count < 2 || _morphRefitSettingsControl is null)
        {
            return new Dictionary<string, object?>
            {
                ["ok"] = false,
                ["reason"] = "Morph refit controls or two diagnostic parts were unavailable.",
            };
        }
        _morphBoundGarmentPartIndices.Clear();
        _morphBoundGarmentPartIndices.UnionWith(new[] { 0, 1 });
        _morphGarmentSettings.Clear();
        _morphGarmentSettings[0] = new MorphRefitGarmentState(true, 25.0, "surface", 0.5);
        _morphGarmentSettings[1] = new MorphRefitGarmentState(false, 75.0, "volume", 1.5);
        _ = _viewport.UpdateSelection(
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<(int A, int B)>>(),
            new HashSet<int> { 0, 1 },
            revision: _viewport.AcknowledgedSelectionRevision + 1);
        ApplySelectedMorphRefitSettings();
        var mixedDisabled = !_morphRefitSettingsControl.Enabled;
        var mixedExplained = _morphDiagnosticStatus.Text.Contains(
            "different refit settings",
            StringComparison.OrdinalIgnoreCase);

        _morphGarmentSettings[1] = _morphGarmentSettings[0];
        ApplySelectedMorphRefitSettings();
        var uniformEnabled = _morphRefitSettingsControl.Enabled;
        var uniformLoaded = _morphRefitEnabled.Checked
            && _morphRefitIntensity.Value == 25.0M
            && _morphRefitClearance.Value == 0.5M;
        _ = _viewport.UpdateSelection(
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<(int A, int B)>>(),
            new HashSet<int>(),
            revision: _viewport.AcknowledgedSelectionRevision + 1);
        _morphBoundGarmentPartIndices.Clear();
        _morphGarmentSettings.Clear();
        return new Dictionary<string, object?>
        {
            ["ok"] = mixedDisabled && mixedExplained && uniformEnabled && uniformLoaded,
            ["mixed_disabled"] = mixedDisabled,
            ["mixed_explained"] = mixedExplained,
            ["uniform_enabled"] = uniformEnabled,
            ["uniform_loaded"] = uniformLoaded,
        };
    }

    private Dictionary<string, object?> RunPartCommandTargetDiagnostic(
        List<(string Name, Dictionary<string, object?> Payload)> formProtocolEvents)
    {
        if (_partVisibilityButton is null || _partDuplicateButton is null || _partDeleteButton is null)
        {
            return new Dictionary<string, object?>
            {
                ["ok"] = false,
                ["reason"] = "Parts",
            };
        }
        var protocolStart = formProtocolEvents.Count;
        try
        {
            ApplyDirectAuthoringOutputContract(exactOutputRequired: false);
            _ = _viewport.UpdateSelection(
                new Dictionary<int, HashSet<int>>(),
                new Dictionary<int, HashSet<int>>(),
                new Dictionary<int, HashSet<(int A, int B)>>(),
                new HashSet<int> { 0 },
                revision: _viewport.AcknowledgedSelectionRevision + 1);
            var clickMethod = typeof(Button).GetMethod(
                "OnClick",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            foreach (var button in new[] { _partVisibilityButton, _partDuplicateButton, _partDeleteButton })
            {
                clickMethod?.Invoke(button, new object[] { EventArgs.Empty });
            }
            var emitted = formProtocolEvents
                .Skip(protocolStart)
                .Where(item => item.Name == "command_request")
                .Select(item => item.Payload)
                .ToArray();
            foreach (var requestId in emitted.Select(payload =>
                Convert.ToInt64(payload.GetValueOrDefault("request_id") ?? 0)))
            {
                if (requestId > 0)
                {
                    _pendingMutationRequests.Remove(requestId);
                }
            }
            var commands = emitted.Select(payload =>
                Convert.ToString(payload.GetValueOrDefault("command")) ?? string.Empty).ToArray();
            var sourceTargets = emitted.All(payload =>
                string.Equals(
                    Convert.ToString(payload.GetValueOrDefault("target_mode")),
                    "source",
                    StringComparison.OrdinalIgnoreCase));
            return new Dictionary<string, object?>
            {
                ["ok"] = commands.SequenceEqual(new[] { "toggle_visibility", "duplicate", "delete" })
                    && sourceTargets,
                ["commands"] = commands,
                ["source_targets"] = sourceTargets,
                ["command_request_count"] = emitted.Length,
            };
        }
        finally
        {
            _viewport.ResetSelectionAuthority();
            ApplyDirectAuthoringOutputContract(exactOutputRequired: true);
        }
    }

    private static bool OwnVisibleState(Control control)
    {
        const int stateVisible = 0x00000002;
        var getState = typeof(Control).GetMethod(
            "GetState",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
        return getState?.Invoke(control, new object[] { stateVisible }) is true;
    }

    private static bool OwnEnabledState(Control control)
    {
        const int stateEnabled = 0x00000004;
        var getState = typeof(Control).GetMethod(
            "GetState",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
        return getState?.Invoke(control, new object[] { stateEnabled }) is true;
    }

    private static IEnumerable<Control> DescendantControls(Control root)
    {
        foreach (Control child in root.Controls)
        {
            yield return child;
            foreach (var descendant in DescendantControls(child))
            {
                yield return descendant;
            }
        }
    }

    private Dictionary<string, object?> EditMeshDiagnosticCameraState()
    {
        var presentation = _viewport.PresentationStatusPayload();
        var activeContext = Convert.ToString(
            presentation.GetValueOrDefault("active_camera_context"));
        var contexts = presentation.GetValueOrDefault("view_contexts")
            as IEnumerable<Dictionary<string, object?>>;
        var context = contexts?.FirstOrDefault(item => string.Equals(
            Convert.ToString(item.GetValueOrDefault("id")),
            activeContext,
            StringComparison.Ordinal));
        return context?.GetValueOrDefault("camera") as Dictionary<string, object?>
            ?? new Dictionary<string, object?>();
    }

    private Dictionary<string, object?> RunEditMeshInteractionDiagnostic(
        string mode,
        List<(string Name, Dictionary<string, object?> Payload)> protocolEvents,
        List<(string Name, Dictionary<string, object?> Payload)> formProtocolEvents,
        bool sustained)
    {
        var size = _viewport.ClientSize;
        var start = mode is "grab" or "smooth" or "inflate" or "pinch"
            ? _viewport.InteractionSoakMeshAnchor()
            : new Point(Math.Max(16, size.Width / 2), Math.Max(16, size.Height / 2));
        var points = EditMeshDiagnosticPath(mode, start, size, sustained);
        var protocolStart = protocolEvents.Count;
        var formProtocolStart = formProtocolEvents.Count;
        var sampleTimes = new List<double>(points.Count);
        var total = Stopwatch.StartNew();
        var beginStarted = Stopwatch.GetTimestamp();
        _viewport.BeginInteractionSoak(mode, start);
        var beginMs = ElapsedMilliseconds(beginStarted);
        if (mode.StartsWith("select_", StringComparison.Ordinal))
        {
            _ = _viewport.WaitForPaintProjectionCacheForInteractionSoak(10_000, out _);
        }
        foreach (var point in points)
        {
            var sampleStarted = Stopwatch.GetTimestamp();
            _viewport.StepInteractionSoak(point);
            sampleTimes.Add(ElapsedMilliseconds(sampleStarted));
        }
        var finishStarted = Stopwatch.GetTimestamp();
        var authorityStreamed = mode is "smooth" or "inflate" or "pinch";
        var result = _viewport.FinishInteractionSoak(
            points[^1],
            deferStreamedAuthority: authorityStreamed);
        var emittedBeforeAuthority = formProtocolEvents.Skip(formProtocolStart).ToArray();
        if (authorityStreamed)
        {
            result = ApplyInteractionSoakAuthoritativeGeometry(result, emittedBeforeAuthority);
        }
        var finishMs = ElapsedMilliseconds(finishStarted);
        var frame = RunEditMeshDiagnosticFrame();
        total.Stop();

        var emitted = protocolEvents.Skip(protocolStart).ToArray();
        var selectionCase = mode.StartsWith("select_", StringComparison.Ordinal);
        var pieces = mode.Split('_', StringSplitOptions.RemoveEmptyEntries);
        var selectionShape = selectionCase && pieces.Length == 3 ? pieces[1] : string.Empty;
        var selectionTarget = selectionCase && pieces.Length == 3 ? pieces[2] : string.Empty;
        var selectionShapePreserved = !selectionCase
            || emitted
                .Where(item => item.Name is "select_request" or "selection_request")
                .Any(item => SelectionDiagnosticPayloadMatches(
                    item.Payload,
                    selectionShape,
                    selectionTarget));
        var selectedExpectedScope = selectionTarget switch
        {
            "vertex" => result.SelectedVertexCount > 0,
            "edge" => result.SelectedEdgeCount > 0,
            "face" => result.SelectedFaceCount > 0,
            _ => result.ChangedVertexCount > 0 || result.AuthorityStreamed,
        };
        var railRow = selectionCase ? "select" : mode;
        var maxSampleMs = sampleTimes.Count == 0 ? 0.0 : sampleTimes.Max();
        var p95SampleMs = Percentile(sampleTimes, 0.95);
        var pointerLatencyOk = p95SampleMs <= 20.0 && maxSampleMs <= 100.0;
        var beginLatencyOk = beginMs <= 250.0;
        var terminalLatencyOk = finishMs <= 250.0;
        return new Dictionary<string, object?>
        {
            ["ok"] = result.FinalAuthorityMatches
                && result.ProvisionalCleared
                && selectionShapePreserved
                && selectedExpectedScope
                && pointerLatencyOk
                && beginLatencyOk
                && terminalLatencyOk
                && frame.GetValueOrDefault("ok") is true
                && _viewport.TexturesEnabled
                && _viewport.HasTexturedMaterialResources,
            ["mode"] = mode,
            ["rail_row"] = railRow,
            ["sustained"] = sustained,
            ["sample_count"] = sampleTimes.Count,
            ["total_ms"] = total.Elapsed.TotalMilliseconds,
            ["begin_ms"] = beginMs,
            ["maximum_sample_ms"] = maxSampleMs,
            ["p95_sample_ms"] = p95SampleMs,
            ["finish_ms"] = finishMs,
            ["latency_gates"] = new Dictionary<string, bool>
            {
                ["begin_at_most_250_ms"] = beginLatencyOk,
                ["pointer_p95_at_most_20_ms"] = p95SampleMs <= 20.0,
                ["no_pointer_sample_over_100_ms"] = maxSampleMs <= 100.0,
                ["terminal_reconciliation_at_most_250_ms"] = terminalLatencyOk,
            },
            ["cursor_coverage_pixels"] = result.CursorCoveragePixels,
            ["changed_vertex_count"] = result.ChangedVertexCount,
            ["selected_vertex_count"] = result.SelectedVertexCount,
            ["selected_edge_count"] = result.SelectedEdgeCount,
            ["selected_face_count"] = result.SelectedFaceCount,
            ["selected_part_count"] = result.SelectedPartCount,
            ["final_authority_matches"] = result.FinalAuthorityMatches,
            ["stale_result_ignored"] = result.StaleResultIgnored,
            ["provisional_cleared"] = result.ProvisionalCleared,
            ["authority_streamed"] = result.AuthorityStreamed,
            ["selection_shape_preserved"] = selectionShapePreserved,
            ["selection_target"] = selectionTarget,
            ["selection_shape"] = selectionShape,
            ["expected_scope_changed"] = selectedExpectedScope,
            ["protocol_event_count"] = emitted.Length,
            ["protocol_event_names"] = emitted.Select(item => item.Name).ToArray(),
            ["frame"] = frame,
            ["textures_enabled_after"] = _viewport.TexturesEnabled,
            ["bound_texture_resources_after"] = _viewport.HasTexturedMaterialResources,
        };
    }

    private Dictionary<string, object?> RunSelectionReleaseRecoveryDiagnostic(
        List<(string Name, Dictionary<string, object?> Payload)> protocolEvents)
    {
        var size = _viewport.ClientSize;
        var start = _viewport.InteractionSoakMeshAnchor();
        var firstEnd = new Point(
            Math.Clamp(start.X + 18, 1, Math.Max(1, size.Width - 2)),
            Math.Clamp(start.Y + 12, 1, Math.Max(1, size.Height - 2)));
        var secondEnd = new Point(
            Math.Clamp(start.X - 14, 1, Math.Max(1, size.Width - 2)),
            Math.Clamp(start.Y + 20, 1, Math.Max(1, size.Height - 2)));
        var protocolStart = protocolEvents.Count;

        _viewport.BeginInteractionSoak("select_brush_face", start);
        _viewport.StepInteractionSoak(firstEnd);
        _viewport.FinishSelectionInteractionSoakAfterLostMouseUp(firstEnd);
        var firstGestureClean = _viewport.SelectionInteractionSoakStateClean;

        _viewport.BeginInteractionSoak("select_brush_face", start);
        var secondResult = _viewport.FinishInteractionSoak(secondEnd);
        var secondGestureClean = _viewport.SelectionInteractionSoakStateClean;

        var terminalRequests = protocolEvents
            .Skip(protocolStart)
            .Where(item => item.Name is "select_request" or "selection_request")
            .Where(item => string.Equals(
                Convert.ToString(item.Payload.GetValueOrDefault("phase")),
                "end",
                StringComparison.OrdinalIgnoreCase))
            .ToArray();
        var strokeIds = terminalRequests
            .Select(item => Convert.ToString(item.Payload.GetValueOrDefault("stroke_id")) ?? string.Empty)
            .Where(item => item.Length > 0)
            .ToArray();
        var distinctTerminalStrokes = strokeIds
            .Distinct(StringComparer.Ordinal)
            .Count() == 2;
        var result = new Dictionary<string, object?>
        {
            ["ok"] = firstGestureClean
                && secondGestureClean
                && terminalRequests.Length == 2
                && distinctTerminalStrokes
                && secondResult.FinalAuthorityMatches
                && secondResult.ProvisionalCleared,
            ["first_gesture_state_clean"] = firstGestureClean,
            ["second_gesture_state_clean"] = secondGestureClean,
            ["terminal_request_count"] = terminalRequests.Length,
            ["terminal_stroke_ids"] = strokeIds,
            ["distinct_terminal_strokes"] = distinctTerminalStrokes,
            ["second_selection_authority_matches"] = secondResult.FinalAuthorityMatches,
            ["second_selection_provisional_cleared"] = secondResult.ProvisionalCleared,
        };
        // The hidden proof emits real protocol requests without a host process
        // answering them. Retire that synthetic authority before the next
        // diagnostic (pending Subdivide) starts, exactly as a session boundary
        // would, so the proof cannot poison the case that follows it.
        _viewport.SetAuthoritativeEditRevision(_viewport.AcknowledgedSelectionRevision);
        _viewport.ResetSelectionAuthority();
        return result;
    }

    private MeshInteractionSoakResult ApplyInteractionSoakAuthoritativeGeometry(
        MeshInteractionSoakResult pending,
        IReadOnlyList<(string Name, Dictionary<string, object?> Payload)> emitted)
    {
        var terminal = emitted.LastOrDefault(item => item.Name == "stroke_end");
        if (terminal.Payload is null || _document.Submeshes.Count == 0)
        {
            return pending;
        }
        var submesh = _document.Submeshes[0];
        if (submesh.Vertices.Count == 0)
        {
            return pending;
        }
        var revision = Math.Max(
            Math.Max(_lastAppliedEditRevision, _lastObservedSessionRevision),
            _viewport.AuthoritativeEditRevision) + 1L;
        var response = new Dictionary<string, object?>(terminal.Payload)
        {
            ["status"] = "ok",
            ["revision"] = revision,
            ["edit_revision"] = revision,
            ["authoritative_geometry_pending"] = true,
        };
        var root = JsonSerializer.SerializeToElement(response);
        var vertexIndex = Math.Max(0, submesh.Vertices.Count / 2);
        var before = submesh.Vertices[vertexIndex];
        var expected = new Vec3(before.X, before.Y, before.Z + 0.01f);
        ApplyPreviewVertexUpdate(
            root,
            new[]
            {
                new PreviewVertexGroup(
                    0,
                    new[] { vertexIndex },
                    new double[] { expected.X, expected.Y, expected.Z },
                    Array.Empty<double>(),
                    Array.Empty<double>(),
                    false),
            },
            vertexUpdatePrepared: true);
        HandleCommandResult(root);
        var actual = submesh.Vertices[vertexIndex];
        var applied = Vector3.Distance(
            new Vector3(actual.X, actual.Y, actual.Z),
            new Vector3(expected.X, expected.Y, expected.Z)) <= 0.000001f;
        return pending with
        {
            FinalAuthorityMatches = applied,
            ProvisionalCleared = !_viewport.HasProvisionalStroke,
            ChangedVertexCount = applied ? 1 : 0,
            AuthorityStreamed = applied && !_viewport.HasProvisionalStroke,
        };
    }

    private Dictionary<string, object?> RunPendingSelectionTopologyDiagnostic(
        List<(string Name, Dictionary<string, object?> Payload)> formProtocolEvents)
    {
        var protocolStart = formProtocolEvents.Count;
        var pendingPrepared = _viewport.BeginPendingFaceSelectionCommandDiagnostic();
        var requestId = pendingPrepared ? WriteCommandRequest("subdivide") : 0;
        var emitted = formProtocolEvents
            .Skip(protocolStart)
            .Where(item => item.Name == "command_request")
            .Select(item => item.Payload)
            .ToArray();
        _viewport.ResetSelectionAuthority();
        return new Dictionary<string, object?>
        {
            ["ok"] = pendingPrepared
                && requestId == 0
                && emitted.Length == 0,
            ["pending_prepared"] = pendingPrepared,
            ["request_id"] = requestId,
            ["command_request_count"] = emitted.Length,
            ["blocked_before_stale_selection"] = requestId == 0,
        };
    }

    private List<Dictionary<string, object?>> RunEditMeshCommandPageDiagnostics()
    {
        var rows = new List<Dictionary<string, object?>>();
        rows.Add(RunEditMeshCommandPageDiagnostic(
            "topology",
            ToolRailPage.Topology,
            () => WriteCommandRequest("recalculate_normals") > 0));
        rows.Add(RunEditMeshCommandPageDiagnostic(
            "morph",
            ToolRailPage.MorphRefit,
            () => WriteCommandRequest("morph_state_request") > 0));
        rows.Add(RunEditMeshCommandPageDiagnostic(
            "viewport",
            ToolRailPage.Viewport,
            () =>
            {
                _viewport.FrameMesh();
                return true;
            }));
        return rows;
    }

    private Dictionary<string, object?> RunEditMeshCommandPageDiagnostic(
        string row,
        ToolRailPage page,
        Func<bool> exercise)
    {
        var started = Stopwatch.StartNew();
        ShowToolRailPage(page);
        PerformLayout();
        var exercised = exercise();
        var frame = RunEditMeshDiagnosticFrame();
        started.Stop();
        return new Dictionary<string, object?>
        {
            ["ok"] = exercised
                && _selectedToolRailPage == page
                && _toolRailPages.GetValueOrDefault(page)?.Parent is not null
                && frame.GetValueOrDefault("ok") is true
                && _viewport.TexturesEnabled
                && _viewport.HasTexturedMaterialResources,
            ["rail_row"] = row,
            ["page"] = page.ToString(),
            ["exercised"] = exercised,
            ["elapsed_ms"] = started.Elapsed.TotalMilliseconds,
            ["frame"] = frame,
            ["textures_enabled_after"] = _viewport.TexturesEnabled,
            ["bound_texture_resources_after"] = _viewport.HasTexturedMaterialResources,
        };
    }

    private Dictionary<string, object?> RunEditMeshDiagnosticFrame()
    {
        var ok = _viewport.TryRunHeadlessRendererFrame(
            out var frameMs,
            out var presentMs,
            out var error);
        return new Dictionary<string, object?>
        {
            ["ok"] = ok,
            ["frame_ms"] = frameMs,
            ["present_ms"] = presentMs,
            ["error"] = error,
            ["textures_enabled"] = _viewport.TexturesEnabled,
            ["bound_texture_resources"] = _viewport.HasTexturedMaterialResources,
        };
    }

    private static List<Point> EditMeshDiagnosticPath(
        string mode,
        Point start,
        Size size,
        bool sustained)
    {
        var radiusX = Math.Max(24, size.Width / 5);
        var radiusY = Math.Max(24, size.Height / 5);
        if (mode.Contains("_lasso_", StringComparison.Ordinal))
        {
            var corners = new[]
            {
                new Point(start.X - radiusX, start.Y - radiusY),
                new Point(start.X + radiusX, start.Y - radiusY),
                new Point(start.X + radiusX, start.Y + radiusY),
                new Point(start.X - radiusX, start.Y + radiusY),
                new Point(start.X - radiusX, start.Y - radiusY),
            };
            return InterpolateDiagnosticPath(corners, 12);
        }
        if (mode.Contains("_rectangle_", StringComparison.Ordinal))
        {
            return new List<Point>
            {
                new(start.X + radiusX, start.Y + radiusY),
            };
        }
        var count = sustained ? 360 : 72;
        var points = new List<Point>(count);
        for (var index = 1; index <= count; index++)
        {
            var phase = index / (double)count * Math.Tau * (sustained ? 6.0 : 2.0);
            points.Add(new Point(
                start.X + (int)Math.Round(Math.Sin(phase) * radiusX),
                start.Y + (int)Math.Round(Math.Sin(phase * 2.0) * radiusY)));
        }
        if (!mode.StartsWith("select_", StringComparison.Ordinal))
        {
            // End away from the origin. A closed synthetic path is useful for
            // cursor coverage but correctly produces no net Move/Grab delta,
            // which would make a healthy authority reconciliation look like a
            // snap-back defect.
            points.Add(new Point(start.X + radiusX / 2, start.Y + radiusY / 3));
        }
        return points;
    }

    private static List<Point> InterpolateDiagnosticPath(IReadOnlyList<Point> anchors, int steps)
    {
        var points = new List<Point>((anchors.Count - 1) * steps);
        for (var segment = 1; segment < anchors.Count; segment++)
        {
            var first = anchors[segment - 1];
            var last = anchors[segment];
            for (var step = 1; step <= steps; step++)
            {
                var ratio = step / (double)steps;
                points.Add(new Point(
                    (int)Math.Round(first.X + (last.X - first.X) * ratio),
                    (int)Math.Round(first.Y + (last.Y - first.Y) * ratio)));
            }
        }
        return points;
    }

    private static bool SelectionDiagnosticPayloadMatches(
        Dictionary<string, object?>? payload,
        string shape,
        string target)
    {
        if (payload is null
            || !string.Equals(
                Convert.ToString(payload.GetValueOrDefault("target_mode")),
                target,
                StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }
        if (shape == "brush")
        {
            return payload.GetValueOrDefault("screen_brush") is Dictionary<string, object?>;
        }
        if (payload.GetValueOrDefault("screen_region") is not Dictionary<string, object?> region)
        {
            return false;
        }
        if (shape == "lasso")
        {
            return string.Equals(
                    Convert.ToString(region.GetValueOrDefault("mode")),
                    "lasso",
                    StringComparison.OrdinalIgnoreCase)
                && region.GetValueOrDefault("points") is Array points
                && points.Length >= 3;
        }
        return !string.Equals(
            Convert.ToString(region.GetValueOrDefault("mode")),
            "lasso",
            StringComparison.OrdinalIgnoreCase);
    }

    private static double ElapsedMilliseconds(long started) =>
        (Stopwatch.GetTimestamp() - started) * 1000.0 / Stopwatch.Frequency;

    private static double Percentile(IReadOnlyList<double> values, double percentile)
    {
        if (values.Count == 0)
        {
            return 0.0;
        }
        var ordered = values.OrderBy(value => value).ToArray();
        var index = Math.Clamp(
            (int)Math.Ceiling(ordered.Length * percentile) - 1,
            0,
            ordered.Length - 1);
        return ordered[index];
    }
}
