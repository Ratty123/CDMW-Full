"""Owned rig transport for the native preview, without changing authored PACs."""

import json

import pytest

from cdmw.modding.skeleton_parser import parse_pab
from cdmw.services.mesh_rust_authoring import read_owned_payload_reference
from tests.test_mesh_jiggle import jiggle_session, set_jiggle, shadow_output
from tests.test_pab_bind_transforms import fixture


@pytest.fixture
def rig_session(jiggle_session, monkeypatch):
    source, service, host = jiggle_session
    session = host.shadow_service._session(host.shadow_session_id)
    session.skeleton = parse_pab(fixture()[0], "owned.pab")
    # A synthetic two-bone rig covers all eight slots used by the owned PAC.
    monkeypatch.setattr("cdmw.modding.mesh_parser.resolve_pac_bone_palette", lambda *_: (0, 1) * 4)
    return source, session, host


def decoded(host):
    return host.state_payload(include_document=False)["jiggle"]["decoded"]


def test_decoded_jiggle_snapshot_is_owned_cached_and_preserves_original_records(rig_session, monkeypatch):
    source, session, host = rig_session
    import cdmw.services.mesh_rust_authoring as authoring
    writes = []
    atomic = authoring._atomic_write_payload

    def write(root, name, *args, **kwargs):
        if name == "jiggle-rig.json":
            writes.append(name)
        return atomic(root, name, *args, **kwargs)

    monkeypatch.setattr(authoring, "_atomic_write_payload", write)
    state = decoded(host)
    assert state["available"], state
    payload = read_owned_payload_reference(host.root, state["file"])
    assert payload["version"] == 1
    assert payload["rig"]["parents"] == [-1, 0]
    assert payload["rig"]["bone_palette"] == [0, 1] * 4
    assert len(payload["rig"]["neutral_local_matrices"][0]) == 4
    part = session.working_mesh.submeshes[0]
    records = [source[offset:offset + 40].hex() for offset in part.source_vertex_offsets]
    assert payload["parts"] == [{"index": 0, "records": records}]
    assert decoded(host) == state
    # Geometry and contribution edits do not rewrite the invariant rig/weights.
    session.revision += 1
    assert decoded(host) == state
    set_jiggle(host)
    assert decoded(host) == state
    assert writes == ["jiggle-rig.json"]
    assert session.original_data == source
    assert shadow_output(host) != source
    host.cancel()  # Owned-tree cleanup must accept this new payload filename.
