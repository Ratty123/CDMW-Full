from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from typing import TypeVar

from cdmw.workers.results import WorkerFailure, WorkerSuccess

T = TypeVar("T")


def run_worker_task(task: Callable[[], T]) -> WorkerSuccess[T] | WorkerFailure:
    started = time.perf_counter()
    try:
        value = task()
    except Exception as exc:
        return WorkerFailure(
            message=str(exc),
            exception_type=type(exc).__name__,
            traceback_text=traceback.format_exc(),
        )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return WorkerSuccess(value=value, elapsed_ms=elapsed_ms)
