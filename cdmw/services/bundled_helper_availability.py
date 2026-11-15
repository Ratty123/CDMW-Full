"""Discovery for asset-authoring helpers the app ships with itself.

Mirrors ``cdmw.modding.mesh_native_availability`` for helpers that travel in the
package rather than being built into ``cdmw_mesh_core``. Kept out of
``asset_authoring_service`` so helper-location policy has one owner and the
service keeps to reporting.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path

PACKAGED_RUST_MESH_EDITOR_PROOF_SCHEMA = "cdmw_packaged_rust_mesh_editor_v1"
PACKAGED_RUST_MESH_EDITOR_RELATIVE_PATH = "native/rust_mesh_editor/cdmw_mesh_lab.exe"
PACKAGED_RUST_MESH_EDITOR_MANIFEST_RELATIVE_PATH = (
    "native/rust_mesh_editor/cdmw_mesh_lab.manifest.json"
)


# Consulted ahead of PATH so a frozen build runs the copy it was tested against
# rather than whatever the machine happens to have installed.
BUNDLED_HELPER_FINDERS: dict[str, Callable[[], Path | None]] = {
    # OpenImageIO is no longer bundled: the user's own copy is used (P20 tier 1).
}


def bundled_helper_path(helper_key: str) -> Path | None:
    finder = BUNDLED_HELPER_FINDERS.get(str(helper_key or ""))
    return finder() if finder is not None else None


def bundled_helper_resolution_snapshot() -> list[dict[str, str]]:
    """Report how each helper the app ships with itself resolved.

    Path lookups only -- no helper is executed, so this stays inside the rule
    that startup must not run helper binaries. Imported lazily because the
    authoring service imports this module.
    """

    from cdmw.services.asset_authoring_service import asset_authoring_discovery_report

    report = asset_authoring_discovery_report()
    helpers = report.get("helpers", {}) if isinstance(report, dict) else {}
    if not isinstance(helpers, dict):
        return []
    snapshot: list[dict[str, str]] = []
    for key, helper in sorted(helpers.items()):
        if not isinstance(helper, dict) or not helper.get("bundled"):
            continue
        snapshot.append(
            {
                "key": str(key),
                "status": str(helper.get("status", "")),
                "source": str(helper.get("source", "")),
                "path": str(helper.get("path", "")),
            }
        )
    return snapshot


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def packaged_rust_mesh_editor_resolution_snapshot() -> dict[str, object]:
    """Capture read-only Rust editor evidence while a frozen payload is live.

    PyInstaller removes a one-file extraction root when the process exits, so
    the external startup verifier cannot inspect these files afterward.  This
    snapshot records the paths and independently observed hashes before close.
    The same verified binary supplies Mesh Editor and Archive Preview modes.
    """

    from cdmw.services.mesh_rust_contract import (
        RUST_MESH_PROVENANCE_FILE,
        resolve_rust_mesh_editor,
        validate_rust_mesh_editor_package,
    )

    resolution = resolve_rust_mesh_editor()
    frozen_root_text = str(getattr(sys, "_MEIPASS", "") or "").strip()
    frozen_root = Path(frozen_root_text).resolve() if frozen_root_text else None
    executable = (
        Path(resolution.resolved_path).expanduser()
        if str(resolution.resolved_path or "").strip()
        else None
    )
    manifest = executable.with_name(RUST_MESH_PROVENANCE_FILE) if executable is not None else None

    executable_relative = ""
    manifest_relative = ""
    executable_inside_bundle = False
    manifest_inside_bundle = False
    if frozen_root is not None:
        try:
            if executable is not None:
                executable_relative = executable.resolve().relative_to(frozen_root).as_posix()
                executable_inside_bundle = True
            if manifest is not None:
                manifest_relative = manifest.resolve().relative_to(frozen_root).as_posix()
                manifest_inside_bundle = True
        except (OSError, ValueError):
            executable_relative = ""
            manifest_relative = ""
            executable_inside_bundle = False
            manifest_inside_bundle = False

    reason = validate_rust_mesh_editor_package(resolution)
    if not bool(getattr(sys, "frozen", False)):
        reason = reason or "Mesh Editor proof was not collected from a frozen application"
    elif resolution.source != "frozen":
        reason = reason or "Mesh Editor did not resolve from the frozen bundle"
    elif executable_relative != PACKAGED_RUST_MESH_EDITOR_RELATIVE_PATH:
        reason = reason or "Mesh Editor resolved from an unexpected bundle path"
    elif manifest_relative != PACKAGED_RUST_MESH_EDITOR_MANIFEST_RELATIVE_PATH:
        reason = reason or "Mesh Editor provenance resolved from an unexpected bundle path"

    executable_sha256 = ""
    manifest_sha256 = ""
    provenance: dict[str, object] = {}
    try:
        if executable is not None and executable.is_file():
            executable_sha256 = _sha256_file(executable)
        if manifest is not None and manifest.is_file():
            manifest_sha256 = _sha256_file(manifest)
            loaded = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                provenance = loaded
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        reason = reason or f"Mesh Editor packaged evidence could not be read: {exc}"

    return {
        "schema": PACKAGED_RUST_MESH_EDITOR_PROOF_SCHEMA,
        "status": "available" if not reason else "unavailable",
        "reason": str(reason or ""),
        "source": str(resolution.source or ""),
        "frozen": bool(getattr(sys, "frozen", False)),
        "path": str(executable or ""),
        "relative_path": executable_relative,
        "inside_bundle_root": executable_inside_bundle,
        "executable_sha256": executable_sha256,
        "provenance_path": str(manifest or ""),
        "provenance_relative_path": manifest_relative,
        "provenance_inside_bundle_root": manifest_inside_bundle,
        "provenance_sha256": manifest_sha256,
        "provenance": provenance,
    }


__all__ = [
    "BUNDLED_HELPER_FINDERS",
    "PACKAGED_RUST_MESH_EDITOR_MANIFEST_RELATIVE_PATH",
    "PACKAGED_RUST_MESH_EDITOR_PROOF_SCHEMA",
    "PACKAGED_RUST_MESH_EDITOR_RELATIVE_PATH",
    "bundled_helper_path",
    "bundled_helper_resolution_snapshot",
    "packaged_rust_mesh_editor_resolution_snapshot",
]
