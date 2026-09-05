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





































def test_dotnet_input_precedence_depth_passes_and_mode_controls_are_explicit() -> None:
    host_commands = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_commands.py").read_text(
        encoding="utf-8"
    )



    assert 'phase == "begin" and isinstance(payload.get("local_selection"), Mapping)' not in host_commands






def test_dotnet_lifecycle_counts_use_parser_and_renderer_owners() -> None:
    host_source = "\n".join(
        (ROOT / "cdmw" / "ui" / "mesh_editor" / name).read_text(encoding="utf-8")
        for name in ("tab_shell.py", "tab_shell_runtime.py")
    )

    assert '"process_restart_count": 0' in host_source
    assert '"full_reload_count": 0' in host_source




def test_embedded_dotnet_exposes_its_tool_panels_in_mesh_edit_mode() -> None:

    # The Parts group builds through its own owner, which also carries the
    # selected-part detail; every whole-part command declares source authority.

    host_protocol = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_payloads.py").read_text(encoding="utf-8")
    sender = host_protocol.split("    def _send_dotnet_native_update(", maxsplit=1)[1].split(
        "    def _dotnet_screen_selection_payload", maxsplit=1
    )[0]
    assert "queue.enqueue_mutation_batch(batch)" in sender
    assert "edit_packets = [batch.as_protocol_payload()]" in sender
    assert '"event": "preview_triangle_update"' not in sender
    assert '"event": "selection_update"' not in sender






def test_codex_mesh_checks_use_real_game_pac_and_keep_unit_runs_non_visual() -> None:
    source = (ROOT / "scripts" / "codex_check.ps1").read_text(encoding="utf-8")
    rust_proof_source = (
        ROOT / "tools" / "mesh_harness" / "real_rust_preview.py"
    ).read_text(encoding="utf-8")
    # The old physical-input harness remains historical compatibility coverage,
    # but it is no longer the production/default appearance gate.
    real_proof_source = "\n".join(
        (ROOT / "tools" / "mesh_harness" / name).read_text(encoding="utf-8")
        for name in ("real_dotnet.py", "real_dotnet_report.py")
    )
    real_input_source = (ROOT / "tools" / "mesh_harness" / "real_dotnet_input.py").read_text(encoding="utf-8")

    assert "real-archive-rust-preview-smoke" in source
    assert "Running no-window real PAC Rust Archive Preview proof" in source
    assert "real-archive-mesh-editor-dotnet-edit-smoke" not in source
    assert "--capture-cdmw-preview-session" in rust_proof_source
    assert '"desktop_automation_used": False' in rust_proof_source
    assert '"vortice_used": False' in rust_proof_source
    assert "test_mesh_editor\\cd_phm_00_nude_10_0001.pac" not in source
    mesh_unit_start = source.index('"mesh-unit" = @(')
    mesh_unit_end = source.index("    )", mesh_unit_start)
    assert "test_mesh_editor_dev_harness.py" not in source[mesh_unit_start:mesh_unit_end]
    assert "--ignore=tests/test_mesh_editor_dev_harness.py" not in source
    assert '"mouse_input_backend": "helper_ui_thread_resident_probe"' in real_proof_source
    assert "request_resident_interaction_probe(" in real_input_source
    assert '"event": "resident_interaction_probe"' in real_input_source
    assert "_set_screen_cursor_position" not in real_input_source
    assert "_send_physical_mouse_message" not in real_input_source
    assert "SetForegroundWindow" not in real_input_source
    real_session_source = (
        ROOT / "tools" / "mesh_harness" / "real_dotnet_session.py"
    ).read_text(encoding="utf-8")
    assert "WA_ShowWithoutActivating" in real_session_source
    assert "WindowDoesNotAcceptFocus" in real_session_source
    assert ".activateWindow()" not in real_session_source
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
    assert "_send_scoped_mouse_wheel(" in input_source
    assert "-120" in input_source
    assert "120" in input_source
    assert "_set_screen_cursor_position" not in input_source
    assert '"non_target_camera_unchanged"' in input_source
    assert '"inverse_camera_restored_exactly"' in input_source
