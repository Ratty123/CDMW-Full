from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from cdmw.constants import APP_NAME
from cdmw.core.common import hidden_subprocess_kwargs

NATIVE_TEXTURE_BACKEND_ID = "cd_texture_rust_0.1"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_cd_texture_binary_path(*, release: bool = True) -> Path:
    exe_name = "cd-texture.exe" if os.name == "nt" else "cd-texture"
    profile = "release" if release else "debug"
    return _repo_root() / "native" / "cd_texture" / "target" / profile / exe_name


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


def native_texture_available() -> bool:
    return find_cd_texture_binary() is not None


def native_texture_report_sidecar_path(preview_path: Path) -> Path:
    return preview_path.with_name(f"{preview_path.name}.cdmw_texture.json")


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


def ensure_native_dds_preview_png(
    dds_path: Path,
    *,
    max_dimension: int,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    timeout_seconds: float = 20.0,
) -> Optional[Path]:
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
