"""On the back: one kind of item moved by its own child point, saved as a DMM set patch.

* An item's socket file whose change is `<set>` lines only is written as a
  `.sockets.xml.patch` that finds each point by `Name` and `Parent`; any other change keeps
  the file whole, as before.
* `back_move` moves the item in the back's plane and turns that back into the child point,
  so the body point (shared with spears and tools) is left alone.
* The sword's sheath files, and files that hang the same kind of item on the same line, move
  with it; another kind of item on the same body point does not.
* Fine-tune's On the back row writes those files, and saving gives one patch per file.

Synthetic files and rigs, except the `real_game` tests at the end, which read the installed
game's files into a temporary folder, change nothing, and check the values against the test
Core that moved Kliff's 2H sword in game on 2026-11-17.
"""

from __future__ import annotations

import math
import tempfile
import zipfile
from pathlib import Path

import pytest

from tests.test_placement_studio_carry_points import (  # noqa: F401
    _bone,
    _same_rotation,
    window_factory,
)
from tests.test_placement_studio_operations import _Baseline
from tools.placement_studio import back_move, carry_plan, corpus, dmm_patch, save_mod
from tools.placement_studio.dmm_patch import PatchError
from tools.placement_studio.documents import SocketDocument, is_weapon_socket_file
from tools.placement_studio.editing import EditSession
from tools.placement_studio.model import Quat, Socket, Vec3
from tools.placement_studio.resolver import PlacementResolver
from tools.placement_studio.session import PlacementSession
from tools.placement_studio.skeleton import BoneHierarchy, multiply

SB = "character/descriptors/socketbonedata/1_pc/1_phm/"
TWO = SB + "weapon/2_twohandweapon/"
BODY = SB + "phm_01.pab.sockets.xml"
DESC = "character/descriptors/characterdescription/phm_description_player_kliff.xml"
ALIAS = "character/phm_description_player_kliff.xml"
SWORD = TWO + "cd_phm_02_sword_0001.sockets.xml"
SHEATH = TWO + "cd_phm_02_sword_0001_in.sockets.xml"
SHEATH_15 = TWO + "cd_phm_02_sword_0015_in.sockets.xml"
LONG = TWO + "cd_phm_02_sword_0002.sockets.xml"
OWN_WAY = TWO + "cd_phm_02_sword_0045.sockets.xml"
SPEAR = TWO + "cd_phm_02_spear_0001.sockets.xml"
BACK = "Spine2_B_SubWeapon_Socket"
CHILD = "Spine2_B_SubWeapon_ChildSocket"
FLIPPED = "0.000000 1.000000 0.000000 0.000000"
IDENT = "0.000000 0.000000 0.000000 1.000000"
GAME_CHILD = f"{FLIPPED}|0.000000 0.000000 -0.470292"


def _file(*rows: str, stack: str = "") -> bytes:
    body = "".join(f'\t\t<Socket Name="{n}" Parent="{p}" Rotation="{r}" Translation="{t}"/>\r\n'
                   for n, p, r, t in (row.split("|") for row in rows))
    extra = f'\t<StackEquipInfo>\r\n\t\t<Socket Name="{stack}"/>\r\n\t</StackEquipInfo>\r\n' \
        if stack else ""
    return (f'<SocketBoneData>\r\n\t<SocketList Count="{len(rows)}">\r\n{body}'
            f'\t</SocketList>\r\n{extra}</SocketBoneData>\r\n').encode()


def _item(child: str = GAME_CHILD, **kw) -> bytes:
    return _file(f"Basic_ChildSocket|B_Weapon_0001|{IDENT}|0.000000 0.000000 0.000000",
                 f"{CHILD}|B_Weapon_0001|{child}", **kw)


#: The item lies with its y axis out of the back and its tip down, as the game's 2H sword
#: does: the back point is turned a quarter about x on a slightly bent spine bone.
BACK_ROTATION = Quat.from_axis_angle(Vec3(1.0, 0.0, 0.0), 90.0)
BODY_BYTES = _file(f"{BACK}|Bip01 Spine2|{BACK_ROTATION.format()}|0.000000 0.150000 -0.120000",
                   f"RHand_Socket|Bip01 R Hand|{IDENT}|0.000000 0.000000 0.000000")


def _row(name: str, case: str = "") -> str:
    tail = f' WeaponCasePart="{case}"' if case else ""
    out = ' OutSocketBone="RHand_Socket" OutChildSocketBone="Basic_ChildSocket"' if not \
        name.endswith("_IN") else ' OutSocketBone="" OutChildSocketBone=""'
    return (f'\t<Part PartName="{name}" InSocketBone="{BACK}" InChildSocketBone="{CHILD}"'
            f'{out}{tail}/>\r\n')


DESC_BYTES = ("<CharacterDescription>\r\n" + _row("TwoHandWeapon_Sword", "TwoHandWeapon_Sword_IN")
              + _row("TwoHandWeapon_Sword_IN") + _row("TwoHandWeapon_Spear")
              + "</CharacterDescription>\r\n").encode("utf-8")

FILES = {
    BODY: BODY_BYTES, DESC: DESC_BYTES, ALIAS: DESC_BYTES,
    SWORD: _item(), SHEATH: _item(), SHEATH_15: _item(),
    # Turned half about the blade and 12 cm along it: the same line, its own child.
    LONG: _item("1.000000 0.000000 0.000000 0.000000|0.000000 0.000000 -0.350292"),
    # Hangs 4 cm to one side of that line.
    OWN_WAY: _item(f"{FLIPPED}|0.040000 0.000000 -0.470292"),
    SPEAR: _item(),
}


def _rig() -> BoneHierarchy:
    return BoneHierarchy([
        _bone(0, "Bip01 Pelvis", -1, translation=Vec3(0.0, 1.0, 0.0)),
        _bone(1, "Bip01 L Thigh", 0, translation=Vec3(0.1, 0.9, 0.0)),
        _bone(2, "Bip01 R Thigh", 0, translation=Vec3(-0.1, 0.9, 0.0)),
        _bone(3, "Bip01 Spine2", 0, Quat.from_euler_degrees(4.0, 0.0, 2.0),
              Vec3(0.0, 1.45, 0.12)),
        _bone(4, "Bip01 R Hand", 0, translation=Vec3(-0.4, 1.1, 0.2)),
    ], "test")


def _socket(path: str, name: str = CHILD) -> Socket:
    return SocketDocument.load(FILES[path], path).socket_map()[name]


def _body() -> Socket:
    return SocketDocument.load(BODY_BYTES, BODY).socket_map()[BACK]


class _Weapon:
    def __init__(self, path: str, files=FILES) -> None:
        self.game_path = path
        self.sockets = SocketDocument.load(files[path], path).socket_map()


def _weapons(files=FILES):
    return [_Weapon(path, files) for path in files if is_weapon_socket_file(path)]


def _value(socket: Socket) -> tuple:
    return socket.parent_bone, socket.rotation.format(), socket.translation.format()


def _point(m) -> tuple:
    return (m[12], m[13], m[14])


def _near(a, b, tolerance=1e-5) -> bool:
    return max(abs(x - y) for x, y in zip(a, b)) <= tolerance


# ── the patch ────────────────────────────────────────────────────────


def test_an_item_file_is_patched_with_two_set_lines_found_by_name_and_parent() -> None:
    base = _item(stack=CHILD).decode()
    edited = base.replace("0.000000 0.000000 -0.470292", "0.177976 -0.030000 -0.164176")
    edited = edited.replace(f'Rotation="{FLIPPED}" Translation="0.177976',
                            'Rotation="0.000000 0.953717 0.000000 0.300706" '
                            'Translation="0.177976')
    patch = dmm_patch.make_patch(SWORD, base.encode(), edited.encode()).decode()
    head = f'<set find="Socket" match-Name="{CHILD}" match-Parent="B_Weapon_0001"'
    assert patch == ("<xml-patch>\n"
                     f'\t{head} attr="Rotation" value="0.000000 0.953717 0.000000 0.300706"/>\n'
                     f'\t{head} attr="Translation" value="0.177976 -0.030000 -0.164176"/>\n'
                     "</xml-patch>\n")
    # The bare reference under StackEquipInfo has no Parent, so the filters skip it.
    assert dmm_patch.apply_patch(base, patch) == edited
    assert dmm_patch.patchable(SWORD) == "weapon_sockets"
    assert dmm_patch.patchable(BODY) == "body_sockets"


def test_an_item_file_whose_change_a_set_cannot_express_stays_whole() -> None:
    base = FILES[SWORD]
    added = base.replace(b'Count="2"', b'Count="3"').replace(
        b"\t</SocketList>",
        b'\t\t<Socket Name="Pelvis_L_ChildSocket" Parent="B_Weapon_0001" '
        b'Rotation="0 0 0 1" Translation="0 0 0"/>\r\n\t</SocketList>')
    with pytest.raises(PatchError):
        dmm_patch.make_patch(SWORD, base, added)
    moved = base.replace(b"-0.470292", b"-0.400000")
    lowered = dmm_patch.lower_for_dmm({SWORD: added, SHEATH: moved, BODY: BODY_BYTES},
                                      lambda path: FILES.get(path))
    assert lowered.files[SWORD] == added
    assert [path for path, _why in lowered.kept_whole] == [SWORD]
    assert lowered.patched == (SHEATH,)
    assert dmm_patch.patch_path(SHEATH) in lowered.files and SHEATH not in lowered.files


def test_a_point_with_no_parent_bone_keeps_its_file_whole() -> None:
    base = _item().replace(b'"Spine2_B_SubWeapon_ChildSocket" Parent="B_Weapon_0001"',
                           b'"Spine2_B_SubWeapon_ChildSocket" Parent=""')
    moved = base.replace(b"-0.470292", b"-0.400000")
    lowered = dmm_patch.lower_for_dmm({SWORD: moved}, lambda path: base)
    assert lowered.files == {SWORD: moved} and not lowered.patched


def test_a_body_file_a_patch_cannot_express_still_blocks() -> None:
    removed = BODY_BYTES.replace(b'Count="2"', b'Count="1"').split(b"\t\t<Socket Name=\"RHand")[0]
    removed += b"\t</SocketList>\r\n</SocketBoneData>\r\n"
    with pytest.raises(PatchError):
        dmm_patch.lower_for_dmm({BODY: removed}, lambda path: FILES.get(path))


# ── the move ─────────────────────────────────────────────────────────


def _moved(key: str, amount: float, child: Socket = None):
    rig, body = _rig(), _body()
    child = child or _socket(SWORD)
    plan = back_move.plan_back_move(rig, body, SWORD, child, _socket(SWORD), key=key,
                                    amount=amount)
    before = carry_plan.weapon_world(rig, body, child)
    after = carry_plan.weapon_world(rig, body, plan.sockets[0][1])
    return before, after, back_move.back_plane(carry_plan.weapon_world(rig, body,
                                                                       _socket(SWORD)))


def test_the_back_plane_faces_out_of_the_back() -> None:
    _before, _after, plane = _moved("out", 0.0)
    assert plane.normal[2] > 0.9
    assert plane.across[0] > 0.9 and abs(plane.across[1]) < 1e-9
    assert plane.up[1] > 0.9


def test_out_along_and_across_shift_the_item_and_keep_its_angle() -> None:
    before, after, plane = _moved("out", 0.03)
    shift = tuple(a - b for a, b in zip(_point(after), _point(before)))
    assert _near(shift, tuple(0.03 * c for c in plane.normal))
    assert _near(after[:12], before[:12])

    before, after, _plane = _moved("along", -0.25)
    tip = tuple(-before[8 + i] for i in range(3))
    shift = tuple(a - b for a, b in zip(_point(after), _point(before)))
    assert _near(shift, tuple(0.25 * c for c in tip))   # lower: toward the tip

    before, after, plane = _moved("across", 0.05)
    shift = tuple(a - b for a, b in zip(_point(after), _point(before)))
    assert abs(math.sqrt(sum(c * c for c in shift)) - 0.05) < 1e-5
    assert sum(a * b for a, b in zip(shift, plane.across)) > 0       # toward the left arm
    assert abs(sum(a * b for a, b in zip(shift, plane.normal))) < 1e-5


def test_a_turn_keeps_the_guard_in_place_and_turns_clockwise_from_behind() -> None:
    before, after, plane = _moved("turn", 35.0)
    guard = back_move.TWO_HAND_GUARD

    def guard_of(m):
        return tuple(m[12 + i] - guard * m[8 + i] for i in range(3))

    assert _near(guard_of(after), guard_of(before))
    # Seen from behind (+x to the viewer's left), a clockwise turn swings the tip, which
    # points down, toward the viewer's left: +x.
    tip_before = tuple(-before[8 + i] for i in range(3))
    tip_after = tuple(-after[8 + i] for i in range(3))
    assert tip_after[0] - tip_before[0] > 0.3
    angle = math.degrees(math.acos(sum(a * b for a, b in zip(tip_before, tip_after))))
    assert abs(angle - 35.0) < 1e-3
    assert abs(sum(a * b for a, b in zip(tip_after, plane.normal))
               - sum(a * b for a, b in zip(tip_before, plane.normal))) < 1e-5


def test_tip_out_points_the_tip_out_of_the_back() -> None:
    before, after, plane = _moved("tip_out", 10.0)
    tip_before = tuple(-before[8 + i] for i in range(3))
    tip_after = tuple(-after[8 + i] for i in range(3))
    assert (sum(a * b for a, b in zip(tip_after, plane.normal))
            - sum(a * b for a, b in zip(tip_before, plane.normal))) > 0.1


def test_a_step_and_its_opposite_give_the_point_back() -> None:
    rig, body, game = _rig(), _body(), _socket(SWORD)
    for key, amount in (("turn", 15.0), ("tip_out", 5.0), ("along", 0.02), ("out", 0.1)):
        there = back_move.plan_back_move(rig, body, SWORD, game, game, key=key,
                                         amount=amount).sockets[0][1]
        back = back_move.plan_back_move(rig, body, SWORD, there, game, key=key,
                                        amount=-amount).sockets[0][1]
        assert _same_rotation(back.rotation, game.rotation, 2e-6), key
        assert _near((back.translation.x, back.translation.y, back.translation.z),
                     (game.translation.x, game.translation.y, game.translation.z), 5e-6), key
        assert (back.name, back.parent_bone) == (CHILD, "B_Weapon_0001")


def test_the_move_is_made_on_the_item_and_leaves_the_body_point() -> None:
    rig, body, game = _rig(), _body(), _socket(SWORD)
    world = carry_plan.weapon_world(rig, body, game)
    plane = back_move.back_plane(world)
    move = back_move.back_move(world, plane, out=0.02, guard=0.16)
    child = back_move.moved_child(rig, body, game, move)
    assert _near(carry_plan.weapon_world(rig, body, child), multiply(world, move), 2e-6)


def test_an_item_edge_on_to_the_back_has_no_plane() -> None:
    rig, body = _rig(), _body()
    sideways = Socket(CHILD, "B_Weapon_0001", Quat.from_axis_angle(Vec3(1, 0, 0), 90.0),
                      Vec3())
    with pytest.raises(back_move.BackMoveError):
        back_move.back_plane(carry_plan.weapon_world(rig, body, sideways))


# ── files in step ────────────────────────────────────────────────────


def test_the_sheaths_and_the_same_line_move_with_the_sword_and_the_spear_does_not() -> None:
    steps = back_move.in_step_files(_weapons(), EditSession(FILES), SWORD, CHILD,
                                    hierarchy=_rig(), body_socket=_body())
    assert {step.socket_file: step.how for step in steps} == {
        SHEATH: "same", SHEATH_15: "same", LONG: "line"}
    # Without the rig only the same value counts.
    steps = back_move.in_step_files(_weapons(), None, SWORD, CHILD)
    assert [step.socket_file for step in steps] == [SHEATH, SHEATH_15]


def test_files_in_step_get_the_same_move_about_their_own_guard() -> None:
    rig, body = _rig(), _body()
    steps = back_move.in_step_files(_weapons(), None, SWORD, CHILD, hierarchy=rig,
                                    body_socket=body)
    steps += [back_move.InStep(LONG, _socket(LONG), "line")]
    plan = back_move.plan_back_move(rig, body, SWORD, _socket(SWORD), _socket(SWORD),
                                    key="along", amount=0.04, in_step=steps)
    moved = dict(plan.sockets)
    assert plan.files[0] == SWORD
    assert _value(moved[SHEATH]) == _value(moved[SHEATH_15]) == _value(moved[SWORD])
    # A shift moves both lines alike.
    for path in (SWORD, LONG):
        before = carry_plan.weapon_world(rig, body, _socket(path))
        after = carry_plan.weapon_world(rig, body, moved[path])
        shift = tuple(a - b for a, b in zip(_point(after), _point(before)))
        tip = tuple(-before[8 + i] for i in range(3))
        assert _near(shift, tuple(-0.04 * c for c in tip)), path


# ── the window ───────────────────────────────────────────────────────


def _pick_sword(window) -> None:
    window._session.hierarchy = _rig()
    window._session._reposition()
    box = window._weapon_box
    index = next(i for i in range(box.count())
                 if getattr(box.itemData(i), "game_path", "") == SWORD)
    box.setCurrentIndex(index)
    window._part_box.setCurrentIndex(window._part_box.findData("TwoHandWeapon_Sword"))
    window._mesh_role_box.setCurrentIndex(window._mesh_role_box.findData("stowed"))
    window._select_socket(CHILD)


def test_on_the_back_moves_the_sword_and_its_sheaths_and_saves_three_patches(
        window_factory) -> None:  # noqa: F811
    window = window_factory(FILES)
    _pick_sword(window)
    assert window._back_move_row.isVisibleTo(window)
    assert "cd_phm_02_sword_0001_in" in window._back_move_note.text()
    assert "cd_phm_02_spear_0001" not in window._back_move_note.text()
    window._back_move_box.setCurrentIndex(window._back_move_box.findData("out"))
    window._step_box.setCurrentIndex(window._step_box.findData(0.02))
    window._back_move_buttons[1].click()
    edits = window._edits
    moved = edits.socket(SWORD, CHILD)
    assert _value(moved) != _value(_socket(SWORD))
    for path in (SHEATH, SHEATH_15):
        assert _value(edits.socket(path, CHILD)) == _value(moved)
    assert _value(edits.socket(LONG, CHILD)) != _value(_socket(LONG))
    assert _value(edits.socket(SPEAR, CHILD)) == _value(_socket(SPEAR))
    assert _value(edits.socket(BODY, BACK)) == _value(_body())
    assert "in 4 files" in window.statusBar().currentMessage()

    # One Undo puts all four files back, and one Redo moves them again.
    window._undo()
    for path in (SWORD, SHEATH, SHEATH_15, LONG):
        assert _value(edits.socket(path, CHILD)) == _value(_socket(path)), path
    window._redo()
    for path in (SWORD, SHEATH, SHEATH_15):
        assert _value(edits.socket(path, CHILD)) == _value(moved), path

    with tempfile.TemporaryDirectory() as folder:
        request = save_mod.SaveRequest(name="2H out", folder=Path(folder),
                                       include=(save_mod.MANUAL,))
        outcome = save_mod.save_mod(edits, request, baseline=_Baseline(FILES),
                                    shared_socket_users=window._shared_socket_users())
        assert outcome.saved, outcome.problems
        written = {p.relative_to(folder).as_posix(): p.read_bytes()
                   for p in Path(folder).rglob("*") if p.is_file()}
    patches = sorted(p.rsplit("/", 1)[-1] for p in written if p.endswith(".sockets.xml.patch"))
    assert patches == ["cd_phm_02_sword_0001.sockets.xml.patch",
                       "cd_phm_02_sword_0001_in.sockets.xml.patch",
                       "cd_phm_02_sword_0002.sockets.xml.patch",
                       "cd_phm_02_sword_0015_in.sockets.xml.patch"]
    assert not any(p.endswith(".sockets.xml") and "/weapon/" in p for p in written)
    readme = next(data for p, data in written.items() if p.lower().endswith("readme.txt"))
    assert b"whole copy of the same file" in readme


def test_on_the_back_can_leave_the_other_files_alone_and_hides_for_a_held_item(
        window_factory) -> None:  # noqa: F811
    window = window_factory(FILES)
    _pick_sword(window)
    window._back_in_step_box.setChecked(False)
    assert "stay as they are" in window._back_move_note.text()
    window._back_move_box.setCurrentIndex(window._back_move_box.findData("turn"))
    window._back_move_buttons[0].click()
    assert _value(window._edits.socket(SWORD, CHILD)) != _value(_socket(SWORD))
    assert _value(window._edits.socket(SHEATH, CHILD)) == _value(_socket(SHEATH))
    window._mesh_role_box.setCurrentIndex(window._mesh_role_box.findData("held"))
    window._select_socket(CHILD)
    assert not window._back_move_row.isVisibleTo(window)


# ── the installed game, read-only ────────────────────────────────────

PHW = "character/descriptors/socketbonedata/1_pc/2_phw/"
REAL = {
    "kliff_body": BODY, "kliff_rig": "character/model/1_pc/1_phm/phm_01.pab",
    "damiane_body": PHW + "phw_damian_01.pab.sockets.xml",
    "phw_rig": "character/model/1_pc/2_phw/phw_01.pab",
    "kliff_rows": DESC,
}
KLIFF_FILES = [TWO + f"cd_phm_02_sword_{s}.sockets.xml" for s in ("0001", "0001_in", "0015_in",
                                                                   "0045")]
DAMIANE_FILES = [PHW + f"weapon/2_twohandweapon/cd_phw_02_sword_{s}.sockets.xml"
                 for s in ("0001", "0002")]
#: The test Core seen working in game (NOTES item 26): Turn +35, Distance +3, along -25.
_CORE = Path(".work/tests/2026-11-17-weapon-carry-2h-back/in-game-core/"
             "Weapon Carry Custom Cores - Test 2H big move.zip")
#: Looked for in the main checkout too, since a worktree sits inside its `.work` folder.
TEST_CORE = next((parent / _CORE for parent in Path(__file__).resolve().parents
                  if (parent / _CORE).is_file()), _CORE)
STEPS = (("turn", 35.0), ("out", 0.03), ("along", -0.25))


@pytest.fixture(scope="module")
def game(tmp_path_factory):
    if not corpus.game_root().is_dir():
        pytest.skip("needs the installed game")
    paths = [*REAL.values(), *KLIFF_FILES, *DAMIANE_FILES]
    base = corpus.extract_baseline(paths, out_root=tmp_path_factory.mktemp("game"))
    missing = [path for path in paths if path not in base]
    if missing:
        pytest.skip(f"the installed game has no {missing[0]}")
    return {path: base.read(path) for path in paths}


def _real_move(game, body_file, rig_file, body_point, files):
    rig = BoneHierarchy.from_pab(game[rig_file], rig_file)
    body = SocketDocument.load(game[body_file], body_file).socket_map()[body_point]
    weapons = [_Weapon(path, game) for path in files]
    first = files[0]
    steps = back_move.in_step_files(weapons, None, first, CHILD, hierarchy=rig, body_socket=body)
    current = {w.game_path: w.sockets[CHILD] for w in weapons}
    game_child = current[first]
    for key, amount in STEPS:
        in_step = [back_move.InStep(s.socket_file, current[s.socket_file], s.how) for s in steps]
        plan = back_move.plan_back_move(rig, body, first, current[first], game_child, key=key,
                                        amount=amount, in_step=in_step)
        current.update(dict(plan.sockets))
    return {s.socket_file: s.how for s in steps}, current


@pytest.mark.real_game
def test_kliffs_three_files_move_exactly_as_the_core_seen_in_game(game) -> None:
    how, moved = _real_move(game, REAL["kliff_body"], REAL["kliff_rig"], BACK, KLIFF_FILES)
    assert how == {KLIFF_FILES[1]: "same", KLIFF_FILES[2]: "same", KLIFF_FILES[3]: "line"}
    for path in KLIFF_FILES[:3]:
        assert moved[path].rotation.format() == "0.000000 0.953717 0.000000 0.300706"
        assert moved[path].translation.format() == "0.177976 -0.030000 -0.164176"
    edits = EditSession({path: game[path] for path in KLIFF_FILES[:3]})
    for path in KLIFF_FILES[:3]:
        edits.set_translation(path, CHILD, moved[path].translation)
        edits.set_rotation_quaternion(path, CHILD, moved[path].rotation)
    lowered = dmm_patch.lower_for_dmm(edits.preview(), lambda path: game.get(path))
    assert lowered.patched == tuple(sorted(KLIFF_FILES[:3]))
    if TEST_CORE.is_file():
        with zipfile.ZipFile(TEST_CORE) as archive:
            core = {name.split("/", 1)[1]: archive.read(name) for name in archive.namelist()
                    if name.endswith(".patch")}
        for path in KLIFF_FILES[:3]:
            assert lowered.files[dmm_patch.patch_path(path)] == core[dmm_patch.patch_path(path)]


@pytest.mark.real_game
def test_damianes_two_files_move_as_the_generator_moves_them(game) -> None:
    how, moved = _real_move(game, REAL["damiane_body"], REAL["phw_rig"],
                            "Spine2_B_MainWeapon_Socket", DAMIANE_FILES)
    assert how == {DAMIANE_FILES[1]: "line"}
    first, second = moved[DAMIANE_FILES[0]], moved[DAMIANE_FILES[1]]
    assert first.rotation.format() == "0.000000 0.953717 0.000000 0.300706"
    assert first.translation.format() == "0.177976 -0.030000 -0.164176"
    # The test Core's values for `_0002`, to the rounding of three steps.
    assert _same_rotation(second.rotation, Quat(-0.037429, -0.952985, 0.011819, -0.300464), 2e-6)
    assert _near((second.translation.x, second.translation.y, second.translation.z),
                 (0.107372, -0.039424, -0.059942), 5e-6)


@pytest.mark.real_game
def test_a_move_of_kliffs_2h_sword_saves_past_the_preflight_on_the_games_rows(game,
                                                                            tmp_path) -> None:
    files = {path: game[path] for path in (BODY, DESC, *KLIFF_FILES)}
    resolver = PlacementResolver()
    resolver.add_files(files)
    session = PlacementSession("1_phm", BoneHierarchy.from_pab(game[REAL["kliff_rig"]],
                                                               REAL["kliff_rig"]), resolver)
    # Each file is read by one row: the sword's by the 2H sword row, the sheaths' by its case.
    shared = session.file_shared_users()
    assert shared[(KLIFF_FILES[0], CHILD)] == ("TwoHandWeapon_Sword",)
    assert shared[(KLIFF_FILES[1], CHILD)] == ("TwoHandWeapon_Sword_IN",)
    edits = EditSession(files)
    body = next(s for s in session.body_sockets() if s.name == BACK)
    steps = back_move.in_step_files(session.weapons(), edits, KLIFF_FILES[0], CHILD,
                                    hierarchy=session.bind_hierarchy, body_socket=body)
    plan = back_move.plan_back_move(session.bind_hierarchy, body, KLIFF_FILES[0],
                                    edits.socket(KLIFF_FILES[0], CHILD),
                                    edits.original_socket(KLIFF_FILES[0], CHILD),
                                    key="out", amount=0.02, in_step=steps)
    with edits.undo_step():
        for path, socket in plan.sockets:
            edits.set_translation(path, CHILD, socket.translation)
            edits.set_rotation_quaternion(path, CHILD, socket.rotation)
    users = {n: u.child_offset for n, u in session.usage_map().items() if u.child_offset}
    users.update(shared)
    outcome = save_mod.save_mod(edits, save_mod.SaveRequest(name="2H out", folder=tmp_path,
                                                            include=(save_mod.MANUAL,)),
                                baseline=_Baseline(files), shared_socket_users=users)
    assert outcome.saved, outcome.problems
    assert sorted(p.name for p in tmp_path.rglob("*.sockets.xml.patch")) == sorted(
        Path(path).name + ".patch" for path in KLIFF_FILES)
