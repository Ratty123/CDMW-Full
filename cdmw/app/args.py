from __future__ import annotations

import argparse
from typing import Optional, Sequence


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crimson Desert Mod Workbench")
    parser.add_argument("--cli", action="store_true", help="Run the command-line workflow using the top-level defaults.")
    parser.add_argument("--gui", action="store_true", help="Force the GUI workflow.")
    parser.add_argument("--isolated-renderer-host", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--backend", default="d3d11", choices=("d3d11", "vulkan"), help=argparse.SUPPRESS)
    parser.add_argument("--preview-package", default="", help=argparse.SUPPRESS)
    parser.add_argument("--status-file", default="", help=argparse.SUPPRESS)
    parser.add_argument("--theme-background", default="", help=argparse.SUPPRESS)
    parser.add_argument("--theme-text", default="", help=argparse.SUPPRESS)
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--startup-splash-host", default="", help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, default=0, help=argparse.SUPPRESS)
    return parser


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    return build_argument_parser().parse_args(argv)
