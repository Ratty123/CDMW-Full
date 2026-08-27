from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_EDITOR = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    # Partials of one class are concatenated in the order listed: the assertions
    # below read the constructor before the hidden startup that follows it.
    patterns = {
        "Program.cs": ("Program.cs", "ExperimentForm.ToolPanels.cs", "ExperimentForm.StartupRealization.cs"),
        "ExperimentForm.Controls.cs": ("ExperimentForm.Controls.cs", "ExperimentForm.FlatButton.cs"),
        "D3D11MaterialViewport.cs": ("D3D11MaterialViewport*.cs",),
        "D3D11MaterialViewport.Overlay.cs": ("D3D11MaterialViewport.Overlay.cs", "D3D11MaterialViewport.OverlayInteraction.cs", "D3D11MaterialViewport.OverlaySelection.cs"),
        "MeshViewport.SelectionPicking.cs": (
            "MeshViewport.SelectionPicking.cs",
            "MeshViewport.SelectionPaint.cs",
            "MeshViewport.SelectionPaintHits.cs",
        ),
    }.get(name, (name,))
    paths: list[Path] = []
    for pattern in patterns:
        for path in sorted(DOTNET_EDITOR.glob(pattern)):
            if path not in paths:
                paths.append(path)
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_renderer_status_response_preserves_mutation_correlation() -> None:
    source = _source("ExperimentForm.MaterialProtocol.cs")
    handler = source.split(
        "private void HandleRendererStatusRequest(JsonElement request)", maxsplit=1
    )[1].split(
        "private Dictionary<string, object?> RendererCompactStatusWithLifecycle()",
        maxsplit=1,
    )[0]

    assert '["request_id"] = JsonLongValue(request, "request_id")' in handler
    assert '["session_id"] = JsonString(request, "session_id")' in handler
    assert '["process_generation"] = JsonLongValue(request, "process_generation")' in handler
    assert 'WriteProtocolEvent("renderer_status", payload)' in handler

def test_equal_surface_resize_refreshes_initial_render_pane_layout() -> None:
    renderer_source = _source("MeshViewport.Renderer.cs")
    equal_bounds = renderer_source.split(
        "if (viewport.Bounds == ClientRectangle)", maxsplit=1
    )[1].split("_renderSurfaceResizeTimer.Start();", maxsplit=1)[0]

    assert equal_bounds.index("UpdateGpuViewport();") < equal_bounds.index("return;")


def test_split_panes_track_the_render_surface_and_release_pointer_capture() -> None:
    split_view_source = _source("MeshViewport.SplitView.cs")
    input_source = _source("MeshViewport.Input.cs")
    scene_proofs = _source("HeadlessGpuSparseSoak.SceneProofs.cs")

    role_bounds = split_view_source.split(
        "private (Rectangle Reference, Rectangle Editable) RolePaneBounds()",
        maxsplit=1,
    )[1].split("private Rectangle ActivePaneBounds()", maxsplit=1)[0]
    mouse_up = input_source.split(
        "protected override void OnMouseUp",
        maxsplit=1,
    )[1].split("protected override void OnMouseMove", maxsplit=1)[0]

    assert "EffectivePaneSurfaceSize(" in split_view_source
    assert "surface?.ClientSize ?? Size.Empty" in split_view_source
    assert "var surfaceSize = PaneSurfaceSize();" in role_bounds
    assert "Math.Max(1, Width)" not in role_bounds
    assert "SetRenderSurfaceCapture(true);" in input_source
    assert "finally" in mouse_up
    assert "SetRenderSurfaceCapture(false);" in mouse_up
    assert "_capturedInputPane = string.Empty;" in mouse_up
    assert "pane_geometry_tracks_current_render_surface" in scene_proofs


def test_part_pick_off_routes_authoritative_clear_selection() -> None:
    program_source = _source("Program.cs")
    part_pick_handler = program_source.split(
        '_partPick.CheckedChanged += (_, _) =>', maxsplit=1
    )[1].split("var left = new Panel", maxsplit=1)[0]
    command_guard = program_source.split(
        "private long WriteCommandRequest", maxsplit=1
    )[1].split("var targetMode = SelectionTarget();", maxsplit=1)[0]

    assert 'WriteCommandRequest("clear_selection");' in part_pick_handler
    assert "Part Pick disabled; clearing selection." in part_pick_handler
    assert '!string.Equals(command, "clear_selection", StringComparison.OrdinalIgnoreCase)' in command_guard


def test_dotnet_tool_protocol_keeps_selection_strokes_and_vertex_refresh_in_sync() -> None:
    input_source = _source("MeshViewport.Input.cs")
    selection_source = _source("MeshViewport.Status.cs")
    picking_source = _source("MeshViewport.SelectionPicking.cs")
    protocol_source = _source("ExperimentForm.Protocol.cs")
    host_state_source = _source("ExperimentForm.HostState.cs")
    host_diagnostics_source = _source("MeshViewport.HostDiagnostics.cs")
    program_source = _source("Program.cs")
    topology_source = _source("MeshViewport.Topology.cs")
    d3d_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOTNET_EDITOR.glob("D3D11MaterialViewport*.cs"))
    )
    texture_source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(DOTNET_EDITOR.glob("NetTextureSet*.cs")))
    material_source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(DOTNET_EDITOR.glob("NetMaterialSet*.cs")))
    material_protocol_source = _source("ExperimentForm.MaterialProtocol.cs")
    package_protocol_source = _source("ExperimentForm.PackageProtocol.cs")
    provenance_source = _source("HelperBuildProvenance.cs")
    all_source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(DOTNET_EDITOR.glob("*.cs")))

    assert '["local_selection"] = SelectionSnapshotPayload()' not in input_source
    assert 'EditorEventRequested?.Invoke("select_request", payload);' in picking_source
    committed_selection = picking_source.split("private void FinishEdgeDrag(Point point)", 1)[1].split(
        "private Rectangle EdgeDragRectangle", 1
    )[0]
    assert "NotifyLocalSelectionChanged();" not in committed_selection
    assert "_strokePrevious" in input_source
    assert "_strokeStart" not in input_source
    # The move handler is the only place an in-flight stroke reports a sample;
    # begin, end and cancel are owned by the stroke lifecycle helpers.
    active_stroke_move = input_source.split(
        "protected override void OnMouseMove", maxsplit=1
    )[1].split("if (_editorStrokeActive)", maxsplit=1)[1].split("else if (_rotating)", maxsplit=1)[0]
    assert "(e.Button & MouseButtons.Left) == MouseButtons.Left" in active_stroke_move
    assert active_stroke_move.index("MouseButtons.Left") < active_stroke_move.index("MaybeEmitEditorStrokeUpdate(e.Location)") < active_stroke_move.index("_strokePrevious = e.Location")
    throttled_stroke_publish = input_source.split(
        "private void MaybeEmitEditorStrokeUpdate", maxsplit=1
    )[1].split("private void EndEditorStroke", maxsplit=1)[0]
    assert "EditorStrokeProtocolIntervalMs" in throttled_stroke_publish
    assert 'Invoke("stroke_update"' in throttled_stroke_publish
    assert "_strokeProtocolPrevious = location" in throttled_stroke_publish
    assert "_viewport.RefreshVertexGeometry(changed" in protocol_source
    assert "RefreshVertexGeometry(IReadOnlyDictionary<int, IReadOnlyCollection<int>> changedVertices)" in d3d_source
    assert "SourceVertexToRenderCorners" in d3d_source
    assert "return BoundsTouchOrOverlap(SubmeshBounds(left), SubmeshBounds(right), tolerance);" in topology_source
    assert "foreach (var a in left.Vertices)" not in topology_source
    assert 'case "deactivate_request":' in protocol_source
    assert 'case "activate_request":' in protocol_source
    assert 'WriteProtocolEvent("protocol_ready"' in protocol_source
    assert 'case "tool_state": ApplyHostToolState' in protocol_source
    assert 'WriteProtocolEvent("tool_state_applied"' in host_state_source
    assert 'tool is "vertex" or "remove"' in host_state_source
    assert 'enabledElement.ValueKind != JsonValueKind.False' in host_state_source
    disabled_tool = host_state_source.split('if (!enabled)', maxsplit=1)[1].split(
        'if (!HostTools.Contains(tool))', maxsplit=1
    )[0]
    assert 'ActivateTool("orbit", "Orbit");' in disabled_tool
    assert '["enabled"] = false' in disabled_tool
    assert '"host_tool_state_v1"' in provenance_source
    assert '["viewport"] = RenderSurfaceStatusPayload()' in selection_source
    for field in ('["hwnd"]', '["form_hwnd"]', '["screen_x"]', '["screen_y"]', '["width"]', '["height"]'):
        assert field in host_diagnostics_source
    assert "Console.OpenStandardInput()" in protocol_source
    assert "_embeddedViewportActive" in program_source
    assert "StartTextureLoad();" in program_source
    assert "Task.Run(() => LoadTextures(materials))" in texture_source
    assert "materials.TextureLoadResources()" in texture_source
    assert "DecodeResourcesAsync(IEnumerable<NetMaterialResource> resources)" in texture_source
    assert "BitmapForReference(NetMaterialTextureReference reference)" in texture_source
    assert "ParseStateUpdate(JsonElement root)" in material_source
    assert "ResourceChannels" in material_source
    assert "result.Resources = ParseResources(root)" in material_source
    assert 'JsonStringMap(item, "resource_channels")' in material_source
    for semantic_diagnostic in (
        "shader_family_source",
        "shader_family_reason",
        "alpha_authority",
        "alpha_reason",
        "double_sided_authority",
        "double_sided_reason",
    ):
        assert semantic_diagnostic in material_source
    assert 'return $"fingerprint|{fingerprint}";' in texture_source
    assert "_decoded[resource.Path] = cached;" in texture_source
    assert 'case "material_state_update":' in protocol_source
    assert "QueueParsedProtocolMessage(new ParsedProtocolMessage(" in protocol_source
    assert "TryParsePreviewVertexGroups(vertexGroups, out preparedVertexUpdate)" in protocol_source
    assert "ValidatePreviewVertexGroups(_document, preparedVertexUpdate)" in protocol_source
    assert "TryPreparePreviewTriangleGroups(root, triangleGroups, out preparedTriangleUpdate)" in protocol_source
    assert "ObserveResidentSession(root);" in protocol_source
    assert 'Material state update requires session_id.' in material_protocol_source
    assert 'Resident session is not established.' in material_protocol_source
    assert "ResourceIdsForAffectedSubmeshes()" in material_source
    assert 'WriteProtocolEvent("material_sync_required"' in material_protocol_source
    assert 'WriteProtocolEvent("material_state_applied"' in material_protocol_source
    assert 'WriteProtocolEvent("material_state_failed"' in material_protocol_source
    failed_source = material_protocol_source.split('WriteProtocolEvent("material_state_failed"', maxsplit=1)[1]
    assert "MatchesPendingMaterialSync" in failed_source
    assert "ClearPendingMaterialSyncActivation();" in failed_source
    assert "ActivateResidentViewport" not in failed_source
    accepted_package = package_protocol_source.split(
        "Interlocked.Exchange(ref _residentPackageLoadGeneration, generation);",
        maxsplit=1,
    )[1].split("PrepareAndApplyResidentPackageAsync", maxsplit=1)[0]
    assert "_activationRequestId" not in accepted_package
    assert "ClearPendingMaterialSyncActivation" not in accepted_package
    activation_request = protocol_source.split('case "activate_request":', maxsplit=1)[1].split(
        'case "preview_session_state":',
        maxsplit=1,
    )[0]
    assert "MatchesAcceptedPackageGeneration" in activation_request
    assert "ClearPendingMaterialSyncActivation();" in activation_request
    # Activation reveals whatever scene is resident, and a prewarm launch is
    # holding a placeholder nobody asked to see. The check has to come before the
    # reveal, and covers all three callers by living in the one method they share.
    activate_source = material_protocol_source.split(
        "private bool ActivateResidentViewport()", maxsplit=1
    )[1].split("private void HandleMaterialStateUpdate", maxsplit=1)[0]
    assert activate_source.index(
        "ResidentActivationContract.ShouldDeferActivation"
    ) < activate_source.index("EnsureEmbeddedWindowRevealed")
    assert '"activation_declined"' in activate_source
    assert "Interlocked.Read(ref _residentPackageLoadCount)" in activate_source
    assert "MatchesAcceptedPackageGeneration" in activate_source
    assert '"resident_material_updates_v2"' in all_source
    assert "material_reload_required" not in all_source
    for counter in (
        "source_parse_count",
        "geometry_upload_count",
        "device_reset_count",
        "device_reset_attempt_count",
        "initial_texture_load_count",
        "material_state_update_count",
        "material_state_applied_count",
        "material_state_failed_count",
    ):
        assert counter in material_protocol_source
    assert "full_reload_count" not in material_protocol_source
    assert "process_restart_count" not in material_protocol_source
    assert 'JsonString(root, "material_signature")' in protocol_source
    assert "public bool TryApplyMaterialState(IReadOnlyCollection<int> affectedSubmeshes" in d3d_source


def test_dotnet_mesh_edit_history_and_selection_navigation_are_visible_and_shortcut_driven() -> None:
    program_source = _source("Program.cs")
    input_source = _source("MeshViewport.Input.cs")
    controls_source = _source("ExperimentForm.Controls.cs")
    presentation_source = _source("ExperimentForm.PresentationProtocol.cs")
    protocol_source = _source("ExperimentForm.Protocol.cs")
    history_source = _source("ExperimentForm.History.cs")

    assert 'AddHelpSection(\n            rightStack,\n            "Action History"' in program_source
    assert 'Name = "ResidentActionHistoryList"' in program_source
    assert "ApplyHistoryState(root);" in protocol_source
    assert 'root.TryGetProperty("history_entries"' in history_source
    assert 'state == "undone"' in history_source
    assert 'WriteCommandRequest("undo")' in controls_source
    assert 'WriteCommandRequest("redo")' in controls_source
    assert "Ctrl+Shift+Z" in controls_source
    assert "IsOrbitOverrideGesture(e)" in input_source
    # The orbit override is rebindable, so the gesture reads the binding rather
    # than naming a key. Undo/redo stay hardwired to Ctrl.
    assert "CameraModifierBindings.IsHeld(CameraOrbitModifier, ModifierKeys)" in input_source
    assert 'Name = "ResidentViewportControlsHint"' in presentation_source


def test_dotnet_buttons_share_flat_hover_pressed_and_accent_visual_state() -> None:
    program_source = _source("Program.cs")
    controls_source = _source("ExperimentForm.Controls.cs")
    presentation_source = _source("ExperimentForm.PresentationProtocol.cs")

    # Flat rounded chrome matching the Qt shell. The old raised/sunken bevel
    # drawn with ControlPaint.DrawBorder is what made the editor read as a
    # much older application than the window hosting it.
    assert "private sealed class MeshEditorFlatButton : Button" in controls_source
    assert "var button = new MeshEditorFlatButton" in controls_source
    assert "button.FlatAppearance.BorderSize = 0;" in controls_source
    assert "ControlPaint.DrawBorder" not in controls_source
    assert "ThemeButtonHighlight" not in controls_source
    assert "ThemeButtonShadow" not in controls_source
    assert "GraphicsPath RoundedPath(" in controls_source
    assert "SmoothingMode.AntiAlias" in controls_source
    assert "FlatAppearance.MouseOverBackColor = accent ? ThemeAccentHover : ThemeButtonHover;" in controls_source
    assert "FlatAppearance.MouseDownBackColor = accent ? ThemeAccentPressed : ThemeButtonPressed;" in controls_source

    assert 'var finish = StyledButton(_options.Embedded ? "Finish Edit Mesh" : "Save Edited Package"' in program_source
    assert "var button = StyledButton(text);" in controls_source
    assert "private Button ToolButton(string text, string tool)" in controls_source
    assert "private Button CommandButton(string text, string command)" in controls_source
    assert "private Button CameraButton(string text, string preset)" in controls_source
    assert "private Button GizmoButton(string text, string tool)" in program_source
    assert "var button = StyledButton(text, 26);" in presentation_source
    assert "new Button" not in program_source
    assert "new Button" not in presentation_source

    assert "RefreshToolButtonStates();" in controls_source
    assert "RefreshGizmoButtonStates();" in controls_source
    assert "SetButtonAccent(" in controls_source
    assert "SetButtonAccent(button, active);" in presentation_source
    assert "_gizmoButtons[tool] = button;" in program_source
    assert "_scene.SetGizmoTool(tool);" in program_source
    assert "RefreshGizmoButtonStates();" in program_source


def test_dotnet_screen_edits_match_rendered_mesh_and_use_readable_hit_targets() -> None:
    input_source = _source("MeshViewport.Input.cs")
    picking_source = _source("MeshViewport.SelectionPicking.cs")
    viewport_source = _source("D3D11MaterialViewport.cs")
    overlay_source = _source("D3D11MaterialViewport.Overlay.cs")
    overlay_policy_source = _source("FitRelativeOverlayPolicy.cs")
    shader_source = _source("D3D11MaterialShaders.hlsl")
    program_source = _source("Program.cs")

    assert 'payload["screen_radius"]' in input_source
    assert '["source_submesh_world_view_projections"] = SourceProjectionOverrides(camera)' in input_source
    assert "ActiveSceneModelMatrix(submeshIndex) * camera.WorldViewProjection" in input_source
    assert input_source.count('["source_submesh_indices"] = VisibleEditableSubmeshIndices()') >= 2
    assert "SelectionClickRadiusPixels = 14.0" in picking_source
    assert "ScreenPayload(point, SelectionClickRadiusPixels)" in picking_source

    assert "DefaultVertexMarkerSizePixels = 7.0f" in _source("MeshOverlayColors.cs")
    assert "MinimumVertexMarkerSizePixels = 2.0f" in overlay_policy_source
    assert "FitRelativeOverlayPolicy.ForCamera(_camera, _overlaySettings.Sizing)" in overlay_source
    assert "GSVertexMarker" in shader_source
    assert "_vertexMarkerGeometryShader" in viewport_source
    assert "GSSetShader(_vertexMarkerGeometryShader)" in overlay_source
    assert "GSSetShader(null)" in overlay_source
    assert "AddScreenCross" in overlay_source and "SelectedVertexMarkerRadiusPixels" in overlay_source
    assert "maximum: 1" in program_source
    assert '["smooth_iterations"] = 3' in program_source


def test_resident_material_generation_order_is_independent_of_packet_kind_duplicates() -> None:
    protocol_source = _source("ExperimentForm.Protocol.cs")
    material_source = _source("ExperimentForm.MaterialProtocol.cs")
    handler = material_source.split("private void HandleMaterialStateUpdate", maxsplit=1)[1].split(
        "private bool AcceptMaterialSession", maxsplit=1
    )[0]
    validator = material_source.split("private bool CanApplyMaterialEditRevision", maxsplit=1)[1].split(
        "private void CompleteMaterialStateUpdate", maxsplit=1
    )[0]
    completion = material_source.split("private void CompleteMaterialStateUpdate", maxsplit=1)[1].split(
        "private void HandleMaterialParameterUpdate", maxsplit=1
    )[0]

    assert "CanApplyMaterialEditRevision(update.EditRevision" in handler
    assert 'CanApplyEditRevision(update.EditRevision, "material_state_update"' not in handler
    assert "_appliedPacketKindsForRevision" not in validator
    assert "revision < 0" in validator
    assert 'reason = "invalid_edit_revision"' in validator
    assert "revision < residentRevision" in validator
    assert 'reason = "stale_edit_revision"' in validator
    assert "revision > residentRevision" in validator
    assert 'reason = "future_edit_revision"' in validator
    assert "CanApplyMaterialEditRevision(update.EditRevision" in completion
    assert "MarkEditRevisionApplied(update.EditRevision)" in completion
    assert 'MarkEditRevisionApplied(update.EditRevision, "material_state_update")' not in completion
    assert "_lastObservedSessionRevision" in protocol_source + material_source


def test_dotnet_preview_settings_have_distinct_support_outdoor_and_layer_mask_paths() -> None:
    settings_source = _source("D3D11MaterialViewport.PresentationSettings.cs")
    parser_source = _source("MeshViewport.PresentationSettings.cs")
    view_modes_source = _source("DotNetPreviewViewModes.cs")
    resource_source = _source("D3D11MaterialViewport.Resources.cs")
    shader_source = _source("D3D11MaterialShaders.hlsl")

    assert "!settings.HighQuality || settings.DisableAllSupportMaps" in settings_source
    assert "DotNetPreviewViewModes.UsesGameOutdoorLighting(viewMode)" in parser_source
    assert '"game_outdoor"' in view_modes_source
    assert "settings.GameOutdoorApprox" in settings_source
    assert 'TextureReferenceForSubmesh(submeshIndex, "layer_mask", "mask")' in resource_source
    assert "Texture2D LayerMaskTexture : register(t7);" in shader_source
    assert "LayerMaskTexture.Sample" in shader_source


def test_dotnet_alpha_blend_uses_a_sorted_depth_read_only_material_pass() -> None:
    renderer_source = _source("D3D11MaterialViewport.cs")
    capture_source = _source("D3D11MaterialViewport.Capture.cs")
    geometry_source = _source("D3D11MaterialViewport.Geometry.cs")
    metrics_source = _source("D3D11MaterialViewport.Metrics.cs")
    settings_source = _source("D3D11MaterialViewport.PresentationSettings.cs")

    assert "_transparentBlendState = _device.CreateBlendState(BlendDescription.NonPremultiplied);" in renderer_source
    assert "transparentDepthDescription.DepthWriteMask = DepthWriteMask.Zero;" in renderer_source
    assert "_visibleTransparentBatches.Add(batch);" in renderer_source
    assert "if (_visibleTransparentBatches.Count > 1)" in renderer_source
    assert "SortTransparentBatchesBackToFront();" in renderer_source
    assert "_context.OMSetBlendState(_transparentBlendState ?? _overlayBlendState);" in renderer_source
    assert "_transparentSolidBatchDrawCount++" in renderer_source
    assert capture_source.count("+ _transparentSolidBatchDrawCount") == 2
    assert "public Vector3 Center { get; }" in geometry_source
    assert '"back_to_front_submesh_depth_read_no_write"' in metrics_source
    assert "var materialSubmeshIndex = batch.MaterialSubmeshIndex;" in settings_source
    assert "_materials.AlphaModeForSubmesh(materialSubmeshIndex)" in settings_source


def test_dotnet_resident_scene_owns_reference_grid_modes_and_gizmo() -> None:
    scene_source = _source("NetSceneState.cs")
    protocol_source = _source("ExperimentForm.Protocol.cs")
    overlay_source = _source("D3D11MaterialViewport.Overlay.cs")
    gizmo_render_source = _source("D3D11MaterialViewport.Gizmo.cs")
    output_source = _source("ExperimentForm.Output.cs")
    program_source = _source("Program.cs")
    input_source = _source("MeshViewport.Input.cs")
    gizmo_source = _source("MeshViewport.Gizmo.cs")

    assert 'case "scene_state_update":' in protocol_source
    assert 'ResidentSceneCapability = "resident_scene_state_v1"' in protocol_source
    assert 'AuthoritativeResidentSceneCapability = "authoritative_resident_scene_frame_v2"' in protocol_source
    assert "HandleSceneStateUpdate(root);" in protocol_source
    assert "TryApplyResidentUpdate" in scene_source
    assert "TryApplyResidentInteractionUpdate" in scene_source
    assert "hasAuthoritativeRoles" in protocol_source
    assert 'rejectionReason = "stale_scene_generation"' in scene_source
    assert 'rejectionReason = "stale_source_identity"' in scene_source
    assert "EditableModelMatrix" in scene_source
    assert "ReferenceModelMatrix" in scene_source
    assert "EditableBoundsMinimum" in scene_source
    assert "GroundOrigin" in scene_source
    for mode in ("side_by_side", "overlay", "replacement_only", "original_only"):
        assert f'"{mode}"' in scene_source
    assert "EditableSubmeshCount" in scene_source
    assert "ReferenceSubmeshCount" in scene_source
    assert "DrawSceneGrid();" in overlay_source
    assert "DrawSceneGizmo();" in overlay_source
    assert 'GizmoTool == "rotate"' in gizmo_render_source
    assert 'GizmoTool == "scale"' in gizmo_render_source
    assert "scene.EditableSubmeshCount" in output_source
    assert 'AddSection(leftStack, "Placement"' in program_source
    assert 'GizmoButton("Move", "move")' in program_source
    assert 'GizmoButton("Rotate", "rotate")' in program_source
    assert 'GizmoButton("Scale", "scale")' in program_source
    assert 'EditorEventRequested?.Invoke("placement_transform_request"' in gizmo_source
    assert "TryBeginPlacementGizmoDrag" in input_source
    assert "TryScreenRay" in gizmo_source
    assert "ClosestAxisParameter" in gizmo_source
    assert "TryRayPlane" in gizmo_source
    assert 'new[] { "xy", "xz", "yz" }' in gizmo_source
    assert "ApplyConstrainedRotation" in gizmo_source
    assert "ApplyConstrainedScale" in gizmo_source
    assert "ProvisionalEditableModelMatrix()" in scene_source
    assert "automaticLinear * ManualLinearMatrix(RotationDegrees, Scale)" in scene_source
    assert "ResolvedAlignmentSourceAnchor()" in scene_source
    assert "_acknowledgedPlacement.SourceAnchor" in scene_source
    assert "part * ProvisionalEditableModelMatrix()" in scene_source
    assert "ProvisionalPlacementPivot()" in scene_source
    assert "preserveResidentWorldFrame" in scene_source


def test_dotnet_interaction_rendering_is_uncapped_without_self_scheduling_and_coalesces_placement() -> None:
    program_source = _source("Program.cs")
    runtime_source = _source("ExperimentForm.Runtime.cs")
    renderer_source = _source("MeshViewport.Renderer.cs")
    gizmo_source = _source("MeshViewport.Gizmo.cs")
    d3d_source = _source("D3D11MaterialViewport.cs")
    metrics_source = _source("RuntimeSupport.cs")
    protocol_source = _source("ExperimentForm.Protocol.cs")
    status_source = _source("MeshViewport.Status.cs")

    assert "_viewport.EditorEventRequested += HandleViewportEditorEvent;" in program_source
    assert "HasActiveRenderInput" not in program_source
    assert "_frameDirty = false;" in program_source
    assert "EnsureRenderScheduled();" in program_source
    rendered_frame_source = program_source.split("private void RecordRenderedFrame", maxsplit=1)[1].split(
        "public MeshViewport", maxsplit=1
    )[0]
    assert "EnsureRenderScheduled();" not in rendered_frame_source
    assert "QueueRenderSurfaceInvalidation" in renderer_source
    assert "BeginInvoke((Action)(() =>" in renderer_source
    assert "_d3d11Viewport.Invalidate();" in renderer_source
    assert "_d3d11Viewport.Refresh();" not in renderer_source
    assert "_viewport.ConsumeRenderRequest()" not in runtime_source
    assert "_viewport.EnsureRenderScheduled();" in runtime_source
    assert "PlacementTransformProtocolIntervalMs = 30.0" in runtime_source
    assert "_pendingPlacementTransformPayload = new Dictionary<string, object?>(payload);" in runtime_source
    assert 'string.Equals(phase, "end"' in runtime_source
    assert 'EmitPlacementTransformRequest("update", handle);' in gizmo_source
    assert 'EmitPlacementTransformRequest("end", handle);' in gizmo_source
    assert '["placement_phase"] = phase' in gizmo_source
    assert "SetMaximumFrameLatency(1)" in d3d_source
    assert "Present(PresentSyncInterval, PresentFlags.None)" in d3d_source
    assert '"state_change_latest_wins_d3d11"' in status_source
    assert "AverageFrameIntervalMs" in metrics_source
    assert "FrameIntervalP95Ms" in metrics_source
    assert "FramePacingJitterMs" in metrics_source
    assert '["render_time_ms"]' in protocol_source
    assert '["frame_interval_p95_ms"]' in protocol_source


def test_dotnet_overlay_geometry_reuses_frame_and_retained_vertex_buffers() -> None:
    d3d_source = _source("D3D11MaterialViewport.cs")
    overlay_source = _source("D3D11MaterialViewport.Overlay.cs")
    metrics_source = _source("D3D11MaterialViewport.Metrics.cs")

    assert "BeginOverlayFrame();" in d3d_source
    assert "DisposeOverlayDynamicResources();" in d3d_source
    assert "InitialOverlayVertexCapacity" in overlay_source
    assert "ResourceUsage.Dynamic" in overlay_source
    assert "CpuAccessFlags.Write" in overlay_source
    assert "MapMode.WriteDiscard" in overlay_source
    assert "MapMode.WriteNoOverwrite" in overlay_source
    flush_source = overlay_source.split("private unsafe void FlushOverlayPrimitives()", maxsplit=1)[1]
    queue_source = overlay_source.split("private unsafe void DrawOverlayPrimitive(", maxsplit=1)[1].split(
        "private void DrawRetainedOverlayPrimitive(", maxsplit=1
    )[0]
    retained_source = overlay_source.split("private unsafe void UpdateRetainedOverlayBuffer(", maxsplit=1)[1].split(
        "private void DrawSelectedEdgesOverlay()", maxsplit=1
    )[0]
    assert "_overlayBatchFlushCount++;" in flush_source
    assert "_overlayBatchedDrawCount++;" in flush_source
    assert "if (command.DrawSceneVertices)" in flush_source
    assert "DrawD3D11VertexOverlay();" in flush_source
    assert "_context.Map(" not in queue_source
    assert "MapMode.WriteNoOverwrite" in retained_source
    assert "if (vertices.Count == 0)" in retained_source
    assert "buffer.Dispose();" in retained_source
    assert "buffer = null;" in retained_source
    assert "capacity = 0;" in retained_source
    selected_faces_source = overlay_source.split("private void DrawSelectedFacesOverlay()", maxsplit=1)[1].split(
        "private void DrawFaceSelectionOverlay(", maxsplit=1
    )[0]
    selected_vertices_source = overlay_source.split("private void DrawSelectedVerticesOverlay()", maxsplit=1)[1].split(
        "private static Dictionary<int, HashSet<int>> VertexOverlaySelections", maxsplit=1
    )[0]
    assert "DisposeFaceOverlayCache(_provisionalFaceOverlayCache);" in selected_faces_source
    assert "DisposeVertexOverlayCache(_provisionalVertexOverlayCache);" in selected_vertices_source
    assert "VertexBuffer: vertexBuffer" in overlay_source
    assert "using var vertexBuffer = _device.CreateBuffer" not in overlay_source
    assert "_context.Draw((uint)command.VertexCount, (uint)command.StartVertex);" in overlay_source
    assert '["overlay_vertex_buffer_creates"]' in metrics_source
    assert '["overlay_vertex_buffer_reused"]' in metrics_source
    assert '["retained_wire_overlay_buffer_creates"]' in metrics_source


def test_dotnet_d3d11_interaction_skips_hidden_gdi_rendering_and_uses_flip_model() -> None:
    d3d_source = _source("D3D11MaterialViewport.cs")
    painting_source = _source("MeshViewport.Painting.cs")
    input_source = _source("MeshViewport.Input.cs")
    gizmo_source = _source("MeshViewport.Gizmo.cs")
    status_source = _source("MeshViewport.Status.cs")

    before_gdi_clear = painting_source.split("e.Graphics.Clear(BackColor);", maxsplit=1)[0]
    assert "if (_d3d11Viewport is not null)" in before_gdi_clear
    assert "_gdiFallbackFrameCount++;" in painting_source
    assert 'SwapEffect = SwapEffect.FlipDiscard' in d3d_source
    assert 'SwapEffect = SwapEffect.Discard' not in d3d_source
    assert "public string PresentationModel => _swapChain is null" in d3d_source
    assert '? "unavailable"' in d3d_source
    assert ': "flip_discard";' in d3d_source
    assert "if (!_rotating" in input_source
    mouse_move_source = input_source.split("protected override void OnMouseMove", maxsplit=1)[1].split(
        "protected override void OnMouseEnter", maxsplit=1
    )[0]
    assert mouse_move_source.count("UpdateGpuViewport();") == 1
    assert "Invalidate();" not in mouse_move_source
    hit_test_source = gizmo_source.split("private string HitTestGizmo", maxsplit=1)[1].split(
        "private void ApplyMoveHandleDrag", maxsplit=1
    )[0]
    assert hit_test_source.count("CurrentCamera()") == 1
    assert "GizmoProjectedPoint(pivot, camera)" in hit_test_source
    assert '["presentation_model"]' in status_source
    assert '["gdi_fallback_frame_count"]' in status_source


def test_resident_role_views_share_resources_and_keep_normal_cameras_independent() -> None:
    program_source = _source("Program.cs")
    presentation_source = _source("MeshViewport.Presentation.cs")
    split_view_source = _source("MeshViewport.SplitView.cs")
    presentation_protocol = _source("ExperimentForm.PresentationProtocol.cs")
    protocol_source = _source("ExperimentForm.Protocol.cs")
    renderer_source = _source("MeshViewport.Renderer.cs")
    pane_renderer_source = _source("D3D11MaterialViewport.Panes.cs")
    d3d_renderer_source = _source("D3D11MaterialViewport.cs")
    scene_source = _source("NetSceneState.cs")
    picking_source = _source("MeshViewport.SelectionPicking.cs")
    occlusion_source = _source("MeshViewport.OcclusionPicking.cs")
    diagnostics_source = _source("MeshViewport.HostDiagnostics.cs")
    status_source = _source("MeshViewport.Status.cs")

    assert program_source.count("new MeshViewport(") == 1
    assert 'NewPresentationContext("editable", "editable")' in presentation_source
    assert 'NewPresentationContext("reference", "reference")' in presentation_source
    assert '["normal_cameras_independent"] = true' in presentation_source
    assert '_comparisonCameraLinked = overlay' in presentation_source
    assert 'LoadPresentationContext("editable")' in presentation_source
    assert 'LoadPresentationContext("reference")' in presentation_source
    assert '["shared_scene_resources"]' in presentation_source
    assert 'RuntimeHelpers.GetHashCode(_document)' in presentation_source
    assert 'RuntimeHelpers.GetHashCode(_materials)' in presentation_source
    assert 'RuntimeHelpers.GetHashCode(_textureSet)' in presentation_source
    assert '"OriginalResidentViewButton"' in presentation_protocol
    assert '"EditableResidentViewButton"' in presentation_protocol
    assert '"Original (focus)"' in presentation_protocol
    assert '"Imported / Modify (focus)"' in presentation_protocol
    assert "Both side-by-side panes remain visible" in presentation_protocol
    assert "_viewport.FocusPresentationPane(view);" in presentation_protocol
    assert "_viewport.ActivatePresentationView(view);" not in presentation_protocol
    assert 'Name = "ResidentRoleViewHeaderDivider"' in presentation_protocol
    assert "notifyHost: true" in presentation_protocol
    assert "editableSubmeshCount > 0" in split_view_source
    assert "referenceSubmeshCount > 0" in split_view_source
    assert 'string.Equals(comparisonMode, "side_by_side", StringComparison.OrdinalIgnoreCase)' in split_view_source
    assert "SinglePaneRoleForMode(_scene.ComparisonMode)" in split_view_source
    assert "private readonly D3D11RenderPane[] _currentRenderPanes = new D3D11RenderPane[2];" in split_view_source
    assert "PopulateCurrentRenderPanes()" in split_view_source
    assert 'bounds.Reference, reference, "reference", interactionAllowed: false' in split_view_source
    assert 'bounds.Editable, editable, "editable", interactionAllowed: true' in split_view_source
    assert "UpdateRenderPanes(_currentRenderPanes, PopulateCurrentRenderPanes())" in renderer_source
    assert "private readonly D3D11RenderPane[] _renderPanes = new D3D11RenderPane[2];" in pane_renderer_source
    assert "UpdateRenderPanes(D3D11RenderPane[] panes, int count)" in pane_renderer_source
    assert "var panes = PanesForFrame(replacementOnly, out var paneCount);" in d3d_renderer_source
    assert "for (var paneIndex = 0; paneIndex < paneCount; paneIndex++)" in d3d_renderer_source
    assert "ActivePaneIncludes(batch.SubmeshIndex)" in d3d_renderer_source
    # An explicit hide holds whatever the pane is showing. The role says which
    # side of a comparison is on screen; it is not a statement about whether a
    # part the caller hid should come back.
    assert "_scene.IsHiddenByPresentation(submeshIndex)" in pane_renderer_source
    assert "HasRenderedBothRolePanes" in pane_renderer_source
    assert "ActivePaneIncludesForPicking(submeshIndex)" in picking_source
    assert "ActivePaneIncludesForPicking(submeshIndex)" in occlusion_source
    assert "_scene.IsPresentationVisible(submeshIndex)" in split_view_source
    assert "RoleViewModelMatrix" in scene_source
    assert "EditablePresentationMatrix(includeSideBySideOffset)" in scene_source
    assert "RoleViewGizmoPivot" in scene_source
    assert "context.CameraMinimum" in split_view_source
    assert "context.CameraMaximum" in split_view_source
    assert "return SceneBoundsForContext(contextId);" in split_view_source
    assert "ReframePresentationContext(_activeCameraContextId);" in _source("MeshViewport.Topology.cs")
    assert "commandGeneration <= context.LastCameraCommandGeneration" in presentation_source
    assert 'role is "original" or "reference" or "original_only"' in presentation_source
    assert '["screen_x"] = origin.X + editable.X' in diagnostics_source
    assert '["client_x"] = editable.X' in diagnostics_source
    assert '["full_surface"]' in diagnostics_source
    assert '["viewports"]' in diagnostics_source
    assert "HasRenderedRequiredPresentation" in _source("ExperimentForm.Runtime.cs")
    assert '"resident_simultaneous_role_panes_v2"' in status_source
    assert '"resizable_role_panes_v1"' in status_source
    assert 'case "presentation_state_update":' in protocol_source
    assert 'WriteProtocolEvent("presentation_state_update_ack"' in presentation_protocol
    assert 'processGeneration != _residentProcessGeneration' in presentation_protocol
    assert 'resident_presentation_state_v1' in presentation_protocol
    assert '_presentationHighlightedSources' in renderer_source


def test_mesh_edit_forces_the_resident_view_to_editable_replacement_only() -> None:
    scene_source = _source("NetSceneState.cs")
    presentation_source = _source("MeshViewport.Presentation.cs")
    controls_source = _source("ExperimentForm.Controls.cs")

    assert '"mesh_edit" => "replacement_only"' in scene_source
    assert "EffectiveComparisonMode(value, InteractionMode)" in scene_source
    assert 'normalized = "editable";' in presentation_source
    assert '_viewport.ActivatePresentationView("editable")' in controls_source
    assert "button.Enabled = !meshEdit" in _source("ExperimentForm.PresentationProtocol.cs")


def test_mesh_edit_opening_default_cannot_replace_an_existing_display_choice() -> None:
    controls_source = _source("ExperimentForm.Controls.cs")
    entry = controls_source.split("if (enteringMeshEdit)", maxsplit=1)[1].split(
        "_meshEditDisplayInitialized = true;",
        maxsplit=1,
    )[0]

    assert "!_viewport.HostDisplayModeAuthoritative" in entry
    assert '_viewport.DisplayMode,' in entry
    assert '"untextured_wire"' in entry
    assert entry.index('"untextured_wire"') < entry.index(
        'SyncPreviewModeSelection("wire_vertices")'
    )


def test_dotnet_input_precedence_depth_passes_and_mode_controls_are_explicit() -> None:
    input_source = _source("MeshViewport.Input.cs")
    overlay_source = _source("D3D11MaterialViewport.Overlay.cs")
    renderer_source = _source("D3D11MaterialViewport.cs")
    program_source = _source("Program.cs")
    controls_source = _source("ExperimentForm.Controls.cs")
    host_commands = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_commands.py").read_text(
        encoding="utf-8"
    )

    placement = input_source.split(
        'if (e.Button == MouseButtons.Left\n            && !string.Equals(_scene.InteractionMode, "mesh_edit"',
        1,
    )[1].split(
        'if (e.Button == MouseButtons.Left && !string.Equals(ActiveTool, "orbit"',
        1,
    )[0]
    assert placement.index("TryBeginPlacementGizmoDrag") < placement.index("PartPickEnabled")
    assert placement.index("PartPickEnabled") < placement.index("_rotating = true")
    assert "_placementDragActive = true;" not in placement

    assert "_overlayDepthState = _device.CreateDepthStencilState(overlayDepthDescription);" in renderer_source
    assert "overlayDepthDescription.DepthEnable = false;" not in renderer_source
    assert "overlayNoDepthDescription.DepthEnable = false;" in renderer_source
    assert "_gizmoDepthState = _device.CreateDepthStencilState" in renderer_source
    assert overlay_source.index("DrawSceneGrid();") < overlay_source.index(
        "_context.OMSetDepthStencilState(_overlayNoDepthState);"
    )
    assert overlay_source.index(
        "_context.OMSetDepthStencilState(_overlayNoDepthState);"
    ) < overlay_source.index("DrawSelectionRectangleOverlay();")
    assert overlay_source.index(
        "_context.OMSetDepthStencilState(_gizmoDepthState);"
    ) < overlay_source.index("DrawSceneGizmo();")

    assert "ApplyInteractionModeControls();" in program_source
    assert "section.Visible = meshEdit;" in controls_source
    assert "section.Visible = !meshEdit;" in controls_source
    assert "var leavingMeshEdit = !meshEdit && _meshEditInteractionActive;" in controls_source
    assert "var mode = _placementPreviewMode;" in controls_source
    assert 'string.Equals(normalized, "textured_wire"' in controls_source
    assert "_viewport.TrySetSynchronizedDisplayMode(mode, out var error)" in controls_source
    assert "SynchronizePresentationDisplaySettings();" in _source("MeshViewport.PresentationSettings.cs")
    assert 'phase == "begin" and isinstance(payload.get("local_selection"), Mapping)' not in host_commands
    assert "includeLocalSelection" not in input_source


def test_dotnet_provisional_picking_and_mutation_responses_are_authority_safe() -> None:
    picking = _source("MeshViewport.SelectionPicking.cs")
    occlusion = _source("MeshViewport.OcclusionPicking.cs")
    selection_authority = _source("MeshViewport.SelectionAuthority.cs")
    mutation_authority = _source("ExperimentForm.MutationAuthority.cs")
    protocol = _source("ExperimentForm.Protocol.cs")
    output = _source("ExperimentForm.Output.cs")
    scene = _source("NetSceneState.cs")
    gizmo = _source("MeshViewport.Gizmo.cs")

    assert "TryNearestVisibleSurface" in occlusion
    assert "RayIntersectsTriangle" in occlusion
    assert "IsWorldPointOccluded" in occlusion
    assert "nearestDistance + depthTolerance < candidateDistance" in occlusion
    assert "ActivePaneIncludesForPicking(submeshIndex)" in occlusion
    assert "ShowXRay" in occlusion
    # Edge hover picks resolve occlusion once per cursor position and compare
    # every candidate against that scan, instead of re-walking every face per
    # candidate through IsWorldPointOccluded.
    assert "WorldPointBehindNearestSurface" in occlusion
    assert "WorldPointBehindNearestSurface(" in picking
    assert "!IsWorldPointOccluded(" in picking
    assert "return TryNearestVisibleSurface(point" in picking

    assert "SelectionAuthoritySnapshot" in selection_authority
    assert "BeginProvisionalSelection" in selection_authority
    assert "RejectProvisionalSelection" in selection_authority
    assert "RestoreAcknowledgedSelection" in selection_authority
    assert "AcknowledgedSelectionRevision" in selection_authority

    for field in ("session_id", "request_id", "base_revision", "process_generation"):
        assert f'"{field}"' in mutation_authority
    assert "TryMatchPendingMutation" in mutation_authority
    assert "revision < candidate.BaseRevision" in mutation_authority
    assert "revision < _viewport.AcknowledgedSelectionRevision" in mutation_authority
    assert "Ignored stale or uncorrelated command result" in mutation_authority
    assert "Ignored stale or uncorrelated selection update" in protocol
    assert "HandleCommandResult(root);" in protocol
    assert "TryPrepareCorrelatedSelectionUpdate" in protocol
    assert "RegisterOutgoingMutation(eventName, message);" in output

    assert "BeginProvisionalPlacement" in gizmo
    assert "TrackProvisionalPlacementRequest" in mutation_authority
    assert "RejectProvisionalPlacement" in mutation_authority
    assert "AcceptAuthoritativePlacementFrame" in scene
    assert "if (!_scene.AcceptAuthoritativePlacementFrame())" in mutation_authority
    assert "ForceAcceptAuthoritativePlacementFrame" in mutation_authority
    assert "CompleteAuthoritativeSceneState();" in protocol

    # A drag owns its provisional snapshot until it ends. Completing it from an
    # authoritative frame that lands mid-drag re-bases the next pointer sample
    # on the frame that just arrived, and the mesh stops following the gizmo.
    assert "public bool PlacementDragActive => _placementDragActive;" in gizmo
    accept_guard = mutation_authority.index("if (_viewport.PlacementDragActive)")
    assert accept_guard < mutation_authority.index(
        "if (!_scene.AcceptAuthoritativePlacementFrame())"
    )
    # A scene frame arrives per drag sample. Re-running the interaction-mode
    # controls unconditionally restores the whole classic layout each time.
    assert "ApplyInteractionModeControls();" not in protocol
    assert "ReassertInteractionModeControls();" in protocol

    # The re-assert is a transition, not a per-frame refresh, and the guard has
    # to say so in both directions. Covering only placement-on-both-sides meant
    # every accepted frame during mesh edit ran the whole interaction-mode pass
    # -- section visibility, both splitter collapses, a layout on each split and
    # the presentation view -- which is what made clicking a tool or a part
    # flicker the panels and flash a different display mode on the way through.
    package_protocol = _source("ExperimentForm.PackageProtocol.cs")
    reassert = package_protocol.split("private void ReassertInteractionModeControls()", 1)[1]
    reassert = reassert.split("private void PublishResidentPackageLoadFailure", 1)[0]
    assert "if (meshEdit == _meshEditInteractionActive)" in reassert
    assert "if (!meshEdit && meshEdit == _meshEditInteractionActive)" not in reassert


def test_dotnet_texture_decode_cache_singleflights_and_prunes_inactive_entries() -> None:
    texture_source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(DOTNET_EDITOR.glob("NetTextureSet*.cs"))
    )

    assert "_decodeFlights" in texture_source
    assert "Task.WhenAll(tasks)" in texture_source
    assert "_decodeSingleflightJoinCount++" in texture_source
    assert "public void PruneToResources(IEnumerable<NetMaterialResource> resources)" in texture_source
    assert "keepKeys.UnionWith(_decodeFlights.Keys)" in texture_source
    assert "_lastGoodResourceKeys.TryGetValue(resourceId" in texture_source
    assert "MaxTextureLoadFailures = 256" in texture_source
    assert "_textureLoadFailures.RemoveRange" in texture_source

    material_source = _source("ExperimentForm.MaterialProtocol.cs")
    completion = material_source.split("private void CompleteMaterialStateUpdate", maxsplit=1)[1].split(
        "private void HandleMaterialParameterUpdate", maxsplit=1
    )[0]
    bind = completion.index("_viewport.TryApplyMaterialState")
    rollback = completion.index("_materials.ReplaceState(previous)", bind)
    prune = completion.index("_textureSet.PruneToResources(_materials.TextureLoadResources())")
    applied = completion.index("_lastAppliedMaterialGeneration = update.Generation")
    assert bind < rollback < prune < applied
    assert '["texture_decode_singleflight_join_count"] = _textureSet.DecodeSingleflightJoinCount' in material_source
    assert '["decoded_bitmap_prune_count"] = _textureSet.DecodedBitmapPruneCount' in material_source

    renderer_status = _source("MeshViewport.Status.cs")
    assert '["texture_decode_singleflight_joins"] = _textureSet.DecodeSingleflightJoinCount' in renderer_status
    assert '["decoded_bitmap_prunes"] = _textureSet.DecodedBitmapPruneCount' in renderer_status


def test_dotnet_lifecycle_counts_use_parser_and_renderer_owners() -> None:
    entry_source = _source("ProgramEntry.cs")
    program_source = _source("Program.cs")
    material_source = _source("ExperimentForm.MaterialProtocol.cs")
    d3d_source = _source("D3D11MaterialViewport.cs")
    renderer_resources = _source("MeshViewport.RendererResources.cs")
    host_source = "\n".join(
        (ROOT / "cdmw" / "ui" / "mesh_editor" / name).read_text(encoding="utf-8")
        for name in ("tab_shell.py", "tab_shell_runtime.py")
    )

    assert entry_source.index("ObjDocument.Load(options.MeshPath)") < entry_source.index("sourceParseCount++")
    assert "new ExperimentForm(options, document, sourceParseCount)" in entry_source
    assert "_sourceParseCount = Math.Max(0, sourceParseCount)" in program_source
    assert "SourceParseCount = 1" not in material_source
    assert '["geometry_upload_count"] = _viewport.GeometryUploadCount' in material_source
    assert "public long GeometryUploadCount => _fullGeometryRebuildCount" in d3d_source
    assert "_deviceResetAttemptCount++" in d3d_source
    assert "_deviceResetCount++" in d3d_source
    assert "RetainD3D11LifecycleCounts(viewport)" in _source("MeshViewport.Renderer.cs")
    assert "RetainD3D11LifecycleCounts(failed)" in _source("MeshViewport.Renderer.cs")
    assert "_retiredDeviceResetAttemptCount + (_d3d11Viewport?.DeviceResetAttemptCount ?? 0)" in renderer_resources
    assert "_retiredDeviceResetCount + (_d3d11Viewport?.DeviceResetCount ?? 0)" in renderer_resources
    assert '"process_restart_count": 0' in host_source
    assert '"full_reload_count": 0' in host_source


def test_dotnet_tool_panel_has_no_disabled_gizmo_placeholder() -> None:
    program_source = _source("Program.cs")

    assert 'DisabledButton("Gizmo"' not in program_source


def test_embedded_dotnet_exposes_its_tool_panels_in_mesh_edit_mode() -> None:
    program_source = _source("Program.cs")
    controls_source = _source("ExperimentForm.Controls.cs")
    layout_source = _source("ExperimentForm.EditMeshLayouts.cs")
    protocol_source = _source("ExperimentForm.Protocol.cs")
    morph_source = _source("ExperimentForm.MorphRefit.cs")
    material_source = _source("ExperimentForm.MaterialProtocol.cs")
    input_source = _source("MeshViewport.Input.cs")
    split_view_source = _source("MeshViewport.SplitView.cs")
    topology_source = _source("MeshViewport.Topology.cs")

    assert '"DotNetMeshEditorLeftViewportSplit"' in program_source
    assert '"DotNetMeshEditorViewportRightSplit"' in program_source
    assert "_leftToolPanel.Margin = new Padding(0);" in program_source
    assert "_rightToolPanel.Margin = new Padding(0);" in program_source
    assert "_viewport.Margin = new Padding(0);" in program_source
    assert "_leftToolSplit.Panel1.Controls.Add(_leftToolPanel);" in program_source
    assert "_presentationViewportRegion = BuildPresentationViewportRegion();" in program_source
    assert "_viewportWorkspaceSplit.Panel1.Controls.Add(_presentationViewportRegion);" in layout_source
    assert "_leftToolModeHost.Controls.Add(_leftToolPanel);" in layout_source
    assert "_rightToolModeHost.Controls.Add(_rightToolPanel);" in layout_source
    assert "InitializeEditMeshLayoutHost(_leftToolSplit);" in program_source
    assert "ApplyEmbeddedToolPanelVisibility(meshEdit: false);" in controls_source
    assert "ApplyEmbeddedToolPanelVisibility(meshEdit: true);" not in controls_source
    assert "ApplyToolRailEditMeshLayout();" in controls_source
    assert "_leftToolSplit.Panel1Collapsed = true;" in controls_source
    assert "_rightToolSplit.Panel2Collapsed = true;" in controls_source
    assert "_leftToolSplit.Panel1Collapsed = false;" in controls_source
    assert "_rightToolSplit.Panel2Collapsed = false;" in controls_source
    assert "if (!options.Embedded)" not in program_source
    assert '"DotNetMeshEditorLeftToolScroll"' in program_source
    assert '"DotNetMeshEditorRightToolScroll"' in program_source
    assert "ApplyNativeControlTheme(control);" in program_source
    assert "ApplyDarkScrollbars(_submeshList);" in program_source
    # The Parts group builds through its own owner, which also carries the
    # selected-part detail; the whole-part commands stay exactly as they were.
    parts_source = _source("ExperimentForm.PartsSection.cs")
    assert 'CommandButton("Hide", "toggle_visibility")' in parts_source
    assert 'CommandButton("Duplicate", "duplicate")' in program_source
    assert 'CommandButton("Delete", "delete")' in program_source
    assert '"Finish Edit Mesh"' in program_source
    assert "RequestFinishEditMesh();" in program_source
    assert 'WriteProtocolEvent("save_request")' in morph_source
    assert 'AddSection(stack, "Clipboard"' not in program_source
    assert 'ConfigureCombo(_selectionTarget, new object[] { "Vertices", "Wires", "Faces" }, selectedIndex: 0);' in program_source
    assert '_selectionTarget.SelectedItem = "Part";' not in program_source
    assert "RefreshSubmeshList();" in protocol_source
    assert material_source.count("RefreshSubmeshList();") >= 2
    assert "ApplyWheelZoomToPane(paneId, e.Delta)" in input_source
    assert "CameraZoomPolicy.ApplyWheelDelta(" in split_view_source
    assert "Math.Clamp(_zoom, 1.0f, 500000.0f)" not in input_source
    assert topology_source.count("var viewCenter = _center;") == 2
    assert topology_source.count("_center = viewCenter;") == 2
    assert "IsSubmeshVisibleForViewportSelection" in _source("MeshViewport.SelectionPicking.cs")
    assert "_materials.ParametersForSubmesh(pair.Key).Visible is false" in _source("D3D11MaterialViewport.Overlay.cs")

    host_protocol = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_payloads.py").read_text(encoding="utf-8")
    sender = host_protocol.split("    def _send_dotnet_native_update(", maxsplit=1)[1].split(
        "    def _dotnet_screen_selection_payload", maxsplit=1
    )[0]
    assert sender.index('"event": "preview_triangle_update"') < sender.index('"event": "selection_update"')
    assert sender.index('"event": "selection_update"') < sender.index("standalone_dotnet_update_queue.enqueue")


def test_dotnet_editor_starts_and_can_return_to_no_part_selection() -> None:
    program_source = _source("Program.cs")
    material_viewport_source = _source("D3D11MaterialViewport.cs")
    selection_source = _source("MeshViewport.SelectionActions.cs")
    selection_picking_source = _source("MeshViewport.SelectionPicking.cs")
    selection_commands_source = _source("MeshViewport.SelectionCommands.cs")
    topology_source = _source("MeshViewport.Topology.cs")
    overlay_source = _source("D3D11MaterialViewport.Overlay.cs")

    assert "public int SelectedSubmeshIndex => _selectedSources.Count > 0 ? _selectedSources.Min() : -1;" in program_source
    assert "private int _overlaySelectedSubmeshIndex = -1;" in material_viewport_source
    assert "_submeshList.SelectedIndex = 0;" not in program_source
    assert "_submeshList.SelectedIndex = -1;" in program_source
    assert '["selected_part_index"] = _viewport.SelectedSubmeshIndex' in program_source
    assert '["parts_list_selected_index"] = _submeshList.SelectedIndex' in program_source
    assert '["parts_list_selected_indices"] = _submeshList.SelectedIndices.Cast<int>().ToArray()' in program_source
    assert '["local_selection"] = _viewport.SelectionSnapshotPayload()' in program_source
    assert "_submeshList.IndexFromPoint(eventArgs.Location) == ListBox.NoMatches" in program_source
    assert "_viewport.SelectPartsFromList(_submeshList.SelectedIndices.Cast<int>());" in program_source
    # MultiSimple: a plain click toggles the part under the cursor and keeps
    # the rest of the selection. MultiExtended replaced the selection on every
    # unmodified click, so a selected part could not be deselected by clicking
    # it again -- only the None button could.
    assert "_submeshList.SelectionMode = SelectionMode.MultiSimple;" in program_source
    assert "_submeshList.SelectionMode = SelectionMode.MultiExtended;" not in program_source
    # A Parts-list click replaces only the part channel: the request carries
    # the current vertex/face/edge snapshot, so accepting it cannot wipe the
    # geometry selection the reader had in the viewport.
    parts_request = selection_source.split(
        "public void SelectPartsFromList(IEnumerable<int> submeshIndices)", maxsplit=1
    )[1].split("private void SyncSelectedPartFocus()", maxsplit=1)[0]
    assert "var selection = SelectionSnapshotPayload();" in parts_request
    assert 'selection["source_indices"] = requestedSources;' in parts_request
    assert '["vertices_by_submesh"] = new Dictionary<string, int[]>()' not in parts_request
    assert "public int[] SelectedSubmeshIndices" in program_source
    assert "public void SelectPartFromList(int submeshIndex)" in selection_source
    assert "public void SelectPartsFromList(IEnumerable<int> submeshIndices)" in selection_source
    assert "SelectedSubmeshIndex =" not in selection_source
    assert "SelectedSubmeshIndex =" not in selection_picking_source
    assert "SubmeshSelectedRequested?.Invoke(SelectedSubmeshIndex);" in selection_source
    assert selection_source.count("SubmeshSelectedRequested?.Invoke(") == 1
    assert "SubmeshSelectedRequested?.Invoke(" not in selection_picking_source
    committed_selection = selection_picking_source.split("private void FinishEdgeDrag(Point point)", 1)[1].split(
        "private Rectangle EdgeDragRectangle", 1
    )[0]
    assert 'EmitSelectionRequest(payload, "end");' in committed_selection
    assert "ApplyPartSelectionOperation" not in committed_selection
    assert "ApplySelectionMapOperation" not in committed_selection
    assert "ApplyEdgeSelectionOperation" not in committed_selection
    assert "SelectedSubmeshIndex = submeshIndex;" not in selection_source
    assert "new HashSet<int> { SelectedSubmeshIndex }" not in selection_commands_source
    assert "SyncSelectedPartFocus();" in topology_source
    assert "DrawSelectedSourcesOverlay();" in overlay_source
    assert "OverlayColor(_overlaySettings.Colors.Selection, _overlayShowXRay ? 64 : 42)" in overlay_source


def test_dotnet_embedded_ready_requires_a_verified_native_parent() -> None:
    host_source = _source("NativeWindowHost.cs")
    program_source = _source("Program.cs")
    runtime_source = _source("ExperimentForm.Runtime.cs")
    protocol_source = _source("ExperimentForm.Protocol.cs")
    material_protocol_source = _source("ExperimentForm.MaterialProtocol.cs")

    constructor_source, shown_source = program_source.split("protected override void OnShown", maxsplit=1)
    assert "GetParent(child) != parent" in host_source
    assert "SetWindowPos(form.Handle, HwndTop" in host_source
    embedded_resize = host_source.split("public static void ResizeToParent", maxsplit=1)[1].split(
        "public static void ResizeHidden", maxsplit=1
    )[0]
    assert "SwpNoZOrder" not in embedded_resize
    assert "SwpNoMove | SwpNoZOrder | SwpNoActivate" in host_source
    assert host_source.index("SetWindowLongPtrSafe(child") < host_source.index("SetParent(child, parent)")
    # An embedded window is created as a child of the host, so the reparent is
    # conditional on a first GetParent check. What matters is that the child
    # style is applied before the SetParent, and that the SetParent is followed
    # by its own verification before Embed reports success -- not that the file
    # mentions GetParent only once.
    reparent_source = host_source.split("SetWindowLongPtrSafe(child", maxsplit=1)[1]
    assert reparent_source.index("SetParent(child, parent)") < reparent_source.index("GetParent(child) != parent")
    assert reparent_source.index("GetParent(child) != parent") < reparent_source.index("return false;")
    assert 'WriteProtocolEvent("ready"' not in constructor_source
    assert constructor_source.index("_ = Handle;") < constructor_source.index("StartProtocolReader();")
    assert constructor_source.index("StartProtocolReader();") < constructor_source.index("_viewport = new MeshViewport")
    assert "StartProtocolReader();" not in shown_source
    assert 'if (_options.Embedded && !TryEmbedOrFail("startup"))' in shown_source
    assert shown_source.index('TryEmbedOrFail("startup")') < shown_source.index('WriteProtocolEvent("ready"')
    assert shown_source.index("StartTextureLoad();") < shown_source.index('WriteProtocolEvent("ready"')
    texture_load_source = constructor_source.split("private void StartTextureLoad", maxsplit=1)[1]
    successful_texture_load = texture_load_source.split("var allSubmeshes", maxsplit=1)[1]
    assert successful_texture_load.index("TryApplyMaterialState") < successful_texture_load.index('QueueReadyAfterFirstFrame("ready"')
    assert "_viewport.HasRenderedRequiredPresentation" in runtime_source
    assert runtime_source.index("_viewport.HasRenderedRequiredPresentation") < runtime_source.index(
        "PublishReady(_pendingTextureState, _pendingTextureError);"
    )
    assert 'PublishReady("ready", string.Empty)' not in successful_texture_load
    assert 'WriteStatus(_options, "error"' in shown_source
    assert '["code"] = "embedded_host_unavailable"' in shown_source
    assert "Close();" in shown_source
    assert 'if (_options.Embedded && !TryEmbedOrFail("reactivation"))' in material_protocol_source
    reactivation_source = material_protocol_source.split('TryEmbedOrFail("reactivation")', maxsplit=1)[1]
    assert reactivation_source.index("return false;") < reactivation_source.index('WriteProtocolEvent("activated"')


def test_codex_mesh_checks_use_real_game_pac_and_keep_unit_runs_non_visual() -> None:
    source = (ROOT / "scripts" / "codex_check.ps1").read_text(encoding="utf-8")
    # The proof drives the editor from real_dotnet and assembles its result in
    # real_dotnet_report, so the recorded input backend lives in the second half.
    real_proof_source = "\n".join(
        (ROOT / "tools" / "mesh_harness" / name).read_text(encoding="utf-8")
        for name in ("real_dotnet.py", "real_dotnet_report.py")
    )
    real_input_source = (ROOT / "tools" / "mesh_harness" / "real_dotnet_input.py").read_text(encoding="utf-8")

    assert "real-archive-mesh-editor-dotnet-edit-smoke" in source
    assert "Running real in-game PAC .NET Mesh Editor proof" in source
    assert "test_mesh_editor\\cd_phm_00_nude_10_0001.pac" not in source
    mesh_unit_start = source.index('"mesh-unit" = @(')
    mesh_unit_end = source.index("    )", mesh_unit_start)
    assert "test_mesh_editor_dev_harness.py" not in source[mesh_unit_start:mesh_unit_end]
    assert "--ignore=tests/test_mesh_editor_dev_harness.py" not in source
    assert '"mouse_input_backend": "win32_physical_cursor"' in real_proof_source
    assert "_send_left_button_input(down=True)" in real_input_source
    assert "if not state.input_window_activated:" in real_input_source
    pytest_config = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert 'visual: opens a window' in pytest_config
    assert 'real_game: reads locally installed game assets' in pytest_config
    assert 'timing: asserts wall-clock responsiveness' in pytest_config
    # Three opt-in markers, all excluded by default for the same reason: they
    # need something the default run cannot promise. A window, the installed
    # game, or a scheduler the caller controls.
    assert '-m "not visual and not real_game and not timing"' in pytest_config


def test_real_dotnet_harness_has_dedicated_resident_side_by_side_zoom_proof() -> None:
    source = (ROOT / "tools" / "mesh_harness" / "real_dotnet.py").read_text(encoding="utf-8")
    input_source = "\n".join(
        (ROOT / "tools" / "mesh_harness" / name).read_text(encoding="utf-8")
        for name in ("real_dotnet_input.py", "real_dotnet_zoom_input.py")
    )
    # _start_embedded_editor moved to real_dotnet_session; its call site and the
    # zoom smoke entry point are still in real_dotnet.py.
    session_source = (ROOT / "tools" / "mesh_harness" / "real_dotnet_session.py").read_text(
        encoding="utf-8"
    )

    assert "def run_real_archive_mesh_editor_dotnet_zoom_smoke(" in source
    assert "_start_embedded_editor(state, side_by_side_camera=True)" in source
    assert 'lambda: "side_by_side" if side_by_side_camera else "replacement_only"' in session_source
    assert 'lambda: "placement" if side_by_side_camera else "mesh_edit"' in session_source
    assert "exercise_side_by_side_wheel_zoom(" in source
    assert "_send_mouse_wheel_input(-1)" in input_source
    assert "_send_mouse_wheel_input(1)" in input_source
    assert '"non_target_camera_unchanged"' in input_source
    assert '"inverse_camera_restored_exactly"' in input_source


def test_overlay_visibility_reaches_every_presentation_context() -> None:
    """Both panes draw from their own context, so both must be written.

    `SaveActivePresentationContext` only stamps the active context, so leaving
    grid/gizmo out of the fan-out let the two panes drift: one could keep
    drawing a grid the host had turned off, or lose one it had turned on, until
    it next became active.
    """
    settings_source = _source("MeshViewport.PresentationSettings.cs")
    fan_out = settings_source.split(
        "private void SynchronizePresentationDisplaySettings()", maxsplit=1
    )[1].split("public bool TrySetSynchronizedDisplayMode", maxsplit=1)[0]

    assert "foreach (var context in _presentationContexts.Values)" in fan_out
    assert "context.GridVisible = _presentationGridVisible;" in fan_out
    assert "context.GizmoVisible = _presentationGizmoVisible;" in fan_out


def test_a_resident_package_swap_keeps_the_host_overlay_choice() -> None:
    """Grid/gizmo visibility is a host toggle, not package content.

    Adopting the incoming scene's values dropped the grid whenever the package
    came from a builder that writes `"grid": {"visible": false}`.
    """
    package_source = _source("MeshViewport.ResidentPackage.cs")
    replace = package_source.split("public void ReplaceResidentPackage(", maxsplit=1)[1]

    assert "_presentationGridVisible = scene.GridVisible;" not in replace
    assert "_presentationGizmoVisible = scene.GizmoVisible;" not in replace
    assert (
        "_scene.SetPresentationOverlayVisibility(_presentationGridVisible, _presentationGizmoVisible);"
        in replace
    )


def test_preview_profile_package_load_keeps_package_overlay_visibility() -> None:
    """The preview profile owns navigation mode, not the Grid checkbox.

    Its package-loader override ran before the first host presentation replay,
    so every real PAC load visibly cleared a checked grid until the user toggled
    the control again.
    """
    package_source = _source("ExperimentForm.PackageProtocol.cs")
    prepare = package_source.split("private static PreparedResidentPackage PrepareResidentPackage(", maxsplit=1)[1]
    prepare = prepare.split("var parseMilliseconds = phase.Elapsed.TotalMilliseconds;", maxsplit=1)[0]

    assert 'scene.SetInteractionMode("placement");' in prepare
    assert 'scene.SetComparisonMode("replacement_only");' in prepare
    assert "SetPresentationOverlayVisibility" not in prepare


def test_pane_focus_and_pane_render_never_read_stored_overlay_visibility() -> None:
    """Grid/gizmo visibility is one host flag for the whole viewport.

    Display updates only write the active context, so a pane's stored copy can
    go stale. Restoring it on `LoadPresentationContext` -- which a click on
    empty space reaches through pane focus -- switched the grid off with no
    host request, and reading `context.GridVisible` at render time showed a
    stale grid in whichever pane was not active when the toggle last changed.
    """
    presentation_source = _source("MeshViewport.Presentation.cs")
    load_context = presentation_source.split(
        "private void LoadPresentationContext(string contextId)", maxsplit=1
    )[1].split("public void ActivatePresentationView", maxsplit=1)[0]
    assert "_presentationGridVisible = context.GridVisible;" not in load_context
    assert "_presentationGizmoVisible = context.GizmoVisible;" not in load_context
    assert (
        "_scene.SetPresentationOverlayVisibility(" in load_context
    ), "context switches must keep asserting the current global overlay flags"

    split_source = _source("MeshViewport.SplitView.cs")
    render_pane = split_source.split(
        "private D3D11RenderPane RenderPane(", maxsplit=1
    )[1].split("private Dictionary<string, object?> PaneRectangleStatusPayload()", maxsplit=1)[0]
    assert "context.GridVisible" not in render_pane
    assert "_presentationGridVisible," in render_pane
    assert '_presentationGizmoVisible && role != "reference"' in render_pane


def test_host_tool_state_cannot_rewrite_the_selection_target_combo() -> None:
    """The host's tool_state names how a stroke applies, not the combo value.

    The host republishes tool_state on every control refresh, and "vertex" is
    the one target_mode value that matches a combo item -- so writing it into
    the combo reset a reader's Faces/Wires choice back to Vertices after
    every selection. The combo belongs to the editor after its fresh-session
    default is applied.
    """
    host_state_source = _source("ExperimentForm.HostState.cs")
    apply_host_state = host_state_source.split("private void ApplyHostToolState", maxsplit=1)[1]
    assert "_selectionTarget" not in apply_host_state
    reset_defaults = host_state_source.split(
        "private void ResetSelectionGestureDefaultsForSession", maxsplit=1
    )[1].split("private void ApplyHostToolState", maxsplit=1)[0]
    assert "_selectionTarget.SelectedIndex = 0;" in reset_defaults


def test_brush_and_lasso_select_honor_the_hosts_selection_mode() -> None:
    """The Selection combo's Brush/Lasso/Rectangle promise is real now.

    The combo published `selection_mode` to the helper for as long as it has
    existed, and the helper ignored it: every Select drag was a rectangle.
    Brush paints throttled add/subtract `screen_brush` dabs that native unions
    over the sweep; lasso sends the swept polygon as `screen_region` mode
    "lasso" with the rectangle endpoints kept as the older-core fallback; a
    plain click keeps the precise 14px click pick in every mode.
    """
    host_state_source = _source("ExperimentForm.HostState.cs")
    # Adopted only when the host value changes: the host republishes
    # tool_state per control refresh, and re-applying the same combo value
    # would stomp a drag mode picked on the editor side between refreshes.
    assert "_viewport.SetSelectionDragMode(selectionDragMode);" in host_state_source
    assert "_lastHostSelectionDragMode" in host_state_source
    assert "ResetSelectionGestureDefaultsForSession" in host_state_source
    material_source = _source("ExperimentForm.MaterialProtocol.cs")
    session_rebind = material_source.split("if (sessionChanged)", maxsplit=1)[1].split(
        "if (!provisional)", maxsplit=1
    )[0]
    assert "ResetSelectionGestureDefaultsForSession();" in session_rebind

    input_source = _source("MeshViewport.Input.cs")
    set_mode = input_source.split("internal void SetSelectionDragMode(", maxsplit=1)[1].split(
        "private void BeginSelectionDrag(", maxsplit=1
    )[0]
    # Only the three drag modes are accepted; the standalone host publishes
    # its element mode in the same field and must not reset the choice.
    assert 'is "brush" or "lasso" or "rectangle"' in set_mode
    begin_drag = input_source.split("private void BeginSelectionDrag(", maxsplit=1)[1]
    assert '"mesh_edit"' in begin_drag, "paint and lasso arm only inside Edit Mesh"

    picking_source = _source("MeshViewport.SelectionPicking.cs")
    assert "private void MaybeEmitSelectionPaintSample(Point point, bool final = false)" in picking_source
    assert "SelectionPaintSampleIntervalMs" in picking_source
    assert '["paint_sample"] = true' in picking_source
    finish = picking_source.split("private void FinishEdgeDrag(Point point)", maxsplit=1)[1].split(
        "private Rectangle EdgeDragRectangle", maxsplit=1
    )[0]
    # The paint branch closes the sweep before the rectangle payload can be
    # built, and the lasso polygon rides the region payload.
    assert finish.index("MaybeEmitSelectionPaintSample(point, final: true)") < finish.index(
        '["screen_region"]'.replace("[", "[")
    )
    assert 'region["mode"] = "lasso";' in finish
    assert 'region["points"]' in finish
    # A step longer than the brush radius -- or a pointer path that bowed away
    # from the straight chord between throttled samples -- becomes a native
    # brush-path band over the polyline actually swept, so the painted band has
    # no holes at any cursor speed or curvature: the 30ms cadence bounds
    # message rate, never coverage.
    assert "private void EmitSelectionSweepPath(" in picking_source
    sampler = picking_source.split(
        "private void MaybeEmitSelectionPaintSample(Point point, bool final = false)", maxsplit=1
    )[1].split("private void EmitSelectionSweepPath(", maxsplit=1)[0]
    assert "stepLength > radius" in sampler
    assert "SelectionPaintPathLeavesChord(previous, point, radius)" in sampler
    assert "toggleGesture" in sampler
    assert "EmitFinalTogglePaintSelection();" in sampler
    sweep = picking_source.split("private void EmitSelectionSweepPath(", maxsplit=1)[1]
    assert 'region["mode"] = "brush";' in sweep
    assert 'region["radius_pixels"] = radius;' in sweep
    assert '["paint_sample"] = true' in sweep
    assert "_selectionPaintToggleTouchedVertices.Add((submeshIndex, vertexIndex))" in picking_source
    toggle_finish = picking_source.split(
        "private void EmitFinalTogglePaintSelection()", maxsplit=1
    )[1].split("private void EmitSelectionSweepPath(", maxsplit=1)[0]
    assert 'region["mode"] = "brush";' in toggle_finish
    assert 'region["points"] = path' in toggle_finish
    assert 'region["radius_pixels"] = SelectionPaintRadiusPixels();' in toggle_finish
    assert '}, "end");' in toggle_finish
    assert '["operation"] = "toggle"' in toggle_finish
    assert '["local_selection"]' not in toggle_finish
    assert "ProvisionalSelectionVertexBudget" not in picking_source
    # The visible-mode echo filters by the same kind of occlusion raster the
    # native authority uses, not by face orientation alone.
    assert "OcclusionDepths" in picking_source
    assert "PaintSegmentVisible" in picking_source
    assert "VertexBuckets" in picking_source
    assert "EdgeBuckets" in picking_source
    assert "PartBounds" in picking_source

    renderer_source = _source("MeshViewport.Renderer.cs")
    # Rectangle rubber-band belongs to rectangle mode alone; painting shows
    # the brush ring and a lasso drag draws the polygon actually swept.
    assert (
        "_edgeDragActive && !_selectionPaintActive && lassoDragPath is null ? EdgeDragRectangle() : null"
        in renderer_source
    )
    assert "(brushTool || selectPaint) && _pointerInside" in renderer_source
    assert "(IReadOnlyList<Point>)_selectionLassoPoints" in renderer_source
    assert "_provisionalSelectedVertices," in renderer_source
    assert "_provisionalSelectedFaces," in renderer_source
    assert "_provisionalSelectedEdges);" in renderer_source
    assert "_presentedSources.UnionWith(ProvisionalStrokeSourceIndices);" not in renderer_source
    overlay_source = _source("D3D11MaterialViewport.Overlay.cs")
    assert "private void DrawSelectionLassoOverlay()" in overlay_source
    assert "DrawSelectionLassoOverlay();" in overlay_source
    diagnostic_source = _source("ExperimentForm.EditMeshToolDiagnostics.cs")
    assert "RunSelectionReleaseRecoveryDiagnostic" in diagnostic_source
    assert '["selection_release_recovery"]' in diagnostic_source
    interaction_soak_source = _source("MeshViewport.InteractionSoak.cs")
    assert "FinishSelectionInteractionSoakAfterLostMouseUp" in interaction_soak_source
    assert "SelectionInteractionSoakStateClean" in interaction_soak_source
    selection_paint_source = _source("MeshViewport.SelectionPaint.cs")
    assert "Task.Run(" in selection_paint_source
    assert "PaintProjectionBuildSnapshot" in selection_paint_source
    assert "_pendingPaintSample" in selection_paint_source
    assert "PaintProjectionDiagnosticsPayload" in _source("MeshViewport.Status.cs")
    assert "EndPaintProjectionGesture" in _source("MeshViewport.Input.cs")
    assert "BeginPaintProjectionGesture" in _source("MeshViewport.Input.cs")
    interaction_soak_source = _source("HeadlessGpuInteractionSoak.cs")
    assert "CaptureShortFaceBrushProof" in interaction_soak_source
    assert "BeginShortFaceBrushInteractionSoak" in interaction_soak_source
    assert '"select_brush_face"' in _source("MeshViewport.InteractionSoak.cs")
    assert '"input_p95_at_most_13_89_ms"' in interaction_soak_source
    assert '"host_heartbeat_at_most_33_3_ms"' in interaction_soak_source


def test_the_local_click_selection_pickers_stay_removed() -> None:
    """Hit resolution lives in native screen selection; the local pickers had
    no callers left, and the `selection_request` echo they emitted was read by
    the host as an authoritative empty selection -- the mirror wipe behind
    "selecting a part cleared my selection". The SimplePreview part pick is
    the one local fallback that stays.
    """
    all_source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(DOTNET_EDITOR.glob("*.cs"))
    )
    for method in (
        "private void SelectVertexAt(",
        "private void SelectFaceAt(",
        "private void SelectPartAt(",
        "private void SelectEdgeAt(",
        "private void NotifyLocalSelectionChanged()",
        "NotifyLocalSelectionChanged();",
        "private void ApplySelectionMapOperation(",
        "private void ApplyPartSelectionOperation(",
        "private void ApplyEdgeSelectionOperation(",
    ):
        assert method not in all_source, method
    assert "private int PickPartAt(Point point)" in _source("MeshViewport.SelectionActions.cs")


def test_embedded_reveal_presents_the_resident_scene_before_ws_visible() -> None:
    """The first composited frame must be the scene resident at reveal.

    The swap chain still holds whatever was last presented while the window
    was hidden -- the procedural prewarm triangle -- and revealing first let
    DWM show that stale surface until the first post-reveal paint.
    """
    reveal_source = _source("ExperimentForm.EmbeddedWindowRealization.cs")
    reveal = reveal_source.split("private void RevealEmbeddedWindow()", maxsplit=1)[1].split(
        "WriteProtocolEvent(", maxsplit=1
    )[0]
    assert "NativeWindowHost.ResizeToParent(" in reveal
    assert "_viewport.PresentFreshFrame();" in reveal
    assert reveal.index("NativeWindowHost.ResizeToParent(") < reveal.index("PresentFreshFrame")
    assert reveal.index("PresentFreshFrame") < reveal.index("Visible = true")

    renderer_source = _source("MeshViewport.Renderer.cs")
    assert "public bool PresentFreshFrame()" in renderer_source
    viewport_source = _source("D3D11MaterialViewport.cs")
    assert "public bool TryPresentCurrentScene()" in viewport_source


def test_an_early_textured_display_request_is_replayed_when_the_session_arrives() -> None:
    """A textured mode picked before any resident session existed used to be
    dropped on the floor: the combo snapped back to the untextured fallback and
    nothing ever re-sent the request, so "Solid (Textured)" did nothing until
    the user happened to pick another textured mode later.
    """
    controls = _source("ExperimentForm.Controls.cs")
    request = controls.split("private void RequestResidentViewportDisplay(", maxsplit=1)[1]
    request = request.split("private bool HasResidentTextureResources", maxsplit=1)[0]
    assert "_pendingResidentDisplayMode = mode;" in request
    assert "_pendingResidentDisplayMode = string.Empty;" in request
    assert "private void ReplayPendingResidentDisplayRequest()" in controls

    material = _source("ExperimentForm.MaterialProtocol.cs")
    observe = material.split("private void ObserveResidentSession(", maxsplit=1)[1]
    observe = observe.split("private bool CanApplyMaterialEditRevision(", maxsplit=1)[0]
    assert observe.count("ReplayPendingResidentDisplayRequest();") == 3

    package = _source("ExperimentForm.PackageProtocol.cs")
    establish = package.split("private void EstablishSimplePreviewSession(", maxsplit=1)[1]
    establish = establish.split("private void HandleResidentPackageLoadRequest(", maxsplit=1)[0]
    assert "ReplayPendingResidentDisplayRequest();" in establish


def test_the_overlay_comparison_pane_keeps_the_placement_gizmo() -> None:
    """Overlay's single pane has role "comparison", and the old gate required
    "editable" — so the gizmo silently vanished exactly in the view whose
    replacement it exists to move. Only the locked reference pane hides it.
    """
    split_view = _source("MeshViewport.SplitView.cs")
    pane = split_view.split("private D3D11RenderPane RenderPane(", maxsplit=1)[1]
    pane = pane.split("private Dictionary<string, object?> PaneRectangleStatusPayload", maxsplit=1)[0]
    # The gizmo flag is the viewport-global host toggle, not the pane
    # context's stored copy; only the locked reference pane hides it.
    assert '_presentationGizmoVisible && role != "reference"' in pane
    assert 'role == "editable"' not in pane


def test_a_released_resident_session_may_be_handed_to_the_next_edit_session() -> None:
    """The helper's session latch needs a release, or it outlives its owner.

    A resident helper is kept warm across the close of the mesh that opened it,
    so latching the session for the life of the process left the next Modify
    Original permanently refused as a mismatch -- the second mesh never loaded
    and only killing the helper recovered it. A release names the session
    letting go; an unreleased, non-provisional session is still nobody else's.
    """
    material = _source("ExperimentForm.MaterialProtocol.cs")
    protocol = _source("ExperimentForm.Protocol.cs")

    assert 'case "session_release":\n                    ObserveResidentSessionRelease(root);' in protocol
    assert 'or "session_release"' in _source("ExperimentForm.ProfileProtocol.cs")

    release = material.split("private void ObserveResidentSessionRelease(", maxsplit=1)[1]
    release = release.split("private void ObserveResidentSession(", maxsplit=1)[0]
    assert '["code"] = "session_release_mismatch",' in release, (
        "only the session holding the helper may release it"
    )
    assert "_residentSessionReleased = true;" in release

    observe = material.split("private void ObserveResidentSession(", maxsplit=1)[1]
    observe = observe.split("private bool CanApplyMaterialEditRevision(", maxsplit=1)[0]
    assert "if ((!_residentSessionProvisional && !_residentSessionReleased) || provisional)" in observe
    assert observe.count("_residentSessionReleased = false;") == 3, (
        "adopting, rebinding and the owner's own return all withdraw the release"
    )

    # The modes belong to the reader who left, not to the mesh arriving next.
    assert "_residentSessionRebound = true;" in observe
    carry = _source("ExperimentForm.PackageProtocol.cs").split(
        "private void CarryResidentInteractionModesForward(", maxsplit=1
    )[1]
    carry = carry.split("private void ReassertInteractionModeControls(", maxsplit=1)[0]
    assert "if (_residentSessionRebound)" in carry
    assert "_residentSessionRebound = false;" in carry


def test_renderer_status_cache_is_keyed_on_the_surface_it_reports() -> None:
    """The cached status reports the D3D surface, so it must key on that size.

    ``RenderSurfaceStatusPayload`` publishes ``surface.ClientSize``, while the
    surface is a child that settles after its parent. Keying the cache only on
    the parent control left a surface-only resize with nothing to invalidate it,
    so the status kept publishing the pre-settle rectangle: measured at
    1047x1195 for a pane its own ``ActivePaneBounds`` and Win32 both reported as
    1242x1195.
    """

    source = _source("ExperimentForm.MaterialProtocol.cs")
    key_record = source.split("private readonly record struct RendererDiagnosticCacheKey(", maxsplit=1)[1]
    key_record = key_record.split(");", maxsplit=1)[0]
    assert "SurfaceWidth" in key_record
    assert "SurfaceHeight" in key_record

    construction = source.split("var cacheKey = new RendererDiagnosticCacheKey(", maxsplit=1)[1]
    construction = construction.split(");", maxsplit=1)[0]
    assert "_viewport.RenderSurfaceClientSize.Width" in construction
    assert "_viewport.RenderSurfaceClientSize.Height" in construction

    split_view = _source("MeshViewport.SplitView.cs")
    assert "internal Size RenderSurfaceClientSize => PaneSurfaceSize();" in split_view
