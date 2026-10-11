"""Experimental jiggle edits change one lane and survive the real editor flow."""

from contextlib import ExitStack
import copy
from dataclasses import replace
import hashlib
import json
import struct
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.domain.mesh.jiggle import PacJiggleRule
from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_jiggle import apply_pac_jiggle_rules
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from tests.test_mesh_cloth_influence import cloth_fixture
from tests.test_mesh_editor_replacement_regressions import _distinct_lods
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
from tests.test_mesh_rust_replacement import command
from tests.test_mesh_cloth_influence import apply_rule, shadow_output
from tests.test_mesh_editor_replacement_sequences import open_editor
from tests.test_mesh_rust_authoring_exact_output import _request
from tests.test_mesh_rust_replacement import prepare_source


def jiggle_fixture(source=None):
    data = bytearray(cloth_fixture() if source is None else source)
    for lod, mesh in enumerate(pac_cloth_lods(data)):
        for part in mesh.submeshes:
            for vertex, offset in enumerate(part.source_vertex_offsets):
                data[offset + 36:offset + 39] = bytes((40 + vertex, 100 + lod, 249 + vertex % 7))
    return bytes(data)


@pytest.fixture
def jiggle_session(tmp_path, monkeypatch):
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: jiggle_fixture())
    source, service, host = _open_exact_session(tmp_path / "session")
    yield source, service, host
    if not host.closed:
        host.cancel()
    service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def archive_context(host):
    return {
        "_archive_entry": ArchiveEntry("owned-rust-exact.pac", host.root / "0009/0.pamt",
                                       host.root / "0009/0.paz", 0, 0, 0, 0, 0),
        "_archive_dependencies": SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={}),
    }


def set_jiggle(host, below_y=None, *, reset=False):
    key = host.state_payload()["jiggle"]["parts"][0]["id"]
    return command(host, "replacement_jiggle", {
        "part_ids": [key], "rule": {"below_y": below_y}, "reset": reset, **archive_context(host),
    })


@pytest.mark.parametrize("blocker", ["profile", "archive_bindings"])
def test_morph_refit_reports_blocked_physics_and_recovers(jiggle_session, monkeypatch, blocker):
    from cdmw.services.mesh_rust_cloth import cloth_ui_state, physics_detection_ui_state
    from cdmw.services.mesh_rust_jiggle import jiggle_ui_state
    from cdmw.services.mesh_rust_replacement import replacement_ui_state

    source, _, host = jiggle_session
    session = host.shadow_service._session(host.shadow_session_id)

    def inspect():
        replacement = replacement_ui_state(host)
        cloth = cloth_ui_state(host, replacement)
        jiggle = jiggle_ui_state(host, replacement)
        physics = physics_detection_ui_state(replacement, cloth, jiggle, {})
        return replacement, cloth, jiggle, physics

    original = inspect()
    assert original[2]["available"] and original[2]["overlay_parts"]
    with monkeypatch.context() as patch:
        if blocker == "profile":
            patch.setitem(host.shadow_service._morph_sessions, host.shadow_session_id,
                          SimpleNamespace(profile=object()))
        else:
            patch.setattr(session, "archive_refit_context", object())
        replacement, cloth, jiggle, physics = inspect()
        assert not replacement["available"]
        assert replacement["blocked_by"] == "morph_refit"
        for state in (cloth, jiggle):
            assert not state["available"]
            assert state["blocked_by"] == "morph_refit"
            assert state["reason"] == (
                "Physics inspection is blocked by Morph & Refit. Existing physics data is unchanged."
            )
        assert jiggle["overlay_parts"] == []
        assert physics["parts"]
        assert all(part["kind"] == "blocked" for part in physics["parts"])
        assert all(part["reason"] == jiggle["reason"] for part in physics["parts"])

    restored = inspect()
    assert restored == original
    assert session.original_data == source


@pytest.mark.parametrize("below_y", [None, .5])
def test_selected_region_changes_only_byte_38_at_every_lod(below_y):
    source = jiggle_fixture(_distinct_lods())
    result = apply_pac_jiggle_rules(source, {0: PacJiggleRule(below_y)})
    expected_addresses = set()
    for level in pac_cloth_lods(source):
        part = level.submeshes[0]
        expected_at_lod = {offset + 38 for point, offset in zip(part.vertices, part.source_vertex_offsets)
                           if below_y is None or point[1] < below_y}
        assert expected_at_lod
        expected_addresses.update(expected_at_lod)
    assert len(result) == len(source)
    assert {i for i, (a, b) in enumerate(zip(source, result)) if a != b} == expected_addresses
    assert all(result[address] == 255 for address in expected_addresses)
    assert apply_pac_jiggle_rules(result, {0: PacJiggleRule(below_y)}) == result
    assert apply_pac_jiggle_rules(source, {}) == source
