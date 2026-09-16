from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from cdmw.core.archive_asset_family import build_archive_asset_family_graph
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference, ArchivePreviewResult, ModelPreviewRenderSettings
from cdmw.rendering.native_preview_core import NativePreviewCoreAttempt
from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin
from cdmw.ui.archive_browser.asset_family_dialog import ArchiveAssetFamilyDialogMixin
from cdmw.ui.archive_browser.asset_family_panel import ArchiveAssetFamilyPanelMixin
from cdmw.ui.archive_browser.mesh_dds_preview import ArchiveMeshDdsPreviewMixin
from cdmw.ui.archive_browser.mesh_direct_patch import ArchiveMeshDirectPatchMixin
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
    _current_archive_related_references_for_entry = ArchiveMeshDdsPreviewMixin._current_archive_related_references_for_entry
    _prompt_archive_mesh_related_file_selection = ArchiveMeshDirectPatchMixin._prompt_archive_mesh_related_file_selection

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


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("textured", [False, True])
def test_partial_pac_preview_discovers_declared_assets_for_export_without_editor(
    tmp_path: Path, monkeypatch, cached: bool, textured: bool,
) -> None:
    payloads = (
        ("character/model/body_a.pac", b"PAR "),
        ("character/bin/body_a.hkx", b"HKX"),
        ("character/identityskeleton.pab", b"PAB"),
        (
            "character/modelproperty/body_a.pac_xml",
            b'<Material><ResourceReferencePath_ITexture value="character/texture/shared/surface_d.dds"/>'
            b'<ResourceReferencePath_ITexture value="character/texture/shared/surface_n.dds"/></Material>',
        ),
        ("character/texture/shared/surface_d.dds", b"DDS "),
        ("character/texture/shared/surface_n.dds", b"DDS "),
    )
    entries = []
    paz_path = tmp_path / "0.paz"
    with paz_path.open("wb") as stream:
        for path, payload in payloads:
            entries.append(ArchiveEntry(
                path, tmp_path / "0.pamt", paz_path, stream.tell(), len(payload), len(payload), 0, 0,
            ))
            stream.write(payload)
    selected, physics, skeleton, sidecar, base, normal = entries
    original_refs = tuple(
        ArchiveModelTextureReference(
            reference_name=entry.basename,
            resolved_archive_path=entry.path,
            resolved_entry=entry,
            resolution_status="resolved",
            reference_kind=kind,
            relation_group=group,
            usage_count=1,
        )
        for entry, kind, group in (
            (physics, "physics", "Physics / Collision"),
            (skeleton, "skeleton", "Skeleton / Rig"),
        )
    )
    if textured:
        # Two authored materials may use the same DDS. Keep both records and
        # their metadata when adding the other declared dependencies.
        original_refs += tuple(
            ArchiveModelTextureReference(
                reference_name=base.basename,
                resolved_archive_path=base.path,
                resolved_entry=base,
                resolution_status="resolved",
                material_name=material,
                shader_family="skin",
                texture_role="base_color",
                semantic_label="Authored base colour",
                usage_count=3,
            )
            for material in ("body", "detail")
        )
    original_graph = build_archive_asset_family_graph(selected, original_refs)
    original_members = original_graph.members
    original = ArchivePreviewResult(
        status="ok", title=selected.basename,
        model_texture_references=original_refs, asset_family_graph=original_graph,
    )
    worker = ArchivePreviewWorker(
        41, selected, None,
        {entry.path: [entry] for entry in entries},
        {entry.basename: [entry] for entry in entries},
        None, None, (), attach_preview_images=False,
        render_settings=ModelPreviewRenderSettings(use_textures_by_default=textured),
        native_preview_dependency_entries=entries,
        native_preview_dependency_entries_complete=True,
    )
    emitted = []
    worker.completed.connect(lambda _request_id, result: emitted.append(result))
    if cached:
        worker.full_preview_cache_key = "partial"
        worker.preview_cache_snapshot = {"partial": original}
    else:
        monkeypatch.setattr(worker, "_try_native_preview_core", lambda: None)
        monkeypatch.setattr(worker, "_build_archive_preview_payload", lambda **_kwargs: original)
    worker.run()

    expected_paths = {entry.path for entry in entries[1:]}
    assert emitted
    for result in emitted:
        references = result.model_texture_references
        assert {ref.resolved_archive_path for ref in references} == expected_paths
        assert all(ref.resolved_entry is not None for ref in references)
        assert references[:len(original_refs)] == original_refs
        assert len(references) == len(expected_paths) + int(textured)
        assert expected_paths <= set(result.asset_family_graph.members)
        assert {row.path for row in result.asset_family_graph.member_rows if row.resolved_entry} >= expected_paths
    assert worker.render_settings.use_textures_by_default is textured
    assert original.model_texture_references == original_refs
    assert original_graph.members == original_members
    assert [ref.usage_count for ref in original_refs] == ([1, 1, 3, 3] if textured else [1, 1])
    assert worker._with_archive_relationships(emitted[-1]) is emitted[-1]

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    owner = _FamilyControls(selected, parent)
    owner._schedule_archive_texture_reference_update(
        emitted[-1].model_texture_references, emitted[-1].asset_family_graph, request_id=41,
    )
    picker_references = []
    owner._prompt_archive_reference_selection = lambda **kwargs: picker_references.extend(kwargs["references"])
    owner._prompt_archive_mesh_related_file_selection(
        selected, title="Export Referenced Files With FBX", intro_text="", confirm_button_text="Export FBX",
    )
    assert {ref.resolved_archive_path for ref in picker_references} == expected_paths
    assert owner.archive_asset_family_button.isEnabled()
    parent.deleteLater()
    app.processEvents()
