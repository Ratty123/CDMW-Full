"""Launch the standalone Placement & Animation Studio window.

    python scripts/placement_studio.py

Requires a pinned vanilla baseline:

    python -m tools.placement_studio.cli extract

The clip browser additionally reads the installed game's archives; without an install it
falls back to browsing the baseline.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    from tools.placement_studio.corpus import Baseline
    from tools.placement_studio.window import launch

    try:
        baseline = Baseline.load()
    except FileNotFoundError as exc:
        print(f"{exc}\n\nRun: python -m tools.placement_studio.cli extract", file=sys.stderr)
        return 2
    return launch(baseline)


if __name__ == "__main__":
    raise SystemExit(main())
