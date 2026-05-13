from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from cdmw.constants import APP_NAME
from cdmw.core.common import hidden_subprocess_kwargs
from cdmw.core.dds_native import dds_native_report_dict, inspect_dds_native_path

NATIVE_TEXTURE_BACKEND_ID = "cd_texture_rust_0.1"
DIRECTXTEX_TEXTURE_BACKEND_ID = "directxtex_native_0.1"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_cd_texture_binary_path(*, release: bool = True) -> Path:
    exe_name = "cd-texture.exe" if os.name == "nt" else "cd-texture"
    profile = "release" if release else "debug"
    return _repo_root() / "native" / "cd_texture" / "target" / profile / exe_name


def default_directxtex_texture_binary_path(*, release: bool = True) -> Path:
    exe_name = "cd-texture-dx.exe" if os.name == "nt" else "cd-texture-dx"
    config = "Release" if release else "Debug"
    return _repo_root() / "native" / "cd_texture_dx" / "build" / config / exe_name


def find_cd_texture_binary() -> Optional[Path]:
    env_path = os.environ.get("CDMW_CD_TEXTURE_BIN", "").strip()
    candidates = [Path(env_path)] if env_path else []
    candidates.extend(
        [
            default_cd_texture_binary_path(release=True),
            default_cd_texture_binary_path(release=False),
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


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
    return find_directxtex_texture_binary() is not None or find_cd_texture_binary() is not None


def native_texture_report_sidecar_path(preview_path: Path) -> Path:
    return preview_path.with_name(f"{preview_path.name}.cdmw_texture.json")


def write_native_texture_report_sidecar(preview_path: Path, report: Mapping[str, Any]) -> bool:
    try:
        report_path = native_texture_report_sidecar_path(preview_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(dict(report), indent=2, sort_keys=True), encoding="utf-8")
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


def native_texture_cache_key(
    dds_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    fallback_mode: str = "texconv",
    binary: Optional[Path] = None,
) -> str:
    resolved_binary = binary or find_cd_texture_binary()
    identity = (
        f"{NATIVE_TEXTURE_BACKEND_ID}|{_source_identity(dds_path)}|"
        f"max={int(max_dimension)}|slot={str(slot_kind or 'base').strip().lower()}|"
        f"srgb={str(srgb or 'auto').strip().lower()}|"
        f"normal={str(normal_space or 'auto').strip().lower()}|fallback={fallback_mode}|"
        f"bin={_binary_identity(resolved_binary) if resolved_binary is not None else 'none'}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


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


def inspect_dds_with_rust(
    dds_path: Path,
    *,
    timeout_seconds: float = 5.0,
) -> Optional[Dict[str, Any]]:
    binary = find_cd_texture_binary()
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [str(binary), "inspect-json", str(dds_path)],
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
            [str(binary), "inspect-json", str(dds_path)],
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
    cache_dir = Path(tempfile.gettempdir()) / APP_NAME / "directxtex_texture_preview" / cache_key
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
    try:
        return preview_path.is_file() and preview_path.stat().st_size > 0 and native_texture_report_sidecar_path(preview_path).is_file()
    except OSError:
        return False


def ensure_directxtex_dds_preview_png(
    dds_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    timeout_seconds: float = 20.0,
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
    )
    return results.get(str(Path(dds_path).expanduser().resolve()))


def ensure_directxtex_dds_preview_pngs(
    jobs: Sequence[Mapping[str, object]],
    *,
    timeout_seconds: float = 45.0,
    include_job_keys: bool = False,
) -> Dict[str, Path]:
    binary = find_directxtex_texture_binary()
    if binary is None:
        return {}
    normalized_jobs: list[Dict[str, object]] = []
    results: Dict[str, Path] = {}
    for job in jobs:
        raw_path = str(job.get("dds_path") or job.get("input") or "").strip()
        if not raw_path:
            continue
        try:
            dds_path = Path(raw_path).expanduser().resolve()
        except OSError:
            continue
        if not dds_path.is_file():
            continue
        max_dimension = max(1, int(job.get("max_dimension") or job.get("max_dim") or 4096))
        slot_kind = str(job.get("slot_kind") or job.get("slot") or "base").strip().lower() or "base"
        srgb = str(job.get("srgb") or "auto").strip().lower() or "auto"
        normal_space = str(job.get("normal_space") or "auto").strip().lower() or "auto"
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
        if _cached_preview_is_valid(preview_path):
            results[key] = preview_path
            if include_job_keys:
                results[job_key] = preview_path
            continue
        normalized_jobs.append(
            {
                "input": key,
                "output": str(preview_path),
                "max_dimension": max_dimension,
                "slot": slot_kind,
                "srgb": srgb,
                "normal_space": normal_space,
                "result_key": job_key,
            }
        )
    if not normalized_jobs:
        return results

    job_keys_by_output = {
        str(job.get("output", "")): str(job.get("result_key", ""))
        for job in normalized_jobs
        if str(job.get("output", "")) and str(job.get("result_key", ""))
    }
    job_root = Path(tempfile.mkdtemp(prefix="cdmw_directxtex_batch_"))
    job_path = job_root / "job.json"
    report_path = job_root / "report.json"
    try:
        for job in normalized_jobs:
            Path(str(job["output"])).parent.mkdir(parents=True, exist_ok=True)
        job_path.write_text(
            json.dumps({"version": 1, "backend": DIRECTXTEX_TEXTURE_BACKEND_ID, "jobs": normalized_jobs}, indent=2),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [str(binary), "batch-preview-json", str(job_path), str(report_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(1.0, float(timeout_seconds)),
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError, ValueError, OverflowError):
        return results
    if completed.returncode != 0 or not report_path.is_file():
        return results
    try:
        parsed = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return results
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return results
    for item in items:
        if not isinstance(item, dict) or str(item.get("status") or "").lower() != "decoded":
            continue
        output_path = Path(str(item.get("output_path") or item.get("output") or ""))
        source_path = Path(str(item.get("source_path") or item.get("input") or ""))
        if not output_path.is_file() or not source_path:
            continue
        item.setdefault("backend", DIRECTXTEX_TEXTURE_BACKEND_ID)
        item.setdefault("native_backend", "directxtex")
        if write_native_texture_report_sidecar(output_path, item):
            try:
                source_key = str(source_path.expanduser().resolve())
            except OSError:
                source_key = str(source_path)
            results[source_key] = output_path
            if include_job_keys:
                result_key = str(item.get("result_key") or "").strip()
                if not result_key:
                    result_key = job_keys_by_output.get(str(output_path), "")
                if not result_key:
                    result_key = directxtex_preview_result_key(
                        source_path,
                        max_dimension=int(item.get("max_dimension") or item.get("max_dim") or 4096),
                        slot_kind=str(item.get("slot") or item.get("slot_kind") or "base"),
                        srgb=str(item.get("srgb") or "auto"),
                        normal_space=str(item.get("normal_space") or "auto"),
                    )
                results[result_key] = output_path
    return results


def ensure_native_dds_preview_png(
    dds_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    timeout_seconds: float = 20.0,
) -> Optional[Path]:
    directxtex_preview = ensure_directxtex_dds_preview_png(
        dds_path,
        max_dimension=max_dimension,
        slot_kind=slot_kind,
        srgb=srgb,
        normal_space=normal_space,
        timeout_seconds=timeout_seconds,
    )
    if directxtex_preview is not None:
        return directxtex_preview

    binary = find_cd_texture_binary()
    if binary is None:
        return None
    cache_key = native_texture_cache_key(
        dds_path,
        max_dimension=max_dimension,
        slot_kind=slot_kind,
        srgb=srgb,
        normal_space=normal_space,
        binary=binary,
    )
    cache_dir = Path(tempfile.gettempdir()) / APP_NAME / "native_texture_preview" / cache_key
    preview_path = cache_dir / f"{dds_path.stem}.png"
    report_path = native_texture_report_sidecar_path(preview_path)
    try:
        if preview_path.is_file() and preview_path.stat().st_size > 0 and report_path.is_file():
            return preview_path
    except OSError:
        pass
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                str(binary),
                "preview-png",
                str(dds_path),
                str(preview_path),
                "--max-dim",
                str(max(1, int(max_dimension))),
                "--slot",
                str(slot_kind or "base"),
                "--srgb",
                str(srgb or "auto"),
                "--normal-space",
                str(normal_space or "auto"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(1.0, float(timeout_seconds)),
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError, ValueError, OverflowError):
        return None
    if completed.returncode != 0 or not preview_path.is_file():
        return None
    try:
        parsed = json.loads(completed.stdout.decode("utf-8")) if completed.stdout else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = {}
    if not isinstance(parsed, dict) or parsed.get("status") != "decoded":
        return None
    parsed.setdefault("backend", NATIVE_TEXTURE_BACKEND_ID)
    parsed.setdefault("native_backend", "rust")
    try:
        report_path.write_text(json.dumps(parsed, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        return None
    return preview_path if preview_path.is_file() and preview_path.stat().st_size > 0 else None


def texconv_preview_report(
    dds_path: Path,
    preview_path: Path,
    *,
    slot_kind: str = "base",
    max_dimension: int = 0,
    backend: str = "texconv_fallback",
) -> Dict[str, Any]:
    try:
        info = inspect_dds_native_path(dds_path)
        report = dds_native_report_dict(dds_path, info, backend=backend)
    except Exception:
        report = {
            "backend": backend,
            "status": "decoded",
            "source_path": str(dds_path),
            "format": "",
            "width": 0,
            "height": 0,
            "mip_count": 0,
        }
    report.update(
        {
            "status": "decoded",
            "source_path": str(dds_path),
            "output_path": str(preview_path),
            "slot": str(slot_kind or "base"),
            "max_dimension": int(max_dimension or 0),
            "native_backend": "texconv",
            "fallback_reason": "DirectXTex/native preview unavailable or unsupported",
        }
    )
    return report
