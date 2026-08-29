"""Immutable character-context discovery and preview contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re

from cdmw.models import ArchiveEntry


def _appearance_path_parts(path: object) -> tuple[str, ...]:
    normalized = str(path or "").replace("\\", "/").strip().strip("/").lower()
    return tuple(part for part in PurePosixPath(normalized).parts if part)


def appearance_model_body_family(path: str) -> str:
    parts = _appearance_path_parts(path)
    for index, part in enumerate(parts[:-1]):
        if part == "1_pc" and index + 1 < len(parts):
            family = parts[index + 1]
            match = re.match(r"^0*(\d+)_([a-z0-9]+)$", family)
            if match:
                return f"{int(match.group(1))}_{match.group(2)}"
            return family
    return ""


def appearance_model_slot(path: str) -> str:
    parts = _appearance_path_parts(path)
    for marker in ("armor", "weapon"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts):
                return f"{marker}/{parts[index + 1]}" if marker == "weapon" else parts[index + 1]
            return marker
    if "head_sub" in parts:
        return "face"
    for marker in ("hair", "beard", "face", "nude", "body", "head"):
        if marker in parts:
            return marker
    return ""


def character_context_entry_key(entry: ArchiveEntry) -> str:
    path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().casefold()
    pamt = str(getattr(entry, "pamt_path", "") or "").strip().casefold()
    offset = int(getattr(entry, "offset", 0) or 0)
    return f"{pamt}|{path}|{offset}"


def merge_character_context_dependency_entries(
    dependency_entries: tuple[ArchiveEntry, ...],
    dependencies_complete: bool,
    components: tuple[NativePreviewContextComponent, ...],
) -> tuple[tuple[ArchiveEntry, ...], bool]:
    merged: list[ArchiveEntry] = []
    seen: set[tuple[str, str, int]] = set()
    candidates = dependency_entries + tuple(component.entry for component in components) + tuple(
        entry for component in components for entry in component.dependency_entries
    )
    for entry in candidates:
        key = (
            str(entry.pamt_path or "").casefold(),
            str(entry.path or "").replace("\\", "/").casefold(),
            int(entry.offset or 0),
        )
        if key not in seen:
            seen.add(key)
            merged.append(entry)
    return tuple(merged), bool(
        dependencies_complete and all(component.dependencies_complete for component in components)
    )


@dataclass(frozen=True, slots=True)
class CharacterContextOption:
    option_id: str
    entry: ArchiveEntry
    slot: str
    label: str
    authority: str
    compatibility: str
    scale: float = 1.0
    appearance_path: str = ""
    face_contents: tuple[str, ...] = ()
    dependency_entries: tuple[ArchiveEntry, ...] = ()
    dependencies_complete: bool = False
    component_entries: tuple[ArchiveEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class CharacterContextAppearance:
    appearance_id: str
    entry: ArchiveEntry
    label: str
    options: tuple[CharacterContextOption, ...]
    resolved_essential_count: int = 0
    source_scale: float = 1.0


@dataclass(frozen=True, slots=True)
class CharacterContextDiscoveryRequest:
    source_entry: ArchiveEntry
    archive_entries: tuple[ArchiveEntry, ...]
    path_index: object
    basename_index: object
    archive_fingerprint: str = ""
    request_id: int = 0


@dataclass(frozen=True, slots=True)
class CharacterContextDiscoveryResult:
    request_id: int
    source_entry: ArchiveEntry
    archive_fingerprint: str
    appearances: tuple[CharacterContextAppearance, ...]
    compatible_hair: tuple[CharacterContextOption, ...] = ()
    compatible_body: tuple[CharacterContextOption, ...] = ()
    source_dependency_entries: tuple[ArchiveEntry, ...] = ()
    source_dependencies_complete: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def source_key(self) -> str:
        return f"{self.archive_fingerprint}|{character_context_entry_key(self.source_entry)}"


@dataclass(frozen=True, slots=True)
class CharacterContextSelection:
    appearance_id: str = ""
    face_option_ids: tuple[str, ...] = ()
    hair_option_id: str = ""
    body_option_id: str = ""
    gear_option_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NativePreviewContextComponent:
    entry: ArchiveEntry
    slot: str
    label: str
    authority: str
    scale: float = 1.0
    appearance_path: str = ""
    dependency_entries: tuple[ArchiveEntry, ...] = ()
    dependencies_complete: bool = False
    presentation_geometry_payload: bytes = b""
    presentation_geometry_source: str = ""


def default_character_context_selection(
    result: CharacterContextDiscoveryResult,
    *,
    appearance_id: str = "",
) -> CharacterContextSelection:
    appearance = next(
        (item for item in result.appearances if item.appearance_id == appearance_id),
        result.appearances[0] if result.appearances else None,
    )
    if appearance is None:
        return CharacterContextSelection()
    return CharacterContextSelection(
        appearance_id=appearance.appearance_id,
        face_option_ids=tuple(option.option_id for option in appearance.options if option.slot == "face"),
    )


def character_context_options_by_id(
    result: CharacterContextDiscoveryResult,
    selection: CharacterContextSelection,
) -> dict[str, CharacterContextOption]:
    options: dict[str, CharacterContextOption] = {}
    appearance = next(
        (item for item in result.appearances if item.appearance_id == selection.appearance_id),
        result.appearances[0] if result.appearances else None,
    )
    if appearance is not None:
        options.update((option.option_id, option) for option in appearance.options)
    options.update((option.option_id, option) for option in result.compatible_hair)
    options.update((option.option_id, option) for option in result.compatible_body)
    return options


def selected_character_context_components(
    result: CharacterContextDiscoveryResult,
    selection: CharacterContextSelection,
) -> tuple[NativePreviewContextComponent, ...]:
    options = character_context_options_by_id(result, selection)
    selected_ids = (
        tuple(selection.face_option_ids)
        + ((selection.hair_option_id,) if selection.hair_option_id else ())
        + ((selection.body_option_id,) if selection.body_option_id else ())
        + tuple(selection.gear_option_ids)
    )
    components: list[NativePreviewContextComponent] = []
    seen: set[str] = set()
    for option_id in selected_ids:
        option = options.get(option_id)
        if option is None:
            continue
        option_entries = option.component_entries or (option.entry,)
        for option_entry in option_entries:
            entry_key = character_context_entry_key(option_entry)
            if entry_key in seen:
                continue
            seen.add(entry_key)
            components.append(
                NativePreviewContextComponent(
                    entry=option_entry,
                    slot=option.slot,
                    label=option.label,
                    authority=option.authority,
                    scale=option.scale,
                    appearance_path=option.appearance_path,
                    dependency_entries=option.dependency_entries,
                    dependencies_complete=option.dependencies_complete,
                )
            )
    return tuple(components)


__all__ = [
    "CharacterContextAppearance",
    "CharacterContextDiscoveryRequest",
    "CharacterContextDiscoveryResult",
    "CharacterContextOption",
    "CharacterContextSelection",
    "NativePreviewContextComponent",
    "appearance_model_body_family",
    "appearance_model_slot",
    "character_context_entry_key",
    "character_context_options_by_id",
    "default_character_context_selection",
    "merge_character_context_dependency_entries",
    "selected_character_context_components",
]
