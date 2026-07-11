from __future__ import annotations

import threading
from dataclasses import dataclass, field

from cdmw.domain.cancellation import raise_if_cancelled


@dataclass(slots=True)
class CancellationToken:
    _event: threading.Event = field(default_factory=threading.Event)

    def request_stop(self) -> None:
        self._event.set()

    def is_stop_requested(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        raise_if_cancelled(self._event, "Operation cancelled")
