from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_EDITOR = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_EDITOR / name).read_text(encoding="utf-8")


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
    all_source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(DOTNET_EDITOR.glob("*.cs")))

    assert '["local_selection"] = SelectionSnapshotPayload()' in input_source
    assert 'EditorEventRequested?.Invoke("selection_request"' in selection_source
    assert "NotifyLocalSelectionChanged();" in picking_source
    assert "_strokePrevious" in input_source
    assert "_strokeStart" not in input_source
    active_stroke_move = input_source.split("if (_editorStrokeActive)", maxsplit=2)[2].split("else if (_rotating)", maxsplit=1)[0]
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
    assert '"host_tool_state_v1"' in protocol_source
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
    assert 'return $"fingerprint|{fingerprint}";' in texture_source
    assert "_decoded[resource.Path] = cached;" in texture_source
    assert 'case "material_state_update":' in protocol_source
    assert 'ObserveResidentSession(document.RootElement);' in protocol_source
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
    assert 'JsonString(document.RootElement, "material_signature")' in protocol_source
    assert "public bool TryApplyMaterialState(IReadOnlyCollection<int> affectedSubmeshes" in d3d_source
    display_source = _source("ExperimentForm.ViewportDisplayProtocol.cs")
    display_modes = _source("MeshViewport.DisplayModes.cs")
    shader_source = _source("D3D11MaterialShaders.hlsl")
    assert 'case "viewport_display_update":' in protocol_source
    assert 'ViewportDisplayModesCapability = "viewport_display_modes_v1"' in protocol_source
    assert 'WriteViewportDisplayResult("viewport_display_applied"' in display_source
    assert 'WriteViewportDisplayResult("viewport_display_failed"' in display_source
    for mode in ("textured", "untextured_faces", "wire", "vertices", "wire_vertices", "xray"):
        assert f'"{mode}"' in display_modes
    assert "if (ShowSolid)" in d3d_source
    assert "if (_overlayShowVertices)" in d3d_source
    assert "PrimitiveTopology.PointList" in d3d_source
    assert "MaterialDebugMode > 6.5f" in shader_source
    assert 'Text = "Choose a brush, then left-drag on the mesh. Right-drag pans; wheel zooms."' in program_source
    assert 'ActiveTool is "grab" or "smooth" or "inflate" or "pinch"' in all_source
    assert "DrawBrushCursorOverlay();" in d3d_source
    assert '_statusLabel.Text = tool is "grab" or "smooth" or "inflate" or "pinch"' in _source("ExperimentForm.Controls.cs")


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
    assert 'MarkEditRevisionApplied(update.EditRevision, "material_state_update")' in completion
    assert "_lastObservedSessionRevision" in protocol_source + material_source


def test_dotnet_resident_scene_owns_reference_grid_modes_and_gizmo() -> None:
    scene_source = _source("NetSceneState.cs")
    protocol_source = _source("ExperimentForm.Protocol.cs")
    overlay_source = _source("D3D11MaterialViewport.Overlay.cs")
    output_source = _source("ExperimentForm.Output.cs")
    program_source = _source("Program.cs")
    input_source = _source("MeshViewport.Input.cs")

    assert 'case "scene_state_update":' in protocol_source
    assert 'ResidentSceneCapability = "resident_scene_state_v1"' in protocol_source
    for mode in ("side_by_side", "overlay", "replacement_only", "original_only"):
        assert f'"{mode}"' in scene_source
    assert "EditableSubmeshCount" in scene_source
    assert "ReferenceSubmeshCount" in scene_source
    assert "DrawSceneGridAndGizmo" in overlay_source
    assert 'GizmoTool == "rotate"' in overlay_source
    assert 'GizmoTool == "scale"' in overlay_source
    assert "scene.EditableSubmeshCount" in output_source
    assert 'AddSection(stack, "Placement"' in program_source
    assert 'GizmoButton("Move", "move")' in program_source
    assert 'GizmoButton("Rotate", "rotate")' in program_source
    assert 'GizmoButton("Scale", "scale")' in program_source
    assert 'EditorEventRequested?.Invoke("placement_transform_request"' in input_source
    assert "ApplyGizmoDrag" in input_source


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
    host_source = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_shell.py").read_text(encoding="utf-8")

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


def test_embedded_dotnet_owns_one_dark_scrollable_tool_panel_and_stable_camera() -> None:
    program_source = _source("Program.cs")
    protocol_source = _source("ExperimentForm.Protocol.cs")
    material_source = _source("ExperimentForm.MaterialProtocol.cs")
    input_source = _source("MeshViewport.Input.cs")
    topology_source = _source("MeshViewport.Topology.cs")

    assert 'Name = "DotNetMeshEditorLayout"' in program_source
    assert "editorLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, toolPanel.Width));" in program_source
    assert "toolPanel.Margin = new Padding(0);" in program_source
    assert "_viewport.Margin = new Padding(0);" in program_source
    assert "editorLayout.Controls.Add(toolPanel, 0, 0);" in program_source
    assert "editorLayout.Controls.Add(_viewport, 1, 0);" in program_source
    assert "if (!options.Embedded)" not in program_source
    assert 'Name = "DotNetMeshEditorToolScroll"' in program_source
    assert 'SetWindowTheme(control.Handle, "DarkMode_Explorer", null)' in program_source
    assert "ApplyDarkScrollbars(_submeshList);" in program_source
    assert 'CommandButton("Show / Hide", "toggle_visibility")' in program_source
    assert 'CommandButton("Duplicate", "duplicate")' in program_source
    assert 'CommandButton("Delete", "delete")' in program_source
    assert '"Finish Edit Mesh"' in program_source
    assert 'WriteProtocolEvent("save_request")' in program_source
    assert 'AddSection(stack, "Clipboard"' not in program_source
    assert '_selectionTarget.SelectedItem = "Part";' in program_source
    assert "RefreshSubmeshList();" in protocol_source
    assert material_source.count("RefreshSubmeshList();") >= 2
    assert "Math.Clamp(_zoom, 1.0f, 500000.0f)" in input_source
    assert topology_source.count("var viewCenter = _center;") == 2
    assert topology_source.count("_center = viewCenter;") == 2
    assert "IsSubmeshVisibleForViewportSelection" in _source("MeshViewport.SelectionPicking.cs")
    assert "_materials.ParametersForSubmesh(pair.Key).Visible is false" in _source("D3D11MaterialViewport.Overlay.cs")

    host_protocol = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_protocol.py").read_text(encoding="utf-8")
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
    clicked_part = selection_source.split("private void SelectPartAt(Point point)", 1)[1].split("private int PickPartAt", 1)[0]
    assert "ApplyPartSelectionOperation(new[] { submeshIndex }, CurrentSelectionOperation());" in clicked_part
    assert "SelectedSubmeshIndex = submeshIndex;" not in clicked_part
    assert "new HashSet<int> { SelectedSubmeshIndex }" not in selection_commands_source
    assert "SyncSelectedPartFocus();" in topology_source
    assert "DrawSelectedSourcesOverlay();" in overlay_source
    assert "OverlayColor(70, 155, 255, _overlayShowXRay ? 64 : 42)" in overlay_source


def test_dotnet_embedded_ready_requires_a_verified_native_parent() -> None:
    host_source = _source("NativeWindowHost.cs")
    program_source = _source("Program.cs")
    protocol_source = _source("ExperimentForm.Protocol.cs")
    material_protocol_source = _source("ExperimentForm.MaterialProtocol.cs")

    constructor_source, shown_source = program_source.split("protected override void OnShown", maxsplit=1)
    assert "GetParent(child) != parent" in host_source
    assert "SetWindowPos(form.Handle, HwndTop" in host_source
    assert "SwpNoZOrder" not in host_source
    assert host_source.index("SetWindowLongPtrSafe(child") < host_source.index("SetParent(child, parent)")
    assert host_source.index("SetParent(child, parent)") < host_source.index("GetParent(child) != parent")
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
    assert "_viewport.Metrics.HasRenderedFrame" in constructor_source
    assert constructor_source.index("_viewport.Metrics.HasRenderedFrame") < constructor_source.index(
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


def test_real_dotnet_edit_harness_declares_mesh_edit_scene_mode() -> None:
    source = (ROOT / "tools" / "mesh_harness" / "real_dotnet.py").read_text(encoding="utf-8")

    assert '"_mesh_editor_embedded_comparison_mode", lambda: "replacement_only"' in source
    assert '"_mesh_editor_embedded_interaction_mode", lambda: "mesh_edit"' in source
