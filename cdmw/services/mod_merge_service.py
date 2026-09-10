"""Review and export a composition of mod folders without installing anything.

Structured changes use recorded source hashes to find their original tables in
the game or another selected package. Conflicting or unproven changes block the
whole export. Inputs and their game baseline remain pinned until publication.
"""
from __future__ import annotations

import hashlib
import json
import struct
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable
from xml.etree.ElementTree import ParseError

from cdmw.domain.archives.overlay_merge import _table, merge_overlay_files
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry
from cdmw.services.new_item_mod_base import mod_folder_payloads
from cdmw.services.new_item_provenance import SourceRevision, SourceTracker


@dataclass(frozen=True)
class ModMergePlan:
    folders: tuple[Path, ...]
    game_root: Path
    files: tuple[tuple[str, bytes, int], ...]
    conflicts: tuple[str, ...]
    sources: tuple[tuple[str, str], ...]
    items: tuple[dict, ...]
    texture_paths: tuple[str, ...]
    generation: str
    revision: SourceRevision
    inventories: tuple[tuple[Path, tuple], ...]
    loose_hashes: tuple[tuple[Path, str], ...]
    compatibility: object = None

    def validate(self, stop_event=None):
        self.revision.validate(stop_event)
        for folder, inventory in self.inventories:
            if _inventory(folder, stop_event) != inventory:
                raise ValueError(f"Mod folder changed: {folder}. Check compatibility again.")
        for path, digest in self.loose_hashes:
            raise_if_cancelled(stop_event, "Mod merge cancelled.")
            if _digest(path.read_bytes()) != digest:
                raise ValueError(f"Source changed: {path}. Check compatibility again.")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _path(value):
    value = str(value).replace("\\", "/").lower()
    parts = PurePosixPath(value).parts
    if not parts or value.startswith("/") or any(p in ("..", ".") or ":" in p for p in parts):
        raise ValueError(f"Invalid mod file path: {value}")
    return PurePosixPath(*parts).as_posix()


def _inventory(folder, stop_event):
    if not folder.is_dir():
        raise ValueError(f"Mod folder does not exist: {folder}")
    result = []
    for path in folder.rglob("*"):
        raise_if_cancelled(stop_event, "Mod merge cancelled.")
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError(f"Linked files or folders are not supported in a mod: {path}")
        if path.is_file():
            stat = path.stat()
            result.append((path.relative_to(folder).as_posix(), stat.st_size, stat.st_mtime_ns))
    return tuple(sorted(result))


def _group(path):
    for body, head in ((".pabgb", ".pabgh"), (".staticinfobody", ".staticinfoheader")):
        for suffix in (body, head):
            if path.endswith(suffix):
                stem = path[:-len(suffix)]
                return stem + body, stem + head
    return (path,)


def _validate_group(paths, files):
    if len(paths) == 2:
        _table(files[paths[0]], files[paths[1]])
    elif paths[0].endswith(".paloc"):
        from cdmw.core.paloc_format import parse_paloc
        parse_paloc(files[paths[0]])
    elif paths[0].endswith(".pappt"):
        from cdmw.core.pappt_format import parse_pappt
        parse_pappt(files[paths[0]])
    elif paths[0] == "ui/xml/texture/cd_item_icon.xml":
        from xml.etree.ElementTree import fromstring
        fromstring(files[paths[0]])


def _items(manifest):
    previous = manifest.get("previous_items", [])
    if not isinstance(previous, list) or any(not isinstance(item, dict) for item in previous):
        raise ValueError("Invalid previous_items in new-item.json.")
    return [*previous, *([dict(manifest, previous_items=[])] if manifest.get("item_key") else [])]


def prepare_mod_merge(
    folders: Iterable[Path], game_root: Path, *, entries: Iterable[ArchiveEntry],
    read_entry: Callable | None = None, on_log=None, stop_event: threading.Event | None = None,
) -> ModMergePlan:
    from cdmw.core.archive_extraction import read_archive_entry_data

    roots = tuple(Path(folder).expanduser().resolve() for folder in folders)
    game_root = Path(game_root).expanduser().resolve()
    if len(roots) < 2 or len(set(roots)) != len(roots):
        raise ValueError("Select at least two different mod folders.")
    for index, folder in enumerate(roots):
        if game_root.is_relative_to(folder):
            raise ValueError("Select individual mod folders, not the game folder or its parent.")
        if any(folder.is_relative_to(other) or other.is_relative_to(folder) for other in roots[:index]):
            raise ValueError("Selected mod folders must not contain one another.")
    tracker = SourceTracker(read_entry or (lambda entry: read_archive_entry_data(entry)[0]))
    loose_hashes, inventories, mods, conflicts = [], [], [], []
    candidates = defaultdict(list)
    for entry in entries:
        candidates[_path(entry.path)].append(entry)
    game_cache = {}

    def loose(path):
        tracker.pin_file(path)
        data = path.read_bytes()
        tracker.pin_file(path)
        loose_hashes.append((path, _digest(data)))
        return data

    def game_candidates(path):
        if path not in game_cache:
            if path == "meta/0.pathc":
                source = game_root / path
                game_cache[path] = [loose(source)] if source.is_file() else []
            else:
                game_cache[path] = [tracker.read(entry) for entry in candidates.get(path, ())]
        return game_cache[path]

    for relative in ("meta/0.papgt", "meta/0.paver"):
        tracker.pin_file(game_root / relative)
    for folder in roots:
        if on_log:
            on_log(f"Reading mod {folder.name}...")
        inventories.append((folder, _inventory(folder, stop_event)))
        manifest_file = folder / "new-item.json"
        manifest = {}
        if manifest_file.is_file():
            if manifest_file.stat().st_size > 8 * 1024 * 1024:
                raise ValueError(f"New Item manifest is too large: {manifest_file}")
            manifest = json.loads(loose(manifest_file))
            if not isinstance(manifest, dict):
                raise ValueError(f"Invalid New Item manifest: {manifest_file}")
        data, flags = {}, {}
        for virtual, payload in mod_folder_payloads(folder, stop_event=stop_event).items():
            raise_if_cancelled(stop_event, "Mod merge cancelled.")
            path = _path(virtual)
            if path == "meta/0.papgt":
                continue  # The combined package receives one newly composed mount list.
            if path.startswith("meta/") and path != "meta/0.pathc":
                conflicts.append(f"{folder.name}: unsupported package metadata {path}.")
                continue
            if payload.entry is not None:
                for physical in (payload.entry.pamt_path, payload.entry.paz_file):
                    if not Path(physical).resolve().is_relative_to(folder):
                        raise ValueError(f"Archive payload escapes the selected mod: {physical}")
                data[path] = tracker.read(payload.entry)
                flags[path] = int(payload.entry.flags)
            else:
                data[path] = loose(payload.path)
                flags[path] = 0
        if not data:
            conflicts.append(f"{folder.name}: no supported mod payloads were found.")
        records = manifest.get("sources", [])
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            raise ValueError(f"Invalid source records in {manifest_file}.")
        hashes = {_path(record["path"]): str(record["sha256"]) for record in records
                  if "path" in record and "sha256" in record}
        label = folder.name if sum(root.name == folder.name for root in roots) == 1 else str(folder)
        mods.append((label, data, flags, hashes, manifest))

    output, source_hashes, owned_items, textures = {}, {}, [], set()
    baseline_payloads = {}
    generations = {str(mod[4].get("generation")) for mod in mods if mod[4].get("generation")}
    if len(generations) > 1:
        conflicts.append("The selected mods use different game table generations. Rebuild them against the same game version.")
    for name, _data, _flags, _hashes, manifest in mods:
        for item in _items(manifest):
            if item not in owned_items:
                owned_items.append(item)
        declared = [manifest, *_items(manifest)]
        for item in declared:
            values = item.get("texture_registry", [])
            if not isinstance(values, list):
                raise ValueError(f"Invalid texture registry ownership in {name}.")
            textures.update(_path(path) for path in values)
    all_paths = set().union(*(set(mod[1]) for mod in mods))
    groups = sorted({_group(path) for path in all_paths if path != "meta/0.pathc"})
    for paths in groups:
        raise_if_cancelled(stop_event, "Mod merge cancelled.")
        participants = [mod for mod in mods if any(path in mod[1] for path in paths)]
        structured = len(paths) == 2 or paths[0].endswith((".paloc", ".pappt")) or paths[0] == "ui/xml/texture/cd_item_icon.xml"
        try:
            for name, data, _flags, _hashes, _manifest in participants:
                if any(path not in data for path in paths):
                    raise ValueError(f"{name}: incomplete table pair {paths[0]}.")
                _validate_group(paths, data)
            bases, common = {}, {}
            for path in paths:
                versions = {_digest(mod[1][path]): mod[1][path] for mod in participants}
                for value in game_candidates(path):
                    versions.setdefault(_digest(value), value)
                parents = defaultdict(set)
                roots_for_path = set()
                for name, data, _flags, hashes, _manifest in participants:
                    digest = hashes.get(path)
                    if digest is None and structured and candidates.get(path):
                        raise ValueError(f"{name}: no recorded baseline for {path}. Re-export this item with CDMW.")
                    if digest is not None and digest not in versions:
                        raise ValueError(f"{name}: the recorded baseline for {path} is unavailable. Use the matching game version and include any required base mod.")
                    before = versions[digest] if digest is not None else None
                    bases.setdefault(name, {})[path] = before
                    parents[_digest(data[path])].add(digest)
                resolved = {}
                def ancestors(digest, visiting):
                    if digest in visiting:
                        raise ValueError(f"Cyclic baseline history for {path}.")
                    if digest not in resolved:
                        older = parents.get(digest, set()) - {digest}
                        resolved[digest] = set().union(*(ancestors(value, visiting | {digest}) for value in older)) if older else {digest}
                    return resolved[digest]
                for _name, _data, _flags, hashes, _manifest in participants:
                    roots_for_path.update(ancestors(hashes.get(path), set()))
                if len(roots_for_path) != 1:
                    raise ValueError(f"Different source versions for {path}. Rebuild these mods against the same baseline.")
                digest = roots_for_path.pop()
                common[path] = versions[digest] if digest is not None else None
                baseline_payloads[path] = common[path]
                if digest is not None:
                    source_hashes[path] = digest
            current = dict(common)
            for name, data, _flags, _hashes, _manifest in participants:
                try:
                    current = merge_overlay_files(bases[name], {path: data[path] for path in paths}, current)
                except (ValueError, RuntimeError) as error:
                    raise ValueError(f"{name}: {error}") from error
            _validate_group(paths, current)
            for path in paths:
                if current[path] is not None:
                    output[path] = (current[path], participants[-1][2][path])
        except (ValueError, RuntimeError, KeyError, IndexError, struct.error, ParseError) as error:
            conflicts.append(f"{paths[0]}: {error}")

    if "meta/0.pathc" in all_paths:
        from cdmw.domain.archives.mod_merge import merge_mod_texture_registry
        try:
            registry = game_candidates("meta/0.pathc")
            if not registry:
                raise ValueError("The game texture registry is unavailable.")
            current = registry[0]
            for name, data, _flags, _hashes, manifest in mods:
                if "meta/0.pathc" not in data:
                    continue
                owned = set()
                for item in (manifest, *_items(manifest)):
                    owned.update(_path(path) for path in item.get("texture_registry", []))
                if not owned:
                    raise ValueError(f"{name}: texture registry changes have no CDMW ownership information.")
                current = merge_mod_texture_registry(registry[0], current, data["meta/0.pathc"], owned, data)
            output["meta/0.pathc"] = (current, 0)
            baseline_payloads["meta/0.pathc"] = registry[0]
        except (ValueError, RuntimeError) as error:
            conflicts.append(f"meta/0.pathc: {error}")
    from cdmw.core.mod_compatibility import compatibility_from_payloads, game_identity, read_compatibility
    dependencies = {}
    for folder, mod in zip(roots, mods):
        evidence = read_compatibility(folder, stop_event=stop_event)
        for record in evidence.dependencies if evidence else mod[4].get("sources", ()):
            path = _path(record["path"])
            if path in output:
                continue
            values = game_candidates(path)
            if not values or _digest(values[0]) != record["sha256"]:
                conflicts.append(f"{folder.name}: referenced source changed or is missing: {path}. Check this mod for game updates.")
            elif path in dependencies and dependencies[path] != record["sha256"]:
                conflicts.append(f"The selected mods reference different source versions of {path}.")
            else:
                dependencies[path] = record["sha256"]
    compatibility = compatibility_from_payloads({path: data for path, (data, _flags) in output.items()},
        baseline_payloads, target_game=game_identity(game_root, stop_event),
        dependencies=tuple({"path": path, "sha256": value} for path, value in sorted(dependencies.items())))
    result = ModMergePlan(roots, game_root,
        tuple((path, data, flags) for path, (data, flags) in sorted(output.items())), tuple(conflicts),
        tuple(sorted(source_hashes.items())), tuple(owned_items), tuple(sorted(textures)),
        next(iter(generations), ""), tracker.capture(), tuple(inventories), tuple(loose_hashes), compatibility)
    result.validate(stop_event)
    return result


def export_merged_mod(plan: ModMergePlan, destination: Path, *, title="Combined mod", on_log=None, stop_event=None):
    from cdmw.domain.archives.mutation import ArchiveAddRequest
    from cdmw.services.archive_overlay_package_service import export_archive_overlay_package
    from cdmw.services.new_item_service import NewItemExportResult, _publish_package_atomically

    if plan.conflicts:
        raise ValueError("Resolve the reported conflicts before writing a merged mod.")
    root = Path(destination).expanduser().resolve()
    def validate():
        for source in (*plan.folders, plan.game_root):
            if root.is_relative_to(source) or source.is_relative_to(root):
                raise ValueError("Choose an output folder separate from the game and all selected mods.")
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise ValueError("Choose a new or empty output folder. Existing mod packages are preserved.")
        plan.validate(stop_event)
    validate()
    title = str(title).strip() or "Combined mod"
    def write(staging):
        additions, metadata = [], []
        for path, data, flags in plan.files:
            if path == "meta/0.pathc":
                metadata.append((path, data))
            else:
                additions.append(ArchiveAddRequest(plan.game_root / "0.pamt", path, data, flags))
        result = export_archive_overlay_package((), additions, package_root=staging,
            game_root=plan.game_root, metadata_files=metadata, on_log=on_log, stop_event=stop_event,
            compatibility=plan.compatibility)
        manifest = {"format": "v1", "schema_version": 1, "kind": "archive_override_mod",
            "name": title, "title": title, "game": "Crimson Desert", "version": "1.0.0",
            "description": "Combined from: " + ", ".join(folder.name for folder in plan.folders),
            "generator": "Crimson Desert Mod Workbench - Merge Mods", "files_dir": ".",
            "manager_targets": ["dmm"], "manager_target_labels": ["Definitive Mod Manager"],
            "structure": "archive_group", "archive_group": result.group,
            "file_count": result.file_count, "overrides": list(result.paths), "target_game": result.target_game}
        for name in ("manifest.json", "modinfo.json"):
            (staging / name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        info = {"generation": plan.generation, "previous_items": list(plan.items),
            "texture_registry": list(plan.texture_paths),
            "sources": [{"path": path, "sha256": digest} for path, digest in plan.sources]}
        (staging / "new-item.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "README.txt").write_text(title + "\n\n" + manifest["description"] +
            "\n\nEnable this combined package in DMM instead of the original selected packages.\n", encoding="utf-8")
        return NewItemExportResult(staging, "DMM", result.paths, (),
            ("manifest.json", "modinfo.json", "new-item.json", "README.txt", *result.metadata_files))
    return _publish_package_atomically(root, write, stop_event=stop_event, before_publish=validate)
