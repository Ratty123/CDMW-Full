"""Read mounted overlays into a new, independent New Item package.

The source installation is read-only. Whole mounted overlay archives are carried
forward, using the game's active version of each path. Shipped archives supply
baselines, never files to copy wholesale into the output.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.core.papgt_format import parse_papgt
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.allocation import DEFAULT_ITEM_KEY_RANGE
from cdmw.services.archive_overlay_install import OVERLAY_DIRECTORY_FIRST


@dataclass(frozen=True)
class MountedItemBase:
    snapshot: object
    game_root: Path
    archives: tuple[str, ...]
    items: tuple[dict, ...]
    originals: dict[str, bytes | None]


def _item_rows(body, header):
    return {row.row_id: bytes(body[start:end])
            for row, start, end in parse_pabgh_table(header, payload=body).row_spans(len(body))}


def _check_material_textures(base, payloads, stop_event):
    """Validate explicit material texture paths without guessing optional sidecars."""
    from cdmw.core.pac_xml_standard_material import find_material_wrappers
    from cdmw.domain.xml_text import decode_xml_text_payload

    for path, data in payloads.items():
        if not path.endswith(".pac_xml"):
            continue
        raise_if_cancelled(stop_event, "Checking mounted material textures cancelled.")
        for wrapper in find_material_wrappers(decode_xml_text_payload(data).text):
            for value in wrapper.textures.values():
                texture = value.replace("\\", "/").strip("/").lower()
                if texture and not base.has_entry(texture):
                    raise ValueError(f"Mounted material {path} is missing a required texture: {texture}")
                if texture:
                    base.payload(texture)  # Pin borrowed shipped textures as dependencies too.


def prepare_mounted_item_base(service, snapshot, *, read_entry, on_log=None, stop_event=None):
    """Collect all mounted overlay contents and refuse already-lost custom rows."""
    def report(message):
        raise_if_cancelled(stop_event, "Reading mounted items cancelled.")
        if on_log:
            on_log(message)
        raise_if_cancelled(stop_event, "Reading mounted items cancelled.")

    root = Path(snapshot.iteminfo.payload_entry.pamt_path).resolve().parent.parent
    mount_path = root / "meta/0.papgt"
    if not mount_path.is_file() or mount_path.stat().st_size > 1024 * 1024:
        raise ValueError("Cannot read the installed archive list (meta/0.papgt). Read the archives again.")
    if snapshot.provenance:
        snapshot.provenance.capture().validate(stop_event)
    # Re-read tables through an independent tracker; do not turn the workspace's
    # normal snapshot into a mod base or retain a cancelled scan's cached payloads.
    base = service.build_snapshot(snapshot.entries.values(), read_entry=read_entry,
                                  on_log=on_log, stop_event=stop_event)
    tracker = base.provenance
    tracker.pin_file(mount_path)
    mounts = parse_papgt(mount_path.read_bytes())
    tracker.pin_file(mount_path)
    overlay_entries, vanilla_archives, archives = {}, [], []
    for mount in mounts:
        name = mount.name
        if len(name) != 4 or not name.isascii() or not name.isdigit():
            raise ValueError(f"Unsupported mounted archive folder: {name}. Use the original mod folder instead.")
        pamt = root / name / "0.pamt"
        if not pamt.resolve().is_relative_to(root) or not pamt.is_file():
            raise ValueError(f"Mounted archive is missing or outside the game folder: {pamt}")
        tracker.pin_file(pamt)
        if int(name) < OVERLAY_DIRECTORY_FIRST:
            vanilla_archives.append(pamt)
            continue
        report(f"Reading mounted overlay {name}...")
        entries = tuple(parse_archive_pamt(pamt))
        if not entries:
            raise ValueError(f"Mounted overlay {name} contains no readable files.")
        for entry in entries:
            if not Path(entry.paz_file).resolve().is_relative_to(root / name):
                raise ValueError(f"Mounted overlay {name} refers to an archive outside its folder.")
        overlay_entries[name] = {entry.path.replace("\\", "/").lower(): entry for entry in entries}
        tracker.pin_file(pamt)
        archives.append(name)
    if not archives:
        raise ValueError("No separate mounted overlay archives were found. Items written into the shipped archives "
                         "cannot be recovered by this option; use their original mod folder.")

    paths = set().union(*(entries.keys() for entries in overlay_entries.values()))
    item_body = base.iteminfo.payload_entry.path
    item_head = base.iteminfo.header_entry.path
    # Find underlying entries for these paths without holding another full game
    # catalogue in memory. Absence is known only after every shipped index is read.
    underlay = {}
    for pamt in vanilla_archives:
        report(f"Checking the underlying game files in {pamt.parent.name}...")
        for entry in parse_archive_pamt(pamt):
            raise_if_cancelled(stop_event, "Reading mounted items cancelled.")
            path = entry.path.replace("\\", "/").lower()
            if path in paths or path in (item_body, item_head):
                underlay.setdefault(path, entry)
        tracker.pin_file(pamt)
    if item_body not in underlay or item_head not in underlay:
        raise ValueError("The underlying game ItemInfo table is unavailable. Use the original mod folder instead.")
    shipped_rows = _item_rows(tracker.read(underlay[item_body]), tracker.read(underlay[item_head]))
    contaminated = sorted(key for key in shipped_rows if key in DEFAULT_ITEM_KEY_RANGE)
    if contaminated:
        raise ValueError("The shipped archives also contain custom items; their original assets cannot be isolated. "
                         "Use the original mod folder. Item IDs: " + ", ".join(map(str, contaminated)))
    active_rows = _item_rows(base.iteminfo.payload, base.iteminfo.header)
    keys = sorted(set(active_rows) - shipped_rows.keys())
    if not keys:
        raise ValueError("No added items were found in the active mounted tables. Read the archives again or use a separate mod.")

    # A lower-priority table may still hold an item that is already hidden in the
    # game. Do not describe an export of the winning table as preserving that item.
    for name, entries in overlay_entries.items():
        if item_body not in entries and item_head not in entries:
            continue
        if item_body not in entries or item_head not in entries:
            raise ValueError(f"Mounted overlay {name} has an incomplete ItemInfo table pair.")
        rows = _item_rows(tracker.read(entries[item_body]), tracker.read(entries[item_head]))
        for key in rows.keys() - shipped_rows.keys():
            if active_rows.get(key) != rows[key]:
                label = parse_iteminfo_row(rows[key]).string_key
                raise ValueError(f"Mounted overlays already conflict: {label} (item {key}) from {name} is hidden "
                                 "or overwritten by another table. Merge the original mod folders to resolve this first.")

    payloads, originals = {}, {}
    for path in sorted(paths):
        report(f"Collecting mounted file: {path}")
        if path.startswith("meta/"):
            raise ValueError(f"Unsupported metadata inside a mounted archive: {path}")
        if not base.has_entry(path):
            raise ValueError(f"Mounted file is not in the current archive catalogue: {path}. Read the archives again.")
        entry = base.entry(path)
        if Path(entry.pamt_path).parent.name not in overlay_entries:
            raise ValueError(f"Mounted overlay file is hidden by a shipped archive: {path}. Review the mount order first.")
        payloads[path] = base.payload(path)
        originals[path] = tracker.read(underlay[path]) if path in underlay else None

    _check_material_textures(base, payloads, stop_event)

    labels = base.item_display_names()
    items = []
    for key in keys:
        report(f"Checking mounted item {labels.get(key) or base.rows[key].string_key} ({key})...")
        row = base.rows[key]
        # Equipment with visual part references must retain every referenced model,
        # prefab and icon. Physics sidecars are optional in the existing family rule.
        from cdmw.core.item_model_family import find_part_stems, find_icon_string, ICON_FOLDER
        missing = []
        if find_part_stems(row, base.stringinfo_texts, base.pappt):
            family = base.family(key)
            missing = [file.path for file in family.missing_files if file.role in {"pac", "prefab", "icon"}]
            for file in family.files:
                if file.exists and file.role in {"pac", "prefab", "icon"}:
                    base.payload(file.path)
            for part in family.parts:
                if part.record is None or not part.pac_paths:
                    missing.append(part.prefab_path or part.stem)
                for path in part.pac_paths:
                    if base.has_entry(path):
                        base.payload(path)
                    else:
                        missing.append(path)
        elif base.equip_type_name(row):
            missing.append("part-prefab references")
        _hash, icon = find_icon_string(row, base.stringinfo_texts)
        if icon:
            path = f"{ICON_FOLDER}/{icon.lower()}.dds"
            if base.has_entry(path):
                base.payload(path)
            else:
                missing.append(path)
        if missing:
            raise ValueError(f"Mounted item {key} is missing required assets: " + ", ".join(sorted(set(missing))))
        items.append({"item_key": key, "internal_name": row.string_key,
                      "display_name": labels.get(key) or row.string_key})
    base.base_payloads = payloads
    base.base_added_paths = frozenset(path for path, before in originals.items() if before is None)
    base.base_manifest = {"previous_items": items}
    tracker.capture().validate(stop_event)
    return MountedItemBase(base, root, tuple(archives), tuple(items), originals)


def complete_mounted_item_plan(plan, mounted, *, stop_event=None):
    """Preserve registrations, genuine underlying baselines and export instructions."""
    from cdmw.core.mod_compatibility import capture_patch_compatibility, compatibility_from_payloads, digest
    from cdmw.core.pathc_format import dds_shape, encode_pathc, parse_pathc, register_dds
    from cdmw.domain.archives.mutation import MetaFileWrite

    base = mounted.snapshot
    registry = next((parse_pathc(meta.payload_data) for meta in plan.meta_files if meta.path == "meta/0.pathc"), base.pathc)
    textures = sorted(path for path in base.base_payloads if path.endswith(".dds"))
    if textures and registry is None:
        raise ValueError("The mounted textures have no readable meta/0.pathc registry. Use the original mod folder.")
    for path in textures:
        raise_if_cancelled(stop_event, "Checking mounted textures cancelled.")
        data = base.base_payloads[path]
        registered = registry.find(path)
        if registered is None:
            registry = register_dds(registry, path, data)
        elif not registered.is_direct or dds_shape(registry.dds_header_for(registered)) != dds_shape(data):
            raise ValueError(f"Mounted texture registration is ambiguous or does not match its DDS: {path}")
    metadata = tuple(plan.meta_files)
    if textures:
        metadata = tuple(meta for meta in metadata if meta.path != "meta/0.pathc") + (
            MetaFileWrite("meta/0.pathc", encode_pathc(registry)),)
    manifest = dict(plan.manifest)
    manifest["mounted_base"] = {"archives": list(mounted.archives), "items": list(mounted.items),
                                "file_count": len(base.base_payloads)}
    manifest["texture_registry"] = sorted(set(manifest.get("texture_registry", ())) | set(textures))
    after = dict(plan.loose_files)
    after.update((meta.path, meta.payload_data) for meta in metadata)
    dependencies = tuple({"path": row["path"], "sha256": row["sha256"]}
                         for row in manifest.get("sources", ()) if row["path"] not in after)
    captured = capture_patch_compatibility(plan.patches, plan.additions, game_root=mounted.game_root,
        metadata_files=tuple((meta.path, meta.payload_data) for meta in metadata),
        dependencies=dependencies, stop_event=stop_event)
    before = dict(captured.originals)
    before.update(mounted.originals)
    # The live texture registry can include other managers' historical entries.
    # Preserve its bytes in the export, but never label it a vanilla baseline.
    before.pop("meta/0.pathc", None)
    # Merge mods consumes source hashes as the parent versions of table edits.
    # Record the underlying game there, not a dependency on the original mod.
    sources = {row["path"]: row for row in manifest.get("sources", ()) if row["path"] not in after}
    for path, data in before.items():
        if data is not None:
            sources[path] = {"path": path, "sha256": digest(data)}
    manifest["sources"] = list(sources.values())
    compatibility = compatibility_from_payloads(after, before, target_game=captured.target_game,
                                               dependencies=dependencies)
    revision = base.provenance.capture()
    revision.validate(stop_event)
    return replace(plan, manifest=manifest, meta_files=metadata, source_revision=revision,
                   export_compatibility=compatibility,
                   summary_lines=(*plan.summary_lines, *mounted_item_instructions(manifest)))


def mounted_item_instructions(manifest):
    """Shared plan review and portable README; no machine-specific paths."""
    mounted = manifest.get("mounted_base")
    if not mounted:
        return ()
    return (
        "Combined mod from mounted content",
        "Included archive folders: " + ", ".join(mounted["archives"]),
        "Existing items: " + ", ".join(f"{item['display_name']} (item {item['item_key']})" for item in mounted["items"]),
        "All active files from these overlay archives are included, including their other changes.",
        "1. Review the included items and files, then write this combined mod to a new folder.",
        "2. Close the game. Use the original mod manager to disable the mods supplying the included archive folders. "
        "For CDMW overlays, use Mod Management. Do not delete game archive folders by hand.",
        "3. Install and enable this combined package in their place. Do not enable it together with the included originals.",
        "4. Check the new item and the included items in game. To revert, disable this package and re-enable the originals.",
        "Only the current mounted result is preserved; already overwritten changes cannot be recovered automatically.",
    )


def write_mounted_item_readme(plan, result):
    lines = mounted_item_instructions(plan.manifest)
    if not lines:
        return result
    path = result.package_root / "README.txt"
    previous = path.read_text(encoding="utf-8") if path.is_file() else ""
    path.write_text(previous.rstrip() + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return replace(result, metadata_files=tuple(sorted(set(result.metadata_files) | {"README.txt"})))
