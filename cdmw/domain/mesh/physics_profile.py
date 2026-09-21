"""Reversible raw XML profile edits; no preview coefficients are persisted."""

from collections.abc import Mapping
from dataclasses import dataclass
import math
from pathlib import PurePosixPath
import re


PROFILE_VALUE_RANGES = {
    "StretchingStiffness": (0., 1.), "BendingStiffness": (0., 1.),
    "Damping": (0., 10.), "Gravity": (-100., 100.),
    "SolverIterationCount": (1, 64), "UseVertexAlphaPositionBlending": (0, 1),
    "UseRotationCorrection": (0, 1),
    "IsCloak": (0, 1), "UseBackStopCollision": (0, 1),
    "UseInputPositionCollision": (0, 1), "ShrinkWhenShieldIsInSocket": (0, 1),
    "UseLraConstraint": (0, 1),
}


def validate_profile_values(values):
    if (not isinstance(values, tuple) or not 1 <= len(values) <= len(PROFILE_VALUE_RANGES)
            or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in values)):
        raise ValueError("Invalid physics profile settings.")
    seen = set()
    for key, value in values:
        if not isinstance(key, str) or key not in PROFILE_VALUE_RANGES or key in seen:
            raise ValueError("Invalid physics profile settings.")
        seen.add(key)
        low, high = PROFILE_VALUE_RANGES[key]
        if (type(value) not in (float, int) or not low <= value <= high or not math.isfinite(value)
                or (key in {"SolverIterationCount", "UseVertexAlphaPositionBlending", "UseRotationCorrection",
                            "IsCloak", "UseBackStopCollision", "UseInputPositionCollision",
                            "ShrinkWhenShieldIsInSocket", "UseLraConstraint"}
                    and value != int(value))):
            raise ValueError("Invalid physics profile settings.")


@dataclass(frozen=True, slots=True)
class PacPhysicsProfileRule:
    variant: str
    source_profile: str
    source_path: str
    source_sha256: str
    values: tuple[tuple[str, float | int], ...]

    def __post_init__(self):
        path = PurePosixPath(self.source_path) if isinstance(self.source_path, str) else None
        if (not isinstance(self.variant, str) or len(self.variant) > 64
                or not isinstance(self.source_profile, str) or not 1 <= len(self.source_profile) <= 256
                or path is None or len(self.source_path) > 1024 or not self.source_path.casefold().startswith("character/descriptors/pbd/")
                or path.suffix.casefold() != ".xml" or ".." in path.parts
                or any(char in self.source_path for char in ("\\", ":", "\x00"))
                or str(path) != self.source_path
                or not isinstance(self.source_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None):
            raise ValueError("Invalid physics profile source identity.")
        validate_profile_values(self.values)

    def to_dict(self):
        return {"variant": self.variant, "source_profile": self.source_profile,
                "source_path": self.source_path, "source_sha256": self.source_sha256,
                "values": dict(self.values)}

    @classmethod
    def from_dict(cls, payload):
        if (not isinstance(payload, Mapping) or set(payload) != {
                "variant", "source_profile", "source_path", "source_sha256", "values"}
                or not isinstance(payload["values"], Mapping)
                or any(not isinstance(key, str) for key in payload["values"])):
            raise ValueError("Invalid physics profile settings.")
        return cls(payload["variant"], payload["source_profile"], payload["source_path"],
                   payload["source_sha256"], tuple(sorted(payload["values"].items())))
