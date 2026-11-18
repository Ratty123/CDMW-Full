"""One-time migrations of stored Preview settings."""

from __future__ import annotations

TEXTURES_SETTING_KEY = "archive/model_use_textures"
TEXTURES_DEFAULT_VERSION_KEY = "archive/model_use_textures_default_version"
# Version 1: textures are on by default (P3). Every settings save writes every
# field, so users who never chose "off" have `false` stored from the old
# default; they are moved to the new default once. The setting stays, so
# anyone can turn textures off again, and that choice is then kept.
TEXTURES_DEFAULT_VERSION = 1


LIGHTING_SETTING_KEY = "preview/preview_lighting_preset"
LIGHTING_DEFAULT_VERSION_KEY = "preview/preview_lighting_preset_default_version"
# Version 1: Studio (fixed lights) is the default and Game icon studio is retired.
# A profile that stored the old default (Neutral studio), Game icon studio or
# nothing moves to Studio (fixed lights) once; Showcase and Dark were chosen on
# purpose and are kept.
LIGHTING_DEFAULT_VERSION = 1


def migrate_lighting_to_studio(settings) -> bool:
    """Move the old default and the retired preset to Studio (fixed lights) once.

    Returns True when this call changed the stored value.
    """

    try:
        version = int(settings.value(LIGHTING_DEFAULT_VERSION_KEY, 0) or 0)
    except (TypeError, ValueError):
        version = 0
    if version >= LIGHTING_DEFAULT_VERSION:
        return False
    stored = str(settings.value(LIGHTING_SETTING_KEY, "") or "").strip().casefold()
    changed = False
    if stored in {"", "neutral_studio", "icon_studio"}:
        changed = stored != ""
        settings.setValue(LIGHTING_SETTING_KEY, "studio_fixed")
    settings.setValue(LIGHTING_DEFAULT_VERSION_KEY, LIGHTING_DEFAULT_VERSION)
    return changed


def migrate_textures_on_by_default(settings) -> bool:
    """Turn textures on once for profiles saved before the new default.

    Returns True when this call changed the stored value.
    """

    try:
        version = int(settings.value(TEXTURES_DEFAULT_VERSION_KEY, 0) or 0)
    except (TypeError, ValueError):
        version = 0
    if version >= TEXTURES_DEFAULT_VERSION:
        return False
    stored = settings.value(TEXTURES_SETTING_KEY, None)
    changed = str(stored).strip().casefold() not in {"true", "1"} if stored is not None else False
    settings.setValue(TEXTURES_SETTING_KEY, True)
    settings.setValue(TEXTURES_DEFAULT_VERSION_KEY, TEXTURES_DEFAULT_VERSION)
    return changed
