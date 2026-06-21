from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TextureWorkflowService:
    settings: object | None = None
