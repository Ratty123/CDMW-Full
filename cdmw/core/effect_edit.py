"""Edit a shipped effect's look, in place, and give it a stem of its own.

An effect binary and the emitters it instances are self-describing graphs
(:mod:`cdmw.core.effect_binary`), and every inline value knows its offset. This
module applies a "look" (the studio's :class:`~cdmw.domain.new_item.spec.EffectLook`,
or anything with the same five attributes) to those values without moving a byte:

* colour: `EmitterRenderData._emissiveColor` and `_color` (float3) become the chosen
  colour scaled to the old colour's peak component, so a dim ember stays dim and a
  bright flame stays bright, only the hue changes; the light an emitter precomputes
  (`_precomputeEmissiveLightLinearColor`) follows. A fire's colour, though, is mostly
  not a colour member: it is the baked colour-over-life curve (`EmitterCurveData`
  with `_splineID` 21: 128 samples of RGB + temperature, half floats) and the material's
  temperature ramp (`_temperatureColorSpline`, four splines R, G, B, intensity over
  normalised temperature); the game's own blue fire differs from the orange one in
  exactly those two places. Both are recoloured too: every sample and every ramp point
  keeps its brightness (the peak channel) and takes the chosen hue, the temperature
  channel is left alone. An effect overrides an emitter's curves and material
  parameters by position (an override record carries no `_splineID` or `_name`), so
  a caller that has the emitter files passes their :class:`EmitterLayout` and the
  positional overrides are recoloured as well;
* intensity: `_emissiveBrightness` and `_brightness` (float3) are multiplied;
* size: `EmitterSimulationData._scaleMin/_scaleMax` and `EmitterData._particleScaleMax`
  (float3) are multiplied, and the effect's bounding boxes with them;
* rate: `EmitterSpawnData._spawnCountMin/_spawnCountMax/_maxParticleCount` (uint)
  are multiplied and rounded (at least 1);
* lifetime: `_lifeTimeMin/_lifeTimeMax` (float) are multiplied.

An emitter's colour is the render preset's unless `EmitterRenderData._overridePresetColor`
says otherwise (the fire ember carries `_emissiveColor` (0.37, 0.05, 0.005) and the flag
false, and draws the preset `fx_fire_uber_ember_01`'s look), so a colour edit also sets
that flag wherever it is present, and the presets an effect or emitter names
(`_renderGroupPreset` -> `effect/binary__/renderpreset/<name>.parg`,
`_simulationGroupPreset` -> `effect/binary__/simulationpreset/<name>.pasg`, the same
container) are cloned and edited alongside; :func:`preset_names_of` lists them and
:func:`rename_string_values` points a clone at them.

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

from cdmw.core.effect_binary import EffectDocument, ReflectNode, ReflectValue, decode_effect_binary, half_floats, write_value

__all__ = [
    "COLOR_CURVE_ID",
    "EMITTER_DIR",
    "RENDER_PRESET_DIR",
    "SIMULATION_PRESET_DIR",
    "TEMPERATURE_RAMP",
    "EffectEditError",
    "EffectEditReport",
    "EmitterLayout",
    "apply_effect_look",
    "emitter_layout_of",
    "emitter_paths_of",
    "preset_names_of",
    "preset_path",
    "rename_effect_strings",
    "rename_string_values",
    "same_length_stem",
]

EMITTER_DIR = "effect/binary__/emitter/"
RENDER_PRESET_DIR = "effect/binary__/renderpreset/"
SIMULATION_PRESET_DIR = "effect/binary__/simulationpreset/"
Vec3 = Tuple[float, float, float]

#: `EmitterCurveData._splineID` of the colour-over-life curve: 128 samples of
#: (R, G, B, temperature) as half floats. The only four-component curve id shipped.
COLOR_CURVE_ID = 21
#: The material parameter that maps normalised temperature to (R, G, B, intensity).
TEMPERATURE_RAMP = "_temperatureColorSpline"
COLOR_MEMBERS = ("_emissiveColor", "_color", "_precomputeEmissiveLightLinearColor")
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


@dataclass(frozen=True, slots=True)
class EmitterLayout:
    """What an emitter file keeps at each position: the `_splineID` of every
    `_curveEntryDataList` entry and the `_name` of every material parameter. An effect's
    embedded override of that emitter names neither, only positions."""

    curve_ids: Tuple[Optional[int], ...] = ()
    parameter_names: Tuple[Optional[str], ...] = ()


def emitter_layout_of(document: EffectDocument) -> EmitterLayout:
    """The :class:`EmitterLayout` of an emitter file's document (root `EmitterData`)."""

    return _layout_of_node(document.root)


def _layout_of_node(node: ReflectNode) -> EmitterLayout:
    curves = node.child("_curveEntryDataList")
    curve_ids: List[Optional[int]] = []
    for entry in curves if isinstance(curves, tuple) else ():
        sid = entry.value("_splineID")
        curve_ids.append(int(sid.value) if sid is not None and isinstance(sid.value, int) else None)
    names: List[Optional[str]] = []
    material = node.child("_effectMaterialData2")
    parameters = material.child("_parameters") if isinstance(material, ReflectNode) else None
    for parameter in parameters if isinstance(parameters, tuple) else ():
        name = parameter.value("_name")
        names.append(str(name.value) if name is not None and name.kind == 1 else None)
    return EmitterLayout(tuple(curve_ids), tuple(names))


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


def preset_names_of(document: EffectDocument) -> Tuple[Tuple[str, str], ...]:
    """(kind, name) for every render (`_renderGroupPreset`) and simulation
    (`_simulationGroupPreset`) preset the graph names, in order, deduplicated."""

    out: List[Tuple[str, str]] = []
    for value in document.root.all_values():
        if value.kind != 1:
            continue
        kind = {"_renderGroupPreset": "render", "_simulationGroupPreset": "simulation"}.get(value.name)
        if kind is None:
            continue
        name = str(value.value)
        if name and (kind, name) not in out:
            out.append((kind, name))
    return tuple(out)


def preset_path(kind: str, name: str) -> str:
    """The archive path of a render or simulation preset by kind and name."""

    folder = RENDER_PRESET_DIR if kind == "render" else SIMULATION_PRESET_DIR
    suffix = ".parg" if kind == "render" else ".pasg"
    return "".join((folder, name, suffix))


def rename_string_values(data: bytes, renames: Mapping[str, str]) -> bytes:
    """Replace whole string values (`_renderGroupPreset` and the like) that equal a
    key of `renames` with its same-length value, in place."""

    for old, new in renames.items():
        if len(old.encode("utf-8")) != len(new.encode("utf-8")):
            raise EffectEditError(f"{old} -> {new}: a rename must keep the length")
    document = decode_effect_binary(data)
    if not document.walk_complete:
        raise EffectEditError(f"the file did not decode fully ({document.walk_note}); its strings are not renamed")
    out = bytes(data)
    for value in list(document.root.all_values()):
        if value.kind != 1:
            continue
        text = str(value.value)
        if text in renames:
            out = write_value(out, value, renames[text].encode("utf-8"))
    return out


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


def apply_effect_look(
    data: bytes,
    look: "LookLike",
    *,
    report: Optional[EffectEditReport] = None,
    emitter_layouts: Optional[Mapping[str, EmitterLayout]] = None,
) -> Tuple[bytes, EffectEditReport]:
    """Return `data` (a `.pae` or `.paem`) with the look applied in place.

    `look` carries `color` (an RGB triple or None), `intensity`, `size`, `rate` and
    `lifetime` (factors, 1.0 for as shipped). Values the file does not carry are not
    added: an override that leaves a colour to its base emitter is edited in the base
    emitter's clone, not here. `emitter_layouts` maps an emitter's archive path
    (`effect/binary__/emitter/<stem>.paem`) to its :class:`EmitterLayout`, so an effect's
    positional overrides of that emitter's colour curve and temperature ramp are found.
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
    if look.color is not None:
        out = _recolor_curves_and_ramps(out, document, look.color, report, emitter_layouts or {})
    return out, report


def _recolor_curves_and_ramps(out: bytes, document: EffectDocument, color: Vec3, report: EffectEditReport, layouts: Mapping[str, EmitterLayout]) -> bytes:
    """Recolour every colour-over-life curve and temperature ramp the graph carries:
    an emitter file's own (ids and names present) and an effect's embedded overrides
    (by position, through `layouts`)."""

    for node in document.root.walk():
        if node.type_name == "EmitterData":
            layout = _layout_of_node(node)
        elif node.type_name.endswith(".paem"):
            layout = layouts.get(node.type_name.lstrip("/")) or layouts.get(node.type_name) or EmitterLayout()
        else:
            continue
        curves = node.child("_curveEntryDataList")
        for index, entry in enumerate(curves if isinstance(curves, tuple) else ()):
            sid = entry.value("_splineID")
            curve_id = int(sid.value) if sid is not None and isinstance(sid.value, int) else (layout.curve_ids[index] if index < len(layout.curve_ids) else None)
            if curve_id != COLOR_CURVE_ID:
                continue
            samples = entry.value("_splineData")
            if samples is None or samples.kind != 3 or samples.size < 8 or samples.size % 8:
                continue
            out = write_value(out, samples, _recolored_curve(samples.raw, color))
            report.count("_splineData:color")
        material = node.child("_effectMaterialData2")
        parameters = material.child("_parameters") if isinstance(material, ReflectNode) else None
        for index, parameter in enumerate(parameters if isinstance(parameters, tuple) else ()):
            name = parameter.value("_name")
            parameter_name = str(name.value) if name is not None and name.kind == 1 else (layout.parameter_names[index] if index < len(layout.parameter_names) else None)
            if parameter_name != TEMPERATURE_RAMP:
                continue
            out = _recolor_ramp(out, parameter, color, report)
    return out


def _normalized_color(color: Vec3) -> Vec3:
    chosen = tuple(max(0.0, float(v)) for v in color)
    top = max(chosen) or 1.0
    return (chosen[0] / top, chosen[1] / top, chosen[2] / top)


def _recolored_curve(raw: bytes, color: Vec3) -> bytes:
    """The colour-over-life curve with every sample's RGB in the chosen hue at the
    sample's own peak; the fourth channel (temperature) is kept."""

    samples = list(half_floats(raw))
    hue = _normalized_color(color)
    for start in range(0, len(samples) - 3, 4):
        r, g, b = samples[start:start + 3]
        peak = max(r, g, b, 0.0)
        samples[start:start + 3] = [channel * peak for channel in hue]
    return struct.pack(f"<{len(samples)}e", *samples)


def _recolor_ramp(out: bytes, parameter: ReflectNode, color: Vec3, report: EffectEditReport) -> bytes:
    """Recolour a `_temperatureColorSpline` parameter's R, G and B splines in place: each
    point takes the chosen hue at the ramp's peak value at that point's x (the three
    splines evaluated piecewise-linearly), tangents scale with the point. A point whose
    position the file leaves at its default (no bytes) stays; only the intensity spline
    (the fourth) is untouched."""

    reference = parameter.child("_value")
    instance = reference.child("_splineDataInstance") if isinstance(reference, ReflectNode) else None
    components = instance.child("_dataForSerialize") if isinstance(instance, ReflectNode) else None
    if not isinstance(components, tuple) or len(components) < 3:
        return out
    curves: List[List[Tuple[float, float, ReflectNode]]] = []
    for component in components[:3]:
        points = component.child("_pointListForSerialize")
        curve: List[Tuple[float, float, ReflectNode]] = []
        for point in points if isinstance(points, tuple) else ():
            position = point.value("_position")
            x, y = struct.unpack("<2f", position.raw) if position is not None and position.size == 8 else (0.0, 0.0)
            curve.append((x, y, point))
        curves.append(sorted(curve, key=lambda item: item[0]))
    hue = _normalized_color(color)
    for channel, curve in enumerate(curves):
        for x, y, point in curve:
            position = point.value("_position")
            if position is None or position.size != 8:
                continue
            peak = max(_evaluate(other, x) for other in curves)
            new_y = hue[channel] * peak
            out = write_value(out, position, struct.pack("<2f", x, new_y))
            ratio = new_y / y if abs(y) > 1e-6 else 0.0
            for tangent_name in ("_innerTangent", "_outterTangent"):
                tangent = point.value(tangent_name)
                if tangent is not None and tangent.size == 4:
                    out = write_value(out, tangent, struct.pack("<f", struct.unpack("<f", tangent.raw)[0] * ratio))
            report.count(TEMPERATURE_RAMP)
    return out


def _evaluate(curve: List[Tuple[float, float, ReflectNode]], x: float) -> float:
    """A spline read as its points joined by straight lines, clamped at the ends."""

    if not curve:
        return 0.0
    if x <= curve[0][0]:
        return curve[0][1]
    for (x0, y0, _a), (x1, y1, _b) in zip(curve, curve[1:]):
        if x <= x1:
            span = x1 - x0
            return y0 if span <= 1e-9 else y0 + (y1 - y0) * (x - x0) / span
    return curve[-1][1]


def _is_default(look: "LookLike") -> bool:
    color = getattr(look, "color", None)
    return color is None and all(abs(float(getattr(look, name, 1.0)) - 1.0) < 1e-9 for name in ("intensity", "size", "rate", "lifetime"))


def _replacement_for(value: ReflectValue, look: "LookLike") -> Optional[bytes]:
    name = value.name
    if look.color is not None and name in COLOR_MEMBERS and value.type_name == "float3" and value.size == 12:
        return _scaled_color(value.raw, look.color)
    if look.color is not None and name == "_overridePresetColor" and value.type_name == "bool" and value.size == 1:
        return bytes([1])
    if abs(look.intensity - 1.0) > 1e-9 and name in BRIGHTNESS_MEMBERS and value.type_name == "float3" and value.size == 12:
        return _multiplied_float3(value.raw, look.intensity)
    if abs(look.size - 1.0) > 1e-9 and value.type_name == "float3" and value.size == 12 and (name in SIZE_MEMBERS or name in BOX_MEMBERS):
        return _multiplied_float3(value.raw, look.size)
    if abs(look.rate - 1.0) > 1e-9 and name in RATE_MEMBERS and value.type_name in ("uint", "uint32") and value.size == 4:
        return _multiplied_uint(value.raw, look.rate)
    if abs(look.lifetime - 1.0) > 1e-9 and name in LIFETIME_MEMBERS and value.type_name == "float" and value.size == 4:
        return _multiplied_float(value.raw, look.lifetime)
    return None
