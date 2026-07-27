"""Text-preserving XML document.

The game's XML uses tabs, CRLF, a fixed attribute order, 6-decimal floats, an optional BOM,
and — in some files — stray trailing whitespace. No serializer round-trips that, so this
model never reserializes: it keeps the original text and applies edits as spliced
replacements. An unedited document returns its input bytes exactly.

Elements are addressed by an identity attribute (`Name` for sockets, `PartName` for
descriptor rows) and scoped to a container, because socket files reuse the `<Socket>` tag for
two different roles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

_ELEMENT = re.compile(r"<[A-Za-z_][\w.\-]*\s[^<>]*?/?>", re.DOTALL)
_ATTRIBUTE = re.compile(r'\b([A-Za-z_][\w.\-]*)="([^"]*)"')

_BOM = "﻿"


class XmlDocumentError(RuntimeError):
    """Raised when an edit cannot be applied to the document as written."""


@dataclass(frozen=True, slots=True)
class Element:
    """One opening tag, with its identity, attributes, and span in the source text."""

    identity: str
    attributes: Mapping[str, str]
    start: int
    end: int

    @property
    def text_length(self) -> int:
        return self.end - self.start

    def get(self, attribute: str, default: str = "") -> str:
        return self.attributes.get(attribute, default)

    def attribute_order(self) -> Tuple[str, ...]:
        return tuple(self.attributes)


class XmlDocument:
    """An XML file held as text, edited by splicing."""

    __slots__ = ("_text", "_encoding", "_had_bom", "_original")

    def __init__(self, text: str, *, encoding: str = "utf-8", had_bom: bool = False) -> None:
        self._text = text
        self._encoding = encoding
        self._had_bom = had_bom
        self._original = text

    # ── construction ────────────────────────────────────────────────

    @classmethod
    def from_bytes(cls, data: bytes) -> "XmlDocument":
        had_bom = data.startswith(b"\xef\xbb\xbf")
        payload = data[3:] if had_bom else data
        for encoding in ("utf-8", "cp1252"):
            try:
                return cls(payload.decode(encoding), encoding=encoding, had_bom=had_bom)
            except UnicodeDecodeError:
                continue
        raise XmlDocumentError("Could not decode as UTF-8 or cp1252")

    def to_bytes(self) -> bytes:
        prefix = b"\xef\xbb\xbf" if self._had_bom else b""
        return prefix + self._text.encode(self._encoding)

    # ── state ───────────────────────────────────────────────────────

    @property
    def text(self) -> str:
        return self._text

    @property
    def encoding(self) -> str:
        return self._encoding

    @property
    def has_bom(self) -> bool:
        return self._had_bom

    @property
    def modified(self) -> bool:
        return self._text != self._original

    def copy(self) -> "XmlDocument":
        return XmlDocument(self._text, encoding=self._encoding, had_bom=self._had_bom)

    # ── reading ─────────────────────────────────────────────────────

    def container_body(self, tag: str) -> Optional[Tuple[int, int]]:
        """Span between `<tag ...>` and `</tag>`, or None when absent."""

        opening = re.search(rf"<{re.escape(tag)}\b[^>]*?>", self._text)
        if opening is None:
            return None
        if opening.group(0).rstrip().endswith("/>"):
            return (opening.end(), opening.end())
        closing = self._text.find(f"</{tag}>", opening.end())
        if closing < 0:
            return None
        return (opening.end(), closing)

    def container_count(self, tag: str) -> Optional[int]:
        match = re.search(rf'<{re.escape(tag)}\b[^>]*?\bCount="(\d+)"', self._text)
        return int(match.group(1)) if match else None

    def elements(self, key_attribute: str, *, container: Optional[str] = None) -> List[Element]:
        """Ordered elements carrying `key_attribute`, optionally scoped to a container."""

        lower, upper = 0, len(self._text)
        if container:
            body = self.container_body(container)
            if body is None:
                return []
            lower, upper = body

        seen: set[str] = set()
        found: List[Element] = []
        for match in _ELEMENT.finditer(self._text):
            if match.start() < lower or match.end() > upper:
                continue
            attributes = dict(_ATTRIBUTE.findall(match.group(0)))
            identity = attributes.get(key_attribute)
            if identity is None or identity in seen:
                continue
            seen.add(identity)
            found.append(Element(identity, attributes, match.start(), match.end()))
        return found

    def element(
        self, key_attribute: str, identity: str, *, container: Optional[str] = None
    ) -> Optional[Element]:
        for item in self.elements(key_attribute, container=container):
            if item.identity == identity:
                return item
        return None

    def __iter__(self) -> Iterator[Element]:
        return iter(self.elements("Name"))

    # ── editing ─────────────────────────────────────────────────────

    def set_attribute(
        self,
        key_attribute: str,
        identity: str,
        attribute: str,
        value: str,
        *,
        container: Optional[str] = None,
    ) -> None:
        """Replace an existing attribute's value in place."""

        target = self.element(key_attribute, identity, container=container)
        if target is None:
            raise XmlDocumentError(f"No element {key_attribute}={identity!r}")
        if attribute not in target.attributes:
            raise XmlDocumentError(f"{identity!r} has no {attribute!r}")
        chunk = self._text[target.start : target.end]
        needle = f'{attribute}="{target.attributes[attribute]}"'
        replaced = chunk.replace(needle, f'{attribute}="{value}"', 1)
        self._text = self._text[: target.start] + replaced + self._text[target.end :]

    def add_attribute(
        self,
        key_attribute: str,
        identity: str,
        attribute: str,
        value: str,
        *,
        after: str = "",
        container: Optional[str] = None,
    ) -> None:
        """Insert an attribute the file omits, after a named sibling attribute."""

        target = self.element(key_attribute, identity, container=container)
        if target is None:
            raise XmlDocumentError(f"No element {key_attribute}={identity!r}")
        if attribute in target.attributes:
            raise XmlDocumentError(f"{identity!r} already has {attribute!r}")
        chunk = self._text[target.start : target.end]
        addition = f' {attribute}="{value}"'
        anchor = re.search(rf'\b{re.escape(after)}="[^"]*"', chunk) if after else None
        if anchor is not None:
            updated = chunk[: anchor.end()] + addition + chunk[anchor.end() :]
        else:
            tail = re.search(r"\s*/?>$", chunk)
            cut = tail.start() if tail else len(chunk)
            updated = chunk[:cut] + addition + chunk[cut:]
        self._text = self._text[: target.start] + updated + self._text[target.end :]

    def add_element(
        self,
        key_attribute: str,
        raw: str,
        *,
        after: str = "",
        container: Optional[str] = None,
        bump_count: bool = True,
    ) -> None:
        """Insert a new element. `raw` supplies its own leading separator and indentation."""

        insert_at: Optional[int] = None
        if after:
            anchor = self.element(key_attribute, after, container=container)
            if anchor is not None:
                insert_at = anchor.end
        if insert_at is None:
            body = self.container_body(container) if container else None
            if body is None:
                raise XmlDocumentError("No insertion anchor available")
            insert_at = body[1]
        self._text = self._text[:insert_at] + raw + self._text[insert_at:]
        if bump_count and container:
            self.adjust_count(container, 1)

    def adjust_count(self, tag: str, delta: int) -> None:
        """Keep a container's declared `Count` in step with its contents."""

        match = re.search(rf'(<{re.escape(tag)}\b[^>]*?\bCount=")(\d+)(")', self._text)
        if match is None:
            return
        updated = max(0, int(match.group(2)) + delta)
        self._text = (
            self._text[: match.start()]
            + f"{match.group(1)}{updated}{match.group(3)}"
            + self._text[match.end() :]
        )

    def separator_before(
        self, key_attribute: str, identity: str, *, container: Optional[str] = None
    ) -> str:
        """The whitespace that precedes an element, for building matching insertions."""

        target = self.element(key_attribute, identity, container=container)
        if target is None:
            return ""
        line_start = self._text.rfind("\n", 0, target.start)
        if line_start < 0:
            return ""
        start = line_start - 1 if line_start > 0 and self._text[line_start - 1] == "\r" else line_start
        return self._text[start : target.start]


def round_trips(data: bytes) -> bool:
    """True when parsing and re-emitting returns the input unchanged."""

    try:
        return XmlDocument.from_bytes(data).to_bytes() == data
    except XmlDocumentError:
        return False
