"""CLI for the resumable production equipment material capture census."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cdmw.services.mesh_rust_contract import (
    resolve_rust_mesh_editor,
    validate_rust_mesh_editor_package,
)
from tools.mesh_harness.equipment_material_capture import run_equipment_material_capture


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[2]
    catalogue_path = args.catalogue.expanduser().resolve(strict=True)
    resolution_path = args.resolution.expanduser().resolve(strict=True)
    output_root = args.output_root.expanduser().resolve()
    cache_root = args.cache_root.expanduser().resolve()
    _require_external_root(output_root, repository_root, resolution_path)
    output_root.mkdir(parents=True, exist_ok=True)

    if args.rust_helper is not None:
        rust_helper = args.rust_helper.expanduser().resolve(strict=True)
    else:
        resolution = resolve_rust_mesh_editor()
        error = validate_rust_mesh_editor_package(resolution)
        if error:
            raise RuntimeError(error)
        rust_helper = Path(resolution.resolved_path).resolve(strict=True)
    manifest = run_equipment_material_capture(
        catalogue_path=catalogue_path,
        resolution_path=resolution_path,
        output_root=output_root,
        cache_root=cache_root,
        rust_helper=rust_helper,
        start=args.start,
        limit=args.limit,
        resume=not args.no_resume,
        census_run_id=args.census_run_id,
        capture_timeout_seconds=args.capture_timeout,
        stop_on_failure=args.stop_on_failure,
        progress=_progress,
    )
    print(
        f"Census run: {manifest.get('census_run_id', '')}\n"
        "Capture binaries: "
        f"Preview Core {manifest['capture_binaries']['preview_core']['sha256'][:12]}, "
        f"Rust {manifest['capture_binaries']['rust_helper']['sha256'][:12]}",
        flush=True,
    )
    print(
        json.dumps(manifest.get("status_counts", {}), indent=2, sort_keys=True),
        flush=True,
    )
    return 1 if int(manifest.get("failed_count", 0) or 0) else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture the frozen 2,057-PAC equipment census through Preview Core and "
            "direct/full Rust D3D12."
        )
    )
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--resolution", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--rust-helper", type=Path)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--capture-timeout", type=float, default=180.0)
    parser.add_argument(
        "--census-run-id",
        help="Shared immutable run ID; pass the same value to every shard.",
    )
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
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


def _progress(current: int, total: int, message: str) -> None:
    print(f"[{current}/{total}] {message}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
