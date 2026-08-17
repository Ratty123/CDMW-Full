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
from typing import Tuple

ICON_REGISTRY_PATH = "ui/xml/texture/cd_item_icon.xml"
_TEXTURE = re.compile(rb'<Texture\s+Name="([^"]*)"\s+Filename="([^"]*)"([^>]*)/>')


class IconRegistryError(ValueError):
    """Raised when the XML does not read as the icon registry, or an entry is refused."""


def registered_icon_names(data: bytes) -> Tuple[str, ...]:
    """Every `<Texture Name=...>` in the registry, in file order."""

    return tuple(match.group(1).decode("utf-8", "replace") for match in _TEXTURE.finditer(bytes(data)))


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
    for match in _TEXTURE.finditer(raw):
        existing = match.group(1).decode("utf-8", "replace")
        if existing.lower() == lower:
            raise IconRegistryError(f"icon {existing!r} is already registered")
        if existing.lower() == str(like or "").lower():
            template = match
    if template is None:
        raise IconRegistryError(f"the registry has no entry named {like!r} to shape the new one after")
    if not _TEXTURE.search(raw):
        raise IconRegistryError("the data holds no <Texture> elements; not the icon registry")
    target = str(filename or icon_filename_for(wanted))
    if any(ch in target for ch in '"<>&'):
        raise IconRegistryError("an icon filename holds no quotes or angle brackets")
    element = b'<Texture Name="' + wanted.encode("utf-8") + b'"' + b"\t" + b'Filename="' + target.encode("utf-8") + b'"' + template.group(3) + b"/>"
    newline = b"\r\n" if b"\r\n" in raw[:4096] else b"\n"
    body = raw.rstrip(b"\r\n")
    trailing = raw[len(body):] or newline
    return body + newline + element + trailing


__all__ = ["ICON_REGISTRY_PATH", "IconRegistryError", "add_icon_texture", "icon_filename_for", "registered_icon_names"]
