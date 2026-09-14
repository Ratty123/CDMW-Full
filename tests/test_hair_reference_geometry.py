from collections import Counter
from cdmw.domain.mesh.hair_reference import join_face_reference, _boundary_loops


def test_fitting_seam_joins_face_to_body_without_closing_facial_holes_or_torso():
    outer = [[-1,-1,0], [1,-1,0], [1,1,0], [-1,1,0]]
    inner = [[-.2,-.2,0], [.2,-.2,0], [.2,.2,0], [-.2,.2,0]]
    vertices = outer + inner
    face = []
    for i in range(4):
        j = (i+1) % 4
        face += [[4+i,j,i], [4+i,4+j,j]]
    for z in (1, 2):
        vertices += [[x,y,z] for x,y,_ in outer]
    body = []
    for i in range(4):
        j = (i+1) % 4
        body += [[8+i,8+j,12+i], [8+j,12+j,12+i]]
    positions, triangles = join_face_reference(vertices, face+body, len(face), [], [])
    assert positions == vertices
    assert triangles[:len(face)] == face
    assert len(triangles) == len(face) + len(body) + 8
    loops = _boundary_loops(triangles)
    assert {frozenset(loop) for loop in loops} == {frozenset(range(4,8)), frozenset(range(12,16))}
    counts = Counter(tuple(sorted((a,b))) for f in triangles for a,b in zip(f, (*f[1:],f[0])))
    assert max(counts.values()) == 2


def test_complete_fitting_head_does_not_gain_an_arbitrary_seam():
    points = [[0,0,0], [1,0,0], [0,1,0], [0,0,1]]
    faces = [[0,2,1], [0,1,3], [1,2,3], [0,3,2]]
    assert join_face_reference(points, faces, len(faces), [], []) == (points,faces)
