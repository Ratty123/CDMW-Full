"""Which held modifier hands the left mouse button to the preview camera.

An edit tool owns the left button while it is active, so a modifier is the only
way to orbit or pan without dropping the tool. Both are rebindable; this module
is the single place that says which values are legal and what happens when the
two bindings collide.
"""

from __future__ import annotations

from typing import Final


ALT: Final = "alt"
CTRL: Final = "ctrl"
SHIFT: Final = "shift"
ALT_OR_CTRL: Final = "alt_or_ctrl"

# Ctrl is the binding the Mesh Editor shipped with and Alt is the one every
# other mesh application uses, so the default orbit binding honours both.
DEFAULT_ORBIT: Final = ALT_OR_CTRL
DEFAULT_PAN: Final = SHIFT

CAMERA_MODIFIER_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ALT_OR_CTRL, "Alt or Ctrl"),
    (ALT, "Alt"),
    (CTRL, "Ctrl"),
    (SHIFT, "Shift"),
)

# What dragging with the middle button (the scroll wheel, held down) or the
# right button does. Unlike the modifiers above these cannot collide with
# anything: each is its own physical button, and pan and orbit both stay
# reachable through the left button's modifiers whatever is chosen here.
DRAG_PAN: Final = "pan"
DRAG_ORBIT: Final = "orbit"

DEFAULT_MIDDLE_DRAG: Final = DRAG_PAN
DEFAULT_RIGHT_DRAG: Final = DRAG_PAN

CAMERA_DRAG_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (DRAG_PAN, "Pan"),
    (DRAG_ORBIT, "Orbit"),
)

_VALUES: Final[frozenset[str]] = frozenset(value for value, _ in CAMERA_MODIFIER_CHOICES)
_DRAG_VALUES: Final[frozenset[str]] = frozenset(value for value, _ in CAMERA_DRAG_CHOICES)

# The physical keys each binding claims. Overlap is what makes a pair unusable:
# the viewport tests pan before orbit, so a shared key would silently pan and
# the orbit binding would look broken rather than conflicting.
_KEYS: Final[dict[str, frozenset[str]]] = {
    ALT: frozenset({ALT}),
    CTRL: frozenset({CTRL}),
    SHIFT: frozenset({SHIFT}),
    ALT_OR_CTRL: frozenset({ALT, CTRL}),
}


def normalize_camera_modifier(value: object, fallback: str) -> str:
    """Coerce a stored or wire value to a legal binding."""

    text = str(value or "").strip().lower()
    if text in _VALUES:
        return text
    return fallback if fallback in _VALUES else DEFAULT_ORBIT


def normalize_camera_drag(value: object, fallback: str) -> str:
    """Coerce a stored or wire value to a legal drag-button binding."""

    text = str(value or "").strip().lower()
    if text in _DRAG_VALUES:
        return text
    return fallback if fallback in _DRAG_VALUES else DRAG_PAN


def camera_drag_label(value: str) -> str:
    for candidate, label in CAMERA_DRAG_CHOICES:
        if candidate == value:
            return label
    return camera_drag_label(DRAG_PAN)


def camera_modifier_label(value: str) -> str:
    for candidate, label in CAMERA_MODIFIER_CHOICES:
        if candidate == value:
            return label
    return camera_modifier_label(DEFAULT_ORBIT)


def camera_bindings_conflict(orbit: str, pan: str) -> bool:
    """True when the two bindings share a physical key."""

    return bool(
        _KEYS.get(normalize_camera_modifier(orbit, DEFAULT_ORBIT), frozenset())
        & _KEYS.get(normalize_camera_modifier(pan, DEFAULT_PAN), frozenset())
    )


def resolve_camera_bindings(orbit: object, pan: object) -> tuple[str, str]:
    """Return a legal, non-overlapping (orbit, pan) pair.

    Pan is treated as the fixed one because the viewport tests it first, so a
    colliding orbit binding is the one that would never fire. When they clash,
    orbit moves to the first choice that does not, which keeps a rebind that the
    user is halfway through from leaving the camera with no orbit key at all.
    """

    resolved_pan = normalize_camera_modifier(pan, DEFAULT_PAN)
    resolved_orbit = normalize_camera_modifier(orbit, DEFAULT_ORBIT)
    if not camera_bindings_conflict(resolved_orbit, resolved_pan):
        return resolved_orbit, resolved_pan
    for candidate, _ in CAMERA_MODIFIER_CHOICES:
        if not camera_bindings_conflict(candidate, resolved_pan):
            return candidate, resolved_pan
    # Unreachable while the choices span more than one physical key, but a
    # silent same-key pair would be worse than an obviously wrong default.
    return DEFAULT_ORBIT, DEFAULT_PAN
