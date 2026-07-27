"""The Inspector and pending-changes panels are read by scanning, not by reading.

Both were walls of monospaced text in which a socket name, a count and a warning all looked
identical. These check the structure survives — and in particular that the colour actually
reaches the widget, which is where the first attempt failed silently: Qt's rich-text engine
ignores class selectors in a <style> block, so every colour has to ride on the element.
"""

from __future__ import annotations

import unittest

from tools.placement_studio.report_style import (
    NAME,
    VALUE,
    WARN,
    inspector_html,
    pending_changes_html,
)


class PendingChangesTests(unittest.TestCase):
    def _html(self) -> str:
        return pending_changes_html(
            ["2 edit(s), 3 operation(s), 1 file(s)", "tiers: {'B': 2}"],
            ["character/descriptors/thing.xml", "  [B] thing.xml :: moved a socket"],
        )

    def test_colour_is_inline_so_qt_actually_applies_it(self) -> None:
        html = self._html()

        self.assertIn("style=", html)
        self.assertNotIn("class=", html, "Qt ignores class selectors in rich text")
        self.assertIn(NAME, html)

    def test_a_file_stands_out_from_its_operations(self) -> None:
        html = self._html()

        self.assertIn("font-weight:bold", html.replace(" ", ""))
        self.assertIn("margin-left", html)

    def test_the_tier_marker_is_picked_out(self) -> None:
        self.assertIn(f"style='color:{VALUE}", self._html().replace('"', "'"))

    def test_an_empty_plan_says_so_rather_than_rendering_blank(self) -> None:
        self.assertIn("Nothing has been changed", pending_changes_html([], []))

    def test_markup_in_the_data_cannot_reach_the_page(self) -> None:
        html = pending_changes_html([], ["<script>x</script>"])

        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class InspectorTests(unittest.TestCase):
    def test_a_heading_is_separated_from_its_fields(self) -> None:
        html = inspector_html("SOCKET Pelvis_L_Socket\n  parent bone: Bip01 Pelvis")

        self.assertIn("<h3", html)
        self.assertIn("margin-left", html)

    def test_a_key_and_its_value_are_told_apart(self) -> None:
        html = inspector_html("used by: 3 row(s)")

        self.assertIn(VALUE, html)
        self.assertIn("used by:", html)

    def test_a_warning_is_coloured_as_one(self) -> None:
        self.assertIn(WARN, inspector_html("WARNING: dangling socket"))

    def test_ordinary_lines_are_not_mistaken_for_warnings(self) -> None:
        self.assertNotIn(WARN, inspector_html("rotation: 0.0 0.0 0.0 1.0"))

    def test_markup_in_the_data_cannot_reach_the_page(self) -> None:
        self.assertNotIn("<b>", inspector_html("name: <b>x</b>"))


if __name__ == "__main__":
    unittest.main()
