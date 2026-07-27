"""Decode and replay Crimson Desert `.paa` motion clips.

`format.parse_paa` reads a clip off disk, `pose.PoseEvaluator` samples it against a `.pab`
skeleton, and `gltf.write_glb` emits something a 3D viewer can actually play back.
"""

from .format import (
    FPS,
    BoneTrack,
    MotionClip,
    PaaFormatError,
    parse_paa,
)

__all__ = [
    "FPS",
    "BoneTrack",
    "MotionClip",
    "PaaFormatError",
    "parse_paa",
]
