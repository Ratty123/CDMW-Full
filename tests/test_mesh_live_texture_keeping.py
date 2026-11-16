"""Step 8 item 3: a document's live texture edits are kept in its draft and come back."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from cdmw.services.mesh_live_texture_drafts import restore_live_edits
from cdmw.services.mesh_live_texture_output import LiveTextureSource
from cdmw.ui.mesh_editor.live_edit import end_edit_prompt
from cdmw.ui.mesh_editor.live_texture_keeping import KEPT_TEXT, NOT_KEPT_TEXT, LiveTextureKeeper
from cdmw.ui.mesh_editor.live_texture_updates import LiveTextureUpdates

_APP = QApplication.instance() or QApplication([])
KEY = "c" * 64
GAME = "character/texture/cd_phm_00_ub_00_0374_n.dds"


def _wait(condition, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _APP.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def _image(colour: str) -> QImage:
    image = QImage(8, 4, QImage.Format.Format_RGBA8888)
    image.fill(QColor(colour))
    return image


def _document(tmp_path: Path, *, draft: bool = True):
    session = tmp_path / "session"
    session.mkdir(exist_ok=True)
    live = LiveTextureUpdates(lambda: session, lambda _fields: True, pool=QThreadPool())
    folder = tmp_path / "draft"
    if draft:
        folder.mkdir(exist_ok=True)
        (folder / "modify_original_workspace.json").write_text("{}", encoding="utf-8")
    root = {"value": folder if draft else None}
    keeper = LiveTextureKeeper(live, lambda: root["value"], pool=QThreadPool(), delay_ms=10)
    original = SimpleNamespace(dds_format="BC5_UNORM")
    live.remember_source(KEY, LiveTextureSource(game_path=GAME, original=original, role="normal"))
    return live, keeper, folder, root


def test_an_edit_is_kept_a_moment_later_and_an_undo_to_the_original_forgets_it(tmp_path):
    live, keeper, folder, _root = _document(tmp_path)
    texts: list[str] = []
    keeper.kept_changed.connect(texts.append)
    live.push(KEY, _image("#ff0000"))
    keeper.edited()
    assert keeper.unkept_count() == 1 and texts[-1] == NOT_KEPT_TEXT
    _wait(lambda: keeper.unkept_count() == 0)
    (kept,) = restore_live_edits(folder)
    assert (kept.live_key, kept.role, kept.game_path) == (KEY, "normal", GAME)
    assert tuple(kept.rgba[0, 0]) == (255, 0, 0, 255)
    assert texts[-1] == KEPT_TEXT
    live.push(KEY, _image("#000000"), changed=False)  # undone back to the opened texture
    keeper.edited()
    _wait(lambda: keeper.unkept_count() == 0)
    assert restore_live_edits(folder) == ()


def test_finish_keeps_the_edits_once_the_draft_folder_exists(tmp_path):
    live, keeper, folder, root = _document(tmp_path, draft=False)
    live.push(KEY, _image("#00ff00"))
    keeper.finished()
    _APP.processEvents()
    assert keeper.unkept_count() == 1  # no draft yet: waits for the one Finish writes
    folder.mkdir()
    root["value"] = folder
    _wait(lambda: keeper.unkept_count() == 0)
    assert tuple(restore_live_edits(folder)[0].rgba[0, 0]) == (0, 255, 0, 255)


def test_a_reopened_draft_shows_its_kept_edits_again(tmp_path):
    live, keeper, folder, _root = _document(tmp_path)
    live.push(KEY, _image("#0000ff"))
    keeper.edited()
    _wait(lambda: keeper.unkept_count() == 0)
    # After a restart: a new document over the same draft.
    pushed: list[tuple[str, tuple[int, int, int, int]]] = []
    reopened = LiveTextureUpdates(lambda: None, lambda _fields: True, pool=QThreadPool())
    original_push = reopened.push

    def recording(key, image, **kwargs):
        pushed.append((key, image.pixelColor(0, 0).getRgb()))
        return original_push(key, image, **kwargs)

    reopened.push = recording
    keeper2 = LiveTextureKeeper(reopened, lambda: folder, pool=QThreadPool(), delay_ms=10)
    statuses: list[str] = []
    keeper2.status.connect(lambda text, _error: statuses.append(text))
    assert keeper2.restore(folder)
    _wait(lambda: pushed)
    assert pushed == [(KEY, (0, 0, 255, 255))]
    # What the draft holds is kept already, and Build Mod finds its game path and role.
    assert keeper2.unkept_count() == 0 and keeper2.restored_info[KEY] == ("normal", GAME)
    assert np.any(np.asarray(reopened.edited_textures()[KEY].pixelColor(0, 0).getRgb()))
    assert statuses and "shown on the model again" in statuses[-1]
    assert not keeper2.restore(tmp_path / "no-draft")


def test_closing_with_texture_edits_not_kept_asks_first(tmp_path):
    live, keeper, _folder, _root = _document(tmp_path, draft=False)
    tab = SimpleNamespace(live_edit=SimpleNamespace(is_ready=False), _live_texture_keeping=keeper,
                          standalone_rust_authoring_session=None)
    assert not end_edit_prompt.has_pending_edit(tab)
    live.push(KEY, _image("#ffffff"))
    assert end_edit_prompt.has_pending_edit(tab)
