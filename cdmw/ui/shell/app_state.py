from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppState:
    current_theme_key: str = "graphite"
    active_archive_path: Path | None = None
    startup_phase: str = "starting"
    shutdown_requested: bool = False
