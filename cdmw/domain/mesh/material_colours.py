"""Per-part edits of the colours a PAC material already declares.

A part's armour colour mostly comes from ``_tintColorR/G/B`` and related colour
rows in its ``.pac_xml`` wrapper, applied through the wrapper's colour mask, not
from a base colour texture. An edit names existing ``MaterialParameterColor``
rows and the colour each should have; the row's alpha byte, which the game
reads as the colour's strength, is always kept.
"""

from __future__ import annotations

import re

MAX_MATERIAL_COLOURS = 32
_NAME = re.compile(r"_?[A-Za-z][A-Za-z0-9_]{0,63}")
_HEX = re.compile(r"#([0-9A-Fa-f]{6})")

#: Colour rows other editors own: Glow writes the emissive colours and Hair Tools the hair dye.
OWNED_ELSEWHERE_PREFIXES = ("_emissive", "emissive", "_glow", "glow", "_hairDyeing", "hairDyeing")


def owned_elsewhere(name: str) -> bool:
    return str(name).startswith(OWNED_ELSEWHERE_PREFIXES)


def normalize_material_colours(value) -> tuple[tuple[str, str], ...]:
    """A validated, name-sorted ``((parameter, "#RRGGBB"), ...)`` from a mapping or pairs."""

    if isinstance(value, dict):
        items = list(value.items())
    elif isinstance(value, (list, tuple)):
        items = [tuple(item) for item in value]
    else:
        raise ValueError("Material colours must map colour rows to #RRGGBB values.")
    if not items:
        raise ValueError("Choose at least one material colour, or restore the original colours.")
    if len(items) > MAX_MATERIAL_COLOURS:
        raise ValueError(f"A part can change at most {MAX_MATERIAL_COLOURS} material colours.")
    result = {}
    for item in items:
        if len(item) != 2:
            raise ValueError("Material colours must map colour rows to #RRGGBB values.")
        name, colour = item
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("Material colour rows are named by their parameter, such as _tintColorR.")
        if owned_elsewhere(name):
            raise ValueError(f"{name} is set by Glow or Hair Tools, not by Material colours.")
        if not isinstance(colour, str) or not _HEX.fullmatch(colour):
            raise ValueError(f"{name}: enter the colour as #RRGGBB.")
        if name.casefold() in {key.casefold() for key in result}:
            raise ValueError(f"{name} is listed twice.")
        result[name] = "#" + colour[1:].upper()
    return tuple(sorted(result.items(), key=lambda pair: pair[0].casefold()))


def colours_to_dict(colours) -> dict[str, str]:
    return {name: colour for name, colour in colours}


#: Readable names for the rows most armour uses, in display order. The Mesh
#: Editor translates these; any other colour row shows its parameter name.
MATERIAL_COLOUR_LABELS = {
    "_tintColorR": "Tint (red mask)",
    "_tintColorG": "Tint (green mask)",
    "_tintColorB": "Tint (blue mask)",
    "_scratchTintColorR": "Wear tint (red mask)",
    "_scratchTintColorG": "Wear tint (green mask)",
    "_scratchTintColorB": "Wear tint (blue mask)",
    "_dyeingDetailLayerColorMaskR": "Detail dye (red mask)",
    "_dyeingDetailLayerColorMaskG": "Detail dye (green mask)",
    "_dyeingDetailLayerColorMaskB": "Detail dye (blue mask)",
    "_dyeingColorMaskR": "Dye (red mask)",
    "_dyeingColorMaskG": "Dye (green mask)",
    "_dyeingColorMaskB": "Dye (blue mask)",
}
_KNOWN_ORDER = {name.casefold(): position for position, name in enumerate(MATERIAL_COLOUR_LABELS)}
_KNOWN_LABELS = {name.casefold(): label for name, label in MATERIAL_COLOUR_LABELS.items()}


def material_colour_label(name: str) -> str:
    return _KNOWN_LABELS.get(name.casefold(), name)


def material_colour_order(name: str) -> tuple[int, str]:
    """Known rows first, in their usual order, then the others by name."""

    return _KNOWN_ORDER.get(name.casefold(), len(_KNOWN_ORDER)), name.casefold()
