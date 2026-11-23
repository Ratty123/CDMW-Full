"""Read and rewrite the colour rows a PAC material wrapper already declares.

Only existing ``MaterialParameterColor`` rows change, and only their RGB: the
alpha byte, the row's ItemID, Index and every other byte of the file stay as
they were. Model variants (``<ModelProperty>`` blocks) repeat part names, so
each variant is edited on its own; an edit applies to every variant whose
wrapper for that part has the row.
"""

from __future__ import annotations

import re

from cdmw.core.material_shader_controls import edit_material_variants, material_variant_fragments
from cdmw.core.pac_xml_standard_material import find_material_wrappers, wrapper_key

_COLOUR_VALUE = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?")


def _row_pattern(name: str) -> re.Pattern[str]:
    return re.compile(
        r'(<MaterialParameterColor\b(?=[^>]*\b(?:StringItemID|_name)="' + re.escape(name) + r'")[^>]*?\b_value=")'
        r'(#[0-9A-Fa-f]{6})([0-9A-Fa-f]{2})?(")')


def wrapper_colours(text: str) -> tuple[dict[str, dict[str, str]], ...]:
    """Per model variant (file order): {folded part name: {row name: "#RRGGBBAA" as written}}."""

    variants = []
    for fragment in material_variant_fragments(text):
        rows: dict[str, dict[str, str]] = {}
        for wrapper in find_material_wrappers(fragment):
            key = wrapper_key(wrapper.submesh_name)
            if key in rows:
                raise ValueError(f"Ambiguous material binding: {wrapper.submesh_name}")
            rows[key] = {parameter.name: parameter.value for parameter in wrapper.parameters
                         if parameter.kind == "Color" and _COLOUR_VALUE.fullmatch(parameter.value)}
        variants.append(rows)
    return tuple(variants)


def _rewrite_block(block: str, colours: dict[str, str]) -> tuple[str, set[str]]:
    found = set()
    for name, colour in colours.items():
        pattern = _row_pattern(name)
        matches = list(pattern.finditer(block))
        if not matches:
            continue
        if len(matches) > 1:
            raise ValueError(f"Ambiguous duplicate material parameter: {name}")
        match = matches[0]
        old = match.group(2)
        # Keep the file's own letter case so an unchanged digit stays byte-identical.
        new = colour.lower() if old[1:] == old[1:].lower() else colour.upper()
        block = block[:match.start(2)] + "#" + new[1:] + block[match.end(2):]
        found.add(name)
    return block, found


def rewrite_material_colours(text: str, choices) -> str:
    """Return ``text`` with each part's chosen colours written into its wrapper.

    ``choices`` maps a part (material binding) name to ``{row name: "#RRGGBB"}``.
    Every named row must exist in at least one variant of that part's wrapper;
    no row is ever added.
    """

    if len(text) > 16 * 1024 * 1024:
        raise ValueError("Material sidecar exceeds the supported size limit.")
    settings = {}
    for name, colours in dict(choices).items():
        key = wrapper_key(name)
        if key in settings:
            raise ValueError(f"Material colours name the part {name} twice.")
        settings[key] = dict(colours)
    if not settings:
        return text
    written: dict[str, set[str]] = {key: set() for key in settings}
    wrapped: set[str] = set()

    def edit(fragment):
        wrappers = find_material_wrappers(fragment)
        seen = set()
        edits = []
        for wrapper in wrappers:
            key = wrapper_key(wrapper.submesh_name)
            if key not in settings:
                continue
            if key in seen:
                raise ValueError(f"Ambiguous material binding: {wrapper.submesh_name}")
            seen.add(key)
            wrapped.add(key)
            block, found = _rewrite_block(fragment[wrapper.start:wrapper.end], settings[key])
            written[key].update(found)
            edits.append((wrapper.start, wrapper.end, block))
        for start, end, block in reversed(edits):
            fragment = fragment[:start] + block + fragment[end:]
        return fragment, None

    text, _ = edit_material_variants(text, edit)
    missing_parts = sorted(set(settings) - wrapped)
    if missing_parts:
        raise ValueError("The material sidecar has no wrapper for: " + ", ".join(missing_parts))
    for key, colours in settings.items():
        missing = sorted(set(colours) - written[key])
        if missing:
            raise ValueError(f"{key}: the material has no colour row named " + ", ".join(missing) + ".")
    return text
