from __future__ import annotations
from pathlib import Path
from tools.mesh_harness.sparse_update_soak import run_sparse_update_soak
from tools.mesh_harness.scenario_registry import scenario_metadata
from tools.mesh_harness.constants import _DEFAULT_GAME_ROOT, _DOTNET_NATIVE_PARITY_SCENARIO, _REAL_MESH_EDITOR_VISUAL_SCENARIO
from tools.mesh_harness.asset_authoring import run_asset_authoring_discovery, run_asset_authoring_mesh_health, run_asset_authoring_openimageio_report, run_asset_authoring_tangent_report, run_asset_authoring_uv_report
from tools.mesh_harness.evidence import _mesh_editor_evidence_report, _write_json_atomic
from tools.mesh_harness.native_strokes import run_native_mesh_editor_standalone_stroke, run_native_mesh_editor_static_replacement_screen_stroke
from tools.mesh_harness.native_workflow import run_long_edit_mesh_tools, run_native_mesh_editor_benchmark, run_native_mesh_editor_workflow
from tools.mesh_harness.parity import (
    DEFAULT_PARITY_DIFFERENCE_SCALE,
    DEFAULT_PARITY_FAIL_PERCENT,
    DEFAULT_PARITY_FAIL_THRESHOLD,
    DEFAULT_PARITY_HARD_FAIL_THRESHOLD,
    run_mesh_dotnet_native_parity_report,
)
from tools.mesh_harness.performance_contract import resolve_performance_request
from tools.mesh_harness.qt_probes import run_native_mesh_editor_qt_cancellation, run_native_mesh_editor_qt_responsiveness
from tools.mesh_harness.real_animation import run_real_archive_animation_binding_smoke
from tools.mesh_harness.real_app import run_real_archive_app_workflow_smoke
from tools.mesh_harness.real_rigging import run_real_archive_rigging_smoke
from tools.mesh_harness.real_sequence import run_real_archive_sequence_binding_smoke
from tools.mesh_harness.service_smoke import run_service_smoke

def _apply_backend_gate(
    proof: dict[str, object],
    *,
    expected_renderer_backend: str,
    expected_edit_backend: str,
) -> dict[str, object]:
    gated = dict(proof)
    renderer_backend = str(gated.get("renderer_backend", "") or "").strip()
    edit_backend = str(gated.get("edit_backend", "") or "").strip()
    renderer_ok = renderer_backend == expected_renderer_backend
    edit_ok = edit_backend == expected_edit_backend
    gated.update(
        {
            "expected_renderer_backend": expected_renderer_backend,
            "expected_edit_backend": expected_edit_backend,
            "renderer_backend_ok": renderer_ok,
            "edit_backend_ok": edit_ok,
            "backend_gate_ok": renderer_ok and edit_ok,
        }
    )
    gated["ok"] = bool(gated.get("ok") and gated["backend_gate_ok"])
    return gated

def run_scenario(
    scenario: str,
    output_dir: Path,
    *,
    game_root: Path | str | None = None,
    allow_synthetic_d3d11: bool = False,
    parity_reference: Path | str | None = None,
    parity_candidate: Path | str | None = None,
    openimageio_path: Path | str | None = None,
    parity_fail_threshold: float = DEFAULT_PARITY_FAIL_THRESHOLD,
    parity_fail_percent: float = DEFAULT_PARITY_FAIL_PERCENT,
    parity_hard_fail_threshold: float = DEFAULT_PARITY_HARD_FAIL_THRESHOLD,
    parity_difference_scale: float = DEFAULT_PARITY_DIFFERENCE_SCALE,
    performance_manifest: Path | str | None = None,
    performance_duration_seconds: float | None = None,
    performance_target_hz: float | None = None,
) -> dict[str, object]:
    performance_request = resolve_performance_request(
        scenario,
        performance_manifest,
        duration_seconds=performance_duration_seconds,
        target_hz=performance_target_hz,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = scenario_metadata(scenario)
    del allow_synthetic_d3d11
    if scenario == 'asset-authoring-discovery':
        discovery_result = run_asset_authoring_discovery(output_dir)
        result = {'scenario': scenario, 'ok': bool(discovery_result.get('ok')), 'asset_authoring': discovery_result}
    elif scenario == 'asset-authoring-mesh-health':
        health_result = run_asset_authoring_mesh_health(output_dir)
        result = {'scenario': scenario, 'ok': bool(health_result.get('ok')), 'asset_authoring': health_result}
    elif scenario == 'asset-authoring-uv-report':
        uv_result = run_asset_authoring_uv_report(output_dir)
        result = {'scenario': scenario, 'ok': bool(uv_result.get('ok')), 'asset_authoring': uv_result}
    elif scenario == 'asset-authoring-tangent-report':
        tangent_result = run_asset_authoring_tangent_report(output_dir)
        result = {'scenario': scenario, 'ok': bool(tangent_result.get('ok')), 'asset_authoring': tangent_result}
    elif scenario == 'asset-authoring-openimageio-report':
        openimageio_result = run_asset_authoring_openimageio_report(output_dir)
        result = {'scenario': scenario, 'ok': bool(openimageio_result.get('ok')), 'asset_authoring': openimageio_result}
    elif scenario == 'real-archive-rigging-smoke':
        real_archive_result = run_real_archive_rigging_smoke(Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT)
        result = {'scenario': scenario, 'ok': bool(real_archive_result.get('ok')), 'real_archive': real_archive_result}
    elif scenario == 'real-archive-animation-binding-smoke':
        animation_result = run_real_archive_animation_binding_smoke(Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT)
        result = {'scenario': scenario, 'ok': bool(animation_result.get('ok')), 'real_archive_animation': animation_result}
    elif scenario == 'real-archive-sequence-binding-smoke':
        sequence_result = run_real_archive_sequence_binding_smoke(Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT)
        result = {'scenario': scenario, 'ok': bool(sequence_result.get('ok')), 'real_archive_sequence': sequence_result}
    elif scenario == 'real-archive-app-workflow-smoke':
        app_result = run_real_archive_app_workflow_smoke(Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT, output_dir)
        result = {'scenario': scenario, 'ok': bool(app_result.get('ok')), 'real_archive_app': app_result}
    elif scenario == _REAL_MESH_EDITOR_VISUAL_SCENARIO:
        from tools.mesh_harness.real_dotnet import (
            run_real_archive_mesh_editor_dotnet_edit_smoke,
            run_real_archive_mesh_editor_dotnet_zoom_smoke,
        )

        performance_timeout = (
            max(metadata.timeout_seconds, performance_request.duration_seconds + 60.0)
            if performance_request is not None
            else metadata.timeout_seconds
        )
        edit_proof = (
            run_real_archive_mesh_editor_dotnet_edit_smoke(
                Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT,
                output_dir,
                timeout_seconds=performance_timeout,
                performance_request=performance_request,
            )
            if performance_request is not None
            else run_real_archive_mesh_editor_dotnet_edit_smoke(
                Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT,
                output_dir,
                timeout_seconds=metadata.timeout_seconds,
            )
        )
        edit_result = _apply_backend_gate(
            edit_proof,
            expected_renderer_backend=metadata.expected_renderer_backend,
            expected_edit_backend=metadata.expected_edit_backend,
        )
        zoom_result = _apply_backend_gate(
            run_real_archive_mesh_editor_dotnet_zoom_smoke(
                Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT,
                output_dir / 'camera_zoom',
                timeout_seconds=metadata.timeout_seconds,
            ),
            expected_renderer_backend=metadata.expected_renderer_backend,
            expected_edit_backend=metadata.expected_edit_backend,
        )
        result = {
            'scenario': scenario,
            'ok': bool(edit_result.get('ok') and zoom_result.get('ok')),
            'real_archive_mesh_editor_dotnet_edit': edit_result,
            'real_archive_mesh_editor_dotnet_zoom': zoom_result,
        }
    elif scenario == _DOTNET_NATIVE_PARITY_SCENARIO:
        configured_paths = {"openimageio": Path(openimageio_path)} if openimageio_path is not None else None
        parity_result = run_mesh_dotnet_native_parity_report(
            output_dir,
            Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT,
            reference_capture_path=parity_reference,
            candidate_capture_path=parity_candidate,
            configured_paths=configured_paths,
            fail_threshold=parity_fail_threshold,
            fail_percent=parity_fail_percent,
            hard_fail_threshold=parity_hard_fail_threshold,
            difference_scale=parity_difference_scale,
            timeout_s=metadata.timeout_seconds,
        )
        result = {'scenario': scenario, 'ok': bool(parity_result.get('ok')), 'dotnet_native_parity': parity_result}
    elif scenario == 'long-edit-mesh-tools':
        long_edit_result = run_long_edit_mesh_tools()
        result = {'scenario': scenario, 'ok': bool(long_edit_result.get('ok')), 'long_edit': long_edit_result}
    elif scenario == 'native-mesh-editor-workflow':
        workflow_result = run_native_mesh_editor_workflow()
        result = {'scenario': scenario, 'ok': bool(workflow_result.get('ok')), 'native_mesh_editor_workflow': workflow_result}
    elif scenario == 'native-mesh-editor-benchmark':
        benchmark_result = run_native_mesh_editor_benchmark()
        result = {'scenario': scenario, 'ok': bool(benchmark_result.get('ok')), 'native_mesh_editor_benchmark': benchmark_result}
    elif scenario == 'native-mesh-editor-sparse-update-soak':
        soak_result = run_sparse_update_soak(output_dir)
        result = {'scenario': scenario, 'ok': bool(soak_result.get('ok')), 'native_mesh_editor_sparse_update_soak': soak_result}
    elif scenario == 'native-mesh-editor-qt-responsiveness':
        responsiveness_result = run_native_mesh_editor_qt_responsiveness()
        result = {'scenario': scenario, 'ok': bool(responsiveness_result.get('ok')), 'native_mesh_editor_qt_responsiveness': responsiveness_result}
    elif scenario == 'native-mesh-editor-qt-cancellation':
        cancellation_result = run_native_mesh_editor_qt_cancellation()
        result = {'scenario': scenario, 'ok': bool(cancellation_result.get('ok')), 'native_mesh_editor_qt_cancellation': cancellation_result}
    elif scenario == 'native-mesh-editor-standalone-stroke':
        standalone_stroke_result = run_native_mesh_editor_standalone_stroke()
        result = {'scenario': scenario, 'ok': bool(standalone_stroke_result.get('ok')), 'native_mesh_editor_standalone_stroke': standalone_stroke_result}
    elif scenario == 'native-mesh-editor-static-screen-stroke':
        static_screen_stroke_result = run_native_mesh_editor_static_replacement_screen_stroke()
        result = {'scenario': scenario, 'ok': bool(static_screen_stroke_result.get('ok')), 'native_mesh_editor_static_screen_stroke': static_screen_stroke_result}
    else:
        _mesh, service_result = run_service_smoke()
        result = {'scenario': scenario, 'ok': bool(service_result.get('ok')), 'service': service_result}
    result['schema'] = 'cdmw_mesh_editor_harness_result_v2'
    result['scenario_metadata'] = metadata.as_dict()
    evidence_report_path = output_dir / 'evidence_report.json'
    _write_json_atomic(evidence_report_path, _mesh_editor_evidence_report(scenario, result))
    result['evidence_report_path'] = str(evidence_report_path)
    _write_json_atomic(output_dir / 'result.json', result)
    return result
