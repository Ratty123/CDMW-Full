"""Review of ddc81f5d (8.7 E5, the helper's half): the page's reserved rule follows a side effect.

Settings > Shortcuts checks a Mesh Editor key with check_helper_keys, whose
reserved rule reads a module set that only palette_chords() updates, and only
the Mesh Editor's theme payload calls that. """

from __future__ import annotations

from PySide6.QtCore import QSettings

_REVIEW = "Review of ddc81f5d (REPORT-review.md): the reserved palette keys are stale until a helper payload"


def test_a_rebound_palette_key_is_refused_for_mesh_editor_commands_with_no_helper_running(tmp_path) -> None:
    from cdmw.services.keymap_store import set_override
    from cdmw.ui.commands import helper_keys
    from cdmw.ui.commands.palette import PALETTE_COMMAND

    fresh = QSettings(str(tmp_path / "fresh.ini"), QSettings.Format.IniFormat)
    helper_keys.palette_chords(fresh)  # a process that has not built a helper payload: the default
    settings = QSettings(str(tmp_path / "keys.ini"), QSettings.Format.IniFormat)
    try:
        # Settings > Shortcuts: the palette moves to Ctrl+K; no Mesh Editor runs.
        set_override(settings, PALETTE_COMMAND, ["Ctrl+K"])
        keys, reason = helper_keys.check_helper_keys(["Ctrl+K"], takes_modifier=False)
        assert reason, "a Mesh Editor command took the palette's key; the palette would swallow it"
        keys, reason = helper_keys.check_helper_keys(["Ctrl+Shift+P"], takes_modifier=False)
        assert not reason, "the palette's old key is free now"
    finally:
        set_override(settings, PALETTE_COMMAND, None)
        helper_keys.palette_chords(fresh)
