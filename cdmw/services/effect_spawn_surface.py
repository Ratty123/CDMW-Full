"""Complete static surfaces for decoded GPU particle spawning, prepared off-thread."""
from __future__ import annotations

import math
import struct


def spawn_surface_geometry(parsed, check_cancelled=lambda: None):
    """Retain triangle order and normals; never replace a missing surface with a point.

    The GPU stream-out tables hold up to 524,288 entries and half-float areas.
    A character stand-in is not an authored surface and must not be passed here.
    """
    vertices, normals, faces, areas = [], [], [], []
    for submesh in getattr(parsed, "submeshes", ()):
        source = getattr(submesh, "vertices", ())
        triangles = getattr(submesh, "faces", ())
        if len(vertices) + len(source) > 524288 or len(faces) + len(triangles) > 524288:
            raise ValueError("spawn surface exceeds the GPU surface table limit")
        offset = len(vertices)
        source_normals = getattr(submesh, "normals", ())
        accumulated = [[0., 0., 0.] for _ in source]
        for index, vertex in enumerate(source):
            if index % 1024 == 0:
                check_cancelled()
            point = tuple(float(v) for v in vertex[:3])
            if len(point) != 3 or not all(math.isfinite(v) for v in point):
                raise ValueError("spawn surface has invalid positions")
            vertices.append(point)
        for index, face in enumerate(triangles):
            if index % 1024 == 0:
                check_cancelled()
            if len(face) != 3 or any(int(i) != i or i < 0 or i >= len(source) for i in face):
                raise ValueError("spawn surface has invalid triangle indices")
            a, b, c = (vertices[offset + i] for i in face)
            u, v = tuple(y-x for x, y in zip(a, b)), tuple(y-x for x, y in zip(a, c))
            cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
            area = math.sqrt(sum(x*x for x in cross)) * .5
            areas.append(struct.unpack("<e", struct.pack("<e", min(area, 65504.)))[0])
            faces.append(tuple(offset + int(i) for i in face))
            for i in face:
                for axis in range(3):
                    accumulated[i][axis] += cross[axis]
        for index, derived in enumerate(accumulated):
            normal = tuple(float(v) for v in source_normals[index][:3]) if index < len(source_normals) else tuple(derived)
            if len(normal) != 3 or not all(math.isfinite(v) for v in normal):
                raise ValueError("spawn surface has invalid normals")
            length = math.sqrt(sum(v*v for v in normal))
            normals.append(tuple(v / length for v in normal) if length > 1e-12 else (0., 1., 0.))
    if not faces:
        raise ValueError("spawn surface has no triangles")
    return {"vertices": vertices, "normals": normals, "faces": faces, "areas": areas}
