"""Compare mods with current game data and publish reviewed updates separately."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from cdmw.core.mod_compatibility import (
    BASELINE_FILE, COMPATIBILITY_FILE, ModCompatibility, build_label, compatibility_from_payloads, digest,
    game_identity, hash_file, payload_path, read_compatibility,
)
from cdmw.domain.archives.overlay_merge import merge_overlay_files
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.mod_merge_service import _group, _inventory, _validate_group
from cdmw.services.new_item_mod_base import mod_folder_payloads
from cdmw.services.new_item_provenance import SourceTracker


@dataclass(frozen=True)
class ModUpdatePlan:
    source: Path
    game_root: Path
    label: str
    recorded_game: dict
    current_game: dict
    status: str
    files: tuple[tuple[str, bytes, int], ...]
    comparisons: tuple[tuple[str, str], ...]
    conflicts: tuple[str, ...]
    compatibility: ModCompatibility
    new_item: dict
    inventory: tuple
    revision: object
    loose_hashes: tuple[tuple[Path, str], ...]
    source_kind: str = "folder"
    package_info: dict = field(default_factory=dict)

    @property
    def can_update(self):
        return bool(self.files) and not self.conflicts and self.status != "unknown"

    def validate(self, stop_event=None):
        self.revision.validate(stop_event)
        inventory_root = self.source / ".cdmw" if self.source_kind == "overlays" else self.source
        if _inventory(inventory_root, stop_event) != self.inventory:
            raise ValueError("The source mod changed. Check compatibility again.")
        for path, expected in self.loose_hashes:
            raise_if_cancelled(stop_event, "Mod update cancelled.")
            if hash_file(path, stop_event) != expected:
                raise ValueError(f"Source changed: {path}. Check compatibility again.")
        if game_identity(self.game_root, stop_event) != self.current_game:
            raise ValueError("The game build changed. Check compatibility again.")


def _reader_context(game_root, entries, read_entry, stop_event):
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.services.archive_overlay_install import is_cdmw_overlay_directory

    tracker = SourceTracker(read_entry or (lambda entry: read_archive_entry_data(entry)[0]))
    candidates, owned, hashes = {}, {}, []
    for entry in entries:
        directory = Path(entry.pamt_path).resolve().parent
        if not directory.is_relative_to(game_root):
            raise ValueError("An archive entry is outside the selected game folder.")
        if directory not in owned:
            owned[directory] = is_cdmw_overlay_directory(directory)
            tracker.pin_file(Path(entry.pamt_path))
        if not owned[directory]:
            candidates.setdefault(payload_path(entry.path), entry)
    for relative in ("meta/0.papgt", "meta/0.paver", "meta/0.pathc"):
        tracker.pin_file(game_root / relative)

    def loose(path):
        raise_if_cancelled(stop_event, "Mod comparison cancelled.")
        tracker.pin_file(path)
        data = path.read_bytes()
        tracker.pin_file(path)
        hashes.append((path, digest(data)))
        return data

    cache = {}
    def current(path):
        if path not in cache:
            raise_if_cancelled(stop_event, "Mod comparison cancelled.")
            if path == "meta/0.pathc":
                file = game_root / path
                cache[path] = loose(file) if file.is_file() else None
            else:
                entry = candidates.get(path)
                cache[path] = tracker.read(entry) if entry is not None else None
        return cache[path]
    return tracker, hashes, loose, current


def _compare(after, flags, evidence, current, stop_event):
    before = dict(evidence.originals) if evidence else {}
    conflicts, comparisons, output, new_baseline = [], [], {}, {}
    recorded = {row["path"]: row for row in evidence.files} if evidence else {}
    for path, data in after.items():
        if path in recorded and digest(data) != recorded[path]["sha256"]:
            conflicts.append(f"{path}: the mod payload changed since its baseline was recorded. Re-export it with CDMW.")
    if set(recorded) - set(after):
        conflicts.append("Recorded files are missing from the mod. Restore or re-export the complete package.")
    for paths in sorted({_group(path) for path in after}):
        raise_if_cancelled(stop_event, "Mod comparison cancelled.")
        if any(path not in before for path in paths):
            comparisons.extend((path, "unknown") for path in paths)
            conflicts.append(f"{paths[0]}: original data is unavailable. Re-export using the original game build before updating.")
            continue
        if any(path not in after for path in paths):
            conflicts.append(f"{paths[0]}: both files of this table are required.")
            continue
        live = {path: current(path) for path in paths}
        new_baseline.update(live)
        changed = any(before[path] != live[path] for path in paths)
        try:
            combined = merge_overlay_files({p: before[p] for p in paths}, {p: after[p] for p in paths}, live)
            _validate_group(paths, combined)
            output.update({path: data for path, data in combined.items() if data is not None})
            comparisons.extend((path, "changed" if changed else "unchanged") for path in paths)
        except (ValueError, RuntimeError, KeyError, TypeError, IndexError) as exc:
            comparisons.extend((path, "conflict") for path in paths)
            conflicts.append(f"{paths[0]}: {exc}")
    dependencies = []
    for record in evidence.dependencies if evidence else ():
        path = payload_path(record["path"])
        if path in after:
            continue
        live = current(path)
        if live is None or digest(live) != record["sha256"]:
            comparisons.append((path, "dependency_changed"))
            conflicts.append(f"{path}: a referenced source changed. Review the mod's references before rebuilding.")
        else:
            dependencies.append({"path": path, "sha256": digest(live)})
    if not after:
        conflicts.append("No supported mod payloads were found.")
    status = "unknown" if any(path not in before for path in after) or not after else (
        "conflict" if conflicts else "changed" if any(value == "changed" for _, value in comparisons) else "unchanged")
    return output, new_baseline, tuple(comparisons), tuple(conflicts), tuple(dependencies), status


def prepare_mod_update(folder, game_root, *, entries, read_entry=None, stop_event=None, on_log=None):
    source, game_root = Path(folder).expanduser().resolve(), Path(game_root).expanduser().resolve()
    if source.is_relative_to(game_root) or game_root.is_relative_to(source):
        raise ValueError("Choose a mod folder separate from the game installation.")
    inventory = _inventory(source, stop_event)
    tracker, hashes, loose, current = _reader_context(game_root, entries, read_entry, stop_event)
    if on_log:
        on_log(f"Comparing {source.name} with the current game data...")
    evidence = read_compatibility(source, stop_event=stop_event)
    for name in (COMPATIBILITY_FILE, BASELINE_FILE):
        path = source / name
        if path.is_file():
            tracker.pin_file(path)
            hashes.append((path, hash_file(path, stop_event)))
    after, flags = {}, {}
    for raw_path, item in mod_folder_payloads(source, stop_event=stop_event).items():
        path = payload_path(raw_path)
        if path == "meta/0.papgt":
            continue
        if path.startswith("meta/") and path != "meta/0.pathc":
            raise ValueError(f"Unsupported game metadata in mod: {path}")
        if item.entry is not None:
            for physical in (item.entry.pamt_path, item.entry.paz_file):
                if not Path(physical).resolve().is_relative_to(source):
                    raise ValueError("A mod archive payload is outside its package.")
            after[path] = tracker.read(item.entry)
            flags[path] = int(item.entry.flags)
        else:
            after[path], flags[path] = loose(item.path), 0
    new_item = {}
    package_info = {}
    for name in ("modinfo.json", "manifest.json"):
        metadata = source / name
        if metadata.is_file():
            if metadata.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("The mod metadata is too large.")
            record = json.loads(loose(metadata))
            if not isinstance(record, dict):
                raise ValueError("Invalid mod metadata.")
            package_info.update(record)
    manifest = source / "new-item.json"
    if manifest.is_file():
        if manifest.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("The New Item metadata is too large.")
        new_item = json.loads(loose(manifest))
        if not isinstance(new_item, dict):
            raise ValueError("Invalid New Item metadata.")
    if evidence is None:
        # Older source hashes can identify unchanged data, but cannot recover a
        # missing original after a patch. Only accept originals proven by a hash.
        before = {}
        records = new_item.get("sources", [])
        if not isinstance(records, list):
            raise ValueError("Invalid legacy source hashes.")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Invalid legacy source record.")
            path = payload_path(record.get("path", ""))
            if path in after:
                live = current(path)
                if live is not None and digest(live) == record.get("sha256"):
                    before[path] = live
        target = package_info.get("target_game")
        if not isinstance(target, dict):
            target = {"game": "Crimson Desert", "build": str(package_info.get("game_build", "") or "")}
        evidence = compatibility_from_payloads(after, before, target_game=target)
    output, baseline, comparisons, conflicts, dependencies, status = _compare(after, flags, evidence, current, stop_event)
    identity = game_identity(game_root, stop_event)
    updated = compatibility_from_payloads(output, baseline, target_game=identity, dependencies=dependencies)
    label = str(package_info.get("title") or package_info.get("name") or source.name)
    plan = ModUpdatePlan(source, game_root, label, evidence.target_game, identity, status,
        tuple((path, data, flags[path]) for path, data in sorted(output.items())), comparisons, conflicts,
        updated, new_item, inventory, tracker.capture(), tuple(hashes), package_info=package_info)
    plan.validate(stop_event)
    return plan


def prepare_installed_overlay_update(game_root, *, entries, read_entry=None, stop_event=None, on_log=None):
    """Review the installed set together so dependent layers stay together."""
    from cdmw.services.archive_overlay_manager import _load_index, _unpack_changes
    from cdmw.domain.archives.overlay_merge import legacy_texture_baseline

    root = Path(game_root).expanduser().resolve()
    tracker, hashes, loose, current = _reader_context(root, entries, read_entry, stop_event)
    tracker.pin_file(root / ".cdmw/overlays.json")
    state = _load_index(root)
    if state is None or not any(layer["active"] for layer in state["layers"]):
        raise ValueError("No installed CDMW overlay history is available. Check an exported mod folder instead.")
    inventory = _inventory(root / ".cdmw", stop_event)
    loose(root / ".cdmw/overlays.json")
    baseline, after, flags, layers, identities, items = {}, {}, {}, [], [], []
    for layer in state["layers"]:
        raise_if_cancelled(stop_event, "Overlay comparison cancelled.")
        journal = root / ".cdmw/overlays" / (layer["id"] + ".zip")
        tracker.pin_file(journal)
        hashes.append((journal, hash_file(journal, stop_event)))
        changes = _unpack_changes(root, layer, {}, stop_event)
        layers.append((layer, changes))
        for path, change in changes.items():
            baseline.setdefault(path, change["before"])
            flags[path] = change["flags"]
    after = dict(baseline)
    for layer, changes in layers:
        if layer["active"]:
            after = merge_overlay_files({p: value["before"] for p, value in changes.items()},
                                        {p: value["after"] for p, value in changes.items()}, after)
            identities.append(layer.get("target_game", {}))
            items.extend({"item_key": key} for key in layer["item_keys"])
    after = {path: data for path, data in after.items() if data is not None and data != baseline.get(path)}
    # If one table half is byte-identical, it is still required for comparison.
    for path in tuple(after):
        for pair in _group(path):
            if pair not in after and baseline.get(pair) is not None:
                after[pair] = baseline[pair]
    recorded = identities[0] if identities and all(item == identities[0] for item in identities) else {}
    evidence = compatibility_from_payloads(after, baseline, target_game=recorded)
    def underlay(path):
        value = current(path)
        if path == "meta/0.pathc" and value is not None and baseline.get(path) is not None:
            textures = {name: data for name, data in after.items() if name.endswith(".dds") and baseline.get(name) is None}
            value = legacy_texture_baseline(baseline[path], value, textures)
        return value
    output, new_baseline, comparisons, conflicts, dependencies, status = _compare(after, flags, evidence, underlay, stop_event)
    identity = game_identity(root, stop_event)
    compatibility = compatibility_from_payloads(output, new_baseline, target_game=identity, dependencies=dependencies)
    info = {"previous_items": items, "texture_registry": [path for path in after if path.endswith(".dds") and baseline.get(path) is None]}
    plan = ModUpdatePlan(root, root, "Installed overlays", recorded, identity, status,
        tuple((path, data, flags[path]) for path, data in sorted(output.items())), comparisons, conflicts,
        compatibility, info, inventory, tracker.capture(), tuple(hashes), "overlays")
    plan.validate(stop_event)
    return plan


def export_updated_mod(plan: ModUpdatePlan, destination, *, title="", stop_event=None, on_log=None):
    from cdmw.domain.archives.mutation import ArchiveAddRequest
    from cdmw.services.archive_overlay_package_service import export_archive_overlay_package
    from cdmw.services.new_item_service import NewItemExportResult, _publish_package_atomically

    if not plan.can_update:
        raise ValueError("Resolve the compatibility conflicts before writing an updated mod.")
    root = Path(destination).expanduser().resolve()
    def validate():
        for source in (plan.source, plan.game_root):
            if root.is_relative_to(source) or source.is_relative_to(root):
                raise ValueError("Choose an output folder separate from the game and the original mod.")
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise ValueError("Choose a new or empty output folder. The original mod is preserved.")
        plan.validate(stop_event)
    validate()
    title = str(title).strip() or plan.label + " - updated"
    def write(staging):
        additions = [ArchiveAddRequest(plan.game_root / "0.pamt", path, data, flags)
                     for path, data, flags in plan.files if path != "meta/0.pathc"]
        metadata = [(path, data) for path, data, _ in plan.files if path == "meta/0.pathc"]
        result = export_archive_overlay_package((), additions, package_root=staging,
            game_root=plan.game_root, metadata_files=metadata, compatibility=plan.compatibility,
            stop_event=stop_event, on_log=on_log)
        manifest = {"format": "v1", "schema_version": 1, "kind": "archive_override_mod",
            "name": title, "title": title, "game": "Crimson Desert",
            "version": str(plan.package_info.get("version") or "1.0.0"),
            "author": str(plan.package_info.get("author") or ""),
            "description": str(plan.package_info.get("description") or ""),
            "generator": "Crimson Desert Mod Workbench - Update Mod", "files_dir": ".",
            "manager_targets": ["dmm"], "manager_target_labels": ["Definitive Mod Manager"],
            "structure": "archive_group", "archive_group": result.group, "file_count": result.file_count,
            "overrides": list(result.paths), "target_game": plan.current_game,
            "updated_from": {"name": plan.label, "target_game": plan.recorded_game}}
        for name in ("manifest.json", "modinfo.json"):
            (staging / name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        info = dict(plan.new_item)
        info["sources"] = [{"path": row["path"], "sha256": row["baseline_sha256"]}
                           for row in plan.compatibility.files if row["baseline_sha256"]]
        (staging / "new-item.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "README.txt").write_text(title + "\n\nBuilt against: " + build_label(plan.current_game) +
            "\nEnable this updated DMM package in place of the original mod.\n"
            "Data comparison passed; this is not an in-game compatibility test.\n", encoding="utf-8")
        return NewItemExportResult(staging, "DMM", result.paths, (),
            ("manifest.json", "modinfo.json", "new-item.json", "README.txt", *result.metadata_files))
    return _publish_package_atomically(root, write, stop_event=stop_event, before_publish=validate)


__all__ = ["ModUpdatePlan", "prepare_mod_update", "prepare_installed_overlay_update", "export_updated_mod"]
