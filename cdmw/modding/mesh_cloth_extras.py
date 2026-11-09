"""Keep cloth paint and cloth pins on their vertices when the resident editor returns a mesh.

Paint and pins are set on the Python working mesh. The resident native session
holds its own copy of each Part's attributes from the moment it was opened, so
an export from it returned the paint as it stood then: paint added later was
gone after the next edit, and a topology edit returned the rest at its old
length. The Python mesh is therefore the authority. Its paint is captured before
an export replaces the Parts and laid back onto the returned vertices:

* through the edit's topology provenance where the Part carries one (a derived
  vertex takes its parents' weighted paint and is pinned only when all are);
* by index where the vertex count is unchanged (a move or a sculpt);
* otherwise by position: a vertex that did not move keeps its values, and a new
  one takes those of the nearest vertex the mesh had before.
"""

from __future__ import annotations

from dataclasses import dataclass

from .mesh_vertex_extras import all_flags, blend_scalars, lineage_plan, vertex_extras_origins

PAINT_ATTR = "cloth_paint"
PIN_ATTR = "cloth_pin"


@dataclass(frozen=True, slots=True)
class _PartClothExtras:
    vertices: tuple
    paint: tuple | None
    pins: tuple | None
    origins: object


def _aligned(part: object, name: str, count: int) -> tuple | None:
    values = getattr(part, name, None)
    if not values or len(values) != count:
        return None
    return tuple(values)


def capture_cloth_extras(mesh: object) -> tuple[_PartClothExtras, ...] | None:
    """Every Part's vertices with its paint and pins, or None when no Part carries any."""

    rows, found = [], False
    for part in tuple(getattr(mesh, "submeshes", ()) or ()):
        vertices = tuple(getattr(part, "vertices", ()) or ())
        paint, pins = _aligned(part, PAINT_ATTR, len(vertices)), _aligned(part, PIN_ATTR, len(vertices))
        found = found or paint is not None or pins is not None
        rows.append(_PartClothExtras(vertices, paint, pins,
                                     vertex_extras_origins(part) if paint is not None or pins is not None else None))
    return tuple(rows) if found else None


def _key(vertex) -> tuple[float, float, float]:
    return (float(vertex[0]), float(vertex[1]), float(vertex[2]))


class _PositionLookup:
    """Paint and pin by position over every vertex the mesh had before."""

    def __init__(self, carried):
        self.values: dict[tuple[float, float, float], tuple[float, bool]] = {}
        for before in carried:
            paint = before.paint or (0.0,) * len(before.vertices)
            pins = before.pins or (False,) * len(before.vertices)
            for vertex, value, pin in zip(before.vertices, paint, pins):
                key = _key(vertex)
                known = self.values.get(key)
                # Vertices that share a position (a seam) share the stronger value.
                self.values[key] = ((max(known[0], float(value)), known[1] or bool(pin)) if known is not None
                                    else (float(value), bool(pin)))

    def for_vertices(self, vertices) -> tuple[list[float], list[bool]]:
        paint, pins, missing = [], [], []
        for index, vertex in enumerate(vertices):
            hit = self.values.get(_key(vertex))
            if hit is None:
                missing.append(index)
                hit = (0.0, False)
            paint.append(hit[0])
            pins.append(hit[1])
        if missing and self.values:
            import numpy as np

            keys = list(self.values)
            source = np.asarray(keys, dtype=np.float64)
            chunk = max(1, 4_000_000 // len(keys))
            for start in range(0, len(missing), chunk):
                rows = missing[start:start + chunk]
                delta = np.asarray([_key(vertices[row]) for row in rows], dtype=np.float64)[:, None, :] - source[None, :, :]
                nearest = np.argmin(np.einsum("vsi,vsi->vs", delta, delta), axis=1)
                for row, found in zip(rows, nearest.tolist()):
                    paint[row], pins[row] = self.values[keys[found]]
        return paint, pins


def _follow_part(part: object, before: _PartClothExtras):
    """(paint, pins) for a Part that is still the Part ``before`` describes."""

    vertices = getattr(part, "vertices", ()) or ()
    if before.paint is None and before.pins is None:
        return None, None
    if len(vertices) == len(before.vertices) and vertex_extras_origins(part) == before.origins:
        return before.paint, before.pins
    plan = lineage_plan(before.origins, len(before.vertices), getattr(part, "topology_provenance", None))
    if plan is not None and len(plan) == len(vertices):
        paint = blend_scalars(before.paint, plan) if before.paint is not None else None
        return paint, all_flags(before.pins, plan) if before.pins is not None else None
    if len(vertices) == len(before.vertices):
        return before.paint, before.pins
    # No lineage to follow (an extrusion or a merge, for example): by position,
    # within this Part's own earlier vertices.
    paint, pins = _PositionLookup((before,)).for_vertices(vertices)
    return (paint if before.paint is not None else None), (pins if before.pins is not None else None)


def restore_cloth_extras(mesh: object, carried: tuple[_PartClothExtras, ...] | None) -> None:
    """Lay the captured paint and pins onto ``mesh``'s current vertices."""

    if carried is None:
        return
    parts = tuple(getattr(mesh, "submeshes", ()) or ())
    same_layout = len(parts) == len(carried)
    lookup = None
    for index, part in enumerate(parts):
        vertices = getattr(part, "vertices", ()) or ()
        if same_layout:
            values = _follow_part(part, carried[index])
        else:
            # Parts were added or removed, so indices no longer name the same Part.
            # One that came back untouched is recognised by its vertices.
            current = tuple(vertices)
            match = next((before for before in carried
                          if len(before.vertices) == len(current) and before.vertices == current), None)
            values = (match.paint, match.pins) if match is not None else None
        if values is None:
            if lookup is None:
                lookup = _PositionLookup(carried)
            values = lookup.for_vertices(vertices)
        for name, row in zip((PAINT_ATTR, PIN_ATTR), values):
            if row is not None and any(row):
                setattr(part, name, list(row))
            elif getattr(part, name, None):
                # The resident session's copy is older than the paint it returned without.
                setattr(part, name, [])


__all__ = ["capture_cloth_extras", "restore_cloth_extras"]
