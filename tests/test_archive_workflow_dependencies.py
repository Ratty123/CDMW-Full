from __future__ import annotations

from pathlib import Path

import pytest

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependenciesUnavailable,
    archive_workflow_dependency_context,
)


def _entry(path: str, offset: int, *, prepared: bool = False) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("C:/Game/0009/0.pamt"),
        paz_file=Path("C:/Game/0009/0.paz"),
        offset=offset,
        comp_size=20,
        orig_size=40,
        flags=0,
        paz_index=0,
        prepared_path=Path(f"C:/cache/{offset}.bin") if prepared else None,
        prepared_sha256=f"sha-{offset}" if prepared else "",
    )


def _snapshot() -> ArchivePreviewDependencySet:
    selected = _entry("character/model/hero.pac", 100, prepared=True)
    texture = _entry("character/texture/hero_d.dds", 200, prepared=True)
    return ArchivePreviewDependencySet(
        session_id="session-a",
        entry_id=7,
        entries=(selected, texture),
        entries_by_normalized_path={
            "character/model/hero.pac": (selected,),
            "character/texture/hero_d.dds": (texture,),
        },
        entries_by_basename={"hero.pac": (selected,), "hero_d.dds": (texture,)},
        total_candidates=1,
        truncated=False,
    )


def test_remote_workflow_context_uses_only_bounded_prepared_dependencies() -> None:
    snapshot = _snapshot()

    class _Bridge:
        displays_v2 = True

        @staticmethod
        def prepared_dependencies_for(_entry: ArchiveEntry) -> ArchivePreviewDependencySet:
            return snapshot

    class _Owner:
        archive_remote_bridge = _Bridge()

        @property
        def archive_entries(self) -> object:
            raise AssertionError("v2 workflow touched the legacy global catalogue")

    selected = _entry("character/model/hero.pac", 100)
    context = archive_workflow_dependency_context(_Owner(), selected)

    assert context.remote
    assert context.selected_entry is snapshot.selected_entry
    assert context.selected_entry.prepared_path == Path("C:/cache/100.bin")
    assert context.entries_by_basename["hero_d.dds"][0].prepared_path == Path("C:/cache/200.bin")


def test_remote_workflow_context_fails_closed_without_prepared_dependencies() -> None:
    class _Bridge:
        displays_v2 = True

        @staticmethod
        def prepared_dependencies_for(_entry: ArchiveEntry) -> None:
            return None

    owner = type("Owner", (), {"archive_remote_bridge": _Bridge()})()

    with pytest.raises(ArchiveWorkflowDependenciesUnavailable, match="still preparing"):
        archive_workflow_dependency_context(owner, _entry("character/model/hero.pac", 100))


def test_legacy_workflow_context_preserves_existing_catalogue_maps() -> None:
    selected = _entry("character/model/hero.pac", 100)
    texture = _entry("character/texture/hero_d.dds", 200)
    path_index = {"character/texture/hero_d.dds": (texture,)}
    basename_index = {"hero_d.dds": (texture,)}
    owner = type(
        "Owner",
        (),
        {
            "archive_entries": (selected, texture),
            "archive_entries_by_normalized_path": path_index,
            "archive_entries_by_basename": basename_index,
        },
    )()

    context = archive_workflow_dependency_context(owner, selected)

    assert not context.remote
    assert context.selected_entry is selected
    assert context.entries == (selected, texture)
    assert context.entries_by_normalized_path is path_index
    assert context.entries_by_basename is basename_index
