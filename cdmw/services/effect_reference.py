"""Resolve shipped effect reference namespaces on the existing worker lanes.

The flattened .pae filename omits its namespace. The game's effect registries
retain it; adding .level.effect to every stem can name an unregistered effect.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

KINDS = ("level", "action", "gimmick", "system", "sequencer")
_REFERENCE = re.compile(r"([A-Za-z0-9_-]{1,128})\.(level|action|gimmick|system|sequencer)\.effect\Z")
_ENTRY = re.compile(r"<Effect\s[^<>]{0,8192}/>")


def resolve_effect_reference(snapshot, reference: str) -> str:
    """Keep a registered reference, or resolve a legacy default by exact stem.

    A snapshot without registry files retains the caller's reference. Registry
    reads remain authoritative: corrupt/unreadable resources are not suppressed.
    Some shipped registries contain malformed comments, so parse individual
    Effect elements after removing comments rather than rejecting the whole file.
    """
    match = _REFERENCE.fullmatch(reference)
    if match is None:
        raise ValueError(f"Invalid effect reference: {reference}")
    cache = getattr(snapshot, "_authoring_indexes", {})
    references = cache.get("effect_references")
    if references is None:
        references = {}
        for kind in KINDS:
            path = f"effect/effect_{kind}.xml"
            if not snapshot.has_entry(path):
                continue
            raw = snapshot.payload(path)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError(f"Effect registry exceeds 8 MB: {path}")
            text = re.sub(r"<!--.*?-->", "", raw.decode("utf-8-sig"), flags=re.DOTALL)
            for entry in _ENTRY.finditer(text):
                name = ET.fromstring(entry.group()).get("Name", "")
                named = _REFERENCE.fullmatch(name)
                if named is not None:
                    references.setdefault(named[1], []).append(name)
        cache["effect_references"] = references
    choices = references.get(match[1], ())
    return reference if not choices or reference in choices else choices[0]
