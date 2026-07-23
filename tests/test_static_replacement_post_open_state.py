from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_post_open_state import (
    alignment_post_open_cancelled,
    alignment_post_open_initial_state,
    alignment_post_open_mark_started,
    alignment_post_open_started,
    cancel_alignment_post_open_tasks,
    queue_alignment_post_open_task,
    run_alignment_post_open_tasks,
)


def test_alignment_post_open_initial_state_is_not_started() -> None:
    state = alignment_post_open_initial_state()

    assert state == {"started": False, "cancelled": False}
    assert alignment_post_open_started(state) is False
    assert alignment_post_open_cancelled(state) is False


def test_alignment_post_open_mark_started_sets_flag() -> None:
    state = alignment_post_open_initial_state()

    alignment_post_open_mark_started(state)

    assert state == {"started": True, "cancelled": False}
    assert alignment_post_open_started(state) is True


def test_queue_alignment_post_open_task_defers_until_started() -> None:
    state = alignment_post_open_initial_state()
    tasks = []
    scheduled = []
    callback = lambda: None

    queue_alignment_post_open_task(state, tasks, callback, schedule=lambda delay, cb: scheduled.append((delay, cb)))

    assert tasks == [callback]
    assert scheduled == []

    alignment_post_open_mark_started(state)
    queue_alignment_post_open_task(state, tasks, callback, schedule=lambda delay, cb: scheduled.append((delay, cb)))

    assert tasks == [callback]
    assert len(scheduled) == 1
    assert scheduled[0][0] == 0
    scheduled[0][1]()


def test_run_alignment_post_open_tasks_marks_started_clears_queue_and_staggers_tasks() -> None:
    state = alignment_post_open_initial_state()
    callbacks = [lambda: None, lambda: None, lambda: None]
    tasks = list(callbacks)
    scheduled = []

    run_alignment_post_open_tasks(state, tasks, schedule=lambda delay, cb: scheduled.append((delay, cb)))

    assert state == {"started": True, "cancelled": False}
    assert tasks == []
    assert [delay for delay, _callback in scheduled] == [0, 45, 90]
    for _delay, callback in scheduled:
        callback()


def test_cancel_alignment_post_open_tasks_drops_queued_and_scheduled_callbacks() -> None:
    state = alignment_post_open_initial_state()
    calls: list[str] = []
    tasks = [lambda: calls.append("queued")]
    scheduled = []

    run_alignment_post_open_tasks(
        state,
        tasks,
        schedule=lambda delay, callback: scheduled.append((delay, callback)),
    )
    cancel_alignment_post_open_tasks(state, tasks)
    queue_alignment_post_open_task(
        state,
        tasks,
        lambda: calls.append("late"),
        schedule=lambda delay, callback: scheduled.append((delay, callback)),
    )
    for _delay, callback in scheduled:
        callback()

    assert alignment_post_open_cancelled(state) is True
    assert tasks == []
    assert calls == []
