"""Exact resource attributes in the supported model-property XML fragments.

This owner inventories unqualified ResourceReferencePath fields. Only admitted
ITexture _path values can be rewritten; comments, ordinary strings, unrelated
attributes and the surrounding byte format are retained verbatim.
"""
from dataclasses import dataclass
from typing import Callable, Mapping
from xml.parsers import expat
from xml.sax.saxutils import escape


_ROOTS = frozenset({"SkinnedMeshPropertyCommon", "ModelPropertyList"})
_PREFIX = b"<IndependentModel>"
_SUFFIX = b"</IndependentModel>"
_SPACE = b" \t\r\n"


class PacXmlReferenceError(ValueError):
    """A model-property fragment has an unverified resource boundary."""


@dataclass(frozen=True, slots=True)
class PacXmlResourceReference:
    tag: str
    path: str
    value_start: int
    value_end: int
    quote: str


@dataclass(frozen=True, slots=True)
class PacXmlReferences:
    data: bytes
    references: tuple[PacXmlResourceReference, ...]

    def rewrite_textures(self, replacements: Mapping[str, str], *, check: Callable[[], None] | None = None) -> bytes:
        """Replace complete normalized ITexture paths in one simultaneous pass."""
        normalized = {}
        for old, new in replacements.items():
            key = old.replace("\\", "/").lower()
            if key in normalized and normalized[key] != new:
                raise PacXmlReferenceError("Ambiguous model texture replacement paths.")
            normalized[key] = new
        pieces, previous = [], 0
        for resource in self.references:
            if check is not None:
                check()
            if resource.tag != "ResourceReferencePath_ITexture":
                continue
            target = normalized.get(resource.path.replace("\\", "/").lower())
            if target is None or target == resource.path:
                continue
            escaped = escape(target, {resource.quote: "&quot;" if resource.quote == '"' else "&apos;"})
            pieces.extend((self.data[previous:resource.value_start], escaped.encode("utf-8")))
            previous = resource.value_end
        if not pieces:
            return self.data
        pieces.append(self.data[previous:])
        return b"".join(pieces)


def _path_span(data: bytes, start: int) -> tuple[int, int, str]:
    """Locate an attribute in an Expat-validated start tag, outside other values."""
    at = start + 1
    while data[at] not in _SPACE + b"/>":
        at += 1
    while True:
        while data[at] in _SPACE:
            at += 1
        if data[at] in b"/>":
            raise PacXmlReferenceError("Cannot locate the model resource path attribute.")
        equal = data.index(b"=", at)
        name = data[at:equal].strip()
        at = equal + 1
        while data[at] in _SPACE:
            at += 1
        quote = data[at:at + 1]
        value_start = at + 1
        value_end = data.index(quote, value_start)
        if name == b"_path":
            return value_start, value_end, quote.decode("ascii")
        at = value_end + 1


def parse_pac_xml_references(data: bytes, *, check: Callable[[], None] | None = None) -> PacXmlReferences:
    """Validate UTF-8 fragments and retain exact byte spans for their references.

    The roots and allowed unqualified attributes match the independent-item audit.
    Chunked parsing permits cancellation without constructing an XML tree or a
    second complete wrapped payload. Namespace-qualified or other resource types
    do not gain a private-copy adapter. No engine lookup or lifetime is inferred.
    """
    data = bytes(data)
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise PacXmlReferenceError("XML entities are unsupported.")
    offset = 0
    while data.startswith(b"\xef\xbb\xbf", offset):
        offset += 3
    parser = expat.ParserCreate("UTF-8", namespace_separator="}")
    depth, roots = 0, 0
    references = []

    def start(tag, attributes):
        nonlocal depth, roots
        if check is not None:
            check()
        if depth == 1:
            if tag not in _ROOTS:
                raise PacXmlReferenceError("Unknown model property root.")
            roots += 1
        depth += 1
        if not tag.startswith("ResourceReferencePath"):
            return
        if set(attributes) - {"Name", "_path"}:
            raise PacXmlReferenceError("Unknown model resource boundary.")
        if "_path" in attributes:
            at = parser.CurrentByteIndex - len(_PREFIX) + offset
            begin, end, quote = _path_span(data, at)
            references.append(PacXmlResourceReference(tag, attributes["_path"], begin, end, quote))

    def end(_tag):
        nonlocal depth
        depth -= 1

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(_PREFIX, False)
        for begin in range(offset, len(data), 65536):
            if check is not None:
                check()
            parser.Parse(data[begin:begin + 65536], False)
        parser.Parse(_SUFFIX, True)
    except expat.ExpatError as exc:
        raise PacXmlReferenceError(f"Unverified model property XML: {exc}") from exc
    if not roots:
        raise PacXmlReferenceError("Unknown model property root.")
    return PacXmlReferences(data, tuple(references))
