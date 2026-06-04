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
from typing import Any, Callable, Dict, Mapping, Optional

from cdmw.core.common import hidden_subprocess_kwargs, raise_if_cancelled, run_process_with_cancellation
from cdmw.models import ArchiveEntry, ModelPreviewRenderSettings, RunCancelled

NATIVE_PREVIEW_CORE_BINARY_NAME = "cdmw-preview-core.exe" if os.name == "nt" else "cdmw-preview-core"
NATIVE_PREVIEW_CORE_BACKEND_ID = "cdmw_preview_core_0.1"
NATIVE_PREVIEW_CORE_SERVICE_MAX_JOBS = 32
NATIVE_PREVIEW_CORE_SERVICE_CACHE_RECYCLE_BYTES = 192 * 1024 * 1024
NATIVE_PREVIEW_CORE_SERVICE_PRIVATE_RECYCLE_BYTES = 768 * 1024 * 1024
NATIVE_PREVIEW_CORE_DDS_CACHE_MAX_BYTES = 96 * 1024 * 1024
NATIVE_PREVIEW_CORE_DDS_CACHE_TARGET_BYTES = 64 * 1024 * 1024


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
            return "Native Preview Core: unavailable; D3D11 native package generation is disabled for this entry."
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
            try:
                if process.poll() is None and process.stdin is not None:
                    process.stdin.write('{"command":"shutdown"}\n')
                    process.stdin.flush()
            except OSError:
                pass
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    pass

    def _kill_locked(self) -> None:
        process = self._process
        self._process = None
        self._jobs_completed = 0
        if process is None:
            return
        try:
            process.kill()
        except OSError:
            pass

    def _read_stdout_line_locked(self, timeout_seconds: float, stop_event: Any = None) -> str:
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("native preview-core service is not running")
        result: Dict[str, object] = {}

        def read_line() -> None:
            try:
                result["line"] = process.stdout.readline()
            except Exception as exc:  # pragma: no cover - defensive for pipe teardown
                result["error"] = exc

        thread = threading.Thread(target=read_line, name="cdmw-preview-core-readline", daemon=True)
        thread.start()
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        while thread.is_alive():
            raise_if_cancelled(stop_event, "Native preview-core job cancelled.")
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
            **hidden_subprocess_kwargs(),
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
    }


def build_native_preview_core_job(
    entry: ArchiveEntry,
    *,
    cache_root: Path,
    output_root: Path,
    render_settings: Optional[ModelPreviewRenderSettings] = None,
    companion_entry: Optional[ArchiveEntry] = None,
    package_root: Optional[Path] = None,
    renderer_backend: str = "d3d11",
    schema_version: int = 8,
) -> Dict[str, Any]:
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
    binary = find_native_preview_core_binary()
    if binary is None:
        return NativePreviewCoreAttempt(
            status="missing",
            fallback_reason="cdmw-preview-core binary was not found",
        )

    job_root = Path(tempfile.mkdtemp(prefix="cdmw_preview_core_"))
    output_root = Path(output_root) if output_root is not None else job_root / "package"
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
    fallback_reason = str(report.get("fallback_reason") or report.get("message") or "").strip()
    return NativePreviewCoreAttempt(
        status=status,
        package_path=package_path,
        fallback_reason=fallback_reason,
        diagnostics=dict(report),
        elapsed_ms=elapsed_ms,
        report_path=str(report_path),
        job_root_path=str(job_root),
    )


__all__ = [
    "NATIVE_PREVIEW_CORE_BACKEND_ID",
    "NATIVE_PREVIEW_CORE_BINARY_NAME",
    "NATIVE_PREVIEW_CORE_SERVICE_CACHE_RECYCLE_BYTES",
    "NATIVE_PREVIEW_CORE_DDS_CACHE_MAX_BYTES",
    "NATIVE_PREVIEW_CORE_DDS_CACHE_TARGET_BYTES",
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
