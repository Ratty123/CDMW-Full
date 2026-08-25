"""The effect placement dialog's plain helpers: the emitter description, the backdrop
memory, the legend swatches, and the frame the numbers travel through. Split from the
dialog so the dialog file stays the dialog."""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from cdmw.services.effect_preview_model import EffectPreview

Vec3 = Tuple[float, float, float]

__all__ = [
    "BACKDROPS",
    "BACKDROP_BLACK",
    "BACKDROP_DARK",
    "BACKDROP_GREY",
    "PARTICLE_TINT",
    "PlacementFrame",
    "describe_effect_preview",
    "placed_item_origin",
    "remember_backdrop",
    "remember_orbit_inversion",
    "remembered_backdrop",
    "remembered_orbit_inversion",
    "swatch",
]


def placed_item_origin(mesh: object) -> Vec3:
    """The applied Model & Placement origin carried by a wearable preview mesh."""

    raw = getattr(mesh, "_cdmw_effect_item_origin", None)
    try:
        values = tuple(float(value) for value in raw)
    except (TypeError, ValueError):
        values = ()
    return values if len(values) == 3 else (0.0, 0.0, 0.0)  # type: ignore[return-value]


def describe_effect_preview(preview: Optional[EffectPreview]) -> str:
    """The emitters as the description read them, one line each, then what it could not read."""

    if preview is None:
        return ""
    lines = []
    for emitter in preview.emitters:
        short = emitter.name.rsplit("/", 1)[-1]
        rate = emitter.burst * emitter.bursts_per_second
        colour = max(emitter.color_over_life, key=max) if emitter.color_over_life else emitter.emissive_color
        top = max(colour) or 1.0
        hex_colour = "#%02x%02x%02x" % tuple(int(round(255 * min(1.0, c / top))) for c in colour)
        texture = emitter.texture.rsplit("/", 1)[-1] if emitter.texture else "no texture"
        loop = "loops" if emitter.loop else "once"
        lines.append(f"{short}: {emitter.kind}, {rate:.0f}/s, {emitter.life[0]:.2f}-{emitter.life[1]:.2f} s, {loop}, {emitter.blend}, {texture}, {hex_colour}")
    if not lines:
        lines.append("The effect names no emitters the description could read.")
    lines.extend(preview.notes)
    return "\n".join(lines)


#: What the viewport can clear to. An effect adds its light to what is behind it, so it
#: reads best on a dark backdrop: measured on the same weapon fire, the effect stands 173
#: shades above #101014 and 131 above the Mesh Editor's material grey. The grey is kept
#: because judging the item's own textures is the other half of this dialog's job.
BACKDROP_DARK = "#101014"
BACKDROP_GREY = "#3B3B3B"
BACKDROP_BLACK = "#06060A"
#: in the order they are offered; the first is what a dialog opens on the first time
BACKDROPS: tuple = (BACKDROP_DARK, BACKDROP_GREY, BACKDROP_BLACK)

#: where the chosen backdrop is remembered between dialogs, in the scope the rest of the
#: studio's own settings use
_SETTINGS_SCOPE = "CrimsonDesertModWorkbench"
_BACKDROP_SETTING = "new_item/effect_placement_backdrop"
_ORBIT_X_SETTING = "preview/invert_orbit_x"
_ORBIT_Y_SETTING = "preview/invert_orbit_y"


def remembered_backdrop() -> str:
    from PySide6.QtCore import QSettings

    try:
        value = QSettings(_SETTINGS_SCOPE, _SETTINGS_SCOPE).value(_BACKDROP_SETTING, BACKDROPS[0])
    except Exception:  # noqa: BLE001 - a session without settings opens on the default
        return BACKDROPS[0]
    return str(value or BACKDROPS[0])


def remember_backdrop(colour: str) -> None:
    from PySide6.QtCore import QSettings

    try:
        QSettings(_SETTINGS_SCOPE, _SETTINGS_SCOPE).setValue(_BACKDROP_SETTING, str(colour))
    except Exception:  # noqa: BLE001 - not remembering is not worth an error
        pass


def _settings_bool(settings: object, key: str) -> bool:
    value = settings.value(key, False)  # type: ignore[attr-defined]
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def remembered_orbit_inversion() -> Tuple[bool, bool]:
    """The shared resident-preview orbit preferences, horizontal then vertical."""

    from PySide6.QtCore import QSettings

    try:
        settings = QSettings(_SETTINGS_SCOPE, _SETTINGS_SCOPE)
        return (
            _settings_bool(settings, _ORBIT_X_SETTING),
            _settings_bool(settings, _ORBIT_Y_SETTING),
        )
    except Exception:  # noqa: BLE001 - a session without settings keeps normal orbit
        return False, False


def remember_orbit_inversion(invert_x: bool, invert_y: bool) -> None:
    """Share this dialog's choice with the other resident preview surfaces."""

    from PySide6.QtCore import QSettings

    try:
        settings = QSettings(_SETTINGS_SCOPE, _SETTINGS_SCOPE)
        settings.setValue(_ORBIT_X_SETTING, bool(invert_x))
        settings.setValue(_ORBIT_Y_SETTING, bool(invert_y))
    except Exception:  # noqa: BLE001 - not remembering is not worth an error
        pass


#: the swatch for the particles themselves, which have no one colour: the warm orange
#: most of the shipped effects land on
PARTICLE_TINT = (0.75, 0.25, 0.05)


def swatch(tint: Sequence[float]) -> str:
    """One of the scene's own colours as a small square of HTML, so the legend cannot
    drift from what the viewport draws."""

    red, green, blue = (max(0, min(255, int(round(255 * float(channel) ** (1 / 2.2))))) for channel in tuple(tint)[:3])
    return f'<span style="color:#{red:02x}{green:02x}{blue:02x}">&#9632;</span>'


class PlacementFrame:
    """The frame the dialog's numbers cross: the scene is the character's frame when a
    character stands in it (the item and anchor are baked through `rotation`, the 3x3
    that turns the item into the hand), and the item's own frame when it is not. Offsets
    and Euler turns are held in the item's frame -- the frame the game's
    ``_offsetTransform`` applies in -- and converted at the viewport's edge."""

    def __init__(self, rotation: Optional[Sequence[float]] = None) -> None:
        self.rotation: Optional[Tuple[float, ...]] = tuple(float(v) for v in rotation) if rotation is not None else None

    def to_scene_point(self, point: Sequence[float]) -> Vec3:
        if self.rotation is None:
            return tuple(float(v) for v in tuple(point)[:3])  # type: ignore[return-value]
        from cdmw.services.effect_character_reference import rotate_point

        return rotate_point(point, self.rotation)

    def from_scene_point(self, point: Sequence[float]) -> Vec3:
        if self.rotation is None:
            return tuple(float(v) for v in tuple(point)[:3])  # type: ignore[return-value]
        from cdmw.services.effect_character_reference import unrotate_point

        return unrotate_point(point, self.rotation)

    def to_scene_euler(self, degrees: Sequence[float]) -> Vec3:
        from cdmw.services.effect_placement_rotation import euler_item_to_scene

        return euler_item_to_scene(degrees, self.rotation)

    def from_scene_euler(self, degrees: Sequence[float]) -> Vec3:
        from cdmw.services.effect_placement_rotation import euler_scene_to_item

        return euler_scene_to_item(degrees, self.rotation)
