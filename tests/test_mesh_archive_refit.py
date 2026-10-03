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
               primary_appearance=None, incoming_appearance=None, role="armor", distinct_material=False):
    source, authority, session = _open_exact_session(
        tmp_path / "session", base_texture_path=texture_paths[0] if texture_paths else None,
        neutral_appearance=primary_appearance,
    )
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


def test_archive_refit_finish_and_build_mod_preserve_both_original_files(tmp_path):
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
            output_path=tmp_path / "mod", manager_profile="dmm",
        )
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors
        assert completed
        body_bytes = (tmp_path / "mod" / primary.path).read_bytes()
        armor_bytes = (tmp_path / "mod" / armor.path).read_bytes()
        assert parse_pac(body_bytes, primary.path).submeshes[0].vertices[0][0] == pytest.approx(0.4, abs=2e-5)
        assert parse_pac(armor_bytes, armor.path).submeshes[-1].vertices[0][0] == pytest.approx(0.7, abs=2e-5)
        assert primary.paz_file.read_bytes() == source
        assert primary.pamt_path.read_bytes() == b"owned archive index"
        metadata = json.loads((tmp_path / "mod/mesh-editor-session.json").read_text())
        assert {asset["path"] for asset in metadata["assets"]} == {primary.path, armor.path}
        assert authority.undo("authoritative-rust-exact").ok
        assert authority._session("authoritative-rust-exact").archive_refit_context is None
        assert authority.redo("authoritative-rust-exact").ok
        assert len(archive_refit_snapshots(authority.capture_export_snapshot("authoritative-rust-exact"))) == 2
    finally:
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)
