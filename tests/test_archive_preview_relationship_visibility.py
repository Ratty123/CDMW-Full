from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from cdmw.models import ArchiveEntry, ArchivePreviewResult
from cdmw.rendering.native_preview_core import NativePreviewCoreAttempt
from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin
from cdmw.ui.archive_browser.asset_family_dialog import ArchiveAssetFamilyDialogMixin
from cdmw.ui.archive_browser.asset_family_panel import ArchiveAssetFamilyPanelMixin
from cdmw.ui.archive_browser.reference_preview import ArchiveReferencePreviewMixin
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker


def _worker(tmp_path: Path, extension: str) -> tuple[ArchivePreviewWorker, ArchiveEntry]:
    selected = ArchiveEntry(f"assets/leaf{extension}", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 12, 12, 0, 0)
    sidecar = ArchiveEntry(f"assets/leaf{extension}.xml", tmp_path / "0.pamt", tmp_path / "0.paz", 12, 0, 0, 0, 0)
    worker = ArchivePreviewWorker(
        41, selected, None,
        {entry.path: [entry] for entry in (selected, sidecar)},
        {entry.basename: [entry] for entry in (selected, sidecar)},
        None, None, (), attach_preview_images=False,
    )
    return worker, sidecar


@pytest.mark.parametrize("extension", [".pam", ".dds", ".wav", ".bin", ".custom"])
@pytest.mark.parametrize("cached", [False, True])
def test_relationships_survive_generic_and_cached_previews(tmp_path: Path, monkeypatch, extension: str, cached: bool) -> None:
    worker, sidecar = _worker(tmp_path, extension)
    original = ArchivePreviewResult(status="info", title=worker.entry.basename)
    emitted = []
    worker.completed.connect(lambda request_id, result: emitted.append((request_id, result)))
    if cached:
        worker.full_preview_cache_key = "cached"
        worker.preview_cache_snapshot = {"cached": original}
    else:
        monkeypatch.setattr(worker, "_build_archive_preview_payload", lambda **_kwargs: original)
        monkeypatch.setattr(worker, "_try_native_preview_core", lambda: None)
    worker.run()

    assert len(emitted) == (2 if extension == ".pam" and not cached else 1)
    for request_id, result in emitted:
        assert request_id == 41
        assert sidecar in [ref.resolved_entry for ref in result.model_texture_references]
        assert sidecar.path in result.asset_family_graph.members
    assert not original.model_texture_references
    assert original.asset_family_graph is None


def test_failed_native_pam_keeps_relationships_and_cancellation_suppresses_publication(tmp_path: Path, monkeypatch) -> None:
    worker, sidecar = _worker(tmp_path, ".pam")
    worker.native_preview_core_enabled = True
    failure = NativePreviewCoreAttempt(status="unavailable", fallback_reason="synthetic decode failure")
    monkeypatch.setattr(worker, "_try_native_preview_core", lambda: failure)
    emitted = []
    worker.completed.connect(lambda _request_id, result: emitted.append(result))
    worker.run()
    assert len(emitted) == 1
    assert emitted[0].status == "error"
    assert sidecar in [ref.resolved_entry for ref in emitted[0].model_texture_references]

    from cdmw.workers import archive_preview_workers
    def cancelled_lookup(*_args, **_kwargs):
        worker.stop()
        return emitted[0].model_texture_references

    monkeypatch.setattr(archive_preview_workers, "build_archive_relationship_references", cancelled_lookup)
    worker.run()
    assert len(emitted) == 1


class _FamilyControls(ArchiveAssetFamilyPanelMixin, ArchiveAssetFamilyDialogMixin, ArchiveReferencePreviewMixin):
    _set_action_button_state = staticmethod(ArchiveBrowserActionMixin._set_action_button_state)

    def __init__(self, entry: ArchiveEntry, parent: QWidget) -> None:
        self.entry = entry
        self.shell = SimpleNamespace(worker_thread=None)
        self.archive_preview_request_id = 41
        self.archive_asset_family_panel_requested = False
        self.current_archive_model_texture_references = []
        self.current_archive_used_by_references = []
        self.current_archive_family_member_rows = []
        self.pending_archive_texture_reference_update = None
        self.archive_asset_family_cache = OrderedDict()
        self.archive_texture_reference_update_timer = QTimer(parent)
        self.archive_asset_family_button = QPushButton("Asset Family", parent)
        self.archive_asset_family_button.setCheckable(True)

    def _current_archive_entry(self):
        return self.entry


def test_relationship_delivery_makes_real_button_visible_and_rejects_stale_clear(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    worker, _sidecar = _worker(tmp_path, ".custom")
    result = worker._with_archive_relationships(ArchivePreviewResult(status="error", title="leaf.custom"))
    owner = _FamilyControls(worker.entry, parent)
    owner._update_archive_texture_reference_action_controls()
    assert owner.archive_asset_family_button.isHidden()

    owner._schedule_archive_texture_reference_update(result.model_texture_references, result.asset_family_graph, request_id=41)
    assert not owner.archive_asset_family_button.isHidden()
    assert owner.archive_asset_family_button.isEnabled()
    owner._schedule_archive_texture_reference_update((), None, request_id=40)
    assert not owner.archive_asset_family_button.isHidden()
    assert owner.current_archive_family_member_rows
    owner._schedule_archive_texture_reference_update((), None, request_id=41)
    assert owner.archive_asset_family_button.isHidden()
    parent.deleteLater()
    app.processEvents()
