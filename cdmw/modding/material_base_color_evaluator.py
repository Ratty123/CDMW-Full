"""Resident/export base-color pixel parity."""

from __future__ import annotations


# Mirrors the recolour block in D3D11MaterialShaders.hlsl. The shader damps
# this branch on submeshes the renderer classified as metal; a user-authored
# recolour has no such classification, so this port implements the plain
# non-metal path and the baked DDS it produces is the exact result.
_COLOURISE_LUMA_FLOOR = 0.08
_COLOURISE_BIAS_MIN = 0.38
_COLOURISE_BIAS_MAX = 1.72
_COLOURISE_BLEND = 0.58


def colourise_strength_from(values: object) -> float:
    """Return the clamped recolour strength declared by an evaluation."""
    try:
        strength = float(getattr(values, "colourise_strength", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return max(0.0, min(1.0, strength))


def colourise_color_from(values: object) -> tuple[float, float, float] | None:
    """Return the clamped normalized recolour operand, if one is declared."""
    colour = tuple(getattr(values, "colourise_color", ()) or ())
    if len(colour) < 3:
        return None
    try:
        clamped = tuple(max(0.0, min(1.0, float(component))) for component in colour[:3])
    except (TypeError, ValueError, OverflowError):
        return None
    return clamped


def _colourised_rgb(rgb: object, values: object) -> object:
    """Repaint toward the declared hue while preserving source luminance."""
    import numpy as np

    strength = colourise_strength_from(values)
    colour = colourise_color_from(values)
    if strength <= 0.0 or colour is None:
        return rgb
    luma_weights = np.asarray((0.299, 0.587, 0.114), dtype=np.float32)
    tint = np.asarray(colour, dtype=np.float32)
    tint_luma = max(float(np.dot(tint, luma_weights)), _COLOURISE_LUMA_FLOOR)
    tint_bias = np.clip(
        tint / np.float32(tint_luma),
        np.float32(_COLOURISE_BIAS_MIN),
        np.float32(_COLOURISE_BIAS_MAX),
    )
    scaled = np.float32(strength)
    albedo_luma = np.sum(rgb * luma_weights, axis=2, keepdims=True)
    lifted_luma = np.clip(
        albedo_luma * (np.float32(1.05) + scaled * np.float32(0.35))
        + np.float32(0.10) * scaled,
        0.0,
        1.0,
    )
    multiplied = np.clip(rgb * tint_bias, 0.0, 1.0)
    colorized = np.clip(lifted_luma * tint_bias, 0.0, 1.0)
    blended = multiplied + (colorized - multiplied) * np.float32(_COLOURISE_BLEND)
    return np.clip(rgb + (blended - rgb) * scaled, 0.0, 1.0)


def shader_equivalent_base_color_rgba(
    rgba: object,
    values: object,
    *,
    alpha_factor: float,
) -> object:
    """Apply the resident HLSL base-color evaluator before DDS encoding."""
    import numpy as np
    from PIL import Image

    pixels = np.asarray(rgba, dtype=np.float32) / np.float32(255.0)
    rgb = pixels[..., :3]
    rgb = _colourised_rgb(rgb, values)
    tint = tuple(getattr(values, "tint_color", ()) or ())
    tint = tint[:3] if len(tint) >= 3 else (1.0, 1.0, 1.0)
    brightness = max(
        0.1,
        float(getattr(values, "base_brightness", 1.0)) * float(getattr(values, "base_color_scale", 1.0)),
    )
    rgb = np.clip(rgb * np.float32(brightness), 0.0, 1.0)
    rgb = np.clip(rgb * np.asarray(tint, dtype=np.float32), 0.0, 1.0)
    rgb = np.power(rgb, np.float32(getattr(values, "gamma", 1.0)))
    lift = np.float32(getattr(values, "base_color_lift", 0) / 255.0)
    rgb = np.clip(lift + rgb * (np.float32(1.0) - lift), 0.0, 1.0)
    luma_weights = np.asarray((0.299, 0.587, 0.114), dtype=np.float32)
    luma = np.sum(rgb * luma_weights, axis=2, keepdims=True)
    saturation = np.float32(max(0.0, float(getattr(values, "saturation", 1.0))))
    rgb = np.clip(luma + (rgb - luma) * saturation, 0.0, 1.0)
    luma = np.sum(rgb * luma_weights, axis=2, keepdims=True)
    balance = np.float32(max(0.0, min(1.0, float(getattr(values, "auto_balance", 0)) / 100.0)))
    if balance > 0.0:
        target = np.where(
            luma < np.float32(96.0 / 255.0),
            np.float32(116.0 / 255.0),
            np.where(luma > np.float32(158.0 / 255.0), np.float32(138.0 / 255.0), luma),
        )
        correction = np.clip(
            np.power(target / np.maximum(luma, np.float32(1.0 / 255.0)), balance),
            np.float32(0.68),
            np.float32(1.42),
        )
        rgb = np.clip(rgb * correction, 0.0, 1.0)
    luma = np.sum(rgb * luma_weights, axis=2, keepdims=True)
    shadow_mask = np.power(
        np.clip((np.float32(96.0 / 255.0) - luma) / np.float32(96.0 / 255.0), 0.0, 1.0),
        np.float32(1.5),
    )
    shadow_boost = np.float32(72.0 / 255.0) * np.float32(
        max(0.0, min(1.0, float(getattr(values, "shadow_lift", 0)) / 100.0))
    )
    rgb = rgb + (np.clip(rgb + shadow_boost, 0.0, 1.0) - rgb) * shadow_mask
    tone = float(getattr(values, "tone_contrast", 0.0))
    contrast = max(0.35, 1.0 + 0.55 * tone / 100.0) if tone < 0.0 else 1.0 + 0.75 * tone / 100.0
    rgb = np.clip((rgb - np.float32(0.5)) * np.float32(contrast) + np.float32(0.5), 0.0, 1.0)
    post_brightness = 1.0 + 0.10 * (-tone / 100.0) if tone < 0.0 else 1.0
    rgb = np.clip(rgb * np.float32(post_brightness), 0.0, 1.0)
    rgb = np.minimum(rgb, np.float32(getattr(values, "value_max", 255) / 255.0))
    result = np.empty_like(pixels, dtype=np.uint8)
    result[..., :3] = np.floor(rgb * np.float32(255.0) + np.float32(0.5)).astype(np.uint8)
    alpha = np.clip(pixels[..., 3] * np.float32(alpha_factor), 0.0, 1.0)
    result[..., 3] = np.floor(alpha * np.float32(255.0) + np.float32(0.5)).astype(np.uint8)
    return Image.fromarray(result, "RGBA")


__all__ = [
    "colourise_color_from",
    "colourise_strength_from",
    "shader_equivalent_base_color_rgba",
]
