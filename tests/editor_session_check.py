"""Run the Mesh Editor helper's own startup check on a session folder CDMW wrote.

CDMW and the helper each keep a list of what a session folder may hold. When CDMW writes
something the helper's list does not allow, the editor closes as it starts ("unexpected
session entry ..."), which neither side's own tests see (2026-11-24: a ``captures``
folder, and a reopened set's ``material-state-<key>.json``). These tests reopen saved work
in a real ``RustMeshAuthoringSession`` and hand its manifest to the helper's
``--validate-cdmw-session``, the same ``LoadedCdmwSessionPackage::load`` the editor runs.

The helper comes from ``CDMW_MESH_LAB_BIN``, else the newest of the Cargo debug build and
the staged release build that knows the check; without one the test is skipped.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_CANDIDATES = (
    ROOT / "tools" / "rust_mesh_lab" / "target" / "debug" / "cdmw_mesh_lab.exe",
    ROOT / "tools" / "rust_mesh_lab" / "target" / "release" / "cdmw_mesh_lab.exe",
    ROOT / "native" / "rust_mesh_editor" / "build" / "Release" / "cdmw_mesh_lab.exe",
)
_FOUND: list[Path | None] = []


def _run(helper: Path, manifest: Path) -> dict:
    run = subprocess.run([str(helper), "--validate-cdmw-session", str(manifest)], capture_output=True,
                         text=True, timeout=120, cwd=str(helper.parent))
    line = next((row for row in reversed(run.stdout.splitlines()) if row.startswith("{")), "")
    return json.loads(line) if line else {}


def helper_with_check() -> Path | None:
    """The first helper binary that answers ``--validate-cdmw-session``, newest first."""

    if _FOUND:
        return _FOUND[0]
    given = os.environ.get("CDMW_MESH_LAB_BIN")
    candidates = [Path(given)] if given else sorted(
        (path for path in _CANDIDATES if path.is_file()), key=lambda path: path.stat().st_mtime, reverse=True)
    found = None
    for helper in candidates:
        try:
            if "ok" in _run(helper, ROOT / "no-such-manifest.json"):
                found = helper
                break
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    _FOUND.append(found)
    return found


_SOURCES = ROOT / "tools" / "rust_mesh_lab" / "apps" / "cdmw_mesh_lab" / "src"


def _stale(helper: Path) -> bool:
    """A helper built before its session check last changed would pass with the old rules."""

    if os.environ.get("CDMW_MESH_LAB_BIN"):
        return False  # the release routine names the staged helper it ships
    newest = max((path.stat().st_mtime for path in _SOURCES.glob("cdmw_session*.rs")), default=0.0)
    return helper.stat().st_mtime < newest


def assert_editor_accepts(manifest_path: Path) -> None:
    """The helper opens this session as the editor would at its start."""

    helper = helper_with_check()
    if helper is None:
        pytest.skip("no Mesh Editor helper with --validate-cdmw-session is built (set CDMW_MESH_LAB_BIN)")
    if _stale(helper):
        pytest.fail(f"{helper} is older than cdmw_session.rs: rebuild it (cargo build -p cdmw_mesh_lab) "
                    "or set CDMW_MESH_LAB_BIN, so the check uses the current rules")
    outcome = _run(helper, Path(manifest_path))
    assert outcome.get("ok") is True, f"the Mesh Editor would refuse this session: {outcome.get('error')}"


__all__ = ["assert_editor_accepts", "helper_with_check"]
