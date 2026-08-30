namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Executable inventory for the controls a reader can reach in Edit Mesh.
/// The inventory is resolved against one real <see cref="ExperimentForm"/>
/// rather than a second set of stand-in widgets.  Adding an interactive
/// control to a production section without adding a row below therefore makes
/// the headless contract fail with that control's path.
/// </summary>
internal sealed partial class ExperimentForm
{
    private sealed record MeshEditorControlContractRow(
        string Key,
        string Surface,
        string Owner,
        string Route,
        string Disposition,
        string Availability,
        string Reason,
        string EvidenceCategory,
        Control? Control,
        bool HostOwned = false);

    private const string ContractExecutable = "executable";
    private const string ContractDisabled = "deliberately_disabled";

    private delegate void ControlContractAdd(
        string key,
        string surface,
        string owner,
        string route,
        Control? control,
        string disposition = ContractExecutable,
        string availability = "session",
        string reason = "",
        string evidenceCategory = "real_form_control_route");

    private delegate void ControlContractAddHostOwned(
        string key,
        string surface,
        string owner,
        string route,
        string disposition,
        string availability,
        string reason,
        string evidenceCategory);

    internal Dictionary<string, object?> MeshEditorControlContractProof()
    {
        BuildAuthoringToolPanels();
        ActivateToolRailLayout();
        ApplyDiagnosticOutputPolicyState(
            "exact_game_asset",
            destinationReady: false,
            authoringEnabled: true);

        var rows = new List<MeshEditorControlContractRow>();
        var unresolved = new List<string>();
        var duplicateControls = new List<string>();
        var classifiedControls = new Dictionary<Control, string>(ReferenceEqualityComparer.Instance);

        void Add(
            string key,
            string surface,
            string owner,
            string route,
            Control? control,
            string disposition = ContractExecutable,
            string availability = "session",
            string reason = "",
            string evidenceCategory = "real_form_control_route")
        {
            rows.Add(new MeshEditorControlContractRow(
                key,
                surface,
                owner,
                route,
                disposition,
                availability,
                reason,
                evidenceCategory,
                control));
            if (control is null)
            {
                unresolved.Add(key);
                return;
            }
            if (!classifiedControls.TryAdd(control, key))
            {
                duplicateControls.Add($"{key} -> {classifiedControls[control]}");
            }
        }

        void AddHostOwned(
            string key,
            string surface,
            string owner,
            string route,
            string disposition,
            string availability,
            string reason,
            string evidenceCategory)
        {
            rows.Add(new MeshEditorControlContractRow(
                key,
                surface,
                owner,
                route,
                disposition,
                availability,
                reason,
                evidenceCategory,
                Control: null,
                HostOwned: true));
        }

        AddToolAndTopologyControlContractRows(Add, AddHostOwned);
        AddPartsAndMorphControlContractRows(Add);
        AddPresentationControlContractRows(Add, AddHostOwned);
        return BuildMeshEditorControlContractReport(
            rows,
            unresolved,
            duplicateControls,
            classifiedControls);
    }

    private void AddToolAndTopologyControlContractRows(
        ControlContractAdd Add,
        ControlContractAddHostOwned AddHostOwned)
    {

        // The list itself is the production registry for the six modal tools
        // and two reveal-only pages; no caption copy is used to find them.
        foreach (var key in EditMeshLayoutContracts.RailToolOrder)
        {
            Add(
                $"tool.{key}",
                "tools",
                "ExperimentForm.ToolList",
                "ActivateTool",
                _toolRailToolButtons.GetValueOrDefault(key),
                evidenceCategory: "hidden_d3d11_protocol");
        }
        Add(
            "page.topology",
            "topology",
            "ExperimentForm.ToolList",
            "ShowToolRailPage(Topology)",
            _toolRailPageButtons.GetValueOrDefault(ToolRailPage.Topology));
        Add(
            "page.morph_refit",
            "morph_refit",
            "ExperimentForm.ToolList",
            "ShowToolRailPage(MorphRefit)",
            _toolRailPageButtons.GetValueOrDefault(ToolRailPage.MorphRefit));
        Add("session.clear_selection", "session", "ExperimentForm.ToolPanels", "WriteCommandRequest(clear_selection)", _sessionClearSelectionButton);
        Add("session.select_all", "session", "ExperimentForm.ToolPanels", "WriteCommandRequest(select_all)", _sessionSelectAllButton);
        Add("session.invert", "session", "ExperimentForm.ToolPanels", "WriteCommandRequest(invert)", _sessionInvertButton);
        Add("session.undo", "session", "ExperimentForm.History", "WriteCommandRequest(undo)", _undoButton, availability: "history");
        Add("session.redo", "session", "ExperimentForm.History", "WriteCommandRequest(redo)", _redoButton, availability: "history");
        Add("output.configure_free_edit", "import_output_export", "ExperimentForm.OutputPolicy", "WriteCommandRequest(configure_free_edit)", _configureFreeEditButton);
        Add(
            "output.export_free_edit",
            "import_output_export",
            "ExperimentForm.OutputPolicy",
            "WriteCommandRequest(export_free_edit)",
            _exportFreeEditButton,
            ContractDisabled,
            "free_edit_only",
            "Export is enabled only after a Free Edit OBJ destination is proven.");
        if (_sessionFinishButton is not null)
        {
            Add("session.finish", "session", "ExperimentForm.ToolPanels", "RequestFinishEditMesh or SaveAndReport", _sessionFinishButton);
        }
        else
        {
            AddHostOwned(
                "session.finish",
                "session",
                "Python Mesh Editor host",
                "Finish Edit Mesh host action",
                ContractExecutable,
                "host_owned",
                "",
                "python_host_contract");
        }

        Add("selection.target", "selection", "ExperimentForm.ToolPanels", "MeshViewport target mode", _selectionTarget);
        Add("selection.shape", "selection", "ExperimentForm.ToolPanels", "MeshViewport.SetSelectionDragMode", _selectionShape);
        Add("selection.operation", "selection", "ExperimentForm.ToolPanels", "selection operation payload", _selectionOperation);
        Add("selection.xray", "selection", "ExperimentForm.Controls", "ConfigureXRayToggle", _xray);
        Add("selection.grow", "selection", "ExperimentForm.ToolPanels", "WriteCommandRequest(grow)", ButtonIn(_selectionSection, "Grow"));
        Add("selection.shrink", "selection", "ExperimentForm.ToolPanels", "WriteCommandRequest(shrink)", ButtonIn(_selectionSection, "Shrink"));
        Add(
            "selection.create_part",
            "selection",
            "ExperimentForm.PartsSection",
            "RequestCreatePartFromSelection",
            _createPartFromSelectionButton,
            ContractDisabled,
            "free_edit_faces_only",
            "Create Part is unavailable because the exact PAC writer cannot add a protected submesh record.");

        Add("transform.translate_step", "tools", "ExperimentForm.ToolPanels", "AxisNudgeRow", _translateStep);
        Add("transform.grab_radius", "tools", "ExperimentForm.ToolPanels", "ToolOptionsPayload", _grabRadius);
        foreach (var axis in new[] { "-X", "+X", "-Y", "+Y", "-Z", "+Z" })
        {
            Add($"transform.nudge.{axis.ToLowerInvariant()}", "tools", "ExperimentForm.ButtonRow", "WriteNudgeRequest", ButtonIn(_transformSection, axis));
        }
        Add("brush.radius", "tools", "ExperimentForm.ToolPanels", "ToolOptionsPayload", _radius);
        Add("brush.strength", "tools", "ExperimentForm.ToolPanels", "ToolOptionsPayload", _strength);
        Add("brush.falloff", "tools", "ExperimentForm.ToolPanels", "ToolOptionsPayload", _falloff);

        Add("topology.delete_selection", "topology", "ExperimentForm.OutputPolicy", "WriteCommandRequest(delete)", ButtonIn(_topologySection, "Delete Selection"));
        Add(
            "topology.duplicate_selection",
            "topology",
            "ExperimentForm.OutputPolicy",
            "WriteCommandRequest(duplicate)",
            ButtonIn(_topologySection, "Duplicate Selection"),
            ContractDisabled,
            "free_edit_only",
            "Duplicate Selection is unavailable because the exact PAC writer cannot add protected geometry records.");
        Add(
            "topology.subdivide",
            "topology",
            "ExperimentForm.OutputPolicy",
            "WriteCommandRequest(subdivide)",
            ButtonIn(_topologySection, "Subdivide"),
            ContractDisabled,
            "free_edit_only",
            "Subdivide is unavailable because derived PAC vertices cannot preserve protected bytes.");
        Add(
            "topology.refine_smooth",
            "topology",
            "ExperimentForm.OutputPolicy",
            "WriteCommandRequest(refine_smooth)",
            ButtonIn(_topologySection, "Refine Smooth"),
            ContractDisabled,
            "free_edit_only",
            "Refine Smooth is unavailable because derived PAC vertices cannot preserve protected bytes.");
        foreach (var pair in _freeEditOnlyButtons.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            Add(
                $"topology.{pair.Key}",
                "topology",
                "ExperimentForm.OutputPolicy",
                $"WriteCommandRequest({pair.Key})",
                pair.Value,
                ContractDisabled,
                "free_edit_only",
                DirectAuthoringCommandBlocker(pair.Key));
        }

    }

    private void AddPartsAndMorphControlContractRows(ControlContractAdd Add)
    {
        Add("parts.selection", "parts_layers", "ExperimentForm.PartsSection", "MeshViewport.SelectPartsFromList", _submeshList);
        Add("parts.select_all", "parts_layers", "ExperimentForm.PartsSection", "SelectAllParts", ButtonIn(_partsSection, "All"));
        Add("parts.select_none", "parts_layers", "ExperimentForm.PartsSection", "ClearPartSelection", ButtonIn(_partsSection, "None"));
        Add("parts.invert", "parts_layers", "ExperimentForm.PartsSection", "InvertPartSelection", ButtonIn(_partsSection, "Invert"));
        Add(
            "parts.visibility",
            "parts_layers",
            "ExperimentForm.PartsSection",
            "WriteCommandRequest(toggle_visibility)",
            _partVisibilityButton,
            ContractDisabled,
            "not_stored_in_exact_output",
            "Part visibility editing has no stored output authority in direct authoring.");
        Add(
            "parts.duplicate",
            "parts_layers",
            "ExperimentForm.ToolPanels",
            "WriteCommandRequest(duplicate source)",
            _partDuplicateButton,
            ContractDisabled,
            "free_edit_only",
            "Duplicate Part is unavailable because the exact PAC writer cannot add a protected submesh record.");
        Add(
            "parts.delete",
            "parts_layers",
            "ExperimentForm.ToolPanels",
            "WriteCommandRequest(delete source)",
            _partDeleteButton,
            ContractDisabled,
            "free_edit_only",
            "Delete Part is unavailable because the exact PAC writer cannot remove a protected submesh record.");

        Add("layers.list", "parts_layers", "ExperimentForm.GeometryLayers", "layer visibility and activation command", _geometryLayerList);
        Add(
            "layers.copy",
            "parts_layers",
            "ExperimentForm.GeometryLayers",
            "WriteCommandRequest(copy)",
            _layerCopyButton,
            ContractDisabled,
            "free_edit_only",
            "Copy is unavailable because copied geometry has no exact PAC writeback route.");
        Add(
            "layers.paste",
            "parts_layers",
            "ExperimentForm.GeometryLayers",
            "WriteCommandRequest(paste)",
            _layerPasteButton,
            ContractDisabled,
            "free_edit_only",
            "Paste is unavailable because copied geometry has no exact PAC writeback route.");
        Add("layers.rename", "parts_layers", "ExperimentForm.GeometryLayers", "BeginRenameGeometryLayer", _layerRenameButton, availability: "non_base_layer");
        Add("layers.move_up", "parts_layers", "ExperimentForm.GeometryLayers", "WriteCommandRequest(layer_move -1)", _layerMoveUpButton, availability: "non_base_layer");
        Add("layers.move_down", "parts_layers", "ExperimentForm.GeometryLayers", "WriteCommandRequest(layer_move +1)", _layerMoveDownButton, availability: "non_base_layer");
        Add(
            "layers.delete",
            "parts_layers",
            "ExperimentForm.GeometryLayers",
            "WriteCommandRequest(layer_delete)",
            _layerDeleteButton,
            ContractDisabled,
            "free_edit_non_base_layer",
            "Layer Delete is unavailable because changed topology has no exact PAC writeback route.");
        Add("history.timeline", "session", "ExperimentForm.History", "resident action timeline", _actionHistoryList, availability: "read_only_view");

        Add("morph.collapse", "morph_refit", "ExperimentForm.MorphRefit", "collapse or expand Morph and Refit", _morphSectionHeader);
        Add("morph.profile", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphUiCommand(morph_activate)", _morphProfile);
        Add("morph.create_profile", "morph_refit", "ExperimentForm.MorphAuthoring", "ShowMorphAuthorDialog", _morphAuthorButton);
        Add("morph.save_profile", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphUiCommand(morph_save_profile)", ButtonIn(_morphRefitSection, "Save Profile"), availability: "active_profile");
        Add("morph.delete_profile", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphUiCommand(morph_delete_profile)", ButtonIn(_morphRefitSection, "Delete Profile"), availability: "active_profile");
        Add("morph.preset", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphUiCommand(morph_apply_preset)", _morphPreset);
        Add("morph.save_preset", "morph_refit", "ExperimentForm.MorphRefit", "SaveMorphPreset", ButtonIn(_morphRefitSection, "Save Preset..."), availability: "active_profile");
        Add("morph.delete_preset", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphUiCommand(morph_delete_preset)", ButtonIn(_morphRefitSection, "Delete Preset"), availability: "active_preset");
        Add("refit.set_driver", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphSetDriver", ButtonIn(_morphRefitSection, "1. Set Selected Driver Parts"), availability: "part_selection");
        Add("refit.bind_garment", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphBind", ButtonIn(_morphRefitSection, "2. Bind Selected Garment Parts"), availability: "driver_and_part_selection");
        Add("refit.clear", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphUiCommand(morph_clear_refit)", ButtonIn(_morphRefitSection, "Clear Refit"));
        Add("refit.enabled", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphConfigureRefit", _morphRefitEnabled, availability: "bound_garment");
        Add("refit.mode", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphConfigureRefit", _morphRefitMode, availability: "bound_garment");
        Add("refit.intensity", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphConfigureRefit", _morphRefitIntensity, availability: "bound_garment");
        Add("refit.clearance", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphConfigureRefit", _morphRefitClearance, availability: "bound_garment");
        Add("refit.apply", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphConfigureRefit", ButtonIn(_morphRefitSection, "Apply to Selected Garments"), availability: "bound_garment");
        Add("morph.reset", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphUiCommand(morph_reset)", ButtonIn(_morphRefitSection, "Reset"), availability: "active_profile");
        Add("morph.bake", "morph_refit", "ExperimentForm.MorphRefit", "RequestMorphUiCommand(morph_bake)", ButtonIn(_morphRefitSection, "Bake"), availability: "unbaked_change");
        foreach (var pair in _morphSliders.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            Add($"morph.slider.{pair.Key}.track", "morph_refit", "ExperimentForm.MorphAuthoring", "QueueMorphSliderUpdate", pair.Value.Track, availability: "active_profile");
            Add($"morph.slider.{pair.Key}.numeric", "morph_refit", "ExperimentForm.MorphAuthoring", "QueueMorphSliderUpdate", pair.Value.Numeric, availability: "active_profile");
        }

    }

    private void AddPresentationControlContractRows(
        ControlContractAdd Add,
        ControlContractAddHostOwned AddHostOwned)
    {
        Add("display.mode", "camera_display", "ExperimentForm.Controls", "RequestResidentViewportDisplay", _previewMode, evidenceCategory: "hidden_d3d11_presentation");
        Add("display.overlay.wire_colour", "camera_display", "ExperimentForm.AppearanceControls", "ChooseOverlayColor(wire)", _wireColorButton);
        Add("display.overlay.vertex_colour", "camera_display", "ExperimentForm.AppearanceControls", "ChooseOverlayColor(vertex)", _vertexColorButton);
        Add("display.overlay.selection_colour", "camera_display", "ExperimentForm.AppearanceControls", "ChooseOverlayColor(selection)", _selectionColorButton);
        Add("display.overlay.live_selection_colour", "camera_display", "ExperimentForm.AppearanceControls", "ChooseOverlayColor(live_selection)", _liveSelectionColorButton);
        Add("display.overlay.reset", "camera_display", "ExperimentForm.AppearanceControls", "ResetOverlayAppearance", NamedIn(_viewportSection, "OverlayAppearanceResetButton"));
        Add("display.overlay.wire_width", "camera_display", "ExperimentForm.AppearanceControls", "ApplyOverlaySizing", _wireOverlayWidth);
        Add("display.overlay.vertex_size", "camera_display", "ExperimentForm.AppearanceControls", "ApplyOverlaySizing", _vertexMarkerSize);
        Add("display.background_colour", "camera_display", "ExperimentForm.AppearanceControls", "ChooseViewportColor(background)", _backgroundColorButton);
        Add("display.grid_colour", "camera_display", "ExperimentForm.AppearanceControls", "ChooseViewportColor(grid)", _gridColorButton);
        Add("display.colours.reset", "camera_display", "ExperimentForm.AppearanceControls", "ResetViewportColors", NamedIn(_viewportSection, "ViewportColorResetButton"));
        foreach (var preset in new[] { "Front", "Back", "Top", "Left", "Right", "Bottom" })
        {
            Add($"camera.{preset.ToLowerInvariant()}", "camera_display", "ExperimentForm.Controls", "MeshViewport.SetCameraPreset", ButtonIn(_viewportSection, preset));
        }
        Add("camera.yaw_minus_15", "camera_display", "ExperimentForm.ToolPanels", "MeshViewport.RotateYawDegrees(-15)", ButtonIn(_viewportSection, "-15"));
        Add("camera.yaw_plus_15", "camera_display", "ExperimentForm.ToolPanels", "MeshViewport.RotateYawDegrees(+15)", ButtonIn(_viewportSection, "+15"));
        Add("camera.fit", "camera_display", "ExperimentForm.ToolPanels", "MeshViewport.FrameMesh", ButtonIn(_viewportSection, "Fit"));
        Add("camera.orbit", "camera_display", "ExperimentForm.Controls", "ActivateTool(orbit)", _toolButtons.GetValueOrDefault("orbit"));
        Add("viewport.pointer_surface", "camera_display", "MeshViewport.Input", "resident viewport pointer input", _viewport, evidenceCategory: "hidden_d3d11_input");

        if (_colourSection is not null)
        {
            Add("colour.tint", "material_colour", "ExperimentForm.ColourSection", "QueuePartColourEdit(tint)", _partTintButton);
            Add("colour.recolour", "material_colour", "ExperimentForm.ColourSection", "QueuePartColourEdit(colourise)", _partRecolourButton);
            Add("colour.recolour_strength", "material_colour", "ExperimentForm.ColourSection", "QueuePartColourEdit(colourise_strength)", _partRecolourStrength);
            Add("colour.emissive_enabled", "material_colour", "ExperimentForm.ColourSection", "QueuePartColourEdit(emissive)", _partEmissiveCheck);
            Add("colour.emissive_colour", "material_colour", "ExperimentForm.ColourSection", "QueuePartColourEdit(emissive_rgb)", _partEmissiveButton);
            Add("colour.emissive_strength", "material_colour", "ExperimentForm.ColourSection", "QueuePartColourEdit(emissive_strength)", _partEmissiveStrength);
            Add("colour.reset", "material_colour", "ExperimentForm.ColourSection", "QueuePartColourEdit(reset)", _partColourResetButton);
            Add("colour.split_selection", "material_colour", "ExperimentForm.ColourSection", "WriteCommandRequest(separate)", _partColourSplitButton, availability: "selected_faces");
        }
        else
        {
            AddHostOwned(
                "material_colour.unavailable",
                "material_colour",
                "ExperimentForm.ColourSection",
                "removed from Mesh Editor construction",
                ContractDisabled,
                "not_reachable",
                "Mesh Editor no longer exposes the obsolete Colour authoring section.",
                "removed_control_contract");
        }

        AddHostOwned(
            "import.open_package",
            "import_output_export",
            "Python Mesh Editor host",
            "Import/Open toolbar action",
            ContractExecutable,
            "host_owned",
            "",
            "python_host_contract");
        AddHostOwned(
            "policy.exact_free_edit",
            "exact_free_edit",
            "ExperimentForm.OutputPolicy",
            "ApplyOutputPolicyState",
            ContractExecutable,
            "session_policy",
            "",
            "synthetic_protocol_contract");

    }

    private Dictionary<string, object?> BuildMeshEditorControlContractReport(
        List<MeshEditorControlContractRow> rows,
        List<string> unresolved,
        List<string> duplicateControls,
        Dictionary<Control, string> classifiedControls)
    {
        var reachable = ReachableMeshEditorInteractiveControls().ToArray();
        var reachableSet = reachable.ToHashSet(ReferenceEqualityComparer.Instance);
        var unclassified = reachable
            .Where(control => !classifiedControls.ContainsKey(control))
            .Select(ControlContractPath)
            .OrderBy(path => path, StringComparer.Ordinal)
            .ToArray();
        var classifiedOutsideReachableSurface = classifiedControls
            .Where(pair => !reachableSet.Contains(pair.Key))
            .Select(pair => $"{pair.Value}: {ControlContractPath(pair.Key)}")
            .OrderBy(path => path, StringComparer.Ordinal)
            .ToArray();
        var requiredSurfaces = new[]
        {
            "session",
            "selection",
            "tools",
            "topology",
            "parts_layers",
            "morph_refit",
            "material_colour",
            "camera_display",
            "import_output_export",
            "exact_free_edit",
        };
        var missingSurfaces = requiredSurfaces
            .Where(surface => !rows.Any(row => string.Equals(row.Surface, surface, StringComparison.Ordinal)))
            .ToArray();
        var invalidDisabledRows = rows
            .Where(row => row.Disposition == ContractDisabled && string.IsNullOrWhiteSpace(row.Reason))
            .Select(row => row.Key)
            .ToArray();
        var enabledDisabledControls = rows
            .Where(row => row.Disposition == ContractDisabled
                && row.Control is not null
                && OwnEnabledState(row.Control))
            .Select(row => row.Key)
            .ToArray();
        var disabledControlsWithoutUserReason = rows
            .Where(row => row.Disposition == ContractDisabled
                && row.Control is not null
                && string.IsNullOrWhiteSpace(row.Control.AccessibleDescription))
            .Select(row => row.Key)
            .ToArray();
        var invalidDispositions = rows
            .Where(row => row.Disposition is not ContractExecutable and not ContractDisabled)
            .Select(row => row.Key)
            .ToArray();
        var keys = rows.Select(row => row.Key).ToArray();
        var duplicateKeys = keys
            .GroupBy(key => key, StringComparer.Ordinal)
            .Where(group => group.Count() > 1)
            .Select(group => group.Key)
            .ToArray();
        var ok = unresolved.Count == 0
            && duplicateControls.Count == 0
            && unclassified.Length == 0
            && classifiedOutsideReachableSurface.Length == 0
            && missingSurfaces.Length == 0
            && invalidDisabledRows.Length == 0
            && enabledDisabledControls.Length == 0
            && invalidDispositions.Length == 0
            && duplicateKeys.Length == 0;

        return new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_mesh_editor_control_contract_v1",
            ["ok"] = ok,
            ["proof_class"] = "headless_real_form_construction",
            ["visual_proof"] = false,
            ["renderer_started"] = false,
            ["control_count"] = reachable.Length,
            ["row_count"] = rows.Count,
            ["host_owned_row_count"] = rows.Count(row => row.HostOwned),
            ["required_surfaces"] = requiredSurfaces,
            ["missing_surfaces"] = missingSurfaces,
            ["unresolved_rows"] = unresolved,
            ["duplicate_control_rows"] = duplicateControls,
            ["duplicate_keys"] = duplicateKeys,
            ["unclassified_controls"] = unclassified,
            ["classified_outside_reachable_surface"] = classifiedOutsideReachableSurface,
            ["invalid_disabled_rows"] = invalidDisabledRows,
            ["enabled_disabled_controls"] = enabledDisabledControls,
            ["disabled_controls_without_user_reason"] = disabledControlsWithoutUserReason,
            ["invalid_dispositions"] = invalidDispositions,
            ["known_gaps"] = rows
                .Where(row => row.EvidenceCategory == "known_control_gap")
                .Select(row => row.Key)
                .ToArray(),
            ["rows"] = rows.Select(row => new Dictionary<string, object?>
            {
                ["key"] = row.Key,
                ["surface"] = row.Surface,
                ["owner"] = row.Owner,
                ["route"] = row.Route,
                ["disposition"] = row.Disposition,
                ["availability"] = row.Availability,
                ["reason"] = row.Reason,
                ["evidence_category"] = row.EvidenceCategory,
                ["host_owned"] = row.HostOwned,
                ["control_type"] = row.Control?.GetType().Name ?? "host",
                ["control_name"] = row.Control?.Name ?? string.Empty,
                ["control_text"] = row.Control?.Text ?? string.Empty,
                ["currently_visible"] = row.Control is not null && OwnVisibleState(row.Control),
                ["currently_enabled"] = row.Control is not null && OwnEnabledState(row.Control),
            }).ToArray(),
        };
    }

    private static Button? ButtonIn(Control? root, string text) => root is null
        ? null
        : DescendantControls(root)
            .OfType<Button>()
            .SingleOrDefault(button => string.Equals(button.Text, text, StringComparison.Ordinal));

    private static Control? NamedIn(Control? root, string name) => root?.Controls
        .Find(name, searchAllChildren: true)
        .SingleOrDefault();

    private IEnumerable<Control> ReachableMeshEditorInteractiveControls()
    {
        var controls = new HashSet<Control>(ReferenceEqualityComparer.Instance);
        var roots = new Control?[]
        {
            _compactSessionBar,
            _selectionSection,
            _transformSection,
            _brushSection,
            _topologySection,
            _morphRefitSection,
            _viewportSection,
            _partsSection,
            _layersSection,
            _actionHistorySection,
            _colourSection,
        };
        foreach (var root in roots.Where(root => root is not null).Cast<Control>())
        {
            foreach (var control in DescendantControls(root).Where(IsContractInteractiveControl))
            {
                controls.Add(control);
            }
        }
        foreach (var control in _toolRailToolButtons.Values)
        {
            controls.Add(control);
        }
        foreach (var control in _toolRailPageButtons.Values)
        {
            controls.Add(control);
        }
        controls.Add(_viewport);
        return controls;
    }

    private static bool IsContractInteractiveControl(Control control)
    {
        // NumericUpDown owns an implementation TextBox.  It is not a second
        // reader-facing control and has no route independent of its owner.
        if (control is TextBoxBase && control.Parent is UpDownBase)
        {
            return false;
        }
        return control is
            ButtonBase
            or ComboBox
            or UpDownBase
            or TrackBar
            or ListBox
            or ListView
            or TextBoxBase;
    }

    private static string ControlContractPath(Control control)
    {
        var parts = new Stack<string>();
        for (Control? current = control; current is not null; current = current.Parent)
        {
            var identity = !string.IsNullOrWhiteSpace(current.Name)
                ? current.Name
                : !string.IsNullOrWhiteSpace(current.Text)
                    ? $"{current.GetType().Name}[{current.Text}]"
                    : current.GetType().Name;
            parts.Push(identity);
        }
        return string.Join("/", parts);
    }
}
