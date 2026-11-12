"""Publish a staged Mesh Editor mod folder: the last step every Mesh Editor build shares.

Build Mod and Combine into one mod both stage a complete package first and then
call this, so the manager metadata, CDMW's history records and the optional ZIP
are handled the same way for both.
"""

from __future__ import annotations

import threading
from pathlib import Path

from cdmw.domain.cancellation import raise_if_cancelled


def publish_mesh_mod_output(
    staging: Path,
    root: Path,
    *,
    manager_profile: str,
    create_zip: bool = False,
    stop_event: threading.Event | None = None,
) -> Path | None:
    """Move `staging` to `root` (and its ZIP beside it); return the ZIP path or None.

    `root` must not exist yet. The staging folder is consumed on success.
    """

    from cdmw.core.atomic_file import atomic_publish_paths
    from cdmw.core.mod_export_history import retain_mod_history
    from cdmw.core.mod_package import _write_package_zip

    staging, root = Path(staging), Path(root)
    # DMM reads the same name/version/author/description from manifest.json.
    # Remove the duplicate before binding local history to the final files.
    if manager_profile == "dmm":
        (staging / "modinfo.json").unlink(missing_ok=True)
    elif manager_profile == "cdumm":
        # CDUMM detects modinfo.json + files/ and reads the mod details
        # from modinfo.json. Its importer derives encryption from the game.
        (staging / "manifest.json").unlink(missing_ok=True)
        (staging / ".no_encrypt").unlink(missing_ok=True)
    retain_mod_history(staging, stop_event=stop_event)
    (staging / "README.txt").unlink(missing_ok=True)
    zip_path = root.with_name(root.name + ".zip") if create_zip else None
    staged_zip = staging.with_name(staging.name + ".zip") if create_zip else None
    try:
        outputs = [(staging, root)]
        if staged_zip is not None:
            _write_package_zip(staging, zip_path=staged_zip, stop_event=stop_event)
            outputs.append((staged_zip, zip_path))
        raise_if_cancelled(stop_event, "Mesh output cancelled")
        atomic_publish_paths(outputs, replace_existing=False)
        return zip_path
    finally:
        if staged_zip is not None:
            staged_zip.unlink(missing_ok=True)


__all__ = ["publish_mesh_mod_output"]
