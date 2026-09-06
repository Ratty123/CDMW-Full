"""Read explicit item -> prefab -> model links for the archive name index."""
from __future__ import annotations

from pathlib import PurePosixPath

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import hashlittle
from cdmw.core.common import raise_if_cancelled
from cdmw.core.prefab_binary import PrefabBinaryError, decode_prefab_binary
from cdmw.core.stringinfo_table import parse_stringinfo, stringinfo_index


def archive_prefab_names(sources, *, stop_event=None):
    if sources.stringinfo_entry is None or sources.stringinfo_header_entry is None:
        return None
    body = read_archive_entry_data(sources.stringinfo_entry, stop_event=stop_event)[0]
    header = read_archive_entry_data(sources.stringinfo_header_entry, stop_event=stop_event)[0]
    strings = stringinfo_index(parse_stringinfo(body, header))
    stems = {PurePosixPath(e.path.replace("\\", "/").lower()).stem
             for e in sources.model_entries if e.path.lower().endswith(".prefab")}
    return {key: value for key, value in strings.items() if value.lower() in stems}


def enrich_prefab_names(index, model_entries, *, stop_event=None):
    from cdmw.core.item_index import _add_display_name, _build_archive_asset_catalog_entries

    prefabs = {}
    for entry in model_entries:
        path = entry.path.replace("\\", "/").lower()
        if path.endswith(".prefab"):
            stem = PurePosixPath(path).stem
            prefabs.setdefault(hashlittle(stem.encode("utf-8"), 0xC5EDE), []).append(entry)
    wanted = {key for item in index.items for key in item.prefab_hashes}
    models = {}
    for key in wanted & prefabs.keys():
        paths = []
        for entry in prefabs[key]:
            raise_if_cancelled(stop_event)
            try:
                data = read_archive_entry_data(entry, stop_event=stop_event)[0]
                document = decode_prefab_binary(data)
            except (OSError, ValueError, PrefabBinaryError):
                continue
            for resource in document.resource_strings():
                path = resource.text.replace("\\", "/").strip()
                if path.lower().endswith(".pac") and path not in paths:
                    paths.append(path)
        models[key] = paths
    existing_paths = {e.path.replace("\\", "/").lower() for e in model_entries}
    existing_pacs = {PurePosixPath(path).name for path in existing_paths if path.endswith(".pac")}
    for item in index.items:
        kept = []
        for path in item.pac_files:
            normalized = path.replace("\\", "/").lower()
            if normalized in existing_paths or ("/" not in normalized and normalized in existing_pacs):
                kept.append(path)
        item.pac_files[:] = kept
        for key in item.prefab_hashes:
            for path in models.get(key, ()):
                if path.lower() not in existing_paths:
                    continue
                stem = PurePosixPath(path).stem.lower()
                if path not in item.pac_files:
                    item.pac_files.append(path)
                _add_display_name(index.model_base_exact_display_names, stem, item.display_name)
                _add_display_name(index.model_base_display_names, stem, item.display_name)
                terms = " ".join((item.internal_name, str(item.item_id), item.display_name, *item.localized_names)).lower()
                index.model_base_aliases[stem] = (index.model_base_aliases.get(stem, "") + " " + terms).strip()
    index.pac_to_items = {}
    for item in index.items:
        for path in item.pac_files:
            index.pac_to_items.setdefault(path, []).append(item)
    index.asset_catalog = _build_archive_asset_catalog_entries(index.items)
    return index
