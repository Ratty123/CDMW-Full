"""Command-line orchestration for the production equipment material audit."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.core.atomic_file import atomic_write_text
from cdmw.ui.shell.archive_backend_resources import resolve_archive_backend_worker
from tools.mesh_harness.equipment_archive_resolution import (
    resolve_live_equipment_catalogue,
)
from tools.mesh_harness.equipment_archive_worker import AuditArchiveWorkerClient
from tools.mesh_harness.equipment_material_audit import (
    build_frozen_equipment_catalogue,
    write_frozen_equipment_catalogue,
)


AUDIT_RUN_STATE_SCHEMA = "cdmw_equipment_material_audit_run_state_v1"


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[2]
    generation = args.generation.expanduser().resolve(strict=True)
    game_root = args.game_root.expanduser().resolve(strict=True)
    cache_root = args.cache_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    _require_external_evidence_root(output_root, repository_root, game_root)
    output_root.mkdir(parents=True, exist_ok=True)
    state_path = output_root / "audit-run-state.json"

    try:
        catalogue = build_frozen_equipment_catalogue(generation)
        catalogue_path = write_frozen_equipment_catalogue(
            catalogue,
            output_root / "catalogue.json",
        )
        _write_state(
            state_path,
            state="catalogue_written",
            catalogue_path=catalogue_path,
            resolution_path=None,
            detail={
                "logical_models": len(catalogue.logical_models),
                "records": len(catalogue.records),
                "icons": len(catalogue.icons),
            },
        )
        print(
            f"Frozen catalogue: {len(catalogue.records)} records, "
            f"{len(catalogue.logical_models)} logical models, {len(catalogue.icons)} icons",
            flush=True,
        )
        if args.catalogue_only:
            return 0

        worker_path = (
            args.worker.expanduser().resolve(strict=True)
            if args.worker is not None
            else resolve_archive_backend_worker()
        )
        with AuditArchiveWorkerClient(
            (worker_path,),
            cache_root=cache_root,
            progress=_worker_progress,
        ) as worker:
            session = worker.open_archive(game_root)
            print(
                f"Live archive: {session.entry_count} entries, "
                f"fingerprint={session.fingerprint}, cache_hit={session.cache_hit}",
                flush=True,
            )
            resolution = resolve_live_equipment_catalogue(
                catalogue,
                worker,
                progress=_resolution_progress,
            )

        resolution_path = output_root / "resolution.json"
        atomic_write_text(
            resolution_path,
            json.dumps(resolution, indent=2, sort_keys=True),
        )
        counts = resolution.get("counts")
        counts = counts if isinstance(counts, Mapping) else {}
        _write_state(
            state_path,
            state="resolution_written",
            catalogue_path=catalogue_path,
            resolution_path=resolution_path,
            detail=dict(counts),
        )
        print(json.dumps(counts, indent=2, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        _write_state(
            state_path,
            state="failed",
            catalogue_path=output_root / "catalogue.json",
            resolution_path=None,
            detail={"error": f"{type(exc).__name__}: {exc}"},
        )
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze and resolve the production equipment material audit catalogue."
    )
    parser.add_argument("--generation", required=True, type=Path)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--catalogue-only", action="store_true")
    return parser


def _require_external_evidence_root(
    output_root: Path,
    repository_root: Path,
    game_root: Path,
) -> None:
    for protected_root, label in (
        (repository_root.resolve(), "repository"),
        (game_root.resolve(), "game install"),
    ):
        if output_root == protected_root or output_root.is_relative_to(protected_root):
            raise ValueError(f"Audit evidence output must be outside the {label}.")


def _resolution_progress(current: int, total: int, message: str) -> None:
    print(f"[{current}/{total}] {message}", flush=True)


def _worker_progress(status: str, payload: Mapping[str, object]) -> None:
    if status == "batch":
        return
    phase = str(payload.get("phase", "") or "").strip()
    detail = str(payload.get("message", "") or "").strip()
    if phase or detail:
        print(f"[archive:{status}] {phase or detail}", flush=True)


def _write_state(
    path: Path,
    *,
    state: str,
    catalogue_path: Path,
    resolution_path: Path | None,
    detail: Mapping[str, object],
) -> None:
    payload = {
        "schema": AUDIT_RUN_STATE_SCHEMA,
        "state": state,
        "updated_utc": datetime.now(UTC).isoformat(),
        "catalogue_path": str(catalogue_path),
        "resolution_path": str(resolution_path) if resolution_path is not None else None,
        "detail": dict(detail),
    }
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
