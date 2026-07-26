from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.mesh_harness.evidence import _real_game_mesh_evidence
from tools.mesh_harness.real_dotnet_flow import (
    PRODUCTION_FLOW_STEPS,
    _latest_settled_topology_metrics,
    production_flow_gates,
    record_flow_step,
)
from tools.mesh_harness.real_dotnet_material import resident_material_gates
from tools.mesh_harness.real_dotnet_display import (
    _DISPLAY_MODE_LABELS,
    _DISPLAY_MODES,
    _REQUIRED_PRODUCTION_DISPLAY_MODES,
    _image_color_metrics,
)


def test_dotnet_real_game_evidence_keeps_drag_and_heartbeat_samples() -> None:
    proof = {
        "ok": True,
        "backend": "dotnet",
        "renderer_backend": "d3d11_vortice_shader",
        "edit_backend": "cdmw_mesh_core_0.1",
        "mouse_drag_start": [10, 20],
        "mouse_drag_points": [[11, 20], [12, 20]],
        "mouse_drag_end": [12, 20],
        "selected_projected_screen_delta": [2.0, 0.0],
        "heartbeat_sample_count": 4,
        "max_heartbeat_gap_ms": 25.0,
        "changed_vertex_count": 1,
        "part_selection": {
            "initially_empty": True,
            "face_selection_keeps_part_unselected": True,
        },
        "resident_material_update": {
            "process_pid_before": 101,
            "process_pid_after": 101,
            "resource_metrics_before": {"texture_srv_creates": 2},
            "resource_metrics_after": {"texture_srv_creates": 2},
        },
        "resident_material_parameter_update": {
            "frame_count_before": 4,
            "frame_count_after": 5,
            "visual_diff_summary": {"ok": True, "changed_pixel_count": 10},
        },
        "gates": {
            "selected_geometry_only": True,
            "resident_material_srv_reused": True,
            "material_parameter_visual_diff": True,
        },
    }

    evidence = _real_game_mesh_evidence(proof)

    assert evidence["projected_drag"]["points"] == [[11, 20], [12, 20]]
    assert evidence["projected_drag"]["screen_delta"] == [2.0, 0.0]
    assert evidence["heartbeat"] == {"count": 4, "max_gap_ms": 25.0}
    assert evidence["resident_material_update"] == proof["resident_material_update"]
    assert evidence["resident_material_parameter_update"] == proof["resident_material_parameter_update"]
    assert evidence["part_selection"] == proof["part_selection"]
    assert evidence["gates"]["resident_material_srv_reused"] is True


def test_real_game_evidence_reads_top_level_gate_aliases() -> None:
    evidence = _real_game_mesh_evidence(
        {
            "ok": False,
            "source_archives_unchanged": True,
            "archive_source_content_unchanged": True,
        }
    )

    assert evidence["gates"]["archive_sources_unchanged"] is True
    assert evidence["gates"]["archive_source_content_unchanged"] is True


def test_real_texture_provenance_accepts_semantic_source_kinds() -> None:
    from tools.mesh_harness.real_dotnet import _has_real_archive_texture_provenance

    row = {
        "source_kind": "crimson_base_color",
        "source_sha256": "abc123",
        "archive_path": "character/texture/body.dds",
        "archive_provenance": {
            "pamt_path": r"C:\game\0009\0.pamt",
            "paz_path": r"C:\game\0009\33.paz",
            "virtual_path": "character/texture/body.dds",
        },
    }

    assert _has_real_archive_texture_provenance(row) is True
    row["archive_provenance"] = {"virtual_path": "character/texture/body.dds"}
    assert _has_real_archive_texture_provenance(row) is False


def test_real_dotnet_harness_waits_for_geometry_before_resident_materials() -> None:
    root = Path(__file__).resolve().parents[1]
    flow_source = (root / "tools" / "mesh_harness" / "real_dotnet.py").read_text(
        encoding="utf-8"
    )

    assert '_wait_protocol_event(state, "textures_ready", 0)' not in flow_source
    material_update = flow_source.index("error = exercise_resident_material_update(")
    offscreen_capture = flow_source.index(
        "state.offscreen_capture_evidence = exercise_deterministic_offscreen_capture("
    )
    assert material_update < offscreen_capture


def test_real_dotnet_capture_rejects_an_unowned_visible_window(tmp_path: Path) -> None:
    from tools.mesh_harness.real_dotnet_capture import capture_dotnet_viewport

    state = SimpleNamespace(
        viewport_hwnd=10,
        form_hwnd=11,
        production_process_pid=42,
        tab=SimpleNamespace(raise_=lambda: None, activateWindow=lambda: None, winId=lambda: 12),
        app=SimpleNamespace(processEvents=lambda: None),
    )
    output = tmp_path / "capture.png"
    with (
        patch("tools.mesh_harness.real_dotnet_capture._host_window_rect", return_value=(0, 0, 128, 128)),
        patch("tools.mesh_harness.real_dotnet_capture._activate_window_for_input", return_value=False),
        patch("tools.mesh_harness.real_dotnet_capture._window_at_screen_point", return_value=99),
        patch("tools.mesh_harness.real_dotnet_capture._window_process_id", return_value=100),
    ):
        result = capture_dotnet_viewport(state, output)

    assert result["ok"] is False
    assert "foreground visible capture target" in str(result["error"])
    assert not output.exists()


def test_real_dotnet_stroke_never_sends_global_input_without_foreground_ownership(tmp_path: Path) -> None:
    from tools.mesh_harness.real_dotnet import _drive_viewport_stroke

    state = SimpleNamespace(
        viewport={"width": 100, "height": 100},
        projected_center=(20.0, 20.0),
        viewport_hwnd=10,
        form_hwnd=11,
        production_process_pid=42,
        heartbeat_ms=[],
        heartbeat_started=0.0,
        tab=SimpleNamespace(
            standalone_dotnet_protocol_events=[],
            standalone_dotnet_update_queue=SimpleNamespace(metrics=lambda: {"active_revision": 0}),
        ),
        after_capture_path=tmp_path / "after.png",
    )
    with (
        patch("tools.mesh_harness.real_dotnet_input._host_window_rect", return_value=(0, 0, 100, 100)),
        patch("tools.mesh_harness.real_dotnet_input._activate_window_for_input", return_value=False),
        patch("tools.mesh_harness.real_dotnet_input._screen_cursor_position", return_value=None),
        patch("tools.mesh_harness.real_dotnet_input._set_screen_cursor_position") as set_cursor,
        patch("tools.mesh_harness.real_dotnet_input._send_left_button_input") as send_button,
        patch("tools.mesh_harness.real_dotnet._pump_for"),
        patch("tools.mesh_harness.real_dotnet._pump_until", return_value=True),
        patch("tools.mesh_harness.real_dotnet._capture_viewport", return_value={"ok": False}),
        patch("tools.mesh_harness.real_dotnet._base_error", side_effect=lambda _state, message: {"error": message}),
    ):
        result = _drive_viewport_stroke(state)

    assert result == {"error": "The .NET viewport could not be made the foreground input target."}
    set_cursor.assert_not_called()
    send_button.assert_not_called()


def test_real_dotnet_harness_targets_editable_pane_coordinates_on_shared_hwnd() -> None:
    root = Path(__file__).resolve().parents[1]
    flow_source = (root / "tools" / "mesh_harness" / "real_dotnet.py").read_text(
        encoding="utf-8"
    )
    input_source = (
        root / "tools" / "mesh_harness" / "real_dotnet_input.py"
    ).read_text(encoding="utf-8")

    assert 'client_x = int(state.viewport.get("client_x", 0) or 0)' in flow_source
    assert "client_x + max(1, width // 2)" in flow_source
    assert 'if "screen_x" in state.viewport' in input_source
    assert 'if "screen_y" in state.viewport' in input_source


def test_topology_evidence_waits_for_final_gpu_shrink_frame() -> None:
    def event(partial: int, live: int) -> dict[str, object]:
        return {
            "event": "metrics",
            "renderer": {"geometry_resources": {"partial_topology_rebuilds": partial, "live_geometry_batches": live}},
        }

    state = SimpleNamespace(tab=SimpleNamespace(standalone_dotnet_protocol_events=[event(3, 4), event(4, 3)]))

    assert _latest_settled_topology_metrics(state, 0, partial_rebuild_floor=4, live_batch_count=3) == event(4, 3)
    assert _latest_settled_topology_metrics(state, 0, partial_rebuild_floor=5, live_batch_count=3) == {}

    capped = [event(3, 4)] * 255 + [event(4, 3)]
    state.tab.standalone_dotnet_protocol_events = capped
    assert _latest_settled_topology_metrics(state, 256, partial_rebuild_floor=4, live_batch_count=3) == event(4, 3)


def test_texture_mip_evidence_joins_on_canonical_resident_resource_id() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "tools" / "mesh_harness" / "real_dotnet_flow.py"
    ).read_text(encoding="utf-8")

    assert 'resource_id = str(getattr(state, "painted_resource_id", "") or binding.mesh_resource_id or "")' in source


def test_stroke_geometry_gate_is_frozen_before_later_workflow_edits() -> None:
    from tools.mesh_harness.real_dotnet import _record_stroke_geometry_evidence

    mesh = SimpleNamespace(
        submeshes=[SimpleNamespace(vertices=[(1.0, 0.0, 0.0), (0.0, 0.0, 0.0)])]
    )
    state = SimpleNamespace(
        controller=SimpleNamespace(working_mesh=lambda clone: mesh),
        original_vertex_positions=(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),),
        submesh_index=0,
        face_vertices=[0],
    )

    _record_stroke_geometry_evidence(state)
    mesh.submeshes[0].vertices[1] = (2.0, 0.0, 0.0)

    assert state.changed_vertex_keys == {(0, 0)}
    assert state.changed_only_selected_geometry is True


def test_dotnet_real_game_resident_material_gates_require_reuse_and_one_process() -> None:
    before_counts = {
        "initial_package_build_count": 1,
        "package_build_count": 1,
        "renderer_process_start_count": 1,
        "process_restart_count": 0,
        "full_reload_count": 0,
        "material_state_update_count": 0,
        "material_state_applied_count": 0,
        "material_state_failed_count": 0,
    }
    after_counts = dict(
        before_counts,
        material_state_update_count=2,
        material_state_applied_count=2,
    )
    resources = {"texture_srv_creates": 3, "texture_srv_disposals": 0, "texture_srv_reuses": 0, "live_texture_srvs": 3}
    payloads = (
        {"generation": 1, "edit_revision": 7, "material_signature": "sig", "resources": [{"resource_id": "r"}]},
        {"generation": 2, "edit_revision": 7, "material_signature": "sig", "resources": [{"resource_id": "r"}]},
    )
    applied_events = (
        {
            "event": "material_state_applied",
            "generation": 1,
            "edit_revision": 7,
            "renderer": {"material_generation": 1},
        },
        {
            "event": "material_state_applied",
            "generation": 2,
            "edit_revision": 7,
            "material_signature": "sig",
            "decoded_resources": 0,
            "reused_resources": 1,
            "renderer": {
                "material_generation": 2,
                "last_requested_material_generation": 2,
                "last_applied_material_generation": 2,
            },
        },
    )
    state = SimpleNamespace(
        material_state_payloads=payloads,
        material_state_applied_events=applied_events,
        material_state_payload=payloads[-1],
        material_state_applied=applied_events[-1],
        material_lifecycle_before=before_counts,
        material_lifecycle_after=after_counts,
        material_resource_metrics_before=resources,
        material_resource_metrics_after=dict(resources, texture_srv_reuses=3),
        material_process_pid_before=77,
        material_process_pid_after=77,
        material_window_identity_before={"form_hwnd": 10, "viewport_hwnd": 11},
        material_window_identity_after={"form_hwnd": 10, "viewport_hwnd": 11},
        material_dedup_ok=True,
    )

    assert all(resident_material_gates(state).values())

    state.material_dedup_ok = False
    assert resident_material_gates(state)["resident_material_dedup_respected"] is False
    state.material_dedup_ok = True

    state.material_process_pid_after = 78
    state.material_lifecycle_after = dict(after_counts, package_build_count=2)
    state.material_resource_metrics_after = dict(resources, texture_srv_creates=4)
    failed = resident_material_gates(state)
    assert failed["resident_material_process_unchanged"] is False
    assert failed["resident_material_no_package_rebuild"] is False
    assert failed["resident_material_srv_reused"] is False

    state.material_state_applied_events = (applied_events[0], dict(applied_events[-1], generation=1))
    assert resident_material_gates(state)["resident_material_generation_ordered"] is False


def test_dotnet_real_game_sends_material_state_before_selection_and_stroke() -> None:
    source = (Path(__file__).resolve().parents[1] / "tools" / "mesh_harness" / "real_dotnet.py").read_text(
        encoding="utf-8"
    )
    material_source = (
        Path(__file__).resolve().parents[1] / "tools" / "mesh_harness" / "real_dotnet_material.py"
    ).read_text(encoding="utf-8")

    assert "mesh_dotnet_material_state_payload(" in material_source
    assert 'state.tab._send_dotnet_material_state(reason="real_archive_harness")' in material_source
    assert 'state.tab._send_dotnet_material_state(reason="real_archive_harness_same_revision")' in material_source
    assert '"part_selection_optional": bool(' in source
    assert "state.initial_part_selection_empty and state.face_selection_keeps_part_unselected" in source
    run = source[source.index("def run_real_archive_mesh_editor_dotnet_edit_smoke(") :]
    offscreen_capture = run.index("exercise_deterministic_offscreen_capture(")
    state_update = run.index("exercise_resident_material_update(")
    builder_presentation = run.index("exercise_builder_presentation_controls(")
    geometry_display = run.index("exercise_geometry_display_modes(")
    selection = run.index("_configure_selection_and_projection(state)")
    transform = run.index("_drive_viewport_stroke(state)")
    parameter_update = run.index("exercise_material_parameter_update(")
    texture_update = run.index("exercise_linked_texture_strokes(")
    topology = run.index("exercise_assignment_and_mesh_edits(")
    export = run.index("exercise_coherent_export(")
    assert state_update < offscreen_capture < builder_presentation < geometry_display < selection < transform < parameter_update < texture_update < topology < export
    capture_source = (
        Path(__file__).resolve().parents[1] / "tools" / "mesh_harness" / "real_dotnet_capture.py"
    ).read_text(encoding="utf-8")
    assert "request_resident_dotnet_icon_capture" in capture_source
    assert 'rows[0]["sha256"] == rows[1]["sha256"]' in capture_source
    assert 'not row["visible_view_mutated"]' in capture_source
    flow_source = (
        Path(__file__).resolve().parents[1] / "tools" / "mesh_harness" / "real_dotnet_flow.py"
    ).read_text(encoding="utf-8")
    topology_flow = flow_source.split("def exercise_assignment_and_mesh_edits", maxsplit=1)[1].split(
        "def exercise_coherent_export", maxsplit=1
    )[0]
    assert "_send_dotnet_native_update(update)" in topology_flow
    assert "_apply_standalone_native_update(update)" not in topology_flow
    package_source = (
        Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "mesh_editor" / "tab_packages.py"
    ).read_text(encoding="utf-8")
    assert "controller = self.standalone_controller or self._dotnet_target_controller()" in package_source


def test_real_dotnet_geometry_color_guard_rejects_black_and_accepts_lit_faces(tmp_path: Path) -> None:
    from PIL import Image

    black = tmp_path / "black.png"
    lit = tmp_path / "lit.png"
    Image.new("RGB", (128, 128), (18, 20, 25)).save(black)
    image = Image.new("RGB", (128, 128), (18, 20, 25))
    for y in range(24, 104):
        for x in range(32, 96):
            image.putpixel((x, y), (125, 142, 164))
    image.save(lit)

    assert _image_color_metrics(black)["non_black_geometry"] is False
    assert _image_color_metrics(lit)["non_black_geometry"] is True


def test_real_dotnet_proof_requires_textured_faces_without_textures_and_vertices() -> None:
    exercised = {mode for mode, _capture_name in _DISPLAY_MODES}

    assert _REQUIRED_PRODUCTION_DISPLAY_MODES <= exercised
    assert {_DISPLAY_MODE_LABELS[mode] for mode in _REQUIRED_PRODUCTION_DISPLAY_MODES} == {
        "Solid (Textured)",
        "Faces (No Textures)",
        "Vertices",
    }
    assert _DISPLAY_MODES[-1][0] == "textured"


def test_real_assignment_preserves_source_dds_format_and_mips(tmp_path: Path) -> None:
    from tools.mesh_harness.real_dotnet_flow import _encode_painted_assignment

    painted = tmp_path / "painted.png"
    painted.write_bytes(b"png")
    source = tmp_path / "source.dds"
    source.write_bytes(b"dds")
    state = SimpleNamespace(
        output_dir=tmp_path,
        painted_composite_path=painted,
        texture_flow_evidence={"dimensions": [2048, 2048], "source_path": str(source)},
    )
    captured: dict[str, object] = {}

    def encode(_input: Path, output: Path, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        output.write_bytes(b"encoded")
        return {"status": "encoded", "format": "DXGI_FORMAT_BC1_UNORM"}

    with (
        patch(
            "cdmw.core.dds_native.inspect_dds_native_path",
            return_value=SimpleNamespace(width=2048, height=2048, format_name="BC1_UNORM", mip_count=12),
        ),
        patch("cdmw.core.texture_native.encode_dds_with_directxtex", side_effect=encode),
    ):
        assigned, error = _encode_painted_assignment(state)

    assert error == ""
    assert assigned == tmp_path / "assigned-real-texture.dds"
    assert captured["dds_format"] == "BC1_UNORM"
    assert captured["mip_count"] == 12
    assert state.assignment_encode_report["source_format_preserved"] is True


def test_production_flow_is_ordered_and_gated_by_real_lifecycle_evidence() -> None:
    class Process:
        @staticmethod
        def processId() -> int:
            return 41

    tab = SimpleNamespace(
        standalone_dotnet_editor_process=Process(),
        standalone_dotnet_lifecycle_counts={
            "renderer_process_start_count": 1,
            "process_restart_count": 0,
            "initial_package_build_count": 1,
            "package_build_count": 1,
            "full_reload_count": 0,
        },
    )
    state = SimpleNamespace(
        production_flow=[],
        production_process_pid=41,
        production_window_identity={"form_hwnd": 10, "viewport_hwnd": 11},
        final_window_identity={"form_hwnd": 10, "viewport_hwnd": 11},
        form_hwnd=10,
        viewport_hwnd=11,
        tab=tab,
        texture_flow_evidence={
            "updates_applied": True,
            "queue_bounded": True,
            "copy_on_write_once": True,
            "mip_chain_preserved": True,
            "snapshot_pixels_match": True,
            "assignment_in_snapshot": True,
            "assignment_exported": True,
            "painted_derivative_exported": True,
        },
        export_flow_evidence={
            "coherent_snapshot": True,
            "source_asset_hash_matches": True,
            "output_reparse_status": "passed",
            "artifact_hashes_present": True,
        },
        edit_flow_evidence={"affected_only_updates": True},
        edit_flow_ok=True,
    )
    for step in PRODUCTION_FLOW_STEPS:
        record_flow_step(state, step)

    assert all(production_flow_gates(state).values())


def test_production_flow_rejects_skips_and_evidence_preserves_new_sections() -> None:
    state = SimpleNamespace(production_flow=[])
    record_flow_step(state, "ready")
    try:
        record_flow_step(state, "transform")
    except RuntimeError as exc:
        assert "expected select" in str(exc)
    else:
        raise AssertionError("out-of-order production flow was accepted")

    proof = {
        "ok": True,
        "production_flow": [{"step": "ready", "ok": True}],
        "linked_texture_updates": {"updates_applied": True},
        "resident_mesh_edits": {"affected_only_updates": True},
        "resident_export": {"output_reparse_status": "passed"},
        "lifecycle_counts": {"renderer_process_start_count": 1},
        "process_identity": {"initial_pid": 4, "final_pid": 4},
        "gates": {"production_flow_complete": True},
    }
    evidence = _real_game_mesh_evidence(proof)

    assert evidence["production_flow"] == proof["production_flow"]
    assert evidence["linked_texture_updates"] == proof["linked_texture_updates"]
    assert evidence["resident_mesh_edits"] == proof["resident_mesh_edits"]
    assert evidence["resident_export"] == proof["resident_export"]
    assert evidence["process_identity"] == proof["process_identity"]


def test_canonical_real_dotnet_runner_drives_extended_flow_without_legacy_renderer(tmp_path: Path) -> None:
    from tools.mesh_harness.real_dotnet import run_real_archive_mesh_editor_dotnet_edit_smoke

    calls: list[str] = []

    class Process:
        @staticmethod
        def processId() -> int:
            return 73

    tab = SimpleNamespace(
        standalone_dotnet_editor_process=Process(),
        _stop_standalone_dotnet_editor_process=lambda: None,
        _standalone_dotnet_editor_process_running=lambda: False,
        deleteLater=lambda: None,
    )
    controller = SimpleNamespace(close_active_session=lambda: None)
    app = SimpleNamespace(processEvents=lambda: None)
    state = SimpleNamespace(
        game_root=tmp_path / "game",
        output_dir=tmp_path / "output",
        production_flow=[],
        tab=None,
        controller=None,
        heartbeat_timer=None,
        process=None,
    )

    def start(target: SimpleNamespace) -> None:
        calls.append("ready")
        target.tab = tab
        target.controller = controller
        target.app = app
        target.submesh_index = 0
        target.selected_faces = (0,)
        target.stroke_updates = ({"event": "stroke_update"},)
        record_flow_step(target, "ready")

    def resident(_state: SimpleNamespace, **_kwargs: object) -> None:
        calls.append("resident_material")

    def select(_state: SimpleNamespace) -> None:
        calls.append("select")

    def transform(_state: SimpleNamespace) -> None:
        calls.append("transform")

    def scalar(target: SimpleNamespace, **_kwargs: object) -> None:
        calls.append("scalar")
        target.material_parameter_payload = {"parameter_generation": 2}

    def flow(name: str):
        def run(_state: SimpleNamespace, **_kwargs: object) -> str:
            calls.append(name)
            return ""

        return run

    with (
        patch("tools.mesh_harness.real_dotnet._prepare_real_asset", return_value=state),
        patch("tools.mesh_harness.real_dotnet._start_embedded_editor", side_effect=start),
        patch(
            "tools.mesh_harness.real_dotnet.exercise_deterministic_offscreen_capture",
            side_effect=lambda *_args, **_kwargs: calls.append("offscreen_capture") or {"ok": True},
        ),
        patch("tools.mesh_harness.real_dotnet.exercise_resident_material_update", side_effect=resident),
        patch(
            "tools.mesh_harness.real_dotnet.exercise_builder_presentation_controls",
            side_effect=flow("builder_presentation"),
        ),
        patch("tools.mesh_harness.real_dotnet.exercise_geometry_display_modes", side_effect=flow("geometry_display")),
        patch("tools.mesh_harness.real_dotnet._configure_selection_and_projection", side_effect=select),
        patch("tools.mesh_harness.real_dotnet._drive_viewport_stroke", side_effect=transform),
        patch(
            "tools.mesh_harness.real_dotnet._record_stroke_geometry_evidence",
            side_effect=lambda _state: calls.append("stroke_evidence"),
        ),
        patch("tools.mesh_harness.real_dotnet.exercise_material_parameter_update", side_effect=scalar),
        patch("tools.mesh_harness.real_dotnet.exercise_linked_texture_strokes", side_effect=flow("texture")),
        patch("tools.mesh_harness.real_dotnet.exercise_assignment_and_mesh_edits", side_effect=flow("mesh_edits")),
        patch("tools.mesh_harness.real_dotnet.exercise_coherent_export", side_effect=flow("export")),
        patch("tools.mesh_harness.real_dotnet._finish_result", return_value={"ok": True, "backend": "dotnet"}),
    ):
        result = run_real_archive_mesh_editor_dotnet_edit_smoke(state.game_root, state.output_dir)

    assert result["ok"] is True
    assert calls == [
        "ready",
        "resident_material",
        "offscreen_capture",
        "builder_presentation",
        "geometry_display",
        "select",
        "transform",
        "stroke_evidence",
        "scalar",
        "texture",
        "mesh_edits",
        "export",
    ]
