"""Long tool work as jobs the client can follow and cancel (P13 stage C, design record 2.4 step 5).

Every worker tool runs as a job on a thread of its own. A call that finishes
within ``QUICK_RESULT_S`` returns its result directly; otherwise the client
gets ``{"job": id}`` at once and follows it with ``app.jobs`` (progress, then
the result) or stops it with ``app.cancel_job``, which sets the same stop
event the work checks. Finished jobs are kept, newest first, up to
``KEEP_FINISHED``.

The job runner applies the one output path rule again before an output job
starts, and :meth:`Job.check_output` is what an output tool calls for each
path it writes, so no tool can skip the rule.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from cdmw.mcp.errors import CANCELLED, FAILED, NOT_FOUND, REFUSED, ToolError

QUICK_RESULT_S = 2.0
KEEP_FINISHED = 50

RUNNING = "running"
DONE = "done"
FAILED_STATE = "failed"
CANCELLED_STATE = "cancelled"


@dataclass
class Job:
    id: str
    tool: str
    client: str
    cancel_event: threading.Event
    game_folder: Callable[[], str] = lambda: ""
    #: The list in the result that is paged (the tool's ``paged``).
    paged: str = ""
    state: str = RUNNING
    done: float = 0.0
    total: float = 0.0
    message: str = ""
    result: object = None
    error: ToolError | None = None
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    _finished: threading.Event = field(default_factory=threading.Event, repr=False)

    def progress(self, done: float, total: float = 0.0, message: str = "") -> None:
        self.done, self.total, self.message = float(done), float(total), str(message or "")

    def check_output(self, path) -> object:
        """The job runner's path rule: call before writing ``path``; returns the resolved path."""

        from cdmw.domain.output_paths import OutputPathRefused, check_output_path

        try:
            return check_output_path(path, game_folder=self.game_folder())
        except OutputPathRefused as refused:
            raise ToolError(REFUSED, str(refused)) from None

    def wait(self, timeout: float | None) -> bool:
        return self._finished.wait(timeout)

    def summary(self) -> dict[str, object]:
        row: dict[str, object] = {"job": self.id, "tool": self.tool, "state": self.state,
                                  "progress": {"done": self.done, "total": self.total, "message": self.message},
                                  "started": self.started}
        if self.finished:
            row["finished"] = self.finished
        if self.error is not None:
            row["error"] = self.error.payload()
        return row


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, call, work: Callable[[], object], *, game_folder: Callable[[], str] | None = None) -> Job:
        job = Job(id="job-" + secrets.token_hex(6), tool=call.tool.name, client=call.client,
                  cancel_event=call.cancel_event, game_folder=game_folder or (lambda: ""))
        call.job = job
        call.on_progress = _chain(call.on_progress, job.progress)
        # The runner checks every output path again before the work starts.
        for name in getattr(call.tool, "output_paths", ()):
            job.check_output(str(call.arguments.get(name) or ""))
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
        threading.Thread(target=self._run, args=(job, work), name=f"cdmw-mcp-{job.id}", daemon=True).start()
        return job

    def _run(self, job: Job, work: Callable[[], object]) -> None:
        try:
            job.result = work()
            job.state = CANCELLED_STATE if job.cancel_event.is_set() else DONE
            if job.state == CANCELLED_STATE:
                job.error = ToolError(CANCELLED, "Cancelled.")
        except ToolError as error:
            job.error = error
            job.state = CANCELLED_STATE if error.code == CANCELLED else FAILED_STATE
        except Exception as exc:
            job.error = ToolError(FAILED, str(exc) or type(exc).__name__)
            job.state = FAILED_STATE
        finally:
            job.finished = time.time()
            job._finished.set()

    def _trim(self) -> None:
        finished = sorted((j for j in self._jobs.values() if j.state != RUNNING), key=lambda j: j.finished)
        for job in finished[:max(0, len(finished) - KEEP_FINISHED)]:
            self._jobs.pop(job.id, None)

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(str(job_id))
        if job is None:
            raise ToolError(NOT_FOUND, f"There is no job {job_id}.")
        return job

    def jobs(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.started, reverse=True)

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        job.cancel_event.set()
        return job


def _chain(first, second):
    if first is None:
        return second

    def both(done, total, message):
        first(done, total, message)
        second(done, total, message)

    return both
