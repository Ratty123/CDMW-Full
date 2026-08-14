"""Real .NET harness evidence: the gate and flow half.

Split from test_mesh_harness_real_dotnet_evidence to keep both files inside
the owned-file line cap."""

from __future__ import annotations
from pathlib import Path
import re
import time
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
    # The result gates moved to real_dotnet_evidence; the smoke flow below is
    # still read from real_dotnet.py.
    evidence_source = (
        Path(__file__).resolve().parents[1] / "tools" / "mesh_harness" / "real_dotnet_evidence.py"
    ).read_text(encoding="utf-8")

    assert "mesh_dotnet_material_state_payload(" in material_source
    assert 'state.tab._send_dotnet_material_state(reason="real_archive_harness")' in material_source
    assert 'state.tab._send_dotnet_material_state(reason="real_archive_harness_same_revision")' in material_source
    assert '"viewport_mesh_selection": bool(' in evidence_source
    assert (
        "state.initial_part_selection_empty\n            and state.part_selection_remained_empty\n            and state.physical_select_gesture.get(\"ok\") is True\n            and state.viewport_mesh_selection_armed"
        in evidence_source
    )
    assert "drive_viewport_selection(" in source
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


def test_real_dotnet_geometry_color_guard_uses_the_saved_viewport_background(tmp_path: Path) -> None:
    from PIL import Image

    for name, background, geometry in (
        ("custom-black", (0, 0, 0), (125, 142, 164)),
        ("custom-light", (238, 240, 244), (42, 50, 62)),
    ):
        empty = tmp_path / f"{name}-empty.png"
        rendered = tmp_path / f"{name}-rendered.png"
        Image.new("RGB", (128, 128), background).save(empty)
        image = Image.new("RGB", (128, 128), background)
        for y in range(24, 104):
            for x in range(32, 96):
                image.putpixel((x, y), geometry)
        image.save(rendered)

        empty_metrics = _image_color_metrics(empty)
        rendered_metrics = _image_color_metrics(rendered)
        assert empty_metrics["background_rgb"] == list(background)
        assert empty_metrics["non_black_geometry"] is False
        assert rendered_metrics["background_rgb"] == list(background)
        assert rendered_metrics["non_black_geometry"] is True


def test_real_dotnet_proof_exercises_every_mode_the_mesh_view_controls_offer() -> None:
    """A mode the user can pick but the harness never drives is an untested claim.

    The harness table is pinned to the combo table rather than to a hand-kept
    shortlist, so removing or adding a visible mode updates acceptance coverage.
    """
    from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
        MESH_PREVIEW_DISPLAY_MODE_OPTIONS,
        MESH_PREVIEW_DISPLAY_MODES,
    )

    exercised = {mode for mode, _capture_name in _DISPLAY_MODES}
    capture_names = [capture_name for _mode, capture_name in _DISPLAY_MODES]

    assert exercised == set(MESH_PREVIEW_DISPLAY_MODES)
    assert len(capture_names) == len(set(capture_names))
    assert _REQUIRED_PRODUCTION_DISPLAY_MODES <= exercised
    assert _DISPLAY_MODE_LABELS == {
        mode: label for label, mode in MESH_PREVIEW_DISPLAY_MODE_OPTIONS
    }
    # Textured is restored last so the run leaves the viewport as it found it.
    assert _DISPLAY_MODES[-1][0] == "textured"


def test_real_dotnet_display_mode_flags_match_the_dotnet_mode_table() -> None:
    """The expected flags are the viewport's own switch, not a second opinion."""
    from tools.mesh_harness.real_dotnet_display import (
        _DISPLAY_MODE_COUNTERS,
        _DISPLAY_MODE_FLAGS,
    )

    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "dotnet_mesh_editor_experiment"
        / "MeshViewport.DisplayModes.cs"
    ).read_text(encoding="utf-8")
    exercised = {mode for mode, _capture_name in _DISPLAY_MODES}

    assert set(_DISPLAY_MODE_FLAGS) == exercised
    assert set(_DISPLAY_MODE_COUNTERS) == exercised
    assert all(_DISPLAY_MODE_COUNTERS.values())
    for mode, flags in _DISPLAY_MODE_FLAGS.items():
        rendered = ", ".join("true" if value else "false" for value in flags)
        entry = re.search(
            rf'^\s*[^\r\n]*"{re.escape(mode)}"[^\r\n]*=>\s*new\([^,]+,\s*{re.escape(rendered)}\),\s*$',
            source,
            re.MULTILINE,
        )
        assert entry is not None, f"{mode} expects named display state ({rendered})"


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
        topology_rebuild_ok=True,
        topology_rebuild_evidence={"all_operations_avoided_fallback": True},
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
        patch(
            "tools.mesh_harness.real_dotnet.exercise_exact_topology_rebuild",
            side_effect=flow("topology_rebuild"),
        ),
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
        "topology_rebuild",
    ]


def _selection_view(session_id: str, vertices: dict[int, set[int]]) -> SimpleNamespace:
    return SimpleNamespace(
        session_id=session_id,
        selection=SimpleNamespace(
            is_empty=lambda: not vertices,
            vertex_map=lambda: dict(vertices),
        ),
    )


def test_resident_selection_inputs_separate_the_target_and_harness_controllers() -> None:
    from tools.mesh_harness.real_dotnet import _resident_selection_inputs

    harness_controller = SimpleNamespace(
        session_view=lambda: _selection_view("edit", {2: {1, 2, 3}})
    )
    state = SimpleNamespace(
        controller=harness_controller,
        tab=SimpleNamespace(
            standalone_dotnet_target_controller=None,
            standalone_controller=harness_controller,
        ),
    )

    report = _resident_selection_inputs(state)

    # The Move stroke reads only the target controller, so an absent one has to
    # stay visible even though the harness controller holds the selection.
    assert report["target_controller_present"] is False
    assert report["target_controller_is_harness_controller"] is False
    assert report["fallback_controller_present"] is True
    assert report["target_selection_empty"] is None
    assert report["target_selection_vertex_count"] is None
    assert report["harness_selection_empty"] is False
    assert report["harness_selection_vertex_count"] == 3


def test_resident_selection_inputs_report_a_shared_controller_holding_a_selection() -> None:
    from tools.mesh_harness.real_dotnet import _resident_selection_inputs

    controller = SimpleNamespace(
        session_view=lambda: _selection_view("edit", {1: {4}, 2: {5, 6}})
    )
    state = SimpleNamespace(
        controller=controller,
        tab=SimpleNamespace(
            standalone_dotnet_target_controller=controller,
            standalone_controller=controller,
        ),
    )

    report = _resident_selection_inputs(state)

    assert report["target_controller_present"] is True
    assert report["target_controller_is_harness_controller"] is True
    assert report["target_session_id"] == "edit"
    assert report["target_selection_empty"] is False
    assert report["target_selection_vertex_count"] == 3
    # The count alone cannot show that the host and the session disagree about
    # *which* vertices are selected, so the map has to survive too.
    assert report["target_selection_counts_by_submesh"] == {"1": 1, "2": 2}
    assert report["target_selection_indices_by_submesh"] == {"1": [4], "2": [5, 6]}


def test_resident_selection_inputs_record_a_raising_session_view() -> None:
    from tools.mesh_harness.real_dotnet import _resident_selection_inputs

    def _raise() -> object:
        raise RuntimeError("no active session")

    controller = SimpleNamespace(session_view=_raise)
    state = SimpleNamespace(
        controller=controller,
        tab=SimpleNamespace(
            standalone_dotnet_target_controller=controller,
            standalone_controller=None,
        ),
    )

    report = _resident_selection_inputs(state)

    # tab_interaction swallows exactly this failure and falls back to a screen
    # brush, so the reason has to survive into the evidence instead.
    assert report["target_controller_present"] is True
    assert report["target_selection_empty"] is None
    assert report["target_error"] == "RuntimeError: no active session"


def test_last_select_request_id_takes_the_newest_selection_request() -> None:
    from tools.mesh_harness.real_dotnet import _last_select_request_id

    state = SimpleNamespace(
        tab=SimpleNamespace(
            standalone_dotnet_protocol_events=[
                {"event": "select_request", "request_id": 4},
                {"event": "stroke_begin", "request_id": 99},
                {"event": "select_request", "request_id": 8},
                {"event": "select_request", "request_id": 5},
            ]
        )
    )

    assert _last_select_request_id(state) == 8


def test_applied_selection_push_id_reads_the_push_the_helper_answered_with() -> None:
    from tools.mesh_harness.real_dotnet import _applied_selection_push_id

    event = {
        "event": "tool_state_applied",
        "local_selection": {"last_host_selection_push": {"request_id": 4}},
    }

    # The helper answers from the push it has applied, which trails the gesture,
    # so this is the number that says whether the answer is current.
    assert _applied_selection_push_id(event) == 4
    assert _applied_selection_push_id({"event": "tool_state_applied"}) == 0
    assert _applied_selection_push_id(None) == 0


def test_move_is_armed_only_after_the_applied_selection_push_catches_up() -> None:
    """A single tool_state ask samples the selection push before last.

    The helper answers from the push it has already applied, so the harness has
    to re-ask until that push is the gesture's own. Asking once reported the
    projection probe's selection while the gesture's was still in flight, which
    is what made both drag gates compare two different gestures.
    """

    root = Path(__file__).resolve().parents[1]
    source = (root / "tools" / "mesh_harness" / "real_dotnet.py").read_text(encoding="utf-8")

    # The arming is its own function now. Bound it by the next top-level def so
    # this guard follows the behaviour rather than a location.
    start = source.index("def _arm_move_and_read_applied_selection(")
    end = source.find("\ndef ", start + 1)
    arming = source[start: end if end != -1 else len(source)]
    # And the driver must still call it, or the retry would sit there unused.
    assert "_arm_move_and_read_applied_selection(state)" in source

    assert "_last_select_request_id(state)" in arming
    assert "_applied_selection_push_id(state.tool_state_event)" in arming
    # The ask has to sit inside a bounded retry, not run once.
    assert "for attempt in range(" in arming
    assert arming.count('"tool": "move"') == 1
    assert "caught_up" in arming
