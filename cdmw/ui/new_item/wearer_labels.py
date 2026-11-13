"""Translated names for who wears a template (P8), shared by the Template page's controls.

The wearer kinds themselves are in ``cdmw.domain.new_item.wearer_kinds``; this module
only gives them their interface words, as literal ``tr`` calls so the localization
scanner sees every one.
"""

from cdmw.domain.new_item.wearer_kinds import (
    KIND_CREATURE_MOUNT,
    KIND_DRAGON,
    KIND_HORSE,
    KIND_PET,
    KIND_PLAYER,
    KIND_SHIP,
    KIND_WAGON,
    KIND_WAR_MACHINE,
)
from cdmw.services.active_ui_translation import translate_active_ui_text as tr


def kind_label(kind: str) -> str:
    """The kind as a category: "Horse gear", "Ship parts"."""

    return {
        KIND_PLAYER: lambda: tr('Characters'),
        KIND_HORSE: lambda: tr('Horse gear'),
        KIND_PET: lambda: tr('Pet gear'),
        KIND_CREATURE_MOUNT: lambda: tr('Creature mount gear'),
        KIND_DRAGON: lambda: tr('Dragon gear'),
        KIND_SHIP: lambda: tr('Ship parts'),
        KIND_WAGON: lambda: tr('Wagon parts'),
        KIND_WAR_MACHINE: lambda: tr('War machine parts'),
    }.get(kind, lambda: tr('Characters'))()


def wearer_label(kind: str) -> str:
    """Who wears that kind, in a sentence: "horse breeds", "ship hulls"."""

    return {
        KIND_PLAYER: lambda: tr('characters'),
        KIND_HORSE: lambda: tr('horse breeds'),
        KIND_PET: lambda: tr('pets'),
        KIND_CREATURE_MOUNT: lambda: tr('creatures'),
        KIND_DRAGON: lambda: tr('dragons'),
        KIND_SHIP: lambda: tr('ship hulls'),
        KIND_WAGON: lambda: tr('wagons'),
        KIND_WAR_MACHINE: lambda: tr('war machines'),
    }.get(kind, lambda: tr('characters'))()


__all__ = ["kind_label", "wearer_label"]
