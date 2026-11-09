"""Keep per-vertex interchange extras aligned with a Part's vertices.

Vertex colours, extra UV sets, morph targets and interchange vertex ids ride
through the native editor as opaque attributes, so a topology edit returned
them at their old length: three vertices beside four colours, which GLB and FBX
export then refused. They are stored with the vertex origins they line up with
and re-expressed for the current vertices through the edit's topology
provenance, whose origins name the same original vertices.

Cloth paint and cloth pins travel the same way. A derived vertex takes the
weighted paint of its parents and is pinned only when every parent is, as the
Python subdivision does for an edge midpoint.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from cdmw.domain.mesh.topology import SubmeshTopologyProvenance

VERTEX_EXTRAS_ORIGINS_ATTR = "_cdmw_vertex_extras_origins"

_ROW_LIST_EXTRAS = ("vertex_colors",)
_ROW_MAP_EXTRAS = ("uv_sets", "morph_targets", "morph_normals", "morph_tangents")
_ID_EXTRAS = ("interchange_vertex_ids",)
#: One number per vertex, blended for a derived vertex.
_SCALAR_EXTRAS = ("cloth_paint",)
#: One true/false per vertex; a derived vertex is set only when all its parents are.
_FLAG_EXTRAS = ("cloth_pin",)

_Plan = list[list[tuple[int, float]]]


def has_vertex_extras(submesh: object) -> bool:
    return any(getattr(submesh, name, None) for name in (
        *_ROW_LIST_EXTRAS, *_ROW_MAP_EXTRAS, *_ID_EXTRAS, *_SCALAR_EXTRAS, *_FLAG_EXTRAS))


def vertex_extras_origins(submesh: object) -> list[list[list[float]]] | None:
    """The origins the Part's extras line up with, or None for its original vertices."""

    provenance = getattr(submesh, "topology_provenance", None)
    if not isinstance(provenance, SubmeshTopologyProvenance):
        return None
    if len(provenance.vertex_origins) != len(getattr(submesh, "vertices", ()) or ()):
        return None
    return [[list(origin.parents), list(origin.weights)] for origin in provenance.vertex_origins]


def _stored_origins(raw: object, original_count: int) -> list[tuple[tuple[int, ...], tuple[float, ...]]] | None:
    if raw is None:
        return [((index,), (1.0,)) for index in range(original_count)]
    if not isinstance(raw, Sequence):
        return None
    origins = []
    for row in raw:
        if not isinstance(row, Sequence) or len(row) != 2:
            return None
        parents, weights = row
        try:
            origins.append((tuple(int(parent) for parent in parents), tuple(float(weight) for weight in weights)))
        except (TypeError, ValueError):
            return None
    return origins


def _plan(stored, provenance: SubmeshTopologyProvenance) -> _Plan | None:
    by_origin = {origin: index for index, origin in enumerate(stored)}
    by_parent = {parents[0]: index for index, (parents, _weights) in enumerate(stored) if len(parents) == 1}
    plan: _Plan = []
    for origin in provenance.vertex_origins:
        exact = by_origin.get((tuple(origin.parents), tuple(origin.weights)))
        if exact is not None:
            plan.append([(exact, 1.0)])
            continue
        blend = [(by_parent.get(parent), weight) for parent, weight in zip(origin.parents, origin.weights)]
        if any(index is None for index, _weight in blend):
            return None
        plan.append(blend)  # type: ignore[arg-type]
    return plan


def _blend_rows(rows: Sequence[object], plan: _Plan) -> list[tuple[float, ...]] | None:
    result = []
    for sources in plan:
        try:
            width = len(rows[sources[0][0]])  # type: ignore[arg-type]
            result.append(tuple(
                sum(float(rows[index][axis]) * weight for index, weight in sources)  # type: ignore[index]
                for axis in range(width)
            ))
        except (TypeError, ValueError, IndexError):
            return None
    return result


def realign_vertex_extras(
    submesh: object,
    stored_origins: object,
    provenance: SubmeshTopologyProvenance | None,
) -> None:
    """Re-express extras stored against ``stored_origins`` for the current vertices.

    An extra that already has one row per vertex and no lineage to follow is
    kept; one that can no longer be matched to the vertices is removed rather
    than exported at the wrong length.
    """

    vertex_count = len(getattr(submesh, "vertices", ()) or ())
    plan = None
    stored_count = -1
    if provenance is not None:
        stored = _stored_origins(stored_origins, provenance.original_vertex_count)
        if stored is not None:
            stored_count = len(stored)
            plan = _plan(stored, provenance)

    def aligned(rows: object) -> object:
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            return None
        if plan is not None and len(rows) == stored_count:
            return _blend_rows(rows, plan)
        return list(rows) if len(rows) == vertex_count else None

    for name in _ROW_LIST_EXTRAS:
        rows = getattr(submesh, name, None)
        if rows:
            setattr(submesh, name, aligned(rows) or [])
    for name in _ROW_MAP_EXTRAS:
        table = getattr(submesh, name, None)
        if isinstance(table, Mapping) and table:
            realigned = {key: aligned(rows) for key, rows in table.items()}
            setattr(submesh, name, {key: rows for key, rows in realigned.items() if rows is not None})
    for name in _ID_EXTRAS:
        ids = getattr(submesh, name, None)
        if not ids:
            continue
        if plan is not None and len(ids) == stored_count:
            # An id names one source vertex; a derived vertex takes its heaviest parent's.
            setattr(submesh, name, [ids[max(sources, key=lambda source: source[1])[0]] for sources in plan])
        elif len(ids) != vertex_count:
            setattr(submesh, name, [])
    for name in _SCALAR_EXTRAS:
        values = getattr(submesh, name, None)
        if not values:
            continue
        if plan is not None and len(values) == stored_count:
            setattr(submesh, name, blend_scalars(values, plan) or [])
        elif len(values) != vertex_count:
            setattr(submesh, name, [])
    for name in _FLAG_EXTRAS:
        flags = getattr(submesh, name, None)
        if not flags:
            continue
        if plan is not None and len(flags) == stored_count:
            setattr(submesh, name, all_flags(flags, plan))
        elif len(flags) != vertex_count:
            setattr(submesh, name, [])


def blend_scalars(values: Sequence[object], plan: _Plan) -> list[float] | None:
    """One 0..1 number per planned vertex: the weighted value of its sources."""

    try:
        return [min(1.0, max(0.0, sum(float(values[index]) * weight for index, weight in sources)))
                for sources in plan]
    except (TypeError, ValueError, IndexError):
        return None


def all_flags(flags: Sequence[object], plan: _Plan) -> list[bool]:
    """One flag per planned vertex: set only when every one of its sources is."""

    return [all(bool(flags[index]) for index, _weight in sources) for sources in plan]


def lineage_plan(stored_origins: object, stored_count: int, provenance: object) -> _Plan | None:
    """How ``provenance``'s vertices derive from rows stored against ``stored_origins``.

    None when the two do not share a lineage that can be followed.
    """

    if not isinstance(provenance, SubmeshTopologyProvenance):
        return None
    stored = _stored_origins(stored_origins, provenance.original_vertex_count)
    if stored is None or len(stored) != stored_count:
        return None
    return _plan(stored, provenance)


__all__ = [
    "VERTEX_EXTRAS_ORIGINS_ATTR",
    "has_vertex_extras",
    "realign_vertex_extras",
    "vertex_extras_origins",
]
