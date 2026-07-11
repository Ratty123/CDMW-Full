"""Dependency-free cooperative cancellation policy."""

from __future__ import annotations

import threading


class RunCancelled(RuntimeError):
    """Raised when an owned operation observes cooperative cancellation."""


def raise_if_cancelled(
    stop_event: threading.Event | None,
    message: str = "Processing stopped by user.",
) -> None:
    if stop_event and stop_event.is_set():
        raise RunCancelled(message)


__all__ = ["RunCancelled", "raise_if_cancelled"]
