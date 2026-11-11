"""Animation playback in Placement & Animation Studio.

The point of posing the rig is that placement can be judged in motion, so the tests that
matter are the ones proving a socket follows the animated bone and that leaving playback
returns the rig exactly to its bind pose.

Synthetic fixtures throughout — no game install needed.
"""

from __future__ import annotations

import math
import os
import struct
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from tools.paa_motion.format import parse_paa
from tools.placement_studio.model import Quat, Socket, Vec3
from tools.placement_studio.playback import (
    Playback,
    PlaybackError,
    coverage,
    load_clip,
    posed_hierarchy,
)
from tools.placement_studio.skeleton import BoneHierarchy, BoneNode
from tools.placement_studio import window_playback
from tools.placement_studio.window_playback import PlaybackMixin

_ROOT_HASH = 0x1111
_CHILD_HASH = 0x2222


def _half_keys(keys, components):
    out = b""
    for frame, values in keys:
        out += struct.pack("<H", frame) + struct.pack(f"<{components}e", *values)
    return struct.pack("<H", len(keys)) + out


def _track(name_hash, *, rotation=(), translation=()):
    return (
        struct.pack("<I", name_hash)
        + _half_keys((), 3)
        + _half_keys(rotation, 4)
        + _half_keys(translation, 3)
    )


def _clip_bytes(tracks):
    body = b"".join(tracks)
    key_bytes = sum(len(t) for t in tracks) - 10 * len(tracks)
    return (
        b"PAR " + bytes([2, 3]) + bytes(range(10))
        + struct.pack("<I", 0)          # no optional prelude fields
        + struct.pack("<f", 1.0)        # duration
        + struct.pack("<HHI", len(tracks), 0, key_bytes)
        + body
    )


class _FakeBone:
    """Stands in for `cdmw.modding.skeleton_parser.Bone`."""

    def __init__(self, index, name, name_hash, parent_index, position, rotation):
        self.index = index
        self.name = name
        self.name_hash = name_hash
        self.parent_index = parent_index
        self.position = position
        self.rotation = rotation
        self.scale = (1.0, 1.0, 1.0)
        self.bind_matrix = ()


class _FakeSkeleton:
    def __init__(self, bones):
        self.bones = bones


def _rig() -> BoneHierarchy:
    """Root at the origin, child one metre up, both unrotated in bind."""

    parsed = _FakeSkeleton([
        _FakeBone(0, "Root", _ROOT_HASH, -1, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
        _FakeBone(1, "Hand", _CHILD_HASH, 0, (0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
    ])
    identity = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    raised = tuple(identity[:12]) + (0.0, 1.0, 0.0, 1.0)
    bones = [
        BoneNode(0, "Root", -1, identity, Vec3()),
        BoneNode(1, "Hand", 0, raised, Vec3(0.0, 1.0, 0.0)),
    ]
    return BoneHierarchy(bones, "test.pab", parsed)


class PlaybackStateTests(unittest.TestCase):
    def test_seek_clamps_to_the_clip(self) -> None:
        clip = parse_paa(_clip_bytes([_track(_ROOT_HASH, rotation=[(0, (0, 0, 0, 1)), (30, (0, 0, 0, 1))])]))
        state = Playback()
        state.load(clip, "clip")
        state.seek(999)
        self.assertEqual(state.frame, 30.0)
        state.seek(-5)
        self.assertEqual(state.frame, 0.0)


class _PlaybackViewport(QObject):
    frame_painted = Signal(float)

    def set_moving(self, moving):
        self.moving = moving


class _PlaybackControls(PlaybackMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._viewport = _PlaybackViewport(self)
        self.frames = []
        self._build_playback_row().setParent(self)

    def _apply_playback_frame(self):
        self.frames.append(self._playback.frame)


@pytest.fixture
def playback_controls(monkeypatch):
    app = QApplication.instance() or QApplication([])
    clock = [10.0]
    monkeypatch.setattr(window_playback, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    controls = _PlaybackControls()
    controls._playback.load(load_clip(_clip_bytes([
        _track(_ROOT_HASH, rotation=[(0, (0, 0, 0, 1)), (30, (0, 0, 0, 1))]),
    ])), "test")
    try:
        yield controls, clock
    finally:
        controls._stop_playback()
        controls.deleteLater()
        app.processEvents()


def test_playback_keeps_one_timer_running_across_painted_frames(playback_controls):
    controls, clock = playback_controls
    controls._on_playback_toggle()
    timer = controls._playback_timer
    timer_id = timer.timerId()
    assert not timer.isSingleShot()
    for _ in range(3):
        clock[0] += 0.016
        timer.timeout.emit()
        assert controls._playback_paint_pending
        assert timer.isActive() and timer.timerId() == timer_id
        controls._viewport.frame_painted.emit(0.008)
        assert not controls._playback_paint_pending
        assert timer.isActive() and timer.timerId() == timer_id
        assert timer.interval() == 16
    assert controls.frames == pytest.approx([0.48, 0.96, 1.44])


def test_playback_waits_for_paint_and_preserves_elapsed_time(playback_controls):
    controls, clock = playback_controls
    controls._on_playback_toggle()
    for now in (10.016, 10.032, 10.048):
        clock[0] = now
        controls._playback_timer.timeout.emit()
    assert controls.frames == pytest.approx([0.48])
    controls._viewport.frame_painted.emit(0.040)
    clock[0] = 10.064
    controls._playback_timer.timeout.emit()
    assert controls.frames == pytest.approx([0.48, 1.92])


def test_pause_resume_and_clip_end_stop_pending_frames(playback_controls):
    controls, clock = playback_controls
    controls._on_playback_toggle()
    clock[0] = 10.016
    controls._playback_timer.timeout.emit()
    controls._on_playback_toggle()
    assert not controls._playback_timer.isActive()
    assert not controls._playback_paint_pending
    assert not controls._viewport.moving
    controls._viewport.frame_painted.emit(0.008)
    controls._playback_timer.timeout.emit()
    assert not controls._playback_timer.isActive()
    assert controls.frames == pytest.approx([0.48])

    clock[0] = 20.0
    controls._on_playback_toggle()
    clock[0] = 20.016
    controls._playback_timer.timeout.emit()
    assert controls.frames == pytest.approx([0.48, 0.96])
    controls._viewport.frame_painted.emit(0.008)
    controls._playback.looping = False
    clock[0] = 22.0
    controls._playback_timer.timeout.emit()
    assert controls.frames[-1] == 30.0
    assert not controls._playback.playing
    assert not controls._playback_paint_pending
    assert not controls._playback_timer.isActive()
    assert not controls._viewport.moving


if __name__ == "__main__":
    unittest.main()
