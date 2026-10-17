"""Bounded derived state for one worker-owned Rust authoring session.

The MeshService revision owns in-place mutations. Known presentation-only
protocol revisions may carry that state forward; every unknown revision drops
it. Array identity/count guards also catch replaced channels before publication.
No cache key walks the vertices, faces, or weight rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _sequence_identity(value: object) -> tuple[int, int]:
    return id(value), len(value) if value is not None else 0


def _part_identity(part: object) -> tuple[object, ...]:
    return (
        id(part), str(getattr(part, "name", "")), str(getattr(part, "material", "")),
        *(_sequence_identity(getattr(part, name, ())) for name in (
            "vertices", "faces", "normals", "uvs", "shader_masks", "bone_indices",
            "bone_weights", "source_vertex_map", "source_vertex_offsets", "source_bone_palette",
        )),
        getattr(part, "source_vertex_stride", 0), getattr(part, "source_skin_weight_layout", ""),
    )


def _mesh_identity(mesh: object) -> tuple[object, ...]:
    levels = (mesh.submeshes, *(getattr(mesh, "lod_levels", ()) or ()))
    return (
        id(mesh),
        str(getattr(mesh, "format", "")), str(getattr(mesh, "path", "")),
        id(getattr(mesh, "_cdmw_original_data", None)),
        str(getattr(mesh, "_cdmw_mesh_asset_source_hash", "")),
        str(getattr(mesh, "_cdmw_sidecar_source_asset_hash", "")),
        tuple(tuple(_part_identity(part) for part in level) for level in levels),
    )


def mesh_state_identity(session: object) -> tuple[object, ...]:
    return (
        getattr(session, "topology_operation_revision", 0), getattr(session, "lod_index", 0),
        bool(getattr(session, "native_editor_mesh_dirty", False)), _mesh_identity(session.working_mesh),
    )


def skeleton_identity(session: object) -> tuple[object, ...]:
    skeleton = getattr(session, "skeleton", None)
    return (
        id(skeleton), str(getattr(skeleton, "path", "")),
        str(getattr(skeleton, "parser_mode", "")), str(getattr(skeleton, "parse_warning", "")),
        tuple((
            getattr(bone, "index", ordinal), getattr(bone, "name_hash", 0),
            str(getattr(bone, "name", "")), getattr(bone, "parent_index", -1),
            tuple(getattr(bone, "position", ()) or ()), tuple(getattr(bone, "bind_matrix", ()) or ()),
        ) for ordinal, bone in enumerate(getattr(skeleton, "bones", ()) or ())),
    )


def source_skin_identity(session: object) -> tuple[object, ...]:
    base = getattr(session, "source_coordinate_base_mesh", None)
    if base is None:
        base = getattr(session, "base_mesh", None)
    return (
        id(getattr(session, "original_data", None)), id(base),
        bool(getattr(session, "base_mesh_is_original_parse", False)),
        str(getattr(session, "mesh_format", "")), skeleton_identity(session),
        str(getattr(session, "skeleton_resolution_reason", "")),
        tuple(_part_identity(part) for part in getattr(base, "submeshes", ()) or ()),
    )


@dataclass(frozen=True, slots=True)
class PreparedMeshDocument:
    """Already encoded immutable geometry, still subject to publication bounds."""

    data: bytes


@dataclass(slots=True)
class _MeshDocument:
    mesh: object
    identity: tuple[object, ...] | None
    revision: int
    data: PreparedMeshDocument
    pending: bool = False


@dataclass(slots=True)
class RustMeshStateCache:
    observed_mesh: object | None = field(default=None, repr=False)
    observed_revision: int = -1
    observed_identity: tuple[object, ...] | None = None
    geometry_revision: int = 0
    weight_revision: int = 0
    capability: tuple | None = field(default=None, repr=False)
    source_palette: tuple | None = field(default=None, repr=False)
    source_rows: dict[int, tuple] = field(default_factory=dict, repr=False)
    skeleton_summary: tuple | None = field(default=None, repr=False)
    bone_influence: tuple | None = field(default=None, repr=False)
    document: _MeshDocument | None = field(default=None, repr=False)

    def _record(self, session: object, identity: tuple[object, ...]) -> None:
        self.observed_mesh = session.working_mesh
        self.observed_revision = int(session.revision)
        self.observed_identity = identity

    def observe(self, session: object) -> None:
        identity = mesh_state_identity(session)
        if (self.observed_mesh is session.working_mesh
                and self.observed_revision == int(session.revision)
                and self.observed_identity == identity):
            return
        self.geometry_revision += 1
        self.weight_revision += 1
        self._record(session, identity)

    def transition(self, session: object, *, before_revision: int, change: str) -> None:
        """Record the result of one serialized, known authoring operation."""
        identity = mesh_state_identity(session)
        if (self.observed_revision != before_revision
                or int(session.revision) not in (before_revision, before_revision + 1)
                or change == "none" and identity != self.observed_identity):
            self.observe(session)
            return
        if int(session.revision) == before_revision and identity == self.observed_identity:
            return
        if change != "none":
            if change != "weights":
                self.geometry_revision += 1
            if change != "geometry":
                self.weight_revision += 1
        old_identity = self.observed_identity
        self._record(session, identity)
        # A presentation or weight edit cannot alter the geometry document.
        # Keep this exact encoding only if the same document channels survived.
        cached = self.document
        if (change in {"none", "weights"} and cached is not None and not cached.pending
                and cached.mesh is session.working_mesh and cached.revision == before_revision
                and (identity == old_identity or change == "weights")):
            cached.revision = int(session.revision)
            cached.identity = identity

    def document_payload(self, session: object, mesh: object) -> PreparedMeshDocument | None:
        self.observe(session)
        cached = self.document
        if cached is None or cached.mesh is not mesh:
            return None
        if cached.pending:
            return None
        if (mesh is session.working_mesh and cached.revision == int(session.revision)
                and cached.identity == self.observed_identity):
            return cached.data
        return None

    def remember_document(self, session: object, mesh: object, data: PreparedMeshDocument) -> None:
        self.observe(session)
        owned = mesh is session.working_mesh
        self.document = _MeshDocument(
            mesh, self.observed_identity if owned else _mesh_identity(mesh), int(session.revision), data, not owned,
        )

    def adopt_prepared_document(self, session: object, prepared: object) -> None:
        """Bind bytes only after this exact prepared replacement was committed."""
        cached = self.document
        if (cached is not None and cached.pending and cached.mesh is prepared.working_mesh
                and session.working_mesh is prepared.working_mesh
                and cached.revision == int(prepared.expected_revision)
                and int(session.revision) == cached.revision + 1
                and cached.identity == _mesh_identity(prepared.working_mesh)):
            cached.pending = False
            cached.revision = int(session.revision)
            cached.identity = mesh_state_identity(session)
        else:
            self.discard_pending_document()

    def discard_pending_document(self) -> None:
        if self.document is not None and self.document.pending:
            self.document = None

    def clear(self) -> None:
        self.observed_mesh = None
        self.observed_identity = None
        self.document = None
        self.capability = None
        self.source_palette = None
        self.source_rows.clear()
        self.skeleton_summary = None
        self.bone_influence = None
