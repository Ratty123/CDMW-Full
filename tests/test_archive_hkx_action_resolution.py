from __future__ import annotations

from pathlib import Path

from cdmw.models import ArchiveEntry, ArchiveModelTextureReference
from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin
from cdmw.ui.archive_browser.asset_family_dialog import ArchiveAssetFamilyDialogMixin
from cdmw.ui.archive_browser.asset_family_panel import ArchiveAssetFamilyPanelMixin


def _entry(path: str, offset: int = 1) -> ArchiveEntry:
    return ArchiveEntry(path, Path("0009/0.pamt"), Path("0009/0.paz"), offset, 1, 1, 0, 0)


class _HkxCandidateProbe(ArchiveBrowserActionMixin):
    def __init__(self, references: tuple[ArchiveModelTextureReference, ...]) -> None:
        self.references = references

    def _archive_asset_family_graph_for_entry(self, _entry: ArchiveEntry) -> object:
        raise AssertionError("HKX action state must not build an asset-family graph")

    def _current_archive_related_references_for_entry(
        self,
        _entry: ArchiveEntry,
    ) -> tuple[ArchiveModelTextureReference, ...]:
        return self.references

    @staticmethod
    def _attachment_package_entry_key(entry: ArchiveEntry) -> tuple[str, str, int]:
        return str(entry.pamt_path), entry.path, entry.offset


def test_hkx_candidates_use_direct_or_worker_resolved_entries_without_graph_io() -> None:
    model = _entry("character/model/body.pac")
    hkx = _entry("character/bin__/meshphysics/body.hkx", offset=2)
    reference = ArchiveModelTextureReference(reference_kind="physics", resolved_entry=hkx)
    probe = _HkxCandidateProbe((reference, reference))

    assert probe._archive_hkx_placement_candidates_for_entry(hkx) == (hkx,)
    assert probe._archive_hkx_placement_candidates_for_entry(model) == (hkx,)


class _TextureReferenceFlushProbe:
    archive_preview_request_id = 7
    pending_archive_texture_reference_update = (7, ("reference",), "graph")
    archive_asset_family_panel_requested = True

    def __init__(self) -> None:
        self.populated: tuple[object, object, bool] | None = None
        self.action_target = object()
        self.updated_with: object | None = None

    def _populate_archive_texture_reference_list(
        self,
        references: object,
        graph: object,
        *,
        enrich: bool,
    ) -> None:
        self.populated = references, graph, enrich

    def _archive_model_preview_controls_target(self) -> object:
        return self.action_target

    def _update_archive_model_action_controls(self, target: object) -> None:
        self.updated_with = target


def test_worker_resolved_references_refresh_hkx_action_state() -> None:
    probe = _TextureReferenceFlushProbe()

    ArchiveAssetFamilyPanelMixin._flush_archive_texture_reference_update(probe)

    assert probe.pending_archive_texture_reference_update is None
    assert probe.populated == (("reference",), "graph", False)
    assert probe.updated_with is probe.action_target


def test_worker_resolved_references_stay_deferred_until_asset_family_is_requested() -> None:
    probe = _TextureReferenceFlushProbe()
    probe.archive_asset_family_panel_requested = False

    ArchiveAssetFamilyPanelMixin._flush_archive_texture_reference_update(probe)

    assert probe.pending_archive_texture_reference_update == (7, ("reference",), "graph")
    assert probe.populated is None
    assert probe.updated_with is None


class _TimerProbe:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


class _TextureReferenceScheduleProbe:
    archive_preview_request_id = 11

    def __init__(self) -> None:
        self.archive_asset_family_panel_requested = False
        self.archive_texture_reference_update_timer = _TimerProbe()
        self.pending_archive_texture_reference_update = None
        self.current_archive_model_texture_references = []
        self.current_archive_asset_family_graph = None
        self.current_archive_family_member_rows = []
        self.action_updates = 0

    @staticmethod
    def _current_archive_entry() -> None:
        return None

    def _update_archive_texture_reference_action_controls(self) -> None:
        self.action_updates += 1


def test_asset_family_tree_population_timer_starts_only_after_user_request() -> None:
    probe = _TextureReferenceScheduleProbe()

    ArchiveAssetFamilyPanelMixin._schedule_archive_texture_reference_update(
        probe,
        ("reference",),
        None,
    )

    assert probe.pending_archive_texture_reference_update == (11, ("reference",), None)
    assert probe.current_archive_model_texture_references == ["reference"]
    assert probe.archive_texture_reference_update_timer.stops == 1
    assert probe.archive_texture_reference_update_timer.starts == 0

    probe.archive_asset_family_panel_requested = True
    ArchiveAssetFamilyPanelMixin._schedule_archive_texture_reference_update(
        probe,
        ("new-reference",),
        None,
    )

    assert probe.pending_archive_texture_reference_update == (11, ("new-reference",), None)
    assert probe.archive_texture_reference_update_timer.starts == 1
    assert probe.action_updates == 2


def test_stale_asset_family_result_is_not_published_before_panel_population() -> None:
    probe = _TextureReferenceScheduleProbe()

    ArchiveAssetFamilyPanelMixin._schedule_archive_texture_reference_update(
        probe,
        ("stale-reference",),
        None,
        request_id=10,
    )

    assert probe.pending_archive_texture_reference_update is None
    assert probe.current_archive_model_texture_references == []
    assert probe.archive_texture_reference_update_timer.stops == 0
    assert probe.archive_texture_reference_update_timer.starts == 0
    assert probe.action_updates == 0


class _VisibilityProbe:
    def __init__(self) -> None:
        self.visible = False

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)


class _SplitterProbe:
    def __init__(self) -> None:
        self.collapsible = True

    def setCollapsible(self, _index: int, collapsible: bool) -> None:
        self.collapsible = bool(collapsible)


class _AssetFamilyToggleProbe:
    archive_preview_request_id = 13

    def __init__(self) -> None:
        self.archive_asset_family_panel_requested = False
        self.pending_archive_texture_reference_update = (13, ("reference",), None)
        self.archive_texture_reference_update_timer = _TimerProbe()
        self.archive_texture_refs_group = _VisibilityProbe()
        self.archive_preview_content_splitter = _SplitterProbe()
        self.layout_refreshes = 0
        self.layout_schedules = 0
        self.action_updates = 0

    @staticmethod
    def _archive_has_asset_family_workspace() -> bool:
        return True

    def _refresh_archive_asset_family_panel_layout(self, *, prefer_default: bool) -> None:
        assert prefer_default is True
        self.layout_refreshes += 1

    def _schedule_archive_asset_family_panel_layout(self, *, prefer_default: bool) -> None:
        assert prefer_default is True
        self.layout_schedules += 1

    def _update_archive_texture_reference_action_controls(self) -> None:
        self.action_updates += 1


def test_asset_family_header_button_defers_then_toggles_the_inline_panel() -> None:
    probe = _AssetFamilyToggleProbe()

    ArchiveAssetFamilyDialogMixin._open_archive_asset_family_workspace_dialog(probe, True)

    assert probe.archive_asset_family_panel_requested is True
    assert probe.archive_texture_reference_update_timer.starts == 1
    assert probe.archive_texture_refs_group.visible is False

    probe.pending_archive_texture_reference_update = None
    ArchiveAssetFamilyDialogMixin._open_archive_asset_family_workspace_dialog(probe, True)

    assert probe.archive_texture_refs_group.visible is True
    assert probe.archive_preview_content_splitter.collapsible is False
    assert probe.layout_refreshes == 1
    assert probe.layout_schedules == 1

    ArchiveAssetFamilyDialogMixin._open_archive_asset_family_workspace_dialog(probe, False)

    assert probe.archive_asset_family_panel_requested is False
    assert probe.archive_texture_reference_update_timer.stops == 1
    assert probe.archive_texture_refs_group.visible is False
    assert probe.archive_preview_content_splitter.collapsible is True
