"""Append a barber hair option without changing existing customization slots."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat


_HAIR_SLOT_KEYS = frozenset({"Hair", "hairShape"})


class HairRegistrationError(ValueError):
    """The source does not support a proven, additive hair registration."""


@dataclass(frozen=True, slots=True)
class HairChoice:
    """One MeshSet of the hair slot, in table order; every set is kept so indexes stay the game's."""

    index: int
    #: Lower case, as archive paths are; the table itself may spell it in mixed case.
    prefab_stem: str
    #: "" when the game gives this hairstyle no barber icon.
    icon_path: str
    #: False for sets the game marks ShowInGame="False" (hairstyles the barber does not offer).
    shown_in_game: bool = True
    #: Why this set cannot be opened or used as a base; "" when it can.
    problem: str = ""

    @property
    def usable(self) -> bool:
        return not self.problem


@dataclass(frozen=True, slots=True)
class HairChoiceAppend:
    data: bytes
    choice: HairChoice
    insertion_offset: int
    inserted_bytes: bytes


_STEM = re.compile(r"[a-z][a-z0-9_]{0,126}")


def validate_hair_stem(stem: str) -> None:
    if not _STEM.fullmatch(stem):
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
    # Mounted game documents use Hair; older/modded catalogues use hairShape.
    # Keep the shared slot index and reject conflicting registrations.
    slots = [node for node in root if node.tag == "ParamDesc" and
             (node.get("Index") == "2" or node.get("UIKey") in _HAIR_SLOT_KEYS)]
    if len(slots) != 1 or slots[0].get("Index") != "2" or slots[0].get("UIKey") not in _HAIR_SLOT_KEYS:
        raise HairRegistrationError("The document must have exactly one hairstyle slot at Index 2.")
    return slots[0]


def read_hair_choices(data: bytes) -> tuple[HairChoice, ...]:
    """Every hairstyle of the slot. A set this tool cannot use is kept, with its reason."""
    slot = _hair_slot(data)
    result = []
    for node in slot:
        if node.tag != "MeshSet" or node.get("Index") != str(len(result)):
            raise HairRegistrationError(
                f"Hairstyle {len(result) + 1} in the barber list is out of order: "
                "its MeshSet indexes must be unique and contiguous from zero.")
        lists = [child for child in node if child.tag == "MeshList"]
        stem = lists[0].get("MeshFileName", "") if lists else ""
        problem = ""
        if len(node) != 1 or len(lists) != 1:
            problem = "This hairstyle is built from more than one mesh list, which Hair Tools cannot edit yet."
        elif not _STEM.fullmatch(stem.lower()):
            problem = "This hairstyle's mesh name is not a plain file name."
        # The game leaves the icon out of hairstyles its barber does not show.
        icon = lists[0].get("IconPath", "") if lists else ""
        result.append(HairChoice(len(result), stem.lower(), icon if _icon_ok(icon) else "",
                                 node.get("ShowInGame", "").strip().lower() != "false", problem))
    if not result:
        raise HairRegistrationError("The barber list has no hairstyles.")
    # The game's own tables carry no Default; one that is given must name a listed hairstyle.
    default = slot.get("Default")
    if default is not None and default not in {str(choice.index) for choice in result}:
        raise HairRegistrationError("The barber list's default hairstyle is not in the list.")
    return tuple(result)


def icon_donor_for(choices: tuple[HairChoice, ...], index: int) -> str:
    """The barber icon a copy of ``choices[index]`` shows: its own, else its player twin's, else the first."""
    donor = choices[index]
    if donor.icon_path:
        return donor.icon_path
    with_icon = [choice for choice in choices if choice.icon_path]
    twin = next((choice for choice in with_icon
                 if choice.prefab_stem in {donor.prefab_stem, donor.prefab_stem + "_player"}), None)
    if twin is None and not with_icon:
        raise HairRegistrationError("No hairstyle in the barber list has an icon to copy for the new one.")
    return (twin or with_icon[0]).icon_path


def _icon_ok(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return not (not path.lower().startswith("ui/texture/") or not path.lower().endswith(".dds") or
                any(part in {"", ".", ".."} for part in parts) or ":" in path or "\x00" in path)


def _validate_icon(path: str) -> None:
    if not _icon_ok(path):
        raise HairRegistrationError("The hair icon must be a contained ui/texture DDS path.")


def append_hair_choice(data: bytes, *, template_index: int, prefab_stem: str,
                       icon_path: str) -> HairChoiceAppend:
    """Insert a cloned MeshSet; every byte outside the insertion is retained."""
    choices = read_hair_choices(data)
    validate_hair_stem(prefab_stem)
    _validate_icon(icon_path)
    if isinstance(template_index, bool) or not isinstance(template_index, int) or not 0 <= template_index < len(choices):
        raise HairRegistrationError("The template hair choice does not exist.")
    if not choices[template_index].usable:
        raise HairRegistrationError(choices[template_index].problem)
    if any(choice.prefab_stem.casefold() == prefab_stem.casefold() for choice in choices):
        raise HairRegistrationError("That hair prefab is already selectable.")
    if len(choices) >= 255:
        raise HairRegistrationError("The hair option count exceeds the supported byte-index proof limit.")
    slot = _hair_slot(data)
    clone = copy.deepcopy(slot[template_index])
    clone.set("Index", str(len(choices)))
    clone[0].set("MeshFileName", prefab_stem)
    clone[0].set("IconPath", icon_path)
    # A copy of a hairstyle the barber hides must itself be offered.
    for name in [key for key in clone.attrib if key.lower() == "showingame"]:
        del clone.attrib[name]
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
        if (len(stack) == 2 and current == "ParamDesc"
                and attrs.get("Index") == slot.get("Index") and attrs.get("UIKey") == slot.get("UIKey")):
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
