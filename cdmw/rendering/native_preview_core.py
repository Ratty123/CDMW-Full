from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import atexit
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from cdmw.core.common import (
    BoundedTextTail,
    finish_process_tree,
    hidden_process_group_kwargs,
    raise_if_cancelled,
    read_bounded_text_line,
    run_process_with_cancellation,
    start_bounded_text_stream_drain,
)
from cdmw.models import ArchiveEntry, ModelPreviewRenderSettings, RunCancelled

NATIVE_PREVIEW_CORE_BINARY_NAME = "cdmw-preview-core.exe" if os.name == "nt" else "cdmw-preview-core"
NATIVE_PREVIEW_CORE_BACKEND_ID = "cdmw_preview_core_0.1"
NATIVE_PREVIEW_CORE_SERVICE_MAX_JOBS = 32
NATIVE_PREVIEW_CORE_SERVICE_CACHE_RECYCLE_BYTES = 192 * 1024 * 1024
NATIVE_PREVIEW_CORE_SERVICE_PRIVATE_RECYCLE_BYTES = 512 * 1024 * 1024
NATIVE_PREVIEW_CORE_DDS_CACHE_MAX_BYTES = 96 * 1024 * 1024
NATIVE_PREVIEW_CORE_DDS_CACHE_TARGET_BYTES = 64 * 1024 * 1024
NATIVE_PREVIEW_CORE_MATERIAL_CONTRACT_SCHEMA_VERSION = 2
NATIVE_PREVIEW_CORE_MATERIAL_CHANNEL_CONTRACT_SCHEMA_VERSION = 2
NATIVE_PREVIEW_CORE_TEXTURE_QUALITY_SCHEMA_VERSION = 1
NATIVE_PREVIEW_CORE_MAX_DEPENDENCY_ENTRIES = 4096
NATIVE_PREVIEW_CORE_MAX_PREFAB_COMPONENTS = 32


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_native_preview_core_path(*, release: bool = True) -> Path:
    config = "Release" if release else "Debug"
    return _repo_root() / "native" / "cdmw_preview_core" / "build" / config / NATIVE_PREVIEW_CORE_BINARY_NAME


def find_native_preview_core_binary() -> Optional[Path]:
    env_path = os.environ.get("CDMW_PREVIEW_CORE_BIN", "").strip()
    candidates = [Path(env_path)] if env_path else []
    frozen_root = Path(str(getattr(sys, "_MEIPASS", ""))) if getattr(sys, "_MEIPASS", "") else None
    exe_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    if frozen_root is not None:
        candidates.append(frozen_root / "native" / NATIVE_PREVIEW_CORE_BINARY_NAME)
    if exe_root is not None:
        candidates.append(exe_root / "native" / NATIVE_PREVIEW_CORE_BINARY_NAME)
    candidates.extend(
        [
            default_native_preview_core_path(release=True),
            default_native_preview_core_path(release=False),
            _repo_root() / "native" / "cdmw_preview_core" / "bin" / NATIVE_PREVIEW_CORE_BINARY_NAME,
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def prune_native_preview_core_cache(
    cache_root: Path,
    *,
    max_bytes: int = NATIVE_PREVIEW_CORE_DDS_CACHE_MAX_BYTES,
    target_bytes: int = NATIVE_PREVIEW_CORE_DDS_CACHE_TARGET_BYTES,
) -> Dict[str, int]:
    dds_root = Path(cache_root) / "dds"
    if max_bytes <= 0 or target_bytes < 0 or not dds_root.is_dir():
        return {"files": 0, "bytes": 0, "removed_files": 0, "removed_bytes": 0}
    files: list[tuple[float, int, Path]] = []
    total_bytes = 0
    try:
        iterator = tuple(dds_root.glob("*.dds"))
    except OSError:
        return {"files": 0, "bytes": 0, "removed_files": 0, "removed_bytes": 0}
    for path in iterator:
        try:
            stat = path.stat()
        except OSError:
            continue
        if not path.is_file():
            continue
        size = max(0, int(stat.st_size))
        total_bytes += size
        files.append((float(stat.st_mtime), size, path))
    if total_bytes <= max_bytes:
        return {"files": len(files), "bytes": total_bytes, "removed_files": 0, "removed_bytes": 0}
    removed_files = 0
    removed_bytes = 0
    for _mtime, size, path in sorted(files, key=lambda item: item[0]):
        if total_bytes <= target_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total_bytes -= size
        removed_files += 1
        removed_bytes += size
    return {
        "files": max(0, len(files) - removed_files),
        "bytes": max(0, total_bytes),
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
    }


@dataclass(frozen=True)
class NativePreviewCoreAttempt:
    status: str
    package_path: str = ""
    fallback_reason: str = ""
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    report_path: str = ""
    job_root_path: str = ""
    backend: str = NATIVE_PREVIEW_CORE_BACKEND_ID

    @property
    def succeeded(self) -> bool:
        return self.status == "ok" and bool(self.package_path)

    def diagnostic_line(self) -> str:
        if self.status == "missing":
            return "Native Preview Core: unavailable; .NET/Vortice package preparation is disabled for this entry."
        reason = self.fallback_reason or str(self.diagnostics.get("message") or "").strip()
        timing = f"{self.elapsed_ms:.1f} ms" if self.elapsed_ms > 0.0 else "n/a"
        if self.succeeded:
            batch_count = self.diagnostics.get("batch_count")
            vertex_count = self.diagnostics.get("vertex_count")
            dds_extracted = self.diagnostics.get("dds_extracted")
            cache_hits = self.diagnostics.get("decoded_cache_job_hits")
            cache_misses = self.diagnostics.get("decoded_cache_job_misses")
            mesh_parser = str(self.diagnostics.get("native_mesh_parser") or "").strip()
            graph_cache_hit = self.diagnostics.get("native_material_graph_cache_hit")
            metrics = []
            if isinstance(batch_count, int):
                metrics.append(f"batches={batch_count:,}")
            if isinstance(vertex_count, int):
                metrics.append(f"vertices={vertex_count:,}")
            if isinstance(dds_extracted, int):
                metrics.append(f"dds={dds_extracted:,}")
            if isinstance(cache_hits, int) and isinstance(cache_misses, int):
                metrics.append(f"cache={cache_hits:,}/{cache_misses:,}")
            if mesh_parser:
                metrics.append(f"parser={mesh_parser}")
            if isinstance(graph_cache_hit, bool):
                metrics.append(f"graph_cache={'hit' if graph_cache_hit else 'miss'}")
            suffix = f"; {'; '.join(metrics)}" if metrics else ""
            return f"Native Preview Core: active; package={self.package_path}; time={timing}{suffix}."
        return f"Native Preview Core: unavailable; reason={reason or self.status}; time={timing}."


def _native_diagnostic_args(*, crash_dir: Optional[Path] = None, diagnostic_log: Optional[Path] = None) -> list[str]:
    resolved_crash_dir = str(crash_dir or os.environ.get("CDMW_CRASH_DIR", "") or "").strip()
    resolved_diagnostic_log = str(diagnostic_log or os.environ.get("CDMW_NATIVE_DIAGNOSTIC_LOG", "") or "").strip()
    args: list[str] = []
    if resolved_crash_dir:
        args.extend(["--crash-dir", resolved_crash_dir])
    if resolved_diagnostic_log:
        args.extend(["--diagnostic-log", resolved_diagnostic_log])
    return args


def _record_native_preview_core_python_event(
    event: str,
    *,
    diagnostic_log: Optional[Path] = None,
    **fields: object,
) -> None:
    diagnostic_log_text = str(diagnostic_log or os.environ.get("CDMW_NATIVE_DIAGNOSTIC_LOG", "") or "").strip()
    if not diagnostic_log_text:
        return
    payload: Dict[str, object] = {
        "timestamp_ms": int(time.time() * 1000),
        "pid": os.getpid(),
        "tool": "cdmw-python",
        "event": str(event or "event"),
    }
    payload.update({str(key): value for key, value in fields.items()})
    try:
        log_path = Path(diagnostic_log_text)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    except OSError:
        return


class NativePreviewCoreServiceClient:
    """Small persistent JSON-line client for cdmw-preview-core.exe.

    The native service is intentionally narrow: Python writes a job file, asks the
    service to process it, then reads the report file. That keeps the protocol
    stable while the native implementation grows from archive IO preflight into
    full D3D11 package generation.
    """

    def __init__(
        self,
        binary: Path,
        *,
        crash_dir: Optional[Path] = None,
        diagnostic_log: Optional[Path] = None,
    ) -> None:
        self.binary = Path(binary)
        self.binary_signature = self.resolve_binary_signature(self.binary)
        self.crash_dir = Path(crash_dir) if crash_dir else None
        self.diagnostic_log = Path(diagnostic_log) if diagnostic_log else None
        self._lock = threading.RLock()
        self._process: Optional[subprocess.Popen[str]] = None
        self._jobs_completed = 0
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_tail = BoundedTextTail()

    @staticmethod
    def resolve_binary_signature(binary: Path) -> tuple[int, int]:
        try:
            stat_result = Path(binary).stat()
        except OSError:
            return (0, 0)
        return (int(getattr(stat_result, "st_mtime_ns", 0) or 0), int(getattr(stat_result, "st_size", 0) or 0))

    @property
    def process_id(self) -> int:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                return 0
            try:
                return int(getattr(process, "pid", 0) or 0)
            except (AttributeError, TypeError, ValueError):
                return 0

    def shutdown(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._jobs_completed = 0
            if process is None:
                return
            shutdown_requested = False
            try:
                if process.poll() is None and process.stdin is not None:
                    process.stdin.write('{"command":"shutdown"}\n')
                    process.stdin.flush()
                    shutdown_requested = True
            except OSError:
                pass
            finish_process_tree(process, grace_seconds=1.0, request_stop=not shutdown_requested)
            self._close_process_streams_locked(process)

    def _kill_locked(self) -> None:
        process = self._process
        self._process = None
        self._jobs_completed = 0
        if process is None:
            return
        finish_process_tree(process, grace_seconds=0.25, request_stop=True)
        self._close_process_streams_locked(process)

    def _close_process_streams_locked(self, process: object) -> None:
        for stream in (
            getattr(process, "stdin", None),
            getattr(process, "stdout", None),
            getattr(process, "stderr", None),
        ):
            close = getattr(stream, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except (OSError, ValueError):
                pass
        stderr_thread = self._stderr_thread
        self._stderr_thread = None
        if stderr_thread is not None and stderr_thread is not threading.current_thread():
            stderr_thread.join(0.2)

    @property
    def stderr_tail(self) -> str:
        return self._stderr_tail.text()

    def _read_stdout_line_locked(self, timeout_seconds: float, stop_event: Any = None) -> str:
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("native preview-core service is not running")
        result: Dict[str, object] = {}

        def read_line() -> None:
            try:
                result["line"] = read_bounded_text_line(process.stdout)
            except Exception as exc:  # pragma: no cover - defensive for pipe teardown
                result["error"] = exc

        thread = threading.Thread(target=read_line, name="cdmw-preview-core-readline", daemon=True)
        thread.start()
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        while thread.is_alive():
            try:
                raise_if_cancelled(stop_event, "Native preview-core job cancelled.")
            except RunCancelled:
                self._kill_locked()
                raise
            if time.monotonic() >= deadline:
                self._kill_locked()
                raise TimeoutError("native preview-core service timed out")
            thread.join(0.02)
        error = result.get("error")
        if isinstance(error, BaseException):
            raise RuntimeError(f"native preview-core service read failed: {error}") from error
        line = str(result.get("line") or "").strip()
        if not line:
            self._kill_locked()
            raise RuntimeError("native preview-core service closed its stdout")
        return line

    def _start_locked(self, stop_event: Any = None) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            return
        self._jobs_completed = 0
        command = [str(self.binary), "--service"]
        command.extend(_native_diagnostic_args(crash_dir=self.crash_dir, diagnostic_log=self.diagnostic_log))
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_process_group_kwargs(),
        )
        stderr = self._process.stderr
        self._stderr_tail = BoundedTextTail()
        if stderr is not None:
            self._stderr_thread, self._stderr_tail = start_bounded_text_stream_drain(
                stderr,
                name="cdmw-preview-core-stderr",
            )
        ready_line = self._read_stdout_line_locked(5.0, stop_event=stop_event)
        try:
            ready = json.loads(ready_line)
        except json.JSONDecodeError as exc:
            self._kill_locked()
            raise RuntimeError(f"native preview-core service sent invalid ready line: {ready_line}") from exc
        if str(ready.get("event") or "").strip().lower() != "ready":
            self._kill_locked()
            raise RuntimeError(f"native preview-core service did not become ready: {ready_line}")

    @staticmethod
    def _int_report_value(report: Mapping[str, Any], key: str) -> int:
        try:
            return int(report.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _read_report_for_recycle(self, report_path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
        except Exception:
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

    def _recycle_reason_for_report(self, report: Mapping[str, Any]) -> str:
        native_reason = str(report.get("service_recycle_reason") or "").strip()
        if native_reason:
            return native_reason
        if self._jobs_completed >= NATIVE_PREVIEW_CORE_SERVICE_MAX_JOBS:
            return "job_count"
        if self._int_report_value(report, "decoded_cache_bytes") > NATIVE_PREVIEW_CORE_SERVICE_CACHE_RECYCLE_BYTES:
            return "decoded_cache_bytes"
        if self._int_report_value(report, "process_private_bytes") > NATIVE_PREVIEW_CORE_SERVICE_PRIVATE_RECYCLE_BYTES:
            return "process_private_bytes"
        return ""

    def _mark_report_recycle_reason(self, report_path: Path, report: Mapping[str, Any], reason: str) -> None:
        if not reason:
            return
        updated = dict(report)
        updated["service_recycle_reason"] = reason
        updated["service_job_count"] = max(
            self._int_report_value(updated, "service_job_count"),
            int(self._jobs_completed),
        )
        try:
            Path(report_path).write_text(json.dumps(updated, separators=(",", ":")), encoding="utf-8")
        except OSError:
            pass

    def preview_job(
        self,
        job_path: Path,
        report_path: Path,
        *,
        timeout_seconds: float,
        stop_event: Any = None,
        on_dispatched: Optional[Callable[[], None]] = None,
    ) -> None:
        with self._lock:
            self._start_locked(stop_event=stop_event)
            process = self._process
            if process is None or process.stdin is None:
                raise RuntimeError("native preview-core service stdin is unavailable")
            command = json.dumps(
                {"command": "preview-job", "job_path": str(job_path), "report_path": str(report_path)},
                separators=(",", ":"),
            )
            try:
                process.stdin.write(command + "\n")
                process.stdin.flush()
            except OSError as exc:
                self._kill_locked()
                raise RuntimeError(f"native preview-core service write failed: {exc}") from exc
            if on_dispatched is not None:
                on_dispatched()
            response_line = self._read_stdout_line_locked(timeout_seconds, stop_event=stop_event)
            try:
                response = json.loads(response_line)
            except json.JSONDecodeError as exc:
                report = self._read_report_for_recycle(report_path)
                if report_path.is_file() and report:
                    self._jobs_completed += 1
                    self._mark_report_recycle_reason(report_path, report, "invalid_stdout_response")
                    self.shutdown()
                    return
                self._kill_locked()
                raise RuntimeError(f"native preview-core service sent invalid response: {response_line}") from exc
            response_status = str(response.get("status") or response.get("event") or "").strip().lower()
            if response_status == "error" and not report_path.is_file():
                message = str(response.get("message") or "native preview-core service returned an error")
                raise RuntimeError(message)
            self._jobs_completed += 1
            report = self._read_report_for_recycle(report_path)
            recycle_reason = self._recycle_reason_for_report(report)
            if recycle_reason:
                self._mark_report_recycle_reason(report_path, report, recycle_reason)
                self.shutdown()


_native_preview_core_service_lock = threading.RLock()
_native_preview_core_service: Optional[NativePreviewCoreServiceClient] = None


def _get_native_preview_core_service(
    binary: Path,
    *,
    crash_dir: Optional[Path] = None,
    diagnostic_log: Optional[Path] = None,
) -> NativePreviewCoreServiceClient:
    global _native_preview_core_service
    with _native_preview_core_service_lock:
        resolved_binary = Path(binary)
        binary_signature = NativePreviewCoreServiceClient.resolve_binary_signature(resolved_binary)
        if (
            _native_preview_core_service is None
            or _native_preview_core_service.binary != resolved_binary
            or _native_preview_core_service.binary_signature != binary_signature
            or _native_preview_core_service.crash_dir != (Path(crash_dir) if crash_dir else None)
            or _native_preview_core_service.diagnostic_log != (Path(diagnostic_log) if diagnostic_log else None)
        ):
            if _native_preview_core_service is not None:
                _native_preview_core_service.shutdown()
            _native_preview_core_service = NativePreviewCoreServiceClient(
                resolved_binary,
                crash_dir=crash_dir,
                diagnostic_log=diagnostic_log,
            )
        return _native_preview_core_service


def shutdown_native_preview_core_service() -> None:
    global _native_preview_core_service
    with _native_preview_core_service_lock:
        if _native_preview_core_service is not None:
            _native_preview_core_service.shutdown()
            _native_preview_core_service = None


def render_settings_to_native_preview_core_dict(settings: Optional[ModelPreviewRenderSettings]) -> Dict[str, Any]:
    if settings is None:
        return {}
    result: Dict[str, Any] = {}
    for attr in (
        "visible_texture_mode",
        "render_diagnostic_mode",
        "preview_texture_max_dimension",
        "low_quality_texture_max_dimension",
        "high_quality_by_default",
        "use_textures_by_default",
        "disable_all_support_maps",
        "disable_normal_map",
        "disable_material_map",
        "disable_height_map",
        "flip_texture_v",
        "normal_strength_floor",
        "normal_strength_cap",
        "height_effect_max",
        "specular_response",
        "surface_contrast",
        "resolution_scale",
        "sharpen_strength",
        "max_anisotropy",
        "d3d11_mip_lod_bias",
        "d3d11_view_mode",
        "d3d11_cull_back_faces",
        "d3d11_light_azimuth_degrees",
        "d3d11_light_elevation_degrees",
        "d3d11_normal_y_mode",
        "d3d11_ao_strength",
        "d3d11_roughness_bias",
        "d3d11_metalness_scale",
        "d3d11_environment_strength",
        "d3d11_emissive_gain",
        "d3d11_tone_exposure",
        "d3d11_tone_contrast",
        "d3d11_tone_gamma",
        "d3d11_texture_address_mode",
        "ambient_strength",
        "diffuse_wrap_bias",
        "diffuse_light_scale",
        "orbit_sensitivity",
        "pan_sensitivity",
        "invert_orbit_x",
        "invert_orbit_y",
        "invert_pan_x",
        "invert_pan_y",
        "specular_base",
        "specular_max",
        "shininess_min",
        "shininess_max",
    ):
        if hasattr(settings, attr):
            value = getattr(settings, attr)
            if isinstance(value, (str, int, float, bool)) or value is None:
                result[attr] = value
    return result


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if result == result and result not in (float("inf"), float("-inf")) else fallback


def _clamp(value: object, low: float, high: float, fallback: float) -> float:
    return max(low, min(high, _safe_float(value, fallback)))


def _native_preview_core_lighting_preset(
    render_settings: Optional[ModelPreviewRenderSettings],
    batches: Sequence[object],
    current: object = "",
) -> str:
    current_text = str(current or "").strip()
    if current_text and current_text != "neutral_studio":
        return current_text
    d3d11_mode = str(getattr(render_settings, "d3d11_view_mode", "") or "").strip().lower()
    if d3d11_mode in {"game_outdoor", "cd_outdoor", "outdoor_game"}:
        return "game_outdoor_approx"
    mode = str(getattr(render_settings, "render_diagnostic_mode", "lit") or "lit").strip().lower()
    if mode in {"texture_probe", "base_direct", "base_no_tint", "normal_raw", "material_raw", "height_raw", "uv_checker"}:
        return "texture_debug"
    if mode in {"metal_shine", "roughness_response", "material_response"}:
        return "shiny_metal_inspection"
    if mode in {"rich_lit", "height_depth", "height_calibrated"}:
        return "cloth_skin_inspection"
    for batch in batches:
        if not isinstance(batch, Mapping):
            continue
        if (
            str(batch.get("material_category", "") or "").strip().lower() == "metal"
            and _safe_float(batch.get("material_category_confidence"), 0.0) >= 0.45
        ):
            return "shiny_metal_inspection"
    return current_text or "neutral_studio"


def _native_preview_core_repair_metal_batch(batch: Dict[str, Any]) -> bool:
    category = str(batch.get("material_category", "") or "").strip().lower()
    confidence = _clamp(batch.get("material_category_confidence"), 0.0, 1.0, 0.0)
    if category != "metal" or confidence < 0.45:
        return False
    response = str(batch.get("material_response_disposition", "") or "").strip().lower()
    strong_response = any(token in response for token in ("metal_response", "metallic", "promoted"))
    metalness_floor = 0.68 if strong_response else 0.56
    specular_floor = 0.68 if strong_response else 0.56
    roughness_target = 0.24 if strong_response else 0.32
    existing_metalness = _clamp(batch.get("metalness"), 0.0, 1.0, 0.0)
    existing_specular = _clamp(batch.get("specular"), 0.0, 1.0, 0.0)
    existing_roughness = _clamp(batch.get("roughness"), 0.0, 1.0, 0.0)
    batch["metalness"] = max(existing_metalness, metalness_floor)
    batch["specular"] = max(existing_specular, specular_floor)
    batch["roughness"] = roughness_target if existing_roughness <= 0.02 else min(existing_roughness, roughness_target)
    hints = batch.get("native_material_hints")
    if not isinstance(hints, Mapping):
        hints = {}
    merged_hints = dict(hints)
    merged_hints["metalness"] = max(_clamp(merged_hints.get("metalness"), 0.0, 1.0, 0.0), batch["metalness"])
    merged_hints["specular"] = max(_clamp(merged_hints.get("specular"), 0.0, 1.0, 0.0), batch["specular"])
    merged_hints["roughness"] = min(
        _clamp(merged_hints.get("roughness"), 0.0, 1.0, batch["roughness"]),
        batch["roughness"],
    )
    merged_hints.setdefault("source", "native_core_material_category_repair")
    batch["native_material_hints"] = merged_hints
    contract = batch.get("material_contract")
    if not isinstance(contract, Mapping):
        contract = {}
    merged_contract = dict(contract)
    merged_contract.setdefault("status", "ok")
    merged_contract["schema_version"] = NATIVE_PREVIEW_CORE_MATERIAL_CONTRACT_SCHEMA_VERSION
    pbr_hints = merged_contract.get("pbr_scalar_hints")
    if not isinstance(pbr_hints, Mapping):
        pbr_hints = {}
    merged_pbr_hints = dict(pbr_hints)
    for key in ("roughness", "metalness", "specular"):
        merged_pbr_hints[key] = merged_hints[key]
    merged_contract["pbr_scalar_hints"] = merged_pbr_hints
    batch["material_contract"] = merged_contract
    channel_contract = batch.get("material_channel_contract")
    if not isinstance(channel_contract, Mapping):
        channel_contract = {}
    merged_channel_contract = dict(channel_contract)
    merged_channel_contract["schema_version"] = NATIVE_PREVIEW_CORE_MATERIAL_CHANNEL_CONTRACT_SCHEMA_VERSION
    merged_channel_contract.setdefault("workflow", "crimson_native_material_response")
    batch["material_channel_contract"] = merged_channel_contract
    return True


def _repair_native_preview_core_manifest(
    package_path: str | Path,
    render_settings: Optional[ModelPreviewRenderSettings],
) -> Dict[str, Any]:
    manifest_path = Path(package_path) / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(manifest, Mapping):
        return {}
    updated: Dict[str, Any] = dict(manifest)
    batches_raw = updated.get("batches")
    batches = list(batches_raw) if isinstance(batches_raw, list) else []
    repaired_metal_batches = 0
    for index, batch in enumerate(batches):
        if not isinstance(batch, Mapping):
            continue
        mutable_batch = dict(batch)
        if _native_preview_core_repair_metal_batch(mutable_batch):
            repaired_metal_batches += 1
            batches[index] = mutable_batch
    updated["batches"] = batches
    updated["material_contract_schema"] = max(
        int(updated.get("material_contract_schema", 0) or 0),
        NATIVE_PREVIEW_CORE_MATERIAL_CONTRACT_SCHEMA_VERSION,
    )
    updated["material_channel_contract_schema"] = max(
        int(updated.get("material_channel_contract_schema", 0) or 0),
        NATIVE_PREVIEW_CORE_MATERIAL_CHANNEL_CONTRACT_SCHEMA_VERSION,
    )
    updated["texture_quality_schema"] = max(
        int(updated.get("texture_quality_schema", 0) or 0),
        NATIVE_PREVIEW_CORE_TEXTURE_QUALITY_SCHEMA_VERSION,
    )
    updated["lighting_preset"] = _native_preview_core_lighting_preset(
        render_settings,
        batches,
        updated.get("lighting_preset", ""),
    )
    updated["diffuse_wrap_bias"] = _clamp(
        updated.get("diffuse_wrap_bias", getattr(render_settings, "diffuse_wrap_bias", 0.58)),
        0.0,
        1.0,
        _safe_float(getattr(render_settings, "diffuse_wrap_bias", 0.58), 0.58),
    )
    if "render_settings" not in updated:
        updated["render_settings"] = render_settings_to_native_preview_core_dict(render_settings)
    if dict(manifest) != updated:
        manifest_path.write_text(json.dumps(updated, separators=(",", ":")), encoding="utf-8")
    return {
        "native_preview_core_manifest_repaired": True,
        "native_preview_core_repaired_metal_batches": repaired_metal_batches,
        "native_preview_core_lighting_preset": updated.get("lighting_preset", ""),
        "native_preview_core_material_contract_schema": updated.get("material_contract_schema", 0),
        "native_preview_core_material_channel_contract_schema": updated.get("material_channel_contract_schema", 0),
        "native_preview_core_texture_quality_schema": updated.get("texture_quality_schema", 0),
    }


def archive_entry_to_native_preview_core_dict(entry: Optional[ArchiveEntry]) -> Dict[str, Any]:
    if entry is None:
        return {}
    return {
        "path": str(entry.path),
        "basename": str(entry.basename),
        "extension": str(entry.extension),
        "pamt_path": str(entry.pamt_path),
        "paz_file": str(entry.paz_file),
        "offset": int(entry.offset),
        "comp_size": int(entry.comp_size),
        "orig_size": int(entry.orig_size),
        "flags": int(entry.flags),
        "paz_index": int(entry.paz_index),
        "compression_type": int(entry.compression_type),
        "prepared_path": str(entry.prepared_path or ""),
        "prepared_sha256": str(entry.prepared_sha256 or "").strip().lower(),
    }


def _validated_native_preview_dependency_entries(
    dependency_entries: Sequence[ArchiveEntry],
    *,
    complete: bool,
) -> tuple[ArchiveEntry, ...]:
    entries = tuple(dependency_entries)
    if complete and not entries:
        raise ValueError("A complete native preview dependency snapshot must contain the selected entry.")
    if len(entries) > NATIVE_PREVIEW_CORE_MAX_DEPENDENCY_ENTRIES:
        raise ValueError("Native preview dependency snapshots are limited to 4,096 entries.")
    return entries


def _validated_enabled_prefab_component_paths(
    component_paths: Sequence[str],
) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in component_paths:
        path = str(raw_path or "").replace("\\", "/").strip()
        if not path:
            continue
        key = path.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(path)
        if len(normalized) > NATIVE_PREVIEW_CORE_MAX_PREFAB_COMPONENTS:
            raise ValueError("Native preview prefab selections are limited to 32 components.")
    return tuple(normalized)


def build_native_preview_core_job(
    entry: ArchiveEntry,
    *,
    cache_root: Path,
    output_root: Path,
    render_settings: Optional[ModelPreviewRenderSettings] = None,
    companion_entry: Optional[ArchiveEntry] = None,
    dependency_entries: Sequence[ArchiveEntry] = (),
    dependency_entries_complete: bool = False,
    enabled_prefab_component_paths: Sequence[str] = (),
    package_root: Optional[Path] = None,
    renderer_backend: str = "d3d11",
    schema_version: int = 8,
) -> Dict[str, Any]:
    dependency_entries = _validated_native_preview_dependency_entries(
        dependency_entries,
        complete=dependency_entries_complete,
    )
    enabled_prefab_component_paths = _validated_enabled_prefab_component_paths(
        enabled_prefab_component_paths
    )
    return {
        "version": 1,
        "backend": NATIVE_PREVIEW_CORE_BACKEND_ID,
        "renderer_backend": str(renderer_backend or "d3d11").strip().lower(),
        "schema_version": int(schema_version),
        "created_at": time.time(),
        "package_root": str(package_root or ""),
        "cache_root": str(cache_root),
        "output_root": str(output_root),
        "entry": archive_entry_to_native_preview_core_dict(entry),
        "companion_entry": archive_entry_to_native_preview_core_dict(companion_entry),
        "archive_dependency_entries": [
            archive_entry_to_native_preview_core_dict(dependency)
            for dependency in dependency_entries
        ],
        "archive_dependency_entries_complete": bool(dependency_entries_complete),
        "enabled_prefab_component_paths": list(enabled_prefab_component_paths),
        "render_settings": render_settings_to_native_preview_core_dict(render_settings),
        "capabilities": {
            "direct_dds": True,
            "d3d11_package": True,
            "material_index": True,
            "material_graph": True,
            "material_graph_version": 3,
            "python_fallback_allowed": False,
            "native_material_runtime": True,
        },
    }


def run_native_preview_core_preview_job(
    entry: ArchiveEntry,
    *,
    cache_root: Path,
    render_settings: Optional[ModelPreviewRenderSettings] = None,
    companion_entry: Optional[ArchiveEntry] = None,
    dependency_entries: Sequence[ArchiveEntry] = (),
    dependency_entries_complete: bool = False,
    enabled_prefab_component_paths: Sequence[str] = (),
    package_root: Optional[Path] = None,
    output_root: Optional[Path] = None,
    timeout_seconds: float = 3.0,
    stop_event: Any = None,
    use_service: bool = True,
    crash_dir: Optional[Path] = None,
    diagnostic_log: Optional[Path] = None,
    dds_cache_max_bytes: int = NATIVE_PREVIEW_CORE_DDS_CACHE_MAX_BYTES,
    dds_cache_target_bytes: int = NATIVE_PREVIEW_CORE_DDS_CACHE_TARGET_BYTES,
) -> NativePreviewCoreAttempt:
    raise_if_cancelled(stop_event, "Native preview-core job cancelled.")
    dependency_entries = _validated_native_preview_dependency_entries(
        dependency_entries,
        complete=dependency_entries_complete,
    )
    enabled_prefab_component_paths = _validated_enabled_prefab_component_paths(
        enabled_prefab_component_paths
    )
    binary = find_native_preview_core_binary()
    if binary is None:
        return NativePreviewCoreAttempt(
            status="missing",
            fallback_reason="cdmw-preview-core binary was not found",
        )
    job_root = Path(tempfile.mkdtemp(prefix="cdmw_preview_core_"))
    output_root = Path(output_root) if (external_output_root := output_root is not None) else job_root / "package"
    job_path = job_root / "job.json"
    report_path = job_root / "report.json"
    cache_prune_report = prune_native_preview_core_cache(
        cache_root,
        max_bytes=dds_cache_max_bytes,
        target_bytes=dds_cache_target_bytes,
    )
    job = build_native_preview_core_job(
        entry,
        cache_root=cache_root,
        output_root=output_root,
        render_settings=render_settings,
        companion_entry=companion_entry,
        dependency_entries=dependency_entries,
        dependency_entries_complete=dependency_entries_complete,
        enabled_prefab_component_paths=enabled_prefab_component_paths,
        package_root=package_root,
    )
    job_path.write_text(json.dumps(job, separators=(",", ":")), encoding="utf-8")
    started = time.perf_counter()
    job_dispatched_to_service = False
    def mark_job_dispatched() -> None:
        nonlocal job_dispatched_to_service
        job_dispatched_to_service = True

    try:
        service_pid = 0
        if use_service:
            service = _get_native_preview_core_service(binary, crash_dir=crash_dir, diagnostic_log=diagnostic_log)
            service.preview_job(
                job_path,
                report_path,
                timeout_seconds=max(0.5, float(timeout_seconds)),
                stop_event=stop_event,
                on_dispatched=mark_job_dispatched,
            )
            service_pid = service.process_id
            returncode, stdout_text, stderr_text = 0, "", ""
        else:
            command = [str(binary), "preview-job", str(job_path), str(report_path)]
            command.extend(_native_diagnostic_args(crash_dir=crash_dir, diagnostic_log=diagnostic_log))
            returncode, stdout_text, stderr_text = run_process_with_cancellation(
                command,
                timeout_seconds=max(0.5, float(timeout_seconds)),
                stop_event=stop_event,
            )
    except RunCancelled:
        if job_dispatched_to_service:
            _record_native_preview_core_python_event(
                "native_preview_core_cancel_after_dispatch",
                diagnostic_log=diagnostic_log,
                job_root=str(job_root),
                job_path=str(job_path),
                report_path=str(report_path),
            )
        else:
            shutil.rmtree(job_root, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(job_root, ignore_errors=True)
        return NativePreviewCoreAttempt(
            status="error",
            fallback_reason=f"native preview-core launch failed: {exc}",
            elapsed_ms=max(0.0, (time.perf_counter() - started) * 1000.0),
            report_path=str(report_path),
            job_root_path=str(job_root),
        )
    elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
    if returncode != 0:
        detail = (stderr_text or stdout_text or "").strip()
        shutil.rmtree(job_root, ignore_errors=True)
        return NativePreviewCoreAttempt(
            status="error",
            fallback_reason=f"native preview-core exited with code {returncode}: {detail[:500]}",
            elapsed_ms=elapsed_ms,
            report_path=str(report_path),
            job_root_path=str(job_root),
        )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        shutil.rmtree(job_root, ignore_errors=True)
        return NativePreviewCoreAttempt(
            status="error",
            fallback_reason=f"native preview-core report unavailable: {exc}",
            elapsed_ms=elapsed_ms,
            report_path=str(report_path),
            job_root_path=str(job_root),
        )
    if not isinstance(report, Mapping):
        report = {"status": "error", "message": "native preview-core report was not an object"}
    else:
        report = dict(report)
    binary_signature = NativePreviewCoreServiceClient.resolve_binary_signature(binary)
    report.setdefault("native_preview_core_binary_mtime_ns", binary_signature[0])
    report.setdefault("native_preview_core_binary_size", binary_signature[1])
    if use_service and service_pid > 0:
        report.setdefault("native_preview_core_process_pid", service_pid)
    post_cache_prune_report = prune_native_preview_core_cache(
        cache_root,
        max_bytes=dds_cache_max_bytes,
        target_bytes=dds_cache_target_bytes,
    )
    removed_files = int(cache_prune_report.get("removed_files", 0) or 0) + int(post_cache_prune_report.get("removed_files", 0) or 0)
    removed_bytes = int(cache_prune_report.get("removed_bytes", 0) or 0) + int(post_cache_prune_report.get("removed_bytes", 0) or 0)
    if removed_files:
        report.setdefault("native_preview_core_cache_pruned_files", removed_files)
        report.setdefault("native_preview_core_cache_pruned_bytes", removed_bytes)
    report.setdefault("native_preview_core_dds_cache_bytes", post_cache_prune_report.get("bytes", 0))
    report.setdefault("native_preview_core_dds_cache_files", post_cache_prune_report.get("files", 0))
    report.setdefault("native_preview_core_job_root", str(job_root))
    status = str(report.get("status") or "error").strip().lower()
    package_path = str(report.get("package_path") or "").strip()
    if status == "ok" and package_path:
        report.update(_repair_native_preview_core_manifest(package_path, render_settings))
    fallback_reason = str(report.get("fallback_reason") or report.get("message") or "").strip()
    if external_output_root:  # The caller owns output_root; only this transient protocol root is disposable.
        shutil.rmtree(job_root, ignore_errors=True)
    return NativePreviewCoreAttempt(
        status=status,
        package_path=package_path,
        fallback_reason=fallback_reason,
        diagnostics=dict(report),
        elapsed_ms=elapsed_ms,
        report_path="" if external_output_root else str(report_path),
        job_root_path="" if external_output_root else str(job_root),
    )


__all__ = [
    "NATIVE_PREVIEW_CORE_BACKEND_ID",
    "NATIVE_PREVIEW_CORE_BINARY_NAME",
    "NATIVE_PREVIEW_CORE_SERVICE_CACHE_RECYCLE_BYTES",
    "NATIVE_PREVIEW_CORE_DDS_CACHE_MAX_BYTES",
    "NATIVE_PREVIEW_CORE_DDS_CACHE_TARGET_BYTES",
    "NATIVE_PREVIEW_CORE_MAX_DEPENDENCY_ENTRIES",
    "NATIVE_PREVIEW_CORE_SERVICE_MAX_JOBS",
    "NATIVE_PREVIEW_CORE_SERVICE_PRIVATE_RECYCLE_BYTES",
    "NativePreviewCoreAttempt",
    "archive_entry_to_native_preview_core_dict",
    "build_native_preview_core_job",
    "default_native_preview_core_path",
    "find_native_preview_core_binary",
    "prune_native_preview_core_cache",
    "render_settings_to_native_preview_core_dict",
    "run_native_preview_core_preview_job",
    "shutdown_native_preview_core_service",
]


atexit.register(shutdown_native_preview_core_service)
