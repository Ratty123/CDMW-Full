from __future__ import annotations

import fnmatch
import gc
import hashlib
import html
import json
import math
import os
import pickle
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import bisect
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Iterator, Mapping
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Callable, Dict, List, Optional, Sequence, Tuple

try:
    import lz4.block as lz4_block
except ImportError:
    lz4_block = None

try:
    import winreg
except ImportError:
    winreg = None

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
except ImportError:
    Cipher = None
    algorithms = None

from cdmw.constants import *
from cdmw.models import *
from cdmw.core.common import *
from cdmw.core.model_preview import (
    build_pam_model_preview,
    build_pamlod_model_preview,
    ensure_model_preview_is_reasonable,
)
from cdmw.core.archive_modding import (
    build_hkx_descriptor_hint_from_xml_text,
    build_hkx_editable_geometry_document,
    build_hkx_physics_overlay_from_document,
    build_hkx_preview,
    build_mesh_preview_from_bytes,
    build_pab_preview,
    merge_hkx_physics_overlays,
)
from cdmw.core.pipeline import ensure_dds_display_preview_png, inspect_crimson_dds, parse_dds
from cdmw.core.upscale_profiles import (
    classify_texture_type,
    derive_texture_group_key,
    infer_texture_semantics,
    normalize_texture_reference_for_sidecar_lookup,
    parse_material_sidecar_profile,
    parse_texture_sidecar_bindings,
)
from cdmw.core.table_catalog import (
    table_catalog_cache_metadata,
    table_catalog_cache_metadata_matches,
    table_field_label,
)
from cdmw.modding.skeleton_parser import iter_pab_candidate_basenames, parse_pab

if TYPE_CHECKING:
    from cdmw.modding.mesh_parser import ParsedMesh

_PATHC_COLLECTION_CACHE: Dict[str, Tuple[str, "PathcCollection"]] = {}
_ARCHIVE_SCAN_CACHE_MAGIC = b"CTFARCH1"
_ARCHIVE_SCAN_CACHE_VERSION = 2
_ARCHIVE_SCAN_CACHE_LEGACY_DIRNAMES: Tuple[str, ...] = ("cache", "archive_scan_cache")
_ARCHIVE_SIDECAR_CACHE_MAGIC = b"CTFSIDE1"
_ARCHIVE_SIDECAR_CACHE_VERSION = 9
_ARCHIVE_SIDECAR_ENTRY_SIGNATURE_FORMAT = 1
_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC = b"CTFDERI1"
_ARCHIVE_DERIVED_INDEX_CACHE_VERSION = 10
_ARCHIVE_DERIVED_INDEX_CACHE_MAX_SAFE_BYTES = 64 * 1024 * 1024
_INITIAL_MODEL_PREVIEW_RENDER_SETTINGS = clamp_model_preview_render_settings()
# Keep visible base textures closer to their source resolution in the 3D preview.
# Support maps are only sampled for lighting/material approximation. Keep them
# small before the CPU material combiner reads them; large support-map previews
# dominate cold .pac/.pam preview load time without improving the on-screen result.
_MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = _INITIAL_MODEL_PREVIEW_RENDER_SETTINGS.preview_texture_max_dimension
_MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = min(
    256,
    max(128, int(_INITIAL_MODEL_PREVIEW_RENDER_SETTINGS.low_quality_texture_max_dimension)),
)
_MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES: Tuple[str, ...] = (
    "",
    "_d",
    "_diff",
    "_ct",
    "_color",
    "_col",
    "_bc",
    "_albedo",
    "_basecolor",
    "_base_color",
    "_diffuse",
)

_ARCHIVE_SEARCH_DEFAULT_FIELD = "any"
_ARCHIVE_SEARCH_FIELDS = {"any", "path", "name", "ext", "role", "package", "size", "content"}
_ARCHIVE_SEARCH_SIZE_RE = re.compile(r"^(>=|<=|>|<|=)?\s*(\d+(?:\.\d+)?)\s*(b|kb|kib|mb|mib|gb|gib)?$", re.IGNORECASE)


@dataclass(frozen=True)
class ArchiveSearchTerm:
    field: str = _ARCHIVE_SEARCH_DEFAULT_FIELD
    value: str = ""
    negated: bool = False
    phrase: bool = False
    glob: bool = False
    size_operator: str = ""
    size_bytes: int = 0


@dataclass(frozen=True)
class ArchiveSearchQuery:
    groups: Tuple[Tuple[ArchiveSearchTerm, ...], ...] = ()
    raw_text: str = ""

    @property
    def is_empty(self) -> bool:
        return not any(group for group in self.groups)

    @property
    def requires_content_scan(self) -> bool:
        return any(term.field == "content" for group in self.groups for term in group)


def _tokenize_archive_search_text(raw_text: str) -> Tuple[Tuple[str, bool], ...]:
    text = str(raw_text or "")
    tokens: List[Tuple[str, bool]] = []
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index].isspace():
            index += 1
        if index >= length:
            break
        start = index
        phrase = False
        if text[index] == '"':
            phrase = True
            index += 1
            value_chars: List[str] = []
            while index < length:
                char = text[index]
                if char == "\\" and index + 1 < length:
                    value_chars.append(text[index + 1])
                    index += 2
                    continue
                if char == '"':
                    index += 1
                    break
                value_chars.append(char)
                index += 1
            tokens.append(("".join(value_chars), phrase))
            continue
        while index < length and not text[index].isspace():
            if text[index] == '"':
                phrase = True
                index += 1
                while index < length:
                    char = text[index]
                    if char == "\\" and index + 1 < length:
                        index += 2
                        continue
                    if char == '"':
                        index += 1
                        break
                    index += 1
                continue
            index += 1
        token = text[start:index].strip()
        if token:
            tokens.append((token, phrase))
    return tuple(tokens)


def _archive_search_size_to_bytes(value: str) -> Tuple[str, int]:
    match = _ARCHIVE_SEARCH_SIZE_RE.match(str(value or "").strip())
    if not match:
        return "", 0
    operator = match.group(1) or "="
    amount = float(match.group(2))
    unit = (match.group(3) or "b").lower()
    multiplier = 1
    if unit in {"kb", "kib"}:
        multiplier = 1024
    elif unit in {"mb", "mib"}:
        multiplier = 1024 * 1024
    elif unit in {"gb", "gib"}:
        multiplier = 1024 * 1024 * 1024
    return operator, int(amount * multiplier)


def _strip_archive_search_quotes(value: str) -> Tuple[str, bool]:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('\\"', '"'), True
    return text, False


def _archive_search_term_from_token(token: str, phrase: bool, *, negated: bool = False) -> Optional[ArchiveSearchTerm]:
    raw = str(token or "").strip()
    if not raw:
        return None
    if raw.startswith("-") and len(raw) > 1:
        negated = True
        raw = raw[1:].strip()
    field = _ARCHIVE_SEARCH_DEFAULT_FIELD
    value = raw
    if ":" in raw:
        maybe_field, maybe_value = raw.split(":", 1)
        normalized_field = maybe_field.strip().lower()
        if normalized_field in _ARCHIVE_SEARCH_FIELDS:
            field = normalized_field
            value = maybe_value.strip()
    stripped_value, quoted_value = _strip_archive_search_quotes(value)
    phrase = phrase or quoted_value
    value = stripped_value
    if not value and field != "size":
        return None
    glob = any(char in value for char in "*?[]")
    size_operator = ""
    size_bytes = 0
    if field == "size":
        size_operator, size_bytes = _archive_search_size_to_bytes(value)
        if not size_operator:
            return None
    return ArchiveSearchTerm(
        field=field,
        value=value,
        negated=negated,
        phrase=phrase,
        glob=glob,
        size_operator=size_operator,
        size_bytes=size_bytes,
    )


def parse_archive_search_query(filter_text: str) -> ArchiveSearchQuery:
    raw_text = str(filter_text or "")
    if not raw_text.strip():
        return ArchiveSearchQuery(raw_text=raw_text)
    # Preserve legacy include-filter behavior: comma/semicolon/newline separated
    # values are alternatives, not one impossible phrase.
    normalized_text = re.sub(r"[;\r\n,]+", " OR ", raw_text)
    groups: List[List[ArchiveSearchTerm]] = [[]]
    negate_next = False
    for token, phrase in _tokenize_archive_search_text(normalized_text):
        upper = token.upper()
        if upper == "OR":
            if groups[-1]:
                groups.append([])
            negate_next = False
            continue
        if upper == "AND":
            continue
        if upper == "NOT":
            negate_next = True
            continue
        term = _archive_search_term_from_token(token, phrase, negated=negate_next)
        negate_next = False
        if term is not None:
            groups[-1].append(term)
    clean_groups = tuple(tuple(group) for group in groups if group)
    return ArchiveSearchQuery(groups=clean_groups, raw_text=raw_text)


def _archive_search_tokens(text: object) -> Tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", str(text or "").casefold()))


def _archive_search_token_prefix_match(haystack: object, needle: object) -> bool:
    needle_tokens = _archive_search_tokens(needle)
    if not needle_tokens:
        return True
    haystack_tokens = _archive_search_tokens(haystack)
    if not haystack_tokens:
        return False
    return all(
        any(candidate == token if len(token) <= 1 else candidate.startswith(token) for candidate in haystack_tokens)
        for token in needle_tokens
    )


def _archive_search_text_match(haystack: object, term: ArchiveSearchTerm) -> bool:
    text = str(haystack or "").casefold()
    value = str(term.value or "").casefold()
    if not value:
        return True
    if term.glob:
        return fnmatch.fnmatch(text, value)
    if term.phrase:
        haystack_tokens = _archive_search_tokens(text)
        needle_tokens = _archive_search_tokens(value)
        if not needle_tokens:
            return True
        if len(needle_tokens) > len(haystack_tokens):
            return False
        width = len(needle_tokens)
        return any(haystack_tokens[index : index + width] == needle_tokens for index in range(0, len(haystack_tokens) - width + 1))
    return _archive_search_token_prefix_match(text, value)


_ARCHIVE_NAME_SEARCH_COMMON_TERMS: Tuple[str, ...] = (
    "armor",
    "armour",
    "cloak",
    "helmet",
    "helm",
    "shield",
    "belt",
    "vest",
    "mask",
    "upperbody",
    "lowerbody",
    "head",
    "hair",
    "hand",
    "boot",
    "shoe",
    "glove",
    "saddle",
    "backpack",
    "bag",
    "weapon",
    "sword",
    "axe",
    "bow",
    "crossbow",
    "dagger",
    "knife",
    "spear",
    "mace",
    "hammer",
    "staff",
    "gun",
    "cannon",
    "bomb",
    "torch",
    "lantern",
    "lamp",
    "candle",
    "forge",
    "chest",
    "treasure",
    "box",
    "barrel",
    "crate",
    "pot",
    "jar",
    "basket",
    "book",
    "scroll",
    "map",
    "coin",
    "gold",
    "silver",
    "house",
    "roof",
    "wall",
    "floor",
    "door",
    "window",
    "gate",
    "fence",
    "bridge",
    "stairs",
    "ladder",
    "pillar",
    "statue",
    "tent",
    "camp",
    "dungeon",
    "cave",
    "shop",
    "farm",
    "horse",
    "camel",
    "mount",
    "wagon",
    "cart",
    "wheel",
    "boat",
    "ship",
    "tree",
    "bush",
    "grass",
    "flower",
    "plant",
    "mushroom",
    "wood",
    "log",
    "stone",
    "rock",
    "ore",
    "crystal",
    "water",
    "river",
    "lake",
    "desert",
    "swamp",
    "snow",
    "animal",
    "monster",
    "dog",
    "cat",
    "wolf",
    "bear",
    "deer",
    "sheep",
    "cow",
    "pig",
    "bird",
    "fish",
    "spider",
    "dragon",
    "golem",
    "flag",
    "banner",
    "rope",
    "chain",
    "fire",
    "trap",
    "puzzle",
    "mine",
    "castle",
    "temple",
    "tower",
)
_ARCHIVE_NAME_SEARCH_TOKEN_ALIASES: Dict[str, Tuple[str, ...]] = {
    "armor": ("armour",),
    "armour": ("armor",),
    "helmet": ("helm",),
    "helm": ("helmet",),
    "pickaxe": ("axe",),
    "crossbow": ("bow",),
    "treasurebox": ("treasure", "box"),
    "campfire": ("camp", "fire"),
    "candlestick": ("candle", "lamp"),
}
_ARCHIVE_NAME_SEARCH_QUERY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "armor": ("armour",),
    "armour": ("armor",),
    "helmet": ("helm",),
    "helm": ("helmet",),
}
_ARCHIVE_NAME_SEARCH_INDEXABLE_FIELDS = {_ARCHIVE_SEARCH_DEFAULT_FIELD, "path", "name"}


def _archive_name_search_embedded_source_tokens(token: str) -> Tuple[str, ...]:
    normalized = str(token or "").casefold()
    if not normalized:
        return ()
    return tuple(
        source_token
        for source_token in _ARCHIVE_NAME_SEARCH_TOKEN_ALIASES
        if len(source_token) > 4 and source_token in normalized and source_token != normalized
    )


def _archive_name_search_aliases_for_token(token: str) -> Tuple[str, ...]:
    normalized = str(token or "").casefold()
    if not normalized:
        return ()
    aliases: List[str] = []
    seen: set[str] = set()
    for source_token, source_aliases in _ARCHIVE_NAME_SEARCH_TOKEN_ALIASES.items():
        if normalized != source_token and (len(source_token) <= 4 or source_token not in normalized):
            continue
        for alias in source_aliases:
            alias_token = str(alias or "").casefold()
            if alias_token and alias_token not in seen:
                aliases.append(alias_token)
                seen.add(alias_token)
    return tuple(aliases)


def _archive_name_search_token_matches(candidate: str, query_token: str) -> bool:
    candidate_token = str(candidate or "").casefold()
    token = str(query_token or "").casefold()
    if not candidate_token or not token:
        return False
    if (candidate_token == token) if len(token) <= 1 else candidate_token.startswith(token):
        return True
    for source_token in _archive_name_search_embedded_source_tokens(candidate_token):
        if (source_token == token) if len(token) <= 1 else source_token.startswith(token):
            return True
    for alias in _archive_name_search_aliases_for_token(candidate_token):
        alias_token = str(alias or "").casefold()
        if (alias_token == token) if len(token) <= 1 else alias_token.startswith(token):
            return True
    return False


def _archive_name_search_text_match(haystack: object, term: ArchiveSearchTerm) -> bool:
    if _archive_search_text_match(haystack, term):
        return True
    if term.glob or term.phrase:
        return False
    needle_tokens = _archive_search_tokens(term.value)
    if not needle_tokens:
        return True
    haystack_tokens = _archive_search_tokens(haystack)
    if not haystack_tokens:
        return False
    return all(
        any(_archive_name_search_token_matches(candidate, needle) for candidate in haystack_tokens)
        for needle in needle_tokens
    )


@dataclass(frozen=True)
class ArchiveNameSearchIndex:
    entries: Sequence[ArchiveEntry]
    token_rows: Mapping[str, Tuple[int, ...]]
    sorted_tokens: Tuple[str, ...]
    common_aliases: Mapping[str, Tuple[str, ...]]

    @property
    def row_count(self) -> int:
        return len(self.token_rows)

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    def expanded_query_tokens(self, token: str) -> Tuple[str, ...]:
        normalized = str(token or "").casefold()
        if not normalized:
            return ()
        expanded = [normalized]
        seen = {normalized}
        for alias in self.common_aliases.get(normalized, ()):
            alias_token = str(alias or "").casefold()
            if alias_token and alias_token not in seen:
                expanded.append(alias_token)
                seen.add(alias_token)
        return tuple(expanded)

    def rows_for_token(self, token: str) -> Tuple[int, ...]:
        rows: set[int] = set()
        for expanded_token in self.expanded_query_tokens(token):
            if len(expanded_token) <= 1:
                rows.update(self.token_rows.get(expanded_token, ()))
                continue
            start = bisect.bisect_left(self.sorted_tokens, expanded_token)
            end = bisect.bisect_left(self.sorted_tokens, expanded_token + "\uffff")
            for indexed_token in self.sorted_tokens[start:end]:
                rows.update(self.token_rows.get(indexed_token, ()))
        return tuple(sorted(rows))

    def rows_for_term(self, term: ArchiveSearchTerm) -> Optional[Tuple[int, ...]]:
        if term.negated or term.glob:
            return None
        if str(term.field or _ARCHIVE_SEARCH_DEFAULT_FIELD).lower() not in _ARCHIVE_NAME_SEARCH_INDEXABLE_FIELDS:
            return None
        token_groups = [
            self.rows_for_token(token)
            for token in _archive_search_tokens(term.value)
            if len(token) > 1
        ]
        if not token_groups:
            return None
        candidate_rows = set(token_groups[0])
        for rows in token_groups[1:]:
            candidate_rows.intersection_update(rows)
            if not candidate_rows:
                break
        return tuple(sorted(candidate_rows))

    def rows_for_query(self, query: ArchiveSearchQuery) -> Optional[Tuple[int, ...]]:
        if query.is_empty or query.requires_content_scan:
            return None
        query_rows: set[int] = set()
        narrowed_any_group = False
        for group in query.groups:
            group_rows: Optional[set[int]] = None
            positive_count = 0
            usable_count = 0
            for term in group:
                if term.negated:
                    continue
                positive_count += 1
                rows = self.rows_for_term(term)
                if rows is None:
                    continue
                usable_count += 1
                if group_rows is None:
                    group_rows = set(rows)
                else:
                    group_rows.intersection_update(rows)
                if not group_rows:
                    break
            if positive_count == 0 or usable_count == 0:
                return None
            narrowed_any_group = True
            if group_rows:
                query_rows.update(group_rows)
        if not narrowed_any_group:
            return None
        return tuple(sorted(query_rows))

    def entries_for_query(
        self,
        entries: Sequence[ArchiveEntry],
        query: ArchiveSearchQuery,
    ) -> Optional[List[ArchiveEntry]]:
        rows = self.rows_for_query(query)
        if rows is None:
            return None
        if entries is self.entries:
            return [self.entries[index] for index in rows if 0 <= index < len(self.entries)]
        allowed_ids = {id(entry) for entry in entries}
        return [
            self.entries[index]
            for index in rows
            if 0 <= index < len(self.entries) and id(self.entries[index]) in allowed_ids
        ]


def build_archive_name_search_index(
    entries: Sequence[ArchiveEntry],
    *,
    item_search_aliases: Optional[Mapping[str, str]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> ArchiveNameSearchIndex:
    token_rows: Dict[str, List[int]] = defaultdict(list)
    total_entries = len(entries)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000

    def add_token(rows: Dict[str, List[int]], token: str, entry_index: int) -> None:
        normalized = str(token or "").casefold()
        if len(normalized) <= 1:
            return
        rows[normalized].append(entry_index)
        for source_token in _archive_name_search_embedded_source_tokens(normalized):
            rows[source_token].append(entry_index)
        for alias_token in _archive_name_search_aliases_for_token(normalized):
            alias_normalized = str(alias_token or "").casefold()
            if len(alias_normalized) > 1:
                rows[alias_normalized].append(entry_index)

    if on_progress:
        on_progress(0 if total_entries > 0 else 1, max(total_entries, 1), f"Building archive name search index... 0 / {total_entries:,} entries")
    for entry_index, entry in enumerate(entries):
        if stop_event is not None and (entry_index == 0 or entry_index % 2048 == 0):
            raise_if_cancelled(stop_event)
        text = f"{entry.path} {entry.basename}"
        alias_text = _archive_entry_item_alias_text(entry, item_search_aliases)
        if alias_text:
            text = f"{text} {alias_text}"
        seen_tokens: set[str] = set()
        for token in _archive_search_tokens(text):
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            add_token(token_rows, token, entry_index)
        if on_progress and (
            entry_index == 0
            or (entry_index + 1) % update_every == 0
            or entry_index + 1 == total_entries
        ):
            on_progress(
                entry_index + 1,
                max(total_entries, 1),
                f"Building archive name search index... {entry_index + 1:,} / {total_entries:,} entries",
            )

    frozen_rows = {
        token: tuple(sorted(set(rows)))
        for token, rows in token_rows.items()
        if token
    }
    return ArchiveNameSearchIndex(
        entries=entries,
        token_rows=frozen_rows,
        sorted_tokens=tuple(sorted(frozen_rows)),
        common_aliases=_ARCHIVE_NAME_SEARCH_QUERY_ALIASES,
    )


class LazyArchiveEntryRowIndex(Mapping[str, Sequence[ArchiveEntry]]):
    def __init__(
        self,
        rows: Optional[Dict[str, Tuple[int, ...]]],
        entries: Sequence[ArchiveEntry],
    ) -> None:
        self._rows: Dict[str, Tuple[int, ...]] = {
            str(key or "").strip().lower(): tuple(int(index) for index in value)
            for key, value in (rows or {}).items()
            if str(key or "").strip()
        }
        self._entries = entries
        self._resolved: OrderedDict[str, Tuple[ArchiveEntry, ...]] = OrderedDict()
        self._resolved_limit = 4096

    def __getitem__(self, key: str) -> Sequence[ArchiveEntry]:
        normalized_key = str(key or "").strip().lower()
        if normalized_key not in self._rows:
            raise KeyError(key)
        cached = self._resolved.get(normalized_key)
        if cached is not None:
            self._resolved.move_to_end(normalized_key)
            return cached
        resolved_entries: List[ArchiveEntry] = []
        seen_indexes: set[int] = set()
        for raw_index in self._rows.get(normalized_key, ()):
            entry_index = int(raw_index)
            if entry_index < 0 or entry_index >= len(self._entries) or entry_index in seen_indexes:
                continue
            seen_indexes.add(entry_index)
            resolved_entries.append(self._entries[entry_index])
        resolved_tuple = tuple(resolved_entries)
        self._resolved[normalized_key] = resolved_tuple
        self._resolved.move_to_end(normalized_key)
        while len(self._resolved) > self._resolved_limit:
            self._resolved.popitem(last=False)
        return resolved_tuple

    def __iter__(self) -> Iterator[str]:
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)

    def get(self, key: object, default: Optional[Sequence[ArchiveEntry]] = None) -> Optional[Sequence[ArchiveEntry]]:
        normalized_key = str(key or "").strip().lower()
        if normalized_key not in self._rows:
            return default
        return self[normalized_key]

    @property
    def row_count(self) -> int:
        return len(self._rows)
_MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "normal": (
        "_n",
        "_normal",
        "_normalmap",
    ),
    "material": (
        "_sp",
        "_material",
        "_mask",
        "_ma",
        "_mg",
        "_m",
        "_orm",
        "_mra",
        "_rma",
        "_arm",
        "_ao",
        "_spec",
        "_specular",
    ),
    "height": (
        "_disp",
        "_displacement",
        "_height",
        "_hgt",
        "_dmap",
        "_bump",
        "_parallax",
        "_pom",
        "_ssdm",
    ),
}


def set_model_texture_display_preview_max_dimension(
    value: int,
    *,
    low_quality_value: Optional[int] = None,
) -> None:
    global _MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION, _MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION
    settings = clamp_model_preview_render_settings(
        ModelPreviewRenderSettings(
            preview_texture_max_dimension=int(value),
            low_quality_texture_max_dimension=(
                int(low_quality_value)
                if low_quality_value is not None
                else ModelPreviewRenderSettings().low_quality_texture_max_dimension
            ),
        )
    )
    _MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = int(settings.preview_texture_max_dimension)
    _MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = min(
        256,
        max(128, int(settings.low_quality_texture_max_dimension)),
    )
_ARCHIVE_TEXTURE_FAMILY_SUFFIXES: Tuple[str, ...] = (
    "",
    "_ct",
    "_color",
    "_col",
    "_albedo",
    "_basecolor",
    "_base_color",
    "_diffuse",
    "_n",
    "_normal",
    "_normalmap",
    "_sp",
    "_spec",
    "_specular",
    "_m",
    "_mask",
    "_ma",
    "_mg",
    "_orm",
    "_mra",
    "_rma",
    "_arm",
    "_ao",
    "_o",
    "_height",
    "_hgt",
    "_disp",
    "_displacement",
    "_dmap",
    "_d",
    "_bump",
    "_parallax",
    "_pom",
    "_ssdm",
    "_em",
    "_emi",
    "_emissive",
    "_glow",
    "_material",
    "_mat",
)
_ARCHIVE_MODEL_FAMILY_VARIANT_SUFFIXES: Tuple[str, ...] = (
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
_ARCHIVE_ITEM_ICON_STEM_PREFIXES: Tuple[str, ...] = (
    "itemicon_prefab_",
    "itemicon_",
    "icon_prefab_",
    "icon_",
)
_ARCHIVE_ATTACHMENT_SIDE_SUFFIXES: Tuple[str, ...] = ("_l", "_r")
_ARCHIVE_ATTACHMENT_SIDE_METADATA_EXTENSIONS: Tuple[str, ...] = (
    ".prefab",
    ".prefabdata.xml",
    ".prefabdata_xml",
    ".pappt",
    ".pamhc",
    ".sockets.xml",
)
_ARCHIVE_NUMBERED_MODEL_FAMILY_VARIANT_RE = re.compile(r"_(?:index|sub)\d{2}$", re.IGNORECASE)
_ARCHIVE_PREFAB_HELM_DESCRIPTOR_RE = re.compile(
    r"^(?P<prefix>cd_)phm_(?P<variant>\d{2})_hel_(?P<rest>.+)$",
    re.IGNORECASE,
)
_ARCHIVE_PLATE_HELM_MODEL_RE = re.compile(
    r"^(?P<prefix>cd_)ptm_(?P<variant>\d{2})_hel_(?P<rest>.+)$",
    re.IGNORECASE,
)
_ARCHIVE_CHARACTER_EQUIPMENT_COMPONENT_RE = re.compile(
    r"^(?P<root>cd_[a-z]\d{4}_\d{2}_.+?)_"
    r"(?P<part>ub|lb|hel|sho|hand|foot|belt|vest|mask|cloak|cape|hair|head|face|acc|body|arm|leg)"
    r"(?:_[a-z0-9]+)*_\d{4}(?:_\d+)?$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class _ArchiveModelSidecarTextureBinding:
    texture_path: str
    parameter_name: str = ""
    submesh_name: str = ""
    sidecar_path: str = ""
    sidecar_kind: str = ""
    linked_mesh_path: str = ""
    part_name: str = ""
    material_name: str = ""
    shader_family: str = ""
    texture_role: str = ""
    visualization_state: str = ""
    resolved_texture_exists: bool = False
    represent_color: Tuple[float, float, float] = ()
    tint_color: Tuple[float, float, float] = ()
    brightness: float = 1.0
    uv_scale: float = 1.0
    tile_type: str = ""
    material_parameters: Tuple[PreviewMaterialParameterInput, ...] = ()


@dataclass(slots=True)
class _StructuredBinaryPreviewBundle:
    preview_text: str
    detail_lines: Tuple[str, ...] = ()
    related_references: Tuple[ArchiveModelTextureReference, ...] = ()
    metadata_label: str = ""


@dataclass(slots=True)
class _BinarySidecarStringRecord:
    offset: int
    text: str


_MODEL_SIDECAR_PARSE_CACHE_LIMIT = 512
_MODEL_SIDECAR_PARSE_CACHE: OrderedDict[
    Tuple[object, ...],
    Tuple[Tuple["_ArchiveModelSidecarTextureBinding", ...], Tuple[str, ...], Dict[str, Tuple[str, ...]], Dict[str, Tuple[str, ...]]],
] = OrderedDict()
_MODEL_SIDECAR_REFERENCE_CACHE_LIMIT = 256
_MODEL_SIDECAR_REFERENCE_CACHE: OrderedDict[
    Tuple[object, ...],
    Tuple[Tuple["_ArchiveModelSidecarTextureBinding", ...], Tuple[str, ...], Dict[str, Tuple[str, ...]], Dict[str, Tuple[str, ...]]],
] = OrderedDict()
_MODEL_SIDECAR_PARSE_CACHE_LOCK = threading.Lock()
_MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT = 2048
_MODEL_TEXTURE_PREVIEW_PATH_CACHE: OrderedDict[Tuple[object, ...], str] = OrderedDict()
_MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK = threading.Lock()

_COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS: Tuple[str, ...] = (
    "*_n.dds",
    "*_nm.dds",
    "*_nrm.dds",
    "*_normal.dds",
    "*_normalmap.dds",
    "*_sp.dds",
    "*_spec.dds",
    "*_specular.dds",
    "*_m.dds",
    "*_mask.dds",
    "*_orm.dds",
    "*_rma.dds",
    "*_mra.dds",
    "*_arm.dds",
    "*_ao.dds",
    "*_metal.dds",
    "*_metallic.dds",
    "*_rough.dds",
    "*_roughness.dds",
    "*_gloss.dds",
    "*_smooth.dds",
    "*_height.dds",
    "*_hgt.dds",
    "*_disp.dds",
    "*_displacement.dds",
    "*_dmap.dds",
    "*_bump.dds",
    "*_parallax.dds",
    "*_pom.dds",
    "*_ssdm.dds",
    "*_vector.dds",
    "*_dr.dds",
    "*_op.dds",
    "*_wn.dds",
    "*_flow.dds",
    "*_velocity.dds",
    "*_pos.dds",
    "*_position.dds",
    "*_pivot.dds",
    "*_depth.dds",
    "*_pivotpos.dds",
    "*_ma.dds",
    "*_mg.dds",
    "*_o.dds",
    "*_emi.dds",
    "*_emc.dds",
    "*_subsurface.dds",
    "*_1bit.dds",
    "*_mask_amg.dds",
    "*_d.dds",
)
_STRUCTURED_BINARY_IDENTIFIER_RE = re.compile(r"^[_A-Za-z][A-Za-z0-9_:<>-]{2,127}$")
_STRUCTURED_BINARY_ASSET_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\\-]+")
_STRUCTURED_BINARY_ASSET_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".dds",
        ".xml",
        ".pac_xml",
        ".pam_xml",
        ".pamlod_xml",
        ".prefabdata_xml",
        ".pami",
        ".meshinfo",
        ".hkx",
        ".hkt",
        ".pam",
        ".pamlod",
        ".pac",
        ".pab",
        ".pabc",
        ".pabv",
        ".pabgb",
        ".pabgh",
        ".pamhc",
        ".pappt",
        ".papr",
        ".paa",
        ".paa_metabin",
        ".pae",
        ".paem",
        ".paseq",
        ".paschedule",
        ".paschedulepath",
        ".pastage",
        ".prefab",
        ".levelinfo",
        ".palevel",
        ".roadsector",
        ".road",
        ".nav",
        ".seqmt",
        ".wem",
        ".bnk",
        ".mp4",
        ".bk2",
        ".json",
    }
)
_ARCHIVE_STRUCTURED_BINARY_PREVIEW_EXTENSIONS: Tuple[str, ...] = (
    ".bnk",
    ".binarygimmick",
    ".hkx",
    ".levelinfo",
    ".meshinfo",
    ".motionblending",
    ".paa",
    ".pae",
    ".paa_metabin",
    ".pabgb",
    ".pabgh",
    ".pabc",
    ".pabv",
    ".pamhc",
    ".pappt",
    ".paem",
    ".pagbg",
    ".pampg",
    ".palevel",
    ".paseq",
    ".paschedule",
    ".paschedulepath",
    ".pastage",
    ".uianiminit",
    ".pamlod",
    ".prefab",
    ".roadsector",
    ".road",
    ".nav",
    ".seqmt",
    ".wem",
)
_ARCHIVE_SCAN_CACHE_SUPPORTED_VERSIONS = {1, 2}
_ARCHIVE_SIDECAR_CACHE_SUPPORTED_VERSIONS = {8, 9}
_ARCHIVE_DERIVED_INDEX_CACHE_SUPPORTED_VERSIONS = {10}
CHACHA20_HASH_INITVAL = 0x000C5EDE
CHACHA20_IV_XOR = 0x60616263
CHACHA20_XOR_DELTAS = (
    0x00000000,
    0x0A0A0A0A,
    0x0C0C0C0C,
    0x06060606,
    0x0E0E0E0E,
    0x0A0A0A0A,
    0x06060606,
    0x02020202,
)

_ARCHIVE_MATERIAL_SIDECAR_EXTENSIONS: frozenset[str] = frozenset({".pami", ".pac_xml", ".pam_xml", ".pamlod_xml"})
_ARCHIVE_METADATA_XML_EXTENSIONS: frozenset[str] = frozenset({".xml", ".app_xml", ".prefabdata_xml"})
_ARCHIVE_XML_LIKE_EXTENSIONS: frozenset[str] = _ARCHIVE_MATERIAL_SIDECAR_EXTENSIONS | _ARCHIVE_METADATA_XML_EXTENSIONS
_ARCHIVE_SCAN_IGNORED_TOP_LEVEL_DIRS: frozenset[str] = frozenset({"cdmods"})
_ARCHIVE_SIDECAR_TEXTURE_ATTR_RE = re.compile(
    r"""\b(?:_path|path|Path|Value|_value|value|File|file|_file|Texture|texture)\s*=\s*(['"])(?P<value>[^'"<>]{1,1024}?\.(?:dds|png|jpg|jpeg|tga|bmp|tif|tiff))\1""",
    re.IGNORECASE,
)
_ARCHIVE_TEXTURE_BYTES_RE = re.compile(br"\.(?:dds|png|jpg|jpeg|tga|bmp|tif|tiff)", re.IGNORECASE)


def _is_material_sidecar_extension(extension: str, basename: str = "") -> bool:
    normalized_extension = str(extension or "").strip().lower()
    normalized_basename = str(basename or "").strip().lower()
    if normalized_extension in _ARCHIVE_MATERIAL_SIDECAR_EXTENSIONS:
        return True
    if normalized_extension == ".xml" and normalized_basename.endswith((".pac.xml", ".pam.xml", ".pamlod.xml")):
        return True
    return False
_PRINTABLE_BINARY_STRING_RE = re.compile(rb"[\x20-\x7E]{4,}")
_TEXT_DDS_REFERENCE_RE = re.compile(r"[A-Za-z0-9_./\\-]{3,255}\.dds", re.IGNORECASE)

def _rot32(value: int, shift: int) -> int:
    value &= 0xFFFFFFFF
    return ((value << shift) | (value >> (32 - shift))) & 0xFFFFFFFF


def _add32(a: int, b: int) -> int:
    return (a + b) & 0xFFFFFFFF


def _sub32(a: int, b: int) -> int:
    return (a - b) & 0xFFFFFFFF


def _finalize_lookup3(a: int, b: int, c: int) -> Tuple[int, int, int]:
    c = _sub32(c ^ b, _rot32(b, 14))
    a = _sub32(a ^ c, _rot32(c, 11))
    b = _sub32(b ^ a, _rot32(a, 25))
    c = _sub32(c ^ b, _rot32(b, 16))
    a = _sub32(a ^ c, _rot32(c, 4))
    b = _sub32(b ^ a, _rot32(a, 14))
    c = _sub32(c ^ b, _rot32(b, 24))
    return a, b, c


def calculate_pa_checksum(value: bytes | str) -> int:
    data = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    length = len(data)
    remaining = length
    a = b = c = _add32(length, 0xDEBA1DCD)
    offset = 0

    while remaining > 12:
        a = _add32(a, struct.unpack_from("<I", data, offset)[0])
        b = _add32(b, struct.unpack_from("<I", data, offset + 4)[0])
        c = _add32(c, struct.unpack_from("<I", data, offset + 8)[0])
        a = _sub32(a, c)
        a ^= _rot32(c, 4)
        c = _add32(c, b)
        b = _sub32(b, a)
        b ^= _rot32(a, 6)
        a = _add32(a, c)
        c = _sub32(c, b)
        c ^= _rot32(b, 8)
        b = _add32(b, a)
        a = _sub32(a, c)
        a ^= _rot32(c, 16)
        c = _add32(c, b)
        b = _sub32(b, a)
        b ^= _rot32(a, 19)
        a = _add32(a, c)
        c = _sub32(c, b)
        c ^= _rot32(b, 4)
        b = _add32(b, a)
        offset += 12
        remaining -= 12

    if remaining == 0:
        return c

    tail = data[offset:] + (b"\x00" * (12 - remaining))
    a = _add32(a, struct.unpack_from("<I", tail, 0)[0])
    b = _add32(b, struct.unpack_from("<I", tail, 4)[0])
    c = _add32(c, struct.unpack_from("<I", tail, 8)[0])
    _, _, c = _finalize_lookup3(a, b, c)
    return c


def hashlittle(data: bytes, initval: int = 0) -> int:
    length = len(data)
    remaining = length
    a = b = c = _add32(0xDEADBEEF + length, initval)
    offset = 0

    while remaining > 12:
        a = _add32(a, struct.unpack_from("<I", data, offset)[0])
        b = _add32(b, struct.unpack_from("<I", data, offset + 4)[0])
        c = _add32(c, struct.unpack_from("<I", data, offset + 8)[0])
        a = _sub32(a, c)
        a ^= _rot32(c, 4)
        c = _add32(c, b)
        b = _sub32(b, a)
        b ^= _rot32(a, 6)
        a = _add32(a, c)
        c = _sub32(c, b)
        c ^= _rot32(b, 8)
        b = _add32(b, a)
        a = _sub32(a, c)
        a ^= _rot32(c, 16)
        c = _add32(c, b)
        b = _sub32(b, a)
        b ^= _rot32(a, 19)
        a = _add32(a, c)
        c = _sub32(c, b)
        c ^= _rot32(b, 4)
        b = _add32(b, a)
        offset += 12
        remaining -= 12

    tail = data[offset:] + (b"\x00" * 12)
    if remaining >= 12:
        c = _add32(c, struct.unpack_from("<I", tail, 8)[0])
    elif remaining >= 9:
        c = _add32(c, struct.unpack_from("<I", tail, 8)[0] & (0xFFFFFFFF >> (8 * (12 - remaining))))
    if remaining >= 8:
        b = _add32(b, struct.unpack_from("<I", tail, 4)[0])
    elif remaining >= 5:
        b = _add32(b, struct.unpack_from("<I", tail, 4)[0] & (0xFFFFFFFF >> (8 * (8 - remaining))))
    if remaining >= 4:
        a = _add32(a, struct.unpack_from("<I", tail, 0)[0])
    elif remaining >= 1:
        a = _add32(a, struct.unpack_from("<I", tail, 0)[0] & (0xFFFFFFFF >> (8 * (4 - remaining))))
    elif remaining == 0:
        return c

    c = _sub32(c ^ b, _rot32(b, 14))
    a = _sub32(a ^ c, _rot32(c, 11))
    b = _sub32(b ^ a, _rot32(a, 25))
    c = _sub32(c ^ b, _rot32(b, 16))
    a = _sub32(a ^ c, _rot32(c, 4))
    b = _sub32(b ^ a, _rot32(a, 14))
    c = _sub32(c ^ b, _rot32(b, 24))
    return c


def derive_chacha20_key_iv(filename: str) -> Tuple[bytes, bytes]:
    basename = Path(filename).name.lower().encode("utf-8", errors="replace")
    seed = hashlittle(basename, CHACHA20_HASH_INITVAL)
    nonce = struct.pack("<I", seed) * 4
    key_base = seed ^ CHACHA20_IV_XOR
    key = b"".join(struct.pack("<I", key_base ^ delta) for delta in CHACHA20_XOR_DELTAS)
    return key, nonce


def crypt_chacha20_filename(data: bytes, filename: str) -> bytes:
    if Cipher is None or algorithms is None:
        raise ValueError(
            "ChaCha20 support requires the cryptography package. Install it with: pip install cryptography"
        )
    key, nonce = derive_chacha20_key_iv(filename)
    cipher = Cipher(algorithms.ChaCha20(key, nonce), mode=None)
    return cipher.encryptor().update(data)


def _looks_like_plain_text_payload(data: bytes) -> bool:
    return try_decode_text_like_archive_data(data) is not None


def _looks_like_paloc_payload(data: bytes) -> bool:
    if len(data) < 16:
        return False
    pos = 0
    matches = 0
    scan_limit = min(len(data), 4_000_000)
    while pos + 8 < scan_limit and matches < 8:
        try:
            slen = struct.unpack_from("<I", data, pos)[0]
        except struct.error:
            break
        if slen == 0 or slen > 50_000 or pos + 4 + slen > len(data):
            pos += 1
            continue
        key_bytes = data[pos + 4 : pos + 4 + slen]
        if not (6 <= slen <= 20 and all(0x30 <= value <= 0x39 for value in key_bytes)):
            pos += 1
            continue
        text_pos = pos + 4 + slen
        if text_pos + 4 >= len(data):
            pos += 1
            continue
        text_len = struct.unpack_from("<I", data, text_pos)[0]
        if not (0 < text_len < 50_000 and text_pos + 4 + text_len <= len(data)):
            pos += 1
            continue
        text_bytes = data[text_pos + 4 : text_pos + 4 + text_len]
        try:
            text_bytes.decode("utf-8")
        except UnicodeDecodeError:
            pos += 1
            continue
        matches += 1
        pos = text_pos + 4 + text_len
    return matches >= 2


def _looks_like_structured_binary_payload(extension: str, data: bytes) -> bool:
    head4 = data[:4]
    if extension == ".dds" and data.startswith(DDS_MAGIC):
        return True
    if head4 in {b"PAR ", b"PARC"}:
        return True
    if len(data) >= 16 and data[4:8] == b"TAG0" and data[12:16] == b"SDKV":
        return True
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return True
    return len(extract_binary_strings(data, sample_limit=16_384, max_strings=10)) >= 3


def _looks_like_decrypted_payload(entry: ArchiveEntry, data: bytes) -> bool:
    candidate = data
    if entry.compression_type == 2:
        if lz4_block is None:
            return False
        try:
            candidate = lz4_block.decompress(data, uncompressed_size=entry.orig_size)
        except Exception:
            return False
    elif entry.compression_type == 1 and entry.extension == ".dds":
        try:
            candidate = reconstruct_partial_dds(entry, data)
        except Exception:
            return False
    if entry.extension == ".paloc" and _looks_like_paloc_payload(candidate):
        return True
    if _looks_like_plain_text_payload(candidate):
        return True
    if entry.extension in _ARCHIVE_STRUCTURED_BINARY_PREVIEW_EXTENSIONS or entry.extension in ARCHIVE_MODEL_EXTENSIONS:
        return _looks_like_structured_binary_payload(entry.extension, candidate)
    return entry.extension == ".dds" and candidate.startswith(DDS_MAGIC)


def try_decrypt_archive_entry_data(entry: ArchiveEntry, data: bytes) -> Tuple[bytes, Optional[str]]:
    if not entry.encrypted:
        return data, None
    if entry.encryption_type != 3:
        raise ValueError(f"Unsupported archive encryption type {entry.encryption_type} for {entry.path}")
    candidate = crypt_chacha20_filename(data, entry.basename)
    if not _looks_like_decrypted_payload(entry, candidate):
        if entry.extension in _ARCHIVE_XML_LIKE_EXTENSIONS and _looks_like_decrypted_payload(entry, data):
            return data, "ChaCha20FlagMismatch"
        raise ValueError(f"ChaCha20 decryption validation failed for {entry.path}")
    return candidate, "ChaCha20"

def discover_pamt_files(package_root: Path) -> List[Path]:
    root = package_root.expanduser().resolve()
    if root.is_file() and root.suffix.lower() == ".pamt":
        return [root]
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Archive package root does not exist or is not a folder: {root}")
    files: List[Path] = []
    for path in root.rglob("*.pamt"):
        if not path.is_file():
            continue
        try:
            top_level_dir = path.relative_to(root).parts[0].lower()
        except (IndexError, ValueError):
            top_level_dir = ""
        if top_level_dir in _ARCHIVE_SCAN_IGNORED_TOP_LEVEL_DIRS:
            continue
        files.append(path)
    files.sort()
    return files


def resolve_archive_scan_cache_path(package_root: Path, cache_root: Path) -> Path:
    try:
        resolved_root = package_root.expanduser().resolve()
    except OSError:
        resolved_root = package_root.expanduser()
    digest = hashlib.sha256(str(resolved_root).lower().encode("utf-8", errors="replace")).hexdigest()[:24]
    return cache_root / f"archive_scan_{digest}.bin"


def resolve_archive_sidecar_cache_path(package_root: Path, cache_root: Path) -> Path:
    try:
        resolved_root = package_root.expanduser().resolve()
    except OSError:
        resolved_root = package_root.expanduser()
    digest = hashlib.sha256(str(resolved_root).lower().encode("utf-8", errors="replace")).hexdigest()[:24]
    return cache_root / f"archive_sidecars_{digest}.bin"


def resolve_archive_sidecar_cache_metadata_path(package_root: Path, cache_root: Path) -> Path:
    return resolve_archive_sidecar_cache_path(package_root, cache_root).with_suffix(".meta.json")


def resolve_archive_derived_index_cache_path(package_root: Path, cache_root: Path) -> Path:
    try:
        resolved_root = package_root.expanduser().resolve()
    except OSError:
        resolved_root = package_root.expanduser()
    digest = hashlib.sha256(str(resolved_root).lower().encode("utf-8", errors="replace")).hexdigest()[:24]
    return cache_root / f"archive_derived_indexes_{digest}.bin"


def resolve_crimson_desert_executable(package_root: Path) -> Optional[Path]:
    base_dir = _archive_base_dir(package_root)
    candidate_roots: List[Path] = []
    for candidate_root in (base_dir, *base_dir.parents[:4]):
        normalized = str(candidate_root).strip().lower()
        if not normalized or any(str(existing).strip().lower() == normalized for existing in candidate_roots):
            continue
        candidate_roots.append(candidate_root)

    for candidate_root in candidate_roots:
        for relative_path in (
            Path("bin64") / "CrimsonDesert.exe",
            Path("CrimsonDesert.exe"),
        ):
            candidate = candidate_root / relative_path
            if candidate.is_file():
                try:
                    return candidate.expanduser().resolve()
                except OSError:
                    return candidate.expanduser()
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def invalidate_archive_browser_cache(
    package_root: Path,
    cache_root: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> List[Path]:
    try:
        resolved_cache_root = cache_root.expanduser().resolve()
    except OSError:
        resolved_cache_root = cache_root.expanduser()

    candidate_roots = [resolved_cache_root]
    sibling_parent = resolved_cache_root.parent
    for dirname in _ARCHIVE_SCAN_CACHE_LEGACY_DIRNAMES:
        candidate_roots.append(sibling_parent / dirname)

    cache_paths: List[Path] = []
    seen: set[str] = set()
    for candidate_root in candidate_roots:
        for candidate_path in (
            resolve_archive_scan_cache_path(package_root, candidate_root),
            resolve_archive_sidecar_cache_path(package_root, candidate_root),
            resolve_archive_sidecar_cache_metadata_path(package_root, candidate_root),
            resolve_archive_derived_index_cache_path(package_root, candidate_root),
        ):
            normalized_path = str(candidate_path).strip().lower()
            if not normalized_path or normalized_path in seen:
                continue
            seen.add(normalized_path)
            cache_paths.append(candidate_path)

    deleted_paths: List[Path] = []
    for cache_path in cache_paths:
        if not cache_path.exists():
            continue
        try:
            cache_path.unlink()
            deleted_paths.append(cache_path)
        except OSError as exc:
            if on_log:
                on_log(f"Warning: could not delete archive cache file {cache_path}: {exc}")

    return deleted_paths


def _candidate_archive_scan_cache_paths(package_root: Path, cache_root: Path) -> List[Path]:
    try:
        resolved_cache_root = cache_root.expanduser().resolve()
    except OSError:
        resolved_cache_root = cache_root.expanduser()

    root_candidates = [resolved_cache_root]
    sibling_parent = resolved_cache_root.parent
    for dirname in _ARCHIVE_SCAN_CACHE_LEGACY_DIRNAMES:
        root_candidates.append(sibling_parent / dirname)

    cache_paths: List[Path] = []
    seen: set[str] = set()
    for candidate_root in root_candidates:
        normalized_root = str(candidate_root).strip()
        if not normalized_root:
            continue
        lowered_root = normalized_root.lower()
        if lowered_root in seen:
            continue
        seen.add(lowered_root)
        cache_paths.append(resolve_archive_scan_cache_path(package_root, candidate_root))
    return cache_paths


def _archive_base_dir(package_root: Path) -> Path:
    try:
        resolved_root = package_root.expanduser().resolve()
    except OSError:
        resolved_root = package_root.expanduser()
    return resolved_root.parent if resolved_root.is_file() else resolved_root


def _archive_relative_source_path(base_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def _collect_archive_scan_sources(
    package_root: Path,
    *,
    pamt_files: Optional[Sequence[Path]] = None,
) -> Tuple[Path, List[Tuple[str, int, int]]]:
    base_dir = _archive_base_dir(package_root)
    files = list(pamt_files) if pamt_files is not None else discover_pamt_files(package_root)
    sources: List[Tuple[str, int, int]] = []
    for pamt_path in files:
        stat_result = pamt_path.stat()
        sources.append(
            (
                _archive_relative_source_path(base_dir, pamt_path),
                int(stat_result.st_size),
                int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
            )
        )
    return base_dir, sources


def _collect_archive_scan_sources_from_entries(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
) -> Tuple[Path, List[Tuple[str, int, int]]]:
    base_dir = _archive_base_dir(package_root)
    unique_archive_paths: Dict[str, Path] = {}
    for entry in entries:
        for raw_path in (getattr(entry, "pamt_path", None), getattr(entry, "paz_file", None)):
            if raw_path is None:
                continue
            archive_path = raw_path if isinstance(raw_path, Path) else Path(raw_path).expanduser()
            try:
                normalized_key = os.path.normcase(os.fspath(archive_path)).strip().lower()
            except (OSError, TypeError, ValueError):
                normalized_key = str(archive_path).strip().lower()
            if not normalized_key or normalized_key in unique_archive_paths:
                continue
            unique_archive_paths[normalized_key] = archive_path

    sources: List[Tuple[str, int, int]] = []
    for archive_path in sorted(unique_archive_paths.values(), key=lambda value: str(value).lower()):
        stat_result = archive_path.stat()
        sources.append(
            (
                _archive_relative_source_path(base_dir, archive_path),
                int(stat_result.st_size),
                int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
            )
        )
    return base_dir, sources


def _normalize_archive_source_rows(rows: object) -> Optional[List[Tuple[str, int, int]]]:
    if not isinstance(rows, list):
        return None
    normalized_rows: List[Tuple[str, int, int]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            return None
        relative_path, raw_size, raw_mtime_ns = row
        normalized_rows.append((str(relative_path), int(raw_size), int(raw_mtime_ns)))
    return normalized_rows


def _serialize_cache_payload(payload: dict, *, magic: bytes, compress: Optional[bool] = None) -> bytes:
    raw = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    use_compression = lz4_block is not None if compress is None else bool(compress and lz4_block is not None)
    if use_compression:
        return magic + b"L" + lz4_block.compress(raw, store_size=True)
    return magic + b"R" + raw


def _deserialize_cache_payload(blob: bytes, *, magic: bytes, invalid_message: str) -> dict:
    if not blob.startswith(magic):
        raise ValueError(invalid_message)
    mode = blob[len(magic) : len(magic) + 1]
    payload = blob[len(magic) + 1 :]
    if mode == b"L":
        if lz4_block is None:
            raise ValueError("Compressed cache requires lz4, but python-lz4 is not available.")
        payload = lz4_block.decompress(payload)
    elif mode != b"R":
        raise ValueError("Cache compression mode is not supported.")
    data = pickle.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Cache payload is invalid.")
    return data


def _deserialize_cache_payload_from_path(
    cache_path: Path,
    *,
    magic: bytes,
    invalid_message: str,
) -> dict:
    with cache_path.open("rb") as handle:
        header = handle.read(len(magic) + 1)
        if len(header) < len(magic) + 1 or not header.startswith(magic):
            raise ValueError(invalid_message)
        mode = header[len(magic) : len(magic) + 1]
        if mode == b"R":
            data = pickle.load(handle)
            if not isinstance(data, dict):
                raise ValueError("Cache payload is invalid.")
            return data
        payload = handle.read()
    return _deserialize_cache_payload(header + payload, magic=magic, invalid_message=invalid_message)


def _write_raw_pickle_cache_payload_to_path(
    cache_path: Path,
    *,
    magic: bytes,
    payload: dict,
) -> None:
    temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temp_path.open("wb") as handle:
        handle.write(magic)
        handle.write(b"R")
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    temp_path.replace(cache_path)


def _serialize_archive_scan_cache_payload(payload: dict) -> bytes:
    return _serialize_cache_payload(payload, magic=_ARCHIVE_SCAN_CACHE_MAGIC)


def _serialize_archive_sidecar_cache_payload(payload: dict) -> bytes:
    # Sidecar caches are loaded after the archive browser becomes usable, so
    # faster writes/reads are more valuable than smaller files here.
    return _serialize_cache_payload(payload, magic=_ARCHIVE_SIDECAR_CACHE_MAGIC, compress=False)


def _deserialize_archive_scan_cache_payload(blob: bytes) -> dict:
    return _deserialize_cache_payload(
        blob,
        magic=_ARCHIVE_SCAN_CACHE_MAGIC,
        invalid_message="Archive cache header is not recognized.",
    )


def _deserialize_archive_scan_cache_payload_from_path(cache_path: Path) -> dict:
    return _deserialize_cache_payload_from_path(
        cache_path,
        magic=_ARCHIVE_SCAN_CACHE_MAGIC,
        invalid_message="Archive cache header is not recognized.",
    )


def _deserialize_archive_sidecar_cache_payload(blob: bytes) -> dict:
    return _deserialize_cache_payload(
        blob,
        magic=_ARCHIVE_SIDECAR_CACHE_MAGIC,
        invalid_message="Texture sidecar cache header is not recognized.",
    )


def _deserialize_archive_derived_index_cache_payload_from_path(cache_path: Path) -> dict:
    return _deserialize_cache_payload_from_path(
        cache_path,
        magic=_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
        invalid_message="Archive derived index cache header is not recognized.",
    )


def _write_archive_sidecar_cache_metadata(
    metadata_path: Path,
    *,
    version: int,
    sources: Sequence[Tuple[str, int, int]],
    entry_count: int,
) -> None:
    payload = {
        "version": int(version),
        "created_at": time.time(),
        "entry_count": int(entry_count),
        "sources": [[relative_path, int(size), int(mtime_ns)] for relative_path, size, mtime_ns in sources],
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp_path.replace(metadata_path)


def _read_archive_sidecar_cache_metadata(metadata_path: Path) -> Optional[dict]:
    if not metadata_path.is_file():
        return None
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Texture sidecar cache metadata is invalid.")
    return payload


def _archive_entry_cache_signature(package_root: Path, entry: ArchiveEntry) -> Tuple[object, ...]:
    base_dir = _archive_base_dir(package_root)
    paz_path = Path(getattr(entry, "paz_file", ""))
    try:
        paz_stat = paz_path.stat()
        paz_stamp = (
            int(paz_stat.st_size),
            int(getattr(paz_stat, "st_mtime_ns", int(paz_stat.st_mtime * 1_000_000_000))),
        )
    except OSError:
        paz_stamp = (0, 0)
    return (
        str(getattr(entry, "path", "") or "").replace("\\", "/"),
        _archive_relative_source_path(base_dir, Path(getattr(entry, "pamt_path", ""))),
        _archive_relative_source_path(base_dir, paz_path),
        paz_stamp,
        int(getattr(entry, "offset", 0)),
        int(getattr(entry, "comp_size", 0)),
        int(getattr(entry, "orig_size", 0)),
        int(getattr(entry, "flags", 0)),
        int(getattr(entry, "paz_index", 0)),
    )


def _build_archive_entry_cache_signatures(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
) -> Tuple[Tuple[object, ...], ...]:
    return tuple(_archive_entry_cache_signature(package_root, entry) for entry in entries)


def _describe_archive_cache_metadata_mismatch(
    cached_sources: Optional[Sequence[Tuple[str, int, int]]],
    current_sources: Sequence[Tuple[str, int, int]],
    cached_entry_count: int,
    current_entry_count: int,
) -> List[str]:
    reasons: List[str] = []
    if cached_entry_count >= 0 and cached_entry_count != current_entry_count:
        reasons.append(f"entry count changed {cached_entry_count:,}->{current_entry_count:,}")
    if cached_sources is None:
        reasons.append("source metadata missing or invalid")
        return reasons
    if len(cached_sources) != len(current_sources):
        reasons.append(f"source count changed {len(cached_sources):,}->{len(current_sources):,}")
    cached_by_path = {str(row[0]): row for row in cached_sources}
    current_by_path = {str(row[0]): row for row in current_sources}
    added = sorted(set(current_by_path) - set(cached_by_path))
    removed = sorted(set(cached_by_path) - set(current_by_path))
    changed = [
        path
        for path in sorted(set(cached_by_path) & set(current_by_path))
        if cached_by_path[path] != current_by_path[path]
    ]
    if added:
        reasons.append("sources added: " + ", ".join(added[:3]) + (" ..." if len(added) > 3 else ""))
    if removed:
        reasons.append("sources removed: " + ", ".join(removed[:3]) + (" ..." if len(removed) > 3 else ""))
    if changed:
        reasons.append("source stamps changed: " + ", ".join(changed[:3]) + (" ..." if len(changed) > 3 else ""))
    return reasons


def _record_timing(
    timings: Optional[Dict[str, float]],
    key: str,
    started_at: float,
) -> None:
    if timings is None:
        return
    timings[key] = max(0.0, float(time.perf_counter() - started_at))


def save_archive_scan_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Path:
    started_at = time.perf_counter()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = resolve_archive_scan_cache_path(package_root, cache_root)
    base_dir, sources = _collect_archive_scan_sources(package_root)
    resolved_base_dir = base_dir.resolve()
    pamt_rel_cache: Dict[Path, str] = {}

    rows = []
    total_entries = len(entries)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000
    for index, entry in enumerate(entries, start=1):
        raise_if_cancelled(stop_event)
        pamt_rel_text = pamt_rel_cache.get(entry.pamt_path)
        if pamt_rel_text is None:
            try:
                pamt_rel_text = entry.pamt_path.resolve().relative_to(resolved_base_dir).as_posix()
            except (OSError, ValueError):
                pamt_rel_text = entry.pamt_path.name
            pamt_rel_cache[entry.pamt_path] = pamt_rel_text
        rows.append(
            (
                entry.path,
                pamt_rel_text,
                int(entry.offset),
                int(entry.comp_size),
                int(entry.orig_size),
                int(entry.flags),
                int(entry.paz_index),
            )
        )
        if on_progress and (index == 1 or index % update_every == 0 or index == total_entries):
            on_progress(index, max(total_entries, 1), f"Building archive cache... {index:,} / {total_entries:,} entries")

    payload = {
        "version": _ARCHIVE_SCAN_CACHE_VERSION,
        "package_root": str(package_root),
        "created_at": time.time(),
        "sources": sources,
        "rows": rows,
    }
    if on_log:
        on_log(f"Writing archive cache: {cache_path.name}")
    if on_progress:
        on_progress(0, 0, "Compressing archive cache...")
    blob = _serialize_archive_scan_cache_payload(payload)
    temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temp_path.write_bytes(blob)
    temp_path.replace(cache_path)
    if on_progress:
        on_progress(1, 1, "Archive index cache written; preparing browser indexes...")
    if on_log:
        on_log(f"Archive cache updated: {cache_path}")
    _record_timing(timings, "cache_write_s", started_at)
    return cache_path


def load_archive_scan_cache(
    package_root: Path,
    cache_root: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Optional[List[ArchiveEntry]]:
    check_started_at = time.perf_counter()
    candidate_paths = _candidate_archive_scan_cache_paths(package_root, cache_root)
    preferred_cache_path = candidate_paths[0]
    existing_candidate_paths = [candidate for candidate in candidate_paths if candidate.exists()]
    if not existing_candidate_paths:
        if timings is not None:
            timings.setdefault("cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("cache_load_s", 0.0)
        return None

    if on_progress:
        on_progress(0, 0, "Checking archive cache...")
    try:
        base_dir, current_sources = _collect_archive_scan_sources(package_root)
    except Exception as exc:
        if on_log:
            on_log(f"Archive cache check failed; will rescan instead: {exc}")
        if timings is not None:
            timings.setdefault("cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("cache_load_s", 0.0)
        return None

    last_failure_message = "Archive cache is unavailable; performing a full rescan."
    for cache_path in existing_candidate_paths:
        cache_label = "archive cache" if cache_path == preferred_cache_path else f"legacy archive cache at {cache_path.parent}"
        if cache_path != preferred_cache_path and on_log:
            on_log(f"Trying {cache_label}: {cache_path.name}")

        try:
            data = _deserialize_archive_scan_cache_payload_from_path(cache_path)
        except Exception as exc:
            last_failure_message = f"{cache_label.capitalize()} could not be read; will try another cache or rescan: {exc}"
            if on_log:
                on_log(last_failure_message)
            continue

        if int(data.get("version", 0)) not in _ARCHIVE_SCAN_CACHE_SUPPORTED_VERSIONS:
            last_failure_message = f"{cache_label.capitalize()} format changed; will try another cache or rescan."
            if on_log:
                on_log(last_failure_message)
            continue

        cached_sources = data.get("sources")
        if not isinstance(cached_sources, list):
            last_failure_message = f"{cache_label.capitalize()} is missing source metadata; will try another cache or rescan."
            if on_log:
                on_log(last_failure_message)
            continue

        if cached_sources != current_sources:
            last_failure_message = f"{cache_label.capitalize()} is out of date; archive indexes changed since the last scan."
            if on_log:
                on_log(last_failure_message)
            continue

        raw_rows = data.get("rows")
        if not isinstance(raw_rows, list):
            last_failure_message = f"{cache_label.capitalize()} is missing entry rows; will try another cache or rescan."
            if on_log:
                on_log(last_failure_message)
            continue

        total_rows = len(raw_rows)
        if on_log:
            on_log(f"Loading {total_rows:,} archive entries from cache...")
        if total_rows == 0:
            if on_progress:
                on_progress(1, 1, "Archive cache loaded. No entries were cached.")
            if timings is not None:
                timings["cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
                timings["cache_load_s"] = 0.0
            return []

        try:
            if timings is not None:
                timings["cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
            load_started_at = time.perf_counter()
            update_every = 50_000 if total_rows >= 500_000 else 10_000 if total_rows >= 100_000 else 2_000
            pamt_path_cache: Dict[str, Path] = {}
            paz_path_cache: Dict[Tuple[str, int], Path] = {}
            entries: List[ArchiveEntry] = []
            for index, row in enumerate(raw_rows, start=1):
                raise_if_cancelled(stop_event)
                if not isinstance(row, tuple) or len(row) != 7:
                    raise ValueError("Archive cache row shape is invalid.")
                path, pamt_rel, offset, comp_size, orig_size, flags, paz_index = row
                pamt_rel_text = str(pamt_rel)
                pamt_path = pamt_path_cache.get(pamt_rel_text)
                if pamt_path is None:
                    pamt_path = base_dir / pamt_rel_text
                    pamt_path_cache[pamt_rel_text] = pamt_path
                paz_key = (pamt_rel_text, int(paz_index))
                paz_path = paz_path_cache.get(paz_key)
                if paz_path is None:
                    paz_path = pamt_path.parent / f"{int(paz_index)}.paz"
                    paz_path_cache[paz_key] = paz_path
                entries.append(
                    ArchiveEntry(
                        path=str(path),
                        pamt_path=pamt_path,
                        paz_file=paz_path,
                        offset=int(offset),
                        comp_size=int(comp_size),
                        orig_size=int(orig_size),
                        flags=int(flags),
                        paz_index=int(paz_index),
                    )
                )
                if on_progress and (index == 1 or index % update_every == 0 or index == total_rows):
                    on_progress(index, total_rows, f"Loading archive cache... {index:,} / {total_rows:,} entries")
            _record_timing(timings, "cache_load_s", load_started_at)
        except Exception as exc:
            last_failure_message = f"{cache_label.capitalize()} could not be loaded; will try another cache or rescan: {exc}"
            if on_log:
                on_log(last_failure_message)
            continue

        if cache_path != preferred_cache_path:
            try:
                preferred_cache_path.parent.mkdir(parents=True, exist_ok=True)
                if not preferred_cache_path.exists():
                    shutil.copy2(cache_path, preferred_cache_path)
                if on_log:
                    on_log(f"Migrated archive cache to preferred location: {preferred_cache_path}")
            except Exception as exc:
                if on_log:
                    on_log(f"Loaded archive cache from legacy location, but migration failed: {exc}")

        if on_log:
            on_log(f"Loaded {len(entries):,} archive entries from cache.")
        return entries

    if on_log:
        on_log(last_failure_message)
    if timings is not None:
        timings.setdefault("cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
        timings.setdefault("cache_load_s", 0.0)
    return None


def scan_archive_entries_cached(
    package_root: Path,
    cache_root: Path,
    *,
    force_refresh: bool = False,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_breadcrumb: Optional[Callable[[Mapping[str, object]], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[List[ArchiveEntry], str, Optional[Path], Dict[str, float]]:
    started_at = time.perf_counter()
    timings: Dict[str, float] = {}
    cache_path = resolve_archive_scan_cache_path(package_root, cache_root)
    if force_refresh:
        if on_log:
            on_log("Ignoring archive cache and performing a full rescan.")
        timings["cache_check_s"] = 0.0
        timings["cache_load_s"] = 0.0
    else:
        cached_entries = load_archive_scan_cache(
            package_root,
            cache_root,
            on_log=on_log,
            on_progress=on_progress,
            stop_event=stop_event,
            timings=timings,
        )
        if cached_entries is not None:
            timings.setdefault("archive_scan_s", 0.0)
            timings.setdefault("cache_write_s", 0.0)
            timings["total_s"] = max(0.0, float(time.perf_counter() - started_at))
            return cached_entries, "cache", cache_path, timings

    scan_started_at = time.perf_counter()
    entries = scan_archive_entries(
        package_root,
        on_log=on_log,
        on_progress=on_progress,
        on_breadcrumb=on_breadcrumb,
        stop_event=stop_event,
    )
    _record_timing(timings, "archive_scan_s", scan_started_at)
    try:
        cache_path = save_archive_scan_cache(
            package_root,
            cache_root,
            entries,
            on_log=on_log,
            on_progress=on_progress,
            stop_event=stop_event,
            timings=timings,
        )
    except Exception as exc:
        if on_log:
            on_log(f"Warning: archive cache could not be written: {exc}")
        cache_path = None
        timings.setdefault("cache_write_s", 0.0)
    timings["total_s"] = max(0.0, float(time.perf_counter() - started_at))
    return entries, "scan", cache_path, timings


def parse_steam_library_paths(libraryfolders_path: Path) -> List[Path]:
    if not libraryfolders_path.exists():
        return []
    try:
        text = libraryfolders_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    paths: List[Path] = []
    for match in re.finditer(r'"path"\s+"([^"]+)"', text, re.IGNORECASE):
        raw_path = match.group(1).replace("\\\\", "\\").strip()
        if raw_path:
            paths.append(Path(raw_path))
    return paths


def parse_steam_appmanifest_installdir(appmanifest_path: Path) -> Optional[str]:
    if not appmanifest_path.exists():
        return None
    try:
        text = appmanifest_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r'"installdir"\s+"([^"]+)"', text, re.IGNORECASE)
    if not match:
        return None
    install_dir = match.group(1).replace("\\\\", "\\").strip()
    return install_dir or None


def _normalize_existing_path(path: Path) -> Optional[Path]:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser()
    if not resolved.exists():
        return None
    return resolved


def discover_steam_roots() -> List[Path]:
    candidates: set[Path] = set()
    env_candidates = [
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
        r"C:\Steam",
    ]
    for raw in env_candidates:
        if not raw:
            continue
        raw_path = Path(raw)
        candidates.add(raw_path if raw_path.name.lower() == "steam" else raw_path / "Steam")

    if winreg is not None and os.name == "nt":
        registry_lookups = [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", ("SteamPath", "SteamExe")),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", ("InstallPath", "SteamPath")),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", ("InstallPath", "SteamPath")),
        ]
        for hive, subkey, value_names in registry_lookups:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    for value_name in value_names:
                        try:
                            value, _value_type = winreg.QueryValueEx(key, value_name)
                        except OSError:
                            continue
                        if not value:
                            continue
                        candidate = Path(str(value))
                        if candidate.suffix.lower() == ".exe":
                            candidate = candidate.parent
                        candidates.add(candidate)
            except OSError:
                continue

    resolved: List[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved_candidate = candidate.expanduser().resolve()
        except OSError:
            resolved_candidate = candidate.expanduser()
        lowered = str(resolved_candidate).lower()
        if lowered in seen or not resolved_candidate.exists():
            continue
        seen.add(lowered)
        resolved.append(resolved_candidate)
    return sorted(resolved)


def discover_windows_drive_roots() -> List[Path]:
    if os.name != "nt":
        return []
    roots: List[Path] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        candidate = Path(f"{letter}:\\")
        if candidate.exists():
            roots.append(candidate)
    return roots


def discover_non_steam_base_paths() -> List[Path]:
    candidates: set[Path] = set()
    env_candidates = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("ProgramW6432"),
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("USERPROFILE"),
        r"C:\Games",
        r"D:\Games",
        r"E:\Games",
        r"F:\Games",
    ]
    for raw in env_candidates:
        if not raw:
            continue
        normalized = _normalize_existing_path(Path(raw))
        if normalized is not None:
            candidates.add(normalized)

    for drive_root in discover_windows_drive_roots():
        normalized_root = _normalize_existing_path(drive_root)
        if normalized_root is None:
            continue
        candidates.add(normalized_root)
        try:
            for child in normalized_root.iterdir():
                if child.is_dir():
                    normalized_child = _normalize_existing_path(child)
                    if normalized_child is not None:
                        candidates.add(normalized_child)
        except OSError:
            continue

    return sorted(candidates)


def discover_non_steam_archive_package_roots(
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> List[Path]:
    explicit_env_vars = (
        "CDMW_PACKAGE_ROOT",
        "CRIMSON_DESERT_PACKAGE_ROOT",
        "cdmw_PACKAGE_ROOT",
    )
    candidates: set[Path] = set()

    for env_var in explicit_env_vars:
        raw_value = os.environ.get(env_var)
        if not raw_value:
            continue
        candidate = Path(raw_value)
        if looks_like_archive_package_root(candidate):
            normalized = _normalize_existing_path(candidate)
            if normalized is not None:
                candidates.add(normalized)
                if on_log:
                    on_log(f"Detected archive package root candidate from {env_var}: {normalized}")
        elif on_log:
            on_log(f"Ignoring {env_var}: path does not look like a valid Crimson Desert package root: {candidate}")

    game_dir_names = ("Crimson Desert", "CrimsonDesert")
    relative_patterns = (
        (),
        ("Games",),
        ("Steam", "steamapps", "common"),
        ("SteamLibrary", "steamapps", "common"),
        ("steamapps", "common"),
        ("Epic Games",),
    )

    for base_path in discover_non_steam_base_paths():
        for relative_parts in relative_patterns:
            for game_dir_name in game_dir_names:
                candidate = base_path.joinpath(*relative_parts, game_dir_name)
                if not looks_like_archive_package_root(candidate):
                    continue
                normalized = _normalize_existing_path(candidate)
                if normalized is not None:
                    candidates.add(normalized)

    store_container_names = (
        "XboxGames",
        "ModifiableWindowsApps",
        "WindowsApps",
    )
    store_candidate_suffixes = (
        (),
        ("Content",),
        ("Game",),
        ("Content", "Game"),
    )

    for drive_root in discover_windows_drive_roots():
        for container_name in store_container_names:
            candidate_container = drive_root / container_name
            if not candidate_container.exists() or not candidate_container.is_dir():
                continue

            direct_name_matches: List[Path] = []
            for game_dir_name in game_dir_names:
                direct_name_matches.extend(
                    [
                        candidate_container / game_dir_name,
                        candidate_container / f"{game_dir_name} Standard Edition",
                        candidate_container / f"{game_dir_name} Deluxe Edition",
                    ]
                )

            seen_container_children: set[str] = set()
            dynamic_child_matches: List[Path] = []
            try:
                for child in candidate_container.iterdir():
                    if not child.is_dir():
                        continue
                    child_key = child.name.lower()
                    if child_key in seen_container_children:
                        continue
                    seen_container_children.add(child_key)
                    lowered_name = child.name.lower()
                    if "crimson" in lowered_name and "desert" in lowered_name:
                        dynamic_child_matches.append(child)
            except OSError:
                continue

            for game_root in [*direct_name_matches, *dynamic_child_matches]:
                for suffix in store_candidate_suffixes:
                    candidate = game_root.joinpath(*suffix)
                    if not looks_like_archive_package_root(candidate):
                        continue
                    normalized = _normalize_existing_path(candidate)
                    if normalized is not None:
                        candidates.add(normalized)

    return sorted(candidates)


def _looks_like_archive_index_container(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    try:
        if next(path.glob("*.pamt"), None) is not None:
            return True
        for child in path.iterdir():
            if not child.is_dir() or not re.fullmatch(r"\d{4}", child.name):
                continue
            if next(child.glob("*.pamt"), None) is not None:
                return True
    except OSError:
        return False
    return False


def looks_like_archive_package_root(path: Path) -> bool:
    if _looks_like_archive_index_container(path):
        return True
    game_files_root = path / "game_files"
    return _looks_like_archive_index_container(game_files_root)


def autodetect_archive_package_roots(
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> List[Path]:
    if on_log:
        on_log("Checking Steam libraries and common custom install locations...")
    library_roots: set[Path] = set()
    for steam_root in discover_steam_roots():
        library_roots.add(steam_root)
        for library_file in (
            steam_root / "steamapps" / "libraryfolders.vdf",
            steam_root / "config" / "libraryfolders.vdf",
        ):
            for library_root in parse_steam_library_paths(library_file):
                library_roots.add(library_root)

    candidates: set[Path] = set()
    for library_root in sorted(library_roots):
        manifest_path = library_root / "steamapps" / f"appmanifest_{CRIMSON_DESERT_STEAM_APP_ID}.acf"
        manifest_install_dir = parse_steam_appmanifest_installdir(manifest_path)
        possible_dirs: List[Path] = []
        if manifest_install_dir:
            possible_dirs.append(library_root / "steamapps" / "common" / manifest_install_dir)
        possible_dirs.append(library_root / "steamapps" / "common" / "Crimson Desert")

        for candidate in possible_dirs:
            if looks_like_archive_package_root(candidate):
                try:
                    resolved_candidate = candidate.resolve()
                except OSError:
                    resolved_candidate = candidate
                candidates.add(resolved_candidate)

    for candidate in discover_non_steam_archive_package_roots(on_log=on_log):
        candidates.add(candidate)

    if on_log:
        if candidates:
            for candidate in sorted(candidates):
                on_log(f"Detected archive package root candidate: {candidate}")
        else:
            on_log("No valid Crimson Desert archive package roots were auto-detected.")

    return sorted(candidates)


class VfsPathResolver:
    def __init__(self, name_block: bytes, *, max_cache_entries: int = 200_000) -> None:
        self._name_block = name_block
        self._path_cache: Dict[int, str] = {0xFFFFFFFF: ""}
        self._max_cache_entries = max(1, int(max_cache_entries))

    def get_full_path(self, offset: int) -> str:
        if offset == 0xFFFFFFFF or offset >= len(self._name_block):
            return ""
        cached = self._path_cache.get(offset)
        if cached is not None:
            return cached
        parts: List[Tuple[int, str]] = []
        current_offset = offset
        base = ""
        seen_offsets: set[int] = set()
        while current_offset != 0xFFFFFFFF:
            if current_offset in seen_offsets:
                break
            seen_offsets.add(current_offset)
            cached = self._path_cache.get(current_offset)
            if cached is not None:
                base = cached
                break
            pos = current_offset
            if pos + 5 > len(self._name_block):
                break
            parent_offset = struct.unpack_from("<I", self._name_block, pos)[0]
            part_len = self._name_block[pos + 4]
            if pos + 5 + part_len > len(self._name_block):
                break
            part = self._name_block[pos + 5 : pos + 5 + part_len].decode("utf-8", errors="replace")
            parts.append((current_offset, part))
            current_offset = parent_offset
            if len(parts) > 255:
                break
        built = base
        for part_offset, part in reversed(parts):
            built = f"{built}{part}"
            if len(self._path_cache) < self._max_cache_entries:
                self._path_cache[part_offset] = built
        return self._path_cache.get(offset, built)


def parse_archive_pamt(pamt_path: Path, paz_dir: Optional[Path] = None) -> List[ArchiveEntry]:
    gc_was_enabled = gc.isenabled()
    if gc_was_enabled:
        gc.disable()
    try:
        return _parse_archive_pamt(pamt_path, paz_dir=paz_dir)
    finally:
        if gc_was_enabled:
            gc.enable()


def _parse_archive_pamt(pamt_path: Path, paz_dir: Optional[Path] = None) -> List[ArchiveEntry]:
    data = pamt_path.read_bytes()
    resolved_paz_dir = paz_dir if paz_dir is not None else pamt_path.parent
    size = len(data)
    if size < 12:
        raise ValueError(f"{pamt_path} is too small to be a valid .pamt file.")

    off = 0
    _header_crc, paz_count, _unknown = struct.unpack_from("<III", data, off)
    off += 12

    paz_table_size = paz_count * 12
    if off + paz_table_size > size:
        raise ValueError(f"{pamt_path.name} paz table is truncated.")
    off += paz_table_size

    if off + 4 > size:
        raise ValueError(f"{pamt_path.name} directory block length is truncated.")
    dir_block_size = read_u32_le(data, off)
    off += 4
    directory_data = data[off : off + dir_block_size]
    if len(directory_data) != dir_block_size:
        raise ValueError(f"{pamt_path.name} directory block is truncated.")
    off += dir_block_size

    if off + 4 > size:
        raise ValueError(f"{pamt_path.name} file-name block length is truncated.")
    file_name_block_size = read_u32_le(data, off)
    off += 4
    file_names = data[off : off + file_name_block_size]
    if len(file_names) != file_name_block_size:
        raise ValueError(f"{pamt_path.name} file-name block is truncated.")
    off += file_name_block_size

    if off + 4 > size:
        raise ValueError(f"{pamt_path.name} folder table length is truncated.")
    folder_count = read_u32_le(data, off)
    off += 4
    folder_table_size = folder_count * 16
    if off + folder_table_size > size:
        raise ValueError(f"{pamt_path.name} folder table is truncated.")
    folder_table = memoryview(data)[off : off + folder_table_size]
    off += folder_table_size

    if off + 4 > size:
        raise ValueError(f"{pamt_path.name} file table length is truncated.")
    file_count = read_u32_le(data, off)
    off += 4
    file_table_size = file_count * struct.calcsize("<IIIIHH")
    if off + file_table_size > size:
        raise ValueError(f"{pamt_path.name} file table is truncated.")
    file_table = memoryview(data)[off : off + file_table_size]

    resolver = VfsPathResolver(file_names)
    dir_resolver = VfsPathResolver(directory_data, max_cache_entries=50_000)
    folder_ranges = sorted(
        (
            file_start_index,
            file_start_index + folder_file_count,
            dir_resolver.get_full_path(name_offset).replace("\\", "/").strip("/"),
        )
        for _folder_hash, name_offset, file_start_index, folder_file_count in struct.iter_unpack("<IIII", folder_table)
        if folder_file_count > 0
    )
    paz_files = [resolved_paz_dir / f"{index}.paz" for index in range(paz_count)]

    entries: List[ArchiveEntry] = []
    folder_cursor = 0
    for entry_index, (name_offset, paz_offset, comp_size, orig_size, paz_index, flags) in enumerate(struct.iter_unpack("<IIIIHH", file_table)):
        relative_path = resolver.get_full_path(name_offset).replace("\\", "/").strip("/")
        guessed_dir = ""
        while folder_cursor < len(folder_ranges) and entry_index >= folder_ranges[folder_cursor][1]:
            folder_cursor += 1
        if folder_cursor < len(folder_ranges):
            start, end, candidate_dir = folder_ranges[folder_cursor]
            if start <= entry_index < end:
                guessed_dir = candidate_dir
        full_path = f"{guessed_dir}/{relative_path}".strip("/") if guessed_dir else relative_path
        if paz_index >= len(paz_files):
            raise ValueError(f"Invalid PAZ index {paz_index} for {pamt_path}")
        entries.append(
            ArchiveEntry(
                path=full_path,
                pamt_path=pamt_path,
                paz_file=paz_files[paz_index],
                offset=paz_offset,
                comp_size=comp_size,
                orig_size=orig_size,
                flags=flags,
                paz_index=paz_index,
            )
        )

    return entries


def scan_archive_entries(
    package_root: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_breadcrumb: Optional[Callable[[Mapping[str, object]], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[ArchiveEntry]:
    pamt_files = discover_pamt_files(package_root)
    if not pamt_files:
        raise ValueError(f"No .pamt files were found under {package_root}.")

    all_entries: List[ArchiveEntry] = []
    total_pmts = len(pamt_files)
    if on_log:
        on_log(f"Found {total_pmts:,} archive index file(s).")
    if on_progress:
        on_progress(0, total_pmts, f"0 / {total_pmts} archive indexes | 0 entries found")
    for index, pamt_path in enumerate(pamt_files, start=1):
        raise_if_cancelled(stop_event)
        try:
            relative_label = pamt_path.relative_to(package_root).as_posix()
        except ValueError:
            relative_label = pamt_path.name

        if on_log:
            on_log(f"[{index}/{total_pmts}] Parsing {relative_label}...")

        parse_started = time.monotonic()
        if on_breadcrumb is not None:
            on_breadcrumb(
                {
                    "phase": "parse_archive_pamt",
                    "status": "starting",
                    "package_root": str(package_root),
                    "pamt_path": str(pamt_path),
                    "relative_label": relative_label,
                    "index": index,
                    "total": total_pmts,
                    "entries_found_before": len(all_entries),
                    "timestamp": time.time(),
                }
            )

        if on_progress:
            on_progress(
                index - 1,
                total_pmts,
                f"Parsing {index} / {total_pmts}: {relative_label} | {len(all_entries):,} entries found",
            )

        try:
            entries = parse_archive_pamt(pamt_path)
        except Exception as exc:
            if on_breadcrumb is not None:
                on_breadcrumb(
                    {
                        "phase": "parse_archive_pamt",
                        "status": "failed",
                        "package_root": str(package_root),
                        "pamt_path": str(pamt_path),
                        "relative_label": relative_label,
                        "index": index,
                        "total": total_pmts,
                        "entries_found_before": len(all_entries),
                        "elapsed_seconds": round(time.monotonic() - parse_started, 3),
                        "error": str(exc),
                        "timestamp": time.time(),
                    }
                )
            raise

        all_entries.extend(entries)
        parse_elapsed = time.monotonic() - parse_started
        if on_log:
            on_log(f"[{index}/{total_pmts}] Parsed {relative_label} -> {len(entries):,} entries in {parse_elapsed:.1f}s")
        if on_breadcrumb is not None:
            on_breadcrumb(
                {
                    "phase": "parse_archive_pamt",
                    "status": "completed",
                    "package_root": str(package_root),
                    "pamt_path": str(pamt_path),
                    "relative_label": relative_label,
                    "index": index,
                    "total": total_pmts,
                    "parsed_entries": len(entries),
                    "entries_found_total": len(all_entries),
                    "elapsed_seconds": round(parse_elapsed, 3),
                    "timestamp": time.time(),
                }
            )
        if on_progress:
            on_progress(
                index,
                total_pmts,
                f"{index} / {total_pmts} archive indexes | {len(all_entries):,} entries found | last: {relative_label}",
            )

    return all_entries


def archive_entry_matches_filter(entry: ArchiveEntry, filter_text: str, extension_filter: str) -> bool:
    normalized_extension = normalize_archive_extension_filter(extension_filter)
    if normalized_extension and normalized_extension not in {"*", "all", ".*"}:
        if entry.extension != normalized_extension:
            return False

    text = filter_text.strip().lower()
    if not text:
        return True

    path_lower = entry.path.lower()
    basename_lower = entry.basename.lower()
    if any(char in text for char in "*?[]"):
        return fnmatch.fnmatch(path_lower, text) or fnmatch.fnmatch(basename_lower, text)
    return text in path_lower or text in basename_lower


def normalize_archive_extension_filter(extension_filter: str) -> str:
    normalized_extension = extension_filter.strip().lower()
    if not normalized_extension or normalized_extension in {"*", "all", ".*"}:
        return normalized_extension
    return normalized_extension if normalized_extension.startswith(".") else f".{normalized_extension}"


def archive_entry_role(entry: ArchiveEntry) -> str:
    path_lower = entry.path.lower()
    extension = entry.extension

    if extension in {".hkx", ".hkt"}:
        if any(token in path_lower for token in ("meshphysics", "havokphysics", "ragdoll", "physics")):
            return "physics"
        return "animation"
    if extension in ARCHIVE_MODEL_EXTENSIONS:
        return "model"
    if extension in {".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".papr", ".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
        return "animation"
    if extension in {".meshinfo", ".prefab", ".pamhc", ".pappt", ".pabgb", ".pabgh", ".pabc", ".pabv", ".levelinfo", ".palevel", ".roadsector", ".road", ".nav", ".seqmt", ".uianiminit"}:
        return "metadata"
    if extension == ".pathc":
        return "metadata"
    if extension in ARCHIVE_VIDEO_EXTENSIONS:
        return "video"
    if extension in ARCHIVE_AUDIO_EXTENSIONS:
        return "audio"
    if "/ui/" in path_lower or entry.basename.lower().startswith("ui_"):
        return "ui"
    if "impostor" in path_lower:
        return "impostor"
    if extension in ARCHIVE_IMAGE_EXTENSIONS or "/texture/" in path_lower:
        texture_type = classify_texture_type(entry.path)
        if texture_type == "normal":
            return "normal"
        if texture_type in {"mask", "roughness", "height", "vector", "emissive"}:
            return "material"
        return "image"
    if extension in ARCHIVE_TEXT_EXTENSIONS:
        return "text"
    return "other"


def archive_entry_is_previewable(entry: ArchiveEntry) -> bool:
    extension = entry.extension
    return (
        extension in ARCHIVE_IMAGE_EXTENSIONS
        or extension in ARCHIVE_AUDIO_EXTENSIONS
        or extension in ARCHIVE_VIDEO_EXTENSIONS
        or extension in ARCHIVE_TEXT_EXTENSIONS
        or extension in ARCHIVE_MODEL_EXTENSIONS
        or extension in _ARCHIVE_STRUCTURED_BINARY_PREVIEW_EXTENSIONS
        or extension == ".pathc"
    )


def archive_entry_matches_advanced_filters(
    entry: ArchiveEntry,
    *,
    package_filter_text: str,
    structure_filter: str,
    role_filter: str,
    min_size_kb: int,
    previewable_only: bool,
) -> bool:
    package_filter = package_filter_text.strip().lower()
    if package_filter and package_filter not in entry.package_label.lower() and package_filter not in str(entry.pamt_path).lower():
        return False

    if min_size_kb > 0 and entry.orig_size < min_size_kb * 1024:
        return False

    if previewable_only and not archive_entry_is_previewable(entry):
        return False

    normalized_structure = normalize_archive_structure_filter_value(structure_filter)
    if normalized_structure:
        if normalized_structure not in archive_entry_structure_prefixes(entry):
            return False

    normalized_role = role_filter.strip().lower()
    if normalized_role and normalized_role != "all":
        entry_role = archive_entry_role(entry)
        if normalized_role == "texture":
            if entry_role not in {"image", "normal", "material", "impostor", "ui"}:
                return False
        elif entry_role != normalized_role:
            return False

    return True


def _split_archive_filter_patterns(text: str) -> Tuple[str, ...]:
    if not text:
        return ()
    raw_parts = re.split(r"[;\r\n,]+", text)
    parts = [part.strip().lower() for part in raw_parts if part and part.strip()]
    return tuple(parts)


def _archive_entry_item_alias_text(entry: ArchiveEntry, item_search_aliases: Optional[Mapping[str, str]]) -> str:
    if not item_search_aliases:
        return ""
    if not _archive_entry_supports_item_alias_search(entry):
        return ""
    stem = PurePosixPath(entry.basename.replace("\\", "/")).stem.lower()
    if not stem:
        return ""
    keys = [stem]
    grouped_stem = derive_texture_group_key(entry.basename).strip().lower()
    if grouped_stem and grouped_stem not in keys:
        keys.append(grouped_stem)
    family_stem = _strip_archive_model_family_variant_suffix(stem)
    if family_stem and family_stem not in keys:
        keys.append(family_stem)
    for alias_stem in iter_archive_character_equipment_root_alias_stems(stem):
        if alias_stem not in keys:
            keys.append(alias_stem)
    for alias_stem in iter_archive_equipment_model_alias_stems(stem):
        if alias_stem not in keys:
            keys.append(alias_stem)
    aliases: List[str] = []
    seen: set[str] = set()
    for key in keys:
        alias = str(item_search_aliases.get(key, "") or "").strip().lower()
        if alias and alias not in seen:
            aliases.append(alias)
            seen.add(alias)
    return " ".join(aliases)


def archive_entry_model_base_key_matches(entry: ArchiveEntry) -> Tuple[Tuple[str, str], ...]:
    stem = PurePosixPath(entry.basename.replace("\\", "/")).stem.strip().lower()
    if not stem:
        return ()
    matches: List[Tuple[str, str]] = []
    seen: set[str] = set()

    def add(key: str, relation: str) -> None:
        normalized_key = str(key or "").strip().lower()
        if normalized_key and normalized_key not in seen:
            matches.append((normalized_key, relation))
            seen.add(normalized_key)

    add(stem, "exact")
    grouped_stem = derive_texture_group_key(entry.basename).strip().lower()
    if grouped_stem:
        add(grouped_stem, "related")
    family_stem = _strip_archive_model_family_variant_suffix(stem)
    if family_stem:
        add(family_stem, "related")
    for alias_stem in iter_archive_character_equipment_root_alias_stems(stem):
        add(alias_stem, "related")
    for alias_stem in iter_archive_equipment_model_alias_stems(stem):
        add(alias_stem, "related")
    return tuple(matches)


def archive_entry_item_name_match(
    entry: ArchiveEntry,
    *,
    item_display_names: Optional[Mapping[str, str]] = None,
    item_exact_display_names: Optional[Mapping[str, str]] = None,
    item_related_display_names: Optional[Mapping[str, str]] = None,
) -> Tuple[str, str, str]:
    first_related_name = ""
    first_related_reason = ""
    display_names = item_display_names or {}
    exact_display_names = item_exact_display_names or {}
    related_display_names = item_related_display_names or {}
    for key, relation in archive_entry_model_base_key_matches(entry):
        exact_display_name = str(exact_display_names.get(key, "") or "").strip()
        if relation == "exact" and exact_display_name:
            return (
                exact_display_name,
                "Exact localization",
                "Exact item name: ItemInfo._itemName localization resolved through ItemInfo._prefabDataList model/prefab evidence.",
            )

        related_display_name = str(related_display_names.get(key, "") or "").strip()
        if not related_display_name and relation == "related":
            related_display_name = exact_display_name
        if not related_display_name:
            related_display_name = str(display_names.get(key, "") or "").strip()
        if related_display_name and not first_related_name:
            first_related_name = related_display_name
            first_related_reason = (
                "Possible related item name. This is a navigation hint from a model family, variant, texture group, "
                "equipment alias, icon reference, or related asset expansion; it is not proof that this file is that item."
            )
    if first_related_name:
        return "", f"Name hint: {first_related_name}", first_related_reason
    return "", "", ""


def archive_entry_role_label(entry: Optional[ArchiveEntry]) -> str:
    if not isinstance(entry, ArchiveEntry):
        return "Unknown"
    ext = str(entry.extension or "").lower()
    path = str(entry.path or "").replace("\\", "/").lower()
    basename = PurePosixPath(path).name
    if ext in ARCHIVE_IMAGE_EXTENSIONS:
        return "Texture"
    if _is_material_sidecar_extension(ext, basename) or ext in {".pac_xml", ".pam_xml", ".pamlod_xml"}:
        return "Material"
    if ext in {".hkx", ".hkt"}:
        if "meshphysics" in path or "havokphysics" in path or "ragdoll" in path or "physics" in path:
            return "Physics"
        return "HKX"
    if ext == ".paa_metabin":
        return "Animation Metadata"
    if ext in {".paa", ".motionblending", ".pae", ".paem", ".papr", ".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
        return "Animation"
    if ext == ".pab":
        return "Skeleton / Rig"
    if ext in {".prefab", ".prefabdata_xml", ".prefabdata.xml", ".pappt"}:
        return "Prefab"
    if ext == ".pamhc":
        return "Model Property Metadata"
    if ext == ".seqmt":
        return "Sequence Texture Metadata"
    if ext in ARCHIVE_AUDIO_EXTENSIONS:
        return "Audio"
    if ext in ARCHIVE_VIDEO_EXTENSIONS:
        return "Video"
    if ext in ARCHIVE_TEXT_EXTENSIONS or ext in {".meshinfo", ".motionblending", ".paa_metabin", ".prefab", ".pappt", ".pamhc", ".seqmt"}:
        if "/ui" in path or path.startswith("ui/"):
            return "UI"
        return "Metadata"
    if ext in {".pac", ".pam", ".pamlod", ".obj", ".fbx", ".dae", ".gltf", ".glb", ".mesh", ".mdl", ".model", ".pat", ".patx"}:
        return "Mesh"
    if "/ui" in path or path.startswith("ui/"):
        return "UI"
    return "Unknown"


def archive_entry_role_display_text(entry: Optional[ArchiveEntry]) -> str:
    if not isinstance(entry, ArchiveEntry):
        return "Unknown"
    role = archive_entry_role_label(entry)
    extension = str(entry.extension or "").lower()
    return f"{role} {extension}".strip()


def archive_entry_override_state(
    entry: Optional[ArchiveEntry],
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[str, str]:
    if not isinstance(entry, ArchiveEntry):
        return "", ""
    normalized_path = str(entry.path or "").replace("\\", "/").strip().lower()
    same_path_entries: List[ArchiveEntry] = []
    if archive_entries_by_normalized_path:
        same_path_entries = [
            candidate
            for candidate in archive_entries_by_normalized_path.get(normalized_path, ())
            if isinstance(candidate, ArchiveEntry)
        ]
    if not same_path_entries:
        same_path_entries = [entry]
    is_mod_package = archive_entry_is_mod_package(entry)
    if len(same_path_entries) <= 1:
        if is_mod_package:
            return (
                "Mod-added",
                "This file comes from a mod/DMM-style package and no vanilla duplicate with the same virtual path was found.",
            )
        return "", ""
    active_entry = active_archive_entry_for_virtual_path(same_path_entries) or entry
    active_key = archive_entry_identity_key(active_entry)
    current_key = archive_entry_identity_key(entry)
    active_label = str(getattr(active_entry, "package_label", "") or "").strip() or str(active_entry.pamt_path)
    duplicate_labels = [
        str(getattr(candidate, "package_label", "") or "").strip() or str(candidate.pamt_path)
        for candidate in sorted(same_path_entries, key=archive_entry_load_priority, reverse=True)
    ]
    duplicate_text = "\n".join(f"- {label}" for label in duplicate_labels[:12])
    if current_key == active_key:
        state = "Active mod" if archive_entry_is_mod_package(entry) else "Active original"
        return (
            state,
            "This duplicate is the active winner for this virtual path based on package/load priority.\n"
            f"Active package: {active_label}\n"
            f"Duplicate candidates:\n{duplicate_text}",
        )
    state = "Shadowed mod" if is_mod_package else "Shadowed original"
    return (
        state,
        "This duplicate is shadowed by a higher-priority archive entry with the same virtual path.\n"
        f"Active package: {active_label}\n"
        f"Duplicate candidates:\n{duplicate_text}",
    )


def normalize_archive_browser_sort_column(value: object) -> int:
    try:
        column = int(value)
    except (TypeError, ValueError):
        return -1
    return column if 0 <= column <= 8 else -1


def normalize_archive_browser_sort_order(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"desc", "descending", "1"}:
        return "desc"
    return "asc"


def archive_browser_sort_is_active(sort_column: object) -> bool:
    return normalize_archive_browser_sort_column(sort_column) >= 0


_ARCHIVE_BROWSER_NATURAL_SORT_RE = re.compile(r"\d+|\D+")


def _archive_browser_natural_sort_key(value: object) -> Tuple[Tuple[int, object, str], ...]:
    text = str(value or "").replace("\\", "/").strip().casefold()
    parts: List[Tuple[int, object, str]] = []
    for token in _ARCHIVE_BROWSER_NATURAL_SORT_RE.findall(text):
        if token.isdigit():
            try:
                parts.append((0, int(token), token))
            except ValueError:
                parts.append((1, token, token))
        else:
            parts.append((1, token, token))
    return tuple(parts)


def archive_browser_entry_sort_key(
    entry: ArchiveEntry,
    sort_column: object,
    *,
    item_display_names: Optional[Mapping[str, str]] = None,
    item_exact_display_names: Optional[Mapping[str, str]] = None,
    item_related_display_names: Optional[Mapping[str, str]] = None,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[object, ...]:
    column = normalize_archive_browser_sort_column(sort_column)
    normalized_path = str(entry.path or "").replace("\\", "/").strip()
    basename = PurePosixPath(normalized_path).name or entry.basename
    parent_path = normalized_path.rpartition("/")[0]
    exact_name, name_evidence, _name_tooltip = archive_entry_item_name_match(
        entry,
        item_display_names=item_display_names,
        item_exact_display_names=item_exact_display_names,
        item_related_display_names=item_related_display_names,
    )
    override_state, _override_tooltip = archive_entry_override_state(entry, archive_entries_by_normalized_path)
    if column == 0:
        primary: object = _archive_browser_natural_sort_key(basename)
    elif column == 1:
        primary = _archive_browser_natural_sort_key(exact_name)
    elif column == 2:
        primary = _archive_browser_natural_sort_key(name_evidence)
    elif column == 3:
        primary = _archive_browser_natural_sort_key(archive_entry_role_display_text(entry))
    elif column == 4:
        primary = (int(entry.orig_size), int(entry.comp_size))
    elif column == 5:
        primary = (
            _archive_browser_natural_sort_key(entry.compression_label),
            int(entry.compression_type),
            int(entry.flags),
        )
    elif column == 6:
        primary = _archive_browser_natural_sort_key(entry.package_label)
    elif column == 7:
        primary = _archive_browser_natural_sort_key(override_state)
    elif column == 8:
        primary = _archive_browser_natural_sort_key(normalized_path or parent_path)
    else:
        primary = ()
    return (
        primary,
        _archive_browser_natural_sort_key(normalized_path),
        _archive_browser_natural_sort_key(entry.package_label),
        int(getattr(entry, "paz_index", 0) or 0),
        int(getattr(entry, "offset", 0) or 0),
        int(getattr(entry, "orig_size", 0) or 0),
        int(getattr(entry, "comp_size", 0) or 0),
    )


def sort_archive_entries_for_browser(
    entries: Sequence[ArchiveEntry],
    sort_column: object,
    sort_order: object = "asc",
    *,
    item_display_names: Optional[Mapping[str, str]] = None,
    item_exact_display_names: Optional[Mapping[str, str]] = None,
    item_related_display_names: Optional[Mapping[str, str]] = None,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> List[ArchiveEntry]:
    column = normalize_archive_browser_sort_column(sort_column)
    if column < 0:
        return list(entries)
    descending = normalize_archive_browser_sort_order(sort_order) == "desc"
    return sorted(
        entries,
        key=lambda entry: archive_browser_entry_sort_key(
            entry,
            column,
            item_display_names=item_display_names,
            item_exact_display_names=item_exact_display_names,
            item_related_display_names=item_related_display_names,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        ),
        reverse=descending,
    )


def _archive_entry_supports_item_alias_search(entry: ArchiveEntry) -> bool:
    extension = str(entry.extension or "").strip().lower()
    basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
    if extension in ARCHIVE_IMAGE_EXTENSIONS:
        return True
    if extension in {".pac", ".pam", ".pamlod", ".prefab", ".pappt", ".pamhc", ".meshinfo", ".seqmt", ".pab", ".hkx", ".hkt"}:
        return True
    return extension in _ARCHIVE_XML_LIKE_EXTENSIONS or _is_material_sidecar_extension(extension, basename)


def _archive_entry_has_item_alias_key(entry: ArchiveEntry, alias_keys: set[str]) -> bool:
    if not alias_keys:
        return False
    if not _archive_entry_supports_item_alias_search(entry):
        return False
    stem = PurePosixPath(entry.basename.replace("\\", "/")).stem.lower()
    if not stem:
        return False
    if stem in alias_keys:
        return True
    grouped_stem = derive_texture_group_key(entry.basename).strip().lower()
    if grouped_stem and grouped_stem in alias_keys:
        return True
    family_stem = _strip_archive_model_family_variant_suffix(stem)
    if family_stem and family_stem in alias_keys:
        return True
    if any(alias_stem in alias_keys for alias_stem in iter_archive_character_equipment_root_alias_stems(stem)):
        return True
    return any(alias_stem in alias_keys for alias_stem in iter_archive_equipment_model_alias_stems(stem))


def _archive_entry_item_alias_relevance_rank(entry: ArchiveEntry, alias_keys: set[str]) -> Optional[int]:
    if not alias_keys or not _archive_entry_supports_item_alias_search(entry):
        return None
    stem = PurePosixPath(entry.basename.replace("\\", "/")).stem.lower()
    if not stem:
        return None
    extension = str(entry.extension or "").strip().lower()
    exact_model_extensions = {".pac", ".pam", ".pamlod", ".prefab"}
    if stem in alias_keys:
        return 1 if extension in exact_model_extensions else 2
    grouped_stem = derive_texture_group_key(entry.basename).strip().lower()
    if grouped_stem and grouped_stem in alias_keys:
        return 2
    family_stem = _strip_archive_model_family_variant_suffix(stem)
    if family_stem and family_stem in alias_keys:
        return 2
    if any(alias_stem in alias_keys for alias_stem in iter_archive_character_equipment_root_alias_stems(stem)):
        return 2
    if any(alias_stem in alias_keys for alias_stem in iter_archive_equipment_model_alias_stems(stem)):
        return 2
    return None


def _archive_item_alias_match_keys_for_patterns(
    item_search_aliases: Optional[Mapping[str, str]],
    patterns: Sequence[str],
) -> set[str]:
    if not item_search_aliases or not patterns:
        return set()
    result: set[str] = set()
    for key, alias in item_search_aliases.items():
        normalized_key = str(key or "").strip().lower()
        alias_lower = str(alias or "").strip().lower()
        if not normalized_key or not alias_lower:
            continue
        if any(_archive_entry_matches_text_pattern("", "", pattern, alias_lower) for pattern in patterns):
            result.add(normalized_key)
    return result


def _archive_entry_matches_text_pattern(path_lower: str, basename_lower: str, pattern: str, alias_lower: str = "") -> bool:
    if not pattern:
        return False
    if any(char in pattern for char in "*?[]"):
        return (
            fnmatch.fnmatch(path_lower, pattern)
            or fnmatch.fnmatch(basename_lower, pattern)
            or bool(alias_lower and fnmatch.fnmatch(alias_lower, pattern))
        )
    return (
        pattern in path_lower
        or pattern in basename_lower
        or bool(alias_lower and (pattern in alias_lower or _archive_alias_token_prefix_match(alias_lower, pattern)))
    )


def _archive_alias_token_prefix_match(alias_lower: str, query_lower: str) -> bool:
    query_tokens = tuple(re.findall(r"[a-z0-9]+", str(query_lower or "").lower()))
    if not query_tokens:
        return False
    alias_tokens = tuple(re.findall(r"[a-z0-9]+", str(alias_lower or "").lower()))
    if not alias_tokens:
        return False
    return all(any(alias_token.startswith(query_token) for alias_token in alias_tokens) for query_token in query_tokens)


def _archive_entry_matches_size_term(entry: ArchiveEntry, term: ArchiveSearchTerm) -> bool:
    value = int(getattr(entry, "orig_size", 0) or 0)
    target = int(term.size_bytes or 0)
    operator = term.size_operator or "="
    if operator == ">":
        return value > target
    if operator == ">=":
        return value >= target
    if operator == "<":
        return value < target
    if operator == "<=":
        return value <= target
    return value == target


def _archive_entry_content_text(entry: ArchiveEntry, *, stop_event: Optional[threading.Event] = None) -> str:
    if stop_event is not None:
        raise_if_cancelled(stop_event)
    try:
        data, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
    except Exception:
        return ""
    decoded = try_decode_text_like_archive_data(data)
    if decoded is not None:
        return decoded
    return bytes(data[:262_144]).decode("latin-1", errors="ignore")


def _archive_search_term_matches_entry(
    entry: ArchiveEntry,
    term: ArchiveSearchTerm,
    *,
    item_search_aliases: Optional[Mapping[str, str]],
    stop_event: Optional[threading.Event] = None,
) -> Tuple[bool, bool]:
    field = str(term.field or _ARCHIVE_SEARCH_DEFAULT_FIELD).lower()
    path_text = str(entry.path or "")
    basename_text = str(entry.basename or PurePosixPath(path_text.replace("\\", "/")).name)
    alias_text = _archive_entry_item_alias_text(entry, item_search_aliases)
    alias_matched = False

    if field == "size":
        return _archive_entry_matches_size_term(entry, term), False
    if field == "ext":
        wanted = str(term.value or "").strip().casefold()
        actual = str(entry.extension or "").strip().casefold()
        if wanted and not wanted.startswith("."):
            wanted = f".{wanted}"
        return actual == wanted, False
    if field == "role":
        return _archive_search_text_match(archive_entry_role(entry), term), False
    if field == "package":
        package_text = " ".join((str(entry.package_label or ""), str(entry.pamt_path or "")))
        return _archive_search_text_match(package_text, term), False
    if field == "path":
        return _archive_name_search_text_match(path_text, term), False
    if field == "name":
        if _archive_name_search_text_match(basename_text, term):
            return True, False
        alias_matched = bool(alias_text and _archive_name_search_text_match(alias_text, term))
        return alias_matched, alias_matched
    if field == "content":
        content = _archive_entry_content_text(entry, stop_event=stop_event)
        return _archive_search_text_match(content, term), False

    if _archive_name_search_text_match(path_text, term) or _archive_name_search_text_match(basename_text, term):
        return True, False
    alias_matched = bool(alias_text and _archive_name_search_text_match(alias_text, term))
    return alias_matched, alias_matched


def _archive_search_query_matches_entry(
    entry: ArchiveEntry,
    query: ArchiveSearchQuery,
    *,
    item_search_aliases: Optional[Mapping[str, str]],
    stop_event: Optional[threading.Event] = None,
) -> Tuple[bool, bool]:
    if query.is_empty:
        return True, False
    for group in query.groups:
        group_matched = True
        group_alias_matched = False
        positive_count = 0
        for term in group:
            term_matched, alias_matched = _archive_search_term_matches_entry(
                entry,
                term,
                item_search_aliases=item_search_aliases,
                stop_event=stop_event,
            )
            if term.negated:
                if term_matched:
                    group_matched = False
                    break
                continue
            positive_count += 1
            if not term_matched:
                group_matched = False
                break
            group_alias_matched = group_alias_matched or alias_matched
        if group_matched and (positive_count > 0 or group):
            return True, group_alias_matched
    return False, False


def _archive_search_query_matches_alias(alias_text: str, query: ArchiveSearchQuery) -> bool:
    if query.is_empty:
        return False
    alias = str(alias_text or "")
    if not alias:
        return False
    for group in query.groups:
        ok = True
        positive_count = 0
        for term in group:
            if term.field not in {_ARCHIVE_SEARCH_DEFAULT_FIELD, "name"}:
                if not term.negated:
                    ok = False
                    break
                continue
            matched = _archive_name_search_text_match(alias, term)
            if term.negated and matched:
                ok = False
                break
            if not term.negated:
                positive_count += 1
                if not matched:
                    ok = False
                    break
        if ok and positive_count > 0:
            return True
    return False


def _archive_item_alias_match_keys_for_query(
    item_search_aliases: Optional[Mapping[str, str]],
    query: ArchiveSearchQuery,
) -> set[str]:
    if not item_search_aliases or query.is_empty:
        return set()
    result: set[str] = set()
    for key, alias in item_search_aliases.items():
        normalized_key = str(key or "").strip().lower()
        if normalized_key and _archive_search_query_matches_alias(str(alias or ""), query):
            result.add(normalized_key)
    return result


def _archive_entry_search_relevance_rank(
    entry: ArchiveEntry,
    *,
    text: str,
    include_patterns: Sequence[str],
    wildcard_filter: bool,
    wildcard_pattern: str,
    item_search_aliases: Optional[Mapping[str, str]],
    simple_alias_match_keys: set[str],
) -> int:
    if not text:
        return 0
    path_lower = entry.path.lower()
    basename_lower = entry.basename.lower()
    if len(include_patterns) > 1:
        for pattern in include_patterns:
            if _archive_entry_matches_text_pattern(path_lower, basename_lower, pattern):
                return 0
    elif wildcard_filter:
        if fnmatch.fnmatch(path_lower, wildcard_pattern) or fnmatch.fnmatch(basename_lower, wildcard_pattern):
            return 0
    elif text in path_lower or text in basename_lower:
        return 0

    alias_rank = _archive_entry_item_alias_relevance_rank(entry, simple_alias_match_keys)
    if alias_rank is not None:
        return alias_rank

    alias_lower = _archive_entry_item_alias_text(entry, item_search_aliases)
    if alias_lower:
        if len(include_patterns) > 1:
            if any(_archive_entry_matches_text_pattern("", "", pattern, alias_lower) for pattern in include_patterns):
                return 2
        elif wildcard_filter:
            if fnmatch.fnmatch(alias_lower, wildcard_pattern):
                return 2
        elif text in alias_lower:
            return 2
    return 3


def _archive_entry_search_query_relevance_rank(
    entry: ArchiveEntry,
    query: ArchiveSearchQuery,
    *,
    item_search_aliases: Optional[Mapping[str, str]],
    simple_alias_match_keys: set[str],
) -> int:
    if query.is_empty:
        return 0
    path_lower = entry.path.casefold()
    basename_lower = entry.basename.casefold()
    alias_lower = _archive_entry_item_alias_text(entry, item_search_aliases)
    for group in query.groups:
        positive_terms = [term for term in group if not term.negated]
        if not positive_terms:
            continue
        if all(
            term.field in {_ARCHIVE_SEARCH_DEFAULT_FIELD, "path", "name"}
            and (
                _archive_search_text_match(path_lower, term)
                or _archive_search_text_match(basename_lower, term)
            )
            for term in positive_terms
        ):
            return 0
        if all(
            term.field in {_ARCHIVE_SEARCH_DEFAULT_FIELD, "path", "name"}
            and (
                _archive_name_search_text_match(path_lower, term)
                or _archive_name_search_text_match(basename_lower, term)
            )
            for term in positive_terms
        ):
            return 1
        alias_rank = _archive_entry_item_alias_relevance_rank(entry, simple_alias_match_keys)
        if alias_rank is not None:
            return alias_rank
        if alias_lower and all(
            term.field in {_ARCHIVE_SEARCH_DEFAULT_FIELD, "name"}
            and _archive_name_search_text_match(alias_lower, term)
            for term in positive_terms
        ):
            return 2
    return 3


def _archive_entry_is_item_alias_expansion_source(entry: ArchiveEntry) -> bool:
    extension = str(entry.extension or "").strip().lower()
    basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
    if extension in {".pac", ".pam", ".pamlod", ".prefab", ".pappt", ".pamhc", ".meshinfo", ".seqmt", ".pab", ".hkx", ".hkt"}:
        return True
    if extension in _ARCHIVE_XML_LIKE_EXTENSIONS or _is_material_sidecar_extension(extension, basename):
        return True
    return False


def _read_archive_entry_text_or_binary_for_reference_expansion(
    entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[str, bytes]:
    extension = str(entry.extension or "").strip().lower()
    if extension not in _STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS and extension not in ARCHIVE_TEXT_EXTENSIONS:
        return "", b""
    try:
        raw_data, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
    except Exception:
        return "", b""
    text = try_decode_text_like_archive_data(raw_data)
    if text is not None:
        return text, b""
    return "", raw_data


def _expand_archive_filter_item_alias_related_entries(
    entries: Sequence[ArchiveEntry],
    filtered: List[ArchiveEntry],
    alias_matched_entries: Sequence[ArchiveEntry],
    *,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    candidate_filter: Optional[Callable[[ArchiveEntry], bool]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[ArchiveEntry]:
    expansion_sources: List[ArchiveEntry] = []
    seen_source_paths: set[str] = set()
    for entry in alias_matched_entries:
        normalized_path = _normalize_model_texture_reference(entry.path)
        if not normalized_path or normalized_path in seen_source_paths:
            continue
        if not _archive_entry_is_item_alias_expansion_source(entry):
            continue
        seen_source_paths.add(normalized_path)
        expansion_sources.append(entry)
        if len(expansion_sources) >= 32:
            break
    if not expansion_sources:
        return filtered

    basename_index = archive_entries_by_basename or build_archive_entry_basename_index(entries)
    normalized_path_index = archive_entries_by_normalized_path or build_archive_entry_path_index(entries)
    expanded_entries: List[ArchiveEntry] = list(filtered)
    seen_filtered_paths = {
        _normalize_model_texture_reference(entry.path)
        for entry in expanded_entries
        if _normalize_model_texture_reference(entry.path)
    }

    def add_entry(candidate: Optional[ArchiveEntry]) -> bool:
        if not isinstance(candidate, ArchiveEntry):
            return False
        if candidate_filter is not None and not candidate_filter(candidate):
            return False
        normalized_candidate = _normalize_model_texture_reference(candidate.path)
        if not normalized_candidate or normalized_candidate in seen_filtered_paths:
            return False
        seen_filtered_paths.add(normalized_candidate)
        expanded_entries.append(candidate)
        return True

    def add_related_for_source(source_entry: ArchiveEntry, *, include_sidecar_children: bool) -> None:
        raise_if_cancelled(stop_event)
        companion_entries = _find_archive_model_related_entries(source_entry, basename_index)
        text, binary_data = _read_archive_entry_text_or_binary_for_reference_expansion(
            source_entry,
            stop_event=stop_event,
        )
        references = build_archive_entry_related_references(
            source_entry,
            text=text,
            binary_data=binary_data,
            companion_entries=companion_entries,
            archive_entries_by_normalized_path=normalized_path_index,
            archive_entries_by_basename=basename_index,
        )
        graph_references = build_archive_relationship_references(
            source_entry,
            archive_entries_by_normalized_path=normalized_path_index,
            archive_entries_by_basename=basename_index,
        )
        references = merge_archive_reference_rows(references, graph_references)
        sidecar_children: List[ArchiveEntry] = []
        for reference in references:
            related_entry = getattr(reference, "resolved_entry", None)
            if add_entry(related_entry):
                extension = str(getattr(related_entry, "extension", "") or "").strip().lower()
                basename = PurePosixPath(str(getattr(related_entry, "path", "") or "").replace("\\", "/")).name.lower()
                if include_sidecar_children and _is_material_sidecar_extension(extension, basename):
                    sidecar_children.append(related_entry)
        if include_sidecar_children:
            for sidecar_entry in sidecar_children[:12]:
                add_related_for_source(sidecar_entry, include_sidecar_children=False)

    for source in expansion_sources:
        add_related_for_source(source, include_sidecar_children=True)

    return expanded_entries


def filter_archive_entries(
    entries: Sequence[ArchiveEntry],
    *,
    filter_text: str,
    exclude_filter_text: str,
    extension_filter: str,
    package_filter_text: str,
    structure_filter: str,
    role_filter: str,
    exclude_common_technical_suffixes: bool,
    min_size_kb: int,
    previewable_only: bool,
    item_search_aliases: Optional[Mapping[str, str]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_name_search_index: Optional[ArchiveNameSearchIndex] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[ArchiveEntry]:
    normalized_extension = normalize_archive_extension_filter(extension_filter)
    text = filter_text.strip().lower()
    search_query = parse_archive_search_query(filter_text)
    include_patterns = _split_archive_filter_patterns(text)
    wildcard_pattern = include_patterns[0] if include_patterns else ""
    wildcard_filter = len(include_patterns) == 1 and any(char in include_patterns[0] for char in "*?[]")
    simple_alias_match_keys = _archive_item_alias_match_keys_for_query(item_search_aliases, search_query)
    exclude_patterns = list(_split_archive_filter_patterns(exclude_filter_text))
    if exclude_common_technical_suffixes:
        exclude_patterns.extend(_COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS)
    package_filter = package_filter_text.strip().lower()
    min_size_bytes = min_size_kb * 1024 if min_size_kb > 0 else 0
    normalized_structure = normalize_archive_structure_filter_value(structure_filter)
    normalized_role = role_filter.strip().lower()
    require_role = bool(normalized_role and normalized_role != "all")
    candidate_entries: Sequence[ArchiveEntry] = entries
    if archive_name_search_index is not None:
        indexed_entries = archive_name_search_index.entries_for_query(entries, search_query)
        if indexed_entries is not None:
            candidate_entries = indexed_entries
    total_entries = len(candidate_entries)
    progress_total = max(total_entries, 1)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000

    if on_progress:
        on_progress(0 if total_entries > 0 else 1, progress_total, f"Applying archive filters... 0 / {total_entries:,} entries")

    def text_match_for_entry(entry: ArchiveEntry) -> Tuple[bool, bool]:
        if search_query.is_empty:
            return True, False
        query_matched, alias_matched = _archive_search_query_matches_entry(
            entry,
            search_query,
            item_search_aliases=item_search_aliases,
            stop_event=stop_event,
        )
        if query_matched:
            return True, alias_matched
        if simple_alias_match_keys:
            alias_matched = _archive_entry_has_item_alias_key(entry, simple_alias_match_keys)
            return alias_matched, alias_matched
        return False, False

    def entry_passes_post_text_filters(
        entry: ArchiveEntry,
        *,
        enforce_extension: bool,
        enforce_structure_role_size_preview: bool = True,
    ) -> bool:
        if (
            enforce_extension
            and normalized_extension
            and normalized_extension not in {"*", "all", ".*"}
            and entry.extension != normalized_extension
        ):
            return False

        path_lower = entry.path.lower()
        basename_lower = entry.basename.lower()
        if exclude_patterns:
            if any(
                _archive_entry_matches_text_pattern(path_lower, basename_lower, pattern)
                for pattern in exclude_patterns
            ):
                return False
            if item_search_aliases:
                alias_lower = _archive_entry_item_alias_text(entry, item_search_aliases)
                if alias_lower and any(
                    _archive_entry_matches_text_pattern("", "", pattern, alias_lower)
                    for pattern in exclude_patterns
                ):
                    return False

        if package_filter:
            package_label_lower = entry.package_label.lower()
            pamt_path_lower = str(entry.pamt_path).lower()
            if package_filter not in package_label_lower and package_filter not in pamt_path_lower:
                return False

        if not enforce_structure_role_size_preview:
            return True

        if min_size_bytes and entry.orig_size < min_size_bytes:
            return False

        if previewable_only and not archive_entry_is_previewable(entry):
            return False

        if normalized_structure and normalized_structure not in archive_entry_structure_prefixes(entry):
            return False

        if require_role:
            entry_role = archive_entry_role(entry)
            if normalized_role == "texture":
                if entry_role not in {"image", "normal", "material", "impostor", "ui"}:
                    return False
            elif entry_role != normalized_role:
                return False

        return True

    filtered: List[ArchiveEntry] = []
    alias_matched_entries: List[ArchiveEntry] = []
    hidden_alias_expansion_sources: List[ArchiveEntry] = []
    for index, entry in enumerate(candidate_entries, start=1):
        if stop_event is not None and (index == 1 or index % 2048 == 0):
            raise_if_cancelled(stop_event)
        text_matched, alias_matched = text_match_for_entry(entry)
        matched = text_matched and entry_passes_post_text_filters(entry, enforce_extension=True)

        if matched:
            filtered.append(entry)
            if alias_matched:
                alias_matched_entries.append(entry)
        elif (
            text
            and item_search_aliases
            and alias_matched
            and normalized_extension == ".dds"
            and _archive_entry_is_item_alias_expansion_source(entry)
            and entry_passes_post_text_filters(
                entry,
                enforce_extension=False,
                enforce_structure_role_size_preview=False,
            )
        ):
            hidden_alias_expansion_sources.append(entry)

        if on_progress and (index == 1 or index % update_every == 0 or index == total_entries):
            on_progress(index, progress_total, f"Applying archive filters... {index:,} / {total_entries:,} entries")

    if text and item_search_aliases and (alias_matched_entries or hidden_alias_expansion_sources):
        def related_candidate_matches_active_filters(candidate: ArchiveEntry) -> bool:
            return entry_passes_post_text_filters(candidate, enforce_extension=True)

        filtered = _expand_archive_filter_item_alias_related_entries(
            entries,
            filtered,
            (*alias_matched_entries, *hidden_alias_expansion_sources),
            archive_entries_by_basename=archive_entries_by_basename,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            candidate_filter=related_candidate_matches_active_filters,
            stop_event=stop_event,
        )

    if text and len(filtered) > 1:
        original_order = {
            _normalize_model_texture_reference(entry.path): index
            for index, entry in enumerate(filtered)
            if _normalize_model_texture_reference(entry.path)
        }
        filtered.sort(
            key=lambda entry: (
                _archive_entry_search_query_relevance_rank(
                    entry,
                    item_search_aliases=item_search_aliases,
                    query=search_query,
                    simple_alias_match_keys=simple_alias_match_keys,
                ),
                original_order.get(_normalize_model_texture_reference(entry.path), 0),
            )
        )

    return order_archive_entries_by_active_overrides(filtered)


def count_archive_entries_with_extension(
    entries: Sequence[ArchiveEntry],
    extension_filter: str,
) -> int:
    normalized_extension = normalize_archive_extension_filter(extension_filter)
    if not normalized_extension or normalized_extension in {"*", "all", ".*"}:
        return len(entries)
    return sum(1 for entry in entries if entry.extension == normalized_extension)


def normalize_archive_structure_filter_value(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip().strip("/")
    if not raw:
        return ""
    return "/".join(
        part.lower()
        for part in raw.split("/")
        if part not in {"", ".", ".."}
    )


def archive_entry_path_parts(entry: ArchiveEntry) -> Tuple[str, ...]:
    return tuple(
        part
        for part in entry.path.replace("\\", "/").split("/")
        if part not in {"", ".", ".."}
    )


def archive_entry_folder_parts(entry: ArchiveEntry) -> Tuple[str, ...]:
    package_dir = entry.pamt_path.parent.name.strip().lower() or "package"
    parent_parts = tuple(part.lower() for part in archive_entry_path_parts(entry)[:-1])
    return (package_dir, *parent_parts)


def archive_entry_structure_prefixes(entry: ArchiveEntry) -> Tuple[str, ...]:
    parts = archive_entry_folder_parts(entry)
    return tuple("/".join(parts[: index + 1]) for index in range(len(parts)))


def archive_entry_identity_key(entry: ArchiveEntry) -> Tuple[str, str, int, int]:
    return (
        str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower(),
        str(getattr(entry, "pamt_path", "") or "").strip().lower(),
        int(getattr(entry, "offset", 0) or 0),
        int(getattr(entry, "paz_index", 0) or 0),
    )


def archive_entry_is_mod_package(entry: ArchiveEntry) -> bool:
    package_parent = getattr(getattr(entry, "pamt_path", None), "parent", Path())
    package_name = str(getattr(package_parent, "name", "") or "")
    package_key = package_name.strip().casefold()
    if not package_key:
        return False
    if package_key.startswith("dmm") or package_key.startswith("mod"):
        return True
    return not bool(re.fullmatch(r"\d+", package_key))


def archive_entry_load_priority(entry: ArchiveEntry) -> Tuple[int, int, int, int, str]:
    package_parent = getattr(getattr(entry, "pamt_path", None), "parent", Path())
    package_name = str(getattr(package_parent, "name", "") or "")
    package_key = package_name.strip().casefold()
    package_number_match = re.fullmatch(r"0*(\d+)", package_key)
    is_numeric_package = bool(package_number_match)
    is_dmm_package = package_key.startswith("dmm")
    if is_dmm_package:
        tier = 3
    elif not is_numeric_package:
        tier = 2
    else:
        tier = 1
    package_number = int(package_number_match.group(1)) if package_number_match else -1
    pamt_stem = str(getattr(getattr(entry, "pamt_path", None), "stem", "") or "").strip().casefold()
    pamt_number_match = re.fullmatch(r"0*(\d+)", pamt_stem)
    pamt_number = int(pamt_number_match.group(1)) if pamt_number_match else -1
    return (
        tier,
        package_number,
        pamt_number,
        int(getattr(entry, "paz_index", 0) or 0),
        str(getattr(entry, "pamt_path", "") or "").casefold(),
    )


def active_archive_entry_for_virtual_path(entries: Sequence[ArchiveEntry]) -> Optional[ArchiveEntry]:
    candidates = [entry for entry in entries if isinstance(entry, ArchiveEntry)]
    if not candidates:
        return None
    return max(candidates, key=archive_entry_load_priority)


def order_archive_entries_by_active_overrides(entries: Sequence[ArchiveEntry]) -> List[ArchiveEntry]:
    grouped: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    ordered_paths: List[str] = []
    for entry in entries:
        normalized_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path:
            normalized_path = archive_entry_identity_key(entry)[0]
        if normalized_path not in grouped:
            ordered_paths.append(normalized_path)
        grouped[normalized_path].append(entry)
    ordered: List[ArchiveEntry] = []
    for normalized_path in ordered_paths:
        group_entries = grouped.get(normalized_path, [])
        if len(group_entries) <= 1:
            ordered.extend(group_entries)
            continue
        active_key = archive_entry_identity_key(active_archive_entry_for_virtual_path(group_entries) or group_entries[0])
        ordered.extend(
            sorted(
                group_entries,
                key=lambda entry: (
                    archive_entry_identity_key(entry) != active_key,
                    -archive_entry_load_priority(entry)[0],
                    -archive_entry_load_priority(entry)[1],
                    -archive_entry_load_priority(entry)[2],
                    str(getattr(entry, "package_label", "") or "").casefold(),
                ),
            )
        )
    return ordered


def build_archive_entry_path_index(entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
    index: Dict[str, List[ArchiveEntry]] = {}
    for archive_entry in entries:
        normalized_path = archive_entry.path.replace("\\", "/").strip().lower()
        index.setdefault(normalized_path, []).append(archive_entry)
    return index


def build_archive_entry_basename_index(entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
    index: Dict[str, List[ArchiveEntry]] = {}
    for archive_entry in entries:
        normalized_path = archive_entry.path.replace("\\", "/").strip()
        basename = normalized_path.rsplit("/", 1)[-1].strip().lower()
        if not basename:
            continue
        index.setdefault(basename, []).append(archive_entry)
    for basename, basename_entries in index.items():
        basename_entries.sort(
            key=lambda entry: (
                -str(entry.path or "").replace("\\", "/").strip().count("/"),
                -len(str(entry.path or "").replace("\\", "/").strip()),
                str(entry.path or "").replace("\\", "/").strip().lower(),
            )
        )
    return index


def build_archive_entry_extension_index(entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
    index: Dict[str, List[ArchiveEntry]] = {}
    for archive_entry in entries:
        extension = normalize_archive_extension_filter(archive_entry.extension)
        if not extension:
            continue
        index.setdefault(extension, []).append(archive_entry)
    return index


def save_archive_derived_index_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    item_search_aliases: Optional[Mapping[str, str]] = None,
    item_display_names: Optional[Mapping[str, str]] = None,
    item_exact_display_names: Optional[Mapping[str, str]] = None,
    item_related_display_names: Optional[Mapping[str, str]] = None,
    item_asset_catalog: Optional[Sequence[Mapping[str, object]]] = None,
    path_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    basename_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    extension_index: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Path:
    started_at = time.perf_counter()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = resolve_archive_derived_index_cache_path(package_root, cache_root)
    _base_dir, sources = _collect_archive_scan_sources_from_entries(package_root, entries)
    catalog_rows = [dict(row) for row in (item_asset_catalog or []) if isinstance(row, Mapping)]
    payload = {
        "version": _ARCHIVE_DERIVED_INDEX_CACHE_VERSION,
        "created_at": time.time(),
        "sources": sources,
        "entry_count": len(entries),
        "item_search_aliases": dict(item_search_aliases or {}),
        "item_display_names": dict(item_display_names or {}),
        "item_exact_display_names": dict(item_exact_display_names or {}),
        "item_related_display_names": dict(item_related_display_names or {}),
        "item_asset_catalog": catalog_rows,
        "table_catalog": table_catalog_cache_metadata(row_counts={"item_asset_catalog": len(catalog_rows)}),
    }
    _write_raw_pickle_cache_payload_to_path(
        cache_path,
        magic=_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
        payload=payload,
    )
    if on_log is not None:
        on_log(f"Archive derived index cache updated: {cache_path}")
    _record_timing(timings, "derived_cache_write_s", started_at)
    return cache_path


def load_archive_derived_index_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    on_log: Optional[Callable[[str], None]] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Optional[Dict[str, object]]:
    check_started_at = time.perf_counter()
    cache_path = resolve_archive_derived_index_cache_path(package_root, cache_root)
    if not cache_path.exists():
        if timings is not None:
            timings.setdefault("derived_cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("derived_cache_load_s", 0.0)
        return None
    try:
        try:
            cache_size = int(cache_path.stat().st_size)
        except OSError:
            cache_size = 0
        if cache_size > _ARCHIVE_DERIVED_INDEX_CACHE_MAX_SAFE_BYTES:
            try:
                cache_path.unlink()
            except OSError:
                pass
            if on_log is not None:
                on_log("Archive derived index cache format changed; rebuilding lightweight cache.")
            if timings is not None:
                timings["derived_cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
                timings.setdefault("derived_cache_load_s", 0.0)
            return None
        _base_dir, current_sources = _collect_archive_scan_sources_from_entries(package_root, entries)
        if timings is not None:
            timings["derived_cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
        load_started_at = time.perf_counter()
        data = _deserialize_archive_derived_index_cache_payload_from_path(cache_path)
        if int(data.get("version", 0)) not in _ARCHIVE_DERIVED_INDEX_CACHE_SUPPORTED_VERSIONS:
            if on_log is not None:
                on_log("Archive derived index cache format changed; rebuilding lightweight cache.")
            try:
                cache_path.unlink()
            except OSError:
                pass
            return None
        if not table_catalog_cache_metadata_matches(data.get("table_catalog")):
            if on_log is not None:
                on_log("Archive derived index cache table catalog metadata changed; rebuilding lightweight cache.")
            try:
                cache_path.unlink()
            except OSError:
                pass
            return None
        cached_sources = _normalize_archive_source_rows(data.get("sources"))
        cached_entry_count = int(data.get("entry_count", -1))
        if cached_sources != current_sources or cached_entry_count != len(entries):
            if on_log is not None:
                reasons = _describe_archive_cache_metadata_mismatch(
                    cached_sources,
                    current_sources,
                    cached_entry_count,
                    len(entries),
                )
                on_log("Archive derived index cache is out of date: " + "; ".join(reasons or ["metadata changed"]))
            return None
        payload = {
            "item_search_aliases": {
                str(key): str(value)
                for key, value in (data.get("item_search_aliases", {}) or {}).items()
            },
            "item_display_names": {
                str(key): str(value)
                for key, value in (data.get("item_display_names", {}) or {}).items()
            },
            "item_exact_display_names": {
                str(key): str(value)
                for key, value in (data.get("item_exact_display_names", {}) or {}).items()
            },
            "item_related_display_names": {
                str(key): str(value)
                for key, value in (data.get("item_related_display_names", {}) or {}).items()
            },
            "item_asset_catalog": [
                dict(row)
                for row in (data.get("item_asset_catalog", []) or [])
                if isinstance(row, Mapping)
            ],
            "table_catalog": dict(data.get("table_catalog", {}) or {}),
            "cache_path": str(cache_path),
        }
        _record_timing(timings, "derived_cache_load_s", load_started_at)
        if on_log is not None:
            on_log("Loaded archive derived indexes from cache.")
        return payload
    except Exception as exc:
        if on_log is not None:
            on_log(f"Archive derived index cache could not be used; rebuilding derived indexes: {exc}")
        if timings is not None:
            timings.setdefault("derived_cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("derived_cache_load_s", 0.0)
        return None


def _extract_archive_sidecar_texture_lookup_paths(sidecar_text: str) -> Tuple[str, ...]:
    if not sidecar_text:
        return ()

    texture_paths: List[str] = []
    seen_paths: set[str] = set()

    for match in _ARCHIVE_SIDECAR_TEXTURE_ATTR_RE.finditer(sidecar_text):
        texture_path = html.unescape(str(match.group("value") or "")).replace("\\", "/").strip()
        normalized_texture = normalize_texture_reference_for_sidecar_lookup(texture_path)
        if not normalized_texture or normalized_texture in seen_paths:
            continue
        seen_paths.add(normalized_texture)
        texture_paths.append(normalized_texture)
    return tuple(texture_paths)


def _build_archive_texture_sidecar_path_rows_for_group(
    group_entries: Sequence[Tuple[int, ArchiveEntry]],
    *,
    stop_event: Optional[threading.Event] = None,
    on_entry_processed: Optional[Callable[[int], None]] = None,
) -> Dict[str, List[int]]:
    path_rows_lists: Dict[str, List[int]] = defaultdict(list)
    if not group_entries:
        return path_rows_lists

    paz_path = group_entries[0][1].paz_file
    try:
        with paz_path.open("rb") as handle:
            for entry_index, entry in group_entries:
                raise_if_cancelled(stop_event)
                try:
                    raw_data, _decompressed, _note = _read_archive_entry_data_from_handle(
                        handle,
                        entry,
                        stop_event=stop_event,
                    )
                except RunCancelled:
                    raise
                except Exception:
                    if on_entry_processed is not None:
                        on_entry_processed(1)
                    continue
                if not raw_data or _ARCHIVE_TEXTURE_BYTES_RE.search(raw_data) is None:
                    if on_entry_processed is not None:
                        on_entry_processed(1)
                    continue
                text = try_decode_text_like_archive_data(raw_data)
                if not text:
                    if on_entry_processed is not None:
                        on_entry_processed(1)
                    continue
                for normalized_texture in _extract_archive_sidecar_texture_lookup_paths(text):
                    path_rows_lists[normalized_texture].append(entry_index)
                if on_entry_processed is not None:
                    on_entry_processed(1)
    except RunCancelled:
        raise
    except Exception:
        return {}
    return path_rows_lists


def build_archive_texture_sidecar_path_rows(
    entries: Sequence[ArchiveEntry],
    *,
    worker_count: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_label: str = "Indexing archive texture sidecars...",
    timings: Optional[Dict[str, float]] = None,
) -> Dict[str, Tuple[int, ...]]:
    grouped_sidecar_entries: Dict[str, List[Tuple[int, ArchiveEntry]]] = defaultdict(list)
    total_sidecars = 0
    for entry_index, entry in enumerate(entries):
        entry_basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
        if not _is_material_sidecar_extension(entry.extension, entry_basename):
            continue
        paz_key = str(entry.paz_file).strip().lower()
        grouped_sidecar_entries[paz_key].append((entry_index, entry))
        total_sidecars += 1
    if total_sidecars <= 0:
        return {}

    path_rows_lists: Dict[str, List[int]] = defaultdict(list)
    progress_interval = max(total_sidecars // 100, 1) if total_sidecars > 0 else 1
    processed_count = 0
    progress_lock = threading.Lock()
    sorted_groups = [
        (paz_key, sorted(grouped_sidecar_entries[paz_key], key=lambda item: item[1].offset))
        for paz_key in sorted(grouped_sidecar_entries)
    ]
    try:
        configured_workers = int(
            worker_count
            if worker_count is not None
            else os.environ.get("CDMW_ARCHIVE_SIDECAR_WORKERS")
            or os.environ.get("CFT_ARCHIVE_SIDECAR_WORKERS", "0")
        )
    except ValueError:
        configured_workers = 0
    if configured_workers <= 0:
        configured_workers = min(12, max(4, (os.cpu_count() or 2) - 1), max(1, len(sorted_groups)))
    worker_count = min(max(configured_workers, 1), 16, max(1, len(sorted_groups)))
    if timings is not None:
        timings["sidecar_count"] = float(total_sidecars)
        timings["sidecar_group_count"] = float(len(sorted_groups))
        timings["sidecar_worker_count"] = float(worker_count)

    def merge_group_rows(group_rows: Dict[str, List[int]]) -> None:
        for normalized_texture, entry_indexes in group_rows.items():
            if entry_indexes:
                path_rows_lists[normalized_texture].extend(entry_indexes)

    def publish_progress(force: bool = False) -> None:
        if on_progress is None:
            return
        if force or processed_count == total_sidecars or processed_count % progress_interval == 0:
            on_progress(
                processed_count,
                total_sidecars,
                f"{progress_label} {processed_count:,} / {total_sidecars:,}",
            )

    def mark_entries_processed(count: int = 1) -> None:
        nonlocal processed_count
        if count <= 0:
            return
        with progress_lock:
            processed_count = min(total_sidecars, processed_count + int(count))
            publish_progress(force=False)

    if worker_count <= 1 or total_sidecars < 2_000:
        for _paz_key, group_entries in sorted_groups:
            raise_if_cancelled(stop_event)
            group_rows = _build_archive_texture_sidecar_path_rows_for_group(
                group_entries,
                stop_event=stop_event,
                on_entry_processed=mark_entries_processed,
            )
            merge_group_rows(group_rows)
            publish_progress(force=True)
    else:
        group_results: Dict[str, Dict[str, List[int]]] = {}
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="ArchiveSidecarIndex") as executor:
            future_by_key = {
                executor.submit(
                    _build_archive_texture_sidecar_path_rows_for_group,
                    group_entries,
                    stop_event=stop_event,
                    on_entry_processed=mark_entries_processed,
                ): (paz_key, len(group_entries))
                for paz_key, group_entries in sorted_groups
            }
            for future in as_completed(future_by_key):
                paz_key, group_count = future_by_key[future]
                raise_if_cancelled(stop_event)
                try:
                    group_results[paz_key] = future.result()
                except RunCancelled:
                    raise
                except Exception:
                    group_results[paz_key] = {}
                    mark_entries_processed(group_count)
                publish_progress(force=True)
        for paz_key, _group_entries in sorted_groups:
            merge_group_rows(group_results.get(paz_key, {}))

    return {key: tuple(value) for key, value in path_rows_lists.items() if value}


def _build_archive_texture_sidecar_path_rows_for_indices(
    entries: Sequence[ArchiveEntry],
    entry_indices: Sequence[int],
    *,
    worker_count: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_label: str = "Indexing changed archive texture sidecars...",
) -> Dict[str, Tuple[int, ...]]:
    grouped_sidecar_entries: Dict[str, List[Tuple[int, ArchiveEntry]]] = defaultdict(list)
    for raw_index in entry_indices:
        entry_index = int(raw_index)
        if entry_index < 0 or entry_index >= len(entries):
            continue
        entry = entries[entry_index]
        entry_basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
        if not _is_material_sidecar_extension(entry.extension, entry_basename):
            continue
        paz_key = str(entry.paz_file).strip().lower()
        grouped_sidecar_entries[paz_key].append((entry_index, entry))
    total_sidecars = sum(len(group_entries) for group_entries in grouped_sidecar_entries.values())
    if total_sidecars <= 0:
        return {}

    path_rows_lists: Dict[str, List[int]] = defaultdict(list)
    processed_count = 0
    progress_lock = threading.Lock()
    if on_progress is not None:
        on_progress(0, total_sidecars, f"{progress_label} 0 / {total_sidecars:,}")
    configured_workers = int(worker_count or 0)
    if configured_workers <= 0:
        configured_workers = min(12, max(4, (os.cpu_count() or 2) - 1), max(1, len(grouped_sidecar_entries)))
    configured_workers = min(max(configured_workers, 1), 16, max(1, len(grouped_sidecar_entries)))
    sorted_groups = [
        (paz_key, sorted(grouped_sidecar_entries[paz_key], key=lambda item: item[1].offset))
        for paz_key in sorted(grouped_sidecar_entries)
    ]

    def mark_entries_processed(count: int = 1) -> None:
        nonlocal processed_count
        if count <= 0:
            return
        with progress_lock:
            processed_count = min(total_sidecars, processed_count + int(count))
            if on_progress is not None:
                on_progress(
                    processed_count,
                    total_sidecars,
                    f"{progress_label} {processed_count:,} / {total_sidecars:,}",
                )

    if configured_workers <= 1 or total_sidecars < 2_000:
        for paz_key, group_entries in sorted_groups:
            del paz_key
            raise_if_cancelled(stop_event)
            group_rows = _build_archive_texture_sidecar_path_rows_for_group(
                group_entries,
                stop_event=stop_event,
                on_entry_processed=mark_entries_processed,
            )
            for normalized_texture, row_indices in group_rows.items():
                if row_indices:
                    path_rows_lists[normalized_texture].extend(row_indices)
            if on_progress is not None:
                on_progress(
                    processed_count,
                    total_sidecars,
                    f"{progress_label} {processed_count:,} / {total_sidecars:,}",
                )
    else:
        with ThreadPoolExecutor(max_workers=configured_workers, thread_name_prefix="ArchiveSidecarIndex") as executor:
            future_by_count = {
                executor.submit(
                    _build_archive_texture_sidecar_path_rows_for_group,
                    group_entries,
                    stop_event=stop_event,
                    on_entry_processed=mark_entries_processed,
                ): len(group_entries)
                for _paz_key, group_entries in sorted_groups
            }
            for future in as_completed(future_by_count):
                group_count = future_by_count[future]
                raise_if_cancelled(stop_event)
                try:
                    group_rows = future.result()
                except RunCancelled:
                    raise
                except Exception:
                    group_rows = {}
                    mark_entries_processed(group_count)
                for normalized_texture, row_indices in group_rows.items():
                    if row_indices:
                        path_rows_lists[normalized_texture].extend(row_indices)
                if on_progress is not None:
                    on_progress(
                        processed_count,
                        total_sidecars,
                        f"{progress_label} {processed_count:,} / {total_sidecars:,}",
                    )
    return {key: tuple(value) for key, value in path_rows_lists.items() if value}


def _incremental_archive_texture_sidecar_path_rows(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
    cached_path_rows: Dict[str, Tuple[int, ...]],
    cached_entry_signatures: object,
    *,
    worker_count: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Optional[Dict[str, Tuple[int, ...]]]:
    if not isinstance(cached_entry_signatures, (list, tuple)):
        return None
    try:
        old_signatures = tuple(tuple(signature) for signature in cached_entry_signatures)
    except Exception:
        return None
    current_signatures = _build_archive_entry_cache_signatures(package_root, entries)

    current_by_signature: Dict[Tuple[object, ...], int] = {}
    duplicate_current_signatures: set[Tuple[object, ...]] = set()
    for current_index, signature in enumerate(current_signatures):
        if signature in current_by_signature:
            duplicate_current_signatures.add(signature)
            continue
        current_by_signature[signature] = current_index
    for signature in duplicate_current_signatures:
        current_by_signature.pop(signature, None)

    old_to_current: Dict[int, int] = {}
    reused_current_indices: set[int] = set()
    for old_index, signature in enumerate(old_signatures):
        current_index = current_by_signature.get(signature)
        if current_index is None:
            continue
        old_to_current[old_index] = current_index
        reused_current_indices.add(current_index)

    changed_sidecar_indices = [
        index
        for index, entry in enumerate(entries)
        if _is_material_sidecar_extension(
            entry.extension,
            PurePosixPath(entry.path.replace("\\", "/")).name.lower(),
        )
        and index not in reused_current_indices
    ]
    if old_to_current and not changed_sidecar_indices and len(current_signatures) == len(old_signatures):
        if on_log is not None:
            on_log("Texture sidecar cache metadata changed, but all sidecar rows remapped without rescanning.")
    elif on_log is not None:
        on_log(
            "Texture sidecar cache is partially out of date; "
            f"reusing {len(reused_current_indices):,} unchanged entries, rescanning {len(changed_sidecar_indices):,} sidecar entries."
        )

    merge_started_at = time.perf_counter()
    remapped_rows_lists: Dict[str, List[int]] = defaultdict(list)
    for normalized_texture, old_indices in cached_path_rows.items():
        for old_index in old_indices:
            current_index = old_to_current.get(int(old_index))
            if current_index is not None:
                remapped_rows_lists[normalized_texture].append(current_index)
    _record_timing(timings, "incremental_remap_s", merge_started_at)

    scan_started_at = time.perf_counter()
    changed_rows = _build_archive_texture_sidecar_path_rows_for_indices(
        entries,
        changed_sidecar_indices,
        worker_count=worker_count,
        stop_event=stop_event,
        on_progress=on_progress,
    )
    _record_timing(timings, "incremental_scan_s", scan_started_at)
    for normalized_texture, current_indices in changed_rows.items():
        remapped_rows_lists[normalized_texture].extend(int(index) for index in current_indices)

    return {
        key: tuple(dict.fromkeys(value))
        for key, value in remapped_rows_lists.items()
        if value
    }


def _build_archive_sidecar_basename_rows_from_path_rows(
    path_rows: Dict[str, Tuple[int, ...]],
) -> Dict[str, Tuple[int, ...]]:
    basename_rows_lists: Dict[str, List[int]] = defaultdict(list)
    for normalized_texture, raw_indexes in path_rows.items():
        texture_basename = PurePosixPath(str(normalized_texture or "").strip().lower()).name
        if not texture_basename or not raw_indexes:
            continue
        basename_rows_lists[texture_basename].extend(int(index) for index in raw_indexes)
    return {key: tuple(value) for key, value in basename_rows_lists.items() if value}


def build_archive_texture_sidecar_basename_rows(
    path_rows: Dict[str, Tuple[int, ...]],
) -> Dict[str, Tuple[int, ...]]:
    return _build_archive_sidecar_basename_rows_from_path_rows(path_rows)


def resolve_archive_texture_sidecar_entry_rows(
    rows: object,
    entries: Sequence[ArchiveEntry],
) -> Dict[str, List[ArchiveEntry]]:
    return _deserialize_archive_sidecar_entry_rows(rows, entries)


def build_lazy_archive_texture_sidecar_entry_index(
    rows: Optional[Dict[str, Tuple[int, ...]]],
    entries: Sequence[ArchiveEntry],
) -> LazyArchiveEntryRowIndex:
    return LazyArchiveEntryRowIndex(rows, entries)


def build_archive_texture_sidecar_entry_index(
    entries: Sequence[ArchiveEntry],
    *,
    worker_count: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_label: str = "Indexing archive texture sidecars...",
) -> Tuple[Dict[str, List[ArchiveEntry]], Dict[str, List[ArchiveEntry]]]:
    path_rows = build_archive_texture_sidecar_path_rows(
        entries,
        worker_count=worker_count,
        stop_event=stop_event,
        on_progress=on_progress,
        progress_label=progress_label,
    )
    if not path_rows:
        return {}, {}
    basename_rows = _build_archive_sidecar_basename_rows_from_path_rows(path_rows)
    return (
        _deserialize_archive_sidecar_entry_rows(path_rows, entries),
        _deserialize_archive_sidecar_entry_rows(basename_rows, entries),
    )


def _serialize_archive_sidecar_entry_rows(
    index: Dict[str, List[ArchiveEntry]],
    *,
    entry_positions_by_identity: Dict[int, int],
) -> Dict[str, Tuple[int, ...]]:
    rows: Dict[str, Tuple[int, ...]] = {}
    for key, entries_for_key in index.items():
        normalized_key = str(key or "").strip().lower()
        if not normalized_key:
            continue
        entry_indexes: List[int] = []
        seen_indexes: set[int] = set()
        for entry in entries_for_key:
            entry_index = entry_positions_by_identity.get(id(entry))
            if entry_index is None or entry_index in seen_indexes:
                continue
            seen_indexes.add(entry_index)
            entry_indexes.append(entry_index)
        if entry_indexes:
            rows[normalized_key] = tuple(entry_indexes)
    return rows


def _deserialize_archive_sidecar_entry_rows(
    rows: object,
    entries: Sequence[ArchiveEntry],
) -> Dict[str, List[ArchiveEntry]]:
    if not isinstance(rows, dict):
        raise ValueError("Texture sidecar cache rows are invalid.")
    resolved_entries = list(entries)
    entry_count = len(resolved_entries)
    index: Dict[str, List[ArchiveEntry]] = {}
    for key, raw_indexes in rows.items():
        normalized_key = str(key or "").strip().lower()
        if not normalized_key:
            continue
        if not isinstance(raw_indexes, (list, tuple)):
            raise ValueError("Texture sidecar cache entry references are invalid.")
        resolved_for_key: List[ArchiveEntry] = []
        seen_indexes: set[int] = set()
        for raw_index in raw_indexes:
            entry_index = int(raw_index)
            if entry_index < 0 or entry_index >= entry_count:
                raise ValueError("Texture sidecar cache entry index is out of range.")
            if entry_index in seen_indexes:
                continue
            seen_indexes.add(entry_index)
            resolved_for_key.append(resolved_entries[entry_index])
        if resolved_for_key:
            index[normalized_key] = resolved_for_key
    return index


def save_archive_texture_sidecar_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    entries_by_texture_path: Optional[Dict[str, List[ArchiveEntry]]] = None,
    entries_by_texture_basename: Optional[Dict[str, List[ArchiveEntry]]] = None,
    path_rows: Optional[Dict[str, Tuple[int, ...]]] = None,
    basename_rows: Optional[Dict[str, Tuple[int, ...]]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Path:
    started_at = time.perf_counter()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = resolve_archive_sidecar_cache_path(package_root, cache_root)
    metadata_path = resolve_archive_sidecar_cache_metadata_path(package_root, cache_root)
    _base_dir, sources = _collect_archive_scan_sources_from_entries(package_root, entries)
    if on_progress is not None:
        on_progress(0, 0, "Writing texture sidecar cache...")
    raise_if_cancelled(stop_event)
    entry_positions_by_identity: Optional[Dict[int, int]] = None
    if path_rows is None:
        if entries_by_texture_path is None:
            raise ValueError("entries_by_texture_path is required when path_rows is not provided.")
        entry_positions_by_identity = {id(entry): index for index, entry in enumerate(entries)}
        path_rows = _serialize_archive_sidecar_entry_rows(
            entries_by_texture_path,
            entry_positions_by_identity=entry_positions_by_identity,
        )
    if basename_rows is None:
        if entries_by_texture_basename is not None:
            if entry_positions_by_identity is None:
                entry_positions_by_identity = {id(entry): index for index, entry in enumerate(entries)}
            basename_rows = _serialize_archive_sidecar_entry_rows(
                entries_by_texture_basename,
                entry_positions_by_identity=entry_positions_by_identity,
            )
        else:
            basename_rows = _build_archive_sidecar_basename_rows_from_path_rows(path_rows)
    payload = {
        "version": _ARCHIVE_SIDECAR_CACHE_VERSION,
        "created_at": time.time(),
        "sources": sources,
        "entry_count": len(entries),
        "entry_signature_format": _ARCHIVE_SIDECAR_ENTRY_SIGNATURE_FORMAT,
        "entry_signatures": _build_archive_entry_cache_signatures(package_root, entries),
        "path_rows": path_rows,
        "basename_rows": basename_rows,
    }
    _write_raw_pickle_cache_payload_to_path(
        cache_path,
        magic=_ARCHIVE_SIDECAR_CACHE_MAGIC,
        payload=payload,
    )
    try:
        _write_archive_sidecar_cache_metadata(
            metadata_path,
            version=_ARCHIVE_SIDECAR_CACHE_VERSION,
            sources=sources,
            entry_count=len(entries),
        )
    except Exception as exc:
        if on_log is not None:
            on_log(f"Warning: texture sidecar cache metadata could not be written: {exc}")
    if on_progress is not None:
        on_progress(1, 1, "Texture sidecar cache is ready.")
    if on_log is not None:
        on_log(f"Texture sidecar cache updated: {cache_path}")
    _record_timing(timings, "cache_write_s", started_at)
    return cache_path


def load_archive_texture_sidecar_cache_rows(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    worker_count: Optional[int] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Optional[Tuple[Dict[str, Tuple[int, ...]], Dict[str, Tuple[int, ...]]]]:
    check_started_at = time.perf_counter()
    cache_path = resolve_archive_sidecar_cache_path(package_root, cache_root)
    metadata_path = resolve_archive_sidecar_cache_metadata_path(package_root, cache_root)
    if not cache_path.exists():
        if timings is not None:
            timings.setdefault("cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("cache_load_s", 0.0)
        return None
    if on_progress is not None:
        on_progress(0, 0, "Checking texture sidecar cache...")
    try:
        _base_dir, current_sources = _collect_archive_scan_sources_from_entries(package_root, entries)
    except Exception as exc:
        if on_log is not None:
            on_log(f"Texture sidecar cache check failed; rebuilding it now: {exc}")
        if timings is not None:
            timings.setdefault("cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("cache_load_s", 0.0)
        return None

    metadata_payload: Optional[dict] = None
    metadata_mismatch_reasons: List[str] = []
    if metadata_path.exists():
        try:
            metadata_payload = _read_archive_sidecar_cache_metadata(metadata_path)
        except Exception as exc:
            if on_log is not None:
                on_log(f"Texture sidecar cache metadata could not be read; falling back to the full cache payload: {exc}")

    if metadata_payload is not None:
        cached_version = int(metadata_payload.get("version", 0))
        if cached_version not in _ARCHIVE_SIDECAR_CACHE_SUPPORTED_VERSIONS:
            if on_log is not None:
                on_log("Texture sidecar cache metadata format changed; rebuilding it now.")
            return None
        cached_sources = _normalize_archive_source_rows(metadata_payload.get("sources"))
        cached_entry_count = int(metadata_payload.get("entry_count", -1))
        if cached_sources != current_sources or cached_entry_count != len(entries):
            metadata_mismatch_reasons = _describe_archive_cache_metadata_mismatch(
                cached_sources,
                current_sources,
                cached_entry_count,
                len(entries),
            )
            if on_log is not None:
                on_log(
                    "Texture sidecar cache metadata changed: "
                    + "; ".join(metadata_mismatch_reasons or ["metadata changed"])
                    + ". Checking cache payload for reuse."
                )

    if on_progress is not None:
        on_progress(0, 0, "Loading texture sidecar cache...")
    try:
        if timings is not None:
            timings["cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
        load_started_at = time.perf_counter()
        data = _deserialize_cache_payload_from_path(
            cache_path,
            magic=_ARCHIVE_SIDECAR_CACHE_MAGIC,
            invalid_message="Texture sidecar cache header is not recognized.",
        )
    except Exception as exc:
        if on_log is not None:
            on_log(f"Texture sidecar cache could not be read; rebuilding it now: {exc}")
        return None

    if int(data.get("version", 0)) not in _ARCHIVE_SIDECAR_CACHE_SUPPORTED_VERSIONS:
        if on_log is not None:
            on_log("Texture sidecar cache format changed; rebuilding it now.")
        return None

    try:
        raise_if_cancelled(stop_event)
        raw_path_rows = {
            str(key or "").strip().lower(): tuple(int(index) for index in value)
            for key, value in (data.get("path_rows", {}) or {}).items()
            if isinstance(value, (list, tuple)) and str(key or "").strip()
        }
        cached_sources = _normalize_archive_source_rows(data.get("sources"))
        cached_entry_count = int(data.get("entry_count", -1))
        payload_matches_current_archives = cached_sources == current_sources and cached_entry_count == len(entries)
        if timings is not None and "cache_load_s" not in timings:
            timings["cache_load_s"] = max(0.0, float(time.perf_counter() - load_started_at))
        if not payload_matches_current_archives:
            payload_mismatch_reasons = _describe_archive_cache_metadata_mismatch(
                cached_sources,
                current_sources,
                cached_entry_count,
                len(entries),
            )
            if on_log is not None:
                on_log(
                    "Texture sidecar cache payload is out of date: "
                    + "; ".join(payload_mismatch_reasons or ["archive metadata changed"])
                )
            cache_version = int(data.get("version", 0))
            signature_format = int(data.get("entry_signature_format", 0) or 0)
            if cache_version >= 9 and signature_format == _ARCHIVE_SIDECAR_ENTRY_SIGNATURE_FORMAT:
                incremental_started_at = time.perf_counter()
                updated_path_rows = _incremental_archive_texture_sidecar_path_rows(
                    package_root,
                    entries,
                    raw_path_rows,
                    data.get("entry_signatures"),
                    worker_count=worker_count,
                    stop_event=stop_event,
                    on_log=on_log,
                    on_progress=on_progress,
                    timings=timings,
                )
                _record_timing(timings, "incremental_update_s", incremental_started_at)
                if updated_path_rows is not None:
                    updated_basename_rows = _build_archive_sidecar_basename_rows_from_path_rows(updated_path_rows)
                    try:
                        save_archive_texture_sidecar_cache(
                            package_root,
                            cache_root,
                            entries,
                            path_rows=updated_path_rows,
                            basename_rows=updated_basename_rows,
                            on_log=on_log,
                            on_progress=on_progress,
                            stop_event=stop_event,
                            timings=timings,
                        )
                    except Exception as exc:
                        if on_log is not None:
                            on_log(f"Warning: incrementally updated texture sidecar cache could not be written: {exc}")
                    if on_progress is not None:
                        on_progress(1, 1, "Texture sidecar cache loaded.")
                    return updated_path_rows, updated_basename_rows
                if on_log is not None:
                    on_log("Texture sidecar cache could not be updated incrementally; rebuilding it now.")
            elif on_log is not None:
                on_log("Texture sidecar cache is stale and does not contain v9 entry signatures; rebuilding it now.")
            return None

        raw_basename_rows = data.get("basename_rows")
        if isinstance(raw_basename_rows, dict):
            basename_rows = {
                str(key or "").strip().lower(): tuple(int(index) for index in value)
                for key, value in raw_basename_rows.items()
                if isinstance(value, (list, tuple)) and str(key or "").strip()
            }
        else:
            basename_rows = _build_archive_sidecar_basename_rows_from_path_rows(raw_path_rows)
        _record_timing(timings, "cache_load_s", load_started_at)
    except Exception as exc:
        if on_log is not None:
            on_log(f"Texture sidecar cache could not be applied; rebuilding it now: {exc}")
        return None

    metadata_refreshed_by_cache_write = False
    if int(data.get("version", 0)) < _ARCHIVE_SIDECAR_CACHE_VERSION:
        try:
            save_archive_texture_sidecar_cache(
                package_root,
                cache_root,
                entries,
                path_rows=raw_path_rows,
                basename_rows=basename_rows,
                on_log=on_log,
                on_progress=None,
                stop_event=stop_event,
                timings=timings,
            )
            metadata_refreshed_by_cache_write = True
            if on_log is not None:
                on_log("Texture sidecar cache upgraded to the current metadata format without rescanning.")
        except Exception as exc:
            if on_log is not None:
                on_log(f"Warning: texture sidecar cache could not be upgraded after loading: {exc}")

    if not metadata_refreshed_by_cache_write and (metadata_payload is None or metadata_mismatch_reasons):
        try:
            _write_archive_sidecar_cache_metadata(
                metadata_path,
                version=int(data.get("version", _ARCHIVE_SIDECAR_CACHE_VERSION)),
                sources=current_sources,
                entry_count=len(entries),
            )
            if metadata_mismatch_reasons and on_log is not None:
                on_log("Texture sidecar cache metadata was stale, but payload matched current archives; metadata refreshed without rescanning.")
        except Exception:
            pass

    if on_progress is not None:
        on_progress(1, 1, "Texture sidecar cache loaded.")
    if on_log is not None:
        on_log("Loaded texture sidecar bindings from cache.")
    return raw_path_rows, basename_rows


def load_archive_texture_sidecar_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    worker_count: Optional[int] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    timings: Optional[Dict[str, float]] = None,
) -> Optional[Tuple[Dict[str, List[ArchiveEntry]], Dict[str, List[ArchiveEntry]]]]:
    cached_rows = load_archive_texture_sidecar_cache_rows(
        package_root,
        cache_root,
        entries,
        worker_count=worker_count,
        on_log=on_log,
        on_progress=on_progress,
        stop_event=stop_event,
        timings=timings,
    )
    if cached_rows is None:
        return None
    path_rows, basename_rows = cached_rows
    return (
        _deserialize_archive_sidecar_entry_rows(path_rows, entries),
        _deserialize_archive_sidecar_entry_rows(basename_rows, entries),
    )


def build_archive_texture_sidecar_entry_index_cached(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    worker_count: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[Dict[str, List[ArchiveEntry]], Dict[str, List[ArchiveEntry]], str, Optional[Path]]:
    cache_path = resolve_archive_sidecar_cache_path(package_root, cache_root)
    cached = load_archive_texture_sidecar_cache(
        package_root,
        cache_root,
        entries,
        worker_count=worker_count,
        on_log=on_log,
        on_progress=on_progress,
        stop_event=stop_event,
    )
    if cached is not None:
        entries_by_texture_path, entries_by_texture_basename = cached
        return entries_by_texture_path, entries_by_texture_basename, "cache", cache_path

    if on_log is not None:
        on_log("Indexing texture sidecar bindings for related-file discovery...")
    path_rows = build_archive_texture_sidecar_path_rows(
        entries,
        worker_count=worker_count,
        stop_event=stop_event,
        on_progress=on_progress,
    )
    basename_rows = _build_archive_sidecar_basename_rows_from_path_rows(path_rows)
    entries_by_texture_path = _deserialize_archive_sidecar_entry_rows(path_rows, entries) if path_rows else {}
    entries_by_texture_basename = (
        _deserialize_archive_sidecar_entry_rows(basename_rows, entries) if basename_rows else {}
    )
    try:
        cache_path = save_archive_texture_sidecar_cache(
            package_root,
            cache_root,
            entries,
            path_rows=path_rows,
            basename_rows=basename_rows if int(_ARCHIVE_SIDECAR_CACHE_VERSION) <= 1 else None,
            entries_by_texture_path=entries_by_texture_path,
            entries_by_texture_basename=entries_by_texture_basename,
            on_log=on_log,
            on_progress=on_progress,
            stop_event=stop_event,
        )
    except Exception as exc:
        if on_log is not None:
            on_log(f"Warning: texture sidecar cache could not be written: {exc}")
        cache_path = None
    return entries_by_texture_path, entries_by_texture_basename, "scan", cache_path


def build_archive_structure_children_map(entries: Sequence[ArchiveEntry]) -> Dict[str, List[Tuple[str, int]]]:
    child_counts: Dict[str, Dict[str, int]] = defaultdict(dict)
    folder_counts: Dict[Tuple[str, ...], int] = defaultdict(int)
    package_dir_cache: Dict[Path, str] = {}
    folder_parts_cache: Dict[str, Tuple[str, ...]] = {"": ()}

    for entry in entries:
        package_dir = package_dir_cache.get(entry.pamt_path)
        if package_dir is None:
            package_dir = entry.pamt_path.parent.name.strip().lower() or "package"
            package_dir_cache[entry.pamt_path] = package_dir
        normalized_path = entry.path.replace("\\", "/").lower()
        folder_text, _, _basename = normalized_path.rpartition("/")
        raw_parts = folder_parts_cache.get(folder_text)
        if raw_parts is None:
            raw_parts = tuple(
                part
                for part in folder_text.split("/")
                if part not in {"", ".", ".."}
            )
            folder_parts_cache[folder_text] = raw_parts
        folder_counts[(package_dir, *raw_parts)] += 1

    for parts, count in folder_counts.items():
        parent = ""
        child_value = ""
        for part in parts:
            child_value = f"{child_value}/{part}" if child_value else part
            parent_counts = child_counts[parent]
            parent_counts[child_value] = parent_counts.get(child_value, 0) + count
            parent = child_value

    def leaf_sort_key(value: str) -> Tuple[int, int, str]:
        leaf = value.rsplit("/", 1)[-1]
        if leaf.isdigit():
            return (0, int(leaf), leaf)
        return (1, 0, leaf)

    return {
        parent: sorted(children.items(), key=lambda item: leaf_sort_key(item[0]))
        for parent, children in child_counts.items()
    }


def build_archive_tree_index(
    entries: Sequence[ArchiveEntry],
    *,
    preserve_direct_file_order: bool = False,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[
    Dict[Tuple[str, ...], List[Tuple[str, Tuple[str, ...]]]],
    Dict[Tuple[str, ...], List[int]],
    Dict[Tuple[str, ...], List[int]],
    Dict[Tuple[str, ...], Tuple[int, int, int]],
]:
    child_folder_sets: Dict[Tuple[str, ...], Dict[Tuple[str, ...], str]] = defaultdict(dict)
    direct_files: Dict[Tuple[str, ...], List[Tuple[str, int]]] = defaultdict(list)
    folder_entry_indexes: Dict[Tuple[str, ...], List[int]] = defaultdict(list)
    folder_preview_stats: Dict[Tuple[str, ...], List[int]] = defaultdict(lambda: [0, 0, 0])
    folder_key_cache: Dict[str, Tuple[str, ...]] = {"": ()}
    folder_hierarchy_cache: Dict[Tuple[str, ...], Tuple[Tuple[Tuple[str, ...], Tuple[str, ...], str], ...]] = {(): ()}
    total_entries = len(entries)
    progress_total = max(total_entries, 1)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000

    if on_progress:
        on_progress(0 if total_entries > 0 else 1, progress_total, f"Indexing archive browser tree... 0 / {total_entries:,} entries")

    for index, entry in enumerate(entries):
        current = index + 1
        if stop_event is not None and (current == 1 or current % 2048 == 0):
            raise_if_cancelled(stop_event)
        normalized_path = entry.path.replace("\\", "/")
        folder_text, _, basename = normalized_path.rpartition("/")
        if not basename:
            basename = normalized_path
        folder_key = folder_key_cache.get(folder_text)
        if folder_key is None:
            folder_key = tuple(
                part
                for part in folder_text.split("/")
                if part not in {"", ".", ".."}
            )
            folder_key_cache[folder_text] = folder_key
        if not folder_key and basename in {"", ".", ".."}:
            continue

        direct_files[folder_key].append((basename.lower(), index))
        folder_entry_indexes[()].append(index)
        root_stats = folder_preview_stats[()]
        root_stats[0] += 1
        root_stats[1] += int(entry.orig_size)
        root_stats[2] += int(entry.comp_size)
        hierarchy = folder_hierarchy_cache.get(folder_key)
        if hierarchy is None:
            parent_key: Tuple[str, ...] = ()
            built_hierarchy: List[Tuple[Tuple[str, ...], Tuple[str, ...], str]] = []
            child_key_parts: List[str] = []
            for part in folder_key:
                child_key_parts.append(part)
                child_key = tuple(child_key_parts)
                built_hierarchy.append((parent_key, child_key, part))
                parent_key = child_key
            hierarchy = tuple(built_hierarchy)
            folder_hierarchy_cache[folder_key] = hierarchy
        for parent_key, child_key, part in hierarchy:
            child_folder_sets[parent_key][child_key] = part
            folder_entry_indexes[child_key].append(index)
            folder_stats = folder_preview_stats[child_key]
            folder_stats[0] += 1
            folder_stats[1] += int(entry.orig_size)
            folder_stats[2] += int(entry.comp_size)

        if on_progress and (current == 1 or current % update_every == 0 or current == total_entries):
            on_progress(current, progress_total, f"Indexing archive browser tree... {current:,} / {total_entries:,} entries")

    def folder_sort_key(item: Tuple[Tuple[str, ...], str]) -> Tuple[int, int, str]:
        _child_key, leaf = item
        if leaf.isdigit():
            return (0, int(leaf), leaf)
        return (1, 0, leaf)

    child_folders = {
        parent: sorted(
            ((leaf, child_key) for child_key, leaf in children.items()),
            key=lambda item: folder_sort_key((item[1], item[0])),
        )
        for parent, children in child_folder_sets.items()
    }
    if preserve_direct_file_order:
        direct_files_by_folder = dict(direct_files)
    else:
        direct_files_by_folder = {
            folder_key: sorted(
                indexes,
                key=lambda item: item[0],
            )
            for folder_key, indexes in direct_files.items()
        }
    direct_file_indexes = {
        folder_key: [index for _basename, index in sorted_items]
        for folder_key, sorted_items in direct_files_by_folder.items()
    }
    normalized_folder_preview_stats = {
        folder_key: (int(stats[0]), int(stats[1]), int(stats[2]))
        for folder_key, stats in folder_preview_stats.items()
    }
    return child_folders, direct_file_indexes, dict(folder_entry_indexes), normalized_folder_preview_stats


def prepare_archive_browser_state(
    entries: Sequence[ArchiveEntry],
    *,
    filter_text: str,
    exclude_filter_text: str,
    extension_filter: str,
    package_filter_text: str,
    structure_filter: str,
    role_filter: str,
    exclude_common_technical_suffixes: bool,
    min_size_kb: int,
    previewable_only: bool,
    item_search_aliases: Optional[Mapping[str, str]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_name_search_index: Optional[ArchiveNameSearchIndex] = None,
    build_structure_children: bool = True,
    build_tree_index: bool = True,
    sort_column: object = -1,
    sort_order: object = "asc",
    item_display_names: Optional[Mapping[str, str]] = None,
    item_exact_display_names: Optional[Mapping[str, str]] = None,
    item_related_display_names: Optional[Mapping[str, str]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> dict:
    sort_is_active = archive_browser_sort_is_active(sort_column)
    total_steps = (
        1
        + (1 if build_structure_children else 0)
        + (1 if sort_is_active else 0)
        + (1 if build_tree_index else 0)
    )
    current_step = 0
    structure_children: Dict[str, List[Tuple[str, int]]] = {}
    if build_structure_children:
        raise_if_cancelled(stop_event)
        current_step += 1
        if on_progress:
            on_progress(current_step, total_steps, "Building folder filters from archive entries...")
        structure_children = build_archive_structure_children_map(entries)

    raise_if_cancelled(stop_event)
    current_step += 1
    if on_progress:
        on_progress(current_step, total_steps, "Applying archive filters...")
    filtered_entries = filter_archive_entries(
        entries,
        filter_text=filter_text,
        exclude_filter_text=exclude_filter_text,
        extension_filter=extension_filter,
        package_filter_text=package_filter_text,
        structure_filter=structure_filter,
        role_filter=role_filter,
        exclude_common_technical_suffixes=exclude_common_technical_suffixes,
        min_size_kb=min_size_kb,
        previewable_only=previewable_only,
        item_search_aliases=item_search_aliases,
        archive_entries_by_basename=archive_entries_by_basename,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_name_search_index=archive_name_search_index,
        on_progress=on_progress,
        stop_event=stop_event,
    )
    if sort_is_active:
        raise_if_cancelled(stop_event)
        current_step += 1
        if on_progress:
            on_progress(current_step, total_steps, "Sorting archive browser rows...")
        filtered_entries = sort_archive_entries_for_browser(
            filtered_entries,
            sort_column,
            sort_order,
            item_display_names=item_display_names,
            item_exact_display_names=item_exact_display_names,
            item_related_display_names=item_related_display_names,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        )

    tree_child_folders: Dict[Tuple[str, ...], List[Tuple[str, Tuple[str, ...]]]] = {}
    tree_direct_files: Dict[Tuple[str, ...], List[int]] = {}
    folder_entry_indexes: Dict[Tuple[str, ...], List[int]] = {}
    folder_preview_stats: Dict[Tuple[str, ...], Tuple[int, int, int]] = {}
    if build_tree_index:
        raise_if_cancelled(stop_event)
        current_step += 1
        if on_progress:
            on_progress(current_step, total_steps, "Indexing archive browser tree...")
        tree_child_folders, tree_direct_files, folder_entry_indexes, folder_preview_stats = build_archive_tree_index(
            filtered_entries,
            preserve_direct_file_order=sort_is_active,
            on_progress=on_progress,
            stop_event=stop_event,
        )
    dds_count = sum(1 for entry in filtered_entries if entry.extension == ".dds")

    return {
        "structure_children": structure_children,
        "filtered_entries": filtered_entries,
        "tree_child_folders": tree_child_folders,
        "tree_direct_files": tree_direct_files,
        "tree_folder_entry_indexes": folder_entry_indexes,
        "tree_folder_preview_stats": folder_preview_stats,
        "tree_index_ready": build_tree_index,
        "dds_count": dds_count,
    }


class PathcCollection:
    def __init__(self, path: Path, raw_data: Optional[bytes] = None) -> None:
        raw = path.read_bytes() if raw_data is None else bytes(raw_data)
        if len(raw) < 32:
            raise ValueError(f"{path} is too small to be a valid .pathc file.")
        self.path = path
        self.raw_size = len(raw)
        (
            _reserved0,
            header_size,
            header_count,
            entry_count,
            collision_entry_count,
            filenames_length,
        ) = struct.unpack_from("<QIIIII", raw, 0)
        self.reserved0 = _reserved0
        offset = struct.calcsize("<QIIIII")
        self.header_size = header_size
        self.header_count = header_count
        self.entry_count = entry_count
        self.collision_entry_count = collision_entry_count
        self.filenames_length = filenames_length
        self.headers: List[bytes] = []
        for _ in range(header_count):
            header = raw[offset : offset + header_size]
            if len(header) != header_size:
                raise ValueError(f"{path.name} texture header block is truncated.")
            self.headers.append(header)
            offset += header_size
        checksums: List[int] = []
        for _ in range(entry_count):
            if offset + 4 > len(raw):
                raise ValueError(f"{path.name} checksum table is truncated.")
            checksums.append(struct.unpack_from("<I", raw, offset)[0])
            offset += 4
        self.checksums = tuple(checksums)
        entries: List[PathcEntry] = []
        for entry_index in range(entry_count):
            if offset + 20 > len(raw):
                raise ValueError(f"{path.name} entry table is truncated.")
            texture_header_index, collision_start_index, collision_end_index, compressed_block_infos = struct.unpack_from(
                "<HBB16s",
                raw,
                offset,
            )
            checksum = checksums[entry_index] if entry_index < len(checksums) else 0
            entries.append(
                PathcEntry(
                    texture_header_index=texture_header_index,
                    collision_start_index=collision_start_index,
                    collision_end_index=collision_end_index,
                    compressed_block_infos=compressed_block_infos,
                    checksum=checksum,
                )
            )
            offset += 20
        self.entries = {checksum: entry for checksum, entry in zip(checksums, entries)}
        self.entry_rows = tuple(entries)
        collision_entries: List[PathcCollisionEntry] = []
        for _ in range(collision_entry_count):
            if offset + 24 > len(raw):
                raise ValueError(f"{path.name} collision table is truncated.")
            filename_offset, texture_header_index, unknown0, compressed_block_infos = struct.unpack_from(
                "<IHH16s",
                raw,
                offset,
            )
            collision_entries.append(
                PathcCollisionEntry(
                    filename_offset=filename_offset,
                    texture_header_index=texture_header_index,
                    unknown0=unknown0,
                    compressed_block_infos=compressed_block_infos,
                )
            )
            offset += 24
        filenames = raw[offset : offset + filenames_length]
        if len(filenames) != filenames_length:
            raise ValueError(f"{path.name} filename table is truncated.")
        self.filename_blob = filenames
        self.hash_collision_entries: Dict[str, PathcCollisionEntry] = {}
        for entry in collision_entries:
            end = filenames.find(b"\x00", entry.filename_offset)
            if end < 0:
                end = len(filenames)
            name = filenames[entry.filename_offset:end].decode("utf-8", errors="replace")
            entry.path = name
            self.hash_collision_entries[name] = entry
        self.collision_entries = tuple(collision_entries)
        self.direct_mapping_count = 0
        self.collision_mapping_count = 0
        self.invalid_mapping_count = 0
        self.unknown_mapping_count = 0
        for entry in self.entry_rows:
            if entry.texture_header_index != 0xFFFF:
                if 0 <= int(entry.texture_header_index) < len(self.headers):
                    self.direct_mapping_count += 1
                else:
                    self.invalid_mapping_count += 1
                continue
            if int(entry.collision_start_index) < int(entry.collision_end_index):
                self.collision_mapping_count += 1
            else:
                self.unknown_mapping_count += 1

    def get_file_header(self, path: str) -> bytes:
        lookup = self.lookup_file(path)
        if lookup.mapping_mode not in {"direct", "collision"} or lookup.texture_header_index < 0:
            raise KeyError(lookup.normalized_path)
        header = self.headers[lookup.texture_header_index]
        compressed_block_infos = lookup.compressed_block_infos
        if self.header_size == 0x94:
            return header[:0x20] + compressed_block_infos + header[0x30:]
        return header

    def lookup_file(self, path: str) -> PathcLookupResult:
        normalized = str(path or "").replace("\\", "/").lstrip("/")
        checksum = calculate_pa_checksum(f"/{normalized}")
        entry = self.entries.get(checksum)
        if entry is None:
            return PathcLookupResult(
                normalized_path=normalized,
                checksum=checksum,
                mapping_mode="missing",
                message="No PATHC hash entry matched this path.",
            )
        if entry.texture_header_index != 0xFFFF:
            header_index = int(entry.texture_header_index)
            if 0 <= header_index < len(self.headers):
                return PathcLookupResult(
                    normalized_path=normalized,
                    checksum=checksum,
                    mapping_mode="direct",
                    texture_header_index=header_index,
                    header_size=self.header_size,
                    compressed_block_infos=entry.compressed_block_infos,
                )
            return PathcLookupResult(
                normalized_path=normalized,
                checksum=checksum,
                mapping_mode="invalid",
                texture_header_index=header_index,
                header_size=self.header_size,
                compressed_block_infos=entry.compressed_block_infos,
                message="Direct PATHC header index is outside the header table.",
            )

        collision_entry = self.hash_collision_entries.get(normalized)
        if collision_entry is None:
            return PathcLookupResult(
                normalized_path=normalized,
                checksum=checksum,
                mapping_mode="missing",
                texture_header_index=-1,
                header_size=self.header_size,
                compressed_block_infos=entry.compressed_block_infos,
                message="PATHC hash entry uses collision mapping, but no collision path matched this file.",
            )
        header_index = int(collision_entry.texture_header_index)
        if not (0 <= header_index < len(self.headers)):
            return PathcLookupResult(
                normalized_path=normalized,
                checksum=checksum,
                mapping_mode="invalid",
                texture_header_index=header_index,
                header_size=self.header_size,
                compressed_block_infos=collision_entry.compressed_block_infos,
                collision_path=collision_entry.path,
                message="Collision PATHC header index is outside the header table.",
            )
        return PathcLookupResult(
            normalized_path=normalized,
            checksum=checksum,
            mapping_mode="collision",
            texture_header_index=header_index,
            header_size=self.header_size,
            compressed_block_infos=collision_entry.compressed_block_infos,
            collision_path=collision_entry.path,
        )

    def iter_collision_samples(self, limit: int = 16) -> Tuple[PathcCollisionEntry, ...]:
        return tuple(self.collision_entries[: max(0, int(limit))])


def load_pathc_collection(path: Path) -> PathcCollection:
    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    stamp = f"{stat.st_size}:{stat.st_mtime_ns}"
    cache_key = str(resolved).lower()
    cached = _PATHC_COLLECTION_CACHE.get(cache_key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    collection = PathcCollection(resolved)
    _PATHC_COLLECTION_CACHE[cache_key] = (stamp, collection)
    return collection


def resolve_archive_meta_root(entry: ArchiveEntry) -> Path:
    return entry.pamt_path.parent.parent / "meta"


def resolve_archive_pathc_path(entry: ArchiveEntry) -> Path:
    return resolve_archive_meta_root(entry) / "0.pathc"


def get_archive_partial_dds_header(entry: ArchiveEntry) -> bytes:
    pathc_path = resolve_archive_pathc_path(entry)
    if not pathc_path.is_file():
        raise ValueError(f"Partial DDS metadata was not found: {pathc_path}")
    collection = load_pathc_collection(pathc_path)
    candidates = [
        entry.path.replace("\\", "/").lstrip("/"),
        PurePosixPath(entry.path.replace("\\", "/")).as_posix().lstrip("/"),
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return collection.get_file_header(candidate)
        except KeyError:
            continue
    raise ValueError(f"Partial DDS header not found in {pathc_path} for {entry.path}")


def _format_pathc_block_infos(block_infos: bytes) -> str:
    if len(block_infos) < 16:
        return block_infos.hex(" ").upper() if block_infos else "none"
    values = struct.unpack_from("<4I", block_infos, 0)
    return ", ".join(f"mip{i}={value:,}" for i, value in enumerate(values))


def _format_pathc_lookup_detail(lookup: PathcLookupResult) -> str:
    lines = [
        "PATHC Lookup:",
        f"- Path: {lookup.normalized_path or '-'}",
        f"- Hash/checksum: 0x{lookup.checksum:08X}",
        f"- Mapping: {lookup.mapping_mode}",
    ]
    if lookup.texture_header_index >= 0:
        lines.append(f"- Texture header index: {lookup.texture_header_index:,}")
    if lookup.header_size:
        lines.append(f"- Header record size: {lookup.header_size:,} bytes")
    if lookup.compressed_block_infos:
        lines.append(f"- First-four-mip / block metadata: {_format_pathc_block_infos(lookup.compressed_block_infos)}")
    if lookup.collision_path:
        lines.append(f"- Collision path: {lookup.collision_path}")
    if lookup.message:
        lines.append(f"- Note: {lookup.message}")
    return "\n".join(lines)


def build_archive_pathc_preview(data: bytes, virtual_path: str) -> _StructuredBinaryPreviewBundle:
    collection = PathcCollection(Path(PurePosixPath(virtual_path.replace("\\", "/")).name or "0.pathc"), raw_data=data)
    lines = [
        f"PATHC texture path index preview for {virtual_path}",
        "",
        "Summary:",
        f"- Header record size: {collection.header_size:,} bytes",
        f"- DDS template/header records: {collection.header_count:,}",
        f"- Path hash entries: {collection.entry_count:,}",
        f"- Collision path entries: {collection.collision_entry_count:,}",
        f"- Filename table size: {collection.filenames_length:,} bytes",
        f"- Direct mappings: {collection.direct_mapping_count:,}",
        f"- Collision mappings: {collection.collision_mapping_count:,}",
        f"- Unknown mappings: {collection.unknown_mapping_count:,}",
        f"- Invalid mappings: {collection.invalid_mapping_count:,}",
    ]
    collision_samples = collection.iter_collision_samples(limit=16)
    if collision_samples:
        lines.extend(["", "Collision path samples:"])
        for index, collision_entry in enumerate(collision_samples, start=1):
            block_info_text = _format_pathc_block_infos(collision_entry.compressed_block_infos)
            lines.append(
                f"- [{index:02d}] header={collision_entry.texture_header_index} "
                f"offset={collision_entry.filename_offset} path={collision_entry.path or '<empty>'} "
                f"blocks=({block_info_text})"
            )
        if len(collection.collision_entries) > len(collision_samples):
            lines.append(f"... {len(collection.collision_entries) - len(collision_samples):,} more collision path(s)")
    else:
        lines.extend(["", "Collision path samples:", "- None"])

    detail_lines = (
        f"PATHC contains {collection.header_count:,} DDS template/header record(s).",
        f"PATHC contains {collection.entry_count:,} path hash entry/entries.",
        f"Mapping types: direct={collection.direct_mapping_count:,}, collision={collection.collision_mapping_count:,}, "
        f"unknown={collection.unknown_mapping_count:,}, invalid={collection.invalid_mapping_count:,}.",
        "This inspector is read-only and does not change DDS reconstruction or mod packaging.",
    )
    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(lines),
        detail_lines=detail_lines,
        metadata_label="PATHC Texture Index",
    )


def build_archive_pathc_lookup_detail_for_entry(entry: ArchiveEntry) -> str:
    try:
        pathc_path = resolve_archive_pathc_path(entry)
        if not pathc_path.is_file():
            return ""
        collection = load_pathc_collection(pathc_path)
        return _format_pathc_lookup_detail(collection.lookup_file(entry.path))
    except Exception as exc:
        return f"PATHC Lookup:\n- Unavailable: {exc}"


def _dds_bytes_per_block(dxgi_format: int, four_cc: bytes) -> Optional[int]:
    block_8_formats = {71, 72, 80, 81}
    block_16_formats = {74, 75, 77, 78, 83, 84, 94, 95, 96, 98, 99}
    if dxgi_format in block_8_formats:
        return 8
    if dxgi_format in block_16_formats:
        return 16
    four_cc_upper = four_cc.upper()
    if four_cc_upper in {b"DXT1", b"BC4U", b"BC4S", b"ATI1"}:
        return 8
    if four_cc_upper in {b"DXT3", b"DXT5", b"BC5U", b"BC5S", b"ATI2", b"RXGB"}:
        return 16
    return None


def _dds_uncompressed_surface_size(
    width: int,
    height: int,
    pf_flags: int,
    rgb_bit_count: int,
    *,
    pitch_or_linear_size: int = 0,
    mip_level: int = 0,
) -> Optional[int]:
    if width <= 0 or height <= 0:
        return None
    if pf_flags & (DDPF_LUMINANCE | DDPF_RGB | DDPF_ALPHAPIXELS | DDPF_ALPHA):
        if rgb_bit_count > 0 and rgb_bit_count % 8 == 0:
            return width * height * max(1, rgb_bit_count // 8)
    if pitch_or_linear_size > 0:
        row_pitch = max(1, pitch_or_linear_size >> max(0, mip_level))
        return row_pitch * max(1, height)
    return None


def _dds_surface_size(
    width: int,
    height: int,
    dxgi_format: int,
    four_cc: bytes,
    *,
    pf_flags: int = 0,
    rgb_bit_count: int = 0,
    pitch_or_linear_size: int = 0,
    mip_level: int = 0,
) -> int:
    bytes_per_block = _dds_bytes_per_block(dxgi_format, four_cc)
    if bytes_per_block is not None:
        block_w = max(1, (max(1, width) + 3) // 4)
        block_h = max(1, (max(1, height) + 3) // 4)
        return block_w * block_h * bytes_per_block
    raw_surface_size = _dds_uncompressed_surface_size(
        width,
        height,
        pf_flags,
        rgb_bit_count,
        pitch_or_linear_size=pitch_or_linear_size,
        mip_level=mip_level,
    )
    if raw_surface_size is not None:
        return raw_surface_size
    raise ValueError(
        f"Unsupported DDS partial compression format: DXGI={dxgi_format} FOURCC={four_cc!r}"
    )


def reconstruct_partial_dds(entry: ArchiveEntry, data: bytes) -> bytes:
    header = get_archive_partial_dds_header(entry)
    if len(header) < 0x80 or header[:4] != DDS_MAGIC:
        raise ValueError("Partial DDS header is missing or invalid.")
    (
        _header_size,
        _flags,
        height,
        width,
        _pitch_or_linear_size,
        depth,
        mip_map_count,
        *reserved1_and_rest,
    ) = struct.unpack_from("<IIIIIII11I", header, 4)
    reserved1 = reserved1_and_rest[:11]
    pf_flags = struct.unpack_from("<I", header, 80)[0]
    ddspf_four_cc = header[84:88]
    rgb_bit_count = struct.unpack_from("<I", header, 88)[0]
    caps2 = struct.unpack_from("<I", header, 112)[0]
    is_dx10 = ddspf_four_cc == b"DX10"
    header_size = 0x94 if is_dx10 else 0x80
    dxgi_format = struct.unpack_from("<I", header, 0x80)[0] if is_dx10 and len(header) >= 0x94 else 0
    dx10_array_size = struct.unpack_from("<I", header, 0x8C)[0] if is_dx10 and len(header) >= 0x94 else 1

    multi_chunk_supported_0 = dx10_array_size < 2 if is_dx10 else True
    multi_chunk_supported_1 = mip_map_count > 5 and (caps2 == 0 and depth < 2)
    use_single_chunk = not multi_chunk_supported_0 or not multi_chunk_supported_1

    if use_single_chunk:
        compressed_block_sizes = [reserved1[0]]
        decompressed_block_sizes = [reserved1[1]]
    else:
        compressed_block_sizes = list(reserved1[:4])
        decompressed_block_sizes: List[int] = []
        current_width = max(1, width)
        current_height = max(1, height)
        for _ in range(min(4, max(1, mip_map_count))):
            decompressed_block_sizes.append(
                _dds_surface_size(
                    current_width,
                    current_height,
                    dxgi_format,
                    ddspf_four_cc,
                    pf_flags=pf_flags,
                    rgb_bit_count=rgb_bit_count,
                    pitch_or_linear_size=_pitch_or_linear_size,
                    mip_level=len(decompressed_block_sizes),
                )
            )
            current_width = max(1, current_width >> 1)
            current_height = max(1, current_height >> 1)

    current_data_offset = header_size
    output_data = bytearray(header[:header_size])
    for compressed_size, decompressed_size in zip(compressed_block_sizes, decompressed_block_sizes):
        if compressed_size <= 0 or decompressed_size <= 0:
            continue
        if compressed_size == decompressed_size:
            block = data[current_data_offset : current_data_offset + decompressed_size]
            if len(block) != decompressed_size:
                raise ValueError("Partial DDS block is truncated.")
            output_data.extend(block)
            current_data_offset += decompressed_size
            continue
        if lz4_block is None:
            raise ValueError("This entry uses Partial DDS reconstruction, but the lz4 Python package is not installed.")
        compressed_data = data[current_data_offset : current_data_offset + compressed_size]
        if len(compressed_data) != compressed_size:
            raise ValueError("Partial DDS block is truncated.")
        output_data.extend(lz4_block.decompress(compressed_data, uncompressed_size=decompressed_size))
        current_data_offset += compressed_size
    if current_data_offset < len(data):
        output_data.extend(data[current_data_offset:])
    return bytes(output_data)


def sanitize_archive_entry_output_path(entry: ArchiveEntry, output_root: Path) -> Path:
    pure_path = PurePosixPath(entry.path.replace("\\", "/"))
    safe_parts = [part for part in pure_path.parts if part not in {"", ".", ".."}]
    if not safe_parts:
        raise ValueError(f"Archive entry has an invalid path: {entry.path}")
    package_root = entry.pamt_path.parent.name.strip() or "package"
    return output_root.joinpath(package_root, *safe_parts)


def find_available_output_path(target_path: Path, reserved_paths: Optional[set[str]] = None) -> Path:
    reserved = reserved_paths or set()
    if str(target_path).lower() not in reserved and not target_path.exists():
        return target_path

    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        lowered = str(candidate).lower()
        if lowered not in reserved and not candidate.exists():
            return candidate
        counter += 1


def _read_archive_entry_raw_data_from_handle(
    handle: BinaryIO,
    entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> bytes:
    raise_if_cancelled(stop_event)
    read_size = entry.comp_size if entry.compressed else entry.orig_size
    handle.seek(entry.offset)
    data = handle.read(read_size)
    raise_if_cancelled(stop_event)
    return data


def read_archive_entry_raw_data(
    entry: ArchiveEntry,
    stop_event: Optional[threading.Event] = None,
) -> bytes:
    raise_if_cancelled(stop_event)
    if not entry.paz_file.exists():
        raise ValueError(f"Missing PAZ file: {entry.paz_file}")

    with entry.paz_file.open("rb") as handle:
        return _read_archive_entry_raw_data_from_handle(handle, entry, stop_event=stop_event)


def maybe_reconstruct_sparse_dds(entry: ArchiveEntry, data: bytes) -> Optional[Tuple[bytes, str]]:
    if entry.extension != ".dds":
        return None
    if not data.startswith(DDS_MAGIC):
        return None
    if len(data) >= entry.orig_size:
        return None
    padded = data + (b"\x00" * (entry.orig_size - len(data)))
    return padded, "SparseDDS"


def _maybe_decompress_partial_par_container(
    entry: ArchiveEntry,
    data: bytes,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Tuple[bytes, str]]:
    if lz4_block is None:
        return None
    if entry.compression_type != 1 or len(data) < 0x50 or not data.startswith(b"PAR "):
        return None

    slots: List[Tuple[int, int, int]] = []
    file_offset = 0x50
    rebuilt_size = 0x50
    saw_compressed_section = False

    for slot in range(8):
        raise_if_cancelled(stop_event)
        slot_offset = 0x10 + slot * 8
        comp_size = struct.unpack_from("<I", data, slot_offset)[0]
        decomp_size = struct.unpack_from("<I", data, slot_offset + 4)[0]
        if decomp_size <= 0:
            continue

        chunk_size = comp_size if comp_size > 0 else decomp_size
        if chunk_size <= 0:
            return None
        if decomp_size > entry.orig_size or rebuilt_size + decomp_size > entry.orig_size:
            return None
        if file_offset + chunk_size > len(data):
            return None

        slots.append((comp_size, decomp_size, file_offset))
        file_offset += chunk_size
        rebuilt_size += decomp_size
        if comp_size > 0:
            saw_compressed_section = True

    if not saw_compressed_section:
        return None
    if file_offset != len(data) or rebuilt_size != entry.orig_size:
        return None

    rebuilt = bytearray(data[:0x50])
    for comp_size, decomp_size, chunk_offset in slots:
        raise_if_cancelled(stop_event)
        chunk_size = comp_size if comp_size > 0 else decomp_size
        chunk = data[chunk_offset : chunk_offset + chunk_size]
        if comp_size > 0:
            try:
                chunk = lz4_block.decompress(chunk, uncompressed_size=decomp_size)
            except Exception:
                return None
            if len(chunk) != decomp_size:
                return None
        rebuilt.extend(chunk)

    if len(rebuilt) != entry.orig_size:
        return None

    # Preserve section sizes but clear the stored compressed lengths so the
    # rebuilt payload behaves like a normal decompressed PAR for downstream parsers.
    for slot in range(8):
        struct.pack_into("<I", rebuilt, 0x10 + slot * 8, 0)

    return bytes(rebuilt), "PartialPAR"


def _decode_archive_entry_data(
    entry: ArchiveEntry,
    data: bytes,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[bytes, bool, str]:
    decompressed = False
    note = ""
    if entry.encrypted:
        raise_if_cancelled(stop_event)
        data, decrypt_note = try_decrypt_archive_entry_data(entry, data)
        if decrypt_note:
            note = decrypt_note
        raise_if_cancelled(stop_event)
    if entry.compressed:
        if entry.compression_type == 1:
            partial_par = _maybe_decompress_partial_par_container(
                entry,
                data,
                stop_event=stop_event,
            )
            if partial_par is not None:
                data, partial_note = partial_par
                decompressed = True
                note = ",".join(part for part in [note, partial_note] if part)
            elif entry.extension == ".dds":
                raise_if_cancelled(stop_event)
                data = reconstruct_partial_dds(entry, data)
                decompressed = True
                note = ",".join(part for part in [note, "PartialDDS"] if part)
            else:
                note = ",".join(
                    part
                    for part in [note, "PartialRaw"]
                    if part
                )
        elif entry.compression_type == 2:
            if lz4_block is None:
                raise ValueError("This entry uses LZ4 compression, but the lz4 Python package is not installed.")
            raise_if_cancelled(stop_event)
            data = lz4_block.decompress(data, uncompressed_size=entry.orig_size)
            decompressed = True
            note = ",".join(part for part in [note, "LZ4"] if part)
        else:
            reconstructed = maybe_reconstruct_sparse_dds(entry, data)
            if reconstructed is not None:
                data, sparse_note = reconstructed
                note = ",".join(part for part in [note, sparse_note] if part)
            else:
                raise ValueError(f"Unsupported archive compression type {entry.compression_type} for {entry.path}")
        raise_if_cancelled(stop_event)

    return data, decompressed, note


def read_archive_entry_data(
    entry: ArchiveEntry,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[bytes, bool, str]:
    data = read_archive_entry_raw_data(entry, stop_event=stop_event)
    return _decode_archive_entry_data(entry, data, stop_event=stop_event)


def _read_archive_entry_data_from_handle(
    handle: BinaryIO,
    entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[bytes, bool, str]:
    data = _read_archive_entry_raw_data_from_handle(handle, entry, stop_event=stop_event)
    return _decode_archive_entry_data(entry, data, stop_event=stop_event)


def extract_archive_entry(
    entry: ArchiveEntry,
    output_root: Path,
) -> Tuple[Path, bool, str]:
    data, decompressed, note = read_archive_entry_data(entry)
    out_path = output_root
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path, decompressed, note


def extract_archive_entries(
    entries: Sequence[ArchiveEntry],
    output_root: Path,
    *,
    collision_mode: str = "overwrite",
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, int]:
    output_root.mkdir(parents=True, exist_ok=True)
    total = len(entries)
    extracted = 0
    decompressed = 0
    failed = 0
    duplicate_targets: Dict[str, int] = defaultdict(int)
    renamed = 0
    used_targets: set[str] = set()
    last_progress_emit_at = 0.0
    progress_interval = max(total // 200, 1) if total > 0 else 1

    def emit_progress(current: int, detail: str, *, force: bool = False) -> None:
        nonlocal last_progress_emit_at
        if on_progress is None:
            return
        current = min(max(int(current), 0), total)
        now = time.monotonic()
        if (
            force
            or current == 0
            or current >= total
            or current % progress_interval == 0
            or now - last_progress_emit_at >= 0.25
        ):
            last_progress_emit_at = now
            on_progress(current, total, detail)

    emit_progress(0, f"Preparing to extract {total:,} archive file(s)...", force=True)
    for entry in entries:
        try:
            target_path = sanitize_archive_entry_output_path(entry, output_root)
            duplicate_targets[str(target_path).lower()] += 1
        except Exception:
            continue

    duplicate_count = sum(1 for count in duplicate_targets.values() if count > 1)
    if duplicate_count and on_log:
        on_log(
            f"Warning: {duplicate_count} extracted path(s) are duplicated across selected archive entries. "
            "Later entries will overwrite earlier extracted files."
        )
    if total:
        emit_progress(0, f"Extracting 0 / {total:,} archive file(s)...", force=True)

    for index, entry in enumerate(entries, start=1):
        raise_if_cancelled(stop_event)
        try:
            target_path = sanitize_archive_entry_output_path(entry, output_root)
            if collision_mode == "rename":
                resolved_path = find_available_output_path(target_path, used_targets)
                if resolved_path != target_path:
                    renamed += 1
            else:
                resolved_path = target_path
            used_targets.add(str(resolved_path).lower())
            out_path, was_decompressed, note = extract_archive_entry(entry, resolved_path)
            extracted += 1
            if was_decompressed:
                decompressed += 1
            if on_log:
                flags = []
                if note and note not in flags:
                    flags.append(note)
                elif was_decompressed:
                    flags.append("Decompressed")
                if collision_mode == "rename" and out_path != target_path:
                    flags.append("Renamed")
                extra = f" [{' '.join(flags)}]" if flags else ""
                on_log(f"[{index}/{total}] EXTRACT {entry.path}{extra} -> {out_path}")
            emit_progress(index, f"Extracted {index:,} / {total:,}: {entry.path}")
        except Exception as exc:
            failed += 1
            if on_log:
                on_log(f"[{index}/{total}] FAIL {entry.path} -> {exc}")
            emit_progress(index, f"Extracted {index:,} / {total:,} with {failed:,} failure(s): {entry.path}")

    emit_progress(total, f"Archive extraction complete: {extracted:,} extracted, {failed:,} failed.", force=True)
    return {
        "total": total,
        "extracted": extracted,
        "decompressed": decompressed,
        "renamed": renamed,
        "failed": failed,
    }


def directory_has_contents(path: Path) -> bool:
    try:
        next(path.iterdir())
        return True
    except StopIteration:
        return False


def _background_delete_directory(path: Path) -> None:
    if not path.exists():
        return
    if os.name == "nt":
        subprocess.Popen(
            ["cmd.exe", "/d", "/c", "rmdir", "/s", "/q", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **hidden_subprocess_kwargs(),
        )
        return
    shutil.rmtree(path, ignore_errors=True)


def clear_directory_contents(path: Path) -> None:
    resolved = path.resolve()
    if resolved == Path(resolved.anchor):
        raise ValueError(f"Refusing to clear root directory: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    children = list(resolved.iterdir())
    if not children:
        return

    trash_root = Path(
        tempfile.mkdtemp(
            prefix=f"__ctf_pending_delete_{resolved.name}_",
            dir=str(resolved.parent),
        )
    )

    try:
        for child in children:
            target = trash_root / child.name
            suffix = 1
            while target.exists():
                target = trash_root / f"{child.name}.{suffix}"
                suffix += 1
            try:
                child.replace(target)
            except OSError:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        _background_delete_directory(trash_root)
    except Exception:
        shutil.rmtree(trash_root, ignore_errors=True)
        raise


def count_existing_archive_targets(entries: Sequence[ArchiveEntry], output_root: Path) -> int:
    return sum(1 for entry in entries if sanitize_archive_entry_output_path(entry, output_root).exists())


def format_byte_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    units = ("KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        value /= 1024.0
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
    return f"{size} B"


def sanitize_cache_filename(name: str) -> str:
    sanitized = re.sub(r'[<>:"/\\\\|?*]+', "_", name).strip(" .")
    return sanitized or "preview.bin"


def build_archive_entry_metadata_summary(entry: ArchiveEntry) -> str:
    flags: List[str] = []
    if entry.compressed:
        flags.append(entry.compression_label)
    if entry.encrypted:
        flags.append("Encrypted")
    flags_text = f" | {' | '.join(flags)}" if flags else ""
    return (
        f"{entry.extension or 'no extension'} | {format_byte_size(entry.orig_size)}"
        f" | Stored {format_byte_size(entry.comp_size)}{flags_text}"
    )


def build_archive_entry_detail_text(entry: ArchiveEntry, extra_detail: str = "") -> str:
    lines = [
        f"Path: {entry.path}",
        f"Package: {entry.package_label}",
        f"PAMT: {entry.pamt_path}",
        f"PAZ: {entry.paz_file}",
        f"Offset: {entry.offset:,}",
        f"Original size: {entry.orig_size:,} bytes ({format_byte_size(entry.orig_size)})",
        f"Stored size: {entry.comp_size:,} bytes ({format_byte_size(entry.comp_size)})",
        f"Compression: {entry.compression_label}",
        f"Encrypted: {'Yes' if entry.encrypted else 'No'}",
    ]
    if extra_detail.strip():
        lines.extend(["", extra_detail.strip()])
    return "\n".join(lines)


def _decode_dds_fourcc(fourcc: bytes) -> str:
    if not fourcc:
        return "-"
    try:
        text = fourcc.decode("ascii", errors="strict")
    except Exception:
        text = ""
    if text and all(32 <= ord(ch) <= 126 for ch in text):
        return text
    return "0x" + fourcc.hex().upper()


def _decode_dds_resource_dimension(value: int) -> str:
    return {
        0: "Unknown",
        1: "Buffer",
        2: "Texture1D",
        3: "Texture2D",
        4: "Texture3D",
    }.get(int(value), f"Unknown ({value})")


def _decode_dds_alpha_mode(value: int) -> str:
    return {
        0: "Unknown",
        1: "Straight",
        2: "Premultiplied",
        3: "Opaque",
        4: "Custom",
    }.get(int(value), f"Unknown ({value})")


def _decode_flag_names(value: int, mapping: Sequence[Tuple[int, str]]) -> str:
    names = [label for mask, label in mapping if value & mask]
    return ", ".join(names) if names else "-"


def _format_u32_list(values: Sequence[int]) -> str:
    if not values:
        return "-"
    return ", ".join(f"0x{int(value):08X}" for value in values)


def _format_hex_dump(data: bytes) -> str:
    if not data:
        return "-"
    lines: List[str] = []
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        hex_part = " ".join(f"{byte:02X}" for byte in chunk)
        ascii_part = "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in chunk)
        lines.append(f"  {offset:04X}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _dds_resource_type_from_caps(caps2: int) -> str:
    if caps2 & 0x00000200:
        return "Cubemap"
    if caps2 & 0x00200000:
        return "Texture3D"
    return "Texture2D"


def build_dds_header_detail_text(
    dds_path: Path,
    dds_info: Optional[DdsInfo] = None,
    *,
    logical_path: str = "",
    sidecar_texts: Sequence[str] = (),
) -> str:
    resolved_info = dds_info if dds_info is not None else parse_dds(dds_path)
    with dds_path.open("rb") as handle:
        blob = handle.read(148)
    if len(blob) < 128 or blob[:4] != DDS_MAGIC:
        raise ValueError("Missing DDS header.")

    header_magic = blob[:4]
    header = blob[4:128]
    header_size = struct.unpack_from("<I", header, 0)[0]
    header_flags = struct.unpack_from("<I", header, 4)[0]
    pitch_or_linear_size = struct.unpack_from("<I", header, 16)[0]
    depth = struct.unpack_from("<I", header, 20)[0]
    reserved1 = list(struct.unpack_from("<11I", header, 28))
    pf_flags = struct.unpack_from("<I", header, 76)[0]
    fourcc = header[80:84]
    rgb_bit_count = struct.unpack_from("<I", header, 84)[0]
    r_mask = struct.unpack_from("<I", header, 88)[0]
    g_mask = struct.unpack_from("<I", header, 92)[0]
    b_mask = struct.unpack_from("<I", header, 96)[0]
    a_mask = struct.unpack_from("<I", header, 100)[0]
    caps = struct.unpack_from("<I", header, 104)[0]
    caps2 = struct.unpack_from("<I", header, 108)[0]
    caps3 = struct.unpack_from("<I", header, 112)[0]
    caps4 = struct.unpack_from("<I", header, 116)[0]
    semantic_path_value = str(logical_path or dds_path).strip() or str(dds_path)
    semantic = infer_texture_semantics(
        semantic_path_value,
        sidecar_texts=sidecar_texts,
        original_texconv_format=resolved_info.texconv_format,
        has_alpha=resolved_info.has_alpha,
    )
    texture_type_hint = str(getattr(semantic, "texture_type", "") or "").strip().lower() or classify_texture_type(semantic_path_value)
    semantic_subtype = str(getattr(semantic, "semantic_subtype", "") or "").strip().lower()
    semantic_confidence = int(getattr(semantic, "confidence", 0) or 0)
    semantic_evidence = list(getattr(semantic, "evidence", ()) or [])
    is_dx10 = fourcc == b"DX10" and len(blob) >= 148
    dxgi_format = struct.unpack_from("<I", blob, 128)[0] if is_dx10 else 0
    resource_dimension = struct.unpack_from("<I", blob, 132)[0] if is_dx10 else 0
    misc_flag = struct.unpack_from("<I", blob, 136)[0] if is_dx10 else 0
    array_size = struct.unpack_from("<I", blob, 140)[0] if is_dx10 else 1
    misc_flags2 = struct.unpack_from("<I", blob, 144)[0] if is_dx10 else 0
    resource_type = _decode_dds_resource_dimension(resource_dimension) if is_dx10 else _dds_resource_type_from_caps(caps2)
    expected_mips = max(1, int(math.floor(math.log2(max(1, resolved_info.width, resolved_info.height, depth or 1)))) + 1)
    block_bytes = _dds_bytes_per_block(dxgi_format, fourcc)
    cube_face_count = 1
    if is_dx10 and (misc_flag & 0x4):
        cube_face_count = 6
    elif caps2 & 0x00000200:
        cube_face_count = sum(
            1
            for mask in (0x00000400, 0x00000800, 0x00001000, 0x00002000, 0x00004000, 0x00008000)
            if caps2 & mask
        ) or 6
    surface_instance_count = max(1, array_size) * max(1, cube_face_count)
    top_level_surface_bytes_text = "-"
    total_surface_bytes_text = "-"
    try:
        cur_w = max(1, resolved_info.width)
        cur_h = max(1, resolved_info.height)
        top_level_surface_bytes = _dds_surface_size(
            cur_w,
            cur_h,
            dxgi_format,
            fourcc,
            pf_flags=pf_flags,
            rgb_bit_count=rgb_bit_count,
            pitch_or_linear_size=pitch_or_linear_size,
            mip_level=0,
        )
        total_surface_bytes = 0
        for mip_index in range(max(1, resolved_info.mip_count)):
            total_surface_bytes += _dds_surface_size(
                cur_w,
                cur_h,
                dxgi_format,
                fourcc,
                pf_flags=pf_flags,
                rgb_bit_count=rgb_bit_count,
                pitch_or_linear_size=pitch_or_linear_size,
                mip_level=mip_index,
            )
            cur_w = max(1, cur_w >> 1)
            cur_h = max(1, cur_h >> 1)
        top_level_surface_bytes *= surface_instance_count
        total_surface_bytes *= surface_instance_count
        top_level_surface_bytes_text = f"{top_level_surface_bytes:,}"
        total_surface_bytes_text = f"{total_surface_bytes:,}"
    except Exception:
        pass
    file_sha256 = _sha256_path(dds_path)
    header_bytes = blob[:148] if is_dx10 else blob[:128]
    ddsd_flags = _decode_flag_names(
        header_flags,
        (
            (0x00000001, "CAPS"),
            (0x00000002, "HEIGHT"),
            (0x00000004, "WIDTH"),
            (0x00000008, "PITCH"),
            (0x00001000, "PIXELFORMAT"),
            (0x00020000, "MIPMAPCOUNT"),
            (0x00080000, "LINEARSIZE"),
            (0x00800000, "DEPTH"),
        ),
    )
    pixel_flag_names = _decode_flag_names(
        pf_flags,
        (
            (DDPF_ALPHAPIXELS, "ALPHAPIXELS"),
            (DDPF_ALPHA, "ALPHA"),
            (DDPF_FOURCC, "FOURCC"),
            (DDPF_RGB, "RGB"),
            (DDPF_LUMINANCE, "LUMINANCE"),
        ),
    )
    caps_names = _decode_flag_names(
        caps,
        (
            (0x00000008, "COMPLEX"),
            (0x00001000, "TEXTURE"),
            (0x00400000, "MIPMAP"),
        ),
    )
    caps2_names = _decode_flag_names(
        caps2,
        (
            (0x00000200, "CUBEMAP"),
            (0x00000400, "CUBEMAP_POSITIVEX"),
            (0x00000800, "CUBEMAP_NEGATIVEX"),
            (0x00001000, "CUBEMAP_POSITIVEY"),
            (0x00002000, "CUBEMAP_NEGATIVEY"),
            (0x00004000, "CUBEMAP_POSITIVEZ"),
            (0x00008000, "CUBEMAP_NEGATIVEZ"),
            (0x00200000, "VOLUME"),
        ),
    )
    crimson_info = inspect_crimson_dds(dds_path, vpath=logical_path)
    crimson_findings = [
        f"  - {finding.severity.upper()} {finding.code}: {finding.message}"
        for finding in crimson_info.findings
        if finding.code not in {"effective_last4"}
    ]
    crimson_last4_text = f"0x{crimson_info.effective_last4:04X}" if crimson_info.effective_last4 is not None else "-"
    crimson_last4_header_text = (
        f"0x{crimson_info.crimson_last4_header:04X}" if crimson_info.crimson_last4_header is not None else "-"
    )
    crimson_path_class_text = (
        f"0x{crimson_info.last4_path_class:04X}" if crimson_info.last4_path_class is not None else "-"
    )
    crimson_format_class_text = (
        f"0x{crimson_info.last4_format_derived:04X}" if crimson_info.last4_format_derived is not None else "-"
    )

    lines = [
        "DDS metadata:",
        f"- Format: {resolved_info.texconv_format}",
        f"- Dimensions: {resolved_info.width}x{resolved_info.height}",
        f"- Mip levels: {resolved_info.mip_count}",
        f"- Mip chain complete: {'Yes' if resolved_info.mip_count >= expected_mips else 'No'} ({resolved_info.mip_count}/{expected_mips} expected)",
        f"- Alpha: {'Yes' if resolved_info.has_alpha else 'No'}",
        f"- Colorspace intent: {resolved_info.colorspace_intent}",
        f"- Precision-sensitive: {'Yes' if resolved_info.precision_sensitive else 'No'}",
        f"- Texture type hint: {texture_type_hint}",
        f"- Semantic subtype: {semantic_subtype or '-'}",
        f"- Semantic confidence: {semantic_confidence}",
        f"- Semantic evidence: {semantic_evidence[0] if semantic_evidence else '-'}",
        f"- Resource type: {resource_type}",
        f"- DX10 header present: {'Yes' if is_dx10 else 'No'}",
        f"- DDS magic: {header_magic.decode('ascii', errors='replace')!r}",
        f"- Header size field: {header_size}",
        f"- Header flags: 0x{header_flags:08X}",
        f"- Header flag names: {ddsd_flags}",
        f"- Pitch / linear size: {pitch_or_linear_size:,}",
        f"- Depth: {depth or 1}",
        f"- Pixel format flags: 0x{pf_flags:08X}",
        f"- Pixel format names: {pixel_flag_names}",
        f"- FOURCC: {_decode_dds_fourcc(fourcc)}",
        f"- RGB bit count: {rgb_bit_count}",
        f"- Channel masks: R=0x{r_mask:08X} G=0x{g_mask:08X} B=0x{b_mask:08X} A=0x{a_mask:08X}",
        f"- Caps: 0x{caps:08X}",
        f"- Caps names: {caps_names}",
        f"- Caps2: 0x{caps2:08X}",
        f"- Caps2 names: {caps2_names}",
        f"- Caps3: 0x{caps3:08X}",
        f"- Caps4: 0x{caps4:08X}",
        f"- Block compression: {f'{block_bytes} bytes per 4x4 block' if block_bytes is not None else 'Uncompressed / direct pixel layout'}",
        f"- Surface instances: {surface_instance_count}",
        f"- Estimated top-level surface bytes: {top_level_surface_bytes_text}",
        f"- Estimated total surface bytes across listed mips: {total_surface_bytes_text}",
        f"- Resolved DDS file size: {dds_path.stat().st_size:,} bytes",
        f"- SHA-256: {file_sha256}",
        f"- Reserved1 values: {_format_u32_list(reserved1)}",
        "- Crimson DDS:",
        f"  - Effective last4: {crimson_last4_text}",
        f"  - Header last4: {crimson_last4_header_text}",
        f"  - Path-class last4: {crimson_path_class_text}",
        f"  - Format-derived last4: {crimson_format_class_text}",
        f"  - Requires PATHC/manifest registration: {'Yes' if crimson_info.requires_pathc else 'No'}",
        f"  - Findings: {len(crimson_findings):,}",
    ]
    if crimson_findings:
        lines.extend(crimson_findings)

    if is_dx10:
        lines.extend(
            [
                "- DX10 header:",
                f"  - DXGI format id: {dxgi_format}",
                f"  - Resource dimension: {_decode_dds_resource_dimension(resource_dimension)}",
                f"  - Array size: {array_size}",
                f"  - Misc flag: 0x{misc_flag:08X}",
                f"  - Misc flags2: 0x{misc_flags2:08X}",
                f"  - Alpha mode: {_decode_dds_alpha_mode(misc_flags2 & 0x7)}",
                f"  - Texture cube flag: {'Yes' if (misc_flag & 0x4) else 'No'}",
            ]
        )
    lines.extend(
        [
            "- Header hex dump:",
            _format_hex_dump(header_bytes),
        ]
    )
    return "\n".join(lines)


def ensure_archive_preview_source(
    entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Path, str]:
    try:
        pamt_stat = entry.pamt_path.stat()
        pamt_stamp = f"{pamt_stat.st_size}:{pamt_stat.st_mtime_ns}"
    except OSError:
        pamt_stamp = "missing"
    try:
        paz_stat = entry.paz_file.stat()
        paz_stamp = f"{paz_stat.st_size}:{paz_stat.st_mtime_ns}"
    except OSError:
        paz_stamp = "missing"
    pathc_stamp = ""
    if entry.extension == ".dds" and entry.compression_type == 1:
        try:
            pathc_path = resolve_archive_pathc_path(entry)
            pathc_stat = pathc_path.stat()
            pathc_stamp = f"|{pathc_path.resolve()}|{pathc_stat.st_size}:{pathc_stat.st_mtime_ns}"
        except OSError:
            pathc_stamp = "|missing_pathc"

    cache_key = hashlib.sha256(
        (
            f"{entry.path}|{entry.pamt_path.resolve()}|{pamt_stamp}|{entry.paz_file.resolve()}|{paz_stamp}|"
            f"{entry.offset}|{entry.comp_size}|{entry.orig_size}|{entry.flags}{pathc_stamp}"
        ).encode("utf-8")
    ).hexdigest()
    suffix = Path(entry.path).suffix or ".bin"
    filename = sanitize_cache_filename(f"{Path(entry.path).stem}{suffix}")
    cache_dir = Path(tempfile.gettempdir()) / APP_NAME / "archive_preview_cache" / cache_key
    target_path = cache_dir / filename
    if target_path.exists() and target_path.stat().st_size > 0:
        note_path = cache_dir / ".note"
        note = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
        return target_path, note

    cache_dir.mkdir(parents=True, exist_ok=True)
    data, _decompressed, note = read_archive_entry_data(entry, stop_event=stop_event)
    target_path.write_bytes(data)
    if note:
        (cache_dir / ".note").write_text(note, encoding="utf-8")
    return target_path, note


def _normalize_model_texture_reference(value: str) -> str:
    raw_text = str(value or "").replace("\\", "/").strip().lower()
    if not raw_text or raw_text == ".":
        return ""
    normalized = PurePosixPath(raw_text).as_posix().strip().lower()
    if normalized == ".":
        return ""
    return normalized


_ARCHIVE_TEXTURE_FAMILY_STOP_TOKENS = {
    "actor",
    "animation",
    "armor",
    "base",
    "bin",
    "character",
    "color",
    "common",
    "dds",
    "diff",
    "diffuse",
    "disp",
    "game",
    "height",
    "hkx",
    "material",
    "mesh",
    "meshphysics",
    "model",
    "modelproperty",
    "normal",
    "object",
    "overlay",
    "pac",
    "pamlod",
    "paz",
    "pc",
    "phm",
    "phw",
    "ptm",
    "rough",
    "sp",
    "texture",
    "textures",
    "wrinkle",
    "xml",
}


def _archive_reference_family_tokens(value: str) -> set[str]:
    normalized = _normalize_model_texture_reference(value)
    if not normalized:
        return set()
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", normalized):
        token = token.strip().lower()
        if len(token) < 3:
            continue
        if token in _ARCHIVE_TEXTURE_FAMILY_STOP_TOKENS:
            continue
        if token.isdigit() or re.fullmatch(r"[a-z]{1,3}\d+", token):
            continue
        tokens.add(token)
    return tokens


def _archive_texture_family_mismatch_summary(
    source_path: str,
    texture_paths: Sequence[str],
    *,
    sidecar_paths: Sequence[str] = (),
) -> str:
    source_tokens = _archive_reference_family_tokens(source_path)
    texture_tokens: set[str] = set()
    for texture_path in texture_paths:
        texture_tokens.update(_archive_reference_family_tokens(texture_path))
    if not source_tokens or not texture_tokens or source_tokens & texture_tokens:
        return ""
    source_display = ", ".join(sorted(source_tokens)[:4])
    texture_display = ", ".join(sorted(texture_tokens)[:5])
    sidecar_display = ", ".join(str(path or "").strip() for path in sidecar_paths[:2] if str(path or "").strip())
    sidecar_note = f" from {sidecar_display}" if sidecar_display else ""
    return (
        "Cross-family material notice: the exact companion sidecar"
        f"{sidecar_note} points at texture family tokens [{texture_display}], while the selected model path looks like "
        f"[{source_display}]. This can be legitimate material reuse, but it is not proof of item identity."
    )


def _archive_texture_family_mismatch_reason(source_entry: ArchiveEntry, texture_entry: Optional[ArchiveEntry]) -> str:
    if not isinstance(texture_entry, ArchiveEntry):
        return ""
    notice = _archive_texture_family_mismatch_summary(source_entry.path, (texture_entry.path,))
    if not notice:
        return ""
    return "cross-family texture name; exact sidecar binding may be legitimate material reuse"


def _normalize_model_submesh_reference(value: str) -> str:
    raw_text = str(value or "").replace("\\", "/").strip().lower()
    if not raw_text:
        return ""
    basename = PurePosixPath(raw_text).name or raw_text
    normalized = re.sub(r"[^a-z0-9]+", "", basename)
    if normalized:
        return normalized
    return re.sub(r"[^a-z0-9]+", "", raw_text)


def _is_anonymous_model_submesh_reference_key(value: str) -> bool:
    normalized = _normalize_model_submesh_reference(value)
    if not normalized:
        return True
    generic_roots = (
        "default",
        "group",
        "mesh",
        "node",
        "object",
        "root",
        "scene",
        "sceneroot",
        "submesh",
        "unknown",
    )
    if normalized in generic_roots:
        return True
    return any(re.fullmatch(fr"{root}\d*", normalized) for root in generic_roots)


def extract_binary_dds_references(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_strings: int = 96,
) -> List[str]:
    references: List[str] = []
    seen: set[str] = set()
    string_candidates = extract_binary_strings(
        data,
        sample_limit=sample_limit,
        max_strings=max(max_strings * 2, 48),
    )
    for text in string_candidates:
        for match in _TEXT_DDS_REFERENCE_RE.finditer(text):
            raw_text = str(match.group(0) or "").strip().strip("\x00")
            if not raw_text or not any(char.isalpha() for char in raw_text):
                continue
            normalized = _normalize_model_texture_reference(raw_text)
            if not normalized or not normalized.endswith(".dds") or normalized in seen:
                continue
            seen.add(normalized)
            references.append(raw_text.replace("\\", "/"))
            if len(references) >= max_strings:
                return references
    return references


def _humanize_model_texture_hint(semantic_hint: str) -> str:
    raw_text = str(semantic_hint or "").strip().lstrip("_")
    if not raw_text:
        return ""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw_text)
    spaced = re.sub(r"[_\s]+", " ", spaced).strip()
    if not spaced:
        return ""
    return " ".join(part[:1].upper() + part[1:] for part in spaced.split())


def _model_texture_hint_priority(semantic_hint: str) -> Optional[Tuple[int, int]]:
    normalized = str(semantic_hint or "").strip().lower().replace("_", "")
    if not normalized:
        return None

    technical_tokens = (
        "normal",
        "height",
        "displacement",
        "materialtexture",
        "materialmask",
        "detailmask",
        "masktexture",
        "roughness",
        "metallic",
        "occlusion",
        "opacity",
        "screenspacedisplacement",
        "specular",
    )
    if any(token in normalized for token in technical_tokens):
        return (0, 0)

    channel_priority = 0
    for suffix, priority in (
        ("texturer", 3),
        ("maskr", 3),
        ("textureg", 2),
        ("maskg", 2),
        ("textureb", 1),
        ("maskb", 1),
        ("texturea", 0),
        ("maska", 0),
    ):
        if normalized.endswith(suffix):
            channel_priority = priority
            break

    if any(token in normalized for token in ("grimediffusetexture", "grimediffusemask", "grimecolortexture")):
        return (3, channel_priority)
    if any(token in normalized for token in ("detaildiffusetexture", "detaildiffusemask", "detailcolortexture")):
        return (5, 1 + channel_priority)
    if "diffusetexture" in normalized:
        return (6, 4 + channel_priority)
    if "diffusemask" in normalized:
        return (6, 1 + channel_priority)
    if "overlaycolor" in normalized:
        return (5, 2)
    if any(
        token in normalized
        for token in (
            "colortexture",
            "diffuse",
            "albedo",
            "basecolor",
            "emissive",
            "tintcolor",
        )
    ):
        return (6, 3)
    if "color" in normalized or "overlay" in normalized or "tint" in normalized:
        return (6, 2)
    return None


def _normalize_model_visible_texture_mode(visible_texture_mode: str) -> str:
    normalized_mode = str(visible_texture_mode or "").strip().lower()
    if normalized_mode not in MODEL_PREVIEW_VISIBLE_TEXTURE_MODES:
        return ModelPreviewRenderSettings().visible_texture_mode
    return normalized_mode


def _classify_model_sidecar_visible_binding(semantic_hint: str, texture_path: str) -> str:
    normalized_hint = str(semantic_hint or "").strip().lower().replace("_", "")
    texture_basename = PurePosixPath(str(texture_path or "").replace("\\", "/")).stem.lower()
    if _is_placeholder_model_texture(texture_path):
        return "technical"

    technical_tokens = (
        "normal",
        "height",
        "displacement",
        "material",
        "roughness",
        "metallic",
        "ambientocclusion",
        "occlusion",
        "opacity",
        "specular",
        "orm",
        "rma",
        "mra",
        "arm",
        "ao",
    )
    technical_suffixes = (
        "_n",
        "_normal",
        "_normalmap",
        "_disp",
        "_displacement",
        "_height",
        "_hgt",
        "_dmap",
        "_parallax",
        "_pom",
        "_ssdm",
        "_mask",
        "_ma",
        "_mg",
        "_sp",
        "_orm",
        "_rma",
        "_mra",
        "_arm",
        "_ao",
        "_spec",
        "_specular",
        "_roughness",
        "_metallic",
    )
    if any(token in normalized_hint for token in technical_tokens):
        return "technical"
    if normalized_hint in {"colorblendingmasktexture", "detailmasktexture"}:
        return "technical"
    if "mask" in normalized_hint and not any(
        token in normalized_hint for token in ("diffuse", "albedo", "color", "colour", "overlay", "emissive")
    ):
        return "technical"
    if texture_basename.endswith(technical_suffixes):
        return "technical"

    layer_tokens = (
        "grime",
        "detail",
        "layer",
        "blend",
        "decal",
    )
    if any(token in normalized_hint for token in layer_tokens):
        return "layer_visible"

    primary_tokens = (
        "basecolor",
        "basecolour",
        "albedo",
        "diffuse",
        "colortexture",
        "overlaycolor",
        "base",
    )
    if any(token in normalized_hint for token in primary_tokens):
        return "primary_visible"

    generic_tokens = (
        "color",
        "colour",
        "overlay",
        "tint",
        "emissive",
    )
    if any(token in normalized_hint for token in generic_tokens):
        return "visible_generic"

    if not normalized_hint:
        return "visible_generic"
    return "visible_generic"


def _allowed_model_sidecar_visible_classes(visible_texture_mode: str) -> Tuple[str, ...]:
    normalized_mode = _normalize_model_visible_texture_mode(visible_texture_mode)
    if normalized_mode == "mesh_base_first":
        return ("primary_visible",)
    if normalized_mode == "layer_aware_visible":
        return ("primary_visible", "visible_generic", "layer_visible")
    return ("primary_visible", "visible_generic", "layer_visible")


def _model_sidecar_visible_class_priority(binding_class: str) -> int:
    if binding_class == "primary_visible":
        return 3
    if binding_class == "layer_visible":
        return 2
    if binding_class == "visible_generic":
        return 1
    return 0


def _model_texture_slot_hint_priority(preview_slot: str, semantic_hint: str) -> Optional[Tuple[int, int]]:
    normalized_slot = str(preview_slot or "").strip().lower()
    normalized_hint = str(semantic_hint or "").strip().lower().replace("_", "")
    if not normalized_slot or not normalized_hint:
        return None

    if normalized_slot == "base":
        if "basecolor" in normalized_hint:
            return (9, 4)
        if any(token in normalized_hint for token in ("grimediffuse", "detaildiffuse", "detailalbedo", "detailcolor")):
            return (5, 1)
        if any(
            token in normalized_hint
            for token in (
                "overlaycolor",
                "colortexture",
                "diffuse",
                "albedo",
                "emissive",
            )
        ):
            return (8, 3)
        if "tintcolor" in normalized_hint:
            return (6, 1)
        if "color" in normalized_hint or "overlay" in normalized_hint or "tint" in normalized_hint:
            return (5, 0)
        return None

    if normalized_slot == "normal":
        if normalized_hint in {"normaltexture", "basenormaltexture"}:
            return (9, 4)
        if "detailnormal" in normalized_hint or "grimenormal" in normalized_hint:
            return (5, 1)
        if normalized_hint.startswith("normal") or normalized_hint.endswith("normaltexture"):
            return (8, 3)
        if "normal" in normalized_hint:
            return (6, 0)
        return None

    if normalized_slot == "material":
        if normalized_hint in {"materialtexture", "basematerialtexture"}:
            return (9, 4)
        if "detailmaterial" in normalized_hint or "grimematerial" in normalized_hint:
            return (5, 1)
        if normalized_hint.startswith("material") or normalized_hint.endswith("materialtexture"):
            return (8, 3)
        if any(token in normalized_hint for token in ("masktexture", "detailmask", "material", "roughness", "metallic", "occlusion")):
            return (6, 0)
        return None

    if normalized_slot == "height":
        if normalized_hint in {"heighttexture", "displacementtexture"}:
            return (9, 4)
        if "detailheight" in normalized_hint or "detaildisplacement" in normalized_hint:
            return (5, 1)
        if normalized_hint.startswith("height") or normalized_hint.endswith("heighttexture"):
            return (8, 3)
        if normalized_hint.startswith("displacement") or normalized_hint.endswith("displacementtexture"):
            return (8, 2)
        if any(token in normalized_hint for token in ("height", "displacement", "parallax", "pom", "ssdm", "bump")):
            return (6, 0)
        return None

    return None


def _score_model_sidecar_entry_candidate(source_entry: ArchiveEntry, candidate: ArchiveEntry) -> Tuple[int, int, int]:
    normalized_candidate = _normalize_model_texture_reference(candidate.path)
    source_path = _normalize_model_texture_reference(source_entry.path)
    source_root = PurePosixPath(source_path).parts[:1]
    candidate_root = PurePosixPath(normalized_candidate).parts[:1]
    score_value = 0
    if candidate.pamt_path == source_entry.pamt_path:
        score_value += 10
    if candidate.pamt_path.parent == source_entry.pamt_path.parent:
        score_value += 6
    if "/texture/" in normalized_candidate:
        score_value += 8
    if candidate_root and source_root and candidate_root == source_root:
        score_value += 4
    source_extension = str(source_entry.extension or "").strip().lower()
    candidate_extension = str(candidate.extension or "").strip().lower()
    candidate_basename = PurePosixPath(candidate.path.replace("\\", "/")).name.lower()
    if source_extension in {".pam", ".pamlod"} and normalized_candidate.endswith(".pami"):
        extension_priority = 2
    elif _is_material_sidecar_extension(candidate_extension, candidate_basename):
        extension_priority = 2
    elif normalized_candidate.endswith(".xml") or candidate_extension in _ARCHIVE_METADATA_XML_EXTENSIONS:
        extension_priority = 1
    else:
        extension_priority = 0
    return score_value, extension_priority, -len(candidate.path)


def _score_model_related_entry_candidate(source_entry: ArchiveEntry, candidate: ArchiveEntry) -> Tuple[int, int, int]:
    normalized_candidate = _normalize_model_texture_reference(candidate.path)
    source_path = _normalize_model_texture_reference(source_entry.path)
    source_root = PurePosixPath(source_path).parts[:1]
    candidate_root = PurePosixPath(normalized_candidate).parts[:1]
    score_value = 0
    if candidate.pamt_path == source_entry.pamt_path:
        score_value += 10
    if candidate.pamt_path.parent == source_entry.pamt_path.parent:
        score_value += 6
    if candidate_root and source_root and candidate_root == source_root:
        score_value += 4
    source_extension = str(source_entry.extension or "").strip().lower()
    candidate_extension = str(candidate.extension or "").strip().lower()
    extension_priority = 0
    if source_extension == ".pam":
        if candidate_extension == ".pamlod":
            extension_priority = 6
        elif candidate_extension in {".pami", ".pam_xml"}:
            extension_priority = 5
        elif candidate_extension in {".xml", ".pamlod_xml"}:
            extension_priority = 4
        elif candidate_extension == ".meshinfo":
            extension_priority = 3
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 2
    elif source_extension == ".pamlod":
        if candidate_extension == ".pam":
            extension_priority = 6
        elif candidate_extension in {".pami", ".pamlod_xml", ".pam_xml"}:
            extension_priority = 5
        elif candidate_extension == ".xml":
            extension_priority = 4
        elif candidate_extension == ".meshinfo":
            extension_priority = 3
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 2
    elif source_extension == ".pac":
        if candidate_extension == ".pab":
            extension_priority = 7
        elif candidate_extension == ".pac_xml":
            extension_priority = 6
        elif candidate_extension in {".xml", ".prefabdata_xml"}:
            extension_priority = 5
        elif candidate_extension == ".meshinfo":
            extension_priority = 4
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 3
        elif candidate_extension in {".prefab", ".pappt", ".pamhc"}:
            extension_priority = 3
    elif source_extension == ".prefab":
        if candidate_extension == ".pac":
            extension_priority = 7
        elif candidate_extension == ".pac_xml":
            extension_priority = 6
        elif candidate_extension in {".pab", ".meshinfo"}:
            extension_priority = 5
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 4
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 3
        elif candidate_extension == ".dds":
            extension_priority = 2
    elif source_extension in {".pappt", ".pamhc"}:
        if candidate_extension in {".pac", ".pam", ".pamlod"}:
            extension_priority = 7
        elif candidate_extension in {".prefab", ".prefabdata_xml", ".app_xml"}:
            extension_priority = 6
        elif candidate_extension in {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"}:
            extension_priority = 5
        elif candidate_extension in {".meshinfo", ".hkx", ".hkt"}:
            extension_priority = 4
        elif candidate_extension in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh"}:
            extension_priority = 3
    elif source_extension == ".meshinfo":
        if candidate_extension in {".pam", ".pamlod", ".pac"}:
            extension_priority = 7
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 6
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 5
        elif candidate_extension == ".pami":
            extension_priority = 4
    elif source_extension == ".pab":
        if candidate_extension == ".pac":
            extension_priority = 7
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 6
        elif candidate_extension == ".meshinfo":
            extension_priority = 5
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 4
    elif source_extension in {".paa", ".paa_metabin", ".motionblending", ".pae", ".paem", ".paseq", ".paschedule", ".paschedulepath", ".pastage", ".seqmt"}:
        if candidate_extension in {".hkx", ".hkt", ".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".paseq", ".paschedule", ".paschedulepath", ".pastage", ".seqmt"}:
            extension_priority = 6
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 5
    elif source_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
        source_stem_lower = PurePosixPath(source_entry.path.replace("\\", "/")).stem.lower()
        if source_stem_lower.endswith(".pac"):
            if candidate_extension == ".pac":
                extension_priority = 7
            elif candidate_extension == ".pab":
                extension_priority = 6
            elif candidate_extension == ".meshinfo":
                extension_priority = 5
            elif candidate_extension in {".hkx", ".hkt"}:
                extension_priority = 4
        elif source_stem_lower.endswith(".pam"):
            if candidate_extension == ".pam":
                extension_priority = 7
            elif candidate_extension == ".pamlod":
                extension_priority = 6
            elif candidate_extension == ".pami":
                extension_priority = 5
            elif candidate_extension == ".meshinfo":
                extension_priority = 4
            elif candidate_extension in {".hkx", ".hkt"}:
                extension_priority = 3
        elif source_stem_lower.endswith(".pamlod"):
            if candidate_extension == ".pamlod":
                extension_priority = 7
            elif candidate_extension == ".pam":
                extension_priority = 6
            elif candidate_extension == ".pami":
                extension_priority = 5
            elif candidate_extension == ".meshinfo":
                extension_priority = 4
            elif candidate_extension in {".hkx", ".hkt"}:
                extension_priority = 3
        elif source_stem_lower.endswith(".pab"):
            if candidate_extension == ".pab":
                extension_priority = 7
            elif candidate_extension == ".pac":
                extension_priority = 6
            elif candidate_extension in {".hkx", ".hkt"}:
                extension_priority = 5
            elif candidate_extension == ".meshinfo":
                extension_priority = 4
        elif candidate_extension in {".pam", ".pamlod", ".pac", ".pab", ".pami", ".meshinfo", ".hkx", ".hkt"}:
            extension_priority = 3
    elif source_extension == ".pami":
        if candidate_extension in {".pam", ".pamlod"}:
            extension_priority = 7
        elif candidate_extension == ".meshinfo":
            extension_priority = 6
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 5
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 4
    elif source_extension in {".hkx", ".hkt"}:
        if candidate_extension in {".pam", ".pamlod", ".pac"}:
            extension_priority = 7
        elif candidate_extension == ".pab":
            extension_priority = 6
        elif candidate_extension == ".meshinfo":
            extension_priority = 5
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 4
    elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS | {".meshinfo", ".hkx", ".hkt"}:
        extension_priority = 2
    return score_value, extension_priority, -len(candidate.path)


def _extend_archive_related_target_basenames(
    add_target: Callable[[str], None],
    *,
    stem: str,
    source_extension: str,
) -> None:
    if not stem:
        return
    add_target(f"{stem}.xml")
    add_target(f"{stem}.hkx")
    add_target(f"{stem}.hkt")
    add_target(f"{stem}.meshinfo")
    add_target(f"{stem}.app_xml")
    add_target(f"{stem}.app.xml")
    add_target(f"{stem}.prefab")
    add_target(f"{stem}.prefabdata.xml")
    add_target(f"{stem}.prefabdata_xml")
    add_target(f"{stem}.pappt")
    add_target(f"{stem}.pamhc")
    add_target(f"{stem}.sockets.xml")
    add_target(f"{stem}.paa")
    add_target(f"{stem}.paa_metabin")
    add_target(f"{stem}.pae")
    add_target(f"{stem}.paem")
    add_target(f"{stem}.motionblending")
    add_target(f"{stem}.paseq")
    add_target(f"{stem}.paschedule")
    add_target(f"{stem}.paschedulepath")
    add_target(f"{stem}.pastage")
    add_target(f"{stem}.seqmt")
    if source_extension in {".pam", ".pamlod"}:
        add_target(f"{stem}.pami")
        add_target(f"{stem}.pam_xml")
        add_target(f"{stem}.pamlod_xml")
    if source_extension == ".pam":
        add_target(f"{stem}.pamlod")
        if stem.endswith("_breakable"):
            add_target(f"{stem[:-10]}.pamlod")
    elif source_extension == ".pamlod":
        add_target(f"{stem}.pam")
    elif source_extension == ".pac":
        add_target(f"{stem}.pab")
        add_target(f"{stem}.pac_xml")
        add_target(f"{stem}.pac.xml")
        add_target(f"{stem}.pappt")
        add_target(f"{stem}.pamhc")
    elif source_extension == ".meshinfo":
        add_target(f"{stem}.pam")
        add_target(f"{stem}.pamlod")
        add_target(f"{stem}.pac")
        add_target(f"{stem}.pami")
    elif source_extension == ".pab":
        add_target(f"{stem}.pac")
    elif source_extension == ".pami":
        add_target(f"{stem}.pam")
        add_target(f"{stem}.pamlod")
    elif source_extension in {".pappt", ".pamhc"}:
        add_target(f"{stem}.pac")
        add_target(f"{stem}.pam")
        add_target(f"{stem}.pamlod")
        add_target(f"{stem}.pab")
        add_target(f"{stem}.hkx")
        add_target(f"{stem}.hkt")
        add_target(f"{stem}.meshinfo")
        add_target(f"{stem}.pac_xml")
        add_target(f"{stem}.pam_xml")
        add_target(f"{stem}.pamlod_xml")
        add_target(f"{stem}.pami")
        add_target(f"{stem}.prefab")
        add_target(f"{stem}.prefabdata.xml")
        add_target(f"{stem}.prefabdata_xml")
    elif source_extension in {".pac_xml", ".pam_xml", ".pamlod_xml", ".prefabdata_xml"}:
        if source_extension == ".pac_xml":
            add_target(f"{stem}.pac")
            add_target(f"{stem}.pab")
            add_target(f"{stem}.hkx")
            add_target(f"{stem}.hkt")
            add_target(f"{stem}.meshinfo")
            add_target(f"{stem}.app_xml")
            add_target(f"{stem}.app.xml")
            add_target(f"{stem}.prefabdata.xml")
            add_target(f"{stem}.prefabdata_xml")
        elif source_extension == ".pam_xml":
            add_target(f"{stem}.pam")
            add_target(f"{stem}.pamlod")
            add_target(f"{stem}.pami")
            add_target(f"{stem}.meshinfo")
            add_target(f"{stem}.hkx")
            add_target(f"{stem}.hkt")
        elif source_extension == ".pamlod_xml":
            add_target(f"{stem}.pamlod")
            add_target(f"{stem}.pam")
            add_target(f"{stem}.pami")
            add_target(f"{stem}.meshinfo")
            add_target(f"{stem}.hkx")
            add_target(f"{stem}.hkt")
    elif source_extension == ".seqmt":
        for related_extension in (
            ".dds",
            ".paa",
            ".paa_metabin",
            ".pae",
            ".paem",
            ".motionblending",
            ".hkx",
            ".hkt",
            ".paseq",
            ".paschedule",
            ".paschedulepath",
            ".pastage",
            ".seqmt",
        ):
            add_target(f"{stem}{related_extension}")
    elif source_extension in {".paa", ".paa_metabin", ".motionblending", ".pae", ".paem", ".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
        for related_extension in (".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".hkx", ".hkt", ".paseq", ".paschedule", ".paschedulepath", ".pastage", ".seqmt"):
            add_target(f"{stem}{related_extension}")
    elif source_extension in {".hkx", ".hkt"}:
        add_target(f"{stem}.pam")
        add_target(f"{stem}.pamlod")
        add_target(f"{stem}.pac")
        add_target(f"{stem}.pab")
        add_target(f"{stem}.pami")


def _collect_same_stem_related_target_basenames(source_entry: ArchiveEntry) -> set[str]:
    normalized_path = source_entry.path.replace("\\", "/").strip()
    basename = PurePosixPath(normalized_path).name.strip().lower()
    stem = PurePosixPath(normalized_path).stem.strip()
    source_extension = str(source_entry.extension or "").strip().lower()
    targets: set[str] = set()

    def add_target(raw_value: str) -> None:
        candidate = str(raw_value or "").strip().lower()
        if candidate:
            targets.add(candidate)

    if basename:
        add_target(f"{basename}.xml")
        add_target(f"{basename}.hkx")
        add_target(f"{basename}.hkt")
        add_target(f"{basename}.meshinfo")
    if stem:
        _extend_archive_related_target_basenames(
            add_target,
            stem=stem,
            source_extension=source_extension,
        )
        if source_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            nested_basename = stem.strip().lower()
            nested_extension = PurePosixPath(nested_basename).suffix.strip().lower()
            nested_stem = PurePosixPath(nested_basename).stem.strip()
            if nested_extension:
                add_target(nested_basename)
                _extend_archive_related_target_basenames(
                    add_target,
                    stem=nested_stem,
                    source_extension=nested_extension,
                )
    return targets


def _strip_archive_model_family_variant_suffix(stem: str) -> str:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ""
    while True:
        before = normalized
        for suffix in sorted(_ARCHIVE_MODEL_FAMILY_VARIANT_SUFFIXES, key=len, reverse=True):
            if normalized.endswith(suffix) and len(normalized) > len(suffix):
                normalized = normalized[: -len(suffix)]
                break
        if normalized != before:
            continue
        stripped = _ARCHIVE_NUMBERED_MODEL_FAMILY_VARIANT_RE.sub("", normalized).strip()
        if stripped and stripped != normalized:
            normalized = stripped
            continue
        stripped = re.sub(r"(?<=\d)[a-z]$", "", normalized).strip()
        if stripped and stripped != normalized:
            normalized = stripped
            continue
        return normalized or before


def _iter_archive_prefab_equipment_family_stems(stem: str) -> Tuple[str, ...]:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ()
    candidates: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = str(value or "").strip().lower()
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    add(normalized)
    add(_strip_archive_model_family_variant_suffix(normalized))
    for candidate in tuple(candidates):
        if "_set_" in candidate:
            add(candidate.replace("_set_", "_", 1))

    for candidate in tuple(candidates):
        match = _ARCHIVE_PREFAB_HELM_DESCRIPTOR_RE.match(candidate)
        if not match:
            continue
        rest = match.group("rest")
        for model_variant in ("00", "01"):
            add(f"{match.group('prefix')}ptm_{model_variant}_hel_{rest}")
    return tuple(candidates)


def _iter_archive_attachment_side_family_stems(stem: str) -> Tuple[str, ...]:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ()
    candidates: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = str(value or "").strip().lower()
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    add(normalized)
    base_stem = _strip_archive_model_family_variant_suffix(normalized)
    add(base_stem)
    for side_suffix in _ARCHIVE_ATTACHMENT_SIDE_SUFFIXES:
        if base_stem and not base_stem.endswith(side_suffix):
            add(f"{base_stem}{side_suffix}")
    return tuple(candidates)


def iter_archive_equipment_model_alias_stems(stem: str) -> Tuple[str, ...]:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ()
    candidates: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = str(value or "").strip().lower()
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    source_stems = [normalized, _strip_archive_model_family_variant_suffix(normalized)]
    for source_stem in source_stems:
        match = _ARCHIVE_PLATE_HELM_MODEL_RE.match(source_stem)
        if not match:
            continue
        rest = match.group("rest")
        descriptor_stem = f"{match.group('prefix')}phm_00_hel_{rest}"
        add(descriptor_stem)
        add(f"{descriptor_stem}_c")
        if rest.isdigit():
            set_descriptor_stem = f"{match.group('prefix')}phm_00_hel_set_{rest}"
            add(set_descriptor_stem)
            add(f"{set_descriptor_stem}_c")
    return tuple(candidates)


def iter_archive_character_equipment_root_alias_stems(stem: str) -> Tuple[str, ...]:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ()
    candidates: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = str(value or "").strip().lower()
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    for source_stem in (normalized, _strip_archive_model_family_variant_suffix(normalized)):
        match = _ARCHIVE_CHARACTER_EQUIPMENT_COMPONENT_RE.match(source_stem)
        if match:
            add(match.group("root"))
    return tuple(candidates)


def _collect_family_heuristic_target_basenames(source_entry: ArchiveEntry) -> set[str]:
    normalized_path = source_entry.path.replace("\\", "/").strip().lower()
    source_extension = str(source_entry.extension or "").strip().lower()
    if source_extension not in {
        ".pac",
        ".pam",
        ".pamlod",
        ".pab",
        ".hkx",
        ".hkt",
        ".meshinfo",
        ".seqmt",
        ".xml",
        ".pac_xml",
        ".pam_xml",
        ".pamlod_xml",
        ".app_xml",
        ".prefabdata_xml",
        ".prefab",
        ".pappt",
        ".pamhc",
    }:
        return set()
    targets: set[str] = set()
    for pab_basename in iter_pab_candidate_basenames(normalized_path):
        normalized_pab = str(pab_basename or "").strip().lower()
        if not normalized_pab:
            continue
        targets.add(normalized_pab)
        family_stem = PurePosixPath(normalized_pab).stem
        if not family_stem:
            continue
        for extension in (".pac", ".pab", ".hkx", ".hkt", ".meshinfo", ".seqmt", ".app_xml", ".app.xml", ".prefabdata.xml", ".pac_xml", ".prefabdata_xml", ".pappt", ".pamhc"):
            targets.add(f"{family_stem}{extension}")
    if source_extension in {".prefab", ".pappt", ".pamhc"}:
        source_stem = PurePosixPath(normalized_path).stem.strip().lower()
        for family_stem in _iter_archive_prefab_equipment_family_stems(source_stem):
            for extension in (
                ".pac",
                ".pab",
                ".hkx",
                ".hkt",
                ".meshinfo",
                ".seqmt",
                ".prefabdata.xml",
                ".pac_xml",
                ".prefabdata_xml",
                ".pappt",
                ".pamhc",
                ".sockets.xml",
            ):
                targets.add(f"{family_stem}{extension}")
            for texture_suffix in _ARCHIVE_TEXTURE_FAMILY_SUFFIXES:
                targets.add(f"{family_stem}{texture_suffix}.dds")
    elif source_extension in {
        ".pac",
        ".pam",
        ".pamlod",
        ".pab",
        ".hkx",
        ".hkt",
        ".meshinfo",
        ".xml",
        ".pac_xml",
        ".pam_xml",
        ".pamlod_xml",
        ".app_xml",
        ".prefabdata_xml",
    }:
        source_stem = PurePosixPath(normalized_path).stem.strip().lower()
        for family_stem in _iter_archive_attachment_side_family_stems(source_stem):
            for extension in _ARCHIVE_ATTACHMENT_SIDE_METADATA_EXTENSIONS:
                targets.add(f"{family_stem}{extension}")
    return targets


def _relation_group_for_kind(relation_kind: str) -> str:
    normalized_kind = str(relation_kind or "").strip().lower()
    if normalized_kind == "item_icon":
        return "Item Icons"
    if normalized_kind == RelationKind.TEXTURE.value:
        return "Textures"
    if normalized_kind == RelationKind.MATERIAL_SIDECAR.value:
        return "Material Sidecars"
    if normalized_kind in {RelationKind.MESH.value, RelationKind.LOD.value}:
        return "Mesh / Model"
    if normalized_kind == RelationKind.SKELETON.value:
        return "Skeleton / Rig"
    if normalized_kind == "physics":
        return "Physics / Collision"
    if normalized_kind == RelationKind.ANIMATION.value:
        return "Animation / Motion"
    return "Metadata / Other"


def _relation_kind_for_entry(candidate_entry: Optional[ArchiveEntry], reference_name: str = "") -> str:
    reference_path = str(getattr(candidate_entry, "path", "") or reference_name).replace("\\", "/")
    reference_path_lower = reference_path.lower()
    reference_basename = PurePosixPath(reference_path).name.lower()
    extension = str(getattr(candidate_entry, "extension", "") or PurePosixPath(reference_path).suffix).strip().lower()
    if _archive_path_is_probable_item_icon(reference_path):
        return "item_icon"
    if extension in {".dds", ".seqmt"}:
        return RelationKind.TEXTURE.value
    if _is_material_sidecar_extension(extension, reference_basename):
        return RelationKind.MATERIAL_SIDECAR.value
    if extension == ".xml":
        return RelationKind.METADATA.value
    if extension in {".app_xml", ".prefabdata_xml", ".pappt", ".pamhc"}:
        return RelationKind.METADATA.value
    if extension in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh"}:
        return RelationKind.SKELETON.value
    if extension in {".pac", ".pam"}:
        return RelationKind.MESH.value
    if extension == ".pamlod":
        return RelationKind.LOD.value
    if extension in {".hkx", ".hkt"}:
        if any(token in reference_path_lower for token in ("meshphysics", "havokphysics", "ragdoll", "physics")):
            return "physics"
        return RelationKind.ANIMATION.value
    if extension in {".motionblending", ".papr", ".paa", ".paa_metabin", ".pae", ".paem", ".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
        return RelationKind.ANIMATION.value
    return RelationKind.METADATA.value


def _build_archive_relation_metadata(
    source_entry: ArchiveEntry,
    *,
    reference_name: str = "",
    resolved_entry: Optional[ArchiveEntry] = None,
    authoritative: bool = False,
    authoritative_reason: str = "",
) -> Tuple[str, str, str, str]:
    relation_kind = _relation_kind_for_entry(resolved_entry, reference_name=reference_name)
    normalized_reference = _normalize_model_texture_reference(reference_name)
    normalized_source = _normalize_model_texture_reference(source_entry.path)
    normalized_resolved = _normalize_model_texture_reference(str(getattr(resolved_entry, "path", "") or ""))
    normalized_basename = PurePosixPath(
        str(getattr(resolved_entry, "path", "") or reference_name).replace("\\", "/")
    ).name.strip().lower()
    same_stem_targets = _collect_same_stem_related_target_basenames(source_entry)
    family_targets = _collect_family_heuristic_target_basenames(source_entry)
    if authoritative:
        confidence = RelationConfidence.AUTHORITATIVE.value
        reason = authoritative_reason or "Explicit path or sidecar binding"
    elif normalized_reference and normalized_resolved and normalized_reference == normalized_resolved:
        confidence = RelationConfidence.EXACT_PATH.value
        reason = "Exact archive path"
    elif (
        normalized_reference
        and normalized_resolved
        and normalized_reference.lstrip("/") == normalized_resolved.lstrip("/")
    ):
        confidence = RelationConfidence.PATH_NORMALIZED.value
        reason = "Path-normalized reference"
    elif (
        normalized_source
        and normalized_resolved
        and normalized_source.replace("/modelproperty/", "/model/") == normalized_resolved
    ):
        confidence = RelationConfidence.PATH_NORMALIZED.value
        reason = "Linked mesh via modelproperty -> model"
    elif (
        normalized_source
        and normalized_resolved
        and normalized_source.replace("/model/", "/modelproperty/") == normalized_resolved
    ):
        confidence = RelationConfidence.PATH_NORMALIZED.value
        reason = "Linked material sidecar via model -> modelproperty"
    elif (
        isinstance(resolved_entry, ArchiveEntry)
        and source_entry.pamt_path != resolved_entry.pamt_path
        and source_entry.pamt_path.parent != resolved_entry.pamt_path.parent
    ):
        confidence = RelationConfidence.CROSS_PACKAGE.value
        reason = "Cross-package reference"
    elif normalized_basename and normalized_basename in family_targets and normalized_basename not in same_stem_targets:
        confidence = RelationConfidence.DERIVED_FAMILY_HEURISTIC.value
        reason = "Family-token heuristic"
    else:
        confidence = RelationConfidence.DERIVED_SAME_STEM.value
        reason = "Same-stem heuristic"
    return relation_kind, _relation_group_for_kind(relation_kind), confidence, reason


def _find_archive_model_related_entries(
    source_entry: ArchiveEntry,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Tuple[ArchiveEntry, ...]:
    if archive_entries_by_basename is None:
        return ()

    normalized_path = source_entry.path.replace("\\", "/").strip()
    basename = PurePosixPath(normalized_path).name.strip()
    source_stem = PurePosixPath(normalized_path).stem.strip()
    if not basename:
        return ()

    source_extension = str(source_entry.extension or "").strip().lower()
    target_basenames: set[str] = set()
    must_keep_basenames: set[str] = set()

    def add_target(raw_value: str, *, must_keep: bool = False) -> None:
        candidate = str(raw_value or "").strip().lower()
        if candidate:
            target_basenames.add(candidate)
            if must_keep:
                must_keep_basenames.add(candidate)

    add_target(f"{basename}.xml", must_keep=True)
    if source_stem:
        _extend_archive_related_target_basenames(
            add_target,
            stem=source_stem,
            source_extension=source_extension,
        )
        if source_extension == ".pac":
            add_target(f"{source_stem}.pab", must_keep=True)
            add_target(f"{source_stem}.prefabdata.xml", must_keep=True)
            add_target(f"{source_stem}.pac_xml", must_keep=True)
            add_target(f"{source_stem}.prefabdata_xml", must_keep=True)
        elif source_extension == ".pam":
            add_target(f"{source_stem}.pami", must_keep=True)
            add_target(f"{source_stem}.pam_xml", must_keep=True)
            add_target(f"{source_stem}.pamlod", must_keep=True)
        elif source_extension == ".pamlod":
            add_target(f"{source_stem}.pami", must_keep=True)
            add_target(f"{source_stem}.pamlod_xml", must_keep=True)
            add_target(f"{source_stem}.pam_xml", must_keep=True)
            add_target(f"{source_stem}.pam", must_keep=True)
        if source_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            nested_basename = source_stem.strip()
            nested_extension = PurePosixPath(nested_basename).suffix.strip().lower()
            nested_stem = PurePosixPath(nested_basename).stem.strip()
            if nested_extension:
                add_target(nested_basename, must_keep=True)
                _extend_archive_related_target_basenames(
                    add_target,
                    stem=nested_stem,
                    source_extension=nested_extension,
                )
    for family_target in _collect_family_heuristic_target_basenames(source_entry):
        add_target(family_target)
    add_target(f"{basename}.hkx", must_keep=True)
    add_target(f"{basename}.hkt", must_keep=True)
    add_target(f"{basename}.meshinfo", must_keep=True)

    candidates: List[ArchiveEntry] = []
    must_keep_candidates: List[ArchiveEntry] = []
    for target_basename in target_basenames:
        for candidate in archive_entries_by_basename.get(target_basename, ()):
            if candidate.path == source_entry.path:
                continue
            if candidate not in candidates:
                candidates.append(candidate)
            if target_basename in must_keep_basenames and candidate not in must_keep_candidates:
                must_keep_candidates.append(candidate)
    if not candidates:
        return ()
    candidates.sort(key=lambda candidate: _score_model_related_entry_candidate(source_entry, candidate), reverse=True)
    ordered: List[ArchiveEntry] = []
    for candidate in must_keep_candidates:
        if candidate not in ordered:
            ordered.append(candidate)
    for candidate in candidates:
        if candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered[:64])


def _find_archive_model_sidecar_entries(
    source_entry: ArchiveEntry,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Tuple[ArchiveEntry, ...]:
    if archive_entries_by_basename is None:
        return ()

    normalized_path = source_entry.path.replace("\\", "/").strip()
    basename = PurePosixPath(normalized_path).name.strip()
    source_stem = PurePosixPath(normalized_path).stem.strip()
    source_extension = str(source_entry.extension or "").strip().lower()
    target_basenames: set[str] = set()

    def add_target(raw_value: str) -> None:
        candidate = str(raw_value or "").strip().lower()
        if candidate:
            target_basenames.add(candidate)

    if basename:
        add_target(f"{basename}.xml")
    if source_stem:
        add_target(f"{source_stem}.xml")
        if source_extension == ".pac":
            add_target(f"{source_stem}.pac_xml")
        elif source_extension == ".pam":
            add_target(f"{source_stem}.pam_xml")
        elif source_extension == ".pamlod":
            add_target(f"{source_stem}.pamlod_xml")
        if source_extension in {".pam", ".pamlod"}:
            add_target(f"{source_stem}.pami")
        elif source_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            nested_basename = source_stem.strip()
            nested_extension = PurePosixPath(nested_basename).suffix.strip().lower()
            nested_stem = PurePosixPath(nested_basename).stem.strip()
            if nested_extension:
                add_target(f"{nested_basename}.xml")
                add_target(f"{nested_stem}.xml")
                if nested_extension == ".pac":
                    add_target(f"{nested_stem}.pac_xml")
                elif nested_extension == ".pam":
                    add_target(f"{nested_stem}.pam_xml")
                elif nested_extension == ".pamlod":
                    add_target(f"{nested_stem}.pamlod_xml")
                if nested_extension in {".pam", ".pamlod"}:
                    add_target(f"{nested_stem}.pami")

    candidates: List[ArchiveEntry] = []
    for target_basename in target_basenames:
        for candidate in archive_entries_by_basename.get(target_basename, ()):
            if candidate.path == source_entry.path:
                continue
            candidate_basename = PurePosixPath(candidate.path.replace("\\", "/")).name.lower()
            if not _is_material_sidecar_extension(candidate.extension, candidate_basename):
                continue
            if candidate not in candidates:
                candidates.append(candidate)
    if not candidates:
        candidates = [
            candidate
            for candidate in _find_archive_model_related_entries(source_entry, archive_entries_by_basename)
            if _is_material_sidecar_extension(
                str(candidate.extension or "").strip().lower(),
                PurePosixPath(candidate.path.replace("\\", "/")).name.lower(),
            )
        ]
    if not candidates:
        return ()
    if len(candidates) > 1:
        source_parts = [part for part in PurePosixPath(_normalize_model_texture_reference(source_entry.path)).parts if part]

        def shared_prefix_depth(candidate: ArchiveEntry) -> int:
            candidate_parts = [part for part in PurePosixPath(_normalize_model_texture_reference(candidate.path)).parts if part]
            depth = 0
            for source_part, candidate_part in zip(source_parts, candidate_parts):
                if source_part != candidate_part:
                    break
                depth += 1
            return depth

        best_depth = max(shared_prefix_depth(candidate) for candidate in candidates)
        if best_depth > 0:
            candidates = [candidate for candidate in candidates if shared_prefix_depth(candidate) == best_depth]
    candidates.sort(key=lambda candidate: _score_model_sidecar_entry_candidate(source_entry, candidate), reverse=True)
    return tuple(candidates[:8])


def _parse_archive_model_sidecar_texture_bindings(
    sidecar_text: str,
    *,
    sidecar_path: str,
) -> Tuple[_ArchiveModelSidecarTextureBinding, ...]:
    parsed_bindings = parse_texture_sidecar_bindings(sidecar_text, sidecar_path=sidecar_path)
    material_profile = parse_material_sidecar_profile(sidecar_text, sidecar_path=sidecar_path)
    slot_parameters_by_key: Dict[Tuple[str, str, str, str], Tuple[PreviewMaterialParameterInput, ...]] = {}

    def _sidecar_parameter_input(kind: str, parameter: object) -> PreviewMaterialParameterInput:
        return PreviewMaterialParameterInput(
            parameter_kind=str(kind or "").strip().lower(),
            parameter_name=str(getattr(parameter, "parameter_name", "") or "").strip(),
            tag_name=str(getattr(parameter, "tag_name", "") or "").strip(),
            string_item_id=str(getattr(parameter, "string_item_id", "") or "").strip(),
            item_id=str(getattr(parameter, "item_id", "") or "").strip(),
            index=int(getattr(parameter, "index", -1) or -1),
            value=str(getattr(parameter, "value", "") or "").strip(),
            texture_path=str(getattr(parameter, "texture_path", "") or "").strip(),
            color_value=tuple(getattr(parameter, "color_value", ()) or ()),
            numeric_value=getattr(parameter, "numeric_value", None),
        )

    def _binding_slot_key(
        *,
        part_name: object,
        material_name: object,
        submesh_name: object = "",
        shader_family: object = "",
    ) -> Tuple[str, str, str, str]:
        return (
            str(part_name or "").strip().lower(),
            str(material_name or "").strip().lower(),
            str(submesh_name or "").strip().lower(),
            str(shader_family or "").strip().lower(),
        )

    for slot in tuple(getattr(material_profile, "materials", ()) or ()):
        parameters: List[PreviewMaterialParameterInput] = []
        for kind, values in (
            ("texture", getattr(slot, "texture_parameters", ()) or ()),
            ("color", getattr(slot, "color_parameters", ()) or ()),
            ("float", getattr(slot, "float_parameters", ()) or ()),
            ("flag", getattr(slot, "flag_parameters", ()) or ()),
            ("byte4", getattr(slot, "byte4_parameters", ()) or ()),
        ):
            parameters.extend(_sidecar_parameter_input(kind, parameter) for parameter in tuple(values or ()))
        if not parameters:
            continue
        keys = {
            _binding_slot_key(
                part_name=getattr(slot, "part_name", ""),
                material_name=getattr(slot, "material_name", ""),
                shader_family=getattr(slot, "shader_family", ""),
            ),
            _binding_slot_key(
                part_name=getattr(slot, "part_name", ""),
                material_name=getattr(slot, "part_name", ""),
                shader_family=getattr(slot, "shader_family", ""),
            ),
            _binding_slot_key(
                part_name=getattr(slot, "material_name", ""),
                material_name=getattr(slot, "material_name", ""),
                shader_family=getattr(slot, "shader_family", ""),
            ),
        }
        for key in keys:
            if key[0] or key[1] or key[3]:
                slot_parameters_by_key[key] = tuple(parameters)

    def _parameters_for_binding(binding: object) -> Tuple[PreviewMaterialParameterInput, ...]:
        keys = (
            _binding_slot_key(
                part_name=getattr(binding, "part_name", ""),
                material_name=getattr(binding, "material_name", ""),
                submesh_name=getattr(binding, "submesh_name", ""),
                shader_family=getattr(binding, "shader_family", ""),
            ),
            _binding_slot_key(
                part_name=getattr(binding, "part_name", ""),
                material_name=getattr(binding, "material_name", ""),
                shader_family=getattr(binding, "shader_family", ""),
            ),
            _binding_slot_key(
                part_name=getattr(binding, "submesh_name", ""),
                material_name=getattr(binding, "material_name", ""),
                shader_family=getattr(binding, "shader_family", ""),
            ),
            _binding_slot_key(
                part_name=getattr(binding, "material_name", ""),
                material_name=getattr(binding, "material_name", ""),
                shader_family=getattr(binding, "shader_family", ""),
            ),
        )
        for key in keys:
            parameters = slot_parameters_by_key.get(key, ())
            if parameters:
                return parameters
        return ()

    archive_bindings: List[_ArchiveModelSidecarTextureBinding] = []
    try:
        from cdmw.modding.asset_replacement import classify_texture_binding
    except Exception:
        classify_texture_binding = None  # type: ignore[assignment]
    for binding in parsed_bindings:
        texture_role = binding.texture_role
        visualization_state = binding.visualization_state
        if classify_texture_binding is not None:
            try:
                classification = classify_texture_binding(binding.parameter_name, binding.texture_path)
                texture_role = classification.slot_label or classification.slot_kind
                visualization_state = classification.visual_state
            except Exception:
                pass
        archive_bindings.append(
            _ArchiveModelSidecarTextureBinding(
                texture_path=binding.texture_path,
                parameter_name=binding.parameter_name,
                submesh_name=binding.submesh_name,
                sidecar_path=binding.sidecar_path,
                sidecar_kind=binding.sidecar_kind,
                linked_mesh_path=binding.linked_mesh_path,
                part_name=binding.part_name,
                material_name=binding.material_name,
                shader_family=binding.shader_family,
                texture_role=texture_role,
                visualization_state=visualization_state,
                resolved_texture_exists=binding.resolved_texture_exists,
                represent_color=tuple(binding.represent_color or ()),
                tint_color=tuple(binding.tint_color or ()),
                brightness=float(binding.brightness or 1.0),
                uv_scale=float(binding.uv_scale or 1.0),
                tile_type=binding.tile_type,
                material_parameters=_parameters_for_binding(binding),
            )
        )
    return tuple(archive_bindings)


def _archive_entry_identity_signature(entry: ArchiveEntry) -> Tuple[object, ...]:
    try:
        paz_stat = Path(getattr(entry, "paz_file", "")).stat()
        paz_stamp = (
            int(paz_stat.st_size),
            int(getattr(paz_stat, "st_mtime_ns", int(paz_stat.st_mtime * 1_000_000_000))),
        )
    except OSError:
        paz_stamp = (0, 0)
    return (
        str(getattr(entry, "path", "") or "").replace("\\", "/"),
        str(getattr(entry, "pamt_path", "") or ""),
        str(getattr(entry, "paz_file", "") or ""),
        paz_stamp,
        int(getattr(entry, "offset", 0)),
        int(getattr(entry, "comp_size", 0)),
        int(getattr(entry, "orig_size", 0)),
        int(getattr(entry, "flags", 0)),
        int(getattr(entry, "paz_index", 0)),
    )


def _archive_entry_pathc_identity_signature(entry: ArchiveEntry) -> Tuple[object, ...]:
    if str(getattr(entry, "extension", "") or "").lower() != ".dds" or int(getattr(entry, "compression_type", 0) or 0) != 1:
        return ()
    try:
        pathc_path = resolve_archive_pathc_path(entry)
        pathc_stat = pathc_path.stat()
        return (
            str(pathc_path),
            int(pathc_stat.st_size),
            int(getattr(pathc_stat, "st_mtime_ns", int(pathc_stat.st_mtime * 1_000_000_000))),
        )
    except OSError:
        return ("missing_pathc",)


def _texconv_identity_signature(texconv_path: Path) -> Tuple[object, ...]:
    try:
        resolved_path = texconv_path.expanduser().resolve()
    except OSError:
        resolved_path = texconv_path.expanduser()
    try:
        texconv_stat = resolved_path.stat()
        return (
            str(resolved_path),
            int(texconv_stat.st_size),
            int(getattr(texconv_stat, "st_mtime_ns", int(texconv_stat.st_mtime * 1_000_000_000))),
        )
    except OSError:
        return (str(resolved_path), 0, 0)


def _extract_model_sidecar_entry_bindings_cached(
    sidecar_entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[
    Tuple[_ArchiveModelSidecarTextureBinding, ...],
    Tuple[str, ...],
    Dict[str, Tuple[str, ...]],
    Dict[str, Tuple[str, ...]],
]:
    cache_key = _archive_entry_identity_signature(sidecar_entry)
    with _MODEL_SIDECAR_PARSE_CACHE_LOCK:
        cached = _MODEL_SIDECAR_PARSE_CACHE.get(cache_key)
        if cached is not None:
            _MODEL_SIDECAR_PARSE_CACHE.move_to_end(cache_key)
            return cached

    sidecar_data, _decompressed, _note = read_archive_entry_data(sidecar_entry, stop_event=stop_event)
    text = try_decode_text_like_archive_data(sidecar_data)
    if text is None:
        parsed_result = ((), (), {}, {})
    else:
        parsed_bindings = _parse_archive_model_sidecar_texture_bindings(text, sidecar_path=sidecar_entry.path)
        sidecar_texts_by_normalized_path: Dict[str, List[str]] = defaultdict(list)
        sidecar_texts_by_basename: Dict[str, List[str]] = defaultdict(list)
        for binding in parsed_bindings:
            normalized_texture_path = normalize_texture_reference_for_sidecar_lookup(binding.texture_path)
            if not normalized_texture_path:
                continue
            if text not in sidecar_texts_by_normalized_path[normalized_texture_path]:
                sidecar_texts_by_normalized_path[normalized_texture_path].append(text)
            texture_basename = PurePosixPath(normalized_texture_path).name
            if texture_basename and text not in sidecar_texts_by_basename[texture_basename]:
                sidecar_texts_by_basename[texture_basename].append(text)
        parsed_result = (
            tuple(parsed_bindings),
            (sidecar_entry.path,) if parsed_bindings else (),
            {key: tuple(values) for key, values in sidecar_texts_by_normalized_path.items()},
            {key: tuple(values) for key, values in sidecar_texts_by_basename.items()},
        )

    with _MODEL_SIDECAR_PARSE_CACHE_LOCK:
        _MODEL_SIDECAR_PARSE_CACHE[cache_key] = parsed_result
        _MODEL_SIDECAR_PARSE_CACHE.move_to_end(cache_key)
        while len(_MODEL_SIDECAR_PARSE_CACHE) > _MODEL_SIDECAR_PARSE_CACHE_LIMIT:
            _MODEL_SIDECAR_PARSE_CACHE.popitem(last=False)
    return parsed_result


def _extract_archive_model_sidecar_texture_references(
    source_entry: ArchiveEntry,
    *,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    stop_event: Optional[threading.Event] = None,
) -> Tuple[
    Tuple[_ArchiveModelSidecarTextureBinding, ...],
    Tuple[str, ...],
    Dict[str, Tuple[str, ...]],
    Dict[str, Tuple[str, ...]],
]:
    raise_if_cancelled(stop_event)
    sidecar_entries = _find_archive_model_sidecar_entries(source_entry, archive_entries_by_basename)
    cache_key: Tuple[object, ...] = (
        _archive_entry_identity_signature(source_entry),
        tuple(_archive_entry_identity_signature(sidecar_entry) for sidecar_entry in sidecar_entries),
    )
    with _MODEL_SIDECAR_PARSE_CACHE_LOCK:
        cached = _MODEL_SIDECAR_REFERENCE_CACHE.get(cache_key)
        if cached is not None:
            _MODEL_SIDECAR_REFERENCE_CACHE.move_to_end(cache_key)
            return cached

    bindings: List[_ArchiveModelSidecarTextureBinding] = []
    sidecar_paths: List[str] = []
    seen_binding_keys: set[Tuple[str, str, str]] = set()
    sidecar_texts_by_normalized_path: Dict[str, List[str]] = defaultdict(list)
    sidecar_texts_by_basename: Dict[str, List[str]] = defaultdict(list)
    had_sidecar_error = False

    def append_unique_texts(target: Dict[str, List[str]], key: str, values: Sequence[str]) -> None:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            return
        bucket = target[normalized_key]
        for value in values:
            text = str(value or "")
            if not text.strip() or text in bucket:
                continue
            bucket.append(text)

    for sidecar_entry in sidecar_entries:
        raise_if_cancelled(stop_event)
        try:
            parsed_bindings, parsed_paths, parsed_texts_by_path, parsed_texts_by_basename = (
                _extract_model_sidecar_entry_bindings_cached(sidecar_entry, stop_event=stop_event)
            )
        except RunCancelled:
            raise
        except Exception:
            had_sidecar_error = True
            continue
        if not parsed_bindings:
            continue
        for parsed_path in parsed_paths:
            if parsed_path not in sidecar_paths:
                sidecar_paths.append(parsed_path)
        for key, values in parsed_texts_by_path.items():
            append_unique_texts(sidecar_texts_by_normalized_path, key, values)
        for key, values in parsed_texts_by_basename.items():
            append_unique_texts(sidecar_texts_by_basename, key, values)
        for binding in parsed_bindings:
            normalized_texture_path = normalize_texture_reference_for_sidecar_lookup(binding.texture_path)
            key = (
                normalized_texture_path,
                str(binding.submesh_name or "").strip().lower(),
                str(binding.parameter_name or "").strip().lower(),
            )
            if key in seen_binding_keys:
                continue
            seen_binding_keys.add(key)
            bindings.append(binding)
    result = (
        tuple(bindings),
        tuple(sidecar_paths),
        {key: tuple(values) for key, values in sidecar_texts_by_normalized_path.items()},
        {key: tuple(values) for key, values in sidecar_texts_by_basename.items()},
    )
    raise_if_cancelled(stop_event)
    if not had_sidecar_error:
        with _MODEL_SIDECAR_PARSE_CACHE_LOCK:
            _MODEL_SIDECAR_REFERENCE_CACHE[cache_key] = result
            _MODEL_SIDECAR_REFERENCE_CACHE.move_to_end(cache_key)
            while len(_MODEL_SIDECAR_REFERENCE_CACHE) > _MODEL_SIDECAR_REFERENCE_CACHE_LIMIT:
                _MODEL_SIDECAR_REFERENCE_CACHE.popitem(last=False)
    return result


def _iter_parsed_model_submeshes(parsed_mesh: Optional[object]) -> List[object]:
    if parsed_mesh is None:
        return []
    if str(getattr(parsed_mesh, "format", "") or "").strip().lower() == "pamlod":
        lod_levels = getattr(parsed_mesh, "lod_levels", None) or [[]]
        return list(lod_levels[0] or [])
    return list(getattr(parsed_mesh, "submeshes", ()) or [])


def _iter_model_submesh_reference_candidates(*values: str) -> Tuple[str, ...]:
    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_submesh_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)

    for raw_value in values:
        raw_text = str(raw_value or "").strip()
        if not raw_text:
            continue
        add_candidate(raw_text)
        pure_path = PurePosixPath(raw_text.replace("\\", "/"))
        basename = pure_path.name
        stem = pure_path.stem
        if basename and basename != raw_text:
            add_candidate(basename)
        if stem and stem not in {raw_text, basename}:
            add_candidate(stem)
    return tuple(ordered_candidates)


def _iter_model_sidecar_binding_submesh_keys(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[str, ...]:
    values: List[str] = [
        str(getattr(binding, "submesh_name", "") or ""),
        str(getattr(binding, "part_name", "") or ""),
        str(getattr(binding, "material_name", "") or ""),
    ]
    explicit_keys = _iter_model_submesh_reference_candidates(*values)
    if explicit_keys:
        return explicit_keys
    linked_mesh_path = str(getattr(binding, "linked_mesh_path", "") or "").replace("\\", "/").strip()
    if linked_mesh_path:
        linked_mesh = PurePosixPath(linked_mesh_path)
        values.extend([linked_mesh_path, linked_mesh.name, linked_mesh.stem])
    return _iter_model_submesh_reference_candidates(*values)


def _iter_model_texture_family_reference_candidates(group_key: str) -> Tuple[str, ...]:
    normalized_group_key = _normalize_model_texture_reference(group_key)
    if not normalized_group_key:
        return ()

    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)

    if "/" in normalized_group_key:
        folder, _, family_name = normalized_group_key.rpartition("/")
    else:
        folder, family_name = "", normalized_group_key
    family_name = family_name.strip()
    if not family_name:
        return ()

    for suffix in _MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES:
        basename = f"{family_name}{suffix}.dds"
        add_candidate(basename)
        if folder:
            add_candidate(f"{folder}/{basename}")

    return tuple(ordered_candidates)


def _iter_model_texture_slot_family_reference_candidates(
    group_key: str,
    preview_slot: str,
) -> Tuple[str, ...]:
    normalized_slot = str(preview_slot or "").strip().lower()
    if not normalized_slot or normalized_slot == "base":
        return _iter_model_texture_family_reference_candidates(group_key)

    suffixes = _MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES.get(normalized_slot, ())
    if not suffixes:
        return ()

    normalized_group_key = _normalize_model_texture_reference(group_key)
    if not normalized_group_key:
        return ()

    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)
        parts = [part for part in PurePosixPath(normalized).parts if part]
        if len(parts) >= 3 and parts[1].lower() == "texture":
            texture_folder_variant = "/".join((parts[0], *parts[2:]))
            if texture_folder_variant and texture_folder_variant not in seen:
                seen.add(texture_folder_variant)
                ordered_candidates.append(texture_folder_variant)

    if "/" in normalized_group_key:
        folder, _, family_name = normalized_group_key.rpartition("/")
    else:
        folder, family_name = "", normalized_group_key
    family_name = family_name.strip()
    if not family_name:
        return ()

    for suffix in suffixes:
        basename = f"{family_name}{suffix}.dds"
        add_candidate(basename)
        if folder:
            add_candidate(f"{folder}/{basename}")

    return tuple(ordered_candidates)


def _iter_model_texture_reference_candidates(
    texture_name: str,
    material_name: str = "",
) -> Tuple[str, ...]:
    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)

    for raw_value in (texture_name, material_name):
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized:
            continue
        add_candidate(normalized)
        basename = PurePosixPath(normalized).name
        stem = PurePosixPath(normalized).stem
        suffix = PurePosixPath(normalized).suffix.lower()
        if basename:
            add_candidate(basename)
        if stem:
            add_candidate(stem)
        if suffix != ".dds":
            add_candidate(f"{normalized}.dds")
            if basename:
                add_candidate(f"{basename}.dds")
            if stem:
                add_candidate(f"{stem}.dds")

    return tuple(ordered_candidates)


def _match_model_texture_slot_family_suffix(
    texture_path: str,
    preview_slot: str,
) -> int:
    normalized_slot = str(preview_slot or "").strip().lower()
    suffixes = _MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES.get(normalized_slot, ())
    if not suffixes:
        return -1
    basename = PurePosixPath(_normalize_model_texture_reference(texture_path)).name
    if not basename.endswith(".dds"):
        return -1
    stem = basename[:-4]
    for index, suffix in enumerate(suffixes):
        if stem.endswith(suffix):
            return index
    return -1


def _looks_like_technical_model_texture(texture_path: str) -> bool:
    normalized = _normalize_model_texture_reference(texture_path)
    if not normalized:
        return False
    basename = PurePosixPath(normalized).name
    for pattern in _COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS:
        if (basename and fnmatch.fnmatch(basename, pattern)) or fnmatch.fnmatch(normalized, pattern):
            return True
    return False


def _is_placeholder_model_texture(texture_path: str) -> bool:
    normalized = _normalize_model_texture_reference(texture_path)
    if not normalized:
        return False
    stem = PurePosixPath(normalized).stem.lower()
    compact_stem = re.sub(r"[^a-z0-9]+", "", stem)
    if "nonetexture" in compact_stem or "nulltexture" in compact_stem or "dummytexture" in compact_stem:
        return True
    if compact_stem in {"none", "notexture", "placeholdertexture"}:
        return True
    return False


def _has_explicit_model_texture_reference(*values: str) -> bool:
    for raw_value in values:
        normalized = _normalize_model_texture_reference(raw_value)
        if normalized.endswith(".dds"):
            return True
    return False


def _is_visible_model_texture_type(texture_type: str) -> bool:
    return str(texture_type or "").strip().lower() in {"color", "ui", "emissive", "impostor"}


def _resolve_model_texture_semantics(
    texture_path: str,
    *,
    family_members: Sequence[str] = (),
    sidecar_texts: Sequence[str] = (),
) -> Tuple[str, str, int]:
    semantic = infer_texture_semantics(
        texture_path,
        family_members=family_members,
        sidecar_texts=sidecar_texts,
    )
    texture_type = str(getattr(semantic, "texture_type", "") or "").strip().lower() or "unknown"
    semantic_subtype = str(getattr(semantic, "semantic_subtype", "") or "").strip().lower() or texture_type
    confidence = int(getattr(semantic, "confidence", 0) or 0)
    if texture_type == "unknown":
        normalized = _normalize_model_texture_reference(texture_path)
        if (
            normalized.endswith(".dds")
            and not _is_placeholder_model_texture(normalized)
            and not _looks_like_technical_model_texture(normalized)
        ):
            return "color", "albedo", max(confidence, 64)
    return texture_type, semantic_subtype, confidence


def _resolve_model_texture_semantic_details(
    texture_path: str,
    *,
    family_members: Sequence[str] = (),
    sidecar_texts: Sequence[str] = (),
) -> Tuple[str, str, int, Tuple[str, ...]]:
    semantic = infer_texture_semantics(
        texture_path,
        family_members=family_members,
        sidecar_texts=sidecar_texts,
    )
    texture_type = str(getattr(semantic, "texture_type", "") or "").strip().lower() or "unknown"
    semantic_subtype = str(getattr(semantic, "semantic_subtype", "") or "").strip().lower() or texture_type
    confidence = int(getattr(semantic, "confidence", 0) or 0)
    packed_channels = tuple(
        str(item or "").strip().lower()
        for item in getattr(semantic, "packed_channels", ())
        if str(item or "").strip()
    )
    if texture_type == "unknown":
        normalized = _normalize_model_texture_reference(texture_path)
        if (
            normalized.endswith(".dds")
            and not _is_placeholder_model_texture(normalized)
            and not _looks_like_technical_model_texture(normalized)
        ):
            return "color", "albedo", max(confidence, 64), ()
    return texture_type, semantic_subtype, confidence, packed_channels


def _refine_model_texture_semantic_from_hint(
    texture_type: str,
    semantic_subtype: str,
    semantic_hint: str,
) -> Tuple[str, str]:
    normalized_hint = re.sub(r"[^a-z0-9]+", "", str(semantic_hint or "").strip().lower())
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    if not normalized_hint:
        return normalized_type, normalized_subtype

    if any(token in normalized_hint for token in ("orm", "occlusionroughnessmetallic")):
        return "mask", "orm"
    if any(token in normalized_hint for token in ("rma", "roughnessmetallicao")):
        return "mask", "rma"
    if any(token in normalized_hint for token in ("mra", "metallicroughnessao")):
        return "mask", "mra"
    if any(token in normalized_hint for token in ("arm", "aoroughnessmetallic")):
        return "mask", "arm"
    if "roughness" in normalized_hint:
        return "roughness", "roughness"
    if any(token in normalized_hint for token in ("specular", "gloss", "smoothness")):
        return "mask", "specular"
    if any(token in normalized_hint for token in ("metallic", "metalness")):
        return "mask", "metallic"
    if any(token in normalized_hint for token in ("ao", "occlusion")):
        return "mask", "ao"
    if "opacity" in normalized_hint or "alpha" in normalized_hint:
        return "mask", "opacity_mask"
    if "material" in normalized_hint and normalized_subtype in {"unknown", "mask"}:
        return "mask", "material_mask"
    return normalized_type, normalized_subtype


def _infer_model_preview_texture_slot(
    texture_path: str,
    *,
    semantic_hint: str = "",
    sidecar_texts: Sequence[str] = (),
) -> str:
    normalized_hint = re.sub(r"[^a-z0-9]+", "", str(semantic_hint or "").strip().lower())
    if normalized_hint:
        if "normal" in normalized_hint:
            return "normal"
        if any(token in normalized_hint for token in ("height", "displacement", "parallax", "pom", "ssdm", "bump")):
            return "height"
        if any(token in normalized_hint for token in ("material", "roughness", "metallic", "metalness", "specular", "ao", "occlusion", "mask")):
            return "material"
        if any(token in normalized_hint for token in ("basecolor", "overlaycolor", "diffuse", "albedo", "colortexture", "emissive")):
            return "base"
    texture_type, semantic_subtype, _confidence = _resolve_model_texture_semantics(
        texture_path,
        sidecar_texts=sidecar_texts,
    )
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    if normalized_type == "normal":
        return "normal"
    if normalized_type == "height" or normalized_subtype in {"displacement", "parallax_height", "height", "bump"}:
        return "height"
    if normalized_type in {"mask", "roughness", "vector"}:
        return "material"
    return "base"


def _model_texture_candidate_slot_priority(
    preview_slot: str,
    texture_path: str,
    *,
    sidecar_texts: Sequence[str] = (),
) -> Optional[Tuple[int, int]]:
    normalized_slot = str(preview_slot or "").strip().lower()
    if normalized_slot not in {"normal", "material", "height"}:
        return None

    texture_type, semantic_subtype, _confidence = _resolve_model_texture_semantics(
        texture_path,
        sidecar_texts=sidecar_texts,
    )
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    suffix_index = _match_model_texture_slot_family_suffix(texture_path, normalized_slot)
    suffix_priority = (
        len(_MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES.get(normalized_slot, ())) - suffix_index
        if suffix_index >= 0
        else 0
    )

    if normalized_slot == "normal":
        if normalized_type == "normal":
            return (12, 3)
        if suffix_index >= 0:
            return (10, suffix_priority)
        return None

    if normalized_slot == "height":
        if normalized_type == "height" or normalized_subtype in {"displacement", "parallax_height", "height", "bump"}:
            return (12, 3)
        if suffix_index >= 0:
            return (10, suffix_priority)
        return None

    if normalized_slot == "material":
        if normalized_type in {"mask", "roughness", "vector"}:
            return (12, 3)
        if normalized_subtype in {"packed_mask", "specular", "metallic", "ao", "mask", "opacity_mask"}:
            return (11, 2)
        if suffix_index >= 0:
            return (10, suffix_priority)
        return None

    return None


def _infer_model_preview_normal_strength(
    *,
    base_texture_path: str = "",
    normal_texture_path: str = "",
    material_name: str = "",
    semantic_hint: str = "",
    prefer_stronger: bool = False,
) -> float:
    normalized_hint = str(semantic_hint or "").strip().lower().replace("_", "")
    combined = " ".join(
        part
        for part in (
            _normalize_model_texture_reference(base_texture_path),
            _normalize_model_texture_reference(normal_texture_path),
            str(material_name or "").strip().lower(),
            normalized_hint,
        )
        if part
    )

    strength = 0.36
    if prefer_stronger:
        strength += 0.08
    if normalized_hint in {"normaltexture", "basenormaltexture"}:
        strength += 0.06
    elif "detailnormal" in normalized_hint or "grimenormal" in normalized_hint:
        strength -= 0.05

    soft_tokens = (
        "wood",
        "plank",
        "timber",
        "fabric",
        "cloth",
        "rope",
        "leather",
        "skin",
        "paper",
        "parchment",
        "banner",
        "canvas",
        "fur",
        "hair",
    )
    hard_tokens = (
        "stone",
        "rock",
        "brick",
        "concrete",
        "cliff",
        "marble",
        "granite",
        "dungeon",
        "ancient",
        "wall",
        "masonry",
        "ruin",
    )
    medium_tokens = (
        "metal",
        "rust",
        "iron",
        "steel",
        "armor",
        "shield",
        "weapon",
    )

    if any(token in combined for token in soft_tokens):
        strength -= 0.04
    if any(token in combined for token in hard_tokens):
        strength += 0.14
    if any(token in combined for token in medium_tokens):
        strength += 0.08

    return max(0.22, min(0.72, strength))


def _set_model_preview_texture_slot(
    mesh: ModelPreviewMesh,
    *,
    slot: str,
    preview_path: str,
    texture_path: str,
    normal_strength: Optional[float] = None,
    semantic_type: str = "",
    semantic_subtype: str = "",
    packed_channels: Sequence[str] = (),
    flip_vertical: Optional[bool] = None,
) -> bool:
    normalized_slot = str(slot or "").strip().lower()
    preview_path_text = str(preview_path or "").strip()
    texture_path_text = str(texture_path or "").strip()
    if not preview_path_text:
        return False

    if normalized_slot == "normal":
        if not str(getattr(mesh, "preview_normal_texture_path", "") or "").strip():
            mesh.preview_normal_texture_path = preview_path_text
            mesh.preview_normal_texture_image = None
            mesh.preview_normal_texture_name = texture_path_text
            if normal_strength is not None:
                mesh.preview_normal_texture_strength = float(normal_strength)
            if texture_path_text and not str(getattr(mesh, "texture_name", "") or "").strip():
                mesh.texture_name = texture_path_text
            _append_model_preview_material_input(
                mesh,
                PreviewMaterialTextureInput(
                    slot_kind="normal",
                    source_texture_path=texture_path_text,
                    texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                    preview_texture_path=preview_path_text,
                    semantic_type="normal",
                    semantic_subtype="normal",
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    confidence="resolved",
                    visualized=True,
                ),
            )
            return True
        return False
    if normalized_slot == "material":
        if not str(getattr(mesh, "preview_material_texture_path", "") or "").strip():
            mesh.preview_material_texture_path = preview_path_text
            mesh.preview_material_texture_image = None
            mesh.preview_material_texture_name = texture_path_text
            mesh.preview_material_texture_type = str(semantic_type or "").strip().lower()
            mesh.preview_material_texture_subtype = str(semantic_subtype or "").strip().lower()
            mesh.preview_material_texture_packed_channels = tuple(
                str(channel or "").strip().lower()
                for channel in packed_channels
                if str(channel or "").strip()
            )
            _append_model_preview_material_input(
                mesh,
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    source_texture_path=texture_path_text,
                    texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                    preview_texture_path=preview_path_text,
                    semantic_type=str(semantic_type or "material").strip().lower(),
                    semantic_subtype=str(semantic_subtype or "").strip().lower(),
                    packed_channels=tuple(
                        str(channel or "").strip().lower()
                        for channel in packed_channels
                        if str(channel or "").strip()
                    ),
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    confidence="resolved",
                    visualized=True,
                ),
            )
            return True
        return False
    if normalized_slot == "height":
        if not str(getattr(mesh, "preview_height_texture_path", "") or "").strip():
            mesh.preview_height_texture_path = preview_path_text
            mesh.preview_height_texture_image = None
            mesh.preview_height_texture_name = texture_path_text
            _append_model_preview_material_input(
                mesh,
                PreviewMaterialTextureInput(
                    slot_kind="height",
                    source_texture_path=texture_path_text,
                    texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                    preview_texture_path=preview_path_text,
                    semantic_type="height",
                    semantic_subtype="displacement",
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    confidence="resolved",
                    visualized=True,
                ),
            )
            return True
        return False

    changed = False
    if not str(getattr(mesh, "preview_texture_path", "") or "").strip():
        mesh.preview_texture_path = preview_path_text
        mesh.preview_texture_image = None
        changed = True
    if texture_path_text:
        current_texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        if not current_texture_name or not current_texture_name.lower().endswith(".dds"):
            mesh.texture_name = texture_path_text
            changed = True
    if flip_vertical is not None:
        mesh.preview_texture_flip_vertical = bool(flip_vertical)
        changed = True
    if changed:
        _append_model_preview_material_input(
            mesh,
            PreviewMaterialTextureInput(
                slot_kind="base",
                source_texture_path=texture_path_text,
                texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                preview_texture_path=preview_path_text,
                semantic_type="color",
                semantic_subtype="albedo",
                material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                confidence="resolved",
                visualized=True,
            ),
        )
    return changed


def _append_model_preview_material_input(
    mesh: ModelPreviewMesh,
    input_item: PreviewMaterialTextureInput,
) -> bool:
    existing = list(getattr(mesh, "preview_material_texture_inputs", ()) or ())
    key = (
        str(input_item.slot_kind or "").strip().lower(),
        str(input_item.preview_texture_path or "").strip().lower(),
        str(input_item.source_texture_path or "").strip().lower(),
        str(input_item.parameter_name or "").strip().lower(),
    )
    for item in existing:
        existing_key = (
            str(getattr(item, "slot_kind", "") or "").strip().lower(),
            str(getattr(item, "preview_texture_path", "") or "").strip().lower(),
            str(getattr(item, "source_texture_path", "") or "").strip().lower(),
            str(getattr(item, "parameter_name", "") or "").strip().lower(),
        )
        if existing_key == key:
            return False
    existing.append(input_item)
    mesh.preview_material_texture_inputs = tuple(existing)
    return True


def _score_model_texture_archive_candidate(
    source_entry: ArchiveEntry,
    candidate: ArchiveEntry,
    reference_candidates: Sequence[str],
) -> Tuple[int, int]:
    score_value = 0
    normalized_candidate_path = _normalize_model_texture_reference(candidate.path)
    candidate_basename = PurePosixPath(normalized_candidate_path).name
    for reference_index, normalized_reference in enumerate(reference_candidates):
        reference_basename = PurePosixPath(normalized_reference).name
        if normalized_candidate_path == normalized_reference:
            score_value += max(8, 24 - reference_index)
            break
        if candidate_basename and candidate_basename == reference_basename:
            score_value += max(4, 16 - reference_index)
            break
    if candidate.pamt_path == source_entry.pamt_path:
        score_value += 8
    if candidate.pamt_path.parent == source_entry.pamt_path.parent:
        score_value += 4
    if candidate.paz_file == source_entry.paz_file:
        score_value += 2
    if "/texture/" in normalized_candidate_path:
        score_value += 1
    return score_value, -len(candidate.path)


def _collect_model_texture_archive_entry_candidates(
    source_entry: ArchiveEntry,
    texture_name: str,
    material_name: str,
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    *,
    expand_family_candidates: bool = True,
    preferred_slot: str = "",
) -> List[Tuple[ArchiveEntry, Tuple[int, int]]]:
    reference_candidates = _iter_model_texture_reference_candidates(texture_name, material_name)
    if not reference_candidates:
        return []

    expanded_reference_candidates: List[str] = list(reference_candidates)
    if expand_family_candidates:
        seen_expanded = set(expanded_reference_candidates)
        for normalized_reference in reference_candidates:
            group_key = derive_texture_group_key(normalized_reference)
            for family_reference in _iter_model_texture_slot_family_reference_candidates(group_key, preferred_slot):
                if family_reference in seen_expanded:
                    continue
                seen_expanded.add(family_reference)
                expanded_reference_candidates.append(family_reference)

    candidates: List[ArchiveEntry] = []
    for normalized_reference in expanded_reference_candidates:
        if texture_entries_by_normalized_path is not None:
            for candidate in texture_entries_by_normalized_path.get(normalized_reference, []):
                if candidate.extension == ".dds" and candidate not in candidates:
                    candidates.append(candidate)

        basename = PurePosixPath(normalized_reference).name
        if texture_entries_by_basename is not None and basename:
            for candidate in texture_entries_by_basename.get(basename, []):
                if candidate.extension == ".dds" and candidate not in candidates:
                    candidates.append(candidate)

    if not candidates:
        return []

    scored_candidates = [
        (candidate, _score_model_texture_archive_candidate(source_entry, candidate, reference_candidates))
        for candidate in candidates
    ]
    scored_candidates.sort(key=lambda item: item[1], reverse=True)
    return scored_candidates


def _model_texture_semantic_priority(texture_type: str, semantic_subtype: str) -> Tuple[int, int]:
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    if normalized_type == "color":
        subtype_priority = {
            "albedo": 4,
            "albedo_variant": 3,
            "diffuse": 2,
        }.get(normalized_subtype, 1)
        return 6, subtype_priority
    if normalized_type == "ui":
        return 5, 0
    if normalized_type == "emissive":
        return 4, 0
    if normalized_type == "impostor":
        return 3, 0
    if normalized_type == "unknown":
        return 2, 0
    if normalized_type == "mask" and normalized_subtype in {"detail_support", "grayscale_data"}:
        return 1, 0
    return 0, 0


def _resolve_model_texture_archive_entry(
    source_entry: ArchiveEntry,
    texture_name: str,
    material_name: str,
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    *,
    semantic_hint: str = "",
    expand_family_candidates: Optional[bool] = None,
    allow_technical_match: bool = False,
    preferred_slot: str = "",
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
) -> Tuple[Optional[ArchiveEntry], str]:
    normalized_preferred_slot = str(preferred_slot or "").strip().lower()
    if _has_explicit_model_texture_reference(texture_name) and _is_placeholder_model_texture(texture_name):
        return None, "missing"
    if _has_explicit_model_texture_reference(material_name) and _is_placeholder_model_texture(material_name):
        return None, "missing"
    if expand_family_candidates is None:
        if normalized_preferred_slot in {"normal", "material", "height"}:
            expand_family_candidates = True
        else:
            expand_family_candidates = not _has_explicit_model_texture_reference(texture_name, material_name)
    scored_candidates = _collect_model_texture_archive_entry_candidates(
        source_entry,
        texture_name,
        material_name,
        texture_entries_by_normalized_path,
        texture_entries_by_basename,
        expand_family_candidates=expand_family_candidates,
        preferred_slot=normalized_preferred_slot,
    )
    if not scored_candidates:
        return None, "missing"

    family_members_by_group: Dict[str, Tuple[str, ...]] = defaultdict(tuple)
    grouped_family_members: Dict[str, List[str]] = defaultdict(list)
    for candidate, _direct_score in scored_candidates:
        grouped_family_members[derive_texture_group_key(candidate.path)].append(candidate.path)
    for group_key, members in grouped_family_members.items():
        family_members_by_group[group_key] = tuple(members)

    best_candidate: Optional[ArchiveEntry] = None
    best_candidate_key: Optional[Tuple[int, int, int, Tuple[int, int]]] = None
    best_candidate_priority = (0, 0)
    hint_priority = _model_texture_hint_priority(semantic_hint)
    slot_filtered_out = False
    for candidate, direct_score in scored_candidates:
        group_key = derive_texture_group_key(candidate.path)
        candidate_normalized_path = normalize_texture_reference_for_sidecar_lookup(candidate.path)
        sidecar_texts = tuple(sidecar_texts_by_normalized_path.get(candidate_normalized_path, ())) if (
            sidecar_texts_by_normalized_path is not None and candidate_normalized_path
        ) else ()
        if not sidecar_texts and sidecar_texts_by_basename is not None:
            sidecar_texts = tuple(
                sidecar_texts_by_basename.get(PurePosixPath(candidate.path.replace("\\", "/")).name.lower(), ())
            )
        texture_type, semantic_subtype, confidence = _resolve_model_texture_semantics(
            candidate.path,
            family_members=family_members_by_group.get(group_key, (candidate.path,)),
            sidecar_texts=sidecar_texts,
        )
        if normalized_preferred_slot in {"normal", "material", "height"}:
            semantic_priority = _model_texture_candidate_slot_priority(
                normalized_preferred_slot,
                candidate.path,
                sidecar_texts=sidecar_texts,
            )
            if semantic_priority is None:
                slot_filtered_out = True
                continue
        else:
            semantic_priority = _model_texture_semantic_priority(
                texture_type,
                semantic_subtype,
            )
            if hint_priority is not None and hint_priority > semantic_priority:
                semantic_priority = hint_priority
        sort_key = (
            semantic_priority[0],
            semantic_priority[1],
            confidence,
            direct_score,
        )
        if best_candidate_key is None or sort_key > best_candidate_key:
            best_candidate = candidate
            best_candidate_key = sort_key
            best_candidate_priority = semantic_priority

    if best_candidate is None:
        if normalized_preferred_slot in {"normal", "material", "height"} and slot_filtered_out:
            return None, "technical_only"
        return None, "missing"
    if allow_technical_match and best_candidate_priority[0] <= 0:
        return best_candidate, "resolved"
    if best_candidate_priority[0] <= 0:
        return None, "technical_only"
    return best_candidate, "resolved"


def _ensure_archive_model_texture_preview_path(
    resolved_texconv_path: Path,
    texture_entry: ArchiveEntry,
    *,
    max_dimension: Optional[int] = None,
    slot_kind: str = "base",
    stop_event: Optional[threading.Event] = None,
) -> str:
    resolved_max_dimension = (
        int(max_dimension)
        if max_dimension is not None
        else int(_MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)
    )
    cache_key: Tuple[object, ...] = (
        _archive_entry_identity_signature(texture_entry),
        _archive_entry_pathc_identity_signature(texture_entry),
        _texconv_identity_signature(resolved_texconv_path),
        resolved_max_dimension,
        str(slot_kind or "base").strip().lower(),
    )
    with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
        cached_preview_path = _MODEL_TEXTURE_PREVIEW_PATH_CACHE.get(cache_key)
        if cached_preview_path:
            cached_path = Path(cached_preview_path)
            try:
                if cached_path.is_file() and cached_path.stat().st_size > 0:
                    _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
                    return cached_preview_path
            except OSError:
                pass
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE.pop(cache_key, None)

    texture_source_path, _texture_note = ensure_archive_preview_source(
        texture_entry,
        stop_event=stop_event,
    )
    dds_info: Optional[DdsInfo] = None
    try:
        dds_info = parse_dds(texture_source_path)
    except Exception:
        dds_info = None
    preview_path = ensure_dds_display_preview_png(
        resolved_texconv_path,
        texture_source_path.resolve(),
        dds_info=dds_info,
        max_dimension=resolved_max_dimension,
        slot_kind=slot_kind,
        stop_event=stop_event,
    )
    preview_path_text = str(preview_path)
    with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
        _MODEL_TEXTURE_PREVIEW_PATH_CACHE[cache_key] = preview_path_text
        _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
        while len(_MODEL_TEXTURE_PREVIEW_PATH_CACHE) > _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT:
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE.popitem(last=False)
    return preview_path_text


def _prefetch_archive_model_texture_preview_paths(
    resolved_texconv_path: Path,
    requests: Sequence[Tuple[ArchiveEntry, str, int]],
    preview_cache: Dict[str, str],
    *,
    stop_event: Optional[threading.Event] = None,
) -> None:
    if not requests:
        return
    try:
        from cdmw.core.texture_native import ensure_directxtex_dds_preview_pngs
    except Exception:
        return

    normalized_requests: List[Tuple[ArchiveEntry, str, int, str, Tuple[object, ...]]] = []
    seen: set[Tuple[str, str, int]] = set()
    for texture_entry, slot_kind, max_dimension in requests:
        slot_key = str(slot_kind or "base").strip().lower() or "base"
        resolved_max_dimension = max(1, int(max_dimension or _MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION))
        normalized_path = _normalize_model_texture_reference(texture_entry.path)
        if not normalized_path:
            continue
        local_key = f"{normalized_path}|{slot_key}"
        dedupe_key = (normalized_path, slot_key, resolved_max_dimension)
        if dedupe_key in seen or preview_cache.get(local_key):
            continue
        seen.add(dedupe_key)
        cache_key: Tuple[object, ...] = (
            _archive_entry_identity_signature(texture_entry),
            _archive_entry_pathc_identity_signature(texture_entry),
            _texconv_identity_signature(resolved_texconv_path),
            resolved_max_dimension,
            slot_key,
        )
        with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
            cached_preview_path = _MODEL_TEXTURE_PREVIEW_PATH_CACHE.get(cache_key)
            if cached_preview_path:
                cached_path = Path(cached_preview_path)
                try:
                    if cached_path.is_file() and cached_path.stat().st_size > 0:
                        _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
                        preview_cache[local_key] = cached_preview_path
                        continue
                except OSError:
                    pass
                _MODEL_TEXTURE_PREVIEW_PATH_CACHE.pop(cache_key, None)
        normalized_requests.append((texture_entry, slot_key, resolved_max_dimension, local_key, cache_key))

    if not normalized_requests:
        return

    jobs: List[Dict[str, object]] = []
    by_source: Dict[str, Tuple[str, Tuple[object, ...]]] = {}
    for texture_entry, slot_key, resolved_max_dimension, local_key, cache_key in normalized_requests:
        raise_if_cancelled(stop_event)
        try:
            texture_source_path, _texture_note = ensure_archive_preview_source(texture_entry, stop_event=stop_event)
            source_key = str(texture_source_path.expanduser().resolve())
        except RunCancelled:
            raise
        except OSError:
            continue
        except Exception:
            continue
        jobs.append(
            {
                "dds_path": source_key,
                "slot_kind": slot_key,
                "max_dimension": resolved_max_dimension,
                "normal_space": "opengl" if slot_key == "normal" else "auto",
                "srgb": "auto",
            }
        )
        by_source[source_key] = (local_key, cache_key)

    if not jobs:
        return

    try:
        timeout_seconds = max(10.0, min(180.0, 4.0 + (len(jobs) * 4.0)))
        results = ensure_directxtex_dds_preview_pngs(jobs, timeout_seconds=timeout_seconds)
    except RunCancelled:
        raise
    except Exception:
        return
    for source_key, preview_path in results.items():
        mapped = by_source.get(str(source_key))
        if mapped is None:
            try:
                mapped = by_source.get(str(Path(source_key).expanduser().resolve()))
            except OSError:
                mapped = None
        if mapped is None:
            continue
        local_key, cache_key = mapped
        preview_path_text = str(preview_path)
        preview_cache[local_key] = preview_path_text
        with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE[cache_key] = preview_path_text
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
            while len(_MODEL_TEXTURE_PREVIEW_PATH_CACHE) > _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT:
                _MODEL_TEXTURE_PREVIEW_PATH_CACHE.popitem(last=False)


def _model_preview_sidecar_tint(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[float, float, float]:
    tint = tuple(getattr(binding, "tint_color", ()) or ())
    if len(tint) < 3:
        tint = tuple(getattr(binding, "represent_color", ()) or ())
    if len(tint) >= 3:
        return (
            max(0.0, min(2.0, float(tint[0]))),
            max(0.0, min(2.0, float(tint[1]))),
            max(0.0, min(2.0, float(tint[2]))),
        )
    return ()


def _model_preview_sidecar_uv_scale(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[float, float]:
    try:
        uv_scale = float(getattr(binding, "uv_scale", 1.0) or 1.0)
    except (TypeError, ValueError):
        uv_scale = 1.0
    uv_scale = max(0.05, min(64.0, uv_scale))
    if abs(uv_scale - 1.0) <= 1e-6:
        return ()
    return (uv_scale, uv_scale)


def _model_preview_sidecar_material_color(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[float, float, float]:
    color = _model_preview_sidecar_tint(binding)
    if len(color) < 3:
        return ()
    try:
        red = max(0.0, min(1.0, float(color[0])))
        green = max(0.0, min(1.0, float(color[1])))
        blue = max(0.0, min(1.0, float(color[2])))
    except (TypeError, ValueError):
        return ()
    luma = (red * 0.2126) + (green * 0.7152) + (blue * 0.0722)
    saturation = max(red, green, blue) - min(red, green, blue)
    if luma <= 0.018 and saturation <= 0.035:
        return ()
    return (red, green, blue)


def _is_low_authority_model_base_texture(texture_path: str) -> bool:
    normalized = _normalize_model_texture_reference(texture_path)
    if not normalized:
        return False
    if _is_placeholder_model_texture(normalized):
        return True
    basename = PurePosixPath(normalized).name.lower()
    stem = PurePosixPath(normalized).stem.lower()
    if "common_default" in stem and "overlay" in stem:
        return True
    if stem in {"cd_common_default_overlay", "cd_common_default_overlay_old"}:
        return True
    if stem.endswith("_o") or "_overlay" in stem:
        return True
    return False


def _model_preview_base_texture_quality(texture_path: str, *, fallback_only: bool = False) -> str:
    if fallback_only:
        return "material_color_fallback"
    if _is_low_authority_model_base_texture(texture_path):
        return "low_authority_overlay"
    normalized = _normalize_model_texture_reference(texture_path)
    return "resolved_base" if normalized else ""


def _mesh_preview_base_is_low_authority(mesh: ModelPreviewMesh) -> bool:
    quality = str(getattr(mesh, "preview_base_texture_quality", "") or "").strip().lower()
    if quality == "low_authority_overlay":
        return True
    texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
    return _is_low_authority_model_base_texture(texture_name)


def _mesh_existing_base_is_sidecar_identity(
    mesh: ModelPreviewMesh,
    parsed_submesh: Optional[object],
    binding: _ArchiveModelSidecarTextureBinding,
) -> bool:
    sidecar_candidates = _iter_model_submesh_reference_candidates(
        str(getattr(binding, "submesh_name", "") or ""),
        str(getattr(binding, "part_name", "") or ""),
        str(getattr(binding, "material_name", "") or ""),
    )
    if not sidecar_candidates:
        return False
    sidecar_candidate_set = set(sidecar_candidates)
    mesh_candidates = _iter_model_submesh_reference_candidates(
        str(getattr(parsed_submesh, "name", "") or ""),
        str(getattr(parsed_submesh, "material", "") or ""),
        str(getattr(parsed_submesh, "texture", "") or ""),
        str(getattr(mesh, "material_name", "") or ""),
        str(getattr(mesh, "texture_name", "") or ""),
    )
    return any(candidate in sidecar_candidate_set for candidate in mesh_candidates)


def _apply_model_sidecar_base_preview(
    mesh: ModelPreviewMesh,
    *,
    texture_entry: ArchiveEntry,
    preview_path_text: str,
    binding: _ArchiveModelSidecarTextureBinding,
    force_unflipped_preview: bool,
    set_texture_name: bool,
) -> None:
    if str(getattr(mesh, "preview_texture_path", "") or "").strip() != preview_path_text:
        mesh.preview_texture_path = preview_path_text
        mesh.preview_texture_image = None
    if force_unflipped_preview:
        mesh.preview_texture_flip_vertical = False
    current_texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
    if set_texture_name or not current_texture_name or not current_texture_name.lower().endswith(".dds"):
        mesh.texture_name = texture_entry.path
    _append_model_preview_material_input(
        mesh,
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name=str(getattr(binding, "parameter_name", "") or "").strip(),
            source_texture_path=texture_entry.path,
            texture_name=PurePosixPath(texture_entry.path.replace("\\", "/")).name,
            preview_texture_path=preview_path_text,
            semantic_type="color",
            semantic_subtype="albedo",
            material_name=(
                str(getattr(binding, "material_name", "") or "").strip()
                or str(getattr(binding, "submesh_name", "") or "").strip()
                or str(getattr(mesh, "material_name", "") or "").strip()
            ),
            part_name=str(getattr(binding, "part_name", "") or "").strip(),
            shader_family=str(getattr(binding, "shader_family", "") or "").strip(),
            confidence="sidecar",
            visualized=True,
            sidecar_kind=str(getattr(binding, "sidecar_kind", "") or "").strip(),
            sidecar_path=str(getattr(binding, "sidecar_path", "") or "").strip(),
            linked_mesh_path=str(getattr(binding, "linked_mesh_path", "") or "").strip(),
            material_parameters=tuple(getattr(binding, "material_parameters", ()) or ()),
        ),
    )
    current_material_name = str(getattr(mesh, "material_name", "") or "").strip()
    sidecar_material_name = str(getattr(binding, "submesh_name", "") or "").strip()
    if sidecar_material_name and not current_material_name:
        mesh.material_name = sidecar_material_name
    mesh.preview_base_texture_source = str(getattr(binding, "sidecar_kind", "") or "sidecar").strip() or "sidecar"
    mesh.preview_sidecar_material_primitive = (
        str(getattr(binding, "material_name", "") or "").strip()
        or str(getattr(binding, "part_name", "") or "").strip()
        or sidecar_material_name
    )
    mesh.preview_sidecar_shader_family = str(getattr(binding, "shader_family", "") or "").strip()
    try:
        mesh.preview_texture_brightness = max(0.1, min(3.0, float(getattr(binding, "brightness", 1.0) or 1.0)))
    except (TypeError, ValueError):
        mesh.preview_texture_brightness = 1.0
    mesh.preview_texture_tint = _model_preview_sidecar_tint(binding)
    mesh.preview_texture_uv_scale = _model_preview_sidecar_uv_scale(binding)
    material_color = _model_preview_sidecar_material_color(binding)
    low_authority_base = _is_low_authority_model_base_texture(texture_entry.path)
    mesh.preview_base_texture_quality = _model_preview_base_texture_quality(texture_entry.path)
    if material_color:
        mesh.preview_color = material_color
    if (
        mesh.preview_texture_tint
        or mesh.preview_texture_uv_scale
        or abs(float(mesh.preview_texture_brightness or 1.0) - 1.0) > 1e-6
    ):
        mesh.preview_texture_approximation_note = "Sidecar tint, brightness, and UV scale are preview approximations."
    if low_authority_base and material_color:
        mesh.preview_texture_approximation_note = (
            "Sidecar material color drives visible preview color; the resolved DDS is a low-detail overlay/default layer."
        )


def _attach_model_sidecar_texture_preview_paths(
    texconv_path: Optional[Path],
    source_entry: ArchiveEntry,
    model_preview: Optional[ModelPreviewData],
    *,
    parsed_mesh: Optional[object],
    sidecar_texture_bindings: Sequence[_ArchiveModelSidecarTextureBinding],
    visible_texture_mode: str = "mesh_base_first",
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
    fallback_only: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> List[str]:
    if texconv_path is None or model_preview is None or not model_preview.meshes or not sidecar_texture_bindings:
        return []

    parsed_submeshes = _iter_parsed_model_submeshes(parsed_mesh)
    resolved_texconv_path = texconv_path.expanduser().resolve()
    normalized_visible_texture_mode = _normalize_model_visible_texture_mode(visible_texture_mode)
    allowed_visible_classes = set(_allowed_model_sidecar_visible_classes(normalized_visible_texture_mode))
    resolved_by_submesh: Dict[str, Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]] = {}
    global_visible_bindings: List[Tuple[ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]] = []
    fallback_visible_bindings: List[
        Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]
    ] = []
    material_color_by_submesh: Dict[
        str,
        Tuple[Tuple[int, int, int, int], Tuple[float, float, float], _ArchiveModelSidecarTextureBinding],
    ] = {}
    global_material_colors: List[Tuple[Tuple[int, int, int, int], Tuple[float, float, float], _ArchiveModelSidecarTextureBinding]] = []
    seen_fallback_binding_keys: set[Tuple[str, str, str]] = set()
    seen_global_binding_keys: set[Tuple[str, str]] = set()
    seen_global_color_keys: set[Tuple[float, float, float, str, str]] = set()
    sidecar_paths: List[str] = []
    promoted_anonymous_fallback = False
    force_unflipped_preview = str(getattr(source_entry, "extension", "") or "").lower() == ".pac"
    preview_cache: Dict[str, str] = {}

    def _preview_path_for_entry(texture_entry: ArchiveEntry, *, slot_kind: str = "base") -> str:
        slot_key = str(slot_kind or "base").strip().lower()
        cache_key = f"{_normalize_model_texture_reference(texture_entry.path)}|{slot_key}"
        preview_path_text = preview_cache.get(cache_key, "")
        if preview_path_text:
            return preview_path_text
        preview_path_text = _ensure_archive_model_texture_preview_path(
            resolved_texconv_path,
            texture_entry,
            slot_kind=slot_key,
            stop_event=stop_event,
        )
        preview_cache[cache_key] = preview_path_text
        return preview_path_text

    for binding in sidecar_texture_bindings:
        raise_if_cancelled(stop_event)
        submesh_keys = _iter_model_sidecar_binding_submesh_keys(binding)
        color_binding_class = _classify_model_sidecar_visible_binding(binding.parameter_name, binding.texture_path)
        material_color = _model_preview_sidecar_material_color(binding)
        if material_color:
            color_priority = (
                _model_sidecar_visible_class_priority(color_binding_class),
                1 if color_binding_class != "technical" else 0,
                1 if str(getattr(binding, "tint_color", "") or "") else 0,
                -len(str(getattr(binding, "texture_path", "") or "")),
            )
            if submesh_keys:
                for submesh_key in submesh_keys:
                    existing_color = material_color_by_submesh.get(submesh_key)
                    if existing_color is None or color_priority > existing_color[0]:
                        material_color_by_submesh[submesh_key] = (color_priority, material_color, binding)
            else:
                global_color_key = (
                    material_color[0],
                    material_color[1],
                    material_color[2],
                    str(getattr(binding, "material_name", "") or "").strip().lower(),
                    str(getattr(binding, "part_name", "") or "").strip().lower(),
                )
                if global_color_key not in seen_global_color_keys:
                    seen_global_color_keys.add(global_color_key)
                    global_material_colors.append((color_priority, material_color, binding))
        texture_entry, resolution_status = _resolve_model_texture_archive_entry(
            source_entry,
            binding.texture_path,
            binding.submesh_name,
            texture_entries_by_normalized_path,
            texture_entries_by_basename,
            semantic_hint=binding.parameter_name,
            expand_family_candidates=False,
            allow_technical_match=True,
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
        )
        if texture_entry is None or resolution_status != "resolved":
            continue
        candidate_normalized_path = normalize_texture_reference_for_sidecar_lookup(texture_entry.path)
        sidecar_texts = tuple(sidecar_texts_by_normalized_path.get(candidate_normalized_path, ())) if (
            sidecar_texts_by_normalized_path is not None and candidate_normalized_path
        ) else ()
        if not sidecar_texts and sidecar_texts_by_basename is not None:
            sidecar_texts = tuple(
                sidecar_texts_by_basename.get(PurePosixPath(texture_entry.path.replace("\\", "/")).name.lower(), ())
            )
        texture_type, semantic_subtype, confidence = _resolve_model_texture_semantics(texture_entry.path)
        if sidecar_texts:
            texture_type, semantic_subtype, confidence = _resolve_model_texture_semantics(
                texture_entry.path,
                sidecar_texts=sidecar_texts,
            )
        if not _is_visible_model_texture_type(texture_type):
            continue
        binding_class = _classify_model_sidecar_visible_binding(binding.parameter_name, texture_entry.path)
        if binding_class not in allowed_visible_classes:
            continue
        priority = _model_texture_hint_priority(binding.parameter_name) or _model_texture_semantic_priority(
            texture_type,
            semantic_subtype,
        )
        candidate_key = (
            _model_sidecar_visible_class_priority(binding_class),
            priority[0],
            priority[1],
            confidence,
            -len(texture_entry.path),
        )
        fallback_binding_key = (
            _normalize_model_texture_reference(texture_entry.path),
            str(binding.parameter_name or "").strip().lower(),
            _normalize_model_submesh_reference(binding.submesh_name),
        )
        if fallback_binding_key not in seen_fallback_binding_keys:
            seen_fallback_binding_keys.add(fallback_binding_key)
            fallback_visible_bindings.append(
                (
                    candidate_key,
                    texture_entry,
                    binding.parameter_name,
                    binding.submesh_name,
                    binding,
                )
            )
        if submesh_keys:
            for submesh_key in submesh_keys:
                existing = resolved_by_submesh.get(submesh_key)
                if existing is None or candidate_key > existing[0]:
                    resolved_by_submesh[submesh_key] = (
                        candidate_key,
                        texture_entry,
                        binding.parameter_name,
                        binding.submesh_name,
                        binding,
                    )
        else:
            global_key = (
                _normalize_model_texture_reference(texture_entry.path),
                str(binding.parameter_name or "").strip().lower(),
            )
            if global_key not in seen_global_binding_keys:
                seen_global_binding_keys.add(global_key)
                global_visible_bindings.append((texture_entry, binding.parameter_name, binding.submesh_name, binding))
        if binding.sidecar_path and binding.sidecar_path not in sidecar_paths:
            sidecar_paths.append(binding.sidecar_path)

    prefetch_requests: List[Tuple[ArchiveEntry, str, int]] = []
    for _candidate_key, texture_entry, _parameter_name, _submesh_name, _binding in resolved_by_submesh.values():
        prefetch_requests.append((texture_entry, "base", int(_MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)))
    mesh_count = max(1, len(tuple(getattr(model_preview, "meshes", ()) or ())))
    for texture_entry, _parameter_name, _submesh_name, _binding in global_visible_bindings[:mesh_count]:
        prefetch_requests.append((texture_entry, "base", int(_MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)))
    fallback_prefetch_limit = max(mesh_count * 2, 8)
    for _candidate_key, texture_entry, _parameter_name, _submesh_name, _binding in sorted(
        fallback_visible_bindings,
        key=lambda item: item[0],
        reverse=True,
    )[:fallback_prefetch_limit]:
        prefetch_requests.append((texture_entry, "base", int(_MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)))
    _prefetch_archive_model_texture_preview_paths(
        resolved_texconv_path,
        prefetch_requests,
        preview_cache,
        stop_event=stop_event,
    )

    assigned_count = 0
    identity_override_count = 0
    low_authority_layer_override_count = 0
    unresolved_meshes: List[ModelPreviewMesh] = []
    unresolved_mesh_indices_by_id: Dict[int, int] = {}
    ordered_anonymous_fallback_count = 0

    def _best_non_low_authority_fallback_for_mesh(
        candidate_keys: Sequence[str],
    ) -> Optional[Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]]:
        if not candidate_keys:
            return None
        candidate_key_set = set(candidate_keys)
        best_item: Optional[
            Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]
        ] = None
        for fallback_item in fallback_visible_bindings:
            texture_entry = fallback_item[1]
            if _is_low_authority_model_base_texture(texture_entry.path):
                continue
            binding = fallback_item[4]
            binding_keys = _iter_model_sidecar_binding_submesh_keys(binding)
            if not binding_keys or not any(binding_key in candidate_key_set for binding_key in binding_keys):
                continue
            if best_item is None or fallback_item[0] > best_item[0]:
                best_item = fallback_item
        return best_item

    def _mesh_reference_candidates_for_index(mesh_index: int, mesh: ModelPreviewMesh) -> Tuple[str, ...]:
        parsed_submesh = parsed_submeshes[mesh_index] if 0 <= mesh_index < len(parsed_submeshes) else None
        return _iter_model_submesh_reference_candidates(
            str(getattr(parsed_submesh, "name", "") or ""),
            str(getattr(parsed_submesh, "material", "") or ""),
            str(getattr(parsed_submesh, "texture", "") or ""),
            str(getattr(mesh, "material_name", "") or ""),
            str(getattr(mesh, "texture_name", "") or ""),
        )

    def _mesh_preview_identity_is_anonymous(mesh_index: int, mesh: ModelPreviewMesh) -> bool:
        candidate_keys = _mesh_reference_candidates_for_index(mesh_index, mesh)
        return not candidate_keys or all(_is_anonymous_model_submesh_reference_key(candidate_key) for candidate_key in candidate_keys)

    for mesh_index, mesh in enumerate(model_preview.meshes):
        raise_if_cancelled(stop_event)
        existing_preview_path = str(getattr(mesh, "preview_texture_path", "") or "").strip()
        parsed_submesh = parsed_submeshes[mesh_index] if mesh_index < len(parsed_submeshes) else None
        candidate_keys = _mesh_reference_candidates_for_index(mesh_index, mesh)
        best_match: Optional[Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding]] = None
        for candidate_key_text in candidate_keys:
            resolved = resolved_by_submesh.get(candidate_key_text)
            if resolved is None:
                continue
            if best_match is None or resolved[0] > best_match[0]:
                best_match = resolved
        promoted_low_authority_layer = False
        if fallback_only and existing_preview_path and _mesh_preview_base_is_low_authority(mesh):
            better_layer_match = _best_non_low_authority_fallback_for_mesh(candidate_keys)
            if better_layer_match is not None:
                best_match = better_layer_match
                promoted_low_authority_layer = True
        if best_match is None:
            if not existing_preview_path:
                unresolved_meshes.append(mesh)
                unresolved_mesh_indices_by_id[id(mesh)] = mesh_index
            continue
        _candidate_key, texture_entry, _parameter_name, submesh_name, binding = best_match
        if existing_preview_path:
            if fallback_only and not promoted_low_authority_layer:
                continue
            if not promoted_low_authority_layer and not _mesh_existing_base_is_sidecar_identity(mesh, parsed_submesh, binding):
                continue
        try:
            preview_path_text = _preview_path_for_entry(texture_entry)
            _apply_model_sidecar_base_preview(
                mesh,
                texture_entry=texture_entry,
                preview_path_text=preview_path_text,
                binding=binding,
                force_unflipped_preview=force_unflipped_preview,
                set_texture_name=bool(existing_preview_path),
            )
            if existing_preview_path and _normalize_model_texture_reference(existing_preview_path) != _normalize_model_texture_reference(preview_path_text):
                if promoted_low_authority_layer:
                    low_authority_layer_override_count += 1
                    mesh.preview_texture_approximation_note = (
                        "Sidecar visible layer texture is used over a low-detail overlay/default base for preview."
                    )
                else:
                    identity_override_count += 1
            assigned_count += 1
        except RunCancelled:
            raise
        except Exception:
            continue

    if unresolved_meshes and fallback_visible_bindings:
        ordered_keys: Dict[str, int] = {}
        best_fallback_by_key: Dict[
            str,
            Tuple[Tuple[int, int, int, int, int], ArchiveEntry, str, str, _ArchiveModelSidecarTextureBinding],
        ] = {}
        for fallback_item in fallback_visible_bindings:
            binding = fallback_item[4]
            sidecar_key = ""
            for raw_value in (
                str(getattr(binding, "submesh_name", "") or ""),
                str(getattr(binding, "part_name", "") or ""),
                str(getattr(binding, "material_name", "") or ""),
            ):
                sidecar_key = _normalize_model_submesh_reference(raw_value)
                if sidecar_key:
                    break
            if not sidecar_key:
                continue
            ordered_keys.setdefault(sidecar_key, len(ordered_keys))
            existing = best_fallback_by_key.get(sidecar_key)
            if existing is None or fallback_item[0] > existing[0]:
                best_fallback_by_key[sidecar_key] = fallback_item
        ordered_fallbacks = [
            best_fallback_by_key[key]
            for key, _order in sorted(ordered_keys.items(), key=lambda item: item[1])
            if key in best_fallback_by_key
        ]
        if len(ordered_fallbacks) > 1:
            for mesh in unresolved_meshes:
                raise_if_cancelled(stop_event)
                if str(getattr(mesh, "preview_texture_path", "") or "").strip():
                    continue
                mesh_index = unresolved_mesh_indices_by_id.get(id(mesh), -1)
                if mesh_index < 0 or mesh_index >= len(ordered_fallbacks):
                    continue
                _candidate_key, texture_entry, _parameter_name, _submesh_name, binding = ordered_fallbacks[mesh_index]
                try:
                    preview_path_text = _preview_path_for_entry(texture_entry)
                    _apply_model_sidecar_base_preview(
                        mesh,
                        texture_entry=texture_entry,
                        preview_path_text=preview_path_text,
                        binding=binding,
                        force_unflipped_preview=force_unflipped_preview,
                        set_texture_name=False,
                    )
                    assigned_count += 1
                    ordered_anonymous_fallback_count += 1
                except RunCancelled:
                    raise
                except Exception:
                    continue

    if not global_visible_bindings and unresolved_meshes and fallback_visible_bindings:
        unresolved_meshes_are_anonymous = all(
            _mesh_preview_identity_is_anonymous(unresolved_mesh_indices_by_id.get(id(mesh), -1), mesh)
            for mesh in unresolved_meshes
        )
        unique_named_sidecar_submeshes = {
            _normalize_model_submesh_reference(submesh_name)
            for _candidate_key, _texture_entry, _parameter_name, submesh_name, _binding in fallback_visible_bindings
            if _normalize_model_submesh_reference(submesh_name)
        }
        unique_named_sidecar_submeshes_all = {
            sidecar_key
            for binding in sidecar_texture_bindings
            for sidecar_key in _iter_model_sidecar_binding_submesh_keys(binding)[:1]
            if sidecar_key
        }
        should_promote_fallback = (
            len(model_preview.meshes) == 1
            or (
                unresolved_meshes_are_anonymous
                and (
                    len(unresolved_meshes) == 1
                    or len(parsed_submeshes) <= 1
                    or (len(unique_named_sidecar_submeshes) == 1 and len(unique_named_sidecar_submeshes_all) <= 1)
                )
            )
        )
        if should_promote_fallback:
            fallback_visible_bindings.sort(key=lambda item: item[0], reverse=True)
            _candidate_key, texture_entry, parameter_name, submesh_name, binding = fallback_visible_bindings[0]
            global_visible_bindings.append((texture_entry, parameter_name, submesh_name, binding))
            promoted_anonymous_fallback = True

    if global_visible_bindings and unresolved_meshes:
        if len(global_visible_bindings) == 1:
            texture_entry, _parameter_name, submesh_name, binding = global_visible_bindings[0]
            for mesh in unresolved_meshes:
                raise_if_cancelled(stop_event)
                if str(getattr(mesh, "preview_texture_path", "") or "").strip():
                    continue
                try:
                    preview_path_text = _preview_path_for_entry(texture_entry)
                    _apply_model_sidecar_base_preview(
                        mesh,
                        texture_entry=texture_entry,
                        preview_path_text=preview_path_text,
                        binding=binding,
                        force_unflipped_preview=force_unflipped_preview,
                        set_texture_name=False,
                    )
                    assigned_count += 1
                except RunCancelled:
                    raise
                except Exception:
                    continue
        else:
            binding_index = 0
            for mesh in unresolved_meshes:
                raise_if_cancelled(stop_event)
                if str(getattr(mesh, "preview_texture_path", "") or "").strip():
                    continue
                if binding_index >= len(global_visible_bindings):
                    break
                texture_entry, _parameter_name, submesh_name, binding = global_visible_bindings[binding_index]
                binding_index += 1
                try:
                    preview_path_text = _preview_path_for_entry(texture_entry)
                    _apply_model_sidecar_base_preview(
                        mesh,
                        texture_entry=texture_entry,
                        preview_path_text=preview_path_text,
                        binding=binding,
                        force_unflipped_preview=force_unflipped_preview,
                        set_texture_name=False,
                    )
                    assigned_count += 1
                except RunCancelled:
                    raise
                except Exception:
                    continue

    material_color_fallback_count = 0
    if material_color_by_submesh or global_material_colors:
        sorted_global_material_colors = [
            item for item in sorted(global_material_colors, key=lambda item: item[0], reverse=True)
        ]
        global_color_index = 0
        for mesh_index, mesh in enumerate(model_preview.meshes):
            raise_if_cancelled(stop_event)
            existing_preview_color = tuple(getattr(mesh, "preview_color", ()) or ())
            existing_preview_path = str(getattr(mesh, "preview_texture_path", "") or "").strip()
            parsed_submesh = parsed_submeshes[mesh_index] if mesh_index < len(parsed_submeshes) else None
            candidate_keys = _iter_model_submesh_reference_candidates(
                str(getattr(parsed_submesh, "name", "") or ""),
                str(getattr(parsed_submesh, "material", "") or ""),
                str(getattr(parsed_submesh, "texture", "") or ""),
                str(getattr(mesh, "material_name", "") or ""),
                str(getattr(mesh, "texture_name", "") or ""),
            )
            best_color: Optional[
                Tuple[Tuple[int, int, int, int], Tuple[float, float, float], _ArchiveModelSidecarTextureBinding]
            ] = None
            for candidate_key_text in candidate_keys:
                color_item = material_color_by_submesh.get(candidate_key_text)
                if color_item is not None and (best_color is None or color_item[0] > best_color[0]):
                    best_color = color_item
            if best_color is None and sorted_global_material_colors:
                if len(sorted_global_material_colors) == 1:
                    best_color = sorted_global_material_colors[0]
                elif not existing_preview_path and global_color_index < len(sorted_global_material_colors):
                    best_color = sorted_global_material_colors[global_color_index]
                    global_color_index += 1
            if best_color is None:
                continue
            _color_priority, material_color, _binding = best_color
            should_assign_color = (
                len(existing_preview_color) < 3
                or not existing_preview_path
                or _is_low_authority_model_base_texture(str(getattr(mesh, "texture_name", "") or ""))
            )
            if not should_assign_color:
                continue
            if tuple(existing_preview_color[:3]) != tuple(material_color):
                mesh.preview_color = material_color
                if not existing_preview_path:
                    mesh.preview_base_texture_quality = "material_color_fallback"
                material_color_fallback_count += 1
                if not existing_preview_path:
                    mesh.preview_texture_approximation_note = (
                        "Sidecar material color is used because no exact visible base DDS preview was resolved."
                    )

    if assigned_count <= 0:
        if material_color_fallback_count <= 0:
            return []
        return [
            f"Applied {material_color_fallback_count:,} sidecar material color fallback(s) for meshes without a reliable visible base DDS."
        ]
    sidecar_suffix = f" from {', '.join(sidecar_paths[:2])}" if sidecar_paths else ""
    if len(sidecar_paths) > 2:
        sidecar_suffix += " ..."
    info_lines = [
        (
            f"Applied {assigned_count:,} textured preview fallback binding(s) from companion material sidecar data{sidecar_suffix}."
            if fallback_only
            else f"Applied {assigned_count:,} textured preview binding(s) from companion material sidecar data{sidecar_suffix}."
        )
    ]
    if promoted_anonymous_fallback:
        info_lines.append(
            "Used a sidecar texture fallback because the recovered mesh preview did not preserve a reliable submesh/material name match."
        )
    if ordered_anonymous_fallback_count > 0:
        info_lines.append(
            f"Matched {ordered_anonymous_fallback_count:,} anonymous mesh texture preview(s) to ordered sidecar material wrapper(s)."
        )
    if identity_override_count > 0:
        info_lines.append(
            f"Selected {identity_override_count:,} sidecar base texture preview(s) over embedded material primitive/identity name(s)."
        )
    if low_authority_layer_override_count > 0:
        info_lines.append(
            f"Promoted {low_authority_layer_override_count:,} sidecar visible layer texture preview(s) over low-detail overlay/default base(s)."
        )
    if material_color_fallback_count > 0:
        info_lines.append(
            f"Applied {material_color_fallback_count:,} sidecar material color fallback(s) where the visible base DDS was missing or low confidence."
        )
    return info_lines


def _attach_model_texture_preview_paths(
    texconv_path: Optional[Path],
    source_entry: ArchiveEntry,
    model_preview: Optional[ModelPreviewData],
    *,
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
    override_existing_base: bool = False,
    prefer_material_name_for_base: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> List[str]:
    if texconv_path is None or model_preview is None or not model_preview.meshes:
        return []

    resolved_texconv_path = texconv_path.expanduser().resolve()
    preview_cache: Dict[str, str] = {}
    resolved_count = 0
    unresolved_lookup_count = 0
    technical_skip_count = 0
    preview_failure_count = 0
    sidecar_bound_count = 0
    override_count = 0
    unresolved_lookup_names: List[str] = []
    technical_skip_names: List[str] = []
    preview_failure_names: List[str] = []
    force_unflipped_preview = str(getattr(source_entry, "extension", "") or "").lower() == ".pac"

    for mesh in model_preview.meshes:
        raise_if_cancelled(stop_event)
        existing_preview_path = str(getattr(mesh, "preview_texture_path", "") or "").strip()
        if override_existing_base and str(getattr(mesh, "preview_base_texture_source", "") or "").strip().lower() in {
            "pami",
            "pac_xml",
            "sidecar",
            "pamlod_xml",
            "pam_xml",
        }:
            continue
        if existing_preview_path and not override_existing_base:
            resolved_count += 1
            sidecar_bound_count += 1
            continue
        texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        material_name = str(getattr(mesh, "material_name", "") or "").strip()
        lookup_texture_name = texture_name
        lookup_material_name = material_name
        if override_existing_base and prefer_material_name_for_base and material_name and not material_name.lower().endswith(".dds"):
            lookup_texture_name = ""
            lookup_material_name = material_name
        texture_label = lookup_texture_name or lookup_material_name
        if not texture_label:
            continue

        texture_entry, resolution_status = _resolve_model_texture_archive_entry(
            source_entry,
            lookup_texture_name,
            lookup_material_name,
            texture_entries_by_normalized_path,
            texture_entries_by_basename,
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
        )
        if texture_entry is None:
            if resolution_status == "technical_only":
                technical_skip_count += 1
                if texture_label not in technical_skip_names and len(technical_skip_names) < 5:
                    technical_skip_names.append(texture_label)
            else:
                unresolved_lookup_count += 1
                if texture_label not in unresolved_lookup_names and len(unresolved_lookup_names) < 5:
                    unresolved_lookup_names.append(texture_label)
            continue

        cache_key = _normalize_model_texture_reference(texture_entry.path)
        preview_path_text = preview_cache.get(cache_key, "")
        if not preview_path_text:
            try:
                preview_path_text = _ensure_archive_model_texture_preview_path(
                    resolved_texconv_path,
                    texture_entry,
                    stop_event=stop_event,
                )
                preview_cache[cache_key] = preview_path_text
            except RunCancelled:
                raise
            except Exception:
                preview_failure_count += 1
                if texture_label not in preview_failure_names and len(preview_failure_names) < 5:
                    preview_failure_names.append(texture_label)
                continue

        if str(getattr(mesh, "preview_texture_path", "") or "").strip() != preview_path_text:
            mesh.preview_texture_path = preview_path_text
            mesh.preview_texture_image = None
        mesh.preview_base_texture_quality = _model_preview_base_texture_quality(texture_entry.path)
        if force_unflipped_preview:
            mesh.preview_texture_flip_vertical = False
        current_texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        if override_existing_base or not current_texture_name or not current_texture_name.lower().endswith(".dds"):
            mesh.texture_name = texture_entry.path
        if not str(getattr(mesh, "preview_base_texture_source", "") or "").strip():
            mesh.preview_base_texture_source = "embedded mesh"
        _append_model_preview_material_input(
            mesh,
            PreviewMaterialTextureInput(
                slot_kind="base",
                source_texture_path=texture_entry.path,
                texture_name=PurePosixPath(texture_entry.path.replace("\\", "/")).name,
                preview_texture_path=preview_path_text,
                semantic_type="color",
                semantic_subtype="albedo",
                material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                confidence=str(getattr(mesh, "preview_base_texture_source", "") or "embedded mesh").strip(),
                visualized=True,
            ),
        )
        if (
            existing_preview_path
            and override_existing_base
            and _normalize_model_texture_reference(existing_preview_path)
            != _normalize_model_texture_reference(preview_path_text)
        ):
            override_count += 1
        resolved_count += 1

    info_lines: List[str] = []
    if resolved_count > 0:
        if override_count > 0:
            info_lines.append(
                f"Corrected {override_count:,} mesh base texture preview(s) so embedded material names override sidecar overlay/detail fallback."
            )
        elif override_existing_base:
            pass
        elif sidecar_bound_count > 0 and sidecar_bound_count >= resolved_count:
            info_lines.append(
                f"Resolved {resolved_count:,} mesh texture preview(s) for textured shading and export using sidecar-aware material bindings."
            )
        elif sidecar_bound_count > 0:
            info_lines.append(
                f"Resolved {resolved_count:,} mesh texture preview(s) for textured shading and export "
                f"({sidecar_bound_count:,} via sidecar-aware bindings, remaining matches via semantic base-color fallback)."
            )
        else:
            info_lines.append(
                f"Resolved {resolved_count:,} mesh texture preview(s) for textured shading and export using semantic base-color selection only."
            )
    if unresolved_lookup_count > 0 and not override_existing_base:
        lookup_suffix = f" Examples: {', '.join(unresolved_lookup_names)}." if unresolved_lookup_names else ""
        info_lines.append(
            f"{unresolved_lookup_count:,} embedded material base name(s) had no direct visible DDS match; "
            f"sidecar layer bindings may still provide a preview fallback.{lookup_suffix}"
        )
    if technical_skip_count > 0 and not override_existing_base:
        technical_suffix = f" Examples: {', '.join(technical_skip_names)}." if technical_skip_names else ""
        info_lines.append(
            f"{technical_skip_count:,} mesh texture reference(s) were skipped because only technical DDS matches were found.{technical_suffix}"
        )
    if preview_failure_count > 0:
        failure_suffix = f" Examples: {', '.join(preview_failure_names)}." if preview_failure_names else ""
        info_lines.append(
            f"{preview_failure_count:,} resolved texture(s) failed during DDS-to-PNG preview generation.{failure_suffix}"
        )
    return info_lines


def _attach_model_support_texture_preview_paths(
    texconv_path: Optional[Path],
    source_entry: ArchiveEntry,
    model_preview: Optional[ModelPreviewData],
    *,
    parsed_mesh: Optional[object] = None,
    sidecar_texture_bindings: Sequence[_ArchiveModelSidecarTextureBinding] = (),
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
    support_slots: Sequence[str] = ("normal", "material", "height"),
    stop_event: Optional[threading.Event] = None,
) -> List[str]:
    if texconv_path is None or model_preview is None or not model_preview.meshes:
        return []

    parsed_submeshes = _iter_parsed_model_submeshes(parsed_mesh)
    resolved_texconv_path = texconv_path.expanduser().resolve()
    preview_cache: Dict[str, str] = {}
    requested_support_slots = {
        str(slot or "").strip().lower()
        for slot in (support_slots or ())
    }
    support_slots = tuple(
        slot
        for slot in ("normal", "material", "height")
        if slot in requested_support_slots
    )
    if not support_slots:
        return []
    slot_labels = {
        "normal": "normal-map",
        "material": "material-mask",
        "height": "height/displacement",
    }
    exact_assigned_by_slot: Dict[str, int] = {slot: 0 for slot in support_slots}
    fallback_assigned_by_slot: Dict[str, int] = {slot: 0 for slot in support_slots}
    exact_examples: Dict[str, List[str]] = {slot: [] for slot in support_slots}
    fallback_examples: Dict[str, List[str]] = {slot: [] for slot in support_slots}
    exact_sidecar_paths: List[str] = []
    force_unflipped_preview = str(getattr(source_entry, "extension", "") or "").lower() == ".pac"
    slot_hints = (
        ("normal", "normal"),
        ("material", "material"),
        ("height", "height"),
    )
    ordered_support_keys_by_slot: Dict[str, Dict[str, int]] = {slot: {} for slot in support_slots}
    ordered_anonymous_assigned_by_slot: Dict[str, int] = {slot: 0 for slot in support_slots}

    def _lookup_sidecar_texts(texture_path: str) -> Tuple[str, ...]:
        normalized_path = normalize_texture_reference_for_sidecar_lookup(texture_path)
        if sidecar_texts_by_normalized_path is not None and normalized_path:
            sidecar_texts = tuple(sidecar_texts_by_normalized_path.get(normalized_path, ()))
            if sidecar_texts:
                return sidecar_texts
        if sidecar_texts_by_basename is not None:
            basename = PurePosixPath(texture_path.replace("\\", "/")).name.lower()
            if basename:
                return tuple(sidecar_texts_by_basename.get(basename, ()))
        return ()

    def _preview_path_for_entry(texture_entry: ArchiveEntry, *, slot_kind: str = "base") -> str:
        slot_key = str(slot_kind or "base").strip().lower()
        cache_key = f"{_normalize_model_texture_reference(texture_entry.path)}|{slot_key}"
        preview_path_text = preview_cache.get(cache_key, "")
        if preview_path_text:
            return preview_path_text
        preview_path_text = _ensure_archive_model_texture_preview_path(
            resolved_texconv_path,
            texture_entry,
            max_dimension=_MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION,
            slot_kind=slot_key,
            stop_event=stop_event,
        )
        preview_cache[cache_key] = preview_path_text
        return preview_path_text

    def _record_slot_example(target: Dict[str, List[str]], slot_name: str, texture_path: str) -> None:
        examples = target[slot_name]
        basename = PurePosixPath(texture_path.replace("\\", "/")).name
        if basename and basename not in examples and len(examples) < 3:
            examples.append(basename)

    def _assign_support_slot(
        mesh: ModelPreviewMesh,
        slot_name: str,
        texture_entry: ArchiveEntry,
        *,
        semantic_hint: str,
    ) -> bool:
        preview_path_text = _preview_path_for_entry(texture_entry, slot_kind=slot_name)
        semantic_type = ""
        semantic_subtype = ""
        packed_channels: Tuple[str, ...] = ()
        if slot_name == "material":
            sidecar_texts = _lookup_sidecar_texts(texture_entry.path)
            semantic_type, semantic_subtype, _confidence, packed_channels = _resolve_model_texture_semantic_details(
                texture_entry.path,
                sidecar_texts=sidecar_texts,
            )
            semantic_type, semantic_subtype = _refine_model_texture_semantic_from_hint(
                semantic_type,
                semantic_subtype,
                semantic_hint,
            )
        changed = _set_model_preview_texture_slot(
            mesh,
            slot=slot_name,
            preview_path=preview_path_text,
            texture_path=texture_entry.path,
            normal_strength=(
                _infer_model_preview_normal_strength(
                    base_texture_path=str(getattr(mesh, "texture_name", "") or "").strip(),
                    normal_texture_path=texture_entry.path,
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    semantic_hint=semantic_hint,
                    prefer_stronger=False,
                )
                if slot_name == "normal"
                else None
            ),
            semantic_type=semantic_type,
            semantic_subtype=semantic_subtype,
            packed_channels=packed_channels,
        )
        if changed and force_unflipped_preview:
            mesh.preview_texture_flip_vertical = False
        return changed

    exact_resolved_by_submesh: Dict[Tuple[str, str], Tuple[Tuple[int, int, int, int], ArchiveEntry, str, str]] = {}
    exact_material_inputs_by_submesh: Dict[str, List[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding]]] = defaultdict(list)
    exact_global_bindings: Dict[str, List[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, str]]] = defaultdict(list)
    seen_exact_global_keys: set[Tuple[str, str, str]] = set()
    preserved_extra_material_input_count = 0
    culled_extra_material_input_count = 0

    def _remember_exact_material_input(
        submesh_key: str,
        candidate_key: Tuple[int, int, int, int],
        texture_entry: ArchiveEntry,
        parameter_name: str,
        binding: _ArchiveModelSidecarTextureBinding,
    ) -> None:
        normalized_submesh_key = str(submesh_key or "").strip()
        if not normalized_submesh_key:
            return
        normalized_texture = _normalize_model_texture_reference(texture_entry.path)
        normalized_parameter = str(parameter_name or "").strip().lower()
        bucket = exact_material_inputs_by_submesh[normalized_submesh_key]
        for _existing_key, existing_entry, existing_parameter, _existing_binding in bucket:
            if (
                _normalize_model_texture_reference(existing_entry.path) == normalized_texture
                and str(existing_parameter or "").strip().lower() == normalized_parameter
            ):
                return
        bucket.append((candidate_key, texture_entry, parameter_name, binding))

    def _append_exact_material_input(
        mesh: ModelPreviewMesh,
        texture_entry: ArchiveEntry,
        parameter_name: str,
        binding: _ArchiveModelSidecarTextureBinding,
    ) -> bool:
        preview_path_text = _preview_path_for_entry(texture_entry, slot_kind="material")
        sidecar_texts = _lookup_sidecar_texts(texture_entry.path)
        semantic_type, semantic_subtype, _confidence, packed_channels = _resolve_model_texture_semantic_details(
            texture_entry.path,
            sidecar_texts=sidecar_texts,
        )
        semantic_type, semantic_subtype = _refine_model_texture_semantic_from_hint(
            semantic_type,
            semantic_subtype,
            parameter_name,
        )
        return _append_model_preview_material_input(
            mesh,
            PreviewMaterialTextureInput(
                slot_kind="material",
                parameter_name=str(parameter_name or "").strip(),
                source_texture_path=texture_entry.path,
                texture_name=PurePosixPath(texture_entry.path.replace("\\", "/")).name,
                preview_texture_path=preview_path_text,
                semantic_type=str(semantic_type or "material").strip().lower(),
                semantic_subtype=str(semantic_subtype or "").strip().lower(),
                packed_channels=tuple(
                    str(channel or "").strip().lower()
                    for channel in packed_channels
                    if str(channel or "").strip()
                ),
                material_name=(
                    str(getattr(binding, "material_name", "") or "").strip()
                    or str(getattr(binding, "submesh_name", "") or "").strip()
                    or str(getattr(mesh, "material_name", "") or "").strip()
                ),
                part_name=str(getattr(binding, "part_name", "") or "").strip(),
                shader_family=str(getattr(binding, "shader_family", "") or "").strip(),
                confidence="sidecar-exact",
                visualized=True,
                sidecar_kind=str(getattr(binding, "sidecar_kind", "") or "").strip(),
                sidecar_path=str(getattr(binding, "sidecar_path", "") or "").strip(),
                linked_mesh_path=str(getattr(binding, "linked_mesh_path", "") or "").strip(),
                material_parameters=tuple(getattr(binding, "material_parameters", ()) or ()),
            ),
        )

    def _material_input_preserve_group(parameter_name: str, texture_path: str) -> str:
        parameter_key = re.sub(r"[^a-z0-9]+", "", str(parameter_name or "").lower())
        stem = PurePosixPath(str(texture_path or "").replace("\\", "/")).stem.lower()
        if any(token in parameter_key for token in ("layerbasecolor", "detaildiffuse", "grimediffuse", "damageblendingdiffuse")):
            return "visible_layer"
        if any(token in parameter_key for token in ("basecolor", "overlaycolor")):
            return "visible_base"
        if "colorblendingmask" in parameter_key or stem.endswith("_ma") or stem.endswith("_mask"):
            return "mask"
        if "detailmask" in parameter_key or stem.endswith("_mg"):
            return "detail_mask"
        if "specular" in parameter_key or stem.endswith("_sp"):
            return "specular"
        if "grime" in parameter_key:
            return "grime"
        if "damage" in parameter_key:
            return "damage"
        if "skin" in parameter_key:
            return "skin"
        if "material" in parameter_key or stem.endswith("_m"):
            return "material"
        return "other"

    def _preserve_visible_material_input(parameter_name: str) -> bool:
        parameter_key = re.sub(r"[^a-z0-9]+", "", str(parameter_name or "").lower())
        return any(
            token in parameter_key
            for token in (
                "layerbasecolor",
                "detaildiffuse",
                "grimediffuse",
                "damageblendingdiffuse",
                "overlaycolor",
                "basecolor",
            )
        )

    def _candidate_material_input_identity(
        candidate: Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding]
    ) -> Tuple[str, str]:
        _candidate_key, texture_entry, parameter_name, _binding = candidate
        return (
            _normalize_model_texture_reference(texture_entry.path),
            str(parameter_name or "").strip().lower(),
        )

    def _select_rich_material_input_candidates(
        candidates: Sequence[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding]]
    ) -> Tuple[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding], ...]:
        if not candidates:
            return ()
        limit = 5
        ordered = sorted(candidates, key=lambda item: item[0], reverse=True)
        selected: List[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding]] = []
        selected_identities: set[Tuple[str, str]] = set()
        selected_groups: set[str] = set()
        for candidate in ordered:
            _candidate_key, texture_entry, parameter_name, _binding = candidate
            group = _material_input_preserve_group(parameter_name, texture_entry.path)
            identity = _candidate_material_input_identity(candidate)
            if identity in selected_identities or group in selected_groups:
                continue
            selected.append(candidate)
            selected_identities.add(identity)
            selected_groups.add(group)
            if len(selected) >= limit:
                return tuple(selected)
        for candidate in ordered:
            identity = _candidate_material_input_identity(candidate)
            if identity in selected_identities:
                continue
            selected.append(candidate)
            selected_identities.add(identity)
            if len(selected) >= limit:
                break
        return tuple(selected)

    for binding in sidecar_texture_bindings:
        raise_if_cancelled(stop_event)
        parameter_name = str(binding.parameter_name or "").strip()
        slot_name = _infer_model_preview_texture_slot("", semantic_hint=parameter_name)
        preserve_visible_input = slot_name == "base" and _preserve_visible_material_input(parameter_name)
        if slot_name not in support_slots and not preserve_visible_input:
            continue
        submesh_keys = _iter_model_sidecar_binding_submesh_keys(binding)
        texture_entry, resolution_status = _resolve_model_texture_archive_entry(
            source_entry,
            binding.texture_path,
            binding.submesh_name,
            texture_entries_by_normalized_path,
            texture_entries_by_basename,
            semantic_hint=parameter_name,
            expand_family_candidates=False,
            allow_technical_match=True,
            preferred_slot=slot_name,
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
        )
        if texture_entry is None or resolution_status != "resolved":
            continue
        sidecar_texts = _lookup_sidecar_texts(texture_entry.path)
        texture_type, semantic_subtype, confidence = _resolve_model_texture_semantics(
            texture_entry.path,
            sidecar_texts=sidecar_texts,
        )
        if preserve_visible_input:
            slot_priority = (8, 0)
        else:
            slot_priority = (
                _model_texture_slot_hint_priority(slot_name, parameter_name)
                or _model_texture_candidate_slot_priority(slot_name, texture_entry.path, sidecar_texts=sidecar_texts)
            )
        if slot_priority is None:
            continue
        candidate_key = (
            slot_priority[0],
            slot_priority[1],
            confidence,
            -len(texture_entry.path),
        )
        if submesh_keys:
            primary_sidecar_key = submesh_keys[0]
            if primary_sidecar_key:
                ordered_support_keys_by_slot.setdefault(slot_name, {}).setdefault(
                    primary_sidecar_key,
                    len(ordered_support_keys_by_slot.setdefault(slot_name, {})),
                )
            for submesh_key in submesh_keys:
                resolved_key = (slot_name, submesh_key)
                if slot_name == "material" or preserve_visible_input:
                    _remember_exact_material_input(
                        submesh_key,
                        candidate_key,
                        texture_entry,
                        parameter_name,
                        binding,
                    )
                if preserve_visible_input:
                    continue
                existing = exact_resolved_by_submesh.get(resolved_key)
                if existing is None or candidate_key > existing[0]:
                    exact_resolved_by_submesh[resolved_key] = (
                        candidate_key,
                        texture_entry,
                        parameter_name,
                        binding.submesh_name,
                )
        else:
            if preserve_visible_input:
                continue
            global_key = (
                slot_name,
                _normalize_model_texture_reference(texture_entry.path),
                parameter_name.lower(),
            )
            if global_key not in seen_exact_global_keys:
                seen_exact_global_keys.add(global_key)
                exact_global_bindings[slot_name].append(
                    (
                        candidate_key,
                        texture_entry,
                        parameter_name,
                        binding.submesh_name,
                    )
                )
        if binding.sidecar_path and binding.sidecar_path not in exact_sidecar_paths:
            exact_sidecar_paths.append(binding.sidecar_path)

    support_prefetch_requests: List[Tuple[ArchiveEntry, str, int]] = []
    support_max_dimension = int(_MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)
    for (slot_name, _submesh_key), (_candidate_key, texture_entry, _parameter_name, _submesh_name) in exact_resolved_by_submesh.items():
        support_prefetch_requests.append((texture_entry, slot_name, support_max_dimension))
    for slot_name, bindings in exact_global_bindings.items():
        for _candidate_key, texture_entry, _parameter_name, _submesh_name in bindings:
            support_prefetch_requests.append((texture_entry, slot_name, support_max_dimension))
    for candidates in exact_material_inputs_by_submesh.values():
        for _candidate_key, texture_entry, _parameter_name, _binding in _select_rich_material_input_candidates(candidates):
            support_prefetch_requests.append((texture_entry, "material", support_max_dimension))
    _prefetch_archive_model_texture_preview_paths(
        resolved_texconv_path,
        support_prefetch_requests,
        preview_cache,
        stop_event=stop_event,
    )

    for mesh_index, mesh in enumerate(model_preview.meshes):
        raise_if_cancelled(stop_event)
        parsed_submesh = parsed_submeshes[mesh_index] if mesh_index < len(parsed_submeshes) else None
        candidate_keys = _iter_model_submesh_reference_candidates(
            str(getattr(parsed_submesh, "name", "") or ""),
            str(getattr(parsed_submesh, "material", "") or ""),
            str(getattr(parsed_submesh, "texture", "") or ""),
            str(getattr(mesh, "material_name", "") or ""),
            str(getattr(mesh, "texture_name", "") or ""),
        )
        seen_rich_material_keys: set[Tuple[str, str]] = set()
        rich_material_candidates: List[
            Tuple[Tuple[int, int, int, int], ArchiveEntry, str, _ArchiveModelSidecarTextureBinding]
        ] = []
        for candidate_key_text in candidate_keys:
            for _candidate_key, texture_entry, parameter_name, binding in sorted(
                exact_material_inputs_by_submesh.get(candidate_key_text, ()),
                key=lambda item: item[0],
                reverse=True,
            ):
                rich_key = (
                    _normalize_model_texture_reference(texture_entry.path),
                    str(parameter_name or "").strip().lower(),
                )
                if rich_key in seen_rich_material_keys:
                    continue
                seen_rich_material_keys.add(rich_key)
                rich_material_candidates.append((_candidate_key, texture_entry, parameter_name, binding))
        selected_rich_material_candidates = _select_rich_material_input_candidates(rich_material_candidates)
        culled_extra_material_input_count += max(
            0,
            len(rich_material_candidates) - len(selected_rich_material_candidates),
        )
        for _candidate_key, texture_entry, parameter_name, binding in selected_rich_material_candidates:
            try:
                if _append_exact_material_input(mesh, texture_entry, parameter_name, binding):
                    preserved_extra_material_input_count += 1
            except RunCancelled:
                raise
            except Exception:
                continue
        for slot_name in support_slots:
            existing_preview_path = str(getattr(mesh, f"preview_{slot_name}_texture_path", "") or "").strip()
            if existing_preview_path:
                continue
            best_match: Optional[Tuple[Tuple[int, int, int, int], ArchiveEntry, str, str]] = None
            for candidate_key_text in candidate_keys:
                resolved = exact_resolved_by_submesh.get((slot_name, candidate_key_text))
                if resolved is None:
                    continue
                if best_match is None or resolved[0] > best_match[0]:
                    best_match = resolved
            if best_match is None:
                continue
            _candidate_key, texture_entry, parameter_name, _submesh_name = best_match
            try:
                if _assign_support_slot(mesh, slot_name, texture_entry, semantic_hint=parameter_name):
                    exact_assigned_by_slot[slot_name] += 1
                    _record_slot_example(exact_examples, slot_name, texture_entry.path)
            except RunCancelled:
                raise
            except Exception:
                continue

    for slot_name in support_slots:
        ordered_keys = ordered_support_keys_by_slot.get(slot_name, {})
        if len(ordered_keys) <= 1:
            continue
        ordered_bindings = [
            exact_resolved_by_submesh.get((slot_name, key))
            for key, _order in sorted(ordered_keys.items(), key=lambda item: item[1])
        ]
        if not any(ordered_bindings):
            continue
        for mesh_index, mesh in enumerate(model_preview.meshes):
            raise_if_cancelled(stop_event)
            existing_preview_path = str(getattr(mesh, f"preview_{slot_name}_texture_path", "") or "").strip()
            if existing_preview_path or mesh_index >= len(ordered_bindings):
                continue
            ordered_binding = ordered_bindings[mesh_index]
            if ordered_binding is None:
                continue
            _candidate_key, texture_entry, parameter_name, _submesh_name = ordered_binding
            try:
                if _assign_support_slot(mesh, slot_name, texture_entry, semantic_hint=parameter_name):
                    exact_assigned_by_slot[slot_name] += 1
                    ordered_anonymous_assigned_by_slot[slot_name] += 1
                    _record_slot_example(exact_examples, slot_name, texture_entry.path)
            except RunCancelled:
                raise
            except Exception:
                continue

    for slot_name in support_slots:
        global_bindings = exact_global_bindings.get(slot_name, [])
        if not global_bindings:
            continue
        global_bindings.sort(key=lambda item: item[0], reverse=True)
        unresolved_meshes = [
            mesh
            for mesh in model_preview.meshes
            if not str(getattr(mesh, f"preview_{slot_name}_texture_path", "") or "").strip()
        ]
        if not unresolved_meshes:
            continue
        if len(global_bindings) == 1:
            _candidate_key, texture_entry, parameter_name, _submesh_name = global_bindings[0]
            for mesh in unresolved_meshes:
                raise_if_cancelled(stop_event)
                try:
                    if _assign_support_slot(mesh, slot_name, texture_entry, semantic_hint=parameter_name):
                        exact_assigned_by_slot[slot_name] += 1
                        _record_slot_example(exact_examples, slot_name, texture_entry.path)
                except RunCancelled:
                    raise
                except Exception:
                    continue
        else:
            binding_index = 0
            for mesh in unresolved_meshes:
                raise_if_cancelled(stop_event)
                if binding_index >= len(global_bindings):
                    break
                _candidate_key, texture_entry, parameter_name, _submesh_name = global_bindings[binding_index]
                binding_index += 1
                try:
                    if _assign_support_slot(mesh, slot_name, texture_entry, semantic_hint=parameter_name):
                        exact_assigned_by_slot[slot_name] += 1
                        _record_slot_example(exact_examples, slot_name, texture_entry.path)
                except RunCancelled:
                    raise
                except Exception:
                    continue

    for mesh in model_preview.meshes:
        raise_if_cancelled(stop_event)
        reference_texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        reference_material_name = str(getattr(mesh, "material_name", "") or "").strip()
        if not reference_texture_name and not reference_material_name:
            continue
        for slot_name, semantic_hint in slot_hints:
            existing_preview_path = str(getattr(mesh, f"preview_{slot_name}_texture_path", "") or "").strip()
            if existing_preview_path:
                continue
            texture_entry, resolution_status = _resolve_model_texture_archive_entry(
                source_entry,
                reference_texture_name,
                reference_material_name,
                texture_entries_by_normalized_path,
                texture_entries_by_basename,
                semantic_hint=semantic_hint,
                allow_technical_match=True,
                preferred_slot=slot_name,
                sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                sidecar_texts_by_basename=sidecar_texts_by_basename,
            )
            if texture_entry is None or resolution_status != "resolved":
                continue
            try:
                if _assign_support_slot(mesh, slot_name, texture_entry, semantic_hint=semantic_hint):
                    fallback_assigned_by_slot[slot_name] += 1
                    _record_slot_example(fallback_examples, slot_name, texture_entry.path)
            except RunCancelled:
                raise
            except Exception:
                continue

    info_lines: List[str] = []
    exact_total = sum(exact_assigned_by_slot.values())
    fallback_total = sum(fallback_assigned_by_slot.values())
    if exact_total > 0:
        sidecar_suffix = f" from {', '.join(exact_sidecar_paths[:2])}" if exact_sidecar_paths else ""
        if len(exact_sidecar_paths) > 2:
            sidecar_suffix += " ..."
        info_lines.append(
            f"Applied {exact_total:,} exact high-quality support-map binding(s) from companion material sidecar data{sidecar_suffix}."
        )
        for slot_name in support_slots:
            count = exact_assigned_by_slot[slot_name]
            if count <= 0:
                continue
            suffix = f" Examples: {', '.join(exact_examples[slot_name])}." if exact_examples[slot_name] else ""
            info_lines.append(
                f"Exact sidecar {slot_labels[slot_name]} bindings: {count:,}.{suffix}"
            )
    if preserved_extra_material_input_count > 0:
        info_lines.append(
            f"Preserved {preserved_extra_material_input_count:,} exact sidecar material texture input(s) for material diagnostics and preview."
        )
    if culled_extra_material_input_count > 0:
        info_lines.append(
            f"Skipped {culled_extra_material_input_count:,} lower-priority sidecar material texture input(s) before preview conversion to keep model loading responsive."
        )
    ordered_total = sum(ordered_anonymous_assigned_by_slot.values())
    if ordered_total > 0:
        ordered_parts = [
            f"{slot_name[0]}:{ordered_anonymous_assigned_by_slot[slot_name]:,}"
            for slot_name in support_slots
            if ordered_anonymous_assigned_by_slot[slot_name] > 0
        ]
        info_lines.append(
            "Matched "
            f"{ordered_total:,} anonymous support-map binding(s) to ordered sidecar material wrapper(s)"
            + (f" ({', '.join(ordered_parts)})." if ordered_parts else ".")
        )
    if fallback_total > 0:
        info_lines.append(
            f"Applied {fallback_total:,} semantic sibling high-quality support-map binding(s) using slot-correct family fallback."
        )
        for slot_name in support_slots:
            count = fallback_assigned_by_slot[slot_name]
            if count <= 0:
                continue
            suffix = f" Examples: {', '.join(fallback_examples[slot_name])}." if fallback_examples[slot_name] else ""
            info_lines.append(
                f"Semantic sibling {slot_labels[slot_name]} bindings: {count:,}.{suffix}"
            )
    if exact_total <= 0 and fallback_total <= 0:
        has_textured_mesh = any(
            str(getattr(mesh, "texture_name", "") or "").strip()
            or str(getattr(mesh, "preview_texture_path", "") or "").strip()
            for mesh in model_preview.meshes
        )
        if has_textured_mesh:
            info_lines.append(
                "No usable high-quality support maps were resolved from exact sidecar bindings or semantic sibling fallback. The preview remains base-texture only."
            )
    return info_lines


def _describe_model_texture_semantic_label(
    texture_path: str,
    *,
    semantic_hint: str = "",
    sidecar_texts: Sequence[str] = (),
) -> str:
    hint_label = _humanize_model_texture_hint(semantic_hint)
    if hint_label:
        return hint_label
    texture_type_raw, subtype_raw, _confidence = _resolve_model_texture_semantics(
        texture_path,
        sidecar_texts=sidecar_texts,
    )
    texture_type = str(texture_type_raw or "").strip().replace("_", " ")
    subtype = str(subtype_raw or "").strip().replace("_", " ")
    if not texture_type or texture_type.lower() == "unknown":
        return hint_label
    hint_priority = _model_texture_hint_priority(semantic_hint)
    if hint_label and hint_priority is not None and hint_priority[0] >= 5 and texture_type.lower() not in {"color", "ui", "emissive"}:
        return hint_label
    if subtype and subtype.lower() not in {"unknown", texture_type.lower()}:
        return f"{texture_type.title()} / {subtype.title()}"
    return texture_type.title()


def _describe_model_related_file_label(entry: ArchiveEntry) -> str:
    extension = str(entry.extension or "").strip().lower()
    path = str(entry.path or "").replace("\\", "/").lower()
    basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
    if extension == ".pam":
        return "Companion PAM"
    if extension == ".pamlod":
        return "Companion PAMLOD"
    if extension == ".pac":
        return "Companion PAC"
    if extension == ".pab":
        return "Companion PAB"
    if extension == ".pabc":
        return "Skeleton Variation"
    if extension == ".papr":
        return "Animation Constraint"
    if "prefabdata" in basename or extension == ".prefabdata_xml":
        return "Prefab Metadata"
    if extension == ".pami":
        return "Material Variant Sidecar"
    if _is_material_sidecar_extension(extension, basename):
        return "Material Sidecar"
    if extension == ".xml":
        return "Companion XML"
    if extension in {".hkx", ".hkt"}:
        label = extension.lstrip(".").upper()
        if any(token in path for token in ("meshphysics", "havokphysics", "ragdoll", "physics")):
            return f"Physics {label}"
        return f"Companion {label}"
    if extension == ".meshinfo":
        return "Companion MeshInfo"
    if extension == ".pappt":
        return "Part Prefab Metadata"
    if extension == ".pamhc":
        return "Model Property Header"
    if extension == ".paa":
        return "Companion PAA"
    if extension == ".paa_metabin":
        return "Animation Metadata"
    if extension == ".motionblending":
        return "Motion Blending"
    if extension in {".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
        return "Animation Metadata"
    if extension == ".seqmt":
        return "Sequence Texture Metadata"
    if extension in {".pae", ".paem"}:
        return "Companion Effect"
    if extension:
        return f"Companion {extension.lstrip('.').upper()}"
    return "Related File"


def _merge_model_reference_semantic_label(
    existing_label: str,
    new_label: str,
    *,
    existing_hint: str = "",
    new_hint: str = "",
) -> str:
    current = str(existing_label or "").strip()
    incoming = str(new_label or "").strip()
    if not current:
        return incoming
    if not incoming or incoming == current:
        return current
    if not str(existing_hint or "").strip() and str(new_hint or "").strip():
        return incoming
    if str(existing_hint or "").strip() and not str(new_hint or "").strip():
        return current
    parts = [part.strip() for part in current.split(" | ") if part.strip()]
    if incoming not in parts:
        parts.append(incoming)
    return " | ".join(parts)


def _model_reference_status_rank(status: str) -> int:
    normalized = str(status or "").strip().lower()
    if normalized == "resolved":
        return 3
    if normalized == "technical_only":
        return 2
    return 1


def _texture_reference_relation_metadata(
    source_entry: ArchiveEntry,
    reference_name: str,
    resolved_entry: Optional[ArchiveEntry],
    *,
    semantic_hint: str = "",
) -> Tuple[str, str]:
    if not isinstance(resolved_entry, ArchiveEntry):
        return (
            RelationConfidence.AUTHORITATIVE.value if semantic_hint else RelationConfidence.DERIVED_SAME_STEM.value,
            "Sidecar texture binding" if semantic_hint else "Resolved texture family",
        )
    normalized_reference = normalize_texture_reference_for_sidecar_lookup(reference_name)
    normalized_resolved = normalize_texture_reference_for_sidecar_lookup(resolved_entry.path)
    mismatch_reason = _archive_texture_family_mismatch_reason(source_entry, resolved_entry) if semantic_hint else ""
    if normalized_reference and normalized_reference == normalized_resolved:
        if mismatch_reason:
            return RelationConfidence.EXACT_PATH.value, f"Exact sidecar path; {mismatch_reason}"
        return RelationConfidence.EXACT_PATH.value, "Exact archive path"
    if (
        normalized_reference
        and normalized_resolved
        and PurePosixPath(normalized_reference).name == PurePosixPath(normalized_resolved).name
        and source_entry.pamt_path.parent != resolved_entry.pamt_path.parent
    ):
        return RelationConfidence.CROSS_PACKAGE.value, "Cross-package texture reference"
    if normalized_reference and normalized_resolved and normalized_reference.lstrip("/") == normalized_resolved.lstrip("/"):
        if mismatch_reason:
            return RelationConfidence.PATH_NORMALIZED.value, f"Path-normalized sidecar path; {mismatch_reason}"
        return RelationConfidence.PATH_NORMALIZED.value, "Path-normalized texture reference"
    if semantic_hint:
        if mismatch_reason:
            return RelationConfidence.AUTHORITATIVE.value, f"Sidecar texture binding; {mismatch_reason}"
        return RelationConfidence.AUTHORITATIVE.value, "Sidecar texture binding"
    return RelationConfidence.DERIVED_SAME_STEM.value, "Resolved texture family"


def build_archive_model_texture_references(
    source_entry: ArchiveEntry,
    model_preview: Optional[ModelPreviewData],
    *,
    parsed_mesh: Optional[object] = None,
    binary_texture_references: Sequence[str] = (),
    sidecar_texture_references: Sequence[_ArchiveModelSidecarTextureBinding] = (),
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
) -> List[ArchiveModelTextureReference]:
    preview_meshes = list(getattr(model_preview, "meshes", ()) or [])
    parsed_submeshes = _iter_parsed_model_submeshes(parsed_mesh)
    related_companion_entries = (
        _find_archive_model_related_entries(source_entry, texture_entries_by_basename)
        if texture_entries_by_basename is not None
        else ()
    )

    if (
        not preview_meshes
        and not parsed_submeshes
        and not binary_texture_references
        and not sidecar_texture_references
        and not related_companion_entries
    ):
        return []

    references: Dict[Tuple[str, ...], ArchiveModelTextureReference] = {}
    ordered_keys: List[Tuple[str, ...]] = []

    for related_entry in related_companion_entries:
        related_key = ("sidecar", _normalize_model_texture_reference(related_entry.path))
        if related_key in references:
            continue
        relation_kind, relation_group, relation_confidence, relation_reason = _build_archive_relation_metadata(
            source_entry,
            resolved_entry=related_entry,
        )
        references[related_key] = ArchiveModelTextureReference(
            reference_name=PurePosixPath(related_entry.path.replace("\\", "/")).name,
            semantic_label=_describe_model_related_file_label(related_entry),
            resolution_status="resolved",
            resolved_archive_path=related_entry.path,
            resolved_package_label=related_entry.package_label,
            resolved_entry=related_entry,
            usage_count=1,
            reference_kind=relation_kind,
            relation_group=relation_group,
            relation_reason=relation_reason,
            relation_confidence=relation_confidence,
        )
        ordered_keys.append(related_key)

    candidates: List[Tuple[str, str, str, str, Optional[object]]] = []
    seen_candidate_keys: set[Tuple[str, str, str]] = set()
    for binding in sidecar_texture_references:
        texture_name = str(binding.texture_path or "").strip()
        material_name = str(
            getattr(binding, "part_name", "")
            or getattr(binding, "material_name", "")
            or binding.submesh_name
            or binding.parameter_name
            or ""
        ).strip()
        semantic_hint = str(binding.parameter_name or "").strip()
        key = (
            _normalize_model_texture_reference(texture_name),
            _normalize_model_texture_reference(material_name),
            str(semantic_hint or "").strip().lower(),
        )
        if not texture_name or key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        candidates.append((texture_name, material_name, "", semantic_hint, binding))
    for mesh in preview_meshes:
        texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        material_name = str(getattr(mesh, "material_name", "") or "").strip()
        key = (
            _normalize_model_texture_reference(texture_name),
            _normalize_model_texture_reference(material_name),
            "",
        )
        seen_candidate_keys.add(key)
        candidates.append(
            (
                texture_name,
                material_name,
                str(getattr(mesh, "preview_texture_path", "") or "").strip(),
                "",
                None,
            )
        )
    for submesh in parsed_submeshes:
        texture_name = str(getattr(submesh, "texture", "") or "").strip()
        material_name = str(getattr(submesh, "material", "") or "").strip()
        key = (
            _normalize_model_texture_reference(texture_name),
            _normalize_model_texture_reference(material_name),
            "",
        )
        if key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        candidates.append((texture_name, material_name, "", "", None))
    for raw_reference in binary_texture_references:
        texture_name = str(raw_reference or "").strip()
        if not texture_name:
            continue
        key = (_normalize_model_texture_reference(texture_name), "", "")
        if key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        candidates.append((texture_name, "", "", "", None))

    for texture_name, material_name, preview_texture_path, semantic_hint, sidecar_binding in candidates:
        reference_name = texture_name or material_name
        if not reference_name:
            continue

        texture_entry, resolution_status = _resolve_model_texture_archive_entry(
            source_entry,
            texture_name,
            material_name,
            texture_entries_by_normalized_path,
            texture_entries_by_basename,
            semantic_hint=semantic_hint,
            expand_family_candidates=not _has_explicit_model_texture_reference(texture_name, material_name),
            allow_technical_match=True,
            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename=sidecar_texts_by_basename,
        )
        resolved_archive_path = texture_entry.path if texture_entry is not None else ""
        reference_key_value = _normalize_model_texture_reference(resolved_archive_path or reference_name)
        if sidecar_binding is not None:
            key = (
                "texture",
                reference_key_value,
                _normalize_model_texture_reference(material_name),
                str(semantic_hint or "").strip().lower(),
                str(getattr(sidecar_binding, "sidecar_kind", "") or "").strip().lower(),
            )
        else:
            key = ("texture", reference_key_value)
        sidecar_texts: Tuple[str, ...] = ()
        normalized_reference_path = normalize_texture_reference_for_sidecar_lookup(resolved_archive_path or reference_name)
        if sidecar_texts_by_normalized_path is not None and normalized_reference_path:
            sidecar_texts = tuple(sidecar_texts_by_normalized_path.get(normalized_reference_path, ()))
        if not sidecar_texts and sidecar_texts_by_basename is not None:
            reference_basename = PurePosixPath(
                (resolved_archive_path or reference_name).replace("\\", "/")
            ).name.lower()
            if reference_basename:
                sidecar_texts = tuple(sidecar_texts_by_basename.get(reference_basename, ()))
        semantic_label = _describe_model_texture_semantic_label(
            resolved_archive_path or reference_name,
            semantic_hint=semantic_hint,
            sidecar_texts=sidecar_texts,
        )
        sidecar_kind = str(getattr(sidecar_binding, "sidecar_kind", "") or "").strip()
        linked_mesh_path = str(getattr(sidecar_binding, "linked_mesh_path", "") or "").strip()
        part_name = str(getattr(sidecar_binding, "part_name", "") or "").strip()
        shader_family = str(getattr(sidecar_binding, "shader_family", "") or "").strip()
        texture_role = str(getattr(sidecar_binding, "texture_role", "") or "").strip()
        visualization_state = str(getattr(sidecar_binding, "visualization_state", "") or "").strip()
        resolved_package_label = texture_entry.package_label if texture_entry is not None else ""
        relation_confidence, relation_reason = _texture_reference_relation_metadata(
            source_entry,
            reference_name,
            texture_entry,
            semantic_hint=semantic_hint,
        )
        existing = references.get(key)
        if existing is None:
            references[key] = ArchiveModelTextureReference(
                reference_name=reference_name,
                material_name=material_name,
                semantic_label=semantic_label,
                semantic_hint=semantic_hint,
                sidecar_parameter_name=semantic_hint,
                sidecar_kind=sidecar_kind,
                linked_mesh_path=linked_mesh_path,
                part_name=part_name,
                shader_family=shader_family,
                texture_role=texture_role,
                visualization_state=visualization_state,
                sidecar_texts=sidecar_texts,
                resolution_status=resolution_status,
                resolved_archive_path=resolved_archive_path,
                resolved_package_label=resolved_package_label,
                resolved_entry=texture_entry,
                preview_texture_path=preview_texture_path,
                usage_count=1,
                reference_kind="texture",
                relation_group="Textures",
                relation_reason=relation_reason,
                relation_confidence=relation_confidence,
            )
            ordered_keys.append(key)
            continue

        existing.usage_count += 1
        if material_name and not existing.material_name:
            existing.material_name = material_name
        if preview_texture_path and not existing.preview_texture_path:
            existing.preview_texture_path = preview_texture_path
        if sidecar_kind and not existing.sidecar_kind:
            existing.sidecar_kind = sidecar_kind
        if linked_mesh_path and not existing.linked_mesh_path:
            existing.linked_mesh_path = linked_mesh_path
        if part_name and not existing.part_name:
            existing.part_name = part_name
        if shader_family and not existing.shader_family:
            existing.shader_family = shader_family
        if texture_role and not existing.texture_role:
            existing.texture_role = texture_role
        if visualization_state and not existing.visualization_state:
            existing.visualization_state = visualization_state
        if texture_entry is not None and (
            existing.resolved_entry is None
            or _model_reference_status_rank(resolution_status) > _model_reference_status_rank(existing.resolution_status)
        ):
            existing.resolved_entry = texture_entry
            existing.resolved_archive_path = texture_entry.path
            existing.resolved_package_label = texture_entry.package_label
            existing.resolution_status = resolution_status
        elif _model_reference_status_rank(resolution_status) > _model_reference_status_rank(existing.resolution_status):
            existing.resolution_status = resolution_status
        if semantic_label:
            existing.semantic_label = _merge_model_reference_semantic_label(
                existing.semantic_label,
                semantic_label,
                existing_hint=existing.semantic_hint,
                new_hint=semantic_hint,
            )
        if semantic_hint and semantic_hint != existing.semantic_hint:
            existing.semantic_hint = " | ".join(
                part
                for part in [existing.semantic_hint.strip(), semantic_hint.strip()]
                if part
            )
            if not existing.sidecar_parameter_name:
                existing.sidecar_parameter_name = semantic_hint
        if sidecar_texts:
            merged_sidecar_texts = list(existing.sidecar_texts)
            for text in sidecar_texts:
                if text not in merged_sidecar_texts:
                    merged_sidecar_texts.append(text)
            existing.sidecar_texts = tuple(merged_sidecar_texts)

    return [references[key] for key in ordered_keys]


def iter_archive_loose_file_candidates(
    entry: ArchiveEntry,
    search_roots: Sequence[Path],
) -> Sequence[Path]:
    pure_path = PurePosixPath(entry.path.replace("\\", "/"))
    safe_parts = [part for part in pure_path.parts if part not in {"", ".", ".."}]
    if not safe_parts:
        return []

    package_root = entry.pamt_path.parent.name.strip()
    candidates: List[Path] = []
    seen: set[str] = set()
    for root in search_roots:
        try:
            resolved_root = root.expanduser().resolve()
        except OSError:
            continue
        if not resolved_root.exists() or not resolved_root.is_dir():
            continue
        root_candidates = [resolved_root.joinpath(*safe_parts)]
        if package_root:
            root_candidates.append(resolved_root.joinpath(package_root, *safe_parts))
        for candidate in root_candidates:
            lowered = str(candidate).lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            if candidate.exists() and candidate.is_file():
                candidates.append(candidate)
    return candidates


def build_loose_archive_preview_assets(
    texconv_path: Optional[Path],
    loose_path: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[str, str, str]:
    resolved_path = loose_path.expanduser().resolve()
    suffix = resolved_path.suffix.lower()
    detail = f"Loose file preview from: {resolved_path}"
    raise_if_cancelled(stop_event)

    if suffix == ".dds":
        dds_info = None
        parse_error: Optional[Exception] = None
        try:
            dds_info = parse_dds(resolved_path)
            metadata_summary = (
                f"Loose DDS | Format: {dds_info.texconv_format} | "
                f"Size: {dds_info.width}x{dds_info.height} | Mips: {dds_info.mip_count}"
            )
        except Exception as exc:
            parse_error = exc
            metadata_summary = f"Loose DDS | {resolved_path.name}"
        if texconv_path is None:
            extra = f"\nDDS metadata unavailable: {parse_error}" if parse_error is not None else ""
            return "", metadata_summary, detail + extra + "\nSet texconv.exe to enable DDS loose-file previews."
        preview_png = ensure_dds_display_preview_png(
            texconv_path.resolve(),
            resolved_path,
            dds_info=dds_info,
            stop_event=stop_event,
        )
        if parse_error is not None:
            detail += f"\nDDS metadata unavailable: {parse_error}"
        return str(preview_png), metadata_summary, detail

    if suffix in ARCHIVE_IMAGE_EXTENSIONS:
        return str(resolved_path), f"Loose image | {resolved_path.name}", detail

    return "", f"Loose file | {resolved_path.name}", detail + "\nThis loose file type cannot be previewed as an image."


def _format_media_duration_millis(duration_ms: int) -> str:
    total_seconds = max(0, int(duration_ms // 1000))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def _runtime_search_roots() -> List[Path]:
    roots: List[Path] = []
    seen: set[str] = set()

    def add_root(candidate: Optional[Path]) -> None:
        if candidate is None:
            return
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            resolved = candidate.expanduser()
        lowered = str(resolved).lower()
        if not lowered or lowered in seen:
            return
        seen.add(lowered)
        roots.append(resolved)

    if getattr(sys, "frozen", False):
        add_root(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            add_root(Path(str(meipass)))
    add_root(Path(__file__).resolve().parents[2])
    return roots


def _resolve_vgmstream_cli_path() -> Optional[Path]:
    candidate_names = ("vgmstream-cli.exe", "test.exe")
    for root in _runtime_search_roots():
        for relative_dir in ("vgmstream", ".tools/vgmstream"):
            base_dir = root / relative_dir
            for candidate_name in candidate_names:
                candidate_path = base_dir / candidate_name
                if candidate_path.is_file():
                    return candidate_path
    return None


def _decode_wem_with_vgmstream(
    source_path: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Optional[Path], str]:
    cli_path = _resolve_vgmstream_cli_path()
    if cli_path is None:
        return None, "Bundled vgmstream decoder is not available in this build."

    output_path = source_path.with_name(f"{sanitize_cache_filename(source_path.stem)}.vgmstream.wav")
    if output_path.exists():
        try:
            if output_path.stat().st_size > 44 and output_path.stat().st_mtime_ns >= source_path.stat().st_mtime_ns:
                return output_path, "Decoded for playback with bundled vgmstream-cli."
        except OSError:
            pass

    command = [str(cli_path), "-o", str(output_path), str(source_path)]
    popen_kwargs: Dict[str, object] = {
        "cwd": str(cli_path.parent),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    popen_kwargs.update(hidden_subprocess_kwargs())
    process = subprocess.Popen(
        command,
        **popen_kwargs,
    )
    try:
        while True:
            try:
                return_code = process.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                raise_if_cancelled(stop_event)
        stderr_text = ""
        if process.stderr is not None:
            try:
                stderr_text = process.stderr.read().strip()
            except Exception:
                stderr_text = ""
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
        raise
    finally:
        if process.stderr is not None:
            try:
                process.stderr.close()
            except Exception:
                pass

    if return_code != 0 or not output_path.exists():
        return None, stderr_text or "vgmstream-cli could not decode this Wwise stream."
    return output_path, "Decoded for playback with bundled vgmstream-cli."


def _ensure_media_preview_source_path(
    source_path: Path,
    declared_extension: str,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Path, str]:
    resolved_source = source_path.expanduser().resolve()
    normalized_extension = str(declared_extension or resolved_source.suffix).strip().lower()
    if normalized_extension != ".wem":
        return resolved_source, ""

    decoded_wav_path, decode_note = _decode_wem_with_vgmstream(
        resolved_source,
        stop_event=stop_event,
    )
    if decoded_wav_path is not None:
        return decoded_wav_path, decode_note

    raise_if_cancelled(stop_event)
    try:
        with resolved_source.open("rb") as handle:
            header = handle.read(12)
    except OSError:
        return resolved_source, decode_note
    if len(header) < 12 or not header.startswith(b"RIFF") or header[8:12] != b"WAVE":
        return resolved_source, decode_note

    alias_path = resolved_source.with_suffix(".wav")
    if alias_path == resolved_source:
        return resolved_source, decode_note
    if alias_path.exists() and alias_path.stat().st_size == resolved_source.stat().st_size:
        return alias_path, decode_note

    shutil.copy2(resolved_source, alias_path)
    return alias_path, decode_note


def _iter_riff_chunks(
    data: bytes,
    *,
    max_chunks: int = 32,
) -> List[Tuple[str, int, int]]:
    chunks: List[Tuple[str, int, int]] = []
    if len(data) < 12 or not data.startswith(b"RIFF"):
        return chunks
    offset = 12
    while offset + 8 <= len(data) and len(chunks) < max_chunks:
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        chunk_name = chunk_id.decode("ascii", errors="replace")
        data_offset = offset + 8
        if data_offset > len(data):
            break
        chunks.append((chunk_name, chunk_size, data_offset))
        next_offset = data_offset + chunk_size
        if next_offset <= offset:
            break
        offset = next_offset + (chunk_size % 2)
    return chunks


def _build_wem_media_preview_detail_text(
    source_path: Path,
    data: bytes,
    *,
    loose: bool,
    playback_source_path: Optional[Path] = None,
    playback_note: str = "",
) -> Tuple[str, str]:
    resolved_source = source_path.expanduser().resolve()
    metadata_summary = f"{'Loose' if loose else 'Archive'} Wwise audio | {resolved_source.name}"
    detail_lines = [f"{'Loose file' if loose else 'Archive preview source'}: {resolved_source}"]
    if playback_source_path is not None:
        resolved_playback = playback_source_path.expanduser().resolve()
        if resolved_playback != resolved_source:
            detail_lines.append(f"Playback source: {resolved_playback}")
    if playback_note:
        detail_lines.append(playback_note)
    if len(data) < 12 or not data.startswith(b"RIFF") or data[8:12] != b"WAVE":
        detail_lines.append("Container sniffing did not confirm a RIFF/WAVE-style Wwise stream. Playback support may depend on the local multimedia backend.")
        return metadata_summary, "\n".join(detail_lines)

    detail_lines.append("Detected RIFF/WAVE-style Wwise audio container.")
    fmt_channels = None
    fmt_sample_rate = None
    fmt_bits_per_sample = None
    chunk_names: List[str] = []
    for chunk_name, chunk_size, chunk_offset in _iter_riff_chunks(data):
        chunk_names.append(f"{chunk_name} ({chunk_size:,} B)")
        if chunk_name == "fmt " and chunk_size >= 16 and chunk_offset + 16 <= len(data):
            try:
                _audio_format, fmt_channels, fmt_sample_rate, _byte_rate, _block_align, fmt_bits_per_sample = struct.unpack_from(
                    "<HHIIHH",
                    data,
                    chunk_offset,
                )
            except struct.error:
                fmt_channels = None
                fmt_sample_rate = None
                fmt_bits_per_sample = None
    if fmt_channels is not None and fmt_sample_rate is not None:
        metadata_summary = (
            f"{metadata_summary} | {fmt_channels} ch | {fmt_sample_rate:,} Hz"
            + (f" | {fmt_bits_per_sample}-bit" if fmt_bits_per_sample is not None else "")
        )
    if chunk_names:
        detail_lines.append("RIFF chunks: " + ", ".join(chunk_names[:12]))
    detail_lines.append(
        "Playback is best-effort through Qt Multimedia. Some Wwise `.wem` variants may still fail if the local backend cannot decode them."
    )
    return metadata_summary, "\n".join(detail_lines)


def _build_mp4_media_preview_detail_text(
    source_path: Path,
    *,
    loose: bool,
) -> Tuple[str, str]:
    resolved_source = source_path.expanduser().resolve()
    metadata_summary = f"{'Loose' if loose else 'Archive'} video | {resolved_source.name}"
    detail_lines = [
        f"{'Loose file' if loose else 'Archive preview source'}: {resolved_source}",
        "Embedded playback uses Qt Multimedia.",
    ]
    return metadata_summary, "\n".join(detail_lines)


def build_loose_archive_media_preview_assets(
    loose_path: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[str, str, str, str]:
    resolved_path = loose_path.expanduser().resolve()
    suffix = resolved_path.suffix.lower()
    raise_if_cancelled(stop_event)

    if suffix in ARCHIVE_VIDEO_EXTENSIONS:
        metadata_summary, detail_text = _build_mp4_media_preview_detail_text(resolved_path, loose=True)
        return str(resolved_path), "video", metadata_summary, detail_text

    if suffix in ARCHIVE_AUDIO_EXTENSIONS:
        media_source, playback_note = _ensure_media_preview_source_path(
            resolved_path,
            suffix,
            stop_event=stop_event,
        )
        try:
            with resolved_path.open("rb") as handle:
                sample = handle.read(131072)
        except OSError:
            sample = b""
        metadata_summary, detail_text = _build_wem_media_preview_detail_text(
            resolved_path,
            sample,
            loose=True,
            playback_source_path=media_source,
            playback_note=playback_note,
        )
        return str(media_source), "audio", metadata_summary, detail_text

    return "", "", f"Loose file | {resolved_path.name}", f"Loose file preview from: {resolved_path}"


def _iter_bnk_chunks(
    data: bytes,
    *,
    max_chunks: int = 32,
) -> List[Tuple[str, int, int]]:
    chunks: List[Tuple[str, int, int]] = []
    offset = 0
    while offset + 8 <= len(data) and len(chunks) < max_chunks:
        chunk_name = data[offset : offset + 4].decode("ascii", errors="replace")
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        data_offset = offset + 8
        if data_offset + chunk_size > len(data):
            break
        chunks.append((chunk_name, chunk_size, data_offset))
        next_offset = data_offset + chunk_size
        aligned_offset = (next_offset + 3) & ~3
        if aligned_offset <= offset:
            break
        offset = aligned_offset
    return chunks


def build_bnk_soundbank_preview(data: bytes) -> Tuple[str, str]:
    if len(data) < 8 or data[:4] != b"BKHD":
        return "", ""

    chunk_rows = _iter_bnk_chunks(data)
    if not chunk_rows:
        return "Detected Wwise soundbank container.", "Wwise soundbank preview is limited because the bank does not expose readable chunk boundaries."

    detail_lines = ["Detected Wwise soundbank container."]
    preview_lines = ["Wwise soundbank summary:"]
    chunk_descriptions: List[str] = []
    embedded_media_count = 0
    embedded_media_examples: List[str] = []
    hirc_object_count = None
    bank_version = None
    bank_id = None

    for chunk_name, chunk_size, chunk_offset in chunk_rows:
        chunk_descriptions.append(f"{chunk_name} ({chunk_size:,} B)")
        if chunk_name == "BKHD" and chunk_size >= 8:
            try:
                bank_version, bank_id = struct.unpack_from("<II", data, chunk_offset)
            except struct.error:
                bank_version = None
                bank_id = None
        elif chunk_name == "DIDX" and chunk_size >= 12:
            embedded_media_count = chunk_size // 12
            preview_lines.append(f"- Embedded media entries: {embedded_media_count:,}")
            for media_index in range(min(8, embedded_media_count)):
                media_id, media_offset, media_size = struct.unpack_from("<III", data, chunk_offset + media_index * 12)
                embedded_media_examples.append(
                    f"{media_id} @ {media_offset:,} ({format_byte_size(media_size)})"
                )
        elif chunk_name == "HIRC" and chunk_size >= 4:
            try:
                hirc_object_count = struct.unpack_from("<I", data, chunk_offset)[0]
            except struct.error:
                hirc_object_count = None

    if bank_version is not None:
        preview_lines.append(f"- Bank version: {bank_version}")
    if bank_id is not None:
        preview_lines.append(f"- Bank id: {bank_id}")
    preview_lines.append(f"- Top-level chunks: {', '.join(chunk_name for chunk_name, _chunk_size, _chunk_offset in chunk_rows)}")
    if hirc_object_count is not None:
        preview_lines.append(f"- HIRC objects: {hirc_object_count:,}")
    if embedded_media_examples:
        preview_lines.append("- First embedded media ids:")
        preview_lines.extend(f"  {example}" for example in embedded_media_examples)

    readable_strings = extract_binary_strings(data, sample_limit=262144, max_strings=24)
    if readable_strings:
        preview_lines.append("- Readable strings:")
        preview_lines.extend(f"  {text}" for text in readable_strings[:16])

    detail_lines.append("Top-level chunks: " + ", ".join(chunk_descriptions[:16]))
    if embedded_media_count:
        detail_lines.append(
            f"Embedded media index contains {embedded_media_count:,} item(s). These can be inspected, but direct bank playback is not exposed yet."
        )
    else:
        detail_lines.append("No embedded media index entries were detected in the top-level DIDX chunk.")

    return "\n".join(preview_lines), "\n".join(detail_lines)


def format_binary_header_preview(data: bytes) -> str:
    if not data:
        return "No bytes available."
    lines: List[str] = []
    for offset in range(0, min(len(data), ARCHIVE_BINARY_HEX_PREVIEW_LIMIT), 16):
        chunk = data[offset : offset + 16]
        hex_part = " ".join(f"{value:02X}" for value in chunk)
        ascii_part = "".join(chr(value) if 32 <= value <= 126 else "." for value in chunk)
        lines.append(f"{offset:04X}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


def try_decode_text_like_archive_data(data: bytes) -> Optional[str]:
    if not data:
        return None

    preview_bytes = data[:ARCHIVE_TEXT_PREVIEW_LIMIT]
    for bom, encoding in (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ):
        if preview_bytes.startswith(bom):
            text = preview_bytes.decode(encoding, errors="replace")
            return text if text.strip("\ufeff\r\n\t ") else None

    sample = preview_bytes[:4096]
    if not sample:
        return None
    if sample.count(0) > max(2, len(sample) // 100):
        return None

    printable_count = sum(1 for value in sample if value in (9, 10, 13) or 32 <= value <= 126)
    likely_text = printable_count / max(len(sample), 1) >= 0.92
    stripped_sample = sample.lstrip(b"\xef\xbb\xbf\r\n\t ")
    if not likely_text and not stripped_sample.startswith((b"<?xml", b"<", b"{", b"[")):
        return None

    text = preview_bytes.decode("utf-8", errors="replace")
    non_whitespace = [char for char in text[:1024] if not char.isspace()]
    if not non_whitespace:
        return None
    control_count = sum(1 for char in non_whitespace if ord(char) < 32 and char not in "\r\n\t")
    if control_count > max(2, len(non_whitespace) // 20):
        return None
    return text


def extract_binary_strings(data: bytes, *, sample_limit: int = 131_072, max_strings: int = 48) -> List[str]:
    sample = data[:sample_limit]
    strings: List[str] = []
    seen: set[str] = set()
    for match in _PRINTABLE_BINARY_STRING_RE.finditer(sample):
        text = match.group().decode("ascii", errors="ignore").strip()
        letter_count = sum(1 for char in text if char.isalpha())
        if len(text) < 4 or text in seen or letter_count == 0:
            continue
        allowed_char_count = sum(1 for char in text if char.isalnum() or char in " _./:-[](){}")
        if allowed_char_count / max(len(text), 1) < 0.85:
            continue
        if len(text) < 12 and letter_count < 4:
            continue
        if "_" not in text and "/" not in text and "::" not in text and " " not in text and len(text) < 12:
            continue
        if len(text) > 160:
            text = text[:157] + "..."
        seen.add(text)
        strings.append(text)
        if len(strings) >= max_strings:
            break
    return strings


def build_binary_strings_preview(data: bytes, *, sample_limit: int = 131_072, max_strings: int = 48) -> str:
    strings = extract_binary_strings(data, sample_limit=sample_limit, max_strings=max_strings)
    if not strings:
        return ""
    scanned_size = min(len(data), sample_limit)
    lines = [f"Readable strings from the first {format_byte_size(scanned_size)} of binary data:"]
    lines.extend(strings)
    if len(data) > sample_limit:
        lines.extend(["", "String scan truncated to keep the preview responsive."])
    return "\n".join(lines)


def _looks_like_structured_field_name(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 3 or len(text) > 128:
        return False
    if "/" in text or "\\" in text:
        return False
    if "." in text and "::" not in text:
        return False
    if " " in text or "\t" in text:
        return False
    if not _STRUCTURED_BINARY_IDENTIFIER_RE.fullmatch(text):
        return False
    return any(character.isalpha() for character in text)


def _looks_like_structured_asset_reference(value: str) -> bool:
    raw_text = str(value or "").strip().strip("\x00")
    if len(raw_text) < 3 or len(raw_text) > 255:
        return False
    normalized_text = raw_text.replace("\\", "/")
    if normalized_text.startswith("/") or normalized_text.endswith("/"):
        return False
    if "//" in normalized_text:
        return False
    suffix = PurePosixPath(normalized_text).suffix.lower()
    if suffix not in _STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS:
        return False
    segments = normalized_text.split("/")
    if not segments:
        return False
    for segment in segments:
        if not segment or not _STRUCTURED_BINARY_ASSET_SEGMENT_RE.fullmatch(segment):
            return False
    return any(character.isalpha() for character in normalized_text)


def _clean_structured_binary_asset_token(value: str) -> str:
    raw_text = str(value or "").strip().strip("\x00").replace("\\", "/")
    if _looks_like_structured_asset_reference(raw_text):
        return raw_text
    lowered = raw_text.lower()
    for extension in sorted(_STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS, key=len, reverse=True):
        marker = str(extension or "").lower()
        if not marker:
            continue
        index = lowered.rfind(marker)
        if index < 0:
            continue
        end = index + len(marker)
        suffix = lowered[end:]
        if not suffix or len(suffix) > 2 or not re.fullmatch(r"[a-z0-9]{1,2}", suffix):
            continue
        candidate = raw_text[:end]
        if _looks_like_structured_asset_reference(candidate):
            return candidate
    return raw_text


def _extract_binary_asset_references(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_references: int = 64,
) -> List[str]:
    references: List[str] = []
    seen: set[str] = set()
    for text in extract_binary_strings(data, sample_limit=sample_limit, max_strings=max(max_references * 6, 96)):
        for match in _STRUCTURED_BINARY_ASSET_TOKEN_RE.finditer(text):
            raw_text = _clean_structured_binary_asset_token(match.group(0))
            if not _looks_like_structured_asset_reference(raw_text):
                continue
            raw_text = raw_text.replace("\\", "/")
            normalized = _normalize_model_texture_reference(raw_text)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            references.append(raw_text)
            if len(references) >= max_references:
                return references
    return references


def _extract_text_asset_references(
    text: str,
    *,
    sidecar_path: str = "",
    max_references: int = 96,
) -> List[str]:
    references: List[str] = []
    seen: set[str] = set()

    def add_reference(raw_value: str) -> None:
        raw_text = str(raw_value or "").strip().strip("\x00").replace("\\", "/")
        if not _looks_like_structured_asset_reference(raw_text):
            return
        normalized = _normalize_model_texture_reference(raw_text)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        references.append(raw_text)

    for binding in parse_texture_sidecar_bindings(text, sidecar_path=sidecar_path):
        add_reference(binding.texture_path)
        if len(references) >= max_references:
            return references

    for match in _STRUCTURED_BINARY_ASSET_TOKEN_RE.finditer(text):
        add_reference(str(match.group(0) or ""))
        if len(references) >= max_references:
            return references
    return references


def _structured_field_type_hint(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "field"
    if "reflectobject" in normalized or normalized.endswith("ptr") or "referencepath" in normalized:
        return "object ref"
    if "list" in normalized or "container" in normalized or "array" in normalized:
        return "list"
    if normalized.startswith(("is", "use", "enable", "disable", "auto", "apply", "has")):
        return "bool"
    if any(token in normalized for token in ("boundingbox", "bbox", "bound", "extent", "position", "rotation", "scale", "offset", "radius")):
        return "vector"
    if normalized.endswith(("type", "enum", "flag", "flags", "layer", "group")):
        return "enum/flag"
    return "field"


def _group_meshinfo_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("boundingbox", "bbox", "bound", "extent", "volume", "radius", "min", "max")):
        return "Bounds"
    if any(token in normalized for token in ("socket", "anchor", "attach")):
        return "Sockets"
    if any(token in normalized for token in ("tree", "branch", "cutting")):
        return "Tree"
    if any(token in normalized for token in ("break", "support", "fade", "convex", "fracture")):
        return "Breakable"
    if any(token in normalized for token in ("collision", "collidable", "constraint", "group", "layer")):
        return "Collision"
    if any(token in normalized for token in ("physics", "motion", "mass", "buoyancy", "dynamic", "pbd", "wind", "material")):
        return "Physics"
    if any(token in normalized for token in ("reflectobject", "vector", "container", "custom", "gamedata", "node")):
        return "Data Model"
    return "Misc"


def _group_animation_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("skeleton", "bone", "rig")):
        return "Skeleton"
    if any(token in normalized for token in ("delaunay", "triangle", "vert", "center")):
        return "Delaunay"
    if any(token in normalized for token in ("animationfilename", "animationfile", "animationdata", "animation")):
        return "Animation Files"
    if any(token in normalized for token in ("parameter", "dimension", "minmax", "smoothing")):
        return "Parameters"
    if any(token in normalized for token in ("phase", "motion", "blend", "speed", "loop", "sync")):
        return "Motion Space"
    if any(token in normalized for token in ("animation", "clip", "frame", "curve", "track", "event")):
        return "Animation"
    if any(token in normalized for token in ("motion", "blend", "space", "parameter")):
        return "Motion / Blend"
    if any(token in normalized for token in ("emitter", "effect", "particle")):
        return "Emitter / Effect"
    if any(token in normalized for token in ("scene", "object", "node", "prefab")):
        return "Scene / Object"
    if any(token in normalized for token in ("resource", "texture", "material", "sound", "audio", "video")):
        return "Resources"
    return "Misc"


_PAA_METABIN_TOKEN_HINTS: Dict[str, Tuple[str, str]] = {
    "nor": ("Motion state", "normal"),
    "abn": ("Motion state", "abnormal / reaction"),
    "dam": ("Action", "damage / hit reaction"),
    "atk": ("Action", "attack"),
    "skill": ("Action", "skill"),
    "move": ("Motion", "movement"),
    "idle": ("Motion", "idle"),
    "std": ("Pose", "standing"),
    "sit": ("Pose", "sitting"),
    "run": ("Motion", "running"),
    "walk": ("Motion", "walking"),
    "jump": ("Motion", "jump"),
    "upper": ("Body region", "upper body"),
    "lower": ("Body region", "lower body"),
    "stt": ("Timeline phase", "start"),
    "ing": ("Timeline phase", "in progress / loop body"),
    "end": ("Timeline phase", "end"),
    "loop": ("Timeline phase", "loop"),
    "f": ("Direction", "forward"),
    "b": ("Direction", "back"),
    "l": ("Direction", "left"),
    "r": ("Direction", "right"),
    "fd": ("Direction", "forward-down"),
    "fu": ("Direction", "forward-up"),
    "cvst": ("Scene use", "conversation / cutscene-style"),
    "quest": ("Scene use", "quest sequence"),
    "camera": ("Scene use", "camera animation"),
}


def _paa_metabin_animation_stem(virtual_path: str) -> str:
    basename = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name
    lowered = basename.lower()
    if lowered.endswith(".paa_metabin"):
        return basename[: -len(".paa_metabin")]
    return PurePosixPath(basename).stem


def _paa_metabin_declared_type_name(data: bytes) -> Tuple[str, int, int]:
    if len(data) >= 0x18:
        name_length = struct.unpack_from("<I", data, 0x14)[0]
        if 0 < name_length <= 128 and 0x18 + name_length <= len(data):
            raw_name = data[0x18 : 0x18 + name_length]
            try:
                type_name = raw_name.decode("ascii", errors="strict").strip("\x00")
            except UnicodeDecodeError:
                type_name = ""
            if type_name and _looks_like_structured_field_name(type_name):
                return type_name, 0x18, int(name_length)
    for record in _extract_binary_string_records(data, sample_limit=4096, max_strings=16):
        if record.text == "AnimationMetaData":
            return record.text, record.offset, len(record.text)
    return "", 0, 0


def _paa_metabin_filename_hint_rows(virtual_path: str) -> List[Dict[str, str]]:
    stem = _paa_metabin_animation_stem(virtual_path)
    tokens = [token for token in re.split(r"[_\-.]+", stem.lower()) if token]
    rows: List[Dict[str, str]] = []
    seen: set[Tuple[str, str, str]] = set()

    def add(kind: str, token: str, meaning: str, confidence: str = "filename_token") -> None:
        key = (kind, token, meaning)
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "kind": kind,
                "token": token,
                "meaning": meaning,
                "confidence": confidence,
            }
        )

    if tokens and tokens[0] == "cd":
        add("Namespace", "cd", "Crimson Desert asset prefix", "filename_convention")
    if len(tokens) >= 2:
        add("Asset code", tokens[1], "character/object/sequence code from filename", "filename_token")
    for token in tokens:
        hint = _PAA_METABIN_TOKEN_HINTS.get(token)
        if hint is None:
            continue
        add(hint[0], token, hint[1])
    if stem:
        add("Animation stem", stem, "same-stem key used to find related animation files", "same_stem_relation_key")
    return rows


def _paa_metabin_header_rows(data: bytes) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    if len(data) >= 4:
        rows.append(
            {
                "offset": 0,
                "name": "signature_words",
                "value": f"u16[0]=0x{struct.unpack_from('<H', data, 0)[0]:04X}, u16[1]={struct.unpack_from('<H', data, 2)[0]}",
                "confidence": "stable_in_corpus",
            }
        )
    if len(data) >= 0x18:
        rows.append(
            {
                "offset": 0x14,
                "name": "declared_type_name_length",
                "value": int(struct.unpack_from("<I", data, 0x14)[0]),
                "confidence": "stable_length_prefixed_string",
            }
        )
    for offset, label in ((0x2C, "descriptor_a"), (0x30, "descriptor_b"), (0x38, "descriptor_c"), (0x44, "descriptor_count")):
        if len(data) < offset + 4:
            continue
        be_value = struct.unpack_from(">I", data, offset)[0]
        le_value = struct.unpack_from("<I", data, offset)[0]
        plausible_value = be_value if be_value <= 1_000_000 else le_value
        rows.append(
            {
                "offset": offset,
                "name": label,
                "value": plausible_value,
                "be_u32": be_value,
                "le_u32": le_value,
                "confidence": "stable_descriptor_word_observed",
            }
        )
    return rows


def _paa_metabin_packed_stream_summary(data: bytes) -> Dict[str, object]:
    stream_offset = 0x50 if len(data) > 0x50 else len(data)
    stream = data[stream_offset:]
    marker_counts = {
        f"0x{marker:02X}": int(stream.count(marker))
        for marker in (0x00, 0x01, 0x05, 0x3C, 0x80, 0xFF)
        if stream.count(marker)
    }
    preview_rows: List[Dict[str, object]] = []
    for offset in range(stream_offset, min(len(data), stream_offset + 96), 8):
        chunk = data[offset : min(len(data), offset + 8)]
        if not chunk:
            continue
        preview_rows.append(
            {
                "offset": offset,
                "hex": chunk.hex(" ").upper(),
                "u16_le": [
                    int.from_bytes(chunk[index : index + 2], "little")
                    for index in range(0, len(chunk) - 1, 2)
                ],
                "u16_be": [
                    int.from_bytes(chunk[index : index + 2], "big")
                    for index in range(0, len(chunk) - 1, 2)
                ],
                "confidence": "packed_stream_preview",
            }
        )
    return {
        "stream_offset": stream_offset,
        "stream_size": len(stream),
        "marker_counts": marker_counts,
        "preview_rows": preview_rows,
        "status": "packed_event_or_timing_stream_observed" if stream else "no_metadata_stream_bytes",
        "confidence": "stable_header_plus_experimental_payload",
    }


def _paa_metabin_analysis_document(data: bytes, virtual_path: str) -> Dict[str, object]:
    type_name, type_offset, type_length = _paa_metabin_declared_type_name(data)
    filename_hints = _paa_metabin_filename_hint_rows(virtual_path)
    stream_summary = _paa_metabin_packed_stream_summary(data)
    return {
        "declared_type": type_name or "unknown",
        "declared_type_offset": type_offset,
        "declared_type_length": type_length,
        "animation_stem": _paa_metabin_animation_stem(virtual_path),
        "filename_hints": filename_hints,
        "header_rows": _paa_metabin_header_rows(data),
        "packed_metadata_stream": stream_summary,
        "editing_supported": False,
        "relationship_use": (
            "Useful for linking animation metadata to same-stem .paa/.motionblending/.hkx style animation assets "
            "and for exposing filename-derived motion hints. The packed stream is not editable."
        ),
    }


def _extract_binary_string_records(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_strings: int = 512,
) -> List[_BinarySidecarStringRecord]:
    sample = data[:sample_limit]
    records: List[_BinarySidecarStringRecord] = []
    seen: set[str] = set()
    for match in _PRINTABLE_BINARY_STRING_RE.finditer(sample):
        text = match.group().decode("ascii", errors="ignore").strip()
        letter_count = sum(1 for char in text if char.isalpha())
        if len(text) < 4 or text in seen or letter_count == 0:
            continue
        allowed_char_count = sum(1 for char in text if char.isalnum() or char in " _./:-[](){}")
        if allowed_char_count / max(len(text), 1) < 0.85:
            continue
        if len(text) < 12 and letter_count < 4:
            continue
        if "_" not in text and "/" not in text and "::" not in text and " " not in text and len(text) < 12:
            continue
        if len(text) > 240:
            text = text[:237] + "..."
        seen.add(text)
        records.append(_BinarySidecarStringRecord(offset=match.start(), text=text))
        if len(records) >= max_strings:
            break
    return records


def _read_binary_sidecar_string_at(data: bytes, offset: int, *, limit: int = 96) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    match = _PRINTABLE_BINARY_STRING_RE.match(data[offset : min(len(data), offset + limit)])
    if match is None:
        return ""
    text = match.group().decode("ascii", errors="ignore").strip()
    if not text or sum(1 for char in text if char.isalpha()) == 0:
        return ""
    if len(text) > 96:
        text = text[:93] + "..."
    return text


def _binary_sidecar_asset_reference_rows(
    string_records: Sequence[_BinarySidecarStringRecord],
    *,
    max_references: int = 96,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen: set[str] = set()
    for record in string_records:
        for match in _STRUCTURED_BINARY_ASSET_TOKEN_RE.finditer(record.text):
            raw_text = _clean_structured_binary_asset_token(match.group(0))
            if not _looks_like_structured_asset_reference(raw_text):
                continue
            normalized = _normalize_model_texture_reference(raw_text)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            rows.append(
                {
                    "offset": record.offset + match.start(),
                    "path": raw_text,
                    "extension": PurePosixPath(raw_text).suffix.lower(),
                    "confidence": "string_path",
                }
            )
            if len(rows) >= max_references:
                return rows
    return rows


def _binary_sidecar_header_words(data: bytes, *, max_words: int = 20) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for offset in range(0, min(len(data) // 4, max_words) * 4, 4):
        value = struct.unpack_from("<I", data, offset)[0]
        rows.append(
            {
                "offset": offset,
                "le_u32": value,
                "le_i32": struct.unpack_from("<i", data, offset)[0],
                "hex": f"0x{value:08X}",
            }
        )
    return rows


def _seqmt_filename_grid_hint(virtual_path: str) -> Dict[str, object]:
    name = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name.lower()
    match = re.search(r"(?:^|_)(\d{1,3})x(\d{1,3})(?:_|\.|$)", name)
    if match is None:
        return {}
    return {
        "columns": int(match.group(1)),
        "rows": int(match.group(2)),
        "source": "filename_token",
    }


def _seqmt_analysis_document(
    data: bytes,
    virtual_path: str,
    *,
    max_frame_records: int = 96,
) -> Dict[str, object]:
    """Decode observed SEQMT DDS! sequence texture atlas metadata.

    Local corpus samples use an unaligned compact header:
    DDS!, version byte, u16 columns, u16 rows, one flag/packing byte, u16 frame count,
    then one four-byte record per frame. The four-byte record semantics are still
    read-only evidence, so expose multiple byte interpretations without naming a
    final value type.
    """

    if len(data) < 12 or data[:4] != b"DDS!":
        return {
            "recognized": False,
            "reason": "missing_DDS_sequence_magic",
            "editing_supported": False,
        }

    version = int(data[4])
    columns = int(struct.unpack_from("<H", data, 5)[0])
    rows = int(struct.unpack_from("<H", data, 7)[0])
    flags_or_packing = int(data[9])
    frame_count = int(struct.unpack_from("<H", data, 10)[0])
    payload_offset = 12
    frame_record_size = 4
    expected_frame_payload_bytes = frame_count * frame_record_size
    available_payload_bytes = max(0, len(data) - payload_offset)
    decoded_frame_bytes = min(available_payload_bytes, expected_frame_payload_bytes)
    decoded_frame_count = decoded_frame_bytes // frame_record_size
    trailing_payload_offset = payload_offset + expected_frame_payload_bytes
    trailing_payload_bytes = max(0, len(data) - trailing_payload_offset)
    grid_capacity = columns * rows
    filename_hint = _seqmt_filename_grid_hint(virtual_path)
    if filename_hint:
        filename_hint = dict(filename_hint)
        filename_hint["matches_header"] = (
            int(filename_hint.get("columns") or 0) == columns
            and int(filename_hint.get("rows") or 0) == rows
        )

    frame_records: List[Dict[str, object]] = []
    preview_count = min(decoded_frame_count, max_frame_records)
    for index in range(preview_count):
        offset = payload_offset + index * frame_record_size
        raw = data[offset : offset + frame_record_size]
        byte_values = [int(value) for value in raw]
        signed_values = [value - 256 if value >= 128 else value for value in byte_values]
        frame_records.append(
            {
                "index": index,
                "grid_x": index % columns if columns > 0 else 0,
                "grid_y": index // columns if columns > 0 else 0,
                "offset": offset,
                "hex": raw.hex(" ").upper(),
                "bytes_rgba": byte_values,
                "bytes_bgra": [byte_values[2], byte_values[1], byte_values[0], byte_values[3]]
                if len(byte_values) == 4
                else byte_values,
                "bytes_signed": signed_values,
            }
        )

    notes = [
        "Frame records are exposed as four raw bytes because the channel semantics are not proven yet.",
        "Editing is disabled until frame record meaning and rebuild rules are validated.",
    ]
    if flags_or_packing == 1:
        notes.append("The flag/packing byte is 1; local samples often use this on filenames containing 4pack.")
    if trailing_payload_bytes > 0:
        notes.append("Extra trailing payload was preserved separately from the fixed frame table.")

    return {
        "recognized": True,
        "format": "DDS_sequence_texture_metadata",
        "magic": "DDS!",
        "version": version,
        "columns": columns,
        "rows": rows,
        "grid_capacity": grid_capacity,
        "frame_count": frame_count,
        "frame_count_matches_grid": frame_count == grid_capacity,
        "flags_or_packing_byte": flags_or_packing,
        "payload_offset": payload_offset,
        "frame_record_size": frame_record_size,
        "expected_frame_payload_bytes": expected_frame_payload_bytes,
        "available_payload_bytes": available_payload_bytes,
        "decoded_frame_count": decoded_frame_count,
        "payload_complete": available_payload_bytes >= expected_frame_payload_bytes,
        "trailing_payload_offset": trailing_payload_offset if trailing_payload_bytes > 0 else None,
        "trailing_payload_bytes": trailing_payload_bytes,
        "trailing_payload_preview_hex": data[trailing_payload_offset : min(len(data), trailing_payload_offset + 64)].hex(" ").upper()
        if trailing_payload_bytes > 0
        else "",
        "filename_grid_hint": filename_hint,
        "frame_records_preview": frame_records,
        "frame_records_preview_truncated": decoded_frame_count > preview_count,
        "editing_supported": False,
        "confidence": "confirmed_on_local_seqmt_corpus_header",
        "notes": notes,
    }


def _binary_sidecar_offset_candidates(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_candidates: int = 64,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_limit = min(len(data), sample_limit)
    if scan_limit < 8:
        return rows
    for owner_offset in range(0, scan_limit - 3, 4):
        target_offset = struct.unpack_from("<I", data, owner_offset)[0]
        if target_offset <= 0 or target_offset >= len(data):
            continue
        if target_offset % 4 != 0:
            continue
        target_string = _read_binary_sidecar_string_at(data, target_offset)
        confidence = "string_target" if target_string else "aligned_in_file"
        rows.append(
            {
                "owner_offset": owner_offset,
                "target_offset": target_offset,
                "patched_slot_value": f"0x{target_offset:08X}",
                "target_preview": target_string,
                "confidence": confidence,
            }
        )
        if len(rows) >= max_candidates:
            break
    return rows


def _binary_sidecar_count_offset_pairs(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_pairs: int = 48,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_limit = min(len(data), sample_limit)
    if scan_limit < 12:
        return rows
    stride_candidates = (4, 8, 12, 16, 24, 32, 48, 64)
    for owner_offset in range(0, scan_limit - 7, 4):
        count = struct.unpack_from("<I", data, owner_offset)[0]
        target_offset = struct.unpack_from("<I", data, owner_offset + 4)[0]
        if count <= 0 or count > 1_000_000:
            continue
        if target_offset <= 0 or target_offset >= len(data) or target_offset % 4 != 0:
            continue
        remaining = len(data) - target_offset
        possible_strides = [stride for stride in stride_candidates if count * stride <= remaining]
        if not possible_strides:
            continue
        target_string = _read_binary_sidecar_string_at(data, target_offset)
        confidence = "strong_string_table" if target_string else "candidate_count_offset_pair"
        rows.append(
            {
                "owner_offset": owner_offset,
                "count": count,
                "data_offset": target_offset,
                "possible_element_sizes": possible_strides,
                "target_preview": target_string,
                "confidence": confidence,
            }
        )
        if len(rows) >= max_pairs:
            break
    return rows


def _is_binary_sidecar_plausible_float(value: float) -> bool:
    if not math.isfinite(value):
        return False
    if abs(value) > 1_000_000.0:
        return False
    if 0.0 < abs(value) < 1.0e-12:
        return False
    return True


def _binary_sidecar_float_rows(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_rows: int = 48,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_limit = min(len(data), sample_limit)
    if scan_limit < 12:
        return rows
    for offset in range(0, scan_limit - 15, 4):
        values = struct.unpack_from("<4f", data, offset)
        if not all(_is_binary_sidecar_plausible_float(value) for value in values):
            continue
        if all(abs(value) < 1.0e-6 for value in values):
            continue
        # Random integer tables can also look like floats. Keep these explicitly
        # experimental and only sample enough rows to guide format recovery.
        non_zero_count = sum(1 for value in values if abs(value) >= 1.0e-6)
        row_kind = "float4_candidate" if non_zero_count >= 4 else "float3_or_padded_float4_candidate"
        rows.append(
            {
                "offset": offset,
                "type": row_kind,
                "values": [round(float(value), 7) for value in values],
                "confidence": "experimental_numeric_scan",
            }
        )
        if len(rows) >= max_rows:
            break
    return rows


def _decode_binary_sidecar_half_float(raw_value: int) -> float:
    try:
        return float(struct.unpack("<e", int(raw_value & 0xFFFF).to_bytes(2, "little"))[0])
    except (struct.error, OverflowError, ValueError):
        return float("nan")


def _is_binary_sidecar_plausible_half_float(value: float) -> bool:
    if not math.isfinite(value):
        return False
    if abs(value) > 16.0:
        return False
    if 0.0 < abs(value) < 1.0e-7:
        return False
    return True


def _binary_sidecar_animation_keyframe_tables(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_tables: int = 16,
    max_preview_rows: int = 8,
) -> List[Dict[str, object]]:
    """Recover read-only PAA-style keyframe table candidates."""

    row_size = 10
    component_count = 4
    minimum_rows = 4
    scan_limit = min(len(data), sample_limit)
    if scan_limit < row_size * minimum_rows:
        return []

    def read_row(offset: int) -> Optional[Tuple[int, Tuple[float, ...], float]]:
        if offset < 0 or offset + row_size > scan_limit:
            return None
        frame = struct.unpack_from("<H", data, offset)[0]
        values: List[float] = []
        for component_index in range(component_count):
            raw_value = struct.unpack_from("<H", data, offset + 2 + component_index * 2)[0]
            value = _decode_binary_sidecar_half_float(raw_value)
            if not _is_binary_sidecar_plausible_half_float(value):
                return None
            values.append(value)
        if all(abs(value) < 1.0e-7 for value in values):
            return None
        norm = math.sqrt(sum(value * value for value in values))
        return frame, tuple(values), norm

    candidates: List[Dict[str, object]] = []
    max_rows_per_candidate = 2048
    for offset in range(0, scan_limit - row_size * minimum_rows + 1, 2):
        first_rows: List[Tuple[int, Tuple[float, ...], float, int]] = []
        previous_frame: Optional[int] = None
        valid = True
        for row_index in range(minimum_rows):
            row_offset = offset + row_index * row_size
            row = read_row(row_offset)
            if row is None:
                valid = False
                break
            frame, values, norm = row
            if previous_frame is not None and not (0 < frame - previous_frame <= 256):
                valid = False
                break
            previous_frame = frame
            first_rows.append((frame, values, norm, row_offset))
        if not valid:
            continue

        rows = list(first_rows)
        while len(rows) < max_rows_per_candidate:
            row_offset = offset + len(rows) * row_size
            row = read_row(row_offset)
            if row is None:
                break
            frame, values, norm = row
            previous_frame = int(rows[-1][0])
            if not (0 < frame - previous_frame <= 256):
                break
            rows.append((frame, values, norm, row_offset))

        consecutive_steps = sum(1 for index in range(1, len(rows)) if int(rows[index][0]) - int(rows[index - 1][0]) == 1)
        normish_rows = sum(1 for _frame, _values, norm, _row_offset in rows if 0.75 <= norm <= 1.25)
        value_kind = "half_float_quaternion_or_vector4"
        if normish_rows >= max(3, int(len(rows) * 0.75)):
            value_kind = "half_float_quaternion_candidate"
        confidence = "strong_half_float_keyframe_run" if consecutive_steps >= len(rows) - 2 else "half_float_keyframe_run"
        preview_rows = [
            {
                "offset": row_offset,
                "frame": int(frame),
                "values": [round(float(value), 6) for value in values],
                "norm": round(float(norm), 6),
            }
            for frame, values, norm, row_offset in rows[:max_preview_rows]
        ]
        candidates.append(
            {
                "offset": offset,
                "row_size": row_size,
                "components": component_count,
                "row_format": "u16 frame + 4 half-float values",
                "row_count": len(rows),
                "frame_start": int(rows[0][0]),
                "frame_end": int(rows[-1][0]),
                "value_kind": value_kind,
                "confidence": confidence,
                "preview_rows": preview_rows,
            }
        )

    candidates.sort(key=lambda row: (-int(row.get("row_count") or 0), int(row.get("offset") or 0)))
    selected: List[Dict[str, object]] = []
    occupied_ranges: List[Tuple[int, int]] = []
    for candidate in candidates:
        start = int(candidate.get("offset") or 0)
        end = start + int(candidate.get("row_count") or 0) * row_size
        if any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied_ranges):
            continue
        selected.append(candidate)
        occupied_ranges.append((start, end))
        if len(selected) >= max_tables:
            break
    selected.sort(key=lambda row: int(row.get("offset") or 0))
    return selected


_BINARY_SIDECAR_DECL_IDENTIFIER_RE = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{2,127}")
_BINARY_SIDECAR_PRIMITIVE_TYPES = {
    "bool",
    "float",
    "float2",
    "float3",
    "float4",
    "int",
    "int16",
    "int32",
    "uint16",
    "uint32",
}
_BINARY_SIDECAR_STRING_TYPES = {"staticstringa", "indexedstringa", "normalizedpatha"}
_BINARY_SIDECAR_KNOWN_TYPE_CODES = {0, 1, 2, 3, 4, 5, 7, 10}


def _looks_like_binary_sidecar_declared_type(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 3 or len(text) > 96:
        return False
    if text.startswith("_") or "/" in text or "\\" in text or "." in text or " " in text:
        return False
    if not _STRUCTURED_BINARY_IDENTIFIER_RE.fullmatch(text):
        return False
    return any(character.isalpha() for character in text)


def _binary_sidecar_descriptor_likely_kind(
    member_name: str,
    declared_type: str,
    descriptor_words: Sequence[int],
) -> Tuple[str, str, str]:
    normalized_name = str(member_name or "").strip().lstrip("_").lower()
    normalized_type = str(declared_type or "").strip().lower()
    type_code = int(descriptor_words[0]) if descriptor_words else -1
    element_size = int(descriptor_words[1]) if len(descriptor_words) > 1 else 0
    flags_word = int(descriptor_words[2]) if len(descriptor_words) > 2 else 0

    is_array = (
        type_code in {3, 10}
        or bool(flags_word & 0x1000)
        or normalized_name.endswith(("list", "array"))
        or any(token in normalized_name for token in ("list", "container", "filenames", "triangles", "phases"))
    )
    array_status = "array_or_table" if is_array else "single_value"

    if normalized_type in _BINARY_SIDECAR_STRING_TYPES or "path" in normalized_type:
        reference_status = "string_reference" if "path" in normalized_type else "string"
        likely_kind = "string_array" if is_array else "string"
    elif "reflectobjectptr" in normalized_type or normalized_type.endswith("ptr"):
        reference_status = "object_reference"
        likely_kind = "object_reference_array" if is_array else "object_reference"
    elif "reflectobject" in normalized_type:
        reference_status = "object_reference"
        likely_kind = "object_value_or_reference"
    elif type_code == 2:
        reference_status = "type_or_enum_reference"
        likely_kind = "enum_or_flags"
    elif normalized_type in _BINARY_SIDECAR_PRIMITIVE_TYPES:
        reference_status = "value"
        likely_kind = "numeric_array" if is_array else ("bool" if normalized_type == "bool" else "numeric")
    elif element_size in {1, 2, 4, 8, 12, 16} and type_code == 0:
        reference_status = "value"
        likely_kind = "numeric_or_packed_value"
    else:
        reference_status = "type_or_class_reference"
        likely_kind = "array_or_table" if is_array else "typed_value"

    return likely_kind, array_status, reference_status


def _binary_sidecar_descriptor_confidence(
    member_name: str,
    declared_type: str,
    descriptor_words: Sequence[int],
) -> str:
    type_code = int(descriptor_words[0]) if descriptor_words else -1
    element_size = int(descriptor_words[1]) if len(descriptor_words) > 1 else -1
    normalized_type = str(declared_type or "").strip().lower()
    if not str(member_name or "").startswith("_"):
        return "low"
    if type_code in _BINARY_SIDECAR_KNOWN_TYPE_CODES:
        if normalized_type in _BINARY_SIDECAR_PRIMITIVE_TYPES and element_size in {1, 2, 4, 8, 12, 16}:
            return "strong_length_prefixed_member_declaration"
        if normalized_type in _BINARY_SIDECAR_STRING_TYPES or "reflectobject" in normalized_type:
            return "strong_length_prefixed_member_declaration"
        if type_code == 2 and _looks_like_binary_sidecar_declared_type(declared_type):
            return "strong_length_prefixed_member_declaration"
        return "length_prefixed_member_declaration"
    return "experimental_unknown_descriptor"


def _binary_sidecar_schema_declarations(
    data: bytes,
    extension: str,
    *,
    sample_limit: int = 262_144,
    max_rows: int = 512,
) -> Dict[str, object]:
    scan_limit = min(len(data), sample_limit)
    normalized_extension = str(extension or "").strip().lower()
    field_group_func = _binary_sidecar_group_func_for_extension(normalized_extension)
    rows: List[Dict[str, object]] = []
    seen_row_keys: set[Tuple[int, str, str]] = set()
    class_candidates: List[Dict[str, object]] = []
    seen_class_names: set[str] = set()

    for match in _BINARY_SIDECAR_DECL_IDENTIFIER_RE.finditer(data[:scan_limit]):
        name_offset = match.start()
        name = match.group().decode("ascii", errors="ignore")
        if name_offset < 4:
            continue
        try:
            name_length = struct.unpack_from("<I", data, name_offset - 4)[0]
        except struct.error:
            continue
        if name_length != len(name):
            continue

        if (
            not name.startswith("_")
            and len(class_candidates) < 24
            and _looks_like_binary_sidecar_declared_type(name)
            and name.lower() not in _BINARY_SIDECAR_PRIMITIVE_TYPES
            and name.lower() not in _BINARY_SIDECAR_STRING_TYPES
            and name not in seen_class_names
        ):
            seen_class_names.add(name)
            class_candidates.append(
                {
                    "offset": name_offset,
                    "name": name,
                    "confidence": "length_prefixed_type_or_class_name",
                }
            )

        if not name.startswith("_") or not _looks_like_structured_field_name(name):
            continue
        type_length_offset = name_offset + len(name)
        if type_length_offset + 4 > scan_limit:
            continue
        try:
            type_length = struct.unpack_from("<I", data, type_length_offset)[0]
        except struct.error:
            continue
        if type_length < 3 or type_length > 96:
            continue
        type_offset = type_length_offset + 4
        descriptor_offset = type_offset + type_length
        if descriptor_offset + 8 > scan_limit:
            continue
        declared_type_bytes = data[type_offset:descriptor_offset]
        if not _BINARY_SIDECAR_DECL_IDENTIFIER_RE.fullmatch(declared_type_bytes):
            continue
        declared_type = declared_type_bytes.decode("ascii", errors="ignore")
        if not _looks_like_binary_sidecar_declared_type(declared_type):
            continue
        descriptor_bytes = data[descriptor_offset:descriptor_offset + 8]
        descriptor_words = struct.unpack_from("<4H", descriptor_bytes, 0)
        if descriptor_words[0] > 64 or descriptor_words[1] > 256:
            continue
        row_key = (name_offset, name, declared_type)
        if row_key in seen_row_keys:
            continue
        seen_row_keys.add(row_key)
        likely_kind, array_status, reference_status = _binary_sidecar_descriptor_likely_kind(
            name,
            declared_type,
            descriptor_words,
        )
        rows.append(
            {
                "declaration_offset": name_offset - 4,
                "name_offset": name_offset,
                "name": name,
                "declared_type": declared_type,
                "type_offset": type_offset,
                "descriptor_offset": descriptor_offset,
                "descriptor_hex": descriptor_bytes.hex(" ").upper(),
                "descriptor_words_le_u16": [int(value) for value in descriptor_words],
                "type_code": int(descriptor_words[0]),
                "element_size": int(descriptor_words[1]),
                "descriptor_flags_hex": f"0x{int(descriptor_words[2]):04X}{int(descriptor_words[3]):04X}",
                "likely_kind": likely_kind,
                "array_status": array_status,
                "reference_status": reference_status,
                "group": field_group_func(name),
                "confidence": _binary_sidecar_descriptor_confidence(name, declared_type, descriptor_words),
                "edit_status": "read_only_declaration_only",
            }
        )
        if len(rows) >= max_rows:
            break

    signature_source = "\n".join(
        f"{row['name']}:{row['declared_type']}:{row['descriptor_hex']}"
        for row in rows
    )
    layout_signature = hashlib.sha1(signature_source.encode("utf-8")).hexdigest()[:16] if signature_source else ""
    declaration_end = 0
    if rows:
        declaration_end = max(int(row.get("descriptor_offset") or 0) + 8 for row in rows)
        declaration_end = min(len(data), (declaration_end + 3) & ~3)
    unusual_rows = [
        row
        for row in rows
        if int(row.get("type_code") or 0) not in _BINARY_SIDECAR_KNOWN_TYPE_CODES
        or str(row.get("confidence") or "").startswith("experimental")
    ]

    return {
        "status": "experimental_read_only_declaration_recovery",
        "declaration_count": len(rows),
        "unique_member_count": len({str(row.get("name") or "") for row in rows}),
        "layout_signature": layout_signature,
        "root_or_class_candidates": class_candidates,
        "declaration_region": {
            "start_offset": int(rows[0]["declaration_offset"]) if rows else 0,
            "end_offset": declaration_end,
            "candidate_value_region_start": declaration_end,
            "confidence": "declaration_end_heuristic" if rows else "no_declarations",
        },
        "declared_member_rows": rows,
        "unknown_descriptor_rows": unusual_rows[:64],
    }


def _build_grouped_schema_declaration_lines(
    declaration_rows: Sequence[Mapping[str, object]],
    *,
    section_order: Sequence[str],
    per_section_limit: int = 24,
) -> List[str]:
    grouped: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in declaration_rows:
        if not isinstance(row, Mapping):
            continue
        group = str(row.get("group") or "Misc").strip() or "Misc"
        grouped[group].append(row)

    lines: List[str] = []
    ordered_sections = list(section_order) + [
        section_name
        for section_name in sorted(grouped, key=str.casefold)
        if section_name not in section_order
    ]
    for section_name in ordered_sections:
        rows = grouped.get(section_name, [])
        if not rows:
            continue
        lines.extend(["", f"{section_name} declared fields ({len(rows)})"])
        for row in rows[:per_section_limit]:
            name = str(row.get("name") or "").strip()
            declared_type = str(row.get("declared_type") or "").strip()
            likely_kind = str(row.get("likely_kind") or "field").strip()
            array_status = str(row.get("array_status") or "").strip()
            descriptor = str(row.get("descriptor_hex") or "").strip()
            array_suffix = ", array" if array_status and array_status != "single_value" else ""
            lines.append(
                f"  [{likely_kind}{array_suffix}] {name}: {declared_type} "
                f"@0x{int(row.get('name_offset') or 0):X} desc={descriptor}"
            )
        if len(rows) > per_section_limit:
            lines.append(f"  ... {len(rows) - per_section_limit} more")
    return lines


def _binary_sidecar_container_summary(data: bytes, extension: str) -> Dict[str, object]:
    head4 = data[:4]
    magic_ascii = "".join(chr(value) if 32 <= value <= 126 else "." for value in head4)
    normalized_extension = str(extension or "").strip().lower()
    container: Dict[str, object] = {
        "magic_ascii": magic_ascii,
        "magic_hex": head4.hex(" ").upper(),
        "recognized_family": "unknown",
    }
    if head4 == b"PAR ":
        container["recognized_family"] = "PAR"
        container["note"] = "PAR-family binary. Current decode is read-only and schema-recovery oriented."
    elif head4 == b"PARC":
        container["recognized_family"] = "PARC"
        container["note"] = "PARC structured container. Current decode is read-only and schema-recovery oriented."
    elif normalized_extension == ".meshinfo":
        container["note"] = "MeshInfo sidecar without a currently proven top-level magic."
    elif normalized_extension == ".motionblending":
        container["note"] = "Motion-blending sidecar without a currently proven top-level magic."
    elif normalized_extension == ".paa_metabin":
        container["note"] = "PAA animation metadata sidecar. Current decode is read-only and relationship/schema-recovery oriented."
    elif normalized_extension == ".pappt":
        container["note"] = "Part-prefab table metadata. Current decode is read-only and used for part/model relationship evidence."
    elif normalized_extension == ".pamhc":
        container["note"] = "Model-property header metadata. Current decode is read-only and used for material/model relationship evidence."
    elif normalized_extension in {".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
        container["note"] = "Animation schedule/sequence metadata. Current decode is read-only and relationship/schema-recovery oriented."
    elif normalized_extension == ".seqmt":
        if head4 == b"DDS!":
            container["recognized_family"] = "DDS_SEQUENCE_TEXTURE"
            container["note"] = "SEQMT DDS! sequence texture metadata. Current decode is read-only and exposes atlas/frame-table evidence."
        else:
            container["note"] = "SEQMT sequence texture metadata. Current decode is read-only and used for timeline/material relationship evidence."
    return container


def _binary_sidecar_kind_label(extension: str) -> str:
    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension == ".meshinfo":
        return "MeshInfo"
    if normalized_extension == ".motionblending":
        return "Motion Blending"
    if normalized_extension == ".paa":
        return "PAA Animation Clip"
    if normalized_extension == ".paa_metabin":
        return "PAA Animation Metadata"
    if normalized_extension == ".pappt":
        return "Part Prefab Table"
    if normalized_extension == ".pamhc":
        return "Model Property Header"
    if normalized_extension in {".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
        return "Animation Schedule"
    if normalized_extension == ".seqmt":
        return "SEQMT Sequence Texture Metadata"
    return normalized_extension.lstrip(".").upper() or "Binary Sidecar"


def _build_binary_sidecar_related_references(
    source_entry: Optional[ArchiveEntry],
    *,
    asset_references: Sequence[str],
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveModelTextureReference, ...]:
    if source_entry is None:
        return ()
    companion_entries = (
        _find_archive_model_related_entries(source_entry, archive_entries_by_basename)
        if archive_entries_by_basename is not None
        else ()
    )
    explicit_references = build_archive_related_file_references(
        source_entry,
        explicit_reference_names=asset_references,
        companion_entries=companion_entries,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    graph_references = build_archive_relationship_references(
        source_entry,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    return merge_archive_reference_rows(explicit_references, graph_references)


def _binary_sidecar_reference_document_rows(
    references: Sequence[ArchiveModelTextureReference],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for reference in references:
        rows.append(
            {
                "reference_name": reference.reference_name,
                "semantic_label": reference.semantic_label,
                "resolution_status": reference.resolution_status,
                "resolved_archive_path": reference.resolved_archive_path,
                "resolved_package_label": reference.resolved_package_label,
                "reference_kind": reference.reference_kind,
                "relation_group": reference.relation_group,
                "relation_confidence": reference.relation_confidence,
                "relation_reason": reference.relation_reason,
                "usage_count": reference.usage_count,
            }
        )
    return rows


def build_binary_sidecar_analysis_document(
    data: bytes,
    virtual_path: str,
    *,
    extension: str = "",
    source_entry: Optional[ArchiveEntry] = None,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Dict[str, object]:
    normalized_extension = str(extension or PurePosixPath(str(virtual_path or "")).suffix).strip().lower()
    animation_metadata = (
        _paa_metabin_analysis_document(data, virtual_path)
        if normalized_extension == ".paa_metabin"
        else {}
    )
    seqmt_metadata = (
        _seqmt_analysis_document(data, virtual_path)
        if normalized_extension == ".seqmt"
        else {}
    )
    string_records = _extract_binary_string_records(data, sample_limit=262_144, max_strings=512)
    field_records = [
        record
        for record in string_records
        if _looks_like_structured_field_name(record.text)
    ]
    asset_reference_rows = _binary_sidecar_asset_reference_rows(string_records, max_references=96)
    asset_references: List[str] = []
    seen_references: set[str] = set()
    for row in asset_reference_rows:
        path = str(row.get("path") or "").strip()
        normalized = _normalize_model_texture_reference(path)
        if not normalized or normalized in seen_references:
            continue
        seen_references.add(normalized)
        asset_references.append(path)
    for path in _extract_binary_asset_references(data, sample_limit=262_144, max_references=96):
        normalized = _normalize_model_texture_reference(path)
        if not normalized or normalized in seen_references:
            continue
        seen_references.add(normalized)
        asset_references.append(path)
    related_references = _build_binary_sidecar_related_references(
        source_entry,
        asset_references=asset_references,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    offset_candidates = _binary_sidecar_offset_candidates(data)
    count_offset_pairs = _binary_sidecar_count_offset_pairs(data)
    float_rows = _binary_sidecar_float_rows(data)
    animation_keyframe_tables = (
        _binary_sidecar_animation_keyframe_tables(data)
        if normalized_extension == ".paa"
        else []
    )
    schema_declarations = _binary_sidecar_schema_declarations(data, normalized_extension)
    schema_member_rows = [
        row
        for row in schema_declarations.get("declared_member_rows", [])
        if isinstance(row, Mapping)
    ]
    field_group_func = _binary_sidecar_group_func_for_extension(normalized_extension)
    prefab_evidence_rows = (
        _prefab_evidence_rows(schema_member_rows, asset_references)
        if normalized_extension == ".prefab"
        else []
    )
    prefab_material_override_rows = (
        _prefab_material_override_evidence_rows(schema_member_rows, asset_references)
        if normalized_extension == ".prefab"
        else []
    )
    field_rows = [
        {
            "offset": record.offset,
            "name": record.text,
            "group": field_group_func(record.text),
            "confidence": "readable_string_identifier",
            "status": "experimental_schema_recovery",
        }
        for record in field_records[:256]
    ]
    editable_candidate_rows: List[Dict[str, object]] = []
    for row in float_rows[:16]:
        editable_candidate_rows.append(
            {
                "offset": row["offset"],
                "type": row["type"],
                "value": row["values"],
                "edit_status": "disabled_until_schema_is_proven",
                "confidence": row["confidence"],
            }
        )

    return {
        "document": "Crimson Desert Mod Workbench binary sidecar decode document.",
        "format_status": "experimental_read_only_schema_recovery",
        "source": {
            "path": virtual_path,
            "extension": normalized_extension,
            "kind": _binary_sidecar_kind_label(normalized_extension),
            "size": len(data),
            "sha1": hashlib.sha1(data).hexdigest(),
        },
        "summary": {
            "readable_strings": len(string_records),
            "field_like_identifiers": len(field_records),
            "asset_reference_hints": len(asset_references),
            "related_files_resolved": sum(1 for reference in related_references if reference.resolved_entry is not None),
            "related_file_rows": len(related_references),
            "offset_candidates": len(offset_candidates),
            "count_offset_pair_candidates": len(count_offset_pairs),
            "float_vector_candidates": len(float_rows),
            "animation_keyframe_table_candidates": len(animation_keyframe_tables),
            "animation_keyframe_rows": sum(int(row.get("row_count") or 0) for row in animation_keyframe_tables),
            "schema_declarations": int(schema_declarations.get("declaration_count") or 0),
            "schema_declared_members": len(schema_member_rows),
            "schema_layout_signature": str(schema_declarations.get("layout_signature") or ""),
            "prefab_evidence_rows": len(prefab_evidence_rows),
            "prefab_material_override_rows": len(prefab_material_override_rows),
            "seqmt_recognized": bool(seqmt_metadata.get("recognized"))
            if isinstance(seqmt_metadata, Mapping)
            else False,
            "seqmt_columns": int(seqmt_metadata.get("columns") or 0)
            if isinstance(seqmt_metadata, Mapping)
            else 0,
            "seqmt_rows": int(seqmt_metadata.get("rows") or 0)
            if isinstance(seqmt_metadata, Mapping)
            else 0,
            "seqmt_frame_count": int(seqmt_metadata.get("frame_count") or 0)
            if isinstance(seqmt_metadata, Mapping)
            else 0,
            "seqmt_payload_complete": bool(seqmt_metadata.get("payload_complete"))
            if isinstance(seqmt_metadata, Mapping)
            else False,
            "animation_metadata_stream_bytes": int(
                ((animation_metadata.get("packed_metadata_stream") or {}).get("stream_size") or 0)
                if isinstance(animation_metadata.get("packed_metadata_stream"), Mapping)
                else 0
            ),
            "animation_metadata_filename_hints": len(animation_metadata.get("filename_hints") or [])
            if isinstance(animation_metadata, Mapping)
            else 0,
        },
        "container": _binary_sidecar_container_summary(data, normalized_extension),
        "header_words_le": _binary_sidecar_header_words(data),
        "schema_declarations": schema_declarations,
        "prefab": {
            "evidence_rows": prefab_evidence_rows,
            "material_override_rows": prefab_material_override_rows,
            "editing_supported": False,
            "note": ".prefab files describe scene/resource/component metadata; renderable geometry usually lives in linked .pac/.pam/.pamlod assets.",
        } if normalized_extension == ".prefab" else {},
        "animation_metadata": animation_metadata,
        "animation": {
            "keyframe_table_candidates": animation_keyframe_tables,
            "editing_supported": False,
            "note": ".paa animation clip rows are exposed as read-only recovery evidence. Channel ownership and write rules are not proven.",
        } if normalized_extension == ".paa" else {},
        "seqmt": seqmt_metadata,
        "strings": {
            "field_rows": field_rows,
            "readable_rows": [
                {
                    "offset": record.offset,
                    "text": record.text,
                    "kind": "field" if _looks_like_structured_field_name(record.text) else "string",
                }
                for record in string_records[:256]
            ],
        },
        "references": {
            "asset_reference_hints": asset_reference_rows,
            "related_files": _binary_sidecar_reference_document_rows(related_references),
        },
        "tables": {
            "offset_candidates": offset_candidates,
            "count_offset_pair_candidates": count_offset_pairs,
            "float_vector_candidates": float_rows,
            "animation_keyframe_table_candidates": animation_keyframe_tables,
        },
        "editing": {
            "supported": False,
            "policy": "read_only_until_schema_and_no_edit_roundtrip_are_proven",
            "reason": (
                ".meshinfo, .motionblending, .paa, .paa_metabin, .prefab, .pappt, .pamhc, and .seqmt layout/count semantics are not proven yet. "
                "The app can export decoded declarations and recovery evidence, but it will not write edited values "
                "until exact value offsets, fixed-size fields, array counts, offsets, and no-edit binary rebuilds "
                "are validated."
            ),
            "candidate_rows": editable_candidate_rows,
        },
        "notes": [
            "Offsets are byte offsets in the decoded archive payload used by preview/export.",
            "Schema declarations are length-prefixed member/type rows recovered from the binary; they identify fields but do not prove value write offsets.",
            "Offset/count/float rows are recovery evidence, not stable schema fields.",
            "Related files may include same-stem companions and archive relationship graph matches.",
        ],
    }


def build_binary_sidecar_analysis_json(
    data: bytes,
    virtual_path: str,
    *,
    extension: str = "",
    source_entry: Optional[ArchiveEntry] = None,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> str:
    document = build_binary_sidecar_analysis_document(
        data,
        virtual_path,
        extension=extension,
        source_entry=source_entry,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    return json.dumps(document, indent=2)


_BINARY_SIDECAR_CORPUS_EXTENSIONS = (".meshinfo", ".motionblending", ".paa_metabin", ".prefab", ".pappt", ".pamhc", ".seqmt")


def _discover_binary_sidecar_corpus_paths(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[Path]:
    candidates_by_extension: Dict[str, List[Path]] = defaultdict(list)
    seen_paths: set[str] = set()
    max_files = int(discovery_limit) if discovery_limit is not None and int(discovery_limit) > 0 else None

    def add_candidate(path: Path) -> None:
        extension = path.suffix.lower()
        if extension not in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            return
        normalized = str(path.expanduser().resolve()).lower()
        if normalized in seen_paths:
            return
        seen_paths.add(normalized)
        if max_files is None or len(candidates_by_extension[extension]) < max_files:
            candidates_by_extension[extension].append(path)

    for raw_source in source_paths:
        raise_if_cancelled(stop_event)
        source = Path(raw_source).expanduser()
        if source.is_file():
            add_candidate(source)
            continue
        if not source.is_dir():
            continue
        for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            for path in source.rglob(f"*{extension}"):
                raise_if_cancelled(stop_event)
                if not path.is_file():
                    continue
                add_candidate(path)

    for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
        candidates_by_extension[extension].sort(key=lambda item: str(item).casefold())

    discovered: List[Path] = []
    discovered_counts: Dict[str, int] = defaultdict(int)
    if max_files is None:
        for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            discovered.extend(candidates_by_extension.get(extension, ()))
        return discovered

    while len(discovered) < max_files:
        added = False
        for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            extension_paths = candidates_by_extension.get(extension, [])
            index = discovered_counts[extension]
            if index >= len(extension_paths):
                continue
            discovered.append(extension_paths[index])
            discovered_counts[extension] += 1
            added = True
            if len(discovered) >= max_files:
                break
        if not added:
            break
    return discovered


def _binary_sidecar_corpus_path_label(path: Path, source_paths: Sequence[Path]) -> str:
    for raw_source in source_paths:
        source = Path(raw_source).expanduser()
        try:
            if source.is_dir():
                return path.relative_to(source).as_posix()
            if source.is_file() and path.resolve() == source.resolve():
                return path.name
        except (OSError, ValueError):
            continue
    return str(path)


def _select_balanced_binary_sidecar_detail_paths(paths: Sequence[Path], max_files: Optional[int]) -> List[Path]:
    if max_files is None or max_files <= 0 or len(paths) <= max_files:
        return list(paths)
    by_extension: Dict[str, List[Path]] = defaultdict(list)
    for path in paths:
        by_extension[path.suffix.lower()].append(path)
    selected: List[Path] = []
    selected_counts: Dict[str, int] = defaultdict(int)
    while len(selected) < max_files:
        added = False
        for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            extension_paths = by_extension.get(extension, [])
            index = selected_counts[extension]
            if index >= len(extension_paths):
                continue
            selected.append(extension_paths[index])
            selected_counts[extension] += 1
            added = True
            if len(selected) >= max_files:
                break
        if not added:
            break
    return selected


def _binary_sidecar_descriptor_is_unknown(row: Mapping[str, object]) -> bool:
    try:
        type_code = int(row.get("type_code") or 0)
    except (TypeError, ValueError):
        return True
    confidence = str(row.get("confidence") or "")
    return type_code not in _BINARY_SIDECAR_KNOWN_TYPE_CODES or confidence.startswith("experimental")


def _build_binary_sidecar_corpus_extension_report(
    paths: Sequence[Path],
    source_paths: Sequence[Path],
    *,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    progress_offset: int = 0,
    progress_total: int = 0,
) -> Dict[str, object]:
    layout_counts: Counter[str] = Counter()
    layout_examples: Dict[str, Dict[str, object]] = {}
    field_file_counts: Counter[str] = Counter()
    field_decl_counts: Counter[str] = Counter()
    field_type_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    field_descriptor_counts: Dict[Tuple[str, str], Counter[str]] = defaultdict(Counter)
    field_metadata: Dict[Tuple[str, str], Dict[str, str]] = {}
    unknown_descriptor_counts: Counter[str] = Counter()
    unknown_descriptor_examples: Dict[str, Dict[str, object]] = {}
    value_region_counts: Counter[int] = Counter()
    value_region_examples: Dict[int, str] = {}
    numeric_region_counts: Counter[int] = Counter()
    numeric_region_examples: Dict[int, str] = {}
    animation_type_counts: Counter[str] = Counter()
    animation_hint_counts: Counter[str] = Counter()
    animation_stream_size_counts: Counter[int] = Counter()
    animation_examples: Dict[str, str] = {}
    seqmt_grid_counts: Counter[str] = Counter()
    seqmt_flag_counts: Counter[int] = Counter()
    seqmt_payload_status_counts: Counter[str] = Counter()
    seqmt_examples: Dict[str, str] = {}
    scanned_count = 0
    failed_rows: List[Dict[str, object]] = []

    total = progress_total or len(paths)
    for local_index, path in enumerate(paths, start=1):
        raise_if_cancelled(stop_event)
        label = _binary_sidecar_corpus_path_label(path, source_paths)
        if progress_callback is not None:
            progress_callback(
                progress_offset + local_index - 1,
                total,
                f"Scanning binary sidecar corpus {progress_offset + local_index:,} / {total:,}: {path.name}",
            )
        try:
            data = path.read_bytes()
            document = build_binary_sidecar_analysis_document(data, label, extension=path.suffix.lower())
        except RunCancelled:
            raise
        except Exception as exc:
            failed_rows.append({"path": label, "error": str(exc)})
            continue

        scanned_count += 1
        seqmt_metadata = document.get("seqmt", {})
        if isinstance(seqmt_metadata, Mapping) and seqmt_metadata.get("recognized"):
            columns = int(seqmt_metadata.get("columns") or 0)
            rows_count = int(seqmt_metadata.get("rows") or 0)
            frame_count = int(seqmt_metadata.get("frame_count") or 0)
            grid_key = f"{columns}x{rows_count}:{frame_count}"
            seqmt_grid_counts[grid_key] += 1
            seqmt_examples.setdefault(grid_key, label)
            flag_value = int(seqmt_metadata.get("flags_or_packing_byte") or 0)
            seqmt_flag_counts[flag_value] += 1
            seqmt_examples.setdefault(f"flag_0x{flag_value:02X}", label)
            payload_status = "complete" if bool(seqmt_metadata.get("payload_complete")) else "truncated"
            if int(seqmt_metadata.get("trailing_payload_bytes") or 0) > 0:
                payload_status = "complete_with_trailing_payload"
            seqmt_payload_status_counts[payload_status] += 1
            seqmt_examples.setdefault(payload_status, label)

        animation_metadata = document.get("animation_metadata", {})
        if isinstance(animation_metadata, Mapping) and animation_metadata:
            declared_type = str(animation_metadata.get("declared_type") or "").strip()
            if declared_type:
                animation_type_counts[declared_type] += 1
                animation_examples.setdefault(declared_type, label)
            for hint in animation_metadata.get("filename_hints") or []:
                if not isinstance(hint, Mapping):
                    continue
                hint_key = f"{hint.get('kind') or 'Hint'}: {hint.get('meaning') or hint.get('token') or ''}".strip()
                if hint_key:
                    animation_hint_counts[hint_key] += 1
                    animation_examples.setdefault(hint_key, label)
            stream = animation_metadata.get("packed_metadata_stream", {})
            if isinstance(stream, Mapping):
                stream_size = int(stream.get("stream_size") or 0)
                if stream_size > 0:
                    bucket = (stream_size // 256) * 256
                    animation_stream_size_counts[bucket] += 1
                    animation_examples.setdefault(f"stream_0x{bucket:08X}", label)
        schema = document.get("schema_declarations", {})
        if not isinstance(schema, Mapping):
            continue
        rows = [
            row
            for row in schema.get("declared_member_rows", [])
            if isinstance(row, Mapping)
        ]
        signature = str(schema.get("layout_signature") or "")
        if signature:
            layout_counts[signature] += 1
            layout_examples.setdefault(
                signature,
                {
                    "signature": signature,
                    "example_path": label,
                    "declaration_count": len(rows),
                    "first_fields": [str(row.get("name") or "") for row in rows[:8]],
                    "candidate_value_region_start": int(
                        (schema.get("declaration_region", {}) or {}).get("candidate_value_region_start") or 0
                    )
                    if isinstance(schema.get("declaration_region", {}), Mapping)
                    else 0,
                },
            )
        declaration_region = schema.get("declaration_region", {})
        if isinstance(declaration_region, Mapping):
            region_start = int(declaration_region.get("candidate_value_region_start") or 0)
            if region_start > 0:
                region_bucket = (region_start // 256) * 256
                value_region_counts[region_bucket] += 1
                value_region_examples.setdefault(region_bucket, label)

        seen_names_in_file: set[str] = set()
        for row in rows:
            name = str(row.get("name") or "").strip()
            declared_type = str(row.get("declared_type") or "").strip()
            descriptor_hex = str(row.get("descriptor_hex") or "").strip()
            if not name or not declared_type:
                continue
            field_decl_counts[name] += 1
            field_type_counts[name][declared_type] += 1
            field_descriptor_counts[(name, declared_type)][descriptor_hex] += 1
            field_metadata.setdefault(
                (name, declared_type),
                {
                    "group": str(row.get("group") or ""),
                    "likely_kind": str(row.get("likely_kind") or ""),
                    "array_status": str(row.get("array_status") or ""),
                    "reference_status": str(row.get("reference_status") or ""),
                    "confidence": str(row.get("confidence") or ""),
                },
            )
            if name not in seen_names_in_file:
                seen_names_in_file.add(name)
                field_file_counts[name] += 1
            if _binary_sidecar_descriptor_is_unknown(row):
                unknown_descriptor_counts[descriptor_hex] += 1
                unknown_descriptor_examples.setdefault(
                    descriptor_hex,
                    {
                        "descriptor_hex": descriptor_hex,
                        "example_path": label,
                        "example_field": name,
                        "declared_type": declared_type,
                        "type_code": int(row.get("type_code") or 0),
                    },
                )

        tables = document.get("tables", {})
        float_rows = list(tables.get("float_vector_candidates") or []) if isinstance(tables, Mapping) else []
        for row in float_rows[:8]:
            if not isinstance(row, Mapping):
                continue
            offset = int(row.get("offset") or 0)
            if offset <= 0:
                continue
            offset_bucket = (offset // 256) * 256
            numeric_region_counts[offset_bucket] += 1
            numeric_region_examples.setdefault(offset_bucket, label)

    stable_fields: List[Dict[str, object]] = []
    for name, file_count in field_file_counts.items():
        type_counts = field_type_counts.get(name, Counter())
        if not type_counts:
            continue
        declared_type, type_count = type_counts.most_common(1)[0]
        descriptor_counts = field_descriptor_counts.get((name, declared_type), Counter())
        descriptor_hex, descriptor_count = descriptor_counts.most_common(1)[0] if descriptor_counts else ("", 0)
        metadata = field_metadata.get((name, declared_type), {})
        stable_fields.append(
            {
                "name": name,
                "declared_type": declared_type,
                "files_with_field": int(file_count),
                "declaration_count": int(field_decl_counts.get(name, 0)),
                "type_consistency": round(type_count / max(sum(type_counts.values()), 1), 4),
                "top_descriptor_hex": descriptor_hex,
                "top_descriptor_count": int(descriptor_count),
                "descriptor_consistency": round(descriptor_count / max(type_count, 1), 4),
                "group": metadata.get("group", ""),
                "likely_kind": metadata.get("likely_kind", ""),
                "array_status": metadata.get("array_status", ""),
                "reference_status": metadata.get("reference_status", ""),
                "confidence": metadata.get("confidence", ""),
            }
        )
    stable_fields.sort(
        key=lambda row: (
            -int(row.get("files_with_field") or 0),
            -float(row.get("type_consistency") or 0.0),
            str(row.get("name") or "").casefold(),
        )
    )

    layout_rows = []
    for signature, count in layout_counts.most_common(64):
        row = dict(layout_examples.get(signature, {}))
        row["file_count"] = int(count)
        layout_rows.append(row)

    unknown_rows = []
    for descriptor_hex, count in unknown_descriptor_counts.most_common(64):
        row = dict(unknown_descriptor_examples.get(descriptor_hex, {"descriptor_hex": descriptor_hex}))
        row["count"] = int(count)
        unknown_rows.append(row)

    value_region_rows = [
        {
            "region_start_bucket": f"0x{region_start:08X}",
            "file_count": int(count),
            "source": "declaration_end_bucket",
            "example_path": value_region_examples.get(region_start, ""),
        }
        for region_start, count in value_region_counts.most_common(32)
    ]
    value_region_rows.extend(
        {
            "region_start_bucket": f"0x{region_start:08X}",
            "file_count": int(count),
            "source": "numeric_candidate_bucket",
            "example_path": numeric_region_examples.get(region_start, ""),
        }
        for region_start, count in numeric_region_counts.most_common(32)
    )
    animation_rows = {
        "declared_types": [
            {
                "declared_type": name,
                "file_count": int(count),
                "example_path": animation_examples.get(name, ""),
            }
            for name, count in animation_type_counts.most_common(16)
        ],
        "filename_hints": [
            {
                "hint": name,
                "file_count": int(count),
                "example_path": animation_examples.get(name, ""),
            }
            for name, count in animation_hint_counts.most_common(32)
        ],
        "packed_stream_size_buckets": [
            {
                "stream_size_bucket": f"0x{bucket:08X}",
                "file_count": int(count),
                "example_path": animation_examples.get(f"stream_0x{bucket:08X}", ""),
            }
            for bucket, count in animation_stream_size_counts.most_common(32)
        ],
    }
    seqmt_rows = {
        "atlas_grids": [
            {
                "grid": name,
                "file_count": int(count),
                "example_path": seqmt_examples.get(name, ""),
            }
            for name, count in seqmt_grid_counts.most_common(32)
        ],
        "flag_or_packing_bytes": [
            {
                "value": f"0x{value:02X}",
                "file_count": int(count),
                "example_path": seqmt_examples.get(f"flag_0x{value:02X}", ""),
            }
            for value, count in seqmt_flag_counts.most_common(16)
        ],
        "payload_statuses": [
            {
                "status": name,
                "file_count": int(count),
                "example_path": seqmt_examples.get(name, ""),
            }
            for name, count in seqmt_payload_status_counts.most_common(16)
        ],
    }

    return {
        "files_scanned": scanned_count,
        "files_failed": len(failed_rows),
        "failed_rows": failed_rows[:32],
        "layout_signatures": layout_rows,
        "stable_fields": stable_fields[:256],
        "unknown_descriptor_bytes": unknown_rows,
        "candidate_value_regions": value_region_rows,
        "animation_metadata": animation_rows,
        "seqmt": seqmt_rows,
    }


def build_binary_sidecar_corpus_report(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = 1000,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, object]:
    normalized_sources = tuple(Path(path).expanduser() for path in source_paths)
    discovered_paths = _discover_binary_sidecar_corpus_paths(
        normalized_sources,
        discovery_limit=discovery_limit,
        stop_event=stop_event,
    )
    max_detail = int(detail_scan_limit) if detail_scan_limit is not None and int(detail_scan_limit) > 0 else None
    detail_paths = _select_balanced_binary_sidecar_detail_paths(discovered_paths, max_detail)
    by_extension_paths: Dict[str, List[Path]] = defaultdict(list)
    for path in detail_paths:
        by_extension_paths[path.suffix.lower()].append(path)

    if progress_callback is not None:
        progress_callback(0, max(len(detail_paths), 1), f"Discovered {len(discovered_paths):,} binary sidecar file(s).")

    by_extension: Dict[str, object] = {}
    progress_offset = 0
    progress_total = max(len(detail_paths), 1)
    for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
        extension_paths = by_extension_paths.get(extension, [])
        by_extension[extension] = _build_binary_sidecar_corpus_extension_report(
            extension_paths,
            normalized_sources,
            stop_event=stop_event,
            progress_callback=progress_callback,
            progress_offset=progress_offset,
            progress_total=progress_total,
        )
        progress_offset += len(extension_paths)

    if progress_callback is not None:
        progress_callback(progress_total, progress_total, "Binary sidecar corpus report complete.")

    return {
        "document": "Crimson Desert Mod Workbench binary sidecar corpus report.",
        "format": "cdmw_binary_sidecar_corpus_v1",
        "format_status": "experimental_read_only_schema_recovery",
        "source_paths": [str(path) for path in normalized_sources],
        "summary": {
            "files_discovered": len(discovered_paths),
            "files_scanned": len(detail_paths),
            "discovery_limit": int(discovery_limit) if discovery_limit is not None and int(discovery_limit) > 0 else None,
            "detail_scan_limit": int(detail_scan_limit) if detail_scan_limit is not None and int(detail_scan_limit) > 0 else None,
            "meshinfo_files_scanned": len(by_extension_paths.get(".meshinfo", [])),
            "motionblending_files_scanned": len(by_extension_paths.get(".motionblending", [])),
            "paa_metabin_files_scanned": len(by_extension_paths.get(".paa_metabin", [])),
            "prefab_files_scanned": len(by_extension_paths.get(".prefab", [])),
            "pappt_files_scanned": len(by_extension_paths.get(".pappt", [])),
            "pamhc_files_scanned": len(by_extension_paths.get(".pamhc", [])),
            "seqmt_files_scanned": len(by_extension_paths.get(".seqmt", [])),
        },
        "by_extension": by_extension,
        "editing": {
            "supported": False,
            "policy": "read_only_until_exact_value_offsets_and_no_edit_rebuilds_are_proven",
            "reason": "Corpus ranking proves declarations and layout frequency, not safe write offsets.",
        },
    }


def build_binary_sidecar_corpus_json(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = 1000,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    return json.dumps(
        build_binary_sidecar_corpus_report(
            source_paths,
            discovery_limit=discovery_limit,
            detail_scan_limit=detail_scan_limit,
            stop_event=stop_event,
            progress_callback=progress_callback,
        ),
        indent=2,
    )


def _group_prefab_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("cloth", "pbd", "shrink", "masterpose", "syncmeshcomponent", "anchormeshnode", "meshnode", "dynamicmotion", "sdf")):
        return "Mesh / Cloth"
    if any(token in normalized for token in ("socket", "skeleton", "bone")):
        return "Skeleton / Sockets"
    if any(token in normalized for token in ("path", "file", "filename", "mesh", "model", "lod", "material", "texture", "resource", "asset")):
        return "Resources"
    if any(token in normalized for token in ("component", "childsceneobjects", "masterpose", "customgamedata")):
        return "Scene / Object"
    if any(token in normalized for token in ("prefab", "scene", "object", "node", "actor", "entity", "spawn", "enable", "uuid", "uid", "tag", "generateuuid")):
        return "Scene / Object"
    if any(token in normalized for token in ("position", "rotation", "scale", "transform", "matrix", "bound", "bbox")):
        return "Transform / Bounds"
    if any(token in normalized for token in ("collision", "physics", "pbd", "shape", "constraint", "rigid", "mass")):
        return "Physics / Collision"
    if any(token in normalized for token in ("script", "event", "trigger", "condition", "gimmick", "logic")):
        return "Logic / Events"
    if any(token in normalized for token in ("render", "opacity", "priority", "sound", "audio", "effect", "emitter", "particle", "light")):
        return "Presentation"
    return "Misc"


def _binary_sidecar_group_func_for_extension(extension: str) -> Callable[[str], str]:
    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension == ".meshinfo":
        return _group_meshinfo_field_name
    if normalized_extension in {".prefab", ".pappt"}:
        return _group_prefab_field_name
    if normalized_extension == ".pamhc":
        return _group_model_property_header_field_name
    if normalized_extension == ".seqmt":
        return _group_seqmt_field_name
    if normalized_extension in {".levelinfo", ".palevel", ".roadsector", ".road", ".nav"}:
        return _group_world_field_name
    if normalized_extension in {".pabc", ".pabv", ".pabgb", ".pabgh"}:
        return _group_rig_variant_field_name
    return _group_animation_field_name


def _group_model_property_header_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("material", "shader", "texture", "submesh", "parameter", "skin", "cloth")):
        return "Material / Texture"
    if any(token in normalized for token in ("mesh", "model", "lod", "resource", "path", "file", "filename", "asset")):
        return "Model Resources"
    if any(token in normalized for token in ("socket", "skeleton", "bone", "rig")):
        return "Skeleton / Rig"
    if any(token in normalized for token in ("physics", "collision", "hkx", "shape", "cloth", "pbd")):
        return "Physics / Collision"
    if any(token in normalized for token in ("bounds", "bbox", "position", "rotation", "scale", "transform")):
        return "Transform / Bounds"
    if any(token in normalized for token in ("variant", "part", "body", "gender", "race")):
        return "Variant / Part"
    return "Misc"


def _group_seqmt_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("material", "shader", "texture", "parameter", "color", "tint", "mask", "blend", "uv")):
        return "Material / Texture"
    if any(token in normalized for token in ("sequence", "sequencer", "timeline", "track", "key", "frame", "curve", "duration", "time")):
        return "Sequence / Timeline"
    if any(token in normalized for token in ("path", "file", "filename", "resource", "asset", "model", "mesh", "prefab")):
        return "Resources"
    if any(token in normalized for token in ("effect", "emitter", "particle", "light", "visibility", "opacity", "render", "presentation")):
        return "Effect / Presentation"
    if any(token in normalized for token in ("position", "rotation", "scale", "transform", "matrix", "bound", "bbox")):
        return "Transform / Bounds"
    return "Misc"


def _group_world_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("level", "world", "zone", "sector", "region", "cell", "tile", "block")):
        return "World / Region"
    if any(token in normalized for token in ("road", "spline", "lane", "path", "waypoint", "route")):
        return "Road / Path"
    if any(token in normalized for token in ("nav", "navigation", "navmesh", "obstacle", "agent")):
        return "Navigation"
    if any(token in normalized for token in ("prefab", "object", "entity", "spawn", "gimmick", "prop")):
        return "Scene Objects"
    if any(token in normalized for token in ("terrain", "height", "water", "foliage", "grass", "vegetation")):
        return "Terrain"
    if any(token in normalized for token in ("bound", "bbox", "extent", "position", "rotation", "scale")):
        return "Bounds / Transform"
    return "Misc"


def _group_rig_variant_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("skeleton", "bone", "joint", "rig", "socket")):
        return "Skeleton / Rig"
    if any(token in normalized for token in ("physics", "ragdoll", "constraint", "collision", "shape")):
        return "Physics"
    if any(token in normalized for token in ("animation", "motion", "blend", "pose", "clip")):
        return "Animation"
    if any(token in normalized for token in ("variant", "gender", "race", "body", "part", "custom")):
        return "Variant / Body"
    if any(token in normalized for token in ("gameplay", "state", "behavior", "ai", "event")):
        return "Gameplay"
    return "Misc"


def _build_grouped_structured_section_lines(
    field_names: Sequence[str],
    *,
    group_func: Callable[[str], str],
    section_order: Sequence[str],
    per_section_limit: int = 24,
) -> List[str]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for name in sorted({str(item or "").strip() for item in field_names if str(item or "").strip()}, key=str.casefold):
        grouped[group_func(name)].append(name)

    lines: List[str] = []
    for section_name in section_order:
        section_fields = grouped.get(section_name, [])
        if not section_fields:
            continue
        lines.extend(["", f"{section_name} ({len(section_fields)})"])
        for field_name in section_fields[:per_section_limit]:
            lines.append(f"  [{_structured_field_type_hint(field_name)}] {field_name}")
        if len(section_fields) > per_section_limit:
            lines.append(f"  ... {len(section_fields) - per_section_limit} more")

    remaining_sections = [
        section_name
        for section_name, section_fields in grouped.items()
        if section_name not in section_order and section_fields
    ]
    for section_name in sorted(remaining_sections, key=str.casefold):
        section_fields = grouped.get(section_name, [])
        if not section_fields:
            continue
        lines.extend(["", f"{section_name} ({len(section_fields)})"])
        for field_name in section_fields[:per_section_limit]:
            lines.append(f"  [{_structured_field_type_hint(field_name)}] {field_name}")
        if len(section_fields) > per_section_limit:
            lines.append(f"  ... {len(section_fields) - per_section_limit} more")

    return lines


def _score_related_reference_candidate(
    source_entry: ArchiveEntry,
    candidate: ArchiveEntry,
    *,
    reference_name: str = "",
) -> Tuple[int, int, int]:
    normalized_reference = _normalize_model_texture_reference(reference_name)
    normalized_candidate = _normalize_model_texture_reference(candidate.path)
    reference_basename = PurePosixPath(normalized_reference).name if normalized_reference else ""
    candidate_basename = PurePosixPath(normalized_candidate).name
    source_root = PurePosixPath(_normalize_model_texture_reference(source_entry.path)).parts[:1]
    candidate_root = PurePosixPath(normalized_candidate).parts[:1]
    score_value = 0
    if normalized_reference and normalized_candidate == normalized_reference:
        score_value += 20
    if reference_basename and candidate_basename == reference_basename:
        score_value += 10
    if candidate.pamt_path == source_entry.pamt_path:
        score_value += 8
    if candidate.pamt_path.parent == source_entry.pamt_path.parent:
        score_value += 5
    if source_root and candidate_root and source_root == candidate_root:
        score_value += 3
    return score_value, -len(candidate.path), 0


def _resolve_related_archive_entry(
    source_entry: ArchiveEntry,
    reference_name: str,
    *,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Optional[ArchiveEntry]:
    normalized_reference = _normalize_model_texture_reference(reference_name)
    candidates: List[ArchiveEntry] = []
    seen_paths: set[str] = set()

    if archive_entries_by_normalized_path is not None and normalized_reference:
        for candidate in archive_entries_by_normalized_path.get(normalized_reference, ()):
            normalized_candidate = _normalize_model_texture_reference(candidate.path)
            if normalized_candidate in seen_paths or normalized_candidate == _normalize_model_texture_reference(source_entry.path):
                continue
            seen_paths.add(normalized_candidate)
            candidates.append(candidate)

    reference_basename = PurePosixPath(normalized_reference or reference_name.replace("\\", "/")).name.lower()
    if archive_entries_by_basename is not None and reference_basename:
        for candidate in archive_entries_by_basename.get(reference_basename, ()):
            normalized_candidate = _normalize_model_texture_reference(candidate.path)
            if normalized_candidate in seen_paths or normalized_candidate == _normalize_model_texture_reference(source_entry.path):
                continue
            seen_paths.add(normalized_candidate)
            candidates.append(candidate)

    if not candidates:
        return None

    candidates.sort(
        key=lambda candidate: _score_related_reference_candidate(
            source_entry,
            candidate,
            reference_name=reference_name,
        ),
        reverse=True,
    )
    return candidates[0]


def _describe_generic_related_reference_label(reference_name: str, resolved_entry: Optional[ArchiveEntry] = None) -> str:
    reference_basename = PurePosixPath(
        str(getattr(resolved_entry, "path", "") or reference_name).replace("\\", "/")
    ).name.lower()
    extension = str(getattr(resolved_entry, "extension", "") or PurePosixPath(reference_name.replace("\\", "/")).suffix).strip().lower()
    if extension == ".dds":
        semantic_label = _describe_model_texture_semantic_label(reference_name)
        return semantic_label or "Texture / DDS"
    if "prefabdata" in reference_basename or extension == ".prefabdata_xml":
        return "Prefab Metadata"
    if extension == ".pami":
        return "Material Variant Sidecar"
    if _is_material_sidecar_extension(extension, reference_basename):
        return "Material Sidecar"
    if extension == ".xml":
        return "Related XML"
    if extension == ".meshinfo":
        return "Related MeshInfo"
    if extension in {".hkx", ".hkt"}:
        return f"Related {extension.lstrip('.').upper()}"
    if extension == ".pab":
        return "Related PAB"
    if extension == ".pabc":
        return "Skeleton Variation"
    if extension in {".pabv", ".pabgb", ".pabgh"}:
        return "Rig / Gameplay Variant"
    if extension == ".papr":
        return "Animation Constraint"
    if extension == ".pac":
        return "Related PAC"
    if extension == ".pam":
        return "Related PAM"
    if extension == ".pamlod":
        return "Related PAMLOD"
    if extension == ".paa":
        return "Related PAA"
    if extension == ".paa_metabin":
        return "Animation Metadata"
    if extension in {".pae", ".paem"}:
        return "Related Effect"
    if extension == ".seqmt":
        return "Sequence Texture Metadata"
    if extension == ".prefab":
        return "Prefab"
    if extension in {".levelinfo", ".palevel"}:
        return "Level Metadata"
    if extension in {".roadsector", ".road", ".nav"}:
        return "World / Navigation"
    if extension:
        return f"Related {extension.lstrip('.').upper()}"
    return "Related File"


def build_archive_related_file_references(
    source_entry: ArchiveEntry,
    *,
    explicit_reference_names: Sequence[str] = (),
    companion_entries: Sequence[ArchiveEntry] = (),
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveModelTextureReference, ...]:
    references: Dict[Tuple[str, str], ArchiveModelTextureReference] = {}
    ordered_keys: List[Tuple[str, str]] = []

    for companion_entry in companion_entries:
        normalized_path = _normalize_model_texture_reference(companion_entry.path)
        if not normalized_path:
            continue
        key = ("file", normalized_path)
        if key in references:
            continue
        relation_kind, relation_group, relation_confidence, relation_reason = _build_archive_relation_metadata(
            source_entry,
            resolved_entry=companion_entry,
            authoritative=(
                str(source_entry.extension or "").strip().lower() == ".dds"
                and _is_material_sidecar_extension(
                    str(companion_entry.extension or "").strip().lower(),
                    PurePosixPath(companion_entry.path.replace("\\", "/")).name.lower(),
                )
            ),
            authoritative_reason="Sidecar binding reference",
        )
        references[key] = ArchiveModelTextureReference(
            reference_name=PurePosixPath(companion_entry.path.replace("\\", "/")).name,
            semantic_label=_describe_model_related_file_label(companion_entry),
            resolution_status="resolved",
            resolved_archive_path=companion_entry.path,
            resolved_package_label=companion_entry.package_label,
            resolved_entry=companion_entry,
            usage_count=1,
            reference_kind=relation_kind,
            relation_group=relation_group,
            relation_reason=relation_reason,
            relation_confidence=relation_confidence,
        )
        ordered_keys.append(key)

    for raw_reference_name in explicit_reference_names:
        reference_name = str(raw_reference_name or "").strip().replace("\\", "/")
        if not reference_name:
            continue
        resolved_entry = _resolve_related_archive_entry(
            source_entry,
            reference_name,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            archive_entries_by_basename=archive_entries_by_basename,
        )
        normalized_key_value = _normalize_model_texture_reference(
            resolved_entry.path if isinstance(resolved_entry, ArchiveEntry) else reference_name
        )
        if not normalized_key_value or normalized_key_value == _normalize_model_texture_reference(source_entry.path):
            continue
        key = ("file", normalized_key_value)
        if key not in references:
            authoritative = bool(isinstance(resolved_entry, ArchiveEntry) or "/" in reference_name or "." in PurePosixPath(reference_name).name)
            relation_kind, relation_group, relation_confidence, relation_reason = _build_archive_relation_metadata(
                source_entry,
                reference_name=reference_name,
                resolved_entry=resolved_entry if isinstance(resolved_entry, ArchiveEntry) else None,
                authoritative=authoritative,
                authoritative_reason="Explicit path reference",
            )
            references[key] = ArchiveModelTextureReference(
                reference_name=reference_name,
                semantic_label=_describe_generic_related_reference_label(reference_name, resolved_entry),
                resolution_status="resolved" if isinstance(resolved_entry, ArchiveEntry) else "missing",
                resolved_archive_path=resolved_entry.path if isinstance(resolved_entry, ArchiveEntry) else "",
                resolved_package_label=resolved_entry.package_label if isinstance(resolved_entry, ArchiveEntry) else "",
                resolved_entry=resolved_entry if isinstance(resolved_entry, ArchiveEntry) else None,
                usage_count=1,
                reference_kind=relation_kind,
                relation_group=relation_group,
                relation_reason=relation_reason,
                relation_confidence=relation_confidence,
            )
            ordered_keys.append(key)
            continue
        references[key].usage_count += 1
        if reference_name and not references[key].reference_name:
            references[key].reference_name = reference_name
        if isinstance(resolved_entry, ArchiveEntry) and references[key].resolved_entry is None:
            references[key].resolved_entry = resolved_entry
            references[key].resolved_archive_path = resolved_entry.path
            references[key].resolved_package_label = resolved_entry.package_label
            references[key].resolution_status = "resolved"

    return tuple(references[key] for key in ordered_keys)


def _archive_relationship_edge_group_label(edge: object, resolved_entry: ArchiveEntry) -> str:
    relation_kind = str(getattr(edge, "relation_kind", "") or "").strip().lower()
    resolved_extension = str(resolved_entry.extension or "").lower()
    resolved_path = str(resolved_entry.path or "").replace("\\", "/").lower()
    resolved_basename = PurePosixPath(resolved_entry.path.replace("\\", "/")).name.lower()
    if relation_kind == "texture" or str(resolved_entry.extension or "").lower() == ".dds":
        return "Textures"
    if relation_kind == "material_sidecar" or _is_material_sidecar_extension(resolved_extension, resolved_basename):
        return "Material Sidecars"
    if resolved_extension == ".pamhc":
        return "Material Sidecars"
    if relation_kind in {"model", "mesh", "lod"} or str(resolved_entry.extension or "").lower() in {".pac", ".pam", ".pamlod"}:
        return "Mesh / Model"
    if relation_kind == "skeleton" or str(resolved_entry.extension or "").lower() in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh"}:
        return "Skeleton / Rig"
    if relation_kind == "physics" or (
        resolved_extension in {".hkx", ".hkt"}
        and any(token in resolved_path for token in ("meshphysics", "havokphysics", "ragdoll", "physics"))
    ):
        return "Physics / Collision"
    if relation_kind == "animation" or resolved_extension in {
        ".hkx",
        ".hkt",
        ".paa",
        ".paa_metabin",
        ".motionblending",
        ".papr",
        ".pae",
        ".paem",
        ".paseq",
        ".paschedule",
        ".paschedulepath",
        ".pastage",
        ".seqmt",
    }:
        return "Animation / Motion"
    return "Metadata / Other"


def _archive_relationship_edge_semantic_label(edge: object, resolved_entry: ArchiveEntry) -> str:
    role = str(getattr(edge, "role", "") or "").strip()
    if role:
        return _humanize_model_texture_hint(role)
    if str(resolved_entry.extension or "").lower() == ".dds":
        return _describe_model_texture_semantic_label(resolved_entry.path)
    return _describe_model_related_file_label(resolved_entry)


def build_archive_relationship_references(
    source_entry: ArchiveEntry,
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveModelTextureReference, ...]:
    extension = str(source_entry.extension or "").strip().lower()
    basename = PurePosixPath(source_entry.path.replace("\\", "/")).name.lower()
    if not (
        extension in ARCHIVE_MODEL_EXTENSIONS
        or extension in {
            ".app_xml",
            ".prefabdata_xml",
            ".pac_xml",
            ".pam_xml",
            ".pamlod_xml",
            ".pami",
            ".prefab",
            ".pappt",
            ".pamhc",
            ".hkx",
            ".hkt",
            ".meshinfo",
            ".levelinfo",
            ".palevel",
            ".roadsector",
            ".road",
            ".nav",
            ".paa",
            ".paa_metabin",
            ".pae",
            ".paem",
            ".motionblending",
            ".paseq",
            ".paschedule",
            ".paschedulepath",
            ".pastage",
            ".seqmt",
            ".pab",
            ".pabc",
            ".pabv",
            ".pabgb",
            ".pabgh",
        }
        or _is_material_sidecar_extension(extension, basename)
    ):
        return ()
    if archive_entries_by_normalized_path is None and archive_entries_by_basename is None:
        return ()

    try:
        from cdmw.core.archive_relationships import build_archive_relationship_plan
    except Exception:
        return ()

    try:
        relationship_plan = build_archive_relationship_plan(
            source_entry,
            (),
            path_index=archive_entries_by_normalized_path,
            basename_index=archive_entries_by_basename,
        )
    except Exception:
        return ()

    references: List[ArchiveModelTextureReference] = []
    seen: set[Tuple[object, ...]] = set()
    source_identity = _archive_entry_identity_signature(source_entry)

    def add_resolved_reference(
        resolved_entry: ArchiveEntry,
        *,
        reference_name: str = "",
        semantic_label: str = "",
        relation_kind: str = "",
        relation_group: str = "",
        relation_reason: str = "",
        relation_confidence: str = "",
        semantic_hint: str = "",
        source_table: str = "",
        source_field: str = "",
    ) -> None:
        resolved_identity = _archive_entry_identity_signature(resolved_entry)
        if not resolved_identity or resolved_identity == source_identity or resolved_identity in seen:
            return
        seen.add(resolved_identity)
        references.append(
            ArchiveModelTextureReference(
                reference_name=reference_name or PurePosixPath(resolved_entry.path.replace("\\", "/")).name,
                semantic_label=semantic_label or _describe_model_related_file_label(resolved_entry),
                resolution_status="resolved",
                resolved_archive_path=resolved_entry.path,
                resolved_package_label=resolved_entry.package_label,
                resolved_entry=resolved_entry,
                usage_count=1,
                reference_kind=relation_kind or _relation_kind_for_entry(resolved_entry),
                relation_group=relation_group or _relation_group_for_kind(relation_kind or _relation_kind_for_entry(resolved_entry)),
                relation_reason=relation_reason,
                relation_confidence=relation_confidence or RelationConfidence.DERIVED_SAME_STEM.value,
                semantic_hint=semantic_hint,
                sidecar_parameter_name=semantic_hint,
                source_table=source_table,
                source_field=source_field,
            )
        )

    direct_same_stem_extensions = {
        ".hkx",
        ".hkt",
        ".meshinfo",
        ".prefab",
        ".pappt",
        ".pamhc",
        ".paa",
        ".paa_metabin",
        ".motionblending",
        ".pae",
        ".paem",
        ".paseq",
        ".paschedule",
        ".paschedulepath",
        ".pastage",
        ".seqmt",
        ".pab",
        ".pabc",
        ".pabv",
        ".pabgb",
        ".pabgh",
        ".levelinfo",
        ".palevel",
        ".roadsector",
        ".road",
        ".nav",
    }
    if archive_entries_by_basename is not None and (
        extension in ARCHIVE_MODEL_EXTENSIONS or extension in direct_same_stem_extensions
    ):
        for related_entry in _find_archive_model_related_entries(source_entry, archive_entries_by_basename):
            relation_kind, relation_group, relation_confidence, relation_reason = _build_archive_relation_metadata(
                source_entry,
                reference_name=related_entry.path,
                resolved_entry=related_entry,
            )
            add_resolved_reference(
                related_entry,
                semantic_label=_describe_model_related_file_label(related_entry),
                relation_kind=relation_kind,
                relation_group=relation_group,
                relation_reason=relation_reason,
                relation_confidence=relation_confidence,
                semantic_hint="same_stem_companion",
            )

    for edge in tuple(getattr(relationship_plan, "edges", ()) or ()):
        if bool(getattr(edge, "unresolved", False)):
            continue
        resolved_entry = getattr(edge, "related_entry", None)
        if not isinstance(resolved_entry, ArchiveEntry):
            continue
        add_resolved_reference(
            resolved_entry,
            semantic_label=_archive_relationship_edge_semantic_label(edge, resolved_entry),
            relation_kind=str(getattr(edge, "relation_kind", "") or _relation_kind_for_entry(resolved_entry)),
            relation_group=_archive_relationship_edge_group_label(edge, resolved_entry),
            relation_reason=str(getattr(edge, "reason", "") or "").strip(),
            relation_confidence=str(getattr(edge, "confidence", "") or RelationConfidence.DERIVED_SAME_STEM.value),
            semantic_hint=str(getattr(edge, "role", "") or "").strip(),
            source_table=str(getattr(edge, "source_table", "") or "").strip(),
            source_field=str(getattr(edge, "source_field", "") or "").strip(),
        )
    return tuple(references)


def merge_archive_reference_rows(
    *reference_groups: Sequence[ArchiveModelTextureReference],
) -> Tuple[ArchiveModelTextureReference, ...]:
    merged: List[ArchiveModelTextureReference] = []
    rows_by_key: Dict[Tuple[object, ...], ArchiveModelTextureReference] = {}

    def key_for(reference: ArchiveModelTextureReference) -> Tuple[object, ...]:
        resolved_entry = getattr(reference, "resolved_entry", None)
        if isinstance(resolved_entry, ArchiveEntry):
            return ("entry", *_archive_entry_identity_signature(resolved_entry))
        resolved_path = str(getattr(reference, "resolved_archive_path", "") or "").replace("\\", "/").strip().lower()
        if resolved_path:
            return ("path", resolved_path)
        return (
            "ref",
            str(getattr(reference, "relation_group", "") or "").strip().lower(),
            str(getattr(reference, "reference_kind", "") or "").strip().lower(),
            str(getattr(reference, "reference_name", "") or "").replace("\\", "/").strip().lower(),
        )

    for group in reference_groups:
        for reference in tuple(group or ()):
            if not isinstance(reference, ArchiveModelTextureReference):
                continue
            key = key_for(reference)
            existing = rows_by_key.get(key)
            if existing is None:
                rows_by_key[key] = reference
                merged.append(reference)
                continue
            existing.usage_count = max(1, int(existing.usage_count or 0)) + max(1, int(reference.usage_count or 0))
            if not existing.semantic_label and reference.semantic_label:
                existing.semantic_label = reference.semantic_label
            if reference.semantic_hint and not existing.semantic_hint:
                existing.semantic_hint = reference.semantic_hint
                existing.sidecar_parameter_name = existing.sidecar_parameter_name or reference.sidecar_parameter_name
                if reference.semantic_label:
                    existing.semantic_label = reference.semantic_label
            if not existing.relation_reason and reference.relation_reason:
                existing.relation_reason = reference.relation_reason
            if not existing.relation_confidence and reference.relation_confidence:
                existing.relation_confidence = reference.relation_confidence
            if not existing.reference_kind and reference.reference_kind:
                existing.reference_kind = reference.reference_kind
            if not existing.relation_group and reference.relation_group:
                existing.relation_group = reference.relation_group
            if not existing.source_table and getattr(reference, "source_table", ""):
                existing.source_table = str(reference.source_table or "")
            if not existing.source_field and getattr(reference, "source_field", ""):
                existing.source_field = str(reference.source_field or "")
    return tuple(merged)


def _archive_item_icon_catalog_row_value(row: object, key: str) -> object:
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _archive_item_icon_catalog_row_values(row: object, key: str) -> Tuple[str, ...]:
    raw_value = _archive_item_icon_catalog_row_value(row, key)
    if isinstance(raw_value, str):
        value = raw_value.replace("\\", "/").strip()
        return (value,) if value else ()
    if isinstance(raw_value, (list, tuple)):
        values: List[str] = []
        seen: set[str] = set()
        for item in raw_value:
            value = str(item or "").replace("\\", "/").strip()
            lowered = value.casefold()
            if value and lowered not in seen:
                values.append(value)
                seen.add(lowered)
        return tuple(values)
    return ()


def _strip_archive_item_icon_stem_prefix(value: str) -> str:
    stem = PurePosixPath(str(value or "").replace("\\", "/")).stem.casefold().strip()
    for prefix in _ARCHIVE_ITEM_ICON_STEM_PREFIXES:
        if stem.startswith(prefix):
            return stem[len(prefix) :].strip("_")
    return stem


def _archive_path_is_probable_item_icon(path: object) -> bool:
    path_text = str(path or "").replace("\\", "/").strip().casefold()
    if not path_text:
        return False
    posix = PurePosixPath(path_text)
    if posix.suffix.lower() != ".dds":
        return False
    stem = posix.stem.casefold()
    return "itemicon" in path_text or any(stem.startswith(prefix) for prefix in _ARCHIVE_ITEM_ICON_STEM_PREFIXES)


def _add_archive_item_icon_match_keys(keys: set[str], raw_value: object) -> None:
    normalized = str(raw_value or "").replace("\\", "/").strip().strip("/").casefold()
    if not normalized:
        return
    posix = PurePosixPath(normalized)
    basename = posix.name.casefold()
    stem = posix.stem.casefold()
    candidates = {
        normalized,
        basename,
        stem,
        _strip_archive_model_family_variant_suffix(stem),
    }
    icon_model_stem = _strip_archive_item_icon_stem_prefix(stem)
    if icon_model_stem:
        candidates.add(icon_model_stem)
        candidates.add(_strip_archive_model_family_variant_suffix(icon_model_stem))
    for candidate in tuple(candidates):
        if not candidate:
            continue
        keys.add(candidate)
        if "/" not in candidate and "." not in candidate:
            for alias in iter_archive_character_equipment_root_alias_stems(candidate):
                if alias:
                    keys.add(alias.casefold())
            for alias in iter_archive_equipment_model_alias_stems(candidate):
                if alias:
                    keys.add(alias.casefold())


def _archive_item_icon_catalog_row_match_keys(row: object) -> set[str]:
    keys: set[str] = set()
    for key in ("pac_files", "model_stems", "icon_paths"):
        for value in _archive_item_icon_catalog_row_values(row, key):
            _add_archive_item_icon_match_keys(keys, value)
    return keys


def _resolve_archive_item_icon_catalog_entries(
    value: str,
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    fallback_extensions: Sequence[str] = (".dds",),
) -> Tuple[ArchiveEntry, ...]:
    normalized = str(value or "").replace("\\", "/").strip()
    if not normalized:
        return ()
    candidates: List[ArchiveEntry] = []
    seen: set[Tuple[object, ...]] = set()

    def add_entry(entry: ArchiveEntry) -> None:
        key = _archive_entry_identity_signature(entry)
        if key in seen:
            return
        candidates.append(entry)
        seen.add(key)

    def add_by_path_or_basename(candidate_text: str) -> None:
        candidate = str(candidate_text or "").replace("\\", "/").strip()
        if not candidate:
            return
        candidate_lower = candidate.casefold()
        if archive_entries_by_normalized_path is not None:
            for entry in archive_entries_by_normalized_path.get(candidate_lower, ()) or ():
                add_entry(entry)
        basename = PurePosixPath(candidate).name.casefold()
        if basename and archive_entries_by_basename is not None:
            for entry in archive_entries_by_basename.get(basename, ()) or ():
                add_entry(entry)

    add_by_path_or_basename(normalized)
    if not PurePosixPath(normalized).suffix:
        for extension in fallback_extensions:
            ext = str(extension or "").strip()
            if ext and not ext.startswith("."):
                ext = f".{ext}"
            add_by_path_or_basename(f"{normalized}{ext}")
    return tuple(candidates)


def build_archive_item_icon_references_from_catalog(
    source_entry: ArchiveEntry,
    item_asset_catalog: Sequence[object] = (),
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    related_references: Sequence[ArchiveModelTextureReference] = (),
) -> Tuple[ArchiveModelTextureReference, ...]:
    if not isinstance(source_entry, ArchiveEntry) or not item_asset_catalog:
        return ()
    source_keys: set[str] = set()
    _add_archive_item_icon_match_keys(source_keys, source_entry.path)
    for reference in tuple(related_references or ()):
        if not isinstance(reference, ArchiveModelTextureReference):
            continue
        _add_archive_item_icon_match_keys(source_keys, getattr(reference, "reference_name", ""))
        _add_archive_item_icon_match_keys(source_keys, getattr(reference, "resolved_archive_path", ""))
        resolved_entry = getattr(reference, "resolved_entry", None)
        if isinstance(resolved_entry, ArchiveEntry):
            _add_archive_item_icon_match_keys(source_keys, resolved_entry.path)
    if not source_keys:
        return ()

    references: List[ArchiveModelTextureReference] = []
    seen_entries: set[Tuple[object, ...]] = {_archive_entry_identity_signature(source_entry)}
    for row in tuple(item_asset_catalog or ()):
        icon_paths = _archive_item_icon_catalog_row_values(row, "icon_paths")
        if not icon_paths:
            continue
        row_keys = _archive_item_icon_catalog_row_match_keys(row)
        if not (source_keys & row_keys):
            continue
        item_label = str(
            _archive_item_icon_catalog_row_value(row, "display_name")
            or _archive_item_icon_catalog_row_value(row, "internal_name")
            or "Item Finder row"
        ).strip()
        if _archive_path_is_probable_item_icon(source_entry.path):
            owner_candidates: List[str] = []
            owner_candidates.extend(_archive_item_icon_catalog_row_values(row, "pac_files"))
            owner_candidates.extend(_archive_item_icon_catalog_row_values(row, "model_stems"))
            for owner_path in owner_candidates:
                for owner_entry in _resolve_archive_item_icon_catalog_entries(
                    owner_path,
                    archive_entries_by_normalized_path=archive_entries_by_normalized_path,
                    archive_entries_by_basename=archive_entries_by_basename,
                    fallback_extensions=(".pac", ".pam", ".pamlod"),
                ):
                    if str(owner_entry.extension or "").lower() not in {".pac", ".pam", ".pamlod"}:
                        continue
                    entry_key = _archive_entry_identity_signature(owner_entry)
                    if entry_key in seen_entries:
                        continue
                    seen_entries.add(entry_key)
                    references.append(
                        ArchiveModelTextureReference(
                            reference_name=owner_path or owner_entry.basename,
                            semantic_label="Owner Model",
                            semantic_hint=item_label,
                            resolution_status="resolved",
                            resolved_archive_path=owner_entry.path,
                            resolved_package_label=owner_entry.package_label,
                            resolved_entry=owner_entry,
                            usage_count=1,
                            reference_kind="used_by",
                            relation_group="Used By / Model",
                            relation_reason=f"Item Finder catalog links {item_label} to the selected inventory icon.",
                            relation_confidence="item_finder",
                        )
                    )
        for icon_path in icon_paths:
            for icon_entry in _resolve_archive_item_icon_catalog_entries(
                icon_path,
                archive_entries_by_normalized_path=archive_entries_by_normalized_path,
                archive_entries_by_basename=archive_entries_by_basename,
            ):
                if not _archive_path_is_probable_item_icon(icon_entry.path):
                    continue
                entry_key = _archive_entry_identity_signature(icon_entry)
                if entry_key in seen_entries:
                    continue
                seen_entries.add(entry_key)
                references.append(
                    ArchiveModelTextureReference(
                        reference_name=icon_path or icon_entry.basename,
                        semantic_label="Inventory Icon",
                        semantic_hint=item_label,
                        resolution_status="resolved",
                        resolved_archive_path=icon_entry.path,
                        resolved_package_label=icon_entry.package_label,
                        resolved_entry=icon_entry,
                        usage_count=1,
                        reference_kind="item_icon",
                        relation_group="Item Icons",
                        relation_reason=f"Item Finder catalog links {item_label} to this inventory icon.",
                        relation_confidence="item_finder",
                    )
                )
    return tuple(references)


_ASSET_FAMILY_GROUP_ORDER: Tuple[str, ...] = (
    "Selected Model",
    "Attachment / Placement",
    "Material",
    "Textures",
    "Item Icons",
    "Physics / HKX",
    "MeshInfo",
    "Prefab / Metadata",
    "Skeleton / Rig",
    "Animation / Motion",
    "Other",
)

_ATTACHMENT_PREFAB_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "_attachedSocketName",
        "_pivotSocketName",
        "_applyPosition",
        "_applyRotation",
        "_applyScale",
        "_worldTransform",
        "_tiledTransform",
        "_offsetTransform",
        "_skinnedMeshFileName",
        "_socketFileName",
        "_skeletonFileName",
    }
)
_ATTACHMENT_CHARACTER_SOCKET_PRIORITY: Tuple[str, ...] = (
    "Pelvis_L_Socket",
    "Pelvis_R_Socket",
    "Spine2_B_MainWeapon_Socket",
    "Spine2_B_SubWeapon_Socket",
    "Spine2_B_Shield_Socket",
    "RHand_Socket",
    "LHand_Socket",
    "UpperWeapon_00_Socket",
    "LowerWeapon_00_Socket",
)
_ATTACHMENT_WEAPON_SOCKET_PRIORITY: Tuple[str, ...] = (
    "Pelvis_L_ChildSocket",
    "Pelvis_R_ChildSocket",
    "Basic_ChildSocket",
    "Store_Pivot_Socket",
    "Stick_Pivot_Socket",
    "InverseB_ChildSocket",
    "InverseF_ChildSocket",
)
_ATTACHMENT_ASSET_REFERENCE_RE = re.compile(
    r"([A-Za-z0-9_./\\-]+?\.(?:"
    r"prefabdata_xml|prefabdata\.xml|pamlod_xml|pac_xml|pam_xml|sockets\.xml|"
    r"paa_metabin|motionblending|paschedulepath|paschedule|paseq|pastage|"
    r"pamlod|meshinfo|prefab|pappt|pamhc|hkx|hkt|pac|pam|pabgb|pabgh|pabc|pabv|papr|pab|paa|pae|paem|seqmt|xml"
    r"))",
    re.IGNORECASE,
)


def _asset_family_group_order() -> Tuple[str, ...]:
    return _ASSET_FAMILY_GROUP_ORDER


def _parse_socket_float_tuple(value: str) -> Tuple[float, ...]:
    values: List[float] = []
    for part in str(value or "").replace(",", " ").split():
        try:
            values.append(float(part))
        except ValueError:
            continue
    return tuple(values)


def _xml_local_tag_name(value: object) -> str:
    text = str(value or "")
    if "}" in text:
        return text.rsplit("}", 1)[-1]
    return text


def parse_socket_bone_data_xml(text: str, source_path: str = "") -> AttachmentSocketDocument:
    """Parse Crimson Desert socket XML enough to explain attachment placement.

    This intentionally stays read-only. It recovers socket names, parent bones,
    transforms, and StackEquipInfo groupings used by weapon/armor placement.
    """
    try:
        root = ET.fromstring(str(text or ""))
    except Exception:
        return AttachmentSocketDocument(source_path=source_path)

    sockets: List[AttachmentSocketInfo] = []
    stack_infos: List[AttachmentStackEquipInfo] = []
    for element in root.iter():
        local_name = _xml_local_tag_name(element.tag)
        if local_name == "Socket" and "Parent" in element.attrib:
            sockets.append(
                AttachmentSocketInfo(
                    name=str(element.attrib.get("Name", "") or "").strip(),
                    parent=str(element.attrib.get("Parent", "") or "").strip(),
                    rotation=_parse_socket_float_tuple(str(element.attrib.get("Rotation", "") or "")),
                    translation=_parse_socket_float_tuple(str(element.attrib.get("Translation", "") or "")),
                    ui_view=str(element.attrib.get("UIView", "") or "").strip(),
                    source_path=source_path,
                )
            )
        elif local_name == "StackEquipInfo":
            socket_names: List[str] = []
            for child in tuple(element):
                if _xml_local_tag_name(child.tag) == "Socket":
                    socket_name = str(child.attrib.get("Name", "") or "").strip()
                    if socket_name:
                        socket_names.append(socket_name)
            stack_infos.append(
                AttachmentStackEquipInfo(
                    equip_type_name=str(element.attrib.get("EquipTypeName", "") or "").strip(),
                    socket_names=tuple(socket_names),
                    origin_bone_name=str(element.attrib.get("OriginBoneName", "") or "").strip(),
                    axis=str(element.attrib.get("Axis", "") or "").strip(),
                    inner_part_names=str(element.attrib.get("InnerPartNames", "") or "").strip(),
                    push_origin_bone=str(element.attrib.get("PushOriginBone", "") or "").strip(),
                    source_path=source_path,
                )
            )
    return AttachmentSocketDocument(source_path=source_path, sockets=tuple(sockets), stack_equip_infos=tuple(stack_infos))


@dataclass(slots=True, frozen=True)
class PrefabSocketNameField:
    field_name: str
    value: str
    length_offset: int
    value_offset: int
    byte_length: int


@dataclass(slots=True, frozen=True)
class PrefabSocketNamePatchResult:
    data: bytes
    fields: Tuple[PrefabSocketNameField, ...]
    proof_lines: Tuple[str, ...]


def _iter_prefab_length_prefixed_ascii_values(
    data: bytes,
    *,
    start_offset: int,
    max_length: int = 260,
) -> Iterator[Tuple[int, int, str]]:
    for length_offset in range(max(0, start_offset), max(0, len(data) - 4)):
        length = struct.unpack_from("<I", data, length_offset)[0]
        if length < 4 or length > max_length:
            continue
        value_offset = length_offset + 4
        value_end = value_offset + length
        if value_end > len(data):
            continue
        raw_value = data[value_offset:value_end]
        if not raw_value or any(byte < 0x20 or byte > 0x7E for byte in raw_value):
            continue
        text = raw_value.decode("ascii", errors="ignore")
        if not text or sum(1 for char in text if char.isalpha()) <= 0:
            continue
        yield length_offset, length, text


def inspect_prefab_socket_name_fields(data: bytes) -> Tuple[PrefabSocketNameField, ...]:
    """Recover the two prefab socket-name value records when their layout is proven.

    The proven safe subset is intentionally narrow: the prefab must declare the
    `_attachedSocketName` and `_pivotSocketName` members as strings, and the
    value block must then expose two length-prefixed socket strings in the same
    order. This matches the original two-hand prefabs and the working 2H-to-1H
    loose mod samples.
    """
    schema = _binary_sidecar_schema_declarations(data, ".prefab")
    rows = tuple(schema.get("declared_member_rows", ()) if isinstance(schema, Mapping) else ())
    row_by_name = {str(row.get("name") or ""): row for row in rows if isinstance(row, Mapping)}
    attached_row = row_by_name.get("_attachedSocketName")
    pivot_row = row_by_name.get("_pivotSocketName")
    if not isinstance(attached_row, Mapping) or not isinstance(pivot_row, Mapping):
        return ()
    if str(attached_row.get("declared_type") or "").casefold() not in {"indexedstringa", "staticstringa"}:
        return ()
    if str(pivot_row.get("declared_type") or "").casefold() not in {"indexedstringa", "staticstringa"}:
        return ()
    try:
        value_scan_start = max(
            int(row.get("descriptor_offset") or 0) + 8
            for row in rows
            if isinstance(row, Mapping)
        )
    except ValueError:
        value_scan_start = 0

    socket_records: List[Tuple[int, int, str]] = []
    for length_offset, length, text in _iter_prefab_length_prefixed_ascii_values(data, start_offset=value_scan_start):
        lowered = text.casefold()
        if (
            "socket" not in lowered
            or text.startswith("_")
            or "/" in text
            or "\\" in text
            or "." in text
        ):
            continue
        socket_records.append((length_offset, length, text))
        if len(socket_records) >= 2:
            break
    if len(socket_records) < 2:
        return ()
    attached_offset, attached_length, attached_text = socket_records[0]
    pivot_offset, pivot_length, pivot_text = socket_records[1]
    if "childsocket" in attached_text.casefold():
        return ()
    if pivot_offset <= attached_offset:
        return ()
    return (
        PrefabSocketNameField(
            field_name="_attachedSocketName",
            value=attached_text,
            length_offset=attached_offset,
            value_offset=attached_offset + 4,
            byte_length=attached_length,
        ),
        PrefabSocketNameField(
            field_name="_pivotSocketName",
            value=pivot_text,
            length_offset=pivot_offset,
            value_offset=pivot_offset + 4,
            byte_length=pivot_length,
        ),
    )


def _validate_prefab_socket_name_replacement(field: PrefabSocketNameField, value: str) -> bytes:
    text = str(value or "").strip()
    try:
        encoded = text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field.field_name} must be ASCII for a safe prefab socket-name rewrite.") from exc
    if not text or any(byte < 0x20 or byte > 0x7E for byte in encoded):
        raise ValueError(f"{field.field_name} contains characters that are unsafe for this prefab string slot.")
    if "socket" not in text.casefold() or "/" in text or "\\" in text or "." in text:
        raise ValueError(f"{field.field_name} replacement must be a socket name, not a path.")
    if len(encoded) != field.byte_length:
        raise ValueError(
            f"{field.field_name} replacement must be exactly {field.byte_length} byte(s) for the proven safe prefab rewrite; "
            f"{text!r} is {len(encoded)} byte(s)."
        )
    return encoded


def build_prefab_socket_name_patch(
    data: bytes,
    *,
    attached_socket_name: str = "",
    pivot_socket_name: str = "",
) -> PrefabSocketNamePatchResult:
    fields = inspect_prefab_socket_name_fields(data)
    if len(fields) != 2:
        raise ValueError("Prefab socket-name fields were not proven safe to edit.")
    replacements = {
        "_attachedSocketName": attached_socket_name,
        "_pivotSocketName": pivot_socket_name,
    }
    patched = bytearray(data)
    proof_lines: List[str] = [
        "Prefab declares _attachedSocketName and _pivotSocketName as string members.",
        "Socket values were recovered as length-prefixed ASCII records in prefab value order.",
        "Patch is same-length only, so no binary offsets or trailing record positions move.",
    ]
    for field in fields:
        replacement = str(replacements.get(field.field_name) or field.value)
        encoded = _validate_prefab_socket_name_replacement(field, replacement)
        patched[field.value_offset:field.value_offset + field.byte_length] = encoded
        proof_lines.append(f"{field.field_name}: {field.value} -> {replacement}")
    return PrefabSocketNamePatchResult(data=bytes(patched), fields=fields, proof_lines=tuple(proof_lines))


def _asset_family_group_for_entry(
    entry: Optional[ArchiveEntry],
    *,
    relation_group: str = "",
    reference_name: str = "",
) -> str:
    path_text = str(getattr(entry, "path", "") or reference_name).replace("\\", "/").strip()
    basename = PurePosixPath(path_text).name.lower()
    extension = str(getattr(entry, "extension", "") or PurePosixPath(path_text).suffix).strip().lower()
    lowered = " ".join((relation_group, path_text, basename, extension)).casefold()
    if "item icon" in lowered or relation_group == "Item Icons" or _archive_path_is_probable_item_icon(path_text):
        return "Item Icons"
    if "socket" in basename or basename.endswith(".sockets.xml"):
        return "Attachment / Placement"
    if _is_material_sidecar_extension(extension, basename) or "material sidecar" in lowered:
        return "Material"
    if extension == ".pamhc":
        return "Material"
    if extension in {".dds", ".seqmt"} or "texture" in lowered:
        return "Textures"
    if extension in {".hkx", ".hkt"} or "physics" in lowered or "ragdoll" in lowered or "meshphysics" in lowered:
        return "Physics / HKX"
    if extension == ".meshinfo":
        return "MeshInfo"
    if extension in {".prefab", ".prefabdata_xml", ".app_xml", ".pappt"} or "prefab" in lowered:
        return "Prefab / Metadata"
    if extension in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh", ".papr"} or "skeleton" in lowered or "rig" in lowered:
        return "Skeleton / Rig"
    if extension in {".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
        return "Animation / Motion"
    if extension in {".pac", ".pam", ".pamlod"}:
        return "Selected Model"
    return "Other"


def _asset_family_role_for_entry(entry: Optional[ArchiveEntry], *, relation_kind: str = "", relation_group: str = "") -> str:
    extension = str(getattr(entry, "extension", "") or "").strip().lower()
    kind = str(relation_kind or "").strip().lower()
    group = str(relation_group or "").strip().casefold()
    basename = str(getattr(entry, "basename", "") or "").casefold()
    if kind == "item_icon" or "item icon" in group or _archive_path_is_probable_item_icon(str(getattr(entry, "path", "") or "")):
        return "Inventory Icon"
    if "socket" in basename or "socket" in group:
        return "Socket XML"
    if extension in {".pac", ".pam", ".pamlod"} or kind in {RelationKind.MESH.value, RelationKind.LOD.value}:
        return "Model"
    if _is_material_sidecar_extension(extension, str(getattr(entry, "basename", "") or "").lower()) or kind == RelationKind.MATERIAL_SIDECAR.value:
        return "Material Sidecar"
    if extension == ".pamhc":
        return "Model Property Header"
    if extension in {".dds", ".seqmt"} or kind == RelationKind.TEXTURE.value:
        return "Texture"
    if extension in {".hkx", ".hkt"} or kind == "physics" or "physics" in group:
        return "HKX / Physics"
    if extension == ".meshinfo":
        return "MeshInfo"
    if extension in {".prefab", ".prefabdata_xml", ".app_xml", ".pappt"}:
        return "Prefab / Metadata"
    if extension in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh", ".papr"} or kind == RelationKind.SKELETON.value:
        return "Skeleton / Rig"
    if extension in {".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".paseq", ".paschedule", ".paschedulepath", ".pastage"} or kind == RelationKind.ANIMATION.value:
        return "Animation / Motion"
    return "Related File"


def _asset_family_status_for_reference(reference: ArchiveModelTextureReference) -> str:
    status = str(getattr(reference, "resolution_status", "") or "").strip().lower()
    if status == "resolved":
        return "Resolved"
    if status == "technical_only":
        return "Context"
    return "Missing"


def _asset_family_storage_warning(reference: ArchiveModelTextureReference) -> str:
    resolved_entry = getattr(reference, "resolved_entry", None)
    if (
        isinstance(resolved_entry, ArchiveEntry)
        and resolved_entry.extension == ".dds"
        and resolved_entry.compression_type == 1
    ):
        return "Archive texture uses Partial DDS storage; the family relationship itself is resolved."
    return ""


def _asset_family_evidence_chip(
    *,
    confidence: str = "",
    relation_group: str = "",
    reason: str = "",
    role_hint: str = "",
    status: str = "",
) -> str:
    normalized_confidence = str(confidence or "").strip().lower()
    lowered = " ".join((relation_group, reason, role_hint)).casefold()
    if str(status or "").casefold() == "missing":
        return "Missing"
    if "item_finder" in normalized_confidence or "item finder" in lowered:
        return "Item Finder"
    if "table" in normalized_confidence or "table" in lowered or "iteminfo." in lowered:
        return "Table"
    if "material" in lowered or "sidecar" in lowered:
        return "Sidecar"
    if "prefab" in lowered:
        return "Prefab"
    if normalized_confidence in {RelationConfidence.AUTHORITATIVE.value, RelationConfidence.EXACT_PATH.value}:
        return "Exact"
    if normalized_confidence in {RelationConfidence.PATH_NORMALIZED.value, RelationConfidence.CROSS_PACKAGE.value}:
        return "Path hint"
    if normalized_confidence == RelationConfidence.DERIVED_SAME_STEM.value:
        return "Same stem"
    if normalized_confidence == RelationConfidence.DERIVED_FAMILY_HEURISTIC.value:
        return "Name hint"
    return normalized_confidence.replace("_", " ").title() if normalized_confidence else "Name hint"


def _asset_family_include_policy(group: str, status: str, evidence: str) -> str:
    if group == "Selected Model":
        return "required"
    if str(status or "").casefold() not in {"resolved", "context"}:
        return "unresolved"
    if evidence in {"Exact", "Sidecar"}:
        return "required"
    if evidence == "Table":
        return "recommended"
    if group == "Item Icons" and evidence == "Item Finder":
        return "recommended"
    if group in {"Material", "Textures"} and evidence in {"Path hint", "Same stem"}:
        return "required"
    return "manual"


def _asset_family_expected_missing_rows(source_entry: ArchiveEntry, present_groups: set[str]) -> Tuple[AssetFamilyMember, ...]:
    extension = str(source_entry.extension or "").strip().lower()
    if extension not in {".pac", ".pam", ".pamlod"}:
        return ()
    source_path = source_entry.path.replace("\\", "/").strip()
    source_posix = PurePosixPath(source_path)
    source_stem = source_posix.stem
    source_parent = source_posix.parent.as_posix()

    def candidate_path(group: str) -> str:
        if group == "Material":
            if extension == ".pac":
                material_parent = source_parent.replace("/model/", "/modelproperty/")
                return f"{material_parent}/{source_stem}.pac_xml"
            if extension == ".pam":
                return f"{source_parent}/{source_stem}.pami"
            if extension == ".pamlod":
                return f"{source_parent}/{source_stem}.pamlod_xml"
        if group == "MeshInfo":
            return f"{source_parent}/{source_stem}.meshinfo"
        if group == "Physics / HKX":
            return f"{source_parent}/{source_stem}.hkx"
        if group == "Prefab / Metadata":
            return f"{source_parent}/{source_stem}.prefab"
        return source_path

    rows: List[AssetFamilyMember] = []
    for group, role, reason in (
        ("Material", "Material Sidecar", "No same-family material sidecar was resolved from the current archive index."),
        ("MeshInfo", "MeshInfo", "No same-family .meshinfo metadata was resolved from the current archive index."),
        ("Physics / HKX", "HKX / Physics", "No same-family HKX physics/animation file was resolved from the current archive index."),
        ("Prefab / Metadata", "Prefab / Metadata", "No same-family prefab or metadata file was resolved from the current archive index."),
    ):
        if group in present_groups:
            continue
        path_text = candidate_path(group)
        rows.append(
            AssetFamilyMember(
                group=group,
                role=role,
                display_name=PurePosixPath(path_text).name,
                path=path_text,
                status="Missing",
                confidence="Missing",
                source_evidence="Missing",
                include_policy="unresolved",
                reason=reason,
                warning="Not found in current index.",
            )
        )
    return tuple(rows)


def _asset_family_summary(member_rows: Sequence[AssetFamilyMember]) -> str:
    if not member_rows:
        return ""
    rows_by_group: Dict[str, List[AssetFamilyMember]] = defaultdict(list)
    for row in member_rows:
        rows_by_group[row.group].append(row)

    parts: List[str] = []
    source_rows = rows_by_group.get("Selected Model", ())
    if source_rows:
        parts.append("Model OK")

    def add_count(group: str, singular: str, plural: str, *, missing_label: str = "", hint_label: str = "") -> None:
        rows = rows_by_group.get(group, ())
        resolved_rows = [row for row in rows if str(row.status).casefold() in {"resolved", "partial", "context", "selected", "model ok"}]
        missing_rows = [row for row in rows if str(row.status).casefold() == "missing"]
        hint_rows = [
            row for row in resolved_rows
            if str(row.include_policy or "").casefold() not in {"required", "recommended"}
            or str(row.source_evidence or "").casefold() in {"same stem", "name hint", "path hint"}
        ]
        if resolved_rows:
            label = singular if len(resolved_rows) == 1 else plural
            if hint_rows and hint_label:
                parts.append(f"{label} hint")
            else:
                parts.append(f"{len(resolved_rows):,} {label}")
        elif missing_rows and missing_label:
            parts.append(missing_label)

    add_count("Material", "material", "materials", missing_label="material missing")
    add_count("Textures", "texture", "textures", missing_label="textures missing")
    add_count("Item Icons", "item icon", "item icons", hint_label="item icon")
    add_count("Physics / HKX", "HKX", "HKX", missing_label="HKX missing", hint_label="HKX")
    add_count("MeshInfo", "meshinfo", "meshinfo", missing_label="meshinfo missing", hint_label="meshinfo")
    add_count("Prefab / Metadata", "prefab", "prefabs", missing_label="prefab missing", hint_label="prefab")
    add_count("Skeleton / Rig", "skeleton", "skeletons", hint_label="skeleton")
    add_count("Animation / Motion", "animation", "animations", hint_label="animation")
    add_count("Attachment / Placement", "placement chain", "placement chains", hint_label="placement")
    return " | ".join(parts)


def _attachment_paths_from_string_records(string_records: Sequence[object]) -> Tuple[str, ...]:
    paths: List[str] = []
    seen: set[str] = set()
    for record in tuple(string_records or ()):
        text = str(getattr(record, "text", "") or "").strip().replace("\\", "/")
        if not text:
            continue
        for match in _ATTACHMENT_ASSET_REFERENCE_RE.finditer(text):
            raw_path = str(match.group(1) or "").strip().replace("\\", "/")
            if not raw_path:
                continue
            normalized = _normalize_model_texture_reference(raw_path)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            paths.append(raw_path)
    return tuple(paths)


def _choose_attachment_socket_name(names: Sequence[str], priority: Sequence[str], *, child: bool) -> str:
    cleaned = [
        str(name or "").strip()
        for name in names
        if str(name or "").strip() and not str(name or "").strip().startswith("_")
    ]
    if not cleaned:
        return ""
    name_set = {name.casefold(): name for name in cleaned}
    for candidate in priority:
        resolved = name_set.get(candidate.casefold())
        if resolved:
            return resolved
    if child:
        for name in cleaned:
            lowered = name.casefold()
            if "childsocket" in lowered or "pivot_socket" in lowered:
                return name
    else:
        for name in cleaned:
            lowered = name.casefold()
            if (
                "socket" in lowered
                and "childsocket" not in lowered
                and "pivot_socket" not in lowered
                and "inspectsocket" not in lowered
                and "trail" not in lowered
            ):
                return name
    return ""


def _path_with_extension(paths: Sequence[str], extensions: set[str], *, contains: str = "") -> str:
    contains_lower = contains.casefold()
    for path_text in tuple(paths or ()):
        normalized = str(path_text or "").replace("\\", "/").strip()
        if not normalized:
            continue
        suffix = PurePosixPath(normalized).suffix.lower()
        lowered = normalized.casefold()
        if suffix in extensions and (not contains_lower or contains_lower in lowered):
            return normalized
    return ""


def _attachment_prefab_evidence_from_entry(prefab_entry: ArchiveEntry) -> Tuple[AttachmentPlacementEvidence, ...]:
    try:
        data, _decompressed, _note = read_archive_entry_data(prefab_entry)
    except Exception:
        return ()
    try:
        string_records = _extract_binary_string_records(data, sample_limit=262_144, max_strings=512)
    except Exception:
        string_records = []
    texts = [str(getattr(record, "text", "") or "").strip() for record in string_records]
    paths = list(_attachment_paths_from_string_records(string_records))
    declared_fields: List[str] = []
    try:
        schema = _binary_sidecar_schema_declarations(data, ".prefab")
        for row in tuple(schema.get("declared_member_rows", ()) if isinstance(schema, Mapping) else ()):
            if not isinstance(row, Mapping):
                continue
            name = str(row.get("name") or "").strip()
            if name in _ATTACHMENT_PREFAB_FIELD_NAMES and name not in declared_fields:
                declared_fields.append(name)
    except Exception:
        pass
    socket_names = [text for text in texts if "Socket" in text and "/" not in text and "." not in text]
    attached_socket = _choose_attachment_socket_name(
        socket_names,
        _ATTACHMENT_CHARACTER_SOCKET_PRIORITY,
        child=False,
    )
    pivot_socket = _choose_attachment_socket_name(
        socket_names,
        _ATTACHMENT_WEAPON_SOCKET_PRIORITY,
        child=True,
    )
    model_path = _path_with_extension(paths, {".pac", ".pam", ".pamlod"})
    socket_file_path = _path_with_extension(paths, {".xml"}, contains="sockets")
    skeleton_path = _path_with_extension(paths, {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh"}, contains="skeleton")

    if not any((attached_socket, pivot_socket, model_path, socket_file_path, skeleton_path, declared_fields)):
        return ()
    if attached_socket and pivot_socket and socket_file_path:
        confidence = "Exact prefab/socket"
        evidence = "Prefab"
        reason = (
            f"{prefab_entry.basename} declares attachment socket {attached_socket} and weapon pivot {pivot_socket}; "
            "socket XML gives the child-side transform when resolved."
        )
    elif attached_socket or pivot_socket or socket_file_path:
        confidence = "Socket XML only" if socket_file_path and not (attached_socket and pivot_socket) else "Prefab socket hint"
        evidence = "Socket XML" if socket_file_path else "Prefab"
        reason = f"{prefab_entry.basename} contains socket placement fields, but the full character -> weapon chain is incomplete."
    else:
        confidence = "Path hint"
        evidence = "Prefab"
        reason = f"{prefab_entry.basename} contains attachment-related prefab fields; no socket names were recovered."
    placement_modes = ["Raw Model Origin"]
    if attached_socket:
        placement_modes.append("Character Socket")
    if pivot_socket:
        placement_modes.append("Weapon Pivot")
    if attached_socket and pivot_socket:
        placement_modes.append("Final Attachment")
    return (
        AttachmentPlacementEvidence(
            source_path=prefab_entry.path,
            source_kind="prefab",
            prefab_path=prefab_entry.path,
            character_socket_name=attached_socket,
            weapon_socket_name=pivot_socket,
            model_path=model_path,
            socket_file_path=socket_file_path,
            skeleton_path=skeleton_path,
            transform_fields=tuple(declared_fields),
            confidence=confidence,
            evidence=evidence,
            reason=reason,
            placement_modes=tuple(placement_modes),
        ),
    )


def _socket_document_from_entry(entry: ArchiveEntry) -> Optional[AttachmentSocketDocument]:
    basename = PurePosixPath(entry.path.replace("\\", "/")).name.casefold()
    if "socket" not in basename and not basename.endswith(".sockets.xml"):
        return None
    try:
        data, _decompressed, _note = read_archive_entry_data(entry)
    except Exception:
        return None
    text = data.decode("utf-8-sig", errors="ignore")
    document = parse_socket_bone_data_xml(text, source_path=entry.path)
    if not document.sockets and not document.stack_equip_infos:
        return None
    return document


def _socket_document_evidence_from_entry(entry: ArchiveEntry, document: AttachmentSocketDocument) -> AttachmentPlacementEvidence:
    preferred_stack = next(
        (
            stack
            for stack in document.stack_equip_infos
            if str(stack.equip_type_name or "").casefold() in {"back", "pelvis_l", "pelvis_r", "right_hand", "left_hand"}
        ),
        document.stack_equip_infos[0] if document.stack_equip_infos else AttachmentStackEquipInfo(source_path=entry.path),
    )
    first_socket_name = preferred_stack.socket_names[0] if preferred_stack.socket_names else (
        document.sockets[0].name if document.sockets else ""
    )
    return AttachmentPlacementEvidence(
        source_path=entry.path,
        source_kind="socket_xml",
        character_socket_name=first_socket_name if preferred_stack.equip_type_name else "",
        socket_file_path=entry.path,
        confidence="Socket XML only",
        evidence="Socket XML",
        reason=(
            f"{entry.basename} defines {len(document.sockets):,} socket(s)"
            + (f" and StackEquipInfo {preferred_stack.equip_type_name}." if preferred_stack.equip_type_name else ".")
        ),
        placement_modes=("Raw Model Origin", "Character Socket") if first_socket_name else ("Raw Model Origin",),
    )


def _find_socket_info(
    documents: Sequence[AttachmentSocketDocument],
    socket_name: str,
    *,
    preferred_path: str = "",
) -> Optional[AttachmentSocketInfo]:
    normalized_preferred = _normalize_model_texture_reference(preferred_path)
    fallback: Optional[AttachmentSocketInfo] = None
    for document in tuple(documents or ()):
        for socket in tuple(getattr(document, "sockets", ()) or ()):
            if socket.name.casefold() != str(socket_name or "").casefold():
                continue
            if normalized_preferred and _normalize_model_texture_reference(socket.source_path) == normalized_preferred:
                return socket
            if fallback is None:
                fallback = socket
    return fallback


def _enrich_attachment_evidence_with_socket_documents(
    evidence: AttachmentPlacementEvidence,
    documents: Sequence[AttachmentSocketDocument],
) -> AttachmentPlacementEvidence:
    character_socket = _find_socket_info(documents, evidence.character_socket_name)
    weapon_socket = _find_socket_info(documents, evidence.weapon_socket_name, preferred_path=evidence.socket_file_path)
    if character_socket is None and weapon_socket is None:
        return evidence
    return replace(
        evidence,
        character_socket_parent=character_socket.parent if character_socket is not None else evidence.character_socket_parent,
        character_socket_translation=character_socket.translation if character_socket is not None else evidence.character_socket_translation,
        character_socket_rotation=character_socket.rotation if character_socket is not None else evidence.character_socket_rotation,
        weapon_socket_parent=weapon_socket.parent if weapon_socket is not None else evidence.weapon_socket_parent,
        weapon_socket_translation=weapon_socket.translation if weapon_socket is not None else evidence.weapon_socket_translation,
        weapon_socket_rotation=weapon_socket.rotation if weapon_socket is not None else evidence.weapon_socket_rotation,
    )


def _asset_family_attachment_evidence(source_entry: ArchiveEntry, member_rows: Sequence[AssetFamilyMember]) -> Tuple[AttachmentPlacementEvidence, ...]:
    entries: List[ArchiveEntry] = [source_entry]
    for row in tuple(member_rows or ()):
        entry = getattr(row, "resolved_entry", None)
        if isinstance(entry, ArchiveEntry) and entry not in entries:
            entries.append(entry)

    socket_documents: List[AttachmentSocketDocument] = []
    prefab_evidence: List[AttachmentPlacementEvidence] = []
    socket_only_evidence: List[AttachmentPlacementEvidence] = []
    for entry in entries:
        extension = str(entry.extension or "").lower()
        if extension in {".prefab", ".pappt"}:
            prefab_evidence.extend(_attachment_prefab_evidence_from_entry(entry))
        document = _socket_document_from_entry(entry)
        if document is not None:
            socket_documents.append(document)
            socket_only_evidence.append(_socket_document_evidence_from_entry(entry, document))

    enriched = [
        _enrich_attachment_evidence_with_socket_documents(evidence, socket_documents)
        for evidence in prefab_evidence
    ]
    if enriched:
        return tuple(enriched)
    return tuple(socket_only_evidence[:4])


def _attachment_evidence_display_name(evidence: AttachmentPlacementEvidence) -> str:
    character_socket = str(evidence.character_socket_name or "").strip()
    weapon_socket = str(evidence.weapon_socket_name or "").strip()
    model_name = PurePosixPath(str(evidence.model_path or evidence.prefab_path or evidence.socket_file_path or "").replace("\\", "/")).name
    if character_socket and weapon_socket:
        return f"{character_socket} -> {weapon_socket}"
    if character_socket:
        return character_socket
    if weapon_socket:
        return weapon_socket
    return model_name or "Attachment placement"


def build_archive_asset_family_graph(
    source_entry: ArchiveEntry,
    references: Sequence[ArchiveModelTextureReference],
) -> AssetFamilyGraph:
    grouped_paths: Dict[str, List[str]] = defaultdict(list)
    relations: List[AssetRelation] = []
    member_rows: List[AssetFamilyMember] = []
    member_paths: List[str] = []
    seen_members: set[str] = set()
    seen_member_rows: set[Tuple[str, str, str]] = set()

    def add_member(raw_value: str) -> None:
        normalized = str(raw_value or "").strip().replace("\\", "/")
        if not normalized or normalized in seen_members:
            return
        seen_members.add(normalized)
        member_paths.append(normalized)

    def add_member_row(row: AssetFamilyMember) -> None:
        key = (row.group, row.path.replace("\\", "/").casefold(), row.display_name.casefold())
        if key in seen_member_rows:
            return
        seen_member_rows.add(key)
        member_rows.append(row)

    add_member(source_entry.path)
    source_group = "Selected Model" if source_entry.extension in {".pac", ".pam", ".pamlod"} else _asset_family_group_for_entry(source_entry)
    add_member_row(
        AssetFamilyMember(
            group=source_group,
            role=_asset_family_role_for_entry(source_entry),
            display_name=source_entry.basename,
            path=source_entry.path,
            status="Model OK" if source_group == "Selected Model" else "Selected",
            confidence="Exact",
            source_evidence="Selected",
            include_policy="required",
            reason="The file currently selected in Archive Browser.",
            resolved_entry=source_entry,
        )
    )

    for reference in references:
        relation_group = str(getattr(reference, "relation_group", "") or "").strip() or "Metadata / Other"
        target_path = str(getattr(reference, "resolved_archive_path", "") or "").strip()
        if not target_path:
            target_path = str(getattr(reference, "reference_name", "") or "").strip().replace("\\", "/")
        if not target_path:
            continue
        resolved_entry = getattr(reference, "resolved_entry", None)
        if not isinstance(resolved_entry, ArchiveEntry):
            resolved_entry = None
        add_member(target_path)
        family_group = _asset_family_group_for_entry(
            resolved_entry,
            relation_group=relation_group,
            reference_name=target_path,
        )
        if target_path not in grouped_paths[family_group]:
            grouped_paths[family_group].append(target_path)
        status = _asset_family_status_for_reference(reference)
        confidence = str(getattr(reference, "relation_confidence", "") or RelationConfidence.DERIVED_SAME_STEM.value)
        role_hint = str(getattr(reference, "semantic_hint", "") or "").strip()
        reason = str(getattr(reference, "relation_reason", "") or "").strip()
        source_table = str(getattr(reference, "source_table", "") or "").strip()
        source_field = str(getattr(reference, "source_field", "") or "").strip()
        field_label = table_field_label(source_table, source_field)
        if field_label and field_label not in reason:
            reason = f"{reason} ({field_label})" if reason else f"Referenced by {field_label}"
        evidence = _asset_family_evidence_chip(
            confidence=confidence,
            relation_group=relation_group,
            reason=reason,
            role_hint=role_hint,
            status=status,
        )
        include_policy = _asset_family_include_policy(family_group, status, evidence)
        storage_warning = _asset_family_storage_warning(reference)
        warning = storage_warning or (
            "Weak relationship hint; review before treating as required." if include_policy == "manual" else ""
        )
        relation_kind = str(getattr(reference, "reference_kind", "") or _relation_kind_for_entry(resolved_entry))
        display_name = (
            PurePosixPath(resolved_entry.path.replace("\\", "/")).name
            if isinstance(resolved_entry, ArchiveEntry)
            else PurePosixPath(target_path.replace("\\", "/")).name
        )
        add_member_row(
            AssetFamilyMember(
                group=family_group,
                role=_asset_family_role_for_entry(
                    resolved_entry,
                    relation_kind=relation_kind,
                    relation_group=relation_group,
                ),
                display_name=display_name,
                path=target_path,
                status=status,
                confidence=evidence,
                source_evidence=evidence,
                include_policy=include_policy,
                reason=reason or "Recovered relationship evidence from the current archive index.",
                warning=warning,
                resolved_entry=resolved_entry,
                source_table=source_table,
                source_field=source_field,
            )
        )
        relations.append(
            AssetRelation(
                source_path=source_entry.path,
                target_path=target_path,
                relation_kind=relation_kind,
                confidence=confidence,
                role_label=str(getattr(reference, "semantic_label", "") or "").strip(),
                status=status,
                source_evidence=evidence,
                include_policy=include_policy,
                warning=warning,
                reason=reason,
                source_entry=source_entry,
                target_entry=resolved_entry,
                semantic_label=str(getattr(reference, "semantic_label", "") or "").strip(),
                semantic_hint=str(getattr(reference, "semantic_hint", "") or "").strip(),
                sidecar_parameter_name=str(getattr(reference, "sidecar_parameter_name", "") or "").strip(),
                material_name=str(getattr(reference, "material_name", "") or "").strip(),
                package_label=str(getattr(reference, "resolved_package_label", "") or "").strip(),
                source_table=source_table,
                source_field=source_field,
            )
        )
    present_groups = {row.group for row in member_rows if str(row.status).casefold() != "missing"}
    for row in _asset_family_expected_missing_rows(source_entry, present_groups):
        add_member_row(row)
        if row.path and row.path not in grouped_paths[row.group]:
            grouped_paths[row.group].append(row.path)

    attachment_evidence = _asset_family_attachment_evidence(source_entry, member_rows)
    for evidence in attachment_evidence:
        for evidence_path in (evidence.prefab_path, evidence.socket_file_path, evidence.skeleton_path, evidence.model_path):
            if evidence_path:
                add_member(evidence_path)
        display_name = _attachment_evidence_display_name(evidence)
        status = "Context" if str(evidence.confidence or "").casefold() != "no placement chain" else "Missing"
        reason = evidence.reason or "Recovered attachment placement evidence. Placement writes are not enabled from this view."
        row = AssetFamilyMember(
            group="Attachment / Placement",
            role="Socket Chain",
            display_name=display_name,
            path=evidence.prefab_path or evidence.socket_file_path or source_entry.path,
            status=status,
            confidence=evidence.confidence,
            source_evidence=evidence.evidence,
            include_policy="manual",
            reason=reason,
            warning="Read-only placement evidence; XML/binary placement writes remain gated.",
            resolved_entry=None,
        )
        add_member_row(row)
        if row.path and row.path not in grouped_paths[row.group]:
            grouped_paths[row.group].append(row.path)

    order_index = {group: index for index, group in enumerate(_asset_family_group_order())}
    member_rows.sort(
        key=lambda row: (
            order_index.get(row.group, 99),
            1 if str(row.status).casefold() == "missing" else 0,
            row.display_name.casefold(),
        )
    )
    return AssetFamilyGraph(
        root_path=source_entry.path,
        family_key=PurePosixPath(source_entry.path.replace("\\", "/")).stem,
        members=tuple(member_paths),
        member_rows=tuple(member_rows),
        relations=tuple(relations),
        attachment_evidence=tuple(attachment_evidence),
        grouped_paths={key: tuple(value) for key, value in grouped_paths.items()},
        summary=_asset_family_summary(member_rows),
    )


def _find_archive_texture_family_entries(
    source_entry: ArchiveEntry,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
) -> Tuple[ArchiveEntry, ...]:
    if archive_entries_by_normalized_path is None:
        return ()
    extension = str(source_entry.extension or "").strip().lower()
    normalized_path = normalize_texture_reference_for_sidecar_lookup(source_entry.path)
    if extension != ".dds" or not normalized_path:
        return ()

    group_key = derive_texture_group_key(normalized_path)
    if not group_key:
        return ()
    if "/" in group_key:
        folder, family = group_key.rsplit("/", 1)
    else:
        folder, family = "", group_key
    if not family:
        return ()

    candidates: List[ArchiveEntry] = []
    seen_paths: set[str] = set()
    source_normalized = _normalize_model_texture_reference(source_entry.path)
    for suffix in _ARCHIVE_TEXTURE_FAMILY_SUFFIXES:
        candidate_path = f"{folder}/{family}{suffix}.dds" if folder else f"{family}{suffix}.dds"
        normalized_candidate_path = _normalize_model_texture_reference(candidate_path)
        for candidate in archive_entries_by_normalized_path.get(normalized_candidate_path, ()):
            normalized_candidate = _normalize_model_texture_reference(candidate.path)
            if normalized_candidate in seen_paths or normalized_candidate == source_normalized:
                continue
            seen_paths.add(normalized_candidate)
            candidates.append(candidate)

    if not candidates:
        return ()
    candidates.sort(key=lambda candidate: _score_model_related_entry_candidate(source_entry, candidate), reverse=True)
    return tuple(candidates[:16])


def _find_archive_texture_referencing_sidecar_entries(
    source_entry: ArchiveEntry,
    *,
    sidecar_entries_by_texture_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_entries_by_texture_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveEntry, ...]:
    normalized_path = normalize_texture_reference_for_sidecar_lookup(source_entry.path)
    if not normalized_path:
        return ()
    basename = PurePosixPath(normalized_path).name
    candidates: List[ArchiveEntry] = []
    seen_paths: set[str] = set()

    def add_candidate(entry: ArchiveEntry) -> None:
        normalized_candidate = _normalize_model_texture_reference(entry.path)
        if not normalized_candidate or normalized_candidate == _normalize_model_texture_reference(source_entry.path):
            return
        if normalized_candidate in seen_paths:
            return
        seen_paths.add(normalized_candidate)
        candidates.append(entry)

    if sidecar_entries_by_texture_path is not None:
        for candidate in sidecar_entries_by_texture_path.get(normalized_path, ()):
            add_candidate(candidate)
    if sidecar_entries_by_texture_basename is not None and basename:
        for candidate in sidecar_entries_by_texture_basename.get(basename, ()):
            add_candidate(candidate)
    return tuple(candidates)


def _collect_archive_texture_sidecar_texts_from_entries(
    sidecar_entries: Sequence[ArchiveEntry],
    *,
    limit: int = 6,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[str, ...]:
    texts: List[str] = []
    seen_texts: set[str] = set()
    for sidecar_entry in sidecar_entries:
        raise_if_cancelled(stop_event)
        try:
            raw_data, _decompressed, _note = read_archive_entry_data(sidecar_entry, stop_event=stop_event)
        except Exception:
            continue
        text = str(try_decode_text_like_archive_data(raw_data) or "").strip()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        texts.append(text)
        if len(texts) >= limit:
            break
    return tuple(texts)


def build_archive_entry_related_references(
    source_entry: ArchiveEntry,
    *,
    text: str = "",
    binary_data: bytes = b"",
    explicit_reference_names: Sequence[str] = (),
    companion_entries: Sequence[ArchiveEntry] = (),
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_entries_by_texture_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_entries_by_texture_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveModelTextureReference, ...]:
    combined_reference_names: List[str] = []
    seen_reference_names: set[str] = set()

    def add_reference_name(raw_value: str) -> None:
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized or normalized in seen_reference_names:
            return
        seen_reference_names.add(normalized)
        combined_reference_names.append(str(raw_value or "").strip().replace("\\", "/"))

    for reference_name in explicit_reference_names:
        add_reference_name(reference_name)
    if text:
        for reference_name in _extract_text_asset_references(text, sidecar_path=source_entry.path):
            add_reference_name(reference_name)
    elif binary_data:
        for reference_name in _extract_binary_asset_references(binary_data, sample_limit=262_144, max_references=64):
            add_reference_name(reference_name)

    combined_companion_entries: List[ArchiveEntry] = []
    seen_companion_paths: set[str] = set()

    def add_companion_entry(candidate: ArchiveEntry) -> None:
        normalized_candidate = _normalize_model_texture_reference(candidate.path)
        if not normalized_candidate or normalized_candidate == _normalize_model_texture_reference(source_entry.path):
            return
        if normalized_candidate in seen_companion_paths:
            return
        seen_companion_paths.add(normalized_candidate)
        combined_companion_entries.append(candidate)

    for candidate in companion_entries:
        add_companion_entry(candidate)
    for candidate in _find_archive_model_related_entries(source_entry, archive_entries_by_basename):
        add_companion_entry(candidate)
    for candidate in _find_archive_texture_family_entries(source_entry, archive_entries_by_normalized_path):
        add_companion_entry(candidate)
    if str(source_entry.extension or "").strip().lower() == ".dds":
        for candidate in _find_archive_texture_referencing_sidecar_entries(
            source_entry,
            sidecar_entries_by_texture_path=sidecar_entries_by_texture_path,
            sidecar_entries_by_texture_basename=sidecar_entries_by_texture_basename,
        ):
            add_companion_entry(candidate)
            for related_candidate in _find_archive_model_related_entries(candidate, archive_entries_by_basename):
                add_companion_entry(related_candidate)

    return build_archive_related_file_references(
        source_entry,
        explicit_reference_names=combined_reference_names,
        companion_entries=combined_companion_entries,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )


def build_meshinfo_preview(
    data: bytes,
    virtual_path: str,
    *,
    source_entry: Optional[ArchiveEntry] = None,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> _StructuredBinaryPreviewBundle:
    strings = extract_binary_strings(data, sample_limit=262_144, max_strings=256)
    field_names = sorted({text for text in strings if _looks_like_structured_field_name(text)}, key=str.casefold)
    asset_references = _extract_binary_asset_references(data, sample_limit=262_144, max_references=64)
    related_references = _build_binary_sidecar_related_references(
        source_entry,
        asset_references=asset_references,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    sidecar_document = build_binary_sidecar_analysis_document(
        data,
        virtual_path,
        extension=".meshinfo",
        source_entry=source_entry,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    summary = sidecar_document.get("summary", {})
    container = sidecar_document.get("container", {})
    tables = sidecar_document.get("tables", {})
    schema_declarations = sidecar_document.get("schema_declarations", {})
    declared_rows = (
        list(schema_declarations.get("declared_member_rows") or [])
        if isinstance(schema_declarations, Mapping)
        else []
    )
    strings_preview = build_binary_strings_preview(data, sample_limit=65_536, max_strings=32)
    header_preview = format_binary_header_preview(data)
    lines = [f"MeshInfo inspector for {virtual_path}", "", "Summary:"]
    lines.append(f"- Declared member rows: {len(declared_rows):,}")
    lines.append(f"- Field-like entries: {len(field_names):,}")
    lines.append(f"- Readable strings: {len(strings):,}")
    lines.append(f"- Related asset hints: {len(asset_references):,}")
    if related_references:
        resolved_count = sum(1 for reference in related_references if reference.resolved_entry is not None)
        lines.append(f"- Resolved related files: {resolved_count:,} / {len(related_references):,}")
    lines.append(f"- Container family: {container.get('recognized_family') or 'unknown'}")
    if isinstance(schema_declarations, Mapping) and schema_declarations.get("layout_signature"):
        lines.append(f"- Declaration layout signature: {schema_declarations.get('layout_signature')}")
    lines.append(f"- Candidate offsets: {int(summary.get('offset_candidates') or 0):,}")
    lines.append(f"- Candidate count/offset tables: {int(summary.get('count_offset_pair_candidates') or 0):,}")
    lines.append(f"- Candidate float/vector rows: {int(summary.get('float_vector_candidates') or 0):,}")
    lines.append("- Editing: read-only until MeshInfo schema and no-edit rebuilds are proven.")

    if declared_rows:
        lines.extend(["", "Declared Fields:"])
        lines.extend(
            _build_grouped_schema_declaration_lines(
                [row for row in declared_rows if isinstance(row, Mapping)],
                section_order=("Physics", "Collision", "Breakable", "Bounds", "Sockets", "Tree", "Data Model", "Misc"),
            )
        )
    else:
        lines.extend(
            _build_grouped_structured_section_lines(
                field_names,
                group_func=_group_meshinfo_field_name,
                section_order=("Physics", "Collision", "Breakable", "Bounds", "Sockets", "Tree", "Data Model", "Misc"),
            )
        )
    if asset_references:
        lines.extend(["", "Detected asset references:"])
        lines.extend(f"  - {reference}" for reference in asset_references[:24])
        if len(asset_references) > 24:
            lines.append(f"  ... {len(asset_references) - 24} more")
    count_offset_pairs = list(tables.get("count_offset_pair_candidates") or []) if isinstance(tables, Mapping) else []
    if count_offset_pairs:
        lines.extend(["", "Candidate count/offset tables:"])
        for row in count_offset_pairs[:8]:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "  - "
                f"offset 0x{int(row.get('owner_offset') or 0):X}: "
                f"count={int(row.get('count') or 0):,}, data=0x{int(row.get('data_offset') or 0):X}, "
                f"confidence={row.get('confidence') or 'candidate'}"
            )
    offset_candidates = list(tables.get("offset_candidates") or []) if isinstance(tables, Mapping) else []
    if offset_candidates:
        lines.extend(["", "Candidate internal offsets:"])
        for row in offset_candidates[:8]:
            if not isinstance(row, Mapping):
                continue
            preview = str(row.get("target_preview") or "").strip()
            suffix = f" -> {preview}" if preview else ""
            lines.append(
                "  - "
                f"slot 0x{int(row.get('owner_offset') or 0):X} -> 0x{int(row.get('target_offset') or 0):X}"
                f" ({row.get('confidence') or 'candidate'}){suffix}"
            )
    float_rows = list(tables.get("float_vector_candidates") or []) if isinstance(tables, Mapping) else []
    if float_rows:
        lines.extend(["", "Candidate numeric/vector rows:"])
        for row in float_rows[:8]:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "  - "
                f"0x{int(row.get('offset') or 0):X} {row.get('type') or 'float'} = {row.get('values')}"
            )
    if strings_preview:
        lines.extend(["", strings_preview])
    lines.extend(["", "Binary header preview:", header_preview])

    detail_lines = [
        f"Detected {len(declared_rows):,} declared member row(s) and {len(field_names):,} field-like identifier(s) from the preview sample.",
        "Declared fields come from length-prefixed member/type rows; raw strings remain separate recovery evidence.",
        "Sidecar JSON export includes string offsets, header words, related files, candidate offsets, count/offset tables, and numeric rows.",
        "Direct editing is disabled because MeshInfo count/offset semantics are not stable enough for safe writes yet.",
    ]
    if asset_references:
        detail_lines.append(f"Detected {len(asset_references):,} related asset reference(s).")
    if related_references:
        detail_lines.append(f"Matched {len(related_references):,} related archive file row(s).")

    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(lines),
        detail_lines=tuple(detail_lines),
        related_references=related_references,
        metadata_label="Mesh Metadata",
    )


def build_par_structured_preview(
    data: bytes,
    virtual_path: str,
    *,
    extension: str,
    source_entry: Optional[ArchiveEntry] = None,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> _StructuredBinaryPreviewBundle:
    strings = extract_binary_strings(data, sample_limit=262_144, max_strings=224)
    field_names = sorted({text for text in strings if _looks_like_structured_field_name(text)}, key=str.casefold)
    asset_references = _extract_binary_asset_references(data, sample_limit=262_144, max_references=64)
    strings_preview = build_binary_strings_preview(data, sample_limit=65_536, max_strings=32)
    header_preview = format_binary_header_preview(data)
    markers = [
        marker
        for marker in ("AnimationMetaData", "ParameterizedMotionSpace", "Sequencer", "SceneObject", "EmitterData")
        if marker in data[:16_384].decode("latin-1", errors="ignore")
        or marker in strings
    ]
    companion_entries = (
        _find_archive_model_related_entries(source_entry, archive_entries_by_basename)
        if source_entry is not None and archive_entries_by_basename is not None
        else ()
    )
    related_references = _build_binary_sidecar_related_references(
        source_entry,
        asset_references=asset_references,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    sidecar_document = build_binary_sidecar_analysis_document(
        data,
        virtual_path,
        extension=extension,
        source_entry=source_entry,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    summary = sidecar_document.get("summary", {})
    container = sidecar_document.get("container", {})
    tables = sidecar_document.get("tables", {})
    schema_declarations = sidecar_document.get("schema_declarations", {})
    declared_rows = (
        list(schema_declarations.get("declared_member_rows") or [])
        if isinstance(schema_declarations, Mapping)
        else []
    )
    animation_metadata = (
        sidecar_document.get("animation_metadata", {})
        if str(extension or "").strip().lower() == ".paa_metabin"
        else {}
    )

    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension == ".paa":
        title = "PAA animation inspector"
        metadata_label = "Animation"
    elif normalized_extension == ".paa_metabin":
        title = "PAA animation metadata inspector"
        metadata_label = "Animation Metadata"
    elif normalized_extension in {".pae", ".paem"}:
        title = "PAE effect inspector"
        metadata_label = "Effect"
    elif normalized_extension == ".motionblending":
        title = "Motion blending inspector"
        metadata_label = "Motion Blending"
    elif normalized_extension in {".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
        title = "Animation schedule inspector"
        metadata_label = "Animation / Schedule Metadata"
    else:
        title = f"{normalized_extension.lstrip('.').upper()} structured inspector"
        metadata_label = "Structured Binary"

    lines = [f"{title} for {virtual_path}", "", "Summary:"]
    lines.append(f"- Declared member rows: {len(declared_rows):,}")
    lines.append(f"- Field-like entries: {len(field_names):,}")
    lines.append(f"- Readable strings: {len(strings):,}")
    if markers:
        lines.append(f"- Detected markers: {', '.join(markers)}")
    if isinstance(animation_metadata, Mapping) and animation_metadata:
        declared_type = str(animation_metadata.get("declared_type") or "").strip()
        animation_stem = str(animation_metadata.get("animation_stem") or "").strip()
        stream = animation_metadata.get("packed_metadata_stream", {})
        if declared_type:
            lines.append(f"- Declared metadata type: {declared_type}")
        if animation_stem:
            lines.append(f"- Animation stem: {animation_stem}")
        if isinstance(stream, Mapping):
            lines.append(f"- Packed metadata stream: {int(stream.get('stream_size') or 0):,} byte(s)")
    if asset_references:
        lines.append(f"- Related asset hints: {len(asset_references):,}")
    if related_references:
        resolved_count = sum(1 for reference in related_references if reference.resolved_entry is not None)
        lines.append(f"- Resolved related files: {resolved_count:,} / {len(related_references):,}")
    if companion_entries:
        lines.append(f"- Same-stem companion files: {len(companion_entries):,}")
    lines.append(f"- Container family: {container.get('recognized_family') or 'unknown'}")
    if isinstance(schema_declarations, Mapping) and schema_declarations.get("layout_signature"):
        lines.append(f"- Declaration layout signature: {schema_declarations.get('layout_signature')}")
    lines.append(f"- Candidate offsets: {int(summary.get('offset_candidates') or 0):,}")
    lines.append(f"- Candidate count/offset tables: {int(summary.get('count_offset_pair_candidates') or 0):,}")
    lines.append(f"- Candidate float/vector rows: {int(summary.get('float_vector_candidates') or 0):,}")
    if normalized_extension == ".paa":
        lines.append(f"- Candidate animation keyframe tables: {int(summary.get('animation_keyframe_table_candidates') or 0):,}")
        lines.append(f"- Candidate animation keyframe rows: {int(summary.get('animation_keyframe_rows') or 0):,}")
    if normalized_extension == ".motionblending":
        lines.append("- Editing: read-only until motion-blending schema and no-edit rebuilds are proven.")
    elif normalized_extension == ".paa":
        lines.append("- Editing: read-only until animation channel ownership, compression rules, and no-edit rebuilds are proven.")
    elif normalized_extension == ".paa_metabin":
        lines.append("- Editing: read-only; this metadata sidecar is used for browsing and relationships only.")

    if isinstance(animation_metadata, Mapping) and animation_metadata:
        hint_rows = [
            row
            for row in animation_metadata.get("filename_hints") or []
            if isinstance(row, Mapping)
        ]
        if hint_rows:
            lines.extend(["", "Filename-derived animation hints:"])
            for row in hint_rows[:18]:
                lines.append(
                    "  - "
                    f"{row.get('kind') or 'Hint'}: {row.get('meaning') or '-'} "
                    f"(token={row.get('token') or '-'}, confidence={row.get('confidence') or 'filename_token'})"
                )
        header_rows = [
            row
            for row in animation_metadata.get("header_rows") or []
            if isinstance(row, Mapping)
        ]
        if header_rows:
            lines.extend(["", "Stable header evidence:"])
            for row in header_rows[:10]:
                lines.append(
                    "  - "
                    f"0x{int(row.get('offset') or 0):X} {row.get('name') or 'word'} = {row.get('value')}; "
                    f"confidence={row.get('confidence') or 'observed'}"
                )
        stream = animation_metadata.get("packed_metadata_stream", {})
        if isinstance(stream, Mapping):
            marker_counts = stream.get("marker_counts") if isinstance(stream.get("marker_counts"), Mapping) else {}
            if marker_counts:
                marker_text = ", ".join(f"{key}:{value}" for key, value in list(marker_counts.items())[:8])
                lines.extend(["", "Packed metadata stream:"])
                lines.append(
                    f"  - offset=0x{int(stream.get('stream_offset') or 0):X}, "
                    f"size={int(stream.get('stream_size') or 0):,}, markers={marker_text}"
                )
                lines.append("  - Stream rows are shown as recovery evidence only; their tuple semantics are not proven.")
            preview_rows = [
                row
                for row in stream.get("preview_rows") or []
                if isinstance(row, Mapping)
            ]
            if preview_rows:
                lines.append("  - First packed bytes:")
                for row in preview_rows[:6]:
                    lines.append(f"    0x{int(row.get('offset') or 0):X}: {row.get('hex') or ''}")

    if declared_rows:
        lines.extend(["", "Declared Fields:"])
        motion_section_order = (
            ("Skeleton", "Animation Files", "Motion Space", "Parameters", "Delaunay", "Scene / Object", "Resources", "Misc")
            if normalized_extension == ".motionblending"
            else ("Animation Files", "Motion Space", "Parameters", "Emitter / Effect", "Scene / Object", "Resources", "Misc")
        )
        lines.extend(
            _build_grouped_schema_declaration_lines(
                [row for row in declared_rows if isinstance(row, Mapping)],
                section_order=motion_section_order,
            )
        )
    else:
        section_order = (
            ("Skeleton", "Animation Files", "Motion Space", "Parameters", "Delaunay", "Scene / Object", "Resources", "Misc")
            if normalized_extension == ".motionblending"
            else ("Animation Files", "Motion Space", "Parameters", "Emitter / Effect", "Scene / Object", "Resources", "Misc")
        )
        lines.extend(
            _build_grouped_structured_section_lines(
                field_names,
                group_func=_group_animation_field_name,
                section_order=section_order,
            )
        )
    if asset_references:
        lines.extend(["", "Detected asset references:"])
        lines.extend(f"  - {reference}" for reference in asset_references[:24])
        if len(asset_references) > 24:
            lines.append(f"  ... {len(asset_references) - 24} more")
    animation_keyframes = list(tables.get("animation_keyframe_table_candidates") or []) if isinstance(tables, Mapping) else []
    if animation_keyframes:
        lines.extend(["", "Candidate animation keyframe tables:"])
        for row in animation_keyframes[:6]:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "  - "
                f"offset 0x{int(row.get('offset') or 0):X}: "
                f"{int(row.get('row_count') or 0):,} row(s), "
                f"frames {int(row.get('frame_start') or 0):,}-{int(row.get('frame_end') or 0):,}, "
                f"{row.get('row_format') or 'keyframe rows'}, "
                f"{row.get('value_kind') or 'half-float values'}, "
                f"confidence={row.get('confidence') or 'candidate'}"
            )
            preview_rows = [preview_row for preview_row in row.get("preview_rows") or [] if isinstance(preview_row, Mapping)]
            for preview_row in preview_rows[:4]:
                lines.append(
                    "    "
                    f"0x{int(preview_row.get('offset') or 0):X} "
                    f"frame={int(preview_row.get('frame') or 0):,} "
                    f"values={preview_row.get('values')} "
                    f"norm={preview_row.get('norm')}"
                )
        lines.append("  - Keyframe rows are read-only recovery evidence; exact animation channels are not proven.")
    count_offset_pairs = list(tables.get("count_offset_pair_candidates") or []) if isinstance(tables, Mapping) else []
    if count_offset_pairs:
        lines.extend(["", "Candidate count/offset tables:"])
        for row in count_offset_pairs[:8]:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "  - "
                f"offset 0x{int(row.get('owner_offset') or 0):X}: "
                f"count={int(row.get('count') or 0):,}, data=0x{int(row.get('data_offset') or 0):X}, "
                f"confidence={row.get('confidence') or 'candidate'}"
            )
    float_rows = list(tables.get("float_vector_candidates") or []) if isinstance(tables, Mapping) else []
    if float_rows:
        lines.extend(["", "Candidate numeric/vector rows:"])
        for row in float_rows[:8]:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "  - "
                f"0x{int(row.get('offset') or 0):X} {row.get('type') or 'float'} = {row.get('values')}"
            )
    if strings_preview:
        lines.extend(["", strings_preview])
    else:
        lines.extend(["", "Readable strings:", "  None detected in the preview sample."])
    lines.extend(["", "Binary header preview:", header_preview])

    detail_lines = [
        f"Detected {len(declared_rows):,} declared member row(s) and {len(field_names):,} field-like identifier(s) from the preview sample.",
    ]
    if declared_rows:
        detail_lines.append("Declared fields come from length-prefixed member/type rows; raw strings remain separate recovery evidence.")
    if markers:
        detail_lines.append(f"Detected structured marker(s): {', '.join(markers)}.")
    if not field_names and not markers and not strings:
        detail_lines.append("No readable strings or structured markers were detected, so the preview falls back to raw header bytes.")
    if asset_references:
        detail_lines.append(f"Detected {len(asset_references):,} related asset reference(s).")
    if related_references:
        detail_lines.append(f"Matched {len(related_references):,} related archive file row(s).")
    if normalized_extension == ".paa":
        detail_lines.append(
            "This inspector summarizes animation clip metadata, candidate half-float keyframe rows, and readable markers. Playback/editing is not implemented yet."
        )
    elif normalized_extension in {".pae", ".paem"}:
        detail_lines.append("This inspector summarizes effect/emitter-side metadata and readable markers. Real particle or timeline playback is not implemented yet.")
    elif normalized_extension == ".motionblending":
        detail_lines.append(
            "This inspector summarizes motion/blend references, candidate tables, and numeric rows. Playback/editing is still disabled until the schema is stable."
        )
    elif normalized_extension == ".paa_metabin":
        detail_lines.append(
            "This inspector summarizes AnimationMetaData headers, filename-derived motion hints, same-stem relationships, and packed metadata bytes. Editing is disabled."
        )
    elif normalized_extension in {".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
        detail_lines.append(
            "This inspector summarizes animation schedule/sequence metadata and same-stem motion references. Editing and playback remain disabled."
        )

    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(lines),
        detail_lines=tuple(detail_lines),
        related_references=related_references,
        metadata_label=metadata_label,
    )


def _structured_asset_profile(
    extension: str,
) -> Tuple[str, str, Callable[[str], str], Tuple[str, ...], str]:
    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension == ".prefab":
        return (
            "Prefab inspector",
            "Prefab",
            _group_prefab_field_name,
            (
                "Scene / Object",
                "Resources",
                "Skeleton / Sockets",
                "Mesh / Cloth",
                "Transform / Bounds",
                "Physics / Collision",
                "Logic / Events",
                "Presentation",
                "Misc",
            ),
            "Summarizes object composition, resource links, transforms, collision, and event-like markers when readable. A .prefab is metadata, not the renderable mesh; linked .pac/.pam/.pamlod files usually hold geometry.",
        )
    if normalized_extension == ".pappt":
        return (
            "Part prefab table inspector",
            "Part Prefab Metadata",
            _group_prefab_field_name,
            (
                "Scene / Object",
                "Resources",
                "Skeleton / Sockets",
                "Mesh / Cloth",
                "Transform / Bounds",
                "Physics / Collision",
                "Logic / Events",
                "Presentation",
                "Misc",
            ),
            "Summarizes part-prefab metadata and readable model/prefab/resource links. The rows are relationship evidence only; linked model files still hold geometry.",
        )
    if normalized_extension == ".pamhc":
        return (
            "Model property header inspector",
            "Model Property Metadata",
            _group_model_property_header_field_name,
            (
                "Material / Texture",
                "Model Resources",
                "Skeleton / Rig",
                "Physics / Collision",
                "Transform / Bounds",
                "Variant / Part",
                "Misc",
            ),
            "Summarizes model-property header metadata, material/resource hints, and same-stem companions. It is read-only relationship evidence, not an editable material sidecar.",
        )
    if normalized_extension in {".paschedule", ".paschedulepath", ".paseq", ".pastage"}:
        return (
            "Animation schedule inspector",
            "Animation / Schedule Metadata",
            _group_animation_field_name,
            ("Skeleton", "Animation Files", "Motion Space", "Parameters", "Delaunay Data", "Scene / Stage", "Misc"),
            "Summarizes schedule/sequence metadata and readable animation references. Playback and editing are not implemented.",
        )
    if normalized_extension == ".seqmt":
        return (
            "SEQMT sequence texture inspector",
            "Sequence Texture Metadata",
            _group_seqmt_field_name,
            ("Material / Texture", "Sequence / Timeline", "Resources", "Effect / Presentation", "Transform / Bounds", "Misc"),
            "Summarizes DDS! sequence texture atlas metadata, frame records, readable resource links, and same-stem companions. It is read-only relationship evidence.",
        )
    if normalized_extension in {".levelinfo", ".palevel"}:
        return (
            "Level inspector",
            "Level Metadata",
            _group_world_field_name,
            ("World / Region", "Scene Objects", "Terrain", "Road / Path", "Navigation", "Bounds / Transform", "Misc"),
            "Summarizes world/region metadata and resolved object or region references. It does not render the level.",
        )
    if normalized_extension in {".roadsector", ".road", ".nav"}:
        return (
            "World navigation inspector",
            "World / Navigation",
            _group_world_field_name,
            ("Road / Path", "Navigation", "World / Region", "Scene Objects", "Terrain", "Bounds / Transform", "Misc"),
            "Summarizes road, path, navigation, region, and scene-object markers when readable.",
        )
    if normalized_extension in {".pabc", ".pabv", ".pabgb", ".pabgh"}:
        return (
            "Rig variant inspector",
            "Rig / Gameplay Variant",
            _group_rig_variant_field_name,
            ("Skeleton / Rig", "Physics", "Animation", "Variant / Body", "Gameplay", "Misc"),
            "Summarizes skeleton, physics, body-variant, and gameplay markers. Replacement remains manual because incompatible rigs can break assets.",
        )
    return (
        f"{normalized_extension.lstrip('.').upper()} structured inspector",
        "Structured Binary",
        _group_prefab_field_name,
        ("Resources", "Scene / Object", "Transform / Bounds", "Physics / Collision", "Logic / Events", "Misc"),
        "Summarizes readable identifiers and resolved references from the binary preview sample.",
    )


def _iteminfo_internal_name_candidates(strings: Sequence[str], *, max_names: int = 48) -> List[str]:
    candidates: List[str] = []
    seen: set[str] = set()
    for raw_text in strings:
        text = str(raw_text or "").strip()
        if len(text) < 3 or len(text) > 96:
            continue
        if text in seen or text.isdigit():
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", text):
            continue
        if text.lower() in {"animationmetadata", "sceneobject", "reflectobject", "staticstringa"}:
            continue
        seen.add(text)
        candidates.append(text)
        if len(candidates) >= max_names:
            break
    return candidates


def _prefab_capability_lines(
    declaration_rows: Sequence[Mapping[str, object]],
    asset_references: Sequence[str],
) -> List[str]:
    lines = [
        f"- {row['label']}: {row['detail']}"
        for row in _prefab_evidence_rows(declaration_rows, asset_references)
    ]
    override_rows = _prefab_material_override_evidence_rows(declaration_rows, asset_references)
    if override_rows:
        routed = sum(1 for row in override_rows if row.get("role") == "resolved_material_sidecar_reference")
        lines.append(
            "- Material override routing: "
            f"{len(override_rows):,} read-only candidate row(s)"
            + (f", {routed:,} resolved material sidecar reference(s)" if routed else "")
        )
    return lines


def _prefab_evidence_rows(
    declaration_rows: Sequence[Mapping[str, object]],
    asset_references: Sequence[str],
) -> List[Dict[str, str]]:
    names = {
        str(row.get("name") or "").strip().lstrip("_").lower()
        for row in declaration_rows
        if isinstance(row, Mapping)
    }
    declared_types = {
        str(row.get("declared_type") or "").strip().lower()
        for row in declaration_rows
        if isinstance(row, Mapping)
    }
    reference_exts = {
        PurePosixPath(str(reference or "").replace("\\", "/")).suffix.lower()
        for reference in asset_references
        if str(reference or "").strip()
    }
    rows: List[Dict[str, str]] = []

    def add(label: str, detail: str, confidence: str = "declared_member_evidence") -> None:
        rows.append({"label": label, "detail": detail, "confidence": confidence})

    if any(value in names for value in ("sceneobjectuid", "sceneobjectuuid", "tag", "isenable", "generateuuid")):
        add("Scene object identity", "declares enable, tag, uid, or uuid fields that help identify the placed object instance.")
    if "components" in names or any("component" in value for value in declared_types):
        add("Scene hierarchy", "declares component and/or child-object containers.")
    if (
        "meshcomponent" in declared_types
        or "resourcereferencepath_staticmesh" in declared_types
        or any(value in names for value in ("objectfilename", "staticmeshinstancefilename", "path"))
        or ".pac" in reference_exts
        or ".pam" in reference_exts
    ):
        add("Static mesh/resource component", "can point at renderable .pac/.pam resources, but this prefab is still the metadata wrapper.")
    if (
        "skinnedmeshcomponent" in declared_types
        or "resourcereferencepath_skinnedmesh" in declared_types
        or "resourcereferencepath_characterskeleton" in declared_types
        or any(value in names for value in ("skinnedmeshfile", "skinnedmeshfilename", "skeletonfilename", "masterposeskinnedmeshcomponent"))
    ):
        add("Skinned mesh component", "declares skinned mesh, skeleton, socket, and model-property style fields.")
    if any(token in value for value in names | declared_types for token in ("cloth", "pbd", "shrink", "dynamicmotion", "sdf", "anchormeshnode")):
        add("Cloth/PBD hooks", "declares cloth, PBD, anchor, shrink-mask, or dynamic-motion fields; these are currently browse-only evidence.")
    if any("socket" in value for value in names | declared_types) or any(reference.endswith(".sockets.xml") for reference in asset_references):
        add("Socket attachments", "contains socket names or socket descriptor references useful for attaching held/body objects.")
    if any(token in value for value in names | declared_types for token in ("collision", "physics", "pbd", "shape")):
        add("Physics/collision hooks", "declares physics or collision-related component fields; editing remains read-only.")
    if any(token in value for value in names for token in ("render", "opacity", "priority")):
        add("Render/presentation overrides", "contains opacity or custom render-pass fields.")
    if (
        any(
            token in value
            for value in names | declared_types
            for token in (
                "materialinstance",
                "prefabmaterialreference",
                "prefabmaterialreferences",
                "materialparameter",
                "resourcereferencepath_material",
            )
        )
        or any(extension in reference_exts for extension in (".material", ".technique", ".pami", ".pac_xml", ".pam_xml", ".pamlod_xml"))
    ):
        add(
            "Material override hooks",
            (
                "declares material instance/reference fields or material sidecar references. These are useful for preview "
                "routing evidence, but binary override values remain read-only until the value layout is proven."
            ),
        )
    if ".xml" in reference_exts or ".prefabdata_xml" in reference_exts:
        add("Descriptor references", "points at XML descriptor data such as sockets or prefab metadata.")
    if not rows:
        add("Readable metadata", "no specific component family was proven, but identifiers and references are still shown below.")
    return rows


_PREFAB_MATERIAL_FIELD_TOKENS = (
    "material",
    "modelproperty",
    "materialproperty",
    "prefabmaterial",
    "override",
    "overrided",
    "pbdmaterial",
    "resource",
    "texture",
    "shader",
    "technique",
    "dye",
    "tint",
    "color",
    "roughness",
    "specular",
    "metal",
    "grime",
    "detail",
)


def _prefab_material_reference_role(reference: str) -> str:
    suffix = PurePosixPath(str(reference or "").replace("\\", "/")).suffix.lower()
    normalized = str(reference or "").replace("\\", "/").lower()
    if suffix in {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"} or "modelproperty/" in normalized:
        return "resolved_material_sidecar_reference"
    if suffix in {".material", ".technique"}:
        return "resolved_shader_material_reference"
    if suffix == ".dds":
        return "resolved_texture_reference"
    if suffix in {".prefabdata_xml", ".prefabdata"}:
        return "resolved_prefab_metadata_reference"
    return "asset_reference"


def _normalize_prefab_material_token_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _prefab_material_override_evidence_rows(
    declaration_rows: Sequence[Mapping[str, object]],
    asset_references: Sequence[str],
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen: set[Tuple[str, str, str]] = set()

    def add(
        *,
        field_name: str,
        declared_type: str,
        role: str,
        confidence: str,
        offset: object = "",
        descriptor_hex: object = "",
        edit_status: str = "read_only_layout_unproven",
    ) -> None:
        key = (str(field_name), str(declared_type), str(role))
        if key in seen:
            return
        seen.add(key)
        row: Dict[str, str] = {
            "field_name": str(field_name or ""),
            "declared_type": str(declared_type or ""),
            "role": str(role or ""),
            "confidence": str(confidence or ""),
            "edit_status": str(edit_status or ""),
        }
        if offset not in ("", None):
            row["offset"] = str(offset)
        if descriptor_hex not in ("", None):
            row["descriptor_hex"] = str(descriptor_hex)
        rows.append(row)

    for row in declaration_rows:
        if not isinstance(row, Mapping):
            continue
        field_name = str(row.get("name") or "").strip()
        declared_type = str(row.get("declared_type") or "").strip()
        normalized = _normalize_prefab_material_token_text(f"{field_name} {declared_type}")
        if not normalized:
            continue
        if not any(token in normalized for token in _PREFAB_MATERIAL_FIELD_TOKENS):
            continue
        role = "material_override_field"
        if "texture" in normalized:
            role = "texture_override_field"
        if "technique" in normalized or "shader" in normalized:
            role = "shader_override_field"
        if "override" in normalized or "overrided" in normalized or "prefabmaterial" in normalized:
            role = "material_instance_override_field"
        add(
            field_name=field_name,
            declared_type=declared_type,
            role=role,
            confidence="declared_member_name",
            offset=row.get("offset", ""),
            descriptor_hex=row.get("descriptor_hex", ""),
        )

    for reference in asset_references:
        reference_text = str(reference or "").strip()
        if not reference_text:
            continue
        role = _prefab_material_reference_role(reference_text)
        if role == "asset_reference":
            continue
        add(
            field_name=reference_text,
            declared_type="asset_reference",
            role=role,
            confidence="readable_asset_reference",
            edit_status="read_only_reference_routing",
        )

    return rows[:64]


def _seqmt_preview_lines(seqmt_metadata: Mapping[str, object], *, max_rows: int = 24) -> List[str]:
    if not bool(seqmt_metadata.get("recognized")):
        reason = str(seqmt_metadata.get("reason") or "unrecognized")
        return [
            "",
            "SEQMT atlas/frame table:",
            f"  - Not recognized as DDS! sequence texture metadata ({reason}).",
        ]

    columns = int(seqmt_metadata.get("columns") or 0)
    rows = int(seqmt_metadata.get("rows") or 0)
    frame_count = int(seqmt_metadata.get("frame_count") or 0)
    capacity = int(seqmt_metadata.get("grid_capacity") or 0)
    flags_or_packing = int(seqmt_metadata.get("flags_or_packing_byte") or 0)
    payload_complete = bool(seqmt_metadata.get("payload_complete"))
    trailing_payload_bytes = int(seqmt_metadata.get("trailing_payload_bytes") or 0)
    filename_hint = seqmt_metadata.get("filename_grid_hint", {})
    lines = [
        "",
        "SEQMT atlas/frame table:",
        "  - Format: DDS! sequence texture metadata",
        f"  - Atlas grid: {columns} x {rows} ({capacity:,} slot(s))",
        f"  - Frame count: {frame_count:,}",
        f"  - Flag/packing byte: 0x{flags_or_packing:02X}",
        (
            "  - Payload: "
            f"{int(seqmt_metadata.get('decoded_frame_count') or 0):,} frame record(s), "
            f"{int(seqmt_metadata.get('frame_record_size') or 0)} byte(s) each, "
            f"{'complete' if payload_complete else 'truncated'}"
        ),
    ]
    if trailing_payload_bytes > 0:
        lines.append(f"  - Extra trailing payload: {trailing_payload_bytes:,} byte(s), preserved as raw metadata")
    if isinstance(filename_hint, Mapping) and filename_hint:
        match_label = "matches header" if bool(filename_hint.get("matches_header")) else "does not match header"
        lines.append(
            "  - Filename grid hint: "
            f"{int(filename_hint.get('columns') or 0)} x {int(filename_hint.get('rows') or 0)} ({match_label})"
        )
    if frame_count != capacity:
        lines.append("  - Grid note: frame count does not equal atlas slot count; treat unused/extra slots as read-only evidence.")
    lines.append("  - Editing: disabled until the four-byte frame record meaning and rebuild rules are proven.")

    frame_records = [
        row
        for row in seqmt_metadata.get("frame_records_preview", [])
        if isinstance(row, Mapping)
    ]
    if frame_records:
        lines.extend(["", f"Frame records (first {min(len(frame_records), max_rows):,}; channel meaning unproven):"])
        for row in frame_records[:max_rows]:
            rgba = row.get("bytes_rgba") or []
            signed_values = row.get("bytes_signed") or []
            rgba_text = ",".join(str(int(value)) for value in rgba) if isinstance(rgba, Sequence) else ""
            signed_text = ",".join(str(int(value)) for value in signed_values) if isinstance(signed_values, Sequence) else ""
            lines.append(
                "  - "
                f"frame {int(row.get('index') or 0):>3} "
                f"(x={int(row.get('grid_x') or 0)}, y={int(row.get('grid_y') or 0)}) "
                f"@0x{int(row.get('offset') or 0):04X}: "
                f"raw={row.get('hex') or ''} bytes={rgba_text} signed={signed_text}"
            )
        if bool(seqmt_metadata.get("frame_records_preview_truncated")) or len(frame_records) > max_rows:
            remaining = max(0, int(seqmt_metadata.get("decoded_frame_count") or 0) - max_rows)
            lines.append(f"  ... {remaining:,} more frame record(s)")
    return lines


def build_structured_asset_preview(
    data: bytes,
    virtual_path: str,
    *,
    extension: str,
    source_entry: Optional[ArchiveEntry] = None,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    stop_event: Optional[threading.Event] = None,
) -> _StructuredBinaryPreviewBundle:
    raise_if_cancelled(stop_event)
    strings = extract_binary_strings(data, sample_limit=262_144, max_strings=256)
    raise_if_cancelled(stop_event)
    field_names = sorted({text for text in strings if _looks_like_structured_field_name(text)}, key=str.casefold)
    asset_references = _extract_binary_asset_references(data, sample_limit=262_144, max_references=96)
    raise_if_cancelled(stop_event)
    strings_preview = build_binary_strings_preview(data, sample_limit=65_536, max_strings=32)
    header_preview = format_binary_header_preview(data)
    title, metadata_label, group_func, section_order, inspector_note = _structured_asset_profile(extension)
    normalized_extension = str(extension or "").strip().lower()
    normalized_basename = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name.lower()
    iteminfo_name_candidates: List[str] = []
    if normalized_extension in {".pabgb", ".pabgh"} and normalized_basename.startswith("iteminfo."):
        if normalized_extension == ".pabgb":
            title = "Item info table inspector"
            metadata_label = "Item Database"
            inspector_note = (
                "Summarizes recovered item identifiers from iteminfo.pabgb. The app uses this table with localization, "
                "icons, and model hashes for Item Finder names and archive relationships."
            )
            iteminfo_name_candidates = _iteminfo_internal_name_candidates(strings)
        else:
            title = "Item info hash table inspector"
            metadata_label = "Item Database Index"
            inspector_note = (
                "Summarizes the companion iteminfo.pabgh index/hash table. It is useful as relationship evidence, "
                "but not directly editable or human-readable by itself."
            )
    schema_declarations = _binary_sidecar_schema_declarations(data, normalized_extension)
    seqmt_metadata = (
        _seqmt_analysis_document(data, virtual_path)
        if normalized_extension == ".seqmt"
        else {}
    )
    declared_rows = (
        list(schema_declarations.get("declared_member_rows") or [])
        if isinstance(schema_declarations, Mapping)
        else []
    )
    type_candidates = (
        list(schema_declarations.get("root_or_class_candidates") or [])
        if isinstance(schema_declarations, Mapping)
        else []
    )
    companion_entries = (
        _find_archive_model_related_entries(source_entry, archive_entries_by_basename)
        if source_entry is not None and archive_entries_by_basename is not None
        else ()
    )
    raise_if_cancelled(stop_event)
    related_references = (
        build_archive_related_file_references(
            source_entry,
            explicit_reference_names=asset_references,
            companion_entries=companion_entries,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            archive_entries_by_basename=archive_entries_by_basename,
        )
        if source_entry is not None
        else ()
    )
    graph_references = (
        build_archive_relationship_references(
            source_entry,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            archive_entries_by_basename=archive_entries_by_basename,
        )
        if source_entry is not None
        else ()
    )
    related_references = merge_archive_reference_rows(related_references, graph_references)
    if len(related_references) > 240:
        related_references = tuple(related_references[:240])
    raise_if_cancelled(stop_event)

    extension_counts: Counter[str] = Counter()
    for reference in asset_references:
        suffix = PurePosixPath(reference.replace("\\", "/")).suffix.lower()
        if suffix:
            extension_counts[suffix] += 1

    lines = [f"{title} for {virtual_path}", "", "Summary:"]
    lines.append(f"- Field-like entries: {len(field_names):,}")
    lines.append(f"- Readable strings: {len(strings):,}")
    lines.append(f"- Related asset hints: {len(asset_references):,}")
    lines.append(f"- Declared member rows: {len(declared_rows):,}")
    if iteminfo_name_candidates:
        lines.append(f"- Item identifier candidates: {len(iteminfo_name_candidates):,}")
    if isinstance(schema_declarations, Mapping) and schema_declarations.get("layout_signature"):
        lines.append(f"- Declaration layout signature: {schema_declarations.get('layout_signature')}")
    if related_references:
        resolved_count = sum(1 for reference in related_references if reference.resolved_entry is not None)
        lines.append(f"- Resolved referenced files: {resolved_count:,} / {len(related_references):,}")
    if extension_counts:
        top_types = ", ".join(f"{suffix}: {count:,}" for suffix, count in extension_counts.most_common(8))
        lines.append(f"- Reference types: {top_types}")
    if companion_entries:
        lines.append(f"- Same-stem companion files: {len(companion_entries):,}")
    if isinstance(seqmt_metadata, Mapping) and seqmt_metadata.get("recognized"):
        lines.append(
            "- SEQMT atlas: "
            f"{int(seqmt_metadata.get('columns') or 0)} x {int(seqmt_metadata.get('rows') or 0)}, "
            f"{int(seqmt_metadata.get('frame_count') or 0):,} frame record(s)"
        )
    if type_candidates:
        type_names = [
            str(candidate.get("name") or "").strip()
            for candidate in type_candidates
            if isinstance(candidate, Mapping) and str(candidate.get("name") or "").strip()
        ]
        if type_names and not iteminfo_name_candidates:
            lines.append(f"- Type/class candidates: {', '.join(type_names[:12])}" + (" ..." if len(type_names) > 12 else ""))
    lines.append(f"- Inspector note: {inspector_note}")

    if normalized_extension == ".prefab":
        lines.extend(["", "Prefab evidence:"])
        lines.extend(_prefab_capability_lines(declared_rows, asset_references))
    if normalized_extension == ".seqmt":
        lines.extend(_seqmt_preview_lines(seqmt_metadata if isinstance(seqmt_metadata, Mapping) else {}))

    if iteminfo_name_candidates:
        lines.extend(["", "Recovered item identifiers:"])
        for name in iteminfo_name_candidates[:32]:
            lines.append(f"  - {name}")
        if len(iteminfo_name_candidates) > 32:
            lines.append(f"  ... {len(iteminfo_name_candidates) - 32} more")

    if declared_rows:
        lines.extend(
            _build_grouped_schema_declaration_lines(
                [row for row in declared_rows if isinstance(row, Mapping)],
                section_order=section_order,
                per_section_limit=18,
            )
        )

    if not iteminfo_name_candidates:
        lines.extend(
            _build_grouped_structured_section_lines(
                field_names,
                group_func=group_func,
                section_order=section_order,
            )
        )
    if asset_references:
        lines.extend(["", "Detected asset references:"])
        lines.extend(f"  - {reference}" for reference in asset_references[:32])
        if len(asset_references) > 32:
            lines.append(f"  ... {len(asset_references) - 32} more")
    if strings_preview:
        lines.extend(["", strings_preview])
    else:
        lines.extend(["", "Readable strings:", "  None detected in the preview sample."])
    lines.extend(["", "Binary header preview:", header_preview])

    detail_lines = [
        inspector_note,
        f"Detected {len(field_names):,} field-like identifier(s) and {len(asset_references):,} asset reference hint(s).",
    ]
    if declared_rows:
        detail_lines.append(
            f"Recovered {len(declared_rows):,} length-prefixed member declaration(s); these identify fields and types but not safe edit offsets."
        )
    if related_references:
        detail_lines.append("Resolved related archive files are listed below.")
    if normalized_extension == ".prefab":
        detail_lines.append(
            "Prefab preview uses direct readable references, same-stem companions, and bounded binary prefab relationship evidence; it remains read-only."
        )
    if normalized_extension == ".seqmt":
        if isinstance(seqmt_metadata, Mapping) and seqmt_metadata.get("recognized"):
            detail_lines.append(
                "SEQMT preview decodes the observed DDS! atlas grid and four-byte frame table. Frame record channel meaning is still read-only evidence."
            )
        else:
            detail_lines.append(
                "SEQMT preview falls back to readable identifiers, asset references, and same-stem companions. Editing remains disabled."
            )
    if iteminfo_name_candidates:
        detail_lines.append(
            "Item info preview exposes internal item identifiers as relationship/name evidence. Display names still come from localization tables when available."
        )
    if not field_names and not asset_references and not strings:
        detail_lines.append("No readable strings or structured markers were detected, so the preview falls back to raw header bytes.")

    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(lines),
        detail_lines=tuple(detail_lines),
        related_references=related_references,
        metadata_label=metadata_label,
    )


_SIMPLIFIED_XML_ATTR_NAMES: frozenset[str] = frozenset(
    {
        "name",
        "_name",
        "type",
        "_type",
        "path",
        "_path",
        "_value",
        "value",
        "_materialname",
        "_submeshname",
        "_prefabname",
        "_meshparamfile",
        "_nudename",
        "_skeletonfile",
        "_animationfile",
        "_normaltexture",
        "_heighttexture",
        "_overlaycolortexture",
        "_colorblendingmasktexture",
        "_detailmasktexture",
    }
)


def _parse_xmlish_preview_root(text: str) -> Optional[ET.Element]:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    candidates = (stripped, f"<ArchivePreviewRoot>{stripped}</ArchivePreviewRoot>")
    for candidate in candidates:
        try:
            return ET.fromstring(candidate)
        except ET.ParseError:
            continue
    return None


def _humanize_xml_field_name(name: str) -> str:
    raw = str(name or "").strip().lstrip("_")
    if not raw:
        return "Value"
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw)
    raw = raw.replace("_", " ").replace("-", " ")
    return " ".join(raw.split()).title() or name


def _xml_field_value_hint(name: str, value: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    normalized_value = str(value or "").strip().lower()
    if "damping" in normalized:
        return "physics damping value"
    if "inertia" in normalized or "mass" in normalized:
        return "physics mass/inertia value"
    if "friction" in normalized:
        return "physics friction value"
    if "angularlimit" in normalized or "twist" in normalized or "plane" in normalized or "coneangle" in normalized:
        return "physics angular limit"
    if "socket" in normalized:
        return "skeleton/socket binding"
    if "bodyname" in normalized:
        return "physics body name"
    if normalized in {"path", "value"} or normalized.endswith("path") or "/" in normalized_value or "\\" in normalized_value:
        return "asset/reference path"
    if "material" in normalized:
        return "material/shader binding"
    if "submesh" in normalized or "mesh" in normalized:
        return "mesh/submesh binding"
    if "texture" in normalized:
        return "texture slot"
    if "color" in normalized or normalized_value.startswith("#"):
        return "color/tint value"
    if "scale" in normalized or "size" in normalized or "radius" in normalized:
        return "size/scale value"
    if "flag" in normalized or normalized.startswith(("is", "use", "enable", "disable")):
        return "flag/toggle"
    if "category" in normalized or "type" in normalized:
        return "type/category"
    return _structured_field_type_hint(name)


def _summarize_physics_attachment_xml(root: ET.Element, *, max_rows: int = 12) -> List[str]:
    elements = list(root.iter())
    if not any(str(element.tag or "").startswith("SkinnedMeshPhysicsAttachment") for element in elements):
        return []
    instance_count = sum(1 for element in elements if str(element.tag or "") == "SkinnedMeshPhysicsAttachmentInstanceDesc")
    body_elements = [
        element
        for element in elements
        if str(element.tag or "") == "SkinnedMeshPhysicsAttachmentBodyCreationDesc"
    ]
    constraint_elements = [
        element
        for element in elements
        if str(element.tag or "").startswith("SkinnedMeshPhysicsAttachment")
        and "ConstraintDesc" in str(element.tag or "")
    ]
    shape_counts: Counter[str] = Counter(
        str(element.tag or "")
        for element in elements
        if str(element.tag or "").startswith("SkinnedMeshPhysicsAttachment")
        and "ShapeDesc" in str(element.tag or "")
    )
    lines = [
        "- Physics attachment descriptor: controls extra socket-bound physics bodies, usually accessories or body-attached props.",
        f"- Physics attachment instances: {instance_count:,}; bodies: {len(body_elements):,}; constraints: {len(constraint_elements):,}",
    ]
    if shape_counts:
        lines.append("- Attachment collision shapes: " + ", ".join(f"{name}: {count:,}" for name, count in shape_counts.most_common(6)))

    socket_names = sorted(
        {
            str(element.attrib.get("_socketName") or "").strip()
            for element in body_elements
            if str(element.attrib.get("_socketName") or "").strip()
        },
        key=str.casefold,
    )
    body_names = sorted(
        {
            str(element.attrib.get("_bodyName") or "").strip()
            for element in body_elements
            if str(element.attrib.get("_bodyName") or "").strip()
        },
        key=str.casefold,
    )
    if socket_names:
        lines.append("- Socket bindings: " + ", ".join(socket_names[:10]) + (f" (+{len(socket_names) - 10} more)" if len(socket_names) > 10 else ""))
    if body_names:
        lines.append("- Physics bodies: " + ", ".join(body_names[:10]) + (f" (+{len(body_names) - 10} more)" if len(body_names) > 10 else ""))

    tunables: List[str] = []
    for element in elements:
        tag = str(element.tag or "")
        for key, value in sorted(element.attrib.items(), key=lambda item: item[0].casefold()):
            normalized = str(key or "").strip().lstrip("_").lower()
            if normalized not in {
                "angulardamping",
                "lineardamping",
                "inertiafactor",
                "maxfrictiontorque",
                "angularlimitmin",
                "angularlimitmax",
                "coneangle",
                "twistmin",
                "twistmax",
                "planemin",
                "planemax",
                "sphereradius",
                "cylinderheight",
                "radius",
            }:
                continue
            label = _humanize_xml_field_name(key)
            tunables.append(f"  - {tag}.{label}: {value} ({_xml_field_value_hint(key, value)})")
            if len(tunables) >= max_rows:
                break
        if len(tunables) >= max_rows:
            break
    if tunables:
        lines.extend(["", "Physics attachment tunables:"])
        lines.extend(tunables)
    lines.append(
        "Editing note: these XML values are much more explicitly named than HKX fields; damping, inertia, limits, shape size, and friction are reasonable modding targets when this descriptor is selected."
    )
    return lines


def build_simplified_text_asset_summary(
    text: str,
    *,
    extension: str,
    virtual_path: str,
    max_rows: int = 40,
) -> str:
    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension not in _ARCHIVE_XML_LIKE_EXTENSIONS and normalized_extension not in {".material", ".xml"}:
        return ""
    root = _parse_xmlish_preview_root(text)
    asset_references = _extract_text_asset_references(text, sidecar_path=virtual_path, max_references=48)
    lines = [f"Simplified values for {virtual_path}", ""]
    if root is None:
        if not asset_references:
            return ""
        lines.extend(["Resolved-looking asset references:"])
        lines.extend(f"  - {reference}" for reference in asset_references[:24])
        if len(asset_references) > 24:
            lines.append(f"  ... {len(asset_references) - 24} more")
        return "\n".join(lines)

    elements = list(root.iter())
    tag_counts: Counter[str] = Counter(str(element.tag or "").strip() for element in elements if str(element.tag or "").strip())
    material_bindings = tuple(parse_texture_sidecar_bindings(text, sidecar_path=virtual_path))
    lines.append("What this appears to contain:")
    if tag_counts:
        top_tags = ", ".join(f"{tag}: {count:,}" for tag, count in tag_counts.most_common(8))
        lines.append(f"- XML/object types: {top_tags}")
    if material_bindings:
        submesh_names = sorted({binding.submesh_name for binding in material_bindings if binding.submesh_name}, key=str.casefold)
        parameter_names = sorted({binding.parameter_name for binding in material_bindings if binding.parameter_name}, key=str.casefold)
        lines.append(f"- Material texture bindings: {len(material_bindings):,}")
        if submesh_names:
            lines.append(f"- Submesh/material slots: {', '.join(submesh_names[:8])}" + (f" (+{len(submesh_names) - 8} more)" if len(submesh_names) > 8 else ""))
        if parameter_names:
            lines.append(f"- Texture parameter kinds: {', '.join(parameter_names[:10])}" + (f" (+{len(parameter_names) - 10} more)" if len(parameter_names) > 10 else ""))
    if asset_references:
        lines.append(f"- Asset/reference paths: {len(asset_references):,}")
    physics_attachment_lines = _summarize_physics_attachment_xml(root)
    if physics_attachment_lines:
        lines.extend(["", "Physics attachment summary:"])
        lines.extend(physics_attachment_lines)

    rows: List[Tuple[str, str, str]] = []
    seen_rows: set[Tuple[str, str]] = set()
    for element in elements:
        for key, value in sorted(element.attrib.items(), key=lambda item: item[0].casefold()):
            clean_key = str(key or "").strip()
            clean_value = str(value or "").strip()
            if not clean_key or not clean_value:
                continue
            normalized_key = clean_key.strip().lower()
            keep = (
                normalized_key in _SIMPLIFIED_XML_ATTR_NAMES
                or normalized_key.endswith(("path", "name", "type", "flag", "scale", "radius", "size", "color", "category"))
                or "/" in clean_value
                or "\\" in clean_value
                or clean_value.startswith("#")
            )
            if not keep:
                continue
            row_key = (normalized_key, clean_value)
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            rows.append((_humanize_xml_field_name(clean_key), clean_value, _xml_field_value_hint(clean_key, clean_value)))
            if len(rows) >= max_rows:
                break
        if len(rows) >= max_rows:
            break

    if rows:
        lines.extend(["", "Recognized fields:"])
        for label, value, hint in rows:
            compact_value = value if len(value) <= 160 else value[:157] + "..."
            lines.append(f"  - {label}: {compact_value} ({hint})")
    if asset_references:
        lines.extend(["", "Detected asset references:"])
        lines.extend(f"  - {reference}" for reference in asset_references[:24])
        if len(asset_references) > 24:
            lines.append(f"  ... {len(asset_references) - 24} more")
    lines.extend(
        [
            "",
            "Editing note: text/XML-like entries can be extracted or included in mod-ready loose folders, but only recognized material sidecars currently have a guided value editor.",
        ]
    )
    return "\n".join(lines)


def describe_archive_binary_content(extension: str, data: bytes) -> str:
    head4 = data[:4]
    if head4 == b"BKHD":
        return "Detected Wwise soundbank data."
    if extension == ".seqmt" and head4 == b"DDS!":
        if len(data) >= 12:
            columns = int(struct.unpack_from("<H", data, 5)[0])
            rows = int(struct.unpack_from("<H", data, 7)[0])
            frame_count = int(struct.unpack_from("<H", data, 10)[0])
            return f"Detected SEQMT DDS! sequence texture metadata ({columns} x {rows}, {frame_count} frame records)."
        return "Detected SEQMT DDS! sequence texture metadata."
    if head4 == b"PAR ":
        if extension == ".pac":
            return "Detected PAR skinned mesh data."
        if extension == ".pab":
            return "Detected PAR skeleton data."
        if extension == ".pat":
            return "Detected PAR model data. Visual model preview is not available yet."
        if extension == ".pam":
            return "Detected PAR mesh data."
        if extension == ".pamlod":
            return "Detected PAR mesh LOD data."
        if extension == ".paa":
            return "Detected PAR animation data. Visual animation preview is not available yet."
        if extension in {".pae", ".paem"}:
            return "Detected PAR effect or emitter data. Real effect playback is not available yet."
        return "Detected PAR-family binary data."
    if head4 == b"PARC":
        return "Detected PARC structured container data."
    if len(data) >= 16 and data[4:8] == b"TAG0" and data[12:16] == b"SDKV":
        return "Detected Havok tagfile data. Visual animation or skeleton preview is not available yet."
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "Detected RIFF/WAVE audio data, likely Wwise `.wem`."
    if b"EmitterData" in data[:4096]:
        return "Structured emitter or effect data detected."
    if b"SceneObject" in data[:4096]:
        return "Structured scene or prefab metadata detected."
    if b"AnimationMetaData" in data[:4096]:
        return "Animation metadata detected."
    if b"ParameterizedMotionSpace" in data[:4096]:
        return "Animation motion-blending metadata detected."
    if b"Sequencer" in data[:4096]:
        return "Structured sequencer data detected."
    if extension == ".seqmt":
        return "Structured SEQMT sequence texture metadata detected."
    if extension == ".pabgb":
        return "Structured gameplay or table-like binary data detected."
    if extension == ".meshinfo":
        return "Structured mesh metadata detected."
    if extension in {".pae", ".paem"}:
        return "Structured emitter or effect data detected."
    if extension == ".levelinfo":
        return "Structured level metadata detected."
    if extension == ".prefab":
        return "Structured prefab metadata detected."
    return ""


def build_archive_binary_preview_payload(
    entry: ArchiveEntry,
    data: bytes,
    *,
    info_extra: str = "",
) -> Tuple[str, str, str]:
    text_preview = try_decode_text_like_archive_data(data)
    if text_preview:
        extra_parts = [part for part in [info_extra, "Binary content was sniffed as plain text."] if part]
        if len(data) > ARCHIVE_TEXT_PREVIEW_LIMIT:
            extra_parts.append(f"Preview truncated to {format_byte_size(ARCHIVE_TEXT_PREVIEW_LIMIT)}.")
        return "text", text_preview, "\n\n".join(extra_parts)

    strings_preview = build_binary_strings_preview(data)
    hint_text = describe_archive_binary_content(entry.extension, data)
    extra_parts = [part for part in [info_extra, hint_text] if part]
    if strings_preview:
        extra_parts.append(strings_preview)
        return "text", strings_preview, "\n\n".join(extra_parts)
    return "info", "", "\n\n".join(extra_parts)


def parse_archive_note_flags(note: str) -> set[str]:
    return {part.strip() for part in note.split(",") if part.strip()}


def summarize_obj_text(content: str) -> str:
    vertices = 0
    texcoords = 0
    normals = 0
    faces = 0
    for raw_line in content.splitlines():
        line = raw_line.lstrip()
        if line.startswith("v "):
            vertices += 1
        elif line.startswith("vt "):
            texcoords += 1
        elif line.startswith("vn "):
            normals += 1
        elif line.startswith("f "):
            faces += 1
    return f"OBJ summary: {vertices:,} vertices, {texcoords:,} UVs, {normals:,} normals, {faces:,} faces."


def _build_model_preview_summary_text(path: str, model_preview: ModelPreviewData) -> str:
    if getattr(model_preview, "format", "").lower() == "pamlod":
        lod_index = getattr(model_preview, "lod_index", -1)
        lod_count = getattr(model_preview, "lod_count", 0)
        lod_label = f"LOD {lod_index + 1}" if lod_index >= 0 else "LOD"
        if lod_count > 0 and lod_index >= 0:
            lod_label = f"{lod_label} of {lod_count}"
        return (
            f"{path}\n"
            f"{lod_label}\n"
            f"{model_preview.vertex_count:,} vertices\n"
            f"{model_preview.face_count:,} faces"
        )
    return (
        f"{path}\n"
        f"{model_preview.mesh_count:,} submesh(es)\n"
        f"{model_preview.vertex_count:,} vertices\n"
        f"{model_preview.face_count:,} faces"
    )


def _attach_hkx_physics_overlay_to_model_preview(
    model_preview: Optional[ModelPreviewData],
    references: Sequence[ArchiveModelTextureReference],
    *,
    stop_event: Optional[threading.Event] = None,
    max_hkx_files: int = 3,
) -> List[str]:
    if model_preview is None:
        return []
    overlays: List[Optional[HkxPhysicsOverlayData]] = []
    notes: List[str] = []
    seen_paths: set[str] = set()
    descriptor_hints: List[Mapping[str, object]] = []
    seen_descriptor_paths: set[str] = set()
    skeleton_bone_positions: Dict[str, Mapping[str, object]] = {}
    seen_skeleton_paths: set[str] = set()

    def _finite_tuple3(value: object) -> Tuple[float, float, float]:
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return ()
        try:
            point = (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError, OverflowError):
            return ()
        return point if all(math.isfinite(component) for component in point) else ()

    def _bone_preview_position(bone: object) -> Tuple[Tuple[float, float, float], str]:
        matrix = tuple(getattr(bone, "bind_matrix", ()) or ())
        candidates: List[Tuple[float, Tuple[float, float, float], str]] = []
        if len(matrix) >= 16:
            for indexes, source in (((12, 13, 14), "bind_matrix_row_translation"), ((3, 7, 11), "bind_matrix_column_translation")):
                point = _finite_tuple3(tuple(matrix[index] for index in indexes))
                if point:
                    magnitude = math.sqrt((point[0] * point[0]) + (point[1] * point[1]) + (point[2] * point[2]))
                    if magnitude > 1e-6:
                        candidates.append((magnitude, point, source))
        if candidates:
            _magnitude, point, source = max(candidates, key=lambda item: item[0])
            return point, source
        point = _finite_tuple3(tuple(getattr(bone, "position", ()) or ()))
        return (point, "local_position") if point else ((), "")

    def _overlay_match_tokens(path_text: object) -> set[str]:
        normalized = str(path_text or "").replace("\\", "/").casefold()
        stop_tokens = {
            "animation",
            "archive",
            "bin",
            "character",
            "cloth",
            "havok",
            "havokphysics",
            "hkx",
            "leveldata",
            "meshphysics",
            "model",
            "object",
            "pac",
            "pam",
            "pamlod",
            "pc",
            "physics",
            "phm",
            "phw",
        }
        return {
            token
            for token in re.findall(r"[a-z0-9]+", normalized)
            if len(token) >= 2 and token not in stop_tokens and token != "cd"
        }

    def _score_overlay_hkx_reference(reference: ArchiveModelTextureReference, order: int) -> Tuple[int, int, ArchiveModelTextureReference]:
        resolved_entry = getattr(reference, "resolved_entry", None)
        candidate_path = str(getattr(resolved_entry, "path", "") or getattr(reference, "resolved_archive_path", "") or "")
        source_path = str(getattr(model_preview, "path", "") or "")
        source_path_folded = source_path.replace("\\", "/").casefold()
        candidate_path_folded = candidate_path.replace("\\", "/").casefold()
        source_stem = PurePosixPath(source_path_folded).stem
        candidate_stem = PurePosixPath(candidate_path_folded).stem
        score = 0
        if source_stem and candidate_stem and source_stem == candidate_stem:
            score += 220
        elif source_stem and source_stem in candidate_path_folded:
            score += 150
        elif candidate_stem and candidate_stem in source_path_folded:
            score += 80
        shared_tokens = _overlay_match_tokens(source_path_folded) & _overlay_match_tokens(candidate_path_folded)
        important_tokens = {
            "shield",
            "sword",
            "weapon",
            "bow",
            "dagger",
            "axe",
            "mace",
            "staff",
            "cloak",
            "cape",
            "hair",
            "helmet",
        }
        for token in shared_tokens:
            score += 70 if token in important_tokens else 22
        return score, order, reference

    for reference in references:
        resolved_entry = getattr(reference, "resolved_entry", None)
        if resolved_entry is None or str(getattr(resolved_entry, "extension", "") or "").lower() not in {".xml", ".app_xml", ".pac_xml", ".prefabdata_xml"}:
            continue
        normalized_path = str(getattr(resolved_entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path or normalized_path in seen_descriptor_paths:
            continue
        if not any(
            token in normalized_path
            for token in ("physics", "attachment", "havok", "modelproperty", "material")
        ):
            continue
        seen_descriptor_paths.add(normalized_path)
        try:
            descriptor_data, _decompressed, _note = read_archive_entry_data(resolved_entry, stop_event=stop_event)
            descriptor_text = descriptor_data.decode("utf-8", errors="ignore")
            descriptor_hint = build_hkx_descriptor_hint_from_xml_text(descriptor_text, resolved_entry.path)
            if descriptor_hint is not None:
                descriptor_hints.append(descriptor_hint)
        except RunCancelled:
            raise
        except Exception as exc:
            notes.append(f"HKX descriptor context skipped for {getattr(resolved_entry, 'path', 'unknown')}: {exc}")
    for reference in references:
        resolved_entry = getattr(reference, "resolved_entry", None)
        if resolved_entry is None or str(getattr(resolved_entry, "extension", "") or "").lower() != ".pab":
            continue
        normalized_path = str(getattr(resolved_entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path or normalized_path in seen_skeleton_paths:
            continue
        seen_skeleton_paths.add(normalized_path)
        try:
            skeleton_data, _decompressed, _note = read_archive_entry_data(resolved_entry, stop_event=stop_event)
            skeleton = parse_pab(skeleton_data, resolved_entry.path)
            bones_by_index = {
                int(getattr(bone, "index", -1)): bone
                for bone in getattr(skeleton, "bones", []) or []
                if int(getattr(bone, "index", -1)) >= 0
            }
            for bone in getattr(skeleton, "bones", []) or []:
                bone_name = str(getattr(bone, "name", "") or "").strip()
                position, position_source = _bone_preview_position(bone)
                if not bone_name or len(position) < 3:
                    continue
                parent_index = int(getattr(bone, "parent_index", -1) or -1)
                parent_bone = bones_by_index.get(parent_index)
                skeleton_bone_positions[bone_name] = {
                    "name": bone_name,
                    "index": int(getattr(bone, "index", -1) or 0),
                    "parent_index": parent_index,
                    "parent_name": str(getattr(parent_bone, "name", "") or "") if parent_bone is not None else "",
                    "position": position,
                    "position_source": position_source,
                    "source_path": resolved_entry.path,
                }
        except RunCancelled:
            raise
        except Exception as exc:
            notes.append(f"HKX skeleton context skipped for {getattr(resolved_entry, 'path', 'unknown')}: {exc}")
    hkx_candidates: List[Tuple[int, int, ArchiveModelTextureReference]] = []
    for order, reference in enumerate(references):
        if stop_event is not None and stop_event.is_set():
            raise RunCancelled("HKX physics overlay preparation cancelled.")
        resolved_entry = getattr(reference, "resolved_entry", None)
        if resolved_entry is None or str(getattr(resolved_entry, "extension", "") or "").lower() not in {".hkx", ".hkt"}:
            continue
        normalized_path = str(getattr(resolved_entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path or normalized_path in seen_paths:
            continue
        hkx_candidates.append(_score_overlay_hkx_reference(reference, order))
    hkx_candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    if hkx_candidates:
        best_score = hkx_candidates[0][0]
        if best_score >= 50:
            threshold = max(45, best_score - 45)
            skipped = [
                candidate
                for candidate in hkx_candidates
                if candidate[0] < threshold
            ]
            hkx_candidates = [
                candidate
                for candidate in hkx_candidates
                if candidate[0] >= threshold
            ]
            if skipped:
                notes.append(
                    "Skipped lower-confidence HKX overlays that looked like broader character/rig context rather than the selected model."
                )
    for _score, _order, reference in hkx_candidates:
        if stop_event is not None and stop_event.is_set():
            raise RunCancelled("HKX physics overlay preparation cancelled.")
        resolved_entry = getattr(reference, "resolved_entry", None)
        if resolved_entry is None:
            continue
        normalized_path = str(getattr(resolved_entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path or normalized_path in seen_paths:
            continue
        seen_paths.add(normalized_path)
        try:
            hkx_data, _decompressed, _note = read_archive_entry_data(resolved_entry, stop_event=stop_event)
            hkx_document = build_hkx_editable_geometry_document(hkx_data, resolved_entry.path, descriptor_hints)
            overlay = build_hkx_physics_overlay_from_document(
                hkx_document,
                source_path=resolved_entry.path,
                normalization_center=tuple(getattr(model_preview, "normalization_center", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
                normalization_scale=float(getattr(model_preview, "normalization_scale", 1.0) or 1.0),
                skeleton_bone_positions=skeleton_bone_positions,
            )
            if overlay is not None:
                overlays.append(overlay)
                notes.append(f"HKX physics overlay loaded from {resolved_entry.path}: {len(overlay.shapes):,} decoded shape(s).")
        except RunCancelled:
            raise
        except Exception as exc:
            notes.append(f"HKX physics overlay skipped for {getattr(resolved_entry, 'path', 'unknown')}: {exc}")
        if len(overlays) >= max_hkx_files:
            break
    merged = merge_hkx_physics_overlays(overlays)
    if merged is not None:
        model_preview.physics_overlay = merged
        if len(seen_paths) > len(overlays):
            notes.append("Only the first compatible HKX physics overlays are drawn to keep preview rendering responsive.")
    return notes


def _retarget_model_preview(model_preview: ModelPreviewData, path: str) -> None:
    model_preview.path = path
    model_preview.summary = _build_model_preview_summary_text(path, model_preview)


def _inspect_pam_declared_geometry(data: bytes) -> Tuple[int, int]:
    if len(data) < 64 or data[:4] != b"PAR ":
        return 0, 0
    mesh_count = struct.unpack_from("<I", data, 16)[0]
    declared_index_count = 0
    for index in range(mesh_count):
        entry_offset = 1040 + index * 536
        if entry_offset + 8 > len(data):
            break
        declared_index_count += struct.unpack_from("<I", data, entry_offset + 4)[0]
    return mesh_count, declared_index_count


def _pam_preview_looks_incomplete(data: bytes, model_preview: ModelPreviewData) -> bool:
    declared_mesh_count, declared_index_count = _inspect_pam_declared_geometry(data)
    if declared_mesh_count > 0 and model_preview.mesh_count < declared_mesh_count:
        return True
    if declared_index_count > 0 and (model_preview.face_count * 3) < int(declared_index_count * 0.85):
        return True
    return False


def _build_pam_model_preview_with_fallback(
    entry: ArchiveEntry,
    data: bytes,
    note_flags: set[str],
    *,
    companion_entry: Optional[ArchiveEntry] = None,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[ModelPreviewData, List[str]]:
    info_extra_parts: List[str] = []
    recovery_errors: List[str] = []
    raw_model_preview: Optional[ModelPreviewData] = None
    skip_padded_recovery = False

    try:
        candidate_raw_model_preview = build_pam_model_preview(entry, data, stop_event=stop_event)
        ensure_model_preview_is_reasonable(candidate_raw_model_preview, stop_event=stop_event)
        raw_model_preview = candidate_raw_model_preview
        if (
            "PartialRaw" in note_flags
            and companion_entry is not None
            and _pam_preview_looks_incomplete(data, raw_model_preview)
        ):
            info_extra_parts.append(
                "Stored PAM geometry recovery looks incomplete for this Partial entry; a companion PAMLOD preview will be preferred when available."
            )
        else:
            return raw_model_preview, info_extra_parts
    except RunCancelled:
        raise
    except Exception as exc:
        raw_error_text = str(exc)
        recovery_errors.append(f"Stored PAM geometry recovery failed: {raw_error_text}")
        if "suppressed" in raw_error_text.lower() or "scrambled" in raw_error_text.lower():
            skip_padded_recovery = True

    if companion_entry is not None:
        try:
            companion_data, _companion_decompressed, companion_note = read_archive_entry_data(
                companion_entry,
                stop_event=stop_event,
            )
            model_preview = build_pamlod_model_preview(companion_entry, companion_data, stop_event=stop_event)
            ensure_model_preview_is_reasonable(model_preview, stop_event=stop_event)
            _retarget_model_preview(model_preview, entry.path)
            info_extra_parts.append(
                f"Visual model preview uses companion {companion_entry.basename} geometry because the selected PAM payload did not yield a complete renderable mesh preview."
            )
            companion_note_flags = parse_archive_note_flags(companion_note)
            if "ChaCha20" in companion_note_flags:
                info_extra_parts.append("Companion PAMLOD geometry was decrypted via deterministic ChaCha20 filename derivation.")
            return model_preview, info_extra_parts
        except RunCancelled:
            raise
        except Exception as exc:
            recovery_errors.append(f"Companion PAMLOD recovery failed: {exc}")

    if "PartialRaw" in note_flags and len(data) < entry.orig_size and not skip_padded_recovery:
        try:
            padded_data = data + (b"\x00" * (entry.orig_size - len(data)))
            model_preview = build_pam_model_preview(entry, padded_data, stop_event=stop_event)
            ensure_model_preview_is_reasonable(model_preview, stop_event=stop_event)
            info_extra_parts.append(
                "Visual model preview uses zero-padded Partial reconstruction because the stored PAM payload is incomplete."
            )
            return model_preview, info_extra_parts
        except RunCancelled:
            raise
        except Exception as exc:
            recovery_errors.append(f"Zero-padded Partial reconstruction failed: {exc}")

    if raw_model_preview is not None:
        info_extra_parts.append(
            "Stored PAM geometry preview is being shown even though the recovered mesh set appears incomplete."
        )
        return raw_model_preview, info_extra_parts

    if "PartialRaw" in note_flags and len(data) < entry.orig_size:
        recovery_errors.append("Stored Partial payload appears truncated beyond the geometry data needed for preview.")
    raise ValueError("; ".join(recovery_errors) if recovery_errors else "PAM geometry could not be recovered.")


def _build_pamlod_model_preview_with_fallback(
    entry: ArchiveEntry,
    data: bytes,
    note_flags: set[str],
    *,
    companion_entry: Optional[ArchiveEntry] = None,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[ModelPreviewData, List[str]]:
    info_extra_parts: List[str] = []
    recovery_errors: List[str] = []

    try:
        model_preview = build_pamlod_model_preview(entry, data, stop_event=stop_event)
        ensure_model_preview_is_reasonable(model_preview, stop_event=stop_event)
        return model_preview, info_extra_parts
    except RunCancelled:
        raise
    except Exception as exc:
        recovery_errors.append(f"Stored PAMLOD geometry recovery failed: {exc}")

    if companion_entry is not None:
        try:
            companion_data, _companion_decompressed, companion_note = read_archive_entry_data(
                companion_entry,
                stop_event=stop_event,
            )
            model_preview = build_pam_model_preview(companion_entry, companion_data, stop_event=stop_event)
            ensure_model_preview_is_reasonable(model_preview, stop_event=stop_event)
            _retarget_model_preview(model_preview, entry.path)
            info_extra_parts.append(
                f"Visual model preview uses companion {companion_entry.basename} geometry because the selected PAMLOD payload did not yield a complete renderable LOD preview."
            )
            companion_note_flags = parse_archive_note_flags(companion_note)
            if "ChaCha20" in companion_note_flags:
                info_extra_parts.append("Companion PAM geometry was decrypted via deterministic ChaCha20 filename derivation.")
            return model_preview, info_extra_parts
        except RunCancelled:
            raise
        except Exception as exc:
            recovery_errors.append(f"Companion PAM recovery failed: {exc}")

    if "PartialRaw" in note_flags and len(data) < entry.orig_size:
        try:
            padded_data = data + (b"\x00" * (entry.orig_size - len(data)))
            model_preview = build_pamlod_model_preview(entry, padded_data, stop_event=stop_event)
            ensure_model_preview_is_reasonable(model_preview, stop_event=stop_event)
            info_extra_parts.append(
                "Visual model preview uses zero-padded Partial reconstruction because the stored PAMLOD payload is incomplete."
            )
            return model_preview, info_extra_parts
        except RunCancelled:
            raise
        except Exception as exc:
            recovery_errors.append(f"Zero-padded PAMLOD reconstruction failed: {exc}")
        recovery_errors.append("Stored Partial payload appears truncated beyond the geometry data needed for preview.")

    raise ValueError("; ".join(recovery_errors) if recovery_errors else "PAMLOD geometry could not be recovered.")


def _build_pac_model_preview_with_fallback(
    entry: ArchiveEntry,
    data: bytes,
    note_flags: set[str],
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[ModelPreviewData, ParsedMesh, List[str]]:
    info_extra_parts: List[str] = []
    recovery_errors: List[str] = []

    try:
        model_preview, parsed_mesh = build_mesh_preview_from_bytes(data, entry.path)
        return model_preview, parsed_mesh, info_extra_parts
    except RunCancelled:
        raise
    except Exception as exc:
        recovery_errors.append(f"Stored PAC geometry recovery failed: {exc}")

    if "PartialRaw" in note_flags and len(data) < entry.orig_size:
        try:
            padded_data = data + (b"\x00" * (entry.orig_size - len(data)))
            model_preview, parsed_mesh = build_mesh_preview_from_bytes(padded_data, entry.path)
            info_extra_parts.append(
                "Visual model preview uses zero-padded Partial reconstruction because the stored PAC payload is incomplete."
            )
            return model_preview, parsed_mesh, info_extra_parts
        except RunCancelled:
            raise
        except Exception as exc:
            recovery_errors.append(f"Zero-padded PAC reconstruction failed: {exc}")
        recovery_errors.append("Stored Partial payload appears truncated beyond the geometry data needed for preview.")

    raise ValueError("; ".join(recovery_errors) if recovery_errors else "PAC geometry could not be recovered.")


def build_archive_preview_result(
    texconv_path: Optional[Path],
    entry: Optional[ArchiveEntry],
    loose_search_roots: Optional[Sequence[Path]] = None,
    *,
    companion_entry: Optional[ArchiveEntry] = None,
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_entries_by_texture_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_entries_by_texture_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    include_loose_preview_assets: bool = True,
    semantic_sidecar_texts: Sequence[str] = (),
    visible_texture_mode: str = "mesh_base_first",
    support_texture_slots: Sequence[str] = ("normal", "material", "height"),
    stop_event: Optional[threading.Event] = None,
) -> ArchivePreviewResult:
    if entry is None:
        return ArchivePreviewResult(
            status="missing",
            title="Archive Preview",
            metadata_summary="Nothing selected.",
            detail_text="Select an archive file or folder to preview it here.",
            preferred_view="info",
        )

    metadata_summary = build_archive_entry_metadata_summary(entry)
    extension = entry.extension
    normalized_visible_texture_mode = _normalize_model_visible_texture_mode(visible_texture_mode)
    timings: Dict[str, float] = {}

    def add_timing(key: str, started_at: float) -> None:
        timings[key] = timings.get(key, 0.0) + max(0.0, float(time.perf_counter() - started_at))

    loose_file_path = ""
    loose_preview_image_path = ""
    loose_preview_media_path = ""
    loose_preview_media_kind = ""
    loose_preview_title = ""
    loose_preview_metadata_summary = ""
    loose_preview_detail_text = ""

    if loose_search_roots:
        loose_candidates = list(iter_archive_loose_file_candidates(entry, loose_search_roots))
        if loose_candidates:
            loose_candidate = loose_candidates[0]
            loose_file_path = str(loose_candidate)
            loose_preview_title = f"{entry.basename} (Loose file)"
            if include_loose_preview_assets:
                try:
                    if loose_candidate.suffix.lower() in ARCHIVE_AUDIO_EXTENSIONS.union(ARCHIVE_VIDEO_EXTENSIONS):
                        (
                            loose_preview_media_path,
                            loose_preview_media_kind,
                            loose_preview_metadata_summary,
                            loose_preview_detail_text,
                        ) = build_loose_archive_media_preview_assets(
                            loose_candidate,
                            stop_event=stop_event,
                        )
                    else:
                        (
                            loose_preview_image_path,
                            loose_preview_metadata_summary,
                            loose_preview_detail_text,
                        ) = build_loose_archive_preview_assets(
                            texconv_path,
                            loose_candidate,
                            stop_event=stop_event,
                        )
                except RunCancelled:
                    raise
                except Exception as exc:
                    loose_preview_metadata_summary = f"Loose file | {loose_candidate.name}"
                    loose_preview_detail_text = (
                        f"Loose file candidate found at {loose_candidate}, but preview failed: {exc}"
                    )
                if len(loose_candidates) > 1:
                    loose_preview_detail_text += (
                        f"\n\nAdditional loose candidates found: {len(loose_candidates) - 1}"
                    )

    try:
        if extension in ARCHIVE_VIDEO_EXTENSIONS:
            source_path, note = ensure_archive_preview_source(entry, stop_event=stop_event)
            metadata_summary, media_detail = _build_mp4_media_preview_detail_text(source_path, loose=False)
            extra_detail_parts: List[str] = []
            if "ChaCha20" in parse_archive_note_flags(note):
                extra_detail_parts.append("Archive payload decrypted via deterministic ChaCha20 filename derivation.")
            extra_detail_parts.append(media_detail)
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=metadata_summary,
                detail_text=build_archive_entry_detail_text(entry, "\n\n".join(part for part in extra_detail_parts if part)),
                preview_media_path=str(source_path.resolve()),
                preview_media_kind="video",
                preferred_view="media",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in ARCHIVE_AUDIO_EXTENSIONS:
            source_path, note = ensure_archive_preview_source(entry, stop_event=stop_event)
            media_source, playback_note = _ensure_media_preview_source_path(
                source_path,
                extension,
                stop_event=stop_event,
            )
            try:
                with source_path.open("rb") as handle:
                    audio_sample = handle.read(131072)
            except OSError:
                audio_sample = b""
            metadata_summary, media_detail = _build_wem_media_preview_detail_text(
                source_path,
                audio_sample,
                loose=False,
                playback_source_path=media_source,
                playback_note=playback_note,
            )
            extra_detail_parts: List[str] = []
            if "ChaCha20" in parse_archive_note_flags(note):
                extra_detail_parts.append("Archive payload decrypted via deterministic ChaCha20 filename derivation.")
            extra_detail_parts.append(media_detail)
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=metadata_summary,
                detail_text=build_archive_entry_detail_text(entry, "\n\n".join(part for part in extra_detail_parts if part)),
                preview_media_path=str(media_source),
                preview_media_kind="audio",
                preferred_view="media",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension == ".dds":
            source_path, note = ensure_archive_preview_source(entry, stop_event=stop_event)
            note_flags = parse_archive_note_flags(note)
            referencing_sidecar_entries = _find_archive_texture_referencing_sidecar_entries(
                entry,
                sidecar_entries_by_texture_path=sidecar_entries_by_texture_path,
                sidecar_entries_by_texture_basename=sidecar_entries_by_texture_basename,
            )
            combined_semantic_sidecar_texts: List[str] = [
                str(text or "").strip()
                for text in semantic_sidecar_texts
                if str(text or "").strip()
            ]
            for sidecar_text in _collect_archive_texture_sidecar_texts_from_entries(
                referencing_sidecar_entries,
                stop_event=stop_event,
            ):
                if sidecar_text not in combined_semantic_sidecar_texts:
                    combined_semantic_sidecar_texts.append(sidecar_text)
            related_references = build_archive_entry_related_references(
                entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
                sidecar_entries_by_texture_path=sidecar_entries_by_texture_path,
                sidecar_entries_by_texture_basename=sidecar_entries_by_texture_basename,
                companion_entries=referencing_sidecar_entries,
            )
            warning_badge = ""
            warning_text = ""
            extra_detail_parts: List[str] = []
            dds_info: Optional[DdsInfo] = None
            try:
                dds_info = parse_dds(source_path)
                metadata_summary = (
                    f"{metadata_summary} | {dds_info.texconv_format} | "
                    f"{dds_info.width}x{dds_info.height} | Mips {dds_info.mip_count}"
                )
                extra_detail_parts.append(
                    build_dds_header_detail_text(
                        source_path,
                        dds_info,
                        logical_path=entry.path,
                        sidecar_texts=tuple(combined_semantic_sidecar_texts),
                    )
                )
            except Exception as exc:
                extra_detail_parts.append(f"DDS metadata unavailable: {exc}")
            if "PartialDDS" in note_flags:
                extra_detail_parts.append(
                    "Type 1 DDS reconstructed successfully using meta/0.pathc partial-header metadata."
                )
            elif "SparseDDS" in note_flags:
                warning_badge = "Type 1 DDS: Unsupported Preview"
                warning_text = (
                    "This archive DDS is stored as truncated type 1 data. "
                    "The image shown here is a padded best-effort preview and may be corrupted, noisy, or incomplete."
                )
                extra_detail_parts.append(warning_text)
                if loose_file_path:
                    extra_detail_parts.append(f"Loose file candidate found: {loose_file_path}")
            if "ChaCha20" in note_flags:
                extra_detail_parts.append("Archive payload decrypted via deterministic ChaCha20 filename derivation.")
            pathc_lookup_detail = build_archive_pathc_lookup_detail_for_entry(entry)
            if pathc_lookup_detail:
                extra_detail_parts.append(pathc_lookup_detail)
            if texconv_path is None:
                return ArchivePreviewResult(
                    status="missing",
                    title=entry.basename,
                    metadata_summary=metadata_summary,
                    detail_text=build_archive_entry_detail_text(
                        entry,
                        "\n".join(
                            part
                            for part in [
                                "Set texconv.exe under Settings > Paths to enable DDS image previews.",
                                *extra_detail_parts,
                            ]
                            if part
                        ),
                    ),
                    preferred_view="info",
                    warning_badge=warning_badge,
                    warning_text=warning_text,
                    model_texture_references=related_references,
                    asset_family_graph=build_archive_asset_family_graph(entry, related_references),
                    loose_file_path=loose_file_path,
                    loose_preview_image_path=loose_preview_image_path,
                    loose_preview_media_path=loose_preview_media_path,
                    loose_preview_media_kind=loose_preview_media_kind,
                    loose_preview_title=loose_preview_title,
                    loose_preview_metadata_summary=loose_preview_metadata_summary,
                    loose_preview_detail_text=loose_preview_detail_text,
                )
            preview_png = ensure_dds_display_preview_png(
                texconv_path.resolve(),
                source_path.resolve(),
                dds_info=dds_info,
                stop_event=stop_event,
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=metadata_summary,
                detail_text=build_archive_entry_detail_text(entry, "\n\n".join(extra_detail_parts)),
                preview_image_path=str(preview_png),
                preferred_view="image",
                warning_badge=warning_badge,
                warning_text=warning_text,
                model_texture_references=related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, related_references),
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in ARCHIVE_IMAGE_EXTENSIONS:
            source_path, note = ensure_archive_preview_source(entry, stop_event=stop_event)
            related_references = build_archive_entry_related_references(
                entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=metadata_summary,
                detail_text=build_archive_entry_detail_text(
                    entry,
                    "Preview fallback: sparse DDS padding was applied."
                    if "SparseDDS" in parse_archive_note_flags(note)
                    else "",
                ),
                preview_image_path=str(source_path),
                preferred_view="image",
                model_texture_references=related_references,
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        entry_read_started_at = time.perf_counter()
        data, _decompressed, note = read_archive_entry_data(entry, stop_event=stop_event)
        add_timing("entry_read_s", entry_read_started_at)
        note_flags = parse_archive_note_flags(note)

        if extension == ".bnk":
            bnk_preview_text, bnk_detail_text = build_bnk_soundbank_preview(data)
            detail_extra = "\n\n".join(
                part
                for part in [
                    (
                        "Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes."
                        if "PartialRaw" in note_flags
                        else ""
                    ),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    bnk_detail_text,
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | Wwise SoundBank",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=bnk_preview_text or build_binary_strings_preview(data),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension == ".pathc":
            pathc_preview = build_archive_pathc_preview(data, entry.path)
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(pathc_preview.detail_lines),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | {pathc_preview.metadata_label}",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=pathc_preview.preview_text,
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension == ".pab":
            skeleton_preview = build_pab_preview(data, entry.path)
            related_references = build_archive_related_file_references(
                entry,
                explicit_reference_names=_extract_binary_asset_references(data, sample_limit=262_144, max_references=48),
                companion_entries=(
                    _find_archive_model_related_entries(entry, texture_entries_by_basename)
                    if texture_entries_by_basename is not None
                    else ()
                ),
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(skeleton_preview.detail_lines),
                    ("Companion and related files are listed below." if related_references else ""),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | Skeleton",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=skeleton_preview.preview_text,
                model_texture_references=related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, related_references),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension == ".meshinfo":
            meshinfo_preview = build_meshinfo_preview(
                data,
                entry.path,
                source_entry=entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(meshinfo_preview.detail_lines),
                    ("Companion and related files are listed below." if meshinfo_preview.related_references else ""),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | {meshinfo_preview.metadata_label or 'Mesh Metadata'}",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=meshinfo_preview.preview_text,
                model_texture_references=meshinfo_preview.related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, meshinfo_preview.related_references),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in {".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
            structured_preview = build_par_structured_preview(
                data,
                entry.path,
                extension=extension,
                source_entry=entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(structured_preview.detail_lines),
                    ("Companion and related files are listed below." if structured_preview.related_references else ""),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | {structured_preview.metadata_label or 'Structured Binary'}",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=structured_preview.preview_text,
                model_texture_references=structured_preview.related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, structured_preview.related_references),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in {".prefab", ".pappt", ".pamhc", ".seqmt", ".levelinfo", ".palevel", ".roadsector", ".road", ".nav", ".pabc", ".pabv", ".pabgb", ".pabgh"}:
            structured_preview = build_structured_asset_preview(
                data,
                entry.path,
                extension=extension,
                source_entry=entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
                stop_event=stop_event,
            )
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(structured_preview.detail_lines),
                    ("Companion and related files are listed below." if structured_preview.related_references else ""),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | {structured_preview.metadata_label or 'Structured Binary'}",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=structured_preview.preview_text,
                model_texture_references=structured_preview.related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, structured_preview.related_references),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in {".hkx", ".hkt"}:
            hkx_preview = build_hkx_preview(data, entry.path)
            related_references = build_archive_entry_related_references(
                entry,
                binary_data=data,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(hkx_preview.detail_lines),
                    ("Companion and related files are listed below." if related_references else ""),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | Havok",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=hkx_preview.preview_text,
                model_texture_references=related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, related_references),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in ARCHIVE_TEXT_EXTENSIONS:
            preview_bytes = data[:ARCHIVE_TEXT_PREVIEW_LIMIT]
            text = try_decode_text_like_archive_data(data) or preview_bytes.decode("utf-8", errors="replace")
            simplified_summary = build_simplified_text_asset_summary(
                text,
                extension=extension,
                virtual_path=entry.path,
            )
            related_references = build_archive_entry_related_references(
                entry,
                text=text,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            graph_references = build_archive_relationship_references(
                entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            if extension in {".app_xml", ".prefabdata_xml"}:
                related_references = graph_references
            else:
                related_references = merge_archive_reference_rows(related_references, graph_references)
            extra_note = ""
            if len(data) > ARCHIVE_TEXT_PREVIEW_LIMIT:
                extra_note = f"\n\nPreview truncated to {format_byte_size(ARCHIVE_TEXT_PREVIEW_LIMIT)}."
            if "PartialRaw" in note_flags:
                extra_note = "\n\n".join(
                    part
                    for part in [
                        "Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes.",
                        extra_note.strip(),
                    ]
                    if part
                )
            if "ChaCha20" in note_flags:
                extra_note = "\n\n".join(
                    part for part in ["Decrypted via deterministic ChaCha20 filename derivation.", extra_note.strip()] if part
                )
            if extension == ".obj":
                summary_text = summarize_obj_text(text)
                extra_note = "\n\n".join(part for part in [summary_text, extra_note.strip()] if part)
            if related_references:
                extra_note = "\n\n".join(
                    part for part in [extra_note.strip(), "Companion and related files are listed below."] if part
                )
            preview_text = text
            if simplified_summary:
                preview_text = f"{simplified_summary}\n\nRaw text preview:\n{text}"
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=metadata_summary,
                detail_text=build_archive_entry_detail_text(
                    entry,
                    "\n\n".join(
                        part
                        for part in [
                            ("Preview fallback: sparse DDS padding was applied." if "SparseDDS" in note_flags else ""),
                            extra_note.strip(),
                        ]
                        if part
                    ),
                ),
                preview_text=preview_text,
                model_texture_references=related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, related_references),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        info_extra_parts: List[str] = []
        if "SparseDDS" in note_flags:
            info_extra_parts.append("Preview fallback: sparse DDS padding was applied.")
        if "PartialPAR" in note_flags:
            info_extra_parts.append(
                "Archive entry uses Partial PAR storage; preview uses reconstructed decompressed sections."
            )
        if "PartialRaw" in note_flags:
            info_extra_parts.append(
                "Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes."
            )
        if "ChaCha20" in note_flags:
            info_extra_parts.append("Decrypted via deterministic ChaCha20 filename derivation.")
        model_preview = None
        model_texture_references: Tuple[ArchiveModelTextureReference, ...] = ()
        model_preview_error = ""
        parsed_mesh_for_references = None
        binary_texture_references: Tuple[str, ...] = ()
        sidecar_texture_references: Tuple[_ArchiveModelSidecarTextureBinding, ...] = ()
        sidecar_reference_paths: Tuple[str, ...] = ()
        sidecar_texts_by_normalized_path: Dict[str, Tuple[str, ...]] = {}
        sidecar_texts_by_basename: Dict[str, Tuple[str, ...]] = {}
        if extension in ARCHIVE_MODEL_EXTENSIONS:
            binary_refs_started_at = time.perf_counter()
            binary_texture_references = tuple(extract_binary_dds_references(data))
            add_timing("model_binary_ref_scan_s", binary_refs_started_at)
            sidecar_refs_started_at = time.perf_counter()
            (
                sidecar_texture_references,
                sidecar_reference_paths,
                sidecar_texts_by_normalized_path,
                sidecar_texts_by_basename,
            ) = _extract_archive_model_sidecar_texture_references(
                entry,
                archive_entries_by_basename=texture_entries_by_basename,
                stop_event=stop_event,
            )
            add_timing("model_sidecar_refs_s", sidecar_refs_started_at)
            if sidecar_texture_references:
                sidecar_count = len(sidecar_texture_references)
                sidecar_suffix = f" from {', '.join(sidecar_reference_paths[:2])}" if sidecar_reference_paths else ""
                if len(sidecar_reference_paths) > 2:
                    sidecar_suffix += " ..."
                info_extra_parts.append(
                    f"Companion material sidecar data contributed {sidecar_count:,} texture binding(s){sidecar_suffix}."
                )
                family_notice = _archive_texture_family_mismatch_summary(
                    entry.path,
                    tuple(str(getattr(binding, "texture_path", "") or "") for binding in sidecar_texture_references),
                    sidecar_paths=sidecar_reference_paths,
                )
                if family_notice:
                    info_extra_parts.append(family_notice)
                if extension in {".pam", ".pamlod", ".pac"}:
                    info_extra_parts.append(
                        "Companion sidecar data only describes material and texture bindings. Geometry preview still depends on recovering a renderable mesh layout from the selected payload or its mesh companion."
                    )
        if extension == ".pam":
            geometry_started_at = time.perf_counter()
            try:
                model_preview, model_info = _build_pam_model_preview_with_fallback(
                    entry,
                    data,
                    note_flags,
                    companion_entry=companion_entry,
                    stop_event=stop_event,
                )
                if getattr(model_preview, "format", "").lower() == "pamlod":
                    lod_label = (
                        f"LOD {model_preview.lod_index + 1} of {model_preview.lod_count}"
                        if getattr(model_preview, "lod_count", 0) > 0 and getattr(model_preview, "lod_index", -1) >= 0
                        else "highest-detail LOD"
                    )
                    metadata_summary = f"{metadata_summary} | {lod_label} | {model_preview.face_count:,} faces"
                else:
                    metadata_summary = (
                        f"{metadata_summary} | {model_preview.mesh_count:,} submesh(es)"
                        f" | {model_preview.face_count:,} faces"
                    )
                info_extra_parts.extend(model_info)
                if getattr(model_preview, "format", "").lower() == "pamlod":
                    info_extra_parts.append(
                        "Geometry preview uses the highest-detail recovered companion PAMLOD LOD only; lower-detail LODs are not stacked in the preview. "
                        "Texture and material references remain listed below."
                    )
                else:
                    info_extra_parts.append(
                        "Geometry preview uses recovered PAM submeshes with temporary material colors. "
                        "Texture and material references remain listed below."
                    )
            except RunCancelled:
                raise
            except Exception as exc:
                model_preview_error = str(exc)
                info_extra_parts.append(f"Visual model preview failed to recover geometry: {exc}")
            add_timing("model_geometry_s", geometry_started_at)
        elif extension == ".pamlod":
            geometry_started_at = time.perf_counter()
            try:
                model_preview, model_info = _build_pamlod_model_preview_with_fallback(
                    entry,
                    data,
                    note_flags,
                    companion_entry=companion_entry,
                    stop_event=stop_event,
                )
                if getattr(model_preview, "format", "").lower() == "pam":
                    metadata_summary = (
                        f"{metadata_summary} | {model_preview.mesh_count:,} submesh(es)"
                        f" | {model_preview.face_count:,} faces"
                    )
                else:
                    lod_label = (
                        f"LOD {model_preview.lod_index + 1} of {model_preview.lod_count}"
                        if getattr(model_preview, "lod_count", 0) > 0 and getattr(model_preview, "lod_index", -1) >= 0
                        else "highest-detail LOD"
                    )
                    metadata_summary = f"{metadata_summary} | {lod_label} | {model_preview.face_count:,} faces"
                info_extra_parts.extend(model_info)
                if getattr(model_preview, "format", "").lower() == "pam":
                    info_extra_parts.append(
                        "Geometry preview uses recovered companion PAM submeshes with temporary material colors. "
                        "Texture and material references remain listed below."
                    )
                else:
                    info_extra_parts.append(
                        "Geometry preview uses the highest-detail recovered PAMLOD LOD only; lower-detail LODs are not stacked in the preview. "
                        "Texture and material references remain listed below."
                    )
            except RunCancelled:
                raise
            except Exception as exc:
                model_preview_error = str(exc)
                info_extra_parts.append(f"Visual model preview failed to recover geometry: {exc}")
        elif extension == ".pac":
            geometry_started_at = time.perf_counter()
            try:
                model_preview, parsed_mesh, model_info = _build_pac_model_preview_with_fallback(
                    entry,
                    data,
                    note_flags,
                    stop_event=stop_event,
                )
                parsed_mesh_for_references = parsed_mesh
                metadata_summary = (
                    f"{metadata_summary} | {model_preview.mesh_count:,} submesh(es)"
                    f" | {model_preview.face_count:,} faces"
                )
                info_extra_parts.extend(model_info)
                info_extra_parts.append(
                    "Geometry preview uses recovered PAC skinned mesh data. Texture and material references remain listed below."
                )
                if getattr(parsed_mesh, "has_bones", False):
                    unique_bones = {
                        int(bone_index)
                        for submesh in getattr(parsed_mesh, "submeshes", [])
                        for palette in getattr(submesh, "bone_indices", [])
                        for bone_index in palette
                        if int(bone_index) >= 0
                    }
                    if unique_bones:
                        info_extra_parts.append(
                            f"Recovered skinning data referencing {len(unique_bones):,} bone slot(s)."
                        )
                unique_material_names = {
                    str(getattr(submesh, "material", "") or "").strip()
                    for submesh in getattr(parsed_mesh, "submeshes", ())
                    if str(getattr(submesh, "material", "") or "").strip()
                }
                unique_texture_names = {
                    str(getattr(submesh, "texture", "") or "").strip()
                    for submesh in getattr(parsed_mesh, "submeshes", ())
                    if str(getattr(submesh, "texture", "") or "").strip()
                }
                if getattr(parsed_mesh, "has_uvs", False):
                    info_extra_parts.append("Recovered UV coordinates for textured preview and export.")
                if unique_material_names:
                    info_extra_parts.append(f"Recovered {len(unique_material_names):,} material slot name(s) from the PAC payload.")
                if unique_texture_names:
                    info_extra_parts.append(f"Recovered {len(unique_texture_names):,} embedded texture reference name(s) from the PAC payload.")
                if texture_entries_by_basename is not None:
                    companion_pab_entries = [
                        related_entry
                        for related_entry in _find_archive_model_related_entries(entry, texture_entries_by_basename)
                        if related_entry.extension == ".pab"
                    ]
                    if companion_pab_entries:
                        info_extra_parts.append(f"Matching skeleton companion detected: {companion_pab_entries[0].path}")
            except Exception as exc:
                model_preview_error = str(exc)
                info_extra_parts.append(f"Visual model preview failed to recover geometry: {exc}")
            add_timing("model_geometry_s", geometry_started_at)
        elif extension in ARCHIVE_MODEL_EXTENSIONS:
            info_extra_parts.append("Visual preview is not available for this model format yet.")
        if (
            model_preview is not None
            and sidecar_texture_references
            and parsed_mesh_for_references is None
            and extension in ARCHIVE_MODEL_EXTENSIONS
        ):
            try:
                from cdmw.modding.mesh_parser import parse_mesh

                parsed_mesh_for_references = parse_mesh(data, entry.path)
            except RunCancelled:
                raise
            except Exception:
                parsed_mesh_for_references = None
        if model_preview is not None:
            if texconv_path is None:
                if any(
                    str(getattr(mesh, "texture_name", "") or "").strip().lower().endswith(".dds")
                    for mesh in model_preview.meshes
                ):
                    info_extra_parts.append(
                        "Set texconv.exe under Settings > Paths to enable textured model shading and PNG-backed model export."
                    )
            else:
                if normalized_visible_texture_mode == "mesh_base_first":
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_texture_preview_paths(
                            texconv_path,
                            entry,
                            model_preview,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_base_texture_attach_s", attach_started_at)
                if sidecar_texture_references:
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_sidecar_texture_preview_paths(
                            texconv_path,
                            entry,
                            model_preview,
                            parsed_mesh=parsed_mesh_for_references,
                            sidecar_texture_bindings=sidecar_texture_references,
                            visible_texture_mode=normalized_visible_texture_mode,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_sidecar_texture_attach_s", attach_started_at)
                if normalized_visible_texture_mode != "mesh_base_first":
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_texture_preview_paths(
                            texconv_path,
                            entry,
                            model_preview,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_base_texture_attach_s", attach_started_at)
                if sidecar_texture_references and normalized_visible_texture_mode == "mesh_base_first":
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_sidecar_texture_preview_paths(
                            texconv_path,
                            entry,
                            model_preview,
                            parsed_mesh=parsed_mesh_for_references,
                            sidecar_texture_bindings=sidecar_texture_references,
                            visible_texture_mode="layer_aware_visible",
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            fallback_only=True,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_sidecar_fallback_attach_s", attach_started_at)
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_texture_preview_paths(
                            texconv_path,
                            entry,
                            model_preview,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            override_existing_base=True,
                            prefer_material_name_for_base=True,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_base_texture_attach_s", attach_started_at)
                requested_support_texture_slots = {
                    str(value or "").strip().lower()
                    for value in (support_texture_slots or ())
                }
                normalized_support_texture_slots = tuple(
                    slot
                    for slot in ("normal", "material", "height")
                    if slot in requested_support_texture_slots
                )
                if normalized_support_texture_slots:
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_support_texture_preview_paths(
                            texconv_path,
                            entry,
                            model_preview,
                            parsed_mesh=parsed_mesh_for_references,
                            sidecar_texture_bindings=sidecar_texture_references,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            support_slots=normalized_support_texture_slots,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_support_texture_attach_s", attach_started_at)
        if extension in ARCHIVE_MODEL_EXTENSIONS and parsed_mesh_for_references is None:
            try:
                from cdmw.modding.mesh_parser import parse_mesh

                parsed_mesh_for_references = parse_mesh(data, entry.path)
            except RunCancelled:
                raise
            except Exception:
                parsed_mesh_for_references = None
        if (
            model_preview is not None
            or parsed_mesh_for_references is not None
            or binary_texture_references
            or sidecar_texture_references
            or extension in ARCHIVE_MODEL_EXTENSIONS
        ):
            references_started_at = time.perf_counter()
            model_texture_references = tuple(
                build_archive_model_texture_references(
                    entry,
                    model_preview,
                    parsed_mesh=parsed_mesh_for_references,
                    binary_texture_references=binary_texture_references,
                    sidecar_texture_references=sidecar_texture_references,
                    texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                    texture_entries_by_basename=texture_entries_by_basename,
                    sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                    sidecar_texts_by_basename=sidecar_texts_by_basename,
                )
            )
            graph_references = build_archive_relationship_references(
                entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            model_texture_references = merge_archive_reference_rows(model_texture_references, graph_references)
            add_timing("model_texture_references_s", references_started_at)
            if model_preview is not None and model_texture_references:
                overlay_started_at = time.perf_counter()
                overlay_notes = _attach_hkx_physics_overlay_to_model_preview(
                    model_preview,
                    model_texture_references,
                    stop_event=stop_event,
                )
                if overlay_notes:
                    info_extra_parts.extend(overlay_notes)
                add_timing("hkx_physics_overlay_s", overlay_started_at)
        binary_preview_started_at = time.perf_counter()
        preferred_view, preview_text, info_extra = build_archive_binary_preview_payload(
            entry,
            data,
            info_extra="\n".join(info_extra_parts),
        )
        header_preview = format_binary_header_preview(data[:ARCHIVE_BINARY_HEX_PREVIEW_LIMIT])
        detail_text = build_archive_entry_detail_text(
            entry,
            "\n\n".join(part for part in [info_extra, f"Binary header preview:\n{header_preview}"] if part).strip(),
        )
        add_timing("binary_preview_s", binary_preview_started_at)
        return ArchivePreviewResult(
            status="ok",
            title=entry.basename,
            metadata_summary=metadata_summary,
            detail_text=detail_text,
            timings=timings,
            preview_text=preview_text,
            preview_model=model_preview,
            model_texture_references=model_texture_references,
            asset_family_graph=build_archive_asset_family_graph(entry, model_texture_references),
            preferred_view="model" if model_preview is not None else preferred_view,
            warning_badge="Model preview fallback" if model_preview is None and model_preview_error else "",
            warning_text=model_preview_error if model_preview is None and model_preview_error else "",
            loose_file_path=loose_file_path,
            loose_preview_image_path=loose_preview_image_path,
            loose_preview_media_path=loose_preview_media_path,
            loose_preview_media_kind=loose_preview_media_kind,
            loose_preview_title=loose_preview_title,
            loose_preview_metadata_summary=loose_preview_metadata_summary,
            loose_preview_detail_text=loose_preview_detail_text,
        )
    except RunCancelled:
        raise
    except Exception as exc:
        try:
            raw_data = read_archive_entry_raw_data(entry)
        except Exception:
            raw_data = b""
        preferred_view = "info"
        preview_text = ""
        raw_extra_parts = [
            f"Decoded preview failed: {exc}",
            "Showing raw stored bytes instead.",
        ]
        if raw_data:
            raw_preferred_view, raw_preview_text, raw_extra = build_archive_binary_preview_payload(
                entry,
                raw_data,
            )
            preferred_view = raw_preferred_view
            preview_text = raw_preview_text
            if raw_extra:
                raw_extra_parts.append(raw_extra)
        raw_header_preview = format_binary_header_preview(raw_data[:ARCHIVE_BINARY_HEX_PREVIEW_LIMIT])
        return ArchivePreviewResult(
            status="ok",
            title=entry.basename,
            metadata_summary=metadata_summary,
            detail_text=build_archive_entry_detail_text(
                entry,
                "\n\n".join(part for part in [*raw_extra_parts, f"Binary header preview:\n{raw_header_preview}"] if part),
            ),
            preview_text=preview_text,
            preferred_view=preferred_view,
            warning_badge="Raw bytes",
            warning_text="Showing raw stored bytes because the decoded preview path failed.",
            loose_file_path=loose_file_path,
            loose_preview_image_path=loose_preview_image_path,
            loose_preview_media_path=loose_preview_media_path,
            loose_preview_media_kind=loose_preview_media_kind,
            loose_preview_title=loose_preview_title,
            loose_preview_metadata_summary=loose_preview_metadata_summary,
            loose_preview_detail_text=loose_preview_detail_text,
        )

