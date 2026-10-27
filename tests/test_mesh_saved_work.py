"""Saved Mesh Editor drafts and built mods: save, list, continue."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.modding.mesh_parser import parse_pac
from cdmw.models import ArchiveEntry
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.mesh_archive_results import (
    EDITED_RESULT_NOTE,
    prepare_mesh_archive_result,
)
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.services.mesh_saved_work_service import (
    BUILT_MOD_DRAFT_MODE,
    KIND_BUILT_MOD,
    KIND_DRAFT,
    STATUS_GAME_UPDATED,
    STATUS_MATCHES,
    STATUS_MOD_MISSING,
    STATUS_ORIGINAL_UNKNOWN,
    STATUS_SOURCE_MISSING,
    MeshDraftRequest,
    add_built_mod_folder,
    ensure_session_draft_workspace,
    list_saved_work,
    plan_session_draft,
    prepare_saved_work_launch,
    read_draft_manifest,
    register_built_mod,
    saved_work_status,
)
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependencyContext,
)
from cdmw.ui.mesh_editor.saved_work_bridge import MeshEditorSavedWorkBridgeMixin
from cdmw.ui.mesh_editor.saved_work_launch import (
    next_pass_draft_request,
    overlay_dependency_context,
)
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveSessionLoadWorker
from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
from tests.test_mesh_editor_pab_resolution import _pab
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_rust_authoring import _with_resolvable_bone_palette
from tests.test_mesh_rust_authoring_exact_output import _candidate_reference, _request

_BONES = tuple(0xA2000000 + index for index in range(8))
_PAC_PATH = "character/model/saved-work.pac"


@pytest.fixture(autouse=True)
def _owned_history(tmp_path, monkeypatch):
    # Build Mod keeps authoring records in %LOCALAPPDATA%; keep them owned.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))


def _prepared(root: Path, path: str, data: bytes, *, game: Path) -> ArchiveEntry:
    root.mkdir(parents=True, exist_ok=True)
    copy = root / (hashlib.sha256(path.encode()).hexdigest()[:10] + Path(path).name)
    copy.write_bytes(data)
    return ArchiveEntry(path, game / "0.pamt", game / "0.paz", 0, len(data), len(data), 0, 0,
                        prepared_path=copy, prepared_sha256=hashlib.sha256(data).hexdigest(),
                        prepared_size=len(data))


def _context(selected: ArchiveEntry, entries) -> ArchiveWorkflowDependencyContext:
    paths, basenames = {}, {}
    for entry in entries:
        paths.setdefault(entry.path.casefold(), []).append(entry)
        basenames.setdefault(entry.basename.casefold(), []).append(entry)
    return ArchiveWorkflowDependencyContext(selected, tuple(entries), paths, basenames, remote=True)


@pytest.fixture
def game(tmp_path):
    """One owned synthetic PAC with its skeleton, as Archive Browser prepares them."""

    root = tmp_path / "game" / "0009"
    root.mkdir(parents=True)
    (root / "0.pamt").write_bytes(b"owned source index")
    (root / "0.paz").write_bytes(b"owned source payload")
    source = _with_resolvable_bone_palette(_pac_fixture(skinned=True), _BONES)
    sources = tmp_path / "prepared"
    entry = _prepared(sources, _PAC_PATH, source, game=root)
    pab = _prepared(sources, "character/model/saved-work.pab", _pab(_BONES), game=root)
    fingerprints = ((root / "0.pamt").read_bytes(), (root / "0.paz").read_bytes())
    yield SimpleNamespace(source=source, entry=entry, context=_context(entry, (entry, pab)),
                          root=root, drafts=tmp_path / "workspace" / "drafts")
    assert ((root / "0.pamt").read_bytes(), (root / "0.paz").read_bytes()) == fingerprints


def _load(entry: ArchiveEntry, context, drafts: Path, **options):
    worker = MeshArchiveSessionLoadWorker(
        1, entry, draft_root=drafts,
        archive_entries_by_normalized_path=context.entries_by_normalized_path,
        archive_entries_by_basename=context.entries_by_basename,
        **options,
    )
    loaded, errors = [], []
    worker.loaded.connect(lambda _id, result: loaded.append(result))
    worker.error.connect(lambda _id, message: errors.append(message))
    worker.run()
    assert not errors
    assert len(loaded) == 1
    return loaded[0]


def _finish_move(loaded, root: Path, x: float) -> int:
    editor = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=loaded.service, active_session_id=loaded.view.session_id),
        root, process_generation=11,
    )
    request = _request(editor, "transaction_request", 1)
    request["candidate"] = _candidate_reference(editor, request_id=1, first_x=x)
    request["label"] = "Move"
    editor.apply_candidate(request)
    editor.finish(_request(editor, "finish_request", 2))
    return loaded.service.session_view(loaded.view.session_id).revision


def _wait_for_autosave(loaded, timeout: float = 20.0) -> None:
    session = loaded.service._session(loaded.view.session_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with session.export_lock:
            saved = session.mesh_layer_autosave_saved_key == (session.revision, session.geometry_layer_revision)
            error = session.mesh_layer_autosave_error
        if error:
            raise AssertionError(error)
        if saved and session.mesh_layer_project_path.is_file():
            return
        time.sleep(0.05)
    raise AssertionError("Mesh Editor autosave did not finish")


def _first_x(loaded) -> float:
    return loaded.service.working_mesh(loaded.view.session_id, clone=False).submeshes[0].vertices[0][0]


def _close(loaded) -> None:
    loaded.service.close_edit_session(loaded.view.session_id)


def test_direct_open_autosaves_a_draft_that_resumes_after_close(game, tmp_path):
    first = _load(game.entry, game.context, game.drafts, draft_request=MeshDraftRequest())
    manifest = first.draft_manifest_path
    # Opening alone writes nothing; the first accepted edit creates the draft.
    assert manifest is not None and not manifest.parent.exists()
    original_x = _first_x(first)
    _finish_move(first, tmp_path / "rust-first", original_x + 0.25)
    _wait_for_autosave(first)
    _close(first)

    saved = read_draft_manifest(manifest)
    assert saved["workspace_mode"] == "persistent_app_draft"
    assert saved["edit_pass"] == 1
    assert saved["source_archive_path"] == _PAC_PATH
    assert saved["game_source_sha256"] == hashlib.sha256(game.source).hexdigest()
    assert (manifest.parent / saved["baseline"]["mesh"]).read_bytes() == game.source
    rows = list_saved_work(game.drafts)
    assert [(row.kind, row.edit_pass, row.manifest_path) for row in rows] == [(KIND_DRAFT, 1, manifest)]
    assert saved_work_status(rows[0], found=True, current_sha256=hashlib.sha256(game.source).hexdigest()) == STATUS_MATCHES

    fresh = _load(game.entry, game.context, game.drafts, draft_request=MeshDraftRequest())
    try:
        assert [draft.manifest_path for draft in fresh.matching_drafts] == [manifest]
        assert _first_x(fresh) == pytest.approx(original_x, abs=2e-5)
        assert fresh.draft_manifest_path != manifest
    finally:
        fresh.service.close_edit_session(fresh.view.session_id, force_without_saving=True)

    launch = prepare_saved_work_launch(game.drafts, rows[0], game.entry, edited_note=EDITED_RESULT_NOTE)
    assert launch.selected_entry is game.entry and launch.resume_manifest_path == manifest
    resumed = _load(launch.selected_entry, game.context, game.drafts, draft_request=launch.draft_request)
    try:
        assert resumed.resumed_manifest_path == manifest
        assert resumed.draft_manifest_path == manifest
        assert _first_x(resumed) == pytest.approx(original_x + 0.25, abs=2e-5)
    finally:
        resumed.service.close_edit_session(resumed.view.session_id, force_without_saving=True)


def test_next_edit_pass_draft_keeps_its_rebuilt_source_after_the_session_result_is_gone(game, tmp_path):
    first = _load(game.entry, game.context, game.drafts, draft_request=MeshDraftRequest())
    original_x = _first_x(first)
    _finish_move(first, tmp_path / "rust-first", original_x + 0.25)
    _wait_for_autosave(first)
    snapshot = first.service.capture_export_snapshot(first.view.session_id)
    result = prepare_mesh_archive_result(first.service, snapshot, game.entry,
                                         ((game.entry.identity, game.context.entries),), tmp_path / "results")
    request = next_pass_draft_request(dict(first.draft_lineage), result)
    _close(first)
    assert request.edit_pass == 2

    second = _load(result.assets[0], _context(result.assets[0], result.entries), game.drafts, draft_request=request)
    _finish_move(second, tmp_path / "rust-second", original_x + 0.5)
    _wait_for_autosave(second)
    manifest = second.draft_manifest_path
    _close(second)
    # The in-session result does not survive restarting CDMW.
    shutil.rmtree(result.root)

    row = next(row for row in list_saved_work(game.drafts) if row.manifest_path == manifest)
    assert row.edit_pass == 2
    assert row.game_source_sha256 == hashlib.sha256(game.source).hexdigest()
    launch = prepare_saved_work_launch(game.drafts, row, game.entry, edited_note=EDITED_RESULT_NOTE)
    assert launch.selected_entry.identity == game.entry.identity
    assert launch.selected_entry.prepared_note == EDITED_RESULT_NOTE
    assert not launch.game_updated
    context = overlay_dependency_context(game.context, launch.selected_entry, launch.replacements)
    resumed = _load(launch.selected_entry, context, game.drafts, draft_request=launch.draft_request)
    try:
        assert resumed.resumed_manifest_path == manifest
        assert _first_x(resumed) == pytest.approx(original_x + 0.5, abs=2e-5)
        assert resumed.skeleton_source_path == "character/model/saved-work.pab"
    finally:
        resumed.service.close_edit_session(resumed.view.session_id, force_without_saving=True)


def _build_mod(loaded, entry: ArchiveEntry, revision: int, output: Path, drafts: Path):
    worker = MeshDirectOutputWorker(
        5, loaded.service, loaded.view.session_id, entry, kind="loose_mod", output_path=output,
        manager_profile="jmm", expected_mesh_revision=revision, saved_work_root=drafts,
    )
    completed, errors = [], []
    worker.completed.connect(lambda _id, result: completed.append(result))
    worker.error.connect(lambda _id, message: errors.append(message))
    worker.run()
    assert not errors
    return completed[0]


def test_build_mod_freezes_its_draft_and_continuing_starts_a_new_one(game, tmp_path):
    first = _load(game.entry, game.context, game.drafts, draft_request=MeshDraftRequest())
    original_x = _first_x(first)
    revision = _finish_move(first, tmp_path / "rust-first", original_x + 0.25)
    built = _build_mod(first, game.entry, revision, tmp_path / "mods" / "saved-work-mod", game.drafts)
    _close(first)

    assert not built.saved_work_error
    assert parse_pac((built.output_path / _PAC_PATH).read_bytes(), _PAC_PATH).submeshes[0].vertices[0][0] \
        == pytest.approx(original_x + 0.25, abs=2e-5)
    row = next(row for row in list_saved_work(game.drafts) if row.kind == KIND_BUILT_MOD)
    assert row.has_draft and row.mod_root == built.output_path and row.edit_pass == 1
    frozen = read_draft_manifest(row.manifest_path)
    assert frozen["workspace_mode"] == BUILT_MOD_DRAFT_MODE
    frozen_project = (row.manifest_path.parent / "mesh_layers" / "mesh_layer_project.json").read_bytes()

    launch = prepare_saved_work_launch(game.drafts, row, game.entry, edited_note=EDITED_RESULT_NOTE)
    assert launch.resume_manifest_path is None and launch.draft_request.seed_project_path is not None
    context = overlay_dependency_context(game.context, launch.selected_entry, launch.replacements)
    continued = _load(launch.selected_entry, context, game.drafts, draft_request=launch.draft_request)
    try:
        assert _first_x(continued) == pytest.approx(original_x + 0.25, abs=2e-5)
        assert continued.draft_manifest_path.parent != row.manifest_path.parent
        _finish_move(continued, tmp_path / "rust-continued", original_x + 0.75)
        _wait_for_autosave(continued)
    finally:
        _close(continued)
    assert (row.manifest_path.parent / "mesh_layers" / "mesh_layer_project.json").read_bytes() == frozen_project


def test_built_mod_without_a_draft_reopens_its_finished_mesh_as_a_new_pass(game, tmp_path):
    first = _load(game.entry, game.context, game.drafts)
    original_x = _first_x(first)
    revision = _finish_move(first, tmp_path / "rust-first", original_x + 0.25)
    built = _build_mod(first, game.entry, revision, tmp_path / "mods" / "someone-elses", None)
    first.service.close_edit_session(first.view.session_id, force_without_saving=True)
    assert built.saved_work_record is None
    finished = (built.output_path / _PAC_PATH).read_bytes()

    record = add_built_mod_folder(game.drafts, built.output_path)
    assert record["source_archive_path"] == _PAC_PATH
    with pytest.raises(ValueError, match="already in the list"):
        add_built_mod_folder(game.drafts, built.output_path)
    row = next(row for row in list_saved_work(game.drafts) if row.kind == KIND_BUILT_MOD)
    assert not row.has_draft and row.edit_pass == 0
    launch = prepare_saved_work_launch(game.drafts, row, game.entry, edited_note=EDITED_RESULT_NOTE)
    assert launch.draft_request.edit_pass == 2
    assert read_archive_entry_data(launch.selected_entry)[0] == finished
    context = overlay_dependency_context(game.context, launch.selected_entry, launch.replacements)
    reopened = _load(launch.selected_entry, context, game.drafts, draft_request=launch.draft_request)
    try:
        assert reopened.resumed_manifest_path is None
        assert _first_x(reopened) == pytest.approx(original_x + 0.25, abs=2e-5)
        # Materials and the skeleton still come from the game's own files.
        assert reopened.skeleton_source_path == "character/model/saved-work.pab"
    finally:
        reopened.service.close_edit_session(reopened.view.session_id, force_without_saving=True)


def test_resumed_draft_restores_removed_parts_and_the_fitting_setup(tmp_path):
    from tests.test_mesh_refit_live_exclusions import _included_parts_pac
    from tests.test_mesh_rust_authoring_exact_output import _rig_command
    from tests.test_mesh_rust_replacement import command

    root = tmp_path / "game" / "0009"
    root.mkdir(parents=True)
    raw = _included_parts_pac()
    entry = _prepared(tmp_path / "prepared", "character/model/parts.pac", raw, game=root)
    context = _context(entry, (entry,))
    drafts = tmp_path / "drafts"
    loaded = _load(entry, context, drafts, draft_request=MeshDraftRequest())
    host = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=loaded.service, active_session_id=loaded.view.session_id),
        tmp_path / "rust", process_generation=11,
    )
    removed = host.state_payload()["replacement"]["parts"][2]["id"]
    command(host, "replacement_include", {"part_ids": [removed], "included": False,
        "_archive_entry": entry, "_archive_dependencies": context})
    _rig_command(host, 1, "refit_set_driver", {"submesh_indices": [0]})
    _rig_command(host, 2, "refit_bind", {"submesh_indices": [1, 2]})
    _rig_command(host, 3, "refit_fit_to_body", {})
    host.finish(_request(host, "finish_request", 4))
    _wait_for_autosave(loaded)
    service, sid = loaded.service, loaded.view.session_id
    included = {part.part_id: part.included for part in service._session(sid).replacement_state.parts}
    fitted = service.working_mesh(sid, clone=True)
    refit = service.cached_morph_state_from_runtime(sid).refit
    assert included[removed] is False
    assert refit.garment_submesh_indices == (1, 2)
    _close(loaded)

    row = list_saved_work(drafts)[0]
    launch = prepare_saved_work_launch(drafts, row, entry, edited_note=EDITED_RESULT_NOTE)
    resumed = _load(launch.selected_entry, context, drafts, draft_request=launch.draft_request)
    try:
        session = resumed.service._session(resumed.view.session_id)
        assert {part.part_id: part.included for part in session.replacement_state.parts} == included
        restored = resumed.service.cached_morph_state_from_runtime(resumed.view.session_id).refit
        assert restored.driver_submesh_indices == refit.driver_submesh_indices
        assert restored.garment_submesh_indices == refit.garment_submesh_indices
        working = resumed.service.working_mesh(resumed.view.session_id, clone=True)
        assert [part.vertices for part in working.submeshes] == [part.vertices for part in fitted.submeshes]
    finally:
        resumed.service.close_edit_session(resumed.view.session_id, force_without_saving=True)


def _row(**changes):
    from cdmw.services.mesh_saved_work_service import SavedWorkRow

    values = dict(kind=KIND_DRAFT, row_id="r", display_name="n", saved_at=1.0, source_archive_path=_PAC_PATH,
                  source_package="", edit_pass=1, folder=Path("."), manifest_path=None, source_sha256="a" * 64,
                  game_source_sha256="a" * 64, has_draft=True)
    values.update(changes)
    return SavedWorkRow(**values)


def test_status_line_compares_the_original_game_file(tmp_path):
    assert saved_work_status(_row(), found=True, current_sha256="a" * 64) == STATUS_MATCHES
    assert saved_work_status(_row(), found=True, current_sha256="b" * 64) == STATUS_GAME_UPDATED
    assert saved_work_status(_row(), found=False) == STATUS_SOURCE_MISSING
    later = _row(edit_pass=3, game_source_sha256="", source_sha256="c" * 64)
    assert saved_work_status(later, found=True, current_sha256="b" * 64) == STATUS_ORIGINAL_UNKNOWN
    mod = _row(kind=KIND_BUILT_MOD, mod_root=tmp_path / "gone", folder=tmp_path / "gone")
    assert saved_work_status(mod, found=True, current_sha256="a" * 64) == STATUS_MOD_MISSING


def test_autosave_keeps_only_the_current_and_previous_generation(game, tmp_path):
    loaded = _load(game.entry, game.context, game.drafts, draft_request=MeshDraftRequest())
    try:
        x = _first_x(loaded)
        for step in range(3):
            _finish_move(loaded, tmp_path / f"rust-{step}", x + 0.1 * (step + 1))
            _wait_for_autosave(loaded)
        project = loaded.draft_manifest_path.parent / "mesh_layers"
        descriptor = json.loads((project / "mesh_layer_project.json").read_text(encoding="utf-8"))
        generations = sorted(path.name for path in project.iterdir() if path.name.startswith("generation-"))
        assert generations == sorted((descriptor["current_generation"], descriptor["previous_generation"]))
    finally:
        _close(loaded)


# ---------------------------------------------------------------- the window


def _draft_on_disk(drafts: Path, entry: ArchiveEntry, data: bytes, name: str, *, now: float) -> Path:
    plan = plan_session_draft(drafts, entry, source_sha256=hashlib.sha256(data).hexdigest(),
                              request=MeshDraftRequest(display_name=name), now=now)
    ensure_session_draft_workspace(plan, data)
    plan.project_path.parent.mkdir(parents=True)
    plan.project_path.write_text('{"format":"mesh_layer_project_v1"}', encoding="utf-8")
    manifest = json.loads(plan.manifest_path.read_text(encoding="utf-8"))
    manifest["updated_at"] = now
    plan.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return plan.manifest_path


class _Resolver:
    def __init__(self, sources):
        self.sources = sources
        self.calls = []

    def cancel(self):
        pass

    def resolve(self, paths, callback):
        self.calls.append(tuple(paths))
        callback(self.sources)


def _wait(app, condition, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def test_saved_work_window_lists_rows_and_runs_its_actions(game, tmp_path, monkeypatch):
    from cdmw.ui.mesh_editor import saved_work_dialog
    from cdmw.ui.mesh_editor.saved_work_dialog import MeshSavedWorkDialog

    app = QApplication.instance() or QApplication([])
    older = _draft_on_disk(game.drafts, game.entry, game.source, "Older fit", now=100.0)
    newer = _draft_on_disk(game.drafts, game.entry, game.source, "Newer fit", now=200.0)
    mod_root = tmp_path / "mods" / "kept-mod"
    mod_root.mkdir(parents=True)
    register_built_mod(game.drafts, mod_root=mod_root, entry=game.entry,
                       source_sha256=hashlib.sha256(game.source).hexdigest(), draft_manifest_path=older)
    opened_urls, continued = [], []
    monkeypatch.setattr(saved_work_dialog.QDesktopServices, "openUrl", lambda url: opened_urls.append(url))
    dialog = MeshSavedWorkDialog(
        None, draft_root=game.drafts,
        source_resolver=_Resolver({_PAC_PATH.casefold(): game.entry}),
        active_draft_manifest=lambda: newer,
    )
    dialog.continue_requested.connect(continued.append)
    try:
        dialog.refresh()
        _wait(app, lambda: len(dialog.rows()) == 3 and all(dialog.status_code(row) != "checking"
                                                            for row in dialog.rows()))
        table = dialog.table
        assert [table.horizontalHeaderItem(column).text() for column in range(6)] == [
            "Saved on", "File name", "Game file", "Draft or mod", "Edit pass", "Status"]
        texts = [[table.item(row, column).text() for column in range(1, 6)] for row in range(3)]
        assert ["Newer fit", _PAC_PATH, "Saved draft", "1", "Matches the current game files"] in texts
        assert ["Older fit", _PAC_PATH, "Saved draft", "1", "Matches the current game files"] in texts
        assert ["kept-mod", _PAC_PATH, "Built mod", "1", "Matches the current game files"] in texts

        def select(name):
            index = next(row for row in range(table.rowCount()) if table.item(row, 1).text() == name)
            table.selectRow(index)
            app.processEvents()
            return dialog.rows()[index]

        # The draft open in Mesh Editor cannot be deleted from here.
        select("Newer fit")
        assert not dialog.delete_button.isEnabled()
        dialog.continue_button.click()
        assert [row.display_name for row in continued] == ["Newer fit"]
        dialog.open_folder_button.click()
        assert opened_urls[-1].toLocalFile().replace("\\", "/").rstrip("/") == newer.parent.as_posix()

        monkeypatch.setattr(saved_work_dialog.QInputDialog, "getText", lambda *_a, **_k: ("Fitted cuirass", True))
        select("Older fit")
        dialog.rename_button.click()
        _wait(app, lambda: any(row.display_name == "Fitted cuirass" for row in dialog.rows()))
        assert read_draft_manifest(older)["display_name"] == "Fitted cuirass"

        monkeypatch.setattr(saved_work_dialog.QMessageBox, "question",
                            lambda *_a, **_k: QMessageBox.StandardButton.Yes)
        select("kept-mod")
        assert dialog.delete_button.text() == "Remove from List..."
        dialog.delete_button.click()
        _wait(app, lambda: len(dialog.rows()) == 2)
        assert mod_root.is_dir()
        assert not any(path.name.startswith("built-") for path in game.drafts.iterdir())

        select("Fitted cuirass")
        assert dialog.delete_button.text() == "Delete..." and dialog.delete_button.isEnabled()
        dialog.delete_button.click()
        _wait(app, lambda: len(dialog.rows()) == 1)
        assert not older.parent.exists() and newer.is_file()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_saved_work_window_says_when_the_game_is_not_loaded(game, tmp_path):
    from cdmw.ui.mesh_editor.saved_work_dialog import MeshSavedWorkDialog

    app = QApplication.instance() or QApplication([])
    _draft_on_disk(game.drafts, game.entry, game.source, "Fit", now=100.0)
    dialog = MeshSavedWorkDialog(None, draft_root=game.drafts, source_resolver=_Resolver(None))
    try:
        dialog.refresh()
        _wait(app, lambda: len(dialog.rows()) == 1 and dialog.status_code(dialog.rows()[0]) != "checking")
        assert dialog.table.item(0, 5).text() == "Load the game in Archive Browser to check"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_tab_plans_a_draft_for_each_open_and_passes_its_lineage_to_the_next_pass(game, tmp_path, monkeypatch):
    from unittest.mock import patch

    from PySide6.QtCore import QSettings

    from cdmw.ui.mesh_editor.tab import MeshEditorTab

    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat))
    first = None
    try:
        with patch.object(tab, "_start_archive_session_load_worker") as start:
            tab.open_archive_session(game.entry, archive_dependencies=game.context)
        start.assert_called_once()
        assert tab.archive_session_draft_request == MeshDraftRequest(edit_pass=1)
        tab.close_standalone_session()

        first = _load(game.entry, game.context, tab.mesh_editor_draft_root,
                      draft_request=MeshDraftRequest(display_name="Cuirass fit"))
        _finish_move(first, tmp_path / "rust", _first_x(first) + 0.25)
        snapshot = first.service.capture_export_snapshot(first.view.session_id)
        result = prepare_mesh_archive_result(first.service, snapshot, game.entry,
                                             ((game.entry.identity, game.context.entries),), tmp_path / "results")
        tab.standalone_controller = SimpleNamespace(mesh_service=first.service, active_session_id=first.view.session_id)
        tab.standalone_output_request_id = 8
        tab.mesh_editor_draft_lineage = dict(first.draft_lineage)
        opened = []
        monkeypatch.setattr(tab, "open_archive_session", lambda target, **kwargs: opened.append(kwargs))
        tab._continue_from_prepared_archive_result(8, result)
        request = opened[0]["draft_request"]
        assert (request.edit_pass, request.display_name) == (2, "Cuirass fit")
        assert request.game_source_sha256 == hashlib.sha256(game.source).hexdigest()
    finally:
        tab.standalone_controller = None
        if first is not None:
            first.service.close_edit_session(first.view.session_id, force_without_saving=True)
        tab.deleteLater()
        app.processEvents()


class _Shell(MeshEditorSavedWorkBridgeMixin, QObject):
    """The shell surface the saved-work routes use, without a main window."""

    def __init__(self, tmp_path, archive):
        super().__init__()
        self.settings = SimpleNamespace(fileName=lambda: str(tmp_path / "settings.ini"))
        self.archive = archive
        self.archive_browser_tab = object()
        self.statuses = []
        self.opened = []

    def set_status_message(self, message, error=False):
        self.statuses.append((message, error))

    def _mesh_editor_open_blocked(self):
        return False

    def _activate_tool_widget(self, _widget):
        pass

    def _run_utility_task_when_idle(self, *, status_message, task, on_complete, on_error):
        try:
            result = task(None)
        except Exception as exc:
            on_error(str(exc))
        else:
            on_complete(result)

    def _open_archive_mesh_editor_with_dependencies(self, entry, dependencies, **options):
        self.opened.append((entry, dependencies, options))


@pytest.mark.parametrize("confirm", [False, True])
def test_continue_editing_asks_before_using_a_copy_of_an_updated_game_file(game, tmp_path, monkeypatch, confirm):
    from cdmw.ui.mesh_editor import saved_work_bridge

    updated = _prepared(tmp_path / "updated", _PAC_PATH, game.source + b"\0", game=game.root)
    context = _context(updated, (updated, *game.context.entries[1:]))
    archive = SimpleNamespace(archive_remote_bridge=None, _current_archive_mesh_entry=lambda: updated,
                              archive_entries=context.entries,
                              archive_entries_by_normalized_path=context.entries_by_normalized_path,
                              archive_entries_by_basename=context.entries_by_basename)
    shell = _Shell(tmp_path, archive)
    drafts = shell._mesh_saved_work_root()
    manifest = _draft_on_disk(drafts, game.entry, game.source, "Fit", now=100.0)
    asked = []
    monkeypatch.setattr(saved_work_bridge.QMessageBox, "question", lambda *args, **_k: asked.append(args) or (
        QMessageBox.StandardButton.Yes if confirm else QMessageBox.StandardButton.No))

    shell._continue_mesh_saved_work(list_saved_work(drafts)[0])

    assert len(asked) == 1
    if not confirm:
        assert shell.opened == []
        return
    (entry, dependencies, options), = shell.opened
    assert read_archive_entry_data(entry)[0] == game.source
    assert dependencies.selected_entry is entry
    assert dependencies.entry_for_path(_PAC_PATH) is entry
    assert dependencies.entry_for_path("character/model/saved-work.pab") is not None
    assert options["resume_manifest_path"] == manifest


def test_continue_editing_waits_for_archive_browser_to_prepare_the_source(game, tmp_path, monkeypatch):
    from cdmw.ui.mesh_editor import saved_work_bridge

    selected = []
    scopes = []
    bridge = SimpleNamespace(displays_v2=True, apply_entry_id_scope=lambda ids, label: scopes.append(ids) or True)
    archive = SimpleNamespace(archive_remote_bridge=bridge,
                              _current_archive_mesh_entry=lambda: selected[0] if selected else None)
    shell = _Shell(tmp_path, archive)
    resolver = SimpleNamespace(entry_ids={_PAC_PATH.casefold(): 42}, cancel=lambda: None,
                               resolve=lambda paths, callback: callback({_PAC_PATH.casefold(): game.entry}))
    shell._mesh_saved_work_source_resolver = resolver
    ready = []
    monkeypatch.setattr(saved_work_bridge, "archive_workflow_dependency_context",
                        lambda _owner, entry: game.context if ready else (_ for _ in ()).throw(
                            saved_work_bridge.ArchiveWorkflowDependenciesUnavailable("preparing")))
    _draft_on_disk(shell._mesh_saved_work_root(), game.entry, game.source, "Fit", now=100.0)
    row = list_saved_work(shell._mesh_saved_work_root())[0]
    app = QApplication.instance() or QApplication([])
    previews = []
    archive._preview_current_archive_entry = lambda: previews.append(True)
    shell._continue_mesh_saved_work(row)
    try:
        assert scopes == [(42,)] and shell.opened == []
        selected.append(game.entry)
        shell._poll_mesh_saved_work_source()
        assert previews == [True] and shell.opened == []
        ready.append(True)
        shell._poll_mesh_saved_work_source()
        (entry, dependencies, options), = shell.opened
        assert entry is game.entry and dependencies is game.context
        assert options["resume_manifest_path"] == row.manifest_path
        assert shell._mesh_saved_work_pending is None
    finally:
        shell._cancel_mesh_saved_work_source_wait()
        app.processEvents()


def test_archive_context_menu_opens_saved_work_for_the_selected_file(tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    from cdmw.ui.archive_browser import actions
    from tests.test_archive_mesh_export_modes import _ExportWindow

    app = QApplication.instance() or QApplication([])
    entry = ArchiveEntry(_PAC_PATH, tmp_path / "0.pamt", tmp_path / "0.paz", 0, 64, 64, 0, 0)
    window = _ExportWindow(entry, tmp_path)
    requested = []
    window._open_mesh_editor_saved_work = requested.append

    class ChooseMenu(QMenu):
        def exec(self, _position):
            choices = {action.text(): action for action in self.actions()}
            return choices["Continue Earlier Work..."]

    monkeypatch.setattr(actions, "QMenu", ChooseMenu)
    try:
        window._show_archive_tree_context_menu(QPoint())
        _wait(app, lambda: bool(requested))
        assert requested == [_PAC_PATH]
    finally:
        window.close()


def test_mesh_editor_button_opens_the_saved_work_window_in_the_real_shell(tmp_path):
    from cdmw.app.events import AppEventBus
    from cdmw.services.service_container import ServiceContainer
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.mesh_editor.saved_work_dialog import MeshSavedWorkDialog
    from cdmw.ui.shell.app_context import AppContext

    app = QApplication.instance() or QApplication([])
    settings = create_settings(settings_file_path=tmp_path / "saved-work-shell.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                         event_bus=AppEventBus())
    window = MainWindow(app_context=context)
    # No game folder is configured; keep the startup prompts from blocking.
    window.show_first_run_guide_on_launch = False
    window._prompt_for_archive_package_root_if_missing = lambda **_kwargs: True
    try:
        tab = window.mesh_editor_tab.ensure_widget()
        tab.saved_work_button.click()
        dialog = window._mesh_saved_work_dialog
        assert isinstance(dialog, MeshSavedWorkDialog) and dialog.isVisible()
        assert dialog.draft_root == tab.mesh_editor_draft_root
        _wait(app, lambda: "No saved work yet" in dialog.empty_label.text())
        tab.draft_choose_button.click()
        assert window._mesh_saved_work_dialog is dialog and dialog.filter_edit.text() == ""
    finally:
        dialog = getattr(window, "_mesh_saved_work_dialog", None)
        if dialog is not None:
            dialog.close()
        window._finalize_close()
        window.deleteLater()
        app.processEvents()


def test_source_resolver_picks_the_active_catalogue_entry_and_reports_missing_files(tmp_path):
    from PySide6.QtCore import Signal

    from cdmw.domain.archives.catalogue import (
        ArchiveDurableIdentity,
        ArchiveEntryDto,
        ArchiveEntryRole,
        ArchiveLookupKind,
        ArchiveLookupResult,
    )
    from cdmw.ui.mesh_editor.saved_work_sources import SavedWorkSourceResolver

    class Catalogue(QObject):
        batch_ready = Signal(str, str, object)
        result_ready = Signal(str, str, object)
        request_failed = Signal(str, object)
        request_cancelled = Signal(str)

        def __init__(self):
            super().__init__()
            self.requests = []

        def resolve_entries(self, request, *, ui_generation):
            self.requests.append((request, ui_generation))
            return f"lookup-{len(self.requests)}"

        def cancel(self, _request):
            return True

    def dto(entry_id, offset, state):
        return ArchiveEntryDto(
            session_id="session", entry_id=entry_id,
            identity=ArchiveDurableIdentity(_PAC_PATH, "0009/0.pamt", 0, offset), path=_PAC_PATH,
            source_pamt="0009/0.pamt", paz_file="0009/0.paz", paz_index=0, offset=offset, stored_size=8,
            original_size=8, flags=0, extension=".pac", package="0009", role=ArchiveEntryRole.MODEL,
            category="model", is_previewable=True, override_state=state, is_active_override=state == "active",
        )

    catalogue = Catalogue()
    bridge = SimpleNamespace(displays_v2=True, current_session=SimpleNamespace(session_id="session"),
                             controller=SimpleNamespace(generation=7))
    resolver = SavedWorkSourceResolver(SimpleNamespace(archive_remote_bridge=bridge, archive_catalogue_service=catalogue))
    results = []
    resolver.resolve([_PAC_PATH, "character/model/gone.pac"], results.append)
    (request, generation), = catalogue.requests
    assert request.kind is ArchiveLookupKind.EXACT_PATHS and generation == 7
    catalogue.result_ready.emit("lookup-1", "resolve_entries", ArchiveLookupResult(
        "session", (dto(1, 0, "shadowed"), dto(2, 64, "active")), total_matches=2, truncated=False))
    (resolved,), = [results]
    assert resolved[_PAC_PATH.casefold()].offset == 64
    assert resolved["character/model/gone.pac"] is None
    assert resolver.entry_ids == {_PAC_PATH.casefold(): 2}

    resolver.resolve([_PAC_PATH], results.append)
    catalogue.request_failed.emit("lookup-2", RuntimeError("worker stopped"))
    assert results[-1] is None


def test_game_update_continues_from_the_saved_copy(game, tmp_path):
    manifest = _draft_on_disk(game.drafts, game.entry, game.source, "Fit", now=100.0)
    row = list_saved_work(game.drafts)[0]
    updated = _prepared(tmp_path / "updated", _PAC_PATH, game.source + b"\0", game=game.root)
    launch = prepare_saved_work_launch(game.drafts, row, updated, edited_note=EDITED_RESULT_NOTE)
    assert launch.game_updated
    assert launch.resume_manifest_path == manifest
    assert read_archive_entry_data(launch.selected_entry)[0] == game.source
    assert launch.selected_entry.identity == updated.identity
    assert launch.selected_entry.prepared_note == ""
