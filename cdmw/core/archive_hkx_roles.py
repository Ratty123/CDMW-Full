"""Shared simulation-role classification for decoded HKX and companion descriptors."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Tuple


_HKX_SIMULATION_ROLE_DESCRIPTIONS: dict[str, str] = {
    "hair": (
        "Inferred hair physics guide. This is based on names/materials/descriptor paths and shows likely strands, "
        "joints, or soft collision guides; it is not a Havok solver result."
    ),
    "cloth": (
        "Inferred cloth or flexible attachment guide. Damping, inertia, and constraint limits are useful edit targets "
        "for swing/jiggle behavior, but the viewport only shows a debug envelope."
    ),
    "body_soft": (
        "Inferred soft body-part physics guide, such as chest/hip/body jiggle attachments. Treat stiffness, damping, "
        "and motor/friction values as experimental tuning controls."
    ),
    "attachment": (
        "Inferred dynamic attachment guide, such as a lantern, strap, prop, or sliding secondary body. This is useful "
        "for visualizing body-to-socket constraints even when it is not cloth or hair."
    ),
    "ragdoll": (
        "Inferred ragdoll or articulated body guide. Constraint lines usually describe body-to-bone or body-to-body "
        "limits rather than cloth simulation."
    ),
    "collision": "Decoded collision shape or generic physics body with no stronger cloth/hair/body-soft hint.",
}


def _hkx_simulation_role_description(role: object) -> str:
    return _HKX_SIMULATION_ROLE_DESCRIPTIONS.get(
        str(role or "collision"),
        _HKX_SIMULATION_ROLE_DESCRIPTIONS["collision"],
    )


def _hkx_simulation_role_from_parts(*parts: object) -> str:
    text_parts: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, Mapping):
            text_parts.extend(str(value) for value in part.values())
        elif isinstance(part, (list, tuple, set)):
            text_parts.extend(str(value) for value in part)
        else:
            text_parts.append(str(part))
    text = " ".join(text_parts).casefold()
    if not text:
        return "collision"
    hair_tokens = ("hair", "pony", "bang", "tailhair", "braid")
    cloth_tokens = ("cloth", "cloak", "cape", "skirt", "dress", "sleeve", "hem", "ribbon", "fur", "tail")
    body_soft_tokens = ("nude", "body", "breast", "chest", "bust", "hip", "butt", "belly", "pelvis", "thigh")
    attachment_tokens = ("sliding", "lantern", "strap", "prop", "socket", "pendant", "earring")
    ragdoll_tokens = ("ragdoll", "hinge", "constraint", "capsule", "bone", "skeleton")
    if any(token in text for token in hair_tokens):
        return "hair"
    if any(token in text for token in cloth_tokens):
        return "cloth"
    if any(token in text for token in body_soft_tokens):
        return "body_soft"
    if any(token in text for token in attachment_tokens):
        return "attachment"
    if any(token in text for token in ragdoll_tokens):
        return "ragdoll"
    return "collision"


def _hkx_simulation_role_counts(*groups: Sequence[object]) -> Tuple[Tuple[str, int], ...]:
    counter: Counter[str] = Counter()
    for group in groups:
        for item in group:
            role = str(getattr(item, "simulation_role", "") or "").strip()
            if role and role != "collision":
                counter[role] += 1
    return tuple(sorted(counter.items()))


__all__ = [
    "_HKX_SIMULATION_ROLE_DESCRIPTIONS",
    "_hkx_simulation_role_counts",
    "_hkx_simulation_role_description",
    "_hkx_simulation_role_from_parts",
]
