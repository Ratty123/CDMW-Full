from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import deque
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from cdmw.core.common import hidden_subprocess_kwargs, raise_if_cancelled, run_process_with_cancellation
from cdmw.core.atomic_file import atomic_write_text
from cdmw.core.dds_native import dds_native_report_dict, inspect_dds_native_path
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

DIRECTXTEX_TEXTURE_BACKEND_ID = "directxtex_native_0.1"
_DIRECTXTEX_FAILURE_REPORTS: deque[Dict[str, Any]] = deque(maxlen=128)
_DIRECTXTEX_FAILURE_REPORTS_LOCK = threading.Lock()
_UNSUPPORTED_NATIVE_DDS_REASON = "DDS format is not a supported 2D texture format"


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
    fallback_available: bool = True,
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
        "fallback_available": bool(fallback_available),
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


def directxtex_texture_cache_key(
    dds_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    fallback_mode: str = "texconv",
    binary: Optional[Path] = None,
) -> str:
    resolved_binary = binary or find_directxtex_texture_binary()
    identity = (
        f"{DIRECTXTEX_TEXTURE_BACKEND_ID}|{_source_identity(dds_path)}|"
        f"max={int(max_dimension)}|slot={str(slot_kind or 'base').strip().lower()}|"
        f"srgb={str(srgb or 'auto').strip().lower()}|"
        f"normal={str(normal_space or 'auto').strip().lower()}|fallback={fallback_mode}|"
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
    binary: Path,
) -> Path:
    cache_key = directxtex_texture_cache_key(
        dds_path,
        max_dimension=max_dimension,
        slot_kind=slot_kind,
        srgb=srgb,
        normal_space=normal_space,
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
) -> str:
    try:
        source_key = str(Path(dds_path).expanduser().resolve())
    except OSError:
        source_key = str(dds_path)
    slot_key = str(slot_kind or "base").strip().lower() or "base"
    srgb_key = str(srgb or "auto").strip().lower() or "auto"
    normal_key = str(normal_space or "auto").strip().lower() or "auto"
    return (
        f"{source_key}|slot={slot_key}|max={max(1, int(max_dimension or 4096))}|"
        f"srgb={srgb_key}|normal={normal_key}"
    )


def _cached_preview_is_valid(preview_path: Path) -> bool:
    return preview_pair_is_valid(preview_path)


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
    timeout_seconds: float = 20.0,
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
            },
        ),
        timeout_seconds=timeout_seconds,
        stop_event=stop_event,
    )
    return results.get(str(Path(dds_path).expanduser().resolve()))


def ensure_directxtex_dds_preview_pngs(
    jobs: Sequence[Mapping[str, object]],
    *,
    timeout_seconds: float = 45.0,
    include_job_keys: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, Path]:
    raise_if_cancelled(stop_event, "DirectXTex preview conversion cancelled.")
    if os.environ.get("CDMW_DEFER_TEXTURE_PREVIEW", "").strip():
        return {}
    binary = find_directxtex_texture_binary()
    if binary is None:
        return {}
    normalized_jobs: list[Dict[str, object]] = []
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
                fallback_available=True,
                reason="unsafe_dds_input",
            )
            continue
        max_dimension = max(1, int(job.get("max_dimension") or job.get("max_dim") or 4096))
        slot_kind = str(job.get("slot_kind") or job.get("slot") or "base").strip().lower() or "base"
        srgb = str(job.get("srgb") or "auto").strip().lower() or "auto"
        normal_space = str(job.get("normal_space") or "auto").strip().lower() or "auto"
        cache_key = directxtex_texture_cache_key(
            dds_path,
            max_dimension=max_dimension,
            slot_kind=slot_kind,
            srgb=srgb,
            normal_space=normal_space,
            binary=binary,
        )
        preview_path = _directxtex_preview_cache_path(
            dds_path,
            max_dimension=max_dimension,
            slot_kind=slot_kind,
            srgb=srgb,
            normal_space=normal_space,
            binary=binary,
        )
        key = str(dds_path)
        job_key = directxtex_preview_result_key(
            dds_path,
            max_dimension=max_dimension,
            slot_kind=slot_kind,
            srgb=srgb,
            normal_space=normal_space,
        )
        normalized = {
            "input": key,
            "output": str(preview_path),
            "max_dimension": max_dimension,
            "slot": slot_kind,
            "srgb": srgb,
            "normal_space": normal_space,
            "result_key": job_key,
            "cache_key": cache_key,
        }
        if _cached_preview_is_valid(preview_path):
            results[key] = preview_path
            if include_job_keys:
                results[job_key] = preview_path
            continue
        if cache_key not in seen_cache_keys:
            seen_cache_keys.add(cache_key)
            normalized_jobs.append(normalized)
    if not normalized_jobs:
        return results
    lock_keys = [f"directxtex:{job['cache_key']}" for job in normalized_jobs]
    with preview_cache_locks(lock_keys):
        from cdmw.core.texture_native_preview_cache import ensure_preview_batch_locked

        return ensure_preview_batch_locked(
            binary,
            normalized_jobs,
            results,
            timeout_seconds=timeout_seconds,
            include_job_keys=include_job_keys,
            stop_event=stop_event,
        )


def ensure_native_dds_preview_png(
    dds_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    timeout_seconds: float = 20.0,
) -> Optional[Path]:
    return ensure_directxtex_dds_preview_png(
        dds_path,
        max_dimension=max_dimension,
        slot_kind=slot_kind,
        srgb=srgb,
        normal_space=normal_space,
        timeout_seconds=timeout_seconds,
    )


def decode_dds_preview_with_directxtex(
    dds_path: Path,
    output_png_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    timeout_seconds: float = 20.0,
    temp_root: Optional[Path] = None,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Dict[str, Any]]:
    raise_if_cancelled(stop_event, "DirectXTex preview conversion cancelled.")
    binary = find_directxtex_texture_binary()
    if binary is None:
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
            fallback_available=True,
            reason="unsafe_dds_input",
        )
        return None
    cache_key = hashlib.sha256(
        (
            f"direct-output|{directxtex_texture_cache_key(source_path, max_dimension=max_dimension, slot_kind=slot_kind, srgb=srgb, normal_space=normal_space, binary=binary)}"
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
            job = {
                "input": str(source_path),
                "output": str(staged),
                "max_dimension": max(1, int(max_dimension or 4096)),
                "slot": str(slot_kind or "base").strip().lower() or "base",
                "srgb": str(srgb or "auto").strip().lower() or "auto",
                "normal_space": str(normal_space or "auto").strip().lower() or "auto",
            }
            job_path.write_text(
                json.dumps({"version": 1, "backend": DIRECTXTEX_TEXTURE_BACKEND_ID, "jobs": [job]}, indent=2),
                encoding="utf-8",
            )
            try:
                returncode, _stdout, stderr = run_process_with_cancellation(
                    [str(binary), "batch-preview-json", str(job_path), str(report_path), *_native_diagnostic_args()],
                    timeout_seconds=max(1.0, float(timeout_seconds)),
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
                    fallback_available=True,
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
                    fallback_available=True,
                    reason="atomic_publication_failed",
                )
                return None
            return item


def encode_dds_with_directxtex(
    png_path: Path,
    output_dds_path: Path,
    *,
    dds_format: str,
    width: int = 0,
    height: int = 0,
    mip_count: int = 1,
    overwrite: bool = True,
    timeout_seconds: float = 60.0,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Dict[str, Any]]:
    results = encode_dds_batch_with_directxtex(
        (
            {
                "png_path": str(png_path),
                "output_path": str(output_dds_path),
                "format": str(dds_format or "BC7_UNORM"),
                "width": int(width or 0),
                "height": int(height or 0),
                "mip_count": int(mip_count or 1),
                "overwrite": bool(overwrite),
            },
        ),
        timeout_seconds=timeout_seconds,
        stop_event=stop_event,
    )
    try:
        output_key = str(Path(output_dds_path).expanduser().resolve())
    except OSError:
        output_key = str(output_dds_path)
    return results.get(output_key)


def encode_dds_batch_with_directxtex(
    jobs: Sequence[Mapping[str, object]],
    *,
    timeout_seconds: float = 120.0,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, Dict[str, Any]]:
    raise_if_cancelled(stop_event, "DirectXTex DDS encode cancelled.")
    binary = find_directxtex_texture_binary()
    if binary is None:
        return {}
    normalized_jobs: list[Dict[str, object]] = []
    for job in jobs:
        raise_if_cancelled(stop_event, "DirectXTex DDS encode cancelled.")
        raw_input = str(job.get("png_path") or job.get("input") or job.get("source_path") or "").strip()
        raw_output = str(job.get("output_path") or job.get("dds_path") or job.get("output") or "").strip()
        if not raw_input or not raw_output:
            continue
        try:
            input_path = Path(raw_input).expanduser().resolve()
            output_path = Path(raw_output).expanduser().resolve()
        except OSError:
            continue
        if not input_path.is_file():
            continue
        normalized_jobs.append(
            {
                "input": str(input_path),
                "output": str(output_path),
                "format": str(job.get("format") or job.get("texconv_format") or "BC7_UNORM"),
                "width": max(0, int(job.get("width") or job.get("target_width") or 0)),
                "height": max(0, int(job.get("height") or job.get("target_height") or 0)),
                "mip_count": max(1, int(job.get("mip_count") or job.get("mips") or 1)),
                "overwrite": bool(job.get("overwrite", True)),
            }
        )
    if not normalized_jobs:
        return {}

    job_root = Path(tempfile.mkdtemp(prefix="cdmw_directxtex_encode_"))
    job_path = job_root / "job.json"
    report_path = job_root / "report.json"
    try:
        try:
            for job in normalized_jobs:
                Path(str(job["output"])).parent.mkdir(parents=True, exist_ok=True)
            job_path.write_text(
                json.dumps({"version": 1, "backend": DIRECTXTEX_TEXTURE_BACKEND_ID, "jobs": normalized_jobs}, indent=2),
                encoding="utf-8",
            )
            returncode, _stdout, _stderr = run_process_with_cancellation(
                [str(binary), "batch-encode-json", str(job_path), str(report_path), *_native_diagnostic_args()],
                timeout_seconds=max(1.0, float(timeout_seconds)),
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
                fallback_available=False,
                reason=type(exc).__name__,
            )
            return {}
        if returncode not in {0, 2} or not report_path.is_file():
            _record_directxtex_failure(
                binary=binary,
                operation="batch-encode-json",
                returncode=returncode,
                stderr=_stderr,
                fallback_available=False,
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
                fallback_available=False,
                reason="invalid_report_json",
            )
            return {}
        items = parsed.get("items") if isinstance(parsed, dict) else None
        if not isinstance(items, list):
            _record_directxtex_failure(
                binary=binary,
                operation="batch-encode-json",
                returncode=returncode,
                stderr="",
                fallback_available=False,
                reason="missing_report_items",
            )
            return {}
        results: Dict[str, Dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict) or str(item.get("status") or "").lower() != "encoded":
                continue
            output = Path(str(item.get("output_path") or ""))
            if not output.is_file():
                continue
            item.setdefault("backend", DIRECTXTEX_TEXTURE_BACKEND_ID)
            item.setdefault("native_backend", "directxtex")
            try:
                output_key = str(output.expanduser().resolve())
            except OSError:
                output_key = str(output)
            results[output_key] = dict(item)
        return results
    finally:
        shutil.rmtree(job_root, ignore_errors=True)


def texconv_preview_report(
    dds_path: Path,
    preview_path: Path,
    *,
    slot_kind: str = "base",
    max_dimension: int = 0,
    backend: str = "texconv_fallback",
) -> Dict[str, Any]:
    metadata_verified = True
    try:
        info = inspect_dds_native_path(dds_path)
        report = dds_native_report_dict(dds_path, info, backend=backend)
    except Exception as exc:
        metadata_verified = False
        report = {
            "backend": backend,
            "status": "decoded_with_unknown_metadata" if Path(preview_path).is_file() else "fallback_unverified",
            "source_path": str(dds_path),
            "format": "",
            "width": 0,
            "height": 0,
            "mip_count": 0,
            "metadata_verified": False,
            "metadata_error": str(exc),
        }
    status = str(report.get("status") or "decoded")
    if not metadata_verified:
        status = str(report.get("status") or "fallback_unverified")
    elif not str(report.get("format") or "").strip() or int(report.get("width") or 0) <= 0 or int(report.get("height") or 0) <= 0:
        status = "decoded_with_unknown_metadata"
    report.update(
        {
            "status": status,
            "source_path": str(dds_path),
            "output_path": str(preview_path),
            "slot": str(slot_kind or "base"),
            "max_dimension": int(max_dimension or 0),
            "native_backend": "texconv",
            "metadata_verified": metadata_verified and status == "decoded",
            "fallback_reason": "DirectXTex/native preview unavailable or unsupported",
        }
    )
    return report
