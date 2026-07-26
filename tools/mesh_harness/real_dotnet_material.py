from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace

from cdmw.services.mesh_dotnet_experiment import mesh_dotnet_material_state_payload


# A resident material update recompiles real material maps on a worker thread.
# The pre-migration 5s default was calibrated against a re-send of an unchanged
# state, which no longer reaches the compiler at all.
_MATERIAL_ACK_TIMEOUT_SECONDS = 45.0


def request_full_renderer_status(
    state: SimpleNamespace,
    pump_until: Callable[..., bool],
    timeout_seconds: float = 10.0,
) -> dict[str, object]:
    """Ask the renderer for its current full status and wait for the reply.

    Per-frame metrics carry a slim payload with no viewport identity, no
    texture resource counters and no presentation block, so comparisons that
    read those fields from a metrics event were reading absent values. This
    samples the real state at the moment it is asked for, which is what the
    before/after comparisons need to mean anything.
    """

    cursor = len(state.tab.standalone_dotnet_protocol_events)
    request_id = int(getattr(state, "renderer_status_request_id", 0) or 0) + 1
    state.renderer_status_request_id = request_id
    sent = bool(
        state.tab._send_dotnet_protocol_message(
            {
                "event": "renderer_status_request",
                "session_id": state.controller.active_session_id,
                "request_id": request_id,
            }
        )
    )
    if not sent:
        return {}
    found: dict[str, object] = {}

    def locate() -> bool:
        nonlocal found
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]:
            if str(event.get("event", "")) != "renderer_status":
                continue
            if int(event.get("request_id", 0) or 0) != request_id:
                continue
            renderer = event.get("renderer")
            if isinstance(renderer, Mapping):
                found = dict(renderer)
                return True
        return False

    pump_until(state, locate, timeout_seconds)
    return found


def renderer_identity(renderer: Mapping[str, object]) -> dict[str, int]:
    viewport = renderer.get("viewport")
    viewport = viewport if isinstance(viewport, Mapping) else {}
    return {"form_hwnd": int(viewport.get("form_hwnd", 0) or 0), "viewport_hwnd": int(viewport.get("hwnd", 0) or 0)}


def renderer_resource_metrics(renderer: Mapping[str, object]) -> dict[str, object]:
    return dict(metrics) if isinstance((metrics := renderer.get("geometry_resources")), Mapping) else {}


def _renderer_decode_metrics(renderer: Mapping[str, object]) -> dict[str, int]:
    return {
        key: int(renderer.get(key, 0) or 0)
        for key in (
            "texture_decode_attempts",
            "texture_decode_successes",
            "texture_decode_reuses",
            "incremental_texture_decodes",
            "decoded_texture_resources",
        )
    }


def _frame_count(event: Mapping[str, object]) -> int:
    metrics = event.get("metrics")
    metrics = metrics if isinstance(metrics, Mapping) else event
    return int(metrics.get("frame_count", 0) or 0)


def _protocol_result(
    state: SimpleNamespace,
    pump_until: Callable[..., bool],
    cursor: int,
    names: set[str],
    timeout_seconds: float = 5.0,
) -> dict[str, object]:
    found: dict[str, object] = {}

    def locate() -> bool:
        nonlocal found
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]:
            if str(event.get("event", "") or "") in names:
                found = dict(event)
                return True
        return False

    pump_until(state, locate, timeout_seconds)
    return found


def resident_material_gates(state: SimpleNamespace) -> dict[str, bool]:
    payload, applied = state.material_state_payload, state.material_state_applied
    payloads = tuple(getattr(state, "material_state_payloads", (payload,)) or ())
    applied_events = tuple(getattr(state, "material_state_applied_events", (applied,)) or ())
    before, after = state.material_lifecycle_before, state.material_lifecycle_after
    resources_before, resources_after = state.material_resource_metrics_before, state.material_resource_metrics_after
    same_srv_keys = ("texture_srv_creates", "texture_srv_disposals", "live_texture_srvs")
    generations = [int(item.get("generation", 0) or 0) for item in payloads]
    applied_generations = [int(item.get("generation", 0) or 0) for item in applied_events]
    edit_revisions = [int(item.get("edit_revision", -1)) for item in payloads]
    applied_edit_revisions = [int(item.get("edit_revision", -1)) for item in applied_events]
    applied_renderer_generations = [
        int(
            (item.get("renderer") if isinstance(item.get("renderer"), Mapping) else {}).get(
                "material_generation", 0
            ) or 0
        )
        for item in applied_events
    ]
    latest_renderer = applied.get("renderer")
    latest_renderer = latest_renderer if isinstance(latest_renderer, Mapping) else {}
    return {
        "resident_material_update_applied": bool(
            applied.get("event") == "material_state_applied"
            and int(applied.get("generation", 0) or 0) == int(payload.get("generation", 0) or 0)
        ),
        "resident_material_signature_applied": applied.get("material_signature") == payload.get("material_signature"),
        "resident_material_generation_ordered": bool(
            len(generations) == len(applied_generations) == 2
            and generations[0] > 0
            and generations[1] == generations[0] + 1
            and applied_generations == generations
            and applied_renderer_generations == generations
            and applied_edit_revisions == edit_revisions
            and len(set(edit_revisions)) == 1
            and int(latest_renderer.get("last_requested_material_generation", 0) or 0) == generations[-1]
            and int(latest_renderer.get("last_applied_material_generation", 0) or 0) == generations[-1]
            and int(latest_renderer.get("material_generation", 0) or 0) == generations[-1]
        ),
        "resident_material_process_unchanged": bool(
            state.material_process_pid_before > 0 and state.material_process_pid_before == state.material_process_pid_after
        ),
        "resident_material_windows_unchanged": bool(
            all(state.material_window_identity_before.values()) and state.material_window_identity_before == state.material_window_identity_after
        ),
        "resident_material_no_package_rebuild": bool(
            int(before.get("package_build_count", 0)) == int(after.get("package_build_count", 0)) == 1
            and int(after.get("initial_package_build_count", 0)) == 1
        ),
        "resident_material_no_process_restart": bool(
            int(before.get("renderer_process_start_count", 0)) == int(after.get("renderer_process_start_count", 0)) == 1
            and int(after.get("process_restart_count", 0)) == 0
        ),
        "resident_material_no_full_reload": int(after.get("full_reload_count", 0)) == 0,
        "resident_material_srv_reused": bool(
            payload.get("resources")
            and int(applied.get("decoded_resources", 0) or 0) == 0
            and int(applied.get("reused_resources", 0) or 0) == len(payload["resources"])
            and int(resources_before.get("texture_srv_creates", 0) or 0) > 0
            and int(resources_after.get("texture_srv_reuses", 0) or 0) > int(resources_before.get("texture_srv_reuses", 0) or 0)
            and all(resources_before.get(key) == resources_after.get(key) for key in same_srv_keys)
        ),
        "resident_material_counters_ok": bool(
            int(after.get("material_state_update_count", 0)) - int(before.get("material_state_update_count", 0)) == 2
            and int(after.get("material_state_applied_count", 0)) - int(before.get("material_state_applied_count", 0)) == 2
            and int(after.get("material_state_failed_count", 0)) == int(before.get("material_state_failed_count", 0))
        ),
        "resident_material_dedup_respected": bool(getattr(state, "material_dedup_ok", False)),
    }


def _perturb_material_state_for_update(state: SimpleNamespace, toggle_index: int) -> bool:
    """Flip one submesh's texture V-flip so the update is a genuine change.

    Production deduplicates material states whose input signature is unchanged
    (afda4eae): resending the launch state succeeds without any protocol
    traffic, so an ack for it never arrives. Real users change something
    before a resident material update; the harness must too.
    """

    mesh = state.controller.working_mesh(clone=False)
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    if not submeshes:
        return False
    target = submeshes[min(max(0, int(toggle_index)), len(submeshes) - 1)]
    setattr(
        target,
        "preview_texture_flip_vertical",
        not bool(getattr(target, "preview_texture_flip_vertical", False)),
    )
    return True


def exercise_resident_material_update(
    state: SimpleNamespace,
    *,
    base_error: Callable[[SimpleNamespace, str], dict[str, object]],
    pump_until: Callable[..., bool],
    wait_protocol_event: Callable[..., dict[str, object]],
) -> dict[str, object] | None:
    view = state.controller.session_view()
    if not _perturb_material_state_for_update(state, 0):
        return base_error(state, "Resident material update found no submeshes to perturb.")
    first_payload = mesh_dotnet_material_state_payload(
        state.controller.working_mesh(clone=False), session_id=view.session_id, edit_revision=view.revision,
        generation=int(state.tab.standalone_dotnet_material_generation) + 1,
    )
    state.material_lifecycle_before = dict(state.tab.standalone_dotnet_lifecycle_counts)
    state.material_window_identity_before = renderer_identity(state.renderer)
    state.material_process_pid_before = int(state.process.processId())
    cursor = len(state.tab.standalone_dotnet_protocol_events)
    if not state.tab._send_dotnet_material_state(reason="real_archive_harness"):
        return base_error(state, "Production .NET material-state sender rejected the resident update.")
    first_applied = _protocol_result(
        state,
        pump_until,
        cursor,
        {"material_state_applied", "material_state_failed"},
        timeout_seconds=_MATERIAL_ACK_TIMEOUT_SECONDS,
    )
    if first_applied.get("event") != "material_state_applied":
        return base_error(state, str(first_applied.get("message") or "First resident .NET material update was not acknowledged."))
    first_renderer = first_applied.get("renderer")
    first_renderer = dict(first_renderer) if isinstance(first_renderer, Mapping) else {}
    state.material_resource_metrics_before = renderer_resource_metrics(first_renderer)
    state.textures_event = first_applied
    if first_renderer:
        state.renderer = first_renderer
    current = state.controller.session_view()
    # Toggle the same submesh back rather than perturbing a second one: this is
    # still a genuine change (so it earns its own ack) but leaves the working
    # mesh byte-identical to how the stage found it. Leaving submeshes flipped
    # contaminates every later stage, which then exercises a material state no
    # user asked for.
    if not _perturb_material_state_for_update(state, 0):
        return base_error(state, "Second resident material update found no submeshes to perturb.")
    second_payload = mesh_dotnet_material_state_payload(
        state.controller.working_mesh(clone=False), session_id=current.session_id, edit_revision=current.revision,
        generation=int(state.tab.standalone_dotnet_material_generation) + 1,
    )
    cursor = len(state.tab.standalone_dotnet_protocol_events)
    if not state.tab._send_dotnet_material_state(reason="real_archive_harness_same_revision"):
        return base_error(state, "Production .NET material-state sender rejected the second resident update.")
    second_applied = _protocol_result(
        state,
        pump_until,
        cursor,
        {"material_state_applied", "material_state_failed"},
        timeout_seconds=_MATERIAL_ACK_TIMEOUT_SECONDS,
    )
    if second_applied.get("event") != "material_state_applied":
        return base_error(state, str(second_applied.get("message") or "Second resident .NET material update was not acknowledged."))
    state.material_state_payloads = (first_payload, second_payload)
    state.material_state_applied_events = (first_applied, second_applied)
    state.material_state_payload = second_payload
    state.material_state_applied = second_applied
    metrics_event = wait_protocol_event(state, "metrics", len(state.tab.standalone_dotnet_protocol_events), 2.0)
    renderer_after = second_applied.get("renderer")
    if not isinstance(renderer_after, Mapping):
        renderer_after = metrics_event.get("renderer")
    if not isinstance(renderer_after, Mapping):
        renderer_after = state.tab.standalone_dotnet_status_payload.get("renderer")
    renderer_after = dict(renderer_after) if isinstance(renderer_after, Mapping) else {}
    state.material_window_identity_after = renderer_identity(renderer_after)
    state.material_resource_metrics_after = renderer_resource_metrics(renderer_after)
    state.material_process_pid_after = int(state.tab.standalone_dotnet_editor_process.processId())
    state.material_lifecycle_after = dict(state.tab.standalone_dotnet_lifecycle_counts)
    # An UNCHANGED resend must take the dedup path: success without protocol
    # traffic and without starting a compile. This encodes the afda4eae
    # production contract the pre-migration harness predates.
    dedup_counts_before = dict(state.tab.standalone_dotnet_lifecycle_counts)
    dedup_cursor = len(state.tab.standalone_dotnet_protocol_events)
    dedup_send_ok = bool(state.tab._send_dotnet_material_state(reason="real_archive_harness_unchanged"))
    dedup_counts_after = dict(state.tab.standalone_dotnet_lifecycle_counts)
    state.material_dedup_ok = bool(
        dedup_send_ok
        and int(dedup_counts_after.get("material_state_deduplicated_count", 0) or 0)
        == int(dedup_counts_before.get("material_state_deduplicated_count", 0) or 0) + 1
        and int(dedup_counts_after.get("material_compile_start_count", 0) or 0)
        == int(dedup_counts_before.get("material_compile_start_count", 0) or 0)
        and len(state.tab.standalone_dotnet_protocol_events) == dedup_cursor
    )
    state.resident_material_gates = resident_material_gates(state)
    return None


def _write_material_visual_diff(before_path: Path, after_path: Path, output_path: Path) -> dict[str, object]:
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageEnhance

        with Image.open(before_path) as before_raw, Image.open(after_path) as after_raw:
            before = before_raw.convert("RGB")
            after = after_raw.convert("RGB")
    except (ImportError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    if before.size != after.size:
        return {"ok": False, "error": "capture sizes differ"}
    diff = ImageChops.difference(before, after)
    # Resident shader parameters produce intentionally subtle changes.  Ignore
    # capture noise, but do not require the destructive values the old proof
    # used just to clear an eight-level threshold.
    diff_threshold = 2
    minimum_changed_pixels = 64
    mask = diff.convert("L").point(lambda value: 255 if value > diff_threshold else 0)
    changed_pixels = mask.histogram()[255]
    panel_size = (360, 260)
    sheet = Image.new("RGB", (panel_size[0] * 3, panel_size[1] + 28), (15, 18, 22))
    for index, image in enumerate((before, after, ImageEnhance.Brightness(diff).enhance(5.0))):
        sheet.paste(image.resize(panel_size), (panel_size[0] * index, 28))
    draw = ImageDraw.Draw(sheet)
    for index, label in enumerate(("before material update", "after rendered frame", "difference")):
        draw.text((panel_size[0] * index + 10, 8), label, fill=(235, 235, 235))
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(output_path)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": bool(changed_pixels >= minimum_changed_pixels and output_path.is_file()),
        "path": str(output_path),
        "changed_pixel_count": changed_pixels,
        "changed_fraction": changed_pixels / max(1, before.width * before.height),
        "diff_bbox": list(mask.getbbox()) if mask.getbbox() is not None else None,
        "diff_threshold": diff_threshold,
        "minimum_changed_pixels": minimum_changed_pixels,
    }


def _next_rendered_metrics(
    state: SimpleNamespace,
    pump_until: Callable[..., bool],
    cursor: int,
    frame_count: int,
) -> dict[str, object]:
    found: dict[str, object] = {}

    def locate() -> bool:
        nonlocal found
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]:
            if str(event.get("event", "") or "") == "metrics" and _frame_count(event) > frame_count:
                found = dict(event)
                return True
        return False

    pump_until(state, locate, 3.0)
    return found


def material_parameter_gates(state: SimpleNamespace) -> dict[str, bool]:
    payload, applied = state.material_parameter_payload, state.material_parameter_applied
    before, after = state.material_parameter_lifecycle_before, state.material_parameter_lifecycle_after
    resources_before, resources_after = state.material_parameter_resource_metrics_before, state.material_parameter_resource_metrics_after
    ack_lifecycle = applied.get("lifecycle_counts") if isinstance(applied.get("lifecycle_counts"), Mapping) else {}
    unchanged_geometry = (
        "full_geometry_rebuilds", "geometry_buffer_identity", "vertex_buffer_creates",
        "index_buffer_creates", "geometry_buffer_disposals",
    )
    unchanged_texture = (
        "texture_srv_creates", "texture_srv_disposals", "texture_srv_reuses", "live_texture_srvs",
        "material_binding_array_creates", "material_binding_array_identity", "affected_material_batch_rebinds",
    )
    affected = list(payload.get("affected_submeshes", ()))
    before_capture = state.material_parameter_before_capture_summary
    after_capture = state.material_parameter_after_capture_summary
    before_bright = int(before_capture.get("bright_sample_count", 0) or 0)
    after_bright = int(after_capture.get("bright_sample_count", 0) or 0)
    before_colors = int(before_capture.get("unique_rgb_count", 0) or 0)
    after_colors = int(after_capture.get("unique_rgb_count", 0) or 0)
    return {
        "material_parameter_update_applied": bool(
            applied.get("event") == "material_parameter_applied"
            and applied.get("session_id") == payload.get("session_id")
            and int(applied.get("parameter_generation", 0) or 0) == int(payload.get("parameter_generation", 0) or 0) == 1
            and int(applied.get("edit_revision", -1)) == int(payload.get("edit_revision", -2))
            and list(applied.get("affected_submeshes", ())) == affected
        ),
        "material_parameter_rendered_next_frame": int(state.material_parameter_frame_after) > int(state.material_parameter_frame_before),
        "material_parameter_visual_diff": bool(state.material_parameter_visual_diff.get("ok")),
        "material_parameter_render_not_black": bool(
            before_capture.get("ok")
            and after_capture.get("ok")
            and before_bright >= 64
            and after_bright >= max(64, int(before_bright * 0.75))
            and after_colors >= max(8, int(before_colors * 0.5))
        ),
        "material_parameter_process_unchanged": bool(
            state.material_parameter_process_pid_before > 0
            and state.material_parameter_process_pid_before == state.material_parameter_process_pid_after
        ),
        "material_parameter_windows_unchanged": bool(
            all(state.material_parameter_window_identity_before.values())
            and state.material_parameter_window_identity_before == state.material_parameter_window_identity_after
        ),
        "material_parameter_no_package_or_process_reload": bool(
            int(before.get("package_build_count", 0)) == int(after.get("package_build_count", 0)) == 1
            and int(before.get("renderer_process_start_count", 0)) == int(after.get("renderer_process_start_count", 0)) == 1
            and int(after.get("process_restart_count", 0)) == int(after.get("full_reload_count", 0)) == 0
            and int(ack_lifecycle.get("source_parse_count", 0)) == 1
        ),
        "material_parameter_no_geometry_rebuild": all(resources_before.get(key) == resources_after.get(key) for key in unchanged_geometry),
        "material_parameter_no_texture_decode": state.material_parameter_decode_metrics_before == state.material_parameter_decode_metrics_after,
        "material_parameter_no_texture_resource_churn": all(
            resources_before.get(key) == resources_after.get(key) for key in unchanged_texture
        ),
        "material_parameter_affected_batch_only": bool(
            len(affected) == 1
            and int(resources_after.get("affected_material_parameter_batches", 0) or 0)
            - int(resources_before.get("affected_material_parameter_batches", 0) or 0) == 1
        ),
        "material_parameter_apply_counted": bool(
            int(resources_after.get("material_parameter_apply_count", 0) or 0)
            - int(resources_before.get("material_parameter_apply_count", 0) or 0) == 1
            and resources_before.get("material_parameter_apply_failure_count") == resources_after.get("material_parameter_apply_failure_count")
        ),
        "material_parameter_counters_ok": bool(
            int(after.get("material_parameter_update_count", 0)) == int(after.get("material_parameter_applied_count", 0)) == 1
            and int(after.get("material_parameter_failed_count", 0)) == 0
            and int(ack_lifecycle.get("material_parameter_update_count", 0))
            == int(ack_lifecycle.get("material_parameter_applied_count", 0)) == 1
            and int(ack_lifecycle.get("material_parameter_failed_count", 0)) == 0
        ),
    }


def material_parameter_evidence(state: SimpleNamespace) -> dict[str, object]:
    return {
        "payload": state.material_parameter_payload,
        "applied": state.material_parameter_applied,
        "frame_count_before": state.material_parameter_frame_before,
        "frame_count_after": state.material_parameter_frame_after,
        "process_pid_before": state.material_parameter_process_pid_before,
        "process_pid_after": state.material_parameter_process_pid_after,
        "window_identity_before": state.material_parameter_window_identity_before,
        "window_identity_after": state.material_parameter_window_identity_after,
        "lifecycle_counts_before": state.material_parameter_lifecycle_before,
        "lifecycle_counts_after": state.material_parameter_lifecycle_after,
        "resource_metrics_before": state.material_parameter_resource_metrics_before,
        "resource_metrics_after": state.material_parameter_resource_metrics_after,
        "decode_metrics_before": state.material_parameter_decode_metrics_before,
        "decode_metrics_after": state.material_parameter_decode_metrics_after,
        "before_capture_png": str(state.material_parameter_before_capture_path),
        "after_capture_png": str(state.material_parameter_after_capture_path),
        "visual_diff_png": str(state.material_parameter_visual_diff_path),
        "before_capture_summary": state.material_parameter_before_capture_summary,
        "after_capture_summary": state.material_parameter_after_capture_summary,
        "visual_diff_summary": state.material_parameter_visual_diff,
    }


def resident_material_evidence(state: SimpleNamespace) -> dict[str, object]:
    return {
        "generation_sequence": [
            {
                "requested_generation": int(payload.get("generation", 0) or 0),
                "applied_generation": int(applied.get("generation", 0) or 0),
                "edit_revision": int(payload.get("edit_revision", -1)),
            }
            for payload, applied in zip(
                tuple(getattr(state, "material_state_payloads", ()) or ()),
                tuple(getattr(state, "material_state_applied_events", ()) or ()),
            )
        ],
        "payload": {
            "schema": state.material_state_payload.get("schema"),
            "version": state.material_state_payload.get("version"),
            "session_id": state.material_state_payload.get("session_id"),
            "edit_revision": state.material_state_payload.get("edit_revision"),
            "generation": state.material_state_payload.get("generation"),
            "material_signature": state.material_state_payload.get("material_signature"),
            "affected_submeshes": list(state.material_state_payload.get("affected_submeshes", ())),
            "resource_count": len(tuple(state.material_state_payload.get("resources", ()) or ())),
        },
        "applied": state.material_state_applied,
        "process_pid_before": state.material_process_pid_before,
        "process_pid_after": state.material_process_pid_after,
        "window_identity_before": state.material_window_identity_before,
        "window_identity_after": state.material_window_identity_after,
        "lifecycle_counts_before": state.material_lifecycle_before,
        "lifecycle_counts_after": state.material_lifecycle_after,
        "resource_metrics_before": state.material_resource_metrics_before,
        "resource_metrics_after": state.material_resource_metrics_after,
    }


def exercise_material_parameter_update(
    state: SimpleNamespace,
    *,
    base_error: Callable[[SimpleNamespace, str], dict[str, object]],
    pump_until: Callable[..., bool],
    wait_protocol_event: Callable[..., dict[str, object]],
    capture_viewport: Callable[[SimpleNamespace, Path], dict[str, object]],
) -> dict[str, object] | None:
    state.material_parameter_before_capture_path = state.output_dir / "real_archive_dotnet_material_before.png"
    state.material_parameter_after_capture_path = state.output_dir / "real_archive_dotnet_material_after.png"
    state.material_parameter_visual_diff_path = state.output_dir / "real_archive_dotnet_material_diff.png"
    baseline = wait_protocol_event(state, "metrics", len(state.tab.standalone_dotnet_protocol_events), 2.0)
    # Both ends of this comparison have to be the same kind of payload. The
    # metrics event supplies the frame count, but its slim renderer has no
    # window identity, resource counters or decode counters, so pairing it with
    # a full status afterwards would report the difference between a real
    # reading and an absent one rather than the effect of the update.
    renderer_before = request_full_renderer_status(state, pump_until)
    if not renderer_before:
        renderer_before = baseline.get("renderer")
        if not isinstance(renderer_before, Mapping):
            renderer_before = state.tab.standalone_dotnet_status_payload.get("renderer")
    renderer_before = dict(renderer_before) if isinstance(renderer_before, Mapping) else {}
    state.material_parameter_frame_before = _frame_count(baseline)
    state.material_parameter_before_capture_summary = capture_viewport(state, state.material_parameter_before_capture_path)
    state.material_parameter_lifecycle_before = dict(state.tab.standalone_dotnet_lifecycle_counts)
    state.material_parameter_process_pid_before = int(state.tab.standalone_dotnet_editor_process.processId())
    state.material_parameter_window_identity_before = renderer_identity(renderer_before)
    state.material_parameter_resource_metrics_before = renderer_resource_metrics(renderer_before)
    state.material_parameter_decode_metrics_before = _renderer_decode_metrics(renderer_before)
    # Use a conspicuous but valid per-part presentation change so the real-game
    # proof cannot pass on protocol acknowledgement alone.  The previous
    # near-neutral values produced only a handful of pixels above the capture
    # noise floor on dark archive materials.
    group = {
        "source_submesh_indices": [int(state.submesh_index)],
        "editor_role": "replacement_preview",
        "texture_brightness": 1.35,
        "contrast": 1.15,
        "saturation": 1.2,
        "gamma": 0.9,
        "tint_color": [0.25, 0.75, 1.0],
        "roughness": 0.2,
        "metalness": 0.15,
        "specular": 0.8,
    }
    cursor = len(state.tab.standalone_dotnet_protocol_events)
    if not state.tab.apply_resident_material_parameters((group,)):
        return base_error(state, "Production .NET material-parameter sender rejected the update.")
    state.material_parameter_payload = dict(state.tab.standalone_dotnet_pending_material_parameter_payload or {})
    result = _protocol_result(state, pump_until, cursor, {"material_parameter_applied", "material_parameter_failed"})
    state.material_parameter_applied = result
    if result.get("event") != "material_parameter_applied":
        return base_error(state, str(result.get("message") or "Resident .NET material-parameter update was not acknowledged."))
    frame_cursor = len(state.tab.standalone_dotnet_protocol_events)
    rendered = _next_rendered_metrics(state, pump_until, frame_cursor, state.material_parameter_frame_before)
    # rendered proves a frame was drawn, but its slim payload has no viewport
    # identity or texture resource counters; the before-state was sampled from
    # a full status, so the after-state has to come from one too.
    renderer_after = request_full_renderer_status(state, pump_until)
    if not renderer_after:
        renderer_after = rendered.get("renderer")
        if not isinstance(renderer_after, Mapping):
            renderer_after = result.get("renderer")
    renderer_after = dict(renderer_after) if isinstance(renderer_after, Mapping) else {}
    state.material_parameter_frame_after = _frame_count(rendered)
    state.material_parameter_after_capture_summary = capture_viewport(state, state.material_parameter_after_capture_path)
    state.material_parameter_visual_diff = _write_material_visual_diff(
        state.material_parameter_before_capture_path,
        state.material_parameter_after_capture_path,
        state.material_parameter_visual_diff_path,
    )
    state.material_parameter_process_pid_after = int(state.tab.standalone_dotnet_editor_process.processId())
    state.material_parameter_window_identity_after = renderer_identity(renderer_after)
    state.material_parameter_resource_metrics_after = renderer_resource_metrics(renderer_after)
    state.material_parameter_decode_metrics_after = _renderer_decode_metrics(renderer_after)
    state.material_parameter_lifecycle_after = dict(state.tab.standalone_dotnet_lifecycle_counts)
    state.material_parameter_gates = material_parameter_gates(state)
    return None


__all__ = [
    "exercise_material_parameter_update",
    "exercise_resident_material_update",
    "material_parameter_evidence",
    "material_parameter_gates",
    "renderer_identity",
    "renderer_resource_metrics",
    "request_full_renderer_status",
    "resident_material_evidence",
    "resident_material_gates",
]
