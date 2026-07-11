"""Pure socket XML formatting helpers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence

from cdmw.models import ArchiveEntry


def attachment_socket_xml_text(root: ET.Element, *, include_declaration: bool) -> str:
    try:
        ET.indent(root, space="  ")
    except Exception:
        pass
    text = ET.tostring(root, encoding="unicode")
    if include_declaration:
        text = '<?xml version="1.0" encoding="utf-8"?>\n' + text
    return text.rstrip() + "\n"


def attachment_socket_xml_numbered_text(root: ET.Element, *, include_declaration: bool) -> str:
    lines = attachment_socket_xml_text(root, include_declaration=include_declaration).splitlines()
    width = max(2, len(str(len(lines))))
    return "\n".join(f"{index:>{width}} | {line}" for index, line in enumerate(lines, start=1)) + "\n"


def attachment_transform_values_close(first: Sequence[float], second: Sequence[float]) -> bool:
    left = tuple(first or ())
    right = tuple(second or ())
    return len(left) == len(right) and all(abs(float(a) - float(b)) <= 0.00001 for a, b in zip(left, right))


def archive_socket_xml_candidates(
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
    current_entry: ArchiveEntry,
    *,
    same_entry: Callable[[ArchiveEntry, ArchiveEntry], bool],
) -> tuple[ArchiveEntry, ...]:
    candidates: list[ArchiveEntry] = []
    seen: set[tuple[str, str, int]] = set()
    for basename, entries in entries_by_basename.items():
        name = str(basename or "").casefold()
        if not (name.endswith(".sockets.xml") or (name.endswith(".xml") and "socket" in name)):
            continue
        for candidate in entries or ():
            if not isinstance(candidate, ArchiveEntry) or same_entry(candidate, current_entry):
                continue
            path = str(candidate.path or "").replace("\\", "/").casefold()
            if not (path.endswith(".sockets.xml") or ("socketbonedata" in path and path.endswith(".xml"))):
                continue
            key = (path, str(candidate.pamt_path).strip().casefold(), int(candidate.offset))
            if key not in seen:
                seen.add(key)
                candidates.append(candidate)
    return tuple(sorted(candidates, key=lambda entry: str(entry.path or "").casefold()))


__all__ = [
    "archive_socket_xml_candidates",
    "attachment_socket_xml_numbered_text",
    "attachment_socket_xml_text",
    "attachment_transform_values_close",
]
