"""`character/descriptors/boneoffset/boneoffsetsample.xml`: per-prefab bone offsets.

While a prefab named by a `BoneOffsetByPrefab/BoneDesc PrefabName=` entry is worn, the
game moves, turns and scales the listed bones of the wearer's skeleton, so every worn
mesh follows (observed in game 2026-11-01). Shipped entries are compatibility fits of
one outfit to one character.

The file closes elements with `</>`, so it is not XML that expat accepts. This reader
handles the subset the shipped file uses: elements, attributes in quotes, comments and
character data. Everything outside the edited entries stays byte-identical.
native/cdmw_item_composer/src/bone_offset_table.cpp mirrors it for composition.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re

BONE_OFFSET_PATH = "character/descriptors/boneoffset/boneoffsetsample.xml"
_SECTION = b"BoneOffsetByPrefab"
_ENTRY = b"BoneDesc"
_NAME = re.compile(rb"[A-Za-z_:][A-Za-z0-9_:.\-]*")
_PREFAB_NAME = re.compile(r"[A-Za-z0-9_]+\Z")


class BoneOffsetTableError(ValueError):
    pass


@dataclass(frozen=True)
class BoneOffsetEntry:
    key: bytes  # PrefabName in ASCII lower case
    name: str
    start: int  # the owned span: whole lines when the entry has its own
    end: int
    element_start: int
    element_end: int


@dataclass(frozen=True)
class BoneOffsetTable:
    data: bytes
    entries: tuple[BoneOffsetEntry, ...]
    insert: int  # where new entries go: the line of the section's closing tag

    def frame(self) -> bytes:
        """The file without its prefab entries."""
        out, cursor = [], 0
        for entry in self.entries:
            out.append(self.data[cursor:entry.start])
            cursor = entry.end
        out.append(self.data[cursor:])
        return b"".join(out)

    def raw(self, entry: BoneOffsetEntry) -> bytes:
        return self.data[entry.start:entry.end]


def _fail(reason):
    raise BoneOffsetTableError(f"Unsupported bone offset table: {reason}.")


def _line_span(data, start, end):
    head = data.rfind(b"\n", 0, start) + 1
    if data[head:start].strip(b" \t"):
        return start, end
    tail = end
    while tail < len(data) and data[tail] in b" \t":
        tail += 1
    if data.startswith(b"\r\n", tail):
        return head, tail + 2
    if data.startswith(b"\n", tail):
        return head, tail + 1
    return start, end


def parse_bone_offset_table(data: bytes) -> BoneOffsetTable:
    data = bytes(data)
    if len(data) > 4 * 1024 * 1024:
        _fail("larger than 4 MiB")
    at = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    try:
        data[at:].decode("utf-8")
    except UnicodeDecodeError:
        _fail("not UTF-8")
    stack = []  # (name, start, attributes)
    sections, entries = [], []
    while at < len(data):
        if data[at] != 0x3C:  # '<'
            found = data.find(b"<", at)
            at = len(data) if found < 0 else found
            continue
        if data.startswith(b"<!--", at):
            found = data.find(b"-->", at + 4)
            if found < 0:
                _fail("an unterminated comment")
            at = found + 3
            continue
        if data.startswith(b"<!", at) or data.startswith(b"<?", at):
            _fail("declarations and processing instructions")
        if data.startswith(b"</", at):
            closer = at
            match = _NAME.match(data, at + 2)
            close = match.end() if match else at + 2
            while close < len(data) and data[close] in b" \t\r\n":
                close += 1
            if close >= len(data) or data[close] != 0x3E:
                _fail("an end tag that does not close")
            if not stack:
                _fail("an end tag without an element")
            name, start, attributes = stack.pop()
            if match and match.group() != name:
                _fail("mismatched end tag")
            at = close + 1
            if not stack and name == _SECTION:
                head = data.rfind(b"\n", 0, closer) + 1
                sections.append(head if not data[head:closer].strip(b" \t") else closer)
            elif len(stack) == 1 and stack[0][0] == _SECTION and name == _ENTRY:
                entries.append((start, at, attributes))
            continue
        match = _NAME.match(data, at + 1)
        if match is None:
            _fail("a tag without a name")
        name, start, at = match.group(), at, match.end()
        attributes = {}
        while True:
            spaced = at
            while at < len(data) and data[at] in b" \t\r\n":
                at += 1
            if at >= len(data):
                _fail("the file ends inside a tag")
            if data.startswith(b"/>", at):
                at += 2
                closed = True
                break
            if data[at] == 0x3E:
                at += 1
                closed = False
                break
            key = _NAME.match(data, at)
            if key is None or spaced == at:
                _fail("a malformed attribute")
            at = key.end()
            while at < len(data) and data[at] in b" \t\r\n":
                at += 1
            if at >= len(data) or data[at] != 0x3D:
                _fail("an attribute without a value")
            at += 1
            while at < len(data) and data[at] in b" \t\r\n":
                at += 1
            if at >= len(data) or data[at] not in b"\"'":
                _fail("an unquoted attribute value")
            end = data.find(data[at:at + 1], at + 1)
            if end < 0 or b"<" in data[at + 1:end]:
                _fail("an unterminated attribute value")
            if key.group() in attributes:
                _fail("a repeated attribute")
            attributes[key.group()] = data[at + 1:end]
            at = end + 1
        if closed:
            if not stack and name == _SECTION:
                _fail("an empty section without a closing tag")
            if len(stack) == 1 and stack[0][0] == _SECTION and name == _ENTRY:
                entries.append((start, at, attributes))
        else:
            stack.append((name, start, attributes))
    if stack:
        _fail("an unclosed element")
    if len(sections) != 1:
        _fail(f"expected one {_SECTION.decode()} section, found {len(sections)}")
    result = []
    for start, end, attributes in entries:
        name = attributes.get(b"PrefabName", b"")
        if not name.strip():
            _fail("a prefab entry without PrefabName")
        line_start, line_end = _line_span(data, start, end)
        result.append(BoneOffsetEntry(name.lower(), name.decode("utf-8"), line_start, line_end, start, end))
    return BoneOffsetTable(data, tuple(result), sections[0])


def prefab_entry_names(data: bytes) -> frozenset[str]:
    """PrefabName of every entry, in lower case."""
    return frozenset(entry.key.decode("utf-8") for entry in parse_bone_offset_table(data).entries)


def clone_prefab_entries(data: bytes, copies: Mapping[str, str] | Iterable[tuple[str, str]]) -> bytes:
    """Copy each source prefab's entry under its new prefab name, before the section closes.

    `copies` holds (source, target) pairs; one source may have several targets.
    Sources without an entry are skipped. A target that already has the same entry
    (a rebuild on an earlier export) is kept; any other existing target is refused.
    """
    table = parse_bone_offset_table(data)
    by_key = {}
    for entry in table.entries:
        by_key.setdefault(entry.key, []).append(entry)
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    added = []
    for source, target in (copies.items() if isinstance(copies, Mapping) else copies):
        found = by_key.get(source.lower().encode("utf-8"), [])
        if not found:
            continue
        if len(found) > 1:
            raise BoneOffsetTableError(f"The bone offset table has {len(found)} entries for {source}.")
        if not _PREFAB_NAME.match(target):
            raise BoneOffsetTableError(f"Invalid prefab name for a bone offset entry: {target!r}")
        entry = found[0]
        element = data[entry.element_start:entry.element_end]
        opening = re.compile(rb'(\sPrefabName\s*=\s*)(["\'])(.*?)\2', re.S).search(element, 0, element.index(b">") + 1)
        clone = element[:opening.start(3)] + target.encode("utf-8") + element[opening.end(3):]
        head = data.rfind(b"\n", 0, entry.element_start) + 1
        indent = data[head:entry.element_start] if entry.start == head else b"\t"
        existing = by_key.get(target.lower().encode("utf-8"), [])
        if existing:
            if [data[e.element_start:e.element_end] for e in existing] == [clone]:
                continue
            raise BoneOffsetTableError(f"The bone offset table already has a different entry for {target}.")
        added.append(indent + clone + newline)
    if not added:
        return data
    result = data[:table.insert] + b"".join(added) + data[table.insert:]
    parse_bone_offset_table(result)
    return result
