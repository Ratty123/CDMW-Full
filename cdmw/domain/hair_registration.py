"""Append a barber hair option without changing existing customization slots."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat


class HairRegistrationError(ValueError):
    """The source does not support a proven, additive hair registration."""


@dataclass(frozen=True, slots=True)
class HairChoice:
    index: int
    prefab_stem: str
    icon_path: str


@dataclass(frozen=True, slots=True)
class HairChoiceAppend:
    data: bytes
    choice: HairChoice
    insertion_offset: int
    inserted_bytes: bytes


def validate_hair_stem(stem: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,126}", stem):
        raise HairRegistrationError("Hair prefab names must be lowercase ASCII file stems (at most 127 characters).")


def _hair_slot(data: bytes) -> ET.Element:
    if not data or len(data) > 2 * 1024 * 1024:
        raise HairRegistrationError("The hair option document is empty or exceeds 2 MiB.")
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", data, re.I) or b"\x00" in data:
        raise HairRegistrationError("Hair option documents must be UTF-8 XML without DTDs or entities.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise HairRegistrationError(f"Invalid hair option XML: {exc}") from exc
    if root.tag != "MeshParam":
        raise HairRegistrationError("Expected a MeshParam customization document.")
    slots = [node for node in root if node.tag == "ParamDesc" and
             (node.get("Index") == "2" or node.get("UIKey") == "hairShape")]
    if len(slots) != 1 or slots[0].get("Index") != "2" or slots[0].get("UIKey") != "hairShape":
        raise HairRegistrationError("The document must have exactly one hairShape slot at Index 2.")
    return slots[0]


def read_hair_choices(data: bytes) -> tuple[HairChoice, ...]:
    slot = _hair_slot(data)
    result = []
    for node in slot:
        if node.tag != "MeshSet" or node.get("Index") != str(len(result)):
            raise HairRegistrationError("Hair MeshSet indexes must be unique and contiguous from zero.")
        if len(node) != 1 or node[0].tag != "MeshList":
            raise HairRegistrationError("The registration proof supports one MeshList per hairstyle.")
        stem = node[0].get("MeshFileName", "")
        validate_hair_stem(stem)
        icon = node[0].get("IconPath", "")
        _validate_icon(icon)
        result.append(HairChoice(len(result), stem, icon))
    if not result or slot.get("Default") not in {str(choice.index) for choice in result}:
        raise HairRegistrationError("The hair slot must contain a valid default choice.")
    return tuple(result)


def _validate_icon(path: str) -> None:
    parts = path.replace("\\", "/").split("/")
    if (not path.lower().startswith("ui/texture/") or not path.lower().endswith(".dds") or
            any(part in {"", ".", ".."} for part in parts) or ":" in path or "\x00" in path):
        raise HairRegistrationError("The hair icon must be a contained ui/texture DDS path.")


def append_hair_choice(data: bytes, *, template_index: int, prefab_stem: str,
                       icon_path: str) -> HairChoiceAppend:
    """Insert a cloned MeshSet; every byte outside the insertion is retained."""
    choices = read_hair_choices(data)
    validate_hair_stem(prefab_stem)
    _validate_icon(icon_path)
    if isinstance(template_index, bool) or not isinstance(template_index, int) or not 0 <= template_index < len(choices):
        raise HairRegistrationError("The template hair choice does not exist.")
    if any(choice.prefab_stem.casefold() == prefab_stem.casefold() for choice in choices):
        raise HairRegistrationError("That hair prefab is already selectable.")
    if len(choices) >= 255:
        raise HairRegistrationError("The hair option count exceeds the supported byte-index proof limit.")
    slot = _hair_slot(data)
    clone = copy.deepcopy(slot[template_index])
    clone.set("Index", str(len(choices)))
    clone[0].set("MeshFileName", prefab_stem)
    clone[0].set("IconPath", icon_path)
    clone.tail = "\n\t"
    # Expat supplies byte offsets, preserving BOM, comments, whitespace and every
    # unrelated slot. Searching text for </ParamDesc> would also match comments.
    parser = expat.ParserCreate()
    stack = []
    offsets = []

    def start(tag, attrs):
        stack.append((tag, attrs))

    def end(tag):
        current, attrs = stack[-1]
        if len(stack) == 2 and current == "ParamDesc" and attrs.get("UIKey") == "hairShape":
            offsets.append(parser.CurrentByteIndex)
        stack.pop()

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(data, True)
    if len(offsets) != 1 or not data[offsets[0]:].startswith(b"</ParamDesc"):
        raise HairRegistrationError("Could not determine the hair slot insertion boundary.")
    offset = offsets[0]
    insertion = ET.tostring(clone, encoding="utf-8")
    result = data[:offset] + insertion + data[offset:]
    checked = read_hair_choices(result)
    if checked[:-1] != choices:
        raise HairRegistrationError("Appending a hairstyle changed an existing choice.")
    return HairChoiceAppend(result, checked[-1], offset, insertion)
