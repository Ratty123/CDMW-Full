"""`ui/xml/texture/cd_item_icon.xml`: the UI's icon registry, and how to add an icon to it.

An ItemInfo row names its icon as `hashlittle("ItemIcon_Prefab_<Stem>", 0xC5EDE)`; the
UI turns that string into a file through this XML, one `<Texture .../>` element per
icon (9,580 in the shipped file, LZ4 + ChaCha20 in package 0012):

    <Texture Name="ItemIcon_Prefab_cd_phm_01_sword_0109"\tFilename="UI/texture/icon/ItemIcon_Prefab_cd_phm_01_sword_0109.dds" Type="Image" GetRect="0,0,256,256"/>

A generated icon whose file was in the archive and registered in `meta/0.pathc` but
missing here still drew as the placeholder bag (seen in game 2026-08-18); the file is
found by name, so the name has to be declared. Names are compared case-insensitively
by the game (`ItemIcon_Prefab_CD_PHM_01_Sword_0109` in StringInfo,
`ItemIcon_Prefab_cd_phm_01_sword_0109` here), and the `Filename` casing is the
registry's own convention rather than the archive path's, which is lower case.

The file is a flat run of elements with no root, a UTF-8 BOM and CRLF line ends;
adding an icon is appending one element shaped like an existing one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple
from xml.parsers import expat

ICON_REGISTRY_PATH = "ui/xml/texture/cd_item_icon.xml"
_ATTRIBUTE = re.compile(rb'''\s+([^\s=]+)\s*=\s*(["'])(.*?)\2''', re.DOTALL)
_EMPTY_TEXTURE = re.compile(rb'''<Texture(?:\s+[^\s=]+\s*=\s*(?:"[^"]*"|'[^']*'))*\s*/>''')


class IconRegistryError(ValueError):
    """Raised when the XML does not read as the icon registry, or an entry is refused."""


@dataclass(frozen=True)
class IconTexture:
    name: str
    filename: str
    raw: bytes


@dataclass(frozen=True)
class IconRegistry:
    textures: Tuple[IconTexture, ...]
    remainder: bytes


def parse_icon_registry(data: bytes) -> IconRegistry:
    """Validate flat UTF-8 XML, retaining exact entries and opaque surrounding data.

    Names are unique ignoring case. Comments, processing instructions and unknown
    elements remain opaque; nested or nonempty Texture elements are unsupported.
    A synthetic root is used only for parsing and is never written to the file.
    """
    raw = bytes(data)
    bom_size = 3 if raw.startswith(b'\xef\xbb\xbf') else 0
    prefix = b'<CDMWIconRegistry>'
    parser = expat.ParserCreate('utf-8')
    depth, active = 0, None
    textures, spans, names = [], [], set()

    def start(tag, attributes):
        nonlocal depth, active
        if tag == 'Texture':
            if depth != 1:
                raise IconRegistryError('nested Texture elements are unsupported')
            name, filename = attributes.get('Name', ''), attributes.get('Filename', '')
            if not name.strip() or not filename.strip():
                raise IconRegistryError('each Texture needs a nonempty Name and Filename')
            if name.lower() in names:
                raise IconRegistryError(f'duplicate icon name {name!r} (case-insensitive)')
            names.add(name.lower())
            active = (parser.CurrentByteIndex - len(prefix) + bom_size, name, filename)
        depth += 1

    def end(tag):
        nonlocal depth, active
        depth -= 1
        if tag == 'Texture' and depth == 1:
            begin, name, filename = active
            finish = parser.CurrentByteIndex - len(prefix) + bom_size
            element = raw[begin:finish]
            if _EMPTY_TEXTURE.fullmatch(element) is None:
                raise IconRegistryError('Texture elements must be self-closing')
            textures.append(IconTexture(name, filename, element))
            spans.append((begin, finish))
            active = None

    parser.StartElementHandler, parser.EndElementHandler = start, end
    try:
        parser.Parse(prefix + raw[bom_size:] + b'</CDMWIconRegistry>', True)
    except expat.ExpatError as exc:
        raise IconRegistryError(f'invalid flat icon registry XML: {exc}') from exc
    if not textures:
        raise IconRegistryError('the data holds no <Texture> elements; not the icon registry')
    remainder, pos = [], 0
    for begin, finish in spans:
        remainder.append(raw[pos:begin])
        pos = finish
    remainder.append(raw[pos:])
    return IconRegistry(tuple(textures), b''.join(remainder).strip(b'\r\n\t '))


def registered_icon_names(data: bytes) -> Tuple[str, ...]:
    """Every `<Texture Name=...>` in the registry, in file order."""

    return tuple(texture.name for texture in parse_icon_registry(data).textures)


def icon_filename_for(name: str) -> str:
    """The registry's own spelling of an icon's file: `UI/texture/icon/<Name>.dds`."""

    return f"UI/texture/icon/{name}.dds"


def add_icon_texture(data: bytes, name: str, *, like: str, filename: str = "") -> bytes:
    """The registry with one more `<Texture>` shaped like the entry named `like`.

    `filename` defaults to :func:`icon_filename_for`. A name already present (in any
    case) is refused rather than shadowed.
    """

    raw = bytes(data)
    wanted = str(name or "").strip()
    if not wanted or any(ch in wanted for ch in '"<>&'):
        raise IconRegistryError("an icon name is a plain identifier")
    lower = wanted.lower()
    template = None
    for texture in parse_icon_registry(raw).textures:
        existing = texture.name
        if existing.lower() == lower:
            raise IconRegistryError(f"icon {existing!r} is already registered")
        if existing.lower() == str(like or "").lower():
            template = texture
    if template is None:
        raise IconRegistryError(f"the registry has no entry named {like!r} to shape the new one after")
    target = str(filename or icon_filename_for(wanted))
    if any(ch in target for ch in '"<>&'):
        raise IconRegistryError("an icon filename holds no quotes or angle brackets")
    attributes = b''.join(match.group(0) for match in _ATTRIBUTE.finditer(template.raw)
                          if match.group(1) not in (b'Name', b'Filename'))
    element = b'<Texture Name="' + wanted.encode("utf-8") + b'"' + b"\t" + b'Filename="' + target.encode("utf-8") + b'"' + attributes + b"/>"
    newline = b"\r\n" if b"\r\n" in raw[:4096] else b"\n"
    body = raw.rstrip(b"\r\n")
    trailing = raw[len(body):] or newline
    return body + newline + element + trailing


__all__ = ["ICON_REGISTRY_PATH", "IconRegistry", "IconTexture", "IconRegistryError",
           "add_icon_texture", "icon_filename_for", "parse_icon_registry", "registered_icon_names"]
