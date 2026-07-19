from __future__ import annotations

from pathlib import Path

from cdmw.models import ArchiveEntry, AssetFamilyGraph, AssetFamilyMember, AttachmentPlacementEvidence
from cdmw.ui.archive_browser.attachment_donor_picker_dialog import (
    _attachment_donor_catalog_scope_entries,
    _attachment_donor_dependencies,
    _prepared_attachment_donor_candidate,
)
from cdmw.ui.archive_browser.attachment_icons import ArchiveAttachmentIconMixin
from cdmw.ui.archive_browser.attachment_package import ArchiveAttachmentPackageMixin
from cdmw.ui.archive_browser.attachment_plan import _attachment_placement_dependency_snapshot
from cdmw.ui.archive_browser.attachment_placement_diff_dialog import _attachment_dialog_dependencies
from cdmw.ui.archive_browser.attachment_safe_placement_dialog import _attachment_safe_placement_dependencies
from cdmw.ui.archive_browser.attachment_socket_editor import _attachment_socket_editor_dependencies
from cdmw.ui.archive_browser.attachment_visual_context import ArchiveAttachmentVisualContextMixin
from cdmw.ui.archive_browser.attachment_visual_core import ArchiveAttachmentVisualCoreMixin
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


def test_attachment_graph_entries_remap_members_and_evidence_to_prepared_candidates(tmp_path: Path) -> None:
    prepared_target = _entry("character/model/weapon.pac", 100, prepared_path=tmp_path / "weapon.pac")
    prepared_prefab = _entry("character/prefab/weapon.prefab", 200, prepared_path=tmp_path / "weapon.prefab")
    snapshot = _snapshot(prepared_target, prepared_prefab)

    class _Owner(ArchiveAttachmentPackageMixin):
        archive_remote_bridge = _Bridge(snapshot)

        def _find_archive_entry_by_virtual_path(self, _path: str) -> ArchiveEntry:
            raise AssertionError("attachment graph touched the legacy virtual-path lookup")

        @property
        def archive_entries_by_basename(self) -> object:
            raise AssertionError("attachment graph touched the legacy basename index")

    selected = _entry("character/model/weapon.pac", 100)
    unprepared_prefab = _entry("character/prefab/weapon.prefab", 200)
    graph = AssetFamilyGraph(
        member_rows=(AssetFamilyMember(resolved_entry=unprepared_prefab),),
        attachment_evidence=(AttachmentPlacementEvidence(prefab_path=unprepared_prefab.path),),
    )

    resolved = ArchiveAttachmentPackageMixin._attachment_package_graph_entries(_Owner(), selected, graph)

    assert resolved == [prepared_target, prepared_prefab]


def test_attachment_placement_snapshot_uses_one_bounded_prepared_candidate_set(tmp_path: Path) -> None:
    prepared_target = _entry("character/model/weapon.pac", 300, prepared_path=tmp_path / "weapon.pac")
    prepared_donor = _entry("character/model/donor.pac", 400, prepared_path=tmp_path / "donor.pac")
    snapshot = _snapshot(prepared_target, prepared_donor)
    owner = type("Owner", (), {"archive_remote_bridge": _Bridge(snapshot)})()

    target, donor, entries_by_path, entries_by_basename = _attachment_placement_dependency_snapshot(
        owner,
        _entry("character/model/weapon.pac", 300),
        _entry("character/model/donor.pac", 400),
    )

    assert target is prepared_target
    assert donor is prepared_donor
    assert entries_by_path is snapshot.entries_by_normalized_path
    assert entries_by_basename is snapshot.entries_by_basename


def test_attachment_donor_picker_uses_only_bounded_prepared_candidates(tmp_path: Path) -> None:
    prepared_target = _entry("character/model/weapon.pac", 500, prepared_path=tmp_path / "weapon.pac")
    prepared_donor = _entry("character/model/donor.pac", 600, prepared_path=tmp_path / "donor.pac")
    prepared_icon = _entry("ui/icon/donor.dds", 700, prepared_path=tmp_path / "donor.dds")
    snapshot = _snapshot(prepared_target, prepared_donor, prepared_icon)

    class _Owner:
        archive_remote_bridge = _Bridge(snapshot)

        @property
        def archive_sidecar_entries_by_texture_path(self) -> object:
            raise AssertionError("donor picker touched the legacy sidecar path index")

        @property
        def archive_sidecar_entries_by_texture_basename(self) -> object:
            raise AssertionError("donor picker touched the legacy sidecar basename index")

        @staticmethod
        def _archive_asset_catalog_row_values(row: object, key: str) -> tuple[str, ...]:
            return tuple(row.get(key, ()))

    resolved = _attachment_donor_dependencies(_Owner(), _entry("character/model/weapon.pac", 500))

    assert resolved is not None
    target, dependencies, prepared_by_identity, sidecars_by_path, sidecars_by_basename = resolved
    assert target is prepared_target
    assert sidecars_by_path == {}
    assert sidecars_by_basename == {}
    scoped, primary_count, related_count = _attachment_donor_catalog_scope_entries(
        _Owner(),
        {
            "pac_files": ("character/model/donor.pac",),
            "icon_paths": ("ui/icon/donor.dds",),
        },
        dependencies,
    )
    assert scoped == [prepared_donor, prepared_icon]
    assert (primary_count, related_count) == (2, 0)
    assert _prepared_attachment_donor_candidate(
        prepared_by_identity,
        _entry("character/model/donor.pac", 600),
    ) is prepared_donor
    assert _prepared_attachment_donor_candidate(
        prepared_by_identity,
        _entry("character/model/outside.pac", 800),
    ) is None


def test_attachment_diff_dialog_resolves_paths_from_bounded_prepared_context(tmp_path: Path) -> None:
    prepared_target = _entry("character/model/weapon.pac", 900, prepared_path=tmp_path / "weapon.pac")
    prepared_prefab = _entry("character/prefab/weapon.prefab", 1000, prepared_path=tmp_path / "weapon.prefab")
    snapshot = _snapshot(prepared_target, prepared_prefab)

    class _Owner:
        archive_remote_bridge = _Bridge(snapshot)

        @property
        def archive_entries(self) -> object:
            raise AssertionError("attachment diff touched the legacy entry catalogue")

        @property
        def archive_entries_by_basename(self) -> object:
            raise AssertionError("attachment diff touched the legacy basename index")

    dependencies = _attachment_dialog_dependencies(_Owner(), _entry("character/model/weapon.pac", 900))

    assert dependencies is not None
    assert dependencies.selected_entry is prepared_target
    assert dependencies.entry_for_path("character/prefab/weapon.prefab") is prepared_prefab


def test_attachment_visual_helpers_remap_graph_and_body_models_from_bounded_context(tmp_path: Path) -> None:
    prepared_target = _entry("character/prefab/weapon.prefab", 1100, prepared_path=tmp_path / "weapon.prefab")
    prepared_model = _entry("character/model/weapon.pac", 1200, prepared_path=tmp_path / "weapon.pac")
    prepared_body = _entry("character/nude/cd_phm_00_nude_10_0001.pac", 1300, prepared_path=tmp_path / "body.pac")
    snapshot = _snapshot(prepared_target, prepared_model, prepared_body)

    class _Owner(ArchiveAttachmentVisualCoreMixin):
        archive_remote_bridge = _Bridge(snapshot)

        @property
        def archive_entries(self) -> object:
            raise AssertionError("attachment visual helper touched the legacy entry catalogue")

        @property
        def archive_entries_by_basename(self) -> object:
            raise AssertionError("attachment visual helper touched the legacy basename index")

    owner = _Owner()
    target = _entry("character/prefab/weapon.prefab", 1100)
    graph = AssetFamilyGraph(
        attachment_evidence=(AttachmentPlacementEvidence(model_path="character/model/weapon.pac"),),
    )

    assert owner._attachment_visual_model_entry(target, graph) is prepared_model
    assert owner._attachment_visual_body_context_model_entry(target) is prepared_body


def test_attachment_icons_and_socket_paths_use_bounded_prepared_indexes(tmp_path: Path) -> None:
    prepared_target = _entry("character/model/weapon.pac", 1400, prepared_path=tmp_path / "weapon.pac")
    prepared_prefab = _entry("character/prefab/weapon.prefab", 1500, prepared_path=tmp_path / "weapon.prefab")
    prepared_socket = _entry("character/socket/weapon.sockets.xml", 1600, prepared_path=tmp_path / "weapon.sockets.xml")
    prepared_icon = _entry("ui/icon/itemicon_weapon.dds", 1700, prepared_path=tmp_path / "itemicon_weapon.dds")
    snapshot = _snapshot(prepared_target, prepared_prefab, prepared_socket, prepared_icon)

    class _Owner(ArchiveAttachmentIconMixin, ArchiveAttachmentPackageMixin):
        archive_remote_bridge = _Bridge(snapshot)
        archive_item_asset_catalog = (
            {
                "pac_files": ("character/model/weapon.pac",),
                "model_stems": ("weapon",),
                "icon_paths": ("ui/icon/itemicon_weapon.dds",),
            },
        )

        @staticmethod
        def _archive_asset_catalog_row_values(row: object, key: str) -> list[str]:
            return list(row.get(key, ()))

        def _resolve_archive_asset_catalog_path_candidates(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("attachment icon lookup touched the legacy catalogue resolver")

        def _find_archive_entry_by_virtual_path(self, _path: str) -> object:
            raise AssertionError("attachment socket lookup touched the legacy path resolver")

        @property
        def archive_entries_by_basename(self) -> object:
            raise AssertionError("attachment lookup touched the legacy basename index")

    owner = _Owner()
    target = _entry("character/model/weapon.pac", 1400)
    prefab = _entry("character/prefab/weapon.prefab", 1500)
    graph = AssetFamilyGraph(
        attachment_evidence=(
            AttachmentPlacementEvidence(
                prefab_path=prefab.path,
                socket_file_path=prepared_socket.path,
            ),
        ),
    )

    assert owner._attachment_package_item_icon_entries(target, graph) == [prepared_icon]
    assert owner._attachment_package_socket_entries_for_prefab(graph, prefab) == [prepared_socket]


def test_attachment_editor_context_helpers_do_not_touch_legacy_catalogues(tmp_path: Path) -> None:
    prepared_target = _entry("character/model/weapon.pac", 1800, prepared_path=tmp_path / "weapon.pac")
    prepared_donor = _entry("character/model/donor.pac", 1900, prepared_path=tmp_path / "donor.pac")
    prepared_socket = _entry("character/socket/weapon.sockets.xml", 2000, prepared_path=tmp_path / "weapon.sockets.xml")
    snapshot = _snapshot(prepared_target, prepared_donor, prepared_socket)

    class _Owner(ArchiveAttachmentVisualContextMixin):
        archive_remote_bridge = _Bridge(snapshot)

        @property
        def archive_entries_by_normalized_path(self) -> object:
            raise AssertionError("attachment editor touched the legacy path index")

        @property
        def archive_entries_by_basename(self) -> object:
            raise AssertionError("attachment editor touched the legacy basename index")

        @property
        def archive_sidecar_entries_by_texture_path(self) -> object:
            raise AssertionError("attachment editor touched the legacy sidecar path index")

        @property
        def archive_sidecar_entries_by_texture_basename(self) -> object:
            raise AssertionError("attachment editor touched the legacy sidecar basename index")

    owner = _Owner()
    target = _entry("character/model/weapon.pac", 1800)
    donor = _entry("character/model/donor.pac", 1900)
    socket = _entry("character/socket/weapon.sockets.xml", 2000)

    visual_entry = owner._attachment_visual_find_archive_entry_by_path_or_basename(target, socket.path)
    socket_dependencies = _attachment_socket_editor_dependencies(owner, socket)
    placement_dependencies = _attachment_safe_placement_dependencies(owner, target, donor)

    assert visual_entry is prepared_socket
    assert socket_dependencies is not None and socket_dependencies.selected_entry is prepared_socket
    assert placement_dependencies is not None
    assert placement_dependencies[0] is prepared_target
    assert placement_dependencies[1] is prepared_donor
    assert placement_dependencies[3:] == ({}, {})
