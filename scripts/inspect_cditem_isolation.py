"""Inspect .cditem ownership and no-merge readiness without publishing or launching."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.services.independent_item_isolation import inspect_isolation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--target", choices=("archive", "virtual"), default="virtual",
                        help="Current deployment route to inspect; match the packages' existing route.")
    parser.add_argument("--folder", type=Path, action="append", default=[],
                        help="Additional ordinary mod folder to include in dependency checks.")
    parser.add_argument("--require-isolated", action="store_true",
                        help="Return status 3 when the stronger no-shared-file-merge claim is not admitted.")
    parser.add_argument("packages", type=Path, nargs="+")
    args = parser.parse_args(argv)
    try:
        result = inspect_isolation(args.packages, args.game_root, target=args.target, folders=args.folder)
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 3 if args.require_isolated and not result["isolated_new_item_admitted"] else 0


if __name__ == "__main__":
    sys.exit(main())
