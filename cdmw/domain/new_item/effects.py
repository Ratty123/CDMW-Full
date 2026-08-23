"""Legacy effect stem shortlist kept for compatibility-only callers.

The guided library enumerates every shipped effect and derives its neutral label,
category and behavior mechanically. These records intentionally carry no display
label, proof claim, recommendation note or special starting scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True, slots=True)
class EffectPreset:
    label: str
    stem: str
    element: str
    proven: bool = False
    note: str = ""
    scale: float = 1.0


EFFECT_PRESETS: Tuple[EffectPreset, ...] = (
    EffectPreset("", "fx_cc_firesweapon_a__fire1", "fire"),
    EffectPreset("", "fx_cc_firesweapon_a__fire2", "fire"),
    EffectPreset("", "fx_fire_up_a__sword1", "fire"),
    EffectPreset("", "fx_fire_up_a__sword2", "fire"),
    EffectPreset("", "fx_hit_common_fire_attach_a_loop", "fire"),
    EffectPreset("", "fx_hit_common_ice_attach_a_loop", "ice"),
    EffectPreset("", "fx_hit_common_ice_attach_a_giant_loop", "ice"),
    EffectPreset("", "fx_body_lightning_loop_a__weaponr_titan_01", "lightning"),
    EffectPreset("", "fx_hit_common_lightning_attach_a_loop", "lightning"),
    EffectPreset("", "fx_body_lightning_loop_a__titan1", "lightning"),
    EffectPreset("", "fx_damian_weapon_b__punishdagger_lightning1", "lightning"),
    EffectPreset("", "fx_glow_weaponmesh_a__glow3", "glow"),
    EffectPreset("", "fx_caliburn_exp_c__swordon1", "glow"),
    EffectPreset("", "fx_caliburn_exp_c__swordtrail1", "glow"),
    EffectPreset("", "fx_antumbra_weapon_a__weapon1", "dark"),
    EffectPreset("", "fx_antumbra_weapon_a__weapon2", "dark"),
    EffectPreset("", "fx_antumbra_weapon_a__weapon3", "dark"),
    EffectPreset("", "fx_character_aura_a__aura13_loop", "aura"),
    EffectPreset("", "fx_character_aura_a__aura14_loop", "aura"),
    EffectPreset("", "fx_aura_ribbon_a__ribbon10_loop", "aura"),
    EffectPreset("", "fx_boss_weapon_a__trail1", "trail"),
    EffectPreset("", "fx_damian_weapon_a__trail_swing1", "trail"),
    EffectPreset("", "fx_gimmick_common_material_a__spark1_loop", "sparks"),
    EffectPreset("", "fx_gimmick_common_material_a__lightning1_loop", "lightning"),
)


def presets_for(available: "set[str] | frozenset[str] | None" = None) -> Tuple[EffectPreset, ...]:
    """The presets whose stems are among `available` (all of them when None)."""

    if available is None:
        return EFFECT_PRESETS
    wanted = {str(stem) for stem in available}
    return tuple(preset for preset in EFFECT_PRESETS if preset.stem in wanted)


__all__ = ["EFFECT_PRESETS", "EffectPreset", "presets_for"]
