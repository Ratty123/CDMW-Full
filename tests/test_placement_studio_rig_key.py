"""What the two rig panels key on: the skeleton the character loaded, not its model id.

`.papr` sits beside the `.pab`, and `posemodifierdata.xml` is keyed by `.pab`. A
customization variant such as `phw_damian_01` has no skeleton of its own and runs on
`phw_01.pab`, so keying either panel on the model id finds nothing for exactly the
characters a modder is most likely to be looking at.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.placement_studio.constraints import constraint_path_for_model  # noqa: E402
from tools.placement_studio.rig_behaviour import pab_for_model  # noqa: E402
from tools.placement_studio.session import PlacementSession  # noqa: E402

_APP = QApplication.instance() or QApplication([])


class SkeletonPathTests(unittest.TestCase):
    """`PlacementSession` records which `.pab` it actually resolved."""

    def _session(self, model: str = "1_phm"):
        from tools.placement_studio.corpus import Baseline

        try:
            return PlacementSession.from_baseline(Baseline.load(), model)
        except Exception as error:  # noqa: BLE001 - needs the pinned baseline
            raise unittest.SkipTest(f"no baseline available: {error}")

    def test_a_loaded_session_names_the_pab_it_read(self) -> None:
        session = self._session()

        self.assertTrue(session.skeleton_path.endswith(".pab"), session.skeleton_path)
        self.assertIn(session.model, session.skeleton_path)

    def test_a_session_with_no_skeleton_reports_an_empty_path(self) -> None:
        """Empty, not a guess: the rig panels must be able to tell there is nothing."""

        session = self._session("no_such_model")
        self.assertEqual(session.skeleton_path, "")


class RigKeyTests(unittest.TestCase):
    """Both resolvers agree on what a skeleton path means."""

    PAPR = (
        "character/model/1_pc/1_phm/phm_01.papr",
        "character/model/1_pc/2_phw/phw_01.papr",
    )

    def test_a_skeleton_path_finds_the_papr_beside_it(self) -> None:
        self.assertEqual(
            constraint_path_for_model("character/model/1_pc/1_phm/phm_01.pab", self.PAPR),
            "character/model/1_pc/1_phm/phm_01.papr",
        )

    def test_the_same_path_finds_the_pose_modifier_key(self) -> None:
        keys = ("phm_01.pab", "phw_01.pab")
        self.assertEqual(
            pab_for_model("character/model/1_pc/1_phm/phm_01.pab", keys), "phm_01.pab"
        )

    def test_a_variant_keys_on_the_rig_it_shares_not_on_its_own_name(self) -> None:
        """`phw_damian_01` loads `phw_01.pab`, so both panels must land on PHW."""

        shared = "character/model/1_pc/2_phw/phw_01.pab"

        self.assertEqual(
            constraint_path_for_model(shared, self.PAPR),
            "character/model/1_pc/2_phw/phw_01.papr",
        )
        self.assertEqual(pab_for_model(shared, ("phw_01.pab",)), "phw_01.pab")
        # The model id on its own finds neither.
        self.assertIsNone(pab_for_model("phw_damian_01", ("phw_01.pab",)))


class WindowKeyTests(unittest.TestCase):
    """The window hands the panels that key, and re-uses it across variants."""

    def test_the_key_is_the_skeleton_path_and_the_display_label(self) -> None:
        from tools.placement_studio.window import PlacementStudioWindow

        window = PlacementStudioWindow.__new__(PlacementStudioWindow)
        window._session = None
        self.assertEqual(window._rig_key(), ("", ""))

        class _Session:
            skeleton_path = "character/model/1_pc/2_phw/phw_01.pab"
            model = "phw_damian_01"
            label = "Damian"

        window._session = _Session()
        self.assertEqual(
            window._rig_key(), ("character/model/1_pc/2_phw/phw_01.pab", "Damian")
        )

    def test_a_session_without_a_skeleton_falls_back_to_the_model(self) -> None:
        """A creature with no `.pab` in the baseline still names itself in the message."""

        from tools.placement_studio.window import PlacementStudioWindow

        window = PlacementStudioWindow.__new__(PlacementStudioWindow)

        class _Session:
            skeleton_path = ""
            model = "cd_m0001_00_bear"
            label = "Bear"

        window._session = _Session()
        self.assertEqual(window._rig_key(), ("cd_m0001_00_bear", "Bear"))


if __name__ == "__main__":
    unittest.main()
