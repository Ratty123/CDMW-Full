"""The reviewed selection is complete, immutable and isolated from the live scene."""
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_placement_studio_operations as fixtures
from tools.placement_studio import carry
from tools.placement_studio.move_operation import MoveRequest, MoveBlocked, plan_move
from tools.placement_studio.prepared_move import prepare_move, preview_session, digest
from tools.paa_motion.format import MotionClip, BoneTrack
from tools.paa_motion.encode import encode_paa


def payload(value):
    return encode_paa(MotionClip((2, 3), 0, "", 1, "", 1, 0, 1, 0,
                                (BoneTrack(1, translation=((0, (value, 0., 0.)),)),)))


def setup():
    session, edits = fixtures._session(), fixtures._edits()
    weapon = fixtures._weapon(session, "cd_phm_02_sword_0001")
    session.select_weapon(weapon)
    unit = session.resolve_equipment_unit("CD_TwoHandWeapon_Sword", weapon=weapon,
                 available_families={carry.family_of(c.name) for c in fixtures.CLIP_INDEX})
    rows = carry.swappable_pairs(unit, fixtures.CLIP_INDEX, carry.AnimationScope(carry.SCOPE_DRAW_STOW))
    plan = plan_move(session, edits, MoveRequest(unit, "Pelvis_R_Socket", replacements=rows, orientation_reviewed=True))
    targets = {r.target_path for r in rows}
    read = lambda entry: payload(0 if entry.path in targets else .5)
    return session, edits, plan, read


def test_preparation_and_preview_never_touch_live_history():
    session, edits, plan, read = setup()
    snapshot = edits.capture()
    result = prepare_move(session, snapshot, plan, read=read)
    assert edits.capture() == snapshot
    before = preview_session(session, result.before_files, plan.unit)
    after = preview_session(session, result.after_files, plan.unit)
    assert before.descriptor_part(plan.unit.primary_part).in_socket != after.descriptor_part(plan.unit.primary_part).in_socket
    assert after.descriptor_part(plan.unit.primary_part).in_socket == "Pelvis_R_Socket"
    assert edits.operations() == []
    operation = result.apply(session, edits)
    assert set(operation.replaced_clips()) == {r.target_path for r in plan.request.replacements}
    exported = edits.preview_for_operations([operation.operation_id])
    assert {p: digest(b) for p, b in exported.items()} == {f.path: digest(f.data) for f in result.changed_files}
    assert json.loads(operation.preparation_json)["in_game"] == "Unverified"


def test_missing_donor_and_invalid_payload_fail_without_changing_session():
    session, edits, plan, read = setup()
    snapshot = edits.capture()
    bad = plan.request.replacements[-1].donor.path
    with pytest.raises(MoveBlocked, match="Cannot prepare"):
        prepare_move(session, snapshot, plan, read=lambda entry: b"broken" if entry.path == bad else read(entry))
    assert edits.capture() == snapshot


def test_stale_session_or_changed_sources_cannot_apply():
    session, edits, plan, read = setup()
    prepared = prepare_move(session, edits.capture(), plan, read=read)
    edits.set_translation(fixtures.BODY, "Pelvis_R_Socket", fixtures.Vec3(.2, 0, 0))
    with pytest.raises(MoveBlocked, match="session changed"):
        prepared.apply(session, edits)
    identities = iter([("old",), ("new",)])
    with pytest.raises(MoveBlocked, match="Source files changed"):
        prepare_move(session, edits.capture(), plan, read=read, identity=lambda: next(identities))


def test_identical_animation_payload_is_listed_but_not_applied():
    session, edits, plan, read = setup()
    prepared = prepare_move(session, edits.capture(), plan, read=lambda entry: payload(0))
    assert all(not f.changed for f in prepared.files if f.donor_path)
    operation = prepared.apply(session, edits)
    assert operation.replaced_clips() == ()
    assert operation.routed_parts()


def test_sparse_operation_ids_cannot_merge_earlier_edits_into_preparation():
    from tools.placement_studio.editing import EditSession
    session, edits, plan, read = setup()
    for _ in range(2):
        edits.begin_operation().rollback()
    earlier = edits.begin_operation()
    edits.set_translation(fixtures.BODY, "Pelvis_L_Socket", fixtures.Vec3(.2, 0, 0))
    earlier.commit()
    snapshot = edits.capture()
    isolated = EditSession.from_snapshot(snapshot)
    next_operation = isolated.begin_operation()
    assert next_operation.operation_id != earlier.operation_id
    next_operation.rollback()
    prepared = prepare_move(session, snapshot, plan, read=read)
    assert edits.capture() == snapshot
    from tools.placement_studio.documents import SocketDocument
    for files in (prepared.before_files, prepared.after_files):
        document = SocketDocument.load(dict(files)[fixtures.BODY], fixtures.BODY)
        assert document.socket_map()['Pelvis_L_Socket'].translation.x == .2
    result = prepared.apply(session, edits)
    assert result.operation_id != earlier.operation_id
    assert all(command.target != "Pelvis_L_Socket" for command in result.commands)


def test_nonfinite_donor_channel_blocks_the_complete_operation():
    session, edits, plan, read = setup()
    snapshot = edits.capture()
    bad = plan.request.replacements[-1].donor.path
    with pytest.raises(MoveBlocked, match="Non-finite"):
        prepare_move(session, snapshot, plan,
                     read=lambda entry: payload(float('nan')) if entry.path == bad else read(entry))
    assert edits.capture() == snapshot
