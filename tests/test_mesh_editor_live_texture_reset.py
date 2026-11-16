"""A new session starts its texture edits afresh (B pass 6: Start Fresh brought the
last session's kept edit back)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor import live_texture_reset
from cdmw.ui.mesh_editor.live_texture_keeping import LiveTextureKeeper

_APP = QApplication.instance() or QApplication([])


class _Live:
    def __init__(self) -> None:
        self.cleared = 0

    def clear(self) -> None:
        self.cleared += 1

    def unkept(self):
        return {}

    def edited_textures(self):
        return {}


def _session(path: Path):
    return SimpleNamespace(document=SimpleNamespace(source_binding=SimpleNamespace(source_path=str(path))))


def test_a_new_session_forgets_the_last_one_s_texture_edits(tmp_path):
    old = tmp_path / "old" / "texture-0001-aaaaaaaaaaaa.dds"
    other = tmp_path / "elsewhere.dds"
    for path in (old, other):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"DDS ")
    closed = []
    editor = SimpleNamespace(_sessions=[_session(other), _session(old)],
                             _close_document_tabs=lambda indices: closed.append(list(indices)))
    dock = SimpleNamespace(_targets={"k": SimpleNamespace(source_path=str(old), session_id="s")},
                           target="the old target", editor=editor)
    live = _Live()
    keeper = LiveTextureKeeper(live, lambda: None)
    keeper.restored_info["k"] = ("base_color", "character/texture/a.dds")
    component = SimpleNamespace(_live_texture_updates=live, _live_texture_keeping=keeper,
                                _shared_edit_history="the last session's")
    tab = SimpleNamespace(live_edit=component, _texture_tools_panel=lambda: dock)

    live_texture_reset.start_texture_edits_afresh(tab)

    assert live.cleared == 1
    assert keeper.restored_info == {}
    assert component._shared_edit_history is None
    # Only the old session's document closes in the Texture Editor.
    assert closed == [[1]]
    assert dock._targets == {} and dock.target is None


def test_nothing_open_is_fine():
    tab = SimpleNamespace(_texture_tools_panel=lambda: None)
    live_texture_reset.start_texture_edits_afresh(tab)
    assert tab._shared_edit_history is None


def test_the_session_load_resets_before_it_restores_the_draft():
    # The order in the session load: forget the last session's edits, then restore what
    # the continued draft kept (otherwise the restore would be wiped, or Start Fresh would
    # show the old edits).
    source = Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "mesh_editor" / "tab_session_runtime.py"
    text = source.read_text(encoding="utf-8")
    reset = text.index("start_texture_edits_afresh(self)")
    restore = text.index("self._live_texture_keeper().restore(draft_root)")
    assert reset < restore
