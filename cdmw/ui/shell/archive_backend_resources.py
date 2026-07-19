"""Resource discovery for the independent full-CDMW archive worker."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Iterable


ARCHIVE_BACKEND_WORKER_NAME = "cdmw-full-archive-worker.exe"
ARCHIVE_BACKEND_WORKER_ENV = "CDMW_FULL_ARCHIVE_WORKER"


def archive_backend_worker_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []
    configured = str(os.environ.get(ARCHIVE_BACKEND_WORKER_ENV, "") or "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())

    frozen_root_text = str(getattr(sys, "_MEIPASS", "") or "").strip()
    if frozen_root_text:
        frozen_root = Path(frozen_root_text)
        candidates.extend(
            (
                frozen_root / "archive_backend" / ARCHIVE_BACKEND_WORKER_NAME,
                frozen_root / "tools" / "archive_backend" / ARCHIVE_BACKEND_WORKER_NAME,
            )
        )
    if getattr(sys, "frozen", False):
        executable_root = Path(sys.executable).resolve().parent
        candidates.extend(
            (
                executable_root / "archive_backend" / ARCHIVE_BACKEND_WORKER_NAME,
                executable_root / ARCHIVE_BACKEND_WORKER_NAME,
            )
        )

    repository_root = Path(__file__).resolve().parents[3]
    staged_backend = repository_root / "native" / "cdmw_full_archive_backend" / "build"
    for configuration in ("Release", "Debug"):
        candidates.append(staged_backend / configuration / ARCHIVE_BACKEND_WORKER_NAME)

    worker_project = (
        repository_root
        / "tools"
        / "dotnet_archive_backend"
        / "src"
        / "Cdmw.FullArchive.Worker"
        / "bin"
    )
    for configuration in ("Release", "Debug"):
        candidates.append(
            worker_project
            / configuration
            / "net10.0-windows"
            / "win-x64"
            / ARCHIVE_BACKEND_WORKER_NAME
        )
    return _deduplicate(candidates)


def resolve_archive_backend_worker(explicit: Path | str | None = None) -> Path:
    if explicit is not None:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"Full archive worker is missing: {candidate}")
    candidates = archive_backend_worker_candidates()
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    searched = "; ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Full archive worker was not found. Searched: {searched}")


def _deduplicate(paths: Iterable[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).replace("\\", "/").casefold()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)


__all__ = [
    "ARCHIVE_BACKEND_WORKER_ENV",
    "ARCHIVE_BACKEND_WORKER_NAME",
    "archive_backend_worker_candidates",
    "resolve_archive_backend_worker",
]
