"""Argument parsing and command-line entry point for compact visual capture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from tools.compact_shell_visual.contracts import (
    HARNESS_DESCRIPTION,
    REFERENCE_FILENAMES,
    REFERENCE_SIZE,
    parse_size,
)
from tools.compact_shell_visual.runner import run_harness


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=HARNESS_DESCRIPTION)
    parser.add_argument("--all", action="store_true", help="Capture all 15 registered tools.")
    parser.add_argument(
        "--tool",
        action="append",
        choices=tuple(REFERENCE_FILENAMES),
        help="Capture one registered key; repeat for a batch.",
    )
    parser.add_argument("--output", required=True, help="Output directory for PNGs and report JSON.")
    parser.add_argument("--size", type=parse_size, default=REFERENCE_SIZE, help="Primary WIDTHxHEIGHT.")
    parser.add_argument("--theme", default="crimson_desert", help="Compact Workspace theme key.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_argument_parser()
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    if not arguments.all and not arguments.tool:
        parser.error("choose --all or at least one --tool")
    if arguments.all and arguments.tool:
        parser.error("--all cannot be combined with --tool")
    report = run_harness(arguments)
    captures = report.get("captures", [])
    print(
        json.dumps(
            {
                "captures": len(captures) if isinstance(captures, list) else 0,
                "output": str(Path(arguments.output).expanduser().resolve()),
                "tools": len(REFERENCE_FILENAMES) if arguments.all else len(arguments.tool or ()),
            },
            sort_keys=True,
        )
    )
    return 0
