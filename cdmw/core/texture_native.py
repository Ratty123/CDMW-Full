from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from uuid import uuid4

from cdmw.core.common import hidden_subprocess_kwargs, raise_if_cancelled, run_process_with_cancellation
from cdmw.core.atomic_file import atomic_write_text
from cdmw.core.dds_native import inspect_dds_native_path
from cdmw.core.dds_resource_limits import (
    DDS_MAX_DECODED_BYTES,
    DDS_MAX_PAYLOAD_BYTES,
    checked_dds_mip_byte_counts,
)
from cdmw.core.temp_cache import app_temp_cache_path, request_app_temp_cache_prune
from cdmw.core.texture_decode_cache import (
    preview_cache_locks,
    preview_pair_is_valid,
    preview_sidecar_path,
    preview_staging_dir,
    publish_preview_pair,
)
from cdmw.models import RunCancelled

DIRECTXTEX_TEXTURE_BACKEND_ID = "directxtex_native_0.2"
NATIVE_TEXTURE_PROTOCOL_VERSION = 2
_DIRECTXTEX_FAILURE_REPORTS: deque[Dict[str, Any]] = deque(maxlen=128)
_DIRECTXTEX_FAILURE_REPORTS_LOCK = threading.Lock()
_UNSUPPORTED_NATIVE_DDS_REASON = "DDS format is not a supported 2D texture format"

_SOURCE_COLOR_POLICIES = frozenset({"auto", "ignore_srgb_metadata"})
_MIP_ALPHA_POLICIES = frozenset({"default", "separate", "preserve_coverage"})
_DDS_ALPHA_MODES = frozenset({"unknown", "straight", "premultiplied", "opaque", "custom"})
_OUTPUT_PIXEL_TYPES = frozenset({"rgba8", "gray16"})


@dataclass(frozen=True, slots=True)
class NativeTextureEncodeRequest:
    input_path: Path
    output_path: Path
    dds_format: str
    width: int = 0
    height: int = 0
    mip_count: int = 1
    overwrite: bool = True
    source_color_policy: str = "auto"
    mip_alpha_policy: str = "default"
    alpha_coverage_reference: float = 0.5
    dds_alpha_mode: str = "unknown"

    def __post_init__(self) -> None:
        if not str(self.dds_format or "").strip():
            raise ValueError("dds_format is required")
        if int(self.width) < 0 or int(self.height) < 0:
            raise ValueError("texture dimensions cannot be negative")
        if int(self.mip_count) < 0:
            raise ValueError("mip_count cannot be negative")
        if str(self.source_color_policy).strip().lower() not in _SOURCE_COLOR_POLICIES:
            raise ValueError(f"unsupported source color policy: {self.source_color_policy}")
        if str(self.mip_alpha_policy).strip().lower() not in _MIP_ALPHA_POLICIES:
            raise ValueError(f"unsupported mip alpha policy: {self.mip_alpha_policy}")
        if not 0.0 <= float(self.alpha_coverage_reference) <= 1.0:
            raise ValueError("alpha coverage reference must be between 0 and 1")
        if str(self.dds_alpha_mode).strip().lower() not in _DDS_ALPHA_MODES:
            raise ValueError(f"unsupported DDS alpha mode: {self.dds_alpha_mode}")


@dataclass(frozen=True, slots=True)
class NativeTextureDecodeRequest:
    input_path: Path
    output_path: Path
    max_dimension: int = 4096
    requested_mip: int = 0
    output_pixel_type: str = "rgba8"
    slot_kind: str = "base"
    normal_space: str = "auto"

    def __post_init__(self) -> None:
        if int(self.max_dimension) < 0:
            raise ValueError("max_dimension cannot be negative")
        if int(self.requested_mip) < 0:
            raise ValueError("requested_mip cannot be negative")
        if str(self.output_pixel_type).strip().lower() not in _OUTPUT_PIXEL_TYPES:
            raise ValueError(f"unsupported output pixel type: {self.output_pixel_type}")


@dataclass(frozen=True, slots=True)
class NativeTextureDecodeCacheJob:
    request: NativeTextureDecodeRequest
    result_key: str
    cache_key: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_directxtex_texture_binary_path(*, release: bool = True) -> Path:
    exe_name = "cd-texture-dx.exe" if os.name == "nt" else "cd-texture-dx"
    config = "Release" if release else "Debug"
    return _repo_root() / "native" / "cd_texture_dx" / "build" / config / exe_name


def find_directxtex_texture_binary() -> Optional[Path]:
    env_path = os.environ.get("CDMW_DIRECTXTEX_TEXTURE_BIN", "").strip()
    candidates = [Path(env_path)] if env_path else []
    frozen_root = Path(str(getattr(sys, "_MEIPASS", ""))) if getattr(sys, "_MEIPASS", "") else None
    exe_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    if frozen_root is not None:
        candidates.append(frozen_root / "native" / ("cd-texture-dx.exe" if os.name == "nt" else "cd-texture-dx"))
    if exe_root is not None:
        candidates.append(exe_root / "native" / ("cd-texture-dx.exe" if os.name == "nt" else "cd-texture-dx"))
    candidates.extend(
        [
            default_directxtex_texture_binary_path(release=True),
            default_directxtex_texture_binary_path(release=False),
            _repo_root() / "native" / "cd_texture_dx" / "bin" / "cd-texture-dx.exe",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def native_texture_available() -> bool:
    return find_directxtex_texture_binary() is not None


def directxtex_texture_failure_reports(*, clear: bool = False) -> tuple[Dict[str, Any], ...]:
    with _DIRECTXTEX_FAILURE_REPORTS_LOCK:
        reports = tuple(dict(report) for report in _DIRECTXTEX_FAILURE_REPORTS)
        if bool(clear):
            _DIRECTXTEX_FAILURE_REPORTS.clear()
        return reports


def _stderr_summary(stderr: object, *, limit: int = 2000) -> str:
    text = str(stderr or "").strip()
    if len(text) <= int(limit):
        return text
    return text[-int(limit):]


def _record_directxtex_failure(
    *,
    binary: Path | None,
    operation: str,
    returncode: object,
    stderr: object = "",
    source_path: object = "",
    retry_available: bool = False,
    reason: str = "",
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "status": "failed",
        "backend": "directxtex",
        "binary": str(binary or ""),
        "operation": str(operation or ""),
        "returncode": returncode,
        "stderr_summary": _stderr_summary(stderr),
        "source_path": str(source_path or ""),
        "retry_available": bool(retry_available),
    }
    if reason:
        report["reason"] = str(reason)
    with _DIRECTXTEX_FAILURE_REPORTS_LOCK:
        _DIRECTXTEX_FAILURE_REPORTS.append(report)
    return report


def _native_diagnostic_args() -> list[str]:
    args: list[str] = []
    crash_dir = str(os.environ.get("CDMW_CRASH_DIR", "") or "").strip()
    diagnostic_log = str(os.environ.get("CDMW_NATIVE_DIAGNOSTIC_LOG", "") or "").strip()
    if crash_dir:
        args.extend(["--crash-dir", crash_dir])
    if diagnostic_log:
        args.extend(["--diagnostic-log", diagnostic_log])
    return args


def _dds_decode_rejection_reason(dds_path: Path) -> str:
    try:
        source_size = int(dds_path.stat().st_size)
        info = inspect_dds_native_path(dds_path)
    except (OSError, ValueError) as exc:
        return f"DDS header inspection failed: {exc}"
    if source_size > DDS_MAX_PAYLOAD_BYTES:
        return f"DDS file exceeds the {DDS_MAX_PAYLOAD_BYTES:,}-byte resource limit."
    if info.width <= 0 or info.height <= 0:
        return info.reason or "DDS dimensions are invalid."
    if info.reason and info.reason != _UNSUPPORTED_NATIVE_DDS_REASON:
        return info.reason
    decoded_bytes_per_pixel = 16 if info.compressed_family == "bc6h" or info.reason else 4
    try:
        checked_dds_mip_byte_counts(
            info.width,
            info.height,
            info.mip_count,
            decoded_bytes_per_pixel,
            max_bytes=DDS_MAX_DECODED_BYTES,
            label="DDS decoded image",
        )
    except ValueError as exc:
        return str(exc)
    return ""


def native_texture_report_sidecar_path(preview_path: Path) -> Path:
    return preview_sidecar_path(preview_path)


def write_native_texture_report_sidecar(preview_path: Path, report: Mapping[str, Any]) -> bool:
    try:
        report_path = native_texture_report_sidecar_path(preview_path)
        atomic_write_text(report_path, json.dumps(dict(report), indent=2, sort_keys=True))
        return True
    except OSError:
        return False


def read_native_texture_report_sidecar(preview_path: Path) -> Dict[str, Any]:
    try:
        report_path = native_texture_report_sidecar_path(preview_path)
        if not report_path.is_file():
            return {}
        data = json.loads(report_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _binary_identity(binary: Path) -> str:
    try:
        stat = binary.stat()
    except OSError:
        return "missing"
    return f"{binary.resolve()}:{stat.st_size}:{getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1_000_000_000))}"


def _source_identity(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError:
        return "missing"
    return f"{path.resolve()}:{stat.st_size}:{getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1_000_000_000))}"


def native_texture_backend_identity(*, binary: Optional[Path] = None) -> str:
    resolved_binary = binary or find_directxtex_texture_binary()
    binary_identity = _binary_identity(resolved_binary) if resolved_binary is not None else "missing"
    return f"{DIRECTXTEX_TEXTURE_BACKEND_ID}|bin={binary_identity}"


def directxtex_texture_cache_key(
    dds_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    requested_mip: int = 0,
    output_pixel_type: str = "rgba8",
    binary: Optional[Path] = None,
) -> str:
    resolved_binary = binary or find_directxtex_texture_binary()
    identity = (
        f"{DIRECTXTEX_TEXTURE_BACKEND_ID}|{_source_identity(dds_path)}|"
        f"max={int(max_dimension)}|slot={str(slot_kind or 'base').strip().lower()}|"
        f"srgb={str(srgb or 'auto').strip().lower()}|"
        f"normal={str(normal_space or 'auto').strip().lower()}|"
        f"mip={max(0, int(requested_mip))}|pixel={str(output_pixel_type or 'rgba8').strip().lower()}|"
        f"bin={_binary_identity(resolved_binary) if resolved_binary is not None else 'none'}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def inspect_dds_with_directxtex(
    dds_path: Path,
    *,
    timeout_seconds: float = 5.0,
) -> Optional[Dict[str, Any]]:
    binary = find_directxtex_texture_binary()
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [str(binary), "inspect-json", str(dds_path), *_native_diagnostic_args()],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(0.5, float(timeout_seconds)),
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    try:
        parsed = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _directxtex_preview_cache_path(
    dds_path: Path,
    *,
    max_dimension: int,
    slot_kind: str,
    srgb: str,
    normal_space: str,
    requested_mip: int,
    output_pixel_type: str,
    binary: Path,
) -> Path:
    cache_key = directxtex_texture_cache_key(
        dds_path,
        max_dimension=max_dimension,
        slot_kind=slot_kind,
        srgb=srgb,
        normal_space=normal_space,
        requested_mip=requested_mip,
        output_pixel_type=output_pixel_type,
        binary=binary,
    )
    cache_dir = app_temp_cache_path("directxtex_texture_preview", cache_key)
    return cache_dir / f"{dds_path.stem}.png"


def directxtex_preview_result_key(
    dds_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    requested_mip: int = 0,
    output_pixel_type: str = "rgba8",
) -> str:
    try:
        source_key = str(Path(dds_path).expanduser().resolve())
    except OSError:
        source_key = str(dds_path)
    slot_key = str(slot_kind or "base").strip().lower() or "base"
    srgb_key = str(srgb or "auto").strip().lower() or "auto"
    normal_key = str(normal_space or "auto").strip().lower() or "auto"
    return (
        f"{source_key}|slot={slot_key}|max={max(0, int(max_dimension))}|"
        f"srgb={srgb_key}|normal={normal_key}|mip={max(0, int(requested_mip))}|"
        f"pixel={str(output_pixel_type or 'rgba8').strip().lower()}"
    )


def _cached_preview_is_valid(preview_path: Path) -> bool:
    return preview_pair_is_valid(preview_path)


def _clamp_native_batch_timeout(seconds: float) -> float:
    return min(3600.0, max(120.0, float(seconds)))


def _native_timeout_components(dds_format: str, megapixels: float) -> tuple[float, float]:
    family = str(dds_format or "").strip().upper()
    if family.startswith(("BC6", "BC7")):
        return 60.0, 45.0 * max(0.0, float(megapixels))
    if family.startswith(("BC1", "BC2", "BC3", "BC4", "BC5")):
        return 30.0, 10.0 * max(0.0, float(megapixels))
    return 30.0, 3.0 * max(0.0, float(megapixels))


def native_decode_timeout_seconds(requests: Sequence[NativeTextureDecodeRequest]) -> float:
    if not requests:
        return 120.0
    base = 30.0
    variable = 0.0
    for request in requests:
        try:
            info = inspect_dds_native_path(request.input_path)
            mip_width = max(1, int(info.width) >> int(request.requested_mip))
            mip_height = max(1, int(info.height) >> int(request.requested_mip))
            max_dimension = max(0, int(request.max_dimension))
            if max_dimension and max(mip_width, mip_height) > max_dimension:
                scale = float(max_dimension) / float(max(mip_width, mip_height))
                mip_width = max(1, int(round(mip_width * scale)))
                mip_height = max(1, int(round(mip_height * scale)))
            request_base, request_variable = _native_timeout_components(
                info.format_name,
                (mip_width * mip_height) / 1_000_000.0,
            )
        except (OSError, ValueError):
            request_base, request_variable = 30.0, 0.0
        base = max(base, request_base)
        variable += request_variable
    return _clamp_native_batch_timeout(base + variable)


def _decode_request_payload(
    request: NativeTextureDecodeRequest,
    *,
    output_path: Optional[Path] = None,
) -> Dict[str, object]:
    return {
        "input": str(request.input_path),
        "output": str(output_path or request.output_path),
        "max_dimension": max(0, int(request.max_dimension)),
        "slot": str(request.slot_kind or "base").strip().lower() or "base",
        "normal_space": str(request.normal_space or "auto").strip().lower() or "auto",
        "requested_mip": max(0, int(request.requested_mip)),
        "output_pixel_type": str(request.output_pixel_type or "rgba8").strip().lower() or "rgba8",
    }


def _decode_staging_parent(preview_path: Path, temp_root: Optional[Path]) -> Path:
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    if temp_root is None:
        return preview_path.parent
    candidate = Path(temp_root).expanduser().resolve()
    candidate.mkdir(parents=True, exist_ok=True)
    try:
        if candidate.stat().st_dev == preview_path.parent.stat().st_dev:
            return candidate
    except OSError:
        pass
    return preview_path.parent


def ensure_directxtex_dds_preview_png(
    dds_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    requested_mip: int = 0,
    output_pixel_type: str = "rgba8",
    timeout_seconds: Optional[float] = None,
    on_log: Optional[Any] = None,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Path]:
    results = ensure_directxtex_dds_preview_pngs(
        (
            {
                "dds_path": str(dds_path),
                "max_dimension": max_dimension,
                "slot_kind": slot_kind,
                "srgb": srgb,
                "normal_space": normal_space,
                "requested_mip": requested_mip,
                "output_pixel_type": output_pixel_type,
            },
        ),
        timeout_seconds=timeout_seconds,
        on_log=on_log,
        stop_event=stop_event,
    )
    return results.get(str(Path(dds_path).expanduser().resolve()))


def ensure_directxtex_dds_preview_pngs(
    jobs: Sequence[Mapping[str, object]],
    *,
    timeout_seconds: Optional[float] = None,
    include_job_keys: bool = False,
    on_log: Optional[Any] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, Path]:
    raise_if_cancelled(stop_event, "DirectXTex preview conversion cancelled.")
    if os.environ.get("CDMW_DEFER_TEXTURE_PREVIEW", "").strip():
        return {}
    binary = find_directxtex_texture_binary()
    if binary is None:
        _record_directxtex_failure(
            binary=None,
            operation="batch-preview-json",
            returncode="missing",
            retry_available=False,
            reason="native_helper_missing",
        )
        return {}
    normalized_jobs: list[NativeTextureDecodeCacheJob] = []
    seen_cache_keys: set[str] = set()
    results: Dict[str, Path] = {}
    for job in jobs:
        raise_if_cancelled(stop_event, "DirectXTex preview conversion cancelled.")
        raw_path = str(job.get("dds_path") or job.get("input") or "").strip()
        if not raw_path:
            continue
        try:
            dds_path = Path(raw_path).expanduser().resolve()
        except OSError:
            continue
        if not dds_path.is_file():
            continue
        rejection_reason = _dds_decode_rejection_reason(dds_path)
        if rejection_reason:
            _record_directxtex_failure(
                binary=binary,
                operation="batch-preview-json",
                returncode="rejected",
                stderr=rejection_reason,
                source_path=dds_path,
                retry_available=False,
                reason="unsafe_dds_input",
            )
            continue
        max_dimension = max(0, int(job.get("max_dimension") if job.get("max_dimension") is not None else job.get("max_dim") or 4096))
        slot_kind = str(job.get("slot_kind") or job.get("slot") or "base").strip().lower() or "base"
        srgb = str(job.get("srgb") or "auto").strip().lower() or "auto"
        normal_space = str(job.get("normal_space") or "auto").strip().lower() or "auto"
        requested_mip = max(0, int(job.get("requested_mip") or job.get("mip_level") or 0))
        output_pixel_type = str(job.get("output_pixel_type") or "rgba8").strip().lower() or "rgba8"
        if output_pixel_type not in _OUTPUT_PIXEL_TYPES:
            _record_directxtex_failure(
                binary=binary,
                operation="batch-preview-json",
                returncode="rejected",
                stderr=f"unsupported output pixel type: {output_pixel_type}",
                source_path=dds_path,
                retry_available=False,
                reason="invalid_decode_request",
            )
            continue
        cache_key = directxtex_texture_cache_key(
            dds_path,
            max_dimension=max_dimension,
            slot_kind=slot_kind,
            srgb=srgb,
            normal_space=normal_space,
            requested_mip=requested_mip,
            output_pixel_type=output_pixel_type,
            binary=binary,
        )
        preview_path = _directxtex_preview_cache_path(
            dds_path,
            max_dimension=max_dimension,
            slot_kind=slot_kind,
            srgb=srgb,
            normal_space=normal_space,
            requested_mip=requested_mip,
            output_pixel_type=output_pixel_type,
            binary=binary,
        )
        key = str(dds_path)
        job_key = directxtex_preview_result_key(
            dds_path,
            max_dimension=max_dimension,
            slot_kind=slot_kind,
            srgb=srgb,
            normal_space=normal_space,
            requested_mip=requested_mip,
            output_pixel_type=output_pixel_type,
        )
        normalized = NativeTextureDecodeCacheJob(
            request=NativeTextureDecodeRequest(
                input_path=dds_path,
                output_path=preview_path,
                max_dimension=max_dimension,
                requested_mip=requested_mip,
                output_pixel_type=output_pixel_type,
                slot_kind=slot_kind,
                normal_space=normal_space,
            ),
            result_key=job_key,
            cache_key=cache_key,
        )
        if _cached_preview_is_valid(preview_path):
            results[key] = preview_path
            if include_job_keys:
                results[job_key] = preview_path
            continue
        if normalized.cache_key not in seen_cache_keys:
            seen_cache_keys.add(normalized.cache_key)
            normalized_jobs.append(normalized)
    if not normalized_jobs:
        return results
    resolved_timeout = (
        _clamp_native_batch_timeout(float(timeout_seconds))
        if timeout_seconds is not None
        else native_decode_timeout_seconds(tuple(job.request for job in normalized_jobs))
    )
    lock_keys = [f"directxtex:{job.cache_key}" for job in normalized_jobs]
    with preview_cache_locks(lock_keys):
        from cdmw.core.texture_native_preview_cache import ensure_preview_batch_locked

        return ensure_preview_batch_locked(
            binary,
            normalized_jobs,
            results,
            timeout_seconds=resolved_timeout,
            include_job_keys=include_job_keys,
            on_log=on_log,
            stop_event=stop_event,
        )


def ensure_native_dds_preview_png(
    dds_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    requested_mip: int = 0,
    output_pixel_type: str = "rgba8",
    timeout_seconds: Optional[float] = None,
    on_log: Optional[Any] = None,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Path]:
    return ensure_directxtex_dds_preview_png(
        dds_path,
        max_dimension=max_dimension,
        slot_kind=slot_kind,
        srgb=srgb,
        normal_space=normal_space,
        requested_mip=requested_mip,
        output_pixel_type=output_pixel_type,
        timeout_seconds=timeout_seconds,
        on_log=on_log,
        stop_event=stop_event,
    )


def decode_dds_preview_with_directxtex(
    dds_path: Path,
    output_png_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    requested_mip: int = 0,
    output_pixel_type: str = "rgba8",
    timeout_seconds: Optional[float] = None,
    on_log: Optional[Any] = None,
    temp_root: Optional[Path] = None,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Dict[str, Any]]:
    raise_if_cancelled(stop_event, "DirectXTex preview conversion cancelled.")
    binary = find_directxtex_texture_binary()
    if binary is None:
        _record_directxtex_failure(
            binary=None,
            operation="batch-preview-json",
            returncode="missing",
            source_path=dds_path,
            retry_available=False,
            reason="native_helper_missing",
        )
        return None
    source_path = Path(dds_path).expanduser().resolve()
    preview_path = Path(output_png_path).expanduser().resolve()
    if not source_path.is_file():
        return None
    rejection_reason = _dds_decode_rejection_reason(source_path)
    if rejection_reason:
        _record_directxtex_failure(
            binary=binary,
            operation="batch-preview-json",
            returncode="rejected",
            stderr=rejection_reason,
            source_path=source_path,
            retry_available=False,
            reason="unsafe_dds_input",
        )
        return None
    request = NativeTextureDecodeRequest(
        input_path=source_path,
        output_path=preview_path,
        max_dimension=max_dimension,
        requested_mip=requested_mip,
        output_pixel_type=output_pixel_type,
        slot_kind=slot_kind,
        normal_space=normal_space,
    )
    resolved_timeout = (
        _clamp_native_batch_timeout(float(timeout_seconds))
        if timeout_seconds is not None
        else native_decode_timeout_seconds((request,))
    )
    cache_key = hashlib.sha256(
        (
            f"direct-output|{directxtex_texture_cache_key(source_path, max_dimension=max_dimension, slot_kind=slot_kind, srgb=srgb, normal_space=normal_space, requested_mip=requested_mip, output_pixel_type=output_pixel_type, binary=binary)}"
            f"|{preview_path}"
        ).encode("utf-8")
    ).hexdigest()
    with preview_cache_locks((f"directxtex-output:{cache_key}",)):
        cached_report = read_native_texture_report_sidecar(preview_path)
        if _cached_preview_is_valid(preview_path) and cached_report.get("cache_key") == cache_key:
            return cached_report
        with preview_staging_dir(_decode_staging_parent(preview_path, temp_root)) as job_root:
            staged = job_root / preview_path.name
            job_path = job_root / "job.json"
            report_path = job_root / "report.json"
            job = _decode_request_payload(request, output_path=staged)
            job_path.write_text(
                json.dumps(
                    {
                        "version": NATIVE_TEXTURE_PROTOCOL_VERSION,
                        "backend": DIRECTXTEX_TEXTURE_BACKEND_ID,
                        "jobs": [job],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            def emit_heartbeat(elapsed_seconds: float) -> None:
                if on_log is not None:
                    on_log(
                        f"Native texture decode is still running after {elapsed_seconds:.0f}s "
                        f"(timeout {resolved_timeout:.0f}s)."
                    )

            try:
                returncode, _stdout, stderr = run_process_with_cancellation(
                    [str(binary), "batch-preview-json", str(job_path), str(report_path), *_native_diagnostic_args()],
                    timeout_seconds=resolved_timeout,
                    timeout_warning_interval_seconds=30.0,
                    on_timeout_warning=emit_heartbeat,
                    stop_event=stop_event,
                )
            except RunCancelled:
                raise
            except Exception as exc:
                _record_directxtex_failure(
                    binary=binary,
                    operation="batch-preview-json",
                    returncode="exception",
                    stderr=str(exc),
                    source_path=source_path,
                    retry_available=False,
                    reason=type(exc).__name__,
                )
                return None
            from cdmw.core.texture_native_preview_cache import read_preview_items

            items = read_preview_items(binary, report_path, returncode, stderr, source_path=source_path)
            if not items or not isinstance(items[0], dict):
                return None
            item = dict(items[0])
            if str(item.get("status") or "").lower() != "decoded" or not staged.is_file():
                return None
            item.setdefault("backend", DIRECTXTEX_TEXTURE_BACKEND_ID)
            item.setdefault("native_backend", "directxtex")
            item["source_path"] = str(source_path)
            item["output_path"] = str(preview_path)
            item["cache_key"] = cache_key
            try:
                publish_preview_pair(staged, preview_path, item)
            except (OSError, ValueError) as exc:
                _record_directxtex_failure(
                    binary=binary,
                    operation="batch-preview-json",
                    returncode="publication_failed",
                    stderr=str(exc),
                    source_path=source_path,
                    retry_available=False,
                    reason="atomic_publication_failed",
                )
                return None
            return item


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Native DDS encode input is not a valid PNG: {path}")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _requested_mip_pixels(width: int, height: int, mip_count: int) -> int:
    width = max(1, int(width))
    height = max(1, int(height))
    requested = int(mip_count)
    total = 0
    level = 0
    while True:
        total += width * height
        level += 1
        if width == 1 and height == 1:
            break
        if requested > 0 and level >= requested:
            break
        width = max(1, width // 2)
        height = max(1, height // 2)
    return total


def native_encode_timeout_seconds(requests: Sequence[NativeTextureEncodeRequest]) -> float:
    if not requests:
        return 120.0
    base = 30.0
    variable = 0.0
    for request in requests:
        source_width, source_height = _png_dimensions(request.input_path)
        width = int(request.width) or source_width
        height = int(request.height) or source_height
        megapixels = _requested_mip_pixels(width, height, request.mip_count) / 1_000_000.0
        request_base, request_variable = _native_timeout_components(request.dds_format, megapixels)
        base = max(base, request_base)
        variable += request_variable
    return _clamp_native_batch_timeout(base + variable)


def _encode_request_from_mapping(job: Mapping[str, object]) -> NativeTextureEncodeRequest:
    raw_input = str(job.get("png_path") or job.get("input") or job.get("source_path") or "").strip()
    raw_output = str(job.get("output_path") or job.get("dds_path") or job.get("output") or "").strip()
    if not raw_input or not raw_output:
        raise ValueError("native texture encode requests require input and output paths")
    return NativeTextureEncodeRequest(
        input_path=Path(raw_input).expanduser().resolve(),
        output_path=Path(raw_output).expanduser().resolve(),
        dds_format=str(job.get("dds_format") or job.get("format") or "BC7_UNORM").strip().upper(),
        width=max(0, int(job.get("width") or job.get("target_width") or 0)),
        height=max(0, int(job.get("height") or job.get("target_height") or 0)),
        mip_count=max(0, int(job.get("mip_count") if job.get("mip_count") is not None else job.get("mips") or 1)),
        overwrite=bool(job.get("overwrite", True)),
        source_color_policy=str(job.get("source_color_policy") or "auto").strip().lower(),
        mip_alpha_policy=str(job.get("mip_alpha_policy") or "default").strip().lower(),
        alpha_coverage_reference=float(job.get("alpha_coverage_reference", 0.5)),
        dds_alpha_mode=str(job.get("dds_alpha_mode") or "unknown").strip().lower(),
    )


def _normalized_encode_request(
    request: NativeTextureEncodeRequest | Mapping[str, object],
) -> NativeTextureEncodeRequest:
    if isinstance(request, NativeTextureEncodeRequest):
        return NativeTextureEncodeRequest(
            input_path=request.input_path.expanduser().resolve(),
            output_path=request.output_path.expanduser().resolve(),
            dds_format=request.dds_format.strip().upper(),
            width=request.width,
            height=request.height,
            mip_count=request.mip_count,
            overwrite=request.overwrite,
            source_color_policy=request.source_color_policy.strip().lower(),
            mip_alpha_policy=request.mip_alpha_policy.strip().lower(),
            alpha_coverage_reference=request.alpha_coverage_reference,
            dds_alpha_mode=request.dds_alpha_mode.strip().lower(),
        )
    return _encode_request_from_mapping(request)


def _staged_dds_path(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path.with_name(f".{output_path.stem}.cdmw-{uuid4().hex}.dds")


def _encode_request_payload(request: NativeTextureEncodeRequest, staged_path: Path) -> Dict[str, object]:
    return {
        "input": str(request.input_path),
        "output": str(staged_path),
        "format": request.dds_format,
        "width": int(request.width),
        "height": int(request.height),
        "mip_count": int(request.mip_count),
        "overwrite": bool(request.overwrite),
        "source_color_policy": request.source_color_policy,
        "mip_alpha_policy": request.mip_alpha_policy,
        "alpha_coverage_reference": float(request.alpha_coverage_reference),
        "dds_alpha_mode": request.dds_alpha_mode,
    }


def _validate_staged_dds(
    staged_path: Path,
    request: NativeTextureEncodeRequest,
    item: Mapping[str, object],
) -> None:
    if not staged_path.is_file() or staged_path.stat().st_size <= 128:
        raise ValueError("native helper did not produce a complete DDS file")
    source_width, source_height = _png_dimensions(request.input_path)
    expected_width = int(request.width) or source_width
    expected_height = int(request.height) or source_height
    max_mips = int(math.floor(math.log2(max(expected_width, expected_height)))) + 1
    expected_mips = max_mips if int(request.mip_count) == 0 else min(max_mips, max(1, int(request.mip_count)))
    reported_format = str(item.get("format") or "").removeprefix("DXGI_FORMAT_").upper()
    if reported_format != request.dds_format.upper():
        raise ValueError(f"native DDS format mismatch: expected {request.dds_format}, got {reported_format or 'unknown'}")
    if int(item.get("width") or 0) != expected_width or int(item.get("height") or 0) != expected_height:
        raise ValueError(
            f"native DDS dimension mismatch: expected {expected_width}x{expected_height}, "
            f"got {item.get('width')}x{item.get('height')}"
        )
    if int(item.get("mip_count") or 0) != expected_mips:
        raise ValueError(f"native DDS mip mismatch: expected {expected_mips}, got {item.get('mip_count')}")
    inspected = inspect_dds_native_path(staged_path)
    if inspected.width != expected_width or inspected.height != expected_height or inspected.mip_count != expected_mips:
        raise ValueError("published DDS header does not match the native encode report")
    reported_dxgi = int(item.get("dxgi_format") or 0)
    if inspected.dxgi_format and reported_dxgi and inspected.dxgi_format != reported_dxgi:
        raise ValueError(
            f"published DDS DXGI format mismatch: expected {reported_dxgi}, got {inspected.dxgi_format}"
        )


def encode_dds_with_directxtex(
    png_path: Path,
    output_dds_path: Path,
    *,
    dds_format: str,
    width: int = 0,
    height: int = 0,
    mip_count: int = 1,
    overwrite: bool = True,
    source_color_policy: str = "auto",
    mip_alpha_policy: str = "default",
    alpha_coverage_reference: float = 0.5,
    dds_alpha_mode: str = "unknown",
    timeout_seconds: Optional[float] = None,
    on_log: Optional[Any] = None,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Dict[str, Any]]:
    request = NativeTextureEncodeRequest(
        input_path=Path(png_path),
        output_path=Path(output_dds_path),
        dds_format=dds_format,
        width=width,
        height=height,
        mip_count=mip_count,
        overwrite=overwrite,
        source_color_policy=source_color_policy,
        mip_alpha_policy=mip_alpha_policy,
        alpha_coverage_reference=alpha_coverage_reference,
        dds_alpha_mode=dds_alpha_mode,
    )
    results = encode_dds_batch_with_directxtex(
        (request,),
        timeout_seconds=timeout_seconds,
        on_log=on_log,
        stop_event=stop_event,
    )
    try:
        output_key = str(Path(output_dds_path).expanduser().resolve())
    except OSError:
        output_key = str(output_dds_path)
    return results.get(output_key)


def encode_dds_batch_with_directxtex(
    jobs: Sequence[NativeTextureEncodeRequest | Mapping[str, object]],
    *,
    timeout_seconds: Optional[float] = None,
    on_log: Optional[Any] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, Dict[str, Any]]:
    raise_if_cancelled(stop_event, "DirectXTex DDS encode cancelled.")
    binary = find_directxtex_texture_binary()
    if binary is None:
        _record_directxtex_failure(
            binary=None,
            operation="batch-encode-json",
            returncode="missing",
            retry_available=False,
            reason="native_helper_missing",
        )
        return {}

    requests: list[NativeTextureEncodeRequest] = []
    for job in jobs:
        raise_if_cancelled(stop_event, "DirectXTex DDS encode cancelled.")
        try:
            request = _normalized_encode_request(job)
        except (OSError, TypeError, ValueError) as exc:
            _record_directxtex_failure(
                binary=binary,
                operation="batch-encode-json",
                returncode="rejected",
                stderr=str(exc),
                retry_available=False,
                reason="invalid_encode_request",
            )
            continue
        if not request.input_path.is_file():
            _record_directxtex_failure(
                binary=binary,
                operation="batch-encode-json",
                returncode="rejected",
                stderr=f"PNG input does not exist: {request.input_path}",
                source_path=request.input_path,
                retry_available=False,
                reason="missing_input",
            )
            continue
        try:
            _png_dimensions(request.input_path)
        except (OSError, ValueError) as exc:
            _record_directxtex_failure(
                binary=binary,
                operation="batch-encode-json",
                returncode="rejected",
                stderr=str(exc),
                source_path=request.input_path,
                retry_available=False,
                reason="invalid_png_input",
            )
            continue
        if request.output_path.exists() and not request.overwrite:
            _record_directxtex_failure(
                binary=binary,
                operation="batch-encode-json",
                returncode="rejected",
                stderr=f"output exists and overwrite=false: {request.output_path}",
                source_path=request.input_path,
                retry_available=False,
                reason="overwrite_rejected",
            )
            continue
        requests.append(request)
    if not requests:
        return {}

    resolved_timeout = (
        _clamp_native_batch_timeout(float(timeout_seconds))
        if timeout_seconds is not None
        else native_encode_timeout_seconds(requests)
    )
    staged_by_path: Dict[str, tuple[NativeTextureEncodeRequest, Path]] = {}
    staged_paths: list[Path] = []
    helper_jobs: list[Dict[str, object]] = []
    for request in requests:
        staged = _staged_dds_path(request.output_path)
        staged_paths.append(staged)
        helper_jobs.append(_encode_request_payload(request, staged))
        staged_by_path[str(staged.resolve())] = (request, staged)

    job_root = Path(tempfile.mkdtemp(prefix="cdmw_directxtex_encode_"))
    job_path = job_root / "job.json"
    report_path = job_root / "report.json"
    started_at = time.monotonic()

    def emit_heartbeat(elapsed_seconds: float) -> None:
        if on_log is not None:
            on_log(
                f"Native texture encode is still running after {elapsed_seconds:.0f}s "
                f"(timeout {resolved_timeout:.0f}s)."
            )

    try:
        job_path.write_text(
            json.dumps(
                {
                    "version": NATIVE_TEXTURE_PROTOCOL_VERSION,
                    "backend": DIRECTXTEX_TEXTURE_BACKEND_ID,
                    "jobs": helper_jobs,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        try:
            returncode, _stdout, stderr = run_process_with_cancellation(
                [str(binary), "batch-encode-json", str(job_path), str(report_path), *_native_diagnostic_args()],
                timeout_seconds=resolved_timeout,
                timeout_warning_interval_seconds=30.0,
                on_timeout_warning=emit_heartbeat,
                stop_event=stop_event,
            )
        except RunCancelled:
            raise
        except Exception as exc:
            _record_directxtex_failure(
                binary=binary,
                operation="batch-encode-json",
                returncode="exception",
                stderr=str(exc),
                retry_available=False,
                reason=type(exc).__name__,
            )
            return {}
        if returncode not in {0, 2} or not report_path.is_file():
            _record_directxtex_failure(
                binary=binary,
                operation="batch-encode-json",
                returncode=returncode,
                stderr=stderr,
                retry_available=False,
                reason="missing_report" if not report_path.is_file() else "nonzero_returncode",
            )
            return {}
        try:
            parsed = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _record_directxtex_failure(
                binary=binary,
                operation="batch-encode-json",
                returncode=returncode,
                stderr=str(exc),
                retry_available=False,
                reason="invalid_report_json",
            )
            return {}
        items = parsed.get("items") if isinstance(parsed, dict) else None
        if not isinstance(items, list):
            _record_directxtex_failure(
                binary=binary,
                operation="batch-encode-json",
                returncode=returncode,
                retry_available=False,
                reason="missing_report_items",
            )
            return {}

        results: Dict[str, Dict[str, Any]] = {}
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            try:
                item_path = str(Path(str(raw_item.get("output_path") or "")).resolve())
            except OSError:
                item_path = ""
            matched = staged_by_path.get(item_path)
            if matched is None:
                continue
            request, staged = matched
            if str(raw_item.get("status") or "").lower() != "encoded":
                _record_directxtex_failure(
                    binary=binary,
                    operation="batch-encode-json",
                    returncode=returncode,
                    stderr=raw_item.get("message", ""),
                    source_path=request.input_path,
                    retry_available=False,
                    reason="native_item_failed",
                )
                continue
            try:
                _validate_staged_dds(staged, request, raw_item)
                raise_if_cancelled(stop_event, "DirectXTex DDS encode cancelled before publication.")
                os.replace(staged, request.output_path)
            except RunCancelled:
                raise
            except Exception as exc:
                _record_directxtex_failure(
                    binary=binary,
                    operation="batch-encode-json",
                    returncode="validation_or_publication_failed",
                    stderr=str(exc),
                    source_path=request.input_path,
                    retry_available=False,
                    reason="atomic_publication_failed",
                )
                continue
            item = dict(raw_item)
            item.setdefault("backend", DIRECTXTEX_TEXTURE_BACKEND_ID)
            item.setdefault("native_backend", "directxtex")
            item["source_path"] = str(request.input_path)
            item["output_path"] = str(request.output_path)
            item["protocol_version"] = NATIVE_TEXTURE_PROTOCOL_VERSION
            item["batch_elapsed_seconds"] = time.monotonic() - started_at
            results[str(request.output_path)] = item
        return results
    finally:
        for staged in staged_paths:
            staged.unlink(missing_ok=True)
        shutil.rmtree(job_root, ignore_errors=True)
