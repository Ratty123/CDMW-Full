"""Write a decoded clip out as a `.glb` so a 3D viewer can play it back.

The skeleton becomes a glTF node hierarchy and the clip becomes one animation. Samples are
baked at the union of each bone's own key frames rather than resampled to every frame:
composing the bind pose onto a delta is a constant right-multiply for rotation and an
affine map for translation, and both commute with the interpolation glTF performs, so the
sparse keys survive the trip exactly.

Joints optionally carry a small shared cube mesh. glTF nodes with no mesh render as
nothing in most viewers, and an animation you cannot see is not much of a deliverable.
"""

from __future__ import annotations

import json
import struct
from typing import Sequence

from .format import FPS, MotionClip
from .pose import (
    bind_transform,
    compose,
    sample_delta_channel,
)

_JOINT_CUBE_RADIUS = 0.008


class _BufferBuilder:
    """Accumulates the GLB binary chunk and hands back accessor indices."""

    def __init__(self) -> None:
        self.blob = bytearray()
        self.views: list[dict] = []
        self.accessors: list[dict] = []

    def _view(self, payload: bytes, target: int | None = None) -> int:
        while len(self.blob) % 4:
            self.blob.append(0)
        offset = len(self.blob)
        self.blob.extend(payload)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload)}
        if target is not None:
            view["target"] = target
        self.views.append(view)
        return len(self.views) - 1

    def scalars(self, values: Sequence[float]) -> int:
        view = self._view(struct.pack(f"<{len(values)}f", *values))
        self.accessors.append({
            "bufferView": view, "componentType": 5126, "count": len(values), "type": "SCALAR",
            "min": [min(values)], "max": [max(values)],
        })
        return len(self.accessors) - 1

    def vectors(self, rows: Sequence[Sequence[float]], kind: str) -> int:
        width = {"VEC3": 3, "VEC4": 4}[kind]
        flat = [component for row in rows for component in row]
        view = self._view(struct.pack(f"<{len(flat)}f", *flat))
        self.accessors.append({
            "bufferView": view, "componentType": 5126, "count": len(rows), "type": kind,
            "min": [min(row[i] for row in rows) for i in range(width)],
            "max": [max(row[i] for row in rows) for i in range(width)],
        })
        return len(self.accessors) - 1

    def indices(self, values: Sequence[int]) -> int:
        view = self._view(struct.pack(f"<{len(values)}H", *values), target=34963)
        self.accessors.append({
            "bufferView": view, "componentType": 5123, "count": len(values), "type": "SCALAR",
        })
        return len(self.accessors) - 1

    def positions(self, rows: Sequence[Sequence[float]]) -> int:
        accessor = self.vectors(rows, "VEC3")
        self.views[self.accessors[accessor]["bufferView"]]["target"] = 34962
        return accessor


def _cube(radius: float) -> tuple[list[tuple[float, float, float]], list[int]]:
    corners = [
        (x * radius, y * radius, z * radius)
        for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)
    ]
    faces = [
        (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5),
        (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6),
        (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3),
    ]
    return corners, [index for face in faces for index in face]


def _channel_samples(bone, track, channel: str):
    """Bake one channel at its own key frames.

    Each channel composes against a constant part of the bind pose — rotation against
    `q_bind`, translation against `t_bind` and `q_bind`, scale against `scale_bind` — so
    baking them on separate frame sets is exact. Doing it per channel rather than on the
    union of all three keeps rotation-only bones, which are most of them, from carrying
    two channels of repeated values.
    """

    keys = getattr(track, channel)
    if not keys:
        return []
    bind = bind_transform(bone)
    out: list[tuple[float, object]] = []
    for frame, _values in keys:
        delta = sample_delta_channel(track, channel, float(frame))
        out.append((frame / FPS, getattr(compose(bind, delta), channel)))
    return out


def build_gltf(skeleton, clip: MotionClip, *, name: str = "motion", show_joints: bool = True) -> tuple[dict, bytes]:
    """Build the glTF JSON and its binary chunk for one clip on one skeleton."""

    buffers = _BufferBuilder()
    nodes: list[dict] = []
    for bone in skeleton.bones:
        bind = bind_transform(bone)
        node: dict = {
            "name": bone.name,
            "translation": list(bind.translation),
            "rotation": list(bind.rotation),
            "scale": list(bind.scale),
        }
        nodes.append(node)
    for index, bone in enumerate(skeleton.bones):
        if 0 <= bone.parent_index < len(nodes) and bone.parent_index != index:
            nodes[bone.parent_index].setdefault("children", []).append(index)

    gltf: dict = {
        "asset": {"version": "2.0", "generator": "cdmw paa_motion"},
        "scene": 0,
        "scenes": [{"nodes": [i for i, b in enumerate(skeleton.bones) if b.parent_index < 0]}],
        "nodes": nodes,
    }

    if show_joints:
        corners, triangles = _cube(_JOINT_CUBE_RADIUS)
        mesh = {
            "primitives": [{
                "attributes": {"POSITION": buffers.positions(corners)},
                "indices": buffers.indices(triangles),
            }]
        }
        gltf["meshes"] = [mesh]
        animated = {track.name_hash for track in clip.tracks if track.animated}
        for index, bone in enumerate(skeleton.bones):
            if bone.name_hash in animated:
                nodes[index]["mesh"] = 0

    samplers: list[dict] = []
    channels: list[dict] = []
    tracks = {track.name_hash: track for track in clip.tracks}
    for index, bone in enumerate(skeleton.bones):
        track = tracks.get(bone.name_hash)
        if track is None or not track.animated:
            continue
        times_cache: dict[tuple, int] = {}
        for channel, kind in (("translation", "VEC3"), ("rotation", "VEC4"), ("scale", "VEC3")):
            samples = _channel_samples(bone, track, channel)
            if not samples:
                continue
            times = tuple(time for time, _value in samples)
            if times not in times_cache:
                times_cache[times] = buffers.scalars(list(times))
            samplers.append({
                "input": times_cache[times],
                "output": buffers.vectors([list(value) for _t, value in samples], kind),
                "interpolation": "LINEAR",
            })
            channels.append({
                "sampler": len(samplers) - 1,
                "target": {"node": index, "path": channel},
            })

    if channels:
        gltf["animations"] = [{"name": name, "samplers": samplers, "channels": channels}]
    gltf["accessors"] = buffers.accessors
    gltf["bufferViews"] = buffers.views
    gltf["buffers"] = [{"byteLength": len(buffers.blob)}]
    return gltf, bytes(buffers.blob)


def write_glb(path, skeleton, clip: MotionClip, *, name: str = "motion", show_joints: bool = True) -> int:
    """Write a self-contained `.glb`. Returns the byte count."""

    gltf, blob = build_gltf(skeleton, clip, name=name, show_joints=show_joints)
    payload = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    binary = blob + b"\x00" * (-len(blob) % 4)
    total = 12 + 8 + len(payload) + (8 + len(binary) if binary else 0)
    with open(path, "wb") as handle:
        handle.write(struct.pack("<4sII", b"glTF", 2, total))
        handle.write(struct.pack("<II", len(payload), 0x4E4F534A))
        handle.write(payload)
        if binary:
            handle.write(struct.pack("<II", len(binary), 0x004E4942))
            handle.write(binary)
    return total
