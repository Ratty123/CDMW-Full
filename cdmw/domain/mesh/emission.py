"""Material-local emission controls verified in the equipment emissive shaders."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from collections.abc import Mapping

ANIMATION_NAMES = ("_emissiveFlowSpeedU", "_emissiveFlowSpeedV",
                   "_emissiveFlickeringFreq", "_emissiveFlickeringIntensityMin")


def authored_glow_animation(source):
    """Read exported/source controls only for a shader known to consume them."""
    def field(row, name, default=None):
        return row.get(name, default) if isinstance(row, Mapping) else getattr(row, name, default)

    inputs = tuple(getattr(source, "preview_material_texture_inputs", ()) or ())
    shader = getattr(source, "preview_sidecar_shader_family", "")
    shaders = [shader] if shader else [field(row, "shader_family", "") for row in inputs]
    if not any(str(name).casefold() in {"skinnedmeshemissive", "skinnedmeshemissive_ver2"} for name in shaders):
        return None
    values = {name.casefold(): 0.0 for name in ANIMATION_NAMES}
    parameters = list(getattr(source, "preview_material_parameters", ()) or ())
    for row in inputs:
        parameters.extend(field(row, "material_parameters", ()) or ())
    try:
        for parameter in parameters:
            name = str(field(parameter, "parameter_name", "")).casefold()
            if name in values:
                number = field(parameter, "numeric_value")
                values[name] = float(number if number is not None else field(parameter, "value"))
        return GlowAnimation(*values.values()).factors()
    except (ValueError, TypeError, OverflowError):
        return None


def authored_rgb_glow_factors(source):
    """Recognize our single-map RGB recipe without guessing other progress shaders."""
    def field(row, name, default=None):
        return row.get(name, default) if isinstance(row, Mapping) else getattr(row, name, default)

    if authored_glow_animation(source) is None:
        return {}
    inputs = tuple(getattr(source, "preview_material_texture_inputs", ()) or ())
    textures = {str(field(row, "parameter_name", "")): str(field(row, "source_texture_path", "")).replace("\\", "/").casefold()
                for row in inputs}
    path = textures.get("_emissiveIntensityTexture")
    if not path or path != textures.get("_emissiveProgressTexture") or path != textures.get("_emissiveProgressMaskTexture"):
        return {}
    parameters = list(getattr(source, "preview_material_parameters", ()) or ())
    for row in inputs:
        parameters.extend(field(row, "material_parameters", ()) or ())
    values = {}
    for parameter in parameters:
        value = field(parameter, "numeric_value")
        values[str(field(parameter, "parameter_name", ""))] = value if value is not None else field(parameter, "value")
    try:
        if float(values.get("_emissiveIntensity", 1)) != 0:
            return {}
        rgb = RgbGlow(float(values["_emissiveProgressIntensity"]), float(values["_emissiveProgressGauge"]),
                      float(values["_emissiveMaskHardness"]), bool(int(values["_emissiveMaskInverse"])))
        color = str(values["_emissiveProgressColor"]).removeprefix("#")
        if len(color) not in (6, 8):
            return {}
        return {"emission_reveal": rgb.factors(),
                "emissive_color": tuple(int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))}
    except (ValueError, TypeError, KeyError, OverflowError):
        return {}



@dataclass(frozen=True, slots=True)
class GlowAnimation:
    flow_u: float = 0.0
    flow_v: float = 0.0
    pulse_frequency: float = 0.0
    pulse_minimum: float = 0.0

    def validate(self):
        for name, maximum in (("flow_u", 10), ("flow_v", 10),
                              ("pulse_frequency", 10), ("pulse_minimum", 1)):
            value = getattr(self, name)
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not 0 <= value <= maximum):
                raise ValueError(f"Glow {name.replace('_', ' ')} must be between 0 and {maximum}.")

    def factors(self):
        self.validate()
        return (self.flow_u, self.flow_v, self.pulse_frequency, self.pulse_minimum)

    @property
    def active(self):
        return bool(self.flow_u or self.flow_v or self.pulse_frequency)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("Malformed glow animation settings.")
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class RgbGlow:
    """RGB/alpha from the source glow map; its red channel is the reveal mask."""
    intensity: float = 1.0
    reveal: float = 1.0
    softness: float = 0.1
    inverse: bool = False

    def validate(self):
        if type(self.inverse) is not bool:
            raise ValueError("RGB glow mask inversion must be a boolean.")
        for name, minimum in (("intensity", 0), ("reveal", 0), ("softness", .001)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= 1:
                raise ValueError(f"RGB glow {name} must be between {minimum} and 1.")

    def factors(self):
        self.validate()
        return (self.reveal, self.softness, float(self.inverse), self.intensity)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("Malformed RGB glow settings.")
        result = cls(**value)
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class EmissionChoice:
    """An explicit override. None on a part means retain its original emission."""
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    intensity: float = 4.0
    animation: GlowAnimation = GlowAnimation()
    rgb: RgbGlow | None = None

    def validate(self):
        self.animation.validate()
        if self.rgb is not None:
            self.rgb.validate()
        if (len(self.color) != 3 or any(type(v) not in (float, int) or not math.isfinite(v)
                                       or not 0 <= v <= 1 for v in self.color)
                or type(self.intensity) not in (float, int) or not math.isfinite(self.intensity)
                or not 0 <= self.intensity <= 20):
            raise ValueError("Glow needs an RGB colour in 0..1 and a strength in 0..20.")

    def hex_color(self):
        self.validate()
        return "#" + "".join(f"{round(v * 255):02X}" for v in self.color) + "FF"

    def to_dict(self):
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - {"color", "intensity", "animation", "rgb"} or not {"color", "intensity", "animation"} <= set(value):
            raise ValueError("Malformed glow settings.")
        if not isinstance(value["color"], (tuple, list)):
            raise ValueError("Malformed glow colour.")
        result = cls(tuple(value["color"]), value["intensity"], GlowAnimation.from_dict(value["animation"]),
                     RgbGlow.from_dict(value["rgb"]) if value.get("rgb") is not None else None)
        result.validate()
        return result
