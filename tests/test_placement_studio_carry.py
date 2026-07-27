"""Working out where a draw animation starts from.

The interesting behaviour is not "which socket is nearest" — it is that nearest is the wrong
question. In a back draw the idle hand hangs by the hip, so the closest hand-to-socket pair
in the whole clip belongs to the hand that is doing nothing. These tests pin the signal that
actually separates them: how far a hand *closes* on a socket over the clip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from tools.placement_studio import carry


@dataclass(frozen=True)
class _Vec:
    x: float
    y: float
    z: float

    def distance_to(self, other: "_Vec") -> float:
        return (
            (self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2
        ) ** 0.5


@dataclass(frozen=True)
class _Node:
    name: str
    world_position: _Vec


class _Clip:
    def __init__(self, frames: int) -> None:
        self.frame_count = frames


class _Session:
    """A rig whose bones and sockets are scripted per frame.

    `tracks` maps a name to a list of positions, one per frame. Sockets and bones come from
    the same table because the real session places sockets against the posed bones, so both
    move together.
    """

    def __init__(self, tracks: Dict[str, List[_Vec]], sockets: List[str]) -> None:
        self._tracks = tracks
        self._socket_names = sockets
        self._frame = 0

    def apply_pose(self, _clip, frame: float) -> None:
        self._frame = int(frame)

    def _at(self, name: str) -> _Vec:
        track = self._tracks[name]
        return track[min(self._frame, len(track) - 1)]

    def placed_sockets(self) -> List[_Node]:
        return [_Node(name, self._at(name)) for name in self._socket_names]

    @property
    def hierarchy(self) -> List[_Node]:
        return [_Node(name, self._at(name)) for name in carry.HAND_BONES]


_FRAMES = 12


def _still(point: _Vec) -> List[_Vec]:
    return [point] * _FRAMES


def _reaches(start: _Vec, target: _Vec) -> List[_Vec]:
    """A hand that travels from `start` to `target` and back — one grab."""

    out = []
    for i in range(_FRAMES):
        # 0 -> 1 -> 0 over the clip, so the closest approach is in the middle.
        t = 1.0 - abs((i / (_FRAMES - 1)) * 2.0 - 1.0)
        out.append(
            _Vec(
                start.x + (target.x - start.x) * t,
                start.y + (target.y - start.y) * t,
                start.z + (target.z - start.z) * t,
            )
        )
    return out


HIP = _Vec(0.15, 1.0, 0.0)
BACK = _Vec(0.0, 1.4, -0.15)


def _back_draw_session() -> _Session:
    """The case that defeats nearest-socket scoring.

    The right hand sweeps up to the back socket and takes the weapon. The left hand does
    nothing — but it rests 0.05 m from the hip socket, far nearer than the drawing hand ever
    gets to the back. Distance alone therefore says "hip".
    """

    return _Session(
        {
            "Bip01 R Hand": _reaches(_Vec(0.3, 0.9, 0.2), BACK),
            "Bip01 L Hand": _still(_Vec(-0.15 + 0.05, 1.0, 0.0)),
            "Pelvis_R_Socket": _still(HIP),
            "Pelvis_L_Socket": _still(_Vec(-0.15, 1.0, 0.0)),
            "Spine2_B_MainWeapon_Socket": _still(BACK),
        },
        ["Pelvis_R_Socket", "Pelvis_L_Socket", "Spine2_B_MainWeapon_Socket"],
    )


def test_the_idle_hand_does_not_win_a_back_draw():
    session = _back_draw_session()

    reach = carry.reach_of_clip(session, _Clip(_FRAMES))

    assert reach.zone == "back"
    assert reach.hand == "Bip01 R Hand"
    assert reach.confident
    # The premise of the test: the idle left hand really is nearer to its hip socket than the
    # drawing hand ever gets to the back one, so this is not passing by accident.
    assert reach.distance > 0.05


def test_a_hip_draw_reads_as_the_hip():
    session = _Session(
        {
            "Bip01 R Hand": _reaches(_Vec(0.35, 1.5, 0.1), HIP),
            "Bip01 L Hand": _still(_Vec(-0.3, 1.1, 0.1)),
            "Pelvis_R_Socket": _still(HIP),
            "Spine2_B_MainWeapon_Socket": _still(BACK),
        },
        ["Pelvis_R_Socket", "Spine2_B_MainWeapon_Socket"],
    )

    reach = carry.reach_of_clip(session, _Clip(_FRAMES))

    assert reach.zone == "hip"
    assert reach.socket == "Pelvis_R_Socket"


def test_a_clip_where_no_hand_goes_anywhere_is_not_claimed():
    """A locomotion clip has no draw in it, and must not be filed under one."""

    session = _Session(
        {
            "Bip01 R Hand": _still(_Vec(0.3, 1.0, 0.0)),
            "Bip01 L Hand": _still(_Vec(-0.3, 1.0, 0.0)),
            "Pelvis_R_Socket": _still(HIP),
            "Spine2_B_MainWeapon_Socket": _still(BACK),
        },
        ["Pelvis_R_Socket", "Spine2_B_MainWeapon_Socket"],
    )

    assert not carry.reach_of_clip(session, _Clip(_FRAMES)).confident


def test_a_hand_that_waves_near_a_socket_without_closing_is_not_a_draw():
    """Approaching from far away but never arriving is not taking hold of anything."""

    far = _Vec(2.0, 1.0, 0.0)
    session = _Session(
        {
            "Bip01 R Hand": _reaches(_Vec(3.0, 1.0, 0.0), far),
            "Bip01 L Hand": _still(_Vec(-3.0, 1.0, 0.0)),
            "Pelvis_R_Socket": _still(HIP),
        },
        ["Pelvis_R_Socket"],
    )

    assert not carry.reach_of_clip(session, _Clip(_FRAMES)).confident


def test_sockets_that_share_a_zone_do_not_compete_for_the_margin():
    """The five upper-back sockets are one place; separating them would drop every back draw."""

    reach = carry.reach_of_clip(
        _Session(
            {
                "Bip01 R Hand": _reaches(_Vec(0.3, 0.9, 0.2), BACK),
                "Bip01 L Hand": _still(_Vec(-2.0, 1.0, 0.0)),
                "Spine2_B_MainWeapon_Socket": _still(BACK),
                # 4 cm away, as on the real rig.
                "Spine2_B_SubWeapon_Socket": _still(_Vec(BACK.x + 0.04, BACK.y, BACK.z)),
                "Pelvis_R_Socket": _still(HIP),
            },
            ["Spine2_B_MainWeapon_Socket", "Spine2_B_SubWeapon_Socket", "Pelvis_R_Socket"],
        ),
        _Clip(_FRAMES),
    )

    assert reach.zone == "back"
    assert reach.strong, "the near-identical sibling socket must not eat the margin"


def test_the_hands_are_never_measured_against():
    """A hand sits on its own hand socket at no distance, which would win every clip."""

    class _Rig:
        def placed_sockets(self):
            return [_Node(name, _Vec(0, 0, 0)) for name in
                    ("RHand_Socket", "LHand_Socket", "Pelvis_R_Socket",
                     "Spine2_B_MainWeapon_Socket", "Pelvis_B_Socket")]

    names = carry.stow_positions(_Rig())

    assert "RHand_Socket" not in names and "LHand_Socket" not in names
    # Routable, but too near both zones to be a usable candidate.
    assert "Pelvis_B_Socket" not in names
    assert names == ["Pelvis_R_Socket", "Spine2_B_MainWeapon_Socket"]


def test_every_carry_socket_has_a_zone_and_a_label():
    for socket, label in carry.CARRY_SOCKETS:
        assert label
        assert carry.zone_of(socket) in carry.ZONE_ORDER, socket


class _StubReach:
    pass


def _index() -> carry.CarryIndex:
    index = carry.CarryIndex()
    index.add("a_weapon_out_00", carry.Reach("Pelvis_R_Socket", 0.09, 0.40, "r", 0.62))
    index.add("b_weapon_out_00", carry.Reach("LThigh_Socket", 0.10, 0.004, "r", 0.30))
    index.add("c_weapon_in_00", carry.Reach("Pelvis_L_Socket", 0.09, 0.20, "r", 0.35))
    index.add("d_weapon_out_00", carry.Reach("Spine2_B_SubWeapon_Socket", 0.11, 0.25, "r", 0.37))
    return index


def test_clips_are_grouped_by_zone_not_by_exact_socket():
    index = _index()

    # A thigh clip has to come back for a hip query: they are the same reach.
    assert index.clips_for("Pelvis_R_Socket", sheathe=False) == [
        "a_weapon_out_00",
        "b_weapon_out_00",
    ]
    assert index.clips_for("Spine2_B_MainWeapon_Socket") == ["d_weapon_out_00"]
    assert index.counts() == {"hip": 3, "back": 1}


def test_draws_and_sheathes_are_separable():
    index = _index()

    assert index.clips_for("Pelvis_R_Socket", sheathe=True) == ["c_weapon_in_00"]
    assert len(index.clips_for("Pelvis_R_Socket")) == 3


def test_clear_cut_clips_are_offered_before_marginal_ones():
    """`b` closes further than nothing but only just out-scores its rival; it sorts last."""

    assert _index().clips_for("Pelvis_R_Socket", sheathe=False)[0] == "a_weapon_out_00"


def test_an_unreached_clip_is_never_stored():
    index = carry.CarryIndex()

    index.add("nothing_happens", carry.Reach("Pelvis_R_Socket", 0.09, 0.4, "r", 0.01))

    assert len(index) == 0


def test_the_index_survives_a_round_trip():
    original = _index()

    restored = carry.CarryIndex.from_json(original.to_json())

    assert restored.counts() == original.counts()
    assert restored.clips_for("Pelvis_R_Socket") == original.clips_for("Pelvis_R_Socket")
    assert restored.reach("a_weapon_out_00").approach == 0.62


def test_a_cache_from_another_layout_is_ignored():
    assert len(carry.CarryIndex.from_json({"version": 99, "clips": {"x": []}})) == 0
    assert len(carry.CarryIndex.from_json("not a dict")) == 0


def test_draw_and_sheathe_are_told_apart_by_name():
    assert carry.is_draw("cd_phm_sword_00_01_normal_stand_weapon_out_000")
    assert carry.is_draw("cd_phm_sword_00_01_normal_stand_weapon_in_000")
    assert not carry.is_draw("cd_phm_sword_00_01_normal_move_run_f")
    assert carry.is_sheathe("x_weapon_in_00")
    assert not carry.is_sheathe("x_weapon_out_00")


def test_building_an_index_can_be_stopped():
    session = _back_draw_session()
    clips = [("one", _Clip(_FRAMES)), ("two", _Clip(_FRAMES))]

    built = carry.build_index(session, clips, should_stop=lambda: True)

    assert len(built) == 0
