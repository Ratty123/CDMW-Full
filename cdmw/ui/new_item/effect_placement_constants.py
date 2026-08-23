"""Shared numeric and camera constants for New Item effect placement."""

REACH_HIDDEN_ABOVE = 6.0

# Three decimals preserve small fit-to-item scales without a later edit rounding them.
SCALE_MINIMUM = 0.01
SCALE_MAXIMUM = 10.0
SCALE_DECIMALS = 3

# Front, side, top and the opening three-quarter view, as yaw/pitch degrees.
STANDING_VIEW_ANGLES: tuple[tuple[float, float], ...] = (
    (0.0, 8.0),
    (90.0, 8.0),
    (0.0, -80.0),
    (-35.0, 20.0),
)

ROTATION_DECIMALS = 1
ROTATION_STEP = 5.0
