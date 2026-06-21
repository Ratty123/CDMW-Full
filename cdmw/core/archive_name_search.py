from __future__ import annotations

import bisect
import fnmatch
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict, defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.core.common import hidden_subprocess_kwargs, raise_if_cancelled
from cdmw.models import ArchiveEntry

_ARCHIVE_NAME_SEARCH_SHARD_META_VERSION = 1


def _archive_base_dir(package_root: Path) -> Path:
    from cdmw.core import archive as archive_core

    return archive_core._archive_base_dir(package_root)


def _archive_relative_source_path(base_dir: Path, path: Path) -> str:
    from cdmw.core import archive as archive_core

    return archive_core._archive_relative_source_path(base_dir, path)


def _archive_entry_item_alias_text(entry: ArchiveEntry, item_search_aliases: Optional[Mapping[str, str]]) -> str:
    from cdmw.core import archive as archive_core

    return archive_core._archive_entry_item_alias_text(entry, item_search_aliases)


def _archive_entry_shard_groups(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core import archive as archive_core

    return archive_core._archive_entry_shard_groups(*args, **kwargs)


def _archive_scan_shard_id(relative_pamt_path: str) -> str:
    from cdmw.core import archive as archive_core

    return archive_core._archive_scan_shard_id(relative_pamt_path)


def resolve_archive_name_search_shard_cache_dir(package_root: Path, cache_root: Path) -> Path:
    from cdmw.core import archive as archive_core

    return archive_core.resolve_archive_name_search_shard_cache_dir(package_root, cache_root)


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


def _native_name_search_cache_row_limit() -> int:
    raw_value = os.environ.get("CDMW_NATIVE_NAME_SEARCH_ROW_CACHE_LIMIT", "2000000")
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return 2_000_000


class _LazyNativeNameSearchTokenRows(Mapping[str, Tuple[int, ...]]):
    def __init__(
        self,
        data: bytes,
        row_spans: Mapping[str, Tuple[int, int]],
        *,
        entry_count: int,
        source_path: Path,
        max_cached_rows: Optional[int] = None,
    ) -> None:
        self._data = data
        self._row_spans: Dict[str, Tuple[int, int]] = dict(row_spans)
        self._entry_count = max(0, int(entry_count))
        self._source_path = Path(source_path)
        self._max_cached_rows = max(1, int(max_cached_rows or _native_name_search_cache_row_limit()))
        self._decoded_rows: OrderedDict[str, Tuple[int, ...]] = OrderedDict()
        self._decoded_row_count = 0
        self._lock = threading.RLock()

    @property
    def decoded_token_count(self) -> int:
        with self._lock:
            return len(self._decoded_rows)

    @property
    def decoded_row_count(self) -> int:
        with self._lock:
            return self._decoded_row_count

    @property
    def source_path(self) -> Path:
        return self._source_path

    def native_binary_data(self) -> bytes:
        return self._data

    def __getitem__(self, token: str) -> Tuple[int, ...]:
        key = str(token or "")
        with self._lock:
            cached = self._decoded_rows.get(key)
            if cached is not None:
                self._decoded_rows.move_to_end(key)
                return cached
            row_span = self._row_spans[key]
            rows = self._decode_rows(row_span)
            self._decoded_rows[key] = rows
            self._decoded_row_count += len(rows)
            self._evict_decoded_rows()
            return rows

    def get(self, token: object, default: Optional[Tuple[int, ...]] = None) -> Tuple[int, ...]:
        key = str(token or "")
        with self._lock:
            cached = self._decoded_rows.get(key)
            if cached is not None:
                self._decoded_rows.move_to_end(key)
                return cached
            row_span = self._row_spans.get(key)
            if row_span is None:
                return () if default is None else default
            rows = self._decode_rows(row_span)
            self._decoded_rows[key] = rows
            self._decoded_row_count += len(rows)
            self._evict_decoded_rows()
            return rows

    def __contains__(self, token: object) -> bool:
        return str(token or "") in self._row_spans

    def __iter__(self) -> Iterator[str]:
        return iter(self._row_spans)

    def __len__(self) -> int:
        return len(self._row_spans)

    def _decode_rows(self, row_span: Tuple[int, int]) -> Tuple[int, ...]:
        row_offset, row_count = row_span
        if row_count <= 0:
            return ()
        rows = struct.unpack_from(f"<{row_count}I", self._data, row_offset)
        entry_count = self._entry_count
        return tuple(int(row) for row in rows if 0 <= int(row) < entry_count)

    def _evict_decoded_rows(self) -> None:
        while self._decoded_row_count > self._max_cached_rows and len(self._decoded_rows) > 1:
            _token, rows = self._decoded_rows.popitem(last=False)
            self._decoded_row_count = max(0, self._decoded_row_count - len(rows))


class _MergedArchiveNameSearchTokenRows(Mapping[str, Tuple[int, ...]]):
    def __init__(
        self,
        shard_indexes: Sequence[Tuple[int, ArchiveNameSearchIndex]],
        *,
        source_shards: Optional[Mapping[str, Tuple[Path, Path]]] = None,
        max_cached_rows: Optional[int] = None,
    ) -> None:
        self._shard_indexes = tuple((int(offset), index) for offset, index in shard_indexes)
        self._source_shards = {
            str(relative_path): (Path(binary_path), Path(meta_path))
            for relative_path, (binary_path, meta_path) in (source_shards or {}).items()
        }
        token_set: set[str] = set()
        for _offset, index in self._shard_indexes:
            token_set.update(str(token) for token in index.token_rows)
        self._tokens = tuple(sorted(token_set))
        self._max_cached_rows = max(1, int(max_cached_rows or _native_name_search_cache_row_limit()))
        self._decoded_rows: OrderedDict[str, Tuple[int, ...]] = OrderedDict()
        self._decoded_row_count = 0
        self._lock = threading.RLock()

    @property
    def decoded_token_count(self) -> int:
        with self._lock:
            return len(self._decoded_rows)

    @property
    def decoded_row_count(self) -> int:
        with self._lock:
            return self._decoded_row_count

    def __getitem__(self, token: str) -> Tuple[int, ...]:
        key = str(token or "")
        with self._lock:
            cached = self._decoded_rows.get(key)
            if cached is not None:
                self._decoded_rows.move_to_end(key)
                return cached
            rows: set[int] = set()
            for offset, index in self._shard_indexes:
                local_rows = index.token_rows.get(key, ())
                for row in local_rows:
                    rows.add(offset + int(row))
            merged_rows = tuple(sorted(rows))
            self._decoded_rows[key] = merged_rows
            self._decoded_rows.move_to_end(key)
            self._decoded_row_count += len(merged_rows)
            while self._decoded_row_count > self._max_cached_rows and len(self._decoded_rows) > 1:
                _old_token, old_rows = self._decoded_rows.popitem(last=False)
                self._decoded_row_count = max(0, self._decoded_row_count - len(old_rows))
            return merged_rows

    def __iter__(self) -> Iterator[str]:
        return iter(self._tokens)

    def __len__(self) -> int:
        return len(self._tokens)

    def copy_shards_to(
        self,
        cache_dir: Path,
        groups: Sequence[_ArchiveEntryShardGroup],
        *,
        alias_signature: str,
    ) -> bool:
        if not self._source_shards:
            return False
        copy_plan: List[Tuple[Path, Path, Path, Path]] = []
        for group in groups:
            paths = self._source_shards.get(group.relative_pamt_path)
            if paths is None:
                return False
            source_binary_path, source_meta_path = paths
            if not source_binary_path.is_file() or not source_meta_path.is_file():
                return False
            try:
                meta = _read_archive_name_search_shard_meta(source_meta_path)
            except Exception:
                return False
            if not _archive_name_search_shard_meta_matches(meta, group, alias_signature=alias_signature):
                return False
            copy_plan.append(
                (
                    source_binary_path,
                    source_meta_path,
                    _archive_name_search_shard_binary_path(cache_dir, group.relative_pamt_path),
                    _archive_name_search_shard_meta_path(cache_dir, group.relative_pamt_path),
                )
            )
        cache_dir.mkdir(parents=True, exist_ok=True)
        for source_binary_path, source_meta_path, target_binary_path, target_meta_path in copy_plan:
            try:
                if source_binary_path.resolve() != target_binary_path.resolve():
                    shutil.copy2(source_binary_path, target_binary_path)
                if source_meta_path.resolve() != target_meta_path.resolve():
                    shutil.copy2(source_meta_path, target_meta_path)
            except OSError:
                return False
        return True


def _build_archive_name_search_index_python(
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


def _archive_name_search_native_min_entries() -> int:
    raw_value = os.environ.get("CDMW_NATIVE_NAME_SEARCH_MIN_ENTRIES", "100000")
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        return 100000


def _sanitize_native_name_search_field(value: object) -> str:
    return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def _load_native_name_search_index_binary(
    binary_path: Path,
    entries: Sequence[ArchiveEntry],
    *,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> ArchiveNameSearchIndex:
    data = Path(binary_path).read_bytes()
    if len(data) < 20 or data[:8] != b"CDNIDX1\0":
        raise ValueError("native name-search index header is not recognized")
    offset = 8

    def read_u16() -> int:
        nonlocal offset
        if offset + 2 > len(data):
            raise ValueError("native name-search index is truncated")
        value = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        return int(value)

    def read_u32() -> int:
        nonlocal offset
        if offset + 4 > len(data):
            raise ValueError("native name-search index is truncated")
        value = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        return int(value)

    version = read_u32()
    if version != 1:
        raise ValueError(f"unsupported native name-search index version: {version}")
    entry_count = read_u32()
    token_count = read_u32()
    if entry_count != len(entries):
        raise ValueError("native name-search index entry count does not match")
    token_row_spans: Dict[str, Tuple[int, int]] = {}
    progress_every = max(1, token_count // 20) if token_count else 1
    if on_progress is not None:
        on_progress(0, max(token_count, 1), f"Loading native archive name search index... 0 / {token_count:,} token(s)")
    for token_index in range(token_count):
        token_size = read_u16()
        if offset + token_size > len(data):
            raise ValueError("native name-search token is truncated")
        token = data[offset : offset + token_size].decode("utf-8", errors="replace")
        offset += token_size
        row_count = read_u32()
        byte_count = row_count * 4
        if offset + byte_count > len(data):
            raise ValueError("native name-search posting list is truncated")
        row_offset = offset
        offset += byte_count
        if token:
            token_row_spans[token] = (row_offset, row_count)
        if on_progress is not None and (
            token_index == 0
            or (token_index + 1) % progress_every == 0
            or token_index + 1 == token_count
        ):
            on_progress(
                token_index + 1,
                max(token_count, 1),
                f"Loading native archive name search index... {token_index + 1:,} / {token_count:,} token(s)",
            )
    if offset != len(data):
        raise ValueError("native name-search index has trailing data")
    token_rows = _LazyNativeNameSearchTokenRows(
        data,
        token_row_spans,
        entry_count=len(entries),
        source_path=Path(binary_path),
    )
    return ArchiveNameSearchIndex(
        entries=entries,
        token_rows=token_rows,
        sorted_tokens=tuple(sorted(token_row_spans)),
        common_aliases=_ARCHIVE_NAME_SEARCH_QUERY_ALIASES,
    )


def _write_native_name_search_index_binary(
    binary_path: Path,
    index: ArchiveNameSearchIndex,
    entry_count: int,
) -> None:
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    if (
        int(entry_count) == int(index.entry_count)
        and isinstance(index.token_rows, _LazyNativeNameSearchTokenRows)
    ):
        try:
            if binary_path.resolve() == index.token_rows.source_path.resolve() and binary_path.is_file():
                return
        except OSError:
            pass
        binary_path.write_bytes(index.token_rows.native_binary_data())
        return
    with binary_path.open("wb") as handle:
        handle.write(b"CDNIDX1\0")
        handle.write(struct.pack("<III", 1, int(entry_count), len(index.token_rows)))
        for token in sorted(index.token_rows):
            token_bytes = str(token).encode("utf-8", errors="replace")
            if len(token_bytes) > 0xFFFF:
                continue
            rows = tuple(int(row) for row in index.token_rows.get(token, ()) if 0 <= int(row) < int(entry_count))
            handle.write(struct.pack("<H", len(token_bytes)))
            handle.write(token_bytes)
            handle.write(struct.pack("<I", len(rows)))
            if rows:
                handle.write(struct.pack(f"<{len(rows)}I", *rows))


def _try_build_archive_name_search_index_native(
    entries: Sequence[ArchiveEntry],
    *,
    item_search_aliases: Optional[Mapping[str, str]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Optional[ArchiveNameSearchIndex]:
    if os.environ.get("CDMW_DISABLE_NATIVE_NAME_SEARCH", "").strip() in {"1", "true", "yes"}:
        return None
    try:
        from cdmw.rendering.native_preview_core import find_native_preview_core_binary
    except Exception:
        return None
    binary = find_native_preview_core_binary()
    if binary is None:
        return None
    total_entries = len(entries)
    progress_total = max(total_entries, 1)
    if on_progress:
        on_progress(0 if total_entries > 0 else 1, progress_total, "Preparing native archive name search input...")

    def emit_native_progress(progress_path: Path, last_key: str) -> str:
        if on_progress is None or not progress_path.is_file():
            return last_key
        try:
            payload = json.loads(progress_path.read_text(encoding="utf-8"))
        except Exception:
            return last_key
        if not isinstance(payload, Mapping):
            return last_key
        stage = str(payload.get("stage") or "").strip().lower()
        processed_entries = int(payload.get("processed_entries") or 0)
        token_count = int(payload.get("token_count") or 0)
        posting_count = int(payload.get("posting_count") or 0)
        key = f"{stage}:{processed_entries}:{token_count}:{posting_count}"
        if key == last_key:
            return last_key
        if stage == "tokenize":
            on_progress(
                min(processed_entries, progress_total),
                progress_total,
                f"Building archive name search index with native helper... {processed_entries:,} / {total_entries:,} entries | {token_count:,} token(s)",
            )
        elif stage == "write":
            on_progress(
                progress_total,
                progress_total,
                f"Writing native archive name search index... {token_count:,} token(s) | {posting_count:,} posting(s)",
            )
        elif stage == "complete":
            on_progress(
                progress_total,
                progress_total,
                f"Native archive name search index built: {token_count:,} token(s), {posting_count:,} posting(s)",
            )
        elif stage == "error":
            on_progress(progress_total, progress_total, "Native archive name search index failed; falling back to Python...")
        return key

    with tempfile.TemporaryDirectory(prefix="cdmw_name_search_") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "entries.tsv"
        output_path = temp_path / "name_index.bin"
        report_path = temp_path / "name_index_report.json"
        progress_path = temp_path / "name_index_progress.json"
        input_update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000
        with input_path.open("w", encoding="utf-8", newline="\n") as handle:
            for entry_index, entry in enumerate(entries):
                if stop_event is not None and (entry_index == 0 or entry_index % 4096 == 0):
                    raise_if_cancelled(stop_event)
                alias_text = _archive_entry_item_alias_text(entry, item_search_aliases)
                handle.write(
                    f"{entry_index}\t"
                    f"{_sanitize_native_name_search_field(entry.path)}\t"
                    # The full archive path already includes the basename. Keep
                    # the field for native TSV compatibility, but avoid sending
                    # duplicate text through the hot startup path.
                    f"\t"
                    f"{_sanitize_native_name_search_field(alias_text)}\n"
                )
                if on_progress is not None and (
                    entry_index == 0
                    or (entry_index + 1) % input_update_every == 0
                    or entry_index + 1 == total_entries
                ):
                    on_progress(
                        entry_index + 1,
                        progress_total,
                        f"Preparing native archive name search input... {entry_index + 1:,} / {total_entries:,} entries",
                    )
        if on_progress is not None:
            on_progress(0 if total_entries > 0 else 1, progress_total, "Building archive name search index with native helper...")
        command = [str(binary), "name-index-job", str(input_path), str(output_path), str(report_path), str(progress_path)]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
        deadline = time.monotonic() + 120.0
        last_progress_key = ""
        while process.poll() is None:
            if stop_event is not None:
                raise_if_cancelled(stop_event)
            last_progress_key = emit_native_progress(progress_path, last_progress_key)
            if time.monotonic() > deadline:
                try:
                    process.kill()
                finally:
                    process.communicate(timeout=2.0)
                return None
            time.sleep(0.15)
        stdout_text, stderr_text = process.communicate()
        last_progress_key = emit_native_progress(progress_path, last_progress_key)
        if process.returncode != 0 or not output_path.is_file():
            return None
        if on_progress is not None:
            on_progress(progress_total, progress_total, "Loading native archive name search index...")
        return _load_native_name_search_index_binary(output_path, entries, on_progress=on_progress)


def build_archive_name_search_index(
    entries: Sequence[ArchiveEntry],
    *,
    item_search_aliases: Optional[Mapping[str, str]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> ArchiveNameSearchIndex:
    if len(entries) >= _archive_name_search_native_min_entries():
        native_index = _try_build_archive_name_search_index_native(
            entries,
            item_search_aliases=item_search_aliases,
            on_progress=on_progress,
            stop_event=stop_event,
        )
        if native_index is not None:
            return native_index
    return _build_archive_name_search_index_python(
        entries,
        item_search_aliases=item_search_aliases,
        on_progress=on_progress,
        stop_event=stop_event,
    )


def _archive_name_search_alias_signature(item_search_aliases: Optional[Mapping[str, str]]) -> str:
    payload = {
        str(key).casefold(): str(value)
        for key, value in (item_search_aliases or {}).items()
        if str(key or "").strip() or str(value or "").strip()
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8",
        errors="replace",
    )
    return hashlib.sha256(encoded).hexdigest()


def _archive_entry_package_group(entry: ArchiveEntry) -> str:
    try:
        return entry.pamt_path.parent.name.lower()
    except Exception:
        return ""


def archive_item_index_dependency_signature(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    stop_event: Optional[threading.Event] = None,
) -> str:
    selected_signatures: List[Tuple[object, ...]] = []
    base_dir = _archive_base_dir(package_root)
    paz_stamp_cache: Dict[str, Tuple[int, int]] = {}

    def entry_signature(entry: ArchiveEntry) -> Tuple[object, ...]:
        paz_path = Path(getattr(entry, "paz_file", ""))
        try:
            paz_key = os.path.normcase(os.fspath(paz_path)).strip().lower()
        except (OSError, TypeError, ValueError):
            paz_key = str(paz_path).strip().lower()
        paz_stamp = paz_stamp_cache.get(paz_key)
        if paz_stamp is None:
            try:
                paz_stat = paz_path.stat()
                paz_stamp = (
                    int(paz_stat.st_size),
                    int(getattr(paz_stat, "st_mtime_ns", int(paz_stat.st_mtime * 1_000_000_000))),
                )
            except OSError:
                paz_stamp = (0, 0)
            paz_stamp_cache[paz_key] = paz_stamp
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

    localization_table_names = (
        "localizationstring_kor",
        "localizationstring_eng",
        "localizationstring_jpn",
        "localizationstring_rus",
        "localizationstring_tur",
        "localizationstring_spa-es",
        "localizationstring_spa-mx",
        "localizationstring_fre",
        "localizationstring_ger",
        "localizationstring_ita",
        "localizationstring_pol",
        "localizationstring_por-br",
        "localizationstring_zho-tw",
        "localizationstring_zho-cn",
    )
    icon_prefixes = ("itemicon_prefab_", "itemicon_", "icon_prefab_", "icon_")
    for index, entry in enumerate(entries):
        if index % 4096 == 0:
            raise_if_cancelled(stop_event)
        lower_path = str(getattr(entry, "path", "") or "").replace("\\", "/").lower()
        basename = os.path.basename(lower_path)
        stem = os.path.splitext(basename)[0]
        group = _archive_entry_package_group(entry)
        wants_localization = group == "0020" and any(table_name in lower_path for table_name in localization_table_names)
        wants_iteminfo = group == "0008" and "iteminfo.pabgb" in lower_path
        wants_stringinfo = group == "0008" and basename == "stringinfo.pabgb"
        wants_part_prefab_dye_slot = group == "0008" and basename == "partprefabdyeslotinfo.pabgb"
        wants_material_match = group == "0008" and basename == "materialmatchinfo.pabgb"
        wants_model_hash = lower_path.endswith((".prefab", ".pac", ".pact"))
        wants_item_icon = lower_path.endswith(".dds") and (
            "itemicon" in lower_path
            or any(stem.startswith(prefix) for prefix in icon_prefixes)
        )
        if (
            wants_localization
            or wants_iteminfo
            or wants_stringinfo
            or wants_part_prefab_dye_slot
            or wants_material_match
            or wants_model_hash
            or wants_item_icon
        ):
            selected_signatures.append(entry_signature(entry))
    payload = {
        "format": 1,
        "dependency_count": len(selected_signatures),
        "dependencies": selected_signatures,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8",
        errors="replace",
    )
    return hashlib.sha256(encoded).hexdigest()


def _archive_name_search_shard_binary_path(cache_dir: Path, relative_pamt_path: str) -> Path:
    return cache_dir / f"{_archive_scan_shard_id(relative_pamt_path)}.bin"


def _archive_name_search_shard_meta_path(cache_dir: Path, relative_pamt_path: str) -> Path:
    return cache_dir / f"{_archive_scan_shard_id(relative_pamt_path)}.json"


def _read_archive_name_search_shard_meta(meta_path: Path) -> dict:
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("name-search shard metadata is invalid")
    return payload


def _write_archive_name_search_shard_meta(meta_path: Path, payload: Mapping[str, object]) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = meta_path.with_suffix(meta_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp_path.replace(meta_path)


def _archive_name_search_shard_meta_matches(
    meta: Mapping[str, object],
    group: _ArchiveEntryShardGroup,
    *,
    alias_signature: str,
) -> bool:
    return (
        int(meta.get("version", 0) or 0) == _ARCHIVE_NAME_SEARCH_SHARD_META_VERSION
        and str(meta.get("relative_pamt_path") or "").replace("\\", "/") == group.relative_pamt_path.replace("\\", "/")
        and int(meta.get("entry_count", -1) or -1) == len(group.entries)
        and str(meta.get("entry_list_signature") or "") == group.entry_list_signature
        and str(meta.get("alias_signature") or "") == alias_signature
    )


def _archive_name_search_shards_ready(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    item_search_aliases: Optional[Mapping[str, str]],
) -> bool:
    cache_dir = resolve_archive_name_search_shard_cache_dir(package_root, cache_root)
    alias_signature = _archive_name_search_alias_signature(item_search_aliases)
    for group in _archive_entry_shard_groups(package_root, entries):
        meta_path = _archive_name_search_shard_meta_path(cache_dir, group.relative_pamt_path)
        binary_path = _archive_name_search_shard_binary_path(cache_dir, group.relative_pamt_path)
        if not meta_path.is_file() or not binary_path.is_file():
            return False
        try:
            meta = _read_archive_name_search_shard_meta(meta_path)
        except Exception:
            return False
        if not _archive_name_search_shard_meta_matches(meta, group, alias_signature=alias_signature):
            return False
    return True


def _load_archive_name_search_shards_trusted(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> ArchiveNameSearchIndex:
    groups = _archive_entry_shard_groups(
        package_root,
        entries,
        include_signatures=False,
        on_progress=on_progress,
        stop_event=stop_event,
        progress_label="Preparing archive search cache (2/3): path/name index",
    )
    cache_dir = resolve_archive_name_search_shard_cache_dir(package_root, cache_root)
    shard_indexes: List[Tuple[int, ArchiveNameSearchIndex]] = []
    source_shards: Dict[str, Tuple[Path, Path]] = {}
    total_groups = len(groups)
    for index, group in enumerate(groups, start=1):
        raise_if_cancelled(stop_event)
        binary_path = _archive_name_search_shard_binary_path(cache_dir, group.relative_pamt_path)
        meta_path = _archive_name_search_shard_meta_path(cache_dir, group.relative_pamt_path)
        if not binary_path.is_file() or not meta_path.is_file():
            raise FileNotFoundError(f"name-search shard missing: {group.relative_pamt_path}")
        source_shards[group.relative_pamt_path] = (binary_path, meta_path)
        shard_indexes.append(
            (
                group.start_index,
                _load_native_name_search_index_binary(
                    binary_path,
                    group.entries,
                    on_progress=None,
                ),
            )
        )
        if on_progress is not None and (index == 1 or index % 20 == 0 or index == total_groups):
            on_progress(index, max(total_groups, 1), f"Loading archive search cache (2/3): path/name index... {index:,} / {total_groups:,}")
    token_rows = _MergedArchiveNameSearchTokenRows(shard_indexes, source_shards=source_shards)
    return ArchiveNameSearchIndex(
        entries=entries,
        token_rows=token_rows,
        sorted_tokens=tuple(token_rows),
        common_aliases=_ARCHIVE_NAME_SEARCH_QUERY_ALIASES,
    )


def _write_archive_name_search_index_shard(
    cache_dir: Path,
    group: _ArchiveEntryShardGroup,
    index: ArchiveNameSearchIndex,
    *,
    alias_signature: str,
) -> None:
    binary_path = _archive_name_search_shard_binary_path(cache_dir, group.relative_pamt_path)
    meta_path = _archive_name_search_shard_meta_path(cache_dir, group.relative_pamt_path)
    _write_native_name_search_index_binary(binary_path, index, len(group.entries))
    _write_archive_name_search_shard_meta(
        meta_path,
        {
            "version": _ARCHIVE_NAME_SEARCH_SHARD_META_VERSION,
            "created_at": time.time(),
            "relative_pamt_path": group.relative_pamt_path,
            "entry_count": len(group.entries),
            "entry_list_signature": group.entry_list_signature,
            "alias_signature": alias_signature,
            "token_count": len(index.token_rows),
        },
    )


def _load_or_update_archive_name_search_shards(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    item_search_aliases: Optional[Mapping[str, str]],
    *,
    load_name_search_index: bool = True,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Optional[ArchiveNameSearchIndex]:
    groups = _archive_entry_shard_groups(package_root, entries)
    cache_dir = resolve_archive_name_search_shard_cache_dir(package_root, cache_root)
    alias_signature = _archive_name_search_alias_signature(item_search_aliases)
    stale_groups: List[_ArchiveEntryShardGroup] = []
    loaded_meta: Dict[str, dict] = {}
    stale_reason_samples: List[str] = []
    for group in groups:
        meta_path = _archive_name_search_shard_meta_path(cache_dir, group.relative_pamt_path)
        binary_path = _archive_name_search_shard_binary_path(cache_dir, group.relative_pamt_path)
        try:
            if not meta_path.is_file() or not binary_path.is_file():
                raise ValueError("added")
            meta = _read_archive_name_search_shard_meta(meta_path)
            if not _archive_name_search_shard_meta_matches(meta, group, alias_signature=alias_signature):
                if str(meta.get("alias_signature") or "") != alias_signature:
                    raise ValueError("item alias signature changed")
                raise ValueError("entry list changed")
            loaded_meta[group.relative_pamt_path] = meta
        except Exception as exc:
            if len(stale_reason_samples) < 3:
                stale_reason_samples.append(f"{group.relative_pamt_path} {str(exc).strip() or 'changed'}")
            stale_groups.append(group)
    if stale_groups and on_log is not None:
        sample_text = "; ".join(stale_reason_samples)
        suffix = f" ({sample_text})" if sample_text else ""
        on_log(f"Archive search cache needs {len(stale_groups):,} shard(s) rebuilt{suffix}.")
    if stale_groups and not load_name_search_index:
        return None
    if stale_groups:
        cache_dir.mkdir(parents=True, exist_ok=True)
        total = len(stale_groups)
        for index, group in enumerate(stale_groups, start=1):
            raise_if_cancelled(stop_event)
            if on_progress is not None:
                on_progress(
                    index - 1,
                    max(total, 1),
                    f"Preparing archive search cache (2/3): path/name index... {index:,} / {total:,}",
                )
            shard_index = _build_archive_name_search_index_python(
                group.entries,
                item_search_aliases=item_search_aliases,
                stop_event=stop_event,
            )
            _write_archive_name_search_index_shard(
                cache_dir,
                group,
                shard_index,
                alias_signature=alias_signature,
            )
        if on_log is not None:
            on_log(f"Archive search cache updated: {len(stale_groups):,} shard(s) rebuilt.")
    if not load_name_search_index:
        return None
    shard_indexes: List[Tuple[int, ArchiveNameSearchIndex]] = []
    source_shards: Dict[str, Tuple[Path, Path]] = {}
    total_groups = len(groups)
    for index, group in enumerate(groups, start=1):
        raise_if_cancelled(stop_event)
        binary_path = _archive_name_search_shard_binary_path(cache_dir, group.relative_pamt_path)
        meta_path = _archive_name_search_shard_meta_path(cache_dir, group.relative_pamt_path)
        source_shards[group.relative_pamt_path] = (binary_path, meta_path)
        shard_indexes.append(
            (
                group.start_index,
                _load_native_name_search_index_binary(
                    binary_path,
                    group.entries,
                    on_progress=None,
                ),
            )
        )
        if on_progress is not None and (index == 1 or index % 20 == 0 or index == total_groups):
            on_progress(index, max(total_groups, 1), f"Loading archive search cache (2/3): path/name index... {index:,} / {total_groups:,}")
    token_rows = _MergedArchiveNameSearchTokenRows(shard_indexes, source_shards=source_shards)
    return ArchiveNameSearchIndex(
        entries=entries,
        token_rows=token_rows,
        sorted_tokens=tuple(token_rows),
        common_aliases=_ARCHIVE_NAME_SEARCH_QUERY_ALIASES,
    )


def load_or_update_archive_name_search_shards(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    item_search_aliases: Optional[Mapping[str, str]],
    *,
    load_name_search_index: bool = True,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Optional[ArchiveNameSearchIndex]:
    return _load_or_update_archive_name_search_shards(
        package_root,
        cache_root,
        entries,
        item_search_aliases,
        load_name_search_index=load_name_search_index,
        on_progress=on_progress,
        on_log=on_log,
        stop_event=stop_event,
    )


def _write_archive_name_search_shard_caches(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    archive_name_search_index: ArchiveNameSearchIndex,
    item_search_aliases: Optional[Mapping[str, str]],
) -> Path:
    groups = _archive_entry_shard_groups(package_root, entries)
    cache_dir = resolve_archive_name_search_shard_cache_dir(package_root, cache_root)
    cache_dir.mkdir(parents=True, exist_ok=True)
    alias_signature = _archive_name_search_alias_signature(item_search_aliases)
    if not groups:
        return cache_dir
    if isinstance(archive_name_search_index.token_rows, _MergedArchiveNameSearchTokenRows):
        if archive_name_search_index.token_rows.copy_shards_to(
            cache_dir,
            groups,
            alias_signature=alias_signature,
        ):
            return cache_dir
    starts = [group.start_index for group in groups]
    ends = [group.start_index + len(group.entries) for group in groups]
    token_rows_by_group: List[Dict[str, List[int]]] = [defaultdict(list) for _group in groups]
    for token in archive_name_search_index.token_rows:
        rows = archive_name_search_index.token_rows.get(token, ())
        for raw_row in rows:
            row = int(raw_row)
            group_index = bisect.bisect_right(starts, row) - 1
            if group_index < 0 or group_index >= len(groups):
                continue
            if row >= ends[group_index]:
                continue
            token_rows_by_group[group_index][str(token)].append(row - starts[group_index])
    for group_index, group in enumerate(groups):
        local_rows = {
            token: tuple(sorted(set(rows)))
            for token, rows in token_rows_by_group[group_index].items()
            if token and rows
        }
        shard_index = ArchiveNameSearchIndex(
            entries=group.entries,
            token_rows=local_rows,
            sorted_tokens=tuple(sorted(local_rows)),
            common_aliases=_ARCHIVE_NAME_SEARCH_QUERY_ALIASES,
        )
        _write_archive_name_search_index_shard(
            cache_dir,
            group,
            shard_index,
            alias_signature=alias_signature,
        )
    return cache_dir


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
