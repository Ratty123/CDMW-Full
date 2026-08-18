"""Curated weapon-effect presets: shipped effect binaries worth trying on a weapon.

The studio can graft any of the 6,294 shipped `.pae` effects into an item's prefabs
as a persistent `EffectComponent`; most of them are impacts, gimmicks and scenery.
These are the ones named for weapons or bodies, grouped by element, so a reader has
somewhere to start. `proven` marks the ones seen drawing on a weapon in game
(fire, 2026-08-18: `fx_cc_firesweapon_a__fire1` drew flames on the sword in the shop
preview). One-shot effects (`_hit_`, `_cast`, `..._lightning1`) flash once when the
weapon appears and then nothing; persistent ones say `loop`, `attach`, `aura` or
`weapon` in their names.

An on-hit effect (an explosion or a shock on the ground when the blade lands) is not
a prefab matter: the game plays those from its combat data, per attack and per
surface (`fx_hit_swordlong_grass_a`, ...), and no item-row field names one. That
stays outside the studio until that data is decoded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True, slots=True)
class EffectPreset:
    label: str
    stem: str
    element: str
    #: seen drawing on a weapon in game
    proven: bool = False
    note: str = ""
    #: a starting uniform scale: effects authored for bigger weapons reach past a sword at 1.0
    #: (the titan's weapon lightning ran metres past the blade, the fire sweep past the tip)
    scale: float = 1.0


EFFECT_PRESETS: Tuple[EffectPreset, ...] = (
    EffectPreset("Fire: flames along the blade", "fx_cc_firesweapon_a__fire1", "fire", proven=True, note="the phase 7 fire check; flames on the sword in the shop preview, reaching past a one-hand blade at 1.0", scale=0.6),
    EffectPreset("Fire: larger flames", "fx_cc_firesweapon_a__fire2", "fire", scale=0.6),
    EffectPreset("Fire: rising fire (sword 1)", "fx_fire_up_a__sword1", "fire"),
    EffectPreset("Fire: rising fire (sword 2)", "fx_fire_up_a__sword2", "fire"),
    EffectPreset("Fire: burning attach loop", "fx_hit_common_fire_attach_a_loop", "fire", note="the burning-status visual the game attaches to a body"),
    EffectPreset("Frost: frozen attach loop", "fx_hit_common_ice_attach_a_loop", "ice", note="the frozen-status visual the game attaches to a body"),
    EffectPreset("Frost: giant frozen attach loop", "fx_hit_common_ice_attach_a_giant_loop", "ice", scale=0.3),
    EffectPreset("Lightning: titan weapon loop", "fx_body_lightning_loop_a__weaponr_titan_01", "lightning", note="the arcs the titan's right-hand weapon carries; the phase 8 J check ran metres past a sword at 1.0", scale=0.2),
    EffectPreset("Lightning: shocked attach loop", "fx_hit_common_lightning_attach_a_loop", "lightning"),
    EffectPreset("Lightning: titan body loop", "fx_body_lightning_loop_a__titan1", "lightning", scale=0.2),
    EffectPreset("Lightning: Damian's dagger strike (flashes once)", "fx_damian_weapon_b__punishdagger_lightning1", "lightning", note="one-shot; the phase 7 lightning check struck once when the weapon appeared"),
    EffectPreset("Glow: weapon mesh glow", "fx_glow_weaponmesh_a__glow3", "glow"),
    EffectPreset("Glow: Caliburn sword on", "fx_caliburn_exp_c__swordon1", "glow"),
    EffectPreset("Glow: Caliburn sword trail", "fx_caliburn_exp_c__swordtrail1", "glow"),
    EffectPreset("Dark: Antumbra weapon 1", "fx_antumbra_weapon_a__weapon1", "dark"),
    EffectPreset("Dark: Antumbra weapon 2", "fx_antumbra_weapon_a__weapon2", "dark"),
    EffectPreset("Dark: Antumbra weapon 3", "fx_antumbra_weapon_a__weapon3", "dark"),
    EffectPreset("Aura: character aura loop 13", "fx_character_aura_a__aura13_loop", "aura"),
    EffectPreset("Aura: character aura loop 14", "fx_character_aura_a__aura14_loop", "aura"),
    EffectPreset("Aura: ribbon loop", "fx_aura_ribbon_a__ribbon10_loop", "aura"),
    EffectPreset("Trail: boss weapon trail", "fx_boss_weapon_a__trail1", "trail"),
    EffectPreset("Trail: Damian swing trail", "fx_damian_weapon_a__trail_swing1", "trail"),
    EffectPreset("Sparks: friction spark loop", "fx_gimmick_common_material_a__spark1_loop", "sparks"),
    EffectPreset("Sparks: lightning gimmick loop", "fx_gimmick_common_material_a__lightning1_loop", "lightning"),
)


def presets_for(available: "set[str] | frozenset[str] | None" = None) -> Tuple[EffectPreset, ...]:
    """The presets whose stems are among `available` (all of them when None)."""

    if available is None:
        return EFFECT_PRESETS
    wanted = {str(stem) for stem in available}
    return tuple(preset for preset in EFFECT_PRESETS if preset.stem in wanted)


__all__ = ["EFFECT_PRESETS", "EffectPreset", "presets_for"]
