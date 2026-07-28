from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_EDITOR = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_EDITOR / name).read_text(encoding="utf-8")


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
    assert active_stroke_move.index("MouseButtons.Left") < active_stroke_move.index('Invoke("stroke_update"') < active_stroke_move.index("_strokePrevious = e.Location")
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
    assert failed_source.index("_activateAfterMaterialSync") < failed_source.index("ActivateResidentViewport")
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
    display_source = _source("ExperimentForm.ViewportDisplayProtocol.cs")
    display_modes = _source("MeshViewport.DisplayModes.cs")
    controls_source = _source("ExperimentForm.Controls.cs")
    resident_package_source = _source("MeshViewport.ResidentPackage.cs")
    morph_source = _source("ExperimentForm.MorphRefit.cs")
    shader_source = _source("D3D11MaterialShaders.hlsl")
    assert 'case "viewport_display_update":' in protocol_source
    assert 'ViewportDisplayModesCapability = "viewport_display_modes_v1"' in protocol_source
    assert 'WriteViewportDisplayResult(root, "viewport_display_applied"' in display_source
    assert 'WriteViewportDisplayResult(root, "viewport_display_failed"' in display_source
    assert "CopyMutationEnvelope(request, payload);" in display_source
    assert 'WriteProtocolEvent("material_state_started"' in material_protocol_source
    assert '&& decode.Failures.Count > 0)' in material_protocol_source
    assert 'WriteProtocolEvent("viewport_display_request"' in controls_source
    assert '"Loading textures in the resident viewport..."' in controls_source
    assert 'SyncPreviewModeSelection(_viewport.DisplayMode);' in display_source
    assert 'texture_request_pending' in display_source
    # One rule decides the settled view, so a load never presents an
    # intermediate mode before the host's own display update lands. Read-only
    # previews default to wire over untextured geometry, and to plain textured
    # geometry once textures resolve; the wire overlay stays an authoring
    # default only.
    assert 'hasTextureResources ? "textured" : "untextured_wire"' in resident_package_source
    assert 'hasTextureResources ? "textured_wire" : "untextured_wire"' in resident_package_source
    assert "InitialResidentDisplayMode(bool hasTextureResources)" in resident_package_source
    assert "InitialResidentDisplayMode(" in controls_source
    assert '"Faces + Wire"' in controls_source
    assert "selectedIndex: Array.IndexOf(" in controls_source
    assert 'var mode = _placementPreviewMode;' in controls_source
    assert 'SyncPreviewModeSelection(_viewport.DisplayMode);' in _source(
        "ExperimentForm.PresentationProtocol.cs"
    )
    no_morph_finish = morph_source.split(
        "private void RequestFinishEditMesh()", maxsplit=1
    )[1].split("private void BeginFinishCommitOrSave()", maxsplit=1)[0]
    assert "if (!_morphStateReceived)" in no_morph_finish
    assert 'WriteProtocolEvent("save_request");' in no_morph_finish
    for mode in ("textured", "untextured_faces", "wire", "vertices", "wire_vertices", "xray"):
        assert f'"{mode}"' in display_modes
    assert "if (ShowSolid)" in d3d_source
    assert "if (_overlayShowVertices)" in d3d_source
    assert "PrimitiveTopology.PointList" in d3d_source
    assert "MaterialDebugMode > 6.5f" in shader_source
    assert '"Brushes paint the replacement under the yellow circle; no preselection is required. Left-drag to apply. Right-drag pans; wheel zooms."' in program_source
    assert 'ActiveTool is "grab" or "smooth" or "inflate" or "pinch"' in all_source
    assert "DrawBrushCursorOverlay();" in d3d_source
    assert '_statusLabel.Text = tool is "grab" or "smooth" or "inflate" or "pinch"' in _source("ExperimentForm.Controls.cs")
    # Tool buttons are idempotent: pressing the active tool keeps it active
    # instead of dropping back to orbit, which read as the tool switching itself
    # off. Orbit stays one click away on its own button.
    assert "private void ToggleTool" not in controls_source
    assert 'button.Click += (_, _) => ActivateTool(tool, text);' in controls_source
    assert 'ToolButton("Orbit", "orbit")' in program_source
    assert "ActivateTool(tool, tool[..1].ToUpperInvariant() + tool[1..]);" in host_state_source


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
    assert "Ctrl+LMB drag" in controls_source
    assert "Ctrl+Shift+Z" in controls_source
    assert "IsOrbitOverrideGesture(e)" in input_source
    assert '(ModifierKeys & Keys.Control) == Keys.Control' in input_source
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


def test_dotnet_overlay_geometry_reuses_one_dynamic_vertex_buffer_per_frame() -> None:
    d3d_source = _source("D3D11MaterialViewport.cs")
    overlay_source = _source("D3D11MaterialViewport.Overlay.cs")
    metrics_source = _source("D3D11MaterialViewport.Metrics.cs")

    assert "BeginOverlayFrame();" in d3d_source
    assert "DisposeOverlayDynamicResources();" in d3d_source
    assert "InitialOverlayVertexCapacity" in overlay_source
    assert "ResourceUsage.Dynamic" in overlay_source
    assert "CpuAccessFlags.Write" in overlay_source
    assert "MapMode.WriteDiscard" in overlay_source
    flush_source = overlay_source.split("private unsafe void FlushOverlayPrimitives()", maxsplit=1)[1]
    queue_source = overlay_source.split("private unsafe void FlushOverlayPrimitives()", maxsplit=1)[0]
    assert "_overlayBatchFlushCount++;" in flush_source
    assert "_overlayBatchedDrawCount++;" in flush_source
    assert "if (command.DrawSceneVertices)" in flush_source
    assert "DrawD3D11VertexOverlay();" in flush_source
    assert "_context.Map(" not in queue_source
    assert "using var vertexBuffer = _device.CreateBuffer" not in overlay_source
    assert "_context.Draw((uint)command.VertexCount, (uint)command.StartVertex);" in overlay_source
    assert '["overlay_vertex_buffer_creates"]' in metrics_source
    assert '["overlay_vertex_buffer_reused"]' in metrics_source


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
    assert '"textured_wire" => "untextured_wire"' in controls_source
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
    assert "ShowXRay || !IsWorldPointOccluded" in picking
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
    assert "ApplyEmbeddedToolPanelVisibility(meshEdit: true);" in controls_source
    assert "_leftToolSplit.Panel1Collapsed = true;" in controls_source
    assert "_rightToolSplit.Panel2Collapsed = true;" in controls_source
    assert "_leftToolSplit.Panel1Collapsed = false;" in controls_source
    assert "_rightToolSplit.Panel2Collapsed = false;" in controls_source
    assert "if (!options.Embedded)" not in program_source
    assert '"DotNetMeshEditorLeftToolScroll"' in program_source
    assert '"DotNetMeshEditorRightToolScroll"' in program_source
    assert 'SetWindowTheme(control.Handle, "DarkMode_Explorer", null)' in program_source
    assert "ApplyDarkScrollbars(_submeshList);" in program_source
    assert 'CommandButton("Show / Hide", "toggle_visibility")' in program_source
    assert 'CommandButton("Duplicate", "duplicate")' in program_source
    assert 'CommandButton("Delete", "delete")' in program_source
    assert '"Finish Edit Mesh"' in program_source
    assert "RequestFinishEditMesh();" in program_source
    assert 'WriteProtocolEvent("save_request")' in morph_source
    assert 'AddSection(stack, "Clipboard"' not in program_source
    assert '_selectionTarget.SelectedItem = "Part";' in program_source
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
    assert "_submeshList.SelectionMode = SelectionMode.MultiExtended;" in program_source
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
    assert 'EditorEventRequested?.Invoke("select_request", payload);' in committed_selection
    assert "ApplyPartSelectionOperation" not in committed_selection
    assert "ApplySelectionMapOperation" not in committed_selection
    assert "ApplyEdgeSelectionOperation" not in committed_selection
    assert "SelectedSubmeshIndex = submeshIndex;" not in selection_source
    assert "new HashSet<int> { SelectedSubmeshIndex }" not in selection_commands_source
    assert "SyncSelectedPartFocus();" in topology_source
    assert "DrawSelectedSourcesOverlay();" in overlay_source
    assert "OverlayColor(70, 155, 255, _overlayShowXRay ? 64 : 42)" in overlay_source


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
    real_proof_source = (ROOT / "tools" / "mesh_harness" / "real_dotnet.py").read_text(encoding="utf-8")
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
    assert '-m "not visual and not real_game"' in pytest_config


def test_real_dotnet_harness_has_dedicated_resident_side_by_side_zoom_proof() -> None:
    source = (ROOT / "tools" / "mesh_harness" / "real_dotnet.py").read_text(encoding="utf-8")
    input_source = (ROOT / "tools" / "mesh_harness" / "real_dotnet_input.py").read_text(
        encoding="utf-8"
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
