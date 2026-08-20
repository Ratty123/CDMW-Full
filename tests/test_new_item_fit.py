"""Gates for the first placement an imported weapon lands at (`fitted_placement`).

The fit is a guess the reader corrects, so the only thing that matters about it is which
guess costs the least correction. For a weapon that is one long axis and a heavy end, the
answer is the grip: matching the two bounding boxes' middles instead leaves the handle
half a weapon from the hand, which is a big drag on every import whose mass sits at one
end -- an axe, a hammer, a halberd.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.ui.new_item.model_import import fitted_placement  # noqa: E402


def bounds(low, high):
    return (tuple(float(v) for v in low), tuple(float(v) for v in high))


class FitTests(unittest.TestCase):
    #: a template sword a metre long down z, its blade (the heavy end) at -z, grip at +z
    TEMPLATE = bounds((-0.05, -0.02, -0.90), (0.05, 0.02, 0.10))
    TEMPLATE_CENTROID = (0.0, 0.0, -0.55)

    def placed(self, source, source_centroid):
        placement = fitted_placement(
            source, self.TEMPLATE, source_centroid=source_centroid, template_centroid=self.TEMPLATE_CENTROID
        )
        low = placement.apply(source[0])
        high = placement.apply(source[1])
        return placement, (min(low[2], high[2]), max(low[2], high[2]))

    def test_the_grips_meet_rather_than_the_middles(self) -> None:
        """An axe: a metre long, and the head is most of it. Its grip has to land on the
        template's grip, not its centre on the template's centre."""

        axe = bounds((-0.2, -0.05, -1.0), (0.2, 0.05, 0.0))
        _placement, (low, high) = self.placed(axe, source_centroid=(0.0, 0.0, -0.75))
        self.assertAlmostEqual(high, 0.10, places=3, msg="the grip end sits where the template's grip is")
        self.assertAlmostEqual(low, -0.90, places=3, msg="and the head reaches the template's far end")

    def test_a_heavy_end_the_other_way_round_is_matched_the_other_way(self) -> None:
        axe = bounds((-0.2, -0.05, 0.0), (0.2, 0.05, 1.0))
        _placement, (low, high) = self.placed(axe, source_centroid=(0.0, 0.0, 0.75))
        self.assertAlmostEqual(low, -0.90, places=3)
        self.assertAlmostEqual(high, 0.10, places=3)

    def test_without_centroids_the_middles_meet_as_before(self) -> None:
        """Nothing says which end is which, so nothing is claimed: the boxes are centred,
        which is what the fit did for everything before."""

        axe = bounds((-0.2, -0.05, -1.0), (0.2, 0.05, 0.0))
        placement = fitted_placement(axe, self.TEMPLATE)
        low = placement.apply(axe[0])
        high = placement.apply(axe[1])
        middle = (min(low[2], high[2]) + max(low[2], high[2])) / 2.0
        self.assertAlmostEqual(middle, -0.40, places=3, msg="the template's own middle")

    def test_the_scale_still_matches_the_template_s_length(self) -> None:
        axe = bounds((-0.4, -0.1, -2.0), (0.4, 0.1, 0.0))
        placement, (low, high) = self.placed(axe, source_centroid=(0.0, 0.0, -1.5))
        self.assertAlmostEqual(placement.scale[0], 0.5, places=4, msg="two metres into one")
        self.assertAlmostEqual(high - low, 1.0, places=3)

    def test_nothing_to_fit_is_no_placement(self) -> None:
        self.assertEqual(fitted_placement(None, self.TEMPLATE).offset, (0.0, 0.0, 0.0))
        self.assertEqual(fitted_placement(self.TEMPLATE, None).scale, (1.0, 1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
