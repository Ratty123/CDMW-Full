"""An approximate, honest simulation description of a shipped effect for the resident viewport.

The game simulates its particles on the GPU with vector fields, presets and post effects
of its own; none of that is reproduced. What this module reads out of a decoded effect
(:mod:`cdmw.core.effect_binary`) is enough for "fire that looks like that fire, roughly
where it will be": per emitter, how many particles spawn how often and for how long, where
they spawn (a point spread, or points sampled on the effect's spawn mesh), the force
that moves them, damping and speed limit, their size and its curve over life, their
colour over life (the colour curve the game reads, id 21, and the temperature ramp are
what a look edit changes, so an edited effect previews edited), an alpha curve, the
sprite texture (an archive path; the package copies the DDS next to the mesh) and the
blend mode, plus the beam width and colour for the lightning-style emitters. Read on the
already-edited bytes (:func:`cdmw.core.effect_edit.apply_effect_look`) so the preview
follows the look.

Values come from three places in this order: the effect's embedded override of the
emitter (an effect changes what its emitter does, by position for the entries the
override leaves unnamed), the emitter file itself, and the render preset the embedded
emitter names (a blue look edited only the effect's and the emitter's ramps and drew
blue in game, so the preset's material does not win over theirs; its emissive colour
does unless `_overridePresetColor` is set). Curve ids other than 21 have no
name the exe exposes; the ones used here are read by shape: id 2 (one component, rising
then falling) as alpha over life, id 5 (three components, growing from a fraction) as
scale over life. That is a reading, not a fact, and the field docstrings say so.
"""

from __future__ import annotations

import json
import math
import random
import struct
from dataclasses import asdict, dataclass
from typing import Callable, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

from cdmw.core.effect_binary import EffectDocument, ReflectNode, half_floats
from cdmw.core.effect_edit import COLOR_CURVE_ID, TEMPERATURE_BRIGHTNESS, TEMPERATURE_RAMP, EmitterLayout, LookLike, emitter_paths_of

__all__ = [
    "ALPHA_CURVE_ID",
    "SCALE_CURVE_ID",
    "EmitterPreview",
    "EffectPreview",
    "build_effect_preview",
    "curve_samples",
    "effect_preview_json",
    "preview_effect_from_snapshot",
]

Vec3 = Tuple[float, float, float]
#: One-component curve that rises from 0 and falls back: read as alpha over life.
ALPHA_CURVE_ID = 2
#: Three-component curve around 1: read as scale over life.
SCALE_CURVE_ID = 5
CURVE_SAMPLES = 16
SURFACE_POINTS = 96


@dataclass(frozen=True, slots=True)
class EmitterPreview:
    """One emitter, reduced to what a CPU billboard/beam simulation needs."""

    name: str
    #: "billboard" (a sprite quad), "beam" (a jittered polyline), "mesh" (a mesh particle)
    kind: str
    #: archive path of the sprite (or beam) texture, "" for none
    texture: str
    #: "additive" or "alpha"
    blend: str
    #: particles spawned per burst and bursts per second (spawnCount / spawnTerm)
    burst: int
    bursts_per_second: float
    max_particles: int
    life: Tuple[float, float]
    loop: bool
    #: "points" (spawn at the sampled surface points) or "spread" (a box of half-extents `spread` around the origin)
    spawn: str
    spread: Vec3
    points: Tuple[Vec3, ...]
    #: acceleration applied every second (the emitter's force range), m/s^2
    force: Tuple[Vec3, Vec3]
    damping: float
    speed_limit: float
    scale: Tuple[Vec3, Vec3]
    #: z rotation range in degrees
    rotation: Tuple[float, float]
    #: sampled at CURVE_SAMPLES points over the particle's life
    scale_over_life: Tuple[float, ...]
    alpha_over_life: Tuple[float, ...]
    #: RGB per sample, the colour curve id 21 with brightness applied
    color_over_life: Tuple[Vec3, ...]
    emissive_color: Vec3
    brightness: float
    #: beams: width in metres and jitter amplitude as a fraction of length
    beam_width: float = 0.0
    beam_jitter: float = 0.0
    mesh: str = ""
    #: how long a non-looping emitter keeps spawning (`_spawnTime`), seconds
    spawn_time: float = 0.0
    #: particle mass (`_mass`) and the emitter's time factor (`_simulationSpeed`)
    mass: float = 1.0
    simulation_speed: float = 1.0
    #: the sprite texture's flipbook grid (`_sequenceCountX/Y`), played over the particle's life
    sequence: Tuple[int, int] = (1, 1)
    #: how much the sprite stretches along its velocity (`_velocityStretch`)
    velocity_stretch: float = 0.0
    #: beams: how far the bolt runs, metres (from the emitter's own box), and along which axis
    beam_length: float = 0.0
    beam_axis: Vec3 = (0.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class EffectPreview:
    stem: str
    emitters: Tuple[EmitterPreview, ...]
    box_min: Vec3
    box_max: Vec3
    #: what could not be read as intended, per emitter, for the status line
    notes: Tuple[str, ...] = ()

    @property
    def textures(self) -> Tuple[str, ...]:
        seen: List[str] = []
        for emitter in self.emitters:
            if emitter.texture and emitter.texture not in seen:
                seen.append(emitter.texture)
        return tuple(seen)


def curve_samples(raw: bytes, components: int, *, count: int = CURVE_SAMPLES) -> Tuple[Tuple[float, ...], ...]:
    """`count` evenly spaced samples of a baked curve (`components` per stride-4-or-N sample)."""

    halves = half_floats(raw)
    if not halves or components <= 0:
        return ()
    stride = 4 if len(halves) == 512 else components
    rows = [tuple(halves[i:i + components]) for i in range(0, len(halves) - stride + 1, stride)]
    if not rows:
        return ()
    out = []
    for k in range(count):
        position = (k / max(1, count - 1)) * (len(rows) - 1)
        low = int(math.floor(position))
        high = min(len(rows) - 1, low + 1)
        t = position - low
        out.append(tuple(a + (b - a) * t for a, b in zip(rows[low], rows[high])))
    return tuple(out)


def _vec3(node: Optional[ReflectNode], name: str, default: Vec3) -> Vec3:
    value = node.value(name) if node is not None else None
    if value is None:
        return default
    raw = value.value
    if isinstance(raw, tuple) and len(raw) >= 3:
        return (float(raw[0]), float(raw[1]), float(raw[2]))
    return default


def _number(node: Optional[ReflectNode], name: str, default: float) -> float:
    value = node.value(name) if node is not None else None
    if value is None:
        return default
    raw = value.value
    return float(raw) if isinstance(raw, (int, float)) else default


def _first_child(node: ReflectNode, member: str) -> Optional[ReflectNode]:
    child = node.child(member)
    return child if isinstance(child, ReflectNode) else None


Ramp = Tuple[Tuple[Tuple[float, float], ...], ...]


@dataclass
class _Material:
    """What the preview reads out of one `_effectMaterialData2` (named or positional parameters)."""

    texture: str = ""
    blend: str = ""
    #: the temperature ramp: R, G, B, intensity splines as sorted (x, y) points, x in 0..1
    ramp: Ramp = ()
    temperature_brightness: Optional[float] = None


def _named_parameters(material: Optional[ReflectNode], layout: EmitterLayout) -> Iterable[Tuple[str, ReflectNode]]:
    if material is None:
        return
    parameters = material.child("_parameters")
    for index, parameter in enumerate(parameters if isinstance(parameters, tuple) else ()):
        name = parameter.value("_name")
        if name is not None and name.kind == 1:
            label = str(name.value)
        elif index < len(layout.parameter_names):
            label = str(layout.parameter_names[index] or "")
        else:
            label = ""
        if label:
            yield label, parameter


def _spline_points(parameter: ReflectNode) -> Ramp:
    reference = parameter.child("_value")
    instance = reference.child("_splineDataInstance") if isinstance(reference, ReflectNode) else None
    components = instance.child("_dataForSerialize") if isinstance(instance, ReflectNode) else None
    if not isinstance(components, tuple):
        return ()
    ramp: List[Tuple[Tuple[float, float], ...]] = []
    for component in components:
        points = component.child("_pointListForSerialize")
        curve: List[Tuple[float, float]] = []
        for point in points if isinstance(points, tuple) else ():
            position = point.value("_position")
            if position is not None and position.size == 8:
                x, y = struct.unpack("<2f", position.raw)
            else:
                x, y = 0.0, 0.0
            curve.append((float(x), float(y)))
        ramp.append(tuple(sorted(curve)))
    return tuple(ramp)


def _read_material(material: Optional[ReflectNode], layout: EmitterLayout) -> _Material:
    out = _Material()
    if material is None:
        return out
    for label, parameter in _named_parameters(material, layout):
        if label in ("_textureEmissive", "_textureBase") and not out.texture:
            child = _first_child(parameter, "_value")
            path = child.value("_path") if child is not None else None
            if path is not None and str(path.value) and "nonetexture" not in str(path.value).lower():
                out.texture = str(path.value)
        elif label == TEMPERATURE_RAMP and not out.ramp:
            ramp = _spline_points(parameter)
            if len(ramp) >= 3 and any(len(component) > 0 for component in ramp[:3]):
                out.ramp = ramp
        elif label == TEMPERATURE_BRIGHTNESS and out.temperature_brightness is None:
            value = parameter.value("_value")
            if value is not None and isinstance(value.value, (int, float)):
                out.temperature_brightness = float(value.value)
    permutations = material.child("_permutations")
    for permutation in permutations if isinstance(permutations, tuple) else ():
        name = permutation.value("_name")
        value = permutation.value("_value")
        if name is not None and name.value == "BLEND_MODE" and value is not None and isinstance(value.value, int):
            out.blend = "alpha" if int(value.value) not in (0, 1) else "additive"
    return out


def _evaluate_points(points: Sequence[Tuple[float, float]], x: float) -> float:
    if not points:
        return 0.0
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            span = x1 - x0
            return y0 if span <= 1e-9 else y0 + (y1 - y0) * (x - x0) / span
    return points[-1][1]


def _ramp_color(ramp: Ramp, temperature: float) -> Vec3:
    """The ramp's RGB at a normalised temperature, times its intensity spline."""

    x = max(0.0, min(1.0, temperature))
    intensity = _evaluate_points(ramp[3], x) if len(ramp) > 3 and ramp[3] else 1.0
    return tuple(max(0.0, _evaluate_points(ramp[channel], x)) * max(0.0, intensity) for channel in range(3))  # type: ignore[return-value]


def _sample_surface(mesh_path: str, meshes: Mapping[str, Sequence[Vec3]], count: int) -> Tuple[Vec3, ...]:
    vertices = list(meshes.get(mesh_path, ()) or ())
    if not vertices:
        return ()
    if len(vertices) <= count:
        return tuple((float(x), float(y), float(z)) for x, y, z in vertices)
    rng = random.Random(len(vertices))
    picked = rng.sample(range(len(vertices)), count)
    return tuple((float(vertices[i][0]), float(vertices[i][1]), float(vertices[i][2])) for i in sorted(picked))


@dataclass
class _Source:
    """One place an emitter's values can come from, in priority order: the effect's
    embedded override (values by position through `layout`), the render preset the
    embedded emitter names, the emitter file itself."""

    node: ReflectNode
    layout: EmitterLayout


RENDER_PRESET_TYPE = "EmitterRenderGroupData"


def _group_node(source: _Source, group: str) -> Optional[ReflectNode]:
    """`source`'s `group` child (`_spawnData`, ...); a render preset's root is its own
    render data, and `group` "" is the root itself."""

    if not group:
        return source.node
    if group == "_renderData" and source.node.type_name == RENDER_PRESET_TYPE:
        return source.node
    return _first_child(source.node, group)


def _read(sources: Sequence[_Source], group: str, name: str, default, reader):
    """The first source whose `group` node carries `name`, else the default."""

    for source in sources:
        node = _group_node(source, group)
        if node is not None and node.value(name) is not None:
            return reader(node, name, default)
    return default


def _curve_from(sources: Sequence[_Source], curve_id: int, assumed_components: int) -> Tuple[Tuple[float, ...], ...]:
    """The first source carrying curve `curve_id` with data: by its own `_splineID`, or by
    position through the source's layout when the entry has none. The component count is
    the entry's `_componentCount` when it says, else `assumed_components`."""

    for source in sources:
        entries = source.node.child("_curveEntryDataList")
        for index, entry in enumerate(entries if isinstance(entries, tuple) else ()):
            sid = entry.value("_splineID")
            if sid is not None and isinstance(sid.value, int):
                found = int(sid.value)
            elif index < len(source.layout.curve_ids):
                found = source.layout.curve_ids[index]
            else:
                found = None
            if found != curve_id:
                continue
            samples = entry.value("_splineData")
            if samples is None or not samples.raw:
                continue
            count_value = entry.value("_componentCount")
            components = int(count_value.value) if count_value is not None and isinstance(count_value.value, int) and count_value.value > 0 else assumed_components
            return curve_samples(samples.raw, components)
    return ()


def _string_from(sources: Sequence[_Source], name: str) -> str:
    for source in sources:
        value = source.node.value(name)
        if value is not None and str(value.value or ""):
            return str(value.value)
    return ""


def _emitter_preview(
    name: str,
    sources: Sequence[_Source],
    meshes: Mapping[str, Sequence[Vec3]],
    notes: List[str],
) -> EmitterPreview:
    burst = int(_read(sources, "_spawnData", "_spawnCountMax", 1, _number))
    term_min = float(_read(sources, "_spawnData", "_spawnTermMin", 0.05, _number))
    term_max = float(_read(sources, "_spawnData", "_spawnTermMax", term_min or 0.05, _number))
    term = max(1e-3, (term_min + term_max) / 2.0)
    life = (float(_read(sources, "_spawnData", "_lifeTimeMin", 1.0, _number)), float(_read(sources, "_spawnData", "_lifeTimeMax", 1.0, _number)))
    max_particles = int(_read(sources, "_spawnData", "_maxParticleCount", 200, _number))
    loop = int(_read(sources, "_spawnData", "_loopCount", 0, _number)) == -1
    spawn_time = float(_read(sources, "_spawnData", "_spawnTime", 0.0, _number))
    mass = float(_read(sources, "_simulationData", "_mass", 1.0, _number))
    simulation_speed = float(_read(sources, "_simulationData", "_simulationSpeed", 1.0, _number))
    velocity_stretch = float(_read(sources, "_renderData", "_velocityStretch", 0.0, _number))
    sequence = (
        max(1, int(_read(sources, "_renderData", "_sequenceCountX", 1, _number))),
        max(1, int(_read(sources, "_renderData", "_sequenceCountY", 1, _number))),
    )
    force = (
        _read(sources, "_simulationData", "_forceMin", (0.0, 0.0, 0.0), _vec3),
        _read(sources, "_simulationData", "_forceMax", (0.0, 0.0, 0.0), _vec3),
    )
    damping = float(_read(sources, "_simulationData", "_damping", 0.0, _number))
    speed_limit = float(_read(sources, "_simulationData", "_velocityLimitMax", 0.0, _number))
    scale = (
        _read(sources, "_simulationData", "_scaleMin", (1.0, 1.0, 1.0), _vec3),
        _read(sources, "_simulationData", "_scaleMax", (1.0, 1.0, 1.0), _vec3),
    )
    rotation = (
        float(_read(sources, "_simulationData", "_rotationMin", (0.0, 0.0, 0.0), _vec3)[2]),
        float(_read(sources, "_simulationData", "_rotationMax", (0.0, 0.0, 0.0), _vec3)[2]),
    )
    # the emitter's colour is the render preset's unless it says otherwise
    override_flag = _read(sources, "_renderData", "_overridePresetColor", 0.0, _number)
    presets = [source for source in sources if source.node.type_name == RENDER_PRESET_TYPE]
    emissive_sources = sources if override_flag or not presets else presets + [source for source in sources if source not in presets]
    emissive = _read(emissive_sources, "_renderData", "_emissiveColor", (1.0, 1.0, 1.0), _vec3)
    brightness_vec = _read(sources, "_renderData", "_emissiveBrightness", (1.0, 1.0, 1.0), _vec3)
    brightness = float(max(brightness_vec)) if brightness_vec else 1.0
    spread = _read(sources, "_renderData", "_particleAverageDistance", (0.25, 0.25, 0.25), _vec3)

    texture, blend, ramp, temperature_brightness = "", "", (), None
    for source in sources:
        material = _read_material(_first_child(source.node, "_effectMaterialData2"), source.layout)
        texture = texture or material.texture
        blend = blend or material.blend
        ramp = ramp or material.ramp
        if temperature_brightness is None:
            temperature_brightness = material.temperature_brightness
    blend = blend or "additive"
    if temperature_brightness is None:
        temperature_brightness = 1.0

    mesh_name = _string_from(sources, "_spawnMeshSurfaceFileName")
    points = _sample_surface(mesh_name, meshes, SURFACE_POINTS) if mesh_name else ()
    if mesh_name and not points:
        notes.append(f"{name}: spawn mesh {mesh_name.rsplit('/', 1)[-1]} was not read; particles spawn in a spread instead")
    particle_mesh = _string_from(sources, "_meshObjectFileName")

    scale_curve = _curve_from(sources, SCALE_CURVE_ID, 3)
    alpha_curve = _curve_from(sources, ALPHA_CURVE_ID, 1)
    color_curve = _curve_from(sources, COLOR_CURVE_ID, 4)
    scale_over_life = tuple(max(0.0, sum(s[:3]) / max(1, len(s[:3]))) for s in scale_curve) if scale_curve else tuple(1.0 for _ in range(CURVE_SAMPLES))
    alpha_over_life = tuple(max(0.0, min(1.0, s[0])) for s in alpha_curve) if alpha_curve else tuple(_bell(k / (CURVE_SAMPLES - 1)) for k in range(CURVE_SAMPLES))
    color_over_life = _colors_over_life(color_curve, ramp, temperature_brightness, emissive)

    kind = "billboard"
    beam_width = 0.0
    beam_jitter = 0.0
    beam_length = 0.0
    beam_axis: Vec3 = (0.0, 0.0, 0.0)
    lowered = name.lower()
    if "beam" in lowered or "lightning" in lowered or "spark_once" in lowered or "ray" in lowered:
        kind = "beam"
        # a reading: a bolt as wide as a quarter of the particle scale, as long as the
        # emitter's own box (what the game reserves for it), jittered a sixth of that
        beam_width = float(max(0.01, min(scale[1]) * 0.25))
        beam_jitter = 0.15
        box_low = _read(sources, "", "_emitterBoundBoxMin", (0.0, 0.0, 0.0), _vec3)
        box_high = _read(sources, "", "_emitterBoundBoxMax", (0.0, 0.0, 0.0), _vec3)
        extents = [abs(h - l) for l, h in zip(box_low, box_high)]
        beam_length = float(max(0.1, max(extents) * 0.6 or 0.5))
        # the bolt runs along the box's long axis, toward the side the box reaches further on
        axis = max(range(3), key=lambda i: extents[i]) if max(extents) > 1e-6 else 1
        sign = -1.0 if abs(box_low[axis]) > abs(box_high[axis]) else 1.0
        beam_axis = tuple(sign if i == axis else 0.0 for i in range(3))
    elif particle_mesh:
        kind = "mesh"

    return EmitterPreview(
        name=name, kind=kind, texture=texture, blend=blend,
        burst=max(1, burst), bursts_per_second=1.0 / term, max_particles=max(1, min(max_particles, 2000)),
        life=(max(0.05, life[0]), max(0.05, max(life))), loop=loop,
        spawn="points" if points else "spread", spread=tuple(abs(float(v)) for v in spread), points=points,  # type: ignore[arg-type]
        force=force, damping=damping, speed_limit=speed_limit, scale=scale, rotation=rotation,
        scale_over_life=scale_over_life, alpha_over_life=alpha_over_life, color_over_life=color_over_life,
        emissive_color=emissive, brightness=brightness, beam_width=beam_width, beam_jitter=beam_jitter, mesh=particle_mesh,
        spawn_time=max(0.0, spawn_time), mass=max(0.0, mass), simulation_speed=max(0.05, simulation_speed),
        sequence=sequence, velocity_stretch=max(0.0, velocity_stretch), beam_length=beam_length, beam_axis=beam_axis,
    )


def _bell(t: float) -> float:
    return max(0.0, math.sin(math.pi * max(0.0, min(1.0, t))))


#: The colour curve's fourth channel is a temperature and the ramp is written over a
#: normalised one, but nothing in the binaries says what the temperature's units are, and
#: the corpus does not agree with itself: across forty shipped effects the channel tops out
#: at 1.4 on one fire, 10 on an artifact aura, 268 on another, and 2039 on a third. A fixed
#: divisor therefore reads most curves at the very bottom of their ramp, which is where the
#: ramp is nearly black -- the fire sweep drew in (0.004, 0, 0), a red so dark it read as
#: soot. Each curve is normalised by its own hottest sample instead, so an emitter's hottest
#: moment reads the top of its own ramp and the curve's shape still moves the hue over the
#: particle's life. The fire sweep then lands on the ramp's (1.0, 0.12, 0.03), which is the
#: same orange its own sibling emitter carries as an emissive colour.


def _colors_over_life(color_curve: Sequence[Sequence[float]], ramp: Ramp, temperature_brightness: float, emissive: Vec3) -> Tuple[Vec3, ...]:
    """The colour curve's RGB plus the temperature ramp read at the sample's temperature
    (the fourth channel over the curve's own hottest sample), times `_temperatureBrightness`;
    without a colour curve, the emitter's `_emissiveColor` throughout. Not scaled by the
    emissive brightness: the viewer normalises the peak so a dim HDR fire still shows."""

    if not color_curve:
        return tuple((max(0.0, emissive[0]), max(0.0, emissive[1]), max(0.0, emissive[2])) for _ in range(CURVE_SAMPLES))
    hottest = max((float(sample[3]) for sample in color_curve if len(sample) > 3), default=0.0)
    out: List[Vec3] = []
    for sample in color_curve:
        rgb = [max(0.0, float(v)) for v in list(sample[:3]) + [0.0] * (3 - len(sample[:3]))]
        if ramp and len(sample) > 3 and hottest > 0.0:
            temperature = float(sample[3]) / hottest
            if temperature > 0.0:
                warm = _ramp_color(ramp, temperature)
                rgb = [rgb[i] + warm[i] * temperature_brightness for i in range(3)]
        out.append((rgb[0], rgb[1], rgb[2]))
    if all(max(c) <= 1e-6 for c in out):
        return tuple((max(0.0, emissive[0]), max(0.0, emissive[1]), max(0.0, emissive[2])) for _ in out)
    return tuple(out)


def build_effect_preview(
    stem: str,
    document: EffectDocument,
    *,
    emitter_documents: Mapping[str, EffectDocument] = (),
    layouts: Mapping[str, EmitterLayout] = (),
    preset_documents: Mapping[str, EffectDocument] = (),
    meshes: Mapping[str, Sequence[Vec3]] = (),
) -> EffectPreview:
    """The preview of `document` (an effect, `.pae`), with its emitter files decoded in
    `emitter_documents` (archive path -> document), their `layouts` for positional
    overrides, the render presets in `preset_documents` (preset name -> document; what
    the emitter file leaves unsaid comes from the `_renderGroupPreset` it names, and its
    emissive colour is the preset's unless `_overridePresetColor` says otherwise), and
    `meshes` (archive path of a spawn mesh -> its vertices)."""

    notes: List[str] = []
    emitters: List[EmitterPreview] = []
    paths = emitter_paths_of(document)
    variations = document.root.child("_emitterVariationDataArray")
    for index, variation in enumerate(variations if isinstance(variations, tuple) else ()):
        name_value = variation.value("_emitterDataName")
        name = str(name_value.value) if name_value is not None else f"emitter {index}"
        embedded = _first_child(variation, "_internalEmitterData")
        if embedded is None:
            notes.append(f"{name}: no embedded emitter data")
            continue
        path = embedded.type_name.lstrip("/")
        sources = [_Source(embedded, (layouts.get(path) if layouts else None) or EmitterLayout())]
        base_doc = emitter_documents.get(path) if emitter_documents else None
        if base_doc is not None:
            sources.append(_Source(base_doc.root, EmitterLayout()))
        else:
            notes.append(f"{name}: the emitter file {path.rsplit('/', 1)[-1]} was not read; only the effect's own overrides describe it")
        preset_name = embedded.value("_renderGroupPreset")
        preset = preset_documents.get(str(preset_name.value)) if preset_name is not None and preset_documents else None
        if preset is not None:
            sources.append(_Source(preset.root, EmitterLayout()))
        emitters.append(_emitter_preview(name, sources, meshes, notes))
    box_min = _vec3(document.root, "_boundingBoxMin", (-0.5, -0.5, -0.5))
    box_max = _vec3(document.root, "_boundingBoxMax", (0.5, 0.5, 0.5))
    if not emitters and not paths:
        notes.append("the effect names no emitters")
    return EffectPreview(stem=stem, emitters=tuple(emitters), box_min=box_min, box_max=box_max, notes=tuple(notes))


class _SnapshotLike(Protocol):
    def has_entry(self, path: str) -> bool: ...
    def payload(self, path: str) -> bytes: ...


def preview_effect_from_snapshot(
    snapshot: _SnapshotLike,
    effect_reference: str,
    look: Optional[LookLike] = None,
    *,
    parse_mesh: Optional[Callable[[bytes, str], object]] = None,
) -> EffectPreview:
    """Read `effect_reference` (`<stem>.pae` or a stem) and everything it names out of the
    archives, apply `look` the way the plan will (:func:`apply_effect_look` on the effect,
    its emitters and its render presets), and build the preview. Spawn meshes are parsed
    with `parse_mesh` (default: the app's mesh parser); one that fails to read is a note,
    not an error."""

    from cdmw.core.effect_binary import decode_effect_binary
    from cdmw.core.effect_edit import apply_effect_look, emitter_layout_of, preset_names_of, preset_path
    from cdmw.services.new_item_snapshot import EFFECT_DIR

    stem = str(effect_reference).split(".", 1)[0]
    effect_path = "".join((EFFECT_DIR, stem, ".pae"))
    if not snapshot.has_entry(effect_path):
        raise KeyError(f"the archives have no {effect_path}")
    source = snapshot.payload(effect_path)
    document = decode_effect_binary(source)
    emitter_documents: dict = {}
    layouts: dict = {}
    emitter_sources: dict = {}
    for emitter_path in emitter_paths_of(document):
        if not snapshot.has_entry(emitter_path):
            continue
        data = snapshot.payload(emitter_path)
        emitter_sources[emitter_path] = data
        layouts[emitter_path] = emitter_layout_of(decode_effect_binary(data))
    preset_sources: dict = {}
    for kind, name in preset_names_of(document) + tuple(item for data in emitter_sources.values() for item in preset_names_of(decode_effect_binary(data))):
        if kind != "render" or name in preset_sources:
            continue
        path = preset_path(kind, name)
        if snapshot.has_entry(path):
            preset_sources[name] = snapshot.payload(path)
    apply = look is not None and not getattr(look, "is_default", False)
    if apply:
        source, _report = apply_effect_look(source, look, emitter_layouts=layouts)
        document = decode_effect_binary(source)
    for emitter_path, data in emitter_sources.items():
        if apply:
            data, _report = apply_effect_look(data, look)
        emitter_documents[emitter_path] = decode_effect_binary(data)
    preset_documents = {}
    for name, data in preset_sources.items():
        if apply:
            data, _report = apply_effect_look(data, look)
        preset_documents[name] = decode_effect_binary(data)
    meshes: dict = {}
    parser = parse_mesh
    if parser is None:
        from cdmw.modding.mesh_parser import parse_mesh as _parse_mesh

        parser = _parse_mesh
    for holder in (document, *emitter_documents.values()):
        for node in holder.root.walk():
            value = node.value("_spawnMeshSurfaceFileName")
            if value is None or not str(value.value or "") or str(value.value) in meshes:
                continue
            path = str(value.value)
            if not snapshot.has_entry(path):
                continue
            try:
                parsed = parser(snapshot.payload(path), path.rsplit("/", 1)[-1])
                vertices = [tuple(float(c) for c in vertex[:3]) for submesh in getattr(parsed, "submeshes", ()) for vertex in getattr(submesh, "vertices", ())]
            except Exception:  # noqa: BLE001 - a spawn mesh that does not parse is a spread, and a note
                vertices = []
            if vertices:
                meshes[path] = vertices
    return build_effect_preview(stem, document, emitter_documents=emitter_documents, layouts=layouts, preset_documents=preset_documents, meshes=meshes)


def effect_preview_json(preview: EffectPreview) -> str:
    """The preview as the viewer reads it: `effect_preview.json`, schema 1."""

    payload = {"schema": 1, "stem": preview.stem, "box_min": list(preview.box_min), "box_max": list(preview.box_max), "notes": list(preview.notes), "emitters": []}
    for emitter in preview.emitters:
        item = asdict(emitter)
        item["life"] = list(emitter.life)
        item["spread"] = list(emitter.spread)
        item["points"] = [list(p) for p in emitter.points]
        item["force"] = [list(emitter.force[0]), list(emitter.force[1])]
        item["scale"] = [list(emitter.scale[0]), list(emitter.scale[1])]
        item["rotation"] = list(emitter.rotation)
        item["scale_over_life"] = list(emitter.scale_over_life)
        item["alpha_over_life"] = list(emitter.alpha_over_life)
        item["color_over_life"] = [list(c) for c in emitter.color_over_life]
        item["emissive_color"] = list(emitter.emissive_color)
        item["sequence"] = list(emitter.sequence)
        item["beam_axis"] = list(emitter.beam_axis)
        payload["emitters"].append(item)
    return json.dumps(payload, indent=1)
