"""Static replacement post-open task state helpers."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping, MutableSequence


def alignment_post_open_initial_state() -> dict[str, bool]:
    return {"started": False}


def alignment_post_open_started(state: MutableMapping[str, object]) -> bool:
    return bool(state.get("started"))


def alignment_post_open_mark_started(state: MutableMapping[str, object]) -> None:
    state["started"] = True


def queue_alignment_post_open_task(
    state: MutableMapping[str, object],
    tasks: MutableSequence[Callable[[], None]],
    callback: Callable[[], None],
    *,
    schedule: Callable[[int, Callable[[], None]], None],
) -> None:
    if alignment_post_open_started(state):
        schedule(0, callback)
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
    for task_index, callback in enumerate(pending_tasks):
        schedule(int(task_index) * int(spacing_ms), callback)


__all__ = [
    "alignment_post_open_initial_state",
    "alignment_post_open_mark_started",
    "alignment_post_open_started",
    "queue_alignment_post_open_task",
    "run_alignment_post_open_tasks",
]
