from __future__ import annotations

from dataclasses import replace
import hashlib
from io import BytesIO
import os
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QSettings, QThread, QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.mesh_archive_results import ADDED_RESULT_NOTE, EDITED_RESULT_NOTE, MeshArchiveResult, prepare_mesh_archive_result
from cdmw.ui.archive_browser.edited_results import ArchiveEditedResultsMixin
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext, archive_workflow_dependency_context
from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveSessionLoadWorker
from cdmw.workers.mesh_editor_workers import MeshDirectOutputResult, MeshDirectOutputWorker
from tests.test_mesh_editor_pab_resolution import _pab
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request, _candidate_reference


def _entry(root, path, data):
    root.mkdir(parents=True, exist_ok=True)
    source = root / (hashlib.sha256(path.encode()).hexdigest()[:10] + Path(path).name)
    source.write_bytes(data)
    pamt, paz = root / "0.pamt", root / "0.paz"
    if not pamt.exists():
        pamt.write_bytes(b"owned original index")
        paz.write_bytes(b"owned original archive")
    return ArchiveEntry(path, pamt, paz, 0, len(data), len(data), 0, 0,
        prepared_path=source, prepared_sha256=hashlib.sha256(data).hexdigest(), prepared_size=len(data))


def _context(entry, entries):
    paths, basenames = {}, {}
    for candidate in entries:
        paths.setdefault(candidate.path.casefold(), []).append(candidate)
        basenames.setdefault(candidate.basename.casefold(), []).append(candidate)
    return ArchiveWorkflowDependencyContext(entry, tuple(entries), paths, basenames, remote=True)


@pytest.fixture
def edited(tmp_path):
    source, service, editor = _open_exact_session(tmp_path / "session", resolved_rig=True)
    editor.apply_candidate({**_request(editor, "transaction_request", 1),
                            "candidate": _candidate_reference(editor, request_id=1, first_x=0.4)})
    editor.finish(_request(editor, "finish_request", 2))
    entry = _entry(tmp_path / "sources", "owned-rust-exact.pac", source)
    entry.content_analysis_json_path = tmp_path / "stale-original-analysis.json"
    entry.content_analysis_text_path = tmp_path / "stale-original-analysis.txt"
    entry.content_analysis_version = "original-source"
    from PIL import Image
    texture = BytesIO()
    Image.new("RGBA", (4, 4), (30, 180, 90, 255)).save(texture, format="DDS")
    dependencies = [entry, *(_entry(tmp_path / "sources", name, data) for name, data in (
        ("owned-rust-exact.pac_xml", b'<Root><SkinnedMeshMaterialWrapper _subMeshName="target"><Material><Vector Name="_parameters">'
            b'<MaterialParameterTexture _name="_diffuseTexture" Index="0"><ResourceReferencePath_ITexture _path="character/texture/armor.dds"/>'
            b'</MaterialParameterTexture></Vector></Material></SkinnedMeshMaterialWrapper></Root>'),
        ("character/texture/armor.dds", texture.getvalue()),
        ("character/model/armor.pab", _pab(tuple(0xA2000000 + index for index in range(8)))),
        ("character/physics/armor.hkx", b"source physics bytes"),
    ))]
    snapshot = service.capture_export_snapshot(editor.authoritative_session_id)
    try:
        yield service, snapshot, entry, tuple(dependencies)
    finally:
        if not editor.closed:
            editor.cancel()
        service.close_edit_session(editor.authoritative_session_id, force_without_saving=True)


def _prepare(edited, root, *, stop_event=None):
    service, snapshot, entry, dependencies = edited
    return prepare_mesh_archive_result(service, snapshot, entry,
        ((entry.identity, dependencies),), root, stop_event=stop_event)


def test_result_reopens_edited_game_bytes_and_retains_source_channels_and_dependencies(edited, tmp_path):
    service, snapshot, original_entry, dependencies = edited
    result = _prepare(edited, tmp_path / "results")
    output = read_archive_entry_data(result.assets[0])[0]
    parsed = parse_pac(output, original_entry.path)
    original = parse_pac(snapshot.original_data, original_entry.path)
    assert parsed.submeshes[0].vertices[0][0] == pytest.approx(0.4, abs=2e-5)
    for field in ("name", "material", "uvs", "bone_indices", "bone_weights", "shader_masks"):
        assert getattr(parsed.submeshes[0], field) == getattr(original.submeshes[0], field), field
    assert result.assets[0].identity == original_entry.identity
    assert result.assets[0].prepared_sha256 != original_entry.prepared_sha256
    assert result.assets[0].content_analysis_json_path is None
    assert result.assets[0].content_analysis_text_path is None
    assert result.assets[0].content_analysis_version == ""
    copied = {entry.path: entry for entry in result.entries}
    for source in dependencies[1:]:
        assert read_archive_entry_data(copied[source.path])[0] == source.prepared_path.read_bytes()
        assert copied[source.path].prepared_path.is_relative_to(result.root)
        # Evicting the old prepared cache cannot remove these dependencies.
        source.prepared_path.unlink()
        assert copied[source.path].prepared_path.is_file()
    assert original_entry.pamt_path.read_bytes() == b"owned original index"
    assert original_entry.paz_file.read_bytes() == b"owned original archive"
    context = _context(result.assets[0], result.entries)
    worker = MeshArchiveSessionLoadWorker(1, result.assets[0],
        archive_entries_by_normalized_path=context.entries_by_normalized_path,
        archive_entries_by_basename=context.entries_by_basename)
    loaded, errors = [], []
    worker.loaded.connect(lambda _id, value: loaded.append(value))
    worker.error.connect(lambda _id, message: errors.append(message))
    worker.run()
    assert not errors
    assert len(loaded) == 1
    reopened = loaded[0]
    try:
        assert reopened.mesh.submeshes[0].vertices[0][0] == pytest.approx(0.4, abs=2e-5)
        assert reopened.service._session(reopened.view.session_id).archive_refit_context is None
        assert reopened.service._session(reopened.view.session_id).replacement_state is None
        assert reopened.source_sha256 == result.assets[0].prepared_sha256
        assert reopened.source_skeleton is not None
        assert reopened.source_skeleton.bone_count == 8
    finally:
        reopened.service.close_edit_session(reopened.view.session_id, force_without_saving=True)


def test_saved_material_context_protects_direct_and_nested_textures_from_cache_pruning(edited, tmp_path):
    from cdmw.core.temp_cache import prune_app_temp_cache
    from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput
    from cdmw.services.mesh_archive_results import capture_mesh_archive_material_context

    _service, _snapshot, entry, _dependencies = edited
    root = tmp_path / "cache"
    unit = root / "archive_preview_cache" / "materials"
    unit.mkdir(parents=True)
    base, mask = unit / "base.dds", unit / "layer-mask.png"
    base.write_bytes(b"owned base texture")
    mask.write_bytes(b"owned layer mask")
    preview = SimpleNamespace(path=entry.path, meshes=(SimpleNamespace(
        source_submesh_index=0, preview_texture_dds_path=str(base),
        preview_material_texture_inputs=(PreviewMaterialTextureInput(
            source_dds_path=str(base), material_parameters=(PreviewMaterialParameterInput(
                parameter_name="layerMask", texture_path=str(mask),
            ),),
        ),),
    ),))
    saved = capture_mesh_archive_material_context(entry, preview)
    try:
        assert saved.package_lease is None and saved.resource_leases
        report = prune_app_temp_cache(max_bytes=1, target_bytes=0, root=root)
        assert report.removed_units == 0 and base.is_file() and mask.is_file()
        source = saved.preview_model.submeshes[0]
        assert source.preview_material_texture_inputs[0].material_parameters[0].texture_path == str(mask)
    finally:
        for pin in saved.resource_leases:
            pin.release()
    report = prune_app_temp_cache(max_bytes=1, target_bytes=0, root=root)
    assert report.removed_units == 1 and not unit.exists()


@pytest.mark.parametrize("changed_materials", [False, True])
def test_rebuilt_material_sidecars_replace_earlier_preview_authority(edited, tmp_path, monkeypatch, changed_materials):
    from cdmw.domain.mesh.replacement import ReplacementFile
    from cdmw.services.mesh_archive_results import capture_mesh_archive_material_context

    service, snapshot, entry, dependencies = edited
    preview = SimpleNamespace(path=entry.path, meshes=(SimpleNamespace(
        source_submesh_index=0, preview_texture_dds_path=str(dependencies[2].prepared_path),
        preview_texture_tint=(1.0, 0.0, 0.0),
    ),))
    materials = capture_mesh_archive_material_context(entry, preview)
    rebuilt, report = service.rebuild_result_from_snapshot(snapshot)
    sidecar = dependencies[1]
    changed = ReplacementFile(sidecar.path, b"owned updated material sidecar" if changed_materials
                              else read_archive_entry_data(sidecar)[0])
    monkeypatch.setattr(service, "rebuild_result_from_snapshot", lambda _snapshot: (
        SimpleNamespace(data=rebuilt.data, companion_files=(changed,)), report,
    ))
    result = prepare_mesh_archive_result(service, snapshot, entry, ((entry.identity, dependencies),),
        tmp_path / "results", material_contexts=(materials,))
    assert result.material_contexts == (() if changed_materials else (materials,))
    assert read_archive_entry_data(next(item for item in result.entries if item.path == sidecar.path))[0] == changed.data
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    tab.standalone_controller = SimpleNamespace(mesh_service=service, active_session_id=snapshot.session_id)
    tab.standalone_output_request_id = 8
    tab.standalone_archive_material_preview_model = preview
    tab.archive_material_context_verified_for_rust = True
    tab.archive_material_context_source_identity = entry.identity
    opened = []
    monkeypatch.setattr(tab, "open_archive_session", lambda target, **kwargs: opened.append(kwargs))
    try:
        tab._continue_from_prepared_archive_result(8, result)
        assert len(opened) == 1
        assert ("material_preview_model" in opened[0]) is not changed_materials
    finally:
        tab.standalone_controller = None
        tab.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("failure", ["cancelled", "dependency_changed", "mesh_changed", "wrong_source"])
def test_incomplete_or_stale_results_are_never_published(edited, tmp_path, failure, monkeypatch):
    service, snapshot, entry, dependencies = edited
    stop = threading.Event()
    if failure == "cancelled":
        original_rebuild = service.rebuild_result_from_snapshot
        def cancel_during_rebuild(value):
            rebuilt = original_rebuild(value)
            stop.set()
            return rebuilt
        monkeypatch.setattr(service, "rebuild_result_from_snapshot", cancel_during_rebuild)
    elif failure == "dependency_changed":
        dependencies[-1].prepared_path.write_bytes(b"changed")
    elif failure == "mesh_changed":
        service._session(snapshot.session_id).revision += 1
    else:
        entry.prepared_sha256 = "0" * 64
    with pytest.raises((RunCancelled, ValueError, RuntimeError)):
        _prepare(edited, tmp_path / "results", stop_event=stop)
    root = tmp_path / "results"
    assert not root.exists() or not list(root.iterdir())
    assert entry.paz_file.read_bytes() == b"owned original archive"


def test_archive_result_worker_captures_validated_revision_and_context(edited, tmp_path):
    service, snapshot, entry, dependencies = edited
    completed, errors = [], []
    worker = MeshDirectOutputWorker(7, service, snapshot.session_id, entry,
        kind="archive_result", output_path=tmp_path / "results",
        expected_mesh_revision=snapshot.mesh_revision,
        archive_dependency_sources=((entry.identity, dependencies),))
    worker.completed.connect(lambda request, result: completed.append((request, result)))
    worker.error.connect(lambda _request, message: errors.append(message))
    worker.run()
    assert not errors
    assert len(completed) == 1 and completed[0][0] == 7
    assert isinstance(completed[0][1].archive_result, MeshArchiveResult)


def test_combined_refit_keeps_each_asset_and_dependency_context(tmp_path, monkeypatch):
    from tests.test_mesh_archive_refit import _load_pair, _edit_both
    from PIL import Image

    app = QApplication.instance() or QApplication([])
    textures = (tmp_path / "body.dds", tmp_path / "armor.dds")
    for path, color in zip(textures, ((200, 30, 20), (20, 30, 200)), strict=True):
        Image.new("RGBA", (4, 4), (*color, 255)).save(path)
    source, service, editor, primary, armor, _loaded = _load_pair(tmp_path, texture_paths=textures)
    try:
        _edit_both(editor)
        editor.finish(_request(editor, "finish_request", 31))
        snapshot = service.capture_export_snapshot(editor.authoritative_session_id)
        # The fixture's source locations remain intact; prepared contexts avoid archive decoding.
        sources = []
        for entry in (primary, armor):
            prepared = _entry(tmp_path / "prepared", entry.path, source)
            prepared = replace(entry, prepared_path=prepared.prepared_path,
                prepared_sha256=prepared.prepared_sha256, prepared_size=len(source))
            sources.append((entry.identity, (prepared,)))
        # Exercise the real request capture too: both assets use local material
        # slot zero, but must keep their different source bindings and owners.
        contexts = {identity: _context(next(item for item in entries if item.identity == identity), entries)
                    for identity, entries in sources}
        session = service._session(snapshot.session_id)
        session.archive_refit_context = replace(session.archive_refit_context, assets=tuple(
            replace(asset, preview_lease=SimpleNamespace(lease=None, archive_dependencies=contexts[asset.entry.identity]))
            for asset in session.archive_refit_context.assets))
        tab = MeshEditorTab(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
        tab.standalone_controller = SimpleNamespace(mesh_service=service, active_session_id=snapshot.session_id)
        tab.archive_session_dependencies = contexts[primary.identity]
        tab.standalone_archive_material_preview_model = session.archive_refit_context.assets[0].source.mesh
        tab.archive_material_context_verified_for_rust = True
        tab.archive_material_context_source_identity = primary.identity
        captured = []
        monkeypatch.setattr(tab, "_mesh_output_target", lambda: primary)
        monkeypatch.setattr(tab, "_standalone_export_validation_ok", lambda: True)
        monkeypatch.setattr(tab, "_standalone_action_worker_active", lambda: False)
        monkeypatch.setattr(tab, "_start_mesh_direct_output_worker", lambda *args, **kwargs: captured.append(kwargs))
        try:
            tab._start_archive_browser_result_requested()
            assert len(captured) == 1
            result = prepare_mesh_archive_result(service, snapshot, primary,
                captured[0]["archive_dependency_sources"], tmp_path / "results",
                material_contexts=captured[0]["archive_material_sources"])
        finally:
            tab.standalone_controller = None
            tab.deleteLater()
            app.processEvents()
        materials = {context.source_identity: context for context in result.material_contexts}
        assert set(materials) == {primary.identity, armor.identity}
        for asset, texture in zip((primary, armor), textures, strict=True):
            assert materials[asset.identity].preview_model.submeshes[0].preview_texture_dds_path == str(texture)
        assert {entry.path for entry in result.assets} == {primary.path, armor.path}
        assert [parse_pac(read_archive_entry_data(entry)[0], entry.path).submeshes[0].vertices[0][0]
                for entry in result.assets] == pytest.approx([0.4, 0.7], abs=2e-5)
        # Editing the armor alone in a second pass must still package the fitted body.
        from cdmw.services.mesh_service import MeshService
        next_service = MeshService()
        mesh = next_service.load_mesh_bytes(read_archive_entry_data(result.assets[1])[0], armor.path, run_roundtrip=True)
        next_view = next_service.open_edit_session(mesh, mode="edit")
        try:
            worker = MeshDirectOutputWorker(2, next_service, next_view.session_id, result.assets[1],
                kind="loose_mod", output_path=tmp_path / "final-mod", manager_profile="dmm",
                inherited_archive_outputs=tuple(item for item in result.entries if item.prepared_note == EDITED_RESULT_NOTE))
            errors = []
            worker.error.connect(lambda _id, message: errors.append(message))
            worker.run()
            assert not errors
            for asset in result.assets:
                assert (tmp_path / "final-mod" / asset.path).read_bytes() == read_archive_entry_data(asset)[0]
        finally:
            next_service.close_edit_session(next_view.session_id, force_without_saving=True)
    finally:
        editor.cancel()
        service.close_edit_session(editor.authoritative_session_id, force_without_saving=True)


@pytest.mark.parametrize("button_name", ["AddtoArchiveBrowser", "Continueeditingmodifiedmesh"])
def test_accepted_result_button_reaches_tab_handler(tmp_path, button_name):
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    messages = []
    tab.status_message_requested.connect(lambda message, _error: messages.append(message))
    tab.standalone_workspace.setEnabled(True)
    button = tab.standalone_native_host_frame.findChild(QPushButton, "MeshEditorRustResult" + button_name)
    try:
        assert button is not None
        button.setEnabled(True)
        button.click()
        assert messages == ["Open an archive mesh before creating a Mesh Editor output."]
    finally:
        tab.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("with_materials", [False, True])
def test_browser_results_keep_original_catalogue_and_open_with_explicit_context(edited, tmp_path, with_materials):
    app = QApplication.instance() or QApplication([])
    result = _prepare(edited, tmp_path / "results")
    if with_materials:
        from cdmw.services.mesh_archive_results import capture_mesh_archive_material_context
        from cdmw.services.preview_rendering_service import acquire_dotnet_preview_package_cache_lease_for_path

        package = tmp_path / "materials"
        package.mkdir()
        texture = package / "source.dds"
        texture.write_bytes(b"owned source texture")
        original_pin = acquire_dotnet_preview_package_cache_lease_for_path(package)
        preview = SimpleNamespace(path=result.assets[0].path, meshes=(SimpleNamespace(
            source_submesh_index=0, preview_texture_dds_path=str(texture),
            preview_texture_tint=(0.2, 0.6, 0.3), preview_pac_material_owner_slot_index=4,
        ),))
        material = capture_mesh_archive_material_context(result.assets[0], preview, package)
        result = replace(result, material_contexts=(material,))
        original_pin.release()  # Closing the original editor must not unpin the result.
        assert material.package_lease.active
    calls = []
    class Browser(ArchiveEditedResultsMixin, QWidget):
        pass
    browser = Browser()
    browser.shell = SimpleNamespace(_activate_tool_widget=lambda widget: calls.append(widget),
        _launch_archive_mesh_editor_for_entry=lambda entry: calls.append(entry))
    browser.archive = browser
    browser.archive_package_root_edit = SimpleNamespace(text=lambda: "original/game/root")
    catalogue = (edited[2],)
    browser.archive_entries = catalogue
    browser._build_archive_edited_results()
    try:
        browser.add_mesh_editor_result(result)
        context = archive_workflow_dependency_context(browser, result.assets[0])
        assert context.selected_entry.prepared_sha256 == result.assets[0].prepared_sha256
        assert len(context.entries) == len(result.entries)
        assert browser.edited_result_context(edited[2]) is None
        assert browser.archive_entries is catalogue
        assert browser.archive_package_root_edit.text() == "original/game/root"
        browser.archive_edited_results_group.findChild(QPushButton, "ArchiveOpenEditedResult").click()
        assert calls[-1] is context.selected_entry
        opened = []
        class Shell(MeshEditorShellBridgeMixin):
            def _prepare_mesh_editor_archive_launch(self, entry):
                return True
            def _activate_tool_widget(self, tab):
                pass
            def set_status_message(self, *args, **kwargs):
                pass
            def _defer_rust_mesh_editor_for_archive_textures(self, entry):
                pytest.fail("An edited result must not use the original preview selection")
        shell = Shell()
        shell.archive = browser
        shell.mesh_editor_tab = SimpleNamespace(open_archive_session=lambda entry, **kw: opened.append((entry, kw)))
        shell._launch_archive_mesh_editor_for_entry(context.selected_entry)
        assert opened[0][0] is context.selected_entry
        assert opened[0][1]["archive_dependencies"] is context
        if with_materials:
            for _ in range(2):
                arguments = opened[-1][1]
                assert arguments["material_preview_model"].submeshes[0].preview_texture_tint == (0.2, 0.6, 0.3)
                assert arguments["material_preview_model"].submeshes[0].preview_pac_material_owner_slot_index == 4
                assert arguments["material_context_verified_for_rust"]
                assert arguments["material_source_identity"] == context.selected_entry.identity
                pin = arguments["material_package_lease"]
                assert pin is not material.package_lease and pin.active
                pin.release()  # Closing a reopened editor also leaves the result usable.
                assert material.package_lease.active and texture.is_file()
                shell._launch_archive_mesh_editor_for_entry(context.selected_entry)
            opened[-1][1]["material_package_lease"].release()
        else:
            assert opened == [(context.selected_entry, {"archive_dependencies": context})]
    finally:
        browser.archive_edited_results_group.deleteLater()
        browser.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("continue_editing", [False, True])
def test_completion_rejects_changed_session_revision_and_request(edited, tmp_path, monkeypatch, continue_editing):
    app = QApplication.instance() or QApplication([])
    prepared = _prepare(edited, tmp_path / "results")
    service, snapshot, _entry_value, _dependencies = edited
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    tab.standalone_controller = SimpleNamespace(mesh_service=service, active_session_id=snapshot.session_id)
    tab.standalone_output_request_id = 4
    published = []
    opened = []
    monkeypatch.setattr(tab, "open_archive_session", lambda entry, **kwargs: opened.append((entry, kwargs)))
    tab.archive_result_ready.connect(published.append)
    result = MeshDirectOutputResult("archive_result", prepared.root, archive_result=prepared)
    try:
        tab._handle_mesh_direct_output_completed(3, result, continue_editing=continue_editing)
        assert not published and not opened
        service._session(snapshot.session_id).revision += 1
        tab._handle_mesh_direct_output_completed(4, result, continue_editing=continue_editing)
        assert not published and not opened
        service._session(snapshot.session_id).revision = snapshot.mesh_revision
        tab._handle_mesh_direct_output_completed(4, result, continue_editing=continue_editing)
        if continue_editing:
            assert not published
            assert opened[0][0] is prepared.assets[0]
            assert opened[0][1]["archive_dependencies"].entries == prepared.entries
        else:
            assert published == [prepared] and not opened
    finally:
        tab.standalone_controller = None
        tab.deleteLater()
        app.processEvents()


def test_generated_companions_remain_additions_in_later_output(edited, tmp_path, monkeypatch):
    service, snapshot, entry, _dependencies = edited
    extra = _entry(tmp_path / "extra", "character/texture/private.dds", b"retained generated DDS")
    extra = replace(extra, prepared_note=ADDED_RESULT_NOTE, flags=0x20)
    worker = MeshDirectOutputWorker(1, service, snapshot.session_id, entry, kind="loose_mod",
        output_path=tmp_path / "mod", inherited_archive_outputs=(extra,))
    captured, errors = [], []
    def output(requests, metadata, report, *, additions=()):
        captured.extend(additions)
        return MeshDirectOutputResult("loose_mod", tmp_path / "mod")
    monkeypatch.setattr(worker, "_write_loose_mod", output)
    worker.error.connect(lambda _id, message: errors.append(message))
    worker.run()
    assert not errors
    assert len(captured) == 1
    assert (captured[0].path, captured[0].payload_data, captured[0].flags) == (extra.path, b"retained generated DDS", 0x20)


def test_add_result_request_captures_source_context_before_worker_start(edited, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    service, snapshot, entry, entries = edited
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    tab.standalone_controller = SimpleNamespace(mesh_service=service, active_session_id=snapshot.session_id)
    tab.archive_session_dependencies = _context(entry, entries)
    calls = []
    monkeypatch.setattr(tab, "_mesh_output_target", lambda: entry)
    monkeypatch.setattr(tab, "_standalone_export_validation_ok", lambda: True)
    monkeypatch.setattr(tab, "_standalone_action_worker_active", lambda: False)
    monkeypatch.setattr(tab, "_start_mesh_direct_output_worker", lambda *args, **kwargs: calls.append((args, kwargs)))
    try:
        tab._start_archive_browser_result_requested()
        assert calls[0][0] == ("archive_result", entry)
        captured = calls[0][1]["archive_dependency_sources"]
        assert captured[0][0] == entry.identity
        assert captured[0][1] == entries
        assert captured[0][1][0] is not entry
        assert calls[0][1]["output_path"].is_relative_to(tmp_path)
    finally:
        tab.standalone_controller = None
        tab.deleteLater()
        app.processEvents()


def test_part_exclusion_is_baked_into_reopened_game_asset(tmp_path):
    from tests.test_static_mesh_replacer_preview import _minimal_two_part_pac_original
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_service import MeshService
    from cdmw.services.mesh_replacement_import import initial_replacement_state, set_part_inclusion

    data, _mesh = _minimal_two_part_pac_original()
    raw = bytearray(data)
    for part in parse_mesh(data, "replacement.pac").submeshes:
        for offset in part.source_vertex_offsets:
            raw[offset + 28] = 255
    data = bytes(raw)
    service = MeshService()
    mesh = service.load_mesh_bytes(data, "character/model/replacement.pac", run_roundtrip=True)
    view = service.open_edit_session(mesh, mode="edit")
    entry = _entry(tmp_path / "source", mesh.path, data)
    try:
        snapshot = service.capture_export_snapshot(view.session_id)
        state = initial_replacement_state(snapshot)
        set_part_inclusion(service, snapshot, (state.parts[0].part_id,), False)
        result = prepare_mesh_archive_result(service, service.capture_export_snapshot(view.session_id), entry,
            ((entry.identity, (entry,)),), tmp_path / "results")
        parsed = parse_mesh(read_archive_entry_data(result.assets[0])[0], entry.path)
        # Exact output keeps descriptor slots but suppresses the excluded draw.
        assert max(max(point[axis] for point in parsed.submeshes[0].vertices)
                   - min(point[axis] for point in parsed.submeshes[0].vertices) for axis in range(3)) < 0.001
        assert parsed.submeshes[1].vertices == snapshot.mesh.submeshes[1].vertices
        assert service.working_mesh(view.session_id).submeshes[0].vertices == snapshot.mesh.submeshes[0].vertices
    finally:
        service.close_edit_session(view.session_id, force_without_saving=True)


@pytest.mark.parametrize("continue_editing", [False, True])
def test_result_button_runs_worker_and_delivers_complete_result_on_ui_thread(edited, tmp_path, monkeypatch, continue_editing):
    app = QApplication.instance() or QApplication([])
    service, snapshot, entry, entries = edited
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    tab.standalone_controller = SimpleNamespace(mesh_service=service, active_session_id=snapshot.session_id)
    tab.archive_session_dependencies = _context(entry, entries)
    tab.standalone_export_validation_revision = snapshot.mesh_revision
    tab.standalone_workspace.setEnabled(True)
    from cdmw.services.preview_rendering_service import acquire_dotnet_preview_package_cache_lease_for_path
    package = tmp_path / "materials"
    package.mkdir()
    texture = package / "body.dds"
    texture.write_bytes(b"owned body texture")
    tab.standalone_archive_material_preview_model = SimpleNamespace(path=entry.path, meshes=(SimpleNamespace(
        source_submesh_index=0, preview_texture_dds_path=str(texture), preview_texture_tint=(0.1, 0.4, 0.7),
    ),))
    tab.archive_material_context_package_path = str(package)
    tab.archive_material_context_package_lease = acquire_dotnet_preview_package_cache_lease_for_path(package)
    tab.archive_material_context_verified_for_rust = True
    tab.archive_material_context_source_identity = entry.identity
    monkeypatch.setattr(tab, "_mesh_output_target", lambda: entry)
    monkeypatch.setattr(tab, "_standalone_export_validation_ok", lambda: True)
    monkeypatch.setattr(tab, "_standalone_action_worker_active", lambda: False)
    monkeypatch.setattr(tab, "_wait_for_dotnet_export_updates", lambda _timeout: True)
    published, opened, errors = [], [], []
    loop = QEventLoop()
    def ready(result):
        published.append((result, QThread.currentThread()))
    tab.archive_result_ready.connect(ready)
    def open_next(entry, **kwargs):
        assert not tab._mesh_direct_output_busy()
        assert kwargs["material_context_verified_for_rust"]
        assert kwargs["material_preview_model"].submeshes[0].preview_texture_tint == (0.1, 0.4, 0.7)
        kwargs["material_package_lease"].release()
        opened.append((entry, kwargs["archive_dependencies"], QThread.currentThread()))
    monkeypatch.setattr(tab, "open_archive_session", open_next)
    tab.status_message_requested.connect(lambda message, error: errors.append(message) if error else None)
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: loop.quit() if (opened or published) and tab.standalone_output_thread is None else None)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    suffix = "Continueeditingmodifiedmesh" if continue_editing else "AddtoArchiveBrowser"
    button = tab.standalone_native_host_frame.findChild(QPushButton, "MeshEditorRustResult" + suffix)
    try:
        button.setEnabled(True)
        button.click()
        worker_thread = tab.standalone_output_thread
        assert worker_thread is not None and worker_thread is not app.thread()
        timer.start()
        timeout.start(10_000)
        loop.exec()
        assert not errors
        if continue_editing:
            assert not published
            assert len(opened) == 1 and opened[0][2] is app.thread()
            assert opened[0][0].prepared_path.is_file()
            assert parse_pac(read_archive_entry_data(opened[0][0])[0], entry.path).submeshes[0].vertices[0][0] == pytest.approx(0.4, abs=2e-5)
            assert opened[0][1].selected_entry is opened[0][0]
        else:
            assert len(published) == 1
            assert published[0][1] is app.thread()
            assert published[0][0].assets[0].prepared_path.is_file()
            materials = published[0][0].material_contexts
            assert len(materials) == 1 and materials[0].package_lease.active
            assert materials[0].preview_model.submeshes[0].preview_texture_tint == (0.1, 0.4, 0.7)
        assert tab.standalone_output_thread is None
    finally:
        timer.stop()
        timeout.stop()
        worker = tab.standalone_output_worker
        if worker is not None:
            worker.stop()
        thread = tab.standalone_output_thread
        if thread is not None:
            thread.quit()
            assert thread.wait(2_000)
        tab.standalone_controller = None
        tab._replace_archive_material_context_package_lease(None)
        tab.deleteLater()
        app.processEvents()


def test_continue_pending_during_output_retirement_is_dropped_on_close(edited, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    service, snapshot, _entry_value, _entries = edited
    prepared = _prepare(edited, tmp_path / "results")
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    tab.standalone_controller = SimpleNamespace(mesh_service=service, active_session_id=snapshot.session_id)
    tab.standalone_output_request_id = 9
    monkeypatch.setattr(tab, "_mesh_direct_output_busy", lambda: True)
    opened = []
    monkeypatch.setattr(tab, "open_archive_session", lambda *args, **kwargs: opened.append(args))
    try:
        tab._continue_from_prepared_archive_result(9, prepared)
        assert not opened
        tab._cancel_mesh_direct_output_worker(invalidate_result=True)
        tab.standalone_controller = None
        loop = QEventLoop()
        QTimer.singleShot(30, loop.quit)
        loop.exec()
        assert not opened
        assert service.session_view(snapshot.session_id).revision == snapshot.mesh_revision
    finally:
        tab.standalone_controller = None
        tab.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("material_context", ["current", "other_archive", "unverified"])
def test_continuation_transfers_verified_material_graph_without_rebinding(
    edited, tmp_path, monkeypatch, material_context,
):
    from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput
    from cdmw.services.mesh_archive_results import capture_mesh_archive_material_context
    from cdmw.services.preview_rendering_service import acquire_dotnet_preview_package_cache_lease_for_path
    from cdmw.ui.mesh_editor.controller import MeshEditorController

    app = QApplication.instance() or QApplication([])
    service, snapshot, entry, _entries = edited
    prepared = _prepare(edited, tmp_path / "results")
    package = tmp_path / "resolved-materials"
    package.mkdir()
    texture = package / "layer.dds"
    texture.write_bytes(b"owned resolved texture")
    lease = acquire_dotnet_preview_package_cache_lease_for_path(package)
    parameters = (PreviewMaterialParameterInput(
        parameter_name="_dyeingDetailLayerColorMaskR", color_value=(0.12, 0.25, 0.8),
    ),)
    inputs = (PreviewMaterialTextureInput(
        slot_kind="base", source_dds_path=str(texture), owner_slot_index=3,
        layer_role="dye", layer_channel="r", material_parameters=parameters,
    ),)
    preview = SimpleNamespace(path=entry.path, meshes=(SimpleNamespace(
        source_submesh_index=0, preview_pac_material_owner_slot_index=3,
        preview_texture_dds_path=str(texture), preview_texture_tint=(0.12, 0.25, 0.8),
        preview_material_parameters=parameters, preview_material_texture_inputs=inputs,
        vertices=[(99.0, 99.0, 99.0)],
    ),))
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    controller = MeshEditorController(mesh_service=service)
    controller.attach_session(snapshot.session_id)
    tab.standalone_controller = controller
    tab.current_archive_selection = entry
    tab.standalone_archive_material_preview_model = preview
    tab.archive_material_context_package_path = str(package)
    tab.archive_material_context_package_lease = lease
    tab.archive_material_context_verified_for_rust = material_context != "unverified"
    tab.archive_material_context_source_identity = (
        replace(entry, pamt_path=tmp_path / "other" / "0.pamt").identity
        if material_context == "other_archive" else entry.identity
    )
    if material_context == "current":
        saved = capture_mesh_archive_material_context(entry, preview, package)
        prepared = replace(prepared, material_contexts=(saved,))
    tab.standalone_output_request_id = 9
    starts = []
    monkeypatch.setattr(tab, "_start_archive_session_load_when_indexes_ready",
        lambda request_id, target, **kwargs: starts.append((request_id, target)))
    try:
        tab._continue_from_prepared_archive_result(9, prepared)
        assert len(starts) == 1
        assert starts[0][1].prepared_sha256 == prepared.assets[0].prepared_sha256
        if material_context == "current":
            assert tab.archive_session_load_material_model is saved.preview_model
            assert tab.archive_material_context_package_path == str(package)
            assert tab.archive_material_context_package_lease is not lease and not lease.active
            assert tab.archive_material_context_package_lease.active and saved.package_lease.active
            assert tab.archive_material_context_verified_for_rust
            assert tab.archive_material_context_source_identity == entry.identity
            dependencies = tab.archive_session_dependencies
            loaded, errors = [], []
            worker = MeshArchiveSessionLoadWorker(starts[0][0], starts[0][1],
                archive_entries_by_normalized_path=dependencies.entries_by_normalized_path,
                archive_entries_by_basename=dependencies.entries_by_basename)
            worker.loaded.connect(lambda _id, result: loaded.append(result))
            worker.error.connect(lambda _id, message: errors.append(message))
            worker.run()
            assert not errors and len(loaded) == 1
            with patch.object(tab, "_start_selected_mesh_editor"), patch.object(
                tab, "_start_archive_material_context_resolution",
                side_effect=AssertionError("Continuation must retain the resolved materials"),
            ):
                tab._handle_archive_session_loaded(starts[0][0], loaded[0])
            # The production Rust bridge retains exact layers and owner slots,
            # without copying the old preview geometry into the new baseline.
            target_controller = tab.standalone_controller
            assert tab._prime_rust_preview_material_context(target_controller) == 1
            context = target_controller._cdmw_rust_mesh_preview_material_context
            source = context.preview_model.submeshes[0]
            assert source.preview_texture_tint == (0.12, 0.25, 0.8)
            assert source.preview_material_parameters == parameters
            # Rust stores the shared parameter table once on the material.
            assert source.preview_material_texture_inputs == (replace(inputs[0], material_parameters=()),)
            assert source.preview_pac_material_owner_slot_index == 3
            assert context.material_package_path == str(package)
            assert not hasattr(source, "vertices")
            assert parse_pac(read_archive_entry_data(starts[0][1])[0], entry.path).submeshes[0].vertices[0][0] == pytest.approx(0.4, abs=2e-5)
        else:
            assert tab.archive_session_load_material_model is None
            assert not tab.archive_material_context_verified_for_rust
            assert not lease.active
    finally:
        tab.close_standalone_session()
        assert not lease.active
        tab.deleteLater()
        app.processEvents()


def test_deleted_vertices_can_finish_again_after_game_format_continuation(tmp_path):
    from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from tests.test_mesh_rust_authoring_exact_output import _rig_command

    source, service, editor = _open_exact_session(tmp_path / "first")
    loaded = []
    continued = None
    try:
        deleted = editor.shadow_service.apply_command(editor.shadow_session_id, MeshEditCommand(
            "delete", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
            params={"_include_preview_deltas": False}, mode="edit"))
        assert deleted.ok
        editor.finish(_request(editor, "finish_request", 1))
        snapshot = service.capture_export_snapshot(editor.authoritative_session_id)
        entry = _entry(tmp_path / "sources", snapshot.mesh.path, source)
        prepared = prepare_mesh_archive_result(service, snapshot, entry,
            ((entry.identity, (entry,)),), tmp_path / "results")
        worker = MeshArchiveSessionLoadWorker(2, prepared.assets[0])
        errors = []
        worker.loaded.connect(lambda _id, result: loaded.append(result))
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.run()
        assert not errors and len(loaded) == 1
        next_service = loaded[0].service
        next_id = loaded[0].view.session_id
        continued = RustMeshAuthoringSession.create(SimpleNamespace(
            mesh_service=next_service, active_session_id=next_id), tmp_path / "second", process_generation=12)
        assert len(continued.shadow_service.working_mesh(continued.shadow_session_id).submeshes[0].vertices) == 3
        # A new game-format baseline must accept a no-op Finish and offer Refit.
        state = _rig_command(continued, 2, "refit_use_loaded_body", {})
        assert state["state"]["morph_refit"]["driver_submesh_indices"]
        continued.finish(_request(continued, "finish_request", 3))
        rebuilt, report = next_service.rebuild_result_from_snapshot(next_service.capture_export_snapshot(next_id))
        assert report.validation_status == "passed"
        assert rebuilt.data == read_archive_entry_data(prepared.assets[0])[0]
    finally:
        if not editor.closed:
            editor.cancel()
        if continued is not None and not continued.closed:
            continued.cancel()
        for result in loaded:
            result.service.close_edit_session(result.view.session_id, force_without_saving=True)
        service.close_edit_session(editor.authoritative_session_id, force_without_saving=True)
