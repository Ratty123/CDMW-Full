"""Pure topology provenance contract for exact PAC LOD0 rebuilds.

An admitted topology edit (Face Delete, Loop Cut, midpoint Subdivide) changes
vertex count, face count, and connectivity. Rebuilding that result into the
original PAC is only safe when every output vertex and every output triangle
still names where it came from in the *original* LOD0 submesh, not in whatever
intermediate edit produced it. This module owns that contract: the immutable
value types, the composition rule that keeps chained edits one level deep, the
canonical form, and the stable blocker codes every consumer reports.

Nothing here reads or writes bytes. The serializer, the native protocol, and the
service all validate through these functions before they trust a contract.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


TOPOLOGY_PROVENANCE_VERSION = "cdmw_mesh_topology_provenance_v1"
TOPOLOGY_PROVENANCE_CAPABILITY = "topology_provenance_v1"

#: The normalized weight sum must land here exactly, not "close enough".
TOPOLOGY_WEIGHT_SUM_ABS_TOL = 1e-12

#: PAC LOD0 index buffers are u16; 65,536 distinct vertices cannot be addressed.
TOPOLOGY_MAX_PAC_VERTEX_COUNT = 65_535

#: A proven PAC skin row holds at most six positive palette slots.
TOPOLOGY_MAX_SKIN_INFLUENCES = 6

TOPOLOGY_OPERATION_DELETE_FACES = "delete_faces_topology"
TOPOLOGY_OPERATION_LOOP_CUT = "loop_cut_topology"
TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT = "subdivide_midpoint_topology"

#: The only topology-changing operations v1 can rebuild exactly.
TOPOLOGY_REBUILDABLE_OPERATIONS = (
    TOPOLOGY_OPERATION_DELETE_FACES,
    TOPOLOGY_OPERATION_LOOP_CUT,
    TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT,
)

#: Native editor action -> stable contract operation name.
TOPOLOGY_OPERATION_BY_NATIVE_ACTION = {
    "delete": TOPOLOGY_OPERATION_DELETE_FACES,
    "loop_cut": TOPOLOGY_OPERATION_LOOP_CUT,
    "subdivide": TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT,
}

#: Stable `MeshEditOperation.metadata` keys for an admitted topology operation.
TOPOLOGY_METADATA_CONTRACT = "topology_contract"
TOPOLOGY_METADATA_INPUT_VERTEX_COUNT = "input_vertex_count"
TOPOLOGY_METADATA_INPUT_FACE_COUNT = "input_face_count"
TOPOLOGY_METADATA_OUTPUT_VERTEX_COUNT = "output_vertex_count"
TOPOLOGY_METADATA_OUTPUT_FACE_COUNT = "output_face_count"
TOPOLOGY_METADATA_SOURCE_REVISION = "source_revision"
TOPOLOGY_METADATA_RESULT_REVISION = "result_revision"

TOPOLOGY_METADATA_KEYS = (
    TOPOLOGY_METADATA_CONTRACT,
    TOPOLOGY_METADATA_INPUT_VERTEX_COUNT,
    TOPOLOGY_METADATA_INPUT_FACE_COUNT,
    TOPOLOGY_METADATA_OUTPUT_VERTEX_COUNT,
    TOPOLOGY_METADATA_OUTPUT_FACE_COUNT,
    TOPOLOGY_METADATA_SOURCE_REVISION,
    TOPOLOGY_METADATA_RESULT_REVISION,
)

#: `source_vertex_map` sentinel for an output vertex with no single original parent.
TOPOLOGY_DERIVED_SOURCE_SENTINEL = -1

TOPOLOGY_PROVENANCE_REQUIRED = "TOPOLOGY_PROVENANCE_REQUIRED"
TOPOLOGY_CONTRACT_UNSUPPORTED = "TOPOLOGY_CONTRACT_UNSUPPORTED"
TOPOLOGY_VERTEX_ORIGIN_INVALID = "TOPOLOGY_VERTEX_ORIGIN_INVALID"
TOPOLOGY_FACE_ORIGIN_INVALID = "TOPOLOGY_FACE_ORIGIN_INVALID"
TOPOLOGY_OPERATION_NOT_REBUILDABLE = "TOPOLOGY_OPERATION_NOT_REBUILDABLE"
TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED = "TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED"
TOPOLOGY_PROTECTED_BYTES_DIVERGE = "TOPOLOGY_PROTECTED_BYTES_DIVERGE"
TOPOLOGY_BOUNDS_EXCEED_SOURCE = "TOPOLOGY_BOUNDS_EXCEED_SOURCE"
TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED = "TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED"
TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED = "TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED"
TOPOLOGY_REVISION_DISCONTINUOUS = "TOPOLOGY_REVISION_DISCONTINUOUS"

TOPOLOGY_BLOCKER_CODES = (
    TOPOLOGY_PROVENANCE_REQUIRED,
    TOPOLOGY_CONTRACT_UNSUPPORTED,
    TOPOLOGY_VERTEX_ORIGIN_INVALID,
    TOPOLOGY_FACE_ORIGIN_INVALID,
    TOPOLOGY_OPERATION_NOT_REBUILDABLE,
    TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED,
    TOPOLOGY_PROTECTED_BYTES_DIVERGE,
    TOPOLOGY_BOUNDS_EXCEED_SOURCE,
    TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED,
    TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED,
    TOPOLOGY_REVISION_DISCONTINUOUS,
)


class TopologyProvenanceError(ValueError):
    """A topology contract could not be composed or validated.

    Carries the stable blocker code so callers report the same string a
    validated-but-rejected contract would produce.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code or TOPOLOGY_CONTRACT_UNSUPPORTED)


@dataclass(frozen=True, slots=True)
class VertexOrigin:
    """Where one output vertex came from in the original LOD0 submesh.

    A direct vertex is a single parent at weight ``1.0``. A derived vertex names
    two or more original parents whose positive weights sum to ``1.0``. Parents
    are ascending, unique, and original-relative, never indices in an
    intermediate edit.
    """

    parents: tuple[int, ...]
    weights: tuple[float, ...]

    @property
    def direct_parent(self) -> int:
        """The single original vertex index, or the derived sentinel."""
        return self.parents[0] if len(self.parents) == 1 else TOPOLOGY_DERIVED_SOURCE_SENTINEL

    @property
    def derived(self) -> bool:
        return len(self.parents) != 1


@dataclass(frozen=True, slots=True)
class SubmeshTopologyProvenance:
    """The complete original-relative lineage of one edited submesh."""

    version: str
    original_vertex_count: int
    original_face_count: int
    vertex_origins: tuple[VertexOrigin, ...]
    face_origins: tuple[int, ...]

    @property
    def output_vertex_count(self) -> int:
        return len(self.vertex_origins)

    @property
    def output_face_count(self) -> int:
        return len(self.face_origins)

    @property
    def direct_vertex_count(self) -> int:
        return sum(1 for origin in self.vertex_origins if not origin.derived)

    @property
    def derived_vertex_count(self) -> int:
        return sum(1 for origin in self.vertex_origins if origin.derived)

    @property
    def max_influence_union_width(self) -> int:
        return max((len(origin.parents) for origin in self.vertex_origins), default=0)


def canonical_vertex_origin(
    parents: Iterable[object],
    weights: Iterable[object],
    *,
    original_vertex_count: int,
) -> VertexOrigin:
    """Merge, normalize, and validate one output vertex's parent weights.

    Duplicate parents merge with :func:`math.fsum`, every merged weight is
    divided by the merged :func:`math.fsum` total, and the normalized sum is
    checked exactly. Chained edits stay one level deep and original-relative
    without accumulating drift.
    """
    raw_parents = tuple(parents or ())
    raw_weights = tuple(weights or ())
    if len(raw_parents) != len(raw_weights):
        raise TopologyProvenanceError(
            TOPOLOGY_VERTEX_ORIGIN_INVALID,
            f"Vertex origin has {len(raw_parents)} parent(s) but {len(raw_weights)} weight(s).",
        )
    if not raw_parents:
        raise TopologyProvenanceError(TOPOLOGY_VERTEX_ORIGIN_INVALID, "Vertex origin has no parents.")

    merged: dict[int, list[float]] = {}
    for raw_parent, raw_weight in zip(raw_parents, raw_weights):
        parent = _strict_index(raw_parent, code=TOPOLOGY_VERTEX_ORIGIN_INVALID, label="parent index")
        weight = _strict_weight(raw_weight)
        if parent < 0 or parent >= original_vertex_count:
            raise TopologyProvenanceError(
                TOPOLOGY_VERTEX_ORIGIN_INVALID,
                f"Vertex origin parent {parent} is outside the original vertex range "
                f"[0, {original_vertex_count}).",
            )
        merged.setdefault(parent, []).append(weight)

    ordered = sorted(merged.items())
    totals = [math.fsum(values) for _parent, values in ordered]
    if any(total <= 0.0 or not math.isfinite(total) for total in totals):
        raise TopologyProvenanceError(
            TOPOLOGY_VERTEX_ORIGIN_INVALID, "Vertex origin merged to a non-positive parent weight."
        )
    total = math.fsum(totals)
    if not math.isfinite(total) or total <= 0.0:
        raise TopologyProvenanceError(
            TOPOLOGY_VERTEX_ORIGIN_INVALID, "Vertex origin weights do not sum to a positive total."
        )
    normalized = tuple(value / total for value in totals)
    if any(value <= 0.0 or not math.isfinite(value) for value in normalized):
        raise TopologyProvenanceError(
            TOPOLOGY_VERTEX_ORIGIN_INVALID, "Vertex origin normalization produced a non-positive weight."
        )
    if not math.isclose(math.fsum(normalized), 1.0, rel_tol=0.0, abs_tol=TOPOLOGY_WEIGHT_SUM_ABS_TOL):
        raise TopologyProvenanceError(
            TOPOLOGY_VERTEX_ORIGIN_INVALID,
            f"Vertex origin weights sum to {math.fsum(normalized)!r} after normalization.",
        )
    return VertexOrigin(tuple(parent for parent, _values in ordered), normalized)


def identity_topology_provenance(vertex_count: int, face_count: int) -> SubmeshTopologyProvenance:
    """The provenance of an unedited original submesh: every output is itself."""
    vertices = _strict_count(vertex_count, label="vertex count")
    faces = _strict_count(face_count, label="face count")
    return SubmeshTopologyProvenance(
        version=TOPOLOGY_PROVENANCE_VERSION,
        original_vertex_count=vertices,
        original_face_count=faces,
        vertex_origins=tuple(VertexOrigin((index,), (1.0,)) for index in range(vertices)),
        face_origins=tuple(range(faces)),
    )


def compose_topology_provenance(
    previous: SubmeshTopologyProvenance,
    *,
    copy_vertex_indices: Sequence[object],
    vertex_blends: Iterable[Mapping[str, object] | Sequence[object]] = (),
    face_origins: Sequence[object],
) -> SubmeshTopologyProvenance:
    """Fold one admitted native result onto the previous original-relative lineage.

    ``copy_vertex_indices`` is one entry per output vertex: a pre-operation
    vertex index for a copy, or a negative sentinel for a vertex the operation
    derived. Every derived vertex must be named by exactly one blend, and every
    blend must reference pre-operation vertices that exist.
    """
    copies = tuple(copy_vertex_indices or ())
    output_vertex_count = len(copies)
    if output_vertex_count <= 0:
        raise TopologyProvenanceError(
            TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED, "A topology result must keep at least one vertex."
        )
    previous_count = previous.output_vertex_count

    blends_by_index: dict[int, tuple[int, int, float]] = {}
    for raw_blend in vertex_blends or ():
        index, left, right, factor = _blend_fields(raw_blend)
        if index < 0 or index >= output_vertex_count:
            raise TopologyProvenanceError(
                TOPOLOGY_VERTEX_ORIGIN_INVALID,
                f"Vertex blend names output vertex {index} outside [0, {output_vertex_count}).",
            )
        if index in blends_by_index:
            raise TopologyProvenanceError(
                TOPOLOGY_VERTEX_ORIGIN_INVALID, f"Output vertex {index} has more than one blend derivation."
            )
        if left < 0 or left >= previous_count or right < 0 or right >= previous_count:
            raise TopologyProvenanceError(
                TOPOLOGY_VERTEX_ORIGIN_INVALID,
                f"Vertex blend for output vertex {index} references a pre-operation vertex outside "
                f"[0, {previous_count}).",
            )
        blends_by_index[index] = (left, right, factor)

    origins: list[VertexOrigin] = []
    for output_index, raw_copy in enumerate(copies):
        copy_index = _strict_index(raw_copy, code=TOPOLOGY_VERTEX_ORIGIN_INVALID, label="copy index")
        blend = blends_by_index.pop(output_index, None)
        if copy_index >= 0:
            if blend is not None:
                raise TopologyProvenanceError(
                    TOPOLOGY_VERTEX_ORIGIN_INVALID,
                    f"Output vertex {output_index} is both a copy and a blend derivation.",
                )
            if copy_index >= previous_count:
                raise TopologyProvenanceError(
                    TOPOLOGY_VERTEX_ORIGIN_INVALID,
                    f"Output vertex {output_index} copies pre-operation vertex {copy_index} outside "
                    f"[0, {previous_count}).",
                )
            origins.append(previous.vertex_origins[copy_index])
            continue
        if blend is None:
            raise TopologyProvenanceError(
                TOPOLOGY_VERTEX_ORIGIN_INVALID,
                f"Output vertex {output_index} has neither a copy source nor a blend derivation.",
            )
        left, right, factor = blend
        left_origin = previous.vertex_origins[left]
        right_origin = previous.vertex_origins[right]
        parents: list[int] = []
        weights: list[float] = []
        for parent, weight in zip(left_origin.parents, left_origin.weights):
            parents.append(parent)
            weights.append(weight * (1.0 - factor))
        for parent, weight in zip(right_origin.parents, right_origin.weights):
            parents.append(parent)
            weights.append(weight * factor)
        parents = [parent for parent, weight in zip(parents, weights) if weight > 0.0]
        weights = [weight for weight in weights if weight > 0.0]
        origins.append(
            canonical_vertex_origin(parents, weights, original_vertex_count=previous.original_vertex_count)
        )

    if blends_by_index:
        missing = sorted(blends_by_index)
        raise TopologyProvenanceError(
            TOPOLOGY_VERTEX_ORIGIN_INVALID,
            f"Vertex blend(s) {missing} do not correspond to a derived output vertex.",
        )

    composed_faces: list[int] = []
    for position, raw_face in enumerate(tuple(face_origins or ())):
        face_index = _strict_index(raw_face, code=TOPOLOGY_FACE_ORIGIN_INVALID, label="face origin")
        if face_index < 0 or face_index >= previous.output_face_count:
            raise TopologyProvenanceError(
                TOPOLOGY_FACE_ORIGIN_INVALID,
                f"Output triangle {position} names pre-operation face {face_index} outside "
                f"[0, {previous.output_face_count}).",
            )
        composed_faces.append(previous.face_origins[face_index])
    if not composed_faces:
        raise TopologyProvenanceError(
            TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED, "A topology result must keep at least one triangle."
        )

    return SubmeshTopologyProvenance(
        version=TOPOLOGY_PROVENANCE_VERSION,
        original_vertex_count=previous.original_vertex_count,
        original_face_count=previous.original_face_count,
        vertex_origins=tuple(origins),
        face_origins=tuple(composed_faces),
    )


def validate_topology_provenance(
    provenance: object,
    *,
    output_vertex_count: int,
    output_face_count: int,
    enforce_pac_index_limit: bool = True,
) -> tuple[str, ...]:
    """Return the stable blocker codes that make ``provenance`` unusable.

    An empty tuple means the contract is complete, canonical, original-relative,
    and matches the edited submesh it claims to describe.
    """
    if not isinstance(provenance, SubmeshTopologyProvenance):
        return (TOPOLOGY_PROVENANCE_REQUIRED,)
    blockers: list[str] = []
    if str(provenance.version or "") != TOPOLOGY_PROVENANCE_VERSION:
        blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
    if provenance.original_vertex_count <= 0 or provenance.original_face_count <= 0:
        blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
    if output_vertex_count <= 0 or output_face_count <= 0:
        blockers.append(TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED)
    if enforce_pac_index_limit and output_vertex_count > TOPOLOGY_MAX_PAC_VERTEX_COUNT:
        blockers.append(TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED)

    if provenance.output_vertex_count != output_vertex_count:
        blockers.append(TOPOLOGY_VERTEX_ORIGIN_INVALID)
    else:
        for origin in provenance.vertex_origins:
            if not _origin_is_canonical(origin, provenance.original_vertex_count):
                blockers.append(TOPOLOGY_VERTEX_ORIGIN_INVALID)
                break

    if provenance.output_face_count != output_face_count:
        blockers.append(TOPOLOGY_FACE_ORIGIN_INVALID)
    elif any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value >= provenance.original_face_count
        for value in provenance.face_origins
    ):
        blockers.append(TOPOLOGY_FACE_ORIGIN_INVALID)

    return tuple(dict.fromkeys(blockers))


def topology_provenance_is_valid(
    provenance: object,
    *,
    output_vertex_count: int,
    output_face_count: int,
) -> bool:
    return not validate_topology_provenance(
        provenance,
        output_vertex_count=output_vertex_count,
        output_face_count=output_face_count,
    )


def topology_contract_submesh_indices(mesh: object) -> tuple[int, ...]:
    """Which of a mesh's submeshes carry a contract that describes their own geometry.

    Callers that only need "does this mesh carry one at all" read the tuple as a
    boolean. One owner for that question keeps every caller agreeing about what
    counts: a contract that no longer matches its submesh's counts is not one.
    """
    return tuple(
        index
        for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ()))
        if getattr(submesh, "topology_provenance", None) is not None
        and topology_provenance_is_valid(
            getattr(submesh, "topology_provenance", None),
            output_vertex_count=len(tuple(getattr(submesh, "vertices", ()) or ())),
            output_face_count=len(tuple(getattr(submesh, "faces", ()) or ())),
        )
    )


def topology_source_vertex_map(provenance: SubmeshTopologyProvenance) -> tuple[int, ...]:
    """Legacy `source_vertex_map` view: original index, or -1 where derived."""
    return tuple(origin.direct_parent for origin in provenance.vertex_origins)


def topology_source_face_indices(provenance: SubmeshTopologyProvenance) -> tuple[int, ...]:
    """One original face index per output triangle, never per output index."""
    return tuple(provenance.face_origins)


def removed_original_vertices(provenance: SubmeshTopologyProvenance) -> tuple[int, ...]:
    """Original vertices no output vertex still names. Reporting only."""
    retained = {parent for origin in provenance.vertex_origins for parent in origin.parents}
    return tuple(index for index in range(provenance.original_vertex_count) if index not in retained)


def removed_original_faces(provenance: SubmeshTopologyProvenance) -> tuple[int, ...]:
    """Original faces no output triangle still names. Reporting only."""
    retained = set(provenance.face_origins)
    return tuple(index for index in range(provenance.original_face_count) if index not in retained)


def topology_operation_for_native_action(action: object) -> str:
    """Stable contract name for a native editor action, or "" when unsupported."""
    return TOPOLOGY_OPERATION_BY_NATIVE_ACTION.get(str(action or "").strip().casefold(), "")


def topology_operation_metadata(
    *,
    input_vertex_count: int,
    input_face_count: int,
    output_vertex_count: int,
    output_face_count: int,
    source_revision: int,
    result_revision: int,
) -> dict[str, object]:
    """The stable metadata block recorded on an admitted topology operation."""
    return {
        TOPOLOGY_METADATA_CONTRACT: TOPOLOGY_PROVENANCE_VERSION,
        TOPOLOGY_METADATA_INPUT_VERTEX_COUNT: _strict_count(input_vertex_count, label="input vertex count"),
        TOPOLOGY_METADATA_INPUT_FACE_COUNT: _strict_count(input_face_count, label="input face count"),
        TOPOLOGY_METADATA_OUTPUT_VERTEX_COUNT: _strict_count(output_vertex_count, label="output vertex count"),
        TOPOLOGY_METADATA_OUTPUT_FACE_COUNT: _strict_count(output_face_count, label="output face count"),
        TOPOLOGY_METADATA_SOURCE_REVISION: _strict_count(source_revision, label="source revision"),
        TOPOLOGY_METADATA_RESULT_REVISION: _strict_count(result_revision, label="result revision"),
    }


def validate_topology_operation_history(operations: Iterable[object]) -> tuple[str, ...]:
    """Check that recorded topology operations form a continuous native history.

    Revision continuity is proven from the recorded source/result revisions, not
    inferred from operation names. A gap means an unrecorded topology-changing
    edit happened in between and the contract can no longer be trusted.
    """
    rows: list[tuple[str, Mapping[str, object]]] = []
    for operation in operations or ():
        name = str(getattr(operation, "operation", "") or "").strip()
        metadata = getattr(operation, "metadata", None)
        if not isinstance(metadata, Mapping):
            metadata = {}
        if name in TOPOLOGY_REBUILDABLE_OPERATIONS or TOPOLOGY_METADATA_CONTRACT in metadata:
            rows.append((name, metadata))
    if not rows:
        return ()

    blockers: list[str] = []
    previous_result: int | None = None
    for name, metadata in rows:
        if name not in TOPOLOGY_REBUILDABLE_OPERATIONS:
            blockers.append(TOPOLOGY_OPERATION_NOT_REBUILDABLE)
            continue
        if str(metadata.get(TOPOLOGY_METADATA_CONTRACT) or "") != TOPOLOGY_PROVENANCE_VERSION:
            blockers.append(TOPOLOGY_CONTRACT_UNSUPPORTED)
            continue
        source_revision = _optional_index(metadata.get(TOPOLOGY_METADATA_SOURCE_REVISION))
        result_revision = _optional_index(metadata.get(TOPOLOGY_METADATA_RESULT_REVISION))
        if source_revision is None or result_revision is None or result_revision <= source_revision:
            blockers.append(TOPOLOGY_REVISION_DISCONTINUOUS)
            continue
        if previous_result is not None and source_revision != previous_result:
            blockers.append(TOPOLOGY_REVISION_DISCONTINUOUS)
        previous_result = result_revision
    return tuple(dict.fromkeys(blockers))


def _origin_is_canonical(origin: object, original_vertex_count: int) -> bool:
    if not isinstance(origin, VertexOrigin):
        return False
    parents = origin.parents
    weights = origin.weights
    if not parents or len(parents) != len(weights):
        return False
    if any(isinstance(value, bool) or not isinstance(value, int) for value in parents):
        return False
    if any(value < 0 or value >= original_vertex_count for value in parents):
        return False
    if any(left >= right for left, right in zip(parents, parents[1:])):
        return False
    if any(not isinstance(value, float) or not math.isfinite(value) or value <= 0.0 for value in weights):
        return False
    return math.isclose(math.fsum(weights), 1.0, rel_tol=0.0, abs_tol=TOPOLOGY_WEIGHT_SUM_ABS_TOL)


def _blend_fields(raw_blend: object) -> tuple[int, int, int, float]:
    if isinstance(raw_blend, Mapping):
        index = raw_blend.get("index")
        left = raw_blend.get("left")
        right = raw_blend.get("right")
        factor = raw_blend.get("factor")
    else:
        values = tuple(raw_blend or ())
        if len(values) != 4:
            raise TopologyProvenanceError(
                TOPOLOGY_VERTEX_ORIGIN_INVALID,
                f"Vertex blend must carry index, left, right, and factor; got {len(values)} value(s).",
            )
        index, left, right, factor = values
    parsed_factor = _strict_weight(factor)
    if not 0.0 < parsed_factor < 1.0:
        raise TopologyProvenanceError(
            TOPOLOGY_VERTEX_ORIGIN_INVALID,
            f"Vertex blend factor {parsed_factor!r} must lie strictly between 0 and 1.",
        )
    return (
        _strict_index(index, code=TOPOLOGY_VERTEX_ORIGIN_INVALID, label="blend output index"),
        _strict_index(left, code=TOPOLOGY_VERTEX_ORIGIN_INVALID, label="blend left index"),
        _strict_index(right, code=TOPOLOGY_VERTEX_ORIGIN_INVALID, label="blend right index"),
        parsed_factor,
    )


def _strict_index(value: object, *, code: str, label: str) -> int:
    if isinstance(value, bool):
        raise TopologyProvenanceError(code, f"Topology {label} must be an integer, not a boolean.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise TopologyProvenanceError(code, f"Topology {label} {value!r} is not an exact integer.")
        return int(value)
    raise TopologyProvenanceError(code, f"Topology {label} {value!r} is not an integer.")


def _strict_weight(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TopologyProvenanceError(
            TOPOLOGY_VERTEX_ORIGIN_INVALID, f"Topology weight {value!r} is not a real number."
        )
    weight = float(value)
    if not math.isfinite(weight) or weight <= 0.0:
        raise TopologyProvenanceError(
            TOPOLOGY_VERTEX_ORIGIN_INVALID, f"Topology weight {value!r} must be finite and strictly positive."
        )
    return weight


def _strict_count(value: object, *, label: str) -> int:
    parsed = _strict_index(value, code=TOPOLOGY_CONTRACT_UNSUPPORTED, label=label)
    if parsed < 0:
        raise TopologyProvenanceError(TOPOLOGY_CONTRACT_UNSUPPORTED, f"Topology {label} {parsed} is negative.")
    return parsed


def _optional_index(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        return None
    parsed = int(value)
    return parsed if parsed >= 0 else None


__all__ = [
    "SubmeshTopologyProvenance",
    "TOPOLOGY_BLOCKER_CODES",
    "TOPOLOGY_BOUNDS_EXCEED_SOURCE",
    "TOPOLOGY_CONTRACT_UNSUPPORTED",
    "TOPOLOGY_DERIVED_SOURCE_SENTINEL",
    "TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED",
    "TOPOLOGY_FACE_ORIGIN_INVALID",
    "TOPOLOGY_MAX_PAC_VERTEX_COUNT",
    "TOPOLOGY_MAX_SKIN_INFLUENCES",
    "TOPOLOGY_METADATA_CONTRACT",
    "TOPOLOGY_METADATA_INPUT_FACE_COUNT",
    "TOPOLOGY_METADATA_INPUT_VERTEX_COUNT",
    "TOPOLOGY_METADATA_KEYS",
    "TOPOLOGY_METADATA_OUTPUT_FACE_COUNT",
    "TOPOLOGY_METADATA_OUTPUT_VERTEX_COUNT",
    "TOPOLOGY_METADATA_RESULT_REVISION",
    "TOPOLOGY_METADATA_SOURCE_REVISION",
    "TOPOLOGY_OPERATION_BY_NATIVE_ACTION",
    "TOPOLOGY_OPERATION_DELETE_FACES",
    "TOPOLOGY_OPERATION_LOOP_CUT",
    "TOPOLOGY_OPERATION_NOT_REBUILDABLE",
    "TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT",
    "TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED",
    "TOPOLOGY_PROTECTED_BYTES_DIVERGE",
    "TOPOLOGY_PROVENANCE_CAPABILITY",
    "TOPOLOGY_PROVENANCE_REQUIRED",
    "TOPOLOGY_PROVENANCE_VERSION",
    "TOPOLOGY_REBUILDABLE_OPERATIONS",
    "TOPOLOGY_REVISION_DISCONTINUOUS",
    "TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED",
    "TOPOLOGY_VERTEX_ORIGIN_INVALID",
    "TOPOLOGY_WEIGHT_SUM_ABS_TOL",
    "TopologyProvenanceError",
    "VertexOrigin",
    "canonical_vertex_origin",
    "compose_topology_provenance",
    "identity_topology_provenance",
    "removed_original_faces",
    "removed_original_vertices",
    "topology_contract_submesh_indices",
    "topology_operation_for_native_action",
    "topology_operation_metadata",
    "topology_provenance_is_valid",
    "topology_source_face_indices",
    "topology_source_vertex_map",
    "validate_topology_operation_history",
    "validate_topology_provenance",
]
