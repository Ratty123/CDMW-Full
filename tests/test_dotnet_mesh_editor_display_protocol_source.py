from tests.test_dotnet_mesh_editor_tool_protocol_source import DOTNET_EDITOR, ROOT, _source


def test_dotnet_display_and_authoring_protocol_stay_in_sync() -> None:
    protocol_source = _source("ExperimentForm.Protocol.cs")
    material_protocol_source = _source("ExperimentForm.MaterialProtocol.cs")
    display_source = _source("ExperimentForm.ViewportDisplayProtocol.cs")
    display_modes = _source("MeshViewport.DisplayModes.cs")
    controls_source = _source("ExperimentForm.Controls.cs")
    resident_package_source = _source("MeshViewport.ResidentPackage.cs")
    package_protocol_source = _source("ExperimentForm.PackageProtocol.cs")
    morph_source = _source("ExperimentForm.MorphRefit.cs")
    shader_source = _source("D3D11MaterialShaders.hlsl")
    host_state_source = _source("ExperimentForm.HostState.cs")
    d3d_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOTNET_EDITOR.glob("D3D11MaterialViewport*.cs"))
    )
    all_source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(DOTNET_EDITOR.glob("*.cs")))

    assert 'case "viewport_display_update":' in protocol_source
    assert 'ViewportDisplayModesCapability = "viewport_display_modes_v1"' in protocol_source
    assert 'WriteViewportDisplayResult(root, "viewport_display_applied"' in display_source
    assert 'WriteViewportDisplayResult(root, "viewport_display_failed"' in display_source
    assert "CopyMutationEnvelope(request, payload);" in display_source
    assert 'WriteProtocolEvent("material_state_started"' in material_protocol_source
    assert '&& decode.Failures.Count > 0)' in material_protocol_source
    assert 'WriteProtocolEvent("viewport_display_request"' in controls_source
    assert '"Loading textures in the resident viewport..."' in controls_source
    assert "SyncPreviewModeSelection(" in display_source
    assert "texture_request_pending" in display_source
    assert 'var requestedMode = JsonString(root, "requested_mode")' in display_source
    assert "textureRequestPending && requestedMode.Length > 0" in display_source
    assert 'message["source_identity"] = _scene.SourceIdentity;' in _source("ExperimentForm.Output.cs")
    assert 'hasTextureResources ? "textured" : "untextured_wire"' in resident_package_source
    assert "InitialResidentDisplayMode(bool hasTextureResources)" in resident_package_source
    assert "InitialResidentDisplayMode(" in controls_source
    resident_readiness = controls_source.split(
        "private bool HasResidentTextureResources()",
        maxsplit=1,
    )[1].split("private void RequestResidentViewportDisplay", maxsplit=1)[0]
    assert "_viewport.HasTexturedMaterialResources" in resident_readiness
    assert "TextureLoadResources().Any()" not in resident_readiness
    assert package_protocol_source.index("TextureReadinessError") < package_protocol_source.index(
        "return new PreparedResidentPackage"
    )
    assert '"texture_resources_ready"' in material_protocol_source
    textured_request = controls_source.split(
        "private void RequestResidentViewportDisplay(string mode)",
        maxsplit=1,
    )[1].split("private void ReplayPendingResidentDisplayRequest", maxsplit=1)[0]
    assert "SyncPreviewModeSelection(mode);" in textured_request
    assert "SyncPreviewModeSelection(_viewport.DisplayMode);" not in textured_request
    assert '"Faces + Wire"' in controls_source
    assert '"Solid + Wire"' not in controls_source
    assert 'normalized = "textured";' in controls_source
    assert "selectedIndex: Array.IndexOf(" in controls_source
    assert 'var mode = _placementPreviewMode;' in controls_source
    assert 'SyncPreviewModeSelection(_viewport.DisplayMode);' in _source("ExperimentForm.PresentationProtocol.cs")
    no_morph_finish = morph_source.split("private void RequestFinishEditMesh()", maxsplit=1)[1].split(
        "private void BeginFinishCommitOrSave()", maxsplit=1
    )[0]
    assert "if (!_morphStateReceived)" in no_morph_finish
    assert 'WriteProtocolEvent("save_request");' in no_morph_finish
    for mode in ("textured", "untextured_faces", "wire", "vertices", "wire_vertices", "xray"):
        assert f'"{mode}"' in display_modes
    assert "if (ShowSolid)" in d3d_source
    assert "if (_overlayShowVertices)" in d3d_source
    assert "PrimitiveTopology.PointList" in d3d_source
    assert "MaterialDebugMode > 6.5f" in shader_source
    assert '"Brushes paint the replacement under the yellow circle; no preselection is required. Left-drag to apply. Right-drag pans; wheel zooms."' in all_source
    assert 'ActiveTool is "grab" or "smooth" or "inflate" or "pinch"' in all_source
    assert "DrawBrushCursorOverlay();" in d3d_source
    assert '_statusLabel.Text = tool is "grab" or "smooth" or "inflate" or "pinch"' in controls_source
    assert "private void ToggleTool" not in controls_source
    assert 'button.Click += (_, _) => ActivateTool(tool, text, announce: true);' in controls_source
    assert 'WriteProtocolEvent("tool_changed"' in controls_source
    assert 'ToolButton("Orbit", "orbit")' in all_source
    assert "ActivateTool(tool, tool[..1].ToUpperInvariant() + tool[1..]);" in host_state_source
    assert 'if (!string.Equals(tool, _viewport.ActiveTool, StringComparison.OrdinalIgnoreCase))' in host_state_source


def test_the_helper_advertises_the_session_handoff_capability() -> None:
    provenance = _source("HelperBuildProvenance.cs")
    status = _source("MeshViewport.Status.cs")
    session = (ROOT / "cdmw" / "ui" / "preview" / "dotnet_session.py").read_text(encoding="utf-8")

    assert '"authoring_session_handoff_v1",' in provenance
    assert '"authoring_session_handoff_v1",' in status
    assert '"authoring_session_handoff_v1" not in self._capabilities' in session
    assert provenance.count('or "authoring_session_handoff_v1"') == 1
    assert status.count('or "authoring_session_handoff_v1"') == 1
