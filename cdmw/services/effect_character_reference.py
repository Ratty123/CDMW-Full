"""The character the effect dialog draws behind the item: the game's own, in its own pose.

The dialog needs a body, and a stick figure of the right height answers "how big is this
effect" but not "where will it be". The game's own answer is on disk: the player rig's
`.pab` gives every bone its bind transform, the body socket file gives `RHand_Socket` its
offset from the weapon bone, and the character's low-detail body -- one 800-vertex mesh
with a head, hands and feet -- is ordinary `.pac` geometry in that same bind space.

Two frames meet here and the dialog has to serve both:

* the **item's** frame, which the effect's offset is measured in, because the effect rides
  on the weapon's prefab and moves with it;
* the **character's** frame, which is the one a reader can look at, because a camera has
  an up and a person standing upright is the only pose that reads.

So the scene is the character's frame moved to put the hand at the origin: the body is
translated by minus the socket's world position and left standing, and the item is turned
by the socket's rotation, which is how the game holds it. Item-space numbers reach the
scene through :func:`rotate_point` and drags come back through :func:`unrotate_point`.

Everything here is best effort. An install missing any piece gets no character rather than
an error, and the dialog falls back to the figure it drew before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

__all__ = [
    "CHARACTER_SUBMESH_PREFIX",
    "CharacterReference",
    "build_character_reference",
    "character_reference_from_snapshot",
    "rotate_point",
    "unrotate_point",
    "rotate_mesh",
]

CHARACTER_SUBMESH_PREFIX = "effect_character_"

#: The playable rig a weapon is held by, and the socket it is held in.
_RIG_MODEL = "1_phm"
_HAND_SOCKET = "RHand_Socket"
#: The character's own low-detail body: one mesh, floor to the top of the head, under a
#: thousand vertices. It is what the game draws when the player is far away, so it is the
#: whole figure rather than a piece of one.
_BODY_LOD = "/nude/"
_BODY_LOD_STEM = "_lod_"
#: If that is not there, two armour pieces stand in for a body: the upper and lower halves.
_ARMOUR_SLOTS = ("9_upperbody", "10_lowerbody")
#: A proxy that is neither an accessory nor a show piece, by size order.
_MEDIAN = 0.5

#: The rotation that leaves everything where it is.
IDENTITY_ROTATION: Tuple[float, ...] = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


@dataclass(frozen=True, slots=True)
class CharacterReference:
    """The character standing with the weapon hand at the origin.

    `mesh` is the body, already moved. `item_rotation` is the 3x3 the item and everything
    measured in the item's frame has to be turned by to join it (see :func:`rotate_mesh`).
    """

    mesh: ParsedMesh
    item_rotation: Tuple[float, ...]
    socket: str
    rig: str
    sources: Tuple[str, ...]

    @property
    def submesh_count(self) -> int:
        return len(self.mesh.submeshes)


def _normalize(path: str) -> str:
    return str(path or "").replace("\\", "/").strip("/").lower()


def rotate_point(point: Sequence[float], rotation: Sequence[float]) -> Tuple[float, float, float]:
    """A point in the item's frame, in the scene's. `rotation` is 3x3 row-major, and the
    point is a row vector, which is the convention the archives' matrices are in."""

    x, y, z = float(point[0]), float(point[1]), float(point[2])
    return (
        x * rotation[0] + y * rotation[3] + z * rotation[6],
        x * rotation[1] + y * rotation[4] + z * rotation[7],
        x * rotation[2] + y * rotation[5] + z * rotation[8],
    )


def unrotate_point(point: Sequence[float], rotation: Sequence[float]) -> Tuple[float, float, float]:
    """A point in the scene's frame, back in the item's: a rotation inverts by transposing."""

    x, y, z = float(point[0]), float(point[1]), float(point[2])
    return (
        x * rotation[0] + y * rotation[1] + z * rotation[2],
        x * rotation[3] + y * rotation[4] + z * rotation[5],
        x * rotation[6] + y * rotation[7] + z * rotation[8],
    )


def rotate_mesh(mesh: ParsedMesh, rotation: Sequence[float]) -> ParsedMesh:
    """`mesh` turned into the scene's frame, normals with it, bounds recomputed."""

    from copy import replace as _replace

    rotation = tuple(float(v) for v in rotation)
    if len(rotation) != 9:
        raise ValueError("a rotation is nine numbers")
    submeshes = [
        _replace(
            submesh,
            vertices=[rotate_point(vertex, rotation) for vertex in submesh.vertices],
            normals=[rotate_point(normal, rotation) for normal in (submesh.normals or ())],
        )
        for submesh in mesh.submeshes
    ]
    every = [vertex for submesh in submeshes for vertex in submesh.vertices]
    low = tuple(min(vertex[axis] for vertex in every) for axis in range(3)) if every else mesh.bbox_min
    high = tuple(max(vertex[axis] for vertex in every) for axis in range(3)) if every else mesh.bbox_max
    return _replace(mesh, submeshes=submeshes, bbox_min=low, bbox_max=high)


def _body_mesh_paths(paths: Iterable[str], sizes: Mapping[str, int]) -> List[str]:
    """The meshes to draw as the body: the low-detail whole figure if the archives carry
    it, else one armour piece per half.

    Picking the smallest armour lands on an accessory -- a scrap near one elbow -- and the
    largest on a show piece of several megabytes. The median of the canonically named base
    armour is at least body-shaped.
    """

    paths = list(paths)
    prefix = f"/model/1_pc/{_RIG_MODEL}"
    whole = sorted(
        path for path in paths
        if f"{prefix}{_BODY_LOD}" in path and _BODY_LOD_STEM in path and path.endswith(".pac")
    )
    if whole:
        return [whole[0]]

    chosen: List[str] = []
    for slot in _ARMOUR_SLOTS:
        in_slot = sorted(
            path for path in paths
            if f"/{_RIG_MODEL}/armor/{slot}/" in path and path.endswith(".pac")
            and "_acc" not in path and "_sub" not in path
        )
        if not in_slot:
            continue
        by_size = sorted(in_slot, key=lambda path: int(sizes.get(path, 0) or 0))
        chosen.append(by_size[int(len(by_size) * _MEDIAN)])
    return chosen


def build_character_reference(
    entry_paths: Iterable[str],
    read: Callable[[str], bytes],
    *,
    sizes: Optional[Mapping[str, int]] = None,
    socket_name: str = _HAND_SOCKET,
    max_vertices: int = 60_000,
) -> Optional[CharacterReference]:
    """The player, standing, with `socket_name` at the origin, or None.

    `entry_paths` is every path in the archives and `read` reads one. `sizes` maps a path
    to its stored size, and is only consulted when the low-detail body is missing and
    armour has to stand in for it.
    """

    try:
        from tools.placement_studio.documents import SocketDocument
        from tools.placement_studio.skeleton import BoneHierarchy
    except Exception:  # noqa: BLE001 - the studio's reader is optional; no character without it
        return None

    paths = [_normalize(path) for path in entry_paths]
    rigs = sorted(
        path for path in paths
        if path.endswith(".pab") and f"/model/1_pc/{_RIG_MODEL}/" in path
    )
    sockets = sorted(
        path for path in paths
        if path.endswith(".pab.sockets.xml") and f"/1_pc/{_RIG_MODEL}/" in path
    )
    if not rigs or not sockets:
        return None
    rig = rigs[0]
    stem = rig.rsplit("/", 1)[-1]
    socket_file = next((path for path in sockets if path.rsplit("/", 1)[-1].startswith(stem)), sockets[0])

    try:
        hierarchy = BoneHierarchy.from_pab(read(rig), rig)
        document = SocketDocument.load(read(socket_file), socket_file)
        socket = next((item for item in document.sockets() if item.name == socket_name), None)
        if socket is None:
            return None
        placed = hierarchy.place(socket)
        if not placed.anchored:
            return None
        matrix = tuple(float(v) for v in placed.world_matrix)
        # the item joins the character by the socket's rotation; the character joins the
        # item by giving up the socket's position, which is where the hand is
        rotation = matrix[0:3] + matrix[4:7] + matrix[8:11]
        hand = matrix[12:15]
    except Exception:  # noqa: BLE001 - a rig that does not read leaves the figure in place
        return None

    from cdmw.modding.mesh_parser import parse_mesh

    submeshes: List[SubMesh] = []
    sources: List[str] = []
    total = 0
    for path in _body_mesh_paths(paths, dict(sizes or {})):
        try:
            parsed = parse_mesh(read(path), path.rsplit("/", 1)[-1])
        except Exception:  # noqa: BLE001 - one piece that does not decode is not the end
            continue
        for submesh in tuple(getattr(parsed, "submeshes", ()) or ()):
            vertices = [tuple(vertex[axis] - hand[axis] for axis in range(3)) for vertex in submesh.vertices]
            if not vertices:
                continue
            total += len(vertices)
            if total > max_vertices:
                break
            submeshes.append(
                SubMesh(
                    name=f"{CHARACTER_SUBMESH_PREFIX}{len(submeshes)}",
                    material=f"{CHARACTER_SUBMESH_PREFIX}body",
                    vertices=vertices,
                    uvs=list(submesh.uvs or ()) or [(0.0, 0.0)] * len(vertices),
                    normals=list(submesh.normals or ()) or [(0.0, 1.0, 0.0)] * len(vertices),
                    faces=list(submesh.faces or ()),
                    vertex_count=len(vertices),
                    face_count=len(submesh.faces or ()),
                )
            )
        sources.append(path)
        if total > max_vertices:
            break
    if not submeshes:
        return None

    every = [vertex for submesh in submeshes for vertex in submesh.vertices]
    low = tuple(min(vertex[axis] for vertex in every) for axis in range(3))
    high = tuple(max(vertex[axis] for vertex in every) for axis in range(3))
    mesh = ParsedMesh(
        path=f"{CHARACTER_SUBMESH_PREFIX}reference.pac",
        format="pac",
        submeshes=submeshes,
        bbox_min=low,
        bbox_max=high,
        total_vertices=sum(len(item.vertices) for item in submeshes),
        total_faces=sum(len(item.faces) for item in submeshes),
        has_uvs=True,
        has_bones=False,
    )
    return CharacterReference(
        mesh=mesh, item_rotation=tuple(rotation), socket=socket_name, rig=rig, sources=tuple(sources)
    )


def character_reference_from_snapshot(snapshot) -> Tuple[Optional[CharacterReference], str]:
    """The character out of a new-item snapshot, and one line saying what came of it.

    The snapshot already holds every archive entry and reads any of them, which is all
    :func:`build_character_reference` wants; this is the seam that keeps the studio's
    controller out of the archives.
    """

    try:
        reference = build_character_reference(
            snapshot.entries.keys(),
            snapshot.payload,
            sizes={path: entry.orig_size for path, entry in snapshot.entries.items()},
        )
    except Exception as exc:  # noqa: BLE001 - the stand-in figure is drawn instead
        return None, f"The character for the placement viewport could not be read: {exc}"
    if reference is None:
        return None, "The archives carry no character for the placement viewport; a stand-in figure is drawn."
    return reference, (
        f"Placement viewport: the character is {reference.sources[0].rsplit('/', 1)[-1]} "
        f"held by {reference.socket}."
    )
