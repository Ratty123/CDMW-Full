from __future__ import annotations

import pytest

from cdmw.domain.archives.catalogue import ArchiveEntryRole, ArchiveSortField, ArchiveViewMode
from cdmw.domain.archives.filters import COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS
from cdmw.ui.archive_browser.remote_query import archive_query_from_browser_state


def test_remote_query_maps_every_existing_archive_filter_control() -> None:
    query = archive_query_from_browser_state(
        "session-a",
        {
            "filter_text": " name: Vow of the Dead King ",
            "exclude_filter_text": "*_lod.dds;debug/*",
            "extension_filter": "DDS",
            "package_filter_text": "0009/0.pamt",
            "structure_filter": "character/model/",
            "role_filter": "texture",
            "exclude_common_technical_suffixes": True,
            "min_size_kb": 64,
            "previewable_only": True,
            "active_overrides_only": True,
            "view_mode": "categories_folders",
            "sort_column": 1,
            "sort_order": "desc",
        },
    )

    assert query.session_id == "session-a"
    assert query.include_text == "name: Vow of the Dead King"
    assert query.exclude_text == "*_lod.dds;debug/*"
    assert query.extensions == (".dds",)
    assert query.packages == ("0009/0.pamt",)
    assert query.folder == "character/model"
    assert query.roles == (
        ArchiveEntryRole.IMAGE,
        ArchiveEntryRole.NORMAL,
        ArchiveEntryRole.MATERIAL,
        ArchiveEntryRole.IMPOSTOR,
        ArchiveEntryRole.USER_INTERFACE,
    )
    assert query.technical_suffixes == COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS
    assert query.minimum_size == 64 * 1024
    assert query.previewable_only
    assert query.active_overrides_only
    assert query.view_mode is ArchiveViewMode.CATEGORIES_AND_FOLDERS
    assert query.sort_field is ArchiveSortField.KNOWN_NAME
    assert query.sort_active
    assert query.sort_descending


@pytest.mark.parametrize(
    ("column", "field"),
    [
        (-1, ArchiveSortField.PATH),
        (0, ArchiveSortField.NAME),
        (1, ArchiveSortField.KNOWN_NAME),
        (2, ArchiveSortField.ROLE),
        (3, ArchiveSortField.ORIGINAL_SIZE),
        (4, ArchiveSortField.COMPRESSION),
        (5, ArchiveSortField.PACKAGE),
        (6, ArchiveSortField.ACTIVE_OVERRIDE),
        (7, ArchiveSortField.PATH),
    ],
)
def test_remote_query_maps_visible_sort_columns(column: int, field: ArchiveSortField) -> None:
    query = archive_query_from_browser_state("session-a", {"sort_column": column})
    assert query.sort_field is field
    assert query.sort_active is (column >= 0)


@pytest.mark.parametrize(
    ("value", "mode"),
    [
        ("folders", ArchiveViewMode.FOLDERS),
        ("categories", ArchiveViewMode.CATEGORIES),
        ("categories_folders", ArchiveViewMode.CATEGORIES_AND_FOLDERS),
        ("flat", ArchiveViewMode.FLAT),
    ],
)
def test_remote_query_maps_existing_view_modes(value: str, mode: ArchiveViewMode) -> None:
    assert archive_query_from_browser_state("session-a", {"view_mode": value}).view_mode is mode


def test_remote_query_neutral_state_is_deterministic_and_unfiltered() -> None:
    query = archive_query_from_browser_state("session-a", {})

    assert query.include_text is None
    assert query.exclude_text is None
    assert query.extensions == ()
    assert query.packages == ()
    assert query.folder is None
    assert query.roles == ()
    assert query.technical_suffixes == ()
    assert query.minimum_size is None
    assert query.view_mode is ArchiveViewMode.FLAT
    assert query.sort_field is ArchiveSortField.PATH
    assert not query.sort_active
