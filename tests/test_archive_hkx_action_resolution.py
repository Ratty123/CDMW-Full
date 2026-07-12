from __future__ import annotations

from pathlib import Path

from cdmw.models import ArchiveEntry, ArchiveModelTextureReference
from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin
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
