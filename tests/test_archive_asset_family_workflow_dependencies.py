from __future__ import annotations

from pathlib import Path

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.asset_family_panel import _asset_family_panel_dependencies
from cdmw.ui.archive_browser.asset_family_references import ArchiveAssetFamilyReferenceMixin
from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet


def _entry(path: str, offset: int, *, prepared_path: Path | None = None) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("C:/Game/0009/0.pamt"),
        paz_file=Path("C:/Game/0009/0.paz"),
        offset=offset,
        comp_size=20,
        orig_size=40,
        flags=0,
        paz_index=0,
        prepared_path=prepared_path,
        prepared_sha256=f"sha-{offset}" if prepared_path is not None else "",
    )


def _snapshot(selected: ArchiveEntry, *dependencies: ArchiveEntry) -> ArchivePreviewDependencySet:
    entries = (selected, *dependencies)
    return ArchivePreviewDependencySet(
        session_id="session-a",
        entry_id=7,
        entries=entries,
        entries_by_normalized_path={entry.path.casefold(): (entry,) for entry in entries},
        entries_by_basename={entry.basename.casefold(): (entry,) for entry in entries},
        total_candidates=len(dependencies),
        truncated=False,
    )


class _Bridge:
    displays_v2 = True

    def __init__(self, snapshot: ArchivePreviewDependencySet) -> None:
        self.snapshot = snapshot

    def prepared_dependencies_for(self, _entry: ArchiveEntry) -> ArchivePreviewDependencySet:
        return self.snapshot


def test_associated_asset_used_by_enrichment_uses_bounded_remote_candidates(tmp_path: Path) -> None:
    prepared_hkx = _entry("character/physics/hero.hkx", 100, prepared_path=tmp_path / "hero.hkx")
    prepared_model = _entry("character/physics/hero.pac", 200, prepared_path=tmp_path / "hero.pac")
    snapshot = _snapshot(prepared_hkx, prepared_model)

    class _Owner(ArchiveAssetFamilyReferenceMixin):
        archive_remote_bridge = _Bridge(snapshot)

        @property
        def archive_entries_by_basename(self) -> object:
            raise AssertionError("Associated Assets touched the legacy basename index")

        @property
        def archive_sidecar_entries_by_texture_path(self) -> object:
            raise AssertionError("Associated Assets touched the legacy sidecar path index")

        @property
        def archive_sidecar_entries_by_texture_basename(self) -> object:
            raise AssertionError("Associated Assets touched the legacy sidecar basename index")

    selected = _entry("character/physics/hero.hkx", 100)
    references = ArchiveAssetFamilyReferenceMixin._archive_known_used_by_references(_Owner(), selected)

    assert [reference.resolved_entry for reference in references] == [prepared_model]


def test_associated_asset_panel_uses_prepared_entry_and_bounded_remote_maps(tmp_path: Path) -> None:
    prepared_model = _entry("character/model/hero.pac", 300, prepared_path=tmp_path / "hero.pac")
    prepared_texture = _entry("character/texture/hero_d.dds", 400, prepared_path=tmp_path / "hero_d.dds")
    snapshot = _snapshot(prepared_model, prepared_texture)

    class _Owner:
        archive_remote_bridge = _Bridge(snapshot)

        @staticmethod
        def _current_archive_entry() -> ArchiveEntry:
            return _entry("character/model/hero.pac", 300)

        @property
        def archive_entries_by_normalized_path(self) -> object:
            raise AssertionError("Associated Assets panel touched the legacy path index")

        @property
        def archive_entries_by_basename(self) -> object:
            raise AssertionError("Associated Assets panel touched the legacy basename index")

    entry, entries_by_path, entries_by_basename = _asset_family_panel_dependencies(_Owner())

    assert entry is prepared_model
    assert entries_by_path is snapshot.entries_by_normalized_path
    assert entries_by_basename is snapshot.entries_by_basename
