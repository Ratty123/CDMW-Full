"""Tests for choosing a body proxy mesh, and for noticing when the choice was wrong.

A baseline once pinned `cd_phm_00_ub_acc_00_0377.pac` — a 23 KB *accessory* — as the upper-body
proxy, because the selection rule took the smallest mesh in the slot. It rendered as a scrap near
one elbow, and because every clipping measurement is taken against the proxy, all of them read
"no vertices inside the body". A wrong answer that looked exactly like a clean one.

So there are two checks here: the name filter that keeps accessories out, and the coverage
measurement that catches a bad proxy whatever the reason.

No game install and no Qt: synthetic meshes and a synthetic rig.
"""

from __future__ import annotations

import unittest

from tools.placement_studio.meshes import (
    MIN_BODY_COVERAGE,
    Mesh,
    body_coverage,
    is_base_armour_mesh,
)
from tools.placement_studio.model import Vec3
from tools.placement_studio.skeleton import BoneHierarchy, BoneNode

_UPPER = "9_upperbody"
_LOWER = "10_lowerbody"


def _path(name: str, model: str = "1_phm", slot: str = _UPPER) -> str:
    return f"character/model/1_pc/{model}/armor/{slot}/{name}"


def _at(y: float):
    """A bind matrix translated to height `y` — `world_position` reads the matrix, not the field."""

    return (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, y, 0.0, 1.0)


def _rig(height: float = 1.79) -> BoneHierarchy:
    return BoneHierarchy(
        [
            BoneNode(0, "Root", -1, _at(0.0), Vec3()),
            BoneNode(1, "Head", 0, _at(height), Vec3(0.0, height, 0.0)),
        ],
        "test",
    )


def _column(low: float, high: float) -> Mesh:
    """A mesh spanning a vertical range — only its bounds matter for coverage."""

    return Mesh(
        name="piece",
        vertices=(Vec3(0.0, low, 0.0), Vec3(0.1, low, 0.0), Vec3(0.0, high, 0.0)),
        triangles=((0, 1, 2),),
    )


class BaseArmourNameTests(unittest.TestCase):
    def test_the_canonical_base_armour_name_is_accepted(self) -> None:
        for name in ("cd_phm_00_ub_0001.pac", "cd_phm_00_ub_0018.pac"):
            self.assertTrue(is_base_armour_mesh(_path(name), "1_phm", _UPPER), name)

    def test_accessories_are_rejected(self) -> None:
        """The exact file that shipped as a body proxy."""

        self.assertFalse(
            is_base_armour_mesh(_path("cd_phm_00_ub_acc_00_0377.pac"), "1_phm", _UPPER)
        )

    def test_sub_pieces_belts_and_variants_are_rejected(self) -> None:
        for name in (
            "cd_phm_00_ub_00_0438_sub01.pac",
            "cd_phw_00_ub_belt_0119.pac",
            "cd_phm_m0001_00_artis_ub_0001.pac",
            "cd_phm_00_ub_0054_08.pac",
            "cd_phm_00_ub_00_0335.pac",
        ):
            self.assertFalse(is_base_armour_mesh(_path(name), "1_phm", _UPPER), name)

    def test_the_slot_tag_must_match(self) -> None:
        """An upper-body mesh must not be accepted as the lower-body pick."""

        path = _path("cd_phm_00_ub_0001.pac")
        self.assertTrue(is_base_armour_mesh(path, "1_phm", _UPPER))
        self.assertFalse(is_base_armour_mesh(path, "1_phm", _LOWER))

    def test_the_model_must_match(self) -> None:
        path = _path("cd_phm_00_ub_0001.pac")
        self.assertFalse(is_base_armour_mesh(path, "2_phw", _UPPER))

    def test_the_lower_body_tag_is_recognised(self) -> None:
        self.assertTrue(
            is_base_armour_mesh(
                _path("cd_phw_00_lb_0005.pac", "2_phw", _LOWER), "2_phw", _LOWER
            )
        )

    def test_an_unknown_slot_matches_nothing(self) -> None:
        self.assertFalse(is_base_armour_mesh(_path("cd_phm_00_ub_0001.pac"), "1_phm", "3_head"))


class BodyCoverageTests(unittest.TestCase):
    def test_a_full_body_proxy_passes(self) -> None:
        coverage = body_coverage(_column(0.25, 1.86), _rig())
        self.assertGreaterEqual(coverage, MIN_BODY_COVERAGE)

    def test_the_accessory_that_shipped_would_be_caught(self) -> None:
        """0.23 of a 1.79 rig — a scrap near one elbow."""

        coverage = body_coverage(_column(1.00, 1.23), _rig())
        self.assertLess(coverage, MIN_BODY_COVERAGE)
        self.assertAlmostEqual(coverage, 0.23 / 1.79, places=2)

    def test_coverage_is_clamped_to_one(self) -> None:
        self.assertEqual(body_coverage(_column(-5.0, 5.0), _rig()), 1.0)

    def test_a_missing_proxy_is_zero_not_an_error(self) -> None:
        self.assertEqual(body_coverage(None, _rig()), 0.0)
        self.assertEqual(body_coverage(Mesh(name="empty"), _rig()), 0.0)

    def test_a_missing_rig_is_zero_not_an_error(self) -> None:
        self.assertEqual(body_coverage(_column(0.0, 1.5), None), 0.0)

    def test_a_degenerate_rig_does_not_divide_by_zero(self) -> None:
        flat = BoneHierarchy([BoneNode(0, "Root", -1, _at(0.0), Vec3())], "flat")
        self.assertEqual(body_coverage(_column(0.0, 1.5), flat), 0.0)
