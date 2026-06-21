"""Shell toolbar ownership boundary."""

from __future__ import annotations


class ToolbarController:
    """Coordinates top-level toolbar actions."""

    def __init__(self, context: object | None = None) -> None:
        self.context = context


__all__ = ["ToolbarController"]
