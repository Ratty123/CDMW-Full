"""Headless million-vertex sparse-update performance evidence."""
from __future__ import annotations
import gc
import json
import math
import os
import time
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from PySide6.QtCore import Qt
from cdmw.core.atomic_file import atomic_write_text
from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts, native_mesh_core_available, native_mesh_core_fallback_counts, native_mesh_core_fallback_events
from cdmw.modding.mesh_native_core_temp_paths import release_native_preview_delta_path
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_service import MeshService
from cdmw.ui.mesh_editor.controller import MeshEditorController
from cdmw.ui.mesh_editor.live_stroke_dispatcher import MeshLiveStrokeDispatcher
from cdmw.ui.shell.diagnostics_controller import windows_process_memory_snapshot
SPARSE_SOAK_VERTEX_COUNT = 1000000
SPARSE_SOAK_UPDATE_COUNT = 1000
SPARSE_SOAK_SELECTED_VERTEX_COUNT = 64
SPARSE_SOAK_UPDATE_HZ = 60.0
SPARSE_SOAK_FRAME_BUDGET_MS = 1000.0 / SPARSE_SOAK_UPDATE_HZ

def build_sparse_update_soak_mesh(vertex_count: int=SPARSE_SOAK_VERTEX_COUNT) -> ParsedMesh:
    count = max(3, int(vertex_count))
    columns = max(2, int(math.ceil(math.sqrt(count))))
    vertices = [(float(index % columns), float(index // columns), 0.0) for index in range(count)]
    submesh = SubMesh(name='native_sparse_update_soak', material='benchmark_material', vertices=vertices, faces=[(0, 1, 2)], vertex_count=count, face_count=1)
    return ParsedMesh(path='tools/native_sparse_update_soak.pac', format='pac', bbox_min=(0.0, 0.0, 0.0), bbox_max=(float(columns - 1), float((count - 1) // columns), 0.0), submeshes=[submesh], total_vertices=count, total_faces=1)

def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted((float(value) for value in values))
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]

def _memory_bytes() -> int:
    snapshot = windows_process_memory_snapshot(os.getpid())
    return int(snapshot.get('private_bytes', 0) or snapshot.get('working_set_bytes', 0) or 0)

def _wait_until(deadline: float) -> None:
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0.0:
            return
        if remaining > 0.002:
            time.sleep(max(0.0, remaining - 0.001))

def _consume_owned_delta_payloads(value: object) -> tuple[int, tuple[str, ...]]:
    paths: set[Path] = set()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, Mapping):
            raw_path = str(item.get('path') or '').strip()
            if raw_path and bool(item.get('delete_after')):
                paths.add(Path(raw_path))
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    missing = [str(path) for path in paths if not path.is_file()]
    for path in paths:
        release_native_preview_delta_path(path)
    return (len(paths), tuple(sorted(missing)))

def _sample_vertices(controller: MeshEditorController, indices: tuple[int, ...]) -> tuple[tuple[float, float, float], ...]:
    vertices = controller.working_mesh(clone=False).submeshes[0].vertices
    return tuple((tuple((float(component) for component in vertices[index])) for index in indices))

def run_sparse_update_soak(output_dir: Path, *, vertex_count: int=SPARSE_SOAK_VERTEX_COUNT, update_count: int=SPARSE_SOAK_UPDATE_COUNT, update_hz: float=SPARSE_SOAK_UPDATE_HZ, selected_vertex_count: int=SPARSE_SOAK_SELECTED_VERTEX_COUNT) -> dict[str, object]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    native_available = native_mesh_core_available()
    if not native_available:
        result = {'ok': False, 'native_core_available': False, 'reason': 'native mesh core binary not available'}
        report_path = output_dir / 'native_sparse_update_soak.json'
        atomic_write_text(report_path, json.dumps(result, indent=2, sort_keys=True))
        result['report_path'] = str(report_path)
        return result
    clear_native_mesh_core_fallback_counts()
    build_started = time.perf_counter()
    mesh = build_sparse_update_soak_mesh(vertex_count)
    build_ms = (time.perf_counter() - build_started) * 1000.0
    service = MeshService(max_history=64, max_history_bytes=256 * 1024 * 1024)
    controller = MeshEditorController(mesh_service=service)
    open_started = time.perf_counter()
    view = controller.open_mesh(mesh, session_id='native-sparse-update-soak', mode='edit')
    open_ms = (time.perf_counter() - open_started) * 1000.0
    del mesh
    gc.collect()
    selected_count = min(max(1, int(selected_vertex_count)), max(1, view.vertex_count))
    stride = max(1, view.vertex_count // selected_count)
    selected_indices = tuple((min(view.vertex_count - 1, index * stride) for index in range(selected_count)))
    before = _sample_vertices(controller, selected_indices)
    dispatcher = MeshLiveStrokeDispatcher()
    failures: list[str] = []
    apply_ms: list[float] = []
    metric_samples: dict[str, list[float]] = defaultdict(list)
    completed_update_count = 0
    consumed_preview_delta_count = 0
    missing_preview_delta_paths: list[str] = []

    def record_outcome(outcome: object) -> None:
        nonlocal completed_update_count, consumed_preview_delta_count
        is_update = str(getattr(outcome, 'phase', '') or '') == 'update'
        if is_update:
            completed_update_count += 1
        result = getattr(outcome, 'result', None)
        metrics = getattr(result, 'metrics', {})
        if is_update and isinstance(metrics, Mapping):
            for key, value in metrics.items():
                if isinstance(value, (int, float)):
                    metric_samples[str(key)].append(float(value))
            elapsed = float(metrics.get('service_total_ms', 0.0) or 0.0)
            if elapsed > 0.0:
                apply_ms.append(elapsed)
        native_update = getattr(outcome, 'native_update', None)
        consumed, missing = _consume_owned_delta_payloads((getattr(native_update, 'vertex_groups', ()), getattr(native_update, 'triangle_groups', ()), getattr(native_update, 'selection_groups', ())))
        consumed_preview_delta_count += consumed
        missing_preview_delta_paths.extend(missing)
    dispatcher.completed.connect(record_outcome, Qt.ConnectionType.DirectConnection)
    dispatcher.failed.connect(lambda failure: failures.append(str(getattr(failure, 'message', failure))), Qt.ConnectionType.DirectConnection)
    submit_ms: list[float] = []
    queue_depth_max = 0
    warmup_memory_bytes = 0
    post_update_memory_bytes = 0
    stroke_id = 'million-vertex-sparse-soak'

    def submit(phase: str, delta_z: float=0.0) -> int:
        nonlocal queue_depth_max
        params: dict[str, object] = {'stroke_phase': phase, 'stroke_id': stroke_id, 'recompute_normals': False, 'record_history': True, '_require_native_history_delta': True, '_include_preview_deltas': True}
        selection = MeshEditSelection()
        if phase == 'begin':
            selection = MeshEditSelection.from_maps(vertices_by_submesh={0: selected_indices})
        if phase in {'begin', 'update'}:
            params['delta'] = (0.0, 0.0, float(delta_z))
        command = MeshEditCommand('transform', selection=selection, params=params, mode='edit')
        started = time.perf_counter()
        sequence = dispatcher.submit(controller, command, phase)
        submit_ms.append((time.perf_counter() - started) * 1000.0)
        queue_depth_max = max(queue_depth_max, int(dispatcher.metrics().get('queue_depth', 0) or 0))
        return sequence
    try:
        submit('begin', 1e-06)
        if not dispatcher.wait_idle(60.0):
            raise TimeoutError('sparse soak begin did not become idle')
        gc.collect()
        warmup_memory_bytes = _memory_bytes()
        period = 1.0 / max(0.0, float(update_hz)) if update_hz > 0 else 0.0
        next_tick = time.perf_counter()
        cadence_started = next_tick
        for index in range(max(1, int(update_count))):
            if period > 0.0:
                _wait_until(next_tick)
            submit('update', 1e-06)
            next_tick += period
        cadence_elapsed_seconds = max(0.0, time.perf_counter() - cadence_started)
        submit('end')
        idle_ok = dispatcher.wait_idle(120.0)
        gc.collect()
        post_update_memory_bytes = _memory_bytes()
        after = _sample_vertices(controller, selected_indices)
        undo_result = service.undo(view.session_id)
        undo_update = controller.native_update_for_result(undo_result)
        consumed, missing = _consume_owned_delta_payloads((undo_update.vertex_groups, undo_update.triangle_groups))
        consumed_preview_delta_count += consumed
        missing_preview_delta_paths.extend(missing)
        undo_vertices = _sample_vertices(controller, selected_indices)
        redo_result = service.redo(view.session_id)
        redo_update = controller.native_update_for_result(redo_result)
        consumed, missing = _consume_owned_delta_payloads((redo_update.vertex_groups, redo_update.triangle_groups))
        consumed_preview_delta_count += consumed
        missing_preview_delta_paths.extend(missing)
        redo_vertices = _sample_vertices(controller, selected_indices)
        history = service.history_usage(view.session_id)
    except Exception as exc:
        idle_ok = False
        cadence_elapsed_seconds = 0.0
        after = ()
        undo_vertices = ()
        redo_vertices = ()
        undo_result = redo_result = None
        history = {}
        failures.append(f'{type(exc).__name__}: {exc}')
    finally:
        dispatcher.stop(10.0)
        controller.close_active_session()
    submission_p95_ms = _percentile(submit_ms, 0.95)
    native_apply_p95_ms = _percentile(apply_ms, 0.95)
    handler_p95_ms = max(submission_p95_ms, native_apply_p95_ms)
    memory_growth_ratio = max(0.0, (post_update_memory_bytes - warmup_memory_bytes) / float(warmup_memory_bytes)) if warmup_memory_bytes > 0 else 0.0
    memory_evidence_available = warmup_memory_bytes > 0 and post_update_memory_bytes > 0
    memory_ok = memory_growth_ratio < 0.1 if memory_evidence_available else os.name != 'nt'
    exact_undo_ok = bool(getattr(undo_result, 'ok', False) and undo_vertices == before)
    exact_redo_ok = bool(getattr(redo_result, 'ok', False) and redo_vertices == after and (after != before))
    history_ok = bool(history and int(history.get('undo_count', 0)) <= 64 and (int(history.get('retained_bytes', 0)) <= 256 * 1024 * 1024))
    fallback_counts = native_mesh_core_fallback_counts()
    coalesced_update_count = int(dispatcher.metrics().get('coalesced_updates', 0) or 0)
    accounted_update_count = completed_update_count + coalesced_update_count
    processed_update_ratio = completed_update_count / max(1, int(update_count))
    effective_update_hz = int(update_count) / cadence_elapsed_seconds if cadence_elapsed_seconds > 0.0 else 0.0
    cadence_ok = update_hz <= 0.0 or float(update_hz) * 0.9 <= effective_update_hz <= float(update_hz) * 1.02
    metric_p95_ms = {key: _percentile(values, 0.95) for key, values in sorted(metric_samples.items()) if key.endswith('_ms') and values}
    metric_max_ms = {key: max(values) for key, values in sorted(metric_samples.items()) if key.endswith('_ms') and values}
    result = {'ok': bool(idle_ok and (not failures) and (handler_p95_ms < SPARSE_SOAK_FRAME_BUDGET_MS) and (queue_depth_max <= 1) and (accounted_update_count == int(update_count)) and cadence_ok and exact_undo_ok and exact_redo_ok and history_ok and memory_ok and (not missing_preview_delta_paths) and (not fallback_counts)), 'schema_version': 1, 'native_core_available': native_available, 'vertex_count': int(vertex_count), 'selected_vertex_count': selected_count, 'update_count': int(update_count), 'update_hz': float(update_hz), 'frame_budget_ms': SPARSE_SOAK_FRAME_BUDGET_MS, 'handler_p95_ms': handler_p95_ms, 'submission_p95_ms': submission_p95_ms, 'native_apply_p95_ms': native_apply_p95_ms, 'handler_max_ms': max(max(submit_ms, default=0.0), max(apply_ms, default=0.0)), 'native_apply_max_ms': max(apply_ms, default=0.0), 'metric_p95_ms': metric_p95_ms, 'metric_max_ms': metric_max_ms, 'completed_update_count': completed_update_count, 'coalesced_update_count': coalesced_update_count, 'accounted_update_count': accounted_update_count, 'processed_update_ratio': processed_update_ratio, 'cadence_elapsed_seconds': cadence_elapsed_seconds, 'effective_update_hz': effective_update_hz, 'cadence_ok': cadence_ok, 'consumed_preview_delta_count': consumed_preview_delta_count, 'missing_preview_delta_paths': missing_preview_delta_paths, 'preview_delta_cleanup_ok': not missing_preview_delta_paths, 'queue_depth_max': queue_depth_max, 'dispatcher_metrics': dispatcher.metrics(), 'idle_ok': idle_ok, 'exact_undo_ok': exact_undo_ok, 'exact_redo_ok': exact_redo_ok, 'history': history, 'history_ok': history_ok, 'warmup_memory_bytes': warmup_memory_bytes, 'post_update_memory_bytes': post_update_memory_bytes, 'post_warmup_memory_growth_ratio': memory_growth_ratio, 'memory_evidence_available': memory_evidence_available, 'memory_ok': memory_ok, 'build_ms': build_ms, 'open_ms': open_ms, 'failures': failures, 'native_fallback_counts': fallback_counts, 'native_fallback_events': list(native_mesh_core_fallback_events())}
    report_path = output_dir / 'native_sparse_update_soak.json'
    atomic_write_text(report_path, json.dumps(result, indent=2, sort_keys=True))
    result['report_path'] = str(report_path)
    return result
__all__ = ['SPARSE_SOAK_UPDATE_COUNT', 'SPARSE_SOAK_UPDATE_HZ', 'SPARSE_SOAK_VERTEX_COUNT', 'build_sparse_update_soak_mesh', 'run_sparse_update_soak']
