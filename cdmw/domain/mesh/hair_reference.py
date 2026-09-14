"""Join the open face and body surfaces of a neutral fitting mannequin."""
from collections import Counter, defaultdict
import math


def _boundary_loops(triangles):
    edges = Counter(tuple(sorted((a, b))) for face in triangles for a, b in zip(face, (*face[1:], face[0])))
    outgoing = defaultdict(list)
    for face in triangles:
        for a, b in zip(face, (*face[1:], face[0])):
            if edges[tuple(sorted((a, b)))] == 1:
                outgoing[a].append(b)
    loops = []
    while outgoing:
        start = next(iter(outgoing))
        loop, current = [], start
        while current in outgoing:
            loop.append(current)
            options = outgoing[current]
            following = options.pop()
            if not options:
                del outgoing[current]
            current = following
            if current == start:
                if len(loop) >= 3:
                    loops.append(loop)
                break
    return loops


def join_face_reference(positions, triangles, face_count, neck_positions, neck_triangles):
    """Bridge the face perimeter to the body opening, leaving eye/mouth holes.

    PAC seams duplicate vertices for UVs. Weld only this untextured reference,
    then join its two oppositely oriented perimeter loops. Output hair is untouched.
    """
    vertices, ids, remap = [], {}, []
    for point in (*positions, *neck_positions):
        key = tuple(round(float(v), 6) for v in point)
        if key not in ids:
            ids[key] = len(vertices)
            vertices.append(list(point))
        remap.append(ids[key])
    scalp = [[remap[i] for i in face] for face in triangles]
    body = scalp[face_count:] + [[remap[len(positions) + i] for i in face] for face in neck_triangles]
    face_loops, body_loops = _boundary_loops(scalp[:face_count]), _boundary_loops(body)
    if not face_loops or not body_loops:
        return positions, triangles
    distance = lambda a, b: math.dist(vertices[a], vertices[b])
    perimeter = lambda loop: sum(distance(a, b) for a,b in zip(loop, (*loop[1:], loop[0])))
    front = max(face_loops, key=perimeter)
    # The other large body boundary is the cropped torso. Select the opening
    # nearest the face, not the longest body perimeter.
    back = min(body_loops, key=lambda loop: sum(min(distance(a,b) for b in front) for a in loop) / len(loop))
    back = list(reversed(back))
    start = min(range(len(back)), key=lambda i: distance(front[0], back[i]))
    back = back[start:] + back[:start]
    a = b = 0
    bridges = []
    while a < len(front) or b < len(back):
        ai, bi = front[a % len(front)], back[b % len(back)]
        an, bn = front[(a+1) % len(front)], back[(b+1) % len(back)]
        advance_front = a < len(front) and distance(an,bi) <= distance(ai,bn)
        if a == len(front)-1 and b < len(back)-1:
            advance_front = False
        if b == len(back)-1 and a < len(front)-1:
            advance_front = True
        if b == len(back) or advance_front:
            bridges.append([an, ai, bi])
            a += 1
        else:
            bridges.append([ai, bi, bn])
            b += 1
    triangles = [face for face in (*scalp, *bridges) if len(set(face)) == 3]
    used = sorted({i for face in triangles for i in face})
    mapping = {old:new for new,old in enumerate(used)}
    return [vertices[i] for i in used], [[mapping[i] for i in face] for face in triangles]
