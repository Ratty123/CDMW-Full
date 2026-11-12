"""The ``app.`` family's tools built in this part: jobs (P13 stage C, design record 2.4 step 5)."""

from __future__ import annotations

from cdmw.mcp.jobs import DONE
from cdmw.mcp.names import READ
from cdmw.mcp.tools import ON_CALL, PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX, Tool, object_schema

_JOB = {"type": "string", "minLength": 1, "maxLength": 64, "description": "The job id a tool returned."}


def _jobs(call) -> dict[str, object]:
    return {"jobs": [job.summary() for job in call.server.jobs.jobs()]}


def _job(call) -> dict[str, object]:
    job = call.server.jobs.get(call.arguments["job"])
    row = job.summary()
    if job.state == DONE:
        limit = int(call.arguments.get("limit") or PAGE_LIMIT_DEFAULT)
        row["result"] = (call.server.pages.first(job.tool, job.paged, job.result, limit) if job.paged
                         else job.result)
    return row


def _cancel(call) -> dict[str, object]:
    job = call.server.jobs.cancel(call.arguments["job"])
    return {"job": job.id, "state": job.state, "cancel_requested": True}


def app_tools() -> list[Tool]:
    return [
        Tool(name="app.jobs", family="app", title="Jobs",
             description="Lists the work AI tools started that took longer than a quick answer: each job's tool, "
                         "state (running, done, failed, cancelled) and progress, newest first.",
             input_schema=object_schema(), effect=READ, route="service:cdmw.mcp.jobs.JobRegistry.jobs",
             handler=_jobs, runs_on=ON_CALL, paged="jobs"),
        Tool(name="app.job", family="app", title="Job",
             description="One job's state and progress, and its result once it is done. A long result comes in "
                         "pages: call the tool that started the job with next_page_token for the rest.",
             input_schema=object_schema({"job": _JOB, "limit": {"type": "integer", "minimum": 1,
                                                                 "maximum": PAGE_LIMIT_MAX,
                                                                 "default": PAGE_LIMIT_DEFAULT}}, ["job"]),
             effect=READ, route="service:cdmw.mcp.jobs.JobRegistry.get", handler=_job, runs_on=ON_CALL),
        Tool(name="app.cancel_job", family="app", title="Cancel job",
             description="Stops a running job, as Cancel does in the interface. Its work stops at the next point "
                         "where it checks; app_job then reports it as cancelled. Stopping work changes nothing.",
             input_schema=object_schema({"job": _JOB}, ["job"]), effect=READ,
             route="service:cdmw.mcp.jobs.JobRegistry.cancel", handler=_cancel, runs_on=ON_CALL),
    ]
