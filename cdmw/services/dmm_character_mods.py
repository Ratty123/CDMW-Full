"""Read the installed character-mod library; never mount or alter a DMM mod.

Version labels are descriptive. Actual file witnesses, including directories,
invalidate a selection when an updater changes, adds, removes or replaces files.
Fit and Module are separate sources, never an inferred combined load order.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.dmm_send import dmm_mods_folder, find_dmm
from cdmw.services.new_item_provenance import SourceRevision, StaleNewItemSource

_TITLES = {
    "character creator enhanced - anywhere": "creator",
    "character creator enhanced": "creator",
    "female armor fit": "fit",
    "female armor module": "module",
    "female armor fit dyes": "fit-dyes",
    "female armor module dyes": "module-dyes",
}
_COMMON = "character/descriptors/conditionalpartprefab/conditionalpartprefab_common.xml"
_PAPPT = "character/bin__/partprefabtable.pappt"


def normalized(path):
    value = str(path).replace("\\", "/").strip().casefold()
    parts = PurePosixPath(value).parts
    if not parts or value.startswith("/") or ":" in value or any(p in {".", ".."} for p in parts):
        raise ValueError("Invalid relative character-mod path.")
    return "/".join(parts)


def _stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _read(path, pins, hashes, *, limit=8 * 1024 * 1024):
    before = _stamp(path)
    if path.is_symlink() or before[0] > limit:
        raise ValueError(f"Unsupported or oversized character-mod file: {path.name}")
    data = path.read_bytes()
    if _stamp(path) != before or pins.setdefault(path, before) != before:
        raise StaleNewItemSource("The DMM library changed while it was being read. Refresh it.")
    hashes[path] = hashlib.sha256(data).hexdigest()
    return data


@dataclass(frozen=True)
class CharacterMod:
    kind: str
    folder: Path
    identifier: str
    title: str
    version: str
    selected: bool
    files: tuple[tuple[str, Path], ...]
    replacements: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class DmmCharacterLibrary:
    install: Path
    mods_folder: Path
    game_folder: Path | None
    mods: tuple[CharacterMod, ...]
    equip_all_selected: bool
    creator_asi_selected: bool
    revision: SourceRevision

    @property
    def identity(self):
        return self.revision.files, self.revision.indexes

    def mod(self, identifier):
        return next(mod for mod in self.mods if mod.identifier == identifier)

    def sources(self, identifier):
        """A chosen collection plus Creator dependencies; no Fit/Module mixing."""
        selected = self.mod(identifier)
        creators = [mod for mod in self.mods if mod.kind == "creator"]
        if len(creators) > 1:
            raise ValueError("Several Character Creator installations were found. Keep one in the DMM library.")
        files = dict(creators[0].files) if creators else {}
        files.update(selected.files)
        return files


def _replacement_rules(data, kind):
    """Read only the declared female-body Match rules; don't emulate the ASI."""
    text = data.decode("utf-8-sig")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I):
        raise ValueError("Unsupported character-mod XML declaration.")
    text = re.sub(r"^\s*<\?xml[^?]*\?>", "", text)
    root = ET.fromstring("<root>" + text + "</root>")
    group = "FemaleFitBodies" if kind == "fit" else "FemaleArmorModuleBodies"
    if not any(el.get("Name") == group for el in root.findall("PartPrefabGroup")):
        raise ValueError("The installed armor mod uses an unrecognized body-selection format.")
    result = []
    for condition in root.findall("Condition"):
        for rule in condition:
            if rule.get("MatchPartPrefabGroup") != group:
                continue
            if (condition.tag != "Condition" or set(condition.attrib) != {"SourcePartPrefab"}
                    or rule.tag != "If" or rule.get("Type") != "Match"
                    or set(rule.attrib) != {"Type", "TargetPartPrefab", "MatchPartPrefabGroup"}):
                raise ValueError("The installed armor mod has unsupported replacement conditions.")
            source, target = condition.get("SourcePartPrefab"), rule.get("TargetPartPrefab")
            if not all(re.fullmatch(r"[a-zA-Z0-9_]+", name or "") for name in (source, target)):
                raise ValueError("Invalid character-mod prefab name.")
            result.append((source.casefold(), target.casefold()))
    if not result:
        raise ValueError("No supported female armor replacements were found.")
    return tuple(result)


def scan_character_library(saved="", *, stop_event=None):
    raise_if_cancelled(stop_event)
    install = Path(saved) if saved else find_dmm()
    if install is None or not (install / "DMM.exe").is_file():
        raise ValueError("DMM was not found. Choose the folder containing DMM.exe.")
    install = install.resolve()
    pins, hashes = {}, {}
    config = json.loads(_read(install / "config.json", pins, hashes).decode("utf-8-sig"))
    if not isinstance(config, dict) or config.get("configVersion", 1) != 1:
        raise ValueError("This DMM configuration format is not supported.")
    mods_folder = dmm_mods_folder(install).resolve()
    browser = config.get("activeBrowserMods", [])
    operations = config.get("activeMods", [])
    asi = config.get("activeAsiMods", [])
    if (not isinstance(browser, list) or not all(isinstance(v, str) for v in browser)
            or not isinstance(operations, list) or not all(isinstance(v, dict) for v in operations)
            or not isinstance(asi, list) or not all(isinstance(v, str) for v in asi)):
        raise ValueError("DMM's selected-mod list could not be read.")
    selected = {normalized(v) for v in browser}
    mods, equip_all = [], False
    # DMM extracts one imported top-level folder per library entry. Search metadata
    # within two wrapper levels; don't recursively inventory unrelated mods.
    manifests = []
    for pattern in ("*/mod.json", "*/*/mod.json", "*/*/*/mod.json"):
        manifests.extend(mods_folder.glob(pattern))
    for manifest in sorted(set(manifests)):
        raise_if_cancelled(stop_event)
        if not manifest.resolve().is_relative_to(mods_folder):
            raise ValueError("A DMM mod points outside its library.")
        metadata_pins, metadata_hashes = {}, {}
        try:
            metadata = json.loads(_read(manifest, metadata_pins, metadata_hashes).decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError):
            continue  # Unrelated managers' metadata is not a character-mod source.
        info = metadata.get("modinfo", {}) if isinstance(metadata, dict) else {}
        if not isinstance(info, dict):
            continue
        kind = _TITLES.get(str(info.get("title", "")).casefold())
        if kind is None:
            continue
        pins.update(metadata_pins)
        hashes.update(metadata_hashes)
        folder = manifest.parent
        if folder.is_symlink() or folder.is_junction():
            raise ValueError("Linked files in character mods are not supported.")
        identifier = normalized(folder.relative_to(mods_folder).as_posix())
        files = {}
        for parent, directories, filenames in os.walk(folder, followlinks=False):
            raise_if_cancelled(stop_event)
            parent = Path(parent)
            pins[parent] = _stamp(parent)
            if len(pins) > 50000:
                raise ValueError("Character-mod library exceeds the file limit.")
            for name in (*directories, *filenames):
                path = parent / name
                if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(folder.resolve()):
                    raise ValueError("Linked files in character mods are not supported.")
            for name in sorted(filenames):
                path = parent / name
                pins[path] = _stamp(path)
                if len(pins) > 50000:
                    raise ValueError("Character-mod library exceeds the file limit.")
                parts = path.relative_to(folder).parts
                # Only a game tree at the root or under a numbered archive group.
                positions = [i for i, part in enumerate(parts) if part.casefold() == "character"
                             and (i == 0 or parts[i - 1].isdigit())]
                if not positions:
                    continue
                key = normalized("/".join(parts[positions[0]:]))
                if key in files:
                    raise ValueError(f"Ambiguous character-mod source: {key}")
                files[key] = path
        rules = ()
        if kind in {"fit", "module"}:
            if _COMMON not in files:
                raise ValueError("The installed armor mod has no supported replacement descriptor.")
            rules = _replacement_rules(_read(files[_COMMON], pins, hashes), kind)
        mods.append(CharacterMod(kind, folder, identifier, str(info["title"]),
                                 str(info.get("version", "?")),
                                 any(p == identifier or p.startswith(identifier + "/") for p in selected),
                                 tuple(sorted(files.items())), rules))
        if kind == "creator":
            equip_path = identifier + "/equip all armor.json"
            equip_all |= any(normalized(op.get("fileName", "missing")) == equip_path
                             and op.get("disabledIndices") == [] for op in operations)
    game = config.get("gamePath")
    game_folder = (Path(game) if Path(game).is_absolute() else install / game) if isinstance(game, str) and game else None
    revision = SourceRevision((), tuple(sorted(pins.items())), lambda _entry: b"", tuple(sorted(hashes.items())))
    revision.validate(stop_event)
    return DmmCharacterLibrary(install, mods_folder, game_folder, tuple(mods), equip_all,
                               "charactercreator" in {Path(v).stem.casefold() for v in asi}, revision)


@dataclass(frozen=True)
class CharacterModelCatalogue:
    paths: tuple[str, ...]
    unresolved: tuple[str, ...] = ()
    item_names: tuple[tuple[str, tuple[str, ...]], ...] = ()


def character_model_paths(library, identifier, snapshot=None, *, stop_event=None):
    """All supplied PACs, plus Module's explicitly redirected stock models."""
    from cdmw.core.pappt_format import parse_pappt
    from cdmw.core.prefab_binary import decode_prefab_binary

    mod = library.mod(identifier)
    sources = library.sources(identifier)
    paths = {path for path, _ in mod.files if path.startswith("character/model/") and path.endswith(".pac")}
    unresolved = []
    targets = {}
    if mod.kind in {"fit", "module"} and snapshot is not None:
        records = {r.stem.casefold(): r for r in snapshot.pappt.records}
        if _PAPPT in sources:
            records.update({r.stem.casefold(): r for r in parse_pappt(sources[_PAPPT].read_bytes()).records})
        prefab_paths = None
        for target in sorted({target for _, target in mod.replacements}):
            raise_if_cancelled(stop_event)
            record = records.get(target)
            if record is not None:
                path = normalized(record.prefab_path)
            else:
                # Some conditional targets are subparts rather than PAPPT rows.
                # Only an exact, unique prefab basename can resolve such a target.
                if prefab_paths is None:
                    prefab_paths = set(snapshot.entry_paths_with_extensions((".prefab",)))
                    prefab_paths.update(p for p in sources if p.endswith(".prefab"))
                matches = [p for p in prefab_paths if p.rsplit("/", 1)[-1] == target + ".prefab"]
                if len(matches) != 1:
                    if mod.kind == 'module':
                        unresolved.append(target)
                    continue
                path = matches[0]
            if path not in sources and not snapshot.has_entry(path):
                if mod.kind == 'module':
                    unresolved.append(target)
                continue
            data = sources[path].read_bytes() if path in sources else snapshot.payload(path)
            document = decode_prefab_binary(data)
            models = [normalized(row.text) for row in document.resource_strings()
                      if row.text.casefold().endswith(".pac")]
            if not models or any(model not in sources and not snapshot.has_entry(model) for model in models):
                if mod.kind == 'module':
                    unresolved.append(target)
            else:
                targets[target] = tuple(models)
                if mod.kind == 'module':
                    paths.update(models)
    names = _replacement_item_names(mod, snapshot, targets, paths, stop_event)
    library.revision.validate(stop_event)
    return CharacterModelCatalogue(tuple(sorted(paths)), tuple(unresolved), names)


def _replacement_item_names(mod, snapshot, targets, paths, stop_event):
    """Labels follow item -> worn prefab -> explicit mod rule -> target PAC only."""
    from collections import defaultdict
    from cdmw.core.iteminfo_behavior import read_behavior_fields

    rules = defaultdict(set)
    for source, target in mod.replacements:
        rules[source].update(path for path in targets.get(target, ()) if path in paths)
    if not rules or snapshot is None or not hasattr(snapshot, 'rows'):
        return ()
    names = defaultdict(set)
    display = snapshot.item_display_names()
    for key, row in snapshot.rows.items():
        raise_if_cancelled(stop_event)
        if not row.equip_type_key:
            continue
        try:
            prefabs = read_behavior_fields(row.raw)['prefabs']
        except ValueError:
            continue  # An unqualified row is never a basis for a friendly label.
        for entry in prefabs:
            if entry['data_type'] != 0:
                continue
            for prefab in entry['prefabs']:
                source = snapshot.stringinfo_texts.get(prefab, '').casefold()
                for path in rules.get(source, ()):
                    names[path].add(display.get(key) or row.string_key.replace('_', ' '))
    return tuple((path, tuple(sorted(labels))) for path, labels in sorted(names.items()))
