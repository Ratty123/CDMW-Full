"""The character starts as a bare figure, and clothing appears only when it is worn.

The pinned baseline holds a coat and a pair of trousers, and those were being loaded as though
they *were* the body. So the figure had no hands, no feet and no face — and worse, the thing a
weapon's clipping was measured against was a coat, which has no arms in it at all.

The anatomy is in the packages instead: `nude/` carries the whole body down to fingers and toes,
`head/head/` carries the face. Neither sits under `armor/`, which is why the armour scan never
found them.
"""

from __future__ import annotations

import unittest

from tools.placement_studio.armour import (
    FACE_SLOT,
    NUDE_SLOT,
    ArmourIndex,
    ArmourPiece,
    _CACHE_VERSION,
)


def _index(*paths: str) -> ArmourIndex:
    pieces = []
    for path in paths:
        slot = NUDE_SLOT if "/nude/" in path else (FACE_SLOT if "/head/head/" in path else "13_hel")
        pieces.append(ArmourPiece(path=path, slot=slot, model="1_phm", source=object()))
    return ArmourIndex(pieces)


_NUDE = "character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac"
_FACE = "character/model/1_pc/1_phm/head/head/cd_phm_00_head_00_0001.pac"


class BaseBodyTests(unittest.TestCase):
    def test_the_bare_figure_is_a_body_and_a_face(self) -> None:
        """The nude mesh's head is a blank scalp, so the face has to come with it."""

        self.assertEqual(_index(_NUDE, _FACE).base_body("1_phm"), [_NUDE, _FACE])

    def test_the_plain_variant_wins_over_the_story_ones(self) -> None:
        """A model carries damage states and named variants; they all skin to the same rig."""

        index = _index(
            "character/model/1_pc/1_phm/nude/cd_phm_00_nude_40_6001.pac",
            _NUDE,
            "character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001_damian.pac",
        )

        self.assertEqual(index.base_body("1_phm"), [_NUDE])

    def test_a_model_with_no_anatomy_indexed_asks_for_nothing(self) -> None:
        """The caller falls back to the pinned meshes — a dressed body beats no body."""

        self.assertEqual(_index().base_body("1_phm"), [])
        self.assertEqual(_index(_NUDE, _FACE).base_body("2_phw"), [])

    def test_a_helmet_is_never_mistaken_for_the_body(self) -> None:
        index = _index(_NUDE, _FACE, "character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_0001.pac")

        self.assertEqual(index.base_body("1_phm"), [_NUDE, _FACE])

    def test_the_cache_was_versioned_past_the_armour_only_index(self) -> None:
        """A v1 file on disk has no anatomy in it, so it must be ignored rather than read."""

        self.assertGreaterEqual(_CACHE_VERSION, 2)


if __name__ == "__main__":
    unittest.main()
