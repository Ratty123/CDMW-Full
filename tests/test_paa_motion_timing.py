"""Time semantics are independent of lossless raw PAA key storage."""
from dataclasses import replace
import struct

import pytest

from tools.paa_motion.format import BoneTrack, MotionClip, Passthrough, FLAG_PACKED, parse_paa
from tools.paa_motion.encode import encode_paa
from tools.paa_motion.pose import sample_delta_seconds
from tools.paa_motion.timing import TimingError, duration_seconds
from tools.placement_studio.playback import Playback


def clip(*tracks, duration=1.0, lead=5):
    return MotionClip((2, 3), FLAG_PACKED, "", 1.0, "", duration, 0,
                      sum(not t.root_motion for t in tracks), sum(t.root_motion for t in tracks),
                      tuple(tracks), Passthrough(table_lead=struct.pack("<I", lead)))


def test_packed_skeleton_and_standard_root_share_seconds_not_key_indices():
    motion = clip(
        BoneTrack(1, translation=((0, (0., 0., 0.)), (5, (1., 0., 0.))), packed=True),
        BoneTrack(2, translation=((0, (0., 0., 0.)), (30, (0., 1., 0.))), root_motion=True),
    )
    assert sample_delta_seconds(motion, 1, .5).translation == (.5, 0., 0.)
    assert sample_delta_seconds(motion, 2, .5).translation == (0., .5, 0.)
    state = Playback()
    state.load(motion, "paired")
    state.looping = False
    state.playing = True
    assert state.advance(.2) and state.playing
    assert state.duration == 1 and state.last_frame == 30
    assert not state.advance(.8)
    assert state.seconds == 1


@pytest.mark.parametrize("tracks", [(), (BoneTrack(1, rotation=((0, (0., 0., 0., 1.)),)),)])
def test_declared_hold_duration_is_playable(tracks):
    state = Playback()
    state.load(clip(*tracks, duration=2.25), "hold")
    state.playing = True
    assert state.advance(1)
    assert state.last_frame == 68
    state.seek(1000)
    assert state.seconds == 2.25
    state.advance(.25)
    assert state.seconds == pytest.approx(.25)


def test_unknown_packed_clock_is_explicit_without_blocking_lossless_storage():
    motion = clip(BoneTrack(1, rotation=((0, (0., 0., 0., 1.)), (5, (0., 0., 1., 0.))), packed=True), lead=7)
    data = encode_paa(motion)
    assert encode_paa(parse_paa(data)) == data
    with pytest.raises(TimingError, match="Unverified"):
        duration_seconds(motion)


def test_zero_duration_falls_back_to_converted_keys_and_roundtrip_preserves_indices():
    motion = clip(BoneTrack(1, translation=((0, (0., 0., 0.)), (5, (1., 0., 0.))), packed=True), duration=0)
    data = encode_paa(motion)
    parsed = parse_paa(data)
    assert duration_seconds(parsed) == 1
    assert parsed.last_frame == 5
    assert encode_paa(parsed) == data
    assert sample_delta_seconds(parsed, 1, .5).translation[0] == .5


@pytest.mark.parametrize("duration", [-1, float("nan"), float("inf")])
def test_invalid_duration_cannot_enter_playback(duration):
    with pytest.raises(TimingError):
        Playback().load(clip(duration=duration), "invalid")
