"""Immutable weapon-swap template contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True, slots=True)
class WeaponSwapSocketRow:
    name: str
    parent: str
    rotation: Tuple[float, float, float, float]
    translation: Tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class WeaponSwapTemplate:
    template_id: str
    label: str
    description: str
    supported_scopes: Tuple[str, ...]
    supported_weapon_classes: Tuple[str, ...]
    risk_level: str = "stable"
    socket_rows: Tuple[WeaponSwapSocketRow, ...] = ()
    weapon_socket_rows: Tuple[WeaponSwapSocketRow, ...] = ()
    touches_iteminfo: bool = False
    touches_paac: bool = False
    touches_hkx: bool = False
    includes_motion_aliases: bool = False
    advanced_only: bool = False


@dataclass(frozen=True, slots=True)
class WeaponSwapValidatedWeapon:
    display_name: str
    model_stem: str
    sheath_stem: str = ""
    note: str = ""


__all__ = ["WeaponSwapSocketRow", "WeaponSwapTemplate", "WeaponSwapValidatedWeapon"]
