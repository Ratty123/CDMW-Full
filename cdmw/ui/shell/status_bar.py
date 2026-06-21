"""Shell status-bar ownership boundary."""

from __future__ import annotations


class StatusBarController:
    """Coordinates status messages and progress surfaces."""

    def __init__(self, context: object | None = None) -> None:
        self.context = context


__all__ = ["StatusBarController"]
