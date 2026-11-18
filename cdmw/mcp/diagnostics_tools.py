"""Read the diagnostic snapshot without creating a report draft or bundle."""

from __future__ import annotations

import json

from cdmw.mcp.names import READ
from cdmw.mcp.rail_actions import tool, window
from cdmw.mcp.tools import ON_WORKER


def _diagnostics(call):
    from cdmw.services.problem_report_diagnostics import collect_report_build_identity, collect_report_logs
    from cdmw.services.problem_report_service import ReportRedactor

    snapshot = call.context.ui_call(lambda: window(call).shell._problem_report_snapshot())
    evidence = {"context": json.loads(snapshot.context_json),
                "build": collect_report_build_identity(stop_event=call.cancel_event),
                "logs": collect_report_logs(snapshot, stop_event=call.cancel_event)}
    text = json.dumps(ReportRedactor(snapshot).value(evidence), ensure_ascii=False, indent=2)
    limit = call.arguments.get("max_characters", 64000)
    return {"text": text[:limit], "truncated": len(text) > limit, "characters": len(text)}


def diagnostics_tools():
    return [
        tool("app.diagnostics", READ, "Read CDMW's redacted diagnostic context, build identity and recent logs.",
             "ui:ProblemReport.snapshot", _diagnostics,
             {"max_characters": {"type": "integer", "minimum": 1, "maximum": 256000}}, runs_on=ON_WORKER),
    ]
