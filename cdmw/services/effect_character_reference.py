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

So the scene is the character's frame moved to put the item's own origin there: the body
is translated by minus the attachment's position and left standing, and the item is turned
by the attachment's rotation. Item-space numbers reach the scene through
:func:`rotate_point` and drags come back through :func:`unrotate_point`.

**The attachment is not the body socket alone.** The Placement studio composes it as
`inverse(child socket on the item) . body socket world`, and the child socket carries the
item's orientation: for a one-hand sword it is a quarter turn about y, so a weapon hung on
`RHand_Socket` by itself is held ninety degrees off. Which child socket applies is named by
the item's own prefab (`_socketFileName` points at a `.sockets.xml`, and weapons share
those: sword_0039's prefab names sword_0001's file). Failing that, the frame most of the
weapons of the same kind use stands in, and failing that the item is hung on the body
socket alone and the dialog says so.

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
    "HeldCharacter",
    "build_character_reference",
    "character_reference_from_snapshot",
    "hold_the_item",
    "item_child_frame",
    "rotate_point",
    "unrotate_point",
    "rotate_mesh",
]

CHARACTER_SUBMESH_PREFIX = "effect_character_"

#: The playable rig a weapon is held by, and the socket it is held in.
_RIG_MODEL = "1_phm"
_HAND_SOCKET = "RHand_Socket"
#: The frame on the item that mates with the hand socket. Every shipped weapon socket file
#: that has one calls it this; the descriptor rows pair it with `RHand_Socket` for every
#: held part, sword through war hammer.
_CHILD_SOCKET = "Basic_ChildSocket"
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
    """The character's body as the archives hold it, and where its weapon hand is.

    Both are item-independent, which is what makes this the expensive half worth keeping:
    the body is a mesh read out of the archives, and the hand is a walk of 434 bones.
    """

    #: the body in the rig's own space, standing on the floor
    body: ParsedMesh
    #: the hand socket's world matrix, row-major, sixteen numbers
    body_matrix: Tuple[float, ...]
    socket: str
    rig: str
    sources: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HeldCharacter:
    """The scene: the body moved so the item's origin is the origin, and the turn the item
    takes to be held there."""

    mesh: ParsedMesh
    item_rotation: Tuple[float, ...]
    socket: str
    #: the frame on the item that mated with the socket, "" when none was found
    child_socket: str
    #: where that frame came from: "prefab", "convention", or "" for none at all
    held_from: str
    sources: Tuple[str, ...]

    @property
    def submesh_count(self) -> int:
        return len(self.mesh.submeshes)

    @property
    def body_name(self) -> str:
        """The body mesh's own file name, for a line that says which character this is."""

        return self.sources[0].rsplit("/", 1)[-1] if self.sources else ""


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
        body_matrix = tuple(float(v) for v in placed.world_matrix)
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
            vertices = [tuple(float(value) for value in vertex[:3]) for vertex in submesh.vertices]
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
        body=mesh, body_matrix=body_matrix, socket=socket_name, rig=rig, sources=tuple(sources)
    )


def item_child_frame(
    entry_paths: Iterable[str],
    read: Callable[[str], bytes],
    *,
    prefab_paths: Sequence[str] = (),
    model_folder: str = "",
    child_socket: str = _CHILD_SOCKET,
) -> Tuple[Optional[Tuple[float, ...]], str, str]:
    """The frame on the item that mates with the hand socket: (matrix, socket name, where).

    A weapon prefab names the socket file it uses in `_socketFileName`, and several weapons
    share one file, so the prefab is the only thing that says which applies. When there is
    no prefab to read, the frame most of the weapons of the same kind use stands in: the
    rotation is the same quarter turn on nearly all of them and only the offset along the
    grip differs, so the pose is right and the grip may be a few centimetres out.
    """

    try:
        from tools.placement_studio.documents import SocketDocument
        from tools.placement_studio.skeleton import invert_rigid
    except Exception:  # noqa: BLE001 - without the studio's reader there is no frame to find
        return None, "", ""

    paths = [_normalize(path) for path in entry_paths]
    known = set(paths)

    def frame_in(socket_file: str) -> Optional[Tuple[float, ...]]:
        if socket_file not in known:
            return None
        try:
            document = SocketDocument.load(read(socket_file), socket_file)
        except Exception:  # noqa: BLE001 - an unreadable socket file is no frame
            return None
        found = next((item for item in document.sockets() if item.name == child_socket), None)
        if found is None:
            return None
        return tuple(float(v) for v in invert_rigid(found.rotation, found.translation))

    # the item's own answer: its prefab names the file. The sheathed prefab describes the
    # item on the character's back, so the held one is preferred.
    for prefab in sorted((_normalize(p) for p in prefab_paths if p), key=lambda p: ("_in" in p, p)):
        if prefab not in known:
            continue
        try:
            named = _socket_files_named_in(read(prefab))
        except Exception:  # noqa: BLE001 - an unreadable prefab is not an error here
            continue
        for socket_file in named:
            matrix = frame_in(socket_file)
            if matrix is not None:
                return matrix, child_socket, "prefab"

    # what the weapons of this kind do, by weight of numbers
    kind = _normalize(model_folder).rstrip("/").split("/model/")[-1]
    if kind:
        from collections import Counter

        tally: Counter = Counter()
        for socket_file in sorted(path for path in paths if path.endswith(".sockets.xml") and f"/socketbonedata/{kind}/" in path):
            matrix = frame_in(socket_file)
            if matrix is not None:
                tally[matrix] += 1
        if tally:
            return tally.most_common(1)[0][0], child_socket, "convention"
    return None, "", ""


def _socket_files_named_in(prefab: bytes) -> List[str]:
    """Every `.sockets.xml` a prefab names, in the order it names them.

    The prefab is a binary object graph and this only wants one string out of it, so it is
    read as strings rather than parsed: a path is printable and ends in a known suffix.
    """

    import re

    found: List[str] = []
    for match in re.findall(rb"[\x20-\x7e]{8,}", prefab):
        text = match.decode("ascii", "replace")
        for candidate in re.findall(r"[A-Za-z0-9_/\\.\-]+\.sockets\.xml", text):
            normalized = _normalize(candidate)
            if normalized not in found:
                found.append(normalized)
    return found


def hold_the_item(
    reference: CharacterReference,
    child_frame: Optional[Sequence[float]] = None,
    *,
    child_socket: str = "",
    held_from: str = "",
    max_vertices: int = 60_000,
) -> HeldCharacter:
    """Stand `reference`'s body around an item whose origin is the origin.

    The attachment is `child_frame . body_matrix`, the studio's own composition. The body
    gives up that matrix's translation and keeps standing; the item, which the caller turns
    with :func:`rotate_mesh`, takes its rotation.
    """

    from copy import replace as _replace

    from tools.placement_studio.skeleton import multiply

    attachment = tuple(float(v) for v in reference.body_matrix)
    if child_frame is not None:
        attachment = tuple(float(v) for v in multiply(tuple(float(v) for v in child_frame), attachment))
    rotation = attachment[0:3] + attachment[4:7] + attachment[8:11]
    origin = attachment[12:15]

    submeshes = [
        _replace(
            submesh,
            vertices=[tuple(vertex[axis] - origin[axis] for axis in range(3)) for vertex in submesh.vertices],
        )
        for submesh in reference.body.submeshes
    ]
    every = [vertex for submesh in submeshes for vertex in submesh.vertices]
    mesh = _replace(
        reference.body,
        submeshes=submeshes,
        bbox_min=tuple(min(vertex[axis] for vertex in every) for axis in range(3)) if every else reference.body.bbox_min,
        bbox_max=tuple(max(vertex[axis] for vertex in every) for axis in range(3)) if every else reference.body.bbox_max,
    )
    return HeldCharacter(
        mesh=mesh, item_rotation=tuple(rotation), socket=reference.socket,
        child_socket=child_socket if child_frame is not None else "",
        held_from=held_from if child_frame is not None else "",
        sources=reference.sources,
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
    return reference, ""


def held_character_from_snapshot(
    snapshot,
    reference: Optional[CharacterReference],
    *,
    prefab_paths: Sequence[str] = (),
    model_folder: str = "",
) -> Tuple[Optional["HeldCharacter"], str]:
    """`reference` holding this item, and one line saying how it is held.

    Split from :func:`character_reference_from_snapshot` because the halves cost different
    things: the body is a mesh and a 434-bone walk, read once, while the frame the item
    mates by is one prefab and one small XML, read per item.
    """

    if reference is None:
        return None, ""
    try:
        child, child_socket, held_from = item_child_frame(
            snapshot.entries.keys(), snapshot.payload,
            prefab_paths=prefab_paths, model_folder=model_folder,
        )
        held = hold_the_item(reference, child, child_socket=child_socket, held_from=held_from)
    except Exception as exc:  # noqa: BLE001 - the stand-in figure is drawn instead
        return None, f"The character for the placement viewport could not be read: {exc}"
    body = held.body_name
    if held.held_from == "prefab":
        return held, f"Placement viewport: {body} holds the item at {held.socket}, mated by the item's own {held.child_socket}."
    if held.held_from == "convention":
        return held, (
            f"Placement viewport: {body} holds the item at {held.socket}, mated by the {held.child_socket} that most "
            "weapons of this kind use, because the item's own prefab named no socket file."
        )
    return held, (
        f"Placement viewport: {body} holds the item at {held.socket} with no mating frame, so the angle it is held "
        "at may be a quarter turn off."
    )
