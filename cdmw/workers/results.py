from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class WorkerSuccess(Generic[T]):
    value: T
    elapsed_ms: float


@dataclass(slots=True)
class WorkerFailure:
    message: str
    exception_type: str
    traceback_text: str
    recoverable: bool = True
