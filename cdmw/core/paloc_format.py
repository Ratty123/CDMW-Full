"""Reader and writer for the Crimson Desert `.paloc` string table.

`gamedata/stringtable/binary__/localizationstring_<lang>.paloc` holds every line of
text the game shows: quest dialogue, item names, UI labels, subtitles. There are 14 of
them, one per language, and each carries the same 187,521 entries.

The layout is a flat run of records with the count at the *end* of the file, which is
why a reader that looks for a header finds nothing and has to scan for the first
plausible record:

    repeat count times:
        u32 category          one of 38 values; groups entries by where they are used
        u32 reserved          zero in all 562,563 records across the three languages read
        u32 key_length;   key   UTF-8
        u32 text_length;  text  UTF-8, may be empty
    u32 count                 the footer

Nothing is offset-addressed and nothing is aligned, so a translated line may be any
length: rewriting the table is just re-emitting the records. That is what makes
`.paloc` the one game format where an edit cannot corrupt anything downstream.

Keys are identifiers rather than indices -- `questdialog_main_01262`,
`aidialogstringinfogroup_cheerup_36512` -- and about 30% of them are bare numbers.
Both forms are UTF-8 and both are preserved verbatim.
"""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence, Tuple

#: The count is a u32 footer, so a valid file is at least that.
_FOOTER = 4
_RECORD_HEAD = 12


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

    def __len__(self) -> int:
        return len(self.entries)

    def index(self) -> Mapping[str, LocalizationEntry]:
        """key -> entry. Later duplicates win, matching a sequential table load."""

        return {entry.key: entry for entry in self.entries}

    def categories(self) -> Mapping[int, int]:
        return dict(Counter(entry.category for entry in self.entries))


def parse_paloc(data: bytes, *, name: str = "") -> LocalizationTable:
    """Parse a `.paloc` string table.

    The footer count and the record walk have to agree on how many records there are,
    and the walk has to land exactly on the footer. Either check failing means this is
    not the format, rather than a table that happens to be short.
    """

    where = f" ({name})" if name else ""
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
    return LocalizationTable(entries=tuple(entries))


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
    return bytes(out)


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
    return LocalizationTable(entries=tuple(entries)), missing


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
