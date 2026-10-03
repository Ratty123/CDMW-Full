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
