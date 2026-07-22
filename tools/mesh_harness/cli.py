from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import os
from pathlib import Path

from tools.mesh_harness.constants import _DEFAULT_GAME_ROOT, _REAL_MESH_EDITOR_VISUAL_SCENARIO
from tools.mesh_harness.parity import (
    DEFAULT_PARITY_DIFFERENCE_SCALE,
    DEFAULT_PARITY_FAIL_PERCENT,
    DEFAULT_PARITY_FAIL_THRESHOLD,
    DEFAULT_PARITY_HARD_FAIL_THRESHOLD,
)
from tools.mesh_harness.performance_contract import PerformanceContractError
from tools.mesh_harness.scenario_registry import scenario_names


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Mesh Editor service/native preview harness without starting the app.")
    parser.add_argument("--scenario", default=_REAL_MESH_EDITOR_VISUAL_SCENARIO, choices=scenario_names())
    parser.add_argument(
        "--game-root",
        type=Path,
        default=Path(os.environ.get("CDMW_GAME_ROOT") or _DEFAULT_GAME_ROOT),
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--parity-reference", type=Path, help="Reference PNG for offline OpenImageIO parity comparison.")
    parser.add_argument("--parity-candidate", type=Path, help="Candidate PNG for offline OpenImageIO parity comparison.")
    parser.add_argument("--oiio-path", type=Path, help="Optional path to oiiotool; CDMW_OIIO_BIN and PATH remain supported.")
    parser.add_argument("--parity-fail-threshold", type=float, default=DEFAULT_PARITY_FAIL_THRESHOLD)
    parser.add_argument("--parity-fail-percent", type=float, default=DEFAULT_PARITY_FAIL_PERCENT)
    parser.add_argument("--parity-hard-fail-threshold", type=float, default=DEFAULT_PARITY_HARD_FAIL_THRESHOLD)
    parser.add_argument("--parity-difference-scale", type=float, default=DEFAULT_PARITY_DIFFERENCE_SCALE)
    parser.add_argument(
        "--performance-manifest",
        type=Path,
        help="Versioned manifest for a resident .NET preview performance capture.",
    )
    parser.add_argument(
        "--performance-duration-seconds",
        type=float,
        help="Requested resident capture duration; defaults to 30 seconds when a manifest is supplied.",
    )
    parser.add_argument(
        "--performance-target-hz",
        type=float,
        help="Frame-pacing target; defaults to 144 Hz when a manifest is supplied.",
    )
    args = parser.parse_args(argv)
    from tools.mesh_harness.scenario_runner import run_scenario

    try:
        result = run_scenario(
            args.scenario,
            args.output,
            game_root=args.game_root,
            parity_reference=args.parity_reference,
            parity_candidate=args.parity_candidate,
            openimageio_path=args.oiio_path,
            parity_fail_threshold=args.parity_fail_threshold,
            parity_fail_percent=args.parity_fail_percent,
            parity_hard_fail_threshold=args.parity_hard_fail_threshold,
            parity_difference_scale=args.parity_difference_scale,
            performance_manifest=args.performance_manifest,
            performance_duration_seconds=args.performance_duration_seconds,
            performance_target_hz=args.performance_target_hz,
        )
    except PerformanceContractError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1
