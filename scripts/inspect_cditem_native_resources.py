"""Prepare separate .cditem research resource images and print their byte/identity reports.

No game/profile output is published and no native engine call is made. Existing
archive checks may use temporary files and the installed checksum helper.
"""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.services.independent_item_native_resources import prepare_native_resource_images


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--target", choices=("archive", "virtual"), default="virtual",
                        help="Existing identity/deployment context to inspect; this does not select a native backend.")
    parser.add_argument("--folder", type=Path, action="append", default=[],
                        help="Additional ordinary mod folder included in dependency checks.")
    parser.add_argument("packages", type=Path, nargs="+")
    args = parser.parse_args(argv)
    try:
        images = prepare_native_resource_images(args.packages, args.game_root, target=args.target, folders=args.folder)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, str(exc) + "\n")
    report = {"format": "cdmw_native_resource_preparation_research_v1", "published": False,
              "native_admission": False, "packages": [image.report() for image in images]}
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
