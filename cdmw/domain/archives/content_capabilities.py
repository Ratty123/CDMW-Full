"""The archive content capability manifest, read as rules rather than transcribed.

`schemas/archive_content_capabilities.v1.json` already registers every archive
format the workbench understands, and the .NET archive backend and the format
reporting tools both read it. Nothing in `cdmw/` did, so each feature that needed
to know what an extension is kept its own list and the lists drifted: a format
registered in the manifest could be previewed and still be unlinkable, because
the code that follows references had never heard of it.

This module is the Python side of that one manifest. It parses the file, not the
payloads it describes, so it stays a rule and the binary readers stay in
`cdmw/core/`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional, Tuple

MANIFEST_RELATIVE_PATH = ("schemas", "archive_content_capabilities.v1.json")
SUPPORTED_SCHEMA_VERSION = 1


@dataclass(slots=True, frozen=True)
class ArchiveContentCapability:
    """What the manifest registers about one archive extension."""

    extension: str
    role: str
    group: str
    container: str
    analyzer: str
    maturity: str
    readable: bool
    structured: bool
    references: bool
    visual: bool
    playback: bool
    exports: Tuple[str, ...]


class ArchiveCapabilityManifestError(RuntimeError):
    """The manifest is missing or unreadable, which every archive rule depends on."""


def normalize_extension(extension: str) -> str:
    """Lower-cases an extension and gives it the leading dot the manifest uses."""

    text = str(extension or "").strip().lower()
    if not text:
        return ""
    return text if text.startswith(".") else f".{text}"


def _manifest_path() -> Path:
    frozen_root = str(getattr(sys, "_MEIPASS", "") or "").strip()
    root = Path(frozen_root) if frozen_root else Path(__file__).resolve().parents[3]
    return root.joinpath(*MANIFEST_RELATIVE_PATH)


def _capability_from_row(row: Mapping[str, object]) -> Optional[ArchiveContentCapability]:
    extension = normalize_extension(str(row.get("extension", "")))
    if not extension:
        return None
    exports = row.get("exports")
    return ArchiveContentCapability(
        extension=extension,
        role=str(row.get("role", "")),
        group=str(row.get("group", "")),
        container=str(row.get("container", "")),
        analyzer=str(row.get("analyzer", "")),
        maturity=str(row.get("maturity", "")),
        readable=bool(row.get("readable", False)),
        structured=bool(row.get("structured", False)),
        references=bool(row.get("references", False)),
        visual=bool(row.get("visual", False)),
        playback=bool(row.get("playback", False)),
        exports=tuple(str(value) for value in exports) if isinstance(exports, list) else (),
    )


@lru_cache(maxsize=1)
def load_capabilities() -> Tuple[ArchiveContentCapability, ...]:
    """Every registered format, in the order the manifest lists it.

    A missing or malformed manifest is raised rather than swallowed. Silently
    returning nothing would leave the archive rules quietly agreeing that no
    format is linkable, which reads as a content bug in every feature at once
    instead of as the broken install it is.
    """

    path = _manifest_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ArchiveCapabilityManifestError(
            f"The archive content capability manifest could not be read from {path}: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise ArchiveCapabilityManifestError(
            f"The archive content capability manifest at {path} is not a JSON object."
        )
    version = payload.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ArchiveCapabilityManifestError(
            f"The archive content capability manifest at {path} declares schema version "
            f"{version!r}, but this build reads version {SUPPORTED_SCHEMA_VERSION}."
        )
    rows = payload.get("extensions")
    if not isinstance(rows, list) or not rows:
        raise ArchiveCapabilityManifestError(
            f"The archive content capability manifest at {path} registers no extensions."
        )
    capabilities = tuple(
        capability
        for capability in (
            _capability_from_row(row) for row in rows if isinstance(row, dict)
        )
        if capability is not None
    )
    if not capabilities:
        raise ArchiveCapabilityManifestError(
            f"No usable extension rows were found in the manifest at {path}."
        )
    return capabilities


@lru_cache(maxsize=1)
def _capabilities_by_extension() -> Mapping[str, ArchiveContentCapability]:
    return {capability.extension: capability for capability in load_capabilities()}


def capability_for(extension: str) -> Optional[ArchiveContentCapability]:
    """The registered capability for an extension, or `None` when it is unknown."""

    return _capabilities_by_extension().get(normalize_extension(extension))


def is_registered_extension(extension: str) -> bool:
    return normalize_extension(extension) in _capabilities_by_extension()


@lru_cache(maxsize=1)
def registered_extensions() -> Tuple[str, ...]:
    """Every registered extension, longest first so a match takes the whole suffix.

    Ordering here is what stops `city.paccd` being read as the `.pac` that its
    name starts with. Ties resolve by name so the order is stable across runs.
    """

    return tuple(
        sorted(
            _capabilities_by_extension(),
            key=lambda extension: (-len(extension), extension),
        )
    )


def extensions_with_role(*roles: str) -> Tuple[str, ...]:
    wanted = {str(role).strip().lower() for role in roles}
    return tuple(
        capability.extension
        for capability in load_capabilities()
        if capability.role in wanted
    )


def extensions_in_group(*groups: str) -> Tuple[str, ...]:
    wanted = {str(group).strip().lower() for group in groups}
    return tuple(
        capability.extension
        for capability in load_capabilities()
        if capability.group in wanted
    )


def extensions_that_reference() -> Tuple[str, ...]:
    """Formats the manifest says can name another file."""

    return tuple(
        capability.extension
        for capability in load_capabilities()
        if capability.references
    )


def extensions_with_playback() -> Tuple[str, ...]:
    return tuple(
        capability.extension
        for capability in load_capabilities()
        if capability.playback
    )


__all__ = [
    "ArchiveCapabilityManifestError",
    "ArchiveContentCapability",
    "MANIFEST_RELATIVE_PATH",
    "SUPPORTED_SCHEMA_VERSION",
    "capability_for",
    "extensions_in_group",
    "extensions_that_reference",
    "extensions_with_playback",
    "extensions_with_role",
    "is_registered_extension",
    "load_capabilities",
    "normalize_extension",
    "registered_extensions",
]
