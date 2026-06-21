from __future__ import annotations

import os
from pathlib import Path
import platform
import sys
import time

from cdmw.services.diagnostics_service import crash_report_details, crash_timestamp
from cdmw.services.workspace_layout import workspace_paths


def bootstrap_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def write_bootstrap_report(kind: str, title: str, body: str) -> None:
    try:
        report_dir = workspace_paths(bootstrap_root())["crash_reports_dir"]
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp_value = crash_timestamp()
        process_id = os.getpid()
        report_path = report_dir / f"{kind}_{timestamp_value}_{process_id}.log"
        details = crash_report_details(kind, title, body, report_id=report_path.stem)
        lines = [
            "Crimson Desert Mod Workbench bootstrap report",
            f"Kind: {kind}",
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Report ID: {details['report_id']}",
            f"Likely Location: {details['likely_location']}",
            f"Exception: {details['exception']}",
            f"Fingerprint: {details['fingerprint']}",
            f"Process ID: {process_id}",
            f"Python: {sys.version}",
            f"Platform: {platform.platform()}",
            "",
            title,
            "",
            body.rstrip(),
        ]
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass
