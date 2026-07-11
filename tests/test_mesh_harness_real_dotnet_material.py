from __future__ import annotations

from types import SimpleNamespace

from PIL import Image

from tools.mesh_harness.real_dotnet_material import _frame_count, _write_material_visual_diff, material_parameter_gates


def _parameter_state() -> SimpleNamespace:
    before_counts = {
        "initial_package_build_count": 1,
        "package_build_count": 1,
        "renderer_process_start_count": 1,
        "process_restart_count": 0,
        "full_reload_count": 0,
        "material_parameter_update_count": 0,
        "material_parameter_applied_count": 0,
        "material_parameter_failed_count": 0,
    }
    resources = {
        "full_geometry_rebuilds": 1,
        "geometry_buffer_identity": 42,
        "vertex_buffer_creates": 3,
        "index_buffer_creates": 3,
        "geometry_buffer_disposals": 0,
        "texture_srv_creates": 3,
        "texture_srv_disposals": 0,
        "texture_srv_reuses": 3,
        "live_texture_srvs": 3,
        "material_binding_array_creates": 6,
        "material_binding_array_identity": 99,
        "affected_material_batch_rebinds": 6,
        "affected_material_parameter_batches": 0,
        "material_parameter_apply_count": 0,
        "material_parameter_apply_failure_count": 0,
    }
    payload = {
        "session_id": "real-session",
        "edit_revision": 0,
        "parameter_generation": 1,
        "affected_submeshes": [2],
    }
    return SimpleNamespace(
        material_parameter_payload=payload,
        material_parameter_applied={
            "event": "material_parameter_applied",
            **payload,
            "lifecycle_counts": {
                "source_parse_count": 1,
                "material_parameter_update_count": 1,
                "material_parameter_applied_count": 1,
                "material_parameter_failed_count": 0,
            },
        },
        material_parameter_lifecycle_before=before_counts,
        material_parameter_lifecycle_after=dict(
            before_counts,
            material_parameter_update_count=1,
            material_parameter_applied_count=1,
        ),
        material_parameter_resource_metrics_before=resources,
        material_parameter_resource_metrics_after=dict(
            resources,
            affected_material_parameter_batches=1,
            material_parameter_apply_count=1,
        ),
        material_parameter_decode_metrics_before={"texture_decode_attempts": 3},
        material_parameter_decode_metrics_after={"texture_decode_attempts": 3},
        material_parameter_frame_before=10,
        material_parameter_frame_after=11,
        material_parameter_visual_diff={"ok": True, "changed_pixel_count": 20},
        material_parameter_before_capture_summary={
            "ok": True,
            "bright_sample_count": 200,
            "unique_rgb_count": 100,
        },
        material_parameter_after_capture_summary={
            "ok": True,
            "bright_sample_count": 180,
            "unique_rgb_count": 90,
        },
        material_parameter_process_pid_before=77,
        material_parameter_process_pid_after=77,
        material_parameter_window_identity_before={"form_hwnd": 10, "viewport_hwnd": 11},
        material_parameter_window_identity_after={"form_hwnd": 10, "viewport_hwnd": 11},
    )


def test_material_parameter_gates_require_one_batch_and_zero_resource_churn() -> None:
    state = _parameter_state()

    assert all(material_parameter_gates(state).values())

    state.material_parameter_resource_metrics_after = dict(
        state.material_parameter_resource_metrics_after,
        geometry_buffer_identity=43,
        texture_srv_creates=4,
        affected_material_parameter_batches=2,
    )
    state.material_parameter_decode_metrics_after = {"texture_decode_attempts": 4}
    failed = material_parameter_gates(state)
    assert failed["material_parameter_no_geometry_rebuild"] is False
    assert failed["material_parameter_no_texture_decode"] is False
    assert failed["material_parameter_no_texture_resource_churn"] is False
    assert failed["material_parameter_affected_batch_only"] is False


def test_material_parameter_visual_diff_requires_changed_pixels(tmp_path) -> None:
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    output = tmp_path / "diff.png"
    Image.new("RGB", (64, 64), (80, 80, 80)).save(before)
    changed = Image.new("RGB", (64, 64), (80, 80, 80))
    for x in range(16, 48):
        for y in range(16, 48):
            changed.putpixel((x, y), (180, 20, 20))
    changed.save(after)

    result = _write_material_visual_diff(before, after, output)

    assert result["ok"] is True
    assert result["changed_pixel_count"] == 32 * 32
    assert output.is_file()


def test_material_parameter_visual_diff_accepts_subtle_resident_shader_change(tmp_path) -> None:
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    output = tmp_path / "diff.png"
    Image.new("RGB", (64, 64), (80, 80, 80)).save(before)
    changed = Image.new("RGB", (64, 64), (80, 80, 80))
    for x in range(16, 48):
        for y in range(16, 48):
            changed.putpixel((x, y), (85, 85, 85))
    changed.save(after)

    result = _write_material_visual_diff(before, after, output)

    assert result["ok"] is True
    assert result["changed_pixel_count"] == 32 * 32
    assert result["diff_threshold"] == 2


def test_material_parameter_gate_rejects_blackened_render() -> None:
    state = _parameter_state()
    state.material_parameter_after_capture_summary = {
        "ok": True,
        "bright_sample_count": 20,
        "unique_rgb_count": 10,
    }

    assert material_parameter_gates(state)["material_parameter_render_not_black"] is False


def test_material_parameter_frame_count_reads_protocol_metrics_envelope() -> None:
    assert _frame_count({"event": "metrics", "metrics": {"frame_count": 7}}) == 7
