"""Translate existing Archive Browser controls into the worker query contract."""

from __future__ import annotations

from collections.abc import Mapping

from cdmw.domain.archives.catalogue import (
    ArchiveEntryRole,
    ArchiveQuery,
    ArchiveSortField,
    ArchiveViewMode,
)
from cdmw.domain.archives.filters import (
    COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS,
    normalize_archive_browser_sort_column,
    normalize_archive_browser_sort_order,
    normalize_archive_structure_filter_value,
)
from cdmw.domain.archives.format import normalize_archive_extension_filter


_VIEW_MODES = {
    "folders": ArchiveViewMode.FOLDERS,
    "categories": ArchiveViewMode.CATEGORIES,
    "categories_folders": ArchiveViewMode.CATEGORIES_AND_FOLDERS,
    "categories_and_folders": ArchiveViewMode.CATEGORIES_AND_FOLDERS,
    "flat": ArchiveViewMode.FLAT,
}

_SORT_FIELDS = {
    0: ArchiveSortField.NAME,
    1: ArchiveSortField.KNOWN_NAME,
    2: ArchiveSortField.ROLE,
    3: ArchiveSortField.ORIGINAL_SIZE,
    4: ArchiveSortField.COMPRESSION,
    5: ArchiveSortField.PACKAGE,
    6: ArchiveSortField.ACTIVE_OVERRIDE,
    7: ArchiveSortField.PATH,
}

_ROLE_FILTERS = {
    "image": (ArchiveEntryRole.IMAGE,),
    "normal": (ArchiveEntryRole.NORMAL,),
    "material": (ArchiveEntryRole.MATERIAL,),
    "impostor": (ArchiveEntryRole.IMPOSTOR,),
    "ui": (ArchiveEntryRole.USER_INTERFACE,),
    "text": (ArchiveEntryRole.TEXT,),
    "model": (ArchiveEntryRole.MODEL,),
    "animation": (ArchiveEntryRole.ANIMATION,),
    "physics": (ArchiveEntryRole.PHYSICS,),
    "metadata": (ArchiveEntryRole.METADATA,),
    "video": (ArchiveEntryRole.VIDEO,),
    "audio": (ArchiveEntryRole.AUDIO,),
}

_TEXTURE_ROLES = (
    ArchiveEntryRole.IMAGE,
    ArchiveEntryRole.NORMAL,
    ArchiveEntryRole.MATERIAL,
    ArchiveEntryRole.IMPOSTOR,
    ArchiveEntryRole.USER_INTERFACE,
)


def archive_query_from_browser_state(
    session_id: str,
    state: Mapping[str, object],
) -> ArchiveQuery:
    """Build one immutable, fully worker-owned browser query."""

    extension = normalize_archive_extension_filter(state.get("extension_filter", "*"))
    extensions = () if extension in {"", "*", ".*", "all"} else (extension,)
    role_value = str(state.get("role_filter", "all") or "all").strip().lower()
    roles = _TEXTURE_ROLES if role_value == "texture" else _ROLE_FILTERS.get(role_value, ())
    view_value = str(state.get("view_mode", "flat") or "flat").strip().lower()
    view_mode = _VIEW_MODES.get(view_value, ArchiveViewMode.FLAT)
    sort_column = normalize_archive_browser_sort_column(state.get("sort_column", -1))
    sort_field = _SORT_FIELDS.get(sort_column, ArchiveSortField.PATH)
    sort_descending = normalize_archive_browser_sort_order(state.get("sort_order", "asc")) == "desc"
    package_filter = str(state.get("package_filter_text", "") or "").strip()
    minimum_kb = _nonnegative_int(state.get("min_size_kb", 0))
    exclude_technical = bool(state.get("exclude_common_technical_suffixes", False))

    return ArchiveQuery(
        session_id=str(session_id),
        include_text=_optional_text(state.get("filter_text")),
        exclude_text=_optional_text(state.get("exclude_filter_text")),
        extensions=extensions,
        packages=(package_filter,) if package_filter else (),
        folder=_optional_text(normalize_archive_structure_filter_value(str(state.get("structure_filter", "") or ""))),
        roles=roles,
        technical_suffixes=COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS if exclude_technical else (),
        minimum_size=minimum_kb * 1024 if minimum_kb else None,
        previewable_only=bool(state.get("previewable_only", False)),
        active_overrides_only=bool(state.get("active_overrides_only", False)),
        view_mode=view_mode,
        sort_field=sort_field,
        sort_active=sort_column >= 0,
        sort_descending=sort_descending,
    )


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


__all__ = ["archive_query_from_browser_state"]
