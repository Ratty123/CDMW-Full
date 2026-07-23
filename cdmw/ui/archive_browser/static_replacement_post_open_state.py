"""Static replacement post-open task state helpers."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping, MutableSequence


def alignment_post_open_initial_state() -> dict[str, bool]:
    return {"started": False, "cancelled": False}


def alignment_post_open_started(state: MutableMapping[str, object]) -> bool:
    return bool(state.get("started"))


def alignment_post_open_mark_started(state: MutableMapping[str, object]) -> None:
    state["started"] = True


def alignment_post_open_cancelled(state: MutableMapping[str, object]) -> bool:
    return bool(state.get("cancelled"))


def cancel_alignment_post_open_tasks(
    state: MutableMapping[str, object],
    tasks: MutableSequence[Callable[[], None]],
) -> None:
    state["cancelled"] = True
    tasks.clear()


def _run_alignment_post_open_task(
    state: MutableMapping[str, object],
    callback: Callable[[], None],
) -> None:
    if not alignment_post_open_cancelled(state):
        callback()


def queue_alignment_post_open_task(
    state: MutableMapping[str, object],
    tasks: MutableSequence[Callable[[], None]],
    callback: Callable[[], None],
    *,
    schedule: Callable[[int, Callable[[], None]], None],
) -> None:
    if alignment_post_open_cancelled(state):
        return
    if alignment_post_open_started(state):
        schedule(0, lambda: _run_alignment_post_open_task(state, callback))
        return
    tasks.append(callback)


def run_alignment_post_open_tasks(
    state: MutableMapping[str, object],
    tasks: MutableSequence[Callable[[], None]],
    *,
    schedule: Callable[[int, Callable[[], None]], None],
    spacing_ms: int = 45,
) -> None:
    alignment_post_open_mark_started(state)
    pending_tasks = list(tasks)
    tasks.clear()
    if alignment_post_open_cancelled(state):
        return
    for task_index, callback in enumerate(pending_tasks):
        schedule(
            int(task_index) * int(spacing_ms),
            lambda callback=callback: _run_alignment_post_open_task(state, callback),
        )


__all__ = [
    "alignment_post_open_initial_state",
    "alignment_post_open_cancelled",
    "alignment_post_open_mark_started",
    "alignment_post_open_started",
    "cancel_alignment_post_open_tasks",
    "queue_alignment_post_open_task",
    "run_alignment_post_open_tasks",
]
