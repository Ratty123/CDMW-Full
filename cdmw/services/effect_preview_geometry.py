"""Bounded particle mesh geometry for the Rust effect descriptor."""
from __future__ import annotations

import math
from dataclasses import replace

from cdmw.domain.cancellation import RunCancelled

MAX_VERTICES = 4096
MAX_FACES = 2048


def particle_geometry(parsed):
    """Keep complete triangles and UVs, rejecting oversized or invalid geometry."""
    vertices, uvs, faces = [], [], []
    for submesh in getattr(parsed, "submeshes", ()):
        source = getattr(submesh, "vertices", ())
        triangles = getattr(submesh, "faces", ())
        if len(vertices) + len(source) > MAX_VERTICES or len(faces) + len(triangles) > MAX_FACES:
            raise ValueError("particle mesh exceeds the preview geometry budget")
        offset = len(vertices)
        texcoords = getattr(submesh, "uvs", ())
        for index, vertex in enumerate(source):
            point = tuple(float(v) for v in vertex[:3])
            uv = tuple(float(v) for v in texcoords[index][:2]) if index < len(texcoords) else (0.0, 0.0)
            if len(point) != 3 or len(uv) != 2 or not all(math.isfinite(v) for v in point + uv):
                raise ValueError("particle mesh has invalid coordinates")
            vertices.append(point)
            uvs.append(uv)
        for face in triangles:
            if len(face) != 3 or any(int(i) != i or i < 0 or i >= len(source) for i in face):
                raise ValueError("particle mesh has invalid triangle indices")
            faces.append(tuple(offset + int(i) for i in face))
    if not faces:
        raise ValueError("particle mesh has no triangles")
    return tuple(vertices), tuple(uvs), tuple(faces)


def load_particle_geometry(preview, snapshot, parser, check_cancelled):
    """Read each referenced particle mesh once on the existing worker lane."""
    cache = {}
    emitters = []
    notes = list(preview.notes)
    for emitter in preview.emitters:
        check_cancelled()
        if emitter.kind != "mesh" or not emitter.mesh:
            emitters.append(emitter)
            continue
        path = emitter.mesh.lstrip("/")
        if path not in cache:
            try:
                if not snapshot.has_entry(path):
                    raise ValueError("mesh is not present in the archives")
                payload = snapshot.payload(path)
                check_cancelled()
                parsed = parser(payload, path.rsplit("/", 1)[-1])
                check_cancelled()
                cache[path] = particle_geometry(parsed)
            except RunCancelled:
                raise
            except Exception as exc:  # A missing mesh must not hide other emitters.
                cache[path] = None
                notes.append(f"{emitter.name}: particle geometry unavailable ({exc})")
        geometry = cache[path]
        if geometry is not None:
            emitter = replace(emitter, particle_vertices=geometry[0], particle_uvs=geometry[1], particle_faces=geometry[2])
        elif emitter.texture:
            emitter = replace(emitter, kind="billboard")
        emitters.append(emitter)
    return replace(preview, emitters=tuple(emitters), notes=tuple(notes))
