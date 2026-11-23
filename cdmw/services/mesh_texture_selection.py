"""Which faces of the open mesh sample a texture, and the texture pixels they cover.

The Mesh Editor's docked Texture Editor turns the 3D selection into a texture selection
(Select From Mesh Selection), and the CDMW MCP reads back which faces a pixel or the
texture selection covers (``textures.mesh_at``). Both take a :class:`TextureMeshSnapshot`
on the UI thread, where the editing session lives, and do the pixel work on any thread.

The parts that sample a texture come from the materials the editor draws now (the
session's active material payload), for the LOD it shows: the same source as
``mesh.state``'s texture coverage. The UV rules are :mod:`cdmw.domain.textures.uv_selection`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

import numpy as np

from cdmw.domain.textures.uv_selection import UvMaskReport, UvPart, uv_faces_covering, uv_faces_mask

#: Roles the 3D view repeats over the surface at a scale of their own: one of their
#: pixels has no one place on the model.
DETAIL_ROLES = frozenset({"detail", "skin_detail_mask", "skin_detail_normal", "skin_detail_material"})
#: Layered-material textures: the shader may repeat them at the layer's own scale.
LAYER_ROLES = frozenset({"layer"})
#: Face numbers listed per part in an answer, at most.
FACE_LIST_LIMIT = 2000
_LAYER_RESOURCES = ("diffuse", "normal", "material", "height", "mask")


def tr(text: str) -> str:
    """Mark a message the interface shows: the localization manifest makes it a catalogue key,
    and the panel translates it when it shows it. MCP answers keep the English."""

    return text


class TextureMeshRefusal(ValueError):
    """Why the mesh selection cannot become a selection on this texture."""


@dataclass(frozen=True, slots=True)
class TextureMeshSnapshot:
    """The mesh, the texture's parts and the 3D selection, copied on the UI thread."""

    texture: str
    role: str
    lod_index: int
    parts: tuple[UvPart, ...]
    #: Every part of the mesh, by number: its name.
    part_names: Mapping[int, str]
    #: The faces to select, by part (None: all of its faces). Only parts that use the texture.
    chosen: Mapping[int, Optional[tuple[int, ...]]]
    #: What the choice came from: "faces", "vertices", "parts" or "part_ids".
    source: str = "faces"
    #: Selected faces on parts that do not use the texture: part -> face count.
    ignored: Mapping[int, int] = field(default_factory=dict)

    @property
    def texture_parts(self) -> tuple[int, ...]:
        return tuple(part.part for part in self.parts)

    def names(self, parts: Iterable[int]) -> str:
        return ", ".join(self.part_names.get(part) or f"Part {part + 1}" for part in parts)


@dataclass(frozen=True, slots=True)
class TextureMeshSelection:
    """The pixels a snapshot's faces cover, and what to tell the user about them."""

    mask: np.ndarray
    report: UvMaskReport
    #: Faces outside the choice whose pixels the mask also covers (mirrored or
    #: overlapping UVs): part -> face count. Painting the selection changes them too.
    shared: Mapping[int, int]
    pixels: int
    notes: tuple[str, ...]


def _sha(reference: object) -> str:
    return str(reference.get("sha256", "") or "").strip().lower() if isinstance(reference, Mapping) else ""


def parts_sampling_texture(material_payload: Mapping[str, object], source_sha256: str,
                           lod_index: int) -> tuple[int, ...]:
    """The parts of one LOD whose materials draw the texture with this hash."""

    wanted = str(source_sha256 or "").strip().lower()
    found: set[int] = set()
    if not wanted:
        return ()
    for row in material_payload.get("textures", ()) or ():
        if not isinstance(row, Mapping) or _sha(row.get("file")) != wanted:
            continue
        levels = tuple(row.get("material_indices_by_lod", ()) or ())
        if 0 <= lod_index < len(levels):
            found.update(int(index) for index in tuple(levels[lod_index] or ()))
    graph = material_payload.get("preview_core_material_graph")
    for material in (graph.get("materials", ()) or ()) if isinstance(graph, Mapping) else ():
        if not isinstance(material, Mapping) or int(material.get("lod_index", 0) or 0) != lod_index:
            continue
        if any(isinstance(layer, Mapping) and _sha(layer.get(resource)) == wanted
               for layer in material.get("layers", ()) or () for resource in _LAYER_RESOURCES):
            found.add(int(material.get("material_index", -1)))
    return tuple(sorted(index for index in found if index >= 0))


def _flips(material_payload: Mapping[str, object], lod_index: int) -> dict[int, bool]:
    flips: dict[int, bool] = {}
    for row in material_payload.get("material_presentations", ()) or ():
        if isinstance(row, Mapping) and int(row.get("lod_index", 0) or 0) == lod_index:
            flips[int(row.get("material_index", -1))] = bool(row.get("texture_flip_vertical", False))
    return flips


def _items(pairs: object) -> dict[int, tuple]:
    return {int(part): tuple(items or ()) for part, items in (pairs or ())}


def _faces_from_vertices(faces: np.ndarray, vertices: Sequence[int]) -> tuple[int, ...]:
    if not len(faces) or not vertices:
        return ()
    chosen = np.zeros(int(faces.max()) + 1, dtype=bool)
    picked = np.asarray([v for v in vertices if 0 <= int(v) < len(chosen)], dtype=np.int64)
    chosen[picked] = True
    return tuple(int(i) for i in np.flatnonzero(chosen[faces].all(axis=1)))


def snapshot_texture_mesh(session: object, source_sha256: str, *, texture: str, role: str = "",
                          part_ids: Optional[Sequence[int]] = None, every_face: bool = False,
                          fallback_parts: Sequence[int] = ()) -> TextureMeshSnapshot:
    """Copy what the selection needs from a Rust Mesh Editor session. Call on the UI thread.

    ``part_ids`` chooses whole parts instead of the 3D selection; ``every_face`` chooses every
    face of the texture's parts (for reading back what a pixel covers). ``fallback_parts`` are
    the Textures panel's parts for this texture, used only when the session names none."""

    role_key = str(role or "").strip().casefold()
    if role_key in DETAIL_ROLES:
        raise TextureMeshRefusal(tr(
            f"{texture} is a detail texture: the 3D view repeats it over the surface at its own "
            "scale, so its pixels have no one place on the model. Open the part's base colour, "
            "normal or mask texture instead."))
    service = getattr(session, "shadow_service", None)
    session_id = getattr(session, "shadow_session_id", None)
    if service is None or session_id is None or getattr(session, "closed", False):
        raise TextureMeshRefusal(tr("Open the mesh in the Mesh Editor first."))
    try:
        view = service.session_view(session_id)
        mesh = service.working_mesh(session_id)
    except (KeyError, RuntimeError) as exc:
        raise TextureMeshRefusal(str(exc) or tr("The Mesh Editor session is closing.")) from None
    lod_index = int(getattr(view, "lod_index", 0) or 0)
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    names = {index: str(getattr(part, "name", "") or "") for index, part in enumerate(submeshes)}
    cache = getattr(session, "archive_refit_material_cache", None) or {}
    payload = cache.get(getattr(session, "active_material_key", "base")) or {}
    using = parts_sampling_texture(payload, source_sha256, lod_index) or tuple(sorted(set(fallback_parts)))
    using = tuple(index for index in using if 0 <= index < len(submeshes))
    if not using:
        raise TextureMeshRefusal(tr(f"No part of this mesh draws {texture} in LOD {lod_index}."))
    flips = _flips(payload, lod_index)
    parts = []
    faces_of: dict[int, np.ndarray] = {}
    for index in using:
        part = submeshes[index]
        faces = np.asarray(part.faces, dtype=np.int64).reshape(-1, 3) if len(part.faces) else np.zeros((0, 3), np.int64)
        uvs = np.asarray(part.uvs, dtype=np.float64).reshape(-1, 2) if len(part.uvs) else np.zeros((0, 2))
        faces_of[index] = faces
        flip = flips.get(index, bool(getattr(part, "preview_texture_flip_vertical", False)))
        parts.append(UvPart(index, uvs, faces, flip_v=flip))
    by_name = TextureMeshSnapshot(texture, role_key, lod_index, tuple(parts), names, {})

    if every_face:
        return TextureMeshSnapshot(texture, role_key, lod_index, tuple(parts), names,
                                   {index: None for index in using}, "every_face")
    if part_ids is not None:
        wanted = tuple(dict.fromkeys(int(index) for index in part_ids))
        missing = [index for index in wanted if not 0 <= index < len(submeshes)]
        if missing:
            raise TextureMeshRefusal(tr(f"The mesh has parts 0 to {len(submeshes) - 1}."))
        chosen = {index: None for index in wanted if index in using}
        if not chosen:
            raise TextureMeshRefusal(tr(
                f"{by_name.names(wanted)} do not use {texture}. It is used by: {by_name.names(using)}."))
        ignored = {index: len(submeshes[index].faces) for index in wanted if index not in using}
        return TextureMeshSnapshot(texture, role_key, lod_index, tuple(parts), names, chosen, "part_ids", ignored)

    selection = view.selection
    whole = {int(index) for index in getattr(selection, "source_indices", ()) or ()}
    faces_by_part = _items(getattr(selection, "faces_by_submesh", ()))
    vertices_by_part = _items(getattr(selection, "vertices_by_submesh", ()))
    for part, edges in _items(getattr(selection, "edges_by_submesh", ())).items():
        vertices_by_part.setdefault(part, ())
        vertices_by_part[part] = tuple({*vertices_by_part[part], *(v for edge in edges for v in edge)})
    selected_parts = whole | set(faces_by_part) | set(vertices_by_part)
    if not selected_parts:
        raise TextureMeshRefusal(tr(
            "Nothing is selected in the 3D view. Select faces (or vertices) on the model, or a part "
            "in the Parts list, then try again."))
    chosen: dict[int, Optional[tuple[int, ...]]] = {}
    sources: set[str] = set()
    ignored: dict[int, int] = {}
    for part in sorted(selected_parts):
        if part in whole:
            picked, kind = None, "parts"
        elif faces_by_part.get(part):
            picked, kind = tuple(int(face) for face in faces_by_part[part]), "faces"
        else:
            faces = faces_of.get(part)
            if faces is None and 0 <= part < len(submeshes):
                faces = np.asarray(submeshes[part].faces, dtype=np.int64).reshape(-1, 3)
            picked = _faces_from_vertices(faces, vertices_by_part.get(part, ())) if faces is not None else ()
            kind = "vertices"
        if part not in using:
            count = len(submeshes[part].faces) if picked is None and 0 <= part < len(submeshes) else len(picked or ())
            if count:
                ignored[part] = count
            continue
        if picked is None or picked:
            chosen[part] = picked
            sources |= {kind}
    if not chosen:
        if ignored:
            raise TextureMeshRefusal(tr(
                f"The selected faces do not use {texture}: they are on {by_name.names(ignored)}. "
                f"{texture} is used by: {by_name.names(using)}."))
        raise TextureMeshRefusal(tr(
            "The selection holds no whole face: select faces, or every corner of the faces you want."))
    source = "faces" if sources == {"faces"} else "+".join(sorted(sources))
    return TextureMeshSnapshot(texture, role_key, lod_index, tuple(parts), names, chosen, source, ignored)


def build_texture_mesh_selection(snapshot: TextureMeshSnapshot, width: int, height: int, *,
                                 grow: int = 0) -> TextureMeshSelection:
    """The snapshot's faces as a 0/255 mask the texture's size. Safe off the UI thread."""

    mask, report = uv_faces_mask(width, height, snapshot.parts, snapshot.chosen)
    if not mask.any():
        raise TextureMeshRefusal(tr(f"The selected faces have no UVs on {snapshot.texture}."))
    # The other faces that sample the faces' own pixels: strictly inside them, so a neighbour
    # across a shared edge is not one, and before Grow, which reaches into neighbours on purpose.
    covering = uv_faces_covering(width, height, snapshot.parts, mask=mask, strict=True,
                                 faces_by_part={part.part: None for part in snapshot.parts})
    if grow > 0:
        from cdmw.core import image_ops

        mask = image_ops.dilate_ellipse(mask, int(grow) * 2 + 1)
    shared: dict[int, int] = {}
    for part, faces in covering.items():
        picked = snapshot.chosen.get(part, ())
        if picked is None:
            continue
        others = len(set(faces) - set(picked or ()))
        if others:
            shared[part] = others
    notes = []
    if snapshot.ignored:
        notes.append(tr(f"Left out {sum(snapshot.ignored.values())} selected faces on "
                        f"{snapshot.names(snapshot.ignored)}, which do not use {snapshot.texture}."))
    if shared:
        notes.append(tr(f"{sum(shared.values())} faces outside the selection share these pixels (mirrored or "
                        "overlapping UVs): painting the selection changes them too."))
    if report.wrapped_faces:
        notes.append(tr(f"{report.wrapped_faces} faces have UVs outside 0-1; they repeat the texture, so their "
                        "pixels were wrapped onto it."))
    left_out = report.skipped_faces + report.too_many_repeats
    if left_out:
        notes.append(tr(f"{left_out} faces were left out: their UVs are unusable or repeat the texture more "
                        "than 64 times."))
    if snapshot.role in LAYER_ROLES:
        notes.append(tr("This is a material layer texture: the shader may repeat it at the layer's own scale, "
                        "so check the result on the model."))
    return TextureMeshSelection(mask, report, shared, int(np.count_nonzero(mask)), tuple(notes))


def faces_answer(snapshot: TextureMeshSnapshot, faces: Mapping[int, Sequence[int]]) -> list[dict[str, object]]:
    """Faces by part as an answer: each part's name, face count, whether that is all of its
    faces, and the face numbers (at most FACE_LIST_LIMIT)."""

    totals = {part.part: len(part.faces) for part in snapshot.parts}
    rows = []
    for part in sorted(faces):
        listed = list(faces[part])
        rows.append({"part": part, "name": snapshot.part_names.get(part, ""), "faces": len(listed),
                     "whole_part": len(listed) == totals.get(part, -1),
                     "face_ids": listed[:FACE_LIST_LIMIT], "listed_all": len(listed) <= FACE_LIST_LIMIT})
    return rows


__all__ = ["DETAIL_ROLES", "FACE_LIST_LIMIT", "LAYER_ROLES", "TextureMeshRefusal", "TextureMeshSelection",
           "TextureMeshSnapshot", "build_texture_mesh_selection", "faces_answer", "parts_sampling_texture",
           "snapshot_texture_mesh"]
