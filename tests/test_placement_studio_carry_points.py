"""Carry points: what moves with a body point, the other shoulder, shield files, other mods' points.

* Fine-tune names the items that hang from a shared body point.
* Over the other shoulder mirrors an item hung on a centre back point across the body and
  writes the point back in its own parent bone's frame.
* A child point is shared per socket file: every tower shield reads one file that only the
  tower shield row reads, so changing it saves, while two rows reading one file still block.
  Hang like copies a child point from another item's file into this item's own file.
* A carry point a body's game file lacks (female Kliff's musket point) is explained.

Synthetic files and rigs, except the `real_game` tests at the end, which read the installed
game's files into a temporary folder and change nothing.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from tests.test_placement_studio_operations import (
    ALIAS,
    BODY,
    DESC,
    FILES,
    IDENT,
    MODEL,
    W2H,
    _Baseline,
    _sockets,
)
from tools.placement_studio import carry_plan, corpus, save_mod
from tools.placement_studio.carry_plan import MirrorError
from tools.placement_studio.clip_names import part_label
from tools.placement_studio.editing import EditSession
from tools.placement_studio.equipment_assets import (
    EquipmentModel,
    models_reading_file,
    rows_reading_file,
    socket_file_kind,
    type_label,
)
from tools.placement_studio.model import DescriptorPart, Quat, Socket, Vec3
from tools.placement_studio.resolver import PlacementResolver
from tools.placement_studio.session import PlacementSession
from tools.placement_studio.skeleton import BoneHierarchy, BoneNode, matrix_from

SHIELDS = "character/descriptors/socketbonedata/1_pc/1_phm/weapon/3_shield/"
ROUND = SHIELDS + "cd_phm_03_shield_0001.sockets.xml"
TOWER = SHIELDS + "cd_phm_03_towershield_0001.sockets.xml"
KITE = SHIELDS + "cd_phm_03_kiteshield_0001.sockets.xml"
SHIELD_POINT = "Spine2_B_Shield_ChildSocket"

#: The values of the game's three shield files (1.0.0.3663).
SHIELD_FILES = {
    ROUND: _sockets(f"Basic_ChildSocket|B_Weapon_0001|{IDENT}|0.070000 0.064101 0.012865",
                    f"{SHIELD_POINT}|B_Weapon_0001|{IDENT}|0.000000 0.063203 0.000000"),
    TOWER: _sockets(f"Basic_ChildSocket|B_Weapon_0001|{IDENT}|0.074677 0.042573 0.302061",
                    f"{SHIELD_POINT}|B_Weapon_0001|0.000000 0.254602 0.000000 0.967046"
                    "|0.000000 0.001953 0.189188"),
    KITE: _sockets(f"Basic_ChildSocket|B_Weapon_0001|{IDENT}|0.074677 0.042573 0.162061",
                   f"{SHIELD_POINT}|B_Weapon_0001|{IDENT}|0.000000 0.062226 0.119033"),
}


def _shield_row(name: str) -> str:
    return (f'\t<Part PartName="{name}" InSocketBone="Spine2_B_Shield_Socket"'
            f' OutSocketBone="RHand_Socket" InChildSocketBone="{SHIELD_POINT}"'
            f' OutChildSocketBone="Basic_ChildSocket"/>\r\n')


def _shield_files(*rows: str) -> dict:
    """Kliff's two shield rows (or `rows`), his body, and the three shield files."""

    rows = rows or ("MainWeapon_Shield_L", "MainWeapon_TowerShield_L")
    text = "<CharacterDescription>\r\n" + "".join(map(_shield_row, rows))
    text += "</CharacterDescription>\r\n"
    files = {BODY: FILES[BODY], DESC: text.encode("utf-8"), ALIAS: text.encode("utf-8")}
    files.update(SHIELD_FILES)
    return files


def _session(files) -> PlacementSession:
    resolver = PlacementResolver()
    resolver.add_files(files)
    return PlacementSession(MODEL, None, resolver)


def _weapon(session, path):
    return next(w for w in session.weapons() if w.game_path == path)


def _users(session) -> dict:
    """What the window passes the preflight: by name, and per socket file."""

    users = {name: usage.child_offset for name, usage in session.usage_map().items()
             if usage.child_offset}
    users.update(session.file_shared_users())
    return users


def _save(edits, files, users):
    with tempfile.TemporaryDirectory() as folder:
        request = save_mod.SaveRequest(name="Shield", folder=Path(folder),
                                       include=(save_mod.MANUAL,))
        outcome = save_mod.save_mod(edits, request, baseline=_Baseline(files),
                                    shared_socket_users=users)
        written = {path.relative_to(folder).as_posix(): path.read_bytes()
                   for path in Path(folder).rglob("*") if path.is_file()}
    return outcome, written


# ── shared per socket file ───────────────────────────────────────────


def test_each_shield_file_is_read_by_its_own_row() -> None:
    rows = [DescriptorPart("MainWeapon_Shield_L"), DescriptorPart("MainWeapon_TowerShield_L")]
    assert rows_reading_file(TOWER, rows) == ("MainWeapon_TowerShield_L",)
    assert rows_reading_file(ROUND, rows) == ("MainWeapon_Shield_L",)
    # No row is named for kite shields; the shield row is the one whose type ends the kind.
    assert rows_reading_file(KITE, rows) == ("MainWeapon_Shield_L",)
    assert (socket_file_kind(TOWER), type_label(TOWER), type_label(ROUND)) == (
        "towershield", "tower shield", "round shield")


def test_rows_the_rules_cannot_place_all_count() -> None:
    rows = [DescriptorPart("MainWeapon_Bow"), DescriptorPart("MainWeapon_Musket")]
    shotgun = ("character/descriptors/socketbonedata/1_pc/1_phm/weapon/7_shotgun/"
               "cd_phm_07_shotgun_0001.sockets.xml")
    # No row is a shotgun, so the file counts every row naming the point, as before.
    assert rows_reading_file(shotgun, rows) == ("MainWeapon_Bow", "MainWeapon_Musket")
    # A case file is read by the case row; a two-hand file by the two-hand row.
    rows = [DescriptorPart("TwoHandWeapon_Sword"), DescriptorPart("TwoHandWeapon_Sword_IN"),
            DescriptorPart("MainWeapon_Sword_R")]
    assert rows_reading_file(W2H, rows) == ("TwoHandWeapon_Sword",)
    assert rows_reading_file(W2H.replace(".sockets", "_in.sockets"), rows) == (
        "TwoHandWeapon_Sword_IN",)


def test_models_reading_a_file_come_from_the_prefabs() -> None:
    models = [EquipmentModel("a.pac", TOWER, "a.prefab"), EquipmentModel("b.pac", TOWER, "b.prefab"),
              EquipmentModel("c.pac", ROUND, "c.prefab"), EquipmentModel("a.pac", TOWER, "d.prefab")]
    assert models_reading_file(models, TOWER) == ("a.pac", "b.pac")


def test_changing_the_tower_shields_point_saves_but_a_truly_shared_one_does_not() -> None:
    files = _shield_files()
    session = _session(files)
    assert session.child_socket_users(SHIELD_POINT) == (
        "MainWeapon_Shield_L", "MainWeapon_TowerShield_L")
    assert session.file_socket_users(_weapon(session, TOWER), SHIELD_POINT) == (
        "MainWeapon_TowerShield_L",)

    edits = EditSession(files)
    edits.nudge(TOWER, SHIELD_POINT, 0.0, 0.02, 0.0)
    outcome, written = _save(edits, files, _users(session))
    assert outcome.saved, outcome.problems
    # Weapon socket files are written whole, as before.
    assert any(path.endswith("cd_phm_03_towershield_0001.sockets.xml") for path in written)

    # Counted by name, as the check used to, the same change was refused.
    by_name = {k: v for k, v in _users(session).items() if isinstance(k, str)}
    edits = EditSession(files)
    edits.nudge(TOWER, SHIELD_POINT, 0.0, 0.02, 0.0)
    outcome, _written = _save(edits, files, by_name)
    assert not outcome.saved

    # Two rows that both read the round shields' file still block.
    files = _shield_files("MainWeapon_Shield_L", "MainWeapon_Shield_R",
                          "MainWeapon_TowerShield_L")
    session = _session(files)
    assert session.file_socket_users(_weapon(session, ROUND), SHIELD_POINT) == (
        "MainWeapon_Shield_L", "MainWeapon_Shield_R")
    edits = EditSession(files)
    edits.nudge(ROUND, SHIELD_POINT, 0.0, 0.02, 0.0)
    outcome, written = _save(edits, files, _users(session))
    assert not outcome.saved
    assert "shared by several items" in outcome.problems[0]
    assert not written


def test_hang_like_lists_the_other_shield_types() -> None:
    session = _session(_shield_files())
    sources = carry_plan.hang_like_sources(session.weapons(), ROUND, SHIELD_POINT,
                                           _weapon(session, ROUND).sockets[SHIELD_POINT])
    assert [(s.label, s.socket_file) for s in sources] == [
        ("kite shield", KITE), ("tower shield", TOWER)]
    assert sources[1].socket.rotation == Quat(0.0, 0.254602, 0.0, 0.967046)


# ── the other shoulder ───────────────────────────────────────────────


def _bone(index, name, parent, rotation=Quat(), translation=Vec3()):
    return BoneNode(index, name, parent, matrix_from(rotation, translation), translation)


def _rig() -> BoneHierarchy:
    """Thighs to say which way left is (+x), and a back bone off the body's middle."""

    return BoneHierarchy([
        _bone(0, "Bip01 Pelvis", -1, translation=Vec3(0.0, 1.0, 0.0)),
        _bone(1, "Bip01 L Thigh", 0, translation=Vec3(0.1, 0.9, 0.0)),
        _bone(2, "Bip01 R Thigh", 0, translation=Vec3(-0.1, 0.9, 0.0)),
        _bone(3, "Bip01 Spine2", 0, Quat.from_euler_degrees(-8.0, 3.0, 5.0),
              Vec3(0.01, 1.4, 0.15)),
        _bone(4, "Bip01 R Hand", 0, translation=Vec3(-0.4, 1.1, 0.2)),
    ], "test")


def _rotation_and_position(matrix):
    return carry_plan.rigid_of(matrix)


def _same_rotation(a: Quat, b: Quat, tolerance=1e-5) -> bool:
    qa, qb = (a.x, a.y, a.z, a.w), (b.x, b.y, b.z, b.w)
    return min(max(abs(x - y) for x, y in zip(qa, qb)),
               max(abs(x + y) for x, y in zip(qa, qb))) <= tolerance


BACK_POINT = Socket("Spine2_B_SubWeapon_Socket", "Bip01 Spine2",
                    Quat.from_euler_degrees(70.0, 20.0, -30.0), Vec3(-0.05, -0.2, 0.03))
BACK_CHILD = Socket("Spine2_B_SubWeapon_ChildSocket", "", Quat.from_euler_degrees(0.0, 180.0, 10.0),
                    Vec3(0.0, -0.47, 0.02))


def test_over_the_other_shoulder_mirrors_the_item_across_the_body() -> None:
    rig = _rig()
    before = carry_plan.weapon_world(rig, BACK_POINT, BACK_CHILD)
    solved = carry_plan.solve_other_shoulder(rig, BACK_POINT, BACK_CHILD, socket_file=BODY)
    after = carry_plan.weapon_world(rig, solved.socket, BACK_CHILD)
    q, t = _rotation_and_position(before)
    mq, mt = _rotation_and_position(after)
    # Rotation (x, -y, -z, w) and position (-x, y, z): the item's mirror image.
    assert _same_rotation(mq, Quat(q.x, -q.y, -q.z, q.w))
    assert max(abs(a - b) for a, b in zip((mt.x, mt.y, mt.z), (-t.x, t.y, t.z))) < 1e-5
    # Same point, same parent bone: a change of that one point.
    assert (solved.socket.name, solved.socket.parent_bone, solved.socket_file) == (
        BACK_POINT.name, BACK_POINT.parent_bone, BODY)
    assert solved.socket.translation != BACK_POINT.translation


def test_mirroring_over_the_other_shoulder_twice_gives_the_point_back() -> None:
    rig = _rig()
    once = carry_plan.solve_other_shoulder(rig, BACK_POINT, BACK_CHILD).socket
    twice = carry_plan.solve_other_shoulder(rig, once, BACK_CHILD).socket
    assert _same_rotation(twice.rotation, BACK_POINT.rotation, 1e-5)
    assert max(abs(a - b) for a, b in zip(
        (twice.translation.x, twice.translation.y, twice.translation.z),
        (BACK_POINT.translation.x, BACK_POINT.translation.y, BACK_POINT.translation.z))) < 1e-5


def test_over_the_other_shoulder_is_only_for_points_without_a_partner() -> None:
    with pytest.raises(MirrorError):
        carry_plan.solve_other_shoulder(_rig(), Socket("Pelvis_L_Socket", "Bip01 Pelvis"),
                                        BACK_CHILD)


PHW = "character/descriptors/socketbonedata/1_pc/2_phw/"
PHW_01 = PHW + "phw_01.pab.sockets.xml"
PHW_DAMIAN = PHW + "phw_damian_01.pab.sockets.xml"
PHW_DESC = "character/descriptors/characterdescription/phw_description_player_001.xml"
PHW_MUSKET = PHW + "weapon/8_musket/cd_phw_08_musket_0001.sockets.xml"
MUSKET_POINT = "Spine2_B_RangeWeapon_Musket_Socket"


def _phw_files() -> dict:
    """Female Kliff's game body file without the musket point, Damiane's with it."""

    common = (f"Spine2_B_SubWeapon_Socket|Bip01 Spine2|{IDENT}|0.000000 -0.200000 0.000000",
              f"RHand_Socket|Bip01 R Hand|{IDENT}|0.000000 0.000000 0.000000")
    desc = ("<CharacterDescription>\r\n"
            f'\t<Part PartName="MainWeapon_Musket" InSocketBone="{MUSKET_POINT}"'
            ' OutSocketBone="RHand_Socket" InChildSocketBone="Spine2_B_RangeWeapon_ChildSocket"'
            ' OutChildSocketBone="Basic_ChildSocket"/>\r\n'
            '\t<Part PartName="TwoHandWeapon_Spear" InSocketBone="Spine2_B_SubWeapon_Socket"'
            ' OutSocketBone="RHand_Socket" InChildSocketBone="Spine2_B_SubWeapon_ChildSocket"'
            ' OutChildSocketBone="Basic_ChildSocket"/>\r\n'
            "</CharacterDescription>\r\n").encode("utf-8")
    return {
        PHW_01: _sockets(*common),
        PHW_DAMIAN: _sockets(*common, f"{MUSKET_POINT}|Bip01 Spine2|{IDENT}"
                                      "|-0.080000 -0.050000 -0.130000"),
        PHW_DESC: desc,
        PHW_MUSKET: _sockets(f"Basic_ChildSocket||{IDENT}|0.000000 0.000000 0.000000",
                             f"Spine2_B_RangeWeapon_ChildSocket||{IDENT}|0.000000 -0.300000 0.000000"),
    }


def test_the_other_shoulder_is_solved_for_each_body_file() -> None:
    edits = EditSession(_phw_files())
    child = edits.socket(PHW_MUSKET, "Spine2_B_RangeWeapon_ChildSocket")
    solved = carry_plan.plan_other_shoulder(edits, "2_phw", "Spine2_B_SubWeapon_Socket", child,
                                            _rig())
    assert [s.socket_file for s in solved] == [PHW_01, PHW_DAMIAN]
    # Only Damiane's file has a musket point to mirror.
    solved = carry_plan.plan_other_shoulder(edits, "2_phw", MUSKET_POINT, child, _rig())
    assert [s.socket_file for s in solved] == [PHW_DAMIAN]


# ── points another mod adds ──────────────────────────────────────────


def test_a_point_the_game_file_lacks_is_named_with_its_body() -> None:
    edits = EditSession(_phw_files())
    missing = carry_plan.points_other_mods_add(
        edits, "2_phw", (MUSKET_POINT, "Spine2_B_SubWeapon_Socket", "Bip_Weapon_C"))
    assert missing == [(PHW_01, MUSKET_POINT)]
    assert carry_plan.body_file_label(PHW_01) == "female Kliff"
    assert carry_plan.body_file_label(PHW_DAMIAN) == "Damiane"


# ── in the window ────────────────────────────────────────────────────


def _open_window(monkeypatch, tmp_path, files):
    QApplication.instance() or QApplication([])
    from tools.placement_studio.window import PlacementStudioWindow

    monkeypatch.setattr(PlacementStudioWindow, "_start_armour_index", lambda self: None)
    monkeypatch.setattr(PlacementStudioWindow, "_start_archive_content_load",
                        lambda *a, **k: None)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(PlacementStudioWindow, "_mod_settings", lambda self: settings)
    base = tmp_path / "vanilla"
    records = {path: corpus._pin(base, path, data, "0009") for path, data in files.items()}
    return PlacementStudioWindow(corpus.Baseline(base, records), background_loading=False)


@pytest.fixture
def window_factory(monkeypatch, tmp_path):
    opened = []

    def build(files):
        studio = _open_window(monkeypatch, tmp_path, files)
        opened.append(studio)
        return studio

    yield build
    for studio in opened:
        studio.close()
        studio.deleteLater()


def _pick(window, *, weapon_path: str, part: str, role: str = "stowed", rig=None) -> None:
    if rig is not None:
        window._session.hierarchy = rig
        window._session._reposition()
    box = window._weapon_box
    index = next(i for i in range(box.count())
                 if getattr(box.itemData(i), "game_path", "") == weapon_path)
    box.setCurrentIndex(index)
    window._part_box.setCurrentIndex(window._part_box.findData(part))
    window._mesh_role_box.setCurrentIndex(window._mesh_role_box.findData(role))


def test_fine_tune_names_what_hangs_from_a_body_point_and_mirrors_it(window_factory) -> None:
    window = window_factory(FILES)
    _pick(window, weapon_path=W2H, part="CD_TwoHandWeapon_Sword", rig=_rig())
    back = "Spine2_B_MainWeapon_Socket"
    window._select_socket(back)
    note = window._share_note.text()
    assert "carries 2 items" in note
    for part in ("CD_TwoHandWeapon_Sword", "CD_TwoHandWeapon_Sword_IN"):
        assert part_label(part) in note
    assert "Over the other shoulder" in note
    button = window._other_shoulder_button
    assert button.isVisibleTo(window)

    session = window._session
    child = session.weapon.sockets["Spine2_B_SubWeapon_ChildSocket"]
    before = carry_plan.weapon_world(window._session.hierarchy, window._edits.socket(BODY, back),
                                     child)
    button.click()
    after = carry_plan.weapon_world(window._session.hierarchy, window._edits.socket(BODY, back),
                                    child)
    q, t = carry_plan.rigid_of(before)
    mq, mt = carry_plan.rigid_of(after)
    assert _same_rotation(mq, Quat(q.x, -q.y, -q.z, q.w))
    assert abs(mt.x + t.x) < 1e-5 and abs(mt.y - t.y) < 1e-5
    assert "It also moves" in window.statusBar().currentMessage()
    assert part_label("CD_TwoHandWeapon_Sword_IN") in window.statusBar().currentMessage()

    # A hip point has a partner, so the existing mirror covers it and this one is not offered.
    _pick(window, weapon_path=W2H.replace("2_twohandweapon/cd_phm_02_sword_0001",
                                          "1_onehandweapon/cd_phm_01_sword_0001_r"),
          part="CD_MainWeapon_Sword_R")
    window._select_socket("Pelvis_L_Socket")
    assert not button.isVisibleTo(window)


def test_hang_like_copies_the_tower_shields_point_and_saves_the_file(window_factory,
                                                                      tmp_path) -> None:
    files = _shield_files()
    window = window_factory(files)
    _pick(window, weapon_path=ROUND, part="MainWeapon_Shield_L")
    window._select_socket(SHIELD_POINT)
    note = window._share_note.text()
    assert "Every round shield model reads this one file" in note
    assert "Shared by" not in note
    button = window._hang_like_button
    assert button.isVisibleTo(window)
    actions = {a.text(): a for a in window._hang_like_menu.actions()}
    assert sorted(actions) == ["Kite shield", "Tower shield"]
    actions["Tower shield"].trigger()
    copied = window._edits.socket(ROUND, SHIELD_POINT)
    tower = window._edits.socket(TOWER, SHIELD_POINT)
    assert (copied.rotation, copied.translation) == (tower.rotation, tower.translation)
    assert window._edits.socket(ROUND, SHIELD_POINT).parent_bone == "B_Weapon_0001"
    outcome, written = _save(window._edits, files, window._shared_socket_users())
    assert outcome.saved, outcome.problems
    saved = next(data for path, data in written.items()
                 if path.endswith("cd_phm_03_shield_0001.sockets.xml"))
    assert b"0.254602" in saved and b"<SocketBoneData>" in saved


def test_hang_like_is_disabled_when_several_rows_read_the_file(window_factory) -> None:
    # Two rows read the round shields' file, so the copy would be refused on save.
    files = _shield_files("MainWeapon_Shield_L", "MainWeapon_Shield_R",
                          "MainWeapon_TowerShield_L")
    window = window_factory(files)
    _pick(window, weapon_path=ROUND, part="MainWeapon_Shield_L")
    window._select_socket(SHIELD_POINT)
    button = window._hang_like_button
    assert button.isVisibleTo(window)
    assert not button.isEnabled()
    assert "share this item's file" in button.toolTip()
    before = window._edits.socket(ROUND, SHIELD_POINT)
    source = next(s for s in window._hang_like_sources() if "tower" in s.label.lower())
    window._hang_like(source)
    assert not window._edits.modified_paths()
    assert window._edits.socket(ROUND, SHIELD_POINT) == before

    # The tower shield's file has one reader, so Hang like stays live there.
    _pick(window, weapon_path=TOWER, part="MainWeapon_TowerShield_L")
    window._select_socket(SHIELD_POINT)
    assert window._hang_like_button.isEnabled()


def test_where_it_hangs_explains_a_point_another_mod_adds(window_factory) -> None:
    window = window_factory(_phw_files())
    _pick(window, weapon_path=PHW_MUSKET, part="MainWeapon_Musket")
    window._refresh_carry_plan()
    note = window._carry_mod_note
    assert note.isVisibleTo(window)
    assert "female Kliff" in note.text()
    assert "Character Creator Enhanced" in note.text()
    assert "Damiane" not in note.text()


# ── the installed game, read-only ────────────────────────────────────

KLIFF = "character/descriptors/socketbonedata/1_pc/1_phm/"
REAL_PATHS = (
    KLIFF + "phm_01.pab.sockets.xml",
    "character/model/1_pc/1_phm/phm_01.pab",
    KLIFF + "weapon/8_musket/cd_phm_08_musket_0001.sockets.xml",
    KLIFF + "weapon/2_twohandweapon/cd_phm_02_sword_0001.sockets.xml",
    ROUND, TOWER, KITE,
    "character/descriptors/characterdescription/phm_description_player_kliff.xml",
    PHW_01, PHW_DAMIAN,
)


@pytest.fixture(scope="module")
def game_files(tmp_path_factory):
    if not corpus.game_root().is_dir():
        pytest.skip("needs the installed game")
    base = corpus.extract_baseline(REAL_PATHS, out_root=tmp_path_factory.mktemp("game"))
    missing = [path for path in REAL_PATHS if path not in base]
    if missing:
        pytest.skip(f"the installed game has no {missing[0]}")
    return {path: base.read(path) for path in REAL_PATHS}


@pytest.mark.real_game
def test_kliffs_musket_goes_over_the_other_shoulder(game_files) -> None:
    rig = BoneHierarchy.from_pab(game_files[REAL_PATHS[1]], REAL_PATHS[1])
    assert carry_plan.mirror_axis(rig) == 0
    resolver = PlacementResolver()
    resolver.add_files({p: d for p, d in game_files.items() if p.endswith(".xml")})
    body = resolver.body_sockets("1_phm")
    weapons = {w.weapon_id: w for w in resolver.weapons(model="1_phm")}
    musket_point = body[MUSKET_POINT]
    musket = weapons["cd_phm_08_musket_0001"].sockets["Spine2_B_RangeWeapon_ChildSocket"]
    sword = carry_plan.weapon_world(rig, body["Spine2_B_SubWeapon_Socket"],
                                    weapons["cd_phm_02_sword_0001"].sockets[
                                        "Spine2_B_SubWeapon_ChildSocket"])
    before = carry_plan.weapon_world(rig, musket_point, musket)
    solved = carry_plan.solve_other_shoulder(rig, musket_point, musket)
    after = carry_plan.weapon_world(rig, solved.socket, musket)
    # The item's length runs along its z axis. The musket and the 2H sword lean the same way
    # over the right shoulder (towards -x); mirrored, the musket leans the other way.
    lean = lambda m: m[8]  # noqa: E731 - the x part of the z axis
    assert lean(before) < -0.3 and lean(sword) < -0.3
    assert lean(after) > 0.3
    assert abs(after[12] + before[12]) < 1e-4 and abs(after[13] - before[13]) < 1e-4
    assert solved.socket.parent_bone == musket_point.parent_bone == "Bip_Weapon_Attach_In_02"
    twice = carry_plan.solve_other_shoulder(rig, solved.socket, musket).socket
    assert _same_rotation(twice.rotation, musket_point.rotation, 1e-5)


@pytest.mark.real_game
def test_the_games_shield_files_are_each_read_by_one_row(game_files) -> None:
    session = _session({p: d for p, d in game_files.items() if p.endswith(".xml")})
    assert set(session.child_socket_users(SHIELD_POINT)) >= {
        "MainWeapon_Shield_L", "MainWeapon_TowerShield_L"}
    assert session.file_socket_users(_weapon(session, TOWER), SHIELD_POINT) == (
        "MainWeapon_TowerShield_L",)
    assert session.file_socket_users(_weapon(session, ROUND), SHIELD_POINT) == (
        "MainWeapon_Shield_L",)


@pytest.mark.real_game
def test_female_kliffs_game_body_file_has_no_musket_point(game_files) -> None:
    edits = EditSession({p: game_files[p] for p in (PHW_01, PHW_DAMIAN)})
    assert carry_plan.points_other_mods_add(edits, "2_phw", (MUSKET_POINT,)) == [
        (PHW_01, MUSKET_POINT)]
