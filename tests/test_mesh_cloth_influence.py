"""Cloth edits own only proven render bindings, at every stored PAC LOD."""

from contextlib import ExitStack
import copy
from dataclasses import replace
import struct
import json
import hashlib
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.modding.mesh_parser import _decode_pac_skin_influences, parse_pac
from cdmw.modding.pac_cloth import apply_pac_cloth_rules, pac_cloth_binding, pac_cloth_lods
from cdmw.modding.mesh_skinning import pack_pac_skin_weights
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from cdmw.services.mesh_replacement_import import initial_replacement_state
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
from tests.test_mesh_rust_replacement import command
from tests.test_mesh_rust_authoring_exact_output import _request
from tests.test_mesh_rust_replacement import prepare_source


def cloth_fixture():
    data = bytearray(_pac_fixture(skinned=True))
    for mesh in pac_cloth_lods(data):
        for part in mesh.submeshes:
            for i, offset in enumerate(part.source_vertex_offsets):
                if i == 0:
                    continue  # A genuinely rigid vertex must never acquire cloth.
                struct.pack_into("<2e", data, offset + 12, 102.0, 103.0)
                struct.pack_into("<I", data, offset + 24, 100 << 10 | 101 << 20 | 0xC0000000)
                data[offset + 32:offset + 36] = bytes((104, 82, 42, 27))
                data[offset + 39] = 0xC0
    return bytes(data)


@pytest.mark.parametrize("rule", [PacClothRule(0), PacClothRule(.5), PacClothRule(1, .5), PacClothRule(.7, .5, .3)])
def test_rules_apply_at_every_lod_and_preserve_all_other_bytes(rule):
    source = cloth_fixture()
    result = apply_pac_cloth_rules(source, {0: rule})
    expected = bytearray(source)
    for mesh in pac_cloth_lods(source):
        for part in mesh.submeshes:
            for position, offset in zip(part.vertices, part.source_vertex_offsets):
                binding = pac_cloth_binding(source, offset)
                if binding is None:
                    continue
                blend = rule.blend(binding[0], position[1])
                if blend == 63:
                    group = struct.unpack_from("<I", source, offset + 24)[0]
                    struct.pack_into("<I", expected, offset + 24, group & 0xC00003FF)
                    expected[offset + 12:offset + 16] = b"\0\0\0\x3c"
                    expected[offset + 32:offset + 36] = bytes(4)
                expected[offset + 39] = 0xC0 | blend
                assert _decode_pac_skin_influences(result, offset) == _decode_pac_skin_influences(source, offset)
    assert result == expected
    assert apply_pac_cloth_rules(source, {0: rule}) == result
    assert apply_pac_cloth_rules(source, {0: PacClothRule()}) == source


@pytest.fixture
def cloth_session(tmp_path, monkeypatch):
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: cloth_fixture())
    source, service, session = _open_exact_session(tmp_path / "session")
    yield source, service, session
    if not session.closed:
        session.cancel()
    service.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def apply_rule(session, tmp_path, rule, *, reset=False):
    part_id = session.state_payload()["cloth"]["parts"][0]["id"]
    return command(session, "replacement_cloth", {"part_ids": [part_id], "reset": reset,
        "rule": rule.to_dict(),
        "_archive_entry": ArchiveEntry("owned-rust-exact.pac", tmp_path / "0009/0.pamt", tmp_path / "0009/0.paz", 0, 0, 0, 0, 0),
        "_archive_dependencies": SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})})


def shadow_output(session):
    snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
    if snapshot.replacement_state is None:
        return snapshot.original_data
    return prepare_replacement_output(snapshot).data
