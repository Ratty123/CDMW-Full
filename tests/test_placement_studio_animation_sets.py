"""Linking a placement to the animations that belong to it.

Move a weapon and the draw has to move with it. The association lives in the action charts,
which name both the socket they route through and the clips they play — so these tests pin
the extraction and the "what changes if I retarget" answer built on it.

Synthetic `.paac` payloads; no game install needed.
"""

from __future__ import annotations

import unittest

from tools.placement_studio.animation_sets import (
    AnimationSetIndex,
    chart_clips,
    chart_sockets,
    read_chart,
    summarise,
)


def _prefixed(text: str) -> bytes:
    """The chart string form: <len+1> <ascii> <NUL>."""

    body = text.encode("ascii")
    return bytes([len(body) + 1]) + body + b"\x00"


def _chart(sockets=(), clips=()) -> bytes:
    out = b"\x00\x11\x22"
    for socket in sockets:
        out += _prefixed(socket)
    for clip in clips:
        out += _prefixed(f"character/motion/1_pc/1_phm/{clip}.paa")
    return out + b"\x33\x44"


_BACK = "Spine2_B_SubWeapon_Socket"
_HIP = "Pelvis_L_SubWeapon_Socket"


class ExtractionTests(unittest.TestCase):
    def test_clips_are_named_by_path_and_returned_as_stems(self) -> None:
        data = _chart(sockets=(_BACK,), clips=("cd_phm_longsword_00_01_normal_stand_weapon_out_000",))
        self.assertEqual(
            chart_clips(data), ("cd_phm_longsword_00_01_normal_stand_weapon_out_000",)
        )

    def test_sockets_are_picked_out_by_suffix(self) -> None:
        data = _chart(sockets=(_BACK, "NotARealThing"), clips=())
        self.assertEqual(chart_sockets(data), (_BACK,))

    def test_a_run_without_the_length_prefix_is_rejected(self) -> None:
        """Bare bytes inside a compressed block must not read as a clip reference."""

        data = b"\x00\x00character/motion/1_pc/1_phm/cd_phm_fake_00.paa\x00"
        self.assertEqual(chart_clips(data), ())

    def test_duplicate_names_collapse(self) -> None:
        clip = "cd_phm_lswd_01_01_nor_std_weapon_out_00"
        data = _chart(sockets=(_BACK,), clips=(clip, clip))
        self.assertEqual(chart_clips(data), (clip,))


class IndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = AnimationSetIndex.from_files({
            "actionchart/back.paac": _chart(
                sockets=(_BACK,), clips=("cd_back_draw_00", "cd_back_sheathe_00")),
            "actionchart/hip.paac": _chart(
                sockets=(_HIP,), clips=("cd_hip_draw_00",)),
            "actionchart/both.paac": _chart(
                sockets=(_BACK, _HIP), clips=("cd_shared_idle_00",)),
        })

    def test_clips_for_a_socket_span_every_chart_that_names_it(self) -> None:
        self.assertEqual(
            self.index.clips_for_socket(_BACK),
            ["cd_back_draw_00", "cd_back_sheathe_00", "cd_shared_idle_00"],
        )

    def test_charts_for_a_socket(self) -> None:
        self.assertEqual(
            self.index.charts_for_socket(_HIP),
            ["actionchart/both.paac", "actionchart/hip.paac"],
        )

    def test_sockets_for_a_clip_is_the_reverse_lookup(self) -> None:
        self.assertEqual(self.index.sockets_for_clip("cd_shared_idle_00"), [_HIP, _BACK])

    def test_a_retarget_reports_what_it_leaves_and_what_it_picks_up(self) -> None:
        """The question a placement move actually raises."""

        leaves, picks_up = self.index.counterpart_clips(_BACK, _HIP)
        self.assertEqual(leaves, ["cd_back_draw_00", "cd_back_sheathe_00", "cd_shared_idle_00"])
        self.assertEqual(picks_up, ["cd_hip_draw_00", "cd_shared_idle_00"])

    def test_an_unknown_socket_yields_nothing_rather_than_everything(self) -> None:
        self.assertEqual(self.index.clips_for_socket("No_Such_Socket"), [])

    def test_sockets_are_listed_once(self) -> None:
        self.assertEqual(self.index.sockets(), [_HIP, _BACK])

    def test_read_chart_keeps_the_path(self) -> None:
        link = read_chart("actionchart/x.paac", _chart(sockets=(_BACK,), clips=("cd_a_00",)))
        self.assertEqual(link.path, "actionchart/x.paac")
        self.assertEqual(link.clips, ("cd_a_00",))


class SummaryTests(unittest.TestCase):
    def test_no_socket_selected(self) -> None:
        self.assertIn("Select a socket", summarise("", [], []))

    def test_socket_with_no_clips_says_so(self) -> None:
        self.assertIn("no chart names a clip", summarise(_BACK, [], []))

    def test_counts_are_reported(self) -> None:
        text = summarise(_BACK, ["a", "b"], ["c.paac"])
        self.assertIn("2 clip(s)", text)
        self.assertIn("1 chart(s)", text)


if __name__ == "__main__":
    unittest.main()
