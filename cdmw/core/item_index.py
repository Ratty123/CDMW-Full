from __future__ import annotations

import os
import re
import struct
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive import (
    hashlittle,
    iter_archive_character_equipment_root_alias_stems,
    iter_archive_equipment_model_alias_stems,
    read_archive_entry_data,
)
from cdmw.core.common import raise_if_cancelled
from cdmw.models import ArchiveEntry
from cdmw.models import RunCancelled


@dataclass(slots=True)
class ArchiveItemRecord:
    item_id: int
    internal_name: str
    display_name: str = ""
    localized_names: tuple[str, ...] = ()
    prefab_hashes: List[int] = field(default_factory=list)
    model_stems: List[str] = field(default_factory=list)
    pac_files: List[str] = field(default_factory=list)
    icon_paths: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ArchiveAssetCatalogEntry:
    item_id: int
    internal_name: str
    display_name: str
    category: str
    group: str = ""
    pac_files: tuple[str, ...] = ()
    model_stems: tuple[str, ...] = ()
    icon_paths: tuple[str, ...] = ()
    localized_names: tuple[str, ...] = ()
    variant_count: int = 1
    evidence: str = ""
    scope_filter: str = ""

    def to_cache_dict(self) -> Dict[str, object]:
        return {
            "item_id": int(self.item_id),
            "internal_name": self.internal_name,
            "display_name": self.display_name,
            "category": self.category,
            "group": self.group,
            "pac_files": list(self.pac_files),
            "model_stems": list(self.model_stems),
            "icon_paths": list(self.icon_paths),
            "localized_names": list(self.localized_names),
            "variant_count": int(self.variant_count),
            "evidence": self.evidence,
            "scope_filter": self.scope_filter,
        }


@dataclass(slots=True)
class ArchiveItemSearchIndex:
    items: List[ArchiveItemRecord]
    pac_to_items: Dict[str, List[ArchiveItemRecord]]
    model_base_aliases: Dict[str, str]
    model_base_display_names: Dict[str, str]
    model_base_exact_display_names: Dict[str, str]
    model_base_related_display_names: Dict[str, str]
    asset_catalog: List[ArchiveAssetCatalogEntry] = field(default_factory=list)


@dataclass(slots=True)
class _ArchiveItemIndexSources:
    localization_entries: Dict[str, ArchiveEntry] = field(default_factory=dict)
    iteminfo_entry: Optional[ArchiveEntry] = None
    stringinfo_entry: Optional[ArchiveEntry] = None
    model_entries: List[ArchiveEntry] = field(default_factory=list)
    icon_entries: List[ArchiveEntry] = field(default_factory=list)


_ITEMINFO_MARKER = b"\x00\x01\x00\x00\x00\x00\x00\x00\x00\x07\x70\x00\x00\x00"
_ITEM_INTERNAL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_MODEL_HASH_SUFFIXES = (
    "",
    "_l",
    "_r",
    "_u",
    "_s",
    "_t",
    "_c",
    "_d",
    "_index01",
    "_index02",
    "_index03",
    "_index01_l",
    "_index01_r",
    "_index02_l",
    "_index02_r",
    "_index03_l",
    "_index03_r",
    "_sub01",
    "_sub02",
    "_sub03",
)
_MODEL_TRAILING_LETTER_VARIANT_RE = re.compile(r"(?<=\d)[a-z]$", re.IGNORECASE)
_MODEL_NUMBERED_FAMILY_VARIANT_RE = re.compile(r"_(?:index|sub)\d{2}$", re.IGNORECASE)
_LOCALIZATION_TABLES = (
    ("kor", "localizationstring_kor"),
    ("eng", "localizationstring_eng"),
    ("jpn", "localizationstring_jpn"),
    ("rus", "localizationstring_rus"),
    ("tur", "localizationstring_tur"),
    ("spa-es", "localizationstring_spa-es"),
    ("spa-mx", "localizationstring_spa-mx"),
    ("fre", "localizationstring_fre"),
    ("ger", "localizationstring_ger"),
    ("ita", "localizationstring_ita"),
    ("pol", "localizationstring_pol"),
    ("por-br", "localizationstring_por-br"),
    ("zho-tw", "localizationstring_zho-tw"),
    ("zho-cn", "localizationstring_zho-cn"),
)
_LOCALIZATION_TABLE_BY_NAME = {table_name: language_code for language_code, table_name in _LOCALIZATION_TABLES}
_ITEM_ICON_PREFAB_PREFIX = "itemicon_prefab_"
_ITEM_ICON_MODEL_COMPATIBILITY_TOKENS: Tuple[Tuple[str, str], ...] = (
    ("onehandsword", "01_sword"),
    ("twohandsword", "02_sword"),
    ("twohandspear", "02_spear"),
    ("halberd", "02_alebard"),
    ("alebard", "02_alebard"),
    ("hammer", "02_hammer"),
    ("spear", "spear"),
    ("shield", "03_shield"),
    ("backpack", "bag"),
    ("ring", "ring"),
    ("earring", "earring"),
    ("necklace", "necklace"),
    ("helm", "hel"),
    ("helmet", "hel"),
    ("armor", "ub"),
    ("cloak", "cloak"),
    ("glove", "hand"),
    ("boots", "foot"),
    ("saddle", "horse_ub"),
)


def _strip_archive_model_variant_suffix(stem: str) -> str:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ""
    while True:
        before = normalized
        for suffix in sorted(_MODEL_HASH_SUFFIXES[1:], key=len, reverse=True):
            if normalized.endswith(suffix) and len(normalized) > len(suffix):
                normalized = normalized[: -len(suffix)]
                break
        if normalized != before:
            continue
        stripped = _MODEL_NUMBERED_FAMILY_VARIANT_RE.sub("", normalized).strip()
        if stripped and stripped != normalized:
            normalized = stripped
            continue
        stripped = _MODEL_TRAILING_LETTER_VARIANT_RE.sub("", normalized).strip()
        if stripped and stripped != normalized:
            normalized = stripped
            continue
        return normalized or before


def _iter_archive_model_hash_candidate_bases(stem: str) -> Tuple[str, ...]:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ()
    candidates: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = str(value or "").strip().lower()
        if value and value not in seen:
            candidates.append(value)
            seen.add(value)

    add(normalized)
    add(_strip_archive_model_variant_suffix(normalized))
    return tuple(candidates)


def _entry_package_group(entry: ArchiveEntry) -> str:
    try:
        return entry.pamt_path.parent.name.lower()
    except Exception:
        return ""


def _find_archive_entry(entries: Sequence[ArchiveEntry], package_group: str, needle: str) -> Optional[ArchiveEntry]:
    normalized_group = str(package_group or "").strip().lower()
    normalized_needle = str(needle or "").strip().lower()
    if not normalized_group or not normalized_needle:
        return None
    for entry in entries:
        if _entry_package_group(entry) != normalized_group:
            continue
        if normalized_needle in entry.path.lower():
            return entry
    return None


def _collect_archive_item_index_sources(
    entries: Sequence[ArchiveEntry],
    *,
    stop_event: Optional[threading.Event] = None,
) -> _ArchiveItemIndexSources:
    sources = _ArchiveItemIndexSources()
    for index, entry in enumerate(entries):
        if index % 4096 == 0:
            raise_if_cancelled(stop_event)
        lower_path = entry.path.lower()
        wants_localization = "localizationstring_" in lower_path
        wants_iteminfo = "iteminfo.pabgb" in lower_path
        wants_stringinfo = os.path.basename(lower_path) == "stringinfo.pabgb"
        wants_model_hash = lower_path.endswith((".prefab", ".pac", ".pact"))
        wants_item_icon = lower_path.endswith(".dds") and "itemicon" in lower_path
        if not (wants_localization or wants_iteminfo or wants_stringinfo or wants_model_hash or wants_item_icon):
            continue
        group = _entry_package_group(entry)
        if wants_localization and group == "0020":
            for table_name, language_code in _LOCALIZATION_TABLE_BY_NAME.items():
                if table_name in lower_path:
                    sources.localization_entries.setdefault(language_code, entry)
                    break
        elif wants_iteminfo and group == "0008" and sources.iteminfo_entry is None:
            sources.iteminfo_entry = entry
        elif wants_stringinfo and group == "0008" and sources.stringinfo_entry is None:
            sources.stringinfo_entry = entry
        elif wants_model_hash and group == "0009":
            sources.model_entries.append(entry)
        elif wants_item_icon:
            sources.icon_entries.append(entry)
    return sources


def _parse_archive_localization_entry(
    loc_entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, str]:
    data, _decompressed, _note = read_archive_entry_data(loc_entry, stop_event=stop_event)
    loc_dict: Dict[str, str] = {}
    pos = 0
    while pos + 8 < len(data):
        raise_if_cancelled(stop_event)
        slen = struct.unpack_from("<I", data, pos)[0]
        if slen == 0 or slen > 50_000 or pos + 4 + slen > len(data):
            pos += 1
            continue

        s_bytes = data[pos + 4 : pos + 4 + slen]
        if 6 <= slen <= 20 and all(0x30 <= value <= 0x39 for value in s_bytes):
            loc_id = s_bytes.decode("ascii")
            text_pos = pos + 4 + slen
            if text_pos + 4 < len(data):
                text_len = struct.unpack_from("<I", data, text_pos)[0]
                if 0 < text_len < 50_000 and text_pos + 4 + text_len <= len(data):
                    text = data[text_pos + 4 : text_pos + 4 + text_len].decode(
                        "utf-8",
                        errors="replace",
                    )
                    loc_dict[loc_id] = text
                    pos = text_pos + 4 + text_len
                    continue
        pos += 1

    return loc_dict


def parse_archive_localization_strings(
    entries: Sequence[ArchiveEntry],
    *,
    table_name: str = "localizationstring_eng",
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, str]:
    loc_entry = _find_archive_entry(entries, "0020", table_name)
    if loc_entry is None:
        if on_log is not None:
            on_log(f"Item-name search: {table_name} was not found in package 0020.")
        return {}

    return _parse_archive_localization_entry(loc_entry, stop_event=stop_event)


def _parse_archive_localization_tables_from_sources(
    sources: _ArchiveItemIndexSources,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, Dict[str, str]]:
    loc_tables: Dict[str, Dict[str, str]] = {}
    missing_tables: List[str] = []
    for language_code, table_name in _LOCALIZATION_TABLES:
        raise_if_cancelled(stop_event)
        loc_entry = sources.localization_entries.get(language_code)
        if loc_entry is None:
            missing_tables.append(table_name)
            continue
        try:
            table = _parse_archive_localization_entry(loc_entry, stop_event=stop_event)
        except RunCancelled:
            raise
        except Exception as exc:
            if on_log is not None:
                on_log(f"Item-name search: skipped {table_name}: {exc}")
            continue
        if table:
            loc_tables[language_code] = table
    if missing_tables and on_log is not None:
        on_log(
            "Item-name search: "
            f"{len(missing_tables):,} localization table(s) not found in package 0020: "
            f"{', '.join(missing_tables)}."
        )
    return loc_tables


def parse_archive_localization_tables(
    entries: Sequence[ArchiveEntry],
    *,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, Dict[str, str]]:
    sources = _collect_archive_item_index_sources(entries, stop_event=stop_event)
    return _parse_archive_localization_tables_from_sources(
        sources,
        on_log=on_log,
        stop_event=stop_event,
    )


def _normalize_item_icon_model_stem(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").rsplit("/", 1)[-1].lower()
    if normalized.endswith((".pac", ".prefab", ".pact")):
        normalized = os.path.splitext(normalized)[0]
    return normalized


def _parse_stringinfo_model_icon_hashes_from_data(data: bytes) -> Dict[int, str]:
    icon_hashes: Dict[int, str] = {}
    pos = 0
    while pos + 8 < len(data):
        slen = struct.unpack_from("<I", data, pos)[0]
        if 3 <= slen <= 180 and pos + 4 + slen + 4 <= len(data):
            raw = data[pos + 4 : pos + 4 + slen].rstrip(b"\x00")
            try:
                text = raw.decode("ascii")
            except UnicodeDecodeError:
                text = ""
            lower_text = text.lower()
            if lower_text.startswith(_ITEM_ICON_PREFAB_PREFIX):
                model_stem = _normalize_item_icon_model_stem(text[len(_ITEM_ICON_PREFAB_PREFIX) :])
                if model_stem.startswith("cd_"):
                    stored_hash = struct.unpack_from("<I", data, pos + 4 + slen)[0]
                    icon_hashes[stored_hash] = model_stem
                    icon_hashes[hashlittle(raw, 0xC5EDE)] = model_stem
                    icon_hashes[hashlittle(model_stem.encode("ascii", errors="ignore"), 0xC5EDE)] = model_stem
            pos += 4 + slen + 8
            continue
        pos += 1
    return icon_hashes


def _parse_archive_stringinfo_model_icon_hashes(
    stringinfo_entry: Optional[ArchiveEntry],
    *,
    stop_event: Optional[threading.Event] = None,
) -> Dict[int, str]:
    if stringinfo_entry is None:
        return {}
    data, _decompressed, _note = read_archive_entry_data(stringinfo_entry, stop_event=stop_event)
    return _parse_stringinfo_model_icon_hashes_from_data(data)


def _add_icon_path(index: Dict[str, List[str]], key: str, path: str) -> None:
    normalized_key = str(key or "").strip().lower()
    normalized_path = str(path or "").replace("\\", "/").strip()
    if not normalized_key or not normalized_path:
        return
    paths = index.setdefault(normalized_key, [])
    if normalized_path not in paths:
        paths.append(normalized_path)


def _build_archive_item_icon_path_index(icon_entries: Sequence[ArchiveEntry]) -> Dict[str, List[str]]:
    index: Dict[str, List[str]] = {}
    for entry in icon_entries:
        lower_path = entry.path.replace("\\", "/").lower()
        basename = lower_path.rsplit("/", 1)[-1]
        stem = os.path.splitext(basename)[0]
        model_stem = ""
        if stem.startswith(_ITEM_ICON_PREFAB_PREFIX):
            model_stem = _normalize_item_icon_model_stem(stem[len(_ITEM_ICON_PREFAB_PREFIX) :])
        elif "cd_" in stem:
            model_stem = _normalize_item_icon_model_stem(stem[stem.find("cd_") :])
        if not model_stem:
            continue
        for key in _iter_archive_model_hash_candidate_bases(model_stem):
            _add_icon_path(index, key, entry.path)
            for alias_stem in iter_archive_character_equipment_root_alias_stems(key):
                _add_icon_path(index, alias_stem, entry.path)
            for alias_stem in iter_archive_equipment_model_alias_stems(key):
                _add_icon_path(index, alias_stem, entry.path)
    return index


def _item_icon_model_reference_is_compatible(internal_name: str, model_stem: str) -> bool:
    normalized_internal = str(internal_name or "").strip().lower()
    normalized_model = str(model_stem or "").strip().lower()
    if not normalized_internal or not normalized_model:
        return False
    return any(
        internal_token in normalized_internal and model_token in normalized_model
        for internal_token, model_token in _ITEM_ICON_MODEL_COMPATIBILITY_TOKENS
    )


def _parse_archive_iteminfo_data(
    data: bytes,
    loc_tables: Mapping[str, Mapping[str, str]],
    *,
    icon_model_hashes: Optional[Mapping[int, str]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[ArchiveItemRecord]:
    items: List[ArchiveItemRecord] = []
    seen_ids: set[int] = set()
    idx = 0
    while True:
        raise_if_cancelled(stop_event)
        pos = data.find(_ITEMINFO_MARKER, idx)
        if pos == -1:
            break
        idx = pos + len(_ITEMINFO_MARKER)
        null_pos = pos

        name_start = null_pos
        while name_start > 0 and 0x21 <= data[name_start - 1] <= 0x7E:
            name_start -= 1
            if null_pos - name_start > 150:
                break
        if null_pos - name_start < 3 or name_start < 8:
            continue

        name = data[name_start:null_pos].decode("ascii", errors="replace")
        if not _ITEM_INTERNAL_NAME_RE.match(name):
            continue
        try:
            name_len = struct.unpack_from("<I", data, name_start - 4)[0]
            item_id = struct.unpack_from("<I", data, name_start - 8)[0]
        except struct.error:
            continue
        if name_len not in (len(name), len(name) + 1):
            continue
        if item_id < 100 or item_id > 100_000_000 or item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        loc_id = ""
        loc_off = pos + 18
        if loc_off + 4 < len(data):
            loc_len = struct.unpack_from("<I", data, loc_off)[0]
            if 5 < loc_len < 25 and loc_off + 4 + loc_len <= len(data):
                loc_bytes = data[loc_off + 4 : loc_off + 4 + loc_len]
                if all(0x30 <= value <= 0x39 for value in loc_bytes):
                    loc_id = loc_bytes.decode("ascii")

        prefab_hashes: List[int] = []
        search_end = min(len(data), pos + 800)
        for scan in range(pos + 14, search_end - 15):
            if data[scan] not in {0x0E, 0x0F}:
                continue
            count1 = struct.unpack_from("<I", data, scan + 3)[0]
            count2 = struct.unpack_from("<I", data, scan + 7)[0]
            if not (0 < count1 <= 5 and 0 < count2 <= 5):
                continue
            for hash_index in range(count2):
                value = struct.unpack_from("<I", data, scan + 11 + hash_index * 4)[0]
                if value:
                    prefab_hashes.append(value)
            if prefab_hashes:
                break

        model_stems: List[str] = []
        if icon_model_hashes:
            next_record_pos = data.find(_ITEMINFO_MARKER, idx)
            icon_search_end = min(
                len(data),
                next_record_pos if next_record_pos != -1 else pos + 2500,
                pos + 2500,
            )
            for scan in range(pos, max(pos, icon_search_end - 3)):
                value = struct.unpack_from("<I", data, scan)[0]
                model_stem = _normalize_item_icon_model_stem(icon_model_hashes.get(value, ""))
                if (
                    model_stem
                    and model_stem not in model_stems
                    and _item_icon_model_reference_is_compatible(name, model_stem)
                ):
                    model_stems.append(model_stem)

        localized_names: List[str] = []
        seen_names: set[str] = set()
        if loc_id:
            for _language_code, table in loc_tables.items():
                localized_name = str(table.get(loc_id, "") or "").strip()
                normalized_name = localized_name.casefold()
                if localized_name and normalized_name not in seen_names:
                    localized_names.append(localized_name)
                    seen_names.add(normalized_name)
        display_name = ""
        if loc_id:
            display_name = str(loc_tables.get("eng", {}).get(loc_id, "") or "").strip()
            if not display_name and localized_names:
                display_name = localized_names[0]

        items.append(
            ArchiveItemRecord(
                item_id=item_id,
                internal_name=name,
                display_name=display_name,
                localized_names=tuple(localized_names),
                prefab_hashes=prefab_hashes,
                model_stems=model_stems,
            )
        )

    return items


def _parse_archive_iteminfo_entry(
    item_entry: ArchiveEntry,
    loc_tables: Mapping[str, Mapping[str, str]],
    *,
    icon_model_hashes: Optional[Mapping[int, str]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[ArchiveItemRecord]:
    data, _decompressed, _note = read_archive_entry_data(item_entry, stop_event=stop_event)
    return _parse_archive_iteminfo_data(
        data,
        loc_tables,
        icon_model_hashes=icon_model_hashes,
        stop_event=stop_event,
    )


def parse_archive_iteminfo(
    entries: Sequence[ArchiveEntry],
    loc_tables: Mapping[str, Mapping[str, str]],
    *,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[ArchiveItemRecord]:
    item_entry = _find_archive_entry(entries, "0008", "iteminfo.pabgb")
    if item_entry is None:
        if on_log is not None:
            on_log("Item-name search: iteminfo.pabgb was not found in package 0008.")
        return []

    return _parse_archive_iteminfo_entry(item_entry, loc_tables, stop_event=stop_event)


def _build_archive_model_hash_table_from_entries(entries: Sequence[ArchiveEntry]) -> Dict[int, str]:
    hash_to_name: Dict[int, str] = {}
    for entry in entries:
        lower_path = entry.path.lower()
        if not lower_path.endswith((".prefab", ".pac", ".pact")):
            continue
        base = os.path.splitext(os.path.basename(lower_path))[0]
        for candidate_base in _iter_archive_model_hash_candidate_bases(base):
            for suffix in _MODEL_HASH_SUFFIXES:
                name = candidate_base + suffix
                hash_to_name.setdefault(hashlittle(name.encode("ascii"), 0xC5EDE), name)
    return hash_to_name


def build_archive_model_hash_table(entries: Sequence[ArchiveEntry]) -> Dict[int, str]:
    sources = _collect_archive_item_index_sources(entries)
    return _build_archive_model_hash_table_from_entries(sources.model_entries)


def _add_display_name(display_names: Dict[str, str], base: str, display_name: str) -> None:
    normalized_base = str(base or "").strip().lower()
    normalized_name = str(display_name or "").strip()
    if not normalized_base or not normalized_name:
        return
    existing_display = display_names.get(normalized_base, "")
    if not existing_display:
        display_names[normalized_base] = normalized_name
    elif normalized_name not in existing_display.split(" / "):
        display_names[normalized_base] = f"{existing_display} / {normalized_name}"


_DISPLAY_VARIANT_SUFFIX_RE = re.compile(r"(?:\s*\(\+\d+\)|\s+\+\d+)$")
_INTERNAL_VARIANT_SUFFIX_RE = re.compile(r"(?:_?\+\d+|_lv\d+|_level\d+|_grade\d+)$", re.IGNORECASE)


def _catalog_display_base(display_name: str) -> str:
    normalized = str(display_name or "").strip()
    return _DISPLAY_VARIANT_SUFFIX_RE.sub("", normalized).strip() or normalized


def _catalog_internal_base(internal_name: str) -> str:
    normalized = str(internal_name or "").strip().lower()
    return _INTERNAL_VARIANT_SUFFIX_RE.sub("", normalized).strip("_") or normalized


def _friendly_internal_item_name(internal_name: str) -> str:
    text = _catalog_internal_base(internal_name)
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(text or ""))
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"\b(?:item|abyssreward|reward|equip|equipment)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return str(internal_name or "").strip() or "Unnamed asset"
    return " ".join(part[:1].upper() + part[1:] for part in text.split())


def _catalog_text_matches_any(text: str, tokens: Sequence[str]) -> bool:
    raw_text = str(text or "").lower()
    normalized_text = " " + re.sub(r"[^a-z0-9]+", " ", raw_text).strip() + " "
    compact_text = re.sub(r"[^a-z0-9]+", "", raw_text)
    for token in tokens:
        raw_token = str(token or "").strip().lower()
        if not raw_token:
            continue
        if "_" in raw_token or raw_token.startswith("_") or raw_token.endswith("_"):
            if raw_token in raw_text:
                return True
            continue
        normalized_token = re.sub(r"[^a-z0-9]+", " ", raw_token).strip()
        if normalized_token and f" {normalized_token} " in normalized_text:
            return True
        compact_token = re.sub(r"[^a-z0-9]+", "", raw_token)
        if len(compact_token) >= 7 and compact_token in compact_text:
            return True
    return False


def _classify_archive_asset_catalog_category_group(item: ArchiveItemRecord) -> Tuple[str, str]:
    primary_text = " ".join(
        token.lower()
        for token in (
            item.internal_name,
            item.display_name,
            " ".join(item.localized_names),
        )
        if token
    )
    relation_text = " ".join(
        token.lower()
        for token in (
            " ".join(item.pac_files),
            " ".join(item.model_stems),
            " ".join(item.icon_paths),
        )
        if token
    )
    text = " ".join(part for part in (primary_text, relation_text) if part)
    high_priority_document_tests: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
        ("Key / Permit", ("homekey", "visitorpass", "license", "permit", "permission", " key ", " pass ")),
        ("Clue / Report", ("sighting", "news", "report", "record", "clue", "evidence")),
        ("Book / Diary", ("diary", "journal", "epistle")),
        ("Document", ("letter", "note", "contract", "memo", "notepad", "noticepaper", "notice paper", "blueprint", "manual", "document", "scroll", "paper")),
    )
    for group, tokens in high_priority_document_tests:
        if _catalog_text_matches_any(primary_text, tokens) or _catalog_text_matches_any(relation_text, tokens):
            return "Quest / Document", group
    compact_primary_text = re.sub(r"[^a-z0-9]+", "", primary_text)
    if "lostletter" in compact_primary_text or (
        "letter" in compact_primary_text and compact_primary_text.endswith("letter")
    ):
        return "Quest / Document", "Document"
    if _catalog_text_matches_any(primary_text, ("recipe", "craftingrecipe", "crafting recipe")):
        return "Crafting / Recipe", "Recipe Book" if _catalog_text_matches_any(primary_text, ("recipe",)) else "Crafting"
    if _catalog_text_matches_any(text, ("itemcatch_fishingrod", "fishingrod", "fishing rod")):
        return "Tool", "Fishing"
    if _catalog_text_matches_any(
        text,
        (
            "petarmor",
            "pet armor",
            "catarmor",
            "cat armor",
            "dogarmor",
            "dog armor",
            "puppy",
            "cat outfit",
            "dog outfit",
            "pet outfit",
            "cat hat",
            "dog hat",
            "pet hat",
            "cat helm",
            "dog helm",
            "pet helm",
        ),
    ):
        return "Mount / Pet", "Pet Gear"
    if _catalog_text_matches_any(primary_text, ("potion", "medicine", "elixir", "tonic", "remedy", "recovery")):
        return "Consumable", "Potion / Medicine"
    if _catalog_text_matches_any(primary_text, ("food", "drink", "meal", "bread", "meat", "fruit", "carrot", "pear")):
        return "Consumable", "Food / Drink"
    category_tests: Tuple[Tuple[str, Tuple[Tuple[str, Tuple[str, ...]], ...]], ...] = (
        (
            "Weapon",
            (
                ("Sword", ("onehandsword", "twohandsword", "twohandgiantbastard", "bastard", "sword", "01_sword", "02_sword")),
                ("Shield", ("shield", "03_shield")),
                ("Dagger / Rapier", ("onehanddagger", "dagger", "rapier")),
                ("Axe / Mace / Hammer", ("onehandaxe", "twohandaxe", "twohandgiantaxe", "onehandmace", "twohandmace", "warhammer", "warhamme", "axe", "mace", "hammer")),
                ("Polearm / Spear", ("onehandspear", "twohandspear", "onehandlance", "lance", "spear", "halberd", "alebard", "pike", "scythe")),
                ("Bow / Crossbow", ("onehandbow", "twohandbow", "bow", "crossbow")),
                ("Firearm", ("pistol", "musket", "shotgun", "cannon", "flamethrower", "icethrower", "lightningthrower", "thrower", "magicbullet", "gatling", "laser")),
                ("Fist / Martial", ("fist", "knuckle")),
                ("Wand / Fan", ("priestwand", "wand", "wingfan")),
                ("Other Weapon", ("weapon",)),
            ),
        ),
        (
            "Armor",
            (
                ("Head", ("helmet", "helm", "_hel", "head", "hood", "hat", "cap", "crown", "circlet", "headdress")),
                ("Face", ("face", "mask", "veil")),
                ("Back / Cloak", ("cloak", "cape", "mantle", "shawl", "back")),
                ("Body", ("armor", "plate", "_ub", "body", "cuirass", "coat", "jacket", "vest", "shirt", "tunic", "robe", "dress", "gown", "mail", "hauberk", "jerkin", "chest")),
                ("Hands", ("glove", "gloves", "hand", "gauntlet", "gauntlets", "bracer", "bracers", "vambrace", "wrist", "sleeve")),
                ("Legs", ("pants", "trouser", "trousers", "skirt", "leg", "legs", "_lb")),
                ("Feet", ("boot", "boots", "foot", "feet", "shoe", "shoes", "sandal", "sabaton", "greave", "greaves", "_sho")),
                ("Other Armor", ("costume", "outfit", "uniform")),
            ),
        ),
        (
            "Accessory",
            (
                ("Earrings", ("earring", "earrings")),
                ("Necklace", ("necklace", "testneck", "neck")),
                ("Ring", ("ring",)),
                ("Amulet / Charm", ("amulet", "charm", "talisman", "pendant", "necklace", "neck")),
                ("Belt / Band", ("belt", "band")),
                ("Other Accessory", ("accessory", "jewelry", "jewel", "glasses", "eyewear")),
            ),
        ),
        (
            "Mount / Pet",
            (
                ("Horse Gear", ("horsegear", "horse gear", "horse", "saddle", "stirrup", "bridle", "mount", "riding")),
                ("Pet Gear", ("petgear", "pet gear", "companionpet")),
                ("Vehicle", ("vehicle",)),
            ),
        ),
        (
            "Consumable",
            (
                ("Potion / Medicine", ("potion", "medicine", "elixir", "tonic", "remedy", "recovery")),
                ("Food / Drink", ("food", "drink", "meal", "bread", "meat", "fruit", "carrot", "pear")),
                ("Other Consumable", ("consumable",)),
            ),
        ),
        (
            "Crafting / Recipe",
            (
                ("Recipe Book", ("recipe", "craftingrecipe", "crafting recipe")),
                ("Crafting", ("craft", "crafting")),
            ),
        ),
        (
            "Tool",
            (
                ("Backpack / Pack", ("backpack", "back_pack", "thrusterpack", "pack")),
                ("Gathering Tool", ("pickaxe", "axe_tool", "gathering", "mining", "lumbering", "drill", "chainsaw", "hoe", "sickle", "trirake", "woodrake", "repairtool")),
                ("Light / Lantern", ("lantern", "torch")),
                ("Fishing", ("fishing", "rod")),
                ("Throwable / Utility", ("bomb", "installationbomb", "bola", "dart")),
                ("Hand Tool", ("broom", "rake", "saw", "stick", "abacus", "pen", "drum", "trumpet", "chain")),
                ("Other Tool", ("tool",)),
            ),
        ),
        (
            "Material",
            (
                ("Ore / Metal", ("ore", "ingot", "metal")),
                ("Cloth / Leather", ("cloth", "leather", "fabric")),
                ("Wood / Stone", ("wood", "stone", "branch")),
                ("Creature Part", ("horn", "tooth", "claw", "scale")),
                ("Crystal / Gem", ("crystal", "gem")),
                ("Other Material", ("material",)),
            ),
        ),
        (
            "Character Customization",
            (
                ("Hair", ("charactercustomize", "hair", "defulthair", "defaulthair", "tiehair")),
                ("Body / Appearance", ("aging", "deaging", "scar", "customize")),
            ),
        ),
        (
            "Gimmick / Interactive",
            (
                ("Gimmick", ("gimmick", "circusmachine")),
                ("Machine Part", ("machine", "core", "tank", "fusion")),
            ),
        ),
        (
            "Housing / Prop",
            (
                ("Furniture", ("furniture", "bookcase", "cabinet", "closet", "chair", "table", "bed", "shelf")),
                ("Decor", ("flowerpot", "pot", "lamp", "picture", "painting", "trophy", "ornament", "doll", "bell", "thurible", "sphere", "globe", "pillar")),
                ("Collection Prop", ("collection_prop", "collection prop", "housing")),
                ("Container", ("chest", "box", "barrel", "crate")),
            ),
        ),
        (
            "Quest / Document",
            (
                ("Quest", ("quest",)),
                ("Key / Permit", ("key", "homekey", "permit", "pass", "visitorpass", "license", "permission")),
                ("Book / Diary", ("book", "diary", "journal", "epistle")),
                ("Map / Treasure", ("map", "treasure", "treasuremap")),
                ("Clue / Report", ("clue", "report", "record", "log", "evidence", "degree")),
                ("Flag / Marker", ("flag", "marker", "picket")),
                ("Document", ("document", "scroll", "letter", "paper", "bundle", "blueprint", "memo", "notepad", "manual")),
                ("Token / Seal", ("token", "seal")),
            ),
        ),
        (
            "Progression / Reward",
            (
                ("Skill", ("skill",)),
                ("Stat", ("stat", "attack", "defense", "resistance", "critical")),
                ("Artifact", ("artifact",)),
                ("Reward", ("reward", "bounty", "income", "contribution")),
                ("Currency", ("money", "gold", "golden", "golden999k", "coin")),
            ),
        ),
    )
    for category, group_tests in category_tests:
        for group, tokens in group_tests:
            if _catalog_text_matches_any(text, tokens):
                return category, group
    return "Item", "Unclassified"


def _catalog_scope_filter_for_item(item: ArchiveItemRecord) -> str:
    patterns: List[str] = []
    seen: set[str] = set()

    def add(value: str, *, wildcard: bool = False) -> None:
        normalized = str(value or "").replace("\\", "/").strip()
        if not normalized:
            return
        if wildcard:
            normalized = f"*{normalized.strip('*')}*"
        lowered = normalized.lower()
        if lowered not in seen:
            patterns.append(normalized)
            seen.add(lowered)

    if item.display_name:
        add(_catalog_display_base(item.display_name) or item.display_name)
    add(item.internal_name)
    for value in (*item.pac_files, *item.model_stems):
        base = os.path.splitext(str(value or "").replace("\\", "/").rsplit("/", 1)[-1])[0]
        add(base, wildcard=True)
    for value in item.icon_paths[:6]:
        base = os.path.splitext(str(value or "").replace("\\", "/").rsplit("/", 1)[-1])[0]
        add(base, wildcard=True)
    return "; ".join(patterns[:18])


def _merge_catalog_entry(existing: ArchiveAssetCatalogEntry, item: ArchiveItemRecord) -> ArchiveAssetCatalogEntry:
    def merged_tuple(*sources: Sequence[str]) -> tuple[str, ...]:
        values: List[str] = []
        seen: set[str] = set()
        for source in sources:
            for raw in source:
                value = str(raw or "").strip()
                lowered = value.lower()
                if value and lowered not in seen:
                    values.append(value)
                    seen.add(lowered)
        return tuple(values)

    display_name = existing.display_name
    item_display_base = _catalog_display_base(item.display_name)
    if item_display_base and (_DISPLAY_VARIANT_SUFFIX_RE.search(display_name) or not display_name):
        display_name = item_display_base
    pac_files = merged_tuple(existing.pac_files, item.pac_files)
    model_stems = merged_tuple(existing.model_stems, item.model_stems)
    icon_paths = merged_tuple(existing.icon_paths, item.icon_paths)
    localized_names = merged_tuple(existing.localized_names, item.localized_names)
    variant_count = existing.variant_count + 1
    scope_item = ArchiveItemRecord(
        item_id=existing.item_id,
        internal_name=existing.internal_name,
        display_name=display_name,
        localized_names=localized_names,
        model_stems=list(model_stems),
        pac_files=list(pac_files),
        icon_paths=list(icon_paths),
    )
    evidence_parts = [existing.evidence]
    if item.icon_paths:
        evidence_parts.append("inventory icon path")
    evidence = "; ".join(part for part in evidence_parts if part)
    return ArchiveAssetCatalogEntry(
        item_id=existing.item_id,
        internal_name=existing.internal_name,
        display_name=display_name or existing.internal_name,
        category=existing.category,
        group=existing.group,
        pac_files=pac_files,
        model_stems=model_stems,
        icon_paths=icon_paths,
        localized_names=localized_names,
        variant_count=variant_count,
        evidence=evidence or existing.evidence,
        scope_filter=_catalog_scope_filter_for_item(scope_item),
    )


def _build_archive_asset_catalog_entries(items: Sequence[ArchiveItemRecord]) -> List[ArchiveAssetCatalogEntry]:
    groups: Dict[str, ArchiveAssetCatalogEntry] = {}
    for item in items:
        display_base = _catalog_display_base(item.display_name)
        internal_base = _catalog_internal_base(item.internal_name)
        identity_basis = display_base.casefold() if display_base else internal_base
        scope_basis = "|".join(sorted(_strip_archive_model_variant_suffix(value) for value in item.pac_files or item.model_stems))
        group_key = f"{identity_basis}|{scope_basis or internal_base}"
        category, catalog_group = _classify_archive_asset_catalog_category_group(item)
        generated_display_name = not bool(display_base or item.display_name)
        evidence_parts = []
        if item.prefab_hashes:
            evidence_parts.append("iteminfo prefab hash")
        if item.model_stems:
            evidence_parts.append("icon/model reference")
        if item.display_name:
            evidence_parts.append("localized display name")
        if generated_display_name:
            evidence_parts.append("generated friendly name")
        if item.icon_paths:
            evidence_parts.append("inventory icon path")
        entry = ArchiveAssetCatalogEntry(
            item_id=item.item_id,
            internal_name=item.internal_name,
            display_name=display_base or item.display_name or _friendly_internal_item_name(item.internal_name),
            category=category,
            group=catalog_group,
            pac_files=tuple(item.pac_files),
            model_stems=tuple(item.model_stems),
            icon_paths=tuple(item.icon_paths),
            localized_names=tuple(item.localized_names),
            variant_count=1,
            evidence="; ".join(evidence_parts) or "item database record",
            scope_filter=_catalog_scope_filter_for_item(item),
        )
        if group_key in groups:
            groups[group_key] = _merge_catalog_entry(groups[group_key], item)
        else:
            groups[group_key] = entry

    return sorted(
        groups.values(),
        key=lambda entry: (
            entry.category.lower(),
            entry.group.lower(),
            entry.display_name.lower(),
            entry.internal_name.lower(),
        ),
    )


def _build_archive_item_search_index_from_records(
    items: Sequence[ArchiveItemRecord],
    model_entries: Sequence[ArchiveEntry],
    *,
    icon_path_index: Optional[Mapping[str, Sequence[str]]] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> ArchiveItemSearchIndex:
    hash_table = _build_archive_model_hash_table_from_entries(model_entries)
    if on_log is not None:
        on_log(f"Item-name search: indexed {len(hash_table):,} model hash candidate(s).")

    pac_to_items: Dict[str, List[ArchiveItemRecord]] = {}
    model_base_aliases: Dict[str, str] = {}
    model_base_display_names: Dict[str, str] = {}
    model_base_exact_display_names: Dict[str, str] = {}
    model_base_related_display_names: Dict[str, str] = {}
    items_with_models: List[ArchiveItemRecord] = []
    icon_index = {str(key).strip().lower(): tuple(value) for key, value in (icon_path_index or {}).items()}

    for item in items:
        exact_model_names: List[str] = []
        related_model_names: List[str] = []
        for prefab_hash in item.prefab_hashes:
            resolved = hash_table.get(prefab_hash)
            if not resolved:
                continue
            if resolved not in exact_model_names:
                exact_model_names.append(resolved)
        for model_stem in item.model_stems:
            normalized_model_stem = _normalize_item_icon_model_stem(model_stem)
            if (
                normalized_model_stem
                and normalized_model_stem not in exact_model_names
                and normalized_model_stem not in related_model_names
            ):
                related_model_names.append(normalized_model_stem)

        icon_paths: List[str] = []
        for resolved in (*exact_model_names, *related_model_names):
            for candidate_key in _iter_archive_model_hash_candidate_bases(resolved):
                for icon_path in icon_index.get(candidate_key, ()):
                    if icon_path not in icon_paths:
                        icon_paths.append(str(icon_path))
        if icon_paths:
            item.icon_paths = icon_paths

        for resolved, match_kind in (
            *((value, "exact") for value in exact_model_names),
            *((value, "related") for value in related_model_names),
        ):
            base = _strip_archive_model_variant_suffix(resolved)
            pac_name = base + ".pac"
            if pac_name not in item.pac_files:
                item.pac_files.append(pac_name)
            pac_to_items.setdefault(pac_name, []).append(item)
            terms = " ".join(
                token
                for token in (
                    item.display_name.lower(),
                    " ".join(name.lower() for name in item.localized_names),
                    item.internal_name.lower(),
                    base.lower(),
                    pac_name.lower(),
                    resolved.lower(),
                )
                if token
            )
            if terms:
                existing = model_base_aliases.get(base, "")
                model_base_aliases[base] = f"{existing} {terms}".strip() if existing else terms
                for root_alias in iter_archive_character_equipment_root_alias_stems(base):
                    existing = model_base_aliases.get(root_alias, "")
                    model_base_aliases[root_alias] = f"{existing} {terms}".strip() if existing else terms
            if item.display_name:
                _add_display_name(model_base_display_names, base, item.display_name)
                for root_alias in iter_archive_character_equipment_root_alias_stems(base):
                    _add_display_name(model_base_display_names, root_alias, item.display_name)
                    _add_display_name(model_base_related_display_names, root_alias, item.display_name)
                if match_kind == "exact":
                    exact_key = _normalize_item_icon_model_stem(resolved)
                    _add_display_name(model_base_exact_display_names, exact_key, item.display_name)
                    if exact_key == base:
                        _add_display_name(model_base_exact_display_names, base, item.display_name)
                else:
                    _add_display_name(model_base_related_display_names, base, item.display_name)
        if item.pac_files:
            items_with_models.append(item)

    if on_log is not None:
        exact_count = len(model_base_exact_display_names)
        related_count = len(model_base_related_display_names)
        on_log(
            "Item-name search: "
            f"linked {len(items_with_models):,} item(s) to model asset(s); "
            f"{exact_count:,} exact name key(s), {related_count:,} related/inferred name key(s)."
        )
        catalog_count = len(_build_archive_asset_catalog_entries(items_with_models))
        if catalog_count:
            on_log(f"Item-name search: built {catalog_count:,} deduped asset catalog row(s).")

    return ArchiveItemSearchIndex(
        items=items_with_models,
        pac_to_items=pac_to_items,
        model_base_aliases=model_base_aliases,
        model_base_display_names=model_base_display_names,
        model_base_exact_display_names=model_base_exact_display_names,
        model_base_related_display_names=model_base_related_display_names,
        asset_catalog=_build_archive_asset_catalog_entries(items_with_models),
    )


def build_archive_item_search_index(
    entries: Sequence[ArchiveEntry],
    *,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> ArchiveItemSearchIndex:
    try:
        sources = _collect_archive_item_index_sources(entries, stop_event=stop_event)
        loc_tables = _parse_archive_localization_tables_from_sources(
            sources,
            on_log=on_log,
            stop_event=stop_event,
        )
        if on_log is not None:
            loaded = ", ".join(f"{language}={len(table):,}" for language, table in loc_tables.items())
            on_log(f"Item-name search: loaded localization tables ({loaded or 'none'}).")
        if sources.iteminfo_entry is None:
            if on_log is not None:
                on_log("Item-name search: iteminfo.pabgb was not found in package 0008.")
            items = []
        else:
            icon_path_index = _build_archive_item_icon_path_index(sources.icon_entries)
            if on_log is not None and icon_path_index:
                path_count = sum(len(paths) for paths in icon_path_index.values())
                on_log(f"Item-name search: indexed {path_count:,} item icon archive path link(s).")
            icon_model_hashes = _parse_archive_stringinfo_model_icon_hashes(
                sources.stringinfo_entry,
                stop_event=stop_event,
            )
            if on_log is not None and icon_model_hashes:
                on_log(f"Item-name search: indexed {len(icon_model_hashes):,} item icon model reference hash(es).")
            items = _parse_archive_iteminfo_entry(
                sources.iteminfo_entry,
                loc_tables,
                icon_model_hashes=icon_model_hashes,
                stop_event=stop_event,
            )
        if on_log is not None:
            on_log(f"Item-name search: parsed {len(items):,} item database record(s).")
    except RunCancelled:
        raise

    return _build_archive_item_search_index_from_records(
        items,
        sources.model_entries,
        icon_path_index=icon_path_index if "icon_path_index" in locals() else {},
        on_log=on_log,
    )
