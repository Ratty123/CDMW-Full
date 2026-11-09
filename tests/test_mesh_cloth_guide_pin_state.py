"""Create cloth guides in the Mesh Editor host: pin counts, saved pins and a refused build."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.cloth_guides import PacClothGuideRule
from cdmw.services import mesh_rust_cloth_guides as guides
from tests.test_pac_cloth_guide_builder import PALETTE, POINTS, guide_free_pac


@dataclass(frozen=True)
class Part:
    part_id: str = "a"
    target_index: int = 0
    included: bool = True
    cloth_guides: object = None
    cloth: object = None


@dataclass(frozen=True)
class State:
    parts: tuple = ()
    revision: int = 1
    neutral_appearance: object = None


@dataclass(frozen=True)
class Snapshot:
    replacement_state: object
    original_data: bytes = b""


def host(mesh_pins, rule):
    """A host around one guide-free PAC part whose working mesh carries ``mesh_pins``."""
    data = guide_free_pac(lods=3)
    state = State((Part(cloth_guides=rule),))
    session = SimpleNamespace(
        mesh_format="pac", hair_state=None, original_data=data, replacement_state=state,
        skeleton=SimpleNamespace(bones=[SimpleNamespace(name_hash=value) for value in PALETTE]),
        working_mesh=SimpleNamespace(submeshes=[SimpleNamespace(vertices=list(POINTS), cloth_pin=mesh_pins)]),
        revision=1, material_generation=0)
    authoring = SimpleNamespace(
        shadow_service=SimpleNamespace(_session=lambda _id: session,
                                       capture_export_snapshot=lambda _id: Snapshot(state, data)),
        shadow_session_id=1, cloth_guide_layout_cache=None, cloth_guide_output_cache=None,
        neutral_appearance=None, replacement_comparison="edited")
    replacement = {"reason": "", "parts": [{"id": "a", "index": 0, "included": True, "name": "guide0"}]}
    return authoring, session, state, replacement


def pinned(point):
    return PacClothGuideRule(0, None, PALETTE, pinned_points=(point,))


@pytest.mark.parametrize("mesh_pins, live, changed", [
    ([False, False, True, False], 1, False),   # the pin the guides were made with
    ([False, False, False, True], 1, True),    # repainted since
    ([], 0, False),                            # a reopened draft: the rule still holds its pins
])
def test_state_counts_live_and_saved_pins_and_says_when_they_differ(mesh_pins, live, changed):
    authoring, _, _, replacement = host(mesh_pins, pinned(POINTS[2]))
    state = guides.guide_authoring_ui_state(authoring, replacement)
    row, = state["parts"]
    assert state["available"] and state["active"]
    assert (row["pinned_count"], row["rule_pinned_count"], row["pins_changed"]) == (live, 1, changed)
    # The pin positions stay out of the state payload.
    assert row["rule"] == {"source_lod": 0, "fixed_above": None, "reduce_skinning": False, "pins": True}


def test_update_keeps_saved_pins_when_the_mesh_carries_none(monkeypatch):
    from cdmw.services import mesh_rust_replacement
    authoring, _, state, replacement = host([], pinned(POINTS[2]))
    monkeypatch.setattr(mesh_rust_replacement, "replacement_ui_state", lambda _authoring: replacement)
    monkeypatch.setattr(guides, "mesh_with_part_ids", lambda _snapshot, _state: None)
    monkeypatch.setattr(guides, "commit_replacement", lambda _service, _snapshot, _mesh, new, **_: new)
    snapshot = Snapshot(state, guide_free_pac(lods=3))
    arguments = {"part_ids": ["a"], "source_lod": 1, "fixed_above": None, "reduce_skinning": False, "use_pins": True}
    result = guides.set_guide_rule(authoring, snapshot, arguments, entry=None, dependencies=(), stop_event=None)
    rule = result.parts[0].cloth_guides
    assert rule.pinned_points == (POINTS[2],) and rule.source_lod == 1 and result.revision == 2

    bare, _, bare_state, bare_replacement = host([], None)
    monkeypatch.setattr(mesh_rust_replacement, "replacement_ui_state", lambda _authoring: bare_replacement)
    with pytest.raises(ValueError, match="has no painted pins"):
        guides.set_guide_rule(bare, Snapshot(bare_state, guide_free_pac(lods=3)), arguments,
                              entry=None, dependencies=(), stop_event=None)


def test_a_refused_guide_build_is_asked_once_per_change(monkeypatch):
    from cdmw.services import mesh_replacement_output
    authoring, session, _, _ = host([], pinned(POINTS[2]))
    calls = []

    def refuse(snapshot):
        calls.append(snapshot)
        raise ValueError("Cloth pins on guide0 no longer line up with its vertices.")

    monkeypatch.setattr(mesh_replacement_output, "prepare_replacement_output", refuse)
    for _ in range(3):
        with pytest.raises(ValueError, match="no longer line up"):
            guides.authored_cloth_source(authoring, session)
    assert len(calls) == 1 and calls[0].replacement_state.parts[0].cloth is None
    session.revision = 2
    with pytest.raises(ValueError, match="no longer line up"):
        guides.authored_cloth_source(authoring, session)
    assert len(calls) == 2
    authoring.replacement_comparison = "original"
    assert guides.authored_cloth_source(authoring, session) == (session.original_data, None)
