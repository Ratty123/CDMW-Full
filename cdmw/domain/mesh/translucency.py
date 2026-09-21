"""Validated experimental absorption settings shared by mesh parts and drafts."""

import math
from collections.abc import Mapping


def translucency_surface_values(value: object) -> tuple[float | None, float | None] | None:
    """Optional absolute roughness/metallic overrides; None retains source maps."""
    if value is None:
        return None
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(item is not None and (isinstance(item, bool) or not isinstance(item, (int, float))
                   or not math.isfinite(item) or not 0 <= item <= 1) for item in value)):
        raise ValueError("Translucent surface requires roughness and metallic values between 0 and 1, or source values.")
    result = tuple(float(item) if item is not None else None for item in value)
    return result if any(item is not None for item in result) else None


def translucency_values(value: object) -> tuple[float, float]:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(item, bool) or not isinstance(item, (int, float))
                   or not math.isfinite(item) or not 0 <= item <= 1 for item in value)):
        raise ValueError("Translucency requires thickness and extinction between 0 and 1.")
    return (float(value[0]), float(value[1]))


def authored_translucency(source: object) -> tuple[float, float] | None:
    """Read exact shader evidence only, never a material-name guess."""
    def field(row, key, default=None):
        return row.get(key, default) if isinstance(row, Mapping) else getattr(row, key, default)

    inputs = tuple(getattr(source, "preview_material_texture_inputs", ()) or ())
    shader = str(getattr(source, "preview_sidecar_shader_family", "") or "").casefold()
    exact = shader == "skinnedmeshtranslucent" if shader else any(
        str(field(item, "shader_family", "")).casefold() == "skinnedmeshtranslucent" for item in inputs)
    if not exact:
        return None
    parameters = list(getattr(source, "preview_material_parameters", ()) or ())
    for item in inputs:
        parameters.extend(field(item, "material_parameters", ()) or ())
    values = {"_thickness": .02, "_extinctioncoefficient": .3}
    for parameter in parameters:
        name = str(field(parameter, "parameter_name", "")).casefold()
        if name in values:
            number = field(parameter, "numeric_value")
            try:
                values[name] = float(number if number is not None else field(parameter, "value"))
            except (ValueError, TypeError, OverflowError):
                return None
    try:
        return translucency_values(tuple(values.values()))
    except ValueError:
        return None
