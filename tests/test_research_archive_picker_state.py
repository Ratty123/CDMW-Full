from __future__ import annotations

from pathlib import Path

from cdmw.models import ArchiveEntry
from cdmw.ui.research.archive_picker_state import (
    archive_picker_available_status_text,
    archive_picker_entries_from_sources,
    archive_picker_entry_for_path,
    archive_picker_entry_index_for_path,
    archive_picker_file_label,
    archive_picker_focus_flat_overflow_status_text,
    archive_picker_focus_missing_status_text,
    archive_picker_folder_parts,
    archive_picker_folder_status_text,
    archive_picker_path_lookup_maps,
    archive_picker_render_status_text,
    archive_picker_reusable_browser_tree_index,
    archive_picker_selected_entry_status_text,
    build_archive_snapshot_cache_key,
    cached_archive_snapshot_cache_key,
    normalize_archive_path,
)


def _entry(path: str, package: str = "pakchunk0/paz00001.paz") -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path(package),
        paz_file=Path(package),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


def test_archive_picker_path_helpers_normalize_labels_indexes_and_cache_keys() -> None:
    assert normalize_archive_path(r" 0001\texture\armor.dds ") == "0001/texture/armor.dds"
    assert archive_picker_file_label(r"0001\texture\armor.dds", show_full_path=False) == "armor.dds"
    assert archive_picker_file_label(r"0001\texture\armor.dds", show_full_path=True) == "0001/texture/armor.dds"
    assert archive_picker_folder_parts(r"0001\texture\armor.dds") == ("0001", "texture")

    entries = [_entry(r"0001\texture\armor.dds"), _entry("0001/texture/armor_n.dds")]
    assert build_archive_snapshot_cache_key(entries) == build_archive_snapshot_cache_key(entries)
    assert build_archive_snapshot_cache_key(entries).startswith("2:")
    assert build_archive_snapshot_cache_key([]) == "0:empty"

    cache: dict[tuple[int, int, str, str], str] = {}
    cached_key = cached_archive_snapshot_cache_key(entries, cache)
    assert cached_key == build_archive_snapshot_cache_key(entries)
    assert cached_archive_snapshot_cache_key(entries, cache) == cached_key
    assert len(cache) == 1
    assert cached_archive_snapshot_cache_key([], cache) == "0:empty"

    eager_index = {normalize_archive_path(entries[0].path).casefold(): 0}
    lazy_index: dict[str, int] = {}
    assert archive_picker_entry_index_for_path(
        "0001/texture/armor.dds",
        entries=entries,
        entry_index_by_path=eager_index,
        lazy_entry_index_by_path=lazy_index,
    ) == 0
    assert archive_picker_entry_index_for_path(
        "0001/texture/armor_n.dds",
        entries=entries,
        entry_index_by_path=eager_index,
        lazy_entry_index_by_path=lazy_index,
    ) == 1
    assert lazy_index["0001/texture/armor_n.dds"] == 1
    assert archive_picker_entry_for_path(
        r"0001\texture\armor.dds",
        entries=entries,
        entry_by_path={normalize_archive_path(entries[0].path): entries[0]},
        entry_index_by_path=eager_index,
        lazy_entry_index_by_path=lazy_index,
    ) is entries[0]
    assert archive_picker_entry_for_path(
        "missing.dds",
        entries=entries,
        entry_by_path={},
        entry_index_by_path={},
        lazy_entry_index_by_path={},
    ) is None


def test_archive_picker_available_status_text_preserves_existing_modes() -> None:
    assert archive_picker_available_status_text(
        entry_count=0,
        eager_path_maps=True,
        view_mode="flat",
        flat_render_limit=5000,
        skipped_large_index=False,
    ) == "No archive files are available yet. Scan archives or broaden the current Archive Browser filter."

    assert archive_picker_available_status_text(
        entry_count=10,
        eager_path_maps=False,
        view_mode="folders",
        flat_render_limit=5000,
        skipped_large_index=False,
    ) == "10 archive file(s) available. Path lookups are lazy to keep RAM usage down."

    assert archive_picker_available_status_text(
        entry_count=6000,
        eager_path_maps=True,
        view_mode="flat",
        flat_render_limit=5000,
        skipped_large_index=True,
    ) == "Flat view shows the first 5,000 of 6,000 visible file(s). Narrow Archive Browser filters for the rest."

    assert "waiting for the Archive Browser tree index" in archive_picker_available_status_text(
        entry_count=100001,
        eager_path_maps=True,
        view_mode="folders",
        flat_render_limit=5000,
        skipped_large_index=True,
    )


def test_archive_picker_status_text_helpers_format_selection_and_focus_messages() -> None:
    entry = _entry("0001/texture/armor.dds")

    assert archive_picker_render_status_text(rendered_count=250, total=1000) == "Rendering archive files... 250 / 1,000"
    assert archive_picker_focus_missing_status_text("missing.dds") == (
        "Reference points to missing.dds, but that file is not visible in the current Archive Files list."
    )
    assert archive_picker_focus_flat_overflow_status_text("armor.dds", rendered_count=5000) == (
        "armor.dds is visible in the current Archive Browser filter, but not in the first 5,000 flat rows. "
        "Narrow the filter or switch to Folders."
    )
    assert archive_picker_selected_entry_status_text(entry) == "Selected: 0001/texture/armor.dds (pakchunk0/paz00001.paz)"
    assert archive_picker_folder_status_text("0001/texture", count=42) == "Folder: 0001/texture (42 file(s))"


def test_archive_picker_entries_from_sources_preserves_list_identity_and_filters_iterables() -> None:
    filtered = [_entry("visible.dds")]
    fallback = [_entry("fallback.dds")]

    assert archive_picker_entries_from_sources(filtered, fallback) is filtered
    assert archive_picker_entries_from_sources([], fallback) is fallback

    mixed_entries = (value for value in [_entry("kept.dds"), object()])
    assert archive_picker_entries_from_sources(mixed_entries, []) == [_entry("kept.dds")]


def test_archive_picker_path_lookup_maps_switches_to_lazy_mode_for_large_lists() -> None:
    entries = [_entry("A.dds"), _entry("folder\\B.dds")]

    eager_maps = archive_picker_path_lookup_maps(entries)
    assert eager_maps.eager_path_maps is True
    assert eager_maps.entry_index_by_path == {"a.dds": 0, "folder/b.dds": 1}
    assert eager_maps.entry_by_path["folder/B.dds"] == entries[1]

    lazy_maps = archive_picker_path_lookup_maps(entries, eager_limit=1)
    assert lazy_maps.eager_path_maps is False
    assert lazy_maps.entry_index_by_path == {}
    assert lazy_maps.entry_by_path == {}


def test_archive_picker_reusable_browser_tree_index_requires_matching_ready_payload() -> None:
    entries = [_entry("a.dds")]
    child_folders = {(): [("texture", ("texture",))]}
    direct_files = {(): [0]}
    folder_indexes = {(): [0]}
    folder_stats = {(): (1, 0, 0)}
    payload = {
        "entries": entries,
        "tree_index_ready": True,
        "tree_child_folders": child_folders,
        "tree_direct_files": direct_files,
        "tree_folder_entry_indexes": folder_indexes,
        "tree_folder_preview_stats": folder_stats,
    }

    reusable_index = archive_picker_reusable_browser_tree_index(payload, entries)

    assert reusable_index is not None
    assert reusable_index.child_folders is child_folders
    assert reusable_index.direct_files is direct_files
    assert reusable_index.folder_entry_indexes is folder_indexes
    assert reusable_index.folder_preview_stats is folder_stats
    assert archive_picker_reusable_browser_tree_index({**payload, "tree_index_ready": False}, entries) is None
    assert archive_picker_reusable_browser_tree_index({**payload, "entries": list(entries)}, entries) is None
    assert archive_picker_reusable_browser_tree_index({**payload, "tree_child_folders": []}, entries) is None
