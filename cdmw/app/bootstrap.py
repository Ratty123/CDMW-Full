from __future__ import annotations

from pathlib import Path
import traceback
from typing import Optional, Sequence

from cdmw.app.activation import request_existing_instance_activation
from cdmw.app.args import build_argument_parser
from cdmw.app.bootstrap_reports import write_bootstrap_report
from cdmw.app.cli import run_cli_workflow
from cdmw.app.gui import run_gui_workflow
from cdmw.app.pyinstaller_runtime import write_current_pyinstaller_runtime_marker
from cdmw.app.single_instance import acquire_single_instance_guard, release_single_instance_guard
from cdmw.app.startup_smoke import gui_startup_smoke_requested, write_gui_startup_smoke_result
from cdmw.app.startup_maintenance import run_startup_maintenance, schedule_startup_maintenance
from cdmw.app.startup_splash import (
    close_external_startup_splash,
    start_external_startup_splash,
    update_pyinstaller_boot_splash,
)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    if args.startup_splash_host:
        from cdmw.ui.startup_splash_host import run_startup_splash_host

        return run_startup_splash_host(Path(args.startup_splash_host), parent_pid=int(args.parent_pid or 0))
    if args.model_library_preview_worker:
        from cdmw.services.model_library_preview import run_model_library_preview_worker

        return run_model_library_preview_worker(Path(args.input), Path(args.output))

    if args.cli and args.gui:
        parser.error("Choose only one of --cli or --gui.")
    if args.isolated_renderer_host and (args.cli or args.gui):
        parser.error("Choose isolated renderer host without --cli or --gui.")
    if args.isolated_renderer_host:
        parser.error(
            "Legacy isolated renderer hosts were removed; model previews use the resident "
            ".NET/Vortice renderer."
        )

    run_gui_mode = not args.cli and not args.isolated_renderer_host
    if run_gui_mode:
        if not acquire_single_instance_guard():
            if gui_startup_smoke_requested():
                write_gui_startup_smoke_result(
                    ok=False,
                    stage="single_instance_guard",
                    detail="Another process owns the requested single-instance scope.",
                )
                update_pyinstaller_boot_splash("Startup smoke blocked by another instance.")
                return 3
            request_existing_instance_activation()
            update_pyinstaller_boot_splash("Already running.")
            return 0
        write_current_pyinstaller_runtime_marker()
        start_external_startup_splash()
        schedule_startup_maintenance()
        update_pyinstaller_boot_splash("Loading...")
    elif args.cli:
        run_startup_maintenance()

    try:
        if args.cli:
            runner = run_cli_workflow
        else:
            runner = run_gui_workflow
        return runner()
    except Exception:
        write_bootstrap_report(
            "bootstrap_failure",
            "Application failed before the normal crash reporter completed startup",
            traceback.format_exc(),
        )
        raise
    finally:
        if run_gui_mode:
            close_external_startup_splash()
            release_single_instance_guard()
