from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Optional


NATIVE_D3D11_HOST_BINARY_NAME = "cdmw-d3d11-preview.exe" if os.name == "nt" else "cdmw-d3d11-preview"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_native_d3d11_host_path(*, release: bool = True) -> Path:
    config = "Release" if release else "Debug"
    return _repo_root() / "native" / "cdmw_d3d11_preview" / "build" / config / NATIVE_D3D11_HOST_BINARY_NAME


def find_native_d3d11_host() -> Optional[Path]:
    env_path = os.environ.get("CDMW_D3D11_PREVIEW_BIN", "").strip()
    candidates = [Path(env_path)] if env_path else []
    frozen_root = Path(str(getattr(sys, "_MEIPASS", ""))) if getattr(sys, "_MEIPASS", "") else None
    exe_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    if frozen_root is not None:
        candidates.append(frozen_root / "native" / NATIVE_D3D11_HOST_BINARY_NAME)
    if exe_root is not None:
        candidates.append(exe_root / "native" / NATIVE_D3D11_HOST_BINARY_NAME)
    candidates.extend(
        [
            default_native_d3d11_host_path(release=True),
            default_native_d3d11_host_path(release=False),
            _repo_root() / "native" / "cdmw_d3d11_preview" / "bin" / NATIVE_D3D11_HOST_BINARY_NAME,
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


__all__ = [
    "NATIVE_D3D11_HOST_BINARY_NAME",
    "default_native_d3d11_host_path",
    "find_native_d3d11_host",
]
