"""Explicit import decisions and deterministic, reviewable influence reduction."""

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class SkinningChoice:
    part_index: int
    policy: str = "preserve"
    capacity: int = 6
    # Empty means the complete verified template, never a guessed body.
    donor_parts: tuple[int, ...] = ()

    def __post_init__(self):
        if type(self.part_index) is not int or self.part_index < 0:
            raise ValueError("A skinning choice requires a valid imported part index.")
        if self.policy not in {"preserve", "transfer", "body_transfer", "reduce"}:
            raise ValueError("Choose imported weights, template transfer, or explicit reduction.")
        if self.capacity not in (4, 6):
            raise ValueError("The supported skeletal influence capacities are four and six.")
        if not isinstance(self.donor_parts, tuple) or any(type(index) is not int or index < 0 for index in self.donor_parts):
            raise ValueError("Donor part restrictions require immutable nonnegative part indices.")


@dataclass(frozen=True, slots=True)
class SkinningPartReport:
    part_index: int
    part_name: str
    policy: str
    target_path: str
    required_bones: tuple[str, ...] = ()
    reduced_vertices: int = 0
    maximum_removed_mass: float = 0.0
    over_one_percent: int = 0
    over_five_percent: int = 0
    removed_bones: tuple[str, ...] = ()
    maximum_normalization_change: float = 0.0
    maximum_quantization_change: float = 0.0
    donor_part_names: tuple[str, ...] = ()
    transfer_details: tuple[str, ...] = ()
    target_sha256: str = ""
    skeleton_path: str = ""
    skeleton_sha256: str = ""
    donor_path: str = ""

    def summary(self):
        if self.policy in {"transfer", "body_transfer"}:
            return (f"{self.part_name}: transfer from {self.donor_path or self.target_path}; review rigid pieces, close layers and distant surfaces. "
                    + " ".join(self.transfer_details))
        text = f"{self.part_name}: keep imported weights in game bind space."
        if self.policy == "reduce":
            text += (f" Reduced {self.reduced_vertices} vertices; maximum removed weight "
                     f"{self.maximum_removed_mass:.2%}; {self.over_one_percent} over 1%, "
                     f"{self.over_five_percent} over 5%. Removed bones: {', '.join(self.removed_bones) or 'none'}. "
                     f"Normalization change up to {self.maximum_normalization_change:.2%}.")
        return text + f" PAC byte quantization changes retained weights by up to {self.maximum_quantization_change:.2%}."


def normalized_influences(indices, weights):
    """Combine duplicates without discarding positive mass or accepting bad rows."""
    if len(indices) != len(weights) or not indices:
        raise ValueError("Skin weights require complete, nonempty influence rows.")
    merged = {}
    for joint, weight in zip(indices, weights, strict=True):
        if type(joint) is not int or joint < 0 or not math.isfinite(weight) or weight < 0:
            raise ValueError("Skin weights contain an invalid joint or weight.")
        if weight > 0:
            merged[joint] = merged.get(joint, 0.0) + weight
    total = sum(merged.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Skin weights have zero or invalid total weight.")
    return {joint: weight / total for joint, weight in merged.items()}


def reduce_influences(indices, weights, capacity, identities):
    """Return kept rows, removed mass/names and the separate normalization change."""
    merged = normalized_influences(indices, weights)
    ordered = sorted(merged, key=lambda joint: (-merged[joint], identities[joint], joint))
    kept, removed = ordered[:capacity], ordered[capacity:]
    mass = sum(merged[joint] for joint in removed)
    total = sum(merged[joint] for joint in kept)
    values = tuple(merged[joint] / total for joint in kept)
    change = max((abs(value - merged[joint]) for joint, value in zip(kept, values)), default=0.)
    return tuple(kept), values, mass, tuple(identities[joint] for joint in removed), change
