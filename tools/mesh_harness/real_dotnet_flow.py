from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from cdmw.core.atomic_file import atomic_binary_writer
from cdmw.domain.mesh.editing import MeshEditSelection
from cdmw.models import TextureEditorSourceBinding
from cdmw.ui.texture_workflow.editor_resident_texture import build_texture_editor_resident_patch
from tools.mesh_harness.real_dotnet_material import renderer_identity, renderer_resource_metrics


PRODUCTION_FLOW_STEPS = (
    "ready",
    "select",
    "transform",
    "scalar_update",
    "linked_texture_stroke_1",
    "linked_texture_stroke_2",
    "committed_assignment",
    "uv_edit",
    "duplicate",
    "delete",
    "undo",
    "redo",
    "export",
    "output_reparse",
)


def record_flow_step(state: SimpleNamespace, name: str, **evidence: object) -> None:
    if name not in PRODUCTION_FLOW_STEPS:
        raise ValueError(f"Unknown production Mesh Editor proof step: {name}")
    completed = {str(row.get("step", "")) for row in state.production_flow if isinstance(row, Mapping)}
    expected = PRODUCTION_FLOW_STEPS[len(completed)] if len(completed) < len(PRODUCTION_FLOW_STEPS) else ""
    if name != expected:
        raise RuntimeError(f"Production Mesh Editor proof step out of order: expected {expected}, got {name}")
    state.production_flow.append({"step": name, "ok": True, **evidence})


def production_flow_gates(state: SimpleNamespace) -> dict[str, bool]:
    rows = tuple(getattr(state, "production_flow", ()) or ())
    names = tuple(str(row.get("step", "")) for row in rows if isinstance(row, Mapping) and row.get("ok") is True)
    texture = dict(getattr(state, "texture_flow_evidence", {}) or {})
    edits = dict(getattr(state, "edit_flow_evidence", {}) or {})
    export = dict(getattr(state, "export_flow_evidence", {}) or {})
    lifecycle = dict(getattr(state.tab, "standalone_dotnet_lifecycle_counts", {}) or {})
    current_pid = int(state.tab.standalone_dotnet_editor_process.processId())
    current_windows = dict(getattr(state, "final_window_identity", {}) or {})
    return {
        "production_flow_complete": names == PRODUCTION_FLOW_STEPS,
        "production_process_stable": bool(state.production_process_pid > 0 and current_pid == state.production_process_pid),
        "production_windows_stable": bool(
            all(state.production_window_identity.values()) and current_windows == state.production_window_identity
        ),
        "production_single_process": bool(
            int(lifecycle.get("renderer_process_start_count", 0)) == 1
            and int(lifecycle.get("process_restart_count", 0)) == 0
        ),
        "production_single_initial_package": bool(
            int(lifecycle.get("initial_package_build_count", 0)) == 1
            and int(lifecycle.get("package_build_count", 0)) == 1
            and int(lifecycle.get("full_reload_count", 0)) == 0
        ),
        "linked_texture_updates_applied": bool(texture.get("updates_applied")),
        "linked_texture_queue_bounded": bool(texture.get("queue_bounded")),
        "linked_texture_copy_on_write_once": bool(texture.get("copy_on_write_once")),
        "linked_texture_snapshot_exact": bool(texture.get("snapshot_pixels_match")),
        "linked_texture_exportable": bool(texture.get("painted_derivative_exported")),
        "committed_assignment_exportable": bool(
            texture.get("assignment_in_snapshot") and texture.get("assignment_exported")
        ),
        "uv_topology_undo_redo_applied": bool(getattr(state, "edit_flow_ok", False)),
        "affected_only_geometry_updates": bool(edits.get("affected_only_updates")),
        "coherent_export_snapshot": bool(export.get("coherent_snapshot")),
        "complete_output_reparse": export.get("output_reparse_status") == "passed",
        "export_artifact_hashes_present": bool(export.get("artifact_hashes_present")),
    }


def _latest_settled_topology_metrics(
    state: SimpleNamespace,
    cursor: int,
    *,
    partial_rebuild_floor: int,
    live_batch_count: int,
) -> dict[str, object]:
    for event in reversed(tuple(state.tab.standalone_dotnet_protocol_events)[max(0, int(cursor)) :]):
        if str(event.get("event", "")) != "metrics":
            continue
        renderer = event.get("renderer")
        resources = renderer_resource_metrics(renderer) if isinstance(renderer, Mapping) else {}
        if (
            int(resources.get("partial_topology_rebuilds", 0) or 0) >= int(partial_rebuild_floor)
            and int(resources.get("live_geometry_batches", -1) or -1) == int(live_batch_count)
        ):
            return dict(event)
    return {}


def _target_texture_row(state: SimpleNamespace) -> dict[str, object]:
    rows = [dict(row) for row in state.resolved_textures if isinstance(row, Mapping)]
    matching = [row for row in rows if int(row.get("submesh_index", -1)) == int(state.submesh_index)]
    return (matching or rows)[0]


def _binding(state: SimpleNamespace, row: Mapping[str, object], *, commit_mode: str = "") -> TextureEditorSourceBinding:
    source_path = str(row.get("source_path", "") or "")
    return TextureEditorSourceBinding(
        launch_origin="mesh_editor",
        display_name=Path(source_path).name,
        source_path=source_path,
        relative_path=str(row.get("archive_path", "") or ""),
        archive_relative_path=str(row.get("archive_path", "") or ""),
        original_dds_path=source_path,
        texture_type="mesh_material",
        semantic_subtype=str(row.get("material", "") or "unknown"),
        mesh_session_id=state.controller.active_session_id,
        mesh_resource_id=str(row.get("archive_path", "") or source_path),
        mesh_submesh_indices=(int(row.get("submesh_index", 0) or 0),),
        mesh_channel="base",
        mesh_commit_mode=commit_mode,
    )


def exercise_linked_texture_strokes(
    state: SimpleNamespace,
    *,
    pump_until: Callable[..., bool],
) -> str:
    import numpy as np
    from PIL import Image
    from cdmw.core.texture_editor_project_io import normalize_texture_editor_source_to_png

    row = _target_texture_row(state)
    source = Path(str(row.get("source_path", "") or ""))
    if not source.is_file():
        return f"Resolved production texture is missing: {source}"
    try:
        normalized = normalize_texture_editor_source_to_png(
            source,
            texconv_path=None,
            output_dir=state.output_dir / "texture-editor-normalized",
            output_stem="real-archive-linked-texture",
        )
        with Image.open(normalized) as image:
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    except Exception as exc:
        return f"Production Texture Editor decode failed: {type(exc).__name__}: {exc}"
    height, width = int(rgba.shape[0]), int(rgba.shape[1])
    if width < 2 or height < 1 or width * height > 64 * 1024 * 1024:
        return f"Production texture dimensions are outside the visual-proof ceiling: {width}x{height}"
    binding = _binding(state, row)
    patch_width = min(8, max(1, width // 2))
    patch_height = min(8, height)
    first = rgba.copy()
    first[:patch_height, :patch_width, 0] = np.uint8(255) - first[:patch_height, :patch_width, 0]
    second = first.copy()
    second_x = min(patch_width, width - 1)
    second_width = min(patch_width, width - second_x)
    second[:patch_height, second_x : second_x + second_width, 1] = (
        np.uint8(255) - second[:patch_height, second_x : second_x + second_width, 1]
    )
    before_lifecycle = dict(state.tab.standalone_dotnet_lifecycle_counts)
    before_resources = renderer_resource_metrics(state.renderer)
    cursor = len(state.tab.standalone_dotnet_protocol_events)
    first_patch = build_texture_editor_resident_patch(
        binding,
        first,
        texture_revision=1,
        dirty_bounds=(0, 0, patch_width, patch_height),
    )
    second_patch = build_texture_editor_resident_patch(
        binding,
        second,
        texture_revision=2,
        dirty_bounds=(second_x, 0, second_width, patch_height),
    )
    if not state.tab.apply_texture_editor_region_patch(first_patch):
        second_patch.composite_lease.release()
        return "First linked Texture Editor stroke was rejected."
    if not state.tab.apply_texture_editor_region_patch(second_patch):
        return "Second linked Texture Editor stroke was rejected."
    queued_metrics = state.tab.standalone_texture_region_queue.metrics()
    if not pump_until(state, state.tab._dotnet_texture_updates_idle, 20.0):
        return "Linked Texture Editor strokes did not drain."
    events = [
        dict(event)
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]
        if str(event.get("event", "")) in {"texture_region_applied", "texture_region_failed"}
    ]
    applied = [event for event in events if event.get("event") == "texture_region_applied"]
    if not applied or any(event.get("event") == "texture_region_failed" for event in events):
        return "Linked Texture Editor strokes were not acknowledged by the .NET/Vortice renderer."
    renderer = applied[-1].get("renderer")
    after_resources = renderer_resource_metrics(renderer) if isinstance(renderer, Mapping) else {}
    after_lifecycle = dict(state.tab.standalone_dotnet_lifecycle_counts)
    snapshot = state.controller.mesh_service.capture_export_snapshot(state.controller.active_session_id)
    target_index = int(row.get("submesh_index", 0) or 0)
    painted = [
        resource
        for resource in snapshot.texture_resources
        if resource.channel == "base" and target_index in resource.affected_submeshes and bool(resource.bgra_data)
    ]
    pixels_match = False
    if painted:
        resource = max(painted, key=lambda item: item.revision)
        expected_bgra = np.ascontiguousarray(second[:, :, (2, 1, 0, 3)]).tobytes(order="C")
        pixels_match = resource.bgra_data == expected_bgra
        state.painted_resource_id = resource.resource_id
        state.painted_texture_revision = int(resource.revision)
    state.painted_composite_path = state.output_dir / "linked-painted-real-texture.png"
    with atomic_binary_writer(state.painted_composite_path) as handle:
        Image.fromarray(second, mode="RGBA").save(handle, format="PNG")
    state.painted_composite_sha256 = sha256(second.tobytes(order="C")).hexdigest()
    create_delta = int(after_resources.get("texture_srv_creates", 0) or 0) - int(
        before_resources.get("texture_srv_creates", 0) or 0
    )
    patch_delta = int(after_resources.get("texture_region_patch_count", 0) or 0) - int(
        before_resources.get("texture_region_patch_count", 0) or 0
    )
    state.texture_binding = binding
    state.texture_flow_evidence = {
        "source_path": str(source),
        "source_sha256": str(row.get("source_sha256", "") or ""),
        "normalized_texture_editor_png": str(normalized),
        "dimensions": [width, height],
        "protocol_events": events,
        "queue_after_enqueue": queued_metrics,
        "queue_after_drain": state.tab.standalone_texture_region_queue.metrics(),
        "lifecycle_before": before_lifecycle,
        "lifecycle_after": after_lifecycle,
        "resource_metrics_before": before_resources,
        "resource_metrics_after": after_resources,
        "updates_applied": bool(
            len(applied) >= 1
            and int(after_lifecycle.get("texture_region_update_count", 0))
            - int(before_lifecycle.get("texture_region_update_count", 0))
            == 2
            and int(after_lifecycle.get("texture_region_failed_count", 0))
            == int(before_lifecycle.get("texture_region_failed_count", 0))
        ),
        "queue_bounded": bool(
            int(queued_metrics.get("active_depth", 0) or 0) <= 1
            and int(queued_metrics.get("pending_depth", 0) or 0) <= 1
            and state.tab.standalone_texture_region_queue.idle()
        ),
        "copy_on_write_once": bool(
            create_delta == 1
            and patch_delta == len(applied)
            and int(after_resources.get("editable_texture_resources", 0) or 0)
            == int(before_resources.get("editable_texture_resources", 0) or 0) + 1
        ),
        "snapshot_pixels_match": pixels_match,
        "painted_resource_id": str(getattr(state, "painted_resource_id", "")),
        "painted_texture_revision": int(getattr(state, "painted_texture_revision", 0)),
        "painted_composite_path": str(state.painted_composite_path),
        "painted_composite_sha256": state.painted_composite_sha256,
    }
    record_flow_step(state, "linked_texture_stroke_1", texture_revision=1)
    record_flow_step(state, "linked_texture_stroke_2", texture_revision=2)
    return ""


def _encode_painted_assignment(state: SimpleNamespace) -> tuple[Path | None, str]:
    from cdmw.core.dds_native import inspect_dds_native_path
    from cdmw.core.texture_native import (
        directxtex_texture_failure_reports,
        encode_dds_with_directxtex,
    )
    from cdmw.domain.textures.editor_presets import resolve_texture_editor_dds_preset

    dimensions = tuple(state.texture_flow_evidence.get("dimensions", ()) or ())
    if len(dimensions) != 2:
        return None, "Painted texture dimensions are unavailable for committed assignment."
    width, height = int(dimensions[0]), int(dimensions[1])
    assigned = state.output_dir / "assigned-real-texture.dds"
    preset = resolve_texture_editor_dds_preset("base_color", width=width, height=height)
    dds_format = preset.dds_format
    mip_count = preset.mip_count
    source_path = Path(str(state.texture_flow_evidence.get("source_path", "") or ""))
    try:
        source_info = inspect_dds_native_path(source_path)
    except (OSError, ValueError):
        source_info = None
    if source_info is not None and (source_info.width, source_info.height) == (width, height):
        dds_format = source_info.format_name
        mip_count = source_info.mip_count
    report = encode_dds_with_directxtex(
        state.painted_composite_path,
        assigned,
        dds_format=dds_format,
        width=width,
        height=height,
        mip_count=mip_count,
        overwrite=True,
        timeout_seconds=60.0,
    )
    state.assignment_encode_report = dict(report or {})
    state.assignment_encode_report.update(
        {
            "source_dds_path": str(source_path),
            "source_format_preserved": bool(source_info is not None and dds_format == source_info.format_name),
            "requested_format": dds_format,
            "requested_mip_count": mip_count,
        }
    )
    if not report or not assigned.is_file():
        failures = directxtex_texture_failure_reports()
        if failures:
            state.assignment_encode_report["failure"] = dict(failures[-1])
        reason = str(state.assignment_encode_report.get("failure", {}).get("stderr_summary", "") or "")
        return None, f"Painted real-texture derivative could not be encoded as DDS{': ' + reason if reason else ''}."
    return assigned, ""


def exercise_assignment_and_mesh_edits(
    state: SimpleNamespace,
    *,
    pump_until: Callable[..., bool],
) -> str:
    def apply_update(update: object, timeout_seconds: float = 15.0) -> bool:
        expected_revision = int(state.controller.session_view().revision)
        before = state.tab.standalone_dotnet_update_queue.metrics()
        state.tab._send_dotnet_native_update(update)
        drained = pump_until(
            state,
            lambda: int(state.tab.standalone_dotnet_update_queue.metrics().get("active_revision", 0) or 0) == 0,
            timeout_seconds,
        )
        after = state.tab.standalone_dotnet_update_queue.metrics()
        return bool(
            drained
            and int(after.get("last_acked_revision", 0) or 0) >= expected_revision
            and int(after.get("rejected_updates", 0) or 0)
            == int(before.get("rejected_updates", 0) or 0)
            and int(after.get("ack_timeouts", 0) or 0) == int(before.get("ack_timeouts", 0) or 0)
        )
    source = Path(state.texture_binding.source_path)
    assigned, encode_error = _encode_painted_assignment(state)
    if assigned is None:
        return encode_error
    state.texture_flow_evidence["assignment_encode"] = dict(state.assignment_encode_report)
    binding = replace(state.texture_binding, mesh_commit_mode="assign")
    cursor = len(state.tab.standalone_dotnet_protocol_events)
    if not state.tab.apply_texture_editor_dds_assignment(str(assigned), binding):
        return "Committed real DDS assignment was rejected."
    if not pump_until(
        state,
        lambda: any(
            str(event.get("event", "")) in {"material_state_applied", "material_state_failed"}
            for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]
        ),
        10.0,
    ):
        return "Committed DDS assignment was not acknowledged."
    assignment_events = [
        dict(event)
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]
        if str(event.get("event", "")) in {"material_state_applied", "material_state_failed"}
    ]
    if not assignment_events or assignment_events[-1].get("event") != "material_state_applied":
        return "Committed DDS assignment failed in the resident renderer."
    assigned_snapshot = state.controller.mesh_service.capture_export_snapshot(state.controller.active_session_id)
    assigned_resources = [resource for resource in assigned_snapshot.texture_resources if bool(resource.dds_data)]
    assigned_bytes = source.read_bytes()
    assigned_derivative = assigned.read_bytes()
    matching_assignments = [resource for resource in assigned_resources if resource.dds_data == assigned_derivative]
    assignment_in_snapshot = bool(matching_assignments)
    if matching_assignments:
        assigned_resource = matching_assignments[-1]
        state.assigned_resource_id = assigned_resource.resource_id
        state.assigned_texture_revision = int(assigned_resource.revision)
    state.assigned_dds_sha256 = sha256(assigned_derivative).hexdigest()
    state.texture_flow_evidence["assignment_path"] = str(assigned)
    state.texture_flow_evidence["assignment_protocol_events"] = assignment_events
    state.texture_flow_evidence["assignment_in_snapshot"] = assignment_in_snapshot
    state.texture_flow_evidence["assignment_resource_id"] = str(getattr(state, "assigned_resource_id", ""))
    state.texture_flow_evidence["assignment_texture_revision"] = int(getattr(state, "assigned_texture_revision", 0))
    state.texture_flow_evidence["assignment_dds_sha256"] = state.assigned_dds_sha256
    state.texture_flow_evidence["assignment_is_painted_derivative"] = bool(
        assigned_derivative and assigned_derivative != assigned_bytes
    )
    record_flow_step(state, "committed_assignment", artifact=str(assigned))
    before_resources = dict(state.texture_flow_evidence.get("resource_metrics_after", {}) or {})
    partial_rebuild_floor = int(before_resources.get("partial_topology_rebuilds", 0) or 0) + 4
    restored_live_batches = int(before_resources.get("live_geometry_batches", 0) or 0)
    selection = state.controller.session_view().selection
    uv_before = tuple(tuple(uv) for uv in state.controller.working_mesh(clone=False).submeshes[state.submesh_index].uvs)
    uv_result = state.controller.apply(
        "uv_transform",
        selection=selection,
        mode="edit",
        offset=(1.0 / 1024.0, 0.0),
    )
    if not uv_result.ok or not apply_update(state.controller.native_update_for_result(uv_result), 10.0):
        return "Resident UV edit was rejected."
    uv_after = tuple(tuple(uv) for uv in state.controller.working_mesh(clone=False).submeshes[state.submesh_index].uvs)
    if uv_before == uv_after:
        return "Resident UV edit changed no UV values."
    record_flow_step(state, "uv_edit", revision=uv_result.revision)

    part_selection = MeshEditSelection.from_maps(source_indices=(state.submesh_index,))
    duplicate = state.controller.run_editor_action("duplicate", selection=part_selection, mode="edit")
    if not duplicate.edit_result.ok or not apply_update(duplicate.native_update):
        return "Resident part duplicate was rejected."
    duplicate_index = len(state.controller.working_mesh(clone=False).submeshes) - 1
    record_flow_step(state, "duplicate", revision=duplicate.edit_result.revision, submesh_index=duplicate_index)
    delete_selection = MeshEditSelection.from_maps(source_indices=(duplicate_index,))
    deleted = state.controller.run_editor_action(
        "delete",
        selection=delete_selection,
        mode="edit",
        delete_parts=True,
    )
    if not deleted.edit_result.ok or not apply_update(deleted.native_update):
        return "Resident part delete was rejected."
    record_flow_step(state, "delete", revision=deleted.edit_result.revision, submesh_index=duplicate_index)
    undone = state.controller.undo()
    if not undone.ok or not apply_update(state.controller.native_update_for_result(undone)):
        return "Resident topology undo was rejected."
    record_flow_step(state, "undo", revision=undone.revision)
    metrics_cursor = len(state.tab.standalone_dotnet_protocol_events)
    redone = state.controller.redo()
    if not redone.ok or not apply_update(state.controller.native_update_for_result(redone)):
        return "Resident topology redo was rejected."
    record_flow_step(state, "redo", revision=redone.revision)
    settled = lambda: _latest_settled_topology_metrics(
        state,
        metrics_cursor,
        partial_rebuild_floor=partial_rebuild_floor,
        live_batch_count=restored_live_batches,
    )
    pump_until(state, lambda: bool(settled()), 5.0)
    final_metrics_event = settled()
    final_renderer = final_metrics_event.get("renderer") if final_metrics_event else {}
    final_resources = renderer_resource_metrics(final_renderer) if isinstance(final_renderer, Mapping) else {}
    state.final_window_identity = renderer_identity(final_renderer) if isinstance(final_renderer, Mapping) else {}
    affected_only = bool(
        final_resources
        and int(final_resources.get("full_geometry_rebuilds", 0) or 0)
        == int(before_resources.get("full_geometry_rebuilds", 0) or 0)
        and int(final_resources.get("partial_topology_rebuilds", 0) or 0)
        - int(before_resources.get("partial_topology_rebuilds", 0) or 0)
        >= 4
        and int(final_resources.get("sparse_vertex_updates", 0) or 0)
        > int(before_resources.get("sparse_vertex_updates", 0) or 0)
    )
    topology_restored = len(state.controller.working_mesh(clone=False).submeshes) == len(state.mesh.submeshes)
    state.edit_flow_evidence = {
        "uv_revision": int(uv_result.revision),
        "duplicate_revision": int(duplicate.edit_result.revision),
        "delete_revision": int(deleted.edit_result.revision),
        "undo_revision": int(undone.revision),
        "redo_revision": int(redone.revision),
        "renderer_metrics_event": final_metrics_event,
        "resource_metrics_before": before_resources,
        "resource_metrics_after": final_resources,
        "affected_only_updates": affected_only,
        "topology_restored": topology_restored,
    }
    state.edit_flow_ok = bool(topology_restored and affected_only)
    return ""


def exercise_coherent_export(
    state: SimpleNamespace,
    *,
    pump_until: Callable[..., bool],
) -> str:
    export_dir = state.output_dir / "resident-editable-export"
    if not state.tab._start_standalone_editable_package_export(export_dir):
        return "Resident editable package export did not start."
    if not pump_until(state, lambda: not state.tab._standalone_editable_package_task_active(), 30.0):
        return "Resident editable package export timed out."
    report_path = export_dir / "mesh_export_report.json"
    if not report_path.is_file():
        return "Resident editable package export produced no report."
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"Resident export report could not be read: {exc}"
    artifacts = [dict(row) for row in tuple(report.get("artifacts", ()) or ()) if isinstance(row, Mapping)]
    reparse = dict(report.get("output_reparse", {}) or {})
    current = state.controller.session_view()
    texture_revisions = {
        (str(row.get("resource_id", "")), str(row.get("channel", ""))): int(row.get("revision", 0) or 0)
        for row in tuple(report.get("texture_revisions", ()) or ())
        if isinstance(row, Mapping)
    }
    coherent = bool(
        str(report.get("session_id", "")) == current.session_id
        and int(report.get("mesh_revision", -1) or 0) == current.revision
        and texture_revisions.get((str(state.assigned_resource_id), "base"), 0) == int(state.assigned_texture_revision)
    )
    hashes_present = bool(artifacts) and all(str(row.get("sha256", "")).strip() for row in artifacts)
    artifact_roles = {str(row.get("role", "")) for row in artifacts}
    dds_readback = [dict(row) for row in tuple(reparse.get("dds_readback", ()) or ()) if isinstance(row, Mapping)]
    bindings = [dict(row) for row in tuple(report.get("resolved_texture_bindings", ()) or ()) if isinstance(row, Mapping)]
    assignment_artifacts = [
        row
        for row in artifacts
        if row.get("role") == "texture_dds"
        and str(row.get("resource_id", "")) == str(state.assigned_resource_id)
    ]
    assignment_exported = bool(
        assignment_artifacts
        and assignment_artifacts[-1].get("sha256") == state.assigned_dds_sha256
        and any(str(row.get("resource_id", "")) == str(state.assigned_resource_id) for row in bindings)
    )
    state.texture_flow_evidence["assignment_exported"] = assignment_exported
    state.texture_flow_evidence["painted_derivative_exported"] = bool(
        assignment_exported and state.texture_flow_evidence.get("assignment_is_painted_derivative")
    )
    complete_reparse = bool(
        reparse.get("status") == "passed"
        and int(reparse.get("glb_submesh_count", 0) or 0) > 0
        and int(reparse.get("obj_submesh_count", 0) or 0) > 0
        and dds_readback
        and all(row.get("status") == "passed" for row in dds_readback)
        and {"mesh_glb", "mesh_obj", "mesh_material", "texture_dds"} <= artifact_roles
        and assignment_exported
    )
    state.export_flow_evidence = {
        "report_path": str(report_path),
        "schema": str(report.get("schema", "")),
        "session_id": str(report.get("session_id", "")),
        "mesh_revision": int(report.get("mesh_revision", 0) or 0),
        "material_generation": int(report.get("material_generation", 0) or 0),
        "texture_revisions": list(report.get("texture_revisions", ()) or ()),
        "resolved_texture_bindings": bindings,
        "artifacts": artifacts,
        "output_reparse": reparse,
        "output_reparse_status": "passed" if complete_reparse else "incomplete",
        "coherent_snapshot": coherent,
        "artifact_hashes_present": hashes_present,
        "assignment_artifact": assignment_artifacts[-1] if assignment_artifacts else {},
        "painted_derivative_exported": state.texture_flow_evidence["painted_derivative_exported"],
    }
    record_flow_step(state, "export", report_path=str(report_path))
    if not complete_reparse:
        return "Resident editable package output reparse failed."
    record_flow_step(state, "output_reparse", status="passed")
    return ""


__all__ = [
    "PRODUCTION_FLOW_STEPS",
    "exercise_assignment_and_mesh_edits",
    "exercise_coherent_export",
    "exercise_linked_texture_strokes",
    "production_flow_gates",
    "record_flow_step",
]
