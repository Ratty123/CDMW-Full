"""Reader and writer for the Crimson Desert `.paloc` string table.

`gamedata/stringtable/binary__/localizationstring_<lang>.paloc` holds every line of
text the game shows: quest dialogue, item names, UI labels, subtitles. There are 14 of
them, one per language, and each carries the same 187,521 entries.

The decoded table is a flat run of records with the count at the *end* of the
payload:

    repeat count times:
        u32 category          one of 38 values; groups entries by where they are used
        u32 reserved          zero in all 562,563 records across the three languages read
        u32 key_length;   key   UTF-8
        u32 text_length;  text  UTF-8, may be empty
    u32 count                 the footer

Some files wrap that payload in a 512-byte header: `paloc`, u32 version (0),
u32 compressed size, u32 uncompressed size, then opaque padding. The remaining
bytes are an LZ4 block, independent of the archive entry's compression flags.
Edits retain the source container and untouched tables re-encode byte for byte.

Nothing is offset-addressed and nothing is aligned, so a translated line may be any
length: rewriting the table is just re-emitting the records. That is what makes
`.paloc` the one game format where an edit cannot corrupt anything downstream.

Keys are identifiers rather than indices -- `questdialog_main_01262`,
`aidialogstringinfogroup_cheerup_36512` -- and about 30% of them are bare numbers.
Both forms are UTF-8 and both are preserved verbatim. The bare numbers are u64s the
game derives from a table row (`(row key << 32) | field tag`; an item's name is tag
0x70, its description 0x71) and the tables keep them in ascending order, which is why
:func:`add_localization_entries` slots a new numeric key in rather than appending.
"""

from __future__ import annotations

import struct
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Iterable, Mapping, Sequence, Tuple

try:
    import lz4.block as lz4_block
except ImportError:
    lz4_block = None

#: The count is a u32 footer, so a valid file is at least that.
_FOOTER = 4
_RECORD_HEAD = 12
_CONTAINER_MAGIC = b"paloc"
_CONTAINER_HEADER = 512
# Check the declared expansion before asking LZ4 to allocate an output buffer.
_MAX_CONTAINER_PAYLOAD = 256 * 1024 * 1024


class PalocFormatError(ValueError):
    """Raised when a buffer is not a `.paloc` string table."""


@dataclass(frozen=True)
class LocalizationEntry:
    """One line of game text and the key the engine looks it up by."""

    category: int
    key: str
    text: str
    #: Zero in every shipped record. Kept so a rebuild cannot invent a value.
    reserved: int = 0


@dataclass(frozen=True)
class LocalizationTable:
    """A parsed `.paloc`."""

    entries: Tuple[LocalizationEntry, ...]
    #: Original wrapper retained for exact rebuilds and container-preserving edits.
    source_container: bytes = field(default=b"", repr=False, compare=False)

    def __len__(self) -> int:
        return len(self.entries)

    def index(self) -> Mapping[str, LocalizationEntry]:
        """key -> entry. Later duplicates win, matching a sequential table load."""

        return {entry.key: entry for entry in self.entries}

    def categories(self) -> Mapping[int, int]:
        return dict(Counter(entry.category for entry in self.entries))


def _container_payload(data: bytes, where: str) -> bytes:
    if len(data) < _CONTAINER_HEADER:
        raise PalocFormatError(f"PALOC container header is truncated{where}")
    version, stored_size, payload_size = struct.unpack_from("<III", data, 5)
    if version != 0:
        raise PalocFormatError(f"unsupported PALOC container version {version}{where}")
    if stored_size != len(data) - _CONTAINER_HEADER:
        raise PalocFormatError(f"PALOC container compressed size does not match its bytes{where}")
    if not _FOOTER <= payload_size <= _MAX_CONTAINER_PAYLOAD:
        raise PalocFormatError(f"PALOC container uncompressed size is out of bounds{where}")
    if lz4_block is None:
        raise PalocFormatError(f"compressed PALOC containers require the lz4 package{where}")
    try:
        payload = lz4_block.decompress(data[_CONTAINER_HEADER:], uncompressed_size=payload_size)
    except lz4_block.LZ4BlockError as exc:
        raise PalocFormatError(f"PALOC container LZ4 decompression failed{where}: {exc}") from exc
    if len(payload) != payload_size:
        raise PalocFormatError(f"PALOC container uncompressed size does not match its payload{where}")
    return payload


def parse_paloc(data: bytes, *, name: str = "") -> LocalizationTable:
    """Parse a `.paloc` string table.

    The footer count and the record walk have to agree on how many records there are,
    and the walk has to land exactly on the footer. Either check failing means this is
    not the format, rather than a table that happens to be short.
    """

    where = f" ({name})" if name else ""
    container = data if data.startswith(_CONTAINER_MAGIC) else b""
    if container:
        data = _container_payload(container, where)
    if len(data) < _FOOTER:
        raise PalocFormatError(f"buffer is too short to hold a count{where}")
    declared = struct.unpack_from("<I", data, len(data) - _FOOTER)[0]
    limit = len(data) - _FOOTER
    entries: list[LocalizationEntry] = []
    pos = 0
    while pos < limit:
        if pos + _RECORD_HEAD > limit:
            raise PalocFormatError(f"record header at 0x{pos:X} runs past the table{where}")
        category, reserved, key_length = struct.unpack_from("<III", data, pos)
        pos += _RECORD_HEAD
        if pos + key_length + 4 > limit:
            raise PalocFormatError(f"key at 0x{pos:X} runs past the table{where}")
        key = data[pos: pos + key_length]
        pos += key_length
        text_length = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if pos + text_length > limit:
            raise PalocFormatError(f"text at 0x{pos:X} runs past the table{where}")
        text = data[pos: pos + text_length]
        pos += text_length
        try:
            entries.append(
                LocalizationEntry(
                    category=category,
                    key=key.decode("utf-8"),
                    text=text.decode("utf-8"),
                    reserved=reserved,
                )
            )
        except UnicodeDecodeError as exc:
            raise PalocFormatError(f"record {len(entries)} is not UTF-8{where}: {exc}") from exc
    if len(entries) != declared:
        raise PalocFormatError(
            f"the footer counts {declared:,} records but the table walks {len(entries):,}{where}"
        )
    return LocalizationTable(entries=tuple(entries), source_container=container)


def encode_paloc(table: LocalizationTable | Iterable[LocalizationEntry]) -> bytes:
    """Serialise a string table. Re-encoding an unedited parse reproduces the source."""

    entries: Sequence[LocalizationEntry] = (
        table.entries if isinstance(table, LocalizationTable) else tuple(table)
    )
    out = bytearray()
    for index, entry in enumerate(entries):
        key = entry.key.encode("utf-8")
        text = entry.text.encode("utf-8")
        for value, what in ((entry.category, "category"), (entry.reserved, "reserved")):
            if not 0 <= value <= 0xFFFFFFFF:
                raise PalocFormatError(f"record {index} {what} {value} does not fit a u32")
        out += struct.pack("<III", entry.category, entry.reserved, len(key))
        out += key
        out += struct.pack("<I", len(text))
        out += text
    out += struct.pack("<I", len(entries))
    payload = bytes(out)
    if isinstance(table, LocalizationTable) and table.source_container:
        original = _container_payload(table.source_container, "")
        if payload == original:
            return table.source_container
        if len(payload) > _MAX_CONTAINER_PAYLOAD:
            raise PalocFormatError("PALOC container uncompressed size is out of bounds")
        compressed = lz4_block.compress(payload, store_size=False)
        header = bytearray(table.source_container[:_CONTAINER_HEADER])
        struct.pack_into("<II", header, 9, len(compressed), len(payload))
        return bytes(header) + compressed
    return payload


def replace_text(
    table: LocalizationTable, replacements: Mapping[str, str]
) -> tuple[LocalizationTable, tuple[str, ...]]:
    """Return a table with the given keys retranslated, plus the keys that were absent.

    Lengths are free to change, so this is the whole of what a translation mod needs.
    """

    wanted = dict(replacements)
    seen: set[str] = set()
    entries = []
    for entry in table.entries:
        if entry.key in wanted:
            seen.add(entry.key)
            entries.append(
                LocalizationEntry(
                    category=entry.category,
                    key=entry.key,
                    text=wanted[entry.key],
                    reserved=entry.reserved,
                )
            )
        else:
            entries.append(entry)
    missing = tuple(sorted(set(wanted) - seen))
    return replace(table, entries=tuple(entries)), missing


def add_localization_entries(
    table: LocalizationTable, entries: Iterable[LocalizationEntry]
) -> LocalizationTable:
    """Return the table with new records added where the game keeps them.

    The shipped tables hold their numeric keys in strictly ascending order (129,386
    of them in the English table, not one descent, 2026-08-17), with the named keys
    interleaved; a numeric key is the u64 the game computes from a row (an item's name
    is `(key << 32) | 0x70`). A new numeric key therefore goes in front of the first
    larger numeric key, so a reader that searches the order still finds it; a named
    key, whose place in that order is not derivable, is appended. The order is taken
    from the table's leading ascending run, so records an earlier mod appended out of
    order at the end neither break the placement nor move.

    A key that already exists, or that repeats inside the batch, is refused rather than
    shadowed: the engine keeps the later duplicate, which would silently rename a
    shipped line.
    """

    additions = tuple(entries)
    existing = {entry.key for entry in table.entries}
    seen: set[str] = set()
    for entry in additions:
        if not entry.key:
            raise PalocFormatError("a localization key cannot be empty")
        if entry.key in existing:
            raise PalocFormatError(f"localization key {entry.key!r} already exists in the table")
        if entry.key in seen:
            raise PalocFormatError(f"localization key {entry.key!r} is repeated in the additions")
        seen.add(entry.key)
    if not additions:
        return table
    spine: list[tuple[int, int]] = []  # (numeric key, index) of the leading ascending run
    for index, entry in enumerate(table.entries):
        if entry.key.isdigit():
            value = int(entry.key)
            if spine and value <= spine[-1][0]:
                break
            spine.append((value, index))
    values = [value for value, _index in spine]
    ordered = sorted((entry for entry in additions if entry.key.isdigit()), key=lambda item: int(item.key), reverse=True)
    merged = list(table.entries)
    # largest first, at positions of the unedited table: each insertion lands at or
    # after every later one, so earlier positions stay valid, and equal positions
    # keep the smaller key in front.
    for entry in ordered:
        slot = bisect_right(values, int(entry.key))
        if slot < len(spine):
            at = spine[slot][1]
        else:
            at = spine[-1][1] + 1 if spine else len(table.entries)
        merged.insert(at, entry)
    named = tuple(entry for entry in additions if not entry.key.isdigit())
    return replace(table, entries=tuple(merged) + named)


def entries_like(
    table: LocalizationTable, template_key: str, texts: Mapping[str, str]
) -> tuple[LocalizationEntry, ...]:
    """New records for `texts` (new key -> text) shaped like the template's own record.

    The category and reserved word are copied from the template so a new item's name sits
    in the same category as the name it was cloned from; the file itself does not say what
    the categories mean, so copying is the only defensible choice.
    """

    template = table.index().get(template_key)
    if template is None:
        raise PalocFormatError(f"template key {template_key!r} is not in the table")
    return tuple(
        LocalizationEntry(category=template.category, key=key, text=text, reserved=template.reserved)
        for key, text in texts.items()
    )


def language_of_paloc_path(path: str) -> str:
    """`.../localizationstring_por-br.paloc` -> `por-br`; empty when the name has no suffix."""

    stem = path.replace("\\", "/").rsplit("/", 1)[-1]
    if not stem.lower().endswith(".paloc"):
        return ""
    stem = stem[: -len(".paloc")]
    return stem.rsplit("_", 1)[1] if "_" in stem else ""


def text_for_language(texts: Mapping[str, str], language: str, *, fallback: str = "eng") -> str:
    """The text for `language`, else the fallback language's; empty when neither is present."""

    value = texts.get(language)
    if value is not None and str(value).strip():
        return str(value)
    return str(texts.get(fallback, "") or "")


def describe_categories(table: LocalizationTable) -> Mapping[int, str]:
    """category -> the key prefix that dominates it, read off the table itself.

    The engine's own name for each category is not in the file, so this reports what
    the data shows rather than inventing a label: `38` comes back as `questdialog`
    because that is what its keys are called.
    """

    prefixes: dict[int, Counter] = {}
    for entry in table.entries:
        head = entry.key.split("_", 1)[0] if "_" in entry.key else ("(numeric)" if entry.key.isdigit() else entry.key)
        prefixes.setdefault(entry.category, Counter())[head] += 1
    return {
        category: counter.most_common(1)[0][0]
        for category, counter in sorted(prefixes.items())
    }


def rebuild_is_exact(data: bytes, *, name: str = "") -> bool:
    """Parse then re-encode, and say whether the bytes came back identical."""

    try:
        table = parse_paloc(data, name=name)
    except PalocFormatError:
        return False
    return encode_paloc(table) == data
