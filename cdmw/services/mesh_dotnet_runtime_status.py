"""Runtime status, provenance, and evaluation helpers for the .NET mesh editor."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from cdmw.core.atomic_file import atomic_write_text

if TYPE_CHECKING:
    from cdmw.services.mesh_dotnet_experiment import MeshDotNetExperimentPackage


MESH_DOTNET_HELPER_MANIFEST_NAME = "cdmw-mesh-dotnet-editor.manifest.json"

_PROVENANCE_HASH_CACHE_MAX_ENTRIES = 16
_provenance_hash_cache_lock = threading.Lock()
_provenance_hash_cache: dict[str, tuple[int, int, str]] = {}


def mesh_dotnet_provenance_file_sha256(path: Path | str) -> str:
    """SHA-256 of a helper file, cached by (path, size, mtime).

    The packaged helper executable is over 150 MB, and provenance is verified
    both before launch and again on protocol_ready — on the UI thread. Hashing
    it fresh each time froze the interface for the whole read, so the digest is
    reused until the file's size or mtime changes.

    Raises OSError when the file cannot be read, matching ``Path.read_bytes``.
    """

    resolved = Path(path)
    stat_result = resolved.stat()
    size = int(stat_result.st_size)
    mtime_ns = int(getattr(stat_result, "st_mtime_ns", 0) or 0)
    key = str(resolved.resolve()).casefold()
    with _provenance_hash_cache_lock:
        cached = _provenance_hash_cache.get(key)
        if cached is not None and cached[0] == size and cached[1] == mtime_ns:
            return cached[2]
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    with _provenance_hash_cache_lock:
        if len(_provenance_hash_cache) >= _PROVENANCE_HASH_CACHE_MAX_ENTRIES:
            _provenance_hash_cache.clear()
        _provenance_hash_cache[key] = (size, mtime_ns, digest)
    return digest


def mesh_dotnet_experiment_evaluation_path(package: MeshDotNetExperimentPackage) -> Path:
    return package.output_dir / "dotnet_evaluation.md"


def write_mesh_dotnet_experiment_evaluation(
    package: MeshDotNetExperimentPackage,
    status_payload: Mapping[str, object] | None = None,
    *,
    validation_report: object | None = None,
) -> Path:
    path = mesh_dotnet_experiment_evaluation_path(package)
    payload = status_payload or {}
    event = str(payload.get("event", "") or "closed").strip().lower()
    dotnet_metrics = _metrics_mapping(payload, "metrics", "dotnet_metrics")
    native_metrics = _metrics_mapping(payload, "native_baseline", "baseline", "python_cpp_baseline")
    validation_ok = _validation_ok(validation_report)
    blocker_count = _sequence_len(getattr(validation_report, "blockers", None))
    warning_count = _sequence_len(getattr(validation_report, "warnings", None))
    recommendation = _dotnet_recommendation(event, dotnet_metrics, native_metrics, validation_ok)
    atomic_write_text(
        path,
        "\n".join(
            [
                "# Mesh .NET Editor Evaluation",
                "",
                f"Package: `{package.package_dir}`",
                f"Status event: `{event or 'closed'}`",
                f"Output validation: `{_validation_label(validation_ok)}`",
                f"Validation blockers: {blocker_count if blocker_count is not None else 'not run'}",
                f"Validation warnings: {warning_count if warning_count is not None else 'not run'}",
                "",
                "| Area | Python/C++ Editor | .NET Experiment |",
                "|---|---:|---:|",
                f"| FPS | {_metric_text(native_metrics, 'fps', 'average_fps', 'avg_fps')} | {_metric_text(dotnet_metrics, 'fps', 'average_fps', 'avg_fps')} |",
                f"| Frame time ms | {_metric_text(native_metrics, 'frame_time_ms', 'average_frame_time_ms', 'avg_frame_time_ms')} | {_metric_text(dotnet_metrics, 'frame_time_ms', 'average_frame_time_ms', 'avg_frame_time_ms')} |",
                f"| UI responsiveness ms | {_metric_text(native_metrics, 'responsiveness_ms', 'input_latency_ms')} | {_metric_text(dotnet_metrics, 'responsiveness_ms', 'input_latency_ms')} |",
                f"| Crash behavior | {_metric_text(native_metrics, 'crash_behavior', 'crash_rate')} | {_dotnet_crash_text(event, dotnet_metrics)} |",
                f"| Memory MB | {_metric_text(native_metrics, 'memory_mb', 'working_set_mb')} | {_metric_text(dotnet_metrics, 'memory_mb', 'working_set_mb')} |",
                f"| Packaging complexity | {_metric_text(native_metrics, 'packaging_complexity', default='bundled Python/C++ path')} | {_metric_text(dotnet_metrics, 'packaging_complexity', default='bundled external process; parser/rebuilder stay Python/C++')} |",
                f"| Maintenance complexity | {_metric_text(native_metrics, 'maintenance_complexity', default='current authority')} | {_metric_text(dotnet_metrics, 'maintenance_complexity', default='UI-only bridge; parser/rebuilder remain Python/C++')} |",
                "",
                f"Keep/drop Recommendation: **{recommendation}**",
                "",
                "Notes:",
                "- Python/C++ remains the parser, validator, rebuilder, and package authority.",
                "- Missing metrics mean the .NET prototype has not produced enough evidence for a migration decision.",
                "- A validation failure means the edited output is not rebuildable, regardless of viewport performance.",
                "",
            ]
        ),
    )
    return path


def _dotnet_renderer_payload(status_payload: Mapping[str, object] | None) -> Mapping[str, object]:
    payload = status_payload or {}
    renderer = payload.get("renderer")
    if isinstance(renderer, Mapping):
        return renderer
    if "backend" in payload or "native_dds_parity" in payload or "dds_native_dxgi_upload" in payload:
        return payload
    return {}


def mesh_dotnet_material_parity_warnings(status_payload: Mapping[str, object] | None) -> tuple[str, ...]:
    renderer = _dotnet_renderer_payload(status_payload)
    warnings: list[str] = []
    dds_resources = renderer.get("dds_resources")
    dds_present = not (dds_resources == 0 or str(dds_resources or "").strip() == "0")
    if dds_present and renderer.get("native_dds_parity") is False:
        warnings.append("native DDS parity is not available")
    if dds_present and renderer.get("dds_native_dxgi_upload") is False:
        warnings.append("native DXGI DDS upload is not available")
    upload_mode = str(renderer.get("dds_upload_mode", "") or "").strip().lower()
    if dds_present and upload_mode and upload_mode != "native_dxgi_upload":
        warnings.append(f"DDS upload mode is {upload_mode}")
    gap = renderer.get("material_contract_gap")
    if isinstance(gap, Sequence) and not isinstance(gap, (str, bytes)) and tuple(gap):
        warnings.append("material contract gaps are present")
    return tuple(warnings)


def mesh_dotnet_helper_provenance_blockers(
    executable: Path | str,
    status_payload: Mapping[str, object] | None,
    *,
    require_manifest: bool = False,
    required_capabilities: Sequence[str] = (),
) -> tuple[str, ...]:
    """Verify helper-reported runtime identity against disk and release manifest."""

    payload = status_payload or {}
    renderer = _dotnet_renderer_payload(payload)
    raw_provenance = payload.get("provenance")
    if not isinstance(raw_provenance, Mapping):
        raw_provenance = renderer.get("provenance")
    if not isinstance(raw_provenance, Mapping):
        return ("helper provenance is missing",)
    provenance = raw_provenance
    blockers: list[str] = []
    executable_path = Path(executable).expanduser()
    manifest_path = executable_path.parent / MESH_DOTNET_HELPER_MANIFEST_NAME
    manifest: Mapping[str, object] = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            manifest = loaded if isinstance(loaded, Mapping) else {}
        except (OSError, ValueError) as exc:
            blockers.append(f"helper manifest is invalid: {exc}")
    elif require_manifest:
        blockers.append(f"release helper manifest is missing: {manifest_path}")

    actual_executable_hash = ""
    if executable_path.is_file():
        try:
            actual_executable_hash = mesh_dotnet_provenance_file_sha256(executable_path)
        except OSError as exc:
            blockers.append(f"helper executable hash failed: {exc}")
    else:
        blockers.append(f"helper executable is missing: {executable_path}")
    reported_executable_hash = str(provenance.get("process_sha256", "") or "").strip().lower()
    if not reported_executable_hash or reported_executable_hash != actual_executable_hash:
        blockers.append("helper process SHA-256 does not match the launched executable")

    shader_path = executable_path.parent / "D3D11MaterialShaders.hlsl"
    actual_shader_hash = ""
    if shader_path.is_file():
        try:
            actual_shader_hash = mesh_dotnet_provenance_file_sha256(shader_path)
        except OSError as exc:
            blockers.append(f"helper shader hash failed: {exc}")
    reported_shader_hash = str(provenance.get("shader_sha256", "") or "").strip().lower()
    if not reported_shader_hash or (actual_shader_hash and reported_shader_hash != actual_shader_hash):
        blockers.append("helper shader SHA-256 does not match the packaged shader")

    if manifest:
        expected = {
            "manifest_id": str(provenance.get("manifest_id", "") or ""),
            "semantic_version": str(provenance.get("semantic_version", "") or ""),
            "executable_sha256": reported_executable_hash,
            "shader_sha256": reported_shader_hash,
            "renderer_backend": str(provenance.get("renderer_backend", "") or ""),
            "edit_backend": str(provenance.get("edit_backend", "") or ""),
        }
        for key, reported in expected.items():
            wanted = str(manifest.get(key, "") or "").strip().lower()
            if not wanted or reported.strip().lower() != wanted:
                blockers.append(f"helper provenance mismatch for {key}")
        try:
            protocol_version = int(provenance.get("protocol_version", 0) or 0)
            expected_protocol = int(manifest.get("protocol_version", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            protocol_version = expected_protocol = 0
        if protocol_version != expected_protocol or protocol_version < 2:
            blockers.append("helper protocol version does not match the release manifest")
        if str(provenance.get("manifest_mode", "") or "") != "release_manifest":
            blockers.append("release helper did not report release_manifest mode")
    elif str(provenance.get("manifest_mode", "") or "") != "development":
        blockers.append("unmanifested helper did not identify itself as development")

    capabilities = provenance.get("capabilities")
    advertised = payload.get("capabilities")
    if isinstance(capabilities, Sequence) and not isinstance(capabilities, (str, bytes)) and isinstance(
        advertised, Sequence
    ) and not isinstance(advertised, (str, bytes)):
        if {str(value) for value in capabilities} != {str(value) for value in advertised}:
            blockers.append("helper provenance capability set does not match the protocol advertisement")
    else:
        blockers.append("helper provenance capability set is missing")
    if manifest:
        manifest_capabilities = manifest.get("capabilities")
        if isinstance(capabilities, Sequence) and not isinstance(capabilities, (str, bytes)) and isinstance(
            manifest_capabilities, Sequence
        ) and not isinstance(manifest_capabilities, (str, bytes)):
            reported_capabilities = {str(value) for value in capabilities}
            packaged_capabilities = {str(value) for value in manifest_capabilities}
            if not reported_capabilities.issubset(packaged_capabilities):
                blockers.append("helper provenance capability set is not covered by the release manifest")
        else:
            blockers.append("release helper manifest capability set is missing")
    if isinstance(capabilities, Sequence) and not isinstance(capabilities, (str, bytes)):
        available_capabilities = {str(value) for value in capabilities}
        missing_capabilities = sorted(
            {str(value) for value in required_capabilities if str(value)} - available_capabilities
        )
        if missing_capabilities:
            blockers.append("helper required capabilities are missing: " + ", ".join(missing_capabilities))
    if str(provenance.get("renderer_backend", "") or "") != "d3d11_vortice_shader":
        blockers.append("helper provenance renderer backend is not d3d11_vortice_shader")
    if str(provenance.get("edit_backend", "") or "") != "cdmw_mesh_core_0.1":
        blockers.append("helper provenance edit backend is not cdmw_mesh_core_0.1")
    return tuple(dict.fromkeys(blockers))


def mesh_dotnet_helper_static_provenance_blockers(
    executable: Path | str,
    *,
    require_manifest: bool = False,
    required_capabilities: Sequence[str] = (),
) -> tuple[str, ...]:
    """Verify a helper from disk before any process is allowed to execute it."""

    executable_path = Path(executable).expanduser()
    if not executable_path.is_file():
        return (f"helper executable is missing: {executable_path}",)
    manifest_path = executable_path.parent / MESH_DOTNET_HELPER_MANIFEST_NAME
    if not manifest_path.is_file():
        if require_manifest:
            return (f"release helper manifest is missing: {manifest_path}",)
        repo_root = Path(__file__).resolve().parents[2]
        trusted_development_roots = (
            repo_root / "tools" / "dotnet_mesh_editor_experiment" / "bin" / "Release",
            repo_root / "tools" / "dotnet_mesh_editor_experiment" / "bin" / "Debug",
        )
        try:
            resolved = executable_path.resolve()
            trusted = any(resolved.is_relative_to(root.resolve()) for root in trusted_development_roots)
        except OSError:
            trusted = False
        return () if trusted else ("unmanifested helper is outside the trusted repository build output",)

    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return (f"helper manifest is invalid: {exc}",)
    if not isinstance(loaded, Mapping):
        return ("helper manifest is not a JSON object",)
    manifest = loaded
    blockers: list[str] = []
    try:
        executable_hash = mesh_dotnet_provenance_file_sha256(executable_path)
    except OSError as exc:
        blockers.append(f"helper executable hash failed: {exc}")
        executable_hash = ""
    if executable_hash != str(manifest.get("executable_sha256", "") or "").strip().lower():
        blockers.append("helper executable SHA-256 does not match the release manifest")
    shader_path = executable_path.parent / "D3D11MaterialShaders.hlsl"
    try:
        shader_hash = mesh_dotnet_provenance_file_sha256(shader_path)
    except OSError as exc:
        blockers.append(f"helper shader hash failed: {exc}")
        shader_hash = ""
    if shader_hash != str(manifest.get("shader_sha256", "") or "").strip().lower():
        blockers.append("helper shader SHA-256 does not match the release manifest")
    if str(manifest.get("renderer_backend", "") or "") != "d3d11_vortice_shader":
        blockers.append("helper manifest renderer backend is not d3d11_vortice_shader")
    if str(manifest.get("edit_backend", "") or "") != "cdmw_mesh_core_0.1":
        blockers.append("helper manifest edit backend is not cdmw_mesh_core_0.1")
    try:
        protocol_version = int(manifest.get("protocol_version", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        protocol_version = 0
    if protocol_version < 2:
        blockers.append("helper manifest protocol version is unsupported")
    capabilities = manifest.get("capabilities")
    if isinstance(capabilities, Sequence) and not isinstance(capabilities, (str, bytes)):
        available = {str(value) for value in capabilities}
        missing = sorted({str(value) for value in required_capabilities if str(value)} - available)
        if missing:
            blockers.append("helper manifest required capabilities are missing: " + ", ".join(missing))
    else:
        blockers.append("helper manifest capability set is missing")
    return tuple(dict.fromkeys(blockers))


def mesh_dotnet_renderer_blockers(
    status_payload: Mapping[str, object] | None,
    *,
    embedded: bool = False,
    developer_override: bool = False,
    require_material_parity: bool = False,
) -> tuple[str, ...]:
    renderer = _dotnet_renderer_payload(status_payload)
    backend = str(renderer.get("backend", "") or "").strip().lower()
    blockers: list[str] = []
    block_reason = str(renderer.get("renderer_block_reason", "") or "").strip()
    if backend == "blocked_renderer_unavailable" or renderer.get("renderer_blocked") is True:
        blockers.append(f"blocked_renderer_unavailable{': ' + block_reason if block_reason else ''}")
    if bool(embedded) and not ((backend, renderer.get("gpu_backed"), renderer.get("renderer_blocked")) == ("d3d11_vortice_shader", True, False) or (bool(developer_override) and (backend, renderer.get("gpu_backed"), renderer.get("renderer_blocked")) in {("wpf_viewport3d_gpu", True, False), ("winforms_gdi_fallback", False, False)})):
        blockers.append(f"embedded production .NET renderer requires backend=d3d11_vortice_shader, gpu_backed=true, renderer_blocked=false; got backend={backend or '<missing>'}, gpu_backed={renderer.get('gpu_backed')!r}, renderer_blocked={renderer.get('renderer_blocked')!r}")
    if bool(require_material_parity) and not bool(developer_override):
        warnings = mesh_dotnet_material_parity_warnings(status_payload)
        if warnings:
            blockers.append("material parity incomplete: " + "; ".join(warnings))
    return tuple(blockers)


def _metrics_mapping(payload: Mapping[str, object], *keys: str) -> Mapping[str, object]:
    for key in keys:
        raw_value = payload.get(key)
        if isinstance(raw_value, Mapping):
            return raw_value
    return {}


def _metric_text(metrics: Mapping[str, object], *keys: str, default: str = "not reported") -> str:
    for key in keys:
        value = metrics.get(key)
        if value is None or value == "":
            continue
        return str(value)
    return default


def _metric_float(metrics: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        value = metrics.get(key)
        if isinstance(value, bool):
            continue
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            continue
        return number
    return None


def _validation_ok(validation_report: object | None) -> bool | None:
    if validation_report is None:
        return None
    return bool(getattr(validation_report, "ok", False))


def _validation_label(value: bool | None) -> str:
    if value is True:
        return "passed"
    if value is False:
        return "blocked"
    return "not run"


def _sequence_len(value: object) -> int | None:
    if value is None:
        return None
    try:
        return len(tuple(value))  # type: ignore[arg-type]
    except TypeError:
        return None


def _dotnet_crash_text(event: str, dotnet_metrics: Mapping[str, object]) -> str:
    if event in {"error", "crash", "crashed"}:
        return "failed"
    return _metric_text(dotnet_metrics, "crash_behavior", "crash_rate", default="no crash reported")


def _dotnet_recommendation(
    event: str,
    dotnet_metrics: Mapping[str, object],
    native_metrics: Mapping[str, object],
    validation_ok: bool | None,
) -> str:
    if event in {"error", "crash", "crashed"}:
        return "drop .NET output for this run; the external editor reported failure"
    if validation_ok is False:
        return "drop .NET output for this run; validation blocked rebuild"
    dotnet_fps = _metric_float(dotnet_metrics, "average_fps", "avg_fps", "fps")
    native_fps = _metric_float(native_metrics, "average_fps", "avg_fps", "fps")
    if dotnet_fps is None:
        return "keep as experiment only; .NET FPS/frame metrics were not reported"
    if native_fps is None:
        return "keep as experiment only; no Python/C++ baseline was reported"
    if validation_ok is True and dotnet_fps >= native_fps * 1.1:
        return "keep .NET experiment for more testing; reported FPS beats baseline and validation passed"
    return "keep Python/C++ editor as default; .NET has not beaten the baseline enough"


__all__ = [
    "MESH_DOTNET_HELPER_MANIFEST_NAME",
    "mesh_dotnet_experiment_evaluation_path",
    "mesh_dotnet_helper_provenance_blockers",
    "mesh_dotnet_material_parity_warnings",
    "mesh_dotnet_provenance_file_sha256",
    "mesh_dotnet_renderer_blockers",
    "write_mesh_dotnet_experiment_evaluation",
]
