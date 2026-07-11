"""Atomic file protocol shared by startup splash parent, shell, and host."""

from __future__ import annotations

import json
import time
from pathlib import Path


STARTUP_SPLASH_COMMAND_FILE_ENV = "CDMW_STARTUP_SPLASH_COMMAND_FILE"


def startup_splash_artifact_paths(command_file: Path) -> tuple[Path, Path, Path]:
    command_path = Path(command_file)
    return (
        command_path,
        command_path.with_suffix(".ready"),
        command_path.with_suffix(command_path.suffix + ".tmp"),
    )


def cleanup_startup_splash_artifacts(command_file: Path) -> None:
    for artifact in startup_splash_artifact_paths(command_file):
        try:
            artifact.unlink(missing_ok=True)
        except OSError:
            pass


def write_startup_splash_payload(
    path: Path,
    *,
    detail: str,
    current: int = 0,
    total: int = 0,
    closed: bool = False,
    theme_key: str,
) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        payload = {
            "detail": str(detail or "Starting application..."),
            "current": max(0, int(current or 0)),
            "total": max(0, int(total or 0)),
            "closed": bool(closed),
            "theme_key": str(theme_key),
            "updated_at": time.time(),
        }
        temp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temp_path.replace(path)
    except Exception:
        pass
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "STARTUP_SPLASH_COMMAND_FILE_ENV",
    "cleanup_startup_splash_artifacts",
    "startup_splash_artifact_paths",
    "write_startup_splash_payload",
]
