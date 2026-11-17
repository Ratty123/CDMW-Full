"""Edited textures reach the Mesh Editor's 3D view live (step 8, stage 2)."""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.live_texture_updates import EDITS_DIRNAME, LiveTextureUpdates, rgba8_dds_bytes

SHA = "ab" * 32


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait(app, predicate, timeout=5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _image(colour: str) -> QImage:
    image = QImage(4, 2, QImage.Format.Format_RGBA8888)
    image.fill(QColor(colour))
    return image


def test_the_dds_is_a_single_mip_rgba8_the_editor_reads() -> None:
    data = rgba8_dds_bytes(2, 1, bytes([1, 2, 3, 4, 5, 6, 7, 8]))
    assert data[:4] == b"DDS " and len(data) == 128 + 8
    size, flags, height, width, pitch, depth, mips = struct.unpack_from("<7I", data, 4)
    assert (size, height, width, pitch, mips) == (124, 1, 2, 8, 1)
    pf_size, pf_flags, fourcc, bits, red, green, blue, alpha = struct.unpack_from("<8I", data, 76)
    assert (pf_size, fourcc, bits) == (32, 0, 32)
    assert (red, green, blue, alpha) == (0xFF, 0xFF00, 0xFF0000, 0xFF000000)
    assert data[128:] == bytes([1, 2, 3, 4, 5, 6, 7, 8])


def test_one_update_in_flight_per_texture_and_the_latest_edit_wins(tmp_path: Path) -> None:
    app = _app()
    sent: list[dict] = []
    live = LiveTextureUpdates(lambda: tmp_path, lambda fields: sent.append(dict(fields)) or True)
    live.push(SHA, _image("red"))
    assert _wait(app, lambda: len(sent) == 1)
    first = sent[0]
    assert first["source_sha256"] == SHA and first["revision"] == 1
    assert first["file"].startswith(EDITS_DIRNAME + "/") and (tmp_path / first["file"]).is_file()
    # Two more strokes while the first is shown: only the latest goes next.
    live.push(SHA, _image("green"))
    live.push(SHA, _image("blue"))
    _wait(app, lambda: False, timeout=0.2)
    assert len(sent) == 1
    live.acknowledge({"source_sha256": SHA, "revision": 1, "ok": True})
    assert _wait(app, lambda: len(sent) == 2)
    assert sent[1]["revision"] == 3
    live.acknowledge({"source_sha256": SHA, "revision": 3, "ok": True})
    # The superseded file is removed; the shown one stays.
    assert not (tmp_path / first["file"]).exists()
    assert (tmp_path / sent[1]["file"]).is_file()


def test_edits_wait_for_the_editor_and_go_out_once_it_is_ready(tmp_path: Path) -> None:
    app = _app()
    ready = {"value": False}
    sent: list[dict] = []

    def send(fields):
        if not ready["value"]:
            return False
        sent.append(dict(fields))
        return True

    live = LiveTextureUpdates(lambda: tmp_path, send)
    live.push(SHA, _image("red"))
    _wait(app, lambda: False, timeout=0.3)
    assert sent == []
    ready["value"] = True
    live.flush()
    assert len(sent) == 1 and sent[0]["revision"] == 1


def test_a_refused_edit_is_reported() -> None:
    _app()
    failures: list[tuple[str, str]] = []
    live = LiveTextureUpdates(lambda: None, lambda fields: True)
    live.failed.connect(lambda sha, why: failures.append((sha, why)))
    live._textures[SHA] = live._textures.get(SHA) or __import__(
        "cdmw.ui.mesh_editor.live_texture_updates", fromlist=["_Texture"])._Texture(revision=1, in_flight=1, written={})
    live.acknowledge({"source_sha256": SHA, "revision": 1, "ok": False, "error": "wrong size"})
    assert failures == [(SHA, "wrong size")]


def test_edits_outlive_the_editor_session_until_discard(tmp_path: Path) -> None:
    """Finish ends the session and deletes its folder; the edit stays for Build Mod and
    is shown again in the document's next session. Discard forgets it."""

    app = _app()
    root = {"value": tmp_path / "first"}
    root["value"].mkdir()  # each session's preparation makes its folder
    sent: list[dict] = []
    live = LiveTextureUpdates(lambda: root["value"], lambda fields: sent.append(dict(fields)) or True)
    live.remember_source(SHA.upper(), "source info")
    live.push(SHA, _image("red"))
    assert _wait(app, lambda: len(sent) == 1)
    live.detach()  # Finish: the session and its folder go
    root["value"] = None
    assert list(live.edited_textures()) == [SHA] and live.sources == {SHA: "source info"}
    live.push(SHA, _image("green"))  # edited while no editor is open
    root["value"] = tmp_path / "second"
    root["value"].mkdir()
    live.reapply()  # Resume: the next session is ready
    assert _wait(app, lambda: len(sent) == 2)
    assert (tmp_path / "second" / sent[1]["file"]).is_file()
    assert live.edited_textures()[SHA].pixelColor(0, 0).green() == 128
    live.clear()  # Discard
    assert live.edited_textures() == {} and live.sources == {}


def test_an_edit_pushed_before_the_session_folder_exists_waits_and_never_makes_it(tmp_path):
    """B pass 12: a draft's kept texture edit was restored before the resumed session was
    prepared; writing it made the session folder, and the preparation (which refuses an
    existing folder) failed. The edit must wait and be shown once the editor is ready."""

    app = _app()
    session = tmp_path / "session-not-prepared-yet"
    sent: list[dict] = []
    live = LiveTextureUpdates(lambda: session, lambda fields: sent.append(dict(fields)) or True)
    live.push("ab" * 32, _image("#FF00FF"))
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    assert not session.exists()
    assert sent == []

    session.mkdir()  # the preparation made it; the editor is ready
    live.reapply()
    live.flush()
    assert _wait(app, lambda: bool(sent))
    written = list((session / EDITS_DIRNAME).glob("*.dds"))
    assert len(written) == 1
    assert sent[-1]["source_sha256"] == "ab" * 32
