from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from tools.headless_stress.task_builders import (
    DEFAULT_MODEL_ROOT,
    PROFILES,
    SOAK_MINUTES_DEFAULT,
    SOAK_MINUTES_MINIMUM,
    prepare_output_root,
)
from tools.headless_stress.runner import run_profile, run_soak


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run headless feature stress checks without starting the full app.")
    parser.add_argument("--profile", choices=PROFILES, default="quick")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--game-root", type=Path)
    parser.add_argument(
        "--include-native-visual",
        action="store_true",
        help="Opt in to the visible real-PAC .NET D3D11 proof and automated mouse input.",
    )
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--soak-minutes", type=float, default=SOAK_MINUTES_DEFAULT)
    parser.add_argument("--max-model-files", type=int)
    parser.add_argument("--audit-zip-contents", action="store_true")
    parser.add_argument("--max-zip-audits", type=int)
    parser.add_argument("--cache-runs", type=int)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--cache-real-root", type=Path)
    args = parser.parse_args(argv)
    if args.profile == "soak" and float(args.soak_minutes) < SOAK_MINUTES_MINIMUM:
        parser.error(f"--profile soak requires --soak-minutes >= {SOAK_MINUTES_MINIMUM:g}")
    if args.cache_runs is not None and args.cache_runs < 1:
        parser.error("--cache-runs must be >= 1")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    args = parse_args(raw_argv)
    output_root = prepare_output_root(args.output)
    if args.profile == "soak":
        return run_soak(args, output_root, raw_argv)
    return run_profile(args, output_root, raw_argv)
