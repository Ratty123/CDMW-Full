"""CLI for strict assembly of parallel equipment material capture shards."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from tools.mesh_harness.equipment_material_capture_merge import (
    assemble_equipment_material_capture,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[2]
    catalogue_path = args.catalogue.expanduser().resolve(strict=True)
    resolution_path = args.resolution.expanduser().resolve(strict=True)
    output_root = args.output_root.expanduser().resolve()
    shard_roots = tuple(
        value.expanduser().resolve(strict=True) for value in args.shard_root
    )
    _require_external_root(output_root, repository_root, resolution_path)
    manifest = assemble_equipment_material_capture(
        catalogue_path=catalogue_path,
        resolution_path=resolution_path,
        shard_roots=shard_roots,
        output_root=output_root,
    )
    print(
        json.dumps(
            {
                "census_run_id": manifest.get("census_run_id"),
                "status_counts": manifest.get("status_counts"),
                "capture_complete": manifest.get("capture_complete"),
                "assembly_sha256": manifest.get("assembly", {}).get("sha256"),
                "output_root": str(output_root),
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    print(
        "Source-cache note: assembled reports retain absolute cache paths under the "
        "source shard roots; keep all shard roots alongside the assembled evidence.",
        flush=True,
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Strictly assemble complete, non-overlapping production material capture "
            "shards into a new canonical evidence root."
        )
    )
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--resolution", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument(
        "--shard-root",
        required=True,
        action="append",
        type=Path,
        help="Completed shard evidence root; repeat once per shard.",
    )
    return parser


def _require_external_root(
    output_root: Path,
    repository_root: Path,
    resolution_path: Path,
) -> None:
    resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
    live_archive = (
        resolution.get("live_archive", {}) if isinstance(resolution, dict) else {}
    )
    game_root_text = (
        live_archive.get("package_root", "") if isinstance(live_archive, dict) else ""
    )
    protected = [(repository_root.resolve(), "repository")]
    if game_root_text:
        protected.append(
            (Path(str(game_root_text)).expanduser().resolve(), "game install")
        )
    for root, label in protected:
        if output_root == root or output_root.is_relative_to(root):
            raise ValueError(f"Equipment capture evidence must be outside the {label}.")


if __name__ == "__main__":
    sys.exit(main())
