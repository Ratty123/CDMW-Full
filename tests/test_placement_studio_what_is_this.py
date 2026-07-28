"""Gates for the badge and the "What is this for" dialog behind both rig panels.

The point of moving this text out of the panels was to make the one fact that matters --
whether an edit reaches the game -- visible without reading, and everything else one
click away. These pin both halves of that.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.placement_studio.constraints import guide as constraints_guide  # noqa: E402
from tools.placement_studio.rig_behaviour import guide as behaviour_guide  # noqa: E402
from tools.placement_studio.what_is_this import (  # noqa: E402
    BADGE_STYLES,
    Guide,
    Section,
    capability_sections,
    guide_html,
)


class RenderingTests(unittest.TestCase):
    def test_every_part_of_a_section_reaches_the_html(self) -> None:
        guide = Guide(
            title="T", badge="B", badge_kind="live", summary="the summary",
            sections=(
                Section(
                    heading="A heading",
                    body="Some body.",
                    bullets=("first bullet",),
                    examples=(("code()", "what it means"),),
                ),
            ),
        )

        html = guide_html(guide)

        for expected in ("the summary", "A heading", "Some body.", "first bullet",
                         "code()", "what it means"):
            self.assertIn(expected, html)

    def test_text_is_escaped_rather_than_injected(self) -> None:
        """Formulas contain `<` and `&`, and this is rendered as rich text."""

        guide = Guide(title="T", badge="B", badge_kind="live", summary="a < b & c")

        self.assertIn("a &lt; b &amp; c", guide_html(guide))
        self.assertNotIn("a < b & c", guide_html(guide))

    def test_prose_columns_are_not_rendered_as_code(self) -> None:
        mono = Section(heading="H", examples=(("x", "y"),))
        prose = Section(heading="H", examples=(("x", "y"),), mono=False)

        self.assertIn("<code>x</code>", guide_html(Guide("T", "B", "live", "s", (mono,))))
        self.assertIn("<b>x</b>", guide_html(Guide("T", "B", "live", "s", (prose,))))

    def test_an_unknown_badge_kind_falls_back_rather_than_raising(self) -> None:
        guide = Guide(title="T", badge="B", badge_kind="nonsense", summary="s")

        self.assertEqual(guide.badge_colours, BADGE_STYLES["experimental"])


class CapabilityTests(unittest.TestCase):
    def test_capabilities_split_into_a_can_and_a_cannot_section(self) -> None:
        table = ((True, "Do a thing", "because"), (False, "Not that", "reason"))

        can, cannot = capability_sections(table)

        self.assertEqual(can.examples, (("Do a thing", "because"),))
        self.assertEqual(cannot.examples, (("Not that", "reason"),))
        self.assertFalse(can.mono)


class PanelGuideTests(unittest.TestCase):
    """The two guides say the opposite thing, because the formats differ."""

    def test_driven_bones_is_flagged_experimental(self) -> None:
        guide = constraints_guide()

        self.assertEqual(guide.badge, "EXPERIMENTAL")
        self.assertEqual(guide.badge_kind, "experimental")
        self.assertIn("appears to read .papr", guide.summary)

    def test_rig_behaviour_is_flagged_as_taking_effect(self) -> None:
        guide = behaviour_guide()

        self.assertEqual(guide.badge, "TAKES EFFECT")
        self.assertEqual(guide.badge_kind, "live")
        self.assertIn("reads this file", guide.summary)

    def test_driven_bones_carries_its_evidence_and_worked_formulas(self) -> None:
        html = guide_html(constraints_guide())

        self.assertIn("Local_Euler_Y*1.5-1.7", html)
        self.assertIn("shipped binary", html)
        self.assertIn("Rig behaviour", html)

    def test_rig_behaviour_warns_that_a_block_is_shared(self) -> None:
        """The consequence a modder cannot see in the file and will not expect."""

        html = guide_html(behaviour_guide())

        self.assertIn("serves several characters", html)
        self.assertIn("DisabledKeyList", html)

    def test_no_guide_section_is_a_wall_of_text(self) -> None:
        """The whole reason for the dialog was that paragraphs were not being read."""

        for guide in (constraints_guide(), behaviour_guide()):
            for section in guide.sections:
                self.assertLessEqual(len(section.body), 320, section.heading)
                for bullet in section.bullets:
                    self.assertLessEqual(len(bullet), 220, bullet)


class StripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_the_strip_shows_the_badge_and_a_button(self) -> None:
        from tools.placement_studio.what_is_this import guide_strip

        guide = constraints_guide()
        strip, badge, button = guide_strip(guide)
        self._strip = strip  # Qt owns the children; keep the parent alive.

        self.assertEqual(badge.text(), "EXPERIMENTAL")
        self.assertEqual(guide.summary, badge.toolTip())
        self.assertIn("What is this for", button.text())

    def test_the_badge_is_coloured_by_its_kind(self) -> None:
        from tools.placement_studio.what_is_this import guide_strip

        strip, warning, _button = guide_strip(constraints_guide())
        self._a = strip
        strip2, live, _b = guide_strip(behaviour_guide())
        self._b = strip2

        self.assertIn(BADGE_STYLES["experimental"][0], warning.styleSheet())
        self.assertIn(BADGE_STYLES["live"][0], live.styleSheet())


if __name__ == "__main__":
    unittest.main()
