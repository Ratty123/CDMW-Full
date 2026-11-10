"""Check that a cloth-painted model is complete before it leaves Create New Item.

Cloth works in game only when three things agree: the PAC holds a cloth guide
mesh, every cloth vertex names guides that exist, and the material file gives
each cloth part a cloth profile the game's catalogue resolves. A model that
misses one of them still loads, and its cloth then hangs still or stretches
away, so each is checked here instead of being left to an in-game test.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

CATALOGUE_PATH = "character/descriptors/pbd/pbdconfig.xml"
PROFILE_ATTRIBUTE = "_pbdSimulationMaterialName"


@dataclass(frozen=True, slots=True)
class PaintedClothCheck:
    #: parts with at least one cloth vertex, in PAC order
    cloth_parts: tuple[str, ...]
    guide_count: int
    cloth_vertices: int
    #: (cloth part name, profile) for every material owner of a cloth part
    profiles: tuple[tuple[str, str], ...] = ()
    #: archive paths of the profile documents those names resolve to
    profile_paths: tuple[str, ...] = ()


def painted_cloth_parts(pac: bytes) -> PaintedClothCheck:
    """Read every cloth vertex of every LOD against the PAC's own guide mesh."""
    from cdmw.modding.pac_cloth import pac_cloth_binding, pac_cloth_lods
    from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides

    bound = []
    for lod, level in enumerate(pac_cloth_lods(pac)):
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                binding = pac_cloth_binding(pac, offset)
                if binding is not None:
                    bound.append((lod, part.name, binding[1]))
    if not bound:
        # Nothing follows guides, so whether this layout can hold any does not matter.
        return PaintedClothCheck((), 0, 0)
    guides = decode_pac_cloth_guides(pac)
    count = len(guides.vertices) if guides is not None else 0
    names: list[str] = []
    for lod, name, indices in bound:
        # The game fetches all four guides of a cloth vertex, also those weighted zero.
        if any(index >= count for index in indices):
            raise ValueError(f"{name} has cloth vertices at LOD {lod} that follow cloth guides the model "
                             f"does not have (it has {count}).")
        if name not in names:
            names.append(name)
    return PaintedClothCheck(tuple(names), count, len(bound))


def cloth_part_profiles(material: bytes, parts: Sequence[str]) -> tuple[tuple[str, str], ...]:
    """The cloth profile every material owner of ``parts`` names; each must name one.

    A part may appear under more than one owner (the material file's variants), and
    those may name different profiles, as shipped files do.
    """
    from cdmw.modding.pbd_profile_edit import ProfileXml

    document = ProfileXml(material)
    found: list[tuple[str, str]] = []
    missing, empty = [], []
    for name in parts:
        nodes = [node for node in document.nodes if node.attributes.get("_subMeshName", "").casefold() == name.casefold()]
        if not nodes:
            missing.append(name)
            continue
        for node in nodes:
            profile = document.owner(node).attributes.get(PROFILE_ATTRIBUTE, "")
            if not profile:
                if name not in empty:
                    empty.append(name)
            elif (name, profile) not in found:
                found.append((name, profile))
    if missing:
        raise ValueError(f"The material file has no entry for cloth part(s): {', '.join(sorted(missing))}.")
    if empty:
        raise ValueError(f"The template gives {', '.join(sorted(empty))} no cloth profile, so the new cloth would not move. "
                         "Choose a cloth profile.")
    return tuple(found)


def profile_document_paths(catalogue: bytes, profiles: Sequence[str]) -> tuple[str, ...]:
    """Archive paths of every document ``profiles`` name in the game's catalogue."""
    from cdmw.core.pbd_cloth import collect_pbd_config_materials
    from cdmw.services.mesh_physics_profiles import _profile_path, _xml_text

    by_name: dict[str, list] = {}
    for row in collect_pbd_config_materials(_xml_text(catalogue)):
        by_name.setdefault(row.name.casefold(), []).append(row)
    paths: list[str] = []
    for profile in dict.fromkeys(profiles):
        matches = by_name.get(profile.casefold(), ())
        if not matches:
            raise ValueError(f"The cloth profile {profile} is not in the game's profile catalogue.")
        for row in matches:
            path = _profile_path(row.filename).casefold()
            if path not in paths:
                paths.append(path)
    return tuple(paths)


def verify_painted_cloth(pac: bytes, material: bytes | None, *, catalogue: bytes | None = None) -> PaintedClothCheck:
    """Guides, bindings and profiles of one cloth-painted model, or ValueError saying what is missing.

    Without ``catalogue`` the profile names are required but not resolved.
    """
    check = painted_cloth_parts(pac)
    if not check.cloth_parts:
        return check
    if material is None:
        raise ValueError("the imported build carries no material file to give its new cloth a profile")
    profiles = cloth_part_profiles(material, check.cloth_parts)
    paths = profile_document_paths(catalogue, [profile for _name, profile in profiles]) if catalogue is not None else ()
    return PaintedClothCheck(check.cloth_parts, check.guide_count, check.cloth_vertices, profiles, paths)


__all__ = [
    "CATALOGUE_PATH",
    "PROFILE_ATTRIBUTE",
    "PaintedClothCheck",
    "cloth_part_profiles",
    "painted_cloth_parts",
    "profile_document_paths",
    "verify_painted_cloth",
]
