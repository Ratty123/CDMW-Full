"""Bounded particle mesh geometry for the Rust effect descriptor."""
from __future__ import annotations

import math
import random
from dataclasses import replace

from cdmw.domain.cancellation import RunCancelled

MAX_VERTICES = 4096
MAX_FACES = 2048


def sample_spawn_surface(parsed, count, check_cancelled=lambda: None):
    """Area-weighted triangle samples with bounded memory and stable positions."""
    def triangles():
        for submesh in getattr(parsed, 'submeshes', ()):
            vertices = getattr(submesh, 'vertices', ())
            for index, face in enumerate(getattr(submesh, 'faces', ())):
                if index % 1024 == 0:
                    check_cancelled()
                if len(face) != 3 or any(i < 0 or i >= len(vertices) for i in face):
                    continue
                a, b, c = (tuple(float(v) for v in vertices[i][:3]) for i in face)
                if not all(math.isfinite(v) for p in (a,b,c) for v in p):
                    continue
                u, v = tuple(y-x for x,y in zip(a,b)), tuple(y-x for x,y in zip(a,c))
                cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
                area = math.sqrt(sum(x*x for x in cross)) * .5
                if area > 1e-12:
                    yield area, a, b, c
    total = sum(area for area, *_ in triangles())
    if total <= 0 or count <= 0:
        return ()
    rng = random.Random(0)
    targets = sorted(rng.random() * total for _ in range(min(count, 1024)))
    result, end, picked = [], 0., 0
    for area, a, b, c in triangles():
        end += area
        while picked < len(targets) and targets[picked] <= end:
            u = math.sqrt(rng.random())
            v = rng.random()
            result.append(tuple((1-u)*x + u*(1-v)*y + u*v*z for x,y,z in zip(a,b,c)))
            picked += 1
        if picked == len(targets):
            break
    return tuple(result)


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
