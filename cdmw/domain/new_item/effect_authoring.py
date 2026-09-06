"""Immutable effect recipes, shared by the inspector, preview and export planner."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

Vec3 = Tuple[float, float, float]

# Only named, decoded fields are exposed. Values are absolute; None means inherit.
EMITTER_FIELDS = (
    ("_opacity", "Opacity", 0.0, 1.0, 1.0),
    ("_spawnCountMin", "Burst minimum", 0.0, 10000.0, 1.0),
    ("_spawnCountMax", "Burst maximum", 0.0, 10000.0, 1.0),
    ("_spawnTermMin", "Interval minimum (s)", 0.0, 120.0, 0.05),
    ("_spawnTermMax", "Interval maximum (s)", 0.0, 120.0, 0.05),
    ("_spawnTime", "Emission duration (s)", 0.0, 120.0, 1.0),
    ("_spawnDelayMin", "Start delay minimum (s)", 0.0, 120.0, 0.0),
    ("_spawnDelayMax", "Start delay maximum (s)", 0.0, 120.0, 0.0),
    ("_lifeTimeMin", "Lifetime minimum (s)", 0.01, 120.0, 1.0),
    ("_lifeTimeMax", "Lifetime maximum (s)", 0.01, 120.0, 1.0),
    ("_sequenceCountX", "Atlas columns", 1.0, 64.0, 1.0),
    ("_sequenceCountY", "Atlas rows", 1.0, 64.0, 1.0),
    ("_maxParticleCount", "Particle limit", 1.0, 100000.0, 200.0),
    ("_loopCount", "Repeats (-1 = forever)", -1.0, 1000.0, 0.0),
    ("_simulationSpeed", "Simulation speed", 0.01, 20.0, 1.0),
    ("_damping", "Damping", 0.0, 100.0, 0.0),
    ("_mass", "Mass", 0.01, 100.0, 1.0),
    ("_velocityLimitMax", "Speed limit", 0.0, 1000.0, 0.0),
    ("_velocityStretch", "Velocity stretch", 0.0, 20.0, 0.0),
)
VECTOR_FIELDS = (
    ("_velocityMin", "Initial velocity minimum"),
    ("_velocityMax", "Initial velocity maximum"),
    ("_forceMin", "Force minimum"),
    ("_forceMax", "Force maximum"),
    ("_rotationMin", "Rotation minimum"),
    ("_rotationMax", "Rotation maximum"),
)
INTEGER_FIELDS = frozenset(('_spawnCountMin', '_spawnCountMax', '_maxParticleCount', '_loopCount', '_sequenceCountX', '_sequenceCountY'))


@dataclass(frozen=True, slots=True)
class EmitterEdit:
    index: int
    enabled: bool = True
    color: Optional[Vec3] = None
    intensity: float = 1.0
    size: float = 1.0
    rate: float = 1.0
    lifetime: float = 1.0
    values: Tuple[Tuple[str, Tuple[float, ...]], ...] = ()
    color_curve: Tuple[Vec3, ...] = ()
    size_curve: Tuple[float, ...] = ()
    opacity_curve: Tuple[float, ...] = ()
    texture: str = ""


@dataclass(frozen=True, slots=True)
class EffectLook:
    color: Optional[Vec3] = None
    intensity: float = 1.0
    size: float = 1.0
    rate: float = 1.0
    lifetime: float = 1.0
    emitters: Tuple[EmitterEdit, ...] = ()
    # Indices into the source effect. Repetition duplicates an emitter; () is empty.
    emitter_order: Optional[Tuple[int, ...]] = None

    @property
    def is_default(self) -> bool:
        return (self.color is None and not self.emitters and self.emitter_order is None
                and all(abs(float(v) - 1.0) < 1e-9 for v in (self.intensity, self.size, self.rate, self.lifetime)))


@dataclass(frozen=True, slots=True)
class EffectLayer:
    stem: str
    name: str = ""
    enabled: bool = True
    scale: float = 1.0
    offset: Vec3 = (0.0, 0.0, 0.0)
    rotation: Vec3 = (0.0, 0.0, 0.0)
    look: EffectLook = field(default_factory=EffectLook)
    kind: str = 'level'

    @property
    def reference(self) -> str:
        return f"{self.stem}.{self.kind}.effect"


def validate_emitter_edits(look: EffectLook) -> None:
    """Validate user recipes before decoding, allocating or writing binary data."""
    limits = {key: (low, high) for key, _label, low, high, _default in EMITTER_FIELDS}
    vectors = {key for key, _label in VECTOR_FIELDS}
    if len(look.emitters) > 128 or (look.emitter_order is not None and len(look.emitter_order) > 128):
        raise ValueError("An effect supports at most 128 emitter slots.")
    seen = set()
    for edit in look.emitters:
        if type(edit.index) is not int or edit.index in seen or not 0 <= edit.index < 128:
            raise ValueError("Emitter indices must be distinct and between 0 and 127.")
        seen.add(edit.index)
        if type(edit.enabled) is not bool:
            raise ValueError('Emitter visibility must be a boolean.')
        if edit.color is not None and (len(edit.color) != 3 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in edit.color)):
            raise ValueError("Emitter colour must contain three values between 0 and 1.")
        for v in (edit.intensity, edit.size, edit.rate, edit.lifetime):
            if not math.isfinite(v) or not 0.05 <= v <= 20:
                raise ValueError("Emitter factors must be between 0.05 and 20.")
        if len(dict(edit.values)) != len(edit.values):
            raise ValueError("An emitter field cannot be set twice.")
        for key, values in edit.values:
            low, high = limits.get(key, (-1000.0, 1000.0))
            if key not in limits and key not in vectors:
                raise ValueError(f"Unsupported emitter field: {key}")
            if len(values) != (3 if key in vectors else 1) or any(not math.isfinite(v) or not low <= v <= high for v in values):
                raise ValueError(f"Invalid value for emitter field {key}.")
            if key in INTEGER_FIELDS and any(v != int(v) for v in values):
                raise ValueError(f'{key} requires a whole number.')
        fields = dict(edit.values)
        for key in ('_spawnCount', '_spawnTerm', '_spawnDelay', '_lifeTime', '_velocity', '_force', '_rotation'):
            if key + 'Min' in fields and key + 'Max' in fields and any(a > b for a, b in zip(fields[key + 'Min'], fields[key + 'Max'])):
                raise ValueError(f'{key} minimum cannot exceed its maximum.')
        for curve, maximum in ((edit.size_curve, 20.0), (edit.opacity_curve, 1.0)):
            if curve and (not 2 <= len(curve) <= 128 or any(not math.isfinite(v) or not 0 <= v <= maximum for v in curve)):
                raise ValueError("Curves require 2 to 128 finite samples in range.")
        if edit.color_curve and (not 2 <= len(edit.color_curve) <= 128 or any(len(c) != 3 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in c) for c in edit.color_curve)):
            raise ValueError("Colour curves require 2 to 128 RGB samples.")
        if edit.texture and (not edit.texture.lower().endswith('.dds') or len(edit.texture) > 1024 or '\\' in edit.texture or ':' in edit.texture or any(p in ('', '.', '..') for p in edit.texture.split('/'))):
            raise ValueError("Choose a relative DDS archive path.")
    if look.emitter_order is not None and any(type(i) is not int or not 0 <= i < 128 for i in look.emitter_order):
        raise ValueError("Invalid emitter order.")
