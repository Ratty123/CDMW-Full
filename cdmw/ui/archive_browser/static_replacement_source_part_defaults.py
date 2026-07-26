"""Source-part adjustment default checks for static replacement."""

from __future__ import annotations


def is_default_source_part_adjustment(adjustment: object) -> bool:
    material_tint = tuple(getattr(adjustment, "material_tint_rgb", ()) or ())
    return (
        bool(getattr(adjustment, "enabled", False))
        and all(abs(float(value)) <= 1e-8 for value in getattr(adjustment, "offset_xyz", ()))
        and all(abs(float(value)) <= 1e-8 for value in getattr(adjustment, "rotate_xyz_degrees", ()))
        and all(abs(float(value) - 1.0) <= 1e-8 for value in getattr(adjustment, "scale_xyz", ()))
        and abs(float(getattr(adjustment, "uniform_scale", 1.0)) - 1.0) <= 1e-8
        and str(getattr(adjustment, "pivot_mode", "part_center") or "part_center") == "part_center"
        and not str(getattr(adjustment, "material_role", "") or "").strip()
        and not tuple(getattr(adjustment, "emissive_color_rgb", ()) or ())
        and getattr(adjustment, "emissive_strength", None) is None
        and abs(float(getattr(adjustment, "material_brightness", 0.0) or 0.0)) <= 1e-8
        and abs(float(getattr(adjustment, "material_contrast", 0.0) or 0.0)) <= 1e-8
        and abs(float(getattr(adjustment, "material_saturation", 0.0) or 0.0)) <= 1e-8
        and abs(float(getattr(adjustment, "material_gamma", 1.0) or 1.0) - 1.0) <= 1e-8
        and (not material_tint or tuple(int(value) for value in material_tint[:3]) == (255, 255, 255))
        and abs(float(getattr(adjustment, "material_colourise_strength", 0.0) or 0.0)) <= 1e-8
    )


__all__ = ["is_default_source_part_adjustment"]
