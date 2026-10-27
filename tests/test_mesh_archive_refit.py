from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_archive_refit import (
    archive_refit_snapshots, load_archive_refit_context, save_archive_refit_context,
    validate_archive_refit,
)
from cdmw.services.mesh_service import MeshService
from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
from tests.test_mesh_rust_authoring_exact_output import (
    _candidate_reference, _open_exact_session, _request, _rig_command,
)


def _entry(root, name, source):
    group = root / "game/character"
    group.mkdir(parents=True, exist_ok=True)
    pamt, paz = group / "0.pamt", group / "0.paz"
    pamt.write_bytes(b"owned archive index")
    paz.write_bytes(source)
    return ArchiveEntry(name, pamt, paz, 0, len(source), len(source), 0, 0)


def _load_pair(tmp_path, *, assign_body=True, texture_paths=None,
               primary_appearance=None, incoming_appearance=None, role="armor", distinct_material=False,
               edit_before_append=False):
    source, authority, session = _open_exact_session(
        tmp_path / "session", base_texture_path=texture_paths[0] if texture_paths else None,
        neutral_appearance=primary_appearance,
    )
    if edit_before_append:
        from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection

        count = len(session.shadow_service.working_mesh(session.shadow_session_id, clone=False).submeshes[0].vertices)
        changed = session.shadow_service.apply_command(
            session.shadow_session_id, MeshEditCommand("recalculate_normals", mode="edit",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: tuple(range(count))})))
        assert changed.ok
        assert session.shadow_service._session(session.shadow_session_id).edit_operations
    primary = _entry(tmp_path, "owned-rust-exact.pac", source)
    armor = _entry(tmp_path, "armor.pac", source)
    other = MeshService()
    mesh = other.load_mesh_bytes(source, armor.path, run_roundtrip=True)
    if distinct_material:
        mesh.submeshes[0].name = "Armor"
        mesh.submeshes[0].material = "Armor material"
    other_id = other.open_edit_session(mesh, mode="edit").session_id
    try:
        incoming = other.capture_export_snapshot(other_id)
        if texture_paths:
            incoming.mesh.submeshes[0].preview_texture_dds_path = str(texture_paths[1])
    finally:
        other.close_edit_session(other_id, force_without_saving=True)
    if assign_body:
        result = _rig_command(session, 1, "refit_use_loaded_body", {})
        assert result["state"]["morph_refit"]["driver_submesh_indices"]
    loaded = _rig_command(session, 2, "refit_choose_archive", {
        "role": role, "_primary_entry": primary, "_archive_entry": armor,
        "_archive_snapshot": incoming, "_archive_neutral_appearance": incoming_appearance,
    })
    return source, authority, session, primary, armor, loaded


def _edit_both(session):
    request = _request(session, "transaction_request", 20)
    reference = _candidate_reference(session, request_id=20, first_x=0.4)
    path = session.root / reference["path"]
    candidate = json.loads(path.read_text())
    candidate["submeshes"][-1]["positions"][0][0] = 0.7
    encoded = json.dumps(candidate).encode()
    path.write_bytes(encoded)
    reference.update(byte_length=len(encoded), sha256=hashlib.sha256(encoded).hexdigest().upper())
    request["candidate"] = reference
    session.apply_candidate(request)


@pytest.mark.parametrize("include_body", [False, True])
def test_archive_refit_finish_and_build_mod_preserve_both_original_files(tmp_path, include_body):
    source, authority, session, primary, armor, loaded = _load_pair(tmp_path)
    try:
        assert loaded["state"]["output_policy"] == "exact_game_asset"
        assert len(loaded["state"]["archive_refit_assets"]) == 2
        _rig_command(session, 3, "refit_bind", {"submesh_indices": loaded["result"]["loaded_parts"]})
        _edit_both(session)
        finished = session.finish(_request(session, "finish_request", 21))
        assert len(finished["exact_output_validation"]["assets"]) == 2
        snapshot = authority.capture_export_snapshot("authoritative-rust-exact")
        assert len(archive_refit_snapshots(snapshot)) == 2
        assert authority.validate_export_snapshot(snapshot).ok
        errors, completed = [], []
        worker = MeshDirectOutputWorker(
            1, authority, "authoritative-rust-exact", primary, kind="loose_mod",
            output_path=tmp_path / "mod", manager_profile="dmm", include_refit_body=include_body,
        )
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors
        assert completed and completed[0].rebuild_report is not None
        armor_bytes = (tmp_path / "mod" / armor.path).read_bytes()
        assert parse_pac(armor_bytes, armor.path).submeshes[-1].vertices[0][0] == pytest.approx(0.7, abs=2e-5)
        assert primary.paz_file.read_bytes() == source
        assert primary.pamt_path.read_bytes() == b"owned archive index"
        from cdmw.core.mod_export_history import mod_metadata_path
        metadata = json.loads(mod_metadata_path(tmp_path / "mod", "mesh-editor-session.json").read_text())
        if include_body:
            body_bytes = (tmp_path / "mod" / primary.path).read_bytes()
            assert parse_pac(body_bytes, primary.path).submeshes[0].vertices[0][0] == pytest.approx(0.4, abs=2e-5)
            assert {asset["path"] for asset in metadata["assets"]} == {primary.path, armor.path}
        else:
            # The opened mesh is the Fit body here; an outfit mod leaves it out.
            assert not (tmp_path / "mod" / primary.path).exists()
            assert [asset["path"] for asset in metadata["assets"]] == [armor.path]
            assert metadata["omitted_body_assets"] == [primary.path]
        assert authority.undo("authoritative-rust-exact").ok
        assert authority._session("authoritative-rust-exact").archive_refit_context is None
        assert authority.redo("authoritative-rust-exact").ok
        assert len(archive_refit_snapshots(authority.capture_export_snapshot("authoritative-rust-exact"))) == 2
    finally:
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


def test_fit_body_assets_follow_the_load_role_and_the_driver():
    from types import SimpleNamespace
    from cdmw.services.mesh_archive_refit import ArchiveRefitAsset, ArchiveRefitContext, archive_refit_body_assets

    outfit = ArchiveRefitAsset(SimpleNamespace(path="outfit.pac"), None, (0, 1), "loaded")
    body = ArchiveRefitAsset(SimpleNamespace(path="body.pac"), None, (2,), "body")
    context = ArchiveRefitContext((outfit, body))

    def state(drivers, garments=()):
        return SimpleNamespace(driver_submesh_indices=drivers,
                               refit=SimpleNamespace(garment_submesh_indices=garments))

    assert archive_refit_body_assets(None) == ()
    assert archive_refit_body_assets(context) == (body,)
    assert archive_refit_body_assets(context, state((2,), (0, 1))) == (body,)
    # A body opened first is a body because every Part of it drives the Fit.
    assert archive_refit_body_assets(context, state((0, 1, 2))) == (outfit, body)
    assert archive_refit_body_assets(context, state((0,), (1,))) == (body,)
    # A file with bound garment Parts belongs in the mod, whatever its role.
    assert archive_refit_body_assets(context, state((0, 1), (2,))) == (outfit,)


@pytest.mark.parametrize("include_body", [False, True])
def test_build_mod_leaves_out_a_loaded_fit_body_unless_included(tmp_path, include_body):
    source, authority, editor, outfit, body, _loaded = _load_pair(tmp_path, assign_body=False, role="body")
    try:
        _rig_command(editor, 3, "refit_bind", {"submesh_indices": [0]})
        _rig_command(editor, 4, "refit_fit_to_body", {})
        _rig_command(editor, 5, "morph_bake", {})
        editor.finish(_request(editor, "finish_request", 6))
        errors, completed = [], []
        worker = MeshDirectOutputWorker(
            1, authority, editor.authoritative_session_id, outfit, kind="loose_mod",
            output_path=tmp_path / "mod", manager_profile="dmm", include_refit_body=include_body,
        )
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors and completed
        assert (tmp_path / "mod" / outfit.path).read_bytes() != source
        # The untouched body would only override other body mods.
        assert (tmp_path / "mod" / body.path).is_file() == include_body
        if include_body:
            assert (tmp_path / "mod" / body.path).read_bytes() == source
    finally:
        editor.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


@pytest.mark.parametrize("include_body", [False, True])
def test_build_mod_dialog_offers_the_fit_body_unticked(tmp_path, monkeypatch, include_body):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog
    from cdmw.ui.mesh_editor.tab import MeshEditorTab

    app = QApplication.instance() or QApplication([])
    _source, authority, editor, outfit, body, _loaded = _load_pair(tmp_path, assign_body=False, role="body")
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    try:
        _rig_command(editor, 3, "refit_bind", {"submesh_indices": [0]})
        editor.finish(_request(editor, "finish_request", 4))
        tab.standalone_controller = SimpleNamespace(
            mesh_service=authority, active_session_id=editor.authoritative_session_id)
        for name, value in (("_mesh_output_target", lambda: outfit), ("_current_target_entry", lambda: outfit),
                            ("_standalone_export_validation_ok", lambda: True),
                            ("_standalone_action_worker_active", lambda: False)):
            monkeypatch.setattr(tab, name, value)
        captured, shown = [], []
        monkeypatch.setattr(tab, "_start_mesh_direct_output_worker", lambda *args, **kwargs: captured.append(kwargs))

        def choose(dialog):
            assert isinstance(dialog, MeshModExportDialog)
            shown.append((dialog.include_body.isHidden(), dialog.include_body.isChecked(),
                          body.basename in dialog.include_body_hint.text(), dialog.mod_name.text()))
            dialog.include_body.setChecked(include_body)
            dialog.output_parent.setText(str(tmp_path / "exports"))
            return dialog.DialogCode.Accepted

        monkeypatch.setattr(MeshModExportDialog, "exec", choose)
        tab._start_mesh_mod_build_requested()
        assert shown == [(False, False, True, "owned-rust-exact Mesh Mod")]
        assert len(captured) == 1 and captured[0]["include_refit_body"] is include_body
    finally:
        tab.standalone_controller = None
        tab.deleteLater()
        app.processEvents()
        editor.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


def test_archive_refit_finish_retains_each_assets_admitted_channel_edits(tmp_path):
    from cdmw.domain.mesh.operations import mesh_edit_operations_from_dicts

    _source, authority, editor, _primary, _armor, _loaded = _load_pair(
        tmp_path, assign_body=False, edit_before_append=True)
    try:
        _edit_both(editor)
        snapshot = editor.shadow_service.capture_export_snapshot(editor.shadow_session_id)
        finished = editor.finish(_request(editor, "finish_request", 21))
        for _entry, component in archive_refit_snapshots(snapshot):
            operations = mesh_edit_operations_from_dicts(component.edit_operations)
            assert any(row.operation == "replace_positions_same_count" and row.submesh_index == 0
                       for row in operations)
        assert all(asset["status"] == "passed"
                   for asset in finished["exact_output_validation"]["assets"])
    finally:
        editor.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


def test_archive_refit_keeps_untracked_channel_rejection_after_splitting(tmp_path):
    _source, authority, editor, _primary, _armor, _loaded = _load_pair(tmp_path, assign_body=False)
    try:
        _edit_both(editor)
        snapshot = editor.shadow_service.capture_export_snapshot(editor.shadow_session_id)
        # A valid position edit must never authorize an unrelated UV edit.
        part = snapshot.mesh.submeshes[-1]
        part.uvs = [(.123, .456), *part.uvs[1:]]
        _entry, component = archive_refit_snapshots(snapshot)[-1]
        report = editor.shadow_service.validate_export_snapshot(component)
        assert any(issue.code == "untracked_edit_channel" and "uv0" in issue.message for issue in report.blockers)
        with pytest.raises(RuntimeError, match="untracked_edit_channel"):
            editor.shadow_service.rebuild_result_from_snapshot(component)
    finally:
        editor.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


@pytest.mark.parametrize("neutral", [False, True])
def test_archive_refit_fit_and_bake_finish_after_an_earlier_channel_edit(tmp_path, neutral):
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
    from tests.test_mesh_neutral_face_editing import IDENTITY

    matrix = (*IDENTITY[:12], .2, .1, .15, 1.)
    appearance = NeutralMeshAppearance("owned/refit.pabc", tuple(range(8)), (matrix,)*8) if neutral else None
    _source, authority, editor, _primary, _armor, _loaded = _load_pair(
        tmp_path, assign_body=False, role="body", edit_before_append=True,
        primary_appearance=appearance, incoming_appearance=appearance)
    try:
        _rig_command(editor, 3, "refit_bind", {"submesh_indices": [0]})
        service, sid = editor.shadow_service, editor.shadow_session_id
        before = list(service.working_mesh(sid, clone=True).submeshes[0].vertices)
        _rig_command(editor, 4, "refit_fit_to_body", {})
        fitted = list(service.working_mesh(sid, clone=True).submeshes[0].vertices)
        assert fitted != before
        operations = service._session(sid).edit_operations
        _rig_command(editor, 5, "undo", {})
        assert service.working_mesh(sid, clone=True).submeshes[0].vertices == before
        _rig_command(editor, 6, "redo", {})
        assert service.working_mesh(sid, clone=True).submeshes[0].vertices == fitted
        assert service._session(sid).edit_operations == operations
        _rig_command(editor, 7, "morph_bake", {})
        finished = editor.finish(_request(editor, "finish_request", 8))
        assert all(asset["status"] == "passed"
                   for asset in finished["exact_output_validation"]["assets"])
        output = authority.working_mesh(editor.authoritative_session_id, clone=True)
        if appearance is not None:
            output = appearance.to_neutral(output)
        for actual, expected in zip(output.submeshes[0].vertices, fitted, strict=True):
            assert actual == pytest.approx(expected, abs=1e-6)
    finally:
        editor.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


@pytest.mark.parametrize("neutral", [False, True])
def test_refit_validation_reuses_channels_without_changing_source_or_export_ownership(tmp_path, neutral):
    from cdmw.services import mesh_archive_refit as owner
    from tests.test_mesh_neutral_face_editing import _appearance

    appearance = _appearance() if neutral else None
    _source, authority, editor, _primary, _armor, _loaded = _load_pair(
        tmp_path, assign_body=False, primary_appearance=appearance, incoming_appearance=appearance,
    )
    try:
        service = editor.shadow_service
        snapshot = service.capture_export_snapshot(editor.shadow_session_id)
        before = [list(part.vertices) for part in snapshot.mesh.submeshes]
        sources_before = [list(asset.source.mesh.submeshes[0].vertices)
                          for asset in snapshot.archive_refit_context.assets]
        exports = archive_refit_snapshots(snapshot)
        with patch.object(owner, "_archive_refit_snapshots", return_value=exports):
            expected = validate_archive_refit(service, snapshot)
        with patch.object(owner, "_clone", wraps=owner._clone) as clone:
            actual = validate_archive_refit(service, snapshot)
        assert actual == expected
        assert actual.ok
        assert clone.call_count == int(neutral)  # Only coordinate conversion needs owned geometry.
        assert [part.vertices for part in snapshot.mesh.submeshes] == before
        assert [asset.source.mesh.submeshes[0].vertices
                for asset in snapshot.archive_refit_context.assets] == sources_before

        # The public export path must still return independently editable copies.
        for _entry, component in exports:
            if component.mesh.lod_levels:
                assert component.mesh.submeshes is component.mesh.lod_levels[0]
            component.mesh.submeshes[0].vertices[0] = (42., 43., 44.)
        assert [part.vertices for part in snapshot.mesh.submeshes] == before
        assert [asset.source.mesh.submeshes[0].vertices
                for asset in snapshot.archive_refit_context.assets] == sources_before
    finally:
        editor.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


@pytest.mark.parametrize("damage", ["part_mapping", "topology", "source_validation"])
def test_refit_validation_keeps_source_and_topology_guards(tmp_path, damage):
    _source, authority, editor, _primary, _armor, _loaded = _load_pair(tmp_path, assign_body=False)
    try:
        service = editor.shadow_service
        snapshot = service.capture_export_snapshot(editor.shadow_session_id)
        context = snapshot.archive_refit_context
        if damage == "part_mapping":
            asset = replace(context.assets[-1], part_indices=context.assets[0].part_indices)
            snapshot = replace(snapshot, archive_refit_context=replace(context, assets=(*context.assets[:-1], asset)))
        elif damage == "topology":
            snapshot.mesh.submeshes[-1].faces[0] = (0, 2, 1)
        else:
            asset = replace(context.assets[-1], source=replace(
                context.assets[-1].source,
                no_op_roundtrip_report={"result": "FAIL", "byte_identical": False, "unexpected_differences": 1},
            ))
            snapshot = replace(snapshot, archive_refit_context=replace(context, assets=(*context.assets[:-1], asset)))
        if damage == "source_validation":
            report = validate_archive_refit(service, snapshot)
            assert not report.ok
            assert any("armor.pac" in issue.message for issue in report.blockers)
        else:
            with pytest.raises(ValueError, match="Part identities|source topology"):
                validate_archive_refit(service, snapshot)
    finally:
        editor.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)
