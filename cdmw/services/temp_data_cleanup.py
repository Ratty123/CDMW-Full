"""Conservative background maintenance for CDMW's disposable session data."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import tempfile
import time
from typing import Sequence

from cdmw.core.atomic_file import atomic_write_text
from cdmw.core.owned_temp import (
    OWNER_MARKER,
    RETIRED_PREFIX,
    cleanup_owned_temp_directory,
    owned_temp_directory_is_protected,
)
from cdmw.core.temp_cache import GENERATED_MATERIALS_CACHE_DIRNAME

_SESSION_PREFIXES = ("cdmw_effect_workspace_", "cdmw_effect_placement_", "cdmw_preview_session_output_", "cdmw_new_item_model_")
_LEGACY_GENERATED_DIRS = (
    "cdmw_synthetic_materials", "cdmw_baked_material_atlases", "cdmw_gltf_imports",
    "cdmw_gltf_uv_bakes", "cdmw_material_combiner", "cdmw-shader-preview-v1",
    "cdmw-material-authority-artifacts-v1",
    "cdmw_effect_placement",
)
_logger = logging.getLogger(__name__)


def maintain_temp_data(
    *, cache_roots: Sequence[Path], report_path: Path, temp_root: Path | None = None,
    cache_pruning: dict | None = None,
) -> dict:
    """Remove only abandoned marked roots; record unverified leftovers without adopting them."""
    temporary = Path(temp_root or tempfile.gettempdir()).resolve()
    report = {
        "schema": "cdmw_temp_data_cleanup_v1", "checked_at": time.time(),
        "removed_roots": 0, "preserved_roots": 0, "deferred_roots": 0, "details": [],
        "cache_pruning": cache_pruning or {},
    }

    def record(path: Path, outcome: str) -> None:
        key = {"removed": "removed_roots", "cleanup_failed": "deferred_roots"}.get(outcome, "preserved_roots")
        report[key] += 1
        if len(report["details"]) < 64:
            report["details"].append({"path": str(path), "outcome": outcome})

    def children(parent: Path) -> tuple[Path, ...]:
        try:
            if parent.is_symlink() or parent.resolve() != parent.absolute():
                record(parent, "redirected_root")
                return ()
            return tuple(parent.iterdir())
        except FileNotFoundError:
            return ()
        except OSError:
            record(parent, "inaccessible_root")
            return ()

    candidates = {path for path in children(temporary) if path.name.startswith((*_SESSION_PREFIXES, RETIRED_PREFIX))}
    for cache_root in cache_roots:
        parent = Path(cache_root).absolute() / GENERATED_MATERIALS_CACHE_DIRNAME
        candidates.update(path for path in children(parent) if path.name.startswith(("run-", RETIRED_PREFIX)))
    for path in sorted(candidates):
        if owned_temp_directory_is_protected(path):
            try:
                outcome = "active_recent_or_unverified" if (path / OWNER_MARKER).is_file() else "unmarked_leftover"
            except OSError:
                outcome = "inaccessible_root"
            record(path, outcome)
        elif cleanup_owned_temp_directory(path, abandoned_only=True):
            record(path, "removed")
        else:
            record(path, "cleanup_failed")

    # Older releases used unmarked shared roots. A folder name alone does not
    # establish ownership, and another version may still be using those files.
    for name in _LEGACY_GENERATED_DIRS:
        path = temporary / name
        try:
            if path.exists():
                record(path, "legacy_unmanaged_cache")
        except OSError:
            record(path, "inaccessible_root")

    from cdmw.rendering.native_preview_temp import sweep_abandoned_preview_jobs

    report["removed_native_preview_jobs"] = sweep_abandoned_preview_jobs(temporary)
    for path in children(temporary):
        if path.name.startswith("cdmw_preview_core_"):
            record(path, "retained_native_preview_job")
    try:
        atomic_write_text(report_path, json.dumps(report, indent=2) + "\n")
    except OSError:
        _logger.warning("Could not save temporary-data cleanup report to %s", report_path, exc_info=True)
    _logger.info("Temporary-data cleanup: %s", {key: value for key, value in report.items() if key != "details"})
    return report
