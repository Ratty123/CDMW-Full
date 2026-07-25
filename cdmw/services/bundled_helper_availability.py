"""Discovery for asset-authoring helpers the app ships with itself.

Mirrors ``cdmw.modding.mesh_native_availability`` for helpers that travel in the
package rather than being built into ``cdmw_mesh_core``. Kept out of
``asset_authoring_service`` so helper-location policy has one owner and the
service keeps to reporting.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path


OPENIMAGEIO_BUNDLE_DIRECTORY = "openimageio"
OPENIMAGEIO_BINARY_NAME = "oiiotool.exe"


def find_bundled_openimageio_binary() -> Path | None:
    """Locate the ``oiiotool`` the app ships beside itself.

    The pip console script in ``Scripts/`` is only a launcher shim. The real
    binary sits in the package's own ``bin/`` next to the DLL closure it loads
    from its own directory, so the shim is not a usable substitute and a frozen
    build carries the whole directory instead.
    """

    candidates: list[Path] = []
    frozen_root = Path(str(getattr(sys, "_MEIPASS", ""))) if getattr(sys, "_MEIPASS", "") else None
    exe_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    for root in (frozen_root, exe_root):
        if root is not None:
            candidates.append(root / OPENIMAGEIO_BUNDLE_DIRECTORY / OPENIMAGEIO_BINARY_NAME)
    try:
        module_spec = importlib.util.find_spec("OpenImageIO")
    except (ImportError, ModuleNotFoundError, ValueError):
        module_spec = None
    if module_spec is not None:
        for location in tuple(getattr(module_spec, "submodule_search_locations", ()) or ()):
            if str(location or "").strip():
                candidates.append(Path(location) / "bin" / OPENIMAGEIO_BINARY_NAME)
    return next((candidate for candidate in candidates if candidate.is_file()), None)


# Consulted ahead of PATH so a frozen build runs the copy it was tested against
# rather than whatever the machine happens to have installed.
BUNDLED_HELPER_FINDERS: dict[str, Callable[[], Path | None]] = {
    "openimageio": find_bundled_openimageio_binary,
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


__all__ = [
    "BUNDLED_HELPER_FINDERS",
    "OPENIMAGEIO_BINARY_NAME",
    "OPENIMAGEIO_BUNDLE_DIRECTORY",
    "bundled_helper_path",
    "bundled_helper_resolution_snapshot",
    "find_bundled_openimageio_binary",
]
