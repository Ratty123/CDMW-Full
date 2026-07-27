"""Shipping a different animation at an existing clip's path.

This is how the working mods change a draw, and it is not what the tool first attempted. A
chart names each clip as a length-prefixed full path, so retargeting one needs a replacement
of exactly the same byte length — and none exists among the back draws. Replacing the file
behind the path avoids the question: the chart still names what it always named.
"""

from __future__ import annotations

import unittest

from tools.placement_studio.editing import EditError, EditSession

_CLIP = "character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_out_000.paa"
_OTHER = "character/motion/1_pc/1_phm/cd_phm_sword_00_01_normal_stand_weapon_in_000.paa"


def _session() -> EditSession:
    return EditSession({_CLIP: b"PAR hip draw bytes", _OTHER: b"PAR hip sheathe bytes"})


class ClipReplacementTests(unittest.TestCase):
    def test_the_replacement_is_what_gets_exported(self) -> None:
        session = _session()

        session.replace_clip(_CLIP, b"PAR back draw bytes", source="cd_phm_lswd_back")

        self.assertEqual(session.preview()[_CLIP], b"PAR back draw bytes")
        self.assertIn(_CLIP, session.modified_paths())

    def test_an_untouched_clip_is_not_exported(self) -> None:
        session = _session()

        session.replace_clip(_CLIP, b"PAR back draw bytes")

        self.assertNotIn(_OTHER, session.modified_paths())

    def test_writing_back_the_original_bytes_is_not_a_change(self) -> None:
        """Choosing the clip that is already there must not produce a mod that ships nothing."""

        session = _session()

        session.replace_clip(_CLIP, b"PAR hip draw bytes", original=b"PAR hip draw bytes")

        self.assertNotIn(_CLIP, session.modified_paths())

    def test_an_empty_payload_is_refused(self) -> None:
        with self.assertRaises(EditError):
            _session().replace_clip(_CLIP, b"")

    def test_replacing_twice_keeps_only_the_last_choice(self) -> None:
        session = _session()

        session.replace_clip(_CLIP, b"PAR first choice")
        session.replace_clip(_CLIP, b"PAR second choice")

        self.assertEqual(session.preview()[_CLIP], b"PAR second choice")

    def test_the_change_is_undoable(self) -> None:
        session = _session()
        session.replace_clip(_CLIP, b"PAR back draw bytes")

        session.undo()

        self.assertNotIn(_CLIP, session.modified_paths())

    def test_the_diff_names_the_animation_that_was_chosen(self) -> None:
        session = _session()

        session.replace_clip(_CLIP, b"PAR back draw bytes", source="cd_phm_lswd_back_draw")

        self.assertTrue(
            any("cd_phm_lswd_back_draw" in line for line in session.diff()),
            f"the pending-changes list does not say what was used: {session.diff()}",
        )

    def test_the_plan_carries_the_replacement(self) -> None:
        session = _session()

        session.replace_clip(_CLIP, b"PAR back draw bytes")

        self.assertTrue(session.to_plan().operations, "nothing would be packaged")


if __name__ == "__main__":
    unittest.main()
