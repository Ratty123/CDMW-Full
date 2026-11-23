"""Focused tests for Item Set & Browse-to-Editor bridge speedups."""
from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import QObject, Signal
import pytest

from cdmw.domain.archives.catalogue import ArchiveAssociationResult
from cdmw.domain.archives.catalogue_operations import PrepareEntriesResult, PrepareEntryResult
from cdmw.domain.archives.catalogue import ArchiveEntryRef
from cdmw.models import ArchiveEntry
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.services.mesh_item_set_editing import (
    lookup_item_set_browse_material_package,
    prepare_editable_item_set,
    register_item_set_browse_material_package,
)
from cdmw.services.mesh_preview_material_source import (
    bind_item_set_piece_from_preview_core_package,
    load_preview_core_set_package,
    unedited_preview_core_material_source,
)
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
from cdmw.ui.mesh_editor.item_set_preparation import (
    MAX_CONCURRENT_PREPARATION_SLOTS,
    MAX_PREPARED_CONTEXT_CACHE,
    ItemSetEditorPreparation,
    prepare_item_set_for_editor,
    switch_item_piece,
)
from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin
from tests.test_archive_remote_preview_dependencies import _CatalogueService, _dto
from tests.test_archive_remote_window_bridge import _app
from tests.test_mesh_item_set_references import _sources
from tests.test_mesh_rust_archive_texture_launch import _LaunchHarness, _Lease, _entry
from tests.test_rust_preview_production_cutover import _write_schema8_preview_core_fixture


# ---------------------------------------------------------------------------
# Fix 1: Signal-driven _wait_for_full_archive_preview + overlapped session load
# ---------------------------------------------------------------------------


class _SignalPreviewWorker(QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()


def test_wait_for_full_archive_preview_wakes_on_signal_without_polling(tmp_path: Path, monkeypatch) -> None:
    app = _app()
    entry = _entry(tmp_path)
    package, *_ = _write_schema8_preview_core_fixture(tmp_path / "pkg")
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_path"] = entry.path
    manifest["source_identity"] = {
        "normalized_path": entry.identity.normalized_path,
        "source_pamt": entry.identity.source_pamt,
        "paz_index": entry.identity.paz_index,
        "entry_offset": entry.identity.entry_offset,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (package / "net_materials.json").write_text(
        json.dumps({"resources": [{"resource_id": "texture:base", "path": "helmet_base.dds"}]}),
        encoding="utf-8",
    )

    worker = _SignalPreviewWorker()
    harness = _LaunchHarness(entry, package)
    harness.archive_preview_worker = worker
    harness.current_archive_preview_result = SimpleNamespace(
        preview_model="quick-model",
        dotnet_preview_package_path=str(package),
        quality_tier="quick",
    )
    poll_calls: list[int] = []
    monkeypatch.setattr(
        "cdmw.ui.mesh_editor.shell_bridge.QTimer.singleShot",
        lambda ms, cb: poll_calls.append(int(ms)),
    )

    harness._launch_archive_mesh_editor_for_entry(entry)
    assert harness.opened == []
    assert poll_calls == []  # connected directly to worker signals; no 250 ms poll

    # Interim fast emission keeps waiting without scheduling a 250 ms poll.
    harness.current_archive_preview_result = SimpleNamespace(
        preview_model="fast-model",
        dotnet_preview_package_path=str(package),
        quality_tier="fast",
    )
    worker.completed.emit(1, harness.current_archive_preview_result)
    assert harness.opened == []
    assert poll_calls == []

    # Full preview arrival opens immediately (~0 ms) on signal delivery.
    harness.current_archive_preview_result = SimpleNamespace(
        preview_model="full-model",
        dotnet_preview_package_path=str(package),
        quality_tier="full",
    )
    lease = _Lease()
    with patch(
        "cdmw.ui.mesh_editor.shell_bridge.acquire_dotnet_preview_package_cache_lease_for_path",
        return_value=lease,
    ):
        worker.completed.emit(1, harness.current_archive_preview_result)
    assert len(harness.opened) == 1
    assert harness.opened[0][1]["material_preview_model"] == "full-model"
    assert harness._mesh_editor_full_preview_wait is None
    assert getattr(harness, "_mesh_editor_full_preview_deadline_timer", None) is None
    worker.deleteLater()
    app.processEvents()


def test_wait_for_full_archive_preview_overlaps_session_load_and_passes_prepared_result(tmp_path: Path) -> None:
    from tests.test_mesh_pac_topology_serializer import _pac_fixture
    from tests.test_mesh_rust_authoring import _prepared_dds_entry

    app = _app()
    pac_bytes = _pac_fixture()
    entry = _prepared_dds_entry(tmp_path, "upper.pac", pac_bytes)
    package, *_ = _write_schema8_preview_core_fixture(tmp_path / "pkg")
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_path"] = entry.path
    manifest["source_identity"] = {
        "normalized_path": entry.identity.normalized_path,
        "source_pamt": entry.identity.source_pamt,
        "paz_index": entry.identity.paz_index,
        "entry_offset": entry.identity.entry_offset,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (package / "net_materials.json").write_text(
        json.dumps({"resources": [{"resource_id": "texture:base", "path": "helmet_base.dds"}]}),
        encoding="utf-8",
    )

    class _RealTab(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.mesh_editor_draft_root = tmp_path / "drafts"
            self.opened: list[tuple[object, dict[str, object]]] = []

        def open_archive_session(self, target: ArchiveEntry, **kwargs: object) -> None:
            self.opened.append((target, kwargs))

    worker = _SignalPreviewWorker()
    tab = _RealTab()
    harness = _LaunchHarness(entry, package)
    harness.mesh_editor_tab = tab
    harness.archive_preview_worker = worker
    harness.archive_entries_by_normalized_path = {entry.path.casefold(): (entry,)}
    harness.archive_entries_by_basename = {entry.basename.casefold(): (entry,)}
    harness.current_archive_preview_result = SimpleNamespace(
        preview_model="quick-model",
        dotnet_preview_package_path=str(package),
        quality_tier="quick",
    )

    harness._launch_archive_mesh_editor_for_entry(entry)
    # Wait for the overlapped MeshArchiveSessionLoadWorker to finish while Browse is still interim.
    for _ in range(200):
        app.processEvents()
        if getattr(harness, "_mesh_editor_preloaded_session", None) is not None:
            break
        threading.Event().wait(0.01)
    assert getattr(harness, "_mesh_editor_preloaded_session", None) is not None

    # Browse finishes its full preview -> open_archive_session receives the preloaded result.
    harness.current_archive_preview_result = SimpleNamespace(
        preview_model="full-model",
        dotnet_preview_package_path=str(package),
        quality_tier="full",
    )
    lease = _Lease()
    with patch(
        "cdmw.ui.mesh_editor.shell_bridge.acquire_dotnet_preview_package_cache_lease_for_path",
        return_value=lease,
    ):
        worker.completed.emit(1, harness.current_archive_preview_result)
    assert len(tab.opened) == 1
    prepared_result = tab.opened[0][1].get("prepared_result")
    assert prepared_result is not None
    assert prepared_result.mesh.path == entry.path
    prepared_result.service.close_edit_session(prepared_result.view.session_id, force_without_saving=True)
    # Ensure cleanup of preload thread completes cleanly.
    for _ in range(50):
        app.processEvents()
        if not getattr(harness, "_mesh_editor_preload_retained", set()):
            break
        threading.Event().wait(0.01)
    tab.deleteLater()
    worker.deleteLater()
    app.processEvents()


# ---------------------------------------------------------------------------
# Fix 2: Reuse Browse's conserved set material package for Item Sets
# ---------------------------------------------------------------------------


def _write_two_piece_set_package(root: Path, upper_entry: ArchiveEntry, lower_entry: ArchiveEntry, *, material_name: str) -> Path:
    package, *_ = _write_schema8_preview_core_fixture(root)
    dds_path = package / "helmet_base.dds"
    Image.new("RGBA", (4, 4), (120, 80, 40, 255)).save(dds_path)
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_path"] = upper_entry.path
    manifest["source_identity"] = {
        "normalized_path": upper_entry.identity.normalized_path,
        "source_pamt": upper_entry.identity.source_pamt,
        "paz_index": upper_entry.identity.paz_index,
        "entry_offset": upper_entry.identity.entry_offset,
    }
    base_batch = copy.deepcopy(manifest["batches"][0])
    base_batch["material_name"] = material_name
    base_batch["dds_textures"]["base"]["source_path"] = str(dds_path)
    base_batch["material_layers"][0]["diffuse_source"] = str(dds_path)
    upper_batch = copy.deepcopy(base_batch)
    upper_batch["index"] = 0
    upper_batch["editor_identity"] = {
        **upper_batch.get("editor_identity", {}),
        "source_model_path": upper_entry.path,
        "source_submesh_index": 0,
        "source_local_submesh_index": 0,
        "source_component_index": 0,
        "prefab_component": False,
        "context_component": False,
    }
    lower_batch = copy.deepcopy(base_batch)
    lower_batch["index"] = 1
    lower_batch["editor_identity"] = {
        **lower_batch.get("editor_identity", {}),
        "source_model_path": lower_entry.path,
        "source_submesh_index": 1,
        "source_local_submesh_index": 0,
        "source_component_index": 1,
        "prefab_component": True,
        "context_component": True,
    }
    manifest["batches"] = [upper_batch, lower_batch]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (package / "net_materials.json").write_text(
        json.dumps({"resources": [{"resource_id": "texture:base", "path": "helmet_base.dds"}]}),
        encoding="utf-8",
    )
    return package


def test_shell_bridge_retains_conserved_set_package_and_lease_for_edit_item_set(tmp_path: Path) -> None:
    upper = _entry(tmp_path, "upper.pac", offset=0)
    lower = _entry(tmp_path, "lower.pac", offset=64)
    set_package = _write_two_piece_set_package(tmp_path / "set_pkg", upper, lower, material_name="armor_mat")
    shell = _LaunchHarness(upper, set_package)
    upper_ctx = ArchiveWorkflowDependencyContext(upper, (upper,), {upper.path: (upper,)}, {upper.basename: (upper,)}, True)
    lower_ctx = ArchiveWorkflowDependencyContext(lower, (lower,), {lower.path: (lower,)}, {lower.basename: (lower,)}, True)
    lease = _Lease()
    with patch(
        "cdmw.ui.mesh_editor.shell_bridge.acquire_dotnet_preview_package_cache_lease_for_path",
        return_value=lease,
    ):
        shell._open_archive_mesh_editor_with_dependencies(
            upper,
            upper_ctx,
            item_set_contexts=(upper_ctx, lower_ctx),
            edit_item_set=True,
        )
    _, kwargs = shell.opened[0]
    # Single-file material fields stay empty so single-file priming never borrows combined owners.
    assert kwargs["material_package_path"] == ""
    assert kwargs["material_preview_model"] is None
    assert not kwargs["material_context_verified_for_rust"]
    # Browse's conserved set package and its lease are forwarded for prepare_editable_item_set.
    assert kwargs["item_set_material_package_path"] == str(set_package)
    assert kwargs["material_package_lease"] is lease


def test_prepare_editable_item_set_reuses_browse_set_package_with_per_piece_fallback(tmp_path: Path, monkeypatch) -> None:
    from cdmw.services import mesh_item_set_budget, mesh_preview_material_source
    from cdmw.workers import mesh_archive_refit_worker
    from tests.test_mesh_rust_authoring import _prepared_dds_entry

    source, service, controller, base_contexts = _sources(tmp_path)
    primary = service.capture_export_snapshot(controller.active_session_id)
    material_name = primary.mesh.submeshes[0].material
    upper_ctx, lower_ctx = base_contexts
    boots_entry = _prepared_dds_entry(tmp_path, "boots.pac", source)
    boots_ctx = ArchiveWorkflowDependencyContext(
        boots_entry, (boots_entry,), {boots_entry.path: (boots_entry,)}, {boots_entry.basename: (boots_entry,)}, True,
    )
    contexts = (upper_ctx, lower_ctx, boots_ctx)

    set_package = _write_two_piece_set_package(
        tmp_path / "browse_set",
        upper_ctx.selected_entry,
        lower_ctx.selected_entry,
        material_name=material_name,
    )

    fallback_calls: list[str] = []

    def fake_prepare_source(mesh, context, cache_root, stop_event):
        fallback_calls.append(context.selected_entry.path)
        return None

    def fake_refit_source(args, stop_event):
        entry = args["_archive_entry"]
        piece_snap = replace(primary, mesh=copy.deepcopy(primary.mesh), base_mesh=copy.deepcopy(primary.base_mesh))
        piece_snap.mesh.path = piece_snap.base_mesh.path = entry.path
        return {"_archive_snapshot": piece_snap}

    monkeypatch.setattr(mesh_preview_material_source, "prepare_item_set_material_source", fake_prepare_source)
    monkeypatch.setattr(mesh_archive_refit_worker, "prepare_archive_refit_source", fake_refit_source)
    monkeypatch.setattr(
        mesh_item_set_budget,
        "prepare_item_set_budget",
        lambda sources, root, identity, stop: mesh_item_set_budget.ItemSetBudget(
            frozenset(range(len(sources))), {}, None,
        ),
    )

    register_item_set_browse_material_package(service, controller.active_session_id, set_package)
    assert lookup_item_set_browse_material_package(service, controller.active_session_id) == str(set_package)
    try:
        mesh, set_context, *_rest = prepare_editable_item_set(
            service,
            controller.active_session_id,
            copy.deepcopy(primary.mesh),
            contexts,
            threading.Event(),
            lambda _msg: None,
            tmp_path / "session_root",
            None,
        )
        # upper.pac and lower.pac were bound directly from Browse's set package; ONLY boots.pac fell back.
        assert fallback_calls == ["boots.pac"]
        assert unedited_preview_core_material_source(mesh.submeshes[0]) is not None
        assert unedited_preview_core_material_source(mesh.submeshes[1]) is not None
        assert unedited_preview_core_material_source(mesh.submeshes[2]) is None
        # Each reused piece owns an active package lease.
        upper_lease = set_context.assets[0].preview_lease
        lower_lease = set_context.assets[1].preview_lease
        assert upper_lease is not None and upper_lease.lease.active
        assert lower_lease is not None and lower_lease[1].lease.active
        upper_lease.lease.release()
        lower_lease[1].lease.release()
    finally:
        register_item_set_browse_material_package(service, controller.active_session_id, None)
        assert lookup_item_set_browse_material_package(service, controller.active_session_id) == ""
        service.close_edit_session(controller.active_session_id, force_without_saving=True)


def test_bind_item_set_piece_basename_fallback_and_missing_dds_rollback(tmp_path: Path) -> None:
    upper = _entry(tmp_path, "upper.pac", offset=0)
    lower = _entry(tmp_path, "lower.pac", offset=64)
    set_package = _write_two_piece_set_package(tmp_path / "pkg", upper, lower, material_name="armor_mat")
    loaded = load_preview_core_set_package(set_package)
    assert loaded is not None
    try:
        # Unambiguous basename match when piece path differs in prefix.
        alt_lower = replace(lower, path="alt/dir/lower.pac")
        part = SimpleNamespace(material="armor_mat", preview_native_material_overrides={})
        mesh = SimpleNamespace(path=alt_lower.path, lod_levels=[], submeshes=[part])
        ctx = SimpleNamespace(selected_entry=alt_lower)
        retained = bind_item_set_piece_from_preview_core_package(mesh, ctx, loaded, threading.Event())
        assert retained is not None and retained.lease.active
        assert unedited_preview_core_material_source(part) is not None
        retained.lease.release()

        # Material mismatch refuses cleanly without mutating the part.
        wrong_part = SimpleNamespace(material="different_mat", preview_native_material_overrides={"keep": 1})
        wrong_mesh = SimpleNamespace(path=lower.path, lod_levels=[], submeshes=[wrong_part])
        assert bind_item_set_piece_from_preview_core_package(wrong_mesh, SimpleNamespace(selected_entry=lower), loaded, threading.Event()) is None
        assert wrong_part.preview_native_material_overrides == {"keep": 1}

        # Missing DDS triggers rollback and returns None so caller falls back cleanly.
        (set_package / "helmet_base.dds").unlink()
        missing_part = SimpleNamespace(material="armor_mat", preview_native_material_overrides={"orig": True})
        missing_mesh = SimpleNamespace(path=lower.path, lod_levels=[], submeshes=[missing_part])
        assert bind_item_set_piece_from_preview_core_package(missing_mesh, SimpleNamespace(selected_entry=lower), loaded, threading.Event()) is None
        assert missing_part.preview_native_material_overrides == {"orig": True}
        assert not hasattr(missing_part, "preview_texture_dds_path")
    finally:
        loaded.lease.release()


def test_bind_item_set_piece_accepts_the_archive_workers_prepared_textures(tmp_path: Path) -> None:
    """Browse's set package draws the archive worker's prepared DDS files, which live in
    the index store outside its lease, and names each texture by its archive path.

    Every piece used to be refused ("texture references were missing or outside the
    leased package"), so Open set in Mesh Editor ran a Preview Core job per piece
    (Demenissian Council Robes, 2026-11-23). A file that is really gone still refuses.
    """

    upper = _entry(tmp_path, "upper.pac", offset=0)
    lower = _entry(tmp_path, "lower.pac", offset=64)
    set_package = _write_two_piece_set_package(tmp_path / "pkg", upper, lower, material_name="armor_mat")
    prepared = tmp_path / "cache" / "index" / "g" / "generation" / "p" / "aa" / "aa11.dds"
    prepared.parent.mkdir(parents=True)
    (set_package / "helmet_base.dds").replace(prepared)
    manifest_path = set_package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for batch in manifest["batches"]:
        batch["dds_textures"]["base"]["source_path"] = str(prepared)
        batch["dds_textures"]["material_inputs"] = [{
            "slot": "base", "parameter_name": "_baseColorTexture", "source_path": str(prepared),
            "archive_path": "character/texture/armor_base.dds", "available": True,
            "direct_upload_candidate": True,
        }]
        batch["material_layers"][0]["diffuse_source"] = str(prepared)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = load_preview_core_set_package(set_package)
    assert loaded is not None
    try:
        part = SimpleNamespace(material="armor_mat", preview_native_material_overrides={})
        mesh = SimpleNamespace(path=lower.path, lod_levels=[], submeshes=[part])
        retained = bind_item_set_piece_from_preview_core_package(
            mesh, SimpleNamespace(selected_entry=lower), loaded, threading.Event())
        assert retained is not None, "the prepared texture outside the lease refused the piece"
        assert unedited_preview_core_material_source(part) is not None
        retained.lease.release()

        prepared.unlink()
        gone = SimpleNamespace(material="armor_mat", preview_native_material_overrides={"orig": True})
        gone_mesh = SimpleNamespace(path=lower.path, lod_levels=[], submeshes=[gone])
        assert bind_item_set_piece_from_preview_core_package(
            gone_mesh, SimpleNamespace(selected_entry=lower), loaded, threading.Event()) is None
        assert gone.preview_native_material_overrides == {"orig": True}
    finally:
        loaded.lease.release()


def test_rebase_reports_only_texture_files_that_are_missing(tmp_path: Path) -> None:
    from cdmw.domain.model_preview_materials import PreviewMaterialTextureInput
    from cdmw.services.mesh_rust_authoring import _rebase_rust_preview_texture_paths

    package = tmp_path / "package"
    package.mkdir()
    owned = package / "owned.dds"
    outside = tmp_path / "index" / "outside.dds"
    outside.parent.mkdir()
    for path in (owned, outside):
        path.write_bytes(b"DDS " + bytes(124))

    def rebase(source_dds_path: Path, **kwargs) -> str:
        item = PreviewMaterialTextureInput(slot_kind="base", source_texture_path="character/texture/robe.dds",
                                           source_dds_path=str(source_dds_path))
        mesh = SimpleNamespace(submeshes=[SimpleNamespace(preview_material_texture_inputs=(item,))], lod_levels=[])
        return _rebase_rust_preview_texture_paths(mesh, package, **kwargs)[1]

    # The archive path beside a package-owned file is the texture's identity, not a missing file.
    assert rebase(owned) == ""
    assert rebase(outside) != ""
    assert rebase(outside, tolerate_external_files=True) == ""
    assert rebase(tmp_path / "gone.dds", tolerate_external_files=True) != ""


# ---------------------------------------------------------------------------
# Fix 3: Allow Item Sets to use Browse's viewport / resident GPU texture reuse
# ---------------------------------------------------------------------------


def test_browse_edit_binding_reuses_viewport_for_shown_item_set(tmp_path: Path) -> None:
    upper = _entry(tmp_path, "upper.pac", offset=0)
    lower = _entry(tmp_path, "lower.pac", offset=64)
    other = _entry(tmp_path, "other.pac", offset=128)
    upper_ctx = SimpleNamespace(selected_entry=upper)
    lower_ctx = SimpleNamespace(selected_entry=lower)

    class _FakeSignal:
        def __init__(self) -> None:
            self.slots: list[object] = []

        def connect(self, slot: object) -> None:
            self.slots.append(slot)

    class _FakeBinding:
        def __init__(self) -> None:
            self.is_ended = False
            self.shown = 0

        def show_view_now(self) -> bool:
            self.shown += 1
            return True

        def end(self) -> None:
            self.is_ended = True

    class _Shell(MeshEditorShellBridgeMixin):
        def __init__(self) -> None:
            self.bound: list[object] = []
            self.live_edit = SimpleNamespace(
                moved_to_own_viewport=_FakeSignal(),
                edit_in_viewport=lambda b: self.bound.append(b),
            )
            self.mesh_editor_tab = SimpleNamespace(live_edit=self.live_edit)
            self.shown_entry = upper
            self.requested_entry = upper
            self.quality = "full"
            self.members = (upper, lower)
            self.archive = SimpleNamespace(
                _current_archive_entry=lambda: self.shown_entry,
                archive_preview_request_entry=self.requested_entry,
                current_archive_preview_result=SimpleNamespace(quality_tier="full"),
                archive_remote_bridge=SimpleNamespace(
                    item_set_members=(upper, lower),
                    item_set_contains=lambda e: e.identity in {upper.identity, lower.identity},
                ),
                begin_edit_in_place=lambda _entry: _FakeBinding(),
            )

        def _watch_documents_for_browse_edit(self) -> None:
            pass

    shell = _Shell()
    # Even when opening the set with lower.pac primary while Browse shows upper.pac of the same set:
    binding = shell._browse_edit_binding(
        lower,
        False,
        {"item_set_contexts": (lower_ctx, upper_ctx), "edit_item_set": True},
    )
    assert binding is not None
    assert binding.shown == 1
    assert shell.bound == [binding]

    # Refused while Browse only has an interim quick/fast preview.
    shell.archive.current_archive_preview_result = SimpleNamespace(quality_tier="quick")
    assert shell._browse_edit_binding(
        upper, True, {"item_set_contexts": (upper_ctx, lower_ctx), "edit_item_set": True},
    ) is None

    # Refused when Browse moved to a model outside the set.
    shell.archive.current_archive_preview_result = SimpleNamespace(quality_tier="full")
    shell.shown_entry = other
    shell.archive.archive_preview_request_entry = other
    assert shell._browse_edit_binding(
        upper, False, {"item_set_contexts": (upper_ctx, lower_ctx), "edit_item_set": True},
    ) is None

    # Refused when a member is not part of Browse's displayed item set.
    shell.shown_entry = upper
    shell.archive.archive_preview_request_entry = upper
    other_ctx = SimpleNamespace(selected_entry=other)
    assert shell._browse_edit_binding(
        upper, True, {"item_set_contexts": (upper_ctx, other_ctx), "edit_item_set": True},
    ) is None


# ---------------------------------------------------------------------------
# Fix 4: Concurrent ItemSetEditorPreparation + bounded cache + piece-switch cache
# ---------------------------------------------------------------------------


class _MockService(_CatalogueService):
    session_published = Signal(object)
    current_session = SimpleNamespace(session_id="session-a")


def _real_prepared(tmp_path: Path, dto) -> PrepareEntryResult:
    file_path = tmp_path / f"{dto.entry_id}_{Path(dto.path).name}"
    file_path.write_bytes(b"PAC-DATA")
    return PrepareEntryResult(
        ArchiveEntryRef(dto.session_id, dto.entry_id, dto.identity, dto.path),
        str(file_path),
        dto.original_size,
        f"sha-{dto.entry_id}",
        "prepared test source",
    )


def _complete_request(service, assoc_req_id: str, prep_req_id: str, model, tmp_path: Path | None = None) -> None:
    service.result_ready.emit(
        assoc_req_id,
        "find_association_candidates",
        ArchiveAssociationResult("session-a", model.entry_id, (), 0, False),
    )
    row = _real_prepared(tmp_path, model) if tmp_path is not None else PrepareEntryResult(
        ArchiveEntryRef(model.session_id, model.entry_id, model.identity, model.path),
        f"C:/cache/{model.entry_id}.pac",
        model.original_size,
        f"sha-{model.entry_id}",
        "prepared test source",
    )
    service.result_ready.emit(
        prep_req_id,
        "prepare_entry",
        PrepareEntriesResult("session-a", (row,), 1, 1, 40),
    )


def test_concurrent_item_set_preparation_dispatches_4_slots_and_preserves_order() -> None:
    _app()
    service = _MockService()
    # Mock _Service defaults to sequential (1 slot) to preserve mock test IDs;
    # explicit max_concurrency=4 (used automatically for real ArchiveCatalogueService) runs 4 slots in parallel.
    assert ItemSetEditorPreparation(service).max_concurrency == 1
    preparation = ItemSetEditorPreparation(service, max_concurrency=MAX_CONCURRENT_PREPARATION_SLOTS)
    assert preparation.max_concurrency == 4

    members = tuple(_dto(i, f"piece_{i}.pac") for i in range(1, 6))
    ready: list[tuple] = []
    preparation.ready.connect(ready.append)

    # Select piece_3 first: expected order is [piece_3, piece_1, piece_2, piece_4, piece_5].
    assert preparation.start(ArchiveCatalogueService.compatibility_entry(members[2]), members)
    # 4 concurrent association requests dispatched immediately!
    assert [req.entry_id for req, _gen in service.requests] == [3, 1, 2, 4]

    # Complete slot 2 (piece_2, association-3 -> prepare-5) FIRST, out of order!
    _complete_request(service, "association-3", "prepare-5", members[1])
    # Slot freed -> member 5 (piece_5, entry_id=5) is immediately dispatched!
    assert service.requests[-1][0].entry_id == 5
    # Complete remaining out of order: piece_4, piece_5, piece_1, piece_3.
    _complete_request(service, "association-4", "prepare-7", members[3])
    _complete_request(service, "association-6", "prepare-8", members[4])
    _complete_request(service, "association-2", "prepare-9", members[0])
    assert not ready
    _complete_request(service, "association-1", "prepare-10", members[2])
    assert len(ready) == 1 and not preparation.pending
    assert [ctx.selected_entry.path for ctx in ready[0]] == [
        "piece_3.pac", "piece_1.pac", "piece_2.pac", "piece_4.pac", "piece_5.pac",
    ]


def test_concurrent_item_set_preparation_failure_cancels_all_other_inflight_slots() -> None:
    _app()
    service = _MockService()
    preparation = ItemSetEditorPreparation(service, max_concurrency=4)
    members = tuple(_dto(i, f"piece_{i}.pac") for i in range(1, 5))
    failures: list[str] = []
    preparation.failed.connect(failures.append)

    assert preparation.start(ArchiveCatalogueService.compatibility_entry(members[0]), members)
    assert len(service.requests) == 4
    service.request_failed.emit("association-2", SimpleNamespace(message="Broken piece 2"))
    assert failures == ["Broken piece 2"]
    assert not preparation.pending
    # All 4 slots' requests were cancelled cleanly.
    assert set(service.cancelled) == {"association-1", "association-2", "association-3", "association-4"}


def test_real_catalogue_service_automatically_uses_4_concurrent_slots() -> None:
    _app()

    class _FakeClient(QObject):
        request_progress = Signal(str, object)
        request_batch = Signal(str, str, object)
        request_succeeded = Signal(str, str, object)
        request_failed = Signal(str, object)
        request_cancelled = Signal(str)
        state_changed = Signal(str)
        worker_crashed = Signal(str)
        worker_ready = Signal()

    client = _FakeClient()
    service = ArchiveCatalogueService(client)
    try:
        preparation = ItemSetEditorPreparation(service)
        assert preparation.max_concurrency == MAX_CONCURRENT_PREPARATION_SLOTS
    finally:
        service._watchdog.stop()
        service.deleteLater()
        client.deleteLater()


def test_prepared_context_cache_reuses_and_invalidates_and_switch_caches_pieces(tmp_path: Path) -> None:
    app = _app()
    service = _MockService()
    preparation = ItemSetEditorPreparation(service, max_concurrency=4)
    upper, lower = _dto(1, "upper.pac"), _dto(2, "lower.pac")
    ready: list[tuple] = []
    preparation.ready.connect(ready.append)

    assert preparation.start(ArchiveCatalogueService.compatibility_entry(upper), (upper, lower))
    _complete_request(service, "association-1", "prepare-3", upper, tmp_path)
    _complete_request(service, "association-2", "prepare-4", lower, tmp_path)
    assert len(ready) == 1
    first_request_count = len(service.requests)

    # Re-opening with lower selected first hits the bounded cache with ZERO backend requests!
    assert preparation.start(ArchiveCatalogueService.compatibility_entry(lower), (upper, lower))
    assert len(service.requests) == first_request_count
    app.processEvents()
    assert len(ready) == 2
    assert [ctx.selected_entry.path for ctx in ready[1]] == ["lower.pac", "upper.pac"]

    # Deleting a prepared file on disk invalidates that cache entry and fetches fresh.
    Path(ready[1][0].selected_entry.prepared_path).unlink()
    assert preparation.start(ArchiveCatalogueService.compatibility_entry(lower), (upper, lower))
    # Only lower (the missing file) is fetched; upper stayed cached!
    assert len(service.requests) == first_request_count + 1
    assert service.requests[-1][0].entry_id == lower.entry_id
    preparation.cancel()

    # Session change clears the entire cache.
    service.session_published.emit(SimpleNamespace(session_id="session-b"))
    assert len(preparation._context_cache) == 0

    # switch_item_piece seeds preparation cache and opens rotated contexts with 0 archive lookups.
    upper_entry = ArchiveCatalogueService.compatibility_entry(upper)
    lower_entry = ArchiveCatalogueService.compatibility_entry(lower)
    upper_entry.prepared_path = tmp_path / "u.pac"
    lower_entry.prepared_path = tmp_path / "l.pac"
    upper_entry.prepared_path.write_bytes(b"u")
    lower_entry.prepared_path.write_bytes(b"l")
    contexts = (
        ArchiveWorkflowDependencyContext(upper_entry, (upper_entry,), {upper_entry.path: (upper_entry,)}, {upper_entry.basename: (upper_entry,)}, True),
        ArchiveWorkflowDependencyContext(lower_entry, (lower_entry,), {lower_entry.path: (lower_entry,)}, {lower_entry.basename: (lower_entry,)}, True),
    )
    opened: list[tuple] = []
    # These stand for the set this preparation made in the new session, with no item scope.
    preparation._remember_emitted_scope(contexts)
    tab = SimpleNamespace(item_set_contexts=contexts, item_set_preparation=preparation)
    bridge = SimpleNamespace(item_set_members=(upper, lower), item_set_contains=lambda _e: True)
    shell = SimpleNamespace(
        mesh_editor_tab=tab,
        _shutting_down=False,
        archive=SimpleNamespace(archive_remote_bridge=bridge, archive_catalogue_service=service),
        _open_archive_mesh_editor_with_dependencies=lambda entry, deps, **kw: opened.append((entry, deps, kw)),
    )
    before_switch_reqs = len(service.requests)
    switch_item_piece(shell, 1)
    assert len(service.requests) == before_switch_reqs
    assert len(opened) == 1 and opened[0][0].path == "lower.pac"
    # Both piece contexts are now warm in preparation's bounded cache.
    assert len(preparation._context_cache) == 2

    # Subsequent prepare_item_set_for_editor reuses them with 0 backend lookups!
    assert prepare_item_set_for_editor(shell, lower_entry)
    assert len(service.requests) == before_switch_reqs
    app.processEvents()
    assert len(ready) == 3

    # Bounded LRU eviction never exceeds MAX_PREPARED_CONTEXT_CACHE.
    for idx in range(100, 100 + MAX_PREPARED_CONTEXT_CACHE + 10):
        dto = _dto(idx, f"extra_{idx}.pac")
        entry = ArchiveCatalogueService.compatibility_entry(dto)
        entry.prepared_path = tmp_path / f"extra_{idx}.pac"
        entry.prepared_path.write_bytes(b"x")
        ctx = ArchiveWorkflowDependencyContext(entry, (entry,), {entry.path: (entry,)}, {entry.basename: (entry,)}, True)
        preparation._remember_emitted_scope((ctx,))
        preparation.cache_contexts((ctx,), members=(dto,))
    assert len(preparation._context_cache) == MAX_PREPARED_CONTEXT_CACHE


def test_tab_session_runtime_forwards_set_package_and_releases_lease_on_close(tmp_path: Path, monkeypatch) -> None:
    from cdmw.services.mesh_service import MeshService
    from cdmw.workers.mesh_editor_aux_workers import MeshArchiveSessionLoadResult
    from tests.test_mesh_editor_direct_mode import _mesh
    from tests.test_mesh_rust_editor_selection import _tab

    app = _app()
    tab = _tab(tmp_path)
    monkeypatch.setattr(tab, "_ensure_standalone_live_stroke_dispatcher", lambda: None)
    monkeypatch.setattr("cdmw.ui.mesh_editor.tab.native_mesh_core_available", lambda: False)

    entry = _entry(tmp_path, "upper.pac")
    context = ArchiveWorkflowDependencyContext(entry, (entry,), {entry.path: (entry,)}, {entry.basename: (entry,)}, True)
    lease = _Lease()
    package_path = str(tmp_path / "set_pkg")

    loaded_ref: list[tuple[MeshService, str]] = []

    def fake_start_load(request_id, load_entry, **_kwargs):
        mesh = _mesh(two_parts=False)
        mesh.path = load_entry.path
        svc = MeshService()
        view = svc.open_edit_session(mesh, mode="edit")
        loaded_ref.append((svc, view.session_id))
        tab._handle_archive_session_loaded(
            request_id,
            MeshArchiveSessionLoadResult(service=svc, view=view, mesh=mesh, source_sha256="a" * 64),
        )

    monkeypatch.setattr(tab, "_start_archive_session_load_when_indexes_ready", fake_start_load)
    try:
        # Verify survival across queued close first.
        with patch.object(tab, "close_standalone_session", return_value=False):
            tab.open_archive_session(
                entry,
                archive_dependencies=context,
                item_set_contexts=(context,),
                edit_item_set=True,
                item_set_material_package_path=package_path,
                material_package_lease=lease,
            )
        assert tab.archive_session_open_pending["item_set_material_package_path"] == package_path
        assert lease.active

        tab._resume_queued_archive_session_open()
        app.processEvents()
        assert len(loaded_ref) == 1
        svc, session_id = loaded_ref[0]
        assert lease.active
        assert lookup_item_set_browse_material_package(svc, session_id) == package_path

        tab.close_standalone_session()
        app.processEvents()
        assert not lease.active
        assert lookup_item_set_browse_material_package(svc, session_id) == ""
        assert tab.item_set_material_package_path == ""
    finally:
        tab.deleteLater()
        app.processEvents()


def test_selection_change_during_preview_wait_discards_preloaded_session(tmp_path: Path) -> None:
    app = _app()
    entry = _entry(tmp_path, "upper.pac")
    other = _entry(tmp_path, "other.pac", offset=64)
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "manifest.json").write_text(json.dumps({"source_path": entry.path, "batches": []}), encoding="utf-8")
    (package / "net_materials.json").write_text(json.dumps({"resources": []}), encoding="utf-8")

    closed_sessions: list[str] = []
    fake_result = SimpleNamespace(
        service=SimpleNamespace(
            close_edit_session=lambda sid, force_without_saving=False: closed_sessions.append(sid),
        ),
        view=SimpleNamespace(session_id="preloaded-sid"),
    )
    worker = _SignalPreviewWorker()
    harness = _LaunchHarness(entry, package)
    harness.archive_preview_worker = worker
    harness.current_archive_preview_result = SimpleNamespace(
        preview_model="quick", dotnet_preview_package_path=str(package), quality_tier="quick",
    )
    harness._wait_for_full_archive_preview(entry, entry.identity)
    harness._mesh_editor_preloaded_session = {
        "key": (entry.identity, "", entry.path.casefold()),
        "result": fake_result,
    }
    harness.entry = other
    worker.finished.emit()
    app.processEvents()
    assert harness._mesh_editor_full_preview_wait is None
    assert harness._mesh_editor_preloaded_session is None
    assert closed_sessions == ["preloaded-sid"]
    worker.deleteLater()
    app.processEvents()


def test_full_preview_wait_handles_worker_signals_on_the_ui_thread() -> None:
    """The preview worker emits on its own QThread; the wait's handler (which may open
    the Mesh Editor) must still run on the UI thread."""

    import time as _time

    from PySide6.QtCore import QThread
    from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin

    app = _app()
    ui_thread = QThread.currentThread()

    class _Harness(QObject, MeshEditorShellBridgeMixin):
        def __init__(self) -> None:
            QObject.__init__(self)
            self.archive = SimpleNamespace(archive_preview_worker=_SignalPreviewWorker())
            self.handled: list[tuple[bool, object]] = []

        def _handle_full_archive_preview_signal(self, wait_token: int, *, terminal: bool = False) -> None:
            self.handled.append((terminal, QThread.currentThread()))

        def _check_full_archive_preview_wait(self) -> None:
            pass

    harness = _Harness()
    worker = harness.archive.archive_preview_worker
    wait = {"token": 1, "deadline": _time.monotonic() + 30}
    assert harness._connect_full_archive_preview_signals(wait)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(lambda: (worker.completed.emit(1, None), worker.finished.emit()))
    thread.start()
    deadline = _time.monotonic() + 5
    while len(harness.handled) < 2 and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.005)
    thread.quit()
    thread.wait(2000)
    harness._mesh_editor_full_preview_wait = wait
    harness._disconnect_full_archive_preview_wait()
    timer = getattr(harness, "_mesh_editor_full_preview_deadline_timer", None)
    if timer is not None:
        timer.stop()
    assert [terminal for terminal, _thread in harness.handled] == [False, True]
    assert all(handled_thread is ui_thread for _terminal, handled_thread in harness.handled)



def test_contexts_prepared_for_one_item_scope_are_not_reused_for_another(tmp_path: Path) -> None:
    """Two variants can share PAC files but pick other prefabs: a set opened for item A
    must not hand its dependency contexts to item B."""

    _app()
    preparation = ItemSetEditorPreparation(_MockService(), max_concurrency=4)
    upper, lower = _dto(1, "upper.pac"), _dto(2, "lower.pac")
    contexts = []
    for dto in (upper, lower):
        entry = ArchiveCatalogueService.compatibility_entry(dto)
        entry.prepared_path = tmp_path / Path(dto.path).name
        entry.prepared_path.write_bytes(b"PAC")
        contexts.append(ArchiveWorkflowDependencyContext(
            entry, (entry,), {entry.path: (entry,)}, {entry.basename: (entry,)}, True))
    scope_a = (("item_a",), (11,))
    scope_b = (("item_b",), (22,))

    # Nothing this preparation emitted: nothing is known about their scope, so nothing is seeded.
    assert preparation.cache_contexts(contexts, members=(upper, lower)) == 0
    # The open set was prepared for item A; Browse now scopes item B.
    preparation._preferred_prefab_stems, preparation._scope_entry_ids = scope_a
    preparation._remember_emitted_scope(tuple(contexts))
    # Then a set for item B was prepared (new context objects) but its open was refused,
    # so the tab still holds A's contexts.
    other = tuple(SimpleNamespace(selected_entry=context.selected_entry) for context in contexts)
    preparation._preferred_prefab_stems, preparation._scope_entry_ids = scope_b
    preparation._remember_emitted_scope(other)
    assert preparation.cache_contexts(
        contexts, members=(upper, lower), preferred_prefab_stems=scope_b[0], scope_entry_ids=scope_b[1],
    ) == 2
    assert preparation._cached_context_for(upper, *scope_b) is None
    assert preparation._cached_context_for(upper, *scope_a) is contexts[0]
    assert preparation._cached_context_for(lower, *scope_a) is contexts[1]
    # A piece switch hands the same contexts back in another order: still A's scope.
    preparation._context_cache.clear()
    assert preparation.cache_contexts(tuple(reversed(contexts)), members=(upper, lower)) == 2
    assert preparation._cached_context_for(lower, *scope_b) is None
