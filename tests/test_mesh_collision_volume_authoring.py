"""Collision shape edits through the Mesh Editor host: preview, Undo, Build Mod and drafts."""

from dataclasses import replace

import pytest

from cdmw.modding.pabv_parser import decode_pabv
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from cdmw.services.mesh_rust_authoring import read_owned_payload_reference
from tests.test_mesh_cloth_decoded_preview import collision_session  # noqa: F401 - fixture
from tests.test_mesh_jiggle_decoded_preview import decoded, rig_session  # noqa: F401 - fixtures
from tests.test_mesh_jiggle import archive_context, jiggle_session  # noqa: F401 - fixture
from tests.test_mesh_collision_archive_flow import _input
from tests.test_mesh_rust_replacement import command
from tests.test_pabv_parser import container, record


def _body(host, session, tmp_path):
    data = container(record(key=session.skeleton.bones[0].name_hash, parameters=(.5, 2.)),
                     record(key=0xA23A288E, parameters=(.3, 1.)))
    entry, prepared = _input(tmp_path, "body", data)
    command(host, "cloth_collision_input", {"role": "body", "_archive_entry": entry, "_archive_prepared": prepared})
    return entry.path, data


def _radii(host):
    payload = read_owned_payload_reference(host.root, decoded(host)["file"])
    return [round(row["radius"], 4) for row in payload["cloth"]["body_colliders"]]


def _edit(source, radius, host=None):
    return {**(archive_context(host) if host is not None else {}), "source": source, "copies": [], "changes": [
        {"ordinal": 0, "removed": False, "parameters": [radius, 2.0], "position": None}]}


def test_body_volume_edit_previews_undoes_ships_and_saves(collision_session, tmp_path):  # noqa: F811
    original, session, host = collision_session
    path, data = _body(host, session, tmp_path)
    sources = {row["source"]: row for row in host.state_payload()["collision_volumes"]["sources"]}
    assert path in sources and sources[path]["shared"] and sources[path]["available"]
    assert [row["parameters"] for row in sources[path]["rows"]][0] == pytest.approx([.5, 2.])
    assert _radii(host)[0] == .5

    result = command(host, "replacement_collision_volumes", _edit(path, .25, host))
    assert result["state"]["collision_volumes"]["active"]
    assert _radii(host)[0] == .25
    snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
    output = prepare_replacement_output(snapshot)
    shipped = [file for file in output.companion_files if file.path == path] if hasattr(output, "companion_files") else \
        [file for file in output.files if file.path == path]
    assert len(shipped) == 1
    assert decode_pabv(shipped[0].data).volumes[0].parameters == pytest.approx((.25, 2.))
    assert decode_pabv(shipped[0].data).volumes[1].parameters == decode_pabv(data).volumes[1].parameters
    assert session.original_data == original

    draft_root = tmp_path / "draft"
    draft_root.mkdir()
    payload = save_replacement_state(snapshot.replacement_state, draft_root, draft_root)
    assert payload["version"] == 17
    loaded = load_replacement_state(payload, draft_root)
    assert loaded.collision_edits == snapshot.replacement_state.collision_edits
    assert any(file.path == path and file.data == data for file in loaded.dependencies)

    command(host, "undo")
    assert not host.state_payload()["collision_volumes"]["active"]
    assert _radii(host)[0] == .5
    command(host, "redo")
    assert _radii(host)[0] == .25
    command(host, "replacement_collision_volumes", {"source": path, "reset": True})
    assert not host.state_payload()["collision_volumes"]["active"]
    assert _radii(host)[0] == .5


@pytest.mark.parametrize("arguments, message", [
    ({"changes": [{"ordinal": 1, "removed": True, "parameters": None, "position": None}], "copies": []},
     "Bip01 Head"),
    ({"changes": [{"ordinal": 9, "removed": True, "parameters": None, "position": None}], "copies": []},
     "does not exist"),
    ({"changes": [], "copies": [], "bogus": 1}, "Choose a collision volume set"),
    ({"changes": [{"ordinal": 0, "removed": False, "parameters": [-1.0, 2.0], "position": None}], "copies": []},
     "greater than zero"),
])
def test_invalid_edits_change_nothing(collision_session, tmp_path, arguments, message):  # noqa: F811
    from cdmw.services.mesh_rust_authoring import RustMeshValidationError
    _, session, host = collision_session
    path, _ = _body(host, session, tmp_path)
    revision, history = session.revision, len(session.undo_stack)
    with pytest.raises((ValueError, RustMeshValidationError), match=message):
        command(host, "replacement_collision_volumes", {**archive_context(host), "source": path, **arguments})
    assert session.revision == revision and len(session.undo_stack) == history
    assert not host.state_payload()["collision_volumes"]["active"]


def test_local_files_are_previewed_but_not_offered_for_editing(collision_session, tmp_path):  # noqa: F811
    _, session, host = collision_session
    body = tmp_path / "body.pabv"
    body.write_bytes(container(record(key=session.skeleton.bones[0].name_hash, parameters=(.5, 2.))))
    command(host, "cloth_collision_input", {"role": "body", "path": str(body)})
    sources = host.state_payload()["collision_volumes"]["sources"]
    assert all(row["role"] != "body" for row in sources)
    with pytest.raises(ValueError, match="Load that collision volume set"):
        command(host, "replacement_collision_volumes", _edit("character/body/reference.pabv", .25, host))
