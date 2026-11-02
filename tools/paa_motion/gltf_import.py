"""Read an animation back from a `.glb` or `.gltf`, as a `.paa` clip.

The other half of `gltf.py`. That module writes the skeleton as a node hierarchy named
after the bones, with each node's bind transform and the clip's animated local transforms;
an animator opens it in Blender, changes the motion, and exports glTF again. This reads
that file and turns each animated node back into a track:

    delta = decompose(bind, local)      the inverse of pose.compose

Nodes are matched to bones by name, so Blender's own additions -- an armature object, a
renamed duplicate such as `Bip01 L Hand.001` -- are tolerated; a node that matches no bone
is reported, never guessed at. Samples land on the 30 Hz frame grid the game plays.

The new clip takes everything the file format needs but glTF does not carry (flags, tag,
unit scale, skeleton path, the bounds frames) from a template clip: the one the motion
was exported from. A bone the file does not animate keeps the template's track.
"""

from __future__ import annotations

import json
import re
import struct
from bisect import bisect_left, bisect_right
from urllib.parse import unquote
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .edit import _rebuild, decompose
from .format import FLAG_PACKED, FPS, BoneTrack, MotionClip
from .pose import Transform, bind_transform, quat_normalize, quat_slerp

_COMPONENT = {5120: ("b", 127.0), 5121: ("B", 255.0), 5122: ("h", 32767.0),
              5123: ("H", 65535.0), 5125: ("I", None), 5126: ("f", None)}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


class GltfImportError(ValueError):
    """Raised when a file holds no animation this module can read onto the skeleton."""


@dataclass(frozen=True)
class ImportReport:
    clip: MotionClip
    matched: Tuple[str, ...]
    unmatched: Tuple[str, ...]
    seconds: float
    animation: str


def _load(path: Path) -> Tuple[dict, bytes]:
    data = path.read_bytes()
    if data[:4] == b"glTF":
        _magic, _version, length = struct.unpack_from("<4sII", data, 0)
        offset, document, blob = 12, None, b""
        while offset < min(length, len(data)):
            size, kind = struct.unpack_from("<II", data, offset)
            chunk = data[offset + 8: offset + 8 + size]
            if kind == 0x4E4F534A:
                document = json.loads(chunk.decode("utf-8"))
            elif kind == 0x004E4942:
                blob = chunk
            offset += 8 + size
        if document is None:
            raise GltfImportError("The .glb has no JSON chunk")
        return document, blob
    document = json.loads(data.decode("utf-8"))
    buffers = document.get("buffers") or []
    blob = b""
    if buffers:
        uri = buffers[0].get("uri", "")
        if uri.startswith("data:"):
            import base64

            blob = base64.b64decode(uri.split(",", 1)[1])
        elif uri:
            # Exporters percent-encode buffer names: `my%20walk.bin`.
            external = (path.parent / unquote(uri)).resolve()
            if path.parent.resolve() not in external.parents:
                raise GltfImportError("The .gltf points at a buffer outside its own folder")
            blob = external.read_bytes()
    return document, blob


def _accessor(document: dict, blob: bytes, index: int) -> List[Tuple[float, ...]]:
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    fmt, norm = _COMPONENT[accessor["componentType"]]
    width = _WIDTH[accessor["type"]]
    size = struct.calcsize("<" + fmt)
    stride = view.get("byteStride") or size * width
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    rows = []
    for row in range(accessor["count"]):
        values = struct.unpack_from("<" + fmt * width, blob, start + row * stride)
        if norm:
            # Integer outputs are only valid normalized (glTF 2.0, animation samplers).
            values = tuple(max(-1.0, v / norm) for v in values)
        rows.append(tuple(float(v) for v in values))
    return rows


#: Key times are float32 in the file; a key meant for frame 12 can land a hair either side.
_TIME_EPSILON = 1e-4


def _sample(times: Sequence[float], values: Sequence[Tuple[float, ...]], at: float,
            rotation: bool, step: bool) -> Tuple[float, ...]:
    if at <= times[0]:
        return values[0]
    if at >= times[-1]:
        return values[-1]
    if step:
        # The key at or just before `at`, with float32 times allowed to fall a hair late.
        return values[max(0, bisect_right(times, at + _TIME_EPSILON) - 1)]
    index = min(max(1, bisect_left(times, at)), len(times) - 1)
    left, right = times[index - 1], times[index]
    t = (at - left) / (right - left) if right > left else 0.0
    a, b = values[index - 1], values[index]
    if rotation:
        return quat_slerp(quat_normalize(a), quat_normalize(b), t)
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _bone_for(node_name: str, by_name: Dict[str, object]):
    if node_name in by_name:
        return by_name[node_name]
    trimmed = re.sub(r"\.\d{3}$", "", node_name)
    return by_name.get(trimmed) or by_name.get(trimmed.replace("_", " "))


def import_animation(path, skeleton, template: MotionClip, *, animation: int = 0,
                     should_stop=None) -> ImportReport:
    """Read one animation from `path` as a clip shaped like `template`."""

    def check() -> None:
        if should_stop is not None and should_stop():
            raise GltfImportError("The import was cancelled")

    if template.flags & FLAG_PACKED:
        raise GltfImportError("Use a full animation as the template, not a distance (LOD) copy")
    document, blob = _load(Path(path))
    animations = document.get("animations") or []
    if not animations:
        raise GltfImportError("The file has no animation in it")
    if not 0 <= animation < len(animations):
        raise GltfImportError(f"The file has {len(animations)} animation(s)")
    chosen = animations[animation]
    nodes = document.get("nodes") or []
    by_name = {bone.name: bone for bone in skeleton.bones}

    channels: Dict[int, Dict[str, Tuple[List[float], List[Tuple[float, ...]], bool]]] = {}
    end = 0.0
    for channel in chosen.get("channels", []):
        target = channel.get("target", {})
        node, path_name = target.get("node"), target.get("path")
        if node is None or path_name not in {"translation", "rotation", "scale"}:
            continue
        sampler = chosen["samplers"][channel["sampler"]]
        times = [row[0] for row in _accessor(document, blob, sampler["input"])]
        values = _accessor(document, blob, sampler["output"])
        interpolation = sampler.get("interpolation", "LINEAR")
        if interpolation == "CUBICSPLINE":
            values = values[1::3]  # in-tangent, value, out-tangent per key
        if not times or len(values) != len(times):
            continue
        channels.setdefault(node, {})[path_name] = (times, values, interpolation == "STEP")
        end = max(end, times[-1])

    matched: List[str] = []
    unmatched: List[str] = []
    bones_animated = {}
    for node, data in channels.items():
        name = nodes[node].get("name", f"node {node}") if node < len(nodes) else f"node {node}"
        bone = _bone_for(name, by_name)
        if bone is None:
            unmatched.append(name)
            continue
        matched.append(bone.name)
        bones_animated[bone.name_hash] = (bone, data)
    if not bones_animated:
        raise GltfImportError(
            "No animated node in the file matches a bone of this character. Export from the "
            "file Placement & Animations wrote, and keep the bone names."
        )

    last = max(1, int(round(end * FPS)))
    template_tracks = {t.name_hash: t for t in template.tracks}
    tracks: List[BoneTrack] = []
    for track in template.tracks:
        check()
        if track.name_hash in bones_animated:
            bone, data = bones_animated.pop(track.name_hash)
            tracks.append(_track(bone, data, last, track))
        else:
            tracks.append(_stretch(track, last, template))
    skeletal = [t for t in tracks if not t.root_motion]
    root = [t for t in tracks if t.root_motion]
    for name_hash, (bone, data) in sorted(bones_animated.items(), key=lambda kv: kv[1][0].index):
        skeletal.append(_track(bone, data, last, BoneTrack(name_hash)))
    del template_tracks

    clip = replace(
        template,
        duration=last / FPS,
        tracks=tuple(skeletal + root),
        skeletal_bone_count=len(skeletal),
        root_bone_count=len(root),
        key_bytes=0,
        passthrough=replace(template.passthrough, trailing=b""),
    )
    return ImportReport(clip, tuple(sorted(matched)), tuple(sorted(unmatched)), last / FPS,
                        str(chosen.get("name", "")))


def _track(bone, data, last: int, template: BoneTrack) -> BoneTrack:
    bind = bind_transform(bone)
    series: List[Transform] = []
    for frame in range(last + 1):
        at = frame / FPS
        parts = {}
        for name, default in (("translation", bind.translation), ("rotation", bind.rotation),
                              ("scale", bind.scale)):
            if name in data:
                times, values, step = data[name]
                parts[name] = _sample(times, values, at, name == "rotation", step)
            else:
                parts[name] = default
        local = Transform(translation=tuple(parts["translation"])[:3],  # type: ignore[arg-type]
                          rotation=quat_normalize(tuple(parts["rotation"])[:4]),  # type: ignore[arg-type]
                          scale=tuple(parts["scale"])[:3])  # type: ignore[arg-type]
        series.append(decompose(bind, local))
    return _rebuild(template, series)


def _stretch(track: BoneTrack, last: int, template: MotionClip) -> BoneTrack:
    """A bone the file left alone keeps its template keys, cut to the new length."""

    if not track.animated or last >= template.last_frame:
        return track
    from .pose import sample_delta_channel

    keep = {}
    for channel in ("scale", "rotation", "translation"):
        keys = getattr(track, channel)
        kept = tuple(k for k in keys if k[0] <= last) or keys[:1]
        if keys and kept[-1][0] < last and keys[-1][0] > last:
            # End on where the motion is at the new last frame, not on an earlier key.
            value = getattr(sample_delta_channel(track, channel, float(last)), channel)
            kept += ((last, tuple(float(v) for v in value)),)
        keep[channel] = kept
    return replace(track, **keep)


__all__ = ["GltfImportError", "ImportReport", "import_animation"]
