"""A refused utility task has to say so in the log the user actually reads.

`_run_utility_task` reported its concurrency refusal through `set_status_message`
alone. The status field holds one transient line, so when the Modify Original
draft check chained into workspace preparation and the second stage was refused
as a concurrent task, the archive log ended at "Checking Modify Original drafts
for <asset>..." with no error line at all. The run looked like it had simply
stopped mid-step.

These drive the real `UtilityControllerMixin` against the real
`LogControllerMixin._background_task_active`, with only the log and status sinks
reduced to recorders. The non-refused path, where the runner starts a real
`QThread`, is covered by `tests/test_modify_original_draft_chain_async.py`.
"""

from __future__ import annotations

from cdmw.ui.shell import utility_controller as utility_controller_module
from cdmw.ui.shell.log_controller import LogControllerMixin
from cdmw.ui.shell.utility_controller import UtilityControllerMixin


DRAFT_CHAIN_STATUS = "Preparing Modify Original workspace..."


class _NeverFiringTimer:
    """`QTimer.singleShot` without an event loop: record the delay, never fire."""

    def __init__(self) -> None:
        self.scheduled: list[int] = []

    def singleShot(self, interval: int, _callback: object) -> None:  # noqa: N802 - Qt spelling
        self.scheduled.append(int(interval))


class _RefusalOwner(UtilityControllerMixin, LogControllerMixin):
    """Smallest host that reaches the real refusal branch."""

    def __init__(self) -> None:
        self.worker_thread = None
        self.archive_basic_index_thread = None
        self.text_search_tab = None
        self._utility_updates_archive_progress = False
        self.log_messages: list[str] = []
        self.archive_log_messages: list[str] = []
        self.status_messages: list[tuple[str, bool]] = []

    def append_log(self, message: str) -> None:
        self.log_messages.append(str(message))

    def append_archive_log(self, message: str, *, verbose: bool = False) -> None:
        self.archive_log_messages.append(str(message))

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.status_messages.append((str(message), bool(error)))


def test_refused_task_names_the_dropped_action_in_the_live_log() -> None:
    owner = _RefusalOwner()
    owner.worker_thread = object()
    started: list[str] = []

    owner._run_utility_task(
        status_message=DRAFT_CHAIN_STATUS,
        task=lambda: started.append("ran"),
    )

    assert not started
    assert len(owner.log_messages) == 1, owner.log_messages
    line = owner.log_messages[0]
    assert line.startswith("ERROR: "), line
    assert DRAFT_CHAIN_STATUS in line, line
    assert owner.archive_log_messages == []
    assert any(error for _message, error in owner.status_messages)


def test_refused_task_with_archive_progress_also_reaches_the_archive_log() -> None:
    owner = _RefusalOwner()
    owner.worker_thread = object()

    owner._run_utility_task(
        status_message=DRAFT_CHAIN_STATUS,
        task=lambda: None,
        show_archive_progress=True,
    )

    assert owner.archive_log_messages == owner.log_messages
    assert DRAFT_CHAIN_STATUS in owner.archive_log_messages[0]
    # The refusal returns before `_utility_updates_archive_progress` is assigned,
    # so the archive decision has to come from the argument, and the flag must
    # keep whatever the still-running task set.
    assert owner._utility_updates_archive_progress is False


def test_refusal_that_no_worker_thread_caused_still_reaches_the_log() -> None:
    owner = _RefusalOwner()
    owner.archive_basic_index_thread = object()

    owner._run_utility_task(
        status_message="Extracting selected archive entries...",
        task=lambda: None,
        show_archive_progress=True,
    )

    assert len(owner.log_messages) == 1, owner.log_messages
    assert "Extracting selected archive entries..." in owner.log_messages[0]
    assert owner.archive_log_messages == owner.log_messages


def test_refusal_line_is_distinguishable_from_the_deferred_wait_line(monkeypatch) -> None:
    monkeypatch.setattr(utility_controller_module, "QTimer", _NeverFiringTimer())
    owner = _RefusalOwner()
    owner.worker_thread = object()

    owner._run_utility_task(
        status_message=DRAFT_CHAIN_STATUS,
        task=lambda: None,
        show_archive_progress=True,
    )
    refused = list(owner.log_messages)
    owner.log_messages.clear()
    owner.archive_log_messages.clear()

    owner._run_utility_task_when_idle(
        status_message=DRAFT_CHAIN_STATUS,
        task=lambda: None,
        show_archive_progress=True,
    )
    deferred = list(owner.log_messages)

    assert refused and deferred
    # A dropped step and a queued step read the same to a user unless the lines
    # differ, and only the dropped one is an error.
    assert set(refused).isdisjoint(deferred)
    assert all(not line.startswith("ERROR: ") for line in deferred), deferred
