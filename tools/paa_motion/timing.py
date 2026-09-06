"""Playback clocks, separate from the raw indices preserved by the PAA codec.

Standard records use 30 Hz. The validated packed-table profile (lead word 5)
uses 5 Hz skeletal keys and still uses 30 Hz for its standard root records.
Unknown profiles must not silently inherit either clock.
"""

from __future__ import annotations

import math
import struct

from .format import FPS, BoneTrack, MotionClip, PaaFormatError


class TimingError(PaaFormatError):
    """The file can be preserved, but its playback clock is not supported."""


def track_rate(clip: MotionClip, track: BoneTrack) -> float:
    if not track.packed:
        return FPS
    lead = clip.passthrough.table_lead
    # An in-memory clip with no passthrough is encoded with this canonical lead.
    if not lead or lead == struct.pack("<I", 5):
        return 5.0
    raise TimingError(f"Unverified packed animation timing: table lead {lead.hex()}")


def validate_timing(clip: MotionClip) -> None:
    if not math.isfinite(clip.duration) or clip.duration < 0:
        raise TimingError("Invalid animation duration")
    for track in clip.tracks:
        if track.animated:
            track_rate(clip, track)


def duration_seconds(clip: MotionClip) -> float:
    validate_timing(clip)
    if clip.duration > 0:
        return clip.duration
    return max((track.last_frame / track_rate(clip, track)
                for track in clip.tracks if track.animated), default=0.0)


def timeline_end(clip: MotionClip) -> float:
    """End on the public 30 Hz UI timeline; raw ``last_frame`` stays unchanged."""
    return duration_seconds(clip) * FPS


def key_position(clip: MotionClip, track: BoneTrack, seconds: float) -> float:
    return max(0.0, seconds) * track_rate(clip, track)
