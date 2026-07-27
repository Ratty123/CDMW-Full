"""Files that travel with a mesh but are not referenced by the prefab.

A prefab points at a mesh and nothing else, yet the mesh's material and physics
live in separate files that the game finds by path convention: the same
relative path under a different role directory.

::

    character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001.pac
    character/modelproperty/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001.pac_xml
    character/bin__/meshphysics/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001.hkx

Measured over the shipped archives, 12,961 of 12,962 ``.pac`` files sit under a
``/model/`` directory; of those, 100% have the physics companion and 99.1% have
the material one. That is a strong enough convention to predict from, which
matters because retargeting a prefab's mesh does *not* bring these along -- the
new mesh's own companions apply instead, and a mesh missing one will render or
collide differently than expected.
"""

from __future__ import annotations

from dataclasses import dataclass

_MODEL_SEGMENT = "/model/"


@dataclass(frozen=True, slots=True)
class Companion:
    """A file the engine resolves from a mesh path by convention."""

    role: str
    path: str
    detail: str


# role -> (replacement directory segment, extension, what it controls)
_RULES: tuple[tuple[str, str, str, str], ...] = (
    ("Material", "/modelproperty/", ".pac_xml", "textures and material assignments"),
    ("Physics", "/bin__/meshphysics/", ".hkx", "collision shape"),
)


def _normalise(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().lstrip("/")


def companion_paths(mesh_path: str) -> tuple[Companion, ...]:
    """Where a mesh's companion files would live, by convention.

    Returns an empty tuple for anything that is not a mesh under a ``/model/``
    directory, since the convention says nothing about those.
    """
    path = _normalise(mesh_path)
    lowered = path.lower()
    if not lowered.endswith(".pac") or _MODEL_SEGMENT not in lowered:
        return ()
    stem = path[: path.rfind(".")]
    found: list[Companion] = []
    for role, segment, extension, detail in _RULES:
        index = stem.lower().find(_MODEL_SEGMENT)
        if index < 0:
            continue
        rebuilt = stem[:index] + segment + stem[index + len(_MODEL_SEGMENT) :]
        found.append(Companion(role=role, path=f"{rebuilt}{extension}", detail=detail))
    return tuple(found)


def companion_extensions() -> frozenset[str]:
    """Extensions worth indexing so companions can be checked for existence."""
    return frozenset(extension for _role, _segment, extension, _detail in _RULES)


__all__ = ["Companion", "companion_extensions", "companion_paths"]
