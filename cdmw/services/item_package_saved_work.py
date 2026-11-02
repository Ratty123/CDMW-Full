"""Item packages in Drafts & Mods: their index and the Create New Item drafts kept with them.

Create New Item lists each .cdmw it writes in ``item_packages.json`` beside the
Mesh Editor drafts, with a copy of the draft it was written from in a folder of
its own. A package written again from that draft keeps its row, name, notes and
project. A package listed by hand (made earlier, or by someone else) has no draft;
Continue Editing then rebuilds the settings from the package's own recipe.

This module never writes, moves or deletes a .cdmw file.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from cdmw.constants import PACKAGE_EXTENSIONS
from cdmw.services.atomic_file_service import atomic_write_bytes, atomic_write_text

ITEM_PACKAGES_INDEX_NAME = "item_packages.json"
ITEM_PACKAGES_INDEX_FORMAT = "cdmw_item_packages_v1"
ITEM_DRAFT_NAME = "new_item_draft.json"
ITEM_DRAFT_DIR_PREFIX = "item-"
MAX_LISTED_PACKAGES = 2000


def item_packages_index_path(draft_root: Path | str) -> Path:
    return Path(draft_root).expanduser().resolve() / ITEM_PACKAGES_INDEX_NAME


def _read_json(path: Path) -> Mapping[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, Mapping) else None


def read_item_package_index(draft_root: Path | str) -> list[dict[str, object]]:
    payload = _read_json(item_packages_index_path(draft_root))
    if payload is None or payload.get("format") != ITEM_PACKAGES_INDEX_FORMAT:
        return []
    return [dict(item) for item in payload.get("packages") or ()
            if isinstance(item, Mapping) and str(item.get("id") or "") and str(item.get("package_path") or "")]


def write_item_package_index(draft_root: Path | str, records: Sequence[Mapping[str, object]]) -> None:
    path = item_packages_index_path(draft_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"format": ITEM_PACKAGES_INDEX_FORMAT, "packages": list(records)},
                                       indent=2, sort_keys=True))


def _same_file(left: object, right: Path) -> bool:
    try:
        return Path(str(left or "")).expanduser().resolve() == right
    except OSError:
        return False


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _draft_folder(root: Path, record: Mapping[str, object]) -> Path | None:
    name = str(record.get("draft_dir") or "")
    if not name or "/" in name or "\\" in name:
        return None
    folder = (root / name).resolve()
    return folder if folder.parent == root and _inside(root, folder) else None


def item_package_draft_path(draft_root: Path | str, record: Mapping[str, object]) -> Path | None:
    """The record's saved draft file, when it has one inside the draft root."""

    root = Path(draft_root).expanduser().resolve()
    folder = _draft_folder(root, record)
    if folder is None:
        return None
    path = folder / ITEM_DRAFT_NAME
    return path if path.is_file() else None


def _slug(text: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in str(text or ""))
    return "-".join(part for part in cleaned.split("-") if part)[:40] or "item"


def register_item_package(
    draft_root: Path | str,
    *,
    package_path: Path | str,
    identity: str,
    title: str,
    draft_bytes: bytes | None,
    template_name: str = "",
) -> dict[str, object]:
    """List a package Create New Item has just written, keeping the draft it came from.

    Writing the same file again replaces its draft and counts another revision; the
    row keeps the name, notes and project the user gave it.
    """

    from cdmw.services.mesh_saved_work_service import SAVED_WORK_LOCK

    root = Path(draft_root).expanduser().resolve()
    package = Path(package_path).expanduser().resolve()
    with SAVED_WORK_LOCK:
        records = read_item_package_index(root)
        record = next((item for item in records if _same_file(item.get("package_path"), package)), None)
        if record is None:
            record = {"id": uuid4().hex, "display_name": package.stem, "project_id": "", "notes": "",
                      "revision": 0, "draft_dir": ""}
            records.append(record)
        folder = _draft_folder(root, record)
        if draft_bytes is not None:
            if folder is None:
                folder = root / f"{ITEM_DRAFT_DIR_PREFIX}{_slug(package.stem)}-{str(record['id'])[:8]}"
            folder.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(folder / ITEM_DRAFT_NAME, draft_bytes)
            record["draft_dir"] = folder.name
        elif folder is not None:
            # The draft no longer describes this package.
            shutil.rmtree(folder, ignore_errors=True)
            record["draft_dir"] = ""
        record.update({
            "package_path": str(package),
            "identity": str(identity or ""),
            "title": str(title or ""),
            "template_name": str(template_name or record.get("template_name") or ""),
            "built_at": time.time(),
            "revision": max(0, int(record.get("revision") or 0)) + 1,
        })
        write_item_package_index(root, records)
        return dict(record)


def add_item_package_file(draft_root: Path | str, package_path: Path | str, *, project_id: str = "") -> dict[str, object]:
    """List a .cdmw made before Drafts & Mods kept item packages, or by someone else."""

    from cdmw.services.independent_item_package import read_package
    from cdmw.services.mesh_saved_work_service import SAVED_WORK_LOCK

    root = Path(draft_root).expanduser().resolve()
    package = Path(package_path).expanduser().resolve()
    if package.suffix.lower() not in PACKAGE_EXTENSIONS or not package.is_file():
        raise ValueError("Choose an existing .cdmw item package.")
    with SAVED_WORK_LOCK:
        if any(_same_file(item.get("package_path"), package) for item in read_item_package_index(root)):
            raise ValueError("This item package is already in the list.")
    loaded = read_package(package)
    record = {
        "id": uuid4().hex,
        "display_name": package.stem,
        "package_path": str(package),
        "identity": str(loaded.identity),
        "title": str(loaded.title),
        "template_name": "",
        "built_at": package.stat().st_mtime,
        "revision": 0,
        "draft_dir": "",
        "project_id": str(project_id or ""),
        "notes": "",
    }
    with SAVED_WORK_LOCK:
        records = read_item_package_index(root)
        if any(_same_file(item.get("package_path"), package) for item in records):
            raise ValueError("This item package is already in the list.")
        records.append(record)
        write_item_package_index(root, records)
    return record


def update_item_package_details(draft_root: Path | str, row_id: str, updates: Mapping[str, object]) -> None:
    from cdmw.services.mesh_saved_work_service import SAVED_WORK_LOCK

    root = Path(draft_root).expanduser().resolve()
    with SAVED_WORK_LOCK:
        records = read_item_package_index(root)
        for record in records:
            if str(record.get("id") or "") == str(row_id):
                record.update(updates)
                break
        else:
            raise ValueError("This item package is no longer in the list.")
        write_item_package_index(root, records)


def remove_item_package_from_list(draft_root: Path | str, row_id: str) -> None:
    """Forget a package and its saved draft. The .cdmw file is kept."""

    from cdmw.services.mesh_saved_work_service import SAVED_WORK_LOCK

    root = Path(draft_root).expanduser().resolve()
    with SAVED_WORK_LOCK:
        records = read_item_package_index(root)
        removed = [record for record in records if str(record.get("id") or "") == str(row_id)]
        if not removed:
            raise ValueError("This item package is no longer in the list.")
        write_item_package_index(root, [record for record in records if record not in removed])
    for record in removed:
        folder = _draft_folder(root, record)
        if folder is not None and (folder / ITEM_DRAFT_NAME).is_file():
            shutil.rmtree(folder)


def item_package_record(draft_root: Path | str, row_id: str) -> dict[str, object] | None:
    return next((record for record in read_item_package_index(draft_root)
                 if str(record.get("id") or "") == str(row_id)), None)


@dataclass(frozen=True)
class ItemPackageSource:
    """A package read for Continue Editing, off the UI thread."""

    package_path: Path
    identity: str
    title: str
    #: the item's recipe (``NewItemSpec``), with symbolic identities
    spec: object
    #: the finished models the package was written with (``ModelFiles``)
    model: object = None
    variant_models: Mapping[tuple, object] = field(default_factory=dict)
    icon_data: bytes | None = None
    #: the Create New Item draft kept when the package was written; None for a listed package
    draft_bytes: bytes | None = None


def read_item_package_source(draft_root: Path | str, row_id: str, *, stop_event=None) -> ItemPackageSource:
    """Read a listed package and its kept draft; refuse one Create New Item did not author."""

    from cdmw.domain.new_item.independent import IndependentItemError
    from cdmw.services.independent_item_package import REBUILT_MODULES, read_package, unpack_recipe
    from cdmw.services.independent_mod_package import has_legacy_item

    record = item_package_record(draft_root, row_id)
    if record is None:
        raise ValueError("This item package is no longer in the list.")
    package_path = Path(str(record.get("package_path") or ""))
    if not package_path.is_file():
        raise ValueError(f"The item package no longer exists: {package_path}")
    package = read_package(package_path, stop_event=stop_event)
    modules = {module["type"] for module in getattr(package, "manifest", {"modules": ()})["modules"]}
    if not has_legacy_item(package) or modules - REBUILT_MODULES:
        extra = ", ".join(sorted(modules - REBUILT_MODULES)) or "no new item"
        raise ValueError(f"{package_path.name} was not written by Create New Item ({extra}), so it cannot be "
                         "continued there. Edit it with the tool that made it.")
    try:
        spec, model, variants, icon = unpack_recipe(package)
    except IndependentItemError as exc:
        raise ValueError(f"{package_path.name} cannot be read: {exc}") from exc
    draft_path = item_package_draft_path(draft_root, record)
    return ItemPackageSource(package_path, str(package.identity), str(package.title), spec, model, dict(variants),
                             icon, draft_path.read_bytes() if draft_path is not None else None)


__all__ = [
    "ITEM_DRAFT_NAME",
    "ITEM_PACKAGES_INDEX_FORMAT",
    "ITEM_PACKAGES_INDEX_NAME",
    "ItemPackageSource",
    "add_item_package_file",
    "item_package_draft_path",
    "item_package_record",
    "read_item_package_source",
    "read_item_package_index",
    "register_item_package",
    "remove_item_package_from_list",
    "update_item_package_details",
    "write_item_package_index",
]
