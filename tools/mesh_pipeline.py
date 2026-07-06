from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cdmw.modding.mesh_asset import mesh_asset_from_bytes, mesh_asset_to_inspect_dict
from cdmw.modding.mesh_roundtrip import (
    parse_allowed_difference,
    roundtrip_mesh_file,
    roundtrip_summary_lines,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run mesh pipeline checks without opening the UI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Parse a mesh and write MeshAsset inspection JSON.")
    inspect_parser.add_argument("asset", type=Path)
    inspect_parser.add_argument("--out", type=Path)

    roundtrip_parser = subparsers.add_parser("roundtrip", help="Parse and rebuild a mesh with no edits.")
    roundtrip_parser.add_argument("asset", type=Path)
    roundtrip_parser.add_argument("--out", type=Path)
    roundtrip_parser.add_argument("--report", type=Path)
    roundtrip_parser.add_argument("--tolerant", action="store_true")
    roundtrip_parser.add_argument(
        "--allow-range",
        action="append",
        default=[],
        help="Inclusive allowed diff range, e.g. 0x10-0x1F:timestamp.",
    )

    args = parser.parse_args(argv)
    if args.command == "inspect":
        return _inspect(args.asset, args.out)
    if args.command == "roundtrip":
        allowed = tuple(parse_allowed_difference(value) for value in args.allow_range)
        result = roundtrip_mesh_file(
            args.asset,
            output_path=args.out,
            report_path=args.report,
            strict=not (args.tolerant or allowed),
            allowed_differences=allowed,
        )
        for line in roundtrip_summary_lines(result.report):
            print(line)
        return 0 if result.report.get("result") == "PASS" else 1
    raise AssertionError(args.command)


def _inspect(asset_path: Path, out_path: Path | None) -> int:
    asset = mesh_asset_from_bytes(asset_path.read_bytes(), str(asset_path))
    payload = json.dumps(mesh_asset_to_inspect_dict(asset), indent=2)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
