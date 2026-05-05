from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from cdmw.core.common import hidden_subprocess_kwargs, run_process_with_cancellation


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_cd_hkx_binary_path() -> Path:
    exe_name = "cd-hkx.exe" if os.name == "nt" else "cd-hkx"
    return _repo_root() / "native" / "cd_hkx" / "target" / "release" / exe_name


def find_cd_hkx_binary() -> Optional[Path]:
    env_path = os.environ.get("CDMW_CD_HKX_BIN", "").strip()
    candidates = [Path(env_path)] if env_path else []
    candidates.append(default_cd_hkx_binary_path())
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def parse_hkx_summary_with_rust(data: bytes, *, timeout_seconds: float = 5.0) -> Optional[Dict[str, Any]]:
    binary = find_cd_hkx_binary()
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [str(binary), "summary-json", "-"],
            input=data,
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


def patch_hkx_fixed_float_with_rust(
    data: bytes,
    *,
    record_index: int,
    item_index: int,
    offset: int,
    value: float,
    timeout_seconds: float = 5.0,
) -> Optional[bytes]:
    binary = find_cd_hkx_binary()
    if binary is None:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_cd_hkx_patch_") as temp_dir:
            input_path = Path(temp_dir) / "input.hkx"
            output_path = Path(temp_dir) / "output.hkx"
            input_path.write_bytes(data)
            completed = subprocess.run(
                [
                    str(binary),
                    "patch-fixed-f32",
                    str(input_path),
                    str(output_path),
                    str(int(record_index)),
                    str(int(item_index)),
                    f"0x{int(offset):X}",
                    repr(float(value)),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=max(0.5, float(timeout_seconds)),
                check=False,
                **hidden_subprocess_kwargs(),
            )
            if completed.returncode != 0 or not output_path.is_file():
                return None
            patched = output_path.read_bytes()
    except (OSError, subprocess.SubprocessError, ValueError, OverflowError):
        return None
    return patched if len(patched) == len(data) else None


def roundtrip_hkx_noedit_with_rust(
    data: bytes,
    *,
    timeout_seconds: float = 5.0,
) -> Optional[Dict[str, Any]]:
    binary = find_cd_hkx_binary()
    if binary is None:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_cd_hkx_noedit_") as temp_dir:
            input_path = Path(temp_dir) / "input.hkx"
            output_path = Path(temp_dir) / "output.hkx"
            input_path.write_bytes(data)
            completed = subprocess.run(
                [str(binary), "roundtrip-noedit", str(input_path), str(output_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=max(0.5, float(timeout_seconds)),
                check=False,
                **hidden_subprocess_kwargs(),
            )
            if completed.returncode != 0 or not completed.stdout or not output_path.is_file():
                return None
            rebuilt = output_path.read_bytes()
    except (OSError, subprocess.SubprocessError, ValueError, OverflowError):
        return None
    if rebuilt != data:
        return None
    try:
        parsed = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    parsed.setdefault("native_backend", "native_rust_cd_hkx")
    parsed.setdefault("command", "roundtrip-noedit")
    return {"data": rebuilt, "report": parsed}


def scan_hkx_corpus_with_rust(
    paths: Sequence[Path | str],
    *,
    mode: str = "corpus-stats-json",
    max_files: Optional[int] = None,
    timeout_seconds: float = 30.0,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Dict[str, Any]]:
    binary = find_cd_hkx_binary()
    if binary is None or mode not in {"corpus-json", "corpus-stats-json", "verify-noedit"}:
        return None
    normalized_paths = [Path(path) for path in paths if str(path)]
    if len(normalized_paths) != 1:
        return None
    args = [str(binary), mode, str(normalized_paths[0])]
    if max_files is not None:
        try:
            args.append(str(max(0, int(max_files))))
        except (TypeError, ValueError, OverflowError):
            return None
    try:
        if stop_event is not None:
            _return_code, stdout_text, _stderr_text = run_process_with_cancellation(args, stop_event=stop_event)
            if _return_code != 0 or not stdout_text:
                return None
            stdout = stdout_text.encode("utf-8", errors="replace")
        else:
            completed = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=max(1.0, float(timeout_seconds)),
                check=False,
                **hidden_subprocess_kwargs(),
            )
            if completed.returncode != 0 or not completed.stdout:
                return None
            stdout = completed.stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    try:
        parsed = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    parsed.setdefault("native_backend", "native_rust_cd_hkx")
    parsed.setdefault("command", mode)
    return parsed
