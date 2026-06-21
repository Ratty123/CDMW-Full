from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class ShutdownAwareTab(Protocol):
    def request_shutdown(self) -> None:
        ...

    def iter_shutdown_workers(self) -> Iterable[object]:
        ...


class CancellableWorker(Protocol):
    def request_stop(self) -> None:
        ...

    def is_running(self) -> bool:
        ...
