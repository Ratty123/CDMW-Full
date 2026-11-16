"""Dependency-light native mesh-core binary discovery."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import sys

from cdmw.modding.mesh_native_core_constants import NATIVE_MESH_CORE_BINARY_NAME


# Both roots are fixed for the life of the process. Resolving them on every
# lookup cost a realpath each, four or five per call, and the UI thread asks
# whenever a Mesh Editor tab is built or a selection is pruned (152 ms in
# one Open in Mesh Editor in the review). The file checks still run each time.
@lru_cache(maxsize=1)
def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=4)
def _executable_root(executable: str) -> Path:
    return Path(executable).resolve().parent


def default_native_mesh_core_path(*, release: bool = True) -> Path:
    config = "Release" if release else "Debug"
    return _repo_root() / "native" / "cdmw_mesh_core" / "build" / config / NATIVE_MESH_CORE_BINARY_NAME


def find_native_mesh_core_binary() -> Path | None:
    env_path = os.environ.get("CDMW_MESH_CORE_BIN", "").strip()
    candidates = [Path(env_path)] if env_path else []
    frozen_root = Path(str(getattr(sys, "_MEIPASS", ""))) if getattr(sys, "_MEIPASS", "") else None
    exe_root = _executable_root(sys.executable) if getattr(sys, "frozen", False) else None
    if frozen_root is not None:
        candidates.append(frozen_root / "native" / NATIVE_MESH_CORE_BINARY_NAME)
    if exe_root is not None:
        candidates.append(exe_root / "native" / NATIVE_MESH_CORE_BINARY_NAME)
    candidates.extend(
        (
            default_native_mesh_core_path(release=True),
            default_native_mesh_core_path(release=False),
            _repo_root() / "native" / "cdmw_mesh_core" / "bin" / NATIVE_MESH_CORE_BINARY_NAME,
        )
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def native_mesh_core_available() -> bool:
    return find_native_mesh_core_binary() is not None


__all__ = ["default_native_mesh_core_path", "find_native_mesh_core_binary", "native_mesh_core_available"]
