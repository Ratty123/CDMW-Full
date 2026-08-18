"""Edit a shipped effect's look, in place, and give it a stem of its own.

An effect binary and the emitters it instances are self-describing graphs
(:mod:`cdmw.core.effect_binary`), and every inline value knows its offset. This
module applies a "look" (the studio's :class:`~cdmw.domain.new_item.spec.EffectLook`,
or anything with the same five attributes) to those values without moving a byte:

* colour: `EmitterRenderData._emissiveColor` and `_color` (float3) become the chosen
  colour scaled to the old colour's peak component, so a dim ember stays dim and a
  bright flame stays bright, only the hue changes;
* intensity: `_emissiveBrightness` and `_brightness` (float3) are multiplied;
* size: `EmitterSimulationData._scaleMin/_scaleMax` and `EmitterData._particleScaleMax`
  (float3) are multiplied, and the effect's bounding boxes with them;
* rate: `EmitterSpawnData._spawnCountMin/_spawnCountMax/_maxParticleCount` (uint)
  are multiplied and rounded (at least 1);
* lifetime: `_lifeTimeMin/_lifeTimeMax` (float) are multiplied.

Renaming keeps every string the same length: a cloned effect and its cloned emitters
take stems of the same length as the shipped ones, so the type table, the string pool
and every self pointer stay where they are and the file needs no relocation. The
effect names its emitters twice: as type names in the header (the emitter file's path)
and as `_emitterDataName` values in the blob (`emitter/<stem>`); both are replaced.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Protocol, Tuple

from cdmw.core.effect_binary import EffectDocument, ReflectValue, decode_effect_binary, write_value

__all__ = [
    "EMITTER_DIR",
    "EffectEditError",
    "EffectEditReport",
    "apply_effect_look",
    "emitter_paths_of",
    "rename_effect_strings",
    "same_length_stem",
]

EMITTER_DIR = "effect/binary__/emitter/"
Vec3 = Tuple[float, float, float]

COLOR_MEMBERS = ("_emissiveColor", "_color")
BRIGHTNESS_MEMBERS = ("_emissiveBrightness", "_brightness")
SIZE_MEMBERS = ("_scaleMin", "_scaleMax", "_particleScaleMax")
BOX_MEMBERS = ("_boundingBoxMin", "_boundingBoxMax", "_emitterBoundBoxMin", "_emitterBoundBoxMax", "_emitterBoundingBoxMin", "_emitterBoundingBoxMax")
RATE_MEMBERS = ("_spawnCountMin", "_spawnCountMax", "_maxParticleCount")
LIFETIME_MEMBERS = ("_lifeTimeMin", "_lifeTimeMax")


class LookLike(Protocol):
    color: Optional[Vec3]
    intensity: float
    size: float
    rate: float
    lifetime: float


class EffectEditError(ValueError):
    """Raised when an effect cannot be edited as asked."""


@dataclass(slots=True)
class EffectEditReport:
    """What an edit pass touched, per member name."""

    edited: Dict[str, int] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def count(self, name: str) -> None:
        self.edited[name] = self.edited.get(name, 0) + 1

    @property
    def total(self) -> int:
        return sum(self.edited.values())


def same_length_stem(stem: str, tag: str, *, taken: Iterable[str] = ()) -> str:
    """A stem of `stem`'s length ending in `tag` (`_n90012`), unique against `taken`.

    The tail is what a clone shares with nothing shipped; the head keeps enough of the
    original to say what it was. A stem shorter than the tag plus two is hashed instead.
    """

    taken_set = {str(item) for item in taken}
    tag = str(tag)
    length = len(stem)
    if length <= len(tag) + 1:
        digest = hashlib.sha1(f"{stem}:{tag}".encode("utf-8")).hexdigest()
        candidate = (digest[:length] if length else digest[:8])
    else:
        candidate = stem[: length - len(tag)] + tag
    if candidate not in taken_set and candidate != stem:
        return candidate
    for bump in range(1, 1000):
        suffix = f"{tag}{bump:x}"
        if length <= len(suffix) + 1:
            candidate = hashlib.sha1(f"{stem}:{suffix}".encode("utf-8")).hexdigest()[: max(1, length)]
        else:
            candidate = stem[: length - len(suffix)] + suffix
        if candidate not in taken_set and candidate != stem:
            return candidate
    raise EffectEditError(f"no free stem of length {length} for {stem}")


def emitter_paths_of(document: EffectDocument) -> Tuple[str, ...]:
    """The emitter files an effect names, as archive paths, in order."""

    return tuple(f"{EMITTER_DIR}{name.split('/', 1)[-1]}.paem" for name in document.emitter_names())


def rename_effect_strings(data: bytes, renames: Mapping[str, str]) -> bytes:
    """Replace shipped emitter and effect stems with the clones' stems, same length.

    Every occurrence of `emitter/<old>` (an `_emitterDataName`), of
    `effect/binary__/emitter/<old>` (the type name an effect embeds an emitter under)
    and of `fx/materialfx/<old>` or `effect/binary__/releasebin/<old>` (an effect's own
    name) becomes the new stem. The prefixes keep a stem from matching inside another
    string, and the length is checked, so nothing moves.
    """

    out = bytes(data)
    for old, new in renames.items():
        if len(old) != len(new):
            raise EffectEditError(f"{old} -> {new}: a rename must keep the length ({len(old)} vs {len(new)})")
        old_b, new_b = old.encode("utf-8"), new.encode("utf-8")
        for prefix in (b"emitter/", b"/effect/binary__/emitter/", b"effect/binary__/emitter/", b"fx/materialfx/", b"effect/binary__/releasebin/"):
            out = out.replace(prefix + old_b, prefix + new_b)
    return out


def _scaled_color(raw: bytes, color: Vec3) -> bytes:
    values = struct.unpack("<3f", raw)
    peak = max(values)
    if peak <= 0.0:
        peak = 1.0
    chosen = tuple(max(0.0, float(v)) for v in color)
    top = max(chosen) or 1.0
    scaled = tuple(v / top * peak for v in chosen)
    return struct.pack("<3f", *scaled)


def _multiplied_float3(raw: bytes, factor: float) -> bytes:
    values = struct.unpack("<3f", raw)
    return struct.pack("<3f", *(v * factor for v in values))


def _multiplied_float(raw: bytes, factor: float) -> bytes:
    return struct.pack("<f", struct.unpack("<f", raw)[0] * factor)


def _multiplied_uint(raw: bytes, factor: float) -> bytes:
    value = struct.unpack("<I", raw)[0]
    return struct.pack("<I", max(1, min(0xFFFFFFFF, int(round(value * factor)))))


def apply_effect_look(data: bytes, look: "LookLike", *, report: Optional[EffectEditReport] = None) -> Tuple[bytes, EffectEditReport]:
    """Return `data` (a `.pae` or `.paem`) with the look applied in place.

    `look` carries `color` (an RGB triple or None), `intensity`, `size`, `rate` and
    `lifetime` (factors, 1.0 for as shipped). Values the file does not carry are not
    added: an override that leaves a colour to its base emitter is edited in the base
    emitter's clone, not here.
    """

    report = report if report is not None else EffectEditReport()
    if _is_default(look):
        return bytes(data), report
    document = decode_effect_binary(data)
    if not document.walk_complete:
        raise EffectEditError(f"the effect did not decode fully ({document.walk_note}); it is not edited")
    out = bytes(data)
    for value in list(document.root.all_values()):
        replacement = _replacement_for(value, look)
        if replacement is None:
            continue
        out = write_value(out, value, replacement)
        report.count(value.name)
    return out, report


def _is_default(look: "LookLike") -> bool:
    color = getattr(look, "color", None)
    return color is None and all(abs(float(getattr(look, name, 1.0)) - 1.0) < 1e-9 for name in ("intensity", "size", "rate", "lifetime"))


def _replacement_for(value: ReflectValue, look: "LookLike") -> Optional[bytes]:
    name = value.name
    if look.color is not None and name in COLOR_MEMBERS and value.type_name == "float3" and value.size == 12:
        return _scaled_color(value.raw, look.color)
    if abs(look.intensity - 1.0) > 1e-9 and name in BRIGHTNESS_MEMBERS and value.type_name == "float3" and value.size == 12:
        return _multiplied_float3(value.raw, look.intensity)
    if abs(look.size - 1.0) > 1e-9 and value.type_name == "float3" and value.size == 12 and (name in SIZE_MEMBERS or name in BOX_MEMBERS):
        return _multiplied_float3(value.raw, look.size)
    if abs(look.rate - 1.0) > 1e-9 and name in RATE_MEMBERS and value.type_name in ("uint", "uint32") and value.size == 4:
        return _multiplied_uint(value.raw, look.rate)
    if abs(look.lifetime - 1.0) > 1e-9 and name in LIFETIME_MEMBERS and value.type_name == "float" and value.size == 4:
        return _multiplied_float(value.raw, look.lifetime)
    return None
