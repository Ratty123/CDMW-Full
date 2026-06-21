from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AppEvent:
    name: str
    payload: dict[str, Any]


class AppEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[AppEvent], None]]] = defaultdict(list)

    def subscribe(self, name: str, callback: Callable[[AppEvent], None]) -> None:
        self._subscribers[str(name)].append(callback)

    def publish(self, name: str, **payload: Any) -> AppEvent:
        event = AppEvent(name=str(name), payload=dict(payload))
        for callback in tuple(self._subscribers.get(event.name, ())):
            callback(event)
        return event
