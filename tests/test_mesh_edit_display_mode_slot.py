"""Remembering the Edit Mesh display mode must not raise into Qt.

`_mesh_edit_display_mode_slot()` called `normalize_mesh_preview_display_mode`
without importing it, so every viewport display-mode event the resident helper
sent raised `NameError` out of `_handle_dotnet_protocol_event` and into the Qt
signal that delivered it. The mode was never remembered, and the rest of that
handler never ran. Nothing failed at import and no test caught it, because the
name is only resolved when a running helper reports a mode change -- the
runtime-wiring blast radius this repository warns about, reached by a click.
"""

import unittest

from cdmw.ui.archive_browser import (
    static_replacement_dialog_sections_mesh_geometry_preview_part_01 as sections,
)
from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    normalize_mesh_preview_display_mode,
)


class MeshEditDisplayModeSlotTests(unittest.TestCase):
    def test_the_module_can_resolve_the_normalizer_it_calls(self) -> None:
        self.assertIs(
            getattr(sections, "normalize_mesh_preview_display_mode", None),
            normalize_mesh_preview_display_mode,
        )

    def test_remembering_a_mode_returns_it_rather_than_raising(self) -> None:
        remembered, remember = sections._mesh_edit_display_mode_slot()
        self.assertEqual(remembered["value"], "")
        known = normalize_mesh_preview_display_mode("wireframe") or "wireframe"
        self.assertTrue(remember(known))
        self.assertEqual(remembered["value"], known)

    def test_an_unknown_mode_settles_on_the_default_without_raising(self) -> None:
        """The normalizer never answers empty: it falls back to the default.

        So the slot's own `if not normalized` branch cannot be reached. What
        matters here is that neither an empty nor a nonsense mode raises, since
        both arrive from a helper the host does not control.
        """

        remembered, remember = sections._mesh_edit_display_mode_slot()
        default = normalize_mesh_preview_display_mode("")
        self.assertTrue(remember(""))
        self.assertEqual(remembered["value"], default)
        self.assertTrue(remember(None))
        self.assertTrue(remember("a mode that does not exist"))
        self.assertEqual(remembered["value"], default)

    def test_every_slot_keeps_its_own_value(self) -> None:
        """The placement combo and the Edit Mesh combo are separate slots."""

        first_remembered, first_remember = sections._mesh_edit_display_mode_slot()
        second_remembered, _second_remember = sections._mesh_edit_display_mode_slot()
        known = normalize_mesh_preview_display_mode("wireframe") or "wireframe"
        first_remember(known)
        self.assertEqual(first_remembered["value"], known)
        self.assertEqual(second_remembered["value"], "")


if __name__ == "__main__":
    unittest.main()
