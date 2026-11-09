"""Give an imported model its own cloth guides, built from its cloth paint and pins.

The alternative to binding paint to the template's guides (``new_item_cloth_paint``):
the template's guide mesh is removed and a new one is built from the painted area
of the built PAC, held where the paint meets unpainted vertices and at painted
pins. The parts that end up carrying cloth need a cloth profile in the material
sidecar, either the template's own assignment or one chosen from the game's
profile catalogue.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from cdmw.modding.pac_cloth_paint import ClothPaintSamples
from cdmw.services.new_item_cloth_paint import SAMPLE_TOLERANCE, _apply_row_matrix, mesh_has_cloth_paint, part_cloth_paint

PROFILE_ATTRIBUTE = "_pbdSimulationMaterialName"
CATALOGUE_PATH = "character/descriptors/pbd/pbdconfig.xml"


def part_cloth_pins(part) -> list[bool]:
    pins = list(getattr(part, "cloth_pin", ()) or ())
    if len(pins) != len(getattr(part, "vertices", ()) or ()):
        return []
    return [bool(pin) for pin in pins]


def mesh_has_cloth_pins(mesh) -> bool:
    return any(any(part_cloth_pins(part)) for part in getattr(mesh, "submeshes", ()) or ())


def import_cloth_samples(mesh, matrix: Sequence[float]) -> ClothPaintSamples:
    """Every imported vertex at its placed position, with its paint and pin."""
    positions, values, pins = [], [], []
    for part in getattr(mesh, "submeshes", ()) or ():
        vertices = list(getattr(part, "vertices", ()) or ())
        positions.extend(_apply_row_matrix(vertex, matrix) for vertex in vertices)
        values.extend(part_cloth_paint(part) or [0.0] * len(vertices))
        pins.extend(part_cloth_pins(part) or [False] * len(vertices))
    return ClothPaintSamples(tuple(positions), tuple(values), tuple(pins))


def apply_import_cloth_guides(result, mesh, matrix: Sequence[float], *, profile: str = "",
                              check_cancelled=lambda: None) -> bool:
    """Rebuild ``result.rebuilt_data`` with guides of its own; False when nothing is painted."""
    from cdmw.modding.pac_cloth_painted_guides import create_painted_cloth_guides

    if not mesh_has_cloth_paint(mesh):
        return False
    if not isinstance(profile, str) or len(profile) > 256:
        raise ValueError("Choose a valid cloth profile.")
    samples = import_cloth_samples(mesh, matrix)
    lows = [min(p[i] for p in samples.positions) for i in range(3)]
    highs = [max(p[i] for p in samples.positions) for i in range(3)]
    tolerance = max(1e-5, math.dist(lows, highs) * SAMPLE_TOLERANCE)
    data, report = create_painted_cloth_guides(result.rebuilt_data, samples, max_sample_distance=tolerance,
                                               check_cancelled=check_cancelled)
    result.rebuilt_data = data
    result.cloth_paint_report = report
    result.cloth_profile_edit = (profile, tuple(report.cloth_parts))
    result.summary_lines.append(
        f"Cloth paint: {report.guide_count:,} new cloth guides ({report.pinned_guides:,} pinned) built from the painted "
        f"area at LOD {report.source_lod}"
        + (f", reduced from {report.source_vertices:,}" if report.reduced else "")
        + f"; {report.cloth_vertices:,} vertices follow them, {report.rigid_vertices:,} follow bones only"
        + (f"; {report.reduced_skin_vertices:,} reduced to four bones" if report.reduced_skin_vertices else "")
        + (f"; the template's {report.removed_template_guides:,} cloth guides were removed" if report.removed_template_guides else "")
        + f". Cloth parts: {', '.join(report.cloth_parts)}; profile: {profile or 'the template’s assignment'}."
        + " Not shown in the preview; test in game.")
    return True


def cloth_profile_names(catalogue: bytes) -> tuple[str, ...]:
    """Profile names in the game's catalogue, in file order."""
    from cdmw.modding.pbd_profile_edit import ProfileXml

    names = []
    for node in ProfileXml(catalogue).nodes:
        name = node.attributes.get("Name", "")
        if name and "Filename" in node.attributes and name not in names:
            names.append(name)
    return tuple(names)


def assign_cloth_profile(data: bytes, profile: str, parts: Sequence[str], *, catalogue: bytes | None = None) -> bytes:
    """Give every material owner of ``parts`` the cloth profile ``profile``.

    An empty ``profile`` keeps the template's assignment, which must then name a
    profile for every one of those parts. A named profile must exist in the
    catalogue when one is supplied.
    """
    from cdmw.modding.pbd_profile_edit import ProfileXml

    if not parts:
        return data
    keys = {str(name).casefold() for name in parts}
    document = ProfileXml(data)
    nodes = [node for node in document.nodes if node.attributes.get("_subMeshName", "").casefold() in keys]
    found = {node.attributes["_subMeshName"].casefold() for node in nodes}
    missing = sorted(keys - found)
    if missing:
        raise ValueError(f"The material file has no entry for cloth part(s): {', '.join(missing)}.")
    owners = []
    for node in nodes:
        owner = document.owner(node)
        if all(owner is not other for other in owners):
            owners.append(owner)
    if not profile:
        empty = sorted({node.attributes["_subMeshName"] for node in nodes
                        if not document.owner(node).attributes.get(PROFILE_ATTRIBUTE, "")})
        if empty:
            raise ValueError(f"The template gives {', '.join(empty)} no cloth profile, so the new cloth would not move. "
                             "Choose a cloth profile.")
        return data
    if catalogue is not None and profile not in cloth_profile_names(catalogue):
        raise ValueError(f"The cloth profile {profile} is not in the game's profile catalogue.")
    edits = [document.attribute_edit(owner, PROFILE_ATTRIBUTE, profile) for owner in owners
             if owner.attributes.get(PROFILE_ATTRIBUTE) != profile]
    return document.apply(edits) if edits else data
