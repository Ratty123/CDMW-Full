from __future__ import annotations
from collections.abc import Mapping
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


def _resident_projection_status() -> dict[str, object]:
    return {
        "native_interaction": {
            "selection_projection": {
                "world_view_projection": [1.0] * 16,
                "viewport_width": 100,
                "viewport_height": 100,
                "source_submesh_indices": [0, 1],
                "source_submesh_world_view_projections": [],
                "pane_bounds_diagnostics": {},
            }
        }
    }


def _resident_projection_protocol_waiter(tool_state_events, standalone_events):
    def wait_protocol_event(_state, event, _cursor, _timeout):
        if event == "tool_state_applied":
            return next(tool_state_events)
        assert event == "resident_interaction_transaction"
        transaction = {"event": event, "request_id": 9}
        standalone_events.append(transaction)
        return transaction

    return wait_protocol_event


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
            "injected_client_end": [12, 20],
            "terminal_transaction_count": 1,
            "correlated_acknowledgement_count": 1,
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

    probe = source.split("def _drive_projection_probe(", 1)[1].split(
        "def _prepare_selection_projection", 1
    )[0]
    projection = source.split("def _prepare_selection_projection(", 1)[1].split(
        "def _arm_move_and_read_applied_selection", 1
    )[0]
    assert "expected_revision" in probe
    assert "request_id" in probe
    assert "request_resident_interaction_probe(" in probe
    assert 'mode="select_brush_vertex"' in probe
    assert '== "applied"' in probe
    assert "helper_originated_mutation_echo_count" in probe
    assert 'result.get("authority_settled")' in probe
    assert 'get("rejected_updates", 0)' in probe
    assert probe.index("queue_settled") < probe.index(
        "state.projection_probe_authority_settled"
    )
    assert "request_full_renderer_status" in projection
    assert "_selection_projection_from_renderer_status" in projection
    assert '"select_request"' not in probe
    assert '"select_request"' not in projection
    selection = source.split("def _drive_projected_vertex_selection(", 1)[1].split(
        "def _capture_selected_projection_state", 1
    )[0]
    assert "if not state.projection_probe_authority_settled:" in selection
    assert "state.physical_select_gesture = dict(result)" in probe
    assert '"resident_probe_selection_is_authoritative"' in probe
    assert "_send_dotnet_native_update(" not in selection
    assert "resident_mutation_batch_ack" not in selection
    assert "_send_dotnet_session_state()" not in selection


def test_renderer_status_projection_prefers_the_seed_submesh_override() -> None:
    from tools.mesh_harness.real_dotnet_report import (
        _selection_projection_from_renderer_status,
    )

    snapshot = {
        "viewport_width": 320,
        "viewport_height": 180,
        "world_view_projection": [1.0] * 16,
        "source_submesh_indices": [1, 3],
        "source_submesh_world_view_projections": [
            {"source_submesh_index": 1, "world_view_projection": [2.0] * 16},
            {"source_submesh_index": 3, "world_view_projection": [3.0] * 16},
        ],
        "pane_bounds_diagnostics": {"active": "edit"},
    }
    renderer = {"native_interaction": {"selection_projection": snapshot}}

    projection = _selection_projection_from_renderer_status(
        renderer,
        source_submesh_index=3,
    )

    assert projection is not None
    captured, matrix, width, height = projection
    assert captured == snapshot
    assert matrix == (3.0,) * 16
    assert (width, height) == (320.0, 180.0)


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
        patch("tools.mesh_harness.real_dotnet_capture._top_level_window_hwnd", return_value=77),
        patch("tools.mesh_harness.real_dotnet_capture._show_window_without_activation", return_value=False),
        patch("tools.mesh_harness.real_dotnet_capture._restore_window_z_order") as restore,
        patch("tools.mesh_harness.real_dotnet_capture._window_at_screen_point", return_value=99),
        patch("tools.mesh_harness.real_dotnet_capture._window_process_id", return_value=100),
    ):
        result = capture_dotnet_viewport(state, output)

    assert result["ok"] is False
    assert "visible owned capture target" in str(result["error"])
    assert result["foreground_activated"] is False
    assert result["host_shown_without_activation"] is False
    assert result["viewport_shown_without_activation"] is False
    assert result["harness_widget_hwnd"] == 12
    assert result["harness_root_hwnd"] == 77
    restore.assert_called_once_with(77)
    assert not output.exists()


def test_top_level_window_hwnd_uses_ga_root_without_activation() -> None:
    from tools.mesh_harness import win32_input

    user32 = SimpleNamespace(
        IsWindow=lambda _hwnd: 1,
        GetAncestor=lambda _hwnd, mode: 91 if mode == 2 else 0,
    )
    with (
        patch.object(win32_input.os, "name", "nt"),
        patch.object(win32_input.ctypes, "windll", SimpleNamespace(user32=user32)),
    ):
        assert win32_input._top_level_window_hwnd(12) == 91


def test_scoped_mouse_message_uses_bounded_synchronous_hwnd_dispatch() -> None:
    from tools.mesh_harness import win32_input

    with (
        patch.object(win32_input.os, "name", "nt"),
        patch.object(
            win32_input,
            "_send_control_message",
            return_value=(True, 0),
        ) as send,
        patch.object(win32_input, "_render_surface_input_owner_hwnd", return_value=23),
    ):
        sent = win32_input._send_mouse_message(
            23,
            0x0201,
            17,
            29,
            wparam=1,
        )

    assert sent is True
    send.assert_called_once_with(
        23,
        0x0201,
        wparam=1,
        lparam=(29 << 16) | 17,
    )


def test_render_surface_mouse_messages_route_to_same_bounds_winforms_owner() -> None:
    from tools.mesh_harness import win32_input

    with (
        patch.object(win32_input.os, "name", "nt"),
        patch.object(win32_input, "_window_parent_hwnd", return_value=31),
        patch.object(win32_input, "_window_process_id", return_value=77),
        patch.object(win32_input, "_host_window_rect", return_value=(10, 20, 110, 120)),
    ):
        owner = win32_input._render_surface_input_owner_hwnd(23)

    assert owner == 31


def test_button_click_rejects_a_logically_visible_control_clipped_outside_form() -> None:
    from tools.mesh_harness import win32_input

    control = {
        "hwnd": 23,
        "pid": 42,
        "text": "Viewport",
        "class_name": "WindowsForms10.BUTTON.app.0.141b42a_r8_ad1",
        "visible": True,
        "enabled": True,
        "rect": [40, 1382, 180, 1427],
    }
    with (
        patch.object(win32_input, "_enumerate_child_windows", return_value=(control,)),
        patch.object(win32_input, "_host_window_rect", return_value=(0, 0, 640, 1080)),
        patch.object(win32_input, "_send_control_message") as send,
    ):
        result = win32_input._click_button_by_text(11, "Viewport", expected_pid=42)

    assert result["ok"] is False
    assert result["reason"] == "control_not_reachable"
    assert result["root_rect"] == [0, 0, 640, 1080]
    assert result["matches"][0]["intersects_root"] is False
    send.assert_not_called()


def test_button_click_scrolls_owning_panel_before_pressing_a_clipped_control() -> None:
    from tools.mesh_harness import win32_input

    control_rect = [40, 1382, 180, 1427]
    control = {
        "hwnd": 23,
        "pid": 42,
        "text": "Morph & Refit",
        "class_name": "WindowsForms10.BUTTON.app.0.141b42a_r8_ad1",
        "visible": True,
        "enabled": True,
        "rect": list(control_rect),
    }

    def window_rect(hwnd: int):
        return (0, 0, 640, 1080) if hwnd == 11 else tuple(control_rect)

    def send_message(hwnd: int, message: int, **_kwargs):
        if hwnd == 31 and message == win32_input._WM_VSCROLL:
            control_rect[:] = [40, 880, 180, 925]
        return True, 0

    user32 = SimpleNamespace(IsWindow=lambda _hwnd: 1)
    with (
        patch.object(win32_input.os, "name", "nt"),
        patch.object(win32_input.ctypes, "windll", SimpleNamespace(user32=user32)),
        patch.object(win32_input, "_enumerate_child_windows", return_value=(control,)),
        patch.object(win32_input, "_host_window_rect", side_effect=window_rect),
        patch.object(
            win32_input,
            "_parent_window",
            side_effect=lambda hwnd: 31 if hwnd == 23 else 11 if hwnd == 31 else 0,
        ),
        patch.object(win32_input, "_window_process_id", return_value=42),
        patch.object(win32_input, "_send_control_message", side_effect=send_message) as send,
    ):
        result = win32_input._click_button_by_text(
            11,
            "Morph & Refit",
            expected_pid=42,
            scroll_clipped=True,
        )

    assert result["ok"] is True
    assert result["intersects_root"] is True
    assert result["scroll"]["ok"] is True
    assert result["scroll"]["parent_hwnd"] == 31
    assert send.call_count == 2


def test_show_without_activation_rejects_a_failed_top_level_z_order_change() -> None:
    from tools.mesh_harness import win32_input

    user32 = SimpleNamespace(
        GetWindowLongW=lambda _hwnd, _index: 0,
        ShowWindow=lambda _hwnd, _mode: 1,
        SetWindowPos=lambda *_args: 0,
        IsWindow=lambda _hwnd: 1,
    )
    with (
        patch.object(win32_input.os, "name", "nt"),
        patch.object(win32_input.ctypes, "windll", SimpleNamespace(user32=user32)),
        patch.object(win32_input, "_host_window_rect", return_value=(0, 0, 128, 128)),
    ):
        assert win32_input._show_window_without_activation(12, topmost=True) is False


def test_real_dotnet_stroke_reports_rejected_helper_probe_without_desktop_input(
    tmp_path: Path,
) -> None:
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
            _send_dotnet_protocol_message=lambda _payload: False,
            _standalone_action_worker_active=lambda: False,
            standalone_dotnet_update_queue=SimpleNamespace(metrics=lambda: {"active_revision": 0}),
        ),
        after_capture_path=tmp_path / "after.png",
    )
    with (
        patch("tools.mesh_harness.real_dotnet_input._host_window_rect", return_value=(0, 0, 100, 100)),
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

    assert isinstance(result, dict)
    assert "published no terminal resident interaction transaction" in str(
        result.get("error", "")
    )


def _drive_resident_stroke_case(
    tmp_path: Path,
    terminal_events: list[dict[str, object]],
    commit_ack: dict[str, object] | None = None,
) -> tuple[SimpleNamespace, object, list[dict[str, object]]]:
    from tools.mesh_harness.real_dotnet_input import drive_viewport_stroke

    events: list[dict[str, object]] = []
    sent: list[dict[str, object]] = []

    def send_protocol(payload: Mapping[str, object]) -> bool:
        sent.append(dict(payload))
        events.extend(dict(event) for event in terminal_events)
        events.append(
            {
                "event": "resident_interaction_probe_applied",
                "request_id": int(payload.get("request_id", 0) or 0),
                "status": "applied",
                "ok": True,
            }
        )
        return True
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
            _send_dotnet_protocol_message=send_protocol,
            _standalone_action_worker_active=lambda: False,
            standalone_dotnet_update_queue=SimpleNamespace(
                metrics=lambda: {"active_revision": 0, "pending_depth": 0}
            ),
        ),
        after_capture_path=tmp_path / "after.png",
    )

    def wait_event(
        _state: SimpleNamespace,
        event: str,
        _cursor: int,
        _timeout: float,
    ) -> dict[str, object]:
        assert event == "resident_interaction_transaction"
        return next(
            (dict(item) for item in events[_cursor:] if item.get("event") == event),
            {},
        )

    with (
        patch("tools.mesh_harness.real_dotnet_input._host_window_rect", return_value=(0, 0, 100, 100)),
        patch(
            "tools.mesh_harness.real_dotnet_input.resident_interaction_commit_ack",
            return_value=dict(commit_ack or {}),
        ),
    ):
        result = drive_viewport_stroke(
            state,
            base_error=lambda _state, message: {"error": message},
            pump_for=lambda *_args: None,
            pump_until=lambda _state, predicate, _timeout: bool(predicate()),
            wait_protocol_event=wait_event,
            capture_viewport=lambda *_args: {"ok": True},
        )
    return state, result, sent


def test_real_dotnet_stroke_requires_one_authoritative_terminal_transaction(
    tmp_path: Path,
) -> None:
    transaction = {
        "event": "resident_interaction_transaction",
        "request_id": 9,
        "gesture_id": 44,
        "mapping_name": "Local\\drag",
    }
    acknowledgement = {
        "event": "resident_interaction_commit_ack",
        "request_id": 9,
        "status": "applied",
    }

    state, result, sent = _drive_resident_stroke_case(
        tmp_path,
        [transaction],
        acknowledgement,
    )

    assert result is None
    assert len(state.mouse_drag_points) == 40
    assert len(sent) == 1
    assert sent[0]["event"] == "resident_interaction_probe"
    assert sent[0]["mode"] == "move"
    assert state.stroke_terminal_coverage == {
        "requested_end": [60, 20],
        "effective_end": [60, 20],
        "injected_client_end": [60, 20],
        "target_screen_end": [60, 20],
        "viewport_rect_at_release": [0, 0, 100, 100],
        "viewport_stationary_to_release": True,
        "input_point_count": 40,
        "terminal_transaction_count": 1,
        "terminal_request_id": 9,
        "terminal_gesture_id": 44,
        "correlated_acknowledgement_count": 1,
        "authority_acknowledgement": acknowledgement,
        "action_settled": True,
        "authority_settled": True,
        "ok": True,
    }


def test_real_dotnet_stroke_rejects_missing_duplicate_and_uncorrelated_terminals(
    tmp_path: Path,
) -> None:
    transaction = {"event": "resident_interaction_transaction", "request_id": 9}
    cases = (
        ([], {}, "published no terminal resident interaction transaction"),
        (
            [transaction, transaction],
            {"event": "resident_interaction_commit_ack", "request_id": 9, "status": "applied"},
            "published duplicate terminal resident interaction transactions",
        ),
        (
            [transaction],
            {},
            "was not authoritatively correlated",
        ),
        (
            [transaction],
            {"event": "resident_interaction_commit_ack", "request_id": 9, "status": "rejected"},
            "did not settle with one accepted acknowledgement",
        ),
    )

    for index, (events, acknowledgement, expected) in enumerate(cases):
        _state, result, _sent = _drive_resident_stroke_case(
            tmp_path / str(index),
            list(events),
            dict(acknowledgement),
        )
        assert isinstance(result, dict)
        assert expected in str(result.get("error", ""))


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
    stroke_driver = input_source.split("def _drive_scoped_viewport_stroke(", 1)[1].split(
        "def _settle_viewport_stroke", 1
    )[0]
    assert "request_resident_interaction_probe" in stroke_driver
    assert "_standalone_action_worker_active" in input_source
    assert '"resident_interaction_transaction"' in input_source
    assert '"resident_interaction_commit_ack"' in input_source
    assert '"resident_mutation_batch_ack"' in input_source
    for legacy_event in ("stroke_begin", "stroke_update", "stroke_end"):
        assert f'"{legacy_event}"' not in input_source


def test_commit_v2_ack_is_read_from_the_correlated_host_to_helper_record() -> None:
    from tools.mesh_harness.real_dotnet_input import resident_interaction_commit_ack

    transaction = {
        "session_id": "session-1",
        "process_generation": 2,
        "helper_process_id": 404,
        "request_id": 9,
        "gesture_id": 44,
        "transaction_sequence": 3,
        "sha256": "ab" * 32,
        "base_revision": 6,
        "target_revision": 7,
        "base_selection_revision": 4,
        "target_selection_revision": 5,
        "topology_generation": 1,
    }
    acknowledgement = {
        **transaction,
        "event": "resident_interaction_commit_ack",
        "status": "applied",
        "direction": "host_to_helper",
        "sent": True,
        "monotonic_ns": 201,
        "durable_revision": 7,
        "durable_selection_revision": 5,
    }
    wrong_direction = {**acknowledgement, "direction": "helper_to_host"}
    stale = {**acknowledgement, "monotonic_ns": 99}

    with patch(
        "tools.mesh_harness.real_dotnet_input.mesh_interaction_diagnostics_snapshot",
        return_value={"recent_events": [wrong_direction, stale, acknowledgement]},
    ):
        result = resident_interaction_commit_ack(
            transaction,
            after_monotonic_ns=100,
        )

    assert result == acknowledgement


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


def _frontmost_submesh_pair():
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
    return submesh, frontmost_submesh


def test_real_pac_move_adopts_the_frontmost_authoritative_submesh(
    monkeypatch,
) -> None:
    from tools.mesh_harness import real_dotnet

    submesh, frontmost_submesh = _frontmost_submesh_pair()
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
                    "last_host_selection_push": {"request_id": 9},
                },
                "selected_part_index": -1,
                "parts_list_selected_index": -1,
                "parts_list_selected_indices": [],
            },
        )
    )
    renderer_status = _resident_projection_status()
    probe_starts: list[tuple[int, int]] = []
    standalone_events: list[dict[str, object]] = []
    state = SimpleNamespace(
        submesh=submesh,
        submesh_index=0,
        controller=SimpleNamespace(
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
    monkeypatch.setattr(real_dotnet, "request_full_renderer_status", lambda *_args: renderer_status)
    def resident_probe(*_args, **kwargs):
        probe_starts.append(tuple(kwargs["start"]))
        return {
            "ok": True,
            "request": {"event": "resident_interaction_probe"},
            "resident_interaction_transactions": [
                {"event": "resident_interaction_transaction", "request_id": 9}
            ],
            "authority_acknowledgement": {
                "event": "resident_interaction_commit_ack",
                "request_id": 9,
                "status": "applied",
            },
            "authority_settled": True,
        }

    monkeypatch.setattr(real_dotnet, "request_resident_interaction_probe", resident_probe)

    monkeypatch.setattr(
        real_dotnet,
        "_wait_protocol_event",
        _resident_projection_protocol_waiter(tool_state_events, standalone_events),
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
    monkeypatch.setattr(
        real_dotnet,
        "_pump_until",
        lambda _state, predicate, _timeout: bool(predicate()),
    )
    monkeypatch.setattr(real_dotnet, "_capture_viewport", lambda *_args: {})
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
    assert probe_starts == [(50, 50)]
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


def test_desktop_input_gate_accepts_authorized_transient_input_only_after_restore(
    monkeypatch,
) -> None:
    import tools.mesh_harness.win32_input as win32_input

    monkeypatch.setattr(win32_input, "os", SimpleNamespace(name="posix"))
    evidence = win32_input._desktop_input_isolation_evidence(
        [
            {"available": True, "foreground_hwnd": 41, "cursor": [-400, 340]},
            {"available": True, "foreground_hwnd": 42, "cursor": [120, 340]},
        ],
        forbidden_hwnds=(101, 102),
        harness_screen_bounds=(-1920, 0, 0, 1080),
        allow_transient_harness_input=True,
    )

    assert evidence["ok"] is True
    assert evidence["cursor_on_harness_screen_count"] == 1
    assert evidence["transient_harness_input_allowed"] is True
    assert evidence["restored_at_end"] is True


def test_visible_physical_mouse_driver_restores_cursor_focus_and_button(
    monkeypatch,
) -> None:
    import tools.mesh_harness.win32_input as win32_input

    class FakeUser32:
        def __init__(self) -> None:
            self.cursor = [12, 34]
            self.foreground = 55
            self.mouse_events: list[int] = []

        def SetCursorPos(self, x: int, y: int) -> int:
            self.cursor = [int(x), int(y)]
            return 1

        def SendInput(self, count: int, payload: object, _size: int) -> int:
            self.mouse_events.append(int(payload._obj.mouse.dwFlags))
            return int(count)

        def IsWindow(self, _hwnd: object) -> int:
            return 1

        def GetAncestor(self, hwnd: object, _kind: int) -> int:
            value = int(getattr(hwnd, "value", 0) or 0)
            return 500 if value in {90, 91, 100, 500} else value

        def GetForegroundWindow(self) -> int:
            return self.foreground

        def GetWindowThreadProcessId(self, hwnd: object, _process: object) -> int:
            return int(getattr(hwnd, "value", 0) or 0) + 1000

        def AttachThreadInput(self, *_args: object) -> int:
            return 1

        def SetForegroundWindow(self, hwnd: object) -> int:
            self.foreground = int(getattr(hwnd, "value", 0) or 0)
            return 1

        def SetFocus(self, _hwnd: object) -> int:
            return 1

    class FakeKernel32:
        def GetCurrentThreadId(self) -> int:
            return 2000

    user32 = FakeUser32()
    monkeypatch.setattr(win32_input, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        win32_input.ctypes,
        "windll",
        SimpleNamespace(user32=user32, kernel32=FakeKernel32()),
    )
    monkeypatch.setattr(win32_input, "_host_window_rect", lambda _hwnd: (100, 200, 500, 600))
    monkeypatch.setattr(win32_input, "_render_surface_input_owner_hwnd", lambda _hwnd: 90)
    monkeypatch.setattr(win32_input, "_window_process_id", lambda _hwnd: 777)
    monkeypatch.setattr(win32_input, "_scoped_input_target_matches", lambda *_args: True)
    monkeypatch.setattr(win32_input, "_window_at_screen_point", lambda *_args: 91)
    monkeypatch.setattr(win32_input, "_window_is_same_or_child", lambda *_args: True)
    monkeypatch.setattr(
        win32_input,
        "_desktop_input_snapshot",
        lambda: {
            "available": True,
            "foreground_hwnd": user32.foreground,
            "cursor": list(user32.cursor),
        },
    )
    monkeypatch.setattr(win32_input, "_physical_mouse_state", None)
    monkeypatch.setattr(win32_input, "_physical_mouse_gesture_count", 0)
    monkeypatch.setattr(win32_input, "_physical_mouse_restore_failures", 0)
    monkeypatch.setattr(win32_input, "_physical_mouse_last_restore", {})

    assert win32_input._send_physical_mouse_message(100, 0x0200, 10, 20)
    assert win32_input._send_physical_mouse_message(100, 0x0201, 10, 20, wparam=1)
    assert win32_input._send_physical_mouse_message(100, 0x0202, 20, 30)
    assert win32_input._restore_physical_mouse_state() is True

    evidence = win32_input._physical_mouse_input_evidence()
    assert user32.mouse_events == [0x0002, 0x0004]
    assert user32.cursor == [12, 34]
    assert user32.foreground == 55
    assert evidence["gesture_count"] == 1
    assert evidence["active"] is False
    assert evidence["restored"] is True
    assert evidence["target_root_hwnd"] == 500
    assert evidence["activated_root_hwnd"] == 500
    assert evidence["last_restore"]["button_released"] is True


def test_real_dotnet_report_uses_helper_local_no_global_input_evidence(monkeypatch) -> None:
    from tools.mesh_harness import real_dotnet_report

    monkeypatch.setattr(
        real_dotnet_report,
        "_physical_mouse_input_evidence",
        lambda: {
            "gesture_count": 0,
            "restore_failure_count": 0,
            "active": False,
            "last_restore": {
                "cursor": [10, 20],
                "foreground_hwnd": 99,
            },
        },
    )

    result = real_dotnet_report._helper_ui_thread_no_global_input_evidence()

    assert result == {
        "method": "helper_ui_thread_no_global_input",
        "ok": True,
        "gesture_count": 0,
        "restore_failure_count": 0,
        "active": False,
    }


def test_real_dotnet_report_no_global_input_evidence_fails_closed(monkeypatch) -> None:
    from tools.mesh_harness import real_dotnet_report

    for physical_input, expected_ok in (
        ({}, False),
        ({"gesture_count": 1, "restore_failure_count": 0, "active": False}, False),
        ({"gesture_count": 0, "restore_failure_count": 1, "active": False}, False),
        ({"gesture_count": 0, "restore_failure_count": 0, "active": True}, False),
    ):
        monkeypatch.setattr(
            real_dotnet_report,
            "_physical_mouse_input_evidence",
            lambda physical_input=physical_input: physical_input,
        )
        assert (
            real_dotnet_report._helper_ui_thread_no_global_input_evidence()["ok"]
            is expected_ok
        )

    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "mesh_harness"
        / "real_dotnet_report.py"
    ).read_text(encoding="utf-8")

    assert '"method": "helper_ui_thread_no_global_input"' in source
    assert "_physical_mouse_input_evidence()" in source
    assert (
        "state.desktop_input_isolation = dict(state.helper_ui_thread_no_global_input)"
        in source
    )
    for forbidden in (
        "_desktop_input_snapshot",
        "_desktop_input_isolation_evidence",
        "_restore_physical_mouse_state",
        "GetCursorPos",
        "GetForegroundWindow",
        "SetCursorPos",
        "SetForegroundWindow",
    ):
        assert forbidden not in source


def test_global_mouse_mutation_is_confined_to_authorized_visible_driver() -> None:
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in (Path("tools/mesh_harness")).glob("*.py")
    }

    for api in (
        "SetCursorPos",
        "SendInput",
        "SetForegroundWindow",
        "AttachThreadInput",
        "SetFocus",
    ):
        assert api in sources["win32_input.py"]
        assert all(
            api not in source
            for name, source in sources.items()
            if name != "win32_input.py"
        )
    for forbidden in ("mouse_event", "SetActiveWindow", "BringWindowToTop"):
        assert all(forbidden not in source for source in sources.values())
    assert "_send_physical_mouse_message" not in sources["real_dotnet_input.py"]
    assert "_send_physical_mouse_message" not in sources[
        "packaged_mesh_texture_smoke.py"
    ]
    assert '"resident_interaction_probe"' in sources["real_dotnet_input.py"]


def test_helper_local_select_probe_emits_transaction_and_waits_for_authority() -> None:
    from tools.mesh_harness.real_dotnet_input import drive_viewport_selection

    events: list[dict[str, object]] = []

    def send_protocol(payload: Mapping[str, object]) -> bool:
        request_id = int(payload.get("request_id", 0) or 0)
        events.extend(
            [
                {
                    "event": "resident_interaction_transaction",
                    "request_id": 9,
                    "session_id": "session-a",
                    "sha256": "ab" * 32,
                },
                {
                    "event": "resident_interaction_probe_applied",
                    "request_id": request_id,
                    "status": "applied",
                    "ok": True,
                },
            ]
        )
        return True

    state = SimpleNamespace(
        viewport={"width": 100, "height": 100, "screen_x": 10, "screen_y": 20},
        viewport_hwnd=101,
        production_process_pid=77,
        form_hwnd=100,
        tab=SimpleNamespace(
            standalone_dotnet_protocol_events=events,
            _send_dotnet_protocol_message=send_protocol,
            _standalone_action_worker_active=lambda: False,
            standalone_dotnet_update_queue=SimpleNamespace(
                metrics=lambda: {"active_revision": 0, "pending_depth": 0}
            ),
        ),
    )

    def pump_for(_state, _seconds: float) -> None:
        return None

    with (
        patch(
            "tools.mesh_harness.real_dotnet_input.resident_interaction_commit_ack",
            return_value={
                "event": "resident_interaction_commit_ack",
                "request_id": 9,
                "status": "applied",
            },
        ),
    ):
        result = drive_viewport_selection(
            state,
            point=(50.0, 50.0),
            pump_for=pump_for,
            pump_until=lambda _state, predicate, _timeout: predicate(),
        )

    assert result["ok"] is True
    assert result["backend"] == "helper_ui_thread_resident_probe"
    assert result["global_mouse_input_used"] is False
    assert result["start"] == [50, 50]
    assert result["end"] == [58, 50]
    assert result["resident_interaction_transaction_count"] == 1
    assert result["resident_interaction_transactions"][0]["request_id"] == 9
    assert result["authority_acknowledgement"]["request_id"] == 9
    assert result["authority_settled"] is True
