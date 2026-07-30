"""The preview pane's chooser for the sounds a Wwise bank embeds."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cdmw.core.archive_media_preview import _decode_wem_with_vgmstream  # noqa: E402
from cdmw.models import ArchivePreviewTrack  # noqa: E402
from cdmw.ui.preview_widgets import MediaPreviewWidget  # noqa: E402

_APP = QApplication.instance() or QApplication([])


def _tracks(count: int) -> tuple[ArchivePreviewTrack, ...]:
    return tuple(
        ArchivePreviewTrack(index=index, name=str(1000 + index), size=index * 16)
        for index in range(1, count + 1)
    )


class SoundChooserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.widget = MediaPreviewWidget("Nothing selected.", theme_key="dark")
        self.addCleanup(self.widget.deleteLater)
        self.selected: list[int] = []
        self.widget.track_selected.connect(self.selected.append)

    def test_an_ordinary_single_stream_file_shows_no_chooser(self) -> None:
        # `isVisibleTo` asks whether the child would show when its parent does.
        # Plain `isVisible` is False for every child of an unshown window, so it
        # would pass here whether or not the row was actually hidden.
        self.widget.set_tracks(_tracks(1), 1)
        self.assertFalse(self.widget.track_label.isVisibleTo(self.widget))
        self.assertFalse(self.widget.track_combo.isVisibleTo(self.widget))

    def test_a_bank_lists_every_sound_it_embeds(self) -> None:
        self.widget.set_tracks(_tracks(3), 2)
        self.assertEqual(self.widget.track_combo.count(), 3)
        self.assertEqual(self.widget.track_combo.currentData(), 2)
        self.assertIn("1001", self.widget.track_combo.itemText(0))

    def test_populating_the_chooser_does_not_request_a_sound(self) -> None:
        # The combo's index moves while it is being filled, so without the guard
        # the pane would re-request the sound that is already playing.
        self.widget.set_tracks(_tracks(4), 3)
        self.assertEqual(self.selected, [])

    def test_choosing_a_sound_requests_that_subsong(self) -> None:
        self.widget.set_tracks(_tracks(4), 1)
        self.widget.track_combo.setCurrentIndex(2)
        self.assertEqual(self.selected, [3])

    def test_moving_off_a_bank_takes_the_chooser_away(self) -> None:
        self.widget.set_tracks(_tracks(3), 1)
        self.assertTrue(self.widget.track_combo.isVisibleTo(self.widget))
        self.widget.set_tracks((), 0)
        self.assertFalse(self.widget.track_combo.isVisibleTo(self.widget))
        self.assertEqual(self.widget.track_combo.count(), 0)


class SubsongDecodeTests(unittest.TestCase):
    def test_each_sound_decodes_to_its_own_cached_wav(self) -> None:
        # One cache name shared across sounds would serve whichever was decoded
        # first for every row afterwards.
        commands: list[list[str]] = []
        outputs: list[str] = []

        class _Result:
            returncode = 0

        def fake_popen(command, **kwargs):
            commands.append(list(command))
            outputs.append(command[command.index("-o") + 1])
            raise _StopDecode()

        class _StopDecode(Exception):
            pass

        import cdmw.core.archive_media_preview as media_preview

        original_popen = media_preview.subprocess.Popen
        original_resolve = media_preview._resolve_vgmstream_cli_path
        media_preview.subprocess.Popen = fake_popen
        media_preview._resolve_vgmstream_cli_path = lambda: __import__("pathlib").Path("vgmstream-cli.exe")
        try:
            for subsong in (1, 2):
                with self.assertRaises(_StopDecode):
                    _decode_wem_with_vgmstream(
                        __import__("pathlib").Path("bank.bnk"),
                        subsong=subsong,
                    )
        finally:
            media_preview.subprocess.Popen = original_popen
            media_preview._resolve_vgmstream_cli_path = original_resolve

        self.assertEqual(len(commands), 2)
        for subsong, command in zip((1, 2), commands):
            self.assertIn("-s", command)
            self.assertEqual(command[command.index("-s") + 1], str(subsong))
        self.assertNotEqual(outputs[0], outputs[1])

    def test_a_single_stream_decode_asks_for_no_subsong(self) -> None:
        commands: list[list[str]] = []

        class _StopDecode(Exception):
            pass

        def fake_popen(command, **kwargs):
            commands.append(list(command))
            raise _StopDecode()

        import cdmw.core.archive_media_preview as media_preview

        original_popen = media_preview.subprocess.Popen
        original_resolve = media_preview._resolve_vgmstream_cli_path
        media_preview.subprocess.Popen = fake_popen
        media_preview._resolve_vgmstream_cli_path = lambda: __import__("pathlib").Path("vgmstream-cli.exe")
        try:
            with self.assertRaises(_StopDecode):
                _decode_wem_with_vgmstream(__import__("pathlib").Path("voice.wem"))
        finally:
            media_preview.subprocess.Popen = original_popen
            media_preview._resolve_vgmstream_cli_path = original_resolve

        self.assertNotIn("-s", commands[0])


if __name__ == "__main__":
    unittest.main()
