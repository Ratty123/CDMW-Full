"""Write a new item straight into DMM's mods folder ("Send to DMM").

DMM (Definitive Mod Manager) lists every folder in its mods folder; the user still
enables the mod and mounts it in DMM, which has no command line. A folder CDMW wrote
earlier is replaced as a whole, so a re-send never merges with the previous version.
A folder CDMW did not write is never touched.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.packages.layout import sanitize_mod_package_folder_name

DMM_FOLDER_SETTING = "dmm/install_folder"
# DMM lists this as its own mod next to the folder; enable both.
OPERATIONS_FILE = "CDMW items - shops and groups.json"
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


def _operation_item(intent) -> Optional[int]:
    """The item an append operation adds: a group member key, or a stock line's item."""
    new = intent.get("new") if isinstance(intent, dict) else None
    if isinstance(new, int) and not isinstance(new, bool):
        return new
    value = new.get("value") if isinstance(new, dict) else None
    item = value.get("raw_q") if isinstance(value, dict) else None
    return item if isinstance(item, int) and not isinstance(item, bool) else None


def write_operations(folder: Path, title: str, targets, *, owned_items=()) -> None:
    """Write shop and item group additions as DMM V3 operations beside a mod's archive.

    DMM applies them to the base and the DLC's rows alike; a table copy would replace
    those rows instead and drop what the DLC adds there. Operations already in the
    folder (earlier items of the same mod) are kept, except those for `owned_items`,
    which `targets` restates; an identical operation is written once.
    """
    path = Path(folder) / OPERATIONS_FILE
    owned = {int(key) for key in owned_items}
    existing = []
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8")).get("targets") or []
        except (OSError, ValueError, AttributeError) as exc:
            raise ValueError(f"The mod's {OPERATIONS_FILE} cannot be read to add to it: {exc}") from exc
    merged: dict[str, list] = {}
    for target in existing:
        for intent in target.get("intents") or ():
            if _operation_item(intent) not in owned:
                merged.setdefault(target["file"], []).append(intent)
    for target in targets:
        intents = merged.setdefault(target["file"], [])
        intents.extend(intent for intent in target["intents"] if intent not in intents)
    merged = {name: intents for name, intents in merged.items() if intents}
    if not merged:
        path.unlink(missing_ok=True)
        return
    operations = dict(format=3, modinfo=dict(title=f"{title} (shops and groups)", version="1.0.0", author="CDMW",
                                             description="Adds CDMW's items to their shops and item groups."),
                      targets=[dict(file=name, intents=intents) for name, intents in merged.items()])
    path.write_text(json.dumps(operations, indent=2) + "\n", encoding="utf-8")


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
    """Plan a CDMW package's item on the installed game and write it as a DMM mod."""
    from cdmw.models import ModPackageInfo
    from cdmw.services.independent_item_package import read_package, recipe_plan, stock_snapshot

    package = read_package(Path(package_path).read_bytes(), stop_event=stop_event)
    if on_log:
        on_log(f"Reading the game tables for {package.title}…")
    snapshot = stock_snapshot(Path(game_root).resolve(), stop_event=stop_event)
    plan = recipe_plan(package, snapshot, stop_event=stop_event).plan
    info = ModPackageInfo(title=package.title, description=f"{package.title}, sent to DMM by CDMW from a .cdmw package.")
    return send_plan(plan, mods, package.title, package_info=info, stop_event=stop_event)


def send_item_packages(package_paths, game_root: Path | str, mods: Path, title: str, *,
                       stop_event: Optional[threading.Event] = None,
                       on_log: Optional[Callable[[str], None]] = None,
                       on_progress: Optional[Callable[[int, int, str], None]] = None) -> DmmSendResult:
    """Compose several CDMW packages as Apply does and write them as one DMM mod.

    Separate mods would each carry their own copy of the shared tables (ItemInfo, the
    shops, the names), and DMM would keep only one of them, so the items are composed
    together first, with the identities Apply gives them.
    """
    from cdmw.core.atomic_file import atomic_publish_directory
    from cdmw.domain.archives.mutation import ArchiveAddRequest
    from cdmw.services.new_item_overlay_export import export_overlay_mod
    from cdmw.services.virtual_loader_composition import compose_packages

    paths = tuple(Path(path).resolve() for path in package_paths)
    if not paths:
        raise ValueError("Select at least one item package to send to DMM.")
    root = Path(game_root).resolve()
    folder, replaced = destination(mods, title)

    def progress(value, detail):
        raise_if_cancelled(stop_event, "Send to DMM cancelled.")
        if on_progress:
            on_progress(min(int(value), 90), 100, detail)

    if on_log:
        on_log(f"Building {len(paths)} item package(s) for the installed game. CDMW checks each package against "
               "this game version, gives every item its number and combines them into one DMM mod; "
               "this takes about half a minute per item.")
    resolved, files, flags, pathc = compose_packages(paths, (), root, stop_event=stop_event, on_log=on_log,
                                                     progress=progress)
    from cdmw.services.dmm_dlc_tables import field_operations, fold_dlc_additions
    from cdmw.services.independent_item_package import stock_snapshot
    snapshot = stock_snapshot(root, stop_event=stop_event)
    read_game = lambda path: snapshot.payload(path) if snapshot.has_entry(path) else None  # noqa: E731
    files = fold_dlc_additions(files, read_game, on_log=on_log)
    owned = {key for row in resolved.registry["items"].values() for key in row["values"].get("iteminfo", {}).values()}
    files, targets = field_operations(files, read_game, owned)
    progress(90, "Writing the DMM mod…")
    files = {path: _plain_copy(path, data) for path, data in files.items()}
    additions = tuple(ArchiveAddRequest(Path(), path, data, _storage_flags(path, data, int(flags.get(path) or 0)))
                      for path, data in sorted(files.items()))
    # DMM registers a mod's new textures itself and reports a mod's own meta/0.pathc as
    # "loose archive files not applied", so the registry stays out of the mod.
    del pathc
    composed = _ComposedMod(additions, (), _Spec(title))
    description = f"{len(paths)} item package(s) sent to DMM by CDMW."
    with tempfile.TemporaryDirectory(prefix=".cdmw-send-", dir=folder.parent.parent) as staging:
        staged = Path(staging) / folder.name
        export_overlay_mod(composed, staged, title=title, description=description, game_root=root,
                           on_log=on_log, stop_event=stop_event)
        # DMM reads every .json in a mod folder as a mod: keep CDMW's own records in
        # CDMW's history and ship only the archive, the texture registry and the mod info.
        from cdmw.core.mod_export_history import retain_dmm_history
        retain_dmm_history(staged, stop_event=stop_event)
        (staged / "README.txt").unlink(missing_ok=True)
        if targets:
            write_operations(staged, title, targets)
        raise_if_cancelled(stop_event, "Send to DMM cancelled.")
        destination(mods, title)  # Refuse a folder that appeared meanwhile.
        # Record the item identities before the mod that uses them appears, so the
        # next send gives every item the same key and saves keep their items.
        _keep_identities(root, resolved.registry)
        atomic_publish_directory(staged, folder, replace_existing=True)
    if on_progress:
        on_progress(100, 100, "Sent to DMM.")
    return DmmSendResult(folder, replaced, title)


# The flags CDMW's generated textures carry, which render through DMM.
_PLAIN_DDS_FLAGS = 0x201
_PRIVATE_COPY = re.compile(r"_r[0-9a-f]{16}(?:_[a-z]+)?\.dds$")


def _plain_copy(path: str, data: bytes) -> bytes:
    """A private copy of a partially compressed game texture, read back whole, keeps the
    compressed mip sizes in its header; the game then reads the whole mips short and
    draws noise. DMM serves the file as it is, so its header must give the real sizes."""
    if _PRIVATE_COPY.search(path) and data[:4] == b"DDS ":
        from cdmw.core.pathc_format import PathcError, with_stored_mip_sizes
        try:
            return with_stored_mip_sizes(data)
        except PathcError:
            return data
    return data


def _storage_flags(path: str, data: bytes, flags: int) -> int:
    """Private copies of game textures are complete DDS files, but carry their source's
    flags, which describe the game's partial DDS layout (top mips compressed separately,
    sizes in its registry). Through DMM those copies render as noise; store them as the
    plain textures CDMW generates."""
    if _PRIVATE_COPY.search(path) and data[:4] == b"DDS ":
        return _PLAIN_DDS_FLAGS
    return flags


def _keep_identities(root: Path, registry) -> None:
    from cdmw.core.atomic_file import atomic_write_bytes
    from cdmw.services.independent_item_install import REGISTRY_PATH, _validate_registry
    from cdmw.services.independent_item_package import canonical

    data = canonical(_validate_registry(registry))
    target = root / REGISTRY_PATH
    if target.is_file() and target.read_bytes() == data:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(target, data)


@dataclass(frozen=True)
class _Meta:
    path: str
    payload_data: bytes


@dataclass(frozen=True)
class _Spec:
    internal_name: str
    item_key: str = ""
    template_key: str = ""


@dataclass(frozen=True)
class _ComposedMod:
    """The parts of a plan the archive group writer reads, from composed files."""

    additions: tuple
    meta_files: tuple
    spec: _Spec
    patches: tuple = ()


__all__ = ["DMM_FOLDER_SETTING", "DmmSendResult", "destination", "dmm_mods_folder", "find_dmm",
           "send_item_package", "send_item_packages", "send_plan", "write_operations"]
