from __future__ import annotations
from pathlib import Path
import re
import time
from types import SimpleNamespace
from unittest.mock import patch
from tools.mesh_harness.evidence import _real_game_mesh_evidence
from tools.mesh_harness.real_dotnet_flow import _latest_settled_topology_metrics
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
        "stroke_terminal_coverage": {
            "ok": True,
            "expected_end": [12, 20],
            "reported_end": [12, 20],
        },
        "part_selection": {
            "initially_empty": True,
            "viewport_did_not_select_part": True,
            "mesh_selection_armed": True,
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
    assert evidence["projected_drag"]["terminal_coverage"]["ok"] is True
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
    session_source = (
        root / "tools" / "mesh_harness" / "real_dotnet_session.py"
    ).read_text(encoding="utf-8")
    assert '"_mesh_editor_commit_dotnet_edit_result"' in session_source
    assert '"production_builder_commit_contract_readback"' in session_source
    assert "selection_matches_result_authority" in session_source


def test_real_dotnet_projection_probe_waits_for_v3_renderer_authority() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "tools" / "mesh_harness" / "real_dotnet.py").read_text(
        encoding="utf-8"
    )

    probe = source.split("def _prepare_selection_projection(", 1)[1].split(
        "def _arm_move_and_read_applied_selection", 1
    )[0]
    assert "probe_expected_revision" in probe
    assert "probe_request_id" in probe
    assert '== "resident_mutation_batch_ack"' in probe
    assert '{"applied", "already_applied"}' in probe
    assert 'get("active_revision", 0)' in probe
    assert 'get("pending_depth", 0)' in probe
    assert 'get("rejected_updates", 0)' in probe
    assert probe.index("probe_queue_settled") < probe.index(
        "state.projection_probe_authority_settled"
    )
    selection = source.split("def _drive_projected_vertex_selection(", 1)[1].split(
        "def _capture_selected_projection_state", 1
    )[0]
    assert "if not state.projection_probe_authority_settled:" in selection
    assert "clear_update = state.controller.native_update_for_result(state.select_result)" in selection
    assert "clear_update," in selection
    assert "result=state.select_result" in selection
    assert "_send_dotnet_session_state()" not in selection


def test_real_skin_surface_gate_rejects_wet_highlights(tmp_path: Path) -> None:
    from PIL import Image
    from tools.mesh_harness.real_dotnet_display import _skin_surface_response

    semantics = [{"shader_family": "skin"}]
    matte = Image.new("RGB", (128, 128), (120, 103, 98))
    wet = matte.copy()
    for y in range(32, 96):
        for x in range(32, 96):
            if (x + y) % 5 == 0:
                wet.putpixel((x, y), (210, 185, 178))
    matte_path = tmp_path / "matte.png"
    wet_path = tmp_path / "wet.png"
    matte.save(matte_path)
    wet.save(wet_path)

    assert _skin_surface_response(matte_path, semantics)["ok"] is True
    wet_evidence = _skin_surface_response(wet_path, semantics)
    assert wet_evidence["ok"] is False
    assert wet_evidence["gates"]["skin_hot_highlight_fraction_bounded"] is False


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
        patch("tools.mesh_harness.real_dotnet_capture._show_window_without_activation", return_value=False),
        patch("tools.mesh_harness.real_dotnet_capture._restore_window_z_order"),
        patch("tools.mesh_harness.real_dotnet_capture._window_at_screen_point", return_value=99),
        patch("tools.mesh_harness.real_dotnet_capture._window_process_id", return_value=100),
    ):
        result = capture_dotnet_viewport(state, output)

    assert result["ok"] is False
    assert "visible owned capture target" in str(result["error"])
    assert result["foreground_activated"] is False
    assert not output.exists()


def test_real_dotnet_stroke_never_sends_scoped_input_without_visible_process_ownership(tmp_path: Path) -> None:
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
        patch("tools.mesh_harness.real_dotnet_input._show_window_without_activation", return_value=False),
        patch("tools.mesh_harness.real_dotnet_input._scoped_input_target_matches", return_value=False),
        patch("tools.mesh_harness.real_dotnet_input._send_mouse_message") as send_message,
        # _drive_viewport_stroke and the helpers it resolves now live in
        # real_dotnet_evidence; patching them on real_dotnet would no longer
        # intercept, and the stroke would run for real.
        patch("tools.mesh_harness.real_dotnet_evidence._pump_for"),
        patch("tools.mesh_harness.real_dotnet_evidence._pump_until", return_value=True),
        patch("tools.mesh_harness.real_dotnet_evidence._capture_viewport", return_value={"ok": False}),
        patch(
            "tools.mesh_harness.real_dotnet_evidence._base_error",
            side_effect=lambda _state, message: {"error": message},
        ),
    ):
        result = _drive_viewport_stroke(state)

    assert result == {
        "error": "The .NET viewport was not an owned scoped input target with a live rectangle."
    }
    send_message.assert_not_called()


def test_real_dotnet_stroke_accepts_bounded_updates_and_requires_terminal_coverage(
    tmp_path: Path,
) -> None:
    from tools.mesh_harness.real_dotnet_input import drive_viewport_stroke

    events: list[dict[str, object]] = []
    state = SimpleNamespace(
        viewport={"width": 100, "height": 100, "screen_x": 0, "screen_y": 0},
        projected_center=(20.0, 20.0),
        viewport_hwnd=10,
        form_hwnd=11,
        production_process_pid=42,
        heartbeat_ms=[],
        heartbeat_started=time.perf_counter(),
        tab=SimpleNamespace(
            standalone_dotnet_protocol_events=events,
            standalone_live_stroke_dispatcher=SimpleNamespace(
                metrics=lambda: {"queue_depth": 0, "control_depth": 0, "active": 0}
            ),
            standalone_dotnet_update_queue=SimpleNamespace(
                metrics=lambda: {"active_revision": 0}
            ),
        ),
        after_capture_path=tmp_path / "after.png",
    )
    move_calls = 0

    def send_message(_hwnd: int, message: int, _x: int, _y: int, *, wparam: int = 0) -> bool:
        nonlocal move_calls
        if message == 0x0200:
            move_calls += 1
        if move_calls in {10, 25} and message == 0x0200:
            events.append({"event": "stroke_update", "request_id": move_calls})
        return True

    def wait_event(
        _state: SimpleNamespace,
        event: str,
        _cursor: int,
        _timeout: float,
    ) -> dict[str, object]:
        if event == "stroke_begin":
            return {"event": event}
        if event == "stroke_end":
            return {
                "event": event,
                "screen_drag": {"end_x": 60, "end_y": 20},
            }
        return {}

    with (
        patch("tools.mesh_harness.real_dotnet_input._host_window_rect", return_value=(0, 0, 100, 100)),
        patch("tools.mesh_harness.real_dotnet_input._show_window_without_activation", return_value=True),
        patch("tools.mesh_harness.real_dotnet_input._scoped_input_target_matches", return_value=True),
        patch("tools.mesh_harness.real_dotnet_input._window_process_id", return_value=42),
        patch("tools.mesh_harness.real_dotnet_input._send_mouse_message", side_effect=send_message),
    ):
        result = drive_viewport_stroke(
            state,
            base_error=lambda _state, message: {"error": message},
            pump_for=lambda *_args: None,
            pump_until=lambda _state, predicate, _timeout: bool(predicate()),
            wait_protocol_event=wait_event,
            capture_viewport=lambda *_args: {"ok": True},
        )

    assert result is None
    assert len(state.mouse_drag_points) == 40
    assert len(state.stroke_updates) == 2
    assert state.stroke_terminal_coverage == {
        "requested_end": [60, 20],
        "expected_end": [60, 20],
        "reported_end": [60, 20],
        "injected_client_end": [60, 20],
        "target_screen_end": [60, 20],
        "viewport_rect_at_release": [0, 0, 100, 100],
        "viewport_stationary_to_release": True,
        "protocol_update_count": 2,
        "input_point_count": 40,
        "ok": True,
    }


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
    assert state.unexpected_changed_vertex_keys == set()
    assert state.changed_only_selected_geometry is True


def test_stroke_geometry_gate_uses_the_full_authoritative_multisubmesh_selection() -> None:
    from tools.mesh_harness.real_dotnet import _record_stroke_geometry_evidence

    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[(1.0, 0.0, 0.0), (0.0, 0.0, 0.0)]),
            SimpleNamespace(vertices=[(2.0, 0.0, 0.0), (0.0, 0.0, 0.0)]),
        ]
    )
    state = SimpleNamespace(
        controller=SimpleNamespace(working_mesh=lambda clone: mesh),
        original_vertex_positions=(
            ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        ),
        submesh_index=0,
        face_vertices=[0],
        selected_vertex_keys={(0, 0), (1, 0)},
    )

    _record_stroke_geometry_evidence(state)

    assert state.changed_vertex_keys == {(0, 0), (1, 0)}
    assert state.unexpected_changed_vertex_keys == set()
    assert state.changed_only_selected_geometry is True


def test_real_pac_move_adopts_the_frontmost_authoritative_submesh(
    monkeypatch,
) -> None:
    from tools.mesh_harness import real_dotnet

    submesh = SimpleNamespace(
        vertices=[
            (0.0, 0.0, 0.0),
            (3.0, 0.0, 0.0),
            (0.0, 3.0, 0.0),
            (1000.0, 0.0, 0.0),
            (1003.0, 0.0, 0.0),
            (1000.0, 3.0, 0.0),
        ],
        faces=[(0, 1, 2), (3, 4, 5)],
    )
    frontmost_submesh = SimpleNamespace(
        vertices=[
            (10.0, 0.0, 0.0),
            (13.0, 0.0, 0.0),
            (10.0, 3.0, 0.0),
        ],
        faces=[(0, 1, 2)],
    )
    projected_world_points: list[tuple[float, float, float]] = []
    tool_state_events = iter(
        (
            {
                "local_selection": {
                    "source_indices": [],
                    "vertices_by_submesh": {},
                },
                "selected_part_index": -1,
                "parts_list_selected_index": -1,
            },
            {
                "local_selection": {
                    "source_indices": [],
                    "vertices_by_submesh": {},
                },
                "selected_part_index": -1,
                "parts_list_selected_index": -1,
            },
            {
                "local_selection": {
                    "source_indices": [],
                    "target_mode": "vertex",
                    "vertices_by_submesh": {"1": [0, 1, 2]},
                },
                "selected_part_index": -1,
                "parts_list_selected_index": -1,
                "parts_list_selected_indices": [],
            },
        )
    )
    protocol_events = {
        "select_request": {
            "screen_brush": {
                "world_view_projection": [1.0] * 16,
                "viewport_width": 100,
                "viewport_height": 100,
            }
        },
    }
    select_calls: list[dict[str, object]] = []
    physical_points: list[tuple[float, float]] = []
    standalone_events: list[dict[str, object]] = []
    state = SimpleNamespace(
        submesh=submesh,
        submesh_index=0,
            controller=SimpleNamespace(
                select=lambda **kwargs: select_calls.append(dict(kwargs)) or SimpleNamespace(ok=True),
                native_update_for_result=lambda result: result,
                session_view=lambda: SimpleNamespace(resident_revision=1),
                working_mesh=lambda *, clone: SimpleNamespace(
                    submeshes=[submesh, frontmost_submesh]
                ),
        ),
        tab=SimpleNamespace(
            standalone_dotnet_protocol_events=standalone_events,
            _send_dotnet_session_state=lambda: None,
                _send_dotnet_native_update=lambda _update, **_kwargs: standalone_events.append(
                    {
                        "event": "resident_mutation_batch_ack",
                        "target_revision": 1,
                        "status": "applied",
                    }
                ) or True,
                _send_dotnet_protocol_message=lambda _payload: True,
                _standalone_action_worker_active=lambda: False,
                standalone_dotnet_update_queue=SimpleNamespace(
                    metrics=lambda: {
                        "active_revision": 0,
                        "pending_depth": 0,
                        "last_acked_revision": 1,
                        "rejected_updates": 0,
                    }
                ),
            ),
        viewport={
            "width": 100,
            "height": 100,
            "client_x": 0,
            "client_y": 0,
        },
        viewport_hwnd=101,
        selected_before_capture_path=Path("selected-before.png"),
    )

    monkeypatch.setattr(real_dotnet, "refresh_editable_viewport_rectangle", lambda *_args: {})
    monkeypatch.setattr(real_dotnet, "_send_mouse_message", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        real_dotnet,
        "_wait_protocol_event",
        lambda _state, event, _cursor, _timeout: (
            next(tool_state_events) if event == "tool_state_applied" else protocol_events[event]
        ),
    )
    monkeypatch.setattr(real_dotnet, "_host_window_rect", lambda _hwnd: (0, 0, 100, 100))
    monkeypatch.setattr(real_dotnet, "_projected_face_cluster_for_drag", lambda *_args, **_kwargs: (0,))
    monkeypatch.setattr(
        real_dotnet,
        "_front_facing_vertex_selection_anchor",
        lambda *_args, **_kwargs: (0, 1, (50.0, 50.0)),
    )
    monkeypatch.setattr(
        real_dotnet,
        "_project_world_to_screen",
        lambda _matrix, point, **_kwargs: projected_world_points.append(tuple(point)) or (50.0, 50.0),
    )
    monkeypatch.setattr(real_dotnet, "_pump_for", lambda *_args: None)
    monkeypatch.setattr(real_dotnet, "_pump_until", lambda *_args: True)
    monkeypatch.setattr(real_dotnet, "_capture_viewport", lambda *_args: {})
    monkeypatch.setattr(
        real_dotnet,
        "drive_viewport_selection",
        lambda _state, *, point, **_kwargs: physical_points.append(tuple(point))
        or {"ok": True, "select_request_count": 2},
    )

    error = real_dotnet._configure_selection_and_projection(state)

    assert error is None
    assert state.face_vertices == [0, 1, 2]
    assert state.selected_vertex_keys == {(1, 0), (1, 1), (1, 2)}
    assert state.projection_seed_submesh_index == 0
    assert state.submesh_index == 1
    assert state.submesh is frontmost_submesh
    assert len(state.before_vertices) == 3
    assert state.projected_anchor_faces == (0,)
    assert projected_world_points == [(11.0, 1.0, 0.0)]
    assert physical_points == [(50.0, 50.0)]
    assert select_calls == [
        {"operation": "replace"},
    ]
    assert state.part_selection_remained_empty is True
    assert state.viewport_mesh_selection_armed is True


def test_input_selection_anchor_targets_an_exact_front_facing_vertex() -> None:
    from tools.mesh_harness.real_dotnet import _front_facing_vertex_selection_anchor

    submesh = SimpleNamespace(
        vertices=[(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.0, 0.5, 0.0)],
        faces=[(0, 1, 2)],
    )
    anchor = _front_facing_vertex_selection_anchor(
        submesh,
        tuple(
            (
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0,
            )
        ),
        viewport_width=100.0,
        viewport_height=100.0,
    )

    assert anchor == (0, 0, (25.0, 75.0))


def test_real_dotnet_harness_selects_requested_monitor_without_cursor_input(
    monkeypatch,
) -> None:
    from tools.mesh_harness.real_dotnet_session import _proof_screen

    screens = [
        SimpleNamespace(name=lambda: "Primary"),
        SimpleNamespace(name=lambda: "Monitor 1"),
    ]
    app = SimpleNamespace(primaryScreen=lambda: screens[0], screens=lambda: screens)
    monkeypatch.setenv("CDMW_HARNESS_SCREEN", "1")

    assert _proof_screen(app) is screens[1]


def test_desktop_input_gate_allows_user_activity_only_outside_the_harness_screen(
    monkeypatch,
) -> None:
    import tools.mesh_harness.win32_input as win32_input

    monkeypatch.setattr(
        win32_input,
        "os",
        SimpleNamespace(name="posix"),
    )
    safe = win32_input._desktop_input_isolation_evidence(
        [
            {"available": True, "foreground_hwnd": 41, "cursor": [120, 340]},
            {"available": True, "foreground_hwnd": 42, "cursor": [121, 340]},
        ],
        forbidden_hwnds=(101, 102),
        harness_screen_bounds=(-1920, 0, 0, 1080),
    )
    cursor_violation = win32_input._desktop_input_isolation_evidence(
        [{"available": True, "foreground_hwnd": 41, "cursor": [-400, 340]}],
        forbidden_hwnds=(101, 102),
        harness_screen_bounds=(-1920, 0, 0, 1080),
    )

    assert safe["ok"] is True
    assert safe["observation_count"] == 2
    assert cursor_violation["ok"] is False
    assert cursor_violation["cursor_on_harness_screen_count"] == 1


def test_harness_has_no_global_mouse_or_focus_mutation_api() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (Path("tools/mesh_harness")).glob("*.py")
    )

    for forbidden in (
        "SetCursorPos",
        "SendInput",
        "mouse_event",
        "SetForegroundWindow",
        "SetActiveWindow",
        "SetFocus",
        "BringWindowToTop",
    ):
        assert forbidden not in source


def test_scoped_select_gesture_emits_helper_selection_and_waits_for_authority() -> None:
    from tools.mesh_harness.real_dotnet_input import drive_viewport_selection

    button = {"down": False}
    state = SimpleNamespace(
        viewport={"width": 100, "height": 100, "screen_x": 10, "screen_y": 20},
        viewport_hwnd=101,
        production_process_pid=77,
        form_hwnd=100,
        tab=SimpleNamespace(
            standalone_dotnet_protocol_events=[],
            _standalone_action_worker_active=lambda: False,
            standalone_dotnet_update_queue=SimpleNamespace(
                metrics=lambda: {"active_revision": 0, "pending_depth": 0}
            ),
        ),
    )

    def send_message(
        _hwnd: int,
        message: int,
        _x: int,
        _y: int,
        *,
        wparam: int = 0,
    ) -> bool:
        was_down = button["down"]
        if message == 0x0201:
            button["down"] = True
        elif message == 0x0202:
            button["down"] = False
        if was_down and message == 0x0202:
            state.tab.standalone_dotnet_protocol_events.append(
                {
                    "event": "select_request",
                    "target_mode": "vertex",
                    "phase": "end",
                    "request_id": 9,
                }
            )
            state.tab.standalone_dotnet_protocol_events.append(
                {
                    "event": "resident_mutation_batch_ack",
                    "request_id": 9,
                    "status": "applied",
                }
            )
        return True

    def pump_for(_state, _seconds: float) -> None:
        if button["down"] and not state.tab.standalone_dotnet_protocol_events:
            state.tab.standalone_dotnet_protocol_events.append(
                {"event": "select_request", "target_mode": "vertex", "paint_final": False}
            )

    with (
        patch("tools.mesh_harness.real_dotnet_input._host_window_rect", return_value=(10, 20, 110, 120)),
        patch("tools.mesh_harness.real_dotnet_input._show_window_without_activation", return_value=True),
        patch("tools.mesh_harness.real_dotnet_input._scoped_input_target_matches", return_value=True),
        patch("tools.mesh_harness.real_dotnet_input._window_process_id", return_value=77),
        patch("tools.mesh_harness.real_dotnet_input._send_mouse_message", side_effect=send_message),
    ):
        result = drive_viewport_selection(
            state,
            point=(50.0, 50.0),
            pump_for=pump_for,
            pump_until=lambda _state, predicate, _timeout: predicate(),
        )

    assert result["ok"] is True
    assert result["backend"] == "scoped_hwnd_messages_normalized_input"
    assert result["start"] == [50, 50]
    assert result["end"] == [58, 50]
    assert result["select_request_count"] == 2
    assert result["authority_acknowledgement"]["request_id"] == 9
    assert result["authority_settled"] is True
