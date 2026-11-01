"""Write a new item straight into DMM's mods folder ("Send to DMM").

DMM (Definitive Mod Manager) lists every folder in its mods folder; the user still
enables the mod and mounts it in DMM, which has no command line. A folder CDMW wrote
earlier is replaced as a whole, so a re-send never merges with the previous version.
A folder CDMW did not write is never touched.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.packages.layout import sanitize_mod_package_folder_name

DMM_FOLDER_SETTING = "dmm/install_folder"
_CDMW_GENERATOR = "Crimson Desert Mod Workbench"


@dataclass(frozen=True)
class DmmSendResult:
    folder: Path
    replaced: bool
    title: str


def find_dmm(saved: str = "") -> Optional[Path]:
    """The DMM folder (the one holding DMM.exe): the saved choice, else a usual place."""
    candidates = [saved] if saved else []
    candidates += [r"C:\DMM", os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "DMM"),
                   os.path.join(os.environ.get("ProgramFiles", ""), "DMM")]
    for candidate in candidates:
        if candidate and (Path(candidate) / "DMM.exe").is_file():
            return Path(candidate)
    return None


def dmm_mods_folder(install: Path | str) -> Path:
    """DMM's mods folder, as DMM's own config.json names it."""
    install = Path(install)
    if not (install / "DMM.exe").is_file():
        raise ValueError(f"{install} is not DMM's folder; choose the folder that contains DMM.exe.")
    mods = install / "mods"
    try:
        configured = json.loads((install / "config.json").read_text(encoding="utf-8")).get("modsPath")
    except (OSError, ValueError, AttributeError):
        configured = None
    if isinstance(configured, str) and configured.strip():
        mods = Path(configured) if Path(configured).is_absolute() else install / configured
    if not mods.is_dir():
        raise ValueError(f"DMM's mods folder {mods} does not exist. Open DMM once, then send again.")
    return mods


def _written_by_cdmw(folder: Path) -> bool:
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and str(manifest.get("generator", "")).startswith(_CDMW_GENERATOR)


def destination(mods: Path, title: str) -> tuple[Path, bool]:
    """The mod folder for `title` and whether it replaces a folder CDMW wrote earlier."""
    folder = Path(mods) / sanitize_mod_package_folder_name(title)
    if not folder.exists():
        return folder, False
    if folder.is_dir() and _written_by_cdmw(folder):
        return folder, True
    raise ValueError(f"DMM already has a mod folder named {folder.name} that CDMW did not write. "
                     "Rename the mod and send it again.")


def send_plan(plan, mods: Path, title: str, *, service=None, package_info=None,
              stop_event: Optional[threading.Event] = None) -> DmmSendResult:
    """Write a planned new item as a DMM mod in DMM's mods folder."""
    from cdmw.core.atomic_file import atomic_publish_directory
    from cdmw.models import ModPackageInfo
    from cdmw.services.new_item_service import NewItemService

    folder, replaced = destination(mods, title)
    info = package_info or ModPackageInfo(title=title, description=f"{title}, sent to DMM by CDMW.")
    # Write beside DMM's folder, then swap it in: a failed or cancelled send leaves the
    # previous version in place, and a re-send never merges with it.
    with tempfile.TemporaryDirectory(prefix=".cdmw-send-", dir=folder.parent.parent) as staging:
        staged = Path(staging) / folder.name
        (service or NewItemService()).export_loose(plan, staged, manager="DMM", package_info=info,
                                                   replace_existing=False, stop_event=stop_event)
        raise_if_cancelled(stop_event, "Send to DMM cancelled.")
        destination(mods, title)  # Refuse a folder that appeared meanwhile.
        atomic_publish_directory(staged, folder, replace_existing=True)
    return DmmSendResult(folder, replaced, title)


def send_item_package(package_path: Path | str, game_root: Path | str, mods: Path, *,
                      stop_event: Optional[threading.Event] = None,
                      on_log: Optional[Callable[[str], None]] = None) -> DmmSendResult:
    """Plan a .cditem package's item on the installed game and write it as a DMM mod."""
    from cdmw.models import ModPackageInfo
    from cdmw.services.independent_item_package import read_package, recipe_plan, stock_snapshot

    package = read_package(Path(package_path).read_bytes(), stop_event=stop_event)
    if on_log:
        on_log(f"Reading the game tables for {package.title}…")
    snapshot = stock_snapshot(Path(game_root).resolve(), stop_event=stop_event)
    plan = recipe_plan(package, snapshot, stop_event=stop_event).plan
    info = ModPackageInfo(title=package.title, description=f"{package.title}, sent to DMM by CDMW from a .cditem package.")
    return send_plan(plan, mods, package.title, package_info=info, stop_event=stop_event)


__all__ = ["DMM_FOLDER_SETTING", "DmmSendResult", "destination", "dmm_mods_folder", "find_dmm",
           "send_item_package", "send_plan"]
