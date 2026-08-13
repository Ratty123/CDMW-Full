from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from cdmw.core.atomic_file import atomic_binary_writer
from cdmw.domain.mesh.editing import MeshEditCommand, MeshEditSelection
from cdmw.domain.mesh.topology import validate_topology_provenance
from cdmw.models import TextureEditorSourceBinding
from cdmw.ui.texture_workflow.editor_resident_texture import build_texture_editor_resident_patch
from tools.mesh_harness.real_dotnet_material import (
    renderer_identity,
    renderer_resource_metrics,
    request_full_renderer_status,
)


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
    # Last, because it deliberately leaves a topology-changed session behind for
    # the exact PAC LOD0 writer and every earlier step wants the original
    # connectivity.
    "topology_rebuild",
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
        "linked_texture_mip_chain_preserved": bool(texture.get("mip_chain_preserved")),
        "linked_texture_snapshot_exact": bool(texture.get("snapshot_pixels_match")),
        "linked_texture_exportable": bool(texture.get("painted_derivative_exported")),
        "committed_assignment_exportable": bool(
            texture.get("assignment_in_snapshot") and texture.get("assignment_exported")
        ),
        "uv_topology_undo_redo_applied": bool(getattr(state, "edit_flow_ok", False)),
        "affected_only_geometry_updates": bool(edits.get("affected_only_updates")),
        "coherent_export_snapshot": bool(export.get("coherent_snapshot")),
        "export_source_asset_hash_matches": bool(export.get("source_asset_hash_matches")),
        "complete_output_reparse": export.get("output_reparse_status") == "passed",
        "export_artifact_hashes_present": bool(export.get("artifact_hashes_present")),
        "exact_topology_rebuild": bool(getattr(state, "topology_rebuild_ok", False)),
        "exact_topology_rebuild_no_fallback": bool(
            dict(getattr(state, "topology_rebuild_evidence", {}) or {})
            .get("rebuild_report", {})
            .get("fallback_used")
            is False
        ),
    }


def _latest_settled_topology_metrics(
    state: SimpleNamespace,
    cursor: int,
    *,
    partial_rebuild_floor: int,
    live_batch_count: int,
) -> dict[str, object]:
    events = tuple(state.tab.standalone_dotnet_protocol_events)
    start = max(0, int(cursor))
    candidates = events[start:] if start < len(events) else events
    for event in reversed(candidates):
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


def _latest_presented_topology_metrics(
    state: SimpleNamespace,
    cursor: int,
    *,
    topology_generation_floor: int,
) -> dict[str, object]:
    events = tuple(state.tab.standalone_dotnet_protocol_events)
    for event in reversed(events[max(0, int(cursor)) :]):
        if str(event.get("event", "")) != "metrics":
            continue
        renderer = event.get("renderer")
        resources = renderer_resource_metrics(renderer) if isinstance(renderer, Mapping) else {}
        if int(resources.get("topology_generation", 0) or 0) >= int(topology_generation_floor):
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
    state.performance_texture_binding = binding
    state.performance_texture_variants = (first, second)
    state.performance_texture_dirty_bounds = (
        (0, 0, patch_width, patch_height),
        (second_x, 0, second_width, patch_height),
    )
    state.performance_texture_revision = 2
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
    mip_generation_delta = int(after_resources.get("texture_region_mip_generation_count", 0) or 0) - int(
        before_resources.get("texture_region_mip_generation_count", 0) or 0
    )
    resource_id = str(getattr(state, "painted_resource_id", "") or binding.mesh_resource_id or "")
    source_diagnostics = tuple(before_resources.get("texture_resource_diagnostics", ()) or ())
    source_mip_count = next(
        (
            int(item.get("source_mip_count", 0) or 0)
            for item in source_diagnostics
            if isinstance(item, Mapping) and str(item.get("resource_id", "") or "") == resource_id
        ),
        0,
    )
    editable_mip_levels = after_resources.get("editable_texture_mip_levels", {})
    editable_mip_count = int(
        editable_mip_levels.get(resource_id, 0) or 0
        if isinstance(editable_mip_levels, Mapping)
        else 0
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
        "source_mip_count": source_mip_count,
        "editable_mip_count": editable_mip_count,
        "mip_generation_delta": mip_generation_delta,
        "mip_chain_preserved": bool(
            source_mip_count > 1
            and editable_mip_count >= source_mip_count
            and mip_generation_delta == len(applied)
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


def _record_apply_update_evidence(
    state: SimpleNamespace,
    update: object,
    expected_revision: int,
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    topology_generation_floor: int | None,
    topology_presented: bool,
) -> None:
    evidence = {
        "expected_revision": expected_revision,
        "vertex_group_count": len(tuple(getattr(update, "vertex_groups", ()) or ())),
        "triangle_group_count": len(tuple(getattr(update, "triangle_groups", ()) or ())),
        "triangle_source_submesh_indices": list(
            tuple(getattr(update, "triangle_source_submesh_indices", ()) or ())
        ),
        "replace_all_triangles": bool(getattr(update, "replace_all_triangles", False)),
        "final_submesh_count": getattr(update, "final_submesh_count", None),
        "refresh_selection": bool(getattr(update, "refresh_selection", False)),
        "topology_generation_floor": topology_generation_floor,
        "topology_presented": topology_presented,
        "before": dict(before),
        "after": dict(after),
    }
    state.last_apply_update_evidence = evidence
    state.apply_update_evidence.append(evidence)


def _commit_painted_assignment(
    state: SimpleNamespace,
    pump_until: Callable[..., bool],
) -> str:
    source = Path(state.texture_binding.source_path)
    assigned, encode_error = _encode_painted_assignment(state)
    if assigned is None:
        return encode_error
    state.texture_flow_evidence["assignment_encode"] = dict(state.assignment_encode_report)
    binding = replace(state.texture_binding, mesh_commit_mode="assign")
    cursor = len(state.tab.standalone_dotnet_protocol_events)
    if not state.tab.apply_texture_editor_dds_assignment(str(assigned), binding):
        return "Committed real DDS assignment was rejected."
    def _local_material_failures() -> int:
        return int(
            state.tab.standalone_dotnet_lifecycle_counts.get("material_state_failed_count", 0) or 0
        )

    failures_before = _local_material_failures()

    def assignment_settled() -> bool:
        if any(
            str(event.get("event", "")) in {"material_state_applied", "material_state_failed"}
            for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]
        ):
            return True
        # A compile that fails before it reaches the helper emits no protocol
        # event at all, so waiting for one can only ever time out. Treat the
        # local failure counter as a settled outcome and report why below.
        return _local_material_failures() > failures_before

    # The assignment recompiles real materials with a freshly encoded DDS; the
    # pre-migration 10s budget did not cover that work.
    if not pump_until(state, assignment_settled, 45.0):
        return "Committed DDS assignment was not acknowledged."
    if _local_material_failures() > failures_before and not any(
        str(event.get("event", "")) == "material_state_applied"
        for event in tuple(state.tab.standalone_dotnet_protocol_events)[cursor:]
    ):
        reason = next(
            (
                str(entry.get("message", ""))
                for entry in reversed(tuple(getattr(state, "status_messages", ()) or ()))
                if entry.get("error")
            ),
            "no status message was recorded",
        )
        return f"Committed DDS assignment failed to compile before reaching the renderer: {reason}"
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
    return ""


def exercise_assignment_and_mesh_edits(
    state: SimpleNamespace,
    *,
    pump_until: Callable[..., bool],
) -> str:
    state.apply_update_evidence = []
    state.history_result_evidence = []
    def apply_update(
        update: object,
        timeout_seconds: float = 15.0,
        *,
        topology_generation_floor: int | None = None,
    ) -> bool:
        expected_revision = int(state.controller.session_view().revision)
        before = state.tab.standalone_dotnet_update_queue.metrics()
        event_cursor = len(state.tab.standalone_dotnet_protocol_events)
        state.tab._send_dotnet_native_update(update)
        drained = pump_until(
            state,
            lambda: int(state.tab.standalone_dotnet_update_queue.metrics().get("active_revision", 0) or 0) == 0,
            timeout_seconds,
        )
        after = state.tab.standalone_dotnet_update_queue.metrics()
        topology_presented = topology_generation_floor is None
        if drained and topology_generation_floor is not None:
            topology_presented = pump_until(
                state,
                lambda: bool(
                    _latest_presented_topology_metrics(
                        state,
                        event_cursor,
                        topology_generation_floor=topology_generation_floor,
                    )
                ),
                timeout_seconds,
            )
        _record_apply_update_evidence(
            state,
            update,
            expected_revision,
            before,
            after,
            topology_generation_floor=topology_generation_floor,
            topology_presented=topology_presented,
        )
        return bool(
            drained
            and topology_presented
            and int(after.get("last_acked_revision", 0) or 0) >= expected_revision
            and int(after.get("rejected_updates", 0) or 0)
            == int(before.get("rejected_updates", 0) or 0)
            and int(after.get("ack_timeouts", 0) or 0) == int(before.get("ack_timeouts", 0) or 0)
        )
    assignment_error = _commit_painted_assignment(state, pump_until)
    if assignment_error:
        return assignment_error
    before_resources = dict(state.texture_flow_evidence.get("resource_metrics_after", {}) or {})
    partial_rebuild_floor = int(before_resources.get("partial_topology_rebuilds", 0) or 0) + 4
    topology_generation_floor = int(before_resources.get("topology_generation", 0) or 0) + 4
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
    if not duplicate.edit_result.ok or not apply_update(
        duplicate.native_update,
        topology_generation_floor=topology_generation_floor - 3,
    ):
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
    if not deleted.edit_result.ok or not apply_update(
        deleted.native_update,
        topology_generation_floor=topology_generation_floor - 2,
    ):
        return "Resident part delete was rejected."
    record_flow_step(state, "delete", revision=deleted.edit_result.revision, submesh_index=duplicate_index)
    undone = state.controller.undo()
    state.history_result_evidence.append(
        {
            "action": undone.action,
            "revision": int(undone.revision),
            "topology_changed": bool(undone.topology_changed),
            "submesh_count_delta": int(undone.submesh_count_delta),
            "native_vertex_group_count": len(tuple(undone.native_preview_vertex_update_groups or ())),
            "native_triangle_group_count": len(tuple(undone.native_preview_triangle_groups or ())),
        }
    )
    if not undone.ok or not apply_update(
        state.controller.native_update_for_result(undone),
        topology_generation_floor=topology_generation_floor - 1,
    ):
        return "Resident topology undo was rejected."
    record_flow_step(state, "undo", revision=undone.revision)
    metrics_cursor = len(state.tab.standalone_dotnet_protocol_events)
    redone = state.controller.redo()
    state.history_result_evidence.append(
        {
            "action": redone.action,
            "revision": int(redone.revision),
            "topology_changed": bool(redone.topology_changed),
            "submesh_count_delta": int(redone.submesh_count_delta),
            "native_vertex_group_count": len(tuple(redone.native_preview_vertex_update_groups or ())),
            "native_triangle_group_count": len(tuple(redone.native_preview_triangle_groups or ())),
        }
    )
    if not redone.ok or not apply_update(
        state.controller.native_update_for_result(redone),
        topology_generation_floor=topology_generation_floor,
    ):
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
    # The settled metrics event proves the geometry work drained, but its
    # payload is the slim per-frame one: no viewport identity and no texture
    # resource counters. Ask the renderer for a full status for those.
    final_status = request_full_renderer_status(state, pump_until)
    final_renderer = final_status or (final_metrics_event.get("renderer") if final_metrics_event else {})
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
        "apply_updates": list(state.apply_update_evidence),
        "history_results": list(state.history_result_evidence),
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
        status = str(state.tab.standalone_status_label.text() or "").strip()
        pending = state.tab.standalone_dotnet_pending_material_parameter_payload
        sent = state.tab.standalone_dotnet_sent_material_parameter_payload
        ordering = {
            "revision": state.tab.standalone_dotnet_material_parameter_revision,
            "generation": state.tab.standalone_dotnet_material_parameter_generation,
            "sent_generation": state.tab.standalone_dotnet_sent_material_parameter_generation,
            "completed_generation": state.tab.standalone_dotnet_completed_material_parameter_generation,
        }
        return (
            f"Resident editable package export produced no report. {status} "
            f"Pending material parameters: {pending!r}. Sent material parameters: {sent!r}. "
            f"Material parameter ordering: {ordering!r}."
        ).strip()
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
    source_asset_hash = str(report.get("source_asset_hash", "") or "").strip().lower()
    original_hash_path = export_dir / "original_asset_hash.txt"
    sidecar_path = export_dir / "mesh.cdmeta.json"
    try:
        original_asset_hash = original_hash_path.read_text(encoding="utf-8").strip().lower()
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar_source_asset_hash = str(sidecar.get("source_asset_hash", "") or "").strip().lower()
    except (OSError, ValueError):
        original_asset_hash = ""
        sidecar_source_asset_hash = ""
    expected_source_asset_hash = str(state.source_payload_sha256 or "").strip().lower()
    source_asset_hash_matches = bool(
        expected_source_asset_hash
        and source_asset_hash == expected_source_asset_hash
        and original_asset_hash == expected_source_asset_hash
        and sidecar_source_asset_hash == expected_source_asset_hash
    )
    state.texture_flow_evidence["assignment_exported"] = assignment_exported
    state.texture_flow_evidence["painted_derivative_exported"] = bool(
        assignment_exported and state.texture_flow_evidence.get("assignment_is_painted_derivative")
    )
    complete_reparse = bool(
        reparse.get("status") == "passed"
        and reparse.get("draw_section_lineage_readback") == "passed"
        and reparse.get("rig_skinning_readback") == "passed"
        and reparse.get("reference_metadata_readback") == "passed"
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
        "source_asset_hash": source_asset_hash,
        "original_asset_hash": original_asset_hash,
        "sidecar_source_asset_hash": sidecar_source_asset_hash,
        "expected_source_asset_hash": expected_source_asset_hash,
        "source_asset_hash_matches": source_asset_hash_matches,
        "assignment_artifact": assignment_artifacts[-1] if assignment_artifacts else {},
        "painted_derivative_exported": state.texture_flow_evidence["painted_derivative_exported"],
    }
    record_flow_step(state, "export", report_path=str(report_path))
    if not complete_reparse:
        return "Resident editable package output reparse failed."
    record_flow_step(state, "output_reparse", status="passed")
    return ""


def exercise_exact_topology_rebuild(state: SimpleNamespace, *, pump_until: Callable[..., bool]) -> str:
    """Face Delete the same real PAC, then rebuild it exactly into its own LOD0.

    This runs on its own resident session over the same archive payload the
    visual flow used, not on the flow's session. By this point that session has
    a committed texture assignment and an Auto UV edit, which the export
    validator blocks for reasons that have nothing to do with topology; reusing
    it would test those blockers rather than this contract. The payload is read
    from the archive again, so the proof is still real game data and still
    read-only.
    """
    from cdmw.domain.mesh.skeleton import summarize_mesh_skinning
    from cdmw.modding.mesh_parser import parse_pac
    from cdmw.services.mesh_service import MeshService
    from tools.mesh_harness.real_common import _read_archive_payload

    original_data = _read_archive_payload(state.model_entry)
    if sha256(original_data).hexdigest() != state.source_payload_sha256:
        return "Real PAC payload changed between the visual flow and the rebuild proof."
    mesh = parse_pac(original_data, state.model_entry.path)
    # The session needs the source bytes to rebuild into them at all; without
    # this the snapshot has nothing to write back over.
    setattr(mesh, "_cdmw_original_data", original_data)
    part_index = next(
        (
            index
            for index, submesh in enumerate(mesh.submeshes)
            if len(tuple(submesh.faces or ())) >= 4
            and int(getattr(submesh, "source_vertex_stride", 0) or 0) == 40
        ),
        -1,
    )
    if part_index < 0:
        return "No proven 40-byte PAC part with enough faces to Face Delete."
    face_count_before = len(tuple(mesh.submeshes[part_index].faces or ()))

    service = MeshService()
    session_id = f"{state.controller.active_session_id}-topology-rebuild"
    view = service.open_edit_session(mesh, session_id=session_id, mode="edit")
    try:
        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(faces_by_submesh={part_index: (0,)}),
                params={"operation": "replace"},
                mode="edit",
            ),
        )
        deleted = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "delete",
                selection=MeshEditSelection.from_maps(faces_by_submesh={part_index: (0,)}),
                params={"_include_preview_deltas": False},
                mode="edit",
            ),
        )
        if not deleted.ok:
            return "Resident Face Delete was rejected on the real PAC part."

        edited = service.working_mesh(view.session_id, clone=True)
        submesh = edited.submeshes[part_index]
        provenance = getattr(submesh, "topology_provenance", None)
        output_faces = len(tuple(submesh.faces or ()))
        if output_faces < 1 or output_faces >= face_count_before:
            return "Face Delete did not remove a triangle while retaining geometry."
        if provenance is None or validate_topology_provenance(
            provenance,
            output_vertex_count=len(tuple(submesh.vertices or ())),
            output_face_count=output_faces,
        ):
            return "Resident Face Delete produced no usable topology contract."

        output_path = Path(state.output_dir) / "topology_rebuild" / "rebuilt_lod0.pac"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # This session is opened straight from archive bytes, so it has no
        # skeleton link the way the visual flow's session does. The skinned-mesh
        # gate wants the bone count the skinning actually references, which the
        # mesh itself proves.
        skeleton_bone_count = int(summarize_mesh_skinning(mesh).inferred_bone_count or 0) or None
        report = service.rebuild_asset(
            view.session_id, output_path, skeleton_bone_count=skeleton_bone_count
        )
        topology_report = dict(getattr(report, "topology_rebuild", {}) or {})
        if topology_report.get("serializer") != "pac_lod0_topology_exact_v1":
            return f"Rebuild did not use the exact topology serializer: {topology_report.get('serializer')!r}."
        if topology_report.get("fallback_used") is not False:
            return "Exact topology rebuild reported a fallback."

        rebuilt_bytes = output_path.read_bytes()
        reparsed = parse_pac(rebuilt_bytes, str(output_path))
        reparsed_part = reparsed.submeshes[part_index] if part_index < len(reparsed.submeshes) else None
        if reparsed_part is None:
            return "Rebuilt PAC lost the edited part on reparse."
        reparse_ok = bool(
            len(reparsed.submeshes) == len(edited.submeshes)
            and len(tuple(reparsed_part.vertices or ())) == len(tuple(submesh.vertices or ()))
            and len(tuple(reparsed_part.faces or ())) == output_faces
            and tuple(tuple(face) for face in reparsed_part.faces)
            == tuple(tuple(int(value) for value in face[:3]) for face in submesh.faces)
        )
        base_part = mesh.submeshes[part_index]
        bounds_preserved = bool(
            reparsed_part.source_bbox_min == base_part.source_bbox_min
            and reparsed_part.source_bbox_extent == base_part.source_bbox_extent
        )
        state.topology_rebuild_evidence = {
            "model_path": state.model_entry.path,
            "part_index": part_index,
            "face_count_before": face_count_before,
            "face_count_after": output_faces,
            "vertex_count_after": len(tuple(submesh.vertices or ())),
            "original_vertex_count": provenance.original_vertex_count,
            "original_face_count": provenance.original_face_count,
            "direct_vertex_count": provenance.direct_vertex_count,
            "blended_vertex_count": provenance.derived_vertex_count,
            "operations": [
                dict(operation) if isinstance(operation, Mapping) else operation
                for operation in tuple(getattr(report, "edit_operations", ()) or ())
            ],
            "rebuild_report": topology_report,
            "output_path": str(output_path),
            "output_sha256": sha256(rebuilt_bytes).hexdigest(),
            "output_bytes": len(rebuilt_bytes),
            "source_payload_sha256": state.source_payload_sha256,
            "reparse_ok": reparse_ok,
            "bounds_preserved": bounds_preserved,
            "delete_revision": int(deleted.revision),
        }
        state.topology_rebuild_ok = bool(reparse_ok and bounds_preserved)
        if not state.topology_rebuild_ok:
            return "Rebuilt PAC did not reparse into the authored LOD0 with the source bounds."
    finally:
        service.close_edit_session(view.session_id)
    record_flow_step(state, "topology_rebuild", part_index=part_index, output_path=str(output_path))
    return ""


__all__ = [
    "PRODUCTION_FLOW_STEPS",
    "exercise_assignment_and_mesh_edits",
    "exercise_coherent_export",
    "exercise_exact_topology_rebuild",
    "exercise_linked_texture_strokes",
    "production_flow_gates",
    "record_flow_step",
]
