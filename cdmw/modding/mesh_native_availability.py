"""Dependency-light native mesh-core binary discovery."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
import sys

from cdmw.modding.mesh_native_core_constants import NATIVE_MESH_CORE_BINARY_NAME


@lru_cache(maxsize=1)
def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_native_mesh_core_path(*, release: bool = True) -> Path:
    config = "Release" if release else "Debug"
    return _repo_root() / "native" / "cdmw_mesh_core" / "build" / config / NATIVE_MESH_CORE_BINARY_NAME


@lru_cache(maxsize=8)
def _candidate_paths(env_path: str, frozen_root_text: str, frozen: bool, executable: str) -> tuple[Path, ...]:
    """Where the binary may be, in order. Resolving these paths is several system calls
    each; the Mesh Editor's panel state asks on the UI thread, and every system call
    there waits for the GIL again behind a busy worker, so the list is worked out once."""

    candidates = [Path(env_path)] if env_path else []
    if frozen_root_text:
        candidates.append(Path(frozen_root_text) / "native" / NATIVE_MESH_CORE_BINARY_NAME)
    if frozen:
        candidates.append(Path(executable).resolve().parent / "native" / NATIVE_MESH_CORE_BINARY_NAME)
    candidates.extend(
        (
            default_native_mesh_core_path(release=True),
            default_native_mesh_core_path(release=False),
            _repo_root() / "native" / "cdmw_mesh_core" / "bin" / NATIVE_MESH_CORE_BINARY_NAME,
        )
    )
    return tuple(candidates)


def find_native_mesh_core_binary() -> Path | None:
    # Only the existence checks run each time, and they stop at the first binary found,
    # so a binary built or removed while CDMW runs is still noticed.
    candidates = _candidate_paths(
        os.environ.get("CDMW_MESH_CORE_BIN", "").strip(),
        str(getattr(sys, "_MEIPASS", "") or ""),
        bool(getattr(sys, "frozen", False)),
        str(sys.executable),
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def native_mesh_core_available() -> bool:
    return find_native_mesh_core_binary() is not None


__all__ = ["default_native_mesh_core_path", "find_native_mesh_core_binary", "native_mesh_core_available"]
