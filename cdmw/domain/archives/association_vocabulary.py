"""The vocabulary that turns file names into links, derived from the manifest.

Associated assets kept a hand-written alternation of the formats it would follow
while the preview pane read `schemas/archive_content_capabilities.v1.json`, so
the two disagreed about what a file points at: the preview would report that a
level names `world/mesh.pat` and the drawer would not list it. Deriving the
pattern and the companion suffixes from the one manifest means a format the
registry already knows becomes linkable without editing a second list.

Texture variant naming is deliberately not derived here. The manifest registers
formats, not authoring conventions, and `_ARCHIVE_TEXTURE_FAMILY_SUFFIXES` in
`cdmw/core/archive_model_references.py` already owns the Crimson Desert suffix
vocabulary that texture lookups share.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import FrozenSet, Pattern, Tuple

from cdmw.domain.archives.content_capabilities import (
    capability_for,
    load_capabilities,
    normalize_extension,
    registered_extensions,
)

# Sidecar suffixes the manifest cannot express because they carry two extensions:
# the dotted twins of the underscore `_xml` sidecars, and the socket sidecar that
# only ever appears dotted. A reference to one still parses without them, because
# the reference pattern treats a dot as a path separator, but stripping a family
# stem needs the whole suffix in one piece.
COMPOSITE_FAMILY_SUFFIXES: Tuple[str, ...] = (
    ".prefabdata.xml",
    ".prefab.xml",
    ".pamlod.xml",
    ".pac.xml",
    ".pam.xml",
    ".app.xml",
    ".sockets.xml",
)

# Groups whose members share a stem with the mesh they were authored beside.
# Textures are excluded because they carry variant suffixes and are expanded by
# the texture family rules instead, and media and loose text are excluded because
# a shared stem there is a coincidence rather than a family.
_FAMILY_GROUPS: FrozenSet[str] = frozenset(
    {"model_mesh_physics", "material_metadata", "animation_scene"}
)

# A reference alternation entry shorter than this matches too much of the noise in
# a decoded binary to be worth following.
_MINIMUM_REFERENCE_EXTENSION_LENGTH = 4

# The headers Associated Assets files its rows under, in reading order. The panel
# and the dialog both render only the groups named here, so a row whose group is
# absent is computed and then never shown: this tuple is the one place that list
# lives, rather than a copy per surface that a new group has to be added to.
ASSET_FAMILY_GROUP_ORDER: Tuple[str, ...] = (
    "Selected Model",
    "Attachment / Placement",
    "Material",
    "Textures",
    "Item Icons",
    "Physics / HKX",
    "MeshInfo",
    "Prefab / Metadata",
    "Skeleton / Rig",
    "Animation / Motion",
    "Audio / Video",
    "Other",
)


@lru_cache(maxsize=1)
def family_suffixes() -> Tuple[str, ...]:
    """Suffixes a same-name asset family can carry, longest first.

    Longest first is what makes stem stripping remove the most specific suffix a
    name ends with, so `armor.prefabdata.xml` loses the whole sidecar suffix
    rather than just its `.xml`.
    """

    suffixes = {
        capability.extension
        for capability in load_capabilities()
        if capability.group in _FAMILY_GROUPS or capability.role == "metadata"
    }
    suffixes.update(COMPOSITE_FAMILY_SUFFIXES)
    return tuple(sorted(suffixes, key=lambda suffix: (-len(suffix), suffix)))


@lru_cache(maxsize=1)
def reference_container_extensions() -> FrozenSet[str]:
    """Formats worth decoding to look for the names of other files inside them.

    Anything the manifest says can name another file, minus the formats whose
    payload is pixels or samples: scanning those for text finds noise, never a
    reference. A Wwise bank is the exception, because its media table names the
    sounds that play with it.
    """

    return frozenset(
        capability.extension
        for capability in load_capabilities()
        if capability.references
        and capability.group != "texture_image"
        and (capability.group != "audio_video" or capability.extension == ".bnk")
    )


@lru_cache(maxsize=1)
def asset_reference_pattern() -> Pattern[str]:
    """Matches a file name of a registered format inside decoded text.

    A dot separates path segments here as much as a slash does, so a name never
    has to be guessed apart from the suffix that follows it, and a two-extension
    sidecar still matches whole. The alternation runs longest first and the match
    ends on a guard, because a name was otherwise clipped onto the shorter
    registered format it starts with: `city.paccd` read as `city.pac` and
    `crate.prefab_xml` as `crate.prefab`. Where a file of the clipped name
    existed, the drawer listed it in place of the real one with full confidence,
    which is worse than finding nothing.
    """

    alternation = "|".join(
        re.escape(extension[1:])
        for extension in registered_extensions()
        if len(extension) >= _MINIMUM_REFERENCE_EXTENSION_LENGTH
    )
    return re.compile(
        r"((?:[A-Za-z0-9_@%+\-]+[./\\])*[A-Za-z0-9_@%+\-]+\.(?:"
        + alternation
        + r"))(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )


def strip_family_suffix(basename: str) -> str:
    """The family stem of a name, with the most specific registered suffix removed."""

    text = str(basename or "").strip()
    lowered = text.lower()
    for suffix in family_suffixes():
        if lowered.endswith(suffix):
            return text[: -len(suffix)]
    return text


def asset_family_group_from_manifest(extension: str) -> str:
    """The Associated Assets group a registered format belongs to.

    This is the fallback the classifier reaches when no named rule matches, so a
    format the manifest registers reaches the group a reader expects instead of
    falling into "Other". Level, route, and gimmick data all describe a scene
    rather than a mesh, which is what the prefab and metadata group already
    covers.
    """

    capability = capability_for(extension)
    if capability is None:
        return "Other"
    if capability.group == "texture_image":
        return "Textures"
    # Role decides ahead of group, because the manifest files prefab, level and
    # gimmick metadata under `material_metadata` alongside the material sidecars.
    # Reading that group as "Material" would file a level under the wrong header;
    # the named sidecar rules upstream have already claimed the real sidecars by
    # the time this fallback runs.
    return {
        "model": "Selected Model",
        "physics": "Physics / HKX",
        "animation": "Animation / Motion",
        "metadata": "Prefab / Metadata",
        "image": "Textures",
        "audio": "Audio / Video",
        "video": "Audio / Video",
    }.get(capability.role, "Other")


def asset_family_role_from_manifest(extension: str) -> str:
    """The Associated Assets role label a registered format carries."""

    capability = capability_for(extension)
    if capability is None:
        return "Related File"
    if capability.group == "texture_image" or capability.role == "image":
        return "Texture"
    return {
        "model": "Model",
        "physics": "HKX / Physics",
        "animation": "Animation / Motion",
        "metadata": "Prefab / Metadata",
        "audio": "Audio / Video",
        "video": "Audio / Video",
    }.get(capability.role, "Related File")


def is_reference_container_extension(extension: str) -> bool:
    return normalize_extension(extension) in reference_container_extensions()


__all__ = [
    "ASSET_FAMILY_GROUP_ORDER",
    "COMPOSITE_FAMILY_SUFFIXES",
    "asset_family_group_from_manifest",
    "asset_family_role_from_manifest",
    "asset_reference_pattern",
    "family_suffixes",
    "is_reference_container_extension",
    "reference_container_extensions",
    "strip_family_suffix",
]
