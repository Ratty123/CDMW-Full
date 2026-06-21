from __future__ import annotations


def run_cli_workflow() -> int:
    from cdmw.core.pipeline import run_cli

    return int(run_cli())
