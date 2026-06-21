"""Texture workflow UI state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class TextureWorkflowState:
    workspace_root: Path | None = None
    active_profile_key: str = ""


__all__ = ["TextureWorkflowState"]
